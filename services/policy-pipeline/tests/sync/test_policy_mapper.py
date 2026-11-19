import datetime

import pytest

from scripts.sync.policy_mapper import (
    map_business_view,
    importance_to_enum,
    normalize_level,
    parse_issue_date,
    map_policy_row,
)

def _bv():
    return {
        "pid": "P_2024_NDRC_718",
        "themes": ["power_market", "energy_storage_theme"],
        "primary_theme": "power_market",
        "重要性": 4,
        "scores": {"D1": 5, "D2": 4, "D3": 4, "D4": 4, "D5": 4, "D6": 5},
        "value_tags": ["机会"],
        "影响分析": {"加油": "a", "充电": "b", "电力_储能_V2G_交易": "c"},
        "comprehensive": True,
    }

def test_importance_to_enum_mapping():
    assert importance_to_enum(5) == "STRATEGIC"
    assert importance_to_enum(4) == "MAJOR"
    assert importance_to_enum(3) == "GENERAL"
    assert importance_to_enum(2) == "INFO"
    assert importance_to_enum(1) == "INFO"

def test_map_basic_fields():
    row = map_business_view(_bv(), pipeline_version=1)
    assert row["pipeline_pid"] == "P_2024_NDRC_718"
    assert row["importance"] == "MAJOR"
    assert row["pipeline_version"] == 1

def test_map_themes_is_json_serializable():
    import json
    row = map_business_view(_bv(), pipeline_version=1)
    themes = json.loads(row["pipeline_themes"])
    assert themes[0]["id"] == "power_market"
    assert themes[0]["isPrimary"] is True
    assert themes[1]["isPrimary"] is False

def test_map_scores_and_impact():
    import json
    row = map_business_view(_bv(), pipeline_version=1)
    assert json.loads(row["pipeline_scores"])["D1"] == 5
    assert "充电" in row["pipeline_impact"]

def test_map_comprehensive_flag_in_themes_meta():
    import json
    row = map_business_view(_bv(), pipeline_version=1)
    themes = json.loads(row["pipeline_themes"])
    assert any(t.get("isComprehensive") for t in themes) or row.get("comprehensive") is True

def test_parse_issue_date():
    assert parse_issue_date("2025-05-27") == datetime.date(2025, 5, 27)
    for bad in ["", "abc", None]:
        with pytest.raises(ValueError):
            parse_issue_date(bad)

def test_map_policy_row_includes_core_and_pipeline_fields():
    core = {
        "title": "核心标题",
        "issuer": "发文机关",
        "date": "2025-05-27",
        "content": "正文",
        "doc_number": "文号",
        "source_url": "https://example.com",
        "region": "全国",
        "level": "省",
        "adcode": "370000",
    }
    row = map_policy_row(_bv(), core, pipeline_version=1)
    assert row["title"] == "核心标题"
    assert row["issuer"] == "发文机关"
    assert row["content"] == "正文"
    assert row["source"] == "AUTO"
    assert row["level"] == "省"
    assert row["adcode"] == "370000"
    assert row["issue_date"] == datetime.date(2025, 5, 27)
    assert row["pipeline_pid"] == "P_2024_NDRC_718"
    assert row["importance"] == "MAJOR"

def test_map_policy_row_rejects_bad_date():
    core = {"title": "t", "issuer": "i", "date": "", "content": "c"}
    with pytest.raises(ValueError):
        map_policy_row(_bv(), core, pipeline_version=1)

def test_map_policy_row_rejects_empty_title():
    core = {"title": "", "issuer": "i", "date": "2025-05-27", "content": "c"}
    with pytest.raises(ValueError):
        map_policy_row(_bv(), core, pipeline_version=1)

def test_map_policy_row_rejects_empty_content():
    core = {"title": "t", "issuer": "i", "date": "2025-05-27", "content": ""}
    with pytest.raises(ValueError):
        map_policy_row(_bv(), core, pipeline_version=1)

# --- level 归一化(canonical 集合 国家/省/市/区/县) ---

@pytest.mark.parametrize("canonical", ["国家", "省", "市", "区", "县"])
def test_normalize_level_canonical_is_identity(canonical):
    assert normalize_level(canonical) == canonical

@pytest.mark.parametrize("raw,expect", [
    ("国家级", "国家"), ("中央", "国家"), ("全国", "国家"), ("国", "国家"),
    ("省级", "省"), ("省份", "省"), ("自治区", "省"), ("直辖市", "省"),
    ("市级", "市"), ("地市", "市"), ("地级市", "市"),
    ("区级", "区"), ("市辖区", "区"),
    ("县级", "县"), ("县级市", "县"),
])
def test_normalize_level_maps_known_variants(raw, expect):
    assert normalize_level(raw) == expect

@pytest.mark.parametrize("raw", ["", "   ", None])
def test_normalize_level_blank_is_none(raw):
    assert normalize_level(raw) is None

def test_normalize_level_strips_whitespace():
    assert normalize_level("  省级  ") == "省"

def test_normalize_level_passes_unknown_through_verbatim():
    """未知取值原样透传:宁可让脏值可见,也不静默改写成假的 canonical 值。"""
    assert normalize_level("特别行政区") == "特别行政区"
    assert normalize_level("乡镇") == "乡镇"

def test_map_policy_row_normalizes_level():
    core = {
        "title": "t", "issuer": "i", "date": "2025-05-27", "content": "c",
        "region": "山东", "level": "省级", "adcode": "370000",
    }
    row = map_policy_row(_bv(), core, pipeline_version=1)
    assert row["level"] == "省"

def test_map_policy_row_blank_level_stays_none():
    core = {"title": "t", "issuer": "i", "date": "2025-05-27", "content": "c", "level": "  "}
    assert map_policy_row(_bv(), core, pipeline_version=1)["level"] is None
