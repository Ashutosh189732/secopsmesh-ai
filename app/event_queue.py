"""In-process stand-in for the Redis event queue described in the plan.

Local dev has no Redis, so this offers the same push/pop shape (per-named-list
FIFO) backed by an in-memory dict of queue.Queue objects. Day 3's orchestrator
consumes this via `pop()`; swapping to real Redis later means replacing this
module's internals with redis-py calls — callers don't change.
"""

import queue as _stdlib_queue
from collections import defaultdict

_queues: dict[str, _stdlib_queue.Queue] = defaultdict(_stdlib_queue.Queue)


def push(list_name: str, item: dict) -> None:
    _queues[list_name].put(item)


def pop(list_name: str, block: bool = False, timeout: float | None = None) -> dict | None:
    try:
        return _queues[list_name].get(block=block, timeout=timeout)
    except _stdlib_queue.Empty:
        return None


def depth(list_name: str) -> int:
    return _queues[list_name].qsize()
