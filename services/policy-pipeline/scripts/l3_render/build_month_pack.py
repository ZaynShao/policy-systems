"""MA4 月报素材包装配。

读 slate.json,从 vault(raw + business_view + relations)与 state(analysis_context)
为每条选中政策装配一个 markdown bundle + INDEX.json。只读;输出到 --out。

**这一步是 F 门能成立的物理前提**:稿子里每个数字、文号、日期都要在某个 bundle 里
回指得到。所以它的危险失败模式不是「跑不出来」,而是**悄悄少装了料**——关系文件
不存在就整批没有承接血缘,而稿子照写不误。故上游缺件一律显式告警并记进 INDEX。

用法:
  python3 -m scripts.l3_render.build_month_pack --slate slate.json \
      --vault /vault --state /state --out ./pack [--judgments judgments.jsonl]
"""
import argparse
import dataclasses
import glob
import json
import os
import sys

from scripts.l3_render import pack_lib as pl

# RAW 段预算仍是原来的 9000,但**头尾都取**:本地 vault 实测 14.7% 的政策正文
# 超过 9000 字符,只截头会把落款整段切掉,而 bundle 明写「以 RAW 落款为准」。
RAW_HEAD, RAW_TAIL = 7500, 1500
SECTION_LEVEL = {
    "national_detail": "国家级",
    "local_detail": "地方(重要)",
    "roundup": "地方(速览)",
    "appendix": "信号(国家级讲话/会议)",
}
ORDER = ("national_detail", "local_detail", "roundup", "appendix")


@dataclasses.dataclass
class PackResult:
    """index 写进 INDEX.json;meta_by_pid 只在进程内传给 MA5d,不落盘(正文很大)。"""
    index: dict
    meta_by_pid: dict
    warnings: list


def load_raw_index(pol_dir):
    idx = {}  # id -> [(path, fm, md), ...]
    for p in glob.glob(os.path.join(pol_dir, "*.md")):
        try:
            md = open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        fm = pl.parse_frontmatter(md)
        if fm.get("id"):
            idx.setdefault(fm["id"], []).append((p, fm, md))
    return idx


def id2title_map(raw_index):
    return {pid: recs[0][1].get("title", pid) for pid, recs in raw_index.items()}


def load_bv(bv_dir, pid):
    p = os.path.join(bv_dir, pid + ".yaml")
    return open(p, encoding="utf-8").read() if os.path.exists(p) else ""


def load_ac(ac_path):
    """缺件返回空。上游没跑出 nightly 由 MA0 的新鲜度闸负责拦,装包这里不重复中止;
    本地路线本来就没有这份产物。缺件的告警由 build_pack 统一发。"""
    ac = {}
    if not os.path.exists(ac_path):
        return ac
    with open(ac_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                o = json.loads(line)
                ac[o["policy_id"]] = o
    return ac


def load_edges(rel_path):
    """缺件返回空,理由同 load_ac——本地热备 vault 只有 _index_by_policy,
    没有 relations_canonical.jsonl,直接 open 会把整个装包炸掉。"""
    edges = []
    if not os.path.exists(rel_path):
        return edges
    with open(rel_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                edges.append(json.loads(line))
    return edges


def load_commentaries(comm_dir, ids):
    import re
    out = []
    for cid in ids or []:
        hits = glob.glob(os.path.join(comm_dir, f"*{cid}*.md"))
        if hits:
            txt = open(hits[0], encoding="utf-8", errors="replace").read()
            out.append({"id": cid, "text": re.sub(r"\s+", " ", txt)[:800]})
    return out


def load_judgments(path):
    """读 MA2 产物,按 policy_id 索引。"""
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                o = json.loads(line)
                if o.get("policy_id"):
                    out[o["policy_id"]] = o
    return out


def _ma2_block(judgment, business_names):
    """MA2 判定段。MA5a 的决策建议**只许覆盖 business_hits 列出的业务线**,
    所以这段必须进 bundle,否则写作那步无从遵守 spec §6.3。

    relevance=error 表示这篇没判成,不是一个判定——那种情况下一个字段都不给,
    否则错误的落款会被当成事实写进稿子。
    """
    names = business_names or {}
    if not judgment:
        return []
    L = ["", "## MA2 判定(决策建议只许覆盖下列 business_hits;不写「X 业务无关」)"]
    if judgment.get("relevance") == "error":
        L.append(f"- ⚠️ **本篇未判定**(MA2 失败):{judgment.get('dq') or ''}")
        L.append("- 落款三事实与业务命中均缺失,写作时只能回指下方 RAW,不得臆测")
        return L
    hits = [f"{h}({names[h]})" if h in names else str(h)
            for h in judgment.get("business_hits") or []]
    L.append(f"- business_hits: {'、'.join(hits) or '(无)'}")
    L.append(f"- 触及决策变量: {'、'.join(judgment.get('decision_variables_touched') or []) or '(无)'}")
    L.append(f"- 相关性: {judgment.get('relevance') or ''}  理由: {judgment.get('why') or ''}")
    L.append("- 下列三项是 MA2 从 RAW 头尾读出的落款事实(速览表与政策信息段用它,"
             "与下方 RAW 落款冲突时以 RAW 为准):")
    L.append(f"    · 发文日期: {judgment.get('issue_date_from_body') or '(未抽到)'}")
    L.append(f"    · 发文机关: {judgment.get('issuer_from_body') or '(未抽到)'}")
    L.append(f"    · 文号: {judgment.get('official_number_from_body') or '(未抽到)'}")
    if judgment.get("dq"):
        L.append(f"- ⚠️ 数据质量: {judgment['dq']}")
    return L


def build_bundle(item, rec, bv, ac_entry, rels, commentaries,
                 judgment=None, business_names=None):
    path, fm, md = rec
    body = pl.body_of(md)
    level_editorial = SECTION_LEVEL.get(item["section"], "?")
    level_auto = pl.classify_level(fm.get("region_name", ""), fm.get("official_number", ""), fm.get("region_level", ""))
    date_hints = pl.body_date_hints(body)
    L = []
    L.append(f"# [{item['section']}] {fm.get('title','')}")
    L.append("")
    L.append("## 编辑卡(来自 slate,非事实源,仅定位与排序依据)")
    L.append(f"- policy_id: {item['policy_id']}")
    if item.get("rank"):
        L.append(f"- 拟评分/序: {item.get('score','')} / rank {item.get('rank')}")
    L.append(f"- 入选理由: {item.get('why','')}")
    if item.get("dq"):
        L.append(f"- ⚠️ 数据质量提示: {item['dq']}")
    L += _ma2_block(judgment, business_names)
    L.append("")
    L.append("## 政策信息(发文机关/日期/文号 **以下方 RAW 正文落款+文号为准**,本区字段不可靠)")
    L.append(f"- 发文机关(frontmatter,⚠️不可靠,常是采集省份): {fm.get('region_name','')}")
    L.append(f"- 文号(frontmatter,⚠️可能误取被废止/引用件号): {fm.get('official_number') or '无'}")
    L.append(f"- frontmatter日期: {fm.get('date','')}  (region.level={fm.get('region_level','')},均不可靠)")
    L.append(f"- **层级(编辑判定,权威): {level_editorial}**  (自动粗判={level_auto},仅参考)")
    L.append(f"- 正文日期线索(校验真实发文日): {', '.join(date_hints[-6:]) or '无'}")
    L.append("")
    clean = pl.strip_web_chrome(body)
    L.append("## RAW 原文(唯一事实来源,引用须逐字回指此处;图片与 URL 已清除)")
    if len(clean) > RAW_HEAD + RAW_TAIL:
        # 实测有一篇 21 万字符的《行业标准制定计划》附件表进了 shortlist,
        # 装进来的只有 4%。不说出来,写作那步会以为自己读的是全文。
        L.append("")
        L.append(f"> ⚠️ 本篇正文(已清页面 chrome)共 {len(clean)} 字符,"
                 f"此处只装了**头 {RAW_HEAD} + 尾 {RAW_TAIL}**,"
                 f"中间已略去。未装进来的部分**不得据以写作**,也不得声称已通读全文。")
    L.append("")
    L.append(pl.excerpt(clean, RAW_HEAD, RAW_TAIL))
    L.append("")
    L.append("## business_view(信号原料,非定论;评分失准,仅参考)")
    L.append("```yaml")
    L.append(bv.strip() or "(无)")
    L.append("```")
    L.append("")
    L.append("## analysis_context(关系+信号叠加,含 audit_refs 溯源)")
    L.append("```json")
    L.append(json.dumps(ac_entry, ensure_ascii=False, indent=2) if ac_entry else "(无)")
    L.append("```")
    L.append("")
    L.append("## 关系边(承接血缘;对端已解析为标题。承接表述须匹配此处,不得杜撰)")
    if rels:
        for r in rels:
            ev = f"  ‹{r['evidence']}›" if r.get("evidence") else ""
            L.append(f"- [{r['dir']}] {r['rel']} → {r['other']}{ev}")
    else:
        L.append("(无)")
    if commentaries:
        L.append("")
        L.append("## 评论校准(commentary_signals 引用原文)")
        for c in commentaries:
            L.append(f"- ({c['id']}) {c['text']}")
    return "\n".join(L)


def build_pack(slate, vault, state, out, judgments=None, business_names=None):
    """装包。返回 PackResult;INDEX.json 落 out 目录。

    上游缺件不中止,但每一件都记进 warnings 并写进 INDEX——少装了料的稿子
    看起来和装齐了的一模一样,不显式说出来就没人会发现。
    """
    judgments = judgments or {}
    pol_dir = os.path.join(vault, "0_raw/policies")
    bv_dir = os.path.join(vault, "_meta/business_view")
    comm_dir = os.path.join(vault, "0_raw/commentaries")
    rel_path = os.path.join(vault, "1_extracted/relations/relations_canonical.jsonl")
    ac_path = os.path.join(state, "analysis_layer/nightly/analysis_context.jsonl")

    warnings = []
    rel_missing = not os.path.exists(rel_path)
    ac_missing = not os.path.exists(ac_path)
    if rel_missing:
        warnings.append(f"relations_canonical.jsonl 不存在({rel_path}),"
                        "本期全部 bundle 无承接血缘,稿内不得出现任何承接表述")
    if ac_missing:
        warnings.append(f"analysis_context.jsonl 不存在({ac_path}),"
                        "本期全部 bundle 无信号叠加与评论校准")

    raw_index = load_raw_index(pol_dir)
    id2title = id2title_map(raw_index)
    ac = load_ac(ac_path)
    edges = load_edges(rel_path)

    os.makedirs(out, exist_ok=True)
    manifest, meta_by_pid, built = [], {}, 0
    for sec in ORDER:
        for it in (slate.get("sections") or {}).get(sec, []):
            item = dict(it)
            item["section"] = sec
            pid = item["policy_id"]
            recs = raw_index.get(pid)
            if not recs:
                manifest.append({"policy_id": pid, "section": sec, "status": "MISSING_RAW"})
                continue
            rec = pl.pick_record(recs, item.get("title_hint"))
            bv = load_bv(bv_dir, pid)
            ac_entry = ac.get(pid)
            rels = pl.resolve_relations(pid, edges, id2title)
            comm_ids = (ac_entry or {}).get("audit_refs", {}).get("commentary_ids", [])
            comms = load_commentaries(comm_dir, comm_ids)
            bundle = build_bundle(item, rec, bv, ac_entry, rels, comms,
                                  judgments.get(pid), business_names)
            built += 1
            fn = f"{built:02d}_{sec}__{pid}.md"
            open(os.path.join(out, fn), "w", encoding="utf-8").write(bundle)
            # 正文给 MA5d 的是**全文**:落款在文末,截断过的正文永远抽不到落款。
            meta_by_pid[pid] = {"title": rec[1].get("title", ""), "body": pl.body_of(rec[2])}
            manifest.append({
                "policy_id": pid, "section": sec, "file": fn,
                "title": rec[1].get("title", ""),
                "level_editorial": SECTION_LEVEL.get(sec, "?"),
                "level_auto": pl.classify_level(rec[1].get("region_name", ""), rec[1].get("official_number", ""), rec[1].get("region_level", "")),
                "has_bv": bool(bv), "has_ac": bool(ac_entry), "n_rels": len(rels), "dup_raw": len(recs),
                "body_len": len(meta_by_pid[pid]["body"]),
                "packed_len": len(pl.strip_web_chrome(meta_by_pid[pid]["body"])),
                "raw_truncated": len(pl.strip_web_chrome(meta_by_pid[pid]["body"])) > RAW_HEAD + RAW_TAIL,
            })
    if built and not ac_missing and not any(m.get("has_ac") for m in manifest):
        warnings.append(f"analysis_context.jsonl 存在但本期 {built} 个 bundle 无一命中"
                        "(空文件,或 nightly 跑出了空结果),等于整期没有信号叠加与评论校准")
    if built and not rel_missing and not any(m.get("n_rels") for m in manifest):
        warnings.append(f"relations_canonical.jsonl 存在但本期 {built} 个 bundle 一条承接边都没有,"
                        "稿内不得出现任何承接表述")
    trunc = [m["policy_id"] for m in manifest if m.get("raw_truncated")]
    if trunc:
        warnings.append(f"{len(trunc)} 篇正文超出 RAW 预算被截头尾({'、'.join(trunc)}),"
                        "写作与 F 门都只覆盖装进来的部分")

    index = {"month": slate["month"], "narrative": slate.get("narrative", ""),
             "warnings": warnings, "items": manifest}
    with open(os.path.join(out, "INDEX.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    return PackResult(index=index, meta_by_pid=meta_by_pid, warnings=warnings)


def main(argv=None):
    ap = argparse.ArgumentParser(description="MA4 月报素材包装配")
    ap.add_argument("--slate", required=True)
    ap.add_argument("--vault", required=True)
    ap.add_argument("--state", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--judgments", help="MA2 产物 judgments.jsonl(给 MA5a 的 business_hits)")
    ap.add_argument("--profile", help="战略画像 yaml,只用来把 business id 显示成中文名")
    a = ap.parse_args(argv)

    judgments = load_judgments(a.judgments) if a.judgments else None
    names = None
    if a.profile:
        from scripts.common.strategy_profile import load_strategy_profile
        profile = load_strategy_profile(a.profile)
        names = {b["id"]: b["zh"] for b in (profile or {}).get("businesses") or []}

    slate = json.load(open(a.slate, encoding="utf-8"))
    res = build_pack(slate, a.vault, a.state, a.out, judgments, names)
    for w in res.warnings:
        print(f"[MA4] 告警:{w}", file=sys.stderr)
    built = sum(1 for m in res.index["items"] if m.get("file"))
    missing = sum(1 for m in res.index["items"] if m.get("status") == "MISSING_RAW")
    print(f"bundles: {built} | missing: {missing}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
