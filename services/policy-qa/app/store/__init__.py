"""Store 契约:检索层对外的唯一形状。

两个 adapter(pg / vault)必须行为一致——一致性由 tests/test_store_contract.py
参数化断言。检索语义的纯函数放在本模块,两侧共用,避免各写一份漂移。
"""
from __future__ import annotations

import json
from typing import Any, Iterable, Literal, Protocol

from pydantic import BaseModel, Field

Importance = Literal["INFO", "GENERAL", "MAJOR", "STRATEGIC"]
BusinessLine = Literal["加油", "充电", "电力", "乡村"]
Order = Literal["date_desc", "importance_desc"]

# --- 检索常量 ---------------------------------------------------------------

IMPORTANCE_ORDER: dict[str, int] = {
    "INFO": 0,
    "GENERAL": 1,
    "MAJOR": 2,
    "STRATEGIC": 3,
}

#: 业务线 → business_view 影响分析的 JSON 键(SCHEMA §4)
BUSINESS_LINE_TO_IMPACT_KEY: dict[str, str] = {
    "加油": "加油",
    "充电": "充电",
    "电力": "电力_储能_V2G_交易",
    "乡村": "乡村",
}

RELATION_TYPES: tuple[str, ...] = (
    "derives_from",
    "extends",
    "iterates",
    "aligns_with",
    "cites_basis",
    "references",
    "clarifies",
    "supersedes",
    "conflicts_with",
)

DEFAULT_LIMIT = 20
MAX_LIMIT = 50
DEFAULT_MAX_CHARS = 20000

#: 已知 pid 撞车快照(2026-08-17 全库实测:14 组、覆盖 40 篇、pid 键控下不可见 26 篇)。
#:
#: 成因在 L1 的 id 生成规则:id 取 official_number 的文号尾号,而系列公告常引用
#: 一个"常设授权文号"而非本件文号(例:江苏成品油系列 7 篇全部引 发改电〔2015〕10 号),
#: 于是整个系列坍缩到同一个 pid。另有一部分是同一文件经两个渠道重复采集(良性)。
#:
#: 消费侧后果:heng-pg 按 pipelinePid upsert,同组只存得下一篇——**其余在生产数据面
#: 不可见**。本服务只读,不修数据;能做的是在命中撞车 pid 时把缺陷告知用户。
#:
#: pg backend 无法在运行时发现撞车(投影时已坍缩),故用本快照;vault backend 在建索引时
#: 实测计算,以实际数量为准。快照会随 vault 增长而过时,只增不减地当下限用。
COLLIDED_PIDS: dict[str, int] = {
    "P_2026_JS_FGW_10": 7,
    "P_2026_HA_X_4": 5,
    "P_2026_NDRC_695": 4,
    "P_2026_SX_FGW_1077": 3,
    "P_2026_FJ_X_3": 3,
    "P_2022_GD_FGW_13": 2,
    "P_2023_GD_FGW_10": 2,
    "P_2024_GD_FGW_174": 2,
    "P_2026_JS_FGW_7": 2,
    "P_2026_GS_FGW_74": 2,
    "P_2026_HN_FGW_169": 2,
    "P_2026_NDRC_1077": 2,
    "P_2026_FJ_GOV_1745": 2,
    "P_2026_HL_FGW_a770e0cb": 2,
}


# --- 纯函数(两 adapter 共用) ------------------------------------------------


def tokenize_keyword(keyword: str | None) -> list[str]:
    """空白切词。词间 AND,每词对 title/docNumber 做不区分大小写子串匹配。"""
    if not keyword:
        return []
    return [tok for tok in keyword.split() if tok]


def keyword_match(title: str | None, doc_number: str | None, tokens: Iterable[str]) -> bool:
    """每个词都要命中 title 或 docNumber 之一(AND 语义)。"""
    haystack = f"{title or ''}\n{doc_number or ''}".lower()
    return all(tok.lower() in haystack for tok in tokens)


def parse_impact(impact_text: str | None) -> dict[str, str] | None:
    """pipelineImpact 是 text 列,内容为 JSON 字符串。解析失败一律视为无影响数据。

    不抛错:库里存在非 JSON 的历史值,检索不能因单篇脏数据整体失败。
    """
    if not impact_text:
        return None
    if isinstance(impact_text, dict):  # vault adapter 直接给 dict
        return {str(k): str(v) for k, v in impact_text.items()}
    try:
        loaded = json.loads(impact_text)
    except (ValueError, TypeError):
        return None
    if not isinstance(loaded, dict):
        return None
    return {str(k): str(v) for k, v in loaded.items()}


#: 影响分析里表示"这条业务线其实没被这份政策影响"的开头写法。
#:
#: 实测(2026-08-17 全库):1989 条影响分析条目里,1276 条(64%)以"未直接涉及"起头。
#: business_view 是逐业务线全填的——不相关也会写一句"未直接涉及。",而不是留空。
#: 所以"值非空即命中"会让业务线过滤 64% 是噪声,"最近对充电影响大的政策"直接失效。
#: 判据取库内既有的书写约定,只认开头,不做语义猜测。
NEGATIVE_IMPACT_PREFIXES: tuple[str, ...] = (
    "未直接涉及",
    "不直接涉及",
    "未涉及",
    "不涉及",
    "无直接影响",
    "无影响",
    "无直接关联",
)


def impact_is_relevant(text: str | None) -> bool:
    """这段影响描述是否表示"确有影响"。空 / 否定式开头 → 否。"""
    cleaned = (text or "").strip().lstrip("（(【[ ")
    if not cleaned:
        return False
    return not cleaned.startswith(NEGATIVE_IMPACT_PREFIXES)


def impact_match(impact_text: str | None, business_line: str | None) -> bool:
    """该政策是否对指定业务线确有影响。

    business_line 为空 → 不过滤(恒真)。JSON 解析失败 → 不命中(不抛错)。
    否定式描述("未直接涉及……")视为不命中,理由见 NEGATIVE_IMPACT_PREFIXES。
    """
    if not business_line:
        return True
    key = BUSINESS_LINE_TO_IMPACT_KEY.get(business_line)
    if key is None:
        return False
    impact = parse_impact(impact_text)
    if not impact:
        return False
    return impact_is_relevant(impact.get(key))


def impact_snippet(impact_text: str | None, business_line: str | None) -> str | None:
    """按业务线取该条影响描述;未指定业务线时返回 None(卡片不带影响文本)。"""
    if not business_line:
        return None
    key = BUSINESS_LINE_TO_IMPACT_KEY.get(business_line)
    if key is None:
        return None
    impact = parse_impact(impact_text)
    if not impact:
        return None
    text = (impact.get(key) or "").strip()
    return text or None


#: 未指定业务线时,影响摘要的字数上限。实测全库剔除"未直接涉及"后
#: 中位 146 字、p90 276 字,240 能完整放下八成以上,20 条也只占约 4k。
IMPACT_DIGEST_MAX_CHARS = 240


def impact_digest(impact_text: str | None, max_chars: int = IMPACT_DIGEST_MAX_CHARS) -> str | None:
    """未指定业务线时的影响摘要:把有实质内容的业务线拼成一行。

    为什么必须有:按主题检索**不带 business_line**,此时若不给影响分析,
    卡片就只剩标题/日期/机关,模型没有任何判断依据,只能挨个去读原文。
    实测(2026-08-18)这让一个盘点式问题读掉 11 篇原文、撞爆 18 次预算——
    而 L2 早就把"这件事对各业务线意味着什么"写好了,不给它才是浪费。
    """
    impact = parse_impact(impact_text)
    if not impact:
        return None
    parts = [
        f"{key}:{text}"
        for key, value in impact.items()
        if (text := str(value).strip())
        and not text.startswith(NEGATIVE_IMPACT_PREFIXES)
    ]
    if not parts:
        return None
    joined = " / ".join(parts)
    return joined if len(joined) <= max_chars else joined[:max_chars] + "…"


def impact_for_card(impact_text: str | None, business_line: str | None) -> str | None:
    """卡片上的影响文本:指定了业务线就给那一条,没指定就给全量摘要。"""
    return impact_snippet(impact_text, business_line) or impact_digest(impact_text)


def importance_from_score(score: Any) -> str:
    """business_view 重要性(1-5) → 枚举。阈值与 pipeline 侧 policy_mapper 一致。"""
    try:
        val = int(score)
    except (TypeError, ValueError):
        return "INFO"
    if val >= 5:
        return "STRATEGIC"
    if val == 4:
        return "MAJOR"
    if val == 3:
        return "GENERAL"
    return "INFO"


def importance_at_least(importance: str, minimum: str | None) -> bool:
    if not minimum:
        return True
    return IMPORTANCE_ORDER.get(importance, 0) >= IMPORTANCE_ORDER.get(minimum, 0)


def normalize_themes(raw: Any) -> list[str]:
    """pipelineThemes(jsonb)→ theme id 列表。只取 id,顺序保持,去重。"""
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return []
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            tid = item.get("id")
        else:
            tid = item
        if tid and str(tid) not in out:
            out.append(str(tid))
    return out


def primary_theme_of(raw: Any) -> str | None:
    """pipelineThemes → 那个 isPrimary 的主题 id。

    投影写入的形状是 `[{id,isPrimary,isComprehensive}]`(见 pipeline 的
    policy_mapper.map_business_view),来源是 business_view 的 primary_theme。
    normalize_themes 只取 id,这里单独把"主"取出来。
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return None
    if not isinstance(raw, list):
        return None
    for item in raw:
        if isinstance(item, dict) and item.get("isPrimary") and item.get("id"):
            return str(item["id"])
    return None


def theme_match(raw: Any, theme_id: str | None, primary_only: bool = False) -> bool:
    """这条记录是否命中指定主题。两个 adapter 共用,保证语义一致。"""
    if not theme_id:
        return True
    if primary_only:
        return primary_theme_of(raw) == theme_id
    return theme_id in normalize_themes(raw)


def clamp_limit(limit: int | None) -> int:
    if not limit or limit < 1:
        return DEFAULT_LIMIT
    return min(int(limit), MAX_LIMIT)


def caveat_for(pid: str, collision_count: int | None = None) -> str | None:
    """该 pid 是否有已知数据缺陷。

    collision_count 由 vault backend 在建索引时实测传入;pg backend 传 None,
    回退到 COLLIDED_PIDS 快照。两侧产出同一句式,保证契约一致。
    """
    count = collision_count if collision_count is not None else COLLIDED_PIDS.get(pid)
    if not count or count < 2:
        return None
    return (
        f"已知数据缺陷:该 pid 在政策库中对应 {count} 份不同文件,"
        "库按 pid 去重后只保留了其中一份,其余在库内不可见。"
        "引用该件时须向用户说明同号可能另有他件,不要断言这是该系列的唯一一件。"
    )


def sort_key(order: str):
    """排序键。date_desc 默认;importance_desc 同级按日期降序。"""
    if order == "importance_desc":
        return lambda c: (IMPORTANCE_ORDER.get(c.importance, 0), c.issue_date or "")
    return lambda c: (c.issue_date or "",)


# --- 返回模型 ---------------------------------------------------------------


class PolicyCard(BaseModel):
    pid: str
    title: str
    doc_number: str | None = None
    issuer: str = ""
    issue_date: str = ""  # ISO YYYY-MM-DD
    region: str | None = None
    level: str | None = None
    importance: Importance = "INFO"
    themes: list[str] = Field(default_factory=list)
    #: L2 标的"主"主题。一篇文件常挂三四个主题,但只有一个是它真正在讲的;
    #: 少了这个区分,"主要讲储能"和"顺带提了储能"在检索结果里没有分别。
    primary_theme: str | None = None
    impact_snippet: str | None = None
    source_url: str | None = None
    caveat: str | None = None


class PolicyDetail(PolicyCard):
    content: str = ""
    content_total_chars: int = 0
    content_offset: int = 0
    scores: dict[str, int] | None = None
    impact: dict[str, str] | None = None
    synced_at: str | None = None


class ThemeInfo(BaseModel):
    """主题登记表的一行。模型靠它知道有哪些主题可选。

    没有这张表,模型只能拿关键词去猜主题名,而主题 id 是 `charging_infra`
    这种内部标识,猜不出来。
    """

    id: str
    name: str = ""
    aliases: list[str] = Field(default_factory=list)
    count: int = 0


class RelationEdge(BaseModel):
    direction: Literal["outbound", "inbound"]
    relation_type: str
    other_pid: str
    other_title: str | None = None
    evidence: str | None = None
    confidence: float | None = None


class CommentaryItem(BaseModel):
    commentary_id: str
    title: str | None = None
    signal_role: str | None = None
    evidence: str | None = None
    source_account: str | None = None
    business_tag: str | None = None
    confidence: float | None = None


class SearchResult(BaseModel):
    total: int
    rows: list[PolicyCard] = Field(default_factory=list)


class StoreError(RuntimeError):
    """检索层故障。api 层转成 SSE error 事件,不泄露 DSN 等连接细节。"""


# --- Protocol ---------------------------------------------------------------


class PolicyStore(Protocol):
    def search_policies(
        self,
        *,
        keyword: str | None = None,
        business_line: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        region_keyword: str | None = None,
        min_importance: str | None = None,
        issuer_keyword: str | None = None,
        theme_id: str | None = None,
        primary_theme_only: bool = False,
        order: str = "date_desc",
        limit: int = DEFAULT_LIMIT,
    ) -> SearchResult: ...

    def list_themes(self) -> list[ThemeInfo]: ...

    def get_policy(
        self, pid: str, *, max_chars: int = DEFAULT_MAX_CHARS, offset: int = 0
    ) -> PolicyDetail | None: ...

    def get_relations(self, pid: str) -> list[RelationEdge]: ...

    def get_commentary(self, pid: str) -> list[CommentaryItem]: ...

    def stats(self) -> dict: ...
