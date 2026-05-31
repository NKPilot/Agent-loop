# Feature Research: Agent 动态工具创建系统

**Domain:** AI Agent 动态工具生成与运行时注册
**Researched:** 2026-05-31
**Confidence:** HIGH

## Feature Landscape

### Table Stakes (Users Expect These)

缺失这些特性 = 系统不可用。

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **代码语法校验** | 语法错误的工具代码注册后无法执行，破坏 agent 循环 | LOW | `ast.parse()` 校验 Python，`bash -n` 校验 Bash。Anvil SDK、Meta-Tools、所有框架均强制执行此步骤 |
| **沙箱隔离执行** | LLM 生成的代码不可信——从 CVE-2026-47392（AST 黑名单绕过，`print.__self__` 泄露 builtins）到 smolagents 的 `additional_authorized_imports` RCE，进程内执行 AI 生成代码的风险已被反复证实 | HIGH | 子目录隔离（chroot/路径白名单）+ 禁止网络 + 独立超时。最低要求：子进程执行，不 `exec()`/`eval()` |
| **用户确认弹窗** | 任何动态工具必须在注册前经人类审核。Anthropic 数据显示人对提示的批准率达 93%，但代码创建确认不同于命令执行——代码审查是安全关键路径 | MEDIUM | 复用现有 `ConfirmationDialog` 模式，但改为代码展示（语法高亮 + 持久化级别 + 目录权限选择），而非简单 y/n |
| **工具持久化** | 会话重启后动态工具必须仍可用。Anvil SDK 存工具到 `tools_dir/`，AutoLearn 用 SQLite。无持久化则动态工具无意义 | MEDIUM | 文件系统存储最简单可靠。JSONL 记录元数据 + `.py` 文件存实际代码。与现有 JSONL 日志范式一致 |
| **list_tools 工具发现** | Agent 必须知道有哪些动态工具可用。mini_claw 提供 `list_tools()` + `search_tools_registry()`，Koda 用 `DiscoverTools` 按需加载（节省 57% token） | LOW | 两个层面：system prompt 注入轻量概要（名称+一句话描述），+ `list_tools` 内置工具返回完整 Schema |
| **运行时错误不崩溃** | 动态工具执行失败不应终止 agent 循环。必须返回结构化错误，让 LLM 自我纠正或放弃该工具 | LOW | 完全复用现有 `ToolExecutor` 的 4 层恢复管道（外观修复→上下文重试→退避→人工介入）和 `ErrorCategory` 分类 |
| **工具可禁用/删除** | 用户需要对已创建的工具进行生命周期管理。错误的工具应可禁用（保留代码但不执行）或删除 | LOW | 前端管理面板 + API 端点。Registry 需增加 `unregister` 和 `enabled/disabled` 状态 |

### Differentiators (Competitive Advantage)

使系统从"能用"变为"好用"。

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **工具自测验证（Agent 写测试并执行）** | 大部分框架只做到语法校验（`ast.parse`）。让 Agent 先生成测试用例、在沙箱中执行、验证结果通过后才呈现给用户确认——这是 Replit Agent 3 的"独立验证 Agent"模式，Spec Guard 的"failure-first test"（Gate 4）模式。显著降低用户审查负担 | HIGH | 分两阶段：(1) 语法检查（ast.parse/bash -n），(2) Agent 编写 pytest 用例→沙箱执行→结果验证。自测失败则 Agent 自行修复后重试，最多 3 轮迭代 |
| **三级持久化作用域** | 多数框架只有全局持久化。提供会话级（session 内可用，重启丢失）/ 沙箱级（同一项目内所有 session 可用）/ 项目级（跨项目可用）三个粒度，让用户精确控制工具生命周期 | MEDIUM | 会话级：存内存 + 临时文件。沙箱级：存 `.sandbox/tools/`。项目级：存 `.loopai/tools/`。前端弹窗让用户选择 |
| **diff 更新 + 命名冲突处理** | Agent 想修改已有工具时，展示新旧代码 diff + 功能变更说明，而非简单覆盖或拒绝。工具重名时合并为同一流程：比对代码→展示差异→用户选择覆盖/重命名/拒绝 | MEDIUM | 依赖 Python `difflib` 生成 unified diff。前端需 `react-diff-viewer` 或自行渲染。冲突处理同时展示两个版本 |
| **复用现有 @tool 基础设施** | 动态工具创建后直接使用相同的 `ToolMetadata` + `ToolRegistry` + `ToolExecutor` + `EventBus` 管道，自动获得 Pydantic 参数校验、超时控制、重试策略、熔断器、JSONL 日志。动态工具是一等公民，非二等公民 | LOW（架构收益） | `DynamicToolCreator` 生成的工具使用 `ToolRegistry.register_meta()` 注册，与 `@tool` 装饰器无区别。这在生态系统中极少见——多数框架区分静态/动态工具 |
| **危险模块扫描** | 代码注册前自动扫描 `import os` / `subprocess` / `socket` / `shutil.rmtree` 等危险调用，标记为 `PermissionLevel.DANGEROUS`，运行前强制用户确认。Anvil SDK 无此功能，smolagents 因缺少此扫描导致文件泄露 | MEDIUM | AST 遍历检测 import 语句 + 字符串模式匹配。非安全沙箱（可能被绕过），但作为防御深度的第一层有价值 |
| **create_tool 内置工具** | Agent 通过调用 `create_tool` 工具来提议新工具，而非通过自由格式的消息"我觉得需要一个工具"。结构化的工具定义（name/description/code/language/permission_level/persistence_scope）使流程可追踪、可验证、可拒绝 | LOW | 本质上是一个 `@tool` 装饰的工具，接受 Pydantic 模型参数。完全复用现有工具执行管道 |

### Anti-Features (Commonly Requested, Often Problematic)

听起来好但实际有害。

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **Agent 自主安装 pip 包** | "Agent 需要 pandas 处理数据" | smolagents `additional_authorized_imports` 导致通过 pandas 文件 I/O 实现 RCE。npm 包同样有供应链风险（Cline 5M+ 用户 token 泄露）。Agent 无法判断包安全性 | 只允许 `math`/`json`/`datetime` 等 stdlib 安全模块。如需额外功能，由用户手动安装后在代码中 import |
| **无确认自动创建工具** | "提升效率，减少人工介入" | Datadog Security Labs 展示了 `!` 动态命令在模型审查前就执行的攻击。无确认 = 任意代码执行。即使语法正确，工具可能包含数据外泄逻辑 | 所有动态工具必须经过前端确认弹窗，展示完整代码，且确认超时（120s）自动拒绝 |
| **AST 黑名单沙箱（进程内）** | "简单，不需要 Docker" | CVE-2026-47392 证明 AST denylist 根本不可靠——`print.__self__` 泄露 builtins，字符串拼接绕过常量检查。每次补丁都会发现新绕过 | OS 级隔离：子进程 + 子目录路径白名单 + 网络 deny-all。不依赖语言级沙箱 |
| **动态工具允许网络访问** | "工具需要调用外部 API" | 生成代码中的网络请求 = 数据外泄通道。Agent 可以通过工具偷偷上传敏感信息 | 默认 deny-all 网络。如需 API 调用，使用静态 @tool 装饰的工具（用户编写并审查过的），动态工具通过调用现有工具间接使用网络 |
| **Agent 修改系统级 @tool 工具** | "修复已有工具的 bug" | 静态工具是系统基础设施，由开发者审查和维护。Agent 修改它们会破坏系统完整性。且系统工具通常有复杂的权限和配置 | 动态工具只能新增或修改动态工具。系统工具（`@tool` 装饰的）为只读。Agent 可以建议修改，但需开发者手动实施 |
| **实时自动重试修复失败工具** | "工具失败时自动修复，无需打扰用户" | 自动修复循环可能产生更危险的代码变体。无人工审查的自动迭代 = 不可控的代码演化。Anvil SDK 的 self-healing 已造成意外行为 | 工具自测失败时，Agent 可在沙箱内修复重试，但最多 3 轮后放弃并告知用户。永远不在无用户确认的情况下替换已注册工具 |

## Feature Dependencies

```
ToolMetadata 扩展 (is_dynamic, source_code, persistence_scope)
    └──requires──> loopai.tools.types (现有)

ToolRegistry 扩展 (unregister, is_enabled toggle)
    └──requires──> loopai.tools.registry (现有)

DynamicToolCreator (代码校验 + AST 扫描 + 沙箱执行)
    ├──requires──> ToolMetadata 扩展
    ├──requires──> ToolRegistry 扩展
    ├──requires──> ToolExecutor (现有) — 沙箱内执行验证测试
    └──requires──> Bash 安全层 (现有) — 子进程隔离 + shell=False

create_tool 内置工具
    ├──requires──> @tool 装饰器 (现有) — 工具定义的 Pydantic 校验
    ├──requires──> DynamicToolCreator
    └──requires──> EventBus (现有) — 发布 tool_creation_proposed 事件

前端 ToolCreationDialog
    ├──requires──> SSE 桥接 (现有) — 接收 tool_creation_proposed 事件
    ├──requires──> ConfirmationDialog (现有模式参考)
    └──requires──> shadcn/ui Dialog + ScrollArea + Badge (现有)

工具自测验证 (write test → execute → validate)
    ├──requires──> DynamicToolCreator — 语法校验通过后才自测
    ├──requires──> Bash 安全层 (现有) — pytest 在沙箱子进程中执行
    └──requires──> CircuitBreaker (现有) — 自测循环熔断保护

工具管理面板 (前端 "Dynamic Tools" tab)
    ├──requires──> ToolRegistry.list_all() (现有，需扩展过滤动态工具)
    ├──requires──> API 端点 (新增): GET/PATCH/DELETE /tools/dynamic
    └──requires──> shadcn/ui Tabs + Card + Badge (现有)

工具更新 + diff 展示
    ├──requires──> ToolRegistry (现有) — 查找现有工具
    └──requires──> Python difflib (stdlib)

list_tools 工具
    ├──requires──> ToolRegistry.list_all() + get_schemas() (现有)
    └──requires──> prompt_builder (现有) — 注入动态工具摘要

工具持久化 (三级)
    ├──requires──> DynamicToolCreator
    └──requires──> 文件系统 IO (stdlib)
```

### Dependency Notes

- **DynamicToolCreator requires ToolExecutor:** 工具自测时，Agent 生成的 pytest 代码需要在沙箱子进程中执行。ToolExecutor 提供超时控制、错误分类、结果包装。
- **ToolCreationDialog enhances ConfirmationDialog:** 复用相同的 Dialog/DialogContent/DialogFooter UI 组件 + 超时自动拒绝 + SSE 事件驱动模式，但内容从命令确认变为代码审查。
- **list_tools 与 prompt_builder 协同:** `prompt_builder.build_system_prompt()` 注入动态工具概要，`list_tools` 工具返回完整 JSON Schema 详情。减少 token 消耗（借鉴 Koda 的 DiscoverTools 模式）。
- **工具自测验证 requires CircuitBreaker:** 防止 Agent 在修复→验证循环中陷入无限重试。

## MVP Definition

### Launch With (v1.1)

核心流程：Agent 提议工具 → 校验 → 用户确认 → 注册执行为最小可行产品。

- [ ] **ToolMetadata 扩展** — 添加 `is_dynamic: bool`, `source_code: str`, `persistence_scope: str`, `enabled: bool` 字段。基础依赖。
- [ ] **代码语法校验** — `ast.parse()` (Python) / `bash -n` (Bash)。基础设施。
- [ ] **DynamicToolCreator** — 接受 LLM 生成的代码字符串，执行语法校验 + 危险模块 AST 扫描，生成 ToolMetadata。
- [ ] **create_tool 内置工具** — Agent 通过结构化工具调用提议新工具。接受 name/description/code/language/permission_level/persistence_scope 参数。
- [ ] **ToolRegistry 扩展** — 添加 `unregister()`、`is_disabled` 检查，支持动态工具的注册/注销。
- [ ] **ToolCreationDialog（前端）** — 展示代码（语法高亮）、持久化级别选择、目录权限、审批/拒绝按钮。复用 ConfirmationDialog 的超时自动拒绝模式。
- [ ] **工具持久化（基础）** — 沙箱级持久化（`.sandbox/tools/`）。MVP 不需要三级，先做一个可靠的单级。
- [ ] **list_tools 工具** — 返回所有已注册工具的名称 + 描述 + 参数 Schema。
- [ ] **system prompt 动态工具注入** — `prompt_builder` 注入动态工具概要。

### Add After Validation (v1.1.x)

- [ ] **工具自测验证** — 语法校验通过后，Agent 写 pytest 用例 → 沙箱执行 → 最多 3 轮迭代修复。触发条件：基础流程稳定，用户反馈审查负担重。
- [ ] **三级持久化** — 会话级 / 沙箱级 / 项目级。触发条件：用户需要更细粒度的工具生命周期控制。
- [ ] **工具管理面板** — 前端 "Dynamic Tools" tab：查看所有动态工具代码、启用/禁用、删除。触发条件：工具数量超过 5 个，需要批量管理。
- [ ] **工具更新 + diff** — Agent 修改已有工具 → diff 展示 → 用户选择覆盖/拒绝。触发条件：首次出现工具修改需求。

### Future Consideration (v2+)

- [ ] **工具评分/使用统计** — 记录每个动态工具的调用次数、成功率、平均延迟，自动建议禁用低质量工具。
- [ ] **工具模板库** — 用户可以从预定义模板创建工具（如"API 调用工具"、"文件处理工具"），降低 LLM 生成错误率。
- [ ] **跨会话工具共享** — 多个会话协同使用同一组动态工具，带权限控制。

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| ToolMetadata 扩展 | HIGH — 所有后续功能依赖 | LOW | P1 |
| 代码语法校验 | HIGH — 无此则不可用 | LOW | P1 |
| DynamicToolCreator + AST 扫描 | HIGH — 核心创建逻辑 | MEDIUM | P1 |
| create_tool 内置工具 | HIGH — Agent 入口 | LOW | P1 |
| ToolRegistry 扩展 (unregister/enabled) | HIGH — 注册管线 | LOW | P1 |
| ToolCreationDialog（前端） | HIGH — 用户交互入口 | MEDIUM | P1 |
| 工具持久化（基础） | HIGH — 无持久化无意义 | LOW | P1 |
| list_tools 工具 | MEDIUM — Agent 需要发现 | LOW | P1 |
| system prompt 注入 | MEDIUM — Agent 需要知道 | LOW | P1 |
| 工具自测验证 | HIGH — 核心差异化 | HIGH | P2 |
| 三级持久化 | MEDIUM — 灵活性提升 | MEDIUM | P2 |
| 工具管理面板 | MEDIUM — 规模化需要 | MEDIUM | P2 |
| 工具更新 + diff | MEDIUM — 迭代需要 | MEDIUM | P2 |
| 工具评分/使用统计 | LOW | HIGH | P3 |
| 工具模板库 | LOW | HIGH | P3 |
| 跨会话工具共享 | LOW | HIGH | P3 |

## Competitor Feature Analysis

| Feature | Anvil SDK | AutoLearn (MCP) | Meta-Tools & Agents | OpenAI Agents SDK | Our Approach |
|---------|-----------|-----------------|---------------------|-------------------|--------------|
| 代码语法校验 | 隐式（运行时失败） | 无显式校验 | 有（editor + shell 调试） | 无（不是动态工具框架） | 显式 `ast.parse()` + `bash -n` |
| 用户确认 | 无（JIT 自动生成） | 无（自动注册） | 有（editor 模式手动） | N/A | 强制确认弹窗 + 超时自动拒绝 |
| 沙箱隔离 | 无 | MCP 服务端隔离 | 无（进程内） | N/A | 子进程 + 子目录 + 禁网 |
| 工具自测 | 无 | 无 | 有（shell 手动调试） | N/A | Agent 自动写 pytest + 执行 + 迭代修复 |
| 持久化 | 文件系统（单级） | SQLite（单级） | LangGraph checkpoint | N/A | 三级（会话/沙箱/项目） |
| 工具发现 | 无内置 list | MCP 协议 list | 语义搜索 + 向量化 | N/A | system prompt 概要 + list_tools 详情 |
| 工具更新 | self-healing 自动修复 | 无 | editor 手动修改 | N/A | diff 展示 + 用户选择 |
| 与现有工具系统集成 | 独立系统 | 独立 MCP 协议 | 独立系统 | N/A | **复用 @tool/ToolRegistry/ToolExecutor 全部基础设施** |

## Sources

- [Anvil SDK — JIT tool generation from intent](https://pypi.org/project/anvil-agent/) — MEDIUM confidence (PyPI listing)
- [Meta-Tools-and-Agents — dynamic tool loading + editor pattern](https://github.com/madhurprash/meta-tools-and-agents) — MEDIUM confidence (GitHub)
- [Agent Builder — define_tool at runtime](https://github.com/builtbyV/agent-builder) — MEDIUM confidence (GitHub)
- [Microsoft Agent Framework + CodeAct + Hyperlight microVM](https://devblogs.microsoft.com/agent-framework/codeact-with-hyperlight/) — HIGH confidence (official Microsoft devblog)
- [AutoLearn MCP — natural language to Python skill](https://pypi.org/project/iflow-mcp_autolearnai-autolearn/) — LOW confidence (PyPI, minimal documentation)
- [Koda — DiscoverTools lazy loading pattern (57% token reduction)](https://github.com/lijunzh/koda/issues/154) — MEDIUM confidence (GitHub issue)
- [mini_claw — list_tools() for prompt injection](https://docs.rs/mini_claw/0.1.15/mini_claw/tools/index.html) — MEDIUM confidence (docs.rs)
- [Pydantic AI — Tool constructor for dynamic registration](https://ai.pydantic.dev/) — HIGH confidence (official documentation)
- [OpenAI Agents SDK — @function_tool decorator + defer_loading](https://github.com/openai/openai-agents-python/blob/0a100fb1/docs/tools.md) — HIGH confidence (official GitHub)
- [CVE-2026-47392 — AST denylist sandbox bypass proof](https://github.com/advisories/GHSA-4mr5-g6f9-cfrh) — HIGH confidence (GitHub Advisory Database)
- [smolagents CodeAgent — insecure import whitelist RCE](https://www.fox-it.com/be/autonomous-ai-agents-a-hidden-risk-in-insecure-smolagents-codeagent-usage/) — HIGH confidence (Fox-IT security research)
- [Datadog Security Labs — dynamic context shell execution bypass](https://securitylabs.datadoghq.com/articles/malicious-skills-supply-chain-risks-in-coding-agents-with-dynamic-context/) — HIGH confidence (Datadog official)
- [DryRun Security — 87% of AI agent PRs contain vulnerabilities](https://www.helpnetsecurity.com/2026/03/13/claude-code-openai-codex-google-gemini-ai-coding-agent-security/) — MEDIUM confidence (industry study)
- [AI Agent Sandbox Security — 5-layer isolation model](https://www.sourcetrail.com/python/execution-sandboxes-for-ai-agents-architecture-risks-and-real-world-patterns/) — MEDIUM confidence (technical blog)
- [sandbox-exec — macOS sandbox profiles for AI agents](https://www.morphllm.com/ai-agent-sandbox) — MEDIUM confidence (vendor blog)
- [Replit Agent 3 — dual-agent self-testing (200+ min autonomous)](https://www.guvi.in/blog/replit-agent-self-testing/) — LOW confidence (educational blog, not primary source)
- [Spec Guard — 6-gate methodology with failure-first test (Gate 4)](https://www.npmjs.com/package/@jpstone/spec-guard) — LOW confidence (npm package, minimal docs)
- [loopAI 现有代码库 — ToolRegistry, ToolExecutor, EventBus, ConfirmationDialog](file://src/loopai/) — HIGH confidence (primary source, 已读取)

---
*Feature research for: Agent 动态工具创建系统*
*Researched: 2026-05-31*
