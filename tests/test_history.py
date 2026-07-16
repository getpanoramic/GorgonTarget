import pytest
from unittest.mock import patch
import httpx

@pytest.mark.asyncio
@patch("gorgontarget.main.async_client.get")
async def test_get_history_transformation(mock_get, async_app_client):
    """
    Verifies that raw history data is correctly transformed,
    specifically checking seriesId and episodeId extraction/derivation.
    """
    
    # Mocked raw data from log
    mock_raw_data = [
        {
            'id': 64922, 
            'series': 'tvdb71663', 
            'statusName': 'Snatched', 
            'actionDate': 20210301015352,
            'show_name': 'The Simpsons'
        },
        {
            'id': 64923, 
            'series': 'tvdb71663', 
            'statusName': 'Downloaded', 
            'actionDate': 20210301020542,
            'episode_id': 123,
            'show_name': 'The Simpsons'
        }
    ]

    # Mock the internal HTTP client call to /api/v2/history
    mock_response = httpx.Response(200, json=mock_raw_data)
    mock_get.return_value = mock_response
    
    # Call the endpoint
    response = await async_app_client.get("/api/v3/history", headers={"X-Api-Key": "testkey"})
    
    assert response.status_code == 200
    data = response.json()
    
    assert len(data["records"]) == 2
    
    # Validate Item 1: This is now 64923 (index 0 after sort)
    item1 = data["records"][0]
    assert item1["seriesId"] == 71663
    assert item1["episodeId"] == 123
    
    # Validate Item 2: This is now 64922 (index 1 after sort)
    item2 = data["records"][1]
    assert item2["seriesId"] == 71663
    assert item2["episodeId"] == 64922 # Should use item id
