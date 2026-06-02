""":mod:`loopai.tools.dynamic_creator` — 动态工具创建器，实现 6 阶段串行管道。

DynamicToolCreator 提供完整的 Agent 动态工具创建流程：
语法检查 → 危险扫描 → 用户确认暂停 → 沙箱自测 → 持久化 → 注册。

generate_tool 是 @tool 装饰的内置工具，Agent 可通过 ToolExecutor 调用它提交代码。
用户确认通过 EventBus + asyncio.Event 暂停，无超时。

决策引用:
    D-04: 实例注册表 + 命名空间支持
    D-05: ToolResult 标准化包装
    D-06: 确认后立即注册到内存，沙箱级/项目级在首次执行成功后才写文件
    D-08: 动态工具永不可获得 PermissionLevel.SAFE，最低为 MODERATE
    D-09: dynamic.{sha256_hash[:8]}_{name} 命名格式
    Pitfall 3: func_ref 不持有 DynamicToolCreator 或 Session 引用
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from loopai.events.bus import EventBus
from loopai.tools.decorator import tool
from loopai.tools.registry import ToolRegistry
from loopai.tools.sandbox import DangerousModuleScanner, SandboxExecutor
from loopai.tools.tool_persistence import ToolPersistenceManager
from loopai.tools.types import PermissionLevel, ToolMetadata, ToolResult

__all__ = ["DynamicToolCreator", "create_generate_tool_fn", "create_list_tools_fn"]


class DynamicToolCreator:
    """动态工具创建器，实现 6 阶段串行管道。

    管道阶段:
        0. 计算 tool_id + 基本校验
        1. 语法检查（ast.parse / bash -n）
        2. 危险扫描（AST 扫描 / Bash 正则）
        3. 用户确认（EventBus + asyncio.Event 暂停，无超时）
        4. 沙箱自测（子进程隔离执行）
        5. 持久化（会话级/沙箱级/项目级）
        6. 注册（register_meta is_dynamic=True）

    Attributes:
        _registry: 工具注册表实例。
        _bus: 事件总线实例。
        _session_id: 当前会话 ID。
        _sandbox: 沙箱执行器实例。
        _persistence: 持久化管理器实例。
        _pending_confirmations: 待确认请求映射（confirmation_id → (Event, config)）。
    """

    def __init__(
        self,
        registry: ToolRegistry,
        bus: EventBus,
        session_id: str,
        sandbox: SandboxExecutor,
        persistence: ToolPersistenceManager,
    ) -> None:
        """初始化动态工具创建器。

        Args:
            registry: 工具注册表，用于注册新创建的工具。
            bus: 事件总线，用于发布工具创建相关事件。
            session_id: 当前 Agent 会话 ID。
            sandbox: 沙箱执行器，用于自测阶段隔离执行代码。
            persistence: 持久化管理器，用于保存工具代码和元数据。
        """
        self._registry = registry
        self._bus = bus
        self._session_id = session_id
        self._sandbox = sandbox
        self._persistence = persistence
        self._pending_confirmations: dict[str, tuple[asyncio.Event, dict | None]] = {}

        # D-06: 确保自测阶段的 SandboxExecutor 使用加固沙箱并发布审计事件
        # 当外部调用者未传入 event_bus 时，自动关联 DynamicToolCreator 的 EventBus
        if self._sandbox._event_bus is None:
            self._sandbox._event_bus = self._bus

    # ── 核心方法：6 阶段管道 ────────────────────────────────────────────

    async def generate_tool(
        self,
        name: str,
        description: str,
        code: str,
        test_code: str,
        language: str,
        param_schema: dict,
    ) -> ToolResult:
        """执行 6 阶段动态工具创建管道。

        Args:
            name: 工具名称（不含 dynamic. 前缀，系统自动添加）。
            description: 工具描述，注入到 ToolMetadata。
            code: 工具源代码（Python 或 Bash）。
            test_code: Agent 编写的自测代码。
            language: 代码语言，``"python"`` 或 ``"bash"``。
            param_schema: 工具参数的 JSON Schema 字典。

        Returns:
            ToolResult.success 表示创建成功，ToolResult.error 表示
            某阶段失败（含结构化错误信息供 Agent 修正）。
        """
        overall_start = datetime.now(timezone.utc)

        # ── Stage 0: 计算 tool_id 和基本校验 ──
        stage0_result = self._stage0_validate(name, code, language, param_schema)
        if stage0_result is not None:
            return stage0_result

        tool_id = f"dynamic.{hashlib.sha256(code.encode()).hexdigest()[:8]}_{name}"

        # D-08/DYN-17: 检测是否为已有工具的更新版本
        existing_meta = self._registry.get(tool_id)
        is_update = existing_meta is not None
        old_code = existing_meta.code if existing_meta else ""

        # ── Stage 1: 语法检查 ──
        stage1_result = await self._stage1_syntax_check(code, language)
        if stage1_result is not None:
            return stage1_result

        # ── Stage 2: 危险扫描 ──
        risk_flags = self._stage2_danger_scan(code, language)

        # ── Stage 3: 用户确认（EventBus 暂停，无超时） ──
        persistence_level, extra_dirs, config = await self._stage3_user_confirmation(
            name=name,
            tool_id=tool_id,
            description=description,
            code=code,
            test_code=test_code,
            language=language,
            param_schema=param_schema,
            risk_flags=risk_flags,
            is_update=is_update,
            old_code=old_code,
        )
        if persistence_level is None:
            # 用户拒绝
            duration_ms = (datetime.now(timezone.utc) - overall_start).total_seconds() * 1000
            return ToolResult.error(
                config.get("reject_reason", "用户拒绝创建工具") if config else "用户拒绝创建工具",
                duration_ms,
            )

        # ── Stage 4: 沙箱自测 ──
        stage4_result = await self._stage4_self_test(
            name=name,
            code=code,
            test_code=test_code,
            language=language,
            extra_dirs=extra_dirs,
        )
        if stage4_result is not None:
            return stage4_result

        # ── Stage 5+6: 持久化 + 注册 ──
        stage56_result = await self._stage56_persist_and_register(
            name=name,
            tool_id=tool_id,
            description=description,
            code=code,
            language=language,
            param_schema=param_schema,
            persistence_level=persistence_level,
            config=config,
            is_update=is_update,
        )

        duration_ms = (datetime.now(timezone.utc) - overall_start).total_seconds() * 1000
        if stage56_result is not None:
            return stage56_result

        return ToolResult.success(
            data=f"工具 {tool_id} 已创建并注册（{persistence_level}级持久化）",
            duration_ms=duration_ms,
        )

    # ── Stage 0: 基本校验 ───────────────────────────────────────────────

    def _stage0_validate(
        self,
        name: str,
        code: str,
        language: str,
        param_schema: dict,
    ) -> ToolResult | None:
        """Stage 0: 校验输入参数合法性。

        Returns:
            ToolResult.error 若校验失败，None 表示通过。
        """
        # 校验 language
        if language not in ("python", "bash"):
            return ToolResult.error(
                f"不支持的语言类型: {language}，仅支持 'python' 或 'bash'",
                0,
            )

        # 校验 name 不为空
        if not name or not name.strip():
            return ToolResult.error("工具名称不能为空", 0)

        # 校验 code 不为空
        if not code or not code.strip():
            return ToolResult.error("工具代码不能为空", 0)

        # 校验 param_schema 是合法 JSON
        try:
            json.loads(json.dumps(param_schema))
        except (TypeError, ValueError) as e:
            return ToolResult.error(f"param_schema 不是合法的 JSON: {e}", 0)

        return None

    # ── Stage 1: 语法检查 ───────────────────────────────────────────────

    async def _stage1_syntax_check(
        self,
        code: str,
        language: str,
    ) -> ToolResult | None:
        """Stage 1: 语法检查。

        Python 使用 ast.parse，Bash 使用 bash -n。

        Returns:
            ToolResult.error 若语法错误，None 表示通过。
        """
        import ast as ast_module

        if language == "python":
            try:
                ast_module.parse(code)
            except SyntaxError as e:
                return ToolResult.error(
                    f"语法检查失败: 第{e.lineno}行 — {e.msg}",
                    0,
                )
        elif language == "bash":
            try:
                result = subprocess.run(
                    ["bash", "-n"],
                    input=code,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode != 0:
                    error_msg = result.stderr.strip() if result.stderr else "未知语法错误"
                    return ToolResult.error(
                        f"Bash 语法检查失败: {error_msg}",
                        0,
                    )
            except subprocess.TimeoutExpired:
                return ToolResult.error(
                    "Bash 语法检查超时（10秒）",
                    0,
                )
            except FileNotFoundError:
                return ToolResult.error(
                    "Bash 语法检查失败: bash 不可用",
                    0,
                )

        return None

    # ── Stage 2: 危险扫描 ───────────────────────────────────────────────

    def _stage2_danger_scan(
        self,
        code: str,
        language: str,
    ) -> list[dict]:
        """Stage 2: 危险扫描。

        Python 使用 DangerousModuleScanner，Bash 使用正则匹配。
        扫描结果不阻止流程——由用户决定是否批准。

        Returns:
            风险标记列表，每项包含 type/name/message/severity/line。
        """
        if language == "python":
            scanner = DangerousModuleScanner()
            return scanner.scan(code)
        elif language == "bash":
            return self._scan_bash_danger(code)
        return []

    def _scan_bash_danger(self, code: str) -> list[dict]:
        """扫描 Bash 代码中的危险命令模式。

        使用正则表达式检测已知危险模式，返回结构化风险列表。

        Args:
            code: Bash 源代码字符串。

        Returns:
            风险标记列表。
        """
        # 危险模式定义: (正则, 名称, 消息, 严重级别)
        danger_patterns: list[tuple[str, str, str, str]] = [
            (r'rm\s+-rf\s+/', 'rm -rf /', 'rm -rf / 会递归删除根目录所有文件，导致系统不可用', 'high'),
            (r'dd\s+if=', 'dd 命令', 'dd 命令可直接读写原始设备，存在数据破坏风险', 'high'),
            (r'\bmkfs\b', 'mkfs 命令', 'mkfs 命令可格式化文件系统，存在数据破坏风险', 'high'),
            (r':\(\)\s*\{', 'Fork 炸弹', '检测到可能的 Fork 炸弹模式，可使系统资源耗尽', 'high'),
            (r'curl.*\|\s*(ba)?sh', 'curl | sh 模式', 'curl 管道 sh 可执行任意远程脚本，存在代码注入风险', 'high'),
            (r'wget.*\|\s*(ba)?sh', 'wget | sh 模式', 'wget 管道 sh 可执行任意远程脚本，存在代码注入风险', 'high'),
            (r'/dev/sd[a-z]', '磁盘设备操作', '直接操作磁盘设备（/dev/sd*）存在数据破坏风险', 'high'),
            (r'chmod\s+777\s+/', 'chmod 777 /', 'chmod 777 / 会使整个文件系统可写，存在安全风险', 'high'),
            (r'>\s*/dev/sd[a-z]', '写入磁盘设备', '重定向输出到磁盘设备会覆写分区表或数据', 'high'),
            (r'\bwget\b.*\b-O\b', 'wget -O', 'wget -O 可将远程文件保存到本地任意路径', 'medium'),
            (r'\bcurl\b.*-o\b', 'curl -o', 'curl -o 可将远程文件保存到本地任意路径', 'medium'),
        ]

        results: list[dict] = []
        for pattern, name, message, severity in danger_patterns:
            for match in re.finditer(pattern, code):
                line_no = code[:match.start()].count('\n') + 1
                results.append({
                    "type": "dangerous_command",
                    "name": name,
                    "message": message,
                    "severity": severity,
                    "line": line_no,
                })

        return results

    # ── Stage 3: 用户确认 ───────────────────────────────────────────────

    async def _stage3_user_confirmation(
        self,
        name: str,
        tool_id: str,
        description: str,
        code: str,
        test_code: str,
        language: str,
        param_schema: dict,
        risk_flags: list[dict],
        is_update: bool = False,
        old_code: str = "",
    ) -> tuple[str | None, list[str], dict | None]:
        """Stage 3: 用户确认（EventBus 暂停，无超时）。

        通过 EventBus 发布 tool_creation_requested 事件，然后
        使用 asyncio.Event 阻塞等待用户通过 API 端点响应。
        当检测到已有工具的更新时，事件 payload 包含 is_update 和 old_code 字段。

        Args:
            name: 工具名称。
            tool_id: 计算出的完整 tool_id。
            description: 工具描述。
            code: 工具源代码。
            test_code: 自测代码。
            language: 代码语言。
            param_schema: 参数 JSON Schema。
            risk_flags: Stage 2 的风险扫描结果。
            is_update: 是否为已有工具的更新版本。
            old_code: 已有工具的旧源代码（更新时）。

        Returns:
            (persistence_level, extra_dirs, config) 元组。
            若用户拒绝，persistence_level 为 None。
        """
        confirmation_id = str(uuid.uuid4())[:8]
        wait_event = asyncio.Event()
        self._pending_confirmations[confirmation_id] = (wait_event, None)

        # 发布确认请求事件
        await self._bus.publish("tool_creation_requested", {
            "event_type": "tool_creation_requested",
            "session_id": self._session_id,
            "step_num": 0,
            "confirmation_id": confirmation_id,
            "tool_name": name,
            "tool_id": tool_id,
            "description": description,
            "code": code,
            "language": language,
            "risk_flags": risk_flags,
            "test_code": test_code,
            "param_schema": param_schema,
            "is_update": is_update,
            "old_code": old_code,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # 阻塞等待用户响应（D-04: 无超时）
        await wait_event.wait()

        # 获取响应
        _, config = self._pending_confirmations.pop(confirmation_id, (None, None))

        if config is None or not config.get("approved"):
            return None, [], config

        persistence_level = config.get("persistence", "session")
        extra_dirs = config.get("extra_dirs", [])

        return persistence_level, extra_dirs, config

    # ── 确认响应 ───────────────────────────────────────────────────────

    def respond(
        self,
        confirmation_id: str,
        approved: bool,
        config: dict | None = None,
    ) -> bool:
        """由 API 端点调用的确认响应方法。

        查找 _pending_confirmations 中的等待事件，存储用户配置，
        并通过 event.set() 唤醒阻塞的 generate_tool 协程。

        Args:
            confirmation_id: Stage 3 生成的确认 ID。
            approved: 用户是否批准。
            config: 用户配置字典，包含 persistence、extra_dirs 等。

        Returns:
            True 若成功处理，False 若 confirmation_id 无效或已过期。
        """
        if config is None:
            config = {}

        config["approved"] = approved

        entry = self._pending_confirmations.get(confirmation_id)
        if entry is None:
            return False

        wait_event, _ = entry
        self._pending_confirmations[confirmation_id] = (wait_event, config)
        wait_event.set()
        return True

    # ── Stage 4: 沙箱自测 ───────────────────────────────────────────────

    async def _stage4_self_test(
        self,
        name: str,
        code: str,
        test_code: str,
        language: str,
        extra_dirs: list[str],
    ) -> ToolResult | None:
        """Stage 4: 沙箱自测。

        合并工具代码和自测代码，在隔离沙箱中执行验证。

        Returns:
            ToolResult.error 若自测失败，None 表示通过。
        """
        # 合并代码和自测代码
        if language == "python":
            full_code = code + "\n\n# --- Self-Test ---\n" + test_code
        else:
            full_code = code + "\n\n# --- Self-Test ---\n" + test_code

        # 创建临时工作目录（必须在 .sandbox 内以满足加固沙箱的路径白名单）
        os.makedirs(".sandbox", exist_ok=True)
        sandbox_dir = tempfile.mkdtemp(prefix="tool_test_", dir=".sandbox")

        try:
            test_result = await self._sandbox.execute(
                full_code,
                language,
                working_dir=sandbox_dir,
                extra_dirs=extra_dirs,
            )

            # 发布自测结果事件
            await self._bus.publish("tool_creation_test_result", {
                "event_type": "tool_creation_test_result",
                "session_id": self._session_id,
                "tool_name": name,
                "status": test_result["status"],
                "output": test_result.get("output", ""),
                "error": test_result.get("error"),
                "duration_ms": test_result.get("duration_ms", 0),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

            if test_result["status"] != "passed":
                error_detail = test_result.get("error") or test_result.get("output", "未知错误")
                return ToolResult.error(
                    f"自测失败（{test_result['status']}）: {error_detail}",
                    test_result.get("duration_ms", 0),
                )

        finally:
            # 清理临时目录
            try:
                import shutil
                shutil.rmtree(sandbox_dir)
            except OSError:
                pass

        return None

    # ── Stage 5+6: 持久化 + 注册 ────────────────────────────────────────

    async def _stage56_persist_and_register(
        self,
        name: str,
        tool_id: str,
        description: str,
        code: str,
        language: str,
        param_schema: dict,
        persistence_level: str,
        config: dict | None,
        is_update: bool = False,
    ) -> ToolResult | None:
        """Stage 5+6: 持久化并注册动态工具。

        D-06: 确认后立即注册到内存（register_meta is_dynamic=True），
        沙箱级/项目级在注册后写文件。

        当 is_update=True 时，更新现有工具的代码/描述/param_schema，
        不修改持久化级别（per D-09/T-10-06）。

        Returns:
            ToolResult.error 若注册失败（如名称冲突），None 表示成功。
        """
        if config is None:
            config = {}

        # 构建 tags
        tags = ["dynamic", f"lang:{language}"]
        if persistence_level != "session":
            tags.append(f"persist:{persistence_level}")

        # 构造 ToolMetadata
        meta = ToolMetadata(
            name=tool_id,
            description=description,
            permission_level=PermissionLevel.MODERATE,
            timeout=30.0,
            param_schema=param_schema,
            func_ref=self._make_func_ref(tool_id, code, language, config),
            is_dynamic=True,
            enabled=True,
            code=code,
            tags=tags,
        )

        # 注册到内存（D-06: 确认后立即注册）
        if is_update:
            # D-08/DYN-17: 更新已有工具——原地更新，不重新注册
            existing = self._registry.get(tool_id)
            if existing:
                existing.code = code
                existing.description = description
                existing.param_schema = param_schema
                existing.func_ref = self._make_func_ref(tool_id, code, language, config)
                # 不修改 tags（保留持久化级别等信息 per D-09/T-10-06）
        else:
            try:
                self._registry.register_meta(meta, is_dynamic=True)
            except ValueError as e:
                return ToolResult.error(f"工具注册失败: {e}", 0)

        # 持久化（D-06: 沙箱/项目级写文件）
        if persistence_level != "session":
            try:
                meta_dict = {
                    "name": name,
                    "description": description,
                    "language": language,
                    "param_schema": param_schema,
                    "persistence": persistence_level,
                }
                self._persistence.save(name, code, language, persistence_level, meta_dict)
            except Exception:
                # 持久化失败不阻塞——工具已注册到内存
                pass

        # 发布工具创建或更新事件
        event_name = "tool_updated" if is_update else "tool_created"
        await self._bus.publish(event_name, {
            "event_type": event_name,
            "session_id": self._session_id,
            "step_num": 0,
            "tool_name": name,
            "tool_id": tool_id,
            "persistence": persistence_level,
            "is_update": is_update,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        return None

    # ── func_ref 构造（Pitfall 3 防护）──────────────────────────────────

    @staticmethod
    def build_func_ref(code: str, language: str) -> Callable:
        """构造动态工具的可调用对象（func_ref），独立于 DynamicToolCreator 实例。

        此静态方法供启动加载（create_agent_components）用于从持久化代码重建 func_ref。
        与 _make_func_ref 行为一致，但不捕获 tool_id 和 config。

        Args:
            code: 工具源代码。
            language: 代码语言（``"python"`` 或 ``"bash"``）。

        Returns:
            async 函数，接受 **kwargs，返回 str（子进程 stdout）。
        """

        async def _dynamic_tool_func(**kwargs: Any) -> str:
            """动态工具的执行体——每次调用创建独立 SandboxExecutor。"""
            sandbox = SandboxExecutor(timeout=30.0, event_bus=None)
            os.makedirs(".sandbox", exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="tool_run_", dir=".sandbox") as tmpdir:
                args_path = os.path.join(tmpdir, "args.json")
                with open(args_path, "w", encoding="utf-8") as f:
                    json.dump(kwargs, f, ensure_ascii=False)

                if language == "python":
                    wrapper = (
                        "# -*- coding: utf-8 -*-\n"
                        "import json, sys, os\n"
                        f"os.chdir({tmpdir!r})\n"
                        f"_args_file = {args_path!r}\n"
                        "with open(_args_file, 'r', encoding='utf-8') as _f:\n"
                        "    _tool_args = json.load(_f)\n"
                        f"{code}\n"
                    )
                else:
                    wrapper = (
                        f'export TOOL_ARGS_FILE="{args_path}"\n'
                        f'export TOOL_RUN_DIR="{tmpdir}"\n'
                        f'cd "{tmpdir}"\n'
                        f'{code}\n'
                    )

                result = await sandbox.execute(wrapper, language, working_dir=tmpdir)

                if result["status"] == "passed":
                    return result["output"]
                else:
                    error_msg = result.get("error", "未知错误")
                    return f"[工具执行失败] {error_msg}"

        return _dynamic_tool_func

    def _make_func_ref(
        self,
        tool_id: str,
        code: str,
        language: str,
        config: dict,
    ) -> Callable:
        """构造动态工具的可调用对象（func_ref）。

        func_ref 是独立的 async 函数，不捕获 self/Session 引用
        （Pitfall 3 防护）。Phase 8 基础版本：内部创建临时
        SandboxExecutor 实例执行。

        委托给 build_func_ref 静态方法，保留 tool_id 和 config 参数
        以保证向后兼容。

        Args:
            tool_id: 工具完整 ID（如 dynamic.a1b2c3d4_disk_check）。
            code: 工具源代码。
            language: 代码语言。
            config: 用户确认配置。

        Returns:
            async 函数，接受 **kwargs，返回 str（子进程 stdout）。
        """
        return self.build_func_ref(code, language)


# ── generate_tool 内置工具工厂函数 ─────────────────────────────────────


def create_generate_tool_fn(creator: DynamicToolCreator) -> Callable:
    """创建 generate_tool 内置工具的 @tool 装饰函数。

    返回的 callable 将被注册到 ToolRegistry（在 Plan 08-04 中完成），
    Agent 可通过 ToolExecutor 调用它提交 Python/Bash 代码创建新的动态工具。

    Args:
        creator: DynamicToolCreator 实例，提供 6 阶段管道。

    Returns:
        @tool 装饰后的 async 函数，带有 __tool_meta__ 属性。
    """

    async def _generate_tool_impl(
        name: str,
        description: str,
        code: str,
        test_code: str,
        language: str,
        param_schema: dict,
    ) -> ToolResult:
        """Agent 调用此工具提交 Python/Bash 代码以创建新的动态工具。

        系统会自动进行语法检查、安全扫描，然后弹出确认窗口供用户审批。
        通过审批和自测后，工具将被注册到系统中。

        Args:
            name: 工具名称（不含 dynamic. 前缀）。
            description: 工具功能描述。
            code: 工具源代码（Python 或 Bash）。
            test_code: Agent 编写的自测验证代码。
            language: 代码语言，``"python"`` 或 ``"bash"``。
            param_schema: 工具参数的 JSON Schema 字典。
        """
        return await creator.generate_tool(
            name=name,
            description=description,
            code=code,
            test_code=test_code,
            language=language,
            param_schema=param_schema,
        )

    # 用 @tool 装饰器包装
    generate_tool_fn = tool(
        name="generate_tool",
        description=(
            "提交 Python 或 Bash 代码创建新的动态工具。"
            "系统会自动进行语法检查、安全扫描，然后弹出确认窗口供用户审批。"
            "通过审批和自测后，工具将被注册到系统中。"
        ),
        permission_level=PermissionLevel.MODERATE,
        timeout=120.0,
        tags=["dynamic", "meta"],
    )(_generate_tool_impl)

    return generate_tool_fn


def create_list_tools_fn(registry: ToolRegistry) -> Callable:
    """创建 list_tools 内置工具工厂。

    返回的 callable 将被注册到 ToolRegistry，Agent 可通过 ToolExecutor
    调用它查询所有已注册动态工具的详细信息（含源代码和参数 Schema）。

    决策引用:
        DYN-23: Agent 可通过 list_tools 内置工具查询动态工具详细信息

    Args:
        registry: 工具注册表实例，用于查询动态工具列表。

    Returns:
        @tool 装饰后的 async 函数，带有 __tool_meta__ 属性。
    """

    async def _list_tools_impl(detail: bool = False) -> str:
        """列出所有可用动态工具及其详细信息。

        Args:
            detail: 若为 True，返回包含源代码和权限级别的完整信息。

        Returns:
            JSON 字符串格式的工具列表。
        """
        tools = registry.list_dynamic()
        result = []
        for meta in tools:
            info = {
                "name": meta.name,
                "description": meta.description,
                "enabled": meta.enabled,
                "tags": meta.tags,
                "param_schema": meta.param_schema,
            }
            if detail:
                info["code"] = meta.code
                info["permission_level"] = meta.permission_level.value
            result.append(info)
        return json.dumps(result, ensure_ascii=False, default=str)

    list_tools_fn = tool(
        name="list_tools",
        description="列出所有已注册的动态工具及其详细信息。使用 detail=true 获取完整信息（含参数 Schema 和源代码）。",
        permission_level=PermissionLevel.SAFE,
        timeout=10.0,
        tags=["dynamic", "meta"],
    )(_list_tools_impl)

    return list_tools_fn
