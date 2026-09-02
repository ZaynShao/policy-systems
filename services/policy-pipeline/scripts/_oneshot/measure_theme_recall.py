"""量一量 L2 pass1「挂不挂主题」这个二元判断到底准不准。

## 为什么要量

2026-08-31 核查发现,全库 1618 篇里 **53% 是零主题、零影响分析**,
而且这个比例是模型决定的:2026-06-06 那批(MiniMax-M2.7)挂主题率 68%,
06-10 起那批(deepseek-v4-flash)只有 24%,8/21 之后新入库的更是只剩 15%。
控制住主题之后两个模型的 D1 几乎一致(4.17 vs 4.45)——**分裂全部发生在这个二元判断上**。

零主题的政策在 QA 里基本等于不可见:没有主题、没有影响分析,只能靠关键词或
机关扫描碰到,而 planner 被明写「优先用主题」。

但 53% 零主题**未必是错的**:抽样眼看,大部分确实该零(公示、讲堂、调价公告、
「技能加油站」这种关键词误命中)。也确实有明显漏网,比如
`【天津市电动汽车充电设施服务能力质效双增实施方案】` 判了 D1=0。

**漏了多少,现在纯属未知。** 不量就重打分,可能花掉 11.5M token 换来一套同样漏的分。

## 这个脚本做什么

分层抽样 + 独立复判 + 混淆矩阵。**只读,不写 vault。**

分层维度:是否已挂主题 × 产出模型。两个方向一起量——
只量漏检(该挂没挂)不够,还得量误挂(不该挂却挂了),
否则「放宽阈值」这个动作没法判断是赚是亏。

复判用的是 pass1 的**原提示词**(同一份 registry、同一套挂载规则),
只换模型。这样测出来的是「模型差异」,不是「提示词差异」。

## 用法(在服务器上跑,API key 在 /etc/policy-pipeline/models.env)

    set -a; . /etc/policy-pipeline/models.env; set +a
    python3 -m scripts._oneshot.measure_theme_recall \
        --vault /vault --n 100 --judge-model <一个比 deepseek-v4-flash 强的模型>

结果**逐条**写 state/theme_recall/detail.jsonl。中途崩了加 `--resume` 接着跑
(seed 必须与上一轮一致),已完成的 pid 会跳过,只补没跑完的。

成本提示:100 篇约 0.7M **输入** token。judge 用推理模型(deepseek-reasoner 之类)
时还会产生大量思考 token,实际花费明显高于这个数;非推理模型则接近这个数。
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import random
import sys
from pathlib import Path

import yaml

from scripts.common.llm import OpenAICompatClient
from scripts.l2_themescore.generator import parse_json_block
from scripts.l1_audit.corpus import load_policies
from scripts.l2_themescore import prompts
from scripts.l2_themescore.generator import gen_pass1
from scripts.l2_themescore.theme_registry import ThemeRegistry, canonicalize_theme_ids

DEFAULT_REGISTRY = "_meta/themes_registry.yaml"
DEFAULT_SCORING = "_meta/framework/scoring.yaml"

#: 复判模型不得等于被复判的产出模型。同模型自评不是复判,是复读。
#: L2 自己的 run_2b.warn_if_same_model 只是 warn;这里测的就是模型差异,所以直接中止。
SELF_JUDGE_ABORT = (
    "复判模型 {judge} 与库里 {n} 篇的产出模型相同。同模型自评测不出模型差异,"
    "换一个更强的模型再跑(样本里出现的产出模型:{models})。"
)


def load_done_rows(detail_path: Path) -> list[dict]:
    """读回已经落盘的复判结果,用于断点续跑。

    为什么需要:一轮复判是真金白银,而 2026-09-02 那次跑到第 91/100 篇崩掉,
    前 90 篇全部作废。**注意 judge_calls.jsonl 救不了场**——scripts/common/llm.py
    的 _log_call 只记 prompt_sha 和 output_chars,不存提示词也不存输出。
    所以只能靠这个脚本自己边跑边写。
    """
    if not detail_path.is_file():
        return []
    rows = []
    for line in detail_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue          # 崩在写一半时最后一行可能截断,丢掉即可
        if row.get("pid"):
            rows.append(row)
    return rows


def load_stored(vault: str) -> dict[str, dict]:
    """读现有 business_view。只取判断这次测量需要的字段。"""
    out = {}
    for path in sorted((Path(vault) / "_meta" / "business_view").glob("*.yaml")):
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        pid = doc.get("pid")
        if not pid:
            continue
        out[pid] = {
            "themes": list(doc.get("themes") or []),
            "primary_theme": doc.get("primary_theme") or "",
            "D1": (doc.get("scores") or {}).get("D1"),
            "model": doc.get("extracted_model") or "?",
            "strategy": doc.get("extracted_strategy"),
        }
    return out


def stratified_sample(stored: dict[str, dict], n: int, seed: int) -> list[str]:
    """按(是否已挂主题 × 产出模型)分层,层内等额抽。

    等额而非按比例:少数层(比如挂了主题的 deepseek 那批只占全库 11%)
    按比例抽会只抽到个位数,置信区间宽到没法用。等额抽再在汇总时加权。
    """
    strata: dict[tuple, list[str]] = collections.defaultdict(list)
    for pid, row in stored.items():
        strata[(bool(row["themes"]), row["model"])].append(pid)
    per = max(1, n // max(1, len(strata)))
    rng = random.Random(seed)
    picked: list[str] = []
    for key in sorted(strata):
        pool = sorted(strata[key])
        rng.shuffle(pool)
        picked.extend(pool[:per])
    return picked


#: 复判成功率下限。低于这个数,剩下的样本已经不成其为一个分层样本了——
#: 失败往往不是随机的(长文超时、编码损伤解析失败),按它算出来的比例会系统性偏。
MIN_SUCCESS_RATE = 0.8


def assert_enough_judged(judged: int, planned: int, state) -> None:
    """自检③:失败率过高时中止,不出报告。

    半份数据配一个看起来正常的百分比,比没有数据危险——
    它会被当成结论拿去决定要不要花 11.5M token 重打全库。
    """
    if planned and judged < MIN_SUCCESS_RATE * planned:
        raise SystemExit(
            f"仅 {judged}/{planned} 篇复判成功"
            f"(<{MIN_SUCCESS_RATE:.0%}),结果不可信;查 {state}/judge_calls.jsonl")


def main(argv=None, _client=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", required=True)
    ap.add_argument("--state", default="state/theme_recall")
    ap.add_argument("--n", type=int, default=100, help="总抽样量(会按层等额分配)")
    ap.add_argument("--seed", type=int, default=20260831, help="固定种子,便于复跑对齐")
    ap.add_argument("--judge-model", required=True)
    ap.add_argument("--resume", action="store_true",
                    help="接着上一轮跑:已在 detail.jsonl 里的 pid 跳过,只补没跑完的。"
                         "样本由 --seed 决定,续跑时 seed 必须与上一轮一致")
    ap.add_argument("--judge-base-url", default=os.environ.get("OPENAI_BASE_URL") or "https://api.deepseek.com")
    args = ap.parse_args(argv)

    stored = load_stored(args.vault)
    if not stored:
        raise SystemExit(f"没读到任何 business_view: {args.vault}/_meta/business_view")
    pids = stratified_sample(stored, args.n, args.seed)

    # 自检①:复判模型不能和被判样本的产出模型相同。
    sample_models = {stored[p]["model"] for p in pids}
    if args.judge_model in sample_models:
        raise SystemExit(SELF_JUDGE_ABORT.format(
            judge=args.judge_model,
            n=sum(1 for p in pids if stored[p]["model"] == args.judge_model),
            models=", ".join(sorted(sample_models))))

    recs = {r.pid: r for r in load_policies(f"{args.vault}/0_raw/policies")}
    missing = [p for p in pids if p not in recs]
    # 自检②:抽到的样本必须都能找回原文。找不回说明 business_view 与 0_raw 对不上,
    # 那是另一个问题,不该在这里被平均掉。
    if missing:
        raise SystemExit(
            f"{len(missing)} 篇抽样在 0_raw/policies 找不到原文,先查这个再测: {missing[:5]}")

    reg = ThemeRegistry.load(str(Path(args.vault) / DEFAULT_REGISTRY))
    scoring_text = (Path(args.vault) / DEFAULT_SCORING).read_text(encoding="utf-8")
    # 用 pass1 的**原提示词**,只换模型:测的是模型差异,不是提示词差异。
    p1_sys = prompts.pass1_system(reg, scoring_text)

    state = Path(args.state)
    state.mkdir(parents=True, exist_ok=True)
    client = _client or OpenAICompatClient(
        model=args.judge_model,
        base_url=args.judge_base_url,
        api_key=os.environ["OPENAI_API_KEY"],
        log_path=str(state / "judge_calls.jsonl"),
    )

    detail_path = state / "detail.jsonl"
    rows = load_done_rows(detail_path) if args.resume else []
    done = {r["pid"] for r in rows}
    if not args.resume and detail_path.exists():
        detail_path.unlink()      # 不续跑就从头来,免得新旧两轮的结果混在一个文件里
    print(f"复判 {len(pids)} 篇,judge={args.judge_model}"
          + (f",续跑:已完成 {len(done)} 篇" if done else ""), file=sys.stderr)

    resumed, failed = len(done), 0
    for i, pid in enumerate(pids, 1):
        if pid in done:
            continue
        rec = recs[pid]
        try:
            out = gen_pass1(client, p1_sys, prompts.pass1_user(rec))
        except Exception as exc:  # noqa: BLE001 — 单篇失败不该毁掉整轮测量
            print(f"[{i}/{len(pids)}] {pid} 复判失败: {type(exc).__name__}: {exc}",
                  file=sys.stderr)
            failed += 1
            continue
        # 模型吐 "null" 时 json.loads **成功**返回 None,不抛异常——上面的 except 挡不住。
        # 2026-09-02 就是栽在这里:跑到第 91 篇崩掉,前 90 篇的结果没来得及落盘。
        if not isinstance(out, dict):
            print(f"[{i}/{len(pids)}] {pid} 复判输出不是对象({type(out).__name__}),跳过",
                  file=sys.stderr)
            failed += 1
            continue
        judged = canonicalize_theme_ids(out.get("themes") or [], reg.ids)
        old = stored[pid]
        row = {
            "pid": pid,
            "title": rec.title,
            "model": old["model"],
            "stored_themes": old["themes"],
            "stored_D1": old["D1"],
            "judged_themes": judged,
            "judged_D1": (out.get("scores") or {}).get("D1"),
            "verdict": (
                "一致-有主题" if old["themes"] and judged else
                "一致-零主题" if not old["themes"] and not judged else
                "疑似漏检" if not old["themes"] and judged else
                "疑似误挂"
            ),
        }
        rows.append(row)
        # **逐条落盘**,不攒到最后。崩了只丢当前这一篇,--resume 能接着跑。
        with detail_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        if i % 10 == 0:
            print(f"  已复判 {i}/{len(pids)}(续跑沿用 {resumed} · 失败 {failed})", file=sys.stderr)

    assert_enough_judged(len(rows), len(pids), state)

    print(f"\n=== 复判 {len(rows)} 篇(judge={args.judge_model},seed={args.seed},"
          f"其中续跑沿用 {resumed} 篇、失败 {failed} 篇)===")
    overall = collections.Counter(r["verdict"] for r in rows)
    for k in ("一致-有主题", "一致-零主题", "疑似漏检", "疑似误挂"):
        print(f"  {k:12s} {overall[k]:4d}")

    print("\n--- 按产出模型分列(层内等额,故不可直接当作全库比例)---")
    for model in sorted({r["model"] for r in rows}):
        sub = [r for r in rows if r["model"] == model]
        zero = [r for r in sub if not r["stored_themes"]]
        witht = [r for r in sub if r["stored_themes"]]
        miss = sum(1 for r in zero if r["judged_themes"])
        over = sum(1 for r in witht if not r["judged_themes"])
        print(f"  {model}")
        print(f"    零主题 {len(zero):3d} 篇 → 复判认为该挂 {miss:3d} 篇"
              f"({100*miss/len(zero) if zero else 0:.0f}% 疑似漏检)")
        print(f"    有主题 {len(witht):3d} 篇 → 复判认为不该挂 {over:3d} 篇"
              f"({100*over/len(witht) if witht else 0:.0f}% 疑似误挂)")

    misses = [r for r in rows if r["verdict"] == "疑似漏检"]
    if misses:
        print(f"\n--- 疑似漏检前 15 例(全部见 {state}/detail.jsonl)---")
        for r in misses[:15]:
            print(f"  {r['pid']}  D1={r['stored_D1']}→{r['judged_D1']}  "
                  f"{'/'.join(r['judged_themes'])}  {r['title'][:44]}")

    print(f"\n明细: {state}/detail.jsonl · 调用日志: {state}/judge_calls.jsonl")
    print("提醒:分层等额抽样,上面的百分比是**层内**比例,换算全库需按各层真实占比加权。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
