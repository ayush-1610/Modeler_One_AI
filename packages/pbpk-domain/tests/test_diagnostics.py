from __future__ import annotations

import pytest

from pbpk_domain.campaign.map import STAGE_PLAN
from pbpk_domain.diagnostics import (
    FedSignals,
    FitSignals,
    StudyResidual,
    diag_ruleset_version,
    diagnose,
)


def cands(stage: str) -> tuple[str, ...]:
    return STAGE_PLAN[stage]["fit_candidates"]


def branches(stage: str) -> tuple[str, ...]:
    return STAGE_PLAN[stage]["branches"]


def _diag(stage: str, residuals, **kw):
    return diagnose(residuals, stage=stage, stage_candidates=cands(stage), stage_branches=branches(stage), **kw)


def iv(**kw) -> StudyResidual:
    return StudyResidual(study_id=kw.pop("study_id", "iv"), role="fitting", route="iv", **kw)


def po(**kw) -> StudyResidual:
    return StudyResidual(study_id=kw.pop("study_id", "po"), role="fitting", route="oral", **kw)


def test_ruleset_version_is_unverified() -> None:
    assert diag_ruleset_version() == "diag-rules@0.2-UNVERIFIED"


# --- individual rules ----------------------------------------------------------------------------


def test_clearance_offers_clearance_parameters_before_logp() -> None:
    d = _diag("S1", [iv(thalf_ratio=1.4, auc_ratio=1.4)])
    assert d.escalate is False
    assert d.permitted_actions == ("fit elim.hepatic.{enzyme}.clspec", "fit elim.renal.gfr_fraction",
                                   "fit elim.renal.ts_clspec", "fit phys.logp")


def test_renally_cleared_compound_is_offered_renal_clearance_not_logp_first() -> None:
    """diag-rules 0.2: with hepatic clearance ruled out (the compound has none), the next offer is the renal
    clearance — not logP, which would distort distribution to hide a clearance error (seen on PK-Sim)."""
    d = _diag("S1", [iv(thalf_ratio=1.4, auc_ratio=1.9)], actions_tried=["fit elim.hepatic.{enzyme}.clspec"])
    assert d.permitted_actions[0] == "fit elim.renal.gfr_fraction"


def test_clearance_low_direction() -> None:
    d = _diag("S1", [iv(thalf_ratio=0.6, auc_ratio=0.6)])
    assert d.permitted_actions[0] == "fit elim.hepatic.{enzyme}.clspec"


def test_distribution_branches_partition() -> None:
    d = _diag("S1", [iv(auc_in_limits=True, early_phase_off=True, vss_off=True)])
    assert d.permitted_actions == ("branch dist.partition_method", "fit phys.logp")


def test_permeability_limited_branches_permeability() -> None:
    d = _diag("S1", [iv(permeability_shape_off=True, vss_off=False)])
    assert d.permitted_actions == ("branch dist.permeability_method", "fit perm.cellular")


def test_absorption_fast() -> None:
    d = _diag("S2", [po(cmax_ratio=1.6, tmax_ratio=0.5)])
    assert d.permitted_actions == ("fit perm.intestinal",)


def test_absorption_slow() -> None:
    d = _diag("S2", [po(cmax_ratio=0.5, tmax_ratio=1.6, auc_in_limits=True)])
    assert d.permitted_actions == ("fit perm.intestinal", "fit phys.solubility.ref")


def test_saturable_elimination_switches_to_mm() -> None:
    lo = po(study_id="lo", dose_mg=10, observed_auc=100)   # norm 10
    hi = po(study_id="hi", dose_mg=100, observed_auc=2000)  # norm 20 -> increasing
    d = _diag("S2", [lo, hi])
    assert d.permitted_actions == ("switch elim.hepatic.{enzyme}.mm",)


def test_low_bioavailability_solubility_when_dose_dependent() -> None:
    lo = po(study_id="lo", dose_mg=10, observed_auc=200, auc_ratio=0.5)   # norm 20
    hi = po(study_id="hi", dose_mg=100, observed_auc=1000, auc_ratio=0.5)  # norm 10 -> decreasing
    d = _diag("S2", [lo, hi])
    assert d.permitted_actions == ("fit phys.solubility.ref",)


def test_low_bioavailability_firstpass_when_dose_independent() -> None:
    d = _diag("S2", [po(dose_mg=10, observed_auc=200, auc_ratio=0.5)])  # single dose -> no trend
    assert d.permitted_actions == ("fit perm.intestinal",)


def test_enterohepatic_recycling() -> None:
    d = _diag("S2", [po(secondary_peak=True)])
    assert d.permitted_actions == ("fit elim.ehc_fraction",)


def test_fed_solubility() -> None:
    d = _diag("S3", [po()], fed=FedSignals(auc_ratio_off=True, cmax_consistent=True))
    assert d.permitted_actions == ("fit food.fed_solubility_factor",)


def test_correlated_pair_fix_and_refit() -> None:
    d = _diag("S1", [iv(thalf_ratio=1.0, auc_ratio=1.0)], fit=FitSignals(correlated_pairs=(("phys.logp", "perm.cellular"),)))
    assert d.permitted_actions == ("fix_and_refit phys.logp|perm.cellular",)


def test_starts_disagree_switches_algorithm() -> None:
    d = _diag("S1", [iv()], fit=FitSignals(starts_agreement=0.3))
    assert d.permitted_actions == ("switch_algorithm DEoptim",)


# --- escalations ---------------------------------------------------------------------------------


def test_param_at_bound_escalates_with_name() -> None:
    d = _diag("S1", [iv(thalf_ratio=1.4, auc_ratio=1.4)], fit=FitSignals(at_bound=("phys.logp",)))
    assert d.escalate is True
    assert "phys.logp" in d.reason


def test_time_dependent_clearance_escalates() -> None:
    d = _diag("S2", [po(accumulation_off=True)])
    assert d.escalate is True
    assert "clearance" in d.reason.lower()


def test_fed_tmax_escalates() -> None:
    d = _diag("S3", [po()], fed=FedSignals(tmax_off=True))
    assert d.escalate is True


def test_no_evidence_escalates() -> None:
    d = _diag("S1", [iv(thalf_ratio=1.0, auc_ratio=1.0)])
    assert d.escalate is True
    assert "no diagnostic rule matched" in d.reason


# --- action bookkeeping --------------------------------------------------------------------------


def test_tried_action_is_skipped() -> None:
    tried = ["fit elim.hepatic.{enzyme}.clspec", "fit elim.renal.gfr_fraction", "fit elim.renal.ts_clspec"]
    d = _diag("S1", [iv(thalf_ratio=1.4, auc_ratio=1.4)], actions_tried=tried)
    assert d.permitted_actions == ("fit phys.logp",)


def test_all_actions_tried_escalates() -> None:
    tried = ["fit elim.hepatic.{enzyme}.clspec", "fit elim.renal.gfr_fraction", "fit elim.renal.ts_clspec",
             "fit phys.logp"]
    d = _diag("S1", [iv(thalf_ratio=1.4, auc_ratio=1.4)], actions_tried=tried)
    assert d.escalate is True
    assert "already been tried" in d.reason


def test_escalation_takes_precedence_over_fit_rule() -> None:
    # clearance_off would offer a fit, but a parameter at its bound forces escalation
    d = _diag("S1", [iv(thalf_ratio=1.4, auc_ratio=1.4)], fit=FitSignals(at_bound=("elim.hepatic.CYP3A4.clspec",)))
    assert d.escalate is True
    assert d.permitted_actions == ()


# --- acceptance: >= 80% of the 20 cases agree on the ruleset's first action ----------------------

CASES = [
    ("S1", [iv(thalf_ratio=1.4, auc_ratio=1.4)], {}, "fit elim.hepatic.{enzyme}.clspec"),
    ("S1", [iv(thalf_ratio=0.6, auc_ratio=0.6)], {}, "fit elim.hepatic.{enzyme}.clspec"),
    ("S1", [iv(auc_in_limits=True, early_phase_off=True, vss_off=True)], {}, "branch dist.partition_method"),
    ("S1", [iv(permeability_shape_off=True, vss_off=False)], {}, "branch dist.permeability_method"),
    ("S2", [po(cmax_ratio=1.6, tmax_ratio=0.5)], {}, "fit perm.intestinal"),
    ("S2", [po(cmax_ratio=0.5, tmax_ratio=1.6, auc_in_limits=True)], {}, "fit perm.intestinal"),
    ("S2", [po(study_id="lo", dose_mg=10, observed_auc=100), po(study_id="hi", dose_mg=100, observed_auc=2000)], {},
     "switch elim.hepatic.{enzyme}.mm"),
    ("S2", [po(study_id="lo", dose_mg=10, observed_auc=200, auc_ratio=0.5),
            po(study_id="hi", dose_mg=100, observed_auc=1000, auc_ratio=0.5)], {}, "fit phys.solubility.ref"),
    ("S2", [po(dose_mg=10, observed_auc=200, auc_ratio=0.5)], {}, "fit perm.intestinal"),
    ("S2", [po(secondary_peak=True)], {}, "fit elim.ehc_fraction"),
    ("S3", [po()], {"fed": FedSignals(auc_ratio_off=True, cmax_consistent=True)}, "fit food.fed_solubility_factor"),
    ("S1", [iv()], {"fit": FitSignals(correlated_pairs=(("phys.logp", "perm.cellular"),))}, "fix_and_refit phys.logp|perm.cellular"),
    ("S1", [iv()], {"fit": FitSignals(starts_agreement=0.3)}, "switch_algorithm DEoptim"),
    ("S1", [iv(thalf_ratio=1.4, auc_ratio=1.4, study_id="a"), iv(study_id="b", thalf_ratio=1.0, auc_ratio=1.0)], {},
     "fit elim.hepatic.{enzyme}.clspec"),
    ("S2", [po(cmax_ratio=2.0, tmax_ratio=0.4)], {}, "fit perm.intestinal"),
    ("S2", [po(cmax_ratio=0.4, tmax_ratio=2.0, auc_in_limits=True)], {}, "fit perm.intestinal"),
    ("S1", [iv(thalf_ratio=1.4, auc_ratio=1.4)], {"actions_tried": ["fit elim.hepatic.{enzyme}.clspec"]},
     "fit elim.renal.gfr_fraction"),
    ("S3", [po()], {"fed": FedSignals(auc_ratio_off=True, cmax_consistent=True)}, "fit food.fed_solubility_factor"),
    ("S2", [po(study_id="lo", dose_mg=5, observed_auc=50), po(study_id="hi", dose_mg=50, observed_auc=1500)], {},
     "switch elim.hepatic.{enzyme}.mm"),
    ("S1", [iv(thalf_ratio=1.3, auc_ratio=1.3)], {}, "fit elim.hepatic.{enzyme}.clspec"),
]


@pytest.mark.parametrize("stage,residuals,kw,expected_first", CASES)
def test_first_action_matches_ruleset(stage, residuals, kw, expected_first) -> None:
    d = _diag(stage, residuals, **kw)
    assert d.permitted_actions and d.permitted_actions[0] == expected_first


@pytest.mark.req("T-14", "D7")
def test_case_agreement_at_least_80_percent() -> None:
    agree = 0
    for stage, residuals, kw, expected_first in CASES:
        d = _diag(stage, residuals, **kw)
        if d.permitted_actions and d.permitted_actions[0] == expected_first:
            agree += 1
    assert agree / len(CASES) >= 0.8
