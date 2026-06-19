from functools import lru_cache
from pathlib import Path
from typing import ClassVar

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    default_backend_sentry_dsn: ClassVar[str] = (
        "https://7affebd49896c5543ade3ac956d3720a@"
        "o4511214385364992.ingest.us.sentry.io/4511591611695104"
    )

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
    sync_local_database_url: str | None = None
    sync_prod_database_url: str | None = None
    sync_tables: str = "all"
    sync_batch_size: int = Field(default=500, ge=1)
    sync_strategy: str = "auto"
    sync_trust_target_watermark: bool = False
    max_scan_upload_mb: int = Field(default=12, ge=1, le=100)
    ewg_attribution_text: str = "Contains information from EWG Skin Deep."
    ewg_user_agent: str = "BeautyProductVerifier/0.1 (local-dev@example.com)"
    sentry_dsn: str | None = None
    sentry_traces_sample_rate: float = Field(default=0.1, ge=0.0, le=1.0)
    sentry_profiles_sample_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    sentry_release: str | None = None

    model_config = SettingsConfigDict(env_prefix="BPV_", env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def resolved_sentry_dsn(self) -> str | None:
        if self.sentry_dsn:
            return self.sentry_dsn
        if self.env == "production":
            return self.default_backend_sentry_dsn
        return None


@lru_cache
def get_settings() -> Settings:
    return Settings()
