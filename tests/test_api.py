import pytest
from unittest.mock import patch
from gorgontarget.utils import extract_clean_year, extract_clean_integer_id

@pytest.mark.asyncio
async def test_root_index(async_app_client):
    response = await async_app_client.get("/")
    assert response.status_code == 200
    assert response.json() == {"status": "running", "service": "GorgonTarget Stateless Proxy"}

@pytest.mark.asyncio
async def test_missing_auth_rejected(async_app_client):
    response = await async_app_client.get("/api/v3/system/status")
    assert response.status_code == 401
    assert "Missing API Key" in response.json()["detail"]

@pytest.mark.asyncio
async def test_get_system_tasks(async_app_client):
    response = await async_app_client.get("/api/v3/system/task", headers={"X-Api-Key": "testkey"})
    
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0
    assert data[0]["name"] == "CheckForUpdates"

@pytest.mark.asyncio
@patch("gorgontarget.routes.system.core_system_status")
async def test_system_status(mock_core_status, async_app_client):
    # Mock the internal function so no real network requests are made
    mock_core_status.return_value = {
        "version": "3.0.10.1567",
        "startupPath": "/app",
        "appData": "/config",
        "osName": "linux",
        "osVersion": "alpine",
        "isNetCore": True,
        "appName": "Sonarr"
    }
    
    response = await async_app_client.get("/api/v3/system/status", headers={"X-Api-Key": "testkey"})
    
    assert response.status_code == 200
    data = response.json()
    assert data["appName"] == "Sonarr"
    assert data["version"] == "3.0.10.1567"
    assert data["startupPath"] == "/app"
    assert data["osName"] == "linux"

@pytest.mark.asyncio
@patch("gorgontarget.routes.series.core_all_series")
async def test_get_series(mock_core_series, async_app_client):
    # Mock the new core_all_series function
    mock_core_series.return_value = [{
        "id": 12345,
        "tvdbId": 12345,
        "title": "Test Show",
        "monitored": True
    }]
    
    response = await async_app_client.get("/api/v3/series", headers={"X-Api-Key": "testkey"})
    
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["title"] == "Test Show"
    assert data[0]["tvdbId"] == 12345
    assert data[0]["monitored"] is True

def test_translator_extract_year():
    assert extract_clean_year({"year": 2026}) == 2026
    assert extract_clean_year({"startYear": {"year": 2025}}) == 2025
    assert extract_clean_year({"year": "invalid"}) == 0
