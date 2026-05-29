"""Session-level failure registry for "never repeat" operations.

Records tool-name + deterministic-hash-signature pairs that have
failed so that the FSM can skip them in subsequent steps within the
same session.  Persisted as append-only JSONL alongside checkpoint
and event-log files.
"""

from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path


class FailureRegistry:
    """Record tool failures and check whether a call should be skipped.

    Uses the same deterministic signature format as
    :class:`LoopDetector._signature` (:func:`hashlib.sha256` over
    ``{tool_name}:{sorted_args_json}``, first 16 hex chars).

    Purely session-scoped — entries are not shared across sessions.
    """

    def __init__(self, session_id: str, log_dir: str = "logs/sessions") -> None:
        self.session_id = session_id
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.log_dir, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)  # 0o700

        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.filepath: Path = self.log_dir / f"{date_str}_{session_id}.failures.jsonl"

        # Open for append + read-back; truncate for fresh session
        self._file = open(self.filepath, "w", encoding="utf-8")
        os.chmod(self._file.fileno(), stat.S_IRUSR | stat.S_IWUSR)  # 0o600

        # In-memory index: tool_name -> list of signatures
        self._entries: dict[str, list[str]] = {}

    # ── Public API ──────────────────────────────────────────────────

    def record(self, tool_name: str, signature: str, error_message: str) -> None:
        """Persist a tool failure and add it to the skip list.

        Args:
            tool_name: The registered tool name.
            signature: Deterministic hash of the call arguments.
            error_message: Human-readable error description.
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
        """Return ``True`` if this exact call has been recorded as a failure.

        Args:
            tool_name: The registered tool name.
            signature: Deterministic hash of the call arguments.

        Returns:
            ``True`` if the call should be skipped.
        """
        if tool_name in self._entries and signature in self._entries[tool_name]:
            return True
        return False

    def list_failures(self, tool_name: str) -> list[str]:
        """Return all recorded failure signatures for *tool_name*.

        Args:
            tool_name: The registered tool name.

        Returns:
            List of signature strings (empty if none recorded).
        """
        return self._entries.get(tool_name, [])

    async def close(self) -> None:
        """Flush and close the failures file."""
        if self._file and not self._file.closed:
            os.fsync(self._file.fileno())
            self._file.close()
