"""Settings. Per-client values come from the client's YAML file (CLIENT_CONFIG); environment variables
override them (secrets, URLs set by the deployment).

Decision 0007: one HRMS core, deployed into each client's own AWS account; a client goes live through its
YAML file (database, domain, AWS) and its own backend package. No client name or rule is written here.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import yaml
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


@lru_cache(maxsize=8)
def load_client_yaml(path: str) -> dict[str, Any]:
    """Read a client YAML file. Empty path = no client file (core tests create their clients themselves)."""
    if not path:
        return {}
    p = Path(path)
    if not p.is_file():
        raise RuntimeError(f"CLIENT_CONFIG file not found: {p.resolve()}")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict) or not isinstance(data.get("client"), dict) or not data["client"].get("code"):
        raise RuntimeError(f"{p}: the YAML must have a 'client' section with at least 'code' and 'name'")
    return data


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Peak HRMS"
    environment: str = "local"  # local | dev | test (laptops, synthetic data) · qa | prod (real client data)
    version: str = "2.0.0"

    # The client this deployment serves: its YAML file, and where its backend package lives (native runs).
    client_config: str = ""
    client_package_path: str = ""

    # Empty DATABASE_URL = Postgres from DB_* parts, else a SQLite file named after the client database.
    database_url: str = ""
    db_host: str | None = None
    db_port: int = 5432
    db_name: str = ""
    db_username: str | None = None
    db_password: str | None = None

    auth_mode: str = "cognito"  # cognito | local (local = app-held passwords, for native runs and tests)
    jwt_secret: str = "change-me-local-only"
    jwt_minutes: int = 480
    cognito_region: str = "ap-south-1"
    cognito_endpoint: str = ""  # http://cognito:9229 for cognito-local
    cognito_user_pool_id: str = ""
    cognito_client_id: str = ""
    cognito_bootstrap: bool = False  # create pool, app client and role groups on first start (cognito-local)

    field_encryption_key: str = ""  # Fernet key; required outside local/test
    storage_dir: str = "./storage"
    s3_bucket: str = ""
    cors_origins: str = "http://localhost:5173,http://localhost:8080"

    seed_demo: bool = True  # synthetic demo data; ignored outside local/dev/test
    demo_password: str = "Peak@12345"

    @model_validator(mode="after")
    def _derive(self) -> "Settings":
        conf = load_client_yaml(self.client_config)
        if not self.db_name:
            self.db_name = str((conf.get("database") or {}).get("name") or "hrms")
        if self.db_host and self.db_username and self.db_password:
            self.database_url = (f"postgresql+psycopg://{quote_plus(self.db_username)}:{quote_plus(self.db_password)}"
                                 f"@{self.db_host}:{self.db_port}/{self.db_name}")
        elif not self.database_url:
            self.database_url = f"sqlite:///./{self.db_name}.db"
        return self

    @property
    def client(self) -> dict[str, Any]:
        """The whole client YAML (empty dict when CLIENT_CONFIG is not set)."""
        return load_client_yaml(self.client_config)

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def demo_data_allowed(self) -> bool:
        """Synthetic data only on laptops; QA and production hold real client data only."""
        return self.environment.lower() in ("local", "dev", "test")


@lru_cache
def get_settings() -> Settings:
    return Settings()
