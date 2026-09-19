from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MODELER_")

    tenancy_mode: Literal["saas-pooled", "cro-silo", "onprem-single"] = "saas-pooled"
    database_url: str = "postgresql+asyncpg://modeler:modeler@localhost:5432/modeler"
    temporal_address: str | None = None
    temporal_namespace: str = "default"
    object_store_uri: str = "s3://modeler-dev"
    results_root: str = ""  # where ingested result Parquet lives; a file:// root serves reads directly
    read_root: str = ""  # projects/CPF read models live here (a file:// or plain path root, per tenant)
    # Keycloak OIDC (T-06 / D10); auth is enabled when the JWKS URL is set.
    oidc_jwks_url: str | None = None
    oidc_issuer: str | None = None
    oidc_audience: str = "modeler-api"
    # DEV ONLY: when true, a fixed development principal is accepted for any bearer token, so the web app can
    # run against live read APIs without Keycloak. Never enable outside local development.
    dev_auth: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
