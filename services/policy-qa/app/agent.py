"""Agent:4 个检索工具 + 一条 tool-calling loop。

流式驱动也在这里(而不是 api.py),这样不起 HTTP 就能测完整对话流程。
api.py 只把这里 yield 的事件翻成 SSE 帧。
"""
from __future__ import annotations

import datetime
import json
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Iterable

from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    PartDeltaEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.usage import UsageLimits

from .config import Config
from .prompts import build_system_prompt
from .store import DEFAULT_LIMIT, MAX_LIMIT, PolicyCard, PolicyStore, StoreError

logger = logging.getLogger("policy-qa")

#: 列表类工具结果的字符上限(检索/关系/评论)。
TOOL_RESULT_MAX_CHARS = 12000
#: 读原文的字符上限。必须比列表类宽:读原文是**唯一**能支撑事实性陈述的来源,
#: 截太狠会让模型拿着半截正文去回答。外层封装占几百字符,故留出余量。
FULLTEXT_RESULT_MAX_CHARS = 26000
#: get_policy_fulltext 单次取的正文长度(模型可用 offset 续读)
FULLTEXT_MAX_CHARS = 20000
#: 全部输入消息的字符上限,超了从最老的一轮开始丢
HISTORY_MAX_CHARS = 60000
#: 会话日志里记的完整工具入参上限。UI 摘要只有 60 字,排查不够用。
ARGS_FULL_MAX_CHARS = 500

#: 达到检索上限后,工具不再干活,改回这句。**不抛错**——抛错会让用户什么都拿不到,
#: 而此时模型手里通常已经有足够材料。让它自己收尾,比中断体验好得多。
BUDGET_EXHAUSTED = (
    "已达本轮检索次数上限,不能再检索了。请立即基于你已经读到的材料作答,"
    "并在开头说明「检索轮次已达上限,以下基于已检索到的部分」;"
    "不要再调用任何工具,也不要因为材料不全就编造内容。"
)

#: 单次检索失败时回给模型的话。同样**不抛错**,理由比预算那条更硬:
#: pydantic-ai 并行执行同一轮的工具调用,任何一个抛异常都会连带取消同批其余调用
#: (实测:七个并行检索里一个失败,另外五个被取消,整轮回答归零)。
#: 让失败的那个自己认领错误,模型就能带着其余结果继续作答。
STORE_UNAVAILABLE = (
    "本次检索失败(政策库暂时不可用),这一条没有结果。不要重复同一个检索。"
    "请基于其余已成功取得的材料继续作答,并在开头说明「部分检索未成功,"
    "以下基于已取得的材料」;材料不足时如实说明,不要编造。"
)


@dataclass
class RunState:
    """一次问答的运行态。工具通过它拿 store,并把引用登记回来。"""

    store: PolicyStore
    cited: dict[str, PolicyCard] = field(default_factory=dict)
    max_tool_calls: int = 18
    tool_calls: int = 0

    def spend(self) -> bool:
        """记一次工具调用。返回 False 表示预算已尽,调用方应回 BUDGET_EXHAUSTED。"""
        self.tool_calls += 1
        return self.tool_calls <= self.max_tool_calls


def _truncate(text: str, limit: int = TOOL_RESULT_MAX_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n[结果过长已截断]"


def _dump(payload: Any, limit: int = TOOL_RESULT_MAX_CHARS) -> str:
    return _truncate(json.dumps(payload, ensure_ascii=False, default=str), limit)


def build_agent(model: Any) -> Agent[RunState, str]:
    """model 传实例:生产是 OpenAIChatModel(DeepSeek),测试是 FunctionModel/TestModel。"""
    agent: Agent[RunState, str] = Agent(
        model,
        deps_type=RunState,
        output_type=str,
    )

    @agent.tool
    def search_policies(
        ctx: RunContext[RunState],
        keyword: str | None = None,
        business_line: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        region_keyword: str | None = None,
        min_importance: str | None = None,
        issuer_keyword: str | None = None,
        order: str = "date_desc",
        limit: int = DEFAULT_LIMIT,
    ) -> str:
        """检索政策库,返回元数据列表(不含正文)。

        keyword 同时匹配标题与文号,多个词空格分隔且必须全部命中。
        business_line 取 加油/充电/电力/乡村,用于回答"对某业务影响大的政策";
        它按内部影响分析筛选,已排除"未直接涉及"的条目。
        date_from/date_to 是 YYYY-MM-DD。region_keyword 匹配区域名、行政区划码或层级
        (国家/省/市/区)。min_importance 取 INFO/GENERAL/MAJOR/STRATEGIC。
        order 取 date_desc(默认)或 importance_desc。limit 最大 50。
        返回里的 total 是满足条件的总数,可能大于本次返回条数。
        """
        if not ctx.deps.spend():
            return BUDGET_EXHAUSTED
        try:
            res = ctx.deps.store.search_policies(
                keyword=keyword,
                business_line=business_line,
                date_from=date_from,
                date_to=date_to,
                region_keyword=region_keyword,
                min_importance=min_importance,
                issuer_keyword=issuer_keyword,
                order=order,
                limit=min(int(limit or DEFAULT_LIMIT), MAX_LIMIT),
            )
        except StoreError as exc:
            logger.warning("search_policies 失败,已降级: %s", exc)
            return STORE_UNAVAILABLE
        return _dump(
            {
                "total": res.total,
                "returned": len(res.rows),
                "rows": [r.model_dump(exclude_none=True) for r in res.rows],
            }
        )

    @agent.tool
    def get_policy_fulltext(
        ctx: RunContext[RunState], pid: str, offset: int = 0
    ) -> str:
        """按 pid 取政策原文全文与内部评估。

        凡要引用数字、文号、日期或原文表述,必须先调用本工具读到原文;检索列表里的
        元数据不足以支撑事实性陈述。正文超长时本工具只返回一段,
        content_total_chars 大于 content_offset+已返回长度时,可用 offset 续读。
        """
        if not ctx.deps.spend():
            return BUDGET_EXHAUSTED
        try:
            detail = ctx.deps.store.get_policy(pid, max_chars=FULLTEXT_MAX_CHARS, offset=offset)
        except StoreError as exc:
            logger.warning("get_policy_fulltext 失败,已降级: %s", exc)
            return STORE_UNAVAILABLE
        if detail is None:
            return _dump({"found": False, "pid": pid, "hint": "库内无此 pid,不要编造该件内容"})
        ctx.deps.cited[detail.pid] = detail
        return _dump({"found": True, **detail.model_dump(exclude_none=True)}, FULLTEXT_RESULT_MAX_CHARS)

    @agent.tool
    def get_policy_relations(ctx: RunContext[RunState], pid: str) -> str:
        """取该政策的上下游关系(废止/迭代/扩展/细化/引用/依据/对齐/冲突/落地),带证据句。

        direction=outbound 是本件指向别人,inbound 是别人指向本件。
        """
        if not ctx.deps.spend():
            return BUDGET_EXHAUSTED
        try:
            edges = ctx.deps.store.get_relations(pid)
        except StoreError as exc:
            logger.warning("get_policy_relations 失败,已降级: %s", exc)
            return STORE_UNAVAILABLE
        return _dump(
            {"pid": pid, "count": len(edges), "edges": [e.model_dump(exclude_none=True) for e in edges]}
        )

    @agent.tool
    def get_policy_commentary(ctx: RunContext[RunState], pid: str) -> str:
        """取行业评论对该政策的解读信号(风险/机会/执行/关注等)。

        这是内部校准信号,不是权威事实:引用时要说明这是行业评论的看法,不能当政策原文用。
        """
        if not ctx.deps.spend():
            return BUDGET_EXHAUSTED
        try:
            items = ctx.deps.store.get_commentary(pid)
        except StoreError as exc:
            logger.warning("get_policy_commentary 失败,已降级: %s", exc)
            return STORE_UNAVAILABLE
        return _dump(
            {"pid": pid, "count": len(items), "items": [i.model_dump(exclude_none=True) for i in items]}
        )

    return agent


# --- 消息历史 ---------------------------------------------------------------


def to_model_messages(messages: Iterable[dict]) -> tuple[list[ModelMessage], str, bool]:
    """客户端消息 → (历史, 本轮提问, 是否截断过)。

    会话不落服务端,历史每次由客户端全量带上,所以这里要自己防上下文膨胀:
    超限时从最老的一轮开始丢(system 由服务端注入,不在这个列表里)。
    """
    items = [m for m in messages if m.get("role") in ("user", "assistant")]
    if not items or items[-1].get("role") != "user":
        raise ValueError("messages 最后一条必须是 user")

    prompt = str(items[-1].get("content") or "").strip()
    if not prompt:
        raise ValueError("最后一条 user 消息内容为空")

    history = items[:-1]
    truncated = False
    while history and sum(len(str(m.get("content") or "")) for m in history) + len(prompt) > HISTORY_MAX_CHARS:
        history = history[1:]
        truncated = True

    out: list[ModelMessage] = []
    for m in history:
        content = str(m.get("content") or "")
        if m["role"] == "user":
            out.append(ModelRequest(parts=[UserPromptPart(content=content)]))
        else:
            out.append(ModelResponse(parts=[TextPart(content=content)]))
    return out, prompt, truncated


def _args_preview(args: Any) -> str:
    """工具入参 → 给人看的一行摘要(UI 直接显示),不是完整 JSON。"""
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            return args[:60]
    if not isinstance(args, dict):
        return str(args)[:60]
    parts = [f"{k}={v}" for k, v in args.items() if v not in (None, "", 0)]
    return ", ".join(parts)[:60] or "(无参数)"


def _args_full(args: Any) -> str:
    """完整入参,给会话日志用。

    UI 那个 60 字的摘要够看,但排查不够用:2026-08-18 排查线上故障时,
    恰恰是被截掉的 `region_keyword` 才是触发失败的那个参数,
    日志里看不见它,平白多绕了好几圈。
    """
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            return args[:ARGS_FULL_MAX_CHARS]
    return _truncate(
        json.dumps(args, ensure_ascii=False, default=str), ARGS_FULL_MAX_CHARS
    )


# --- 流式驱动 ---------------------------------------------------------------


async def stream_answer(
    agent: Agent[RunState, str],
    *,
    store: PolicyStore,
    messages: list[dict],
    cfg: Config,
    today: datetime.date | None = None,
) -> AsyncIterator[tuple[str, dict]]:
    """跑一轮问答,yield (事件名, 数据)。事件名与 SSE 契约一致。"""
    history, prompt, truncated = to_model_messages(messages)
    state = RunState(store=store, max_tool_calls=cfg.max_tool_rounds)
    seq = 0
    pending: dict[str, int] = {}

    yield "meta", {"history_truncated": truncated}

    # 正常的上限由 RunState 预算温和处理(工具改回提示语,让模型收尾);
    # 这里只留一个远高于预算的兜底,防模型无视提示无限调用。
    limits = UsageLimits(tool_calls_limit=max(24, cfg.max_tool_rounds * 3))
    async with agent.iter(
        prompt,
        deps=state,
        message_history=history,
        usage_limits=limits,
        instructions=build_system_prompt(today),
    ) as run:
        async for node in run:
            if Agent.is_model_request_node(node):
                # 模型在**还要接着调工具**的轮次里也会输出文本,那是给它自己看的规划
                # 自语("我先做几轮并行检索…现在深挖几篇原文"),不该当成答复给用户。
                #
                # 麻烦在于流式下当场分不出来:output_type 是 str,任何文本都"匹配输出
                # 模式",FinalResultEvent 在规划文本上照样触发。但**一旦这一轮里冒出
                # 工具调用**,就能确定刚才那段是规划。
                #
                # 所以:文本照常实时发(保住流式体验),发现本轮有工具调用时补发一个
                # delta_reset,让前端把本轮已显示的文本丢掉,并静默本轮后续文本。
                emitted_this_turn = False
                suppress_rest = False

                async with node.stream(run.ctx) as stream:
                    async for event in stream:
                        if isinstance(event, PartStartEvent) and isinstance(
                            event.part, ToolCallPart
                        ):
                            if emitted_this_turn and not suppress_rest:
                                yield "delta_reset", {}
                            suppress_rest = True
                            continue
                        if suppress_rest:
                            continue
                        chunk = ""
                        # 首块文本走 PartStartEvent,后续才是 PartDeltaEvent。
                        # 只接 delta 会把每次回答的开头吞掉。
                        if isinstance(event, PartStartEvent) and isinstance(event.part, TextPart):
                            chunk = event.part.content or ""
                        elif isinstance(event, PartDeltaEvent) and isinstance(
                            event.delta, TextPartDelta
                        ):
                            chunk = event.delta.content_delta or ""
                        if chunk:
                            emitted_this_turn = True
                            yield "delta", {"text": chunk}
            elif Agent.is_call_tools_node(node):
                async with node.stream(run.ctx) as stream:
                    async for event in stream:
                        if isinstance(event, FunctionToolCallEvent):
                            seq += 1
                            pending[event.part.tool_call_id] = seq
                            yield "tool", {
                                "seq": seq,
                                "name": event.part.tool_name,
                                "args_preview": _args_preview(event.part.args),
                                # 完整入参只进会话日志,UI 用上面那个摘要
                                "args_full": _args_full(event.part.args),
                                "status": "start",
                            }
                        elif isinstance(event, FunctionToolResultEvent):
                            # 工具返回值在 part.content 上;event.content 是另一回事
                            # (跟在结果后面发给模型的补充内容),别拿错。
                            part = event.part
                            call_id = getattr(part, "tool_call_id", None)
                            yield "tool", {
                                "seq": pending.get(call_id, seq),
                                "name": getattr(part, "tool_name", "") or "",
                                "status": "done",
                                "result_chars": len(str(getattr(part, "content", "") or "")),
                            }

    usage = run.usage
    yield "done", {
        "citations": [
            {
                "pid": c.pid,
                "title": c.title,
                "doc_number": c.doc_number,
                "source_url": c.source_url,
                "caveat": c.caveat,
            }
            for c in state.cited.values()
        ],
        "usage": {
            "prompt_tokens": getattr(usage, "input_tokens", 0) or 0,
            "completion_tokens": getattr(usage, "output_tokens", 0) or 0,
            "tool_calls": seq,
        },
    }
