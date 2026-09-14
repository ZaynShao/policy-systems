"""MA7 返修:≤2 轮,仍不过**照常发布**并挂容错提示。

口径是用户定的:审计门不过**不是不发布**,而是把过不了的地方明说出来
(「因 AI 出稿某部分可能不够符合要求,敬请谅解」),再给人工修改意见栏回炉。
所以 run_repair **永远不抛异常**——它交出稿子和一张残留清单。

两条设计:

- **只重写被点名的那一段**。整篇重写会把已经过关的部分重新掷一次骰子,
  而且没法说清这一轮到底改好了什么。
- **改不好就退回原文**。返修可能引入新违规;拿严重度加权分比一比,不是严格变好
  就不采用——原文至少是带着完整上下文写出来的,而且这样不会白烧掉一轮。
"""
import copy

from scripts.l3_monthly import budget, fact_gate, gates, prompts

SEVERITY_WEIGHT = {"BLOCKER": 100, "MAJOR": 10, "MINOR": 1}
MAX_ROUNDS = 2


def iter_blocks(content):
    """(location, text, setter) 三元组。location 就是 caveats 里那个定位串。"""
    items = []
    for key in ("overview", "localRoundup", "appendix"):
        if str(content.get(key) or "").strip():
            items.append((key, content[key],
                          lambda v, k=key: content.__setitem__(k, v)))
    for i, take in enumerate(content.get("businessTakes") or []):
        if str(take.get("text") or "").strip():
            items.append((f"businessTakes[{i}].text", take["text"],
                          lambda v, t=take: t.__setitem__("text", v)))
    for det in content.get("details") or []:
        no = det.get("no")
        for key in ("info", "reading", "focus"):
            if str(det.get(key) or "").strip():
                items.append((f"details[{no}].{key}", det[key],
                              lambda v, d=det, k=key: d.__setitem__(k, v)))
        for j, adv in enumerate(det.get("advice") or []):
            if str(adv.get("text") or "").strip():
                items.append((f"details[{no}].advice[{j}].text", adv["text"],
                              lambda v, a=adv: a.__setitem__("text", v)))
    return items


def block_texts(content):
    """成稿里可定位、可单独返修的最小段。"""
    return {loc: text for loc, text, _ in iter_blocks(content)}


def sources_for(location, content, bundles):
    """这一段的事实源。

    详情块**只认它自己那一个 bundle**——那正是分块写作的意义:写第 3 篇时看不到
    第 5 篇的材料,就编不出跨篇的事实。概述与综述是从已写完的各块收上来的,
    故以各块正文加本期结构计数为源。
    """
    bundles = bundles or {}
    if location.startswith("details["):
        pid = _pid_of(location, content)
        return [bundles[pid]] if pid in bundles else []
    written = [str(d.get(k) or "") for d in content.get("details") or []
               for k in ("info", "reading", "focus")]
    return list(bundles.values()) + written + [fact_gate.editorial_source(content)]


def audit_blocks(content, profile, bundles=None, fact_client=None):
    """按段跑 MA6 的三道门(D 门 / 业务口径门 / F 门),每条违规带上 location。

    按段跑而不是整篇跑,是为了让 MA7 有得返修——整篇跑只拿得到行号,
    行号对不上稿件结构,就只能整篇重写。F 门也只有按段跑才知道该拿哪个 bundle 对。
    """
    out = []
    for loc, text, _ in iter_blocks(content):
        for violation in gates.run_gates(text, profile):
            item = dict(violation)
            item["location"] = loc
            out.append(item)
        srcs = sources_for(loc, content, bundles)
        unbacked = fact_gate.check_facts(text, srcs, location=loc)
        out += fact_gate.adjudicate(fact_client, unbacked, srcs)
    return sorted(out, key=lambda v: (gates.SEVERITY_ORDER.index(v["severity"]),
                                      v["location"]))


def _score(violations):
    return sum(SEVERITY_WEIGHT.get(v["severity"], 1) for v in violations)


def _pid_of(location, content):
    if not location.startswith("details["):
        return None
    no = location[len("details["):].split("]")[0]
    for det in content.get("details") or []:
        if str(det.get("no")) == no:
            return det.get("policyId")
    return None


def _to_caveat(violation):
    """残留 → 前端容错提示条的一条。字段名对齐 spec §7.1 的 content.caveats。"""
    return {"gate": violation["gate"], "rule": violation["rule"],
            "severity": violation["severity"], "location": violation["location"],
            "note": f"{violation['note']}(原文:{violation['quote']})"}


def _repair_round(client, content, bundles_by_pid, profile, violations, max_tokens):  # noqa: C901
    by_loc = {}
    for v in violations:
        by_loc.setdefault(v["location"], []).append(v)
    blocks = {loc: setter for loc, _, setter in iter_blocks(content)}
    texts = block_texts(content)
    for loc, items in by_loc.items():
        if loc not in blocks:
            continue
        bundle = bundles_by_pid.get(_pid_of(loc, content)) or ""
        user = prompts.build_repair_user(loc, texts[loc], items, bundle)
        try:
            new = (client.complete(prompts.REPAIR_SYSTEM, user,
                                   max_tokens=max_tokens) or "").strip()
        except Exception:  # noqa: BLE001 —— 一段修不成不该毁掉整期,它会变成 caveat
            continue
        srcs = sources_for(loc, content, bundles_by_pid)
        after = gates.run_gates(new, profile) + fact_gate.check_facts(new, srcs, loc)
        if not new or _score(after) >= _score(items):
            continue
        blocks[loc](new)


def run_repair(client, content, bundles_by_pid, profile,
               max_rounds=MAX_ROUNDS, max_tokens=budget.REPAIR, adjudicate_facts=True):
    """返回 (content, caveats, rounds)。**不抛异常**——过不了也照常发布。

    adjudicate_facts:F 门里代码匹配不上的,交同一个 client 判是否等价表述;
    关掉就是纯代码判定(更严,也更省)。
    """
    content = copy.deepcopy(content)
    fc = client if adjudicate_facts else None
    violations = audit_blocks(content, profile, bundles_by_pid, fc)
    rounds = 0
    while violations and rounds < max_rounds:
        rounds += 1
        _repair_round(client, content, bundles_by_pid or {}, profile,
                      violations, max_tokens)
        violations = audit_blocks(content, profile, bundles_by_pid, fc)
    return content, [_to_caveat(v) for v in violations], rounds
