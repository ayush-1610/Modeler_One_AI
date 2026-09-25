"""diagnose_round maps a failed evaluation to permitted actions via the ruleset (T-13 <-> T-14 wiring).

No Docker or engine needed: it reads the MAP (stage plan + scenario routes/doses) and the evaluation metrics,
builds each study's PK residuals and calls pbpk_domain.diagnostics.diagnose. Drives it from a real
evaluate_round output so the metrics shape is the true one.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from modeler_contracts.runs import RoundContext, RoundEvaluation, RoundRunResult
from modeler_orchestrator.campaign_activities import diagnose_round, evaluate_round
from pbpk_domain.campaign.map import generate_map
from pbpk_domain.campaign.split import (
    FoodState,
    FormulationKind,
    QuestionOfInterest,
    Route,
    StudyRecord,
    split_studies,
)
from pbpk_domain.cpf import CPF, EngineBinding, ParameterRecord, ParameterStatus, Provenance
from pbpk_domain.m15 import Rating

GOLDEN = Path(__file__).parents[2] / "engine-worker" / "golden" / "results_sample" / "results.csv"
GOLDEN_AUC, GOLDEN_CMAX = 4064.1245, 50.25272


def _cpf() -> CPF:
    prov = Provenance(source_type="measured", reference="Example 2020")

    def rec(pid, value, unit=None, binding=None):
        return ParameterRecord(id=pid, value=value, unit=unit, status=ParameterStatus.FIXED,
                               provenance=prov, engine_binding=binding)

    return CPF(compound="Example-A", parameters=(
        rec("phys.mw", 408.5, "g/mol"), rec("phys.logp", 2.6, "Log Units"),
        rec("bind.fu", 0.02), rec("phys.solubility.ref", 0.1, "mg/ml"),
        rec("elim.hepatic.CYP3A4.clspec", 0.8, "l/µmol/min",
            EngineBinding(building_block="Compound", process="MetabolizationSpecific_FirstOrder:CYP3A4",
                          parameter="CLspec/[Enzyme]", data_source="Optimized")),
    ))


def _iv_map(tmp_path: Path) -> str:
    studies = [
        StudyRecord(study_id="iv", n=12, design="SD", route=Route.IV_BOLUS, dose_mg=5.0, infusion_time_min=5.0,
                    formulation=FormulationKind.SOLUTION, food_state=FoodState.FASTED, n_timepoints=15),
    ]
    split = split_studies(studies, QuestionOfInterest())
    m = generate_map(
        compound="Example-A", cpf=_cpf(), studies=studies, split=split, objective="predict",
        context_of_use="MIDD", food_effect_in_question=False, model_risk=Rating.HIGH,
        engine_image_digest="sha256:abcd", software_versions={"ospsuite": "12.4.4"},
    )
    p = tmp_path / "map.json"
    p.write_text(m.model_dump_json(), encoding="utf-8")
    return p.as_uri()


def _profiles(tmp_path: Path) -> str:
    rows = [r for r in csv.reader(GOLDEN.open(encoding="utf-8-sig")) if r]
    times = [float(r[1]) for r in rows[1:]]
    concs = [float(r[2]) for r in rows[1:]]
    p = tmp_path / "profiles.json"
    p.write_text(json.dumps({"profiles": {"iv": {"times_min": times, "concentrations": concs}}}), encoding="utf-8")
    return p.as_uri()


def _observed(tmp_path: Path, *, auc, cmax, thalf) -> str:
    # thalf is in minutes, the unit of the simulated profile's time axis (predicted t1/2 ~181 min)
    p = tmp_path / "observed.json"
    p.write_text(json.dumps({"iv": {"auc": auc, "cmax": cmax, "thalf": thalf}}), encoding="utf-8")
    return p.as_uri()


def _ctx(tmp_path: Path, map_uri: str, observed_uri: str) -> RoundContext:
    return RoundContext(
        campaign_id="c1", tenant_id="t1", stage="S1", round_index=1,
        cpf_uri=(tmp_path / "cpf.json").as_uri(), cpf_sha256="a" * 64, pending_action=None,
        map_uri=map_uri, observed_uri=observed_uri,
    )


def test_clearance_evidence_yields_clspec_action(tmp_path: Path) -> None:
    map_uri = _iv_map(tmp_path)
    # observed AUC ~3x below predicted and observed t1/2 (60 min) below predicted (181 min): both "high" the
    # same way -> clearance too low (the model clears too slowly)
    obs = _observed(tmp_path, auc=GOLDEN_AUC / 3, cmax=GOLDEN_CMAX / 3, thalf=60.0)
    ctx = _ctx(tmp_path, map_uri, obs)
    ev = evaluate_round(ctx, RoundRunResult(results_uri=_profiles(tmp_path), cpf_uri="x", cpf_sha256="b" * 64))
    assert ev.gate_passed is False
    diag = diagnose_round(ctx, ev)
    assert diag.escalate is False
    assert diag.permitted_actions[0] == "fit elim.hepatic.{enzyme}.clspec"
    assert "clearance_off" in diag.evidence


def test_no_matching_evidence_escalates(tmp_path: Path) -> None:
    map_uri = _iv_map(tmp_path)
    # prediction matches observed -> gate passes; diagnose still runs but finds no evidence -> escalate
    obs = _observed(tmp_path, auc=GOLDEN_AUC, cmax=GOLDEN_CMAX, thalf=181.0)
    ctx = _ctx(tmp_path, map_uri, obs)
    ev = evaluate_round(ctx, RoundRunResult(results_uri=_profiles(tmp_path), cpf_uri="x", cpf_sha256="b" * 64))
    diag = diagnose_round(ctx, ev)
    assert diag.escalate is True
    assert "no diagnostic rule matched" in diag.escalation_reason


def test_missing_map_escalates(tmp_path: Path) -> None:
    ctx = RoundContext(
        campaign_id="c1", tenant_id="t1", stage="S1", round_index=1,
        cpf_uri="x", cpf_sha256="a" * 64, pending_action=None, map_uri="",
    )
    diag = diagnose_round(ctx, RoundEvaluation(gate_passed=False, acceptable=False, metrics={}, findings=[]))
    assert diag.escalate is True
    assert "MAP not locally loadable" in diag.escalation_reason


def test_a_fit_left_at_its_bound_escalates_with_the_parameter(tmp_path: Path) -> None:
    # The post-fit pass carries the fit's optimiser evidence: a parameter the fit left at its bound escalates the
    # round with that parameter named (MS-01 §5), whatever PK rule would otherwise fire. Before this was wired,
    # the refit of the published Dapagliflozin model left UGT1A9 clspec at 0.1x and the round reported
    # "no diagnostic rule matched".
    from dataclasses import replace

    map_uri = _iv_map(tmp_path)
    obs = _observed(tmp_path, auc=GOLDEN_AUC / 3, cmax=GOLDEN_CMAX / 3, thalf=60.0)
    ctx = replace(_ctx(tmp_path, map_uri, obs), phase="postfit",
                  fit_signals={"at_bound": ["elim.hepatic.UGT1A9.clspec"], "correlated_pairs": [], "starts_agreement": 1.0})
    ev = evaluate_round(ctx, RoundRunResult(results_uri=_profiles(tmp_path), cpf_uri="x", cpf_sha256="b" * 64))
    diag = diagnose_round(ctx, ev)
    assert diag.escalate is True
    assert "elim.hepatic.UGT1A9.clspec" in diag.escalation_reason
    assert "param_at_bound" in diag.evidence


def test_diagnose_round_is_the_registered_activity() -> None:
    # guards the Temporal registration: the decorator must sit on diagnose_round itself
    from temporalio import activity as temporal_activity

    assert temporal_activity._Definition.from_callable(diagnose_round).name == "diagnose_round"
