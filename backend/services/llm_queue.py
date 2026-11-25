"""One question at a time through the LLM (PROJECT_SPEC §19.2).

The CPU runs one 8B model; two questions at once would each take twice as long and need twice
the memory. A request joins the queue, waits its turn (the streaming endpoint tells the user
"2 questions ahead of you"), holds the slot for ALL its LLM calls (rewrite + answer), and
releases it. At most `max_waiting` requests may wait; more get 429 QUEUE_FULL.
"""

import asyncio
from collections import deque


class QueueFull(Exception):
    pass


class Ticket:
    def __init__(self, queue: "LLMQueue"):
        self._queue = queue

    @property
    def position(self) -> int:
        """Questions ahead of this one: 0 means it is this ticket's turn."""
        return self._queue.position(self)

    @property
    def ready(self) -> bool:
        return self._queue.is_ready(self)


class LLMQueue:
    def __init__(self, max_waiting: int):
        self.max_waiting = max_waiting
        self._waiting: deque[Ticket] = deque()
        self._active: Ticket | None = None
        self._changed = asyncio.Event()

    @property
    def depth(self) -> int:
        return len(self._waiting)

    @property
    def busy(self) -> bool:
        return self._active is not None

    def join(self) -> Ticket:
        """Take a place in line. Raises QueueFull if `max_waiting` are already waiting."""
        if len(self._waiting) >= self.max_waiting:
            raise QueueFull
        ticket = Ticket(self)
        self._waiting.append(ticket)
        self._notify()
        return ticket

    def position(self, ticket: Ticket) -> int:
        if ticket is self._active:
            return 0
        return list(self._waiting).index(ticket) + (1 if self._active else 0)

    def is_ready(self, ticket: Ticket) -> bool:
        return self._active is None and bool(self._waiting) and self._waiting[0] is ticket

    def start(self, ticket: Ticket) -> None:
        if not self.is_ready(ticket):
            raise RuntimeError("it is not this ticket's turn")
        self._active = self._waiting.popleft()
        self._notify()

    def release(self, ticket: Ticket) -> None:
        """Done (or gone): leave the line or give up the slot. Safe to call more than once."""
        if ticket is self._active:
            self._active = None
        elif ticket in self._waiting:
            self._waiting.remove(ticket)
        self._notify()

    async def changed(self, timeout: float) -> bool:
        """Wait until the line moves. False on timeout (the caller sends a keep-alive)."""
        event = self._changed
        try:
            await asyncio.wait_for(event.wait(), timeout)
            return True
        except TimeoutError:
            return False

    def _notify(self) -> None:
        event, self._changed = self._changed, asyncio.Event()
        event.set()
