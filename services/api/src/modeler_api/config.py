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


@lru_cache
def get_settings() -> Settings:
    return Settings()
