from scripts.l3_render import pack_lib as pl


def test_parse_frontmatter_basic():
    md = (
        "---\nid: P_2026_X\ntitle: 测试政策\n"
        "official_number: 发改能源〔2026〕688号\ndate: '2026-05-20'\n"
        "region:\n  level: 省\n  code: '330000'\n  name: 国家发展改革委\n"
        "provenance:\n  url: http://x\n---\n## 政策原文\n正文"
    )
    fm = pl.parse_frontmatter(md)
    assert fm["id"] == "P_2026_X"
    assert fm["official_number"] == "发改能源〔2026〕688号"
    assert fm["date"] == "2026-05-20"
    # region_name must be ONLY the name line, not everything after (catches greedy .*$ bug)
    assert fm["region_name"] == "国家发展改革委"


def test_classify_level_national_by_issuer_over_region():
    assert pl.classify_level("国家发展改革委", "发改能源〔2026〕688号", "省") == "国家"
    assert pl.classify_level("国家能源局", "", "市") == "国家"


def test_classify_level_local():
    assert pl.classify_level("四川省发展和改革委员会", "川发改能源〔2026〕184号", "省") == "地方"


def test_is_noise():
    assert pl.is_noise("赛罕区市场监管局开展六一儿童节前专项检查") is True
    assert pl.is_noise("关于有序推动多用户绿电直连发展有关事项的通知") is False


def test_resolve_relations_to_titles():
    edges = [
        {"from": "P_A", "to": "P_B", "rel": "cites_basis", "evidence": "x"},
        {"from": "P_C", "to": "P_A", "rel": "supersedes", "evidence": "y"},
    ]
    id2title = {"P_A": "甲政策", "P_B": "乙政策", "P_C": "丙政策"}
    out = pl.resolve_relations("P_A", edges, id2title)
    rels = {(r["rel"], r["dir"], r["other"]) for r in out}
    assert ("cites_basis", "out", "乙政策") in rels
    assert ("supersedes", "in", "丙政策") in rels


def test_pick_record_disambiguates_by_title_hint():
    recs = [
        ("/a.md", {"title": "福建省商务厅等9部门关于以旧换新"}, "body-a"),
        ("/b.md", {"title": "商务部等8部门办公厅关于以旧换新"}, "body-b"),
    ]
    chosen = pl.pick_record(recs, title_hint="商务部等8部门")
    assert chosen[0] == "/b.md"


def test_body_date_hints_extracts_signoff_dates():
    body = "...本通知自2026年7月1日起执行。\n浙江省发展和改革委员会\n2026年5月28日"
    hints = pl.body_date_hints(body)
    assert "2026年5月28日" in hints


# ── 采集页面 chrome 清理(2026-09-07 实测:RAW 里 23% 字符是 URL/图片) ──
def test_strip_web_chrome_drops_images_keeps_link_text():
    from scripts.l3_render import pack_lib as pl
    t = "![](http://a.gov.cn/x.jpg)[新闻中心](https://a.gov.cn/xw/)政策通知"
    assert pl.strip_web_chrome(t) == "新闻中心政策通知"


def test_strip_web_chrome_marks_bare_url():
    """裸 URL 换成标记而不是删掉:删掉会让前后两句悄悄接在一起。"""
    from scripts.l3_render import pack_lib as pl
    out = pl.strip_web_chrome("详见 http://a.gov.cn/notice.htm 办理")
    assert "http" not in out and pl.LINK_MARK in out and out.startswith("详见 ")


def test_strip_web_chrome_leaves_policy_text_alone():
    from scripts.l3_render import pack_lib as pl
    t = "第一条 为规范本市充电设施建设,依据《条例》第 12 条,制定本办法。"
    assert pl.strip_web_chrome(t) == t
