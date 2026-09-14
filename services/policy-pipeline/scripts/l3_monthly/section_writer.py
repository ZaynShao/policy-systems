"""MA5b 省级综述 / MA5c 附录 / MA5e 概述 + 三大业务速判。

三段的共同点是**输入不是 RAW**:

- 综述与附录拿的是代码拼出的条目摘要(标题 / 落款 / MA2 的业务命中与理由)。
  综述是把已经判定过的东西串起来,不是对着原文再解读一遍——后者既贵又会和详情打架。
- 概述**最后写**,输入是已写完的各块。概述因此必然与正文一致;
  让它对着原文另想一遍,就会出现概述说的和正文写的不是一回事。

代码盯死的是业务速判:只有正文里真出过决策建议的业务线才配有一条速判。
每条业务线都硬凑一句是现有产线的病,凑出来的关联比没有更糟。
"""
from scripts.l3_monthly import budget, judge, prompts


DETAILED_SECTIONS = ("national_detail", "local_detail")


class SectionError(ValueError):
    """段落写不出来。宁可空着让上游看见,也不给一段看起来像样的东西。"""


def _caveat(gate, location, note):
    return {"gate": gate, "location": location, "note": note}


def digest(item, judgment, business_names):
    """给 MA5b/MA5c 的条目摘要:代码拼,**不含 RAW**。

    抽不到的字段直接不写。填「未知」这种占位会被当成事实抄进综述里去。
    """
    j = judgment or {}
    names = business_names or {}
    parts = [str(item.get("title") or item.get("policy_id") or "").strip()]
    # 已有独立详情块的,综述里点到即可——不标出来就会被再讲一遍
    if item.get("section") in DETAILED_SECTIONS:
        parts.append("已有独立详情块")
    for key in ("issuer_from_body", "issue_date_from_body"):
        val = str(j.get(key) or "").strip()
        if val:
            parts.append(val)
    hits = [names.get(h, h) for h in j.get("business_hits") or []]
    if hits:
        parts.append("涉及" + "、".join(hits))
    why = str(j.get("why") or "").strip()
    if why:
        parts.append(why)
    return " | ".join(p for p in parts if p)


def _text_section(client, system, user, retries, max_tokens):
    for attempt in range(retries + 1):
        out = (client.complete(system, user,
                               max_tokens=budget.escalate(max_tokens, attempt))
               or "").strip()
        if out:
            return out
    raise SectionError(f"连续 {retries + 1} 次写不出内容")


def write_roundup(client, profile_text, digests, month, retries=1, max_tokens=budget.SECTION):
    """MA5b 省级综述。本月没有地方条目就没有综述可写——空输入下不调模型。"""
    if not digests:
        return ""
    return _text_section(client, prompts.build_roundup_system(profile_text),
                         prompts.build_roundup_user(month, digests),
                         retries, max_tokens)


def write_appendix(client, profile_text, digests, month, retries=1, max_tokens=budget.SECTION):
    """MA5c 附录(国家级讲话 / 会议类信号)。同样,没条目就不写。"""
    if not digests:
        return ""
    return _text_section(client, prompts.build_appendix_system(profile_text),
                         prompts.build_appendix_user(month, digests),
                         retries, max_tokens)


def _covered_businesses(details, extra_hits=None):
    """速判的合法范围:正文里真出过决策建议的业务线,**加上只进了速览/附录的那些**。

    只看详情会漏掉一整条业务线:实测各期 shortlist 有 13–15% 是成品油调价这类
    周期性系列,它们按编辑口径进速览而不进详情,而它们恰恰全是加油线。
    只认详情的话,一个满是加油政策的月份会出一份「本月加油线没事」的月刊。
    """
    covered = {str(a.get("business") or "").strip()
               for d in details or [] for a in d.get("advice") or []
               if str(a.get("business") or "").strip()}
    covered |= {str(b).strip() for b in extra_hits or () if str(b).strip()}
    return covered


def _enforce_takes(raw_takes, details, businesses, extra_hits=None):
    order = [b.get("zh") for b in businesses or [] if b.get("zh")]
    covered = _covered_businesses(details, extra_hits)
    by_biz, caveats = {}, []
    for i, take in enumerate(raw_takes or []):
        take = take if isinstance(take, dict) else {}
        biz = str(take.get("business") or "").strip()
        text = str(take.get("text") or "").strip()
        loc = f"businessTakes[{i}]"
        if biz not in covered:
            caveats.append(_caveat("B", loc, f"「{biz}」本月正文里一条决策建议都没有,"
                                             "速判凭空多出一条,已删除"))
        elif not text:
            caveats.append(_caveat("F", loc, f"「{biz}」的速判正文为空,已删除"))
        elif biz in by_biz:
            caveats.append(_caveat("D", loc, f"「{biz}」重复出条,只保留第一条"))
        else:
            by_biz[biz] = {"business": biz, "text": text}
    for biz in sorted(covered - set(by_biz)):
        # 反向漏报:正文写了、速判没提,读者会以为本月这条线没事
        caveats.append(_caveat("B", "businessTakes",
                               f"正文里出过「{biz}」的决策建议,速判却漏了它"))
    takes = [by_biz[b] for b in order if b in by_biz]
    takes += [by_biz[b] for b in by_biz if b not in order]
    return takes, caveats


def write_overview(client, profile_text, details, businesses, month,
                   roundup="", appendix="", extra_hits=None,
                   retries=1, max_tokens=budget.SECTION):
    """MA5e。返回 (overview, businessTakes, caveats)。

    输入是**已写完的各块**——详情、省级综述、附录都要给,概述才可能与全篇一致;
    只给详情的话,只在综述里出现过的业务线会被判成「本月没事」。
    """
    system = prompts.build_overview_system(profile_text)
    user = prompts.build_overview_user(month, details, roundup, appendix)
    last = ""
    for attempt in range(retries + 1):
        try:
            obj = judge.extract_json(client.complete(
                system, user, max_tokens=budget.escalate(max_tokens, attempt)))
        except judge.JudgmentError as exc:
            last = str(exc)
            continue
        if (not isinstance(obj, dict) or not str(obj.get("overview") or "").strip()
                or not isinstance(obj.get("businessTakes"), list)):
            last = "缺 overview 或 businessTakes"
            continue
        takes, caveats = _enforce_takes(obj["businessTakes"], details,
                                        businesses, extra_hits)
        return str(obj["overview"]).strip(), takes, caveats
    raise SectionError(f"连续 {retries + 1} 次写不出合法概述:{last}")
