"""事实核验:答案里的文号和引文,必须在本轮工具返回过的材料里逐字出现过。

**这一层不调模型。** 一开始想用 evaluator-optimizer(再叫一次模型去审初稿),
后来发现搞错了性质:"文号必须逐字照抄""引用原文必须逐字"本来就是**字面规则**,
那么正确的检查就是字面比对。让另一个模型去judge,既贵又引入新的幻觉面,
还不如一个正则加一次子串查找可靠。

针对的是实测过的失败:真模型冒烟时写出 `浙发改价格〔2026〕21号`,
而库里是〔2024〕21号(被它废止的旧件的号)。当时靠人眼发现,补了 prompt 规则;
prompt 规则挡不住第二次,这一层能。

核验不改答案,只报告。答案是流式吐给用户的,回头改写既做不到也不该做——
把存疑的地方标出来,让用户自己去点引用核对,比服务端偷偷改字更符合这套纪律。
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

#: 中文公文文号:机关简称 + 〔年份〕+ 序号 + 号。
#: 前缀放宽到 0-12 字,因为库里既有"发改能源〔2026〕1号"也有单独出现的"〔2026〕1号"。
DOC_NUMBER_RE = re.compile(r"[一-龥A-Za-z]{0,12}〔\d{4}〕\d{1,6}号")

#: 直接引语。只认这两种成对引号——《》是书名号,标题不适用"逐字"这条规矩
#: (标题在检索结果里本来就有,模型转述标题不算引用原文)。
QUOTE_RE = re.compile(r"[「“]([^「」“”]{8,300})[」”]")

#: 省略号:引文允许省略,所以要按它切段后逐段核。
ELLIPSIS_RE = re.compile(r"…{1,}|\.{3,}")

#: 证据缓冲上限。本轮所有工具返回拼起来,超了就不再追加——
#: 核验宁可漏报也不能因为吃内存把回答拖垮。
EVIDENCE_MAX_CHARS = 400_000

#: 引文片段短于这个长度就不核了。太短的片段几乎必然能在长文里偶然命中,
#: 核了也是假阳性。
MIN_QUOTE_FRAGMENT = 8

ClaimKind = Literal["doc_number", "quote"]


class UnsupportedClaim(BaseModel):
    kind: ClaimKind
    text: str
    hint: str


class VerificationReport(BaseModel):
    checked_doc_numbers: int = 0
    checked_quotes: int = 0
    unsupported: list[UnsupportedClaim] = []

    @property
    def ok(self) -> bool:
        return not self.unsupported


def normalize(text: str) -> str:
    """把括号变体统一成〔〕,去掉所有空白。

    同一个文号在正文里可能写成 (2026)、（2026）、[2026]、〔2026〕。
    不归一化就会把纯粹的写法差异报成编造,假阳性一多这层就没人看了。
    """
    table = str.maketrans({"(": "〔", ")": "〕", "（": "〔", "）": "〕",
                           "[": "〔", "]": "〕", "［": "〔", "］": "〕"})
    return re.sub(r"\s+", "", text.translate(table))


def _doc_number_supported(number: str, evidence: str) -> bool:
    """文号是否在证据里出现过。

    先整串比对;不中再退一步只比"〔年份〕序号号"那段——模型可能把机关简称
    写全了(库里是"浙发改价格〔2024〕21号",它写成"浙江省发改委〔2024〕21号"),
    那是转写不是编造,不该报。**年份和序号一位都不能差**,那才是编造。
    """
    if number in evidence:
        return True
    core = re.search(r"〔\d{4}〕\d{1,6}号", number)
    return bool(core and core.group(0) in evidence)


#: 会被贪婪前缀吃进来的动词。它们不是机关简称,报出来只会让人困惑。
_PREFIX_NOISE = ("废止", "根据", "依据", "参见", "同时", "按照", "见", "据")


def _report_text(number: str) -> str:
    """把动词前缀剥掉再报给人看。判定用的是原串,这里只管显示。

    不能用 startswith:贪婪前缀可能是"本件废止财税〔2018〕74号"这种,动词前面
    还有别的字。取**最后一个**噪声词的结束位置往后截,才切得干净。
    """
    cut = 0
    head = number.split("〔", 1)[0]
    for noise in _PREFIX_NOISE:
        idx = head.rfind(noise)
        if idx >= 0:
            cut = max(cut, idx + len(noise))
    return number[cut:] if cut and number[cut:] else number


def verify_answer(answer: str, evidence: str, question: str = "") -> VerificationReport:
    """核对答案里的文号与引文。

    evidence 是本轮所有工具返回拼成的串;question 是用户的原问题,
    **也算证据**——用户自己给出的文号,模型复述一遍不是编造。

    不带 question 会产生刺眼的假阳性:2026-08-18 答案评测里,用户问
    「发改办能源〔2026〕000号讲了什么」,模型正确回答"库内未收录",
    核验却把这个号报成存疑。一个总在报警的核验器等于没有核验器。
    """
    if not answer.strip() or not (evidence.strip() or question.strip()):
        return VerificationReport()

    norm_evidence = normalize(evidence + "\n" + question)
    unsupported: list[UnsupportedClaim] = []

    numbers = list(dict.fromkeys(DOC_NUMBER_RE.findall(normalize(answer))))
    for num in numbers:
        if not _doc_number_supported(num, norm_evidence):
            unsupported.append(
                UnsupportedClaim(
                    kind="doc_number",
                    # 前缀是贪婪匹配的,可能把"废止""根据"这类动词也吃进来
                    # (实测报出过"废止财税〔2018〕74号")。判定不受影响,但报给人看
                    # 要干净:报真正没对上的那一串。
                    text=_report_text(num),
                    hint="本轮检索到的材料里没有这个文号,可能是记混或编造,请点引用核对",
                )
            )

    quotes = QUOTE_RE.findall(answer)
    checked_quotes = 0
    for quote in quotes:
        fragments = [
            f for f in (s.strip() for s in ELLIPSIS_RE.split(quote))
            if len(f) >= MIN_QUOTE_FRAGMENT
        ]
        if not fragments:
            continue
        checked_quotes += 1
        for frag in fragments:
            if normalize(frag) not in norm_evidence:
                unsupported.append(
                    UnsupportedClaim(
                        kind="quote",
                        text=frag[:60],
                        hint="这段引文在本轮读到的原文里找不到逐字对应,可能是转述而非引用",
                    )
                )
                break  # 一条引文报一次就够,不要把每个片段都刷出来

    return VerificationReport(
        checked_doc_numbers=len(numbers),
        checked_quotes=checked_quotes,
        unsupported=unsupported,
    )
