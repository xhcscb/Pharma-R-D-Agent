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
    openfda_base_url: str = "https://api.fda.gov"
    openfda_api_key: str | None = None
    sec_data_base_url: str = "https://data.sec.gov"
    sec_archives_base_url: str = "https://www.sec.gov/Archives/edgar/data"
    project_contact_email: str | None = None
    sec_user_agent: str | None = None
    http_user_agent: str = "pharma-analyst-data/0.2"
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

    def identified_sec_user_agent(self) -> str:
        """返回 SEC 自动访问政策要求的可联系访问标识。"""
        if self.sec_user_agent and "@" in self.sec_user_agent:
            return self.sec_user_agent
        if self.project_contact_email and "@" in self.project_contact_email:
            return f"pharma-analyst-data/0.2 ({self.project_contact_email})"
        raise ValueError(
            "SEC EDGAR 要求可联系的访问标识。请设置 PROJECT_CONTACT_EMAIL，"
            "或设置包含联系邮箱的 SEC_USER_AGENT。"
        )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_local_directories()
    return settings
