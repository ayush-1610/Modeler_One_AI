"""Activities for the campaign workflows (task T-13).

Most steps are wired to real subsystems: `plan_campaign` runs the S0 completeness gate from the CPF,
`build_round_snapshot` regenerates the stage snapshot from the CPF and the MAP's scenarios (T-16 +
`pbpk_domain.campaign.round_build`), `choose_action` picks the first permitted action (the deterministic
fallback the strategist agent in T-15 will refine), and `resume_campaign`/`record_round` read and write
durable, audited campaign state through the persistence layer (T-05) when `MODELER_DATABASE_URL` is set —
resuming past finished stages and appending each round, and `evaluate_round` reduces the round's simulated
profiles to PK and judges them against the tier gate (`pbpk_domain.campaign.evaluate` over T-18 NCA +
`acceptance`). The rest are still boundaries: `run_round` needs the engine (T-09) to produce the simulated
profiles `evaluate_round` reads, and `diagnose_round` the diagnostics ruleset (T-14). Every activity has its
final signature, so the workflow state machine is complete and testable today.
"""

from __future__ import annotations

import json
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
from modeler_orchestrator.campaign_store import CampaignStore

_store: CampaignStore | None = None
_store_checked = False


def _campaign_store() -> CampaignStore | None:
    """The campaign store from MODELER_DATABASE_URL, created once; None when no database is configured."""
    global _store, _store_checked
    if not _store_checked:
        _store = CampaignStore.from_env()
        _store_checked = True
    return _store


def _local_path(uri: str) -> Path | None:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return None
    return Path(unquote(parsed.path))


def _load_local_text(uri: str) -> str | None:
    path = _local_path(uri)
    return None if path is None else path.read_text(encoding="utf-8")


def _load_local_json(uri: str) -> dict | None:
    """Parse a local `file://` JSON document, or None when it is not a loadable local file."""
    path = _local_path(uri)
    if path is None or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


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
async def resume_campaign(request: CampaignRequest) -> ResumeState:
    """Reconstruct progress from persisted rows (create the campaign row on first run) so a re-started
    campaign resumes past the stages it already finished. Without a database, every campaign starts fresh."""
    store = _campaign_store()
    if store is None:
        return ResumeState(last_completed_stage=None, cpf_uri=request.cpf_uri, cpf_sha256=request.cpf_sha256)
    return await store.resume(request)


@activity.defn(name="build_round_snapshot")
def build_round_snapshot(ctx: RoundContext) -> RoundBuild:
    """Regenerate the round's snapshot from the CPF and the MAP's scenarios for this stage.

    Loads the CPF and MAP (local `file://` today; the object store lands with the run wiring), builds the
    stage snapshot via `pbpk_domain.campaign.round_build.build_stage_snapshot`, writes it next to the CPF and
    returns its URI and content hash. The fit request itself (the PI spec) is a separate task, so `needs_fit`
    only flags that the pending action is a fit. When the CPF or MAP is not locally loadable, or no scenario
    trains this stage (e.g. the validation stages), the round falls back to echoing the CPF so the workflow
    still advances; the reason is logged."""
    needs_fit = bool(ctx.pending_action and ctx.pending_action.startswith("fit"))

    def _echo(reason: str) -> RoundBuild:
        activity.logger.info(
            "build_round_snapshot %s %s round %d: echoing CPF (%s)", ctx.campaign_id, ctx.stage, ctx.round_index, reason
        )
        return RoundBuild(snapshot_uri=ctx.cpf_uri, snapshot_sha256=ctx.cpf_sha256, needs_fit=needs_fit, fit_request=None)

    cpf_text = _load_local_text(ctx.cpf_uri)
    map_text = _load_local_text(ctx.map_uri) if ctx.map_uri else None
    if cpf_text is None or map_text is None:
        return _echo("CPF or MAP not locally loadable (object-store I/O pending)")

    from pbpk_domain.campaign.map import MapDocument
    from pbpk_domain.campaign.round_build import ScenarioBuildError, build_stage_snapshot
    from pbpk_domain.cpf import CPF

    cpf = CPF.model_validate_json(cpf_text)
    map_doc = MapDocument.model_validate_json(map_text)
    try:
        stage = build_stage_snapshot(cpf, list(map_doc.scenarios), stage=ctx.stage, seed=ctx.seed)
    except ScenarioBuildError as exc:
        return _echo(str(exc))

    out = _local_path(ctx.cpf_uri).parent / "snapshots" / f"{ctx.campaign_id}-{ctx.stage}-r{ctx.round_index}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    stage.snapshot.dump(out)
    for note in stage.notes:
        activity.logger.info("build_round_snapshot %s %s: %s", ctx.campaign_id, ctx.stage, note)
    activity.logger.info(
        "build_round_snapshot %s %s round %d: built %d simulation(s) fit=%s",
        ctx.campaign_id, ctx.stage, ctx.round_index, len(stage.simulations), needs_fit,
    )
    return RoundBuild(
        snapshot_uri=out.as_uri(), snapshot_sha256=stage.snapshot.sha256(), needs_fit=needs_fit, fit_request=None
    )


@activity.defn(name="run_round")
def run_round(run: RoundRun) -> RoundRunResult:
    """Apply the fit (parameter transfer, new CPF version) when one ran, then simulate the INTERNAL
    studies for evaluation. Engine and persistence wiring lands with T-09/T-05; for now it echoes the CPF."""
    ctx = run.context
    return RoundRunResult(results_uri=f"{ctx.cpf_uri}#results-r{ctx.round_index}", cpf_uri=ctx.cpf_uri, cpf_sha256=ctx.cpf_sha256)


@activity.defn(name="evaluate_round")
def evaluate_round(ctx: RoundContext, run_result: RoundRunResult) -> RoundEvaluation:
    """Reduce the round's simulated profiles to PK and judge them against the tier gate.

    Reads the MAP (tier + each study's fitting/validation role), the run's normalized profile bundle
    (``results_uri`` -> ``{"profiles": {study_id: {"times_min", "concentrations"}}}``, written by `run_round`
    once the engine is wired) and the observed PK (``ctx.observed_uri`` -> ``{study_id: {"auc", "cmax"}}``),
    then calls `pbpk_domain.campaign.evaluate.assess_round`. When the MAP, results or observed PK are not yet
    available, no gate can pass, so the round proceeds to diagnostics rather than falsely passing; the reason
    is recorded in the findings."""

    def _cannot(reason: str) -> RoundEvaluation:
        return RoundEvaluation(gate_passed=False, acceptable=False, metrics={}, findings=[reason])

    map_text = _load_local_text(ctx.map_uri) if ctx.map_uri else None
    if map_text is None:
        return _cannot("evaluation: MAP not locally loadable (object-store I/O pending)")
    profiles_doc = _load_local_json(run_result.results_uri)
    if not profiles_doc or "profiles" not in profiles_doc:
        return _cannot("evaluation: no simulated profile bundle from the run yet (run_round/engine pending)")

    from pbpk_domain.campaign.evaluate import ObservedPK, SimulatedProfile, assess_round
    from pbpk_domain.campaign.map import MapDocument

    map_doc = MapDocument.model_validate_json(map_text)
    role_of = {s.study_id: ("fitting" if s.assignment == "INTERNAL" else "validation") for s in map_doc.studies}

    simulated = [
        SimulatedProfile(
            study_id=study_id, role=role_of.get(study_id, "validation"),
            times=prof.get("times_min", []), concentrations=prof.get("concentrations", []),
        )
        for study_id, prof in profiles_doc["profiles"].items()
    ]
    observed_doc = _load_local_json(ctx.observed_uri) if ctx.observed_uri else {}
    observed = {
        study_id: ObservedPK(auc=pk.get("auc"), cmax=pk.get("cmax"))
        for study_id, pk in (observed_doc or {}).items()
    }

    assessment = assess_round(simulated, observed, model_risk=map_doc.model_risk)
    activity.logger.info(
        "evaluate_round %s %s round %d: gate=%s studies=%d",
        ctx.campaign_id, ctx.stage, ctx.round_index, assessment.gate_passed, len(assessment.studies),
    )
    return RoundEvaluation(
        gate_passed=assessment.gate_passed, acceptable=assessment.gate_passed,
        metrics=assessment.metrics, findings=list(assessment.findings),
    )


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
async def record_round(record: RoundRecord) -> None:
    """Persist the round as an append-only, audited record (CPF before/after, chosen action, metrics),
    getting-or-creating the campaign and stage rows. Without a database the round is only logged."""
    store = _campaign_store()
    if store is None:
        ctx = record.context
        activity.logger.info(
            "record_round %s %s round %d gate=%s action=%s",
            ctx.campaign_id, ctx.stage, ctx.round_index, record.evaluation.gate_passed,
            record.choice.action_id if record.choice else None,
        )
        return
    await store.record_round(record)


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
