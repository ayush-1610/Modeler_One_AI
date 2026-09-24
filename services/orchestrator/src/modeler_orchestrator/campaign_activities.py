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
    StagePlan,
    StageRequest,
)
from modeler_orchestrator.campaign_store import CampaignStore

# The round simulates one built snapshot (a few small simulations) on the small engine class.
ROUND_RESOURCE_CLASS = "s"
# Canonical result the engine writes and evaluate_round reads: {"profiles": {study_id: {times_min, concentrations}}}.
ROUND_PROFILES_NAME = "profiles.json"
# The name the round's snapshot is given as an engine input. run_job.R's simulate task reads it by this name, and
# PK-Sim names every exported model after it: "<input stem>-<simulation>.pkml". The fit spec must reference
# exactly those names, or the parameter identification cannot find its models.
ROUND_SNAPSHOT_INPUT = "snapshot.json"


def exported_pkml_name(simulation: str) -> str:
    """The file name the engine exports a round simulation's model under (see ROUND_SNAPSHOT_INPUT)."""
    return f"{Path(ROUND_SNAPSHOT_INPUT).stem}-{simulation}.pkml"
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
    """The text of a local ``file://`` document, or None when it is not a loadable local file.

    Callers treat None as "not available here" and degrade gracefully, so a missing file must not raise."""
    path = _local_path(uri)
    if path is None or not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


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
    from pbpk_domain.cpf import CPF

    cpf = CPF.model_validate_json(text)
    system = _round_system(request, cpf)
    if system is not None:
        # every compound of the system is simulated, so each must be ready (MS-01 §2.2 per compound)
        outcomes = [(c.compound, plan_campaign_cpf(c)) for c in system.compounds]
        return S0Readiness(ready=all(r.ready for _n, r in outcomes),
                           findings=[f"{name}: {f}" for name, r in outcomes for f in r.findings])
    return plan_campaign_cpf(cpf)


def plan_campaign_cpf(cpf) -> S0Readiness:
    """S0 readiness of one compound's CPF."""
    from pbpk_domain.cpf import check_completeness
    from pbpk_domain.cpf.build import missing_expression_profiles, unplaceable_parameters

    report = check_completeness(cpf)
    findings = list(report.missing)
    # A pathway the CPF names but the builder cannot place would be silently absent from every simulation.
    unplaced = unplaceable_parameters(cpf) if report.ready else ()
    for pid in unplaced:
        findings.append(f"{pid} cannot be placed in the model (no engine binding the builder supports): the "
                        "simulation would run without this pathway")
    # MS-01 §S0: every enzyme/transporter a process names must have an expression profile, or the process
    # silently eliminates nothing on the engine.
    for molecule in missing_expression_profiles(cpf):
        findings.append(f"no expression profile for {molecule}: its processes cannot act in PK-Sim "
                        "(harvest it from an OSP reference model into the expression library)")
    return S0Readiness(ready=report.ready and not unplaced and not missing_expression_profiles(cpf), findings=findings)


@activity.defn(name="plan_stage")
def plan_stage(request: StageRequest) -> StagePlan:
    """Decide what a stage does from the signed MAP before its first round (MS-01 §4).

    S1–S3 are fit loops, S4/S5 simulate the final CPF once and judge it. A stage with no scenario is skipped
    with its documented reason (e.g. no oral study -> S2 skipped, decision tree §6.2; no external study -> S5
    not achievable) instead of running a round that has nothing to simulate and escalating on it."""
    from pbpk_domain.campaign.map import FIT_STAGES, VALIDATION_STAGES, MapDocument, stage_coverage

    kind = "validate" if request.stage in VALIDATION_STAGES else "fit" if request.stage in FIT_STAGES else "readiness"
    map_text = _load_local_text(request.map_uri) if request.map_uri else None
    if map_text is None:
        # Without a loadable MAP the stage cannot be planned here; run it and let the round report why.
        return StagePlan(stage=request.stage, kind=kind, notes=["MAP not locally loadable; stage not pre-planned"])
    coverage = stage_coverage(MapDocument.model_validate_json(map_text), request.stage)
    return StagePlan(stage=request.stage, kind=coverage.kind, studies=list(coverage.studies),
                     skip_reason=coverage.skip_reason, notes=list(coverage.notes))


def _round_system(ctx, cpf):
    """The round's model system with the parent's current (possibly fitted) CPF, or None for one compound."""
    text = _load_local_text(ctx.system_uri) if getattr(ctx, "system_uri", "") else None
    if text is None:
        return None
    from pbpk_domain.system import ModelSystem, with_cpf

    return with_cpf(ModelSystem.model_validate_json(text), cpf)


def _round_stem(ctx: RoundContext) -> str:
    """The round's artifact name; a post-fit re-simulation gets its own, so it never overwrites the main pass."""
    return f"{ctx.campaign_id}-{ctx.stage}-r{ctx.round_index}" + (f"-{ctx.phase}" if ctx.phase else "")


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
    from pbpk_domain.campaign.round_build import protocol_name, scenarios_for_stage
    from pbpk_domain.cpf.formulations import FormulationError, resolve_formulation_name
    from pbpk_domain.fit_spec import FitSimulation, FitSpecError, build_fit_spec, pi_observed, resolve_fit_ids
    from pbpk_domain.units import is_molar

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
        if not scenario.gated:
            continue  # a model system's metabolite / sum study is reported, not fitted (phase 1)
        profile = (observed_doc or {}).get(scenario.study_id, {}).get("profile")
        if not profile or mol_weight is None:
            continue
        # Observed profiles are stored in the engine's units (µmol/l, `pbpk_domain.units`); declare the molar
        # dimension, or ospsuite reads µmol/l as a mass concentration and the fit is meaningless or fails.
        dimension = "Concentration (molar)" if is_molar(profile["unit"]) else "Concentration (mass)"
        formulation = None
        if scenario.route == "oral" and scenario.formulation not in ("solution", "suspension"):
            try:
                formulation, _ = resolve_formulation_name(cpf, scenario.formulation_name)
            except FormulationError:
                formulation = None
        simulations.append(FitSimulation(
            study_id=scenario.study_id, pkml=exported_pkml_name(scenario.study_id),
            output_path=scenario.analyte_output or output_path,
            observed=pi_observed(scenario.study_id, profile["times"], profile["values"], time_unit=profile["time_unit"],
                                 unit=profile["unit"], mol_weight=mol_weight, dimension=dimension,
                                 sd=profile.get("sd"), lloq=profile.get("lloq")),
            protocol=protocol_name(scenario.study_id), formulation=formulation,
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
    """The per-simulation pkml the engine exported (``snapshot-<Sim>.pkml``, `exported_pkml_name`), as the fit's
    model inputs.

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

    from pbpk_domain.campaign.map import VALIDATION_STAGES, MapDocument
    from pbpk_domain.campaign.round_build import ScenarioBuildError, build_stage_snapshot
    from pbpk_domain.cpf import CPF

    cpf = CPF.model_validate_json(cpf_text)
    map_doc = MapDocument.model_validate_json(map_text)
    try:
        # A validation stage judges every study it can build and names the rest; a fitting stage must not
        # silently fit to fewer studies than the MAP planned, so it fails on any unbuildable one.
        # S6 predicts from the internal studies (S4's scenarios) with the final CPF.
        scenario_stage = "S4" if ctx.stage == "S6" else ctx.stage
        stage = build_stage_snapshot(cpf, list(map_doc.scenarios), stage=scenario_stage, seed=ctx.seed,
                                     skip_unbuildable=scenario_stage in VALIDATION_STAGES, system=_round_system(ctx, cpf))
    except ScenarioBuildError as exc:
        echoed = _echo(str(exc))
        echoed.notes = [str(exc)]
        return echoed

    out = _local_path(ctx.cpf_uri).parent / "snapshots" / f"{_round_stem(ctx)}.json"
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
        snapshot_uri=out.as_uri(), snapshot_sha256=snapshot_sha, needs_fit=needs_fit, fit_request=fit_request,
        notes=list(stage.notes),
    )


@activity.defn(name="prepare_round_job")
def prepare_round_job(ctx: RoundContext, build: RoundBuild) -> EngineJob:
    """Build the engine job that simulates the round's snapshot. The engine writes the canonical profile
    bundle (`profiles.json`) plus the raw OSP CSVs under the job's outputs prefix. On a fit round it also
    exports one pkml per simulation (`export_pkml`) — the per-simulation model the parameter identification
    fits — which `collect_pkml_inputs` turns into the fit's model inputs."""
    root = os.environ.get("MODELER_OBJECT_STORE_URI", "file:///tmp/modeler-object-store").rstrip("/")
    round_dir = f"r{ctx.round_index}" + (f"-{ctx.phase}" if ctx.phase else "")
    return EngineJob(
        job_id=_round_stem(ctx),
        tenant_id=ctx.tenant_id,
        task="simulate",
        inputs=[EngineInput(name=ROUND_SNAPSHOT_INPUT, uri=build.snapshot_uri, sha256=build.snapshot_sha256)],
        outputs_uri=f"{root}/tenants/{ctx.tenant_id}/campaigns/{ctx.campaign_id}/{ctx.stage}/{round_dir}",
        # pkml per simulation: the fit's models on a fit round, and the VPC's models on a stage the VPC gates.
        options={"export_pkml": True} if ((build.needs_fit and build.fit_request is not None) or _vpc_stage(ctx.stage)
                                          or ctx.stage == "S6") else {},
        timeout_s=int(max(60.0, ctx.deadline_seconds)) if ctx.deadline_seconds else 600,
    )


def _vpc_stage(stage: str) -> bool:
    from pbpk_domain.campaign.vpc import VPC_STAGES

    return stage in VPC_STAGES


@activity.defn(name="prepare_vpc_jobs")
def prepare_vpc_jobs(ctx: RoundContext, manifest: EngineManifest) -> list[EngineJob]:
    """One population job per study the round simulated (MS-01 VPC): the study's exported model run across 100
    virtual individuals from its demographics, seed recorded, returning the 5/50/95 % band (``vpc.json``)."""
    from pbpk_domain.campaign.map import MapDocument
    from pbpk_domain.campaign.round_build import scenarios_for_stage
    from pbpk_domain.campaign.vpc import VPC_INDIVIDUALS, VPC_PERCENTILES

    map_text = _load_local_text(ctx.map_uri) if ctx.map_uri else None
    if map_text is None or manifest is None:
        return []
    map_doc = MapDocument.model_validate_json(map_text)
    pkml = {Path(o.name).name: o for o in manifest.outputs if o.name.endswith(".pkml")}
    cpf_text = _load_local_text(ctx.cpf_uri)
    compound = json.loads(cpf_text)["compound"] if cpf_text else ""
    root = os.environ.get("MODELER_OBJECT_STORE_URI", "file:///tmp/modeler-object-store").rstrip("/")
    jobs = []
    for scenario in scenarios_for_stage(map_doc.scenarios, ctx.stage):
        model = pkml.get(exported_pkml_name(scenario.study_id))
        if model is None or not scenario.gated:
            continue
        jobs.append(EngineJob(
            job_id=f"{_round_stem(ctx)}-vpc-{scenario.study_id}", tenant_id=ctx.tenant_id, task="population",
            inputs=[EngineInput(name="simulation.pkml", uri=model.uri, sha256=model.sha256)],
            outputs_uri=f"{root}/tenants/{ctx.tenant_id}/campaigns/{ctx.campaign_id}/{ctx.stage}/"
                        f"r{ctx.round_index}{'-' + ctx.phase if ctx.phase else ''}/vpc/{scenario.study_id}",
            options={
                "population": {
                    "population": scenario.population, "number_of_individuals": VPC_INDIVIDUALS,
                    "proportion_of_females": 100 if scenario.sex == "FEMALE" else 0,
                    "age_min": scenario.vpc_age_min, "age_max": scenario.vpc_age_max,
                },
                "seed": ctx.seed,
                "vpc": {"output_path": scenario.analyte_output or PLASMA_OUTPUT_PATH.format(compound=compound),
                        "percentiles": list(VPC_PERCENTILES)},
            },
            timeout_s=int(max(120.0, ctx.deadline_seconds)) if ctx.deadline_seconds else 900,
        ))
    return jobs


@activity.defn(name="evaluate_vpc")
def evaluate_vpc(ctx: RoundContext, evaluation: RoundEvaluation, manifests: list[EngineManifest]) -> RoundEvaluation:
    """Add the VPC to a round's evaluation: coverage of each study's observed points by its 5–95 % band; the gate
    needs every study at ≥ 80 % (MS-01 S1/S2). Metrics gain ``vpc`` per study; a failing study is a finding."""
    from pbpk_domain.campaign.vpc import VPC_GATE_STAGES, VPC_MIN_COVERAGE, coverage

    gating = ctx.stage in VPC_GATE_STAGES

    observed_doc = _load_local_json(ctx.observed_uri) if ctx.observed_uri else {}
    results: dict[str, dict] = {}
    findings = list(evaluation.findings)
    for manifest in manifests:
        band_file = next((o for o in manifest.outputs if Path(o.name).name == "vpc.json"), None)
        study_id = manifest.job_id.rsplit("-vpc-", 1)[-1]
        band = _load_local_json(band_file.uri) if band_file else None
        profile = ((observed_doc or {}).get(study_id) or {}).get("profile")
        if not band or not profile:
            findings.append(f"{study_id}: VPC not available ({'no band' if not band else 'no observed profile'})")
            results[study_id] = {"coverage": None, "passes": False}
            continue
        factor = minutes_per_unit(profile.get("time_unit", "min"))
        cov = coverage(study_id, band, [t * factor for t in profile["times"]], profile["values"], lloq=profile.get("lloq"))
        results[study_id] = {"coverage": round(cov.fraction, 3), "points": cov.n_points, "inside": cov.n_inside,
                             "individuals": cov.individuals, "passes": cov.passes,
                             "band": {"times_min": band["times_min"], "p5": band["percentiles"]["5"],
                                      "p50": band["percentiles"]["50"], "p95": band["percentiles"]["95"]}}
        if not cov.passes:
            flag = "" if gating else f" — reported, not gated at {ctx.stage} (MS-01 §4)"
            findings.append(f"{study_id} VPC: {cov.n_inside}/{cov.n_points} observed points inside the 5–95 % band "
                            f"({cov.fraction:.0%}, gate ≥ {VPC_MIN_COVERAGE:.0%}){flag}")
    vpc_ok = (bool(results) and all(r["passes"] for r in results.values())) or not gating
    metrics = dict(evaluation.metrics) | {"vpc": results}
    return RoundEvaluation(gate_passed=evaluation.gate_passed and vpc_ok, acceptable=evaluation.acceptable and vpc_ok,
                           metrics=metrics, findings=findings)


def minutes_per_unit(unit: str) -> float:
    from pbpk_domain.units import minutes_per

    return minutes_per(unit)


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
        best = next(s for s in fit_outcome.starts if s.start_index == fit_outcome.best_start_index)
        updated = apply_fit_estimates(CPF.model_validate_json(cpf_text), estimates, stage=ctx.stage,
                                      run=f"{ctx.campaign_id}-{ctx.stage}-r{ctx.round_index}",
                                      uncertainty=getattr(best, "uncertainty", None))
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
    from pbpk_domain.units import minutes_per

    map_doc = MapDocument.model_validate_json(map_text)
    role_of = {s.study_id: ("fitting" if s.assignment == "INTERNAL" else "validation") for s in map_doc.studies}
    # External validation judges fasted and fed as separate groups (MS-01 §4 S5, §8); elsewhere one group.
    food_of = {s.study_id: s.food_state for s in map_doc.scenarios if s.stage == ctx.stage}
    group_of = food_of if ctx.stage == "S5" else {}

    # A model system's study is read on its analyte's curve (the engine bundle keeps every selected output by path);
    # one that is not gated (a metabolite or sum, phase 1) is reported beside the gate, not in it.
    stage_scenarios = {s.study_id: s for s in map_doc.scenarios if s.stage == ctx.stage}
    reported: set[str] = set()
    not_read: list[str] = []
    simulated = []
    for study_id, prof in profiles_doc["profiles"].items():
        scenario = stage_scenarios.get(study_id)
        concentrations = prof.get("concentrations", [])
        if scenario is not None and scenario.analyte_output and scenario.analyte_output != prof.get("path"):
            output = (prof.get("outputs") or {}).get(scenario.analyte_output)
            if output is None or output.get("unit") != prof.get("unit"):
                not_read.append(f"{study_id}: the engine returned no {scenario.analyte_output!r} in "
                                f"{prof.get('unit')}; not evaluated")
                continue
            concentrations = output["concentrations"]
        if scenario is not None and not scenario.gated:
            reported.add(study_id)
        simulated.append(SimulatedProfile(
            study_id=study_id, role=role_of.get(study_id, "validation"),
            times=prof.get("times_min", []), concentrations=concentrations, group=group_of.get(study_id, ""),
        ))
    observed_doc = _load_local_json(ctx.observed_uri) if ctx.observed_uri else {}
    def _window(pk: dict) -> tuple[float | None, float | None]:
        """The sampled interval, so the prediction is reduced over the same interval as the observation."""
        profile = pk.get("profile") or {}
        times = profile.get("times") or []
        if not times:
            return None, None
        # Simulated times are minutes; observed profiles are stored canonical (minutes) since campaign:prepare
        # normalises them, but convert defensively so an hours-based profile is never cut at the wrong time.
        factor = minutes_per(profile.get("time_unit", "min"))
        return min(times) * factor, max(times) * factor

    def _sample_times(pk: dict) -> tuple[float, ...] | None:
        profile = pk.get("profile") or {}
        times = profile.get("times") or []
        if not times:
            return None
        factor = minutes_per(profile.get("time_unit", "min"))
        return tuple(float(t) * factor for t in times)

    infusion = {s.study_id: s.infusion_time_min for s in map_doc.scenarios if s.route.startswith("iv")}
    observed = {}
    for study_id, pk in (observed_doc or {}).items():
        t_first, t_last = _window(pk)
        values = (pk.get("profile") or {}).get("values")
        observed[study_id] = ObservedPK(auc=pk.get("auc"), cmax=pk.get("cmax"), tmax=pk.get("tmax"),
                                        thalf=pk.get("thalf"), t_first=t_first, t_last=t_last,
                                        sample_times=_sample_times(pk),
                                        sample_values=tuple(float(v) for v in values) if values else None,
                                        infusion_time=infusion.get(study_id))

    assessment = assess_round(simulated, observed, model_risk=map_doc.model_risk, reported=frozenset(reported))
    activity.logger.info(
        "evaluate_round %s %s round %d: gate=%s studies=%d",
        ctx.campaign_id, ctx.stage, ctx.round_index, assessment.gate_passed, len(assessment.studies),
    )
    return RoundEvaluation(
        gate_passed=assessment.gate_passed, acceptable=assessment.gate_passed,
        metrics=assessment.metrics, findings=list(assessment.findings) + not_read,
    )


def _ratio(predicted: float | None, observed: float | None) -> float | None:
    return predicted / observed if predicted and observed and observed > 0 else None


def _fittable_candidates(cpf, candidates: tuple[str, ...], stage: str) -> tuple[str, ...]:
    """Keep only the stage's fit candidates this CPF can actually fit.

    A candidate that resolves to no parameter (a hepatic enzyme clearance on a renally cleared compound), or
    to one with no bounds, or one whose fit policy does not permit this stage, or one with no harvested engine
    path, cannot change anything. Offering it anyway burns a round on a no-op and can exhaust the round budget
    before the candidate that would have worked is ever tried.
    """
    from pbpk_domain.cpf.formulations import weibull_parameter_path
    from pbpk_domain.fit_spec import resolve_fit_ids
    from pbpk_domain.pksim_paths import ParameterPathError, pksim_parameter_path

    keep: list[str] = []
    for target in candidates:
        for pid in resolve_fit_ids(cpf, target):
            record = cpf.get(pid)
            if record is None or record.value is None:
                continue
            policy = record.fit_policy
            if policy is not None and policy.stage and stage not in policy.stage:
                continue  # MS-01: this parameter may not be fitted at this stage
            if policy is None and record.plausibility is None:
                continue  # nothing to bound the fit with
            if weibull_parameter_path(pid, protocol="<protocol>") is None:  # formulation paths are per simulation
                try:
                    pksim_parameter_path(record, compound=cpf.compound)
                except ParameterPathError:
                    continue  # no engine path: the fit could not be applied even if it ran
            keep.append(target)
            break
    return tuple(keep)


def _off(ratio: float | None, thresholds: dict) -> bool:
    """A predicted/observed ratio outside the ruleset's diagnostic band (ratio_low .. ratio_high)."""
    return ratio is not None and not float(thresholds["ratio_low"]) <= ratio <= float(thresholds["ratio_high"])


@activity.defn(name="diagnose_round")
def diagnose_round(ctx: RoundContext, evaluation: RoundEvaluation) -> RoundDiagnosis:
    """Map the round's evidence to permitted actions with the deterministic diagnostics ruleset (MS-01 §5).

    Builds each study's PK residuals from the evaluation metrics and the MAP scenario (route, dose), then
    calls `pbpk_domain.diagnostics.diagnose` with the stage's permitted candidates/branches, skipping actions
    already tried. Evidence that needs a profile-shape or fit analysis not yet wired (early-phase residuals,
    secondary peaks, at-bound / correlation / optimiser-agreement signals) simply does not fire; the
    PK-ratio-driven rules (clearance, absorption rate, dose dependence) are active, and on the post-fit pass the
    fit's optimiser evidence (parameters at a bound, correlated pairs, start agreement). With no MAP, or no
    rule matching, the round escalates rather than inventing an action."""
    map_text = _load_local_text(ctx.map_uri) if ctx.map_uri else None
    if map_text is None:
        return RoundDiagnosis(evidence=[], permitted_actions=[], escalate=True,
                              escalation_reason="diagnostics: MAP not locally loadable (object-store I/O pending)")

    from pbpk_domain.campaign.map import STAGE_PLAN, MapDocument
    from pbpk_domain.diagnostics import FitSignals, StudyResidual, diagnose, load_diag_ruleset

    map_doc = MapDocument.model_validate_json(map_text)
    plan = STAGE_PLAN.get(ctx.stage, {})
    candidates = tuple(plan.get("fit_candidates", ()))
    cpf_text = _load_local_text(ctx.cpf_uri)
    if cpf_text is not None:
        from pbpk_domain.cpf import CPF

        cpf = CPF.model_validate_json(cpf_text)
        usable = _fittable_candidates(cpf, candidates, ctx.stage)
        if usable != candidates:
            activity.logger.info(
                "diagnose_round %s %s: fit candidates usable for this CPF: %s (dropped %s)",
                ctx.campaign_id, ctx.stage, ",".join(usable) or "none",
                ",".join(c for c in candidates if c not in usable) or "none",
            )
        candidates = usable
    scenarios = {s.study_id: s for s in map_doc.scenarios}
    thresholds = load_diag_ruleset()["thresholds"]
    residuals = [
        StudyResidual(
            study_id=st["study_id"], role=st.get("role", "fitting"),
            route="iv" if (scenarios.get(st["study_id"]) and scenarios[st["study_id"]].route.startswith("iv")) else "oral",
            # a per-kg dose is not comparable with absolute ones in the dose-normalised trend, nor is a phased regimen's
            # first dose (a loading dose then maintenance): left out of it
            dose_mg=(scenarios[st["study_id"]].dose_mg
                     if st["study_id"] in scenarios and not scenarios[st["study_id"]].dose_per_kg
                     and not scenarios[st["study_id"]].dose_phases else None),
            auc_ratio=_ratio(st.get("predicted_auc"), st.get("observed_auc")),
            cmax_ratio=_ratio(st.get("predicted_cmax"), st.get("observed_cmax")),
            tmax_ratio=_ratio(st.get("predicted_tmax"), st.get("observed_tmax")),
            thalf_ratio=_ratio(st.get("predicted_thalf"), st.get("observed_thalf")),
            observed_auc=st.get("observed_auc"), auc_in_limits=st.get("auc_in_limits"),
            early_phase_off=_off(st.get("early_ratio"), thresholds),
            vss_off=_off(st.get("vss_ratio"), thresholds),
        )
        for st in evaluation.metrics.get("studies", [])
    ]
    signals = ctx.fit_signals or {}
    fit = FitSignals(
        at_bound=tuple(signals.get("at_bound") or ()),
        correlated_pairs=tuple(tuple(p) for p in signals.get("correlated_pairs") or () if len(p) == 2),
        starts_agreement=signals.get("starts_agreement"),
    )
    diagnosis = diagnose(
        residuals, stage=ctx.stage, stage_candidates=candidates,
        stage_branches=plan.get("branches", ()), actions_tried=ctx.actions_tried, fit=fit,
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
    plan_stage,
    prepare_vpc_jobs,
    evaluate_vpc,
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
