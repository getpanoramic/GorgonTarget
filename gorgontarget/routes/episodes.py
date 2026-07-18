from fastapi import APIRouter, Depends, Query, HTTPException, Request
from typing import List, Optional
from ..utils import get_medusa_key, logger, extract_clean_integer_id, parse_medusa_size, async_client, medusa_headers, build_sonarr_images, extract_id_from_str
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
        # Request all relevant categories from Medusa's schedule
        params = [
            ("category[]", "today"),
            ("category[]", "soon"),
            ("category[]", "later"),
            ("paused", "true")
        ]
        res = await async_client.get("/api/v2/schedule", params=params, headers=medusa_headers(api_key))
        if res.status_code != 200: 
            return []
            
        data = res.json()
        logger.debug(f"DEBUG: Medusa Calendar raw data keys: {data.keys()}")
        
        # Combine all calendar categories (excluding 'missed')
        combined = data.get("today", []) + data.get("soon", []) + data.get("later", [])
        
        records = []
        for item in combined:
            airdate_str = item.get("localAirTime") or item.get("airdate")
            if not airdate_str:
                continue
                
            # Filter by start/end dates if provided
            if start and airdate_str < start:
                continue
            if end and airdate_str > end:
                continue
                
            series_id = int(item.get("tvdbid") or extract_id_from_str(item.get("showSlug", "0")) or 0)
            episode_id = int(extract_id_from_str(f"{series_id}{item.get('season', 0)}{item.get('episode', 0)}") or 0)
            
            records.append({
                "id": episode_id,
                "seriesId": series_id,
                "seasonNumber": item.get("season"),
                "episodeNumber": item.get("episode"),
                "title": item.get("epName", "Unknown Episode"),
                "airDateUtc": airdate_str,
                "hasFile": False,
                "monitored": True,
                "series": {
                    "id": series_id,
                    "title": item.get("showName", "Unknown"),
                    "status": item.get("showStatus", "continuing").lower(),
                    "images": build_sonarr_images(series_id)
                },
                "images": build_sonarr_images(series_id)
            })
            
        return records
    except Exception as e:
        logger.error(f"Calendar exception: {str(e)}")
        return []

@router.get("/api/v3/wanted/missing")
async def get_wanted_missing(api_key: str = Depends(get_medusa_key)):
    try:
        params = {"period": "all", "status": "all"}
        res = await async_client.get("/api/v2/internal/getEpisodeBacklog", params=params, headers=medusa_headers(api_key))
        
        if res.status_code != 200: 
            return {"page": 1, "pageSize": 20, "totalRecords": 0, "records": []}
        
        data = res.json()
        
        records = []
        for show in data:
            series_id = int(extract_id_from_str(show.get("slug", "0")) or 0)
            show_name = show.get("name", "Unknown Show")
            
            for ep in show.get("episodes", []):
                ep_id = int(ep.get("id", 0) or 0)
                
                # Strict NZB360 schema mapping with complete nested structures
                record = {
                    "id": ep_id,
                    "seriesId": series_id,
                    "tvdbId": series_id,
                    "episodeFileId": 0,
                    "seasonNumber": ep.get("season"),
                    "episodeNumber": ep.get("episode"),
                    "title": ep.get("name", "Unknown Episode"),
                    "airDate": ep.get("airdate"),
                    "airDateUtc": ep.get("airdate"),
                    "hasFile": False,
                    "monitored": True,
                    "episodeFile": {
                        "id": 0,
                        "seriesId": series_id,
                        "seasonNumber": ep.get("season"),
                        "relativePath": None,
                        "path": None,
                        "size": 0,
                        "dateAdded": "2026-07-17T00:00:00Z",
                        "quality": {
                            "quality": {"id": 1, "name": "Unknown", "source": "unknown", "resolution": 0},
                            "revision": {"version": 1, "real": 0, "isRepack": False}
                        },
                        "customFormats": [],
                        "customFormatScore": 0,
                        "indexerFlags": None,
                        "releaseType": "unknown",
                        "mediaInfo": {
                            "id": 0,
                            "audioBitrate": 0,
                            "audioChannels": 0,
                            "audioCodec": None,
                            "videoBitDepth": 0,
                            "videoBitrate": 0,
                            "videoCodec": None,
                            "videoFps": 0,
                            "resolution": None
                        },
                        "qualityCutoffNotMet": True
                    },
                    "series": {
                        "id": series_id,
                        "title": show_name,
                        "status": "continuing",
                        "images": build_sonarr_images(series_id, api_key=api_key),
                        "sortTitle": show_name,
                        "year": 2026,
                        "path": "/dev/null"
                    },
                    "images": build_sonarr_images(series_id, api_key=api_key)
                }
                records.append(record)
        
        response = {
            "page": 1, 
            "pageSize": len(records) or 20, 
            "totalRecords": len(records), 
            "records": records
        }
        logger.debug(f"DEBUG: Forensic response structure: {response}")
        return response
    except Exception as e:
        logger.error(f"Wanted missing exception: {str(e)}")
        return {"page": 1, "pageSize": 20, "totalRecords": 0, "records": []}

@router.get("/api/v3/wanted/missing/{id}")
async def get_wanted_missing_by_id(id: int, api_key: str = Depends(get_medusa_key)):
    try:
        params = {"period": "all", "status": "all"}
        res = await async_client.get("/api/v2/internal/getEpisodeBacklog", params=params, headers=medusa_headers(api_key))
        
        if res.status_code != 200: 
            raise HTTPException(status_code=404, detail="Not found")
        
        data = res.json()
        
        for show in data:
            series_id = int(extract_id_from_str(show.get("slug", "0")) or 0)
            show_name = show.get("name", "Unknown Show")
            
            for ep in show.get("episodes", []):
                ep_id = int(extract_id_from_str(f"{series_id}{ep.get('season', 0)}{ep.get('episode', 0)}") or 0)
                if ep_id == id:
                    return {
                        "id": ep_id,
                        "seriesId": series_id,
                        "tvdbId": series_id,
                        "episodeFileId": 0,
                        "seasonNumber": ep.get("season"),
                        "episodeNumber": ep.get("episode"),
                        "title": ep.get("name", "Unknown Episode"),
                        "airDate": ep.get("airdate", "2026-01-01T00:00:00Z"),
                        "airDateUtc": ep.get("airdate", "2026-01-01T00:00:00Z"),
                        "runtime": 30,
                        "hasFile": False,
                        "monitored": True,
                        "series": {
                            "id": series_id,
                            "title": show_name,
                            "status": "continuing",
                            "images": build_sonarr_images(series_id, api_key=api_key)
                        },
                        "images": build_sonarr_images(series_id, api_key=api_key)
                    }
        
        raise HTTPException(status_code=404, detail="Episode not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Wanted missing by ID exception: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/api/v3/parse")
async def parse_title(title: str = Query(...), api_key: str = Depends(get_medusa_key)):
    try:
        # Call Medusa's guessit endpoint
        params = {"release": title}
        res = await async_client.get("/api/v2/guessit", params=params, headers=medusa_headers(api_key))
        
        if res.status_code != 200:
            raise HTTPException(status_code=res.status_code, detail="Failed to parse title")
            
        data = res.json()
        logger.debug(f"DEBUG: FORENSIC Medusa guessit response: {data}")
        parsed = data.get("parse", {})
        quality_str = parsed.get("screen_size", "unknown")
        
        # Build base structure based on the provided comprehensive schema
        response = {
            "id": 1,
            "title": parsed.get("title"),
            "parsedEpisodeInfo": {
                "releaseTitle": title,
                "seriesTitle": parsed.get("title"),
                "seriesTitleInfo": {
                    "title": parsed.get("title"), 
                    "titleWithoutYear": parsed.get("title"),
                    "year": parsed.get("year", 0),
                    "allTitles": [parsed.get("title")] if parsed.get("title") else []
                },
                "quality": {
                    "quality": {
                        "id": 1, 
                        "name": quality_str, 
                        "source": "unknown", 
                        "resolution": 1080 if "1080" in quality_str else 720 if "720" in quality_str else 0
                    },
                    "revision": {
                        "version": 1, 
                        "real": "REAL" in title.upper(), 
                        "isRepack": "REPACK" in title.upper()
                    }
                },
                "seasonNumber": parsed.get("season", 1),
                "episodeNumbers": [parsed.get("episode")] if parsed.get("episode") is not None else [],
                "absoluteEpisodeNumbers": [],
                "specialAbsoluteEpisodeNumbers": [],
                "languages": [{"id": 1, "name": parsed.get("language", "English")}],
                "fullSeason": parsed.get("season") is not None and parsed.get("episode") is None,
                "isPartialSeason": False,
                "isMultiSeason": False,
                "isSeasonExtra": False,
                "isSplitEpisode": False,
                "isMiniSeries": False,
                "special": False,
                "releaseType": "episode" if parsed.get("type") == "episode" else "unknown"
            },
            "series": {
                "id": 1,
                "title": parsed.get("title"),
                "alternateTitles": [],
                "status": "continuing",
                "year": parsed.get("year", 0),
                "images": [],
                "originalLanguage": {"id": 1, "name": "English"},
                "seasons": [],
                "genres": [],
                "tags": [],
                "addOptions": {
                    "ignoreEpisodesWithFiles": True,
                    "ignoreEpisodesWithoutFiles": True,
                    "monitor": "unknown",
                    "searchForMissingEpisodes": True,
                    "searchForCutoffUnmetEpisodes": True
                },
                "ratings": {"votes": 0, "value": 0},
                "statistics": {
                    "seasonCount": 0,
                    "episodeFileCount": 0,
                    "episodeCount": 0,
                    "totalEpisodeCount": 0,
                    "sizeOnDisk": 0,
                    "releaseGroups": [],
                    "percentOfEpisodes": 0
                }
            },
            "episodes": [],
            "languages": [{"id": 1, "name": parsed.get("language", "English")}],
            "customFormats": [],
            "customFormatScore": 0
        }
        
        return response
    except Exception as e:
        logger.error(f"Parse exception: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/api/v3/release")
async def interactive_search(episodeId: int = Query(...), api_key: str = Depends(get_medusa_key)):
    # 1. Fetch episode details to get series/season/episode info
    client = MedusaClient(api_key)
    shows = await client.get_all_series()
    
    target_ep = None
    target_series = None
    
    for show in shows:
        series_id = extract_clean_integer_id(show)
        episodes = await client.get_episodes(series_id)
        for ep in episodes:
            translated = MedusaTranslator.to_sonarr_episode(ep, series_id)
            if translated.id == episodeId:
                target_ep = ep
                target_series = show
                break
        if target_ep: break
        
    if not target_ep:
        raise HTTPException(status_code=404, detail="Episode not found")
        
    # 2. Trigger manual search in Medusa
    slug = target_series.get("slug") or f"tvdb{target_series.get('externals', {}).get('tvdb')}"
    season = target_ep.get("season")
    episode = target_ep.get("episode")
    
    payload = {
        "showSlug": slug,
        "options": {},
        "episodes": [f"s{season:02d}e{episode:02d}"]
    }
    
    res = await async_client.put("/api/v2/search/manual", json=payload, headers=medusa_headers(api_key))
    if res.status_code != 202:
        raise HTTPException(status_code=500, detail="Failed to trigger manual search")
        
    # 3. Poll for results
    search_url = f"/api/v2/providers/all/results"
    params = {
        "limit": 1000,
        "showslug": slug,
        "season": season,
        "episode": episode,
        "page": 1
    }
    
    for _ in range(5):
        import asyncio
        await asyncio.sleep(2)
        res = await async_client.get(search_url, params=params, headers=medusa_headers(api_key))
        if res.status_code == 200:
            results = res.json()
            if results:
                # Map to Sonarr release format
                return [
                    {
                        "id": i + 1,
                        "guid": r.get("identifier"),
                        "title": r.get("release"),
                        "indexerId": r.get("indexer", 0),
                        "indexer": r.get("provider", {}).get("name"),
                        "seriesId": r.get("seriesId"),
                        "episodeIds": [episodeId],
                        "quality": {
                            "quality": {"id": 1, "name": "Unknown", "source": "unknown", "resolution": 0},
                            "revision": {"version": 1, "real": 0, "isRepack": False}
                        },
                        "size": r.get("size", 0),
                        "seeders": r.get("seeders"),
                        "leechers": r.get("leechers"),
                        "publishDate": r.get("pubdate"),
                        "downloadUrl": r.get("url"),
                        "infoUrl": r.get("url"),
                        "protocol": "torrent",
                        "languages": [{"id": 1, "name": "English"}],
                        "seasonNumber": r.get("season"),
                        "episodeNumbers": r.get("episodes", []),
                        "mappedEpisodeInfo": [
                            {
                                "id": episodeId,
                                "seasonNumber": r.get("season"),
                                "episodeNumber": ep,
                                "title": r.get("release")
                            }
                            for ep in r.get("episodes", [])
                        ],
                        "approved": True,
                        "downloadAllowed": True
                    }
                    for i, r in enumerate(results)
                ]
    
    return []

@router.get("/api/v3/queue")
async def get_queue(page: int = Query(1), pageSize: int = Query(20), api_key: str = Depends(get_medusa_key)):
    try:
        # Fetch active queue from Medusa
        res = await async_client.get("/api/v2/queue", headers=medusa_headers(api_key))
        
        if res.status_code != 200:
            return {"page": 1, "pageSize": pageSize, "totalRecords": 0, "records": []}
            
        data = res.json()
        
        records = []
        for item in data.get("queue", []):
            # Create a placeholder structure compliant with the schema
            record = {
                "id": int(item.get("id", 1)),
                "seriesId": None,
                "episodeId": None,
                "seasonNumber": None,
                "series": {
                    "id": 1,
                    "title": item.get("showName"),
                    "status": "continuing",
                    "images": [],
                    "year": 2026
                },
                "episode": {
                    "id": 1,
                    "seriesId": 1,
                    "seasonNumber": 1,
                    "episodeNumber": 1,
                    "title": item.get("epName"),
                    "hasFile": False,
                    "monitored": True,
                    "episodeFile": None,
                    "series": {
                        "id": 1,
                        "title": item.get("showName"),
                        "status": "continuing",
                        "images": []
                    },
                    "images": []
                },
                "languages": [{"id": 1, "name": "English"}],
                "quality": {
                    "quality": {"id": 1, "name": "Unknown", "source": "unknown", "resolution": 0},
                    "revision": {"version": 1, "real": 0, "isRepack": False}
                },
                "customFormats": [],
                "customFormatScore": 1,
                "qualityCutoffNotMet": True,
                "date": "2026-07-17T00:00:00Z",
                "size": item.get("size", 0),
                "title": item.get("epName"),
                "status": "downloading",
                "trackedDownloadStatus": "ok",
                "trackedDownloadState": "downloading",
                "episodeHasFile": False
            }
            records.append(record)
            
        return {
            "page": page,
            "pageSize": pageSize,
            "totalRecords": len(records),
            "records": records
        }
    except Exception as e:
        logger.error(f"Queue exception: {str(e)}")
        return {"page": 1, "pageSize": pageSize, "totalRecords": 0, "records": []}

@router.get("/api/v3/queue/status")
async def get_queue_status(api_key: str = Depends(get_medusa_key)):
    # Medusa doesn't have a direct 'queue/status' endpoint, returning placeholder 
    # to avoid 404/errors in the client
    return {"totalCount": 0, "count": 0, "pageSize": 20, "sortKey": "timeleft", "unknownQueueItems": 0, "queued": 0, "downloading": 0, "failed": 0, "errors": False, "warnings": False}
