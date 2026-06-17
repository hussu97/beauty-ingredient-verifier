from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Beauty Product Verifier"
    env: str = "local"
    database_url: str = "sqlite:///./storage/beauty_product_verifier.sqlite3"
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"
    storage_dir: Path = Path("./storage")
    auto_create_tables: bool = True
    bootstrap_demo_data: bool = True
    open_beauty_facts_user_agent: str = "BeautyProductVerifier/0.1 (local-dev@example.com)"
    enable_live_open_beauty_facts_lookup: bool = True
    enable_optional_ml: bool = False
    enable_sqlite_vec: bool = True
    ocr_language: str = "en"
    image_embedding_model: str = "sentence-transformers/clip-ViT-B-32"
    image_download_timeout_seconds: float = 20.0
    max_scan_upload_mb: int = Field(default=12, ge=1, le=100)

    model_config = SettingsConfigDict(env_prefix="BPV_", env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
