---
phase: 08-dynamic-tool-core
verified: 2026-05-31T14:00:00Z
status: human_needed
score: 24/24 must-haves verified
overrides_applied: 0
human_verification:
  - test: "启动应用，创建 Agent 会话，通过 Agent 发起 generate_tool 调用，观察 ToolCreationDialog 是否正常弹出"
    expected: "ToolCreationDialog 展示 7 个 Zone：工具元数据、Monaco Editor 只读代码、风险评估 Badge、可折叠自测代码、持久化 RadioGroup、目录权限 Input、自测结果区域"
    why_human: "需要完整的前后端联调环境和 SSE 通信，无法通过静态分析验证端到端流程"
  - test: "在 ToolCreationDialog 中选择 Sandbox 持久化级别，点击 Approve，观察自测是否在沙箱中执行"
    expected: "Zone 7 展示自测结果（passed/failed/timeout），通过后 SSE 发送 tool_created 事件，对话框关闭，工具出现在 system prompt 动态工具列表中"
    why_human: "沙箱自测涉及子进程隔离执行，需要实际运行环境验证资源限制和超时行为"
  - test: "创建会话级动态工具，关闭会话后检查 ToolRegistry 中该工具是否已移除"
    expected: "会话级工具（无 persist: 标签）在会话 cleanup 时被移除；沙箱级工具保留并可在下次会话中加载"
    why_human: "会话生命周期管理涉及 asyncio 任务清理、active_sessions 字典状态变更，需要运行时验证"
  - test: "在 ToolCreationDialog 中选择 Reject 按钮或按 Escape 键，观察 Agent 是否收到拒绝响应并继续执行"
    expected: "拒绝后 Agent 收到 ToolResult.error('用户拒绝创建工具')，Agent 继续执行后续步骤"
    why_human: "EventBus + asyncio.Event 阻塞解除和 Agent 恢复执行需要完整 FSM 运行环境验证"
---

# Phase 8: 动态工具创建核心 Verification Report

**Phase Goal:** Agent 提议工具代码、语法检查+危险扫描、前端确认弹窗（ToolCreationDialog）、Agent自测验证、三级持久化注册
**Verified:** 2026-05-31
**Status:** human_needed
**Re-verification:** No -- initial verification

## Verdict

All 24 must-have truths verified at code level. All 13 Phase 8 requirements (DYN-01 through DYN-10, DYN-24 through DYN-26) satisfied with implementation evidence. TypeScript compiles clean. No debt markers found. Behavioral spot-checks on Python modules all pass. **4 human verification items** identified for end-to-end flow validation -- visual UI rendering, sandbox execution, session lifecycle, and agent recovery after rejection require running environment.

## Goal Achievement

### Observable Truths

All 24 must-haves across 5 plans:

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | ToolMetadata 模型包含 is_dynamic 布尔字段，默认 False | VERIFIED | `types.py:214`: `is_dynamic: bool = False` -- default False, not excluded from serialization |
| 2 | 6 个新事件类型定义在 schemas.py 的 Event 联合类型中 | VERIFIED | `schemas.py` lines 315-388: ToolCreationRequested, ToolCreationConfirmed, ToolCreationRejected, ToolCreationTestResult, ToolCreated, ToolCreationFailed; Event union lines 424-429 |
| 3 | TypeScript 端有镜像的事件接口定义 | VERIFIED | `eventTypes.ts` lines 232-284: all 6 TS interfaces + RiskFlag; Event union lines 356-361; EVENT_TYPE_MAP lines 392-397 |
| 4 | ConfirmToolCreationRequest API schema 包含 persistence 和 extra_dirs 字段 | VERIFIED | `api/schemas.py` lines 87-117: PersistenceLevel type + ConfirmToolCreationRequest model with persistence + extra_dirs |
| 5 | DangerousModuleScanner 检测 30+ 禁止入口 | VERIFIED | 39 total forbidden entries (26 FORBIDDEN_IMPORTS + 6 FORBIDDEN_CALLS + 7 BYPASS_PATTERNS) -- exceeds 30+ requirement |
| 6 | SandboxExecutor 子进程执行带超时和资源限制 | VERIFIED | `sandbox.py` lines 293-434: subprocess.run(shell=False), preexec_fn=_set_limits, RLIMIT_CPU/AS/NPROC, TimeoutExpired handling |
| 7 | ToolRegistry 分区存储 _static_tools + _dynamic_tools | VERIFIED | `registry.py` lines 53-54: two dicts; `register_meta(is_dynamic=True)` enforces `dynamic.` prefix (line 101) |
| 8 | ToolPersistenceManager 三级持久化 | VERIFIED | `tool_persistence.py` lines 29-41: SANDOX_DIR=".sandbox/tools", PROJECT_DIR="src/loopai/tools/dynamic"; save/load_sandbox_tools/load_project_tools/delete methods |
| 9 | generate_tool 是 @tool 装饰的内置工具 | VERIFIED | `dynamic_creator.py` lines 640-651: `create_generate_tool_fn` returns @tool decorated function with MODERATE permission, 120s timeout |
| 10 | DynamicToolCreator 实现 6 阶段管道 | VERIFIED | `dynamic_creator.py` lines 88-170: Stage 0 (validate) -> Stage 1 (syntax) -> Stage 2 (danger scan) -> Stage 3 (confirm) -> Stage 4 (self-test) -> Stage 5+6 (persist+register) |
| 11 | 语法检查失败返回结构化 ToolResult.error | VERIFIED | Stage 1 returns ToolResult.error with line number and error message for SyntaxError/bash -n failures |
| 12 | 用户确认通过 EventBus + asyncio.Event 暂停，无超时 | VERIFIED | `dynamic_creator.py` lines 363-384: asyncio.Event creation, bus.publish, await wait_event.wait() without timeout |
| 13 | 动态工具以 dynamic.{sha256[:8]}_{name} 命名 | VERIFIED | `dynamic_creator.py` tool_id format: `f"dynamic.{hashlib.sha256(code.encode()).hexdigest()[:8]}_{name}"` |
| 14 | generate_tool 在 create_agent_components 中注册 | VERIFIED | `main.py` lines 98-108: SandboxExecutor + ToolPersistenceManager + DynamicToolCreator created, generate_tool registered |
| 15 | POST confirm-tool-creation 端点存在 | VERIFIED | `control.py` lines 276-335: `/sessions/{session_id}/confirm-tool-creation` with 3-layer validation (session -> dynamic_creator -> confirmation_id) |
| 16 | build_system_prompt 追加动态工具列表 | VERIFIED | `prompt_builder.py` lines 57-70: iterates registry.list_all() for is_dynamic tools, appends "## 动态工具" section |
| 17 | 会话关闭时自动移除会话级动态工具 | VERIFIED | `control.py` lines 134-144: cleanup iterates list_dynamic(), removes tools without persist: tag |
| 18 | ToolCreationDialog 独立组件，无超时 | VERIFIED | `ToolCreationDialog.tsx`: reads `pendingToolCreation` from uiStore, no setTimeout/auto-reject timer (D-04 compliant) |
| 19 | Monaco Editor 只读模式，语法高亮 | VERIFIED | `ToolCreationDialog.tsx` lines 209-222: `<Editor language={...} options={{ readOnly: true }} />` with vs-dark theme |
| 20 | 危险模块 Badge 按 severity 着色 | VERIFIED | `ToolCreationDialog.tsx` lines 243-264: high=destructive, medium=amber text, low=secondary; empty shows green "No Risks Detected" |
| 21 | 持久化 RadioGroup 三选一，默认 Session | VERIFIED | `ToolCreationDialog.tsx` lines 327-348: RadioGroup with session/sandbox/project, defaultValue="session" |
| 22 | 目录权限 Input 允许输入额外目录 | VERIFIED | `ToolCreationDialog.tsx` lines 367-382: Input with placeholder, onChange sets `extraDirsInput` |
| 23 | 自测代码可折叠预览，Zone 7 展示结果 | VERIFIED | `ToolCreationDialog.tsx` lines 275-315 (Zone 4 collapsed), lines 387-450 (Zone 7 conditional render) |
| 24 | Approve/Reject 通过 confirmToolCreation API 回传 | VERIFIED | `ToolCreationDialog.tsx` lines 97-103 (handleApprove), lines 124-127 (handleReject) both call confirmToolCreation |

**Score:** 24/24 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/loopai/tools/types.py` | is_dynamic field | VERIFIED | Line 214: `is_dynamic: bool = False`, with docstring, not excluded from serialization |
| `src/loopai/events/schemas.py` | 6 events + Event union | VERIFIED | All 6 event classes (lines 315-388), Event union extended (lines 424-429) |
| `src/loopai/api/schemas.py` | ConfirmToolCreationRequest | VERIFIED | PersistenceLevel type + model with confirmation_id/approved/persistence/extra_dirs |
| `frontend/src/lib/eventTypes.ts` | TS event interfaces | VERIFIED | RiskFlag + 6 event interfaces + Event union + EVENT_TYPE_MAP (all 6 entries) |
| `frontend/package.json` | @monaco-editor/react | VERIFIED | `"@monaco-editor/react": "4.8.0-rc.3"` |
| `src/loopai/tools/sandbox.py` | Scanner + Executor | VERIFIED | DangerousModuleScanner (39 entries) + SandboxExecutor (subprocess + rlimit) |
| `src/loopai/tools/registry.py` | Partition registry | VERIFIED | _static_tools/_dynamic_tools, dynamic. prefix enforcement, remove() static protection |
| `src/loopai/tools/tool_persistence.py` | 3-tier persistence | VERIFIED | save/load_sandbox_tools/load_project_tools/delete; SANDOX_DIR + PROJECT_DIR |
| `src/loopai/tools/dynamic_creator.py` | DynamicToolCreator + generate_tool | VERIFIED | 6-stage pipeline, respond(), _make_func_ref (Pitfall 3), create_generate_tool_fn |
| `src/loopai/main.py` | Factory integration | VERIFIED | create_agent_components registers generate_tool, returns dynamic_creator |
| `src/loopai/api/routes/control.py` | Endpoint + cleanup | VERIFIED | confirm_tool_creation endpoint (3-layer validation), session cleanup in _run_and_cleanup |
| `src/loopai/tools/prompt_builder.py` | Dynamic tool list | VERIFIED | build_system_prompt appends "## 动态工具" section for is_dynamic tools |
| `frontend/src/components/ToolCreationDialog.tsx` | 7-zone confirmation dialog | VERIFIED | All 7 zones present, Monaco Editor, RadioGroup, Badges, ScrollArea, no timeout |
| `frontend/src/stores/uiStore.ts` | Tool creation state | VERIFIED | 5 new fields + 5 setters + clearPendingToolCreation |
| `frontend/src/lib/api.ts` | confirmToolCreation API | VERIFIED | POST function with sessionId/confirmationId/approved/persistence/extraDirs |
| `frontend/src/App.tsx` | Dialog rendering | VERIFIED | `<ToolCreationDialog />` rendered after `<ConfirmationDialog />` |
| `frontend/src/hooks/useSessionEvents.ts` | SSE routing | VERIFIED | 3 event routes: tool_creation_requested, tool_creation_test_result, tool_created |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| Event union (schemas.py) | TS Event union (eventTypes.ts) | event_type discriminator | WIRED | 6 event types mirrored, event_type literal matching |
| ToolRegistry.register_meta(is_dynamic=True) | dynamic. prefix enforcement | ValueError on missing prefix | WIRED | `registry.py:101`: `raise ValueError` if not `startswith("dynamic.")` |
| ToolPersistenceManager.save(project) | filesystem path | Path.write_text | WIRED | `tool_persistence.py:122-137`: writes to `src/loopai/tools/dynamic/` |
| DynamicToolCreator._request_user_confirmation | EventBus + asyncio.Event | bus.publish + event.wait() | WIRED | `dynamic_creator.py:367-384`: publish then await wait_event.wait() |
| DynamicToolCreator._build_and_register | ToolRegistry.register_meta(is_dynamic=True) | ToolMetadata construction | WIRED | `dynamic_creator.py:538`: `self._registry.register_meta(meta, is_dynamic=True)` |
| main.py create_agent_components | ToolRegistry.register (generate_tool) | create_generate_tool_fn | WIRED | `main.py:107-108`: `generate_tool_fn = create_generate_tool_fn(dynamic_creator)` then `registry.register(generate_tool_fn)` |
| control.py confirm_tool_creation | DynamicToolCreator.respond() | active_sessions lookup | WIRED | `control.py:328`: `dynamic_creator.respond(body.confirmation_id, body.approved, config)` |
| ToolCreationDialog handleApprove | api.ts confirmToolCreation() | POST /confirm-tool-creation | WIRED | Line 97: `await confirmToolCreation(sessionId, event.confirmation_id, true, persistence, ...)` |
| useSessionEvents onEvent | uiStore.setPendingToolCreation() | event_type literal match | WIRED | Line 42-43: checks `eventType === "tool_creation_requested"` AND `data.event_type`, then sets uiStore |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| ToolCreationDialog | `pendingToolCreation` | SSE event from EventBus via useSessionEvents | Real SSE data from agent pipeline | FLOWING |
| ToolCreationDialog Zone 7 | `toolCreationTestResult` | SSE event from Stage 4 self-test | Real subprocess execution result | FLOWING |
| DynamicToolCreator | `risk_flags` | DangerousModuleScanner.scan() / _scan_bash_danger() | Real AST analysis / regex matching | FLOWING |
| ToolMetadata (dynamic) | `is_dynamic: True` | register_meta(is_dynamic=True) | Real boolean set at registration time | FLOWING |
| build_system_prompt dynamic list | `meta.is_dynamic` | registry.list_all() filter | Real ToolMetadata from ToolRegistry | FLOWING |
| Session cleanup | `meta.tags` | registry.list_dynamic() | Real tags from ToolMetadata | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| ToolMetadata is_dynamic default | `python -c "m=ToolMetadata(...); assert m.is_dynamic == False"` | OK | PASS |
| DangerousModuleScanner detects 6 issues in malicious code | `scanner.scan('import os\nimport subprocess\neval("1+1")...')` | 6 issues, 6 high severity | PASS |
| Clean code produces 0 issues | `scanner.scan('import math\nimport json\nprint(1+1)')` | 0 issues | PASS |
| ToolRegistry dynamic. prefix enforcement | `r.register_meta(m3, is_dynamic=True)` with name='bad.name' | ValueError raised | PASS |
| generate_tool fn has __tool_meta__ | `gen_fn = create_generate_tool_fn(creator)` | name=generate_tool, perm=moderate, timeout=120.0 | PASS |
| DynamicToolCreator stages 0-2 pipeline | `creator._stage0_validate`, `_stage1_syntax_check`, `_stage2_danger_scan` | All pass: valid passes, invalid fails, scans detect/clean correctly | PASS |
| TypeScript compilation | `cd frontend && npx tsc --noEmit` | 0 errors | PASS |
| Persist tag for session vs sandbox | `persist:` tag check | Session: no tag (cleaned). Sandbox: `persist:sandbox` (retained) | PASS |

### Probe Execution

**No probes declared.** Phase 8 contains no `scripts/*/tests/probe-*.sh` files, and no plans reference probe-based verification. Skipping Step 7c.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| DYN-01 | 08-01, 08-03, 08-04 | Agent 通过 generate_tool 提交代码 | SATISFIED | `dynamic_creator.py`: create_generate_tool_fn + @tool decoration; `main.py`: registered to ToolRegistry |
| DYN-02 | 08-02, 08-03 | 语法检查 ast.parse/bash -n，失败返回结构化错误 | SATISFIED | `dynamic_creator.py`: _stage1_syntax_check with ast.parse/bash -n, returns ToolResult.error |
| DYN-03 | 08-02, 08-03, 08-05 | 危险扫描 30+ 入口，结果标记在确认弹窗 | SATISFIED | `sandbox.py`: 39 entries; `ToolCreationDialog.tsx`: Zone 3 Badge list with severity coloring |
| DYN-04 | 08-01, 08-02, 08-03 | 提取元数据，dynamic.{hash[:8]}_{name} 命名 | SATISFIED | `dynamic_creator.py`: tool_id format; `register_meta(is_dynamic=True)` |
| DYN-05 | 08-01, 08-03, 08-05 | ToolCreationDialog Monaco Editor 语法高亮只读 | SATISFIED | `ToolCreationDialog.tsx`: Zone 2 Monaco Editor readOnly, language selector for python/shell |
| DYN-06 | 08-01, 08-05 | 用户选择持久化级别 3 选 1 | SATISFIED | `ToolCreationDialog.tsx`: Zone 5 RadioGroup session/sandbox/project, default session |
| DYN-07 | 08-01, 08-05 | 用户可指定额外目录权限 | SATISFIED | `ToolCreationDialog.tsx`: Zone 6 Input; `dynamic_creator.py`: extra_dirs passed to sandbox config |
| DYN-08 | 08-01, 08-03, 08-04, 08-05 | 用户确认/拒绝通过 EventBus 事件回传 | SATISFIED | `dynamic_creator.py`: Stage 3 bus.publish + event.wait(); `control.py`: respond() endpoint; SSE events routed to uiStore |
| DYN-09 | 08-02, 08-03 | 语法检查通过后沙箱自测 | SATISFIED | `dynamic_creator.py`: Stage 4 self-test via SandboxExecutor.execute(), result published as event |
| DYN-10 | 08-01, 08-03, 08-05 | 自测结果展示在确认弹窗 | SATISFIED | `ToolCreationDialog.tsx`: Zone 7 conditional render with passed/failed/timeout colored alerts |
| DYN-24 | 08-01, 08-02, 08-04 | 会话级工具内存注册，会话结束自动清理 | SATISFIED | `control.py`: _run_and_cleanup removes tools without persist: tag; `registry.py`: remove() method |
| DYN-25 | 08-01, 08-02 | 沙箱级工具保存到 .sandbox/tools/，启动时加载 | SATISFIED | `tool_persistence.py`: save/load_sandbox_tools using SANDOX_DIR=".sandbox/tools" |
| DYN-26 | 08-01, 08-02 | 项目级工具保存到 src/loopai/tools/dynamic/，可 git 提交 | SATISFIED | `tool_persistence.py`: save/load_project_tools using PROJECT_DIR="src/loopai/tools/dynamic" |

**All 13 Phase 8 requirements:** SATISFIED. No orphaned requirements (DYN-11 through DYN-23 are mapped to Phases 9 and 10).

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `ToolCreationDialog.tsx` | 376 | `placeholder="e.g. /home/user/projects/data"` | None | HTML input placeholder attribute -- not a code debt marker |

**No blocking anti-patterns found.** No TBD/FIXME/XXX markers. No TODO/HACK placeholders. No hardcoded empty data. No console.log-only implementations. No setInterval/setTimeout auto-reject timers.

### Human Verification Required

#### 1. End-to-End Tool Creation Flow
**Test:** 启动应用，创建 Agent 会话，触发 Agent 调用 generate_tool 提交 Python 代码（例如一个简单的磁盘检查工具），观察完整流程
**Expected:** ToolCreationDialog 弹出并正确展示 7 个 Zone，Monaco Editor 显示代码并语法高亮，风险 Badge 正确着色。用户点击 Approve 后自测在沙箱执行，Zone 7 展示结果。通过后 tool_created SSE 事件关闭对话框，system prompt 追加动态工具。
**Why human:** 需要完整的前后端联调环境和 SSE 通信，涉及 EventBus 分发、asyncio.Event 阻塞/解除、subprocess 子进程执行

#### 2. Sandbox Self-Test Execution
**Test:** 选择 Sandbox 持久化级别，提交带 test_code 的工具创建请求，观察自测结果
**Expected:** 代码和测试代码合并后在隔离子进程中执行（subprocess.run + resource.setrlimit），Zone 7 展示 passed/failed/timeout 及输出日志。自测失败时 Agent 收到错误信息，工具不被注册
**Why human:** 沙箱自测涉及子进程隔离、资源限制（RLIMIT_CPU/AS/NPROC）、超时捕获，需要实际运行环境验证

#### 3. Session-Level Tool Cleanup
**Test:** 创建会话级动态工具（默认 persistence=session），正常关闭会话，验证工具被移除
**Expected:** 会话级工具（无 persist: 标签）在 _run_and_cleanup 中被自动移除。沙箱级/项目级工具保留。下次会话中沙箱级/项目级工具可被 load_*_tools() 重新加载
**Why human:** 会话生命周期管理涉及 asyncio 任务清理、active_sessions 字典状态变更、持久化文件系统操作

#### 4. User Rejection Recovery
**Test:** 在 ToolCreationDialog 中选择 Reject 按钮或按 Escape 键，观察 Agent 行为
**Expected:** 拒绝后 DynamicToolCreator.respond(approved=False) 被调用，asyncio.Event 唤醒，generate_tool 管道返回 ToolResult.error('用户拒绝创建工具')，Agent 继续执行后续步骤（如尝试不同的代码或工具）
**Why human:** EventBus + asyncio.Event 阻塞解除和 Agent 恢复执行需要完整 FSM 运行环境验证

## Gaps Summary

**No code-level gaps found.** All 24 must-have truths verified, all 13 requirements satisfied, all key links wired, TypeScript compiles clean, behavioral spot-checks pass.

**4 human verification items** require running frontend+backend environment for end-to-end validation. These are categorized as human_needed because:
1. SSE event flow requires a running EventBus and browser connection
2. Subprocess sandbox execution cannot be fully validated via static analysis
3. Session lifecycle cleanup requires asyncio task orchestration
4. Agent recovery after rejection requires FSM state machine continuity

---
_Verified: 2026-05-31_
_Verifier: Claude (gsd-verifier)_
