"""Campaign orchestration for the MS-01 stage pipeline (task T-13).

`ModelingCampaignWorkflow` drives a compound from readiness to a signed model: S0 readiness, then a MAP
signature gate, then one `StageLoopWorkflow` child per stage (S1…S5), then a final CPF-acceptance gate.
`StageLoopWorkflow` runs the MS-01 round loop for one stage — build a snapshot from the CPF, fit (a
`FitRoundWorkflow` child) or simulate, evaluate the tier gate, and on failure diagnose, choose the next
permitted action and apply it — bounded by the stage's time budget and a maximum number of rounds, pausing
for a human decision when it must escalate. A fit is judged in its own round (the round re-simulates the fitted
CPF before evaluating). S4/S5 are validation stages: one round from the final CPF, judged, never fitted. A
stage the MAP gives nothing to simulate is SKIPPED with its documented reason (`plan_stage`).

Durability: each stage is a child workflow (bounding history) and the campaign can resume from persisted
rows via `resume_campaign`; a worker restart replays from Temporal history, so no round is lost or repeated.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
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
        EngineInput,
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
        StagePlan,
        StageRequest,
        fit_signals,
    )

ACT_RETRY = RetryPolicy(maximum_attempts=3)
# Engine errors are deterministic for a given input; only infrastructure failures are retried.
ENGINE_RETRY = RetryPolicy(maximum_attempts=2, non_retryable_error_types=["InputIntegrityError", "EngineError", "EngineTimeout"])
ROUND_ENGINE_QUEUE = "engine-s"  # one built snapshot, a few small simulations
_MIN = timedelta(minutes=1)
_VALIDATION_STAGES = ("S4", "S5")
_VALIDATION_FAILURE = {"S4": "internal_validation_failed", "S5": "external_validation_failed"}


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
        if request.stage in _VALIDATION_STAGES:
            return await self._validate(request)
        started = workflow.now()
        cpf_uri, cpf_sha = request.cpf_uri, request.cpf_sha256
        best_cpf_uri, best_cpf_sha = cpf_uri, cpf_sha
        actions_tried: list[str] = []
        pending_action: str | None = None
        pending_bounds: dict[str, list[float]] | None = None
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
                pending_bounds_override=pending_bounds,
                deadline_seconds=remaining, seed=request.seed,
                map_uri=request.map_uri, map_sha256=request.map_sha256,
                observed_uri=request.observed_uri, observed_sha256=request.observed_sha256,
                system_uri=request.system_uri, system_sha256=request.system_sha256,
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
                pending_bounds = None
                continue

            actions_tried.append(choice.action_id)
            pending_action = choice.action_id
            pending_bounds = choice.bounds_override  # strategist's bounds for this fit, applied next round

        return StageOutcome(
            stage=request.stage, status="ESCALATED", rounds_run=rounds_run,
            cpf_uri=best_cpf_uri, cpf_sha256=best_cpf_sha,
            findings=["maximum rounds reached without passing the gate"], escalation_reason="rounds_exhausted",
        )

    async def _validate(self, request: StageRequest) -> StageOutcome:
        """S4/S5 (MS-01 §4): simulate the final CPF once and judge it; never fit. A failure waits for the
        modeler's §6.6 decision — record a limitation and continue (ACCEPTED), or stop (ABORTED)."""
        ctx = RoundContext(
            campaign_id=request.campaign_id, tenant_id=request.tenant_id, stage=request.stage, round_index=1,
            cpf_uri=request.cpf_uri, cpf_sha256=request.cpf_sha256, pending_action=None,
            deadline_seconds=float(request.budget_seconds), seed=request.seed,
            map_uri=request.map_uri, map_sha256=request.map_sha256,
            observed_uri=request.observed_uri, observed_sha256=request.observed_sha256,
            system_uri=request.system_uri, system_sha256=request.system_sha256,
        )
        _run_result, evaluation, _diagnosis, _choice = await self._run_round(ctx, float(request.budget_seconds), judge_only=True)
        if evaluation.gate_passed:
            return StageOutcome(stage=request.stage, status="PASSED", rounds_run=1, cpf_uri=request.cpf_uri,
                                cpf_sha256=request.cpf_sha256, findings=evaluation.findings)
        reason = _VALIDATION_FAILURE[request.stage]
        decision = await self._await_escalation(request)
        status = "ACCEPTED" if decision is not None and decision.action == "accept_best" else "ABORTED"
        return StageOutcome(stage=request.stage, status=status, rounds_run=1, cpf_uri=request.cpf_uri,
                            cpf_sha256=request.cpf_sha256, findings=evaluation.findings, escalation_reason=reason)

    async def _vpc(self, ctx: RoundContext, evaluation: RoundEvaluation, manifest: EngineManifest | None,
                   remaining: float) -> RoundEvaluation:
        """MS-01 VPC on a stage whose PK gate passed: one population job per study, then coverage ≥ 80 %."""
        if not evaluation.gate_passed or manifest is None:
            return evaluation
        jobs: list[EngineJob] = await workflow.execute_activity(
            "prepare_vpc_jobs", args=[ctx, manifest], start_to_close_timeout=_MIN, retry_policy=ACT_RETRY,
            result_type=list[EngineJob],
        )
        if not jobs:
            return evaluation
        manifests = await asyncio.gather(*(
            workflow.execute_activity(
                "run_engine_job", job, task_queue=ROUND_ENGINE_QUEUE,
                start_to_close_timeout=timedelta(seconds=max(120.0, remaining)), heartbeat_timeout=_MIN * 2,
                retry_policy=ENGINE_RETRY, result_type=EngineManifest,
            ) for job in jobs
        ))
        return await workflow.execute_activity(
            "evaluate_vpc", args=[ctx, evaluation, list(manifests)], start_to_close_timeout=_MIN * 2,
            retry_policy=ACT_RETRY, result_type=RoundEvaluation,
        )

    async def _simulate(self, ctx: RoundContext, remaining: float) -> tuple[RoundBuild, EngineManifest | None]:
        build: RoundBuild = await workflow.execute_activity(
            "build_round_snapshot", ctx, start_to_close_timeout=_MIN * 5, retry_policy=ACT_RETRY, result_type=RoundBuild,
        )
        # Simulate the built snapshot on the engine (exporting pkml too on a fit round, via prepare_round_job).
        # build_round_snapshot echoes the CPF (snapshot_uri == cpf_uri) when no scenario trains this stage;
        # there is then nothing to simulate, so the engine step is skipped and run_round reports no results
        # (evaluate cannot judge the gate) rather than a false pass.
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
        return build, manifest

    async def _run_round(
        self, ctx: RoundContext, remaining: float, *, judge_only: bool = False,
    ) -> tuple[RoundRunResult, RoundEvaluation, RoundDiagnosis, ActionChoice | None]:
        build, manifest = await self._simulate(ctx, remaining)

        # Fit round: take the per-simulation pkml the simulate step exported and run the fitting child. When the
        # engine produced no pkml (or there is no fit request) the fit is skipped; the round still simulates.
        fit_outcome: FitRoundOutcome | None = None
        if build.needs_fit and build.fit_request is not None and manifest is not None:
            pkml_inputs: list[EngineInput] = await workflow.execute_activity(
                "collect_pkml_inputs", manifest, start_to_close_timeout=_MIN, retry_policy=ACT_RETRY,
                result_type=list[EngineInput],
            )
            if pkml_inputs:
                fit_request = replace(build.fit_request, model_inputs=pkml_inputs)
                fit_outcome = await workflow.execute_child_workflow(
                    FitRoundWorkflow.run, fit_request, id=f"{ctx.campaign_id}-{ctx.stage}-r{ctx.round_index}-fit",
                )

        run_result: RoundRunResult = await workflow.execute_activity(
            "run_round", RoundRun(context=ctx, build=build, fit_outcome=fit_outcome, manifest=manifest),
            start_to_close_timeout=_MIN * 5, retry_policy=ACT_RETRY, result_type=RoundRunResult,
        )
        judged, judged_manifest = ctx, manifest
        if run_result.cpf_uri != ctx.cpf_uri:
            # The fit changed the CPF: judge the fitted model in this round, not the pre-fit simulation.
            judged = replace(ctx, cpf_uri=run_result.cpf_uri, cpf_sha256=run_result.cpf_sha256,
                             pending_action=None, pending_bounds_override=None, phase="postfit",
                             fit_signals=fit_signals(fit_outcome))
            post_build, post_manifest = await self._simulate(judged, remaining)
            judged_manifest = post_manifest
            run_result = await workflow.execute_activity(
                "run_round", RoundRun(context=judged, build=post_build, fit_outcome=None, manifest=post_manifest),
                start_to_close_timeout=_MIN * 5, retry_policy=ACT_RETRY, result_type=RoundRunResult,
            )
        evaluation: RoundEvaluation = await workflow.execute_activity(
            "evaluate_round", args=[judged, run_result], start_to_close_timeout=_MIN * 10, retry_policy=ACT_RETRY,
            result_type=RoundEvaluation,
        )
        diagnosis = RoundDiagnosis()
        choice: ActionChoice | None = None
        if evaluation.gate_passed:
            evaluation = await self._vpc(judged, evaluation, judged_manifest, remaining)
            if not evaluation.gate_passed:
                # PK agrees but the population does not cover the data: no fit action addresses variability.
                diagnosis = RoundDiagnosis(escalate=True, escalation_reason="vpc_coverage_below_80",
                                           evidence=[f for f in evaluation.findings if "VPC" in f])
        if not evaluation.gate_passed and not judge_only and not diagnosis.escalate:
            diagnosis = await workflow.execute_activity(
                "diagnose_round", args=[judged, evaluation], start_to_close_timeout=_MIN * 2, retry_policy=ACT_RETRY,
                result_type=RoundDiagnosis,
            )
            if not diagnosis.escalate:
                choice = await workflow.execute_activity(
                    "choose_action", args=[judged, diagnosis], start_to_close_timeout=_MIN * 2, retry_policy=ACT_RETRY,
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
            if stage in ("S6", "S7"):
                # S6 prediction and S7 package run on the single-node runner (local_runner); their Temporal wiring
                # (signature gate, sensitivity/uncertainty jobs, reproduction) is not built yet — say so, never
                # run them as a fitting loop.
                stage_outcomes.append(StageOutcome(
                    stage=stage, status="SKIPPED", rounds_run=0, cpf_uri=cpf_uri, cpf_sha256=cpf_sha,
                    findings=[f"{stage} is not wired in the Temporal workflow yet; run it with the single-node runner"],
                ))
                continue
            stage_req = StageRequest(
                campaign_id=request.campaign_id, tenant_id=request.tenant_id, stage=stage,
                cpf_uri=cpf_uri, cpf_sha256=cpf_sha, budget_seconds=_stage_budget(request, stage),
                map_uri=request.map_uri, map_sha256=request.map_sha256,
                observed_uri=request.observed_uri, observed_sha256=request.observed_sha256,
                system_uri=request.system_uri, system_sha256=request.system_sha256,
                max_rounds=request.max_rounds_per_stage, seed=request.seed,
                signature_timeout_days=request.signature_timeout_days,
            )
            plan: StagePlan = await workflow.execute_activity(
                "plan_stage", stage_req, start_to_close_timeout=_MIN, retry_policy=ACT_RETRY, result_type=StagePlan,
            )
            if plan.skip_reason:
                # Nothing to simulate here: a documented limitation (MS-01 §6.2 / §6.7, §3.3 rule 2), not a failure.
                stage_outcomes.append(StageOutcome(stage=stage, status="SKIPPED", rounds_run=0, cpf_uri=cpf_uri,
                                                   cpf_sha256=cpf_sha, findings=[plan.skip_reason, *plan.notes]))
                continue
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
