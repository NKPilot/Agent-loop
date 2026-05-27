"""Tests for the loopAI tool system: types, decorator, registry, executor, errors.

Tests 1-6: ToolResult, ErrorCategory, RetryConfig, PermissionLevel, ToolMetadata
Tests 7-13: @tool decorator, ToolRegistry
"""

import math
import time
from typing import Optional

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
    assert result.error_message is None


# ── Test 2: ToolResult error construction ─────────────────────────────


def test_tool_result_error():
    """ToolResult.error() sets status='error', is_error=True, error_message accessible."""
    from loopai.tools.types import ToolResult

    result = ToolResult.error(error_msg="something failed", duration_ms=0.5)
    assert result.status == "error"
    assert result.is_error is True
    assert result.error_message == "something failed"
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


# ═══════════════════════════════════════════════════════════════════════
# Task 2: @tool decorator + ToolRegistry
# ═══════════════════════════════════════════════════════════════════════


# ── Test 7: @tool no-arg decoration ───────────────────────────────────


def test_tool_decorator_no_args():
    """@tool with no arguments — auto-derives name from function, description from docstring."""
    from loopai.tools.decorator import tool

    @tool()
    def my_helper(data: str) -> str:
        """Process the helper data."""
        return data.upper()

    meta = my_helper.__tool_meta__
    assert meta.name == "my_helper"
    assert meta.description == "Process the helper data."
    # function should still be callable
    assert my_helper("hello") == "HELLO"


# ── Test 8: @tool full-arg decoration ─────────────────────────────────


def test_tool_decorator_full_args():
    """@tool with all arguments specified — everything stored in __tool_meta__."""
    from loopai.tools.decorator import tool
    from loopai.tools.types import PermissionLevel, RetryConfig

    @tool(
        name="custom_tool",
        description="A custom description.",
        permission_level=PermissionLevel.DANGEROUS,
        timeout=60.0,
        retry=RetryConfig(max_attempts=5),
        tags=["bash", "dangerous"],
    )
    def do_stuff(x: int) -> int:
        """This docstring should be overridden."""
        return x * 2

    meta = do_stuff.__tool_meta__
    assert meta.name == "custom_tool"
    assert meta.description == "A custom description."
    assert meta.permission_level == PermissionLevel.DANGEROUS
    assert meta.timeout == 60.0
    assert meta.retry.max_attempts == 5
    assert meta.tags == ["bash", "dangerous"]
    assert do_stuff(5) == 10


# ── Test 9: @tool auto-generated Pydantic param schema ────────────────


def test_tool_decorator_type_hints_generate_schema():
    """Type hints on decorated function auto-generate JSON Schema via Pydantic."""
    from loopai.tools.decorator import tool
    from typing import Optional

    @tool()
    def mixed_types(
        text: str,
        count: int,
        price: float,
        flag: bool,
        optional_val: Optional[str] = None,
        items: list[str] = None,
    ) -> str:
        """Tool with mixed parameter types."""
        return f"{text}-{count}-{price}"

    meta = mixed_types.__tool_meta__
    schema = meta.param_schema
    props = schema.get("properties", {})

    assert props["text"]["type"] == "string"
    assert props["count"]["type"] == "integer"
    assert props["price"]["type"] == "number"
    assert props["flag"]["type"] == "boolean"
    # Optional[str] → anyOf [string, null]
    assert "anyOf" in props["optional_val"]
    # list[str] → array with string items
    assert props["items"]["type"] == "array"
    assert props["items"]["items"]["type"] == "string"


# ── Test 10: @tool parameter validation on call ───────────────────────


def test_tool_decorator_parameter_validation():
    """Calling a decorated tool with wrong type raises Pydantic ValidationError."""
    from loopai.tools.decorator import tool
    from pydantic import ValidationError

    @tool()
    def takes_int(x: int) -> int:
        return x * 2

    # Correct type works
    assert takes_int(5) == 10

    # Wrong type raises ValidationError BEFORE the function body runs
    with pytest.raises(ValidationError):
        takes_int("not_an_int")


# ── Test 11: ToolRegistry basic operations ────────────────────────────


def test_tool_registry_register_get_list_namespace():
    """ToolRegistry: register, get by name, list_namespace filters correctly."""
    from loopai.tools.decorator import tool
    from loopai.tools.registry import ToolRegistry

    registry = ToolRegistry()

    @tool(name="bash.ls", tags=["bash"])
    def ls_tool(path: str = ".") -> str:
        """List directory contents."""
        return f"ls {path}"

    @tool(name="bash.df", tags=["bash"])
    def df_tool() -> str:
        """Show disk usage."""
        return "df output"

    @tool(name="disk.du", tags=["disk"])
    def du_tool() -> str:
        """Show directory size."""
        return "du output"

    registry.register(ls_tool)
    registry.register(df_tool)
    registry.register(du_tool)

    # get by exact name
    meta = registry.get("bash.ls")
    assert meta is not None
    assert meta.name == "bash.ls"

    # get non-existent tool
    assert registry.get("nonexistent") is None

    # list_namespace filters by prefix
    bash_tools = registry.list_namespace("bash")
    assert len(bash_tools) == 2
    bash_names = {t.name for t in bash_tools}
    assert bash_names == {"bash.ls", "bash.df"}

    disk_tools = registry.list_namespace("disk")
    assert len(disk_tools) == 1
    assert disk_tools[0].name == "disk.du"


# ── Test 12: ToolRegistry instance isolation ──────────────────────────


def test_tool_registry_instance_isolation():
    """Two ToolRegistry instances are independent — different tool sets."""
    from loopai.tools.decorator import tool
    from loopai.tools.registry import ToolRegistry

    reg_a = ToolRegistry()
    reg_b = ToolRegistry()

    @tool(name="tool_a")
    def func_a() -> str:
        """Tool A."""
        return "a"

    @tool(name="tool_b")
    def func_b() -> str:
        """Tool B."""
        return "b"

    reg_a.register(func_a)
    reg_b.register(func_b)

    assert reg_a.get("tool_a") is not None
    assert reg_a.get("tool_b") is None
    assert reg_b.get("tool_a") is None
    assert reg_b.get("tool_b") is not None


# ── Test 13: ToolRegistry get_schemas() ───────────────────────────────


def test_tool_registry_get_schemas():
    """get_schemas() returns OpenAI function-calling format list."""
    from loopai.tools.decorator import tool
    from loopai.tools.registry import ToolRegistry

    registry = ToolRegistry()

    @tool(name="math.add")
    def add_tool(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    registry.register(add_tool)

    schemas = registry.get_schemas()
    assert len(schemas) == 1
    schema = schemas[0]
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "math.add"
    assert schema["function"]["description"] == "Add two numbers."
    assert "parameters" in schema["function"]
    params = schema["function"]["parameters"]
    assert params["type"] == "object"
