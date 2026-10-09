#!/usr/bin/env python3
"""Run a published OSP model through Modeler One on real PK-Sim (plan Phase 4) and report what happened.

    uv run python deploy/reference/run_reference.py roundtrip Dapagliflozin --out out/dapa
    uv run python deploy/reference/run_reference.py campaign  Dapagliflozin --mode as-is --out out/dapa
    uv run python deploy/reference/run_reference.py campaign  Dapagliflozin --mode refit --out out/dapa

vbe        an ILLUSTRATIVE virtual bioequivalence on PK-Sim (T-31): S6's own VBE step run from the published model,
           its tablet as the reference and an invented TEST tablet (the published one with t50 x1.5), with an
           illustrative intra-subject CV. It proves the machinery on PK-Sim; it is not clinical evidence.
roundtrip  every published simulation that runs an imported study against the one the pipeline regenerates from
           the imported CPF, on PK-Sim at identical time points (services/engine-worker/golden/reference_compare.R,
           run through REFERENCE_RSCRIPT, e.g. "docker run --rm -v $PWD:$PWD -w $PWD <image> Rscript").
as-is      a campaign on the published CPF exactly as imported (nothing fittable): the published model judged by the
           pipeline's gates against the real clinical data.
refit      a campaign from shifted values with the published model's identified parameters freed within the bounds
           the user approved (pbpk_domain.reference.refit).

Campaigns run exactly as the web app starts them (write API → prepare → single-node runner) on the engine
MODELER_ENGINE_COMMAND names. The MAP is not signed by a person here and the run stops at the S6 signature gate:
a verification run never signs on anyone's behalf. Output: <out>/<step>.json and a Markdown summary on stdout.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "services" / "engine-worker" / "golden" / "fixtures"


def _import(model: str):
    from pbpk_domain.reference import import_osp_snapshot

    snapshot_path = FIXTURES / f"{model}-Model.json"
    return snapshot_path, import_osp_snapshot(json.loads(snapshot_path.read_text(encoding="utf-8")))


def roundtrip(model: str, out: Path, *, system: bool = False) -> dict:
    """``system``: import the model system (parent, enantiomers, metabolites) and compare every study on its analyte."""
    from pbpk_domain.reference.roundtrip import roundtrip_inputs, system_roundtrip_inputs

    if system:
        from pbpk_domain.reference import import_osp_system

        snapshot_path = FIXTURES / f"{model}-Model.json"
        imported = import_osp_system(json.loads(snapshot_path.read_text(encoding="utf-8")))
        ours, pairs, notes = system_roundtrip_inputs(imported)
    else:
        snapshot_path, imported = _import(model)
        ours, pairs, notes = roundtrip_inputs(imported)
    work = out / "roundtrip"
    work.mkdir(parents=True, exist_ok=True)
    (work / "ours.json").write_text(json.dumps(ours, ensure_ascii=False), encoding="utf-8")
    (work / "pairs.json").write_text(json.dumps(pairs, indent=1), encoding="utf-8")
    rscript = shlex.split(os.environ.get("REFERENCE_RSCRIPT", "Rscript"))
    script = REPO / "services" / "engine-worker" / "golden" / "reference_compare.R"
    cmd = [*rscript, str(script), str(snapshot_path), str(work / "ours.json"), str(work / "pairs.json"), str(work / "engine")]
    started = time.monotonic()
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)  # the report says what failed
    report_path = work / "engine" / "roundtrip.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    result = {"model": model, "seconds": round(time.monotonic() - started), "exit": proc.returncode,
              "notes": notes, "import_notes": list(imported.notes), "report": report,
              "stderr_tail": proc.stderr[-4000:], "stdout_tail": proc.stdout[-6000:]}
    (out / "roundtrip.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    return result


def evaluate(model: str, out: Path) -> dict:
    """The published model judged on every study it can simulate, by the pipeline's own evaluation: one engine run of
    the imported CPF, then AUC and Cmax fold errors per study (sampled at the observed times), GMFE per role."""
    import hashlib

    from modeler_api.studies import observed_from_studies
    from modeler_contracts.runs import EngineInput, EngineJob
    from modeler_orchestrator.local_runner import default_engine
    from pbpk_domain.campaign.evaluate import ObservedPK, SimulatedProfile, assess_round
    from pbpk_domain.m15 import Rating
    from pbpk_domain.reference.roundtrip import study_snapshot

    _snapshot_path, imported = _import(model)
    snapshot, assignment, notes = study_snapshot(imported, linked_only=False)
    work = out / "evaluate"
    work.mkdir(parents=True, exist_ok=True)
    snap_path = work / "snapshot.json"
    snap_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
    started = time.monotonic()
    manifest = default_engine()(EngineJob(
        job_id=f"evaluate-{model.lower()}", tenant_id="ref", task="simulate",
        inputs=[EngineInput(name="snapshot.json", uri=snap_path.as_uri(),
                            sha256=hashlib.sha256(snap_path.read_bytes()).hexdigest())],
        outputs_uri=(work / "engine").as_uri(), timeout_s=7200,
    ))
    profiles_path = work / "engine" / "profiles.json"
    if manifest.status != "SUCCEEDED" or not profiles_path.exists():
        result = {"model": model, "error": f"engine {manifest.status}: {manifest.stderr_tail[-2000:]}", "notes": notes}
        (out / "evaluate.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
        return result
    profiles = json.loads(profiles_path.read_text(encoding="utf-8"))["profiles"]
    mw = imported.cpf.require("phys.mw").numeric_value
    rows = [s for s in imported.studies if s["study_id"] in assignment]
    observed_doc = observed_from_studies(rows, mw)
    simulated, observed = [], {}
    for sid, prof in profiles.items():
        role = "fitting" if assignment.get(sid) == "INTERNAL" else "validation"
        simulated.append(SimulatedProfile(sid, role, prof["times_min"], prof["concentrations"]))
        pk = observed_doc.get(sid)
        if pk:
            times = pk["profile"]["times"]
            observed[sid] = ObservedPK(auc=pk["auc"], cmax=pk["cmax"], tmax=pk["tmax"], thalf=pk["thalf"],
                                       t_first=min(times), t_last=max(times), sample_times=tuple(times))
    assessment = assess_round(simulated, observed, model_risk=Rating.MEDIUM)
    studies = [{"study_id": s.study_id, "role": s.role, "assignment": assignment.get(s.study_id),
                "auc_ratio": (s.predicted_auc / s.observed_auc) if s.predicted_auc and s.observed_auc else None,
                "cmax_ratio": (s.predicted_cmax / s.observed_cmax) if s.predicted_cmax and s.observed_cmax else None}
               for s in assessment.studies]
    summary = {}
    for role in ("fitting", "validation", "all"):
        chosen = [s for s in studies if role == "all" or s["role"] == role]
        for q in ("auc", "cmax"):
            ratios = [s[f"{q}_ratio"] for s in chosen if s[f"{q}_ratio"]]
            if ratios:
                logs = [abs(math.log10(r)) for r in ratios]
                summary[f"{role}.{q}"] = {"n": len(ratios), "gmfe": 10 ** (sum(logs) / len(logs)),
                                          **{f"within_{k}": _within(logs, fold) for k, fold in
                                             (("1_25", 1.25), ("1_5", 1.5), ("2", 2.0))}}
    result = {"model": model, "seconds": round(time.monotonic() - started), "summary": summary, "studies": studies,
              "not_simulated": notes, "findings": list(assessment.findings)}
    (out / "evaluate.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    return result


# The illustrative VBE proof per model: the published tablet as the reference, a TEST tablet with its t50 scaled.
# The variability path is harvested from the OSP reference snapshots (Ketoconazole, Alfentanil), never typed from
# memory; the engine refuses one the simulation does not have.
VBE_PROOF = {
    "Dapagliflozin": {"reference": "IC tablet (Chang 2015)", "t50_factor": 1.5,
                      "variability": [{"parameter": "Organism|Lumen|Stomach|Gastric emptying time", "cv_percent": 30,
                                       "source": "ILLUSTRATIVE value for the PK-Sim proof of the VBE machinery; not a "
                                                 "clinical estimate"}],
                      "n_subjects": 24, "n_trials": 20, "seed": 2026, "pos_threshold": 0.8},
}
ILLUSTRATIVE = ("ILLUSTRATIVE: the published model as imported (not a campaign-validated model), an invented TEST tablet "
                "and an illustrative intra-subject CV. It shows the VBE machinery working on PK-Sim; it is not clinical "
                "or regulatory evidence.")


def vbe(model: str, out: Path) -> dict:
    """S6's VBE step (`modeler_orchestrator.vbe_activities.run_vbe`) on PK-Sim from the published model: the MAP pins
    `vbe-crossover` with the proof's inputs, the TEST tablet is the published tablet with its t50 scaled."""
    import hashlib

    from modeler_contracts.runs import RoundContext
    from modeler_orchestrator.local_runner import default_engine
    from modeler_orchestrator.vbe_activities import run_vbe
    from pbpk_domain.campaign.map import MapApplication, generate_map
    from pbpk_domain.campaign.split import QuestionOfInterest, split_studies
    from pbpk_domain.cpf import Provenance
    from pbpk_domain.m15 import Rating
    from pbpk_domain.reference.roundtrip import study_records

    proof = VBE_PROOF[model]
    _snapshot_path, imported = _import(model)
    reference = proof["reference"]
    note = f"ILLUSTRATIVE TEST tablet for the VBE proof: the published {reference} with t50 x{proof['t50_factor']:g}"
    test = []
    for record in imported.cpf.with_prefix(f"form.{reference}"):
        suffix = record.id[len(f"form.{reference}."):]
        value = record.value * proof["t50_factor"] if suffix == "weibull.t50" else record.value
        test.append(record.model_copy(update={"id": f"form.Test tablet.{suffix}", "value": value,
                                              "provenance": Provenance(source_type="assumed", reference=note)}))
    cpf = imported.cpf.model_copy(update={"parameters": (*imported.cpf.parameters, *test)})
    inputs = {"test_formulation": "Test tablet", "reference_formulation": reference,
              **{k: proof[k] for k in ("variability", "n_subjects", "n_trials", "seed", "pos_threshold")}}
    studies = study_records(imported)
    map_doc = generate_map(compound=imported.compound, cpf=cpf, studies=studies,
                           split=split_studies(studies, QuestionOfInterest()), objective="illustrative VBE proof",
                           context_of_use=ILLUSTRATIVE, food_effect_in_question=False, model_risk=Rating.MEDIUM,
                           engine_image_digest=os.environ.get("MODELER_ENGINE_IMAGE", "reference"),
                           software_versions={"ospsuite": "12.4.4"},
                           applications=(MapApplication.pinned("vbe-crossover", inputs),))
    work = out / "vbe"
    work.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MODELER_OBJECT_STORE_URI", (work / "objects").as_uri())
    (work / "cpf.json").write_text(cpf.model_dump_json(), encoding="utf-8")
    (work / "map.json").write_text(map_doc.model_dump_json(), encoding="utf-8")
    ctx = RoundContext(campaign_id=f"vbe-{model.lower()}", tenant_id="ref", stage="S6", round_index=1,
                       cpf_uri=(work / "cpf.json").as_uri(),
                       cpf_sha256=hashlib.sha256((work / "cpf.json").read_bytes()).hexdigest(), pending_action=None,
                       map_uri=(work / "map.json").as_uri(), deadline_seconds=7200.0)
    started = time.monotonic()
    result = {"model": model, "illustrative": ILLUSTRATIVE, **(run_vbe(ctx, default_engine(), cpf=cpf, map_doc=map_doc)
                                                              or {"status": "NOT_RUN", "reason": "no application"})}
    result["seconds"] = round(time.monotonic() - started)
    for metric in (result.get("metrics") or {}).values():
        metric.pop("trials", None)  # K rows per metric: in vbe.json only
    (out / "vbe.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    return result


def _within(abs_log_errors: list[float], fold: float) -> float:
    return sum(1 for x in abs_log_errors if x <= math.log10(fold) + 1e-12) / len(abs_log_errors)


def _claims() -> dict:
    return {"sub": "reference-run", "name": "Reference run (unsigned verification)", "tenant_id": "ref",
            "realm_access": {"roles": ["modeler-curator"]}, "projects": ["*"], "acr": "loa2",
            "auth_time": int(time.time())}


def campaign(model: str, mode: str, out: Path, *, system: bool = False) -> dict:
    from fastapi.testclient import TestClient

    from modeler_api import write_api
    from modeler_api.auth import get_verifier
    from modeler_api.main import app
    from modeler_contracts.runs import CAMPAIGN_STAGES, CampaignRequest
    from modeler_orchestrator.local_runner import run_campaign
    from modeler_storage.filestore import FileReadStore, FileWriteStore
    from pbpk_domain.reference.refit import refit_cpf

    compounds: dict = {}
    links = None
    if system:
        from pbpk_domain.fit_spec import qualify
        from pbpk_domain.reference import import_osp_system
        from pbpk_domain.system import formation_targets, links_of

        imported = import_osp_system(json.loads((FIXTURES / f"{model}-Model.json").read_text(encoding="utf-8")))
        system = imported.system
        fitted_name = system.parents[0]
        compounds = {c.compound: c for c in system.compounds}
        links = links_of(system).model_dump(mode="json")
        freed = {}
        if mode == "refit":
            # every compound's identified parameters (MS-01 v1.3): a parent's at the parent stages, a metabolite's at SM,
            # and the rate forming each metabolite at SM too; reported under their fit ids
            forms = {}
            for metabolite in (c for c, role in system.roles.items() if role == "metabolite"):
                for compound, pid in formation_targets(system, metabolite):
                    forms.setdefault(compound, set()).add(pid)
            for name, original in list(compounds.items()):
                compounds[name], theirs = refit_cpf(original, role=system.roles[name],
                                                    formation=frozenset(forms.get(name, ())))
                freed |= {qualify(name, pid, fitted_name): info for pid, info in theirs.items()}
        cpf = compounds[fitted_name]
    else:
        _snapshot_path, imported = _import(model)
        fitted_name = model
        cpf, freed = (refit_cpf(imported.cpf) if mode == "refit" else (imported.cpf, {}))
        compounds = {model: cpf}
    root = tempfile.mkdtemp(prefix=f"ref-{model}-{mode}-")

    class _Verifier:
        def verify(self, token):
            return _claims()

    app.dependency_overrides[get_verifier] = lambda: _Verifier()
    app.dependency_overrides[write_api._stores] = lambda: (FileReadStore(root), FileWriteStore(root))
    try:
        client = TestClient(app)
        auth = {"Authorization": "Bearer reference"}
        project = client.post("/api/v1/projects", json={
            "name": f"{model} {mode}", "compound": model, "model_risk": "medium",
            "question": f"Reference run ({mode}) of the published OSP {model} model"}, headers=auth).json()["data"]
        pid, qid = project["id"], project["questions"][0]["id"]
        for name, compound_cpf in compounds.items():
            client.put(f"/api/v1/projects/{pid}/compounds/{name}/cpf", json=compound_cpf.model_dump(mode="json"),
                       headers=auth).raise_for_status()
        if links is not None:
            client.put(f"/api/v1/projects/{pid}/system", json=links, headers=auth).raise_for_status()
        client.post(f"/api/v1/projects/{pid}/studies", json={"studies": list(imported.studies)}, headers=auth).raise_for_status()
        r = client.post(f"/api/v1/projects/{pid}/questions/{qid}/campaign:prepare", json={"compound": fitted_name},
                        headers=auth)
        if r.status_code != 200:
            raise SystemExit(f"prepare failed: {r.status_code} {r.text}")
        prep = r.json()["data"]
    finally:
        app.dependency_overrides.clear()

    request = CampaignRequest(
        campaign_id=f"ref-{model.lower()}-{mode}", tenant_id="ref", compound=fitted_name, map_id=prep["map_id"],
        cpf_uri=prep["cpf_uri"], cpf_sha256=prep["cpf_sha256"], map_uri=prep["map_uri"],
        observed_uri=prep["observed_uri"], stages=list(CAMPAIGN_STAGES),
        system_uri=prep.get("system_uri", ""), system_sha256=prep.get("system_sha256", ""),
        # The default stage budget assumes the 48-core server; a smaller engine host (a 4-core CI runner) sets more.
        stage_budgets_seconds={s: int(os.environ.get("REFERENCE_STAGE_BUDGET_S", "1800")) for s in CAMPAIGN_STAGES
                               if s != "S0"},
    )
    started = time.monotonic()
    outcome = run_campaign(request, read_root=root, project=pid, question=f"reference {mode}", model_risk="medium")
    record = FileReadStore(root).get_campaign("ref", request.campaign_id) or {}
    final_cpf = None
    if getattr(outcome, "final_cpf_uri", None):
        path = Path(unquote(urlparse(outcome.final_cpf_uri).path))
        if path.exists():
            final_cpf = json.loads(path.read_text(encoding="utf-8"))
    final_system = None
    if final_cpf is not None and request.system_uri:
        from modeler_orchestrator.round_system import current_system_uri

        system_path = Path(unquote(urlparse(current_system_uri(outcome.final_cpf_uri, request.system_uri)).path))
        if system_path.exists():
            final_system = json.loads(system_path.read_text(encoding="utf-8"))
    result = {
        "model": model, "mode": mode, "seconds": round(time.monotonic() - started),
        "outcome": {"status": outcome.status, "reason": getattr(outcome, "reason", None)},
        "freed": freed, "split": prep["studies"], "campaign": record, "not_evaluated": prep.get("not_evaluated", []),
        "fitted": _fitted(final_cpf, freed, final_system) if final_cpf else {},
    }
    (out / f"campaign-{mode}.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    return result


def _fitted(final_cpf: dict, freed: dict, final_system: dict | None = None) -> dict:
    """Each freed parameter's final value; another compound's (``<compound>::<id>``) from the system as of the final CPF."""
    from pbpk_domain.fit_spec import split_fit_id

    by_compound = {c["compound"]: {p["id"]: p for p in c.get("parameters", [])}
                   for c in (final_system or {}).get("compounds", [])}
    own = {p["id"]: p for p in final_cpf.get("parameters", [])}
    out = {}
    for fit_id, info in freed.items():
        compound, pid = split_fit_id(fit_id)
        values = by_compound.get(compound, {}) if compound else own
        out[fit_id] = {**info, "fitted": values.get(pid, {}).get("value")}
    return out


def summary(step: str, result: dict) -> str:
    lines: list[str] = []
    if step == "vbe":
        lines.append(f"### VBE {result['model']} (illustrative): {result.get('status')} in {result.get('seconds')} s")
        lines.append(f"_{result['illustrative']}_")
        if result.get("status") != "RUN":
            lines.append(f"- not run: {result.get('reason')}")
            return "\n".join(lines)
        lines.append(f"- TEST `{result['formulations']['test']}` vs reference `{result['formulations']['reference']}`; "
                     f"design {result['design_study']} ({result['dose_mg']:g} mg, {result['food_state']}); "
                     f"{result['n_trials_run']} trials x {result['n_subjects']}; individuals {result['individuals']}, "
                     f"excluded {len(result['excluded_individuals'])}; occasion seeds {result['occasion_seeds']}")
        lines.append("| metric | PoS | GMR median | GMR 5-95 % | simulated between-subject CV |")
        lines.append("|---|---|---|---|---|")
        for name, m in result["metrics"].items():
            lines.append(f"| {name} | {m['probability_of_success']:.0%} | {m['gmr_median']:.4f} | "
                         f"{m['gmr_p05']:.4f}-{m['gmr_p95']:.4f} | {m['between_subject_cv_percent']:.1f} % |")
        lines.append(f"| joint | {result['joint_probability_of_success']:.0%} | | | |")
        lines.append(f"- validation: {result['validation']['status']}: {result['validation']['reason']}")
        return "\n".join(lines)
    if step == "evaluate":
        if "error" in result:
            return f"### Evaluate {result['model']}: {result['error']}"
        lines.append(f"### Evaluate {result['model']}: the published model on every study, by the pipeline's evaluation "
                     f"({result['seconds']} s)")
        lines.append("| group | n | GMFE | within 1.25× | within 1.5× | within 2× |")
        lines.append("|---|---|---|---|---|---|")
        for key, v in result["summary"].items():
            lines.append(f"| {key} | {v['n']} | {v['gmfe']:.3f} | {v['within_1_25']:.0%} | {v['within_1_5']:.0%} | "
                         f"{v['within_2']:.0%} |")
        lines.append("| study | role | AUC pred/obs | Cmax pred/obs |")
        lines.append("|---|---|---|---|")
        for s in result["studies"]:
            fmt = lambda v: f"{v:.3f}" if v else ""
            lines.append(f"| {s['study_id']} | {s['role']} | {fmt(s['auc_ratio'])} | {fmt(s['cmax_ratio'])} |")
        for n in result["not_simulated"]:
            if not n.startswith("expression profiles"):
                lines.append(f"- {n}")
        return "\n".join(lines)
    if step == "roundtrip":
        report = result.get("report") or {}
        pairs = [r for r in report.get("pairs", []) if "error" not in r]
        # a reporting tier, not the acceptance: pairs off by more than 1e-6 but at most 1e-3 of the peak, with AUC and
        # Cmax within 1e-3, differ at the level of the solver's tolerance, not by a model input
        close = sum(1 for r in pairs if not r.get("identical") and r["max_rel_to_peak"] <= CLOSE
                    and abs(r["auc_ratio"] - 1) <= CLOSE and abs(r["cmax_ratio"] - 1) <= CLOSE)
        labelled = sum(1 for r in pairs if not r.get("identical") and r.get("by_design"))
        lines.append(f"### Round trip {result['model']}: {report.get('identical', 0)} of {report.get('total', 0)} "
                     f"identical within {report.get('tolerance')} of the peak; {close} more within {CLOSE:g} (solver "
                     f"level); {labelled} labelled by design ({result['seconds']} s, exit {result['exit']})")
        lines.append("| ours | analyte | published | max diff / peak | AUC ratio | Cmax ratio | differs by design |")
        lines.append("|---|---|---|---|---|---|---|")
        for row in report.get("pairs", []):
            if "error" in row:
                lines.append(f"| {row['ours']} | {row.get('analyte', '')} | {row['published']} | ERROR: {row['error']} | | | |")
            else:
                lines.append(f"| {row['ours']} | {row.get('analyte', '')} | {row['published']} | {row['max_rel_to_peak']:.3g} | "
                             f"{row['auc_ratio']:.6f} | {row['cmax_ratio']:.6f} | {row.get('by_design') or ''} |")
        for name, diff in (report.get("parameter_diffs") or {}).items():
            if "error" in diff:
                lines.append(f"- parameters of {name}: ERROR {diff['error']}")
                continue
            lines.append(f"- parameters of {name} vs {diff['ours']}: {diff['compared']} compared, {diff['differing']} "
                         f"differ; only published {len(diff['only_published'])}, only ours {len(diff['only_ours'])}")
            for t in diff.get("top", [])[:15]:
                lines.append(f"  - `{t['path']}`: {t['published']:.10g} → {t['ours']:.10g}")
            for p in diff.get("only_published", [])[:10]:
                lines.append(f"  - only published: `{p}`")
        if not report:
            lines.append("```\n" + result.get("stderr_tail", "") + "\n" + result.get("stdout_tail", "") + "\n```")
    else:
        c = result.get("campaign", {})
        lines.append(f"### Campaign {result['model']} ({result['mode']}): {result['outcome']['status']} "
                     f"in {result['seconds']} s. {result['outcome'].get('reason') or ''}")
        lines.append("| stage | status | rounds (action: AUC GMFE / Cmax GMFE, verdict) | notes |")
        lines.append("|---|---|---|---|")
        for s in c.get("stages", []):
            rounds = "; ".join(f"{r['action']}: {r.get('aucGmfe')} / {r.get('cmaxGmfe')} {r['verdict']}"
                               for r in s.get("rounds", []))
            notes = " · ".join(n[:160] for n in s.get("notes", []) if not n.startswith("expression profiles"))
            lines.append(f"| {s['stage']} | {s['status']} | {rounds} | {notes} |")
        for s in c.get("stages", []):
            for r in s.get("rounds", []):
                for st in r.get("studies", []):
                    lines.append(f"- {s['stage']} r{r['round']} {st.get('study_id')}: "
                                 + ", ".join(f"{k}={v}" for k, v in st.items() if k != "study_id"))
        if result.get("fitted"):
            lines.append("| parameter | published | start | fitted | bounds |")
            lines.append("|---|---|---|---|---|")
            for pid, f in result["fitted"].items():
                lines.append(f"| {pid} | {f['published']:.4g} | {f['start']:.4g} | {f['fitted']} | "
                             f"[{f['lower']:.3g}, {f['upper']:.3g}] |")
    return "\n".join(lines)


CLOSE = 1e-3  # the round trip's "solver level" reporting tier (see summary)


def recap(text: str) -> str:
    """The headline and every round-trip row outside 1e-6 of the peak, again at the end of the log (the parameter
    lists above run long; a log tail must still show the result)."""
    keep = [line for line in text.splitlines() if line.startswith(("### ", "| group", "| stage", "| S"))
            or (line.startswith("| ") and _off_row(line))]
    return "\n".join(["#### recap", *keep])


def _off_row(line: str) -> bool:
    cells = [c.strip() for c in line.strip("|").split("|")]
    if len(cells) < 4 or cells[0] in ("ours", "study", "parameter", "---"):
        return False
    try:
        return float(cells[3]) > 1e-6
    except ValueError:
        return cells[3].startswith("ERROR")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", choices=["roundtrip", "campaign", "evaluate", "vbe"])
    parser.add_argument("model")
    parser.add_argument("--mode", choices=["as-is", "refit"], default="as-is")
    parser.add_argument("--system", action="store_true", help="the model system (parent, enantiomers, metabolites): round trip every analyte, or run the campaign on it")
    parser.add_argument("--out", type=Path, default=REPO / "reports" / "reference")
    args = parser.parse_args()
    args.out = args.out.resolve()  # engine inputs are file:// URIs, which need an absolute path
    args.out.mkdir(parents=True, exist_ok=True)
    if args.step == "roundtrip":
        result = roundtrip(args.model, args.out, system=args.system)
    elif args.step == "evaluate":
        result = evaluate(args.model, args.out)
    elif args.step == "vbe":
        result = vbe(args.model, args.out)
    else:
        result = campaign(args.model, args.mode, args.out, system=args.system)
    text = summary(args.step, result)
    print(text)
    print(recap(text))
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as handle:
            handle.write(text + "\n\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
