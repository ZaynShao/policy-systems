"""滑动窗口限流。纯逻辑，时间由调用方注入，可确定性重测。

基础反爬用：语料共 1240 篇、19MB 量级，没有限流的话对方一个循环就能
把全文拖走。这里限制的是**节奏**，不是总量。
"""
from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    """limit 次 / window_seconds 秒。"""

    limit: int
    window_seconds: int


@dataclass(frozen=True)
class Decision:
    allowed: bool
    remaining: int
    retry_after: int  # 秒；allowed 时为 0


class SlidingWindow:
    """按 key 记录命中时刻的滑动窗口计数器。

    key 建议带上作用域（如 `<token>:rpm` / `<token>:fulltext`），
    不同作用域各记各的账。
    """

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str, cutoff: float) -> deque[float]:
        hits = self._hits[key]
        while hits and hits[0] <= cutoff:
            hits.popleft()
        return hits

    def check(self, key: str, rule: Rule, now: float) -> Decision:
        """判定并在放行时记账。**被拒的请求不计数** —— 否则疯狂重试
        会不断把窗口推后，等于自我延长封禁。"""
        hits = self._prune(key, now - rule.window_seconds)

        if len(hits) >= rule.limit:
            oldest = hits[0] if hits else now
            retry_after = max(1, math.ceil(oldest + rule.window_seconds - now))
            return Decision(allowed=False, remaining=0, retry_after=retry_after)

        hits.append(now)
        return Decision(allowed=True, remaining=rule.limit - len(hits), retry_after=0)

    def tracked(self, key: str) -> int:
        """当前为该 key 保留的记录条数（测内存边界用）。"""
        return len(self._hits.get(key, ()))
