import pytest
from unittest.mock import patch, AsyncMock
from gorgontarget.translator import MedusaTranslator

@pytest.mark.asyncio
async def test_get_episodes_endpoint(async_app_client):
    # Mock MedusaClient and MedusaTranslator
    with patch("gorgontarget.routes.episodes.MedusaClient") as mock_client_class, \
         patch("gorgontarget.translator.MedusaTranslator.to_sonarr_episode") as mock_to_sonarr:
        
        mock_client = AsyncMock()
        mock_client_class.return_value = mock_client
        
        # Setup mock episodes
        mock_client.get_episodes.return_value = [{"id": 1, "title": "Test Ep"}]
        
        # Setup mock translator return (a dict, as it was returning a dict in reality)
        mock_to_sonarr.return_value = {
            "id": 1,
            "seriesId": 123,
            "title": "Test Ep",
            "seasonNumber": 1,
            "episodeNumber": 1
        }
        
        response = await async_app_client.get(
            "/api/v3/episode?seriesId=123", 
            headers={"X-Api-Key": "testkey"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["title"] == "Test Ep"
