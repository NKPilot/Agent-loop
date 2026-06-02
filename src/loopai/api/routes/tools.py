"""动态工具管理 REST API 端点。

提供 HTTP 端点，供 Web 前端管理动态工具的生命周期：
查询、禁用、启用和删除。

端点：
    GET    /api/tools/                 — 列出所有动态工具（摘要）
    GET    /api/tools/{tool_name}      — 获取单个工具完整信息（含代码）
    POST   /api/tools/{tool_name}/disable — 禁用动态工具
    POST   /api/tools/{tool_name}/enable  — 启用动态工具
    POST   /api/tools/{tool_name}/delete  — 删除动态工具

决策引用：
    D-09: dynamic.{hash}_{name} 命名格式
    D-06: 禁用/启用仅修改 enabled 字段和 meta.json，不卸载内存
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Request

from loopai.api.schemas import (
    ToolActionResponse,
    ToolDeleteRequest,
    ToolDetailResponse,
    ToolListResponse,
    ToolSummary,
)
from loopai.tools.tool_persistence import ToolPersistenceManager
from loopai.tools.types import ToolMetadata

logger = logging.getLogger(__name__)

router = APIRouter()


# ── 辅助函数 ─────────────────────────────────────────────────────────────


def _collect_registries(request: Request) -> list:
    """从所有活跃会话中收集包含 dynamic_creator 的注册表。

    遍历 app.state.active_sessions，提取每个会话中
    dynamic_creator 的 _registry 引用。

    Returns:
        注册表列表（ToolRegistry 实例）。
    """
    active_sessions: dict = getattr(request.app.state, "active_sessions", {})
    registries = []
    for entry in active_sessions.values():
        dynamic_creator = entry.get("dynamic_creator")
        if dynamic_creator is not None:
            registries.append(dynamic_creator._registry)
    return registries


def _extract_tags(meta: ToolMetadata) -> tuple[str, str]:
    """从 ToolMetadata tags 中提取 persistence 和 language。

    Args:
        meta: ToolMetadata 实例。

    Returns:
        (persistence, language) 元组。未找到对应 tag 时返回默认值。
    """
    persistence = "session"
    language = "python"
    for tag in meta.tags:
        if tag.startswith("persist:"):
            persistence = tag[len("persist:"):]
        if tag.startswith("lang:"):
            language = tag[len("lang:"):]
    return persistence, language


def _find_meta(registries: list, tool_name: str) -> ToolMetadata | None:
    """在所有注册表中查找工具元数据。

    Args:
        registries: 注册表列表。
        tool_name: 工具名称。

    Returns:
        找到的第一个 ToolMetadata，None 表示未找到。
    """
    for registry in registries:
        meta = registry.get(tool_name)
        if meta is not None:
            return meta
    return None


# ── 端点 ────────────────────────────────────────────────────────────────


@router.get("/tools/")
async def list_tools(request: Request) -> ToolListResponse:
    """列出所有动态工具（摘要信息）。

    收集所有活跃会话注册表中的动态工具元数据，
    按工具名去重（首条胜出），返回排序后的列表。

    Returns:
        ToolListResponse 包含 tools 列表。
    """
    registries = _collect_registries(request)

    # 按工具名去重，首条胜出（来自排序后的遍历确保确定性）
    seen: dict[str, ToolMetadata] = {}
    for registry in registries:
        for meta in registry.list_dynamic():
            if meta.name not in seen:
                seen[meta.name] = meta

    summaries = []
    for name in sorted(seen.keys()):
        meta = seen[name]
        persistence, language = _extract_tags(meta)
        summaries.append(
            ToolSummary(
                tool_name=name,
                description=meta.description,
                language=language,
                persistence=persistence,
                enabled=meta.enabled,
                is_dynamic=True,
            )
        )

    return ToolListResponse(tools=summaries)


@router.get("/tools/{tool_name}")
async def get_tool_detail(
    tool_name: str,
    request: Request,
) -> ToolDetailResponse:
    """获取单个动态工具的完整信息（含源代码和参数 Schema）。

    Args:
        tool_name: 工具名称（如 ``dynamic.a1b2c3d4_disk_check``）。
        request: FastAPI 请求对象。

    Returns:
        ToolDetailResponse 包含工具的完整元数据。

    Raises:
        HTTPException 404: 如果工具未找到。
    """
    registries = _collect_registries(request)
    meta = _find_meta(registries, tool_name)

    if meta is None:
        raise HTTPException(
            status_code=404,
            detail=f"动态工具 '{tool_name}' 未找到",
        )

    persistence, language = _extract_tags(meta)

    return ToolDetailResponse(
        tool_name=meta.name,
        description=meta.description,
        language=language,
        code=meta.code,
        param_schema=meta.param_schema,
        persistence=persistence,
        enabled=meta.enabled,
        tags=meta.tags,
    )


@router.post("/tools/{tool_name}/disable")
async def disable_tool(
    tool_name: str,
    request: Request,
) -> ToolActionResponse:
    """禁用动态工具。

    在所有活跃会话的注册表中查找工具元数据，设置 enabled=False。
    若工具已持久化，同步更新 meta.json 中的 enabled 字段。

    Args:
        tool_name: 工具名称。
        request: FastAPI 请求对象。

    Returns:
        ToolActionResponse 包含操作结果。

    Raises:
        HTTPException 404: 如果工具未找到。
    """
    registries = _collect_registries(request)
    meta = _find_meta(registries, tool_name)

    if meta is None:
        raise HTTPException(
            status_code=404,
            detail=f"动态工具 '{tool_name}' 未找到",
        )

    # 在所有注册表中设置 enabled=False
    for registry in registries:
        m = registry.get(tool_name)
        if m is not None:
            m.enabled = False

    # 更新持久化文件中的 enabled 字段
    persistence, _ = _extract_tags(meta)
    if persistence in ("sandbox", "project"):
        try:
            _update_persistence_enabled(tool_name, persistence, False)
        except Exception as exc:
            logger.warning("更新持久化工具 '%s' enabled 状态失败: %s", tool_name, exc)

    # 发布事件
    bus = getattr(request.app.state, "bus", None)
    if bus is not None:
        await bus.publish(
            "tool_disabled",
            {
                "event_type": "tool_disabled",
                "session_id": "system",
                "tool_name": tool_name,
            },
        )

    return ToolActionResponse(
        tool_name=tool_name,
        action="disable",
        success=True,
    )


@router.post("/tools/{tool_name}/enable")
async def enable_tool(
    tool_name: str,
    request: Request,
) -> ToolActionResponse:
    """启用动态工具。

    设置 enabled=True 并同步更新持久化文件。

    Args:
        tool_name: 工具名称。
        request: FastAPI 请求对象。

    Returns:
        ToolActionResponse 包含操作结果。

    Raises:
        HTTPException 404: 如果工具未找到。
    """
    registries = _collect_registries(request)
    meta = _find_meta(registries, tool_name)

    if meta is None:
        raise HTTPException(
            status_code=404,
            detail=f"动态工具 '{tool_name}' 未找到",
        )

    # 在所有注册表中设置 enabled=True
    for registry in registries:
        m = registry.get(tool_name)
        if m is not None:
            m.enabled = True

    # 更新持久化文件
    persistence, _ = _extract_tags(meta)
    if persistence in ("sandbox", "project"):
        try:
            _update_persistence_enabled(tool_name, persistence, True)
        except Exception as exc:
            logger.warning("更新持久化工具 '%s' enabled 状态失败: %s", tool_name, exc)

    # 发布事件
    bus = getattr(request.app.state, "bus", None)
    if bus is not None:
        await bus.publish(
            "tool_enabled",
            {
                "event_type": "tool_enabled",
                "session_id": "system",
                "tool_name": tool_name,
            },
        )

    return ToolActionResponse(
        tool_name=tool_name,
        action="enable",
        success=True,
    )


@router.post("/tools/{tool_name}/delete")
async def delete_tool(
    tool_name: str,
    body: ToolDeleteRequest,
    request: Request,
) -> ToolActionResponse:
    """删除动态工具。

    从所有活跃会话的注册表中移除工具元数据，
    并清理文件系统中的持久化文件。

    Args:
        tool_name: 工具名称。
        body: 必须包含 ``confirmation=True`` 以确认删除。
        request: FastAPI 请求对象。

    Returns:
        ToolActionResponse 包含操作结果。

    Raises:
        HTTPException 400: 如果 ``confirmation`` 不是 ``True``。
        HTTPException 404: 如果工具未找到。
    """
    if not body.confirmation:
        raise HTTPException(
            status_code=400,
            detail="删除操作需要确认：请设置 confirmation=true",
        )

    registries = _collect_registries(request)
    meta = _find_meta(registries, tool_name)

    if meta is None:
        raise HTTPException(
            status_code=404,
            detail=f"动态工具 '{tool_name}' 未找到",
        )

    persistence, _ = _extract_tags(meta)

    # 从所有注册表中移除
    for registry in registries:
        try:
            registry.remove(tool_name)
        except (ValueError, KeyError):
            pass

    # 清理文件系统
    if persistence in ("sandbox", "project"):
        try:
            ToolPersistenceManager().delete(tool_name, persistence)
        except Exception as exc:
            logger.warning("删除持久化工具 '%s' 文件失败: %s", tool_name, exc)

    # 发布事件
    bus = getattr(request.app.state, "bus", None)
    if bus is not None:
        await bus.publish(
            "tool_deleted",
            {
                "event_type": "tool_deleted",
                "session_id": "system",
                "tool_name": tool_name,
            },
        )

    return ToolActionResponse(
        tool_name=tool_name,
        action="delete",
        success=True,
    )


# ── 内部辅助 ────────────────────────────────────────────────────────────


def _update_persistence_enabled(
    tool_name: str, persistence: str, enabled: bool
) -> None:
    """更新持久化工具的 meta.json 中的 enabled 字段。

    Args:
        tool_name: 工具名称。
        persistence: 持久化级别（"sandbox" 或 "project"）。
        enabled: 新的 enabled 值。
    """
    pm = ToolPersistenceManager()

    if persistence == "sandbox":
        meta_path = f"{pm.SANDOX_DIR}/{tool_name}/meta.json"
    elif persistence == "project":
        meta_path = f"{pm.PROJECT_DIR}/{tool_name}.meta.json"
    else:
        return

    import os

    if not os.path.isfile(meta_path):
        logger.warning("meta.json 未找到: %s", meta_path)
        return

    with open(meta_path, "r", encoding="utf-8") as f:
        meta_data = json.load(f)

    meta_data["enabled"] = enabled

    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta_data, f, ensure_ascii=False, indent=2)
