""":mod:`loopai.tools.decorator` — 用于注册可调用对象的 ``@tool`` 装饰器。

该装饰器检查函数的类型提示和文档字符串，自动生成
Pydantic 验证模型和 JSON Schema（D-01, D-02, D-03）。装饰后的
函数被包装，使得每次调用时进行参数验证——类型不匹配时，
在函数体执行前抛出 :class:`pydantic.ValidationError`（T-02-01）。

决策引用:
    D-01: 完整装饰器配置（name, description, permission, timeout, retry, tags）
    D-02: 基于类型提示的 Pydantic 自动验证
    D-03: Python 到 JSON Schema 类型映射表
    D-07: 每个工具的超时时间，默认 30 秒

用法::

    from loopai.tools.decorator import tool

    @tool(name="bash.df", tags=["bash"])
    def df() -> str:
        '''显示磁盘使用情况。'''
        return subprocess.check_output(["df", "-h"]).decode()
"""

from __future__ import annotations

import inspect
import types
import typing
from collections.abc import Callable
from enum import Enum
from functools import wraps
from typing import Any, Optional, Union, get_args, get_origin

from pydantic import BaseModel, ValidationError, create_model

from loopai.tools.types import PermissionLevel, RetryConfig, ToolMetadata

# ── 类型映射: Python 注解 → JSON Schema 类型（D-03）─────────

_PY_TO_JSON_TYPE: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


def _annotation_to_json_schema(annotation: type) -> dict:
    """递归将 Python 类型注解转换为 JSON Schema（D-03）。

    支持的映射:
        str              → {"type": "string"}
        int              → {"type": "integer"}
        float            → {"type": "number"}
        bool             → {"type": "boolean"}
        Optional[X]      → {"anyOf": [schema(X), {"type": "null"}]}
        list[X]          → {"type": "array", "items": schema(X)}
        Union[X, Y]      → {"anyOf": [schema(X), schema(Y)]}
        Enum 子类        → {"type": "string", "enum": [...]}
        Literal[...]     → {"type": "string", "enum": [...]}
        (默认)           → {"type": "string"}
    """
    origin = get_origin(annotation)
    args = get_args(annotation)

    # Optional[X] → Union[X, None]
    if origin is Union or origin is Optional or origin is types.UnionType:
        # 检查 Optional（Union 包含 NoneType）
        non_none = [a for a in args if a is not type(None)]  # noqa: E721
        if len(non_none) == 1 and len(args) == 2:
            # Optional[X]
            inner = _annotation_to_json_schema(non_none[0])
            return {"anyOf": [inner, {"type": "null"}]}
        # 一般 Union[X, Y]
        return {"anyOf": [_annotation_to_json_schema(a) for a in args]}

    # list[X]
    if origin is list or origin is list:
        if args:
            items_schema = _annotation_to_json_schema(args[0])
            return {"type": "array", "items": items_schema}
        return {"type": "array"}

    # Literal[...] → 字符串枚举
    if origin is typing.Literal:
        return {"type": "string", "enum": list(args)}

    # Enum 子类 → 值枚举
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return {"type": "string", "enum": [e.value for e in annotation]}

    # 直接类型映射
    if annotation in _PY_TO_JSON_TYPE:
        return {"type": _PY_TO_JSON_TYPE[annotation]}

    # 回退
    return {"type": "string"}


def _build_param_schema(func: Callable) -> dict:
    """从函数的类型提示构建 JSON Schema ``parameters`` 字典。

    使用 Pydantic 的 ``model_json_schema()`` 推导模式，
    然后应用我们的自定义映射以确保一致性（D-03）。

    Returns:
        形如 ``{"type": "object", "properties": {...}, "required": [...]}`` 的字典。
    """
    sig = inspect.signature(func)
    fields: dict[str, tuple[type, Any]] = {}
    required: list[str] = []

    for name, param in sig.parameters.items():
        if name in ("self", "cls"):
            continue
        annotation = param.annotation
        if annotation is inspect.Parameter.empty:
            annotation = str  # 无注解时默认为 string

        default = param.default
        if default is inspect.Parameter.empty:
            required.append(name)
            fields[name] = (annotation, ...)
        else:
            # Optional——保持注解原样；Pydantic 处理默认值
            fields[name] = (annotation, default)

    if not fields:
        return {"type": "object", "properties": {}, "required": []}

    # 使用我们的类型映射构建 properties，确保一致性
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
    """为运行时参数验证构建 Pydantic 模型（D-02）。"""
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
        # 无参数——创建一个无字段的模型
        return create_model(
            f"_{func.__name__}_Params",
            __base__=BaseModel,
        )

    return create_model(
        f"_{func.__name__}_Params",
        __base__=BaseModel,
        **fields,
    )


# ── 公共 API: tool 装饰器 ──────────────────────────────────────────


def tool(
    name: str | None = None,
    description: str | None = None,
    permission_level: PermissionLevel = PermissionLevel.SAFE,
    timeout: float = 30.0,
    retry: RetryConfig | None = None,
    tags: list[str] | None = None,
):
    """装饰器工厂——将可调用对象注册为带有元数据的工具（D-01）。

    Args:
        name: 工具标识符。如为 ``None``，从 ``func.__name__`` 自动推导。
        description: 人类可读的描述。如为 ``None``，从文档字符串自动推导。
        permission_level: 安全分类（默认 ``SAFE``）。
        timeout: 执行超时时间，秒（默认 30 秒）。
        retry: 重试策略。如为 ``None``，使用 :class:`RetryConfig` 默认值。
        tags: 用于分类的任意字符串标签。

    Returns:
        一个装饰器，用参数验证包装函数，并附加
        :class:`ToolMetadata` 到 ``func.__tool_meta__``。

    Example::

        @tool(name="bash.df", permission_level=PermissionLevel.SAFE, tags=["bash"])
        def df() -> str:
            '''显示磁盘使用情况。'''
            ...
    """
    if retry is None:
        retry = RetryConfig()
    if tags is None:
        tags = []

    def decorator(func: Callable) -> Callable:
        # 从函数自动推导元数据
        tool_name = name if name is not None else func.__name__
        tool_desc = description
        if tool_desc is None:
            # 使用文档字符串第一行，或回退
            if func.__doc__:
                tool_desc = inspect.cleandoc(func.__doc__).split("\n")[0].strip()
            else:
                tool_desc = ""

        # 构建验证模型和 JSON Schema
        validation_model = _build_validation_model(func)
        param_schema = _build_param_schema(func)

        # 创建 ToolMetadata
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

        # 构建从参数名到位置索引的映射
        sig = inspect.signature(func)
        param_names = [
            p.name
            for p in sig.parameters.values()
            if p.name not in ("self", "cls")
        ]

        def _merge_args_kwargs(
            args: tuple, kwargs: dict
        ) -> dict:
            """将位置参数合并到 kwargs 中，使用函数签名。"""
            merged = dict(kwargs)
            for i, value in enumerate(args):
                if i < len(param_names):
                    merged[param_names[i]] = value
            return merged

        # 确定函数是否为异步
        is_async = inspect.iscoroutinefunction(func)

        if is_async:

            @wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                # 合并位置参数和关键字参数
                merged = _merge_args_kwargs(args, kwargs)
                # 通过 Pydantic 模型验证参数
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
                # 合并位置参数和关键字参数
                merged = _merge_args_kwargs(args, kwargs)
                # 通过 Pydantic 模型验证参数
                try:
                    validated = validation_model(**merged)
                except ValidationError:
                    raise
                return func(**validated.model_dump())

            sync_wrapper.__tool_meta__ = meta
            sync_wrapper.__wrapped__ = func
            return sync_wrapper

    return decorator
