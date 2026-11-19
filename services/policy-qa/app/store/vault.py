"""vault 文件 adapter —— **仅供本地开发**,不部署。

生产数据面是 heng-pg 投影(pg.py)。本 adapter 让开发者在没有数据库的机器上跑通
全链路,因此它的职责不是"尽可能多地暴露 vault 内容",而是**尽可能贴近 pg 的行为**:
契约要求两个 backend 行为一致(HANDOFF §4),不一致会让本地验过的东西上线翻车。

最典型的一处:同一个 pid 对应多份文件时,pg 按 pipelinePid upsert 只存得下一份,
所以这里也必须坍缩成一份,并把撞车数记进 caveat。

只读。任何情况下不写 vault(反污染纪律)。
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import yaml

from . import (
    DEFAULT_LIMIT,
    DEFAULT_MAX_CHARS,
    CommentaryItem,
    PolicyCard,
    PolicyDetail,
    RelationEdge,
    SearchResult,
    StoreError,
    caveat_for,
    clamp_limit,
    impact_match,
    impact_snippet,
    importance_at_least,
    importance_from_score,
    keyword_match,
    normalize_themes,
    sort_key,
    tokenize_keyword,
)

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n?", re.S)
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _read_text(path: Path) -> str:
    """统一读法:UTF-8,坏字节替换而不是抛错。

    库内有一批 RAW 是 UTF-8 被 latin-1 解码过的残留,原样读进来交给模型判断,
    不在这里"修复"——修复属于 pipeline 的 cleanup pass,不是消费端该干的事。
    """
    return path.read_text(encoding="utf-8", errors="replace")


def split_frontmatter(text: str) -> tuple[dict, str]:
    """切出 frontmatter 与正文。只认文件开头的 --- 块。"""
    m = _FRONTMATTER.match(text)
    if not m:
        return {}, text
    try:
        loaded = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return {}, text[m.end():]
    fm = loaded if isinstance(loaded, dict) else {}
    return fm, text[m.end():]


def _issuer_to_str(raw: Any) -> str:
    """issuer 在 vault 里是数组(实测 400/400),pg 侧是拼好的字符串。这里对齐 pg。"""
    if isinstance(raw, list):
        return "、".join(str(x).strip() for x in raw if str(x).strip())
    return str(raw).strip() if raw else ""


class VaultStore:
    """启动时全量扫描建内存索引(约 1500 篇,秒级)。之后全内存查询。"""

    def __init__(self, vault_dir: str | os.PathLike):
        self.root = Path(vault_dir)
        if not self.root.is_dir():
            raise StoreError(f"vault 目录不存在: {vault_dir}")
        self._policies: dict[str, dict] = {}
        self._relations: dict[str, list[RelationEdge]] = {}
        self._commentary: dict[str, list[CommentaryItem]] = {}
        self.skipped_no_date = 0
        self.skipped_no_id = 0
        self.collisions: dict[str, int] = {}
        self._load()

    # --- 建索引 -------------------------------------------------------------

    def _load(self) -> None:
        self._load_policies()
        self._load_business_views()
        self._load_relations()
        self._load_commentary()

    def _load_policies(self) -> None:
        pol_dir = self.root / "0_raw" / "policies"
        if not pol_dir.is_dir():
            raise StoreError(f"vault 缺少 0_raw/policies: {pol_dir}")

        # pid → 候选文件列表。_archive/ 与 _duplicates/ 是 0_raw 下的兄弟目录,
        # 只 glob policies/*.md 天然排除,不需要额外过滤。
        candidates: dict[str, list[dict]] = {}
        for path in sorted(pol_dir.glob("*.md")):
            fm, body = split_frontmatter(_read_text(path))
            pid = str(fm.get("id") or "").strip()
            if not pid:
                self.skipped_no_id += 1
                continue
            date = str(fm.get("date") or "").strip()
            if not _ISO_DATE.match(date):
                # 与 pipeline 侧一致:坏 date 不写假数据,直接不收
                self.skipped_no_date += 1
                continue
            region = fm.get("region") or {}
            if not isinstance(region, dict):
                region = {}
            provenance = fm.get("provenance") or {}
            if not isinstance(provenance, dict):
                provenance = {}
            candidates.setdefault(pid, []).append(
                {
                    "pid": pid,
                    "title": str(fm.get("title") or path.stem),
                    "doc_number": (str(fm.get("official_number") or "").strip() or None),
                    "issuer": _issuer_to_str(fm.get("issuer")),
                    "issue_date": date,
                    "region": (str(region.get("name") or "").strip() or None),
                    "level": (str(region.get("level") or "").strip() or None),
                    "adcode": (str(region.get("code") or "").strip() or None),
                    "source_url": (str(provenance.get("url") or "").strip() or None),
                    "content": body,
                    "filename": path.name,
                    "importance": "INFO",
                    "themes": [],
                    "scores": None,
                    "impact": None,
                }
            )

        for pid, rows in candidates.items():
            if len(rows) > 1:
                self.collisions[pid] = len(rows)
                # pg 侧是 upsert 顺序决定的"最后一个赢",不可复现;这里取确定性规则:
                # 发布日期最新者,同日按文件名排序。保证同一 vault 每次跑结果一致。
                rows = sorted(rows, key=lambda r: (r["issue_date"], r["filename"]), reverse=True)
            self._policies[pid] = rows[0]

    def _load_business_views(self) -> None:
        bv_dir = self.root / "_meta" / "business_view"
        if not bv_dir.is_dir():
            return
        for pid, row in self._policies.items():
            path = bv_dir / f"{pid}.yaml"
            if not path.is_file():
                continue  # 缺 business_view 不丢政策,只是没有内部评估
            try:
                bv = yaml.safe_load(_read_text(path))
            except yaml.YAMLError:
                continue
            if not isinstance(bv, dict):
                continue
            row["importance"] = importance_from_score(bv.get("重要性"))
            row["themes"] = normalize_themes(bv.get("themes"))
            scores = bv.get("scores")
            if isinstance(scores, dict):
                row["scores"] = {
                    str(k): int(v) for k, v in scores.items() if isinstance(v, (int, float))
                }
            impact = bv.get("影响分析")
            if isinstance(impact, dict):
                cleaned = {
                    str(k): str(v).strip()
                    for k, v in impact.items()
                    if v is not None and str(v).strip()
                }
                row["impact"] = cleaned or None

    def _load_relations(self) -> None:
        rel_dir = self.root / "1_extracted" / "relations"
        if not rel_dir.is_dir():
            return
        seen: set[tuple[str, str, str]] = set()
        # 只取目录下的 *.jsonl;_index_by_policy/ 是子目录(反链页),不是关系数据
        for path in sorted(rel_dir.glob("*.jsonl")):
            for line in _read_text(path).split("\n"):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                frm = str(rec.get("from") or "").strip()
                to = str(rec.get("to") or "").strip()
                rel = str(rec.get("rel") or "").strip()
                if not (frm and to and rel):
                    continue
                key = (frm, to, rel)
                if key in seen:
                    continue
                seen.add(key)
                evidence = rec.get("evidence")
                conf = rec.get("confidence")
                conf = float(conf) if isinstance(conf, (int, float)) else None
                self._relations.setdefault(frm, []).append(
                    RelationEdge(
                        direction="outbound",
                        relation_type=rel,
                        other_pid=to,
                        other_title=self._title_of(to),
                        evidence=evidence,
                        confidence=conf,
                    )
                )
                self._relations.setdefault(to, []).append(
                    RelationEdge(
                        direction="inbound",
                        relation_type=rel,
                        other_pid=frm,
                        other_title=self._title_of(frm),
                        evidence=evidence,
                        confidence=conf,
                    )
                )

    def _load_commentary(self) -> None:
        path = self.root / "1_extracted" / "commentary_signals.jsonl"
        if not path.is_file():
            return
        for line in _read_text(path).split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            cid = str(rec.get("commentary_id") or "").strip()
            if not cid:
                continue
            conf = rec.get("confidence")
            item = CommentaryItem(
                commentary_id=cid,
                title=rec.get("title"),
                signal_role=rec.get("signal_role"),
                evidence=rec.get("evidence"),
                source_account=rec.get("source_account"),
                business_tag=rec.get("business_tag"),
                confidence=float(conf) if isinstance(conf, (int, float)) else None,
            )
            for pid in rec.get("related_policy_ids") or []:
                # 软引用:悬挂 pid 原样收下,查询时自然查不到,不在这里丢
                self._commentary.setdefault(str(pid), []).append(item)

    def _title_of(self, pid: str) -> str | None:
        row = self._policies.get(pid)
        return row["title"] if row else None

    # --- 查询 ---------------------------------------------------------------

    def _to_card(self, row: dict, business_line: str | None) -> PolicyCard:
        return PolicyCard(
            pid=row["pid"],
            title=row["title"],
            doc_number=row["doc_number"],
            issuer=row["issuer"],
            issue_date=row["issue_date"],
            region=row["region"],
            level=row["level"],
            importance=row["importance"],
            themes=row["themes"],
            impact_snippet=impact_snippet(row["impact"], business_line),
            source_url=row["source_url"],
            caveat=caveat_for(row["pid"], self.collisions.get(row["pid"])),
        )

    def search_policies(
        self,
        *,
        keyword: str | None = None,
        business_line: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        region_keyword: str | None = None,
        min_importance: str | None = None,
        issuer_keyword: str | None = None,
        order: str = "date_desc",
        limit: int = DEFAULT_LIMIT,
    ) -> SearchResult:
        tokens = tokenize_keyword(keyword)
        matched: list[PolicyCard] = []
        for row in self._policies.values():
            if tokens and not keyword_match(row["title"], row["doc_number"], tokens):
                continue
            if date_from and row["issue_date"] < date_from:
                continue
            if date_to and row["issue_date"] > date_to:
                continue
            if region_keyword and not (
                region_keyword in (row["region"] or "")
                or region_keyword in (row["adcode"] or "")
                or region_keyword == (row["level"] or "")
            ):
                continue
            # issuer 字段全库 38% 为空(其中 57% 的机关只写在标题里),只匹配 issuer 列
            # 会静默漏掉三分之一的库,模型据此可能得出"库里没有财政部的文件"这种
            # 假的全称否定。故 issuer 与 title 任一命中即算。
            if issuer_keyword and not (
                issuer_keyword.lower() in (row["issuer"] or "").lower()
                or issuer_keyword.lower() in (row["title"] or "").lower()
            ):
                continue
            if not importance_at_least(row["importance"], min_importance):
                continue
            if not impact_match(row["impact"], business_line):
                continue
            matched.append(self._to_card(row, business_line))

        matched.sort(key=sort_key(order), reverse=True)
        return SearchResult(total=len(matched), rows=matched[: clamp_limit(limit)])

    def get_policy(
        self, pid: str, *, max_chars: int = DEFAULT_MAX_CHARS, offset: int = 0
    ) -> PolicyDetail | None:
        row = self._policies.get(pid)
        if row is None:
            return None
        content = row["content"]
        offset = max(0, int(offset))
        card = self._to_card(row, None)
        return PolicyDetail(
            **card.model_dump(),
            content=content[offset : offset + max(1, int(max_chars))],
            content_total_chars=len(content),
            content_offset=offset,
            scores=row["scores"],
            impact=row["impact"],
            synced_at=None,  # vault 是文件,没有投影时间
        )

    def get_relations(self, pid: str) -> list[RelationEdge]:
        return list(self._relations.get(pid, []))

    def get_commentary(self, pid: str) -> list[CommentaryItem]:
        return list(self._commentary.get(pid, []))

    def stats(self) -> dict:
        dates = [r["issue_date"] for r in self._policies.values() if r["issue_date"]]
        return {
            "policies": len(self._policies),
            "latest_issue_date": max(dates) if dates else None,
            "latest_synced_at": None,
            "skipped_no_date": self.skipped_no_date,
            "skipped_no_id": self.skipped_no_id,
            "collided_pids": len(self.collisions),
        }
