from fastapi import APIRouter, Depends, Query, Request, HTTPException, status, Response
from fastapi.responses import StreamingResponse
from typing import Optional
from ..utils import async_client, get_medusa_key, medusa_headers, logger, parse_medusa_size
from ..client import MedusaClient
import re
import json
import os
import logging
import glob

router = APIRouter()

@router.get("/api/v3/language")
async def get_languages():
    return [
        {"id": 1, "name": "English", "nameLower": "english"},
        {"id": 2, "name": "French", "nameLower": "french"},
        {"id": 3, "name": "German", "nameLower": "german"},
        {"id": 4, "name": "Spanish", "nameLower": "spanish"}
    ]

@router.get("/api/v3/wanted/cutoff")
async def get_wanted_cutoff(page: int = Query(1), pageSize: int = Query(50)):
    return {
        "page": page,
        "pageSize": pageSize,
        "sortKey": None,
        "sortDirection": "default",
        "totalRecords": 1,
        "records": [
            {
                "id": 1,
                "seriesId": 1,
                "tvdbId": 1,
                "episodeFileId": 1,
                "seasonNumber": 1,
                "episodeNumber": 1,
                "title": None,
                "airDate": None,
                "airDateUtc": None,
                "lastSearchTime": None,
                "runtime": 1,
                "finaleType": None,
                "overview": None,
                "episodeFile": {
                    "id": 1,
                    "seriesId": 1,
                    "seasonNumber": 1,
                    "relativePath": None,
                    "path": None,
                    "size": 1,
                    "dateAdded": "2026-07-23T17:24:40.705Z",
                    "sceneName": None,
                    "releaseGroup": None,
                    "languages": [{"id": 1, "name": None}],
                    "quality": {
                        "quality": {"id": 1, "name": None, "source": "unknown", "resolution": 1},
                        "revision": {"version": 1, "real": 1, "isRepack": True}
                    },
                    "customFormats": [
                        {
                            "id": 1,
                            "name": None,
                            "includeCustomFormatWhenRenaming": None,
                            "specifications": [
                                {
                                    "id": 1,
                                    "name": None,
                                    "implementation": None,
                                    "implementationName": None,
                                    "infoLink": None,
                                    "negate": True,
                                    "required": True,
                                    "fields": [
                                        {
                                            "order": 1,
                                            "name": None,
                                            "label": None,
                                            "unit": None,
                                            "helpText": None,
                                            "helpTextWarning": None,
                                            "helpLink": None,
                                            "value": None,
                                            "type": None,
                                            "advanced": True,
                                            "selectOptions": ["[Max Depth Exceeded]"],
                                            "selectOptionsProviderAction": None,
                                            "section": None,
                                            "hidden": None,
                                            "privacy": "normal",
                                            "placeholder": None,
                                            "isFloat": True
                                        }
                                    ],
                                    "presets": []
                                }
                            ]
                        }
                    ],
                    "customFormatScore": 1,
                    "indexerFlags": None,
                    "releaseType": "unknown",
                    "mediaInfo": {
                        "id": 1,
                        "audioBitrate": 1,
                        "audioChannels": 1,
                        "audioCodec": None,
                        "audioLanguages": None,
                        "audioStreamCount": 1,
                        "videoBitDepth": 1,
                        "videoBitrate": 1,
                        "videoCodec": None,
                        "videoFps": 1,
                        "videoDynamicRange": None,
                        "videoDynamicRangeType": None,
                        "resolution": None,
                        "runTime": None,
                        "scanType": None,
                        "subtitles": None
                    },
                    "qualityCutoffNotMet": True
                },
                "hasFile": True,
                "monitored": True,
                "absoluteEpisodeNumber": None,
                "sceneAbsoluteEpisodeNumber": None,
                "sceneEpisodeNumber": None,
                "sceneSeasonNumber": None,
                "unverifiedSceneNumbering": True,
                "endTime": None,
                "grabDate": None,
                "series": {
                    "id": 1,
                    "title": None,
                    "alternateTitles": [
                        {
                            "title": None,
                            "seasonNumber": None,
                            "sceneSeasonNumber": None,
                            "sceneOrigin": None,
                            "comment": None
                        }
                    ],
                    "sortTitle": None,
                    "status": "continuing",
                    "ended": True,
                    "profileName": None,
                    "overview": None,
                    "nextAiring": None,
                    "previousAiring": None,
                    "network": None,
                    "airTime": None,
                    "images": [
                        {"coverType": "unknown", "url": None, "remoteUrl": None}
                    ],
                    "originalLanguage": {"id": 1, "name": None},
                    "remotePoster": None,
                    "seasons": [
                        {
                            "seasonNumber": 1,
                            "monitored": True,
                            "statistics": {
                                "nextAiring": None,
                                "previousAiring": None,
                                "episodeFileCount": 1,
                                "episodeCount": 1,
                                "totalEpisodeCount": 1,
                                "sizeOnDisk": 1,
                                "releaseGroups": ["string"],
                                "percentOfEpisodes": 1
                            },
                            "images": [
                                {"coverType": "unknown", "url": None, "remoteUrl": None}
                            ]
                        }
                    ],
                    "year": 1,
                    "path": None,
                    "qualityProfileId": 1,
                    "seasonFolder": True,
                    "monitored": True,
                    "monitorNewItems": "all",
                    "useSceneNumbering": True,
                    "runtime": 1,
                    "tvdbId": 1,
                    "tvRageId": 1,
                    "tvMazeId": 1,
                    "tmdbId": 1,
                    "firstAired": None,
                    "lastAired": None,
                    "seriesType": "standard",
                    "cleanTitle": None,
                    "imdbId": None,
                    "titleSlug": None,
                    "rootFolderPath": None,
                    "folder": None,
                    "certification": None,
                    "genres": ["string"],
                    "tags": [1],
                    "added": "2026-07-23T17:24:40.705Z",
                    "addOptions": {
                        "ignoreEpisodesWithFiles": True,
                        "ignoreEpisodesWithoutFiles": True,
                        "monitor": "unknown",
                        "searchForMissingEpisodes": True,
                        "searchForCutoffUnmetEpisodes": True
                    },
                    "ratings": {"votes": 1, "value": 1},
                    "statistics": {
                        "seasonCount": 1,
                        "episodeFileCount": 1,
                        "episodeCount": 1,
                        "totalEpisodeCount": 1,
                        "sizeOnDisk": 1,
                        "releaseGroups": ["string"],
                        "percentOfEpisodes": 1
                    },
                    "episodesChanged": None
                },
                "images": [
                    {"coverType": "unknown", "url": None, "remoteUrl": None}
                ]
            }
        ]
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
    # Medusa doesn't expose all these fields, mapping best effort
    now = "2026-07-23T20:22:08.218Z"
    return {
        "appName": "Sonarr",
        "instanceName": "GorgonTarget",
        "version": "4.0.0",
        "buildTime": now,
        "isDebug": True,
        "isProduction": True,
        "isAdmin": True,
        "isUserInteractive": True,
        "startupPath": "/app",
        "appData": "/config",
        "osName": "linux",
        "osVersion": "alpine",
        "isNetCore": True,
        "isLinux": True,
        "isOsx": False,
        "isWindows": False,
        "isDocker": True,
        "mode": "console",
        "branch": "master",
        "authentication": "none",
        "sqliteVersion": "3.37.0",
        "migrationVersion": 1,
        "urlBase": "",
        "runtimeVersion": "3.11",
        "runtimeName": "python",
        "startTime": now,
        "packageVersion": "4.0.0",
        "packageAuthor": "GorgonTarget",
        "packageUpdateMechanism": "builtIn",
        "packageUpdateMechanismMessage": None,
        "databaseVersion": "1",
        "databaseType": "sqLite"
    }

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
        free_bytes = parse_medusa_size(tv_download.get("freeSpace", "0 GB"))
        output.append({
            "id": 1,
            "path": tv_download.get("location"),
            "label": tv_download.get("type"),
            "freeSpace": free_bytes,
            "totalSpace": int(free_bytes * 1.5) # Estimate total to prevent UI errors
        })
        
    # Map Root Directories
    root_dirs = disk_space.get("rootDir", [])
    for i, d in enumerate(root_dirs):
        free_bytes = parse_medusa_size(d.get("freeSpace", "0 GB"))
        output.append({
            "id": i + 2,
            "path": d.get("location"),
            "label": d.get("type"),
            "freeSpace": free_bytes,
            "totalSpace": int(free_bytes * 1.5) # Estimate total to prevent UI errors
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

@router.get("/api/v3/downloadclient/schema")
async def get_download_client_schema(api_key: str = Depends(get_medusa_key)):
    client = MedusaClient(api_key)
    config = await client.get_system_config()
    clients = config.get("clients", {})
    
    schema = []
    
    # Define field maps for known implementations
    field_maps = {
        "transmission": [
            {"name": "host", "label": "Host", "type": "string"},
            {"name": "username", "label": "Username", "type": "string"},
            {"name": "password", "label": "Password", "type": "password"}
        ],
        "sabnzbd": [
            {"name": "host", "label": "Host", "type": "string"},
            {"name": "apiKey", "label": "API Key", "type": "string"}
        ],
        "nzbget": [
            {"name": "host", "label": "Host", "type": "string"},
            {"name": "username", "label": "Username", "type": "string"},
            {"name": "password", "label": "Password", "type": "password"}
        ]
    }
    
    # Dynamic schema generation based on configured clients
    torrent = clients.get("torrents", {})
    if torrent.get("enabled"):
        method = torrent.get("method")
        schema.append({
            "implementation": method,
            "name": method.capitalize() if method else "Torrent",
            "fields": field_maps.get(method, [{"name": "host", "label": "Host", "type": "string"}])
        })
        
    nzb = clients.get("nzb", {})
    if nzb.get("enabled"):
        method = nzb.get("method")
        if method:
            schema.append({
                "implementation": method,
                "name": method.capitalize(),
                "fields": field_maps.get(method, [{"name": "host", "label": "Host", "type": "string"}])
            })
            
    return schema

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

@router.get("/api/v3/filesystem")
async def get_filesystem(
    path: str = Query(""),
    includeFiles: bool = Query(True),
    api_key: str = Depends(get_medusa_key)
):
    client = MedusaClient(api_key)
    # Map the Bazarr request to Medusa's browser API
    # Medusa's browser API uses 'path' and 'includeFiles=0/1'
    params = {"path": path, "includeFiles": "1" if includeFiles else "0"}
    
    data = await client.browser(params)
    
    # Map Medusa response to Sonarr/Bazarr schema
    directories = []
    files = []
    
    for item in data:
        # Skip the current path item if it exists
        if "currentPath" in item:
            continue
            
        is_file = item.get("path", "").endswith((".mkv", ".mp4", ".avi", ".ts"))
        formatted_item = {
            "name": item.get("name"),
            "path": item.get("path"),
            "type": "file" if is_file else "directory"
        }
        
        if is_file:
            files.append(formatted_item)
        else:
            directories.append(formatted_item)
        
    return {
        "path": path,
        "directories": directories,
        "files": files
    }

@router.get("/api/v3/logs/download")
async def download_logs(api_key: str = Depends(get_medusa_key)):
    log_base = "/tmp/gorgontarget.log"
    # Find all rotated log files: gorgontarget.log, gorgontarget.log.1, etc.
    log_files = glob.glob(f"{log_base}*")
    
    # Sort files: current log should be last, rotated logs should be in order
    # The rotating handler keeps .1 as newest, then .2, etc.
    # We want .3 -> .2 -> .1 -> ""
    def get_log_index(filename):
        if filename == log_base: return 0
        return int(filename.split('.')[-1])

    # Sort files by index: .3, .2, .1, (base)
    log_files.sort(key=get_log_index, reverse=True)
    
    if not log_files:
        return Response(content="Log file not found.", media_type="text/plain", status_code=404)

    def iter_files():
        for log_file in log_files:
            if os.path.exists(log_file):
                with open(log_file, mode="rb") as file_like:
                    yield from file_like

    return StreamingResponse(
        iter_files(),
        media_type="text/plain",
        headers={"Content-Disposition": "attachment; filename=gorgontarget_full.log"}
    )

@router.get("/api/v3/qualityprofile")
async def get_quality_profiles(api_key: str = Depends(get_medusa_key)):
    return [
        {"id": 1, "name": "Medusa Managed Profile", "upgradeAllowed": False, "cutoff": 1, "items": []},
        {"id": 2, "name": "HD - 720p/1080p", "upgradeAllowed": False, "cutoff": 2, "items": []}
    ]

@router.get("/api/v3/rootfolder")
async def get_root_folders(api_key: str = Depends(get_medusa_key)):
    client = MedusaClient(api_key)
    config = await client.get_system_config()
    disk_space = config.get("diskSpace", {})
    root_dirs = disk_space.get("rootDir", [])
    
    output = []
    for i, d in enumerate(root_dirs):
        free_bytes = parse_medusa_size(d.get("freeSpace", "0 GB"))
        output.append({
            "id": i + 1,
            "path": d.get("location"),
            "accessible": True,
            "freeSpace": free_bytes,
            "unmappedFolders": []
        })
    return output

@router.get("/api/v3/tag")
async def get_tags(api_key: str = Depends(get_medusa_key)):
    # Medusa doesn't have a direct equivalent to Sonarr tags.
    # Return a default empty list or minimal mapping to satisfy the UI requirement.
    return []

@router.get("/api/v3/languageprofile")
async def get_language_profiles(api_key: str = Depends(get_medusa_key)):
    client = MedusaClient(api_key)
    config = await client.get_system_config()
    subtitles = config.get("subtitles", {})
    wanted_langs = subtitles.get("wantedLanguages", [])
    
    # Map Medusa's wantedLanguages to the requested schema
    languages = []
    for i, lang in enumerate(wanted_langs):
        languages.append({
            "id": i + 1,
            "language": {
                "id": i + 1,
                "name": lang.get("name")
            },
            "allowed": True
        })
        
    return [{
        "id": 1,
        "name": "Default Language Profile",
        "upgradeAllowed": True,
        "cutoff": {
            "id": 1,
            "name": "English"
        },
        "languages": languages
    }]

@router.get("/api/v3/system/backup")
async def get_backups(api_key: str = Depends(get_medusa_key)):
    res = await async_client.get("/api/v2/config/backup", headers=medusa_headers(api_key))
    return res.json() if res.status_code == 200 else []
