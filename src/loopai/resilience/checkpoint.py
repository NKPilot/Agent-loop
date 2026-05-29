""":mod:`loopai.resilience.checkpoint` — JSONL session checkpointing (RES-01).

Saves session state to a JSONL log file after each state transition.
Supports crash recovery by reading the last line of the log file.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from loopai.session.context import Session


class CheckpointManager:
    """JSONL-based session checkpoint manager (RES-01).

    Writes one JSON line per state transition. The file is append-only,
    providing a built-in audit trail and enabling crash recovery by
    replaying or reading the last entry.

    Attributes:
        session_id: The session identifier, used as part of the filename.
        log_dir: Directory where checkpoint files are stored.
        filepath: The full path to the checkpoint JSONL file.
    """

    def __init__(self, session_id: str, log_dir: str = "logs/sessions") -> None:
        self.session_id = session_id
        self.log_dir = log_dir
        self.filepath = Path(log_dir) / f"{session_id}_checkpoint.jsonl"
        os.makedirs(self.filepath.parent, exist_ok=True)

    def save(self, session: Session) -> dict:
        """Save the current session state as a JSONL line.

        Only whitelisted fields (session_id, messages, step_count, state)
        are serialized to avoid leaking sensitive or unserializable data.

        Args:
            session: The current Session object.

        Returns:
            The dict that was written to the checkpoint file.
        """
        data = {
            "session_id": session.session_id,
            "step_count": session.step_count,
            "state": session.state.value,
            "messages": [
                {k: v for k, v in m.items() if k != "func_ref"}
                for m in session.messages
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with open(self.filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
        return data

    @classmethod
    def recover(cls, session_id: str, log_dir: str = "logs/sessions") -> Session | None:
        """Recover a session from the last checkpoint line.

        Args:
            session_id: The session identifier to recover.
            log_dir: Directory where checkpoint files are stored.

        Returns:
            A reconstructed Session object, or None if no checkpoint exists.
        """
        from loopai.session.context import Session

        filepath = Path(log_dir) / f"{session_id}_checkpoint.jsonl"
        if not filepath.exists():
            return None

        # Read the last line
        last_line = None
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    last_line = line.strip()
        if last_line is None:
            return None

        data = json.loads(last_line)
        session = Session(session_id_override=data.get("session_id", session_id))
        session.step_count = data.get("step_count", 0)

        from loopai.session.context import AgentState
        state_val = data.get("state", "reason")
        try:
            session.state = AgentState(state_val)
        except ValueError:
            session.state = AgentState.REASON

        session.messages.clear()
        session.messages.extend(data.get("messages", []))

        return session

    async def close(self) -> None:
        """Close the checkpoint manager (no-op for JSONL, placeholder for future)."""
        pass
