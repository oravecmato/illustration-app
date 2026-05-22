"""SSE event bus: per-run pub/sub."""

import asyncio
import logging

logger = logging.getLogger(__name__)

TERMINAL_EVENT_TYPES = {"run_completed", "run_failed", "run_cancelled"}


class EventBus:
    """Simple in-process pub/sub event bus for a single run."""

    def __init__(self):
        self._queues: list[asyncio.Queue] = []
        self._snapshot: dict | None = None

    def set_snapshot(self, snapshot: dict) -> None:
        self._snapshot = snapshot

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        if self._snapshot is not None:
            q.put_nowait({"type": "snapshot", "data": self._snapshot})
        self._queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._queues.remove(q)
        except ValueError:
            pass

    async def publish(self, event_type: str, data: dict) -> None:
        event = {"type": event_type, "data": data}
        dead: list[asyncio.Queue] = []
        for q in self._queues:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("SSE queue full, dropping event %s", event_type)
                dead.append(q)
        for q in dead:
            self.unsubscribe(q)
