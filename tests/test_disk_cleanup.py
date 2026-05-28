"""磁盘诊断与清理端到端测试（Plan 02-04, BIZ-01）。

验证 :mod:`loopai.tools.disk_tools` 中 4 个 Bash 工具的注册、执行、
安全边界和完整诊断流程。
"""

from __future__ import annotations

import asyncio
import os
import subprocess

import pytest

from loopai.events.bus import EventBus
from loopai.state_machine.guards import PermissionGuard
from loopai.tools.decorator import tool
from loopai.tools.disk_tools import register_disk_tools
from loopai.tools.errors import GuardViolationError
from loopai.tools.executor import ToolExecutor
from loopai.tools.registry import ToolRegistry
from loopai.tools.types import PermissionLevel

SANDBOX = os.environ.get("LOOPAI_TEST_SANDBOX", ".sandbox")


@pytest.fixture(scope="module", autouse=True)
def setup_demo():
    """模块级夹具：运行预设场景脚本，测试结束后清理沙箱。"""
    subprocess.run(["bash", "scripts/setup_demo_scenario.sh", SANDBOX], check=True)
    yield
    subprocess.run(["rm", "-rf", os.path.abspath(SANDBOX)], check=False)


@pytest.fixture
def registry():
    """返回已注册 4 个磁盘工具的 ToolRegistry。"""
    r = ToolRegistry()
    register_disk_tools(r, working_dir=SANDBOX)
    return r


@pytest.fixture
def executor(registry):
    """返回绑定 registry 的 ToolExecutor。"""
    return ToolExecutor(registry)


@pytest.fixture
def event_bus():
    """返回全新的 EventBus 实例（覆盖 conftest.py 中的 fixture）。"""
    return EventBus()


class TestDiskDf:
    """disk_df 工具测试。"""

    @pytest.mark.asyncio
    async def test_df_returns_filesystem_header(self, executor):
        """disk_df 应返回包含 'Filesystem' 列头的输出。"""
        result = await executor.execute("disk.df", {})
        assert not result.is_error, f"df failed: {result.error_message}"
        assert "Filesystem" in result.data


class TestDiskDu:
    """disk_du 工具测试。"""

    @pytest.mark.asyncio
    async def test_du_returns_sandbox_path(self, executor):
        """disk_du 应返回包含沙箱路径和大小信息的输出。"""
        result = await executor.execute("disk.du", {"directory": SANDBOX, "max_depth": 2})
        assert not result.is_error, f"du failed: {result.error_message}"
        assert SANDBOX in result.data

    @pytest.mark.asyncio
    async def test_du_outside_sandbox_returns_error(self, executor):
        """disk_du 的 directory 超出沙箱范围时应返回错误。"""
        result = await executor.execute("disk.du", {"directory": "/etc", "max_depth": 1})
        assert result.is_error
        assert "沙箱" in result.error_message


class TestDiskFind:
    """disk_find 工具测试。"""

    @pytest.mark.asyncio
    async def test_find_large_files(self, executor):
        """disk_find 查找 >10M 文件应返回预设大文件。"""
        result = await executor.execute(
            "disk.find",
            {"directory": SANDBOX, "min_size": "+10M", "file_type": "f"},
        )
        assert not result.is_error, f"find failed: {result.error_message}"
        # 预设场景包含 access.log (200MB)、app.log (50MB) 等大文件
        output = result.data
        assert "access.log" in output or "old_db_backup" in output


class TestDiskRm:
    """disk_rm 工具测试——安全边界和删除行为。"""

    @pytest.mark.asyncio
    async def test_rm_delete_file_in_sandbox(self, executor):
        """disk_rm 应在沙箱内成功删除文件。"""
        target = f"{SANDBOX}/tmp/temp_20260101.tmp"
        assert os.path.exists(target), f"预设文件不存在: {target}"

        result = await executor.execute("disk.rm", {"target": target, "recursive": False})
        assert not result.is_error, f"rm failed: {result.error_message}"
        assert not os.path.exists(target), f"文件应已被删除: {target}"
        assert "已删除" in result.data

    @pytest.mark.asyncio
    async def test_rm_outside_sandbox_raises_guard(self, executor):
        """disk_rm 尝试删除沙箱外的路径应抛出 GuardViolationError。"""
        result = await executor.execute(
            "disk.rm", {"target": "/etc/hosts", "recursive": False}
        )
        assert result.is_error
        assert "沙箱" in result.error_message.lower() or "guard" in result.error_message.lower()


class TestFullFlow:
    """完整流程测试——从诊断到清理的端到端验证。"""

    @pytest.mark.asyncio
    async def test_full_diagnosis_cleanup_flow(self, registry, executor, event_bus):
        """模拟完整的磁盘诊断→定位→分析→确认→清理流程。"""
        # 1. 扫描磁盘
        df_result = await executor.execute("disk.df", {})
        assert not df_result.is_error
        assert "Filesystem" in df_result.data

        # 2. 定位大目录
        du_result = await executor.execute("disk.du", {"directory": SANDBOX, "max_depth": 2})
        assert not du_result.is_error
        assert SANDBOX in du_result.data

        # 3. 筛选大文件
        find_result = await executor.execute(
            "disk.find",
            {"directory": SANDBOX, "min_size": "+10M", "file_type": "f"},
        )
        assert not find_result.is_error

        # 4. 确认后可删除临时文件
        target = f"{SANDBOX}/tmp/temp_20260115.tmp"
        assert os.path.exists(target)
        rm_result = await executor.execute("disk.rm", {"target": target, "recursive": False})
        assert not rm_result.is_error
        assert "已删除" in rm_result.data
        assert not os.path.exists(target)

        # 5. 验证其他大文件仍存在（未被误删）
        assert os.path.exists(f"{SANDBOX}/logs/app.log")
        assert os.path.exists(f"{SANDBOX}/backups/old_db_backup.sql")

    @pytest.mark.asyncio
    async def test_permission_guard_confirms_dangerous(self, registry, event_bus):
        """PermissionGuard 应识别 disk.rm 为 DANGEROUS——无人回应时超时返回。"""
        guard = PermissionGuard(bus=event_bus, confirmation_timeout=0.5)

        session_id = "test-session-timeout"
        tool_name = "disk.rm"
        step_num = 3
        confirmation_id = f"{session_id}_{tool_name}_{step_num}"

        # 后台启动 check
        check_task = asyncio.create_task(guard.check(
            tool_name=tool_name,
            tool_args={"target": f"{SANDBOX}/tmp/temp_20260201.tmp"},
            permission_level=PermissionLevel.DANGEROUS,
            session_id=session_id,
            step_num=step_num,
        ))
        await asyncio.sleep(0)

        # 无人回应——应超时
        should_proceed, action = await check_task

        assert not should_proceed
        assert action == "timeout"

    @pytest.mark.asyncio
    async def test_permission_guard_approve_flow(self, registry, event_bus):
        """用户批准后 PermissionGuard 应允许执行。"""
        guard = PermissionGuard(bus=event_bus, confirmation_timeout=120.0)

        session_id = "test-session-approve"
        tool_name = "disk.rm"
        step_num = 5
        confirmation_id = f"{session_id}_{tool_name}_{step_num}"

        # 后台启动 check()，等它发布事件后再 respond
        check_task = asyncio.create_task(guard.check(
            tool_name=tool_name,
            tool_args={"target": f"{SANDBOX}/tmp/temp_20260201.tmp"},
            permission_level=PermissionLevel.DANGEROUS,
            session_id=session_id,
            step_num=step_num,
        ))

        # 给 check() 一个事件循环周期来发布 confirmation_required
        await asyncio.sleep(0)

        # 模拟用户批准
        guard.respond(confirmation_id, approved=True)

        should_proceed, action = await check_task

        assert should_proceed
        assert action == "allow"

    @pytest.mark.asyncio
    async def test_permission_guard_deny_flow(self, registry, event_bus):
        """用户拒绝后 PermissionGuard 应阻止执行。"""
        guard = PermissionGuard(bus=event_bus, confirmation_timeout=120.0)

        session_id = "test-session-deny"
        tool_name = "disk.rm"
        step_num = 7
        confirmation_id = f"{session_id}_{tool_name}_{step_num}"

        check_task = asyncio.create_task(guard.check(
            tool_name=tool_name,
            tool_args={"target": f"{SANDBOX}/tmp/temp_20260201.tmp"},
            permission_level=PermissionLevel.DANGEROUS,
            session_id=session_id,
            step_num=step_num,
        ))
        await asyncio.sleep(0)

        # 模拟用户拒绝
        guard.respond(confirmation_id, approved=False)

        should_proceed, action = await check_task

        assert not should_proceed
        assert action == "user_denied"

    @pytest.mark.asyncio
    async def test_safe_tool_no_confirmation(self, registry, event_bus):
        """SAFE 权限级别的工具应直接允许，无需确认。"""
        guard = PermissionGuard(bus=event_bus, confirmation_timeout=120.0)

        should_proceed, action = await guard.check(
            tool_name="disk.df",
            tool_args={},
            permission_level=PermissionLevel.SAFE,
            session_id="test-session",
            step_num=1,
        )

        assert should_proceed
        assert action == "allow"

    @pytest.mark.asyncio
    async def test_user_rejects_nginx_log(self, registry, executor, event_bus):
        """模拟用户拒绝删除 nginx 日志——文件应保留。"""
        target = f"{SANDBOX}/logs/nginx/access.log"
        assert os.path.exists(target), f"预设文件不存在: {target}"

        guard = PermissionGuard(bus=event_bus, confirmation_timeout=120.0)
        session_id = "test-reject-nginx"
        tool_name = "disk.rm"
        step_num = 4
        confirmation_id = f"{session_id}_{tool_name}_{step_num}"

        # 后台启动 check()，模拟用户在确认面板选择拒绝
        check_task = asyncio.create_task(guard.check(
            tool_name=tool_name,
            tool_args={"target": target},
            permission_level=PermissionLevel.DANGEROUS,
            session_id=session_id,
            step_num=step_num,
        ))
        await asyncio.sleep(0)
        guard.respond(confirmation_id, approved=False)

        should_proceed, action = await check_task

        assert not should_proceed
        assert action == "user_denied"
        # 文件未被删除
        assert os.path.exists(target)
