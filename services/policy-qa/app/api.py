"""HTTP 接口。

SSE 帧手写(不引 sse-starlette):事件名要与契约逐字一致,手写反而更可控,
也少一个依赖。契约见 README 的「接口」段。
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .agent import stream_answer
from .auth import require_token
from .store import StoreError

logger = logging.getLogger("policy-qa")

router = APIRouter()


class ChatMessage(BaseModel):
    role: str
    content: str = ""


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(default_factory=list)


def _frame(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


@router.get("/healthz")
async def healthz() -> dict:
    """存活探针。不带任何数据,故不鉴权。"""
    return {"ok": True}


@router.get("/v1/health", dependencies=[Depends(require_token)])
async def health(request: Request) -> dict:
    try:
        stats = request.app.state.store.stats()
    except StoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, **request.app.state.config.safe_summary, **stats}


@router.post("/v1/chat", dependencies=[Depends(require_token)])
async def chat(request: Request, body: ChatRequest) -> StreamingResponse:
    if not body.messages:
        raise HTTPException(status_code=400, detail="messages 不能为空")
    for msg in body.messages:
        if msg.role == "system":
            # system prompt 由服务端注入,客户端不得覆盖——否则答题纪律形同虚设
            raise HTTPException(status_code=400, detail="不接受客户端提供的 system 消息")
        if msg.role not in ("user", "assistant"):
            raise HTTPException(status_code=400, detail=f"未知 role: {msg.role}")
    if body.messages[-1].role != "user":
        raise HTTPException(status_code=400, detail="messages 最后一条必须是 user")
    if not body.messages[-1].content.strip():
        raise HTTPException(status_code=400, detail="最后一条 user 消息内容为空")

    app = request.app
    request_id = uuid.uuid4().hex[:16]
    messages = [m.model_dump() for m in body.messages]

    async def generate() -> AsyncIterator[str]:
        record: dict[str, Any] = {
            "request_id": request_id,
            "backend": app.state.config.backend,
            "messages_in_chars": sum(len(m["content"]) for m in messages),
            "question": messages[-1]["content"][:500],
            "tool_calls": [],
        }
        answer_chars = 0
        try:
            async for name, data in stream_answer(
                app.state.agent,
                store=app.state.store,
                messages=messages,
                cfg=app.state.config,
                planner=getattr(app.state, "planner", None),
            ):
                if name == "meta":
                    data = {"request_id": request_id, **data}
                elif name == "delta":
                    answer_chars += len(data.get("text", ""))
                elif name == "tool" and data.get("status") == "start":
                    record["tool_calls"].append(
                        {
                            "name": data.get("name"),
                            # 记完整入参,不是 UI 那个 60 字摘要——排查要靠它
                            "args": data.get("args_full") or data.get("args_preview"),
                        }
                    )
                elif name == "plan":
                    # 计划也落日志:线上答得不对时,第一个要看的就是"它当时打算怎么查"
                    record["plan"] = data
                elif name == "done":
                    record["citations"] = [c["pid"] for c in data.get("citations", [])]
                    record["usage"] = data.get("usage")
                yield _frame(name, data)
        except Exception as exc:  # noqa: BLE001 - 流已开始,只能以事件形式报错
            record["error"] = f"{type(exc).__name__}: {exc}"
            # 用户只看到脱敏文本,排查得有地方看真因。只写会话 jsonl 的话,
            # 运维第一反应是 docker logs,那里却什么都没有。
            logger.warning(
                "对话失败 request_id=%s: %s", request_id, record["error"], exc_info=exc
            )
            yield _frame("error", {"message": _safe_error(exc)})
        finally:
            record["answer_chars"] = answer_chars
            app.state.chatlog.write(record)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # nginx 不要缓冲,否则前端看不到增量
            "Connection": "keep-alive",
        },
    )


def _safe_error(exc: Exception) -> str:
    """给用户看的错误文本。不回显异常细节——里面可能带连接串或提示词片段。"""
    if isinstance(exc, StoreError):
        return "政策库暂时不可用,请稍后再试。"
    name = type(exc).__name__
    if "UsageLimit" in name:
        return "本轮检索次数已达上限,请把问题拆细一些再问。"
    return "回答生成失败,请重试;若持续失败请联系维护者。"
