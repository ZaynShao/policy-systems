"""导出 vault 政策原文为对外语料包。

  python -m scripts.public_export.run --vault /root/policy-vault --out ./dist

只读 `0_raw/policies/`。**从不打开** `1_extracted/` / `2_crystallized/` /
`_meta/`，所以派生产出物在数据流层面就不可能进入对外语料 —— 不是"取出来再
过滤"，而是根本没碰过。

产物（--out）：
  policies.jsonl   每行一篇公开记录（含原样正文）
  index.json       去掉正文的轻量索引，供检索/列表
  manifest.json    篇数、生成时间、内容指纹、被排除的篇目及原因
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from scripts.public_export.redact import ExcludedPolicy, split_frontmatter, to_index_entry, to_public_record

RAW_SUBDIR = "0_raw/policies"


def export(vault: Path) -> tuple[list[dict], list[dict]]:
    """遍历 vault 政策原文，返回 (公开记录, 排除记录)。"""
    src = vault / RAW_SUBDIR
    if not src.is_dir():
        raise SystemExit(f"政策原文目录不存在: {src}")

    records: list[dict] = []
    excluded: list[dict] = []
    for path in sorted(src.glob("*.md")):
        try:
            fm, body = split_frontmatter(path.read_text(encoding="utf-8"))
            records.append(to_public_record(fm, body))
        except ExcludedPolicy as e:
            excluded.append({"file": path.name, "reason": str(e)})
        except Exception as e:  # 单篇坏掉不该拖垮整包
            excluded.append({"file": path.name, "reason": f"unreadable: {type(e).__name__}: {e}"})
    return records, excluded


def _fingerprint(records: list[dict]) -> str:
    """内容指纹：语料没变则指纹不变，供下游判断是否需要重新分发。"""
    h = hashlib.sha256()
    for rec in records:
        h.update(json.dumps(rec, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    return h.hexdigest()


def write_bundle(records: list[dict], excluded: list[dict], out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)

    with (out / "policies.jsonl").open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    index = [to_index_entry(r) for r in records]
    (out / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    manifest = {
        "schema": "policy-corpus-public/v1",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "policy_count": len(records),
        "excluded_count": len(excluded),
        "fingerprint": _fingerprint(records),
        "excluded": excluded,
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="导出 vault 政策原文为对外语料包")
    ap.add_argument("--vault", type=Path, required=True, help="vault 根目录")
    ap.add_argument("--out", type=Path, required=True, help="语料包输出目录")
    ap.add_argument("--dry-run", action="store_true", help="只统计，不写文件")
    args = ap.parse_args(argv)

    records, excluded = export(args.vault)

    if args.dry_run:
        print(f"[dry-run] 可导出 {len(records)} 篇，排除 {len(excluded)} 篇")
        for item in excluded[:20]:
            print(f"  - {item['file']}: {item['reason']}")
        return 0

    manifest = write_bundle(records, excluded, args.out)
    print(f"导出 {manifest['policy_count']} 篇 → {args.out}")
    print(f"排除 {manifest['excluded_count']} 篇；指纹 {manifest['fingerprint'][:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
