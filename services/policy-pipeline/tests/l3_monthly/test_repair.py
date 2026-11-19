"""MA7 返修:≤2 轮,仍不过**照常发布**并挂容错提示。

这一步的口径是用户定的:审计门不过不是不发布,而是把过不了的地方明说出来
(「因 AI 出稿某部分可能不够符合要求,敬请谅解」),再给人工修改意见栏回炉。
所以 run_repair **永远不抛异常**——它交出稿子和一张残留清单。

返修只重写被点名的那一段。整篇重写会把已经过关的部分重新掷一次骰子。
"""
import copy

import pytest

from scripts.l3_monthly import repair


PROFILE = {
    "schema_version": 1, "status": "active", "profile_id": "t", "effective_from": "2026-08-31",
    "businesses": [{"id": "fuel", "zh": "加油"}, {"id": "charging", "zh": "充电"},
                   {"id": "power", "zh": "电力"}],
    "not_business_lines": [{"zh": "换电(已退役)"}],
    "relevance_rules": {}, "signals": [], "open_questions": [],
}


# F 门一并入,占位 bundle 就等于"没有事实源":稿里的「第三条」立刻成了无源断言。
# 夹具改成能回指的真材料,才测得出 D 门与业务口径门这条线。
BUNDLE_A = {"P_A": "## RAW 原文\n第三条 各省应于年底前完成备案。"}


def _content(**over):
    base = {
        "schema": "monthly.v2", "month": "2026-07",
        "overview": "本月政策密度抬升。",
        "businessTakes": [{"business": "充电", "text": "备案口径要摸清。"}],
        "details": [{
            "no": "01", "policyId": "P_A", "title": "甲文件",
            "info": "发文机关:国家发展改革委。", "reading": "改了备案口径。",
            "focus": "第三条要求年底前完成。",
            "advice": [{"business": "充电", "tag": "C 跟踪", "text": "跟进备案。"}],
        }],
        "localRoundup": "江苏等省本月集中调整。", "appendix": "国务院专题学习。",
    }
    base.update(over)
    return base


class FakeClient:
    def __init__(self, outputs):
        self.outputs = dict(outputs)   # location -> 新文本(或 list 依次取)
        self.seen = []

    def complete(self, system, user, max_tokens=None):
        loc = next((l for l in self.outputs if f"【位置】{l}\n" in user), None)
        self.seen.append(loc)
        val = self.outputs.get(loc, "")
        return val.pop(0) if isinstance(val, list) else val


# ── ① 可定位的最小段 ───────────────────────────────────────────
def test_block_texts_covers_every_addressable_unit():
    keys = set(repair.block_texts(_content()))
    assert keys == {"overview", "businessTakes[0].text", "localRoundup", "appendix",
                    "details[01].info", "details[01].reading", "details[01].focus",
                    "details[01].advice[0].text"}


def test_audit_blocks_attaches_location():
    c = _content()
    c["details"][0]["reading"] = "改了**备案**口径。"
    v = repair.audit_blocks(c, PROFILE, BUNDLE_A)
    assert [x["location"] for x in v] == ["details[01].reading"]
    assert v[0]["gate"] == "D" and v[0]["rule"] == "D-EMPH"


def test_clean_content_needs_no_rounds_and_no_llm():
    c = FakeClient({})
    out, caveats, rounds = repair.run_repair(c, _content(), BUNDLE_A, PROFILE)
    assert caveats == [] and rounds == 0 and c.seen == []


# ── ② 只重写被点名的那一段 ─────────────────────────────────────
def test_repairs_only_the_named_block():
    c = _content()
    c["details"][0]["reading"] = "改了**备案**口径。"
    before = copy.deepcopy(c)
    client = FakeClient({"details[01].reading": "改了备案口径。"})
    out, caveats, rounds = repair.run_repair(client, c, BUNDLE_A, PROFILE)
    assert out["details"][0]["reading"] == "改了备案口径。"
    assert caveats == [] and rounds == 1
    for k in ("info", "focus"):
        assert out["details"][0][k] == before["details"][0][k]
    assert out["overview"] == before["overview"]
    assert client.seen == ["details[01].reading"]


def test_advice_text_is_written_back_into_the_right_entry():
    c = _content()
    c["details"][0]["advice"][0]["text"] = "跟进「备案」。"
    client = FakeClient({"details[01].advice[0].text": "跟进备案。"})
    out, caveats, _ = repair.run_repair(client, c, BUNDLE_A, PROFILE)
    assert out["details"][0]["advice"][0] == {
        "business": "充电", "tag": "C 跟踪", "text": "跟进备案。"}
    assert caveats == []


def test_bundle_is_given_to_the_writer_as_fact_source():
    c = _content()
    c["details"][0]["reading"] = "改了**备案**口径。"
    seen = {}

    class C:
        def complete(self, system, user, max_tokens=None):
            seen["user"] = user
            return "改了备案口径。"

    repair.run_repair(C(), c, {"P_A": "## RAW 原文\n第三条 某某某"}, PROFILE)
    assert "## RAW 原文" in seen["user"]


# ── ③ 返修不许把事情弄得更糟 ───────────────────────────────────
def test_repair_that_introduces_new_violations_is_rejected():
    """返修可能引入新违规。更糟就退回原文,免得白白烧掉一轮。"""
    c = _content()
    c["details"][0]["reading"] = "改了备案口径,详见「附件」。"      # 1 条 MAJOR
    client = FakeClient({"details[01].reading": "改了备案口径 P_2026_NEA_688。"})  # BLOCKER
    out, caveats, _ = repair.run_repair(client, c, BUNDLE_A, PROFILE)
    assert out["details"][0]["reading"] == "改了备案口径,详见「附件」。"
    assert [x["rule"] for x in caveats] == ["D-QUOTE"]


def test_empty_repair_output_keeps_the_original():
    c = _content()
    c["details"][0]["reading"] = "改了「备案」口径。"
    client = FakeClient({"details[01].reading": "   "})
    out, caveats, _ = repair.run_repair(client, c, BUNDLE_A, PROFILE)
    assert out["details"][0]["reading"] == "改了「备案」口径。"
    assert caveats


# ── ④ 两轮封顶,残留照常发布 ───────────────────────────────────
def test_stops_after_two_rounds_and_never_raises():
    """用户定的口径:仍不过**不是不发布**,而是给容错提示。

    两轮都没修好(每轮都是拿一条同样严重的违规换另一条),故两轮都退回原文。"""
    c = _content()
    c["details"][0]["reading"] = "改了「备案」口径。"
    client = FakeClient({"details[01].reading": ["还是「不行」。", "依旧「不行」。"]})
    out, caveats, rounds = repair.run_repair(client, c, BUNDLE_A, PROFILE)
    assert rounds == 2
    assert caveats and all(cv["location"] == "details[01].reading" for cv in caveats)
    assert out["details"][0]["reading"] == "改了「备案」口径。"


def test_second_round_finishes_what_the_first_started():
    """第一轮把 BLOCKER 降成 MAJOR,第二轮清干净——每轮都严格变好才采用。"""
    c = _content()
    c["details"][0]["reading"] = "改了备案口径 P_2026_NEA_688,详见「附件」。"
    client = FakeClient({"details[01].reading": [
        "改了备案口径,详见「附件」。", "改了备案口径,详见附件。"]})
    out, caveats, rounds = repair.run_repair(client, c, BUNDLE_A, PROFILE)
    assert rounds == 2 and caveats == []
    assert out["details"][0]["reading"] == "改了备案口径,详见附件。"


def test_client_failure_does_not_sink_the_issue():
    """一段修不成不该毁掉整期——它变成一条 caveat,稿子照发。"""
    c = _content()
    c["details"][0]["reading"] = "改了「备案」口径。"

    class Boom:
        def complete(self, system, user, max_tokens=None):
            raise RuntimeError("上游 503")

    out, caveats, rounds = repair.run_repair(Boom(), c, BUNDLE_A, PROFILE)
    assert rounds == 2 and len(caveats) == 1
    assert out["details"][0]["reading"] == "改了「备案」口径。"


def test_caveat_shape_matches_content_schema():
    """前端靠 caveats 渲染容错提示条,字段名得对得上 spec §7.1。"""
    c = _content()
    c["details"][0]["reading"] = "改了「备案」口径。"
    client = FakeClient({"details[01].reading": "还是「不行」。"})
    _, caveats, _ = repair.run_repair(client, c, BUNDLE_A, PROFILE)
    cv = caveats[0]
    assert set(cv) >= {"gate", "location", "note"}
    assert cv["gate"] == "D" and "角括号" in cv["note"]


def test_business_gate_violation_also_goes_through_repair():
    """业务口径门(换电已退役)与 D 门走同一条返修链。"""
    c = _content()
    c["details"][0]["reading"] = "换电业务(换电):本月有动作。"
    client = FakeClient({"details[01].reading": "充电业务:本月有动作。"})
    out, caveats, rounds = repair.run_repair(client, c, BUNDLE_A, PROFILE)
    assert rounds == 1 and caveats == []
    assert out["details"][0]["reading"] == "充电业务:本月有动作。"


# ── ⑤ F 门并进同一条链 ─────────────────────────────────────────
def test_fact_gate_participates_in_audit_and_repair():
    """稿里冒出一个 bundle 里没有的数字,和风格违规走同一条返修链。"""
    c = _content()
    c["details"][0]["reading"] = "改了备案口径,涉及 1685 万千瓦。"
    v = repair.audit_blocks(c, PROFILE, BUNDLE_A)
    assert [(x["gate"], x["location"]) for x in v] == [("F", "details[01].reading")]

    client = FakeClient({"details[01].reading": "改了备案口径。"})
    out, caveats, rounds = repair.run_repair(client, c, BUNDLE_A, PROFILE,
                                             adjudicate_facts=False)
    assert rounds == 1 and caveats == []
    assert out["details"][0]["reading"] == "改了备案口径。"


def test_detail_may_only_cite_its_own_bundle():
    """分块写作的意义就在这:写第 1 篇时看不到第 2 篇的材料,就编不出跨篇的事实。"""
    c = _content()
    c["details"][0]["reading"] = "改了备案口径,涉及 470 个站点。"
    bundles = dict(BUNDLE_A, P_OTHER="全国已建 470 个站点。")
    v = repair.audit_blocks(c, PROFILE, bundles)
    assert [(x["gate"], x["kind"]) for x in v] == [("F", "number")]


def test_overview_may_cite_what_the_details_wrote():
    """概述是从已写完的各块收上来的,引用正文里的数字不该算无源。"""
    c = _content()
    c["details"][0]["focus"] = "第三条要求年底前完成,涉及 470 个站点。"
    c["overview"] = "本月涉及 470 个站点。"
    bundles = {"P_A": "## RAW\n第三条 各省年底前完成。全国 470 个站点。"}
    assert [x["location"] for x in repair.audit_blocks(c, PROFILE, bundles)] == []


def test_repair_is_rejected_when_it_would_break_facts():
    """返修把风格改好了却把数字改错,不算变好。"""
    c = _content()
    c["details"][0]["reading"] = "涉及 1685 万千瓦,详见「附件」。"
    bundles = {"P_A": "## RAW\n第三条 各省年底前完成。共 1685 万千瓦。"}
    client = FakeClient({"details[01].reading": "涉及 1658 万千瓦,详见附件。"})
    out, caveats, _ = repair.run_repair(client, c, bundles, PROFILE,
                                        adjudicate_facts=False)
    assert out["details"][0]["reading"] == "涉及 1685 万千瓦,详见「附件」。"
