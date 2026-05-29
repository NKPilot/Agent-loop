""":mod:`loopai.tools.registry` — Instance-based tool registry with namespace support.

ToolRegistry accepts callables decorated with ``@tool`` and indexes them
by their :attr:`ToolMetadata.name`. Multiple registry instances can coexist,
each with independent tool sets — enabling per-agent or per-session tool
configurations (D-04).

Decision references:
    D-04: Instance registry + namespace support (e.g. ``bash.ls``, ``disk.du``)

Usage::

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
    """Instance-based tool registry with namespace-aware lookup (D-04).

    Each instance maintains its own ``_tools`` dict indexed by tool name.
    Two registries are fully independent — registering a tool in one does
    not affect the other.
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolMetadata] = {}

    # ── Registration ──────────────────────────────────────────────

    def register(self, tool_fn: Callable) -> None:
        """Register a ``@tool``-decorated function.

        Reads :attr:`ToolMetadata` from ``tool_fn.__tool_meta__`` and indexes
        it by ``metadata.name``.

        Args:
            tool_fn: A function decorated with :func:`~loopai.tools.decorator.tool`.

        Raises:
            AttributeError: If *tool_fn* was not decorated with ``@tool``.
        """
        meta: ToolMetadata = tool_fn.__tool_meta__
        self._tools[meta.name] = meta

    def register_many(self, tools: list[Callable]) -> None:
        """Register multiple tools at once.

        Args:
            tools: A list of ``@tool``-decorated functions.
        """
        for t in tools:
            self.register(t)

    # ── Lookup ────────────────────────────────────────────────────

    def get(self, name: str) -> ToolMetadata | None:
        """Retrieve a tool's metadata by its full name.

        Supports ``"namespace.name"`` format — the full string is used as
        the lookup key.

        Args:
            name: The tool name (e.g. ``"bash.ls"``).

        Returns:
            :class:`ToolMetadata` if found, ``None`` otherwise.
        """
        return self._tools.get(name)

    def list_namespace(self, namespace: str) -> list[ToolMetadata]:
        """Return all tools whose name starts with ``namespace + '.'``.

        Args:
            namespace: The namespace prefix (e.g. ``"bash"``).

        Returns:
            List of :class:`ToolMetadata` in the namespace (may be empty).
        """
        prefix = namespace + "."
        return [m for name, m in self._tools.items() if name.startswith(prefix)]

    def list_all(self) -> list[ToolMetadata]:
        """Return metadata for every registered tool.

        Returns:
            List of all :class:`ToolMetadata` objects.
        """
        return list(self._tools.values())

    # ── Schema export ─────────────────────────────────────────────

    def get_schemas(self, exclude_open: set[str] | None = None) -> list[dict]:
        """Return OpenAI function-calling JSON Schemas for all registered tools.

        Args:
            exclude_open: Optional set of tool names to exclude (e.g., circuit-broken tools).

        Returns:
            List of OpenAI-compatible tool schema dicts, minus excluded tools.

        Each element is a dict with shape::

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

    # ── Introspection ─────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
