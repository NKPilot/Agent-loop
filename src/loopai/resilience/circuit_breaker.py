"""每工具独立、基于滑动窗口失败率的熔断器。

实现标准 closed → open → half-open → closed 状态机（D-05）。
状态转换发布到 EventBus（D-06），使仪表盘和 JSONL 日志器可观察。
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from loopai.events.bus import EventBus


class CircuitState(str, Enum):
    """熔断器状态。"""

    CLOSED = "closed"  # 正常操作——允许调用
    OPEN = "open"  # 已触发——阻止调用
    HALF_OPEN = "half_open"  # 探测中——允许一次试探调用


class CircuitBreaker:
    """由滑动窗口失败率驱动的每工具独立熔断器。

    每个工具有自己独立的滑动窗口和状态。
    经过 cooldown_seconds 后，允许一次探测调用（half-open）。
    成功则关闭电路；失败则重新打开。

    半开探测的线程安全通过 ``asyncio.Lock`` 和 ``_probing``
    集合保证（陷阱 1）。
    """

    def __init__(
        self,
        window_size: int = 10,
        failure_threshold: float = 0.5,
        cooldown_seconds: float = 30.0,
    ) -> None:
        self.window_size = window_size
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds

        # 每工具独立状态
        self._window: dict[str, deque[bool]] = {}  # tool_name -> [success/fail]
        self._state: dict[str, CircuitState] = {}  # tool_name -> state
        self._opened_at: dict[str, float] = {}  # tool_name -> monotonic 时间戳
        self._probing: set[str] = set()  # 当前处于半开探测中的工具
        self._lock: asyncio.Lock = asyncio.Lock()

    # ── 公共 API ──────────────────────────────────────────────────

    def check(self, tool_name: str) -> tuple[bool, CircuitState]:
        """检查 *tool_name* 是否允许执行。

        Returns:
            ``(allowed, current_state)``。
            - ``(True, CLOSED)``——正常操作。
            - ``(True, HALF_OPEN)``——试探调用允许。
            - ``(False, OPEN)``——阻止（冷却未到期或
              已有其他探测进行中）。
        """
        # 半开互斥（陷阱 1）
        if tool_name in self._probing:
            return (False, CircuitState.OPEN)

        state = self._state.get(tool_name, CircuitState.CLOSED)

        if state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._opened_at.get(tool_name, 0.0)
            if elapsed >= self.cooldown_seconds:
                self._state[tool_name] = CircuitState.HALF_OPEN
                self._probing.add(tool_name)
                return (True, CircuitState.HALF_OPEN)
            return (False, CircuitState.OPEN)

        return (True, state)

    async def record(
        self,
        tool_name: str,
        success: bool,
        bus: EventBus | None = None,
        *,
        session_id: str = "",
    ) -> None:
        """记录工具执行结果并更新状态。

        Args:
            tool_name: 被执行的工具。
            success: 执行成功则为 ``True``。
            bus: 可选的 EventBus，用于发布状态变更事件。
            session_id: 事件负载的会话 ID。
        """
        # 为新工具初始化滑动窗口
        if tool_name not in self._window:
            self._window[tool_name] = deque(maxlen=self.window_size)
            self._state.setdefault(tool_name, CircuitState.CLOSED)

        self._window[tool_name].append(success)

        # 从探测集合中移除（探测已完成）
        self._probing.discard(tool_name)

        # 计算失败率
        window = self._window[tool_name]
        failures = sum(1 for r in window if not r)
        rate = failures / len(window) if window else 0.0

        state = self._state.get(tool_name, CircuitState.CLOSED)

        if state == CircuitState.HALF_OPEN:
            async with self._lock:
                if success:
                    previous = CircuitState.HALF_OPEN.value
                    self._state[tool_name] = CircuitState.CLOSED
                    if bus is not None:
                        await bus.publish(
                            "circuit_closed",
                            {
                                "event_type": "circuit_closed",
                                "session_id": session_id,
                                "tool_name": tool_name,
                                "previous_state": previous,
                                "new_state": CircuitState.CLOSED.value,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            },
                        )
                else:
                    previous = CircuitState.HALF_OPEN.value
                    self._state[tool_name] = CircuitState.OPEN
                    self._opened_at[tool_name] = time.monotonic()
                    if bus is not None:
                        await bus.publish(
                            "circuit_opened",
                            {
                                "event_type": "circuit_opened",
                                "session_id": session_id,
                                "tool_name": tool_name,
                                "failure_rate": rate,
                                "window_size": self.window_size,
                                "previous_state": previous,
                                "new_state": CircuitState.OPEN.value,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            },
                        )

        elif state == CircuitState.CLOSED and rate > self.failure_threshold:
            previous = CircuitState.CLOSED.value
            self._state[tool_name] = CircuitState.OPEN
            self._opened_at[tool_name] = time.monotonic()
            if bus is not None:
                await bus.publish(
                    "circuit_opened",
                    {
                        "event_type": "circuit_opened",
                        "session_id": session_id,
                        "tool_name": tool_name,
                        "failure_rate": rate,
                        "window_size": self.window_size,
                        "previous_state": previous,
                        "new_state": CircuitState.OPEN.value,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )

    async def record_with_session(
        self,
        tool_name: str,
        success: bool,
        session_id: str,
        bus: EventBus | None = None,
    ) -> None:
        """便捷包装，将 *session_id* 传递给 ``record``。"""
        await self.record(tool_name, success, bus, session_id=session_id)

    def get_open_tools(self) -> set[str]:
        """返回当前处于 OPEN 状态的工具名称集合。

        由 FSM 使用，用于过滤向 LLM 展示的工具模式。
        """
        return {
            name
            for name, state in self._state.items()
            if state == CircuitState.OPEN
        }

    def get_tool_state(self, tool_name: str) -> CircuitState:
        """返回 *tool_name* 的当前电路状态。

        如果工具没有记录状态，默认为 ``CLOSED``。
        """
        return self._state.get(tool_name, CircuitState.CLOSED)

    def reset_tool(self, tool_name: str) -> None:
        """重置 *tool_name* 的所有状态（窗口、状态、计时器、探测）。"""
        self._window.pop(tool_name, None)
        self._state.pop(tool_name, None)
        self._opened_at.pop(tool_name, None)
        self._probing.discard(tool_name)
