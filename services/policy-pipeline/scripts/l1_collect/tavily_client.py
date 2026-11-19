"""Tavily 搜索 REST 客户端(urllib,无新依赖)。用于渠道发现:搜机构政策列表页。"""
from __future__ import annotations
import json
import os
from typing import Callable, Optional

TAVILY_URL = "https://api.tavily.com/search"


class TavilyClient:
    def __init__(self, api_key: Optional[str] = None, _post: Optional[Callable] = None):
        self.api_key = api_key if api_key is not None else os.environ.get("TAVILY_API_KEY")
        self._post = _post or self._http_post

    def search(self, query: str, max_results: int = 5) -> list:
        """返回 [{url, title, content}]。渠道发现只要 URL,月刊的缺口对账要标题去跟
        vault 比——URL 比不出来,所以这里给完整条目。无 key 或传输出错一律返回空:
        搜索是双保险,挂了不该把出刊也带挂。"""
        if not self.api_key:
            return []
        try:
            data = self._post(TAVILY_URL, {
                "query": query, "max_results": max_results,
                "search_depth": "basic",
            }, self.api_key)
        except Exception:
            return []
        return [{"url": r["url"], "title": r.get("title") or "",
                 "content": r.get("content") or ""}
                for r in (data.get("results") or []) if r.get("url")]

    def search_urls(self, query: str, max_results: int = 5) -> list:
        return [r["url"] for r in self.search(query, max_results)]

    @staticmethod
    def _http_post(url: str, payload: dict, api_key: str) -> dict:
        import urllib.request
        body = json.dumps({**payload, "api_key": api_key}).encode("utf-8")
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
