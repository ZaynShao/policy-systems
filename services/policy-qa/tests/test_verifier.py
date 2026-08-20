"""事实核验。

它针对的是一次真实事故:模型写出 `浙发改价格〔2026〕21号`,而库里是〔2024〕21号
——被本件废止的那份旧件的号。当时靠人眼抓到,补了 prompt 规则;
prompt 规则挡不住第二次,这一层能。

这层**不调模型**:"文号必须逐字照抄"本来就是字面规则,那么正确的检查就是字面比对。
"""
from __future__ import annotations

from app.verifier import normalize, verify_answer

EVIDENCE = (
    '{"pid": "P_2026_ZJ_21", "title": "浙江省分时电价机制通知", '
    '"doc_number": "浙发改价格〔2024〕21号", '
    '"content": "为完善分时电价机制,峰谷价差原则上不低于3:1。'
    '本通知自2026年7月1日起执行,浙发改价格〔2019〕8号同时废止。"}'
)


def test_fabricated_doc_number_is_caught():
    """把年份改掉凑一个"看起来合理"的文号——这就是真实事故那一幕。"""
    report = verify_answer(
        "该件为《浙江省分时电价机制通知》(浙发改价格〔2026〕21号),自7月起执行。",
        EVIDENCE,
    )
    assert not report.ok
    assert [c.kind for c in report.unsupported] == ["doc_number"]
    assert "〔2026〕21号" in report.unsupported[0].text


def test_doc_number_actually_present_passes():
    report = verify_answer(
        "该件为浙发改价格〔2024〕21号,其中明确峰谷价差要求。", EVIDENCE
    )
    assert report.ok, [c.model_dump() for c in report.unsupported]
    assert report.checked_doc_numbers == 1


def test_abolished_predecessor_number_is_still_supported():
    """被废止旧件的文号也在原文里出现过,引用它是**如实转述**,不该报。

    核验的判据是"模型见没见过",不是"这个号属不属于本件"——后者是语义判断,
    交给 prompt 规则和用户核对,这一层只做能确定的事。
    """
    report = verify_answer("本件同时废止了浙发改价格〔2019〕8号。", EVIDENCE)
    assert report.ok


def test_issuer_prefix_may_be_rewritten_without_being_flagged():
    """机关简称写全了是转写不是编造。年份和序号一位都不能差,那才是编造。"""
    ok = verify_answer("浙江省发展改革委〔2024〕21号规定……", EVIDENCE)
    assert ok.ok, "只是把机关名写全,不该报"

    bad = verify_answer("浙江省发展改革委〔2024〕99号规定……", EVIDENCE)
    assert not bad.ok, "序号对不上就是编造"


def test_bracket_variants_are_not_false_positives():
    """同一个文号在正文里可能写成 ()、（）、[]、〔〕。写法差异不是编造。"""
    report = verify_answer("依据浙发改价格(2024)21号……", EVIDENCE)
    assert report.ok


def test_quote_must_be_verbatim():
    report = verify_answer(
        "原文称「峰谷价差原则上不低于四比一」。", EVIDENCE
    )
    assert not report.ok
    assert report.unsupported[0].kind == "quote"


def test_verbatim_quote_with_ellipsis_passes():
    """引文允许用……省略,按省略号切段后逐段核。"""
    report = verify_answer(
        "原文称「为完善分时电价机制……峰谷价差原则上不低于3:1」。", EVIDENCE
    )
    assert report.ok, [c.model_dump() for c in report.unsupported]
    assert report.checked_quotes == 1


def test_short_quotes_are_not_checked():
    """太短的片段在长文里几乎必然偶然命中,核了全是假阳性。"""
    report = verify_answer("提到了「电价」两个字。", EVIDENCE)
    assert report.ok
    assert report.checked_quotes == 0


def test_no_evidence_means_no_verdict():
    """一次工具都没调(比如闲聊被拒答)时不做判断,免得把正常回答报成编造。"""
    report = verify_answer("我只覆盖能源政策库。", "")
    assert report.ok
    assert report.checked_doc_numbers == 0


def test_normalize_unifies_brackets_and_strips_whitespace():
    assert normalize("发改能源 (2026) 1号") == "发改能源〔2026〕1号"
    assert normalize("发改能源［2026］1号") == "发改能源〔2026〕1号"


def test_verb_prefix_is_stripped_from_the_report():
    """正则前缀是贪婪的,会把"废止"这类动词吃进来。判定不受影响,但报出来要干净。

    实测报出过「废止财税〔2018〕74号」——读的人会以为文号本身叫这个。
    """
    report = verify_answer("本件废止财税〔2018〕99号。", EVIDENCE)
    assert not report.ok
    assert report.unsupported[0].text == "财税〔2018〕99号"


def test_doc_number_from_the_user_question_is_not_a_fabrication():
    """用户自己在问题里写的文号,模型复述一遍不算编造。

    2026-08-18 答案评测实测:用户问「发改办能源〔2026〕000号讲了什么」,
    模型正确回答"库内未收录",核验却把这个号报成存疑。
    一个总在报警的核验器等于没有核验器。
    """
    question = "发改办能源〔2026〕000号《某内部通知》讲了什么？"
    answer = "库内未收录 发改办能源〔2026〕000号,无法解读其内容。"
    assert not verify_answer(answer, EVIDENCE).ok, "不带问题时会误报——这正是修之前的行为"
    assert verify_answer(answer, EVIDENCE, question=question).ok


def test_a_different_number_is_still_caught_even_with_a_question():
    """把用户问题算进证据,不等于放行任何文号:换一个号照样抓。"""
    question = "发改办能源〔2026〕000号讲了什么？"
    answer = "相关的还有 发改办能源〔2026〕999号。"
    assert not verify_answer(answer, EVIDENCE, question=question).ok
