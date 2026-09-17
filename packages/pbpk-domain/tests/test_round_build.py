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


def test_recorded_weight_is_noted_not_emitted() -> None:
    stage = build_stage_snapshot(_cpf(), [_scenario(weight_kg=72.0)], stage="S1")
    assert any("weight/height recorded" in n for n in stage.notes)
    # not written into the snapshot's OriginData (only species/population/gender/age)
    assert stage.snapshot.individuals[0].origin_data.model_dump(by_alias=True).get("Weight") is None


# --- gaps surfaced, never invented ---------------------------------------------------------------


def test_iv_without_infusion_time_raises() -> None:
    with pytest.raises(ScenarioBuildError, match="infusion time"):
        build_stage_snapshot(_cpf(), [_scenario(infusion_time_min=None)], stage="S1")


def test_ir_formulation_raises() -> None:
    sc = _scenario(study_id="ir", stage="S2", route="oral", dose_mg=10.0, infusion_time_min=None,
                   formulation="ir_tablet")
    with pytest.raises(ScenarioBuildError, match="dissolution model"):
        build_stage_snapshot(_cpf(), [sc], stage="S2")


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
