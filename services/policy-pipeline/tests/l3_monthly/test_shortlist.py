"""MA1 粗筛 + 去重。

去重是实测出来的需求:vault 里同一份文件被采成多份(942 号 3 个文件名变体、
884 号 2 个、42 号令 2 个)。不处理会让选目重复计数、配额失真。
纪律:**只对文号相同的做硬合并**;标题核心相同的只打 near-dup 标记交 MA3 裁,
不静默丢——把两份不同的文件当重复丢掉,比留着重复更糟。
"""
from scripts.l3_monthly import shortlist as sl
from scripts.l3_monthly.models import Candidate


def _c(pid, title, docno="", body_len=100, raw_path="/x.md"):
    return Candidate(policy_id=pid, title=title, official_number=docno,
                     date="2026-07-01", date_missing=False,
                     raw_path=raw_path, body_len=body_len, region_name="")


# ── 标题归一 ────────────────────────────────────────────────────
def test_normalize_title_strips_trailing_docno_paren():
    a = sl.normalize_title("关于印发《新型能源体系建设“十五五”规划》的通知(发改能源〔2026〕884号)")
    b = sl.normalize_title("关于印发《新型能源体系建设“十五五”规划》的通知")
    assert a == b


def test_normalize_title_strips_brackets_and_width():
    assert sl.normalize_title("《Ａ办法》 试行") == sl.normalize_title("A办法试行")


def test_core_title_takes_book_title_mark_content():
    t = "国家发展改革委 国家能源局关于印发《新型电力系统建设“十五五”规划》的通知"
    assert sl.core_title(t) == sl.normalize_title("新型电力系统建设十五五规划")


def test_core_title_falls_back_to_whole_title():
    assert sl.core_title("2026年8月14日国内成品油价格调整") != ""


# ── 硬合并:同文号 ───────────────────────────────────────────────
def test_dedupe_merges_same_official_number_keeps_longest_body():
    # 标题必须相容才合并——只共用文号不算(见下方 docno_conflict 用例)
    items = [_c("P_1", "关于印发《甲办法》的通知", "发改能源〔2026〕884号",
                body_len=100, raw_path="/short.md"),
             _c("P_2", "关于印发《甲办法》的通知(发改能源〔2026〕884号)", "发改能源〔2026〕884号",
                body_len=900, raw_path="/long.md")]
    kept, dropped = sl.dedupe(items)
    assert [k.policy_id for k in kept] == ["P_2"], "应保留 RAW 正文最长的那份"
    assert dropped[0].policy_id == "P_1" and dropped[0].dup_of == "P_2"


def test_dedupe_does_not_merge_empty_official_numbers():
    """文号为空的不能互相合并——空 != 空。"""
    items = [_c("P_1", "甲", ""), _c("P_2", "乙", "")]
    kept, _ = sl.dedupe(items)
    assert {k.policy_id for k in kept} == {"P_1", "P_2"}


# ── 软标记:核心标题相同 ─────────────────────────────────────────
def test_dedupe_flags_near_dup_without_dropping():
    """942 号那种:同一份通知被采两次,但文号只有一份抓到了。"""
    items = [
        _c("P_1", "关于印发《新型电力系统建设“十五五”规划》的通知(发改能源〔2026〕942号)",
           "发改能源〔2026〕942号"),
        _c("P_2", "国家发展改革委 国家能源局关于印发《新型电力系统建设“十五五”规划》的通知", ""),
    ]
    kept, dropped = sl.dedupe(items)
    assert len(kept) == 2 and dropped == [], "near-dup 不丢,交 MA3 裁"
    assert kept[0].near_dup_group and kept[0].near_dup_group == kept[1].near_dup_group


def test_dedupe_does_not_flag_news_item_as_dup_of_notice():
    """《X规划》发布(新闻) vs 关于印发《X规划》的通知(公文)不是同一件事。"""
    items = [
        _c("P_1", "《新型电力系统建设“十五五”规划》发布", ""),
        _c("P_2", "关于印发《新型电力系统建设“十五五”规划》的通知", ""),
    ]
    kept, _ = sl.dedupe(items)
    assert kept[0].near_dup_group != kept[1].near_dup_group or not kept[0].near_dup_group


# ── 噪声过滤 ────────────────────────────────────────────────────
def test_build_shortlist_drops_noise():
    items = [_c("P_1", "赛罕区市场监管局开展六一儿童节前专项检查"),
             _c("P_2", "关于有序推动多用户绿电直连发展有关事项的通知")]
    kept, dropped = sl.build_shortlist(items)
    assert [k.policy_id for k in kept] == ["P_2"]
    assert dropped[0].drop_reason == "noise"


def test_build_shortlist_reports_counts():
    items = [_c("P_1", "关于印发《甲实施办法》的通知", "文号A", body_len=10),
             _c("P_2", "关于印发《甲实施办法》的通知(文号A)", "文号A", body_len=99),
             _c("P_3", "赛罕区市场监管局职称评审通知")]
    kept, dropped = sl.build_shortlist(items)
    assert len(kept) == 1
    assert {d.drop_reason for d in dropped} == {"noise", "dup"}


# ══════════════════════════════════════════════════════════════════
# 以下用例全部来自 2026-09-07 对真实 vault(1653 篇)的实测,不是构造的假设。
# ══════════════════════════════════════════════════════════════════

def test_refuses_hard_merge_when_docno_shared_by_unrelated_titles():
    """实测:文号「发改能源〔2026〕884号」同时挂在成品油调价公告与十五五规划通知上。

    全库这样的组有 31 个(`国办发〔2025〕5号` 横跨 6 份不相干文件)。
    按文号盲目合并会**静默删掉一篇真政策**,比留着重复严重得多。
    """
    items = [
        _c("P_A", "2026年7月31日国内成品油价格调整", "发改能源〔2026〕884号", body_len=300),
        _c("P_B", "关于印发《新型能源体系建设“十五五”规划》的通知", "发改能源〔2026〕884号",
           body_len=9000),
    ]
    kept, dropped = sl.dedupe(items)
    assert {k.policy_id for k in kept} == {"P_A", "P_B"}, "标题核心不相干,不得合并"
    assert dropped == []
    assert all(k.docno_conflict for k in kept), "应打 docno_conflict:至少一方文号是错抓的"


def test_hard_merge_still_works_when_titles_compatible():
    """同一份通知的两次采集:一份标题带文号后缀,一份不带。这才是真重复。"""
    items = [
        _c("P_A", "关于印发《新型能源体系建设“十五五”规划》的通知(发改能源〔2026〕884号)",
           "发改能源〔2026〕884号", body_len=100),
        _c("P_B", "关于印发《新型能源体系建设“十五五”规划》的通知",
           "发改能源〔2026〕884号", body_len=9000),
    ]
    kept, dropped = sl.dedupe(items)
    assert [k.policy_id for k in kept] == ["P_B"]
    assert dropped[0].dup_of == "P_B"


def test_near_dup_catches_containment_across_title_shapes():
    """实测漏网:42 号令的两份采集,一份带书名号一份不带,核心标题是包含关系。

    第二份还带着别人的文号「发改环资〔2026〕698号」(已知的错抓),所以只能靠标题抓。
    """
    items = [
        _c("P_A", "《可再生能源消费最低比重目标和可再生能源电力消纳责任权重制度实施办法》 2026年第42号令",
           "发改环资〔2026〕698号"),
        _c("P_B", "中华人民共和国国家发展和改革委员会 中华人民共和国工业和信息化部 "
                  "中华人民共和国交通运输部令（第42号）可再生能源消费最低比重目标和"
                  "可再生能源电力消纳责任权重制度实施办法", ""),
    ]
    kept, _ = sl.dedupe(items)
    assert len(kept) == 2
    assert kept[0].near_dup_group and kept[0].near_dup_group == kept[1].near_dup_group


def test_containment_does_not_merge_news_item_with_notice():
    """包含规则不得把新闻稿并进公文——文种不同就不比包含。"""
    items = [
        _c("P_A", "《新型能源体系建设“十五五”规划》发布（附全文）", ""),
        _c("P_B", "关于印发《新型能源体系建设“十五五”规划》的通知", ""),
    ]
    kept, _ = sl.dedupe(items)
    assert not (kept[0].near_dup_group and kept[0].near_dup_group == kept[1].near_dup_group)


def test_short_core_title_does_not_trigger_containment():
    """核心标题太短时禁用包含规则,否则「通知」这种会把全库并成一组。"""
    items = [_c("P_A", "关于甲的通知", ""), _c("P_B", "关于甲的通知的补充规定通知", "")]
    kept, _ = sl.dedupe(items)
    assert not (kept[0].near_dup_group and kept[0].near_dup_group == kept[1].near_dup_group)


def test_flags_policy_id_collision():
    """实测:P_2026_NDRC_884 一个 id 挂了两份不同文件。

    id 撞车会让 slate 的 policy_id 指向不确定的一篇,必须标出来逼 MA3 给 title_hint。
    """
    items = [
        _c("P_2026_NDRC_884", "2026年7月31日国内成品油价格调整", ""),
        _c("P_2026_NDRC_884", "关于印发《新型能源体系建设“十五五”规划》的通知", ""),
    ]
    kept, _ = sl.dedupe(items)
    assert all(k.id_collision for k in kept)


def test_sequence_number_paren_is_not_stripped():
    """实测:江苏省成品油价格调整公告（2026年第10/11/12号）是三份不同日期的公告。

    剥掉「（2026年第N号）」就把唯一的区分特征剥掉了,六份会被并成一份。
    真文号带〔〕(如 发改能源〔2026〕884号),序号不带——按这个区分。
    """
    items = [
        _c("P_JS_10", "江苏省成品油价格调整公告（2026年第10号）", "苏发改价格函〔2026〕1号"),
        _c("P_JS_11", "江苏省成品油价格调整公告（2026年第11号）", "苏发改价格函〔2026〕1号"),
        _c("P_JS_12", "江苏省成品油价格调整公告（2026年第12号）", "苏发改价格函〔2026〕1号"),
    ]
    kept, dropped = sl.dedupe(items)
    assert len(kept) == 3, "三份不同日期的调价公告不得合并成一份"
    assert dropped == []


def test_real_docno_paren_is_still_stripped():
    """带〔〕的才是文号,该剥的还得剥——否则同一份通知的两次采集合不起来。"""
    a = sl.normalize_title("关于印发《甲办法》的通知(发改能源〔2026〕884号)")
    assert a == sl.normalize_title("关于印发《甲办法》的通知")


def test_series_key_groups_periodic_price_notices():
    """实测:2026-07 窗口 261 篇 shortlist 里,41 篇(15%)是成品油调价系列。

    各省各期一份、标题只差日期,near-dup 抓不住(核心标题确实不同),但编辑视角上
    它们是**同一个周期性系列**。不删——只打标记,让 MA3 自己决定整体作一条。
    """
    a = sl.series_key("2026年6月18日24时起贵州成品油价格调整")
    b = sl.series_key("2026年7月31日24时起贵州成品油价格调整")
    assert a == b and a


def test_series_key_separates_different_issuers():
    assert sl.series_key("辽宁省成品油价格调整公告（2026年6月18日24时起执行）") != \
           sl.series_key("2026年6月18日24时起贵州成品油价格调整")


def test_build_shortlist_marks_series_of_three_or_more():
    items = [_c(f"P_{i}", f"2026年{i}月4日24时起贵州成品油价格调整") for i in range(1, 5)]
    kept, _ = sl.build_shortlist(items)
    assert all(k.series_group for k in kept)
    assert all(k.series_size == 4 for k in kept)


def test_build_shortlist_does_not_mark_a_pair_as_series():
    """两篇不算系列——门槛设 3,免得把成对出现的正常文件误标。"""
    items = [_c("P_1", "2026年6月4日24时起贵州成品油价格调整"),
             _c("P_2", "2026年7月4日24时起贵州成品油价格调整")]
    kept, _ = sl.build_shortlist(items)
    assert all(not k.series_group for k in kept)


def test_series_does_not_group_unrelated_titles():
    items = [_c("P_1", "关于印发《甲实施办法》的通知"),
             _c("P_2", "关于印发《乙实施办法》的通知"),
             _c("P_3", "关于印发《丙实施办法》的通知")]
    kept, _ = sl.build_shortlist(items)
    assert all(not k.series_group for k in kept), "书名号内容不同就不是同一系列"


def test_same_pid_same_title_is_hard_merged():
    """实测漏网:P_2026_HL_FGW_a770e0cb 两行标题完全相同却都留在了 shortlist。

    两条文号都为空,走不到文号合并那条路;而同 policy_id + 标题相容 = 同一份文件
    采了两次,MA3 会看见同一篇两遍。按 pid 也做一轮合并。
    """
    items = [
        _c("P_HL", "国家发展改革委组织召开视频会议安排部署全国迎峰度夏能源保供工作",
           "", body_len=100),
        _c("P_HL", "国家发展改革委组织召开视频会议安排部署全国迎峰度夏能源保供工作",
           "", body_len=800),
    ]
    kept, dropped = sl.dedupe(items)
    assert len(kept) == 1 and kept[0].body_len == 800
    assert dropped[0].dup_of == "P_HL" and not kept[0].id_collision


def test_same_pid_incompatible_titles_still_flags_collision_and_keeps_both():
    items = [_c("P_X", "江苏省成品油价格调整公告（2026年第7号）", ""),
             _c("P_X", "江苏省成品油价格调整公告（2026年第8号）", "")]
    kept, dropped = sl.dedupe(items)
    assert len(kept) == 2 and dropped == []
    assert all(k.id_collision for k in kept)
