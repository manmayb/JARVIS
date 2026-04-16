"""Async-safe TTL cache for LLM responses and tool outputs.

Uses an in-memory dict with monotonic timestamps for expiry. Thread-safe
via asyncio.Lock. Evicts expired entries lazily on access and periodically
on set.
"""

from __future__ import annotations

import asyncio, hashlib, json, time
from typing import Any, Optional
from core.logging import get_logger

log = get_logger(__name__)


class TTLCache:
    """Simple async-safe in-memory TTL cache."""

    def __init__(self, default_ttl: int = 600, max_size: int = 512):
        self._store: dict[str, tuple[float, Any]] = {}
        self._default_ttl = default_ttl
        self._max_size = max_size
        self._lock = asyncio.Lock()
        self._hits = 0
        self._misses = 0

    @staticmethod
    def _make_key(*parts: Any) -> str:
        raw = json.dumps(parts, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()[:24]

    async def get(self, key: str) -> Optional[Any]:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            expires, value = entry
            if time.monotonic() > expires:
                del self._store[key]
                self._misses += 1
                return None
            self._hits += 1
            return value

    async def set(self, key: str, value: Any,
                  ttl: int | None = None) -> None:
        ttl = ttl or self._default_ttl
        async with self._lock:
            # Lazy eviction when at capacity
            if len(self._store) >= self._max_size:
                self._evict_expired()
            # If still at capacity, drop oldest entry
            if len(self._store) >= self._max_size:
                oldest_key = min(self._store, key=lambda k: self._store[k][0])
                del self._store[oldest_key]
            self._store[key] = (time.monotonic() + ttl, value)

    async def invalidate(self, key: str) -> None:
        async with self._lock:
            self._store.pop(key, None)

    async def clear(self) -> None:
        async with self._lock:
            self._store.clear()

    def stats(self) -> dict:
        return {
            "size": len(self._store),
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / max(1, self._hits + self._misses), 3),
        }

    def _evict_expired(self) -> None:
        now = time.monotonic()
        expired = [k for k, (exp, _) in self._store.items() if now > exp]
        for k in expired:
            del self._store[k]


# ---------- Singleton instances ----------

llm_cache = TTLCache(default_ttl=600, max_size=256)    # 10 min for LLM responses
tool_cache = TTLCache(default_ttl=300, max_size=128)   # 5 min for tool outputs
