""":mod:`loopai.tools` — 工具注册、执行和错误处理系统。

公共 API 导出：
    - 类型定义：ToolResult、ErrorCategory、RetryConfig、PermissionLevel、ToolMetadata
    - 装饰器：tool（注册可调用对象，附加元数据和自动生成的 JSON Schema）
    - 注册表：ToolRegistry（基于实例的工具查找，支持命名空间）
    - 执行器：ToolExecutor（参数验证、超时、结果包装、重试）
    - 错误：classify_error、GuardViolationError（异常到类别映射）
"""

from loopai.tools.types import (
    ErrorCategory,
    PermissionLevel,
    RetryConfig,
    ToolMetadata,
    ToolResult,
)

__all__ = [
    "ErrorCategory",
    "PermissionLevel",
    "RetryConfig",
    "ToolMetadata",
    "ToolResult",
    "GuardViolationError",
    "classify_error",
    "tool",
    "ToolRegistry",
    "ToolExecutor",
]
