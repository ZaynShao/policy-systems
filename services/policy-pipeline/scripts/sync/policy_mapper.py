"""business_view YAML(dict) → Policy 行 dict。纯函数，映射契约见 spec §5.4。"""
from __future__ import annotations
import datetime
import json
import re


# Policy.level 的 canonical 集合。L1 只产出这五个值(ingester 按 region.code 判级),
# 但 vault 契约没把 level 做成枚举,heng-guan 手工录入 / 种子数据用的是"省级/市级"
# 那套口径。投影是两边的交界,所以在这里收口一次,别让同义异写进库。
CANONICAL_LEVELS = ("国家", "省", "市", "区", "县")

# 直辖市 / 自治区折进"省"是跟 ingester 对齐:code 末尾 0000(非 000000)即判省,
# 北京(110000)、内蒙古(150000)在 L1 本来就是 level=省。
_LEVEL_ALIASES = {
    "国": "国家", "国家级": "国家", "中央": "国家", "全国": "国家",
    "省级": "省", "省份": "省", "自治区": "省", "直辖市": "省",
    "市级": "市", "地市": "市", "地级市": "市",
    "区级": "区", "市辖区": "区",
    "县级": "县", "县级市": "县",
}


def normalize_level(v) -> str | None:
    """行政层级 → canonical 五值;空 → None;**未知取值原样透传**。

    不把未知值抹成空或猜一个 canonical:脏值要留在库里可被查出来,静默改写等于
    把上游的归属 bug 埋掉(参见 L1 区县档 level 误标)。
    """
    s = str(v or "").strip()
    if not s:
        return None
    if s in CANONICAL_LEVELS:
        return s
    return _LEVEL_ALIASES.get(s, s)


def importance_to_enum(score: int) -> str:
    """pipeline 1-5 分 → Prisma PolicyImportance。"""
    if score >= 5:
        return "STRATEGIC"
    if score == 4:
        return "MAJOR"
    if score == 3:
        return "GENERAL"
    return "INFO"


def map_business_view(bv: dict, pipeline_version: int) -> dict:
    primary = bv.get("primary_theme")
    comprehensive = bool(bv.get("comprehensive", False))
    themes = [
        {
            "id": t,
            "isPrimary": (t == primary),
            "isComprehensive": comprehensive and (t == primary),
        }
        for t in bv.get("themes", [])
    ]
    impact = bv.get("影响分析", {})
    impact_text = json.dumps(impact, ensure_ascii=False) if isinstance(impact, dict) else str(impact)
    return {
        "pipeline_pid": bv["pid"],
        "pipeline_version": pipeline_version,
        "importance": importance_to_enum(int(bv.get("重要性", 1))),
        "pipeline_scores": json.dumps(bv.get("scores", {}), ensure_ascii=False),
        "pipeline_themes": json.dumps(themes, ensure_ascii=False),
        "pipeline_impact": impact_text,
        "comprehensive": comprehensive,
    }


def parse_issue_date(s: str) -> datetime.date:
    """YYYY-MM-DD → date;空/非法 → raise ValueError(不写假数据)。"""
    s = (s or "").strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if not m:
        raise ValueError(f"unparseable issue date: {s!r}")
    return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def map_policy_row(bv: dict, core: dict, pipeline_version: int) -> dict:
    """business_view(分析) + raw 核心字段 → 完整 Policy 行。
    核心字段坏掉(坏 date / 空 title / 空 content)→ raise ValueError,由 collect 拒收+记池。"""
    issue_date = parse_issue_date(core.get("date"))          # 可能 raise
    title = (core.get("title") or "").strip()
    content = (core.get("content") or "").strip()
    if not title:
        raise ValueError("empty title")
    if not content:
        raise ValueError("empty content")
    row = map_business_view(bv, pipeline_version)            # pipeline 字段
    row.update({
        "title": title,
        "issuer": core.get("issuer") or "",                 # 空 issuer 允许空串(过 NOT NULL)
        "issue_date": issue_date,                            # date 对象,psycopg2 自适配
        "content": content,
        "source": "AUTO",                                   # 都是 L1 自动采集
        "doc_number": core.get("doc_number") or None,
        "source_url": core.get("source_url") or None,
        "region": core.get("region") or None,
        "level": normalize_level(core.get("level")),   # 同义异写收口,见 normalize_level
        "adcode": core.get("adcode") or None,             # L1 region.code(GB/T 2260 6位),省级匹配键
    })
    return row
