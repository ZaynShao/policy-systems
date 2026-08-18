"""SQL 构造。纯函数,断言结构与参数,不连库。"""
from __future__ import annotations

import json

from app.store import sqlbuild


def test_search_always_excludes_manual_rows():
    """表里混着人工录入行(pipelinePid IS NULL),任何检索都不能捞到它们。"""
    sql, _ = sqlbuild.build_search_sql()
    assert '"pipelinePid" IS NOT NULL' in sql


def test_search_has_no_business_line_clause():
    """business_line 过滤在 Python 侧(pipelineImpact 是存 JSON 的 text 列)。"""
    sql, params = sqlbuild.build_search_sql()
    assert "pipelineImpact" not in sql.split("FROM")[1]  # 只在 SELECT 列里出现
    assert params == {}


def test_search_excludes_content_column():
    """粗滤要把候选行全取回 Python,带正文会到几十 MB。"""
    sql, _ = sqlbuild.build_search_sql()
    assert '"content"' not in sql


def test_keyword_tokens_are_and_ed():
    sql, params = sqlbuild.build_search_sql(keyword="充电 通知")
    assert params["kw0"] == "%充电%"
    assert params["kw1"] == "%通知%"
    assert sql.count("ILIKE %(kw0)s") == 2  # title 与 docNumber 各一次
    assert " AND " in sql


def test_keyword_like_metachars_escaped():
    """% 和 _ 是 LIKE 元字符,必须按字面量匹配,否则用户输入会变成通配符。"""
    _, params = sqlbuild.build_search_sql(keyword="50%_test")
    assert params["kw0"] == r"%50\%\_test%"


def test_injection_attempt_stays_a_parameter():
    """恶意输入只能进参数,不能改变 SQL 结构。

    注意 SQL 文本只随**词数**变化(每个词一个参数名),不随词的内容变化。
    所以对比基线要用同词数的无害输入。
    """
    evil = "';DROP--"
    sql, params = sqlbuild.build_search_sql(keyword=evil)
    assert "DROP TABLE" not in sql
    assert evil in params["kw0"]
    baseline, _ = sqlbuild.build_search_sql(keyword="harmless")
    assert sql == baseline, "同词数下,关键字内容不应改变 SQL 文本"

    multi, multi_params = sqlbuild.build_search_sql(keyword="a b c")
    assert set(multi_params) == {"kw0", "kw1", "kw2"}
    assert "DROP" not in multi


def test_date_and_issuer_clauses():
    sql, params = sqlbuild.build_search_sql(
        date_from="2026-01-01", date_to="2026-12-31", issuer_keyword="能源局"
    )
    assert '"issueDate" >= %(date_from)s' in sql
    assert '"issueDate" <= %(date_to)s' in sql
    assert params["issuer_kw"] == "%能源局%"


def test_region_matches_name_code_or_level():
    sql, params = sqlbuild.build_search_sql(region_keyword="江苏")
    assert '"region" ILIKE %(region_kw)s' in sql
    assert '"adcode" ILIKE %(region_kw)s' in sql
    assert '"level" = %(region_exact)s' in sql
    assert params["region_exact"] == "江苏"


def test_min_importance_expands_to_allowed_set():
    _, params = sqlbuild.build_search_sql(min_importance="MAJOR")
    assert set(params["importances"]) == {"MAJOR", "STRATEGIC"}
    _, params = sqlbuild.build_search_sql(min_importance="INFO")
    assert set(params["importances"]) == {"INFO", "GENERAL", "MAJOR", "STRATEGIC"}


def test_search_has_row_cap():
    sql, _ = sqlbuild.build_search_sql()
    assert f"LIMIT {sqlbuild.SEARCH_ROW_CAP}" in sql


def test_get_policy_sql():
    sql, params = sqlbuild.build_get_policy_sql("P_2026_X_1")
    assert '"pipelinePid" = %(pid)s' in sql
    assert '"content"' in sql
    assert params == {"pid": "P_2026_X_1"}


def test_relations_sql_joins_both_directions():
    sql, params = sqlbuild.build_relations_sql("P_2026_X_1")
    assert sql.count("UNION ALL") == 1
    assert "'outbound'" in sql and "'inbound'" in sql
    # 关系表存的是 Policy.id,必须 JOIN 回去换 pid
    assert sql.count('JOIN "Policy"') == 4
    assert params == {"pid": "P_2026_X_1"}


def test_commentary_sql_uses_jsonb_containment():
    sql, params = sqlbuild.build_commentary_sql("P_2026_X_1")
    assert '"relatedPolicyPids" @> %(pid_json)s::jsonb' in sql
    assert json.loads(params["pid_json"]) == ["P_2026_X_1"]


def test_stats_sql():
    sql, _ = sqlbuild.build_stats_sql()
    assert "COUNT(*)" in sql
    assert '"pipelinePid" IS NOT NULL' in sql
