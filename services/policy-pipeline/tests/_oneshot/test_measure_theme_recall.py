"""主题挂载复判测量脚本。

这个脚本的产出会被拿去决定「要不要花 11.5M token 重打全库」,所以它的自检
比它的统计更重要:一份**看起来正常但其实不可信**的百分比,比没有数据危险。

四条自检各有一条用例:
  ① 复判模型不得等于被复判样本的产出模型 —— 同模型自评是复读,不是复判
  ①′ 而且要比**网关自报的**名字:网关会把不存在的模型名静默映射到 flash,
     只比请求名的话这条守卫形同虚设(2026-09-03 探路轮就这么废了)
  ② 抽样必须都能找回原文 —— 找不回是另一个问题,不该在这里被平均掉
  ③ 复判成功率不足 80% 就中止 —— 失败不是随机的(长文超时、编码损伤),
     按剩下的样本算比例会系统性偏
"""
import json

import pytest
import yaml

from scripts._oneshot.measure_theme_recall import (
    assert_enough_judged,
    assert_judge_is_not_self_by_alias,
    assert_resume_is_same_judge,
    load_done_rows,
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


# ── 模型吐 null 不能把整轮打崩 ──────────────────────────────────────
#
# 2026-09-02 实况:跑到第 91/100 篇崩掉,前 90 篇的复判结果没来得及落盘。
# 成因是 parse_json_block 用 json.loads,而 **json.loads("null") 成功返回 None、不抛**,
# 所以 `except Exception` 那层挡不住,下一行 out.get("themes") 直接 AttributeError。
# 一轮复判是真金白银,一篇畸形输出不该让整轮作废。
def _raw(vault, pid, title="某某政策"):
    d = vault / "0_raw" / "policies"
    d.mkdir(parents=True, exist_ok=True)
    # pid 取自 frontmatter 的 `id`(不是 `pid`),见 l1_audit/corpus.parse_policy_file
    (d / f"{pid}.md").write_text(
        f"---\nid: {pid}\ntitle: {title}\nissuer: [某某局]\n---\n\n正文若干。\n",
        encoding="utf-8")


def _framework(vault):
    """脚本会 load 主题登记表和打分体系(pass1 的原提示词就是拿它们拼的)。"""
    (vault / "_meta" / "framework").mkdir(parents=True, exist_ok=True)
    (vault / "_meta" / "themes_registry.yaml").write_text(
        yaml.dump({"themes": [
            {"id": "charging_infra", "zh": "充电基建", "aliases": ["充电桩"]},
            {"id": "v2g", "zh": "车网互动", "aliases": ["V2G"]},
        ]}, allow_unicode=True), encoding="utf-8")
    (vault / "_meta" / "framework" / "scoring.yaml").write_text(
        "dimensions: {D1: {name: 业务关联度}}\n", encoding="utf-8")


class _FakeClient:
    """按脚本给的 user 依次返回预设文本。complete 签名与真客户端一致。

    ``reported`` 模拟网关在响应里自报的模型名(真客户端把它放在
    ``last_reported_model``)。默认 None = 端点没回 model 字段。
    """

    def __init__(self, outputs, reported=None):
        self.outputs = list(outputs)
        self.calls = 0
        self.last_reported_model = reported

    def complete(self, system, user, max_tokens=None):
        self.calls += 1
        return self.outputs.pop(0) if self.outputs else "null"


def test_json_null_parses_to_none_without_raising():
    """这条钉住的是崩溃的根因,不是 workaround。"""
    from scripts.l2_themescore.generator import parse_json_block

    assert parse_json_block("null") is None          # 不抛,返回 None
    assert parse_json_block("```json\nnull\n```") is None


def test_call_log_cannot_be_used_to_salvage_a_crashed_run():
    """钉住一个反直觉的事实:judge_calls.jsonl **救不了场**。

    2026-09-02 那轮崩在第 91/100 篇,当时以为"输出都在调用日志里、钱没白花"。
    并不是——scripts/common/llm.py 的 _log_call 只记 prompt_sha 与 output_chars,
    既不存提示词也不存输出。所以断点续跑只能靠本脚本自己边跑边落盘。
    这条用例的作用是:哪天有人给 _log_call 加了字段,这里会失败,提醒他复用成为可能。
    """
    import inspect

    from scripts.common import llm

    src = inspect.getsource(llm._log_call)
    assert '"output_chars"' in src and '"prompt_sha"' in src
    assert '"output":' not in src, "_log_call 开始存输出了?那断点续跑可以改用它"


def test_load_done_rows_reads_back_finished_items(tmp_path):
    d = tmp_path / "detail.jsonl"
    d.write_text(
        json.dumps({"pid": "P_1", "verdict": "疑似漏检"}) + "\n"
        + json.dumps({"pid": "P_2", "verdict": "一致-零主题"}) + "\n",
        encoding="utf-8")
    assert [r["pid"] for r in load_done_rows(d)] == ["P_1", "P_2"]


def test_load_done_rows_tolerates_a_truncated_last_line(tmp_path):
    """崩在写一半时最后一行可能是残的,不该让续跑起不来。"""
    d = tmp_path / "detail.jsonl"
    d.write_text(json.dumps({"pid": "P_1"}) + "\n" + '{"pid": "P_2", "verd', encoding="utf-8")
    assert [r["pid"] for r in load_done_rows(d)] == ["P_1"]


def test_load_done_rows_on_missing_file(tmp_path):
    assert load_done_rows(tmp_path / "没有.jsonl") == []


def test_one_null_output_does_not_kill_the_whole_run(tmp_path, capsys):
    """端到端:4 篇里有一篇吐 null,其余 3 篇的结果必须照常产出。

    这是 2026-09-02 那次崩溃的回归用例。当时跑到第 91/100 篇崩掉,
    前 90 篇的复判结果全部丢失——而复判一轮是要花钱的。
    """
    v = tmp_path / "vault"
    _framework(v)
    for i in range(10):
        pid = f"P_X_{i}"
        _bv(v, pid, ["charging_infra"] if i % 2 else [], "model-a")
        _raw(v, pid)
    ok = '{"themes":["charging_infra"],"scores":{"D1":5}}'
    # 第 3 篇吐 null(合法 JSON、解析成 None——正是崩溃的那种输入)。
    # 10 篇挂 1 篇 = 10% 失败率,在自检③的 20% 容忍线内,应当照常出报告。
    client = _FakeClient([ok, ok, "null"] + [ok] * 7)
    state = tmp_path / "st"
    rc = main(["--vault", str(v), "--judge-model", "model-c", "--n", "10",
               "--state", str(state)], _client=client)
    assert rc == 0, "一篇畸形输出不该让整轮失败"
    rows = [json.loads(l) for l in (state / "detail.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 9, f"应保住另外 9 篇,实际 {len(rows)}"
    assert "不是对象" in capsys.readouterr().err, "跳过的那篇要说明原因"


def test_results_are_written_as_they_go_and_resume_skips_them(tmp_path):
    """结果逐条落盘,--resume 接着跑——崩了只丢当前那一篇,不是整轮。"""
    v = tmp_path / "vault"
    _framework(v)
    for i in range(10):
        pid = f"P_X_{i}"
        _bv(v, pid, ["charging_infra"] if i % 2 else [], "model-a")
        _raw(v, pid)

    ok = '{"themes":["charging_infra"],"scores":{"D1":5}}'
    state = tmp_path / "st"
    first = _FakeClient([ok] * 10)
    main(["--vault", str(v), "--judge-model", "model-c", "--n", "10",
          "--state", str(state)], _client=first)
    assert first.calls == 10
    assert len((state / "detail.jsonl").read_text(encoding="utf-8").strip().splitlines()) == 10

    # 续跑:全都做过了,一次模型都不该调
    second = _FakeClient([])
    main(["--vault", str(v), "--judge-model", "model-c", "--n", "10",
          "--state", str(state), "--resume"], _client=second)
    assert second.calls == 0, "已完成的 pid 不该再调模型"


def test_without_resume_the_old_detail_file_is_discarded(tmp_path):
    """不带 --resume 就从头来:新旧两轮的结果不能混在一个文件里。"""
    v = tmp_path / "vault"
    _framework(v)
    for i in range(10):
        pid = f"P_X_{i}"
        _bv(v, pid, ["charging_infra"] if i % 2 else [], "model-a")
        _raw(v, pid)
    ok = '{"themes":["charging_infra"],"scores":{"D1":5}}'
    state = tmp_path / "st"
    main(["--vault", str(v), "--judge-model", "model-c", "--n", "10",
          "--state", str(state)], _client=_FakeClient([ok] * 10))
    main(["--vault", str(v), "--judge-model", "model-c", "--n", "10",
          "--state", str(state)], _client=_FakeClient([ok] * 10))
    assert len((state / "detail.jsonl").read_text(encoding="utf-8").strip().splitlines()) == 10


# ── 自检①′:网关别名把「换了模型」变成「没换」 ──────────────────────
#
# 2026-09-03 实况:探路轮点名 deepseek-chat 跑了 40 篇,自检①放行(字符串不等),
# 报出 39/40 一致。但网关 /models 里根本没有 deepseek-chat,它被静默映射成
# deepseek-v4-flash——也就是被复判那批自己的产出模型。那 39/40 是复读率,
# 不是漏检率,整轮作废。守卫只能建立在**网关自报的**模型名上。
def _lib_with_raw(tmp_path, n=10, model="model-a"):
    v = tmp_path / "vault"
    _framework(v)
    for i in range(n):
        pid = f"P_X_{i}"
        _bv(v, pid, ["charging_infra"] if i % 2 else [], model)
        _raw(v, pid)
    return v


def test_alias_guard_rejects_a_reported_model_that_matches_the_judged_cohort():
    with pytest.raises(SystemExit, match="网关自报"):
        assert_judge_is_not_self_by_alias(
            "deepseek-chat", "deepseek-v4-flash", {"deepseek-v4-flash"})


def test_alias_guard_passes_when_the_gateway_really_gave_another_model():
    assert assert_judge_is_not_self_by_alias(
        "deepseek-v4-pro", "deepseek-v4-pro", {"deepseek-v4-flash"}) is None


def test_alias_guard_passes_when_the_endpoint_reports_nothing():
    """兼容端点不回 model 字段时不能硬拦——拦了脚本对着这类端点就没法跑。"""
    assert assert_judge_is_not_self_by_alias("m", None, {"model-a"}) is None


def test_run_aborts_on_the_first_call_when_the_gateway_aliased_the_judge(tmp_path):
    """端到端:名义换了模型,网关其实没换 → 花掉一次调用就停,不是跑完 200 次才发现。"""
    v = _lib_with_raw(tmp_path)
    ok = '{"themes":["charging_infra"],"scores":{"D1":5}}'
    client = _FakeClient([ok] * 10, reported="model-a")   # 库里正是 model-a 产的
    state = tmp_path / "st"
    with pytest.raises(SystemExit, match="网关自报"):
        main(["--vault", str(v), "--judge-model", "看起来不一样的名字", "--n", "10",
              "--state", str(state)], _client=client)
    assert client.calls == 1, "第一次调用就该停,不该把预算跑完"
    assert not (state / "detail.jsonl").exists(), "被别名的结果一行都不该落盘"


def test_rows_record_both_the_asked_and_the_reported_judge(tmp_path):
    v = _lib_with_raw(tmp_path)
    ok = '{"themes":["charging_infra"],"scores":{"D1":5}}'
    state = tmp_path / "st"
    main(["--vault", str(v), "--judge-model", "model-c", "--n", "10", "--state", str(state)],
         _client=_FakeClient([ok] * 10, reported="model-c-actual"))
    row = json.loads((state / "detail.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert row["judge"] == "model-c" and row["judge_reported"] == "model-c-actual"


# ── 续跑不能把两个复判模型的结果混在一起 ──────────────────────────
def test_resume_refuses_to_mix_results_from_a_different_judge():
    with pytest.raises(SystemExit, match="不能混算"):
        assert_resume_is_same_judge([{"pid": "P_1", "judge": "model-x"}], "model-c")


def test_resume_refuses_rows_from_before_judge_was_recorded():
    """探路轮那批没有 judge 字段——它们正是要作废的那批,不能被 --resume 捡回来。"""
    with pytest.raises(SystemExit, match="不能混算"):
        assert_resume_is_same_judge([{"pid": "P_1", "verdict": "一致-零主题"}], "model-c")


def test_resume_accepts_rows_from_the_same_judge():
    assert assert_resume_is_same_judge([{"pid": "P_1", "judge": "model-c"}], "model-c") is None


# ── --strata zero-theme:把预算全押在漏检方向 ──────────────────────
#
# 为什么要这个开关:四层等额时同样的 n 只有一半落在零主题上,而"零主题里漏了多少"
# 才是"要不要重打全库分"唯一依赖的数。n=10 时 0/10 的 95% 上界是 31%,
# "一篇没漏"和"漏了三成"分不开;押到 50 篇上界降到 7.1%。
# 代价是这一轮量不到误挂——那是另一个决定要用的数。
def test_zero_theme_strata_samples_only_the_unthemed_layers(tmp_path):
    stored = load_stored(str(_library(tmp_path)))
    picked = stratified_sample(stored, 20, seed=1, only_zero_theme=True)
    assert picked, "该抽到东西"
    assert all(not stored[p]["themes"] for p in picked), "只能抽零主题的"
    assert len({stored[p]["model"] for p in picked}) == 2, "两个产出模型都要覆盖"


def test_zero_theme_strata_doubles_the_sample_on_the_layers_that_matter(tmp_path):
    """同样的 n,押在两层上每层拿到的篇数应是四层等额时的两倍。"""
    stored = load_stored(str(_library(tmp_path)))
    four = stratified_sample(stored, 20, seed=1)
    two = stratified_sample(stored, 20, seed=1, only_zero_theme=True)
    zero_in_four = [p for p in four if not stored[p]["themes"]]
    assert len(two) == 2 * len(zero_in_four), f"{len(two)} vs {len(zero_in_four)}"


def test_default_still_measures_both_directions(tmp_path):
    """默认不变:漏检与误挂同时量。收窄是显式选项,不是新默认。"""
    stored = load_stored(str(_library(tmp_path)))
    picked = stratified_sample(stored, 20, seed=1)
    assert any(stored[p]["themes"] for p in picked)
    assert any(not stored[p]["themes"] for p in picked)


def test_zero_theme_run_says_it_did_not_measure_the_other_direction(tmp_path, capsys):
    """报告里不能只是"误挂 0%"——那会被读成"没有误挂",实际是没量。"""
    v = _lib_with_raw(tmp_path)
    state = tmp_path / "st"
    main(["--vault", str(v), "--judge-model", "model-c", "--n", "10",
          "--strata", "zero-theme", "--state", str(state)],
         _client=_FakeClient(["null"] * 0 + ['{"themes":[],"scores":{"D1":0}}'] * 10))
    out = capsys.readouterr().out
    assert "误挂方向这轮没量" in out


def test_zero_hits_are_reported_with_their_confidence_bound(tmp_path, capsys):
    """一篇没漏时必须把上界打出来:0/5 看着完美,其实上界高达 45%。"""
    v = _lib_with_raw(tmp_path)
    state = tmp_path / "st"
    main(["--vault", str(v), "--judge-model", "model-c", "--n", "10",
          "--strata", "zero-theme", "--state", str(state)],
         _client=_FakeClient(['{"themes":[],"scores":{"D1":0}}'] * 10))
    assert "别读成「零漏检」" in capsys.readouterr().out
