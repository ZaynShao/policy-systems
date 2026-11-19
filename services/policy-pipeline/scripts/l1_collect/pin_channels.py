"""把人工核过的列表页(pin)落到 channel_catalog:修已有行 / 补缺失行。

为什么要单独一条路径:
  - `expand_channels_l1` 是 add-if-absent(按 root_domain 跳过已在目录的),
    修不了「已在目录、但 list_url 是坏的」——而跨条线机关全属这一类;
  - `channel_reprobe` 只碰候选行,且会用发现结果**覆盖** list_url,
    正是它会把人工修好的 URL 再改回去。

按 (city, channel_type) 定位——机关会换子域(nea.gov.cn → www.nea.gov.cn),
按域名匹配会把同一个机关认成两行。默认 dry-run,`--apply` 才落盘。
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .channel_catalog import Channel, ChannelStatus, load_catalog, save_catalog
from .channel_discovery import NATIONAL_TARGETS, _host
from .connectivity_probe import probe_url

CAT = Path("state/T1_channels/channel_catalog.yaml")


def pinned_targets() -> list[dict]:
    """注册表里带 pin 的目标(当前只有国家级跨条线机关)。"""
    return [t for t in NATIONAL_TARGETS if t.get("list_url")]


def _stamp(ch: Channel, note: str) -> None:
    if note not in (ch.notes or ""):
        ch.notes = f"{ch.notes}; {note}" if ch.notes else note


def _new_channel(pin: dict) -> Channel:
    return Channel(
        city=pin["city"], province=pin["province"], level=pin["level"],
        city_code=pin["city_code"], channel_type=pin["channel_type"],
        root_domain=pin.get("root_domain") or _host(pin["list_url"]),
        list_url=pin["list_url"], source="curated", status=ChannelStatus.候选,
    )


def apply_pins(catalog: list[Channel], *, pins: list[dict], today: str) -> dict:
    """就地把 pins 写进 catalog 并逐个探测。返回计数,catalog 被原地修改。"""
    index = {(c.city, c.channel_type): c for c in catalog}
    stats = {"added": 0, "repaired": 0, "unchanged": 0,
             "verified": 0, "candidate": 0}
    for pin in pins:
        url = pin["list_url"]
        key = (pin["city"], pin["channel_type"])
        ch = index.get(key)
        if ch is None:
            ch = _new_channel(pin)
            catalog.append(ch)
            index[key] = ch
            outcome = "added"
        elif ch.list_url == url and ch.source == "curated":
            outcome = "unchanged"
        else:
            outcome = "repaired"

        pr = probe_url(url)
        ch.list_url = url
        ch.root_domain = pin.get("root_domain") or _host(url)
        ch.source = "curated"
        ch.last_probed_at = pr.probed_at
        ch.probe_result = pr.verdict
        ch.status = ChannelStatus.验证 if pr.verdict == "ok" else ChannelStatus.候选
        if outcome != "unchanged":
            _stamp(ch, f"pinned-{today}")

        stats[outcome] += 1
        stats["verified" if ch.status == ChannelStatus.验证 else "candidate"] += 1
    return stats


def _cst_today() -> str:
    return datetime.now(timezone(timedelta(hours=8))).date().isoformat()


def run(*, catalog_path: Path, pins: list[dict] | None = None,
        dry_run: bool = True, today: str | None = None) -> dict:
    pins = pinned_targets() if pins is None else pins
    today = today or _cst_today()
    path = Path(catalog_path)
    catalog = load_catalog(path) if path.exists() else []
    stats = apply_pins(catalog, pins=pins, today=today)
    if not dry_run:
        save_catalog(catalog, path)
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description="Apply curated list-page pins to the channel catalog.")
    ap.add_argument("--catalog", default=str(CAT))
    ap.add_argument("--apply", action="store_true", help="Persist changes. Default is dry-run.")
    ap.add_argument("--today", default=None, help="CST date for provenance notes, e.g. 2026-09-07")
    a = ap.parse_args()

    pins = pinned_targets()
    path = Path(a.catalog)
    catalog = load_catalog(path) if path.exists() else []
    before = {(c.city, c.channel_type): c.list_url for c in catalog}
    stats = apply_pins(catalog, pins=pins, today=a.today or _cst_today())

    for ch in catalog:
        key = (ch.city, ch.channel_type)
        if ch.source != "curated" or key not in {(p["city"], p["channel_type"]) for p in pins}:
            continue
        was = before.get(key, "(新增)")
        mark = "  " if was == ch.list_url else "→ "
        print(f"{mark}{ch.city}/{ch.channel_type}  probe={ch.probe_result}  status={ch.status.value}")
        if was != ch.list_url:
            print(f"     旧: {was}")
            print(f"     新: {ch.list_url}")

    if a.apply:
        save_catalog(catalog, path)
    mode = "apply" if a.apply else "dry-run"
    print(f"mode={mode} " + " ".join(f"{k}={v}" for k, v in stats.items()))


if __name__ == "__main__":
    main()
