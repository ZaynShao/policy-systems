"""Agent 与工具。用 FunctionModel 驱动,零真网。"""
from __future__ import annotations

import datetime
import json

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from app.agent import build_agent, stream_answer, to_model_messages
from app.config import Config

TODAY = datetime.date(2026, 8, 17)


def _cfg(**kw) -> Config:
    base = dict(
        backend="vault",
        database_url=None,
        vault_dir="/tmp",
        api_key="k",
        base_url="https://example.invalid/v1",
        model_name="deepseek-chat",
        access_token="t",
        trust_platform_auth=False,
        log_dir="/tmp",
        max_tool_rounds=8,
        request_timeout_s=120,
        pg_maxconn=8,
    )
    base.update(kw)
    return Config(**base)


def _model(fn):
    """把 (messages, info) -> ModelResponse 的函数包成支持流式的 FunctionModel。

    本服务全程走流式(SSE),FunctionModel 不给 stream_function 会直接断言失败,
    所以测试必须提供流式版本,否则测的不是真实调用路径。
    """

    async def stream_fn(messages: list[ModelMessage], info: AgentInfo):
        resp = fn(messages, info)
        for part in resp.parts:
            if isinstance(part, ToolCallPart):
                args = part.args
                yield {
                    0: DeltaToolCall(
                        name=part.tool_name,
                        json_args=args if isinstance(args, str) else json.dumps(args),
                    )
                }
            elif isinstance(part, TextPart):
                yield part.content

    return FunctionModel(fn, stream_function=stream_fn)


def _scripted(*steps):
    """按脚本依次返回:每步是 (tool_name, args) 或最终文本。"""
    calls = {"n": 0}

    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        idx = calls["n"]
        calls["n"] += 1
        step = steps[idx] if idx < len(steps) else "结束。"
        if isinstance(step, tuple):
            name, args = step
            return ModelResponse(parts=[ToolCallPart(tool_name=name, args=args)])
        return ModelResponse(parts=[TextPart(content=step)])

    return _model(fn)


async def _collect(agent, store, messages, cfg=None):
    events = []
    async for name, data in stream_answer(
        agent, store=store, messages=messages, cfg=cfg or _cfg(), today=TODAY
    ):
        events.append((name, data))
    return events


@pytest.mark.asyncio
async def test_tools_are_registered(vault_store):
    """四个工具都要注册上,少一个模型就用不了。"""
    seen = {}

    def fn(messages, info: AgentInfo):
        seen["tools"] = {t.name for t in info.function_tools}
        return ModelResponse(parts=[TextPart(content="ok")])

    agent = build_agent(_model(fn))
    await _collect(agent, vault_store, [{"role": "user", "content": "hi"}])
    assert seen["tools"] == {
        "search_policies",
        "get_policy_fulltext",
        "get_policy_relations",
        "get_policy_commentary",
    }


@pytest.mark.asyncio
async def test_search_then_fulltext_flow(vault_store):
    agent = build_agent(
        _scripted(
            ("search_policies", {"business_line": "充电"}),
            ("get_policy_fulltext", {"pid": "P_2026_TEST_1"}),
            "《关于加快充电基础设施建设的通知》要求2026年底前建成充电桩10万个。",
        )
    )
    events = await _collect(agent, vault_store, [{"role": "user", "content": "充电有什么新政策"}])
    names = [n for n, _ in events]
    assert names[0] == "meta" and names[-1] == "done"

    tools = [d for n, d in events if n == "tool"]
    assert [t["name"] for t in tools if t["status"] == "start"] == [
        "search_policies",
        "get_policy_fulltext",
    ]
    assert all(t["result_chars"] > 0 for t in tools if t["status"] == "done")

    text = "".join(d["text"] for n, d in events if n == "delta")
    assert "充电桩10万个" in text


@pytest.mark.asyncio
async def test_citations_only_from_fulltext(vault_store):
    """引用只登记真正读过原文的政策——检索列表不算读过。"""
    agent = build_agent(
        _scripted(("search_policies", {"keyword": "充电"}), "只检索没读原文。")
    )
    events = await _collect(agent, vault_store, [{"role": "user", "content": "q"}])
    done = [d for n, d in events if n == "done"][0]
    assert done["citations"] == []

    agent2 = build_agent(
        _scripted(("get_policy_fulltext", {"pid": "P_2026_TEST_1"}), "读过了。")
    )
    events2 = await _collect(agent2, vault_store, [{"role": "user", "content": "q"}])
    done2 = [d for n, d in events2 if n == "done"][0]
    assert [c["pid"] for c in done2["citations"]] == ["P_2026_TEST_1"]
    assert done2["citations"][0]["title"] == "关于加快充电基础设施建设的通知"


@pytest.mark.asyncio
async def test_caveat_reaches_citation(vault_store):
    """撞车 pid 的缺陷说明必须一路传到引用里,不能在中途丢。"""
    from conftest import COLLISION_PID

    agent = build_agent(
        _scripted(("get_policy_fulltext", {"pid": COLLISION_PID}), "读过了。")
    )
    events = await _collect(agent, vault_store, [{"role": "user", "content": "q"}])
    done = [d for n, d in events if n == "done"][0]
    assert done["citations"][0]["caveat"] is not None


@pytest.mark.asyncio
async def test_missing_pid_tells_model_not_to_invent(vault_store):
    captured = {}

    def fn(messages, info):
        for m in messages:
            for p in getattr(m, "parts", []):
                if getattr(p, "part_kind", "") == "tool-return":
                    captured["content"] = str(p.content)
        if "content" not in captured:
            return ModelResponse(parts=[ToolCallPart(tool_name="get_policy_fulltext", args={"pid": "P_NOPE"})])
        return ModelResponse(parts=[TextPart(content="库里没有这件。")])

    agent = build_agent(_model(fn))
    await _collect(agent, vault_store, [{"role": "user", "content": "q"}])
    payload = json.loads(captured["content"])
    assert payload["found"] is False
    assert "不要编造" in payload["hint"]


@pytest.mark.asyncio
async def test_tool_budget_degrades_gracefully(vault_store):
    """预算用尽时**不抛错**:工具改回提示语,让模型拿现有材料收尾。

    抛错等于用户什么都拿不到,而此时模型手里通常已有足够材料——真实冒烟里
    "最近对充电影响大的政策"就是 2 次检索 + 并行读 4 篇后撞上限的。
    """
    from app.agent import BUDGET_EXHAUSTED

    turns = {"n": 0}
    returns: list[str] = []

    def fn(messages, info):
        turns["n"] += 1
        # 每轮只看最后一条消息里的工具返回,避免重复累计
        if messages:
            for p in getattr(messages[-1], "parts", []):
                if getattr(p, "part_kind", "") == "tool-return":
                    returns.append(str(p.content))
        if turns["n"] <= 4:  # 预算 3,故第 4 次必然超支
            return ModelResponse(
                parts=[ToolCallPart(tool_name="search_policies", args={"keyword": "充电"})]
            )
        return ModelResponse(parts=[TextPart(content="检索轮次已达上限,以下基于已检索到的部分:……")])

    agent = build_agent(_model(fn))
    events = await _collect(
        agent, vault_store, [{"role": "user", "content": "q"}], cfg=_cfg(max_tool_rounds=3)
    )
    names = [n for n, _ in events]
    assert "error" not in names, "预算用尽不该变成错误"
    assert names[-1] == "done"
    assert sum(1 for s in returns if BUDGET_EXHAUSTED in s) == 1, "第 4 次应回提示语"
    assert sum(1 for s in returns if BUDGET_EXHAUSTED not in s) == 3, "只有前 3 次真干活"
    text = "".join(d["text"] for n, d in events if n == "delta")
    assert "上限" in text


@pytest.mark.asyncio
async def test_store_failure_degrades_instead_of_killing_the_run(vault_store):
    """单个检索失败**不抛错**:那一条认领错误,其余材料照样能拿来作答。

    真机第一次接 heng-pg 就撞上了:模型一轮并行发七个检索,连接池只有四条,
    多出来的当场 PoolError;pydantic-ai 的并行执行里一个工具抛异常会连带取消
    同批其余调用,于是七条全废、整轮回答归零,用户只看到"政策库暂时不可用"。
    """
    from app.agent import STORE_UNAVAILABLE
    from app.store import StoreError

    class _FlakyStore:
        """第一次检索失败,第二次成功——模拟并发打满时只有部分调用中招。"""

        def __init__(self, inner):
            self._inner = inner
            self.attempts = 0

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def search_policies(self, **kw):
            self.attempts += 1
            if self.attempts == 1:
                raise StoreError("查询失败: PoolError")
            return self._inner.search_policies(**kw)

    returns: list[str] = []

    def fn(messages, info):
        if messages:
            for p in getattr(messages[-1], "parts", []):
                if getattr(p, "part_kind", "") == "tool-return":
                    returns.append(str(p.content))
        if len(returns) < 2:
            return ModelResponse(
                parts=[ToolCallPart(tool_name="search_policies", args={"business_line": "充电"})]
            )
        return ModelResponse(parts=[TextPart(content="部分检索未成功,以下基于已取得的材料:……")])

    store = _FlakyStore(vault_store)
    agent = build_agent(_model(fn))
    events = await _collect(agent, store, [{"role": "user", "content": "充电有什么新政策"}])

    names = [n for n, _ in events]
    assert "error" not in names, "单次检索失败不该让整轮回答归零"
    assert names[-1] == "done"
    assert sum(1 for s in returns if STORE_UNAVAILABLE in s) == 1, "失败那次应回提示语"
    assert sum(1 for s in returns if STORE_UNAVAILABLE not in s) == 1, "成功那次应回真结果"
    text = "".join(d["text"] for n, d in events if n == "delta")
    assert "已取得的材料" in text


@pytest.mark.asyncio
async def test_intermediate_planning_text_is_not_streamed(vault_store):
    """模型在还要接着调工具的轮次里输出的文本是**规划自语**,不能给用户看。

    实测真模型会写"我将用盘点式方法检索…先做几轮并行检索…现在深挖几篇原文",
    直接转发既难看又误导。只有 FinalResultEvent 之后的文本才是最终答复。
    """
    turns = {"n": 0}

    def fn(messages, info):
        turns["n"] += 1
        if turns["n"] == 1:
            # 同一轮里既说话又调工具 —— 这段话是给它自己看的
            return ModelResponse(
                parts=[
                    TextPart(content="我先做几轮并行检索,再深挖原文。"),
                    ToolCallPart(tool_name="search_policies", args={"keyword": "充电"}),
                ]
            )
        return ModelResponse(parts=[TextPart(content="结论:该通知要求建成充电桩10万个。")])

    agent = build_agent(_model(fn))
    events = await _collect(agent, vault_store, [{"role": "user", "content": "q"}])
    names = [n for n, _ in events]
    assert "delta_reset" in names, "发现本轮有工具调用后必须让前端丢弃已显示文本"

    # 模拟前端:收到 delta_reset 就清空当前累积
    shown = ""
    for n, d in events:
        if n == "delta":
            shown += d["text"]
        elif n == "delta_reset":
            shown = ""
    assert "我先做几轮并行检索" not in shown, "中间轮次的规划自语不得留在答复里"
    assert "充电桩10万个" in shown, "最终答复必须完整送达"


@pytest.mark.asyncio
async def test_search_limit_capped(vault_store):
    """模型要 999 条也只能拿到 50 条。"""
    captured = {}

    def fn(messages, info):
        for m in messages:
            for p in getattr(m, "parts", []):
                if getattr(p, "part_kind", "") == "tool-return":
                    captured["content"] = str(p.content)
        if "content" not in captured:
            return ModelResponse(
                parts=[ToolCallPart(tool_name="search_policies", args={"limit": 999})]
            )
        return ModelResponse(parts=[TextPart(content="done")])

    agent = build_agent(_model(fn))
    await _collect(agent, vault_store, [{"role": "user", "content": "q"}])
    payload = json.loads(captured["content"])
    assert payload["returned"] <= 50


# --- 消息历史 ---------------------------------------------------------------


def test_history_conversion():
    history, prompt, truncated = to_model_messages(
        [
            {"role": "user", "content": "第一问"},
            {"role": "assistant", "content": "第一答"},
            {"role": "user", "content": "第二问"},
        ]
    )
    assert prompt == "第二问"
    assert len(history) == 2 and truncated is False


def test_history_requires_trailing_user():
    with pytest.raises(ValueError):
        to_model_messages([{"role": "assistant", "content": "x"}])
    with pytest.raises(ValueError):
        to_model_messages([])
    with pytest.raises(ValueError):
        to_model_messages([{"role": "user", "content": "   "}])


def test_history_truncates_oldest_first():
    big = "x" * 30000
    msgs = [
        {"role": "user", "content": big},
        {"role": "assistant", "content": big},
        {"role": "user", "content": big},
        {"role": "user", "content": "最后一问"},
    ]
    history, prompt, truncated = to_model_messages(msgs)
    assert truncated is True
    assert prompt == "最后一问"
    assert len(history) < 3
