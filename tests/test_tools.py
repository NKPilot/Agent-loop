"""Tests for the loopAI tool system: types, decorator, registry, executor, errors.

Tests 1-6: ToolResult, ErrorCategory, RetryConfig, PermissionLevel, ToolMetadata
"""

import math
import time

import pytest

# ── Test 1: ToolResult success construction ───────────────────────────


def test_tool_result_success():
    """ToolResult.success() sets status='success', is_error=False, data accessible."""
    from loopai.tools.types import ToolResult

    result = ToolResult.success(data="hello", duration_ms=1.5)
    assert result.status == "success"
    assert result.is_error is False
    assert result.data == "hello"
    assert result.duration_ms == 1.5
    assert result.error is None


# ── Test 2: ToolResult error construction ─────────────────────────────


def test_tool_result_error():
    """ToolResult.error() sets status='error', is_error=True, error accessible."""
    from loopai.tools.types import ToolResult

    result = ToolResult.error(error_msg="something failed", duration_ms=0.5)
    assert result.status == "error"
    assert result.is_error is True
    assert result.error == "something failed"
    assert result.duration_ms == 0.5
    assert result.data is None


# ── Test 3: ErrorCategory enum ────────────────────────────────────────


def test_error_category_enum_values():
    """ErrorCategory has four values: TRANSIENT, TOOL_EXECUTION, GUARD_VIOLATION, FATAL."""
    from loopai.tools.types import ErrorCategory

    categories = list(ErrorCategory)
    assert len(categories) == 4
    assert ErrorCategory.TRANSIENT.value == "transient"
    assert ErrorCategory.TOOL_EXECUTION.value == "tool_execution"
    assert ErrorCategory.GUARD_VIOLATION.value == "guard_violation"
    assert ErrorCategory.FATAL.value == "fatal"


# ── Test 4: RetryConfig construction ──────────────────────────────────


def test_retry_config_defaults():
    """RetryConfig has correct defaults and compute_delay works."""
    from loopai.tools.types import RetryConfig

    rc = RetryConfig()
    assert rc.max_attempts == 3
    assert rc.base_delay == 1.0
    assert rc.max_delay == 60.0
    assert rc.backoff == 2.0
    assert rc.jitter == 0.1

    # compute_delay at attempt=0 should be ~base_delay
    delay0 = rc.compute_delay(0)
    assert 1.0 <= delay0 <= 1.0 + rc.jitter

    # compute_delay at attempt=10 should be capped at max_delay
    delay10 = rc.compute_delay(10)
    assert delay10 <= rc.max_delay


# ── Test 5: PermissionLevel enum ──────────────────────────────────────


def test_permission_level_enum_values():
    """PermissionLevel has three values: SAFE, MODERATE, DANGEROUS."""
    from loopai.tools.types import PermissionLevel

    levels = list(PermissionLevel)
    assert len(levels) == 3
    assert PermissionLevel.SAFE.value == "safe"
    assert PermissionLevel.MODERATE.value == "moderate"
    assert PermissionLevel.DANGEROUS.value == "dangerous"


# ── Test 6: ToolMetadata construction ─────────────────────────────────


def test_tool_metadata_full_construction():
    """ToolMetadata supports all fields: name, description, permission_level,
    timeout, retry, tags, param_schema, func_ref."""
    from loopai.tools.types import ToolMetadata, RetryConfig, PermissionLevel

    def dummy_func():
        """A dummy tool."""
        pass

    meta = ToolMetadata(
        name="dummy",
        description="A dummy tool.",
        permission_level=PermissionLevel.SAFE,
        timeout=30.0,
        retry=RetryConfig(max_attempts=3),
        tags=["test", "dummy"],
        param_schema={"type": "object", "properties": {}},
        func_ref=dummy_func,
    )

    assert meta.name == "dummy"
    assert meta.description == "A dummy tool."
    assert meta.permission_level == PermissionLevel.SAFE
    assert meta.timeout == 30.0
    assert meta.retry.max_attempts == 3
    assert meta.tags == ["test", "dummy"]
    assert meta.param_schema == {"type": "object", "properties": {}}
    assert meta.func_ref is dummy_func

    # func_ref should be excluded from serialization
    serialized = meta.model_dump()
    assert "func_ref" not in serialized
