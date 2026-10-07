"""The MODELER_* environment of the orchestrator and the engine worker, read in one place (docs/ARCHITECTURE_BOUNDARIES.md,
rule B5; the API has its own `modeler_api.config.Settings`).

`runtime_env()` reads the environment on every call, so a value set by a deployment script or a test is seen at once. A
field is None when its variable is unset, and each caller keeps the default it had (`env.get("image_digest", "local")`):
today the same variable defaults differently in different places, and choosing one default is the owner's decision
(CHANGELOG, known gap), not a side effect of moving the reads here.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

VARIABLES = {
    "read_root": "MODELER_READ_ROOT",
    "object_store_uri": "MODELER_OBJECT_STORE_URI",
    "engine_command": "MODELER_ENGINE_COMMAND",
    "engine_id": "MODELER_ENGINE_ID",
    "image_digest": "MODELER_IMAGE_DIGEST",
    "engine_cores": "MODELER_ENGINE_CORES",
    "engine_concurrency": "MODELER_ENGINE_CONCURRENCY",
    "resource_class": "MODELER_RESOURCE_CLASS",
    "fit_workers": "MODELER_FIT_WORKERS",
    "memo": "MODELER_MEMO",
    "temporal_address": "MODELER_TEMPORAL_ADDRESS",
    "temporal_namespace": "MODELER_TEMPORAL_NAMESPACE",
    "database_url": "MODELER_DATABASE_URL",
    "s3_endpoint": "MODELER_S3_ENDPOINT",
    "s3_access_key": "MODELER_S3_ACCESS_KEY",
    "s3_secret_key": "MODELER_S3_SECRET_KEY",
    "s3_bucket": "MODELER_S3_BUCKET",
    "s3_region": "MODELER_S3_REGION",
}

# The orchestrator's object store when MODELER_OBJECT_STORE_URI is unset (the API's default differs: known gap).
LOCAL_OBJECT_STORE = "file:///tmp/modeler-object-store"


@dataclass(frozen=True)
class RuntimeSettings:
    read_root: str | None = None
    object_store_uri: str | None = None
    engine_command: str | None = None
    engine_id: str | None = None
    image_digest: str | None = None
    engine_cores: str | None = None
    engine_concurrency: str | None = None
    resource_class: str | None = None
    fit_workers: str | None = None
    memo: str | None = None
    temporal_address: str | None = None
    temporal_namespace: str | None = None
    database_url: str | None = None
    s3_endpoint: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_bucket: str | None = None
    s3_region: str | None = None

    def get(self, name: str, default: str) -> str:
        """The value, or `default` when the variable is unset (a variable set to "" stays "", as before)."""
        value = getattr(self, name)
        return default if value is None else value

    def require(self, name: str) -> str:
        """The value of a variable the process cannot run without (KeyError naming the variable when unset)."""
        value = getattr(self, name)
        if value is None:
            raise KeyError(VARIABLES[name])
        return value

    def object_store_root(self) -> str:
        return self.get("object_store_uri", LOCAL_OBJECT_STORE).rstrip("/")


def runtime_env(environ: Mapping[str, str] | None = None) -> RuntimeSettings:
    """The MODELER_* variables as they are now (`environ` replaces os.environ, e.g. in a test)."""
    environ = os.environ if environ is None else environ
    return RuntimeSettings(**{name: environ.get(variable) for name, variable in VARIABLES.items()})
