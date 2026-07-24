from fastapi import APIRouter, Depends, HTTPException, Query
from ..utils import get_medusa_key, medusa_headers, async_client, logger

router = APIRouter()

@router.delete("/api/v3/queue/{id}")
async def delete_queue_item(id: int, api_key: str = Depends(get_medusa_key), block: bool = Query(False)):
    """
    Remove an item from the queue.
    """
    logger.debug(f"Request to delete queue item {id} (block: {block})")
    
    # Based on analysis, DELETE /api/v2/queue/{id} is the endpoint
    res = await async_client.delete(f"/api/v2/queue/{id}", headers=medusa_headers(api_key))
    
    if res.status_code == 200:
        return {"status": "success"}
    else:
        logger.error(f"Failed to delete queue item {id}: {res.status_code} {res.text}")
        raise HTTPException(status_code=500, detail="Failed to delete queue item")
