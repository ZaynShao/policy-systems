"""public_export 的脱敏契约测试。

红线：本模块的唯一职责是保证**只有政策原文出库**。
任何放宽白名单的改动都必须先让这里的测试失败。
"""
from __future__ import annotations

import datetime
import json

import pytest

from scripts.public_export.redact import (
    PUBLIC_PROVENANCE_FIELDS,
    PUBLIC_REGION_FIELDS,
    PUBLIC_TOP_FIELDS,
    ExcludedPolicy,
    split_frontmatter,
    to_public_record,
)


# 取自真实语料的 frontmatter 形状：provenance 全语料共 41 个子字段，
# 这里塞进最容易泄露内部过程的一批，确保它们一个都出不去。
FULL_FM = {
    "id": "P_2022_JS_X_1",
    "aliases": ["P_2022_JS_X_1"],
    "title": "2022年全省市场监管主要任务分工方案",
    "official_number": "苏市监〔2022〕1号",
    "issuer": ["江苏省市场监督管理局"],
    "issuer_canonical": ["江苏省市场监管局"],
    "date": "2022-03-09",
    "type": "policy",
    "subtype": "分工方案",
    "tags": ["市场监管"],
    "confidence": 0.85,
    "dup_aliases": ["P_2022_JS_X_9"],
    "dedup_at": "2026-06-10T00:00:00+08:00",
    "dedup_rule": "title+date",
    "region": {
        "level": "省",
        "code": "320000",
        "name": "江苏省市场监督管理局",
        "needs_city_code": True,
    },
    "provenance": {
        "url": "https://scjgj.jiangsu.gov.cn/art/2022/3/9/art_78958_10370828.html",
        "fetched_at": "2026-06-08T02:18:23+08:00",
        "source_type": "A",
        "fetched_via": "firecrawl",
        "fetched_method": "render",
        "collected_by": "t1-city-collection",
        "collected_mode": "build-phase-manual",
        "confidence": 0.85,
        "audit_run": "run_20260608",
        "candidate_priority": 3,
        "src_count": 2,
        "id_fixed_at": "2026-06-12T00:00:00+08:00",
        "id_fixed_method": "llm",
        "id_fixed_from": "P_2022_JS_X_0",
        "id_fix_confidence": 0.9,
        "relevel_at": "2026-06-13T00:00:00+08:00",
        "relevel_method": "rule",
        "relevel_from": "市",
        "region_fixed_from": "江苏省",
        "date_fixed_from": "2022-03-10",
        "issuer_fixed_from": "江苏市监局",
        "issuer_canonical_fixed_from": "苏市监",
        "body_refetched_at": "2026-06-20T00:00:00+08:00",
        "body_pre_refetch_len": 1024,
        "date_correction_reason": "原站更正",
        "fm_repaired_reason": "缺 issuer",
    },
}

BODY = "## 政策原文\n\n为深入贯彻……\n\n一、深化营商环境改革\n"


# --- 白名单本身 ------------------------------------------------------------

def test_whitelists_are_exactly_what_was_agreed():
    """白名单是需求裁定的结果，不是实现细节 —— 改它等于改对外承诺。"""
    assert PUBLIC_TOP_FIELDS == ("id", "title", "official_number", "issuer", "date")
    assert PUBLIC_REGION_FIELDS == ("level", "code", "name")
    assert PUBLIC_PROVENANCE_FIELDS == ("url", "fetched_at")


# --- 核心脱敏行为 ----------------------------------------------------------

def test_public_record_has_no_key_outside_whitelist():
    rec = to_public_record(FULL_FM, BODY)
    assert set(rec) == {
        "id", "title", "official_number", "issuer", "date",
        "region", "source_url", "fetched_at", "body",
    }
    assert set(rec["region"]) == {"level", "code", "name"}


@pytest.mark.parametrize("leaked", [
    "aliases", "issuer_canonical", "confidence", "type", "subtype", "tags",
    "dup_aliases", "dedup_at", "dedup_rule", "provenance",
])
def test_internal_top_level_fields_never_surface(leaked):
    rec = to_public_record(FULL_FM, BODY)
    assert leaked not in rec


@pytest.mark.parametrize("leaked", [
    "source_type", "fetched_via", "fetched_method", "collected_by", "collected_mode",
    "confidence", "audit_run", "candidate_priority", "src_count",
    "id_fixed_from", "id_fixed_method", "id_fix_confidence",
    "relevel_from", "relevel_method", "region_fixed_from", "date_fixed_from",
    "issuer_fixed_from", "issuer_canonical_fixed_from",
    "body_pre_refetch_len", "date_correction_reason", "fm_repaired_reason",
])
def test_provenance_repair_trail_never_surfaces(leaked):
    """采集手段与数据修复轨迹属于内部产出物，一律不出库。"""
    flat = repr(to_public_record(FULL_FM, BODY))
    assert leaked not in flat


def test_region_needs_city_code_is_dropped():
    rec = to_public_record(FULL_FM, BODY)
    assert "needs_city_code" not in rec["region"]


def test_unknown_future_field_is_excluded_by_default():
    """白名单的意义：pipeline 将来新增字段，默认不外泄，无需改这里。"""
    fm = dict(FULL_FM, brand_new_internal_score=0.42)
    fm["provenance"] = dict(FULL_FM["provenance"], brand_new_trace="internal")
    flat = repr(to_public_record(fm, BODY))
    assert "brand_new_internal_score" not in flat
    assert "brand_new_trace" not in flat


# --- 正文：原样给 ----------------------------------------------------------

def test_body_is_passed_through_verbatim():
    """需求裁定：正文原样给，不去噪。含网页导航/图片也照给。"""
    noisy = "## 政策原文\n\n无障碍阅读长者浏览模式\n\n![](https://x/y.png)\n\n正文……"
    assert to_public_record(FULL_FM, noisy)["body"] == noisy


def test_issuer_uses_raw_not_canonical():
    """issuer_canonical 是 L2 派生，对外只给 raw issuer。"""
    assert to_public_record(FULL_FM, BODY)["issuer"] == ["江苏省市场监督管理局"]


def test_source_url_and_fetched_at_are_lifted_from_provenance():
    rec = to_public_record(FULL_FM, BODY)
    assert rec["source_url"] == FULL_FM["provenance"]["url"]
    assert rec["fetched_at"] == FULL_FM["provenance"]["fetched_at"]


# --- JSON 可序列化 ---------------------------------------------------------

def test_yaml_native_dates_are_normalised_to_iso_strings():
    """真语料里未加引号的 date 会被 YAML 解析成 date/datetime 对象，
    直接 json.dumps 会炸。对外记录必须始终是 JSON-safe 的。"""
    fm = dict(FULL_FM, date=datetime.date(2022, 3, 9))
    fm["provenance"] = dict(
        FULL_FM["provenance"],
        fetched_at=datetime.datetime(2026, 6, 8, 2, 18, 23),
    )
    rec = to_public_record(fm, BODY)
    assert rec["date"] == "2022-03-09"
    assert rec["fetched_at"].startswith("2026-06-08T02:18:23")
    json.dumps(rec, ensure_ascii=False)  # 不抛即通过


def test_whole_record_is_json_serialisable():
    json.dumps(to_public_record(FULL_FM, BODY), ensure_ascii=False)


# --- 排除规则 --------------------------------------------------------------

def test_known_duplicate_is_excluded():
    fm = dict(FULL_FM, _duplicate_of="P_2022_JS_X_1", _duplicate_reason="same title+date")
    with pytest.raises(ExcludedPolicy):
        to_public_record(fm, BODY)


def test_missing_id_is_excluded():
    fm = {k: v for k, v in FULL_FM.items() if k != "id"}
    with pytest.raises(ExcludedPolicy):
        to_public_record(fm, BODY)


def test_empty_body_is_excluded():
    with pytest.raises(ExcludedPolicy):
        to_public_record(FULL_FM, "   \n  ")


# --- frontmatter 切分 ------------------------------------------------------

def test_split_frontmatter_keeps_body_verbatim():
    text = "---\nid: P_1\ntitle: T\n---\n\n## 政策原文\n\n正文\n"
    fm, body = split_frontmatter(text)
    assert fm == {"id": "P_1", "title": "T"}
    assert body == "## 政策原文\n\n正文\n"


def test_split_frontmatter_without_frontmatter_yields_empty_mapping():
    fm, body = split_frontmatter("没有 frontmatter 的正文")
    assert fm == {}
    assert body == "没有 frontmatter 的正文"


def test_split_frontmatter_does_not_treat_body_hr_as_delimiter():
    """正文里的 --- 分隔线不能被当成 frontmatter 结束符。"""
    text = "---\nid: P_1\n---\n\n正文上半\n\n---\n\n正文下半\n"
    fm, body = split_frontmatter(text)
    assert fm == {"id": "P_1"}
    assert "正文上半" in body and "正文下半" in body
