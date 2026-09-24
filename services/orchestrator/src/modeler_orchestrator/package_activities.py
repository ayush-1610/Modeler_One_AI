"""S6 prediction and S7 report & package activities (MS-01 §4 S6/S7; decisions D5, D13).

S6 re-simulates the internal studies from the final CPF, then runs, per study, a local sensitivity analysis over the
FITTED and PREDICTED parameters and a batch of runs sampled from the fitted parameters' uncertainty
(`pbpk_domain.campaign.prediction`).

S7 assembles the submission package from what the campaign persisted as it went (``evidence/<stage>.json``): the
final CPF, the signed MAP, the observed data, the final simulations of S4/S5 with their result tables, every fit's
specs and results, and S6. Every bundled snapshot is re-run on a fresh engine process and its results compared
with the bundled tables at 1e-6 (`verify_reproduction`); the report (MAR) records the verdict and the data
bundle's hash; the downloadable package is written **only if reproduction passed** (D13).

Artifacts live beside the engine outputs: ``<object store>/tenants/<t>/campaigns/<id>/{evidence,s6,package}``.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from modeler_contracts.runs import EngineInput, EngineJob, EngineManifest, RoundContext
from modeler_orchestrator.campaign_activities import PLASMA_OUTPUT_PATH, exported_pkml_name

SENSITIVITY_TOP = 12  # rows kept per study in the S6 ranking


def _path(uri: str) -> Path:
    return Path(unquote(urlparse(uri).path))


def _read_json(uri: str) -> dict | None:
    path = _path(uri)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _root() -> str:
    return os.environ.get("MODELER_OBJECT_STORE_URI", "file:///tmp/modeler-object-store").rstrip("/")


def campaign_dir(tenant_id: str, campaign_id: str) -> Path:
    """Where the campaign's evidence, S6 results and package live (the object store, file:// today)."""
    path = _path(f"{_root()}/tenants/{tenant_id}/campaigns/{campaign_id}")
    path.mkdir(parents=True, exist_ok=True)
    return path


# --- evidence, persisted stage by stage --------------------------------------------------------------------


def persist_stage_evidence(tenant_id: str, campaign_id: str, stage: str, evidence: dict) -> Path:
    """Write what a finished stage produced — status, rounds, final metrics, notes, the judged snapshot and its
    engine outputs — so S7 can assemble the package even after the campaign paused for a signature."""
    out = campaign_dir(tenant_id, campaign_id) / "evidence" / f"{stage}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(evidence, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return out


def load_stage_evidence(tenant_id: str, campaign_id: str) -> dict[str, dict]:
    folder = campaign_dir(tenant_id, campaign_id) / "evidence"
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("S*.json"))}


# --- S6 --------------------------------------------------------------------------------------------------


def _parameter_paths(cpf, records, scenario) -> tuple[list[str], list[str], list[str]]:
    """(paths, units, CPF ids) of the records the engine can locate in this study's simulation."""
    from pbpk_domain.campaign.round_build import protocol_name
    from pbpk_domain.cpf.formulations import FormulationError, resolve_formulation_name, weibull_parameter_path
    from pbpk_domain.pksim_paths import ParameterPathError, pksim_parameter_path

    formulation = None
    if scenario.route == "oral" and scenario.formulation not in ("solution", "suspension"):
        try:
            formulation, _ = resolve_formulation_name(cpf, scenario.formulation_name)
        except FormulationError:
            formulation = None
    paths, units, ids = [], [], []
    for record in records:
        if record.id.startswith("form."):
            if record.id.split(".")[1] != formulation:
                continue  # this study does not use that formulation
            path = weibull_parameter_path(record.id, protocol=protocol_name(scenario.study_id))
        else:
            try:
                path = pksim_parameter_path(record, compound=cpf.compound)
            except ParameterPathError:
                path = None
        if path:
            paths.append(path)
            units.append(record.unit or "")
            ids.append(record.id)
    return paths, units, ids


def prepare_s6_jobs(ctx: RoundContext, manifest: EngineManifest) -> tuple[list[EngineJob], list[str]]:
    """Per internal study: a sensitivity job and, when fitted parameters carry an SD, an uncertainty batch.
    Returns the jobs and the notes on what could not be done."""
    from pbpk_domain.campaign.map import MapDocument
    from pbpk_domain.campaign.prediction import (
        SENSITIVITY_VARIATION,
        UNCERTAINTY_SAMPLES,
        sample_parameters,
        sensitivity_candidates,
        uncertain_parameters,
    )
    from pbpk_domain.campaign.round_build import scenarios_for_stage
    from pbpk_domain.cpf import CPF

    cpf = CPF.model_validate_json(_path(ctx.cpf_uri).read_text(encoding="utf-8"))
    map_doc = MapDocument.model_validate_json(_path(ctx.map_uri).read_text(encoding="utf-8"))
    models = {Path(o.name).name: o for o in manifest.outputs if o.name.endswith(".pkml")}
    sens_records, unc_records = sensitivity_candidates(cpf), uncertain_parameters(cpf)
    draws = sample_parameters(unc_records, UNCERTAINTY_SAMPLES, ctx.seed) if unc_records else []
    notes: list[str] = []
    if not sens_records:
        notes.append("no FITTED or PREDICTED parameter: nothing for the sensitivity analysis to vary")
    if not unc_records:
        notes.append("no fitted parameter carries a standard error: parameter uncertainty was not propagated")
    else:
        notes.append(f"uncertainty propagated from {', '.join(r.id for r in unc_records)} "
                     f"({UNCERTAINTY_SAMPLES} independent draws; parameter correlations not propagated yet)")
    base = f"{_root()}/tenants/{ctx.tenant_id}/campaigns/{ctx.campaign_id}/s6"
    jobs: list[EngineJob] = []
    for scenario in scenarios_for_stage(map_doc.scenarios, "S4"):
        model = models.get(exported_pkml_name(scenario.study_id))
        if model is None:
            notes.append(f"{scenario.study_id}: no exported model from the S6 simulation; not analysed")
            continue
        sim_input = [EngineInput(name="simulation.pkml", uri=model.uri, sha256=model.sha256)]
        paths, _units, ids = _parameter_paths(cpf, sens_records, scenario)
        if paths:
            jobs.append(EngineJob(
                job_id=f"{ctx.campaign_id}-S6-sens-{scenario.study_id}", tenant_id=ctx.tenant_id, task="sensitivity",
                inputs=sim_input, outputs_uri=f"{base}/sensitivity/{scenario.study_id}",
                options={"study": scenario.study_id, "parameter_paths": paths, "cpf_ids": ids, "number_of_steps": 2,
                         "variation_range": SENSITIVITY_VARIATION},
                timeout_s=1800,
            ))
        if draws:
            paths, units, ids = _parameter_paths(cpf, unc_records, scenario)
            if paths:
                jobs.append(EngineJob(
                    job_id=f"{ctx.campaign_id}-S6-unc-{scenario.study_id}", tenant_id=ctx.tenant_id, task="batch",
                    inputs=sim_input, outputs_uri=f"{base}/uncertainty/{scenario.study_id}",
                    options={"study": scenario.study_id, "parameter_paths": paths, "parameter_units": units, "cpf_ids": ids,
                             "runs": [{"parameter_values": [d[i] for i in ids]} for d in draws]},
                    timeout_s=3600,
                ))
    return jobs, notes


def evaluate_s6(ctx: RoundContext, jobs: list[EngineJob], manifests: list[EngineManifest]) -> dict:
    """Reduce the S6 jobs: sensitivity ranked by magnitude (CPF ids where known), and 5/50/95 % intervals of
    AUC (over the study's observed window) and Cmax from the uncertainty batch."""
    from pbpk_domain.campaign.prediction import parse_sensitivity, prediction_interval, results_csv_pk

    observed = _read_json(ctx.observed_uri) if ctx.observed_uri else {}
    sensitivity: dict[str, list[dict]] = {}
    intervals: dict[str, dict] = {}
    for job, manifest in zip(jobs, manifests, strict=True):
        study = job.options["study"]
        outputs = {Path(o.name).name: o for o in manifest.outputs}
        if job.task == "sensitivity" and "sensitivity.csv" in outputs:
            by_path = dict(zip(job.options["parameter_paths"], job.options["cpf_ids"], strict=True))
            rows = parse_sensitivity(_path(outputs["sensitivity.csv"].uri).read_bytes())
            rows.sort(key=lambda r: abs(r.value), reverse=True)
            sensitivity[study] = [{"parameter": by_path.get(r.parameter, r.parameter), "pk_parameter": r.pk_parameter,
                                   "value": r.value} for r in rows[:SENSITIVITY_TOP]]
        if job.task == "batch" and "batch_index.json" in outputs:
            index = _read_json(outputs["batch_index.json"].uri) or {}
            times = ((observed or {}).get(study) or {}).get("profile", {}).get("times") or []
            t_last = max(times) if times else None
            aucs, cmaxs = [], []
            for run in index.get("runs", []):
                csv_out = outputs.get(run["results"])
                pk = results_csv_pk(_path(csv_out.uri).read_bytes(), t_last_min=t_last) if csv_out else None
                if pk:
                    aucs.append(pk["auc"])
                    cmaxs.append(pk["cmax"])
            intervals[study] = {"AUC": prediction_interval(aucs), "Cmax": prediction_interval(cmaxs)}
    result = {"sensitivity": sensitivity, "intervals": intervals}
    out = campaign_dir(ctx.tenant_id, ctx.campaign_id) / "s6" / "s6.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


# --- S7 --------------------------------------------------------------------------------------------------


def _read(uri: str) -> bytes | None:
    path = _path(uri)
    return path.read_bytes() if path.exists() else None


def collect_bundle(tenant_id: str, campaign_id: str, *, cpf_uri: str, map_uri: str, observed_uri: str,
                   evidence: dict[str, dict], system_uri: str = "") -> tuple[dict[str, bytes], set[str], dict[str, str]]:
    """The data bundle: (files by bundle path, the numeric result tables, snapshot bundle path -> stem). A model
    system's document (every compound's CPF and their links, as the campaign started) is `cpf/system.json`; the
    fitted parent is `cpf/final.json`."""
    files: dict[str, bytes] = {}
    numeric: set[str] = set()
    snapshots: dict[str, str] = {}
    for bundle_path, uri in (("cpf/final.json", cpf_uri), ("map/map.json", map_uri), ("data/observed.json", observed_uri),
                             ("cpf/system.json", system_uri)):
        data = _read(uri) if uri else None
        if data is not None:
            files[bundle_path] = data
    for stage, ev in sorted(evidence.items()):
        files[f"evidence/{stage}.json"] = json.dumps(ev, ensure_ascii=False, indent=1, default=str).encode("utf-8")
        snap = ev.get("snapshot_uri")
        if stage in ("S4", "S5") and snap and snap.endswith(".json") and _read(snap) is not None:
            stem = f"{stage}-{campaign_id}"
            path = f"snapshots/{stem}.json"
            files[path] = _read(snap)
            snapshots[path] = stem
            for output in ev.get("outputs", []):
                name = Path(output["name"]).name
                if name.startswith("snapshot-") and name.endswith("-Results.csv"):
                    data = _read(output["uri"])
                    if data is not None:
                        table = f"results/{stem}/{stem}-{name.removeprefix('snapshot-')}"
                        files[table] = data
                        numeric.add(table)
    # every parameter identification the final CPF's values came from: spec and result of each start
    cpf = json.loads(files.get("cpf/final.json", b"{}") or b"{}")
    runs = {p["provenance"]["run"] for p in cpf.get("parameters", []) if (p.get("provenance") or {}).get("run")}
    fits_root = _path(f"{_root()}/tenants/{tenant_id}/fits")
    for run in sorted(runs):
        for f in sorted((fits_root / run).glob("start-*/pi_*.json")):
            files[f"fits/{run}/{f.parent.name}/{f.name}"] = f.read_bytes()
    s6 = campaign_dir(tenant_id, campaign_id) / "s6" / "s6.json"
    if s6.exists():
        files["prediction/s6.json"] = s6.read_bytes()
    return files, numeric, snapshots


def prepare_reproduction_jobs(tenant_id: str, campaign_id: str, files: dict[str, bytes],
                              snapshots: dict[str, str]) -> list[EngineJob]:
    """Re-run every bundled snapshot on a fresh engine process, exactly as a reviewer would."""
    folder = campaign_dir(tenant_id, campaign_id) / "package" / "rerun"
    jobs = []
    for bundle_path, stem in sorted(snapshots.items()):
        src = folder / f"{stem}.json"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(files[bundle_path])
        jobs.append(EngineJob(
            job_id=f"{campaign_id}-S7-rerun-{stem}", tenant_id=tenant_id, task="simulate",
            inputs=[EngineInput(name="snapshot.json", uri=src.as_uri(), sha256=hashlib.sha256(files[bundle_path]).hexdigest())],
            outputs_uri=(folder / stem).as_uri(), options={"stem": stem}, timeout_s=1800,
        ))
    return jobs


def verify_package_reproduction(files: dict[str, bytes], numeric: set[str], jobs: list[EngineJob],
                                manifests: list[EngineManifest]) -> dict:
    """Compare the re-run's result tables with the bundled ones (1e-6), file by file."""
    from pbpk_domain.reproducibility import assemble_bundle, verify_reproduction

    rerun: dict[str, bytes] = {}
    for job, manifest in zip(jobs, manifests, strict=True):
        stem = job.options["stem"]
        for output in manifest.outputs:
            name = Path(output.name).name
            if name.startswith("snapshot-") and name.endswith("-Results.csv"):
                rerun[f"results/{stem}/{stem}-{name.removeprefix('snapshot-')}"] = _path(output.uri).read_bytes()
    tables = {p: files[p] for p in sorted(numeric)}
    manifest = assemble_bundle("reproduction", "", tables, numeric_paths=set(tables))
    report = verify_reproduction(manifest, tables, rerun)
    return {"passes": report.passes and bool(tables),
            "verdicts": [{"path": v.path, "status": v.status, "detail": v.detail} for v in report.verdicts]}


def _pandoc() -> str:
    try:
        import pypandoc

        return pypandoc.get_pandoc_path()
    except Exception:  # noqa: BLE001 - pandoc is optional; the Markdown report is always written
        return "pandoc"


def finish_package(tenant_id: str, campaign_id: str, *, files: dict[str, bytes], numeric: set[str], map_uri: str,
                   cpf_uri: str, evidence: dict[str, dict], prediction: dict | None, reproduction: dict,
                   engine_image_digest: str = "") -> dict:
    """The MAR (from the evidence, the reproduction verdict and the data bundle hash), rendered; and, only when the
    reproduction passed, the downloadable package (zip with manifest and rerun_all.R). Returns the package record."""
    from pbpk_domain.campaign.map import MapDocument
    from pbpk_domain.cpf import CPF
    from pbpk_domain.report.campaign_mar import assemble_campaign_mar
    from pbpk_domain.report.mar import check_report
    from pbpk_domain.report.render import render_all
    from pbpk_domain.reproducibility import assemble_bundle, write_bundle_zip

    map_doc = MapDocument.model_validate_json(_path(map_uri).read_text(encoding="utf-8"))
    cpf = CPF.model_validate_json(_path(cpf_uri).read_text(encoding="utf-8"))
    data_manifest = assemble_bundle(f"{campaign_id}-data", campaign_id, files, numeric_paths=numeric,
                                    engine_image_digest=engine_image_digest, software_versions=map_doc.software_versions)
    mar = assemble_campaign_mar(map_doc=map_doc, final_cpf=cpf, stage_evidence=evidence, prediction=prediction,
                                reproduction=reproduction, data_bundle_sha256=data_manifest.content_sha256())
    issues = check_report(mar)
    out = campaign_dir(tenant_id, campaign_id) / "package"
    out.mkdir(parents=True, exist_ok=True)
    rendered = render_all(mar, out / "report", pandoc=_pandoc(), strict=not issues)
    record: dict = {
        "reproduction": {"passes": reproduction["passes"],
                         "compared": len(reproduction["verdicts"]),
                         "failures": [v for v in reproduction["verdicts"] if v["status"] not in ("match", "within_tolerance")]},
        "report": {fmt: str(path) for fmt, path in rendered.items()},
        "report_issues": [i.model_dump() for i in issues],
        "data_bundle_sha256": data_manifest.content_sha256(),
        "files": len(files),
        "exportable": False,
    }
    if "pdf" not in rendered:
        record["report_notes"] = ["PDF/A not rendered (DOCX and Markdown written)" if "docx" in rendered
                                  else "DOCX/PDF not rendered: pandoc unavailable (Markdown written)"]
    if reproduction["passes"] and not issues:
        full = dict(files)
        for path in rendered.values():
            full[f"report/{Path(path).name}"] = Path(path).read_bytes()
        manifest = assemble_bundle(f"{campaign_id}-package", campaign_id, full, numeric_paths=numeric,
                                   engine_image_digest=engine_image_digest, software_versions=map_doc.software_versions)
        (out / "package.zip").write_bytes(write_bundle_zip(manifest, full))
        record.update(exportable=True, package=str(out / "package.zip"), package_sha256=manifest.content_sha256())
    (out / "package.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
    return record


__all__ = [
    "PLASMA_OUTPUT_PATH", "campaign_dir", "collect_bundle", "evaluate_s6", "finish_package", "load_stage_evidence",
    "persist_stage_evidence", "prepare_reproduction_jobs", "prepare_s6_jobs", "verify_package_reproduction",
]
