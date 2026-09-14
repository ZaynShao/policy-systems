"""MA0:取窗 + 新鲜度闸。

取窗故意撒 [M-1, M+1] 三个月:frontmatter 的 `date` 常是生效日或发布日而非发文日,
只取当月会系统性漏掉月初月末两头的文件。真实归属交 MA2 按 RAW 落款判。

新鲜度闸的立场是**宁可不出,不出错稿**:上游没重算就中止本轮并告警,不静默降级。
月刊一个月只出一期,晚一天有人补跑;用陈数据出一期发给决策层,错误会被当成事实带走。
"""
import glob
import os
import re
import time

from scripts.l3_render import pack_lib as pl
from scripts.l3_monthly.models import Candidate

MONTH_RE = re.compile(r"^(20\d{2})-(0[1-9]|1[0-2])$")
DEFAULT_MAX_AGE_HOURS = 48


def _shift(year, month, delta):
    idx = year * 12 + (month - 1) + delta
    return idx // 12, idx % 12 + 1


def month_window(month):
    """'2026-07' → ('2026-06', '2026-08')。跨年由月序号运算保证。"""
    m = MONTH_RE.match(month or "")
    if not m:
        raise ValueError(f"month 必须形如 YYYY-MM,当前 {month!r}")
    y, mo = int(m.group(1)), int(m.group(2))
    py, pm = _shift(y, mo, -1)
    ny, nm = _shift(y, mo, +1)
    return (f"{py:04d}-{pm:02d}", f"{ny:04d}-{nm:02d}")


def window_months(month):
    prev, nxt = month_window(month)
    return (prev, month, nxt)


def in_window(date_str, month):
    return (date_str or "")[:7] in window_months(month)


def collect_candidates(vault_dir, month):
    """扫 0_raw/policies,取窗内的 + **没有 date 的**。`month=None` 表示不筛,取全库
    (MA1b 的缺口对账要拿全库比:"在不在库里"是全库问题,不是窗口问题)。

    没 date 的一律带进来并打 `date_missing`:frontmatter 缺字段不等于这篇与本月无关,
    静默丢掉就再也查不出来了。它们会在 MA1 被噪声规则筛掉大半,余下交 MA2 判。
    """
    pol_dir = os.path.join(vault_dir, "0_raw", "policies")
    out = []
    for path in sorted(glob.glob(os.path.join(pol_dir, "*.md"))):
        try:
            md = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        fm = pl.parse_frontmatter(md)
        pid = fm.get("id")
        if not pid:
            continue
        date = fm.get("date", "") or ""
        missing = not date
        if month and not missing and not in_window(date, month):
            continue
        body = md.split("---", 2)[-1].strip()
        out.append(Candidate(
            policy_id=pid, title=fm.get("title", ""),
            official_number=fm.get("official_number", "") or "",
            date=date, date_missing=missing,
            raw_path=path, body_len=len(body),
            region_name=fm.get("region_name", "") or "",
        ))
    return out


def freshness_problems(vault_dir, state_dir, max_age_hours=DEFAULT_MAX_AGE_HOURS):
    """返回问题列表;空列表 = 可以开跑。不抛异常——调用方要能一次看全所有问题。"""
    probs = []

    ac = os.path.join(state_dir, "analysis_layer", "nightly", "analysis_context.jsonl")
    if not os.path.exists(ac):
        probs.append(f"analysis_context 不存在:{ac}(上游 nightly 未跑)")
    else:
        age_h = (time.time() - os.path.getmtime(ac)) / 3600.0
        if age_h > max_age_hours:
            probs.append(f"analysis_context 已过期:{age_h:.1f} 小时未重算"
                         f"(阈值 {max_age_hours} 小时)")

    bv = os.path.join(vault_dir, "_meta", "business_view")
    if not os.path.isdir(bv) or not glob.glob(os.path.join(bv, "*.yaml")):
        probs.append(f"business_view 为空或不存在:{bv}")

    profile = os.path.join(vault_dir, "_meta", "framework", "business_strategy.yaml")
    if not os.path.exists(profile):
        probs.append(f"战略画像不存在:{profile}"
                     f"(业务口径是月刊相关性判据的唯一来源,缺件不得开跑)")

    return probs
