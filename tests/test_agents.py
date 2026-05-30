"""Agent 系统单元测试（@agent 装饰器、AgentRegistry、AgentTool 桥接）。

使用 mock LLMClient 避免真实 API 调用。覆盖 7 个测试场景：
1. @agent 装饰器创建 AgentMetadata
2. AgentRegistry 注册/查找
3. AgentTool.__tool_meta__ 返回有效 ToolMetadata
4. AgentTool 创建独立 Session
5. AgentTool.execute 返回结构化摘要
6. 子 Agent 超时返回错误摘要
7. 子 Agent 工具隔离
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import SecretStr

from loopai.agents import (
    AgentMetadata,
    AgentToolResult,
    agent,
    AgentRegistry,
    AgentTool,
)
from loopai.config import AgentConfig
from loopai.tools.types import ToolMetadata


# ── Test 1: @agent 装饰器 ────────────────────────────────────────────────


def test_agent_decorator_creates_agentmetadata():
    """Test 1: @agent 装饰器正确创建 AgentMetadata。

    验证装饰器附加 __agent_meta__ 属性，各字段值正确，
    参数模式从类型提示自动推导。
    """

    @agent(
        name="test1.agent",
        description="A test agent for unit testing",
        system_prompt="You are a test agent.",
        max_steps=5,
        timeout=30.0,
    )
    def my_agent(query: str) -> str:
        return f"Processed: {query}"

    assert hasattr(my_agent, "__agent_meta__")
    meta = my_agent.__agent_meta__
    assert meta.name == "test1.agent"
    assert meta.description == "A test agent for unit testing"
    assert meta.system_prompt == "You are a test agent."
    assert meta.max_steps == 5
    assert meta.timeout == 30.0

    # 参数模式应从类型提示推导
    props = meta.param_schema.get("properties", {})
    assert "query" in props
    assert props["query"] == {"type": "string"}
    assert "query" in meta.param_schema.get("required", [])

    # validation_model 应存在
    assert hasattr(meta, "validation_model")


def test_agent_decorator_defaults():
    """验证 @agent 装饰器的默认参数值。"""

    @agent(
        name="test1.defaults",
        description="Default test",
        system_prompt="System prompt",
    )
    def default_agent() -> str:
        return "ok"

    meta = default_agent.__agent_meta__
    assert meta.max_steps == 10
    assert meta.timeout == 120.0


# ── Test 2: AgentRegistry ─────────────────────────────────────────────────


def test_agent_registry_register_get_list():
    """Test 2: AgentRegistry register/get/list_all 功能正确。"""
    reg = AgentRegistry()

    meta1 = AgentMetadata(
        name="test2.agent1",
        description="Agent 1",
        system_prompt="Prompt 1",
    )
    meta2 = AgentMetadata(
        name="test2.agent2",
        description="Agent 2",
        system_prompt="Prompt 2",
    )

    # register
    reg.register(meta1)
    reg.register(meta2)
    assert len(reg) == 2

    # get
    assert reg.get("test2.agent1") is meta1
    assert reg.get("test2.agent2") is meta2
    assert reg.get("nonexistent") is None

    # list_all
    all_agents = reg.list_all()
    assert len(all_agents) == 2
    assert meta1 in all_agents
    assert meta2 in all_agents

    # __contains__
    assert "test2.agent1" in reg
    assert "nonexistent" not in reg


def test_agent_registry_duplicate_raises():
    """注册同名 AgentMetadata 应抛出 ValueError。"""
    reg = AgentRegistry()
    meta = AgentMetadata(
        name="test2.dup", description="Dup", system_prompt="P"
    )
    reg.register(meta)

    with pytest.raises(ValueError, match="already registered"):
        reg.register(meta)


def test_agent_registry_register_many():
    """register_many 一次注册多个。"""
    reg = AgentRegistry()
    metas = [
        AgentMetadata(name=f"test2.many{i}", description=f"D{i}", system_prompt="P")
        for i in range(3)
    ]
    reg.register_many(metas)
    assert len(reg) == 3


# ── Test 3: AgentTool.__tool_meta__ ──────────────────────────────────────


def test_agent_tool_tool_meta_shape():
    """Test 3: AgentTool.__tool_meta__ 返回有效的 ToolMetadata。"""
    meta = AgentMetadata(
        name="test3.agent",
        description="Test agent for tool_meta",
        system_prompt="System prompt.",
        max_steps=3,
        timeout=60.0,
        param_schema={
            "type": "object",
            "properties": {"x": {"type": "string"}},
            "required": ["x"],
        },
    )
    config = AgentConfig(api_key=SecretStr("sk-test"))
    tool = AgentTool(agent_meta=meta, config=config)

    tm = tool.__tool_meta__
    assert isinstance(tm, ToolMetadata)
    assert tm.name == "test3.agent"
    assert tm.description == "Test agent for tool_meta"
    assert tm.timeout == 60.0
    assert tm.func_ref is not None
    assert tm.permission_level.value == "safe"
    assert "x" in tm.param_schema.get("properties", {})

    # ToolMetadata 可通过 register_meta 注册
    from loopai.tools.registry import ToolRegistry

    registry = ToolRegistry()
    registry.register_meta(tm)
    assert registry.get("test3.agent") is not None


# ── Test 4-6: AgentTool 执行（需要 mock LLMClient）─────────────────────


def _make_tool_config() -> AgentConfig:
    """返回测试用的 AgentConfig（mock API 密钥）。"""
    return AgentConfig(api_key=SecretStr("sk-test-fake"))


@pytest.mark.asyncio
async def test_agent_tool_creates_independent_session():
    """Test 4: AgentTool 创建独立 Session（session_id 与主 Agent 不同）。

    验证子 Agent 有自己的 session_id，且返回结果中包含该 session_id。
    """
    meta = AgentMetadata(
        name="test4.agent",
        description="Independent session test",
        system_prompt="You are a helpful assistant.",
        max_steps=3,
        timeout=30.0,
    )
    config = _make_tool_config()
    tool = AgentTool(agent_meta=meta, config=config)

    with patch("loopai.agents.tool.LLMClient") as MockClient:
        instance = MockClient.return_value
        instance.complete = AsyncMock(return_value={
            "content": "这是独立 Session 的测试回复",
            "tool_calls": [],
            "role": "assistant",
            "token_usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        })

        result_json = await tool.execute(query="test input")
        result = AgentToolResult.model_validate_json(result_json)

        # session_id 应非空
        assert result.session_id, "Sub-agent should have a session_id"
        # summary 包含 mock 回复
        assert "这是独立 Session" in result.summary
        # steps 应大于 0
        assert result.steps >= 1


@pytest.mark.asyncio
async def test_agent_tool_returns_structured_summary():
    """Test 5: AgentTool.execute 返回结构化摘要，包含必需字段。"""
    meta = AgentMetadata(
        name="test5.agent",
        description="Summary test",
        system_prompt="You are helpful.",
        max_steps=5,
        timeout=30.0,
    )
    config = _make_tool_config()
    tool = AgentTool(agent_meta=meta, config=config)

    with patch("loopai.agents.tool.LLMClient") as MockClient:
        instance = MockClient.return_value
        instance.complete = AsyncMock(return_value={
            "content": "最终回复摘要",
            "tool_calls": [],
            "role": "assistant",
            "token_usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
        })

        result_json = await tool.execute(query="test")
        result = AgentToolResult.model_validate_json(result_json)

        # 必需字段
        assert hasattr(result, "summary")
        assert hasattr(result, "tool_calls")
        assert hasattr(result, "steps")
        assert hasattr(result, "session_id")
        assert hasattr(result, "success")
        assert result.session_id != ""


@pytest.mark.asyncio
async def test_agent_tool_timeout_returns_error_summary():
    """Test 6: 子 Agent 超时返回错误摘要（success=False, 含超时提示）。"""
    meta = AgentMetadata(
        name="test6.agent",
        description="Timeout test",
        system_prompt="You are helpful.",
        max_steps=10,
        timeout=0.05,  # 非常短的超时
    )
    config = _make_tool_config()
    tool = AgentTool(agent_meta=meta, config=config)

    with patch("loopai.agents.tool.LLMClient") as MockClient:
        instance = MockClient.return_value

        # 使用真正的 async 函数来模拟挂起的 LLM 调用
        async def _hanging_complete(*args, **kwargs):
            await asyncio.sleep(5)

        instance.complete = _hanging_complete

        result_json = await tool.execute(query="test")
        result = AgentToolResult.model_validate_json(result_json)

        assert result.success is False
        assert "超时" in result.summary
        assert result.session_id != ""


# ── Test 7: 子 Agent 工具隔离 ──────────────────────────────────────────


def test_sub_agent_tool_isolation():
    """Test 7: 子 Agent 工具隔离——子 Agent 不能访问主 Agent 注册表的工具。

    验证子 Agent 的 tool_registry 只包含通过 @agent(tools=[...]) 注册的工具，
    不包含主 Agent 的工具。
    """
    from loopai.tools.decorator import tool

    # 主 Agent 的工具
    @tool(name="main_tool", tags=["main"])
    def main_tool_func() -> str:
        return "main"

    # 子 Agent 的工具
    @tool(name="sub_tool", tags=["sub"])
    def sub_tool_func() -> str:
        return "sub"

    # 使用 @agent 装饰器，只传 sub 工具
    @agent(
        name="test7.agent",
        description="Tool isolation test",
        system_prompt="You have sub tools only.",
        tools=[sub_tool_func],
    )
    def isolated_agent(path: str) -> str:
        return f"Checking: {path}"

    meta = isolated_agent.__agent_meta__

    # 子 Agent 只能访问 sub_tool
    sub_registry = meta.tool_registry
    assert sub_registry is not None
    assert sub_registry.get("sub_tool") is not None
    # 不应有 main_tool
    assert sub_registry.get("main_tool") is None
    assert "main_tool" not in sub_registry

    # 主 Agent 的 registry 不应有 sub_tool
    from loopai.tools.registry import ToolRegistry
    main_registry = ToolRegistry()
    main_registry.register(main_tool_func)
    assert main_registry.get("main_tool") is not None
    assert main_registry.get("sub_tool") is None


# ── BIZ-03: 多 Agent 磁盘诊断集成 ──────────────────────────────────────────


def test_biz03_agent_tools_in_registry():
    """BIZ-03-1: create_agent_components 返回的 ToolRegistry 包含子 Agent Tool。

    验证 disk_analyzer 和 disk_cleaner 作为 AgentTool 注册到主 ToolRegistry，
    主 Agent 的 tool schemas 包含子 Agent 的 function 定义。
    """
    from loopai.events.bus import EventBus
    from loopai.main import create_agent_components

    config = _make_tool_config()
    bus = EventBus()
    components = create_agent_components(config, "诊断磁盘", bus)

    registry = components["registry"]
    session = components["session"]

    # 验证 AgentTool 在 ToolRegistry 中
    analyzer_meta = registry.get("disk_analyzer")
    cleaner_meta = registry.get("disk_cleaner")
    assert analyzer_meta is not None, "disk_analyzer AgentTool should be registered"
    assert cleaner_meta is not None, "disk_cleaner AgentTool should be registered"

    # 验证 tool schemas 包含子 Agent
    schemas = registry.get_schemas()
    schema_names = [s["function"]["name"] for s in schemas]
    assert "disk_analyzer" in schema_names
    assert "disk_cleaner" in schema_names

    # 验证系统提示提及子 Agent
    sys_prompt = session.messages[0]["content"]
    assert "可用子 Agent" in sys_prompt
    assert "disk_analyzer" in sys_prompt
    assert "disk_cleaner" in sys_prompt


@pytest.mark.asyncio
async def test_biz03_multi_agent_disk_flow():
    """BIZ-03-2: Mock 场景——先调用 disk_analyzer 分析，再调用 disk_cleaner 清理。

    模拟多 Agent 磁盘诊断端到端流程：
    1. 主 Agent 调用 disk_analyzer 获取分析结果
    2. 将分析结果传给 disk_cleaner 执行清理
    3. 两个子 Agent 均返回有效结果
    """
    from loopai.agents.disk_agents import disk_analyzer, disk_cleaner

    config = _make_tool_config()
    config.tool_working_dir = ".sandbox"

    # 创建 AgentTool 实例
    tool_a = AgentTool(agent_meta=disk_analyzer.__agent_meta__, config=config)
    tool_c = AgentTool(agent_meta=disk_cleaner.__agent_meta__, config=config)

    # Mock LLMClient 让子 Agent 快速返回
    with patch("loopai.agents.tool.LLMClient") as MockClient:
        instance = MockClient.return_value
        instance.complete = AsyncMock(return_value={
            "content": "磁盘分析完成：.sandbox 目录下共 3 个大文件（超过 10MB），"
                       "建议清理 tmp/ 下的临时文件。",
            "tool_calls": [],
            "role": "assistant",
            "token_usage": {"prompt_tokens": 50, "completion_tokens": 20,
                           "total_tokens": 70},
        })

        # 步骤 1: 诊断
        result_json = await tool_a.execute(path=".sandbox")
        result_a = AgentToolResult.model_validate_json(result_json)

        assert result_a.success, "disk_analyzer should succeed"
        assert result_a.summary, "disk_analyzer should have summary"
        assert "大文件" in result_a.summary or "完成" in result_a.summary
        assert result_a.session_id, "disk_analyzer should have session_id"
        assert result_a.steps >= 1, "disk_analyzer should have steps > 0"

        # 步骤 2: 清理（基于诊断结果）
        instance.complete = AsyncMock(return_value={
            "content": "已清理 .sandbox/tmp/ 目录下的临时文件，释放 156MB 空间。",
            "tool_calls": [],
            "role": "assistant",
            "token_usage": {"prompt_tokens": 30, "completion_tokens": 15,
                           "total_tokens": 45},
        })

        result_json_c = await tool_c.execute(
            target=".sandbox/tmp", recursive=True
        )
        result_c = AgentToolResult.model_validate_json(result_json_c)

        assert result_c.success, "disk_cleaner should succeed"
        assert result_c.summary, "disk_cleaner should have summary"
        assert "清理" in result_c.summary
        assert result_c.session_id, "disk_cleaner should have session_id"
        assert result_c.steps >= 1, "disk_cleaner should have steps > 0"

        # 验证两个子 Agent 有不同的 session_id
        assert result_a.session_id != result_c.session_id, (
            "Each sub-agent call should have unique session_id"
        )
