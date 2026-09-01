"""SCHEMA.md 是数据契约文档,不许和代码里的键集打架。

2026-08-31 查实:business_view_isolation 一直在清理「乡村」这个废弃 impact 键,
program_gate 也只认三个键 —— 但 SCHEMA.md 的影响分析字段下**一直明写着**
`乡村: 乡村方向影响描述`。数据层因此始终干净(全库 0 篇把乡村当键),
可任何照着 schema 学数据模型的人或 agent,学到的都是四个键,
下游服务就按四个键写枚举,再由模型选中一个查无此物的业务线。

所以扫的不是数据,是**文档**:契约写错了,数据干净也没用。
"""
from pathlib import Path

import pytest

from scripts.business_view_isolation.inventory import (
    DEPRECATED_IMPACT_KEYS,
    EXPECTED_IMPACT_KEYS,
)

SCHEMA = Path(__file__).resolve().parents[2] / "SCHEMA.md"


@pytest.mark.parametrize("key", sorted(DEPRECATED_IMPACT_KEYS))
def test_schema_does_not_document_deprecated_impact_keys(key):
    lines = [
        f"{i}: {t.strip()}"
        for i, t in enumerate(SCHEMA.read_text(encoding="utf-8").splitlines(), 1)
        if t.strip().startswith(f"{key}:")
    ]
    assert not lines, f"SCHEMA.md 仍把废弃键「{key}」写成影响分析字段: {lines}"


@pytest.mark.parametrize("key", sorted(EXPECTED_IMPACT_KEYS))
def test_schema_documents_every_live_impact_key(key):
    """反向也要守:少写一个键,下游就会漏掉一条真实业务线。"""
    text = SCHEMA.read_text(encoding="utf-8")
    assert f"{key}:" in text, f"SCHEMA.md 缺少现行 impact 键「{key}」"
