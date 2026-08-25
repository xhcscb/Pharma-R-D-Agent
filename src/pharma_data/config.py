from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    database_url: str = "sqlite:///./data/runtime/pharma.db"
    object_store_root: Path = Path("./data/objects")
    public_export_root: Path = Path("./data/exports")
    metric_ontology_path: Path = Path("./config/metric_ontology.json")
    log_level: str = "INFO"
    worker_poll_seconds: float = 2.0
    worker_lock_seconds: int = 900
    internal_api_key: str | None = None
    inbox_enabled: bool = True
    public_inbox_root: Path = Path("./data/public")
    public_inbox_archive_root: Path = Path("./data/public/_archive")
    public_inbox_metadata_root: Path = Path("./data/public/_metadata")
    public_inbox_quarantine_root: Path = Path("./data/public/_quarantine")
    restricted_inbox_root: Path = Field(
        default=Path("./data/restricted"),
        validation_alias=AliasChoices("RESTRICTED_INBOX_ROOT", "INBOX_ROOT"),
    )
    restricted_inbox_archive_root: Path = Field(
        default=Path("./data/restricted/_archive"),
        validation_alias=AliasChoices("RESTRICTED_INBOX_ARCHIVE_ROOT", "INBOX_ARCHIVE_ROOT"),
    )
    restricted_inbox_metadata_root: Path = Field(
        default=Path("./data/restricted/_metadata"),
        validation_alias=AliasChoices("RESTRICTED_INBOX_METADATA_ROOT", "INBOX_METADATA_ROOT"),
    )
    restricted_inbox_quarantine_root: Path = Field(
        default=Path("./data/restricted/_quarantine"),
        validation_alias=AliasChoices(
            "RESTRICTED_INBOX_QUARANTINE_ROOT",
            "INBOX_QUARANTINE_ROOT",
        ),
    )
    inbox_archive_mode: Literal["move", "copy", "none"] = "move"
    inbox_poll_seconds: float = Field(default=10.0, ge=1.0)
    inbox_settle_seconds: float = Field(default=5.0, ge=0.0)
    authoritative_source_catalog_path: Path = Path("./config/authoritative_sources.json")

    # MinerU runs as an isolated service so its CUDA/Python dependency graph does not
    # contaminate the application environment. Restricted documents may only use
    # explicitly trusted private endpoints.
    mineru_enabled: bool = True
    mineru_required: bool = False
    mineru_execution_mode: Literal["local", "remote"] = "local"
    mineru_api_url: str = "http://127.0.0.1:18010"
    mineru_cpu_api_url: str | None = None
    mineru_backend: Literal["pipeline", "vlm-http-client", "hybrid-http-client"] = (
        "pipeline"
    )
    mineru_server_url: str | None = None
    mineru_device: str = "cuda"
    mineru_max_concurrency: int = Field(default=1, ge=1, le=32)
    mineru_virtual_vram_size: int = Field(default=3, ge=1)
    mineru_page_batch_size: int = Field(default=1, ge=1, le=100)
    mineru_timeout_seconds: float = Field(default=1800.0, ge=5)
    mineru_node_id: str = "local-gpu-0"
    mineru_api_key: str | None = None
    mineru_trusted_hosts: str = "127.0.0.1,localhost"
    mineru_allowed_access_classes: str = "public,restricted"
    mineru_raw_output_root: Path = Path("./data/parser_outputs/mineru")
    mineru_return_images: bool = True
    mineru_max_image_bytes: int = Field(default=25 * 1024 * 1024, ge=1024)
    mineru_cpu_fallback: bool = True
    pp_structure_fallback: bool = True
    visual_semantics_enabled: bool = True
    visual_semantics_required: bool = True
    visual_semantics_min_confidence: float = Field(default=0.85, ge=0, le=1)

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
        self.mineru_raw_output_root.mkdir(parents=True, exist_ok=True)
        if self.inbox_enabled:
            for path in (
                self.public_inbox_root,
                self.public_inbox_archive_root,
                self.public_inbox_metadata_root,
                self.public_inbox_quarantine_root,
                self.restricted_inbox_root,
                self.restricted_inbox_archive_root,
                self.restricted_inbox_metadata_root,
                self.restricted_inbox_quarantine_root,
            ):
                path.mkdir(parents=True, exist_ok=True)
        if self.database_url.startswith("sqlite:///"):
            Path(self.database_url.removeprefix("sqlite:///")).parent.mkdir(
                parents=True, exist_ok=True
            )

    def mineru_trusted_host_set(self) -> set[str]:
        return {
            item.strip().casefold()
            for item in self.mineru_trusted_hosts.split(",")
            if item.strip()
        }

    def mineru_allowed_access_class_set(self) -> set[str]:
        return {
            item.strip().casefold()
            for item in self.mineru_allowed_access_classes.split(",")
            if item.strip()
        }

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
