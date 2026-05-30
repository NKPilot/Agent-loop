"""基于 asyncio.Queue 的事件总线，具备发布/订阅语义。

每个订阅者获得独立的有限队列。发布者将事件扇出到
所有匹配的主题订阅者和通配符 "*" 订阅者。
"""

import asyncio
import json
import warnings
from typing import Any


class EventBus:
    """进程内发布/订阅事件总线，基于 asyncio.Queue。

    支持基于主题的订阅，通配符 "*" 接收所有事件。
    每个订阅者拥有自己的有限队列（maxsize=256）。
    队列满的慢消费者将被丢弃并产生警告。
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[dict[str, Any] | None]]] = {}
        self._history: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()

    async def publish(self, event_type: str, event_data: dict[str, Any]) -> None:
        """将 event_data 扇出到 event_type 和 "*" 通配符的所有订阅者。

        Args:
            event_type: 主题字符串（例如 "step_start"、"llm_token"）。
            event_data: 事件负载字典。必须是 JSON 可序列化的，
                        并且包含与 event_type 匹配的 "event_type" 键。

        Raises:
            TypeError: 如果 event_data 不是 JSON 可序列化的。
            ValueError: 如果 event_data["event_type"] 与 event_type 不匹配。
        """
        # 验证 event_type 一致性
        if event_data.get("event_type") != event_type:
            raise ValueError(
                f"event_data['event_type'] ({event_data.get('event_type')!r}) "
                f"与发布主题 ({event_type!r}) 不匹配"
            )

        # 发布前验证 JSON 可序列化性
        try:
            json.dumps(event_data)
        except (TypeError, ValueError) as exc:
            raise TypeError(
                f"event_data 不是 JSON 可序列化的: {exc}"
            ) from exc

        # 记录到历史，用于重放
        self._history.append(event_data)

        # 扇出到匹配的主题订阅者和通配符订阅者
        targets: list[asyncio.Queue[dict[str, Any] | None]] = []
        targets.extend(self._subscribers.get(event_type, []))
        targets.extend(self._subscribers.get("*", []))

        for queue in targets:
            try:
                queue.put_nowait(event_data)
            except asyncio.QueueFull:
                warnings.warn(
                    f"EventBus: 丢弃慢消费者的事件 {event_type!r}"
                    f"（队列已满，maxsize={queue.maxsize}）",
                    RuntimeWarning,
                    stacklevel=2,
                )

    async def subscribe(self, topic: str) -> asyncio.Queue[dict[str, Any] | None]:
        """为主题注册新订阅者。

        Args:
            topic: 要订阅的 event_type，或 "*" 表示所有事件。

        Returns:
            一个有界的 asyncio.Queue（maxsize=256），用于接收事件。
        """
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=256)
        async with self._lock:
            self._subscribers.setdefault(topic, []).append(queue)
        return queue

    async def unsubscribe(
        self, topic: str, queue: asyncio.Queue[dict[str, Any] | None]
    ) -> None:
        """从主题中移除订阅者队列。

        Args:
            topic: 要取消订阅的主题。
            queue: 之前通过 subscribe() 返回的队列。
        """
        async with self._lock:
            queues = self._subscribers.get(topic, [])
            if queue in queues:
                queues.remove(queue)
            # 清理空的主题列表
            if not queues:
                self._subscribers.pop(topic, None)

    def replay(self, topic: str | None = None) -> list[dict[str, Any]]:
        """返回历史事件，可按主题过滤。

        Args:
            topic: 如果为 None 或 "*"，返回所有事件。
                   否则仅返回匹配 event_type 的事件。

        Returns:
            按发布顺序排列的事件字典列表。
        """
        if topic is None or topic == "*":
            return list(self._history)
        return [e for e in self._history if e.get("event_type") == topic]

    async def shutdown(self) -> None:
        """优雅地关闭所有订阅者。

        向每个订阅者队列发送 None 哨兵，表示不再有
        事件发布。消费者在收到 None 后应退出其
        处理循环。

        使用 put_nowait 避免在满队列上阻塞。如果队列已满，
        哨兵替换最旧的项目，以便消费者仍然可以关闭。
        """
        for queues in self._subscribers.values():
            for queue in queues:
                try:
                    queue.put_nowait(None)
                except asyncio.QueueFull:
                    # 队列已满——排出一个项目，然后插入哨兵
                    try:
                        queue.get_nowait()
                        queue.put_nowait(None)
                    except asyncio.QueueEmpty:
                        pass
