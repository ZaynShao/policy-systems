"""MA3:选目定调。

输入是 MA2 的**结构化判定**,不喂 RAW——选目靠的是判定结果与编辑判断,不是重读原文,
喂 RAW 只会把上下文撑爆。输出 slate.json。

分工:模型做编辑判断(排序、定调、写 why),**约束由代码执行**。
代码只做「修剪」不做「发明」:把超配额的砍掉、把「需人工裁定」的从详情挪进速览、
给 id 撞车的补 title_hint——这些都是执行画像与 schema 的既定规则,不是替模型做编辑决定。
"""
import json

import pytest

from scripts.l3_monthly import slate_builder as sb


def _j(pid, title, relevance="high", level="国家", **over):
    d = {"policy_id": pid, "title": title, "level": level, "relevance": relevance,
         "issue_date_from_body": "2026-07-10", "business_hits": ["fuel"],
         "decision_variables_touched": ["批发价"], "why": "改批发价", "dq": "",
         "near_dup_group": "", "id_collision": False, "docno_conflict": False}
    d.update(over)
    return d


def _item(pid, **over):
    d = {"policy_id": pid, "title_hint": pid, "score": "4分", "rank": 1,
         "why": "理由", "dq": ""}
    d.update(over)
    return d


def _slate(national=(), local=(), roundup=(), appendix=()):
    return {"month": "2026-07", "narrative": "本月定调",
            "sections": {"national_detail": list(national), "local_detail": list(local),
                         "roundup": list(roundup), "appendix": list(appendix)}}


class _Fake:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def complete(self, system, user, max_tokens=1024):
        self.calls.append((system, user))
        return self.replies.pop(0)


# ── 输入渲染 ────────────────────────────────────────────────────
def test_render_judgments_carries_decision_signal_not_raw():
    txt = sb.render_judgments([_j("P_A", "甲政策", why="改了批发价", dq="日期存疑")])
    assert "P_A" in txt and "甲政策" in txt
    assert "改了批发价" in txt and "日期存疑" in txt
    assert "high" in txt


def test_render_judgments_marks_collision_and_near_dup():
    txt = sb.render_judgments([
        _j("P_A", "甲", id_collision=True),
        _j("P_B", "乙", near_dup_group="通知::某规划"),
    ])
    assert "id撞车" in txt and "疑似重复" in txt


def test_render_judgments_skips_error_records():
    txt = sb.render_judgments([_j("P_A", "甲", relevance="error")])
    assert "P_A" not in txt, "判定失败的不该进选目视野"


# ── 约束校验 ────────────────────────────────────────────────────
def test_validate_flags_over_quota():
    js = [_j(f"P_{i}", f"政策{i}") for i in range(8)]
    s = _slate(national=[_item(f"P_{i}", rank=i + 1) for i in range(8)])
    errs = sb.validate_selection(s, js)
    assert any("national_detail" in e and "上限" in e for e in errs)


def test_validate_flags_manual_review_in_detail():
    js = [_j("P_A", "甲", relevance="需人工裁定")]
    errs = sb.validate_selection(_slate(national=[_item("P_A")]), js)
    assert any("需人工裁定" in e for e in errs)


def test_validate_flags_error_record_selected():
    js = [_j("P_A", "甲", relevance="error")]
    errs = sb.validate_selection(_slate(roundup=[_item("P_A")]), js)
    assert any("error" in e for e in errs)


def test_validate_flags_unknown_policy_id():
    errs = sb.validate_selection(_slate(national=[_item("P_X")]), [_j("P_A", "甲")])
    assert any("P_X" in e for e in errs)


def test_validate_flags_id_collision_without_title_hint():
    js = [_j("P_A", "甲", id_collision=True)]
    errs = sb.validate_selection(_slate(national=[_item("P_A", title_hint="")]), js)
    assert any("title_hint" in e for e in errs)


# ── 修剪(执行规则,不做编辑决定)────────────────────────────────
def test_repair_trims_over_quota_by_rank():
    js = [_j(f"P_{i}", f"政策{i}") for i in range(8)]
    s = _slate(national=[_item(f"P_{i}", rank=i + 1) for i in range(8)])
    fixed, repairs = sb.repair_selection(s, js)
    kept = [i["policy_id"] for i in fixed["sections"]["national_detail"]]
    assert kept == ["P_0", "P_1", "P_2", "P_3", "P_4"], "按 rank 保留前 5,不重新排序"
    assert any("national_detail" in r for r in repairs)


def test_repair_moves_manual_review_from_detail_to_roundup():
    js = [_j("P_A", "甲", relevance="需人工裁定")]
    fixed, repairs = sb.repair_selection(_slate(national=[_item("P_A")]), js)
    assert fixed["sections"]["national_detail"] == []
    assert [i["policy_id"] for i in fixed["sections"]["roundup"]] == ["P_A"]
    assert any("需人工裁定" in r for r in repairs)


def test_repair_drops_error_and_unknown_records():
    js = [_j("P_A", "甲", relevance="error")]
    fixed, repairs = sb.repair_selection(
        _slate(roundup=[_item("P_A"), _item("P_UNKNOWN")]), js)
    assert fixed["sections"]["roundup"] == []
    assert len(repairs) == 2


def test_repair_fills_title_hint_for_id_collision():
    js = [_j("P_A", "江苏省成品油价格调整公告（2026年第11号）", id_collision=True)]
    fixed, _ = sb.repair_selection(_slate(national=[_item("P_A", title_hint="")]), js)
    assert fixed["sections"]["national_detail"][0]["title_hint"].startswith("江苏省成品油")


def test_repair_drops_duplicate_pid_across_sections_keeping_first():
    js = [_j("P_A", "甲")]
    fixed, repairs = sb.repair_selection(
        _slate(national=[_item("P_A")], roundup=[_item("P_A")]), js)
    assert [i["policy_id"] for i in fixed["sections"]["national_detail"]] == ["P_A"]
    assert fixed["sections"]["roundup"] == []
    assert any("重复" in r for r in repairs)


def test_repair_is_idempotent():
    js = [_j(f"P_{i}", f"政策{i}") for i in range(8)]
    s = _slate(national=[_item(f"P_{i}", rank=i + 1) for i in range(8)])
    once, _ = sb.repair_selection(s, js)
    twice, again = sb.repair_selection(once, js)
    assert twice == once and again == []


# ── 编排 ────────────────────────────────────────────────────────
def test_build_slate_happy_path():
    js = [_j("P_A", "甲"), _j("P_B", "乙", level="地方")]
    reply = json.dumps(_slate(national=[_item("P_A")], local=[_item("P_B")]),
                       ensure_ascii=False)
    s, repairs = sb.build_slate(_Fake([reply]), "2026-07", js)
    assert s["month"] == "2026-07" and repairs == []
    assert [i["policy_id"] for i in s["sections"]["national_detail"]] == ["P_A"]


def test_build_slate_forces_month_from_caller():
    """模型可能把月份写错;月份是调用方给的事实,不接受模型的版本。"""
    js = [_j("P_A", "甲")]
    bad = _slate(national=[_item("P_A")]); bad["month"] = "2025-01"
    s, _ = sb.build_slate(_Fake([json.dumps(bad, ensure_ascii=False)]), "2026-07", js)
    assert s["month"] == "2026-07"


def test_build_slate_retries_on_bad_json():
    js = [_j("P_A", "甲")]
    good = json.dumps(_slate(national=[_item("P_A")]), ensure_ascii=False)
    c = _Fake(["不是 JSON", good])
    s, _ = sb.build_slate(c, "2026-07", js)
    assert len(c.calls) == 2 and s["sections"]["national_detail"]


def test_build_slate_raises_when_still_invalid_after_retries():
    """选目产不出来就没有可写的东西了——硬停并告警,不能编一份出来。"""
    js = [_j("P_A", "甲")]
    with pytest.raises(sb.SlateError):
        sb.build_slate(_Fake(["坏", "还是坏"]), "2026-07", js, retries=1)


def test_build_slate_rejects_empty_narrative():
    js = [_j("P_A", "甲")]
    s = _slate(national=[_item("P_A")]); s["narrative"] = "  "
    good = json.dumps(_slate(national=[_item("P_A")]), ensure_ascii=False)
    c = _Fake([json.dumps(s, ensure_ascii=False), good])
    out, _ = sb.build_slate(c, "2026-07", js)
    assert len(c.calls) == 2, "空定调等于没做编辑判断,应重试"


def test_build_slate_prompt_has_no_raw_body():
    js = [_j("P_A", "甲")]
    c = _Fake([json.dumps(_slate(national=[_item("P_A")]), ensure_ascii=False)])
    sb.build_slate(c, "2026-07", js)
    _, user = c.calls[0]
    assert "政策原文" not in user and len(user) < 4000


def test_render_judgments_marks_periodic_series_with_size():
    """成品油调价这类系列本月可能四十来篇;不告诉编辑它是系列,它就会占满速览位。"""
    txt = sb.render_judgments([
        _j("P_A", "2026年7月3日24时起贵州成品油价格调整",
           series_group="时起贵州成品油价格调整", series_size=7)])
    assert "周期性系列" in txt and "7篇" in txt


def test_slate_system_tells_editor_to_collapse_series():
    from scripts.l3_monthly import prompts as pr
    assert "周期性系列" in pr.SLATE_SYSTEM
    assert "最多占一个位置" in pr.SLATE_SYSTEM
