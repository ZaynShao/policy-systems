"""元数据抽取:全 regex + canonical lookup,无 LLM(LESSONS B1)。"""
from __future__ import annotations
import re
from dataclasses import dataclass
from urllib.parse import urlparse
from typing import Optional

from scripts.l1_collect.cn_dates import pick_issuance_date

# 文号 regex(支持〔〕 / [] / () 三种括号)
_OFFNUM_RE = re.compile(r"[一-龥]{2,8}[〔\[(]\s*(?:19|20)\d{2}\s*[〕\])]\s*\d+\s*号")
_OFFNUM_RE_LOOSE = re.compile(r"[一-龥]{0,8}[〔\[(]\s*(?:19|20)\d{2}\s*[〕\])]\s*\d+\s*号")
# 被废止/失效旧件号上下文:这些词附近的文号不是本件文号
_REPEAL_NEAR = re.compile(r"废止|失效|停止执行|不再执行")
# 引用动词不是文号的组成部分,但会被 _OFFNUM_RE 的 [一-龥]{2,8} 前缀吞进来
# (生产实测抽出过 "根据财库〔2022〕3号")。按长优先剥掉。
_CITE_VERB_PREFIX = re.compile(r"^(?:根据|依据|按照|参见|详见|遵照|据|见|按)+")
_BRACKET_YEAR = re.compile(r"[〔\[(]\s*((?:19|20)\d{2})\s*[〕\])]")
# 文号年份与发文年份相差多少年即判定「非本件文号」。跨年发文(差 1)属正常。
_STALE_YEAR_GAP = 2

_DATE_URL_RE = re.compile(r"/((?:19|20)\d{2})[-_/](\d{1,2})[-_/](\d{1,2})/")
# 政府站极常见紧凑格式 /YYYYMM/tYYYYMMDD_id（年月目录 + 文件名带 8 位无分隔日期），
# 原 delimited 正则抓不到 → date 空 → pid 落 P_1900 占位。带范围校验防 20251340 这类越界。
_DATE_URL_COMPACT = re.compile(r"[t/_]((?:19|20)\d{2})(\d{2})(\d{2})(?:\D|$)")

# 中央部委 issuer canonical 表(市级补由 channel_catalog 反查时补)
ISSUER_DOMAIN_TABLE = {
    "www.gov.cn": "国务院",
    "www.ndrc.gov.cn": "国家发展和改革委员会",
    "www.nea.gov.cn": "国家能源局",
    "www.miit.gov.cn": "工业和信息化部",
    "www.mofcom.gov.cn": "商务部",
    "www.mohurd.gov.cn": "住房和城乡建设部",
    "www.mee.gov.cn": "生态环境部",
    "www.mof.gov.cn": "财政部",
}


@dataclass
class ExtractedMeta:
    title: str = ""
    official_number: str = ""
    date: str = ""
    issuer: Optional[str] = None
    url: str = ""


def _is_repealed_context(text: str, start: int, end: int) -> bool:
    """文号前后窗口出现废止/失效语义 → 是被废止旧件号,非本件文号。"""
    return bool(_REPEAL_NEAR.search(text[max(0, start - 12):end + 16]))


def _is_stale_year(num: str, date: str) -> bool:
    """文号括号年与发文年相差 >= _STALE_YEAR_GAP → 是正文引用的旧件号,非本件文号。
    date 为空时该规则不生效(调用方没给日期就不猜)。"""
    if not date or not date[:4].isdigit():
        return False
    m = _BRACKET_YEAR.search(num)
    if not m:
        return False
    return abs(int(date[:4]) - int(m.group(1))) >= _STALE_YEAR_GAP


def extract_official_number(text: str, date: str = "") -> str:
    """取本件文号,无 -> ''。

    正文里第一个文号形状的串未必属于本件——政府页常在正文/附注里引用上位文件,
    也常把相关链接拼进正文。逐条排除后取第一个存活的:
      1. 废止/失效上下文里的旧件号
      2. 被贪婪前缀吞进来的引用动词(根据/依据/按照…)
      3. 括号年与发文年相差 >= 2 年的(需调用方给 date)
    """
    if not text:
        return ""
    for rx in (_OFFNUM_RE, _OFFNUM_RE_LOOSE):
        for m in rx.finditer(text):
            if _is_repealed_context(text, m.start(), m.end()):
                continue
            num = _CITE_VERB_PREFIX.sub("", m.group(0).replace(" ", ""))
            if _is_stale_year(num, date):
                continue
            return num
    return ""


def extract_date(url: str, body: str = "") -> str:
    """优先 URL path(发布日);其次正文落款/发文日。绝不取生效/截止日。返回 YYYY-MM-DD 或 ''。"""
    if url:
        m = _DATE_URL_RE.search(url)
        if m:
            y, mo, d = m.groups()
            return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
        m = _DATE_URL_COMPACT.search(url)
        if m:
            y, mo, d = m.groups()
            if 1 <= int(mo) <= 12 and 1 <= int(d) <= 31:
                return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    if body:
        d = pick_issuance_date(body)
        if d:
            return d
    return ""


def extract_issuer_from_url(url: str) -> Optional[str]:
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return None
    return ISSUER_DOMAIN_TABLE.get(host)


def extract_meta(url: str, title: str, body: str) -> ExtractedMeta:
    date = extract_date(url, body)
    return ExtractedMeta(
        title=title.strip(),
        official_number=extract_official_number(body, date=date),
        date=date,
        issuer=extract_issuer_from_url(url),
        url=url,
    )
