"""FastAPI 装配。

启动顺序有意为之:先读配置(缺必填直接 fail-fast),再建 store(vault backend
在这里全量建索引,约两秒),最后建 agent。任何一步失败都不进入服务循环——
带着半截配置起来、等第一个请求才炸,排查成本高得多。
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from .agent import build_agent
from .planner import build_planner
from .api import router
from .chatlog import ChatLog
from .config import Config, load_config
from .strategy import load_profile

logger = logging.getLogger("policy-qa")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def configure_logging(level: str | None = None) -> None:
    """给 policy-qa 自己的 logger 配一个 handler,否则 info 全被丢掉。

    为什么需要:uvicorn 只给 uvicorn.* 那几个 logger 配 handler,root 上一个也没有。
    ``logging.getLogger("policy-qa")`` 于是既没有自己的 handler,也没有可继承的,
    只剩 Python 的 lastResort——**而 lastResort 是 WARNING 级的,info 一行都出不来**。

    后果不是"少看几行日志"。运维手册里那条

        docker logs platform-policy-qa | grep 已加载业务战略画像

    永远不会有输出,看起来像"画像没加载",实际只是这行日志没地方去。
    (失败一直是可见的——warning 会走 lastResort——所以这里补的是可观测性,
    不是正确性。真正判断画像在不在,看 ``/v1/health`` 的 business_context.available。)

    只配 policy-qa 这一支,**不动 root**:动 root 会把 httpx、pydantic_ai 的 INFO
    一并放出来,把真正有用的那几行淹掉。
    """
    lg = logging.getLogger("policy-qa")
    if lg.handlers:
        return          # 重复装配(测试里会建多个 app)不叠 handler,否则每行打 N 遍
    handler = logging.StreamHandler()        # stderr → docker logs
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s [policy-qa] %(message)s"))
    lg.addHandler(handler)
    lg.setLevel((level or os.environ.get("POLICY_QA_LOG_LEVEL") or "INFO").upper())
    lg.propagate = False        # 自己已经输出了,别再交给 root 出第二遍


def build_store(cfg: Config):
    if cfg.backend == "vault":
        from .store.vault import VaultStore

        return VaultStore(cfg.vault_dir or "")
    from .store.pg import PgStore

    return PgStore(cfg.database_url or "", maxconn=cfg.pg_maxconn)


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
    configure_logging()      # 必须在第一条 logger.info 之前
    cfg: Config = getattr(app.state, "config", None) or load_config()
    app.state.config = cfg
    app.state.store = getattr(app.state, "store", None) or build_store(cfg)
    preflight = getattr(app.state.store, "preflight", None)
    if preflight is not None:
        preflight()
    app.state.chatlog = getattr(app.state, "chatlog", None) or ChatLog(cfg.log_dir)
    # 业务战略画像:可选。加载失败只记 warning 并退回不做业务框定,不阻断启动——
    # 让一个可选的参照文件把问答服务拦在门外,代价远大于少一段业务口径。
    if getattr(app.state, "strategy", None) is None:
        app.state.strategy = load_profile(cfg.strategy_file)
    if getattr(app.state, "agent", None) is None:
        model = build_model(cfg)
        app.state.agent = build_agent(model)
        # 规划器与作答共用同一个模型实例:它只是换一套 prompt 和输出类型,
        # 没必要为它多配一个 provider。
        app.state.planner = build_planner(model) if cfg.enable_planner else None
    prof = app.state.strategy
    logger.info("policy-qa 就绪: %s | 业务战略画像: %s", cfg.safe_summary,
                prof.profile_id if prof else "未配置/未加载(问答照常,只是不做业务框定)")
    yield


def create_app(
    cfg: Config | None = None, *, store=None, agent=None, chatlog=None, strategy=None
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
    app.state.strategy = strategy
    app.include_router(router)

    @app.get("/", include_in_schema=False)
    async def index():
        page = STATIC_DIR / "index.html"
        if not page.is_file():
            return {"ok": True, "hint": "静态页缺失,接口仍可用"}
        return FileResponse(page)

    return app


app = create_app()
