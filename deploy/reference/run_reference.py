#!/usr/bin/env python3
"""Run a published OSP model through Modeler One on real PK-Sim (plan Phase 4) and report what happened.

    uv run python deploy/reference/run_reference.py roundtrip Dapagliflozin --out out/dapa
    uv run python deploy/reference/run_reference.py campaign  Dapagliflozin --mode as-is --out out/dapa
    uv run python deploy/reference/run_reference.py campaign  Dapagliflozin --mode refit --out out/dapa

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


def roundtrip(model: str, out: Path) -> dict:
    from pbpk_domain.reference.roundtrip import roundtrip_inputs

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


def _claims() -> dict:
    return {"sub": "reference-run", "name": "Reference run (unsigned verification)", "tenant_id": "ref",
            "realm_access": {"roles": ["modeler-curator"]}, "projects": ["*"], "acr": "loa2",
            "auth_time": int(time.time())}


def campaign(model: str, mode: str, out: Path) -> dict:
    from fastapi.testclient import TestClient

    from modeler_api import write_api
    from modeler_api.auth import get_verifier
    from modeler_api.filestore import FileReadStore, FileWriteStore
    from modeler_api.main import app
    from modeler_contracts.runs import CAMPAIGN_STAGES, CampaignRequest
    from modeler_orchestrator.local_runner import run_campaign
    from pbpk_domain.reference.refit import refit_cpf

    _snapshot_path, imported = _import(model)
    cpf, freed = (refit_cpf(imported.cpf) if mode == "refit" else (imported.cpf, {}))
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
        r = client.put(f"/api/v1/projects/{pid}/compounds/{model}/cpf", json=cpf.model_dump(mode="json"), headers=auth)
        r.raise_for_status()
        client.post(f"/api/v1/projects/{pid}/studies", json={"studies": list(imported.studies)}, headers=auth).raise_for_status()
        r = client.post(f"/api/v1/projects/{pid}/questions/{qid}/campaign:prepare", json={"compound": model}, headers=auth)
        if r.status_code != 200:
            raise SystemExit(f"prepare failed: {r.status_code} {r.text}")
        prep = r.json()["data"]
    finally:
        app.dependency_overrides.clear()

    request = CampaignRequest(
        campaign_id=f"ref-{model.lower()}-{mode}", tenant_id="ref", compound=model, map_id=prep["map_id"],
        cpf_uri=prep["cpf_uri"], cpf_sha256=prep["cpf_sha256"], map_uri=prep["map_uri"],
        observed_uri=prep["observed_uri"], stages=list(CAMPAIGN_STAGES),
    )
    started = time.monotonic()
    outcome = run_campaign(request, read_root=root, project=pid, question=f"reference {mode}", model_risk="medium")
    record = FileReadStore(root).get_campaign("ref", request.campaign_id) or {}
    final_cpf = None
    if getattr(outcome, "final_cpf_uri", None):
        path = Path(unquote(urlparse(outcome.final_cpf_uri).path))
        if path.exists():
            final_cpf = json.loads(path.read_text(encoding="utf-8"))
    result = {
        "model": model, "mode": mode, "seconds": round(time.monotonic() - started),
        "outcome": {"status": outcome.status, "reason": getattr(outcome, "reason", None)},
        "freed": freed, "split": prep["studies"], "campaign": record,
        "fitted": _fitted(final_cpf, freed) if final_cpf else {},
    }
    (out / f"campaign-{mode}.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    return result


def _fitted(final_cpf: dict, freed: dict) -> dict:
    by_id = {p["id"]: p for p in final_cpf.get("parameters", [])}
    return {pid: {**info, "fitted": by_id.get(pid, {}).get("value")} for pid, info in freed.items()}


def summary(step: str, result: dict) -> str:
    lines: list[str] = []
    if step == "roundtrip":
        report = result.get("report") or {}
        lines.append(f"### Round trip {result['model']}: {report.get('identical', 0)} of {report.get('total', 0)} "
                     f"identical within {report.get('tolerance')} of the peak ({result['seconds']} s, exit {result['exit']})")
        lines.append("| ours | published | max diff / peak | AUC ratio | Cmax ratio |")
        lines.append("|---|---|---|---|---|")
        for row in report.get("pairs", []):
            if "error" in row:
                lines.append(f"| {row['ours']} | {row['published']} | ERROR: {row['error']} | | |")
            else:
                lines.append(f"| {row['ours']} | {row['published']} | {row['max_rel_to_peak']:.3g} | "
                             f"{row['auc_ratio']:.6f} | {row['cmax_ratio']:.6f} |")
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", choices=["roundtrip", "campaign"])
    parser.add_argument("model")
    parser.add_argument("--mode", choices=["as-is", "refit"], default="as-is")
    parser.add_argument("--out", type=Path, default=REPO / "reports" / "reference")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    result = roundtrip(args.model, args.out) if args.step == "roundtrip" else campaign(args.model, args.mode, args.out)
    text = summary(args.step, result)
    print(text)
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as handle:
            handle.write(text + "\n\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
