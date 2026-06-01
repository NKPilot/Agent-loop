# Phase 9: 安全加固与沙箱隔离 - Discussion Log

> **Audit trail only.** Decisions captured in CONTEXT.md.

**Date:** 2026-05-31
**Phase:** 09-security-hardening
**Areas discussed:** 加固方式, 网络隔离, 文件隔离, 资源限制, 审计日志

---

## 加固方式

| Option | Description | Selected |
|--------|-------------|----------|
| 增量增强 | 在现有 SandboxExecutor 上叠加网络隔离、文件校验 | ✓ |
| 新建独立沙箱类 | 新建 HardenedSandboxExecutor | |
| 外部沙箱方案 | nsjail/gVisor | |

## 网络隔离

| Option | Description | Selected |
|--------|-------------|----------|
| 网络命名空间 | unshare(CLONE_NEWNET) | ✓ |
| iptables 规则 | preexec_fn iptables | |
| 仅 AST 检测 | 不做 OS 级隔离 | |

## 文件隔离

| Option | Description | Selected |
|--------|-------------|----------|
| 路径白名单 | cwd 限制 + 白名单校验 | ✓ |
| chroot 隔离 | 临时 chroot 环境 | |
| mount namespace | 完全隔离文件系统视图 | |

## 资源限制

| Option | Description | Selected |
|--------|-------------|----------|
| 统一限制 | 30s/512MB/无网络/白名单 | ✓ |
| 按语言分级 | Python 更宽松 | |
| 用户可调 | 确认时可自定义 | |

## 审计日志

| Option | Description | Selected |
|--------|-------------|----------|
| 完整审计 | EventBus 事件 + JSONL | ✓ |
| 仅日志 | Python logging | |
