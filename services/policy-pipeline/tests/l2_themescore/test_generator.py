import json
from scripts.common.llm import LLMClient
from scripts.l2_themescore.generator import parse_json_block, gen_pass1, gen_pass2
from scripts.l2_themescore.prompts import pass1_system, pass2_system

def _fake(payload):
    class M:
        def create(self, **kw):
            class R: content = [type("B",(),{"text": payload})()]
            return R()
    class A:
        def __init__(self,**kw): self.messages = M()
    return A()

def _seq_fake(payloads):
    state = {"i": 0}
    class M:
        def create(self, **kw):
            payload = payloads[min(state["i"], len(payloads)-1)]
            state["i"] += 1
            class R: content = [type("B",(),{"text": payload})()]
            return R()
    class A:
        def __init__(self,**kw): self.messages = M()
    return A()

def test_parse_json_block_strips_fence():
    assert parse_json_block('```json\n{"a":1}\n```') == {"a":1}
    assert parse_json_block('{"b":2}') == {"b":2}

def test_gen_pass1(tmp_path):
    payload = '{"themes":["power_market"],"primary_theme":"power_market","scores":{"D1":5,"D2":4,"D3":4,"D4":4,"D5":4,"D6":5}}'
    c = LLMClient(client=_fake(payload), log_path=str(tmp_path/"l.jsonl"))
    out = gen_pass1(c, system="sys", user="u")
    assert out["primary_theme"] == "power_market"
    assert out["scores"]["D1"] == 5

def test_gen_pass2(tmp_path):
    payload = '{"影响分析":{"加油":"a","充电":"b","电力_储能_V2G_交易":"c"},"行动建议":["A 趁早:x"],"didi_impact_one_liner":"y"}'
    c = LLMClient(client=_fake(payload), log_path=str(tmp_path/"l.jsonl"))
    out = gen_pass2(c, system="sys", user="u")
    assert set(out["影响分析"].keys()) == {"加油","充电","电力_储能_V2G_交易"}

def test_gen_repairs_json_after_strict_retry_fails(tmp_path):
    good = '{"scores":{"D1":1}}'
    c = LLMClient(client=_seq_fake(['{"a":', '{"a":', good]), log_path=str(tmp_path/"l.jsonl"))
    out = gen_pass1(c, system="sys", user="u")
    assert out == {"scores": {"D1": 1}}


def test_gen_pass1_retries_when_json_valid_but_scores_missing(tmp_path):
    """合法 JSON 但缺 scores,以前直接 KeyError 冒到 plan() 外,一次重试都没有。

    2026-09-07 查 51 篇静默丢件:三条可查的退件理由里有两条就是 'scores'。
    缺字段与非 JSON 是同一件事——这次没生成出来,必须在重试圈内。
    """
    good = '{"themes":[],"scores":{"D1":3,"D2":3,"D3":3,"D4":3,"D5":3,"D6":3}}'
    c = LLMClient(client=_seq_fake(['{"themes":["power_market"]}', good]),
                  log_path=str(tmp_path/"l.jsonl"))
    out = gen_pass1(c, system="sys", user="u")
    assert out["scores"]["D1"] == 3


def test_gen_pass1_treats_json_null_as_malformed(tmp_path):
    """json.loads("null") 会**成功**并返回 None,顶层类型必须显式判,否则空输出被当成结果。"""
    good = '{"scores":{"D1":2}}'
    c = LLMClient(client=_seq_fake(['null', good]), log_path=str(tmp_path/"l.jsonl"))
    assert gen_pass1(c, system="sys", user="u") == {"scores": {"D1": 2}}


def test_gen_pass1_raises_after_three_bad_shapes(tmp_path):
    """三次机会用尽仍不成形 → 抛出,让 orchestrate 记失败进死信,而不是静默出局。"""
    import pytest
    from scripts.l2_themescore.generator import MalformedOutput
    c = LLMClient(client=_seq_fake(['{"themes":[]}']), log_path=str(tmp_path/"l.jsonl"))
    with pytest.raises(MalformedOutput):
        gen_pass1(c, system="sys", user="u")


def test_gen_pass2_retries_when_impact_missing(tmp_path):
    good = '{"影响分析":{"加油":"a"},"行动建议":[]}'
    c = LLMClient(client=_seq_fake(['{"行动建议":[]}', good]), log_path=str(tmp_path/"l.jsonl"))
    assert gen_pass2(c, system="sys", user="u")["影响分析"] == {"加油": "a"}

def test_pass1_prompt_blocks_standard_weak_mention_overhang():
    class R:
        ids = ["equipment_renewal_theme", "energy_storage_theme", "vpp_theme", "charging_infra"]
        zh = {x: x for x in ids}
        aliases = {x: [] for x in ids}
    prompt = pass1_system(R(), scoring_text="scores")
    assert "标准制定" in prompt
    assert "不等于 theme 命中" in prompt
    assert "不得因清单式提到" in prompt
    assert "政府公报目录" in prompt
    assert "应归零主题" in prompt

def test_pass1_prompt_prioritizes_explicit_charging_buildout_over_grid_context():
    class R:
        ids = ["distribution_grid_opening", "charging_infra", "residential_charging"]
        zh = {x: x for x in ids}
        aliases = {x: [] for x in ids}
    prompt = pass1_system(R(), scoring_text="scores")
    assert "充电设施全覆盖" in prompt
    assert "停车位电气化改造" in prompt
    assert "primary_theme 应优先选 charging_infra" in prompt
    assert "residential_charging" in prompt

def test_pass1_prompt_blocks_macro_nev_over_expansion():
    class R:
        ids = ["charging_infra", "v2g", "vpp_theme", "green_power_trading_theme",
               "energy_storage_theme", "equipment_renewal_theme"]
        zh = {x: x for x in ids}
        aliases = {x: [] for x in ids}
    prompt = pass1_system(R(), scoring_text="scores")
    assert "新能源汽车宏观规划" in prompt
    assert "储能单元" in prompt
    assert "不得自动挂 energy_storage_theme" in prompt
    assert "不得自动挂 equipment_renewal_theme" in prompt

def test_pass2_prompt_blocks_impact_hallucination():
    prompt = pass2_system()
    assert "不得编造" in prompt
    assert "正文明确" in prompt
    assert "未直接涉及" in prompt
    assert "V2G" in prompt and "虚拟电厂" in prompt
    assert "量化指标" in prompt
    assert "标准制定" in prompt
    assert "不等于直接业务影响" in prompt

def _capture():
    seen = []
    P = ('{"themes":["power_market"],"primary_theme":"power_market",'
         '"scores":{"D1":5,"D2":4,"D3":4,"D4":4,"D5":4,"D6":5},"影响分析":{}}')
    class M:
        def create(self, **kw):
            seen.append(kw.get("max_tokens"))
            class R: content = [type("B",(),{"text": P})()]
            return R()
    class A:
        def __init__(self,**kw): self.messages = M()
    return A(), seen

def test_gen_passes_have_reasoning_headroom(tmp_path):
    # reasoning 模型须留足"思考+输出"预算;原 896/1024 偏紧→截断成空。守这条不回退。
    client_obj, seen = _capture()
    c = LLMClient(client=client_obj, log_path=str(tmp_path/"l.jsonl"))
    gen_pass1(c, system="s", user="u")
    gen_pass2(c, system="s", user="u")
    assert seen[0] >= 2048   # pass1
    assert seen[1] >= 2048   # pass2
