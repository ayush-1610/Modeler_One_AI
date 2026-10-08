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


def test_the_server_is_a_production_deployment_recording_its_catalog_digest():
    text = SERVER_ENV.read_text(encoding="utf-8")
    assert re.search(r"^export MODELER_DEPLOYMENT=production$", text, re.MULTILINE)
    snippet = re.search(r"^MODELER_ENGINE_CATALOG=.*?^export MODELER_IMAGE_DIGEST=.*?$", text, re.MULTILINE | re.DOTALL)
    digest = subprocess.run(["bash", "-c", f'REPO="{ROOT}"; {snippet.group(0)}; echo "$MODELER_IMAGE_DIGEST"'],
                            capture_output=True, text=True, check=True).stdout.strip()
    assert digest == "catalog:sha256:" + _registration()["catalog_sha256"]
    env = runtime_env({"MODELER_DEPLOYMENT": "production", "MODELER_OBJECT_STORE_URI": "file:///data",
                       "MODELER_ENGINE_COMMAND": "Rscript run_job.R", "MODELER_IMAGE_DIGEST": digest})
    env.check_production()
