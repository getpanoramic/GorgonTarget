import pytest
from unittest.mock import MagicMock, AsyncMock
from gorgontarget.main import app
from gorgontarget.utils import get_async_client

@pytest.mark.asyncio
async def test_get_calendar(async_app_client):
    # Setup mock data
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "today": [{
            "localAirTime": "2026-07-27T20:00:00Z",
            "tvdbid": 12345,
            "showSlug": "show-slug",
            "season": 1,
            "episode": 1,
            "epName": "Test Episode",
            "showName": "Test Show",
            "showStatus": "continuing"
        }]
    }
    
    # Mock client
    mock_client = MagicMock()
    # The get method needs to be an async function returning the mock_response
    mock_client.get = AsyncMock(return_value=mock_response)
    
    # Override dependency
    app.dependency_overrides[get_async_client] = lambda: mock_client
    
    try:
        response = await async_app_client.get(
            "/api/v3/calendar?start=2026-07-01T00:00:00Z&end=2026-07-31T23:59:59Z", 
            headers={"X-Api-Key": "testkey"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["title"] == "Test Episode"
        assert data[0]["series"]["title"] == "Test Show"
        assert data[0]["seriesId"] == 12345
    finally:
        # Clean up override
        app.dependency_overrides.clear()
