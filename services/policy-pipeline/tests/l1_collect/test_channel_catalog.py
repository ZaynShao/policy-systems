"""Tests for channel_catalog: data model + YAML IO."""
from __future__ import annotations
from pathlib import Path

from scripts.l1_collect.channel_catalog import (
    Channel, ChannelStatus, load_catalog, save_catalog,
)


def test_channel_required_fields():
    ch = Channel(
        city="杭州市", province="浙江省", level="市", city_code="330100",
        channel_type="发改委", root_domain="fgw.hangzhou.gov.cn",
        list_url="https://fgw.hangzhou.gov.cn/col/col1229453592/index.html",
        source="vault_catalog", status=ChannelStatus.候选,
    )
    assert ch.city == "杭州市"
    assert ch.status == ChannelStatus.候选


def test_channel_status_enum():
    assert {s.value for s in ChannelStatus} == {"候选", "验证", "已扫"}


def test_load_save_roundtrip(tmp_state_dir: Path, sample_catalog_yaml: str):
    p = tmp_state_dir / "T1_channels" / "channel_catalog.yaml"
    p.write_text(sample_catalog_yaml, encoding="utf-8")
    catalog = load_catalog(p)
    assert len(catalog) == 1
    assert catalog[0].city == "杭州市"
    assert catalog[0].status == ChannelStatus.验证
    out = tmp_state_dir / "T1_channels" / "out.yaml"
    save_catalog(catalog, out)
    catalog2 = load_catalog(out)
    assert catalog2[0].city == catalog[0].city


def test_save_preserves_field_order(tmp_state_dir: Path, sample_catalog_yaml: str):
    """YAML 输出字段顺序应固定,便于 diff。"""
    p = tmp_state_dir / "T1_channels" / "channel_catalog.yaml"
    p.write_text(sample_catalog_yaml, encoding="utf-8")
    catalog = load_catalog(p)
    out = tmp_state_dir / "out.yaml"
    save_catalog(catalog, out)
    text = out.read_text(encoding="utf-8")
    assert text.index("city:") < text.index("channel_type:")


def test_channel_label_区分同站不同栏目():
    """同一个部委站的两个栏目 city/type/domain 全一样,只有 list_url 不同。

    名字不带 list_url 的话,第二个栏目会把第一个的扫描结果覆盖掉,
    流水线还会对同一份数据跑两遍——《售电公司管理办法》所在的
    「发改委·意见征求」正是要和已在册的「发改委·通知公告」共存。
    """
    from scripts.l1_collect.channel_catalog import Channel, ChannelStatus, channel_label
    def mk(url):
        return Channel(city="国家发展和改革委员会", province="国家", level="国家",
                       city_code="000000", channel_type="发改委",
                       root_domain="ndrc.gov.cn", list_url=url,
                       source="manual", status=ChannelStatus.验证)
    a = channel_label(mk("https://www.ndrc.gov.cn/xwdt/tzgg"))
    b = channel_label(mk("https://www.ndrc.gov.cn/hdjl/yjzq/"))
    assert a != b
    assert channel_label(mk("https://www.ndrc.gov.cn/hdjl/yjzq/")) == b  # 稳定


def test_目录里所有渠道的_label_互不相同():
    """加栏目时最容易踩的坑,用全量目录钉住。"""
    from pathlib import Path
    from scripts.l1_collect.channel_catalog import load_catalog, channel_label
    cat = load_catalog(Path(__file__).resolve().parents[2]
                       / "state" / "T1_channels" / "channel_catalog.yaml")
    labels = [channel_label(c) for c in cat]
    assert len(set(labels)) == len(labels)


def test_目录含发改委意见征求栏目():
    """《售电公司管理办法(公开征求意见稿)》2026-09-04 挂在这个栏目;
    此前只收「通知公告」,征求意见稿整条不进库。"""
    from pathlib import Path
    from scripts.l1_collect.channel_catalog import load_catalog, ChannelStatus
    cat = load_catalog(Path(__file__).resolve().parents[2]
                       / "state" / "T1_channels" / "channel_catalog.yaml")
    yjzq = [c for c in cat if "hdjl/yjzq" in c.list_url]
    assert yjzq, "发改委意见征求栏目不在目录里"
    assert all(c.status == ChannelStatus.验证 for c in yjzq)
