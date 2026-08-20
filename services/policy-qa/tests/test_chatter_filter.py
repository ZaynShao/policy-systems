"""答复开头的规划自语过滤。

这是第三道防线:prompt 说"不要写思考过程"没管住,`===答复===` 分隔标记也
只在模型愿意用时有效(实测两次跑,一次用了一次没用)。所以补一层确定性的。

**本文件的重点是"不许误删"。** 漏删一句自语只是难看;删掉正文是数据事故,
而用户不会知道自己少看了什么。所以下面反向用例比正向用例多。
"""
from __future__ import annotations

import pytest

from app.agent import strip_leading_chatter

# 三段都是真模型在 2026-08-18 实测中吐出来的原话
REAL_SAMPLES = [
    "我有充分材料支撑回答了。下面给出最终答复。",
    "我已读取了足够多关键文件的原文。现在整理最终答复。",
    "我已经读取了核心的国家级政策和几篇关键省级文件的原文。现在整理回答。让我确认一下需要包含的关键信息。",
]


@pytest.mark.parametrize("chatter", REAL_SAMPLES)
def test_real_world_chatter_is_stripped(chatter):
    body = "## 结论\n\n库内影响最大的是六部门三年倍增行动方案。"
    assert strip_leading_chatter(chatter + "\n" + body).startswith("## 结论")


def test_refusal_is_not_chatter():
    """"我只覆盖能源政策库"是**正经答复**,只有自称、没有流程词,不该被删。

    这是拒答闲聊时的标准回复,删掉用户就什么都看不到了。
    """
    text = "我只覆盖能源政策库,其他行业的问题回答不了。"
    assert strip_leading_chatter(text) == text


def test_required_disclosures_survive():
    """预算耗尽/检索失败时的交代是 prompt **要求**模型写的,不能当自语删掉。

    它们有流程词但没有自称,正是两条件取交集的用意。
    """
    for text in (
        "检索轮次已达上限,以下基于已检索到的部分:江苏那份通知要求……",
        "部分检索未成功,以下基于已取得的材料:充电桩建设目标为10万个。",
    ):
        assert strip_leading_chatter(text) == text


def test_first_person_content_in_the_body_is_untouched():
    """只从开头剥,正文里的第一人称一个字都不能动。"""
    text = "## 结论\n\n该件影响有限。我建议重点关注第三条的备案时限要求,原文材料显示……"
    assert strip_leading_chatter(text) == text


def test_stops_at_the_first_non_chatter_sentence():
    """遇到第一个不像自语的句子就停,后面即使又出现自语式句子也不再删。"""
    text = "我先看看材料。结论如下。我已读取了原文。"
    out = strip_leading_chatter(text)
    assert out.startswith("结论如下。")
    assert "我已读取了原文。" in out, "第二句之后的内容一律不动"


def test_long_sentence_is_never_treated_as_chatter():
    """长句更可能是正经论述,误删代价大于漏删,所以超过阈值就不删。"""
    long_line = (
        "我在阅读原文后确认,该文件对充电业务的核心影响在于把备案时限从三十个"
        "工作日压缩到十五个工作日,并要求各地在年底前完成配套细则的制定工作。"
    )
    assert strip_leading_chatter(long_line) == long_line


def test_all_chatter_keeps_the_text_rather_than_emptying_it():
    """整段都像自语时保持原样——宁可多显示,也不能把答复整个吞掉。"""
    text = "我已读取了原文。现在整理答复。"
    assert strip_leading_chatter(text) == text


def test_empty_and_whitespace_are_safe():
    assert strip_leading_chatter("") == ""
    assert strip_leading_chatter("   ") == "   "


def test_high_precision_not_high_recall():
    """判据是**白名单模式**,不是"自称词+流程词"的组合。

    组合判据会误伤下面这类正经论述——它有自称、有流程词,却是答复本身。
    这条守的就是那个边界:宁可漏删,不可误删。
    """
    body = "我建议重点关注第三条的备案时限,原文材料显示已从三十日压到十五日。"
    assert strip_leading_chatter(body) == body

    # "下面给出X"只有 X 是答复/回答时才算自语;给出实质内容的不算
    content = "下面给出各省的落地情况。江苏要求年底前完成。"
    assert strip_leading_chatter(content) == content
