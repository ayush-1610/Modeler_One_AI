"""T-50: MAP/main has one owner, modeler_project.map_artifact (phase 6e, rule B3): it writes the signed MAP and every
reader (the plan page, blinding) asks it. Its stored content reads back unchanged: the audit chain hashes content."""

from __future__ import annotations

import pytest

from modeler_project import ArtifactKind, FileProjectStore, Workspace
from modeler_project.blinding import map_signed
from modeler_project.map_artifact import MapArtifact, MapSignature, latest_map, record_signed_map, signed_map

pytestmark = pytest.mark.req("T-50")
SIGNED = {"map": {"version": 1, "status": "SIGNED"}, "map_sha256": "a" * 64,
          "signature": {"signature_id": "sig-1", "manifestation": "Dr MIDD Lead | Approved | 2026-10-08 12:00:00 UTC"},
          "campaign": {"compound": "Drug", "map_uri": "file:///prep/map.json"}}


def test_stored_content_reads_back_unchanged_signed_or_not():
    assert MapArtifact.from_content(SIGNED).to_content() == SIGNED
    unsigned = {"map": {"version": 1, "status": "DRAFT"}, "map_sha256": "b" * 64}
    artifact = MapArtifact.from_content(unsigned)
    assert artifact.to_content() == unsigned and not artifact.signed   # no null keys added
    with pytest.raises(ValueError, match="extra"):
        MapArtifact.from_content({**SIGNED, "note": "an undeclared key"})


def test_the_owner_writes_and_answers_for_the_map(tmp_path):
    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    assert latest_map(ws) is None and signed_map(ws) is None and not map_signed(ws)
    plan = ws.commit(ArtifactKind.MODEL_PLAN, "main", {"studies": []}, actor="u1", reason="plan")
    artifact = MapArtifact(map=SIGNED["map"], map_sha256=SIGNED["map_sha256"],
                           signature=MapSignature(**SIGNED["signature"]), campaign=SIGNED["campaign"])
    version = record_signed_map(ws, artifact, derived_from=[plan.ref], actor="u1", reason="MAP v1 from plan v1")
    assert version.content == SIGNED and version.derived_from == (plan.ref,)
    found = signed_map(ws)
    assert found is not None and found[0].ref == version.ref and found[1] == artifact and map_signed(ws)
