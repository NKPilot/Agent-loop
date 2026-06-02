"""动态工具系统集成测试。

测试完整管线：工具创建 → 注册 → 持久化 → 启用/禁用 → 删除 → REST API
使用真实组件（ToolRegistry、DynamicToolCreator、SandboxExecutor）避免 mock 过度。
"""

import asyncio
import json
import os
import shutil
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from loopai.api.app import create_app
from loopai.events.bus import EventBus
from loopai.tools.registry import ToolRegistry
from loopai.tools.sandbox import SandboxExecutor
from loopai.tools.tool_persistence import ToolPersistenceManager
from loopai.tools.dynamic_creator import (
    DynamicToolCreator,
    create_generate_tool_fn,
    create_list_tools_fn,
)
from loopai.tools.types import PermissionLevel, ToolMetadata


# ── 测试用的简单 Python 工具代码 ──────────────────────────────────────────

SIMPLE_CODE = '''
def main(args=None):
    import datetime
    return str(datetime.datetime.now())
'''

SIMPLE_TEST = '''
result = main()
print(result)
assert result, "应返回时间字符串"
'''

UPDATED_CODE = '''
def main(args=None):
    import datetime
    return datetime.datetime.now().isoformat()
'''

UPDATED_TEST = '''
result = main()
print(result)
assert "T" in result, "ISO 格式应包含 T"
'''


# ── 组件工厂 ─────────────────────────────────────────────────────────────


def _make_components(bus, session_id="test-session"):
    """创建动态工具系统的完整组件栈。"""
    registry = ToolRegistry()
    sandbox = SandboxExecutor(timeout=10.0, event_bus=bus)
    persistence = ToolPersistenceManager()

    # 加载已持久化工具
    for loader_fn in [persistence.load_sandbox_tools, persistence.load_project_tools]:
        for tool_data in loader_fn():
            meta_dict = tool_data.get("meta", {})
            tool_id = tool_data["tool_name"]
            code = tool_data["code"]
            language = tool_data["language"]
            persistence_level = tool_data["persistence"]
            enabled = meta_dict.get("enabled", True)

            tags = ["dynamic", f"lang:{language}", f"persist:{persistence_level}"]
            if not enabled:
                tags.append("disabled")

            meta = ToolMetadata(
                name=tool_id,
                description=meta_dict.get("description", ""),
                permission_level=PermissionLevel.MODERATE,
                timeout=30.0,
                param_schema=meta_dict.get("param_schema", {}),
                func_ref=DynamicToolCreator.build_func_ref(code, language),
                is_dynamic=True,
                enabled=enabled,
                tags=tags,
                code=code,
            )
            try:
                registry.register_meta(meta, is_dynamic=True)
            except ValueError:
                pass

    creator = DynamicToolCreator(
        registry=registry, bus=bus, session_id=session_id,
        sandbox=sandbox, persistence=persistence,
    )
    return {"registry": registry, "creator": creator, "sandbox": sandbox, "persistence": persistence}


async def _approve_tool_creation(bus, creator, timeout=3.0):
    """等待 tool_creation_requested 事件并自动批准。"""
    queue = await bus.subscribe("*")
    try:
        while True:
            ev = await asyncio.wait_for(queue.get(), timeout=timeout)
            if ev is None:
                break
            if ev.get("event_type") == "tool_creation_requested":
                creator.respond(ev["confirmation_id"], True, {"persistence": "sandbox", "extra_dirs": []})
                return ev
    except asyncio.TimeoutError:
        return None


async def _create_tool(creator, bus, name, code=SIMPLE_CODE, test_code=SIMPLE_TEST, language="python"):
    """辅助函数：创建工具并自动批准。"""
    task = asyncio.create_task(
        creator.generate_tool(
            name=name, description=f"{name} 描述", code=code,
            test_code=test_code, language=language,
            param_schema={"type": "object", "properties": {}, "required": []},
        )
    )
    approved = await _approve_tool_creation(bus, creator)
    if approved is None:
        task.cancel()
        return None
    return await asyncio.wait_for(task, timeout=15.0)


# ── 测试 1: 完整创建管线 ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_pipeline():
    """端到端：创建工具 → 确认 → 自测 → 注册 → 事件发布。"""
    bus = EventBus()
    comp = _make_components(bus)
    events = []

    async def _collect():
        q = await bus.subscribe("*")
        while True:
            ev = await q.get()
            if ev is None:
                break
            events.append(ev)

    collector = asyncio.create_task(_collect())
    result = await _create_tool(comp["creator"], bus, "full_test")
    collector.cancel()

    assert result is not None, "管线应完成"
    assert not result.is_error, f"管线应成功: {result.error_message}"

    # 验证注册
    tools = comp["registry"].list_dynamic()
    names = [t.name for t in tools]
    assert any("full_test" in n for n in names), f"工具应已注册: {names}"

    # 验证事件
    ev_types = [e.get("event_type") for e in events]
    assert "tool_creation_requested" in ev_types
    assert "tool_creation_test_result" in ev_types
    assert "tool_created" in ev_types

    await bus.shutdown()


# ── 测试 2: 启用/禁用 ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_enable_disable():
    """禁用工具从 schema 消失，重新启用后恢复。"""
    bus = EventBus()
    comp = _make_components(bus)

    result = await _create_tool(comp["creator"], bus, "toggle")
    assert result is not None and not result.is_error

    tools = comp["registry"].list_dynamic()
    tool = [t for t in tools if "toggle" in t.name][0]
    tid = tool.name

    # 初始启用
    schemas = comp["registry"].get_schemas()
    assert tid in [s["function"]["name"] for s in schemas]

    # 禁用
    comp["registry"].get(tid).enabled = False
    schemas = comp["registry"].get_schemas()
    assert tid not in [s["function"]["name"] for s in schemas]

    # 重新启用
    comp["registry"].get(tid).enabled = True
    schemas = comp["registry"].get_schemas()
    assert tid in [s["function"]["name"] for s in schemas]

    await bus.shutdown()


# ── 测试 3: 删除 ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete():
    """删除后工具从 registry 移除。"""
    bus = EventBus()
    comp = _make_components(bus)

    result = await _create_tool(comp["creator"], bus, "del_me")
    assert result is not None and not result.is_error

    tools = comp["registry"].list_dynamic()
    tool = [t for t in tools if "del_me" in t.name][0]
    tid = tool.name

    assert comp["registry"].get(tid) is not None
    comp["registry"].remove(tid)
    assert comp["registry"].get(tid) is None

    await bus.shutdown()


# ── 测试 4: 工具更新（同名覆盖） ─────────────────────────────────────


@pytest.mark.asyncio
async def test_update():
    """同名工具再次创建 → is_update=True → 代码更新 → tool_updated 事件。"""
    bus = EventBus()
    comp = _make_components(bus)

    # 第一次创建
    result1 = await _create_tool(comp["creator"], bus, "upgrade", code=SIMPLE_CODE, test_code=SIMPLE_TEST)
    assert result1 is not None and not result1.is_error

    # 第二次创建（同名 = 更新）
    events2 = []
    q2 = await bus.subscribe("*")

    async def _collect2():
        while True:
            ev = await q2.get()
            if ev is None:
                break
            events2.append(ev)

    c2 = asyncio.create_task(_collect2())

    task2 = asyncio.create_task(
        comp["creator"].generate_tool(
            name="upgrade", description="版本2", code=UPDATED_CODE,
            test_code=UPDATED_TEST, language="python",
            param_schema={"type": "object", "properties": {}, "required": []},
        )
    )

    # 等待确认请求
    approved = None
    for _ in range(20):
        await asyncio.sleep(0.1)
        for ev in events2:
            if ev.get("event_type") == "tool_creation_requested":
                approved = ev
                break
        if approved:
            break

    assert approved is not None, "应发布 tool_creation_requested"
    assert approved.get("is_update") is True, "应标记 is_update"
    assert approved.get("old_code") == SIMPLE_CODE, "应包含旧代码"

    comp["creator"].respond(approved["confirmation_id"], True, {"persistence": "sandbox"})
    result2 = await asyncio.wait_for(task2, timeout=15.0)
    c2.cancel()

    assert not result2.is_error, f"更新应成功: {result2.error}"

    # 验证代码更新
    tools = comp["registry"].list_dynamic()
    tool = [t for t in tools if "upgrade" in t.name][0]
    assert tool.code == UPDATED_CODE
    assert tool.description == "版本2"

    # 只有一个
    assert sum(1 for t in tools if "upgrade" in t.name) == 1

    # 事件类型
    ev_types = [e.get("event_type") for e in events2]
    assert "tool_updated" in ev_types

    await bus.shutdown()


# ── 测试 5: 持久化与跨会话加载 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_persistence_and_reload():
    """沙箱级工具持久化后，新会话自动加载。"""
    bus1 = EventBus()
    comp1 = _make_components(bus1)

    result = await _create_tool(comp1["creator"], bus1, "keep_me")
    assert result is not None and not result.is_error

    # 验证持久化文件
    persisted = comp1["persistence"].load_sandbox_tools()
    names = [t["tool_name"] for t in persisted if "keep_me" in str(t["tool_name"])]
    assert len(names) >= 1

    await bus1.shutdown()

    # 新会话
    bus2 = EventBus()
    comp2 = _make_components(bus2, session_id="new-session")

    tools = comp2["registry"].list_dynamic()
    loaded = [t for t in tools if "keep_me" in t.name]
    assert len(loaded) == 1
    assert loaded[0].code == SIMPLE_CODE
    assert loaded[0].enabled

    await bus2.shutdown()


# ── 测试 6: list_tools 内置工具 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_tools():
    """list_tools 返回正确工具列表，detail 控制代码可见性。"""
    bus = EventBus()
    comp = _make_components(bus)

    await _create_tool(comp["creator"], bus, "list_a")
    await _create_tool(comp["creator"], bus, "list_b")

    fn = create_list_tools_fn(comp["registry"])

    # 简要模式
    brief = json.loads(await fn(detail=False))
    assert len(brief) >= 2
    for item in brief:
        assert "code" not in item

    # 详细模式
    detail = json.loads(await fn(detail=True))
    assert len(detail) >= 2
    for item in detail:
        assert "code" in item
        assert "permission_level" in item

    await bus.shutdown()


# ── 测试 7: 语法错误拦截 ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_syntax_error():
    """Stage 1 语法检查拦截不合法代码，不发布确认事件。"""
    bus = EventBus()
    comp = _make_components(bus)

    events = []

    async def _collect():
        q = await bus.subscribe("*")
        while True:
            ev = await q.get()
            if ev is None:
                break
            events.append(ev)

    collector = asyncio.create_task(_collect())

    result = await comp["creator"].generate_tool(
        name="bad", description="语法错误",
        code="def broken(:\n    pass",  # 语法错误
        test_code="print('x')", language="python",
        param_schema={"type": "object", "properties": {}, "required": []},
    )

    collector.cancel()
    assert result.is_error
    assert "语法检查失败" in result.error_message

    # 未发布确认事件
    requests = [e for e in events if e.get("event_type") == "tool_creation_requested"]
    assert len(requests) == 0

    await bus.shutdown()


# ── 测试 8: 危险扫描标记 ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_danger_scan():
    """Stage 2 检测危险代码，标记风险但不阻止。"""
    bus = EventBus()
    comp = _make_components(bus)

    task = asyncio.create_task(
        comp["creator"].generate_tool(
            name="risky", description="危险",
            code="import os\ndef main(args=None):\n    os.system('date')\n    return 'ok'",
            test_code="main()", language="python",
            param_schema={"type": "object", "properties": {}, "required": []},
        )
    )

    approved = await _approve_tool_creation(bus, comp["creator"])
    assert approved is not None
    assert len(approved.get("risk_flags", [])) > 0, "os.system 应触发标记"

    result = await asyncio.wait_for(task, timeout=15.0)
    assert not result.is_error, "标记不应阻止创建"

    await bus.shutdown()


# ── 测试 9-11: REST API ───────────────────────────────────────────────


def _setup_api_test(registry):
    """创建带模拟会话的 TestClient，注入 registry。"""
    app = create_app()
    app.state.bus = EventBus()
    app.state.active_sessions = {}
    app.state.session_queues = {}

    mock_creator = MagicMock()
    mock_creator._registry = registry
    app.state.active_sessions["test-session"] = {
        "dynamic_creator": mock_creator,
    }
    return TestClient(app)


def test_api_list():
    """GET /api/tools/ 返回工具列表。"""
    registry = ToolRegistry()
    meta = ToolMetadata(
        name="dynamic-abcd1234-api_test", description="API 测试",
        permission_level=PermissionLevel.MODERATE, timeout=30.0,
        param_schema={}, func_ref=DynamicToolCreator.build_func_ref(SIMPLE_CODE, "python"),
        is_dynamic=True, enabled=True,
        tags=["dynamic", "lang:python", "persist:session"], code=SIMPLE_CODE,
    )
    registry.register_meta(meta, is_dynamic=True)

    client = _setup_api_test(registry)
    resp = client.get("/api/tools/")
    assert resp.status_code == 200
    assert len(resp.json()["tools"]) >= 1


def test_api_enable_disable():
    """POST /api/tools/{name}/enable 和 /disable。"""
    registry = ToolRegistry()
    meta = ToolMetadata(
        name="dynamic-abcd1234-toggle_api", description="开关测试",
        permission_level=PermissionLevel.MODERATE, timeout=30.0,
        param_schema={}, func_ref=DynamicToolCreator.build_func_ref(SIMPLE_CODE, "python"),
        is_dynamic=True, enabled=True,
        tags=["dynamic", "lang:python", "persist:session"], code=SIMPLE_CODE,
    )
    registry.register_meta(meta, is_dynamic=True)

    client = _setup_api_test(registry)

    resp = client.post("/api/tools/dynamic-abcd1234-toggle_api/disable")
    assert resp.status_code == 200
    assert registry.get("dynamic-abcd1234-toggle_api").enabled is False

    resp = client.post("/api/tools/dynamic-abcd1234-toggle_api/enable")
    assert resp.status_code == 200
    assert registry.get("dynamic-abcd1234-toggle_api").enabled is True

    resp = client.post("/api/tools/nonexistent/disable")
    assert resp.status_code == 404


def test_api_delete():
    """POST /api/tools/{name}/delete。"""
    registry = ToolRegistry()
    meta = ToolMetadata(
        name="dynamic-abcd1234-delete_api", description="删除测试",
        permission_level=PermissionLevel.MODERATE, timeout=30.0,
        param_schema={}, func_ref=DynamicToolCreator.build_func_ref(SIMPLE_CODE, "python"),
        is_dynamic=True, enabled=True,
        tags=["dynamic", "lang:python", "persist:session"], code=SIMPLE_CODE,
    )
    registry.register_meta(meta, is_dynamic=True)

    client = _setup_api_test(registry)

    resp = client.post(
        "/api/tools/dynamic-abcd1234-delete_api/delete",
        json={"confirmation": True},
    )
    assert resp.status_code == 200
    assert registry.get("dynamic-abcd1234-delete_api") is None

    resp = client.post(
        "/api/tools/nonexistent/delete",
        json={"confirmation": True},
    )
    assert resp.status_code == 404


# ── 清理 ───────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _cleanup():
    """每个测试后清理持久化文件。"""
    yield
    sandbox_dir = ".sandbox/tools"
    if os.path.isdir(sandbox_dir):
        for name in list(os.listdir(sandbox_dir)):
            path = os.path.join(sandbox_dir, name)
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
