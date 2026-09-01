"""业务线枚举:一处定义,处处派生,且不许长回废弃的口径。

为什么单开一个文件:2026-08-31 查实,「乡村」这条早在 2026-05-31 就被
框架判为退役(decision_framework.yaml 明写"非业务线、非输出类目"),
skill 里写着"退役原型,不得作专门考量点",prompts.py 里写着"不作专门考量点",
**但它同时还留在四个肯定式的枚举里**:BusinessLine 字面量、
BUSINESS_LINE_TO_IMPACT_KEY、planner 的 valid_lines、planner 字段描述。

结果是:模型照选不误。选中之后 L2 从来不写这个 impact 键(pipeline 侧
program_gate.py 只认三个键,business_view_isolation 还在主动清理),
于是 impact_match 返回 False,检索返回 0 条 —— 而空结果会被模型
读成"库里没有这类政策",比报错更糟,因为它看起来像个结论。

教训写成断言:**否定句降低不了概率,删枚举才行**。所以这里守两件事——
枚举只有一份(派生关系不许断),以及退役口径不许再出现在源码里。
"""
from __future__ import annotations

import tokenize
import typing
from pathlib import Path

import pytest

from app.planner import PLANNER_PROMPT, RetrievalPlan, _sanitize
from app.store import (
    BUSINESS_LINE_SCOPE,
    BUSINESS_LINE_TO_IMPACT_KEY,
    BusinessLine,
    ThemeInfo,
)

#: pipeline 侧 scripts/l2_themescore/program_gate.py 的 IMPACT_KEYS 副本。
#: 这是**跨仓契约**:L2 只会写这三个键,写别的会被 program_gate 判废。
#: 两边不一致时改的应该是本服务,不是把这里改宽。
PIPELINE_IMPACT_KEYS = {"加油", "充电", "电力_储能_V2G_交易"}

#: 已判退役、不得再作为业务线出现的口径。
#: 「乡村」:2026-05-31 去污染判为非业务线,涉乡村充电的影响并入「充电」。
RETIRED_LINES = ("乡村",)

APP_DIR = Path(__file__).resolve().parents[1] / "app"


def test_impact_keys_match_pipeline_contract():
    """本服务认的 impact 键 == L2 实际会写的键。多一个就是静默空结果。"""
    assert set(BUSINESS_LINE_TO_IMPACT_KEY.values()) == PIPELINE_IMPACT_KEYS


def test_business_line_literal_derives_from_the_single_map():
    """BusinessLine 字面量与映射表必须同步——它俩分开写,就是当初漏删的原因。"""
    assert typing.get_args(BusinessLine) == tuple(BUSINESS_LINE_TO_IMPACT_KEY)


def test_scope_covers_exactly_the_same_lines():
    """注入提示词的口径,不能比枚举多也不能少:多了模型会选,少了模型不知道。"""
    assert set(BUSINESS_LINE_SCOPE) == set(BUSINESS_LINE_TO_IMPACT_KEY)


def test_planner_whitelist_derives_from_the_single_map():
    """planner 的白名单是 set(映射表),不是另抄一份。抄一份就会再次走散。"""
    plan = RetrievalPlan(kind="survey", business_lines=list(BUSINESS_LINE_TO_IMPACT_KEY))
    assert _sanitize(plan, []).business_lines == list(BUSINESS_LINE_TO_IMPACT_KEY)


@pytest.mark.parametrize("line", RETIRED_LINES)
def test_retired_line_is_dropped_by_planner(line):
    """就算模型硬编出退役口径,也不许进入检索计划。"""
    plan = RetrievalPlan(kind="survey", business_lines=[line, "充电"])
    assert _sanitize(plan, []).business_lines == ["充电"]


@pytest.mark.parametrize("line", RETIRED_LINES)
def test_retired_line_absent_from_planner_prompt(line):
    """渲染后的规划提示词里不许出现退役口径——模型看见就会选。"""
    rendered = PLANNER_PROMPT.format(
        today="2026-08-31",
        recent_from="2026-06-02",
        themes="  - charging_infra(充电基础设施,151 篇)",
        business_lines="、".join(f"{k}({v})" for k, v in BUSINESS_LINE_SCOPE.items()),
        question="最近有哪些对充电影响大的政策",
    )
    assert line not in rendered
    for name in BUSINESS_LINE_TO_IMPACT_KEY:
        assert name in rendered


def _lines_reaching_the_model(path: Path) -> list[tuple[int, str]]:
    """源码里**会进入模型上下文**的部分:去掉 # 注释,其余全留。

    这条边界是有讲究的:`#` 注释只给人看,写清楚历史反而有价值;
    但 docstring 不同——pydantic-ai 拿工具的 docstring 生成 schema 描述,
    字面量、字段 description、提示词模板更是直接喂进去。所以只豁免 # 注释。
    """
    src = path.read_text(encoding="utf-8")
    dropped: dict[int, list[tuple[int, int]]] = {}
    with path.open("rb") as fh:
        for tok in tokenize.tokenize(fh.readline):
            if tok.type == tokenize.COMMENT:
                dropped.setdefault(tok.start[0], []).append((tok.start[1], tok.end[1]))
    out = []
    for i, text in enumerate(src.splitlines(), 1):
        for start, end in reversed(dropped.get(i, [])):
            text = text[:start] + text[end:]
        out.append((i, text))
    return out


@pytest.mark.parametrize("line", RETIRED_LINES)
def test_retired_line_never_reaches_the_model(line):
    """扫描全服务源码:退役口径不许出现在任何会进模型上下文的位置。

    这条是本文件的主张所在。写一句"XX 已退役,不要用"看起来是修好了,
    实际上把这个词又送进了模型的上下文——它照选不误。真正的修法是让它不出现。
    历史背景要留就留在 `#` 注释或本文件里,那些地方模型看不到。
    """
    offenders = [
        f"{path.relative_to(APP_DIR)}:{i}"
        for path in sorted(APP_DIR.rglob("*.py"))
        for i, text in _lines_reaching_the_model(path)
        if line in text
    ]
    assert not offenders, f"退役口径「{line}」仍会进入模型上下文: {offenders}"
