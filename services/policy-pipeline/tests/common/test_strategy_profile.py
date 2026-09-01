"""业务战略画像(pipeline 侧读取端)。

这个文件守的是一处**刻意的不对称**:同一份画像文件,policy-qa 读不出来时软着陆,
pipeline 读不出来时必须炸。

理由是两边的失败代价不同。在线问答画像坏了,还能答政策本身,降级只损失一层
业务框定;而 L2 是批量派生,一跑上千篇、结果直接落进 vault——静默用一套跟你
以为的不一样的口径把全库写一遍,事后连"哪些是按哪版口径写的"都查不出来。
全库 1546 篇是两个模型分两批打的、分不可比,幸亏 extracted_model 记了才发现得了;
这次把 extracted_strategy 也记上,就是同一个教训。
"""
import textwrap

import pytest
import yaml

from scripts.common.strategy_profile import (
    StrategyProfileError,
    check_impact_keys,
    load_strategy_profile,
    parse_strategy_profile,
    render_for_impact_analysis,
)
from scripts.l2_themescore import program_gate, prompts
from scripts.l2_themescore.business_view_writer import write_business_view
from scripts.l2_themescore.models import BusinessViewDraft, Scores

VALID = textwrap.dedent(
    """
    schema_version: 1
    profile_id: 2026-test
    status: active
    effective_from: 2026-08-31
    businesses:
      - id: fuel
        zh: 加油
        weight_2026: 守成
        headline: 一安全两增长
        quantitative_targets: [{metric: 年增, value: "40%", confidence: 数字待核}]
        decision_variables: [批发价与炼厂装车价, 商户合规成本]
      - {id: charging, zh: 充电, decision_variables: [建桩节奏与选址]}
      - {id: power, zh: 电力, decision_variables: [目标省现货规则]}
    relevance_rules:
      core_test: 是否改变 decision_variables 里的任何一个数
      absent_is_not_low: 材料空白不得自动判低相关
    open_questions:
      - {id: Q1, topic: 油品品种与车型, status: 材料空白}
    consistency:
      impact_keys: {fuel: 加油, charging: 充电, power: 电力_储能_V2G_交易}
    """
)


def _p(**over):
    data = yaml.safe_load(VALID)
    data.update(over)
    return parse_strategy_profile(data)


@pytest.mark.parametrize("version", [0, 2, None, "1"])
def test_rejects_unknown_schema_version(version):
    with pytest.raises(StrategyProfileError, match="schema_version"):
        _p(schema_version=version)


@pytest.mark.parametrize("status", ["superseded", "draft", None])
def test_rejects_non_active_profile(status):
    """换战略时旧画像标 superseded 留库里。指错文件必须炸,不能静默用旧战略跑全库。"""
    with pytest.raises(StrategyProfileError, match="active"):
        _p(status=status)


def test_rejects_empty_businesses():
    with pytest.raises(StrategyProfileError, match="businesses"):
        _p(businesses=[])


def test_no_path_means_no_profile():
    """没配这个可选项是正常情况,不是错误。"""
    assert load_strategy_profile(None) is None
    assert load_strategy_profile("") is None


def test_configured_but_unreadable_raises_instead_of_degrading(tmp_path):
    """**这条是本文件的主张所在。**

    配了却读不出来,批处理必须停。软着陆的话,这一轮会用旧口径把上千篇重写一遍,
    而且不会有任何人发现——因为输出看起来完全正常。
    """
    with pytest.raises(StrategyProfileError):
        load_strategy_profile(str(tmp_path / "缺席.yaml"))


def test_broken_yaml_raises(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("businesses: [unclosed\n", encoding="utf-8")
    with pytest.raises(StrategyProfileError, match="YAML"):
        load_strategy_profile(str(bad))


def test_loads_from_disk(tmp_path):
    good = tmp_path / "ok.yaml"
    good.write_text(VALID, encoding="utf-8")
    assert load_strategy_profile(str(good))["profile_id"] == "2026-test"


# ── 与 L2 契约对账 ──────────────────────────────────────────────────
def test_impact_keys_must_match_what_l2_actually_writes():
    check_impact_keys(_p(), program_gate.IMPACT_KEYS)   # 不抛即通过


def test_impact_key_mismatch_stops_the_batch():
    """画像多一条业务线而 L2 不会写那个键 → 下游按画像去取就是恒空。

    空结果会被模型读成「库里没有」。「乡村」当初就是这么活了三个月的,
    所以这里宁可让批处理起不来。
    """
    data = yaml.safe_load(VALID)
    data["consistency"]["impact_keys"]["rural"] = "乡村"
    with pytest.raises(StrategyProfileError, match="不一致"):
        check_impact_keys(parse_strategy_profile(data), program_gate.IMPACT_KEYS)


def test_missing_consistency_block_is_an_error():
    data = yaml.safe_load(VALID)
    del data["consistency"]
    with pytest.raises(StrategyProfileError, match="impact_keys"):
        check_impact_keys(parse_strategy_profile(data), program_gate.IMPACT_KEYS)


# ── 渲染与注入 ──────────────────────────────────────────────────────
def test_render_carries_decision_variables_and_gaps():
    text = render_for_impact_analysis(_p())
    assert "批发价与炼厂装车价" in text
    assert "是否改变 decision_variables" in text
    assert "油品品种与车型" in text          # 空白维度要说出来
    assert "不要" in text and "未直接涉及" in text  # 且要说明空白不等于无影响


def test_render_omits_unverified_numbers():
    """画像里的数字全标了待核(ASR 转写易错),写影响分析根本用不到。"""
    text = render_for_impact_analysis(_p())
    assert "40%" not in text and "数字待核" not in text


def test_pass2_without_profile_is_unchanged():
    """没配画像时提示词必须逐字不变——新功能不该顺手改掉既有的派生口径。"""
    assert "【公司业务口径】" not in prompts.pass2_system()


def test_pass2_injects_the_profile_and_keeps_the_json_template():
    """注入段是插进去的,不能把末尾的 JSON 输出模板挤掉或吃掉花括号。"""
    text = prompts.pass2_system(render_for_impact_analysis(_p()))
    assert "批发价与炼厂装车价" in text
    assert '{"影响分析":{"加油":"...","充电":"...","电力_储能_V2G_交易":"..."}' in text
    assert "【证据边界】" in text


# ── 出处落盘 ────────────────────────────────────────────────────────
def _draft():
    return BusinessViewDraft(
        pid="P_2026_T_1", themes=["charging_infra"], primary_theme="charging_infra",
        comprehensive=False, scores=Scores.from_dict({f"D{i}": 3 for i in range(1, 7)}),
    )


def test_writer_records_which_profile_was_used(tmp_path):
    path = write_business_view(
        _draft(), str(tmp_path), sanitized_from="0_raw/policies/x.md",
        extracted_at="2026-08-31", extracted_model="deepseek-v4-flash",
        extracted_strategy="2026-test",
    )
    assert yaml.safe_load(open(path, encoding="utf-8"))["extracted_strategy"] == "2026-test"


def test_writer_omits_the_field_when_no_profile(tmp_path):
    """没用画像就不写这个键,而不是写个空值——空值会让人以为用了一版没名字的画像。"""
    path = write_business_view(
        _draft(), str(tmp_path), sanitized_from="0_raw/policies/x.md",
        extracted_at="2026-08-31", extracted_model="deepseek-v4-flash",
    )
    assert "extracted_strategy" not in yaml.safe_load(open(path, encoding="utf-8"))


# ── 「还没配」与「配错了」必须区别对待 ──────────────────────────────
#
# run_2b 的 --strategy 默认指向 vault 里的固定路径。画像还没推上来的库里那个文件
# 就是不存在的——这时必须照旧跑完,不能让每晚的 L2 全线失败。但显式指了个路径却
# 找不到,那是拼错了:你以为按新口径跑了,实际没有,而输出看起来完全正常。
def test_unset_strategy_means_no_profile():
    from scripts.l2_themescore.run_2b import resolve_strategy_path

    assert resolve_strategy_path("/vault", None) is None
    assert resolve_strategy_path("/vault", "  ") is None


def test_missing_file_at_the_default_path_degrades_with_a_notice(tmp_path, capsys):
    from scripts.l2_themescore.run_2b import DEFAULT_STRATEGY, resolve_strategy_path

    assert resolve_strategy_path(str(tmp_path), DEFAULT_STRATEGY) is None
    assert "未找到业务战略画像" in capsys.readouterr().out


def test_missing_file_at_an_explicit_path_stops_the_run(tmp_path):
    from scripts.l2_themescore.run_2b import resolve_strategy_path

    with pytest.raises(SystemExit, match="不存在"):
        resolve_strategy_path(str(tmp_path), "_meta/framework/typo.yaml")


def test_existing_file_resolves_to_its_path(tmp_path):
    from scripts.l2_themescore.run_2b import DEFAULT_STRATEGY, resolve_strategy_path

    target = tmp_path / DEFAULT_STRATEGY
    target.parent.mkdir(parents=True)
    target.write_text(VALID, encoding="utf-8")
    resolved = resolve_strategy_path(str(tmp_path), DEFAULT_STRATEGY)
    assert resolved == str(target)
    assert load_strategy_profile(resolved)["profile_id"] == "2026-test"
