"""heng-pg 只读 adapter —— 生产数据面。

数据来自 pipeline 的每日投影(vault → heng-pg),本服务**只读**:连接本身设
read-only,角色也应当是只读角色(双保险)。任何写操作都是纪律事故。

SQL 在 sqlbuild.py(纯函数,单测覆盖结构与参数);本模块只负责连接、执行、
把行映射成契约模型,以及 SQL 表达不了的那部分过滤(business_line)。
"""
from __future__ import annotations

import json
import threading
from typing import Any, Callable, Sequence

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
    normalize_themes,
    sort_key,
)
from . import sqlbuild

Executor = Callable[[str, dict], list[tuple]]


def _s(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def row_to_card(row: Sequence, business_line: str | None) -> PolicyCard:
    """SEARCH_COLUMNS 顺序 → PolicyCard。列序改了这里必须同步改。"""
    (
        pid,
        title,
        doc_number,
        issuer,
        issue_date,
        region,
        level,
        importance,
        themes,
        impact,
        source_url,
    ) = row[:11]
    return PolicyCard(
        pid=str(pid),
        title=str(title or ""),
        doc_number=_s(doc_number),
        issuer=str(issuer or ""),
        issue_date=str(issue_date or "")[:10],
        region=_s(region),
        level=_s(level),
        importance=str(importance or "INFO"),  # type: ignore[arg-type]
        themes=normalize_themes(themes),
        impact_snippet=impact_snippet(impact, business_line),
        source_url=_s(source_url),
        caveat=caveat_for(str(pid)),
    )


class PgStore:
    def __init__(self, dsn: str, *, executor: Executor | None = None, maxconn: int = 4):
        self._dsn = dsn
        self._lock = threading.Lock()
        self._pool = None
        self._executor = executor or self._pooled_query
        if executor is None:
            self._init_pool(maxconn)

    def _init_pool(self, maxconn: int) -> None:
        try:
            from psycopg2 import pool as pg_pool
        except ImportError as exc:  # pragma: no cover - 部署环境必然装了
            raise StoreError("psycopg2 未安装,无法使用 pg backend") from exc
        try:
            self._pool = pg_pool.ThreadedConnectionPool(
                1,
                max(1, maxconn),
                dsn=self._dsn,
                # 连接级只读:即便误用了可写角色,写操作也会被数据库拒绝
                options="-c default_transaction_read_only=on",
            )
        except Exception as exc:
            # 不把 DSN 带进异常文本——里面有口令
            raise StoreError(f"连接 heng-pg 失败: {type(exc).__name__}") from exc

    def _pooled_query(self, sql: str, params: dict) -> list[tuple]:
        if self._pool is None:  # pragma: no cover
            raise StoreError("连接池未初始化")
        conn = None
        try:
            with self._lock:
                conn = self._pool.getconn()
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall() if cur.description else []
            conn.rollback()  # 只读事务,显式结束
            return rows
        except StoreError:
            raise
        except Exception as exc:
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass
            raise StoreError(f"查询失败: {type(exc).__name__}") from exc
        finally:
            if conn is not None:
                with self._lock:
                    self._pool.putconn(conn)

    # --- 查询 ---------------------------------------------------------------

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
        sql, params = sqlbuild.build_search_sql(
            keyword=keyword,
            date_from=date_from,
            date_to=date_to,
            region_keyword=region_keyword,
            min_importance=min_importance,
            issuer_keyword=issuer_keyword,
        )
        rows = self._executor(sql, params)
        # business_line 过滤只能在这里做:pipelineImpact 是存 JSON 的 text 列,
        # 解析失败要静默跳过,不能让整条查询失败(与 vault adapter 同一纯函数)
        cards = [
            row_to_card(r, business_line) for r in rows if impact_match(r[9], business_line)
        ]
        cards.sort(key=sort_key(order), reverse=True)
        return SearchResult(total=len(cards), rows=cards[: clamp_limit(limit)])

    def get_policy(
        self, pid: str, *, max_chars: int = DEFAULT_MAX_CHARS, offset: int = 0
    ) -> PolicyDetail | None:
        sql, params = sqlbuild.build_get_policy_sql(pid)
        rows = self._executor(sql, params)
        if not rows:
            return None
        row = rows[0]
        card = row_to_card(row, None)
        content = str(row[11] or "")
        scores_raw = row[12]
        if isinstance(scores_raw, str):
            try:
                scores_raw = json.loads(scores_raw)
            except ValueError:
                scores_raw = None
        scores = (
            {str(k): int(v) for k, v in scores_raw.items() if isinstance(v, (int, float))}
            if isinstance(scores_raw, dict)
            else None
        )
        impact_map = None
        from . import parse_impact

        parsed = parse_impact(row[9])
        if parsed:
            impact_map = {k: v for k, v in parsed.items() if str(v).strip()} or None
        offset = max(0, int(offset))
        return PolicyDetail(
            **card.model_dump(),
            content=content[offset : offset + max(1, int(max_chars))],
            content_total_chars=len(content),
            content_offset=offset,
            scores=scores,
            impact=impact_map,
            synced_at=_s(row[13]),
        )

    def get_relations(self, pid: str) -> list[RelationEdge]:
        sql, params = sqlbuild.build_relations_sql(pid)
        out: list[RelationEdge] = []
        for direction, rel_type, other_pid, other_title, evidence, confidence in self._executor(
            sql, params
        ):
            if not other_pid:
                continue
            out.append(
                RelationEdge(
                    direction=direction,  # type: ignore[arg-type]
                    relation_type=str(rel_type),
                    other_pid=str(other_pid),
                    other_title=_s(other_title),
                    evidence=_s(evidence),
                    confidence=float(confidence) if confidence is not None else None,
                )
            )
        return out

    def get_commentary(self, pid: str) -> list[CommentaryItem]:
        sql, params = sqlbuild.build_commentary_sql(pid)
        out: list[CommentaryItem] = []
        for cid, title, role, evidence, account, tag, confidence in self._executor(sql, params):
            out.append(
                CommentaryItem(
                    commentary_id=str(cid),
                    title=_s(title),
                    signal_role=_s(role),
                    evidence=_s(evidence),
                    source_account=_s(account),
                    business_tag=_s(tag),
                    confidence=float(confidence) if confidence is not None else None,
                )
            )
        return out

    def stats(self) -> dict:
        sql, params = sqlbuild.build_stats_sql()
        rows = self._executor(sql, params)
        if not rows:
            return {"policies": 0, "latest_issue_date": None, "latest_synced_at": None}
        n, latest_issue, latest_sync = rows[0][:3]
        return {
            "policies": int(n or 0),
            "latest_issue_date": str(latest_issue)[:10] if latest_issue else None,
            "latest_synced_at": _s(latest_sync),
        }

    def close(self) -> None:
        if self._pool is not None:
            self._pool.closeall()
            self._pool = None
