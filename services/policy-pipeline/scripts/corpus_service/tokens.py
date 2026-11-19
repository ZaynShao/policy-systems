"""对外令牌的独立签发与校验。不依赖平台账号体系。

注册表是一个 JSON 文件，只存令牌的 sha256，**明文不落盘**：
签发时打印一次，之后无法找回，丢了就重签。

  {"tokens": [{"name": "外团队A", "sha256": "...", "issued_at": "...",
               "expires_at": "2027-01-27", "rpm": 60,
               "full_text_per_day": 200, "revoked": false}]}
"""
from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_RPM = 60
DEFAULT_FULL_TEXT_PER_DAY = 200


def mint_token() -> str:
    """生成一个新的对外令牌明文。"""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_record(name: str, *, token: str, expires_at: str | None = None,
               rpm: int = DEFAULT_RPM,
               full_text_per_day: int = DEFAULT_FULL_TEXT_PER_DAY) -> dict[str, Any]:
    """构造注册表条目。只带哈希，不带明文。"""
    return {
        "name": name,
        "sha256": hash_token(token),
        "issued_at": datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat(),
        "expires_at": expires_at,
        "rpm": rpm,
        "full_text_per_day": full_text_per_day,
        "revoked": False,
    }


@dataclass(frozen=True)
class TokenRecord:
    name: str
    key: str  # 限流记账用的稳定标识（哈希前缀，非明文）
    rpm: int
    full_text_per_day: int


def _expired(expires_at: Any, now: float) -> bool:
    if not expires_at:
        return False
    try:
        deadline = datetime.datetime.fromisoformat(str(expires_at))
    except ValueError:
        return True  # 日期写坏了按过期处理，宁可拒绝
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=datetime.timezone.utc)
    return now > deadline.timestamp()


@dataclass(frozen=True)
class TokenRegistry:
    entries: tuple[dict[str, Any], ...]

    @classmethod
    def load(cls, path: Path) -> "TokenRegistry":
        """注册表不存在时返回空表 —— 空表拒绝一切令牌。"""
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls(entries=())
        tokens = raw.get("tokens") if isinstance(raw, dict) else None
        return cls(entries=tuple(t for t in (tokens or []) if isinstance(t, dict)))

    @property
    def is_empty(self) -> bool:
        return not self.entries

    def authenticate(self, presented: str, now: float) -> TokenRecord | None:
        """校验令牌。未知 / 过期 / 已撤销 → None。

        逐条比对且不提前退出，避免命中位置产生时序差异。
        """
        if not presented:
            return None
        digest = hash_token(presented)
        found: dict[str, Any] | None = None
        for entry in self.entries:
            if hmac.compare_digest(digest, str(entry.get("sha256", ""))):
                found = entry
        if found is None or found.get("revoked") or _expired(found.get("expires_at"), now):
            return None
        return TokenRecord(
            name=str(found.get("name") or "unnamed"),
            key=digest[:16],
            rpm=int(found.get("rpm") or DEFAULT_RPM),
            full_text_per_day=int(found.get("full_text_per_day") or DEFAULT_FULL_TEXT_PER_DAY),
        )
