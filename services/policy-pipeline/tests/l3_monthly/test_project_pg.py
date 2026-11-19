"""把成稿投影进 heng-pg。

照仓内既有的 `scripts/sync/pg_writer.py` 同一范式:**SQL 构造是纯函数(可单测)**,
执行是薄 psycopg2 封装。列名对齐 heng-guan 的 Prisma schema。

这一步有两件容易出事、必须由测试钉住的:
① 每次投影都要留一行 MonthlyVersion——现有 generate() 就是没留,版本历史从第一版起就断了;
② content 里的 policyId 是 pipeline 的 pid,前端要的是 heng 的 Policy.id。
   不映射,详情标题的链接就全是死的。
"""
import json

from scripts.l3_monthly import project_pg as pp


def _content(**over):
    base = {
        "schema": "monthly.v2", "month": "2026-07", "narrative": "本月定调",
        "overview": "概述。", "businessTakes": [], "quickTable": [],
        "details": [{"no": "01", "policyId": "P_2026_NEA_688", "title": "甲文件",
                     "info": "", "reading": "", "focus": "", "advice": []},
                    {"no": "02", "policyId": "P_2026_JS_10", "title": "乙文件",
                     "info": "", "reading": "", "focus": "", "advice": []}],
        "localRoundup": "", "appendix": "", "uncovered": "", "caveats": [],
        "provenance": {"writerModel": "deepseek-v4-pro", "auditRounds": 1},
    }
    base.update(over)
    return base


class FakeConn:
    """按 SQL 关键字派发的假连接,只用来验证调用序列与参数。"""

    def __init__(self, existing=None, pid_map=None):
        self.existing = existing            # (id, version) 或 None
        self.pid_map = pid_map or {}
        self.executed = []

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        self.executed.append(("COMMIT", None))

    def rollback(self):
        self.executed.append(("ROLLBACK", None))


class _FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self._row = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.conn.executed.append((sql, params))
        if 'FROM "Monthly"' in sql:
            self._row = self.conn.existing
        elif 'FROM "Policy"' in sql:
            self._row = self.conn.pid_map.get(params["pipeline_pid"])
        elif "RETURNING" in sql:
            self._row = ("m-new",)

    def fetchone(self):
        return self._row


def _flat(sql):
    """SQL 里的对齐空格不该让测试变脆。"""
    return " ".join(sql.split())


def _sqls(conn):
    return [s for s, _ in conn.executed if isinstance(s, str)]


# ── ① SQL 构造是纯函数 ─────────────────────────────────────────
def test_insert_targets_the_right_columns():
    sql, params = pp.build_monthly_insert(
        {"title": "能源政策月刊 · 2026 年 7 月", "year": 2026, "month": 7,
         "cover_date": "2026-07-01", "status": "PUBLISHED",
         "content": '{"schema":"monthly.v2"}', "ai_model": "deepseek-v4-pro",
         "tokens_in": 0, "tokens_out": 0, "cost_cny": 0.0})
    assert 'INSERT INTO "Monthly"' in sql and "RETURNING" in sql
    for col in ('"type"', '"title"', '"year"', '"month"', '"coverDate"',
                '"status"', '"content"', '"aiModel"', '"version"'):
        assert col in sql, col
    assert params["year"] == 2026 and params["month"] == 7


def test_insert_marks_it_as_a_monthly_not_a_topic():
    sql, _ = pp.build_monthly_insert({"title": "t", "year": 2026, "month": 7,
                                      "cover_date": "2026-07-01", "status": "DRAFT",
                                      "content": "{}", "ai_model": "", "tokens_in": 0,
                                      "tokens_out": 0, "cost_cny": 0.0})
    assert "'MONTHLY'" in sql and '"MonthlyType"' in sql


def test_update_bumps_version_and_leaves_created_at_alone():
    sql, params = pp.build_monthly_update(
        {"title": "t", "status": "PUBLISHED", "content": "{}", "ai_model": "m",
         "tokens_in": 1, "tokens_out": 2, "cost_cny": 0.5}, "m-1")
    assert 'UPDATE "Monthly"' in sql
    assert '"version" = "Monthly"."version" + 1' in _flat(sql)
    assert '"createdAt"' not in sql and params["monthly_id"] == "m-1"


def test_version_row_carries_the_change_note():
    """现有 generate() 不写 changeNote,版本历史从第一版起就是空的。"""
    sql, params = pp.build_version_insert("m-1", 3, "{}", "自动生成")
    assert 'INSERT INTO "MonthlyVersion"' in sql and '"changeNote"' in sql
    assert params["version"] == 3 and params["change_note"] == "自动生成"


# ── ② pid → heng Policy.id 映射 ───────────────────────────────
def test_details_get_the_heng_policy_id_and_keep_the_pipeline_pid():
    """前端靠 policyId 跳 /policy?openId=;放 pipeline 的 pid 进去链接就是死的。"""
    out, hits = pp.map_policy_ids(_content(), {"P_2026_NEA_688": "cuid-1"})
    d0, d1 = out["details"]
    assert d0["policyId"] == "cuid-1" and d0["pipelinePid"] == "P_2026_NEA_688"
    assert hits == ["cuid-1"]
    # 映射不到的**不能瞎填**:宁可没链接,也不要链到别人身上
    assert d1["policyId"] == "" and d1["pipelinePid"] == "P_2026_JS_10"


def test_map_policy_ids_does_not_mutate_the_input():
    c = _content()
    pp.map_policy_ids(c, {"P_2026_NEA_688": "cuid-1"})
    assert c["details"][0]["policyId"] == "P_2026_NEA_688"


# ── ③ 投影流程 ─────────────────────────────────────────────────
def test_first_projection_inserts_and_writes_version_one():
    conn = FakeConn(existing=None, pid_map={"P_2026_NEA_688": ("cuid-1",)})
    res = pp.project(conn, _content(), model="deepseek-v4-pro")
    sqls = _sqls(conn)
    assert any('INSERT INTO "Monthly"' in s for s in sqls)
    assert any('INSERT INTO "MonthlyVersion"' in s for s in sqls)
    assert res["monthly_id"] == "m-new" and res["version"] == 1
    assert ("COMMIT", None) in conn.executed


def test_rerun_updates_and_bumps_version():
    conn = FakeConn(existing=("m-1", 2), pid_map={})
    res = pp.project(conn, _content(), model="m", change_note="重跑")
    sqls = _sqls(conn)
    assert any('UPDATE "Monthly"' in s for s in sqls)
    assert not any('INSERT INTO "Monthly"' in s for s in sqls)
    assert res["version"] == 3


def test_join_rows_are_written_for_resolved_policies_only():
    conn = FakeConn(existing=None, pid_map={"P_2026_NEA_688": ("cuid-1",)})
    pp.project(conn, _content(), model="m")
    joins = [p for s, p in conn.executed
             if isinstance(s, str) and 'INTO "MonthlyPolicy"' in s]
    assert [p["policy_id"] for p in joins] == ["cuid-1"]


def test_dry_run_touches_nothing():
    conn = FakeConn(existing=None)
    res = pp.project(conn, _content(), model="m", dry_run=True)
    assert conn.executed == [] and res["dry_run"] is True
    assert res["version"] == 1


def test_status_is_explicit_and_defaults_to_published():
    """用户要的是每月自动出稿、前端直接展示,所以默认发布;
    但状态必须是显式参数,免得哪天想改成先进审核却要动代码。"""
    conn = FakeConn(existing=None)
    pp.project(conn, _content(), model="m")
    ins = next(p for s, p in conn.executed
               if isinstance(s, str) and 'INSERT INTO "Monthly"' in s)
    assert ins["status"] == "PUBLISHED"
    conn2 = FakeConn(existing=None)
    pp.project(conn2, _content(), model="m", status="DRAFT")
    ins2 = next(p for s, p in conn2.executed
                if isinstance(s, str) and 'INSERT INTO "Monthly"' in s)
    assert ins2["status"] == "DRAFT"


def test_content_written_is_the_mapped_one():
    conn = FakeConn(existing=None, pid_map={"P_2026_NEA_688": ("cuid-1",)})
    pp.project(conn, _content(), model="m")
    ins = next(p for s, p in conn.executed
               if isinstance(s, str) and 'INSERT INTO "Monthly"' in s)
    assert json.loads(ins["content"])["details"][0]["policyId"] == "cuid-1"


def test_failure_rolls_back():
    class Boom(FakeConn):
        def cursor(self):
            raise RuntimeError("连接断了")

    conn = Boom(existing=None)
    try:
        pp.project(conn, _content(), model="m")
    except RuntimeError:
        pass
    assert ("ROLLBACK", None) in conn.executed


def test_publish_date_only_set_when_published():
    _, pub = pp.build_monthly_insert(
        {"title": "t", "year": 2026, "month": 7, "cover_date": "2026-07-01",
         "status": "PUBLISHED", "content": "{}", "ai_model": "", "tokens_in": 0,
         "tokens_out": 0, "cost_cny": 0.0})
    _, draft = pp.build_monthly_insert(
        {"title": "t", "year": 2026, "month": 7, "cover_date": "2026-07-01",
         "status": "DRAFT", "content": "{}", "ai_model": "", "tokens_in": 0,
         "tokens_out": 0, "cost_cny": 0.0})
    assert pub["publish_date"] is not None and draft["publish_date"] is None
