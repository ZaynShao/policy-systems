"""MA0→MA3 的编排 CLI。

要点:新鲜度闸不过就中止(宁可不出,不出错稿);每步产物落盘可单独重跑;
--dry-run 不调 LLM,让没有凭据的人也能核对取窗与去重。
"""
import json

import pytest

from scripts.l3_monthly import run_slate as R


def _vault(tmp_path, n=3):
    v = tmp_path / "vault"
    (v / "0_raw" / "policies").mkdir(parents=True)
    (v / "_meta" / "business_view").mkdir(parents=True)
    (v / "_meta" / "business_view" / "x.yaml").write_text("a: 1", encoding="utf-8")
    (v / "_meta" / "framework").mkdir(parents=True)
    (v / "_meta" / "framework" / "business_strategy.yaml").write_text(
        json.dumps({
            "schema_version": 1, "status": "active", "profile_id": "p", "effective_from": "2026-08-31",
            "businesses": [{"id": "fuel", "zh": "加油", "decision_variables": ["批发价"]},
                           {"id": "charging", "zh": "充电", "decision_variables": ["定价"]},
                           {"id": "power", "zh": "电力", "decision_variables": ["现货规则"]}],
            "relevance_rules": {"core_test": "是否改变决策变量"},
            "signals": [{"id": "F02", "business": "fuel", "weight": "high", "what": "发票管理"}],
            "consistency": {"impact_keys": {"fuel": "加油", "charging": "充电",
                                            "power": "电力_储能_V2G_交易"}},
        }, ensure_ascii=False), encoding="utf-8")
    for i in range(n):
        (v / "0_raw" / "policies" / f"p{i}.md").write_text(
            f"---\nid: P_{i}\ntitle: 关于印发《第{i}号办法》的通知\ndate: '2026-07-0{i+1}'\n"
            f"region:\n  level: 国\n  name: 国家发展改革委\n---\n"
            f"## 政策原文\n国家发展改革委\n正文内容{i}\n2026年7月{i+1}日\n", encoding="utf-8")
    return v


def _state(tmp_path):
    s = tmp_path / "state"
    (s / "analysis_layer" / "nightly").mkdir(parents=True)
    (s / "analysis_layer" / "nightly" / "analysis_context.jsonl").write_text(
        '{"policy_id":"P_0"}\n', encoding="utf-8")
    return s


class _Fake:
    def __init__(self, judge_reply, slate_reply):
        self.j, self.s = judge_reply, slate_reply
        self.n = 0

    def complete(self, system, user, max_tokens=1024):
        self.n += 1
        return self.s if "本期月份" in user else self.j


def _judge_json():
    return json.dumps({"level": "国家", "issue_date_from_body": "2026-07-01",
                       "business_hits": ["fuel"], "decision_variables_touched": ["批发价"],
                       "relevance": "high", "why": "改批发价", "dq": ""}, ensure_ascii=False)


def _slate_json():
    return json.dumps({"month": "2026-07", "narrative": "本月定调",
                       "sections": {"national_detail": [
                           {"policy_id": "P_0", "title_hint": "第0号", "score": "5分",
                            "rank": 1, "why": "旗舰", "dq": ""}],
                           "local_detail": [], "roundup": [], "appendix": []}},
                      ensure_ascii=False)


def test_dry_run_writes_candidates_and_shortlist_without_llm(tmp_path):
    out = tmp_path / "out"
    rep = R.run(month="2026-07", vault=str(_vault(tmp_path)), state=str(_state(tmp_path)),
                out=str(out), client=None, dry_run=True)
    assert (out / "candidates.jsonl").exists() and (out / "shortlist.jsonl").exists()
    assert not (out / "judgments.jsonl").exists(), "dry-run 不该调 LLM"
    assert rep["counts"]["candidates"] == 3


def test_full_run_writes_all_artifacts(tmp_path):
    out = tmp_path / "out"
    c = _Fake(_judge_json(), _slate_json())
    rep = R.run(month="2026-07", vault=str(_vault(tmp_path)), state=str(_state(tmp_path)),
                out=str(out), client=c, dry_run=False)
    for f in ("candidates.jsonl", "shortlist.jsonl", "gap_report.json",
              "judgments.jsonl", "slate.json", "run_report.json"):
        assert (out / f).exists(), f"缺产物 {f}"
    slate = json.loads((out / "slate.json").read_text(encoding="utf-8"))
    assert slate["month"] == "2026-07"
    assert rep["counts"]["judged"] == 3


def test_freshness_gate_aborts_before_spending_tokens(tmp_path):
    """上游没重算就中止:月刊一个月一期,晚一天有人补跑;用陈数据出一期发给决策层,
    错误会被当成事实带走。"""
    v = _vault(tmp_path)
    bare = tmp_path / "emptystate"
    bare.mkdir()
    c = _Fake(_judge_json(), _slate_json())
    with pytest.raises(R.FreshnessError) as e:
        R.run(month="2026-07", vault=str(v), state=str(bare), out=str(tmp_path / "o"),
              client=c, dry_run=False)
    assert "analysis_context" in str(e.value)
    assert c.n == 0, "闸没过就不该花掉任何 token"


def test_missing_strategy_profile_aborts(tmp_path):
    v = _vault(tmp_path)
    (v / "_meta" / "framework" / "business_strategy.yaml").unlink()
    with pytest.raises(R.FreshnessError):
        R.run(month="2026-07", vault=str(v), state=str(_state(tmp_path)),
              out=str(tmp_path / "o"), client=_Fake(_judge_json(), _slate_json()),
              dry_run=False)


def test_gap_check_uses_whole_vault_not_the_window(tmp_path):
    """缺口对账要拿全库比,不是窗口内候选——否则日期在窗外的库内文件会被报成假缺口。"""
    v = _vault(tmp_path)
    (v / "0_raw" / "policies" / "old.md").write_text(
        "---\nid: P_OLD\ntitle: 关于印发《陈年办法》的通知\ndate: '2025-01-01'\n---\n"
        "## 政策原文\n正文\n", encoding="utf-8")
    seen = {}

    def fake_search(query, max_results=5):
        return [{"title": "关于印发《陈年办法》的通知", "url": "u", "content": ""}]

    out = tmp_path / "out"
    R.run(month="2026-07", vault=str(v), state=str(_state(tmp_path)), out=str(out),
          client=_Fake(_judge_json(), _slate_json()), dry_run=False, search_fn=fake_search)
    rep = json.loads((out / "gap_report.json").read_text(encoding="utf-8"))
    assert rep["summary"]["gaps"] == 0, "库里有(即使日期在窗外)就不是缺口"


def test_build_client_maps_provider():
    from scripts.common.llm import OpenAICompatClient
    assert isinstance(R.build_client("openai", "deepseek-v4-pro", "/tmp/x.jsonl"),
                      OpenAICompatClient)


def test_empty_analysis_context_warns_but_does_not_abort(tmp_path):
    """空的 analysis_context 是**本地路线的合法 stub**(方法正本要求这么放),
    但在生产上它意味着 nightly 跑出了空结果——所以放行加告警,而不是一刀切中止。
    """
    s = tmp_path / "state"
    (s / "analysis_layer" / "nightly").mkdir(parents=True)
    (s / "analysis_layer" / "nightly" / "analysis_context.jsonl").write_text(
        "", encoding="utf-8")
    rep = R.run(month="2026-07", vault=str(_vault(tmp_path)), state=str(s),
                out=str(tmp_path / "o"), client=None, dry_run=True)
    assert any("analysis_context" in w and "空" in w for w in rep["warnings"])


def test_non_empty_analysis_context_has_no_warning(tmp_path):
    rep = R.run(month="2026-07", vault=str(_vault(tmp_path)), state=str(_state(tmp_path)),
                out=str(tmp_path / "o"), client=None, dry_run=True)
    assert rep["warnings"] == []
