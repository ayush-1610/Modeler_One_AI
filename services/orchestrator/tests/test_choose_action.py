"""choose_action delegates to the strategist and stays inside the diagnostics' permitted set (T-15 wiring).

With no per-tenant model the strategist returns the first not-yet-tried permitted action, so choose_action
reproduces the ruleset's first action. The 20-case eval below is the T-15 acceptance: the chosen action agrees
with the ruleset's first action for >= 80% of cases (here 100%, since the fallback is that first action).
"""

from __future__ import annotations

from modeler_contracts.runs import RoundContext, RoundDiagnosis
from modeler_orchestrator.campaign_activities import choose_action
from pbpk_domain.campaign.map import STAGE_PLAN
from pbpk_domain.diagnostics import FedSignals, FitSignals, StudyResidual, diagnose


def _ctx(stage: str, actions_tried=()) -> RoundContext:
    return RoundContext(
        campaign_id="c1", tenant_id="t1", stage=stage, round_index=1,
        cpf_uri="x", cpf_sha256="a" * 64, pending_action=None, actions_tried=list(actions_tried),
    )


def _diagnose(stage, residuals, **kw) -> RoundDiagnosis:
    d = diagnose(residuals, stage=stage, stage_candidates=STAGE_PLAN[stage]["fit_candidates"],
                 stage_branches=STAGE_PLAN[stage]["branches"], **kw)
    return RoundDiagnosis(evidence=list(d.evidence), causes=list(d.causes),
                          permitted_actions=list(d.permitted_actions), escalate=d.escalate, escalation_reason=d.reason)


def iv(**kw):
    return StudyResidual(study_id=kw.pop("study_id", "iv"), role="fitting", route="iv", **kw)


def po(**kw):
    return StudyResidual(study_id=kw.pop("study_id", "po"), role="fitting", route="oral", **kw)


def test_delegates_to_strategist_first_permitted() -> None:
    diag = _diagnose("S1", [iv(thalf_ratio=1.4, auc_ratio=1.4)])
    choice = choose_action(_ctx("S1"), diag)
    assert choice.action_id == "fit elim.hepatic.{enzyme}.clspec"
    assert choice.source == "fallback"
    assert choice.parameters_to_fit == ["elim.hepatic.{enzyme}.clspec"]


def test_skips_tried_action() -> None:
    diag = _diagnose("S1", [iv(thalf_ratio=1.4, auc_ratio=1.4)])
    choice = choose_action(_ctx("S1", actions_tried=["fit elim.hepatic.{enzyme}.clspec"]), diag)
    assert choice.action_id == "fit phys.logp"


def test_no_permitted_action_returns_none() -> None:
    diag = _diagnose("S1", [iv(thalf_ratio=1.0, auc_ratio=1.0)])  # no evidence -> empty permitted set
    choice = choose_action(_ctx("S1"), diag)
    assert choice.action_id is None
    assert choice.source == "none"


# --- T-15 acceptance: >= 80% of the 20 cases agree with the ruleset's first action ---------------

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
    ("S2", [po(cmax_ratio=2.0, tmax_ratio=0.4)], {}, "fit perm.intestinal"),
    ("S2", [po(cmax_ratio=0.4, tmax_ratio=2.0, auc_in_limits=True)], {}, "fit perm.intestinal"),
    ("S3", [po()], {"fed": FedSignals(auc_ratio_off=True, cmax_consistent=True)}, "fit food.fed_solubility_factor"),
    ("S2", [po(study_id="lo", dose_mg=5, observed_auc=50), po(study_id="hi", dose_mg=50, observed_auc=1500)], {},
     "switch elim.hepatic.{enzyme}.mm"),
    ("S1", [iv(thalf_ratio=1.3, auc_ratio=1.3)], {}, "fit elim.hepatic.{enzyme}.clspec"),
    ("S2", [po(cmax_ratio=1.8, tmax_ratio=0.6)], {}, "fit perm.intestinal"),
    ("S1", [iv(auc_in_limits=True, early_phase_off=True, vss_off=True)], {}, "branch dist.partition_method"),
]


def test_case_agreement_at_least_80_percent() -> None:
    agree = 0
    for stage, residuals, kw, expected in CASES:
        diag = _diagnose(stage, residuals, **kw)
        choice = choose_action(_ctx(stage), diag)
        if choice.action_id == expected:
            agree += 1
    assert agree / len(CASES) >= 0.8
    assert agree == len(CASES)  # the deterministic fallback is exactly the ruleset's first action
