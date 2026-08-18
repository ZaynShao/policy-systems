"""检索评测:golden 选目能不能被检索层捞到。**不调模型**,零成本、确定性。

问的问题是"检索层有没有能力把该看的政策摆到模型面前"——模型再聪明,
检索不出来就无从谈起。所以这一层单独量化,而且因为不花钱,可以进 pytest
当回归门禁(见 tests/test_eval_retrieval.py)。

答案质量是另一回事,在 answers.py,那个要花钱。
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

GOLDEN_DIR = Path(__file__).parent / "golden"

#: 一个称职的分析师会用的几种检索姿势。评测衡量的是「这组姿势合起来能覆盖多少选目」,
#: 而不是「某一条 query 有多神」——真实使用里模型本来就会多轮检索。
STRATEGIES: list[tuple[str, dict]] = [
    ("按日期倒序", {"order": "date_desc"}),
    ("按重要性", {"order": "importance_desc"}),
    ("重要性≥MAJOR", {"min_importance": "MAJOR", "order": "importance_desc"}),
    ("业务线=电力", {"business_line": "电力", "order": "importance_desc"}),
    ("业务线=充电", {"business_line": "充电", "order": "importance_desc"}),
    ("业务线=加油", {"business_line": "加油", "order": "importance_desc"}),
    # 跨条线机关(财税/市场监管)发的能源政策是已知的打分盲区:D1 常被打 1-2 分,
    # 按重要性排序会沉到底。月刊的做法是按机关单独扫一遍,这里照搬。
    ("机关=税务总局", {"issuer_keyword": "税务总局", "order": "date_desc"}),
    ("机关=财政部", {"issuer_keyword": "财政部", "order": "date_desc"}),
]

#: 放宽日期窗口的姿势。单独列出来是因为它专治「成文日 vs 发布日」漂移:
#: 库里的 date 可能比月刊记的发布日早半个月,掐死窗口会漏掉重要文件。
WIDENED_DAYS = 30


@dataclass
class ItemResult:
    key: str
    found_by: list[str]
    editor_score: int | None
    known_trap: str | None

    @property
    def found(self) -> bool:
        return bool(self.found_by)


def _shift(date_str: str, days: int) -> str:
    import datetime

    y, m, d = (int(x) for x in date_str.split("-"))
    return (datetime.date(y, m, d) + datetime.timedelta(days=days)).isoformat()


def run(store, golden_path: Path | None = None, *, limit: int = 50) -> dict:
    data = json.loads((golden_path or GOLDEN_DIR / "2026-07-monthly.json").read_text("utf-8"))
    win = data["window"]
    strategies = list(STRATEGIES)
    strategies.append(
        (
            f"放宽窗口±{WIDENED_DAYS}天·按重要性",
            {
                "order": "importance_desc",
                "_date_from": _shift(win["date_from"], -WIDENED_DAYS),
                "_date_to": _shift(win["date_to"], WIDENED_DAYS),
            },
        )
    )

    # 每种姿势先跑一次,拿到它捞回的 pid 集合
    caught: dict[str, set[str]] = {}
    for name, params in strategies:
        params = dict(params)
        date_from = params.pop("_date_from", win["date_from"])
        date_to = params.pop("_date_to", win["date_to"])
        res = store.search_policies(date_from=date_from, date_to=date_to, limit=limit, **params)
        caught[name] = {c.pid for c in res.rows}

    results: list[ItemResult] = []
    for item in data["items"]:
        pids = set(item["pids"])
        found_by = [name for name, got in caught.items() if got & pids]
        results.append(
            ItemResult(
                key=item["key"],
                found_by=found_by,
                editor_score=item.get("editor_score"),
                known_trap=item.get("known_trap"),
            )
        )

    hit = sum(1 for r in results if r.found)
    return {
        "total": len(results),
        "hit": hit,
        "recall": round(hit / len(results), 3) if results else 0.0,
        "items": results,
        "per_strategy": {name: len(got) for name, got in caught.items()},
    }


def format_report(report: dict) -> str:
    lines = [
        f"检索召回: {report['hit']}/{report['total']}  ({report['recall']:.0%})",
        "",
    ]
    for r in report["items"]:
        mark = "✓" if r.found else "✗"
        score = f"[{r.editor_score}分]" if r.editor_score else "[地方]"
        lines.append(f"  {mark} {score:<6} {r.key}")
        if r.found:
            lines.append(f"        经由: {'、'.join(r.found_by)}")
        elif r.known_trap:
            lines.append(f"        已知坑: {r.known_trap}")
    lines.append("")
    lines.append("各姿势捞回量: " + ", ".join(f"{k}={v}" for k, v in report["per_strategy"].items()))
    return "\n".join(lines)


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.store.vault import VaultStore

    if len(sys.argv) < 2:
        print("用法: python eval/retrieval.py <vault 路径>")
        return 2
    report = run(VaultStore(sys.argv[1]))
    print(format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
