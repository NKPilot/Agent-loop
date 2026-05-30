---
phase: 05
plan: 06
subsystem: frontend
tags: [tool-detail, token-tracking, recharts, confirmation-dialog, session-tabs]
requires: [05-04, 05-05]
affects: [App.tsx, ToolDetail.tsx, TokenUsageCard.tsx, ConfirmationDialog.tsx]
tech-stack:
  added:
    - recharts: "3.8.1 — AreaChart 累积成本曲线 + PieChart Token 拆分"
  patterns:
    - "JSON 语法着色通过 React 元素 token 化实现，不使用 dangerouslySetInnerHTML"
    - "危险操作确认：Zustand pendingConfirmation -> Dialog -> confirmCommand API"
    - "多 Tab 视图切换：shadcn/ui Tabs 组件 + Zustand 事件数据"
key-files:
  created:
    - frontend/src/components/ToolDetail.tsx
    - frontend/src/components/TokenUsageCard.tsx
    - frontend/src/components/ConfirmationDialog.tsx
  modified:
    - frontend/src/App.tsx
decisions:
  - "ToolDetail JSON 语法着色采用 token 解析方案（非 dangerouslySetInnerHTML），满足 T-05-17"
  - "ConfirmationDialog 使用 Dialog onOpenChange 拦截关闭事件（Escape/点击外部），自动触发拒绝操作"
  - "Raw Events Tab 使用 .join() 合并 JSON 字符串在 pre 中渲染，避免多 React 子节点问题"
metrics:
  duration: "~45 分钟"
  completed_date: "2026-05-30"
  tasks_completed: 3
  total_commits: 3
---

# Phase 05 Plan 06: ToolDetail + Token/Cost Tracking + Confirmation Dialog Summary

## 概览

构建右侧面板三件套：ToolDetail（工具调用详情）、TokenUsageCard（Token/成本追踪 + recharts 图表）、ConfirmationDialog（危险命令确认弹窗）。同时实现会话历史多 Tab 视图（Timeline / Token Usage / Raw Events）。覆盖 OBS-03（工具详情）、OBS-04（Token/成本追踪）、OBS-05（会话历史浏览）和 D-06（危险操作确认）。

### 关键交付

| 组件 | 功能 | 满足需求 |
|------|------|----------|
| ToolDetail | 选中工具调用的参数 JSON 语法高亮、结果内容、状态标记、耗时、元数据（token/cost） | OBS-03 |
| TokenUsageCard | Summary Card（4 指标）、Context Window Progress Bar、AreaChart 累积成本曲线、PieChart Token 拆分 | OBS-04 |
| ConfirmationDialog | 危险命令确认弹窗、命令详情、标记原因、超时倒计时、批准/拒绝操作 | D-06 |
| 会话历史 Tabs | "Timeline"/"Token Usage"/"Raw Events" 三 Tab 切换，键盘快捷键 t/u/r | OBS-05 |

## 任务执行详情

### Task 1: ToolDetail 组件

**提交:** `85fbe8c`

- 创建 `ToolDetail.tsx`：从 Zustand store 读取 `selectedToolCallId` 和 `activeSessionId`
- 空状态渲染 "Select a tool call" + 副标题（UI-SPEC 精确文案）
- 选中状态：Header（工具名 + 状态 Badge + 耗时）、Arguments（JSON 语法着色 font-mono）、Result（溢出文件引用支持）、Metadata（tool_call_id + token + cost）
- JSON 语法着色通过 token 解析实现：字符串值绿色、数字蓝色、布尔琥珀色、null 灰色
- 满足威胁模型 T-05-17：不使用 dangerouslySetInnerHTML
- 更新 `App.tsx` 右侧面板使用 ToolDetail 替换占位符

### Task 2: TokenUsageCard + recharts 图表 + 会话历史 Tabs

**提交:** `91e39cd`

- 创建 `TokenUsageCard.tsx`：
  - 从所有 StepEnd 事件提取累积 token 数据（prompt/completion/total）
  - Summary Card：网格布局显示 4 个指标（Prompt/Completion/Total/Cost）
  - Context Window Progress Bar：颜色阈值（<75% default, 75-90% amber, >90% red）
  - AreaChart：累积成本 vs 步骤曲线，渐变色填充
  - PieChart：Prompt 和 Completion 拆分，内半径 40px 环形图
  - 空状态："No token data available yet"
- 中间面板使用 shadcn/ui Tabs 组件：Timeline / Token Usage / Raw Events
- Raw Events Tab：JSON.stringify + pre + font-mono + ScrollArea
- 键盘导航：t/u/r 切换三个 Tab

### Task 3: ConfirmationDialog 危险命令确认弹窗

**提交:** `612ae63`

- 创建 `ConfirmationDialog.tsx`：
  - 监听 ZuStand `pendingConfirmation` 状态，自动弹出 Dialog
  - 标题 "Dangerous Command" + AlertTriangle 图标（destructive 颜色）
  - 显示权限等级 Badge、工具名、参数详情（monospace ScrollArea）、标记原因（amber Alert）
  - 120 秒超时倒计时，超时自动拒绝
  - "Reject Command"（outline）/ "Approve Command"（destructive）按钮
  - API 调用 loading 状态（Button disabled + Loader2 spinner）
  - 错误提示（Alert variant="destructive"）
  - Dialog 关闭时视为拒绝操作（通过 onOpenChange 拦截）
- useSessionEvents.ts 已有 confirmation_required 事件分发逻辑（无需修改）
- 渲染于 App 组件树的顶层（Dialog 使用 Radix Portal）

## Deviations from Plan

无 - 计划完全按预期执行。

## Acceptance Criteria Verification

### Task 1
- [x] ToolDetail.tsx 存在
- [x] selectedToolCallId 引用（找到 4 处）
- [x] "Select a tool call" 空状态文案
- [x] JSON.stringify/full_args 参数渲染
- [x] font-mono 至少 2 处（5 处实际）
- [x] duration_ms/is_error 引用
- [x] ToolDetail 在 App.tsx 中导入
- [x] tsc --noEmit 通过
- [x] pnpm build 通过

### Task 2
- [x] TokenUsageCard.tsx 存在
- [x] AreaChart/PieChart/ResponsiveContainer 导入（16 处）
- [x] calculateCost/formatCost/formatTokens 使用（7 处）
- [x] totalPromptTokens/totalCompletionTokens 计算（13 处）
- [x] Context Progress Bar 实现（3 处颜色类）
- [x] Tabs 组件在 App.tsx 中（9 处）
- [x] "Timeline"、"Token Usage"、"Raw Events" 标签文案
- [x] 键盘快捷键 t/u/r
- [x] tsc --noEmit 通过
- [x] pnpm build 通过

### Task 3
- [x] ConfirmationDialog.tsx 存在
- [x] pendingConfirmation 引用（20 处）
- [x] confirmCommand 调用（5 处）
- [x] AlertTriangle 图标
- [x] destructive variant（4 处）
- [x] "Approve Command" / "Reject Command" 精确文案
- [x] ConfirmationDialog 在 App.tsx 中
- [x] useSessionEvents.ts 已有 confirmation_required 分发
- [x] tsc --noEmit 通过
- [x] pnpm build 通过

## Threat Surface Scan

| Threat ID | Category | Component | Status | Mitigation |
|-----------|----------|-----------|--------|------------|
| T-05-17 | Information Disclosure | ToolDetail.tsx | mitigated | JSON 着色通过 React token 元素实现，不使用 innerHTML |
| T-05-18 | Tampering | ConfirmationDialog.tsx | mitigated | 确认请求通过 POST API 发送，服务端验证 confirmation_id |
| T-05-19 | Repudiation | ConfirmationDialog.tsx | accepted | 操作记录在 JSONL 日志中 |
| T-05-20 | Information Disclosure | Raw Events Tab (App.tsx) | accepted | v1 本地单用户工具 |

无新增安全面。

## Known Stubs

无 - 所有组件完整实现，空状态均有适当 UI 反馈。

## Self-Check: PASSED

- [x] ToolDetail.tsx 存在且构建通过
- [x] TokenUsageCard.tsx 存在且构建通过
- [x] ConfirmationDialog.tsx 存在且构建通过
- [x] App.tsx 导入并使用所有三个新组件
- [x] 所有 3 次提交存在
- [x] 无未追踪文件
