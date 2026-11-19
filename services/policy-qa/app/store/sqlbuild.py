"""SQL 构造:纯函数,不碰连接,可单测。风格对齐 pipeline 侧 sync/pg_writer.py。

列名是 Prisma 默认 camelCase,必须带双引号。表结构以 pipeline 的 pg_writer.py 为准
(HANDOFF §2.1),本服务只读,任何时候都不写。

纪律:所有用户可控的值一律走 psycopg2 参数,SQL 文本里只拼固定片段与参数名。
"""
from __future__ import annotations

import json

from . import IMPORTANCE_ORDER, tokenize_keyword

#: 检索用列——**不含 content**。全库粗滤要把候选行都取回 Python 侧做
#: business_line 过滤与 total 统计,带上正文会到几十 MB。
SEARCH_COLUMNS = (
    '"pipelinePid", "title", "docNumber", "issuer", "issueDate", '
    '"region", "level", "importance", "pipelineThemes", "pipelineImpact", "sourceUrl"'
)

DETAIL_COLUMNS = SEARCH_COLUMNS + ', "content", "pipelineScores", "syncedAt"'

#: 粗滤结果的硬上限。库约 1500 篇,正常不会触顶;防的是过滤条件全空时的病态内存。
SEARCH_ROW_CAP = 5000


def _like(value: str) -> str:
    """子串匹配参数。% 和 _ 是 LIKE 元字符,转义后按字面量匹配。"""
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


#: 本服务读到的所有列。启动自检拿它跟 information_schema 对,缺了直接不启动。
#: 与 SEARCH_COLUMNS/DETAIL_COLUMNS 手工同步——那两个是拼进 SQL 的字符串,
#: 从里面反解列名比重复列一遍更容易出错。
REQUIRED_POLICY_COLUMNS = (
    "pipelinePid", "title", "docNumber", "issuer", "issueDate", "region",
    "level", "importance", "pipelineThemes", "pipelineImpact", "sourceUrl",
    "content", "pipelineScores", "syncedAt",
    # 只有 region_keyword 检索会用到,所以它缺失时前几轮检索照样成功,
    # 直到模型问了个带地区的问题才炸——2026-08-18 线上就是这么misleading。
    "adcode",
)


def build_required_columns_sql() -> tuple[str, dict]:
    """查 Policy 表实际有哪些列。启动自检用。"""
    sql = (
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = 'Policy'"
    )
    return sql, {}


def build_search_sql(
    *,
    keyword: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    region_keyword: str | None = None,
    min_importance: str | None = None,
    issuer_keyword: str | None = None,
    theme_id: str | None = None,
    primary_theme_only: bool = False,
) -> tuple[str, dict]:
    """粗滤 SQL。

    business_line 过滤**不在这里**:它要解析 pipelineImpact 这个存 JSON 的 text 列,
    解析失败必须静默跳过而不是让整条查询失败,所以放 Python 侧(两 adapter 共用
    impact_match,保证 vault/pg 语义一致)。
    """
    where = ['"pipelinePid" IS NOT NULL']  # 排除人工录入行,只认 pipeline 投影
    params: dict = {}

    for idx, token in enumerate(tokenize_keyword(keyword)):
        name = f"kw{idx}"
        where.append(f'("title" ILIKE %({name})s OR "docNumber" ILIKE %({name})s)')
        params[name] = _like(token)

    if date_from:
        where.append('"issueDate" >= %(date_from)s')
        params["date_from"] = date_from
    if date_to:
        where.append('"issueDate" <= %(date_to)s')
        params["date_to"] = date_to

    if region_keyword:
        where.append(
            '("region" ILIKE %(region_kw)s OR "adcode" ILIKE %(region_kw)s '
            'OR "level" = %(region_exact)s)'
        )
        params["region_kw"] = _like(region_keyword)
        params["region_exact"] = region_keyword

    if issuer_keyword:
        # issuer 列全库约 38% 为空,机关往往只写在标题里(如"财政部 税务总局关于……"),
        # 只匹配 issuer 会静默漏掉三分之一的库。两处任一命中即算。
        where.append('("issuer" ILIKE %(issuer_kw)s OR "title" ILIKE %(issuer_kw)s)')
        params["issuer_kw"] = _like(issuer_keyword)

    if theme_id:
        # pipelineThemes 是 jsonb 数组 [{id,isPrimary,isComprehensive}],用包含判定。
        # primary_only 时把 isPrimary:true 一起放进判定对象——jsonb 的 @> 是
        # "被包含对象的每个键值都要匹配",所以这一个操作符就够,不用拆两条件。
        probe: dict = {"id": theme_id}
        if primary_theme_only:
            probe["isPrimary"] = True
        where.append('"pipelineThemes" @> %(theme_json)s::jsonb')
        params["theme_json"] = json.dumps([probe], ensure_ascii=False)

    if min_importance:
        floor = IMPORTANCE_ORDER.get(min_importance, 0)
        allowed = tuple(k for k, v in IMPORTANCE_ORDER.items() if v >= floor)
        where.append('"importance"::text IN %(importances)s')
        params["importances"] = allowed

    sql = (
        f'SELECT {SEARCH_COLUMNS} FROM "Policy" '
        f"WHERE {' AND '.join(where)} "
        f'ORDER BY "issueDate" DESC NULLS LAST, "pipelinePid" ASC '
        f"LIMIT {SEARCH_ROW_CAP}"
    )
    return sql, params


def build_get_policy_sql(pid: str) -> tuple[str, dict]:
    sql = (
        f'SELECT {DETAIL_COLUMNS} FROM "Policy" '
        'WHERE "pipelinePid" = %(pid)s LIMIT 1'
    )
    return sql, {"pid": pid}


def build_relations_sql(pid: str) -> tuple[str, dict]:
    """出向 + 入向一次取回。

    关系表两端存的是 Policy.id(cuid),不是 pid,所以两侧都要 JOIN 回 Policy 换 pid。
    """
    sql = (
        'SELECT \'outbound\' AS direction, r."relationType", '
        'p2."pipelinePid" AS other_pid, p2."title" AS other_title, '
        'r."evidence", r."confidence" '
        'FROM "PolicySemanticRelation" r '
        'JOIN "Policy" p1 ON p1."id" = r."fromPolicyId" '
        'JOIN "Policy" p2 ON p2."id" = r."toPolicyId" '
        'WHERE p1."pipelinePid" = %(pid)s '
        "UNION ALL "
        'SELECT \'inbound\' AS direction, r."relationType", '
        'p1."pipelinePid" AS other_pid, p1."title" AS other_title, '
        'r."evidence", r."confidence" '
        'FROM "PolicySemanticRelation" r '
        'JOIN "Policy" p1 ON p1."id" = r."fromPolicyId" '
        'JOIN "Policy" p2 ON p2."id" = r."toPolicyId" '
        'WHERE p2."pipelinePid" = %(pid)s '
        "ORDER BY 1, 2"
    )
    return sql, {"pid": pid}


def build_commentary_sql(pid: str) -> tuple[str, dict]:
    """relatedPolicyPids 是 jsonb 数组,用 @> 包含判定。pid 走参数,不拼字符串。"""
    sql = (
        'SELECT "commentaryId", "title", "signalRole", "evidence", '
        '"sourceAccount", "businessTag", "confidence" '
        'FROM "CommentarySignal" '
        'WHERE "relatedPolicyPids" @> %(pid_json)s::jsonb '
        'ORDER BY "confidence" DESC NULLS LAST, "commentaryId" ASC'
    )
    return sql, {"pid_json": json.dumps([pid], ensure_ascii=False)}


def build_themes_sql() -> tuple[str, dict]:
    """主题登记表。heng 已经把 vault 的 _meta/themes_registry.yaml 投影成
    KnowledgeTheme,所以取主题体系不需要另开数据通道。"""
    sql = (
        'SELECT "id", "name", "aliases", "count" FROM "KnowledgeTheme" '
        'ORDER BY "count" DESC NULLS LAST, "id" ASC'
    )
    return sql, {}


def build_stats_sql() -> tuple[str, dict]:
    sql = (
        'SELECT COUNT(*) AS n, MAX("issueDate") AS latest_issue_date, '
        'MAX("syncedAt") AS latest_synced_at '
        'FROM "Policy" WHERE "pipelinePid" IS NOT NULL'
    )
    return sql, {}
