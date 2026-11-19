"""新华云 CMS 空壳页的数据源兜底。

国家能源局 policy/{zxwj,tz,gg}.htm 都是这种页:HTML 只有一个空 <ul>,条目由 JS
从同目录的 ds_<id>.json 拉。firecrawl 带 waitFor 4 秒也只拿得到挂载前的骨架
(2026-09-07 服务器实测 1958 字 / 7 链接 / 0 条目),所以必须直接取 JSON。
"""
import json
import pytest

from scripts.l1_collect import step2_scan
from scripts.l1_collect.channel_catalog import Channel, ChannelStatus

SHELL = (
    '<html><body>'
    '<a href="/index.htm" data="datasource:b4ae3efbfd3f4ffcb1bb211fa7bdb92d"'
    ' datatype="ds" preview="ds_">首页</a>'
    '<ul id="showData0" data="datasource:40d365c13659452aa06cdb7268d6192e"'
    ' datatype="ds" preview="ds_"></ul>'
    '</body></html>'
)
PAGE = "https://www.nea.gov.cn/policy/zxwj.htm"


class _Resp:
    def __init__(self, payload, status=200):
        self._p, self.status_code = payload, status

    def json(self):
        return self._p


def _stub(monkeypatch, payload, seen=None):
    def fake_get(url, **kw):
        if seen is not None:
            seen.append(url)
        return _Resp(payload)
    monkeypatch.setattr(step2_scan.requests, "get", fake_get)


def test_只认容器上的数据源_不认导航链接上的(monkeypatch):
    seen = []
    _stub(monkeypatch, {"datasource": []}, seen)
    step2_scan._xinhua_datasource_html(PAGE, SHELL)
    assert len(seen) == 1
    assert "ds_40d365c13659452aa06cdb7268d6192e.json" in seen[0]
    assert "b4ae3efbfd" not in seen[0]  # <a> 上那个是"首页"导航,不是列表数据


def test_拼回的html能被主流程当普通列表页解析(monkeypatch):
    _stub(monkeypatch, {"datasource": [
        {"showTitle": "关于公开征求《供电企业信息公开实施办法》（修订稿）意见的通知",
         "publishTime": "2026-08-31 10:00:00",
         "publishUrl": "../20260831/c1aa140dcdbe40e481ded09e4e6fda98/c.html"},
    ]})
    html = step2_scan._xinhua_datasource_html(PAGE, SHELL)
    ch = Channel(city="国家能源局", province="国家", level="国家", city_code="000000",
                 channel_type="能源局", root_domain="nea.gov.cn", list_url=PAGE,
                 source="manual", status=ChannelStatus.验证)
    rows = step2_scan._extract_list_items(html, PAGE, ch)
    assert len(rows) == 1
    assert rows[0].date_hint == "2026-08-31"          # 日期能被 _DATE_RE 读到
    assert rows[0].url.startswith("https://www.nea.gov.cn/20260831/")  # 相对路径已还原
    assert "供电企业信息公开实施办法" in rows[0].title


def test_showTitle_里嵌着a标签时剥干净(monkeypatch):
    """CMS 的 Link 型条目会把整个 <a> 塞进 showTitle。"""
    _stub(monkeypatch, {"datasource": [
        {"showTitle": "<a href='http://www.nea.gov.cn/x/c.html'>中国氢能发展报告（2026）</a>",
         "publishTime": "2026-08-11 09:00:00",
         "publishUrl": "http://www.nea.gov.cn/20260811/x/c.html"},
    ]})
    html = step2_scan._xinhua_datasource_html(PAGE, SHELL)
    assert "中国氢能发展报告（2026）" in html
    assert "<a href='http" not in html   # 嵌套标签没漏进标题


def test_按上限截断(monkeypatch):
    """接上渠道的第一晚不该去抓上千篇历史件——补历史要另外有意做。"""
    _stub(monkeypatch, {"datasource": [
        {"showTitle": f"通知{i}", "publishTime": "2026-09-04 08:00:00",
         "publishUrl": f"../2026/{i}/c.html"} for i in range(500)
    ]})
    html = step2_scan._xinhua_datasource_html(PAGE, SHELL)
    assert html.count("<li>") == step2_scan.DATASOURCE_MAX_ITEMS


def test_没有数据源标记时返回空_不影响普通页(monkeypatch):
    _stub(monkeypatch, {"datasource": [{"showTitle": "x", "publishUrl": "y"}]})
    assert step2_scan._xinhua_datasource_html(PAGE, "<html><body><p>普通页</p></body></html>") == ""


def test_取数失败不抛_退回上层继续走firecrawl(monkeypatch):
    def boom(url, **kw):
        raise RuntimeError("network down")
    monkeypatch.setattr(step2_scan.requests, "get", boom)
    assert step2_scan._xinhua_datasource_html(PAGE, SHELL) == ""
