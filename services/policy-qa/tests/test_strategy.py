"""业务战略画像:加载、校验、渲染,以及它怎么换掉手写的业务口径。

这个文件守的是三件事:
1. **失败要软着陆**——画像是可选增强,任何加载失败都只能退回"不做业务框定",
   不能把问答服务拦在门外。
2. **不许静默用错版本**——status 不是 active 就拒绝加载。换战略时旧画像会被标
   superseded 留在库里,指错文件却照常起服务,比报错危险得多。
3. **配了画像就整段替换手写口径**——不是追加。两份业务定义同时在场,模型按哪份
   答就成了掷骰子,而手写那份的出处本身就存疑(见 prompts.DEFAULT_BUSINESS_CONTEXT
   的注释:「汽油为主」在战略材料里 0 次命中)。
"""
from __future__ import annotations

import textwrap

import pytest
import yaml

from app.agent import _business_context
from app.prompts import (
    DEFAULT_BUSINESS_CONTEXT,
    NO_BUSINESS_CONTEXT,
    build_system_prompt,
)
from app.strategy import StrategyError, load_profile, parse_profile

VALID = textwrap.dedent(
    """
    schema_version: 1
    profile_id: 2026-test
    status: active
    effective_from: 2026-08-31
    source: {title: 测试用战略课程}
    businesses:
      - id: charging
        zh: 充电
        weight_2026: 战略重心
        headline: 直连增长
        quantitative_targets:
          - {metric: 年增, value: ">40%", confidence: 数字待核}
        decision_variables: [建桩节奏与选址, 充电服务费定价空间]
    relevance_rules:
      core_test: 是否改变 decision_variables 里的任何一个数
      high_form: 带具体省份且带可代入模型的数值的实施细则
      low_form: 全国性宏观框架与规划纲要
      absent_is_not_low: 材料空白不得自动判低相关
    signals:
      - {id: C01, business: charging, weight: high, evidence: inferred,
         what: 省级充电设施建设行动方案, changes: 决定选址与建设节奏}
      - {id: C13, business: charging, weight: suppress, evidence: stated,
         what: 电动自行车充电器安全技术要求, changes: 两轮车不在任何一条打法里}
      - {id: C09, business: charging, weight: medium, evidence: inferred,
         what: 新能源乘用车消费政策, changes: 影响私家车份额假设}
    open_questions:
      - {id: Q3, topic: 高速服务区充电, status: 材料空白, note: 建议人工复核}
    """
)


def _profile(**overrides):
    data = yaml.safe_load(VALID)
    data.update(overrides)
    return parse_profile(data)


# ── 校验 ────────────────────────────────────────────────────────────
def test_parses_a_valid_profile():
    p = _profile()
    assert p.profile_id == "2026-test"
    assert p.business_ids == ("charging",)
    assert len(p.signals) == 3


@pytest.mark.parametrize("version", [0, 2, None, "1"])
def test_rejects_unknown_schema_version(version):
    """不认识的版本宁可不加载,也不要按旧结构猜新文件的字段。"""
    with pytest.raises(StrategyError, match="schema_version"):
        _profile(schema_version=version)


@pytest.mark.parametrize("status", ["superseded", "draft", None])
def test_rejects_non_active_profile(status):
    """换战略时旧画像标 superseded 留库里;指错文件必须报错,不能静默用旧战略。"""
    with pytest.raises(StrategyError, match="active"):
        _profile(status=status)


def test_rejects_empty_businesses():
    with pytest.raises(StrategyError, match="businesses"):
        _profile(businesses=[])


def test_rejects_profile_without_core_test():
    """core_test 是整份画像的判据核心,缺了这份画像就只剩一堆清单。"""
    with pytest.raises(StrategyError, match="core_test"):
        _profile(relevance_rules={"high_form": "x"})


def test_rejects_suppress_signal_without_reason():
    """压制信号必须写明理由——不写理由的压制,和拍脑袋降权没有区别。"""
    data = yaml.safe_load(VALID)
    data["signals"] = [{"id": "X", "weight": "suppress", "what": "某类政策"}]
    with pytest.raises(StrategyError, match="changes"):
        parse_profile(data)


# ── 软着陆 ──────────────────────────────────────────────────────────
def test_no_path_configured_is_not_an_error():
    """没配这个可选项是正常情况,不该有 warning。"""
    assert load_profile(None) is None
    assert load_profile("  ") is None


def test_missing_file_degrades_instead_of_raising(tmp_path, caplog):
    assert load_profile(str(tmp_path / "nope.yaml")) is None
    assert "不做业务框定" in caplog.text


def test_broken_yaml_degrades_instead_of_raising(tmp_path, caplog):
    bad = tmp_path / "bad.yaml"
    bad.write_text("businesses: [unclosed\n", encoding="utf-8")
    assert load_profile(str(bad)) is None
    assert "不做业务框定" in caplog.text


def test_schema_violation_degrades_instead_of_raising(tmp_path, caplog):
    """文件在、YAML 也合法,但 schema 不对——同样只能降级,不能崩。"""
    bad = tmp_path / "wrong.yaml"
    bad.write_text(yaml.dump({"schema_version": 99}), encoding="utf-8")
    assert load_profile(str(bad)) is None


def test_loads_from_disk(tmp_path):
    good = tmp_path / "ok.yaml"
    good.write_text(VALID, encoding="utf-8")
    p = load_profile(str(good))
    assert p is not None and p.profile_id == "2026-test"


# ── 渲染 ────────────────────────────────────────────────────────────
def test_render_carries_the_operative_parts():
    text = _profile().render()
    assert "充电" in text
    assert "建桩节奏与选址" in text                    # 决策变量
    assert "是否改变 decision_variables" in text        # 判据核心
    assert "电动自行车充电器安全技术要求" in text        # suppress:压误判
    assert "两轮车不在任何一条打法里" in text            # 压制得给理由
    assert "省级充电设施建设行动方案" in text            # high:提召回
    assert "高速服务区充电" in text                      # 空白维度要说出来


def test_render_omits_unverified_numbers():
    """画像里的数字全标了「数字待核」(ASR 转写易错),而判相关性根本用不到它们。

    把不可信的数字送进上下文,就是在等模型某天把它当事实引用出来。
    """
    text = _profile().render()
    assert ">40%" not in text
    assert "数字待核" not in text


def test_render_omits_medium_signals():
    """medium 供人工复核。塞进提示词只会稀释 high/suppress 两档的注意力。"""
    assert "新能源乘用车消费政策" not in _profile().render()


# ── 与提示词的接线 ──────────────────────────────────────────────────
def test_profile_replaces_the_handwritten_scope_entirely():
    """**整段替换,不是追加。**

    两份业务定义同时在场,模型按哪份答就成了掷骰子;而手写那份里的
    「汽油为主」在 2026 战略材料四段中命中 0 次,出处存疑。
    """
    prompt = build_system_prompt(business_context=_profile().render())
    assert "充电" in prompt and "建桩节奏与选址" in prompt
    assert "汽油为主" not in prompt
    assert "重卡占比小" not in prompt


def test_without_profile_the_handwritten_scope_still_applies():
    """没配画像时行为不变——新功能不该顺手改掉既有的答题口径。"""
    prompt = build_system_prompt()
    assert DEFAULT_BUSINESS_CONTEXT in prompt


def test_toggle_off_states_the_restriction_instead_of_going_silent():
    """关掉不是把业务边界那段删了了事。

    整段抽掉,模型会退回自己脑子里的行业常识去猜公司在做什么——比给一份口径更糟。
    所以关掉时给的是一段**明确的限制**。
    """
    prompt = build_system_prompt(business_context=NO_BUSINESS_CONTEXT)
    assert "不做公司业务关联分析" in prompt
    assert "汽油为主" not in prompt


@pytest.mark.parametrize(
    "strategy, enabled, expect",
    [
        (None, True, None),                    # 没画像 + 开 → 兜底手写口径
        (None, False, NO_BUSINESS_CONTEXT),    # 没画像 + 关 → 仍要明确限制
        ("profile", False, NO_BUSINESS_CONTEXT),  # 有画像 + 关 → 关就是关
    ],
)
def test_business_context_selection(strategy, enabled, expect):
    obj = _profile() if strategy == "profile" else None
    assert _business_context(obj, enabled) == expect


def test_business_context_uses_profile_when_enabled():
    p = _profile()
    assert _business_context(p, True) == p.render()
