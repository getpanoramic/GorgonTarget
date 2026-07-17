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
        # Simplistic resolution: iterate over all series episodes to find the series ID
        # This is expensive but necessary if the client doesn't provide seriesId.
        from ..client import MedusaClient
        client = MedusaClient(api_key)
        series_list = await client.get_all_series()
        for s in series_list:
            # DEBUG: Inspect the series object structure
            logger.debug(f"DEBUG: Checking series object: {s}")
            s_id = extract_clean_integer_id(s)
            logger.debug(f"DEBUG: Extracted s_id: {s_id}")
            episodes = await client.get_episodes(s_id)
            for ep in episodes:
                # Need to match the same ID generation used in episodes.py
                ep_id = int(extract_id_from_str(f"{s_id}{ep.get('season', 0)}{ep.get('episode', 0)}") or 0)
                logger.debug(f"DEBUG: Checking ep_id: {ep_id} against input: {episode_ids}")
                if ep_id in episode_ids:
                    series_id = s_id
                    break
            if series_id:
                break
        logger.debug(f"DEBUG: Resolved series_id from episodeIds: {series_id}")
    
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
        client = MedusaClient(api_key)
        
        # Resolve slug for command
        slug = None
        if series_id:
            from ..cache import series_map_cache
            slug = await series_map_cache.get(f"map_{series_id}") or str(series_id)
        
        logger.debug(f"DEBUG: Pre-execution slug: {slug}, name: {name}")
        
        success = False
        if slug:
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
                episode_ids = command.get("episodeIds", [])
                logger.debug(f"DEBUG: EpisodeSearch triggered for IDs: {episode_ids}, series_id: {series_id}")
                if episode_ids:
                    from ..client import MedusaClient
                    client = MedusaClient(api_key)
                    
                    # Get all series to find the show slug
                    series_list = await client.get_all_series()
                    series_id = None
                    show_slug = None
                    for s in series_list:
                        s_id = s.get("id", {}).get("tvdb") or s.get("id", {}).get("tvmaze")
                        if not s_id: continue
                        
                        episodes = await client.get_episodes(s_id)
                        if episodes:
                            logger.debug(f"DEBUG: Sample episode structure for {s.get('title')}: {episodes[0]}")
                        
                        for ep in episodes:
                            # Use Medusa's internal episode ID if available for matching
                            # Or regenerate based on what we have
                            ep_id = int(ep.get("id") or 0)
                            
                            # DEBUG: log what we are checking
                            # logger.debug(f"DEBUG: Checking ep_id: {ep_id} against {episode_ids}")
                            
                            if ep_id in episode_ids:
                                series_id = s_id
                                show_slug = s.get("id", {}).get("slug")
                                logger.debug(f"DEBUG: Found match! series_id: {series_id}, show_slug: {show_slug}")
                                break
                        if series_id:
                            break
                    
                    if show_slug:
                        episodes = await client.get_episodes(series_id)
                        ep_format = []
                        for ep in episodes:
                            translated_id = int(extract_id_from_str(f"{series_id}{ep.get('season', 0)}{ep.get('episode', 0)}") or 0)
                            if translated_id in episode_ids:
                                ep_format.append(f"S{ep.get('season'):02d}E{ep.get('episode'):02d}")
                        
                        logger.debug(f"DEBUG: Episodes to search (format SXXEXX): {ep_format}")
                        
                        if ep_format:
                            payload = {"showSlug": show_slug, "episodes": ep_format, "options": {}}
                            logger.debug(f"DEBUG: Sending backlog search payload: {payload}")
                            res = await async_client.put("/api/v2/search/backlog", json=payload, headers=medusa_headers(api_key))
                            success = res.status_code == 200
                            logger.debug(f"DEBUG: Backlog search request result code: {res.status_code}")
                            
        else:
            logger.debug(f"DEBUG: Search skipped because slug was: {slug}")
                            
        if name == "CheckForUpdates" and not success:
            res = await async_client.post("/api/v2/system/operation", json={"command": "check_update"}, headers=medusa_headers(api_key))
            success = res.status_code == 200
        
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
