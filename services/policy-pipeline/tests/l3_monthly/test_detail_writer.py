"""MA5a 每篇详情块:模型写判断,代码执行约束。

这一步只喂**它自己那一个 bundle**,所以它天然写不出跨篇的杜撰;
真正要代码盯死的是两件在既有产线上出过事的事:
① 决策建议不许溢出 MA2 算出的 business_hits(否则又变回"每篇都对三条业务线各说一句");
② 不许写「X 业务:不相关」——那是 D 门与业务口径门都禁的。
"""
import json

import pytest

from scripts.l3_monthly import detail_writer as dw


NAMES = {"fuel": "加油", "charging": "充电", "power": "电力"}


def _detail(**over):
    base = {
        "info": "发文机关:国家发展改革委。发文日期:2026年7月8日。文号:发改能源〔2026〕688号。",
        "reading": "该文件把充电设施纳入电力需求侧管理。",
        "focus": "第三条要求各省在年底前完成备案。",
        "advice": [{"business": "充电", "tag": "B 研究/跟进", "text": "先摸清备案口径。"}],
    }
    base.update(over)
    return base


class FakeClient:
    """按次返回预置输出;记录每次的 system 段以便验证前缀缓存。"""

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.systems = []
        self.calls = 0

    def complete(self, system, user, max_tokens=None):
        self.calls += 1
        self.systems.append(system)
        return self.outputs.pop(0)


# ── ① 解析 ──────────────────────────────────────────────────────
def test_parse_detail_accepts_fenced_json():
    out = dw.parse_detail("```json\n" + json.dumps(_detail(), ensure_ascii=False) + "\n```")
    assert out["reading"].startswith("该文件")


def test_parse_detail_rejects_missing_section():
    d = _detail()
    del d["focus"]
    with pytest.raises(dw.DetailError):
        dw.parse_detail(json.dumps(d, ensure_ascii=False))


def test_parse_detail_rejects_empty_section():
    """空段落不是"这篇没什么好说的",是模型没写出来。留空会一路进稿。"""
    with pytest.raises(dw.DetailError):
        dw.parse_detail(json.dumps(_detail(reading="  "), ensure_ascii=False))


def test_parse_detail_rejects_advice_not_list():
    with pytest.raises(dw.DetailError):
        dw.parse_detail(json.dumps(_detail(advice="充电业务:跟进"), ensure_ascii=False))


# ── ② 决策建议受 business_hits 约束 ────────────────────────────
def test_advice_outside_business_hits_is_dropped():
    """MA2 只判中充电,写作却给加油也来一条——那是凭空生出来的业务关联。"""
    d = _detail(advice=[{"business": "充电", "tag": "C 跟踪", "text": "跟进备案。"},
                        {"business": "加油", "tag": "C 跟踪", "text": "顺带一提。"}])
    out, caveats = dw.enforce_advice(d, ["charging"], NAMES)
    assert [a["business"] for a in out["advice"]] == ["充电"]
    assert any("加油" in c["note"] and c["gate"] == "B" for c in caveats)


def test_empty_business_hits_means_no_advice():
    """MA2 没判中任何业务线时,决策建议就得是空的——不许写「X 业务:不相关」补位。"""
    out, caveats = dw.enforce_advice(_detail(), [], NAMES)
    assert out["advice"] == []
    assert caveats


def test_illegal_action_tag_is_dropped():
    d = _detail(advice=[{"business": "充电", "tag": "E 立即执行", "text": "马上上线。"}])
    out, caveats = dw.enforce_advice(d, ["charging"], NAMES)
    assert out["advice"] == []
    assert any(c["gate"] == "D" for c in caveats)


def test_legal_tags_come_from_the_gate_whitelist():
    """标签白名单只有一份,在 D 门里。这里再抄一份就会走散。"""
    from scripts.l3_monthly import gates
    for tag in sorted(gates.ALLOWED_TAGS):
        d = _detail(advice=[{"business": "充电", "tag": tag, "text": "跟进。"}])
        out, _ = dw.enforce_advice(d, ["charging"], NAMES)
        assert len(out["advice"]) == 1, f"{tag} 应被接受"


def test_duplicate_business_keeps_first():
    d = _detail(advice=[{"business": "充电", "tag": "C 跟踪", "text": "第一条。"},
                        {"business": "充电", "tag": "A 趁早行动", "text": "第二条。"}])
    out, caveats = dw.enforce_advice(d, ["charging"], NAMES)
    assert [a["text"] for a in out["advice"]] == ["第一条。"]
    assert caveats


def test_advice_with_blank_text_is_dropped():
    d = _detail(advice=[{"business": "充电", "tag": "C 跟踪", "text": "  "}])
    out, caveats = dw.enforce_advice(d, ["charging"], NAMES)
    assert out["advice"] == [] and caveats


# ── ③ 写作编排 ─────────────────────────────────────────────────
def _judgment(hits, relevance="high"):
    return {"policy_id": "P_A", "business_hits": hits, "relevance": relevance,
            "issuer_from_body": "国家发展改革委", "issue_date_from_body": "2026年7月8日",
            "official_number_from_body": "发改能源〔2026〕688号", "dq": ""}


def test_write_detail_fills_facts_from_code_not_model():
    """编号、policyId、标题是已知事实,不交给模型写——模型写就有写错的机会。"""
    c = FakeClient([json.dumps(_detail(), ensure_ascii=False)])
    d, caveats = dw.write_detail(c, "口径段", "bundle 正文", _judgment(["charging"]),
                                 no="03", policy_id="P_A", title="甲文件",
                                 business_names=NAMES)
    assert d["no"] == "03" and d["policyId"] == "P_A" and d["title"] == "甲文件"


def test_write_detail_retries_then_errors_without_faking():
    """连续写不出合法结构就报错,**不兜底编一段**——编出来的段落事后查不出来。"""
    c = FakeClient(["不是 JSON", "还是不是 JSON"])
    with pytest.raises(dw.DetailError):
        dw.write_detail(c, "口径段", "bundle", _judgment(["charging"]),
                        no="01", policy_id="P_A", title="甲", business_names=NAMES,
                        retries=1)
    assert c.calls == 2


def test_write_detail_system_prefix_is_identical_across_policies():
    """一期二十多篇详情共用同一段口径与体例。放 system 且逐字相同才吃得上前缀缓存。"""
    c = FakeClient([json.dumps(_detail(), ensure_ascii=False)] * 2)
    for pid in ("P_A", "P_B"):
        dw.write_detail(c, "口径段", f"bundle-{pid}", _judgment(["charging"]),
                        no="01", policy_id=pid, title="甲", business_names=NAMES)
    assert c.systems[0] == c.systems[1]


def test_write_detail_carries_ma2_dq_into_caveats():
    """MA2 标了数据质量问题的,成稿要挂着——不能写完就把警告丢了。"""
    j = _judgment(["charging"])
    j["dq"] = "落款日期抽不到"
    c = FakeClient([json.dumps(_detail(), ensure_ascii=False)])
    _, caveats = dw.write_detail(c, "口径段", "bundle", j, no="01", policy_id="P_A",
                                 title="甲", business_names=NAMES)
    assert any("落款日期抽不到" in cv["note"] for cv in caveats)


def test_caveat_location_points_at_the_block():
    """审计条目要能定位到段,MA7 才可能只返修这一段而不是整篇重写。"""
    d = _detail(advice=[{"business": "加油", "tag": "C 跟踪", "text": "越界。"}])
    _, caveats = dw.enforce_advice(d, ["charging"], NAMES, location="details[03]")
    assert all(c["location"].startswith("details[03]") for c in caveats)
