from functools import lru_cache
from urllib.parse import quote_plus

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration comes from environment variables (or backend/.env when running natively)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Peak HRMS"
    environment: str = "local"  # local | dev | test (laptops, synthetic data) · qa | prod (real client data)
    version: str = "1.1.0"

    # Client (tenant). One deployment and ONE DATABASE per client (decision 0006).
    #   TENANT          client code, e.g. HV (Hotel Vivek)
    #   TENANT_PACKAGE  Python package with the client's settings and demo data, e.g. hotel_vivek
    #   TENANT_PATH     folder that contains that package (native runs), e.g. ../../hotel_vivek_backend
    tenant: str = ""
    tenant_package: str = ""
    tenant_path: str = ""

    # Empty = SQLite file for quick native runs, named after the client (hrms_hv.db).
    database_url: str = ""
    # On AWS the database password comes from Secrets Manager as separate values; DATABASE_URL is built from them.
    db_host: str | None = None
    db_port: int = 5432
    db_name: str = ""  # empty = hrms_<tenant>, e.g. hrms_hv
    db_username: str | None = None
    db_password: str | None = None

    # Sign-in: "local" = passwords kept by this app (quick start, tests); "cognito" = AWS Cognito
    # (cognito-local in Docker, the real user pool on AWS).
    auth_mode: str = "local"
    jwt_secret: str = "change-me-local-only"
    jwt_minutes: int = 480
    cognito_region: str = "ap-south-1"
    cognito_endpoint: str | None = None  # e.g. http://cognito:9229 for cognito-local; empty on AWS
    cognito_user_pool_id: str | None = None
    cognito_client_id: str | None = None
    cognito_bootstrap: bool = False  # create the pool, client and groups on start (cognito-local only)

    # Fernet key for PAN and bank account. Generate: python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
    field_encryption_key: str = ""

    biometric_adapter: str = "excel"  # excel | mock | http
    biometric_api_url: str | None = None
    biometric_api_key: str | None = None

    storage_dir: str = "./storage"
    s3_bucket: str | None = None

    cors_origins: str = "http://localhost:5173,http://localhost:8080"
    seed_demo: bool = True  # ignored outside local/dev/test
    demo_password: str = "Peak@12345"
    demo_employee_count: int = 256

    # Monitoring (SCRUM-130)
    monitor_interval_seconds: int = 60  # 0 = no background checks (tests)
    monitor_web_url: str = ""  # e.g. http://web/healthz inside Docker
    monitor_biometric_stale_hours: int = 26  # no new punches for this long = degraded
    monitor_alert_emails: str = ""  # comma-separated; alerts are queued in the outbox for them
    monitor_keep_days: int = 7

    @model_validator(mode="after")
    def _db_from_parts(self) -> "Settings":
        self.tenant = self.tenant.strip().upper()
        if not self.db_name:
            self.db_name = f"hrms_{self.tenant.lower()}" if self.tenant else "hrms"
        if self.db_host and self.db_username and self.db_password:
            self.database_url = (f"postgresql+psycopg://{quote_plus(self.db_username)}:{quote_plus(self.db_password)}"
                                 f"@{self.db_host}:{self.db_port}/{self.db_name}")
        elif not self.database_url:
            self.database_url = f"sqlite:///./{self.db_name}.db"
        return self

    @property
    def demo_data_allowed(self) -> bool:
        """Synthetic data only on laptops; QA and production hold real client data only."""
        return self.environment.lower() in ("local", "dev", "test")

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
