"""T-44: evidence grading, conversion, conflicts, coverage and the P2 register gate."""

from __future__ import annotations

import pytest

from modeler_project import ArtifactKind, FileProjectStore, Workspace
from modeler_project.evidence import (
    GRADE_CHECKS,
    EvidenceItem,
    EvidenceState,
    Extraction,
    SourceRef,
    SourceType,
    assess,
    grading_rubric,
    new_id,
)
from modeler_project.evidence_register import (
    EvidenceError,
    blocking,
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


def _clearance(system: str, source=SourceType.PUBLICATION, **conditions):
    return EvidenceItem(id=new_id(), req_id="REQ-elim.hepatic", target="elim.hepatic.CYP3A4.clspec", value=12,
                        unit="µl/min/pmol", source_type=source, quote="CLint was 12 µl/min/pmol",
                        source=SourceRef(doc_sha256="a" * 64, page=2, locator="Table 2"),
                        conditions={"system": system, **conditions})


@pytest.mark.req("T-30")
def test_the_grading_rubric_is_versioned_data_and_names_only_checks_the_code_knows():
    rubric = grading_rubric()
    assert (rubric.version, rubric.status) == ("0.1", "UNVERIFIED")
    assert {check for _grade, check, _why in rubric.rules} <= set(GRADE_CHECKS)
    assert rubric.rules[-1][1] == "always"                               # every item gets a grade


@pytest.mark.req("T-30")
def test_a_value_its_source_calls_predicted_is_graded_as_a_prediction():
    # rubric 0.1 (the owner's decision 8c, 2026-10-29): an in silico logP reported in a paper is a prediction
    logp = EvidenceItem(id=new_id(), req_id="REQ-phys.logp", target="phys.logp", value=2.1, unit=None,
                        source_type=SourceType.PUBLICATION, quote="logP 2.1", source=SourceRef(doc_sha256="a" * 64, page=1),
                        conditions={"type": "logP", "measured or predicted": "predicted (ACD/Percepta)"})
    assert assess(logp).confidence == "C"
    measured = logp.model_copy(update={"conditions": {"type": "logP", "measured or predicted": "measured, shake flask"}})
    assert assess(measured).confidence == "A"                           # the condition's name is not read, its value is


@pytest.mark.req("T-30")
def test_a_human_in_vitro_value_ranks_below_in_vivo_where_an_in_vivo_value_can_exist():
    # rubric 0.1 (8c): clearance, transport and permeability; parameters measured only in vitro are not affected
    in_vitro = assess(_clearance("human liver microsomes (HLM)"))
    assert in_vitro.confidence == "B" and in_vitro.grade_rubric == "0.1"
    assert in_vitro.grade_reason == "a human in vitro system, where a human in vivo value can exist"
    assert assess(_clearance("rCYP3A4 supersomes")).confidence == "B"
    assert assess(_clearance("IV study in healthy volunteers")).confidence == "A"
    assert assess(_fu(9, "%")).confidence == "A"                        # fu is measured in vitro by nature: still A
    assert assess(_clearance("hepatocytes", species="dog")).confidence == "B"


@pytest.mark.req("T-30")
@pytest.mark.parametrize("source", [s for s in SourceType if s is not SourceType.ASSUMPTION])
@pytest.mark.parametrize("extraction", list(Extraction))
@pytest.mark.parametrize("system", ["HLM", "IV study", "predicted"])
def test_a_prediction_is_never_graded_above_a_measured_value(source, extraction, system):
    # 8c: the grade carries what the status says, so grade and status never point at different parameters (PI-2b)
    order = "ABCD"
    measured = assess(_clearance(system, source=source).model_copy(update={"extraction": extraction}))
    predicted = assess(_clearance("in silico", source=SourceType.PREDICTED))
    if system != "predicted":
        assert order.index(measured.confidence) <= order.index(predicted.confidence)
    assert predicted.confidence == "C"


def test_conflicts_coverage_and_the_register_gate(tmp_path):
    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    from modeler_project.brief import empty_brief
    from modeler_project.requirements import derive

    matrix = derive(empty_brief("X", by="u"))
    ws.commit(ArtifactKind.REQUIREMENTS, "main", matrix.to_content(), actor="system", reason="derived")
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

    # what is still open on the literature's side, until each is found or recorded as not available
    open_items = blocking(coverage(matrix, items(ws)))
    assert open_items and "REQ-bind.fu" not in [r.req_id for r in open_items]
    for row in open_items:
        matrix = RequirementMatrix.from_content({**matrix.to_content(), "items": [
            {**i.model_dump(mode="json"), "status": "NOT_AVAILABLE"} if i.req_id == row.req_id else i.model_dump(mode="json")
            for i in matrix.items]})
    assert not blocking(coverage(matrix, items(ws)))


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


def test_an_agent_cannot_file_a_value_where_a_real_project_saw_it_go_wrong():
    """Redesign §4: with no per-item review (D-27), code stops the misfilings of the 2026-10-06 project: a binding
    percentage read as fu, fe filed as PK-Sim's GFR fraction, a sentence filed as a value."""
    from modeler_project.evidence import Misfiling, file_check

    assert file_check("bind.fu", 30, "%", "30 % bound to plasma proteins")[0] == "% bound"
    assert file_check("bind.fu", 0.7, None, "the unbound fraction (fu) was 0.7") == (None, "")
    with pytest.raises(Misfiling, match="bound share"):
        file_check("bind.fu", 0.3, None, "plasma protein binding 0.3")
    with pytest.raises(Misfiling, match="elim.fe_urine"):
        file_check("elim.renal.gfr_fraction", 0.45, None, "45 % of the dose was excreted unchanged in urine")
    with pytest.raises(Misfiling, match="description, not a value"):
        file_check("phys.logp", "lipophilic, moderately", None, "the drug is lipophilic, moderately")
    with pytest.raises(Misfiling, match="template"):
        file_check("elim.hepatic.{enzyme}.km/vmax", 120, "µmol/l", "Km 120 µM")
