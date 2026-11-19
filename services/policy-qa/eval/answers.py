"""答案评测:跑真模型,量化答题纪律。

**这个会花钱**(真 DeepSeek 调用),所以是手动步骤,不进 CI、不进 pytest。
检索层的评测在 retrieval.py,那个免费、确定性,已经进了 pytest 门禁。

子串匹配是粗的,而且刻意如此:这些纪律的失败表现都很具体——编一个文号、
把调价公告当重要政策、声称库里有其实没有的文件。粗匹配能挡住明显的回归;
标了 note 的用例必须人眼复核,报告里会提示。

用法:
    POLICY_QA_DATA_BACKEND=vault POLICY_QA_VAULT_DIR=... \\
    POLICY_QA_ACCESS_TOKEN=x DEEPSEEK_API_KEY=sk-... \\
    python eval/answers.py [用例id ...]
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

GOLDEN = Path(__file__).parent / "golden" / "disciplines.json"


def _check(case: dict, answer: str, cited: list[str]) -> list[tuple[bool, str]]:
    checks: list[tuple[bool, str]] = []
    for bad in case.get("must_not_mention", []):
        checks.append((bad not in answer, f"不得出现「{bad}」"))
    anyof = case.get("must_mention_any")
    if anyof:
        checks.append((any(x in answer for x in anyof), f"须提及其一: {anyof}"))
    for need in case.get("must_mention_all", []):
        checks.append((need in answer, f"须提及「{need}」"))
    expect = case.get("expect_cited_any")
    if expect:
        checks.append((bool(set(cited) & set(expect)), f"须引用其一: {expect}"))
    return checks


async def run_case(case: dict, store, agent, cfg, planner=None) -> dict:
    from app.agent import stream_answer

    parts: list[str] = []
    cited: list[str] = []
    unsupported: list[str] = []
    tools = 0
    async for name, data in stream_answer(
        agent,
        store=store,
        messages=[{"role": "user", "content": case["question"]}],
        cfg=cfg,
        planner=planner,
    ):
        if name == "delta":
            parts.append(data.get("text", ""))
        elif name == "tool" and data.get("status") == "start":
            tools += 1
        elif name == "done":
            cited = [c["pid"] for c in data.get("citations", [])]
        elif name == "verify":
            unsupported = [u["text"] for u in data.get("unsupported", [])]
        elif name == "error":
            return {"case": case, "error": data.get("message"), "answer": "", "cited": [], "checks": []}
    answer = "".join(parts)
    return {
        "case": case,
        "answer": answer,
        "cited": cited,
        "tools": tools,
        # 事实核验的命中要报出来:它是这套纪律的最后一道闸,
        # 评测时不看,等于白装。
        "unsupported": unsupported,
        "checks": _check(case, answer, cited),
    }


async def main_async(only: list[str]) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.agent import build_agent
    from app.config import load_config
    from app.planner import build_planner
    from app.main import build_model, build_store

    cfg = load_config()
    store = build_store(cfg)
    model = build_model(cfg)
    agent = build_agent(model)
    # 评测要走**生产同款路径**:生产开着规划器,评测不带就测不到真实行为
    planner = build_planner(model) if cfg.enable_planner else None
    print(f"规划器: {'开' if planner else '关'}\n")

    cases = json.loads(GOLDEN.read_text("utf-8"))["cases"]
    if only:
        cases = [c for c in cases if c["id"] in only]

    passed = failed = 0
    needs_eye = []
    for case in cases:
        print("=" * 78)
        print(f"[{case['id']}] {case['question']}")
        print(f"  理由: {case['why']}")
        res = await run_case(case, store, agent, cfg, planner)
        if res.get("error"):
            print(f"  !! 出错: {res['error']}")
            failed += 1
            continue
        for ok, label in res["checks"]:
            print(f"  {'PASS' if ok else 'FAIL'}  {label}")
            if ok:
                passed += 1
            else:
                failed += 1
        print(f"  引用: {res['cited']}  工具 {res['tools']} 次")
        if res["unsupported"]:
            print(f"  ⚠ 事实核验存疑: {res['unsupported']}")
        print("  ---- 回答 ----")
        print("  " + res["answer"].strip().replace("\n", "\n  ")[:1600])
        if case.get("note"):
            needs_eye.append((case["id"], case["note"]))

    print("=" * 78)
    print(f"断言: {passed} 通过 / {failed} 失败")
    if needs_eye:
        print("\n以下用例的子串断言只能粗筛,必须人眼复核:")
        for cid, note in needs_eye:
            print(f"  · {cid}: {note}")
    return 1 if failed else 0


def main() -> int:
    return asyncio.run(main_async(sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
