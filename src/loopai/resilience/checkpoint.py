"""会话状态持久化的 JSONL 增量检查点管理器。

提供崩溃恢复能力，在每次 FSM 步骤后将序列化的 Session 状态
追加为单行 JSON。恢复时读取最后一行。
遵循与 JSONLLogger 相同的 log_dir 模式和文件权限
（D-02：同目录存放，通过 session_id 关联）。
"""

from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from loopai.session.context import Session


class CheckpointManager:
    """追加式 JSONL 检查点写入器，支持崩溃恢复。

    检查点文件存放在 ``logs/sessions/`` 中，与 JSONL 事件
    日志并列，通过 ``.ckpt.jsonl`` 后缀区分（D-02）。

    文件权限与 JSONLLogger 一致：目录 0o700，文件 0o600。
    """

    def __init__(self, session_id: str, log_dir: str = "logs/sessions") -> None:
        self.session_id = session_id
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.log_dir, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)  # 0o700

        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.filepath: Path = self.log_dir / f"{date_str}_{session_id}.ckpt.jsonl"

        self._file = open(self.filepath, "a", encoding="utf-8")
        os.chmod(self._file.fileno(), stat.S_IRUSR | stat.S_IWUSR)  # 0o600

    # ── 公共 API ──────────────────────────────────────────────────

    def save(self, session: "Session") -> dict:
        """将 *session* 状态序列化为单行 JSON 并刷新。

        只有白名单字段被序列化。``config`` 字段被**排除**，
        因为它包含绝不可写入磁盘的 ``SecretStr`` API 密钥。

        返回已写入的状态字典，以便调用方发布
        ``checkpoint_saved`` 事件。
        """
        state: dict = {
            "session_id": session.session_id,
            "state": session.state.value,
            "step_count": session.step_count,
            "messages": session.messages,
            "tool_history": session.tool_history,
            "created_at": session.created_at,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        line = json.dumps(state, ensure_ascii=False)
        self._file.write(line + "\n")
        self._file.flush()
        return state

    @classmethod
    def recover(
        cls, session_id: str, log_dir: str = "logs/sessions"
    ) -> "Session | None":
        """恢复 *session_id* 的最新检查点。

        在 ``logs/sessions/`` 中搜索以 ``_{session_id}.ckpt.jsonl``
        结尾的文件，选取最后一个（按名称排序）并读取
        最后一行 JSONL。

        Returns:
            重建的 :class:`Session`（``config=None``），
            如果检查点文件不存在或文件为空则返回 ``None``。
        """
        from loopai.session.context import AgentState, Session

        log_dir_path = Path(log_dir)
        if not log_dir_path.exists():
            return None

        suffix = f"_{session_id}.ckpt.jsonl"
        candidates = sorted(log_dir_path.glob(f"*{suffix}"))
        if not candidates:
            return None

        ckpt_file = candidates[-1]  # 按文件名排序取最新
        text = ckpt_file.read_text(encoding="utf-8").strip()
        if not text:
            return None

        lines = text.split("\n")
        last_line = lines[-1]
        data = json.loads(last_line)

        # JSON 将元组序列化为列表——转换回来
        raw_history = data.get("tool_history", [])
        tool_history: list[tuple[str, str]] = [
            tuple(item) if isinstance(item, list) else item  # type: ignore[misc]
            for item in raw_history
        ]

        session = Session(
            session_id=data["session_id"],
            state=AgentState(data["state"]),
            messages=data.get("messages", []),
            step_count=data.get("step_count", 0),
            tool_history=tool_history,
            created_at=data.get("created_at", ""),
            config=None,  # config 从不存检查点
        )
        return session

    async def close(self) -> None:
        """Fsync 后关闭检查点文件。"""
        if self._file and not self._file.closed:
            os.fsync(self._file.fileno())
            self._file.close()
