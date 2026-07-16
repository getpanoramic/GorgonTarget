from fastapi import APIRouter, Depends, Request, Query, HTTPException
from typing import Optional
from ..utils import async_client, get_medusa_key, medusa_headers, extract_clean_integer_id, extract_clean_year, build_sonarr_images, apply_absolute_urls, logger, SERIES_ID_MAP
from ..models import SonarrAddSeries
from ..cache import series_map_cache
from ..translator import MedusaTranslator
from ..client import MedusaClient
from fastapi.responses import JSONResponse
import os

router = APIRouter()

async def core_all_series(api_key: str):
    # This was a core implementation helper function, needs to be imported or refactored.
    # Moving it to utils or keeping it in main?
    # I'll keep it here for now or put in utils. Let's put in utils.
    from ..cache import series_list_cache
    cached = await series_list_cache.get("all_series")
    if cached:
        logger.debug("Returning cached translated series dataset.")
        return cached

    client = MedusaClient(api_key)
    medusa_shows = await client.get_all_series()
    
    sonarr_shows = []
    for show in medusa_shows:
        series_obj = MedusaTranslator.to_sonarr_series(show, api_key=api_key)
        logger.debug(f"Translating show: {series_obj.title}, images: {series_obj.images}")
        sonarr_shows.append(series_obj.dict())

    logger.debug(f"OUTBOUND DATASET: Sent {len(sonarr_shows)} series objects with full image specifications.")
    await series_list_cache.set("all_series", sonarr_shows)
    return sonarr_shows

@router.get("/api/series")
@router.get("/api/v3/series")
async def get_all_series_v2(request: Request, api_key: str = Depends(get_medusa_key)):
    user_agent = request.headers.get("user-agent", "unknown")
    logger.debug(f"User-Agent: {user_agent}")
    data = await core_all_series(api_key)
    return apply_absolute_urls(data, request)

@router.get("/api/v3/series/lookup")
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

@router.get("/api/v3/series/{series_id}")
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
        
    logger.debug(f"Returning series details for {series_id}")
    return apply_absolute_urls(series_dict, request)

@router.post("/api/v3/series")
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
            # SERIES_ID_MAP is a global in main.py, I might need to import it or make it accessible
            # Assuming I can import it.
            from ..utils import SERIES_ID_MAP
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
