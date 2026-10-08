"""One default per MODELER_* variable (the owner's decision, 2026-10-08): development defaults, production must set."""

from __future__ import annotations

import pytest

from modeler_contracts.runtime import (
    LOCAL_OBJECT_STORE,
    PLACEHOLDER_DIGEST,
    QUALIFIED_ENGINE_ID,
    ConfigurationError,
    default_engine_id,
    runtime_env,
)

pytestmark = pytest.mark.req("T-25")

PRODUCTION = {"MODELER_DEPLOYMENT": "production", "MODELER_OBJECT_STORE_URI": "file:///data/objstore",
              "MODELER_ENGINE_COMMAND": "Rscript /repo/services/engine-worker/r/run_job.R",
              "MODELER_IMAGE_DIGEST": "catalog:sha256:" + "a" * 64}


def test_development_defaults():
    env = runtime_env({})
    assert not env.production and env.production_problems() == []
    assert env.object_store_root() == LOCAL_OBJECT_STORE
    assert env.resolved_image_digest() == PLACEHOLDER_DIGEST
    assert env.resolved_engine_command("python3 stub_engine.py") == "python3 stub_engine.py"


def test_a_complete_production_deployment_starts():
    env = runtime_env(PRODUCTION)
    env.check_production()
    assert env.resolved_image_digest() == "catalog:sha256:" + "a" * 64
    assert env.resolved_engine_id(env.resolved_engine_command("unused")) == QUALIFIED_ENGINE_ID
    image = runtime_env({**PRODUCTION, "MODELER_IMAGE_DIGEST": "sha256:" + "b" * 64})
    image.check_production()


@pytest.mark.parametrize("unset", ["MODELER_OBJECT_STORE_URI", "MODELER_ENGINE_COMMAND", "MODELER_IMAGE_DIGEST"])
def test_production_refuses_a_missing_setting(unset):
    env = runtime_env({k: v for k, v in PRODUCTION.items() if k != unset})
    with pytest.raises(ConfigurationError, match=unset):
        env.check_production()


@pytest.mark.parametrize("digest, problem", [
    (PLACEHOLDER_DIGEST, "placeholder"), ("sha256:abcd", "not sha256"), ("local", "not sha256"),
])
def test_production_refuses_a_placeholder_or_malformed_digest(digest, problem):
    env = runtime_env({**PRODUCTION, "MODELER_IMAGE_DIGEST": digest})
    with pytest.raises(ConfigurationError, match=problem):
        env.resolved_image_digest()


def test_production_has_no_default_engine():
    env = runtime_env({k: v for k, v in PRODUCTION.items() if k != "MODELER_ENGINE_COMMAND"})
    with pytest.raises(ConfigurationError, match="MODELER_ENGINE_COMMAND"):
        env.resolved_engine_command("python3 stub_engine.py")


def test_an_unknown_deployment_is_refused():
    with pytest.raises(ConfigurationError, match="MODELER_DEPLOYMENT"):
        runtime_env({"MODELER_DEPLOYMENT": "prod"}).check_production()


@pytest.mark.parametrize("command, engine_id", [
    ("python3 /repo/deploy/dev/stub_engine.py", "software-fixture:stub_engine"),
    ("python3 deploy/dev/analytical_engine.py", "software-fixture:analytical_engine"),
    ("Rscript /repo/services/engine-worker/r/run_job.R", QUALIFIED_ENGINE_ID),
    ("bash /repo/deploy/dev/docker_engine.sh", QUALIFIED_ENGINE_ID),
    ("/usr/bin/something-else", "unknown"),
])
def test_the_engine_names_itself(command, engine_id):
    # a fixture run never records PK-Sim's engine id (the owner's decision, 2026-10-08)
    assert default_engine_id(command) == engine_id
    assert runtime_env({"MODELER_ENGINE_ID": "pinned"}).resolved_engine_id(command) == "pinned"
