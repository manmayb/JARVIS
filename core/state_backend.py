"""Pluggable state backend for rate-limits and tool confirmations.

Defaults to an in-memory backend. When ``REDIS_URL`` is set in the
environment the Redis backend is used instead, enabling horizontal
scaling across multiple Uvicorn workers.
"""

from __future__ import annotations

import asyncio, time
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Optional
from core.config import settings
from core.logging import get_logger

log = get_logger(__name__)


# ── Abstract interface ──────────────────────────────────────────────

class StateBackend(ABC):
    """Minimal state interface consumed by executor and sandbox."""

    @abstractmethod
    async def rate_limit_allowed(self, key: str,
                                 limit: int, window: int = 60) -> bool: ...

    @abstractmethod
    async def add_approval(self, user_id: str, tool_name: str,
                           tier: str) -> None: ...

    @abstractmethod
    async def has_approval(self, user_id: str, tool_name: str,
                           tier: str) -> bool: ...

    @abstractmethod
    async def append_to_list(self, key: str, value: str) -> None: ...

    @abstractmethod
    async def get_list(self, key: str) -> list[str]: ...


# ── In-memory implementation ────────────────────────────────────────

class MemoryBackend(StateBackend):
    def __init__(self):
        self._rate: dict[str, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()
        self._approvals: dict[str, set[str]] = {}   # "user:tier" → {tool}
        self._lists: dict[str, list[str]] = defaultdict(list)

    async def rate_limit_allowed(self, key: str,
                                 limit: int, window: int = 60) -> bool:
        now = time.monotonic()
        async with self._lock:
            self._rate[key] = [t for t in self._rate[key]
                               if t > now - window]
            if len(self._rate[key]) >= limit:
                return False
            self._rate[key].append(now)
            return True

    async def add_approval(self, user_id: str, tool_name: str,
                           tier: str) -> None:
        k = f"{user_id}:{tier}"
        self._approvals.setdefault(k, set()).add(tool_name)

    async def has_approval(self, user_id: str, tool_name: str,
                           tier: str) -> bool:
        return tool_name in self._approvals.get(f"{user_id}:{tier}", set())

    async def append_to_list(self, key: str, value: str) -> None:
        async with self._lock:
            self._lists[key].append(value)

    async def get_list(self, key: str) -> list[str]:
        async with self._lock:
            return list(self._lists.get(key, []))


# ── Redis implementation ────────────────────────────────────────────

class RedisBackend(StateBackend):
    def __init__(self, redis_client):
        self._r = redis_client

    async def rate_limit_allowed(self, key: str,
                                 limit: int, window: int = 60) -> bool:
        pipe = self._r.pipeline()
        now = time.time()
        rl_key = f"rl:{key}"
        pipe.zremrangebyscore(rl_key, "-inf", now - window)
        pipe.zadd(rl_key, {str(now): now})
        pipe.zcard(rl_key)
        pipe.expire(rl_key, window + 5)
        results = await pipe.execute()
        return results[2] <= limit

    async def add_approval(self, user_id: str, tool_name: str,
                           tier: str) -> None:
        await self._r.sadd(f"approval:{user_id}:{tier}", tool_name)

    async def has_approval(self, user_id: str, tool_name: str,
                           tier: str) -> bool:
        return await self._r.sismember(
            f"approval:{user_id}:{tier}", tool_name
        )

    async def append_to_list(self, key: str, value: str) -> None:
        rk = f"list:{key}"
        await self._r.rpush(rk, value)
        await self._r.expire(rk, 3600)  # 1 hour TTL for transient logs

    async def get_list(self, key: str) -> list[str]:
        return await self._r.lrange(f"list:{key}", 0, -1)


# ── Factory ─────────────────────────────────────────────────────────

_backend: StateBackend | None = None


async def get_backend() -> StateBackend:
    global _backend
    if _backend is not None:
        return _backend

    redis_url = getattr(settings, "redis_url", None)
    if redis_url:
        try:
            import redis.asyncio as aioredis
            client = aioredis.from_url(redis_url, decode_responses=True)
            await client.ping()
            _backend = RedisBackend(client)
            log.info("state.backend", type="redis", url=redis_url)
            return _backend
        except Exception as exc:
            log.warning("state.redis_failed", error=str(exc))

    _backend = MemoryBackend()
    log.info("state.backend", type="memory")
    return _backend


async def close_backend() -> None:
    global _backend
    if isinstance(_backend, RedisBackend):
        await _backend._r.close()
    _backend = None
