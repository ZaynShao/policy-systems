"""对着**真** Postgres 跑一遍 SQL。默认跳过。

存在的理由:其余测试全都注入 fake executor 或用 vault 文件,SQL 文本从没被
数据库解析过——`::text IN`、`@> ::jsonb`、ILIKE 转义、列名大小写写错了,
本地照样全绿,第一次执行是在生产上。这就是 README 已知限制 #9。

跑法(需要一个能建表的空库):

    POLICY_QA_TEST_DATABASE_URL=postgresql://user@127.0.0.1:5432/probe_db \\
        python -m pytest tests/test_pg_integration.py -v

本机临时起一个的办法见 `docs/dev-postgres.md`。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.store.pg import PgStore

DSN = os.getenv("POLICY_QA_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not DSN, reason="未设 POLICY_QA_TEST_DATABASE_URL,跳过真库集成测试"
)

SCHEMA_SQL = Path(__file__).parent / "fixtures" / "heng_pg_schema.sql"


@pytest.fixture(scope="module")
def live_store():
    """按 heng 的 Prisma schema 建表灌数,跑完拆掉。

    表结构必须与 services/heng-guan/backend/prisma/schema.prisma 的 Policy /
    PolicySemanticRelation / CommentarySignal 一致;那份 schema 变了,这里要跟。
    """
    psycopg2 = pytest.importorskip("psycopg2")

    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                'DROP TABLE IF EXISTS "CommentarySignal", "PolicySemanticRelation", '
                '"Policy" CASCADE'
            )
            cur.execute(
                'DROP TYPE IF EXISTS "PolicyImportance", "PolicySource", '
                '"InterpretStatus" CASCADE'
            )
            cur.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
        yield PgStore(DSN)
    finally:
        conn.close()


def test_every_search_shape_parses_on_a_real_server(live_store):
    """每种 WHERE 组合都让服务器真解析一遍。

    断言只看「没抛异常」——命中几条由 fixture 数据决定,不是本测试的重点;
    重点是 SQL 文本本身合法。
    """
    shapes = {
        "无条件": {},
        "keyword 单词": {"keyword": "充电"},
        "keyword 多词": {"keyword": "充电 基础设施"},
        "keyword 含 LIKE 元字符": {"keyword": "100%_电"},
        "date_from": {"date_from": "2026-05-20"},
        "date_to": {"date_to": "2026-06-30"},
        "date 区间": {"date_from": "2026-01-01", "date_to": "2026-12-31"},
        "region 名": {"region_keyword": "浙江"},
        "region adcode": {"region_keyword": "330000"},
        "region level": {"region_keyword": "省"},
        "issuer(同时匹配标题)": {"issuer_keyword": "财政部"},
        "min_importance(枚举转 text 再 IN 元组)": {"min_importance": "MAJOR"},
        "全条件叠加": {
            "keyword": "充电",
            "date_from": "2026-01-01",
            "date_to": "2026-12-31",
            "region_keyword": "全国",
            "issuer_keyword": "发展改革委",
            "min_importance": "INFO",
        },
    }
    for label, kw in shapes.items():
        try:
            live_store.search_policies(**kw)
        except Exception as exc:  # noqa: BLE001 - 要把是哪一种形状说清楚
            pytest.fail(f"{label} 的 SQL 在真库上失败: {type(exc).__name__}: {exc}")


def test_detail_relation_commentary_sql_parse_on_a_real_server(live_store):
    """列表之外的三条路径:详情多选三列,关系走 UNION ALL + 两次 JOIN,
    评论走 jsonb 包含判定 `@>`。"""
    assert live_store.get_policy("P_2026_NDRC_1") is not None
    assert live_store.get_policy("P_DOES_NOT_EXIST") is None
    assert live_store.get_relations("P_2026_NDRC_1")
    assert live_store.get_commentary("P_2026_NDRC_1")
    assert live_store.stats()["policies"] >= 1


def test_preflight_accepts_the_real_schema(live_store):
    """自检要的列必须与 heng 的 Prisma schema 一致。

    这条防的是自检本身写歪:REQUIRED_POLICY_COLUMNS 多写一个不存在的列,
    服务就再也起不来了,而单测里的假执行器发现不了。
    """
    live_store.preflight()


def test_preflight_catches_a_column_that_the_database_lacks(live_store):
    """把线上那次事故复刻一遍:删掉 adcode,自检必须当场报出它。"""
    psycopg2 = pytest.importorskip("psycopg2")

    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute('ALTER TABLE "Policy" DROP COLUMN "adcode"')
        with pytest.raises(Exception) as excinfo:
            live_store.preflight()
        assert "adcode" in str(excinfo.value)
        with conn.cursor() as cur:
            cur.execute('ALTER TABLE "Policy" ADD COLUMN "adcode" text')
    finally:
        conn.close()

    live_store.preflight()


def test_theme_containment_works_on_a_real_server(live_store):
    """主题过滤走 jsonb 的 `@>` 包含判定,必须让真服务器解析一遍。

    `pipelineThemes` 是 `[{id,isPrimary,isComprehensive}]`,过滤时把探针对象
    整个丢进 `@>`——`@>` 的语义是"被包含对象的每个键值都要匹配",所以
    primary_theme_only 不需要拆成两个条件。这套写法只在内存 fixture 上验过,
    真库上没跑过,而这正是 README 已知限制 #9 说的那类坑。
    """
    res = live_store.search_policies(theme_id="charging_infra")
    assert [c.pid for c in res.rows] == ["P_2026_NDRC_1"]

    primary = live_store.search_policies(theme_id="charging_infra", primary_theme_only=True)
    assert [c.pid for c in primary.rows] == ["P_2026_NDRC_1"]
    assert primary.rows[0].primary_theme == "charging_infra"

    # 挂着但不是"主"主题的,primary_theme_only 要把它排除掉
    assert live_store.search_policies(theme_id="power_market").total == 1
    assert live_store.search_policies(
        theme_id="power_market", primary_theme_only=True
    ).total == 0

    # 不存在的主题给空结果而不是报错
    assert live_store.search_policies(theme_id="no_such_theme").total == 0


def test_manual_rows_never_surface(live_store):
    """pipelinePid 为空的是人工录入行,任何查询都不该带出它。"""
    res = live_store.search_policies()
    assert res.total >= 1
    assert all(r.pid for r in res.rows)
    assert not any(r.title == "手工录入的政策" for r in res.rows)


def test_the_connection_really_refuses_writes(live_store):
    """连接级 read-only 是两道锁之一(另一道是只读角色),它必须真的生效。"""
    from app.store import StoreError

    with pytest.raises(StoreError):
        live_store._executor('UPDATE "Policy" SET "title" = "title"', {})


def test_parallel_searches_all_succeed(live_store):
    """一轮里并行发的检索必须全部成活。

    真机第一次上线就栽在这:模型一轮并行发七个检索,池子只有四条连接,
    多出来的当场 PoolError,又因为并行执行里一个失败会取消同批其余调用,
    七条全废。这条测试对着真库复现过那个失败,修复后才转绿。
    """
    import threading

    calls = [
        {"business_line": "充电", "date_from": "2026-05-20"},
        {"business_line": "充电", "date_from": "2026-04-20"},
        {"keyword": "充电", "date_from": "2026-05-20"},
        {"keyword": "储能"},
        {"issuer_keyword": "财政部"},
        {"issuer_keyword": "税务总局"},
        {"min_importance": "MAJOR"},
    ]
    barrier = threading.Barrier(len(calls))
    errors: list[str] = []
    lock = threading.Lock()

    def worker(kw):
        barrier.wait(timeout=15)
        try:
            live_store.search_policies(**kw)
        except Exception as exc:  # noqa: BLE001
            with lock:
                errors.append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=worker, args=(c,)) for c in calls]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert not errors, f"并行检索出现失败: {errors}"
