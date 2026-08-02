"""raw 政策 md → 对外公开记录。纯函数，无 I/O。

对外承诺（需求裁定，见 README）：
  1. 只出**政策原文**，不出任何派生产出物。
  2. 正文**原样**给，不去噪。
  3. 采集元数据只留原文链接与采集时间。

实现纪律：**白名单**投影，不是黑名单过滤。
全语料 provenance 有 41 个子字段（id_fixed_from / relevel_from /
body_pre_refetch_len / date_correction_reason ...），黑名单必漏。
白名单让 pipeline 将来新增的任何字段默认不外泄。
"""
from __future__ import annotations

import datetime
import re
from typing import Any, Mapping

import yaml

# --- 对外字段白名单 ---------------------------------------------------------
# 改动这三行 = 改动对外承诺。tests/public_export/test_redact.py 会挡住无意的放宽。
PUBLIC_TOP_FIELDS: tuple[str, ...] = ("id", "title", "official_number", "issuer", "date")
PUBLIC_REGION_FIELDS: tuple[str, ...] = ("level", "code", "name")
PUBLIC_PROVENANCE_FIELDS: tuple[str, ...] = ("url", "fetched_at")

# provenance.url / fetched_at 提升到顶层时的对外命名
_PROVENANCE_RENAME = {"url": "source_url", "fetched_at": "fetched_at"}

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n?", re.S)


class ExcludedPolicy(Exception):
    """该篇不应进入对外语料（重复件 / 核心字段缺失）。"""


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """切出 frontmatter 与正文。

    只认文件**开头**的 `---` 块，正文里的 `---` 分隔线不受影响。
    无 frontmatter 时返回 ({}, 原文)。

    正文只剥掉 frontmatter 之后的前导空行（与 pipeline 既有
    `scripts/sync/run_sync.py::_read_full_body` 一致，保证对外正文与内部
    同步到 Postgres 的正文逐字相同），其余内容不动。
    """
    m = _FRONTMATTER.match(text)
    if not m:
        return {}, text
    loaded = yaml.safe_load(m.group(1))
    fm = loaded if isinstance(loaded, Mapping) else {}
    return dict(fm), text[m.end():].lstrip("\n")


def _jsonable(value: Any) -> Any:
    """YAML 会把未加引号的日期解析成 date/datetime；对外记录必须 JSON-safe。"""
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, Mapping):
        return {k: _jsonable(v) for k, v in value.items()}
    return value


def _project(src: Mapping[str, Any] | None, allowed: tuple[str, ...]) -> dict[str, Any]:
    """白名单投影：只取 allowed 里存在的键。"""
    if not isinstance(src, Mapping):
        return {}
    return {k: _jsonable(src[k]) for k in allowed if k in src}


def to_public_record(fm: Mapping[str, Any], body: str) -> dict[str, Any]:
    """frontmatter + 正文 → 对外记录。不合格的抛 ExcludedPolicy。"""
    if fm.get("_duplicate_of"):
        raise ExcludedPolicy(f"known duplicate of {fm['_duplicate_of']}")
    if not str(fm.get("id") or "").strip():
        raise ExcludedPolicy("missing id")
    if not body.strip():
        raise ExcludedPolicy("empty body")

    rec: dict[str, Any] = _project(fm, PUBLIC_TOP_FIELDS)
    rec["region"] = _project(fm.get("region"), PUBLIC_REGION_FIELDS)
    for key, value in _project(fm.get("provenance"), PUBLIC_PROVENANCE_FIELDS).items():
        rec[_PROVENANCE_RENAME[key]] = value
    rec["body"] = body  # 原样，不去噪
    return rec


def to_index_entry(rec: Mapping[str, Any]) -> dict[str, Any]:
    """列表/检索用的轻量条目 —— 去掉 body，避免检索时拖动全文。"""
    return {k: v for k, v in rec.items() if k != "body"}
