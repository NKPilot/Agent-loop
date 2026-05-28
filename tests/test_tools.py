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


# ═══════════════════════════════════════════════════════════════════════
# Task 3: ToolExecutor + error classification + retry
# ═══════════════════════════════════════════════════════════════════════


# ── Test 14: Executor runs sync tool successfully ─────────────────────


@pytest.mark.asyncio
async def test_executor_sync_tool_success():
    """ToolExecutor.execute() on a sync tool returns ToolResult.success()."""
    from loopai.tools.decorator import tool
    from loopai.tools.registry import ToolRegistry
    from loopai.tools.executor import ToolExecutor

    registry = ToolRegistry()

    @tool(name="greet")
    def greet(name: str) -> str:
        """Greet someone."""
        return f"Hello, {name}!"

    registry.register(greet)
    executor = ToolExecutor(registry)

    result = await executor.execute("greet", {"name": "World"})
    assert result.status == "success"
    assert result.is_error is False
    assert result.data == "Hello, World!"
    assert result.duration_ms > 0


# ── Test 15: Executor runs async tool successfully ────────────────────


@pytest.mark.asyncio
async def test_executor_async_tool_success():
    """ToolExecutor.execute() on an async tool returns ToolResult.success()."""
    from loopai.tools.decorator import tool
    from loopai.tools.registry import ToolRegistry
    from loopai.tools.executor import ToolExecutor

    registry = ToolRegistry()

    @tool(name="async_greet")
    async def async_greet(name: str) -> str:
        """Greet asynchronously."""
        return f"Hi, {name}!"

    registry.register(async_greet)
    executor = ToolExecutor(registry)

    result = await executor.execute("async_greet", {"name": "AsyncWorld"})
    assert result.status == "success"
    assert result.is_error is False
    assert result.data == "Hi, AsyncWorld!"
    assert result.duration_ms > 0


# ── Test 16: Executor handles tool timeout ────────────────────────────


@pytest.mark.asyncio
async def test_executor_tool_timeout():
    """Tool that exceeds timeout returns ToolResult.error() with timeout info."""
    import asyncio
    from loopai.tools.decorator import tool
    from loopai.tools.registry import ToolRegistry
    from loopai.tools.executor import ToolExecutor

    registry = ToolRegistry()

    @tool(name="slow_tool", timeout=0.1)
    async def slow_tool() -> str:
        """A very slow tool."""
        await asyncio.sleep(10.0)
        return "done"

    registry.register(slow_tool)
    executor = ToolExecutor(registry)

    result = await executor.execute("slow_tool", {})
    assert result.status == "error"
    assert result.is_error is True


# ── Test 17: Executor handles parameter validation failure ────────────


@pytest.mark.asyncio
async def test_executor_parameter_validation_failure():
    """Invalid args to executor result in ToolResult.error(), no retry."""
    from loopai.tools.decorator import tool
    from loopai.tools.registry import ToolRegistry
    from loopai.tools.executor import ToolExecutor

    registry = ToolRegistry()

    call_count = 0

    @tool(name="validated_tool")
    def validated_tool(x: int) -> int:
        """Requires an int."""
        nonlocal call_count
        call_count += 1
        return x * 2

    registry.register(validated_tool)
    executor = ToolExecutor(registry)

    # Pass string instead of int
    result = await executor.execute("validated_tool", {"x": "not_an_int"})
    assert result.status == "error"
    assert result.is_error is True
    # Function body should NOT have been called (validation fails first)
    assert call_count == 0


# ── Test 18: classify_error — TRANSIENT ───────────────────────────────


def test_classify_error_transient():
    """TimeoutError, ConnectionError classified as TRANSIENT (D-11)."""
    from loopai.tools.errors import classify_error, GuardViolationError
    from loopai.tools.types import ErrorCategory

    assert classify_error(TimeoutError("timed out")) == ErrorCategory.TRANSIENT
    assert classify_error(ConnectionError("refused")) == ErrorCategory.TRANSIENT


# ── Test 19: classify_error — TOOL_EXECUTION ──────────────────────────


def test_classify_error_tool_execution():
    """ValueError, TypeError classified as TOOL_EXECUTION."""
    from loopai.tools.errors import classify_error
    from loopai.tools.types import ErrorCategory

    assert classify_error(ValueError("bad value")) == ErrorCategory.TOOL_EXECUTION
    assert classify_error(TypeError("bad type")) == ErrorCategory.TOOL_EXECUTION
    assert classify_error(RuntimeError("something went wrong")) == ErrorCategory.TOOL_EXECUTION


# ── Test 20: classify_error — GUARD_VIOLATION ─────────────────────────


def test_classify_error_guard_violation():
    """PermissionError, GuardViolationError classified as GUARD_VIOLATION."""
    from loopai.tools.errors import classify_error, GuardViolationError
    from loopai.tools.types import ErrorCategory

    assert classify_error(PermissionError("denied")) == ErrorCategory.GUARD_VIOLATION
    assert classify_error(GuardViolationError("guard blocked")) == ErrorCategory.GUARD_VIOLATION


# ── Test 21: classify_error — FATAL ───────────────────────────────────


def test_classify_error_fatal():
    """MemoryError, SystemExit classified as FATAL."""
    from loopai.tools.errors import classify_error
    from loopai.tools.types import ErrorCategory

    assert classify_error(MemoryError("out of memory")) == ErrorCategory.FATAL
    assert classify_error(SystemExit(1)) == ErrorCategory.FATAL


# ── Test 22: Retry on transient error with backoff ────────────────────


@pytest.mark.asyncio
async def test_executor_retry_on_transient():
    """TransientError triggers retry with exponential backoff (D-12, D-13)."""
    from loopai.tools.decorator import tool
    from loopai.tools.registry import ToolRegistry
    from loopai.tools.executor import ToolExecutor
    from loopai.tools.types import RetryConfig

    registry = ToolRegistry()
    call_count = 0

    @tool(name="flaky", retry=RetryConfig(max_attempts=3, base_delay=0.01, max_delay=0.5))
    def flaky_tool() -> str:
        """Fails first two times."""
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise TimeoutError("transient failure")
        return "success on attempt 3"

    registry.register(flaky_tool)
    executor = ToolExecutor(registry)

    result = await executor.execute("flaky", {})
    assert result.status == "success"
    assert result.data == "success on attempt 3"
    assert call_count == 3  # 2 failures + 1 success = 3 calls


# ── Test 23: No retry on TOOL_EXECUTION error ─────────────────────────


@pytest.mark.asyncio
async def test_executor_no_retry_on_tool_execution_error():
    """TOOL_EXECUTION errors do NOT trigger retry (D-13)."""
    from loopai.tools.decorator import tool
    from loopai.tools.registry import ToolRegistry
    from loopai.tools.executor import ToolExecutor
    from loopai.tools.types import RetryConfig

    registry = ToolRegistry()
    call_count = 0

    @tool(name="bad_tool", retry=RetryConfig(max_attempts=3, base_delay=0.01, max_delay=0.5))
    def bad_tool() -> str:
        """Always raises ValueError."""
        nonlocal call_count
        call_count += 1
        raise ValueError("always fails")

    registry.register(bad_tool)
    executor = ToolExecutor(registry)

    result = await executor.execute("bad_tool", {})
    assert result.status == "error"
    assert result.is_error is True
    # Should only be called once — no retry for TOOL_EXECUTION
    assert call_count == 1


# ── Test 24: No retry on GUARD_VIOLATION error ────────────────────────


@pytest.mark.asyncio
async def test_executor_no_retry_on_guard_violation():
    """GUARD_VIOLATION errors do NOT trigger retry (D-13)."""
    from loopai.tools.decorator import tool
    from loopai.tools.registry import ToolRegistry
    from loopai.tools.executor import ToolExecutor
    from loopai.tools.types import RetryConfig

    registry = ToolRegistry()
    call_count = 0

    @tool(name="forbidden", retry=RetryConfig(max_attempts=3, base_delay=0.01, max_delay=0.5))
    def forbidden_tool() -> str:
        """Always denied."""
        nonlocal call_count
        call_count += 1
        raise PermissionError("access denied")

    registry.register(forbidden_tool)
    executor = ToolExecutor(registry)

    result = await executor.execute("forbidden", {})
    assert result.status == "error"
    assert result.is_error is True
    # Should only be called once — no retry for GUARD_VIOLATION
    assert call_count == 1


# ── Test 25: FatalError re-raises directly ────────────────────────────


@pytest.mark.asyncio
async def test_executor_fatal_error_reraises():
    """FatalError is re-raised directly, not wrapped in ToolResult (D-13)."""
    from loopai.tools.decorator import tool
    from loopai.tools.registry import ToolRegistry
    from loopai.tools.executor import ToolExecutor
    from loopai.tools.types import RetryConfig
    from loopai.tools.errors import GuardViolationError

    registry = ToolRegistry()

    @tool(name="oom")
    def oom_tool() -> str:
        """Simulates OOM."""
        # We cannot actually raise MemoryError reliably (Python might handle it),
        # so we use SystemExit which is also FATAL per D-11.
        raise SystemExit(1)

    registry.register(oom_tool)
    executor = ToolExecutor(registry)

    with pytest.raises(SystemExit):
        await executor.execute("oom", {})


# ═══════════════════════════════════════════════════════════════════════
# Task 4: Overflow file tests (CTX-04)
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_overflow_file_created():
    """Tool output >80K chars creates overflow file and sets overflow_file path."""
    from loopai.tools.decorator import tool
    from loopai.tools.registry import ToolRegistry
    from loopai.tools.executor import ToolExecutor

    registry = ToolRegistry()

    @tool(name="big_output")
    def big_output() -> str:
        """Produces output >80K characters."""
        return "x" * 85_000

    registry.register(big_output)
    executor = ToolExecutor(registry)

    result = await executor.execute("big_output", {},
                                     session_id="sess_abc", tool_call_id="call_001")
    assert result.status == "success"
    assert result.overflow_file is not None, "overflow_file should be set for >80K output"
    assert result.data == "x" * 85_000, "data should remain intact"
    # Verify file exists on disk
    import os
    assert os.path.exists(result.overflow_file), f"Overflow file not found: {result.overflow_file}"


@pytest.mark.asyncio
async def test_no_overflow_below_threshold():
    """Tool output <80K chars leaves overflow_file as None."""
    from loopai.tools.decorator import tool
    from loopai.tools.registry import ToolRegistry
    from loopai.tools.executor import ToolExecutor

    registry = ToolRegistry()

    @tool(name="small_output")
    def small_output() -> str:
        """Produces output <80K characters."""
        return "Hello, small world!"

    registry.register(small_output)
    executor = ToolExecutor(registry)

    result = await executor.execute("small_output", {})
    assert result.status == "success"
    assert result.overflow_file is None, "overflow_file should be None for <80K output"


@pytest.mark.asyncio
async def test_overflow_file_content():
    """Overflow file content matches the original tool output exactly."""
    from loopai.tools.decorator import tool
    from loopai.tools.registry import ToolRegistry
    from loopai.tools.executor import ToolExecutor

    registry = ToolRegistry()
    expected_content = "A" * 82_000 + "B" * 82_000  # ~164K chars

    @tool(name="large_content")
    def large_content() -> str:
        """Produces output >80K characters."""
        return expected_content

    registry.register(large_content)
    executor = ToolExecutor(registry)

    result = await executor.execute("large_content", {},
                                     session_id="sess_content", tool_call_id="call_002")
    assert result.overflow_file is not None

    # Read the overflow file and verify content matches
    from pathlib import Path
    file_content = Path(result.overflow_file).read_text(encoding="utf-8")
    assert file_content == expected_content, "Overflow file content does not match original output"
    # Verify data is still intact on the result
    assert result.data == expected_content
