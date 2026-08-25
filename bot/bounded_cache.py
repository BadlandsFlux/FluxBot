"""A dict that evicts its least-recently-set entry once it exceeds a
fixed size cap.

Several caches across this bot are keyed by "every (guild, user) pair
that's ever done X" (run a permission-gated command, touched voice,
etc.), with no natural cap, entries just accumulate for as long as the
process stays up. For a bot meant to run for weeks or months without a
restart, that's the wrong shape: slow, but genuinely unbounded growth.

This isn't a TTL cache, it's "most recent N distinct keys", the exact
same idea bot/message_cache.py already uses for message content,
factored out here so the handful of similar caches don't each
reimplement the same eviction loop.

Safe to use anywhere a cache miss just means "recompute/refetch this
one thing", which is true of every current use: an evicted permission
cache entry just gets refetched from Fluxer on next use, an evicted
voice-state entry just gets re-observed on the next event. None of
these caches have a use case where losing an entry causes incorrect
behavior, only a bit of avoidable extra work.
"""
from __future__ import annotations

from collections import OrderedDict
from typing import Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")


class BoundedDict(OrderedDict, Generic[K, V]):
    def __init__(self, *args, max_size: int, **kwargs):
        self.max_size = max_size
        super().__init__(*args, **kwargs)

    def __setitem__(self, key: K, value: V) -> None:
        super().__setitem__(key, value)
        self.move_to_end(key)
        while len(self) > self.max_size:
            self.popitem(last=False)
