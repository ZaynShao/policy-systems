"""MA3:选目定调。

输入是 MA2 的**结构化判定**,不喂 RAW:选目靠判定结果与编辑判断,重读原文只会把
上下文撑爆,而且会诱使模型在选目阶段就开始写稿。

分工是这一步的关键:**模型做编辑判断(选哪些、怎么排、本月定调),代码执行约束**。
代码只「修剪」不「发明」——砍超配额、把「需人工裁定」从详情挪进速览、给 id 撞车的
补 title_hint,都是在执行画像与 schema 的既定规则,不是替模型做编辑决定。
这条界线一旦越过,就退回成「机器评分决定选目」,也就是现有产线出稿不行的根因。
"""
import copy

from scripts.l3_monthly import budget, prompts
from scripts.l3_monthly.judge import JudgmentError, extract_json
from scripts.l3_render.slate_schema import SECTIONS, validate_slate

# 配额参照已交付各期的实际体量(2026-06 终稿:国家级 4 / 地方 2 / 速览 9)。
# 上限不是目标——「宁薄勿凑」写在提示词里,配额只挡住凑数。
QUOTAS = {"national_detail": 5, "local_detail": 3, "roundup": 12, "appendix": 5}
DETAIL_SECTIONS = ("national_detail", "local_detail")


class SlateError(RuntimeError):
    """选目产不出来。**不兜底**:没有 slate 就没有可写的东西,硬停并告警,不能编一份。"""


def render_judgments(judgments):
    """把判定渲染成选目视野。判定失败(error)的不进视野——没判出来就不该被选。"""
    lines = []
    for j in judgments:
        if j.get("relevance") == "error":
            continue
        flags = []
        if j.get("id_collision"):
            flags.append("id撞车:title_hint 必填")
        if j.get("near_dup_group"):
            flags.append(f"疑似重复[{j['near_dup_group']}]")
        if j.get("docno_conflict"):
            flags.append("文号与他篇冲突,以正文落款为准")
        if j.get("series_size"):
            flags.append(f"周期性系列,本月共{j['series_size']}篇")
        head = f"- {j.get('policy_id')} | {j.get('level') or '?'} | {j.get('relevance')}"
        if j.get("business_hits"):
            head += " | 影响:" + "/".join(j["business_hits"])
        lines.append(head)
        lines.append(f"    标题:{j.get('title') or ''}")
        if j.get("issue_date_from_body"):
            lines.append(f"    正文落款日:{j['issue_date_from_body']}")
        if j.get("why"):
            lines.append(f"    初判:{j['why']}")
        if j.get("dq"):
            lines.append(f"    数据质量:{j['dq']}")
        if flags:
            lines.append(f"    ⚠ {';'.join(flags)}")
    return "\n".join(lines)


def _index(judgments):
    return {j.get("policy_id"): j for j in judgments if j.get("policy_id")}


def validate_selection(slate, judgments):
    """schema 之外的选目约束。返回错误列表;空列表 = 通过。"""
    errs = []
    idx = _index(judgments)
    seen = {}
    for name in SECTIONS:
        items = (slate.get("sections") or {}).get(name) or []
        if len(items) > QUOTAS[name]:
            errs.append(f"{name} 选了 {len(items)} 篇,超过上限 {QUOTAS[name]}")
        for it in items:
            pid = it.get("policy_id")
            j = idx.get(pid)
            if j is None:
                errs.append(f"{name} 选了不在本月判定结果里的 {pid}")
                continue
            if j.get("relevance") == "error":
                errs.append(f"{name} 选了判定失败(error)的 {pid}")
            if j.get("relevance") == "需人工裁定" and name in DETAIL_SECTIONS:
                errs.append(f"{pid} 是「需人工裁定」,不得进 {name},只能进 roundup")
            if j.get("id_collision") and not str(it.get("title_hint") or "").strip():
                errs.append(f"{pid} 有 id撞车,title_hint 必填才定位得到是哪一篇")
            if pid in seen:
                errs.append(f"policy_id {pid} 在 {seen[pid]} 与 {name} 重复出现")
            else:
                seen[pid] = name
    return errs


def repair_selection(slate, judgments):
    """执行约束,返回 (修好的 slate, 修补说明列表)。只修剪,不发明。"""
    idx = _index(judgments)
    out = copy.deepcopy(slate)
    sections = out.setdefault("sections", {})
    for name in SECTIONS:
        sections.setdefault(name, [])
    repairs = []

    # 1) 丢掉不认识的与判定失败的
    for name in SECTIONS:
        kept = []
        for it in sections[name]:
            pid = it.get("policy_id")
            j = idx.get(pid)
            if j is None:
                repairs.append(f"{name}:丢弃不在判定结果里的 {pid}")
            elif j.get("relevance") == "error":
                repairs.append(f"{name}:丢弃判定失败(error)的 {pid}")
            else:
                kept.append(it)
        sections[name] = kept

    # 2) 「需人工裁定」从详情挪进速览(画像规则:那表示无依据判断,不是判断它重要)
    for name in DETAIL_SECTIONS:
        kept = []
        for it in sections[name]:
            if idx[it["policy_id"]].get("relevance") == "需人工裁定":
                sections["roundup"].append(it)
                repairs.append(f"{it['policy_id']} 是「需人工裁定」,从 {name} 挪入 roundup")
            else:
                kept.append(it)
        sections[name] = kept

    # 3) 跨分区去重,保留先出现的
    seen = {}
    for name in SECTIONS:
        kept = []
        for it in sections[name]:
            pid = it.get("policy_id")
            if pid in seen:
                repairs.append(f"{pid} 在 {seen[pid]} 与 {name} 重复,丢弃后者")
            else:
                seen[pid] = name
                kept.append(it)
        sections[name] = kept

    # 4) id 撞车的补 title_hint
    for name in SECTIONS:
        for it in sections[name]:
            j = idx[it["policy_id"]]
            if j.get("id_collision") and not str(it.get("title_hint") or "").strip():
                it["title_hint"] = j.get("title") or ""
                repairs.append(f"{it['policy_id']} 有 id撞车,用判定里的标题补上 title_hint")

    # 5) 最后砍超配额:按 rank 取前 N,保留原有相对顺序
    for name in SECTIONS:
        items = sections[name]
        if len(items) <= QUOTAS[name]:
            continue
        keep = {id(x) for x in sorted(items, key=lambda i: i.get("rank") or 10**6)[:QUOTAS[name]]}
        sections[name] = [x for x in items if id(x) in keep]
        repairs.append(f"{name} 超过上限 {QUOTAS[name]},按 rank 保留前 {QUOTAS[name]} 篇")
    return out, repairs


def build_slate(client, month, judgments, retries=1, max_tokens=budget.SLATE):
    """跑 MA3 并把约束执行到位。返回 (slate, repairs)。产不出合规 slate 则抛 SlateError。"""
    system = prompts.SLATE_SYSTEM
    user = prompts.build_slate_user(month, render_judgments(judgments))
    last = ""
    for _ in range(retries + 1):
        try:
            obj = extract_json(client.complete(system, user, max_tokens=max_tokens))
        except JudgmentError as exc:
            last = str(exc)
            continue
        if not isinstance(obj, dict):
            last = "输出 JSON 不是对象"
            continue
        obj["month"] = month              # 月份是调用方给的事实,不接受模型的版本
        if not str(obj.get("narrative") or "").strip():
            last = "narrative 为空——没做编辑定调"
            continue
        fixed, repairs = repair_selection(obj, judgments)
        errs = validate_slate(fixed) + validate_selection(fixed, judgments)
        if errs:
            last = ";".join(errs[:5])
            continue
        return fixed, repairs
    raise SlateError(f"MA3 连续 {retries + 1} 次产不出合规 slate:{last}")
