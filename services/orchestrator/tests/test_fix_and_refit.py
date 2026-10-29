"""MS-01's fix_and_refit carried out by the round activities (PI-2b; the owner's rule of 2026-10-25, UNVERIFIED).

A fit whose two parameters the data cannot tell apart (|r| > 0.95) hands the pair to the diagnosis. The next round fixes
the one with the more reliable signed source (the higher grade; measured beats predicted) at its signed value and
refits the rest. A pair the signed sources cannot rank escalates instead. No engine needed: the activities read
`file://` inputs, and the fit's outcome is given.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from modeler_contracts.runs import FitRoundOutcome, FitStartOutcome, RoundContext, RoundEvaluation, RoundRun
from modeler_orchestrator.campaign_activities import _stage_fits, build_round_snapshot, diagnose_round, run_round
from pbpk_domain.campaign.map import MapDocument, generate_map
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
from pbpk_domain.cpf import CPF, FitPolicy, ParameterRecord, ParameterStatus, Provenance
from pbpk_domain.m15 import Rating

pytestmark = pytest.mark.req("T-14")

PAIR = "fix_and_refit phys.logp|bind.fu"
FIT_BOTH = "fit phys.logp+bind.fu"


def _signed_cpf() -> CPF:
    prov = Provenance(source_type="Publication", reference="Example 2020")
    return CPF(compound="Example-A", parameters=(
        ParameterRecord(id="phys.mw", value=408.5, unit="g/mol", status=ParameterStatus.FIXED, provenance=prov),
        ParameterRecord(id="phys.logp", value=2.6, unit="Log Units", status=ParameterStatus.FIXED, provenance=prov,
                        fit_policy=FitPolicy(stage=("S1",), lower=1.0, upper=4.0)),
        ParameterRecord(id="bind.fu", value=0.02, status=ParameterStatus.FIXED, provenance=prov,
                        fit_policy=FitPolicy(stage=("S1",), lower=0.005, upper=0.2)),
        ParameterRecord(id="phys.solubility.ref", value=0.1, unit="mg/ml", status=ParameterStatus.FIXED, provenance=prov),
    ))


def _inputs(tmp_path: Path, grades: dict[str, str] | None) -> tuple[str, str, str]:
    """The signed MAP (with the sources' grades, or none), the CPF after S1 fitted both, and an observed IV profile."""
    adult = Demographics(sex=Sex.MALE, age_years=35.0)
    studies = [StudyRecord(study_id="iv", n=12, design="SD", route=Route.IV_BOLUS, dose_mg=5.0, infusion_time_min=5.0,
                           formulation=FormulationKind.SOLUTION, food_state=FoodState.FASTED, n_timepoints=15, demographics=adult)]
    signed = generate_map(compound="Example-A", cpf=_signed_cpf(), studies=studies,
                          split=split_studies(studies, QuestionOfInterest()), objective="o", context_of_use="c",
                          food_effect_in_question=False, model_risk=Rating.HIGH, engine_image_digest="sha256:abcd",
                          software_versions={"ospsuite": "12.4.4"}, grades=grades).sign(printed_name="Owner")
    fitted = _signed_cpf().replace(*(
        r.model_copy(update={"value": v, "status": ParameterStatus.FITTED, "fitted_at_stage": "S1",
                             "provenance": Provenance(source_type="ParameterIdentification")})
        for r, v in ((_signed_cpf().get("phys.logp"), 3.4), (_signed_cpf().get("bind.fu"), 0.03))))
    (tmp_path / "map.json").write_text(signed.model_dump_json(), encoding="utf-8")
    (tmp_path / "cpf.json").write_text(fitted.model_dump_json(), encoding="utf-8")
    (tmp_path / "observed.json").write_text(json.dumps({"iv": {"auc": 100.0, "cmax": 20.0, "profile": {
        "times": [0.5, 1, 4], "values": [12.0, 20.0, 5.0], "time_unit": "h", "unit": "ng/ml"}}}), encoding="utf-8")
    return (tmp_path / "cpf.json").as_uri(), (tmp_path / "map.json").as_uri(), (tmp_path / "observed.json").as_uri()


def _ctx(tmp_path: Path, grades, *, pending: str | None = PAIR, tried=(FIT_BOTH, PAIR), **kw) -> RoundContext:
    cpf_uri, map_uri, observed_uri = _inputs(tmp_path, grades)
    return RoundContext(campaign_id="c1", tenant_id="t1", stage="S1", round_index=3, cpf_uri=cpf_uri, cpf_sha256="a" * 64,
                        pending_action=pending, actions_tried=list(tried), map_uri=map_uri, observed_uri=observed_uri, **kw)


def _outcome(estimates: dict[str, float]) -> FitRoundOutcome:
    return FitRoundOutcome(round_id="r", planned_starts=1, starts=[FitStartOutcome(0, "SUCCEEDED", estimates, 1.0, True, 10)],
                           acceptable=True, findings=[], best_start_index=0, deadline_reached=False)


def _cpf(uri: str) -> CPF:
    return CPF.model_validate_json(Path(uri.removeprefix("file://")).read_text(encoding="utf-8"))


def test_the_more_reliable_parameter_is_fixed_at_its_signed_value_and_the_rest_refitted(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, {"phys.logp": "A", "bind.fu": "C"})
    build = build_round_snapshot(ctx)
    assert build.needs_fit and [p.name for p in build.fit_request.parameters] == ["bind.fu"]
    assert any(n.startswith("MS-01 fix_and_refit at S1 round 3: phys.logp fixed at its signed source value 2.6 Log Units, "
                            "bind.fu refitted; phys.logp has the more reliable source (a higher grade") for n in build.notes)
    # the round simulates the model with the fixed value: the snapshot is built from the fixed CPF
    snapshot = json.loads(Path(build.snapshot_uri.removeprefix("file://")).read_text(encoding="utf-8"))
    logp = snapshot["Compounds"][0]["Lipophilicity"][0]["Parameters"][0]
    assert (logp["Name"], logp["Value"], logp["ValueOrigin"]["Source"]) == ("Lipophilicity", 2.6, "Publication")

    # the refit's estimate goes into the fixed CPF, which carries forward
    result = run_round(RoundRun(context=ctx, build=build, fit_outcome=_outcome({"bind.fu": 0.025})))
    cpf = _cpf(result.cpf_uri)
    assert cpf.get("phys.logp").value == 2.6 and cpf.get("phys.logp").status is ParameterStatus.FIXED
    assert cpf.get("bind.fu").value == 0.025 and cpf.get("bind.fu").status is ParameterStatus.FITTED
    assert "fixed at its signed source value" in cpf.get("phys.logp").provenance.reference
    # without an estimate the fix still carries forward
    kept = run_round(RoundRun(context=ctx, build=build, fit_outcome=None))
    assert kept.cpf_uri != ctx.cpf_uri and _cpf(kept.cpf_uri).get("phys.logp").value == 2.6


def test_a_measured_value_is_fixed_before_a_predicted_one_of_the_same_grade(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, {"phys.logp": "B", "bind.fu": "B"})
    signed = MapDocument.model_validate_json(Path(ctx.map_uri.removeprefix("file://")).read_text(encoding="utf-8"))
    predicted_logp = signed.model_copy(update={"cpf_parameters": tuple(
        p.model_copy(update={"status": "PREDICTED"}) if p.id == "phys.logp" else p for p in signed.cpf_parameters)})
    fit_ids, fixed, problem = _stage_fits(ctx, _cpf(ctx.cpf_uri), predicted_logp)
    assert problem is None and fit_ids == ("phys.logp",) and fixed[0].fixed == "bind.fu"


def test_a_parameter_fixed_in_the_stage_stays_out_of_its_later_fits(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, {"phys.logp": "A", "bind.fu": "C"}, pending="fit phys.logp+bind.fu+phys.solubility.ref",
               tried=(FIT_BOTH, PAIR, "fit phys.logp+bind.fu+phys.solubility.ref"))
    signed = MapDocument.model_validate_json(Path(ctx.map_uri.removeprefix("file://")).read_text(encoding="utf-8"))
    fit_ids, fixed, problem = _stage_fits(ctx, _cpf(ctx.cpf_uri), signed)
    assert problem is None and [f.fixed for f in fixed] == ["phys.logp"]
    assert fit_ids == ("bind.fu", "phys.solubility.ref")


def test_a_pair_the_signed_sources_cannot_rank_is_not_refitted_and_escalates(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, None)  # no grades, both measured: nothing says which is more reliable
    build = build_round_snapshot(ctx)
    assert build.fit_request is None
    assert any("FIT NOT RUN in round 3" in n and "neither source is more reliable" in n for n in build.notes)
    assert run_round(RoundRun(context=ctx, build=build, fit_outcome=None)).cpf_uri == ctx.cpf_uri

    # the diagnosis of the fit that found the pair escalates instead of choosing the action
    judged = _ctx(tmp_path, None, pending=None, tried=(FIT_BOTH,), phase="postfit",
                  fit_signals={"at_bound": [], "correlated_pairs": [["phys.logp", "bind.fu"]], "starts_agreement": 1.0})
    diagnosis = diagnose_round(judged, _evaluation())
    assert diagnosis.escalate and diagnosis.permitted_actions == []
    assert diagnosis.escalation_reason.startswith("non-identifiable pair phys.logp and bind.fu (|r| > 0.95): neither source "
                                                  "is more reliable: phys.logp (no grade, measured), bind.fu (no grade, measured)")


def _evaluation() -> RoundEvaluation:
    # PK within the diagnostic band: only the fit's optimiser evidence fires a rule
    study = {"study_id": "iv", "gated": True, "role": "fitting", "predicted_auc": 100.0, "observed_auc": 100.0,
             "predicted_cmax": 20.0, "observed_cmax": 20.0, "predicted_thalf": 60.0, "observed_thalf": 60.0}
    return RoundEvaluation(gate_passed=False, acceptable=False, metrics={"studies": [study]}, findings=[])


def test_the_pair_reaches_the_diagnosis_and_its_action_names_what_will_be_fixed(tmp_path: Path) -> None:
    judged = _ctx(tmp_path, {"phys.logp": "A", "bind.fu": "C"}, pending=None, tried=(FIT_BOTH,), phase="postfit",
                  fit_signals={"at_bound": [], "correlated_pairs": [["phys.logp", "bind.fu"]], "starts_agreement": 1.0})
    diagnosis = diagnose_round(judged, _evaluation())
    assert not diagnosis.escalate and diagnosis.permitted_actions == [PAIR]
    assert "correlated_pair" in diagnosis.evidence
    assert any("phys.logp and bind.fu are not identifiable together (|r| > 0.95); if refitted, phys.logp is fixed at its "
               "signed source value and bind.fu refitted" in n for n in diagnosis.notes)
