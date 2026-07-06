import os
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, Header, HTTPException, Query, status, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import httpx

app = FastAPI(title="Sonarr-to-Medusa Universal Proxy", version="3.0.0")

# Environment configurations with fallback defaults
MEDUSA_URL = os.getenv("MEDUSA_URL", "http://localhost:8081")
MEDUSA_API_KEY = os.getenv("MEDUSA_API_KEY", "")
PROXY_API_KEY = os.getenv("PROXY_API_KEY", "super-secret-key")

# Asynchronous HTTP client for non-blocking proxying
async_client = httpx.AsyncClient(base_url=MEDUSA_URL, timeout=15.0)

# ---------------------------------------------------------------------------
# CORE AUTHENTICATION HELPERS
# ---------------------------------------------------------------------------
def verify_auth(x_api_key: str = Header(None)):
    """Validates that incoming traffic matches your specified proxy token."""
    if not x_api_key or x_api_key != PROXY_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid X-Api-Key")
    return x_api_key

def medusa_headers():
    """Generates expected downstream headers for PyMedusa v2 API."""
    return {"x-api-key": MEDUSA_API_KEY, "Content-Type": "application/json"}

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
# 1. SYSTEM & CONFIGURATION ENDPOINTS
# ---------------------------------------------------------------------------
@app.get("/api/v3/system/status", dependencies=[Depends(verify_auth)])
async def get_system_status():
    """Returns a fake system envelope to claim v3/v4 client compatibility."""
    return {
        "version": "3.0.10.1567",
        "buildTime": "2026-01-01T00:00:00Z",
        "isDebug": False,
        "isProduction": True,
        "isAdmin": True,
        "isUserInteractive": False,
        "startupPath": "/app",
        "appData": "/config",
        "osName": "linux",
        "osVersion": "alpine",
        "isNetCore": True,
        "appName": "Sonarr"
    }

@app.get("/api/v3/diskspace", dependencies=[Depends(verify_auth)])
async def get_disk_space():
    """Mock storage status so downstream request tools don't throw allocation warnings."""
    return [{
        "path": "/tv",
        "label": "TV Shows",
        "freeSpace": 500000000000,
        "totalSpace": 1000000000000
    }]

# ---------------------------------------------------------------------------
# 2. PROFILES, TAGS, AND CONFIGURATIONS (Sane Defaults & Emulation)
# ---------------------------------------------------------------------------
@app.get("/api/v3/qualityprofile", dependencies=[Depends(verify_auth)])
async def get_quality_profiles():
    return [
        {"id": 1, "name": "Medusa Managed Profile", "upgradeAllowed": False, "cutoff": 1, "items": []},
        {"id": 2, "name": "HD - 720p/1080p", "upgradeAllowed": False, "cutoff": 2, "items": []}
    ]

@app.get("/api/v3/languageprofile", dependencies=[Depends(verify_auth)])
async def get_language_profiles():
    return [{"id": 1, "name": "English", "cutoff": {"id": 1, "name": "English"}, "languages": [{"language": {"id": 1, "name": "English"}, "allowed": True}]}]

@app.get("/api/v3/rootfolder", dependencies=[Depends(verify_auth)])
async def get_root_folders():
    return [{"id": 1, "path": "/tv", "accessible": True, "freeSpace": 500000000000, "unmappedFolders": []}]

@app.get("/api/v3/tag", dependencies=[Depends(verify_auth)])
async def get_tags(): 
    return []

@app.get("/api/v3/customformat", dependencies=[Depends(verify_auth)])
async def get_custom_formats(): 
    return []  # Medusa doesn't support custom regex release tags the way Sonarr does.

# ---------------------------------------------------------------------------
# 3. SERIES & EPISODE TRANSFORMATION LOGIC
# ---------------------------------------------------------------------------
@app.get("/api/v3/series", dependencies=[Depends(verify_auth)])
async def get_all_series():
    try:
        res = await async_client.get("/api/v2/series", headers=medusa_headers())
        if res.status_code != 200:
            return JSONResponse(status_code=res.status_code, content=res.json())
        
        medusa_shows = res.json()
        sonarr_shows = []
        for show in medusa_shows:
            sonarr_shows.append({
                "id": show.get("id"), 
                "title": show.get("title"),
                "sortTitle": show.get("title", "").lower(),
                "status": "continuing" if show.get("status") == "continuing" else "ended",
                "overview": show.get("overview", ""),
                "tvdbId": show.get("ids", {}).get("tvdb") or show.get("id"),
                "path": show.get("path", "/tv"),
                "profileId": 1,
                "languageProfileId": 1,
                "monitored": not show.get("paused", False),
                "useSceneNumbering": False,
                "seasons": [] 
            })
        return sonarr_shows
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": str(e)})

@app.post("/api/v3/series", dependencies=[Depends(verify_auth)])
async def add_series(payload: SonarrAddSeries):
    """Maps Sonarr's structure into Medusa config settings."""
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
        res = await async_client.post("/api/v2/series", json=medusa_payload, headers=medusa_headers())
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

@app.get("/api/v3/series/lookup", dependencies=[Depends(verify_auth)])
async def series_lookup(term: str = Query(...)):
    """Strips out structural query variables (like tvdb:XXXXX) into normal query elements."""
    query_term = term.split(":")[-1] if term.startswith("tvdb:") else term
    try:
        res = await async_client.get("/api/v2/series/lookup", params={"q": query_term, "indexer": "tvdb"}, headers=medusa_headers())
        if res.status_code != 200: 
            return []
        return [{
            "title": item.get("title"),
            "tvdbId": item.get("ids", {}).get("tvdb"),
            "overview": item.get("overview"),
            "year": item.get("year", 0),
            "remotePoster": item.get("image", "")
        } for item in res.json()]
    except Exception:
        return []

@app.get("/api/v3/episode", dependencies=[Depends(verify_auth)])
async def get_episodes(seriesId: int = Query(...)):
    """Translates individual episode file indexes."""
    try:
        res = await async_client.get(f"/api/v2/series/{seriesId}/episodes", headers=medusa_headers())
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
# 4. CALENDAR, QUEUE & HISTORY (Crucial for Dashboards & Request Apps)
# ---------------------------------------------------------------------------
@app.get("/api/v3/calendar", dependencies=[Depends(verify_auth)])
async def get_calendar(start: str = Query(...), end: str = Query(...)):
    """Pulls incoming shows via Medusa's active scheduler."""
    try:
        res = await async_client.get("/api/v2/schedule", headers=medusa_headers())
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

@app.get("/api/v3/queue", dependencies=[Depends(verify_auth)])
async def get_queue():
    """NOT DIRECTLY LINKABLE: Medusa delegates downstream queue handling to external tools."""
    return {"page": 1, "pageSize": 20, "sortKey": "id", "sortDirection": "descending", "totalRecords": 0, "records": []}

@app.get("/api/v3/history", dependencies=[Depends(verify_auth)])
async def get_history():
    """NOT DIRECTLY LINKABLE: Auditing logs differ systematically from Sonarr data blocks."""
    return {"page": 1, "pageSize": 20, "totalRecords": 0, "records": []}

# ---------------------------------------------------------------------------
# 5. HARDWARE AGENTS (Download clients / Indexers)
# ---------------------------------------------------------------------------
@app.get("/api/v3/downloadclient", dependencies=[Depends(verify_auth)])
async def get_download_clients():
    """NOT DIRECTLY LINKABLE: Safe mock fallback to avoid configuration collision."""
    return []

@app.get("/api/v3/indexer", dependencies=[Depends(verify_auth)])
async def get_indexers():
    """NOT DIRECTLY LINKABLE: Search structures must be maintained via Medusa dashboard."""
    return []

@app.get("/api/v3/metadata", dependencies=[Depends(verify_auth)])
async def get_metadata_consumers(): 
    return []

# ---------------------------------------------------------------------------
# 6. COMMAND ORCHESTRATION ENGINE
# ---------------------------------------------------------------------------
@app.post("/api/v3/command", dependencies=[Depends(verify_auth)])
async def execute_command(command: SonarrCommand):
    """Intercepts orchestration actions and triggers target Medusa update routines."""
    if command.name in ["RefreshSeries", "RescanSeries"] and command.seriesId:
        await async_client.post(f"/api/v2/series/{command.seriesId}/actions/force-update", headers=medusa_headers())
        return {"id": 999, "name": command.name, "state": "completed"}
    
    elif command.name == "SeriesSearch" and command.seriesId:
        await async_client.post(f"/api/v2/series/{command.seriesId}/actions/force-search", headers=medusa_headers())
        return {"id": 998, "name": command.name, "state": "completed"}
        
    return {"id": 1000, "name": command.name, "state": "completed"}

@app.get("/api/v3/command/{command_id}", dependencies=[Depends(verify_auth)])
async def get_command_status(command_id: int):
    return {"id": command_id, "state": "completed"}
