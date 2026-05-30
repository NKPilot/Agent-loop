"""会话级别的"不可重复"操作失败注册表。

记录已失败的工具名称 + 确定性哈希签名对，
使 FSM 可以在同一会话的后续步骤中跳过它们。
与检查点和事件日志文件一同以追加式 JSONL 持久化。
"""

from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path


class FailureRegistry:
    """记录工具失败并检查调用是否应跳过。

    使用与 :class:`LoopDetector._signature` 相同的确定性签名格式
    （:func:`hashlib.sha256` 对 ``{tool_name}:{sorted_args_json}``
    的哈希，取前 16 个十六进制字符）。

    纯会话范围——条目不跨会话共享。
    """

    def __init__(self, session_id: str, log_dir: str = "logs/sessions") -> None:
        self.session_id = session_id
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.log_dir, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)  # 0o700

        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.filepath: Path = self.log_dir / f"{date_str}_{session_id}.failures.jsonl"

        # 以追加 + 回读方式打开；新会话截断
        self._file = open(self.filepath, "w", encoding="utf-8")
        os.chmod(self._file.fileno(), stat.S_IRUSR | stat.S_IWUSR)  # 0o600

        # 内存索引：tool_name -> 签名列表
        self._entries: dict[str, list[str]] = {}

    # ── 公共 API ──────────────────────────────────────────────────

    def record(self, tool_name: str, signature: str, error_message: str) -> None:
        """持久化工具失败并添加到跳过列表。

        Args:
            tool_name: 已注册的工具名称。
            signature: 调用参数的确定性哈希。
            error_message: 人类可读的错误描述。
        """
        if tool_name not in self._entries:
            self._entries[tool_name] = []
        self._entries[tool_name].append(signature)

        entry = {
            "tool_name": tool_name,
            "signature": signature,
            "error_message": error_message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._file.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._file.flush()

    def should_skip(self, tool_name: str, signature: str) -> bool:
        """如果这个完全相同的调用已被记录为失败，返回 ``True``。

        Args:
            tool_name: 已注册的工具名称。
            signature: 调用参数的确定性哈希。

        Returns:
            如果调用应跳过，返回 ``True``。
        """
        if tool_name in self._entries and signature in self._entries[tool_name]:
            return True
        return False

    def list_failures(self, tool_name: str) -> list[str]:
        """返回 *tool_name* 的所有已记录失败签名。

        Args:
            tool_name: 已注册的工具名称。

        Returns:
            签名字符串列表（如无记录则为空）。
        """
        return self._entries.get(tool_name, [])

    async def close(self) -> None:
        """刷新并关闭失败文件。"""
        if self._file and not self._file.closed:
            os.fsync(self._file.fileno())
            self._file.close()
