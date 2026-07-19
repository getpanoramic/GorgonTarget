import pytest
import asyncio
import time
from unittest.mock import patch, AsyncMock, MagicMock
from gorgontarget.translator import MedusaTranslator

@pytest.mark.asyncio
async def test_get_episodes_concurrency(async_app_client):
    # Mock MedusaClient and MedusaTranslator
    with patch("gorgontarget.routes.episodes.MedusaClient") as mock_client_class, \
         patch("gorgontarget.routes.episodes.MedusaTranslator") as mock_translator:
        
        mock_client = AsyncMock()
        mock_client_class.return_value = mock_client
        
        # Mock get_all_series
        mock_client.get_all_series.return_value = [
            {"id": {"tvdb": 1}, "ids": {"tvdb": 1}},
            {"id": {"tvdb": 2}, "ids": {"tvdb": 2}}
        ]
        
        # Mock get_episodes with a delay
        async def side_effect(s_id):
            await asyncio.sleep(0.1)
            return [{"id": s_id * 10, "season": 1, "episode": 1}]
        
        mock_client.get_episodes.side_effect = side_effect
        
        # Mock Translator
        def translate_side_effect(ep, s_id):
            mock_ep = MagicMock()
            mock_ep.id = ep["id"]
            mock_ep.dict.return_value = {"id": ep["id"], "seriesId": s_id}
            return mock_ep
        
        mock_translator.to_sonarr_episode.side_effect = translate_side_effect
        
        start_time = time.time()
        # Call the endpoint
        response = await async_app_client.get("/api/v3/episode?episodeIds=10&episodeIds=20", headers={"X-Api-Key": "testkey"})
        end_time = time.time()
        
        assert response.status_code == 200
        # It should take ~0.1s, not 0.2s. 0.15s is a safe threshold.
        assert end_time - start_time < 0.15
