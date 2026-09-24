"""The OSP reference importer: a published model becomes a CPF and its real clinical studies (plan Phase 4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pbpk_domain.campaign.map import generate_map
from pbpk_domain.campaign.round_build import build_stage_snapshot
from pbpk_domain.campaign.split import QuestionOfInterest, StudyRecord, split_studies
from pbpk_domain.cpf.build import missing_expression_profiles, unplaceable_parameters
from pbpk_domain.cpf.completeness import check_completeness
from pbpk_domain.cpf.models import ParameterStatus
from pbpk_domain.m15 import Rating
from pbpk_domain.reference import ReferenceImportError, import_osp_snapshot
from pbpk_domain.reference.osp_import import _convert

FIXTURES = Path(__file__).resolve().parents[3] / "services" / "engine-worker" / "golden" / "fixtures"
pytestmark = pytest.mark.req("T-03")


def _snapshot(model: str) -> dict:
    return json.loads((FIXTURES / f"{model}-Model.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def dapa():
    return _snapshot("Dapagliflozin"), import_osp_snapshot(_snapshot("Dapagliflozin"))


def _study(imported, study_id: str) -> dict:
    return next(s for s in imported.studies if s["study_id"] == study_id)


def test_dapagliflozin_imports_s0_ready_with_nothing_unplaced(dapa):
    _snap, imported = dapa
    assert imported.compound == "Dapagliflozin"
    assert check_completeness(imported.cpf).ready
    assert imported.unplaced == ()
    assert unplaceable_parameters(imported.cpf) == ()
    assert missing_expression_profiles(imported.cpf) == ()


def test_published_values_come_through_verbatim_with_their_provenance(dapa):
    _snap, imported = dapa
    cpf = imported.cpf
    assert cpf.require("elim.hepatic.UGT1A9.clspec").value == 0.399443557
    assert cpf.require("elim.hepatic.UGT1A9.clspec").unit == "l/µmol/min"
    assert cpf.require("elim.renal.gfr_fraction").value == 0.7899801465
    assert cpf.require("phys.logp").value == 2.6719093089
    assert cpf.require("bind.fu").value == 0.09
    assert cpf.require("form.IC tablet (Chang 2015).weibull.t50").value == 30.0
    # A value the published model identified keeps that status; a literature value stays FIXED.
    assert cpf.require("phys.logp").status is ParameterStatus.FITTED
    assert cpf.require("bind.fu").status is ParameterStatus.FIXED
    assert cpf.require("bind.fu").provenance.reference == "OSP Dapagliflozin model: Kasichayanula et al. 2014"
    # No fit policy is invented: the import reproduces the published model, it does not decide what to refit.
    assert all(p.fit_policy is None for p in cpf.parameters)


def test_the_published_individuals_changed_physiology_is_carried(dapa):
    _snap, imported = dapa
    indiv = {p.engine_binding.parameter: p.value for p in imported.cpf.parameters if p.id.startswith("indiv.")}
    assert indiv["Organism|Liver|EHC continuous fraction"] == 1.0
    assert indiv["Organism|Lumen|Rectum|Effective surface area enhancement factor"] == 0.6067264038
    assert len(indiv) == 7


def test_only_plasma_data_of_the_parent_become_studies_and_the_rest_are_named(dapa):
    _snap, imported = dapa
    assert len(imported.studies) == 40
    assert len(imported.skipped) == 15
    assert any("Urine fraction data (excreta need task T-11)" in s for s in imported.skipped)
    assert any("data for Dapagliflozin-3-O-glucuronide, not the parent drug" in s for s in imported.skipped)


def test_study_design_comes_from_the_dataset_metadata(dapa):
    _snap, imported = dapa
    iv = _study(imported, "boulton-2013-14c-dapagliflozin-iv")
    # The IV microdose was given 1 h after the oral dose: its times are shifted so that dose is at 0.
    assert iv["route"] == "iv_infusion" and iv["infusion_time_min"] == 1.0 and iv["dose_mg"] == 0.08
    assert iv["profile"]["times"][0] == pytest.approx(1.08333337 - 1.0)
    assert "times shifted" in iv["reference"]

    mad = _study(imported, "komoroski-2009-mad-10-mg-day-7-and-day-14")
    assert (mad["design"], mad["dosing_interval_h"], mad["n_doses"]) == ("MD", 24.0, 14)

    capsule = _study(imported, "komoroski-2009-sad-10-mg")
    assert (capsule["formulation"], capsule["formulation_name"]) == ("ir_capsule", "Dissolved")

    tablet = _study(imported, "chang-2015-study-1-treatment-a-single-oral-doses")
    assert tablet["formulation_name"] == "IC tablet (Chang 2015)"
    assert tablet["food_state"] == "fed"
    assert "published model simulates it without a meal" in tablet["reference"]

    renal = _study(imported, "kasichayanula-2013b-t2dm-with-severe-renal-impairment")
    assert renal["special_population"] == "renal_impairment" and renal["population_type"] == "patient"


def test_the_imported_model_runs_the_ms01_split_and_every_stage_builds(dapa):
    snap, imported = dapa
    fields = StudyRecord.model_fields
    studies = [StudyRecord.model_validate({k: v for k, v in s.items() if k in fields}) for s in imported.studies]
    split = split_studies(studies, QuestionOfInterest())
    classes = {s.study_id: s.study_class.value for s in split.splits}
    assert classes["boulton-2013-14c-dapagliflozin-iv"] == "IV-SD"
    assert classes["kasichayanula-2013b-t2dm-with-severe-renal-impairment"] == "SPECIAL"  # never fits the model
    map_doc = generate_map(
        compound="Dapagliflozin", cpf=imported.cpf, studies=studies, split=split, objective="o", context_of_use="c",
        food_effect_in_question=False, model_risk=Rating.MEDIUM, engine_image_digest="sha256:x",
        software_versions={"ospsuite": "12.4.4"},
    )
    for stage in ("S1", "S2", "S3", "S4", "S5"):
        built = build_stage_snapshot(imported.cpf, map_doc.scenarios, stage=stage)
        assert built.simulations, stage

    # The regenerated model carries the published parameter values exactly (same processes, same values).
    ours = json.loads(build_stage_snapshot(imported.cpf, map_doc.scenarios, stage="S1").snapshot.model_dump_json(
        by_alias=True, exclude_none=True))

    def processes(compound):
        return {(p["InternalName"], p.get("Molecule")): {q["Name"]: q["Value"] for q in p["Parameters"]
                                                          if q["Name"] in ("CLspec/[Enzyme]", "GFR fraction")}
                for p in compound["Processes"]}

    assert processes(ours["Compounds"][0]) == processes(snap["Compounds"][0])
    published_indiv = {p["Path"]: p["Value"] for p in snap["Individuals"][0]["Parameters"]}
    assert {p["Path"]: p["Value"] for p in ours["Individuals"][0]["Parameters"]} == published_indiv


def test_display_units_are_converted_to_the_builders_units():
    imported = import_osp_snapshot(_snapshot("Rifampicin"))
    assert imported.cpf.require("bind.fu").unit is None
    assert imported.cpf.require("bind.fu").value == pytest.approx(0.17)          # 17 % in the snapshot
    assert imported.cpf.require("phys.solubility.ref").value == pytest.approx(2.8)  # 2800 mg/l
    concentrations = [p for p in imported.cpf.parameters if p.id.endswith(".transporter_conc")]
    assert concentrations and all(p.unit == "nmol/l" for p in concentrations)
    assert _convert(1.0, "µmol/l", "nmol/l") == pytest.approx(1000.0)
    assert _convert(2.0, "nmol/l/min", "µmol/l/min") == pytest.approx(2e-3)
    with pytest.raises(ReferenceImportError):
        _convert(1.0, "mg/ml", "µmol/l")  # different dimensions: never guessed


def test_gaps_in_other_reference_models_are_named_not_hidden():
    rifampicin = import_osp_snapshot(_snapshot("Rifampicin"))
    assert "CYP2C8" in missing_expression_profiles(rifampicin.cpf)  # S0 refuses it until the profile is harvested
    midazolam = import_osp_snapshot(_snapshot("Midazolam"))
    assert any(u.startswith("MetabolizationLiverMicrosomes_MM") for u in midazolam.unplaced)
    with pytest.raises(ReferenceImportError, match="expected one compound"):
        import_osp_snapshot(_snapshot("Itraconazole"))
