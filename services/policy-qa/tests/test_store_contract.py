"""双 adapter 契约:同一份数据,vault 与 pg 必须给出同样的答案。

覆盖边界说明(重要,别误读这套测试的强度):

  - **本文件覆盖 Python 侧语义**:business_line 过滤与摘录、排序、limit/total、
    行→模型映射、caveat 附着。这些在两个 adapter 里是各写一份的,最容易漂,
    所以在这里做真正的 apples-to-apples 对比(fake executor 返回全部行,
    不模拟 SQL 的 WHERE——因为这几项 SQL 本来就不参与过滤)。
  - **SQL 侧过滤**(keyword/date/region/issuer/min_importance)由 test_sqlbuild 覆盖
    结构与参数,由 test_vault_adapter 覆盖语义。真库上的实际行为需要 operator
    在服务器 smoke(PR-3),本地无法验证。
"""
from __future__ import annotations

import json

import pytest

from app.store import DEFAULT_LIMIT
from app.store.pg import PgStore


def _rows_from_vault(vault_store, detail: bool = False) -> list[tuple]:
    """把 vault 的内存行转成 pg 查询会返回的元组形状(SEARCH_COLUMNS 顺序)。

    刻意保留 pg 侧的真实类型差异:themes 是 jsonb(list[dict]),
    impact 是 text 列里的 JSON 字符串。
    """
    out = []
    for row in vault_store._policies.values():
        themes = [{"id": t, "isPrimary": i == 0} for i, t in enumerate(row["themes"])]
        impact = json.dumps(row["impact"], ensure_ascii=False) if row["impact"] else None
        base = (
            row["pid"],
            row["title"],
            row["doc_number"],
            row["issuer"],
            row["issue_date"],
            row["region"],
            row["level"],
            row["importance"],
            themes,
            impact,
            row["source_url"],
        )
        if detail:
            scores = json.dumps(row["scores"], ensure_ascii=False) if row["scores"] else None
            base = base + (row["content"], scores, "2026-08-17T21:00:00+08:00")
        out.append(base)
    return out


@pytest.fixture
def pg_store(vault_store):
    """用 mini-vault 的数据喂一个 fake executor,构造出等价的 PgStore。"""

    def executor(sql: str, params: dict) -> list[tuple]:
        if "COUNT(*)" in sql:
            rows = _rows_from_vault(vault_store)
            dates = [r[4] for r in rows]
            return [(len(rows), max(dates) if dates else None, "2026-08-17T21:00:00+08:00")]
        if 'FROM "Policy" WHERE "pipelinePid" = %(pid)s' in sql:
            pid = params["pid"]
            return [r for r in _rows_from_vault(vault_store, detail=True) if r[0] == pid][:1]
        if "PolicySemanticRelation" in sql:
            pid = params["pid"]
            return [
                (e.direction, e.relation_type, e.other_pid, e.other_title, e.evidence, e.confidence)
                for e in vault_store.get_relations(pid)
            ]
        if "CommentarySignal" in sql:
            pid = json.loads(params["pid_json"])[0]
            return [
                (
                    c.commentary_id,
                    c.title,
                    c.signal_role,
                    c.evidence,
                    c.source_account,
                    c.business_tag,
                    c.confidence,
                )
                for c in vault_store.get_commentary(pid)
            ]
        # 检索:SQL 侧的 WHERE 由 test_sqlbuild 覆盖,这里返回全集
        return _rows_from_vault(vault_store)

    return PgStore("postgresql://fake/db", executor=executor)


def _cards(res):
    return [(c.pid, c.importance, c.impact_snippet) for c in res.rows]


@pytest.mark.parametrize("business_line", [None, "充电", "电力", "加油"])
def test_business_line_filter_matches(vault_store, pg_store, business_line):
    v = vault_store.search_policies(business_line=business_line, limit=DEFAULT_LIMIT)
    p = pg_store.search_policies(business_line=business_line, limit=DEFAULT_LIMIT)
    assert v.total == p.total
    assert _cards(v) == _cards(p)


@pytest.mark.parametrize("order", ["date_desc", "importance_desc"])
def test_order_matches(vault_store, pg_store, order):
    v = vault_store.search_policies(order=order, limit=50)
    p = pg_store.search_policies(order=order, limit=50)
    assert [c.pid for c in v.rows] == [c.pid for c in p.rows]


@pytest.mark.parametrize("limit", [1, 3, 999])
def test_limit_and_total_match(vault_store, pg_store, limit):
    v = vault_store.search_policies(limit=limit)
    p = pg_store.search_policies(limit=limit)
    assert v.total == p.total
    assert len(v.rows) == len(p.rows) <= 50


def test_card_mapping_matches(vault_store, pg_store):
    """themes 在两侧的原始形状不同(vault 字符串列表 / pg jsonb 字典列表),
    归一化后必须一致。

    caveat 单独排除:见 test_caveat_divergence_is_known,那是设计上的已知分歧。
    """
    v = {c.pid: c for c in vault_store.search_policies(limit=50).rows}
    p = {c.pid: c for c in pg_store.search_policies(limit=50).rows}
    assert v.keys() == p.keys()
    for pid in v:
        vd = v[pid].model_dump()
        pd = p[pid].model_dump()
        vd.pop("caveat")
        pd.pop("caveat")
        assert vd == pd, f"{pid} 卡片映射不一致"


def test_caveat_divergence_is_known(vault_store, pg_store):
    """**已知且有意的分歧**:撞车 pid 的 caveat 两侧不可能完全一致。

    vault 能在建索引时数出真实撞车数;pg 拿到的是投影后的结果,撞车在投影时
    就已经被 upsert 吃掉了,运行时无从发现,只能靠 COLLIDED_PIDS 快照。
    后果:快照没收录的新撞车,pg backend 不会提示。这是数据面缺陷,修在 pipeline,
    不在本服务(消费端只读)。
    """
    from conftest import COLLISION_PID

    v = vault_store.get_policy(COLLISION_PID)
    p = pg_store.get_policy(COLLISION_PID)
    assert v.caveat is not None, "vault 实测得到撞车数,必须提示"
    assert p.caveat is None, "该测试 pid 不在快照里,pg 侧发现不了——这正是缺陷所在"


def test_detail_matches(vault_store, pg_store):
    for pid in ("P_2026_TEST_1", "P_2026_TEST_2"):
        v = vault_store.get_policy(pid)
        p = pg_store.get_policy(pid)
        assert v.content == p.content
        assert v.scores == p.scores
        assert v.impact == p.impact
        assert v.importance == p.importance
        assert v.themes == p.themes


def test_detail_offset_matches(vault_store, pg_store):
    v = vault_store.get_policy("P_2026_TEST_1", max_chars=7, offset=3)
    p = pg_store.get_policy("P_2026_TEST_1", max_chars=7, offset=3)
    assert v.content == p.content
    assert v.content_total_chars == p.content_total_chars
    assert v.content_offset == p.content_offset == 3


def test_missing_policy_matches(vault_store, pg_store):
    assert vault_store.get_policy("P_NOPE") is None
    assert pg_store.get_policy("P_NOPE") is None


def test_caveat_attached_on_both(vault_store, pg_store):
    """撞车 pid 两侧都要带缺陷说明——vault 实测计数,pg 走静态快照。"""
    from conftest import COLLISION_PID
    from app.store import COLLIDED_PIDS

    v = vault_store.get_policy(COLLISION_PID)
    assert v.caveat is not None

    # pg 侧无法运行时发现撞车,靠快照。用快照里的真实 pid 验证机制。
    real_pid = next(iter(COLLIDED_PIDS))
    from app.store import caveat_for

    assert caveat_for(real_pid) is not None
    assert caveat_for("P_2026_NOT_COLLIDED") is None


def test_relations_and_commentary_match(vault_store, pg_store):
    for pid in ("P_2026_TEST_1", "P_2026_TEST_3"):
        v = vault_store.get_relations(pid)
        p = pg_store.get_relations(pid)
        assert [e.model_dump() for e in v] == [e.model_dump() for e in p]
        assert [c.model_dump() for c in vault_store.get_commentary(pid)] == [
            c.model_dump() for c in pg_store.get_commentary(pid)
        ]


def test_stats_shape_matches(vault_store, pg_store):
    v, p = vault_store.stats(), pg_store.stats()
    assert v["policies"] == p["policies"]
    assert v["latest_issue_date"] == p["latest_issue_date"]
