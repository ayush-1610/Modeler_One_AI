#!/usr/bin/env python3
"""T-56: Dapagliflozin from a mock technical proposal through P0 → P6, over the API (plan §19 T-56, Appendix A).

    uv run python deploy/proof/run_t56.py prepare --api http://localhost:8000 --token "$TOKEN" --out out/t56
    uv run python deploy/proof/run_t56.py accept  --api … --token … --project <id> --as "Full Name"
        → then, in the web app, the MIDD lead signs the plan on /projects/<id>/plan and runs the campaign (P6)
    uv run python deploy/proof/run_t56.py trace   --api … --token … --project <id> --campaign <cid> --out out/t56

**prepare** (P0 → P3 proposals): the project starts from the mock proposal (`dapagliflozin/proposal.md`); the brief is
filled by hand from it (the manual path, each field citing the proposal's section); the data plan is derived; every
parameter of the published OSP Dapagliflozin model is proposed as evidence citing the model (`OSP_LIBRARY`, its
ValueOrigin text as the quote); every clinical dataset the model carries is proposed with its publication and figure;
the fed study Kasichayanula 2011a is delivered in the client-data template as the "client" study. Nothing is accepted.

**accept** (the owner's decisions, run only by the owner with their own name): every item `prepare` proposed is
accepted with its reason, the gates P1–P4 are approved, and P5 is drafted: the MS-01 default plan, one fasted dose level
moved to external validation (Appendix A step 6), the validator's warnings acknowledged. It stops before the MAP
signature: a Part 11 signature is a person's act in the web app (step-up), never a script's.

**trace** (the T-56 acceptance, "a reviewer can trace every number in the MAR to its source"): every parameter of the
campaign's final CPF to its evidence item and source or to the fit that produced it, every judged study to its dataset
and publication, every number in the MAR's evidence index to its source; any broken link is listed and the exit
code is 1.

Honest limits, stated in the report: the inputs are the published model's values (a "literature" proof, not an A2 search;
A2 runs only with a provider key); the "client" fed study is published data in the client template; no measured
dissolution profile is public, so the dissolution item is waived and the tablet's release comes from the published
model. A campaign counts as evidence only on real PK-Sim (`MODELER_ENGINE_COMMAND` on the server).
"""

from __future__ import annotations

import argparse
import io
import json
import re
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

# The data-plan item each published-model parameter answers (by CPF id prefix, most specific first). A parameter with
# no item of its own is carried with the item of its group, and the evidence says so.
REQUIREMENT_OF = (
    ("phys.halogens.", "REQ-phys.halogens"), ("phys.mw", "REQ-phys.mw"), ("phys.logp", "REQ-phys.logp"),
    ("phys.pka.", "REQ-phys.pka"), ("phys.solubility.", "REQ-phys.solubility.ref"), ("bind.fu", "REQ-bind.fu"),
    ("bind.partner", "REQ-bind.partner"), ("perm.intestinal", "REQ-perm.intestinal"), ("elim.renal.", "REQ-elim.renal"),
    ("elim.", "REQ-elim.pathway"), ("expr.", "REQ-expr.profiles"), ("form.", "REQ-form.release"),
    ("indiv.", "REQ-sys.demographics"), ("sim.", "REQ-dist.bp_ratio"), ("dist.", "REQ-dist.bp_ratio"),
    ("perm.cellular", "REQ-dist.bp_ratio"),
)
_OWN_ITEM = {"REQ-phys.mw", "REQ-phys.logp", "REQ-bind.fu", "REQ-bind.partner", "REQ-perm.intestinal", "REQ-elim.renal"}

# The brief, filled by hand from the mock proposal: (path, value, proposal section).
BRIEF = (
    ("proj.title", "PBPK model of dapagliflozin: food effect of the 10 mg IR tablet", "title"),
    ("proj.type", "research", "title (mock proof project)"),
    ("drug.modality", "small_molecule", "§1"),
    ("qoi.text", "Effect of a meal on dapagliflozin AUC and Cmax after a single 10 mg IR tablet", "§2"),
    ("qoi.context_of_use", ("Predict fed versus fasted exposure of the 10 mg IR tablet in healthy adults to support the "
                            "food-effect discussion; it does not replace a clinical food-effect study"), "§2"),
    ("qoi.applications", ["APP-01 model build and verification", "APP-12 food effect"], "§1–2"),
    ("scope.platform", "PK-Sim (Open Systems Pharmacology Suite)", "§1"),
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
_STAT = {"ArithmeticMean": "arithmetic_mean", "GeometricMean": "geometric_mean", "Median": "median"}
_REF = re.compile(r"\((https?://[^,\s)]+),\s*([^)]*)\)")


# --- the inputs, from the published model --------------------------------------------------------------------


def requirement_of(cpf_id: str) -> str:
    return next(req for prefix, req in REQUIREMENT_OF if cpf_id == prefix.rstrip(".") or cpf_id.startswith(prefix))


def load_reference():
    from pbpk_domain.reference import import_osp_snapshot

    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    return snapshot, import_osp_snapshot(snapshot, source="OSP Dapagliflozin model")


def statistics(snapshot: dict) -> dict[str, str]:
    """Study id → the statistic its observed series is (harvested from the snapshot's quantity path)."""
    from pbpk_domain.reference.osp_import import _props, _study_id

    out = {}
    for dataset in snapshot.get("ObservedData", []):
        path = ((dataset.get("Columns") or [{}])[0].get("QuantityInfo") or {}).get("Path", "")
        kind = path.rsplit("|", 1)[-1]
        if kind in _STAT:
            out[_study_id(_props(dataset), dataset["Name"])] = _STAT[kind]
    return out


def evidence_items(imported) -> list[dict[str, Any]]:
    """One manual-evidence body per parameter of the published model, citing the model and its ValueOrigin."""
    out = []
    for record in imported.cpf.parameters:
        req = requirement_of(record.id)
        prov = record.provenance
        origin = prov.reference if prov and prov.reference else imported.source
        fitted = record.status.value == "FITTED"
        note = (f"{KIT_NOTE}: value of the published OSP Dapagliflozin model"
                + ("; identified by parameter identification in that model" if fitted else "")
                + ("" if req in _OWN_ITEM else f"; carried with {req} (no data-plan item of its own)"))
        out.append({
            "req_id": req, "target": record.id, "value": record.value, "unit": record.unit, "source_type": "OSP_LIBRARY",
            "quote": origin, "locator": "PK-Sim snapshot, compound Dapagliflozin", "url": OSP_MODEL_URL,
            "title": "Open Systems Pharmacology — Dapagliflozin model (PK-Sim snapshot)",
            "conditions": {"value origin": (prov.source_type if prov else "published model")}, "note": note,
            **({"_process": record.engine_binding.process} if record.engine_binding and record.engine_binding.process
               and record.id.startswith("elim.") else {}),
        })
    return out


def _reference(text: str) -> tuple[str | None, str, str]:
    """(url, locator, import note) from an imported study's reference text."""
    match = _REF.search(text or "")
    note = text.split("Import:", 1)[1].strip() if "Import:" in (text or "") else ""
    return (match.group(1), match.group(2).strip(), note) if match else (None, "", note)


def dataset_bodies(imported, stats: dict[str, str]) -> tuple[list[dict[str, Any]], list[str]]:
    """The literature datasets (every imported study but the client's), with their publication and figure."""
    out, skipped = [], []
    for row in imported.studies:
        sid = row["study_id"]
        if sid == CLIENT_STUDY:
            continue
        statistic = stats.get(sid)
        profile = row.get("profile")
        if statistic is None or not profile:
            skipped.append(f"{sid}: {'no profile' if not profile else 'statistic not stated in the snapshot'}")
            continue
        url, locator, note = _reference(row.get("reference", ""))
        study = {k: v for k, v in row.items() if k not in ("profile", "reference")}
        out.append({
            "kind": "profile", "study": study, "time_unit": profile.get("time_unit", "h"), "unit": profile["unit"],
            "series": [{"name": "mean", "statistic": statistic, "times": profile["times"], "values": profile["values"],
                        "n": row.get("n")}],
            "origin": "OSP_LIBRARY", "purpose": "model_building",
            "source": {"url": url, "locator": locator, "title": f"OSP Dapagliflozin model observed data: {row['reference'].split(' (')[0]}"},
            "note": f"{KIT_NOTE}; import: {note}" if note else KIT_NOTE,
        })
    return out, skipped


def client_workbook(imported) -> bytes:
    """The client-data template with the fed study (published data, delivered as the mock client's study)."""
    from openpyxl import load_workbook

    from modeler_intake.client_template import build_template

    row = next(s for s in imported.studies if s["study_id"] == CLIENT_STUDY)
    url, locator, _note = _reference(row["reference"])
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
    api.post(f"/api/v1/projects/{pid}/requirements:derive", "P1 data plan")
    log(f"P1  brief filled ({len(BRIEF)} fields, each citing the proposal); data plan derived")

    ids = requirement_ids(api, pid)
    proposed = {"evidence": [], "datasets": [], "processes": {}, "requirements": ids}
    for body in evidence_items(imported):
        process = body.pop("_process", None)
        body["req_id"] = ids.get(body["req_id"], body["req_id"])
        item = api.post(f"/api/v1/projects/{pid}/evidence", f"P2 evidence {body['target']}", json=body)
        proposed["evidence"].append({"id": item["id"], "target": body["target"], "value": body["value"], "unit": body["unit"]})
        if process:
            proposed["processes"][body["target"].rpartition(".")[0]] = process.split(":", 1)[0]
    bodies, skipped = dataset_bodies(imported, statistics(snapshot))
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
    """The owner's decisions on what `prepare` proposed, up to the MAP signature (which is the owner's, in the UI)."""
    reason = f"accepted by {name} ({KIT_NOTE}): taken verbatim from the published OSP Dapagliflozin model, cited"
    api.post(f"/api/v1/projects/{pid}/brief:approve", "P1 brief approval", json={"note": f"approved by {name}"})
    release = prepared["proposed"]["requirements"].get("REQ-form.release", "REQ-form.release")
    api.put(f"/api/v1/projects/{pid}/requirements/{release}", "P1 release model from the literature",
            json={"provider": "LITERATURE", "reason": "no measured dissolution profile is public; the tablet's release "
                                                       "(Weibull) is taken from the published model"})
    api.post(f"/api/v1/projects/{pid}/requirements:approve", "P1 data plan approval", json={"note": f"approved by {name}"})
    for item in prepared["proposed"]["evidence"]:
        numeric = isinstance(item["value"], int | float)
        body = {"state": "ACCEPTED", "reason": reason,
                **({"value_pksim": item["value"], "unit_pksim": item["unit"]} if numeric else {})}
        api.post(f"/api/v1/projects/{pid}/evidence/{item['id']}:decide", f"P2 accept {item['target']}", json=body)
    for ds in prepared["proposed"]["datasets"]:
        api.post(f"/api/v1/projects/{pid}/datasets/{ds['id']}:decide", f"P2 accept {ds['study_id']}",
                 json={"state": "ACCEPTED", "reason": reason})
    view = api.get(f"/api/v1/projects/{pid}/evidence", "P2 register")
    for ds in view.get("datasets", []):
        if ds.get("state") == "PROPOSED" and ds.get("origin") == "CLIENT":
            api.post(f"/api/v1/projects/{pid}/datasets/{ds['id']}:decide", "P3 accept the client study",
                     json={"state": "ACCEPTED", "reason": f"accepted by {name}: the client's fed study as delivered"})
    log("P2  every proposed value and dataset accepted with its reason")
    # assemble first: the assembly names the structure choices it needs (the process type of each pathway)
    assembled = api.post(f"/api/v1/projects/{pid}/inputs:assemble", "P4 assemble")
    for key, value in prepared["proposed"]["processes"].items():
        assembled = api.put(f"/api/v1/projects/{pid}/inputs/choices", f"P4 process {key}",
                            json={"kind": "process", "key": key, "value": value,
                                  "reason": "the process type the published model uses"})
    # the client's tablet study names no formulation: simulated as the published model simulates it
    client_formulation = prepared["client_formulation"]
    assembled = api.put(f"/api/v1/projects/{pid}/inputs/choices", f"P4 formulation of {CLIENT_ID}",
                        json={"kind": "formulation", "key": CLIENT_ID, "value": client_formulation,
                              "reason": f"the fed arm's tablet release is not reported; simulated as the published model "
                                        f"simulates its tablet studies ({client_formulation})"})
    readiness = assembled["readiness"]["content"]
    if not readiness.get("ready"):
        raise RuntimeError("P4 readiness: " + json.dumps(readiness, default=str)[:1500])
    api.post(f"/api/v1/projects/{pid}/inputs:accept", "P4 accept", json={"note": f"accepted by {name}"})
    log("P4  CPF v1 assembled from the accepted evidence; readiness passed; inputs accepted")
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
    by_study = {d.get("study", {}).get("study_id"): d for d in datasets.values() if d.get("state") == "ACCEPTED"}
    for sid, origin in sorted(origins.items()):
        ds = by_study.get(sid)
        src = (ds or {}).get("source") or {}
        where = src.get("doi") or src.get("pmid") or src.get("url") or src.get("doc_sha256") or src.get("title") or ""
        if ds is None or not where:
            broken.append(f"study {sid}: {'no accepted dataset' if ds is None else 'its dataset cites no source'}")
        lines.append(f"| `{sid}` | {origin} | {(ds or {}).get('id', '—')} | {where} {src.get('locator', '')} |")
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
    print(report)
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
