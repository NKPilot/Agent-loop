""":mod:`loopai.tools.errors` — Error classification and custom exceptions.

Maps Python exceptions to :class:`ErrorCategory` enum values so the
:class:`ToolExecutor` can make retry/abort decisions without inspecting
exception type chains at every call site (D-11, D-13).

Decision references:
    D-11: Exception-to-category mapping table
    D-13: Only TRANSIENT triggers auto-retry

Mapping rules:
    ============================  ===================
    Exception type(s)             ErrorCategory
    ============================  ===================
    TimeoutError, ConnectionError TRANSIENT
    ValueError, TypeError,        TOOL_EXECUTION
        RuntimeError (default)
    PermissionError,              GUARD_VIOLATION
        GuardViolationError
    MemoryError, SystemExit,      FATAL
        KeyboardInterrupt
    ============================  ===================
"""

from __future__ import annotations

import asyncio
from typing import get_type_hints

from loopai.tools.types import ErrorCategory


class GuardViolationError(Exception):
    """Raised when a tool call is blocked by a security guard or permission check.

    This is a custom exception used alongside :class:`PermissionError` to
    represent a tool-call-level guard violation (e.g. dangerous command
    denied, path outside sandbox).  Unlike :exc:`PermissionError` (which comes
    from the OS), this carries a semantic meaning specific to the tool system.
    """

    pass


def classify_error(exception: Exception) -> ErrorCategory:
    """Classify an exception into one of four error categories (D-11).

    Args:
        exception: The caught exception instance.

    Returns:
        The :class:`ErrorCategory` that determines the executor's recovery
        strategy (retry, inject error, or terminate).
    """
    # ── FATAL — terminate the session ─────────────────────────────
    if isinstance(exception, (MemoryError, SystemExit, KeyboardInterrupt)):
        return ErrorCategory.FATAL

    # ── GUARD_VIOLATION — denied by security policy ────────────────
    if isinstance(exception, (PermissionError, GuardViolationError)):
        return ErrorCategory.GUARD_VIOLATION

    # ── TRANSIENT — retry with backoff ────────────────────────────
    if isinstance(exception, (TimeoutError, ConnectionError, asyncio.TimeoutError)):
        return ErrorCategory.TRANSIENT

    # Check for OSError with transient errno codes (ECONNRESET, ETIMEDOUT,
    # EHOSTUNREACH, etc.)
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

    # ── Default: TOOL_EXECUTION — inject error into LLM context ───
    return ErrorCategory.TOOL_EXECUTION
