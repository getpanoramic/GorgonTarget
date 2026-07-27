from fastapi import APIRouter, Depends, Query
from typing import List
from ..utils import get_medusa_key, logger, get_async_client, medusa_headers, build_sonarr_images, extract_id_from_str, generate_deterministic_id
from ..models_calendar import CalendarEpisode
import httpx
import asyncio
from datetime import datetime, timezone

router = APIRouter()

def ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt

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
            start_dt = ensure_aware(datetime.fromisoformat(start.replace("Z", "+00:00")))
            end_dt = ensure_aware(datetime.fromisoformat(end.replace("Z", "+00:00")))
        except ValueError:
            start_dt, end_dt = None, None

        params = [
            ("category[]", "today"),
            ("category[]", "soon"),
            ("category[]", "later"),
            ("category[]", "missed"),
            ("paused", "true")
        ]
        
        res = await async_client.get("/api/v2/schedule", params=params, headers=medusa_headers(api_key))
        if res.status_code != 200: 
            logger.error(f"Calendar fetch failed: {res.status_code} - {res.text}")
            return []
            
        data = res.json()
        logger.debug(f"DEBUG: Calendar raw data keys: {list(data.keys())}")
        
        # Combine all calendar categories (including 'missed')
        combined = data.get("today", []) + data.get("soon", []) + data.get("later", []) + data.get("missed", [])
        
        records = []
        for item in combined:
            logger.debug(f"DEBUG: Processing calendar item: {item.get('showName', 'Unknown')} - {item.get('season', '0')}x{item.get('episode', '0')}")
            airdate_str = item.get("localAirTime") or item.get("airdate")
            if not airdate_str:
                logger.debug(f"DEBUG: Skipping item due to missing airdate: {item.get('epName', 'Unknown')}")
                continue
                
            # Filter by start/end dates
            if start_dt and end_dt:
                try:
                    airdate_dt = ensure_aware(datetime.fromisoformat(airdate_str.replace("Z", "+00:00")))
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
            # Use deterministic hash based on unique components to avoid collisions
            episode_id = generate_deterministic_id(f"{series_id}_{item.get('season', 0)}_{item.get('episode', 0)}")

            # Construct minimal compatible CalendarResource
            record = {
                "id": episode_id,
                "seriesId": series_id,
                "seasonNumber": item.get("season", 0),
                "episodeNumber": item.get("episode", 0),
                "title": item.get("epName", "Unknown Episode"),
                "airDate": airdate_str.split('T')[0] if airdate_str else None,
                "airDateUtc": airdate_str,
                "hasFile": False,
                "monitored": True,
                "series": {
                    "id": series_id,
                    "title": item.get("showName", "Unknown"),
                    "status": "continuing",
                    "year": 2026,
                    "monitored": True
                } if includeSeries else None,
                "images": build_sonarr_images(series_id, api_key) if includeEpisodeImages else []
            }
            records.append(record)
            
        logger.debug(f"DEBUG: Returning {len(records)} calendar records.")
        return records
    except Exception as e:
        logger.error(f"Calendar exception: {str(e)}")
        return []
