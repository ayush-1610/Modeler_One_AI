"""Plan 2026-11-05 §3.3 (build I): what another project of the same drug found, reused with the person's consent. Only
literature and public-source values; a client's data never leaves its project; each value proposed anew with its source,
its document copied so the quote still resolves, to decide like any value."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from modeler_api import project_api
from modeler_api.auth import get_verifier
from modeler_api.main import app
from modeler_project import FileProjectStore, Workspace
from modeler_project.documents import DocumentLibrary, document_record
from modeler_project.evidence import EvidenceItem, EvidenceState, SourceRef, SourceType, new_id
from modeler_project.evidence_register import items, propose

pytestmark = pytest.mark.req("T-44")
H = {"Authorization": "Bearer t"}
PAPER = b"# Pharmacokinetics of exampleamide\n\nThe logP of exampleamide was 2.1 by shake flask at pH 7.4.\n"


class FakeVerifier:
    def verify(self, token):
        return {"sub": "u1", "name": "Dev User", "tenant_id": "t1", "realm_access": {"roles": ["modeler-curator"]},
                "projects": ["*"], "acr": "loa2", "auth_time": int(time.time())}


@pytest.fixture
def client(tmp_path, monkeypatch):
    store = FileProjectStore(tmp_path)
    monkeypatch.setenv("MODELER_READ_ROOT", str(tmp_path))
    monkeypatch.delenv("MODELER_LLM_PROVIDER", raising=False)
    from modeler_api.config import reload_settings

    reload_settings()
    app.dependency_overrides[get_verifier] = lambda: FakeVerifier()
    app.dependency_overrides[project_api.get_project_store] = lambda: store
    yield TestClient(app), store
    app.dependency_overrides.clear()
    reload_settings()


def _project(c, drug: str) -> str:
    started = c.post("/api/v1/projects:initiate", headers=H, data={"drug_name": drug, "extract": "false"},
                     files=[("files", ("proposal.md", b"# Proposal\nPBPK model.", "text/markdown"))])
    assert started.status_code in (200, 201), started.text
    return started.json()["data"]["project_id"]


def _found(store, pid: str) -> str:
    """A literature value and a client value in a project, as its agents and the client's file would leave them."""
    ws = Workspace(store, "t1", pid)
    doc = document_record(DocumentLibrary(ws).add(PAPER, "fulltext-PMC9.md", role="paper", by="agent:a2"))
    paper = EvidenceItem(id=new_id(), target="phys.logp", value=2.1, source_type=SourceType.PUBLICATION,
                         quote="The logP of exampleamide was 2.1", conditions={"method": "shake flask", "pH": "7.4"},
                         source=SourceRef(doc_sha256=doc.sha256, page=1, title="Pharmacokinetics of exampleamide",
                                          doi="10.1/oa", year=2019))
    client = EvidenceItem(id=new_id(), target="bind.fu", value=0.09, source_type=SourceType.CLIENT_FILE,
                          provider="CLIENT", quote="fu 0.09", source=SourceRef(locator="Sheet1!B4", title="client.xlsx"))
    propose(ws, paper, actor="agent:a2")
    propose(ws, client, actor="u1")
    return paper.id


def test_the_same_drugs_literature_values_are_offered_and_reused_with_their_source(client):
    c, store = client
    first, here, other = _project(c, "Exampleamide"), _project(c, "exampleamide"), _project(c, "Otheramide")
    original = _found(store, first)
    _found(store, other)
    offers = c.get(f"/api/v1/projects/{here}/value-reuse", headers=H).json()["data"]["offers"]
    assert [(o["project_id"], o["values"]) for o in offers] == [(first, 1)]          # not the client's, not another drug
    assert offers[0]["what"] == ["phys.logp (Pharmacokinetics of exampleamide)"]

    refused = c.post(f"/api/v1/projects/{here}/value-reuse", headers=H, json={"project_id": other})
    assert refused.status_code == 409 and "another drug" in refused.json()["detail"]
    done = c.post(f"/api/v1/projects/{here}/value-reuse", headers=H, json={"project_id": first})
    assert done.status_code == 200, done.text
    [made] = done.json()["data"]["ids"]
    ws = Workspace(store, "t1", here)
    copy = next(e for e in items(ws) if e.id == made)
    assert (copy.target, copy.value, copy.state, copy.source.doi) == ("phys.logp", 2.1, EvidenceState.PROPOSED, "10.1/oa")
    assert "reused from project" in copy.note and original in copy.note and "u1's consent" in copy.note
    assert copy.source.doc_sha256 in {d.sha256 for d in map(document_record, DocumentLibrary(ws).documents())}
    assert not [e for e in items(ws) if e.provider == "CLIENT"]                      # the client's value stayed home
    assert c.get(f"/api/v1/projects/{here}/value-reuse", headers=H).json()["data"]["offers"] == []   # nothing new left
