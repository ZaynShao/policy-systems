"""MA5a:每篇详情块写作。

只喂**它自己那一个 bundle**,所以它天然写不出跨篇杜撰;短上下文也便宜、可并发、
错一篇不毁全局。留给模型的是「这篇对我们意味着什么」,**约束一律由代码执行**:

- 决策建议不许溢出 MA2 算出的 business_hits。现有产线的病之一就是每篇都对三条业务线
  各说一句,凑出来的关联比没有更糟。
- 行动标签取自 D 门那一份白名单——白名单只有一份,在 gates 里,这里再抄一份就会走散。
- 编号 / policy_id / 标题由代码填,不交给模型:已知的事实交出去就有写错的机会。

写不出合法结构就报错,**不兜底编一段**——编出来的段落事后查不出来。
"""
from scripts.l3_monthly import budget, gates, judge, prompts

REQUIRED = ("info", "reading", "focus", "advice")
TEXT_KEYS = ("info", "reading", "focus")


class DetailError(ValueError):
    """详情块写不出来。宁可让上游看见,也不给一段看起来像样的东西。"""


def _caveat(gate, location, note):
    return {"gate": gate, "location": location, "note": note}


def parse_detail(text):
    """取出并校验详情块 JSON。围栏与前后废话都容忍;缺段或空段则抛。"""
    try:
        obj = judge.extract_json(text)
    except judge.JudgmentError as exc:
        raise DetailError(str(exc)) from exc
    if not isinstance(obj, dict):
        raise DetailError("输出 JSON 不是对象")
    missing = [k for k in REQUIRED if k not in obj]
    if missing:
        raise DetailError(f"缺字段: {missing}")
    for k in TEXT_KEYS:
        if not isinstance(obj[k], str) or not obj[k].strip():
            # 空段不是「这篇没什么好说的」,是模型没写出来;留空会一路进稿。
            raise DetailError(f"{k} 为空")
    if not isinstance(obj["advice"], list):
        raise DetailError("advice 必须是数组")
    return obj


def enforce_advice(detail, business_hits, business_names, location="details"):
    """按 MA2 的 business_hits 修剪决策建议。返回 (detail, caveats)。

    只删不改:模型多写的业务线是凭空生出来的关联,删掉;它写对的那些原样保留。
    每条删除都记一条 caveat,免得静默瘦身之后没人知道这里曾经有过东西。
    """
    names = business_names or {}
    allowed = {names.get(h, h) for h in business_hits or []}
    kept, caveats, seen = [], [], set()
    for i, entry in enumerate(detail.get("advice") or []):
        entry = entry if isinstance(entry, dict) else {}
        biz = str(entry.get("business") or "").strip()
        tag = str(entry.get("tag") or "").strip()
        text = str(entry.get("text") or "").strip()
        loc = f"{location}.advice[{i}]"
        if biz not in allowed:
            caveats.append(_caveat(
                "B", loc, f"决策建议写了「{biz}」,而 MA2 判定的业务命中是 "
                          f"{'、'.join(sorted(allowed)) or '(空)'},已删除该条"))
        elif tag not in gates.ALLOWED_TAGS:
            caveats.append(_caveat(
                "D", loc, f"行动标签「{tag}」不在白名单 {sorted(gates.ALLOWED_TAGS)} 内,已删除该条"))
        elif not text:
            caveats.append(_caveat("F", loc, f"「{biz}」的建议正文为空,已删除该条"))
        elif biz in seen:
            caveats.append(_caveat("D", loc, f"「{biz}」重复出条,只保留第一条"))
        else:
            seen.add(biz)
            kept.append({"business": biz, "tag": tag, "text": text})
            continue
    out = dict(detail)
    out["advice"] = kept
    return out, caveats


def write_detail(client, profile_text, bundle_text, judgment, no, policy_id, title,
                 business_names, style_sample=None, retries=1, max_tokens=budget.WRITE):
    """写一篇详情块。返回 (detail, caveats);连续失败抛 DetailError。"""
    system = prompts.build_detail_system(profile_text, style_sample)
    user = prompts.build_detail_user(bundle_text)
    last = ""
    for attempt in range(retries + 1):
        try:
            detail = parse_detail(client.complete(system, user,
                                  max_tokens=budget.escalate(max_tokens, attempt)))
        except DetailError as exc:
            last = str(exc)
            continue
        loc = f"details[{no}]"
        detail, caveats = enforce_advice(detail, judgment.get("business_hits"),
                                         business_names, loc)
        detail.update({"no": no, "policyId": policy_id, "title": title})
        if judgment.get("dq"):
            # MA2 标过的数据质量问题要跟着成稿走,不能写完就把警告丢了
            caveats.append(_caveat("F", loc, f"MA2 数据质量提示:{judgment['dq']}"))
        return detail, caveats
    raise DetailError(f"连续 {retries + 1} 次写不出合法详情块:{last}")
