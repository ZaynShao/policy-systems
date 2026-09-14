"""推理模型的 token 预算。

deepseek-v4-pro 是**推理模型**:max_tokens 不够时不是把正文截断,而是
推理把预算吃光、**正文返回空串**(finish_reason=length)。而
OpenAICompatClient.complete() 只取 content 不看 finish_reason,
于是"预算不够"和"模型没话说"在代码里长得一模一样——链路会安静地降级成
一份近乎空白的月刊,同时把几十万 token 花完。

2026-09-08 拿 5 篇真 vault 政策在生产端点实测(deepseek-v4-pro,判定任务):
推理 token **min 1291 / 中位 1558 / max 2564**,而正文只有约 50 token。
判定这种"输出极短"的步骤照样要给到 4000 上下——预算是给推理留的,不是给正文。
"""
import json

from scripts.l3_monthly import budget, detail_writer, judge, section_writer


# 实测的推理开销上限(5 篇真政策)。样本小,故留足余量。
MEASURED_MAX_REASONING = 2564


def test_every_budget_covers_the_measured_reasoning_overhead():
    """任何一档预算都必须能装下实测的推理上限,否则该步骤稳定返回空。"""
    for name in ("JUDGE", "WRITE", "SECTION", "REPAIR", "SHORT_JSON", "SLATE"):
        value = getattr(budget, name)
        assert value > MEASURED_MAX_REASONING, f"{name}={value} 装不下推理开销"


def test_escalate_doubles_each_attempt():
    """原样重试一遍解决不了「预算被推理吃光」——失败往往正是预算不够。"""
    assert budget.escalate(4000, 0) == 4000
    assert budget.escalate(4000, 1) == 8000
    assert budget.escalate(4000, 2) == 16000


class Recorder:
    """记下每次调用的 max_tokens;前 n 次返回空串(模拟预算被推理吃光)。"""

    def __init__(self, empty_first=1, good=""):
        self.empty_first, self.good = empty_first, good
        self.budgets = []

    def complete(self, system, user, max_tokens=None):
        self.budgets.append(max_tokens)
        if len(self.budgets) <= self.empty_first:
            return ""
        return self.good


def _candidate():
    from scripts.l3_monthly.models import Candidate
    return Candidate(policy_id="P_A", title="甲文件", official_number="",
                     date="2026-07-10", date_missing=False, raw_path="",
                     body_len=100, region_name="江苏省")


def test_judge_retry_raises_the_budget():
    good = json.dumps({"level": "国家", "business_hits": [], "relevance": "low",
                       "why": "无关", "issue_date_from_body": "",
                       "issuer_from_body": "", "official_number_from_body": "",
                       "decision_variables_touched": []}, ensure_ascii=False)
    c = Recorder(empty_first=1, good=good)
    judge.judge_one(c, "口径段", [], _candidate(), "正文", retries=1)
    assert len(c.budgets) == 2
    assert c.budgets[1] > c.budgets[0], "重试必须放大预算"
    assert c.budgets[0] >= budget.JUDGE


def test_detail_retry_raises_the_budget():
    good = json.dumps({"info": "发文机关:某委。", "reading": "改了口径。",
                       "focus": "第三条。", "advice": []}, ensure_ascii=False)
    c = Recorder(empty_first=1, good=good)
    detail_writer.write_detail(c, "口径段", "bundle", {"business_hits": []},
                               no="01", policy_id="P_A", title="甲",
                               business_names={}, retries=1)
    assert len(c.budgets) == 2 and c.budgets[1] > c.budgets[0]
    assert c.budgets[0] >= budget.WRITE


def test_section_retry_raises_the_budget():
    c = Recorder(empty_first=1, good="综述正文。")
    section_writer.write_roundup(c, "口径段", ["条目一"], "2026-07", retries=1)
    assert len(c.budgets) == 2 and c.budgets[1] > c.budgets[0]
    assert c.budgets[0] >= budget.SECTION


def test_overview_retry_raises_the_budget():
    good = json.dumps({"overview": "概述。", "businessTakes": []}, ensure_ascii=False)
    c = Recorder(empty_first=1, good=good)
    section_writer.write_overview(c, "口径段", [], [], "2026-07", retries=1)
    assert len(c.budgets) == 2 and c.budgets[1] > c.budgets[0]
