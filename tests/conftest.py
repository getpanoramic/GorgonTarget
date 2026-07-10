import pytest
import httpx
from httpx import AsyncClient
from gorgontarget.main import app

@pytest.fixture
def mock_medusa_system_response():
    return {
        "main": {
            "version": "3.0.10.1567",
            "rootDir": "/app",
            "dataDir": "/config"
        }
    }

@pytest.fixture
def mock_medusa_series_response():
    return [
        {
            "id": {"tvdb": 12345},
            "title": "Test Show",
            "status": "continuing",
            "overview": "A show about testing.",
            "year": 2026,
            "path": "/tv/Test Show",
            "paused": False,
            "ids": {"tvdb": 12345, "tmdb": 67890}
        }
    ]

@pytest.fixture
async def async_app_client():
    # Use ASGITransport to properly bind the FastAPI app in modern httpx versions
    transport = httpx.ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
