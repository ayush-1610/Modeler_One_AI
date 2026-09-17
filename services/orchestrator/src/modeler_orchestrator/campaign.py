"""Campaign orchestration for the MS-01 stage pipeline (task T-13).

`ModelingCampaignWorkflow` drives a compound from readiness to a signed model: S0 readiness, then a MAP
signature gate, then one `StageLoopWorkflow` child per stage (S1…S5), then a final CPF-acceptance gate.
`StageLoopWorkflow` runs the MS-01 round loop for one stage — build a snapshot from the CPF, fit (a
`FitRoundWorkflow` child) or simulate, evaluate the tier gate, and on failure diagnose, choose the next
permitted action and apply it — bounded by the stage's time budget and a maximum number of rounds, pausing
for a human decision when it must escalate.

Durability: each stage is a child workflow (bounding history) and the campaign can resume from persisted
rows via `resume_campaign`; a worker restart replays from Temporal history, so no round is lost or repeated.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from modeler_orchestrator.fitting import FitRoundWorkflow

with workflow.unsafe.imports_passed_through():
    from modeler_contracts.runs import (
        ActionChoice,
        CampaignOutcome,
        CampaignRequest,
        DeviationRecord,
        EngineJob,
        EngineManifest,
        EscalationDecision,
        FitRoundOutcome,
        ResumeState,
        ReviewDecision,
        ReviewRequest,
        RoundBuild,
        RoundContext,
        RoundDiagnosis,
        RoundEvaluation,
        RoundRecord,
        RoundRun,
        RoundRunResult,
        S0Readiness,
        StageOutcome,
        StageRequest,
    )

ACT_RETRY = RetryPolicy(maximum_attempts=3)
# Engine errors are deterministic for a given input; only infrastructure failures are retried.
ENGINE_RETRY = RetryPolicy(maximum_attempts=2, non_retryable_error_types=["InputIntegrityError", "EngineError", "EngineTimeout"])
ROUND_ENGINE_QUEUE = "engine-s"  # one built snapshot, a few small simulations
_MIN = timedelta(minutes=1)


def _stage_budget(request: CampaignRequest, stage: str) -> int:
    # Default 30 min per stage when the MAP did not set one; S0 needs no engine time.
    return request.stage_budgets_seconds.get(stage, 0 if stage == "S0" else 1800)


@workflow.defn
class StageLoopWorkflow:
    """One MS-01 stage: the round loop with gate, diagnostics, escalation and a time budget."""

    def __init__(self) -> None:
        self._escalation: EscalationDecision | None = None
        self._deviations: list[DeviationRecord] = []

    @workflow.signal
    def escalation_decided(self, decision: EscalationDecision) -> None:
        self._escalation = decision

    @workflow.signal
    def deviation_recorded(self, deviation: DeviationRecord) -> None:
        self._deviations.append(deviation)

    @workflow.query
    def deviations(self) -> list[DeviationRecord]:
        return self._deviations

    @workflow.run
    async def run(self, request: StageRequest) -> StageOutcome:
        started = workflow.now()
        cpf_uri, cpf_sha = request.cpf_uri, request.cpf_sha256
        best_cpf_uri, best_cpf_sha = cpf_uri, cpf_sha
        actions_tried: list[str] = []
        pending_action: str | None = None
        rounds_run = 0

        for round_index in range(1, request.max_rounds + 1):
            elapsed = (workflow.now() - started).total_seconds()
            remaining = request.budget_seconds - elapsed
            if remaining <= 0:
                return StageOutcome(
                    stage=request.stage, status="ESCALATED", rounds_run=rounds_run,
                    cpf_uri=best_cpf_uri, cpf_sha256=best_cpf_sha,
                    findings=["stage time budget exhausted"], escalation_reason="budget_exhausted",
                )

            ctx = RoundContext(
                campaign_id=request.campaign_id, tenant_id=request.tenant_id, stage=request.stage,
                round_index=round_index, cpf_uri=cpf_uri, cpf_sha256=cpf_sha,
                pending_action=pending_action, actions_tried=list(actions_tried),
                deadline_seconds=remaining, seed=request.seed,
                map_uri=request.map_uri, map_sha256=request.map_sha256,
                observed_uri=request.observed_uri, observed_sha256=request.observed_sha256,
            )
            rounds_run = round_index
            run_result, evaluation, diagnosis, choice = await self._run_round(ctx, remaining)
            cpf_uri, cpf_sha = run_result.cpf_uri, run_result.cpf_sha256
            best_cpf_uri, best_cpf_sha = cpf_uri, cpf_sha

            if evaluation.gate_passed:
                return StageOutcome(
                    stage=request.stage, status="PASSED", rounds_run=rounds_run,
                    cpf_uri=cpf_uri, cpf_sha256=cpf_sha, findings=evaluation.findings,
                )

            must_escalate = diagnosis.escalate or choice is None or choice.action_id is None
            if must_escalate:
                reason = diagnosis.escalation_reason or "no_permitted_action"
                decision = await self._await_escalation(request)
                if decision is None or decision.action == "abort":
                    return StageOutcome(
                        stage=request.stage, status="ABORTED", rounds_run=rounds_run,
                        cpf_uri=best_cpf_uri, cpf_sha256=best_cpf_sha,
                        findings=evaluation.findings, escalation_reason=reason,
                    )
                if decision.action == "accept_best":
                    return StageOutcome(
                        stage=request.stage, status="ACCEPTED", rounds_run=rounds_run,
                        cpf_uri=best_cpf_uri, cpf_sha256=best_cpf_sha,
                        findings=evaluation.findings, escalation_reason=reason,
                    )
                # "retry": clear the decision and continue without a new action.
                pending_action = None
                continue

            actions_tried.append(choice.action_id)
            pending_action = choice.action_id

        return StageOutcome(
            stage=request.stage, status="ESCALATED", rounds_run=rounds_run,
            cpf_uri=best_cpf_uri, cpf_sha256=best_cpf_sha,
            findings=["maximum rounds reached without passing the gate"], escalation_reason="rounds_exhausted",
        )

    async def _run_round(
        self, ctx: RoundContext, remaining: float
    ) -> tuple[RoundRunResult, RoundEvaluation, RoundDiagnosis, ActionChoice | None]:
        build: RoundBuild = await workflow.execute_activity(
            "build_round_snapshot", ctx, start_to_close_timeout=_MIN * 5, retry_policy=ACT_RETRY, result_type=RoundBuild,
        )
        fit_outcome: FitRoundOutcome | None = None
        if build.needs_fit and build.fit_request is not None:
            fit_outcome = await workflow.execute_child_workflow(
                FitRoundWorkflow.run, build.fit_request, id=f"{ctx.campaign_id}-{ctx.stage}-r{ctx.round_index}-fit",
            )

        # Simulate the built snapshot on the engine. build_round_snapshot echoes the CPF (snapshot_uri ==
        # cpf_uri) when no scenario trains this stage; there is then nothing to simulate, so the engine step
        # is skipped and run_round reports no results (evaluate cannot judge the gate) rather than a false pass.
        manifest: EngineManifest | None = None
        if build.snapshot_uri != ctx.cpf_uri:
            job: EngineJob = await workflow.execute_activity(
                "prepare_round_job", args=[ctx, build], start_to_close_timeout=_MIN, retry_policy=ACT_RETRY, result_type=EngineJob,
            )
            manifest = await workflow.execute_activity(
                "run_engine_job", job, task_queue=ROUND_ENGINE_QUEUE,
                start_to_close_timeout=timedelta(seconds=max(60.0, remaining)), heartbeat_timeout=_MIN * 2,
                retry_policy=ENGINE_RETRY, result_type=EngineManifest,
            )

        run_result: RoundRunResult = await workflow.execute_activity(
            "run_round", RoundRun(context=ctx, build=build, fit_outcome=fit_outcome, manifest=manifest),
            start_to_close_timeout=_MIN * 5, retry_policy=ACT_RETRY, result_type=RoundRunResult,
        )
        evaluation: RoundEvaluation = await workflow.execute_activity(
            "evaluate_round", args=[ctx, run_result], start_to_close_timeout=_MIN * 10, retry_policy=ACT_RETRY,
            result_type=RoundEvaluation,
        )
        diagnosis = RoundDiagnosis()
        choice: ActionChoice | None = None
        if not evaluation.gate_passed:
            diagnosis = await workflow.execute_activity(
                "diagnose_round", args=[ctx, evaluation], start_to_close_timeout=_MIN * 2, retry_policy=ACT_RETRY,
                result_type=RoundDiagnosis,
            )
            if not diagnosis.escalate:
                choice = await workflow.execute_activity(
                    "choose_action", args=[ctx, diagnosis], start_to_close_timeout=_MIN * 2, retry_policy=ACT_RETRY,
                    result_type=ActionChoice,
                )
        await workflow.execute_activity(
            "record_round",
            RoundRecord(context=ctx, run_result=run_result, evaluation=evaluation, diagnosis=diagnosis, choice=choice),
            start_to_close_timeout=_MIN * 2, retry_policy=ACT_RETRY,
        )
        return run_result, evaluation, diagnosis, choice

    async def _await_escalation(self, request: StageRequest) -> EscalationDecision | None:
        # Wait for a decision, then consume it (set None) so the next escalation waits afresh. The pending
        # value is not cleared before waiting, so a decision that arrived while the round was still running
        # is honoured rather than lost.
        try:
            await workflow.wait_condition(
                lambda: self._escalation is not None, timeout=timedelta(days=request.signature_timeout_days)
            )
        except TimeoutError:
            return None
        decision = self._escalation
        self._escalation = None
        return decision


@workflow.defn
class ModelingCampaignWorkflow:
    """Whole campaign: S0 readiness, MAP signature, the fitting/validation stages, final CPF acceptance."""

    def __init__(self) -> None:
        self._map_decision: ReviewDecision | None = None
        self._final_decision: ReviewDecision | None = None

    @workflow.signal
    def map_signed(self, decision: ReviewDecision) -> None:
        self._map_decision = decision

    @workflow.signal
    def accept_final_cpf(self, decision: ReviewDecision) -> None:
        self._final_decision = decision

    @workflow.run
    async def run(self, request: CampaignRequest) -> CampaignOutcome:
        resume: ResumeState = await workflow.execute_activity(
            "resume_campaign", request, start_to_close_timeout=_MIN, retry_policy=ACT_RETRY, result_type=ResumeState,
        )
        cpf_uri = resume.cpf_uri or request.cpf_uri
        cpf_sha = resume.cpf_sha256 or request.cpf_sha256
        completed = _stages_through(request.stages, resume.last_completed_stage)
        stage_outcomes: list[StageOutcome] = []

        # S0 readiness (no engine) + MAP signature gate.
        if "S0" in request.stages and "S0" not in completed:
            readiness: S0Readiness = await workflow.execute_activity(
                "plan_campaign", request, start_to_close_timeout=_MIN * 5, retry_policy=ACT_RETRY, result_type=S0Readiness,
            )
            if not readiness.ready:
                return CampaignOutcome(
                    campaign_id=request.campaign_id, status="ESCALATED", stages=stage_outcomes,
                    final_cpf_uri=cpf_uri, final_cpf_sha256=cpf_sha, reason="S0 readiness failed: " + "; ".join(readiness.findings),
                )
            approved = await self._await_signature(
                "map_approval", request.map_id, cpf_sha, "MAP approval", request, lambda: self._map_decision
            )
            if not approved:
                return CampaignOutcome(
                    campaign_id=request.campaign_id, status="REJECTED", stages=stage_outcomes,
                    final_cpf_uri=cpf_uri, final_cpf_sha256=cpf_sha, reason="MAP not signed",
                )
            stage_outcomes.append(StageOutcome(stage="S0", status="PASSED", rounds_run=0, cpf_uri=cpf_uri, cpf_sha256=cpf_sha))

        # Fitting and validation stages, each a child workflow, CPF carried forward.
        for stage in request.stages:
            if stage == "S0" or stage in completed:
                continue
            stage_req = StageRequest(
                campaign_id=request.campaign_id, tenant_id=request.tenant_id, stage=stage,
                cpf_uri=cpf_uri, cpf_sha256=cpf_sha, budget_seconds=_stage_budget(request, stage),
                map_uri=request.map_uri, map_sha256=request.map_sha256,
                observed_uri=request.observed_uri, observed_sha256=request.observed_sha256,
                max_rounds=request.max_rounds_per_stage, seed=request.seed,
                signature_timeout_days=request.signature_timeout_days,
            )
            outcome: StageOutcome = await workflow.execute_child_workflow(
                StageLoopWorkflow.run, stage_req, id=f"{request.campaign_id}-{stage}",
            )
            stage_outcomes.append(outcome)
            cpf_uri, cpf_sha = outcome.cpf_uri, outcome.cpf_sha256
            if outcome.status in ("ESCALATED", "ABORTED", "FAILED"):
                return CampaignOutcome(
                    campaign_id=request.campaign_id, status="ESCALATED", stages=stage_outcomes,
                    final_cpf_uri=cpf_uri, final_cpf_sha256=cpf_sha,
                    reason=f"stage {stage} {outcome.status}: {outcome.escalation_reason or ''}".strip(),
                )

        # Final CPF acceptance signature.
        approved = await self._await_signature(
            "final_cpf", request.compound, cpf_sha, "final CPF acceptance", request, lambda: self._final_decision
        )
        if not approved:
            return CampaignOutcome(
                campaign_id=request.campaign_id, status="REJECTED", stages=stage_outcomes,
                final_cpf_uri=cpf_uri, final_cpf_sha256=cpf_sha, reason="final CPF not accepted",
            )
        return CampaignOutcome(
            campaign_id=request.campaign_id, status="COMPLETED", stages=stage_outcomes,
            final_cpf_uri=cpf_uri, final_cpf_sha256=cpf_sha,
        )

    async def _await_signature(self, record_type, record_id, record_sha, meaning, request, getter) -> bool:
        await workflow.execute_activity(
            "notify_reviewers",
            ReviewRequest(record_type=record_type, record_id=record_id, record_sha256=record_sha, required_meaning=meaning),
            start_to_close_timeout=_MIN, retry_policy=ACT_RETRY,
        )
        try:
            await workflow.wait_condition(lambda: getter() is not None, timeout=timedelta(days=request.signature_timeout_days))
        except TimeoutError:
            return False
        decision = getter()
        return decision is not None and decision.approved


def _stages_through(stages: list[str], last_completed: str | None) -> set[str]:
    """Every stage up to and including `last_completed` (for idempotent resume)."""
    if last_completed is None or last_completed not in stages:
        return set()
    return set(stages[: stages.index(last_completed) + 1])


__all__ = ["ModelingCampaignWorkflow", "StageLoopWorkflow"]
