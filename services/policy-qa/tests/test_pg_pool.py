"""连接池并发行为。

这是真机第一次接 heng-pg 就炸的地方,而当时整套测试都是绿的:契约测试注入
fake executor,直接绕过 `_pooled_query`,连接池那段代码从没被执行过。
本文件专门测那一段,且**必须并发地测**——单线程跑一万次也发现不了池子满。
"""
from __future__ import annotations

import threading
import time

import pytest

from app.store import StoreError
from app.store.pg import STATEMENT_TIMEOUT_MS, PgStore


class _FakeCursor:
    description = [("x",)]

    def __init__(self, on_execute):
        self._on_execute = on_execute

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params):
        self._on_execute()

    def fetchall(self):
        return [(1,)]


class _FakeConn:
    def __init__(self, on_execute):
        self._on_execute = on_execute

    def cursor(self):
        return _FakeCursor(self._on_execute)

    def rollback(self):
        return None


class _FakePool:
    """按 ThreadedConnectionPool 的真实脾气建模:满了就**抛错**,不阻塞。

    psycopg2 的池在耗尽时抛 PoolError 而不是等待,正是这个行为把并发检索打挂的。
    """

    def __init__(self, maxconn: int, on_execute=lambda: None):
        self.maxconn = maxconn
        self.peak = 0
        self._live = 0
        self._lock = threading.Lock()
        self._on_execute = on_execute

    def getconn(self):
        with self._lock:
            if self._live >= self.maxconn:
                raise RuntimeError("connection pool exhausted")
            self._live += 1
            self.peak = max(self.peak, self._live)
        return _FakeConn(self._on_execute)

    def putconn(self, conn):
        with self._lock:
            self._live -= 1


def _store_with_fake_pool(maxconn: int, on_execute=lambda: None, **kw) -> PgStore:
    """构造一个走 `_pooled_query` 但连假池子的 store。

    传 executor 只是为了跳过真实 `_init_pool`(它会去连数据库),随后把执行器
    换回真正要测的那条路径。
    """
    store = PgStore("dsn", executor=lambda sql, params: [], maxconn=maxconn, **kw)
    store._pool = _FakePool(maxconn, on_execute)
    store._executor = store._pooled_query
    return store


def test_concurrent_queries_queue_instead_of_exhausting_the_pool():
    """并发数超过池子大小时,多出来的**排队**,不是报错。

    没有信号量这道闸的话,第 maxconn+1 个 getconn 当场抛 PoolError。
    """
    maxconn = 3
    concurrency = 12
    barrier = threading.Barrier(concurrency)
    # 查询必须**占住连接一段可测量的时间**,否则线程虽然同时起跑,每个持有连接
    # 只有几微秒,实际根本不重叠——那样即使没有闸门,这条测试也照样是绿的。
    store = _store_with_fake_pool(maxconn, on_execute=lambda: time.sleep(0.05))

    errors: list[Exception] = []
    results: list[list] = []
    lock = threading.Lock()

    def worker():
        # 先集合再一起冲,确保真的是同时进入,而不是被调度错开
        barrier.wait(timeout=10)
        try:
            rows = store._pooled_query("SELECT 1", {})
        except Exception as exc:  # noqa: BLE001 - 测试要看清是什么错
            with lock:
                errors.append(exc)
        else:
            with lock:
                results.append(rows)

    threads = [threading.Thread(target=worker) for _ in range(concurrency)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"并发查询不该失败,实际: {errors[:3]}"
    assert len(results) == concurrency
    assert store._pool.peak <= maxconn, f"同时占用连接数超过池上限: {store._pool.peak}"


def test_slot_is_released_even_when_the_query_raises():
    """查询报错也要还槽位,否则几次失败就把池子永久漏干。"""
    maxconn = 2

    def boom():
        raise RuntimeError("boom")

    store = _store_with_fake_pool(maxconn, on_execute=boom)

    for _ in range(maxconn * 3):
        with pytest.raises(StoreError):
            store._pooled_query("SELECT 1", {})

    # 槽位没漏的话,这里还能拿满一池
    for _ in range(maxconn):
        assert store._slots.acquire(timeout=1)


def test_waiting_for_a_slot_times_out_instead_of_hanging_forever():
    """池子被长时间占住时报错收场,不让请求无限期挂着。"""
    store = _store_with_fake_pool(1, acquire_timeout_s=0.05)
    assert store._slots.acquire(timeout=1)  # 占掉唯一槽位
    try:
        with pytest.raises(StoreError) as excinfo:
            store._pooled_query("SELECT 1", {})
        assert "超时" in str(excinfo.value)
    finally:
        store._slots.release()


def test_pool_is_created_read_only_with_a_statement_timeout(monkeypatch):
    """连接级只读 + 语句超时是两道独立的保险,建池时就得挂上。"""
    captured: dict = {}

    class _Recorder:
        def __init__(self, minconn, maxconn, dsn=None, options=None, **kw):
            captured.update(
                minconn=minconn, maxconn=maxconn, dsn=dsn, options=options
            )

    import psycopg2.pool

    monkeypatch.setattr(psycopg2.pool, "ThreadedConnectionPool", _Recorder)

    PgStore("postgresql://u:p@h/db", maxconn=5)

    assert captured["maxconn"] == 5
    assert "default_transaction_read_only=on" in captured["options"]
    assert f"statement_timeout={STATEMENT_TIMEOUT_MS}" in captured["options"]


def _store_with_columns(columns):
    """注入一个只回列名的假执行器,用来测启动自检。"""
    return PgStore("dsn", executor=lambda sql, params: [(c,) for c in columns])


def test_preflight_names_the_missing_columns():
    """缺列时要把列名喊出来,而不是等用户提问再回一句脱敏套话。

    线上真实案例:`adcode` 缺失,只有带地区词的检索会炸,健康检查还是绿的
    (它只查 count 和两个 max),排查了几个小时。
    """
    from app.store import sqlbuild

    complete = list(sqlbuild.REQUIRED_POLICY_COLUMNS)
    store = _store_with_columns([c for c in complete if c != "adcode"])

    with pytest.raises(StoreError) as excinfo:
        store.preflight()
    message = str(excinfo.value)
    assert "adcode" in message
    # 别把没缺的列也报出来,否则运维不知道该补哪个
    assert "pipelinePid" not in message


def test_preflight_passes_when_the_schema_is_complete():
    from app.store import sqlbuild

    store = _store_with_columns(
        list(sqlbuild.REQUIRED_POLICY_COLUMNS) + ["someUnrelatedColumn"]
    )
    store.preflight()  # 不抛就是通过


def test_preflight_calls_out_a_wrong_database():
    """一行都查不到,说明连的库里根本没有 Policy 表。"""
    store = _store_with_columns([])
    with pytest.raises(StoreError) as excinfo:
        store.preflight()
    assert "POLICY_QA_PG_DB" in str(excinfo.value)


def test_pool_failure_message_never_carries_the_dsn():
    """连不上时的异常文本不能带 DSN——里面有口令。"""
    secret = "s3cret-password"
    with pytest.raises(StoreError) as excinfo:
        PgStore(f"postgresql://user:{secret}@127.0.0.1:1/nonexistent")
    assert secret not in str(excinfo.value)
