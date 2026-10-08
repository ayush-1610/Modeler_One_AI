"""The MODELER_* environment of the orchestrator and the engine worker, read in one place (docs/ARCHITECTURE_BOUNDARIES.md,
rule B5; the API has its own `modeler_api.config.Settings`).

`runtime_env()` reads the environment on every call, so a value set by a deployment script or a test is seen at once. A
field is None when its variable is unset.

One default per variable (the owner's decision, 2026-10-08): development defaults that let a laptop run without
configuration, and a production deployment (MODELER_DEPLOYMENT=production) that must set them and refuses to start
otherwise (`production_problems`):
- object store: `LOCAL_OBJECT_STORE` for the API and the orchestrator alike; production sets it;
- engine command: production sets it; development falls back to the caller's default (the stub engine for the
  orchestrator, which every page labels a software fixture);
- engine id: named by the engine itself (`default_engine_id`): the qualified catalog's `ospsuite-<version>` for PK-Sim,
  `software-fixture:<name>` for a fixture, so no record of a fixture run names PK-Sim;
- engine digest: production refuses the all-zero placeholder, which exists for tests and development only (a run
  carrying it is never evidence). A container records its image digest (`sha256:<hex>`); the server, which runs PK-Sim
  from its own installation, records the digest of its harvested engine catalog (`catalog:sha256:<hex>`).
"""

from __future__ import annotations

import os
import re
import shlex
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
    "deployment": "MODELER_DEPLOYMENT",
}

# The object store when MODELER_OBJECT_STORE_URI is unset, for the API and the orchestrator alike (development only).
LOCAL_OBJECT_STORE = "file:///tmp/modeler-object-store"
DEPLOYMENTS = ("development", "production")
# The digest of no engine: tests and development only, refused in production; a run carrying it is never evidence.
PLACEHOLDER_DIGEST = "sha256:" + "0" * 64
_DIGEST = re.compile(r"^(catalog:)?sha256:[0-9a-f]{64}$")
# The qualified engine (services/engine-worker/golden/catalog.json `engine.ospsuite`; a test keeps them equal).
QUALIFIED_ENGINE_ID = "ospsuite-12.4.4"
# Engine commands that are software fixtures, not PK-Sim (CLAUDE.md: their numbers are never simulation results).
FIXTURE_ENGINES = ("stub_engine.py", "analytical_engine.py")
PKSIM_ENGINES = ("run_job.R", "docker_engine.sh")


class ConfigurationError(RuntimeError):
    """A production deployment is missing a setting it must not default."""


def engine_kind(command: str) -> str:
    """What an engine command runs: "pksim", "software-fixture" or "unknown"."""
    words = [os.path.basename(w) for w in shlex.split(command)]
    if any(w in FIXTURE_ENGINES for w in words):
        return "software-fixture"
    if any(w in PKSIM_ENGINES for w in words):
        return "pksim"
    return "unknown"


def default_engine_id(command: str) -> str:
    """The engine id a run records when MODELER_ENGINE_ID is unset: the engine names itself."""
    kind = engine_kind(command)
    if kind == "software-fixture":
        fixture = next(w for w in (os.path.basename(w) for w in shlex.split(command)) if w in FIXTURE_ENGINES)
        return f"software-fixture:{fixture.removesuffix('.py')}"
    return QUALIFIED_ENGINE_ID if kind == "pksim" else "unknown"


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
    deployment: str | None = None

    @property
    def production(self) -> bool:
        deployment = self.deployment or "development"
        if deployment not in DEPLOYMENTS:
            raise ConfigurationError(f"MODELER_DEPLOYMENT is {deployment!r}; expected one of {', '.join(DEPLOYMENTS)}")
        return deployment == "production"

    def production_problems(self) -> list[str]:
        """What a production deployment is missing (empty in development, and in a complete production setup)."""
        if not self.production:
            return []
        problems = [f"{VARIABLES[name]} is not set" for name in ("object_store_uri", "engine_command") if not getattr(self, name)]
        digest = self.image_digest
        if not digest:
            problems.append("MODELER_IMAGE_DIGEST is not set (the engine's image or catalog digest)")
        elif digest == PLACEHOLDER_DIGEST:
            problems.append("MODELER_IMAGE_DIGEST is the all-zero placeholder, which is for tests and development only")
        elif not _DIGEST.match(digest):
            problems.append(f"MODELER_IMAGE_DIGEST {digest!r} is not sha256:<64 hex> or catalog:sha256:<64 hex>")
        return problems

    def check_production(self) -> None:
        """Refuse to start a production deployment that is missing a setting (ConfigurationError naming each)."""
        problems = self.production_problems()
        if problems:
            raise ConfigurationError("production deployment refused: " + "; ".join(problems))

    def resolved_engine_command(self, development_default: str) -> str:
        """The engine command: production must set it; development falls back to `development_default`."""
        if self.engine_command:
            return self.engine_command
        if self.production:
            raise ConfigurationError("MODELER_ENGINE_COMMAND is not set (production has no default engine)")
        return development_default

    def resolved_engine_id(self, command: str) -> str:
        return self.engine_id or default_engine_id(command)

    def resolved_image_digest(self) -> str:
        """The digest a run records: production's checked value, else the placeholder in development."""
        if self.production:
            self.check_production()
        return self.image_digest or PLACEHOLDER_DIGEST

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
