"""T-40: versioned artifacts, staleness, impact preview, approvals, phases and the audit chain."""

from __future__ import annotations

import json

import pytest

from modeler_project import ArtifactKind, ArtifactStatus, FileProjectStore, ImmutableVersionError, PhaseStatus, Workspace
from modeler_project.artifacts import ArtifactVersion

pytestmark = pytest.mark.req("T-40")

K = ArtifactKind


@pytest.fixture
def ws(tmp_path) -> Workspace:
    return Workspace(FileProjectStore(tmp_path), "t1", "p1")


def _chain(ws: Workspace):
    """document → brief → requirements → model_plan → map, each derived from the one before."""
    doc = ws.commit(K.DOCUMENT, "doc-1", {"name": "proposal.pdf"}, actor="u", reason="upload")
    brief = ws.commit(K.BRIEF, "main", {"dose": 50}, derived_from=[doc.ref], actor="agent:a1", reason="extracted")
    req = ws.commit(K.REQUIREMENTS, "main", {"items": ["fu"]}, derived_from=[brief.ref], actor="system", reason="derived")
    plan = ws.commit(K.MODEL_PLAN, "main", {"roles": {}}, derived_from=[req.ref], actor="u", reason="planned")
    map_ = ws.commit(K.MAP, "main", {"version": 1}, derived_from=[plan.ref], actor="system", reason="generated")
    return doc, brief, req, plan, map_


def test_versions_are_immutable_and_numbered(ws, tmp_path):
    v1 = ws.commit(K.BRIEF, "main", {"dose": 50}, actor="u", reason="first")
    v2 = ws.commit(K.BRIEF, "main", {"dose": 100}, actor="u", reason="strength corrected")
    assert (v1.version, v2.version) == (1, 2)
    assert ws.get(v1.ref).content == {"dose": 50}
    with pytest.raises(ImmutableVersionError):
        FileProjectStore(tmp_path).put("t1", "p1", ArtifactVersion.create(kind=K.BRIEF, id="main", version=1, content={}))


def test_identical_recommit_is_a_no_op_and_a_change_needs_a_reason(ws):
    v1 = ws.commit(K.BRIEF, "main", {"dose": 50}, actor="u", reason="first")
    assert ws.commit(K.BRIEF, "main", {"dose": 50}, actor="u", reason="again") == v1
    with pytest.raises(ValueError, match="needs a reason"):
        ws.commit(K.BRIEF, "main", {"dose": 75}, actor="u", reason="  ")


def test_an_edit_makes_every_descendant_stale_and_nothing_else(ws):
    doc, brief, _req, _plan, _map = _chain(ws)
    unrelated = ws.commit(K.EVIDENCE, "ev-1", {"v": 1}, derived_from=[doc.ref], actor="u", reason="x")
    assert ws.stale() == []

    ws.commit(K.BRIEF, "main", {"dose": 100}, derived_from=[doc.ref], actor="u", reason="client changed the strength")
    stale = {item.ref.key: item.reasons for item in ws.stale()}
    assert set(stale) == {(K.REQUIREMENTS, "main"), (K.MODEL_PLAN, "main"), (K.MAP, "main")}
    assert "client changed the strength" in stale[(K.REQUIREMENTS, "main")][0]
    assert stale[(K.MODEL_PLAN, "main")] == ("requirements/main@v1 is itself stale",)
    assert ws.status(ws.latest(K.EVIDENCE, "ev-1")) is ArtifactStatus.DRAFT
    assert ws.status(unrelated) is ArtifactStatus.DRAFT
    assert ws.status(brief) is ArtifactStatus.SUPERSEDED


def test_impact_preview_lists_descendants_without_saving(ws):
    *_, map_ = _chain(ws)
    ws.approve(map_.ref, by="lead", meaning="Approved", signature_id="sig-1")
    report = ws.impact(K.BRIEF, "main", {"dose": 100})
    assert [c.path for c in report.changes] == ["dose"]
    assert [i.ref.key for i in report.affected] == [(K.REQUIREMENTS, "main"), (K.MODEL_PLAN, "main"), (K.MAP, "main")]
    map_item = report.affected[-1]
    assert map_item.needs_signature and "must be signed" in map_item.effect
    assert ws.latest(K.BRIEF, "main").version == 1  # nothing was saved
    assert ws.impact(K.BRIEF, "main", {"dose": 50}).unchanged


def test_approval_binds_the_hash_and_refuses_stale_or_superseded_versions(ws):
    doc, brief, req, _plan, _map = _chain(ws)
    ws.approve(brief.ref, by="lead", meaning="Reviewed")
    assert ws.status(brief) is ArtifactStatus.APPROVED
    ws.commit(K.BRIEF, "main", {"dose": 100}, derived_from=[doc.ref], actor="u", reason="edit")
    with pytest.raises(ValueError, match="superseded"):
        ws.approve(brief.ref, by="lead")
    with pytest.raises(ValueError, match="stale"):
        ws.approve(req.ref, by="lead")


def test_phase_rail_follows_the_gates(ws):
    assert set(ws.phases().values()) == {PhaseStatus.NOT_STARTED}
    doc, brief, req, _plan, _map = _chain(ws)
    phases = ws.phases()
    assert phases["P0"] is PhaseStatus.APPROVED and phases["P1"] is PhaseStatus.IN_REVIEW
    ws.approve(brief.ref, by="lead")
    ws.approve(req.ref, by="lead")
    assert ws.phases()["P1"] is PhaseStatus.APPROVED
    ws.commit(K.BRIEF, "main", {"dose": 100}, derived_from=[doc.ref], actor="u", reason="edit")
    assert ws.phases()["P1"] is PhaseStatus.STALE   # the data plan was derived from the old brief


def test_history_shows_changes_between_versions(ws):
    ws.commit(K.BRIEF, "main", {"dose": 50, "route": "oral"}, actor="u", reason="first")
    ws.commit(K.BRIEF, "main", {"dose": 100, "route": "oral"}, actor="u", reason="edit")
    rows = ws.history(K.BRIEF, "main")
    assert [r["status"] for r in rows] == [ArtifactStatus.SUPERSEDED, ArtifactStatus.DRAFT]
    assert [(c.path, c.before, c.after) for c in rows[1]["changes"]] == [("dose", 50, 100)]


def test_every_commit_and_approval_is_on_a_verifiable_audit_chain(ws):
    _doc, brief, *_ = _chain(ws)
    ws.approve(brief.ref, by="lead", meaning="Reviewed", note="checked against the PDF")
    log = ws.store.audit("t1")
    records = log.records()
    assert [r.event.action for r in records][-1] == "artifact.approve"
    assert [r.event.seq for r in records] == list(range(1, len(records) + 1))
    assert log.verify() is None
    # tampering with any stored line breaks the chain from that line on
    lines = log.path.read_text().splitlines()
    row = json.loads(lines[1])
    row["event"]["actor"] = "someone-else"
    lines[1] = json.dumps(row)
    log.path.write_text("\n".join(lines) + "\n")
    assert log.verify() == 1


def test_blobs_are_content_addressed(tmp_path):
    store = FileProjectStore(tmp_path)
    sha = store.put_blob("t1", "p1", b"%PDF-1.7 proposal")
    assert store.put_blob("t1", "p1", b"%PDF-1.7 proposal") == sha
    assert store.blob_path("t1", "p1", sha).read_bytes() == b"%PDF-1.7 proposal"
    assert store.blob_path("t1", "p1", "0" * 64) is None
