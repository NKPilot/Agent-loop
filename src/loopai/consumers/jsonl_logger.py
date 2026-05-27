"""JSONL 会话事件日志记录器。

作为 Event Bus 消费者运行，将每个事件作为一行 JSON 写入磁盘。
每个会话使用独立的文件，仅追加写入，每次事件后 flush 以确保崩溃恢复。
"""

from __future__ import annotations

import asyncio
import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path

from loopai.events.bus import EventBus


class JSONLLogger:
    """将 Event Bus 事件写入磁盘的消费者。

    按 D-10: 1:1 事件到行映射。
    按 D-11: 文件命名 YYYY-MM-DD_{session_id}.jsonl。
    权限: 文件 0o600，目录 0o700。
    每次写入后 flush，stop 时 fsync。

    Attributes:
        session_id: 此日志记录器所属的会话 ID。
        log_dir: 日志目录路径。
        filepath: 此会话日志文件的完整路径。
        _seq: 单调递增的事件序列号。
    """

    def __init__(self, session_id: str, log_dir: str = "logs/sessions") -> None:
        self.session_id = session_id
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.log_dir, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)  # 0o700

        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.filepath = self.log_dir / f"{date_str}_{session_id}.jsonl"

        self._file = open(self.filepath, "a", encoding="utf-8")
        os.chmod(self.filepath, stat.S_IRUSR | stat.S_IWUSR)  # 0o600

        self._seq = 0
        self._queue: asyncio.Queue[dict | None] | None = None
        self._task: asyncio.Task[None] | None = None

    async def start(self, bus: EventBus) -> asyncio.Task[None]:
        """订阅 Event Bus 并启动消费任务。

        Args:
            bus: 要订阅的 EventBus 实例。

        Returns:
            正在运行的消费任务的 asyncio.Task 引用。
        """
        self._queue = await bus.subscribe("*")
        self._task = asyncio.create_task(self._consume())
        return self._task

    async def _consume(self) -> None:
        """消费循环: 从队列中处理所有事件直到接收到 None 哨兵。"""
        if self._queue is None:
            return

        while True:
            event = await self._queue.get()
            if event is None:  # 关闭哨兵
                break
            await self._write(event)
            self._queue.task_done()

    async def _write(self, event: dict) -> None:
        """将单个事件序列化为 JSON 行并写入磁盘。

        条目包含 seq、ts、session_id 以及事件的所有字段。
        每次写入后立即 flush 以确保崩溃恢复。

        Args:
            event: 要写入的事件字典。
        """
        entry = {
            "seq": self._seq,
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            **event,
        }
        self._seq += 1
        self._file.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._file.flush()

    async def stop(self) -> None:
        """优雅关闭: fsync 将缓冲数据强制落盘后关闭文件。"""
        if self._file:
            os.fsync(self._file.fileno())
            self._file.close()
            self._file = None  # type: ignore[assignment]
