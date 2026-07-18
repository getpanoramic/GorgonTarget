import pytest
from unittest.mock import patch, AsyncMock
from gorgontarget.client import MedusaClient

@pytest.mark.asyncio
@patch("gorgontarget.routes.config.MedusaClient")
async def test_get_config_host(mock_medusa_client_class, async_app_client):
    # Setup mock
    mock_client = AsyncMock()
    mock_medusa_client_class.return_value = mock_client
    mock_client.get_system_config.return_value = {
        "main": {
            "webInterface": {
                "port": 8081,
                "httpsEnable": False,
                "username": "user",
                "password": "password",
                "apiKey": "testkey"
            },
            "launchBrowser": True,
            "autoUpdate": True
        }
    }
    
    # Call endpoint
    response = await async_app_client.get("/api/v3/config/host", headers={"X-Api-Key": "testkey"})
    
    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["port"] == 8081
    assert data["enableSsl"] is False
    assert data["username"] == "user"
    assert data["apiKey"] == "testkey"
    assert data["launchBrowser"] is True

@pytest.mark.asyncio
@patch("gorgontarget.routes.config.MedusaClient")
async def test_get_config_indexer(mock_medusa_client_class, async_app_client):
    # Setup mock
    mock_client = AsyncMock()
    mock_medusa_client_class.return_value = mock_client
    mock_client.get_system_config.return_value = {
        "indexers": {
            "indexers": {
                "tvdb": {"id": 1, "enabled": True},
                "tvmaze": {"id": 3, "enabled": False}
            }
        }
    }
    
    # Call endpoint
    response = await async_app_client.get("/api/v3/config/indexer", headers={"X-Api-Key": "testkey"})
    
    # Assert
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert {"id": 1, "name": "tvdb", "enabled": True} in data
    assert {"id": 3, "name": "tvmaze", "enabled": False} in data
