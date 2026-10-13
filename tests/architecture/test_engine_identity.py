"""The engine identity a run records agrees with the qualified engine and the server's configuration (2026-10-08)."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from modeler_api.config import Settings
from modeler_contracts.runtime import LOCAL_OBJECT_STORE, PLACEHOLDER_DIGEST, QUALIFIED_ENGINE_ID, runtime_env
from modeler_engine.registration import build_engine_image_registration

pytestmark = pytest.mark.req("T-25")

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "services" / "engine-worker" / "golden" / "catalog.json"
SERVER_ENV = ROOT / "deploy" / "server" / "_env.sh"


def _registration() -> dict:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    return build_engine_image_registration(digest="sha256:" + "0" * 64, catalog=catalog, benchmark={},
                                           golden={"roundtrip": True, "pi_smoke": True, "tasks": True})


def test_qualified_engine_id_is_the_catalogs():
    assert QUALIFIED_ENGINE_ID == _registration()["engine_id"]


def test_the_api_and_the_orchestrator_share_one_object_store_default():
    assert Settings.model_fields["object_store_uri"].default == LOCAL_OBJECT_STORE == runtime_env({}).object_store_root()
    assert Settings.model_fields["image_digest"].default == PLACEHOLDER_DIGEST


def _server_env(tmp_path: Path, secrets: str) -> dict[str, str]:
    """What deploy/server/_env.sh exports, sourced in a clean shell with the given secrets file."""
    (tmp_path / "secrets.env").write_text(secrets, encoding="utf-8")
    env = {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin", "MODELER_REPO": str(ROOT), "MODELER_DATA": str(tmp_path / "data"),
           "MODELER_LOGS": str(tmp_path / "logs"), "MODELER_SECRETS_FILE": str(tmp_path / "secrets.env")}
    out = subprocess.run(["bash", "-c", f'. "{SERVER_ENV}"; echo "$MODELER_DEPLOYMENT|${{MODELER_DEV_AUTH:-}}|$(web_scheme)"'],
                         env=env, capture_output=True, text=True, check=True).stdout.strip().splitlines()[-1]
    deployment, dev_auth, scheme = out.split("|")
    return {"deployment": deployment, "dev_auth": dev_auth, "web": scheme}


def test_the_server_is_a_pilot_until_keycloak_then_production_without_the_dev_sign_in(tmp_path):
    # a pilot (the owner's decision, 2026-10-09): production's engine settings and the DEV sign-in, until Keycloak is
    # configured in the secrets file (deploy/server/keycloak.sh env); then production, which refuses the DEV verifier
    assert _server_env(tmp_path, "") == {"deployment": "pilot", "dev_auth": "1", "web": "http"}
    keycloak = ("export MODELER_OIDC_ISSUER=https://server:8443/realms/modeler\n"
                "export MODELER_WEB_TLS_PFX=/k/keycloak.p12\nexport MODELER_WEB_TLS_PFX_PASSFILE=/k/keystore.pass\n")
    assert _server_env(tmp_path, keycloak) == {"deployment": "production", "dev_auth": "", "web": "https"}


def test_the_server_records_its_catalog_digest():
    text = SERVER_ENV.read_text(encoding="utf-8")
    snippet = re.search(r"^MODELER_ENGINE_CATALOG=.*?^export MODELER_IMAGE_DIGEST=.*?$", text, re.MULTILINE | re.DOTALL)
    digest = subprocess.run(["bash", "-c", f'REPO="{ROOT}"; {snippet.group(0)}; echo "$MODELER_IMAGE_DIGEST"'],
                            capture_output=True, text=True, check=True).stdout.strip()
    assert digest == "catalog:sha256:" + _registration()["catalog_sha256"]
    env = runtime_env({"MODELER_DEPLOYMENT": "pilot", "MODELER_OBJECT_STORE_URI": "file:///data",
                       "MODELER_ENGINE_COMMAND": "Rscript run_job.R", "MODELER_IMAGE_DIGEST": digest})
    env.check_production()
