from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from pydantic import BaseModel
from datetime import datetime
import time
from ..utils import get_medusa_key, medusa_headers, logger, async_client, COMMAND_REGISTRY

router = APIRouter()

class SonarrCommand(BaseModel):
    name: str
    seriesId: Optional[int] = None

@router.post("/api/v3/command")
async def execute_command(command: SonarrCommand, api_key: str = Depends(get_medusa_key)):
    # Generate a unique integer ID
    command_id = abs(hash(f"{command.name}-{command.seriesId}-{time.time()}")) % 10000
    
    # Set initial state
    COMMAND_REGISTRY[command_id] = {
        "id": command_id,
        "name": command.name,
        "state": "queued",
        "startedOn": datetime.utcnow().isoformat() + "Z"
    }

    # Dispatch to Medusa in the background without blocking the UI
    try:
        from ..client import MedusaClient
        client = MedusaClient(api_key)
        
        # Resolve slug for command
        slug = None
        if command.seriesId:
            from ..cache import series_map_cache
            slug = await series_map_cache.get(f"map_{command.seriesId}") or str(command.seriesId)
        
        success = False
        if slug:
            if command.name == "RefreshSeries":
                # Maps to updateShow
                url = f"/home/updateShow?showslug={slug}"
                res = await async_client.get(url, headers=medusa_headers(api_key))
                success = res.status_code == 200
            elif command.name in ["RescanSeries", "SeriesSearch"]:
                # Maps to refreshShow
                url = f"/home/refreshShow?showslug={slug}"
                res = await async_client.get(url, headers=medusa_headers(api_key))
                success = res.status_code == 200
        elif command.name == "CheckForUpdates":
            res = await async_client.post("/api/v2/system/operation", json={"command": "check_update"}, headers=medusa_headers(api_key))
            success = res.status_code == 200
        
        if success:
            COMMAND_REGISTRY[command_id]["state"] = "completed"
        else:
            COMMAND_REGISTRY[command_id]["state"] = "failed"
            
    except Exception as e:
        logger.debug(f"Command Execution Failed: {str(e)}")
        COMMAND_REGISTRY[command_id]["state"] = "failed"

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
