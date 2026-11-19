"""落款三字段抽取(发文机关 / 发文日 / 文号)。

速览表的这三列**一律取自 RAW 正文的落款与文头**,禁止回退 frontmatter——
frontmatter 的 date 常是生效/发布日、region.name 常是采集省份、official_number
可能抓到被废止件的号。抽不到就留空并记 caveat,**不许猜**。

日期与文号复用仓内既有的单一真相源(cn_dates / metadata_extractor),不另写一套。
"""
from scripts.l3_monthly import signoff as S

BODY = """国家发展改革委 国家能源局

关于印发《新型能源体系建设"十五五"规划》的通知

发改能源〔2026〕884号

各省、自治区、直辖市人民政府:

现将《新型能源体系建设"十五五"规划》印发给你们,请认真贯彻执行。
本规划自2026年8月1日起施行。

国家发展改革委
国家能源局
2026年6月13日
"""


def test_picks_signoff_date_not_effective_date():
    """正文里既有「自2026年8月1日起施行」也有落款「2026年6月13日」,只能取后者。"""
    assert S.signoff_fields(BODY)["date"] == "2026-06-13"


def test_picks_joint_issuers_from_signoff_block():
    got = S.signoff_fields(BODY)["issuer"]
    assert "国家发展改革委" in got and "国家能源局" in got


def test_picks_official_number_from_body():
    assert S.signoff_fields(BODY)["doc_no"] == "发改能源〔2026〕884号"


def test_missing_signoff_leaves_blank_and_reports_why():
    f = S.signoff_fields("一段没有任何落款与文号的正文。")
    assert f["date"] == "" and f["issuer"] == "" and f["doc_no"] == ""
    assert f["missing"] == ["date", "issuer", "doc_no"]


def test_chinese_numeral_signoff_date():
    body = "某某文件正文。\n\n浙江省发展和改革委员会\n二〇二六年五月二十八日\n"
    f = S.signoff_fields(body)
    assert f["date"] == "2026-05-28"
    assert "浙江省发展和改革委员会" in f["issuer"]


def test_issuer_stops_at_non_org_line():
    body = "正文结束。\n\n请各单位遵照执行。\n浙江省能源局\n2026年5月28日\n"
    assert S.signoff_fields(body)["issuer"] == "浙江省能源局"


# ══════════════════════════════════════════════════════════════
# 以下用例来自 2026-09-07 对 168 篇真实 RAW 的实测假阳性。
# ══════════════════════════════════════════════════════════════

def test_headline_ending_in_ju_is_not_an_issuer():
    """实测假阳性:「一季度全省经济实现平稳开局」被当成发文机关——因为"开局"以"局"结尾。"""
    body = "云南省发展改革委发布数据。\n一季度全省经济实现平稳开局\n2026年4月21日\n"
    assert S.signoff_fields(body)["issuer"] == ""


def test_source_line_is_not_an_issuer():
    """实测假阳性:「来源:云南发布、云南省能源局」是转载出处,不是发文机关。"""
    body = "正文。\n来源：云南发布、云南省能源局\n2026年4月23日\n"
    assert S.signoff_fields(body)["issuer"] == ""


def test_real_org_names_still_extracted():
    for org in ("浙江省发展和改革委员会", "国家能源局", "上海市商务委员会",
                "山西省发展和改革委员会", "西藏自治区商务厅", "国务院办公厅"):
        body = f"正文。\n\n{org}\n2026年5月28日\n"
        assert S.signoff_fields(body)["issuer"] == org, f"{org} 应被认出"
