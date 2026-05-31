---
phase: 08-dynamic-tool-core
plan: 02
subsystem: tools
tags: [ast, sandbox, subprocess, rlimit, dynamic-tools, tool-registry, persistence]

requires:
  - phase: 08-dynamic-tool-core
    plan: 01
    provides: "ToolMetadata.is_dynamic 字段、ToolMetadata 基础模型"
provides:
  - "DangerousModuleScanner: AST 静态扫描器，检测 35+ 危险入口"
  - "SandboxExecutor: 子进程隔离执行 Python/Bash，resource.setrlimit 资源限制"
  - "ToolRegistry 分区存储: _static_tools + _dynamic_tools，dynamic. 命名空间强制"
  - "ToolPersistenceManager: session/sandbox/project 三级持久化读写"
affects: [08-dynamic-tool-core, 09-security-hardening]

tech-stack:
  added: []
  patterns:
    - "AST NodeVisitor 安全扫描模式：visit_* 方法 + generic_visit 确保完整遍历"
    - "分区注册表模式：_static_tools + _dynamic_tools 两个独立字典，静态优先查找"
    - "三级持久化模式：session(不写文件) / sandbox(.sandbox/tools/目录) / project(src/loopai/tools/dynamic/)"
    - "Unix preexec_fn 资源限制模式：RLIMIT_CPU/AS/NPROC，非 Unix 平台优雅跳过"

key-files:
  created:
    - "src/loopai/tools/sandbox.py - DangerousModuleScanner + SandboxExecutor"
    - "src/loopai/tools/tool_persistence.py - ToolPersistenceManager 三级持久化"
    - "src/loopai/tools/dynamic/.gitkeep - 项目级动态工具目录占位"
  modified:
    - "src/loopai/tools/registry.py - _static_tools/_dynamic_tools 分区，register_meta is_dynamic 参数"

key-decisions:
  - "DangerousModuleScanner 使用 ast.NodeVisitor 而非正则匹配：利用 Python 官方 AST 解析，避免正则绕过（如字符串中的 import）"
  - "Severity 分级采用惰性构建的类级缓存 _SEVERITY_MAP：首次 scan() 时构建，后续调用复用，避免每次实例化开销"
  - "SandboxExecutor._set_limits() 使用静态方法 + 硬编码默认值：preexec_fn 无法访问实例属性，在子进程 fork 后 exec 前执行"
  - "ToolRegistry.get() 静态优先：get(name) 先查 _static_tools 再查 _dynamic_tools，防止动态工具覆盖同名静态工具"
  - "remove() 只允许删除动态工具：静态工具编译时注册，运行时不可移除，通过 ValueError 强制保护"
  - "ToolPersistenceManager 不依赖任何外部库：纯 stdlib (os, json, shutil, pathlib)，保持零新增依赖原则"

patterns-established:
  - "AST 扫描器模式: ast.NodeVisitor 子类 + visit_* 方法 + generic_visit 确保完整遍历"
  - "分区注册表模式: 两个独立字典 + 静态优先查找 + 跨分区唯一性检查"
  - "三级持久化模式: session(无文件) / sandbox(目录结构) / project(扁平文件)"
  - "Unix 资源限制 preexec_fn 模式: resource.setrlimit + try/except 容错"

requirements-completed: [DYN-02, DYN-03, DYN-04, DYN-09, DYN-24, DYN-25, DYN-26]

duration: 10min
completed: 2026-05-31
---

# Phase 8 Plan 2: 动态工具核心 — 安全扫描与沙箱执行基础设施

**DangerousModuleScanner 检测 35+ 危险入口（含内省绕过模式），SandboxExecutor 子进程隔离执行带 rlimit 资源限制，ToolRegistry 分区存储防命名冲突，ToolPersistenceManager 三级持久化读写**

## 性能

- **Duration:** 10min
- **Started:** 2026-05-31T04:42:00Z
- **Completed:** 2026-05-31T04:47:04Z
- **Tasks:** 2
- **Files modified:** 4 (2 created, 1 modified, 1 directory created)

## 成果

- DangerousModuleScanner(ast.NodeVisitor) 扫描三类危险模式：FORBIDDEN_IMPORTS(30个模块)、FORBIDDEN_CALLS(6个内置函数)、BYPASS_PATTERNS(7个内省属性)，按 high/medium/low 三级 severity 分级
- SandboxExecutor 通过 subprocess.run(shell=False) 隔离执行 Python/Bash 代码，preexec_fn 设置 RLIMIT_CPU/AS/NPROC 资源限制，超时返回 status="timeout"，非 Unix 平台优雅跳过
- ToolRegistry 分区为 _static_tools(静态) + _dynamic_tools(动态)，register_meta(is_dynamic=True) 强制 dynamic. 前缀，get() 静态优先查找
- ToolPersistenceManager 支持 session/sandbox/project 三级持久化，load_sandbox_tools()/load_project_tools() 启动扫描，delete() 按级别清理

## 任务提交

每个任务原子提交：

1. **Task 1: 创建 DangerousModuleScanner + SandboxExecutor** - `2370ccb` (feat)
2. **Task 2: 分区 ToolRegistry + 创建 ToolPersistenceManager** - `5d048d2` (feat)

## 创建/修改的文件

- `src/loopai/tools/sandbox.py` - DangerousModuleScanner（AST 扫描器，35+ 危险入口检测）+ SandboxExecutor（子进程隔离执行，resource.setrlimit）
- `src/loopai/tools/registry.py` - ToolRegistry 分区存储：_static_tools + _dynamic_tools，remove() 拒绝静态工具删除，list_dynamic() 新增方法
- `src/loopai/tools/tool_persistence.py` - ToolPersistenceManager 三级持久化管理器：save/load/delete for session/sandbox/project
- `src/loopai/tools/dynamic/.gitkeep` - 项目级动态工具目录占位符

## 做出的决策

- DangerousModuleScanner 使用 ast.NodeVisitor 而非正则匹配：利用 Python 官方 AST 解析，避免字符串中 import 等正则绕过
- Severity 分级采用惰性构建的类级缓存：首次 scan() 时构建 _SEVERITY_MAP，后续调用复用
- SandboxExecutor._set_limits() 使用静态方法 + 硬编码默认值：preexec_fn 在子进程 fork 后 exec 前执行，无法访问实例属性
- ToolRegistry.get() 静态优先：先查 _static_tools 再查 _dynamic_tools，防止动态工具覆盖同名静态工具
- ToolPersistenceManager 零外部依赖：纯 Python stdlib (os, json, shutil, pathlib)

## 偏离计划

无 — 计划完全按原样执行。

## 遇到的问题

无。

## 威胁覆盖率

| 威胁 ID | 类别 | 组件 | 处置 | 实现覆盖 |
|---------|------|------|------|---------|
| T-08-03 | Elevation of Privilege | DangerousModuleScanner | mitigate | AST 扫描检测 35+ 禁止 import/call/attribute；BYPASS_PATTERNS 拦截内省链 |
| T-08-04 | Elevation of Privilege | SandboxExecutor | mitigate | subprocess.run(shell=False) + resource.setrlimit(RLIMIT_CPU/AS/NPROC) |
| T-08-05 | Spoofing | ToolRegistry.register_meta | mitigate | dynamic. 前缀强制校验 + _dynamic_tools 分区隔离 + 跨分区名称唯一性 |
| T-08-06 | Denial of Service | SandboxExecutor | mitigate | subprocess timeout(默认30s) + RLIMIT_CPU/AS/NPROC 资源限制 |
| T-08-07 | Information Disclosure | ToolPersistenceManager | mitigate | 写入路径限定 .sandbox/tools/ 和 src/loopai/tools/dynamic/，不读取沙箱外路径 |

## 用户设置要求

无 — 无需外部服务配置。

## 下一阶段准备情况

- DangerousModuleScanner 和 SandboxExecutor 已就绪，可供 Phase 8 后续计划（DynamicToolCreator）集成使用
- ToolRegistry 分区存储已就绪，静态工具向后兼容（register/register_meta 默认行为不变）
- ToolPersistenceManager 持久化读写已就绪，等待 DynamicToolCreator 在首次执行成功后调用 save()
- 沙箱资源限制预配置为 30s CPU / 512MB 内存 / 50 进程上限，可根据实际需求调整

## 自我检查: 通过

- 创建的文件: 全部找到 (sandbox.py, tool_persistence.py, dynamic/.gitkeep, SUMMARY.md)
- 提交: 全部找到 (2370ccb, 5d048d2)
- 验证: Both tasks and plan-level verification passed

---
*Phase: 08-dynamic-tool-core*
*Completed: 2026-05-31*
