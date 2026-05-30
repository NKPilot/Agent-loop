"""Integration tests for session REST API endpoints.

Tests list, detail, delete, and export endpoints against
temporary JSONL log files created during test setup.
"""

import json
from pathlib import Path

import pytest


# ── Helpers ─────────────────────────────────────────────────────────────


def _create_jsonl_file(log_dir: Path, session_id: str, events: list[dict]) -> Path:
    """Create a temporary JSONL log file with the given session_id and events.

    File naming matches JSONLLogger: YYYY-MM-DD_{session_id}.jsonl.
    Each event is written as a JSONL line with seq, ts, session_id wrapper.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    filepath = log_dir / f"2026-05-29_{session_id}.jsonl"
    with open(filepath, "w", encoding="utf-8") as f:
        for seq, event in enumerate(events):
            entry = {
                "seq": seq,
                "ts": "2026-05-29T00:00:00",
                "session_id": session_id,
                **event,
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return filepath


def _create_overflow_file(session_id: str, overflow_dir: Path) -> Path:
    """Create a temporary overflow file associated with a session_id."""
    overflow_dir.mkdir(parents=True, exist_ok=True)
    filepath = overflow_dir / f"{session_id}_bash_1_1234567890.txt"
    filepath.write_text("overflow content", encoding="utf-8")
    return filepath


# ── Test 1: Empty session list ──────────────────────────────────────────


def test_list_sessions_empty(test_client, monkeypatch, tmp_path):
    """GET /api/sessions returns empty list when no JSONL files exist."""
    log_dir = tmp_path / "sessions"
    monkeypatch.setattr("loopai.api.routes.sessions.LOG_DIR", log_dir)

    response = test_client.get("/api/sessions")
    assert response.status_code == 200
    data = response.json()
    assert "sessions" in data
    assert data["sessions"] == []


# ── Test 2: List sessions with data ─────────────────────────────────────


def test_list_sessions_with_data(test_client, monkeypatch, tmp_path):
    """GET /api/sessions returns existing session summaries."""
    log_dir = tmp_path / "sessions"
    monkeypatch.setattr("loopai.api.routes.sessions.LOG_DIR", log_dir)

    # Create two sessions
    _create_jsonl_file(
        log_dir,
        "abc123",
        [
            {"event_type": "step_start", "session_id": "abc123", "step_num": 1},
            {"event_type": "step_end", "session_id": "abc123", "step_num": 1},
            {"event_type": "session_end", "session_id": "abc123", "final_state": "FINISH", "total_steps": 1, "exit_reason": "completed"},
        ],
    )
    _create_jsonl_file(
        log_dir,
        "def456",
        [
            {"event_type": "step_start", "session_id": "def456", "step_num": 1},
        ],
    )

    response = test_client.get("/api/sessions")
    assert response.status_code == 200
    data = response.json()
    assert "sessions" in data
    assert len(data["sessions"]) == 2

    # Each session summary should have required fields
    for session in data["sessions"]:
        assert "id" in session
        assert "created_at" in session
        assert "step_count" in session
        assert "status" in session

    # The completed session should have status "completed"
    completed = [s for s in data["sessions"] if s["id"] == "abc123"]
    assert len(completed) == 1
    assert completed[0]["status"] == "completed"
    assert completed[0]["step_count"] == 3  # total event lines in JSONL


# ── Test 3: Get session detail ──────────────────────────────────────────


def test_get_session_detail(test_client, monkeypatch, tmp_path):
    """GET /api/sessions/{id} returns full event array for a session."""
    log_dir = tmp_path / "sessions"
    monkeypatch.setattr("loopai.api.routes.sessions.LOG_DIR", log_dir)

    _create_jsonl_file(
        log_dir,
        "abc123",
        [
            {"event_type": "step_start", "session_id": "abc123", "step_num": 1},
            {"event_type": "step_end", "session_id": "abc123", "step_num": 1},
        ],
    )

    response = test_client.get("/api/sessions/abc123")
    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "abc123"
    assert "events" in data
    assert len(data["events"]) == 2
    assert data["events"][0]["event_type"] == "step_start"
    assert data["events"][1]["event_type"] == "step_end"


# ── Test 4: Get nonexistent session returns 404 ─────────────────────────


def test_get_session_not_found(test_client, monkeypatch, tmp_path):
    """GET /api/sessions/{id} returns 404 for nonexistent session."""
    log_dir = tmp_path / "sessions"
    monkeypatch.setattr("loopai.api.routes.sessions.LOG_DIR", log_dir)

    response = test_client.get("/api/sessions/nonexistent")
    assert response.status_code == 404


# ── Test 5: Delete session ──────────────────────────────────────────────


def test_delete_session(test_client, monkeypatch, tmp_path):
    """DELETE /api/sessions/{id} deletes session JSONL file and overflow files."""
    log_dir = tmp_path / "sessions"
    overflow_dir = tmp_path / "overflow"
    monkeypatch.setattr("loopai.api.routes.sessions.LOG_DIR", log_dir)
    monkeypatch.setattr("loopai.api.routes.sessions.OVERFLOW_DIR", overflow_dir)

    filepath = _create_jsonl_file(
        log_dir,
        "abc123",
        [
            {"event_type": "step_start", "session_id": "abc123", "step_num": 1},
        ],
    )
    overflow_file = _create_overflow_file("abc123", overflow_dir)

    assert filepath.exists()
    assert overflow_file.exists()

    response = test_client.delete("/api/sessions/abc123")
    assert response.status_code == 200
    data = response.json()
    assert data["deleted"] is True

    # Verify file is actually deleted
    assert not filepath.exists()
    assert not overflow_file.exists()


# ── Test 6: Delete nonexistent session returns 404 ──────────────────────


def test_delete_session_not_found(test_client, monkeypatch, tmp_path):
    """DELETE /api/sessions/{id} returns 404 for nonexistent session."""
    log_dir = tmp_path / "sessions"
    monkeypatch.setattr("loopai.api.routes.sessions.LOG_DIR", log_dir)

    response = test_client.delete("/api/sessions/nonexistent")
    assert response.status_code == 404


# ── Test 7: Export session JSONL ────────────────────────────────────────


def test_export_session(test_client, monkeypatch, tmp_path):
    """GET /api/sessions/{id}/export returns JSONL download with correct headers."""
    log_dir = tmp_path / "sessions"
    monkeypatch.setattr("loopai.api.routes.sessions.LOG_DIR", log_dir)

    _create_jsonl_file(
        log_dir,
        "abc123",
        [
            {"event_type": "step_start", "session_id": "abc123", "step_num": 1},
            {"event_type": "step_end", "session_id": "abc123", "step_num": 1},
        ],
    )

    response = test_client.get("/api/sessions/abc123/export")
    assert response.status_code == 200
    assert response.headers.get("content-type") == "application/x-jsonlines"
    assert "attachment" in response.headers.get("content-disposition", "")
    assert "abc123.jsonl" in response.headers.get("content-disposition", "")

    # Verify content is valid JSONL
    lines = response.text.strip().split("\n")
    assert len(lines) == 2
    for line in lines:
        entry = json.loads(line)
        assert entry["session_id"] == "abc123"


# ── Test 8: Export nonexistent session returns 404 ──────────────────────


def test_export_session_not_found(test_client, monkeypatch, tmp_path):
    """GET /api/sessions/{id}/export returns 404 for nonexistent session."""
    log_dir = tmp_path / "sessions"
    monkeypatch.setattr("loopai.api.routes.sessions.LOG_DIR", log_dir)

    response = test_client.get("/api/sessions/nonexistent/export")
    assert response.status_code == 404
