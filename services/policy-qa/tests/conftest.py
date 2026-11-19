"""测试夹具:手造一个 mini-vault,覆盖真实库里的各类边界。

刻意包含的坑(全部来自真实 vault 实测):
  - issuer 是数组(实测 400/400 都是数组,不是字符串)
  - 缺 business_view 的政策(不能因此丢政策,只是没有内部评估)
  - 正文编码损伤(原样保留,不在消费端修)
  - 同一 pid 对应多份文件(全库 14 组;pg 按 pid upsert 只存得下一份)
  - date 缺失(不收,与 pipeline 一致:不写假数据)
  - _archive/ 下的政策(不可见)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _policy_md(
    *,
    pid: str,
    title: str,
    date: str | None,
    issuer: list[str],
    level: str = "国家",
    code: str = "000000",
    region_name: str = "全国",
    official_number: str = "",
    url: str = "https://example.gov.cn/doc",
    body: str = "正文内容。",
) -> str:
    date_line = f"date: '{date}'\n" if date else ""
    issuer_block = "issuer: []\n"
    if issuer:
        issuer_block = "issuer:\n" + "".join(f"- {x}\n" for x in issuer)
    return (
        "---\n"
        f"id: {pid}\n"
        f"aliases:\n- {pid}\n"
        f"title: {title}\n"
        f"official_number: '{official_number}'\n"
        f"{issuer_block}"
        f"{date_line}"
        "region:\n"
        f"  level: {level}\n"
        f"  code: '{code}'\n"
        f"  name: {region_name}\n"
        "provenance:\n"
        f"  url: {url}\n"
        "  source_type: A\n"
        "  fetched_via: firecrawl\n"
        "type: policy\n"
        "---\n\n"
        "## 政策原文\n\n"
        f"{body}\n"
    )


def _bv_yaml(
    *,
    pid: str,
    importance: int,
    themes: list[str],
    scores: dict[str, int],
    impact: dict[str, str] | None = None,
) -> str:
    out = [f"pid: {pid}", "themes:"]
    out += [f"- {t}" for t in themes] if themes else ["themes: []"]
    if themes:
        pass
    else:
        out = [f"pid: {pid}", "themes: []"]
    out.append("scores:")
    for k, v in scores.items():
        out.append(f"  {k}: {v}")
    out.append(f"重要性: {importance}")
    if impact:
        out.append("影响分析:")
        for k, v in impact.items():
            out.append(f"  {k}: {v}")
    out.append(f"sanitized_from: 0_raw/policies/{pid}.md")
    out.append("extracted_by: scripts/l2_themescore/run_2b.py")
    return "\n".join(out) + "\n"


#: 撞车组的胜出者:日期最新那篇(确定性规则,见 vault.py)
COLLISION_PID = "P_2026_TEST_DUP"
COLLISION_WINNER_TITLE = "撞车公告第二号"


@pytest.fixture
def mini_vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    pol = root / "0_raw" / "policies"

    # 1) 完整件:国家级、高分、有充电与电力影响
    _write(
        pol / "充电基础设施建设通知.md",
        _policy_md(
            pid="P_2026_TEST_1",
            title="关于加快充电基础设施建设的通知",
            date="2026-07-15",
            issuer=["国家发展改革委", "国家能源局"],
            official_number="发改能源〔2026〕1号",
            body="各省应于2026年底前建成充电桩10万个。本通知自发布之日起施行。",
        ),
    )
    # 2) 缺 business_view:省级、无文号
    _write(
        pol / "江苏省成品油价格调整公告.md",
        _policy_md(
            pid="P_2026_TEST_2",
            title="江苏省成品油价格调整公告",
            date="2026-06-01",
            issuer=["江苏省发展改革委"],
            level="省",
            code="320000",
            region_name="江苏省",
            body="汽油价格每吨提高200元。",
        ),
    )
    # 3) 中分件:只有电力影响
    _write(
        pol / "储能示范项目通知.md",
        _policy_md(
            pid="P_2026_TEST_3",
            title="关于开展新型储能示范项目的通知",
            date="2026-05-01",
            issuer=["国家能源局"],
            official_number="国能发〔2026〕88号",
            body="支持电网侧储能建设。",
        ),
    )
    # 4) 正文编码损伤:原样保留,不修
    _write(
        pol / "乱码件.md",
        _policy_md(
            pid="P_2026_TEST_GARBLE",
            title="å…³äºŽç”µåŠ›å¸‚åœºçš„é€šçŸ¥",
            date="2026-04-01",
            issuer=["某部门"],
            body="æ­¤å¤„ä¸ºä¹±ç å†…å®¹ã€‚",
        ),
    )
    # 5) 撞车组:同一 pid 两份不同文件,只应留下日期最新的一份
    _write(
        pol / "撞车公告一.md",
        _policy_md(
            pid=COLLISION_PID,
            title="撞车公告第一号",
            date="2026-03-01",
            issuer=["某省发改委"],
            official_number="发改电〔2015〕10号",
            body="第一号正文。",
        ),
    )
    _write(
        pol / "撞车公告二.md",
        _policy_md(
            pid=COLLISION_PID,
            title=COLLISION_WINNER_TITLE,
            date="2026-03-15",
            issuer=["某省发改委"],
            official_number="发改电〔2015〕10号",
            body="第二号正文。",
        ),
    )
    # 6) 缺 date:不收
    _write(
        pol / "无日期件.md",
        _policy_md(
            pid="P_1900_TEST_NODATE",
            title="日期真空件",
            date=None,
            issuer=["某部门"],
        ),
    )
    # 7) archive 下的件:不可见
    _write(
        root / "0_raw" / "_archive" / "policies" / "已归档件.md",
        _policy_md(
            pid="P_2026_TEST_ARCHIVED",
            title="已归档的政策",
            date="2026-02-01",
            issuer=["某部门"],
        ),
    )

    bv = root / "_meta" / "business_view"
    _write(
        bv / "P_2026_TEST_1.yaml",
        _bv_yaml(
            pid="P_2026_TEST_1",
            importance=5,
            themes=["charging_infra", "power_market"],
            scores={"D1": 5, "D2": 5, "D3": 5, "D4": 4, "D5": 4, "D6": 5},
            impact={
                "充电": "直接利好充电桩布局,建议尽早对接省级实施细则。",
                "电力_储能_V2G_交易": "配套增容需求带动电力侧机会。",
            },
        ),
    )
    _write(
        bv / "P_2026_TEST_3.yaml",
        _bv_yaml(
            pid="P_2026_TEST_3",
            importance=4,
            themes=["energy_storage_theme"],
            scores={"D1": 4, "D2": 4, "D3": 4, "D4": 3, "D5": 3, "D6": 4},
            impact={
                "电力_储能_V2G_交易": "储能示范项目带来参与机会。",
                # 库内约定:不相关的业务线也会写一句,而不是留空(全库 64% 如此)
                "充电": "未直接涉及。正文未提及充电设施。",
            },
        ),
    )
    _write(
        bv / f"{COLLISION_PID}.yaml",
        _bv_yaml(
            pid=COLLISION_PID,
            importance=1,
            themes=[],
            scores={"D1": 0, "D2": 1, "D3": 1, "D4": 1, "D5": 0, "D6": 0},
        ),
    )

    rel = root / "1_extracted" / "relations"
    lines = [
        {
            "from": "P_2026_TEST_1",
            "to": "P_2026_TEST_3",
            "rel": "supersedes",
            "confidence": 0.95,
            "evidence": "本通知施行后,原储能示范项目通知同时废止。",
        },
        {
            "from": "P_2026_TEST_2",
            "to": "P_2026_TEST_1",
            "rel": "references",
            "confidence": 0.8,
            "evidence": "依据发改能源〔2026〕1号执行。",
        },
        # 重复行:去重后只算一条
        {
            "from": "P_2026_TEST_1",
            "to": "P_2026_TEST_3",
            "rel": "supersedes",
            "confidence": 0.95,
            "evidence": "重复记录。",
        },
        # 悬挂 to:目标不在库,仍应作为出向边返回
        {
            "from": "P_2026_TEST_1",
            "to": "P_2099_NOT_EXIST",
            "rel": "references",
            "confidence": 0.5,
            "evidence": "指向库外文件。",
        },
    ]
    _write(
        rel / "relations_canonical.jsonl",
        "\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n",
    )

    sigs = [
        {
            "commentary_id": "C_test0001",
            "title": "充电桩新政解读",
            "related_policy_ids": ["P_2026_TEST_1"],
            "signal_role": "opportunity",
            "confidence": 0.72,
            "evidence": "行业普遍认为该政策利好运营商。",
            "source_account": "某行业媒体",
            "business_tag": "charging",
        },
        {
            "commentary_id": "C_test0002",
            "title": "悬挂引用评论",
            "related_policy_ids": ["P_2099_NOT_EXIST"],
            "signal_role": "noise",
            "confidence": 0.3,
            "evidence": "指向库外政策。",
            "source_account": "某号",
            "business_tag": "cross",
        },
    ]
    _write(
        root / "1_extracted" / "commentary_signals.jsonl",
        "\n".join(json.dumps(x, ensure_ascii=False) for x in sigs) + "\n",
    )

    return root


@pytest.fixture
def vault_store(mini_vault: Path):
    from app.store.vault import VaultStore

    return VaultStore(mini_vault)
