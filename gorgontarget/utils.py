import logging
import sys
import httpx
from fastapi import Header, HTTPException, status, Query, Request
from typing import Optional, List, Dict, Any
from .settings import settings
import re
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)]
)
logger = logging.getLogger("GorgonTarget")

# Shared HTTP client for proxying
async_client = httpx.AsyncClient(base_url=settings.medusa_url, timeout=settings.timeout)

# Global State
SERIES_ID_MAP = {}
COMMAND_REGISTRY = {}

# Authentication
async def get_medusa_key(
    x_api_key: Optional[str] = Header(None),
    apikey: Optional[str] = Query(None),
    api_key: Optional[str] = Query(None)
) -> str:
    resolved_key = x_api_key or apikey or api_key
    logger.debug(f"DEBUG: get_medusa_key resolved_key: {resolved_key}")
    if not resolved_key:
        logger.debug("DEBUG: get_medusa_key missing key")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Missing API Key context."
        )
    return resolved_key

def medusa_headers(api_key: str) -> dict:
    return {"x-api-key": api_key, "Content-Type": "application/json"}

# Helpers
def build_sonarr_images(series_id: int, api_key: str = "") -> List[Dict[str, str]]:
    key_param = f"?api_key={api_key}" if api_key else ""
    return [
        {"coverType": "poster", "url": f"/mediacover/{series_id}/poster-500.jpg{key_param}"},
        {"coverType": "banner", "url": f"/mediacover/{series_id}/banner-500.jpg{key_param}"},
        {"coverType": "fanart", "url": f"/mediacover/{series_id}/fanart-500.jpg{key_param}"}
    ]

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

def apply_absolute_urls(data: Any, request: Request) -> Any:
    base_url = str(request.base_url).rstrip('/')
    def _fix_item(item: dict):
        if "images" in item:
            for img in item["images"]:
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

def parse_date(date_int: int) -> str:
    try:
        return datetime.strptime(str(date_int), '%Y%m%d%H%M%S').isoformat() + 'Z'
    except:
        return "2026-01-01T00:00:00Z"

def parse_date_for_sort(date_int: int) -> datetime:
    try:
        return datetime.strptime(str(date_int), '%Y%m%d%H%M%S')
    except:
        return datetime(2026, 1, 1)

def parse_medusa_size(size_str: str) -> int:
    try:
        if not size_str: return 0
        val, unit = size_str.split()
        val = float(val)
        multipliers = {"GB": 10**9, "TB": 10**12, "MB": 10**6}
        return int(val * multipliers.get(unit.upper(), 1))
    except:
        return 0

def extract_id_from_str(id_str: str) -> int:
    """Extract numeric ID from strings like 'tvdb71663' or 'tmdb75219'."""
    import re
    match = re.search(r'\d+', str(id_str))
    return int(match.group()) if match else 0

def map_event_type(status: str) -> int:
    mapping = {
        "Snatched": 2,
        "Downloaded": 4,
        "Failed": 10
    }
    return mapping.get(status, 1)
