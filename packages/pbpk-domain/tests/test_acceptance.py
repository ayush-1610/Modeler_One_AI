import pytest

from pbpk_domain.acceptance import Comparison, evaluate, load_acceptance_ruleset, loosest_internal_target, prediction_error_pct
from pbpk_domain.m15 import Rating


def test_prediction_error():
    assert prediction_error_pct(110, 100) == pytest.approx(10.0)
    assert prediction_error_pct(80, 100) == pytest.approx(-20.0)


def test_high_risk_uses_one_point_two_five_fold_for_every_study():
    report = evaluate(
        [
            Comparison("SAD 10 mg", "AUC", predicted=124, observed=100, role="fitting"),
            Comparison("SAD 10 mg", "Cmax", predicted=80, observed=100, role="fitting"),
            Comparison("MAD 20 mg", "AUC", predicted=130, observed=100, role="validation"),
        ],
        Rating.HIGH,
    )
    assert [v.passes for v in report.verdicts] == [True, True, False]
    assert not report.passes
    assert report.failures()[0].comparison.study == "MAD 20 mg"
    assert report.failures()[0].prediction_error_pct == pytest.approx(30.0)


def test_medium_risk_allows_twenty_percent_of_studies_outside():
    comparisons = [Comparison(f"S{i}", "AUC", predicted=1.4 if i else 1.7, observed=1.0, role="validation") for i in range(5)]
    report = evaluate(comparisons, Rating.MEDIUM)
    (group,) = report.groups
    assert group.fraction_within == pytest.approx(0.8)
    assert report.passes


def test_ddi_ratio_medium_uses_guest_limits():
    report = evaluate([Comparison("itraconazole", "AUCR", predicted=8.5, observed=5.0, role="validation")], Rating.MEDIUM)
    assert report.verdicts[0].passes
    assert report.verdicts[0].limit.startswith("Guest")


def test_ruleset_is_flagged_for_sme_review_and_unknown_quantities_rejected():
    assert load_acceptance_ruleset()["status"] == "UNVERIFIED"
    with pytest.raises(ValueError, match="no acceptance rule"):
        evaluate([Comparison("S", "tmax", 1, 1, "fitting")], Rating.LOW)


def test_an_internal_target_is_applied_to_internal_auc_and_cmax_only_and_never_looser_than_the_tier():
    # MS-01 §8: stricter MAP criteria for internal groups, never looser than the tier
    comparisons = [Comparison("fit-a", "AUC", 1.3, 1.0, "fitting"), Comparison("fit-b", "Cmax", 0.85, 1.0, "fitting"),
                   Comparison("ext", "AUC", 1.3, 1.0, "validation")]
    plain = evaluate(comparisons, Rating.MEDIUM)
    assert [v.passes for v in plain.verdicts] == [True, True, True] and plain.internal_target_pe is None
    strict = evaluate(comparisons, Rating.MEDIUM, internal_target_pe=20)
    assert [v.passes for v in strict.verdicts] == [False, True, True]          # +30 % fails; -15 % passes; external: tier only
    assert strict.verdicts[0].limit == "0.67-1.5-fold and |PE| ≤ 20 %" and strict.verdicts[2].limit == "0.67-1.5-fold"
    assert strict.internal_target_pe == 20
    assert [round(loosest_internal_target(t), 1) for t in ("high", "medium", "low")] == [20.0, 33.3, 50.0]
    with pytest.raises(ValueError, match="looser than the medium tier"):
        evaluate(comparisons, Rating.MEDIUM, internal_target_pe=40)
