"""F 门:稿内每个事实都要能在素材包里回指得到。

分工照 spec §6.4:**代码抽claim + 代码匹配**,只有匹配不上的才交 LLM 判是否等价表述。
绝大多数能代码判掉,不该为此每期烧一遍 token。

抽取口径的关键是**别过度抽**:中文数字("三大业务""一、概述")不是事实断言,
抽进来会让每期几十条假阳性,人看两次就不看了,这道门也就废了。
"""
from scripts.l3_monthly import fact_gate as fg


BUNDLE = """## RAW 原文
国家发展改革委 国家能源局
发改能源〔2026〕1067号
各省级人民政府:
第三条 各省应于 2026年7月23日 前完成备案。
全国虚拟电厂项目已达 470 个,最大调节能力 1685 万千瓦。
本办法所称"绿电直连",是指……
2026年7月8日
"""


# ── ① 抽取口径 ─────────────────────────────────────────────────
def test_extracts_doc_no_date_article_number_and_quote():
    kinds = {c["kind"] for c in fg.extract_claims(
        '依据发改能源〔2026〕1067号,第三条要求 2026年7月23日 前完成,'
        '调节能力 1685 万千瓦,文件称"绿电直连"。')}
    assert kinds == {"doc_no", "date", "article", "number", "quote"}


def test_does_not_extract_chinese_numerals():
    """「三大业务」「一、概述」不是事实断言。抽进来就是每期几十条假阳性。"""
    claims = fg.extract_claims("一、概述\n三大业务的态势各不相同,十余省已跟进。")
    assert claims == []


def test_does_not_extract_bare_year_month_of_the_issue():
    """「2026 年 7 月」这种期次表述到处都是,不作事实断言抽。"""
    assert [c["text"] for c in fg.extract_claims("2026 年 7 月政策密度抬升。")] == []


def test_quote_extraction_ignores_overlong_spans():
    """整段被引号包住的不是引文而是排版,拿去逐字回指必然失败。"""
    long = "他说" + '"' + "很长的一段话" * 12 + '"'
    assert not [c for c in fg.extract_claims(long) if c["kind"] == "quote"]


# ── ② 匹配 ─────────────────────────────────────────────────────
def test_claims_present_in_bundle_pass():
    text = ('依据发改能源〔2026〕1067号,第三条要求各省于 2026年7月23日 前完成备案;'
            '全国虚拟电厂已达 470 个,调节能力 1685 万千瓦,文件称"绿电直连"。')
    assert fg.check_facts(text, [BUNDLE]) == []


def test_wrong_digit_is_caught():
    v = fg.check_facts("调节能力 1658 万千瓦。", [BUNDLE])
    assert len(v) == 1 and v[0]["gate"] == "F" and "1658" in v[0]["quote"]


def test_wrong_doc_no_is_caught():
    v = fg.check_facts("依据发改能源〔2026〕1068号。", [BUNDLE])
    assert [x["kind"] for x in v] == ["doc_no"]


def test_quote_must_be_verbatim():
    v = fg.check_facts('文件称"绿电直供"。', [BUNDLE])
    assert [x["kind"] for x in v] == ["quote"]


def test_date_matches_across_formats():
    """稿里写 2026年7月23日、素材里写 2026-07-23,是同一天,不该报。"""
    assert fg.check_facts("应于 2026年7月23日 前完成。",
                          ["各省应于 2026-07-23 前完成备案。"]) == []


def test_fullwidth_digits_normalise():
    assert fg.check_facts("共 １６８５ 万千瓦。", [BUNDLE]) == []


def test_thousands_separator_normalises():
    assert fg.check_facts("共 1,685 万千瓦。", [BUNDLE]) == []


def test_claim_may_be_backed_by_any_source():
    """概述的依据是已写完的各块,不是某一个 bundle。"""
    assert fg.check_facts("调节能力 1685 万千瓦。", ["无关材料", BUNDLE]) == []


def test_violation_carries_location_and_expected_shape():
    v = fg.check_facts("调节能力 1658 万千瓦。", [BUNDLE], location="details[01].reading")
    assert v[0]["location"] == "details[01].reading"
    assert v[0]["severity"] == "BLOCKER" and "回指" in v[0]["note"]


def test_no_sources_means_every_claim_is_unbacked():
    """素材包没装上就等于没有事实源。这时不该"全部通过",那是最危险的假绿。"""
    v = fg.check_facts("依据发改能源〔2026〕1067号。", [])
    assert len(v) == 1


# ── ③ 交给 LLM 的只有代码判不掉的 ──────────────────────────────
def test_adjudicate_only_sees_unmatched_claims():
    seen = {}

    class C:
        def complete(self, system, user, max_tokens=None):
            seen["user"] = user
            return '{"verdicts":[{"index":0,"equivalent":true,"why":"同一数字的不同写法"}]}'

    v = fg.check_facts("调节能力 1658 万千瓦,且 1685 万千瓦。", [BUNDLE])
    assert len(v) == 1                      # 1685 能匹配上,只有 1658 是待判
    left = fg.adjudicate(C(), v, [BUNDLE])
    assert "1658" in seen["user"] and "1685 万千瓦,且" not in seen["user"]
    assert left == []                        # 模型判为等价 → 不再算违规


def test_adjudicate_keeps_violation_when_model_says_not_equivalent():
    class C:
        def complete(self, system, user, max_tokens=None):
            return '{"verdicts":[{"index":0,"equivalent":false,"why":"数字确实不同"}]}'

    v = fg.check_facts("调节能力 1658 万千瓦。", [BUNDLE])
    assert len(fg.adjudicate(C(), v, [BUNDLE])) == 1


def test_adjudicate_keeps_violations_when_model_fails():
    """模型答不出来就维持原判——F 门宁可多报,不可放过。"""
    class C:
        def complete(self, system, user, max_tokens=None):
            return "不是 JSON"

    v = fg.check_facts("调节能力 1658 万千瓦。", [BUNDLE])
    assert len(fg.adjudicate(C(), v, [BUNDLE])) == 1


def test_adjudicate_without_client_is_a_no_op():
    v = fg.check_facts("调节能力 1658 万千瓦。", [BUNDLE])
    assert fg.adjudicate(None, v, [BUNDLE]) == v


def test_doc_no_prefix_must_match_not_just_the_bracket_core():
    """把正则放松到只认括号核心,「错改能源〔2026〕1067号」就会蒙混过关。"""
    v = fg.check_facts("依据错改能源〔2026〕1067号。", [BUNDLE])
    assert [x["kind"] for x in v] == ["doc_no"]


def test_doc_no_matches_even_when_the_sentence_adds_words_before_it():
    """正则会贪婪地把「依据」一起吃进来,那不是稿子写错了。"""
    assert fg.check_facts("依据发改能源〔2026〕1067号。", [BUNDLE]) == []


# ── ④ 本期自身的结构计数 ───────────────────────────────────────
def _content():
    return {"quickTable": [{"level": "国家级"}, {"level": "国家级"}, {"level": "地方"}],
            "details": [{"no": "01"}]}


def test_editorial_counts_are_backed_by_the_issue_itself():
    """「国家级 2 项」回指的是本期选目,不是某份 RAW。不给这个源就每期误报几条。"""
    src = fg.editorial_source(_content())
    assert fg.check_facts("本期国家级 2 项、地方 1 项,详情 1 篇。", [src]) == []


def test_wrong_editorial_count_is_still_caught():
    """给了这个源不是放水:数错了照抓。"""
    v = fg.check_facts("本期国家级 5 项。", [fg.editorial_source(_content())])
    assert [x["quote"] for x in v] == ["5 项"]
