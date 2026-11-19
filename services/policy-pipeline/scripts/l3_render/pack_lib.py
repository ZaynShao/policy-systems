"""月报素材包纯逻辑:解析 / 国家-地方分级 / 关系解析 / 噪声过滤 / 撞车消歧 / 正文日期线索。

只读、无 IO 副作用,可离线单测。
"""
import re

NATIONAL_ISSUER_HINTS = (
    "国家发展改革委", "国家发改委", "发展改革委等", "国家能源局", "工业和信息化部",
    "国家数据局", "商务部", "财政部", "生态环境部", "中共中央", "国务院", "市场监管总局",
)
NATIONAL_DOCNO_PREFIXES = ("发改", "国能发", "国能", "工信部", "商务部")
NOISE_KEYWORDS = (
    "市场监管局", "市场监督管理局", "市场监管总局", "信用上海", "诚信建设", "辩论赛",
    "职称", "专家库", "维保", "儿童节", "中高考", "座谈会", "智能搜索", "信息公开",
    "询价结果", "采购意向", "比对活动", "平台经济",
)


def parse_frontmatter(md: str) -> dict:
    """从 markdown 解析 YAML frontmatter 的关键字段(粗解析,够用即可)。"""
    m = re.search(r"^---\n(.*?)\n---", md, re.S)
    body = m.group(1) if m else ""
    d = {}
    for k in ("id", "title", "official_number", "date", "type"):
        mm = re.search(rf"^{k}:\s*(.*)$", body, re.M)
        if mm:
            d[k] = mm.group(1).strip().strip("'\"")
    lvl = re.search(r"level:\s*(\S+)", body)
    d["region_level"] = lvl.group(1) if lvl else ""
    # region.name 是 region: 块下第一个 name:,只取该行(不可用 (.*)$ 配 re.S,会贪婪吞到文末)
    nm = re.search(r"region:\s*\n(?:.*\n)*?\s*name:\s*([^\n]*)", body)
    d["region_name"] = nm.group(1).strip().strip("'\"") if nm else ""
    return d


def classify_level(issuer: str, docno: str, region_level: str) -> str:
    """国家/地方判定:看发文机关 + 文号,不信 region.level 字段(已知有脏数据)。"""
    issuer = issuer or ""
    docno = docno or ""
    if any(h in issuer for h in NATIONAL_ISSUER_HINTS):
        return "国家"
    if docno and any(docno.startswith(p) for p in NATIONAL_DOCNO_PREFIXES):
        return "国家"
    return "地方"


def is_noise(title: str) -> bool:
    t = title or ""
    return any(k in t for k in NOISE_KEYWORDS)


def resolve_relations(pid: str, edges: list, id2title: dict) -> list:
    """把 pid 的关系边解析为 {rel, dir(in/out), other(对端标题), evidence} 列表。

    relations_canonical.jsonl 的字段是 from / to / rel / evidence。
    """
    out = []
    for e in edges:
        frm, to, rel = e.get("from"), e.get("to"), e.get("rel")
        ev = (e.get("evidence") or "")[:200]
        if frm == pid and to in id2title:
            out.append({"rel": rel, "dir": "out", "other": id2title[to], "evidence": ev})
        elif to == pid and frm in id2title:
            out.append({"rel": rel, "dir": "in", "other": id2title[frm], "evidence": ev})
    return out


def pick_record(recs, title_hint=None):
    """id 撞车时按 title_hint 选 raw;无 hint 或单条则取第一条。recs=[(path, fm, body), ...]"""
    if len(recs) == 1 or not title_hint:
        return recs[0]
    for r in recs:
        if title_hint in (r[1].get("title") or ""):
            return r
    return recs[0]


ELISION = "\n……(中略)……\n"
LINK_MARK = "〔链接〕"
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]*)\]\((?:https?|ftp)://[^)]*\)")
_BARE_URL = re.compile(r"(?:https?|ftp)://\S+")


def strip_web_chrome(text: str) -> str:
    """去掉采集页面带进来的图片与 URL,只留链接文字。

    2026-09-07 对 168 篇 shortlist 实测:RAW 正文里 **23% 的字符是 URL 与图片占位**,
    26% 的文件有四成以上的头部预算被它吃掉,最脏的一篇 86%——写作那步只剩几百字
    真正文可读。而 URL 本身还在 D 门禁项上(过程性元信息),留着只是招违规。

    **不动 vault 里的 RAW**(那是永不修改的),只清理喂给模型的摘录;
    速览表抽落款用的仍是未清理的全文,以免动摇已实测过的抽取口径。
    """
    t = _MD_IMAGE.sub("", text or "")
    t = _MD_LINK.sub(lambda m: m.group(1), t)
    return _BARE_URL.sub(LINK_MARK, t)


def body_of(md: str) -> str:
    """取 frontmatter 之后的正文。装包与 MA2 摘录共用同一种取法。"""
    return (md or "").split("---", 2)[-1].strip()


def excerpt(body: str, head_chars: int, tail_chars: int) -> str:
    """长正文摘录:**头尾都取**,预算由调用方给(各步的预算不一样)。

    文头有发文机关与标题、落款在文末。只截「正文前 N 字」会把落款整段截掉,
    下游便只能退回去信 frontmatter——那正是这条产线要修的病。
    MA2 的判定摘录与 MA4 装包的 RAW 段共用这一条规则。
    """
    body = body or ""
    if len(body) <= head_chars + tail_chars:
        return body
    return body[:head_chars] + ELISION + body[-tail_chars:]


def body_date_hints(body: str) -> list:
    """从正文抽取候选日期(用于校验真实发文日,绕开 frontmatter date 脏数据)。"""
    return re.findall(r"20\d{2}年\d{1,2}月\d{1,2}日", body or "")
