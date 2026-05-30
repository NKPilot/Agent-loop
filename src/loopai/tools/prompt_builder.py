"""从 ToolRegistry 动态生成系统提示词。

避免在系统提示中硬编码工具列表——工具注册后自动反映在提示中。
"""

from __future__ import annotations

from loopai.tools.registry import ToolRegistry
from loopai.tools.types import PermissionLevel


def build_system_prompt(registry: ToolRegistry, working_dir: str = ".") -> str:
    """从 ToolRegistry 生成包含所有已注册工具说明的系统提示。

    Args:
        registry: 已注册工具的 ToolRegistry 实例。
        working_dir: 沙箱工作目录，提示中会告知 LLM。

    Returns:
        完整的系统提示字符串。
    """
    lines = [
        "你是一个具有系统诊断能力的 AI 助手。",
        "",
        "## 可用工具",
    ]

    safe_tools = []
    moderate_tools = []
    dangerous_tools = []

    for schema in registry.get_schemas():
        func = schema.get("function", schema)
        name = func.get("name", "unknown")
        desc = func.get("description", "").split("\n")[0]  # 取第一行

        info = (name, desc)
        # 通过 registry.get 获取权限级别
        meta = registry.get(name)
        if meta is not None:
            level = meta.permission_level
        else:
            level = PermissionLevel.MODERATE

        if level == PermissionLevel.DANGEROUS:
            dangerous_tools.append(info)
        elif level == PermissionLevel.SAFE:
            safe_tools.append(info)
        else:
            moderate_tools.append(info)

    for name, desc in safe_tools + moderate_tools:
        lines.append(f"- **{name}** — {desc}")
    for name, desc in dangerous_tools:
        lines.append(f"- **{name}** — {desc}（危险操作，需要用户确认）")

    lines.extend([
        "",
        "## 规则",
        "- 优先使用专用工具而非通用 bash 命令。",
        "- 需要删除文件时，直接调用删除工具——系统会自动弹出确认框让用户决定，"
        "你不需要用文字询问。",
        "- 分析完成后立即执行，不要停留在文字描述。",
        f"- 操作范围限制在沙箱目录：{working_dir}",
    ])

    return "\n".join(lines)
