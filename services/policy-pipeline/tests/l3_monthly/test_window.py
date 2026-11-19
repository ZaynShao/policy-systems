"""MA0 取窗 + 新鲜度闸。

取窗的唯一职责是**别漏**:frontmatter date 已知不可靠(常是生效日/发布日),
所以窗口故意撒 [M-1, M+1] 三个月,真实归属交 MA2 按 RAW 落款判。
新鲜度闸的职责是**宁可不出,不出错稿**——上游没重算就中止,不静默降级。
"""
import json
import os

import pytest

from scripts.l3_monthly import window as w


# ── 窗口 ────────────────────────────────────────────────────────
def test_month_window_spans_prev_and_next():
    assert w.month_window("2026-07") == ("2026-06", "2026-08")


def test_month_window_crosses_year_boundary():
    assert w.month_window("2026-01") == ("2025-12", "2026-02")
    assert w.month_window("2026-12") == ("2026-11", "2027-01")


def test_month_window_rejects_bad_format():
    with pytest.raises(ValueError):
        w.month_window("2026/07")


def test_in_window():
    assert w.in_window("2026-06-30", "2026-07") is True
    assert w.in_window("2026-08-31", "2026-07") is True
    assert w.in_window("2026-05-31", "2026-07") is False
    assert w.in_window("2026-09-01", "2026-07") is False


# ── 候选收集 ────────────────────────────────────────────────────
def _write(pol_dir, name, *, pid, title, date=None, docno=None, body="正文"):
    fm = [f"id: {pid}", f"title: {title}"]
    if date is not None:
        fm.append(f"date: '{date}'")
    if docno is not None:
        fm.append(f"official_number: {docno}")
    fm += ["region:", "  level: 国", "  name: 国家发展改革委"]
    (pol_dir / name).write_text("---\n" + "\n".join(fm) + "\n---\n## 政策原文\n" + body,
                                encoding="utf-8")


def test_collect_candidates_keeps_only_window(tmp_path):
    pol = tmp_path / "0_raw" / "policies"
    pol.mkdir(parents=True)
    _write(pol, "a.md", pid="P_A", title="窗内", date="2026-07-10")
    _write(pol, "b.md", pid="P_B", title="窗前", date="2026-04-01")
    got = {c.policy_id for c in w.collect_candidates(str(tmp_path), "2026-07")}
    assert got == {"P_A"}


def test_collect_candidates_keeps_dateless_flagged_not_dropped(tmp_path):
    """没 date 的不能静默丢——frontmatter 缺字段不等于这篇与本月无关。"""
    pol = tmp_path / "0_raw" / "policies"
    pol.mkdir(parents=True)
    _write(pol, "a.md", pid="P_A", title="无日期", date=None)
    cands = w.collect_candidates(str(tmp_path), "2026-07")
    assert [c.policy_id for c in cands] == ["P_A"]
    assert cands[0].date_missing is True


def test_candidate_body_len_matches_packer_notion_of_body(tmp_path):
    """body_len 必须与装包器 build_bundle 对 body 的取法一致。

    它的用途是 MA1 去重时比「谁的 RAW 更完整」;如果这里算的 body 和 MA4 实际装进
    bundle 的不是同一段,就会出现「留下的那份反而更短」。故直接与装包器的表达式对齐。
    """
    pol = tmp_path / "0_raw" / "policies"
    pol.mkdir(parents=True)
    _write(pol, "a.md", pid="P_A", title="甲", date="2026-07-10", body="正文" * 50)
    c = w.collect_candidates(str(tmp_path), "2026-07")[0]
    assert c.raw_path.endswith("a.md")
    raw = (pol / "a.md").read_text(encoding="utf-8")
    assert c.body_len == len(raw.split("---", 2)[-1].strip())
    assert c.body_len >= len("正文" * 50)


# ── 新鲜度闸 ────────────────────────────────────────────────────
def _mk_state(tmp_path, *, ac_lines=1):
    nightly = tmp_path / "analysis_layer" / "nightly"
    nightly.mkdir(parents=True)
    p = nightly / "analysis_context.jsonl"
    p.write_text("".join(json.dumps({"policy_id": f"P_{i}"}) + "\n"
                         for i in range(ac_lines)), encoding="utf-8")
    return p


def test_freshness_passes_on_fresh_state(tmp_path):
    vault = tmp_path / "v"
    (vault / "_meta" / "business_view").mkdir(parents=True)
    (vault / "_meta" / "business_view" / "P_A.yaml").write_text("x: 1", encoding="utf-8")
    (vault / "_meta" / "framework").mkdir(parents=True)
    (vault / "_meta" / "framework" / "business_strategy.yaml").write_text("x: 1", encoding="utf-8")
    state = tmp_path / "s"
    state.mkdir()
    _mk_state(state)
    assert w.freshness_problems(str(vault), str(state), max_age_hours=48) == []


def test_freshness_flags_missing_analysis_context(tmp_path):
    vault = tmp_path / "v"
    (vault / "_meta" / "business_view").mkdir(parents=True)
    (vault / "_meta" / "business_view" / "P_A.yaml").write_text("x: 1", encoding="utf-8")
    (vault / "_meta" / "framework").mkdir(parents=True)
    (vault / "_meta" / "framework" / "business_strategy.yaml").write_text("x: 1", encoding="utf-8")
    state = tmp_path / "s"
    state.mkdir()
    probs = w.freshness_problems(str(vault), str(state))
    assert any("analysis_context" in p for p in probs)


def test_freshness_flags_stale_analysis_context(tmp_path):
    vault = tmp_path / "v"
    (vault / "_meta" / "business_view").mkdir(parents=True)
    (vault / "_meta" / "business_view" / "P_A.yaml").write_text("x: 1", encoding="utf-8")
    (vault / "_meta" / "framework").mkdir(parents=True)
    (vault / "_meta" / "framework" / "business_strategy.yaml").write_text("x: 1", encoding="utf-8")
    state = tmp_path / "s"
    state.mkdir()
    p = _mk_state(state)
    os.utime(p, (0, 0))                      # 1970 年的文件 = 明显过期
    probs = w.freshness_problems(str(vault), str(state), max_age_hours=48)
    assert any("过期" in x for x in probs)


def test_freshness_flags_missing_strategy_profile(tmp_path):
    """画像缺失必须拦下:业务口径是月刊相关性判据的唯一来源。"""
    vault = tmp_path / "v"
    (vault / "_meta" / "business_view").mkdir(parents=True)
    (vault / "_meta" / "business_view" / "P_A.yaml").write_text("x: 1", encoding="utf-8")
    state = tmp_path / "s"
    state.mkdir()
    _mk_state(state)
    probs = w.freshness_problems(str(vault), str(state))
    assert any("business_strategy" in p for p in probs)
