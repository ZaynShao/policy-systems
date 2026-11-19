"""policy_id 唯一性(SCHEMA §2「碰撞:加 _a _b 后缀」)。

生产实测(2026-09-07,1653 篇):21 个 id 各挂 2~10 份**不同 URL** 的文件,
compute_pid 只截文号尾数、且无任何唯一性兜底 → 撞了也静默写入。
"""
from __future__ import annotations
from pathlib import Path

from scripts.l1_collect.ingester import PidRegistry, ingest_one


def test_free_candidate_returned_unchanged():
    reg = PidRegistry()
    assert reg.reserve("P_2026_NDRC_884", identity="https://a.gov.cn/1") == "P_2026_NDRC_884"


def test_same_identity_is_idempotent():
    """同一文档重复入库 → 拿回同一个 id,不得每跑一次多吃一个后缀。"""
    reg = PidRegistry()
    first = reg.reserve("P_2026_NDRC_884", identity="https://a.gov.cn/1")
    again = reg.reserve("P_2026_NDRC_884", identity="https://a.gov.cn/1")
    assert first == again == "P_2026_NDRC_884"


def test_different_identity_gets_suffix_a():
    """生产实例:发改能源〔2026〕884号 同时挂成品油调价与新型能源体系规划两份不同文档。"""
    reg = PidRegistry()
    reg.reserve("P_2026_NDRC_884", identity="https://a.gov.cn/oil")
    assert reg.reserve("P_2026_NDRC_884", identity="https://a.gov.cn/plan") == "P_2026_NDRC_884_a"


def test_third_identity_gets_suffix_b():
    reg = PidRegistry()
    reg.reserve("P_2026_SX_FGW_1077", identity="u1")
    reg.reserve("P_2026_SX_FGW_1077", identity="u2")
    assert reg.reserve("P_2026_SX_FGW_1077", identity="u3") == "P_2026_SX_FGW_1077_b"


def test_suffix_sequence_continues_past_z():
    """江苏成品油 10 份共用一个 id;后缀序列必须能一直发下去,不能到 _z 就崩。"""
    reg = PidRegistry()
    got = [reg.reserve("P_2026_JS_FGW_10", identity=f"u{i}") for i in range(28)]
    assert got[0] == "P_2026_JS_FGW_10"
    assert got[1] == "P_2026_JS_FGW_10_a"
    assert got[26] == "P_2026_JS_FGW_10_z"
    assert got[27] == "P_2026_JS_FGW_10_aa"
    assert len(set(got)) == 28


def test_registry_loads_ids_already_in_vault(tmp_path: Path):
    """增量入库场景:vault 里已有该 id(属另一份文档)→ 新文档必须让号。"""
    (tmp_path / "老文件.md").write_text(
        "---\nid: P_2026_NDRC_884\naliases:\n  - P_2026_NDRC_884\n"
        "title: 关于印发《新型能源体系建设“十五五”规划》的通知\n"
        "provenance:\n  url: https://www.ndrc.gov.cn/plan\n---\n\n## 政策原文\n\n正文\n",
        encoding="utf-8")
    reg = PidRegistry.from_vault_policies(tmp_path)
    assert reg.reserve("P_2026_NDRC_884", identity="https://www.ndrc.gov.cn/oil") == "P_2026_NDRC_884_a"


def test_registry_reuses_id_for_same_url_already_in_vault(tmp_path: Path):
    """重跑同一 URL → 认出是同一份,拿回原 id(生产里 HL_FGW_a770e0cb 就是这种重复)。"""
    (tmp_path / "老文件.md").write_text(
        "---\nid: P_2026_NDRC_884\naliases:\n  - P_2026_NDRC_884\ntitle: 甲\n"
        "provenance:\n  url: https://www.ndrc.gov.cn/plan\n---\n\n## 政策原文\n\n正文\n",
        encoding="utf-8")
    reg = PidRegistry.from_vault_policies(tmp_path)
    assert reg.reserve("P_2026_NDRC_884", identity="https://www.ndrc.gov.cn/plan") == "P_2026_NDRC_884"


def test_registry_identity_ignores_tracking_params(tmp_path: Path):
    """URL 带 utm 等 tracking 参数不改变身份(复用 dedup 的归一口径)。"""
    reg = PidRegistry()
    a = reg.reserve("P_2026_NDRC_884", identity="https://a.gov.cn/x?utm_source=wx")
    b = reg.reserve("P_2026_NDRC_884", identity="https://a.gov.cn/x")
    assert a == b == "P_2026_NDRC_884"


def test_ingest_one_never_overwrites_an_existing_pid(tmp_path: Path):
    """端到端:两份不同文档同文号入库 → 落盘的 frontmatter id/aliases 必须已分家。"""
    import yaml
    common = dict(official_number="发改能源〔2026〕884号", date="2026-07-31",
                  issuer="国家发展和改革委员会", body="正文", out_dir=tmp_path)
    _, pid1 = ingest_one(url="https://www.ndrc.gov.cn/plan",
                         title="关于印发《新型能源体系建设“十五五”规划》的通知", **common)
    p2, pid2 = ingest_one(url="https://www.ndrc.gov.cn/oil",
                          title="2026年7月31日国内成品油价格调整", **common)
    assert pid1 != pid2, "两份不同文档不得共用一个 policy_id"
    fm = yaml.safe_load(p2.read_text(encoding="utf-8").split("---")[1])
    assert fm["id"] == pid2
    assert fm["aliases"] == [pid2], "aliases 必须跟着 id 走,否则 Obsidian 反链指向旧号"


def test_batch_ingest_shares_one_registry(tmp_path: Path, monkeypatch):
    """批量入库:同批内两份同文号文档也必须分号,且全批只扫一次目录。"""
    import json
    from scripts.l1_collect import ingester, step5_ingest

    in_dir = tmp_path / "in"; in_dir.mkdir()
    out_dir = tmp_path / "out"; out_dir.mkdir()
    for i, (u, t) in enumerate([
        ("https://www.ndrc.gov.cn/plan", "关于印发《新型能源体系建设“十五五”规划》的通知"),
        ("https://www.ndrc.gov.cn/oil", "2026年7月31日国内成品油价格调整"),
    ]):
        (in_dir / f"{i}.json").write_text(json.dumps({
            "url": u, "title": t, "official_number": "发改能源〔2026〕884号",
            "date": "2026-07-31", "issuer": "国家发展和改革委员会", "body": "正文",
        }, ensure_ascii=False), encoding="utf-8")

    calls = []
    orig = ingester.PidRegistry.from_vault_policies
    monkeypatch.setattr(ingester.PidRegistry, "from_vault_policies",
                        classmethod(lambda cls, d: calls.append(d) or orig(d)))

    ingested, failed, pids = step5_ingest.ingest_extracted(
        in_dir, tmp_path / "log.jsonl", out_dir=out_dir)
    assert (ingested, failed) == (2, 0)
    assert len(set(pids)) == 2, f"同批两份不同文档撞号: {pids}"
    assert len(calls) == 1, f"批量入库应只建一次 registry,实际 {len(calls)} 次"
