""":mod:`loopai.tools.types` — Core type definitions for the tool system.

Defines the foundational types used by the decorator, registry, executor,
and error classification modules. All Pydantic models follow the conventions
established in Phase 1 (``loopai.events.schemas``).

Decision references:
    D-01: ToolMetadata captures full decorator configuration
    D-02: Pydantic-based parameter validation via generated models
    D-03: Python-to-JSON-Schema type mapping table
    D-05: ToolResult standardized wrapper with truncation support
    D-06: sync/async dual support (func_ref holds either)
    D-07: per-tool timeout, default 30s
    D-11: ErrorCategory classification for retry decisions
    D-12: RetryConfig with exponential backoff + jitter
    D-13: Only TRANSIENT triggers auto-retry
"""

from __future__ import annotations

import math
import random
from enum import Enum
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field


# ── Enumerations ──────────────────────────────────────────────────────


class ErrorCategory(str, Enum):
    """Error classification for retry decision logic (D-11, D-13).

    Each category maps to a different recovery strategy:

    * **TRANSIENT** — Retry with exponential backoff (timeouts, network errors, rate limits)
    * **TOOL_EXECUTION** — Do NOT retry; inject structured error into LLM context
    * **GUARD_VIOLATION** — Do NOT retry; explain denial reason to LLM
    * **FATAL** — Terminate the session immediately (OOM, disk full, API key invalid)
    """

    TRANSIENT = "transient"
    TOOL_EXECUTION = "tool_execution"
    GUARD_VIOLATION = "guard_violation"
    FATAL = "fatal"


class PermissionLevel(str, Enum):
    """Security classification for tool operations (D-08, D-10).

    * **SAFE** — Read-only operations within working directory
    * **MODERATE** — Write operations within user directory
    * **DANGEROUS** — Irreversible or out-of-scope operations (requires confirmation)
    """

    SAFE = "safe"
    MODERATE = "moderate"
    DANGEROUS = "dangerous"


# ── Configuration models ──────────────────────────────────────────────


class RetryConfig(BaseModel):
    """Retry policy for transient errors (D-12, D-13).

    Exponential backoff with random jitter:
        delay = min(base_delay * (backoff ** attempt) + random(0, jitter), max_delay)

    Attributes:
        max_attempts: Total execution attempts (1 original + N-1 retries).
        base_delay: Initial delay in seconds before first retry.
        max_delay: Upper cap on computed delay, in seconds.
        backoff: Multiplicative factor per attempt.
        jitter: Maximum random jitter added to the computed delay.
    """

    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    backoff: float = 2.0
    jitter: float = 0.1

    def compute_delay(self, attempt: int) -> float:
        """Compute the retry delay for a given attempt number.

        Args:
            attempt: Zero-based retry attempt index (0 = first retry).

        Returns:
            Delay in seconds, capped at ``max_delay``.
        """
        exponential = self.base_delay * (self.backoff ** attempt)
        jitter_amount = random.uniform(0, self.jitter)
        delay = min(exponential + jitter_amount, self.max_delay)
        return delay


# ── Tool result ────────────────────────────────────────────────────────


class ToolResult(BaseModel):
    """Standardized wrapper for all tool execution outcomes (D-05).

    Every tool call, regardless of success or failure, is wrapped in a
    ``ToolResult`` so the agent loop has a consistent interface for
    injecting results into the LLM context.

    Attributes:
        status: ``"success"`` or ``"error"``.
        data: The return value of the tool (on success).
        error: Error message string (on failure).
        duration_ms: Wall-clock execution time in milliseconds.
        truncated: Whether ``data`` was truncated for context budget.
        overflow_file: Path to file containing the full (untruncated) result.
    """

    status: Literal["success", "error"]
    data: Any = None
    error_message: str | None = None
    duration_ms: float
    truncated: bool = False
    overflow_file: str | None = None

    @property
    def is_error(self) -> bool:
        """Convenience accessor: ``True`` when ``status == 'error'``."""
        return self.status == "error"

    @classmethod
    def success(
        cls,
        data: Any,
        duration_ms: float,
        truncated: bool = False,
        overflow_file: str | None = None,
    ) -> ToolResult:
        """Factory for a successful result."""
        return cls(
            status="success",
            data=data,
            duration_ms=duration_ms,
            truncated=truncated,
            overflow_file=overflow_file,
        )

    @classmethod
    def error(cls, error_msg: str, duration_ms: float) -> ToolResult:
        """Factory for a failed result."""
        return cls(
            status="error",
            error_message=error_msg,
            duration_ms=duration_ms,
        )


# ── Tool metadata ─────────────────────────────────────────────────────


class ToolMetadata(BaseModel):
    """Metadata for a registered tool (D-01).

    Created by the ``@tool`` decorator and stored on the function as
    ``__tool_meta__``. The ``func_ref`` field is excluded from Pydantic
    serialization to prevent leaking function references into JSON Schema
    output or log files (T-02-04).

    Attributes:
        name: Unique tool identifier (auto-derived from function name).
        description: Human-readable description (auto-derived from docstring).
        permission_level: Security classification.
        timeout: Execution timeout in seconds.
        retry: Retry policy for transient errors.
        tags: Arbitrary string tags for categorization and discovery.
        param_schema: JSON Schema for the tool's parameters (generated from type hints).
        func_ref: Reference to the callable (excluded from serialization).
    """

    name: str
    description: str
    permission_level: PermissionLevel = PermissionLevel.SAFE
    timeout: float = 30.0
    retry: RetryConfig = RetryConfig()
    tags: list[str] = []
    param_schema: dict = {}
    func_ref: Any = Field(default=None, exclude=True)

    model_config = {"arbitrary_types_allowed": True}

    def to_openai_schema(self) -> dict:
        """Return the OpenAI function-calling JSON Schema for this tool.

        Returns:
            A dict with shape::

                {
                    "type": "function",
                    "function": {
                        "name": "...",
                        "description": "...",
                        "parameters": {...}
                    }
                }
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.param_schema,
            },
        }
