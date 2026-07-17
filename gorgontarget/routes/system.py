from fastapi import APIRouter, Depends, Query, Request
from typing import Optional
from ..utils import async_client, get_medusa_key, medusa_headers, logger, parse_medusa_size
from ..client import MedusaClient
import re
import json

router = APIRouter()

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

@router.get("/api/system/status")
@router.get("/api/v3/system/status")
async def get_system_status(api_key: str = Depends(get_medusa_key)):
    return await core_system_status(api_key)

@router.get("/api/v3/health")
async def get_health_proxy(api_key: str = Depends(get_medusa_key)):
    """Maps system health status."""
    # Ping the config to check backend responsiveness
    res = await async_client.get("/api/v2/config", headers=medusa_headers(api_key))
    status = "ok" if res.status_code == 200 else "error"
    return [{"source": "Medusa", "type": status, "message": "Backend operational"}]

@router.get("/api/v3/diskspace")
async def get_diskspace(api_key: str = Depends(get_medusa_key)):
    # Using your provided config endpoint
    res = await async_client.get("/api/v2/config", headers=medusa_headers(api_key))
    data = res.json() if res.status_code == 200 else {}
    
    # Translate Medusa 'diskSpace' to Sonarr 'DiskSpace'
    from ..utils import parse_medusa_size
    return [{
        "path": d.get("location"),
        "label": d.get("type"),
        "freeSpace": parse_medusa_size(d.get("freeSpace", "0 GB")),
        "totalSpace": 0
    } for d in data.get("diskSpace", {}).get("rootDir", [])]

@router.get("/api/v3/downloadclient")
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

@router.get("/api/v3/indexer")
async def get_indexers(api_key: str = Depends(get_medusa_key)):
    # Using your provided providers endpoint
    res = await async_client.get("/api/v2/providers", headers=medusa_headers(api_key))
    data = res.json() if res.status_code == 200 else []
    
    return [{"id": i, "name": idx.get("name", "Indexer"), "enableRss": True} for i, idx in enumerate(data)]

@router.get("/api/v3/log")
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

@router.get("/api/v3/log/file")
async def get_log_file(api_key: str = Depends(get_medusa_key)):
    client = MedusaClient(api_key)
    log_content = await client.get_raw_logs()
    return log_content

@router.get("/api/v3/qualityprofile")
async def get_quality_profiles(api_key: str = Depends(get_medusa_key)):
    return [
        {"id": 1, "name": "Medusa Managed Profile", "upgradeAllowed": False, "cutoff": 1, "items": []},
        {"id": 2, "name": "HD - 720p/1080p", "upgradeAllowed": False, "cutoff": 2, "items": []}
    ]

@router.get("/api/v3/system/backup")
async def get_backups(api_key: str = Depends(get_medusa_key)):
    res = await async_client.get("/api/v2/config/backup", headers=medusa_headers(api_key))
    return res.json() if res.status_code == 200 else []
