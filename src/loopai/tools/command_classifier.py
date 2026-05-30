""":mod:`loopai.tools.command_classifier` — 命令白名单/黑名单分类器。

根据命令标识、参数模式和目标路径，将 shell 命令分类到
:class:`PermissionLevel` 级别（SAFE、MODERATE、DANGEROUS）。
实现路径感知升级：访问系统目录的 SAFE 命令（例如 ``ls /etc``）
升级为 MODERATE；访问系统目录的 MODERATE 命令升级为 DANGEROUS。

决策引用:
    D-08: 基于白名单 + 黑名单升级的分类
    D-10: 路径感知的权限升级（SAFE → MODERATE → DANGEROUS）

用法::

    from loopai.tools.command_classifier import CommandClassifier

    classifier = CommandClassifier()
    level, reason = classifier.classify("rm", ["-rf", "/etc"], "/home/user")
    # -> (PermissionLevel.DANGEROUS, "命中黑名单命令 rm")
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from loopai.tools.types import PermissionLevel


class CommandClassifier:
    """按权限级别（SAFE/MODERATE/DANGEROUS）对 shell 命令进行分类。

    分类遵循确定性的优先级链：

    1. **Shell 元字符检测**——管道、命令替换和逻辑运算符
       不受支持；整个命令被保守地分类为 MODERATE。
    2. **黑名单检查**——匹配 :attr:`DANGEROUS_COMMANDS` 的命令
       无论参数如何都被立即标记为 DANGEROUS。
    3. **模式扫描**——参数字符串根据 :attr:`DANGEROUS_PATTERNS`
       进行检查（例如 ``chmod 777 /``、``> /dev/``）。
    4. **路径范围升级**——如果任何参数以 :attr:`SYSTEM_PATHS` 中的
       系统路径为目标，基础级别提升一级。
    5. **默认**——不在任何列表中的命令为 MODERATE（保守策略）。
    """

    #: 白名单——只读、安全的命令（D-08）。
    SAFE_COMMANDS: set[str] = {
        "ls", "df", "du", "find", "cat", "head", "tail",
        "wc", "grep", "sort", "uniq", "echo", "stat",
    }

    #: 黑名单——危险或破坏性命令（D-08）。
    DANGEROUS_COMMANDS: set[str] = {
        "rm", "dd", "mkfs", "shred", "fdisk",
        "mkfs.ext4", "mkfs.xfs", "mkfs.btrfs", "mkswap",
    }

    #: 始终产生 DANGEROUS 分类的正则模式（D-08）。
    DANGEROUS_PATTERNS: list[str] = [
        r">\s*/dev/",            # 输出重定向到设备
        r"chmod\s+777\s+/",      # 根目录全局可写
        r"chown\s+\S+\s+/",      # 根目录所有权变更
    ]

    #: 系统目录——以这些目录为目标是触发路径升级（D-10）。
    SYSTEM_PATHS: set[str] = {
        "/etc", "/dev", "/sys", "/proc", "/boot",
        "/usr", "/lib", "/lib64", "/bin", "/sbin",
        "/var", "/root", "/opt",
    }

    #: Shell 元字符正则——匹配完整命令字符串。
    _SHELL_META_PATTERN: re.Pattern = re.compile(
        r"[|;&`$]|\$\(|&&|\|\|"
    )

    # ── 公共 API ──────────────────────────────────────────────────────

    def classify(
        self,
        command: str,
        args: list[str],
        working_dir: str,
    ) -> tuple[PermissionLevel, str]:
        """分类命令及其参数。

        Args:
            command: 命令字符串（例如 ``"ls"``、``"rm -rf /etc"``）。
            args: 位置参数列表。
            working_dir: 会话工作目录（例如 ``"/home/user"``）。

        Returns:
            ``(PermissionLevel, reason_string)`` 元组，其中 *reason_string*
            是人类可读（中文）的分类说明。
        """
        from loopai.tools.types import PermissionLevel

        # 第 1 步：提取基础命令名称（第一个空白分隔的 token）。
        cmd_name = command.strip().split()[0] if command.strip() else ""

        # 第 2 步：检测不支持的 shell 元字符（管道、命令替换、逻辑运算）。
        if self._has_shell_metacharacters(command):
            return (
                PermissionLevel.MODERATE,
                "命令包含管道(|)、命令替换($()或``)、逻辑运算符(&&, ||)或分号(;)，"
                "暂不支持，保守处理为 MODERATE",
            )

        # 第 3 步：黑名单检查——这些命令始终是 DANGEROUS。
        if cmd_name in self.DANGEROUS_COMMANDS:
            return (
                PermissionLevel.DANGEROUS,
                f"命中黑名单命令 {cmd_name}",
            )

        # 第 4 步：扫描参数串中是否有危险模式。
        args_str = " ".join(args)
        full_str = f"{command} {args_str}".strip()
        for pattern in self.DANGEROUS_PATTERNS:
            if re.search(pattern, full_str):
                return (
                    PermissionLevel.DANGEROUS,
                    f"命令参数匹配危险模式: {pattern}",
                )

        # 第 5 步：确定基础权限级别。
        if cmd_name in self.SAFE_COMMANDS:
            base_level: PermissionLevel = PermissionLevel.SAFE
        else:
            # 既不在白名单也不在黑名单——保守默认（D-08）。
            base_level = PermissionLevel.MODERATE

        # 第 6 步：路径范围检查——如果目标是系统目录则升级。
        target_paths = self._extract_target_paths(args, working_dir)
        has_system_path = any(
            self._is_path_in_system_scope(p) for p in target_paths
        )

        if has_system_path:
            if base_level == PermissionLevel.SAFE:
                return (
                    PermissionLevel.MODERATE,
                    f"白名单命令 {cmd_name} 但目标路径包含系统目录，升级为 MODERATE",
                )
            if base_level == PermissionLevel.MODERATE:
                return (
                    PermissionLevel.DANGEROUS,
                    f"命令 {cmd_name} 目标路径包含系统目录，升级为 DANGEROUS",
                )

        # 第 7 步：无需升级——返回基础分类。
        if base_level == PermissionLevel.SAFE:
            return (
                PermissionLevel.SAFE,
                f"白名单命令 {cmd_name}，参数安全",
            )
        return (
            PermissionLevel.MODERATE,
            f"命令 {cmd_name} 不在白名单，保守处理为 MODERATE",
        )

    # ── 内部辅助 ─────────────────────────────────────────────────────

    def _has_shell_metacharacters(self, command: str) -> bool:
        """检查命令字符串是否包含不安全的 shell 元字符。

        检测：管道（``|``）、命令替换（``$()``、反引号）、
        逻辑运算符（``&&``、``||``）和分号链式连接（``;``）。

        Args:
            command: 要检查的完整命令字符串。

        Returns:
            如果找到任何元字符或不支持的构造，返回 ``True``。
        """
        return bool(self._SHELL_META_PATTERN.search(command))

    def _extract_target_paths(
        self, args: list[str], working_dir: str
    ) -> list[str]:
        """从参数列表中提取文件系统目标路径。

        绝对路径原样返回。相对路径根据 *working_dir* 解析。
        看起来不像文件路径的参数（没有 ``/`` 前缀、
        没有文件扩展名模式）被跳过。

        Args:
            args: 命令参数列表。
            working_dir: 解析相对路径的基础目录。

        Returns:
            在 *args* 中找到的规范化绝对路径列表。
        """
        paths: list[str] = []
        for arg in args:
            # 跳过标志/选项（以 '-' 开头）
            if arg.startswith("-"):
                continue
            # 跳过 key=value 对（例如 dd 中的 "if=/dev/zero"）
            if "=" in arg:
                parts = arg.split("=", 1)
                # 检查值部分是否包含路径
                val = parts[1]
                if val.startswith("/"):
                    paths.append(os.path.normpath(val))
                continue
            # 绝对路径
            if arg.startswith("/"):
                paths.append(os.path.normpath(arg))
                continue
            # 相对路径——如果看起来像路径，则根据 working_dir 解析
            if "/" in arg or "." in arg:
                resolved = os.path.normpath(
                    os.path.join(working_dir, arg)
                )
                paths.append(resolved)

        return paths

    def _is_path_in_system_scope(self, path: str) -> bool:
        """检查 *path* 是否落在任何系统目录下。

        如果路径是 :attr:`SYSTEM_PATHS` 中任何条目的精确匹配或后代，
        则认为"在系统范围内"。例如：
            - ``/etc/passwd`` 在范围内（``/etc`` 的子路径）
            - ``/dev`` 在范围内（精确匹配）
            - ``/home/user`` 不在范围内

        Args:
            path: 绝对路径字符串（已规范化）。

        Returns:
            如果路径驻留在系统目录内，返回 ``True``。
        """
        # 确保末尾斜杠以保证前缀匹配安全。
        normalized = path.rstrip("/") + "/"
        for sys_path in self.SYSTEM_PATHS:
            sys_prefix = sys_path.rstrip("/") + "/"
            if normalized == sys_prefix or normalized.startswith(sys_prefix):
                return True
        return False
