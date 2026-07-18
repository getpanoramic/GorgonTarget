from fastapi import APIRouter, Depends, Query, Request, HTTPException, status
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

@router.get("/api/v3/system/task")
async def get_system_tasks(api_key: str = Depends(get_medusa_key)):
    client = MedusaClient(api_key)
    config = await client.get_system_config()
    schedulers = config.get("system", {}).get("schedulers", [])
    
    return [
        {
            "id": i + 1,
            "name": s.get("name"),
            "taskName": s.get("key"),
            "interval": s.get("cycleTime"),
            "lastExecution": s.get("lastRun"),
            "lastStartTime": s.get("lastRun"),
            "nextExecution": s.get("nextRun"),
            "lastDuration": "N/A"
        }
        for i, s in enumerate(schedulers)
    ]

@router.post("/api/v3/system/task/{task_name}")
async def trigger_task(task_name: str, api_key: str = Depends(get_medusa_key)):
    headers = medusa_headers(api_key)
    
    # Task mapping to Medusa API
    mapping = {
        "dailySearch": ("/api/v2/search/daily", "PUT"),
        "backlog": ("/api/v2/search/backlog", "PUT"),
        "properFinder": ("/api/v2/search/proper", "PUT"),
        "subtitlesFinder": ("/api/v2/search/subtitles", "PUT"),
        "downloadHandler": ("/api/v2/system/operation", "POST"),
        "traktChecker": ("/api/v2/recommended/trakt", "POST")
    }
    
    if task_name not in mapping:
        raise HTTPException(status_code=404, detail="Task not found")
        
    path, method = mapping[task_name]
    
    payload = {}
    if task_name == "downloadHandler":
        payload = {"type": "FORCEADH"}
        
    if method == "PUT":
        res = await async_client.put(path, headers=headers)
    else:
        res = await async_client.post(path, json=payload, headers=headers)
        
    if res.status_code not in [200, 201]:
        raise HTTPException(status_code=500, detail="Failed to trigger task")
        
    return {"status": "success"}

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
    client = MedusaClient(api_key)
    config = await client.get_system_config()
    disk_space = config.get("diskSpace", {})
    
    output = []
    
    # Map TV Download Directory
    tv_download = disk_space.get("tvDownloadDir", {})
    if tv_download:
        output.append({
            "id": 1,
            "path": tv_download.get("location"),
            "label": tv_download.get("type"),
            "freeSpace": parse_medusa_size(tv_download.get("freeSpace", "0 GB")),
            "totalSpace": 0 # Not available in Medusa config
        })
        
    # Map Root Directories
    root_dirs = disk_space.get("rootDir", [])
    for i, d in enumerate(root_dirs):
        output.append({
            "id": i + 2,
            "path": d.get("location"),
            "label": d.get("type"),
            "freeSpace": parse_medusa_size(d.get("freeSpace", "0 GB")),
            "totalSpace": 0 # Not available in Medusa config
        })
            
    return output

@router.get("/api/v3/downloadclient")
async def get_download_clients(api_key: str = Depends(get_medusa_key)):
    client = MedusaClient(api_key)
    config = await client.get_system_config()
    clients = config.get("clients", {})
    output = []
    client_id = 1

    # Torrent Clients
    torrent = clients.get("torrents", {})
    if torrent.get("enabled"):
        method = torrent.get("method")
        output.append({
            "id": client_id,
            "name": f"{method.capitalize() if method else 'Torrent'} ({torrent.get('host', 'unknown')})",
            "enable": True,
            "protocol": "torrent",
            "implementation": method
        })
        client_id += 1

    # NZB Clients
    nzb = clients.get("nzb", {})
    if nzb.get("enabled"):
        method = nzb.get("method")
        if method and method in nzb:
            details = nzb.get(method, {})
            output.append({
                "id": client_id,
                "name": f"{method.capitalize()} ({details.get('host', 'unknown')})",
                "enable": True,
                "protocol": "usenet",
                "implementation": method
            })
            client_id += 1
            
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
