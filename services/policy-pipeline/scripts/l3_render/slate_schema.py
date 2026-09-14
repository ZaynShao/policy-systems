"""slate.json 的结构校验。

slate 是编辑定调的落点,MA3 产出、MA4 装包消费。坏 slate 若不在此拦下,
要到装包甚至写作阶段才炸,那时已经花掉一轮 LLM 钱。
**只校验结构**;配额(national_detail 上限等)属选目策略,在 MA3 侧校验。
"""
import re

SECTIONS = ("national_detail", "local_detail", "roundup", "appendix")
REQUIRED_ITEM_KEYS = ("policy_id", "title_hint", "why")
MONTH_RE = re.compile(r"^20\d{2}-(0[1-9]|1[0-2])$")


def validate_slate(obj):
    """返回错误列表;空列表 = 通过。不抛异常——调用方要能一次看全所有问题。"""
    errs = []
    if not isinstance(obj, dict):
        return ["slate 根节点必须是对象"]

    month = obj.get("month")
    if not isinstance(month, str) or not MONTH_RE.match(month):
        errs.append(f"month 必须形如 YYYY-MM,当前 {month!r}")

    if not isinstance(obj.get("narrative"), str) or not obj["narrative"].strip():
        errs.append("narrative 缺失或为空——本月定调是编辑判断的落点,不能空")

    sections = obj.get("sections")
    if not isinstance(sections, dict):
        return errs + ["sections 必须是对象"]

    for name in sections:
        if name not in SECTIONS:
            errs.append(f"未知 section {name!r}(允许:{'/'.join(SECTIONS)})")

    seen = {}
    for name in SECTIONS:
        items = sections.get(name, [])
        if not isinstance(items, list):
            errs.append(f"sections.{name} 必须是数组")
            continue
        for idx, it in enumerate(items):
            where = f"sections.{name}[{idx}]"
            if not isinstance(it, dict):
                errs.append(f"{where} 必须是对象")
                continue
            for k in REQUIRED_ITEM_KEYS:
                if not str(it.get(k) or "").strip():
                    errs.append(f"{where} 缺 {k}")
            pid = it.get("policy_id")
            if pid:
                if pid in seen:
                    errs.append(f"policy_id {pid} 重复出现于 {seen[pid]} 与 {where}"
                                f"——同一篇不得跨 section 重复计数")
                else:
                    seen[pid] = where
    return errs
