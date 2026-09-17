"""evaluate_round reduces a run's simulated profiles to PK and judges the tier gate (T-13 <-> T-18 wiring).

No Docker or engine needed: it reads the MAP (tier + roles), a normalized profile bundle (as `run_round`
will emit) and the observed PK, all as local `file://` JSON, and returns a real gate verdict. Missing inputs
mean the gate cannot pass yet (the round proceeds to diagnostics) rather than a false pass.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from modeler_contracts.runs import RoundContext, RoundRunResult
from modeler_orchestrator.campaign_activities import evaluate_round
from pbpk_domain.campaign.map import generate_map
from pbpk_domain.campaign.split import (
    FoodState,
    FormulationKind,
    QuestionOfInterest,
    Route,
    StudyRecord,
    split_studies,
)
from pbpk_domain.cpf import CPF, ParameterRecord, ParameterStatus, Provenance
from pbpk_domain.m15 import Rating

GOLDEN = Path(__file__).parents[2] / "engine-worker" / "golden" / "results_sample" / "results.csv"
GOLDEN_AUC, GOLDEN_CMAX = 4064.1245, 50.25272


def _cpf() -> CPF:
    prov = Provenance(source_type="measured", reference="Example 2020")

    def rec(pid, value, unit=None):
        return ParameterRecord(id=pid, value=value, unit=unit, status=ParameterStatus.FIXED, provenance=prov)

    return CPF(compound="Example-A", parameters=(
        rec("phys.mw", 408.5, "g/mol"), rec("phys.logp", 2.6, "Log Units"),
        rec("bind.fu", 0.02), rec("phys.solubility.ref", 0.1, "mg/ml"),
    ))


def _write_map(tmp_path: Path) -> str:
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


def _write_profiles(tmp_path: Path) -> str:
    rows = [r for r in csv.reader(GOLDEN.open(encoding="utf-8-sig")) if r]
    times = [float(r[1]) for r in rows[1:]]
    concs = [float(r[2]) for r in rows[1:]]
    p = tmp_path / "profiles.json"
    p.write_text(json.dumps({"profiles": {"iv": {"times_min": times, "concentrations": concs}}}), encoding="utf-8")
    return p.as_uri()


def _write_observed(tmp_path: Path, auc: float, cmax: float) -> str:
    p = tmp_path / "observed.json"
    p.write_text(json.dumps({"iv": {"auc": auc, "cmax": cmax}}), encoding="utf-8")
    return p.as_uri()


def _ctx(tmp_path: Path, *, map_uri: str, observed_uri: str = "") -> RoundContext:
    return RoundContext(
        campaign_id="c1", tenant_id="t1", stage="S1", round_index=1,
        cpf_uri=(tmp_path / "cpf.json").as_uri(), cpf_sha256="a" * 64, pending_action=None,
        map_uri=map_uri, observed_uri=observed_uri,
    )


def test_gate_passes_when_prediction_matches_observed(tmp_path: Path) -> None:
    map_uri = _write_map(tmp_path)
    results = RoundRunResult(results_uri=_write_profiles(tmp_path), cpf_uri="x", cpf_sha256="b" * 64)
    ctx = _ctx(tmp_path, map_uri=map_uri, observed_uri=_write_observed(tmp_path, GOLDEN_AUC, GOLDEN_CMAX))
    ev = evaluate_round(ctx, results)
    assert ev.gate_passed is True
    assert ev.metrics["AUC"]["n"] == 1
    assert ev.metrics["groups"]  # tier groups reported


def test_gate_fails_when_prediction_off(tmp_path: Path) -> None:
    map_uri = _write_map(tmp_path)
    results = RoundRunResult(results_uri=_write_profiles(tmp_path), cpf_uri="x", cpf_sha256="b" * 64)
    ctx = _ctx(tmp_path, map_uri=map_uri, observed_uri=_write_observed(tmp_path, GOLDEN_AUC * 3, GOLDEN_CMAX * 3))
    ev = evaluate_round(ctx, results)
    assert ev.gate_passed is False
    assert any("AUC" in f for f in ev.findings)


def test_without_observed_cannot_pass(tmp_path: Path) -> None:
    map_uri = _write_map(tmp_path)
    results = RoundRunResult(results_uri=_write_profiles(tmp_path), cpf_uri="x", cpf_sha256="b" * 64)
    ev = evaluate_round(_ctx(tmp_path, map_uri=map_uri), results)
    assert ev.gate_passed is False
    assert any("no observed PK" in f for f in ev.findings)


def test_without_results_bundle_cannot_pass(tmp_path: Path) -> None:
    map_uri = _write_map(tmp_path)
    results = RoundRunResult(results_uri="file:///nonexistent/profiles.json", cpf_uri="x", cpf_sha256="b" * 64)
    ev = evaluate_round(_ctx(tmp_path, map_uri=map_uri), results)
    assert ev.gate_passed is False
    assert any("no simulated profile" in f for f in ev.findings)
