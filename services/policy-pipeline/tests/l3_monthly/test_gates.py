"""MA6 的两道纯代码门:D 门(风格)与业务口径门。

两道门都不花 LLM 钱——正则与词表能判死的事,没有理由让模型来判。
规则来自实际执行过的 D 门清单,并在两份已交付终稿(2026-05 / 2026-06)上实测过
**零误报**;下面的干净样例即照终稿的真实形态构造。
"""
from scripts.l3_monthly import gates as G

CLEAN = """能 源 政 策 月 刊 2026 年 6 月

一、概述

本月国家级政策以"十五五"规划为主线。

与公司三大业务的关联速判:

加油业务 — 本月没有直接命中汽油零售的国家级政策。

充电业务 — 信号密集且可操作。四川把公共充电站列为重点民生保障行业。

电力业务 — 制度确定性显著增强。42 号令把消纳责任权重升为规章。

二、政策速览

打分 | 日期 | 文件 | 发文机关
5分 | 2026-06-13 | 新型能源体系建设"十五五"规划(发改能源〔2026〕884号) | 国家发展改革委

三、政策详情

(一)新型能源体系建设"十五五"规划

【政策信息】国务院同意,发改委与能源局联合印发。

【政策解读】承接 2024 年《能源法》的工作基础,把总量目标落到分领域。

【重点关注内容】三件事值得盯:一是投资盘子,二是市场建设,三是新型储能定位。

决策建议:

充电业务:以规划为纲梳理充电基建在"十五五"的投资定位。[B 研究/跟进]

电力业务:优先解析电力市场建设章节,校准业务节奏。[A 趁早行动]

附录:6 月战略基调与数据信号

(一)国家能源局有关负责同志答记者问(2026-06-02)
"""

PROFILE = {
    "businesses": [
        {"id": "fuel", "zh": "加油", "portfolio_status": {}},
        {"id": "charging", "zh": "充电", "portfolio_status": {}},
        {"id": "power", "zh": "电力", "portfolio_status": {
            "电力现货": {"status": "主战场"},
            "储能": {"status": "hold", "note": "因政策性峰谷价差要停而暂停"},
            "虚拟电厂聚合入市": {"status": "在建能力"},
        }},
    ],
    "not_business_lines": [
        {"id": "intl", "zh": "国际化(墨西哥充电)"},
        {"id": "swap", "zh": "换电"},
    ],
    "open_questions": [{"id": "Q5", "topic": "V2G / 车网互动"}],
}


# ── D 门:干净稿不报 ────────────────────────────────────────────
def test_clean_draft_has_no_style_violation():
    """照两份已交付终稿的真实形态构造;19 条禁项在真终稿上实测 0 命中。"""
    assert G.check_style(CLEAN) == []


# ── D 门:逐条禁项 ──────────────────────────────────────────────
def _one(text):
    return {v["rule"] for v in G.check_style(text)}


def test_flags_machine_tokens():
    assert "D-TOKEN" in _one("本条依据 P_2026_SC_884 判定。")
    assert "D-TOKEN" in _one("主题归入 green_power_trading_theme。")
    assert "D-TOKEN" in _one("D3 维度得分偏低。")
    assert "D-TOKEN" in _one("由 MiniMax 模型抽取。")
    assert "D-TOKEN" in _one("字段 sanitized_from 已清洗。")


def test_flags_star_rating():
    assert "D-STAR" in _one("重要性 ⭐5")


def test_flags_corner_quotes():
    assert "D-QUOTE" in _one("发布了「新型能源体系规划」。")


def test_flags_markdown_emphasis_and_syntax():
    assert "D-EMPH" in _one("投资达 **20 万亿元**。")
    assert "D-MD" in _one("## 数据覆盖说明")
    assert "D-MD" in _one("详见 https://www.ndrc.gov.cn/x")


def test_flags_machine_relation_table():
    assert "D-RELTABLE" in _one("| 之前文件 | 关系 | 说明 |")
    assert "D-RELTABLE" in _one("该文属上位法承接,与前件构成同期双联。")


def test_flags_process_meta():
    assert "D-META" in _one("本期覆盖国家级 3 项、省级 5 项。")
    assert "D-META" in _one("「业界观点」段落本期尚未覆盖,暂行跳过,下期补充。")
    assert "D-META" in _one("**参考来源**:见文末链接")


def test_flags_ai_tone_and_rhetoric():
    assert "D-TONE" in _one("综上所述,本月政策密度上升。")
    assert "D-TONE" in _one("值得注意的是,该文影响面较广。")
    assert "D-TONE" in _one("这不是一次普通调整,而是制度层面的重构。")


def test_flags_retired_content_pollution():
    """乡村能源是已退役原型的污染,历史上真被抄进过月刊。"""
    assert "D-POLLUTE" in _one("乡村能源建设也值得关注。")
    assert "D-POLLUTE" in _one("新能源汽车下乡活动持续推进。")


def test_flags_appendix_machine_numbering():
    assert "D-APPX" in _one("A1 · 国家能源局答记者问")


def test_flags_bad_action_tag():
    assert "D-TAG" in _one("充电业务:尽快排查。[E 立即执行]")
    assert "D-TAG" not in _one("充电业务:尽快排查。[A 趁早行动]")


def test_flags_headline_with_interpunct():
    assert "D-HEAD" in _one("能源政策月刊 · 2026 年 6 月\n\n一、概述\n")


def test_violation_carries_line_and_quote():
    v = G.check_style("正常一行\n重要性 ⭐5\n")[0]
    assert v["line"] == 2 and "⭐" in v["quote"] and v["severity"]


# ── 业务口径门 ──────────────────────────────────────────────────
def test_clean_draft_passes_business_gate():
    assert G.check_business(CLEAN, PROFILE) == []


def test_flags_business_line_outside_the_profile():
    t = "储能业务:加快独立储能项目布局。"
    assert "B-LINE" in {v["rule"] for v in G.check_business(t, PROFILE)}


def test_flags_retired_line_used_as_business():
    t = "换电业务:在大湾区继续扩站。"
    assert "B-LINE" in {v["rule"] for v in G.check_business(t, PROFILE)}


def test_flags_hold_item_in_business_label():
    """实测:2026-06 终稿写「电力业务(储能·V2G·电力交易)」。

    按 2026-08-31 生效的画像,储能是 hold、V2G 是材料空白(Q5 明写现行把 V2G
    列进电力线无依据)。口径变了,标签就得跟着变——这正是本门要抓的漂移。
    """
    t = "电力业务(储能·V2G·电力交易) — 制度确定性增强。"
    rules = {v["rule"] for v in G.check_business(t, PROFILE)}
    assert "B-LABEL" in rules


def test_subject_matter_mentions_are_not_flagged():
    """换电/储能/虚拟电厂在正文里是**议题**不是业务线。

    2026-06 终稿里换电出现 11 次、虚拟电厂 12 次、储能 7 次,见词就抓等于全篇误报。
    """
    t = ("充电业务 — 武汉充换电分时电价临时调整,午间低谷移至 14:00。\n"
         "电力业务 — 山西分布式管理新政以承载力红黄绿分区引导配储,"
         "分布式加储能的配套机会继续累积;虚拟电厂运营商身份获得明确。")
    assert G.check_business(t, PROFILE) == []


def test_flags_negative_business_entry():
    """「X 业务:不相关」是机器味,决策建议只列有实话可说的业务。"""
    t = "加油业务:与本文无关。"
    assert "B-NEGATIVE" in {v["rule"] for v in G.check_business(t, PROFILE)}


# ── 合并入口 ────────────────────────────────────────────────────
def test_run_gates_merges_and_sorts_by_severity():
    t = "能源政策月刊 · 2026 年 6 月\n重要性 ⭐5\n储能业务:加快布局。\n"
    vs = G.run_gates(t, PROFILE)
    assert {v["gate"] for v in vs} == {"D", "B"}
    order = [G.SEVERITY_ORDER.index(v["severity"]) for v in vs]
    assert order == sorted(order), "最重的排前面,人先看见要紧的"
