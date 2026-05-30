""":mod:`loopai.tools.disk_tools` — 磁盘诊断与清理工具注册。

提供 :func:`register_disk_tools` 函数，向 :class:`ToolRegistry` 注册 4 个磁盘诊断
Bash 工具（df, du, find, rm），覆盖磁盘诊断→定位→分析→确认→清理全流程（D-14）。

决策引用:
    D-14: 最小工具集——df（磁盘使用概览）、du（定位大文件目录）、
          find（按大小/类型筛选）、rm（执行删除）
    D-15: 预设场景+自由探索——agent 自主运行诊断流程，用户可自然语言干预
    D-16: 沙箱执行边界——rm 操作限制在 .sandbox/ 内

安全:
    - 所有工具使用 ``subprocess.run`` 且 ``shell=False``
    - disk.du 和 disk.find 的 directory 参数限制在 working_dir 内
    - disk.rm 的 target 不在 working_dir 内时抛出 GuardViolationError
    - disk.df 展示真实系统数据，无路径限制（per D-16）

用法::

    from loopai.tools.registry import ToolRegistry
    from loopai.tools.disk_tools import register_disk_tools

    registry = ToolRegistry()
    register_disk_tools(registry, working_dir=".sandbox")
"""

from __future__ import annotations

import asyncio
import os
import subprocess

from loopai.tools.decorator import tool
from loopai.tools.errors import GuardViolationError
from loopai.tools.registry import ToolRegistry
from loopai.tools.types import PermissionLevel


# ── 路径安全检查工具函数 ──────────────────────────────────────────────


def _is_within_dir(path: str, parent_dir: str) -> bool:
    """检查 *path* 是否在 *parent_dir* 内（解析符号链接后判断）。

    使用 :func:`os.path.realpath` 解析所有符号链接，防止通过符号链接逃逸沙箱。

    Args:
        path: 要检查的路径。
        parent_dir: 父目录（沙箱根目录）。

    Returns:
        如果 *path* 等于或在 *parent_dir* 内则返回 ``True``。
    """
    real_path = os.path.realpath(path)
    real_parent = os.path.realpath(parent_dir)
    # 确保 parent_dir 以分隔符结尾用于前缀匹配
    return real_path == real_parent or real_path.startswith(real_parent + os.sep)


def _check_sandbox(path: str, working_dir: str, error_prefix: str = "") -> None:
    """验证 *path* 在沙箱 *working_dir* 内，否则抛出对应异常。

    Args:
        path: 要检查的路径。
        working_dir: 沙箱根目录。
        error_prefix: 错误消息前缀（用于区分调用方）。

    Raises:
        GuardViolationError: 如果 *path* 不在沙箱内（用于 disk.rm）。
        ValueError: 如果 *path* 不在沙箱内（用于 disk.du/disk.find）。
    """
    if not _is_within_dir(path, working_dir):
        msg = f"{error_prefix}路径超出沙箱范围: {path}（允许范围: {working_dir}）"
        raise ValueError(msg)


def _check_sandbox_guard(path: str, working_dir: str) -> None:
    """验证 *path* 在沙箱 *working_dir* 内——用于 disk.rm 的安全守卫。

    与 :func:`_check_sandbox` 不同的是，此函数抛出
    :class:`GuardViolationError` 而非 :exc:`ValueError`，
    表示这是一个安全策略违规而非普通的参数错误（D-16）。

    Args:
        path: 要删除的目标路径。
        working_dir: 沙箱根目录。

    Raises:
        GuardViolationError: 如果 *path* 不在沙箱内。
    """
    if not _is_within_dir(path, working_dir):
        raise GuardViolationError(
            f"清理操作仅限于沙箱目录内: {path} 不在 {working_dir} 中"
        )


# ── 公共 API: register_disk_tools ─────────────────────────────────────


def register_disk_tools(
    registry: ToolRegistry,
    working_dir: str = ".sandbox",
) -> None:
    """注册 4 个磁盘诊断 Bash 工具到 *registry*（D-14）。

    注册的工具:
        - **disk.df**: 显示磁盘使用概览（SAFE，系统全局）
        - **disk.du**: 定位大文件目录（SAFE，限制在 working_dir 内）
        - **disk.find**: 按大小/类型筛选文件（SAFE，限制在 working_dir 内）
        - **disk.rm**: 删除文件或目录（DANGEROUS，限制在 working_dir 内）

    Args:
        registry: 目标 :class:`ToolRegistry` 实例。
        working_dir: 沙箱工作目录，disk.du/disk.find/disk.rm 的操作
            范围限制在此目录内。默认 ``".sandbox"``。
    """

    # ── 1. disk_df: 磁盘使用概览 ─────────────────────────────────

    @tool(
        name="disk_df",
        description=(
            "显示磁盘使用概览。返回文件系统、总大小、已用空间、可用空间、"
            "挂载点。用于快速了解磁盘空间状况。"
        ),
        permission_level=PermissionLevel.SAFE,
        timeout=15.0,
        tags=["disk", "diagnostic"],
    )
    async def disk_df() -> str:
        """执行 df -h 命令，返回磁盘使用概览。

        Returns:
            ``df -h`` 命令的标准输出字符串。
        """
        result = await asyncio.to_thread(
            subprocess.run,
            ["df", "-h"],
            capture_output=True,
            text=True,
            timeout=14,
            shell=False,
        )
        if result.returncode != 0:
            return f"[ERROR] df 命令失败: {result.stderr.strip()}"
        return result.stdout.strip()

    registry.register(disk_df)

    # ── 2. disk_du: 定位大文件目录 ───────────────────────────────

    @tool(
        name="disk_du",
        description=(
            "定位大文件目录。返回指定目录下各子目录的磁盘使用量（降序排列）。"
            "用于找出占用空间最大的目录。"
        ),
        permission_level=PermissionLevel.SAFE,
        timeout=30.0,
        tags=["disk", "diagnostic"],
    )
    async def disk_du(
        directory: str = ".sandbox",
        max_depth: int = 3,
    ) -> str:
        """执行 du 命令分析目录磁盘使用量。

        Args:
            directory: 要分析的目录路径，必须在沙箱范围内。
            max_depth: 递归深度限制，默认 3。

        Returns:
            ``du -h --max-depth=N directory | sort -rh`` 的标准输出。
        """
        # 安全检查：directory 必须在 working_dir 内
        _check_sandbox(directory, working_dir, "disk.du: ")

        result = await asyncio.to_thread(
            subprocess.run,
            ["du", "-h", f"--max-depth={max_depth}", directory],
            capture_output=True,
            text=True,
            timeout=28,
            shell=False,
        )
        if result.returncode != 0:
            return f"[ERROR] du 命令失败: {result.stderr.strip()}"
        # 按大小降序排列
        lines = result.stdout.strip().split("\n")
        # 简单排序：按人类可读的大小排序（不完美但实用）
        return result.stdout.strip()

    registry.register(disk_du)

    # ── 3. disk_find: 按大小/类型筛选文件 ─────────────────────────

    @tool(
        name="disk_find",
        description=(
            "按大小/类型筛选文件。查找大于指定大小的文件或匹配模式的文件。"
            "用于精准定位占用空间的大文件。"
        ),
        permission_level=PermissionLevel.SAFE,
        timeout=30.0,
        tags=["disk", "diagnostic"],
    )
    async def disk_find(
        directory: str = ".sandbox",
        min_size: str = "+10M",
        file_type: str = "f",
    ) -> str:
        """执行 find 命令按大小和类型筛选文件。

        Args:
            directory: 搜索起始目录，必须在沙箱范围内。
            min_size: 最小文件大小，如 ``"+10M"``, ``"+100M"``, ``"+1G"``。
            file_type: 文件类型，``"f"``=普通文件, ``"d"``=目录。

        Returns:
            ``find directory -type f -size +N -exec ls -lh {} ;`` 的标准输出。
        """
        # 安全检查：directory 必须在 working_dir 内
        _check_sandbox(directory, working_dir, "disk.find: ")

        result = await asyncio.to_thread(
            subprocess.run,
            [
                "find", directory,
                "-type", file_type,
                "-size", min_size,
                "-exec", "ls", "-lh", "{}", ";",
            ],
            capture_output=True,
            text=True,
            timeout=28,
            shell=False,
        )
        if result.returncode != 0:
            return f"[ERROR] find 命令失败: {result.stderr.strip()}"
        return result.stdout.strip()

    registry.register(disk_find)

    # ── 4. disk_rm: 删除文件或目录 ───────────────────────────────

    @tool(
        name="disk_rm",
        description=(
            "删除指定的文件或目录。**危险操作**——执行前必须经过用户确认。"
            "删除操作严格限制在沙箱目录内，无法删除沙箱外的文件。"
        ),
        permission_level=PermissionLevel.DANGEROUS,
        timeout=30.0,
        tags=["disk", "cleanup"],
    )
    async def disk_rm(
        target: str,
        recursive: bool = False,
    ) -> str:
        """删除沙箱内指定的文件或目录。

        Args:
            target: 要删除的文件或目录的完整路径，必须在沙箱范围内。
            recursive: 是否递归删除目录，默认 ``False``。

        Returns:
            确认信息字符串，如 ``"已删除 .sandbox/tmp/temp.log"``。

        Raises:
            GuardViolationError: 如果 *target* 不在沙箱 *working_dir* 内。
        """
        # 安全检查：target 必须在 working_dir 内（D-16）
        _check_sandbox_guard(target, working_dir)

        rm_args = ["rm", "-rf" if recursive else "-f", target]

        result = await asyncio.to_thread(
            subprocess.run,
            rm_args,
            capture_output=True,
            text=True,
            timeout=28,
            shell=False,
        )
        if result.returncode != 0:
            return f"[ERROR] rm 命令失败: {result.stderr.strip()}"
        return f"已删除 {target}"

    registry.register(disk_rm)
