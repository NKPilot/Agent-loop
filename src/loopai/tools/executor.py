""":mod:`loopai.tools.executor` — Tool execution pipeline with retry and error handling.

The :class:`ToolExecutor` is the runtime engine for tool calls.  It implements
a complete execution pipeline:

    1. Look up tool metadata from the :class:`ToolRegistry`
    2. Validate arguments against the tool's Pydantic model (D-02, D-05)
    3. Execute the tool with a configurable timeout (D-07)
    4. Classify any exceptions via :func:`~loopai.tools.errors.classify_error`
    5. Retry on transient errors with exponential backoff (D-12, D-13)
    6. Wrap the outcome in a standardized :class:`ToolResult`

Sync functions are executed in the default thread pool via
:func:`asyncio.to_thread` (D-06).  Async functions are awaited directly.

Decision references:
    D-02: Pydantic-based argument validation
    D-05: Standardized ToolResult wrapping
    D-06: sync/async dual execution strategy
    D-07: Per-tool timeout with ``asyncio.wait_for``
    D-11: Exception-to-ErrorCategory mapping
    D-12: Configurable retry with exponential backoff + jitter
    D-13: Only TRANSIENT errors trigger auto-retry
"""

from __future__ import annotations

import asyncio
import inspect
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from loopai.tools.errors import classify_error
from loopai.tools.registry import ToolRegistry
from loopai.tools.types import ErrorCategory, ToolMetadata, ToolResult

# Overflow threshold for tool output (80K characters)
_OVERFLOW_THRESHOLD_CHARS = 80 * 1024
# Directory for overflow files
_OVERFLOW_DIR = ".sandbox/overflow"


class ToolExecutor:
    """Execute tool calls through a validated, timeout-controlled pipeline.

    Args:
        registry: The :class:`ToolRegistry` to look up tools from.

    Example::

        registry = ToolRegistry()
        registry.register(my_tool)
        executor = ToolExecutor(registry)

        result = await executor.execute("my_tool", {"arg1": "value"})
        if result.is_error:
            print(f"Tool failed: {result.error_message}")
    """

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    # ── Public API ──────────────────────────────────────────────────

    async def execute(self, tool_name: str, args: dict,
                      session_id: str = "", tool_call_id: str = "") -> ToolResult:
        """Execute a tool by name with the given arguments.

        This is the main entry point.  It handles metadata lookup, argument
        validation, execution, and result wrapping.  Retry decisions are
        delegated to :meth:`_execute_with_retry`.

        Args:
            tool_name: Full tool name (e.g. ``"bash.df"``).
            args: Raw argument dict from the LLM (untrusted boundary).
            session_id: Session identifier for overflow file naming.
            tool_call_id: Tool call identifier for overflow file naming.

        Returns:
            A :class:`ToolResult` with success/error status and timing info.

        Raises:
            KeyError: If *tool_name* is not found in the registry.
        """
        metadata = self._registry.get(tool_name)
        if metadata is None:
            return ToolResult.error(
                error_msg=f"Tool '{tool_name}' not found in registry",
                duration_ms=0.0,
            )

        # Step 1: Validate arguments via the tool's Pydantic model (D-02)
        valid_model = metadata.validation_model
        if valid_model is not None:
            try:
                validated = valid_model(**args)
                validated_args = validated.model_dump()
            except ValidationError as exc:
                return ToolResult.error(
                    error_msg=f"Argument validation failed: {exc}",
                    duration_ms=0.0,
                )
        else:
            validated_args = dict(args)

        # Step 2: Execute with retry (D-12, D-13)
        return await self._execute_with_retry(metadata, validated_args,
                                               session_id, tool_call_id)

    # ── Retry loop ──────────────────────────────────────────────────

    async def _execute_with_retry(
        self, metadata: ToolMetadata, validated_args: dict,
        session_id: str = "", tool_call_id: str = "",
    ) -> ToolResult:
        """Execute the tool with retry on transient errors.

        Args:
            metadata: Tool metadata (contains retry config).
            validated_args: Arguments that have passed Pydantic validation.
            session_id: Session identifier for overflow file naming.
            tool_call_id: Tool call identifier for overflow file naming.

        Returns:
            A :class:`ToolResult` for the final outcome.
        """
        last_result: ToolResult | None = None
        retry_config = metadata.retry

        for attempt in range(retry_config.max_attempts):
            try:
                result = await self._execute_once(metadata, validated_args,
                                                   session_id, tool_call_id)
                # Success — return immediately
                return result
            except Exception as exc:
                category = classify_error(exc)

                if category == ErrorCategory.FATAL:
                    # D-13: Fatal errors re-raise directly to terminate session
                    raise

                if category == ErrorCategory.TRANSIENT:
                    # D-13: Transient errors — retry with backoff
                    msg = (
                        f"Transient error "
                        f"(attempt {attempt + 1}/{retry_config.max_attempts}): {exc}"
                    )
                    last_result = ToolResult.error(
                        error_msg=msg,
                        duration_ms=0.0,
                    )
                    # Don't sleep on the last attempt
                    if attempt < retry_config.max_attempts - 1:
                        delay = retry_config.compute_delay(attempt)
                        await asyncio.sleep(delay)
                    continue

                # TOOL_EXECUTION or GUARD_VIOLATION — no retry
                return ToolResult.error(
                    error_msg=f"{category.value}: {exc}",
                    duration_ms=0.0,
                )

        # Exhausted all retry attempts
        if last_result is not None:
            return last_result
        return ToolResult.error(
            error_msg="Retry attempts exhausted with no result",
            duration_ms=0.0,
        )

    # ── Single execution attempt ────────────────────────────────────

    async def _execute_once(
        self, metadata: ToolMetadata, validated_args: dict,
        session_id: str = "", tool_call_id: str = "",
    ) -> ToolResult:
        """Execute the tool function once with timeout and result wrapping.

        Args:
            metadata: Tool metadata (contains timeout, func_ref).
            validated_args: Validated argument dict.
            session_id: Session identifier for overflow file naming.
            tool_call_id: Tool call identifier for overflow file naming.

        Returns:
            A :class:`ToolResult` for this single attempt.

        Raises:
            Exception: Any exception raised by the tool function (caught by
                the retry loop in :meth:`_execute_with_retry`).
        """
        func = metadata.func_ref
        if func is None:
            return ToolResult.error(
                error_msg="Tool has no callable reference",
                duration_ms=0.0,
            )

        timeout = metadata.timeout
        start = time.monotonic()

        # Determine execution strategy: async → await, sync → thread pool (D-06)
        if inspect.iscoroutinefunction(func):
            coro = func(**validated_args)
        else:
            coro = asyncio.to_thread(func, **validated_args)

        # Apply timeout (D-07)
        try:
            raw_result = await asyncio.wait_for(coro, timeout=timeout)
        except TimeoutError:
            # asyncio.TimeoutError is a TRANSIENT category — re-raise
            # so the retry loop can handle it
            duration_ms = (time.monotonic() - start) * 1000
            raise TimeoutError(
                f"Tool '{metadata.name}' timed out after {timeout}s"
            )

        duration_ms = (time.monotonic() - start) * 1000

        # Write overflow file for large string results (> 80K characters)
        truncated = False
        overflow_file: str | None = None
        data: Any = raw_result

        if isinstance(data, str) and len(data) > _OVERFLOW_THRESHOLD_CHARS:
            overflow_file = self._write_overflow_file(
                metadata.name, session_id, tool_call_id, data
            )
            # data 保持完整 — FSM._handle_act 负责在注入上下文时替换为引用

        return ToolResult.success(
            data=data,
            duration_ms=duration_ms,
            truncated=truncated,
            overflow_file=overflow_file,
        )

    # ── Overflow file writing ─────────────────────────────────────────

    def _write_overflow_file(
        self, tool_name: str, session_id: str, tool_call_id: str, content: str
    ) -> str:
        """Write tool output to an overflow file when it exceeds the threshold.

        File path format: ``.sandbox/overflow/{session_id}_{tool_call_id}_{timestamp}.txt``
        If ``session_id`` is empty, the file path falls back to ``{timestamp}.txt``.

        Args:
            tool_name: Name of the tool (currently unused in the path).
            session_id: Session identifier for the file name.
            tool_call_id: Tool call identifier for the file name.
            content: The full tool output string to write.

        Returns:
            The absolute path string to the written overflow file.
        """
        os.makedirs(_OVERFLOW_DIR, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        if session_id:
            filename = f"{session_id}_{tool_call_id}_{timestamp}.txt"
        else:
            filename = f"{timestamp}.txt"

        file_path = str(Path(_OVERFLOW_DIR) / filename)
        Path(file_path).write_text(content, encoding="utf-8")
        return file_path
