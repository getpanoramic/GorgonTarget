from fastapi import APIRouter, Depends, Query
from typing import Optional
from ..utils import async_client, get_medusa_key, medusa_headers, logger

router = APIRouter()

@router.get("/api/v3/blocklist")
async def get_blocklist(
    page: int = Query(1), 
    pageSize: int = Query(50),
    sortKey: str = Query("date"),
    sortDirection: str = Query("descending"),
    api_key: str = Depends(get_medusa_key)
):
    try:
        # Fetch failed downloads from Medusa
        params = {"limit": pageSize}
        res = await async_client.get("/api/v2/internal/getFailed", params=params, headers=medusa_headers(api_key))
        
        if res.status_code != 200:
            logger.debug(f"Blocklist fetch failed: {res.status_code}")
            return {"page": 1, "pageSize": pageSize, "totalRecords": 0, "records": []}
            
        data = res.json()
        logger.debug(f"Blocklist raw data received (count: {len(data)})")
        
        records = []
        for item in data:
            # Map Medusa quality (if available in release string) to Sonarr schema
            release = item.get("release", "")
            quality_name = "Unknown"
            if "1080p" in release: quality_name = "1080p"
            elif "720p" in release: quality_name = "720p"
            elif "480p" in release: quality_name = "480p"
            elif "2160p" in release: quality_name = "2160p"
            
            # Sonarr quality mapping
            quality_map = {
                "2160p": {"id": 1, "name": "2160p", "source": "web", "resolution": 2160},
                "1080p": {"id": 2, "name": "1080p", "source": "web", "resolution": 1080},
                "720p": {"id": 3, "name": "720p", "source": "web", "resolution": 720},
                "480p": {"id": 4, "name": "480p", "source": "web", "resolution": 480},
                "Unknown": {"id": 0, "name": "Unknown", "source": "unknown", "resolution": 0}
            }
            mapped_quality = quality_map.get(quality_name, quality_map["Unknown"])

            # Map Medusa failed item to Sonarr blocklist item
            records.append({
                "id": item.get("id"),
                "sourceTitle": release,
                "quality": {
                    "quality": mapped_quality,
                    "revision": {"version": 1, "real": 0, "isRepack": False}
                },
                "languages": [{"id": 1, "name": "English"}],
                "date": "2026-07-17T00:00:00Z", # Placeholder for missing timestamp
                "size": item.get("size", 0),
                "indexer": item.get("provider", {}).get("name", "Unknown"),
                "message": "Download failed"
            })
            
        return {
            "page": page,
            "pageSize": pageSize,
            "totalRecords": len(records),
            "records": records
        }
    except Exception as e:
        logger.error(f"Blocklist exception: {str(e)}")
        return {"page": 1, "pageSize": pageSize, "totalRecords": 0, "records": []}
