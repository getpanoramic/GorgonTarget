import httpx
from typing import Dict, Any, List, Optional
from .settings import settings
from .cache import capability_cache, series_map_cache
from .translator import MedusaTranslator

class MedusaClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {"x-api-key": self.api_key, "Content-Type": "application/json"}
        self.client = httpx.AsyncClient(base_url=settings.medusa_url, timeout=settings.timeout)

    async def close(self):
        await self.client.aclose()

    async def detect_capabilities(self) -> Dict[str, bool]:
        cached = await capability_cache.get(self.api_key)
        if cached: return cached

        caps = {"v2_rest": False, "legacy_cmd": False}
        try:
            res = await self.client.get("/api/v2/?cmd=server.info", headers=self.headers)
            if res.status_code == 200:
                caps["v2_rest"] = True
        except Exception:
            pass
        
        await capability_cache.set(self.api_key, caps)
        return caps

    async def get_system_config(self) -> Dict[str, Any]:
        try:
            res = await self.client.get("/api/v2/config", headers=self.headers)
            if res.status_code == 200:
                return res.json()
        except Exception:
            pass
        return {}

    async def get_all_series(self) -> List[Dict[str, Any]]:
        res = await self.client.get("/api/v2/series", params={"limit": 1000}, headers=self.headers)
        if res.status_code == 200:
            shows = res.json()
            # Update cache map for episode lookups
            for show in shows:
                m_id = MedusaTranslator.extract_clean_integer_id(show)
                indexer = show.get("default_indexer") or show.get("indexer") or "tvdb"
                val = show.get("ids", {}).get(indexer)
                slug = f"{indexer}{val}" if val else str(m_id)
                await series_map_cache.set(f"map_{m_id}", slug)
            return shows
        return []

    async def get_series_by_id(self, series_id: int) -> Optional[Dict[str, Any]]:
        res = await self.client.get(f"/api/v2/series/{series_id}", headers=self.headers)
        if res.status_code == 200:
            return res.json()
        return None

    async def add_series(self, tvdb_id: int, root_path: str, title: str, monitored: bool) -> Optional[Dict[str, Any]]:
        caps = await self.detect_capabilities()
        if caps.get("v2_rest"):
            payload = {
                "config": {"location": f"{root_path}/{title}", "qualities": [], "paused": not monitored},
                "ids": {"tvdb": tvdb_id},
                "selectedIndexer": "tvdb"
            }
            res = await self.client.post("/api/v2/series", json=payload, headers=self.headers)
            if res.status_code in [200, 201]:
                return res.json()

        # Fallback to legacy
        params = {"cmd": "series.addnew", "indexer": 1, "indexerid": tvdb_id, "location": root_path}
        res = await self.client.get(f"/api/v2/{self.api_key}/", params=params, headers=self.headers)
        if res.status_code == 200 and res.json().get("result") == "success":
            return {"id": tvdb_id, "title": title, "path": root_path}
        return None

    async def get_episodes(self, target_id: int) -> List[Dict[str, Any]]:
        slug = await series_map_cache.get(f"map_{target_id}") or target_id
        res = await self.client.get(f"/api/v2/series/{slug}/episodes", headers=self.headers)
        if res.status_code == 200:
            return res.json()
        return []
