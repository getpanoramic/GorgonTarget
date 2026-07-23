import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "GorgonTarget Stateless Proxy"
    version: str = "4.0.0"
    medusa_url: str = os.getenv("MEDUSA_URL", "http://localhost:8081")
    medusa_username: Optional[str] = os.getenv("MEDUSA_USERNAME")
    medusa_password: Optional[str] = os.getenv("MEDUSA_PASSWORD")
    timeout: float = 30.0
    cache_ttl_seconds: int = 300

    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()
