#!/usr/bin/env python3
"""T-56: Dapagliflozin from a mock technical proposal through P0 → P6, over the API (plan §19 T-56, Appendix A).

    uv run python deploy/proof/run_t56.py prepare --api http://localhost:8000 --token "$TOKEN" --out out/t56
    uv run python deploy/proof/run_t56.py accept  --api … --token … --project <id> --as "Full Name"
        → then, in the web app, the MIDD lead signs the plan on /projects/<id>/plan and runs the campaign (P6)
    uv run python deploy/proof/run_t56.py trace   --api … --token … --project <id> --campaign <cid> --out out/t56

**prepare** (P0 → P3 proposals): the project starts from the mock proposal (`dapagliflozin/proposal.md`); the brief is
filled by hand from it (the manual path, each field citing the proposal's section), and the data plan follows it; every
parameter of the published OSP Dapagliflozin model is proposed as evidence citing the model (`OSP_LIBRARY`, its
ValueOrigin text as the quote); every clinical dataset the model carries is proposed with its publication and figure;
the fed study Kasichayanula 2011a is delivered in the client-data template as the "client" study. Nothing is accepted.

**accept** (the owner's decisions, run only by the owner with their own name): the values and datasets `prepare`
proposed flow in with nothing to accept (D-27); the owner settles what the Inputs step leaves to a person (the values
held until checked, each pathway's process type, the client study's formulation, the healthy adult default where a
study states no individual), and P5 is drafted: the MS-01 default plan, the validator's warnings acknowledged. It stops before the MAP signature: a Part 11 signature is
a person's act in the web app (step-up), never a script's.

**trace** (the T-56 acceptance, "a reviewer can trace every number in the MAR to its source"): every parameter of the
campaign's final CPF to its evidence item and source or to the fit that produced it, every judged study to its dataset
and publication, every number in the MAR's evidence index to its source; any broken link is listed and the exit
code is 1. It also writes ``pq.json``, the Performance Qualification record the validation pack renders (`pq_record`):
PQ passes only on a production (Part 11) run on PK-Sim whose package reproduces, within the 1-hour goal.

Honest limits, stated in the report: the inputs are the published model's values (a "literature" proof, not an A2 search;
A2 runs only with a provider key); the "client" fed study is published data in the client template; no measured
dissolution profile is public, so the dissolution item is waived and the tablet's release comes from the published
model. A campaign counts as evidence only on real PK-Sim (`MODELER_ENGINE_COMMAND` on the server).
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
SNAPSHOT = REPO / "services" / "engine-worker" / "golden" / "fixtures" / "Dapagliflozin-Model.json"
PROPOSAL = Path(__file__).resolve().parent / "dapagliflozin" / "proposal.md"
OSP_MODEL_URL = "https://github.com/Open-Systems-Pharmacology/Dapagliflozin-Model"
CLIENT_STUDY = "kasichayanula-2011a-fed"
CLIENT_ID = "KAS-2011A-FED"                      # the study id the mock client uses in its workbook
KIT_NOTE = "T-56 proof kit"


# The brief, filled by hand from the mock proposal: (path, value, proposal section).
BRIEF = (
    ("proj.title", "PBPK model of dapagliflozin: food effect of the 10 mg IR tablet", "title"),
    ("proj.type", "research", "title (mock proof project)"),
    ("drug.modality", "small_molecule", "§1"),
    ("qoi.text", "Effect of a meal on dapagliflozin AUC and Cmax after a single 10 mg IR tablet", "§2"),
    ("qoi.context_of_use", ("Predict fed versus fasted exposure of the 10 mg IR tablet in healthy adults to support the "
                            "food-effect discussion; it does not replace a clinical food-effect study"), "§2"),
    ("qoi.applications", ["APP-01 model build and verification", "APP-12 food effect"], "§1–2"),
    # the ICH M15 ratings and model risk are the person's, never assumed (a plan without a risk cannot be signed): a
    # food-effect discussion that does not replace the clinical study is medium influence, medium consequence
    ("m15.influence_rating", "medium", "the person's ICH M15 rating (§2: supports, does not replace, the clinical study)"),
    ("m15.consequence_rating", "medium", "the person's ICH M15 rating (§2: a label discussion, not a dosing decision)"),
    ("acceptance.tier", "medium", "the person's ICH M15 rating (§2: supports, does not replace, the clinical study)"),
    # the scope gates of D-28: a full PBPK model of a systemic small molecule, an IR tablet
    ("scope.pbpk_model", "full", "§1 (a PBPK model in PK-Sim)"),
    ("scope.site_of_action", "systemic", "§2 (exposure: AUC, Cmax)"),
    ("scope.formulation_types", ["ir_tablet"], "§3"),
    ("scope.platform", "PK-Sim (Open Systems Pharmacology Suite)", "§1"),
    ("scope.pathways", ["hepatic_metabolism", "renal_filtration"], "§6"),
    ("scope.pathways_stated", ["UGT1A9 glucuronidation", "renal (glomerular filtration)"], "§6"),
    ("products[0].name", "Dapagliflozin 10 mg IR tablet", "§3"),
    ("products[0].role", "TEST", "§3"),
    ("products[0].strength", 10, "§3"),
    ("products[0].release", "IR", "§3"),
    ("scenarios[0].population", "healthy adults", "§4"), ("scenarios[0].route", "oral", "§4"),
    ("scenarios[0].dose", 10, "§4"), ("scenarios[0].food_state", "fasted", "§4"),
    ("scenarios[1].population", "healthy adults", "§4"), ("scenarios[1].route", "oral", "§4"),
    ("scenarios[1].dose", 10, "§4"), ("scenarios[1].food_state", "fed", "§4"),
    ("data_plan[0].item", "dissolution profiles of the 10 mg tablet", "§5"),
    ("data_plan[0].category", "dissolution", "§5"), ("data_plan[0].provider", "CLIENT", "§5"),
    ("data_plan[1].item", "one fed pharmacokinetic study", "§5"),
    ("data_plan[1].category", "clinical_pk_fed", "§5"), ("data_plan[1].provider", "CLIENT", "§5"),
    ("data_plan[2].item", "physicochemistry, binding, elimination, IV and oral clinical PK", "§5"),
    ("data_plan[2].category", "clinical_pk_oral", "§5"), ("data_plan[2].provider", "LITERATURE", "§5"),
)


# --- the inputs, from the published model --------------------------------------------------------------------


def load_reference():
    from pbpk_domain.reference import import_osp_snapshot

    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    return snapshot, import_osp_snapshot(snapshot, source="OSP Dapagliflozin model")


def evidence_items(imported) -> list[dict[str, Any]]:
    """One manual-evidence body per parameter of the published model, citing the model and its ValueOrigin (the same
    rules as the Inputs step's published-model source, `modeler_project.published_model`)."""
    from modeler_project.published_model import evidence_bodies

    return evidence_bodies(imported, model="Dapagliflozin", url=OSP_MODEL_URL, note=f"{KIT_NOTE}: ")


def dataset_bodies(imported, snapshot: dict) -> tuple[list[dict[str, Any]], list[str]]:
    """The literature datasets (every imported study but the client's), with their publication and figure."""
    from modeler_project.published_model import dataset_bodies as bodies
    from modeler_project.published_model import statistics

    return bodies(imported, statistics(snapshot), model="Dapagliflozin", label=KIT_NOTE, leave_out=(CLIENT_STUDY,))


def client_workbook(imported) -> bytes:
    """The client-data template with the fed study (published data, delivered as the mock client's study)."""
    from openpyxl import load_workbook

    from modeler_intake.client_template import build_template
    from modeler_project.published_model import study_reference

    row = next(s for s in imported.studies if s["study_id"] == CLIENT_STUDY)
    url, locator, _note = study_reference(row["reference"])
    wb = load_workbook(io.BytesIO(build_template()))
    header = [str(c.value).rstrip("*") for c in wb["Studies"][1]]
    study = {"study_id": CLIENT_ID, "reference": f"{url} ({locator})",
             "design": "SD", "population": "healthy", "n": row["n"], "route": "oral", "dose": row["dose_mg"],
             "dose_unit": "mg", "formulation": "ir_tablet", "food_state": "fed"}
    wb["Studies"].append([study.get(h) for h in header])
    profile = row["profile"]
    for t, v in zip(profile["times"], profile["values"], strict=True):
        wb["PK_Summary"].append([study["study_id"], None, t, profile.get("time_unit", "h"), "arithmetic_mean",
                                 v, None, None, row["n"], profile["unit"]])
    wb["README"].append([(f"{KIT_NOTE}: mock client delivery. The study is Kasichayanula 2011a, fed arm ({url}, {locator}), "
                          "as carried by the published OSP Dapagliflozin model — published data, not a client measurement.")])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


# --- the API -------------------------------------------------------------------------------------------------


class Api:
    """A thin client over the write API: raises with the API's own reason on any refusal."""

    def __init__(self, client):
        self.client = client

    def _check(self, response, what: str):
        if response.status_code >= 400:
            raise RuntimeError(f"{what}: {response.status_code} {response.text[:600]}")
        return response.json().get("data", response.json())

    def get(self, path: str, what: str = ""):
        return self._check(self.client.get(path), what or f"GET {path}")

    def post(self, path: str, what: str = "", **kw):
        return self._check(self.client.post(path, **kw), what or f"POST {path}")

    def put(self, path: str, what: str = "", **kw):
        return self._check(self.client.put(path, **kw), what or f"PUT {path}")


def requirement_ids(api: Api, pid: str) -> dict[str, str]:
    """Template item id → the data plan's id (a per-product item is `REQ-…@<product>`)."""
    items = api.get(f"/api/v1/projects/{pid}/requirements", "P1 data plan")["matrix"]["items"]
    return {i["req_id"].split("@", 1)[0]: i["req_id"] for i in items}


def prepare(api: Api, log=print) -> dict[str, Any]:
    snapshot, imported = load_reference()
    started = api.post("/api/v1/projects:initiate", "P0 initiate",
                       data={"drug_name": "Dapagliflozin", "extract": "false"},
                       files=[("files", ("proposal.md", PROPOSAL.read_bytes(), "text/markdown"))])
    pid = started["project_id"]
    log(f"P0  project {pid} from the mock proposal")
    changes = [{"path": path, "status": "EDITED", "value": value, "note": f"mock proposal {section}"}
               for path, value, section in BRIEF]
    api.put(f"/api/v1/projects/{pid}/brief", "P1 brief", json={"changes": changes, "reason": "filled by hand from the mock proposal"})
    steps = {s["step"]: s for s in api.get(f"/api/v1/projects/{pid}/steps", "steps")["steps"]}
    if steps["start"]["state"] != "done":
        raise RuntimeError("Start still needs: " + "; ".join(steps["start"]["reasons"]))
    log(f"P1  brief filled ({len(BRIEF)} fields, each citing the proposal); the data plan follows it; Start done")

    ids = requirement_ids(api, pid)
    proposed = {"evidence": [], "datasets": [], "processes": {}, "requirements": ids}
    for body in evidence_items(imported):
        process = body.pop("_process", None)
        body["req_id"] = ids.get(body["req_id"], body["req_id"])
        item = api.post(f"/api/v1/projects/{pid}/evidence", f"P2 evidence {body['target']}", json=body)
        proposed["evidence"].append({"id": item["id"], "target": body["target"], "value": body["value"], "unit": body["unit"]})
        if process:
            proposed["processes"][body["target"].rpartition(".")[0]] = process.split(":", 1)[0]
    bodies, skipped = dataset_bodies(imported, snapshot)
    for body in bodies:
        ds = api.post(f"/api/v1/projects/{pid}/datasets", f"P2 dataset {body['study']['study_id']}", json=body)
        proposed["datasets"].append({"id": ds["id"], "study_id": body["study"]["study_id"]})
    log(f"P2  {len(proposed['evidence'])} parameter values and {len(proposed['datasets'])} clinical datasets proposed "
        f"(source: the published OSP model and its publications); {len(skipped)} not proposed")
    upload = api.post(f"/api/v1/projects/{pid}/client-data", "P3 client workbook",
                      files=[("files", ("ModelerOne_ClientData_dapagliflozin.xlsx", client_workbook(imported),
                                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))])
    log(f"P3  client workbook read ({', '.join(r['file'] for r in upload['read'])})")
    client = next(s for s in imported.studies if s["study_id"] == CLIENT_STUDY)
    return {"project_id": pid, "proposed": proposed, "skipped": skipped, "imported_notes": list(imported.notes),
            "client_formulation": client.get("formulation_name") or "Dissolved"}


def accept(api: Api, pid: str, prepared: dict[str, Any], *, name: str, log=print) -> dict[str, Any]:
    """The owner's decisions on what `prepare` proposed, up to the MAP signature (which is the owner's, in the UI). Every
    value and dataset flows in with nothing to accept (D-27); what is left is what a person settles on the Inputs step:
    the values held until checked, the process type of each pathway, a study's formulation and its individual."""
    reason = f"checked by {name} ({KIT_NOTE}): taken verbatim from the published OSP Dapagliflozin model, cited"
    release = prepared["proposed"]["requirements"].get("REQ-form.release", "REQ-form.release")
    api.put(f"/api/v1/projects/{pid}/requirements/{release}", "Start: release model from the literature",
            json={"provider": "LITERATURE", "reason": "no measured dissolution profile is public; the tablet's release "
                                                       "(Weibull) is taken from the published model"})
    # assemble first: the assembly names what is held until a person checks it and the structure choices it needs
    assembled = api.post(f"/api/v1/projects/{pid}/inputs:assemble", "Inputs: assemble")
    held = [item for t in assembled.get("todo", []) if t["kind"] == "review" for item in t.get("items", [])]
    for item in held:
        numeric = isinstance(item["value"], int | float)
        body = {"state": "ACCEPTED", "reason": reason,
                **({"value_pksim": item["value"], "unit_pksim": item["unit"]} if numeric else {})}
        api.post(f"/api/v1/projects/{pid}/evidence/{item['id']}:decide", f"Inputs: check {item['target']}", json=body)
    log(f"Inputs: {len(held)} held values checked (the published model's own); every other value and dataset flowed in")
    for key, value in prepared["proposed"]["processes"].items():
        assembled = api.put(f"/api/v1/projects/{pid}/inputs/choices", f"Inputs: process {key}",
                            json={"kind": "process", "key": key, "value": value,
                                  "reason": "the process type the published model uses"})
    # the client's tablet study names no formulation: simulated as the published model simulates it
    client_formulation = prepared["client_formulation"]
    assembled = api.put(f"/api/v1/projects/{pid}/inputs/choices", f"Inputs: formulation of {CLIENT_ID}",
                        json={"kind": "formulation", "key": CLIENT_ID, "value": client_formulation,
                              "reason": f"the fed arm's tablet release is not reported; simulated as the published model "
                                        f"simulates its tablet studies ({client_formulation})"})
    # D-29: a study the published model simulates in its default individual gets the healthy adult default explicitly
    # (never silently); the MAP lists each as a limitation
    register = api.get(f"/api/v1/projects/{pid}/evidence", "evidence register")
    by_study = {d["study"]["study_id"]: d["id"] for d in register.get("datasets", []) if d.get("state") != "REJECTED"}
    unstated = [t["target"] for t in assembled.get("todo", []) if t["kind"] == "demographics" and t["target"] in by_study]
    for sid in unstated:
        api.post(f"/api/v1/projects/{pid}/datasets/{by_study[sid]}:study", f"Inputs: demographics of {sid}",
                 json={"demographics_choice": "healthy_adult_default"})
    if unstated:
        assembled = api.post(f"/api/v1/projects/{pid}/inputs:assemble", "Inputs: assemble")
    readiness = assembled["readiness"]["content"]
    if not readiness.get("ready"):
        raise RuntimeError("Inputs readiness: " + json.dumps(readiness, default=str)[:1500])
    log("Inputs: CPF v1 assembled from every value not excluded; readiness passed (nothing accepted: D-27)")
    plan = moved = api.get(f"/api/v1/projects/{pid}/plan", "P5 plan")
    for _ in range(20):
        open_warnings = [v for v in moved.get("violations", []) if v.get("severity") == "warning" and not v.get("acknowledged")]
        if not open_warnings:
            break
        v = open_warnings[0]
        moved = api.post(f"/api/v1/projects/{pid}/plan/violations/{v['id']}:acknowledge", "P5 acknowledge",
                         json={"reason": f"accepted by {name} as a limitation of the proof"})
    roles: dict[str, int] = {}
    for placement in plan["plan"]["placements"].values():
        roles[placement["role"]] = roles.get(placement["role"], 0) + 1
    log(f"P5  plan: the MS-01 default ({', '.join(f'{r} {n}' for r, n in sorted(roles.items()))}); fits: "
        f"{', '.join(plan['plan'].get('fits') or []) or 'none — every value is the published one'}; blocking: "
        f"{moved.get('blocking')}")
    log(f"     → review the plan on /projects/{pid}/plan (moves and fits are the reviewer's), sign it (MIDD lead, "
        "step-up), then: run_t56.py start")
    return moved


def start(api: Api, pid: str, log=print) -> str:
    """P6: start the campaign from the signed MAP's staged inputs (what "Run the campaign" does on the canvas)."""
    plan = api.get(f"/api/v1/projects/{pid}/plan", "P5 plan")
    signed = plan.get("map") or {}
    if signed.get("status") != "APPROVED" or not signed.get("campaign"):
        raise RuntimeError("the MAP is not signed: the MIDD lead signs it on the plan page first")
    started = api.post(f"/api/v1/projects/{pid}/campaigns", "P6 start", json=signed["campaign"])
    log(f"P6  campaign {started['campaign_id']} started from MAP v{signed.get('version')}")
    return started["campaign_id"]


# --- the trace (T-56 acceptance) -----------------------------------------------------------------------------


def trace(api: Api, pid: str, campaign_id: str) -> tuple[str, list[str]]:
    """Every number's chain to its source, as Markdown, and the broken links."""
    campaign = api.get(f"/api/v1/campaigns/{campaign_id}", "campaign")
    inputs = api.get(f"/api/v1/projects/{pid}/inputs", "inputs")
    register = api.get(f"/api/v1/projects/{pid}/evidence", "evidence")
    evidence = {e["id"]: e for e in register.get("evidence", [])}
    datasets = {d["id"]: d for d in register.get("datasets", [])}
    broken: list[str] = []
    lines = [f"# T-56 trace — campaign `{campaign_id}`", "",
             f"Engine: {(campaign.get('engine') or {}).get('kind', 'unknown')} (`{(campaign.get('engine') or {}).get('command', '')}`)."
             + (" **Not a PBPK result: a software fixture ran this campaign.**"
                if (campaign.get("engine") or {}).get("kind") != "pksim" else ""), "",
             "## Parameters (CPF v1 → evidence → source)", "",
             "| Parameter | Value | Evidence | Source | Quote |", "|---|---|---|---|---|"]
    parameters = inputs.get("records") or []
    if not parameters:
        broken.append("the project has no assembled CPF: nothing to trace")
    for p in parameters:
        prov = p.get("provenance") or {}
        ref = prov.get("evidence") or ""
        item = evidence.get(ref.split("@", 1)[0]) if ref else None
        if item is None:
            broken.append(f"parameter {p['id']}: no evidence item behind it ({ref or 'none recorded'})")
            lines.append(f"| `{p['id']}` | {p.get('value')} {p.get('unit') or ''} | — | — | — |")
            continue
        src = item.get("source") or {}
        where = src.get("doi") or src.get("pmid") or src.get("url") or src.get("doc_sha256") or ""
        if not where:
            broken.append(f"parameter {p['id']}: evidence {item['id']} cites no document, DOI, PMID or URL")
        lines.append(f"| `{p['id']}` | {p.get('value')} {p.get('unit') or ''} | {ref} ({item.get('state')}) | {where} "
                     f"{src.get('locator', '')} | {str(item.get('quote', ''))[:80]} |")
    lines += ["", "## Studies (judged data → dataset → publication)", "", "| Study | Origin | Dataset | Source |", "|---|---|---|---|"]
    origins = campaign.get("observedOrigins") or {}
    # every dataset not excluded is used (D-27): the one a study was judged on is the one not left out
    by_study = {d.get("study", {}).get("study_id"): d for d in datasets.values() if d.get("state") != "REJECTED"}
    for sid, origin in sorted(origins.items()):
        ds = by_study.get(sid)
        src = (ds or {}).get("source") or {}
        where = src.get("doi") or src.get("pmid") or src.get("url") or src.get("doc_sha256") or src.get("title") or ""
        if ds is None or not where:
            broken.append(f"study {sid}: {'no dataset in use' if ds is None else 'its dataset cites no source'}")
        lines.append(f"| `{sid}` | {origin} | {(ds or {}).get('id', '—')} | {where} {src.get('locator', '')} |")
    lines += ["", "## Stages (outcome, rounds and notes)", ""]
    for stage in campaign.get("stages", []):
        if stage.get("status") == "PENDING" and not stage.get("rounds"):
            continue
        lines.append(f"- **{stage['stage']}** {stage.get('label', '')}: {stage.get('status')}")
        for r in stage.get("rounds", []):
            found = "; ".join((r.get("findings") or [])[:4])
            lines.append(f"  - round {r['round']}: {r['action']} → {r['verdict']}" + (f" ({found})" if found else ""))
        lines += [f"  - note: {n}" for n in stage.get("notes", [])]
    fits = [n for st in campaign.get("stages", []) for n in st.get("notes", []) if n.startswith("Parameter identification")]
    lines.append(f"\nParameter identifications run: {len(fits)}.")
    lines += ["", "## Changes during the campaign (ledger)", ""]
    for e in (campaign.get("ledger") or {}).get("entries", []):
        changed = ", ".join(f"{c['parameter']} {c.get('before')} → {c.get('after')}" for c in e.get("changes", []))
        lines.append(f"- {e['seq']}. {e['stage']} (cycle {e.get('cycle', 1)}) {e['kind']}: {e['reason']}"
                     + (f" — {changed}" if changed else ""))
    package = campaign.get("package") or {}
    lines += ["", "## MAR", ""]
    if not package:
        lines.append("No MAR yet: the campaign has not reached S7.")
    else:
        lines.append(f"Report issues: {len(package.get('report_issues', []))}; reproduction "
                     f"{'passed' if (package.get('reproduction') or {}).get('passes') else 'NOT passed'}.")
        broken += [f"MAR: {i.get('kind')} at {i.get('location')}: {i.get('detail')}" for i in package.get("report_issues", [])]
        response = api.client.get(f"/api/v1/campaigns/{campaign_id}/package/mar.md")
        if response.status_code == 200:
            rows = mar_evidence_index(response.text)
            lines.append(f"Evidence index: {len(rows)} entries (every number in the report resolves to one).")
            broken += [f"MAR evidence {ref}: no source" for ref, _value, source in rows if not source.strip()]
        else:
            broken.append(f"MAR: the Markdown report could not be read ({response.status_code})")
    lines += ["", "## Broken links", ""] + ([f"- {b}" for b in broken] or ["None: every number traces to its source."])
    return "\n".join(lines) + "\n", broken


def pq_record(api: Api, campaign_id: str, broken: list[str]) -> dict[str, Any]:
    """The Performance Qualification record of this proof campaign (``pq/1``, judged by
    `pbpk_domain.report.validation_pack.pq_checks`): what ran it, where, how long, and whether its package holds."""
    from datetime import UTC, datetime

    from pbpk_domain.report.validation_pack import pq_checks

    campaign = api.get(f"/api/v1/campaigns/{campaign_id}", "campaign")
    package = campaign.get("package") or {}
    facts = {"engine_kind": (campaign.get("engine") or {}).get("kind"), "deployment": campaign.get("deployment"),
             "status": campaign.get("status"), "package": bool(package),
             "report_issues": len(package.get("report_issues", [])) if package else None,
             "reproduction": bool((package.get("reproduction") or {}).get("passes")), "broken": len(broken),
             "elapsed_seconds": campaign.get("elapsedSeconds"),
             "parameter_identifications": [n for st in campaign.get("stages", []) for n in st.get("notes", [])
                                           if n.startswith("Parameter identification")],
             "stages": [{"stage": s["stage"], "status": s["status"]} for s in campaign.get("stages", [])]}
    return {"schema": "pq/1", "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "subject": f"T-56 campaign {campaign_id} ({campaign.get('compound', '')})", "facts": facts,
            "checks": pq_checks(facts)}


def mar_evidence_index(markdown: str) -> list[tuple[str, str, str]]:
    """(reference, value or title, source) of every row of the MAR's evidence index."""
    rows, inside = [], False
    for line in markdown.splitlines():
        if line.strip() == "## Evidence index":
            inside = True
            continue
        if inside and line.startswith("## "):
            break
        if inside and line.startswith("|") and not line.startswith(("| Reference", "| ---")):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 3:
                rows.append((cells[0], cells[1], cells[2]))
    return rows


# --- command line --------------------------------------------------------------------------------------------


def _client(args):
    import httpx

    return httpx.Client(base_url=args.api, headers={"Authorization": f"Bearer {args.token}"}, timeout=120)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=("prepare", "accept", "start", "watch", "trace"))
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--token", required=True, help="the person's own access token (never a password)")
    parser.add_argument("--project")
    parser.add_argument("--campaign")
    parser.add_argument("--as", dest="name", help="accept: the person deciding (their own name)")
    parser.add_argument("--out", type=Path, default=Path("out/t56"))
    args = parser.parse_args(argv)
    api = Api(_client(args))
    args.out.mkdir(parents=True, exist_ok=True)
    if args.command == "prepare":
        result = prepare(api)
        (args.out / "prepared.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
        print(f"next: review on /projects/{result['project_id']}, then accept --project {result['project_id']} --as <name>")
        return 0
    if args.command == "accept":
        if not (args.project and args.name):
            parser.error("accept needs --project and --as")
        prepared = json.loads((args.out / "prepared.json").read_text(encoding="utf-8"))
        accept(api, args.project, prepared, name=args.name)
        return 0
    if args.command == "start":
        if not args.project:
            parser.error("start needs --project")
        print(start(api, args.project))
        return 0
    if args.command == "watch":
        while True:
            c = api.get(f"/api/v1/campaigns/{args.campaign}")
            print(f"{time.strftime('%H:%M:%S')} {c.get('status')} at {c.get('currentStage')}")
            if c.get("status") not in ("RUNNING", "QUEUED"):
                return 0
            time.sleep(30)
    report, broken = trace(api, args.project, args.campaign)
    (args.out / "trace.md").write_text(report, encoding="utf-8")
    pq = pq_record(api, args.campaign, broken)
    (args.out / "pq.json").write_text(json.dumps(pq, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(report)
    for c in pq["checks"]:
        print(f"{c['id']}  {c['result']:<11} {c['item']}: {c['found']}" + (f" ({c['note']})" if c["note"] else ""))
    print(f"PQ record: {args.out / 'pq.json'} (the validation pack's --pq)")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
