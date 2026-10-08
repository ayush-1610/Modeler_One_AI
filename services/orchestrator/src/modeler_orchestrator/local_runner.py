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
from modeler_contracts.runtime import engine_kind, runtime_env
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
from modeler_orchestrator.history import Ledger, influence_map, study_verdict
from modeler_orchestrator.memo import model_set
from modeler_storage.filestore import FileWriteStore, WriteStore
from pbpk_domain.campaign.map import FIT_STAGES
from pbpk_domain.data_origin import real_data_summary, signature_refusal
from pbpk_domain.fitting import BudgetTooSmallError

# One callable dispatches an engine job to a manifest — the real EngineRunner.run in production, a stub in tests.
EngineRun = Callable[[EngineJob], EngineManifest]

STAGE_LABELS = {
    "S0": "Readiness", "S1": "IV disposition", "S2": "Oral fasted",
    "S3": "Formulation / fed", "SJ": "Joint refinement", "S4": "Internal validation", "S5": "External validation",
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
_BEFORE_GATE = ("S1", "S2", "S3", "S4", "S5")


def default_engine() -> EngineRun:
    """A real engine dispatcher: ``Rscript run_job.R`` over a ``file://`` object store, configured from env.

    On the server the engine env (PATH, LD_LIBRARY_PATH, DOTNET_ROOT, R_LIBS_USER, LC_ALL) is passed through
    to the subprocess by EngineRunner; ``MODELER_ENGINE_COMMAND`` points at the run_job.R for this host.
    """
    from modeler_engine.runner import EngineRunner, LocalObjectStore

    env = runtime_env()
    command = env.resolved_engine_command(development_engine())
    runner = EngineRunner(
        command=shlex.split(command),
        store=LocalObjectStore(),
        engine_id=env.resolved_engine_id(command),
        image_digest=env.resolved_image_digest(),
    )
    return runner.run


def development_engine() -> str:
    """The engine a development checkout runs when MODELER_ENGINE_COMMAND is unset: its stub engine, a software fixture
    every page labels as such (production has no default: modeler_contracts.runtime)."""
    stub = Path(__file__).resolve().parents[4] / "deploy" / "dev" / "stub_engine.py"
    return shlex.join([sys.executable, str(stub)])


def engine_identity(engine: EngineRun | None = None) -> dict:
    """What a campaign's numbers come from, for the monitor: real PK-Sim, a software fixture, or an injected engine.

    Shown on every campaign so a run on the stub can never be read as a PBPK result."""
    if engine is not None:
        return {"kind": "injected", "command": getattr(engine, "__name__", type(engine).__name__)}
    command = runtime_env().resolved_engine_command(development_engine())
    words = [os.path.basename(w) for w in shlex.split(command)]
    return {"kind": engine_kind(command), "command": " ".join(words)}


def fit_workers(fit_request, n_jobs: int) -> int:
    """How many fit starts run at once: the planner's parallelism (cores ÷ simulations per start), never more than
    this machine's CPUs, overridable with MODELER_FIT_WORKERS (e.g. to spare memory on a laptop's Docker engine)."""
    override = runtime_env().fit_workers
    if override:
        return max(1, min(int(override), n_jobs))
    per_start = max(1, int(getattr(fit_request, "simulations_per_evaluation", 1) or 1))
    planned = max(1, int(getattr(fit_request, "cores", 1) or 1) // per_start)
    return max(1, min(planned, os.cpu_count() or 1, n_jobs))


def _local_text(uri: str) -> str | None:
    parsed = urlparse(uri)
    path = Path(unquote(parsed.path))
    if parsed.scheme != "file" or not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


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
    origins: dict[str, str | None] = field(default_factory=dict)  # study -> origin of its observed data (plan §9.4)
    ledger: Ledger = field(default_factory=Ledger)  # every parameter-set change and the verdicts it moved (§12.3 N6)
    influence: dict | None = None                   # parameters × studies on the working set (§12.3 N5)
    cycle: int = 1                                  # the external-validation feedback cycle (§12.3 N4)
    feedback: list[dict] = field(default_factory=list)  # every signed feedback decision, in order
    feedback_pending: dict | None = None            # the S5 failure's diagnosis while a decision is awaited
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
        writer.origins = dict(campaign.get("observedOrigins") or {})
        writer.ledger = Ledger.from_content(campaign.get("ledger"))
        writer.influence = campaign.get("influence")
        writer.cycle = int(campaign.get("cycle", 1))
        writer.feedback = list(campaign.get("feedback") or [])
        writer.feedback_pending = campaign.get("feedbackPending")
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

    def add_round(self, stage: str, round_index: int, action: str, evaluation: RoundEvaluation,
                  model_set: dict | None = None) -> None:
        auc = evaluation.metrics.get("AUC", {}).get("gmfe")
        cmax = evaluation.metrics.get("Cmax", {}).get("gmfe")
        # What the verdict rests on (plan §9.4): a pass judged on data that is not real is shown for what it is.
        real_data = real_data_summary(self.origins, evaluation.metrics.get("studies", []))
        verdict = "passed" if evaluation.gate_passed else "no pass"
        if evaluation.gate_passed and real_data["judged"] and not real_data["passable"]:
            verdict = real_data["label"]
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
            "realData": real_data,
            "modelSet": model_set,  # the parameter set, engine and scenarios this verdict judged (plan §12.3 N1)
            "cycle": self.cycle,
        })
        if model_set:
            self.ledger.judged(stage=stage, cpf_sha=model_set["cpf_sha256"], model_set=model_set["id"],
                               studies=evaluation.metrics.get("studies", []))

    def record_change(self, stage: str, kind: str, reason: str, before: tuple[str, str], after: tuple[str, str]) -> None:
        """A new working parameter set (uri, sha): recorded before the rounds judged on it, which explain themselves."""
        if before[1] != after[1]:
            self.ledger.change(stage=stage, kind=kind, reason=reason, before=before, after=after, cycle=self.cycle)

    def next_round(self, stage: str) -> int:
        return len(self._rounds.setdefault(stage, [])) + 1

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
            "observedOrigins": self.origins,
            "realData": self.real_data(),
            "ledger": self.ledger.to_content(),
            "influence": self.influence,
            "cycle": self.cycle,
            "feedback": self.feedback,
            "feedbackPending": self.feedback_pending,
            "resume": self.resume,
        })

    def real_data(self) -> dict[str, dict]:
        """Each stage's real-data summary of its last judged round (the one the stage's verdict rests on)."""
        latest: dict[str, dict] = {}
        for stage, rounds in self._rounds.items():
            judged = [r["realData"] for r in rounds if (r.get("realData") or {}).get("judged")]
            if judged:
                latest[stage] = judged[-1]
        return latest

    def record_signature_request(self, stage: str) -> None:
        """The review-inbox item that holds the campaign until the S4/S5 evaluation is signed (MS-01 §4 S6)."""
        self.store.upsert_escalation(self.tenant_id, {
            "id": f"{self.campaign_id}-{stage}", "campaignId": self.campaign_id, "stage": stage,
            "reasonCode": "SIGNATURE_REQUIRED",
            "evidence": "Internal (S4) and external (S5) validation are complete. MS-01 requires them signed before "
                        "the model is used for prediction (S6) and the report and package are assembled (S7).",
            "options": _SIGNATURE_OPTIONS,
        })

    def record_feedback(self, diagnosis: dict, findings: list[str]) -> None:
        """The review-inbox item for an S5 failure (plan §12.4 FEEDBACK_PENDING): the diagnosis and the decisions."""
        self.feedback_pending = diagnosis
        failing = "; ".join(f"{f['study_id']} ({f['class']}): {', '.join(f['failed'])} {f['direction']}"
                            for f in diagnosis.get("failing", []))
        self.store.upsert_escalation(self.tenant_id, {
            "id": f"{self.campaign_id}-S5", "campaignId": self.campaign_id, "stage": "S5",
            "reasonCode": "EXTERNAL_VALIDATION_FAILED",
            "evidence": f"External validation failed (cycle {self.cycle}): {failing or '; '.join(findings)}.",
            "options": diagnosis.get("options", _VALIDATION_OPTIONS), "feedback": diagnosis,
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
    engine_key: str = ""                                    # what the engine is (command, image digest): model sets
    _last: dict[str, dict] = field(default_factory=dict)   # stage -> its judged round (metrics, snapshot, outputs)
    _passed: set[str] = field(default_factory=set)         # fit stages that passed their gate (no-regression baseline)

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
        # a resumed campaign's fit stages that passed are the no-regression baseline (an accepted-best stage is not)
        status_of = self.writer._status if self.writer else {}
        self._passed |= {s for s in completed if s in FIT_STAGES and status_of.get(s, "PASSED") == "PASSED"}

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
                if plan.kind == "joint":
                    outcome = self._run_joint(request, cpf_uri, cpf_sha, stages=FIT_STAGES, record_stage="SJ")
                elif plan.kind == "validate":
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
            if stage in FIT_STAGES and outcome.status == "PASSED":
                if outcome.cpf_sha256 != cpf_sha:
                    # the stage changed the parameter set: every earlier stage that passed is judged again on it
                    regressions = self._no_regression(request, stage, outcome.cpf_uri, outcome.cpf_sha256)
                    if regressions:
                        # the remedy first: one joint fit over the stages up to this one (N2 → N3); else escalate
                        upto = FIT_STAGES[: FIT_STAGES.index(stage) + 1]
                        joint = self._run_joint(request, outcome.cpf_uri, outcome.cpf_sha256, stages=upto,
                                                record_stage=stage, after_regression=True)
                        if joint.status == "PASSED":
                            outcome = StageOutcome(stage=stage, status="PASSED", rounds_run=outcome.rounds_run + 1,
                                                   cpf_uri=joint.cpf_uri, cpf_sha256=joint.cpf_sha256,
                                                   findings=[*regressions, *joint.findings])
                        else:
                            outcome = StageOutcome(stage=stage, status="ESCALATED", rounds_run=outcome.rounds_run,
                                                   cpf_uri=outcome.cpf_uri, cpf_sha256=outcome.cpf_sha256,
                                                   findings=[*regressions, *joint.findings], escalation_reason="regression")
                if outcome.status == "PASSED":
                    self._passed.add(stage)
            outcomes.append(outcome)
            cpf_uri, cpf_sha = outcome.cpf_uri, outcome.cpf_sha256
            self._influence(request, cpf_uri, cpf_sha)
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
                    if stage == "S5" and outcome.escalation_reason == _VALIDATION_FAILURE["S5"]:
                        diagnosis = self._diagnose_s5(request, cpf_uri, cpf_sha)
                        self.writer.resume["feedback"] = diagnosis
                        self.writer.record_feedback(diagnosis, outcome.findings)
                    else:
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
                system_uri=request.system_uri, system_sha256=request.system_sha256, cycle=request.cycle,
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
                self.writer.record_change(stage, "fit", f"round {round_index}: {action}", (ctx.cpf_uri, ctx.cpf_sha256),
                                          (run_result.cpf_uri, run_result.cpf_sha256))
                self.writer.add_round(stage, round_index, action, evaluation,
                                      model_set=self._model_set(request, stage, run_result.cpf_sha256))
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
            system_uri=request.system_uri, system_sha256=request.system_sha256, cycle=request.cycle,
        )
        result = self._run_round(ctx, judge_only=True)
        evaluation = result.evaluation
        self._remember(stage, result)
        if self.writer:
            self.writer.stage_notes(stage, result.notes)
            self.writer.add_round(stage, 1, "validate", evaluation,
                                  model_set=self._model_set(request, stage, result.run_result.cpf_sha256))
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
            system_uri=request.system_uri, system_sha256=request.system_sha256, cycle=request.cycle,
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
            reproduction=reproduction, engine_image_digest=runtime_env().resolved_image_digest(),
            projects=projects, project_notes=project_notes,
            history=self.writer.ledger.to_content() if self.writer else None,
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

    def _no_regression(self, request: CampaignRequest, stage: str, cpf_uri: str, cpf_sha: str) -> list[str]:
        """Plan §12.3 N2: after `stage` changed the CPF, simulate every internal study of each earlier fit stage that
        passed, from the new model set, and judge it against its own stage gate (external studies stay unseen). A
        study that passed before and fails now is a regression; the findings say which and why."""
        regressions: list[str] = []
        for earlier in [s for s in FIT_STAGES if s in self._passed and FIT_STAGES.index(s) < FIT_STAGES.index(stage)]:
            ctx = RoundContext(
                campaign_id=request.campaign_id, tenant_id=request.tenant_id, stage=earlier, round_index=1,
                cpf_uri=cpf_uri, cpf_sha256=cpf_sha, pending_action=None, seed=request.seed,
                deadline_seconds=float(request.stage_budgets_seconds.get(earlier, _DEFAULT_STAGE_BUDGET_S)),
                map_uri=request.map_uri, map_sha256=request.map_sha256,
                observed_uri=request.observed_uri, observed_sha256=request.observed_sha256,
                system_uri=request.system_uri, system_sha256=request.system_sha256, cycle=request.cycle, phase=f"after-{stage}",
            )
            result = self._run_round(ctx, judge_only=True)
            if self.writer:
                self.writer.add_round(earlier, self.writer.next_round(earlier), f"no-regression check with {stage}'s CPF",
                                      result.evaluation, model_set=self._model_set(request, earlier, cpf_sha))
                self.writer.flush(current_stage=stage, status="RUNNING")
            if not result.evaluation.gate_passed:
                why = "; ".join(result.evaluation.findings[:3]) or "its gate no longer passes"
                regressions.append(f"{earlier} no longer passes with the CPF {stage} fitted (no-regression gate, plan §12.3 "
                                   f"N2): {why}")
        return regressions

    def _joint_plan(self, cpf_uri: str, stages: tuple[str, ...]):
        """The parameters `stages` fitted and the S1-CI guard (from the CPF the joint fit starts from)."""
        from modeler_orchestrator.joint import joint_parameters
        from pbpk_domain.cpf import CPF

        text = _local_text(cpf_uri)
        return joint_parameters(CPF.model_validate_json(text), stages) if text else None

    def _joint_map(self, request: CampaignRequest, stages: tuple[str, ...], tag: str) -> tuple[str, str, list[str]]:
        from modeler_orchestrator.joint import joint_map

        return joint_map(request.map_uri, stages, tag=tag) if request.map_uri else ("", "", [])

    def _run_joint(self, request: CampaignRequest, cpf_uri: str, cpf_sha: str, *, stages: tuple[str, ...],
                   record_stage: str, after_regression: bool = False) -> StageOutcome:
        """SJ (plan §12.3 N3, MS-01 v1.1 UNVERIFIED): refit the parameters `stages` fitted, in one parameter
        identification over all their internal studies, from the sequential estimates; keep the joint estimate only
        if every study passes and the agreement is no worse, else keep the sequential set and record why."""
        from modeler_orchestrator.joint import JOINT, agreement

        label = "S1–" + stages[-1] if len(stages) > 1 else stages[0]
        plan = self._joint_plan(cpf_uri, stages)
        if plan is None or not plan.fit_ids:
            why = f"no parameter was fitted in {label}: nothing to refine jointly (S4 judges every internal study)"
            if self.writer and not after_regression:
                self.writer.stage_notes(record_stage, [why])
            return StageOutcome(stage=JOINT, status="SKIPPED" if not after_regression else "ESCALATED", rounds_run=0,
                                cpf_uri=cpf_uri, cpf_sha256=cpf_sha, findings=[why])
        map_uri, map_sha, studies = self._joint_map(request, stages, tag=f"{request.campaign_id}-{stages[-1]}"
                                                    + (f"-c{request.cycle}" if request.cycle > 1 else ""))
        budget = float(request.stage_budgets_seconds.get(JOINT, _DEFAULT_STAGE_BUDGET_S))
        base_ctx = RoundContext(
            campaign_id=request.campaign_id, tenant_id=request.tenant_id, stage=JOINT, round_index=1, cpf_uri=cpf_uri,
            cpf_sha256=cpf_sha, pending_action=None, deadline_seconds=budget, seed=request.seed,
            map_uri=map_uri or request.map_uri, map_sha256=map_sha or request.map_sha256,
            observed_uri=request.observed_uri, observed_sha256=request.observed_sha256,
            system_uri=request.system_uri, system_sha256=request.system_sha256, cycle=request.cycle,
            phase="after-regression" if after_regression else "",
        )
        base = self._run_round(base_ctx, judge_only=True)
        fit_ctx = replace(base_ctx, round_index=2, pending_action="fit " + "+".join(plan.fit_ids),
                          pending_bounds_override=plan.bounds or None)
        joint = self._run_round(fit_ctx, judge_only=True)
        base_score, joint_score = agreement(base.evaluation), agreement(joint.evaluation)
        kept = joint.fitted and joint.evaluation.gate_passed and (
            base_score is None or joint_score is None or joint_score <= base_score + 1e-9)
        if self.writer:
            what = "joint refit after the regression" if after_regression else "joint baseline (sequential estimates)"
            self.writer.add_round(record_stage, self.writer.next_round(record_stage), what, base.evaluation,
                                  model_set=self._model_set(request, JOINT, cpf_sha))
            if kept:
                self.writer.record_change(record_stage, "joint refit", f"joint fit of {', '.join(plan.fit_ids)} over {label} "
                                          "kept: every internal study passes, agreement no worse", (cpf_uri, cpf_sha),
                                          (joint.run_result.cpf_uri, joint.run_result.cpf_sha256))
            self.writer.add_round(record_stage, self.writer.next_round(record_stage), f"joint fit of {', '.join(plan.fit_ids)}",
                                  joint.evaluation, model_set=self._model_set(request, JOINT, joint.run_result.cpf_sha256))
        notes = [f"joint refinement over {len(studies) or 'the'} internal studies of {label} ({', '.join(studies)})"
                 if studies else f"joint refinement over the internal studies of {label}",
                 f"refitted: {', '.join(plan.fit_ids)}"
                 + (f"; held within their S1 95 % CI: {', '.join(plan.guarded)}" if plan.guarded else ""),
                 *plan.notes,
                 "studies weighted per observed point (equal weight per study, D-04, waits for run_pi.R weights)"]
        if kept:
            notes.append(f"joint estimate kept: every internal study passes, GMFE {base_score} → {joint_score}"
                         if base_score is not None else "joint estimate kept: every internal study passes")
            outcome = StageOutcome(stage=JOINT, status="PASSED", rounds_run=2, cpf_uri=joint.run_result.cpf_uri,
                                   cpf_sha256=joint.run_result.cpf_sha256, findings=notes)
        else:
            why = ("the fit produced no estimate" if not joint.fitted else "an internal study fails with the joint estimate"
                   if not joint.evaluation.gate_passed else f"the agreement got worse (GMFE {base_score} → {joint_score})")
            notes.append(f"joint estimate not kept: {why}; the sequential estimates stay")
            status = "PASSED" if base.evaluation.gate_passed and not after_regression else "ESCALATED"
            outcome = StageOutcome(stage=JOINT, status=status, rounds_run=2, cpf_uri=cpf_uri, cpf_sha256=cpf_sha,
                                   findings=[*notes, *([] if status == "PASSED" else base.evaluation.findings[:3])],
                                   escalation_reason=None if status == "PASSED" else "joint_refinement_failed")
        if self.writer:
            self.writer.stage_notes(record_stage, notes)
        return outcome

    def _diagnose_s5(self, request: CampaignRequest, cpf_uri: str, cpf_sha: str) -> dict:
        """Plan §12.3 N4 step 1: each failing external study — metric, direction, class, the parameters acting on it
        (the engine's sensitivity for that study, N5) and how it differs from training — and the decisions allowed."""
        from modeler_orchestrator.feedback import diagnose
        from modeler_orchestrator.package_activities import prepare_feedback_sensitivity, reduce_sensitivity
        from pbpk_domain.cpf import CPF

        map_doc = (_local_json(request.map_uri) if request.map_uri else None) or {}
        last = self._last.get("S5") or {}
        studies = (last.get("metrics") or {}).get("studies", [])
        failing = [str(s.get("study_id")) for s in studies if study_verdict(s) == "fail"]
        notes: list[str] = []
        sensitivity: dict[str, list[dict]] = {}
        if failing and last.get("outputs") and request.map_uri:
            ctx = RoundContext(
                campaign_id=request.campaign_id, tenant_id=request.tenant_id, stage="S5", round_index=1, cpf_uri=cpf_uri,
                cpf_sha256=cpf_sha, pending_action=None, seed=request.seed, map_uri=request.map_uri,
                map_sha256=request.map_sha256, cycle=request.cycle,
            )
            try:
                jobs, notes = prepare_feedback_sensitivity(ctx, last["outputs"], failing)
                sensitivity = reduce_sensitivity(jobs, self._run_jobs(jobs))
            except Exception as exc:  # noqa: BLE001 - the decision is still offered; the gap is stated
                notes.append(f"sensitivity of the failing studies not computed: {type(exc).__name__}: {exc}")
        influence = influence_map(map_doc, cpf_uri, {"sensitivity": sensitivity}, cpf_sha=cpf_sha) if map_doc else None
        if self.writer and influence:
            self.writer.influence = influence
        text = _local_text(cpf_uri)
        cpf = CPF.model_validate_json(text) if text else None
        diagnosis = diagnose(map_doc, studies, influence=influence, history=self.writer.feedback if self.writer else [],
                             cpf=cpf)
        return {**diagnosis, "cycle": request.cycle, "notes": notes}

    def _influence(self, request: CampaignRequest, cpf_uri: str, cpf_sha: str) -> None:
        """The influence map on the working parameter set (plan §12.3 N5), with S6's sensitivities once they ran."""
        map_doc = _local_json(request.map_uri) if request.map_uri else None
        if self.writer and map_doc:
            self.writer.influence = influence_map(map_doc, cpf_uri, self.writer.prediction, cpf_sha=cpf_sha)

    def _model_set(self, request: CampaignRequest, stage: str, cpf_sha: str) -> dict:
        map_doc = _local_json(request.map_uri) if request.map_uri else None
        scenarios = [s for s in (map_doc or {}).get("scenarios", []) if s.get("stage") == stage]
        return model_set(cpf_sha256=cpf_sha, engine_key=self.engine_key, scenarios=scenarios, stage=stage)

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
                                                                 int(runtime_env().get("fit_workers", "64"))))
        if workers <= 1 or len(jobs) <= 1:
            return [self.engine(job) for job in jobs]
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="engine-job") as pool:
            return list(pool.map(self.engine, jobs))


def engine_key(engine: EngineRun | None = None) -> str:
    """The engine a model set and a memoized run are bound to: its identity and image digest."""
    ident = engine_identity(engine)
    return f"{ident['kind']}:{ident['command']}@{runtime_env().resolved_image_digest()}"


def _executor_engine(engine: EngineRun | None, *, read_root: str, tenant_id: str, memo: bool | None) -> EngineRun:
    """The engine the executor calls: memoized (plan §12.3 N7) by default for the configured engine, and for an
    injected one only when asked (tests count their engine's calls)."""
    from modeler_orchestrator.memo import MemoEngine

    base = engine or default_engine()
    if memo if memo is not None else (engine is None or runtime_env().memo == "1"):
        return MemoEngine(base, root=Path(read_root) / tenant_id / "memo", engine_key=engine_key(engine))
    return base


def _campaign_writer(request: CampaignRequest, *, read_root: str, project: str, question: str, model_risk: str,
                     budget_seconds: int | None, engine: EngineRun | None) -> CampaignArtifactWriter:
    total_budget = budget_seconds or (sum(request.stage_budgets_seconds.values()) or 3600)
    return CampaignArtifactWriter(
        store=FileWriteStore(read_root), tenant_id=request.tenant_id, campaign_id=request.campaign_id,
        project=project, compound=request.compound, question=question, model_risk=model_risk,
        budget_seconds=total_budget, stages=list(request.stages), engine=engine_identity(engine),
        origins=observed_origins(request.observed_uri),
    )


def _run_with(request: CampaignRequest, writer: CampaignArtifactWriter, *, read_root: str, engine: EngineRun | None,
              memo: bool | None) -> CampaignOutcome:
    return LocalExecutor(engine=_executor_engine(engine, read_root=read_root, tenant_id=request.tenant_id, memo=memo),
                         writer=writer, engine_key=engine_key(engine)).run(request)


def run_campaign(
    request: CampaignRequest, *, read_root: str, project: str, question: str = "", model_risk: str = "medium",
    budget_seconds: int | None = None, engine: EngineRun | None = None, memo: bool | None = None,
) -> CampaignOutcome:
    """Run a campaign to completion single-node, writing live monitor artifacts under ``read_root``."""
    writer = _campaign_writer(request, read_root=read_root, project=project, question=question, model_risk=model_risk,
                              budget_seconds=budget_seconds, engine=engine)
    writer.flush(current_stage=request.stages[0], status="RUNNING")
    return _run_with(request, writer, read_root=read_root, engine=engine, memo=memo)


def start_campaign(
    request: CampaignRequest, *, read_root: str, project: str, question: str = "", model_risk: str = "medium",
    budget_seconds: int | None = None, engine: EngineRun | None = None, memo: bool | None = None,
):
    """Write the campaign's first monitor record (QUEUED) now, then run it on a background thread.

    The record exists before the caller hands out the campaign id, so a GET right after the start finds the campaign
    instead of a 404 (the T-56 kit test polled it before the thread's first write, about 1 run in 30)."""
    import threading

    writer = _campaign_writer(request, read_root=read_root, project=project, question=question, model_risk=model_risk,
                              budget_seconds=budget_seconds, engine=engine)
    writer.flush(current_stage=request.stages[0], status="QUEUED")
    thread = threading.Thread(target=_run_with, args=(request, writer),
                              kwargs={"read_root": read_root, "engine": engine, "memo": memo}, daemon=True)
    thread.start()
    return thread


def observed_origins(observed_uri: str) -> dict[str, str | None]:
    """Each study's data origin as campaign:prepare recorded it in the observed PK (None: not recorded)."""
    observed = _local_json(observed_uri) if observed_uri else None
    return {sid: (pk or {}).get("origin") for sid, pk in (observed or {}).items()}


def gate_refusal(campaign: dict, project: dict | None) -> str | None:
    """Why the S4/S5 evaluation of this campaign may not be signed (plan §9.4, D-19), or None. Every stage before the
    gate counts: a model fitted or judged on data that is not real is not validated by signing it."""
    summaries = {stage: summary for stage, summary in (campaign.get("realData") or {}).items() if stage in _BEFORE_GATE}
    return signature_refusal(summaries, exploratory=bool((project or {}).get("exploratory")))


# MS-01 §4 decisions a reviewer may take on an escalated stage; learn and new evidence answer an S5 failure (§12.3 N4).
ESCALATION_ACTIONS = ("retry", "accept_best", "abort", "approve", "learn", "new_evidence")
_FEEDBACK_CYCLES = ("learn", "new_evidence")


def _learn_studies(diagnosis: dict, payload: dict) -> list[str]:
    """The studies a learn decision moves: the ones named, else every failing study whose class may learn."""
    if payload.get("studies"):
        return [str(s) for s in payload["studies"]]
    return [f["study_id"] for f in diagnosis.get("failing", [])
            if diagnosis["classes"].get(f["class"], {}).get("learn", {}).get("possible")]


def check_feedback(campaign: dict, stage: str, action: str, payload: dict | None) -> None:
    """The guardrails of a feedback decision, checked before it is signed (ValueError: refused, with the reason)."""
    from modeler_orchestrator.feedback import check_evidence, check_learn

    if action not in _FEEDBACK_CYCLES:
        return
    resume = campaign.get("resume") or {}
    diagnosis = resume.get("feedback")
    if stage != "S5" or resume.get("escalated_stage") != "S5" or not diagnosis:
        raise ValueError(f"{action.replace('_', ' ')} answers a failed external validation (S5) awaiting a decision")
    payload = payload or {}
    if action == "learn":
        check_learn(_learn_studies(diagnosis, payload), diagnosis, beyond_cap=str(payload.get("beyond_cap", "")))
        return
    try:
        value = float(payload.get("value"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ValueError("new evidence needs a numeric value") from None
    check_evidence(resume["cpf_uri"], parameter=str(payload.get("parameter", "")), value=value,
                   unit=payload.get("unit") or None, reference=str(payload.get("reference", "")))


def resolve_escalation(
    *, read_root: str, tenant_id: str, campaign_id: str, stage: str, action: str,
    engine: EngineRun | None = None, background: bool = True, payload: dict | None = None,
    signature_id: str = "", printed_name: str = "", note: str = "",
) -> dict:
    """Apply a signed review-inbox decision to a single-node campaign (MS-01 §4).

    ``abort``       — the stage is abandoned and the campaign ends there.
    ``accept_best`` — the best CPF found so far is accepted and the remaining stages continue.
    ``retry``       — the stage runs again from the CPF it escalated with (e.g. after new data or a wider bound).
    ``approve``     — a signature gate (the S4/S5 evaluation before S6) is signed and the campaign continues.
    ``learn``       — S5 failed: the failing studies move to the internal set (a MAP deviation signed by this decision)
                      and cycle c+1 runs from the stage they train through SJ, S4 and S5 on the studies left.
    ``new_evidence``— S5 failed: one parameter takes a measured value (`payload`: parameter, value, unit, reference)
                      and cycle c+1 runs the whole chain; S5 re-judges the same studies, flagged as prompted by S5.

    Continuing runs the remaining stages on a background thread, exactly as starting a campaign does, so the
    caller returns immediately and the monitor fills in live. Raises LookupError/ValueError for a campaign that
    is not there or has no open escalation at that stage.
    """
    from modeler_storage.filestore import FileReadStore

    if action not in ESCALATION_ACTIONS:
        raise ValueError(f"unknown escalation action {action!r}; expected one of {', '.join(ESCALATION_ACTIONS)}")

    read, write = FileReadStore(read_root), FileWriteStore(read_root)
    campaign = read.get_campaign(tenant_id, campaign_id)
    if campaign is None:
        raise LookupError(f"campaign {campaign_id} not found")
    resume = campaign.get("resume")
    if not resume or resume.get("escalated_stage") != stage:
        raise ValueError(f"campaign {campaign_id} has no open escalation at stage {stage}")

    if action == "approve" and (refusal := gate_refusal(campaign, read.get_project(tenant_id, campaign.get("project", "")))):
        raise ValueError(refusal)
    check_feedback(campaign, stage, action, payload)

    request = CampaignRequest(**resume["request"])
    writer = CampaignArtifactWriter.from_campaign(write, tenant_id, campaign)
    write.remove_escalation(tenant_id, f"{campaign_id}-{stage}")  # the decision resolves it
    completed = list(resume.get("completed_stages", []))
    cpf_uri, cpf_sha = resume["cpf_uri"], resume["cpf_sha256"]

    diagnosis = resume.get("feedback")
    writer.feedback_pending = None
    if action == "abort":
        if diagnosis:  # §12.4: stop → ABANDONED, on the record with the studies that failed
            writer.feedback.append({"cycle": writer.cycle, "action": "stop", "signature_id": signature_id, "note": note,
                                    "failing": [f["study_id"] for f in diagnosis.get("failing", [])]})
        writer.stage_status(stage, "ABORTED")
        writer.resume = None
        writer.flush(current_stage=stage, status="ABORTED")
        return {"campaign_id": campaign_id, "stage": stage, "action": action, "status": "ABORTED"}

    if action == "accept_best":
        writer.stage_status(stage, "ACCEPTED")
        completed.append(stage)
        if diagnosis:  # MS-01 §6.6 path 1: the failure is a limitation of the context of use, on the record
            failing = [f["study_id"] for f in diagnosis.get("failing", [])]
            writer.feedback.append({"cycle": writer.cycle, "action": "limitation", "failing": failing,
                                    "signature_id": signature_id, "note": note})
            writer.stage_notes("S5", [f"limitation (cycle {writer.cycle}, signed {signature_id or 'decision'}): "
                                      f"{', '.join(failing)} failed external validation; the context of use is restricted"
                                      + (f" ({note})" if note else ""), *diagnosis.get("notAchievable", [])])
    elif action in _FEEDBACK_CYCLES:
        request, cpf_uri, cpf_sha, queue = _start_cycle(writer, request, diagnosis or {}, action, payload or {},
                                                        cpf_uri=cpf_uri, cpf_sha=cpf_sha, signature_id=signature_id,
                                                        printed_name=printed_name, note=note)
        completed = [s for s in completed if s not in queue]

    remaining = [s for s in request.stages if s != "S0" and s not in completed]
    writer.resume = None
    if not remaining:
        writer.flush(current_stage=stage, status="COMPLETED")
        return {"campaign_id": campaign_id, "stage": stage, "action": action, "status": "COMPLETED"}

    for pending in remaining:  # a retried/continued stage starts from PENDING again in the monitor
        writer.stage_status(pending, "PENDING")
    writer.flush(current_stage=remaining[0], status="RUNNING")

    continuation = replace(request, stages=remaining, cpf_uri=cpf_uri, cpf_sha256=cpf_sha)
    executor = LocalExecutor(engine=_executor_engine(engine, read_root=read_root, tenant_id=tenant_id, memo=None),
                             writer=writer, approved_gates={stage} if action == "approve" else set(),
                             engine_key=engine_key(engine))

    def _continue() -> None:
        executor.run(continuation, original=request, completed_before=completed)

    if background:
        import threading

        threading.Thread(target=_continue, daemon=True).start()
    else:
        _continue()
    return {"campaign_id": campaign_id, "stage": stage, "action": action, "status": "RUNNING",
            "remaining_stages": remaining}


def _start_cycle(writer: CampaignArtifactWriter, request: CampaignRequest, diagnosis: dict, action: str, payload: dict, *,
                 cpf_uri: str, cpf_sha: str, signature_id: str, printed_name: str, note: str):
    """Plan §12.4: a learn or new-evidence decision starts cycle c+1. Returns the campaign request the cycle runs
    under (the deviated MAP for learn), the CPF it starts from, and the stages it re-runs (the queue)."""
    from modeler_orchestrator.feedback import PROMPTED_BY_S5, learn_map, new_evidence_cpf

    failing = [f["study_id"] for f in diagnosis.get("failing", [])]
    writer.cycle += 1
    cycle = writer.cycle
    order = {s: i for i, s in enumerate(STAGE_LABELS)}
    if action == "learn":
        map_uri, map_sha, deviation = learn_map(
            request.map_uri, _learn_studies(diagnosis, payload), diagnosis, cycle=cycle, reason=note,
            signature_id=signature_id, printed_name=printed_name or "reviewer", beyond_cap=str(payload.get("beyond_cap", "")))
        entry = min(deviation["stages"].values(), key=order.__getitem__)
        writer.feedback.append({**deviation, "action": "learn", "failing": failing, "note": note})
        writer.ledger.event(stage="S5", kind="learn", reason=deviation["statement"], cycle=cycle)
        writer.stage_notes("S5", [f"cycle {cycle}: {deviation['statement']}"])
        request = replace(request, map_uri=map_uri, map_sha256=map_sha, cycle=cycle)
    else:
        value, unit = float(payload["value"]), payload.get("unit") or None
        reference = str(payload.get("reference", ""))
        new_uri, new_sha = new_evidence_cpf(cpf_uri, parameter=str(payload["parameter"]), value=value, unit=unit,
                                            reference=reference, cycle=cycle, campaign_id=request.campaign_id, failing=failing)
        reason = (f"{payload['parameter']} = {value:g}{' ' + unit if unit else ''} measured ({reference}), "
                  f"{PROMPTED_BY_S5} ({', '.join(failing)})")
        writer.record_change("S5", "new evidence", reason, (cpf_uri, cpf_sha), (new_uri, new_sha))
        writer.feedback.append({"cycle": cycle, "action": "new_evidence", "parameter": payload["parameter"], "value": value,
                                "unit": unit, "reference": reference, "failing": failing, "signature_id": signature_id,
                                "note": note})
        writer.stage_notes("S5", [(f"cycle {cycle}: S5 re-judges the same external studies after {reason}; the verdict "
                                   "needs a model-risk review (D-06)")])
        cpf_uri, cpf_sha = new_uri, new_sha
        entry = "S1"
        request = replace(request, cycle=cycle)
    # learn refits the affected stage only (MS-01 §6.6), then SJ re-judges and refines every internal study, S4 and
    # S5 follow (plan §12.4: [S(k), SJ, S4, S5]); new evidence re-runs the whole chain from S1
    skipped = set(FIT_STAGES) - {entry} if action == "learn" else set()
    queue = [s for s in request.stages if s != "S0" and order.get(s, 99) >= order[entry] and s not in skipped]
    return request, cpf_uri, cpf_sha, queue


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
    runtime_env().check_production()
    spec = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    read_root = spec.get("read_root") or runtime_env().read_root
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
