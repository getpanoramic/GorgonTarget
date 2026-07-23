import asyncio
from fastapi import APIRouter, Depends, Query, HTTPException, Request
from typing import List, Optional
from ..utils import get_medusa_key, logger, extract_clean_integer_id, parse_medusa_size, async_client, medusa_headers, build_sonarr_images, extract_id_from_str
from ..client import MedusaClient
from ..translator import MedusaTranslator
from ..cache import episode_series_map

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
        
        # Concurrent fetching of episodes for all shows
        series_ids = [extract_clean_integer_id(show) for show in shows]
        all_episodes_data = await asyncio.gather(*[client.get_episodes(s_id) for s_id in series_ids])
        
        for i, medusa_episodes in enumerate(all_episodes_data):
            s_id = series_ids[i]
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
    logger.debug(f"DEBUG: Retrieved {len(medusa_episodes)} raw episodes from Medusa for series {target_id}.")
    if medusa_episodes:
        logger.debug(f"DEBUG: Sample raw episode: {medusa_episodes[0]}")

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
    series_ids = [extract_clean_integer_id(show) for show in shows]
    
    # Concurrent fetching of episodes for all shows
    all_episodes_data = await asyncio.gather(*[client.get_episodes(s_id) for s_id in series_ids])
    
    for i, episodes in enumerate(all_episodes_data):
        series_id = series_ids[i]
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

                # Always ensure episodeFile key exists
                compliant_ep["episodeFile"] = None
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
                        "quality": {
                            "quality": {"id": 1, "name": "HDTV-1080p", "source": "hdtv", "resolution": 1080},
                            "revision": {"version": 1, "real": False, "isRepack": False}
                        }
                    }

                logger.debug(f"get_single_episode returning: {compliant_ep}")
                return compliant_ep
            else:
                # Trace logging to debug ID mismatch
                logger.debug(f"Skipping episode ID match: requested={episode_id}, found={translated.id} (series={series_id})")
    
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
        # Improved forensic logging
        logger.debug(f"DEBUG: Processing ep {ep.get('season')}x{ep.get('episode')} - Raw keys: {list(ep.keys())}")
        
        status = str(ep.get("status", "")).lower()
        # Correctly extract location from nested 'file' object
        file_node = ep.get("file")
        if isinstance(file_node, dict):
            location = file_node.get("location") or file_node.get("name")
        else:
            location = ep.get("location")
            
        logger.debug(f"DEBUG: Checking ep status='{status}', resolved_location='{location}' for ep_id: {ep.get('id')}")
        
        # Include if it has a non-empty location
        if location and isinstance(location, str) and location.strip():
            ep_id = extract_clean_integer_id({"id": ep.get("id")})
            episode_files.append({
                "id": ep_id,
                "seriesId": target_id,
                "seasonNumber": int(ep.get("season", 0)),
                "relativePath": location,
                "path": location,
                "size": file_node.get("size") if isinstance(file_node, dict) else parse_medusa_size(ep.get("size", "0 B")),
                "dateAdded": ep.get("date", "2026-01-01T00:00:00Z"),
                "quality": {
                    "quality": {"id": 1, "name": "HDTV-1080p", "source": "hdtv", "resolution": 1080},
                    "revision": {"version": 1, "real": False, "isRepack": False}
                }
            })
        else:
            logger.debug(f"DEBUG: Episode excluded due to empty/invalid location")
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
                # Forensic logging: dump raw ep
                logger.debug(f"DEBUG: FORENSIC RAW EPISODE DATA: {ep}")
                
                # Get ID from Medusa, fallback to deterministic hash if 0
                ep_id = MedusaTranslator.extract_clean_integer_id(ep)
                if ep_id == 0:
                    ep_key = f"{show.get('slug', '0')}-{ep.get('season', 0)}-{ep.get('episode', 0)}"
                    ep_id = abs(hash(ep_key)) % 100000000
                    if ep_id == 0: ep_id = 1
                
                # Populate mapping cache
                await episode_series_map.set(str(ep_id), series_id)
                logger.debug(f"DEBUG: Populated cache with key={str(ep_id)}, value={series_id}, title={ep.get('title')}")
                
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
                logger.debug(f"DEBUG: Mapped record: {record}")
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
                # Use the same translator logic for deterministic ID matching
                ep_id = MedusaTranslator.extract_clean_integer_id(ep)
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
        show_info = data.get("show", {})
        
        quality_str = parsed.get("quality") or parsed.get("screen_size", "unknown")
        year = parsed.get("year") or show_info.get("year", {}).get("start") or 0
        logger.debug(f"DEBUG: Parsed values: quality={quality_str}, year={year}, title={parsed.get('title')}, language={show_info.get('language')}, proper={parsed.get('proper_tag')}")
        
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
                    "year": year,
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
                        "real": "REAL" in title.upper() or parsed.get("proper_tag") == "REAL", 
                        "isRepack": "REPACK" in title.upper() or parsed.get("proper_tag") == "REPACK"
                    }
                },
                "edition": parsed.get("proper_tag") or "",
                "seasonNumber": parsed.get("season", 1),
                "episodeNumbers": parsed.get("episode") if isinstance(parsed.get("episode"), list) else ([parsed.get("episode")] if parsed.get("episode") is not None else []),
                "absoluteEpisodeNumbers": [],
                "specialAbsoluteEpisodeNumbers": [],
                "languages": [{"id": 1, "name": show_info.get("language", "English")}],
                "language": {"id": 1, "name": show_info.get("language", "English")},
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
                "title": show_info.get("title", parsed.get("title")),
                "alternateTitles": [],
                "status": show_info.get("status", "continuing"),
                "year": year,
                "images": [],
                "originalLanguage": {"id": 1, "name": show_info.get("language", "English")},
                "seasons": [],
                "genres": show_info.get("genres", []),
                "tags": [],
                "addOptions": {
                    "ignoreEpisodesWithFiles": True,
                    "ignoreEpisodesWithoutFiles": True,
                    "monitor": "unknown",
                    "searchForMissingEpisodes": True,
                    "searchForCutoffUnmetEpisodes": True
                },
                "ratings": {"votes": show_info.get("rating", {}).get("imdb", {}).get("votes", 0), "value": float(show_info.get("rating", {}).get("imdb", {}).get("rating", 0))},
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
            "languages": [{"id": 1, "name": show_info.get("language", "English")}],
            "customFormats": [],
            "customFormatScore": 0
        }
        
        return response
    except Exception as e:
        logger.error(f"Parse exception: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/api/v3/release")
async def download_release(release: dict, api_key: str = Depends(get_medusa_key)):
    # The UI payload is often nested: {'release': {...}}
    data = release.get("release", release)
    
    # Extract indexerId/guid. UI uses indexerId, we need provider name for pickManualSearch
    indexer_id = data.get("indexerId")
    identifier = data.get("guid") 
    
    logger.debug(f"DEBUG: download_release raw data: {data}")

    # Resolve provider name from indexerId
    provider = None
    
    # Try fetching providers to map ID to name
    try:
        providers_res = await async_client.get("/api/v2/providers", headers=medusa_headers(api_key))
        if providers_res.status_code == 200:
            providers = providers_res.json()
            # If indexerId is a number, try to match by index
            if isinstance(indexer_id, int):
                if 0 <= indexer_id < len(providers):
                    provider = providers[indexer_id].get("id")
            else:
                # Try match by ID string
                for p in providers:
                    if str(p.get("id")) == str(indexer_id):
                        provider = p.get("id")
                        break
    except Exception as e:
        logger.error(f"Failed to resolve provider: {e}")
    
    # Fallback to direct mapping if resolution failed
    if not provider:
        provider = data.get("indexer") or str(indexer_id)
    
    if not provider or not identifier:
        logger.error(f"Missing provider or identifier in: {data}")
        raise HTTPException(status_code=400, detail=f"Missing provider or identifier. Data keys: {data.keys()}")
        
    # Triggering the GET request to Medusa
    params = {"provider": provider, "identifier": identifier}
    logger.debug(f"DEBUG: Triggering download for provider: {provider}, identifier: {identifier}")
    
    res = await async_client.get("/home/pickManualSearch", params=params, headers=medusa_headers(api_key), follow_redirects=True)
    
    # 200 is success
    if res.status_code != 200:
        logger.error(f"Download trigger failed: {res.status_code} {res.text}")
        raise HTTPException(status_code=500, detail=f"Failed to trigger download: {res.text}")
    
    return {"status": "success"}

@router.get("/api/v3/release")
async def interactive_search(episodeId: int = Query(...), api_key: str = Depends(get_medusa_key)):
    try:
        from ..cache import search_cache
        cached_results = await search_cache.get(f"search_{episodeId}")
        if cached_results:
            logger.debug(f"DEBUG: Returning cached results for {episodeId}")
            return cached_results

        # 1. Fetch episode details
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
        series_data = await client.get_series_by_id(extract_clean_integer_id(target_series))
        slug = series_data.get("id", {}).get("slug") or str(extract_clean_integer_id(target_series))
        
        season = target_ep.get("season")
        episode = target_ep.get("episode")
        
        payload = {
            "showSlug": slug,
            "options": {},
            "episodes": [f"s{season:02d}e{episode:02d}"]
        }
        logger.debug(f"DEBUG: Triggering manual search for slug: {slug}, season: {season}, episode: {episode}")
        
        res = await async_client.put("/api/v2/search/manual", json=payload, headers=medusa_headers(api_key))
        if res.status_code != 202:
            logger.error(f"Failed to trigger manual search: {res.status_code} {res.text}")
            raise HTTPException(status_code=500, detail=f"Failed to trigger manual search: {res.text}")
            
        # 3. Poll for results from all enabled providers
        providers_res = await async_client.get("/api/v2/providers", headers=medusa_headers(api_key))
        enabled_providers = [p.get("id") for p in providers_res.json()] if providers_res.status_code == 200 else []
        logger.debug(f"DEBUG: Enabled providers: {enabled_providers}")
        
        results = []
        # Optimized polling: 4 attempts, 2-second interval = 8 seconds total max
        for poll_attempt in range(4):
            import asyncio
            await asyncio.sleep(2)
            logger.debug(f"DEBUG: Polling attempt {poll_attempt + 1}")
            
            current_poll_results = []
            for provider_id in enabled_providers:
                res = await async_client.get(f"/api/v2/providers/{provider_id}/results", params={"limit": 100, "showslug": slug, "season": season, "episode": episode, "page": 1}, headers=medusa_headers(api_key))
                if res.status_code == 200:
                    provider_results = res.json()
                    logger.debug(f"DEBUG: Provider {provider_id} returned {len(provider_results)} results")
                    current_poll_results.extend(provider_results)
            
            if current_poll_results:
                results = current_poll_results
                logger.debug(f"DEBUG: Search results found on attempt {poll_attempt + 1}")
                break
        
        logger.debug(f"DEBUG: Total results found: {len(results)}")
        
        if results:
            from datetime import datetime
            
            def map_release(i, r):
                pub_date = r.get("pubdate")
                age_days = 0
                if pub_date:
                    try:
                        # Handle potential timezone offsets by stripping them for naive parsing
                        pub_dt = datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
                        age_days = (datetime.now(pub_dt.tzinfo) - pub_dt).days
                    except: pass
                
                release_str = r.get("release", "")
                is_repack = "REPACK" in release_str.upper()
                is_real = "REAL" in release_str.upper()
                
                return {
                    "id": i + 1,
                    "guid": r.get("identifier"),
                    "title": release_str,
                    "indexerId": i,
                    "indexer": r.get("provider", {}).get("name"),
                    "seriesId": r.get("seriesId"),
                    "episodeIds": [episodeId],
                    "quality": {
                        "quality": {
                            "id": 1, 
                            "name": str(r.get("quality", "HDTV")), 
                            "source": "unknown", 
                            "resolution": 0
                        },
                        "revision": {"version": 1, "real": 1 if is_real else 0, "isRepack": is_repack}
                    },
                    "age": age_days,
                    "size": r.get("size", 0),
                    "seeders": r.get("seeders", 0),
                    "leechers": r.get("leechers", 0),
                    "publishDate": pub_date,
                    "downloadUrl": r.get("url"),
                    "infoUrl": r.get("url"),
                    "protocol": "torrent",
                    "languages": [{"id": 1, "name": "English"}],
                    "seasonNumber": r.get("season"),
                    "episodeNumbers": r.get("episodes", []),
                    "mappedEpisodeInfo": [{"id": episodeId, "seasonNumber": r.get("season"), "episodeNumber": ep, "title": release_str} for ep in r.get("episodes", [])],
                    "approved": True,
                    "downloadAllowed": True
                }

            formatted_results = [map_release(i, r) for i, r in enumerate(results)]
            await search_cache.set(f"search_{episodeId}", formatted_results)
            return formatted_results
        
        return []
    except Exception as e:
        logger.exception(f"Interactive search exception: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

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
