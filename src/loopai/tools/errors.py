""":mod:`loopai.tools.errors` — 错误分类和自定义异常。

将 Python 异常映射到 :class:`ErrorCategory` 枚举值，
使 :class:`ToolExecutor` 能够做出重试/中止决策，而无需
在每个调用点检查异常类型链（D-11, D-13）。

决策引用:
    D-11: 异常到类别映射表
    D-13: 仅 TRANSIENT 触发自动重试

映射规则:
    ============================  ===================
    异常类型                       ErrorCategory
    ============================  ===================
    TimeoutError, ConnectionError TRANSIENT
    ValueError, TypeError,        TOOL_EXECUTION
        RuntimeError (默认)
    PermissionError,              GUARD_VIOLATION
        GuardViolationError
    MemoryError, SystemExit,      FATAL
        KeyboardInterrupt
    ============================  ===================
"""

from __future__ import annotations

import asyncio

from loopai.tools.types import ErrorCategory


class GuardViolationError(Exception):
    """当工具调用被安全守卫或权限检查阻止时抛出。

    这是一个自定义异常，与 :class:`PermissionError` 一起用于
    表示工具调用级别的守卫违规（例如危险命令被拒绝、
    路径超出沙箱范围）。不同于 :exc:`PermissionError`（来自
    操作系统），它携带了工具系统特有的语义含义。
    """

    pass


def classify_error(exception: Exception) -> ErrorCategory:
    """将异常分类为四种错误类别之一（D-11）。

    Args:
        exception: 捕获的异常实例。

    Returns:
        :class:`ErrorCategory`，决定执行器的恢复
        策略（重试、注入错误或终止）。
    """
    # ── FATAL——终止会话 ─────────────────────────────────────────
    if isinstance(exception, (MemoryError, SystemExit, KeyboardInterrupt)):
        return ErrorCategory.FATAL

    # ── GUARD_VIOLATION——安全策略拒绝 ──────────────────────────
    if isinstance(exception, (PermissionError, GuardViolationError)):
        return ErrorCategory.GUARD_VIOLATION

    # ── TRANSIENT——带退避重试 ──────────────────────────────────
    if isinstance(exception, (TimeoutError, ConnectionError, asyncio.TimeoutError)):
        return ErrorCategory.TRANSIENT

    # 检查具有瞬态 errno 代码的 OSError（ECONNRESET、ETIMEDOUT、
    # EHOSTUNREACH 等）
    if isinstance(exception, OSError):
        transient_errnos = {
            getattr(__import__("errno"), name, None)
            for name in (
                "ECONNRESET",
                "ETIMEDOUT",
                "EHOSTUNREACH",
                "ECONNREFUSED",
                "ENETUNREACH",
                "ENETDOWN",
            )
        }
        transient_errnos.discard(None)
        errno_val = getattr(exception, "errno", None)
        if errno_val is not None and errno_val in transient_errnos:
            return ErrorCategory.TRANSIENT

    # ── 默认: TOOL_EXECUTION——将错误注入 LLM 上下文 ──
    return ErrorCategory.TOOL_EXECUTION
