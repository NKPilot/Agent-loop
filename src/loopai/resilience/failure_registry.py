""":mod:`loopai.resilience.failure_registry` — Persistent known-failure tracking (RES-03).

Records tool failures with deterministic sha256 signatures for deduplication.
Used by the FSM to skip previously-failed tool calls with the same arguments.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


class FailureRegistry:
    """Session-level registry of known tool failures (RES-03).

    Each failure is identified by a sha256 hash of (tool_name, sorted_args_json).
    Once recorded, ``should_skip()`` returns True for the same signature to
    prevent the agent from retrying a known-bad call with identical arguments.

    Attributes:
        session_id: Session identifier, used for the log filename.
        log_dir: Directory for the failure log.
    """

    def __init__(self, session_id: str, log_dir: str = "logs/sessions") -> None:
        self.session_id = session_id
        self.log_dir = log_dir
        self._failures: dict[str, list[str]] = {}  # tool_name -> [signatures]
        os.makedirs(log_dir, exist_ok=True)
        self._log_path = Path(log_dir) / f"{session_id}_failures.jsonl"

    def _make_signature(self, tool_name: str, arguments: dict) -> str:
        args_json = json.dumps(arguments, sort_keys=True, ensure_ascii=True)
        raw = f"{tool_name}:{args_json}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def record(self, tool_name: str, signature: str, error_message: str) -> None:
        """Record a tool failure.

        Args:
            tool_name: The tool that failed.
            signature: The sha256-based call signature.
            error_message: The error message from the failure.
        """
        if tool_name not in self._failures:
            self._failures[tool_name] = []
        if signature not in self._failures[tool_name]:
            self._failures[tool_name].append(signature)

        entry = {
            "tool_name": tool_name,
            "signature": signature,
            "error_message": error_message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def should_skip(self, tool_name: str, signature: str) -> bool:
        """Check if this exact tool+args combination has previously failed.

        Args:
            tool_name: The tool name.
            signature: The sha256-based call signature.

        Returns:
            True if this exact call has been recorded as failed.
        """
        return signature in self._failures.get(tool_name, [])

    def list_failures(self, tool_name: str) -> list[str]:
        """List all failure signatures for a given tool.

        Args:
            tool_name: The tool name to query.

        Returns:
            List of signature strings.
        """
        return list(self._failures.get(tool_name, []))

    async def close(self) -> None:
        """Close the failure registry (no-op, placeholder for future)."""
        pass
