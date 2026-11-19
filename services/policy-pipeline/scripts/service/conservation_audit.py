"""守恒巡检:每段链路的「应有 / 实有 / 差额」。

与 closure_audit 的分工要说清楚:那个查**活性**——各 state 文件是不是 26 小时内
动过。它对丢件是盲的。2026-09-07 查实的两件事都发生在它眼皮底下:51 篇政策有原文
没标签因而进不了库、国家能源局渠道连着几个月只回 2017 年的存档件——期间每个
state 文件都在正常更新,活性审计全绿。

本脚本问的是另一个问题:**东西有没有丢**。四段各有一个能核对的等式,差额不为零
就报出来并附清单。差额只能通过 config/audit_exemptions.yaml 里的显式豁免归零,
豁免走 PR、带原因和日期——静默忽略正是上一轮出事的方式。

纯 stdlib + yaml,cron 友好:永不 raise,恒 exit 0(告警通道坏了不该弄死巡检)。
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

from scripts.service import notify

#: 渠道多久没出新件算可疑。按层级分:国家部委几乎每周发文,省级慢一些,
#: 市级本来就稀疏、且数量占全目录八成,逐条告警只会淹没真信号,只统计不点名。
STALE_DAYS = {"国家": 21, "省": 90}
#: 报告排序用。同样是停更,国家部委的一条比省级的一条重要得多——按"烂了多久"排,
#: 一条 1811 天的省级市监渠道会把国家能源局挤到看不见的地方。
_LEVEL_RANK = {"国家": 0, "省": 1, "市": 2, "区": 3}

#: 解读文章里被《》引用到几次才算"这篇政策我们本该有"。
#: 阈值 3 → 65 篇;阈值 5 → 19 篇。取 5 起步,先把最扎眼的清掉再放宽。
MIN_MENTIONS = 5

_ID_RE = re.compile(r"^id:\s*(\S+)", re.M)
_TITLE_RE = re.compile(r"^title:\s*(.+)$", re.M)
_DATE_RE = re.compile(r"^date:\s*'?(\d{4}-\d{2}-\d{2})", re.M)
_URL_RE = re.compile(r"^\s*url:\s*(\S+)", re.M)
_QUOTED_RE = re.compile(r"《([^《》]{6,40})》")
_FORM_RE = re.compile(r"办法|规定|意见|方案|通知|规划|细则|条例|指南|规则|决定|批复")
_ENERGY_RE = re.compile(
    r"电力|电价|电网|售电|购电|输配电|电能|用电|发电|储能|充电|换电|加油|成品油|"
    r"油品|燃油|天然气|氢|光伏|风电|新能源|可再生|绿电|绿证|碳|能源|电动汽车|"
    r"车网|虚拟电厂|需求响应"
)


def normalize_title(s: str) -> str:
    """比对政策名用。括号里的"(征求意见稿)""(试行)"和各种引号不参与判等。"""
    return re.sub(r"[（(].*?[)）]|[\s《》“”\"'’‘]", "", s)


# ---- 读盘(薄封装,判定逻辑一律放纯函数) --------------------------------------


def read_policy_meta(vault: str) -> list[dict]:
    """0_raw/policies 每篇的 pid / 标题 / 发文日 / 来源域名。"""
    out = []
    for fp in glob.glob(str(Path(vault) / "0_raw" / "policies" / "*.md")):
        head = Path(fp).read_text(encoding="utf-8", errors="replace")[:1500]
        m = _ID_RE.search(head)
        if not m:
            continue
        u = _URL_RE.search(head)
        host = ""
        if u:
            hm = re.match(r"https?://([^/]+)", u.group(1))
            host = hm.group(1) if hm else ""
        t = _TITLE_RE.search(head)
        d = _DATE_RE.search(head)
        out.append({"pid": m.group(1), "title": (t.group(1).strip() if t else ""),
                    "date": (d.group(1) if d else ""), "host": host})
    return out


def read_business_view_pids(vault: str) -> set[str]:
    return {Path(p).stem for p in
            glob.glob(str(Path(vault) / "_meta" / "business_view" / "*.yaml"))}


def count_commentary_mentions(vault: str) -> collections.Counter:
    """解读文章里被《》点名的能源政策,按出现次数计。

    这是唯一能发现"根本没采到"的信号:漏采的难处在于你不知道本该有什么,
    而自家库里的解读文章恰好替你列了清单。
    """
    cnt: collections.Counter = collections.Counter()
    for fp in glob.glob(str(Path(vault) / "0_raw" / "commentaries" / "*.md")):
        body = Path(fp).read_text(encoding="utf-8", errors="replace")
        for m in _QUOTED_RE.finditer(body):
            name = m.group(1).strip()
            if _FORM_RE.search(name) and _ENERGY_RE.search(name):
                cnt[name] += 1
    return cnt


def load_exemptions(path: str) -> dict:
    """豁免表。缺文件 = 没有豁免,不是错误。"""
    p = Path(path)
    if not p.exists():
        return {}
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _exempt_set(exemptions: dict, section: str, key: str) -> set[str]:
    rows = exemptions.get(section) or []
    return {str(r.get(key, "")) for r in rows if isinstance(r, dict) and r.get(key)}


# ---- 纯函数:四段守恒 --------------------------------------------------------


def diff_derivation(policies: list[dict], bv_pids: set[str],
                    exempt: set[str]) -> list[dict]:
    """① 有原文、没 business_view → 投影不到 heng-pg → 问答查不到。

    vault→pg 的投影以 business_view 为遍历源(sync/run_sync.py),所以这一段的
    差额等于"问答看不见的政策数",不是一个内部指标。
    """
    seen: dict[str, dict] = {}
    for p in policies:
        if p["pid"] in bv_pids or p["pid"] in exempt:
            continue
        seen.setdefault(p["pid"], p)
    return sorted(seen.values(), key=lambda x: x["date"], reverse=True)


def diff_projection(bv_count: int, pg_count: int) -> int:
    """② business_view 篇数 vs heng-pg 里 pipeline 投影行数。正数 = 有派生没进库。"""
    return bv_count - pg_count


def coverage_gaps(mentions: collections.Counter, titles: list[str],
                  min_mentions: int, exempt: set[str]) -> list[tuple[str, int]]:
    """③ 解读反复引用、库里却没有原文的政策。"""
    pool = "\n".join(normalize_title(t) for t in titles)
    ex = {normalize_title(x) for x in exempt}
    gaps = [(n, c) for n, c in mentions.items()
            if c >= min_mentions
            and normalize_title(n) not in pool
            and normalize_title(n) not in ex]
    return sorted(gaps, key=lambda x: -x[1])


def channel_last_seen(policies: list[dict]) -> dict[str, str]:
    """每个来源域名最近一篇政策的发文日。"""
    last: dict[str, str] = {}
    for p in policies:
        h, d = p["host"], p["date"]
        if not h or not d:
            continue
        if d > last.get(h, ""):
            last[h] = d
    return last


def last_seen_for(root_domain: str, last_seen: dict[str, str]) -> str:
    """按域名后缀取该渠道最近一件的日期。

    目录里的 root_domain 是 `ndrc.gov.cn`,而政策 provenance 里的 host 是
    `www.ndrc.gov.cn`、`zfxxgk.nea.gov.cn` 这类带子域的写法。直接等值比对会让
    **每一条渠道**都判成"从未出件",于是巡检第一版把全部 52 条渠道都点了名
    ——一份全是假阳性的告警和没有告警一样没用。
    """
    best = ""
    for host, d in last_seen.items():
        if (host == root_domain or host.endswith("." + root_domain)) and d > best:
            best = d
    return best


def stale_channels(channels: list, last_seen: dict[str, str], today: date,
                   exempt: set[str], stale_days: dict | None = None) -> tuple[list, int]:
    """④ 「验证」渠道多久没出新件。返回(点名清单, 市级可疑数)。

    **看的是最近一件的日期,不是有没有产出。** 国家能源局那条渠道在册九个月里
    每次扫描都稳定回 29 条、全过关键词门,任何"还在出东西吗"的检查都是绿的
    ——29 条全是 2017 年的存档。只有日期能把它认出来。
    """
    stale_days = stale_days or STALE_DAYS
    named, city_suspect = [], 0
    checked: set[tuple] = set()
    for ch in channels:
        if getattr(ch.status, "value", ch.status) != "验证":
            continue
        dom = ch.root_domain
        if dom in exempt or (dom, ch.level) in checked:
            continue
        checked.add((dom, ch.level))
        seen = last_seen_for(dom, last_seen)
        limit = stale_days.get(ch.level)
        if limit is None:
            if not seen or (today - date.fromisoformat(seen)).days > 180:
                city_suspect += 1
            continue
        age = (today - date.fromisoformat(seen)).days if seen else None
        if age is None or age > limit:
            # 曾经出件、现在停了 = 坏了,今天就要看;从未出件 = 一开始就没配对,
            # 是一笔存量欠账。混在一张单子里,前者会被后者淹掉。
            named.append({"domain": dom, "level": ch.level, "city": ch.city,
                          "last": seen or "从未", "age": age, "limit": limit,
                          "kind": "停更" if seen else "从未出件"})
    return sorted(named, key=lambda x: (x["kind"] != "停更",
                                        _LEVEL_RANK.get(x["level"], 9),
                                        -(x["age"] or 0))), city_suspect


# ---- 报告 -------------------------------------------------------------------


def render(result: dict, sample: int = 8) -> str:
    L = [f"[S2] 守恒巡检 {result['checked_at'][:10]}"]
    d = result["derivation"]
    L.append(f"① 有原文没标签(问答查不到):{len(d)} 篇")
    for x in d[:sample]:
        L.append(f"    {x['date']} {x['pid']} {x['title'][:28]}")
    if len(d) > sample:
        L.append(f"    …另 {len(d) - sample} 篇")
    proj = result["projection"]
    if proj is None:
        L.append("② 投影守恒:跳过(未给 DATABASE_URL)")
    else:
        L.append(f"② business_view {proj['bv']} 篇 vs 库内 {proj['pg']} 行,差 {proj['diff']}")
    g = result["coverage"]
    L.append(f"③ 解读反复引用、库里没原文:{len(g)} 篇(阈值 ≥{result['min_mentions']} 次)")
    for name, c in g[:sample]:
        L.append(f"    {c} 次 《{name[:30]}》")
    if len(g) > sample:
        L.append(f"    …另 {len(g) - sample} 篇")
    s = result["stale"]
    broke = [x for x in s if x["kind"] == "停更"]
    never = [x for x in s if x["kind"] != "停更"]
    L.append(f"④ 渠道停更 {len(broke)} 条(曾出件后停);从未出件 {len(never)} 条;"
             f"市级可疑 {result['city_suspect']} 条")
    for x in broke[:sample]:
        L.append(f"    停更 {x['level']} {x['city'][:12]} {x['domain']} "
                 f"最近 {x['last']} 距今 {x['age']} 天(限 {x['limit']})")
    if len(broke) > sample:
        L.append(f"    …另 {len(broke) - sample} 条停更")
    for x in never[:3]:
        L.append(f"    从未 {x['level']} {x['city'][:12]} {x['domain']}")
    if len(never) > 3:
        L.append(f"    …另 {len(never) - 3} 条从未出件")
    return "\n".join(L)


def has_violation(result: dict) -> bool:
    return bool(result["derivation"] or result["coverage"] or result["stale"]
                or (result["projection"] or {}).get("diff"))


# ---- 组装 -------------------------------------------------------------------


def _pg_projected_count(dsn: str) -> int | None:
    try:
        import psycopg2
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM "Policy" WHERE "pipelineScores" IS NOT NULL')
            return int(cur.fetchone()[0])
    except Exception:
        return None


def run(vault: str, catalog_path: str, exemptions_path: str,
        dsn: str | None = None, today: date | None = None,
        min_mentions: int = MIN_MENTIONS) -> dict:
    from scripts.l1_collect.channel_catalog import load_catalog

    today = today or date.today()
    ex = load_exemptions(exemptions_path)
    policies = read_policy_meta(vault)
    bv = read_business_view_pids(vault)

    derivation = diff_derivation(policies, bv, _exempt_set(ex, "derivation", "pid"))
    coverage = coverage_gaps(count_commentary_mentions(vault),
                             [p["title"] for p in policies], min_mentions,
                             _exempt_set(ex, "coverage", "name"))
    try:
        channels = load_catalog(Path(catalog_path))
    except Exception:
        channels = []
    stale, city_suspect = stale_channels(
        channels, channel_last_seen(policies), today,
        _exempt_set(ex, "channels", "root_domain"))

    projection = None
    if dsn:
        pg = _pg_projected_count(dsn)
        if pg is not None:
            projection = {"bv": len(bv), "pg": pg, "diff": diff_projection(len(bv), pg)}

    return {"checked_at": datetime.now().isoformat(timespec="seconds"),
            "derivation": derivation, "projection": projection,
            "coverage": coverage, "stale": stale, "city_suspect": city_suspect,
            "min_mentions": min_mentions}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", required=True)
    ap.add_argument("--catalog", default="state/T1_channels/channel_catalog.yaml")
    ap.add_argument("--exemptions", default="config/audit_exemptions.yaml")
    ap.add_argument("--min-mentions", type=int, default=MIN_MENTIONS)
    ap.add_argument("--notify", action="store_true", help="有差额时推飞书")
    ap.add_argument("--json-out", help="把完整结果(含全部清单)写到这个文件")
    args = ap.parse_args(argv)

    try:
        result = run(args.vault, args.catalog, args.exemptions,
                     dsn=os.environ.get("DATABASE_URL"),
                     min_mentions=args.min_mentions)
    except Exception as e:  # cron 友好:巡检自己坏了也要说话,不能静默
        msg = f"[S2] 守恒巡检执行失败: {type(e).__name__}: {str(e)[:200]}"
        print(msg)
        if args.notify:
            notify.send_text(msg)
        return 0

    report = render(result)
    print(report)
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8")
    if args.notify and has_violation(result):
        notify.send_text(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
