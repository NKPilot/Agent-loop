""":mod:`loopai.tools` — Tool registration, execution, and error handling system.

Public API exports:
    - Type definitions: ToolResult, ErrorCategory, RetryConfig, PermissionLevel, ToolMetadata
    - Decorator: tool (register callables with metadata and auto-generated JSON Schema)
    - Registry: ToolRegistry (instance-based tool lookup with namespace support)
    - Executor: ToolExecutor (parameter validation, timeout, result wrapping, retry)
    - Errors: classify_error, GuardViolationError (exception-to-category mapping)
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
