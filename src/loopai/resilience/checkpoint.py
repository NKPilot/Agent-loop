"""JSONL incremental checkpoint manager for session state persistence.

Provides crash recovery by appending a serialised Session state as a
single JSON line after every FSM step.  Recovery reads the last line.
Follows the same log_dir pattern and file permissions as JSONLLogger
(D-02: colocated, linked by session_id).
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
    """Append-only JSONL checkpoint writer with crash recovery.

    Checkpoint files live in ``logs/sessions/`` alongside JSONL event
    logs, differentiated by ``.ckpt.jsonl`` suffix (D-02).

    File permissions match JSONLLogger: 0o700 directory, 0o600 file.
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

    # ── Public API ──────────────────────────────────────────────────

    def save(self, session: "Session") -> dict:
        """Serialize *session* state as one JSON line and flush.

        Only a whitelist of fields is serialised.  The ``config`` field
        is **excluded** because it contains a ``SecretStr`` API key that
        must never be written to disk.

        Returns the written state dict so the caller can publish a
        ``checkpoint_saved`` event.
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
        """Recover the most recent checkpoint for *session_id*.

        Searches ``logs/sessions/`` for files ending with
        ``_{session_id}.ckpt.jsonl``, picks the last (by name) and reads
        the last JSONL line.

        Returns:
            A reconstructed :class:`Session` (with ``config=None``), or
            ``None`` if no checkpoint file exists or the file is empty.
        """
        from loopai.session.context import AgentState, Session

        log_dir_path = Path(log_dir)
        if not log_dir_path.exists():
            return None

        suffix = f"_{session_id}.ckpt.jsonl"
        candidates = sorted(log_dir_path.glob(f"*{suffix}"))
        if not candidates:
            return None

        ckpt_file = candidates[-1]  # most recent by filename sort
        text = ckpt_file.read_text(encoding="utf-8").strip()
        if not text:
            return None

        lines = text.split("\n")
        last_line = lines[-1]
        data = json.loads(last_line)

        # JSON serialises tuples as lists — convert back
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
            config=None,  # config is never checkpointed
        )
        return session

    async def close(self) -> None:
        """Fsync then close the checkpoint file."""
        if self._file and not self._file.closed:
            os.fsync(self._file.fileno())
            self._file.close()
