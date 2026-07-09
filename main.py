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
# ADVANCED PATH & CASE-INSENSITIVE ROUTING MIDDLEWARE (WITH UA LOGGING)
# ---------------------------------------------------------------------------
class CaseInsensitiveAPIMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] == "http":
            # Extract headers and log the User-Agent and Path
            headers = dict(scope.get("headers", []))
            ua = headers.get(b"user-agent", b"Unknown").decode("utf-8", "ignore")
            path = scope.get("path", "")
            method = scope.get("method", "UNKNOWN")
            
            # Print to logs for debugging
            print(f"[GorgonTarget REQUEST] {method} {path} | UA: {ua}", file=sys.stderr, flush=True)
            
            # Normalize trailing slashes early
            if path.endswith("/") and len(path) > 1:
                path = path.rstrip("/")
                
            if path.startswith("/api"):
                scope["path"] = path.lower()
            else:
                scope["path"] = path

        await self.app(scope, receive, send)

# ---------------------------------------------------------------------------
# APP INITIALIZATION & LOGGER CONFIG
# ---------------------------------------------------------------------------
app = FastAPI(title="GorgonTarget Stateless Proxy", version="3.6.0")
app.add_middleware(CaseInsensitiveAPIMiddleware)

MEDUSA_URL = os.getenv("MEDUSA_URL", "http://localhost:8081")
async_client = httpx.AsyncClient(base_url=MEDUSA_URL, timeout=15.0)

# Maps Sonarr proxy IDs -> real Medusa IDs
SERIES_ID_MAP = {}

async_client = httpx.AsyncClient(
    base_url=MEDUSA_URL,
    timeout=30
)

def log_debug(message: str):
    print(f"[GorgonTarget DEBUG] {message}", file=sys.stderr, flush=True)

@app.on_event("startup")
async def startup_event():
    log_debug("Proxy starting up... checking Medusa version.")
    # Assuming you have a way to get your API key here
    # You might need to use a default or handle the key fetching
    version = await detect_medusa_version(YOUR_DEFAULT_API_KEY)
    # You can store this in a global variable to use in add_series
    global DETECTED_MEDUSA_VERSION
    DETECTED_MEDUSA_VERSION = version

# ---------------------------------------------------------------------------
# DYNAMIC AUTHENTICATION HELPER
# ---------------------------------------------------------------------------
async def get_medusa_key(
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
    
    # Trigger lazy version check now that we have the key
    await get_medusa_version_lazy(resolved_key)
    
    return resolved_key

def medusa_headers(api_key: str) -> dict:
    return {"x-api-key": api_key, "Content-Type": "application/json"}

# Global variables
DETECTED_MEDUSA_VERSION = None
CHECK_IN_PROGRESS = False

async def get_medusa_version_lazy(api_key: str):
    global DETECTED_MEDUSA_VERSION, CHECK_IN_PROGRESS
    
    # 1. Early exit if already completed
    if DETECTED_MEDUSA_VERSION is not None:
        return DETECTED_MEDUSA_VERSION
        
    # 2. Prevent concurrent checks
    if CHECK_IN_PROGRESS:
        log_debug("Detection already in progress, waiting for result...")
        return "Unknown"

    CHECK_IN_PROGRESS = True
    log_debug("First API hit: Starting lazy Medusa version detection.")
    
    try:
        # 3. Perform detection
        version = await detect_medusa_version(api_key)
        
        if version:
            DETECTED_MEDUSA_VERSION = version
            log_debug(f"SUCCESS: Medusa version detected as: {DETECTED_MEDUSA_VERSION}")
        else:
            DETECTED_MEDUSA_VERSION = "Unknown"
            log_debug("WARNING: Version detection failed (empty response). Defaulting to 'Unknown'.")
            
    except Exception as e:
        DETECTED_MEDUSA_VERSION = "Unknown"
        log_debug(f"ERROR: Exception during version detection: {str(e)}")
        
    finally:
        CHECK_IN_PROGRESS = False
        
    return DETECTED_MEDUSA_VERSION

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
# ID & VALUE CONVERSION SAFETY FUNCTIONS
# ---------------------------------------------------------------------------
def extract_clean_integer_id(show_node: dict) -> int:
    raw_id = show_node.get("id")

    if isinstance(raw_id, dict):
        raw_id = (
            raw_id.get("medusa")
            or raw_id.get("tvdb")
            or raw_id.get("tmdb")
        )

    try:
        return int(raw_id)
    except (ValueError, TypeError):
        return 0

def extract_clean_year(show_node: dict) -> int:
    raw_year = show_node.get("year") or show_node.get("startYear")
    if isinstance(raw_year, dict):
        raw_year = raw_year.get("year") or raw_year.get("value") or list(raw_year.values())[0]
        
    try:
        if raw_year is not None:
            return int(raw_year)
    except (ValueError, TypeError):
        pass
    return 0

# ---------------------------------------------------------------------------
# REUSABLE CORE IMPLEMENTATIONS (SHARED ACROSS V2/V3)
# ---------------------------------------------------------------------------
async def core_system_status(api_key: str):
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

async def core_all_series(api_key: str):
    log_debug("Fetching global show registry list via /api/v2/series")

    params = {"limit": 1000}

    res = await async_client.get(
        "/api/v2/series",
        params=params,
        headers=medusa_headers(api_key)
    )

    if res.status_code != 200:
        return JSONResponse(
            status_code=res.status_code,
            content=res.json()
        )

    medusa_shows = res.json()

    log_debug(
        f"Medusa returned {len(medusa_shows)} series"
    )

    sonarr_shows = []

    # refresh cache
    SERIES_ID_MAP.clear()

    for idx, show in enumerate(medusa_shows):
        ids = show.get("ids", {})
        medusa_id = extract_clean_integer_id(show)
        
        # Determine indexer and construct the SLUG
        indexer = show.get("default_indexer") or show.get("indexer") or "tvdb"
        val = ids.get(indexer) or ids.get("tvdb") or ids.get("tmdb")
        
        # BUILD THE SLUG (e.g., "tvdb324846")
        slug_string = f"{indexer}{val}" if val else str(medusa_id)
        
        # CRITICAL: Map Sonarr ID (int) -> Medusa SLUG (string)
        SERIES_ID_MAP[int(medusa_id)] = slug_string
        
        log_debug(f"Mapping Sonarr ID {medusa_id} to Medusa Slug: {slug_string}")
        
        # Redefine ID variables for your append block
        tvdb_id = ids.get("tvdb")
        tmdb_id = ids.get("tmdb")
        imdb_id = ids.get("imdb")

        log_debug(f"Mapping ID {medusa_id} to internal map")

        title = show.get(
            "title",
            f"Series {medusa_id}"
        )

        raw_path = show.get("path", "")

        if not raw_path or raw_path == "/tv":
            safe_folder = (
                title
                .replace("/", "_")
                .replace("\\", "_")
            )

            path = f"/tv/{safe_folder}"
        else:
            path = str(raw_path)

        sonarr_shows.append({

            "id": int(medusa_id),

            "tvdbId": int(tvdb_id) if tvdb_id else 0,
            "tmdbId": int(tmdb_id) if tmdb_id else 0,
            "imdbId": imdb_id or "",

            "title": title,
            "sortTitle": title.lower(),

            "status": (
                "continuing"
                if show.get("status") == "continuing"
                else "ended"
            ),

            "overview": show.get("overview", ""),

            "year": extract_clean_year(show),

            "images": [],
            "alternateTitles": [],
            "genres": [],
            "seriesType": "standard",

            "path": path,

            "profileId": 1,
            "languageProfileId": 1,

            "monitored": not show.get(
                "paused",
                False
            ),

            "useSceneNumbering": False,
            "added": "2026-01-01T00:00:00Z",
            "seasons": []
        })

    return sonarr_shows

# ---------------------------------------------------------------------------
# EXPLICIT LEGACY V2 PATH ROUTING FALLBACKS
# ---------------------------------------------------------------------------
@app.get("/api/system/status")
async def get_system_status_v2(api_key: str = Depends(get_medusa_key)):
    return await core_system_status(api_key)

@app.get("/api/series")
async def get_all_series_v2(api_key: str = Depends(get_medusa_key)):
    try:
        return await core_all_series(api_key)
    except Exception as e:
        log_debug(f"Exception handling legacy series list processing: {str(e)}")
        return JSONResponse(status_code=502, content={"error": str(e)})

# ---------------------------------------------------------------------------
# CORE MODERN V3 ENDPOINTS
# ---------------------------------------------------------------------------
@app.get("/")
async def root_index():
    return {"status": "running", "service": "GorgonTarget Proxy"}

@app.get("/api/v3/system/status")
async def get_system_status_v3(api_key: str = Depends(get_medusa_key)):
    return await core_system_status(api_key)

@app.get("/api/v3/diskspace")
async def get_disk_space(api_key: str = Depends(get_medusa_key)):
    return [{
        "path": "/tv",
        "label": "TV Shows",
        "freeSpace": 500000000000,
        "totalSpace": 1000000000000
    }]

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

@app.post("/api/v3/series")
async def add_series(payload: SonarrAddSeries, api_key: str = Depends(get_medusa_key)):
    # Medusa PVR expects 'cmd' in the query parameters
    params = {
        "cmd": "series.addnew",
        "indexer": 1,           # 1 = TheTVDB
        "indexerid": payload.tvdbId,
        "location": payload.rootFolderPath,
    }
    
    log_debug(f"Calling Medusa API with params: {params}")
    
    try:
        # Note the usage of 'params' and the correct API path for Pymedusa
        # The structure is typically /api/v2/<api_key>/
        res = await async_client.get(f"/api/v2/{api_key}/", params=params, headers=medusa_headers(api_key))
        
        log_debug(f"Medusa Response: {res.status_code} - {res.text}")
        
        if res.status_code == 200:
            data = res.json()
            # Check if Medusa actually succeeded
            if data.get("result") == "success":
                # Register the new ID in your map so future lookups succeed
                clean_id = int(payload.tvdbId) # Using TVDB ID as a fallback for internal mapping
                SERIES_ID_MAP[clean_id] = f"tvdb{payload.tvdbId}"
                
                return {
                    "id": clean_id,
                    "title": payload.title,
                    "tvdbId": payload.tvdbId,
                    "path": payload.rootFolderPath,
                    "monitored": payload.monitored,
                }
            else:
                return JSONResponse(status_code=400, content={"error": "Medusa result fail", "details": data.get("message")})
        
        return JSONResponse(status_code=res.status_code, content={"error": "Medusa request failed"})
        
    except Exception as e:
        log_debug(f"Exception in add_series: {e}")
        return JSONResponse(status_code=502, content={"error": str(e)})

@app.get("/api/v3/series/lookup")
async def series_lookup(term: Optional[str] = Query(None), api_key: str = Depends(get_medusa_key)):
    if not term: return []
    # Handle both 'tvdb:12345' and '12345'
    clean_term = term.replace("tvdb:", "").strip() 
    try:
        res = await async_client.get("/api/v2/series/lookup", params={"q": clean_term, "indexer": "tvdb"}, headers=medusa_headers(api_key))
        if res.status_code != 200: return []
        return [{
            "title": item.get("title"),
            "tvdbId": extract_clean_integer_id(item),
            "imdbId": item.get("ids", {}).get("imdb", ""),
            "images": [],
            "alternateTitles": [],
            "genres": [],
            "seriesType": "standard",
            "overview": item.get("overview"),
            "year": extract_clean_year(item),
            "remotePoster": item.get("image", ""),
            "added": "2026-01-01T00:00:00Z",
        } for item in res.json()]
    except Exception:
        return []

@app.get("/api/v3/series/{series_id}")
async def get_single_series(series_id: int, api_key: str = Depends(get_medusa_key)):
    if series_id == 0:
        return {"id": 0, "title": "Initialization Stub", "tvdbId": 0, "year": 0, "imdbId": "", "images": [], "alternateTitles": [], "genres": [], "seriesType": "standard", "path": "/tv", "monitored": False, "added": "2026-01-01T00:00:00Z"}
        
    try:
        res = await async_client.get(f"/api/v2/series/{series_id}", headers=medusa_headers(api_key))
        if res.status_code != 200:
            raise HTTPException(status_code=404, detail="Series not found")
            
        show = res.json()
        clean_id = extract_clean_integer_id(show)
        show_year = extract_clean_year(show)
        
        return {
            "id": int(clean_id),
            "title": show.get("title"),
            "tvdbId": int(clean_id),
            "imdbId": show.get("ids", {}).get("imdb", ""),
            "year": show_year,
            "images": [],
            "alternateTitles": [],
            "genres": [],
            "seriesType": "standard",
            "path": show.get("path", "/tv"),
            "monitored": not show.get("paused", False),
            "added": "2026-01-01T00:00:00Z",
        }
    except Exception:
        raise HTTPException(status_code=404, detail="Series not found")

@app.post("/api/v3/series")
async def add_series(payload: SonarrAddSeries, api_key: str = Depends(get_medusa_key)):
    medusa_payload = {
        "config": {"location": f"{payload.rootFolderPath}/{payload.title}", "qualities": [], "paused": not payload.monitored},
        "ids": {"tvdb": payload.tvdbId},
        "selectedIndexer": "tvdb"
    }
    try:
        res = await async_client.post("/api/v2/series", json=medusa_payload, headers=medusa_headers(api_key))
        if res.status_code in [200, 201]:
            new_show = res.json()
            clean_id = extract_clean_integer_id(new_show)
            return {
                "id": int(clean_id),
                "title": payload.title,
                "tvdbId": payload.tvdbId,
                "imdbId": "",
                "year": 0,
                "images": [],
                "alternateTitles": [],
                "genres": [],
                "seriesType": "standard",
                "path": medusa_payload["config"]["location"],
                "monitored": payload.monitored,
                "profileId": payload.profileId,
                "added": "2026-01-01T00:00:00Z",
            }
        return JSONResponse(status_code=res.status_code, content=res.json())
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": str(e)})

@app.get("/api/v3/episode")
async def get_episodes(
    seriesId: Optional[int] = Query(None),
    seriesid: Optional[int] = Query(None),
    includeEpisodeFile: bool = Query(False),
    api_key: str = Depends(get_medusa_key)
):
    target_id = seriesId or seriesid
    log_debug(f"Episode fetch requested for seriesId: {target_id}")
    
    if not target_id:
        log_debug("No seriesId provided, returning empty list.")
        return []

    if not SERIES_ID_MAP:
        log_debug("SERIES_ID_MAP is empty, triggering core_all_series refresh.")
        await core_all_series(api_key)

    # Resolve ID
    medusa_id = SERIES_ID_MAP.get(target_id, target_id)
    log_debug(f"Resolved Sonarr ID {target_id} to Medusa ID/Slug: {medusa_id}")

    try:
        url_path = f"/api/v2/series/{medusa_id}/episodes"
        log_debug(f"Querying Medusa: {url_path}")
        
        res = await async_client.get(url_path, headers=medusa_headers(api_key))
        
        if res.status_code != 200:
            log_debug(f"Medusa returned {res.status_code}. Response: {res.text}")
            return []

        medusa_eps = res.json()
        log_debug(f"Medusa returned {len(medusa_eps)} episodes for {medusa_id}")
        
        translated_episodes = []
        for ep in medusa_eps:
            status = str(ep.get("status", "")).lower()
            has_file = status in ["downloaded", "snatched"]
            
            episode = {
                "id": int(ep.get("id", 0)),
                "seriesId": int(target_id),
                "episodeFileId": int(ep.get("id", 0)) if has_file else 0,
                "seasonNumber": int(ep.get("season", 0)),
                "episodeNumber": int(ep.get("episode", ep.get("number", 0))),
                "title": ep.get("title", ""),
                "overview": ep.get("overview", ""),
                "monitored": True,
                "hasFile": has_file
            }

            if includeEpisodeFile and has_file:
                episode["episodeFile"] = {
                    "id": int(ep.get("id", 0)),
                    "seriesId": int(target_id),
                    "size": 0
                }

            translated_episodes.append(episode)

        return translated_episodes

    except Exception as e:
        log_debug(f"Episode fetch exception: {str(e)}")
        return []

# ---------------------------------------------------------------------------
# 4. CALENDAR, QUEUE, WANTED & HISTORY
# ---------------------------------------------------------------------------
@app.get("/api/v3/calendar")
async def get_calendar(start: str = Query(...), end: str = Query(...), api_key: str = Depends(get_medusa_key)):
    try:
        res = await async_client.get("/api/v2/schedule", headers=medusa_headers(api_key))
        if res.status_code != 200: return []
        
        # Ensure we return a full object with 'series' metadata
        return [{
            "id": int(item.get("id", 0)),
            "seriesId": int(item.get("seriesId", 0)),
            "episodeNumber": item.get("episode"),
            "seasonNumber": item.get("season"),
            "title": item.get("title"),
            "airDateUtc": item.get("airDate"),
            "series": {"title": item.get("show_name", "Unknown")}
        } for item in res.json().get("coming", [])]
    except Exception:
        return []

@app.get("/api/v3/wanted/missing")
async def get_wanted_missing(api_key: str = Depends(get_medusa_key)):
    try:
        res = await async_client.get("/api/v2/schedule", headers=medusa_headers(api_key))
        if res.status_code != 200: return {"page": 1, "pageSize": 20, "totalRecords": 0, "records": []}
        
        data = res.json()
        combined = data.get("missed", []) + data.get("coming", [])
        
        records = [{
            "id": int(item.get("id", idx + 1000)),
            "seriesId": int(item.get("seriesId", 0)),
            "episodeNumber": item.get("episode"),
            "seasonNumber": item.get("season"),
            "title": item.get("title"),
            "airDateUtc": item.get("airDate"),
            "series": {"title": item.get("show_name", "Unknown")},
            "monitored": True
        } for idx, item in enumerate(combined)]
        
        return {"page": 1, "pageSize": len(records) or 20, "totalRecords": len(records), "records": records}
    except Exception:
        return {"page": 1, "pageSize": 20, "totalRecords": 0, "records": []}

@app.get("/api/v3/queue")
async def get_queue(
    page: int = Query(1),
    pageSize: int = Query(20),
    sortKey: str = Query("id"),
    api_key: str = Depends(get_medusa_key)
):
    log_debug(f"Queue requested: page={page}, size={pageSize}")
    # Return a basic structure that indicates no active downloads, 
    # which stops the app from waiting for more pages.
    return {
        "page": page,
        "pageSize": pageSize,
        "totalRecords": 0,
        "records": []
    }

@app.get("/api/v3/queue/status")
async def get_queue_status(api_key: str = Depends(get_medusa_key)):
    # This structure is what Sonarr V3 expects to stop the loading icon
    return {
        "totalCount": 0,
        "count": 0,
        "pageSize": 20,
        "sortKey": "timeleft",
        "unknownQueueItems": 0,
        "queued": 0,
        "downloading": 0,
        "failed": 0,
        "errors": False,
        "warnings": False
    }

@app.get("/api/v3/history")
async def get_history(
    page: int = Query(1), 
    pageSize: int = Query(100), 
    api_key: str = Depends(get_medusa_key)
):
    try:
        # Medusa's history endpoint
        res = await async_client.get("/api/v2/history", headers=medusa_headers(api_key))
        if res.status_code != 200:
            return {"page": 1, "pageSize": pageSize, "totalRecords": 0, "records": []}
            
        data = res.json()
        # Transform Medusa items to match Sonarr's expected history schema
        records = [{
            "id": i + 1,
            "sourceTitle": item.get("show_name", "Unknown"),
            "eventType": item.get("action", "unknown"),
            "date": item.get("date", "2026-01-01T00:00:00Z"),
            "seriesId": int(item.get("series_id", 0)),
            "episodeId": int(item.get("episode_id", 0))
        } for i, item in enumerate(data)]
        
        return {
            "page": page, 
            "pageSize": pageSize, 
            "totalRecords": len(records), 
            "records": records
        }
    except Exception:
        return {"page": 1, "pageSize": pageSize, "totalRecords": 0, "records": []}

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
    elif command.name == "SeriesSearch" and command.seriesId:
        await async_client.post(f"/api/v2/series/{command.seriesId}/actions/force-search", headers=medusa_headers(api_key))
    return {"id": 1000, "name": command.name, "state": "completed"}

@app.get("/api/v3/command/{command_id}")
async def get_command_status(command_id: int, api_key: str = Depends(get_medusa_key)):
    return {"id": command_id, "state": "completed"}
