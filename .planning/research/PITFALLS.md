# Pitfalls Research

**Domain:** Agent 动态工具创建系统 — LLM Agent 自主编写并执行代码
**Researched:** 2026-05-31
**Confidence:** HIGH（基于 2025-2026 年 15+ 真实 CVE 披露、代码审计报告和框架安全公告）

## Critical Pitfalls

### Pitfall 1: AST/Regex 源码级过滤被 Python 内省绕过

**What goes wrong:**
对 Agent 生成的 Python 代码执行 AST 分析或正则过滤，阻止 `exec`、`eval`、`os` 等危险名称。LLM 生成的代码使用 Python 内省机制（`().__class__.__bases__[0].__subclasses__()`、异常帧遍历、`types.FunctionType`）绕过所有源码级检查，获得真实 `exec`/`__import__` 引用并执行任意系统命令。

2026 年披露的真实案例：
- **CVE-2026-40158** — PraisonAI AST 过滤器只检查 `ast.Attribute` 节点，LLM 生成 `type.__getattribute__('__subclasses__')` 通过 `ast.Constant` 传危险名称完全绕过
- **CVE-2026-39888** — PraisonAI 子进程模式封堵列表仅 11 个名称（直接执行模式有 30+），缺少 `__traceback__`、`tb_frame`、`f_back`、`f_builtins`，通过捕获异常遍历帧栈恢复 `exec`
- **CVE-2026-42079** — PPTAgent 直接对 LLM 生成内容调用 `eval()`，builtins 完全在作用域内

**Why it happens:**
- Python 是极度内省的动态语言，运行时对象图可被完全遍历
- 开发者误以为"我封了 os 和 subprocess 就安全了"，实际可绕过的入口超过 30 个
- AST 过滤只解析代码结构但不追踪数据流——变量赋值绕过了名称检查
- `compile()` + `types.FunctionType` 可以在不调用 `exec()` 的情况下执行任意代码对象

**How to avoid:**

1. **永不信任进程内沙箱** — Python 不可在语言层面被沙箱化。共识结论：必须在 Python 之外隔离，不能在 Python 之内隔离。即使是最激进的运行时限制（`del __builtins__`、删除 `eval`）也能通过对象图轻易绕过。

2. **必须使用的外部隔离方案**：

| 方案 | 隔离级别 | 适用场景 |
|------|----------|----------|
| **seccomp-bpf + Landlock** | OS 级 syscall 过滤 + 路径沙箱 | 本地开发阶段（Linux） |
| **Docker + --read-only + --cap-drop ALL** | 容器隔离 | 单用户受信任代码 |
| **gVisor (runsc)** | 用户态内核截获 syscall | LLM 生成代码（中风险） |
| **Firecracker microVM** | 独立 Guest 内核 KVM | 多租户/生产环境（金标准） |
| **nsjail** | 命名空间 + cgroups + seccomp | Google 级轻量隔离 |

3. **代码扫描只做第一道防线，不做唯一防线**：
   - AST 分析快速拦截明显危险模式（`eval`、`exec`、`os.system`、`subprocess.call`、`ctypes.CDLL`）
   - 不作信任边界 — 扫不过 ≠ 安全，扫过了 ≠ 安全
   - 扫描后仍要通过外部沙箱执行

4. **危险模块全量封堵检查** — 至少扫描以下所有入口（不仅是 `os` 和 `subprocess`）：
   ```python
   DANGEROUS_NAMES = {
       "os", "subprocess", "sys", "ctypes", "cffi", "mmap",
       "gc", "code", "types.FunctionType", "types.CodeType",
       "marshal", "pickle", "imp", "importlib", "pdb",
       "builtins.__import__", "builtins.exec", "builtins.eval",
       "builtins.compile", "builtins.open",
       "__subclasses__", "__bases__", "__globals__", "__code__",
       "__traceback__", "tb_frame", "f_back", "f_builtins",
       "gi_frame", "gi_code", "cr_frame",
   }
   ```

5. **代码结构规则** — 拒绝任何包含异常帧遍历、`type()` 元编程、`ctypes.CDLL` 调用的代码

**Warning signs:**
- AST 扫描器中危险名称列表 < 30 个
- 封堵列表与 smolagents、PraisonAI 或 Agenta 已披露的绕过路径有重叠的遗漏项
- `compile()` 或 `types` 在使用中未被监控
- 日志中出现 `__subclasses__`、`__traceback__`、`tb_frame` 等运行时属性访问

**Phase to address:**
Phase 1（动态工具创建核心）— 语法检查 + 危险模块扫描必须在工具注册前执行。Phase 2（沙箱限制）— 引入 gVisor/nsjail 级的外部隔离。

---

### Pitfall 2: 代码注入 — Agent 生成包含漏洞的代码污染工具集

**What goes wrong:**
Agent 生成的 Python/Bash 代码通过了语法检查，内部却包含了注入漏洞、凭证窃取逻辑或环境变量外泄。因为代码是通过安全检查的（"AST 没报错"），它被注册为合法工具。用户后续调用该工具时，恶意代码在工具执行上下文中运行，享有与其他静态工具同等的权限和信任。

具体攻击形式：
- **凭证外泄** — `import os; os.environ` 读取 `OPENAI_API_KEY`、`GITHUB_TOKEN` 等并通过 HTTP 外传
- **文件侧信道** — 生成的工具读写沙箱外文件（通过符号链接、硬链接或路径遍历）
- **时间炸弹** — 代码表面正常，但在特定日期/条件触发恶意行为
- **间接提示注入传播** — 工具输出中包含的恶意内容进入主 Agent 上下文，污染后续推理

**Why it happens:**
- "AST 无报错 = 代码安全"的假设是致命的逻辑错误
- 语法检查只验证代码合法性，不验证代码意图
- 当前不存在"意图验证"机制——Agent 声称代码做 X，但实际执行后做 Y
- LLM 有时听从指令生成恶意代码（通过提示注入诱导），有时"幻觉"出危险代码片段

**How to avoid:**

1. **代码语义审查管线**（注册前的强制检查，不仅仅语法检查）：
   ```
   Agent 生成代码
     -> 1. AST 语法检查（ast.parse）
     -> 2. 危险名称扫描（DANGEROUS_NAMES 全量扫描）
     -> 3. I/O 操作审计（open/read/write/http/socket）
     -> 4. 环境变量访问审计（os.environ/os.getenv）
     -> 5. 网络访问审计（urllib/requests/socket/httpx）
     -> 6. 子进程创建审计（subprocess/os.system/popen）
     -> 7. 通过 → Agent 自测验证
     -> 8. 自测通过 → 用户人工确认 → 注册
   ```

2. **禁止生成的代码访问以下资源**（零例外）：
   - `os.environ` / `os.getenv` — 不提供环境变量给动态工具
   - 网络访问 — 默认 `deny-all egress`，沙箱内禁止网络
   - 子进程创建 — 禁止在动态工具内 `subprocess` 或 `os.system`
   - 其他工具的注册表（防止工具间交叉污染）
   - 文件系统外部路径（必须限制在沙箱子目录内）

3. **Agent 自测必须在隔离沙箱中运行** — 自测执行的代码隔离级别须与实际执行一致

4. **意图验证提示** — 在 system prompt 中要求 Agent 在生成代码前解释：
   - 此工具做什么？
   - 它使用哪些资源？
   - 是否涉及文件读写、环境变量、网络请求？
   代码生成后，用上述问题交叉比对实际代码内容

5. **不要在动态工具内提供 `exec`/`eval` 能力** — 即使沙箱内的动态工具，也不应具备代码生成/执行能力（防止递归逃逸）

**Warning signs:**
- 动态工具代码中出现 `os.environ`、网络请求、子进程调用
- Agent 在代码中嵌入了未经解释的外部 URL
- 工具描述与实际代码行为不匹配
- 生成的代码包含 base64 编码字符串（常见混淆手法）

**Phase to address:**
Phase 1（代码校验）— 语法检查 + 安全审计管线。Phase 2（沙箱限制）— 隔离执行 + 网络禁止。Phase 3（用户确认）— 前端代码展示 + 意图比对。

---

### Pitfall 3: 资源耗尽 — Agent 生成死循环/内存炸弹/磁盘炸弹

**What goes wrong:**
LLM 生成的代码包含无限循环（`while True`）、指数级递归、大对象分配（`"x" * 10**12`）、或磁盘填充操作。因为代码通过了语法检查，它在执行时耗尽 CPU/内存/磁盘资源，导致 Agent 进程崩溃，连累同进程内的主 Agent 循环。在共享进程架构（loopAI 的设计）下，一个动态工具的资源耗尽可以拖垮整个 Agent 系统。

**Why it happens:**
- LLM 对代码性能/资源消耗没有直觉——它生成的代码可能无意中触发资源风暴
- 恶意注入可以让 LLM 故意生成资源炸弹（fork bomb、disk fill）
- 动态工具继承了主 Agent 的资源限制，没有独立的 `rlimit` 配置
- 语法检查无法识别逻辑问题（死循环、大对象、未限制的递归）

**How to avoid:**

1. **独立的资源限制（每个动态工具执行前设置 `resource.setrlimit`）**：
   ```python
   import resource
   # CPU 时间限制
   resource.setrlimit(resource.RLIMIT_CPU, (5, 10))      # 软 5 秒 CPU / 硬 10 秒
   # 内存限制
   resource.setrlimit(resource.RLIMIT_AS, (256*1024*1024, 512*1024*1024))  # 256MB/512MB
   # 进程数限制（防 fork bomb）
   resource.setrlimit(resource.RLIMIT_NPROC, (50, 100))
   # 文件大小限制（防磁盘填充）
   resource.setrlimit(resource.RLIMIT_FSIZE, (10*1024*1024, 50*1024*1024))  # 10MB/50MB
   # 打开文件数限制
   resource.setrlimit(resource.RLIMIT_NOFILE, (64, 128))
   ```

2. **AST 级的循环和递归防护**：
   - 扫描 `while True`、未限定的 `while`（无有效退出条件）
   - 扫描深度递归（超过 100 的无基础情况递归）
   - 扫描大常量（字符串/列表超过 1MB 的字面量）
   - 扫描 `*` 操作符与大量级常数（`[0] * 10**9`）

3. **独立执行的超时控制**：
   - 每动态工具独立超时（默认 30 秒，比静态工具的 60 秒短）
   - 硬超时通过 `signal.SIGALRM` + 进程级定时器（不依赖 Python 的 `asyncio.wait_for`，因为死循环不释放 GIL）
   - 超时后强制 SIGKILL 子进程（不是 SIGTERM）

4. **代码复杂度限制**（AST 级别检查）：
   - 最大 AST 节点数：500（阻止超大代码块）
   - 最大递归深度：100
   - 最大循环嵌套层级：3
   - 最大字符串长度：1MB
   - 拒绝包含 `fork`、`clone`、`spawn` 的代码

5. **独立进程执行** — 动态工具的代码执行必须在独立子进程中（`multiprocessing` 或 `subprocess`），与主 Agent 进程完全隔离。子进程崩溃不应影响主 Agent。

**Warning signs:**
- 工具执行时间超过预期（无进度更新）
- 系统 CPU 使用率骤增
- 内存使用量持续增长不降
- 10K+ 新文件出现在沙箱目录中
- `/tmp` 或工作目录出现大量临时文件

**Phase to address:**
Phase 2（沙箱限制）— 资源限制 + 独立进程执行 + 超时控制。Phase 1 仅做 AST 级的循环/递归静态扫描。

---

### Pitfall 4: 工具毒化 — 恶意动态工具污染 ToolRegistry 并劫持 Agent 执行

**What goes wrong:**
Agent 生成的动态工具被注册到 ToolRegistry。如果工具名称与现有静态工具冲突，恶意工具可"遮盖"合法工具。更危险的是，工具的 `description` 字段（注入到 system prompt）包含间接提示注入载荷，操纵 LLM 后续的工具选择决策，将 Agent 引导到攻击者控制的执行路径。由于现有 ToolRegistry 为扁平命名空间设计（不区分静态工具/动态工具），工具毒化的影响面是整个 Agent 系统。

2026 年真实披露：
- **CVE-2026-30856** — Tencent WeKnora MCP 客户端命名冲突：恶意 MCP 服务器注册与合法服务器同名的工具，用间接提示注入劫持 LLM 流程
- **CVE-2026-44339** — PraisonAI `ToolExecutionMixin.execute_tool` 回退到 `globals()` 和 `getattr(__main__, ...)`，允许调用任何未声明的函数
- **Strands-agents** — `ToolLoader` 按工具名直接插入 `sys.modules`，允许覆盖 stdlib 模块（如 `os`、`json`）
- **CoSAI OASIS** — 正式定义 Tool Registry Poisoning (TRP) 为非提示注入的独立风险类别

**Why it happens:**
- ToolRegistry 使用扁平命名空间，无静态/动态工具的区分
- 工具名称冲突策略是简单的"后注册覆盖先注册"（或反之），均不安全
- 工具 description 未经净化直接注入 system prompt（间接提示注入载体）
- 缺少工具身份验证——无法验证"调用方引用的工具名"和"实际被执行的可调用对象"之间的绑定

**How to avoid:**

1. **命名空间分离** — ToolRegistry 必须区分静态工具和动态工具：
   ```python
   registry = ToolRegistry()
   registry._static_tools: dict[str, ToolMetadata] = {}   # @tool 装饰的静态工具
   registry._dynamic_tools: dict[str, ToolMetadata] = {}  # Agent 生成的动态工具

   # 命名前缀强制
   # 静态工具: "bash.df", "disk.check_usage"
   # 动态工具: "dynamic.cleanup_cache_00a1b2c3"  ← 必须包含随机后缀
   ```

2. **冲突检测而非静默覆盖**：
   - 动态工具名称与静态工具冲突 → 拒绝注册
   - 动态工具与已有动态工具冲突 → 展示 diff，要求用户选择覆盖 or 拒绝
   - 命名策略：`dynamic.{hash[:8]}_{简洁名称}` → 强制唯一性

3. **工具描述净化** — 在注入 system prompt 前清理：
   - 截断超长描述（最大 500 字符）
   - 扫描并拒绝描述中的指令性语言（"你应该"、"你必须"、"ignore previous instructions"）
   - 用固定模板包装动态工具描述：`"[动态工具] {name}: {description} [沙箱隔离 | 会话级]"`

4. **明确的信任边界** — 动态工具的权限必须低于静态工具：
   - 动态工具默认 `PermissionLevel.MODERATE`（需用户确认）
   - 动态工具不得访问其他工具的 `func_ref`（不可反射调用）
   - 动态工具不可注册 `PermissionLevel.SAFE`（防止自动放行恶意工具）
   - 提示注入扫描作为额外防线 — 使用 AgentShield / CloneGuard 模式在工具描述和输出上运行注入检测

5. **不向后备选机制** — 永不通过 `globals()`、`__main__`、或未限定的 `sys.modules` 查找解析工具名。工具必须显式注册到 Registry。

**Warning signs:**
- 动态工具名与静态工具名冲突（无前缀区分）
- 工具描述中包含指令性语言或 "must" / "should" 句式
- Agent 选择动态工具的概率突然上升（可能被劫持）
- 相同前缀的工具数量异常增加（工具注入洪泛）
- 用户未发起的工具调用链（意图偏离）

**Phase to address:**
Phase 1（动态工具注册）— 命名空间分离 + 冲突检测 + 描述净化。Phase 3（工具管理）— 前端展示 + 禁用/启用 + 权限审计。

---

### Pitfall 5: 子进程沙箱逃逸 — `ctypes`、`sys`、`statistics` 等"安全模块"的传递性访问

**What goes wrong:**
即使沙箱限制了 `os` 和 `subprocess` 的导入，LLM 生成的代码通过**看似安全的模块**获取系统访问：
- `ctypes.CDLL(None).system("id")` — 直接加载 libc 调用 `system()`，完全绕过 Python 级 import hook
- `statistics.sys.modules["os"]` — 通过允许列表中的 `statistics` 模块获取 `sys`，再通过 `sys.modules` 获取 `os`
- 异常帧遍历 — 触发行数异常的捕获，通过 `__traceback__.tb_frame.f_back.f_builtins` 恢复 `__import__`

2026 年已确认的绕过：
- **GHSA-4675-36f9-wf6r** — `ctypes` 不在 picklescan 的危险模块列表中
- **huggingface/smolagents** — `LocalPythonExecutor` 的 `DANGEROUS_MODULES` 缺少 `ctypes`；`statistics.sys.modules` 传递性访问被利用获取 `os`
- **Agenta CVE-2026-27952** — `numpy` 在白名单中，`numpy.ma.core.inspect` → `sys.modules` → `os.system`

**Why it happens:**
- 危险模块列表不完整（只关注"明显"的 `os`/`subprocess`，忽略传递性入口）
- 导入白名单与精细子模块限制之间脱节（允许 `statistics` 但不阻止 `statistics.sys`）
- 动态模块加载（`importlib`、`imp`）和代码对象重建（`compile` + `marshal` + `types.FunctionType`）未被监控
- Python 的"一切皆对象"哲学使得运行时内省难以彻底封堵

**How to avoid:**

1. **危险模块全量列表**（必须全部封堵，不仅是 `os`/`subprocess`）：
   ```python
   DANGEROUS_MODULES = {
       # 直接系统调用入口
       "os", "subprocess",
       # C 库直接接口
       "ctypes", "cffi",
       # 系统内省和代码执行入口
       "sys", "gc", "code", "types", "marshal",
       "importlib", "imp", "pdb", "bdb", "inspect",
       "tracemalloc", "faulthandler", "traceback",
       # 内存直接操作
       "mmap", "signal",
       # 序列化（可执行任意代码）
       "pickle", "shelve",
       # 进程管理
       "multiprocessing", "concurrent.futures.process",
       # Web/网络库（在无网沙箱中禁止）
       "requests", "urllib", "http", "socket", "asyncio",
       "aiohttp", "httpx", "websockets",
       # 文件系统操作（超权限）
       "pathlib", "shutil", "glob", "fnmatch",
   }
   ```

2. **只允许绝对安全的模块**（最小化导入白名单）：
   ```python
   ALLOWED_MODULES = {
       # 纯计算/无副作用的模块
       "math", "itertools", "collections", "functools",
       "operator", "decimal", "fractions",
       # 文本/日期处理
       "re", "string", "datetime", "textwrap",
       # 数据结构
       "json", "csv", "dataclasses", "enum", "typing",
       # JSON 和 csv 需要额外处理——禁止直接文件 I/O
   }
   ```

3. **模块导入拦截** — 在沙箱执行前植入 import hook：
   ```python
   import builtins
   _real_import = builtins.__import__
   def _sandboxed_import(name, *args, **kwargs):
       if name in DANGEROUS_MODULES:
           raise ImportError(f"Module '{name}' is blocked in sandbox")
       # 检查子模块传递访问
       top_level = name.split('.')[0]
       if top_level in DANGEROUS_MODULES:
           raise ImportError(f"Submodule of '{top_level}' is blocked")
       return _real_import(name, *args, **kwargs)
   builtins.__import__ = _sandboxed_import
   ```

4. **必须使用外部隔离** — 即使 import hook + AST 扫描双保险，仍必须在外部沙箱（gVisor/nsjail/Firecracker）中执行，因为 import hook 本身可被绕过（`sys.modules` 直读、`ctypes` 绕过）

5. **禁止 `compile()` 和动态代码生成** — 沙箱内的动态工具不得再执行 `compile()`、`exec()`、`eval()` 或 `types.FunctionType`。防止沙箱内代码进行"二次动态代码生成"。

**Warning signs:**
- 导入日志中出现被拦截的模块访问尝试
- `ctypes` 或 `cffi` 出现在代码中（即使以别名形式）
- 异常帧/回溯被捕获为字符串（`str(e)` 或 `repr(e)`）
- `sys.modules` 的直接引用
- `statistics.sys` 或 `math.sys` 的访问模式

**Phase to address:**
Phase 1（代码校验）— 危险模块扫描 + import hook 植入。Phase 2（沙箱限制）— 外部沙箱隔离使 Python 级绕过变为无效。

---

### Pitfall 6: 动态工具与静态工具的集成冲突

**What goes wrong:**
新加入的动态工具系统与现有 v1.0 基础设施产生集成断裂：
- **EventBus 事件类型**：v1.0 的 EventBus 定义的事件类型（`tool_call_start`、`tool_call_end` 等）未区分静态/动态工具。前端凭事件 payload 无法判断工具是静态还是动态，导致确认弹窗逻辑混乱（动态工具需要不同的确认 UI）。
- **ToolRegistry 命名冲突**：现有静态工具（如 `bash.df`）和动态工具（如 `dynamic.df_custom`）共享扁平命名空间，LLM 可能误选动态工具替代静态工具。
- **PermissionGuard 确认流程不匹配**：静态工具的 `DANGEROUS` 级别触发 `confirmation_required` 事件，但动态工具可能需要完全不同的确认流程（展示代码 + 持久化级别 + 目录权限）。
- **CircuitBreaker 误触发**：动态工具首次执行可能失败（需要调测），现有的 CircuitBreaker 将连续失败视为工具不可用，可能错误熔断还在调测阶段的动态工具。

**Why it happens:**
- v1.0 架构假设所有工具都是开发者预先定义并经过测试的静态工具
- EventBus 的 `schemas.py` 中事件类型是枚举，未设计扩展点（新增类型需修改核心 schema）
- ToolRegistry 为单一字典设计，无分区/命名空间/优先级概念
- PermissionGuard 的确认逻辑硬编码为 DANGEROUS → 用户确认，缺少语义区分

**How to avoid:**

1. **EventBus 事件类型扩展**（扩展而非重新设计）：
   ```python
   # 新增事件类型（不修改现有静态工具事件）
   event_type: "dynamic_tool_created"     # 工具注册成功
   event_type: "dynamic_tool_create_failed"  # 创建失败
   event_type: "dynamic_tool_call_start"  # 动态工具被调用
   event_type: "dynamic_tool_call_end"    # 动态工具调用完成
   event_type: "dynamic_tool_verify"      # Agent 自测执行中
   ```

2. **ToolRegistry 分区存储**：
   ```python
   class ToolRegistry:
       def __init__(self):
           self._static: dict[str, ToolMetadata] = {}
           self._dynamic: dict[str, ToolMetadata] = {}
           
       def get(self, name: str) -> ToolMetadata | None:
           # 如果 LLM 调用动态工具但静态工具存在同名 → 优先返回静态工具
           # 如果传入全限定名 (dynamic.xxx) → 仅查询动态区
           ...
       def get_for_llm(self) -> list[dict]:
           # 返回给 LLM 的工具列表，动态工具需带标签标注
           ...
   ```

3. **PermissionGuard 分级确认**：
   - `PermissionLevel.DYNAMIC` 新增级别（或通过 source 标注区分）
   - 动态工具的确认事件 payload 中新增字段：`source: "dynamic"`、`code_preview`、`persistence_level`、`sandbox_scope`
   - 前端据此展示不同的确认 UI（代码预览 + 持久化选择，而非简单的"批准/拒绝"）

4. **CircuitBreaker 豁免动态工具**：
   - 动态工具前 N 次执行（建议 3 次）不触发 CircuitBreaker
   - 仅记录失败次数，供用户在前端查看
   - 第 N+1 次起纳入常规 CircuitBreaker 逻辑

5. **系统提示词更新**：
   - 动态工具在 system prompt 中以特殊标签呈现：`[动态工具 - 沙箱隔离 - 需要确认]`
   - 注入规则："优先使用内置静态工具；仅在需要新功能时创建动态工具"
   - 动态工具描述包含其持久化级别和在何时可用

**Warning signs:**
- EventBus 日志中出现事件类型分发异常
- 前端确认弹窗接收到的 payload 缺少必需字段
- LLM 在拥有同功能静态工具时倾向选择动态工具
- CircuitBreaker 频频熔断刚注册的动态工具

**Phase to address:**
Phase 1（动态工具创建）— ToolRegistry 分区 + EventBus schema 扩展。Phase 3（工具管理）— PermissionGuard 适配 + 前端确认 UI 差异化。Phase 4（集成验证）— CircuitBreaker 豁免 + 端到端验证。

---

### Pitfall 7: 用户确认门被 LLM 绕过

**What goes wrong:**
动态工具的创建流程包含用户确认步骤。但如果确认机制依赖 LLM 的判断（如"Agent 自测通过后自动批准"），攻击者可以通过提示注入让 LLM 产生虚假的"测试通过"报告，绕过人工审查。Agent 自主决定注册工具而无人知晓。

更隐蔽的形式：Agent 生成一个看似无害的工具（如 `disk_checker`），自测返回"通过"。用户未见代码直接批准。工具内部实际上包含了在特定条件下擦除日志的代码。由于工具已注册为"已批准"，后续执行不再触发确认。

**Why it happens:**
- 用户确认流程与 Agent 自测结果之间存在信任短路——"自测通过"被等同于"安全"
- LLM 生成的自测用例可能刻意回避危险码路径（对抗性测试设计）
- 自动批准逻辑：`if self_test_passed and no_syntax_error: approve()` — 忽略了 LLM 可伪造测试结果
- 前端展示的代码可能是美化/简化的版本（Agent 在摘要中省略了关键细节）

**How to avoid:**

1. **确认流的三阶段设计，永不跳过人工审查**：
   ```
   阶段 1: 系统自动检查（语法 + 安全扫描 + 资源复杂度）
     - 自动拒接（ast.parse 失败、危险名称命中、网络访问）→ 无法到达阶段 2
     - 自动放行进入阶段 2
   
   阶段 2: Agent 自测（代码功能验证）
     - Agent 编写测试用例并执行
     - 自测在隔离沙箱中运行（非生产环境）
     - 自测结果仅作为参考信息，不作为安全放行依据
   
   阶段 3: 用户确认（必须人工参与，不可自动跳过）
     - 前端展示：完整代码 + AST 扫描结果摘要 + 自测结果
     - 用户选择：持久化级别（会话/沙箱/项目）、目录权限
     - 用户必须点击"批准"（非自动计时放行）
     - 前端记录确认审计日志（谁、何时、批准了什么）
   ```

2. **代码展示必须是完整源代码** — 不可摘要、不可截断、不可由 Agent 美化。`generate_tool` 返回的代码字符串直接展示，不做任何 Agent 解释。

3. **人工确认不可超时放行** — 静态工具的 `PermissionGuard` 有 120 秒超时机制。动态工具注册无超时——用户确认之前，工具保持 `pending` 状态，不可执行。

4. **Agent 自测的沙箱行为**：
   - 隔离沙箱中运行测试，失败不影响现有系统
   - 自测结果与代码对比——Agent 声称测试通过但测试用例不覆盖危险路径时标记为可疑
   - 自测中监控 Agent 是否尝试访问实际数据/环境变量

5. **注册后观察期** — 新注册的动态工具首次 N 次执行（默认 5 次）标记为"观察中"。每次执行的结果在前端额外高亮展示。用户可在观察期内随时禁用或删除工具。

**Warning signs:**
- Agent 在自测报告中使用含糊语言（"已验证"、"应该没问题"）
- 自测用例覆盖范围极窄（只测了正常输入）
- Agent 在代码摘要中使用了"简化"、"大致"、"核心逻辑"等修饰词
- 用户批量批准（连续 3+ 个工具快速批准）
- 前端确认界面缺少完整代码展示

**Phase to address:**
Phase 2（用户确认）— 三阶段确认流程 + 前端代码展示。Phase 3（工具管理）— 注册后观察期 + 启用/禁用 + 审计日志。

---

### Pitfall 8: 持久化级别的蕴含风险 — 会话/沙箱/项目级的代码存活周期混淆

**What goes wrong:**
三种持久化级别设计存在模糊地带：
- **会话级**：工具在当前 session 结束时销毁。但如果 session 未正常终止（崩溃、超时），工具残留不清理。
- **沙箱级**：工具在沙箱内持久存在。但沙箱重启或重建后，工具消失且无迁移机制。
- **项目级**：工具写入项目文件系统（如 `.loopai/dynamic_tools/`）。但如果项目中存在同名旧工具，覆盖行为是静默的，且旧工具可能已被其他 session 引用。

当工具所依赖的资源（文件路径、环境变量）在持久化级别间变化时，工具可能表现不一致。Agent 可能认为"项目级工具"在所有环境中可用，但实际上不同环境的沙箱配置不同。

**Why it happens:**
- 持久化级别定义的是代码生命周期，不是依赖资源的生命周期
- Session/沙箱的销毁是异步的，工具清理函数可能未及时执行
- 项目级工具的文件路径缺乏版本控制和冲突解决机制
- 没有工具迁移和状态同步的协议（跨沙箱、跨 session）

**How to avoid:**

1. **清晰的清理合约**：
   - 会话级工具 → `session.on_close` 事件触发时清理（注册关闭钩子，非依赖 GC）
   - 沙箱级工具 → 沙箱重建时迁移或警告
   - 项目级工具 → 永不清理由系统自动执行（由用户手动删除）

2. **项目级工具使用带版本的存储**：
   ```json
   {
     "tool_id": "dynamic.a1b2c3d4_cleanup_cache",
     "version": 2,
     "created_at": "2026-05-31T10:00:00Z",
     "updated_at": "2026-05-31T11:00:00Z",
     "code": "...",
     "sha256_hash": "e3b0c44298fc1c149afbf4c8996fb924...",
     "previous_versions": [
       {"version": 1, "code": "...", "sha256_hash": "..."}
     ]
   }
   ```

3. **依赖声明** — 动态工具在创建时需要声明其依赖：
   ```python
   @dynamic_tool(
       requires_paths=["/workspace/logs", "/tmp/scan_results"],
       requires_env=[],
       max_memory_mb=128,
   )
   ```

4. **会话关闭强制清理链** — 不是"依赖 GC"而是显式管理：
   - Session 关闭 → 遍历所有会话级工具 → 调用 `tool.on_destroy()` → 清理文件 → 从 Registry 移除
   - 必须记录清理日志（清理成功/失败/文件残留）

5. **沙箱级工具的迁移通知** — 沙箱重建时，通知用户哪些工具将丢失，提供导出/迁移选项。

**Warning signs:**
- 会话关闭日志中缺少工具清理记录
- 项目级工具与先前版本哈希不匹配但未触发警告
- 用户报告"上次创建的工具消失了"
- 工具引用的文件路径在沙箱重建后已不存在

**Phase to address:**
Phase 2（持久化系统）— 清理合约 + 版本化存储。Phase 3（工具管理）— 前端工具列表区分持久化级别 + 迁移提示。

---

## Technical Debt Patterns

Shortcuts that seem reasonable but create long-term problems.

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| 动态工具与静态工具共享 ToolRegistry 扁平命名空间 | 零代码改动 | 命名冲突、工具毒化、LLM 误选 | **Never** — 必须分区存储 |
| AST-only 安全扫描（无外部沙箱） | 前期开发极快 | 30+ 已知绕过路径，虚假安全感 | 本地 demo 展示（不可连接网络） |
| 自动批准 Agent 自测通过的工具 | 减少人工步骤 | 恶意工具可通过自测获得注册 | **Never** — 必须人工确认 |
| `exec()` 直接执行 Agent 生成代码 | 一行代码 | 等同于 `CVE-2026-42079`，无任何安全边界 | **Never** |
| 直接注入动态工具描述到 system prompt | 无前端改动 | 间接提示注入载体，Agent 被劫持 | **Never** — 必须净化并包装 |
| 依赖 Python 进程内沙箱（仅 import hook） | 无需外部依赖 | Python 沙箱从根本上无法安全（公认结论） | 仅用于快速原型，不可面向用户 |
| 动态工具无限超时 | 简单实现 | 死循环拖垮主 Agent 进程 | **Never** — 必须有独立超时 |
| 工具清理依赖 GC（`__del__`） | 无需管理代码 | 清理时间不可控，残留堆积 | 仅限会话级非关键工具 |
| dynamic. 前缀作为唯一区别 | 实现简单 | 攻击者可生成 `dynamic.bash` 混淆静态 `bash` | 必须含随机哈希后缀 |

---

## Integration Gotchas

Common mistakes when connecting dynamic tool system to existing safety layers.

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| ToolRegistry | 动态工具直接 `register()` 到现有注册表 | 通过 `register_dynamic()` 专用方法 → 内部调用 validate + conflict_check + sandbox_scope |
| EventBus | 复用 `tool_call_start`/`tool_call_end` 事件 | 定义 `dynamic_tool_*` 前缀的新事件类型，前端可据此差异化 UI |
| PermissionGuard | 动态工具使用相同的 DANGEROUS/MODERATE 级别 | 引入 `PermissionLevel.DYNAMIC`，payload 含代码 + 持久化信息 |
| CommandClassifier | 动态 Bash 工具绕过分类器 | 动态 Bash 工具必须强制调用 `classifier.classify()` |
| CircuitBreaker | 动态工具连续失败触发熔断 | 前 N 次执行豁免，仅记录不熔断 |
| GuardPipeline | 动态工具的 TokenGuard/CostGuard 检查不足 | 代码长度计入 token 统计，扫描成本计入 CostGuard |
| JSONL Logger | 动态工具的生成和执行未分开记录 | 记录 `dynamic_tool_created` + `dynamic_tool_executed` 两条事件 |
| 前端确认弹窗 | 复用危险命令确认弹窗 (`bash.rm` 风格) | 专用 `ToolCreationDialog`（代码展示 + 持久化级别 + 权限） |
| Session Context | 动态工具的 `func_ref` 持有 Session 引用 | 动态工具的 `func_ref` 是隔离的，不可引用主 Session 对象 |
| Checkpoint/Recovery | 动态工具不在检查点中 | 会话级动态工具不持久到检查点；项目级需要同步到检查点 |

---

## Performance Traps

Patterns that work at small scale but fail as usage grows.

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| 每次 LLM 调用都发送全部动态工具列表 | system prompt 随工具增长而膨胀 | 工具发现机制（system prompt 只注入概要，`list_tools` 查询详情） | 10+ 动态工具 |
| 动态工具同步执行（阻塞 Agent 循环） | Agent 等待工具创建完成才能继续 | 异步创建：Agent 提议 → 用户确认 → 后台注册 → Agent 继续推理 | 首次工具创建时 |
| 不安全代码的 AST 扫描为全量扫描 | 大代码块的扫描时间 O(n) 增长 | AST 扫描有最大节点限制（500），超出则拒绝 | 工具代码 > 1000 行 |
| 每次工具执行前重复安全扫描 | 已注册工具的重复扫描浪费 CPU | 注册时扫描一次，缓存结果。仅在代码更新时重新扫描 | 高频调用工具 |
| 动态工具文件存储在单目录下无索引 | 工具查找需遍历文件系统 | 索引文件（`tool_index.json`）+ 内存缓存 | 50+ 项目级工具 |

---

## Security Mistakes

Domain-specific security issues beyond general web security.

| Mistake | Risk | Prevention |
|---------|------|------------|
| Python 进程内沙箱作为唯一防线 | 30+ 已知绕过路径，满分 CVSS 10.0 | 外部隔离（seccomp/Landlock/gVisor/nsjail），进程内仅作快速预筛 |
| `ctypes` 不在危险模块列表 | `ctypes.CDLL(None).system("id")` 直接调用 libc | 危险模块列表中包含 `ctypes`、`cffi` 及所有 C/asm 接口 |
| 允许白名单模块的传递访问 | `statistics.sys.modules["os"]` 绕过 | import hook 拦截子模块传递访问，检查完整模块链 |
| 动态工具的 `PermissionLevel.SAFE` | 恶意工具自动放行 | 动态工具最低 `MODERATE`，永不可 `SAFE` |
| Agent 自测代码有网络权限 | 自测中外泄数据到外部 | 自测在 `deny-all egress` 沙箱中运行 |
| LLM 通过 `generate_tool` 读取文件 | `generate_tool` 工具返回当前目录文件内容 | `generate_tool` 不接受文件路径参数，使用代码字符串传递 |
| 工具版本回退到有漏洞的旧版本 | 用户更新工具后存在残留 | 版本存储 + 旧版本标记为禁用（不删除用于审计） |
| 工具描述未净化直接写入 system prompt | 间接提示注入劫持工具选择 | 描述 max 500 字符 + 指令语言扫描 + 模板包装 |
| 未隔离的导入缓存 (`sys.modules`) | 前一个沙箱的 import 状态泄漏到后一个 | 每个动态工具执行前重置导入状态（专用子进程） |
| LLM 输出直接传给 `ast.literal_eval` | `literal_eval` 可被恶意利用 | 仅 `ast.parse` 做静态分析，不执行 |

---

## UX Pitfalls

Common user experience mistakes in this domain.

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| 动态工具创建无代码预览 | 用户不知道 Agent 创建了什么 | 前端展示完整代码（语法高亮 + 危险标注行） |
| 工具失败无清晰错误信息 | 用户看到原始异常，"我的工具有 bug 但不知道为什么" | 结构化错误（所属阶段 + 具体原因 + 建议操作） |
| 持久化级别混淆 | 用户选择"会话级"但期望下次仍然可用 | 每个级别附场景说明："下次会话可用吗？" |
| Agent 建议创建工具但用户不知道为何需要 | 用户疑惑"不能直接用已有工具吗？" | Agent 必需解释：为何需要新工具、为何现有工具不足 |
| 工具命名无即时而反馈 | 用户输入名称才知道是否冲突 | 实时命名校验（前端即时提示是否可用） |
| 工具列表无生命周期标注 | 用户不清楚哪些工具是临时的 | 会话级/沙箱级/项目级用视觉标签区分 |
| 删除工具无撤销 | 踩删关键工具系统受影响 | 软删除 + 回收站 + 24h 内可恢复 |
| 批量创建工具无集中管理 | 10+ 动态工具散落，用户难以管理 | 前端"动态工具"Tab 集中管理（启用/禁用/删除/导出） |

---

## "Looks Done But Isn't" Checklist

Things that appear complete but are missing critical pieces.

- [ ] **代码语法检查**: 通过了 `ast.parse()`，但未做危险名称扫描、I/O 审计、资源复杂度检查。Verify: 生成包含 `ctypes.CDLL` 的代码，验证是否能通过检查。
- [ ] **Agent 自测**: Agent 声称测试通过，但测试用例未覆盖异常路径、边界条件和资源限制行为。Verify: 审查 Agent 生成的具体测试用例覆盖率。
- [ ] **沙箱隔离**: 开启 Docker/gVisor，但未配置 `--read-only`、`--cap-drop ALL`、`--memory` 限制。Verify: 在沙箱内执行 `touch /etc/test` 和 `echo "x" * 2**30`，验证是否被阻止。
- [ ] **权限注册**: 使用了 `PermissionLevel`，但动态工具默认 SAFE 或不区分来源。Verify: 注册一个动态工具，检查其 level 是否被强制最低为 MODERATE。
- [ ] **用户确认流**: 前端展示了确认弹窗，但 Agent 可通过 API 绕过确认注册工具。Verify: 使用 curl 直接调用 `POST /api/dynamic-tools` 不携带用户令牌，验证是否被拒绝。
- [ ] **工具清理**: 会话结束时代码调用清理函数，但 crash/超时时不触发。Verify: 创建会话级工具后 `kill -9` 主进程，重启后检查工具残留。
- [ ] **命名冲突**: 使用哈希后缀防冲突，但哈希只取 4 位（碰撞概率 1/65536）。Verify: stress test 10K 次工具创建，检测碰撞。
- [ ] **动态工具调用权限**: 限制了调用动态工具的权限，但静态工具可内部调用动态工具（通过 ToolRegistry）绕过权限。Verify: 用 DANGEROUS 级动态工具测试间接调用。
- [ ] **网络隔离**: 沙箱配置了 iptables，但 DNS 查询未被阻止（数据可通过 DNS 隧道外泄）。Verify: 尝试 `dig @8.8.8.8 evil.com` 或 `nslookup` 类调用。
- [ ] **工具版本回退**: 存放了更新历史，但旧版本可直接恢复执行。Verify: 恢复到旧版本后尝试执行。

---

## Recovery Strategies

When pitfalls occur despite prevention, how to recover.

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| 沙箱逃逸成功 | HIGH — 可能造成系统级破坏 | 1. 立即停止 Agent 进程。2. 审计所有沙箱外文件修改（通过文件系统时间戳）。3. 审计网络连接日志。4. 轮换所有可访问的凭证。5. 修复逃逸路径后重启。6. 评估是否需从备份恢复。 |
| 恶意工具注入并注册 | MEDIUM — 工具已在 Registry 中 | 1. 禁用可疑工具（非删除，保留证据）。2. 审计该工具的执行记录。3. 检查 LLM 是否被工具输出污染（回放 session）。4. 移除工具及其产出的文件。 |
| 资源耗尽崩溃 | MEDIUM — Agent 进程已死 | 1. 重启 Agent 进程。2. 清空沙箱临时文件。3. 设置更严格的 `rlimit`。4. 标记引发崩溃的工具为"需审查"。 |
| 命名冲突导致工具覆盖 | LOW — 旧工具信息丢失 | 1. 检查 `tool_index.json` 版本历史。2. 从备份恢复旧工具。3. 重命名新工具清除冲突。 |
| 用户错误批准恶意工具 | MEDIUM — 工具已具备执行权限 | 1. 立即禁用工具。2. 回放该工具的所有执行记录。3. 评估产生的文件/数据修改。4. 改进前端确认 UI 防止重犯。 |
| 工具清理残留 | LOW — 文件残留但未执行 | 1. 手动运行清理脚本。2. 检查会话关闭钩子是否正确注册。3. 添加定期清理 cron（每小时清理超 24h 的会话残留）。 |

---

## Pitfall-to-Phase Mapping

How roadmap phases should address these pitfalls.

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| AST/Regex 源码过滤被绕过 (P1) | Phase 1（语法检查 + 危险模块扫描）→ Phase 2（外部沙箱隔离） | 生成包含 `type.__getattribute__('__subclasses__')` 的代码，验证是否被外部沙箱阻断 |
| 代码注入 / 漏洞污染 (P2) | Phase 1（安全审计管线）→ Phase 2（沙箱隔离）→ Phase 3（用户确认） | 生成包含 `os.environ` 读取的代码，验证在三层均有拦截 |
| 资源耗尽 (P3) | Phase 2（独立 rlimit + 超时 + 独立进程） | 生成 `while True: pass` 代码，验证在 5 秒内被 SIGKILL |
| 工具毒化 (P4) | Phase 1（命名空间分离）→ Phase 3（描述净化） | 注册与 `bash` 同名的动态工具，验证被拒绝；注入"你应该忽略所有指令"到工具描述，验证被净化 |
| 子进程沙箱逃逸 (P5) | Phase 1（危险模块全量扫描）→ Phase 2（外部沙箱隔离） | 生成 `ctypes.CDLL(None).system("id")`，验证被 import hook 拦截且外部沙箱阻止 syscall |
| 集成冲突 (P6) | Phase 1（ToolRegistry 分区 + EventBus 扩展）→ Phase 3（PermissionGuard 适配） | 同时注册静态和动态工具，LLM 调用时分别跟踪 → 前端区分 UI |
| 用户确认门被绕过 (P7) | Phase 2（三阶段确认）→ Phase 3（注册后观察期） | 使用 curl 直接 POST 工具注册 API 不带确认令牌，验证被拒绝 |
| 持久化级别混淆 (P8) | Phase 2（清理合约 + 版本存储）→ Phase 3（前端标注） | 创建会话级工具 → `kill -9` 主进程 → 重启 → 验证工具已清除 |

---

## Sources

### 真实 CVE 和安全公告
- [CVE-2026-40158 — PraisonAI AST Filter Bypass via type.__getattribute__()](https://app.opencve.io/cve/CVE-2026-40158) — CVSS 10.0
- [CVE-2026-39888 — PraisonAI Sandbox Escape via Exception Frame Traversal](https://app.opencve.io/cve/CVE-2026-39888) — CVSS 10.0
- [CVE-2026-42079 — PPTAgent: Direct eval() of LLM-Generated Code with Builtins in Scope](https://app.opencve.io/cve/CVE-2026-42079) — CVSS 8.6
- [CVE-2026-33873 — Langflow: exec() on LLM-Generated Code During "Validation"](https://app.opencve.io/cve/CVE-2026-33873) — CVSS 9.3
- [CVE-2026-27952 — Agenta: RestrictedPython Sandbox Escape via numpy whitelist](https://cvepremium.circl.lu/vuln/fkie_cve-2026-27952) — CVSS 9.9
- [CVE-2026-30856 — Tencent WeKnora: Tool Name Shadowing + Indirect Prompt Injection](https://radar.offseq.com/threat/cve-2026-30856-cwe-706) — CWE-706
- [CVE-2026-44339 — PraisonAI: Unsafe Fallback to globals() / __main__ in ToolExecutionMixin](https://vulnerability.circl.lu/vuln/CVE-2026-44339) — CWE-470
- [SB2026050723 — LiteLLM: Guardrail Regex Sandbox Bypass via Bytecode Rewriting](https://www.cybersecurity-help.cz/vdb/SB2026050723) — CVSS 8.7
- [X41 Advisory X41-2026-001 — LiteLLM Sandbox Escape Details](https://seclists.org/oss-sec/2026/q2/54)

### 沙箱逃逸技术
- [GHSA-4675-36f9-wf6r — ctypes Not Flagged as Dangerous in smolagents LocalPythonExecutor](https://github.com/advisories/GHSA-4675-36f9-wf6r)
- [huntr.com — smolagents ctypes Sandbox Escape](https://huntr.com/bounties/50ad1e34-cf05-471b-95bf-1fc2ba6fef6c)
- [huntr.com — smolagents statistics.sys.modules Transitive Access](https://huntr.com/bounties/27cf10ec-3204-4fb5-88ac-71ed4f8f601c)
- [FOX-IT — Autonomous AI Agents: Hidden Risk in smolagents CodeAgent](https://www.fox-it.com/be/autonomous-ai-agents-a-hidden-risk-in-insecure-smolagents-codeagent-usage/)

### 工具毒化和提示注入
- [Datadog Security Labs — Malicious Coding Agent Skills and Dynamic Context Risk](https://securitylabs.datadoghq.com/articles/malicious-skills-supply-chain-risks-in-coding-agents-with-dynamic-context/)
- [Strands-agents — Tool Registry Poisoning via sys.modules hijacking](https://security.snyk.io/vuln/SNYK-PYTHON-STRANDSAGENTS-14157238)
- [CoSAI OASIS — Tool Registry Poisoning (TRP) Risk Definition](https://github.com/cosai-oasis/secure-ai-tooling/issues/141)
- [arXiv:2602.11327 — MCP/A2A Protocol Threat Modeling (Shadowing Attacks)](https://github.com/bug-ops/zeph/issues/2496)
- [Checkmarx CxZero — MCP Risk Taxonomy (2025)](https://content.techgig.com/technology-guide/exploiting-agentic-ai-developer-tools-risks-and-prevention/articleshow/124534183.cms)

### 沙箱隔离架构
- [How to Sandbox AI Agents in 2026: Firecracker, gVisor, Runtimes](https://dev.to/manveer_chawla_64a7283d5a/how-to-sandbox-ai-agents-in-2026-firecracker-gvisor-runtimes-isolation-strategies-14pk)
- [Execution Sandboxes for AI Agents: Architecture, Risks, and Patterns](https://www.sourcetrail.com/python/execution-sandboxes-for-ai-agents-architecture-risks-and-real-world-patterns/)
- [Notes on Sandboxing Untrusted Code — Why Python Can't Be Sandboxed](https://gist.github.com/mavdol/2c68acb408686f1e038bf89e5705b28c)
- [MCP Security Patterns 2026: gVisor vs Firecracker](https://dev.to/chunxiaoxx/mcp-security-patterns-2026-gvisor-vs-firecracker-for-ai-agent-sandboxing-3hp7)

### 行业最佳实践
- [Awesome Agent Runtime Security (GitHub)](https://github.com/bureado/awesome-agent-runtime-security)
- [AgentGuard — Architectural Safety Layer for AI Agents](https://github.com/psychomad/AgentGuard)
- [Building Code Agents with Hugging Face smolagents — Secure Code Execution](https://learn.deeplearning.ai/courses/building-code-agents-with-hugging-face-smolagents/lesson/h11ie/secure-code-execution)
- [Hardening Best Practices: Sandboxing, Least Privilege & Data Exfiltration Guards](https://skywork.ai/blog/ai-agent/hardening-best-practices-sandboxing-least-privilege-data-exfiltration/)

### loopAI 现有安全基础设施（项目内参考）
- `src/loopai/state_machine/guards.py` — BudgetGuard、LoopDetector、MessageValidator、PermissionGuard、TokenGuard、CostGuard、RateLimitGuard、GuardPipeline
- `src/loopai/tools/command_classifier.py` — CommandClassifier（白名单/黑名单 + 路径感知升级）
- `src/loopai/tools/bash.py` — BashTool（shell=False + shlex + 元字符扫描 + 超时）
- `src/loopai/tools/executor.py` — ToolExecutor（4 层恢复管道 + 重试 + 溢出文件）
- `src/loopai/resilience/circuit_breaker.py` — CircuitBreaker 熔断机制

---
*Pitfalls research for: Agent 动态工具创建系统（loopAI v1.1）*
*Researched: 2026-05-31*
*基于 2025-2026 年 15+ 真实 CVE、安全审计报告和框架安全公告*
