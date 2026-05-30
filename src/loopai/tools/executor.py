""":mod:`loopai.tools.executor` — 带重试和错误处理的工具执行管道。

:class:`ToolExecutor` 是工具调用的运行时引擎。它实现了完整的执行管道：

    1. 从 :class:`ToolRegistry` 查找工具元数据
    2. 根据工具的 Pydantic 模型验证参数（D-02, D-05）
    3. 使用可配置超时执行工具（D-07）
    4. 通过 :func:`~loopai.tools.errors.classify_error` 分类异常
    5. 对瞬态错误使用指数退避重试（D-12, D-13）
    6. 将结果包装为标准的 :class:`ToolResult`

同步函数通过 :func:`asyncio.to_thread` 在默认线程池中执行（D-06）。
异步函数直接 await。

决策引用:
    D-02: 基于 Pydantic 的参数验证
    D-05: 标准化 ToolResult 包装
    D-06: 同步/异步双执行策略
    D-07: 使用 ``asyncio.wait_for`` 的每工具超时
    D-11: 异常到 ErrorCategory 映射
    D-12: 可配置重试，指数退避 + 抖动
    D-13: 仅 TRANSIENT 错误触发自动重试
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from loopai.tools.errors import classify_error
from loopai.tools.registry import ToolRegistry
from loopai.tools.types import (
    ErrorCategory,
    RecoveryConfig,
    RecoveryLayer,
    ToolMetadata,
    ToolResult,
)

# 工具输出的溢出阈值（80K 字符）
_OVERFLOW_THRESHOLD_CHARS = 80 * 1024
# 溢出文件目录
_OVERFLOW_DIR = ".sandbox/overflow"


class ToolExecutor:
    """通过验证的、带超时控制的管道执行工具调用。

    Args:
        registry: 用于查找工具的 :class:`ToolRegistry`。

    Example::

        registry = ToolRegistry()
        registry.register(my_tool)
        executor = ToolExecutor(registry)

        result = await executor.execute("my_tool", {"arg1": "value"})
        if result.is_error:
            print(f"Tool failed: {result.error_message}")
    """

    def __init__(self, registry: ToolRegistry,
                 recovery_config: RecoveryConfig | None = None) -> None:
        self._registry = registry
        self._recovery_cfg = recovery_config or RecoveryConfig()

    # ── 公共 API ──────────────────────────────────────────────────

    async def execute(self, tool_name: str, args: dict,
                      session_id: str = "", tool_call_id: str = "") -> ToolResult:
        """按名称执行给定参数的工具。

        这是主入口点。处理元数据查找、参数验证、执行和结果包装。
        重试决策委托给 :meth:`_execute_with_retry`。

        Args:
            tool_name: 完整工具名称（例如 ``"bash.df"``）。
            args: 来自 LLM 的原始参数字典（非信任边界）。
            session_id: 用于溢出文件命名的会话标识符。
            tool_call_id: 用于溢出文件命名的工具调用标识符。

        Returns:
            包含成功/错误状态和计时信息的 :class:`ToolResult`。

        Raises:
            KeyError: 如果在注册表中未找到 *tool_name*。
        """
        metadata = self._registry.get(tool_name)
        if metadata is None:
            return ToolResult.error(
                error_msg=f"Tool '{tool_name}' not found in registry",
                duration_ms=0.0,
            )

        # 第 1 步：通过工具的 Pydantic 模型验证参数（D-02）
        valid_model = metadata.validation_model
        if valid_model is not None:
            try:
                validated = valid_model(**args)
                validated_args = validated.model_dump()
            except ValidationError as exc:
                return ToolResult.error(
                    error_msg=f"Argument validation failed: {exc}",
                    duration_ms=0.0,
                )
        else:
            validated_args = dict(args)

        # 第 2 步：带恢复策略执行（D-12, D-13, D-04）
        return await self._execute_with_recovery(metadata, validated_args,
                                                  session_id, tool_call_id)

    # ── 重试循环 ──────────────────────────────────────────────────

    async def _execute_with_retry(
        self, metadata: ToolMetadata, validated_args: dict,
        session_id: str = "", tool_call_id: str = "",
    ) -> ToolResult:
        """在瞬态错误上带重试执行工具。

        Args:
            metadata: 工具元数据（包含重试配置）。
            validated_args: 已通过 Pydantic 验证的参数。
            session_id: 用于溢出文件命名的会话标识符。
            tool_call_id: 用于溢出文件命名的工具调用标识符。

        Returns:
            最终结果的 :class:`ToolResult`。
        """
        last_result: ToolResult | None = None
        retry_config = metadata.retry

        for attempt in range(retry_config.max_attempts):
            try:
                result = await self._execute_once(metadata, validated_args,
                                                   session_id, tool_call_id)
                # 成功——立即返回
                return result
            except Exception as exc:
                category = classify_error(exc)

                if category == ErrorCategory.FATAL:
                    # D-13: 致命错误直接重新抛出以终止会话
                    raise

                if category == ErrorCategory.TRANSIENT:
                    # D-13: 瞬态错误——带退避重试
                    msg = (
                        f"Transient error "
                        f"(attempt {attempt + 1}/{retry_config.max_attempts}): {exc}"
                    )
                    last_result = ToolResult.error(
                        error_msg=msg,
                        duration_ms=0.0,
                    )
                    # 最后一次尝试不睡眠
                    if attempt < retry_config.max_attempts - 1:
                        delay = retry_config.compute_delay(attempt)
                        await asyncio.sleep(delay)
                    continue

                # TOOL_EXECUTION 或 GUARD_VIOLATION——不重试
                return ToolResult.error(
                    error_msg=f"{category.value}: {exc}",
                    duration_ms=0.0,
                )

        # 所有重试尝试已耗尽
        if last_result is not None:
            return last_result
        return ToolResult.error(
            error_msg="Retry attempts exhausted with no result",
            duration_ms=0.0,
        )

    # ── 4 层恢复管道 ─────────────────────────────────────────────

    async def _execute_with_recovery(
        self, metadata: ToolMetadata, validated_args: dict,
        session_id: str = "", tool_call_id: str = "",
    ) -> ToolResult:
        """以 4 层恢复升级策略执行工具（D-03, D-04）。

        第 1 层——外观修复：修复参数中的 JSON 格式错误。
        第 2 层——上下文内：在 FSM 级别处理（结构化错误 → LLM 重新调用）。
        第 3 层——退避：来自 RetryConfig 的现有指数退避 + 抖动。
        第 4 层——人工升级：发布事件，返回错误结果。
        """
        # ── 第 1 层：外观修复 ────────────────────────────────────
        for attempt in range(self._recovery_cfg.cosmetic_max_attempts):
            try:
                result = await self._execute_once(metadata, validated_args,
                                                   session_id, tool_call_id)
                return result  # 成功 → 立即返回
            except (json.JSONDecodeError, TypeError) as exc:
                # 在首次尝试时尝试外观修复
                if attempt == 0:
                    repaired = self._cosmetic_repair(validated_args, exc)
                    if repaired is not None:
                        validated_args = repaired
                        continue
                # 无法修复 → 升级
                return ToolResult.error(
                    error_msg=f"Layer 1 (cosmetic) exhausted: {exc}",
                    duration_ms=0.0,
                )
            except (TimeoutError, ConnectionError, asyncio.TimeoutError):
                # 网络/超时问题 → 非外观问题，落入第 3 层
                break
            except Exception as exc:
                # 其他异常 → 检查类别
                cat = classify_error(exc)
                if cat == ErrorCategory.TRANSIENT:
                    break  # 落入第 3 层
                # TOOL_EXECUTION 或 GUARD_VIOLATION → 返回错误
                return ToolResult.error(
                    error_msg=f"{cat.value}: {exc}",
                    duration_ms=0.0,
                )

        # ── 第 3 层：完整重试 + 退避（现有逻辑）──────────────
        last_result: ToolResult | None = None
        retry_config = metadata.retry

        for attempt in range(retry_config.max_attempts):
            try:
                result = await self._execute_once(metadata, validated_args,
                                                   session_id, tool_call_id)
                return result  # 成功
            except Exception as exc:
                category = classify_error(exc)

                if category == ErrorCategory.FATAL:
                    raise  # 致命 → 终止会话

                if category == ErrorCategory.TRANSIENT:
                    msg = (f"Transient error "
                           f"(attempt {attempt + 1}/{retry_config.max_attempts}): {exc}")
                    last_result = ToolResult.error(error_msg=msg, duration_ms=0.0)
                    if attempt < retry_config.max_attempts - 1:
                        delay = retry_config.compute_delay(attempt)
                        await asyncio.sleep(delay)
                    continue

                # TOOL_EXECUTION 或 GUARD_VIOLATION → 不重试
                return ToolResult.error(
                    error_msg=f"{category.value}: {exc}",
                    duration_ms=0.0,
                )

        # 第 3 层耗尽或 last_result 从瞬态重试中设置
        if last_result is not None:
            result_for_layer4 = last_result
        else:
            result_for_layer4 = ToolResult.error(
                error_msg="Layer 3 (backoff) exhausted with no result",
                duration_ms=0.0,
            )

        # ── 第 4 层：人工升级 ───────────────────────────────────
        return result_for_layer4  # FSM 层处理升级

    # ── 外观修复 ─────────────────────────────────────────────────

    def _cosmetic_repair(
        self, validated_args: dict, exception: Exception
    ) -> dict | None:
        """根据异常类型尝试对工具参数进行外观修复。

        当前修复：
        - TypeError: 检查常见类型不匹配并强制转换

        Args:
            validated_args: 当前参数字典。
            exception: 被抛出的异常。

        Returns:
            修复后的参数字典，或 None 表示无法修复。
        """
        # TypeError: 尝试数字字符串 → 数字强制转换
        if isinstance(exception, TypeError):
            repaired = dict(validated_args)
            for key, value in repaired.items():
                if isinstance(value, str):
                    # 尝试 int 转换
                    try:
                        repaired[key] = int(value)
                        continue
                    except (ValueError, TypeError):
                        pass
                    # 尝试 float 转换
                    try:
                        repaired[key] = float(value)
                        continue
                    except (ValueError, TypeError):
                        pass
            if repaired != validated_args:
                return repaired

        return None

    # ── 单次执行尝试 ────────────────────────────────────────────

    async def _execute_once(
        self, metadata: ToolMetadata, validated_args: dict,
        session_id: str = "", tool_call_id: str = "",
    ) -> ToolResult:
        """使用超时和结果包装执行一次工具函数。

        Args:
            metadata: 工具元数据（包含 timeout、func_ref）。
            validated_args: 已验证的参数字典。
            session_id: 用于溢出文件命名的会话标识符。
            tool_call_id: 用于溢出文件命名的工具调用标识符。

        Returns:
            此次单次尝试的 :class:`ToolResult`。

        Raises:
            Exception: 工具函数抛出的任何异常（由
                :meth:`_execute_with_retry` 中的重试循环捕获）。
        """
        func = metadata.func_ref
        if func is None:
            return ToolResult.error(
                error_msg="Tool has no callable reference",
                duration_ms=0.0,
            )

        timeout = metadata.timeout
        start = time.monotonic()

        # 确定执行策略：异步 → await，同步 → 线程池（D-06）
        if inspect.iscoroutinefunction(func):
            coro = func(**validated_args)
        else:
            coro = asyncio.to_thread(func, **validated_args)

        # 应用超时（D-07）
        try:
            raw_result = await asyncio.wait_for(coro, timeout=timeout)
        except TimeoutError:
            # asyncio.TimeoutError 是 TRANSIENT 类别——重新抛出
            # 以便重试循环可以处理
            duration_ms = (time.monotonic() - start) * 1000
            raise TimeoutError(
                f"Tool '{metadata.name}' timed out after {timeout}s"
            )

        duration_ms = (time.monotonic() - start) * 1000

        # 为大型字符串结果（> 80K 字符）写入溢出文件
        truncated = False
        overflow_file: str | None = None
        data: Any = raw_result

        if isinstance(data, str) and len(data) > _OVERFLOW_THRESHOLD_CHARS:
            overflow_file = self._write_overflow_file(
                metadata.name, session_id, tool_call_id, data
            )
            # data 保持完整——FSM._handle_act 负责在注入上下文时替换为引用

        return ToolResult.success(
            data=data,
            duration_ms=duration_ms,
            truncated=truncated,
            overflow_file=overflow_file,
        )

    # ── 溢出文件写入 ─────────────────────────────────────────────

    def _write_overflow_file(
        self, tool_name: str, session_id: str, tool_call_id: str, content: str
    ) -> str:
        """当工具输出超过阈值时将其写入溢出文件。

        文件路径格式：``.sandbox/overflow/{session_id}_{tool_call_id}_{timestamp}.txt``
        如果 ``session_id`` 为空，文件路径回退为 ``{timestamp}.txt``。

        Args:
            tool_name: 工具名称（当前未在路径中使用）。
            session_id: 文件名的会话标识符。
            tool_call_id: 文件名的工具调用标识符。
            content: 要写入的完整工具输出字符串。

        Returns:
            已写入溢出文件的绝对路径字符串。
        """
        os.makedirs(_OVERFLOW_DIR, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        if session_id:
            filename = f"{session_id}_{tool_call_id}_{timestamp}.txt"
        else:
            filename = f"{timestamp}.txt"

        file_path = str(Path(_OVERFLOW_DIR) / filename)
        Path(file_path).write_text(content, encoding="utf-8")
        return file_path
