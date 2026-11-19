import json
from datetime import datetime, timezone
from pathlib import Path

def write_queue(records, out_path: str, append: bool = False) -> int:
    """records: list[QueueRecord]. 一条一行 JSONL,带 ts。返回条数。

    append 的存在理由:生产上 run_2b apply 是**逐篇**被 orchestrate 调起的,覆盖写
    等于每篇政策都把上一篇的退件记录冲掉——真出事时现场只剩最后一篇,而最后一篇
    通常是成功的(退件列表为空),于是文件看着永远干净。2026-09-07 查 51 篇静默丢件
    时就卡在这:知道被退了,查不到退件理由。批量 dry-run 仍用覆盖,那要的是本轮全貌。
    """
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()
    with Path(out_path).open("a" if append else "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps({"ts": ts, **r.to_dict()}, ensure_ascii=False) + "\n")
    return len(records)
