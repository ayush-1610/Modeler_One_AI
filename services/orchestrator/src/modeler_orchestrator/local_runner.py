"""Single-node headless campaign executor — the runner-first, no-Docker execution mode.

Runs the MS-01 stage pipeline (S0 readiness → S1…S5) in-process by calling the **same** campaign activity
functions the Temporal worker calls (`plan_stage`, `build_round_snapshot`, `prepare_round_job`,
`collect_pkml_inputs`, `run_round`, `evaluate_round`, `diagnose_round`, `choose_action`) and the same fit
planning/assessment (`plan_jobs`, `assess_round`), driving the engine through the same subprocess boundary
(`modeler_engine.runner.EngineRunner` + `LocalObjectStore`, i.e. `Rscript run_job.R`). The scientific work is
single-sourced with the Temporal path; only the loop control (`StageLoopWorkflow` / `ModelingCampaignWorkflow`)
is re-expressed here, without Temporal signals, timers or a cluster.

Stage kinds (MS-01 §4): S1–S3 are round loops — simulate, judge, diagnose, fit — and a fit is judged in the
round it happens (the round re-simulates from the fitted CPF before evaluating). S4/S5 simulate the final CPF
once and judge it, never fitting; S5 judges fasted and fed separately. A stage with no study to simulate is
SKIPPED with its documented reason rather than escalated.

Human gates (MS-01 §1): the MAP signature is collected in the UI before a campaign starts; final CPF
acceptance is a review-inbox action after the stages pass. On an escalation the runner **stops** the campaign
and records an escalation for the review inbox (paused, never silently continued) rather than blocking for days.

Persistence: progress is written as the campaign monitor view (``campaigns.json``) and escalations
(``escalations.json``) through ``FileWriteStore``, so the web app renders live progress; the Postgres §5 tables
implement the same ``WriteStore`` later.
"""

from __future__ import annotations

import json
import os
import shlex
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from urllib.parse import unquote, urlparse

from modeler_api.filestore import FileWriteStore, WriteStore
from modeler_contracts.runs import (
    CampaignOutcome,
    CampaignRequest,
    EngineJob,
    EngineManifest,
    RoundContext,
    RoundDiagnosis,
    RoundEvaluation,
    RoundRun,
    RoundRunResult,
    StageOutcome,
    StageRequest,
    fit_signals,
)
from modeler_orchestrator.campaign_activities import (
    build_round_snapshot,
    choose_action,
    collect_pkml_inputs,
    diagnose_round,
    evaluate_round,
    evaluate_vpc,
    plan_campaign,
    plan_stage,
    prepare_round_job,
    prepare_vpc_jobs,
    run_round,
)
from modeler_orchestrator.fitting_activities import assess_round as assess_fit_round
from modeler_orchestrator.fitting_activities import plan_jobs
from pbpk_domain.fitting import BudgetTooSmallError

# One callable dispatches an engine job to a manifest — the real EngineRunner.run in production, a stub in tests.
EngineRun = Callable[[EngineJob], EngineManifest]

STAGE_LABELS = {
    "S0": "Readiness", "S1": "IV disposition", "S2": "Oral fasted",
    "S3": "Formulation / fed", "S4": "Internal validation", "S5": "External validation",
    "S6": "Prediction", "S7": "Report & package",
}
# Stages that stop the campaign when a stage ends there.
_STOP_STATUSES = ("ESCALATED", "ABORTED", "FAILED")
# Why a validation stage escalates (MS-01 §4 S4, §6.6).
_VALIDATION_FAILURE = {"S4": "internal_validation_failed", "S5": "external_validation_failed"}
_DEFAULT_STAGE_BUDGET_S = 1800
# The decision options MS-01 §4 offers on any stage escalation (mirrors the escalations API / review inbox).
# Every one of them resumes or ends the stage, so every one is an approval and carries a Part 11 signature —
# matching `escalations.decision_options()`, which requires the "Approved" meaning for all three.
_ESCALATION_OPTIONS = [
    {"id": "retry", "label": "Retry the stage", "requiresSignature": True},
    {"id": "accept_best", "label": "Accept the best round", "requiresSignature": True},
    {"id": "abort", "label": "Abort the stage", "requiresSignature": True},
]
# A validation stage is deterministic — re-running it gives the same answer — so MS-01 §6.6 offers no retry:
# record the failure as a limitation (restricting the context of use) and continue, or stop. Moving the failing
# study to the internal set and refitting (§6.6 path 2) is a MAP deviation: revise the MAP and start again.
_VALIDATION_OPTIONS = [
    {"id": "accept_best", "label": "Record a limitation and continue (MS-01 §6.6)", "requiresSignature": True},
    {"id": "abort", "label": "Stop the campaign", "requiresSignature": True},
]
# MS-01 §4 S6 "runs only after S4 and S5 are signed" (decision D5: evaluation signatures are a human touchpoint).
_SIGNATURE_OPTIONS = [
    {"id": "approve", "label": "Sign the internal and external validation and continue to prediction and the report",
     "requiresSignature": True},
    {"id": "abort", "label": "Stop the campaign", "requiresSignature": True},
]
_GATED_STAGE = "S6"


def default_engine() -> EngineRun:
    """A real engine dispatcher: ``Rscript run_job.R`` over a ``file://`` object store, configured from env.

    On the server the engine env (PATH, LD_LIBRARY_PATH, DOTNET_ROOT, R_LIBS_USER, LC_ALL) is passed through
    to the subprocess by EngineRunner; ``MODELER_ENGINE_COMMAND`` points at the run_job.R for this host.
    """
    from modeler_engine.runner import EngineRunner, LocalObjectStore

    runner = EngineRunner(
        command=shlex.split(os.environ.get("MODELER_ENGINE_COMMAND", "Rscript run_job.R")),
        store=LocalObjectStore(),
        engine_id=os.environ.get("MODELER_ENGINE_ID", "local"),
        image_digest=os.environ.get("MODELER_IMAGE_DIGEST", "local"),
    )
    return runner.run


# Engine commands that are software fixtures, not PK-Sim (CLAUDE.md: their numbers are never simulation results).
_FIXTURE_ENGINES = ("stub_engine.py", "analytical_engine.py")
_PKSIM_ENGINES = ("run_job.R", "docker_engine.sh")


def engine_identity(engine: EngineRun | None = None) -> dict:
    """What a campaign's numbers come from, for the monitor: real PK-Sim, a software fixture, or an injected engine.

    Shown on every campaign so a run on the stub can never be read as a PBPK result."""
    if engine is not None:
        return {"kind": "injected", "command": getattr(engine, "__name__", type(engine).__name__)}
    command = os.environ.get("MODELER_ENGINE_COMMAND", "Rscript run_job.R")
    words = [os.path.basename(w) for w in shlex.split(command)]
    if any(w in _FIXTURE_ENGINES for w in words):
        kind = "software-fixture"
    elif any(w in _PKSIM_ENGINES for w in words):
        kind = "pksim"
    else:
        kind = "unknown"
    return {"kind": kind, "command": " ".join(words)}


def fit_workers(fit_request, n_jobs: int) -> int:
    """How many fit starts run at once: the planner's parallelism (cores ÷ simulations per start), never more than
    this machine's CPUs, overridable with MODELER_FIT_WORKERS (e.g. to spare memory on a laptop's Docker engine)."""
    override = os.environ.get("MODELER_FIT_WORKERS")
    if override:
        return max(1, min(int(override), n_jobs))
    per_start = max(1, int(getattr(fit_request, "simulations_per_evaluation", 1) or 1))
    planned = max(1, int(getattr(fit_request, "cores", 1) or 1) // per_start)
    return max(1, min(planned, os.cpu_count() or 1, n_jobs))


def _local_json(uri: str) -> dict | None:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return None
    path = Path(unquote(parsed.path))
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


@dataclass
class _RoundOutcome:
    run_result: RoundRunResult
    evaluation: RoundEvaluation
    diagnosis: RoundDiagnosis
    choice: object
    notes: list[str]
    fitted: bool = False  # the round applied fitted estimates and was judged on the re-simulated, fitted model
    snapshot_uri: str | None = None           # the snapshot the judged simulation ran
    outputs: list[dict] = field(default_factory=list)  # that engine run's outputs (name, uri, sha256)


def _gof_series(results_uri: str, observed_uri: str) -> list[dict]:
    """Best-effort goodness-of-fit series for the monitor: simulated profiles + any observed points."""
    profiles = (_local_json(results_uri) or {}).get("profiles") if results_uri else None
    if not profiles:
        return []
    observed = _local_json(observed_uri) if observed_uri else {}
    series: list[dict] = []
    for study_id, prof in profiles.items():
        times = prof.get("times_min", [])
        series.append({
            "name": f"Predicted ({study_id})", "kind": "simulated", "unit": prof.get("unit", ""),
            "time_h": [t / 60.0 for t in times], "concentration": list(prof.get("concentrations", [])),
        })
        obs_profile = ((observed or {}).get(study_id) or {}).get("profile")
        if obs_profile and obs_profile.get("times") and obs_profile.get("values"):
            factor = 60.0 if obs_profile.get("time_unit", "min") == "min" else 1.0
            series.append({
                "name": f"Observed ({study_id})", "kind": "observed", "unit": obs_profile.get("unit", ""),
                "time_h": [t / factor for t in obs_profile["times"]], "concentration": list(obs_profile["values"]),
            })
    return series


@dataclass
class CampaignArtifactWriter:
    """Projects campaign progress to the monitor read model (``campaigns.json``) and escalations, live."""

    store: WriteStore
    tenant_id: str
    campaign_id: str
    project: str
    compound: str
    question: str
    model_risk: str
    budget_seconds: int
    stages: list[str]
    resume: dict | None = None  # how to continue this campaign after a human decision (set on escalation)
    prediction: dict | None = None  # the S6 result (sensitivity ranking, prediction intervals)
    package: dict | None = None     # the S7 record (reproduction verdict, report files, exportable package)
    engine: dict | None = None      # what produced the numbers (`engine_identity`): PK-Sim or a software fixture
    _started: float = field(default_factory=time.monotonic)
    _rounds: dict[str, list[dict]] = field(default_factory=dict)
    _status: dict[str, str] = field(default_factory=dict)
    _gof: list[dict] = field(default_factory=list)
    _notes: dict[str, list[str]] = field(default_factory=dict)
    _gof_by_stage: dict[str, list[dict]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for stage in self.stages:
            self._rounds.setdefault(stage, [])
            self._status.setdefault(stage, "PENDING")

    @classmethod
    def from_campaign(cls, store: WriteStore, tenant_id: str, campaign: dict) -> CampaignArtifactWriter:
        """Rebuild a writer from a persisted monitor record, so resuming keeps the earlier stages and rounds."""
        stages = [s["stage"] for s in campaign.get("stages", [])] or list(STAGE_LABELS)
        writer = cls(
            store=store, tenant_id=tenant_id, campaign_id=campaign["id"], project=campaign.get("project", ""),
            compound=campaign.get("compound", ""), question=campaign.get("question", ""),
            model_risk=campaign.get("modelRisk", "medium"), budget_seconds=int(campaign.get("budgetSeconds", 3600)),
            stages=stages, resume=campaign.get("resume"),
        )
        for row in campaign.get("stages", []):
            writer._status[row["stage"]] = row.get("status", "PENDING")
            writer._rounds[row["stage"]] = list(row.get("rounds", []))
            writer._notes[row["stage"]] = list(row.get("notes", []))
        writer._gof = list(campaign.get("gof", []))
        writer._gof_by_stage = {k: list(v) for k, v in (campaign.get("gofByStage") or {}).items()}
        writer.prediction = campaign.get("prediction")
        writer.engine = campaign.get("engine")
        writer.package = campaign.get("package")
        writer._started = time.monotonic() - float(campaign.get("elapsedSeconds", 0))
        return writer

    def _elapsed(self) -> int:
        return int(time.monotonic() - self._started)

    def stage_status(self, stage: str, status: str) -> None:
        self._status[stage] = status

    def stage_notes(self, stage: str, notes: list[str]) -> None:
        """Record what the stage could not do or deferred (skip reasons, studies not simulated), once each."""
        kept = self._notes.setdefault(stage, [])
        for note in notes:
            if note and note not in kept:
                kept.append(note)

    def add_round(self, stage: str, round_index: int, action: str, evaluation: RoundEvaluation) -> None:
        auc = evaluation.metrics.get("AUC", {}).get("gmfe")
        cmax = evaluation.metrics.get("Cmax", {}).get("gmfe")
        verdict = "passed" if evaluation.gate_passed else "no pass"
        self._rounds[stage].append({
            "round": round_index, "action": action,
            "aucGmfe": round(auc, 3) if auc is not None else None,
            "cmaxGmfe": round(cmax, 3) if cmax is not None else None,
            "verdict": verdict,
            # per-study and per-group results, so validation can be shown fasted vs fed and study by study
            "studies": evaluation.metrics.get("studies", []),
            "groups": evaluation.metrics.get("groups", []),
            "vpc": evaluation.metrics.get("vpc", {}),  # per study: coverage and the 5/50/95 % band for the plot
            "findings": list(evaluation.findings),
        })

    def set_gof(self, series: list[dict], stage: str | None = None) -> None:
        """The latest goodness-of-fit series, and each stage's own, so validation plots are not overwritten."""
        if series:
            self._gof = series
            if stage:
                self._gof_by_stage[stage] = series

    def flush(self, *, current_stage: str, status: str) -> None:
        self.store.upsert_campaign(self.tenant_id, {
            "id": self.campaign_id, "project": self.project, "compound": self.compound,
            "question": self.question, "modelRisk": self.model_risk,
            "budgetSeconds": self.budget_seconds, "elapsedSeconds": self._elapsed(),
            "currentStage": current_stage, "status": status,
            "stages": [
                {"stage": s, "label": STAGE_LABELS.get(s, s), "status": self._status[s], "rounds": self._rounds[s],
                 "notes": self._notes.get(s, [])}
                for s in self.stages
            ],
            "gof": self._gof,
            "gofByStage": self._gof_by_stage,
            "prediction": self.prediction,
            "package": self.package,
            "engine": self.engine,
            "resume": self.resume,
        })

    def record_signature_request(self, stage: str) -> None:
        """The review-inbox item that holds the campaign until the S4/S5 evaluation is signed (MS-01 §4 S6)."""
        self.store.upsert_escalation(self.tenant_id, {
            "id": f"{self.campaign_id}-{stage}", "campaignId": self.campaign_id, "stage": stage,
            "reasonCode": "SIGNATURE_REQUIRED",
            "evidence": "Internal (S4) and external (S5) validation are complete. MS-01 requires them signed before "
                        "the model is used for prediction (S6) and the report and package are assembled (S7).",
            "options": _SIGNATURE_OPTIONS,
        })

    def record_escalation(self, stage: str, reason: str, findings: list[str]) -> None:
        evidence = "; ".join(findings) if findings else f"Stage {stage} escalated ({reason})."
        options = _VALIDATION_OPTIONS if stage in _VALIDATION_FAILURE else _ESCALATION_OPTIONS
        self.store.upsert_escalation(self.tenant_id, {
            "id": f"{self.campaign_id}-{stage}", "campaignId": self.campaign_id, "stage": stage,
            "reasonCode": (reason or "ESCALATED").upper(), "evidence": evidence, "options": options,
        })


@dataclass
class LocalExecutor:
    """Runs a whole campaign in-process against an injected engine dispatcher, writing live monitor artifacts."""

    engine: EngineRun
    writer: CampaignArtifactWriter | None = None
    approved_gates: set[str] = field(default_factory=set)  # signature gates already signed (resumed campaigns)
    _last: dict[str, dict] = field(default_factory=dict)   # stage -> its judged round (metrics, snapshot, outputs)

    def run(
        self, request: CampaignRequest, *,
        original: CampaignRequest | None = None, completed_before: list[str] | None = None,
    ) -> CampaignOutcome:
        """Run `request`'s stages. On a resumed campaign, `original` is the full request the campaign started
        from and `completed_before` the stages already finished, so the persisted resume state stays complete."""
        original = original or request
        completed = list(completed_before or [])
        cpf_uri, cpf_sha = request.cpf_uri, request.cpf_sha256
        outcomes: list[StageOutcome] = []

        # S0 readiness (no engine) — the MAP is already signed (a campaign only starts after that gate).
        if "S0" in request.stages:
            readiness = plan_campaign(request)
            if not readiness.ready:
                if self.writer:
                    self.writer.stage_status("S0", "ESCALATED")
                    self.writer.record_escalation("S0", "S0_not_ready", readiness.findings)
                    self.writer.flush(current_stage="S0", status="ESCALATED")
                return CampaignOutcome(
                    campaign_id=request.campaign_id, status="ESCALATED", stages=outcomes,
                    final_cpf_uri=cpf_uri, final_cpf_sha256=cpf_sha,
                    reason="S0 readiness failed: " + "; ".join(readiness.findings),
                )
            outcomes.append(StageOutcome(stage="S0", status="PASSED", rounds_run=0, cpf_uri=cpf_uri, cpf_sha256=cpf_sha))
            completed.append("S0")
            if self.writer:
                self.writer.stage_status("S0", "PASSED")
                self.writer.flush(current_stage="S0", status="RUNNING")

        for stage in request.stages:
            if stage == "S0":
                continue
            if stage == _GATED_STAGE and stage not in self.approved_gates:
                # Pause for the S4/S5 evaluation signature; a signed "approve" in the review inbox resumes here.
                if self.writer:
                    self.writer.resume = {"request": asdict(original), "cpf_uri": cpf_uri, "cpf_sha256": cpf_sha,
                                          "completed_stages": completed, "escalated_stage": stage}
                    self.writer.record_signature_request(stage)
                    self.writer.flush(current_stage=stage, status="AWAITING_SIGNATURE")
                return CampaignOutcome(
                    campaign_id=request.campaign_id, status="AWAITING_SIGNATURE", stages=outcomes,
                    final_cpf_uri=cpf_uri, final_cpf_sha256=cpf_sha,
                    reason="the internal and external validation await signature before prediction (MS-01 §4 S6)",
                )
            plan = plan_stage(StageRequest(
                campaign_id=request.campaign_id, tenant_id=request.tenant_id, stage=stage, cpf_uri=cpf_uri,
                cpf_sha256=cpf_sha, budget_seconds=0, map_uri=request.map_uri, map_sha256=request.map_sha256,
            ))
            if self.writer:
                self.writer.stage_notes(stage, plan.notes)
            if plan.skip_reason:
                # Nothing to simulate at this stage: a documented limitation, not a failure (MS-01 §6.2 / §6.7,
                # §3.3 rule 2). The CPF carries forward unchanged.
                skipped = StageOutcome(stage=stage, status="SKIPPED", rounds_run=0, cpf_uri=cpf_uri,
                                       cpf_sha256=cpf_sha, findings=[plan.skip_reason, *plan.notes])
                outcomes.append(skipped)
                completed.append(stage)
                if self.writer:
                    self.writer.stage_notes(stage, [plan.skip_reason])
                self._persist(request, skipped)
                if self.writer:
                    self.writer.stage_status(stage, "SKIPPED")
                    self.writer.flush(current_stage=stage, status="RUNNING")
                continue
            if self.writer:
                self.writer.stage_status(stage, "RUNNING")
                self.writer.flush(current_stage=stage, status="RUNNING")
            try:
                if plan.kind == "validate":
                    outcome = self._run_validation(request, stage, cpf_uri, cpf_sha)
                elif plan.kind == "predict":
                    outcome = self._run_prediction(request, cpf_uri, cpf_sha)
                elif plan.kind == "report":
                    outcome = self._run_package(request, cpf_uri, cpf_sha)
                else:
                    outcome = self._run_stage(request, stage, cpf_uri, cpf_sha)
            except Exception as exc:  # noqa: BLE001 - an engine or activity failure must surface, not hang
                # Without this the background thread dies silently and the campaign sits at RUNNING forever,
                # which looks like a hang to the user and hides the real error.
                outcome = StageOutcome(
                    stage=stage, status="FAILED", rounds_run=0, cpf_uri=cpf_uri, cpf_sha256=cpf_sha,
                    findings=[f"{type(exc).__name__}: {exc}"], escalation_reason="stage_failed",
                )
            outcomes.append(outcome)
            cpf_uri, cpf_sha = outcome.cpf_uri, outcome.cpf_sha256
            if outcome.status not in _STOP_STATUSES:
                completed.append(stage)
                self._persist(request, outcome)
            if self.writer:
                self.writer.stage_status(stage, outcome.status)
                self.writer.flush(current_stage=stage, status="RUNNING")
            if outcome.status in _STOP_STATUSES:
                if self.writer:
                    # Persist how to continue, so a signed review-inbox decision can retry, accept or abort.
                    self.writer.resume = {
                        "request": asdict(original), "cpf_uri": cpf_uri, "cpf_sha256": cpf_sha,
                        "completed_stages": completed, "escalated_stage": stage,
                    }
                    self.writer.record_escalation(stage, outcome.escalation_reason or "escalated", outcome.findings)
                    self.writer.flush(current_stage=stage, status="ESCALATED")
                # Carry the findings into the reason: a bare code like "stage_failed" tells the user nothing.
                detail = outcome.escalation_reason or ""
                if outcome.findings:
                    detail = f"{detail}: {'; '.join(outcome.findings)}" if detail else "; ".join(outcome.findings)
                return CampaignOutcome(
                    campaign_id=request.campaign_id, status="ESCALATED", stages=outcomes,
                    final_cpf_uri=cpf_uri, final_cpf_sha256=cpf_sha,
                    reason=f"stage {stage} {outcome.status}: {detail}".strip().rstrip(":"),
                )

        # All stages passed. Final CPF acceptance is a human review-inbox action (MS-01 §1), collected after.
        if self.writer:
            self.writer.resume = None  # nothing left to resume
            self.writer.flush(current_stage=(request.stages or completed or ["S0"])[-1], status="COMPLETED")
        return CampaignOutcome(
            campaign_id=request.campaign_id, status="COMPLETED", stages=outcomes,
            final_cpf_uri=cpf_uri, final_cpf_sha256=cpf_sha,
        )

    def _run_stage(self, request: CampaignRequest, stage: str, cpf_uri: str, cpf_sha: str) -> StageOutcome:
        budget = request.stage_budgets_seconds.get(stage, 0 if stage == "S0" else _DEFAULT_STAGE_BUDGET_S)
        started = time.monotonic()
        best_uri, best_sha = cpf_uri, cpf_sha
        actions_tried: list[str] = []
        pending_action: str | None = None
        pending_bounds: dict[str, list[float]] | None = None
        rounds_run = 0

        for round_index in range(1, request.max_rounds_per_stage + 1):
            remaining = budget - (time.monotonic() - started)
            if remaining <= 0:
                return StageOutcome(stage=stage, status="ESCALATED", rounds_run=rounds_run, cpf_uri=best_uri,
                                    cpf_sha256=best_sha, findings=["stage time budget exhausted"], escalation_reason="budget_exhausted")
            ctx = RoundContext(
                campaign_id=request.campaign_id, tenant_id=request.tenant_id, stage=stage, round_index=round_index,
                cpf_uri=cpf_uri, cpf_sha256=cpf_sha, pending_action=pending_action, actions_tried=list(actions_tried),
                pending_bounds_override=pending_bounds, deadline_seconds=remaining, seed=request.seed,
                map_uri=request.map_uri, map_sha256=request.map_sha256,
                observed_uri=request.observed_uri, observed_sha256=request.observed_sha256,
                system_uri=request.system_uri, system_sha256=request.system_sha256,
            )
            rounds_run = round_index
            try:
                result = self._run_round(ctx)
            except BudgetTooSmallError as exc:
                # The stage's remaining time cannot hold the planned fit (D8): escalate with the best CPF so far and
                # say why, rather than failing the stage and losing the rounds already run.
                return StageOutcome(stage=stage, status="ESCALATED", rounds_run=rounds_run - 1, cpf_uri=best_uri,
                                    cpf_sha256=best_sha, findings=[f"stage time budget exhausted: {exc}"],
                                    escalation_reason="budget_exhausted")
            run_result, evaluation, diagnosis, choice = result.run_result, result.evaluation, result.diagnosis, result.choice
            self._remember(stage, result)
            cpf_uri, cpf_sha = run_result.cpf_uri, run_result.cpf_sha256
            best_uri, best_sha = cpf_uri, cpf_sha

            if self.writer:
                self.writer.stage_notes(stage, result.notes)
                action = pending_action or "baseline"
                if pending_action and pending_action.startswith("fit") and not result.fitted:
                    action += " (fit produced no estimates; judged unchanged)"
                self.writer.add_round(stage, round_index, action, evaluation)
                self.writer.set_gof(_gof_series(run_result.results_uri, request.observed_uri), stage)
                self.writer.flush(current_stage=stage, status="RUNNING")

            if evaluation.gate_passed:
                return StageOutcome(stage=stage, status="PASSED", rounds_run=rounds_run, cpf_uri=cpf_uri,
                                    cpf_sha256=cpf_sha, findings=list(evaluation.findings))
            if diagnosis.escalate or choice is None or choice.action_id is None:
                reason = diagnosis.escalation_reason or "no_permitted_action"
                return StageOutcome(stage=stage, status="ESCALATED", rounds_run=rounds_run, cpf_uri=best_uri,
                                    cpf_sha256=best_sha, findings=list(evaluation.findings), escalation_reason=reason)
            actions_tried.append(choice.action_id)
            pending_action = choice.action_id
            pending_bounds = choice.bounds_override

        return StageOutcome(stage=stage, status="ESCALATED", rounds_run=rounds_run, cpf_uri=best_uri,
                            cpf_sha256=best_sha, findings=["maximum rounds reached without passing the gate"],
                            escalation_reason="rounds_exhausted")

    def _run_validation(self, request: CampaignRequest, stage: str, cpf_uri: str, cpf_sha: str) -> StageOutcome:
        """S4/S5 (MS-01 §4): simulate every planned study from the final CPF once and judge it — never fit.

        A failure escalates instead of refitting: at S4 it means a stage passed on stale values or stages
        interact; at S5 the modeler chooses a §6.6 path (limitation and continue, or stop)."""
        budget = request.stage_budgets_seconds.get(stage, _DEFAULT_STAGE_BUDGET_S)
        ctx = RoundContext(
            campaign_id=request.campaign_id, tenant_id=request.tenant_id, stage=stage, round_index=1,
            cpf_uri=cpf_uri, cpf_sha256=cpf_sha, pending_action=None, deadline_seconds=float(budget), seed=request.seed,
            map_uri=request.map_uri, map_sha256=request.map_sha256,
            observed_uri=request.observed_uri, observed_sha256=request.observed_sha256,
            system_uri=request.system_uri, system_sha256=request.system_sha256,
        )
        result = self._run_round(ctx, judge_only=True)
        evaluation = result.evaluation
        self._remember(stage, result)
        if self.writer:
            self.writer.stage_notes(stage, result.notes)
            self.writer.add_round(stage, 1, "validate", evaluation)
            self.writer.set_gof(_gof_series(result.run_result.results_uri, request.observed_uri), stage)
            self.writer.flush(current_stage=stage, status="RUNNING")
        findings = list(evaluation.findings) + [n for n in result.notes if n.startswith("NOT SIMULATED")]
        if evaluation.gate_passed:
            return StageOutcome(stage=stage, status="PASSED", rounds_run=1, cpf_uri=cpf_uri, cpf_sha256=cpf_sha,
                                findings=findings)
        return StageOutcome(stage=stage, status="ESCALATED", rounds_run=1, cpf_uri=cpf_uri, cpf_sha256=cpf_sha,
                            findings=findings, escalation_reason=_VALIDATION_FAILURE.get(stage, "validation_failed"))

    def _remember(self, stage: str, result: _RoundOutcome) -> None:
        """Keep the stage's latest judged round — its metrics, snapshot and outputs — for the package (S7)."""
        self._last[stage] = {"metrics": result.evaluation.metrics, "snapshot_uri": result.snapshot_uri,
                             "outputs": result.outputs}

    def _persist(self, request: CampaignRequest, outcome: StageOutcome) -> None:
        """Write the finished stage's evidence where S7 reads it, even across a pause for a signature."""
        from modeler_orchestrator.package_activities import persist_stage_evidence

        stage = outcome.stage
        writer = self.writer
        evidence = {
            "status": outcome.status, "findings": list(outcome.findings), "cpf_uri": outcome.cpf_uri,
            "rounds": list(writer._rounds.get(stage, [])) if writer else [],
            "notes": list(writer._notes.get(stage, [])) if writer else [],
            **self._last.get(stage, {}),
        }
        try:
            persist_stage_evidence(request.tenant_id, request.campaign_id, stage, evidence)
        except OSError:
            pass  # evidence is for the package; failing to write it must not stop the campaign — S7 will say so

    def _run_prediction(self, request: CampaignRequest, cpf_uri: str, cpf_sha: str) -> StageOutcome:
        """S6 (MS-01 §4): from the final CPF, re-simulate the internal studies, then run a local sensitivity
        analysis and propagate the fitted parameters' uncertainty to prediction intervals of AUC and Cmax."""
        from modeler_orchestrator.package_activities import evaluate_s6, prepare_s6_jobs

        ctx = RoundContext(
            campaign_id=request.campaign_id, tenant_id=request.tenant_id, stage="S6", round_index=1,
            cpf_uri=cpf_uri, cpf_sha256=cpf_sha, pending_action=None, seed=request.seed,
            deadline_seconds=float(request.stage_budgets_seconds.get("S6", _DEFAULT_STAGE_BUDGET_S)),
            map_uri=request.map_uri, map_sha256=request.map_sha256,
            observed_uri=request.observed_uri, observed_sha256=request.observed_sha256,
            system_uri=request.system_uri, system_sha256=request.system_sha256,
        )
        build, manifest = self._simulate(ctx)
        if manifest is None:
            reason = "; ".join(getattr(build, "notes", []) or []) or "no internal study could be simulated"
            return StageOutcome(stage="S6", status="SKIPPED", rounds_run=0, cpf_uri=cpf_uri, cpf_sha256=cpf_sha,
                                findings=[f"S6 not run: {reason}"])
        jobs, notes = prepare_s6_jobs(ctx, manifest)
        result = evaluate_s6(ctx, jobs, self._run_jobs(jobs))
        notes.append("application templates for the question of interest (DDI, paediatric, organ impairment, VBE) "
                     "are the next phase (T-31); S6 characterises the validated model")
        result["notes"] = notes
        self._last["S6"] = {"prediction": result}
        if self.writer:
            self.writer.prediction = result
            self.writer.stage_notes("S6", notes)
            self.writer.flush(current_stage="S6", status="RUNNING")
        return StageOutcome(stage="S6", status="PASSED", rounds_run=1, cpf_uri=cpf_uri, cpf_sha256=cpf_sha,
                            findings=notes)

    def _run_package(self, request: CampaignRequest, cpf_uri: str, cpf_sha: str) -> StageOutcome:
        """S7 (MS-01 §4): assemble the data bundle from the persisted evidence, re-run every bundled simulation on
        a fresh engine process, write the MAR, and release the package only if the reproduction passed (D13)."""
        from modeler_orchestrator.package_activities import (
            collect_bundle,
            collect_projects,
            finish_package,
            load_stage_evidence,
            prepare_project_jobs,
            prepare_reproduction_jobs,
            verify_package_reproduction,
        )

        evidence = load_stage_evidence(request.tenant_id, request.campaign_id)
        files, numeric, snapshots = collect_bundle(request.tenant_id, request.campaign_id, cpf_uri=cpf_uri,
                                                   map_uri=request.map_uri, observed_uri=request.observed_uri,
                                                   evidence=evidence, system_uri=request.system_uri)
        jobs = prepare_reproduction_jobs(request.tenant_id, request.campaign_id, files, snapshots)
        reproduction = verify_package_reproduction(files, numeric, jobs, self._run_jobs(jobs))
        projects: dict[str, bytes] = {}
        project_notes: list[str] = []
        project_jobs = prepare_project_jobs(request.tenant_id, request.campaign_id, files, snapshots)
        try:
            projects = collect_projects(project_jobs, self._run_jobs(project_jobs))
        except Exception as exc:  # noqa: BLE001 - the package is still released on reproduction; the gap is reported
            project_notes.append(f"PK-Sim project (.pksim5) not written: {exc}")
        if project_jobs and not projects and not project_notes:
            project_notes.append("PK-Sim project (.pksim5) not written: the engine returned no project file")
        record = finish_package(
            request.tenant_id, request.campaign_id, files=files, numeric=numeric, map_uri=request.map_uri,
            cpf_uri=cpf_uri, evidence=evidence, prediction=(evidence.get("S6") or {}).get("prediction"),
            reproduction=reproduction, engine_image_digest=os.environ.get("MODELER_IMAGE_DIGEST", ""),
            projects=projects, project_notes=project_notes,
        )
        if self.writer:
            self.writer.package = record
            self.writer.flush(current_stage="S7", status="RUNNING")
        if record["exportable"]:
            return StageOutcome(stage="S7", status="PASSED", rounds_run=1, cpf_uri=cpf_uri, cpf_sha256=cpf_sha,
                                findings=[(f"package released: {record['files']} files, reproduction passed on "
                                           f"{record['reproduction']['compared']} result tables")])
        findings = [f"{f['path']}: {f['status']} {f.get('detail', '')}".strip() for f in record["reproduction"]["failures"]]
        findings += [f"report: {i['detail']}" for i in record["report_issues"]]
        if not record["reproduction"]["compared"]:
            findings.append("no result table to reproduce (no S4/S5 simulation in the evidence)")
        return StageOutcome(stage="S7", status="ESCALATED", rounds_run=1, cpf_uri=cpf_uri, cpf_sha256=cpf_sha,
                            findings=findings, escalation_reason="package_not_reproducible")

    def _simulate(self, ctx: RoundContext) -> tuple[object, EngineManifest | None]:
        """Build the round's snapshot from ctx's CPF and run it on the engine (skipped when nothing was built)."""
        build = build_round_snapshot(ctx)
        manifest: EngineManifest | None = None
        if build.snapshot_uri != ctx.cpf_uri:
            manifest = self.engine(prepare_round_job(ctx, build))
        return build, manifest

    def _run_round(self, ctx: RoundContext, *, judge_only: bool = False) -> _RoundOutcome:
        build, manifest = self._simulate(ctx)
        notes = list(getattr(build, "notes", []) or [])

        fit_outcome = None
        if build.needs_fit and build.fit_request is not None and manifest is not None:
            pkml = collect_pkml_inputs(manifest)
            if pkml:
                fit_outcome = self._run_fit(replace(build.fit_request, model_inputs=pkml))

        run_result = run_round(RoundRun(context=ctx, build=build, fit_outcome=fit_outcome, manifest=manifest))
        judged_ctx = ctx
        fitted = run_result.cpf_uri != ctx.cpf_uri
        judged_manifest, judged_build = manifest, build
        if fitted:
            # The simulation above ran the CPF *before* the fit. Judge the fit in the round it happened: simulate
            # the fitted CPF and evaluate that, or a successful fit is scored on stale values, its action counts as
            # tried, and the stage can run out of actions and escalate although the fit worked.
            judged_ctx = replace(ctx, cpf_uri=run_result.cpf_uri, cpf_sha256=run_result.cpf_sha256,
                                 pending_action=None, pending_bounds_override=None, phase="postfit",
                                 fit_signals=fit_signals(fit_outcome))
            post_build, post_manifest = self._simulate(judged_ctx)
            judged_manifest, judged_build = post_manifest, post_build
            notes.extend(n for n in (getattr(post_build, "notes", []) or []) if n not in notes)
            run_result = run_round(RoundRun(context=judged_ctx, build=post_build, fit_outcome=None, manifest=post_manifest))

        evaluation = evaluate_round(judged_ctx, run_result)
        diagnosis = RoundDiagnosis()
        choice = None
        judged = {"snapshot_uri": judged_build.snapshot_uri if judged_manifest is not None else None,
                  "outputs": [{"name": o.name, "uri": o.uri, "sha256": o.sha256}
                              for o in (judged_manifest.outputs if judged_manifest is not None else [])]}
        if evaluation.gate_passed and judged_manifest is not None:
            vpc_jobs = prepare_vpc_jobs(judged_ctx, judged_manifest)  # none outside the VPC stages (no pkml)
            if vpc_jobs:
                evaluation = evaluate_vpc(judged_ctx, evaluation, self._run_jobs(vpc_jobs))
                if not evaluation.gate_passed:
                    # PK agrees but the population does not cover the data: no fit action addresses variability.
                    diagnosis = RoundDiagnosis(escalate=True, escalation_reason="vpc_coverage_below_80",
                                               evidence=[f for f in evaluation.findings if "VPC" in f])
                    return _RoundOutcome(run_result=run_result, evaluation=evaluation, diagnosis=diagnosis,
                                         choice=None, notes=notes, fitted=fitted, **judged)
        if not evaluation.gate_passed and not judge_only:
            diagnosis = diagnose_round(judged_ctx, evaluation)
            if not diagnosis.escalate:
                choice = choose_action(judged_ctx, diagnosis)
        return _RoundOutcome(run_result=run_result, evaluation=evaluation, diagnosis=diagnosis, choice=choice,
                             notes=notes, fitted=fitted, **judged)

    def _run_fit(self, fit_request) -> object:
        """Reproduce FitRoundWorkflow without Temporal: plan the multistart, run the starts on the engine in
        parallel — as many at once as the plan assumed (`fit_workers`) — and assess.

        The multistart planner sizes the number of starts for parallel execution; running them one after another
        multiplies a planned one-minute fit by the number of starts (up to 32), which breaks the one-hour budget."""
        jobs = plan_jobs(fit_request)
        manifests = self._run_jobs(jobs, workers=fit_workers(fit_request, len(jobs)))
        return assess_fit_round(fit_request, jobs, manifests, deadline_reached=False)

    def _run_jobs(self, jobs: list, *, workers: int | None = None) -> list:
        """Run independent engine jobs (fit starts, VPC populations) at once; each is its own engine subprocess."""
        workers = workers if workers is not None else max(1, min(len(jobs), os.cpu_count() or 1,
                                                                 int(os.environ.get("MODELER_FIT_WORKERS", "64"))))
        if workers <= 1 or len(jobs) <= 1:
            return [self.engine(job) for job in jobs]
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="engine-job") as pool:
            return list(pool.map(self.engine, jobs))


def run_campaign(
    request: CampaignRequest, *, read_root: str, project: str, question: str = "", model_risk: str = "medium",
    budget_seconds: int | None = None, engine: EngineRun | None = None,
) -> CampaignOutcome:
    """Run a campaign to completion single-node, writing live monitor artifacts under ``read_root``."""
    total_budget = budget_seconds or (sum(request.stage_budgets_seconds.values()) or 3600)
    writer = CampaignArtifactWriter(
        store=FileWriteStore(read_root), tenant_id=request.tenant_id, campaign_id=request.campaign_id,
        project=project, compound=request.compound, question=question, model_risk=model_risk,
        budget_seconds=total_budget, stages=list(request.stages), engine=engine_identity(engine),
    )
    writer.flush(current_stage=request.stages[0], status="RUNNING")
    return LocalExecutor(engine=engine or default_engine(), writer=writer).run(request)


# MS-01 §4 decisions a reviewer may take on an escalated stage.
ESCALATION_ACTIONS = ("retry", "accept_best", "abort", "approve")


def resolve_escalation(
    *, read_root: str, tenant_id: str, campaign_id: str, stage: str, action: str,
    engine: EngineRun | None = None, background: bool = True,
) -> dict:
    """Apply a signed review-inbox decision to a single-node campaign (MS-01 §4).

    ``abort``       — the stage is abandoned and the campaign ends there.
    ``accept_best`` — the best CPF found so far is accepted and the remaining stages continue.
    ``retry``       — the stage runs again from the CPF it escalated with (e.g. after new data or a wider bound).
    ``approve``     — a signature gate (the S4/S5 evaluation before S6) is signed and the campaign continues.

    Continuing runs the remaining stages on a background thread, exactly as starting a campaign does, so the
    caller returns immediately and the monitor fills in live. Raises LookupError/ValueError for a campaign that
    is not there or has no open escalation at that stage.
    """
    from modeler_api.filestore import FileReadStore

    if action not in ESCALATION_ACTIONS:
        raise ValueError(f"unknown escalation action {action!r}; expected one of {', '.join(ESCALATION_ACTIONS)}")

    read, write = FileReadStore(read_root), FileWriteStore(read_root)
    campaign = read.get_campaign(tenant_id, campaign_id)
    if campaign is None:
        raise LookupError(f"campaign {campaign_id} not found")
    resume = campaign.get("resume")
    if not resume or resume.get("escalated_stage") != stage:
        raise ValueError(f"campaign {campaign_id} has no open escalation at stage {stage}")

    request = CampaignRequest(**resume["request"])
    writer = CampaignArtifactWriter.from_campaign(write, tenant_id, campaign)
    write.remove_escalation(tenant_id, f"{campaign_id}-{stage}")  # the decision resolves it
    completed = list(resume.get("completed_stages", []))
    cpf_uri, cpf_sha = resume["cpf_uri"], resume["cpf_sha256"]

    if action == "abort":
        writer.stage_status(stage, "ABORTED")
        writer.resume = None
        writer.flush(current_stage=stage, status="ABORTED")
        return {"campaign_id": campaign_id, "stage": stage, "action": action, "status": "ABORTED"}

    if action == "accept_best":
        writer.stage_status(stage, "ACCEPTED")
        completed.append(stage)

    remaining = [s for s in request.stages if s != "S0" and s not in completed]
    writer.resume = None
    if not remaining:
        writer.flush(current_stage=stage, status="COMPLETED")
        return {"campaign_id": campaign_id, "stage": stage, "action": action, "status": "COMPLETED"}

    for pending in remaining:  # a retried/continued stage starts from PENDING again in the monitor
        writer.stage_status(pending, "PENDING")
    writer.flush(current_stage=remaining[0], status="RUNNING")

    continuation = replace(request, stages=remaining, cpf_uri=cpf_uri, cpf_sha256=cpf_sha)
    executor = LocalExecutor(engine=engine or default_engine(), writer=writer,
                             approved_gates={stage} if action == "approve" else set())

    def _continue() -> None:
        executor.run(continuation, original=request, completed_before=completed)

    if background:
        import threading

        threading.Thread(target=_continue, daemon=True).start()
    else:
        _continue()
    return {"campaign_id": campaign_id, "stage": stage, "action": action, "status": "RUNNING",
            "remaining_stages": remaining}


def _request_from_spec(spec: dict) -> CampaignRequest:
    fields = {f for f in CampaignRequest.__dataclass_fields__}
    return CampaignRequest(**{k: v for k, v in spec.items() if k in fields})


def main(argv: list[str] | None = None) -> int:
    """CLI: ``python -m modeler_orchestrator.local_runner <spec.json>`` runs one campaign on this host.

    The spec JSON carries the CampaignRequest fields plus the monitor metadata ``project``/``question``/
    ``model_risk``; ``read_root`` comes from the spec or ``MODELER_READ_ROOT``.
    """
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print("usage: python -m modeler_orchestrator.local_runner <spec.json>", file=sys.stderr)
        return 2
    spec = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    read_root = spec.get("read_root") or os.environ.get("MODELER_READ_ROOT")
    if not read_root:
        print("read_root not set (spec.read_root or MODELER_READ_ROOT)", file=sys.stderr)
        return 2
    outcome = run_campaign(
        _request_from_spec(spec), read_root=read_root, project=spec["project"],
        question=spec.get("question", ""), model_risk=spec.get("model_risk", "medium"),
        budget_seconds=spec.get("budget_seconds"),
    )
    print(json.dumps({"campaign_id": outcome.campaign_id, "status": outcome.status, "reason": outcome.reason,
                      "stages": [{"stage": s.stage, "status": s.status, "rounds": s.rounds_run} for s in outcome.stages]}, indent=2))
    return 0 if outcome.status == "COMPLETED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
