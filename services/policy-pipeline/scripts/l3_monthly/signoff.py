"""落款三字段:发文机关 / 发文日 / 文号。

速览表这三列**一律取自 RAW 正文的落款与文头**,禁止回退 frontmatter——frontmatter 的
date 常是生效/发布日、region.name 常是采集省份、official_number 可能抓到被废止件的号。
抽不到就留空并报出来,**不许猜**。

日期与文号**复用仓内既有的单一真相源**:cn_dates.pick_luokuan_strict(已剔生效/截止日、
认中文数字落款)与 metadata_extractor.extract_official_number(带废止上下文守卫)。
不另写一套——手写副本走散的代价,这条链路已经吃过一次。
"""
from scripts.l1_collect import cn_dates
from scripts.l1_collect.metadata_extractor import extract_official_number

# 机关名后缀。**不能用光秃秃的「局/委/厅」**:实测把「一季度全省经济实现平稳开局」
# 认成了发文机关(「开局」以「局」结尾)。所以只认带机构语义的完整后缀。
ORG_SUFFIX = (
    "发展和改革委员会", "发展改革委员会", "发展改革委", "管理委员会", "委员会", "管委会",
    "人民政府", "办公厅", "办公室", "监管办", "监管局", "管理局", "能源局", "商务局",
    "商务厅", "财政厅", "财政局", "工业和信息化厅", "工业和信息化部", "经信委", "经信厅",
    "市场监管局", "税务局", "总局", "能源监管办", "人民银行", "研究院", "科学院",
    "国务院", "省政府", "市政府", "县政府", "自治区政府",
)
# 转载出处/编辑信息行,不是发文机关(实测:「来源:云南发布、云南省能源局」)。
NON_ORG_PREFIX = ("来源", "编辑", "责任编辑", "转自", "转载", "供稿", "作者", "审核", "校对")


def _luokuan_span(body):
    """落款日期 + 它在正文里的位置。选取沿用 cn_dates 的权威判断,这里只负责回头定位。"""
    date = cn_dates.pick_luokuan_strict(body or "")
    if not date:
        return "", -1
    pos = -1
    for c in cn_dates.find_date_candidates(body):
        if c.date == date:
            pos = c.start
    return date, pos


def issuer_before(body, pos):
    """取落款日期之前**连续**的机关名行(联合发文常并列多行);遇到非机关名行即停。"""
    if pos < 0:
        return ""
    orgs = []
    for line in reversed((body or "")[:pos].split("\n")):
        line = line.strip()
        if not line:
            if orgs:
                break
            continue
        if any(line.startswith(pre) for pre in NON_ORG_PREFIX) or "：" in line or ":" in line:
            break
        if line.endswith(ORG_SUFFIX) and 4 <= len(line) <= 30:
            orgs.append(line)
        else:
            break
    return " ".join(reversed(orgs))


def signoff_fields(body):
    """返回 {date, issuer, doc_no, missing}。missing 列出抽不到的字段名。"""
    date, pos = _luokuan_span(body)
    issuer = issuer_before(body, pos)
    doc_no = extract_official_number(body or "")
    out = {"date": date, "issuer": issuer, "doc_no": doc_no or ""}
    out["missing"] = [k for k in ("date", "issuer", "doc_no") if not out[k]]
    return out
