""":mod:`loopai.tools.registry` — 基于实例的工具注册表，支持命名空间与分区存储。

ToolRegistry 接受 ``@tool`` 装饰的可调用对象，并按
:attr:`ToolMetadata.name` 对其进行索引。多个注册表实例可以共存，
每个拥有独立的工具集——支持按 Agent 或按会话的工具配置（D-04）。

v1.1 新增分区存储（D-09）：
    * ``_static_tools`` — 静态工具（``@tool`` 装饰的编译时工具）
    * ``_dynamic_tools`` — 动态工具（Agent 运行时创建，强制 ``dynamic.`` 前缀）

决策引用:
    D-04: 实例注册表 + 命名空间支持（例如 ``bash.ls``、``disk.du``）
    D-09: dynamic.{name} 命名空间注册，使用 register_meta()
    T-08-05: 动态工具强制 dynamic. 前缀 + 分区存储；拒绝覆盖静态工具

用法::

    from loopai.tools.registry import ToolRegistry
    from loopai.tools.decorator import tool

    registry = ToolRegistry()

    @tool(name="bash.df", tags=["bash"])
    def df() -> str: ...

    registry.register(df)
    meta = registry.get("bash.df")

    # 动态工具注册
    dyn_meta = ToolMetadata(name="dynamic.a1b2c3d4_disk_check", ...)
    registry.register_meta(dyn_meta, is_dynamic=True)
"""

from __future__ import annotations

from collections.abc import Callable

from loopai.tools.types import ToolMetadata


class ToolRegistry:
    """基于实例的工具注册表，支持命名空间感知查找和分区存储（D-04, D-09）。

    每个实例维护两个独立字典：

    * ``_static_tools`` — 静态工具（``@tool`` 装饰的函数、内置工具）
    * ``_dynamic_tools`` — 动态工具（Agent 运行时创建，强制 ``dynamic.`` 前缀）

    查找时静态工具优先：``get()`` 先查 ``_static_tools`` 再查 ``_dynamic_tools``。
    """

    def __init__(self) -> None:
        self._static_tools: dict[str, ToolMetadata] = {}
        self._dynamic_tools: dict[str, ToolMetadata] = {}

    # ── 注册 ────────────────────────────────────────────────────────

    def register(self, tool_fn: Callable) -> None:
        """注册一个 ``@tool`` 装饰的函数到静态分区。

        从 ``tool_fn.__tool_meta__`` 读取 :attr:`ToolMetadata`，
        并按 ``metadata.name`` 进行索引。

        Args:
            tool_fn: 用 :func:`~loopai.tools.decorator.tool` 装饰的函数。

        Raises:
            AttributeError: 如果 *tool_fn* 未用 ``@tool`` 装饰。
            ValueError: 如果名称已存在（在任一分区中）。
        """
        meta: ToolMetadata = tool_fn.__tool_meta__
        if meta.name in self._static_tools or meta.name in self._dynamic_tools:
            raise ValueError(f"Tool '{meta.name}' is already registered")
        self._static_tools[meta.name] = meta

    def register_meta(
        self,
        meta: ToolMetadata,
        is_dynamic: bool = False,
    ) -> None:
        """直接注册一个已有的 ToolMetadata 实例。

        用于 AgentTool 桥接和动态工具创建——ToolMetadata
        通过此方法注册到 ToolRegistry，无需经过 @tool 装饰器。

        Args:
            meta: 已构造的 ToolMetadata 实例。
            is_dynamic: 是否为动态工具。若为 True，强制校验 ``meta.name``
                以 ``"dynamic."`` 开头，并写入 ``_dynamic_tools`` 分区。

        Raises:
            ValueError: 如果名称已存在（在任一分区中）。
            ValueError: 如果 ``is_dynamic=True`` 但名称不以 ``"dynamic."`` 开头。
        """
        # 名称唯一性检查（跨分区）
        if meta.name in self._static_tools or meta.name in self._dynamic_tools:
            raise ValueError(f"Tool '{meta.name}' is already registered")

        if is_dynamic:
            # 动态工具强制 dynamic. 前缀（T-08-05）
            if not meta.name.startswith("dynamic."):
                raise ValueError(
                    f"动态工具名称必须以 'dynamic.' 开头，"
                    f"当前名称为 '{meta.name}'"
                )
            self._dynamic_tools[meta.name] = meta
        else:
            self._static_tools[meta.name] = meta

    def register_many(self, tools: list[Callable]) -> None:
        """一次性注册多个静态工具。

        Args:
            tools: ``@tool`` 装饰的函数列表。
        """
        for t in tools:
            self.register(t)

    # ── 查找 ────────────────────────────────────────────────────────

    def get(self, name: str) -> ToolMetadata | None:
        """按完整名称检索工具的元数据（静态优先）。

        支持 ``"namespace.name"`` 格式——完整字符串用作查找键。
        先在 ``_static_tools`` 中查找，未找到再查 ``_dynamic_tools``。

        Args:
            name: 工具名称（例如 ``"bash.ls"``）。

        Returns:
            如果找到返回 :class:`ToolMetadata`，否则返回 ``None``。
        """
        return self._static_tools.get(name) or self._dynamic_tools.get(name)

    def list_namespace(self, namespace: str) -> list[ToolMetadata]:
        """返回以 ``namespace + '.'`` 开头的所有工具（合并两个分区）。

        Args:
            namespace: 命名空间前缀（例如 ``"bash"``）。

        Returns:
            命名空间内的 :class:`ToolMetadata` 列表（可能为空）。
            静态工具在前，动态工具在后。
        """
        prefix = namespace + "."
        static = [
            m for name, m in self._static_tools.items()
            if name.startswith(prefix)
        ]
        dynamic = [
            m for name, m in self._dynamic_tools.items()
            if name.startswith(prefix)
        ]
        return static + dynamic

    def list_all(self) -> list[ToolMetadata]:
        """返回所有已注册工具的元数据（合并两个分区）。

        Returns:
            全部 :class:`ToolMetadata` 对象的列表。
            静态工具在前，动态工具在后。
        """
        return list(self._static_tools.values()) + list(
            self._dynamic_tools.values()
        )

    def list_dynamic(self) -> list[ToolMetadata]:
        """返回所有动态工具的元数据。

        Returns:
            动态分区中全部 :class:`ToolMetadata` 对象的列表。
        """
        return list(self._dynamic_tools.values())

    # ── 删除 ────────────────────────────────────────────────────────

    def remove(self, name: str) -> None:
        """从对应分区中删除工具。

        只能删除动态工具；静态工具不允许删除（T-08-05）。

        Args:
            name: 要删除的工具名称。

        Raises:
            ValueError: 如果工具存在于 ``_static_tools`` 分区中。
            KeyError: 如果工具不存在于任何分区中。
        """
        if name in self._static_tools:
            raise ValueError(
                f"不允许删除静态工具 '{name}'。"
                f"静态工具是编译时注册的，不可在运行时移除。"
            )
        if name in self._dynamic_tools:
            del self._dynamic_tools[name]
        else:
            raise KeyError(f"Tool '{name}' not found in any partition")

    # ── 模式导出 ───────────────────────────────────────────────────

    def get_schemas(self, exclude_open: set[str] | None = None) -> list[dict]:
        """返回所有已注册工具的 OpenAI 函数调用 JSON Schema。

        合并两个分区的工具，静态工具在前。

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
        static_tools = list(self._static_tools.values())
        dynamic_tools = list(self._dynamic_tools.values())
        tools = static_tools + dynamic_tools
        if exclude_open:
            tools = [m for m in tools if m.name not in exclude_open]
        return [meta.to_openai_schema() for meta in tools]

    # ── 内省 ───────────────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self._static_tools) + len(self._dynamic_tools)

    def __contains__(self, name: str) -> bool:
        return name in self._static_tools or name in self._dynamic_tools
