#!/usr/bin/env python3
"""独立版补的:从本机政策库(只读)录链路看板的演示数据,写到 dashboard/data/。

在 services/policy-pipeline 目录下跑(先装好 requirements-dev.txt 里的依赖):

    python dashboard/export_data.py --vault <政策库克隆目录> [--monthly-state <月刊产线的 state 目录>]

数字都用本服务自己的代码算:守恒巡检 scripts/service/conservation_audit.py(原项目 PR 1184)、
vault→平台库同步的取行函数 scripts/sync/run_sync.py、对外语料导出 scripts/public_export/run.py。
只读政策库,不连数据库、不联网、不调用大模型;`00 背景资料/`、`开发日记/`、`_meta/framework/`
(业务战略画像)这些内部资料一概不读。月刊产线的选目单(slate.json)只数件数,不取内容。
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import glob
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVICE = HERE.parent
sys.path.insert(0, str(SERVICE))

import yaml  # noqa: E402

from scripts.l1_audit.corpus import load_policies  # noqa: E402
from scripts.l1_collect.channel_catalog import load_catalog  # noqa: E402
from scripts.l1_collect.channel_discovery import _CODE_TO_PROV  # noqa: E402
from scripts.l1_collect.ingester import PROVINCE_SHORT_BY_CODE  # noqa: E402
from scripts.public_export.redact import split_frontmatter  # noqa: E402
from scripts.public_export.run import export as export_public  # noqa: E402
from scripts.service import conservation_audit as audit  # noqa: E402
from scripts.sync.run_sync import collect_commentary_rows, collect_policy_rows, collect_relation_rows  # noqa: E402

CATALOG = SERVICE / "state" / "T1_channels" / "channel_catalog.yaml"
EXEMPTIONS = SERVICE / "config" / "audit_exemptions.yaml"

#: 正文是一串人名的公告(招聘、面试、专家名单、资格人员名单等)不进看板的条目列表
PERSON_LIST_RE = re.compile(
    r"招聘|录用|面试|体检|考察及有关|资格复审|拟聘|聘任|任前|任职公示|毕业生|人员名单|专家名单|入库专家|"
    r"资格认定公示|人员资格证书|执法辅助人员|责任人名单|获奖名单|成绩的通知|先进个人|行风监督员|组成人员")
#: 公司内部信息(内部了解、未见公开渠道、内部文件、拜访纪要之类)不进看板:标题、正文开头、摘要、L2 文字里带着就整条不收
INTERNAL_RE = re.compile(r"内部了解|未见公开渠道|内部·|拜访纪要|拜访记录|内部文件|内部底数|内部资料|仅供内部|内部参考|"
                         r"请勿外传|不得外传")
#: 标着密级的材料也不收(只看标题和正文开头,正文里讲保密规定的不算)
SECRET_RE = re.compile(r"密级|机密")
#: 标题、摘要或 L2 文字里点了个人姓名(「职务 + 姓名 + 署名/指出…」)的条目不进看板
NAMED_PERSON_RE = re.compile(
    r"(?:书记|主任|局长|部长|总理|主席|厅长|市长|省长|署长|行长|会长|理事长|董事长|总经理|院长|委员|司长|处长)"
    r"[\u4e00-\u9fff]{2,3}(?:署名|指出|表示|强调|介绍|说|发表|撰文|讲话|出席|主持|会见|调研)")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")

RELATION_ZH = {
    "references": ("引用", "被引用"), "aligns_with": ("同向", "同向"), "cites_basis": ("以之为依据", "被作为依据"),
    "clarifies": ("细化", "被细化"), "derives_from": ("落地自", "被落地"), "extends": ("扩展", "被扩展"),
    "iterates": ("迭代", "被迭代"), "supersedes": ("废止", "被废止"), "conflicts_with": ("冲突", "冲突"),
}
MAX_RELATIONS = 12
EXCERPT_CHARS = 300


# ---- 小工具 ------------------------------------------------------------------

def read_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").split("\n"):
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def as_list(v) -> list[str]:
    if v is None or v == "":
        return []
    return [str(x) for x in v] if isinstance(v, list) else [str(v)]


def host_of(url: str) -> str:
    m = re.match(r"https?://([^/?#]+)", url or "")
    return m.group(1).lower() if m else ""


def vault_head(vault: Path) -> dict:
    """政策库最后一次提交的时间和说明(数据截至日)。"""
    try:
        out = subprocess.run(["git", "-C", str(vault), "log", "-1", "--format=%h%n%cI%n%s"],
                             capture_output=True, text=True, check=True).stdout.split("\n")
        return {"commit": out[0], "committed_at": out[1], "subject": out[2]}
    except Exception:
        return {"commit": "", "committed_at": "", "subject": ""}


# ---- 正文开头:去导航、去联系人和带职务称呼的句子 ------------------------------

_MOJIBAKE = re.compile(r"[\u00c0-\u00ff][\u0080-\u00bf]")
_HTML_TAG = re.compile(r"<\s*/?\s*[a-zA-Z][^>\n]*>?")
_MD_IMG = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_URL = re.compile(r"(?:https?://|www\.)\S+")
_LIST_MARK = re.compile(r"^(?:[-*+•·]|\d{1,2}[.、)])\s+")
_NAV = re.compile(r"首页|当前位置|所在的位置|您的位置|欢迎访问|字号|字体|打印|关闭窗口|分享|收藏|浏览次数|访问量|"
                  r"返回顶部|扫一扫|微信|微博|无障碍|网站地图|版权所有|主办单位|ICP|备案|来源[:：]|发布时间|"
                  r"发布日期|信息来源|索\s*引\s*号|标\s*题[:：]|主题分类|成文日期|发文机关|有效性|公开事项|目录项|"
                  r"人工智能朗读|网站标识码|公网安备|承办单位|历史搜索|热门搜索|IPv6|【[大中小]】")
PHONE_RE = re.compile(r"(?<!\d)(?:1[3-9]\d{9}|[(（]?0\d{2,3}[)）]?[-－—–\s]?\d{7,8})(?!\d)")
#: 句子里有这些就整句不要:联系方式、证件,以及职务称呼(称呼前后往往就是人名)
_PERSONAL = re.compile(r"@|联系人|联系电话|联系方式|电话|传真|手机|邮箱|邮编|地址[:：]|身份证|同志|总理|国务委员|"
                       r"部长|署长|行长|司长|局长|厅长|主任|书记|处长|科长|股长|市长|省长|州长|县长|区长|乡长|镇长|"
                       r"主席|院长|校长|所长|站长|队长|组长|会长|理事长|秘书长|董事长|总经理|经理|先生|女士|"
                       r"记者|通讯员|编辑|审核|校对|签发|讲话|指出|强调|表示")
_CJK = re.compile(r"[\u4e00-\u9fff]")
_END = "。：:；;！？!?"


def _fix_mojibake(line: str) -> str:
    """UTF-8 被当 latin-1 解码的乱码行还原;还原不了的整行丢掉。"""
    if not _MOJIBAKE.search(line):
        return line
    try:
        return line.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return ""


def _is_menu(line: str) -> bool:
    """一行全是空格隔开的短词(网站栏目、导航菜单),没有句子。"""
    tokens = line.split(" ")
    if len(tokens) < 6 or re.search(r"[。；！？]", line):
        return False
    return sum(1 for t in tokens if len(t) <= 8) >= 0.8 * len(tokens)


def _strip_menu_prefix(line: str) -> str:
    """行首连着一串栏目名(短词、没标点)的,把这串去掉。"""
    tokens = line.split(" ")
    n = 0
    while n < len(tokens) and len(tokens[n]) <= 10 and re.fullmatch(r"[\u4e00-\u9fff]+", tokens[n]):
        n += 1
    return " ".join(tokens[n:]) if n >= 3 else line


def _clean_line(raw: str) -> str:
    line = _fix_mojibake(raw)
    line = _URL.sub(" ", _MD_LINK.sub(r"\1", _MD_IMG.sub(" ", _HTML_TAG.sub(" ", line))))
    line = re.sub(r"-{3,}|={3,}", " ", line)
    line = re.sub(r"[#>*|`_~\\]+", " ", line)
    line = _LIST_MARK.sub("", line.strip())
    return _strip_menu_prefix(re.sub(r"\s+", " ", line).strip())


def excerpt(body: str, title: str, limit: int = EXCERPT_CHARS) -> str:
    """正文开头一小段,给详情页当「要点」的兜底。网页导航、联系人、带职务称呼的句子都去掉。"""
    lines = []
    for raw in body.split("\n"):  # 不用 splitlines:乱码里的 \x85 会被它当成换行
        line = _clean_line(raw)
        if not line or line == "政策原文" or (title and line in title):
            continue
        if len(line) < 12 and line[-1] not in _END:
            continue  # 菜单项、栏目名
        if (_NAV.search(line) and len(line) < 90) or line.count(" - ") >= 2 or _is_menu(line):
            continue
        lines.append(line)
    out = ""
    for s in re.split(r"(?<=[。！？；!?;])", " ".join(lines)):
        s = re.sub(r"^[\d\s:：\-./]{6,}", "", s.strip()).strip()  # 句首的访问计数、时间戳
        if len(_CJK.findall(s)) < 4 or _PERSONAL.search(s) or PHONE_RE.search(s):
            continue
        if _NAV.search(s) and len(s) < 120:
            continue
        if len(out) + len(s) > limit:
            out += s[: max(0, limit - len(out))] + "…"
            break
        out += s
    return out


def redact(text) -> str:
    """摘要、L2 文字里偶尔带着机构电话、邮箱:换成「略」,别的一字不改。"""
    return EMAIL_RE.sub("(邮箱略)", PHONE_RE.sub("(电话略)", str(text or "")))


# ---- 地区 --------------------------------------------------------------------

_PROV_BY_SHORT = {short: _CODE_TO_PROV[code] for code, short in PROVINCE_SHORT_BY_CODE.items()
                  if code in _CODE_TO_PROV}


def province_of(pid: str, level: str, name: str, code: str, city_to_prov: dict) -> str:
    """条目归哪个省:区划代码前两位 → 地区名本身是省 → 渠道目录里的城市 → 编号里的省份缩写(L1 发号规则)。"""
    if level == "国家":
        return "全国"
    code = (code or "").strip()
    if re.fullmatch(r"\d{6}", code) and code[:2] in _CODE_TO_PROV:
        return _CODE_TO_PROV[code[:2]]
    if name in _CODE_TO_PROV.values():
        return name
    if name in city_to_prov:
        return city_to_prov[name]
    for prov in _CODE_TO_PROV.values():
        short = re.sub(r"(省|市|壮族自治区|回族自治区|维吾尔自治区|自治区)$", "", prov)
        if name.startswith(short):
            return prov
    parts = pid.split("_")
    if len(parts) > 2 and parts[2] in _PROV_BY_SHORT:
        return _PROV_BY_SHORT[parts[2]]
    return "未知"


# ---- 月刊选目单(只数件数) -----------------------------------------------------

def monthly_issues(state_dir: Path | None, raw_pids: set[str]) -> tuple[list[dict], dict]:
    """返回 (每期件数, pid→进过的期别)。只认 national_detail / local_detail / roundup 里的选用件。"""
    issues, picked = [], collections.defaultdict(list)
    if not state_dir:
        return issues, picked
    for slate_path in sorted(state_dir.glob("*月刊/slate.json")):
        slate = json.loads(slate_path.read_text(encoding="utf-8"))
        label = str(slate.get("task") or slate_path.parent.name)
        pids = []
        for section in ("national_detail", "local_detail"):
            pids += [e.get("pid") for e in slate.get(section) or [] if isinstance(e, dict)]
        for group in slate.get("roundup") or []:
            for m in group.get("members") or []:
                pids.append(m.get("pid") if isinstance(m, dict) else m)
        uniq = list(dict.fromkeys(p for p in pids if p))
        in_vault = [p for p in uniq if p in raw_pids]
        for p in in_vault:
            picked[p].append(label)
        window = slate.get("window") or {}
        issues.append({"issue": label, "window": [window.get("lo", ""), window.get("hi", "")],
                       "selected": len(uniq), "in_vault": len(in_vault), "outside_vault": len(uniq) - len(in_vault),
                       "detail": sum(len(slate.get(s) or []) for s in ("national_detail", "local_detail")),
                       "roundup_groups": len(slate.get("roundup") or [])})
    return issues, picked


# ---- 主流程 ------------------------------------------------------------------

def build(vault: Path, monthly_state: Path | None) -> tuple[dict, dict, dict]:
    head = vault_head(vault)
    as_of = (head["committed_at"] or dt.date.today().isoformat())[:10]

    # 原文:与同步、巡检同一个读法
    recs = load_policies(str(vault / "0_raw" / "policies"))
    by_pid = collections.defaultdict(list)
    for r in recs:
        by_pid[r.pid].append(r)
    projected_rec = {r.pid: r for r in recs}  # 同步按编号建索引,同号只留排在最后的一篇

    # L2
    bv = {}
    for fp in sorted(glob.glob(str(vault / "_meta" / "business_view" / "*.yaml"))):
        d = read_yaml(Path(fp))
        if d and d.get("pid"):
            bv[d["pid"]] = d
    summaries = {d["policy_id"]: d for d in read_jsonl(vault / "1_extracted" / "policy_summaries.jsonl")
                 if d.get("policy_id")}
    registry = read_yaml(vault / "_meta" / "themes_registry.yaml") or {}
    themes = [{"id": t["id"], "zh": t.get("zh") or t["id"]} for t in registry.get("themes") or []]
    theme_zh = {t["id"]: t["zh"] for t in themes}
    relations = []
    for fp in sorted(glob.glob(str(vault / "1_extracted" / "relations" / "*.jsonl"))):
        relations += read_jsonl(Path(fp))

    # 出口:同步(不连库,只算应写入的行)、对外语料
    rows, rejected = collect_policy_rows(vault, pipeline_version=1)
    projected_pids = {r["pipeline_pid"] for r in rows}
    rows_without_adcode = sum(1 for r in rows if not r.get("adcode"))
    relation_rows = collect_relation_rows(vault, pipeline_version=1)
    commentary_rows = collect_commentary_rows(vault, pipeline_version=1)
    public_records, public_excluded = export_public(vault)

    # 守恒巡检(原项目 PR 1184):按数据截至日算渠道停更;不给 DATABASE_URL,② 算不了
    result = audit.run(str(vault), str(CATALOG), str(EXEMPTIONS), dsn=None,
                       today=dt.date.fromisoformat(as_of))

    catalog = load_catalog(CATALOG)
    city_to_prov = {c.city: c.province for c in catalog if c.province and c.province != "国家"}

    issues, monthly_picked = monthly_issues(monthly_state, set(by_pid))

    # ---- 条目 ----
    items, excluded = [], collections.Counter()
    for r in recs:
        _, body = split_frontmatter(Path(r.path).read_text(encoding="utf-8"))
        fm = r.raw_fm
        title = (r.title or "").strip()
        if PERSON_LIST_RE.search(title):
            excluded["人员名单类公告(正文是人名)"] += 1
            continue
        if INTERNAL_RE.search(title + body[:600]) or SECRET_RE.search(title + body[:600]):
            excluded["公司内部信息或标着密级的材料"] += 1
            continue
        region = fm.get("region") if isinstance(fm.get("region"), dict) else {}
        level = str(region.get("level") or "")
        prov = fm.get("provenance") or {}
        group = by_pid[r.pid]
        own_name = Path(r.path).name
        b = bv.get(r.pid)
        l2_here = False
        if b is not None:
            src = Path(str(b.get("sanitized_from") or "")).name
            names = [Path(x.path).name for x in group]
            l2_here = len(group) == 1 or src == own_name or (src not in names and projected_rec[r.pid] is r)
        item = {
            "pid": r.pid,
            "title": title,
            "doc_no": (r.official_number or "").strip(),
            "issuer": as_list(fm.get("issuer")),
            "date": str(fm.get("date") or "").strip(),
            "level": level,
            "region": str(region.get("name") or ""),
            "region_code": str(region.get("code") or ""),
            "province": province_of(r.pid, level, str(region.get("name") or ""), str(region.get("code") or ""),
                                    city_to_prov),
            "url": r.url,
            "site": host_of(r.url),
            "source_type": str(prov.get("source_type") or ""),
            "fetched_at": str(prov.get("fetched_at") or "")[:10],
            "excerpt": excerpt(body, title),
            "summary": None,
            "l2": None,
            "flags": {},
            "relations": [],
        }
        s = summaries.get(r.pid)
        if s and (len(group) == 1 or l2_here):
            item["summary"] = {"text": redact(s.get("summary")), "one_liner": redact(s.get("summary_one_liner")),
                               "reading_value": redact(s.get("reading_value"))}
        if b is not None and l2_here:
            item["l2"] = {
                "themes": [t for t in b.get("themes") or []],
                "primary_theme": b.get("primary_theme") or "",
                "comprehensive": bool(b.get("comprehensive")),
                "scores": b.get("scores") or {},
                "importance": b.get("重要性"),
                "action": b.get("行动分类") or "",
                "value_tags": as_list(b.get("价值标签")),
                "impact": {k: redact(v) for k, v in b.get("影响分析").items()}
                          if isinstance(b.get("影响分析"), dict) else {},
                "advice": [redact(x) for x in as_list(b.get("行动建议"))],
                "one_liner": redact(b.get("didi_impact_one_liner")),
                "model": b.get("extracted_model") or "",
                "extracted_at": str(b.get("extracted_at") or "")[:10],
                "deep": bool(b.get("gate_passed_deep")),
                "archived": b.get("archive") or "",
            }
        flags = item["flags"]
        if len(group) > 1:
            flags["same_pid_files"] = len(group)
            flags["platform_file_title"] = projected_rec[r.pid].title
        if b is None:
            flags["no_l2"] = True
        elif not l2_here:
            flags["l2_on_other_file"] = True
        if projected_rec[r.pid] is r:
            if r.pid in projected_pids:
                flags["in_platform"] = True
            elif b is not None:
                reason = next((x["reason"] for x in rejected if x["pid"] == r.pid), "")
                flags["platform_rejected"] = "发文日缺失" if "date" in reason else reason
        if r.pid in monthly_picked and (len(group) == 1 or l2_here):
            flags["monthly"] = monthly_picked[r.pid]
        texts = [title, item["excerpt"], *(item["summary"] or {}).values()]
        if item["l2"]:
            texts += [item["l2"]["one_liner"], *item["l2"]["impact"].values(), *item["l2"]["advice"]]
        if any(INTERNAL_RE.search(t or "") for t in texts):
            excluded["公司内部信息或标着密级的材料"] += 1
            continue
        if any(NAMED_PERSON_RE.search(t or "") for t in texts):
            excluded["标题、摘要或 L2 里点了个人姓名"] += 1
            continue
        items.append(item)

    # 相关政策(L2 关系):只带类型、方向和对方编号,不带证据原文
    shown = {it["pid"] for it in items}
    rel_by_pid = collections.defaultdict(list)
    for e in relations:
        a, z, rel = e.get("from"), e.get("to"), e.get("rel")
        if not (a and z and rel in RELATION_ZH):
            continue
        rel_by_pid[a].append([rel, "out", z, e.get("confidence")])
        rel_by_pid[z].append([rel, "in", a, e.get("confidence")])
    for it in items:
        if it["l2"] is None and it["flags"].get("same_pid_files"):
            continue
        rels = [x for x in rel_by_pid.get(it["pid"], []) if x[2] in shown and x[2] != it["pid"]]
        rels.sort(key=lambda x: -(x[3] or 0))
        it["relations"] = [x[:3] for x in rels[:MAX_RELATIONS]]

    items.sort(key=lambda x: (x["date"], x["pid"]), reverse=True)

    issuer_count = collections.Counter(i for it in items for i in it["issuer"])
    policies = {
        "as_of": as_of,
        "themes": themes,
        "relation_types": {k: list(v) for k, v in RELATION_ZH.items()},
        "issuer_suggestions": [name for name, _ in issuer_count.most_common(80)],
        "excluded": [{"reason": k, "count": v} for k, v in sorted(excluded.items())],
        "items": items,
    }

    # ---- 链路件数 ----
    pids_with_raw = set(by_pid)
    bv_with_raw = [p for p in bv if p in pids_with_raw]
    collided = {p: g for p, g in by_pid.items() if len(g) > 1}
    level_count = collections.Counter(str((r.raw_fm.get("region") or {}).get("level") or "") for r in recs)
    month_count = collections.Counter(str((r.raw_fm.get("provenance") or {}).get("fetched_at") or "")[:7] for r in recs)
    model_count = collections.Counter(b.get("extracted_model") or "?" for b in bv.values())
    model_themed = collections.Counter(b.get("extracted_model") or "?" for b in bv.values() if b.get("themes"))
    theme_count = collections.Counter(t for b in bv.values() for t in b.get("themes") or [])
    rel_count = collections.Counter(e.get("rel") for e in relations)
    status_count = collections.Counter(getattr(c.status, "value", c.status) for c in catalog)
    reject_count = collections.Counter("发文日缺失" if "date" in x["reason"] else
                                       "L2 找不到原文" if "raw not found" in x["reason"] else x["reason"]
                                       for x in rejected)
    count_files = lambda sub: sum(1 for p in (vault / sub).rglob("*") if p.is_file() and p.name != ".DS_Store")  # noqa: E731

    overview = {
        "as_of": as_of,
        "vault_head": head,
        "recorded_at": dt.date.today().isoformat(),
        "l1": {
            "policy_files": len(recs),
            "policy_pids": len(by_pid),
            "collision_groups": len(collided),
            "collision_files": sum(len(g) for g in collided.values()),
            "commentaries": count_files("0_raw/commentaries"),
            "archived": count_files("0_raw/_archive"),
            "duplicates": count_files("0_raw/_duplicates"),
            "quarantined": sum(1 for p in (vault / "_quarantine").rglob("*.md") if p.name != "README.md"),
            "by_level": [[k, v] for k, v in level_count.most_common()],
            "by_fetch_month": sorted([k, v] for k, v in month_count.items() if k),
            "channels": {"total": len(catalog), "by_status": dict(status_count.most_common())},
        },
        "vault_dirs": [
            {"dir": "0_raw/policies/", "what": "L1 政策原文,入库后不改", "count": len(recs), "unit": "篇"},
            {"dir": "0_raw/commentaries/", "what": "L1 评论、解读原文", "count": count_files("0_raw/commentaries"),
             "unit": "篇"},
            {"dir": "0_raw/_archive/ · _duplicates/", "what": "重抓换下的旧版、去重隔离",
             "count": count_files("0_raw/_archive") + count_files("0_raw/_duplicates"), "unit": "份"},
            {"dir": "1_extracted/", "what": "L2 通用派生:摘要、关系、评论信号",
             "count": len(summaries) + len(relations) + len(commentary_rows), "unit": "条"},
            {"dir": "_meta/business_view/", "what": "L2 业务派生:主题打分、影响分析", "count": len(bv), "unit": "份"},
            {"dir": "2_crystallized/", "what": "结晶层:主题页、地区页(维持,不再更新)",
             "count": count_files("2_crystallized"), "unit": "页"},
            {"dir": "3_lints/", "what": "lint 报告(停在 2026-04)", "count": count_files("3_lints"), "unit": "份"},
            {"dir": "_quarantine/", "what": "隔离区:转发来的重复件",
             "count": sum(1 for p in (vault / "_quarantine").rglob("*.md") if p.name != "README.md"), "unit": "篇"},
        ],
        "l2": {
            "business_view": len(bv),
            "business_view_with_raw": len(bv_with_raw),
            "business_view_orphan": len(bv) - len(bv_with_raw),
            "pids_without_l2": len(pids_with_raw - set(bv)),
            "themed": sum(1 for b in bv.values() if b.get("themes")),
            "impact": sum(1 for b in bv.values() if isinstance(b.get("影响分析"), dict)),
            "summaries": len(summaries),
            "relations": len(relations),
            "relations_by_type": [[k, v] for k, v in rel_count.most_common()],
            "commentary_signals": len(commentary_rows),
            "market_intel_signals": len(read_jsonl(vault / "1_extracted" / "market_intel_signals.jsonl")),
            "by_theme": [[t, theme_zh.get(t, t), n] for t, n in theme_count.most_common()],
            "by_model": [{"model": m, "count": n, "themed": model_themed[m]} for m, n in model_count.most_common()],
        },
        "exits": {
            "platform": {"rows": len(rows), "rejected": [[k, v] for k, v in reject_count.most_common()],
                         "rows_without_adcode": rows_without_adcode, "relation_rows": len(relation_rows),
                         "commentary_rows": len(commentary_rows)},
            "qa": {"searchable": len(rows), "no_l2": len(result["derivation"]),
                   "collision_hidden": sum(len(g) - 1 for g in collided.values())},
            "monthly": {"issues": issues},
            "corpus": {"exported": len(public_records),
                       "excluded": [[k, v] for k, v in collections.Counter(
                           "已知重复件" if "duplicate" in x["reason"] else x["reason"] for x in public_excluded
                       ).most_common()]},
        },
    }

    # ---- 守恒巡检结果 ----
    raw_by_pid = {r.pid: r for r in recs}
    derivation = []
    for x in result["derivation"]:
        r = raw_by_pid.get(x["pid"])
        derivation.append({**x, "level": str(((r.raw_fm.get("region") or {}) if r else {}).get("level") or ""),
                           "fetched_at": str(((r.raw_fm.get("provenance") or {}) if r else {}).get("fetched_at") or "")[:10]})
    audit_out = {
        "as_of": as_of,
        "today_used": as_of,
        "catalog": "state/T1_channels/channel_catalog.yaml",
        "exemptions": "config/audit_exemptions.yaml",
        "exemption_counts": {k: len(v or []) for k, v in (audit.load_exemptions(str(EXEMPTIONS)) or {}).items()},
        "min_mentions": result["min_mentions"],
        "stale_days": audit.STALE_DAYS,
        "derivation": derivation,
        "projection": {"computable": False, "business_view": len(bv), "sync_rows": len(rows),
                       "sync_rejected": len(rejected)},
        "coverage": [{"name": n, "mentions": c} for n, c in result["coverage"]],
        "stale": result["stale"],
        "city_suspect": result["city_suspect"],
        "report_text": audit.render(result).replace(result["checked_at"][:10], as_of, 1),
    }
    return overview, audit_out, policies


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="从本机政策库录链路看板的演示数据")
    ap.add_argument("--vault", type=Path, required=True, help="政策库克隆目录(只读)")
    ap.add_argument("--monthly-state", type=Path, help="月刊产线的 state 目录(下面是 *月刊/slate.json),只数件数")
    ap.add_argument("--out", type=Path, default=HERE / "data", help="输出目录,默认 dashboard/data")
    args = ap.parse_args(argv)
    if not (args.vault / "0_raw" / "policies").is_dir():
        raise SystemExit(f"不是政策库目录(缺 0_raw/policies): {args.vault}")

    overview, audit_out, policies = build(args.vault.resolve(), args.monthly_state)
    args.out.mkdir(parents=True, exist_ok=True)
    for name, data in (("overview.json", overview), ("audit.json", audit_out), ("policies.json", policies)):
        (args.out / name).write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"数据截至 {overview['as_of']}:政策原文 {overview['l1']['policy_files']} 篇,"
          f"看板条目 {len(policies['items'])} 条(排除 {sum(x['count'] for x in policies['excluded'])} 条),"
          f"守恒① {len(audit_out['derivation'])} 篇、③ {len(audit_out['coverage'])} 篇、④ {len(audit_out['stale'])} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
