"""Temporal test-server tests for the campaign state machine (T-13).

All activities are mocked so the tests exercise workflow orchestration only: the stage round loop and its
gate, escalation pause/resume, the time-budget deadline, the MAP and final-CPF signature gates, and
idempotent resume. Uses the time-skipping test environment, so day-long signature waits resolve instantly.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from modeler_contracts.runs import (
    ActionChoice,
    CampaignRequest,
    EscalationDecision,
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
    StagePlan,
    StageRequest,
)
from modeler_orchestrator.campaign import ModelingCampaignWorkflow, StageLoopWorkflow

TASK_QUEUE = "test-campaign"


def mock_activities(*, evaluate_gate=False, diagnose_actions=None, diagnose_escalate=None, s0_ready=True,
                    resume_last_stage=None, skip_stages=(), fit_changes_cpf=False, calls=None):
    """A full set of async mock activities with configurable evaluate/diagnose/plan/resume behaviour.

    ``skip_stages``: stages plan_stage reports as having nothing to simulate. ``fit_changes_cpf``: run_round on
    a fit round returns a new CPF (as a real fit does). ``calls``: a list the mocks append (activity, stage,
    phase) to, so a test can see what ran."""
    log = calls if calls is not None else []

    @activity.defn(name="plan_stage")
    async def plan_stage(request: StageRequest) -> StagePlan:
        kind = "validate" if request.stage in ("S4", "S5") else "fit"
        if request.stage in skip_stages:
            return StagePlan(stage=request.stage, kind=kind, skip_reason=f"nothing to simulate at {request.stage}")
        return StagePlan(stage=request.stage, kind=kind, studies=["s"])

    @activity.defn(name="resume_campaign")
    async def resume_campaign(request: CampaignRequest) -> ResumeState:
        return ResumeState(last_completed_stage=resume_last_stage, cpf_uri=request.cpf_uri, cpf_sha256=request.cpf_sha256)

    @activity.defn(name="plan_campaign")
    async def plan_campaign(request: CampaignRequest) -> S0Readiness:
        return S0Readiness(ready=s0_ready, findings=[] if s0_ready else ["missing phys.mw"])

    @activity.defn(name="notify_reviewers")
    async def notify_reviewers(request: ReviewRequest) -> None:
        return None

    @activity.defn(name="build_round_snapshot")
    async def build_round_snapshot(ctx: RoundContext) -> RoundBuild:
        return RoundBuild(snapshot_uri=ctx.cpf_uri, snapshot_sha256=ctx.cpf_sha256, needs_fit=False, fit_request=None)

    @activity.defn(name="run_round")
    async def run_round(run: RoundRun) -> RoundRunResult:
        ctx = run.context
        log.append(("run_round", ctx.stage, ctx.phase))
        if fit_changes_cpf and ctx.pending_action and ctx.pending_action.startswith("fit"):
            return RoundRunResult(results_uri="r", cpf_uri=f"{ctx.cpf_uri}.fitted", cpf_sha256="f" * 64)
        return RoundRunResult(results_uri="r", cpf_uri=ctx.cpf_uri, cpf_sha256=f"{ctx.round_index:064d}")

    @activity.defn(name="evaluate_round")
    async def evaluate_round(ctx: RoundContext, run_result: RoundRunResult) -> RoundEvaluation:
        log.append(("evaluate_round", ctx.stage, ctx.phase))
        passed = evaluate_gate(ctx) if callable(evaluate_gate) else bool(evaluate_gate)
        return RoundEvaluation(gate_passed=passed, acceptable=passed, metrics={}, findings=[] if passed else ["off"])

    @activity.defn(name="diagnose_round")
    async def diagnose_round(ctx: RoundContext, evaluation: RoundEvaluation) -> RoundDiagnosis:
        log.append(("diagnose_round", ctx.stage, ctx.phase))
        actions = list(diagnose_actions or [])
        escalate = diagnose_escalate if diagnose_escalate is not None else not actions
        return RoundDiagnosis(evidence=["e"], permitted_actions=actions, escalate=escalate,
                              escalation_reason="no action" if escalate else None)

    @activity.defn(name="choose_action")
    async def choose_action(ctx: RoundContext, diagnosis: RoundDiagnosis) -> ActionChoice:
        for a in diagnosis.permitted_actions:
            if a not in ctx.actions_tried:
                return ActionChoice(action_id=a, rationale="fallback")
        return ActionChoice(action_id=None, rationale="none left")

    @activity.defn(name="record_round")
    async def record_round(record: RoundRecord) -> None:
        return None

    return [resume_campaign, plan_campaign, plan_stage, notify_reviewers, build_round_snapshot, run_round,
            evaluate_round, diagnose_round, choose_action, record_round]


@asynccontextmanager
async def running(activities):
    """Start a time-skipping environment with a worker for the campaign workflows; yield the environment."""
    async with await WorkflowEnvironment.start_time_skipping() as env:
        worker = Worker(
            env.client, task_queue=TASK_QUEUE,
            workflows=[ModelingCampaignWorkflow, StageLoopWorkflow], activities=activities,
        )
        async with worker:
            yield env


def _stage_request(**kw) -> StageRequest:
    base = dict(campaign_id="c1", tenant_id="t1", stage="S1", cpf_uri="file:///tmp/cpf.json",
                cpf_sha256="a" * 64, budget_seconds=1800, max_rounds=4, seed=1, signature_timeout_days=14)
    base.update(kw)
    return StageRequest(**base)


def _campaign_request(**kw) -> CampaignRequest:
    base = dict(campaign_id="camp1", tenant_id="t1", compound="Example-A", map_id="map1",
                cpf_uri="file:///tmp/cpf.json", cpf_sha256="a" * 64, stages=["S0", "S1", "S2"],
                stage_budgets_seconds={"S1": 1800, "S2": 1800}, max_rounds_per_stage=2, seed=1)
    base.update(kw)
    return CampaignRequest(**base)


def run(coro):
    return asyncio.run(coro)


def _sid() -> str:
    return f"s-{uuid.uuid4()}"


def _cid() -> str:
    return f"c-{uuid.uuid4()}"


# --- StageLoopWorkflow -----------------------------------------------------------------------------


def test_stage_passes_on_first_round():
    async def scenario():
        async with running(mock_activities(evaluate_gate=True)) as env:
            outcome = await env.client.execute_workflow(
                StageLoopWorkflow.run, _stage_request(), id=_sid(), task_queue=TASK_QUEUE
            )
            assert outcome.status == "PASSED"
            assert outcome.rounds_run == 1
    run(scenario())


def test_stage_escalates_when_rounds_exhausted():
    async def scenario():
        acts = mock_activities(evaluate_gate=False, diagnose_actions=["fit_a", "fit_b", "fit_c", "fit_d", "fit_e"])
        async with running(acts) as env:
            outcome = await env.client.execute_workflow(
                StageLoopWorkflow.run, _stage_request(max_rounds=4), id=_sid(), task_queue=TASK_QUEUE
            )
            assert outcome.status == "ESCALATED"
            assert outcome.escalation_reason == "rounds_exhausted"
            assert outcome.rounds_run == 4
    run(scenario())


def test_stage_deadline_exhausted_before_any_round():
    async def scenario():
        async with running(mock_activities(evaluate_gate=False)) as env:
            outcome = await env.client.execute_workflow(
                StageLoopWorkflow.run, _stage_request(budget_seconds=0), id=_sid(), task_queue=TASK_QUEUE
            )
            assert outcome.status == "ESCALATED"
            assert outcome.escalation_reason == "budget_exhausted"
    run(scenario())


def test_stage_escalation_abort():
    async def scenario():
        async with running(mock_activities(evaluate_gate=False, diagnose_actions=[])) as env:
            handle = await env.client.start_workflow(
                StageLoopWorkflow.run, _stage_request(), id=_sid(), task_queue=TASK_QUEUE
            )
            await handle.signal(StageLoopWorkflow.escalation_decided, EscalationDecision(action="abort"))
            outcome = await handle.result()
            assert outcome.status == "ABORTED"
    run(scenario())


def test_stage_escalation_accept_best():
    async def scenario():
        async with running(mock_activities(evaluate_gate=False, diagnose_actions=[])) as env:
            handle = await env.client.start_workflow(
                StageLoopWorkflow.run, _stage_request(), id=_sid(), task_queue=TASK_QUEUE
            )
            await handle.signal(StageLoopWorkflow.escalation_decided, EscalationDecision(action="accept_best"))
            outcome = await handle.result()
            assert outcome.status == "ACCEPTED"
    run(scenario())


def test_stage_escalation_retry_then_pass():
    async def scenario():
        # gate passes only from round 2; round 1 escalates (no actions) -> retry -> round 2 passes
        acts = mock_activities(evaluate_gate=lambda ctx: ctx.round_index >= 2, diagnose_actions=[])
        async with running(acts) as env:
            handle = await env.client.start_workflow(
                StageLoopWorkflow.run, _stage_request(), id=_sid(), task_queue=TASK_QUEUE
            )
            await handle.signal(StageLoopWorkflow.escalation_decided, EscalationDecision(action="retry"))
            outcome = await handle.result()
            assert outcome.status == "PASSED"
            assert outcome.rounds_run == 2
    run(scenario())


# --- ModelingCampaignWorkflow ----------------------------------------------------------------------


def test_campaign_happy_path_s0_to_s2():
    async def scenario():
        async with running(mock_activities(evaluate_gate=True)) as env:
            handle = await env.client.start_workflow(
                ModelingCampaignWorkflow.run, _campaign_request(), id=_cid(), task_queue=TASK_QUEUE
            )
            await handle.signal(ModelingCampaignWorkflow.map_signed, ReviewDecision(approved=True, signature_id="sig-map"))
            await handle.signal(ModelingCampaignWorkflow.accept_final_cpf, ReviewDecision(approved=True, signature_id="sig-final"))
            outcome = await handle.result()
            assert outcome.status == "COMPLETED"
            assert [s.stage for s in outcome.stages] == ["S0", "S1", "S2"]
            assert all(s.status == "PASSED" for s in outcome.stages)
    run(scenario())


def test_campaign_rejected_when_map_not_signed():
    async def scenario():
        async with running(mock_activities(evaluate_gate=True)) as env:
            handle = await env.client.start_workflow(
                ModelingCampaignWorkflow.run, _campaign_request(), id=_cid(), task_queue=TASK_QUEUE
            )
            await handle.signal(ModelingCampaignWorkflow.map_signed, ReviewDecision(approved=False))
            outcome = await handle.result()
            assert outcome.status == "REJECTED"
            assert outcome.reason == "MAP not signed"
    run(scenario())


def test_campaign_escalates_when_s0_not_ready():
    async def scenario():
        async with running(mock_activities(s0_ready=False)) as env:
            outcome = await env.client.execute_workflow(
                ModelingCampaignWorkflow.run, _campaign_request(), id=_cid(), task_queue=TASK_QUEUE
            )
            assert outcome.status == "ESCALATED"
            assert "S0 readiness failed" in outcome.reason
    run(scenario())


def test_campaign_escalates_when_a_stage_escalates():
    async def scenario():
        acts = mock_activities(evaluate_gate=False, diagnose_actions=["fit_a", "fit_b"])
        async with running(acts) as env:
            handle = await env.client.start_workflow(
                ModelingCampaignWorkflow.run, _campaign_request(max_rounds_per_stage=2), id=_cid(), task_queue=TASK_QUEUE
            )
            await handle.signal(ModelingCampaignWorkflow.map_signed, ReviewDecision(approved=True))
            outcome = await handle.result()
            assert outcome.status == "ESCALATED"
            assert "stage S1" in outcome.reason
    run(scenario())


def test_campaign_resume_skips_completed_stage():
    async def scenario():
        async with running(mock_activities(evaluate_gate=True, resume_last_stage="S1")) as env:
            handle = await env.client.start_workflow(
                ModelingCampaignWorkflow.run, _campaign_request(), id=_cid(), task_queue=TASK_QUEUE
            )
            await handle.signal(ModelingCampaignWorkflow.accept_final_cpf, ReviewDecision(approved=True))
            outcome = await handle.result()
            assert outcome.status == "COMPLETED"
            # S0 and S1 already completed -> only S2 runs this time
            assert [s.stage for s in outcome.stages] == ["S2"]
    run(scenario())


# --- MS-01 stage kinds: skip, validation, fit judged in its own round (R1/R2/R13) -----------------


def test_campaign_skips_a_stage_with_nothing_to_simulate_and_continues():
    async def scenario():
        acts = mock_activities(evaluate_gate=True, skip_stages=("S2",))
        async with running(acts) as env:
            handle = await env.client.start_workflow(
                ModelingCampaignWorkflow.run, _campaign_request(stages=["S0", "S1", "S2", "S4", "S5"]), id=_cid(),
                task_queue=TASK_QUEUE,
            )
            await handle.signal(ModelingCampaignWorkflow.map_signed, ReviewDecision(approved=True))
            await handle.signal(ModelingCampaignWorkflow.accept_final_cpf, ReviewDecision(approved=True))
            outcome = await handle.result()
            assert outcome.status == "COMPLETED"
            status = {s.stage: s.status for s in outcome.stages}
            assert status == {"S0": "PASSED", "S1": "PASSED", "S2": "SKIPPED", "S4": "PASSED", "S5": "PASSED"}
            s2 = next(s for s in outcome.stages if s.stage == "S2")
            assert s2.findings == ["nothing to simulate at S2"]  # the documented reason travels with it
    run(scenario())


def test_validation_stage_judges_once_and_never_diagnoses():
    async def scenario():
        calls: list = []
        async with running(mock_activities(evaluate_gate=False, diagnose_actions=["fit_a"], calls=calls)) as env:
            handle = await env.client.start_workflow(
                StageLoopWorkflow.run, _stage_request(stage="S5"), id=_sid(), task_queue=TASK_QUEUE
            )
            await handle.signal(StageLoopWorkflow.escalation_decided, EscalationDecision(action="accept_best"))
            outcome = await handle.result()
            assert outcome.status == "ACCEPTED" and outcome.rounds_run == 1
            assert outcome.escalation_reason == "external_validation_failed"
            assert not [c for c in calls if c[0] == "diagnose_round"]  # validation never diagnoses or fits
    run(scenario())


def test_a_fit_is_judged_on_the_fitted_model_in_its_own_round():
    """R13: the round's first simulation ran the pre-fit CPF; the gate must see the fitted one."""
    async def scenario():
        calls: list = []
        # the gate passes only on the re-simulated, fitted model
        acts = mock_activities(evaluate_gate=lambda ctx: ctx.phase == "postfit", diagnose_actions=["fit_a"],
                               fit_changes_cpf=True, calls=calls)
        async with running(acts) as env:
            outcome = await env.client.execute_workflow(
                StageLoopWorkflow.run, _stage_request(), id=_sid(), task_queue=TASK_QUEUE
            )
            assert outcome.status == "PASSED" and outcome.rounds_run == 2  # baseline, then the fit round passes
            assert outcome.cpf_uri.endswith(".fitted")
            assert ("evaluate_round", "S1", "postfit") in calls
    run(scenario())
