"""T-47: the P3 client-data endpoints — template download and read, triage (person and A4), recipe mapping, gate."""

from __future__ import annotations

import io
import time

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from modeler_api import project_api
from modeler_api.auth import get_verifier
from modeler_api.main import app
from modeler_project import ArtifactKind, FileProjectStore, Workspace
from modeler_project.brief import empty_brief
from modeler_project.requirements import derive

pytestmark = pytest.mark.req("T-47")
H = {"Authorization": "Bearer t"}
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class FakeVerifier:
    def verify(self, token):
        return {"sub": "u1", "name": "Dev User", "tenant_id": "t1", "realm_access": {"roles": ["modeler-curator"]},
                "projects": ["*"], "acr": "loa2", "auth_time": int(time.time())}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    store = FileProjectStore(tmp_path)
    monkeypatch.delenv("MODELER_LLM_PROVIDER", raising=False)
    app.dependency_overrides[get_verifier] = lambda: FakeVerifier()
    app.dependency_overrides[project_api.get_project_store] = lambda: store
    ws = Workspace(store, "t1", "p1")
    brief = ws.commit(ArtifactKind.BRIEF, "main", empty_brief("Exampleamide", by="u1").to_content(), actor="u1", reason="start")
    ws.commit(ArtifactKind.REQUIREMENTS, "main", derive(empty_brief("Exampleamide", by="u1")).to_content(),
              derived_from=[brief.ref], actor="system", reason="derived")
    yield TestClient(app), ws
    app.dependency_overrides.clear()


def _save(wb) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_the_template_is_downloaded_filled_and_read_into_client_datasets(setup):
    c, _ws = setup
    r = c.get("/api/v1/client-data/template.xlsx", headers=H)
    assert r.status_code == 200 and r.headers["content-type"] == XLSX
    wb = load_workbook(io.BytesIO(r.content))
    header = [x.value.rstrip("*") for x in wb["Studies"][1]]
    values = {"study_id": "CL-1", "design": "SD", "population": "healthy", "n": 12, "route": "oral", "dose": 10,
              "dose_unit": "mg", "formulation": "ir_tablet", "food_state": "fasted"}
    wb["Studies"].append([values.get(h) for h in header])
    for t, v in ((0.5, 20.0), (1, 41.0), (2, 30.5), (4, 12.0)):
        wb["PK_Summary"].append(["CL-1", None, t, "h", "arithmetic_mean", v, None, None, 12, "ng/ml"])
    up = c.post("/api/v1/projects/p1/client-data", headers=H,
                files=[("files", ("client.xlsx", _save(wb), XLSX)), ("files", ("report.md", b"# Study CL-1\nLLOQ 0.5 ng/ml", "text/markdown"))])
    assert up.status_code == 201, up.text
    view = up.json()["data"]
    files = {f["file"]: f for f in view["files"]}
    workbook, report = files["client.xlsx"], files["report.md"]
    assert workbook["template"] and len(workbook["datasets"]) == 1 and not workbook["issues"]
    assert report["kind"] == "markdown" and not report["datasets"]
    evidence = c.get("/api/v1/projects/p1/evidence", headers=H).json()["data"]
    ds = next(d for d in evidence["datasets"] if d["id"] == workbook["datasets"][0])
    assert ds["origin"] == "CLIENT" and ds["provider"] == "CLIENT" and ds["series"][0]["values"] == [20.0, 41.0, 30.5, 12.0]
    # every client item of the default plan (nothing promised yet) is listed; the client's study is unpromised
    assert any("CL-1" in u for u in view["reconciliation"]["unpromised"])


def _raw_workbook() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    for row in (["Study ABC-1, 25 mg oral tablet, fasted"], ["Subject", "Time (h)", "Conc (ng/mL)"],
                ["001", 0.5, 10.1], ["001", 1, 22.4], ["001", 2, 15.0], ["002", 0.5, 9.8], ["002", 1, 20.0], ["002", 2, 14.1]):
        ws.append(row)
    notes = wb.create_sheet("Misc")
    notes.append(["Shipped with the courier on 1 September"])
    return _save(wb)


def test_any_other_workbook_is_triaged_classified_and_mapped_by_a_confirmed_recipe(setup):
    c, _ws = setup
    view = c.post("/api/v1/projects/p1/client-data", headers=H, files=[("files", ("raw.xlsx", _raw_workbook(), XLSX))]).json()["data"]
    sub = view["files"][0]
    assert not sub["template"]
    triage = {t["sheet"]: t for t in sub["triage"]}
    assert triage["Sheet1"]["category"] == "PK_INDIVIDUAL" and triage["Sheet1"]["evidence_quote"] == "Subject"
    assert triage["Misc"]["category"] == "OTHER"
    refused = c.post(f"/api/v1/projects/p1/client-data/{sub['id']}:triage", headers=H)
    assert refused.status_code == 409 and "agents are off" in refused.json()["detail"]
    view = c.post(f"/api/v1/projects/p1/client-data/{sub['id']}/sheets/Misc:classify", headers=H,
                  json={"category": "PRODUCT_INFO", "reason": "batch list, per the client's email"}).json()["data"]
    assert {t["sheet"]: t["by"] for t in view["files"][0]["triage"]}["Misc"] == "u1"

    proposal = {"tables": [{
        "record_type": "concentration_time", "sheet": "Sheet1", "header_rows": 2, "first_data_row": 3,
        "columns": [{"column": "A", "role": "subject_id"}, {"column": "B", "role": "time"}, {"column": "C", "role": "value"}],
        "time_unit": "h", "value_unit": "ng/mL", "statistic": "individual",
        "constants": [{"key": "study_id", "value": "ABC-1"}, {"key": "analyte", "value": "parent"},
                      {"key": "matrix", "value": "plasma"}, {"key": "dose", "value": "25"}, {"key": "dose_unit", "value": "mg"},
                      {"key": "route", "value": "oral"}, {"key": "formulation", "value": "ir_tablet"},
                      {"key": "food_state", "value": "fasted"}],
        "evidence": [{"cell": "Sheet1!C2", "quote": "ng/mL", "supports": "value unit"},
                     {"cell": "Sheet1!A1", "quote": "25 mg", "supports": "dose"}]}]}
    preview = c.post(f"/api/v1/projects/p1/client-data/{sub['id']}:map", headers=H,
                     json={"proposal": proposal, "study": {"n": 2, "design": "SD"}}).json()["data"]
    assert preview["concentrations"] == 6 and preview["studies"] == ["ABC-1"] and preview["ready"], preview
    done = c.post(f"/api/v1/projects/p1/client-data/{sub['id']}:map", headers=H,
                  json={"proposal": proposal, "study": {"n": 2, "design": "SD"}, "confirm": True})
    assert done.status_code == 200, done.text
    ids = done.json()["data"]["datasets"]
    ds = next(d for d in c.get("/api/v1/projects/p1/evidence", headers=H).json()["data"]["datasets"] if d["id"] == ids[0])
    assert ds["origin"] == "CLIENT" and [s["name"] for s in ds["series"]] == ["001", "002"] and ds["study"]["dose_mg"] == 25
    assert ds["quote"].startswith("[Sheet1 row 3]")


def test_a4_classifies_only_with_a_header_quote_code_can_find(setup):
    from modeler_agents.llm import ChatResult, ToolCall
    from modeler_api.client_api import run_triage_job

    c, ws = setup
    sub = c.post("/api/v1/projects/p1/client-data", headers=H, files=[("files", ("raw.xlsx", _raw_workbook(), XLSX))]).json()["data"]["files"][0]

    class Scripted:
        provider, model = "test", "s"

        def __init__(self):
            self.turn = 0

        def complete(self, messages, tools):
            self.turn += 1
            calls = () if self.turn > 1 else (
                ToolCall(id="1", name="classify_sheet", arguments={"sheet": "Misc", "category": "PRODUCT_INFO",
                                                                   "cell": "Misc!A1", "quote": "Shipped with the courier"}),
                ToolCall(id="2", name="classify_sheet", arguments={"sheet": "Sheet1", "category": "DISSOLUTION",
                                                                   "cell": "Sheet1!A1", "quote": "dissolution"}))
            return ChatResult(content="" if calls else "done", tool_calls=calls, finish_reason="", usage={}, model="s")

    result = run_triage_job(ws.store, "t1", "p1", sub["id"], model=Scripted())
    # only Misc was undecided by code; the claim about Sheet1 is refused (not offered, and no such quote)
    assert result["classified"] == 1
    triage = {t["sheet"]: t for t in c.get("/api/v1/projects/p1/client-data", headers=H).json()["data"]["files"][0]["triage"]}
    assert triage["Misc"]["category"] == "PRODUCT_INFO" and triage["Misc"]["by"].startswith("agent:")
    assert triage["Sheet1"]["category"] == "PK_INDIVIDUAL"


def test_p3_closes_only_when_required_client_items_are_met_or_skipped(setup):
    c, ws = setup
    view = c.get("/api/v1/projects/p1/client-data", headers=H).json()["data"]
    blocking = view["reconciliation"]["blocking"]
    if blocking:
        gate = c.post("/api/v1/projects/p1/client-data:approve", headers=H, json={})
        assert gate.status_code == 409 and "still missing" in gate.json()["detail"]
    else:
        ok = c.post("/api/v1/projects/p1/client-data:approve", headers=H, json={"note": "nothing promised by the client"})
        assert ok.status_code == 200 and ok.json()["data"]["register"]["status"] == "APPROVED"
        assert ws.phases()["P3"] == "APPROVED"


@pytest.mark.req("T-48")
def test_dissolution_profiles_are_shown_and_a_fit_is_proposed_as_a_release_model(setup):
    import numpy as np

    from pbpk_domain.dissolution import weibull_fraction

    c, _ws = setup
    wb = load_workbook(io.BytesIO(c.get("/api/v1/client-data/template.xlsx", headers=H).content))
    times = (5, 10, 15, 20, 30, 45, 60)
    for t, f in zip(times, weibull_fraction(np.array(times), 25.0, 1.1), strict=True):
        wb["Dissolution"].append(["Tab 10", "TEST", 10, "B7", "USP 2 paddle", 50, "FaSSIF", 6.5, 500, 37, None, t, "min",
                                  *[round(100 * float(f) + d, 2) for d in np.linspace(-1, 1, 12)]])
    view = c.post("/api/v1/projects/p1/client-data", headers=H, files=[("files", ("diss.xlsx", _save(wb), XLSX))]).json()["data"]
    profile = view["dissolution"]["profiles"][0]
    assert profile["release_model"] == "Weibull" and profile["fit"]["t50_min"] == pytest.approx(25.0, rel=0.01)
    r = c.post(f"/api/v1/projects/p1/dissolution/{profile['id']}:propose", headers=H, json={"formulation": "Tab10"})
    assert r.status_code == 201 and len(r.json()["data"]["evidence"]) == 4
    targets = {e["target"] for e in c.get("/api/v1/projects/p1/evidence", headers=H).json()["data"]["evidence"]}
    assert {"form.Tab10.type", "form.Tab10.weibull.t50", "form.Tab10.weibull.shape", "form.Tab10.weibull.lag"} <= targets
    bad = c.post(f"/api/v1/projects/p1/dissolution/{profile['id']}:propose", headers=H, json={"formulation": "Tab 1.0"})
    assert bad.status_code == 422 and "no dots" in bad.json()["detail"]
