# Stack Research — Agent 动态工具创建系统 (v1.1)

**Domain:** AI Agent 动态代码生成、沙箱执行、运行时工具注册
**Researched:** 2026-05-31
**Confidence:** HIGH（所有版本号经 npm/PyPI 验证；stdlib 模块经实际 import 验证）

> 此文件为 v1.1 里程碑的**增量堆栈**。v1.0 基础堆栈（Python 3.13, FastAPI, openai SDK, React 19, Vite 8, Tailwind 4, shadcn/ui, Zustand, React Query）保持不变，详见 `.planning/PROJECT.md` 和 `CLAUDE.md`。

## 核心发现

**Python 后端：零新增 PyPI 依赖。** 动态代码加载（`importlib.util`）、安全扫描（`ast`）、沙箱隔离（`subprocess` + `resource`）、临时目录（`tempfile`）全部是 Python 3.12+ stdlib。这是经过深思熟虑的选择——RestrictedPython 太受限（禁 `open`/`subprocess`），Docker 太重（学习项目不需要容器编排），而 stdlib 三层防御（AST 扫描 + resource limits + 子进程隔离）恰好匹配"LLM 生成 + 人工审核"的安全模型。

**前端：唯一新增依赖是 `@monaco-editor/react`。** Monaco 的 `Editor`（只读模式）覆盖代码展示，`DiffEditor` 覆盖工具更新 diff 对比。单依赖解决两个 UI 需求，Python/Bash 语法高亮开箱即用。CodeMirror 6 是轻量替代方案但 diff 视图不如 Monaco 精致，且需要分别安装 `@uiw/react-codemirror` + `@codemirror/merge` 两个包。

## Recommended Stack — Python 后端（v1.1 新增）

### 动态代码执行与安全

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **ast** | (stdlib 3.12+) | 预执行代码安全扫描——`ast.NodeVisitor` 检测危险模块导入（`os`, `subprocess`, `socket`, `ctypes`）、危险函数调用（`eval`, `exec`, `compile`, `__import__`）、间接绕过模式（`getattr(__builtins__,...)`） | 零依赖。AST 结构化遍历比字符串正则匹配更难绕过。Python 3.12 的 `ast` 模块完全稳定，支持 `match`/`case` 等新语法节点。扫描结果用于前端确认弹窗中的"风险提示"，不做硬阻断 |
| **importlib.util** | (stdlib 3.12+) | 项目级持久化工具的模块加载——`spec_from_file_location()` → `module_from_spec()` → `exec_module()` 三步法 | Python 3.4+ 推荐的动态加载方式。取代已废弃的 `imp.load_source()`（3.12 已移除）和 `SourceFileLoader.load_module()`。支持正确的 `__name__`、`__package__`、相对导入语义 |
| **subprocess** | (stdlib 3.12+) | MODERATE/DANGEROUS 级别工具的隔离执行——`subprocess.run(args_list, shell=False, timeout=N, capture_output=True, preexec_fn=set_limits, cwd=sandbox_dir)` | 与现有 bash 工具安全模式一致。`preexec_fn` 在 fork 后 exec 前设置 resource limits，只影响子进程。`shell=False` 防止命令注入 |
| **resource** | (stdlib, Unix) | 子进程硬资源限制——`setrlimit(RLIMIT_CPU, RLIMIT_AS, RLIMIT_FSIZE, RLIMIT_NPROC)` | 内核级强制限制，子进程无法绕过。WSL2 完全支持。防止 LLM 生成的代码出现死循环、内存泄漏、fork 炸弹、磁盘写满 |
| **tempfile** | (stdlib) | 沙箱子目录创建——`tempfile.mkdtemp(prefix="tool_sandbox_")` | 每次工具执行创建独立临时目录，工具只能在此目录内读写。执行完毕后清理 |
| **shlex** | (stdlib) | Bash 语法检查 `bash -n` 的参数安全拼接——`shlex.quote(filepath)` | 已有依赖。用于 Bash 动态工具的语法验证阶段 |

### 动态工具加载策略（按持久化级别）

```
会话级工具 (Session-level)
  └─ exec(compiled_code, restricted_globals)
     └─ 提取函数 → 手动构造 ToolMetadata → registry.register_meta()

沙箱级工具 (Sandbox-level)
  └─ 代码保存到 .sandbox/tools/{name}.py
     └─ exec() 加载 + 沙箱目录作为工作目录

项目级工具 (Project-level)
  └─ 代码保存到 project/tools/{name}.py
     └─ importlib.util.spec_from_file_location() 加载
        └─ 注册到 sys.modules 防止重复
           └─ Agent 启动时自动扫描 project/tools/ 加载所有持久化工具
```

### 执行隔离策略（按权限级别）

| 权限级别 | 执行方式 | 隔离措施 | 超时 |
|---------|---------|---------|------|
| **SAFE** | 当前进程 `exec()` + 受限 globals | `__builtins__` 替换为安全子集（移除 `eval`, `exec`, `__import__`, `compile`, `open`, `breakpoint`） | 30s（默认） |
| **MODERATE** | `subprocess` 子进程 | `preexec_fn` resource limits + `chdir` 沙箱子目录 | 60s |
| **DANGEROUS** | `subprocess` 子进程 + 前端确认 | resource limits + 沙箱子目录 + 网络禁用 + **用户确认弹窗** | 120s |

### 与现有系统集成点

```
ToolRegistry.register_meta()        ← DynamicToolCreator 构造 ToolMetadata 后直接注册
ToolExecutor.execute()              ← 动态工具复用现有超时/重试/错误分类管线
EventBus.publish()                  ← 新事件: tool_created, tool_updated, tool_deleted, tool_validated
PermissionLevel (SAFE/MODERATE/DANGEROUS) ← 动态工具复用三级权限
ToolResult                          ← 动态工具结果包装（含 truncated/overflow 处理）
GuardPipeline                       ← AST 扫描作为新 Guard 插入管线
```

## Recommended Stack — 前端（v1.1 新增）

### 代码编辑器与 Diff 展示

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **@monaco-editor/react** | 4.7.0 (stable) / 4.8.0-rc.3 (React 19) | 代码展示 + Diff 对比——`Editor`（只读模式）用于 ToolCreationDialog 代码审查；`DiffEditor` 用于工具更新时的 side-by-side diff | VS Code 内核，Python/Bash 语法高亮开箱即用。内置 `DiffEditor` 提供 split（左右对比）和 unified（内联对比）两种模式。单依赖覆盖两个 UI 需求。React 19 兼容性通过 `@next` tag 获得 |

### 前端组件集成矩阵

| UI 场景 | 使用组件 | 配置 |
|---------|---------|------|
| **工具创建确认——代码展示** | `@monaco-editor/react` `Editor` | `value={code}`, `language="python"`, `options={{ readOnly: true, minimap: { enabled: false }, lineNumbers: "on" }}` |
| **工具更新——新旧对比** | `@monaco-editor/react` `DiffEditor` | `original={oldCode}`, `modified={newCode}`, `language="python"`, `options={{ readOnly: true, renderSideBySide: true }}` |
| **工具管理面板——查看代码** | `@monaco-editor/react` `Editor` | `value={code}`, `language="python"`, `options={{ readOnly: true, minimap: { enabled: false } }}` |
| **工具管理面板——查看 Bash 工具** | `@monaco-editor/react` `Editor` | `value={code}`, `language="shell"` |
| **持久化级别选择** | shadcn/ui `Select` + `RadioGroup` | 会话级 / 沙箱级 / 项目级 三选一 |
| **目录权限授予** | shadcn/ui `Input` + `Checkbox` | 输入允许访问的目录路径列表 |
| **风险提示横幅** | shadcn/ui `Alert` + `Badge` | AST 扫描结果可视化（危险模块检测 / 网络调用检测 / 危险函数检测） |

## Installation

```bash
# Python 后端 — 无新增 PyPI 依赖！
# ast, importlib.util, subprocess, resource, tempfile, shlex 全部是 Python 3.12+ stdlib

# 前端 — 唯一新增依赖
cd frontend

# React 19 兼容版（推荐，项目使用 React 19.2.6）
pnpm add @monaco-editor/react@next

# 稳定版（React 16.8–18）
# pnpm add @monaco-editor/react@4.7.0

# Monaco Editor 本身由 @monaco-editor/react 异步加载，无需手动安装 monaco-editor
# Vite 8 无需额外插件——@monaco-editor/react 内置了 ESM Worker 加载逻辑
```

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| **ast (stdlib)** 预执行扫描 | **RestrictedPython 8.1** | 当安全需求从"LLM 生成 + 人工审核"升级为"完全不可信外部代码"。RestrictedPython 通过 AST 转换移除危险能力（`open`、`__import__` 全禁），但动态工具需要文件 I/O 和系统命令能力——RestrictedPython 太受限。注意 CVE-2025-22153 等历史逃逸 |
| **@monaco-editor/react** | **@uiw/react-codemirror v4.25 + @codemirror/merge v6.12** | 当包体积是关键约束时。CodeMirror 6 核心 ~100KB，加上 merge 扩展 ~300KB total（vs Monaco ~5MB）。但 diff 视图不如 Monaco 精致，且需要两个包分别处理编辑和 diff。React 19 兼容性更好（@uiw/react-codemirror v4.25 已适配 React 19） |
| **subprocess + resource** | **Docker SDK / gVisor** | 当需要内核级 syscall 过滤和完全网络隔离时。但对于学习项目，`subprocess` + `resource.setrlimit` + `tempfile.mkdtemp` 三层隔离已足够覆盖"LLM 生成代码"的风险面 |
| **exec()** (会话级) | **importlib.util** (会话级) | `importlib` 更规范但会污染 `sys.modules`。会话级工具生命周期短，不需要模块语义——`exec()` 更简单。项目级工具必须用 `importlib.util` |
| **react-diff-viewer-continued** (作为辅助) | — | 轻量 GitHub-style diff 展示（v4.2.2, ~50KB）。如果只需要 view-only diff 且不想引入 Monaco 体积，可作为替代。但当前推荐 Monaco 单依赖方案 |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| **RestrictedPython** | 太受限——动态工具需要文件 I/O 和 `subprocess` 调用系统命令（如 `df`, `du`, `find`）。且已有多起 CVE 绕过（CVE-2025-22153 `try/except*` 逃逸，CVE-2023-37271 栈帧逃逸）。在"LLM 生成 + 人工审核"安全模型下是过度工程 | **ast 预执行扫描** + `subprocess` 隔离 + `resource` 限制。三层防御但保留工具实用能力 |
| **Docker SDK / gVisor / Firecracker** | 操作复杂度过高。需要 Docker daemon、镜像管理、额外权限。学习项目不应引入容器编排——先学会走（stdlib 隔离），再学跑（容器） | **subprocess + resource.setrlimit + tempfile.mkdtemp**。零外部依赖，纯 Python stdlib |
| **monaco-editor (裸包)** | 需要手动配置 Web Worker 打包（Vite 需要额外插件配置 Worker 加载路径）。`@monaco-editor/react` 封装了所有这些细节 | **@monaco-editor/react** |
| **react-ace** | Ace Editor 已基本停止维护，对 Python 3.12+ 新语法的支持滞后。Monaco 是事实标准的 Web 代码编辑器 | **@monaco-editor/react** |
| **react-diff-viewer-continued (作为主方案)** | 纯展示组件（不可编辑），需要额外集成 Prism/highlight.js 做语法高亮。功能与 Monaco DiffEditor 重叠但品质不如 | **@monaco-editor/react DiffEditor**——同一依赖内建支持 |
| **PyPy sandbox** | 已基本废弃，需要 PyPy 运行时。项目使用 CPython 3.13 | **subprocess + resource** |
| **Docker (initial 沙箱)** | CLAUDE.md 明确声明 "Adds operational complexity before the core logic is solid"——该原则同样适用于工具沙箱 | **stdlib 隔离** |
| **`shell=True`** | CLAUDE.md 明确禁止：命令注入风险 | **`subprocess.run([...], shell=False)`** |

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| ast (stdlib 3.12+) | Python 3.12+（项目 requires-python>=3.12） | `match`/`case` AST 节点在 3.10+ 支持，3.12 完全稳定 |
| importlib.util (stdlib) | Python 3.4+ | `spec_from_file_location` 自 3.4 起稳定；`SourceFileLoader.load_module()` 已废弃不要用 |
| resource (stdlib) | Linux/macOS/WSL2 | Windows 不支持但项目运行在 WSL2 Linux。`RLIMIT_*` 常量在所有 Unix 上可用 |
| subprocess.preexec_fn | Unix only | 在 `_posixsubprocess` 模块中实现，Windows 上 `preexec_fn` 参数被忽略 |
| @monaco-editor/react 4.8.0-rc.3 | React 19.2.x（项目当前） | Release candidate。v4.7.0 稳定版目标 React 16-18。如果 rc 不稳定，降级方案见下 |
| @uiw/react-codemirror 4.25.10 | React 19.x | 完全支持 React 19。作为 Monaco 的降级替代方案 |
| @codemirror/merge 6.12.1 | CodeMirror 6.0.2 | 官方维护的 merge/diff 扩展，稳定成熟 |

> **React 19 + Monaco 兼容性备选方案：** 如果 `@monaco-editor/react@next` (4.8.0-rc.3) 在开发中遇到问题，切换为 `@uiw/react-codemirror@4.25.10` + `@codemirror/merge@6.12.1`。CodeMirror 方案在 React 19 上更成熟，代价是 diff 视图不如 Monaco 精致。

## Stack Patterns by Variant

### AST 扫描器架构

```python
# 三层扫描，结果累积为 Warning 列表（不做硬阻断）
class SecurityVisitor(ast.NodeVisitor):
    FORBIDDEN_IMPORTS = {"os", "sys", "subprocess", "ctypes", "multiprocessing", "socket", "requests", "httpx"}
    FORBIDDEN_CALLS = {"eval", "exec", "compile", "__import__", "breakpoint"}
    BYPASS_PATTERNS = {"getattr", "__builtins__", "__globals__", "__class__"}

    def visit_Import(self, node): ...      # 检测危险导入
    def visit_ImportFrom(self, node): ...  # 检测 from X import Y
    def visit_Call(self, node): ...        # 检测危险函数调用
    def visit_Attribute(self, node): ...   # 检测间接绕过模式
```

### 动态工具元数据构造（不使用 @tool 装饰器）

```python
# DynamicToolCreator 手动构造 ToolMetadata
meta = ToolMetadata(
    name="dynamic.my_tool",
    description="Agent-generated disk cleanup tool",
    permission_level=PermissionLevel.MODERATE,  # 默认 MODERATE
    timeout=60.0,
    retry=RetryConfig(max_attempts=1),  # 动态工具默认不重试
    tags=["dynamic", "session:{id}"],
    param_schema=extracted_schema,    # 从函数签名提取
    func_ref=loaded_function,         # exec() 或 importlib 加载的函数
    validation_model=built_model,     # Pydantic create_model() 构建
)
registry.register_meta(meta)
```

### Monaco Editor 在 Vite 8 中的配置

无需额外配置。`@monaco-editor/react` v4.x 使用默认 ESM Worker 加载路径，Vite 8 (Rolldown) 原生支持。Monaco Worker 文件通过动态 `import()` 异步加载，不影响首屏时间。

## Sources

- [RestrictedPython 8.0 changes (CVE-2025-22153 fix)](https://restrictedpython.readthedocs.io/en/stable/changes.html) — MEDIUM 置信度（官方文档）
- [RestrictedPython PyPI](https://pypi.org/project/RestrictedPython/) — MEDIUM 置信度（PyPI 注册表）
- [CVE-2026-27952 — RestrictedPython + numpy 沙箱逃逸](https://cvepremium.circl.lu/vuln/fkie_cve-2026-27952) — LOW 置信度（第三方 CVE 数据库）
- [Python importlib.util 动态加载指南 (Runebook)](https://runebook.dev/en/docs/python/library/importlib/importlib.machinery.SourceFileLoader) — MEDIUM 置信度（社区文档，内容与官方一致）
- [Python AST 安全扫描实践 (jb51, 2025)](https://www.jb51.net/python/354141w52.htm) — MEDIUM 置信度（中文技术社区）
- [Microsoft HVE-Core AST 安全验证](https://github.com/microsoft/hve-core/issues/1017) — MEDIUM 置信度（微软开源项目）
- [@monaco-editor/react DeepWiki](https://deepwiki.com/suren-atoyan/monaco-react) — HIGH 置信度（项目文档聚合）
- [@monaco-editor/react npm](https://www.npmjs.com/package/@monaco-editor/react) — HIGH 置信度（npm registry，版本号经 `npm view` 验证）
- [@codemirror/merge npm v6.12.1](https://www.npmjs.com/package/@codemirror/merge) — HIGH 置信度（npm registry）
- [@uiw/react-codemirror npm v4.25.10](https://www.npmjs.com/package/@uiw/react-codemirror) — HIGH 置信度（npm registry）
- [react-diff-viewer-continued npm v4.2.2](https://www.npmjs.com/package/react-diff-viewer-continued) — HIGH 置信度（npm registry）
- [Monaco vs CodeMirror 深度对比 (CSDN, 2025)](https://blog.csdn.net/weixin_28842269/article/details/159599623) — MEDIUM 置信度（技术博客多源一致）
- [Python resource 模块文档 (ReadTheDocs)](https://python-documentation-cn.readthedocs.io/en/latest/library/resource.html) — HIGH 置信度（官方文档镜像）
- [sandbox-runtime PyPI (Anthropic)](https://pypi.org/project/sandbox-runtime/) — LOW 置信度（仅作实现参考，未直接使用）

---
*Stack research for: loopAI v1.1 — Agent 动态工具创建系统*
*Researched: 2026-05-31*
