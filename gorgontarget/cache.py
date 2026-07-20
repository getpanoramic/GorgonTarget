import time
import asyncio
from typing import Any, Dict, Optional

class AsyncTTLCache:
    def __init__(self, ttl: int = 300):
        self.ttl = ttl
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Any]:
        async with self._lock:
            entry = self._cache.get(key)
            if entry:
                if time.time() - entry["timestamp"] < self.ttl:
                    return entry["value"]
                else:
                    del self._cache[key]
            return None

    async def set(self, key: str, value: Any):
        async with self._lock:
            self._cache[key] = {
                "value": value,
                "timestamp": time.time()
            }

    async def set_many(self, entries: Dict[str, Any]):
        async with self._lock:
            now = time.time()
            for key, value in entries.items():
                self._cache[key] = {
                    "value": value,
                    "timestamp": now
                }

    async def clear(self):
        async with self._lock:
            self._cache.clear()

# Singleton instances for different cache domains
series_map_cache = AsyncTTLCache(ttl=3600)
series_details_cache = AsyncTTLCache(ttl=3600)
series_episodes_cache = AsyncTTLCache(ttl=3600)
episode_series_map = AsyncTTLCache(ttl=3600)  # Added cache for episode to series mapping
capability_cache = AsyncTTLCache(ttl=86400)
series_list_cache = AsyncTTLCache(ttl=3600)
search_cache = AsyncTTLCache(ttl=300)
