"""S6 virtual bioequivalence (T-31 B6 PR 4): the MAP's ``vbe-crossover`` application, run from the final CPF.

1. The trial design (dose, food state, population) is the reference product's own oral single-dose study in the MAP,
   else another oral single-dose study with a CPF formulation; the TEST and reference arms are that scenario with each
   product's CPF formulation (`MapScenario.formulation_name`), built by the round builder like any other simulation.
2. The TEST arm's population job creates K·n individuals (the person's seed) with its own occasion; the reference arm
   loads exactly those individuals (the TEST arm's ``population.csv``) with its own occasion. The occasion seeds are
   derived from the person's seed (2s+1, 2s+2) and recorded.
3. Each arm's ``pk_analyses.csv`` gives AUC_inf and C_max per individual (`pbpk_domain.vbe`), reduced to K trials of
   n subjects, each judged by the 90 % CI of its geometric mean ratio, and the probability of success.

Nothing is defaulted: every input comes from the signed MAP (`MapApplication.problems` is empty, or it is not run).
The result says what it is not yet: validated against observed BE data (the F-304 gate is the next step).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlparse

from modeler_contracts.runs import EngineInput, EngineJob, EngineManifest, RoundContext
from modeler_contracts.runtime import runtime_env
from modeler_orchestrator.campaign_activities import PLASMA_OUTPUT_PATH, ROUND_SNAPSHOT_INPUT, exported_pkml_name

if TYPE_CHECKING:
    from collections.abc import Callable

    from pbpk_domain.campaign.map import MapApplication, MapDocument, MapScenario
    from pbpk_domain.cpf import CPF
    from pbpk_domain.system import ModelSystem

VBE_TEMPLATE = "vbe-crossover"
ARMS = ("test", "reference")


def vbe_application(map_doc: MapDocument) -> MapApplication | None:
    return next((a for a in map_doc.applications if a.template == VBE_TEMPLATE), None)


def design_scenario(map_doc: MapDocument, reference_formulation: str) -> MapScenario | None:
    """The scenario the virtual trial copies: the reference product's own oral single-dose study (a fasted one
    first), else another oral single-dose study given as a CPF formulation."""
    oral = [s for s in map_doc.scenarios
            if s.route == "oral" and s.formulation_name and s.dosing_interval_h is None and not s.dose_phases]
    oral.sort(key=lambda s: (s.formulation_name != reference_formulation, s.food_state != "fasted"))
    return oral[0] if oral else None


def _path(uri: str) -> Path:
    return Path(unquote(urlparse(uri).path))


def _not_run(reason: str, **extra: Any) -> dict:
    return {"status": "NOT_RUN", "reason": reason, **extra}


def _output(manifest: EngineManifest, name: str):
    return next((o for o in manifest.outputs if Path(o.name).name == name), None)


def run_vbe(ctx: RoundContext, engine: Callable[[EngineJob], EngineManifest], *, cpf: CPF, map_doc: MapDocument,
            system: ModelSystem | None = None) -> dict | None:
    """The MAP's VBE application run on the engine, or None when the MAP pins none. A VBE that cannot run says why
    (``status: NOT_RUN``); it never falls back to a default."""
    from pbpk_domain.analysis_templates import load_template, resolved_limits
    from pbpk_domain.campaign.round_build import ScenarioBuildError, build_stage_snapshot
    from pbpk_domain.vbe import VbeError, read_pk_analyses, run_trials

    application = vbe_application(map_doc)
    if application is None:
        return None
    header = {"template": application.template, "template_version": application.template_version,
              "validation": "not validated: the F-304 gate against observed BE data has not run"}
    if problems := application.problems(cpf):
        return {**header, **_not_run("; ".join(problems))}
    template = load_template(application.template)
    inputs = application.inputs
    limits = resolved_limits(template, inputs)
    design = design_scenario(map_doc, inputs["reference_formulation"])
    if design is None:
        return {**header, **_not_run("no oral single-dose study with a CPF formulation in the MAP to take the trial "
                                     "design (dose, food state, population) from")}
    arms = {arm: design.model_copy(update={"study_id": f"vbe-{arm}", "stage": "S6",
                                           "formulation_name": inputs[f"{arm}_formulation"]}) for arm in ARMS}
    seed = int(inputs["seed"])
    occasion_seeds = {"test": 2 * seed + 1, "reference": 2 * seed + 2}
    n_subjects, n_trials = int(inputs["n_subjects"]), int(inputs["n_trials"])
    header |= {"design_study": design.study_id, "dose_mg": design.dose_mg, "food_state": design.food_state,
               "population": design.population, "seed": seed, "occasion_seeds": occasion_seeds,
               "variability": inputs["variability"], "limits_name": inputs.get("limits", "standard"),
               "limits_source": limits.source, "limits_verified": limits.verified,
               "formulations": {arm: inputs[f"{arm}_formulation"] for arm in ARMS}}
    try:
        stage = build_stage_snapshot(cpf, list(arms.values()), stage="S6", seed=ctx.seed, system=system)
    except (ScenarioBuildError, ValueError) as exc:
        return {**header, **_not_run(f"the TEST and reference simulations could not be built: {exc}")}

    out = _path(ctx.cpf_uri).parent / "snapshots" / f"{ctx.campaign_id}-S6-vbe.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    stage.snapshot.dump(out)
    base = f"{runtime_env().object_store_root()}/tenants/{ctx.tenant_id}/campaigns/{ctx.campaign_id}/s6/vbe"
    timeout = int(max(3600.0, ctx.deadline_seconds or 0))
    output_path = design.analyte_output or PLASMA_OUTPUT_PATH.format(compound=cpf.compound)
    variability = [{"path": v["parameter"], "cv_percent": v["cv_percent"]} for v in inputs["variability"]]
    try:
        built = engine(EngineJob(
            job_id=f"{ctx.campaign_id}-S6-vbe", tenant_id=ctx.tenant_id, task="simulate",
            inputs=[EngineInput(name=ROUND_SNAPSHOT_INPUT, uri=out.as_uri(), sha256=hashlib.sha256(out.read_bytes()).hexdigest())],
            outputs_uri=f"{base}/models", options={"export_pkml": True}, timeout_s=timeout))
        models = {arm: _output(built, exported_pkml_name(f"vbe-{arm}")) for arm in ARMS}
        if missing := [arm for arm, m in models.items() if m is None]:
            return {**header, **_not_run(f"the engine exported no model for the {' and '.join(missing)} arm")}
        population = {"population": design.population, "number_of_individuals": n_subjects * n_trials,
                      "proportion_of_females": 100 if design.sex == "FEMALE" else 0,
                      "age_min": design.vpc_age_min, "age_max": design.vpc_age_max}
        manifests: dict[str, EngineManifest] = {}
        for arm in ARMS:
            model = models[arm]
            job_inputs = [EngineInput(name="simulation.pkml", uri=model.uri, sha256=model.sha256)]
            options: dict[str, Any] = {"variability": variability, "occasion_seed": occasion_seeds[arm]}
            if arm == "test":  # creates the individuals; the reference arm runs exactly them
                options |= {"population": population, "seed": seed}
            else:
                people = _output(manifests["test"], "population.csv")
                if people is None:
                    return {**header, **_not_run("the TEST arm exported no population.csv for the reference arm")}
                job_inputs.append(EngineInput(name="population.csv", uri=people.uri, sha256=people.sha256))
            manifests[arm] = engine(EngineJob(
                job_id=f"{ctx.campaign_id}-S6-vbe-{arm}", tenant_id=ctx.tenant_id, task="population",
                inputs=job_inputs, outputs_uri=f"{base}/{arm}", options=options, timeout_s=timeout))
    except Exception as exc:  # noqa: BLE001 - an engine failure (e.g. an unknown variability path) is reported
        return {**header, **_not_run(f"the engine stopped: {exc}")}

    pk = {}
    for arm in ARMS:
        csv_out = _output(manifests[arm], "pk_analyses.csv")
        if csv_out is None:
            return {**header, **_not_run(f"the {arm} arm exported no pk_analyses.csv")}
        try:
            _, pk[arm] = read_pk_analyses(_path(csv_out.uri).read_text(encoding="utf-8-sig"), output_path)
        except VbeError as exc:
            return {**header, **_not_run(f"{arm} arm: {exc}")}
    try:
        trials = run_trials(pk["test"], pk["reference"], n_subjects=n_subjects, n_trials=n_trials,
                            limits=(limits.lower, limits.upper), confidence=limits.ci_level,
                            pos_threshold=float(inputs["pos_threshold"]))
    except VbeError as exc:
        return {**header, **_not_run(str(exc))}
    return {**header, "status": "RUN", "output_path": output_path, **trials}
