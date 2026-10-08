"""①选目第一步:扫时间窗候选,join business_view 打分,并捞回跨月件。

用法:
  python3 scan_window.py --vault <vault> --lo 2026-09-01 --hi 2026-10-08 --out candidates.jsonl --print

两类候选都会进 candidates.jsonl:
  1. frontmatter date 落在 [lo, hi] 的件(常规);
  2. frontmatter date 早于 lo、但入库日(provenance.fetched_at)落在 [lo, hi] 的件(跨月捞回,
     cross_month=true,打印时标 ↩)。这类件多是"上月成文、本月发布"的国家级文件,
     7 月刊的 45 号、8 月刊的 942/1055/979 号都是这样漏掉又捞回来的。
     --backfill-days 控制回看多久(默认 75 天),太久会把历史重采件也捞进来。

frontmatter 只用来圈范围,机关/日期/文号一律回 RAW 正文核(见 verify_head.py)。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import clean_body, demojibake, fm_fetched, fm_get, fm_region, split_front  # noqa: E402


def load_bview(bview_dir: Path, pid: str) -> dict:
    p = bview_dir / f"{pid}.yaml"
    if not p.exists():
        return {}
    t = p.read_text(encoding="utf-8", errors="replace")
    out = {}
    for k in ("重要性", "行动分类", "primary_theme"):
        m = re.search(rf"^{k}:\s*(.*)$", t, re.M)
        if m:
            out[k] = m.group(1).strip().strip("'\"")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", type=Path, required=True)
    ap.add_argument("--lo", required=True, help="窗口起,如 2026-09-01")
    ap.add_argument("--hi", required=True, help="窗口止,建议含次月初")
    ap.add_argument("--out", type=Path, default=Path("candidates.jsonl"))
    ap.add_argument("--print", action="store_true", help="按打分降序打印候选表")
    ap.add_argument("--backfill-days", type=int, default=75,
                    help="跨月捞回的回看天数:date 早于 lo 但不早于 lo-N 天、且入库日在窗口内的件也进候选")
    ap.add_argument("--no-backfill", action="store_true", help="关闭跨月捞回")
    a = ap.parse_args()

    lo_d = dt.date.fromisoformat(a.lo)
    floor = (lo_d - dt.timedelta(days=a.backfill_days)).isoformat()

    policies = a.vault / "0_raw/policies"
    bview = a.vault / "_meta/business_view"
    rows = []
    for p in sorted(policies.glob("*.md")):
        raw = p.read_text(encoding="utf-8", errors="replace")
        front, body = split_front(raw)
        date = fm_get(front, "date")
        fetched = fm_fetched(front)
        in_window = a.lo <= date <= a.hi
        cross = (not in_window and not a.no_backfill
                 and floor <= date < a.lo and fetched and a.lo <= fetched <= a.hi)
        if not (in_window or cross):
            continue
        pid = fm_get(front, "id")
        lvl, region = fm_region(front)
        bv = load_bview(bview, pid)
        url = re.search(r"url:\s*(\S+)", front)
        rows.append({
            "pid": pid,
            "file": p.name,
            "title": demojibake(fm_get(front, "title")),
            "fm_date": date,
            "fm_fetched": fetched,
            "cross_month": cross,
            "fm_region_level": lvl,
            "fm_region": region,
            "url": url.group(1) if url else "",
            "bv_score": bv.get("重要性", ""),
            "bv_action": bv.get("行动分类", ""),
            "mojibake": "å" in raw,
            "excerpt": clean_body(body, drop_short=4)[:400].replace("\n", " / "),
        })

    with a.out.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    n_cross = sum(1 for r in rows if r["cross_month"])
    print(f"窗口 {a.lo}~{a.hi} 候选 {len(rows)} 条(含跨月捞回 {n_cross} 条) -> {a.out}")
    print(f"  乱码 {sum(1 for r in rows if r['mojibake'])} 条 | 无打分 {sum(1 for r in rows if not r['bv_score'])} 条")
    print("  提示:无打分的可能正是旗舰件,打分低的也可能是重要跨条线件,必须逐条看标题判断;")
    print("        标 ↩ 的是成文日在窗口前、本窗口才入库的件,国家级文件尤其要看。")

    if a.print:
        rows.sort(key=lambda r: (-int(r["bv_score"] or 0), r["fm_date"]))
        print()
        for r in rows:
            mark = "↩" if r["cross_month"] else " "
            print(f"{r['bv_score'] or '-':>2} {r['bv_action'] or '-'} {mark}{r['fm_date']} "
                  f"{r['fm_region'] or '?':<8} {r['title'][:54]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
