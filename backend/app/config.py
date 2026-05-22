from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: str
    runpod_api_key: str
    runpod_endpoint_id: str
    database_url: str = "sqlite+aiosqlite:///./data/app.db"
    output_dir: str = "./output"
    workflow_path: str = "./app/workflows/default.json"
    allowed_origin: str = "http://localhost:5173"


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
