from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    database_url: str = "sqlite:///./data/runtime/pharma.db"
    object_store_root: Path = Path("./data/objects")
    public_export_root: Path = Path("./data/exports")
    log_level: str = "INFO"
    worker_poll_seconds: float = 2.0
    worker_lock_seconds: int = 900
    internal_api_key: str | None = None

    clinicaltrials_base_url: str = "https://clinicaltrials.gov/api/v2"
    http_user_agent: str = "pharma-analyst-data/0.1 research-contact@example.invalid"
    http_rate_limit_per_second: float = Field(default=1.0, gt=0)

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "change-me-neo4j"
    milvus_uri: str = "http://localhost:19530"
    timescale_url: str = "postgresql+psycopg://pharma:pharma@localhost:5433/pharma_timeseries"
    elasticsearch_url: str = "http://localhost:9200"
    embedding_model: str = "BAAI/bge-m3"
    embedding_dimension: int = 1024
    hf_token: str | None = None

    def ensure_local_directories(self) -> None:
        self.object_store_root.mkdir(parents=True, exist_ok=True)
        self.public_export_root.mkdir(parents=True, exist_ok=True)
        if self.database_url.startswith("sqlite:///"):
            Path(self.database_url.removeprefix("sqlite:///")).parent.mkdir(
                parents=True, exist_ok=True
            )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_local_directories()
    return settings
