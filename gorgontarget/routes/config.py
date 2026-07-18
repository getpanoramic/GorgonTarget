from fastapi import APIRouter, Depends
from ..utils import get_medusa_key, logger

router = APIRouter()

@router.get("/api/v3/config/host")
async def get_config_host(api_key: str = Depends(get_medusa_key)):
    # Return placeholder as Medusa doesn't have a 1:1 host config mapping
    return {"id": 1, "port": 80, "ssl": False, "username": "", "password": ""}

@router.get("/api/v3/config/indexer")
async def get_config_indexer(api_key: str = Depends(get_medusa_key)):
    # Return empty list as a placeholder
    return []

@router.get("/api/v3/config/downloadclient")
async def get_config_downloadclient(api_key: str = Depends(get_medusa_key)):
    # Return empty list as a placeholder
    return []

@router.get("/api/v3/config/importlist")
async def get_config_importlist(api_key: str = Depends(get_medusa_key)):
    # Return empty list as a placeholder
    return []
