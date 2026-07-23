import httpx
import sys
from typing import Dict, Any, List, Optional
from .settings import settings
from .cache import capability_cache, series_map_cache, series_details_cache, series_episodes_cache
from .translator import MedusaTranslator
from .utils import logger

class MedusaClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {"x-api-key": self.api_key, "Content-Type": "application/json"}
        self.client = httpx.AsyncClient(base_url=settings.medusa_url, timeout=settings.timeout, follow_redirects=True)
        self.logged_in = False

    async def close(self):
        await self.client.aclose()

    async def login(self):
        if self.logged_in: return
        
        # Fetch login credentials from config
        config = await self.get_system_config()
        
        # Credentials are in config['webInterface']
        web_interface = config.get("webInterface", {})
        username = web_interface.get("username")
        password = web_interface.get("password")
        
        print(f"[DEBUG] Login attempt - Username extracted: {bool(username)}, Password extracted: {bool(password)}", file=sys.stderr, flush=True)
        
        if username and password:
            # Login to web UI to get session cookies
            res = await self.client.post("/login/", data={"username": username, "password": password})
            print(f"[DEBUG] Login response status: {res.status_code}", file=sys.stderr, flush=True)
            self.logged_in = True
        else:
            print(f"[DEBUG] Login skipped: Missing username or password in config. Available keys: {list(config.keys())}", file=sys.stderr, flush=True)

    async def browser(self, params: Dict[str, Any]) -> Any:
        await self.login()
        res = await self.client.get("/browser/", params=params, headers=self.headers)
        
        # Use print to ensure visibility in logs
        print(f"[DEBUG] /browser/ returned status {res.status_code}", file=sys.stderr, flush=True)
        
        if res.status_code == 200:
            try:
                return res.json()
            except Exception as e:
                print(f"[ERROR] Failed to decode JSON from /browser/. Content preview: {res.text[:500]}", file=sys.stderr, flush=True)
                raise e
        else:
            print(f"[ERROR] /browser/ request failed. Status: {res.status_code}, Content preview: {res.text[:500]}", file=sys.stderr, flush=True)
            return []

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
            # Update cache map for episode lookups in batch
            cache_updates = {}
            for show in shows:
                m_id = MedusaTranslator.extract_clean_integer_id(show)
                
                # The API provides a slug directly in the 'id' field of the response
                show_id_info = show.get("id", {})
                slug = show_id_info.get("slug")
                
                if not slug:
                    # Fallback if slug is missing
                    indexer = show.get("default_indexer") or show.get("indexer") or "tvdb"
                    val = show.get("ids", {}).get(indexer)
                    slug = f"{indexer}{val}" if val else str(m_id)
                
                cache_updates[f"map_{m_id}"] = slug
            
            await series_map_cache.set_many(cache_updates)
            print(f"[DEBUG] get_all_series: Updated cache with {len(cache_updates)} mappings", file=sys.stderr, flush=True)
            return shows
        return []

    async def get_series_by_id(self, series_id: int) -> Optional[Dict[str, Any]]:
        # Attempt to retrieve from details cache first
        cached_details = await series_details_cache.get(f"details_{series_id}")
        if cached_details: return cached_details

        # Attempt to retrieve the slug from cache
        slug = await series_map_cache.get(f"map_{series_id}")
        if not slug:
            # If mapping is missing, refresh cache by fetching all series
            await self.get_all_series()
            slug = await series_map_cache.get(f"map_{series_id}") or series_id

        res = await self.client.get(f"/api/v2/series/{slug}", headers=self.headers)
        if res.status_code == 200:
            details = res.json()
            await series_details_cache.set(f"details_{series_id}", details)
            return details
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
        # Attempt to retrieve from episodes cache first
        cached_episodes = await series_episodes_cache.get(f"episodes_{target_id}")
        if cached_episodes: return cached_episodes

        # Attempt to retrieve the slug from cache
        slug = await series_map_cache.get(f"map_{target_id}")
        
        # If mapping is missing, attempt to refresh cache
        if not slug:
            await self.get_all_series()
            slug = await series_map_cache.get(f"map_{target_id}")

        # If still no slug, try fetching series details to construct it properly
        if not slug:
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
            else:
                slug = str(target_id)

        # Make the API call using the resolved slug and increase limit to get all episodes
        url = f"/api/v2/series/{slug}/episodes"
        res = await self.client.get(url, params={"limit": 1000}, headers=self.headers)

        if res.status_code == 200:
            episodes = res.json()
            await series_episodes_cache.set(f"episodes_{target_id}", episodes)
            return episodes

        return []

    async def execute_command(self, cmd_name: str, series_id: Optional[int] = None) -> bool:
        slug = None
        if series_id:
            slug = await series_map_cache.get(f"map_{series_id}") or str(series_id)

        if cmd_name == "RefreshSeries" and slug:
            res = await self.client.post(f"/api/v2/series/{slug}/actions/force-update", headers=self.headers)
            return res.status_code == 200
        elif cmd_name in ["RescanSeries", "SeriesSearch"] and slug:
            res = await self.client.post(f"/api/v2/series/{slug}/actions/force-search", headers=self.headers)
            return res.status_code == 200
        elif cmd_name == "CheckForUpdates":
            res = await self.client.post("/api/v2/system/operation", json={"command": "check_update"}, headers=self.headers)
            return res.status_code == 200
        return False

    async def get_indexers(self) -> List[Dict[str, Any]]:
        res = await self.client.get("/api/v2/providers", headers=self.headers)
        return res.json() if res.status_code == 200 else []

    async def browser(self, params: Dict[str, Any]) -> Any:
        await self.login()
        res = await self.client.get("/browser/", params=params, headers=self.headers)
        
        # Use print to ensure visibility in logs
        print(f"[DEBUG] /browser/ returned status {res.status_code}", file=sys.stderr, flush=True)
        
        if res.status_code == 200:
            try:
                return res.json()
            except Exception as e:
                print(f"[ERROR] Failed to decode JSON from /browser/. Content preview: {res.text[:500]}", file=sys.stderr, flush=True)
                raise e
        else:
            print(f"[ERROR] /browser/ request failed. Status: {res.status_code}, Content preview: {res.text[:500]}", file=sys.stderr, flush=True)
            return []
