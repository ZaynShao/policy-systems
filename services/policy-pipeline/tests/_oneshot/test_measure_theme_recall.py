"""主题挂载复判测量脚本。

这个脚本的产出会被拿去决定「要不要花 11.5M token 重打全库」,所以它的自检
比它的统计更重要:一份**看起来正常但其实不可信**的百分比,比没有数据危险。

三条自检各有一条用例:
  ① 复判模型不得等于被复判样本的产出模型 —— 同模型自评是复读,不是复判
  ② 抽样必须都能找回原文 —— 找不回是另一个问题,不该在这里被平均掉
  ③ 复判成功率不足 80% 就中止 —— 失败不是随机的(长文超时、编码损伤),
     按剩下的样本算比例会系统性偏
"""
import json

import pytest
import yaml

from scripts._oneshot.measure_theme_recall import (
    assert_enough_judged,
    load_stored,
    main,
    stratified_sample,
)


def _bv(vault, pid, themes, model, d1=0):
    d = vault / "_meta" / "business_view"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{pid}.yaml").write_text(yaml.dump({
        "pid": pid, "themes": themes, "primary_theme": themes[0] if themes else "",
        "scores": {"D1": d1}, "extracted_model": model,
    }, allow_unicode=True), encoding="utf-8")


def _library(tmp_path):
    v = tmp_path / "vault"
    for i in range(20):
        _bv(v, f"P_A_{i}", ["charging_infra"] if i % 2 else [], "model-a")
    for i in range(20):
        _bv(v, f"P_B_{i}", ["charging_infra"] if i % 4 == 0 else [], "model-b")
    return v


def test_load_stored_reads_the_fields_the_measurement_needs(tmp_path):
    v = tmp_path / "vault"
    _bv(v, "P_1", ["charging_infra"], "model-a", d1=5)
    row = load_stored(str(v))["P_1"]
    assert row["themes"] == ["charging_infra"] and row["model"] == "model-a" and row["D1"] == 5


def test_load_stored_skips_unparseable_files_instead_of_crashing(tmp_path):
    v = tmp_path / "vault"
    _bv(v, "P_1", [], "model-a")
    (v / "_meta" / "business_view" / "broken.yaml").write_text("a: [unclosed\n", encoding="utf-8")
    assert list(load_stored(str(v))) == ["P_1"]


def test_sample_is_equal_per_stratum_not_proportional(tmp_path):
    """等额而非按比例:少数层按比例抽只能抽到个位数,置信区间宽到没法用。"""
    stored = load_stored(str(_library(tmp_path)))
    picked = stratified_sample(stored, 20, seed=1)
    counts = {}
    for pid in picked:
        key = (bool(stored[pid]["themes"]), stored[pid]["model"])
        counts[key] = counts.get(key, 0) + 1
    assert len(counts) == 4, "四个层都该被抽到"
    assert len(set(counts.values())) == 1, f"层内应等额,实际 {counts}"


def test_sample_is_reproducible_by_seed(tmp_path):
    """同种子必须给同样本:不然复跑对不上,前后两次测量没法比。"""
    stored = load_stored(str(_library(tmp_path)))
    assert stratified_sample(stored, 20, seed=7) == stratified_sample(stored, 20, seed=7)
    assert stratified_sample(stored, 20, seed=7) != stratified_sample(stored, 20, seed=8)


def test_aborts_when_judge_model_equals_the_model_being_judged(tmp_path):
    """自检①。同模型自评测不出模型差异,而这次要测的恰恰就是模型差异。"""
    v = _library(tmp_path)
    with pytest.raises(SystemExit, match="同模型自评"):
        main(["--vault", str(v), "--judge-model", "model-a", "--n", "8",
              "--state", str(tmp_path / "st")])


def test_aborts_when_sampled_policies_have_no_raw_text(tmp_path):
    """自检②。business_view 与 0_raw 对不上是另一个问题,不该在这里被平均掉。"""
    v = _library(tmp_path)
    (v / "0_raw" / "policies").mkdir(parents=True)   # 空目录:一篇原文都找不回
    with pytest.raises(SystemExit, match="找不到原文"):
        main(["--vault", str(v), "--judge-model", "model-c", "--n", "8",
              "--state", str(tmp_path / "st")])


def test_aborts_when_too_many_judgements_failed(tmp_path):
    """自检③。半份数据配一个看起来正常的百分比,比没有数据危险。"""
    with pytest.raises(SystemExit, match="不可信"):
        assert_enough_judged(70, 100, tmp_path)


def test_accepts_a_tolerable_failure_rate(tmp_path):
    assert_enough_judged(85, 100, tmp_path) is None


def test_empty_library_aborts_instead_of_reporting_zero(tmp_path):
    v = tmp_path / "vault"
    (v / "_meta" / "business_view").mkdir(parents=True)
    with pytest.raises(SystemExit, match="没读到"):
        main(["--vault", str(v), "--judge-model", "model-c", "--state", str(tmp_path / "st")])
