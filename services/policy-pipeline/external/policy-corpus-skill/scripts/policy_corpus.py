#!/usr/bin/env python3
"""政策原文库客户端。只读，只走 HTTP，仅依赖标准库。

env:
  POLICY_CORPUS_API    接口地址，如 https://<host>/policy-corpus
  POLICY_CORPUS_TOKEN  访问令牌
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 30


def _call(path: str, params: dict | None = None) -> dict:
    base = (os.getenv("POLICY_CORPUS_API") or "").rstrip("/")
    token = os.getenv("POLICY_CORPUS_TOKEN") or ""
    if not base:
        raise SystemExit("未配置 POLICY_CORPUS_API —— 请向政策库维护团队申请接口地址与令牌")
    if not token:
        raise SystemExit("未配置 POLICY_CORPUS_TOKEN —— 请向政策库维护团队申请访问令牌")

    query = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v not in ("", None)})
    url = f"{base}{path}" + (f"?{query}" if query else "")
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        try:
            detail = json.loads(body).get("detail") or body
        except json.JSONDecodeError:
            detail = body
        if e.code == 401:
            raise SystemExit("令牌无效或已过期，请联系政策库维护团队")
        if e.code == 404:
            raise SystemExit("未找到该政策")
        if e.code == 429:
            retry = e.headers.get("Retry-After", "")
            hint = f"（{retry} 秒后可重试）" if retry else ""
            raise SystemExit(f"已触发访问频率限制{hint}：{detail}")
        if e.code == 503:
            raise SystemExit("政策库暂时不可用，请稍后重试")
        raise SystemExit(f"接口返回 {e.code}: {detail}")
    except urllib.error.URLError as e:
        raise SystemExit(f"无法连接接口: {e.reason}")


def _out(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def cmd_search(a: argparse.Namespace) -> int:
    _out(_call("/v1/policies", {
        "q": a.q, "region": a.region, "level": a.level,
        "date_from": a.date_from, "date_to": a.date_to,
        "page": a.page, "page_size": a.page_size,
    }))
    return 0


def cmd_get(a: argparse.Namespace) -> int:
    rec = _call(f"/v1/policies/{urllib.parse.quote(a.policy_id, safe='')}")
    if a.body_only:
        print(rec.get("body", ""))
    else:
        _out(rec)
    return 0


def cmd_manifest(_: argparse.Namespace) -> int:
    _out(_call("/v1/manifest"))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="政策原文库客户端（只读）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="检索政策，不返回正文")
    s.add_argument("--q", default="", help="匹配标题 / 文号 / 发文机关（不搜正文）")
    s.add_argument("--region", default="", help="地区名，子串匹配")
    s.add_argument("--level", default="", help="层级，精确匹配：国 / 省 / 市")
    s.add_argument("--date-from", dest="date_from", default="", help="发文日期下界 YYYY-MM-DD")
    s.add_argument("--date-to", dest="date_to", default="", help="发文日期上界 YYYY-MM-DD")
    s.add_argument("--page", type=int, default=1)
    s.add_argument("--page-size", dest="page_size", type=int, default=20, help="上限 100")
    s.set_defaults(func=cmd_search)

    g = sub.add_parser("get", help="按 id 取政策原文")
    g.add_argument("policy_id")
    g.add_argument("--body-only", action="store_true", help="只输出正文纯文本")
    g.set_defaults(func=cmd_get)

    m = sub.add_parser("manifest", help="语料篇数 / 生成时间 / 内容指纹")
    m.set_defaults(func=cmd_manifest)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
