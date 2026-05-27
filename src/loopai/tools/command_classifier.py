""":mod:`loopai.tools.command_classifier` — Command whitelist/blacklist classifier.

Classifies shell commands into :class:`PermissionLevel` tiers (SAFE, MODERATE,
DANGEROUS) based on command identity, argument patterns, and target paths.
Implements path-aware escalation: a SAFE command targeting a system directory
(e.g. ``ls /etc``) is upgraded to MODERATE; a MODERATE command targeting a
system directory is upgraded to DANGEROUS.

Decision references:
    D-08: Whitelist-based + blacklist upgrade classification
    D-10: Path-aware permission escalation (SAFE -> MODERATE -> DANGEROUS)

Usage::

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
    """Classify shell commands by permission level (SAFE/MODERATE/DANGEROUS).

    Classification follows a deterministic priority chain:

    1. **Shell metacharacter detection** — Pipes, command substitution, and
       logic operators are not supported; the entire command is conservatively
       classified as MODERATE.
    2. **Blacklist check** — Commands matching :attr:`DANGEROUS_COMMANDS` are
       immediately DANGEROUS regardless of arguments.
    3. **Pattern scan** — Argument strings are checked against
       :attr:`DANGEROUS_PATTERNS` (e.g. ``chmod 777 /``, ``> /dev/``).
    4. **Path scope escalation** — If any argument targets a system path in
       :attr:`SYSTEM_PATHS`, the base level is upgraded one tier.
    5. **Default** — Commands not in either list are MODERATE (conservative).
    """

    #: Whitelist — read-only, safe commands (D-08).
    SAFE_COMMANDS: set[str] = {
        "ls", "df", "du", "find", "cat", "head", "tail",
        "wc", "grep", "sort", "uniq", "echo", "stat",
    }

    #: Blacklist — dangerous or destructive commands (D-08).
    DANGEROUS_COMMANDS: set[str] = {
        "rm", "dd", "mkfs", "shred", "fdisk",
        "mkfs.ext4", "mkfs.xfs", "mkfs.btrfs", "mkswap",
    }

    #: Regex patterns that always produce a DANGEROUS classification (D-08).
    DANGEROUS_PATTERNS: list[str] = [
        r">\s*/dev/",            # output redirection to device
        r"chmod\s+777\s+/",      # world-writable root
        r"chown\s+\S+\s+/",      # ownership change on root
    ]

    #: System directories — targeting any of these triggers path escalation (D-10).
    SYSTEM_PATHS: set[str] = {
        "/etc", "/dev", "/sys", "/proc", "/boot",
        "/usr", "/lib", "/lib64", "/bin", "/sbin",
        "/var", "/root", "/opt",
    }

    #: Shell metacharacter regex — matched against the full command string.
    _SHELL_META_PATTERN: re.Pattern = re.compile(
        r"[|;&`$]|\$\(|&&|\|\|"
    )

    # ── Public API ──────────────────────────────────────────────────────

    def classify(
        self,
        command: str,
        args: list[str],
        working_dir: str,
    ) -> tuple[PermissionLevel, str]:
        """Classify a command and its arguments.

        Args:
            command: The command string (e.g. ``"ls"``, ``"rm -rf /etc"``).
            args: Positional argument list.
            working_dir: The session working directory (e.g. ``"/home/user"``).

        Returns:
            A tuple of ``(PermissionLevel, reason_string)`` where *reason_string*
            is a human-readable (Chinese) explanation of the classification.
        """
        from loopai.tools.types import PermissionLevel

        # Step 1: Extract the base command name (first whitespace-delimited token).
        cmd_name = command.strip().split()[0] if command.strip() else ""

        # Step 2: Detect unsupported shell metacharacters (pipe, cmd sub, logic).
        if self._has_shell_metacharacters(command):
            return (
                PermissionLevel.MODERATE,
                "命令包含管道(|)、命令替换($()或``)、逻辑运算符(&&, ||)或分号(;)，"
                "暂不支持，保守处理为 MODERATE",
            )

        # Step 3: Blacklist check — these commands are always DANGEROUS.
        if cmd_name in self.DANGEROUS_COMMANDS:
            return (
                PermissionLevel.DANGEROUS,
                f"命中黑名单命令 {cmd_name}",
            )

        # Step 4: Scan argument string for dangerous patterns.
        args_str = " ".join(args)
        full_str = f"{command} {args_str}".strip()
        for pattern in self.DANGEROUS_PATTERNS:
            if re.search(pattern, full_str):
                return (
                    PermissionLevel.DANGEROUS,
                    f"命令参数匹配危险模式: {pattern}",
                )

        # Step 5: Determine the base permission level.
        if cmd_name in self.SAFE_COMMANDS:
            base_level: PermissionLevel = PermissionLevel.SAFE
        else:
            # Not in whitelist, not in blacklist — conservative default (D-08).
            base_level = PermissionLevel.MODERATE

        # Step 6: Path scope check — escalate if targeting system directories.
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

        # Step 7: No escalation needed — return base classification.
        if base_level == PermissionLevel.SAFE:
            return (
                PermissionLevel.SAFE,
                f"白名单命令 {cmd_name}，参数安全",
            )
        return (
            PermissionLevel.MODERATE,
            f"命令 {cmd_name} 不在白名单，保守处理为 MODERATE",
        )

    # ── Internal helpers ─────────────────────────────────────────────────

    def _has_shell_metacharacters(self, command: str) -> bool:
        """Check if the command string contains unsafe shell metacharacters.

        Detects: pipes (``|``), command substitution (``$()``, backticks),
        logic operators (``&&``, ``||``), and semicolon chaining (``;``).

        Args:
            command: The full command string to inspect.

        Returns:
            ``True`` if any metacharacter or unsupported construct is found.
        """
        return bool(self._SHELL_META_PATTERN.search(command))

    def _extract_target_paths(
        self, args: list[str], working_dir: str
    ) -> list[str]:
        """Extract file-system target paths from the argument list.

        Absolute paths are returned as-is. Relative paths are resolved against
        *working_dir*. Arguments that do not look like file paths (no ``/``
        prefix, no file extension pattern) are skipped.

        Args:
            args: Command argument list.
            working_dir: Base directory for resolving relative paths.

        Returns:
            List of normalized absolute paths found in *args*.
        """
        paths: list[str] = []
        for arg in args:
            # Skip flags/options (start with '-')
            if arg.startswith("-"):
                continue
            # Skip key=value pairs (e.g. "if=/dev/zero" from dd)
            if "=" in arg:
                parts = arg.split("=", 1)
                # Check the value part for paths
                val = parts[1]
                if val.startswith("/"):
                    paths.append(os.path.normpath(val))
                continue
            # Absolute path
            if arg.startswith("/"):
                paths.append(os.path.normpath(arg))
                continue
            # Relative path — resolve against working_dir if it looks like a path
            if "/" in arg or "." in arg:
                resolved = os.path.normpath(
                    os.path.join(working_dir, arg)
                )
                paths.append(resolved)

        return paths

    def _is_path_in_system_scope(self, path: str) -> bool:
        """Check whether *path* falls under any system directory.

        A path is "in system scope" if it equals or is a descendant of any
        entry in :attr:`SYSTEM_PATHS`.  For example:
            - ``/etc/passwd`` is in scope (child of ``/etc``)
            - ``/dev`` is in scope (exact match)
            - ``/home/user`` is NOT in scope

        Args:
            path: An absolute path string (already normalized).

        Returns:
            ``True`` if the path resides within a system directory.
        """
        # Ensure trailing slash for prefix matching safety.
        normalized = path.rstrip("/") + "/"
        for sys_path in self.SYSTEM_PATHS:
            sys_prefix = sys_path.rstrip("/") + "/"
            if normalized == sys_prefix or normalized.startswith(sys_prefix):
                return True
        return False
