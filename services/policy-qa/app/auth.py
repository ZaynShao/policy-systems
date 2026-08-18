"""Bearer 鉴权。

MVP 是单枚静态令牌(env 注入),够用且没有额外依赖;后续换 portal SSO 时
只需要换这一层。**本服务是对内工具,任何时候都不该裸露公网**——鉴权不是
唯一防线,nginx 侧还要限制来源(PR-3)。
"""
from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, Request, status


def _extract(header: str | None) -> str | None:
    if not header:
        return None
    parts = header.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


def check_token(provided: str | None, expected: str) -> bool:
    """常数时间比较,避免按字节比较泄露令牌前缀。"""
    if not provided or not expected:
        return False
    return secrets.compare_digest(provided, expected)


async def require_token(request: Request, authorization: str | None = Header(default=None)) -> None:
    cfg = request.app.state.config
    if cfg.trust_platform_auth:
        # 鉴权已由上游 nginx 的 auth_request 完成(平台登录态)。本服务不对宿主机
        # 暴露端口,只在平台内网可达,与 heng/kb 等内部服务同一信任模型。
        return
    if not check_token(_extract(authorization), cfg.access_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="需要有效的 Bearer 令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )
