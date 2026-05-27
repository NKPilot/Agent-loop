""":mod:`loopai.tools.decorator` — ``@tool`` decorator for registering callables.

The decorator inspects the function's type hints and docstring to auto-generate
Pydantic validation models and JSON Schema (D-01, D-02, D-03). The decorated
function is wrapped so that argument validation occurs on every call — wrong
types raise :class:`pydantic.ValidationError` before the function body executes
(T-02-01).

Decision references:
    D-01: Full decorator configuration (name, description, permission, timeout, retry, tags)
    D-02: Pydantic auto-validation from type hints
    D-03: Python-to-JSON-Schema type mapping table
    D-07: Per-tool timeout, default 30 s

Usage::

    from loopai.tools.decorator import tool

    @tool(name="bash.df", tags=["bash"])
    def df() -> str:
        '''Show disk usage.'''
        return subprocess.check_output(["df", "-h"]).decode()
"""

from __future__ import annotations

import inspect
import types
import typing
from enum import Enum
from functools import wraps
from typing import Any, Callable, Optional, Union, get_args, get_origin

from pydantic import BaseModel, ValidationError, create_model

from loopai.tools.types import PermissionLevel, RetryConfig, ToolMetadata

# ── Type mapping: Python annotation → JSON Schema type (D-03) ─────────

_PY_TO_JSON_TYPE: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


def _annotation_to_json_schema(annotation: type) -> dict:
    """Recursively convert a Python type annotation to JSON Schema (D-03).

    Supported mappings:
        str              → {"type": "string"}
        int              → {"type": "integer"}
        float            → {"type": "number"}
        bool             → {"type": "boolean"}
        Optional[X]      → {"anyOf": [schema(X), {"type": "null"}]}
        list[X]          → {"type": "array", "items": schema(X)}
        Union[X, Y]      → {"anyOf": [schema(X), schema(Y)]}
        Enum subclass    → {"type": "string", "enum": [...]}
        Literal[...]     → {"type": "string", "enum": [...]}
        (default)        → {"type": "string"}
    """
    origin = get_origin(annotation)
    args = get_args(annotation)

    # Optional[X] → Union[X, None]
    if origin is Union or origin is Optional or origin is types.UnionType:
        # Check for Optional (Union with NoneType)
        non_none = [a for a in args if a is not type(None)]  # noqa: E721
        if len(non_none) == 1 and len(args) == 2:
            # Optional[X]
            inner = _annotation_to_json_schema(non_none[0])
            return {"anyOf": [inner, {"type": "null"}]}
        # General Union[X, Y]
        return {"anyOf": [_annotation_to_json_schema(a) for a in args]}

    # list[X]
    if origin is list or origin is list:
        if args:
            items_schema = _annotation_to_json_schema(args[0])
            return {"type": "array", "items": items_schema}
        return {"type": "array"}

    # Literal[...] → enum of strings
    if origin is typing.Literal:
        return {"type": "string", "enum": list(args)}

    # Enum subclass → enum of values
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return {"type": "string", "enum": [e.value for e in annotation]}

    # Direct type mapping
    if annotation in _PY_TO_JSON_TYPE:
        return {"type": _PY_TO_JSON_TYPE[annotation]}

    # Fallback
    return {"type": "string"}


def _build_param_schema(func: Callable) -> dict:
    """Build a JSON Schema ``parameters`` dict from a function's type hints.

    Uses the Pydantic ``model_json_schema()`` to derive the schema, then
    applies our custom mapping for consistency (D-03).

    Returns:
        A dict like ``{"type": "object", "properties": {...}, "required": [...]}``.
    """
    sig = inspect.signature(func)
    fields: dict[str, tuple[type, Any]] = {}
    required: list[str] = []

    for name, param in sig.parameters.items():
        if name in ("self", "cls"):
            continue
        annotation = param.annotation
        if annotation is inspect.Parameter.empty:
            annotation = str  # default to string if unannotated

        default = param.default
        if default is inspect.Parameter.empty:
            required.append(name)
            fields[name] = (annotation, ...)
        else:
            # Optional — keep the annotation as-is; Pydantic handles defaults
            fields[name] = (annotation, default)

    if not fields:
        return {"type": "object", "properties": {}, "required": []}

    # Create a Pydantic model and extract its JSON Schema
    validation_model = create_model(
        f"_{func.__name__}_Params",
        __base__=BaseModel,
        **fields,
    )
    pydantic_schema = validation_model.model_json_schema()

    # Build properties using our type mapping for consistency
    properties: dict = {}
    for name, param in sig.parameters.items():
        if name in ("self", "cls"):
            continue
        annotation = param.annotation
        if annotation is inspect.Parameter.empty:
            annotation = str
        properties[name] = _annotation_to_json_schema(annotation)

    result: dict = {
        "type": "object",
        "properties": properties,
        "required": required,
    }
    return result


def _build_validation_model(func: Callable) -> type[BaseModel]:
    """Build a Pydantic model for runtime argument validation (D-02)."""
    sig = inspect.signature(func)
    fields: dict[str, tuple[type, Any]] = {}

    for name, param in sig.parameters.items():
        if name in ("self", "cls"):
            continue
        annotation = param.annotation
        if annotation is inspect.Parameter.empty:
            annotation = str

        default = param.default
        if default is inspect.Parameter.empty:
            fields[name] = (annotation, ...)
        else:
            fields[name] = (annotation, default)

    if not fields:
        # No parameters — create a model with no fields
        return create_model(
            f"_{func.__name__}_Params",
            __base__=BaseModel,
        )

    return create_model(
        f"_{func.__name__}_Params",
        __base__=BaseModel,
        **fields,
    )


# ── Public API: tool decorator ────────────────────────────────────────


def tool(
    name: str | None = None,
    description: str | None = None,
    permission_level: PermissionLevel = PermissionLevel.SAFE,
    timeout: float = 30.0,
    retry: RetryConfig | None = None,
    tags: list[str] | None = None,
):
    """Decorator factory — register a callable as a tool with metadata (D-01).

    Args:
        name: Tool identifier. Auto-derived from ``func.__name__`` if ``None``.
        description: Human-readable description. Auto-derived from docstring if ``None``.
        permission_level: Security classification (default ``SAFE``).
        timeout: Execution timeout in seconds (default 30 s).
        retry: Retry policy. Uses :class:`RetryConfig` defaults if ``None``.
        tags: Arbitrary string tags for categorization.

    Returns:
        A decorator that wraps the function with parameter validation and
        attaches :class:`ToolMetadata` as ``func.__tool_meta__``.

    Example::

        @tool(name="bash.df", permission_level=PermissionLevel.SAFE, tags=["bash"])
        def df() -> str:
            '''Show disk usage.'''
            ...
    """
    if retry is None:
        retry = RetryConfig()
    if tags is None:
        tags = []

    def decorator(func: Callable) -> Callable:
        # Auto-derive metadata from function
        tool_name = name if name is not None else func.__name__
        tool_desc = description
        if tool_desc is None:
            # Use docstring first line, or fallback
            if func.__doc__:
                tool_desc = inspect.cleandoc(func.__doc__).split("\n")[0].strip()
            else:
                tool_desc = ""

        # Build validation model and JSON Schema
        validation_model = _build_validation_model(func)
        param_schema = _build_param_schema(func)

        # Create ToolMetadata
        meta = ToolMetadata(
            name=tool_name,
            description=tool_desc,
            permission_level=permission_level,
            timeout=timeout,
            retry=retry,
            tags=list(tags),
            param_schema=param_schema,
            func_ref=func,
            validation_model=validation_model,
        )

        # Build a mapping from parameter name to position index
        sig = inspect.signature(func)
        param_names = [
            p.name
            for p in sig.parameters.values()
            if p.name not in ("self", "cls")
        ]

        def _merge_args_kwargs(
            args: tuple, kwargs: dict
        ) -> dict:
            """Merge positional args into kwargs using the function signature."""
            merged = dict(kwargs)
            for i, value in enumerate(args):
                if i < len(param_names):
                    merged[param_names[i]] = value
            return merged

        # Determine if the function is async
        is_async = inspect.iscoroutinefunction(func)

        if is_async:

            @wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                # Merge positional and keyword arguments
                merged = _merge_args_kwargs(args, kwargs)
                # Validate arguments via Pydantic model
                try:
                    validated = validation_model(**merged)
                except ValidationError:
                    raise
                return await func(**validated.model_dump())

            async_wrapper.__tool_meta__ = meta
            async_wrapper.__wrapped__ = func
            return async_wrapper
        else:

            @wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                # Merge positional and keyword arguments
                merged = _merge_args_kwargs(args, kwargs)
                # Validate arguments via Pydantic model
                try:
                    validated = validation_model(**merged)
                except ValidationError:
                    raise
                return func(**validated.model_dump())

            sync_wrapper.__tool_meta__ = meta
            sync_wrapper.__wrapped__ = func
            return sync_wrapper

    return decorator
