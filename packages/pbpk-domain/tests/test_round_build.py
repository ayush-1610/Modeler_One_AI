from __future__ import annotations

import pytest

from pbpk_domain.campaign.map import MapScenario, generate_map
from pbpk_domain.campaign.round_build import (
    ScenarioBuildError,
    build_stage_snapshot,
    scenarios_for_stage,
)
from pbpk_domain.campaign.split import (
    Demographics,
    FoodState,
    FormulationKind,
    QuestionOfInterest,
    Route,
    Sex,
    StudyRecord,
    split_studies,
)
from pbpk_domain.cpf import CPF, EngineBinding, ParameterRecord, ParameterStatus, Provenance
from pbpk_domain.m15 import Rating

pytestmark = pytest.mark.req("T-10")


def _cpf() -> CPF:
    prov = Provenance(source_type="measured", reference="Example 2020")

    def rec(pid, value, unit=None, binding=None):
        return ParameterRecord(id=pid, value=value, unit=unit, status=ParameterStatus.FIXED,
                               provenance=prov, engine_binding=binding)

    return CPF(compound="Example-A", parameters=(
        rec("phys.mw", 408.5, "g/mol"),
        rec("phys.logp", 2.6, "Log Units"),
        rec("bind.fu", 0.02),
        rec("phys.solubility.ref", 0.1, "mg/ml"),
        rec("elim.hepatic.CYP3A4.clspec", 0.8, "l/µmol/min",
            EngineBinding(building_block="Compound", process="MetabolizationSpecific_FirstOrder:CYP3A4",
                          parameter="CLspec/[Enzyme]", data_source="Optimized")),
    ))


def _scenario(**kw) -> MapScenario:
    base = dict(
        study_id="s1", stage="S1", route="iv_bolus", dose_mg=5.0, infusion_time_min=15.0,
        formulation="solution", food_state="fasted", meal_template=None, n_subjects=12,
        population="European_ICRP_2002", sex="MALE", age_years=35.0,
    )
    base.update(kw)
    return MapScenario(**base)


# --- direct scenario construction ---------------------------------------------------------------


def test_iv_stage_builds_valid_snapshot() -> None:
    stage = build_stage_snapshot(_cpf(), [_scenario()], stage="S1")
    snap = stage.snapshot
    assert len(snap.individuals) == 1
    assert len(snap.simulations) == 1
    assert snap.simulations[0].individual == "Individual: MALE 35y European_ICRP_2002"
    # the IV protocol carries the infusion time
    protocol = next(p for p in snap.protocols if p.name == "s1 protocol")
    assert protocol.application_type == "Intravenous"
    assert any(par.name == "Infusion time" and par.value == 15.0 for par in protocol.parameters)


def test_oral_fasted_stage_has_formulation_no_meal() -> None:
    sc = _scenario(study_id="po", stage="S2", route="oral", dose_mg=10.0, infusion_time_min=None)
    stage = build_stage_snapshot(_cpf(), [sc], stage="S2")
    sim = stage.snapshot.simulations[0]
    assert sim.compounds[0].protocol.formulations  # oral must map a formulation
    assert sim.events == []  # fasted -> no meal event


def test_fed_stage_adds_meal_event() -> None:
    sc = _scenario(study_id="fed", stage="S3", route="oral", dose_mg=10.0, infusion_time_min=None,
                   food_state="fed", meal_template="Meal: High-fat breakfast (Human)")
    stage = build_stage_snapshot(_cpf(), [sc], stage="S3")
    assert [e.name for e in stage.snapshot.events] == ["fed meal"]
    assert stage.snapshot.simulations[0].events[0]["Name"] == "fed meal"


def test_demographics_flow_into_the_individual() -> None:
    sc = _scenario(sex="FEMALE", age_years=68.0, population="WhiteAmerican_NHANES_1997")
    stage = build_stage_snapshot(_cpf(), [sc], stage="S1")
    origin = stage.snapshot.individuals[0].origin_data
    assert origin.gender == "FEMALE"
    assert origin.age.value == 68.0
    assert origin.population == "WhiteAmerican_NHANES_1997"


def test_build_is_deterministic() -> None:
    a = build_stage_snapshot(_cpf(), [_scenario()], stage="S1")
    b = build_stage_snapshot(_cpf(), [_scenario()], stage="S1")
    assert a.snapshot.sha256() == b.snapshot.sha256()


def test_expression_note_lists_process_molecules() -> None:
    stage = build_stage_snapshot(_cpf(), [_scenario()], stage="S1")
    assert any("CYP3A4" in n and "expression profiles" in n for n in stage.notes)


def test_study_weight_and_height_are_written_into_the_individual() -> None:
    # OriginData Weight (kg) / Height (cm): keys harvested from the OSP Midazolam model's Korean individual
    stage = build_stage_snapshot(_cpf(), [_scenario(weight_kg=72.0, height_cm=178.0)], stage="S1")
    origin = stage.snapshot.individuals[0].origin_data.model_dump(by_alias=True, exclude_none=True)
    assert origin["Weight"] == {"Value": 72.0, "Unit": "kg"}
    assert origin["Height"] == {"Value": 178.0, "Unit": "cm"}
    # without a recorded weight PK-Sim derives it from the population: no key is emitted
    plain = build_stage_snapshot(_cpf(), [_scenario()], stage="S1")
    assert "Weight" not in plain.snapshot.individuals[0].origin_data.model_dump(by_alias=True, exclude_none=True)


# --- gaps surfaced, never invented ---------------------------------------------------------------


def test_iv_infusion_without_infusion_time_raises() -> None:
    with pytest.raises(ScenarioBuildError, match="infusion time"):
        build_stage_snapshot(_cpf(), [_scenario(route="iv_infusion", infusion_time_min=None)], stage="S1")


def test_iv_bolus_without_infusion_time_is_a_pksim_bolus() -> None:
    """Harvested from the OSP Alfentanil protocols: ``IntravenousBolus`` with Start time and InputDose only."""
    built = build_stage_snapshot(_cpf(), [_scenario(route="iv_bolus", infusion_time_min=None)], stage="S1")
    protocol = next(p for p in built.snapshot.to_json_dict()["Protocols"])
    assert protocol["ApplicationType"] == "IntravenousBolus"
    assert [q["Name"] for q in protocol["Parameters"]] == ["Start time", "InputDose"]


def test_tablet_without_a_cpf_formulation_raises() -> None:
    sc = _scenario(study_id="ir", stage="S2", route="oral", dose_mg=10.0, infusion_time_min=None,
                   formulation="ir_tablet")
    with pytest.raises(ScenarioBuildError, match="defines no formulation"):
        build_stage_snapshot(_cpf(), [sc], stage="S2")


def _with_tablet(cpf: CPF, name: str = "IC tablet", t50: float = 30.0, shape: float = 0.6) -> CPF:
    prov = Provenance(source_type="measured", reference="in-vitro dissolution")
    extra = (
        ParameterRecord(id=f"form.{name}.type", value="Weibull", status=ParameterStatus.FIXED, provenance=prov),
        ParameterRecord(id=f"form.{name}.weibull.t50", value=t50, unit="min", status=ParameterStatus.FIXED, provenance=prov),
        ParameterRecord(id=f"form.{name}.weibull.shape", value=shape, status=ParameterStatus.FIXED, provenance=prov),
    )
    return cpf.model_copy(update={"parameters": (*cpf.parameters, *extra)})


def test_tablet_is_built_as_the_cpf_weibull_formulation() -> None:
    cpf = _with_tablet(_cpf())
    sc = _scenario(study_id="tab", stage="S2", route="oral", dose_mg=10.0, infusion_time_min=None,
                   formulation="ir_tablet", formulation_name="IC tablet")
    stage = build_stage_snapshot(cpf, [sc], stage="S2")
    form = next(f for f in stage.snapshot.formulations if f.name == "IC tablet")
    assert form.formulation_type == "Formulation_Tablet_Weibull"
    values = {p.name: p.value for p in form.parameters}
    assert values["Dissolution time (50% dissolved)"] == 30.0 and values["Dissolution shape"] == 0.6
    assert values["Lag time"] == 0.0 and values["Use as suspension"] == 1.0  # as in every published OSP tablet
    assert stage.snapshot.simulations[0].to_json_dict().get("Compounds")  # the simulation references it


def test_an_unnamed_tablet_uses_the_only_cpf_formulation_and_says_so() -> None:
    cpf = _with_tablet(_cpf())
    sc = _scenario(study_id="tab", stage="S2", route="oral", dose_mg=10.0, infusion_time_min=None, formulation="ir_tablet")
    stage = build_stage_snapshot(cpf, [sc], stage="S2")
    assert any("only formulation 'IC tablet'" in n for n in stage.notes)


def test_no_scenario_for_stage_raises() -> None:
    with pytest.raises(ScenarioBuildError, match="no MAP scenario"):
        build_stage_snapshot(_cpf(), [_scenario(stage="S1")], stage="S2")


# --- end to end through the MAP ------------------------------------------------------------------


def _studies() -> list[StudyRecord]:
    adult = Demographics(sex=Sex.MALE, age_years=35.0)
    return [
        StudyRecord(study_id="iv", n=12, design="SD", route=Route.IV_BOLUS, dose_mg=5.0,
                    infusion_time_min=5.0, formulation=FormulationKind.SOLUTION, food_state=FoodState.FASTED,
                    n_timepoints=15, demographics=adult),
        StudyRecord(study_id="po", n=20, design="SD", route=Route.ORAL, dose_mg=10.0,
                    formulation=FormulationKind.SOLUTION, food_state=FoodState.FASTED, n_timepoints=15,
                    demographics=adult),
    ]


def test_build_from_generated_map_scenarios() -> None:
    studies = _studies()
    split = split_studies(studies, QuestionOfInterest())
    m = generate_map(
        compound="Example-A", cpf=_cpf(), studies=studies, split=split,
        objective="predict exposure", context_of_use="MIDD", food_effect_in_question=False,
        model_risk=Rating.MEDIUM, engine_image_digest="sha256:abcd",
        software_versions={"ospsuite": "12.4.4"},
    )
    s1 = scenarios_for_stage(m.scenarios, "S1")
    assert [sc.study_id for sc in s1] == ["iv"]
    stage = build_stage_snapshot(_cpf(), m.scenarios, stage="S1")
    assert stage.simulations == ("iv",)
    # S2 (oral fasted) also builds from the same MAP scenarios
    stage2 = build_stage_snapshot(_cpf(), m.scenarios, stage="S2")
    assert stage2.simulations == ("po",)


def test_a_phased_regimen_is_one_schema_per_phase() -> None:
    """A loading dose then maintenance, as the OSP Voriconazole protocol "Purkin et al. 2003 B" writes it."""
    from pbpk_domain.campaign.split import DosePhase

    phases = (DosePhase(start_h=0.0, dose_mg=6.0, n_doses=2, interval_h=12.0),
              DosePhase(start_h=24.0, dose_mg=3.0, n_doses=17, interval_h=12.0))
    sc = _scenario(route="iv_bolus", infusion_time_min=None, dose_mg=6.0, dose_per_kg=True, dose_phases=phases)
    built = build_stage_snapshot(_cpf(), [sc], stage="S1")
    protocol = built.snapshot.to_json_dict()["Protocols"][0]
    assert protocol["DosingInterval"] == "Single" and len(protocol["Schemas"]) == 2
    for schema, (start, dose, n) in zip(protocol["Schemas"], [(0.0, 6.0, 2), (24.0, 3.0, 17)], strict=True):
        params = {q["Name"]: q["Value"] for q in schema["Parameters"]}
        assert (params["Start time"], params["NumberOfRepetitions"], params["TimeBetweenRepetitions"]) == (start, n, 12.0)
        item = schema["SchemaItems"][0]
        assert item["ApplicationType"] == "IntravenousBolus"
        assert {q["Name"]: (q["Value"], q.get("Unit")) for q in item["Parameters"]}["InputDose"] == (dose, "mg/kg")
    # the simulation covers the whole regimen
    end = max(q["Value"] for s in built.snapshot.to_json_dict()["Simulations"][0]["OutputSchema"]
              for q in s["Parameters"] if q["Name"] == "End time")
    assert end >= 24.0 + 17 * 12.0


def test_a_phase_keeps_its_own_infusion_time() -> None:
    from pbpk_domain.campaign.split import DosePhase

    phases = (DosePhase(start_h=0.0, dose_mg=1.0, infusion_time_min=2.0),
              DosePhase(start_h=2 / 60, dose_mg=0.576, infusion_time_min=480.0))
    sc = _scenario(route="iv_infusion", infusion_time_min=2.0, dose_mg=1.0, dose_phases=phases)
    protocol = build_stage_snapshot(_cpf(), [sc], stage="S1").snapshot.to_json_dict()["Protocols"][0]
    infusions = [next(q["Value"] for q in s["SchemaItems"][0]["Parameters"] if q["Name"] == "Infusion time")
                 for s in protocol["Schemas"]]
    assert infusions == [2.0, 480.0]


def test_phase_rules_are_enforced() -> None:
    from pydantic import ValidationError

    from pbpk_domain.campaign.split import DosePhase, StudyRecord
    from pbpk_domain.snapshot.builder import DosePhaseSpec, Measured, OralProtocolSpec

    with pytest.raises(ValidationError, match="interval"):
        DosePhase(start_h=0.0, dose_mg=1.0, n_doses=2)
    base = dict(study_id="s", n=1, dose_mg=400.0, n_timepoints=5, design="MD",
                dose_phases=(DosePhase(start_h=0.0, dose_mg=400.0, n_doses=2, interval_h=12.0),
                             DosePhase(start_h=24.0, dose_mg=200.0, n_doses=2, interval_h=12.0)))
    StudyRecord(**base)
    with pytest.raises(ValidationError, match="first dose"):
        StudyRecord(**{**base, "dose_mg": 200.0})
    with pytest.raises(ValidationError, match="replaces"):
        StudyRecord(**{**base, "n_doses": 4, "dosing_interval_h": 12.0})
    with pytest.raises(ValidationError, match="multiple-dose"):
        StudyRecord(**{**base, "design": "SD"})
    with pytest.raises(ValidationError, match="time order"):
        StudyRecord(**{**base, "dose_phases": tuple(reversed(base["dose_phases"]))})
    mg = Measured(value=400.0, unit="mg")
    with pytest.raises(ValidationError, match="not repetitions"):
        OralProtocolSpec(name="p", dose=mg, repetitions=2, repetition_interval_h=12.0,
                         phases=(DosePhaseSpec(start_h=0.0, dose=mg),))
    with pytest.raises(ValidationError, match="dose unit"):
        OralProtocolSpec(name="p", dose=mg, phases=(DosePhaseSpec(start_h=0.0, dose=Measured(value=3.0, unit="mg/kg")),))


def test_a_system_splits_every_phase_by_its_dose_fractions() -> None:
    """Each enantiomer of a racemic product gets every phase at dose x its fraction."""
    import json
    from pathlib import Path

    from pbpk_domain.campaign.split import DosePhase
    from pbpk_domain.reference.osp_import import import_osp_system

    fixtures = Path(__file__).resolve().parents[3] / "services" / "engine-worker" / "golden" / "fixtures"
    system = import_osp_system(json.loads((fixtures / "Verapamil-Model.json").read_text(encoding="utf-8"))).system
    product, fractions = next((p, f) for p, f in system.products.items() if len(f) == 2)
    phases = (DosePhase(start_h=0.0, dose_mg=240.0), DosePhase(start_h=12.0, dose_mg=120.0, n_doses=3, interval_h=12.0))
    sc = _scenario(route="oral", infusion_time_min=None, dose_mg=240.0, dose_phases=phases, product=product)
    built = build_stage_snapshot(system.cpf(system.parents[0]), [sc], stage="S1", system=system)
    doc = built.snapshot.to_json_dict()
    protocols = {p["Name"]: p for p in doc["Protocols"]}
    for entry in doc["Simulations"][0]["Compounds"]:
        if entry.get("Protocol") is None:
            continue
        f = fractions[entry["Name"]]
        doses = [next(q["Value"] for q in s["SchemaItems"][0]["Parameters"] if q["Name"] == "InputDose")
                 for s in protocols[entry["Protocol"]["Name"]]["Schemas"]]
        assert doses == pytest.approx([240.0 * f, 120.0 * f])


def test_alternatives_are_written_and_selected_per_simulation() -> None:
    from pydantic import ValidationError

    from pbpk_domain.snapshot.builder import CompoundSpec, Measured, SnapshotBuilder

    base = dict(name="K", molecular_weight=Measured(value=500.0, unit="g/mol"),
                lipophilicity=Measured(value=3.0, unit="Log Units"), fraction_unbound=Measured(value=0.1),
                solubility=Measured(value=0.008, unit="mg/ml"), intestinal_permeability=Measured(value=1e-5, unit="cm/min"))
    spec = CompoundSpec(**base, solubility_alternatives={"Capsule fed": (Measured(value=0.0007, unit="mg/ml"), 6.5)},
                        intestinal_permeability_alternatives={"Fit fed": Measured(value=9.9e-6, unit="cm/min")})
    compound = spec.to_compound().model_dump(by_alias=True, exclude_none=True)
    assert [a["Name"] for a in compound["Solubility"]] == ["Measured", "Capsule fed"]
    assert compound["Solubility"][1]["IsDefault"] is False
    builder = SnapshotBuilder()
    builder.add_compound(spec)
    entry, _ = builder._simulation_compound("K", None, None, (), {"COMPOUND_SOLUBILITY": "Capsule fed"})
    groups = {a.group_name: a.alternative_name for a in entry.alternatives}
    assert groups["COMPOUND_SOLUBILITY"] == "Capsule fed" and groups["COMPOUND_INTESTINAL_PERMEABILITY"] == "Measured"
    with pytest.raises(ValueError, match="no COMPOUND_SOLUBILITY alternative"):
        builder._simulation_compound("K", None, None, (), {"COMPOUND_SOLUBILITY": "Tablet"})
    with pytest.raises(ValidationError, match="reuse the default"):
        CompoundSpec(**base, solubility_alternatives={"Measured": (Measured(value=0.001, unit="mg/ml"), 6.5)})
