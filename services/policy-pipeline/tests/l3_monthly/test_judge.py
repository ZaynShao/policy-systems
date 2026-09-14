"""MA2:逐篇归属判定。

这一步是「业务需求不准」的修点:业务口径从战略画像渲染,不写死在提示词里。
两条硬规则由**代码**执行,不靠模型自觉:
- 落在画像 scope_absent 维度上的政策,模型若判 low 一律改判「需人工裁定」
  (画像 relevance_rules.absent_is_not_low 的原文要求);
- 输出必须是合法 JSON 且字段齐全,残缺就重试,不拿半个结果往下走。
"""
import json

import pytest

from scripts.l3_monthly import judge as J
from scripts.l3_monthly.models import Candidate


# 取自真实画像 business_strategy.yaml(profile_id: 2026-energy-strategy)的代表性条目
PROFILE = {
    "profile_id": "2026-energy-strategy",
    "effective_from": "2026-08-31",
    "businesses": [
        {"id": "fuel", "zh": "加油", "weight_2026": "守成", "headline": "一安全,两增长",
         "quantitative_targets": [],
         "decision_variables": ["批发价 / 炼厂装车价", "商户合规成本(安全、财税法)"],
         "scope_absent": [
             "油品品种(汽油/柴油):四段合计 0 次。**现行「汽油为主」口径的出处不在本材料**",
             "车型(乘用车/重卡/商用车/货车):四段合计 0 次",
         ]},
        {"id": "charging", "zh": "充电", "weight_2026": "战略重心",
         "headline": "直连增长 + 私家车(2C)运营升级",
         "quantitative_targets": [
             {"metric": "年对年增长", "value": ">40%", "confidence": "数字待核"}],
         "decision_variables": ["充电服务费定价空间", "场站侧电价结构"],
         "scope_absent": [
             "高速/服务区:0 次",
             "县域/农村场景:四段合计 0 次",
         ]},
        {"id": "power", "zh": "电力", "weight_2026": "建能力",
         "headline": "售电与电力交易,现货是主战场",
         "quantitative_targets": [],
         "decision_variables": ["目标省的现货规则与结算机制"],
         "scope_absent": [
             "V2G / 车网互动:0 次",
             "绿电 / 绿证 / 碳交易:0 次",
             "「充电站/充电桩」二词 0 次 —— 原文一律说「充电场景」「负荷」「商户」",
         ]},
    ],
    "relevance_rules": {
        "core_test": "是否改变 decision_variables 里的任何一个数",
        "high_form": "带具体省份/城市 + 可代入模型的数值的实施细则",
        "low_form": "全国性宏观框架、目标宣示、规划纲要",
        "early_signal": "征求意见稿不因未生效而降权",
        "absent_is_not_low": "遇到落在空白维度上的政策,应标为「需人工裁定」,不得自动判低相关",
    },
    "signals": [
        {"id": "F02", "business": "fuel", "weight": "high", "what": "成品油消费税稽查"},
        {"id": "P12", "business": "power", "weight": "medium", "what": "省间电力交易"},
        {"id": "P14", "business": "power", "weight": "suppress", "what": "新型电力系统宏观框架"},
    ],
    "open_questions": [
        {"id": "Q1", "topic": "油品品种与车型(汽油/柴油/重卡/商用车)"},
        {"id": "Q3", "topic": "高速/服务区充电"},
        {"id": "Q5", "topic": "V2G / 车网互动"},
    ],
}


# ── 空白维度词表 ────────────────────────────────────────────────
def test_absent_terms_extracts_slash_separated_dimensions():
    t = J.absent_terms(PROFILE)
    for w in ("汽油", "柴油", "重卡", "商用车", "高速", "服务区", "县域", "农村场景",
              "V2G", "车网互动", "绿电", "绿证", "碳交易"):
        assert w in t, f"{w} 应在空白维度词表里"


def test_absent_terms_excludes_vocabulary_note_not_a_blank_dimension():
    """电力线那条「『充电站/充电桩』二词 0 次」讲的是**用词习惯**,不是业务空白。

    若把充电桩当空白维度,几乎每篇充电政策都会被强制改判「需人工裁定」,
    整期详情就空了——这是会毁掉一期月刊的错误。
    """
    t = J.absent_terms(PROFILE)
    assert "充电桩" not in t and "充电站" not in t


def test_absent_terms_drops_overlong_prose():
    assert all(2 <= len(w) <= 8 for w in J.absent_terms(PROFILE))


# ── 月刊版口径渲染 ──────────────────────────────────────────────
def test_render_for_monthly_includes_high_and_suppress_signals_only():
    from scripts.common.strategy_profile import render_for_monthly
    txt = render_for_monthly(PROFILE)
    assert "F02" in txt and "P14" in txt
    assert "P12" not in txt, "medium 信号既不提召回也不压误判,进来只稀释注意力"


def test_render_for_monthly_omits_unverified_numbers():
    from scripts.common.strategy_profile import render_for_monthly
    txt = render_for_monthly(PROFILE)
    assert ">40%" not in txt, "画像里的定量目标全标了数字待核,不得进提示词"


def test_render_for_monthly_carries_decision_variables_and_rules():
    from scripts.common.strategy_profile import render_for_monthly
    txt = render_for_monthly(PROFILE)
    assert "批发价" in txt and "现货规则" in txt
    assert "征求意见稿" in txt, "early_signal 判据必须带上"
    assert "需人工裁定" in txt


# ── 输出解析 ────────────────────────────────────────────────────
def _ok_json(**over):
    d = {"level": "国家", "issue_date_from_body": "2026-07-23",
         "issuer_from_body": "国家发展改革委", "official_number_from_body": "发改能源〔2026〕1067号",
         "business_hits": ["fuel"], "decision_variables_touched": ["批发价"],
         "relevance": "high", "why": "改批发价", "dq": ""}
    d.update(over)
    return json.dumps(d, ensure_ascii=False)


def test_parse_judgment_accepts_plain_json():
    j = J.parse_judgment(_ok_json())
    assert j["level"] == "国家" and j["relevance"] == "high"


def test_parse_judgment_accepts_fenced_json():
    j = J.parse_judgment("```json\n" + _ok_json() + "\n```")
    assert j["business_hits"] == ["fuel"]


def test_parse_judgment_rejects_missing_field():
    bad = json.loads(_ok_json())
    del bad["relevance"]
    with pytest.raises(J.JudgmentError):
        J.parse_judgment(json.dumps(bad))


def test_parse_judgment_rejects_unknown_relevance():
    with pytest.raises(J.JudgmentError):
        J.parse_judgment(_ok_json(relevance="很相关"))


def test_parse_judgment_rejects_unknown_business_id():
    with pytest.raises(J.JudgmentError):
        J.parse_judgment(_ok_json(business_hits=["storage"]))


def test_parse_judgment_rejects_non_json():
    with pytest.raises(J.JudgmentError):
        J.parse_judgment("这篇政策与加油业务相关。")


# ── 硬规则:空白维度不得自动判低 ────────────────────────────────
def test_low_on_absent_dimension_is_forced_to_manual():
    j = json.loads(_ok_json(relevance="low"))
    out = J.enforce_rules(j, "关于加强柴油车排放监管的通知", J.absent_terms(PROFILE))
    assert out["relevance"] == "需人工裁定"
    assert "柴油" in out["dq"], "改判理由要写进 dq,否则下游看不出为什么"


def test_high_on_absent_dimension_is_left_alone():
    """规则原文是「不得自动判**低**相关」,不是「一律改判」。"""
    j = json.loads(_ok_json(relevance="high"))
    out = J.enforce_rules(j, "关于柴油价格的通知", J.absent_terms(PROFILE))
    assert out["relevance"] == "high"


def test_low_without_absent_dimension_stays_low():
    j = json.loads(_ok_json(relevance="low"))
    out = J.enforce_rules(j, "关于开展电力市场宣传月活动的通知", J.absent_terms(PROFILE))
    assert out["relevance"] == "low"


# ── 单篇判定 ────────────────────────────────────────────────────
def _cand():
    return Candidate(policy_id="P_A", title="关于加强柴油车排放监管的通知",
                     official_number="", date="2026-07-10", date_missing=False,
                     raw_path="/a.md", body_len=500, region_name="")


class _FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def complete(self, system, user, max_tokens=1024):
        self.calls.append((system, user))
        return self.replies.pop(0)


def test_judge_one_applies_rules_and_records_pid():
    c = _FakeClient([_ok_json(relevance="low")])
    out = J.judge_one(c, "口径段", J.absent_terms(PROFILE), _cand(), "RAW 头部")
    assert out["policy_id"] == "P_A"
    assert out["relevance"] == "需人工裁定"


def test_judge_one_retries_once_on_bad_output():
    c = _FakeClient(["不是 JSON", _ok_json()])
    out = J.judge_one(c, "口径段", set(), _cand(), "RAW 头部")
    assert out["relevance"] == "high"
    assert len(c.calls) == 2


def test_judge_one_gives_up_after_retries_without_faking_a_result():
    """连续坏输出不得兜底成一个假判定——宁可标 error 让下游看见。"""
    c = _FakeClient(["坏", "还是坏"])
    out = J.judge_one(c, "口径段", set(), _cand(), "RAW 头部", retries=1)
    assert out["relevance"] == "error"
    assert out["dq"]


def test_judge_prompt_puts_profile_in_system_so_the_prefix_is_cacheable():
    """口径段约 1300 token,一期要判两百多篇。

    放 system 里前缀才逐字相同、吃得上服务端前缀缓存;放 user 段就是把同一段
    口径重复付费两百遍。
    """
    c = _FakeClient([_ok_json()])
    J.judge_one(c, "【公司业务口径】…", set(), _cand(), "落款:2026年7月20日")
    system, user = c.calls[0]
    assert "【公司业务口径】" in system
    assert "【公司业务口径】" not in user
    assert "落款:2026年7月20日" in user
    assert "2026-07-10" not in user, "frontmatter 日期不可信,不该喂给模型当依据"


def test_judge_system_prefix_is_identical_across_candidates():
    c = _FakeClient([_ok_json(), _ok_json()])
    a = _cand()
    b = Candidate(policy_id="P_B", title="另一篇", official_number="", date="2026-08-01",
                  date_missing=False, raw_path="/b.md", body_len=1, region_name="")
    J.judge_one(c, "口径段", set(), a, "正文A")
    J.judge_one(c, "口径段", set(), b, "正文B")
    assert c.calls[0][0] == c.calls[1][0], "system 段必须逐字相同,否则缓存不命中"


def test_parse_judgment_requires_signoff_facts():
    """落款三事实是速览表的主来源(正则在真实 RAW 上只有 35–47% 命中且有假阳性),
    缺一个都不能放行。"""
    import json as _j
    for k in ("issuer_from_body", "official_number_from_body"):
        bad = _j.loads(_ok_json())
        del bad[k]
        with pytest.raises(J.JudgmentError):
            J.parse_judgment(_j.dumps(bad))
