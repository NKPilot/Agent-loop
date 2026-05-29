"""Tests for FailureRegistry — session-level failure record and skip logic."""

import hashlib
import json
import tempfile
from pathlib import Path

import pytest

from loopai.resilience.failure_registry import FailureRegistry


def _make_signature(tool_name: str, args: dict) -> str:
    """Generate a deterministic hash signature (same format as LoopDetector)."""
    args_json = json.dumps(args, sort_keys=True, ensure_ascii=True)
    raw = f"{tool_name}:{args_json}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class TestRecordAndSkip:
    """Verify recording a failure causes should_skip to return True."""

    def test_record_and_skip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = FailureRegistry(session_id="sess-1", log_dir=tmpdir)
            sig = _make_signature("bash", {"cmd": "rm -rf /"})

            assert registry.should_skip("bash", sig) is False
            registry.record("bash", sig, "permission denied")
            assert registry.should_skip("bash", sig) is True


class TestNoSkipForDifferentSignature:
    """Verify a different signature is not blocked for the same tool."""

    def test_no_skip_for_different_signature(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = FailureRegistry(session_id="sess-1", log_dir=tmpdir)
            sig1 = _make_signature("bash", {"cmd": "ls"})
            sig2 = _make_signature("bash", {"cmd": "pwd"})

            registry.record("bash", sig1, "error")
            assert registry.should_skip("bash", sig1) is True
            assert registry.should_skip("bash", sig2) is False


class TestNoSkipForUnrecordedTool:
    """Verify should_skip returns False for tools never recorded."""

    def test_no_skip_for_unrecorded_tool(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = FailureRegistry(session_id="sess-1", log_dir=tmpdir)
            sig = _make_signature("python", {"code": "1+1"})

            assert registry.should_skip("bash", sig) is False
            assert registry.should_skip("python", sig) is False


class TestListFailures:
    """Verify list_failures returns recorded signatures."""

    def test_list_failures(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = FailureRegistry(session_id="sess-1", log_dir=tmpdir)
            sig1 = _make_signature("bash", {"cmd": "ls"})
            sig2 = _make_signature("bash", {"cmd": "pwd"})

            assert registry.list_failures("bash") == []
            registry.record("bash", sig1, "error 1")
            registry.record("bash", sig2, "error 2")
            assert len(registry.list_failures("bash")) == 2
            assert sig1 in registry.list_failures("bash")
            assert sig2 in registry.list_failures("bash")


class TestPersistenceRoundtrip:
    """Verify file content is written correctly and can be read back."""

    def test_persistence_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = FailureRegistry(session_id="sess-1", log_dir=tmpdir)
            sig = _make_signature("bash", {"cmd": "ls"})
            registry.record("bash", sig, "test error")
            registry._file.flush()

            # Read the file back directly
            filepath = Path(registry.filepath)
            content = filepath.read_text().strip()
            assert content, "File should not be empty"
            lines = content.split("\n")
            assert len(lines) == 1

            parsed = json.loads(lines[0])
            assert parsed["tool_name"] == "bash"
            assert parsed["signature"] == sig
            assert parsed["error_message"] == "test error"
            assert "timestamp" in parsed
