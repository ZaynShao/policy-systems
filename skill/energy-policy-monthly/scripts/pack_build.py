"""②装配:按 slate.json 把四层资产打成每政策一个 bundle。

用法:
  python3 pack_build.py --slate slate.json --vault <vault> --out pack/ \
      [--analysis-context <analysis_context.jsonl>]

产出 pack/ 下:
  national_detail_<pid>.md / local_detail_<pid>.md / roundup_<key>.md / INDEX.md

每个 bundle 含:RAW 清洗正文(乱码已还原、未改字) + business_view + analysis_context
+ 关系边 + 关联评论 RAW 节选。写作时事实只能从 bundle 里取,每个数字要能回指 RAW。
commentary_signals.jsonl 只作 join 键(related_policy_ids→path),不引它的结论。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import clean_body, demojibake, fm_get, split_front  # noqa: E402


def index_policies(policies: Path) -> dict[str, list[Path]]:
    idx: dict[str, list[Path]] = {}
    for p in sorted(policies.glob("*.md")):
        m = re.search(r"^id:\s*(\S+)", p.read_text(encoding="utf-8", errors="replace")[:600], re.M)
        if m:
            idx.setdefault(m.group(1), []).append(p)
    return idx


def pick_file(files: list[Path], hint: str) -> Path:
    """同 pid 多份时按 title_hint 里的号数/日期消歧,否则取正文最长的一份。

    vault 里存在真实的 id 撞车(两份不同政策共用一个 pid),也存在同一政策被多个
    渠道重复采集。前者必须靠 hint 区分,后者取信息最全的一份。
    """
    if hint and len(files) > 1:
        for k in re.findall(r"第\d+号|\d+月\d+日|〔\d{4}〕\d+号", hint):
            hit = [f for f in files if k in f.name]
            if len(hit) == 1:
                return hit[0]
            if hit:
                files = hit
    if len(files) == 1:
        return files[0]
    return max(files, key=lambda f: len(clean_body(split_front(f.read_text(encoding="utf-8", errors="replace"))[1])))


def load_rows(path: Path | None) -> list[dict]:
    if not path or not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def bundle_one(pid, hint, ctx, *, full: bool) -> str:
    pidx, rels, actx, csig, comments, bview = ctx
    parts = [f"## 政策 {pid}" + (f"（{hint}）" if hint else "")]
    files = pidx.get(pid, [])
    if not files:
        parts.append("\n**!! vault 无此 pid 的 RAW 文件——核对 slate 里的 pid,或该件需补采**\n")
        return "\n".join(parts)
    f = pick_file(files, hint)
    front, body = split_front(f.read_text(encoding="utf-8", errors="replace"))
    text = clean_body(body)
    if not full and len(text) > 3500:
        text = text[:3500] + "\n……(综述件截断)"
    url = re.search(r"url:\s*(\S+)", front)
    parts.append(f"- 文件: {f.name}")
    if len(files) > 1:
        parts.append(f"- 同 pid 共 {len(files)} 份,已选定本份;其余: {', '.join(x.name[:40] for x in files if x != f)}")
    parts.append(f"- 采集URL: {url.group(1) if url else '-'}")
    parts.append(f"- frontmatter(仅溯源,机关/日期/文号不可靠): date={fm_get(front,'date')} "
                 f"title={demojibake(fm_get(front,'title'))[:60]}")

    bv = bview / f"{pid}.yaml"
    parts.append("\n### business_view(仅作信号)\n```yaml\n" + bv.read_text(encoding="utf-8", errors="replace").strip() + "\n```"
                 if bv.exists() else "\n### business_view: 无打分文件(不代表不重要)")

    row = actx.get(pid)
    parts.append("### analysis_context\n```json\n" + json.dumps(row, ensure_ascii=False, indent=1) + "\n```"
                 if row else "### analysis_context: 无记录")

    edges = [r for r in rels if r.get("from") == pid or r.get("to") == pid]
    if edges:
        parts.append("### 关系边(canonical)\n" + "\n".join(
            f"- {e.get('from')} --{e.get('rel')}({e.get('confidence')})--> {e.get('to')} | "
            f"{(e.get('evidence') or '')[:60]}" for e in edges[:12]))
    else:
        parts.append("### 关系边: 无")

    cs = [c for c in csig if pid in (c.get("related_policy_ids") or [])]
    if cs:
        blocks = []
        for c in cs[:4]:
            cp = comments / c["path"]
            ex = clean_body(split_front(cp.read_text(encoding="utf-8", errors="replace"))[1])[:500] if cp.exists() else ""
            blocks.append(f"- 《{c.get('title','')[:40]}》({c.get('source_account','')}, "
                          f"角色={c.get('signal_role')}, conf={c.get('confidence')})\n  RAW节选: {ex}")
        parts.append("### 评论校准(RAW 节选)\n" + "\n".join(blocks))
    else:
        parts.append("### 评论校准: 无关联评论")

    parts.append("### RAW 正文(去噪+乱码还原,未改字)\n```\n" + text + "\n```")
    return "\n".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slate", type=Path, required=True)
    ap.add_argument("--vault", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--analysis-context", type=Path)
    a = ap.parse_args()

    slate = json.loads(a.slate.read_text(encoding="utf-8"))
    ctx = (
        index_policies(a.vault / "0_raw/policies"),
        load_rows(a.vault / "1_extracted/relations/relations_canonical.jsonl"),
        {r["policy_id"]: r for r in load_rows(a.analysis_context)},
        load_rows(a.vault / "1_extracted/commentary_signals.jsonl"),
        a.vault / "0_raw/commentaries",
        a.vault / "_meta/business_view",
    )
    a.out.mkdir(parents=True, exist_ok=True)
    index = ["# bundle 索引\n"]

    for sec in ("national_detail", "local_detail"):
        for it in slate.get(sec, []):
            if it.get("excluded"):
                continue
            doc = [f"# BUNDLE [{sec}] {it['pid']}", f"选目理由: {it.get('why','')}",
                   "dq: " + ("; ".join(it.get("dq") or []) or "无"), ""]
            doc.append(bundle_one(it["pid"], it.get("title_hint", ""), ctx, full=True))
            for comp in it.get("companions", []):
                doc.append("\n---\n伴随件:\n")
                doc.append(bundle_one(comp, "", ctx, full=True))
            name = f"{sec}_{it['pid']}.md"
            (a.out / name).write_text("\n".join(doc), encoding="utf-8")
            index.append(f"- [{sec}] {it['pid']} {it.get('title_hint','')} -> {name}")

    for g in slate.get("roundup", []):
        if g.get("excluded"):
            index.append(f"- [roundup] {g['key']} 已按编辑指令剔除: {g.get('excluded_reason','')}")
            continue
        doc = [f"# BUNDLE [roundup] {g['key']}", f"选目理由: {g.get('why','')}",
               "dq: " + ("; ".join(g.get("dq") or []) or "无"), ""]
        for m in g["members"]:
            pid = m["pid"] if isinstance(m, dict) else m
            hint = m.get("title_hint", "") if isinstance(m, dict) else ""
            doc.append(bundle_one(pid, hint, ctx, full=False))
            doc.append("")
        name = f"roundup_{g['key']}.md"
        (a.out / name).write_text("\n".join(doc), encoding="utf-8")
        index.append(f"- [roundup] {g['key']} ({len(g['members'])}件) -> {name}")

    (a.out / "INDEX.md").write_text("\n".join(index) + "\n", encoding="utf-8")
    print(f"装配完成: {len(index)-1} 个 bundle -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
