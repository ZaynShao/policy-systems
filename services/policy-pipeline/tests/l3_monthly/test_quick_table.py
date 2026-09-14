"""MA5d:速览表纯代码生成(不过 LLM)。

表格是最容易被编造的地方——一行四个字段,模型编一个日期或文号,F 门未必逐个抓得住。
所以这张表不让模型写,而是从**两个已有来源**拼:

- 主来源:MA2 的落款三事实。MA2 本来就在读 RAW 头尾判国家/地方,顺手报落款几乎不要钱。
- 交叉核对:signoff 正则。2026-09-07 对 168 篇真实 RAW 实测,正则命中率 date 47% /
  issuer 35% / doc_no 36%,且 doc_no 有**已证实的精度缺陷**——会把正文里引用的
  别人的文号(国办发〔2025〕5号)当成本件的号。

据此定权:date/issuer 两者互补(谁有用谁,冲突以 MA2 为准并记 caveat);
doc_no **只认 MA2**,正则单独有值不采信——它的失败模式恰恰是"报一个不属于本件的号"。
"""
from scripts.l3_monthly import quick_table as Q

BODY_884 = ("国家发展改革委 国家能源局\n\n发改能源〔2026〕884号\n\n正文。\n\n"
            "国家发展改革委\n国家能源局\n2026年6月13日\n")
BODY_BARE = "一段没有落款也没有文号的正文。\n"
BODY_CITED_ONLY = "本细则根据国办发〔2025〕5号制定。\n\n西藏自治区商务厅\n2026年6月2日\n"


def _slate(*pids):
    return {"month": "2026-06", "narrative": "定调", "sections": {
        "national_detail": [{"policy_id": p, "title_hint": p, "score": "5分",
                             "rank": i + 1, "why": "y", "dq": ""}
                            for i, p in enumerate(pids)],
        "local_detail": [], "roundup": [], "appendix": []}}


def _j(**over):
    d = {"issue_date_from_body": "", "issuer_from_body": "",
         "official_number_from_body": ""}
    d.update(over)
    return d


def test_prefers_ma2_signoff_facts():
    rows, cav = Q.build_quick_table(
        _slate("P_1"), {"P_1": {"title": "甲通知", "body": BODY_BARE}},
        {"P_1": _j(issue_date_from_body="2026-06-13", issuer_from_body="国家发展改革委",
                   official_number_from_body="发改能源〔2026〕884号")})
    r = rows[0]
    assert (r["date"], r["issuer"], r["doc_no"]) == (
        "2026-06-13", "国家发展改革委", "发改能源〔2026〕884号")
    assert cav == []


def test_regex_fills_date_and_issuer_when_ma2_blank():
    """date/issuer 的正则是仓内既有的单一真相源,MA2 没读出来时可以补位。"""
    rows, cav = Q.build_quick_table(
        _slate("P_1"), {"P_1": {"title": "甲", "body": BODY_884}}, {"P_1": _j()})
    assert rows[0]["date"] == "2026-06-13"
    assert "国家发展改革委" in rows[0]["issuer"]


def test_regex_alone_never_supplies_doc_no():
    """实测:正则会把正文里引用的「国办发〔2025〕5号」当成本件文号。

    它的失败模式恰恰是"报一个不属于本件的号",所以 MA2 没报文号时宁可留空。
    """
    rows, cav = Q.build_quick_table(
        _slate("P_1"), {"P_1": {"title": "西藏细则", "body": BODY_CITED_ONLY}},
        {"P_1": _j(issue_date_from_body="2026-06-02", issuer_from_body="西藏自治区商务厅")})
    assert rows[0]["doc_no"] == ""
    assert any("doc_no" in c["note"] for c in cav)


def test_disagreement_keeps_ma2_value_and_records_caveat():
    rows, cav = Q.build_quick_table(
        _slate("P_1"), {"P_1": {"title": "甲", "body": BODY_884}},
        {"P_1": _j(issue_date_from_body="2026-06-25", issuer_from_body="国家能源局",
                   official_number_from_body="发改能源〔2026〕884号")})
    assert rows[0]["date"] == "2026-06-25"
    assert any("不一致" in c["note"] and "date" in c["note"] for c in cav)


def test_all_blank_produces_caveat_and_no_guessing():
    rows, cav = Q.build_quick_table(
        _slate("P_1"), {"P_1": {"title": "甲", "body": BODY_BARE}}, {"P_1": _j()})
    assert (rows[0]["date"], rows[0]["issuer"], rows[0]["doc_no"]) == ("", "", "")
    assert any("P_1" in c["note"] for c in cav) and all(c["gate"] == "F" for c in cav)


def test_rows_follow_slate_rank_and_number_from_one():
    rows, _ = Q.build_quick_table(
        _slate("P_1", "P_2"),
        {"P_1": {"title": "甲", "body": BODY_BARE}, "P_2": {"title": "乙", "body": BODY_BARE}},
        {"P_1": _j(), "P_2": _j()})
    assert [r["no"] for r in rows] == ["01", "02"]


def test_title_uses_document_title_not_slate_hint():
    rows, _ = Q.build_quick_table(
        _slate("P_1"), {"P_1": {"title": "关于印发《甲》的通知", "body": BODY_BARE}},
        {"P_1": _j()})
    assert rows[0]["title"].startswith("关于印发")


def test_renders_pipe_table_without_banned_marks():
    rows, _ = Q.build_quick_table(
        _slate("P_1"), {"P_1": {"title": "甲通知", "body": BODY_884}}, {"P_1": _j()})
    md = Q.render_table(rows)
    assert md.split("\n")[0] == "打分 | 日期 | 文件 | 发文机关"
    assert "**" not in md and "⭐" not in md and "「" not in md
