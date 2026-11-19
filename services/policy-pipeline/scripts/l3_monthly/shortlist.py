"""MA1:粗筛(去噪)+ 去重。

去重是实测出来的需求:vault 里同一份文件被采成多份(942 号 3 个文件名变体、
884 号 2 个、42 号令 2 个)。不处理会让选目重复计数、配额失真。

纪律分两档,**不把两份不同的文件当重复丢掉**:
- 硬合并:文号相同(且非空)**且标题核心相容** → 留 RAW 正文最长的那份。
- 软标记:文种相同 + 核心标题相等或互相包含 → 只打 `near_dup_group` 交 MA3 裁,一份都不丢。

**文号相同绝不足以判重复。** 2026-09-07 实测:真实 vault 1653 篇里,同一文号挂着
不相干标题的组有 31 个——`发改能源〔2026〕884号` 同时挂在成品油调价公告与十五五规划
通知上,`国办发〔2025〕5号` 横跨 6 份毫不相干的文件。frontmatter 的文号会抓到侧栏噪声,
盲目按文号合并会**静默删掉真政策**。这类冲突改为打 `docno_conflict` 标记交下游按 RAW 落款判。
"""
import dataclasses
import re
import unicodedata

from scripts.l3_render import pack_lib as pl

_BRACKETS = "《》〈〉「」『』【】“”‘’\"'()（）[]〔〕 \t　"
# 只剥**真文号**的尾括号:真文号带〔〕(发改能源〔2026〕884号),而「（2026年第10号）」
# 是序号——江苏的成品油调价公告靠它区分,剥掉会把六份不同日期的公告并成一份(实测)。
_TRAILING_DOCNO = re.compile(r"[（(][^（()）]*〔[^（()）]*[)）]\s*$")
_BOOK_TITLE = re.compile(r"《([^《》]+)》")
_DOC_KINDS = ("通知", "公告", "命令", "决定", "批复", "意见", "办法", "方案", "规划")
MIN_CORE_LEN = 8   # 核心标题短于此不参与包含判定,否则「关于甲的通知」会把全库并成一组
MIN_SERIES = 3     # 两篇不算系列,免得把成对出现的正常文件误标
_SERIES_DROP = re.compile(r"[年月日时起第号(){}\[\]（）《》「」【】“”\s]|\d+")


def normalize_title(t):
    """标题归一:去尾部文号括号、去各类括号引号、全角转半角、去空白。"""
    s = unicodedata.normalize("NFKC", t or "")
    s = _TRAILING_DOCNO.sub("", s).strip()
    return "".join(ch for ch in s if ch not in _BRACKETS)


def core_title(t):
    """取书名号里的核心文件名;没有书名号则退回整个标题的归一形式。"""
    m = _BOOK_TITLE.search(unicodedata.normalize("NFKC", t or ""))
    return normalize_title(m.group(1)) if m else normalize_title(t)


def doc_kind(t):
    """粗判文种。用于把「《X规划》发布」(新闻)与「关于印发《X规划》的通知」(公文)分开。"""
    s = t or ""
    for k in _DOC_KINDS:
        if k in s:
            return k
    return ""


def series_key(t):
    """周期性系列的归一键:抹掉数字与日期/序号字样,保留发布者与事由。

    实测(2026-07 窗口 261 篇):41 篇即 15% 是成品油调价系列,各省各期一份、
    标题只差日期。near-dup 抓不住(核心标题确实不同),但它们在编辑视角上是一件事。
    **只打标记不删**——是否值得写、写几条,是 MA3 的编辑判断,不是代码该替它做的决定。
    """
    return _SERIES_DROP.sub("", unicodedata.normalize("NFKC", t or ""))


def _norm_docno(s):
    return "".join(unicodedata.normalize("NFKC", s or "").split())


def titles_compatible(a, b):
    """两个标题是否指向同一份文件。相等或(足够长的)包含关系才算。"""
    ca, cb = core_title(a), core_title(b)
    if not ca or not cb:
        return False
    if ca == cb:
        return True
    lo, hi = (ca, cb) if len(ca) <= len(cb) else (cb, ca)
    return len(lo) >= MIN_CORE_LEN and lo in hi


def _cluster(cands):
    """按标题相容性把一组候选切成若干簇(贪心,够用)。"""
    clusters = []
    for c in cands:
        for cl in clusters:
            if any(titles_compatible(c.title, m.title) for m in cl):
                cl.append(c)
                break
        else:
            clusters.append([c])
    return clusters


def dedupe(items):
    """返回 (kept, dropped)。dropped 的每条带 dup_of 与 drop_reason='dup'。"""
    by_docno, order = {}, []
    for c in items:
        key = _norm_docno(c.official_number)
        if not key:                       # 空文号不参与硬合并:空 != 空
            order.append([c])
            continue
        if key not in by_docno:
            by_docno[key] = []
            order.append(by_docno[key])
        by_docno[key].append(c)

    kept, dropped = [], []
    for group in order:
        clusters = _cluster(group)
        conflicted = len(clusters) > 1     # 同文号却切成多簇 = 有一方文号是错抓的
        for cl in clusters:
            winner = max(cl, key=lambda c: c.body_len)   # RAW 正文最长的那份最完整
            kept.append(dataclasses.replace(winner, docno_conflict=conflicted))
            for c in cl:
                if c is not winner:
                    dropped.append(dataclasses.replace(
                        c, dup_of=winner.policy_id, drop_reason="dup",
                        docno_conflict=conflicted))

    # 同 policy_id 再合一轮:文号为空时走不到上面那条路,而同 id + 标题相容
    # 就是同一份文件采了两次(实测 P_2026_HL_FGW_a770e0cb 两行标题完全相同)。
    by_pid, pid_order = {}, []
    for c in kept:
        if c.policy_id not in by_pid:
            by_pid[c.policy_id] = []
            pid_order.append(by_pid[c.policy_id])
        by_pid[c.policy_id].append(c)
    kept = []
    for group in pid_order:
        for cl in _cluster(group):
            winner = max(cl, key=lambda c: c.body_len)
            kept.append(winner)
            for c in cl:
                if c is not winner:
                    dropped.append(dataclasses.replace(
                        c, dup_of=winner.policy_id, drop_reason="dup"))

    # 软标记:文种相同的簇内再按核心标题相容性分组
    for kind in {doc_kind(c.title) for c in kept}:
        same_kind = [c for c in kept if doc_kind(c.title) == kind]
        for cl in _cluster(same_kind):
            if len(cl) < 2:
                continue
            core = min((core_title(c.title) for c in cl), key=len)
            if not core:
                continue
            tag = f"{kind or '未知'}::{core}"
            for c in cl:
                c.near_dup_group = tag

    # id 撞车:同一 policy_id 挂了不相容的标题
    by_id = {}
    for c in kept + dropped:
        by_id.setdefault(c.policy_id, []).append(c)
    for pid, group in by_id.items():
        if len(group) > 1 and len(_cluster(group)) > 1:
            for c in group:
                c.id_collision = True

    return kept, dropped


def build_shortlist(items):
    """粗筛 → 去重。返回 (kept, dropped);dropped 的 drop_reason ∈ {noise, dup}。"""
    survivors, dropped = [], []
    for c in items:
        if pl.is_noise(c.title):
            dropped.append(dataclasses.replace(c, drop_reason="noise"))
        else:
            survivors.append(c)
    kept, dup_dropped = dedupe(survivors)

    buckets = {}
    for c in kept:
        buckets.setdefault(series_key(c.title), []).append(c)
    for key, group in buckets.items():
        if key and len(group) >= MIN_SERIES:
            for c in group:
                c.series_group = key[:40]
                c.series_size = len(group)
    return kept, dropped + dup_dropped
