"""Step 1 · Start over the API (redesign §3.1): one upload for the proposal and the client's files, the Start page with
its short brief, scope gates, model risk and checklist, and edits with no "why" asked except for the model risk."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from modeler_api.main import app
from modeler_intake.client_template import build_template

pytestmark = pytest.mark.req("T-41")

DEV = {"Authorization": "Bearer dev"}
PROPOSAL = b"PBPK model of exampleamide.\nObjective: predict exposure after a single oral dose of 50 mg in healthy adults."
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
FILLED = (("qoi.text", "exposure after 50 mg"), ("qoi.context_of_use", "internal decision on the dose"),
          ("qoi.applications", ["APP-01"]), ("m15.influence_rating", "low"), ("m15.consequence_rating", "medium"),
          ("drug.modality", "small_molecule"), ("scope.model_structure", "full_pbpk"), ("scope.site_of_action", "systemic"),
          ("scope.formulation_types", ["ir_solid"]), ("scenarios[0].route", "oral"), ("scenarios[0].food_state", "fasted"))


@pytest.fixture
def http(tmp_path, api_settings):
    api_settings(read_root=str(tmp_path), dev_auth=True, execution_backend="local")
    return TestClient(app)


def _started(http) -> dict:
    answer = http.post("/api/v1/projects:initiate", headers=DEV, data={"drug_name": "Exampleamide", "extract": "false"},
                       files=[("files", ("proposal.txt", PROPOSAL, "text/plain")),
                              ("client_files", ("ModelerOne_ClientData.xlsx", build_template(), XLSX)),
                              ("client_files", ("scan.gif", b"GIF89a", "image/gif"))])
    assert answer.status_code == 201, answer.text
    return answer.json()["data"]


def _edit(http, pid: str, changes: list[dict], reason: str = "at Start"):
    return http.put(f"/api/v1/projects/{pid}/brief", headers=DEV, json={"changes": changes, "reason": reason})


def test_one_upload_starts_the_project_with_its_proposal_and_the_clients_files(http):
    started = _started(http)
    pid = started["project_id"]
    assert [d["role"] for d in started["documents"]] == ["proposal"]
    template, refused = started["client_files"]
    assert template["template"] is True and template["id"] and template["problem"] is None
    assert refused["id"] is None and "unsupported" in refused["problem"]          # reported; the project still starts
    page = http.get(f"/api/v1/projects/{pid}/start", headers=DEV).json()["data"]
    assert [f["file"] for f in page["client_files"]] == ["ModelerOne_ClientData.xlsx"]
    assert {d["role"] for d in page["documents"]} == {"proposal", "client_file"}
    client = http.get(f"/api/v1/projects/{pid}/client-data", headers=DEV).json()["data"]   # in Inputs at once
    assert [f["file"] for f in client["files"]] == ["ModelerOne_ClientData.xlsx"]


def test_the_start_page_lists_what_start_needs_and_is_done_once_the_short_brief_is_filled(http):
    pid = _started(http)["project_id"]
    page = http.get(f"/api/v1/projects/{pid}/start", headers=DEV).json()["data"]
    assert page["state"] == "needs_you" and "Model risk: not set yet" in page["missing"]
    assert [g["state"] for g in page["gates"]] == ["unset"] * 5
    assert page["checklist"]["version"] == 1 and not page["checklist"]["stale"] and page["checklist"]["items"]
    assert [f["path"] for f in page["identity"]][:2] == ["drug.name", "drug.pubchem_cid"]
    tier = next(f for f in page["risk_fields"] if f["path"] == "acceptance.tier")
    assert tier["human_only"] and tier["required"] and page["risk"]["allowed"] == []
    modality = next(f for f in page["gate_fields"] if f["path"] == "drug.modality")
    assert {o["value"]: o["supported"] for o in modality["options"]} == {
        "small_molecule": True, "large_molecule": False, "other": False}

    assert _edit(http, pid, [{"path": p, "status": "EDITED", "value": v} for p, v in FILLED]).status_code == 200
    page = http.get(f"/api/v1/projects/{pid}/start", headers=DEV).json()["data"]
    assert page["missing"] == ["Model risk: not set yet"] and page["risk"]["allowed"] == ["low", "medium"]
    route = page["scenarios"][0]["route"]
    assert route["record"]["value"] == "oral" and {o["value"]: o["supported"] for o in route["options"]}["dermal"] is False

    no_reason = _edit(http, pid, [{"path": "acceptance.tier", "status": "EDITED", "value": "medium"}])
    assert no_reason.status_code == 422 and "give the reasons" in no_reason.json()["detail"]
    outside = _edit(http, pid, [{"path": "acceptance.tier", "status": "EDITED", "value": "high", "note": "cautious"}])
    assert outside.status_code == 422 and "admits a model risk of low or medium, not high" in outside.json()["detail"]
    assert _edit(http, pid, [{"path": "acceptance.tier", "status": "EDITED", "value": "medium",
                              "note": "the consequence drives it: the dose is chosen from the model"}]).status_code == 200
    page = http.get(f"/api/v1/projects/{pid}/start", headers=DEV).json()["data"]
    assert page["state"] == "done" and page["missing"] == [] and page["risk"]["reasons"].startswith("the consequence")
    steps = {s["step"]: s["state"] for s in http.get(f"/api/v1/projects/{pid}/steps", headers=DEV).json()["data"]["steps"]}
    assert steps["start"] == "done"


def test_a_product_the_builder_cannot_model_is_refused_at_start(http):
    pid = _started(http)["project_id"]
    _edit(http, pid, [{"path": p, "status": "EDITED", "value": v} for p, v in FILLED]
          + [{"path": "acceptance.tier", "status": "EDITED", "value": "low", "note": "low influence"},
             {"path": "scope.formulation_types", "status": "EDITED", "value": ["dr_solid"]}])
    page = http.get(f"/api/v1/projects/{pid}/start", headers=DEV).json()["data"]
    refused = [g for g in page["gates"] if g["state"] == "not_supported"]
    assert [g["id"] for g in refused] == ["scope.formulation_types"]
    assert page["state"] == "needs_you" and page["missing"] == [refused[0]["message"]]
    assert refused[0]["message"].startswith("Not supported yet: Delayed-release (enteric-coated)")
