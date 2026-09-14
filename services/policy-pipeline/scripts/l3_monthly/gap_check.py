"""MA1b:web 双保险——查库外漏采。

存在理由是实测出来的。2026-09-07 对 2026-07/08 跑一轮搜索,与真实 vault(1653 篇)
对账,捞出两条库里没有的国家级文件,其中一条是**国家税务总局公告 2026 年第 11 号**
(成品油零售全面推广「交易即开票」,2026-11-01 全国加油站全覆盖)。库里同名检索出来的
全是商务局的零售许可与年检,税务口一条没有——这正是方法正本点名的跨条线系统性漏采,
且直接命中加油线 F02(消费税/发票票据)与 F05(加油卡/第三方支付)两条 high 信号。

**铁律:web 只作 QA,其正文永不进稿。** 本模块只回答"这个月有没有该看却没入库的文件",
缺口的处置见 WORKFLOW §6.2:能补采的补进 vault 再走正常流程,补不进的只进"已知未覆盖"脚注。
"""
import re

from scripts.l3_monthly import shortlist as sl

_DOCNO_BRACKET = re.compile(r"[一-龥]{2,12}〔\d{4}〕\d{1,5}号")
_DOCNO_ANNUAL = re.compile(r"\d{4}年第\d{1,4}号")


def _month_cn(month):
    y, m = month.split("-")
    return f"{y}年{int(m)}月"


def build_queries(profile, month):
    """按战略画像里 weight: high 的信号构造查询。

    只取 high:medium/suppress 的信号本来就不该左右选目,为它们烧搜索额度没有意义。
    查询词不写在配置里——写死一份词表就是又一份会走散的手写副本。
    """
    mcn = _month_cn(month)
    out = []
    for sig in (profile or {}).get("signals") or []:
        if sig.get("weight") != "high":
            continue
        what = " ".join(str(sig.get("what") or "").split())
        if not what:
            continue
        out.append({"signal_id": sig.get("id", ""), "query": f"{what} {mcn}"})
    return out


def extract_doc_no(text):
    """从标题/正文里抽文号。两种形态:带〔〕的公文号,和「2026年第11号」这类年度序号。"""
    m = _DOCNO_BRACKET.search(text or "")
    if m:
        return m.group(0)
    m = _DOCNO_ANNUAL.search(text or "")
    return m.group(0) if m else ""


def _norm_docno(s):
    return "".join((s or "").split())


def match_in_vault(item, vault_index):
    """返回命中的 policy_id;没命中返回 None。

    `vault_index` 必须是**全库**,不是本月窗口内的候选。「这份文件在不在库里」是全库问题:
    实测中 42 号令的 frontmatter 日期是 2026-06,跑 2026-08 时落在窗口外,拿窗口候选对账
    会把它报成缺口。每期产一批假缺口,人看几次就不看了,双保险也就废了。

    先比文号(精确),再比标题(核心相等或相容)。**不比 URL**——同一份文件在不同站点
    转载,URL 必然不同。
    """
    docno = _norm_docno(item.get("doc_no"))
    if docno:
        for c in vault_index:
            if _norm_docno(c.official_number) and _norm_docno(c.official_number) == docno:
                return c.policy_id
    title = item.get("title") or ""
    for c in vault_index:
        if sl.titles_compatible(title, c.title):
            return c.policy_id
    return None


def run_gap_check(profile, month, vault_index, search_fn, max_results=5):
    """跑搜索腿并与 vault 对账,返回 gap_report 结构。

    `vault_index` 传**全库**(不是 MA0 的窗口候选),理由见 match_in_vault。
    search_fn(query, max_results=N) → [{title, url, content}]。无 key 时它返回空列表,
    本函数照常返回一份空报告——搜索是双保险,挂了不该把出刊带挂。
    """
    queries = build_queries(profile, month)
    seen = {}
    order = []
    for q in queries:
        for r in search_fn(q["query"], max_results=max_results) or []:
            title = (r.get("title") or "").strip()
            url = (r.get("url") or "").strip()
            key = url or sl.normalize_title(title)
            if not key:
                continue
            if key in seen:
                sids = seen[key]["signal_id"].split(",") if seen[key]["signal_id"] else []
                if q["signal_id"] and q["signal_id"] not in sids:
                    sids.append(q["signal_id"])
                    seen[key]["signal_id"] = ",".join(sids)
                continue
            seen[key] = {
                "title": title, "url": url,
                "doc_no": extract_doc_no(title) or extract_doc_no(r.get("content") or ""),
                "signal_id": q["signal_id"], "query": q["query"],
            }
            order.append(key)

    items = []
    for key in order:
        it = seen[key]
        pid = match_in_vault(it, vault_index)
        it["in_vault"] = pid is not None
        it["matched_pid"] = pid or ""
        items.append(it)
    items.sort(key=lambda i: i["in_vault"])          # 缺口排前面,人先看见要紧的

    return {
        "month": month,
        "items": items,
        "summary": {"queries": len(queries), "found": len(items),
                    "gaps": sum(1 for i in items if not i["in_vault"])},
    }
