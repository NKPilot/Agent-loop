#!/usr/bin/env bash
# ============================================================================
# setup_demo_scenario.sh — 磁盘诊断预设场景创建脚本
#
# 在项目 .sandbox/ 沙箱内创建模拟的日志、缓存、临时文件和备份文件，
# 用于磁盘空间诊断与清理的端到端验证（D-15, D-16）。
#
# 幂等性: 每次运行前先清理沙箱再重建，确保结果一致。
#
# 用法:
#     bash scripts/setup_demo_scenario.sh [沙箱目录，默认 .sandbox]
#
# 场景结构:
#     .sandbox/
#     ├── logs/
#     │   ├── app.log        (50MB,  模拟应用日志)
#     │   ├── nginx/
#     │   │   ├── access.log (200MB, 模拟 nginx 访问日志)
#     │   │   └── error.log  (30MB,  模拟 nginx 错误日志)
#     │   └── system.log     (10MB,  模拟系统日志)
#     ├── cache/
#     │   ├── pip-cache/     (100MB, 模拟 pip 缓存)
#     │   └── npm-cache/     (80MB,  模拟 npm 缓存)
#     ├── tmp/
#     │   ├── temp_20260101.tmp (5MB)
#     │   ├── temp_20260115.tmp (5MB)
#     │   └── temp_20260201.tmp (5MB)
#     └── backups/
#         └── old_db_backup.sql (500MB, 模拟旧数据库备份)
# ============================================================================

set -euo pipefail

SANDBOX="${1:-.sandbox}"

echo "=== 磁盘诊断预设场景设置 ==="
echo "沙箱目录: ${SANDBOX}"

# ── 幂等性: 清理旧场景 ────────────────────────────────────────────
if [ -d "${SANDBOX}" ]; then
    echo "清理旧场景..."
    rm -rf "${SANDBOX}"
fi

# ── 创建目录结构 ──────────────────────────────────────────────────
echo "创建目录结构..."
mkdir -p "${SANDBOX}/logs/nginx"
mkdir -p "${SANDBOX}/cache/pip-cache"
mkdir -p "${SANDBOX}/cache/npm-cache"
mkdir -p "${SANDBOX}/tmp"
mkdir -p "${SANDBOX}/backups"

# ── 创建日志文件 ──────────────────────────────────────────────────
echo "创建日志文件..."

echo "  - logs/app.log (50MB)..."
dd if=/dev/zero of="${SANDBOX}/logs/app.log" bs=1M count=50 status=none 2>/dev/null || \
    dd if=/dev/zero of="${SANDBOX}/logs/app.log" bs=1024 count=51200 2>/dev/null

echo "  - logs/nginx/access.log (200MB)..."
dd if=/dev/zero of="${SANDBOX}/logs/nginx/access.log" bs=1M count=200 status=none 2>/dev/null || \
    dd if=/dev/zero of="${SANDBOX}/logs/nginx/access.log" bs=1024 count=204800 2>/dev/null

echo "  - logs/nginx/error.log (30MB)..."
dd if=/dev/zero of="${SANDBOX}/logs/nginx/error.log" bs=1M count=30 status=none 2>/dev/null || \
    dd if=/dev/zero of="${SANDBOX}/logs/nginx/error.log" bs=1024 count=30720 2>/dev/null

echo "  - logs/system.log (10MB)..."
dd if=/dev/zero of="${SANDBOX}/logs/system.log" bs=1M count=10 status=none 2>/dev/null || \
    dd if=/dev/zero of="${SANDBOX}/logs/system.log" bs=1024 count=10240 2>/dev/null

# ── 创建缓存文件 ──────────────────────────────────────────────────
echo "创建缓存文件..."

echo "  - cache/pip-cache/ (100MB)..."
# 创建多个缓存文件以模拟真实的 pip 缓存目录
for i in $(seq 1 10); do
    dd if=/dev/zero of="${SANDBOX}/cache/pip-cache/pkg_${i}.whl" bs=1M count=10 status=none 2>/dev/null || \
        dd if=/dev/zero of="${SANDBOX}/cache/pip-cache/pkg_${i}.whl" bs=1024 count=10240 2>/dev/null
done

echo "  - cache/npm-cache/ (80MB)..."
for i in $(seq 1 8); do
    dd if=/dev/zero of="${SANDBOX}/cache/npm-cache/module_${i}.tgz" bs=1M count=10 status=none 2>/dev/null || \
        dd if=/dev/zero of="${SANDBOX}/cache/npm-cache/module_${i}.tgz" bs=1024 count=10240 2>/dev/null
done

# ── 创建临时文件 ──────────────────────────────────────────────────
echo "创建临时文件..."

echo "  - tmp/temp_20260101.tmp (5MB)..."
dd if=/dev/zero of="${SANDBOX}/tmp/temp_20260101.tmp" bs=1M count=5 status=none 2>/dev/null || \
    dd if=/dev/zero of="${SANDBOX}/tmp/temp_20260101.tmp" bs=1024 count=5120 2>/dev/null

echo "  - tmp/temp_20260115.tmp (5MB)..."
dd if=/dev/zero of="${SANDBOX}/tmp/temp_20260115.tmp" bs=1M count=5 status=none 2>/dev/null || \
    dd if=/dev/zero of="${SANDBOX}/tmp/temp_20260115.tmp" bs=1024 count=5120 2>/dev/null

echo "  - tmp/temp_20260201.tmp (5MB)..."
dd if=/dev/zero of="${SANDBOX}/tmp/temp_20260201.tmp" bs=1M count=5 status=none 2>/dev/null || \
    dd if=/dev/zero of="${SANDBOX}/tmp/temp_20260201.tmp" bs=1024 count=5120 2>/dev/null

# ── 创建备份文件 ──────────────────────────────────────────────────
echo "创建备份文件..."

echo "  - backups/old_db_backup.sql (500MB)..."
dd if=/dev/zero of="${SANDBOX}/backups/old_db_backup.sql" bs=1M count=500 status=none 2>/dev/null || \
    dd if=/dev/zero of="${SANDBOX}/backups/old_db_backup.sql" bs=1024 count=512000 2>/dev/null

# ── 验证场景 ──────────────────────────────────────────────────────
echo ""
echo "=== 场景创建完成 ==="
echo ""
echo "目录结构:"
du -sh "${SANDBOX}"/*/
echo ""
echo "文件数量: $(find "${SANDBOX}" -type f | wc -l)"
echo "总大小: $(du -sh "${SANDBOX}" | cut -f1)"
echo ""
echo "大文件列表 (>=10MB):"
find "${SANDBOX}" -type f -size +10M -exec ls -lh {} \;
echo ""
echo "预设场景已就绪，可以运行诊断流程。"
