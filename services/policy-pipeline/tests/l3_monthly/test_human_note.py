"""MA9:人工修改意见回炉。

页面上提交的意见落在 content.pendingNote。这一步把它变成一次**定向**返修:
先问模型这条意见说的是哪几段(意见是自然语言,靠字符串匹配定位太脆),
再走 MA7 同一条链重写那几段。

铁律:**人工意见同样过 F 门**。人说了不等于稿子里就能写——
改完仍要过三道门,过不了就不采用并记 caveat,而不是因为"是人说的"就放行。
"""
import pytest

from scripts.l3_monthly import human_note as hn


PROFILE = {
    "schema_version": 1, "status": "active", "profile_id": "t",
    "effective_from": "2026-08-31",
    "businesses": [{"id": "charging", "zh": "充电"}],
    "not_business_lines": [], "relevance_rules": {}, "signals": [],
    "open_questions": [],
}
BUNDLES = {"P_A": "## RAW 原文\n第三条 各省应于年底前完成备案。共 1685 万千瓦。"}


def _content(**over):
    base = {
        "schema": "monthly.v2", "month": "2026-07",
        "overview": "本月政策密度抬升。", "businessTakes": [],
        "details": [{"no": "01", "policyId": "P_A", "title": "甲文件",
                     "info": "发文机关:国家能源局。", "reading": "改了备案口径。",
                     "focus": "第三条要求年底前完成。", "advice": []}],
        "localRoundup": "", "appendix": "", "caveats": [],
    }
    base.update(over)
    return base


class Client:
    def __init__(self, locate="", rewrite="重写后的正文。"):
        self.locate, self.rewrite = locate, rewrite
        self.users = []

    def complete(self, system, user, max_tokens=None):
        self.users.append(user)
        if "哪几段" in system:
            return self.locate
        return self.rewrite


# ── ① 定位 ─────────────────────────────────────────────────────
def test_locate_returns_only_known_locations():
    c = Client(locate='{"locations":["details[01].reading","details[99].nope"]}')
    got = hn.locate_targets(c, "解读那段写错了", ["overview", "details[01].reading"])
    assert got == ["details[01].reading"]


def test_locate_falls_back_to_everything_when_model_fails():
    """定不出来就全篇都当候选——总比把意见丢掉强,反正每段改完都要过门。"""
    c = Client(locate="不是 JSON")
    got = hn.locate_targets(c, "整体太啰嗦", ["overview", "details[01].reading"])
    assert got == ["overview", "details[01].reading"]


def test_locate_prompt_carries_the_note_and_the_block_labels():
    c = Client(locate='{"locations":[]}')
    hn.locate_targets(c, "第一篇的解读写错了", ["details[01].reading"])
    assert "第一篇的解读写错了" in c.users[0]
    assert "details[01].reading" in c.users[0]


# ── ② 回炉 ─────────────────────────────────────────────────────
def test_note_rewrites_only_the_targeted_block():
    c = Client(locate='{"locations":["details[01].reading"]}',
               rewrite="备案口径按第三条执行。")
    out, caveats, applied = hn.apply_note(c, _content(), BUNDLES, PROFILE,
                                          "解读要点明第三条")
    assert out["details"][0]["reading"] == "备案口径按第三条执行。"
    assert out["details"][0]["focus"] == "第三条要求年底前完成。"
    assert applied == ["details[01].reading"]


def test_rewrite_that_breaks_the_fact_gate_is_not_applied():
    """人说了不等于能写。改出来的东西回指不到素材,照样不采用。"""
    c = Client(locate='{"locations":["details[01].reading"]}',
               rewrite="备案口径涉及 9999 万千瓦。")
    out, caveats, applied = hn.apply_note(c, _content(), BUNDLES, PROFILE,
                                          "把规模写进去")
    assert out["details"][0]["reading"] == "改了备案口径。"
    assert applied == []
    assert any("未采用" in cv["note"] for cv in caveats)


def test_rewrite_that_breaks_the_style_gate_is_not_applied():
    c = Client(locate='{"locations":["details[01].reading"]}',
               rewrite="改了「备案」口径。")
    out, _, applied = hn.apply_note(c, _content(), BUNDLES, PROFILE, "加个引号")
    assert out["details"][0]["reading"] == "改了备案口径。"
    assert applied == []


def test_pending_note_is_cleared_and_recorded():
    """回炉完就把 pendingNote 清掉,否则下一轮会把同一条意见再跑一遍。"""
    c = Client(locate='{"locations":["details[01].reading"]}', rewrite="新的解读。")
    out, _, _ = hn.apply_note(c, _content(pendingNote="解读要改"), BUNDLES, PROFILE,
                              "解读要改")
    assert "pendingNote" not in out or not out["pendingNote"]
    assert out["humanNote"] == "解读要改"


def test_empty_note_is_a_no_op():
    c = Client()
    out, caveats, applied = hn.apply_note(c, _content(), BUNDLES, PROFILE, "   ")
    assert applied == [] and caveats == [] and c.users == []


def test_note_is_given_to_the_writer_along_with_the_bundle():
    c = Client(locate='{"locations":["details[01].reading"]}', rewrite="新解读。")
    hn.apply_note(c, _content(), BUNDLES, PROFILE, "要点明第三条")
    rewrite_user = c.users[-1]
    assert "要点明第三条" in rewrite_user
    assert "## RAW 原文" in rewrite_user


def test_caveats_from_the_note_round_use_the_same_shape():
    c = Client(locate='{"locations":["details[01].reading"]}',
               rewrite="备案口径涉及 9999 万千瓦。")
    _, caveats, _ = hn.apply_note(c, _content(), BUNDLES, PROFILE, "写规模")
    assert set(caveats[0]) >= {"gate", "location", "note"}


# ── ③ 素材来源 ─────────────────────────────────────────────────
def test_load_bundles_reuses_the_pack_from_ma4(tmp_path):
    """回炉要用当初写稿时那一批素材。重新装一遍可能拿到不一样的材料,
    F 门的对账就失去意义。"""
    import json
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "01_national_detail__P_A.md").write_text("甲的素材", encoding="utf-8")
    (pack / "INDEX.json").write_text(json.dumps({"items": [
        {"policy_id": "P_A", "file": "01_national_detail__P_A.md"},
        {"policy_id": "P_GHOST", "status": "MISSING_RAW"},
    ]}, ensure_ascii=False), encoding="utf-8")
    assert hn.load_bundles(str(pack)) == {"P_A": "甲的素材"}
