from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: str
    runpod_api_key: str
    runpod_endpoint_id: str
    database_url: str = "sqlite+aiosqlite:///./data/app.db"
    output_dir: str = "./output"
    workflow_path: str = "./app/workflows/default.json"
    agents_dir: str = "./app/agents"
    allowed_origin: str = "http://localhost:5173"

    # Image storage backend (§ 8.7). `local` writes under `output_dir` and
    # serves via the `/static` mount; `r2` writes to Cloudflare R2 and serves
    # directly from the bucket's public r2.dev URL. R2 fields below are
    # validated at startup (services/storage.py) only when backend == "r2".
    image_store_backend: Literal["local", "r2"] = "local"
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = ""
    r2_public_base: str = ""
    r2_prefix: str = "dev"


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
