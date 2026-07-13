import httpx
import sys
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
                # Ensure we handle nested IDs structure correctly
                ids = show.get("ids", {})
                
                # DEBUG: Log the show structure to understand why extraction is failing
                print(f"[DEBUG] get_all_series: show_id={show.get('id')}, ids={ids}, default_indexer={show.get('default_indexer')}", file=sys.stderr, flush=True)

                indexer = show.get("default_indexer") or show.get("indexer") or "tvdb"
                val = ids.get(indexer)
                
                # If indexer+id is not possible, try to find *any* indexer id
                if not val:
                    for k in ["tvdb", "tvmaze", "imdb"]:
                        if ids.get(k):
                            indexer = k
                            val = ids.get(k)
                            break
                            
                slug = f"{indexer}{val}" if val else str(m_id)
                await series_map_cache.set(f"map_{m_id}", slug)
                print(f"[DEBUG] get_all_series: Mapping m_id={m_id} to slug={slug}", file=sys.stderr, flush=True)
            return shows
        return []

    async def get_series_by_id(self, series_id: int) -> Optional[Dict[str, Any]]:
        # Attempt to retrieve the slug from cache
        slug = await series_map_cache.get(f"map_{series_id}")
        if not slug:
            # If mapping is missing, refresh cache by fetching all series
            await self.get_all_series()
            slug = await series_map_cache.get(f"map_{series_id}") or series_id

        res = await self.client.get(f"/api/v2/series/{slug}", headers=self.headers)
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
        # Attempt to retrieve the slug from cache
        slug = await series_map_cache.get(f"map_{target_id}")
        print(f"[DEBUG] get_episodes: target_id={target_id}, cached_slug={slug}", file=sys.stderr, flush=True)

        # If mapping is missing, attempt to refresh cache
        if not slug:
            print(f"[DEBUG] get_episodes: Mapping missing, refreshing cache...", file=sys.stderr, flush=True)
            await self.get_all_series()
            slug = await series_map_cache.get(f"map_{target_id}")
            print(f"[DEBUG] get_episodes: After refresh, cached_slug={slug}", file=sys.stderr, flush=True)

        # If still no slug, try fetching series details to construct it properly
        if not slug:
            print(f"[DEBUG] get_episodes: Still no slug, fetching series details for target_id={target_id}", file=sys.stderr, flush=True)
            series_data = await self.get_series_by_id(target_id)
            if series_data:
                # Correctly construct indexer+id
                indexer = series_data.get("default_indexer") or series_data.get("indexer") or "tvdb"
                # Use the ID value associated with that indexer
                val = series_data.get("ids", {}).get(indexer)
                if val:
                    slug = f"{indexer}{val}"
                else:
                    # Fallback to numeric if somehow missing (still likely to fail, but safer)
                    slug = str(target_id)
                print(f"[DEBUG] get_episodes: Constructed slug={slug} from series data", file=sys.stderr, flush=True)
            else:
                slug = str(target_id)
                print(f"[DEBUG] get_episodes: Could not fetch series data, using raw target_id={slug}", file=sys.stderr, flush=True)

        # Make the API call using the resolved slug
        url = f"/api/v2/series/{slug}/episodes"
        print(f"[DEBUG] get_episodes: Calling API URL={url}", file=sys.stderr, flush=True)
        res = await self.client.get(url, headers=self.headers)

        print(f"[DEBUG] get_episodes: API status={res.status_code}", file=sys.stderr, flush=True)
        if res.status_code == 200:
            return res.json()

        print(f"[DEBUG] get_episodes: Failed API call, response={res.text[:100]}", file=sys.stderr, flush=True)
        return []

    async def get_calendar(self) -> Dict[str, List[Dict[str, Any]]]:
        res = await self.client.get("/api/v2/schedule", headers=self.headers)
        if res.status_code == 200:
            return res.json()
        return {"coming": [], "missed": []}

    async def get_history(self) -> List[Dict[str, Any]]:
        res = await self.client.get("/api/v2/history", headers=self.headers)
        if res.status_code == 200:
            return res.json()
        return []

    async def get_logs(self, limit: int = 1000) -> List[Dict[str, Any]]:
        res = await self.client.get("/api/v2/log", params={"raw": "true", "limit": limit}, headers=self.headers)
        if res.status_code == 200:
            try:
                match = re.search(r'\[.*\]', res.text)
                return json.loads(match.group(0)) if match else []
            except Exception:
                pass
        return []

    async def get_raw_logs(self) -> str:
        res = await self.client.get("/api/v2/log", params={"raw": "true"}, headers=self.headers)
        return res.text if res.status_code == 200 else ""

    async def get_download_clients(self) -> Dict[str, Any]:
        res = await self.client.get("/api/v2/config", headers=self.headers)
        return res.json().get("clients", {}) if res.status_code == 200 else {}

    async def get_indexers(self) -> List[Dict[str, Any]]:
        res = await self.client.get("/api/v2/providers", headers=self.headers)
        return res.json() if res.status_code == 200 else []

    async def execute_command(self, cmd_name: str, series_id: Optional[int] = None) -> bool:
        if cmd_name == "RefreshSeries" and series_id:
            res = await self.client.post(f"/api/v2/series/{series_id}/actions/force-update", headers=self.headers)
            return res.status_code == 200
        elif cmd_name in ["RescanSeries", "SeriesSearch"] and series_id:
            res = await self.client.post(f"/api/v2/series/{series_id}/actions/force-search", headers=self.headers)
            return res.status_code == 200
        elif cmd_name == "CheckForUpdates":
            res = await self.client.post("/api/v2/system/operation", json={"command": "check_update"}, headers=self.headers)
            return res.status_code == 200
        return False
