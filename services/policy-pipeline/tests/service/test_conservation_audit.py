"""守恒巡检。

四段各有一个能核对的等式;差额只能靠显式豁免归零。
最要紧的一条是 stale_channels 看日期而不是看有没有产出——见该函数的注释。
"""
from datetime import date

import pytest

from scripts.service import conservation_audit as ca


def _p(pid, title="", d="2026-09-01", host="ndrc.gov.cn"):
    return {"pid": pid, "title": title, "date": d, "host": host}


class _Ch:
    def __init__(self, domain, level, status="验证", city="X"):
        self.root_domain, self.level, self.status, self.city = domain, level, status, city


# ---- ① 派生守恒 ----

def test_有原文没标签的被报出来():
    got = ca.diff_derivation([_p("P_A"), _p("P_B")], {"P_A"}, set())
    assert [x["pid"] for x in got] == ["P_B"]


def test_豁免的不报():
    assert ca.diff_derivation([_p("P_B")], set(), {"P_B"}) == []


def test_按发文日倒序_新的先看():
    got = ca.diff_derivation([_p("P_OLD", d="2024-01-01"), _p("P_NEW", d="2026-09-01")],
                             set(), set())
    assert [x["pid"] for x in got] == ["P_NEW", "P_OLD"]


# ---- ③ 采集守恒 ----

def test_解读反复引用而库里没有的被报出来():
    import collections
    m = collections.Counter({"售电公司管理办法": 9, "煤炭工业发展十五五规划": 4})
    got = ca.coverage_gaps(m, ["关于印发《煤炭工业发展“十五五”规划》的通知"], 3, set())
    assert got == [("售电公司管理办法", 9)]


def test_标题比对忽略括号与引号():
    """《售电公司管理办法（公开征求意见稿）》与《售电公司管理办法》是同一件。"""
    import collections
    m = collections.Counter({"售电公司管理办法": 9})
    have = ["国家发展改革委关于印发《售电公司管理办法（公开征求意见稿）》的通知"]
    assert ca.coverage_gaps(m, have, 3, set()) == []


def test_低于阈值不报():
    import collections
    assert ca.coverage_gaps(collections.Counter({"某某管理办法": 2}), [], 5, set()) == []


# ---- ④ 渠道时效 ----

def test_渠道有产出但全是老件_照样报():
    """这条是本脚本存在的理由。

    国家能源局 nea.gov.cn/zcfb 在册九个月,每次扫描稳定回 29 条、全过关键词门,
    任何"这个渠道还在出东西吗"的活性检查都是绿的——29 条全是 2017 年的存档。
    只有"最近一件是什么时候的"能把它认出来。
    """
    named, _ = ca.stale_channels([_Ch("nea.gov.cn", "国家")],
                                 {"nea.gov.cn": "2017-10-11"},
                                 date(2026, 9, 7), set())
    assert len(named) == 1
    assert named[0]["last"] == "2017-10-11"
    assert named[0]["age"] > 3000


def test_渠道从未出过件也报():
    named, _ = ca.stale_channels([_Ch("mot.gov.cn", "国家")], {}, date(2026, 9, 7), set())
    assert named[0]["last"] == "从未" and named[0]["age"] is None


def test_新鲜的渠道不报():
    named, _ = ca.stale_channels([_Ch("ndrc.gov.cn", "国家")],
                                 {"ndrc.gov.cn": "2026-09-01"}, date(2026, 9, 7), set())
    assert named == []


def test_省级阈值比国家级宽():
    ls = {"a.gov.cn": "2026-07-01", "b.gov.cn": "2026-07-01"}
    named, _ = ca.stale_channels([_Ch("a.gov.cn", "国家"), _Ch("b.gov.cn", "省")],
                                 ls, date(2026, 9, 7), set())
    assert [x["domain"] for x in named] == ["a.gov.cn"]


def test_市级只计数不点名():
    """市级占目录八成且本来就稀疏,逐条点名会淹掉真信号。"""
    named, n = ca.stale_channels([_Ch("c1.gov.cn", "市"), _Ch("c2.gov.cn", "市")],
                                 {"c1.gov.cn": "2026-09-01"}, date(2026, 9, 7), set())
    assert named == [] and n == 1


def test_候选渠道不参与():
    named, _ = ca.stale_channels([_Ch("x.gov.cn", "国家", status="候选")], {},
                                 date(2026, 9, 7), set())
    assert named == []


def test_渠道豁免生效():
    named, _ = ca.stale_channels([_Ch("pbc.gov.cn", "国家")], {}, date(2026, 9, 7),
                                 {"pbc.gov.cn"})
    assert named == []


# ---- 报告与判定 ----

def _result(**kw):
    base = {"checked_at": "2026-09-07T10:00:00", "derivation": [], "projection": None,
            "coverage": [], "stale": [], "city_suspect": 0, "min_mentions": 5}
    base.update(kw)
    return base


def test_全绿时不算违规():
    assert ca.has_violation(_result()) is False


def test_任一段有差额都算违规():
    assert ca.has_violation(_result(derivation=[_p("P_X")])) is True
    assert ca.has_violation(_result(coverage=[("x", 9)])) is True
    assert ca.has_violation(_result(stale=[{"domain": "d"}])) is True
    assert ca.has_violation(_result(projection={"bv": 10, "pg": 8, "diff": 2})) is True


def test_投影相等不算违规():
    assert ca.has_violation(_result(projection={"bv": 10, "pg": 10, "diff": 0})) is False


def test_报告里带清单且长清单被截断():
    d = [_p(f"P_{i}", title="标题", d="2026-09-01") for i in range(20)]
    txt = ca.render(_result(derivation=d), sample=3)
    assert "20 篇" in txt and "另 17 篇" in txt


def test_豁免表缺文件不算错():
    assert ca.load_exemptions("/nonexistent/audit_exemptions.yaml") == {}


def test_域名按后缀匹配_不是等值比对():
    """目录写 root_domain=ndrc.gov.cn,政策 provenance 里是 www.ndrc.gov.cn。

    等值比对会让每条渠道都判成"从未出件"——巡检第一版就是这样,52 条渠道
    全部点名,一份全是假阳性的告警和没告警一样没用。
    """
    ls = {"www.ndrc.gov.cn": "2026-09-01", "zfxxgk.nea.gov.cn": "2026-08-20"}
    assert ca.last_seen_for("ndrc.gov.cn", ls) == "2026-09-01"
    assert ca.last_seen_for("nea.gov.cn", ls) == "2026-08-20"
    assert ca.last_seen_for("mot.gov.cn", ls) == ""


def test_后缀匹配不误伤相似域名():
    assert ca.last_seen_for("ea.gov.cn", {"www.nea.gov.cn": "2026-09-01"}) == ""


def test_取子域里最新的一件():
    ls = {"www.nea.gov.cn": "2026-05-01", "zfxxgk.nea.gov.cn": "2026-09-04"}
    assert ca.last_seen_for("nea.gov.cn", ls) == "2026-09-04"


def test_渠道新鲜判定走后缀匹配():
    named, _ = ca.stale_channels([_Ch("ndrc.gov.cn", "国家")],
                                 {"www.ndrc.gov.cn": "2026-09-01"},
                                 date(2026, 9, 7), set())
    assert named == []


def test_停更与从未出件分开且停更排在前():
    """两者是不同的故障:停更 = 本来好的坏了(今天就要看);
    从未出件 = 一开始就没配对(存量欠账)。混在一张单子里,前者会被后者淹掉
    ——初版就是这样,3 条真停更被 45 条从未出件盖住。"""
    chans = [_Ch("nea.gov.cn", "国家", city="国家能源局"),
             _Ch("mot.gov.cn", "国家", city="交通运输部")]
    named, _ = ca.stale_channels(chans, {"www.nea.gov.cn": "2026-05-28"},
                                 date(2026, 9, 7), set())
    assert [x["kind"] for x in named] == ["停更", "从未出件"]
    assert named[0]["domain"] == "nea.gov.cn" and named[0]["age"] == 102


def test_报告把两类分别计数():
    stale = [{"kind": "停更", "level": "国家", "city": "能源局", "domain": "nea.gov.cn",
              "last": "2026-05-28", "age": 102, "limit": 21},
             {"kind": "从未出件", "level": "国家", "city": "交通部", "domain": "mot.gov.cn",
              "last": "从未", "age": None, "limit": 21}]
    txt = ca.render(_result(stale=stale))
    assert "渠道停更 1 条" in txt and "从未出件 1 条" in txt
    assert "距今 102 天" in txt


def test_国家级停更排在省级前面():
    """同样是停更,一条 1811 天的省级市监渠道不该把国家能源局挤出可见范围。"""
    chans = [_Ch("scjg.hebei.gov.cn", "省", city="河北市监"),
             _Ch("nea.gov.cn", "国家", city="国家能源局")]
    named, _ = ca.stale_channels(chans, {"scjg.hebei.gov.cn": "2021-09-22",
                                         "www.nea.gov.cn": "2026-05-28"},
                                 date(2026, 9, 7), set())
    assert [x["city"] for x in named] == ["国家能源局", "河北市监"]
