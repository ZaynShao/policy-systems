"""检索评测的回归门禁。

不调模型,所以能进 pytest 常规跑。这里用 mini-vault 验 harness 本身正确;
对真实 vault 的召回率由 `python eval/retrieval.py <vault>` 手动跑
(需要本机 vault 克隆,CI 上没有)。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval import retrieval  # noqa: E402

GOLDEN = Path(__file__).resolve().parents[1] / "eval" / "golden" / "2026-07-monthly.json"


def test_golden_file_is_wellformed():
    data = json.loads(GOLDEN.read_text("utf-8"))
    assert data["window"]["date_from"] < data["window"]["date_to"]
    assert len(data["items"]) >= 14
    for item in data["items"]:
        assert item["pids"], f"{item['key']} 没有可断言的 pid"
        assert all(p.startswith("P_") for p in item["pids"])
    # 反向用例:月刊收录但库内确实没有的件,用来验"不编造"
    assert data["absent"], "缺少反向用例"


def test_strategies_cover_known_traps():
    """策略集必须包含针对两个已知盲区的姿势,否则评测会给出虚高的召回率。"""
    names = [n for n, _ in retrieval.STRATEGIES]
    assert any("机关" in n for n in names), "缺跨条线机关扫描(治打分失准)"
    assert retrieval.WIDENED_DAYS >= 30, "放宽窗口的幅度要够(治成文日/发布日漂移)"


def test_harness_runs_on_mini_vault(vault_store, tmp_path):
    """用 mini-vault 造一份微型 golden,验 harness 的命中/未命中判定都正确。"""
    golden = {
        "window": {"date_from": "2026-01-01", "date_to": "2026-12-31"},
        "items": [
            {"key": "存在的件", "editor_score": 5, "pids": ["P_2026_TEST_1"]},
            {"key": "不存在的件", "editor_score": 3, "pids": ["P_2099_NOPE"],
             "known_trap": "构造的未命中"},
        ],
        "absent": [{"key": "x"}],
    }
    path = tmp_path / "mini.json"
    path.write_text(json.dumps(golden, ensure_ascii=False), encoding="utf-8")

    report = retrieval.run(vault_store, path)
    assert report["total"] == 2
    assert report["hit"] == 1
    assert report["recall"] == 0.5
    by_key = {r.key: r for r in report["items"]}
    assert by_key["存在的件"].found and by_key["存在的件"].found_by
    assert not by_key["不存在的件"].found

    text = retrieval.format_report(report)
    assert "1/2" in text and "构造的未命中" in text
