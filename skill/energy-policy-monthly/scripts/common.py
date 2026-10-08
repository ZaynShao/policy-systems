"""共用解析工具:乱码还原、frontmatter 拆分、正文去噪。

乱码还原是最容易写错的一环,见 demojibake 里的 NEL 说明。
去噪里最容易误伤的一环是"纯数字短行",见 rejoin_split_numbers。
"""
from __future__ import annotations

import re

NAV = {
    "首页", "无障碍", "关怀版", "个人中心", "搜索", "政务公开", "政务服务",
    "互动交流", "上一篇", "下一篇", "通知公告", "打印", "关闭", "分享",
    "字号", "大", "中", "小", "返回", "更多", "网站首页", "微博微信",
    "移动端", "分享到微信朋友圈x", "扫一扫在手机打开当前页", "索引号",
}


def demojibake(text: str) -> str:
    """还原 UTF-8 被按 latin-1 解码的乱码(如 2026å¹´ → 2026年),非乱码原样返回。

    整体转换失败时逐行修复,此处必须用 text.split("\\n") 而不是 splitlines():
    乱码字节里含 \\x85(NEL)、\\x0b 等,splitlines 会把它们当换行,
    从而切断多字节序列、导致整段修不回来。
    """
    if "å" not in text and "ï¼" not in text and "æ" not in text:
        return text
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        out = []
        for line in text.split("\n"):
            try:
                out.append(line.encode("latin-1").decode("utf-8"))
            except (UnicodeEncodeError, UnicodeDecodeError):
                out.append(line)
        return "\n".join(out)


_NL = r"[ \t]*\n[ \t]*"
_NLO = r"(?:[ \t]*\n[ \t]*)?"   # 可选换行:拆行与未拆行都能匹配,未拆行时替换为自身
_NLB = r"(?:[ \t]*\n(?:[ \t]*\n)?[ \t]*)?"   # 可选换行,允许夹一个空行;只用于〔年〕号与年第N号这两种紧结构
_REJOIN_RULES = [
    # 被拆开的年份:连续 2-3 行纯数字,拼起来恰好是 19xx/20xx 四位 → 并行(202\n6 → 2026,20\n2\n6 → 2026)
    (re.compile(r"^[ \t]*((?:19|20)\d{0,2})" + _NL + r"(\d{1,2})(?:" + _NL + r"(\d{1,2}))?[ \t]*$", re.M),
     lambda m: "".join(g for g in m.groups() if g) if len("".join(g for g in m.groups() if g)) == 4 else m.group(0)),
    # 文号:〔\n2021\n〕\n1595\n号 → 〔2021〕1595号
    (re.compile(r"〔" + _NLB + r"(\d{4})" + _NLB + r"〕" + _NLB + r"(\d{1,5})" + _NLB + r"号"), r"〔\1〕\2号"),
    # 整行年份 + 下一行以"年"开头(2026\n年第10号 / 2026\n年保底) → 并行
    (re.compile(r"^[ \t]*((?:19|20)\d{2})[ \t]*\n(?:[ \t]*\n)?[ \t]*(?=年)", re.M), r"\1"),
    # 公告号:2026年第\n10\n号 → 2026年第10号
    (re.compile(r"年第" + _NLB + r"(\d{1,4})" + _NLB + r"号"), r"年第\1号"),
    # 日期:2026\n年\n8\n月\n26\n日 → 2026年8月26日(年月日之间任意位置可有换行)
    (re.compile(r"(?<!\d)(\d{4})" + _NLO + r"年" + _NLO + r"(\d{1,2})" + _NLO + r"月(?:" + _NLO + r"(\d{1,2})" + _NLO + r"日)?"),
     lambda m: f"{m.group(1)}年{m.group(2)}月" + (f"{m.group(3)}日" if m.group(3) else "")),
]


def rejoin_split_numbers(text: str) -> str:
    """把被拆成多行的文号与日期拼回一行。

    乱码件(如川能源〔2026〕47号的页面)里,"发改体改规〔2021〕1595号"会被抓成
    "发改体改规〔\\n2021\\n〕\\n1595\\n号","2026年8月26日"会被抓成 "202\\n6\\n年\\n8\\n月\\n26\\n日"。
    clean_body 原来会把这些纯数字短行当页面噪声整行删掉,bundle 里就只剩"〔 〕号"。
    这里只按四种强结构整段匹配(拆开的年份、〔年〕号文号、年第N号公告号、年月日),
    不做泛化的"数字行并行",避免把表格里的数字列并成一串。
    2026-08 月刊 F 门实测触发;修复后回归过 942/1055/695/332/47 五件与全库并行次数分布。
    """
    prev = None
    while prev != text:
        prev = text
        for pat, rep in _REJOIN_RULES:
            text = pat.sub(rep, text)
    return text


def split_front(text: str) -> tuple[str, str]:
    """拆 frontmatter 与正文。"""
    if not text.startswith("---"):
        return "", text
    end = text.find("\n---", 3)
    if end < 0:
        return "", text
    return text[3:end], text[end + 4:]


def fm_get(front: str, key: str) -> str:
    m = re.search(rf"^{key}:\s*(.*)$", front, re.M)
    return m.group(1).strip().strip("'\"") if m else ""


def fm_fetched(front: str) -> str:
    """provenance.fetched_at 的日期部分(入库日),用于跨月捞回。"""
    m = re.search(r"fetched_at:\s*'?(\d{4}-\d{2}-\d{2})", front)
    return m.group(1) if m else ""


def fm_region(front: str) -> tuple[str, str]:
    m = re.search(r"^region:\s*\n((?:\s+\S.*\n?)+)", front, re.M)
    if not m:
        return "", ""
    blk = m.group(1)
    lvl = re.search(r"level:\s*(\S+)", blk)
    nm = re.search(r"name:\s*(\S+)", blk)
    return (lvl.group(1) if lvl else ""), (nm.group(1) if nm else "")


def clean_body(body: str, *, drop_short: int = 0) -> str:
    """去掉爬虫导航噪声与图片/面包屑,保留正文。

    先 demojibake,再 rejoin_split_numbers,最后逐行去噪;顺序不能换,
    否则拆行的文号数字会在去噪那步被当成噪声丢掉。
    """
    out, blank = [], 0
    for ln in rejoin_split_numbers(demojibake(body)).splitlines():
        s = ln.strip()
        if s in NAV or s.startswith("!["):
            continue
        if s.startswith("[") and "](" in s and len(s) > 70:
            continue
        if re.fullmatch(r"[\d\s\-:./_]*", s) and 0 < len(s) < 12:
            continue
        if drop_short and 0 < len(s) <= drop_short:
            continue
        if not s:
            blank += 1
            if blank > 1:
                continue
        else:
            blank = 0
        out.append(ln.rstrip())
    return "\n".join(out).strip()
