from fastapi import APIRouter, Depends, Query, HTTPException, Request
from typing import List, Optional
from ..utils import get_medusa_key, logger, extract_clean_integer_id, parse_medusa_size, async_client, medusa_headers
from ..client import MedusaClient
from ..translator import MedusaTranslator

router = APIRouter()

@router.get("/api/v3/episode")
async def get_episodes(
    seriesId: Optional[int] = Query(None),
    seriesid: Optional[int] = Query(None),
    episodeIds: Optional[List[int]] = Query(None),
    includeEpisodeFile: bool = Query(False),
    api_key: str = Depends(get_medusa_key)
):
    client = MedusaClient(api_key)
    
    if episodeIds:
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

@router.get("/api/v3/episode/{episode_id}")
async def get_single_episode(episode_id: int, includeEpisodeFile: bool = Query(False), api_key: str = Depends(get_medusa_key)):
    logger.debug(f"get_single_episode requested for ID: {episode_id}")
    client = MedusaClient(api_key)
    shows = await client.get_all_series()
    
    for show in shows:
        series_id = extract_clean_integer_id(show)
        episodes = await client.get_episodes(series_id)
        for ep in episodes:
            translated = MedusaTranslator.to_sonarr_episode(ep, series_id)
            if translated.id == episode_id:
                ep_dict = translated.dict()
                
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

                logger.debug(f"get_single_episode returning: {compliant_ep}")
                return compliant_ep
    
    logger.debug(f"get_single_episode: Episode {episode_id} not found.")
    raise HTTPException(status_code=404, detail="Episode not found")

@router.get("/api/v3/episodefile")
async def get_episode_files(
    seriesId: Optional[int] = Query(None), 
    seriesid: Optional[int] = Query(None),
    api_key: str = Depends(get_medusa_key)
):
    logger.debug(f"get_episode_files requested with seriesId={seriesId}, seriesid={seriesid}")
    target_id = seriesId or seriesid
    if not target_id: 
        logger.debug("get_episode_files called without a valid seriesId, returning empty.")
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
    logger.debug(f"get_episode_files returning {len(episode_files)} files for series {target_id}")
    return episode_files

@router.get("/api/v3/calendar")
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

@router.get("/api/v3/wanted/missing")
async def get_wanted_missing(api_key: str = Depends(get_medusa_key)):
    try:
        res = await async_client.get("/api/v2/schedule", headers=medusa_headers(api_key))
        if res.status_code != 200: 
            logger.debug(f"Wanted missing fetch failed: {res.status_code}")
            return {"page": 1, "pageSize": 20, "totalRecords": 0, "records": []}
        
        data = res.json()
        logger.debug(f"Wanted missing raw data: {data}")
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
        logger.debug(f"Wanted missing exception: {str(e)}")
        return {"page": 1, "pageSize": 20, "totalRecords": 0, "records": []}

@router.get("/api/v3/queue")
async def get_queue(page: int = 1, pageSize: int = 20, api_key: str = Depends(get_medusa_key)):
    return {"page": page, "pageSize": pageSize, "totalRecords": 0, "records": []}

@router.get("/api/v3/queue/status")
async def get_queue_status(api_key: str = Depends(get_medusa_key)):
    return {"totalCount": 0, "count": 0, "pageSize": 20, "sortKey": "timeleft", "unknownQueueItems": 0, "queued": 0, "downloading": 0, "failed": 0, "errors": False, "warnings": False}
