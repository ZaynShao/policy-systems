"""MA9:人工修改意见回炉。

页面上提交的意见落在 `content.pendingNote`。这一步把它变成一次**定向**返修:
先问模型这条意见说的是哪几段(意见是自然语言,靠字符串匹配定位太脆,
而且一旦定错就会把不相干的段落重写一遍),再走 MA7 同一条链重写那几段。

**铁律:人工意见同样过三道门。** 人说了不等于稿子里就能写——改完仍要过
D 门 / 业务口径门 / F 门,过不了就不采用并记一条 caveat,而不是因为
「是人说的」就放行。这条一旦松掉,修改意见栏就成了绕过事实核查的后门。
"""
import argparse
import copy
import json
import os
import sys

from scripts.common.strategy_profile import load_strategy_profile
from scripts.l3_monthly import (budget, fact_gate, gates, judge, project_pg,
                                prompts, repair, run_slate)


def locate_targets(client, note, locations, max_tokens=budget.SHORT_JSON):
    """问模型这条意见说的是哪几段。定不出来就全篇当候选。

    退回全篇不危险:每一段改完都要各自过门,过不了的自然不会被采用。
    危险的是把意见丢掉——读者提了却什么都没发生。
    """
    known = list(locations)
    try:
        obj = judge.extract_json(client.complete(
            prompts.NOTE_LOCATE_SYSTEM,
            prompts.build_note_locate_user(note, known), max_tokens=max_tokens))
        picked = [loc for loc in obj["locations"] if loc in known]
    except (judge.JudgmentError, KeyError, TypeError):
        return known
    return picked or known


def apply_note(client, content, bundles, profile, note, max_tokens=budget.REPAIR):
    """按意见回炉。返回 (content, caveats, applied_locations)。**不抛异常**。"""
    text = (note or "").strip()
    out = copy.deepcopy(content)
    if not text:
        return out, [], []

    setters = {loc: setter for loc, _, setter in repair.iter_blocks(out)}
    texts = repair.block_texts(out)
    caveats, applied = [], []

    for loc in locate_targets(client, text, list(setters)):
        if loc not in setters:
            continue
        srcs = repair.sources_for(loc, out, bundles)
        user = prompts.build_note_rewrite_user(loc, texts[loc], text,
                                               "\n\n".join(srcs))
        try:
            new = (client.complete(prompts.NOTE_REWRITE_SYSTEM, user,
                                   max_tokens=max_tokens) or "").strip()
        except Exception:  # noqa: BLE001 —— 一段改不成不该毁掉整轮
            new = ""
        if not new:
            caveats.append({"gate": "H", "location": loc,
                            "note": f"人工意见「{text}」未采用:这一段没能改出来"})
            continue
        problems = gates.run_gates(new, profile) + fact_gate.check_facts(new, srcs, loc)
        if problems:
            caveats.append({
                "gate": problems[0]["gate"], "location": loc,
                "note": f"人工意见「{text}」的改写未采用:{problems[0]['note']}"
                        f"(改写内容过不了审核门,原文保留)"})
            continue
        setters[loc](new)
        applied.append(loc)

    # 回炉完就把待办清掉,否则下一轮会把同一条意见再跑一遍
    out.pop("pendingNote", None)
    out.pop("pendingNoteAt", None)
    out["humanNote"] = text
    return out, caveats, applied


def load_bundles(pack_dir):
    """从 MA4 留下的 pack 目录读回素材。MA9 与 MA4 用同一批,不重新装包——
    重新装一遍就可能拿到和当初写稿时不一样的材料,F 门的对账就失去意义。"""
    with open(os.path.join(pack_dir, "INDEX.json"), encoding="utf-8") as f:
        index = json.load(f)
    out = {}
    for item in index.get("items") or []:
        if item.get("file"):
            with open(os.path.join(pack_dir, item["file"]), encoding="utf-8") as f:
                out[item["policy_id"]] = f.read()
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="MA9 人工修改意见回炉")
    ap.add_argument("--month", required=True, help="YYYY-MM")
    ap.add_argument("--out", required=True, help="该期的工作区(要用里面的 pack/)")
    ap.add_argument("--vault", required=True, help="只用来读战略画像")
    ap.add_argument("--dsn", default=os.environ.get("DATABASE_URL", ""),
                    help="给了就从库里读 pendingNote 并把结果写回;不给就只跑本地 content.json")
    ap.add_argument("--writer-model", default="deepseek-v4-pro")
    ap.add_argument("--writer-provider", default="openai",
                    choices=["anthropic", "openai"])
    a = ap.parse_args(argv)

    conn = None
    if a.dsn:
        import psycopg2
        conn = psycopg2.connect(a.dsn)
        content = project_pg.fetch_content(conn, a.month)
        if content is None:
            print(f"[l3_monthly] 中止:库里没有 {a.month} 这一期", file=sys.stderr)
            return 1
    else:
        with open(os.path.join(a.out, "content.json"), encoding="utf-8") as f:
            content = json.load(f)

    note = str(content.get("pendingNote") or "").strip()
    if not note:
        print(json.dumps({"month": a.month, "applied": [], "reason": "没有待回炉的意见"},
                         ensure_ascii=False))
        return 0

    profile = load_strategy_profile(
        os.path.join(a.vault, run_slate.DEFAULT_PROFILE_REL))
    client = run_slate.build_client(a.writer_provider, a.writer_model,
                                    os.path.join(a.out, "llm_calls.jsonl"),
                                    usage_path=os.path.join(a.out, "usage.jsonl"))
    bundles = load_bundles(os.path.join(a.out, "pack"))
    new_content, caveats, applied = apply_note(client, content, bundles, profile, note)
    new_content["caveats"] = (content.get("caveats") or []) + caveats

    with open(os.path.join(a.out, "content.json"), "w", encoding="utf-8") as f:
        json.dump(new_content, f, ensure_ascii=False, indent=2)
    if conn:
        # 投影时 changeNote 记意见原文,版本历史因此说得清这一版为什么改
        project_pg.project(conn, new_content, model=a.writer_model,
                           change_note=f"人工意见回炉:{note}")
        conn.close()
    print(json.dumps({"month": a.month, "applied": applied,
                      "not_applied": len(caveats)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
