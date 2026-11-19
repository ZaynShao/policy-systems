"""政策原文对外只读接口。薄封装 —— 逻辑全在 corpus / tokens / ratelimit。

对外只有三个 GET，没有任何写入口。
数据源是 public_export 产出的语料包，**本进程不挂载 vault**，
所以派生产出物在部署形态上就不可达。

令牌独立签发（scripts/corpus_service/issue_token.py），不走平台账号体系。
每个令牌两条限流账：整体 rpm + 每日取全文次数 —— 后者是反爬的主闸，
语料共 1240 篇，不限的话一个循环就能拖走全文。

env（红线：凭据全 env，零硬编码）：
  POLICY_CORPUS_BUNDLE    语料包目录，必填
  POLICY_CORPUS_REGISTRY  令牌注册表 JSON 路径，必填
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status

from scripts.corpus_service.corpus import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Corpus
from scripts.corpus_service.ratelimit import Rule, SlidingWindow
from scripts.corpus_service.tokens import TokenRecord, TokenRegistry

BUNDLE = Path(os.getenv("POLICY_CORPUS_BUNDLE", "")).expanduser()
REGISTRY = Path(os.getenv("POLICY_CORPUS_REGISTRY", "")).expanduser()

app = FastAPI(
    title="政策原文对外接口",
    version="1.1.0",
    description="只读。仅提供政策原文与其出处，不含任何分析产出物。",
)

_corpus: Corpus | None = None
_registry: TokenRegistry | None = None
_limiter = SlidingWindow()


def get_corpus() -> Corpus:
    global _corpus
    if _corpus is None:
        if not BUNDLE.is_dir():
            raise HTTPException(status_code=503, detail="语料包未就绪")
        _corpus = Corpus.load(BUNDLE)
    return _corpus


def get_registry() -> TokenRegistry:
    global _registry
    if _registry is None:
        _registry = TokenRegistry.load(REGISTRY)
    return _registry


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="未授权",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_token(request: Request) -> TokenRecord:
    """校验 Bearer 令牌并施加整体 rpm 限流。"""
    scheme, _, presented = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer":
        raise _unauthorized()

    record = get_registry().authenticate(presented, now=time.time())
    if record is None:
        raise _unauthorized()

    decision = _limiter.check(f"{record.key}:rpm", Rule(record.rpm, 60), now=time.time())
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"请求过于频繁，上限 {record.rpm} 次/分钟",
            headers={"Retry-After": str(decision.retry_after)},
        )
    return record


def spend_full_text_quota(record: TokenRecord) -> None:
    """取全文单独记一笔日配额 —— 反爬主闸。"""
    decision = _limiter.check(
        f"{record.key}:fulltext", Rule(record.full_text_per_day, 86400), now=time.time()
    )
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"今日取全文已达上限 {record.full_text_per_day} 篇，请明日再试或联系政策库维护团队",
            headers={"Retry-After": str(decision.retry_after)},
        )


@app.get("/v1/manifest", summary="语料版本信息")
def manifest(
    _: TokenRecord = Depends(require_token),
    c: Corpus = Depends(get_corpus),
) -> dict:
    """篇数、生成时间、内容指纹。指纹未变说明语料没更新。"""
    return c.manifest


@app.get("/v1/policies", summary="检索政策（不返回正文）")
def list_policies(
    q: str = Query("", max_length=200, description="匹配标题 / 文号 / 发文机关"),
    region: str = Query("", max_length=100, description="地区名，子串匹配"),
    level: str = Query("", max_length=20, description="层级，精确匹配，如 国 / 省 / 市"),
    date_from: str = Query("", max_length=10, description="发文日期下界 YYYY-MM-DD"),
    date_to: str = Query("", max_length=10, description="发文日期上界 YYYY-MM-DD"),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    _: TokenRecord = Depends(require_token),
    c: Corpus = Depends(get_corpus),
) -> dict:
    return c.search(q=q, region=region, level=level, date_from=date_from,
                    date_to=date_to, page=page, page_size=page_size)


@app.get("/v1/policies/{policy_id}", summary="取单篇政策原文")
def get_policy(
    policy_id: str,
    response: Response,
    record: TokenRecord = Depends(require_token),
    c: Corpus = Depends(get_corpus),
) -> dict:
    """返回完整记录，正文为采集时的原样内容（含原站导航等噪音）。

    计入每日取全文配额；不存在的 id 不扣配额。
    """
    rec = c.get(policy_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="政策不存在")
    spend_full_text_quota(record)
    response.headers["X-FullText-Quota"] = str(record.full_text_per_day)
    return rec
