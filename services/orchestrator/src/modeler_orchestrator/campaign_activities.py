"""Activities for the campaign workflows (task T-13).

Two kinds live here. Deterministic, domain-only steps are implemented now: `plan_campaign` runs the S0
completeness gate from the CPF, and `choose_action` picks the first permitted action (the deterministic
fallback the strategist agent in T-15 will replace). The rest are boundaries to subsystems still being
built — `build_round_snapshot` needs the MAP's scenarios (T-16) and the CPF builder, `run_round` the
engine (T-09), `evaluate_round` the engine results and `acceptance.evaluate`, `diagnose_round` the
diagnostics ruleset (T-14), and `resume_campaign`/`record_round` persistence (T-05). They have final
signatures and honest placeholder behaviour so the workflow state machine is complete and testable today.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse

from temporalio import activity

from modeler_contracts.runs import (
    ActionChoice,
    CampaignRequest,
    ResumeState,
    RoundBuild,
    RoundContext,
    RoundDiagnosis,
    RoundEvaluation,
    RoundRecord,
    RoundRun,
    RoundRunResult,
    S0Readiness,
)


def _load_local_text(uri: str) -> str | None:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return None
    return Path(unquote(parsed.path)).read_text(encoding="utf-8")


@activity.defn(name="plan_campaign")
def plan_campaign(request: CampaignRequest) -> S0Readiness:
    """S0 readiness. Runs the CPF completeness gate (MS-01 §2.2) when the CPF is a local file; other
    object stores are read once T-07 lands."""
    text = _load_local_text(request.cpf_uri)
    if text is None:
        return S0Readiness(ready=True, findings=["CPF not loadable in this environment; completeness not checked (T-07 pending)"])
    from pbpk_domain.cpf import CPF, check_completeness

    report = check_completeness(CPF.model_validate_json(text))
    return S0Readiness(ready=report.ready, findings=list(report.missing))


@activity.defn(name="resume_campaign")
def resume_campaign(request: CampaignRequest) -> ResumeState:
    """Reconstruct progress from persisted rows so a re-started campaign is idempotent. Until the
    persistence layer (T-05) exists, every campaign starts fresh from its request CPF."""
    return ResumeState(last_completed_stage=None, cpf_uri=request.cpf_uri, cpf_sha256=request.cpf_sha256)


@activity.defn(name="build_round_snapshot")
def build_round_snapshot(ctx: RoundContext) -> RoundBuild:
    """Build the round's snapshot from the CPF and the MAP's scenarios, and, when the pending action is a
    fit, the fit request. Full implementation needs the MAP scenarios (T-16) and engine benchmark; for now
    it decides only whether the round fits (any 'fit …' action) and echoes the CPF as the snapshot."""
    needs_fit = bool(ctx.pending_action and ctx.pending_action.startswith("fit"))
    activity.logger.info("build_round_snapshot %s %s round %d fit=%s", ctx.campaign_id, ctx.stage, ctx.round_index, needs_fit)
    return RoundBuild(snapshot_uri=ctx.cpf_uri, snapshot_sha256=ctx.cpf_sha256, needs_fit=needs_fit, fit_request=None)


@activity.defn(name="run_round")
def run_round(run: RoundRun) -> RoundRunResult:
    """Apply the fit (parameter transfer, new CPF version) when one ran, then simulate the INTERNAL
    studies for evaluation. Engine and persistence wiring lands with T-09/T-05; for now it echoes the CPF."""
    ctx = run.context
    return RoundRunResult(results_uri=f"{ctx.cpf_uri}#results-r{ctx.round_index}", cpf_uri=ctx.cpf_uri, cpf_sha256=ctx.cpf_sha256)


@activity.defn(name="evaluate_round")
def evaluate_round(ctx: RoundContext, run_result: RoundRunResult) -> RoundEvaluation:
    """Compute PK metrics from the run and judge them against the tier gate (`acceptance.evaluate`).
    Needs engine results (T-08/T-18); until then no gate can pass, so a round always proceeds to
    diagnostics (the workflow logic under test) rather than falsely passing."""
    return RoundEvaluation(gate_passed=False, acceptable=False, metrics={}, findings=["evaluation not wired to engine results yet (T-18)"])


@activity.defn(name="diagnose_round")
def diagnose_round(ctx: RoundContext, evaluation: RoundEvaluation) -> RoundDiagnosis:
    """Map round evidence to permitted actions (MS-01 §5). The deterministic ruleset is T-14; until then
    a round with no evidence escalates rather than inventing an action."""
    return RoundDiagnosis(evidence=[], permitted_actions=[], escalate=True, escalation_reason="diagnostics ruleset not available (T-14)")


@activity.defn(name="choose_action")
def choose_action(ctx: RoundContext, diagnosis: RoundDiagnosis) -> ActionChoice:
    """Pick the next action from the permitted set, skipping ones already tried. This is the deterministic
    fallback (first permitted action); the strategist agent (T-15) refines the choice and its rationale."""
    for action in diagnosis.permitted_actions:
        if action not in ctx.actions_tried:
            return ActionChoice(action_id=action, rationale="first permitted action not yet tried (deterministic fallback)")
    return ActionChoice(action_id=None, rationale="no permitted action left to try")


@activity.defn(name="record_round")
def record_round(record: RoundRecord) -> None:
    """Persist the full round record (CPF before/after, fit specs, metrics, diagnostics, chosen action,
    manifests, wall time) with an audit event. Persistence is T-05; for now the round is logged."""
    ctx = record.context
    activity.logger.info(
        "record_round %s %s round %d gate=%s action=%s",
        ctx.campaign_id, ctx.stage, ctx.round_index, record.evaluation.gate_passed,
        record.choice.action_id if record.choice else None,
    )


CAMPAIGN_ACTIVITIES = [
    plan_campaign,
    resume_campaign,
    build_round_snapshot,
    run_round,
    evaluate_round,
    diagnose_round,
    choose_action,
    record_round,
]
