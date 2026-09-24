#!/usr/bin/env python3
"""Load every example the pipeline has been proven on into the running tool, as projects a user opens and works in.

    uv run python deploy/showcase/seed_examples.py                       # every example, 3 campaigns at a time
    uv run python deploy/showcase/seed_examples.py --only rifampicin     # examples whose id contains "rifampicin"
    uv run python deploy/showcase/seed_examples.py --no-campaigns        # projects, CPFs, studies and MAPs only

Each example is created through the API exactly as a user builds it in the browser: project, CPF (every compound of
a model system, and its links), studies, MAP (generated and signed), campaign. Nothing is pre-computed or copied in:
every number the tool then shows comes from the campaign it runs on this machine's engine (PK-Sim on the server).
The examples are the published OSP library models with their real clinical data (`services/engine-worker/golden/
fixtures`, SOURCES.md), run as published ("as-is": the published parameters, evaluated stage by stage) and, for the
two plan-exit drugs, refitted ("refit": the parameters MS-01 lets S1-S3 fit, freed from their published values); the
illustrative Aciclovir check is included and labelled as such.

Idempotent: an example whose project exists (same name) is skipped. Campaigns run a few at a time (--parallel) so
the engine host is not oversubscribed; one that stops at a human gate (S6 signature, an escalation) is left for the
user to decide in the review inbox, as MS-01 intends. A log of every step is written to --out.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "services" / "engine-worker" / "golden" / "fixtures"
TOKEN = os.environ.get("MODELER_SEED_TOKEN", "dev")  # the single-node dev verifier (MODELER_DEV_AUTH); DEV ONLY
FINAL = {"COMPLETED", "ESCALATED", "ABORTED", "FAILED", "AWAITING_SIGNATURE"}
PREFIX = "Example · "

# Model systems: parent with enantiomers / metabolites, simulated together (docs/plans/2026-09-24-multi-compound.md).
SYSTEMS = {
    "Verapamil": "R/S-verapamil and norverapamil with their published sums; CYP3A4 metabolism, P-gp",
    "Omeprazole": "esomeprazole and R-omeprazole; CYP2C19 extensive and poor metabolisers, CYP3A4",
    "Dabigatran": "dabigatran etexilate prodrug, dabigatran and its glucuronide; esterases, P-gp, UGT",
    "Itraconazole": "itraconazole with hydroxy-, keto- and N-desalkyl-itraconazole; CYP3A4, solubility per product",
}
REFIT = ("dapagliflozin-osp", "rifampicin-osp")  # plan exit (docs/plans/2026-09-24-remaining-to-goal.md)


@dataclass
class Example:
    id: str
    name: str
    compound: str                        # the fitted compound (a system's parent)
    question: str
    real_data: bool
    cpfs: dict[str, dict[str, Any]]      # compound -> CPF (JSON)
    studies: list[dict[str, Any]]
    links: dict[str, Any] | None = None  # a model system's links (PUT /system)
    notes: list[str] = field(default_factory=list)


def api(base: str, method: str, path: str, body: Any = None, timeout: float = 300) -> tuple[int, Any]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{base}{path}", data=data, method=method,
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw or b"null")
        except json.JSONDecodeError:
            return e.code, {"detail": raw.decode(errors="replace")[:600]}
    except (OSError, urllib.error.URLError, TimeoutError) as e:
        return 0, {"detail": f"{type(e).__name__}: {e}"}


def examples(base: str) -> list[Example]:
    """Every wizard template (the published single-compound models and the illustrative check), its refit twin for
    the plan-exit drugs, and every model system."""
    from pbpk_domain.cpf.models import CPF
    from pbpk_domain.reference.osp_import import import_osp_system
    from pbpk_domain.reference.refit import refit_cpf
    from pbpk_domain.system import links_of

    status, body = api(base, "GET", "/api/v1/templates")
    if status != 200:
        raise SystemExit(f"the API does not answer at {base}: {status} {body}")
    out: list[Example] = []
    for summary in body["data"]["templates"]:
        st, full = api(base, "GET", f"/api/v1/templates/{summary['id']}")
        if st != 200:
            print(f"  ! template {summary['id']}: {st} {full.get('detail')}", flush=True)
            continue
        t = full["data"]
        mode = "as published" if t["real_data"] else "illustrative"
        out.append(Example(id=f"{t['id']}-as-is", name=f"{PREFIX}{summary['compound']} ({mode})", compound=t["compound"],
                           question=t["question"], real_data=t["real_data"], cpfs={t["compound"]: t["cpf"]},
                           studies=t["studies"], notes=t.get("notes", [])))
        if t["id"] in REFIT:
            refit, freed = refit_cpf(CPF.model_validate(t["cpf"]))
            out.append(Example(id=f"{t['id']}-refit", name=f"{PREFIX}{summary['compound']} (refit S1-S3)",
                               compound=t["compound"], question=t["question"], real_data=True,
                               cpfs={t["compound"]: refit.model_dump(mode="json", exclude={"created_at"})},
                               studies=t["studies"],
                               notes=[f"freed for the fit: {', '.join(sorted(freed))}", *t.get("notes", [])]))
    for model, topic in SYSTEMS.items():
        imported = import_osp_system(json.loads((FIXTURES / f"{model}-Model.json").read_text(encoding="utf-8")))
        system = imported.system
        out.append(Example(
            id=f"{model.lower()}-system-as-is", name=f"{PREFIX}{model} system (as published)", compound=system.parents[0],
            question=f"Predict {model.lower()} and metabolite exposure in healthy adults ({topic})", real_data=True,
            cpfs={c.compound: c.model_dump(mode="json", exclude={"created_at"}) for c in system.compounds},
            studies=list(imported.studies), links=links_of(system).model_dump(mode="json"), notes=list(imported.notes)))
    return out


def create(base: str, ex: Example, log: dict[str, Any]) -> dict[str, Any] | None:
    """Project, CPFs, links, studies, MAP (prepared and signed). Returns the campaign start body, or None."""
    def step(name: str, status: int, payload: Any, ok: tuple[int, ...]) -> bool:
        log["steps"].append({"step": name, "http_status": status,
                             "detail": None if status in ok else (payload or {}).get("detail", payload)})
        return status in ok

    st, body = api(base, "POST", "/api/v1/projects", {
        "name": ex.name, "compound": ex.compound, "question": ex.question[:200], "model_risk": "medium"})
    if not step("create project", st, body, (201,)):
        return None
    project = body["data"]
    pid, qid = project["id"], (project.get("questions") or [{"id": "qoi-1"}])[0]["id"]
    log["project_id"] = pid
    for compound, cpf in ex.cpfs.items():
        st, body = api(base, "PUT", f"/api/v1/projects/{pid}/compounds/{compound}/cpf", cpf)
        if not step(f"put CPF {compound}", st, body, (200,)):
            return None
    if ex.links is not None:
        st, body = api(base, "PUT", f"/api/v1/projects/{pid}/system", ex.links)
        if not step("put system links", st, body, (200,)):
            return None
    st, body = api(base, "POST", f"/api/v1/projects/{pid}/studies", {"studies": ex.studies})
    if not step(f"upload {len(ex.studies)} studies", st, body, (201,)):
        return None
    st, body = api(base, "POST", f"/api/v1/projects/{pid}/questions/{qid}/campaign:prepare",
                   {"compound": ex.compound, "model_risk": "medium"})
    if not step("prepare campaign (MAP)", st, body, (200,)):
        return None
    prep = body["data"]
    st, body = api(base, "POST", f"/api/v1/projects/{pid}/signatures", {
        "meaning": "Approved", "record_type": "map_approval", "record_id": prep["map_id"],
        "record_sha256": prep["map_sha256"]})
    if not step("sign the MAP", st, body, (201,)):
        return None
    return {"project_id": pid, "body": {
        "compound": ex.compound, "map_id": prep["map_id"], "cpf_uri": prep["cpf_uri"], "cpf_sha256": prep["cpf_sha256"],
        "map_uri": prep["map_uri"], "observed_uri": prep["observed_uri"], "system_uri": prep.get("system_uri", ""),
        "system_sha256": prep.get("system_sha256", ""), "question": ex.question, "model_risk": "medium",
        "stages": prep.get("stages")}}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default=os.environ.get("MODELER_API_BASE", "http://127.0.0.1:8000"))
    ap.add_argument("--only", default="", help="substring filter on the example id")
    ap.add_argument("--parallel", type=int, default=3, help="campaigns running at once")
    ap.add_argument("--no-campaigns", action="store_true", help="create the projects but start no campaign")
    ap.add_argument("--out", type=Path, default=REPO / "reports" / "showcase")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(UTC).strftime("%Y%m%dT%H%MZ")

    _st, listed = api(args.base, "GET", "/api/v1/projects")
    existing = {p.get("name") for p in ((listed or {}).get("data") or {}).get("projects", [])}
    todo = [ex for ex in examples(args.base) if args.only.lower() in ex.id]
    print(f"{len(todo)} example(s); {sum(ex.name in existing for ex in todo)} already in the tool", flush=True)

    logs: list[dict[str, Any]] = []
    queue: list[tuple[Example, dict[str, Any], dict[str, Any]]] = []
    for ex in todo:
        log: dict[str, Any] = {"id": ex.id, "name": ex.name, "real_data": ex.real_data, "studies": len(ex.studies),
                               "steps": [], "notes": ex.notes[:20]}
        logs.append(log)
        if ex.name in existing:
            log["outcome"] = "exists (skipped)"
            print(f"= {ex.name}: already in the tool", flush=True)
            continue
        start = create(args.base, ex, log)
        if start is None:
            log["outcome"] = "not created: " + str(log["steps"][-1]["detail"])[:300]
            print(f"! {ex.name}: {log['outcome']}", flush=True)
            continue
        print(f"+ {ex.name}: project {start['project_id']}, {len(ex.studies)} studies, MAP signed", flush=True)
        log["outcome"] = "created"
        if not args.no_campaigns:
            queue.append((ex, start, log))

    running: list[tuple[Example, str, dict[str, Any]]] = []
    while queue or running:
        while queue and len(running) < args.parallel:
            ex, start, log = queue.pop(0)
            st, body = api(args.base, "POST", f"/api/v1/projects/{start['project_id']}/campaigns", start["body"])
            if st != 202:
                log["outcome"] = f"campaign refused: {st} {(body or {}).get('detail')}"
                print(f"! {ex.name}: {log['outcome']}", flush=True)
                continue
            log["campaign_id"] = body["campaign_id"]
            running.append((ex, body["campaign_id"], log))
            print(f"> {ex.name}: campaign {body['campaign_id']} started", flush=True)
        time.sleep(30)
        for item in list(running):
            ex, cid, log = item
            _st, got = api(args.base, "GET", f"/api/v1/campaigns/{cid}")
            status = ((got or {}).get("data") or {}).get("status")
            if status in FINAL:
                log["outcome"] = f"campaign {status}"
                running.remove(item)
                print(f"< {ex.name}: {status}", flush=True)
        (args.out / f"seed-{started_at}.json").write_text(json.dumps(logs, indent=1, ensure_ascii=False), encoding="utf-8")

    (args.out / f"seed-{started_at}.json").write_text(json.dumps(logs, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"done; log: {args.out / f'seed-{started_at}.json'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
