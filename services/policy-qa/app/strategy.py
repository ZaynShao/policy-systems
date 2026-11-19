"""公司业务战略画像:让「业务符合度」有个可替换的依据,而不是散在提示词里。

为什么需要它:2026-08-31 查实,这条链路上判断「政策与业务是否相关」的逻辑
**没有单一出处**——L2 靠 themes_registry 挂主题,月刊 skill 手写一份业务边界,
本服务的 prompts.py 又手写一份,三处口径互不相同,而库里唯一忠实于战略背景文档的
decision_framework.yaml 全仓零代码引用。手写副本的代价是走散:同一批业务线,
三套词表,枚举里还留着早已判退役的类目。

所以画像做成**数据**而不是提示词:一个 YAML,消费方 load 它渲染提示词。
战略会变,换战略 = 换文件,不改代码。

失败要软着陆。画像是增强不是必需路径:文件缺失、损坏、schema 不认识,
一律返回 None 并记一条 warning,服务照常起、照常答——只是不做业务框定。
让一个可选的参照文件把问答服务带崩是本末倒置。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("policy-qa")

#: 本服务认识的 schema 版本。画像文件写了别的版本就拒绝加载——
#: 与其按旧结构猜新文件的字段,不如明确地不加载。
SUPPORTED_SCHEMA_VERSIONS = frozenset({1})

#: 渲染进提示词时,信号只取这两档:high 提召回,suppress 压误判。
#: medium 主要供人工复核,进提示词只会稀释注意力。
RENDERED_WEIGHTS = ("high", "suppress")


class StrategyError(RuntimeError):
    """画像文件不可用。仅在显式校验路径抛出;load_profile 吞掉并返回 None。"""


@dataclass(frozen=True)
class StrategyProfile:
    """一版业务战略画像。字段只保留渲染提示词与自检要用的部分。"""

    profile_id: str
    effective_from: str
    source_title: str
    businesses: tuple[dict[str, Any], ...]
    relevance_rules: dict[str, str]
    signals: tuple[dict[str, Any], ...]
    open_questions: tuple[dict[str, Any], ...]
    path: str

    @property
    def business_ids(self) -> tuple[str, ...]:
        return tuple(b["id"] for b in self.businesses)

    def render(self) -> str:
        """渲染成注入 system prompt 的一段话。

        刻意**不渲染定量目标**:画像里的数字全部标了「数字待核」(ASR 转写,
        已知易错),而政策相关性判断根本不需要它们。把不可信的数字送进上下文,
        只会等着模型某天把它当事实引用出来。
        """
        lines = [
            f"【业务口径与相关性判据】(战略画像 {self.profile_id},生效 {self.effective_from};"
            f"源自《{self.source_title}》)",
            "",
            "公司业务线只有下列几条,没有第四条:",
        ]
        for biz in self.businesses:
            weight = biz.get("weight_2026") or ""
            head = biz.get("headline") or ""
            lines.append(f"- **{biz['zh']}**({weight}):{head}")
            for var in biz.get("decision_variables") or []:
                lines.append(f"    · 决策变量:{var}")

        rules = self.relevance_rules
        lines += ["", "判断一条政策是否与业务相关:"]
        for key in ("core_test", "high_form", "low_form", "early_signal"):
            text = _one_line(rules.get(key))
            if text:
                lines.append(f"- {text}")

        low = [s for s in self.signals if s.get("weight") == "suppress"]
        if low:
            lines += ["", "**以下类型见到就压低,不要当成「对业务影响大的政策」报上来**:"]
            lines += [f"- {s['what']} —— {s['changes']}" for s in low]

        high = [s for s in self.signals if s.get("weight") == "high"]
        if high:
            lines += ["", "**以下类型属高相关,检索到应优先展开**:"]
            lines += [f"- {s['what']}" for s in high]

        if self.open_questions:
            lines += [
                "",
                "**下列维度画像里是空白(材料未覆盖)。落在这些维度上的政策,"
                "说明「需人工裁定」,不要自行判定为不相关**:",
            ]
            lines += [f"- {q['topic']}" for q in self.open_questions]

        absent = _one_line(rules.get("absent_is_not_low"))
        if absent:
            lines += ["", f"注意:{absent}"]
        return "\n".join(lines)


def _one_line(text: Any) -> str:
    """把 YAML 块标量压成一行。

    画像里的判据写成 `|` 多行是为了人读着舒服,但渲染成 markdown bullet 时,
    内部换行会让第二行顶格,看起来像另起了一条。模型对结构敏感,别给它歧义。
    """
    return " ".join(str(text or "").split())


def _as_tuple(raw: Any, field: str) -> tuple[Any, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise StrategyError(f"{field} 必须是列表,实际是 {type(raw).__name__}")
    return tuple(raw)


def parse_profile(data: Any, *, path: str = "<inline>") -> StrategyProfile:
    """把 YAML 数据结构校验成 StrategyProfile。校验不过就抛,不猜。"""
    if not isinstance(data, dict):
        raise StrategyError("画像文件根节点必须是映射")

    version = data.get("schema_version")
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise StrategyError(
            f"schema_version={version!r} 不在支持范围 {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
        )

    status = data.get("status")
    if status != "active":
        # 换战略时旧画像会被标成 superseded 留在库里。指到一份非 active 的文件
        # 通常意味着配置没跟着换,这时候静默用旧战略比不加载更危险。
        raise StrategyError(f"画像 status={status!r},只有 active 才会被加载")

    businesses = _as_tuple(data.get("businesses"), "businesses")
    if not businesses:
        raise StrategyError("businesses 为空——没有业务线的画像没有意义")
    for biz in businesses:
        for key in ("id", "zh"):
            if not (isinstance(biz, dict) and biz.get(key)):
                raise StrategyError(f"businesses 条目缺 {key}: {biz!r}")

    signals = _as_tuple(data.get("signals"), "signals")
    for sig in signals:
        if not isinstance(sig, dict) or not sig.get("what"):
            raise StrategyError(f"signals 条目缺 what: {sig!r}")
        weight = sig.get("weight")
        if weight in RENDERED_WEIGHTS and not sig.get("changes") and weight == "suppress":
            raise StrategyError(f"suppress 信号必须写明 changes(压制理由): {sig.get('id')!r}")

    rules = data.get("relevance_rules") or {}
    if not isinstance(rules, dict):
        raise StrategyError("relevance_rules 必须是映射")
    if not (rules.get("core_test") or "").strip():
        raise StrategyError("relevance_rules.core_test 不能为空——它是整份画像的判据核心")

    return StrategyProfile(
        profile_id=str(data.get("profile_id") or "unnamed"),
        effective_from=str(data.get("effective_from") or "未标注"),
        source_title=str((data.get("source") or {}).get("title") or "未标注"),
        businesses=businesses,
        relevance_rules={k: str(v) for k, v in rules.items()},
        signals=signals,
        open_questions=_as_tuple(data.get("open_questions"), "open_questions"),
        path=path,
    )


def load_profile(path: str | None) -> StrategyProfile | None:
    """按路径加载画像。**任何失败都吞掉并返回 None**——退回不做业务框定的行为。

    path 为空表示没配这个可选项,属正常情况,不记 warning。
    """
    if not (path or "").strip():
        return None
    target = Path(path)
    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8"))
        profile = parse_profile(raw, path=str(target))
    except FileNotFoundError:
        logger.warning("业务战略画像文件不存在,本次不做业务框定: %s", target)
        return None
    except (OSError, yaml.YAMLError, StrategyError) as exc:
        logger.warning("业务战略画像加载失败,本次不做业务框定: %s (%s)", target, exc)
        return None
    logger.info(
        "已加载业务战略画像 %s(生效 %s,业务线 %s,信号 %d 条): %s",
        profile.profile_id,
        profile.effective_from,
        "/".join(b["zh"] for b in profile.businesses),
        len(profile.signals),
        target,
    )
    return profile
