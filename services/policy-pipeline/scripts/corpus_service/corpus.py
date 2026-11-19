"""对外语料的检索核心。纯函数 + 一个只读容器，无 Web 依赖，可独立重测。

数据来自 public_export 产出的语料包（policies.jsonl / index.json /
manifest.json）。本模块**不接触 vault**，也无从接触派生层。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20


def _norm(s: Any) -> str:
    return str(s or "").strip().lower()


def _issuer_text(rec: Mapping[str, Any]) -> str:
    issuer = rec.get("issuer")
    if isinstance(issuer, (list, tuple)):
        return " ".join(str(x) for x in issuer)
    return str(issuer or "")


def matches(rec: Mapping[str, Any], *, q: str = "", region: str = "",
            level: str = "", date_from: str = "", date_to: str = "") -> bool:
    """单条记录是否命中筛选条件。空条件恒真。

    q 命中标题 / 文号 / 发文机关（不搜正文：正文含大量网页噪音，
    全文搜出来的多是导航栏，噪音大于价值）。
    """
    if q:
        haystack = " ".join((
            str(rec.get("title") or ""),
            str(rec.get("official_number") or ""),
            _issuer_text(rec),
        )).lower()
        if _norm(q) not in haystack:
            return False
    reg = rec.get("region") or {}
    if region and _norm(region) not in _norm(reg.get("name")):
        return False
    if level and _norm(level) != _norm(reg.get("level")):
        return False
    date = str(rec.get("date") or "")
    if date_from and date < date_from:
        return False
    if date_to and date > date_to:
        return False
    return True


def paginate(items: Sequence[Any], page: int, page_size: int) -> tuple[list[Any], int]:
    """返回 (当页数据, 总数)。page 从 1 起；越界返回空页而非报错。"""
    page = max(1, int(page or 1))
    page_size = min(MAX_PAGE_SIZE, max(1, int(page_size or DEFAULT_PAGE_SIZE)))
    total = len(items)
    start = (page - 1) * page_size
    return list(items[start:start + page_size]), total


def sort_key(rec: Mapping[str, Any]) -> tuple:
    """默认排序：发文日期倒序，同日按 id 稳定排列。"""
    return (str(rec.get("date") or ""), str(rec.get("id") or ""))


@dataclass(frozen=True)
class Corpus:
    """加载好的对外语料。构造后只读。"""

    records: dict[str, dict]
    index: list[dict]
    manifest: dict

    @classmethod
    def load(cls, bundle: Path) -> "Corpus":
        records: dict[str, dict] = {}
        with (bundle / "policies.jsonl").open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rec = json.loads(line)
                    records[rec["id"]] = rec
        index = json.loads((bundle / "index.json").read_text(encoding="utf-8"))
        manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
        # manifest 里的 excluded 是内部排除原因，不对外
        manifest = {k: v for k, v in manifest.items() if k != "excluded"}
        return cls(records=records, index=sorted(index, key=sort_key, reverse=True),
                   manifest=manifest)

    def search(self, *, q: str = "", region: str = "", level: str = "",
               date_from: str = "", date_to: str = "",
               page: int = 1, page_size: int = DEFAULT_PAGE_SIZE) -> dict:
        hits: Iterable[dict] = (
            r for r in self.index
            if matches(r, q=q, region=region, level=level,
                       date_from=date_from, date_to=date_to)
        )
        items, total = paginate(list(hits), page, page_size)
        return {"total": total, "page": max(1, int(page or 1)),
                "page_size": min(MAX_PAGE_SIZE, max(1, int(page_size or DEFAULT_PAGE_SIZE))),
                "items": items}

    def get(self, policy_id: str) -> dict | None:
        """按 id 取全文（含原样正文）。不存在返回 None。"""
        return self.records.get(policy_id)
