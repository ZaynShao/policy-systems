"""检索规划阶段。

规划器的价值在于把"撒网"换成"取证",但它多了一次模型调用,也就多了一处
可能把整个回答带崩的地方。所以这里的测试重点有两块:
产出要**可执行且合法**(不能给不存在的主题 id),失败要**软着陆**(退回旧行为)。
"""
from __future__ import annotations

import datetime

import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.planner import (
    RetrievalPlan,
    _sanitize,
    build_planner,
    make_plan,
    plan_to_prompt,
)
from app.store import ThemeInfo

THEMES = [
    ThemeInfo(id="charging_infra", name="充电基础设施", count=151),
    ThemeInfo(id="energy_storage_theme", name="新型储能", count=122),
]


def _planner_model(plan: dict):
    """FunctionModel 产出结构化结果:要调 pydantic-ai 生成的那个输出工具。

    工具名从 info.output_tools 拿,不写死——写死会在库改名时静默失效。
    """

    def fn(messages, info: AgentInfo) -> ModelResponse:
        tool_name = info.output_tools[0].name
        return ModelResponse(parts=[ToolCallPart(tool_name=tool_name, args=plan)])

    return FunctionModel(fn)


@pytest.mark.asyncio
async def test_plan_survives_and_is_sanitized():
    """模型给的主题 id 不在登记表里就得掐掉。

    结构化输出保证类型,保证不了取值:一个不存在的 theme_id 查出来是空结果,
    而空结果看起来像"库里没有这类政策",比直接报错更有害。
    """
    planner = build_planner(
        _planner_model(
            {
                "kind": "survey",
                "theme_ids": ["charging_infra", "不存在的主题"],
                "business_lines": ["充电", "外卖"],
                "date_from": "2026-05-20",
                "date_to": None,
                "keywords": ["充电桩", "  "],
                "issuer_sweeps": ["财政部"],
                "note": "充电类盘点",
            }
        )
    )
    plan = await make_plan(
        planner, question="最近对充电影响大的政策", themes=THEMES,
        today=datetime.date(2026, 8, 18),
    )
    assert plan is not None
    assert plan.theme_ids == ["charging_infra"], "不存在的主题必须掐掉"
    assert plan.business_lines == ["充电"], "非法业务线必须掐掉"
    assert plan.keywords == ["充电桩"], "空白关键词必须掐掉"
    assert plan.issuer_sweeps == ["财政部"]


def test_issuer_sweeps_only_apply_to_survey_questions():
    """解读单篇政策时挨个扫机关是纯浪费,模型给了也不执行。

    机关扫描存在的唯一理由是兜住跨条线文件(财税/认证既无能源主题又低分),
    那是盘点类问题才有的需求。
    """
    plan = _sanitize(
        RetrievalPlan(
            kind="single_policy",
            theme_ids=["charging_infra"],
            issuer_sweeps=["财政部", "税务总局"],
        ),
        THEMES,
    )
    assert plan.issuer_sweeps == []
    assert plan.theme_ids == ["charging_infra"], "主题不受影响"


def test_at_most_three_themes():
    """主题给太多就退化成撒网了,而撒网正是规划要解决的问题。"""
    many = [ThemeInfo(id=f"t{i}", name=str(i)) for i in range(6)]
    plan = _sanitize(
        RetrievalPlan(kind="survey", theme_ids=[f"t{i}" for i in range(6)]), many
    )
    assert len(plan.theme_ids) == 3


@pytest.mark.asyncio
async def test_planner_failure_degrades_to_no_plan():
    """规划器炸了必须返回 None,让下游退回无计划的旧行为。

    多加一层就多一个失败点;这一层绝不能有权让用户拿不到答案。
    """

    def boom(messages, info: AgentInfo) -> ModelResponse:
        raise RuntimeError("planner exploded")

    planner = build_planner(FunctionModel(boom))
    plan = await make_plan(planner, question="q", themes=THEMES)
    assert plan is None
    assert plan_to_prompt(None) == "", "没有计划就不该往 prompt 里塞任何东西"


def test_plan_renders_as_instructions_not_suggestions():
    """渲染出来的是给模型执行的指令,要点名工具参数,否则它不知道怎么落地。"""
    plan = RetrievalPlan(
        kind="survey",
        theme_ids=["charging_infra"],
        business_lines=["充电"],
        date_from="2026-04-20",
        issuer_sweeps=["财政部"],
    )
    text = plan_to_prompt(plan)
    assert "theme_id" in text, "要告诉模型这个计划对应哪个工具参数"
    assert "charging_infra" in text
    assert "财政部" in text
    assert "2026-04-20" in text
    assert "盘点" in text


def test_single_policy_plan_says_not_to_sweep():
    plan = RetrievalPlan(kind="single_policy", keywords=["分时电价"])
    text = plan_to_prompt(plan)
    assert "不要做盘点式扫描" in text
