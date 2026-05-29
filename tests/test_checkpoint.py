"""Tests for CheckpointManager — JSONL incremental checkpoint persistence."""

import json
import tempfile
from pathlib import Path

import pytest

from loopai.resilience.checkpoint import CheckpointManager
from loopai.session.context import AgentState, Session


def _make_session(session_id: str = "test-sess") -> Session:
    """Create a Session with basic messages and tool_history for tests."""
    session = Session(session_id=session_id)
    session.state = AgentState.REASON
    session.step_count = 3
    session.messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
    ]
    session.tool_history = [("bash", "abc123"), ("python", "def456")]
    return session


class TestCheckpointSaveFormat:
    """Verify save() writes a valid JSONL line with required fields."""

    def test_checkpoint_save_format(self):
        session = _make_session()
        with tempfile.TemporaryDirectory() as tmpdir:
            ckpt = CheckpointManager(session_id=session.session_id, log_dir=tmpdir)
            state = ckpt.save(session)

            # Verify returned state dict
            assert state["session_id"] == session.session_id
            assert state["state"] == "reason"
            assert state["step_count"] == 3
            assert "timestamp" in state
            assert "created_at" in state
            assert "messages" in state
            assert "tool_history" in state
            # config must NOT be in checkpoint
            assert "config" not in state

            # Verify file content (file is opened in append mode, read via Path)
            text = ckpt.filepath.read_text().strip()
            lines = text.split("\n")
            assert len(lines) == 1
            parsed = json.loads(lines[0])
            assert parsed["session_id"] == session.session_id
            assert parsed["step_count"] == 3


class TestCheckpointRecoverRoundtrip:
    """Verify save() + recover() produces a matching Session."""

    def test_checkpoint_recover_roundtrip(self):
        session = _make_session()
        with tempfile.TemporaryDirectory() as tmpdir:
            ckpt = CheckpointManager(session_id=session.session_id, log_dir=tmpdir)
            ckpt.save(session)

            recovered = CheckpointManager.recover(
                session_id=session.session_id, log_dir=tmpdir
            )
            assert recovered is not None
            assert recovered.session_id == session.session_id
            assert recovered.state == AgentState.REASON
            assert recovered.step_count == 3
            assert recovered.messages == session.messages
            assert recovered.tool_history == session.tool_history
            assert recovered.created_at == session.created_at
            # config was not checkpointed
            assert recovered.config is None


class TestCheckpointFileLocation:
    """Verify checkpoint file uses correct directory and naming convention."""

    def test_checkpoint_file_location(self):
        session = _make_session()
        with tempfile.TemporaryDirectory() as tmpdir:
            ckpt = CheckpointManager(session_id=session.session_id, log_dir=tmpdir)
            ckpt.save(session)

            filepath = Path(ckpt.filepath)
            assert filepath.parent == Path(tmpdir)
            assert session.session_id in filepath.name
            assert filepath.suffix == ".jsonl"
            assert ".ckpt.jsonl" in filepath.name


class TestCheckpointRecoverNoFile:
    """Verify recover() returns None for non-existent session."""

    def test_checkpoint_recover_no_file(self):
        result = CheckpointManager.recover(
            session_id="nonexistent-session", log_dir="/tmp/nonexistent-dir-12345"
        )
        assert result is None


class TestCheckpointAppendOnly:
    """Verify multiple save() calls produce multiple JSONL lines and
    recover() returns the last one."""

    def test_checkpoint_append_only(self):
        session = _make_session()
        with tempfile.TemporaryDirectory() as tmpdir:
            ckpt = CheckpointManager(session_id=session.session_id, log_dir=tmpdir)

            # First save — step 3
            ckpt.save(session)

            # Second save — step 5
            session.step_count = 5
            session.state = AgentState.ACT
            ckpt.save(session)

            # Third save — step 7
            session.step_count = 7
            session.state = AgentState.OBSERVE
            ckpt.save(session)

            # Verify file has 3 lines
            text = ckpt.filepath.read_text().strip()
            lines = text.split("\n")
            assert len(lines) == 3

            # Recover should return last snapshot (step 7, OBSERVE)
            recovered = CheckpointManager.recover(
                session_id=session.session_id, log_dir=tmpdir
            )
            assert recovered is not None
            assert recovered.step_count == 7
            assert recovered.state == AgentState.OBSERVE
