""":mod:`loopai.agents.disk_agents` — 磁盘诊断子 Agent 定义（BIZ-03）。

提供两个 ``@agent`` 装饰的子 Agent，用于多 Agent 磁盘诊断端到端流程：

1. **disk_analyzer** — 只读诊断 Agent，使用 disk_df/disk_du/disk_find 分析磁盘
2. **disk_cleaner** — 清理执行 Agent，使用 disk_rm 执行删除（危险操作需要确认）

本模块通过 ``register_disk_tools()`` 创建绑定到 ``working_dir`` 的工具实例，
再从 ``ToolMetadata`` 通过 ``register_meta()`` 构建子 Agent 的独立 ``ToolRegistry``。
由于 ``ToolMetadata.func_ref`` 指向原始函数（而非 ``@tool`` 包装器），
无法直接传递给 ``@agent(tools=[])``，因此采用直接构建 ``AgentMetadata``
+ 附加 ``__agent_meta__`` 的模式。

决策引用:
    D-01: @agent 装饰器——定义子 Agent 的 system prompt、工具集、预算。
    D-03: 独立工具集——每个子 Agent 有自己独立的 ToolRegistry。
    D-14: 最小工具集——df、du、find（只读）、rm（需确认）。
"""

from __future__ import annotations

from loopai.agents.types import AgentMetadata
from loopai.tools.decorator import _build_param_schema
from loopai.tools.disk_tools import register_disk_tools
from loopai.tools.registry import ToolRegistry


def _build_sub_registries(
    working_dir: str = ".sandbox",
) -> tuple[ToolRegistry, ToolRegistry]:
    """创建两个独立的子 Agent ``ToolRegistry``。

    1. 只读注册表：disk_df / disk_du / disk_find（给 disk_analyzer）
    2. 清理注册表：disk_rm（给 disk_cleaner）

    通过 ``register_disk_tools()`` 创建全量工具实例（绑定 working_dir），
    再分别用 ``register_meta()`` 提取到只读/清理子注册表中。
    这避免了 ``func_ref.__tool_meta__`` 缺失的问题。

    Args:
        working_dir: 工具的工作目录（沙箱根目录），默认 ".sandbox"。

    Returns:
        (read_registry, clean_registry) 二元组。
    """
    full_registry = ToolRegistry()
    register_disk_tools(full_registry, working_dir=working_dir)

    read_registry = ToolRegistry()
    read_registry.register_meta(full_registry.get("disk_df"))
    read_registry.register_meta(full_registry.get("disk_du"))
    read_registry.register_meta(full_registry.get("disk_find"))

    clean_registry = ToolRegistry()
    clean_registry.register_meta(full_registry.get("disk_rm"))

    return read_registry, clean_registry


def _define_agent(
    name: str,
    description: str,
    system_prompt: str,
    tool_registry: ToolRegistry,
    max_steps: int,
    func,
    timeout: float = 120.0,
):
    """构建 ``AgentMetadata`` 并附加到函数上（模拟 ``@agent`` 装饰器的效果）。

    与 ``@agent`` 装饰器不同，此函数直接接受已构建好的 ``ToolRegistry``，
    避免经过 ``ToolRegistry.register()`` 路径（该路径要求工具函数有
    ``__tool_meta__`` 属性）。

    Args:
        name: 子 Agent 的唯一标识符。
        description: 子 Agent 能力和用途的描述。
        system_prompt: 子 Agent 的系统提示。
        tool_registry: 已构建好的子 Agent 工具注册表。
        max_steps: 最大步骤预算。
        func: 装饰的目标函数（用于推导参数模式）。
        timeout: 执行超时时间（秒），默认 120.0。

    Returns:
        附加了 ``__agent_meta__`` 属性的函数。
    """
    param_schema = _build_param_schema(func)
    meta = AgentMetadata(
        name=name,
        description=description,
        system_prompt=system_prompt,
        tool_registry=tool_registry,
        max_steps=max_steps,
        timeout=timeout,
        param_schema=param_schema,
    )
    func.__agent_meta__ = meta
    return func


# ── 创建子 Agent 的工具注册表 ───────────────────────────────────────
_read_registry, _clean_registry = _build_sub_registries()


# ── disk_analyzer ──────────────────────────────────────────────────────

def _disk_analyzer_impl(path: str = ".sandbox") -> str:
    """分析指定路径下的磁盘使用情况。

    主 Agent 将磁盘分析任务委托给此子 Agent。
    子 Agent 会自主使用 df、du、find 工具进行全方位分析，
    完成后返回结构化的诊断报告。

    Args:
        path: 要分析的目录路径，默认为 ".sandbox"。

    Returns:
        磁盘诊断分析报告。
    """
    return f"磁盘分析完成: {path}"


disk_analyzer = _define_agent(
    name="disk_analyzer",
    description=(
        "分析磁盘使用情况，找出大文件和可清理项。"
        "使用 df 查看总体磁盘使用、du 定位大目录、find 精准筛选大文件。"
    ),
    system_prompt=(
        "你是一个磁盘分析专家。使用工具扫描磁盘，"
        "找出占用空间大的目录和文件，"
        "分析哪些可以安全清理、哪些建议保留。"
        "输出结构化的分析报告。"
    ),
    tool_registry=_read_registry,
    max_steps=10,
    func=_disk_analyzer_impl,
)


# ── disk_cleaner ──────────────────────────────────────────────────────

def _disk_cleaner_impl(target: str, recursive: bool = False) -> str:
    """执行磁盘清理操作。

    主 Agent 将需要删除的文件/目录列表传递给此子 Agent。
    子 Agent 调用 disk_rm 执行删除，操作本身有沙箱限制。

    Args:
        target: 要删除的文件或目录路径。
        recursive: 是否递归删除目录，默认为 False。

    Returns:
        清理操作的结果报告。
    """
    return f"清理完成: {target} (recursive={recursive})"


disk_cleaner = _define_agent(
    name="disk_cleaner",
    description=(
        "执行磁盘清理——删除指定的文件或目录。"
        "**危险操作**——系统会自动弹出确认框让用户决定。"
    ),
    system_prompt=(
        "你是一个磁盘清理专家。接收需要清理的文件/目录列表，"
        "调用 disk_rm 执行删除。注意：disk_rm 是危险操作，"
        "系统会自动弹出确认框。"
    ),
    tool_registry=_clean_registry,
    max_steps=5,
    func=_disk_cleaner_impl,
)
