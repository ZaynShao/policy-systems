from pathlib import Path
from scripts.service.hash_ledger import LedgerEntry, compute_hash
import json

from scripts.service.l2_queue import QueueItem, enqueue
from scripts.service.orchestrate import StageResult, process_pid, drain_queue

def test_process_pid_skips_when_unchanged():
    ledger = {"P_X": LedgerEntry("P_X", compute_hash("same"), 1)}
    calls = []
    res = process_pid("P_X", "same", version=1, ledger=ledger,
                      run_attribution=lambda pid: calls.append(pid))
    assert res.ok is True
    assert res.error == "skipped"
    assert calls == []  # 未变 → 不调归属

def test_process_pid_runs_when_changed():
    ledger = {}
    calls = []
    res = process_pid("P_X", "new", version=1, ledger=ledger,
                      run_attribution=lambda pid: calls.append(pid))
    assert res.ok is True
    assert calls == ["P_X"]
    assert "P_X" in ledger  # mark_done 已更新账本

def test_process_pid_records_error():
    def boom(pid):
        raise RuntimeError("llm failed")
    res = process_pid("P_X", "txt", version=1, ledger={},
                      run_attribution=boom)
    assert res.ok is False
    assert "llm failed" in res.error

def test_drain_queue_processes_high_first(tmp_path):
    q = tmp_path / "q.jsonl"
    enqueue(q, QueueItem("P_A", "cron", "normal", "t1"))
    enqueue(q, QueueItem("P_B", "manual", "high", "t2"))
    order = []
    sync_calls = []
    drain_queue(
        queue_path=q,
        ledger={},
        ledger_path=tmp_path / "ledger.json",
        raw_text_for=lambda pid: pid + "_txt",
        version=1,
        run_attribution=lambda pid: order.append(pid),
        run_sync=lambda: sync_calls.append("synced"),
    )
    assert order[0] == "P_B"   # high 先
    assert order == ["P_B", "P_A"]
    assert sync_calls == ["synced"]   # 队列排空后触发一次 sync

def test_drain_queue_empty_no_sync(tmp_path):
    q = tmp_path / "q.jsonl"
    sync_calls = []
    drain_queue(queue_path=q, ledger={}, ledger_path=tmp_path / "l.json",
                raw_text_for=lambda pid: "", version=1,
                run_attribution=lambda pid: None,
                run_sync=lambda: sync_calls.append("x"))
    assert sync_calls == []  # 空队列不触发 sync


def test_drain_queue_missing_raw_does_not_block(tmp_path):
    """drain 防卡死: 第一条 raw_text_for 抛 KeyError，标错误出队，第二条正常处理，队列最终为空。"""
    q = tmp_path / "q.jsonl"
    enqueue(q, QueueItem("P_MISSING", "cron", "normal", "t1"))
    enqueue(q, QueueItem("P_OK", "cron", "normal", "t2"))

    processed = []

    def raw_text_for(pid: str) -> str:
        if pid == "P_MISSING":
            raise KeyError(f"raw not found: {pid}")
        return pid + "_txt"

    results = drain_queue(
        queue_path=q,
        ledger={},
        ledger_path=tmp_path / "ledger.json",
        raw_text_for=raw_text_for,
        version=1,
        run_attribution=lambda pid: processed.append(pid),
        run_sync=lambda: None,
    )

    # P_MISSING: StageResult ok=False, error 含 raw_missing
    missing_res = next(r for r in results if r.pid == "P_MISSING")
    assert missing_res.ok is False
    assert "raw_missing" in missing_res.error

    # P_OK: 正常处理
    ok_res = next(r for r in results if r.pid == "P_OK")
    assert ok_res.ok is True
    assert "P_OK" in processed

    # 队列最终为空
    from scripts.service.l2_queue import read_queue
    assert read_queue(q) == []
    dead_rows = [
        json.loads(line)
        for line in (tmp_path / "l2_failures.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert dead_rows[0]["pid"] == "P_MISSING"
    assert "raw_missing" in dead_rows[0]["error"]


def test_drain_failed_pid_to_dead_letter_and_dequeued(tmp_path):
    """run_attribution 抛错的 pid → ① 进 l2_failures.jsonl ② 出主队 ③ 不进 ledger。"""
    q = tmp_path / "q.jsonl"
    ledger_path = tmp_path / "ledger.json"
    ledger = {}
    enqueue(q, QueueItem("P_FAIL", "cron", "normal", "t1"))

    def boom(pid: str) -> None:
        raise RuntimeError("llm failed")

    results = drain_queue(
        queue_path=q,
        ledger=ledger,
        ledger_path=ledger_path,
        raw_text_for=lambda pid: "RAW",
        version=1,
        run_attribution=boom,
        run_sync=lambda: None,
    )

    assert results == [StageResult("P_FAIL", False, "llm failed")]
    from scripts.service.l2_queue import next_item
    assert next_item(q) is None
    dead_rows = [
        json.loads(line)
        for line in (tmp_path / "l2_failures.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert dead_rows[0]["pid"] == "P_FAIL"
    assert "llm failed" in dead_rows[0]["error"]
    assert "P_FAIL" not in ledger
    assert not ledger_path.exists()


def test_process_pid_fails_when_归属跑完但没有产出():
    """退出码 0 不等于写出了 business_view。

    2026-09-07 实测:run_2b 判官打回 / 程序门拦下 / 模型少字段时都返回 0,
    于是 51 篇政策被盖章"已完成"、永不重跑、且从不进死信。盖章前必须验收产出。
    """
    ledger = {}
    res = process_pid("P_X", "txt", version=1, ledger=ledger,
                      run_attribution=lambda pid: None,
                      verify_output=lambda pid: False)
    assert res.ok is False
    assert res.error.startswith("no_output")
    assert "P_X" not in ledger  # 账本没盖章 → 下次还会重跑


def test_process_pid_marks_done_when_产出验收通过():
    ledger = {}
    res = process_pid("P_X", "txt", version=1, ledger=ledger,
                      run_attribution=lambda pid: None,
                      verify_output=lambda pid: True)
    assert res.ok is True
    assert "P_X" in ledger


def test_drain_queue_没产出的进死信让周日重排能捡回来(tmp_path):
    """闭环:没产出 → 死信 → deadletter_sweep 每周重排 → 重跑。

    死信这条链路早就建好了(alert 每天看、sweep 每周排),但在验收产出之前
    从没有东西进得去,整套机制空转了三个月。
    """
    q = tmp_path / "q.jsonl"
    enqueue(q, QueueItem("P_A", "cron", "normal", "t1"))
    results = drain_queue(
        queue_path=q, ledger={}, ledger_path=tmp_path / "l.json",
        raw_text_for=lambda pid: "raw",
        version=1,
        run_attribution=lambda pid: None,
        run_sync=lambda: None,
        verify_output=lambda pid: False,
    )
    assert results[0].ok is False
    dead = tmp_path / "l2_failures.jsonl"
    assert dead.exists()
    rec = json.loads(dead.read_text(encoding="utf-8").splitlines()[0])
    assert rec["pid"] == "P_A"
    assert "no_output" in rec["error"]
    assert Path(q).read_text(encoding="utf-8").strip() == ""  # 已出队,不阻塞后续
