"""MA4→MA8 编排:装包 → 分块写作 → 两道门 → 返修 → 组稿。

MA0–MA3(选目)是 run_slate 那条链,这里从**已有的 slate.json** 接上。
分开是有理由的:选目一轮要判两百多篇、几十万 token,写作那半边出个 bug
不该把它重跑一遍。`--skip-slate` 就是给这种情形用的。

这条链的验收标准只有一条:**它永远交得出稿**。一篇写不出来就少一篇并记 caveat;
门过不了就返修,两轮仍不过挂容错提示照常发布——那是用户定的口径,不是降级。
"""
import argparse
import hashlib
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

from scripts.common.strategy_profile import load_strategy_profile, render_for_monthly
from scripts.l3_monthly import (assemble, detail_writer, quick_table, repair,
                                run_slate, section_writer)
from scripts.l3_render import build_month_pack, slate_schema

DETAIL_SECTIONS = ("national_detail", "local_detail")
DIGEST_SECTIONS = ("local_detail", "roundup")
APPENDIX_SECTIONS = ("appendix",)


class MonthlyError(RuntimeError):
    """上游产物不齐,接不上。"""


def _read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def _pack_sha(bundles):
    h = hashlib.sha256()
    for pid in sorted(bundles):
        h.update(pid.encode("utf-8"))
        h.update(bundles[pid].encode("utf-8"))
    return h.hexdigest()[:16]


def _title_of(item, slate):
    if item.get("title"):
        return item["title"]
    for entries in (slate.get("sections") or {}).values():
        for e in entries:
            if e.get("policy_id") == item.get("policy_id"):
                return e.get("title_hint") or e.get("policy_id")
    return item.get("policy_id", "")


def _write_details(client, profile_text, pack, bundles, judgments, names, slate,
                   concurrency, style_sample):
    """MA5a。一篇写不出来就少一篇并记 caveat,不让它毁掉整期。

    先按 slate 次序给临时编号写,写完再把成活的重编成连续号——
    交付件里出现 01、03 这种跳号是很显眼的毛病。caveat 的定位串同步改。
    """
    targets = [i for i in pack.index["items"]
               if i.get("file") and i.get("section") in DETAIL_SECTIONS]

    def _one(pair):
        n, item = pair
        pid = item["policy_id"]
        try:
            return item, detail_writer.write_detail(
                client, profile_text, bundles[pid], judgments.get(pid, {}),
                no=f"{n:02d}", policy_id=pid, title=_title_of(item, slate),
                business_names=names, style_sample=style_sample)
        except detail_writer.DetailError as exc:
            return item, exc

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        results = list(pool.map(_one, enumerate(targets, 1)))

    details, caveats = [], []
    for item, outcome in results:
        if isinstance(outcome, detail_writer.DetailError):
            caveats.append({
                "gate": "F", "location": "details",
                "note": f"{item['policy_id']}({_title_of(item, slate)})的详情块未能写出,"
                        f"本期缺这一篇:{outcome}"})
            continue
        detail, det_caveats = outcome
        new_no = f"{len(details) + 1:02d}"
        old_prefix, new_prefix = f"details[{detail['no']}]", f"details[{new_no}]"
        detail["no"] = new_no
        for cv in det_caveats:
            cv["location"] = cv["location"].replace(old_prefix, new_prefix, 1)
        details.append(detail)
        caveats += det_caveats
    return details, caveats


def _uncovered_note(out):
    """MA1b 查到、但库里没有 RAW 的缺口,只进文末脚注,**不进正文**。"""
    path = os.path.join(out, "gap_report.json")
    if not os.path.exists(path):
        return ""
    gaps = [g for g in (json.load(open(path, encoding="utf-8")).get("items") or [])
            if not g.get("in_vault")]
    if not gaps:
        return ""
    named = "；".join(f"{g.get('title','')}({g.get('issuer','') or '来源待核'})"
                      for g in gaps)
    return f"本期检索到但库内尚无原文、故未纳入正文的文件:{named}。"


def run(month, vault, state, out, client, profile_path=None, template_dir=None,
        skip_slate=False, concurrency=4, writer_model="", style_sample=None,
        **slate_kwargs):
    os.makedirs(out, exist_ok=True)
    profile = load_strategy_profile(
        profile_path or os.path.join(vault, run_slate.DEFAULT_PROFILE_REL))
    if not profile:
        raise MonthlyError("读不到战略画像——业务口径是这条产线的唯一真相源,不能没有")
    profile_text = render_for_monthly(profile)
    names = {b["id"]: b["zh"] for b in profile["businesses"]}

    if not skip_slate:
        run_slate.run(month=month, vault=vault, state=state, out=out,
                      client=client, concurrency=concurrency, **slate_kwargs)

    slate_path = os.path.join(out, "slate.json")
    if not os.path.exists(slate_path):
        raise MonthlyError(f"没有 slate.json({slate_path}):先跑 MA0–MA3 选目链路")
    with open(slate_path, encoding="utf-8") as f:
        slate = json.load(f)
    # --skip-slate 是给"写作出了 bug、别把选目重跑一遍"用的,代价是 slate 可能是
    # 手改过或上一版留下的。不校验的话,跨分区重复的 policy_id 会让装包写出两个
    # bundle 而 bundles 字典只留最后一个——第二篇详情就拿着别人的素材写。
    errs = slate_schema.validate_slate(slate)
    if errs:
        raise MonthlyError("slate.json 结构不合法,拒绝据此出稿:" + ";".join(errs))
    judgments = {j["policy_id"]: j
                 for j in _read_jsonl(os.path.join(out, "judgments.jsonl"))
                 if j.get("policy_id")}

    # MA4 装包
    pack_dir = os.path.join(out, "pack")
    pack = build_month_pack.build_pack(slate, vault, state, pack_dir, judgments, names)
    bundles = {i["policy_id"]: open(os.path.join(pack_dir, i["file"]),
                                    encoding="utf-8").read()
               for i in pack.index["items"] if i.get("file")}
    caveats = [{"gate": "F", "location": "pack", "note": w} for w in pack.warnings]

    # MA5d 速览表(纯代码)
    rows, qt_caveats = quick_table.build_quick_table(slate, pack.meta_by_pid, judgments)
    caveats += qt_caveats

    # MA5a 详情块
    details, detail_caveats = _write_details(
        client, profile_text, pack, bundles, judgments, names, slate,
        concurrency, style_sample)
    caveats += detail_caveats

    # MA5b 省级综述 / MA5c 附录
    by_section = {}
    for item in pack.index["items"]:
        by_section.setdefault(item.get("section"), []).append(item)

    def _digests(sections):
        return [section_writer.digest(i, judgments.get(i["policy_id"]), names)
                for sec in sections for i in by_section.get(sec, []) if i.get("file")]

    roundup = section_writer.write_roundup(client, profile_text,
                                           _digests(DIGEST_SECTIONS), month)
    appendix = section_writer.write_appendix(client, profile_text,
                                             _digests(APPENDIX_SECTIONS), month)

    # MA5e 概述 + 业务速判(最后写,输入是已写完的各块)
    extra = {names.get(h, h)
             for sec in DIGEST_SECTIONS[1:] + APPENDIX_SECTIONS
             for i in by_section.get(sec, [])
             for h in (judgments.get(i["policy_id"], {}).get("business_hits") or [])}
    try:
        overview, takes, ov_caveats = section_writer.write_overview(
            client, profile_text, details, profile["businesses"], month,
            roundup=roundup, appendix=appendix, extra_hits=extra)
    except section_writer.SectionError as exc:
        overview, takes = "", []
        ov_caveats = [{"gate": "F", "location": "overview",
                       "note": f"概述未能写出,本期缺概述与业务速判:{exc}"}]
    caveats += ov_caveats

    content = {
        "schema": "monthly.v2", "month": month,
        "narrative": slate.get("narrative", ""),
        "overview": overview, "businessTakes": takes, "quickTable": rows,
        "details": details, "localRoundup": roundup, "appendix": appendix,
        "uncovered": _uncovered_note(out), "caveats": [],
        "provenance": {"writerModel": writer_model, "packSha": _pack_sha(bundles),
                       "profileId": profile.get("profile_id", ""), "auditRounds": 0},
    }

    # MA6 两道门 + MA7 返修(≤2 轮;仍不过挂容错提示照常发布)
    content, remaining, rounds = repair.run_repair(client, content, bundles, profile)
    content["caveats"] = caveats + remaining
    content["provenance"]["auditRounds"] = rounds

    with open(os.path.join(out, "content.json"), "w", encoding="utf-8") as f:
        json.dump(content, f, ensure_ascii=False, indent=2)

    outputs = assemble.write_outputs(content, profile, out, template_dir=template_dir)
    return {"content": content, "outputs": outputs, "rounds": rounds,
            "counts": {"details": len(details), "quick_table": len(rows),
                       "caveats": len(content["caveats"]),
                       "bundles": len(bundles)}}


def main(argv=None):
    ap = argparse.ArgumentParser(description="月刊全链 MA4→MA8(可选带 MA0→MA3)")
    ap.add_argument("--month", required=True, help="YYYY-MM")
    ap.add_argument("--vault", required=True)
    ap.add_argument("--state", required=True)
    ap.add_argument("--out", required=True, help="工作区目录(gitignored)")
    ap.add_argument("--template-dir", help="上期 docx 解包目录;不给就只出 final.md")
    ap.add_argument("--style-sample", help="上期终稿 md 路径,只作版式样例")
    ap.add_argument("--writer-model", default="deepseek-v4-pro")
    ap.add_argument("--writer-provider", default="openai",
                    choices=["anthropic", "openai"])
    ap.add_argument("--search-provider", default="none", choices=["none", "tavily"])
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--skip-slate", action="store_true",
                    help="复用已有 slate.json,只重跑写作与组稿")
    a = ap.parse_args(argv)

    client = run_slate.build_client(a.writer_provider, a.writer_model,
                                    os.path.join(a.out, "llm_calls.jsonl"),
                                    usage_path=os.path.join(a.out, "usage.jsonl"))
    sample = (open(a.style_sample, encoding="utf-8").read()
              if a.style_sample else None)
    extra = {} if a.skip_slate else {"search_provider": a.search_provider}
    try:
        res = run(month=a.month, vault=a.vault, state=a.state, out=a.out,
                  client=client, template_dir=a.template_dir,
                  skip_slate=a.skip_slate, concurrency=a.concurrency,
                  writer_model=a.writer_model, style_sample=sample, **extra)
    except (MonthlyError, run_slate.FreshnessError) as exc:
        print(f"[l3_monthly] 中止:{exc}", file=sys.stderr)
        return 1
    print(json.dumps({"counts": res["counts"], "rounds": res["rounds"],
                      "outputs": res["outputs"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
