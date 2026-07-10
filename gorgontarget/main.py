import sys
import json
from typing import Optional, List
from fastapi import FastAPI, Header, HTTPException, Query, Depends, Request
from starlette.types import ASGIApp, Scope, Receive, Send
from .settings import settings
from .client import MedusaClient
from .translator import MedusaTranslator
from .models import SonarrAddSeries, SonarrCommand, SonarrSeries, SonarrEpisode, SonarrSystemStatus

class CaseInsensitiveAPIMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] == "http":
            path = scope.get("path", "")
            method = scope.get("method", "UNKNOWN")
            
            # Extract headers safely for diagnostic reporting
            headers = dict(scope.get("headers", []))
            decoded_headers = {}
            for k, v in headers.items():
                try:
                    decoded_headers[k.decode("utf-8").lower()] = v.decode("utf-8")
                except Exception:
                    pass
            
            # Extract the user agent
            ua = decoded_headers.get("user-agent", "Unknown Agent")
            
            # Print detailed request metrics to console
            print(f"\n[GorgonTarget DEBUG] {method} -> {path}", file=sys.stderr, flush=True)
            print(f"[GorgonTarget DEBUG] User-Agent: {ua}", file=sys.stderr, flush=True)
            if decoded_headers:
                print(f"[GorgonTarget DEBUG] Headers: {json.dumps(decoded_headers)}", file=sys.stderr, flush=True)

            # Route sanitization
            if path.endswith("/") and len(path) > 1:
                path = path.rstrip("/")
            if path.startswith("/api"):
                scope["path"] = path.lower()
                
        await self.app(scope, receive, send)

app = FastAPI(title=settings.app_name, version=settings.version)
app.add_middleware(CaseInsensitiveAPIMiddleware)

async def get_client(
    x_api_key: Optional[str] = Header(None),
    apikey: Optional[str] = Query(None),
    api_key: Optional[str] = Query(None)
) -> MedusaClient:
    key = x_api_key or apikey or api_key
    if not key:
        raise HTTPException(status_code=401, detail="Missing API Key context.")
    
    client = MedusaClient(key)
    await client.detect_capabilities()
    return client

# --- CORE INTEGRATION ENDPOINTS ---

@app.get("/")
async def root_index():
    return {"status": "running", "service": settings.app_name}

@app.get("/api/system/status", response_model=SonarrSystemStatus)
@app.get("/api/v3/system/status", response_model=SonarrSystemStatus)
async def get_system_status(client: MedusaClient = Depends(get_client)):
    config = await client.get_system_config()
    main_cfg = config.get("main", {}) or config.get("app", {})
    return SonarrSystemStatus(
        version=main_cfg.get("version", "3.0.10.1567"),
        startupPath=main_cfg.get("rootDir", "/app"),
        appData=main_cfg.get("dataDir", "/config"),
        osName="windows" if "\\" in main_cfg.get("rootDir", "") else "linux",
        osVersion="NT" if "\\" in main_cfg.get("rootDir", "") else "alpine"
    )

@app.get("/api/v3/series", response_model=List[SonarrSeries])
async def get_series(client: MedusaClient = Depends(get_client)):
    medusa_shows = await client.get_all_series()
    return [MedusaTranslator.to_sonarr_series(show) for show in medusa_shows]

@app.get("/api/v3/series/{series_id}", response_model=SonarrSeries)
async def get_single_series(series_id: int, client: MedusaClient = Depends(get_client)):
    # Diagnostic print to check lookup values directly
    print(f"[GorgonTarget] Fetching explicit profile context for Series ID: {series_id}", file=sys.stderr, flush=True)
    
    show = await client.get_series_by_id(series_id)
    if not show:
        # Fallback Strategy: If an exact lookup by string mapping fails, search list collections
        all_shows = await client.get_all_series()
        for s in all_shows:
            # Check matching variations against TVDB markers
            tvdb_obj = s.get("id", {}) or s.get("ids", {})
            if str(tvdb_obj.get("tvdb")) == str(series_id) or str(s.get("indexerId")) == str(series_id):
                return MedusaTranslator.to_sonarr_series(s)
        
        # If absolutely missing, stub a fallback response using the requested ID to avoid blocking UI rendering
        return SonarrSeries(
            id=series_id,
            title=f"Medusa Show {series_id}",
            tvdbId=series_id,
            path=f"/tv/Show_{series_id}",
            monitored=True
        )
    return MedusaTranslator.to_sonarr_series(show)

@app.post("/api/v3/series", response_model=SonarrSeries)
async def add_series(payload: SonarrAddSeries, client: MedusaClient = Depends(get_client)):
    print(f"[GorgonTarget] Intercepted Add Series Payload: {payload.model_dump_json()}", file=sys.stderr, flush=True)
    result = await client.add_series(
        payload.tvdbId, payload.rootFolderPath, payload.title, payload.monitored
    )
    if not result:
        raise HTTPException(status_code=502, detail="Failed to add series to Medusa")
    
    return SonarrSeries(
        id=int(payload.tvdbId),
        title=payload.title,
        tvdbId=payload.tvdbId,
        path=payload.rootFolderPath,
        monitored=payload.monitored
    )

@app.get("/api/v3/episode", response_model=List[SonarrEpisode])
async def get_episodes(
    seriesId: Optional[int] = Query(None),
    seriesid: Optional[int] = Query(None),
    client: MedusaClient = Depends(get_client)
):
    target_id = seriesId or seriesid
    if not target_id:
        return []
    
    eps = await client.get_episodes(target_id)
    return [MedusaTranslator.to_sonarr_episode(ep, target_id) for ep in eps]

@app.get("/api/v3/episodefile")
async def get_episode_files(seriesId: Optional[int] = Query(None), seriesid: Optional[int] = Query(None)):
    return []

@app.post("/api/v3/command")
async def execute_command(command: SonarrCommand, client: MedusaClient = Depends(get_client)):
    print(f"[GorgonTarget] Received POST command request: {command.name}", file=sys.stderr, flush=True)
    return {"id": 1000, "name": command.name, "state": "completed"}

@app.get("/api/v3/command")
async def get_active_commands():
    return []

# --- TRAFFIC ENDPOINTS ---

@app.get("/api/v3/queue")
async def get_queue_records(page: int = 1, pageSize: int = 50):
    return {"page": page, "pageSize": pageSize, "totalRecords": 0, "records": []}

@app.get("/api/v3/queue/status")
async def get_queue_status():
    return {"queuedCount": 0, "records": []}

@app.get("/api/v3/history")
async def get_history(
    page: int = 1,
    pageSize: int = 100,
    sortKey: str = "date",
    sortDirection: str = "descending"
):
    return {
        "page": page,
        "pageSize": pageSize,
        "sortKey": sortKey,
        "sortDirection": sortDirection,
        "totalRecords": 0,
        "records": []
    }

@app.get("/api/v3/wanted/missing")
async def get_wanted_missing(
    page: int = 1,
    pageSize: int = 200,
    sortKey: str = "airDateUtc",
    sortDirection: str = "descending"
):
    return {
        "page": page,
        "pageSize": pageSize,
        "sortKey": sortKey,
        "sortDirection": sortDirection,
        "totalRecords": 0,
        "records": []
    }

@app.get("/api/v3/calendar")
async def get_calendar(start: Optional[str] = None, end: Optional[str] = None):
    return []

# --- STATIC COMPATIBILITY STUBS ---

@app.get("/api/v3/tag")
async def get_tags():
    return []

@app.get("/api/v3/diskspace")
async def get_disk_space(): 
    return [{"path": "/tv", "label": "TV Shows", "freeSpace": 500000000000, "totalSpace": 1000000000000}]

@app.get("/api/v3/qualityprofile")
async def get_quality_profiles(): 
    return [{"id": 1, "name": "Medusa Managed Profile", "upgradeAllowed": False, "cutoff": 1, "items": []}]

@app.get("/api/v3/languageprofile")
async def get_language_profiles(): 
    return [{"id": 1, "name": "English", "cutoff": {"id": 1, "name": "English"}, "languages": [{"language": {"id": 1, "name": "English"}, "allowed": True}]}]

@app.get("/api/v3/rootfolder")
async def get_root_folders(): 
    return [{"id": 1, "path": "/tv", "accessible": True, "freeSpace": 500000000000, "unmappedFolders": []}]

@app.get("/api/v3/system/tasks")
@app.get("/api/v3/system/backup")
@app.get("/api/v3/config")
@app.get("/api/v3/config/ui")
@app.get("/api/v3/config/host")
@app.get("/api/v3/config/downloadclient")
@app.get("/api/v3/config/indexer")
@app.get("/api/v3/health")
@app.get("/api/v3/ping")
@app.get("/api/v3/log")
@app.get("/api/v3/release")
@app.get("/api/v3/manualimport")
@app.get("/api/v3/notification")
@app.get("/api/v3/importlist")
@app.get("/api/v3/delayprofile")
@app.get("/api/v3/naming")
@app.get("/api/v3/blocklist")
async def generic_sonarr_stubs(): 
    return []
