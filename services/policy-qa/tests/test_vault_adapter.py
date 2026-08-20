"""vault adapter 行为。夹具见 conftest.mini_vault。"""
from __future__ import annotations

from conftest import COLLISION_PID, COLLISION_WINNER_TITLE


def test_archive_and_bad_date_excluded(vault_store):
    pids = {c.pid for c in vault_store.search_policies(limit=50).rows}
    assert "P_2026_TEST_ARCHIVED" not in pids, "_archive/ 下的政策不得进入检索"
    assert "P_1900_TEST_NODATE" not in pids, "缺 date 的政策不收"
    assert vault_store.stats()["skipped_no_date"] == 1


def test_collision_collapses_to_latest(vault_store):
    """同 pid 多份文件必须坍缩成一份——与 pg 的 upsert 行为对齐。"""
    assert vault_store.collisions.get(COLLISION_PID) == 2
    detail = vault_store.get_policy(COLLISION_PID)
    assert detail is not None
    assert detail.title == COLLISION_WINNER_TITLE, "应留下发布日期最新的一份"
    assert detail.caveat is not None and "2 份" in detail.caveat
    rows = [c for c in vault_store.search_policies(limit=50).rows if c.pid == COLLISION_PID]
    assert len(rows) == 1, "撞车 pid 在检索结果里只能出现一次"


def test_issuer_array_joined(vault_store):
    detail = vault_store.get_policy("P_2026_TEST_1")
    assert detail.issuer == "国家发展改革委、国家能源局"


def test_missing_business_view_keeps_policy(vault_store):
    """缺 business_view 不能丢政策,只是没有内部评估。"""
    detail = vault_store.get_policy("P_2026_TEST_2")
    assert detail is not None
    assert detail.importance == "INFO"
    assert detail.scores is None and detail.impact is None


def test_business_view_mapping(vault_store):
    detail = vault_store.get_policy("P_2026_TEST_1")
    assert detail.importance == "STRATEGIC"  # 重要性 5
    assert detail.scores == {"D1": 5, "D2": 5, "D3": 5, "D4": 4, "D5": 4, "D6": 5}
    assert "充电" in detail.impact
    assert detail.themes == ["charging_infra", "power_market"]


def test_garbled_content_preserved(vault_store):
    """编码损伤原样保留,不在消费端修复。"""
    detail = vault_store.get_policy("P_2026_TEST_GARBLE")
    assert "ä¹±ç " in detail.content


def test_keyword_is_and_across_tokens(vault_store):
    assert vault_store.search_policies(keyword="充电 通知").total == 1
    assert vault_store.search_policies(keyword="充电 储能").total == 0, "词间是 AND"


def test_keyword_matches_doc_number(vault_store):
    res = vault_store.search_policies(keyword="国能发〔2026〕88号")
    assert [c.pid for c in res.rows] == ["P_2026_TEST_3"]


def test_business_line_filter_and_snippet(vault_store):
    charging = vault_store.search_policies(business_line="充电")
    assert [c.pid for c in charging.rows] == ["P_2026_TEST_1"]
    assert "充电桩" in charging.rows[0].impact_snippet

    power = vault_store.search_policies(business_line="电力")
    assert {c.pid for c in power.rows} == {"P_2026_TEST_1", "P_2026_TEST_3"}

    # 无影响数据的政策不该被业务线过滤命中
    assert all(c.pid != "P_2026_TEST_2" for c in power.rows)


def test_negative_impact_is_not_a_match(vault_store):
    """"未直接涉及……"不算命中——库里 64% 的影响条目是这种否定式,
    按"值非空即命中"会让业务线过滤失去意义。"""
    charging = vault_store.search_policies(business_line="充电")
    assert "P_2026_TEST_3" not in {c.pid for c in charging.rows}
    # 但详情里仍能看到完整影响分析,由模型自己判断
    detail = vault_store.get_policy("P_2026_TEST_3")
    assert detail.impact["充电"].startswith("未直接涉及")


def test_no_business_line_still_carries_the_impact_analysis(vault_store):
    """不指定业务线时给**全量影响摘要**,不是留空。

    留空曾经害惨了一次:规划器改成偏好按主题检索之后,主题检索不带 business_line,
    卡片就只剩标题/日期/机关,模型没有任何判断依据,只能挨个读原文——
    实测一个盘点式问题读掉 11 篇、总调用 20 次撞爆 18 的上限。
    而 L2 早把"这件事对各业务线意味着什么"写好了,不给它才是浪费。
    """
    card = next(
        c for c in vault_store.search_policies(keyword="充电").rows
        if c.pid == "P_2026_TEST_1"
    )
    assert card.impact_snippet, "没有业务线时也要带影响分析"
    assert "充电" in card.impact_snippet


def test_impact_digest_drops_the_irrelevant_entries(vault_store):
    """摘要里不能混进"未直接涉及"——全库六成条目是那句,混进来就全是噪声。"""
    card = next(
        c for c in vault_store.search_policies(keyword="储能").rows
        if c.pid == "P_2026_TEST_3"
    )
    assert card.impact_snippet
    assert "未直接涉及" not in card.impact_snippet


def test_date_range(vault_store):
    res = vault_store.search_policies(date_from="2026-05-01", date_to="2026-06-30")
    assert {c.pid for c in res.rows} == {"P_2026_TEST_2", "P_2026_TEST_3"}


def test_region_and_issuer_filters(vault_store):
    assert {c.pid for c in vault_store.search_policies(region_keyword="江苏").rows} == {
        "P_2026_TEST_2"
    }
    assert {c.pid for c in vault_store.search_policies(region_keyword="320000").rows} == {
        "P_2026_TEST_2"
    }
    # level 走全等
    national = {c.pid for c in vault_store.search_policies(region_keyword="国家").rows}
    assert "P_2026_TEST_1" in national and "P_2026_TEST_2" not in national
    assert {c.pid for c in vault_store.search_policies(issuer_keyword="国家能源局").rows} == {
        "P_2026_TEST_1",
        "P_2026_TEST_3",
    }


def test_issuer_falls_back_to_title(vault_store):
    """issuer 字段全库 38% 为空,机关常只写在标题里。只匹配 issuer 列会假性漏检,
    进而诱导模型做出"库里没有该机关文件"的错误全称否定。"""
    # 江苏那篇的 issuer 是"江苏省发展改革委",标题里没有"发展改革委"以外的机关词;
    # 用标题里独有的词验证标题回退确实生效
    res = vault_store.search_policies(issuer_keyword="成品油")
    assert "P_2026_TEST_2" in {c.pid for c in res.rows}, "标题命中也应算 issuer 命中"


def test_min_importance(vault_store):
    res = vault_store.search_policies(min_importance="MAJOR")
    assert {c.pid for c in res.rows} == {"P_2026_TEST_1", "P_2026_TEST_3"}


def test_order_and_limit(vault_store):
    by_date = vault_store.search_policies(order="date_desc", limit=2)
    assert by_date.total > 2, "total 是过滤后总数,不受 limit 影响"
    assert len(by_date.rows) == 2
    assert by_date.rows[0].issue_date >= by_date.rows[1].issue_date

    by_imp = vault_store.search_policies(order="importance_desc", limit=3)
    assert by_imp.rows[0].pid == "P_2026_TEST_1"


def test_limit_hard_cap(vault_store):
    assert len(vault_store.search_policies(limit=999).rows) <= 50


def test_get_policy_offset_and_total(vault_store):
    full = vault_store.get_policy("P_2026_TEST_1")
    part = vault_store.get_policy("P_2026_TEST_1", max_chars=5, offset=2)
    assert part.content == full.content[2:7]
    assert part.content_total_chars == full.content_total_chars
    assert part.content_offset == 2


def test_get_policy_missing_returns_none(vault_store):
    assert vault_store.get_policy("P_NOPE") is None


def test_relations_bidirectional_and_deduped(vault_store):
    out = vault_store.get_relations("P_2026_TEST_1")
    supersedes = [e for e in out if e.relation_type == "supersedes"]
    assert len(supersedes) == 1, "重复关系行必须去重"
    assert supersedes[0].direction == "outbound"
    assert supersedes[0].other_pid == "P_2026_TEST_3"
    assert supersedes[0].other_title == "关于开展新型储能示范项目的通知"

    inbound = [e for e in out if e.direction == "inbound"]
    assert {e.other_pid for e in inbound} == {"P_2026_TEST_2"}

    # 反向:TEST_3 应看到入向的 supersedes
    back = vault_store.get_relations("P_2026_TEST_3")
    assert any(e.direction == "inbound" and e.relation_type == "supersedes" for e in back)


def test_relation_to_missing_policy_kept(vault_store):
    """悬挂目标不丢边,只是没有标题。"""
    out = vault_store.get_relations("P_2026_TEST_1")
    dangling = [e for e in out if e.other_pid == "P_2099_NOT_EXIST"]
    assert len(dangling) == 1 and dangling[0].other_title is None


def test_commentary_lookup(vault_store):
    items = vault_store.get_commentary("P_2026_TEST_1")
    assert [i.commentary_id for i in items] == ["C_test0001"]
    assert items[0].signal_role == "opportunity"
    assert vault_store.get_commentary("P_2026_TEST_3") == []


def test_stats(vault_store):
    st = vault_store.stats()
    assert st["policies"] == 5  # 6 篇候选 - 1 篇撞车坍缩;不含 archive/无日期
    assert st["latest_issue_date"] == "2026-07-15"
    assert st["collided_pids"] == 1
