"""MA5b 省级综述 / MA5c 附录 / MA5e 概述+三大业务速判。

三段的共同点是**输入不是 RAW**:
- 综述与附录拿的是代码拼出的条目摘要(标题/落款/MA2 的业务命中与理由),
  综述是把已判定的东西串起来,不是重新解读原文;
- 概述最后写,输入是**已写完的各块**——概述因此必然与正文一致,
  而不是各自对着原文再想一遍。

代码要盯死的是业务速判:只有正文里真出过决策建议的业务线才配有一条速判。
现有产线的病就是每条业务线都硬凑一句,凑出来的比没有更糟。
"""
import json

import pytest

from scripts.l3_monthly import section_writer as sw


BUSINESSES = [{"id": "fuel", "zh": "加油"}, {"id": "charging", "zh": "充电"},
              {"id": "power", "zh": "电力"}]


class FakeClient:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.systems, self.users, self.calls = [], [], 0

    def complete(self, system, user, max_tokens=None):
        self.calls += 1
        self.systems.append(system)
        self.users.append(user)
        return self.outputs.pop(0)


def _item(pid, title, section="roundup"):
    return {"policy_id": pid, "title": title, "section": section,
            "level_editorial": "地方(速览)", "file": f"01_{section}__{pid}.md"}


def _judgment(pid, hits, why="改变备案口径", issuer="江苏省发展改革委",
              date="2026年7月8日"):
    return {"policy_id": pid, "business_hits": hits, "why": why,
            "issuer_from_body": issuer, "issue_date_from_body": date,
            "relevance": "high", "dq": ""}


# ── ① 条目摘要:代码拼,不含 RAW ─────────────────────────────────
def test_digest_carries_facts_but_no_raw():
    d = sw.digest(_item("P_A", "江苏充电设施管理办法"), _judgment("P_A", ["charging"]),
                  {"fuel": "加油", "charging": "充电", "power": "电力"})
    assert "江苏充电设施管理办法" in d and "江苏省发展改革委" in d
    assert "充电" in d and "改变备案口径" in d
    assert "RAW" not in d and "0_raw" not in d


def test_digest_omits_fields_it_does_not_have():
    """抽不到的落款留空即可,不能写「未知」占位——那会被当成事实抄进综述。"""
    d = sw.digest(_item("P_A", "某公告"), _judgment("P_A", [], issuer="", date=""),
                  {})
    assert "未知" not in d and "None" not in d


# ── ② MA5b 省级综述 / MA5c 附录 ────────────────────────────────
def test_write_roundup_returns_text():
    c = FakeClient(["江苏、浙江两省本月集中调整了充电设施备案口径。"])
    out = sw.write_roundup(c, "口径段", ["条目一", "条目二"], "2026-07")
    assert out.startswith("江苏")


def test_write_roundup_retries_then_errors_without_faking():
    c = FakeClient(["", "   "])
    with pytest.raises(sw.SectionError):
        sw.write_roundup(c, "口径段", ["条目一"], "2026-07", retries=1)
    assert c.calls == 2


def test_write_roundup_skipped_when_no_items():
    """本月没有地方条目就没有综述可写。空输入下不许调模型编一段。"""
    c = FakeClient([])
    assert sw.write_roundup(c, "口径段", [], "2026-07") == ""
    assert c.calls == 0


def test_write_appendix_skipped_when_no_items():
    c = FakeClient([])
    assert sw.write_appendix(c, "口径段", [], "2026-07") == ""
    assert c.calls == 0


# ── ③ MA5e 概述 + 三大业务速判 ─────────────────────────────────
def _details(*advice_businesses):
    out = []
    for i, biz in enumerate(advice_businesses, 1):
        out.append({"no": f"{i:02d}", "policyId": f"P_{i}", "title": f"文件{i}",
                    "info": "发文机关:某委。", "reading": "改了备案口径。",
                    "focus": "第三条要求年底前完成。",
                    "advice": [{"business": biz, "tag": "C 跟踪", "text": "跟进。"}]})
    return out


def _overview_json(takes):
    return json.dumps({"overview": "本月政策密度抬升。", "businessTakes": takes},
                      ensure_ascii=False)


def test_overview_input_is_written_blocks_not_raw():
    """概述最后写,输入是已写完的各块——这样它必然与正文一致。"""
    c = FakeClient([_overview_json([{"business": "充电", "text": "备案口径要摸清。"}])])
    sw.write_overview(c, "口径段", _details("充电"), BUSINESSES, "2026-07")
    user = c.users[0]
    assert "改了备案口径。" in user and "第三条要求年底前完成。" in user
    assert "## RAW 原文" not in user


def test_business_take_without_any_advice_is_dropped():
    """正文里一条加油建议都没有,速判却给加油来一句——那是凭空生出来的。"""
    c = FakeClient([_overview_json([
        {"business": "充电", "text": "备案口径要摸清。"},
        {"business": "加油", "text": "本月加油线也值得留意。"}])])
    _, takes, caveats = sw.write_overview(c, "口径段", _details("充电"),
                                          BUSINESSES, "2026-07")
    assert [t["business"] for t in takes] == ["充电"]
    assert any("加油" in cv["note"] for cv in caveats)


def test_business_takes_follow_profile_order():
    c = FakeClient([_overview_json([
        {"business": "电力", "text": "电力线。"},
        {"business": "加油", "text": "加油线。"}])])
    _, takes, _ = sw.write_overview(c, "口径段", _details("加油", "电力"),
                                    BUSINESSES, "2026-07")
    assert [t["business"] for t in takes] == ["加油", "电力"]


def test_missing_take_for_a_covered_business_is_flagged():
    """正文里出过充电建议,速判却漏了充电——读者会以为本月充电线没事。"""
    c = FakeClient([_overview_json([{"business": "加油", "text": "加油线。"}])])
    _, takes, caveats = sw.write_overview(c, "口径段", _details("加油", "充电"),
                                          BUSINESSES, "2026-07")
    assert [t["business"] for t in takes] == ["加油"]
    assert any("充电" in cv["note"] and "漏" in cv["note"] for cv in caveats)


def test_overview_rejects_missing_fields_and_retries():
    c = FakeClient(['{"overview":"只有概述"}', _overview_json([])])
    ov, takes, _ = sw.write_overview(c, "口径段", _details(), BUSINESSES, "2026-07")
    assert c.calls == 2 and ov == "本月政策密度抬升。" and takes == []


def test_overview_errors_rather_than_faking():
    c = FakeClient(["不是 JSON", "还是不是"])
    with pytest.raises(sw.SectionError):
        sw.write_overview(c, "口径段", _details("充电"), BUSINESSES, "2026-07",
                          retries=1)


# ── ④ 只进速览的业务线也要有速判(真数据推出来的) ───────────────
def test_business_covered_only_by_roundup_still_gets_a_take():
    """实测各期 shortlist 有 13–15% 是成品油调价这类周期性系列,按编辑口径进速览
    不进详情,而它们恰恰全是加油线。只认详情的话,一个满是加油政策的月份
    会出一份「本月加油线没事」的月刊。"""
    c = FakeClient([_overview_json([
        {"business": "充电", "text": "备案口径要摸清。"},
        {"business": "加油", "text": "本月各省成品油调价密集,留意价差窗口。"}])])
    _, takes, caveats = sw.write_overview(
        c, "口径段", _details("充电"), BUSINESSES, "2026-07",
        roundup="江苏等省本月多次调整成品油价格。", extra_hits=["加油"])
    assert [t["business"] for t in takes] == ["加油", "充电"]
    assert not [cv for cv in caveats if "加油" in cv["note"]]


def test_overview_user_carries_roundup_and_appendix():
    """spec §6.3 说 MA5e 的输入是已写完的**各块**,不是只有详情。"""
    c = FakeClient([_overview_json([])])
    sw.write_overview(c, "口径段", _details(), BUSINESSES, "2026-07",
                      roundup="省级综述正文。", appendix="附录正文。")
    assert "省级综述正文。" in c.users[0] and "附录正文。" in c.users[0]


def test_digest_marks_items_that_already_have_a_detail_block():
    """地方(重要)的条目本期另有专段展开,综述里再讲一遍就是重复。"""
    d = sw.digest(_item("P_A", "江苏办法", section="local_detail"),
                  _judgment("P_A", ["charging"]), {"charging": "充电"})
    assert "已有独立详情块" in d
    assert "已有独立详情块" not in sw.digest(
        _item("P_B", "浙江公告"), _judgment("P_B", ["charging"]), {"charging": "充电"})
