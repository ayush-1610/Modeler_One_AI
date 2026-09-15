from __future__ import annotations

import pytest

from pbpk_domain.campaign.split import (
    Assignment,
    FoodState,
    FormulationKind,
    QuestionOfInterest,
    Route,
    SpecialPopulation,
    Statistic,
    StudyClass,
    StudyRecord,
    classify,
    information_score,
    split_studies,
)


def study(study_id: str, **kw) -> StudyRecord:
    base = dict(
        study_id=study_id,
        n=12,
        design="SD",
        route=Route.ORAL,
        dose_mg=10.0,
        formulation=FormulationKind.SOLUTION,
        food_state=FoodState.FASTED,
        statistic=Statistic.MEAN_SD,
        n_timepoints=15,
    )
    base.update(kw)
    return StudyRecord(**base)


# --- classification (§3.2) -----------------------------------------------------------------------


def test_classify_iv_sd() -> None:
    assert classify(study("s", route=Route.IV_BOLUS)) is StudyClass.IV_SD
    assert classify(study("s", route=Route.IV_INFUSION)) is StudyClass.IV_SD


def test_classify_iv_multiple_dose_is_not_iv_sd() -> None:
    # IV multiple dose is not IV-SD; with no oral route it falls through to PO-OTHER (documented edge).
    assert classify(study("s", route=Route.IV_BOLUS, design="MD")) is StudyClass.PO_OTHER


def test_classify_oral_solution_fasted() -> None:
    assert classify(study("s", formulation=FormulationKind.SOLUTION)) is StudyClass.PO_SOL_FASTED
    assert classify(study("s", formulation=FormulationKind.SUSPENSION)) is StudyClass.PO_SOL_FASTED


def test_classify_oral_ir_solid_fasted() -> None:
    assert classify(study("s", formulation=FormulationKind.IR_TABLET)) is StudyClass.PO_IR_FASTED
    assert classify(study("s", formulation=FormulationKind.IR_CAPSULE)) is StudyClass.PO_IR_FASTED


def test_classify_fed_beats_formulation() -> None:
    assert classify(study("s", food_state=FoodState.FED, formulation=FormulationKind.IR_TABLET)) is StudyClass.PO_FED


def test_classify_multiple_dose() -> None:
    assert classify(study("s", design="MD")) is StudyClass.PO_MD


def test_classify_modified_release() -> None:
    assert classify(study("s", formulation=FormulationKind.MR)) is StudyClass.PO_MR


def test_classify_flagged_precedence() -> None:
    # non-human wins over everything
    assert classify(study("s", species="Rat", route=Route.IV_BOLUS)) is StudyClass.PRECLINICAL
    # special population wins over route/food
    assert classify(study("s", special_population=SpecialPopulation.PEDIATRIC)) is StudyClass.SPECIAL
    assert classify(study("s", population_type="patient")) is StudyClass.SPECIAL
    # genotype -> PGX
    assert classify(study("s", genotype="CYP2D6 PM")) is StudyClass.PGX
    # co-medication -> DDI
    assert classify(study("s", co_medication="itraconazole")) is StudyClass.DDI


def test_special_population_beats_ddi() -> None:
    s = study("s", special_population=SpecialPopulation.RENAL_IMPAIRMENT, co_medication="rifampicin")
    assert classify(s) is StudyClass.SPECIAL


# --- information score (§3.2) --------------------------------------------------------------------


def test_information_score_weights() -> None:
    assert information_score(study("s", n=10, n_timepoints=10, statistic=Statistic.INDIVIDUAL)) == 100.0
    assert information_score(study("s", n=10, n_timepoints=10, statistic=Statistic.MEAN_SD)) == 60.0
    assert information_score(study("s", n=10, n_timepoints=10, statistic=Statistic.MEAN)) == 40.0


def test_information_score_bonuses() -> None:
    base = study("s", n=10, n_timepoints=10, statistic=Statistic.MEAN_SD)  # weight 0.6 -> 60
    with_urine = study("s", n=10, n_timepoints=10, statistic=Statistic.MEAN_SD, matrices=frozenset({"plasma", "urine"}))
    assert information_score(with_urine) == pytest.approx(90.0)  # weight 0.9
    with_both = study("s", n=10, n_timepoints=10, statistic=Statistic.MEAN_SD,
                      matrices=frozenset({"plasma", "urine"}), multiple_dose_levels=True)
    assert information_score(with_both) == pytest.approx(120.0)  # weight 1.2
    assert information_score(base) == 60.0


# --- split (§3.3) --------------------------------------------------------------------------------


def test_split_basic_iv_and_two_oral_doses() -> None:
    studies = [
        study("iv", route=Route.IV_BOLUS, dose_mg=5),
        study("po_low", dose_mg=5, n=20),
        study("po_high", dose_mg=50, n=20),
        study("po_extra", dose_mg=5, n=6),  # lower score at the low dose
    ]
    res = split_studies(studies)
    assert res.assignment_of("iv") is Assignment.INTERNAL
    # lowest and highest dose covered internally; the highest-scoring at each dose
    assert res.assignment_of("po_low") is Assignment.INTERNAL
    assert res.assignment_of("po_high") is Assignment.INTERNAL
    assert res.assignment_of("po_extra") is Assignment.EXTERNAL


def test_split_single_iv_records_limitation() -> None:
    res = split_studies([study("iv", route=Route.IV_BOLUS), study("po", dose_mg=10)])
    assert res.assignment_of("iv") is Assignment.INTERNAL
    assert any("Only one IV-SD study" in m for m in res.limitations)


def test_split_no_iv_records_limitation() -> None:
    res = split_studies([study("po", dose_mg=10), study("po2", dose_mg=50)])
    assert any("No IV-SD study" in m for m in res.limitations)


def test_flagged_supportive_without_application() -> None:
    res = split_studies([study("iv", route=Route.IV_BOLUS), study("ddi", co_medication="itraconazole")])
    assert res.assignment_of("ddi") is Assignment.SUPPORTIVE


def test_flagged_external_with_planned_application() -> None:
    q = QuestionOfInterest(planned_applications=frozenset({StudyClass.DDI}))
    res = split_studies([study("iv", route=Route.IV_BOLUS), study("ddi", co_medication="itraconazole")], q)
    assert res.assignment_of("ddi") is Assignment.EXTERNAL
    assert any("external validation for the planned DDI application" in s for s in res.rationale)


def test_fed_is_question_all_fed_external() -> None:
    studies = [
        study("iv", route=Route.IV_BOLUS),
        study("po", dose_mg=10),
        study("fed1", food_state=FoodState.FED),
        study("fed2", food_state=FoodState.FED, n=30),
    ]
    res = split_studies(studies, QuestionOfInterest(food_effect=True))
    assert res.assignment_of("fed1") is Assignment.EXTERNAL
    assert res.assignment_of("fed2") is Assignment.EXTERNAL
    assert any("Food effect is the question" in s for s in res.rationale)


def test_fed_measured_solubility_all_fed_external() -> None:
    studies = [study("iv", route=Route.IV_BOLUS), study("po", dose_mg=10), study("fed1", food_state=FoodState.FED)]
    res = split_studies(studies, QuestionOfInterest(measured_fed_solubility=True))
    assert res.assignment_of("fed1") is Assignment.EXTERNAL
    assert any("Measured fed solubility" in s for s in res.rationale)


def test_fed_must_fit_one_internal_rest_external() -> None:
    studies = [
        study("iv", route=Route.IV_BOLUS),
        study("po", dose_mg=10),
        study("fed_best", food_state=FoodState.FED, n=40),
        study("fed_other", food_state=FoodState.FED, n=12),
    ]
    res = split_studies(studies)  # no food_effect, no measured solubility -> must fit fed
    assert res.assignment_of("fed_best") is Assignment.INTERNAL
    assert res.assignment_of("fed_other") is Assignment.EXTERNAL


def test_fed_must_fit_single_study_records_limitation() -> None:
    studies = [study("iv", route=Route.IV_BOLUS), study("po", dose_mg=10), study("fed", food_state=FoodState.FED)]
    res = split_studies(studies)
    assert res.assignment_of("fed") is Assignment.INTERNAL
    assert any("fed external validation is not achievable" in m for m in res.limitations)


def test_external_coverage_rebalance_multiple_dose() -> None:
    # Two MD studies both would be internal only if fitted, but MD is never fitted in S1-S3; here MD is
    # not a fitting need, so both are external already. Use fasted rebalance instead:
    studies = [
        study("iv", route=Route.IV_BOLUS),
        study("po_low", dose_mg=5, n=40),   # internal (low dose)
        study("po_low2", dose_mg=5, n=35),  # same low dose, high score -> would be external
        study("po_high", dose_mg=50, n=40),
    ]
    res = split_studies(studies)
    # there is fasted external coverage (po_low2), so no limitation about fasted
    assert not any("external fasted oral" in m for m in res.limitations)
    externals = set(res.by_assignment(Assignment.EXTERNAL))
    assert "po_low2" in externals


def test_deterministic_repeat() -> None:
    studies = [
        study("iv", route=Route.IV_BOLUS),
        study("a", dose_mg=5),
        study("b", dose_mg=50),
        study("fed", food_state=FoodState.FED),
        study("ddi", co_medication="x"),
    ]
    q = QuestionOfInterest(food_effect=True)
    first = split_studies(studies, q)
    second = split_studies(studies, q)
    assert first.model_dump() == second.model_dump()


def test_every_study_gets_exactly_one_assignment() -> None:
    studies = [
        study("iv", route=Route.IV_BOLUS),
        study("po", dose_mg=10),
        study("fed", food_state=FoodState.FED),
        study("md", design="MD"),
        study("mr", formulation=FormulationKind.MR),
        study("ddi", co_medication="x"),
        study("peds", special_population=SpecialPopulation.PEDIATRIC),
        study("preclinical", species="Dog", route=Route.IV_BOLUS),
    ]
    res = split_studies(studies, QuestionOfInterest(food_effect=True))
    assert len(res.splits) == len(studies)
    assert {s.study_id for s in res.splits} == {s.study_id for s in studies}
    for s in res.splits:
        assert s.assignment in (Assignment.INTERNAL, Assignment.EXTERNAL, Assignment.SUPPORTIVE)
