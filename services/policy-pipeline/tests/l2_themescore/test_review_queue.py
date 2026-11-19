import json
from pathlib import Path
from scripts.l2_themescore.models import QueueRecord
from scripts.l2_themescore.review_queue import write_queue

def test_write_queue(tmp_path):
    out = tmp_path/"q.jsonl"
    n = write_queue([QueueRecord(pid="P1", stage="program_gate", reason="registry:未知 theme",
                                 detail={"bad":["x"]})], str(out))
    assert n == 1
    rows = [json.loads(l) for l in Path(out).read_text(encoding="utf-8").splitlines()]
    assert rows[0]["pid"] == "P1" and rows[0]["stage"] == "program_gate"


def test_write_queue_append_keeps_earlier_rejections(tmp_path):
    """生产上 apply 是逐篇调起的,覆盖写会让退件现场只剩最后一篇。"""
    out = tmp_path / "q.jsonl"
    write_queue([QueueRecord(pid="P1", stage="generation_error", reason="'scores'")],
                str(out), append=True)
    write_queue([QueueRecord(pid="P2", stage="judge_reject", reason="D1 过高")],
                str(out), append=True)
    rows = [json.loads(l) for l in Path(out).read_text(encoding="utf-8").splitlines()]
    assert [r["pid"] for r in rows] == ["P1", "P2"]
    assert all(r["ts"] for r in rows)  # 带时间戳才能事后对上是哪一轮退的


def test_write_queue_default_still_overwrites(tmp_path):
    """批量 dry-run 要的是本轮全貌,默认仍覆盖。"""
    out = tmp_path / "q.jsonl"
    write_queue([QueueRecord(pid="P1", stage="x", reason="y")], str(out))
    write_queue([QueueRecord(pid="P2", stage="x", reason="y")], str(out))
    rows = Path(out).read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1 and json.loads(rows[0])["pid"] == "P2"
