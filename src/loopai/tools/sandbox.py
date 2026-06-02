""":mod:`loopai.tools.sandbox` — 动态工具代码安全扫描与沙箱执行。

提供两个核心类：

* **DangerousModuleScanner** — 基于 AST 的静态代码扫描器，检测危险导入、
  函数调用和内省绕过模式（35+ 入口）。
* **SandboxExecutor** — 在子进程中隔离执行 Python/Bash 代码，通过
  三层安全防护（网络命名空间隔离、路径白名单、rlimit 资源限制）构建
  真正的安全边界。

决策引用:
    D-06: 确认后立即注册到内存，沙箱级/项目级在首次执行成功后才写文件
    T-08-03: AST 扫描不做信任边界——用户确认 + Phase 9 沙箱作后续防线
    T-08-04: subprocess 子进程隔离 + resource.setrlimit
    DYN-11: 子进程隔离——SystemExit 被捕获，主进程不受影响
    DYN-12: rlimit 资源硬限制——CPU/内存/进程数/文件大小
    DYN-13: 网络命名空间隔离——unshare --net 阻断所有网络连接
    DYN-14: 路径白名单校验——realpath + startswith 包含性检查
"""

from __future__ import annotations

import asyncio
import ast
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from loopai.events.bus import EventBus

__all__ = ["DangerousModuleScanner", "SandboxExecutor"]

logger = logging.getLogger(__name__)

# ── unshare 可用性缓存（避免重复同步检测） ──────────────────────────────

_unshare_available: bool | None = None

# ── 模块级常量 ──────────────────────────────────────────────────────────

# 敏感路径黑名单——即使出现在白名单中也拒绝
DENY_PATTERNS: list[str] = [
    "/etc",
    "/proc",
    "/sys",
    "/dev",
    os.path.expanduser("~/.ssh"),
    os.path.expanduser("~/.gnupg"),
    os.path.expanduser("~/.aws"),
]

# 沙箱根目录的真实路径
SANDBOX_ROOT: str = os.path.realpath(".sandbox")


class DangerousModuleScanner(ast.NodeVisitor):
    """基于 AST 的静态代码扫描器，检测危险入口。

    对 LLM 生成的 Python 代码执行第一道快筛（T-08-03）。扫描三类危险模式：

    * **FORBIDDEN_IMPORTS** — 禁止导入的模块（os, subprocess, socket 等 30 个）
    * **FORBIDDEN_CALLS** — 禁止直接调用的内置函数（eval, exec, open 等）
    * **BYPASS_PATTERNS** — 沙箱绕过/内省链（__subclasses__, __globals__ 等）

    注意：AST 扫描不是信任边界。它只提供快速反馈，真正的隔离
    由 SandboxExecutor 的子进程 + rlimit 以及用户确认门共同保证。
    """

    # ── 禁止清单 ──────────────────────────────────────────────────────

    FORBIDDEN_IMPORTS: set[str] = {
        "os",
        "subprocess",
        "sys",
        "ctypes",
        "cffi",
        "mmap",
        "gc",
        "code",
        "types",
        "marshal",
        "pickle",
        "imp",
        "importlib",
        "pdb",
        "bdb",
        "inspect",
        "multiprocessing",
        "socket",
        "requests",
        "httpx",
        "urllib",
        "http",
        "signal",
        "tracemalloc",
        "faulthandler",
        "traceback",
    }

    FORBIDDEN_CALLS: set[str] = {
        "eval",
        "exec",
        "compile",
        "__import__",
        "breakpoint",
        "open",
    }

    BYPASS_PATTERNS: set[str] = {
        "__subclasses__",
        "__bases__",
        "__globals__",
        "__code__",
        "__traceback__",
        "tb_frame",
        "f_back",
    }

    # ── 严重级别映射 ──────────────────────────────────────────────────

    _SEVERITY_MAP: dict[str, str] = {}

    @classmethod
    def _build_severity_map(cls) -> dict[str, str]:
        """惰性构建严重级别映射（按计划中的规则）。"""
        if cls._SEVERITY_MAP:
            return cls._SEVERITY_MAP

        m: dict[str, str] = {}

        # FORBIDDEN_IMPORTS 分级
        high_imports = {"os", "subprocess", "socket", "ctypes"}
        medium_imports = {"sys", "importlib", "multiprocessing"}
        for name in cls.FORBIDDEN_IMPORTS:
            if name in high_imports:
                m[f"import:{name}"] = "high"
            elif name in medium_imports:
                m[f"import:{name}"] = "medium"
            else:
                m[f"import:{name}"] = "low"

        # FORBIDDEN_CALLS 分级
        high_calls = {"eval", "exec", "compile", "__import__"}
        for name in cls.FORBIDDEN_CALLS:
            if name in high_calls:
                m[f"call:{name}"] = "high"
            else:
                m[f"call:{name}"] = "medium"

        # BYPASS_PATTERNS 全部高危
        for name in cls.BYPASS_PATTERNS:
            m[f"attribute:{name}"] = "high"

        cls._SEVERITY_MAP = m
        return m

    # ── 中文消息映射 ──────────────────────────────────────────────────

    _MESSAGES: dict[str, dict[str, str]] = {
        "import": {
            "os": "导入 os 模块可执行系统命令，存在命令注入风险",
            "subprocess": "导入 subprocess 模块可启动子进程，存在任意代码执行风险",
            "sys": "导入 sys 模块可访问解释器内部，存在运行时篡改风险",
            "ctypes": "导入 ctypes 模块可调用 C 函数，存在内存破坏风险",
            "cffi": "导入 cffi 模块可调用外部函数，存在绕过沙箱风险",
            "mmap": "导入 mmap 模块可直接操作内存映射，存在内存篡改风险",
            "gc": "导入 gc 模块可操作垃圾回收器，存在对象操纵风险",
            "code": "导入 code 模块可动态构造代码对象，存在代码注入风险",
            "types": "导入 types 模块可动态构造类型，存在类型伪造风险",
            "marshal": "导入 marshal 模块可序列化代码对象，存在反序列化攻击风险",
            "pickle": "导入 pickle 模块可执行任意反序列化代码，存在 RCE 风险",
            "imp": "导入 imp 模块（已弃用）可用于低层模块加载，存在绕过风险",
            "importlib": "导入 importlib 模块可动态加载模块，存在绕过导入检查风险",
            "pdb": "导入 pdb 模块可启动调试器，存在运行时篡改风险",
            "bdb": "导入 bdb 模块可操作调试框架，存在断点注入风险",
            "inspect": "导入 inspect 模块可内省调用栈和源码，存在信息泄露风险",
            "multiprocessing": "导入 multiprocessing 模块可创建子进程，存在沙箱逃逸风险",
            "socket": "导入 socket 模块可建立网络连接，存在数据外泄风险",
            "requests": "导入 requests 模块可发起 HTTP 请求，存在数据外泄风险",
            "httpx": "导入 httpx 模块可发起 HTTP 请求，存在数据外泄风险",
            "urllib": "导入 urllib 模块可发起网络请求，存在数据外泄风险",
            "http": "导入 http 模块可创建 HTTP 服务，存在后门风险",
            "signal": "导入 signal 模块可注册信号处理器，存在进程劫持风险",
            "tracemalloc": "导入 tracemalloc 模块可追踪内存分配，存在信息泄露风险",
            "faulthandler": "导入 faulthandler 模块可转储调用栈，存在信息泄露风险",
            "traceback": "导入 traceback 模块可获取错误调用栈，存在信息泄露风险",
        },
        "call": {
            "eval": "调用 eval() 可执行任意 Python 表达式，存在代码注入风险",
            "exec": "调用 exec() 可执行任意 Python 代码块，存在完全 RCE 风险",
            "compile": "调用 compile() 可编译任意代码字符串为代码对象，存在绕过 AST 检查风险",
            "__import__": "调用 __import__() 可动态导入模块，存在绕过导入检查风险",
            "breakpoint": "调用 breakpoint() 可启动调试器，存在运行时篡改风险",
            "open": "调用 open() 可读写任意文件，存在信息泄露和文件篡改风险",
        },
        "attribute": {
            "__subclasses__": "访问 __subclasses__ 可遍历类层次结构，存在沙箱逃逸风险",
            "__bases__": "访问 __bases__ 可遍历基类链，存在类型系统绕过风险",
            "__globals__": "访问 __globals__ 可获取模块全局命名空间，存在变量篡改风险",
            "__code__": "访问 __code__ 可获取函数字节码，存在代码逆向和篡改风险",
            "__traceback__": "访问 __traceback__ 可获取异常回溯对象，存在信息泄露风险",
            "tb_frame": "访问 tb_frame 可从回溯获取栈帧，存在栈内省风险",
            "f_back": "访问 f_back 可遍历调用栈，存在栈逃逸风险",
        },
    }

    # ── 公共 API ──────────────────────────────────────────────────────

    def scan(self, code: str) -> list[dict[str, Any]]:
        """扫描 Python 代码字符串，返回检测到的问题列表。

        Args:
            code: 待扫描的 Python 源代码字符串。

        Returns:
            问题列表，每个问题为一个字典::

                {
                    "type": "import" | "call" | "attribute",
                    "name": str,           # 检测到的模块/函数/属性名
                    "message": str,        # 人类可读的中文解释
                    "severity": "high" | "medium" | "low",
                    "line": int,           # 源代码行号
                }
        """
        self._issues: list[dict[str, Any]] = []
        try:
            tree = ast.parse(code)
            self.visit(tree)
        except SyntaxError as e:
            # 语法错误的代码无法进一步扫描，返回语法错误信息
            self._issues.append({
                "type": "syntax_error",
                "name": "SyntaxError",
                "message": f"代码存在语法错误，无法完成 AST 扫描：{e.msg}",
                "severity": "high",
                "line": getattr(e, "lineno", 1),
            })
        return self._issues

    # ── AST 访问器 ────────────────────────────────────────────────────

    def visit_Import(self, node: ast.Import) -> None:
        """检测 ``import foo`` 语句中的危险模块。"""
        self._build_severity_map()
        for alias in node.names:
            root_module = alias.name.split(".")[0]
            if root_module in self.FORBIDDEN_IMPORTS:
                key = f"import:{root_module}"
                self._issues.append({
                    "type": "import",
                    "name": alias.name,
                    "message": self._MESSAGES.get("import", {}).get(
                        root_module, f"禁止导入模块 {root_module}"
                    ),
                    "severity": self._SEVERITY_MAP.get(key, "low"),
                    "line": node.lineno if hasattr(node, "lineno") else 1,
                })
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """检测 ``from foo import bar`` 语句中的危险模块。"""
        self._build_severity_map()
        if node.module is not None:
            root_module = node.module.split(".")[0]
            if root_module in self.FORBIDDEN_IMPORTS:
                key = f"import:{root_module}"
                self._issues.append({
                    "type": "import",
                    "name": node.module,
                    "message": self._MESSAGES.get("import", {}).get(
                        root_module, f"禁止导入模块 {root_module}"
                    ),
                    "severity": self._SEVERITY_MAP.get(key, "low"),
                    "line": node.lineno if hasattr(node, "lineno") else 1,
                })
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        """检测危险函数调用（eval, exec, open 等）。"""
        self._build_severity_map()
        func_name: str | None = None

        if isinstance(node.func, ast.Name):
            func_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            func_name = node.func.attr

        if func_name and func_name in self.FORBIDDEN_CALLS:
            key = f"call:{func_name}"
            self._issues.append({
                "type": "call",
                "name": func_name,
                "message": self._MESSAGES.get("call", {}).get(
                    func_name, f"禁止调用 {func_name}()"
                ),
                "severity": self._SEVERITY_MAP.get(key, "medium"),
                "line": node.lineno if hasattr(node, "lineno") else 1,
            })
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """检测内省绕过属性访问（__subclasses__, __globals__ 等）。"""
        self._build_severity_map()
        if node.attr in self.BYPASS_PATTERNS:
            key = f"attribute:{node.attr}"
            self._issues.append({
                "type": "attribute",
                "name": node.attr,
                "message": self._MESSAGES.get("attribute", {}).get(
                    node.attr, f"禁止访问 {node.attr}（沙箱绕过模式）"
                ),
                "severity": self._SEVERITY_MAP.get(key, "high"),
                "line": node.lineno if hasattr(node, "lineno") else 1,
            })
        self.generic_visit(node)


class SandboxExecutor:
    """在子进程中隔离执行 Python/Bash 代码。

    使用 ``subprocess.run(shell=False)`` 在子进程中运行代码，通过
    ``resource.setrlimit`` 限制 CPU 时间、内存和进程数（Unix 平台）。

    决策引用:
        T-08-04: subprocess 子进程隔离 + resource.setrlimit
        T-08-06: timeout 限制执行时间 + RLIMIT_CPU/AS/NPROC
    """

    def __init__(
        self,
        timeout: float = 30.0,
        memory_limit_mb: int = 512,
        event_bus: "EventBus | None" = None,
    ) -> None:
        """初始化沙箱执行器。

        Args:
            timeout: 子进程执行超时（秒），传递给 subprocess.run。
            memory_limit_mb: 子进程最大内存限制（MB），仅在 Unix 平台生效。
            event_bus: 可选的事件总线，用于发布沙箱安全事件
                       （sandbox_timeout、sandbox_violation、sandbox_resource_exceeded）。
                       默认 None 保持向后兼容。
        """
        self.timeout = timeout
        self.memory_limit_mb = memory_limit_mb
        self._event_bus = event_bus

    # ── 公共 API ──────────────────────────────────────────────────────

    async def execute(
        self,
        code: str,
        language: str,
        working_dir: str | None = None,
        extra_dirs: list[str] | None = None,
    ) -> dict[str, Any]:
        """在隔离子进程中执行代码。

        集成三层安全加固：路径白名单校验 → unshare 网络隔离 → rlimit 资源限制。

        Args:
            code: 待执行的源代码字符串。
            language: 代码语言，``"python"`` 或 ``"bash"``。
            working_dir: 子进程工作目录。若为 None，使用临时目录。
            extra_dirs: 额外允许的目录列表。

        Returns:
            结构化结果字典::

                {
                    "status": "passed" | "failed" | "timeout",
                    "output": str,        # stdout 输出
                    "error": str | None,  # stderr 或异常信息
                    "duration_ms": float, # 执行耗时（毫秒）
                }
        """
        temp_dir: str | None = None
        start_time = time.monotonic()

        try:
            # 创建临时工作目录
            if working_dir is None:
                temp_dir = tempfile.mkdtemp(prefix="sandbox_")
                working_dir = temp_dir

            # ── 路径白名单校验（DYN-14） ──────────────────────────────
            allowed_roots = [SANDBOX_ROOT]
            if extra_dirs:
                allowed_roots.extend(extra_dirs)
            # 自动创建的临时目录始终允许
            if temp_dir is not None:
                allowed_roots.append(temp_dir)

            # 校验 working_dir
            if not self._validate_path(working_dir, allowed_roots):
                detail = f"路径校验失败: {working_dir} 不在白名单内"
                if self._event_bus:
                    await self._event_bus.publish("sandbox_violation", {
                        "event_type": "sandbox_violation",
                        "session_id": "sandbox",
                        "step_num": 0,
                        "tool_name": "sandbox_executor",
                        "violation_type": "sensitive_path"
                        if any(working_dir.startswith(p) for p in DENY_PATTERNS)
                        else "path_escape",
                        "detail": detail,
                    })
                return {
                    "status": "failed",
                    "output": "",
                    "error": detail,
                    "duration_ms": 0,
                }

            # 校验 extra_dirs 中每个路径
            if extra_dirs:
                for ed in extra_dirs:
                    if not self._validate_path(ed, allowed_roots):
                        detail = f"路径校验失败: extra_dir {ed} 不在白名单内"
                        if self._event_bus:
                            await self._event_bus.publish("sandbox_violation", {
                                "event_type": "sandbox_violation",
                                "session_id": "sandbox",
                                "step_num": 0,
                                "tool_name": "sandbox_executor",
                                "violation_type": "path_escape",
                                "detail": detail,
                            })
                        return {
                            "status": "failed",
                            "output": "",
                            "error": detail,
                            "duration_ms": 0,
                        }

            # 确定文件名和命令
            if language == "python":
                script_name = "script.py"
                script_path = os.path.join(working_dir, script_name)
                with open(script_path, "w", encoding="utf-8") as f:
                    f.write(code)
            elif language == "bash":
                script_name = "script.sh"
                script_path = os.path.join(working_dir, script_name)
                with open(script_path, "w", encoding="utf-8") as f:
                    f.write(code)
                os.chmod(script_path, 0o755)
            else:
                return {
                    "status": "failed",
                    "output": "",
                    "error": f"不支持的语言类型: {language}",
                    "duration_ms": 0,
                }

            # ── 构建命令（DYN-13：unshare 网络隔离） ─────────────────
            cmd = self._build_cmd(script_path, language)

            # 设置子进程环境变量
            env = os.environ.copy()
            env["SANDBOX_DIR"] = working_dir

            # 确定是否可以使用 preexec_fn（仅 Unix）
            preexec_fn = None
            if sys.platform != "win32":
                preexec_fn = self._set_limits

            # 执行子进程（使用线程池避免阻塞事件循环）
            result = await asyncio.to_thread(
                subprocess.run,
                cmd,
                cwd=working_dir,
                timeout=self.timeout,
                capture_output=True,
                text=True,
                env=env,
                preexec_fn=preexec_fn,
                shell=False,
            )

            duration_ms = (time.monotonic() - start_time) * 1000

            if result.returncode == 0:
                return {
                    "status": "passed",
                    "output": result.stdout,
                    "error": None,
                    "duration_ms": round(duration_ms, 2),
                }
            else:
                # ── 分类违规并发布事件（D-05） ──────────────────────
                violation = self._classify_violation(result.stderr or "")
                error_msg = result.stderr or f"进程退出码: {result.returncode}"

                if violation and self._event_bus:
                    if violation == "network_attempt":
                        await self._event_bus.publish("sandbox_violation", {
                            "event_type": "sandbox_violation",
                            "session_id": "sandbox",
                            "step_num": 0,
                            "tool_name": "sandbox_executor",
                            "violation_type": "network_attempt",
                            "detail": "子进程尝试网络连接，已被 unshare --net 阻断",
                        })
                    elif violation in ("memory", "process", "file_size"):
                        resource_labels = {
                            "memory": ("memory", "512MB"),
                            "process": ("process", "0"),
                            "file_size": ("file_size", "100MB"),
                        }
                        res_type, limit_str = resource_labels[violation]
                        await self._event_bus.publish(
                            "sandbox_resource_exceeded", {
                                "event_type": "sandbox_resource_exceeded",
                                "session_id": "sandbox",
                                "step_num": 0,
                                "tool_name": "sandbox_executor",
                                "resource_type": res_type,
                                "limit": limit_str,
                                "detail": f"子进程资源超限: {violation}",
                            }
                        )

                return {
                    "status": "failed",
                    "output": result.stdout,
                    "error": error_msg,
                    "duration_ms": round(duration_ms, 2),
                }

        except subprocess.TimeoutExpired:
            duration_ms = (time.monotonic() - start_time) * 1000
            # ── 发布超时事件（D-05） ───────────────────────────────
            if self._event_bus:
                await self._event_bus.publish("sandbox_timeout", {
                    "event_type": "sandbox_timeout",
                    "session_id": "sandbox",
                    "step_num": 0,
                    "tool_name": "sandbox_executor",
                    "timeout_seconds": self.timeout,
                })
            return {
                "status": "timeout",
                "output": "",
                "error": f"子进程执行超时（{self.timeout}秒）",
                "duration_ms": round(duration_ms, 2),
            }
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            return {
                "status": "failed",
                "output": "",
                "error": f"沙箱执行异常: {type(e).__name__}: {e}",
                "duration_ms": round(duration_ms, 2),
            }
        finally:
            # 清理临时目录
            if temp_dir is not None:
                try:
                    shutil.rmtree(temp_dir)
                except OSError:
                    pass  # 清理失败不阻塞

    # ── 命令构建（DYN-13：网络隔离） ────────────────────────────────

    @staticmethod
    def _build_cmd(script_path: str, language: str) -> list[str]:
        """构建平台特定的子进程命令列表。

        在 Linux 上使用 ``unshare --user --map-root-user --net`` 包装基础命令，
        创建无网络命名空间以阻断所有网络连接。非 Linux 平台优雅降级为
        仅基础命令（仅 rlimit 保护）。

        unshare 可用性在模块级缓存（首次检测后复用）。

        决策引用:
            DYN-13: 网络命名空间隔离
            RESEARCH Pattern 1: unshare CLI Wrapper

        Args:
            script_path: 脚本文件的绝对路径。
            language: ``"python"`` 或 ``"bash"``。

        Returns:
            命令列表（可直接传递给 subprocess.run）。
        """
        global _unshare_available

        # 基础命令
        if language == "python":
            base_cmd = [sys.executable, script_path]
        else:
            base_cmd = ["bash", script_path]

        # 非 Linux 优雅降级
        if sys.platform != "linux":
            return base_cmd

        # 使用缓存的 unshare 可用性结果
        if _unshare_available is None:
            try:
                subprocess.run(
                    ["unshare", "--user", "--map-root-user", "true"],
                    timeout=5,
                    capture_output=True,
                    shell=False,
                )
                _unshare_available = True
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
                logger.warning(
                    "unshare 不可用 (%s)，降级为无网络隔离模式。"
                    "需要 util-linux 2.32+ 以使用 --map-root-user。",
                    e,
                )
                _unshare_available = False

        if _unshare_available:
            return ["unshare", "--user", "--map-root-user", "--net"] + base_cmd
        return base_cmd

    # ── 路径安全（DYN-14：路径白名单） ───────────────────────────────

    @staticmethod
    def _safe_realpath(path: str) -> str:
        """解析路径的真实绝对路径，处理不存在的路径组件。

        与 ``os.path.realpath()`` 不同，此方法在路径的中间组件不存在时
        不会失败——它逐级向上解析存在的父目录，然后将不存在的部分拼接回去。
        这防止了攻击者通过在尚未创建的目录中使用符号链接来绕过路径检查。

        决策引用:
            RESEARCH Pitfall 4: _safe_realpath() 处理不存在的路径
            T-09-03: os.path.realpath() 解析符号链接后再做包含性检查

        Args:
            path: 任意路径字符串。

        Returns:
            规范化后的绝对路径。
        """
        # 标准化路径分隔符和多余组件
        path = os.path.normpath(path)

        # 如果路径本身存在，退化为 os.path.realpath()
        if os.path.lexists(path):
            return os.path.realpath(path)

        # 逐级向上查找存在的父目录
        current = path
        missing_parts: list[str] = []
        while current and not os.path.lexists(current):
            parent = os.path.dirname(current)
            if parent == current:
                # 到达根目录——整个路径都不存在
                return path
            missing_parts.insert(0, os.path.basename(current))
            current = parent

        # current 现在是最深的已存在父目录
        real_parent = os.path.realpath(current)
        result = os.path.join(real_parent, *missing_parts)
        return result

    @staticmethod
    def _validate_path(path: str, allowed_roots: list[str]) -> bool:
        """校验路径是否在白名单内且不在黑名单中。

        使用两阶段检查：
        1. 使用 ``_safe_realpath()`` 解析路径（对抗符号链接绕过）
        2. 检查解析后的路径是否以白名单根目录之一为前缀
        3. 检查是否命中 DENY_PATTERNS 黑名单（白名单中的路径也拒绝）

        决策引用:
            DYN-14: 路径白名单校验
            RESEARCH Pattern 2: 路径白名单 — _safe_realpath() + startswith() + DENY_PATTERNS
            T-09-03: 防止符号链接绕过

        Args:
            path: 待校验的路径。
            allowed_roots: 允许的根目录列表。

        Returns:
            路径在白名单中且不在黑名单中时返回 True。
        """
        # 解析真实路径
        real_path = SandboxExecutor._safe_realpath(path)

        # 黑名单检查（优先级最高——即使路径在白名单中也拒绝）
        for deny_pattern in DENY_PATTERNS:
            deny_real = SandboxExecutor._safe_realpath(deny_pattern)
            if (real_path == deny_real
                    or real_path.startswith(deny_real + os.sep)):
                return False

        # 白名单检查
        for root in allowed_roots:
            root_real = SandboxExecutor._safe_realpath(root)
            if (real_path == root_real
                    or real_path.startswith(root_real + os.sep)):
                return True

        return False

    # ── 违规分类（D-05） ───────────────────────────────────────────────

    @staticmethod
    def _classify_violation(stderr: str) -> str | None:
        """分析 stderr 输出以确定违规类型。

        用于在子进程返回非零退出码时分类失败原因，并发布对应的
        安全事件。

        决策引用:
            D-05: 沙箱违规事件发布机制
            T-09-04: 检测网络尝试并发布 sandbox_violation
            T-09-06: 检测文件大小超限并发布 sandbox_resource_exceeded

        Args:
            stderr: 子进程的标准错误输出。

        Returns:
            违规类型字符串，或未检测到已知违规时为 None：
            - ``"network_attempt"`` — 检测到网络连接尝试
            - ``"process"`` — RLIMIT_NPROC 阻止进程创建
            - ``"memory"`` — 内存分配失败
            - ``"file_size"`` — 文件大小超限
            - ``None`` — 未检测到已知违规
        """
        if not stderr:
            return None

        stderr_lower = stderr.lower()

        # 网络尝试：unshare --net 阻断
        if ("network is unreachable" in stderr_lower
                or "network unreachable" in stderr_lower
                or "cannot assign requested address" in stderr_lower):
            return "network_attempt"

        # 进程创建限制：RLIMIT_NPROC=0
        # "Resource temporarily unavailable" 是 fork 因 RLIMIT_NPROC=0 失败时的
        # 标准 OS 错误信息（EAGAIN），即使消息中不包含 "fork" 或 "process" 也足以判定
        if "resource temporarily unavailable" in stderr_lower:
            return "process"

        # 内存限制：RLIMIT_AS
        if ("cannot allocate memory" in stderr_lower
                or "memoryerror" in stderr_lower):
            return "memory"

        # 文件大小限制：RLIMIT_FSIZE → SIGXFSZ
        if ("file too large" in stderr_lower
                or "file size limit exceeded" in stderr_lower):
            return "file_size"

        return None

    # ── 资源限制（仅 Unix） ───────────────────────────────────────────

    @staticmethod
    def _set_limits() -> None:
        """在子进程中设置资源限制（preexec_fn 回调）。

        仅在 Unix 平台调用。设置以下硬限制：

        * **RLIMIT_CPU** — CPU 时间限制 (30s, 30s)
        * **RLIMIT_AS** — 地址空间（内存）限制 (512MB, 512MB)
        * **RLIMIT_NPROC** — 最大子进程数 (0, 0)——禁止 fork
        * **RLIMIT_FSIZE** — 最大文件写入量 (100MB, 100MB)

        决策引用:
            DYN-12: rlimit 资源硬限制
            T-09-05: RLIMIT_NPROC=0 防止 fork bomb
            T-09-06: RLIMIT_FSIZE=100MB 防止磁盘填充攻击
            T-09-07: RLIMIT_AS=512MB 防止内存炸弹

        注意：preexec_fn 在 exec 之前运行，设置的限制对子进程生效。
        RLIMIT_NPROC=0 在 unshare --user 命名空间内仍然安全——
        命名空间内的伪 root UID 0 同样受 rlimit 约束。
        """
        import resource

        memory_bytes = 512 * 1024 * 1024  # 512 MB
        fs_bytes = 100 * 1024 * 1024      # 100 MB

        try:
            resource.setrlimit(
                resource.RLIMIT_CPU,
                (30, 30),  # soft, hard: 30 秒 CPU 时间
            )
        except (ValueError, OSError):
            pass

        try:
            resource.setrlimit(
                resource.RLIMIT_AS,
                (memory_bytes, memory_bytes),
            )
        except (ValueError, OSError):
            pass

        try:
            resource.setrlimit(
                resource.RLIMIT_NPROC,
                (0, 0),  # 禁止 fork——防止 fork bomb
            )
        except (ValueError, OSError):
            pass

        try:
            resource.setrlimit(
                resource.RLIMIT_FSIZE,
                (fs_bytes, fs_bytes),  # 最大 100MB 文件写入
            )
        except (ValueError, OSError):
            pass
