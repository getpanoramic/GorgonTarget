import os
import urllib.parse
import sys
import json
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, Header, HTTPException, Query, status, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from starlette.types import ASGIApp, Scope, Receive, Send
import httpx

# ---------------------------------------------------------------------------
# REFINED PATH & CASE-INSENSITIVE ROUTING MIDDLEWARE (CLEAN LOGS)
# ---------------------------------------------------------------------------
class CaseInsensitiveAPIMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] == "http":
            path = scope.get("path", "")
            method = scope.get("method", "UNKNOWN")
            
            # Print simplified request line instead of heavy header dumps
            print(f"[GorgonTarget] {method} {path}", file=sys.stderr, flush=True)
            
            if path.endswith("/") and len(path) > 1:
                path = path.rstrip("/")
                
            if path.startswith("/api"):
                scope["path"] = path.lower()
            else:
                scope["path"] = path

        await self.app(scope, receive, send)

# ---------------------------------------------------------------------------
# APP INITIALIZATION
# ---------------------------------------------------------------------------
app = FastAPI(title="GorgonTarget Stateless Proxy", version="3.6.0")
app.add_middleware(CaseInsensitiveAPIMiddleware)

MEDUSA_URL = os.getenv("MEDUSA_URL", "http://localhost:8081")
async_client = httpx.AsyncClient(base_url=MEDUSA_URL, timeout=30.0)

# Maps Sonarr proxy IDs -> real Medusa IDs
SERIES_ID_MAP = {}

def log_debug(message: str):
    print(f"[GorgonTarget DEBUG] {message}", file=sys.stderr, flush=True)

# Helper function to generate standard image links for Sonarr clients
def build_sonarr_images(series_id: int) -> List[Dict[str, str]]:
    return [
        {"coverType": "poster", "url": f"/api/v3/mediacover/{series_id}/poster.jpg"},
        {"coverType": "banner", "url": f"/api/v3/mediacover/{series_id}/banner.jpg"},
        {"coverType": "fanart", "url": f"/api/v3/mediacover/{series_id}/fanart.jpg"}
    ]

def parse_medusa_size(size_str: str) -> int:
    """Converts '547.56 GB' or '1.39 TB' to bytes."""
    try:
        if not size_str: return 0
        val, unit = size_str.split()
        val = float(val)
        multipliers = {"GB": 10**9, "TB": 10**12, "MB": 10**6}
        return int(val * multipliers.get(unit.upper(), 1))
    except:
        return 0

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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Missing API Key context."
        )
    return resolved_key

def medusa_headers(api_key: str) -> dict:
    return {"x-api-key": api_key, "Content-Type": "application/json"}

# ---------------------------------------------------------------------------
# ID & VALUE CONVERSION SAFETY FUNCTIONS
# ---------------------------------------------------------------------------
def extract_clean_integer_id(show_node: dict) -> int:
    raw_id = show_node.get("id")
    if isinstance(raw_id, dict):
        raw_id = raw_id.get("medusa") or raw_id.get("tvdb") or raw_id.get("tmdb")
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
# CORE REUSABLE IMPLEMENTATIONS
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
        log_debug(f"Config fallback exception: {str(e)}")

    return {
        "version": medusa_version,
        "startupPath": startup_path,
        "appData": app_data,
        "osName": os_name,
        "osVersion": "alpine" if os_name == "linux" else "NT",
        "isNetCore": True,
        "appName": "Sonarr"
    }

async def core_all_series(api_key: str):
    res = await async_client.get("/api/v2/series", params={"limit": 1000}, headers=medusa_headers(api_key))
    if res.status_code != 200:
        return JSONResponse(status_code=res.status_code, content=res.json())

    medusa_shows = res.json()
    sonarr_shows = []
    SERIES_ID_MAP.clear()

    for show in medusa_shows:
        ids = show.get("ids", {})
        medusa_id = extract_clean_integer_id(show)
        
        indexer = show.get("default_indexer") or show.get("indexer") or "tvdb"
        val = ids.get(indexer) or ids.get("tvdb") or ids.get("tmdb")
        slug_string = f"{indexer}{val}" if val else str(medusa_id)
        
        SERIES_ID_MAP[int(medusa_id)] = slug_string
        
        title = show.get("title", f"Series {medusa_id}")
        raw_path = show.get("path", "")
        
        # Python 3.11 Syntax Fix: Build safe string outside the f-string
        safe_title = title.replace("/", "_").replace("\\", "_")
        path = str(raw_path) if raw_path and raw_path != "/tv" else f"/tv/{safe_title}"

        sonarr_shows.append({
            "id": int(medusa_id),
            "tvdbId": int(ids.get("tvdb")) if ids.get("tvdb") else 0,
            "tmdbId": int(ids.get("tmdb")) if ids.get("tmdb") else 0,
            "imdbId": ids.get("imdb") or "",
            "title": title,
            "sortTitle": title.lower(),
            "status": "continuing" if show.get("status") == "continuing" else "ended",
            "overview": show.get("overview", ""),
            "year": extract_clean_year(show),
            "images": build_sonarr_images(int(medusa_id)),
            "alternateTitles": [],
            "genres": [],
            "seriesType": "standard",
            "path": path,
            "profileId": 1,
            "languageProfileId": 1,
            "monitored": not show.get("paused", False),
            "useSceneNumbering": False,
            "added": "2026-01-01T00:00:00Z",
            "seasons": []
        })

    log_debug(f"OUTBOUND DATASET: Sent {len(sonarr_shows)} series objects with full image specifications.")
    return sonarr_shows

# ---------------------------------------------------------------------------
# MEDIA COVER ASSET PROXY TUNNEL
# ---------------------------------------------------------------------------
@app.get("/api/v3/mediacover/{series_id}/{asset_file}")
async def get_media_cover(series_id: str, asset_file: str, api_key: str = Depends(get_medusa_key)):
    """
    Catches image proxy requests from Prismarr, resolves their asset targets, 
    and fetches the raw byte content dynamically from Medusa.
    """
    asset_lower = asset_file.lower()
    medusa_asset_type = "poster"
    if "banner" in asset_lower:
        medusa_asset_type = "banner"
    elif "fanart" in asset_lower:
        medusa_asset_type = "fanart"

    target_url = f"/api/v2/series/{series_id}/images/{medusa_asset_type}"
    log_debug(f"Proxying visual cover asset: {medusa_asset_type} for series {series_id}")
    
    try:
        response = await async_client.get(target_url, headers=medusa_headers(api_key))
        if response.status_code == 200:
            return StreamingResponse(
                response.iter_bytes(), 
                media_type=response.headers.get("content-type", "image/jpeg")
            )
    except Exception as e:
        log_debug(f"Failed to pull image proxy: {str(e)}")
        
    transparent_pixel = b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff\x21\xf9\x04\x01\x00\x00\x00\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b'
    return StreamingResponse(iter([transparent_pixel]), media_type="image/gif")

# ---------------------------------------------------------------------------
# CORE ROUTING ENDPOINTS
# ---------------------------------------------------------------------------
@app.get("/")
async def root_index():
    return {"status": "running", "service": "GorgonTarget Stateless Proxy"}

@app.get("/api/system/status")
async def get_system_status_v2(api_key: str = Depends(get_medusa_key)):
    return await core_system_status(api_key)

@app.get("/api/series")
@app.get("/api/v3/series")
async def get_all_series_v2(api_key: str = Depends(get_medusa_key)):
    return await core_all_series(api_key)

@app.get("/api/v3/system/status")
async def get_system_status_v3(api_key: str = Depends(get_medusa_key)):
    return await core_system_status(api_key)

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

@app.get("/api/v3/series/lookup")
async def series_lookup(term: Optional[str] = Query(None), api_key: str = Depends(get_medusa_key)):
    if not term: return []
    clean_term = term.replace("tvdb:", "").strip() 
    try:
        res = await async_client.get("/api/v2/series/lookup", params={"q": clean_term, "indexer": "tvdb"}, headers=medusa_headers(api_key))
        if res.status_code != 200: return []
        return [{
            "title": item.get("title"),
            "tvdbId": extract_clean_integer_id(item),
            "imdbId": item.get("ids", {}).get("imdb", ""),
            "images": build_sonarr_images(extract_clean_integer_id(item)),
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
        return {
            "id": int(clean_id),
            "title": show.get("title"),
            "tvdbId": int(clean_id),
            "imdbId": show.get("ids", {}).get("imdb", ""),
            "year": extract_clean_year(show),
            "images": build_sonarr_images(int(clean_id)),
            "alternateTitles": [],
            "genres": [],
            "seriesType": "standard",
            "path": show.get("path", "/tv"),
            "monitored": not show.get("paused", False),
            "added": "2026-01-01T00:00:00Z",
        }
    except Exception:
        raise HTTPException(status_code=404, detail="Series not found")

class SonarrAddSeries(BaseModel):
    title: str
    tvdbId: int
    profileId: int
    rootFolderPath: str
    monitored: bool = True

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
            SERIES_ID_MAP[int(clean_id)] = f"tvdb{payload.tvdbId}"
            return {
                "id": int(clean_id),
                "title": payload.title,
                "tvdbId": payload.tvdbId,
                "imdbId": "",
                "year": 0,
                "images": build_sonarr_images(int(clean_id)),
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
    if not target_id: return []
    if not SERIES_ID_MAP: await core_all_series(api_key)

    medusa_id = SERIES_ID_MAP.get(target_id, target_id)
    try:
        res = await async_client.get(f"/api/v2/series/{medusa_id}/episodes", headers=medusa_headers(api_key))
        if res.status_code != 200: return []

        translated_episodes = []
        for ep in res.json():
            status_str = str(ep.get("status", "")).lower()
            has_file = status_str in ["downloaded", "snatched"]
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
                episode["episodeFile"] = {"id": int(ep.get("id", 0)), "seriesId": int(target_id), "size": 0}
            translated_episodes.append(episode)
        return translated_episodes
    except Exception:
        return []

@app.get("/api/v3/episodefile")
async def get_episode_files(seriesId: Optional[int] = Query(None), seriesid: Optional[int] = Query(None)):
    return []

# ---------------------------------------------------------------------------
# CALENDAR, QUEUE, WANTED & HISTORY TRAFFIC
# ---------------------------------------------------------------------------
@app.get("/api/v3/calendar")
async def get_calendar(start: str = Query(...), end: str = Query(...), api_key: str = Depends(get_medusa_key)):
    try:
        res = await async_client.get("/api/v2/schedule", headers=medusa_headers(api_key))
        if res.status_code != 200: return []
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
        combined = res.json().get("missed", []) + res.json().get("coming", [])
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
async def get_queue(page: int = 1, pageSize: int = 20, api_key: str = Depends(get_medusa_key)):
    return {"page": page, "pageSize": pageSize, "totalRecords": 0, "records": []}

@app.get("/api/v3/queue/status")
async def get_queue_status(api_key: str = Depends(get_medusa_key)):
    return {"totalCount": 0, "count": 0, "pageSize": 20, "sortKey": "timeleft", "unknownQueueItems": 0, "queued": 0, "downloading": 0, "failed": 0, "errors": False, "warnings": False}

@app.get("/api/v3/history")
async def get_history(page: int = 1, pageSize: int = 100, api_key: str = Depends(get_medusa_key)):
    try:
        res = await async_client.get("/api/v2/history", headers=medusa_headers(api_key))
        if res.status_code != 200: return {"page": page, "pageSize": pageSize, "totalRecords": 0, "records": []}
        records = [{
            "id": i + 1,
            "sourceTitle": item.get("show_name", "Unknown"),
            "eventType": item.get("action", "unknown"),
            "date": item.get("date", "2026-01-01T00:00:00Z"),
            "seriesId": int(item.get("series_id", 0)),
            "episodeId": int(item.get("episode_id", 0))
        } for i, item in enumerate(res.json())]
        return {"page": page, "pageSize": pageSize, "totalRecords": len(records), "records": records}
    except Exception:
        return {"page": page, "pageSize": pageSize, "totalRecords": 0, "records": []}

# ---------------------------------------------------------------------------
# HARDWARE & MANAGEMENT AGENTS
# ---------------------------------------------------------------------------
@app.get("/api/v3/metadata")
async def get_metadata_consumers(api_key: str = Depends(get_medusa_key)): return []

class SonarrCommand(BaseModel):
    name: str
    seriesId: Optional[int] = None

@app.post("/api/v3/command")
async def execute_command(command: SonarrCommand, api_key: str = Depends(get_medusa_key)):
    headers = medusa_headers(api_key)
    
    # Mapping Sonarr commands to Medusa internal actions
    if command.name == "RefreshSeries" and command.seriesId:
        await async_client.post(f"/api/v2/series/{command.seriesId}/actions/force-update", headers=headers)
    elif command.name == "RescanSeries" and command.seriesId:
        await async_client.post(f"/api/v2/series/{command.seriesId}/actions/force-search", headers=headers)
    elif command.name == "SeriesSearch" and command.seriesId:
        await async_client.post(f"/api/v2/series/{command.seriesId}/actions/force-search", headers=headers)
    elif command.name == "CheckForUpdates":
        # New: Triggering the system update via Medusa operation API
        await async_client.post("/api/v2/system/operation", json={"command": "check_update"}, headers=headers)
        
    return {"id": 1000, "name": command.name, "state": "completed"}

@app.get("/api/v3/command/{command_id}")
async def get_command_status(command_id: int, api_key: str = Depends(get_medusa_key)):
    return {"id": command_id, "state": "completed"}

# ---------------------------------------------------------------------------
# UPDATED FUNCTIONAL ENDPOINTS
# ---------------------------------------------------------------------------

@app.get("/api/v3/update")
async def get_updates(api_key: str = Depends(get_medusa_key)):
    """Triggers update check and returns status."""
    await async_client.post("/api/v2/system/operation", json={"command": "check_update"}, headers=medusa_headers(api_key))
    return []

@app.get("/api/v3/autotagging")
async def get_autotagging(api_key: str = Depends(get_medusa_key)):
    """Maps Medusa labels to Autotagging UI."""
    res = await async_client.get("/api/v2/labels", headers=medusa_headers(api_key))
    if res.status_code == 200:
        return [{"id": label.get("id"), "label": label.get("name")} for label in res.json()]
    return []

@app.post("/api/v3/autotagging")
async def post_autotagging(payload: dict, api_key: str = Depends(get_medusa_key)):
    # Medusa doesn't have a direct equivalent to 'autotagging'; 
    # if you want to support this, it would map to managing 'Labels'
    return {"status": "success"}

@app.get("/api/v3/system/backup")
async def get_backups(api_key: str = Depends(get_medusa_key)):
    res = await async_client.get("/api/v2/config/backup", headers=medusa_headers(api_key))
    return res.json() if res.status_code == 200 else []

# ---------------------------------------------------------------------------
# FUNCTIONAL MANAGEMENT RELAYS
# ---------------------------------------------------------------------------

@app.get("/api/v3/health")
async def get_health_proxy(api_key: str = Depends(get_medusa_key)):
    """Maps system health status."""
    # Ping the config to check backend responsiveness
    res = await async_client.get("/api/v2/config", headers=medusa_headers(api_key))
    status = "ok" if res.status_code == 200 else "error"
    return [{"source": "Medusa", "type": status, "message": "Backend operational"}]

# ---------------------------------------------------------------------------
# DYNAMIC SCHEMA TRANSLATORS
# ---------------------------------------------------------------------------

@app.get("/api/v3/diskspace")
async def get_diskspace(api_key: str = Depends(get_medusa_key)):
    # Using your provided config endpoint
    res = await async_client.get("/api/v2/config", headers=medusa_headers(api_key))
    data = res.json() if res.status_code == 200 else {}
    
    # Translate Medusa 'diskSpace' to Sonarr 'DiskSpace'
    return [{
        "path": d.get("location"),
        "label": d.get("type"),
        "freeSpace": parse_size_to_bytes(d.get("freeSpace", "0 GB")),
        "totalSpace": 0
    } for d in data.get("diskSpace", {}).get("rootDir", [])]

@app.get("/api/v3/downloadclient")
async def get_download_clients(api_key: str = Depends(get_medusa_key)):
    res = await async_client.get("/api/v2/config", headers=medusa_headers(api_key))
    if res.status_code != 200: 
        return []
    
    data = res.json()
    clients_data = data.get("clients", {})
    output = []
    
    # 1. Map Torrent client (Transmission)
    torrent = clients_data.get("torrents", {})
    if torrent.get("enabled"):
        output.append({
            "id": 1,
            "name": f"Transmission ({torrent.get('method')})",
            "enable": True,
            "protocol": "torrent",
            "implementation": torrent.get("method", "transmission")
        })

    # 2. Map NZB clients (SABnzbd/NZBGet)
    nzb = clients_data.get("nzb", {})
    if nzb.get("enabled"):
        # Check for SABnzbd
        if nzb.get("sabnzbd"):
            output.append({
                "id": 2,
                "name": "SABnzbd",
                "enable": True,
                "protocol": "usenet",
                "implementation": "sabnzbd"
            })
        # Check for NZBGet
        if nzb.get("nzbget"):
            output.append({
                "id": 3,
                "name": "NZBGet",
                "enable": True,
                "protocol": "usenet",
                "implementation": "nzbget"
            })
            
    return output

@app.get("/api/v3/indexer")
async def get_indexers(api_key: str = Depends(get_medusa_key)):
    # Using your provided providers endpoint
    res = await async_client.get("/api/v2/providers", headers=medusa_headers(api_key))
    data = res.json() if res.status_code == 200 else []
    
    return [{"id": i, "name": idx.get("name", "Indexer"), "enableRss": True} for i, idx in enumerate(data)]

import json

@app.get("/api/v3/log")
async def get_logs(page: int = 1, pageSize: int = 100, api_key: str = Depends(get_medusa_key)):
    res = await async_client.get("/api/v2/log", params={"raw": "true", "limit": 1000}, headers=medusa_headers(api_key))
    
    if res.status_code != 200:
        return {"page": page, "pageSize": pageSize, "totalRecords": 0, "records": []}
    
    try:
        # Use simple json.loads, if it fails, try to grab the first valid JSON object
        raw_text = res.text
        # If the API returns multiple JSONs, we take the first valid one or parse as list
        try:
            logs = json.loads(raw_text)
        except json.JSONDecodeError:
            # Fallback: if Medusa returned broken/concatenated JSON, try to fix
            logs = json.loads(raw_text.split('\n')[0]) 
            
        return {
            "page": page,
            "pageSize": pageSize,
            "totalRecords": len(logs),
            "records": [{"time": l.get("time"), "level": l.get("level"), "message": l.get("message")} for l in logs]
        }
    except Exception as e:
        log_debug(f"Log parsing error: {e}")
        return {"page": page, "pageSize": pageSize, "totalRecords": 0, "records": []}

def parse_size_to_bytes(size_str):
    try:
        val, unit = size_str.split()
        mult = {"GB": 10**9, "TB": 10**12, "MB": 10**6}
        return int(float(val) * mult.get(unit, 1))
    except:
        return 0

# ---------------------------------------------------------------------------
# REMAINING STUBS
# ---------------------------------------------------------------------------
@app.get("/api/v3/system/tasks")
@app.get("/api/v3/config")
@app.get("/api/v3/config/ui")
@app.get("/api/v3/config/host")
@app.get("/api/v3/ping")
@app.get("/api/v3/release")
@app.get("/api/v3/manualimport")
@app.get("/api/v3/notification")
@app.get("/api/v3/importlist")
@app.get("/api/v3/delayprofile")
@app.get("/api/v3/naming")
@app.get("/api/v3/blocklist")
async def generic_sonarr_stubs(): 
    return []
