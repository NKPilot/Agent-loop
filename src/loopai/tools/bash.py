""":mod:`loopai.tools.bash` — BashTool：安全的子进程执行，shell=False。

提供 :class:`BashTool` 用于通过安全的 ``subprocess.run`` 封装
执行 shell 命令，强制执行 ``shell=False``、通过
:class:`CommandClassifier` 进行命令分类、shell 元字符拦截、
超时控制和输出截断。

该模块还导出 :func:`create_bash_tool`，这是一个工厂函数，
返回一个 ``@tool`` 装饰的可调用对象，适合注册到 :class:`ToolRegistry`。

决策引用:
    D-05: ToolResult 标准化包装
    D-07: Bash 工具默认超时 60 秒
    D-08: 通过 CommandClassifier 的白名单/黑名单分类
    D-14: 磁盘诊断的最小工具集（df, du, find, rm）

安全:
    - 始终 ``shell=False`` + 参数列表（从不传字符串）
    - 拒绝 Shell 元字符（``|``、``;``、``&``、``$``、反引号）
    - 每条命令执行前都经过分类
    - 输出截断在 ``max_output_bytes`` 以内，防止内存耗尽

用法::

    from loopai.tools.bash import BashTool, create_bash_tool

    # 直接使用
    tool = BashTool(working_dir="/home/user")
    result = await tool.execute("df -h")

    # 作为已注册工具
    bash_fn = create_bash_tool(working_dir="/home/user")
    registry.register(bash_fn)
"""

from __future__ import annotations

import asyncio
import re
import shlex
import subprocess
import time
from typing import TYPE_CHECKING

from loopai.tools.command_classifier import CommandClassifier
from loopai.tools.types import ToolResult

if TYPE_CHECKING:
    pass


class BashTool:
    """安全子进程执行器——用安全层封装 ``subprocess.run``。

    每条命令在执行前经过三道闸门：

    1. **解析**——``shlex.split()`` 将命令字符串转换为安全的
       参数列表（无 shell 解释）。
    2. **分类**——:class:`CommandClassifier` 根据命令标识和
       目标路径分配 :class:`PermissionLevel`。
    3. **元字符扫描**——在到达 ``subprocess`` 之前检测并拒绝
       Shell 元字符（``|``、``;``、``&``、``$``、反引号）。

    执行后检查输出是否超过 ``max_output_bytes``，必要时进行截断。

    Attributes:
        working_dir: 子进程执行的工作目录。
        default_timeout: 默认超时秒数（D-07 规定 60 秒）。
        max_output_bytes: 截断前最大 stdout 字节数（100 KB）。
        classifier: 用于命令分类的 :class:`CommandClassifier` 实例。
    """

    def __init__(
        self,
        working_dir: str = "/home/user",
        default_timeout: float = 60.0,
        max_output_bytes: int = 102400,
    ) -> None:
        self.working_dir = working_dir
        self.default_timeout = default_timeout
        self.max_output_bytes = max_output_bytes
        self.classifier = CommandClassifier()

    # ── 公共 API ──────────────────────────────────────────────────────

    async def execute(
        self,
        command: str,
        args: list[str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """通过安全管道执行 shell 命令。

        Args:
            command: 命令字符串（例如 ``"ls -la"``、``"df -h"``）。
            args: 可选的显式参数列表。如为 ``None``，则用
                :func:`shlex.split` 解析 *command*。
            timeout: 每次调用的超时覆盖，秒。回退到
                :attr:`default_timeout`（60 秒）。

        Returns:
            包含成功/错误状态和捕获输出的 :class:`ToolResult`。
        """
        effective_timeout = timeout if timeout is not None else self.default_timeout

        # ── 第 1 步：将命令解析为参数列表 ─────────────────────────
        if args is None:
            try:
                parsed = shlex.split(command)
            except ValueError as exc:
                return ToolResult.error(
                    f"命令解析失败: {exc}",
                    duration_ms=0.0,
                )
            if not parsed:
                return ToolResult.error(
                    "空命令",
                    duration_ms=0.0,
                )
            cmd_name = parsed[0]
            cmd_args = parsed[1:]
        else:
            cmd_name = command
            cmd_args = list(args)

        # ── 第 2 步：通过 CommandClassifier 分类 ────────────────
        level, reason = self.classifier.classify(
            cmd_name, cmd_args, self.working_dir
        )

        # ── 第 3 步：安全扫描——阻止 shell 元字符 ──────────────
        meta_detail = self._scan_metacharacters(command)
        if meta_detail:
            return ToolResult.error(
                f"命令包含不安全的 shell 元字符: {meta_detail}",
                duration_ms=0.0,
            )

        # ── 第 4 步：通过 subprocess 执行，带超时 ──────────────
        args_list = [cmd_name] + cmd_args

        start = time.monotonic()
        try:
            # 在线程中运行子进程，避免阻塞事件循环。
            proc_result = await asyncio.wait_for(
                asyncio.to_thread(
                    subprocess.run,
                    args_list,
                    timeout=effective_timeout,
                    capture_output=True,
                    text=True,
                    shell=False,
                    cwd=self.working_dir,
                ),
                timeout=effective_timeout + 5.0,  # 线程安全余量
            )
        except asyncio.TimeoutError:
            duration_ms = (time.monotonic() - start) * 1000
            return ToolResult.error(
                f"命令执行超时 ({effective_timeout:.0f}s)",
                duration_ms=duration_ms,
            )
        except subprocess.TimeoutExpired:
            duration_ms = (time.monotonic() - start) * 1000
            return ToolResult.error(
                f"命令执行超时 ({effective_timeout:.0f}s)",
                duration_ms=duration_ms,
            )
        except FileNotFoundError:
            duration_ms = (time.monotonic() - start) * 1000
            return ToolResult.error(
                f"命令未找到: {cmd_name}",
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = (time.monotonic() - start) * 1000
            return ToolResult.error(
                f"命令执行异常: {exc}",
                duration_ms=duration_ms,
            )

        duration_ms = (time.monotonic() - start) * 1000

        # ── 第 5 步：检查返回码 ──────────────────────────────────
        if proc_result.returncode != 0:
            err_detail = (
                proc_result.stderr.strip()
                if proc_result.stderr
                else proc_result.stdout.strip()
            )
            return ToolResult.error(
                f"命令 '{command}' 返回非零退出码 {proc_result.returncode}: {err_detail}",
                duration_ms=duration_ms,
            )

        # ── 第 6 步：必要时截断输出 ────────────────────────────
        output: str = (
            proc_result.stdout if proc_result.stdout else proc_result.stderr
        )
        truncated = False
        output_bytes = len(output.encode("utf-8"))
        if output_bytes > self.max_output_bytes:
            truncated = True
            encoded = output.encode("utf-8")[: self.max_output_bytes]
            output = encoded.decode("utf-8", errors="replace")

        return ToolResult.success(
            data=output,
            duration_ms=duration_ms,
            truncated=truncated,
        )

    # ── 内部辅助 ─────────────────────────────────────────────────────

    # Shell 元字符模式：管道符、分号、后台、美元符号、
    # 反引号、命令替换、逻辑运算符。
    _META_PATTERN: re.Pattern = re.compile(r"[|;&`$]|\$\(|&&|\|\|")

    @classmethod
    def _scan_metacharacters(cls, command: str) -> str | None:
        """扫描 *command* 中是否存在危险的 shell 元字符。

        Args:
            command: 要检查的原始命令字符串。

        Returns:
            找到的第一个元字符的人类可读描述，
            或 ``None`` 表示命令安全。
        """
        match = cls._META_PATTERN.search(command)
        if not match:
            return None
        found = match.group()
        descriptions: dict[str, str] = {
            "|": "管道符 (|)",
            ";": "分号 (;)",
            "&": "后台符号 (&)",
            "$": "变量引用 ($)",
            "`": "反引号命令替换 (`)",
            "$(": "命令替换 ($(...))",
            "&&": "逻辑与 (&&)",
            "||": "逻辑或 (||)",
        }
        desc = descriptions.get(found, f"元字符 ({found})")
        return f"检测到 {desc}，出于安全原因已拒绝执行"


# ── 用于 @tool 注册的工厂函数 ─────────────────────────────────────────


def create_bash_tool(working_dir: str = "/home/user") -> "callable":
    """创建一个 ``@tool`` 装饰的 bash 执行函数。

    返回的函数接受单个 ``command: str`` 参数，
    并将命令输出作为字符串返回。它携带一个
    :attr:`__tool_meta__` 属性，包含完整的 :class:`ToolMetadata`，
    以便注册到 :class:`~loopai.tools.registry.ToolRegistry`。

    Args:
        working_dir: BashTool 子进程执行的工作目录。

    Returns:
        一个 ``@tool`` 装饰的异步可调用对象，附带了元数据。

    Example::

        from loopai.tools.bash import create_bash_tool
        from loopai.tools.registry import ToolRegistry

        registry = ToolRegistry()
        bash_fn = create_bash_tool(working_dir="/home/user")
        registry.register(bash_fn)
    """
    from loopai.tools.decorator import tool
    from loopai.tools.types import PermissionLevel

    bash_tool_instance = BashTool(working_dir=working_dir)

    @tool(
        name="bash",
        description=(
            "执行 Bash 命令。"
            "支持的系统命令：ls, df, du, find, cat, head, tail, wc, grep, "
            "sort, uniq, echo, stat。"
            "危险命令（rm, dd, mkfs 等）需要用户确认。"
        ),
        permission_level=PermissionLevel.MODERATE,
        timeout=60.0,
        tags=["bash", "system"],
    )
    async def bash_execute(command: str) -> str:
        """执行 bash 命令并返回输出。

        Args:
            command: 要执行的 shell 命令（例如 "df -h"）。

        Returns:
            命令的 stdout 输出字符串。
        """
        result = await bash_tool_instance.execute(command)
        if result.is_error:
            return f"[ERROR] {result.error_message}"
        return str(result.data) if result.data is not None else ""

    return bash_execute
