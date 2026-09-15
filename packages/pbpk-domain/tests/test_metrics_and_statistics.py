import math

import numpy as np
import pytest

from pbpk_domain.bioequivalence import paired_crossover_ci, probability_of_success
from pbpk_domain.ddi_static import (
    PerpetratorInVitro,
    RulesetNotApprovedError,
    aucr_mechanistic_static,
    gut_inhibitor_concentration_um,
    load_ruleset,
    r1_reversible,
    screen,
)
from pbpk_domain.m15 import AssessmentTable, RatedElement, Rating, Stage, allowed_model_risk, validate_table
from pbpk_domain.metrics import fraction_within_fold, gmfe, guest_limits, within_guest_limits


def test_gmfe_known_vector_and_exclusions():
    result = gmfe([2.0, 1.0, 5.0], [1.0, 1.0, 0.0])
    assert result.value == pytest.approx(math.sqrt(2))
    assert (result.n, result.n_excluded) == (2, 1)


def test_fraction_within_twofold_is_inclusive_at_boundary():
    result = fraction_within_fold([2.0, 0.5, 2.01, 1.0], [1.0, 1.0, 1.0, 1.0])
    assert result.value == pytest.approx(0.75)


def test_guest_limits():
    lower, upper = guest_limits(5.0, delta=2)
    assert (lower, upper) == (pytest.approx(5 / 1.8), pytest.approx(9.0))
    lower_ind, upper_ind = guest_limits(0.2, delta=2)
    assert (lower_ind, upper_ind) == (pytest.approx(0.2 / 1.8), pytest.approx(0.36))
    assert guest_limits(1.0) == (1.0, 1.0)
    assert within_guest_limits(8.9, 5.0) and not within_guest_limits(9.5, 5.0)


def test_paired_crossover_ci_matches_hand_calculation():
    reference = np.array([100.0, 80.0, 120.0, 90.0])
    d = np.array([0.1, -0.1, 0.05, -0.05])
    result = paired_crossover_ci(reference * np.exp(d), reference)
    half_width = 2.353363434801823 * math.sqrt(0.025 / 3) / 2
    assert result.geometric_mean_ratio == pytest.approx(1.0)
    assert result.ci_lower == pytest.approx(math.exp(-half_width))
    assert result.ci_upper == pytest.approx(math.exp(half_width))
    assert result.passes


def test_bioequivalence_failure_and_probability():
    reference = np.full(12, 100.0)
    shifted = paired_crossover_ci(reference * np.exp(np.linspace(0.2, 0.4, 12)), reference)
    assert not shifted.passes
    identical = paired_crossover_ci(reference * np.exp(np.linspace(-0.01, 0.01, 12)), reference)
    assert probability_of_success([shifted, identical]) == 0.5
    with pytest.raises(ValueError, match="positive"):
        paired_crossover_ci([1.0, 0.0], [1.0, 1.0])


def test_static_ddi_formulas():
    assert r1_reversible(0.1, 1.0) == pytest.approx(1.1)
    assert gut_inhibitor_concentration_um(100, 500) == pytest.approx(800)
    assert aucr_mechanistic_static(0.9, 9.0, 1.0) == pytest.approx(1 / 0.19)


def test_screen_refuses_unapproved_ruleset():
    ruleset = load_ruleset()
    inputs = PerpetratorInVitro(imax_u_um=0.5, ki_u_um=1.0, dose_mg=200, molecular_weight_g_per_mol=450)
    with pytest.raises(RulesetNotApprovedError):
        screen(inputs, ruleset)
    results = {r.model: r for r in screen(inputs, ruleset, allow_unapproved=True)}
    assert results["reversible_inhibition"].flagged
    assert results["reversible_inhibition"].ruleset == "ddi-static-screening@2026.1-draft"


def _rated(rating: Rating) -> RatedElement:
    return RatedElement(description="described", rating=rating, justification="justified")


def complete_table(**overrides) -> AssessmentTable:
    fields = dict(
        question_of_interest="Can drug X be given with a strong CYP3A4 inhibitor?",
        context_of_use="PBPK predicts AUC ratio to inform labeling",
        model_influence=_rated(Rating.HIGH),
        consequence_of_wrong_decision=_rated(Rating.MEDIUM),
        model_risk=_rated(Rating.HIGH),
        model_impact=_rated(Rating.MEDIUM),
        technical_criteria="AUCR within Guest limits for >= 80% of qualification studies",
        appropriateness_of_proposed_midd="Established PBPK DDI use",
    )
    fields.update(overrides)
    return AssessmentTable(**fields)


def test_model_risk_range_follows_m15():
    assert allowed_model_risk(Rating.LOW, Rating.LOW) == (Rating.LOW,)
    assert allowed_model_risk(Rating.HIGH, Rating.LOW) == (Rating.LOW, Rating.MEDIUM, Rating.HIGH)
    assert allowed_model_risk(Rating.MEDIUM, Rating.HIGH) == (Rating.MEDIUM, Rating.HIGH)


def test_assessment_table_stage_rules():
    assert validate_table(complete_table(), Stage.PLANNING) == []
    submission_codes = {i.code for i in validate_table(complete_table(), Stage.SUBMISSION)}
    assert submission_codes == {"MISSING_ENTRY"}

    inconsistent = complete_table(
        model_influence=_rated(Rating.MEDIUM), consequence_of_wrong_decision=_rated(Rating.HIGH), model_risk=_rated(Rating.LOW)
    )
    assert [i.code for i in validate_table(inconsistent, Stage.PLANNING)] == ["MODEL_RISK_INCONSISTENT"]

    unjustified = complete_table(model_impact=RatedElement(description="d", rating=Rating.LOW))
    assert [i.code for i in validate_table(unjustified, Stage.PLANNING)] == ["MISSING_JUSTIFICATION"]
