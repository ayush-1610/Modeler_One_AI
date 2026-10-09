"""A fit that moves another compound of a model system (multi-compound phase 2, D-20): the estimate goes into that
compound's CPF, the system as of the new version is written beside it, and the next round reads it from there."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from modeler_contracts.runs import FitRoundOutcome, FitStartOutcome, RoundContext
from modeler_orchestrator.campaign_activities import _apply_round_fit, _round_system
from modeler_orchestrator.feedback import new_evidence_cpf
from modeler_orchestrator.round_system import beside, content_sha256, current_system_uri
from pbpk_domain.cpf import CPF
from pbpk_domain.reference.osp_import import import_osp_system
from pbpk_domain.system import ModelSystem

FIXTURES = Path(__file__).resolve().parents[2] / "engine-worker" / "golden" / "fixtures"
HYDROXY = "Hydroxy-Itraconazole"
KCAT = "elim.hepatic.CYP3A4.kcat"
pytestmark = pytest.mark.req("T-14")


def _campaign(tmp_path: Path) -> RoundContext:
    snapshot = json.loads((FIXTURES / "Itraconazole-Model.json").read_text(encoding="utf-8"))
    system = import_osp_system(snapshot).system
    cpf_path, system_path = tmp_path / "cpf.json", tmp_path / "system.json"
    cpf_path.write_text(system.cpf("Itraconazole").model_dump_json(), encoding="utf-8")
    system_path.write_text(system.model_dump_json(), encoding="utf-8")
    return RoundContext(campaign_id="c1", tenant_id="t1", stage="S2", round_index=1, cpf_uri=cpf_path.as_uri(),
                        cpf_sha256="a" * 64, pending_action=None, system_uri=system_path.as_uri())


def _fit(estimates: dict[str, float]) -> FitRoundOutcome:
    start = FitStartOutcome(start_index=0, status="SUCCEEDED", estimates=estimates, converged=True,
                            uncertainty={k: {"sd": 0.01, "cv": 5.0, "ci_lower": v * 0.9, "ci_upper": v * 1.1}
                                         for k, v in estimates.items()})
    return FitRoundOutcome(round_id="r", planned_starts=1, starts=[start], acceptable=True, findings=[],
                           best_start_index=0, deadline_reached=False)


def _cpf(uri: str) -> CPF:
    return CPF.model_validate_json(Path(uri.removeprefix("file://")).read_text(encoding="utf-8"))


def test_a_metabolite_estimate_goes_into_the_metabolites_cpf_beside_the_parents_new_version(tmp_path):
    ctx = _campaign(tmp_path)
    parent = _cpf(ctx.cpf_uri)
    uri, _sha = _apply_round_fit(ctx, _fit({"phys.logp": 4.5, f"{HYDROXY}::{KCAT}": 0.05}))
    updated = _cpf(uri)
    assert updated.version == parent.version + 1 and updated.get("phys.logp").numeric_value == 4.5
    # the system as of the new version is beside it; the metabolite's own CPF holds its fitted value and provenance
    system = ModelSystem.model_validate_json(beside(Path(uri.removeprefix("file://"))).read_text(encoding="utf-8"))
    hydroxy = system.cpf(HYDROXY)
    record = hydroxy.get(KCAT)
    assert record.numeric_value == 0.05 and record.status.value == "FITTED" and record.fitted_at_stage == "S2"
    assert record.provenance.supersedes.startswith(f"{HYDROXY}@") and record.uncertainty.cv_percent == 5.0
    assert system.cpf("Itraconazole") == updated
    # the parent's new version names the compound it moved, so its own hash binds that state
    assert f"{HYDROXY} v{hydroxy.version} (sha256 {content_sha256(hydroxy)[:12]})" in updated.note
    # the next round reads the system from beside its CPF, not the campaign's starting one
    nxt = RoundContext(**{**ctx.__dict__, "cpf_uri": uri, "round_index": 2})
    assert _round_system(nxt, updated).cpf(HYDROXY).get(KCAT).numeric_value == 0.05
    assert current_system_uri(uri, ctx.system_uri) != ctx.system_uri


def test_a_metabolite_only_fit_still_versions_the_parent(tmp_path):
    ctx = _campaign(tmp_path)
    parent = _cpf(ctx.cpf_uri)
    uri, _sha = _apply_round_fit(ctx, _fit({f"{HYDROXY}::{KCAT}": 0.05}))
    updated = _cpf(uri)
    assert updated.version == parent.version + 1 and updated.parameters == parent.parameters
    assert HYDROXY in updated.note


def test_an_estimate_for_a_stranger_is_not_applied(tmp_path):
    ctx = _campaign(tmp_path)
    assert _apply_round_fit(ctx, _fit({f"Nobody::{KCAT}": 0.05})) == (ctx.cpf_uri, ctx.cpf_sha256)


def test_a_new_evidence_version_carries_the_system_forward(tmp_path):
    ctx = _campaign(tmp_path)
    uri, _sha = _apply_round_fit(ctx, _fit({f"{HYDROXY}::{KCAT}": 0.05}))
    record = _cpf(uri).get("phys.logp")
    new_uri, _ = new_evidence_cpf(uri, parameter="phys.logp", value=float(record.numeric_value), unit=record.unit,
                                  reference="Example 2020", cycle=2, campaign_id="c1", failing=["s"],
                                  system_uri=ctx.system_uri)
    assert _round_system(RoundContext(**{**ctx.__dict__, "cpf_uri": new_uri}), _cpf(new_uri)).cpf(HYDROXY).get(KCAT).numeric_value == 0.05


def test_a_single_compound_campaign_writes_no_system(tmp_path):
    ctx = _campaign(tmp_path)
    single = RoundContext(**{**ctx.__dict__, "system_uri": ""})
    uri, _sha = _apply_round_fit(single, _fit({"phys.logp": 4.5}))
    assert not beside(Path(uri.removeprefix("file://"))).exists()
    assert _cpf(uri).note is None or HYDROXY not in _cpf(uri).note


def test_the_joint_refinement_refits_another_compounds_fitted_parameter(tmp_path):
    from modeler_orchestrator.joint import joint_parameters
    from pbpk_domain.cpf.models import FitPolicy

    ctx = _campaign(tmp_path)
    uri, _sha = _apply_round_fit(ctx, _fit({f"{HYDROXY}::{KCAT}": 0.05}))
    updated = _cpf(uri)
    system = _round_system(RoundContext(**{**ctx.__dict__, "cpf_uri": uri}), updated)
    hydroxy = system.cpf(HYDROXY)
    record = hydroxy.get(KCAT).model_copy(update={"fit_policy": FitPolicy(lower=0.001, upper=1.0)})
    system = system.model_copy(update={"compounds": tuple(
        hydroxy.model_copy(update={"parameters": tuple(record if p.id == KCAT else p for p in hydroxy.parameters)})
        if c.compound == HYDROXY else c for c in system.compounds)})
    plan = joint_parameters(updated, ("S2",), system)
    assert plan.fit_ids == (f"{HYDROXY}::{KCAT}",)
    assert joint_parameters(updated, ("S2",)).fit_ids == ()  # outside the system the parent alone fitted nothing
