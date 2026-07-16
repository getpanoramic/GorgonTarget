import os
import urllib.parse
import sys
import json
import re
import time
from datetime import datetime
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, Header, HTTPException, Query, status, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from starlette.types import ASGIApp, Scope, Receive, Send
import httpx

from .settings import settings
from .cache import series_map_cache, capability_cache, series_list_cache
from .models import SonarrAddSeries, SonarrCommand, SonarrSeries, SonarrEpisode, SonarrSystemStatus
from .translator import MedusaTranslator
from .client import MedusaClient

# Shared HTTP client for proxying
async_client = httpx.AsyncClient(base_url=settings.medusa_url, timeout=settings.timeout)

SERIES_ID_MAP = {}

# ADD THIS: Persistent registry for command tracking
COMMAND_REGISTRY = {}

# ---------------------------------------------------------------------------
# PATH NORMALIZATION MIDDLEWARE (Fixes double slashes)
# ---------------------------------------------------------------------------
class PathNormalizationMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] == "http":
            path = scope.get("path", "")
            
            # Print simplified request line
            print(f"[Middleware DEBUG] Incoming path: {path}", file=sys.stderr, flush=True)
            
            # Collapse double slashes and double-prefixing
            new_path = path.replace("//", "/")
            
            # Robustly collapse redundant API prefixes
            while "/api/api/" in new_path:
                new_path = new_path.replace("/api/api/", "/api/")
            while "/api/v3/api/v3/" in new_path:
                new_path = new_path.replace("/api/v3/api/v3/", "/api/v3/")
            
            scope["path"] = new_path.lower()
            print(f"[Middleware DEBUG] Normalized path: {new_path}", file=sys.stderr, flush=True)

        await self.app(scope, receive, send)

# ---------------------------------------------------------------------------
# APP INITIALIZATION
# ---------------------------------------------------------------------------
app = FastAPI(title="GorgonTarget Stateless Proxy", version="3.6.0")
app.add_middleware(PathNormalizationMiddleware)

MEDUSA_URL = settings.medusa_url
async_client = httpx.AsyncClient(base_url=MEDUSA_URL, timeout=settings.timeout)

# Maps Sonarr proxy IDs -> real Medusa IDs
SERIES_ID_MAP = {}

def log_debug(message: str):
    print(f"[GorgonTarget DEBUG] {message}", file=sys.stderr, flush=True)

# Helper function to generate standard image links for Sonarr clients
def build_sonarr_images(series_id: int, api_key: str = "") -> List[Dict[str, str]]:
    key_param = f"?api_key={api_key}" if api_key else ""
    return [
        {"coverType": "poster", "url": f"/mediacover/{series_id}/poster-500.jpg{key_param}"},
        {"coverType": "banner", "url": f"/mediacover/{series_id}/banner-500.jpg{key_param}"},
        {"coverType": "fanart", "url": f"/mediacover/{series_id}/fanart-500.jpg{key_param}"}
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
    client = MedusaClient(api_key)
    medusa_config = await client.get_system_config()
    
    medusa_version = "3.0.10.1567"
    os_name = "linux"
    startup_path = "/app"
    app_data = "/config"
    
    if medusa_config:
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
    cached = await series_list_cache.get("all_series")
    if cached:
        log_debug("Returning cached translated series dataset.")
        return cached

    client = MedusaClient(api_key)
    medusa_shows = await client.get_all_series()
    
    sonarr_shows = []
    for show in medusa_shows:
        series_obj = MedusaTranslator.to_sonarr_series(show, api_key=api_key)
        log_debug(f"Translating show: {series_obj.title}, images: {series_obj.images}")
        sonarr_shows.append(series_obj.dict())

    log_debug(f"OUTBOUND DATASET: Sent {len(sonarr_shows)} series objects with full image specifications.")
    await series_list_cache.set("all_series", sonarr_shows)
    return sonarr_shows

# ---------------------------------------------------------------------------
# MEDIA COVER ASSET PROXY TUNNEL
# ---------------------------------------------------------------------------
@app.get("/api/v3/release")
async def get_releases(episodeId: int = Query(...), api_key: str = Depends(get_medusa_key)):
    client = MedusaClient(api_key)
    
    # 1. Fetch all series to search for the episode
    shows = await client.get_all_series()
    
    # 2. Find the series/episode
    found_ep = None
    for show in shows:
        series_id = extract_clean_integer_id(show)
        episodes = await client.get_episodes(series_id)
        for ep in episodes:
            translated = MedusaTranslator.to_sonarr_episode(ep, series_id)
            if translated.id == episodeId:
                found_ep = (show, translated)
                break
        if found_ep: break
    
    if not found_ep:
        return []
    
    show, ep = found_ep
    slug = await series_map_cache.get(f"map_{extract_clean_integer_id(show)}") or str(extract_clean_integer_id(show))
    
    # 3. Dynamic search across all providers
    providers = await client.get_indexers()
    releases = []
    for provider in providers:
        p_name = provider.get("name")
        if not p_name: continue
        
        search_url = f"/api/v2/providers/{p_name}/results?showslug={slug}&season={ep.seasonNumber}&episode={ep.episodeNumber}&limit=100&page=1"
        res = await async_client.get(search_url, headers=medusa_headers(api_key))
        
        if res.status_code == 200:
            for item in res.json():
                releases.append({
                    "guid": item.get("hash", ""),
                    "title": item.get("name", "Unknown Release"),
                    "size": parse_medusa_size(item.get("size", "0 B")),
                    "indexerId": 1,
                    "releaseWeight": 1
                })
    return releases

@app.get("/api/v3/mediacover/{series_id}/{asset_file}")
async def get_media_cover(
    series_id: str, 
    asset_file: str, 
    api_key: Optional[str] = Query(None)
):
    """
    Catches image proxy requests. Accepts API key as a query parameter 
    to properly authenticate with the Medusa backend.
    """
    effective_key = api_key or os.getenv("DEFAULT_MEDUSA_API_KEY", "")
    
    asset_lower = asset_file.lower()
    
    # Asset mapping
    medusa_asset_type = "poster"
    if "banner" in asset_lower:
        medusa_asset_type = "banner"
    elif "fanart" in asset_lower:
        medusa_asset_type = "fanart"
    elif "poster" in asset_lower:
        medusa_asset_type = "poster"

    # Resolve the series slug from the cache
    slug = await series_map_cache.get(f"map_{series_id}") or series_id

    # Construct the URL dynamically using the configured MEDUSA_URL
    target_url = f"/api/v2/series/{slug}/asset/{medusa_asset_type}"
    log_debug(f"Proxying visual cover asset: {medusa_asset_type} for series {series_id} (slug: {slug})")

    try:
        # Fetch using shared async_client, passing API key in headers
        response = await async_client.get(target_url, headers=medusa_headers(effective_key))
        if response.status_code == 200:
            return StreamingResponse(
                response.iter_bytes(), 
                media_type=response.headers.get("content-type", "image/jpeg")
            )
        else:
            log_debug(f"Medusa returned status {response.status_code} for {target_url}")
            
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

# Helper to ensure all image URLs are fully qualified absolute URLs pointing to this proxy
def apply_absolute_urls(data: Any, request: Request) -> Any:
    # Dynamically detect the base URL from the incoming request (the proxy's host)
    base_url = str(request.base_url).rstrip('/')
    
    def _fix_item(item: dict):
        if "images" in item:
            for img in item["images"]:
                # If the URL is already fully qualified, leave it.
                # Otherwise, prepend the proxy's base URL.
                if "url" in img and not img["url"].startswith("http"):
                    path = img["url"].lstrip("/")
                    img["url"] = f"{base_url}/{path}"
                
                if "remoteUrl" in img and not img["remoteUrl"].startswith("http"):
                    path_rem = img["remoteUrl"].lstrip("/")
                    img["remoteUrl"] = f"{base_url}/{path_rem}"
        
        if "remotePoster" in item and item["remotePoster"] and not item["remotePoster"].startswith("http"):
            path_post = item["remotePoster"].lstrip("/")
            item["remotePoster"] = f"{base_url}/{path_post}"
        return item

    if isinstance(data, list):
        return [_fix_item(item) for item in data]
    elif isinstance(data, dict):
        return _fix_item(data)
    return data

@app.get("/api/series")
@app.get("/api/v3/series")
async def get_all_series_v2(request: Request, api_key: str = Depends(get_medusa_key)):
    user_agent = request.headers.get("user-agent", "unknown")
    log_debug(f"User-Agent: {user_agent}")
    data = await core_all_series(api_key)
    return apply_absolute_urls(data, request)

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
    # Return a schema-compliant response
    return [{
        "id": 1,
        "path": "/tv",
        "accessible": True,
        "freeSpace": 500000000000,
        "unmappedFolders": []
    }]

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
async def series_lookup(request: Request, term: Optional[str] = Query(None), api_key: str = Depends(get_medusa_key)):
    if not term: return []
    clean_term = term.replace("tvdb:", "").strip() 
    try:
        res = await async_client.get("/api/v2/series/lookup", params={"q": clean_term, "indexer": "tvdb"}, headers=medusa_headers(api_key))
        if res.status_code != 200: return []
        data = [{
            "title": item.get("title"),
            "tvdbId": extract_clean_integer_id(item),
            "imdbId": item.get("ids", {}).get("imdb", ""),
            "images": build_sonarr_images(extract_clean_integer_id(item), api_key=api_key),
            "alternateTitles": [],
            "genres": [],
            "seriesType": "standard",
            "overview": item.get("overview"),
            "year": extract_clean_year(item),
            "remotePoster": f"/api/v3/mediacover/{extract_clean_integer_id(item)}/poster-500.jpg",
            "added": "2026-01-01T00:00:00Z",
        } for item in res.json()]
        return apply_absolute_urls(data, request)
    except Exception:
        return []

@app.get("/api/v3/series/{series_id}")
async def get_single_series(request: Request, series_id: int, api_key: str = Depends(get_medusa_key)):
    if series_id == 0:
        return {"id": 0, "title": "Initialization Stub", "tvdbId": 0, "year": 0, "imdbId": "", "images": [], "alternateTitles": [], "genres": [], "seriesType": "standard", "path": "/tv", "monitored": False, "added": "2026-07-16T12:01:19.954Z", "seasons": [], "statistics": {"seasonCount": 0, "episodeFileCount": 0, "episodeCount": 0, "totalEpisodeCount": 0, "sizeOnDisk": 0}}
    
    client = MedusaClient(api_key)
    show = await client.get_series_by_id(series_id)
    if not show:
        raise HTTPException(status_code=404, detail="Series not found")
        
    # Build comprehensive SeriesResource
    series_dict = {
        "id": series_id,
        "title": show.get("title", "Unknown"),
        "alternateTitles": [],
        "sortTitle": show.get("title", "").lower(),
        "status": "continuing",
        "ended": False,
        "profileName": "Medusa Profile",
        "overview": show.get("overview", ""),
        "nextAiring": None,
        "previousAiring": None,
        "network": "Medusa",
        "airTime": None,
        "images": build_sonarr_images(series_id, api_key),
        "originalLanguage": {"id": 1, "name": "English"},
        "remotePoster": None,
        "seasons": [{"seasonNumber": 1, "monitored": True, "statistics": {"episodeFileCount": 0, "episodeCount": 0, "totalEpisodeCount": 0, "sizeOnDisk": 0, "percentOfEpisodes": 0}, "images": []}],
        "year": extract_clean_year(show),
        "path": show.get("location", "/tv"),
        "qualityProfileId": 1,
        "seasonFolder": True,
        "monitored": True,
        "monitorNewItems": "all",
        "useSceneNumbering": False,
        "runtime": 30,
        "tvdbId": series_id,
        "tvRageId": 0,
        "tvMazeId": 0,
        "tmdbId": 0,
        "firstAired": None,
        "lastAired": None,
        "seriesType": "standard",
        "cleanTitle": show.get("title", "").lower(),
        "imdbId": "",
        "titleSlug": show.get("title", "").lower().replace(" ", "-"),
        "rootFolderPath": "/tv",
        "folder": show.get("title", ""),
        "certification": None,
        "genres": [],
        "tags": [],
        "added": "2026-07-16T12:01:19.954Z",
        "addOptions": {"ignoreEpisodesWithFiles": True, "ignoreEpisodesWithoutFiles": True, "monitor": "all", "searchForMissingEpisodes": True, "searchForCutoffUnmetEpisodes": True},
        "ratings": {"votes": 0, "value": 0.0},
        "statistics": {"seasonCount": 1, "episodeFileCount": 0, "episodeCount": 0, "totalEpisodeCount": 0, "sizeOnDisk": 0, "percentOfEpisodes": 0},
        "episodesChanged": False
    }
        
    log_debug(f"Returning series details for {series_id}")
    return apply_absolute_urls(series_dict, request)

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
                "images": build_sonarr_images(int(clean_id), api_key=api_key),
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
    episodeIds: Optional[List[int]] = Query(None),
    includeEpisodeFile: bool = Query(False),
    api_key: str = Depends(get_medusa_key)
):
    client = MedusaClient(api_key)
    
    # If episode IDs are explicitly requested, we need to find them across all series
    if episodeIds:
        # Optimization: cache might be needed here, but for now we follow existing pattern
        shows = await client.get_all_series()
        all_translated_episodes = []
        for show in shows:
            s_id = extract_clean_integer_id(show)
            medusa_episodes = await client.get_episodes(s_id)
            for ep in medusa_episodes:
                translated = MedusaTranslator.to_sonarr_episode(ep, s_id)
                if translated.id in episodeIds:
                    episode_dict = translated.dict()
                    if not includeEpisodeFile:
                        episode_dict.pop("episodeFile", None)
                    all_translated_episodes.append(episode_dict)
        return all_translated_episodes
    
    # Legacy series-based lookup
    target_id = seriesId or seriesid
    if not target_id: return []
    
    medusa_episodes = await client.get_episodes(target_id)
    
    translated_episodes = []
    for ep in medusa_episodes:
        episode = MedusaTranslator.to_sonarr_episode(ep, target_id).dict()
        if not includeEpisodeFile:
            episode.pop("episodeFile", None)
        translated_episodes.append(episode)
        
    return translated_episodes

@app.get("/api/v3/episode/{episode_id}")
async def get_single_episode(episode_id: int, includeEpisodeFile: bool = Query(False), api_key: str = Depends(get_medusa_key)):
    log_debug(f"get_single_episode requested for ID: {episode_id}")
    client = MedusaClient(api_key)
    # Fetch all series to search for the episode
    shows = await client.get_all_series()
    
    for show in shows:
        series_id = extract_clean_integer_id(show)
        episodes = await client.get_episodes(series_id)
        for ep in episodes:
            translated = MedusaTranslator.to_sonarr_episode(ep, series_id)
            if translated.id == episode_id:
                ep_dict = translated.dict()
                
                # Construct a more complete EpisodeResource object
                compliant_ep = {
                    "id": ep_dict.get("id", episode_id),
                    "seriesId": ep_dict.get("seriesId", series_id),
                    "tvdbId": ep_dict.get("tvdbId", 0),
                    "episodeFileId": ep_dict.get("episodeFileId", 0),
                    "seasonNumber": ep_dict.get("seasonNumber", 0),
                    "episodeNumber": ep_dict.get("episodeNumber", 0),
                    "title": ep_dict.get("title", "Unknown"),
                    "airDate": ep_dict.get("airDate"),
                    "airDateUtc": ep_dict.get("airDateUtc"),
                    "runtime": ep_dict.get("runtime", 0),
                    "hasFile": ep_dict.get("hasFile", False),
                    "monitored": ep_dict.get("monitored", True)
                }

                # Include episodeFile if requested and available
                if includeEpisodeFile and ep_dict.get("episodeFile"):
                    ef = ep_dict["episodeFile"]
                    compliant_ep["episodeFile"] = {
                        "id": ef.get("id", 0),
                        "seriesId": series_id,
                        "seasonNumber": ef.get("seasonNumber", compliant_ep["seasonNumber"]),
                        "relativePath": ef.get("relativePath", ""),
                        "path": ef.get("path", ""),
                        "size": ef.get("size", 0),
                        "dateAdded": ef.get("dateAdded", "2026-01-01T00:00:00Z"),
                        "quality": compliant_ep.get("quality", {"quality": {"id": 1, "name": "Unknown"}, "revision": {"version": 1, "real": 0, "isRepack": False}})
                    }

                log_debug(f"get_single_episode returning: {compliant_ep}")
                return compliant_ep
    
    log_debug(f"get_single_episode: Episode {episode_id} not found.")
    raise HTTPException(status_code=404, detail="Episode not found")

@app.get("/api/v3/episodefile")
async def get_episode_files(
    seriesId: Optional[int] = Query(None), 
    seriesid: Optional[int] = Query(None),
    api_key: str = Depends(get_medusa_key)
):
    log_debug(f"get_episode_files requested with seriesId={seriesId}, seriesid={seriesid}")
    target_id = seriesId or seriesid
    if not target_id: 
        log_debug("get_episode_files called without a valid seriesId, returning empty.")
        return []
    
    client = MedusaClient(api_key)
    medusa_episodes = await client.get_episodes(target_id)
    
    episode_files = []
    for ep in medusa_episodes:
        status = str(ep.get("status", "")).lower()
        if status in ["downloaded", "snatched"]:
            ep_id = extract_clean_integer_id({"id": ep.get("id")})
            episode_files.append({
                "id": ep_id,
                "seriesId": target_id,
                "seasonNumber": int(ep.get("season", 0)),
                "relativePath": ep.get("location", ""),
                "path": ep.get("location", ""),
                "size": parse_medusa_size(ep.get("size", "0 B")),
                "dateAdded": ep.get("date", "2026-01-01T00:00:00Z")
            })
    log_debug(f"get_episode_files returning {len(episode_files)} files for series {target_id}")
    return episode_files

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
        if res.status_code != 200: 
            log_debug(f"Wanted missing fetch failed: {res.status_code}")
            return {"page": 1, "pageSize": 20, "totalRecords": 0, "records": []}
        
        data = res.json()
        log_debug(f"Wanted missing raw data: {data}")
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
    except Exception as e:
        log_debug(f"Wanted missing exception: {str(e)}")
        return {"page": 1, "pageSize": 20, "totalRecords": 0, "records": []}

@app.get("/api/v3/queue")
async def get_queue(page: int = 1, pageSize: int = 20, api_key: str = Depends(get_medusa_key)):
    return {"page": page, "pageSize": pageSize, "totalRecords": 0, "records": []}

@app.get("/api/v3/queue/status")
async def get_queue_status(api_key: str = Depends(get_medusa_key)):
    return {"totalCount": 0, "count": 0, "pageSize": 20, "sortKey": "timeleft", "unknownQueueItems": 0, "queued": 0, "downloading": 0, "failed": 0, "errors": False, "warnings": False}

@app.get("/api/v3/history")
async def get_history(
    page: int = Query(1), 
    pageSize: int = Query(100),
    seriesIds: Optional[str] = Query(None), # Comma-separated IDs
    includeEpisode: bool = Query(False),
    api_key: str = Depends(get_medusa_key)
):
    try:
        # Resolve requested series IDs
        target_series_ids = set()
        if seriesIds:
            target_series_ids = {int(i.strip()) for i in seriesIds.split(",") if i.strip().isdigit()}
            
        # Medusa's history endpoint with specific query params
        params = {
            "page": page,
            "limit": pageSize,
            "sort": '[{"field":"date","type":"desc"}]',
            "filter": "{}",
            "compact": "true"
        }
        res = await async_client.get("/api/v2/history", params=params, headers=medusa_headers(api_key))
        if res.status_code != 200:
            log_debug(f"History fetch failed: {res.status_code}")
            return {"page": 1, "pageSize": pageSize, "totalRecords": 0, "records": []}
            
        data = res.json()
        log_debug(f"History raw data received (count: {len(data)}): {data}")
        
        # Filter and transform
        filtered_records = []
        
        # ... (keep helper functions map_event_type, parse_date, extract_id_from_str)
        
        # Add a proper date parsing helper for sorting
        def parse_date_for_sort(date_int: int) -> datetime:
            try:
                return datetime.strptime(str(date_int), '%Y%m%d%H%M%S')
            except:
                return datetime(2026, 1, 1)

        # Before transforming, sort the raw data to ensure chronological order from Medusa
        # Medusa's history seems to be naturally older-to-newer or unordered, 
        # but let's sort descending by actionDate.
        data.sort(key=lambda x: parse_date_for_sort(x.get("actionDate", 0)), reverse=True)

        for i, item in enumerate(data):
            # ... (rest of the transformation logic remains the same)
            # Extract identifiers
            series_id = extract_id_from_str(item.get("series", "0"))
            raw_episode_id = item.get("episode_id", 0)
            show_title = item.get("showTitle", "Unknown")
            season = item.get("season", 0)
            episode = item.get("episode", 0)
            
            # If episode_id is missing, use the unique history item id as a proxy
            episode_id = int(raw_episode_id) if raw_episode_id else int(item.get("id", i + 1))
            
            if target_series_ids and series_id not in target_series_ids:
                continue
                
            filtered_records.append({
                "id": int(item.get("id", i + 1)),
                "episodeId": episode_id,
                "seriesId": series_id,
                "sourceTitle": show_title,
                "eventType": "grabbed" if item.get("statusName") == "Snatched" else "downloadFolderImported",
                "date": parse_date(item.get("actionDate", 0)),
                "quality": {
                    "quality": {
                        "id": int(item.get("quality", 0)),
                        "name": "Unknown",
                        "source": "unknown",
                        "resolution": 0
                    },
                    "revision": {"version": 1, "real": 0, "isRepack": False}
                },
                "languages": [{"id": 1, "name": "English"}],
                "downloadId": item.get("infoHash", ""),
                "customFormats": [],
                "customFormatScore": 0,
                "qualityCutoffNotMet": False,
                "series": {
                    "id": series_id,
                    "title": show_title,
                    "status": "continuing",
                    "images": []
                },
                "episode": {
                    "id": episode_id,
                    "seriesId": series_id,
                    "seasonNumber": season,
                    "episodeNumber": episode,
                    "title": item.get("episodeTitle", "Unknown Episode"),
                    "hasFile": True,
                    "monitored": True
                },
                "data": {"seriesId": series_id, "episodeId": episode_id}
            })
        
        # No additional filtering for pagination, just return all processed records
        # as Medusa API already handled the limit/page for us.
        
        log_debug(f"Returning {len(filtered_records)} records to client.")
        
        return {
            "page": page, 
            "pageSize": pageSize, 
            "totalRecords": len(filtered_records), 
            "records": filtered_records
        }
    except Exception as e:
        log_debug(f"History exception: {str(e)}")
        return {"page": 1, "pageSize": pageSize, "totalRecords": 0, "records": []}

# ---------------------------------------------------------------------------
# HARDWARE & MANAGEMENT AGENTS
# ---------------------------------------------------------------------------
@app.get("/api/v3/metadata")
async def get_metadata_consumers(api_key: str = Depends(get_medusa_key)): return []

class SonarrCommand(BaseModel):
    name: str
    seriesId: Optional[int] = None

# ---------------------------------------------------------------------------
# REPLACED: SMART COMMAND PROCESSING
# ---------------------------------------------------------------------------

@app.post("/api/v3/command")
async def execute_command(command: SonarrCommand, api_key: str = Depends(get_medusa_key)):
    # Generate a unique integer ID
    command_id = abs(hash(f"{command.name}-{command.seriesId}-{time.time()}")) % 10000
    
    # Set initial state
    COMMAND_REGISTRY[command_id] = {
        "id": command_id,
        "name": command.name,
        "state": "queued",
        "startedOn": datetime.utcnow().isoformat() + "Z"
    }

    # Dispatch to Medusa in the background without blocking the UI
    headers = medusa_headers(api_key)
    
    # We use a non-blocking approach to trigger Medusa
    try:
        if command.name == "RefreshSeries" and command.seriesId:
            await async_client.post(f"/api/v2/series/{command.seriesId}/actions/force-update", headers=headers)
        elif command.name in ["RescanSeries", "SeriesSearch"] and command.seriesId:
            await async_client.post(f"/api/v2/series/{command.seriesId}/actions/force-search", headers=headers)
        elif command.name == "CheckForUpdates":
            await async_client.post("/api/v2/system/operation", json={"command": "check_update"}, headers=headers)
        
        COMMAND_REGISTRY[command_id]["state"] = "completed"
    except Exception as e:
        log_debug(f"Command Execution Failed: {str(e)}")
        COMMAND_REGISTRY[command_id]["state"] = "failed"

    return COMMAND_REGISTRY[command_id]

@app.get("/api/v3/command")
async def get_all_commands():
    # Return the full list for Prismarr's history tracking
    return list(COMMAND_REGISTRY.values())

@app.get("/api/v3/command/{command_id}")
async def get_command_status(command_id: int):
    # Retrieve specific command state
    return COMMAND_REGISTRY.get(command_id, {
        "id": command_id, 
        "name": "Unknown", 
        "state": "completed"
    })

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
        "freeSpace": MedusaTranslator.parse_size_to_bytes(d.get("freeSpace", "0 GB")),
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

@app.get("/api/v3/log")
async def get_logs(page: int = 1, pageSize: int = 100, api_key: str = Depends(get_medusa_key)):
    res = await async_client.get("/api/v2/log", params={"raw": "true", "limit": 1000}, headers=medusa_headers(api_key))

    if res.status_code != 200:
        return {"page": page, "pageSize": pageSize, "totalRecords": 0, "records": []}

    try:
        # Regex to extract the first valid JSON array or object from the dirty response
        match = re.search(r'\[.*\]', res.text)
        if match:
            logs = json.loads(match.group(0))
        else:
            logs = []

        return {
            "page": page,
            "pageSize": pageSize,
            "totalRecords": len(logs),
            "records": [{"time": l.get("time"), "level": l.get("level"), "message": l.get("message")} for l in logs]
        }
    except Exception as e:
        # Silently fail for logs to prevent UI crashes
        return {"page": page, "pageSize": pageSize, "totalRecords": 0, "records": []}

@app.get("/api/v3/log/file")
async def get_log_file(api_key: str = Depends(get_medusa_key)):
    client = MedusaClient(api_key)
    log_content = await client.get_raw_logs()
    return log_content
def parse_size_to_bytes(size_str):
    try:
        val, unit = size_str.split()
        mult = {"GB": 10**9, "TB": 10**12, "MB": 10**6}
        return int(float(val) * mult.get(unit, 1))
    except:
        return 0

# ---------------------------------------------------------------------------
# DYNAMIC TESTERS (Pass-through logic)
# ---------------------------------------------------------------------------

@app.post("/api/v3/downloadclient/test")
async def test_download_client(client: dict, api_key: str = Depends(get_medusa_key)):
    """Dynamically tests the connection and returns the real Medusa response."""
    # 1. Fetch current config to build the test URL dynamically
    res = await async_client.get("/api/v2/config", headers=medusa_headers(api_key))
    config = res.json()
    # Assuming Transmission for this example; adapt if testing SABnzbd
    trans = config.get("clients", {}).get("torrents", {})
    
    test_url = f"{MEDUSA_URL}/home/testTorrent"
    params = {
        "torrent_method": trans.get("method"),
        "host": trans.get("host"),
        "username": trans.get("username"),
        "password": trans.get("password")
    }
    
    # 2. Execute the test and capture raw text
    resp = await async_client.get(test_url, params=params, headers=medusa_headers(api_key))
    
    # 3. Return the exact message from Medusa
    return [{"id": 0, "message": resp.text.strip()}]

@app.post("/api/v3/indexer/test")
async def test_indexer(indexer: dict, api_key: str = Depends(get_medusa_key)):
    """Triggers the provider test and returns the real result."""
    # The POST to the operation endpoint triggers the test internally
    res = await async_client.post("/api/v2/providers/internal/operation", 
                                  json={"command": "test_providers"}, 
                                  headers=medusa_headers(api_key))
    
    # Assuming the API returns the result in the body text or JSON
    msg = res.text if res.text else "Test triggered"
    return [{"id": 0, "message": msg.replace('"', '').strip()}]

# ---------------------------------------------------------------------------
# DYNAMIC SCHEMA GENERATOR
# ---------------------------------------------------------------------------

@app.get("/api/v3/downloadclient/schema")
async def get_download_client_schema(api_key: str = Depends(get_medusa_key)):
    """Dynamically builds the schema from the existing Medusa configuration."""
    res = await async_client.get("/api/v2/config", headers=medusa_headers(api_key))
    if res.status_code != 200:
        return []
        
    config = res.json()
    # We look at the 'clients' section to see what fields are currently used
    # This reflects the actual structure of your current setup
    clients = config.get("clients", {})
    
    # We dynamically generate a schema based on the keys found in the torrents config
    torrent_fields = clients.get("torrents", {}).keys()
    
    schema = []
    for field in torrent_fields:
        # Ignore sensitive fields like password
        if field.lower() in ["password", "apikey"]:
            continue
            
        schema.append({
            "name": field,
            "label": field.replace('_', ' ').title(),
            "type": "string",
            "advanced": False
        })
    return schema

# ---------------------------------------------------------------------------
# REMAINING STUBS
# ---------------------------------------------------------------------------
@app.get("/api/v3/system/tasks")
@app.get("/api/v3/config")
@app.get("/api/v3/config/ui")
@app.get("/api/v3/config/host")
@app.get("/api/v3/ping")
@app.get("/api/v3/language")
async def get_languages(api_key: str = Depends(get_medusa_key)):
    return [
        {"id": 1, "name": "English"},
        {"id": 2, "name": "Portuguese"},
        {"id": 3, "name": "Spanish"}
    ]
@app.get("/api/v3/notification")
@app.get("/api/v3/importlist")
@app.get("/api/v3/delayprofile")
@app.get("/api/v3/naming")
@app.get("/api/v3/blocklist")
async def generic_sonarr_stubs(): 
    return []
