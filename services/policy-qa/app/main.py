"""FastAPI 装配。

启动顺序有意为之:先读配置(缺必填直接 fail-fast),再建 store(vault backend
在这里全量建索引,约两秒),最后建 agent。任何一步失败都不进入服务循环——
带着半截配置起来、等第一个请求才炸,排查成本高得多。
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from .agent import build_agent
from .api import router
from .chatlog import ChatLog
from .config import Config, load_config

logger = logging.getLogger("policy-qa")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def build_store(cfg: Config):
    if cfg.backend == "vault":
        from .store.vault import VaultStore

        return VaultStore(cfg.vault_dir or "")
    from .store.pg import PgStore

    return PgStore(cfg.database_url or "")


def build_model(cfg: Config):
    """DeepSeek 走 OpenAI 兼容接口。凭据只从配置来,不落任何文件。"""
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    return OpenAIChatModel(
        cfg.model_name,
        provider=OpenAIProvider(base_url=cfg.base_url, api_key=cfg.api_key),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg: Config = getattr(app.state, "config", None) or load_config()
    app.state.config = cfg
    app.state.store = getattr(app.state, "store", None) or build_store(cfg)
    app.state.chatlog = getattr(app.state, "chatlog", None) or ChatLog(cfg.log_dir)
    if getattr(app.state, "agent", None) is None:
        app.state.agent = build_agent(build_model(cfg))
    logger.info("policy-qa 就绪: %s", cfg.safe_summary)
    yield


def create_app(
    cfg: Config | None = None, *, store=None, agent=None, chatlog=None
) -> FastAPI:
    """参数只供测试注入;生产走 lifespan 里的正常构建路径。"""
    app = FastAPI(
        title="policy-qa",
        description="滴滴能源政策问答助手(对内)",
        lifespan=lifespan,
    )
    if cfg is not None:
        app.state.config = cfg
    app.state.store = store
    app.state.agent = agent
    app.state.chatlog = chatlog
    app.include_router(router)

    @app.get("/", include_in_schema=False)
    async def index():
        page = STATIC_DIR / "index.html"
        if not page.is_file():
            return {"ok": True, "hint": "静态页缺失,接口仍可用"}
        return FileResponse(page)

    return app


app = create_app()
