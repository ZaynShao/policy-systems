"""跨条线机关渠道:pinned list_url 的注册、发现与目录修复。

背景(2026-09-07 实测):国家税务总局早已在 NATIONAL_TARGETS 里,但自动发现把
list_url 选成了栏目内的**单篇文章**(…/content.html),probe 判 structure_unknown
→ status 停在候选 → run_incremental._select_channels 只取「验证」→ 该渠道永不被扫。
国家能源局则更隐蔽:list_url 指向 2017 年冻结的旧栏目,probe 一直 ok,看起来健康
却零新增。两者同一病根——list_url 只能由自动发现产生,没有「人工核verified 后钉住」
的表达方式。本文件锁住 pin 机制。
"""
from __future__ import annotations

import pytest

from scripts.l1_collect.channel_catalog import Channel, ChannelStatus
from scripts.l1_collect.connectivity_probe import ProbeResult


# ── 注册表:跨条线机关必须带人工核过的 list_url ──────────────────────────

def test_cross_domain_targets_carry_pinned_list_url():
    """税务总局/央行/能源局 三条必须钉死 list_url,不能再交给 Tavily+LLM 猜。"""
    from scripts.l1_collect.channel_discovery import NATIONAL_TARGETS

    by_type = {t["channel_type"]: t for t in NATIONAL_TARGETS}
    for ctype in ("税务总局", "央行", "能源局"):
        assert by_type[ctype].get("list_url"), f"{ctype} 缺 pinned list_url"


def test_pinned_list_urls_are_not_articles_or_bare_homepages():
    """pin 的两种历史坏味道:单篇文章页 / 光秃秃的域名首页。"""
    from urllib.parse import urlparse

    from scripts.l1_collect.channel_discovery import NATIONAL_TARGETS

    for t in NATIONAL_TARGETS:
        url = t.get("list_url")
        if not url:
            continue
        assert not url.endswith("content.html"), f"{t['city']} pin 到了单篇文章:{url}"
        assert urlparse(url).path.strip("/"), f"{t['city']} pin 到了裸首页:{url}"


def test_pinned_targets_keep_national_region_convention():
    """非地理来源沿用既有约定:level/province=国家、city_code=000000、city=机关名。
    不新增 level 取值——ingester._infer_region 已按 city_code==000000 映射成
    region{level:国家, name:全国}。"""
    from scripts.l1_collect.channel_discovery import NATIONAL_TARGETS
    from scripts.l1_collect.ingester import _infer_region

    for t in NATIONAL_TARGETS:
        assert t["level"] == "国家"
        assert t["province"] == "国家"
        assert t["city_code"] == "000000"

    region = _infer_region(issuer=None, city="国家税务总局", city_code="000000")
    assert region == {"level": "国家", "code": "000000", "name": "全国"}


# ── discover_one:pin 命中时跳过搜索,直接探测 ────────────────────────────

def _pinned_target():
    return {
        "city": "国家税务总局", "province": "国家", "level": "国家",
        "city_code": "000000", "channel_type": "税务总局",
        "root_domain": "chinatax.gov.cn",
        "list_url": "https://fgk.chinatax.gov.cn/zcfgk/c100012/listflfg.html",
    }


def test_discover_one_uses_pin_without_search(monkeypatch):
    """有 pin → 不烧 Tavily/LLM,直接探 pin;probe ok → 验证。"""
    from scripts.l1_collect import channel_discovery as cd

    def _boom(*a, **k):
        raise AssertionError("pinned target 不该走搜索/LLM")

    monkeypatch.setattr(cd, "_tavily_search", _boom)
    monkeypatch.setattr(cd, "_llm_pick", _boom)
    monkeypatch.setattr(cd, "probe_url", lambda u, **k: ProbeResult(
        url=u, http_status=200, page_has_list_pattern=True,
        verdict="ok", probed_at="2026-09-07T10:00:00+08:00"))

    ch = cd.discover_one(_pinned_target())

    assert ch.list_url == _pinned_target()["list_url"]
    assert ch.root_domain == "chinatax.gov.cn"
    assert ch.status == ChannelStatus.验证
    assert ch.source == "curated"


def test_discover_one_pin_survives_probe_failure(monkeypatch):
    """probe 不 ok(如本地无 firecrawl key 渲染不了 JS 列表)→ 保留 pin,
    但状态压回候选,不冒充已验证。"""
    from scripts.l1_collect import channel_discovery as cd

    monkeypatch.setattr(cd, "probe_url", lambda u, **k: ProbeResult(
        url=u, http_status=200, page_has_list_pattern=False,
        verdict="structure_unknown", probed_at="2026-09-07T10:00:00+08:00"))

    ch = cd.discover_one(_pinned_target())

    assert ch.list_url == _pinned_target()["list_url"], "probe 失败不得丢弃 pin"
    assert ch.status == ChannelStatus.候选
    assert ch.probe_result == "structure_unknown"


# ── pin_channels:把 pin 落到既有 catalog(修复 + 新增) ──────────────────

def _catalog_row(**over):
    data = {
        "city": "国家税务总局", "province": "国家", "level": "国家",
        "city_code": "000000", "channel_type": "税务总局",
        "root_domain": "chinatax.gov.cn",
        "list_url": "https://fgk.chinatax.gov.cn/zcfgk/c100012/c5239280/content.html",
        "source": "discovery", "status": ChannelStatus.候选,
        "last_probed_at": "2026-06-15T00:00:00+08:00",
        "probe_result": "structure_unknown", "notes": "",
    }
    data.update(over)
    return Channel(**data)


@pytest.fixture
def _probe_ok(monkeypatch):
    from scripts.l1_collect import pin_channels as pc

    monkeypatch.setattr(pc, "probe_url", lambda u, **k: ProbeResult(
        url=u, http_status=200, page_has_list_pattern=True,
        verdict="ok", probed_at="2026-09-07T10:00:00+08:00"))
    return pc


def test_apply_pins_repairs_wrong_list_url(_probe_ok):
    """已存在但 list_url 是文章页 → 就地改写成 pin,并因 probe ok 升到验证。"""
    pc = _probe_ok
    row = _catalog_row()
    catalog = [row]
    pin = _pinned_target()

    stats = pc.apply_pins(catalog, pins=[pin], today="2026-09-07")

    assert row.list_url == pin["list_url"]
    assert row.status == ChannelStatus.验证
    assert row.source == "curated"
    assert stats["repaired"] == 1
    assert stats["added"] == 0


def test_apply_pins_appends_missing_channel(_probe_ok):
    """catalog 里没有该机关 → 新增一行。"""
    pc = _probe_ok
    catalog = []

    stats = pc.apply_pins(catalog, pins=[_pinned_target()], today="2026-09-07")

    assert len(catalog) == 1
    assert catalog[0].city == "国家税务总局"
    assert stats["added"] == 1


def test_apply_pins_is_idempotent(_probe_ok):
    """第二遍跑:URL 已一致 → 不重复计 repaired,notes 不重复追加。"""
    pc = _probe_ok
    row = _catalog_row()
    catalog = [row]
    pin = _pinned_target()

    pc.apply_pins(catalog, pins=[pin], today="2026-09-07")
    first_notes = row.notes
    stats = pc.apply_pins(catalog, pins=[pin], today="2026-09-07")

    assert stats["repaired"] == 0
    assert stats["unchanged"] == 1
    assert row.notes == first_notes


def test_apply_pins_matches_on_city_and_type_not_domain(_probe_ok):
    """能源局的 pin 换了子域(www.nea.gov.cn),仍应认出同一行、就地修,
    而不是新增一行重复渠道。"""
    pc = _probe_ok
    row = _catalog_row(
        city="国家能源局", channel_type="能源局", root_domain="nea.gov.cn",
        list_url="http://www.nea.gov.cn/zcfb", status=ChannelStatus.验证,
        probe_result="manual_verified_zcfb_34kw")
    catalog = [row]
    pin = {
        "city": "国家能源局", "province": "国家", "level": "国家",
        "city_code": "000000", "channel_type": "能源局",
        "root_domain": "nea.gov.cn",
        "list_url": "https://www.nea.gov.cn/policy/zxwj.htm",
    }

    stats = pc.apply_pins(catalog, pins=[pin], today="2026-09-07")

    assert len(catalog) == 1
    assert row.list_url == "https://www.nea.gov.cn/policy/zxwj.htm"
    assert stats["repaired"] == 1


def test_apply_pins_dry_run_does_not_write(tmp_path, _probe_ok):
    """默认 dry-run:不落盘。"""
    from scripts.l1_collect.channel_catalog import save_catalog

    pc = _probe_ok
    path = tmp_path / "channel_catalog.yaml"
    save_catalog([_catalog_row()], path)
    before = path.read_text(encoding="utf-8")

    pc.run(catalog_path=path, pins=[_pinned_target()],
           dry_run=True, today="2026-09-07")

    assert path.read_text(encoding="utf-8") == before


def test_apply_pins_writes_when_applied(tmp_path, _probe_ok):
    from scripts.l1_collect.channel_catalog import load_catalog, save_catalog

    pc = _probe_ok
    path = tmp_path / "channel_catalog.yaml"
    save_catalog([_catalog_row()], path)

    pc.run(catalog_path=path, pins=[_pinned_target()],
           dry_run=False, today="2026-09-07")

    reloaded = load_catalog(path)
    assert reloaded[0].list_url == _pinned_target()["list_url"]
    assert reloaded[0].status == ChannelStatus.验证


# ── reprobe 不得把人工 pin 改回去 ────────────────────────────────────────

def test_reprobe_keeps_pin_and_skips_discovery(monkeypatch):
    """firecrawl 抽风时 pin 会停在候选,下一轮 channel_reprobe 就会捞到它。
    彼时 reprobe 若照旧走 Tavily+LLM,人工修好的 URL 会被再次改坏——
    curated 行必须把 pin 透传给 discover_one。"""
    from scripts.l1_collect import channel_reprobe as cr
    from scripts.l1_collect import channel_discovery as cd

    pinned_url = "https://fgk.chinatax.gov.cn/zcfgk/c100012/listflfg.html"
    ch = _catalog_row(list_url=pinned_url, source="curated")

    def _boom(*a, **k):
        raise AssertionError("curated 行不该重新走搜索/LLM")

    monkeypatch.setattr(cd, "_tavily_search", _boom)
    monkeypatch.setattr(cd, "_llm_pick", _boom)
    monkeypatch.setattr(cd, "probe_url", lambda u, **k: ProbeResult(
        url=u, http_status=200, page_has_list_pattern=True,
        verdict="ok", probed_at="2026-09-07T10:00:00+08:00"))

    updated, outcome = cr.reprobe_candidate(ch, today="2026-09-07")

    assert updated.list_url == pinned_url
    assert outcome == "promoted"
