""":mod:`loopai.agents.registry` — 基于实例的 Agent 注册表。

AgentRegistry 接受 ``@agent`` 装饰的可调用对象，并按
AgentMetadata.name 对其进行索引。多个注册表实例可以共存，
每个拥有独立的子 Agent 集（D-02）。

该注册表复用 ToolRegistry 的设计模式（register/list_all/get），
但管理的是 AgentMetadata 而非 ToolMetadata。

决策引用:
    D-02: 子 Agent 通过 AgentRegistry 注册，与 ToolRegistry 独立管理。
"""

from __future__ import annotations

from loopai.agents.types import AgentMetadata


class AgentRegistry:
    """基于实例的 Agent 注册表（D-02）。

    每个实例维护自己的 ``_agents`` 字典，按 Agent 名称索引。
    两个注册表完全独立——在其中一个注册不会影响另一个。
    """

    def __init__(self) -> None:
        self._agents: dict[str, AgentMetadata] = {}

    # ── 注册 ────────────────────────────────────────────────────────

    def register(self, agent_meta: AgentMetadata) -> None:
        """注册一个 AgentMetadata。

        Args:
            agent_meta: 要注册的 AgentMetadata 实例。

        Raises:
            ValueError: 如果名称已存在。
        """
        if agent_meta.name in self._agents:
            raise ValueError(
                f"Agent '{agent_meta.name}' is already registered"
            )
        self._agents[agent_meta.name] = agent_meta

    def register_many(self, agents: list[AgentMetadata]) -> None:
        """一次性注册多个 AgentMetadata。

        Args:
            agents: AgentMetadata 实例列表。
        """
        for a in agents:
            self.register(a)

    # ── 查找 ────────────────────────────────────────────────────────

    def get(self, name: str) -> AgentMetadata | None:
        """按名称检索 AgentMetadata。

        Args:
            name: Agent 名称（例如 ``"disk.analyzer"``）。

        Returns:
            如果找到返回 AgentMetadata，否则返回 None。
        """
        return self._agents.get(name)

    def list_all(self) -> list[AgentMetadata]:
        """返回所有已注册的 AgentMetadata。

        Returns:
            全部 AgentMetadata 对象的列表。
        """
        return list(self._agents.values())

    # ── 内省 ───────────────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self._agents)

    def __contains__(self, name: str) -> bool:
        return name in self._agents
