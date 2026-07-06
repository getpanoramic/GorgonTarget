import os
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, Header, HTTPException, Query, status, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import httpx

app = FastAPI(title="GorgonTarget Stateless Proxy", version="3.1.0")

# The only required environment configuration is the backend URL
MEDUSA_URL = os.getenv("MEDUSA_URL", "http://localhost:8081")

# Asynchronous HTTP client for non-blocking proxying
async_client = httpx.AsyncClient(base_url=MEDUSA_URL, timeout=15.0)

# ---------------------------------------------------------------------------
# DYNAMIC AUTHENTICATION HELPER
# ---------------------------------------------------------------------------
def get_medusa_key(x_api_key: str = Header(None)) -> str:
    """
    Extracts the incoming API key sent by the Sonarr client.
    This key is treated as the source of truth and forwarded to Medusa.
    """
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Missing X-Api-Key header from Sonarr client."
        )
    return x_api_key

def medusa_headers(api_key: str) -> dict:
    """Generates expected downstream headers dynamically using the passed key."""
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
# 1. SYSTEM & CONFIGURATION ENDPOINTS
# ---------------------------------------------------------------------------
@app.get("/api/v3/system/status", dependencies=[Depends(get_medusa_key)])
async def get_system_status():
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

@app.get("/api/v3/diskspace", dependencies=[Depends(get_medusa_key)])
async def get_disk_space():
    return [{
        "path": "/tv",
        "label": "TV Shows",
        "freeSpace": 500000000000,
        "totalSpace": 1000000000000
    }]

# ---------------------------------------------------------------------------
# 2. PROFILES, TAGS, AND CONFIGURATIONS (Sane Defaults & Emulation)
# ---------------------------------------------------------------------------
@app.get("/api/v3/qualityprofile", dependencies=[Depends(get_medusa_key)])
async def get_quality_profiles():
    return [
        {"id": 1, "name": "Medusa Managed Profile", "upgradeAllowed": False, "cutoff": 1, "items": []},
        {"id": 2, "name": "HD - 720p/1080p", "upgradeAllowed": False, "cutoff": 2, "items": []}
    ]

@app.get("/api/v3/languageprofile", dependencies=[Depends(get_medusa_key)])
async def get_language_profiles():
    return [{"id": 1, "name": "English", "cutoff": {"id": 1, "name": "English"}, "languages": [{"language": {"id": 1, "name": "English"}, "allowed": True}]}]

@app.get("/api/v3/rootfolder", dependencies=[Depends(get_medusa_key)])
async def get_root_folders():
    return [{"id": 1, "path": "/tv", "accessible": True, "freeSpace": 500000000000, "unmappedFolders": []}]

@app.get("/api/v3/tag", dependencies=[Depends(get_medusa_key)])
async def get_tags(): 
    return []

@app.get("/api/v3/customformat", dependencies=[Depends(get_medusa_key)])
async def get_custom_formats(): 
    return []

# ---------------------------------------------------------------------------
# 3. SERIES & EPISODE TRANSFORMATION LOGIC (Dynamic Tokens)
# ---------------------------------------------------------------------------
@app.get("/api/v3/series")
async def get_all_series(api_key: str = Depends(get_medusa_key)):
    try:
        res = await async_client.get("/api/v2/series", headers=medusa_headers(api_key))
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

@app.post("/api/v3/series")
async def add_series(payload: SonarrAddSeries, api_key: str = Depends(get_medusa_key)):
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
async def series_lookup(term: str = Query(...), api_key: str = Depends(get_medusa_key)):
    query_term = term.split(":")[-1] if term.startswith("tvdb:") else term
    try:
        res = await async_client.get("/api/v2/series/lookup", params={"q": query_term, "indexer": "tvdb"}, headers=medusa_headers(api_key))
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

@app.get("/api/v3/episode")
async def get_episodes(seriesId: int = Query(...), api_key: str = Depends(get_medusa_key)):
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
# 4. CALENDAR, QUEUE & HISTORY
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

@app.get("/api/v3/queue", dependencies=[Depends(get_medusa_key)])
async def get_queue():
    return {"page": 1, "pageSize": 20, "sortKey": "id", "sortDirection": "descending", "totalRecords": 0, "records": []}

@app.get("/api/v3/history", dependencies=[Depends(get_medusa_key)])
async def get_history():
    return {"page": 1, "pageSize": 20, "totalRecords": 0, "records": []}

# ---------------------------------------------------------------------------
# 5. HARDWARE AGENTS
# ---------------------------------------------------------------------------
@app.get("/api/v3/downloadclient", dependencies=[Depends(get_medusa_key)])
async def get_download_clients(): return []

@app.get("/api/v3/indexer", dependencies=[Depends(get_medusa_key)])
async def get_indexers(): return []

@app.get("/api/v3/metadata", dependencies=[Depends(get_medusa_key)])
async def get_metadata_consumers(): return []

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

@app.get("/api/v3/command/{command_id}", dependencies=[Depends(get_medusa_key)])
async def get_command_status(command_id: int):
    return {"id": command_id, "state": "completed"}
