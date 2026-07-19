from fastapi import APIRouter, Depends, HTTPException, Request
from typing import Optional, Any, Dict
from pydantic import BaseModel, Field
from datetime import datetime
import time
from ..utils import get_medusa_key, medusa_headers, logger, async_client, COMMAND_REGISTRY, extract_clean_integer_id, extract_id_from_str

router = APIRouter()

class SonarrCommandBody(BaseModel):
    sendUpdatesToClient: Optional[bool] = True
    updateScheduledTask: Optional[bool] = True
    completionMessage: Optional[str] = None
    requiresDiskAccess: Optional[bool] = True
    isExclusive: Optional[bool] = True
    isLongRunning: Optional[bool] = True
    name: Optional[str] = None
    lastExecutionTime: Optional[str] = None
    lastStartTime: Optional[str] = None
    trigger: Optional[str] = "unspecified"
    suppressMessages: Optional[bool] = True
    clientUserAgent: Optional[str] = None

class SonarrCommand(BaseModel):
    id: Optional[int] = None
    name: Optional[str] = None
    commandName: Optional[str] = None
    message: Optional[str] = None
    body: Optional[SonarrCommandBody] = None
    priority: Optional[str] = "normal"
    status: Optional[str] = "queued"
    result: Optional[str] = "unknown"
    queued: Optional[str] = None
    started: Optional[str] = None
    ended: Optional[str] = None
    duration: Optional[str] = None
    exception: Optional[str] = None
    trigger: Optional[str] = "unspecified"
    clientUserAgent: Optional[str] = None
    stateChangeTime: Optional[str] = None
    sendUpdatesToClient: Optional[bool] = True
    updateScheduledTask: Optional[bool] = True
    lastExecutionTime: Optional[str] = None

@router.post("/api/v3/command")
async def execute_command(command: Dict[str, Any], api_key: str = Depends(get_medusa_key)):
    logger.debug(f"Received Command request payload: {command}")
    
    # Extract command name from 'name' or 'commandName' or nested body
    name = command.get("name") or command.get("commandName")
    if not name and "body" in command and isinstance(command["body"], dict):
        name = command["body"].get("name")
        
    # Try to extract seriesId from body
    series_id = None
    if "body" in command and isinstance(command["body"], dict):
        series_id = command["body"].get("seriesId") or command["body"].get("id")
    
    # If series_id is missing, try to resolve it from episodeIds if available
    episode_ids = command.get("episodeIds") or (command["body"].get("episodeIds") if "body" in command and isinstance(command["body"], dict) else [])
    
    if not series_id and episode_ids:
        # Optimization: Try to use cached maps to resolve series_id from episode_ids
        from ..client import MedusaClient
        from ..cache import series_episodes_cache
        client = MedusaClient(api_key)
        series_list = await client.get_all_series()
        
        # Map all episode IDs to series IDs once to avoid nested loops
        # This is a bit intensive, but only runs if series_id is missing
        for s in series_list:
            raw_id = s.get("id")
            s_id = 0
            if isinstance(raw_id, dict):
                s_id = raw_id.get("tvdb") or raw_id.get("tvmaze") or 0
            else:
                try: s_id = int(raw_id)
                except (ValueError, TypeError): s_id = 0
            
            if not s_id: continue
            
            # Use cached episodes if available
            episodes = await client.get_episodes(s_id)
            
            for ep in episodes:
                ep_id = int(extract_id_from_str(f"{s_id}{ep.get('season', 0)}{ep.get('episode', 0)}") or 0)
                if ep_id in episode_ids:
                    series_id = s_id
                    break
            if series_id: break
        logger.debug(f"DEBUG: Resolved series_id: {series_id}")
    
    logger.debug(f"DEBUG: Extracted name: {name}, series_id: {series_id}")
        
    if not name:
        logger.error("Could not find command name in the payload.")
        raise HTTPException(status_code=400, detail="Command name is required.")

    # Generate a unique integer ID
    command_id = abs(hash(f"{name}-{series_id}-{time.time()}")) % 10000
    
    # Set initial state matching the schema requested
    now_str = datetime.utcnow().isoformat() + "Z"
    COMMAND_REGISTRY[command_id] = {
        "id": command_id,
        "name": name,
        "commandName": name,
        "message": None,
        "body": {
            "sendUpdatesToClient": True,
            "updateScheduledTask": True,
            "completionMessage": None,
            "requiresDiskAccess": True,
            "isExclusive": True,
            "isLongRunning": True,
            "name": name,
            "lastExecutionTime": None,
            "lastStartTime": now_str,
            "trigger": "unspecified",
            "suppressMessages": True,
            "clientUserAgent": None
        },
        "priority": "normal",
        "status": "queued",
        "result": "unknown",
        "queued": now_str,
        "started": now_str,
        "ended": None,
        "duration": None,
        "exception": None,
        "trigger": "unspecified",
        "clientUserAgent": None,
        "stateChangeTime": now_str,
        "sendUpdatesToClient": True,
        "updateScheduledTask": True,
        "lastExecutionTime": None
    }

    # Dispatch to Medusa in the background without blocking the UI
    try:
        from ..client import MedusaClient
        from ..cache import series_map_cache
        client = MedusaClient(api_key)
        
        # Resolve slug for command
        slug = None
        if series_id:
            slug = await series_map_cache.get(f"map_{series_id}") or str(series_id)
        
        logger.debug(f"DEBUG: Pre-execution slug: {slug}, name: {name}")
        
        # Dispatch logic
        success = False
        
        # Commands that don't need a slug
        if name == "RefreshMonitoredDownloads":
            logger.debug("DEBUG: RefreshMonitoredDownloads triggered")
            success = True
        elif name == "CheckForUpdates":
            res = await async_client.post("/api/v2/system/operation", json={"command": "check_update"}, headers=medusa_headers(api_key))
            success = res.status_code == 200
        elif name == "dailySearch":
            res = await async_client.put("/api/v2/search/daily", headers=medusa_headers(api_key))
            success = res.status_code == 200
        elif name == "backlog":
            res = await async_client.put("/api/v2/search/backlog", headers=medusa_headers(api_key))
            success = res.status_code == 200
        elif name == "properFinder":
            res = await async_client.put("/api/v2/search/proper", headers=medusa_headers(api_key))
            success = res.status_code == 200
        elif name == "subtitlesFinder":
            res = await async_client.put("/api/v2/search/subtitles", headers=medusa_headers(api_key))
            success = res.status_code == 200
        elif name == "downloadHandler":
            res = await async_client.post("/api/v2/system/operation", json={"type": "FORCEADH"}, headers=medusa_headers(api_key))
            success = res.status_code == 200
        elif name == "traktChecker":
            res = await async_client.post("/api/v2/recommended/trakt", headers=medusa_headers(api_key))
            success = res.status_code == 200
        
        # Commands that need a slug or series context
        elif slug or name == "EpisodeSearch":
            if name == "RefreshSeries":
                url = f"/home/updateShow?showslug={slug}"
                res = await async_client.get(url, headers=medusa_headers(api_key))
                success = res.status_code == 200
            elif name in ["RescanSeries", "SeriesSearch"]:
                url = f"/home/refreshShow?showslug={slug}"
                res = await async_client.get(url, headers=medusa_headers(api_key))
                success = res.status_code == 200
            elif name == "EpisodeSearch":
                logger.debug("DEBUG: Entering EpisodeSearch block")
                episode_ids = [eid for eid in command.get("episodeIds", []) if isinstance(eid, int) and eid > 0]
                
                if not episode_ids:
                    logger.warning(f"EpisodeSearch triggered with no valid episode IDs: {command.get('episodeIds')}")
                    success = False
                else:
                    logger.debug(f"DEBUG: EpisodeSearch triggered for valid IDs: {episode_ids}, series_id: {series_id}")
                    
                    # If we don't have a series_id, resolve it
                    if not series_id:
                        series_list = await client.get_all_series()
                        for s in series_list:
                            # Safely extract integer ID by trying any numeric value
                            raw_id = s.get("id")
                            s_id = 0
                            if isinstance(raw_id, dict):
                                # Try any numeric value in the dictionary
                                for val in raw_id.values():
                                    try:
                                        s_id = int(val)
                                        if s_id: break
                                    except (ValueError, TypeError):
                                        continue
                            else:
                                try:
                                    s_id = int(raw_id)
                                except (ValueError, TypeError):
                                    s_id = 0
                            
                            if not s_id: continue
                            episodes = await client.get_episodes(s_id)
                            
                            # Defensive check that episodes is a list
                            if not isinstance(episodes, list):
                                logger.warning(f"Unexpected episodes format for series {s_id}: {type(episodes)}")
                                continue
                            
                            for ep in episodes:
                                try:
                                    ep_id_raw = ep.get("id")
                                    if ep_id_raw is None: continue
                                    ep_id = int(ep_id_raw)
                                    if ep_id in episode_ids:
                                        series_id = s_id
                                        break
                                except (ValueError, TypeError):
                                    continue
                            if series_id: break

                    if series_id:
                        slug = await series_map_cache.get(f"map_{series_id}") or str(series_id)
                        episodes = await client.get_episodes(series_id)
                        
                        # Defensive check that episodes is a list
                        if not isinstance(episodes, list):
                            logger.error(f"Failed to get episodes for series {series_id}")
                            success = False
                        else:
                            ep_format = []
                            for ep in episodes:
                                try:
                                    ep_id = int(ep.get("id") or 0)
                                    if ep_id in episode_ids:
                                        season = int(ep.get("season", 0))
                                        episode = int(ep.get("episode", 0))
                                        ep_format.append(f"S{season:02d}E{episode:02d}")
                                except (ValueError, TypeError):
                                    continue
                            
                            logger.debug(f"DEBUG: Episodes to search (format SXXEXX): {ep_format}")
                            
                            if ep_format:
                                payload = {"showSlug": slug, "episodes": ep_format, "options": {}}
                                logger.debug(f"DEBUG: Sending backlog search payload: {payload}")
                                res = await async_client.put("/api/v2/search/backlog", json=payload, headers=medusa_headers(api_key))
                                success = res.status_code == 200
                                logger.debug(f"DEBUG: Backlog search request result code: {res.status_code}")
                            else:
                                logger.warning("No valid episodes found to search for.")
                    else:
                        logger.warning(f"Could not resolve series_id for episode IDs: {episode_ids}")
                            
        else:
            logger.debug(f"DEBUG: Search skipped because slug was: {slug}")
        
        if success:
            COMMAND_REGISTRY[command_id]["status"] = "completed"
            COMMAND_REGISTRY[command_id]["result"] = "success"
        else:
            COMMAND_REGISTRY[command_id]["status"] = "failed"
            COMMAND_REGISTRY[command_id]["result"] = "failure"
            
    except Exception as e:
        logger.debug(f"Command Execution Failed: {str(e)}")
        COMMAND_REGISTRY[command_id]["status"] = "failed"
        COMMAND_REGISTRY[command_id]["result"] = "failure"

    return COMMAND_REGISTRY[command_id]

@router.get("/api/v3/command")
async def get_all_commands():
    # Return the full list for Prismarr's history tracking
    return list(COMMAND_REGISTRY.values())

@router.get("/api/v3/command/{command_id}")
async def get_command_status(command_id: int):
    # Retrieve specific command state
    return COMMAND_REGISTRY.get(command_id, {
        "id": command_id, 
        "name": "Unknown", 
        "state": "completed"
    })
