""":mod:`loopai.tools.sandbox` — 动态工具代码安全扫描与沙箱执行。

提供两个核心类：

* **DangerousModuleScanner** — 基于 AST 的静态代码扫描器，检测危险导入、
  函数调用和内省绕过模式（35+ 入口）。
* **SandboxExecutor** — 在子进程中隔离执行 Python/Bash 代码，通过
  ``resource.setrlimit`` 限制 CPU/内存/进程数。

决策引用:
    D-06: 确认后立即注册到内存，沙箱级/项目级在首次执行成功后才写文件
    T-08-03: AST 扫描不做信任边界——用户确认 + Phase 9 沙箱作后续防线
    T-08-04: subprocess 子进程隔离 + resource.setrlimit
"""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any

__all__ = ["DangerousModuleScanner", "SandboxExecutor"]


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
    ) -> None:
        """初始化沙箱执行器。

        Args:
            timeout: 子进程执行超时（秒），传递给 subprocess.run。
            memory_limit_mb: 子进程最大内存限制（MB），仅在 Unix 平台生效。
        """
        self.timeout = timeout
        self.memory_limit_mb = memory_limit_mb

    # ── 公共 API ──────────────────────────────────────────────────────

    async def execute(
        self,
        code: str,
        language: str,
        working_dir: str | None = None,
        extra_dirs: list[str] | None = None,
    ) -> dict[str, Any]:
        """在隔离子进程中执行代码。

        Args:
            code: 待执行的源代码字符串。
            language: 代码语言，``"python"`` 或 ``"bash"``。
            working_dir: 子进程工作目录。若为 None，使用临时目录。
            extra_dirs: 额外目录列表（当前版本保留，供未来扩展）。

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

            # 确定文件名和命令
            if language == "python":
                script_name = "script.py"
                script_path = os.path.join(working_dir, script_name)
                with open(script_path, "w", encoding="utf-8") as f:
                    f.write(code)
                cmd = [sys.executable, script_path]
            elif language == "bash":
                script_name = "script.sh"
                script_path = os.path.join(working_dir, script_name)
                with open(script_path, "w", encoding="utf-8") as f:
                    f.write(code)
                os.chmod(script_path, 0o755)
                cmd = ["bash", script_path]
            else:
                return {
                    "status": "failed",
                    "output": "",
                    "error": f"不支持的语言类型: {language}",
                    "duration_ms": 0,
                }

            # 设置子进程环境变量
            env = os.environ.copy()
            env["SANDBOX_DIR"] = working_dir

            # 确定是否可以使用 preexec_fn（仅 Unix）
            preexec_fn = None
            if sys.platform != "win32":
                preexec_fn = self._set_limits

            # 执行子进程
            result = subprocess.run(
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
                return {
                    "status": "failed",
                    "output": result.stdout,
                    "error": result.stderr or f"进程退出码: {result.returncode}",
                    "duration_ms": round(duration_ms, 2),
                }

        except subprocess.TimeoutExpired:
            duration_ms = (time.monotonic() - start_time) * 1000
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

    # ── 资源限制（仅 Unix） ───────────────────────────────────────────

    @staticmethod
    def _set_limits() -> None:
        """在子进程中设置资源限制（preexec_fn 回调）。

        仅在 Unix 平台调用。设置以下限制：

        * **RLIMIT_CPU** — CPU 时间限制
        * **RLIMIT_AS** — 地址空间（内存）限制
        * **RLIMIT_NPROC** — 最大子进程数

        注意：preexec_fn 在 exec 之前运行，设置的限制对子进程生效。
        """
        import resource

        memory_bytes = 512 * 1024 * 1024  # 512 MB 默认值

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
                (50, 50),  # 最多 50 个子进程
            )
        except (ValueError, OSError):
            pass
