"""业务战略画像的读取端(pipeline 侧)。

画像文件在 vault:`_meta/framework/business_strategy.yaml`。它把「公司业务是什么、
什么样的政策改变得了业务决策」写成数据,供 L2/L3 与 policy-qa 共用,
免得各自在提示词里手写一份——2026-08-31 查实,手写副本已经走散成三套词表。

**与 policy-qa 侧 app/strategy.py 的关系**:两边各有一个读取端,校验规则一致
(schema_version 白名单、status 必须 active、businesses 不能空),但渲染不同——
这边渲染给 pass2 写影响分析用,强调「每条业务线真正在乎哪些变量」;
那边渲染给问答检索用,强调高相关/压制清单。共用一份渲染反而两头都不合身。
仓里没有跨服务的 python 包,这份重复是有意接受的;校验规则若要改,两边一起改。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

SUPPORTED_SCHEMA_VERSIONS = frozenset({1})


class StrategyProfileError(RuntimeError):
    """画像不可用。**这里不软着陆**——见 load_strategy_profile 的说明。"""


def _one_line(text: Any) -> str:
    return " ".join(str(text or "").split())


def parse_strategy_profile(data: Any) -> dict:
    if not isinstance(data, dict):
        raise StrategyProfileError("画像文件根节点必须是映射")
    version = data.get("schema_version")
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise StrategyProfileError(
            f"schema_version={version!r} 不在支持范围 {sorted(SUPPORTED_SCHEMA_VERSIONS)}")
    if data.get("status") != "active":
        raise StrategyProfileError(
            f"画像 status={data.get('status')!r},只有 active 才会被加载")
    businesses = data.get("businesses")
    if not isinstance(businesses, list) or not businesses:
        raise StrategyProfileError("businesses 为空——没有业务线的画像没有意义")
    for biz in businesses:
        if not isinstance(biz, dict) or not biz.get("id") or not biz.get("zh"):
            raise StrategyProfileError(f"businesses 条目缺 id/zh: {biz!r}")
    return data


def load_strategy_profile(path: str | None) -> dict | None:
    """按路径加载画像。路径为空 → None(没配这个可选项,属正常)。

    **配了却读不出来就抛异常,不静默降级。**
    这和 policy-qa 侧的处理刻意相反:那边是在线问答,画像坏了还能答政策本身,
    降级是对的;这边是批量派生,一跑就是上千篇、结果直接落进 vault。
    静默用一套跟你以为的不一样的口径把全库写一遍,比不跑要糟得多。
    """
    if not (path or "").strip():
        return None
    target = Path(path)
    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    except OSError as exc:
        raise StrategyProfileError(f"画像文件读不出来: {target} ({exc})") from exc
    except yaml.YAMLError as exc:
        raise StrategyProfileError(f"画像文件不是合法 YAML: {target} ({exc})") from exc
    return parse_strategy_profile(raw)


def check_impact_keys(profile: dict, impact_keys: set[str]) -> None:
    """画像声明的 impact 键必须与 L2 实际会写的键一一对应。

    对不上就是配置错误:画像里多一条业务线,而 L2 根本不会写那个键,
    下游按画像去取就是恒空——空结果会被模型读成「库里没有」。
    「乡村」当初就是这么活了三个月的,所以这里宁可让批处理起不来。
    """
    declared = (profile.get("consistency") or {}).get("impact_keys") or {}
    if not isinstance(declared, dict) or not declared:
        raise StrategyProfileError("画像缺 consistency.impact_keys,无法与 L2 契约对账")
    if set(declared.values()) != set(impact_keys):
        raise StrategyProfileError(
            f"画像声明的 impact 键 {sorted(declared.values())} "
            f"与 L2 实际会写的 {sorted(impact_keys)} 不一致")


def render_for_impact_analysis(profile: dict) -> str:
    """渲染成 pass2 的业务口径段。

    只给「每条业务线在乎哪些变量」和判据,**不给信号清单**:pass2 面对的是
    已经确定的一篇政策,任务是写影响,不是判要不要看这篇。塞检索用的清单
    只会稀释注意力。也**不给定量目标**——画像里的数字全标了待核。
    """
    lines = [
        f"【公司业务口径】(战略画像 {profile.get('profile_id')},"
        f"生效 {profile.get('effective_from')})",
        "公司业务线只有下列这几条,影响分析的键与之一一对应:",
    ]
    for biz in profile["businesses"]:
        head = biz.get("headline") or ""
        lines.append(f"- {biz['zh']}({biz.get('weight_2026') or ''}):{head}")
        for var in biz.get("decision_variables") or []:
            lines.append(f"    · 在乎:{var}")

    rules = profile.get("relevance_rules") or {}
    core = _one_line(rules.get("core_test"))
    if core:
        lines += ["", f"判断影响大小的准绳:{core}"]

    absent = _one_line(rules.get("absent_is_not_low"))
    if absent:
        lines.append(f"注意:{absent}")

    gaps = [q.get("topic") for q in (profile.get("open_questions") or []) if q.get("topic")]
    if gaps:
        lines += [
            "",
            "下列维度画像里是空白。政策若落在这些维度上,照常按正文写影响,"
            "**不要**因为画像没写就判成「未直接涉及」:",
        ]
        lines += [f"- {g}" for g in gaps]
    return "\n".join(lines)
