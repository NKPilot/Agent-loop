"""会话 REST API 端点：列表、详情、删除、导出。

从文件系统读取 JSONL 会话日志文件，并将其作为 REST 资源暴露。
提供 CRUD 操作用于可观测性仪表盘中的会话历史浏览（OBS-05）。

端点：
    GET  /api/sessions               — 列出所有会话摘要
    GET  /api/sessions/{session_id}  — 获取完整事件历史
    DELETE /api/sessions/{session_id} — 删除会话及溢出文件
    GET  /api/sessions/{session_id}/export — 以 JSONL 格式下载会话
"""

import json
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response

from loopai.api.schemas import DeleteResponse, SessionListResponse, SessionSummary

router = APIRouter()

# 模块级配置，支持通过 monkeypatch 进行测试
LOG_DIR: Path = Path("logs/sessions")
OVERFLOW_DIR: Path = Path(".sandbox/overflow")


# ── 辅助函数 ─────────────────────────────────────────────────────────────


def _find_session_file(session_id: str) -> Path | None:
    """查找给定 session_id 对应的 JSONL 文件。

    扫描 LOG_DIR 中匹配 ``*_{session_id}.jsonl`` 的文件。
    返回第一个匹配项，未找到则返回 None。
    """
    if not LOG_DIR.exists():
        return None
    matches = list(LOG_DIR.glob(f"*_{session_id}.jsonl"))
    return matches[0] if matches else None


def _parse_session_summary(filepath: Path) -> SessionSummary:
    """从 JSONL 日志文件中提取会话摘要。

    读取最后一行确定步骤计数（seq 字段），
    从最后一个事件的 event_type 推导状态，
    使用文件的修改时间作为 created_at 时间戳。
    """
    session_id = _extract_session_id(filepath)
    created_at = _format_mtime(filepath)

    events = _read_jsonl_lines(filepath)
    step_count = len(events)

    # 从最后一个事件推导状态
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
    """从 JSONL 文件名中提取 session_id。

    文件名格式：``YYYY-MM-DD_{session_id}.jsonl``。
    在第一个下划线处分割，取之后的所有内容。
    """
    stem = filepath.stem  # 例如 "2026-05-29_abc123"
    parts = stem.split("_", 1)
    return parts[1] if len(parts) > 1 else stem


def _format_mtime(filepath: Path) -> str:
    """将文件修改时间格式化为 ISO 8601 字符串。"""
    from datetime import datetime, timezone

    mtime = os.path.getmtime(filepath)
    return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()


def _read_jsonl_lines(filepath: Path) -> list[dict]:
    """从文件中读取所有 JSONL 行，返回解析后的字典列表。

    跳过空行。返回原始事件字典（不包含 seq/ts/session_id 包装字段），
    供 API 消费者使用。
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
    """从文件中读取原始 JSONL 内容。"""
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


# ── 端点 ────────────────────────────────────────────────────────────────


@router.get("/sessions")
def list_sessions() -> SessionListResponse:
    """列出所有历史会话。

    扫描 LOG_DIR 中的 JSONL 文件，返回每个会话的轻量级
    摘要（id、created_at、step_count、status）。

    当日志目录或文件不存在时返回空列表（而不是 404）。
    """
    if not LOG_DIR.exists():
        return SessionListResponse(sessions=[])

    sessions = []
    for filepath in sorted(LOG_DIR.glob("*.jsonl"), key=lambda p: p.name):
        try:
            summary = _parse_session_summary(filepath)
            sessions.append(summary)
        except Exception:
            # 静默跳过损坏或无法读取的文件
            continue

    return SessionListResponse(sessions=sessions)


@router.get("/sessions/{session_id}")
def get_session(session_id: str) -> dict:
    """获取一个会话的完整事件历史。

    读取会话的 JSONL 日志文件，以 JSON 数组形式
    返回所有事件以及会话元数据。

    如果给定 session_id 没有日志文件存在，返回 404。
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
    """删除会话的 JSONL 日志文件及关联的溢出文件。

    扫描 .sandbox/overflow/ 中以此 session_id 开头的文件，
    与主日志文件一同删除。

    如果给定 session_id 没有日志文件存在，返回 404。
    路径遍历防护（T-05-05）：session_id 从 glob 匹配的文件名中提取，
    从不直接拼接到路径中。
    """
    filepath = _find_session_file(session_id)
    if filepath is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' not found",
        )

    # 删除 JSONL 日志文件
    filepath.unlink()

    # 删除关联的溢出文件（T-05-05：基于 glob，无路径遍历风险）
    if OVERFLOW_DIR.exists():
        for overflow_file in OVERFLOW_DIR.glob(f"{session_id}_*"):
            try:
                overflow_file.unlink()
            except OSError:
                pass  # 尽力清理

    return DeleteResponse(deleted=True)


@router.get("/sessions/{session_id}/export")
def export_session(session_id: str) -> Response:
    """将会话的 JSONL 日志文件导出为可下载附件。

    返回原始 JSONL 内容，附带 ``Content-Disposition: attachment``
    和 ``application/x-jsonlines`` 媒体类型。

    如果给定 session_id 没有日志文件存在，返回 404。
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
