"""MA5d:速览表纯代码生成。

表格是最容易被编造的地方——一行四个字段,模型编一个日期或文号,F 门未必逐个抓得住。
所以这张表**不过 LLM**,而是从两个已有来源拼:

- 主来源:MA2 的落款三事实(它本来就在读 RAW 头尾判国家/地方,顺手报落款几乎不要钱)。
- 交叉核对:signoff 正则。2026-09-07 对 168 篇真实 RAW 实测,命中率 date 47% /
  issuer 35% / doc_no 36%,且 doc_no 有已证实的精度缺陷——会把正文引用的别人的文号
  (国办发〔2025〕5号)当成本件的号。

据此定权:date/issuer 两者互补(谁有用谁,冲突以 MA2 为准并记 caveat);
**doc_no 只认 MA2**,正则单独有值不采信——它的失败模式恰恰是"报一个不属于本件的号"。
抽不到就留空并记 caveat,交终审或人工意见回炉补,**不猜**。
"""
from scripts.l3_monthly import signoff

LEVEL = {"national_detail": "国家级", "local_detail": "地方",
         "roundup": "地方", "appendix": "信号"}
DEFAULT_SECTIONS = ("national_detail", "local_detail")
HEADER = "打分 | 日期 | 文件 | 发文机关"


def _resolve(pid, judgment, regex_fields, caveats, no):
    """按各自实测的可靠性合并两个来源。返回 (date, issuer, doc_no)。"""
    out = {}
    for key, jkey, regex_may_fill in (
            ("date", "issue_date_from_body", True),
            ("issuer", "issuer_from_body", True),
            ("doc_no", "official_number_from_body", False)):
        jv = str((judgment or {}).get(jkey) or "").strip()
        rv = str(regex_fields.get(key) or "").strip()
        if jv and rv and jv != rv:
            caveats.append({"gate": "F", "location": f"quickTable[{no}]",
                            "note": f"{pid} 的 {key} 两个来源不一致"
                                    f"(MA2={jv} / 落款正则={rv}),取 MA2 值,须人工核 RAW"})
        val = jv or (rv if regex_may_fill else "")
        if not val:
            why = ("未能从 RAW 落款抽出" if not rv else
                   "落款正则虽有值但其已证实会误取引用件的号,不予采信")
            caveats.append({"gate": "F", "location": f"quickTable[{no}]",
                            "note": f"{pid} 的 {key} {why},已留空;"
                                    f"禁止回退 frontmatter,须人工核 RAW 补"})
        out[key] = val
    return out["date"], out["issuer"], out["doc_no"]


def build_quick_table(slate, meta_by_pid, judgments_by_pid=None,
                      sections=DEFAULT_SECTIONS):
    """返回 (rows, caveats)。rows 按 slate 的 rank 排,编号 01 起。"""
    judgments_by_pid = judgments_by_pid or {}
    rows, caveats = [], []
    for sec in sections:
        items = sorted((slate.get("sections") or {}).get(sec, []),
                       key=lambda i: i.get("rank") or 10 ** 6)
        for it in items:
            pid = it.get("policy_id")
            meta = meta_by_pid.get(pid) or {}
            no = f"{len(rows) + 1:02d}"
            regex_fields = signoff.signoff_fields(meta.get("body", ""))
            date, issuer, doc_no = _resolve(
                pid, judgments_by_pid.get(pid), regex_fields, caveats, no)
            rows.append({
                "no": no, "policy_id": pid, "level": LEVEL.get(sec, "地方"),
                "score": it.get("score", ""),
                "title": meta.get("title", "") or it.get("title_hint", ""),
                "date": date, "issuer": issuer, "doc_no": doc_no,
            })
    return rows, caveats


def render_table(rows):
    """渲染成 final.md 的表格块。列分隔用 ' | ',与公文渲染器的表格识别一致。"""
    out = [HEADER]
    for r in rows:
        title = r["title"]
        if r["doc_no"]:
            title = f"{title}({r['doc_no']})"
        out.append(" | ".join([r["score"], r["date"], title, r["issuer"]]))
    return "\n".join(out)
