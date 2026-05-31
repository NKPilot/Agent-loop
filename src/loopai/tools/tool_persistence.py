""":mod:`loopai.tools.tool_persistence` — 动态工具的三级持久化管理。

ToolPersistenceManager 负责动态工具的读写持久化，支持三级存储：

* **会话级 (session)** — 仅内存，不写文件
* **沙箱级 (sandbox)** — 写入 ``.sandbox/tools/{tool_name}/`` 目录
* **项目级 (project)** — 写入 ``src/loopai/tools/dynamic/`` 目录

注意：持久化调用时机由 DynamicToolCreator 控制——根据 D-06，
确认后立即注册到内存，沙箱级/项目级在首次执行成功后才写文件。
ToolPersistenceManager 只负责文件的读写操作。

决策引用:
    D-06: 确认后立即注册到内存，沙箱级/项目级在首次执行成功后才写文件
    D-07: 沙箱级路径 ``.sandbox/tools/{tool_name}/``，项目级路径 ``src/loopai/tools/dynamic/{tool_name}.py``
    T-08-07: 写入路径限定 .sandbox/tools/ 和 src/loopai/tools/dynamic/
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ToolPersistenceManager:
    """动态工具的三级持久化管理器。

    负责文件系统的读写操作——保存工具代码和元数据，
    启动时扫描已持久化工具，以及删除操作。

    Attributes:
        SANDOX_DIR: 沙箱级持久化目录路径。
        PROJECT_DIR: 项目级持久化目录路径。
    """

    SANDOX_DIR = ".sandbox/tools"
    PROJECT_DIR = "src/loopai/tools/dynamic"

    def __init__(self) -> None:
        """初始化持久化管理器，确保目标目录存在。"""
        os.makedirs(self.SANDOX_DIR, exist_ok=True)
        os.makedirs(self.PROJECT_DIR, exist_ok=True)

    # ── 保存 ────────────────────────────────────────────────────────

    def save(
        self,
        tool_name: str,
        code: str,
        language: str,
        persistence: str,
        meta_dict: dict[str, Any],
    ) -> str:
        """根据持久化级别保存工具。

        Args:
            tool_name: 工具名称（例如 ``"dynamic.a1b2c3d4_disk_check"``）。
            code: 工具的源代码。
            language: 代码语言（``"python"`` 或 ``"bash"``）。
            persistence: 持久化级别，``"session"`` / ``"sandbox"`` / ``"project"``。
            meta_dict: 工具元数据字典，包含 name、description、param_schema 等。

        Returns:
            保存的文件路径。会话级返回空字符串；沙箱级返回代码文件路径；
            项目级返回 .py 文件路径。
        """
        if persistence == "session":
            # 会话级：不写文件，仅在内存中
            return ""

        if persistence == "sandbox":
            return self._save_sandbox(tool_name, code, language, meta_dict)

        if persistence == "project":
            return self._save_project(tool_name, code, language, meta_dict)

        raise ValueError(f"不支持的持久化级别: {persistence}")

    def _save_sandbox(
        self,
        tool_name: str,
        code: str,
        language: str,
        meta_dict: dict[str, Any],
    ) -> str:
        """沙箱级持久化：创建 ``.sandbox/tools/{tool_name}/`` 目录结构。

        目录结构::

            .sandbox/tools/{tool_name}/
                tool.py  (或 tool.sh)
                meta.json

        Returns:
            代码文件的完整路径。
        """
        tool_dir = os.path.join(self.SANDOX_DIR, tool_name)
        os.makedirs(tool_dir, exist_ok=True)

        # 写入代码文件
        ext = ".py" if language == "python" else ".sh"
        code_path = os.path.join(tool_dir, f"tool{ext}")
        with open(code_path, "w", encoding="utf-8") as f:
            f.write(code)

        # 写入 meta.json
        self._write_meta(tool_dir, tool_name, language, persistence="sandbox", extra=meta_dict)

        return code_path

    def _save_project(
        self,
        tool_name: str,
        code: str,
        language: str,
        meta_dict: dict[str, Any],
    ) -> str:
        """项目级持久化：写入 ``src/loopai/tools/dynamic/{tool_name}.py``。

        同时写入 meta.json 在同目录下。
        Bash 工具写入 ``.sh`` 文件。

        Returns:
            代码文件的完整路径。
        """
        ext = ".py" if language == "python" else ".sh"
        code_path = os.path.join(self.PROJECT_DIR, f"{tool_name}{ext}")

        with open(code_path, "w", encoding="utf-8") as f:
            f.write(code)

        # 写入 meta.json
        meta_path = os.path.join(self.PROJECT_DIR, f"{tool_name}.meta.json")
        meta_data = self._build_meta_dict(
            tool_name, language, persistence="project", extra=meta_dict
        )
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta_data, f, ensure_ascii=False, indent=2)

        return code_path

    # ── 加载 ────────────────────────────────────────────────────────

    def load_sandbox_tools(self) -> list[dict[str, Any]]:
        """扫描 ``.sandbox/tools/`` 目录，返回所有沙箱级工具。

        遍历 ``.sandbox/tools/*/`` 子目录，读取 ``tool.py`` / ``tool.sh``
        和 ``meta.json``。

        Returns:
            工具数据列表，每个元素为::

                {
                    "tool_name": str,
                    "code": str,
                    "language": "python" | "bash",
                    "meta": dict,       # meta.json 内容
                    "persistence": "sandbox",
                }
        """
        tools: list[dict[str, Any]] = []

        if not os.path.isdir(self.SANDOX_DIR):
            return tools

        for entry in sorted(os.listdir(self.SANDOX_DIR)):
            entry_path = os.path.join(self.SANDOX_DIR, entry)
            if not os.path.isdir(entry_path):
                continue

            tool_name = entry
            code, language = self._read_tool_file(entry_path)

            if code is None:
                continue  # 没有找到代码文件，跳过

            meta = {}
            meta_path = os.path.join(entry_path, "meta.json")
            if os.path.isfile(meta_path):
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                except (json.JSONDecodeError, OSError):
                    pass  # meta.json 损坏，使用空字典

            tools.append({
                "tool_name": tool_name,
                "code": code,
                "language": language,
                "meta": meta,
                "persistence": "sandbox",
            })

        return tools

    def load_project_tools(self) -> list[dict[str, Any]]:
        """扫描 ``src/loopai/tools/dynamic/`` 目录，返回所有项目级工具。

        遍历 ``.py`` 和 ``.sh`` 文件，读取文件内容和对应的 ``.meta.json``。

        Returns:
            工具数据列表，每个元素为::

                {
                    "tool_name": str,
                    "code": str,
                    "language": "python" | "bash",
                    "meta": dict,       # meta.json 内容
                    "persistence": "project",
                }
        """
        tools: list[dict[str, Any]] = []

        if not os.path.isdir(self.PROJECT_DIR):
            return tools

        for entry in sorted(os.listdir(self.PROJECT_DIR)):
            entry_path = os.path.join(self.PROJECT_DIR, entry)

            # 跳过 meta.json 和非代码文件
            if entry.endswith(".meta.json"):
                continue
            if not (entry.endswith(".py") or entry.endswith(".sh")):
                continue
            # 跳过 .gitkeep
            if entry == ".gitkeep":
                continue

            # 提取工具名（去掉扩展名）
            tool_name = entry.rsplit(".", 1)[0] if "." in entry else entry

            language = "python" if entry.endswith(".py") else "bash"

            code = None
            try:
                with open(entry_path, "r", encoding="utf-8") as f:
                    code = f.read()
            except OSError:
                continue  # 读取失败，跳过

            if code is None:
                continue

            meta = {}
            meta_path = os.path.join(self.PROJECT_DIR, f"{tool_name}.meta.json")
            if os.path.isfile(meta_path):
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                except (json.JSONDecodeError, OSError):
                    pass

            tools.append({
                "tool_name": tool_name,
                "code": code,
                "language": language,
                "meta": meta,
                "persistence": "project",
            })

        return tools

    # ── 删除 ────────────────────────────────────────────────────────

    def delete(self, tool_name: str, persistence: str) -> None:
        """删除工具文件。

        Args:
            tool_name: 工具名称。
            persistence: 持久化级别（``"session"`` / ``"sandbox"`` / ``"project"``）。

        Raises:
            ValueError: 如果持久化级别不支持。
        """
        if persistence == "session":
            # 会话级：内存中，无需删除文件
            return

        if persistence == "sandbox":
            tool_dir = os.path.join(self.SANDOX_DIR, tool_name)
            if os.path.isdir(tool_dir):
                shutil.rmtree(tool_dir)
            return

        if persistence == "project":
            code_path = os.path.join(self.PROJECT_DIR, f"{tool_name}.py")
            sh_path = os.path.join(self.PROJECT_DIR, f"{tool_name}.sh")
            meta_path = os.path.join(self.PROJECT_DIR, f"{tool_name}.meta.json")

            for path in (code_path, sh_path, meta_path):
                if os.path.isfile(path):
                    os.remove(path)
            return

        raise ValueError(f"不支持的持久化级别: {persistence}")

    # ── 内部辅助 ────────────────────────────────────────────────────

    def _write_meta(
        self,
        tool_dir: str,
        tool_name: str,
        language: str,
        persistence: str,
        extra: dict[str, Any],
    ) -> None:
        """写入 meta.json 到指定目录。"""
        meta_path = os.path.join(tool_dir, "meta.json")
        meta_data = self._build_meta_dict(
            tool_name, language, persistence, extra
        )
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta_data, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _build_meta_dict(
        tool_name: str,
        language: str,
        persistence: str,
        extra: dict[str, Any],
    ) -> dict[str, Any]:
        """构建标准化的 meta.json 字典。"""
        return {
            "name": extra.get("name", tool_name),
            "description": extra.get("description", ""),
            "language": language,
            "param_schema": extra.get("param_schema", {}),
            "created_at": extra.get(
                "created_at", datetime.now(timezone.utc).isoformat()
            ),
            "persistence": persistence,
        }

    @staticmethod
    def _read_tool_file(tool_dir: str) -> tuple[str | None, str]:
        """读取工具目录中的代码文件。

        优先读取 tool.py，其次 tool.sh。

        Returns:
            (code, language) 元组。若未找到代码文件，code 为 None。
        """
        for ext, language in [(".py", "python"), (".sh", "bash")]:
            code_path = os.path.join(tool_dir, f"tool{ext}")
            if os.path.isfile(code_path):
                try:
                    with open(code_path, "r", encoding="utf-8") as f:
                        return f.read(), language
                except OSError:
                    continue
        return None, "python"
