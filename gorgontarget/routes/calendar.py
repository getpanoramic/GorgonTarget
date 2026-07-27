from fastapi import APIRouter, Depends, Query
from typing import List
from ..utils import get_medusa_key, logger, get_async_client, medusa_headers, build_sonarr_images, extract_id_from_str
from ..models_calendar import CalendarEpisode
import httpx
import asyncio
from datetime import datetime

router = APIRouter()

@router.get("/api/v3/calendar", response_model=List[CalendarEpisode])
async def get_calendar(
    start: str = Query(...), 
    end: str = Query(...), 
    unmonitored: bool = Query(False),
    includeSeries: bool = Query(True),
    includeEpisodeFile: bool = Query(False),
    includeEpisodeImages: bool = Query(False),
    tags: str = Query(None),
    api_key: str = Depends(get_medusa_key),
    client: httpx.AsyncClient = Depends(get_async_client)
):
    try:
        # In case the dependency provider returns a coroutine instead of the client
        if asyncio.iscoroutine(client):
            async_client = await client
        else:
            async_client = client
        
        # Robust date parsing for filtering
        try:
            start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
        except ValueError:
            start_dt, end_dt = None, None

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
        
        # Combine all calendar categories (excluding 'missed')
        combined = data.get("today", []) + data.get("soon", []) + data.get("later", [])
        
        records = []
        for item in combined:
            airdate_str = item.get("localAirTime") or item.get("airdate")
            if not airdate_str:
                continue
                
            # Filter by start/end dates
            if start_dt and end_dt:
                try:
                    airdate_dt = datetime.fromisoformat(airdate_str.replace("Z", "+00:00"))
                    if airdate_dt < start_dt or airdate_dt > end_dt:
                        continue
                except ValueError:
                    # Fallback to string comparison if parsing fails
                    if airdate_str < start or airdate_str > end:
                        continue
            elif start and airdate_str < start:
                continue
            elif end and airdate_str > end:
                continue
                
            series_id = int(item.get("tvdbid") or extract_id_from_str(item.get("showSlug", "0")) or 0)
            episode_id = int(extract_id_from_str(f"{series_id}{item.get('season', 0)}{item.get('episode', 0)}") or 0)
            
        # Construct comprehensive CalendarResource (mirrors EpisodeResource)
            record = {
                "id": episode_id,
                "seriesId": series_id,
                "tvdbId": series_id,
                "episodeFileId": 0,
                "seasonNumber": item.get("season", 0),
                "episodeNumber": item.get("episode", 0),
                "title": item.get("epName", "Unknown Episode"),
                "airDate": airdate_str,
                "airDateUtc": airdate_str,
                "runtime": 30,
                "hasFile": False,
                "monitored": True,
                "series": {
                    "id": series_id,
                    "title": item.get("showName", "Unknown"),
                    "status": item.get("showStatus", "continuing").lower(),
                    "year": 2026,
                    "qualityProfileId": 1,
                    "monitored": True,
                    "runtime": 30,
                    "tvdbId": series_id,
                    "seriesType": "standard",
                    "added": "2026-01-01T00:00:00Z"
                } if includeSeries else None,
                "episodeFile": None, # Placeholder for now, requires deeper Medusa query if includeEpisodeFile is True
                "images": build_sonarr_images(series_id, api_key) if includeEpisodeImages else []
            }
            records.append(record)
            
        logger.debug(f"DEBUG: Calendar records: {records}")
        return records
    except Exception as e:
        logger.error(f"Calendar exception: {str(e)}")
        return []
