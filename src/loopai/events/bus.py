"""asyncio.Queue-based Event Bus with publish/subscribe semantics.

Each subscriber gets an independent bounded queue. Publishers fan out
events to all matching topic subscribers and wildcard "*" subscribers.
"""

import asyncio
import json
import warnings
from typing import Any


class EventBus:
    """In-process publish/subscribe event bus backed by asyncio.Queue.

    Supports topic-based subscription with a "*" wildcard that receives
    all events. Each subscriber has its own bounded queue (maxsize=256).
    Slow consumers that fill their queue will be dropped with a warning.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[dict[str, Any] | None]]] = {}
        self._history: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()

    async def publish(self, event_type: str, event_data: dict[str, Any]) -> None:
        """Fan out event_data to all subscribers of event_type and wildcard '*'.

        Args:
            event_type: The topic string (e.g. "step_start", "llm_token").
            event_data: The event payload dict. Must be JSON-serializable and
                        contain an "event_type" key matching event_type.

        Raises:
            TypeError: If event_data is not JSON-serializable.
            ValueError: If event_data["event_type"] does not match event_type.
        """
        # Validate event_type consistency
        if event_data.get("event_type") != event_type:
            raise ValueError(
                f"event_data['event_type'] ({event_data.get('event_type')!r}) "
                f"does not match publish topic ({event_type!r})"
            )

        # Validate JSON serializability before publishing
        try:
            json.dumps(event_data)
        except (TypeError, ValueError) as exc:
            raise TypeError(
                f"event_data is not JSON-serializable: {exc}"
            ) from exc

        # Record in history for replay
        self._history.append(event_data)

        # Fan out to matching topic subscribers and wildcard subscribers
        targets: list[asyncio.Queue[dict[str, Any] | None]] = []
        targets.extend(self._subscribers.get(event_type, []))
        targets.extend(self._subscribers.get("*", []))

        for queue in targets:
            try:
                queue.put_nowait(event_data)
            except asyncio.QueueFull:
                warnings.warn(
                    f"EventBus: dropping event {event_type!r} for "
                    f"slow consumer (queue full, maxsize={queue.maxsize})",
                    RuntimeWarning,
                    stacklevel=2,
                )

    async def subscribe(self, topic: str) -> asyncio.Queue[dict[str, Any] | None]:
        """Register a new subscriber for a topic.

        Args:
            topic: The event_type to subscribe to, or "*" for all events.

        Returns:
            A bounded asyncio.Queue (maxsize=256) that will receive events.
        """
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=256)
        async with self._lock:
            self._subscribers.setdefault(topic, []).append(queue)
        return queue

    async def unsubscribe(
        self, topic: str, queue: asyncio.Queue[dict[str, Any] | None]
    ) -> None:
        """Remove a subscriber queue from a topic.

        Args:
            topic: The topic to unsubscribe from.
            queue: The queue previously returned by subscribe().
        """
        async with self._lock:
            queues = self._subscribers.get(topic, [])
            if queue in queues:
                queues.remove(queue)
            # Clean up empty topic lists
            if not queues:
                self._subscribers.pop(topic, None)

    def replay(self, topic: str | None = None) -> list[dict[str, Any]]:
        """Return historical events, optionally filtered by topic.

        Args:
            topic: If None or "*", return all events.
                   Otherwise return only events with matching event_type.

        Returns:
            A list of event dicts in publication order.
        """
        if topic is None or topic == "*":
            return list(self._history)
        return [e for e in self._history if e.get("event_type") == topic]

    async def shutdown(self) -> None:
        """Gracefully shut down all subscribers.

        Sends a None sentinel to each subscriber queue to signal that
        no more events will be published. Consumers should exit their
        processing loop when they receive None.
        """
        for queues in self._subscribers.values():
            for queue in queues:
                await queue.put(None)
