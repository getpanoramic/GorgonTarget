from fastapi import APIRouter, Depends, Query
from typing import Optional
from ..utils import async_client, get_medusa_key, medusa_headers, logger, parse_date, parse_date_for_sort, extract_id_from_str, build_sonarr_images

router = APIRouter()

@router.get("/api/v3/history")
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
            "compact": "false"
        }
        res = await async_client.get("/api/v2/history", params=params, headers=medusa_headers(api_key))
        if res.status_code != 200:
            logger.debug(f"History fetch failed: {res.status_code}")
            return {"page": 1, "pageSize": pageSize, "totalRecords": 0, "records": []}
            
        data = res.json()
        logger.debug(f"History raw data received (count: {len(data)}): {data}")
        
        # Filter and transform
        filtered_records = []
        
        # Medusa returns a list of grouped items, need to flatten them first
        all_records = []
        for group in data:
            for row in group.get("rows", []):
                # Enrich row with data from group
                row["showTitle"] = group.get("showTitle") or row.get("showTitle", "Unknown")
                row["showSlug"] = group.get("showSlug") or row.get("showSlug", "0")
                all_records.append(row)
        
        # Before transforming, sort the raw data to ensure chronological order from Medusa
        all_records.sort(key=lambda x: parse_date_for_sort(x.get("actionDate", 0)), reverse=True)

        for i, item in enumerate(all_records):
            # Extract identifiers - use showSlug for series mapping
            series_id_str = item.get("showSlug", "0")
            series_id = extract_id_from_str(series_id_str)
            
            raw_episode_id = item.get("id", 0)
            show_title = item.get("showTitle", "Unknown")
            season = item.get("season", 0)
            episode = item.get("episode", 0)
            
            # If episode_id is missing, use the unique history item id as a proxy
            episode_id = int(item.get("episode_id", 0)) if item.get("episode_id") else int(item.get("id", i + 1))
            
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
                    "images": build_sonarr_images(series_id)
                },
                "episode": {
                    "id": episode_id,
                    "seriesId": series_id,
                    "seasonNumber": season,
                    "episodeNumber": episode,
                    "title": item.get("episodeTitle", "Unknown Episode"),
                    "hasFile": True,
                    "monitored": True,
                    "series": {
                        "id": series_id,
                        "title": show_title,
                        "status": "continuing",
                        "images": build_sonarr_images(series_id)
                    },
                    "images": build_sonarr_images(series_id)
                },
                "data": {"seriesId": series_id, "episodeId": episode_id}
            })
        
        logger.debug(f"Returning {len(filtered_records)} records to client.")
        
        return {
            "page": page, 
            "pageSize": pageSize, 
            "totalRecords": len(filtered_records), 
            "records": filtered_records
        }
    except Exception as e:
        logger.debug(f"History exception: {str(e)}")
        return {"page": 1, "pageSize": pageSize, "totalRecords": 0, "records": []}
