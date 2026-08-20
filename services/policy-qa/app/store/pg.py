"""heng-pg 只读 adapter —— 生产数据面。

数据来自 pipeline 的每日投影(vault → heng-pg),本服务**只读**:连接本身设
read-only,角色也应当是只读角色(双保险)。任何写操作都是纪律事故。

SQL 在 sqlbuild.py(纯函数,单测覆盖结构与参数);本模块只负责连接、执行、
把行映射成契约模型,以及 SQL 表达不了的那部分过滤(business_line)。
"""
from __future__ import annotations

import json
import logging
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
    impact_for_card,
    impact_snippet,
    normalize_themes,
    primary_theme_of,
    sort_key,
    ThemeInfo,
)
from . import sqlbuild

logger = logging.getLogger("policy-qa")

Executor = Callable[[str, dict], list[tuple]]

#: 连接池大小。模型一轮里会并行发多个检索(prompt 明确要求盘点式问题至少扫四轮),
#: 每个同步工具占一个线程,所以池子必须容得下一轮的并行度。heng-pg 是与 heng
#: 共用的库,不能开太大。
DEFAULT_MAXCONN = 8
#: 等一个连接槽位的上限。到点仍拿不到就报错,而不是让请求无限期挂着。
ACQUIRE_TIMEOUT_S = 30
#: 服务端语句超时(毫秒)。慢查询会一直占着槽位,把后面排队的全拖死;
#: 让数据库自己掐断比在客户端等更可靠。
STATEMENT_TIMEOUT_MS = 25000


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
        primary_theme=primary_theme_of(themes),
        impact_snippet=impact_for_card(impact, business_line),
        source_url=_s(source_url),
        caveat=caveat_for(str(pid)),
    )


class PgStore:
    def __init__(
        self,
        dsn: str,
        *,
        executor: Executor | None = None,
        maxconn: int = DEFAULT_MAXCONN,
        acquire_timeout_s: float = ACQUIRE_TIMEOUT_S,
    ):
        self._dsn = dsn
        self._maxconn = max(1, maxconn)
        self._acquire_timeout_s = acquire_timeout_s
        # 把并发查询数卡在池子大小上,多出来的调用在这里**排队等待**。
        # ThreadedConnectionPool 满了是直接抛 PoolError 而不是阻塞,少了这道闸,
        # 模型一轮并行发五六个检索就会有几个当场失败(实测:池 4、并发 7,
        # 五个被取消,整轮回答归零)。
        self._slots = threading.BoundedSemaphore(self._maxconn)
        self._pool = None
        self._executor = executor or self._pooled_query
        if executor is None:
            self._init_pool(self._maxconn)

    def _init_pool(self, maxconn: int) -> None:
        try:
            from psycopg2 import pool as pg_pool
        except ImportError as exc:  # pragma: no cover - 部署环境必然装了
            raise StoreError("psycopg2 未安装,无法使用 pg backend") from exc
        try:
            self._pool = pg_pool.ThreadedConnectionPool(
                1,
                maxconn,
                dsn=self._dsn,
                # 连接级只读:即便误用了可写角色,写操作也会被数据库拒绝。
                # statement_timeout 兜住慢查询,免得它一直占着槽位。
                options=(
                    "-c default_transaction_read_only=on "
                    f"-c statement_timeout={STATEMENT_TIMEOUT_MS}"
                ),
            )
        except Exception as exc:
            # 不把 DSN 带进异常文本——里面有口令
            raise StoreError(f"连接 heng-pg 失败: {type(exc).__name__}") from exc

    def _pooled_query(self, sql: str, params: dict) -> list[tuple]:
        if self._pool is None:  # pragma: no cover
            raise StoreError("连接池未初始化")
        if not self._slots.acquire(timeout=self._acquire_timeout_s):
            raise StoreError(f"等待数据库连接超时({self._acquire_timeout_s}s)")
        conn = None
        try:
            # 槽位已经限住了并发数,getconn 必然拿得到,不会走到 PoolError 那支。
            # ThreadedConnectionPool 自身是线程安全的,这里不需要再加锁。
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
                self._pool.putconn(conn)
            self._slots.release()

    def list_themes(self) -> list[ThemeInfo]:
        """主题登记表。取不到就返回空——主题只是检索的增强维度,
        没有它检索照样能跑,不值得让整个服务起不来。但要在日志里说清楚。"""
        sql, params = sqlbuild.build_themes_sql()
        try:
            rows = self._executor(sql, params)
        except StoreError as exc:
            logger.warning("读不到 KnowledgeTheme 主题登记表,主题检索将不可用: %s", exc)
            return []
        out: list[ThemeInfo] = []
        for tid, name, aliases, count in rows:
            if not tid:
                continue
            if isinstance(aliases, str):
                try:
                    aliases = json.loads(aliases)
                except ValueError:
                    aliases = []
            out.append(
                ThemeInfo(
                    id=str(tid),
                    name=str(name or ""),
                    aliases=[str(a) for a in aliases] if isinstance(aliases, list) else [],
                    count=int(count or 0),
                )
            )
        return out

    def preflight(self) -> None:
        """核对 Policy 表有没有本服务要读的列,缺了就别启动。

        2026-08-18 线上第一课:heng 的 `adcode` 列(2026-06-28 迁移加的)在库里
        不存在,于是**每个带地区词的检索都失败**,而用户只看到一句脱敏的
        "政策库暂时不可用"。健康检查照样绿——它只查 count 和两个 max,
        碰不到那些列。查了几个小时才定位到。

        与其等用户提问才炸,不如启动时就把缺的列名喊出来。
        """
        sql, params = sqlbuild.build_required_columns_sql()
        present = {str(r[0]) for r in self._executor(sql, params)}
        if not present:
            raise StoreError('库里找不到 "Policy" 表,POLICY_QA_PG_DB 是不是指错库了?')
        missing = [c for c in sqlbuild.REQUIRED_POLICY_COLUMNS if c not in present]
        if missing:
            raise StoreError(
                'heng-pg 的 "Policy" 表缺少本服务需要的列: ' + ", ".join(missing) +
                "。多半是这个库落后于 heng 的 Prisma 迁移,或者 POLICY_QA_PG_DB "
                "指向了一份没上迁移链的旧副本。"
            )

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
        theme_id: str | None = None,
        primary_theme_only: bool = False,
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
            theme_id=theme_id,
            primary_theme_only=primary_theme_only,
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
