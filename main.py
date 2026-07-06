import os
import urllib.parse
import sys
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, Header, HTTPException, Query, status, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.types import ASGIApp, Scope, Receive, Send
import httpx

# ---------------------------------------------------------------------------
# CASE-INSENSITIVE ROUTING MIDDLEWARE
# ---------------------------------------------------------------------------
class CaseInsensitiveAPIMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] == "http":
            path = scope.get("path", "")
            if path.startswith("/api/v3"):
                scope["path"] = path.lower()
        await self.app(scope, receive, send)

# ---------------------------------------------------------------------------
# APP INITIALIZATION & LOGGER CONFIG
# ---------------------------------------------------------------------------
app = FastAPI(title="GorgonTarget Stateless Proxy", version="3.4.3")
app.add_middleware(CaseInsensitiveAPIMiddleware)

MEDUSA_URL = os.getenv("MEDUSA_URL", "http://localhost:8081")
async_client = httpx.AsyncClient(base_url=MEDUSA_URL, timeout=15.0)

def log_debug(message: str):
    print(f"[GorgonTarget DEBUG] {message}", file=sys.stderr, flush=True)

# ---------------------------------------------------------------------------
# DYNAMIC AUTHENTICATION HELPER
# ---------------------------------------------------------------------------
def get_medusa_key(
    x_api_key: Optional[str] = Header(None),
    apikey: Optional[str] = Query(None),
    api_key: Optional[str] = Query(None)
) -> str:
    resolved_key = x_api_key or apikey or api_key
    if not resolved_key:
        log_debug("Authentication rejected: Missing API key context.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Missing API Key parameter or X-Api-Key header from Sonarr client."
        )
    return resolved_key

def medusa_headers(api_key: str) -> dict:
    return {"x-api-key": api_key, "Content-Type": "application/json"}

# ---------------------------------------------------------------------------
# REQUEST MODELS
# ---------------------------------------------------------------------------
class SonarrAddSeries(BaseModel):
    title: str
    tvdbId: int
    profileId: int
    rootFolderPath: str
    monitored: bool = True
    addOptions: Optional[dict] = None

class SonarrCommand(BaseModel):
    name: str
    seriesId: Optional[int] = None
    episodeIds: Optional[List[int]] = None

# ---------------------------------------------------------------------------
# ROOT HEALTH PATHS
# ---------------------------------------------------------------------------
@app.get("/")
async def root_index():
    return {"status": "running", "service": "GorgonTarget Proxy"}

# ---------------------------------------------------------------------------
# 1. SYSTEM & CONFIGURATION ENDPOINTS
# ---------------------------------------------------------------------------
@app.get("/api/v3/system/status")
async def get_system_status(api_key: str = Depends(get_medusa_key)):
    medusa_version = "3.0.10.1567"
    os_name = "linux"
    startup_path = "/app"
    app_data = "/config"
    
    try:
        config_res = await async_client.get("/api/v2/config", headers=medusa_headers(api_key))
        if config_res.status_code == 200:
            medusa_config = config_res.json()
            main_config = medusa_config.get("main", {}) or medusa_config.get("app", {})
            if "version" in main_config:
                medusa_version = main_config.get("version")
            running_dir = main_config.get("rootDir", main_config.get("dataDir", "/config"))
            if "\\" in running_dir:
                os_name = "windows"
                startup_path = "C:\\Program Files\\Medusa"
                app_data = running_dir
            else:
                startup_path = main_config.get("rootDir", "/app")
                app_data = main_config.get("dataDir", "/config")
    except Exception as e:
        log_debug(f"Exception falling back config properties: {str(e)}")

    return {
        "version": medusa_version,
        "buildTime": "2026-01-01T00:00:00Z",
        "isDebug": False,
        "isProduction": True,
        "isAdmin": True,
        "isUserInteractive": False,
        "startupPath": startup_path,
        "appData": app_data,
        "osName": os_name,
        "osVersion": "alpine" if os_name == "linux" else "NT",
        "isNetCore": True,
        "appName": "Sonarr"
    }

@app.get("/api/v3/diskspace")
async def get_disk_space(api_key: str = Depends(get_medusa_key)):
    return [{
        "path": "/tv",
        "label": "TV Shows",
        "freeSpace": 500000000000,
        "totalSpace": 1000000000000
    }]

# ---------------------------------------------------------------------------
# 2. PROFILES, TAGS, AND CONFIGURATIONS
# ---------------------------------------------------------------------------
@app.get("/api/v3/qualityprofile")
async def get_quality_profiles(api_key: str = Depends(get_medusa_key)):
    return [
        {"id": 1, "name": "Medusa Managed Profile", "upgradeAllowed": False, "cutoff": 1, "items": []},
        {"id": 2, "name": "HD - 720p/1080p", "upgradeAllowed": False, "cutoff": 2, "items": []}
    ]

@app.get("/api/v3/languageprofile")
async def get_language_profiles(api_key: str = Depends(get_medusa_key)):
    return [{"id": 1, "name": "English", "cutoff": {"id": 1, "name": "English"}, "languages": [{"language": {"id": 1, "name": "English"}, "allowed": True}]}]

@app.get("/api/v3/rootfolder")
async def get_root_folders(api_key: str = Depends(get_medusa_key)):
    return [{"id": 1, "path": "/tv", "accessible": True, "freeSpace": 500000000000, "unmappedFolders": []}]

@app.get("/api/v3/filesystem")
async def get_filesystem(path: Optional[str] = Query(None), api_key: str = Depends(get_medusa_key)):
    return {"parent": "", "directories": [{"name": "tv", "path": "/tv", "type": "directory"}], "files": []}

@app.get("/api/v3/tag")
async def get_tags(api_key: str = Depends(get_medusa_key)): 
    return []

@app.get("/api/v3/customformat")
async def get_custom_formats(api_key: str = Depends(get_medusa_key)): 
    return []

# ---------------------------------------------------------------------------
# 3. SERIES & EPISODE TRANSFORMATION LOGIC
# ---------------------------------------------------------------------------
@app.get("/api/v3/series")
async def get_all_series(api_key: str = Depends(get_medusa_key)):
    log_debug("Fetching global show registry list via /api/v2/series")
    try:
        res = await async_client.get("/api/v2/series", headers=medusa_headers(api_key))
        if res.status_code != 200:
            log_debug(f"Downstream Medusa global series fetch failed: {res.status_code}")
            return JSONResponse(status_code=res.status_code, content=res.json())
        
        medusa_shows = res.json()
        sonarr_shows = []
        for show in medusa_shows:
            # FIX: Fallback safely to TVDB IDs so 'id' fields are never 0
            series_id = show.get("ids", {}).get("tvdb") or show.get("id")
            try:
                series_id = int(series_id)
            except (ValueError, TypeError):
                series_id = 99999  # Safe unique fallback integer if conversion fails
                
            sonarr_shows.append({
                "id": series_id, 
                "title": show.get("title"),
                "sortTitle": show.get("title", "").lower(),
                "status": "continuing" if show.get("status") == "continuing" else "ended",
                "overview": show.get("overview", ""),
                "tvdbId": series_id,
                "path": show.get("path", "/tv"),
                "profileId": 1,
                "languageProfileId": 1,
                "monitored": not show.get("paused", False),
                "useSceneNumbering": False,
                "seasons": [] 
            })
        log_debug(f"Successfully processed and translated {len(sonarr_shows)} shows back to Sonarr UI context.")
        return sonarr_shows
    except Exception as e:
        log_debug(f"Exception handling processing global show lists: {str(e)}")
        return JSONResponse(status_code=502, content={"error": str(e)})

@app.get("/api/v3/series/{series_id}")
async def get_single_series(series_id: int, api_key: str = Depends(get_medusa_key)):
    log_debug(f"Polling database for individual show entry match ID: {series_id}")
    
    if series_id == 0:
        log_debug("Intercepted query for context ID 0. Sending back initialization safe-stub.")
        return {"id": 0, "title": "Initialization Stub", "tvdbId": 0, "path": "/tv", "monitored": False}
        
    try:
        res = await async_client.get(f"/api/v2/series/{series_id}", headers=medusa_headers(api_key))
        if res.status_code != 200:
            # Second attempt via tracking direct TVDB indexing compatibility fallback
            res = await async_client.get(f"/api/v2/series/tvdb:{series_id}", headers=medusa_headers(api_key))
            
        if res.status_code != 200:
            log_debug(f"Medusa single show ID fetch could not find target index: {series_id}")
            raise HTTPException(status_code=404, detail="Series not found")
            
        show = res.json()
        return {
            "id": series_id, 
            "title": show.get("title"),
            "tvdbId": series_id,
            "path": show.get("path", "/tv"),
            "monitored": not show.get("paused", False),
        }
    except Exception:
        raise HTTPException(status_code=404, detail="Series not found")

@app.post("/api/v3/series")
async def add_series(payload: SonarrAddSeries, api_key: str = Depends(get_medusa_key)):
    log_debug(f"Interpreting queue update payload request to insert TVDB index: {payload.tvdbId}")
    medusa_payload = {
        "config": {
            "location": f"{payload.rootFolderPath}/{payload.title}",
            "qualities": [], 
            "paused": not payload.monitored
        },
        "ids": {"tvdb": payload.tvdbId},
        "selectedIndexer": "tvdb"
    }
    try:
        res = await async_client.post("/api/v2/series", json=medusa_payload, headers=medusa_headers(api_key))
        if res.status_code in [200, 201]:
            return {
                "id": payload.tvdbId,
                "title": payload.title,
                "tvdbId": payload.tvdbId,
                "path": medusa_payload["config"]["location"],
                "monitored": payload.monitored,
                "profileId": payload.profileId
            }
        return JSONResponse(status_code=res.status_code, content=res.json())
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": str(e)})

@app.get("/api/v3/series/lookup")
async def series_lookup(term: Optional[str] = Query(None), api_key: str = Depends(get_medusa_key)):
    log_debug(f"Incoming search query context parameter details: '{term}'")
    if not term:
        return []
    
    clean_term = urllib.parse.unquote(term)
    if clean_term.lower().startswith("tvdb:"):
        query_term = clean_term.split(":")[-1].strip()
        log_debug(f"Extracted direct tracking TVDB string index sequence: '{query_term}'")
    else:
        query_term = clean_term
    
    try:
        res = await async_client.get("/api/v2/series/lookup", params={"q": query_term, "indexer": "tvdb"}, headers=medusa_headers(api_key))
        if res.status_code != 200: 
            log_debug(f"Downstream Medusa tracking lookup failed: {res.status_code} - {res.text}")
            return []
            
        items = res.json()
        translated_results = []
        for item in items:
            translated_results.append({
                "title": item.get("title"),
                "tvdbId": item.get("ids", {}).get("tvdb"),
                "overview": item.get("overview"),
                "year": item.get("year", 0),
                "remotePoster": item.get("image", "")
            })
        log_debug(f"Lookup generated {len(translated_results)} parsed objects for the client frontend UI.")
        return translated_results
    except Exception as e:
        log_debug(f"Internal processing exception thrown inside validation: {str(e)}")
        return []

@app.get("/api/v3/episode")
async def get_episodes(seriesId: Optional[int] = Query(None), api_key: str = Depends(get_medusa_key)):
    if not seriesId:
        return []
    try:
        res = await async_client.get(f"/api/v2/series/{seriesId}/episodes", headers=medusa_headers(api_key))
        if res.status_code != 200: 
            return []
        
        sonarr_episodes = []
        for ep in res.json():
            sonarr_episodes.append({
                "id": ep.get("id"),
                "seriesId": seriesId,
                "episodeFileId": 0 if ep.get("status") != "Downloaded" else ep.get("id"),
                "seasonNumber": ep.get("season"),
                "episodeNumber": ep.get("episode"),
                "title": ep.get("title", f"Episode {ep.get('episode')}"),
                "monitored": True,
                "hasFile": True if ep.get("status") == "Downloaded" else False
            })
        return sonarr_episodes
    except Exception:
        return []

# ---------------------------------------------------------------------------
# 4. CALENDAR, QUEUE, WANTED & HISTORY
# ---------------------------------------------------------------------------
@app.get("/api/v3/calendar")
async def get_calendar(start: str = Query(...), end: str = Query(...), api_key: str = Depends(get_medusa_key)):
    try:
        res = await async_client.get("/api/v2/schedule", headers=medusa_headers(api_key))
        if res.status_code != 200: 
            return []
        
        calendar = []
        for item in res.json().get("coming", []):
            calendar.append({
                "seriesId": item.get("seriesId"),
                "episodeNumber": item.get("episode"),
                "seasonNumber": item.get("season"),
                "title": item.get("title"),
                "airDateUtc": item.get("airDate")
            })
        return calendar
    except Exception:
        return []

@app.get("/api/v3/wanted/missing")
async def get_wanted_missing(api_key: str = Depends(get_medusa_key)):
    try:
        res = await async_client.get("/api/v2/schedule", headers=medusa_headers(api_key))
        if res.status_code != 200:
            return {"page": 1, "pageSize": 20, "totalRecords": 0, "records": []}
        
        medusa_schedule = res.json()
        combined = medusa_schedule.get("missed", []) + medusa_schedule.get("coming", [])
        
        records = [{
            "id": idx + 1000,
            "seriesId": item.get("seriesId"),
            "episodeNumber": item.get("episode"),
            "seasonNumber": item.get("season"),
            "title": item.get("title"),
            "airDateUtc": item.get("airDate")
        } for idx, item in enumerate(combined)]
        
        return {"page": 1, "pageSize": len(records) if records else 20, "totalRecords": len(records), "records": records}
    except Exception:
        return {"page": 1, "pageSize": 20, "totalRecords": 0, "records": []}

@app.get("/api/v3/queue")
async def get_queue(api_key: str = Depends(get_medusa_key)):
    return {"page": 1, "pageSize": 20, "sortKey": "id", "sortDirection": "descending", "totalRecords": 0, "records": []}

@app.get("/api/v3/queue/status")
async def get_queue_status(api_key: str = Depends(get_medusa_key)):
    return {"unhealthyCount": 0, "unknownCount": 0, "errors": False, "warnings": False}

@app.get("/api/v3/history")
async def get_history(api_key: str = Depends(get_medusa_key)):
    # FIX: Return fully mapped envelope object block rather than an empty flat array
    return {
        "page": 1,
        "pageSize": 100,
        "sortKey": "date",
        "sortDirection": "descending",
        "totalRecords": 0,
        "records": []
    }

# ---------------------------------------------------------------------------
# 5. HARDWARE AGENTS
# ---------------------------------------------------------------------------
@app.get("/api/v3/downloadclient")
async def get_download_clients(api_key: str = Depends(get_medusa_key)): return []

@app.get("/api/v3/indexer")
async def get_indexers(api_key: str = Depends(get_medusa_key)): return []

@app.get("/api/v3/metadata")
async def get_metadata_consumers(api_key: str = Depends(get_medusa_key)): return []

# ---------------------------------------------------------------------------
# 6. COMMAND ORCHESTRATION ENGINE
# ---------------------------------------------------------------------------
@app.post("/api/v3/command")
async def execute_command(command: SonarrCommand, api_key: str = Depends(get_medusa_key)):
    if command.name in ["RefreshSeries", "RescanSeries"] and command.seriesId:
        await async_client.post(f"/api/v2/series/{command.seriesId}/actions/force-update", headers=medusa_headers(api_key))
        return {"id": 999, "name": command.name, "state": "completed"}
    elif command.name == "SeriesSearch" and command.seriesId:
        await async_client.post(f"/api/v2/series/{command.seriesId}/actions/force-search", headers=medusa_headers(api_key))
        return {"id": 998, "name": command.name, "state": "completed"}
    return {"id": 1000, "name": command.name, "state": "completed"}

@app.get("/api/v3/command/{command_id}")
async def get_command_status(command_id: int, api_key: str = Depends(get_medusa_key)):
    return {"id": command_id, "state": "completed"}
