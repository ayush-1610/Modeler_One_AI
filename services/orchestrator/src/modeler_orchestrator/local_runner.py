"""Single-node headless campaign executor — the runner-first, no-Docker execution mode.

Runs the MS-01 stage pipeline (S0 readiness → S1…S5) in-process by calling the **same** campaign activity
functions the Temporal worker calls (`build_round_snapshot`, `prepare_round_job`, `collect_pkml_inputs`,
`run_round`, `evaluate_round`, `diagnose_round`, `choose_action`) and the same fit planning/assessment
(`plan_jobs`, `assess_round`), driving the engine through the same subprocess boundary
(`modeler_engine.runner.EngineRunner` + `LocalObjectStore`, i.e. `Rscript run_job.R`). The scientific work is
single-sourced with the Temporal path; only the loop control (`StageLoopWorkflow` / `ModelingCampaignWorkflow`)
is re-expressed here, without Temporal signals, timers or a cluster.

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
)
from modeler_orchestrator.campaign_activities import (
    build_round_snapshot,
    choose_action,
    collect_pkml_inputs,
    diagnose_round,
    evaluate_round,
    plan_campaign,
    prepare_round_job,
    run_round,
)
from modeler_orchestrator.fitting_activities import assess_round as assess_fit_round
from modeler_orchestrator.fitting_activities import plan_jobs

# One callable dispatches an engine job to a manifest — the real EngineRunner.run in production, a stub in tests.
EngineRun = Callable[[EngineJob], EngineManifest]

STAGE_LABELS = {
    "S0": "Readiness", "S1": "IV disposition", "S2": "Oral fasted",
    "S3": "Formulation / fed", "S4": "Internal validation", "S5": "External validation",
}
# Stages that stop the campaign when a stage ends there.
_STOP_STATUSES = ("ESCALATED", "ABORTED", "FAILED")
_DEFAULT_STAGE_BUDGET_S = 1800
# The decision options MS-01 §4 offers on any stage escalation (mirrors the escalations API / review inbox).
# Every one of them resumes or ends the stage, so every one is an approval and carries a Part 11 signature —
# matching `escalations.decision_options()`, which requires the "Approved" meaning for all three.
_ESCALATION_OPTIONS = [
    {"id": "retry", "label": "Retry the stage", "requiresSignature": True},
    {"id": "accept_best", "label": "Accept the best round", "requiresSignature": True},
    {"id": "abort", "label": "Abort the stage", "requiresSignature": True},
]


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
    _started: float = field(default_factory=time.monotonic)
    _rounds: dict[str, list[dict]] = field(default_factory=dict)
    _status: dict[str, str] = field(default_factory=dict)
    _gof: list[dict] = field(default_factory=list)

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
        writer._gof = list(campaign.get("gof", []))
        writer._started = time.monotonic() - float(campaign.get("elapsedSeconds", 0))
        return writer

    def _elapsed(self) -> int:
        return int(time.monotonic() - self._started)

    def stage_status(self, stage: str, status: str) -> None:
        self._status[stage] = status

    def add_round(self, stage: str, round_index: int, action: str, evaluation: RoundEvaluation) -> None:
        auc = evaluation.metrics.get("AUC", {}).get("gmfe")
        cmax = evaluation.metrics.get("Cmax", {}).get("gmfe")
        verdict = "passed" if evaluation.gate_passed else ("improved" if action != "baseline" else "no pass")
        self._rounds[stage].append({
            "round": round_index, "action": action,
            "aucGmfe": round(auc, 3) if auc is not None else None,
            "cmaxGmfe": round(cmax, 3) if cmax is not None else None,
            "verdict": verdict,
        })

    def set_gof(self, series: list[dict]) -> None:
        if series:
            self._gof = series

    def flush(self, *, current_stage: str, status: str) -> None:
        self.store.upsert_campaign(self.tenant_id, {
            "id": self.campaign_id, "project": self.project, "compound": self.compound,
            "question": self.question, "modelRisk": self.model_risk,
            "budgetSeconds": self.budget_seconds, "elapsedSeconds": self._elapsed(),
            "currentStage": current_stage, "status": status,
            "stages": [
                {"stage": s, "label": STAGE_LABELS.get(s, s), "status": self._status[s], "rounds": self._rounds[s]}
                for s in self.stages
            ],
            "gof": self._gof,
            "resume": self.resume,
        })

    def record_escalation(self, stage: str, reason: str, findings: list[str]) -> None:
        evidence = "; ".join(findings) if findings else f"Stage {stage} escalated ({reason})."
        self.store.upsert_escalation(self.tenant_id, {
            "id": f"{self.campaign_id}-{stage}", "campaignId": self.campaign_id, "stage": stage,
            "reasonCode": (reason or "ESCALATED").upper(), "evidence": evidence, "options": _ESCALATION_OPTIONS,
        })


@dataclass
class LocalExecutor:
    """Runs a whole campaign in-process against an injected engine dispatcher, writing live monitor artifacts."""

    engine: EngineRun
    writer: CampaignArtifactWriter | None = None

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
            if self.writer:
                self.writer.stage_status(stage, "RUNNING")
                self.writer.flush(current_stage=stage, status="RUNNING")
            try:
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
            )
            rounds_run = round_index
            run_result, evaluation, diagnosis, choice = self._run_round(ctx)
            cpf_uri, cpf_sha = run_result.cpf_uri, run_result.cpf_sha256
            best_uri, best_sha = cpf_uri, cpf_sha

            if self.writer:
                self.writer.add_round(stage, round_index, pending_action or "baseline", evaluation)
                self.writer.set_gof(_gof_series(run_result.results_uri, request.observed_uri))
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

    def _run_round(self, ctx: RoundContext) -> tuple[RoundRunResult, RoundEvaluation, RoundDiagnosis, object]:
        build = build_round_snapshot(ctx)
        manifest: EngineManifest | None = None
        if build.snapshot_uri != ctx.cpf_uri:
            manifest = self.engine(prepare_round_job(ctx, build))

        fit_outcome = None
        if build.needs_fit and build.fit_request is not None and manifest is not None:
            pkml = collect_pkml_inputs(manifest)
            if pkml:
                fit_outcome = self._run_fit(replace(build.fit_request, model_inputs=pkml))

        run_result = run_round(RoundRun(context=ctx, build=build, fit_outcome=fit_outcome, manifest=manifest))
        evaluation = evaluate_round(ctx, run_result)
        diagnosis = RoundDiagnosis()
        choice = None
        if not evaluation.gate_passed:
            diagnosis = diagnose_round(ctx, evaluation)
            if not diagnosis.escalate:
                choice = choose_action(ctx, diagnosis)
        return run_result, evaluation, diagnosis, choice

    def _run_fit(self, fit_request) -> object:
        """Reproduce FitRoundWorkflow without Temporal: plan the multistart, run each start on the engine,
        assess. Starts run sequentially (the single-node engine already parallelises PI internally)."""
        jobs = plan_jobs(fit_request)
        manifests = [self.engine(job) for job in jobs]
        return assess_fit_round(fit_request, jobs, manifests, deadline_reached=False)


def run_campaign(
    request: CampaignRequest, *, read_root: str, project: str, question: str = "", model_risk: str = "medium",
    budget_seconds: int | None = None, engine: EngineRun | None = None,
) -> CampaignOutcome:
    """Run a campaign to completion single-node, writing live monitor artifacts under ``read_root``."""
    total_budget = budget_seconds or (sum(request.stage_budgets_seconds.values()) or 3600)
    writer = CampaignArtifactWriter(
        store=FileWriteStore(read_root), tenant_id=request.tenant_id, campaign_id=request.campaign_id,
        project=project, compound=request.compound, question=question, model_risk=model_risk,
        budget_seconds=total_budget, stages=list(request.stages),
    )
    writer.flush(current_stage=request.stages[0], status="RUNNING")
    return LocalExecutor(engine=engine or default_engine(), writer=writer).run(request)


# MS-01 §4 decisions a reviewer may take on an escalated stage.
ESCALATION_ACTIONS = ("retry", "accept_best", "abort")


def resolve_escalation(
    *, read_root: str, tenant_id: str, campaign_id: str, stage: str, action: str,
    engine: EngineRun | None = None, background: bool = True,
) -> dict:
    """Apply a signed review-inbox decision to a single-node campaign (MS-01 §4).

    ``abort``       — the stage is abandoned and the campaign ends there.
    ``accept_best`` — the best CPF found so far is accepted and the remaining stages continue.
    ``retry``       — the stage runs again from the CPF it escalated with (e.g. after new data or a wider bound).

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
    executor = LocalExecutor(engine=engine or default_engine(), writer=writer)

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
