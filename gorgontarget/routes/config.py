from fastapi import APIRouter, Depends
from ..utils import get_medusa_key, logger
from ..client import MedusaClient

router = APIRouter()

async def get_medusa_client(api_key: str = Depends(get_medusa_key)):
    return MedusaClient(api_key)

@router.get("/api/v3/config/host")
async def get_config_host(client: MedusaClient = Depends(get_medusa_client)):
    config = await client.get_system_config()
    web_interface = config.get("main", {}).get("webInterface", {})
    return {
        "id": 1,
        "port": web_interface.get("port"),
        "ssl": web_interface.get("httpsEnable"),
        "username": web_interface.get("username"),
        "password": web_interface.get("password")
    }

@router.get("/api/v3/config/indexer")
async def get_config_indexer(client: MedusaClient = Depends(get_medusa_client)):
    config = await client.get_system_config()
    indexers = config.get("indexers", {}).get("indexers", {})
    return [
        {"id": data.get("id"), "name": name, "enabled": data.get("enabled")}
        for name, data in indexers.items()
    ]

@router.get("/api/v3/config/downloadclient")
async def get_config_downloadclient(client: MedusaClient = Depends(get_medusa_client)):
    config = await client.get_system_config()
    clients = config.get("clients", {})
    # This might need refinement based on actual expected return structure
    return clients

@router.get("/api/v3/config/importlist")
async def get_config_importlist(client: MedusaClient = Depends(get_medusa_client)):
    # Import list is not clearly defined in the config example, returning empty list
    return []
