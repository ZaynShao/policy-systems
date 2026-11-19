"""MA2:逐篇归属判定。

每篇一次独立调用、短上下文:便宜、可并发、可重试,错一篇不毁全局。
这也是「业务需求不准」的修点——业务口径由 render_for_monthly() 从战略画像渲染,
不写死在提示词里。

两条硬规则由**代码**执行,不靠模型自觉:
- 输出必须是合法 JSON 且字段齐全、枚举合法,否则重试;重试仍失败标 error,
  **不兜底成一个假判定**——假判定会一路混进选目,而且事后查不出来。
- 落在画像 scope_absent 维度上的政策,模型判 low 一律改判「需人工裁定」
  (画像 relevance_rules.absent_is_not_low 的原文要求:证据为空不等于业务无关)。
"""
import json
import re

from scripts.l3_monthly import budget, prompts

BUSINESS_IDS = ("fuel", "charging", "power")
RELEVANCE = ("high", "medium", "low", "需人工裁定")
REQUIRED = ("level", "issue_date_from_body", "issuer_from_body",
            "official_number_from_body", "business_hits",
            "decision_variables_touched", "relevance", "why", "dq")

_SPLIT = re.compile(r"[/、,，()（）\s]+")
_PAREN = re.compile(r"[(（]([^)）]*)[)）]")
_STRIP = "「」『』《》【】\"'“”‘’ \t"
_ZERO_COUNT = re.compile(r"0\s*次")


class JudgmentError(ValueError):
    """模型输出不可用。**不软着陆**:宁可标 error 让下游看见,也不编一个判定。"""


def _tokens(text):
    return {t.strip(_STRIP) for t in _SPLIT.split(text or "") if 2 <= len(t.strip(_STRIP)) <= 8}


def absent_terms(profile):
    """从画像抽「材料空白」维度的词表。

    只认 `<维度列表>:<...0 次...>` 这种形状。电力线那条
    「『充电站/充电桩』二词 0 次 —— 原文一律说…」讲的是**用词习惯**不是业务空白,
    它没有冒号,因此被排除——否则几乎每篇充电政策都会被强制改判,整期详情就空了。
    """
    terms = set()
    for biz in profile.get("businesses") or []:
        for entry in biz.get("scope_absent") or []:
            head, sep, tail = str(entry).partition(":")
            if not sep:
                head, sep, tail = str(entry).partition(":")
            if not sep or not _ZERO_COUNT.search(tail):
                continue
            terms |= _tokens(head)
    for q in profile.get("open_questions") or []:
        topic = str(q.get("topic") or "")
        for m in _PAREN.findall(topic):
            terms |= _tokens(m)
        terms |= _tokens(_PAREN.sub("", topic))
    return {t for t in terms if t}


def extract_json(text):
    """从模型输出里取出 JSON 对象。代码围栏、前后废话都容忍。MA2 与 MA3 共用。"""
    raw = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", raw, re.S)
    if m:
        raw = m.group(1).strip()
    else:
        i, j = raw.find("{"), raw.rfind("}")
        if i >= 0 and j > i:
            raw = raw[i:j + 1]
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise JudgmentError(f"输出不是合法 JSON: {exc}") from exc


def parse_judgment(text, business_ids=BUSINESS_IDS):
    """从模型输出里取出并校验判定 JSON。围栏、前后废话都容忍;字段不全或枚举非法则抛。"""
    obj = extract_json(text)
    if not isinstance(obj, dict):
        raise JudgmentError("输出 JSON 不是对象")
    missing = [k for k in REQUIRED if k not in obj]
    if missing:
        raise JudgmentError(f"缺字段: {missing}")
    if obj["relevance"] not in RELEVANCE:
        raise JudgmentError(f"relevance 取值非法: {obj['relevance']!r}")
    if obj["level"] not in ("国家", "地方"):
        raise JudgmentError(f"level 取值非法: {obj['level']!r}")
    hits = obj["business_hits"]
    if not isinstance(hits, list) or any(h not in business_ids for h in hits):
        raise JudgmentError(f"business_hits 非法: {hits!r}(只能取 {list(business_ids)})")
    if not isinstance(obj["decision_variables_touched"], list):
        raise JudgmentError("decision_variables_touched 必须是数组")
    return obj


def enforce_rules(judgment, text, terms):
    """代码侧执行画像的 absent_is_not_low:落在空白维度上的不得自动判低。

    只在模型判 **low** 时改判——规则原文是「不得自动判低相关」,不是「一律改判」。
    改判理由写进 dq,否则下游看不出这条为什么是「需人工裁定」。
    """
    if judgment.get("relevance") != "low":
        return judgment
    hit = sorted(t for t in (terms or set()) if t and t in (text or ""))
    if not hit:
        return judgment
    judgment["relevance"] = "需人工裁定"
    note = f"命中画像空白维度({'、'.join(hit)}),证据为空不等于业务无关,改判需人工裁定"
    judgment["dq"] = f"{judgment.get('dq') or ''}{'；' if judgment.get('dq') else ''}{note}"
    return judgment


def judge_one(client, profile_text, terms, candidate, raw_head, retries=1,
              max_tokens=budget.JUDGE):
    """判一篇。返回带 policy_id 的判定字典;连续失败返回 relevance='error' 的记录。"""
    system = prompts.build_judge_system(profile_text)
    user = prompts.build_judge_user(candidate.title, raw_head)
    last = ""
    for attempt in range(retries + 1):
        try:
            out = client.complete(system, user,
                                  max_tokens=budget.escalate(max_tokens, attempt))
            j = parse_judgment(out)
        except JudgmentError as exc:
            last = str(exc)
            continue
        j = enforce_rules(j, f"{candidate.title}\n{raw_head}", terms)
        j.update(_carry(candidate))
        return j
    err = {"level": "", "issue_date_from_body": "", "issuer_from_body": "",
           "official_number_from_body": "", "business_hits": [],
           "decision_variables_touched": [], "relevance": "error", "why": "",
           "dq": f"模型输出连续 {retries + 1} 次不可用:{last}"}
    err.update(_carry(candidate))
    return err


def _carry(candidate):
    """MA1 的标记位要跟着判定走到 MA3——选目时它得知道哪些是同一份文件的多次采集、
    哪些 policy_id 挂了不止一份(那种必须给 title_hint 才定位得到)。"""
    return {"policy_id": candidate.policy_id, "title": candidate.title,
            "near_dup_group": candidate.near_dup_group,
            "id_collision": candidate.id_collision,
            "docno_conflict": candidate.docno_conflict,
            "series_group": candidate.series_group,
            "series_size": candidate.series_size}
