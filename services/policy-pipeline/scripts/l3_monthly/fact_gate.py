"""F 门:稿内每个事实都要能在素材包里回指得到。

分工照 spec §6.4:**代码抽 claim + 代码匹配**,只有匹配不上的才交 LLM 判是否等价表述。
一期几十个数字,绝大多数能代码判掉,没理由为此每期烧一遍 token。

抽取口径的关键是**别过度抽**。中文数字("三大业务""一、概述""十余省")不是事实断言,
抽进来会让每期几十条假阳性,人看两次就不看了,这道门也就废了。故只认:
文号、带日的日期、第 N 条、**带单位的阿拉伯数字**、引号里的短引文。

匹配前两边都做归一(全角数字、千分位、空白),日期再按年月日比对——
稿里写 2026年7月23日、素材里写 2026-07-23 是同一天,报出来就是噪音。
"""
import re

from scripts.l3_monthly import budget, judge

GATE = "F"
RULE = "F-UNBACKED"
SEVERITY = "BLOCKER"

_FULLWIDTH = str.maketrans("０１２３４５６７８９", "0123456789")

# 抽取按此顺序,先匹配到的把原文位置抹掉,免得同一段被两种 kind 重复抽
_PATTERNS = (
    ("doc_no", re.compile(r"[一-龥]{2,10}[〔\[]\d{4}[〕\]]\d{1,4}号")),
    ("date", re.compile(r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日|\d{4}-\d{1,2}-\d{1,2}")),
    ("article", re.compile(r"第[〇一二三四五六七八九十百零两\d]{1,6}条")),
    ("quote", re.compile(r"[“\"]([^”\"]{2,40})[”\"]")),
    ("number", re.compile(
        r"\d[\d,，.]*\s*(?:%|％|万千瓦时|亿千瓦时|万千瓦|兆瓦|千瓦|亿元|万元|"
        r"亿|万|元|个|座|台|户|家|条|项|份|倍|次)")),
)
_DATE_PARTS = re.compile(r"(\d{4})\s*[年-]\s*(\d{1,2})\s*[月-]\s*(\d{1,2})")


_DOC_CORE = re.compile(r"[〔\[]\d{4}[〕\]]\d{1,4}号")


def _lined(text):
    """归一但**保留换行**:文号前缀要靠换行断开,抹掉换行会把上一行的机关名粘上来。"""
    return re.sub(r"[^\S\n]|[,，]", "", (text or "").translate(_FULLWIDTH))


def _norm(text):
    return _lined(text).replace("\n", "")


def _doc_no_backed(claim, lined_sources):
    """文号前缀无分隔符,正则只能贪婪地把前面的词一起吃进来(「依据发改能源〔…〕」)。

    与其把正则放松(那会让「错改能源〔2026〕1067号」也蒙混过关),不如按结构比:
    文号核心必须原样出现,且**素材里紧挨核心的那串汉字必须是稿内前缀的后缀**。
    """
    m = _DOC_CORE.search(_norm(claim))
    if not m:
        return False
    core, prefix = m.group(0), _norm(claim)[:m.start()]
    for src in lined_sources:
        start = 0
        while (i := src.find(core, start)) >= 0:
            j = i
            while j > 0 and "\u4e00" <= src[j - 1] <= "\u9fa5":
                j -= 1
            if src[j:i] and prefix.endswith(src[j:i]):
                return True
            start = i + 1
    return False


def _dates_in(text):
    return {(int(y), int(m), int(d)) for y, m, d in _DATE_PARTS.findall(_norm(text))}


def extract_claims(text):
    """抽出稿内需要回指的事实断言。返回 [{kind, text}]。"""
    rest = text or ""
    claims = []
    for kind, pattern in _PATTERNS:
        for m in pattern.finditer(rest):
            claims.append({"kind": kind, "text": (m.group(1) if kind == "quote"
                                                  else m.group(0)).strip()})
        rest = pattern.sub(lambda m: " " * len(m.group(0)), rest)
    return claims


def _backed(claim, sources, lined_sources, source_dates):
    if claim["kind"] == "date":
        return bool(_dates_in(claim["text"]) & source_dates)
    if claim["kind"] == "doc_no":
        return _doc_no_backed(claim["text"], lined_sources)
    needle = _norm(claim["text"])
    return any(needle in src for src in sources)


def check_facts(text, sources, location=""):
    """返回回指不到的 claim 列表。空 sources 不等于全部通过——那是最危险的假绿。"""
    normed = [_norm(s) for s in sources or []]
    lined = [_lined(s) for s in sources or []]
    source_dates = set()
    for s in sources or []:
        source_dates |= _dates_in(s)
    out = []
    for claim in extract_claims(text):
        if _backed(claim, normed, lined, source_dates):
            continue
        out.append({"gate": GATE, "rule": RULE, "severity": SEVERITY,
                    "kind": claim["kind"], "location": location,
                    "quote": claim["text"],
                    "note": f"这处{_KIND_CN.get(claim['kind'], '事实')}"
                            f"在素材包里回指不到,不得写入"})
    return out


_KIND_CN = {"doc_no": "文号", "date": "日期", "article": "条款号",
            "number": "数字", "quote": "引文"}

FACT_SYSTEM = """你是《能源政策月刊》的事实核查员。

下面每一条是稿子里写到、但代码在素材里逐字匹配不到的表述。你只判一件事:
**它是不是素材里同一事实的等价表述**(例如同一日期的另一种写法、同一数字的换算或概数)。

只要素材里找不到对应事实,或者你不确定,就判 equivalent=false。**存疑即为不等价。**

输出一个 JSON 对象,不要任何解释文字:
{"verdicts":[{"index":0,"equivalent":true,"why":"简短理由"}]}"""


def build_fact_user(violations, sources):
    items = "\n".join(f"{i}. [{_KIND_CN.get(v['kind'], '事实')}] {v['quote']}"
                      for i, v in enumerate(violations))
    src = "\n\n".join(sources or []) or "(无素材)"
    return f"【待判表述】\n{items}\n\n【素材】\n{src}\n\n输出 JSON。"


def adjudicate(client, violations, sources, max_tokens=budget.SHORT_JSON):
    """把代码判不掉的交给模型判是否等价表述。

    模型答不出来就维持原判——F 门宁可多报,不可放过:多报一条只是多一句容错提示,
    放过一条就是把编造的数字发给决策层。
    """
    if not client or not violations:
        return violations
    try:
        obj = judge.extract_json(
            client.complete(FACT_SYSTEM, build_fact_user(violations, sources),
                            max_tokens=max_tokens))
        verdicts = obj["verdicts"]
    except (judge.JudgmentError, KeyError, TypeError):
        return violations
    equivalent = {v.get("index") for v in verdicts
                  if isinstance(v, dict) and v.get("equivalent") is True}
    return [v for i, v in enumerate(violations) if i not in equivalent]


_COUNT_UNITS = ("项", "篇", "条", "个", "份")


def editorial_source(content):
    """本期**自身**的结构事实。

    概述里的「国家级 5 项 + 省级 8 项」是编辑口径的计数,它回指的不是某份 RAW
    而是本期选目。不给这个源,每期都会误报几条(实测已交付的 2026-04 里有
    「5 项」「8 项」「1 项」「3 项」这类计数);给了,写错的计数反而会被抓出来。

    各计数按几种常见量词都铺一遍,免得因为稿子写「篇」而源里写「项」误报。
    """
    rows = content.get("quickTable") or []
    counts = {
        "国家级": sum(1 for r in rows if str(r.get("level", "")).startswith("国家")),
        "地方": sum(1 for r in rows if not str(r.get("level", "")).startswith("国家")),
        "速览": len(rows),
        "详情": len(content.get("details") or []),
        "合计": len(rows),
    }
    parts = [f"{name}{n}" + "".join(f"{n}{u}" for u in _COUNT_UNITS)
             for name, n in counts.items()]
    return "本期结构计数:" + ";".join(parts) + "。"
