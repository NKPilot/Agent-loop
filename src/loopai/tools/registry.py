""":mod:`loopai.tools.registry` — 基于实例的工具注册表，支持命名空间。

ToolRegistry 接受 ``@tool`` 装饰的可调用对象，并按
:attr:`ToolMetadata.name` 对其进行索引。多个注册表实例可以共存，
每个拥有独立的工具集——支持按 Agent 或按会话的工具配置（D-04）。

决策引用:
    D-04: 实例注册表 + 命名空间支持（例如 ``bash.ls``、``disk.du``）

用法::

    from loopai.tools.registry import ToolRegistry
    from loopai.tools.decorator import tool

    registry = ToolRegistry()

    @tool(name="bash.df", tags=["bash"])
    def df() -> str: ...

    registry.register(df)
    meta = registry.get("bash.df")
"""

from __future__ import annotations

from collections.abc import Callable

from loopai.tools.types import ToolMetadata


class ToolRegistry:
    """基于实例的工具注册表，支持命名空间感知查找（D-04）。

    每个实例维护自己的 ``_tools`` 字典，按工具名索引。
    两个注册表完全独立——在其中一个注册工具不会影响另一个。
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolMetadata] = {}

    # ── 注册 ────────────────────────────────────────────────────────

    def register(self, tool_fn: Callable) -> None:
        """注册一个 ``@tool`` 装饰的函数。

        从 ``tool_fn.__tool_meta__`` 读取 :attr:`ToolMetadata`，
        并按 ``metadata.name`` 进行索引。

        Args:
            tool_fn: 用 :func:`~loopai.tools.decorator.tool` 装饰的函数。

        Raises:
            AttributeError: 如果 *tool_fn* 未用 ``@tool`` 装饰。
            ValueError: 如果名称已存在。
        """
        meta: ToolMetadata = tool_fn.__tool_meta__
        if meta.name in self._tools:
            raise ValueError(f"Tool '{meta.name}' is already registered")
        self._tools[meta.name] = meta

    def register_meta(self, meta: ToolMetadata) -> None:
        """直接注册一个已有的 ToolMetadata 实例。

        用于 AgentTool 桥接——AgentTool 构造自己的 ToolMetadata，
        然后通过此方法注册到 ToolRegistry，无需经过 @tool 装饰器。

        Args:
            meta: 已构造的 ToolMetadata 实例。

        Raises:
            ValueError: 如果名称已存在。
        """
        if meta.name in self._tools:
            raise ValueError(f"Tool '{meta.name}' is already registered")
        self._tools[meta.name] = meta

    def register_many(self, tools: list[Callable]) -> None:
        """一次性注册多个工具。

        Args:
            tools: ``@tool`` 装饰的函数列表。
        """
        for t in tools:
            self.register(t)

    # ── 查找 ────────────────────────────────────────────────────────

    def get(self, name: str) -> ToolMetadata | None:
        """按完整名称检索工具的元数据。

        支持 ``"namespace.name"`` 格式——完整字符串用作查找键。

        Args:
            name: 工具名称（例如 ``"bash.ls"``）。

        Returns:
            如果找到返回 :class:`ToolMetadata`，否则返回 ``None``。
        """
        return self._tools.get(name)

    def list_namespace(self, namespace: str) -> list[ToolMetadata]:
        """返回以 ``namespace + '.'`` 开头的所有工具。

        Args:
            namespace: 命名空间前缀（例如 ``"bash"``）。

        Returns:
            命名空间内的 :class:`ToolMetadata` 列表（可能为空）。
        """
        prefix = namespace + "."
        return [m for name, m in self._tools.items() if name.startswith(prefix)]

    def list_all(self) -> list[ToolMetadata]:
        """返回所有已注册工具的元数据。

        Returns:
            全部 :class:`ToolMetadata` 对象的列表。
        """
        return list(self._tools.values())

    # ── 模式导出 ───────────────────────────────────────────────────

    def get_schemas(self, exclude_open: set[str] | None = None) -> list[dict]:
        """返回所有已注册工具的 OpenAI 函数调用 JSON Schema。

        Args:
            exclude_open: 可选的要排除的工具名称集合（例如熔断器打开的）。

        Returns:
            OpenAI 兼容的工具模式字典列表，减去被排除的工具。

        每个元素是一个具有以下形状的字典::

            {
                "type": "function",
                "function": {
                    "name": "...",
                    "description": "...",
                    "parameters": {...}
                }
            }
        """
        tools = self._tools.values()
        if exclude_open:
            tools = [m for m in tools if m.name not in exclude_open]
        return [meta.to_openai_schema() for meta in tools]

    # ── 内省 ───────────────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
