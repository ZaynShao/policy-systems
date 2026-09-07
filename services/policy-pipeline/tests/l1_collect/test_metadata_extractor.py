"""Tests for metadata_extractor."""
from __future__ import annotations
from scripts.l1_collect.metadata_extractor import (
    extract_official_number, extract_date, extract_issuer_from_url,
)


def test_extract_official_number_standard():
    s = "...本通知...（发改能源〔2024〕1128号）规定..."
    assert extract_official_number(s) == "发改能源〔2024〕1128号"


def test_extract_official_number_square_brackets():
    s = "依据沪发改[2023]58号文..."
    out = extract_official_number(s)
    assert "[2023]58号" in out or "〔2023〕58号" in out


def test_extract_date_from_url_pattern():
    assert extract_date("https://www.gov.cn/zhengce/2024-08/15/content_xxx.html") == "2024-08-15"


def test_extract_date_compact_url_format():
    """/YYYYMM/tYYYYMMDD_ 紧凑格式(政府站常见,原delimited正则抓不到) → 抽到日期。"""
    assert extract_date(
        "https://fgw.shanxi.gov.cn/zcfb/zcjd/202505/t20250527_984313") == "2025-05-27"


def test_extract_date_compact_rejects_invalid_month_day():
    """紧凑匹配但月/日越界(20251340) → 不采用,回落(空)。"""
    assert extract_date("https://x.gov.cn/202513/t20251340_1") == ""


def test_extract_date_body_effective_only_returns_empty():
    """正文只有生效句、无落款 → 不得把生效日当 date(契约:绝不取生效/截止日)。"""
    body = "...本通知自2025年3月1日起施行..."
    assert extract_date("", body=body) == ""


def test_extract_date_body_picks_luokuan():
    """正文有生效句 + 落款 → 取落款发文日。"""
    body = "本通知自2025年3月1日起施行。\n\n济南市人民政府\n2025年1月20日"
    assert extract_date("", body=body) == "2025-01-20"


def test_extract_issuer_from_url_ndrc():
    assert extract_issuer_from_url("https://www.ndrc.gov.cn/xxgzz/zcfb/") == "国家发展和改革委员会"


def test_extract_issuer_from_url_unknown():
    assert extract_issuer_from_url("https://unknown.example.com/x") is None


# --- 文号归属:正文里第一个文号形状的串未必是本件文号(生产实测) ---

def test_official_number_never_swallows_citation_verb():
    """生产实例:抽出 '根据财库〔2022〕3号' —— 贪婪前缀把「根据」吃进了文号。
    「根据/依据/按照」不是任何文号的组成部分。"""
    out = extract_official_number("根据财库〔2022〕3号文件要求,现将有关事项通知如下")
    assert out == "财库〔2022〕3号"


def test_official_number_rejects_stale_year_when_date_known():
    """生产实例:10 份 2026 年江苏成品油公告全被打上 发改电〔2015〕10号——
    那是正文引用的 2015 年调价机制文件,不是本件文号。"""
    body = "根据现行成品油价格形成机制(发改电〔2015〕10号),现将价格调整如下"
    assert extract_official_number(body, date="2026-06-04") == ""


def test_official_number_keeps_year_boundary_document():
    """跨年发文(文号 2025、发布 2026-01)是正常的,不能误杀。"""
    body = "苏发改价格〔2025〕318号\n\n现将有关事项通知如下"
    assert extract_official_number(body, date="2026-01-08") == "苏发改价格〔2025〕318号"


def test_official_number_keeps_same_year_document():
    body = "发改能源〔2026〕884号\n\n各省级人民政府:"
    assert extract_official_number(body, date="2026-06-25") == "发改能源〔2026〕884号"


def test_official_number_year_rule_inactive_without_date():
    """不给 date 时年份规则不生效(保持既有调用方行为)。"""
    body = "根据现行成品油价格形成机制(发改电〔2015〕10号),现将价格调整如下"
    assert extract_official_number(body) == "发改电〔2015〕10号"


def test_extract_meta_drops_foreign_number_for_jiangsu_case():
    """端到端:江苏成品油公告不再被贴上别人的文号。"""
    from scripts.l1_collect.metadata_extractor import extract_meta
    meta = extract_meta(
        url="https://fzggw.jiangsu.gov.cn/art/2026/6/4/art_84598_11563900.html",
        title="江苏省成品油价格调整公告（2026年第10号）",
        body="根据现行成品油价格形成机制(发改电〔2015〕10号),现将价格调整如下")
    assert meta.date == "2026-06-04"
    assert meta.official_number == ""
