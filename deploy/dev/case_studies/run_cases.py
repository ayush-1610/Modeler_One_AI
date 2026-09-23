#!/usr/bin/env python3
"""Drive every case study through the running API exactly as the UI does, and save the evidence.

Usage:  uv run python deploy/dev/case_studies/run_cases.py --base http://127.0.0.1:8040 --out reports/case-studies

For each case it performs the same sequence a user performs in the browser — create project, put CPF, upload
studies, generate the MAP, sign it, start the campaign, watch it — and records every request, response and the
final campaign state. Cases that are meant to be refused are recorded as such; a guardrail firing is a pass,
not an error.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from cases import CASES

TOKEN = "dev"


def api(base: str, method: str, path: str, body=None, timeout=120):
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
            return e.code, {"detail": raw.decode(errors="replace")[:400]}
    except (OSError, urllib.error.URLError, TimeoutError) as e:  # record connection problems verbatim
        return 0, {"detail": f"{type(e).__name__}: {e}"}


def run_case(base: str, case: dict) -> dict:
    """One case, end to end. Never raises: a refusal is data, not a crash."""
    started = time.monotonic()
    steps: list[dict] = []
    project_id = case["id"]

    def step(name, status, payload, note=""):
        steps.append({"step": name, "http_status": status, "note": note,
                      "response": payload if isinstance(payload, dict | list) else str(payload)})
        return status, payload

    st, body = step("create project", *api(base, "POST", "/api/v1/projects", {
        "name": case["title"], "compound": case["compound"], "question": case["narrative"][:120],
        "application": case["application"], "model_risk": case["model_risk"]}))
    if st != 201:
        return _result(case, steps, started, "blocked", "the project could not be created")
    project_id = body["data"]["id"]
    question_id = (body["data"].get("questions") or [{"id": "qoi-1"}])[0]["id"]

    st, body = step("put CPF", *api(base, "PUT",
                                    f"/api/v1/projects/{project_id}/compounds/{case['compound']}/cpf", case["cpf"]))
    cpf_view = body.get("data") if st == 200 else None
    if st != 200:
        return _result(case, steps, started, "blocked", "the CPF was rejected", project_id=project_id)

    if case["studies"]:
        st, body = step("upload studies", *api(base, "POST", f"/api/v1/projects/{project_id}/studies",
                                               {"studies": case["studies"]}))
    else:
        step("upload studies", 0, {"detail": "no studies in this case, by design"}, "skipped on purpose")

    st, body = step("prepare campaign", *api(base, "POST",
                                             f"/api/v1/projects/{project_id}/questions/{question_id}/campaign:prepare",
                                             {"compound": case["compound"], "model_risk": case["model_risk"],
                                              "stages": case["stages"]}))
    if st != 200:
        return _result(case, steps, started, "refused", _detail(body), project_id=project_id, cpf=cpf_view)
    prep = body["data"]

    step("sign the MAP", *api(base, "POST", f"/api/v1/projects/{project_id}/signatures", {
        "meaning": "Approved", "record_type": "map_approval",
        "record_id": prep["map_id"], "record_sha256": prep["map_sha256"]}))

    st, body = step("start campaign", *api(base, "POST", f"/api/v1/projects/{project_id}/campaigns", {
        "compound": case["compound"], "map_id": prep["map_id"], "cpf_uri": prep["cpf_uri"],
        "cpf_sha256": prep["cpf_sha256"], "map_uri": prep["map_uri"], "observed_uri": prep["observed_uri"],
        "model_risk": case["model_risk"], "stages": prep["stages"]}))
    if st != 202:
        return _result(case, steps, started, "refused", _detail(body), project_id=project_id, cpf=cpf_view)
    campaign_id = body.get("campaign_id")

    campaign = None
    for _ in range(90):
        time.sleep(2)
        _s, got = api(base, "GET", f"/api/v1/campaigns/{campaign_id}")
        campaign = (got or {}).get("data")
        if campaign and campaign.get("status") in ("COMPLETED", "ESCALATED", "ABORTED"):
            break
    step("run to completion", 200, {"final_status": (campaign or {}).get("status")})

    _s, esc = api(base, "GET", "/api/v1/escalations")
    escalations = [e for e in ((esc or {}).get("data", {}) or {}).get("escalations", [])
                   if e.get("campaignId") == campaign_id]
    outcome = (campaign or {}).get("status", "unknown").lower()
    return _result(case, steps, started, outcome, "", project_id=project_id, cpf=cpf_view,
                   prep=prep, campaign=campaign, escalations=escalations)


def _detail(body) -> str:
    d = (body or {}).get("detail") or (body or {}).get("errors")
    return json.dumps(d) if isinstance(d, dict | list) else str(d or "")


def _result(case, steps, started, outcome, reason, **extra) -> dict:
    return {"id": case["id"], "title": case["title"], "application": case["application"],
            "compound": case["compound"], "model_risk": case["model_risk"], "stages": case["stages"],
            "narrative": case["narrative"], "expectation": case["expect"],
            "outcome": outcome, "reason": reason,
            "seconds": round(time.monotonic() - started, 1), "steps": steps, **extra}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8040")
    ap.add_argument("--out", default="reports/case-studies")
    ap.add_argument("--only", default="", help="substring filter on case id")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    selected = [c for c in CASES if args.only in c["id"]]
    results = []
    for i, case in enumerate(selected, 1):
        print(f"[{i}/{len(selected)}] {case['id']} — {case['title']}", flush=True)
        result = run_case(args.base, case)
        results.append(result)
        (out / f"{case['id']}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
        print(f"      -> {result['outcome']} ({result['seconds']}s)", flush=True)

    summary = {"generated_at": datetime.now(UTC).isoformat(), "base_url": args.base,
               "engine": "analytical stand-in (NOT PK-Sim)", "cases": len(results),
               "results": [{k: r[k] for k in ("id", "title", "application", "compound", "model_risk",
                                              "outcome", "reason", "seconds", "expectation")} for r in results]}
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\nsaved {len(results)} case studies to {out}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
