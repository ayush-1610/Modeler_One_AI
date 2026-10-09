"""T-49: CPF v1 assembled from accepted evidence, the study catalog from accepted datasets, and readiness."""

from __future__ import annotations

import pytest

from modeler_project import ArtifactKind, FileProjectStore, Workspace
from modeler_project.brief import empty_brief
from modeler_project.dataset_register import decide_dataset, propose_dataset
from modeler_project.datasets import ObservedDataset, Origin, Series, new_dataset_id
from modeler_project.evidence import EvidenceItem, EvidenceState, SourceRef, SourceType, new_id
from modeler_project.evidence_register import decide, propose
from modeler_project.inputs import accept_inputs, assemble, current_cpf, set_choice
from modeler_project.requirements import derive

pytestmark = pytest.mark.req("T-49")
PAPER = SourceRef(title="Doe, clinical pharmacology review", authors="Doe J", year=2019, doi="10.1/x", locator="Table 2", page=3)


def _accept(ws, target, value, unit=None, *, source=SourceType.REGULATORY_REVIEW, conditions=None, pksim=None):
    item = propose(ws, EvidenceItem(id=new_id(), target=target, value=value, unit=unit, source_type=source, source=PAPER,
                                    quote=f"{target} {value}", conditions=conditions or {}), actor="u", value_in_quote=True)
    decide(ws, item.id, state=EvidenceState.ACCEPTED, reason="checked", by="u", **(pksim or {}))
    return item


def _project(tmp_path):
    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    brief = empty_brief("Renaldrug", by="u")
    b = ws.commit(ArtifactKind.BRIEF, "main", brief.to_content(), actor="u", reason="start")
    ws.commit(ArtifactKind.REQUIREMENTS, "main", derive(brief).to_content(), derived_from=[b.ref], actor="u", reason="derived")
    for target, value, unit, conditions in (
        ("phys.mw", 225.2, "g/mol", {}), ("phys.logp", -1.56, None, {"type": "logP", "pH": "7.4", "method": "shake flask"}),
        ("bind.fu", 85, "%", {"species": "human"}), ("phys.solubility.ref", 1.3, "mg/ml", {"pH": "7"}),
        ("phys.pka", 2.3, None, {"type": "base", "method": "potentiometric"}),
        ("elim.renal.gfr_fraction", 1.0, None, {}),
    ):
        _accept(ws, target, value, unit, conditions=conditions)
    dataset = ObservedDataset(
        id=new_dataset_id(), kind="profile", origin=Origin.LITERATURE, time_unit="h", unit="µmol/l",
        study={"study_id": "doe-iv-250", "reference": "Doe 2019", "n": 12, "route": "iv_infusion", "dose_mg": 250,
               "infusion_time_min": 60, "formulation": "solution", "food_state": "fasted", "n_timepoints": 6},
        series=(Series(name="mean", statistic="arithmetic_mean", times=(0.5, 1, 2, 4, 8, 12),
                       values=(20.1, 35.2, 21.0, 9.1, 2.0, 0.5), n=12),))
    propose_dataset(ws, dataset, actor="u")
    decide_dataset(ws, dataset.id, state=EvidenceState.ACCEPTED, reason="table 3 checked", by="u")
    return ws


def test_a_complete_compound_assembles_builds_and_is_accepted(tmp_path):
    ws = _project(tmp_path)
    result = assemble(ws, by="u")
    ready = result["readiness"].content
    assert ready["ready"], [c for c in ready["checks"] if not c["ok"]]
    cpf = current_cpf(ws)
    logp, fu, gfr = cpf.get("phys.logp"), cpf.get("bind.fu"), cpf.get("elim.renal.gfr_fraction")
    assert logp.unit == "Log Units" and fu.value == pytest.approx(0.85) and cpf.get("phys.pka.base.0").value == 2.3
    assert gfr.engine_binding.process == "GlomerularFiltration" and gfr.engine_binding.parameter == "GFR fraction"
    # provenance reaches PK-Sim's ValueOrigin with harvested Source / Method only, the citation in the description
    assert (logp.provenance.source_type, logp.provenance.method) == ("Publication", "InVitro")
    assert "Doe J, 2019" in logp.provenance.reference and "grade" in logp.provenance.reference
    assert logp.provenance.evidence.startswith("ev-") and gfr.provenance.method == "InVivo"
    catalog = result["catalog"].content["studies"]
    assert catalog[0]["origin"] == "LITERATURE" and catalog[0]["profile"]["values"][1] == 35.2
    assert any("built" in d for c in ready["checks"] for d in c["detail"] if c["check"].startswith("every planned"))
    accept_inputs(ws, by="u", printed_name="Dr U")
    assert ws.phases()["P4"] == "APPROVED"
    # a later evidence decision makes the accepted inputs stale until they are assembled again
    _accept(ws, "perm.intestinal", 1e-5, "cm/s")
    assert assemble(ws, by="u")["cpf"].version == 2 and ws.phases()["P4"] != "APPROVED"


def test_conflicts_and_open_structure_choices_are_named_never_resolved_by_code(tmp_path):
    ws = _project(tmp_path)
    _accept(ws, "bind.fu", 0.9, None, conditions={"species": "human"})                 # a second accepted fu
    _accept(ws, "elim.hepatic.CYP3A4.clspec", 0.5, "l/µmol/min", pksim={"value_pksim": 0.5, "unit_pksim": "l/µmol/min"})
    ready = assemble(ws, by="u")["readiness"].content
    assembly = next(c for c in ready["checks"] if c["check"] == "assembly")
    assert not ready["ready"]
    assert any(d.startswith("bind.fu: 2 accepted values") for d in assembly["detail"])
    assert any("choose the process type for elim.hepatic.CYP3A4" in d and "rCYP450_FirstOrder" in d for d in assembly["detail"])
    set_choice(ws, kind="process", key="elim.hepatic.CYP3A4", value="MetabolizationSpecific_FirstOrder",
               reason="OSP standard first-order specific clearance", by="u")
    assemble(ws, by="u")
    clspec = current_cpf(ws).get("elim.hepatic.CYP3A4.clspec")
    assert clspec.engine_binding.process == "MetabolizationSpecific_FirstOrder:CYP3A4"
    assert clspec.engine_binding.parameter == "CLspec/[Enzyme]"
    with pytest.raises(ValueError, match="not ready"):
        accept_inputs(ws, by="u")


def test_a_total_clearance_filed_under_total_cl_is_placed_on_liver_clearance(tmp_path):
    # parameter registry 1.1 (phase 4e, the owner's decision): elim.hepatic.total_cl is an alias of the id PK-Sim's
    # LiverClearance is bound to; before, it satisfied S0 while nothing placed it
    ws = _project(tmp_path)
    _accept(ws, "elim.hepatic.total_cl", 0.3, "l/h/kg")
    report = assemble(ws, by="u")["cpf"].content["assembly"]
    cpf = current_cpf(ws)
    assert cpf.get("elim.hepatic.total_cl") is None
    clearance = cpf.get("elim.hepatic.total.plasma_clearance")
    assert clearance.value == pytest.approx(5.0) and clearance.unit == "ml/min/kg"
    assert (clearance.engine_binding.process, clearance.engine_binding.parameter) == ("LiverClearance", "Plasma clearance")
    assert clearance.provenance.method == "InVivo"   # MS-01: a total clearance is clinical
    assert not [i for i in report["issues"] if "total" in i["target"]]


def test_an_ehc_fraction_is_set_on_the_individual_at_its_harvested_path(tmp_path):
    # registry 1.2 (the owner's decision, 2026-10-09; UNVERIFIED): MS-01 places it on the Individual, at the path the OSP
    # reference snapshots set (Organism|Liver|EHC continuous fraction); before, it was refused
    from pbpk_domain.cpf.build import individual_parameters

    ws = _project(tmp_path)
    _accept(ws, "elim.ehc_fraction", 0.5)
    report = assemble(ws, by="u")["cpf"].content["assembly"]
    record = current_cpf(ws).get("elim.ehc_fraction")
    assert record is not None and record.value == 0.5
    assert (record.engine_binding.building_block, record.engine_binding.parameter) == (
        "Individual", "Organism|Liver|EHC continuous fraction")
    assert individual_parameters(current_cpf(ws))["Organism|Liver|EHC continuous fraction"].value == 0.5
    assert not [i for i in report["issues"] if i["target"] == "elim.ehc_fraction"]
