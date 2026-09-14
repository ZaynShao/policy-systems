"""MA0→MA3 编排:取窗 → 粗筛去重 → web 双保险 → 逐篇判定 → 选目定调。

每步产物落盘,可单独重跑、可人工核对。`--dry-run` 不调 LLM,让没有凭据的人
也能核对取窗与去重结果。

新鲜度闸在**花掉任何 token 之前**执行:上游没重算就中止。月刊一个月一期,
晚一天有人补跑;拿陈数据出一期发给决策层,错误会被当成事实带走。
"""
import argparse
import dataclasses
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

from scripts.common.llm import LLMClient, OpenAICompatClient
from scripts.common.strategy_profile import load_strategy_profile, render_for_monthly
from scripts.l3_monthly import (gap_check, judge, rawtext, shortlist,
                                slate_builder, usage, window)

DEFAULT_PROFILE_REL = "_meta/framework/business_strategy.yaml"


class FreshnessError(RuntimeError):
    """上游数据没准备好。**在花 token 之前**抛,不静默降级。"""


def build_client(provider, model, log_path, usage_path=None):
    """与 l2_themescore.make_client 同范式:openai → OpenAICompat(DeepSeek 走这条)。

    `usage_path` 给了就从 `_post` 这个注入点把 usage 抄一份出来。共用的
    `llm_calls.jsonl` 不记 token,而 v4pro 的账全在推理 token 上,不记就算不出来。
    """
    if provider == "openai":
        post = None
        if usage_path:
            probe = OpenAICompatClient(model=model, log_path=log_path)
            post = usage.UsageRecorder(usage_path).wrap(probe._post)
        return OpenAICompatClient(model=model, log_path=log_path, _post=post)
    return LLMClient(model=model, log_path=log_path)


def _write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def _search_fn(provider):
    if provider != "tavily":
        return lambda query, max_results=5: []
    from scripts.l1_collect.tavily_client import TavilyClient
    return TavilyClient().search


def run(month, vault, state, out, client, dry_run=False, search_fn=None,
        search_provider="none", concurrency=4, max_age_hours=48,
        head_chars=1500, tail_chars=600):
    os.makedirs(out, exist_ok=True)

    probs = window.freshness_problems(vault, state, max_age_hours=max_age_hours)
    if probs:
        raise FreshnessError("上游数据未就绪,本轮中止:" + ";".join(probs))
    profile = load_strategy_profile(os.path.join(vault, DEFAULT_PROFILE_REL))

    cands = window.collect_candidates(vault, month)
    _write_jsonl(os.path.join(out, "candidates.jsonl"),
                 [dataclasses.asdict(c) for c in cands])

    kept, dropped = shortlist.build_shortlist(cands)
    _write_jsonl(os.path.join(out, "shortlist.jsonl"),
                 [dataclasses.asdict(c) for c in kept])
    _write_jsonl(os.path.join(out, "dropped.jsonl"),
                 [dataclasses.asdict(c) for c in dropped])

    warnings = []
    ac = os.path.join(state, "analysis_layer", "nightly", "analysis_context.jsonl")
    if os.path.getsize(ac) == 0:
        warnings.append(
            "analysis_context 为空——本地路线的 stub 属正常,"
            "生产上则意味着 nightly 跑出了空结果,装包的 ac 段会整体降级为「无」")

    report = {"month": month, "warnings": warnings,
              "counts": {"candidates": len(cands), "shortlist": len(kept),
                         "dropped": len(dropped)}}
    if dry_run:
        _write_json(os.path.join(out, "run_report.json"), report)
        return report

    # MA1b:对账要拿**全库**,不是窗口内候选
    vault_index = window.collect_candidates(vault, None)
    gap = gap_check.run_gap_check(profile, month, vault_index,
                                  search_fn or _search_fn(search_provider))
    _write_json(os.path.join(out, "gap_report.json"), gap)
    report["counts"]["gaps"] = gap["summary"]["gaps"]

    profile_text = render_for_monthly(profile)
    terms = judge.absent_terms(profile)

    def _one(c):
        try:
            md = open(c.raw_path, encoding="utf-8", errors="replace").read()
        except OSError as exc:
            return {"policy_id": c.policy_id, "title": c.title, "relevance": "error",
                    "dq": f"RAW 读不出来:{exc}", "level": "",
                    "issue_date_from_body": "", "business_hits": [],
                    "decision_variables_touched": [], "why": ""}
        head = rawtext.excerpt(rawtext.body_of(md), head_chars, tail_chars)
        return judge.judge_one(client, profile_text, terms, c, head)

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        judgments = list(pool.map(_one, kept))
    _write_jsonl(os.path.join(out, "judgments.jsonl"), judgments)
    report["counts"]["judged"] = len(judgments)
    report["counts"]["judge_errors"] = sum(
        1 for j in judgments if j.get("relevance") == "error")

    slate, repairs = slate_builder.build_slate(client, month, judgments)
    _write_json(os.path.join(out, "slate.json"), slate)
    report["slate_repairs"] = repairs
    report["counts"]["selected"] = sum(
        len(v) for v in slate["sections"].values())
    _write_json(os.path.join(out, "run_report.json"), report)
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description="月刊选目链路 MA0→MA3")
    ap.add_argument("--month", required=True, help="YYYY-MM")
    ap.add_argument("--vault", required=True)
    ap.add_argument("--state", required=True)
    ap.add_argument("--out", required=True, help="工作区目录(gitignored)")
    ap.add_argument("--writer-model", default="deepseek-v4-pro")
    ap.add_argument("--writer-provider", default="openai",
                    choices=["anthropic", "openai"])
    ap.add_argument("--search-provider", default="none", choices=["none", "tavily"])
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--dry-run", action="store_true",
                    help="只跑 MA0/MA1,不调 LLM(无凭据也能核对取窗与去重)")
    a = ap.parse_args(argv)

    client = None
    if not a.dry_run:
        client = build_client(a.writer_provider, a.writer_model,
                              os.path.join(a.out, "llm_calls.jsonl"),
                                    usage_path=os.path.join(a.out, "usage.jsonl"))
    try:
        rep = run(month=a.month, vault=a.vault, state=a.state, out=a.out,
                  client=client, dry_run=a.dry_run,
                  search_provider=a.search_provider, concurrency=a.concurrency)
    except (FreshnessError, slate_builder.SlateError) as exc:
        print(f"[l3_monthly] 中止:{exc}", file=sys.stderr)
        return 1
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
