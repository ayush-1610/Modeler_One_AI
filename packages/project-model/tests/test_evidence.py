"""T-44: evidence grading, conversion, conflicts, coverage and the P2 register gate."""

from __future__ import annotations

import pytest

from modeler_project import ArtifactKind, FileProjectStore, PhaseStatus, Workspace
from modeler_project.evidence import EvidenceItem, EvidenceState, Extraction, SourceRef, SourceType, assess, new_id
from modeler_project.evidence_register import (
    EvidenceError,
    blocking,
    close_register,
    coverage,
    decide,
    items,
    propose,
    request_access,
)
from modeler_project.requirements import RequirementMatrix, RequirementOverride
from pbpk_domain.parameter_units import ConversionError, to_storage_unit

pytestmark = pytest.mark.req("T-44")


def _fu(value, unit, source=SourceType.PUBLICATION, **kw):
    return EvidenceItem(id=new_id(), req_id="REQ-bind.fu", target="bind.fu", value=value, unit=unit, source_type=source,
                        source=SourceRef(doc_sha256="a" * 64, page=3, locator="Table 1"), quote="fu was 9 %",
                        conditions={"species": "human", "matrix": "plasma", "method": "equilibrium dialysis",
                                    "drug concentration": "1 µM"}, **kw)


def test_unit_conversion_is_code_and_refuses_science():
    assert to_storage_unit("perm.intestinal", 1e-6, "cm/s").value == pytest.approx(6e-5)
    assert to_storage_unit("bind.fu", 9, "%").value == pytest.approx(0.09)
    assert to_storage_unit("phys.solubility.ref", 1500, "µg/ml").value == pytest.approx(1.5)
    assert to_storage_unit("form.tab.weibull.t50", 0.5, "h").value == 30
    with pytest.raises(ConversionError, match="IVIVE"):
        to_storage_unit("elim.hepatic.UGT1A9.clspec", 12, "µl/min/mg")
    with pytest.raises(ConversionError, match="percentage"):
        to_storage_unit("bind.fu", 9, None)


def test_grades_follow_the_rubric():
    assert assess(_fu(9, "%"), required_conditions=("species", "matrix")).confidence == "A"
    secondary = assess(_fu(9, "%", source=SourceType.DATABASE))
    assert secondary.confidence == "B"
    digitized = assess(_fu(9, "%", extraction=Extraction.FIGURE_DIGITIZED))
    assert digitized.confidence == "C"
    predicted = assess(_fu(9, "%", source=SourceType.PREDICTED))
    assert predicted.confidence == "C"
    missing = assess(_fu(9, "%"), required_conditions=("temperature",))
    assert missing.confidence == "B" and "condition_missing: temperature" in missing.flags
    rat = assess(_fu(9, "%").model_copy(update={"conditions": {"species": "rat"}}))
    assert rat.confidence == "B" and "species_mismatch: rat" in rat.flags
    impossible = assess(_fu(150, "%"))
    assert any(f.startswith("outside_physical_range") for f in impossible.flags)


def test_conflicts_coverage_and_the_register_gate(tmp_path):
    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    from modeler_project.brief import empty_brief
    from modeler_project.requirements import derive

    matrix = derive(empty_brief("X", by="u"))
    matrix_version = ws.commit(ArtifactKind.REQUIREMENTS, "main", matrix.to_content(), actor="system", reason="derived")
    a = propose(ws, _fu(9, "%"), actor="agent:r1")
    b = propose(ws, _fu(0.35, None), actor="agent:r1")
    listed = {e.id: e for e in items(ws)}
    assert any(f.startswith("conflict >2-fold") for f in listed[a.id].flags)
    rows = {r.req_id: r for r in coverage(matrix, list(listed.values()))}
    assert rows["REQ-bind.fu"].status == "CONFLICTING" and rows["REQ-phys.logp"].status == "NOT_FOUND"

    with pytest.raises(EvidenceError, match="reason"):
        decide(ws, a.id, state=EvidenceState.ACCEPTED, reason=" ", by="u")
    decide(ws, a.id, state=EvidenceState.ACCEPTED, reason="primary measurement, therapeutic concentration", by="u")
    decide(ws, b.id, state=EvidenceState.REJECTED, reason="radiolabel artefact discussed by the authors", by="u")
    rows = {r.req_id: r for r in coverage(matrix, items(ws))}
    assert rows["REQ-bind.fu"].status == "ACCEPTED"
    assert not any(f.startswith("conflict") for f in next(e for e in items(ws) if e.id == a.id).flags)

    with pytest.raises(EvidenceError, match="still open"):
        close_register(ws, matrix_version.ref, matrix, by="u")
    for row in blocking(coverage(matrix, items(ws))):
        matrix = RequirementMatrix.from_content({**matrix.to_content(), "items": [
            {**i.model_dump(mode="json"), "status": "NOT_AVAILABLE"} if i.req_id == row.req_id else i.model_dump(mode="json")
            for i in matrix.items]})
    close_register(ws, matrix_version.ref, matrix, by="u", note="gaps accepted for the test")
    assert ws.phases()["P2"] is PhaseStatus.APPROVED
    decide(ws, a.id, state=EvidenceState.REJECTED, reason="superseded by the client's own measurement", by="u")
    assert ws.phases()["P2"] is PhaseStatus.STALE


def test_clspec_cannot_be_accepted_without_its_pksim_value(tmp_path):
    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    clint = propose(ws, EvidenceItem(id=new_id(), target="elim.hepatic.UGT1A9.clspec", value=12.0, unit="µl/min/mg",
                                     source_type=SourceType.PUBLICATION, quote="CLint 12 µl/min/mg"), actor="u")
    assert any(f.startswith("needs_conversion") for f in clint.flags)
    with pytest.raises(EvidenceError, match="PK-Sim unit"):
        decide(ws, clint.id, state=EvidenceState.ACCEPTED, reason="ok", by="u")
    done = decide(ws, clint.id, state=EvidenceState.ACCEPTED, reason="IVIVE in the attached worksheet", by="u",
                  value_pksim=0.42, unit_pksim="l/µmol/min")
    assert done.value_pksim == 0.42 and "set by u" in done.conversion


def test_access_requests_are_deduplicated(tmp_path):
    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    first, created = request_access(ws, title="Paper", authors="A", doi="10.1/x", journal=None, year=None, needed_for="fu", by="a")
    again, created_again = request_access(ws, title="Paper (copy)", authors="A", doi="10.1/X", journal=None, year=None,
                                          needed_for="fu", by="a")
    assert created and not created_again and first == again
    assert RequirementOverride(req_id="r", status="NOT_AVAILABLE", reason="no data", by="u").status == "NOT_AVAILABLE"
