"""Activities for the campaign workflows (task T-13).

Most steps are wired to real subsystems: `plan_campaign` runs the S0 completeness gate from the CPF,
`build_round_snapshot` regenerates the stage snapshot from the CPF and the MAP's scenarios (T-16 +
`pbpk_domain.campaign.round_build`), `choose_action` picks the first permitted action (the deterministic
fallback the strategist agent in T-15 will refine), and `resume_campaign`/`record_round` read and write
durable, audited campaign state through the persistence layer (T-05) when `MODELER_DATABASE_URL` is set —
resuming past finished stages and appending each round, `evaluate_round` reduces the round's simulated
profiles to PK and judges them against the tier gate (`pbpk_domain.campaign.evaluate` over T-18 NCA +
`acceptance`), and `diagnose_round` maps the round's evidence to permitted actions with the deterministic
diagnostics ruleset (`pbpk_domain.diagnostics`, T-14). The round's snapshot is simulated on the engine: the
workflow schedules `run_engine_job` (task `simulate`) on the engine task queue with the job `prepare_round_job`
builds, and `run_round` finalizes the round by pointing the result at the engine's `profiles.json` (the bundle
`evaluate_round` reads) and applying any fit estimates into a new CPF version. On a fit round `build_round_snapshot`
also assembles the `FitRoundRequest` (parameters resolved to PK-Sim paths, PI spec built against the observed
profiles). On a fit round the simulate step also exports one pkml per simulation, `collect_pkml_inputs` turns
them into the fit's model inputs, and the fitting child runs; run_round then applies the winning estimates.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from temporalio import activity

from modeler_contracts.runs import (
    ActionChoice,
    CampaignRequest,
    EngineInput,
    EngineJob,
    EngineManifest,
    FitParameterBounds,
    FitRoundRequest,
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

# The round simulates one built snapshot (a few small simulations) on the small engine class.
ROUND_RESOURCE_CLASS = "s"
# Canonical result the engine writes and evaluate_round reads: {"profiles": {study_id: {times_min, concentrations}}}.
ROUND_PROFILES_NAME = "profiles.json"
# Fit-round sizing from the engine benchmark (osp-engine-facts): 0.506 s/simulation.
FIT_SECONDS_PER_SIM = 0.506
FIT_EVALUATIONS_PER_START = 40
# The plasma output every simulation selects (matches builder.PLASMA_OUTPUT_PATH).
PLASMA_OUTPUT_PATH = "Organism|PeripheralVenousBlood|{compound}|Plasma (Peripheral Venous Blood)"

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


def _is_log_scale(cpf, param_id: str) -> bool:
    record = cpf.get(param_id)
    return bool(record and record.fit_policy and record.fit_policy.scale.value == "log")


def _build_fit_request(ctx: RoundContext, cpf, map_doc, *, snapshot_stem: str, out_dir: Path) -> FitRoundRequest | None:
    """Assemble the round's FitRoundRequest from the chosen action, the CPF and the observed profiles.

    Returns None (the round then simulates instead of fitting) when there is no fittable parameter, no
    observed profile to fit against, or the spec cannot be built. The pkml model inputs are left empty here
    and filled by the snapshot->pkml conversion step before the fit runs."""
    from pbpk_domain.campaign.round_build import scenarios_for_stage
    from pbpk_domain.fit_spec import FitSimulation, FitSpecError, build_fit_spec, pi_observed, resolve_fit_ids

    target = ctx.pending_action.split(" ", 1)[1] if ctx.pending_action and " " in ctx.pending_action else ""
    fit_ids = list(resolve_fit_ids(cpf, target))
    if not fit_ids:
        activity.logger.info("build_round_snapshot %s %s: no fittable CPF parameter for %r", ctx.campaign_id, ctx.stage, target)
        return None

    # The strategist's bounds are keyed by the (possibly templated) action target; apply them to every
    # concrete parameter that target resolves to. Absent an override, build_fit_spec uses the CPF's policy.
    pending = ctx.pending_bounds_override or {}
    override: dict[str, tuple[float, float]] = {}
    for cid in fit_ids:
        bounds = pending.get(cid) or pending.get(target)
        if bounds and len(bounds) == 2:
            override[cid] = (float(bounds[0]), float(bounds[1]))

    observed_doc = _load_local_json(ctx.observed_uri) if ctx.observed_uri else {}
    mw = cpf.get("phys.mw")
    mol_weight = mw.numeric_value if mw is not None else None
    output_path = PLASMA_OUTPUT_PATH.format(compound=cpf.compound)
    simulations = []
    for scenario in scenarios_for_stage(map_doc.scenarios, ctx.stage):
        profile = (observed_doc or {}).get(scenario.study_id, {}).get("profile")
        if not profile or mol_weight is None:
            continue
        simulations.append(FitSimulation(
            study_id=scenario.study_id, pkml=f"{snapshot_stem}-{scenario.study_id}.pkml", output_path=output_path,
            observed=pi_observed(scenario.study_id, profile["times"], profile["values"], time_unit=profile["time_unit"],
                                 unit=profile["unit"], mol_weight=mol_weight, sd=profile.get("sd"), lloq=profile.get("lloq")),
        ))
    if not simulations:
        activity.logger.info("build_round_snapshot %s %s: no observed profile to fit against", ctx.campaign_id, ctx.stage)
        return None

    try:
        spec = build_fit_spec(cpf, fit_ids, simulations, bounds_override=override or None, seed=ctx.seed)
    except FitSpecError as exc:
        activity.logger.info("build_round_snapshot %s %s: fit spec not built (%s)", ctx.campaign_id, ctx.stage, exc)
        return None

    spec_path = out_dir / f"{snapshot_stem}-pi_spec.json"
    payload = json.dumps(spec, ensure_ascii=False, indent=2).encode("utf-8")
    spec_path.write_bytes(payload)
    bounds = [FitParameterBounds(name=p["name"], lower=p["min"], upper=p["max"], log_scale=_is_log_scale(cpf, p["name"]))
              for p in spec["parameters"]]
    activity.logger.info("build_round_snapshot %s %s round %d: fit request for %s over %d study(ies)",
                         ctx.campaign_id, ctx.stage, ctx.round_index, ",".join(fit_ids), len(simulations))
    return FitRoundRequest(
        round_id=f"{ctx.campaign_id}-{ctx.stage}-r{ctx.round_index}", tenant_id=ctx.tenant_id,
        base_spec_uri=spec_path.as_uri(), base_spec_sha256=hashlib.sha256(payload).hexdigest(),
        parameters=bounds, simulations_per_evaluation=len(simulations), evaluations_per_start=FIT_EVALUATIONS_PER_START,
        seconds_per_simulation=FIT_SECONDS_PER_SIM, cores=int(os.environ.get("MODELER_ENGINE_CORES", "48")),
        budget_seconds=int(max(60.0, ctx.deadline_seconds)) if ctx.deadline_seconds else 3600, seed=ctx.seed, model_inputs=[],
    )


@activity.defn(name="collect_pkml_inputs")
def collect_pkml_inputs(manifest: EngineManifest) -> list[EngineInput]:
    """The per-simulation pkml the engine exported (``<snapshot>-<Sim>.pkml``), as the fit's model inputs.

    The simulate step runs with ``export_pkml`` on a fit round, so its manifest carries one pkml per
    simulation; each becomes an EngineInput named by its bare file name (which matches the pkml names the PI
    spec's `simulations[].pkml` reference). Empty when the engine produced no pkml, so the fit is skipped."""
    return [
        EngineInput(name=Path(o.name).name, uri=o.uri, sha256=o.sha256)
        for o in manifest.outputs if o.name.endswith(".pkml")
    ]


@activity.defn(name="build_round_snapshot")
def build_round_snapshot(ctx: RoundContext) -> RoundBuild:
    """Regenerate the round's snapshot from the CPF and the MAP's scenarios for this stage.

    Loads the CPF and MAP (local `file://` today; the object store lands with the run wiring), builds the
    stage snapshot via `pbpk_domain.campaign.round_build.build_stage_snapshot`, writes it next to the CPF and
    returns its URI and content hash. When the pending action is a fit, it also assembles the round's
    FitRoundRequest (`_build_fit_request`: resolve the parameters, build the PI spec against the observed
    profiles, persist it) — None when nothing is fittable, so the round simulates instead. When the CPF or MAP
    is not locally loadable, or no scenario trains this stage (e.g. the validation stages), the round falls
    back to echoing the CPF so the workflow still advances; the reason is logged."""
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
    # The hash the engine job carries must be of the exact file bytes the engine downloads (dump() writes the
    # pretty PK-Sim form), not the canonical content hash — otherwise the runner's integrity check rejects it.
    snapshot_sha = hashlib.sha256(out.read_bytes()).hexdigest()
    for note in stage.notes:
        activity.logger.info("build_round_snapshot %s %s: %s", ctx.campaign_id, ctx.stage, note)
    fit_request = _build_fit_request(ctx, cpf, map_doc, snapshot_stem=out.stem, out_dir=out.parent) if needs_fit else None
    activity.logger.info(
        "build_round_snapshot %s %s round %d: built %d simulation(s) fit=%s fit_request=%s",
        ctx.campaign_id, ctx.stage, ctx.round_index, len(stage.simulations), needs_fit, fit_request is not None,
    )
    return RoundBuild(
        snapshot_uri=out.as_uri(), snapshot_sha256=snapshot_sha, needs_fit=needs_fit, fit_request=fit_request
    )


@activity.defn(name="prepare_round_job")
def prepare_round_job(ctx: RoundContext, build: RoundBuild) -> EngineJob:
    """Build the engine job that simulates the round's snapshot. The engine writes the canonical profile
    bundle (`profiles.json`) plus the raw OSP CSVs under the job's outputs prefix. On a fit round it also
    exports one pkml per simulation (`export_pkml`) — the per-simulation model the parameter identification
    fits — which `collect_pkml_inputs` turns into the fit's model inputs."""
    root = os.environ.get("MODELER_OBJECT_STORE_URI", "file:///tmp/modeler-object-store").rstrip("/")
    return EngineJob(
        job_id=f"{ctx.campaign_id}-{ctx.stage}-r{ctx.round_index}",
        tenant_id=ctx.tenant_id,
        task="simulate",
        inputs=[EngineInput(name="snapshot.json", uri=build.snapshot_uri, sha256=build.snapshot_sha256)],
        outputs_uri=f"{root}/tenants/{ctx.tenant_id}/campaigns/{ctx.campaign_id}/{ctx.stage}/r{ctx.round_index}",
        options={"export_pkml": True} if (build.needs_fit and build.fit_request is not None) else {},
        timeout_s=int(max(60.0, ctx.deadline_seconds)) if ctx.deadline_seconds else 600,
    )


def _best_estimates(fit_outcome) -> dict[str, float]:
    """The winning start's parameter estimates, or {} when the fit produced none."""
    if fit_outcome is None or fit_outcome.best_start_index is None:
        return {}
    best = next((s for s in fit_outcome.starts if s.start_index == fit_outcome.best_start_index), None)
    return dict(best.estimates) if best and best.estimates else {}


def _apply_round_fit(ctx: RoundContext, fit_outcome) -> tuple[str, str]:
    """Transfer a fit's estimates into a new CPF version written next to the CPF; returns (cpf_uri, sha256).

    Falls back to the unchanged CPF when no estimates were produced or the CPF is not locally loadable."""
    estimates = _best_estimates(fit_outcome)
    cpf_text = _load_local_text(ctx.cpf_uri) if estimates else None
    if not estimates or cpf_text is None:
        return ctx.cpf_uri, ctx.cpf_sha256

    from pbpk_domain.cpf import CPF
    from pbpk_domain.fit_spec import FitSpecError, apply_fit_estimates

    try:
        updated = apply_fit_estimates(CPF.model_validate_json(cpf_text), estimates, stage=ctx.stage,
                                      run=f"{ctx.campaign_id}-{ctx.stage}-r{ctx.round_index}")
    except FitSpecError as exc:
        activity.logger.warning("run_round %s %s round %d: fit not applied (%s)", ctx.campaign_id, ctx.stage, ctx.round_index, exc)
        return ctx.cpf_uri, ctx.cpf_sha256

    payload = updated.model_dump_json().encode("utf-8")
    out = _local_path(ctx.cpf_uri).parent / "cpf" / f"{ctx.campaign_id}-{ctx.stage}-r{ctx.round_index}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(payload)
    activity.logger.info(
        "run_round %s %s round %d: applied %d estimate(s) -> CPF v%d",
        ctx.campaign_id, ctx.stage, ctx.round_index, len(estimates), updated.version,
    )
    return out.as_uri(), hashlib.sha256(payload).hexdigest()


@activity.defn(name="run_round")
def run_round(run: RoundRun) -> RoundRunResult:
    """Finalize the round: apply any fit estimates into a new CPF version, and point the result at the
    engine's `profiles.json` (what `evaluate_round` reads).

    When the round fitted parameters, the winning start's estimates are transferred into a new CPF version
    (status FITTED) carried forward to the next round. When the engine step was skipped (no snapshot was
    built for this stage) or produced no profile bundle, the result points at a marker URI so evaluate
    reports it has nothing to judge rather than a false pass."""
    ctx = run.context
    cpf_uri, cpf_sha = _apply_round_fit(ctx, run.fit_outcome)

    manifest = run.manifest
    if manifest is not None and manifest.status == "SUCCEEDED":
        for output in manifest.outputs:
            if Path(output.name).name == ROUND_PROFILES_NAME:
                activity.logger.info(
                    "run_round %s %s round %d: profiles at %s", ctx.campaign_id, ctx.stage, ctx.round_index, output.uri
                )
                return RoundRunResult(results_uri=output.uri, cpf_uri=cpf_uri, cpf_sha256=cpf_sha)
        activity.logger.warning(
            "run_round %s %s round %d: engine manifest has no %s output", ctx.campaign_id, ctx.stage, ctx.round_index, ROUND_PROFILES_NAME
        )
    return RoundRunResult(results_uri=f"{ctx.cpf_uri}#no-results-r{ctx.round_index}", cpf_uri=cpf_uri, cpf_sha256=cpf_sha)


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
        study_id: ObservedPK(auc=pk.get("auc"), cmax=pk.get("cmax"), tmax=pk.get("tmax"), thalf=pk.get("thalf"))
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


def _ratio(predicted: float | None, observed: float | None) -> float | None:
    return predicted / observed if predicted and observed and observed > 0 else None


@activity.defn(name="diagnose_round")
def diagnose_round(ctx: RoundContext, evaluation: RoundEvaluation) -> RoundDiagnosis:
    """Map the round's evidence to permitted actions with the deterministic diagnostics ruleset (MS-01 §5).

    Builds each study's PK residuals from the evaluation metrics and the MAP scenario (route, dose), then
    calls `pbpk_domain.diagnostics.diagnose` with the stage's permitted candidates/branches, skipping actions
    already tried. Evidence that needs a profile-shape or fit analysis not yet wired (early-phase residuals,
    secondary peaks, at-bound / correlation / optimiser-agreement signals) simply does not fire; the
    PK-ratio-driven rules (clearance, absorption rate, dose dependence) are active now. With no MAP, or no
    rule matching, the round escalates rather than inventing an action."""
    map_text = _load_local_text(ctx.map_uri) if ctx.map_uri else None
    if map_text is None:
        return RoundDiagnosis(evidence=[], permitted_actions=[], escalate=True,
                              escalation_reason="diagnostics: MAP not locally loadable (object-store I/O pending)")

    from pbpk_domain.campaign.map import STAGE_PLAN, MapDocument
    from pbpk_domain.diagnostics import StudyResidual, diagnose

    map_doc = MapDocument.model_validate_json(map_text)
    plan = STAGE_PLAN.get(ctx.stage, {})
    scenarios = {s.study_id: s for s in map_doc.scenarios}
    residuals = [
        StudyResidual(
            study_id=st["study_id"], role=st.get("role", "fitting"),
            route="iv" if (scenarios.get(st["study_id"]) and scenarios[st["study_id"]].route.startswith("iv")) else "oral",
            dose_mg=scenarios[st["study_id"]].dose_mg if st["study_id"] in scenarios else None,
            auc_ratio=_ratio(st.get("predicted_auc"), st.get("observed_auc")),
            cmax_ratio=_ratio(st.get("predicted_cmax"), st.get("observed_cmax")),
            tmax_ratio=_ratio(st.get("predicted_tmax"), st.get("observed_tmax")),
            thalf_ratio=_ratio(st.get("predicted_thalf"), st.get("observed_thalf")),
            observed_auc=st.get("observed_auc"), auc_in_limits=st.get("auc_in_limits"),
        )
        for st in evaluation.metrics.get("studies", [])
    ]
    diagnosis = diagnose(
        residuals, stage=ctx.stage, stage_candidates=plan.get("fit_candidates", ()),
        stage_branches=plan.get("branches", ()), actions_tried=ctx.actions_tried,
    )
    activity.logger.info(
        "diagnose_round %s %s round %d: causes=%s actions=%d escalate=%s",
        ctx.campaign_id, ctx.stage, ctx.round_index, list(diagnosis.causes), len(diagnosis.permitted_actions), diagnosis.escalate,
    )
    return RoundDiagnosis(
        evidence=list(diagnosis.evidence), causes=list(diagnosis.causes),
        permitted_actions=list(diagnosis.permitted_actions),
        escalate=diagnosis.escalate, escalation_reason=diagnosis.reason,
    )


@activity.defn(name="choose_action")
def choose_action(ctx: RoundContext, diagnosis: RoundDiagnosis) -> ActionChoice:
    """Choose the next action from the diagnostics' permitted set via the strategist (T-15).

    The strategist may only choose among `diagnosis.permitted_actions`; with no per-tenant model configured it
    returns the first not-yet-tried permitted action (the deterministic path the workflow uses today). Enabling
    the LLM strategist means passing `decider=strategist.llm_decider(make_llm(policy))` and a `log_step` that
    appends to `agent_steps` — both land when per-tenant agents and that table are wired."""
    from modeler_agents.strategist import StrategyContext, decide

    choice = decide(StrategyContext(
        stage=ctx.stage, permitted_actions=tuple(diagnosis.permitted_actions), actions_tried=tuple(ctx.actions_tried),
        evidence=tuple(diagnosis.evidence), causes=tuple(diagnosis.causes),
    ))
    return ActionChoice(
        action_id=choice.action_id, rationale=choice.rationale,
        parameters_to_fit=list(choice.parameters_to_fit),
        bounds_override={k: list(v) for k, v in choice.bounds_override.items()} if choice.bounds_override else None,
        source=choice.source,
    )


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
    prepare_round_job,
    collect_pkml_inputs,
    run_round,
    evaluate_round,
    diagnose_round,
    choose_action,
    record_round,
]
