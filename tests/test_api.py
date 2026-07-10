import pytest
from unittest.mock import patch
from gorgontarget.translator import MedusaTranslator

pytestmark = pytest.mark.asyncio

async def test_root_index(async_app_client):
    response = await async_app_client.get("/")
    assert response.status_code == 200
    assert response.json() == {"status": "running", "service": "GorgonTarget Stateless Proxy"}

async def test_missing_auth_rejected(async_app_client):
    response = await async_app_client.get("/api/v3/system/status")
    assert response.status_code == 401
    assert "Missing API Key" in response.json()["detail"]

@patch("gorgontarget.client.MedusaClient.get_system_config")
@patch("gorgontarget.client.MedusaClient.detect_capabilities")
async def test_system_status(mock_detect, mock_config, async_app_client, mock_medusa_system_response):
    mock_detect.return_value = {"v2_rest": True}
    mock_config.return_value = mock_medusa_system_response
    
    response = await async_app_client.get("/api/v3/system/status", headers={"X-Api-Key": "testkey"})
    
    assert response.status_code == 200
    data = response.json()
    assert data["appName"] == "Sonarr"
    assert data["version"] == "3.0.10.1567"
    assert data["startupPath"] == "/app"
    assert data["osName"] == "linux"

@patch("gorgontarget.client.MedusaClient.get_all_series")
@patch("gorgontarget.client.MedusaClient.detect_capabilities")
async def test_get_series(mock_detect, mock_get_series, async_app_client, mock_medusa_series_response):
    mock_detect.return_value = {"v2_rest": True}
    mock_get_series.return_value = mock_medusa_series_response
    
    response = await async_app_client.get("/api/v3/series", headers={"X-Api-Key": "testkey"})
    
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["title"] == "Test Show"
    assert data[0]["tvdbId"] == 12345
    assert data[0]["monitored"] is True

def test_translator_extract_year():
    assert MedusaTranslator.extract_clean_year({"year": 2026}) == 2026
    assert MedusaTranslator.extract_clean_year({"startYear": {"year": 2025}}) == 2025
    assert MedusaTranslator.extract_clean_year({"year": "invalid"}) == 0
