"""Agent 循环守卫模块。

提供三个安全网守卫类，保护 agent 循环免受常见故障模式影响：
- BudgetGuard: 步数预算执行，防止失控会话
- LoopDetector: 循环检测，捕获无限工具调用循环
- MessageValidator: 消息验证，防止格式错误的 API 调用
"""

from __future__ import annotations

import hashlib
import json
from collections import deque


class ValidationError(ValueError):
    """消息验证失败时抛出的异常。

    包含导致验证失败的 tool_call_id，用于调试和错误报告。
    """

    def __init__(self, message: str, tool_call_id: str | None = None) -> None:
        super().__init__(message)
        self.tool_call_id = tool_call_id


class LoopDetector:
    """检测重复工具调用的循环检测器。

    使用滑动窗口记录最近 N 次工具调用，通过确定性哈希签名比较
    来识别重复模式。三级升级机制：
    - 允许 (allow): 正常操作
    - 警告 (warn): 连续 3 次相同调用时注入系统警告
    - 阻止 (block): 连续 5 次相同调用时拒绝执行
    - 强制退出 (force_exit): 阻止后模式仍然持续

    Attributes:
        window_size: 滑动窗口大小，默认 20。
        warn_threshold: 警告阈值，默认 3 次。
        block_threshold: 阻止阈值，默认 5 次。
    """

    def __init__(
        self,
        window_size: int = 20,
        warn_threshold: int = 3,
        block_threshold: int = 5,
    ) -> None:
        self._window: deque[tuple[str, str]] = deque(maxlen=window_size)
        self._warn_threshold = warn_threshold
        self._block_threshold = block_threshold
        self._consecutive_count = 0
        self._last_signature: str | None = None

    @staticmethod
    def _signature(tool_name: str, arguments: dict) -> str:
        """为工具调用生成确定性哈希签名。

        使用 sha256 对规范化的 (tool_name, sorted_args_json) 对进行哈希，
        取前 16 个十六进制字符。相同参数始终产生相同签名。

        Args:
            tool_name: 工具名称。
            arguments: 工具参数字典。

        Returns:
            16 字符的十六进制签名字符串。
        """
        args_json = json.dumps(arguments, sort_keys=True, ensure_ascii=True)
        raw = f"{tool_name}:{args_json}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def check(self, tool_name: str, arguments: dict) -> tuple[bool, str]:
        """检查此工具调用是否构成循环。

        Args:
            tool_name: 被调用的工具名称。
            arguments: 工具参数字典。

        Returns:
            (should_proceed, action) 元组。
            should_proceed 为 True 时允许调用继续，False 时拒绝。
            action 为 "allow"、"warn"、"block" 或 "force_exit" 之一。
        """
        sig = self._signature(tool_name, arguments)

        if sig == self._last_signature:
            self._consecutive_count += 1
        else:
            self._consecutive_count = 1
            self._last_signature = sig

        self._window.append((tool_name, sig))

        if self._consecutive_count > self._block_threshold:
            return (False, "force_exit")
        elif self._consecutive_count >= self._block_threshold:
            return (False, "block")
        elif self._consecutive_count >= self._warn_threshold:
            return (True, "warn")
        return (True, "allow")

    def reset(self) -> None:
        """重置检测器状态。

        清除滑动窗口、连续计数和最后签名。
        当新的工具调用打破了重复模式时使用。
        """
        self._consecutive_count = 0
        self._last_signature = None
        self._window.clear()


class MessageValidator:
    """验证 OpenAI API 消息列表的结构完整性。

    核心规则：每条包含 tool_calls 的 assistant 消息，必须后跟
    对应数量的 tool-role 消息，每条 tool 消息的 tool_call_id
    必须匹配某个之前声明的 tool_call.id。

    这是严格验证——违规会立即抛出 ValidationError，
    而不是尝试自动修复。
    """

    @staticmethod
    def validate(messages: list[dict]) -> None:
        """验证消息列表结构。

        遍历消息列表，追踪待处理的 tool_call_ids。
        每条 assistant 消息添加新的待处理 ID，每条 tool 消息
        消费对应的待处理 ID。遍历完成后，检查是否有未匹配的 ID。

        Args:
            messages: 要验证的消息字典列表。

        Raises:
            ValidationError: 如果发现孤立的 tool_call 或 tool_result，
                             错误消息中包含具体的 tool_call_id。
        """
        pending_ids: set[str] = set()

        for msg in messages:
            role = msg.get("role", "")

            if role == "assistant":
                tool_calls = msg.get("tool_calls")
                if tool_calls:
                    for tc in tool_calls:
                        tc_id = tc.get("id", "")
                        if tc_id:
                            pending_ids.add(tc_id)

            elif role == "tool":
                tc_id = msg.get("tool_call_id", "")
                if tc_id and tc_id in pending_ids:
                    pending_ids.remove(tc_id)
                else:
                    raise ValidationError(
                        f"Orphan tool result: tool_call_id '{tc_id}' "
                        f"has no matching assistant tool_call",
                        tool_call_id=tc_id,
                    )

        # 检查是否有未匹配的 tool_call
        if pending_ids:
            orphan = next(iter(pending_ids))
            raise ValidationError(
                f"Orphan tool call: tool_call_id '{orphan}' "
                f"has no matching tool result",
                tool_call_id=orphan,
            )
