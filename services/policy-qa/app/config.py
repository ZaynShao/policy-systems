"""运行配置。全部来自 env，启动时校验，缺必填直接 fail-fast。

凭据只从 env 读，绝不落文件、绝不进日志（服务级纪律）。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

Backend = Literal["pg", "vault"]

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"


class ConfigError(RuntimeError):
    """配置缺失或非法。启动期抛出，不进入服务循环。"""


def _require(name: str) -> str:
    val = (os.getenv(name) or "").strip()
    if not val:
        raise ConfigError(f"缺少必填环境变量 {name}")
    return val


def _int_env(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"环境变量 {name} 必须是整数，实际为 {raw!r}") from exc


@dataclass(frozen=True)
class Config:
    backend: Backend
    database_url: str | None
    vault_dir: str | None
    api_key: str
    base_url: str
    model_name: str
    access_token: str
    trust_platform_auth: bool
    log_dir: str
    max_tool_rounds: int
    request_timeout_s: int

    @property
    def safe_summary(self) -> dict:
        """可安全写日志/健康检查的摘要——不含任何凭据。"""
        return {
            "backend": self.backend,
            "model": self.model_name,
            "base_url": self.base_url,
            "max_tool_rounds": self.max_tool_rounds,
            "auth": "平台登录态(上游 nginx)" if self.trust_platform_auth else "服务自带令牌",
        }


def load_config(env: dict | None = None) -> Config:
    """从环境读取配置。env 参数仅供测试注入。"""
    if env is not None:
        original = dict(os.environ)
        os.environ.clear()
        os.environ.update(env)
        try:
            return load_config()
        finally:
            os.environ.clear()
            os.environ.update(original)

    backend = (os.getenv("POLICY_QA_DATA_BACKEND") or "").strip()
    if backend not in ("pg", "vault"):
        raise ConfigError(
            f"POLICY_QA_DATA_BACKEND 必须是 pg 或 vault，实际为 {backend!r}"
        )

    database_url = None
    vault_dir = None
    if backend == "pg":
        database_url = _require("POLICY_QA_DATABASE_URL")
    else:
        vault_dir = _require("POLICY_QA_VAULT_DIR")
        if not os.path.isdir(vault_dir):
            raise ConfigError(f"POLICY_QA_VAULT_DIR 不是目录: {vault_dir}")

    # 模型名三级回退：服务专属 → 平台共享 → 内置默认
    model_name = (
        (os.getenv("POLICY_QA_MODEL") or "").strip()
        or (os.getenv("DEEPSEEK_MODEL") or "").strip()
        or DEFAULT_MODEL
    )
    base_url = (os.getenv("DEEPSEEK_BASE_URL") or "").strip() or DEFAULT_BASE_URL

    # 部署在平台 nginx 后面时,鉴权由 nginx 的 auth_request 做(平台登录态),
    # 服务自己不再要 bearer——这是平台既有惯例,heng/kb 等内部服务都如此。
    # 但必须**显式声明**:两者都不配就 fail-fast,免得哪天漏配 token 就裸奔。
    trust_platform_auth = (os.getenv("POLICY_QA_TRUST_PLATFORM_AUTH") or "").strip() in ("1", "true", "yes")
    access_token = (os.getenv("POLICY_QA_ACCESS_TOKEN") or "").strip()
    if not access_token and not trust_platform_auth:
        raise ConfigError(
            "缺少 POLICY_QA_ACCESS_TOKEN。若本服务部署在平台 nginx 之后、"
            "由平台登录态鉴权,请显式设 POLICY_QA_TRUST_PLATFORM_AUTH=1"
        )

    return Config(
        backend=backend,  # type: ignore[arg-type]
        database_url=database_url,
        vault_dir=vault_dir,
        api_key=_require("DEEPSEEK_API_KEY"),
        base_url=base_url,
        model_name=model_name,
        access_token=access_token,
        trust_platform_auth=trust_platform_auth,
        log_dir=(os.getenv("POLICY_QA_LOG_DIR") or "").strip() or "./qa_logs",
        max_tool_rounds=_int_env("POLICY_QA_MAX_TOOL_ROUNDS", 18),
        request_timeout_s=_int_env("POLICY_QA_REQUEST_TIMEOUT_S", 120),
    )
