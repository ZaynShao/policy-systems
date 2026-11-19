"""System prompt 冒烟。

不测措辞,测**纪律条款还在不在**——整段 prompt 是产品口径,被误删一段
(比如"附件未采集"那条)不会有任何报错,但回答质量会静默崩掉。
"""
from __future__ import annotations

import datetime

import pytest

from app.prompts import DEFAULT_RECENT_DAYS, build_system_prompt

ANCHORS = [
    "逐字",  # 引文纪律
    "附件未采集",  # 数字不推算
    "失准",  # 评分只作信号
    "正文文头",  # 机关/日期以正文为准
    "编码损伤",  # 乱码处理
    "全称否定",  # 慎用"各省均未"
    "不预测",  # 能力边界
    "成品油调价",  # 业务边界
    "没有联网能力",  # 不谎称查网
    "同时废止",  # 文号抓错的判别法(冒烟实测编造过文号年份)
]


@pytest.mark.parametrize("anchor", ANCHORS)
def test_discipline_anchor_present(anchor):
    assert anchor in build_system_prompt(datetime.date(2026, 8, 17))


def test_today_is_injected():
    """模型不知道今天几号,而"最近""上个月"是本场景高频问法。"""
    prompt = build_system_prompt(datetime.date(2026, 8, 17))
    assert "2026-08-17" in prompt


def test_recent_window_precomputed():
    """把 90 天前的绝对日期算好给它,别让模型自己减。"""
    prompt = build_system_prompt(datetime.date(2026, 8, 17))
    expected = (datetime.date(2026, 8, 17) - datetime.timedelta(days=DEFAULT_RECENT_DAYS)).isoformat()
    assert expected in prompt
    assert expected == "2026-05-19"


def test_defaults_to_today_when_not_given():
    assert datetime.date.today().isoformat() in build_system_prompt()
