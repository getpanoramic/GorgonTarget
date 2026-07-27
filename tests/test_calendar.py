import pytest
from unittest.mock import patch, AsyncMock

@pytest.mark.asyncio
@patch("gorgontarget.routes.calendar.async_client")
async def test_get_calendar(mock_async_client, async_app_client):
    # Setup mock
    mock_response = AsyncMock()
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
    
    # Patch the get method of the mocked async_client
    mock_async_client.get.return_value = mock_response
    
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
