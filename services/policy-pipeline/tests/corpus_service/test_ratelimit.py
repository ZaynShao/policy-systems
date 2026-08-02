"""限流核心测试。时间由外部注入，行为完全确定，不依赖 sleep。"""
from __future__ import annotations

from scripts.corpus_service.ratelimit import Rule, SlidingWindow

RPM = Rule(limit=3, window_seconds=60)
DAILY = Rule(limit=5, window_seconds=86400)


def test_requests_under_limit_are_allowed():
    w = SlidingWindow()
    for i in range(3):
        assert w.check("tok", RPM, now=1000.0 + i).allowed is True


def test_request_over_limit_is_rejected():
    w = SlidingWindow()
    for i in range(3):
        w.check("tok", RPM, now=1000.0 + i)
    assert w.check("tok", RPM, now=1003.0).allowed is False


def test_rejected_request_is_not_counted():
    """被拒的请求不该继续占用配额，否则疯狂重试会无限延长封禁。"""
    w = SlidingWindow()
    for i in range(3):
        w.check("tok", RPM, now=1000.0)
    for _ in range(50):
        w.check("tok", RPM, now=1001.0)
    # 首批 3 次在 t=1000 落窗，t=1060.1 时应已全部滑出
    assert w.check("tok", RPM, now=1060.1).allowed is True


def test_window_slides_and_frees_capacity():
    w = SlidingWindow()
    for i in range(3):
        w.check("tok", RPM, now=1000.0 + i)
    assert w.check("tok", RPM, now=1059.0).allowed is False
    assert w.check("tok", RPM, now=1060.5).allowed is True  # 第一次已滑出


def test_retry_after_points_at_oldest_hit_expiry():
    w = SlidingWindow()
    for i in range(3):
        w.check("tok", RPM, now=1000.0 + i)
    d = w.check("tok", RPM, now=1010.0)
    assert d.allowed is False
    assert d.retry_after == 50  # 最早那次 1000 在 1060 滑出


def test_retry_after_is_at_least_one_second():
    w = SlidingWindow()
    for i in range(3):
        w.check("tok", RPM, now=1000.0)
    assert w.check("tok", RPM, now=1059.9).retry_after >= 1


def test_remaining_is_reported():
    w = SlidingWindow()
    assert w.check("tok", RPM, now=1000.0).remaining == 2
    assert w.check("tok", RPM, now=1000.0).remaining == 1
    assert w.check("tok", RPM, now=1000.0).remaining == 0


def test_tokens_are_isolated_from_each_other():
    w = SlidingWindow()
    for i in range(3):
        w.check("a", RPM, now=1000.0)
    assert w.check("a", RPM, now=1000.0).allowed is False
    assert w.check("b", RPM, now=1000.0).allowed is True


def test_scopes_are_isolated_within_same_token():
    """整体 rpm 与全文取用配额是两条独立的账，互不消耗。"""
    w = SlidingWindow()
    for i in range(3):
        w.check("tok:rpm", RPM, now=1000.0)
    assert w.check("tok:rpm", RPM, now=1000.0).allowed is False
    assert w.check("tok:fulltext", DAILY, now=1000.0).allowed is True


def test_daily_scope_spans_a_day():
    w = SlidingWindow()
    for i in range(5):
        w.check("tok", DAILY, now=1000.0 + i)
    assert w.check("tok", DAILY, now=1000.0 + 86000).allowed is False
    assert w.check("tok", DAILY, now=1000.0 + 86401).allowed is True


def test_zero_limit_rejects_everything():
    assert SlidingWindow().check("tok", Rule(0, 60), now=1000.0).allowed is False


def test_old_entries_are_pruned_so_memory_stays_bounded():
    w = SlidingWindow()
    for i in range(1000):
        w.check("tok", RPM, now=1000.0 + i * 30)  # 每 30s 一次，窗口内最多 2 条
    assert w.tracked("tok") <= RPM.limit
