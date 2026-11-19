"""检索核心的行为测试。纯函数，不起 Web 服务。"""
from __future__ import annotations

import json

import pytest

from scripts.corpus_service.corpus import MAX_PAGE_SIZE, Corpus, matches, paginate, sort_key

REC_A = {
    "id": "P_2022_JS_1", "title": "关于加强充电基础设施建设的通知",
    "official_number": "苏发改〔2022〕1号", "issuer": ["江苏省发展改革委"],
    "date": "2022-03-09", "region": {"level": "省", "code": "320000", "name": "江苏省"},
    "source_url": "https://example.gov.cn/a", "fetched_at": "2026-06-08T02:18:23+08:00",
    "body": "## 政策原文\n\n充电桩相关内容",
}
REC_B = {
    "id": "P_2024_NDRC_2", "title": "电力中长期交易基本规则",
    "official_number": "发改能源〔2024〕9号", "issuer": ["国家发展改革委"],
    "date": "2024-11-01", "region": {"level": "国", "code": "000000", "name": "全国"},
    "source_url": "https://example.gov.cn/b", "fetched_at": "2026-06-09T02:18:23+08:00",
    "body": "## 政策原文\n\n电力交易内容",
}


@pytest.fixture()
def bundle(tmp_path):
    (tmp_path / "policies.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in (REC_A, REC_B)) + "\n",
        encoding="utf-8",
    )
    index = [{k: v for k, v in r.items() if k != "body"} for r in (REC_A, REC_B)]
    (tmp_path / "index.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "manifest.json").write_text(json.dumps({
        "schema": "policy-corpus-public/v1", "policy_count": 2,
        "fingerprint": "abc123", "generated_at": "2026-07-27T00:00:00+08:00",
        "excluded_count": 1,
        "excluded": [{"file": "internal.md", "reason": "known duplicate of P_X"}],
    }, ensure_ascii=False), encoding="utf-8")
    return tmp_path


# --- 筛选 ------------------------------------------------------------------

def test_empty_filters_match_everything():
    assert matches(REC_A) is True


def test_q_matches_title_and_doc_number_and_issuer():
    assert matches(REC_A, q="充电") is True
    assert matches(REC_A, q="苏发改") is True
    assert matches(REC_A, q="江苏省发展改革委") is True
    assert matches(REC_A, q="风电") is False


def test_q_does_not_search_body():
    """正文含大量网页导航噪音，全文搜命中率高但价值低 —— 明确不搜。"""
    assert matches(REC_A, q="政策原文") is False


def test_region_is_substring_match_and_level_is_exact():
    assert matches(REC_A, region="江苏") is True
    assert matches(REC_A, region="浙江") is False
    assert matches(REC_A, level="省") is True
    assert matches(REC_A, level="市") is False


def test_date_range_is_inclusive():
    assert matches(REC_A, date_from="2022-03-09", date_to="2022-03-09") is True
    assert matches(REC_A, date_from="2022-03-10") is False
    assert matches(REC_A, date_to="2022-03-08") is False


def test_filters_are_conjunctive():
    assert matches(REC_A, q="充电", region="江苏") is True
    assert matches(REC_A, q="充电", region="浙江") is False


# --- 分页 ------------------------------------------------------------------

def test_paginate_slices_and_reports_total():
    items, total = paginate(list(range(10)), page=2, page_size=3)
    assert items == [3, 4, 5]
    assert total == 10


def test_paginate_clamps_page_size_and_handles_out_of_range():
    assert paginate(list(range(300)), 1, 999)[0].__len__() == MAX_PAGE_SIZE
    assert paginate(list(range(5)), 99, 10)[0] == []
    assert paginate(list(range(5)), 0, 10)[0] == list(range(5))  # page<1 视作首页


# --- Corpus ----------------------------------------------------------------

def test_load_indexes_by_id_and_sorts_index_newest_first(bundle):
    c = Corpus.load(bundle)
    assert set(c.records) == {"P_2022_JS_1", "P_2024_NDRC_2"}
    assert [r["id"] for r in c.index] == ["P_2024_NDRC_2", "P_2022_JS_1"]


def test_get_returns_full_record_with_body(bundle):
    assert Corpus.load(bundle).get("P_2022_JS_1")["body"] == REC_A["body"]


def test_get_unknown_id_returns_none(bundle):
    assert Corpus.load(bundle).get("nope") is None


def test_search_results_never_carry_body(bundle):
    """检索结果走 index，绝不能带上 19MB 量级的正文。"""
    for item in Corpus.load(bundle).search()["items"]:
        assert "body" not in item


def test_search_applies_filters_and_reports_total(bundle):
    res = Corpus.load(bundle).search(q="充电")
    assert res["total"] == 1
    assert res["items"][0]["id"] == "P_2022_JS_1"


def test_manifest_excluded_details_are_not_exposed(bundle):
    """排除原因暴露了内部去重判定，属于内部信息，不对外。"""
    m = Corpus.load(bundle).manifest
    assert "excluded" not in m
    assert m["fingerprint"] == "abc123"
    assert "policy_count" in m


def test_sort_key_is_stable_for_same_date():
    same = [dict(REC_A, id="P_B"), dict(REC_A, id="P_A")]
    assert [r["id"] for r in sorted(same, key=sort_key)] == ["P_A", "P_B"]
