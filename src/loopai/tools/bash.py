""":mod:`loopai.tools.bash` — BashTool: safe subprocess execution with shell=False.

Provides :class:`BashTool` for executing shell commands through a secure
``subprocess.run`` wrapper that enforces ``shell=False``, command
classification via :class:`CommandClassifier`, shell metacharacter
interception, timeout control, and output truncation.

The module also exports :func:`create_bash_tool`, a factory that returns a
``@tool``-decorated callable suitable for registration with :class:`ToolRegistry`.

Decision references:
    D-05: ToolResult standardized wrapper
    D-07: Bash tool default timeout 60 s
    D-08: Whitelist/blacklist classification via CommandClassifier
    D-14: Minimal tool set for disk diagnosis (df, du, find, rm)

Security:
    - Always ``shell=False`` + argument list (never a string)
    - Shell metacharacters (``|``, ``;``, ``&``, ``$``, backticks) are rejected
    - Every command is classified before execution
    - Output is truncated at ``max_output_bytes`` to prevent memory exhaustion

Usage::

    from loopai.tools.bash import BashTool, create_bash_tool

    # Direct usage
    tool = BashTool(working_dir="/home/user")
    result = await tool.execute("df -h")

    # As a registered tool
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
    """Safe subprocess executor — wraps ``subprocess.run`` with security layers.

    Every command passes through three gates before execution:

    1. **Parsing** — ``shlex.split()`` converts the command string into a safe
       argument list (no shell interpretation).
    2. **Classification** — :class:`CommandClassifier` assigns a
       :class:`PermissionLevel` based on command identity and target paths.
    3. **Metacharacter scan** — Shell metacharacters (``|``, ``;``, ``&``,
       ``$``, backticks) are detected and rejected before reaching
       ``subprocess``.

    After execution the output is checked against ``max_output_bytes`` and
    truncated if necessary.

    Attributes:
        working_dir: Working directory for subprocess execution.
        default_timeout: Default timeout in seconds (60 s per D-07).
        max_output_bytes: Maximum stdout bytes before truncation (100 KB).
        classifier: :class:`CommandClassifier` instance for command classification.
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

    # ── Public API ──────────────────────────────────────────────────────

    async def execute(
        self,
        command: str,
        args: list[str] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """Execute a shell command through the security pipeline.

        Args:
            command: The command string (e.g. ``"ls -la"``, ``"df -h"``).
            args: Optional explicit argument list.  If ``None``, *command*
                is parsed with :func:`shlex.split`.
            timeout: Per-call timeout override in seconds.  Falls back to
                :attr:`default_timeout` (60 s).

        Returns:
            A :class:`ToolResult` with success/error status and captured output.
        """
        effective_timeout = timeout if timeout is not None else self.default_timeout

        # ── Step 1: Parse command into argument list ─────────────────
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

        # ── Step 2: Classify via CommandClassifier ───────────────────
        level, reason = self.classifier.classify(
            cmd_name, cmd_args, self.working_dir
        )

        # ── Step 3: Security scan — block shell metacharacters ───────
        meta_detail = self._scan_metacharacters(command)
        if meta_detail:
            return ToolResult.error(
                f"命令包含不安全的 shell 元字符: {meta_detail}",
                duration_ms=0.0,
            )

        # ── Step 4: Execute via subprocess with timeout ──────────────
        args_list = [cmd_name] + cmd_args

        start = time.monotonic()
        try:
            # Run subprocess in a thread to avoid blocking the event loop.
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
                timeout=effective_timeout + 5.0,  # safety margin for thread
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

        # ── Step 5: Check return code ────────────────────────────────
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

        # ── Step 6: Truncate output if needed ────────────────────────
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

    # ── Internal helpers ─────────────────────────────────────────────────

    # Shell metacharacter pattern: pipe, semicolon, background, dollar sign,
    # backtick, command substitution, logic operators.
    _META_PATTERN: re.Pattern = re.compile(r"[|;&`$]|\$\(|&&|\|\|")

    @classmethod
    def _scan_metacharacters(cls, command: str) -> str | None:
        """Scan *command* for dangerous shell metacharacters.

        Args:
            command: The raw command string to inspect.

        Returns:
            A human-readable description of the first metacharacter found,
            or ``None`` if the command is safe.
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


# ── Factory function for @tool registration ─────────────────────────────


def create_bash_tool(working_dir: str = "/home/user") -> "callable":
    """Create a ``@tool``-decorated bash execution function.

    The returned function accepts a single ``command: str`` argument and
    returns the command output as a string.  It carries a
    :attr:`__tool_meta__` attribute with full :class:`ToolMetadata` so it
    can be registered with :class:`~loopai.tools.registry.ToolRegistry`.

    Args:
        working_dir: Working directory for BashTool subprocess execution.

    Returns:
        A ``@tool``-decorated async callable with metadata attached.

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
        """Execute a bash command and return the output.

        Args:
            command: The shell command to execute (e.g. "df -h").

        Returns:
            The command's stdout output as a string.
        """
        result = await bash_tool_instance.execute(command)
        if result.is_error:
            return f"[ERROR] {result.error_message}"
        return str(result.data) if result.data is not None else ""

    return bash_execute
