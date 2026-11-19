"""按关键词 dump 单件 RAW 去噪正文,用于逐字核事实、抠可引原文。

用法:
  python3 dump_raw.py --vault <vault> --kw "绿电直连" --lines 40
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import clean_body, fm_get, split_front  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", type=Path, required=True)
    ap.add_argument("--kw", required=True)
    ap.add_argument("--lines", type=int, default=40)
    ap.add_argument("--max-files", type=int, default=4)
    a = ap.parse_args()

    policies = a.vault / "0_raw/policies"
    hits = [p for p in sorted(policies.glob("*.md")) if a.kw in p.name]
    if not hits:  # 文件名没命中就搜正文头部
        for p in sorted(policies.glob("*.md")):
            if a.kw in p.read_text(encoding="utf-8", errors="replace")[:1500]:
                hits.append(p)

    for p in hits[:a.max_files]:
        front, body = split_front(p.read_text(encoding="utf-8", errors="replace"))
        url = re.search(r"url:\s*(\S+)", front)
        print(f"\n{'='*70}\n文件: {p.name}")
        print(f"pid: {fm_get(front,'id')}  fm_date: {fm_get(front,'date')}")
        print(f"url: {url.group(1) if url else '-'}\n{'-'*70}")
        for ln in clean_body(body, drop_short=3).splitlines()[:a.lines]:
            print(ln[:120])
    if not hits:
        print(f"未命中: {a.kw}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
