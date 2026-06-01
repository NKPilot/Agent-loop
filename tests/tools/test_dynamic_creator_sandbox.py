"""D-06 集成测试套件 — DynamicToolCreator 与加固 SandboxExecutor 集成验证。

验证 DynamicToolCreator._stage4_self_test() 在加固后的 SandboxExecutor
中执行自测，违规事件通过 EventBus 正确发布。

测试覆盖:
    - 网络违规检测（unshare --net 阻断）
    - 超时事件发布
    - 路径白名单校验（extra_dirs 违规）
    - func_ref 独立沙箱创建

决策引用:
    D-06: 自测在加固后的 SandboxExecutor 中运行，违规可被检测和审计
    DYN-13: 网络命名空间隔离——unshare --net 阻断所有网络连接
    DYN-14: 路径白名单校验——realpath + startswith 包含性检查
"""

import asyncio
import os
import sys
import time

import pytest

from loopai.events.bus import EventBus
from loopai.tools.dynamic_creator import DynamicToolCreator
from loopai.tools.registry import ToolRegistry
from loopai.tools.sandbox import SandboxExecutor
from loopai.tools.tool_persistence import ToolPersistenceManager


# ── 工具函数 ────────────────────────────────────────────────────────────────


def _is_linux() -> bool:
    """当前平台是否为 Linux。"""
    return sys.platform == "linux"


# ── 辅助：创建带 EventBus 的测试组件 ─────────────────────────────────────────


def _make_creator(bus, sandbox_timeout=15.0):
    """创建 DynamicToolCreator 实例（注入加固 SandboxExecutor）。"""
    registry = ToolRegistry()
    sandbox = SandboxExecutor(timeout=sandbox_timeout, event_bus=bus)
    persistence = ToolPersistenceManager()

    return DynamicToolCreator(
        registry=registry,
        bus=bus,
        session_id="test-session-sandbox",
        sandbox=sandbox,
        persistence=persistence,
    )


# ── 任务 1.1: 网络违规检测 ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stage4_uses_hardened_sandbox():
    """D-06: 自测在加固沙箱中运行——网络违规被检测并发布事件。

    验证 _stage4_self_test 中 SandboxExecutor 的网络隔离生效：
    自测代码尝试 UDP 连接，unshare --net 阻断连接并发布
    sandbox_violation 事件到 EventBus。
    """
    bus = EventBus()
    creator = _make_creator(bus, sandbox_timeout=15.0)

    # 订阅 sandbox_violation 事件
    q = await bus.subscribe("sandbox_violation")

    # 工具代码：简单函数
    tool_code = "def test_func():\n    return 'ok'"

    # 自测代码：尝试网络连接（在 Linux 上被 unshare --net 阻断）
    # 注意：不捕获异常，让 OSError 导致子进程非零退出码，
    # 以便 SandboxExecutor._classify_violation() 检测到 network_attempt
    test_code = """
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.settimeout(3)
s.connect(("8.8.8.8", 53))
print("SHOULD_NOT_REACH")
"""

    result = await creator._stage4_self_test(
        name="test_net_tool",
        code=tool_code,
        test_code=test_code,
        language="python",
        extra_dirs=[],
    )

    # 自测结果：代码可能 passed（异常被捕获）或 failed（异常未被捕获）
    # 关键验证是 EventBus 上的审计事件
    assert result is not None, "_stage4_self_test 在沙箱违规时应返回 ToolResult"

    if _is_linux():
        # 验证 sandbox_violation 事件已发布到总线
        violation_found = False
        while True:
            try:
                event = q.get_nowait()
                if event is None:
                    break  # 哨兵
                if event.get("event_type") == "sandbox_violation":
                    if event.get("violation_type") == "network_attempt":
                        violation_found = True
                        detail = event.get("detail", "")
                        assert "unshare" in detail.lower(), (
                            f"事件详情应提及 unshare 网络隔离，实际: {detail}"
                        )
                        break
            except asyncio.QueueEmpty:
                break

        assert violation_found, (
            "Linux 平台上应检测到 sandbox_violation/network_attempt 事件"
        )
    else:
        # 非 Linux 平台：无 unshare，网络连接可能成功
        # 自测代码捕获异常，工具可能 passed
        pass


# ── 任务 1.2: 超时事件 ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stage4_timeout_publishes_event():
    """D-06: 自测代码超时时发布 sandbox_timeout 事件。

    自测代码包含长时间 sleep，SandboxExecutor 超时后
    发布 sandbox_timeout 事件到 EventBus。
    """
    bus = EventBus()
    creator = _make_creator(bus, sandbox_timeout=2.0)

    # 订阅 sandbox_timeout 事件
    q = await bus.subscribe("sandbox_timeout")

    # 工具代码
    tool_code = "def test_func():\n    return 'ok'"

    # 自测代码：sleep 超过超时时间
    test_code = """
import time
time.sleep(60)
"""

    result = await creator._stage4_self_test(
        name="test_timeout_tool",
        code=tool_code,
        test_code=test_code,
        language="python",
        extra_dirs=[],
    )

    # 自测应返回错误（超时导致 failed）
    assert result is not None, "_stage4_self_test 超时时应返回 ToolResult"

    # 验证 sandbox_timeout 事件已发布
    timeout_found = False
    while True:
        try:
            event = q.get_nowait()
            if event is None:
                break
            if event.get("event_type") == "sandbox_timeout":
                timeout_found = True
                assert event.get("timeout_seconds") == 2.0, (
                    f"超时秒数应为 2.0，实际: {event.get('timeout_seconds')}"
                )
                break
        except asyncio.QueueEmpty:
            break

    assert timeout_found, "应检测到 sandbox_timeout 事件"


# ── 任务 1.3: 路径校验 ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stage4_path_validation():
    """D-06: extra_dirs 路径违规被检测并发布 sandbox_violation 事件。

    向 _stage4_self_test 传入 extra_dirs=["/etc"]，SandboxExecutor
    的路径校验拒绝该路径，发布 sandbox_violation 事件。
    """
    bus = EventBus()
    creator = _make_creator(bus, sandbox_timeout=10.0)

    # 订阅 sandbox_violation 事件
    q = await bus.subscribe("sandbox_violation")

    # 工具代码
    tool_code = "def test_func():\n    return 'ok'"

    # 简单自测代码
    test_code = "print('hello')"

    result = await creator._stage4_self_test(
        name="test_path_tool",
        code=tool_code,
        test_code=test_code,
        language="python",
        extra_dirs=["/etc"],
    )

    # execute() 应在路径校验阶段失败，状态应为 "failed"
    assert result is not None, "_stage4_self_test 路径违规时应返回 ToolResult"

    # 验证 sandbox_violation/路径违规事件已发布
    violation_found = False
    while True:
        try:
            event = q.get_nowait()
            if event is None:
                break
            if event.get("event_type") == "sandbox_violation":
                vtype = event.get("violation_type", "")
                if vtype in ("path_escape", "sensitive_path"):
                    violation_found = True
                    break
        except asyncio.QueueEmpty:
            break

    assert violation_found, "应检测到 sandbox_violation 路径违规事件"


# ── 任务 1.4: func_ref 独立沙箱 ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_func_ref_creates_independent_sandbox():
    """D-06: _make_func_ref 闭包创建独立 SandboxExecutor(event_bus=None)。

    验证工具运行时执行使用独立的沙箱实例，不依赖 DynamicToolCreator 的
    EventBus。工具运行时沙箱与自测阶段沙箱隔离。
    """
    bus = EventBus()
    registry = ToolRegistry()
    sandbox = SandboxExecutor(timeout=30.0, event_bus=bus)
    persistence = ToolPersistenceManager()
    creator = DynamicToolCreator(registry, bus, "test-func-ref", sandbox, persistence)

    # 创建工具函数（通过内部 _make_func_ref）
    func = creator._make_func_ref(
        "dynamic.deadbeef_test_func",
        "print('hello from sandbox')",
        "python",
        {},
    )

    # 执行工具函数——应在独立沙箱中运行
    result = await func()

    # 简单工具返回 stdout 输出
    assert "hello from sandbox" in result, (
        f"工具输出应包含 'hello from sandbox'，实际: {result}"
    )

    # 验证工具运行时的 SandboxExecutor 不发布事件到外部 EventBus
    # （func_ref 创建的 SandboxExecutor(event_bus=None) 不持有 EventBus）
    tool_events = bus.replay()
    # 工具运行时不应发布 sandbox 事件（event_bus=None）
    sandbox_events = [
        e
        for e in tool_events
        if e.get("event_type", "").startswith("sandbox_")
    ]
    # func_ref 创建的 SandboxExecutor 没有 event_bus，所以不应有 sandbox 事件
    assert len(sandbox_events) == 0, (
        f"func_ref 创建的独立 SandboxExecutor(event_bus=None)"
        f" 不应发布沙箱事件，实际发布: {sandbox_events}"
    )
