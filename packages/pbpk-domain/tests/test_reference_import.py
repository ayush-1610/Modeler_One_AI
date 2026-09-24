"""The OSP reference importer: a published model becomes a CPF and its real clinical studies (plan Phase 4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pbpk_domain.campaign.map import generate_map
from pbpk_domain.campaign.round_build import build_stage_snapshot
from pbpk_domain.campaign.split import QuestionOfInterest, StudyRecord, split_studies
from pbpk_domain.cpf.build import expression_molecule, missing_expression_profiles, unplaceable_parameters
from pbpk_domain.cpf.completeness import check_completeness
from pbpk_domain.cpf.models import ParameterStatus
from pbpk_domain.m15 import Rating
from pbpk_domain.reference import ReferenceImportError, import_osp_snapshot
from pbpk_domain.reference.osp_import import _convert, import_osp_system
from pbpk_domain.reference.roundtrip import system_roundtrip_inputs

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
    assert len(indiv) == 8  # 7 physiology paths and the individual's Seed
    # the published individual's Seed sets its organ-volume percentiles; every subject built from the CPF uses it
    seed = imported.cpf.require("indiv.seed")
    assert (seed.engine_binding.building_block, seed.engine_binding.parameter) == ("Individual", "Seed")
    built = build_stage_snapshot(imported.cpf, [s.model_copy(update={"stage": "S1"}) for s in _dapa_scenarios(imported)[:1]],
                                 stage="S1")
    assert [i.seed for i in built.snapshot.individuals] == [int(seed.value)]
    assert "Seed" not in {q.path for i in built.snapshot.individuals for q in i.parameters}


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


def test_rifampicin_keeps_its_auto_induction_and_the_simulations_select_it():
    """The published simulations select inhibition / induction on AADAC, P-gp, OATP1B1 and CYP3A4 as interactions;
    rifampicin induces its own metabolism (AADAC) and transport, so they change its own kinetics."""
    imported = import_osp_snapshot(_snapshot("Rifampicin"))
    ids = {p.id for p in imported.cpf.parameters}
    assert {"ddi.perp.AADAC.ec50", "ddi.perp.AADAC.emax", "ddi.perp.P-gp.ec50", "ddi.perp.OATP1B1.ki"} <= ids
    assert "ddi.perp.CYP2C8.ki" not in ids
    assert check_completeness(imported.cpf).ready and unplaceable_parameters(imported.cpf) == ()


def test_simulation_level_compound_values_are_carried():
    """Every published Dapagliflozin simulation sets the veg-oil logP (tissue partitioning) and B/P ratio."""
    imported = import_osp_snapshot(_snapshot("Dapagliflozin"))
    assert imported.cpf.require("sim.Dapagliflozin|logP (veg.oil/water)").value == 2.0831076805
    assert imported.cpf.require("sim.Dapagliflozin|Blood/Plasma concentration ratio").value == 0.88


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
    # Interactions the published simulations never select (DDI with victim drugs) are named, not imported.
    assert missing_expression_profiles(rifampicin.cpf) == ()
    assert any("CompetitiveInhibition (CYP2C8)" in n for n in rifampicin.notes)
    midazolam = import_osp_snapshot(_snapshot("Midazolam"))
    assert midazolam.unplaced == ()  # microsomal Michaelis-Menten and specific binding are placed
    assert any(u.endswith("Whole Blood data; only plasma concentrations are compared") for u in midazolam.skipped)
    with pytest.raises(ReferenceImportError, match="no compound 'Hydroxy'"):
        import_osp_snapshot(_snapshot("Itraconazole"), compound="Hydroxy")


def test_a_multi_compound_model_imports_its_parent_and_labels_metabolite_feedback():
    # Itraconazole's metabolites (hydroxy-, keto-, N-desalkyl-) inhibit CYP3A4, which clears the parent: a parent-only
    # simulation cannot reproduce those curves, so the round trip labels them instead of calling them defects.
    imported = import_osp_snapshot(_snapshot("Itraconazole"))
    assert imported.compound == "Itraconazole"
    assert any("other compounds are not simulated" in n and "Hydroxy-Itraconazole" in n for n in imported.notes)
    assert any("metabolite Hydroxy-Itraconazole acts on CYP3A4" in why for why in imported.differs_by_design.values())
    # asking for a metabolite imports that compound instead
    assert import_osp_snapshot(_snapshot("Itraconazole"), compound="hydroxy-itraconazole").compound == "Hydroxy-Itraconazole"


def test_every_osp_regimen_notation_is_read():
    from pbpk_domain.reference.osp_import import _dose_times

    assert _dose_times("(S0-T24-R3)") == [0.0, 24.0, 48.0]
    assert _dose_times("(S-0,T-24,R-3)") == [0.0, 24.0, 48.0]
    assert _dose_times("0-24-48") == [0.0, 24.0, 48.0]
    assert _dose_times("0-(S24-T24-R2)") == [0.0, 24.0, 48.0]
    assert _dose_times(1.0) == [1.0]
    assert _dose_times("weekly") is None


def test_rifampicin_studies_keep_their_real_design():
    imported = import_osp_snapshot(_snapshot("Rifampicin"))
    mean_md = _study(imported, "acocella-1977-mean-600-mg-md")  # IV 600 mg q24h × 7, sampled to 152 h
    assert (mean_md["design"], mean_md["dosing_interval_h"], mean_md["n_doses"]) == ("MD", 24.0, 7)
    assert mean_md["infusion_time_min"] == 180.0
    day1 = _study(imported, "furesz-1970-600-mg")  # fitted by the paper against a MD simulation, sampled on day 1
    assert day1.get("design") is None
    assert _study(imported, "acocella-1984-individual-1-600-mg-3-h-infusion")["infusion_time_min"] == 180.0
    assert _study(imported, "peloquin-1999-antacid")["co_medication"] == "antacid"
    # Chattopadhyay 2018: daily x7, then one dose at 180 h, then daily from 192 h: the published protocol's phases
    phased = _study(imported, "chattopadhyay-2018-rifampicin")
    assert [(p["start_h"], p["n_doses"]) for p in phased["dose_phases"]] == [(0.0, 7), (180.0, 1), (192.0, 3)]
    # linked through the paper's own parameter identification, not only through the simulations
    assert imported.simulation_of["chouchane-1995-rimactan"] == "Rifampicin po 300 mg"


def test_the_regenerated_rifampicin_simulations_select_its_interactions_and_values():
    from pbpk_domain.reference.roundtrip import roundtrip_inputs

    imported = import_osp_snapshot(_snapshot("Rifampicin"))
    ours, pairs, _notes = roundtrip_inputs(imported)
    published = _snapshot("Rifampicin")
    sim = ours["Simulations"][0]
    assert {i["Name"] for i in sim["Interactions"]} == {i["Name"] for i in published["Simulations"][0]["Interactions"]}
    # the compound's own process selections are exactly the published ones (metabolism, transport, GFR)
    assert {p["Name"] for p in sim["Compounds"][0]["Processes"]} == {
        p["Name"] for p in published["Simulations"][0]["Compounds"][0]["Processes"]}
    assert len(pairs) == 22  # with Chattopadhyay 2018, placed as the published protocol's phases

    dapa = import_osp_snapshot(_snapshot("Dapagliflozin"))
    ours_dapa, _pairs, _ = roundtrip_inputs(dapa)
    params = {p["Path"]: p["Value"] for p in ours_dapa["Simulations"][0]["Parameters"]}
    assert params["Dapagliflozin|logP (veg.oil/water)"] == 2.0831076805


def test_midazolam_edge_cases_per_kg_doses_populations_brand_names_and_mixed_route():
    from pbpk_domain.reference.roundtrip import roundtrip_inputs

    imported = import_osp_snapshot(_snapshot("Midazolam"))
    per_kg = [s for s in imported.studies if s.get("dose_per_kg")]
    assert per_kg and all(s["dose_mg"] < 1 for s in per_kg)  # 0.05-0.15 mg/kg, simulated as PK-Sim mg/kg doses
    assert any((s.get("demographics") or {}).get("population") == "Asian_Tanaka_1996" for s in imported.studies)
    assert any(s["formulation"] == "other" and "does not name its form" in s["reference"] for s in imported.studies)
    ids = {p.id for p in imported.cpf.parameters}
    assert {"elim.hepatic.CYP3A4.kcat", "elim.hepatic.UGT1A4.km", "bind.specific.GABRG2.kd"} <= ids
    ours, _pairs, notes = roundtrip_inputs(imported)
    # the published "Mikus 2017" protocol gives oral 4 mg at 0 h and IV 2 mg at 6 h: the IV study is that one IV dose
    # (its times shifted to it), never two IV doses 6 h apart; both arms are labelled as differing by design
    iv = next(p for p in ours["Protocols"] if p["Name"] == "mikus-2017-midazolam-control-iv protocol")
    assert iv["ApplicationType"] == "Intravenous" and iv["DosingInterval"] == "Single"
    assert imported.offset_min["mikus-2017-midazolam-control-iv"] == 360.0
    assert "also gives an oral dose" in imported.differs_by_design["mikus-2017-midazolam-control-iv"]
    assert "also gives an intravenous dose" in imported.differs_by_design["mikus-2017-midazolam-control-po"]
    per_kg_protocol = next(p for p in ours["Protocols"] if p["Name"] == f"{per_kg[0]['study_id']} protocol")
    assert any(p.get("Unit") == "mg/kg" for p in per_kg_protocol["Parameters"] if p["Name"] == "InputDose")
    assert not [n for n in notes if n.startswith("NOT SIMULATED")]


def test_midazolam_gut_wall_permeabilities_set_per_simulation_are_carried():
    # PI-identified P (interstitial<->intracellular) of the 11 gut segments, set in the simulations, not the compound.
    # Without them the regenerated oral curves ran 1.4-3.7x above the published ones.
    imported = import_osp_snapshot(_snapshot("Midazolam"))
    path = "Neighborhoods|Duodenum_int_Duodenum_cell|Midazolam|P (interstitial->intracellular)"
    record = imported.cpf.require(f"sim.{path}")
    assert (record.value, record.unit) == (0.0019242177595, "cm/min")
    assert record.status is ParameterStatus.FITTED
    assert sum(p.id.startswith("sim.Neighborhoods|") for p in imported.cpf.parameters) == 22
    # The one IV simulation that leaves half of them at the default is named.
    assert any("'iv 0.05 mg/kg (30 min)' leaves 11" in n for n in imported.notes)
    sim = build_stage_snapshot(imported.cpf, _first_scenarios(imported), stage="S1", skip_unbuildable=True)
    doc = json.loads(sim.snapshot.model_dump_json(by_alias=True, exclude_none=True))
    assert any(p["Path"] == path for p in doc["Simulations"][0]["Parameters"])


def test_the_published_expression_profile_wins_over_the_library_copy():
    # The library's CYP3A4 (from the Dapagliflozin model) has t1/2 (liver) 37 h; the Midazolam model uses 36 h.
    imported = import_osp_snapshot(_snapshot("Midazolam"))
    record = imported.cpf.require("expr.CYP3A4|t1/2 (liver)")
    assert (record.value, record.unit) == (36.0, "h")
    assert record.engine_binding.building_block == "ExpressionProfile"
    assert expression_molecule(record.engine_binding.parameter) == "CYP3A4"
    assert expression_molecule("Organism|Liver|Periportal|Intracellular|CYP3A4|Relative expression") == "CYP3A4"
    # Only values that differ are recorded as values: the relative expressions match the library.
    assert [p.id for p in imported.cpf.parameters if p.id.startswith("expr.") and not p.id.startswith("expr.profile.")] \
        == ["expr.CYP3A4|t1/2 (liver)"]
    # every profile of the published individual is carried verbatim, and it is what the model is built with
    from pbpk_domain.cpf.build import expression_documents

    documents = expression_documents(imported.cpf)
    published = {p["Molecule"]: p for p in _snapshot("Midazolam")["ExpressionProfiles"]
                 if f"{p['Molecule']}|{p['Species']}|{p['Category']}" in _snapshot("Midazolam")["Individuals"][0]["ExpressionProfiles"]}
    assert documents == published
    built = build_stage_snapshot(imported.cpf, _first_scenarios(imported), stage="S1", skip_unbuildable=True)
    doc = json.loads(built.snapshot.model_dump_json(by_alias=True, exclude_none=True))
    cyp = next(e for e in doc["ExpressionProfiles"] if e["Molecule"] == "CYP3A4")
    liver = [p for p in cyp["Parameters"] if p["Path"] == "CYP3A4|t1/2 (liver)"]
    assert liver == [{"Path": "CYP3A4|t1/2 (liver)", "Value": 36.0, "Unit": "h"}]
    assert "expr.CYP3A4|t1/2 (liver)" in built.build_report.bindings_used
    assert "expr.profile.CYP3A4" in built.build_report.bindings_used
    assert "CYP3A4" in built.build_report.expression_documents
    assert unplaceable_parameters(imported.cpf) == ()


@pytest.mark.parametrize(("model", "molecule"), [("Clarithromycin", "P-gp"), ("Metformin", "MATE1"), ("Metformin", "OCT1"),
                                                  ("Ketoconazole", "ABCB1"), ("Verapamil", "P-gp")])
def test_every_regenerated_profile_is_the_published_one(model, molecule):
    """The library's copy comes from another model: Clarithromycin's P-gp has no ontogeny where the library's has;
    Metformin leaves MATE1/OCT1 at the PK-Sim default in organs the library's copy sets; Ketoconazole's ABCB1 has
    another transport type and localization. Every profile a regenerated individual gets is the published one."""
    from pbpk_domain.reference.roundtrip import roundtrip_inputs

    snapshot = _snapshot(model)
    importer = import_osp_system if model == "Verapamil" else import_osp_snapshot
    imported = importer(snapshot)
    ours = (system_roundtrip_inputs(imported) if model == "Verapamil" else roundtrip_inputs(imported))[0]
    by_ref = {f"{p['Molecule']}|{p['Species']}|{p['Category']}": p for p in snapshot["ExpressionProfiles"]}

    def body(profile):
        return {k: v for k, v in profile.items() if k not in ("Category", "Species", "Molecule")}

    published = [by_ref[r] for i in snapshot["Individuals"] for r in i.get("ExpressionProfiles", []) if r.startswith(f"{molecule}|")]
    mine = [p for p in ours["ExpressionProfiles"] if p["Molecule"] == molecule]
    assert mine and published
    assert all(any(body(m) == body(p) for p in published) for m in mine)


def _first_scenarios(imported):
    studies = [StudyRecord.model_validate({k: v for k, v in s.items() if k in StudyRecord.model_fields})
               for s in imported.studies]
    map_doc = generate_map(
        compound=imported.compound, cpf=imported.cpf, studies=studies,
        split=split_studies(studies, QuestionOfInterest()), objective="test", context_of_use="test",
        food_effect_in_question=False, model_risk=Rating.MEDIUM, engine_image_digest="test", software_versions={},
    )
    return [s.model_copy(update={"stage": "S1"}) for s in map_doc.scenarios[:2]]


def test_a_study_the_published_model_simulates_in_another_individual_keeps_it():
    # Midazolam, Yu 2004 (Korean, CYP3A5 *3/*3): Asian population, study weight and height, and a lower CYP3A4
    # reference concentration, under its own profile category; the other studies keep the main individual.
    imported = import_osp_snapshot(_snapshot("Midazolam"))
    yu = _study(imported, "yu-2004-control-cyp3a5-3-3")
    assert yu["demographics"] == {"population": "Asian_Tanaka_1996", "sex": "MALE", "age_years": 23.3,
                                  "weight_kg": 66.9, "height_cm": 172.9}
    own = yu["published_individual"]
    assert own["name"] == "Korean (Yu 2004 study)"
    assert own["expression"]["CYP3A4|Reference concentration"] == {"value": 3.6271334069, "unit": "µmol/l"}
    built = build_stage_snapshot(imported.cpf, [s for s in _first_scenarios_for(imported, [yu["study_id"], "hohmann-2015-iv-1-mg"])],
                                 stage="S1", skip_unbuildable=True)
    doc = json.loads(built.snapshot.model_dump_json(by_alias=True, exclude_none=True))
    cyp = {e["Category"]: e for e in doc["ExpressionProfiles"] if e["Molecule"] == "CYP3A4"}
    assert len(cyp) == 2
    ref = {cat: next(p["Value"] for p in e["Parameters"] if p["Path"] == "CYP3A4|Reference concentration") for cat, e in cyp.items()}
    assert sorted(ref.values()) == [3.6271334069, 4.32]
    # Rifampicin's 7-day study runs in the "EHC off" individual: the main individual's EHC override does not apply
    rif = import_osp_snapshot(_snapshot("Rifampicin"))
    day7 = _study(rif, "acocella-1972a-day-7")
    assert day7["published_individual"]["parameters"] == {}
    built = build_stage_snapshot(rif.cpf, _first_scenarios_for(rif, ["acocella-1972a-day-7"]), stage="S1",
                                 skip_unbuildable=True)
    doc = json.loads(built.snapshot.model_dump_json(by_alias=True, exclude_none=True))
    assert [i.get("Parameters", []) for i in doc["Individuals"]] == [[]]


def _first_scenarios_for(imported, study_ids):
    studies = [StudyRecord.model_validate({k: v for k, v in s.items() if k in StudyRecord.model_fields})
               for s in imported.studies]
    map_doc = generate_map(
        compound=imported.compound, cpf=imported.cpf, studies=studies,
        split=split_studies(studies, QuestionOfInterest()), objective="test", context_of_use="test",
        food_effect_in_question=False, model_risk=Rating.MEDIUM, engine_image_digest="test", software_versions={},
    )
    first = {}
    for s in map_doc.scenarios:
        first.setdefault(s.study_id, s)
    return [first[sid].model_copy(update={"stage": "S1"}) for sid in study_ids if sid in first]


def _dapa_scenarios(imported):
    return _first_scenarios_for(imported, [s["study_id"] for s in imported.studies])
