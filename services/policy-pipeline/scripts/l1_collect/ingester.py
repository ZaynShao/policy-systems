"""写 vault/0_raw/policies/<filename>.md,过 validate_schema 校验。

ID 生成规则(对齐 SCHEMA §2):
  P_<year>_<issuer_short>_<num_or_hash>

issuer_short 来源:
  1. 中央部委 lookup table(ISSUER_SHORT_TABLE)
  2. 市级:用 city_code 前 2 位映射省级 short(BJ/SH/...),后接城市拼音 → 形如 BJ_城市码
"""
from __future__ import annotations
import hashlib
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
import yaml

VAULT = Path.home() / "Documents" / "Zayn Main" / "政策分析"
POLICIES_DIR = VAULT / "0_raw" / "policies"
CST = timezone(timedelta(hours=8))

ISSUER_SHORT_TABLE = {
    "国家发展和改革委员会": "NDRC",
    "国家能源局": "NEA",
    "工业和信息化部": "MIIT",
    "商务部": "MOFCOM",
    "住房和城乡建设部": "MOHURD",
    "生态环境部": "MEE",
    "财政部": "MOF",
    "国务院": "SC",
}

# 省码(国标 6 位的前 2 位)→ short
PROVINCE_SHORT_BY_CODE = {
    "11": "BJ", "12": "TJ", "13": "HE", "14": "SX", "15": "NM",
    "21": "LN", "22": "JL", "23": "HL",
    "31": "SH", "32": "JS", "33": "ZJ", "34": "AH", "35": "FJ",
    "36": "JX", "37": "SD",
    "41": "HA", "42": "HB", "43": "HN", "44": "GD", "45": "GX",
    "46": "HI",
    "50": "CQ", "51": "SC", "52": "GZ", "53": "YN", "54": "XZ",
    "61": "SN", "62": "GS", "63": "QH", "64": "NX", "65": "XJ",
    "71": "TW", "81": "HK", "82": "MO",
}


def _issuer_short(issuer: Optional[str], city_code: Optional[str] = None,
                  channel_type: Optional[str] = None) -> str:
    if issuer and issuer in ISSUER_SHORT_TABLE:
        return ISSUER_SHORT_TABLE[issuer]
    if city_code and len(city_code) >= 2:
        prov = PROVINCE_SHORT_BY_CODE.get(city_code[:2], "OTHER")
        # 市级用 prov_<channel> 区分(避免一个市的多个 channel 撞 id)
        ct_short = {"发改委": "FGW", "能源局": "NYJ", "政府网": "GOV",
                    "经信委": "JXW", "工信": "GX", "商务局": "SWJ"}.get(channel_type or "", "X")
        return f"{prov}_{ct_short}"
    return "OTHER"


def _hash8(s: str) -> str:
    return hashlib.sha1(s.encode()).hexdigest()[:8]


def _suffix(n: int) -> str:
    """1->a, 26->z, 27->aa(双射 26 进制)。SCHEMA §2 的 _a/_b 后缀序列。"""
    out = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        out = chr(97 + r) + out
    return out


class PidRegistry:
    """policy_id 占位表,兑现 SCHEMA §2「碰撞:加 _a _b 后缀」。

    compute_pid 只截文号尾数(丢掉文种前缀与括号年),不同文档天然可能算出同一个
    候选 id;上游文号抽错时更是成片相撞。这里按「文档身份」发号:
      - 号还空着            -> 用候选号
      - 已被同一份文档占着  -> 拿回原号(重跑幂等,不会越跑后缀越长)
      - 已被别的文档占着    -> 顺延 _a/_b/... 到第一个可用号

    身份 = 归一后的 URL(复用 dedup 口径)。生产实测 21 组碰撞里 20 组是不同 URL
    的不同文档(必须分号),1 组是同 URL 重复入库(必须复用原号)。
    """

    def __init__(self) -> None:
        self._owner: dict = {}          # pid -> identity

    @staticmethod
    def _norm(identity: str) -> str:
        from .dedup import normalize_url
        return normalize_url(identity) or identity or ""

    def reserve(self, candidate: str, identity: str) -> str:
        ident = self._norm(identity)
        n = 0
        while True:
            pid = candidate if n == 0 else f"{candidate}_{_suffix(n)}"
            owner = self._owner.get(pid)
            if owner is None:
                self._owner[pid] = ident
                return pid
            if owner == ident:
                return pid
            n += 1

    @classmethod
    def from_vault_policies(cls, policies_dir) -> "PidRegistry":
        """扫 vault 现有 0_raw/policies/,把已发出去的号登记为已占用。"""
        reg = cls()
        for f in sorted(Path(policies_dir).glob("*.md")):
            try:
                txt = f.read_text(encoding="utf-8")[:4000]
            except Exception:
                continue
            m = re.search(r"^---\n(.*?)\n---", txt, re.S)
            if not m:
                continue
            try:
                fm = yaml.safe_load(m.group(1)) or {}
            except Exception:
                continue
            if not isinstance(fm, dict):
                continue
            pid = fm.get("id")
            if not pid:
                continue
            url = ((fm.get("provenance") or {}).get("url")) or ""
            reg._owner.setdefault(pid, cls._norm(url))
        return reg


def compute_pid(date: str, issuer: Optional[str], official_number: str,
                title: str, city_code: Optional[str] = None,
                channel_type: Optional[str] = None) -> str:
    year = (date or "1900").split("-")[0]
    short = _issuer_short(issuer, city_code, channel_type)
    if official_number:
        m = re.search(r"(\d+)\s*号", official_number)
        tail = m.group(1) if m else _hash8(official_number)
    else:
        tail = _hash8(f"{date}|{title}")
    return f"P_{year}_{short}_{tail}"


def _sanitize_filename(title: str) -> str:
    t = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", title)[:80]   # 含控制字符:内嵌换行/制表符会崩 produce_and_push
    return t.strip() or "untitled"


def _infer_region(issuer: Optional[str], city: Optional[str],
                  city_code: Optional[str]) -> dict:
    """按 city_code 区分级别(省级渠道 city=省名/code 末尾 0000,不能一律判市)。
    000000=国家;末尾 0000(非000000)=省;其余=市。治省级渠道被误标 level=市。"""
    if city:
        if city_code == "000000":
            return {"level": "国家", "code": "000000", "name": "全国"}
        if city_code and city_code.endswith("0000"):
            return {"level": "省", "code": city_code, "name": city}
        return {"level": "市", "code": city_code or "", "name": city}
    if issuer in ISSUER_SHORT_TABLE:
        return {"level": "国家", "code": "000000", "name": "全国"}
    return {"level": "", "code": "", "name": ""}


def ingest_one(*, url: str, title: str, official_number: str, date: str,
               issuer: Optional[str], body: str,
               city: Optional[str] = None, city_code: Optional[str] = None,
               province: Optional[str] = None, channel_type: Optional[str] = None,
               via: str = "trafilatura", confidence: float = 0.85,
               out_dir: Path = POLICIES_DIR,
               registry: "PidRegistry | None" = None) -> tuple:
    """生成 vault md 文件,返回 (md 路径, pid)。out_dir 默认 POLICIES_DIR,可覆盖用于 staging。

    registry 省略时按 out_dir 现存文件临时建表(单篇入库够用);批量入库应由调用方
    建一次传进来,避免每篇重扫一遍目录。
    """
    pid = compute_pid(date, issuer, official_number, title, city_code, channel_type)
    reg = registry if registry is not None else PidRegistry.from_vault_policies(out_dir)
    pid = reg.reserve(pid, identity=url)
    region = _infer_region(issuer, city, city_code)
    fm = {
        "id": pid,
        "aliases": [pid],
        "title": title,
        "official_number": official_number or "",
        "issuer": [issuer] if issuer else [],
        "date": date or "",
        "region": region,
        "provenance": {
            "url": url,
            "source_type": "A",
            "fetched_via": via,
            "fetched_at": datetime.now(CST).isoformat(timespec="seconds"),
            "collected_by": "t1-city-collection",
            "collected_mode": "build-phase-manual",
            "confidence": confidence,
        },
        "type": "policy",
    }
    body_md = f"## 政策原文\n\n{body.strip()}\n"
    fn = out_dir / f"{_sanitize_filename(title)}.md"
    n = 1
    while fn.exists():
        fn = out_dir / f"{_sanitize_filename(title)}__{n}.md"
        n += 1
    content = "---\n" + yaml.dump(fm, allow_unicode=True, sort_keys=False) + "---\n\n" + body_md
    fn.write_text(content, encoding="utf-8")
    return fn, pid


# 内嵌 minimal schema check(白名单 + 必填,与 audit/validate_schema.py 对齐)
# 全量 schema 校验留给 T7.3 跑完后调 validate_schema.py --vault 做最终 gate。
_FM_ALLOWED = {
    "id", "aliases", "title", "official_number", "issuer", "date",
    "region", "provenance", "issuer_canonical", "type", "subtype",
    "dup_aliases", "dedup_at", "dedup_rule", "_duplicate_of", "_duplicate_reason",
    "confidence",
}
_FM_REQUIRED = {"id", "title", "date", "region", "provenance"}


def validate_with_schema(path: Path) -> bool:
    """轻量入库校验:frontmatter 白名单 + 必填 + body 不含禁止段。"""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return False
    m = re.search(r"^---\n(.*?)\n---", text, re.S)
    if not m:
        return False
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except Exception:
        return False
    if not isinstance(fm, dict):
        return False
    keys = set(fm.keys())
    if keys - _FM_ALLOWED:
        return False
    if _FM_REQUIRED - keys:
        return False
    # body 不能含禁止段
    body = text[m.end():]
    for forbidden in ("## 摘要", "## 初步影响分析", "## 六维评分",
                      "## 业务关联", "## 跟进建议", "## 战略地位映射"):
        if forbidden in body:
            return False
    return True
