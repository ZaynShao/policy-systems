"""MA6 的两道纯代码门:D 门(风格)与业务口径门。

**正则与词表能判死的事,没有理由让模型来判**——D 门每期要扫全文,交给 LLM 既贵又不稳。
留给 LLM 的只有 F 门里代码匹配不上的灰区(是否等价表述)。

规则出处是实际执行过的 D 门禁用清单;在两份已交付终稿(2026-05 / 2026-06)上实测
**19 条禁项零命中**,而两条正向模式(行动标签、评分「N分」)正常命中——校准过,不误伤。
"""
import re

from scripts.l3_monthly.judge import absent_terms

SEVERITY_ORDER = ("BLOCKER", "MAJOR", "MINOR")

# rule, severity, 正则, 说明
_STYLE_RULES = [
    ("D-TOKEN", "BLOCKER", r"P_20\d\d[_A-Za-z0-9]*", "政策内部 id 泄漏到正文"),
    ("D-TOKEN", "BLOCKER", r"\w+_theme\b", "主题枚举码泄漏"),
    ("D-TOKEN", "BLOCKER", r"\bD[1-6]\b", "打分维度码泄漏"),
    ("D-TOKEN", "BLOCKER", r"MiniMax|M2\.7|deepseek|DeepSeek|GPT-|Claude",
     "模型名泄漏"),
    ("D-TOKEN", "BLOCKER", r"sanitized_from|extracted_\w+|gate_passed\w*|rel-\w+",
     "管道字段泄漏"),
    ("D-STAR", "BLOCKER", r"⭐", "评分须写「N分」,不用星标"),
    ("D-RELTABLE", "BLOCKER", r"\|\s*之前文件\s*\|", "机器承接关系表"),
    ("D-RELTABLE", "BLOCKER", r"上位法承接|工作接续|同期双联|业态承接",
     "内部关系分类词;承接要写成自然句"),
    ("D-POLLUTE", "BLOCKER", r"乡村能源|农村能源|新能源汽车下乡|汽车下乡",
     "已退役原型的内容污染,不得作为月刊考量点"),
    ("D-QUOTE", "MAJOR", r"[「」『』]", "角括号须换成中文双引号"),
    ("D-EMPH", "MAJOR", r"\*\*|(?<!\*)\*(?!\*)", "交付是 docx,正文不留 markdown 强调符"),
    ("D-MD", "MAJOR", r"^#{1,6}\s|`|https?://", "正文不留 markdown 标题/反引号/链接"),
    ("D-META", "MAJOR",
     r"数据覆盖说明|本期覆盖|尚未覆盖|暂行跳过|下期补充|参考来源|覆盖窗口|方法论",
     "过程性元信息:给读者看的是结论不是流程自白"),
    ("D-APPX", "MAJOR", r"^A[1-9]\s*·", "附录须用中文括号序号"),
    ("D-BANNER", "MINOR", r"^>\s|^(window|version|report_date)\s*[::]",
     "标题下的 banner / frontmatter 式元信息"),
    ("D-TONE", "MINOR", r"综上所述|总而言之|值得注意的是|首先.{0,30}其次",
     "AI 套话"),
    ("D-TONE", "MINOR", r"不是.{1,24}而是", "「不是…而是…」修辞"),
]

_HEAD_SPACED = re.compile(r"能\s+源\s+政\s+策\s+月\s+刊")
_HEAD_PLAIN = re.compile(r"能源政策月刊")
_TAG = re.compile(r"\[([A-Za-z][^\]]{0,10})\]")
ALLOWED_TAGS = {"A 趁早行动", "B 研究/跟进", "C 跟踪", "D 关注",
                "A 趁早", "B 研究", "B 跟进", "C 跟踪", "D 关注"}


def _v(gate, rule, severity, line, quote, note):
    return {"gate": gate, "rule": rule, "severity": severity,
            "line": line, "quote": quote.strip()[:80], "note": note}


def check_style(text):
    """D 门。返回违规列表;空列表 = 通过。"""
    out = []
    lines = (text or "").split("\n")

    first = next((i for i, l in enumerate(lines) if l.strip()), None)
    if first is not None:
        head = lines[first]
        if _HEAD_PLAIN.search(head) and not _HEAD_SPACED.search(head):
            out.append(_v("D", "D-HEAD", "MAJOR", first + 1, head,
                          "文头须用官文字距式「能 源 政 策 月 刊」"))

    for i, line in enumerate(lines, 1):
        for rule, sev, pat, note in _STYLE_RULES:
            m = re.search(pat, line, re.M)
            if m:
                out.append(_v("D", rule, sev, i, m.group(0), note))
        for m in _TAG.finditer(line):
            if m.group(1) not in ALLOWED_TAGS:
                out.append(_v("D", "D-TAG", "MINOR", i, m.group(0),
                              f"行动标签须取自 {sorted(ALLOWED_TAGS)}"))
    return _sort(out)


_BIZ_LABEL = re.compile(
    r"^\s*([一-龥A-Za-z]{1,8})业务\s*([（(][^)）]*[)）])?\s*[—\-::]")
_BIZ_NEGATIVE = re.compile(
    r"^\s*([一-龥A-Za-z]{1,8})业务\s*[::]\s*.{0,12}?(不相关|无关|未直接涉及|不涉及)")


def _profile_terms(profile):
    lines = {b.get("zh") for b in (profile.get("businesses") or []) if b.get("zh")}
    retired = set()
    for e in profile.get("not_business_lines") or []:
        zh = str(e.get("zh") or "")
        retired.add(re.split(r"[（(]", zh)[0].strip())
    hold = set()
    for b in profile.get("businesses") or []:
        for name, meta in (b.get("portfolio_status") or {}).items():
            if isinstance(meta, dict) and meta.get("status") == "hold":
                hold.add(name)
    return lines, {r for r in retired if r}, hold


def check_business(text, profile):
    """业务口径门:对账战略画像。

    只认**行首的业务标签**,不见词就抓——2026-06 终稿里换电出现 11 次、虚拟电厂 12 次、
    储能 7 次,它们在正文里是**议题**不是业务线;见词就抓等于全篇误报。
    """
    out = []
    lines_ok, retired, hold = _profile_terms(profile)
    absent = absent_terms(profile)
    for i, line in enumerate((text or "").split("\n"), 1):
        neg = _BIZ_NEGATIVE.search(line)
        if neg:
            out.append(_v("B", "B-NEGATIVE", "MAJOR", i, neg.group(0),
                          "决策建议只列有实话可说的业务,不写「X 业务:不相关」"))
            continue
        m = _BIZ_LABEL.match(line)
        if not m:
            continue
        name, paren = m.group(1), m.group(2) or ""
        if name not in lines_ok:
            why = ("已退役,不是业务线" if name in retired else
                   "画像里 hold" if name in hold else "不在画像的业务线内")
            out.append(_v("B", "B-LINE", "BLOCKER", i, m.group(0),
                          f"「{name}业务」{why};画像业务线只有 {sorted(lines_ok)}"))
            continue
        bad = sorted({w for w in (retired | hold | absent) if w and w in paren})
        if bad:
            out.append(_v("B", "B-LABEL", "BLOCKER", i, m.group(0),
                          f"业务标签里带了 {bad}——按现行画像它们或已退役、或 hold、"
                          f"或属材料空白,不能挂进业务线名"))
    return _sort(out)


def _sort(violations):
    return sorted(violations, key=lambda v: (SEVERITY_ORDER.index(v["severity"]),
                                             v["line"]))


def run_gates(text, profile):
    """两道代码门合并,最重的排前面。F 门另在 MA6 的事实链路里跑。"""
    return _sort(check_style(text) + check_business(text, profile))
