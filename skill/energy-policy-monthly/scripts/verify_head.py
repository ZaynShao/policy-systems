"""①选目第二步:对短名单逐条抽 RAW 真实文头(标题/文号/落款机关/落款日期)。

用法:
  python3 verify_head.py --vault <vault> --keys "碳达峰行动方案" "车船税" "绿电直连"
  python3 verify_head.py --vault <vault> --keys-file shortlist.json

为什么必须跑这一步:frontmatter 的 issuer 常是采集省份、date 常是生效日或发布日、
official_number 可能抓到侧栏噪声、id 前缀只是采集渠道。国家级文件经省级站点采到时
会被标成省份——只看 frontmatter 会把国务院文件误判成地方件。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import clean_body, fm_get, split_front  # noqa: E402

DOCNO = re.compile(r"([一-龥A-Za-z]{2,12}〔\d{4}〕\s*\d+\s*号|[一-龥]{2,12}\[\d{4}\]\s*\d+\s*号|\d{4}年第\d+号)")
ISSUER = re.compile(
    r"^\**\s*("
    r"国务院(?:办公厅)?|中共中央办公厅|"
    r"国家发展(?:和)?改革委(?:员会)?(?:办公厅)?|国家能源局(?:综合司)?|财政部|税务总局|国家税务总局|"
    r"工业和信息化部|生态环境部|交通运输部|住房和城乡建设部|商务部|市场监管总局|海关总署|"
    r"[一-龥]{2,6}(?:省|市|自治区|兵团)[一-龥]{0,12}(?:委员会|厅|局|办公室|政府|管委会)"
    r")\s*\**$"
)
DATELINE = re.compile(r"^\**\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*\**$")


def probe(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8", errors="replace")
    front, body = split_front(raw)
    text = clean_body(body)
    lines = text.splitlines()
    issuers, dates = [], []
    for ln in lines:
        m = ISSUER.match(ln.strip())
        if m:
            issuers.append(m.group(1))
        d = DATELINE.match(ln.strip())
        if d:
            dates.append(f"{d.group(1)}-{int(d.group(2)):02d}-{int(d.group(3)):02d}")
    title = ""
    for ln in lines[:30]:
        s = ln.strip().strip("*#").strip()
        if re.search(r"(通知|公告|方案|规划|意见|办法|规定|细则|批复|函)$", s) and len(s) > len(title):
            title = s
    return {
        "file": path.name,
        "pid": fm_get(front, "id"),
        "fm_date": fm_get(front, "date"),
        "raw_title": title,
        "raw_docno": sorted(set(DOCNO.findall(text)))[:3],
        "raw_issuer": list(dict.fromkeys(issuers))[:4],
        "raw_dateline": sorted(set(dates))[-2:],
        "body_chars": len(text),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", type=Path, required=True)
    ap.add_argument("--keys", nargs="*", default=[])
    ap.add_argument("--keys-file", type=Path)
    a = ap.parse_args()

    keys = list(a.keys)
    if a.keys_file:
        keys += json.loads(a.keys_file.read_text(encoding="utf-8"))
    policies = a.vault / "0_raw/policies"
    seen = set()
    for kw in keys:
        hits = [p for p in sorted(policies.glob("*.md")) if kw in p.name]
        if not hits:
            print(f"!! 未命中文件名: {kw}(可能标题被截断,试更短的关键词)")
            continue
        for p in hits:
            if p.name in seen:
                continue
            seen.add(p.name)
            r = probe(p)
            print(f"\n【{kw}】")
            print(f"  pid={r['pid']}  fm_date={r['fm_date']}  正文{r['body_chars']}字")
            print(f"  RAW标题: {r['raw_title'][:64]}")
            print(f"  RAW文号: {r['raw_docno']}")
            print(f"  RAW机关: {r['raw_issuer']}")
            print(f"  RAW落款: {r['raw_dateline']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
