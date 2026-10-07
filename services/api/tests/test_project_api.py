"""T-40: the start-up pipeline's shared endpoints (phases, artifacts, history, impact, audit)."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from modeler_api import project_api
from modeler_api.auth import get_verifier
from modeler_api.main import app
from modeler_project import ArtifactKind, FileProjectStore, Workspace
from modeler_project import audit as file_audit
from modeler_storage import audit as pg_audit

pytestmark = pytest.mark.req("T-40")


class FakeVerifier:
    def __init__(self, claims):
        self.claims = claims

    def verify(self, token):
        return self.claims


def _claims(projects=("*",), roles=("modeler-curator",)):
    return {"sub": "u1", "name": "Dev", "tenant_id": "t1", "realm_access": {"roles": list(roles)},
            "projects": list(projects), "acr": "loa2", "auth_time": int(time.time())}


@pytest.fixture
def setup(tmp_path):
    store = FileProjectStore(tmp_path)
    app.dependency_overrides[get_verifier] = lambda: FakeVerifier(_claims())
    app.dependency_overrides[project_api.get_project_store] = lambda: store
    yield TestClient(app), Workspace(store, "t1", "p1")
    app.dependency_overrides.clear()


H = {"Authorization": "Bearer t"}


def test_phases_artifacts_history_and_impact(setup):
    client, ws = setup
    doc = ws.commit(ArtifactKind.DOCUMENT, "d1", {"name": "proposal.pdf"}, actor="u1", reason="upload")
    ws.commit(ArtifactKind.BRIEF, "main", {"dose": 50}, derived_from=[doc.ref], actor="u1", reason="extracted")
    ws.commit(ArtifactKind.BRIEF, "main", {"dose": 100}, derived_from=[doc.ref], actor="u1", reason="edited")

    phases = client.get("/api/v1/projects/p1/phases", headers=H).json()["data"]["phases"]
    assert {p["phase"]: p["status"] for p in phases}["P1"] == "IN_REVIEW"

    listed = client.get("/api/v1/projects/p1/artifacts?kind=brief", headers=H).json()["data"]["artifacts"]
    assert [(a["id"], a["version"], a["status"]) for a in listed] == [("main", 2, "DRAFT")]

    one = client.get("/api/v1/projects/p1/artifacts/brief/main?version=1", headers=H).json()["data"]
    assert one["content"] == {"dose": 50} and one["status"] == "SUPERSEDED"

    history = client.get("/api/v1/projects/p1/artifacts/brief/main/history", headers=H).json()["data"]["versions"]
    assert history[1]["changes"] == [{"path": "dose", "before": 50, "after": 100, "kind": "changed"}]

    impact = client.post("/api/v1/projects/p1/impact", headers=H,
                         json={"kind": "brief", "id": "main", "content": {"dose": 150}}).json()["data"]
    assert impact["changes"][0]["after"] == 150 and impact["affected"] == []
    assert client.get("/api/v1/projects/p1/artifacts/nope/main", headers=H).status_code == 404


def test_audit_endpoint_reports_the_chain(setup):
    client, ws = setup
    ws.commit(ArtifactKind.BRIEF, "main", {"dose": 50}, actor="u1", reason="extracted")
    data = client.get("/api/v1/projects/p1/audit", headers=H).json()["data"]
    assert data["chain_verifies"] is True
    assert data["events"][0]["action"] == "artifact.create"


def test_project_membership_is_enforced(setup, tmp_path):
    client, _ = setup
    app.dependency_overrides[get_verifier] = lambda: FakeVerifier(_claims(projects=("other",)))
    assert client.get("/api/v1/projects/p1/phases", headers=H).status_code == 403


def test_file_and_postgres_audit_chains_hash_identically():
    """The single-node chain must migrate into `audit_events` unchanged: same event shape, same row hash."""
    kwargs = dict(tenant_id="t1", seq=1, occurred_at="2026-10-05T00:00:00+00:00", actor="u1", action="artifact.create",
                  resource_type="brief", resource_id="p1/main@v1", before=None, after="ab" * 32, reason="x")
    assert file_audit.row_hash(file_audit.GENESIS_HASH, file_audit.AuditEvent(**kwargs)) == \
        pg_audit.compute_row_hash(pg_audit.GENESIS_HASH, pg_audit.AuditEvent(**kwargs))
