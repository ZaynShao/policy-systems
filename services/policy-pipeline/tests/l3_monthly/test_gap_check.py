"""MA1b:web 双保险的缺口对账。

用例里的政策全部来自 2026-09-07 对真实 vault + 真实 web 搜索的实测:
- 发改能源〔2026〕1067号《可再生能源发展"十五五"规划》—— 库里有
- 国家税务总局公告 2026 年第 11 号,成品油零售「交易即开票」—— **库里没有**
  (`grep 交易即开票` 零命中;命中加油线 F02/F05 两条 high 信号)
- 《电力安全生产"十五五"行动计划》(2026-08-07 国家能源局)—— **库里没有**
"""
from scripts.l3_monthly import gap_check as gc
from scripts.l3_monthly.models import Candidate


PROFILE = {
    "signals": [
        {"id": "F02", "business": "fuel", "weight": "high",
         "what": "成品油消费税稽查、发票与票据管理政策"},
        {"id": "F05", "business": "fuel", "weight": "high",
         "what": "预付卡/加油卡/电子券/第三方支付监管规则"},
        {"id": "P14", "business": "power", "weight": "suppress",
         "what": "新型电力系统建设的宏观框架、指导意见"},
        {"id": "P12", "business": "power", "weight": "medium",
         "what": "省间/区域电力交易、输电权交易"},
    ]
}


def _cand(pid, title, docno=""):
    return Candidate(policy_id=pid, title=title, official_number=docno,
                     date="2026-07-01", date_missing=False, raw_path="/x.md",
                     body_len=500, region_name="")


VAULT = [
    _cand("P_1067", "关于印发《可再生能源发展“十五五”规划》的通知(发改能源〔2026〕1067号)",
          "发改能源〔2026〕1067号"),
    _cand("P_884", "国家发展改革委 国家能源局关于印发《新型能源体系建设“十五五”规划》的通知",
          "发改能源〔2026〕884号"),
]


# ── 查询构造 ────────────────────────────────────────────────────
def test_build_queries_only_uses_high_weight_signals():
    qs = gc.build_queries(PROFILE, "2026-07")
    assert {q["signal_id"] for q in qs} == {"F02", "F05"}, "medium/suppress 不该烧搜索额度"


def test_build_queries_embeds_month():
    qs = gc.build_queries(PROFILE, "2026-07")
    assert all("2026年7月" in q["query"] for q in qs)


def test_build_queries_empty_profile_is_not_an_error():
    assert gc.build_queries({}, "2026-07") == []


# ── 文号抽取 ────────────────────────────────────────────────────
def test_extract_doc_no_bracket_form():
    assert gc.extract_doc_no("关于印发…的通知(发改能源〔2026〕1067号)") == "发改能源〔2026〕1067号"


def test_extract_doc_no_annual_number_form():
    """税务总局那类公告用「2026年第11号」,不带〔〕。"""
    got = gc.extract_doc_no("国家税务总局公告2026年第11号 成品油零售领域全面推广交易即开票")
    assert "2026年第11号" in got


def test_extract_doc_no_returns_empty_when_absent():
    assert gc.extract_doc_no("某地开展专项检查") == ""


# ── 对账 ────────────────────────────────────────────────────────
def test_match_hits_by_official_number():
    item = {"title": "可再生能源发展十五五规划印发", "doc_no": "发改能源〔2026〕1067号"}
    assert gc.match_in_vault(item, VAULT) == "P_1067"


def test_match_hits_by_core_title_even_when_docno_missing():
    item = {"title": "《新型能源体系建设“十五五”规划》全文发布", "doc_no": ""}
    assert gc.match_in_vault(item, VAULT) == "P_884"


def test_match_misses_the_real_tax_bureau_gap():
    """实测缺口:成品油「交易即开票」。库里全是商务局的零售许可/年检,税务口一条没有。"""
    item = {"title": "国家税务总局关于在成品油零售领域全面推广“交易即开票”有关事项的公告",
            "doc_no": "国家税务总局公告2026年第11号"}
    assert gc.match_in_vault(item, VAULT) is None


# ── 报告 ────────────────────────────────────────────────────────
def _fake_search(results_by_query):
    def search(query, max_results=5):
        return results_by_query.get(query, [])
    return search


def test_run_gap_check_separates_gaps_from_hits():
    qs = gc.build_queries(PROFILE, "2026-07")
    hits = {
        qs[0]["query"]: [
            {"title": "国家税务总局关于在成品油零售领域全面推广“交易即开票”有关事项的公告"
                      "(国家税务总局公告2026年第11号)",
             "url": "https://chinatax.gov.cn/x", "content": ""},
            {"title": "关于印发《可再生能源发展“十五五”规划》的通知(发改能源〔2026〕1067号)",
             "url": "https://ndrc.gov.cn/y", "content": ""},
        ],
        qs[1]["query"]: [],
    }
    rep = gc.run_gap_check(PROFILE, "2026-07", VAULT, _fake_search(hits))
    assert rep["month"] == "2026-07"
    assert rep["summary"]["found"] == 2
    assert rep["summary"]["gaps"] == 1
    gaps = [i for i in rep["items"] if not i["in_vault"]]
    assert "交易即开票" in gaps[0]["title"]
    assert gaps[0]["signal_id"] == "F02"
    assert gaps[0]["url"] == "https://chinatax.gov.cn/x"


def test_run_gap_check_dedupes_same_item_across_queries():
    qs = gc.build_queries(PROFILE, "2026-07")
    same = {"title": "国家税务总局关于在成品油零售领域全面推广“交易即开票”有关事项的公告",
            "url": "https://chinatax.gov.cn/x", "content": ""}
    rep = gc.run_gap_check(PROFILE, "2026-07", VAULT,
                           _fake_search({qs[0]["query"]: [same], qs[1]["query"]: [same]}))
    assert rep["summary"]["found"] == 1, "同一条被两个信号搜到,只应记一次"
    assert set(rep["items"][0]["signal_id"].split(",")) == {"F02", "F05"}


def test_run_gap_check_without_search_provider_is_not_a_crash():
    """无 key / --search-provider none:返回空报告并标明原因,不阻塞出刊。"""
    rep = gc.run_gap_check(PROFILE, "2026-07", VAULT, lambda q, max_results=5: [])
    assert rep["summary"] == {"queries": 2, "found": 0, "gaps": 0}
    assert rep["items"] == []


def test_gap_check_matches_against_whole_vault_not_just_window():
    """实测假缺口:42 号令的 frontmatter 日期是 2026-06,跑 2026-08 时落在窗口外。

    「这份文件在不在库里」是**全库问题**,不是窗口问题。拿窗口内候选去对账,
    会把库里明明有、只是日期在窗外的文件报成缺口——每期都产生一批假缺口,
    人看几次就不看了,双保险就废了。
    """
    out_of_window = _cand(
        "P_42LING",
        "《可再生能源消费最低比重目标和可再生能源电力消纳责任权重制度实施办法》 2026年第42号令",
        "")
    out_of_window.date = "2026-06-12"          # 跑 2026-08 时不在 [07,08,09] 窗口内
    item = {"title": "可再生能源消费最低比重目标和可再生能源电力消纳责任权重制度实施办法",
            "doc_no": ""}
    assert gc.match_in_vault(item, [out_of_window]) == "P_42LING"

    PROFILE_ONE = {"signals": [{"id": "F02", "weight": "high", "what": "成品油发票"}]}
    q = gc.build_queries(PROFILE_ONE, "2026-08")[0]["query"]
    rep = gc.run_gap_check(
        PROFILE_ONE, "2026-08", [out_of_window],
        lambda query, max_results=5: [{"title": item["title"], "url": "u", "content": ""}]
        if query == q else [])
    assert rep["summary"]["gaps"] == 0, "库里有就不是缺口,无论 frontmatter 日期在不在窗内"
