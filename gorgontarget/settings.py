import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "GorgonTarget Stateless Proxy"
    version: str = "4.0.0"
    medusa_url: str = os.getenv("MEDUSA_URL", "http://localhost:8081")
    timeout: float = 30.0
    cache_ttl_seconds: int = 300

    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()
