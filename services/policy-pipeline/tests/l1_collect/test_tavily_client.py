"""TavilyClient.search():返回带标题的结果。

渠道发现只要 URL,所以原来只有 search_urls();月刊的缺口对账要拿标题去跟 vault 比,
URL 比不出来。新增 search() 返回完整条目,search_urls() 改为它的薄封装,行为不变。
"""
from scripts.l1_collect.tavily_client import TavilyClient


def _fake_post(payload_seen):
    def post(url, payload, api_key):
        payload_seen.append((url, payload, api_key))
        return {"results": [
            {"url": "https://a.example/1", "title": "甲通知", "content": "正文甲"},
            {"url": "https://b.example/2", "title": "乙公告", "content": "正文乙"},
            {"title": "无URL的条目"},
        ]}
    return post


def test_search_returns_title_url_content():
    seen = []
    c = TavilyClient(api_key="k", _post=_fake_post(seen))
    got = c.search("查询", max_results=3)
    assert [g["title"] for g in got] == ["甲通知", "乙公告"], "无 URL 的条目应被丢弃"
    assert got[0]["url"] == "https://a.example/1"
    assert got[0]["content"] == "正文甲"
    assert seen[0][1]["query"] == "查询" and seen[0][1]["max_results"] == 3


def test_search_urls_unchanged_behaviour():
    c = TavilyClient(api_key="k", _post=_fake_post([]))
    assert c.search_urls("查询") == ["https://a.example/1", "https://b.example/2"]


def test_search_without_key_returns_empty():
    assert TavilyClient(api_key="", _post=_fake_post([])).search("x") == []


def test_search_swallows_transport_error():
    def boom(*a, **k):
        raise RuntimeError("network down")
    assert TavilyClient(api_key="k", _post=boom).search("x") == []
