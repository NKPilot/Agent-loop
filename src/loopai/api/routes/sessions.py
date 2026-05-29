"""Session REST API endpoints: list, detail, delete, export.

Reads JSONL session log files from the filesystem and exposes them
as REST resources. Provides CRUD operations for session history
browsing in the observability dashboard (OBS-05).

Endpoints:
    GET  /api/sessions              — list all session summaries
    GET  /api/sessions/{session_id} — get full event history
    DELETE /api/sessions/{session_id} — delete session and overflow files
    GET  /api/sessions/{session_id}/export — download session as JSONL
"""

import json
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response

from loopai.api.schemas import DeleteResponse, SessionListResponse, SessionSummary

router = APIRouter()

# Module-level config for testability via monkeypatch
LOG_DIR: Path = Path("logs/sessions")
OVERFLOW_DIR: Path = Path(".sandbox/overflow")


# ── Helpers ─────────────────────────────────────────────────────────────


def _find_session_file(session_id: str) -> Path | None:
    """Find the JSONL file for a given session_id.

    Scans LOG_DIR for files matching ``*_{session_id}.jsonl``.
    Returns the first match or None if not found.
    """
    if not LOG_DIR.exists():
        return None
    matches = list(LOG_DIR.glob(f"*_{session_id}.jsonl"))
    return matches[0] if matches else None


def _parse_session_summary(filepath: Path) -> SessionSummary:
    """Extract a session summary from a JSONL log file.

    Reads the last line to determine step count (seq field),
    derives status from the last event's event_type, and uses
    the file's mtime as the created_at timestamp.
    """
    session_id = _extract_session_id(filepath)
    created_at = _format_mtime(filepath)

    events = _read_jsonl_lines(filepath)
    step_count = len(events)

    # Derive status from last event
    status = "unknown"
    exit_reason = None
    if events:
        last_event = events[-1]
        if last_event.get("event_type") == "session_end":
            status = "completed"
            exit_reason = last_event.get("exit_reason")
        elif last_event.get("event_type") == "error":
            status = "error"
        else:
            status = "running"

    return SessionSummary(
        id=session_id,
        created_at=created_at,
        step_count=step_count,
        status=status,
        exit_reason=exit_reason,
    )


def _extract_session_id(filepath: Path) -> str:
    """Extract session_id from a JSONL filename.

    Filename format: ``YYYY-MM-DD_{session_id}.jsonl``.
    Splits on first underscore and takes everything after it.
    """
    stem = filepath.stem  # e.g., "2026-05-29_abc123"
    parts = stem.split("_", 1)
    return parts[1] if len(parts) > 1 else stem


def _format_mtime(filepath: Path) -> str:
    """Format file modification time as ISO 8601 string."""
    from datetime import datetime, timezone

    mtime = os.path.getmtime(filepath)
    return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()


def _read_jsonl_lines(filepath: Path) -> list[dict]:
    """Read all JSONL lines from a file, returning parsed dicts.

    Skips empty lines. Returns raw event dicts (without seq/ts/session_id
    wrapper fields) for API consumers.
    """
    events = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            events.append(json.loads(line))
    return events


def _read_raw_jsonl(filepath: Path) -> str:
    """Read the raw JSONL content from a file."""
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


# ── Endpoints ────────────────────────────────────────────────────────────


@router.get("/sessions")
def list_sessions() -> SessionListResponse:
    """List all historical sessions.

    Scans the LOG_DIR for JSONL files and returns a lightweight
    summary for each session (id, created_at, step_count, status).

    Returns an empty list (not 404) when no log directory or files exist.
    """
    if not LOG_DIR.exists():
        return SessionListResponse(sessions=[])

    sessions = []
    for filepath in sorted(LOG_DIR.glob("*.jsonl"), key=lambda p: p.name):
        try:
            summary = _parse_session_summary(filepath)
            sessions.append(summary)
        except Exception:
            # Skip corrupted or unreadable files silently
            continue

    return SessionListResponse(sessions=sessions)


@router.get("/sessions/{session_id}")
def get_session(session_id: str) -> dict:
    """Get the full event history for a session.

    Reads the session's JSONL log file and returns all events
    as a JSON array along with session metadata.

    Returns 404 if no log file exists for the given session_id.
    """
    filepath = _find_session_file(session_id)
    if filepath is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' not found",
        )

    events = _read_jsonl_lines(filepath)
    return {
        "session_id": session_id,
        "events": events,
        "step_count": len(events),
    }


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str) -> DeleteResponse:
    """Delete a session's JSONL log file and associated overflow files.

    Scans .sandbox/overflow/ for files starting with the session_id
    and deletes them alongside the main log file.

    Returns 404 if no log file exists for the given session_id.
    Path traversal protection (T-05-05): session_id is extracted from
    glob-matched filenames, never directly concatenated into paths.
    """
    filepath = _find_session_file(session_id)
    if filepath is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' not found",
        )

    # Delete the JSONL log file
    filepath.unlink()

    # Delete associated overflow files (T-05-05: glob-based, no path traversal)
    if OVERFLOW_DIR.exists():
        for overflow_file in OVERFLOW_DIR.glob(f"{session_id}_*"):
            try:
                overflow_file.unlink()
            except OSError:
                pass  # Best-effort cleanup

    return DeleteResponse(deleted=True)


@router.get("/sessions/{session_id}/export")
def export_session(session_id: str) -> Response:
    """Export a session's JSONL log file as a downloadable attachment.

    Returns the raw JSONL content with ``Content-Disposition: attachment``
    and ``application/x-jsonlines`` media type.

    Returns 404 if no log file exists for the given session_id.
    """
    filepath = _find_session_file(session_id)
    if filepath is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' not found",
        )

    raw_jsonl = _read_raw_jsonl(filepath)

    return Response(
        content=raw_jsonl,
        media_type="application/x-jsonlines",
        headers={
            "Content-Disposition": f'attachment; filename="{session_id}.jsonl"',
        },
    )
