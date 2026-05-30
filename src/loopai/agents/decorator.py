""":mod:`loopai.agents.decorator` — ``@agent`` 装饰器，用于注册子 Agent。

该装饰器复用 ``tools/decorator.py`` 的 ``_build_param_schema`` 和
``_build_validation_model`` 函数，将子 Agent 封装为可被主 Agent 调用的
可调用对象。装饰后的函数附加 ``__agent_meta__`` 属性（类似 ``__tool_meta__``
模式），供 AgentTool 桥接层读取。

决策引用:
    D-01: @agent 装饰器——类似 @tool，定义子 Agent 的 system prompt、工具集、预算。
    D-02: 子 Agent 通过 AgentRegistry 注册，与 ToolRegistry 独立管理。
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from functools import wraps
from typing import Any

from loopai.agents.registry import AgentRegistry
from loopai.agents.types import AgentMetadata
from loopai.tools.decorator import _build_param_schema, _build_validation_model
from loopai.tools.registry import ToolRegistry


def agent(
    name: str,
    description: str,
    system_prompt: str,
    tools: list[Callable] | None = None,
    max_steps: int = 10,
    timeout: float = 120.0,
    auto_register: bool = True,
):
    """装饰器工厂——将可调用对象注册为子 Agent（D-01）。

    从函数签名自动推导参数模式（复用 @tool 装饰器的 Pydantic 验证）。
    装饰后的函数通过 ``fn.__agent_meta__`` 携带 AgentMetadata。

    子 Agent 在调用时内部启动独立 ReActFSM session，完成后返回结构化结果。
    对外表现为普通 Tool——可通过 AgentTool 桥接后注册到主 Agent 的 ToolRegistry。

    Args:
        name: 子 Agent 的唯一标识符。
        description: 子 Agent 能力和用途的描述（供主 Agent LLM 理解）。
        system_prompt: 子 Agent 的系统提示，定义其角色和行为。
        tools: 子 Agent 可用的 @tool 装饰函数列表。如为 None 则使用空注册表。
        max_steps: 子 Agent 的最大步骤预算（默认 10）。
        timeout: 子 Agent 整体执行超时时间（秒，默认 120.0）。
        auto_register: 是否自动将元数据注册到默认 AgentRegistry（默认 True）。

    Returns:
        一个装饰器，用参数验证包装函数，并附加 AgentMetadata 到
        ``func.__agent_meta__``。

    Example::

        @agent(
            name="disk.analyzer",
            description="分析磁盘使用情况并给出建议",
            system_prompt="你是一个磁盘分析专家...",
            tools=[df_tool, du_tool],
        )
        def disk_analyzer(path: str) -> str:
            ...  # 函数体可自定义预处理/后处理逻辑
    """
    if tools is None:
        tools = []

    def decorator(func: Callable) -> Callable:
        # 构建子 Agent 的 tool_registry
        tool_registry = ToolRegistry()
        for t in tools:
            tool_registry.register(t)

        # 构建参数模式（复用 @tool 装饰器的逻辑）
        param_schema = _build_param_schema(func)
        validation_model = _build_validation_model(func)

        # 创建 AgentMetadata
        meta = AgentMetadata(
            name=name,
            description=description,
            system_prompt=system_prompt,
            tool_registry=tool_registry,
            max_steps=max_steps,
            timeout=timeout,
            param_schema=param_schema,
            validation_model=validation_model,
        )

        # 构建参数名到位置索引的映射
        sig = inspect.signature(func)
        param_names = [
            p.name
            for p in sig.parameters.values()
            if p.name not in ("self", "cls")
        ]

        def _merge_args_kwargs(args: tuple, kwargs: dict) -> dict:
            merged = dict(kwargs)
            for i, value in enumerate(args):
                if i < len(param_names):
                    merged[param_names[i]] = value
            return merged

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            merged = _merge_args_kwargs(args, kwargs)
            # 通过 Pydantic 模型验证参数
            validated = validation_model(**merged)
            return func(**validated.model_dump())

        # 附加元数据——AgentTool 桥接层通过 __agent_meta__ 读取
        wrapper.__agent_meta__ = meta
        wrapper.__agent_param_schema__ = param_schema
        wrapper.__agent_validation_model__ = validation_model
        wrapper.__wrapped__ = func

        # 自动注册到默认 AgentRegistry
        if auto_register:
            _default_registry.register(meta)

        return wrapper

    return decorator


# 模块级默认注册表
_default_registry = AgentRegistry()


def get_default_registry() -> AgentRegistry:
    """返回模块级默认 AgentRegistry。

    当 @agent 装饰器的 auto_register=True 时，元数据自动注册到此注册表。
    """
    return _default_registry
