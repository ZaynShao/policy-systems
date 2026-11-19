def test_targets_for_levels_merges_province_energy_without_losing_known_domain(monkeypatch):
    from scripts._oneshot import expand_channels_l1 as mod

    registry_target = {
        "city": "山东省",
        "province": "山东省",
        "level": "省",
        "city_code": "370000",
        "channel_type": "能源局",
        "root_domain": "nyj.shandong.gov.cn",
    }
    energy_targets = [
        {
            "city": "山东省",
            "province": "山东省",
            "level": "省",
            "city_code": "370000",
            "channel_type": "能源局",
            "root_domain": None,
        },
        {
            "city": "山东省",
            "province": "山东省",
            "level": "省",
            "city_code": "370000",
            "channel_type": "发改委",
            "root_domain": None,
        },
    ]
    monkeypatch.setattr(mod, "province_targets_from_registry", lambda reg: [registry_target])
    monkeypatch.setattr(mod, "province_energy_targets", lambda: energy_targets)
    monkeypatch.setattr(mod, "nea_regulatory_targets", lambda: [{"city": "国家能源局华北能源监管局"}])

    targets = mod.targets_for_levels(["province", "nea_regulatory"])

    by_key = {(t["province"], t["channel_type"]): t for t in targets if "province" in t}
    assert by_key[("山东省", "能源局")]["root_domain"] == "nyj.shandong.gov.cn"
    assert by_key[("山东省", "发改委")]["root_domain"] is None
    assert {"city": "国家能源局华北能源监管局"} in targets


def test_targets_for_levels_merges_province_industry_without_losing_known_domain(monkeypatch):
    from scripts._oneshot import expand_channels_l1 as mod

    registry_target = {
        "city": "江苏省",
        "province": "江苏省",
        "level": "省",
        "city_code": "320000",
        "channel_type": "工信",
        "root_domain": "gxt.jiangsu.gov.cn",
    }
    industry_targets = [
        {
            "city": "江苏省",
            "province": "江苏省",
            "level": "省",
            "city_code": "320000",
            "channel_type": "工信",
            "root_domain": None,
            "search_name": "江苏省工业和信息化厅 工信厅",
        },
        {
            "city": "浙江省",
            "province": "浙江省",
            "level": "省",
            "city_code": "330000",
            "channel_type": "工信",
            "root_domain": None,
            "search_name": "浙江省经济和信息化厅 经信厅",
        },
    ]
    monkeypatch.setattr(mod, "province_targets_from_registry", lambda reg: [registry_target])
    monkeypatch.setattr(mod, "province_industry_targets", lambda: industry_targets)

    targets = mod.targets_for_levels(["industry"])

    by_key = {(t["province"], t["channel_type"]): t for t in targets}
    assert by_key[("江苏省", "工信")]["root_domain"] == "gxt.jiangsu.gov.cn"
    assert by_key[("浙江省", "工信")]["root_domain"] is None
    assert by_key[("浙江省", "工信")]["search_name"] == "浙江省经济和信息化厅 经信厅"
