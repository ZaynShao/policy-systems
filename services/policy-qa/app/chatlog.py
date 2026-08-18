"""会话日志:每请求一行 jsonl。

会话**不落库**——服务端无状态,历史由客户端持有。这里只留一条可追溯的运行记录,
用于排查"某次回答为什么是那样"(调了哪些工具、引了哪些政策、花了多少 token)。

纪律:凭据(DSN / API key / 令牌)永不入日志。用户问题原文会落盘,因为排查
检索质量必须知道问的是什么;日志目录的访问控制由部署侧保证(PR-3)。
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_lock = threading.Lock()


class ChatLog:
    def __init__(self, log_dir: str):
        self.dir = Path(log_dir)
        self.enabled = True
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            # 日志写不了不能让问答挂掉
            self.enabled = False

    def write(self, record: dict[str, Any]) -> None:
        if not self.enabled:
            return
        now = datetime.now(timezone.utc).astimezone()
        record = {"ts": now.isoformat(), **record}
        path = self.dir / f"chat-{now:%Y%m%d}.jsonl"
        line = json.dumps(record, ensure_ascii=False, default=str)
        try:
            with _lock:
                with path.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
        except OSError:
            self.enabled = False
