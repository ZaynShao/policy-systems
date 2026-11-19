"""检索规划:回答之前先想清楚要查什么。

为什么需要它:平铺的工具循环里,模型拿到"最近对充电影响大的政策"这种问题,
只能靠 system prompt 里"至少扫四轮"的泛化指令去撒网——2026-08-18 的生产日志
是一口气并发八个检索,其中三个是挨个猜部委名。拿到了并行的成本,没拿到并行的收益。

规划阶段是**一次不带工具的模型调用**,产出结构化的检索计划,再交给下游执行。
它便宜(无检索、输出几十个 token),但能把后续的检索从"撒网"变成"取证"。

失败要软着陆:规划出错就退回无计划的旧行为,绝不能因为多了一层而答不出来。
"""
from __future__ import annotations

import datetime
import logging
from typing import Any, Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from .store import ThemeInfo

logger = logging.getLogger("policy-qa")

QuestionKind = Literal["single_policy", "survey", "other"]

#: 规划阶段的预算护栏。它不调工具,正常几百 token 就够;设上限是防跑飞。
PLAN_MAX_CHARS = 2000


class RetrievalPlan(BaseModel):
    """一次问答的检索计划。字段都是**给下游执行的指令**,不是给用户看的文字。"""

    kind: QuestionKind = Field(
        description=(
            "问题类型。single_policy=解读某一篇具体政策;"
            "survey=盘点/筛选类(最近有哪些、对某业务影响大的有哪些);other=其它"
        )
    )
    theme_ids: list[str] = Field(
        default_factory=list,
        description="要扫的主题 id,只能从给定的主题登记表里选,最多 3 个。选不出就留空",
    )
    business_lines: list[str] = Field(
        default_factory=list,
        description="要扫的业务线,只能取 加油/充电/电力/乡村。选不出就留空",
    )
    date_from: str | None = Field(
        default=None, description="时间窗起点 YYYY-MM-DD。盘点类必填,解读单篇可留空"
    )
    date_to: str | None = Field(default=None, description="时间窗终点 YYYY-MM-DD,可留空")
    keywords: list[str] = Field(
        default_factory=list, description="要试的关键词,最多 3 个。主题能覆盖时就别用关键词"
    )
    issuer_sweeps: list[str] = Field(
        default_factory=list,
        description=(
            "要单独按机关扫一遍的机关名。**只在盘点类问题上用**,"
            "用于兜住财税、认证这类跨条线文件——它们既没有能源主题也没有高分,"
            "其它维度捞不到。最多 3 个"
        ),
    )
    note: str = Field(
        default="", description="一句话说明为什么这样选。给排查用,不会展示给用户"
    )


PLANNER_PROMPT = """你在给一个政策库问答助手做**检索规划**。你不回答问题,只决定该查什么。

今天是 {today}。

可选的主题(只能从这里选 id):
{themes}

业务线口径:加油(汽油为主)、充电(乘用车为主)、电力(储能/V2G/电力交易)、乡村(一笔带过即可)。

规划要点:
- **优先用主题**。主题是库里已有的分类,比关键词准。一个问题通常一到两个主题就够。
- 主题覆盖不到的才用关键词。别把主题名再抄成关键词,那是重复检索。
- 用户问"最近"而没给范围时,时间窗取近 90 天,即 date_from={recent_from}。
  盘点类问题**把起点再往前放 30 天**——库里的日期常是成文日而非发布日,
  掐着月份边界查会漏掉重要文件。
- `issuer_sweeps` **盘点类问题默认给"财政部""税务总局"**,必要时加"市场监管总局"。
  这不是可选项:实测表明财税、认证这类跨条线文件**既没有能源主题、内部评分也偏低**,
  主题查不到、排序也沉底,只能按机关点名。评测里有整整一类重要政策
  (车船税、城镇土地使用税、CCC 认证)只有这一条通路能捞到。
  但解读单篇政策时不要给——那纯属浪费检索次数。
- 解读单篇政策(kind=single_policy)时,给关键词就够,不要给业务线和机关扫描。

用户的问题:{question}"""


def _themes_block(themes: list[ThemeInfo]) -> str:
    if not themes:
        return "(主题登记表读取失败,本次不要给 theme_ids)"
    return "\n".join(
        f"  - {t.id}({t.name},{t.count} 篇)" for t in themes
    )


def build_planner(model: Any) -> Agent[None, RetrievalPlan]:
    """规划器:无工具、结构化输出。model 传实例,与 build_agent 同理。"""
    return Agent(model, output_type=RetrievalPlan)


async def make_plan(
    planner: Agent[None, RetrievalPlan],
    *,
    question: str,
    themes: list[ThemeInfo],
    today: datetime.date | None = None,
    recent_days: int = 90,
) -> RetrievalPlan | None:
    """跑一次规划。**任何异常都吞掉并返回 None**——退回无计划的旧行为。

    规划是增强,不是必需路径。让它把整个回答带崩是本末倒置。
    """
    day = today or datetime.date.today()
    prompt = PLANNER_PROMPT.format(
        today=day.isoformat(),
        recent_from=(day - datetime.timedelta(days=recent_days)).isoformat(),
        themes=_themes_block(themes),
        question=question[:PLAN_MAX_CHARS],
    )
    try:
        result = await planner.run(prompt)
    except Exception as exc:  # noqa: BLE001 - 规划失败不该影响作答
        logger.warning("检索规划失败,退回无计划检索: %s", exc)
        return None
    plan = result.output
    return _sanitize(plan, themes)


def _sanitize(plan: RetrievalPlan, themes: list[ThemeInfo]) -> RetrievalPlan:
    """把模型可能编出来的东西掐掉。

    结构化输出保证了字段类型,保证不了取值合法——它完全可能给一个不存在的
    theme_id,下游拿去查就是空结果,而空结果看起来像"库里没有",比报错更糟。
    """
    known = {t.id for t in themes}
    valid_lines = {"加油", "充电", "电力", "乡村"}
    return plan.model_copy(
        update={
            "theme_ids": [t for t in plan.theme_ids if t in known][:3],
            "business_lines": [b for b in plan.business_lines if b in valid_lines][:4],
            "keywords": [k.strip() for k in plan.keywords if k.strip()][:3],
            # 解读单篇时机关扫描没有意义,模型给了也丢掉
            "issuer_sweeps": (
                [s.strip() for s in plan.issuer_sweeps if s.strip()][:3]
                if plan.kind == "survey"
                else []
            ),
        }
    )


def plan_to_prompt(plan: RetrievalPlan | None) -> str:
    """把计划渲染成注入 system prompt 的一段话。

    注意是**指令**不是建议:模型看到自己刚定的计划会倾向于照做,
    这正是我们要的——把"撒网"换成"按计划取证"。
    """
    if plan is None:
        return ""
    lines = ["", "【本轮检索计划】(你自己刚刚定的,照它执行,不要另起炉灶)"]
    if plan.kind == "single_policy":
        lines.append("- 这是解读单篇政策:先定位到那一篇,再读原文,不要做盘点式扫描。")
    elif plan.kind == "survey":
        lines.append("- 这是盘点类问题:先把下面几路检索做完,再去读原文。")
    if plan.theme_ids:
        lines.append(f"- 按主题检索(search_policies 的 theme_id):{', '.join(plan.theme_ids)}")
    if plan.business_lines:
        lines.append(f"- 按业务线检索:{', '.join(plan.business_lines)}")
    if plan.keywords:
        lines.append(f"- 关键词:{', '.join(plan.keywords)}")
    if plan.date_from or plan.date_to:
        lines.append(f"- 时间窗:{plan.date_from or '不限'} ~ {plan.date_to or '不限'}")
    if plan.issuer_sweeps:
        lines.append(
            f"- 另按机关各扫一遍(兜住跨条线文件):{', '.join(plan.issuer_sweeps)}"
        )
    lines.append("- 计划之外的检索只在计划落空时才做,并说明为什么。")
    return "\n".join(lines)
