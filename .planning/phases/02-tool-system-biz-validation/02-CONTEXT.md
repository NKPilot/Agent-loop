# 阶段 2: 工具系统与业务验证 — 上下文

**收集时间:** 2026-05-27
**状态:** 待规划

<domain>
## 阶段边界

本阶段交付工具注册与执行管线、Bash 安全执行、权限分级、错误分类与重试机制，以及磁盘清理业务场景的端到端验证。所有工具系统代码建立在 Phase 1 的 EventBus 和 ReActFSM 之上。

覆盖需求: TOOL-01 至 TOOL-07 + BIZ-01（8 条）
</domain>

<decisions>
## 实现决策

### 工具注册与执行管线
- **D-01:** `@tool` 装饰器完整配置——接受 name, description, permission_level, timeout, retry, tags 所有参数。type hints + docstring 自动推导未指定的字段（函数名→工具名、参数类型+描述→参数 Schema）。
- **D-02:** Pydantic 自动参数校验——装饰器内部用 type hints 构造 Pydantic 模型，调用前自动 Marshal + Validate。校验失败直接返回结构化错误注入上下文，不调用工具。
- **D-03:** Python→JSON Schema 类型映射表——str→string, int→integer, float→number, bool→boolean, Optional[X]→anyOf[X,null], list[X]→array, Union[X,Y]→anyOf[X,Y], Enum→enum, Literal→enum。不引入额外依赖，覆盖绝大多数实际场景。
- **D-04:** 实例注册表+命名空间——ToolRegistry 可创建多个实例，每个实例可配置不同权限策略和工具集。工具分 namespace（如 'bash.df', 'disk.du'）。支持未来多 agent 场景。
- **D-05:** ToolResult 标准化包装——所有工具返回统一包装为 ToolResult(status, data, error, duration_ms, truncated)，超过长度限制的自动截断+溢出文件引用。
- **D-06:** sync/async 双支持——管线自动检测函数类型，async 函数用 await 调用，sync 函数用 `asyncio.to_thread()` 在线程池中执行。
- **D-07:** 装饰器默认超时+可覆盖——每个工具在 @tool() 中有独立 timeout 值。全局默认 30s。Bash 工具默认 60s。超时后 asyncio.wait_for 取消执行并注入 TimeoutError。

### Bash 安全与权限分级
- **D-08:** 白名单为底+黑名单升级——白名单命令（ls, df, du, find, cat, head, tail, wc, grep, sort, uniq, echo, stat）直接放行标记为 safe。不在白名单但非黑名单的标记为 moderate。命中黑名单（rm, dd, mkfs, > 设备重定向、chmod 777 /）强制标记为 dangerous 需确认。
- **D-09:** 事件驱动确认暂停——agent 通过 EventBus 发出 confirmation_required 事件，状态机暂停在 ACT 前。CLI 消费者展示命令详情等待 y/n。Phase 5 前端可通过 SSE 展示确认弹窗。
- **D-10:** 按影响范围划分权限级别——safe: 只读操作且限于工作目录内。moderate: 写操作但在用户目录内（cp, mv, mkdir, touch）。dangerous: 不可逆操作或超出用户目录范围（/etc, /dev, /sys, /proc, /boot）。同一命令（如 rm）根据路径不同可属于不同级别。

### 错误分类与重试策略
- **D-11:** 异常类型映射——TransientError(超时、网络、ConnectionError、RateLimitError)→可重试。ToolExecutionError(非零退出码、参数无效、JSON 解析失败)→不重试但注入上下文给 LLM。GuardViolationError(权限不足、危险命令被拒)→向 LLM 说明原因。FatalError(OOM、磁盘满、API key 无效)→立即终止会话。
- **D-12:** 装饰器可配置重试参数——@tool(retry=RetryConfig(max_attempts=3, base_delay=1.0, max_delay=60.0, backoff=2.0, jitter=0.1))。有全局默认值，工具作者可按需覆盖。
- **D-13:** 仅 TransientError 触发自动重试——ToolExecutionError、GuardViolationError、FatalError 直接返回结果或终止，不重试。

### 磁盘清理业务验证
- **D-14:** 最小工具集——df（磁盘使用概览）、du（定位大文件目录）、find（按大小/类型筛选）、rm（执行删除）。共 4 个 Bash 工具覆盖诊断→分析→确认→清理全流程。
- **D-15:** 预设场景+自由探索——系统预设磁盘空间不足场景（/tmp/loopai-demo/ 沙箱内创建模拟日志、缓存、临时文件）。agent 自主运行诊断流程，用户可以自然语言干预（"不要删 nginx 日志"）。
- **D-16:** 沙箱执行边界——rm 操作限制在 /tmp/loopai-demo/ 内。df 展示真实系统数据，但清理操作完全在沙箱内——安全无风险。

### Claude 可自行决定
以下领域未在讨论中锁定:
- ToolRegistry 的并发安全（多 agent 同时注册工具时的锁策略）
- 命令注入防护的具体实现细节（管道、反引号、$()、&&、|| 的处理）
- 重试计数器重置窗口（多长时间后重置失败计数）
- 预设场景中文件类型和目录结构的具体设计
- 工具 Schema 生成中 Literal/Annotated/泛型等边缘类型的处理
- Bash 工具的工作目录配置（相对于 session 还是绝对路径）
</decisions>

<canonical_refs>
## 规范参考

**下游 agent 在规划或实现前必须阅读以下文件:**

### 项目级文档
- `.planning/ROADMAP.md` — 阶段定义、依赖关系、成功标准
- `.planning/REQUIREMENTS.md` — TOOL-01 至 TOOL-07 + BIZ-01 完整需求描述
- `.planning/PROJECT.md` — 项目核心价值、技术栈、安全约束
- `CLAUDE.md` — 推荐技术栈详情

### 阶段 1 上下文（依赖）
- `.planning/phases/01-agent-core-loop/01-CONTEXT.md` — Phase 1 决策（EventBus 架构、分层事件结构、工具调用事件类型）
- `.planning/phases/01-agent-core-loop/01-RESEARCH.md` — 现有代码架构（EventBus、FSM、Guards、LLMClient 已在 src/loopai/ 下）

### 阶段 2 需求
- `TOOL-01`: @tool 装饰器+JSON Schema 自动生成
- `TOOL-02`: 工具执行管线（校验→沙箱→结果→注入）
- `TOOL-03`: Bash/Shell 工具（subprocess, shell=False, 超时）
- `TOOL-04`: 危险命令确认机制
- `TOOL-05`: 命令权限分级（safe/moderate/dangerous）
- `TOOL-06`: 错误分类体系（4 类+不同恢复策略）
- `TOOL-07`: 瞬时错误重试（指数退避+随机抖动）
- `BIZ-01`: 磁盘空间诊断与清理端到端验证
</canonical_refs>

<code_context>
## 现有代码洞察

### 可复用资产
- `src/loopai/events/bus.py` — EventBus（Phase 1），工具执行和确认流程可直接使用 pub/sub
- `src/loopai/events/schemas.py` — 事件 pydantic 模型，需扩展 tool_call 和 confirmation 事件
- `src/loopai/state_machine/fsm.py` — ReActFSM，需在 ACT 状态前插入工具注册表检查和权限守卫
- `src/loopai/state_machine/guards.py` — BudgetGuard/LoopDetector/MessageValidator 模式，新增 PermissionGuard 和 ErrorClassifier
- `src/loopai/llm/client.py` — LLMClient（OpenAI beta streaming），工具 Schema 需通过 function calling 传递给 LLM

### 集成点
- FSM 的 ACT 状态需要 ToolRegistry 来查找和调用工具
- EventBus 需要新增事件类型：tool_call_start, tool_call_args, tool_call_done, tool_result, confirmation_required, confirmation_response
- CLI 渲染器需要处理 confirmation_required 事件（展示命令详情+等待输入）
</code_context>

<specifics>
## 具体想法

讨论中用户提及:
- 偏好完整配置而非最小配置（工具元数据驱动）
- 偏好自动化（自动 Schema 生成、自动错误分类）而非手动
- 安全决策偏谨慎——按影响范围分级、仅 TransientError 重试、沙箱执行
- 演示设计偏可控——预设场景但保留用户自然语言干预空间
</specifics>

<deferred>
## 延期想法

无——讨论保持在阶段范围内。
</deferred>

---

*阶段: 2-工具系统与业务验证*
*上下文收集时间: 2026-05-27*
