"""T-47: the P3 client-data endpoints — template download and read, triage (person and A4), recipe mapping, gate."""

from __future__ import annotations

import io
import time
from typing import Any

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
                  json={"proposal": proposal, "study": {"n": 2, "design": "SD", "purpose": "external_validation"}, "confirm": True})
    assert done.status_code == 200, done.text
    ids = done.json()["data"]["datasets"]
    ds = next(d for d in c.get("/api/v1/projects/p1/evidence", headers=H).json()["data"]["datasets"] if d["id"] == ids[0])
    assert ds["origin"] == "CLIENT" and [s["name"] for s in ds["series"]] == ["001", "002"] and ds["study"]["dose_mg"] == 25
    # the purpose the person chose goes on the dataset; the study record stays a valid MS-01 record
    assert ds["purpose"] == "external_validation" and "purpose" not in ds["study"]
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
    early = c.post(f"/api/v1/projects/p1/dissolution/{profile['id']}:propose", headers=H, json={"formulation": "Tab10"})
    assert early.status_code == 409 and "confirm the product" in early.json()["detail"]   # plan 2026-11-03 §3.3
    product = next(g for g in c.get("/api/v1/projects/p1/client-review", headers=H).json()["data"]["groups"]
                   if g["kind"] == "product")
    shown = next(i for i in product["items"] if i["kind"] == "profile")["release"]     # drawn on its card (build C)
    assert shown["times_min"] == list(times) and shown["fit"]["t50_min"] == profile["fit"]["t50_min"]
    confirmed = c.post("/api/v1/projects/p1/client-review:confirm", headers=H, json={"group": product["id"]})
    assert confirmed.status_code == 200, confirmed.text
    r = c.post(f"/api/v1/projects/p1/dissolution/{profile['id']}:propose", headers=H, json={"formulation": "Tab10"})
    assert r.status_code == 201 and len(r.json()["data"]["evidence"]) == 4
    targets = {e["target"] for e in c.get("/api/v1/projects/p1/evidence", headers=H).json()["data"]["evidence"]}
    assert {"form.Tab10.type", "form.Tab10.weibull.t50", "form.Tab10.weibull.shape", "form.Tab10.weibull.lag"} <= targets
    bad = c.post(f"/api/v1/projects/p1/dissolution/{profile['id']}:propose", headers=H, json={"formulation": "Tab 1.0"})
    assert bad.status_code == 422 and "no dots" in bad.json()["detail"]


@pytest.mark.req("T-48")
def test_the_lever_for_a_tablet_studys_formulation_follows_what_the_project_holds(setup):
    """Final review round 4: the step bar named "add a product" whatever the project held. What gives a tablet study its
    formulation is read from the project (`formulation_way`) and carried by the Inputs step and To do's formulation item:
    no product here (add one, or ask the client: the item carries the client request's line for the study the sheet form
    loaded), a product with no profile (its dissolution data), a profile that can give the release (use it), and none once
    the release is set."""
    from modeler_project.study_requirements import UNNAMED_PRODUCT

    c, _ws = setup
    wb = load_workbook(io.BytesIO(c.get("/api/v1/client-data/template.xlsx", headers=H).content))
    header = [x.value.rstrip("*") for x in wb["Studies"][1]]
    values = {"study_id": "CL-1", "design": "SD", "population": "healthy", "n": 12, "route": "oral", "dose": 10,
              "dose_unit": "mg", "formulation": "ir_tablet", "food_state": "fasted"}
    wb["Studies"].append([values.get(h) for h in header])
    for t, v in ((0.5, 20.0), (1, 41.0), (2, 30.5), (4, 12.0)):
        wb["PK_Summary"].append(["CL-1", None, t, "h", "arithmetic_mean", v, None, None, 12, "ng/ml"])
    assert c.post("/api/v1/projects/p1/client-data", headers=H, files=[("files", ("client.xlsx", _save(wb), XLSX))]).status_code == 201
    study = next(g for g in c.get("/api/v1/projects/p1/client-review", headers=H).json()["data"]["groups"] if g["id"] == "study:CL-1")
    assert c.post("/api/v1/projects/p1/client-review:confirm", headers=H, json={"group": study["id"]}).status_code == 200

    def way() -> tuple[dict | None, dict | None, list[dict]]:
        assert c.post("/api/v1/projects/p1/inputs:assemble", headers=H).status_code == 200
        inputs = next(s for s in c.get("/api/v1/projects/p1/steps", headers=H).json()["data"]["steps"] if s["step"] == "inputs")
        item = next((t for t in c.get("/api/v1/projects/p1/inputs", headers=H).json()["data"]["todo"] if t["kind"] == "formulation"), None)
        assert (item or {}).get("way") == inputs["formulation"]        # one reading for the step bar and To do
        lever = inputs["formulation"]
        if lever is not None:                                           # one study: its own way is the step bar's
            assert lever["each"] == [{"study": "CL-1", "named": None, **{k: lever[k] for k in ("way", "products", "ready")}}]
            lever = {k: v for k, v in lever.items() if k != "each"}
        return lever, item, (item or {}).get("ask", [])

    asked = [("REQ-form.release", f"{UNNAMED_PRODUCT} — study CL-1", "the model itself", True)]
    # no product here at all: add one, or ask the client, who is asked for the product of the study the sheet form loaded
    lever, item, ask = way()
    assert lever == {"way": "add_product", "products": [], "studies": ["CL-1"], "ready": True}
    assert [(a["req_id"], a["what"], a["why"], a["required"]) for a in ask] == asked
    # a product the proposal names, with no dissolution data: its dissolution data, or the client, who is asked the same
    # line (round 5: the line follows the way that offers "ask the client", not only "no product at all")
    edit = {"changes": [{"path": "products[0].name", "status": "EDITED", "value": "Tab 10", "note": "the proposal"}], "reason": "product"}
    assert c.put("/api/v1/projects/p1/brief", headers=H, json=edit).status_code == 200
    lever, item, ask = way()
    assert lever == {"way": "add_dissolution", "products": ["Tab 10"], "studies": ["CL-1"], "ready": True}
    assert [(a["req_id"], a["what"], a["why"], a["required"]) for a in ask] == asked
    # its dissolution profile is here and can give the release: use it (the profile's product first)
    import numpy as np

    from pbpk_domain.dissolution import weibull_fraction

    diss = load_workbook(io.BytesIO(c.get("/api/v1/client-data/template.xlsx", headers=H).content))
    times = (5, 10, 15, 20, 30, 45, 60)
    for t, f in zip(times, weibull_fraction(np.array(times), 25.0, 1.1), strict=True):
        diss["Dissolution"].append(["Tab 10", "TEST", 10, "B7", "USP 2 paddle", 50, "FaSSIF", 6.5, 500, 37, None, t, "min",
                                    *[round(100 * float(f) + d, 2) for d in np.linspace(-1, 1, 12)]])
    view = c.post("/api/v1/projects/p1/client-data", headers=H, files=[("files", ("diss.xlsx", _save(diss), XLSX))]).json()["data"]
    lever, item, ask = way()
    # its product's dissolution data are confirmed first (the profile is used only then): not ready
    assert lever == {"way": "use_profile", "products": ["Tab 10"], "studies": ["CL-1"], "ready": False} and ask == []
    product = next(g for g in c.get("/api/v1/projects/p1/client-review", headers=H).json()["data"]["groups"] if g["kind"] == "product")
    assert c.post("/api/v1/projects/p1/client-review:confirm", headers=H, json={"group": product["id"]}).status_code == 200
    lever, item, ask = way()
    assert lever == {"way": "use_profile", "products": ["Tab 10"], "studies": ["CL-1"], "ready": True}
    # once its fit is the release, the study has its formulation: no lever, no item
    profile = view["dissolution"]["profiles"][0]
    assert c.post(f"/api/v1/projects/p1/dissolution/{profile['id']}:propose", headers=H, json={"formulation": "Tab10"}).status_code == 201
    lever, item, _ask = way()
    assert lever is None and item is None
    # and that profile is the release of the formulation made from it: never offered again (round 5)
    from modeler_project.formulation_way import _released

    assert _released(_ws) == ({profile["id"]}, {"tab10"})


def test_formulation_way_reads_each_problem_of_the_readiness_check(tmp_path):
    """Round 4: the readiness check's problems name the lever: a study naming its formulation puts that product first;
    several formulations and a study naming none is a choice; a formulation not complete has no lever."""
    from modeler_project.formulation_way import formulation_way

    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    none = "CL-1: the study is a solid oral form but the CPF defines no formulation (form.{name}.type)"
    named = "CL-2: the CPF defines no formulation 'Brand 5 mg' (form.Brand 5 mg.type)"
    several = "CL-3: the study does not name its formulation and the CPF defines several: A, B"
    weibull = "CL-4: Weibull formulation 'A' needs form.A.weibull.t50 (the in-vitro dissolution fit)"
    lead = lambda w: {k: v for k, v in w.model_dump().items() if k != "each"}  # the step bar's fields
    ways = lambda w: [(e.study, e.way, e.products) for e in w.each]  # each study's own
    # no product here: CL-1 adds one; CL-2 names Brand 5 mg, which only Brand 5 mg's dissolution data settle (round 5:
    # it was "add a product" for both); the step bar names the lever done first, for the study it settles
    way = formulation_way(ws, [none, named])
    assert lead(way) == {"way": "add_dissolution", "products": ("Brand 5 mg",), "studies": ("CL-2",), "ready": True}
    assert ways(way) == [("CL-1", "add_product", ()), ("CL-2", "add_dissolution", ("Brand 5 mg",))]
    assert lead(formulation_way(ws, [none])) == {"way": "add_product", "products": (), "studies": ("CL-1",), "ready": True}
    assert lead(formulation_way(ws, [several, weibull])) == {"way": "choose", "products": (), "studies": ("CL-3",), "ready": True}
    assert formulation_way(ws, [weibull]) is None
    assert formulation_way(ws, []) is None
    brief = empty_brief("Exampleamide", by="u1").to_content()
    brief["groups"]["products"] = [{"name": {"value": "Test 5 mg", "status": "EDITED"}}, {"name": {"value": "Brand 5 mg", "status": "EDITED"}}]
    ws.commit(ArtifactKind.BRIEF, "main", brief, actor="u1", reason="products")
    # products here, none with a profile: each study's dissolution data, the product a study names first
    way = formulation_way(ws, [none, named])
    assert lead(way) == {"way": "add_dissolution", "products": ("Brand 5 mg", "Test 5 mg"), "studies": ("CL-1", "CL-2"), "ready": True}
    assert ways(way) == [("CL-1", "add_dissolution", ("Test 5 mg", "Brand 5 mg")), ("CL-2", "add_dissolution", ("Brand 5 mg",))]


def _profile(pid: str, product: str | None, *, usable: bool = True) -> dict:
    """A dissolution profile as the register keeps it, as far as `formulation_way` reads it (software test data)."""
    return {"id": pid, "key": {"product": product}, "release_model": "Weibull" if usable else "Table",
            "fit": {"t50_min": 18.0} if usable else None}


@pytest.mark.req("T-48")
def test_formulation_way_is_read_for_each_study(tmp_path, monkeypatch):
    """Round 5 (round 4's skeptic, way_edge.py): a study that names its product is settled by that product's profile or
    its dissolution data, never by another product's profile; a profile that is a release already is not offered again;
    the products a study names come first, then those whose data are confirmed, then the register's order; and a study
    whose way asks the client is asked."""
    from modeler_project import client_review
    from modeler_project import formulation_way as fw

    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    none = "CL-1: the study is a solid oral form but the CPF defines no formulation (form.{name}.type)"
    named = "CL-2: the CPF defines no formulation 'Test 10 mg' (form.Test 10 mg.type)"
    profiles: list[dict] = []
    confirmed: set[str] = set()
    released: tuple[set[str], set[str]] = (set(), set())
    monkeypatch.setattr(fw, "_profiles", lambda _ws: profiles)
    monkeypatch.setattr(client_review, "confirmed_profiles", lambda _ws: confirmed)
    monkeypatch.setattr(fw, "_released", lambda _ws: released)
    lead = lambda w: {k: v for k, v in w.model_dump().items() if k != "each"}  # the step bar's fields
    ways = lambda w: [(e.study, e.way, e.products, e.ready) for e in w.each]  # each study's own

    # (a) the study names Test 10 mg and only Brand 10 mg's profile can give a release: Test 10 mg's dissolution data, not
    # Brand 10 mg's profile (round 4 offered "use Brand 10 mg's profile", which would not settle the study)
    profiles[:] = [_profile("d1", "Brand 10 mg")]
    confirmed |= {"d1"}
    way = fw.formulation_way(ws, [named])
    assert lead(way) == {"way": "add_dissolution", "products": ("Test 10 mg",), "studies": ("CL-2",), "ready": True}
    assert ways(way) == [("CL-2", "add_dissolution", ("Test 10 mg",), True)]
    assert way.each[0].named == "Test 10 mg"
    # (b) Test 10 mg's profile is here too, still to confirm, and Brand 10 mg's is confirmed: the named product comes first
    # all the same (round 4 put the confirmed other product first), not ready
    profiles[:] = [_profile("d1", "Brand 10 mg"), _profile("d2", "Test 10 mg")]
    way = fw.formulation_way(ws, [named])
    assert lead(way) == {"way": "use_profile", "products": ("Test 10 mg",), "studies": ("CL-2",), "ready": False}
    # with a study that names none: it may use either profile, the confirmed one first; the step bar names the study's
    # product first, as the docstring orders them
    way = fw.formulation_way(ws, [none, named])
    assert ways(way) == [("CL-1", "use_profile", ("Brand 10 mg", "Test 10 mg"), True), ("CL-2", "use_profile", ("Test 10 mg",), False)]
    assert lead(way) == {"way": "use_profile", "products": ("Test 10 mg", "Brand 10 mg"), "studies": ("CL-1", "CL-2"), "ready": False}
    # a study naming none, alone: the confirmed product first, whatever the register's order
    assert lead(fw.formulation_way(ws, [none]))["products"] == ("Brand 10 mg", "Test 10 mg")
    assert lead(fw.formulation_way(ws, [none]))["ready"] is True
    # a profile a formulation was made from is that formulation's release already: not offered again; a profile that is
    # a table cannot give one
    released = ({"d1"}, set())
    profiles[:] = [_profile("d1", "Brand 10 mg"), _profile("d2", "Test 10 mg", usable=False)]
    way = fw.formulation_way(ws, [none])
    assert lead(way) == {"way": "add_dissolution", "products": ("Brand 10 mg", "Test 10 mg"), "studies": ("CL-1",), "ready": True}
    # nor is a profile of a product whose formulation the model holds
    released = (set(), {"brand 10 mg"})
    profiles[:] = [_profile("d1", "Brand 10 mg"), _profile("d3", "Ref 10 mg")]
    assert lead(fw.formulation_way(ws, [none]))["products"] == ("Ref 10 mg",)

    # the client is asked for each study whose way offers it (`inputs.todo`'s `ask`): a study that names its product, for
    # that product's data
    from modeler_project.study_requirements import UNNAMED_PRODUCT, named_product, unnamed_product_request

    lines = unnamed_product_request(["CL-1", "CL-2"], named={"CL-2": "Test 10 mg"}, brief=None, matrix=None)
    assert [line.what for line in lines] == [f"{UNNAMED_PRODUCT} — study CL-1", f"{named_product('Test 10 mg')} — study CL-2"]


def _named_template(c, study: str, product: str | None, *, dissolution: str | None = None) -> bytes:
    """A filled client-data template (software test data): a tablet study whose Studies row names `product` (None: the
    column left empty), its mean profile, and `dissolution`'s usable curve when given."""
    import math

    wb = load_workbook(io.BytesIO(c.get("/api/v1/client-data/template.xlsx", headers=H).content))
    header = [x.value.rstrip("*") for x in wb["Studies"][1]]
    values = {"study_id": study, "design": "SD", "population": "healthy", "n": 12, "route": "oral", "dose": 10,
              "dose_unit": "mg", "formulation": "ir_tablet", "food_state": "fasted", "product": product,
              "product_role": "TEST" if product else None}
    wb["Studies"].append([values.get(h) for h in header])
    for t, v in ((0.5, 20.0), (1, 41.0), (2, 30.5), (4, 12.0)):
        wb["PK_Summary"].append([study, None, t, "h", "arithmetic_mean", v, None, None, 12, "ng/ml"])
    if dissolution:
        for t in (5, 10, 15, 20, 30, 45, 60):
            fraction = 1 - math.exp(-math.log(2) * (t / 20.0) ** 1.3)
            wb["Dissolution"].append([dissolution, "RLD", 10, "B1", "USP 2 paddle", 50, "phosphate", 6.8, 900, 37, None, t, "min",
                                      *[round(100 * fraction + d, 2) for d in (-1.5, -1.2, -0.9, -0.6, -0.3, 0, 0, 0.3, 0.6, 0.9, 1.2, 1.5)]])
    return _save(wb)


@pytest.mark.req("T-48")
def test_a_study_whose_own_file_names_its_product_is_settled_by_that_product_only(setup):
    """Round 6 (round 5's downstream-why skeptic, probe B): the usual way a study names its product is its own file, the
    client template's Studies.product (here read with the sheet form). CL-02's names Test 10 mg while only Brand 10 mg
    (the RLD) has a usable, confirmed profile: its way is Test 10 mg's dissolution data, never Brand 10 mg's profile (round
    5 offered "use Brand 10 mg's profile", which would model CL-02 with the RLD's release), and the client is asked for
    Test 10 mg's data in the named words, its line naming the product, never "(no file names the product)"."""
    from modeler_project.study_requirements import UNNAMED_PRODUCT, named_product

    c, _ws = setup
    up = c.post("/api/v1/projects/p1/client-data", headers=H,
                files=[("files", ("named.xlsx", _named_template(c, "CL-02", "Test 10 mg", dissolution="Brand 10 mg"), XLSX))])
    assert up.status_code == 201, up.text
    groups = c.get("/api/v1/projects/p1/client-review", headers=H).json()["data"]["groups"]
    for g in ("study:CL-02", *(g["id"] for g in groups if g["kind"] == "product")):
        assert c.post("/api/v1/projects/p1/client-review:confirm", headers=H, json={"group": g}).status_code == 200
    assert c.post("/api/v1/projects/p1/inputs:assemble", headers=H).status_code == 200
    inputs = next(s for s in c.get("/api/v1/projects/p1/steps", headers=H).json()["data"]["steps"] if s["step"] == "inputs")
    item = next(t for t in c.get("/api/v1/projects/p1/inputs", headers=H).json()["data"]["todo"] if t["kind"] == "formulation")
    assert item["way"] == inputs["formulation"]
    assert inputs["formulation"] == {"way": "add_dissolution", "products": ["Test 10 mg"], "studies": ["CL-02"], "ready": True,
                                     "each": [{"study": "CL-02", "way": "add_dissolution", "products": ["Test 10 mg"],
                                               "ready": True, "named": "Test 10 mg"}]}
    assert [(a["what"], a["product"]) for a in item["ask"]] == [(f"{named_product('Test 10 mg')} — study CL-02", "Test 10 mg")]
    assert not any(UNNAMED_PRODUCT in a["what"] for a in item["ask"])
    # a study whose file names no product is still asked in the unnamed words, its line naming no product
    up = c.post("/api/v1/projects/p1/client-data", headers=H,
                files=[("files", ("unnamed.xlsx", _named_template(c, "CL-01", None), XLSX))])
    assert up.status_code == 201, up.text
    assert c.post("/api/v1/projects/p1/client-review:confirm", headers=H, json={"group": "study:CL-01"}).status_code == 200
    assert c.post("/api/v1/projects/p1/inputs:assemble", headers=H).status_code == 200
    item = next(t for t in c.get("/api/v1/projects/p1/inputs", headers=H).json()["data"]["todo"] if t["kind"] == "formulation")
    # CL-01 names none: Brand 10 mg's profile can give its release (the step bar's lever, done here and now), in the
    # readiness check's order of the studies
    assert [(e["study"], e["way"], e["products"], e["named"]) for e in item["way"]["each"]] == [
        ("CL-02", "add_dissolution", ["Test 10 mg"], "Test 10 mg"), ("CL-01", "use_profile", ["Brand 10 mg"], None)]
    assert (item["way"]["way"], item["way"]["studies"]) == ("use_profile", ["CL-01"])
    assert [(a["what"], a["product"]) for a in item["ask"]] == [(f"{named_product('Test 10 mg')} — study CL-02", "Test 10 mg")]


class _Ledger:
    """The delivery's ledger, written as its reading writes it (entities and facts; software test data)."""

    def __init__(self, ws: Workspace):
        from modeler_project.intake_store import IntakeStore

        self.store = IntakeStore(ws)
        self.n = 0

    def _anchor(self) -> str:
        import hashlib

        from modeler_intake.anchors import anchor_text

        self.n += 1
        return anchor_text(hashlib.sha256(b"named products").hexdigest(), "workbook", "1.0", f"s:'Studies'!B{self.n}")

    def entity(self, type: str, label: str, parent: str | None = None) -> str:
        from modeler_intake.document_reading import name_key
        from modeler_project.ledger_models import Entity

        prefix = {"study": "st", "arm": "arm", "product": "pr"}[type]
        source = self._anchor()
        return self.store.entities.append("entity", lambda seq: Entity(
            id=f"{prefix}-{seq}", type=type, label=label, key=name_key(label), parent=parent, source=source,  # type: ignore[arg-type]
            by="code", at="2026-11-16T09:00:00.000Z").model_dump(mode="json")).body["id"]

    def fact(self, field: str, value: Any, **entity: str) -> None:
        from modeler_project.ledger_models import EntityRef, Fact

        anchor = self._anchor()
        self.store.facts.append("fact", lambda seq: Fact(
            id=f"f-{seq}", delivery="dl-1", entity=EntityRef(**entity), field=field, value=value, verbatim=str(value),
            anchor=anchor, method="prose", by="code", at="2026-11-16T09:00:00.000Z").model_dump(mode="json"))


@pytest.mark.req("T-48")
def test_the_product_a_study_names_is_read_from_both_of_its_paths(tmp_path, monkeypatch):
    """Round 6: `file_products` reads the product a study's own client data name from the sheet form's Studies rows and
    from the delivery's values of the study that name a product (the link a product's card shows as "Role Test · study
    CL-02"), each as the readiness check names the study (an arm's row and value by `<study>-<arm>`); `formulation_way`
    then treats the study as one that names its product: named in the sheet form, on the delivery, in both and agreeing
    (spelled apart: one product), or a name no product here has, never with another product's profile. No link is made
    up for a study whose files name none."""
    from modeler_project import client_data, client_review
    from modeler_project import formulation_way as fw
    from modeler_project.study_requirements import named_product

    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    none = lambda s: f"{s}: the study is a solid oral form but the CPF defines no formulation (form.{{name}}.type)"
    rows: list[dict] = []
    monkeypatch.setattr(client_data, "submissions", lambda _ws: [{"id": "f1", "file": "client.xlsx", "sha256": "0" * 64,
                                                                  "template": True, "studies": rows}])
    profiles = [_profile("d1", "Brand 10 mg")]
    monkeypatch.setattr(fw, "_profiles", lambda _ws: profiles)
    monkeypatch.setattr(client_review, "confirmed_profiles", lambda _ws: {"d1"})
    monkeypatch.setattr(fw, "_released", lambda _ws: (set(), set()))
    own = lambda w: [(e.study, e.way, e.products, e.ready, e.named) for e in w.each]
    ledger = _Ledger(ws)

    # named in the sheet form only (the Studies row of CL-02, and of CL-07's arm A, named as its dataset is: CL-07-A)
    rows += [{"row": 2, "values": {"study_id": "CL-02", "product": "Test 10 mg"}},
             {"row": 3, "values": {"study_id": "CL-07", "treatment": "A", "product": "Test 10 mg"}}]
    # named on the delivery only: CL-05's values name Test 10 mg; CL-06's arm B names it (its whole study too)
    st5, st6 = ledger.entity("study", "CL-05"), ledger.entity("study", "CL-06")
    test, brand = ledger.entity("product", "Test 10 mg"), ledger.entity("product", "Brand 10 mg")
    arm_b = ledger.entity("arm", "B", parent=st6)
    ledger.fact("product_role", "TEST", study=st5, product=test)
    ledger.fact("product_role", "TEST", study=st6, arm=arm_b, product=test)
    ledger.fact("percent_dissolved", 50.0, product=brand)              # a product's own value names no study
    # named in both and agreeing, spelled apart: CL-08's row says "Product TEST 10 MG", its delivery values "Test 10 mg"
    rows.append({"row": 4, "values": {"study_id": "CL-08", "product": "Product TEST 10 MG"}})
    ledger.fact("product_role", "TEST", study=ledger.entity("study", "CL-08"), product=test)
    # a name no product here has, and studies whose files name no product (a value of CL-10 names none; CL-11's row none)
    rows.append({"row": 5, "values": {"study_id": "CL-09", "product": "Generic 5 mg"}})
    ledger.fact("route", "oral", study=ledger.entity("study", "CL-10"))
    rows.append({"row": 6, "values": {"study_id": "CL-11", "product": None}})
    named = fw.file_products(ws)
    assert {k: named.get(fw._study(k)) for k in ("CL-02", "CL-07-A", "CL-07", "CL-05", "CL-06-B", "CL-06", "CL-08", "CL-09",
                                                  "CL-10", "CL-11")} == {
        "CL-02": ("Test 10 mg",), "CL-07-A": ("Test 10 mg",), "CL-07": None, "CL-05": ("Test 10 mg",),
        "CL-06-B": ("Test 10 mg",), "CL-06": ("Test 10 mg",), "CL-08": ("Product TEST 10 MG",), "CL-09": ("Generic 5 mg",),
        "CL-10": None, "CL-11": None}

    # only Brand 10 mg's profile can give a release: each study whose files name Test 10 mg (or Generic 5 mg) adds that
    # product's dissolution data, said as the product is named here; the study whose files name none may use Brand's
    way = fw.formulation_way(ws, [none(s) for s in ("CL-02", "CL-05", "CL-06-B", "CL-08", "CL-09", "CL-10")])
    assert own(way) == [("CL-02", "add_dissolution", ("Test 10 mg",), True, "Test 10 mg"),
                        ("CL-05", "add_dissolution", ("Test 10 mg",), True, "Test 10 mg"),
                        ("CL-06-B", "add_dissolution", ("Test 10 mg",), True, "Test 10 mg"),
                        ("CL-08", "add_dissolution", ("Test 10 mg",), True, "Test 10 mg"),
                        ("CL-09", "add_dissolution", ("Generic 5 mg",), True, "Generic 5 mg"),
                        ("CL-10", "use_profile", ("Brand 10 mg",), True, None)]
    # the step bar names the profile, for the study it settles (done here and now); the others say theirs
    assert (way.way, way.products, way.studies) == ("use_profile", ("Brand 10 mg",), ("CL-10",))
    # Test 10 mg's profile arrives, still to confirm: the study that names it uses it (not ready), never Brand 10 mg's
    profiles.append(_profile("d2", "Test 10 mg"))
    way = fw.formulation_way(ws, [none("CL-08"), none("CL-10")])
    assert own(way) == [("CL-08", "use_profile", ("Test 10 mg",), False, "Test 10 mg"),
                        ("CL-10", "use_profile", ("Brand 10 mg", "Test 10 mg"), True, None)]
    assert (way.products, way.ready) == (("Test 10 mg", "Brand 10 mg"), False)
    # the client is asked for the product a study names, in those words; a study whose files name two, for either
    assert named_product(["Test 10 mg", "Brand 10 mg"]) == ("The formulation or dissolution data of Test 10 mg or Brand 10 mg, "
                                                             "the product the study used")


@pytest.mark.req("T-48")
def test_a_study_way_is_ready_as_its_first_product_and_a_named_study_may_use_its_profile_again(tmp_path, monkeypatch):
    """Round 6 (round 5's skeptic, way_edge5 cases 2 and 1): a study's own `ready` is its first product's, never that of
    a confirmed profile of no product listed before it; and a study that names its product, whose profile was made the
    release of a formulation of another name, is offered that profile again (used under the study's name, it gives the
    formulation the study names), never told its product has no profile that can give a release."""
    from modeler_project import client_review
    from modeler_project import formulation_way as fw

    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    none = "CL-1: the study is a solid oral form but the CPF defines no formulation (form.{name}.type)"
    named = "CL-2: the CPF defines no formulation 'Test 10 mg' (form.Test 10 mg.type)"
    profiles: list[dict] = [_profile("d9", None), _profile("d1", "Brand 10 mg")]
    confirmed = {"d9"}
    released: tuple[set[str], set[str]] = (set(), set())
    monkeypatch.setattr(fw, "_profiles", lambda _ws: profiles)
    monkeypatch.setattr(client_review, "confirmed_profiles", lambda _ws: confirmed)
    monkeypatch.setattr(fw, "_released", lambda _ws: released)
    way = fw.formulation_way(ws, [none])
    # the confirmed profile of no product comes first; the first product listed, Brand 10 mg, is not confirmed
    assert [(e.way, e.products, e.ready) for e in way.each] == [("use_profile", ("Brand 10 mg",), False)]
    assert (way.products, way.ready) == (("Brand 10 mg",), False)
    # Test 10 mg's confirmed profile is the release of "Test10" already: CL-2, which names Test 10 mg, may use it again
    profiles[:] = [_profile("d2", "Test 10 mg")]
    confirmed = {"d2"}
    released = ({"d2"}, {"test10"})
    way = fw.formulation_way(ws, [named])
    assert [(e.way, e.products, e.ready, e.named) for e in way.each] == [("use_profile", ("Test 10 mg",), True, "Test 10 mg")]
    # a study that names none is not offered it (it is Test10's release)
    assert fw.formulation_way(ws, [none]).each[0].way == "add_dissolution"


@pytest.mark.req("T-47", "F-402")
def test_a_blinded_product_says_which_blinded_study_its_values_are(tmp_path):
    """Round 6 (round 5's skeptic): a product (or the compound) is blinded because it holds a blinded study's values; its
    card names that study ("it holds the values of study 230-23, which is blinded"), where round 5 said "a blinded study"
    and the card's body said "this study is blinded" of a product. Each blinded study once, by its label; a study that is
    not blinded is not named."""
    from modeler_project import intake_review
    from modeler_project.ledger_view import LedgerView

    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    ledger = _Ledger(ws)
    blinded, other, also = ledger.entity("study", "230-23"), ledger.entity("study", "230-24"), ledger.entity("study", "230-25")
    product = ledger.entity("product", "Test 10 mg")
    ledger.fact("product_role", "TEST", study=blinded, product=product)
    ledger.fact("dose", 10.0, study=blinded, product=product)
    ledger.fact("product_role", "TEST", study=other, product=product)
    reader = LedgerView(ws)
    assert intake_review.held_why(reader, "product", product, {blinded}) == "it holds the values of study 230-23, which is blinded"
    ledger.fact("product_role", "TEST", study=also, product=product)
    assert intake_review.held_why(LedgerView(ws), "product", product, {blinded, also}) == (
        "it holds the values of studies 230-23 and 230-25, which are blinded")


def _be_workbook() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Reference"
    ws.append(["Study 230-23: plasma desvenlafaxine (ng/mL), 50 mg, fasting"])
    ws.append(["Subject No.", "Period", "Pre-dose", "1.00", "2.00", "4.00 h", "8.00", "24.00"])
    ws.append(["001", "I", "BLQ", 40.5, 80.2, 95.0, 60.1, 12.3])
    ws.append(["002", "II", "BLQ", 35.0, 70.4, 88.8, 55.5, "NS"])
    ws.append(["Mean", None, None, 37.8, 75.3, 91.9, 57.8, None])
    ws.append([])
    ws.append(["BLQ: below 1.0 ng/mL"])
    return _save(wb)


def test_a_sheet_is_shown_with_a_suggested_form_and_read_from_the_form(setup):
    c, _ws = setup
    sub = c.post("/api/v1/projects/p1/client-data", headers=H,
                 files=[("files", ("230-23 Fasting Reference.xlsx", _be_workbook(), XLSX))]).json()["data"]["files"][0]
    sheet = c.get(f"/api/v1/projects/p1/client-data/{sub['id']}/sheets/Reference", headers=H).json()["data"]
    assert sheet["rows"][1][:3] == ["Subject No.", "Period", "Pre-dose"] and sheet["read_before"] == []
    form = sheet["form"]
    assert form["layout"] == "times_across" and form["subject_column"] == "A" and form["last_data_row"] == 4
    assert form["constants"]["study_id"] == "230-23-REF" and form["lloq"] == 1.0
    assert any("'NS'" in n for n in sheet["notes"]) and form["missing_tokens"] == ["NS"]   # read as no sample by code

    # unmarked, "NS" is not a number: the preview names the cell, and nothing is kept
    assert form["mean_row"] == 5
    form["mean_n"] = 2                        # the Mean row under the subjects is read as the study's mean profile
    study = {"n": 2, "design": "SD", "crossover": True, "purpose": "external_validation"}
    unmarked = {**form, "missing_tokens": []}
    preview = c.post(f"/api/v1/projects/p1/client-data/{sub['id']}:map", headers=H,
                     json={"form": unmarked, "study": study}).json()["data"]
    assert not preview["ready"] and [i["location"] for i in preview["issues"]] == ["Reference!H4"]
    preview = c.post(f"/api/v1/projects/p1/client-data/{sub['id']}:map", headers=H, json={"form": form, "study": study}).json()["data"]
    assert preview["ready"] and preview["concentrations"] == 11 + 4 and preview["recipe"]["tables"][0]["time_row"] == 2
    sample = preview["sample"]
    assert sample["series"] == ["001 / I", "002 / II", "Mean"] and sample["times"] == [0, 1, 2, 4, 8, 24] and sample["below_lloq"] == 2
    assert sample["rows"][1] == {"series": "001 / I", "time": 1.0, "value": 40.5, "blq": False, "cell": "Reference!D3"}
    done = c.post(f"/api/v1/projects/p1/client-data/{sub['id']}:map", headers=H,
                  json={"form": form, "study": study, "confirm": True}).json()["data"]
    ds = next(d for d in c.get("/api/v1/projects/p1/evidence", headers=H).json()["data"]["datasets"] if d["id"] == done["datasets"][0])
    assert ds["purpose"] == "external_validation" and ds["study"]["study_id"] == "230-23-REF" and ds["study"]["lloq"] == 1.0
    again = c.get(f"/api/v1/projects/p1/client-data/{sub['id']}/sheets/Reference", headers=H).json()["data"]
    assert again["read_before"][0]["datasets"] == done["datasets"]
    refused = c.post(f"/api/v1/projects/p1/client-data/{sub['id']}:map", headers=H, json={"study": study})
    assert refused.status_code == 422


def test_reading_a_sheet_again_replaces_the_earlier_reading(setup):
    c, _ws = setup
    sub = c.post("/api/v1/projects/p1/client-data", headers=H,
                 files=[("files", ("230-23_Fasting_Reference.xlsx", _be_workbook(), XLSX))]).json()["data"]["files"][0]
    form = c.get(f"/api/v1/projects/p1/client-data/{sub['id']}/sheets/Reference", headers=H).json()["data"]["form"]
    assert form["constants"]["study_id"] == "230-23-REF" and form["constants"]["food_state"] == "fasted"
    form["missing_tokens"] = ["NS"]
    form["mean_n"] = 2
    study = {"n": 2, "design": "SD", "purpose": "model_building"}
    first = c.post(f"/api/v1/projects/p1/client-data/{sub['id']}:map", headers=H,
                   json={"form": form, "study": study, "confirm": True}).json()["data"]["datasets"]
    # the purpose was wrong: read again, replacing the first reading
    second = c.post(f"/api/v1/projects/p1/client-data/{sub['id']}:map", headers=H,
                    json={"form": form, "study": {**study, "purpose": "external_validation"}, "confirm": True, "replace": True})
    assert second.status_code == 200, second.text
    datasets = {d["id"]: d for d in c.get("/api/v1/projects/p1/evidence", headers=H).json()["data"]["datasets"]}
    assert datasets[first[0]]["state"] == "REJECTED" and "read again" in datasets[first[0]]["decision_reason"]
    assert datasets[second.json()["data"]["datasets"][0]]["purpose"] == "external_validation"
    view = c.get(f"/api/v1/projects/p1/client-data/{sub['id']}/sheets/Reference", headers=H).json()["data"]
    assert [r["datasets"] for r in view["read_before"]] == [second.json()["data"]["datasets"]]


def test_a_triage_start_answers_through_its_typed_model(setup, monkeypatch):
    # phase 6c: no test reached the started answer of :triage (the conftest guard checks each answer)
    from modeler_api import agent_jobs, client_api, jobs

    c, ws = setup
    sub = c.post("/api/v1/projects/p1/client-data", headers=H,
                 files=[("files", ("raw.xlsx", _raw_workbook(), XLSX))]).json()["data"]["files"][0]

    class Configured:
        provider, model = "test", "scripted"

    calls = []
    monkeypatch.setattr(agent_jobs, "chat_model", lambda agent=None: (Configured(), None))
    monkeypatch.setattr(client_api, "run_triage_job", lambda *args, **kwargs: calls.append(args))
    started = c.post(f"/api/v1/projects/p1/client-data/{sub['id']}:triage", headers=H)
    assert started.status_code == 202 and started.json()["data"] == {"status": "RUNNING"}
    for _ in range(200):
        if not jobs.running(ws.store, "t1", "p1", "triage"):
            break
        time.sleep(0.01)
    assert calls and calls[0][3] == sub["id"]


@pytest.mark.req("T-21")
def test_the_reading_agent_proposes_each_unread_data_sheet_and_the_page_shows_its_checked_proposal(setup):
    """R3c: A4 corrects code's first filling of each data sheet; code checks it, and the sheet then opens on the agent's
    reading, marked as the agent's, for the person to check and save. Nothing is read into the project by the agent."""
    from modeler_agents.llm import ChatResult, ToolCall
    from modeler_api.client_api import run_reading_job

    c, ws = setup
    sub = c.post("/api/v1/projects/p1/client-data", headers=H,
                 files=[("files", ("230-23_Fasting_Reference.xlsx", _be_workbook(), XLSX))]).json()["data"]["files"][0]
    first = c.get(f"/api/v1/projects/p1/client-data/{sub['id']}/sheets/Reference", headers=H).json()["data"]
    assert first["proposed_by"] == "code" and first["run_id"] is None
    corrected = {**first["form"], "missing_tokens": ["NS"], "mean_n": 2}     # what code's filling left for a person
    guessed = {**corrected, "constants": {**corrected["constants"], "n": "24"}}  # an n the sheet never states

    class Scripted:
        provider, model = "test", "scripted"

        def __init__(self):
            self.turns = [[("propose_reading", {"form": guessed})], [("propose_reading", {"form": corrected})], []]

        def complete(self, messages, tools):
            calls = self.turns.pop(0)
            return ChatResult(content="done", finish_reason="", model="s", usage={"input_tokens": 1, "output_tokens": 1},
                              tool_calls=tuple(ToolCall(id=str(i), name=n, arguments=a) for i, (n, a) in enumerate(calls)))

    result = run_reading_job(ws.store, "t1", "p1", sub["id"], model=Scripted())
    assert [(s["sheet"], s["proposed"], s["refused"]) for s in result["sheets"]] == [("Reference", True, 1)]
    assert c.get("/api/v1/projects/p1/evidence", headers=H).json()["data"]["datasets"] == []    # nothing read yet
    sheet = c.get(f"/api/v1/projects/p1/client-data/{sub['id']}/sheets/Reference", headers=H).json()["data"]
    assert sheet["proposed_by"] == f"agent:{result['sheets'][0]['run_id']}" and sheet["run_id"] == result["sheets"][0]["run_id"]
    assert sheet["form"]["missing_tokens"] == ["NS"] and "n" not in sheet["form"]["constants"]
    run = c.get(f"/api/v1/projects/p1/agent-runs/{sheet['run_id']}", headers=H).json()["data"]
    assert run["run"]["agent"] == "A4-sheet-reading" and run["run"]["status"] == "COMPLETED"
    assert any(s["kind"] == "tool_result" and "REJECTED" in str(s["content"]) for s in run["steps"])   # the refusal is kept

    # the person saves the agent's reading once; the sheet is then read, and nothing is left for the agent
    study = {"n": 2, "design": "SD", "purpose": "model_building"}
    saved = c.post(f"/api/v1/projects/p1/client-data/{sub['id']}:map", headers=H,
                   json={"form": sheet["form"], "study": study, "confirm": True})
    assert saved.status_code == 200, saved.text
    assert len(saved.json()["data"]["datasets"]) == 1
    left = c.post(f"/api/v1/projects/p1/client-data/{sub['id']}:read", headers=H)
    assert left.status_code == 409 and "no data sheet is left to read" in left.json()["detail"]


@pytest.mark.req("T-21")
def test_a_reading_start_runs_in_the_background_and_refuses_the_template_and_unknown_sheets(setup, monkeypatch):
    from modeler_api import agent_jobs, intake_jobs, jobs
    from modeler_intake.client_template import build_template

    c, ws = setup
    sub = c.post("/api/v1/projects/p1/client-data", headers=H,
                 files=[("files", ("230-23_Fasting_Reference.xlsx", _be_workbook(), XLSX))]).json()["data"]["files"][0]
    off = c.post(f"/api/v1/projects/p1/client-data/{sub['id']}:read", headers=H)
    assert off.status_code == 409 and "agents are off" in off.json()["detail"]

    class Configured:
        provider, model = "test", "scripted"

    calls = []
    monkeypatch.setattr(agent_jobs, "chat_model", lambda agent=None: (Configured(), None))
    monkeypatch.setattr(intake_jobs, "run_reading_job", lambda *args, **kwargs: calls.append((args, kwargs)))
    assert c.post(f"/api/v1/projects/p1/client-data/{sub['id']}:read", headers=H, json={"sheets": ["Nope"]}).status_code == 404
    started = c.post(f"/api/v1/projects/p1/client-data/{sub['id']}:read", headers=H, json={"sheets": ["Reference"]})
    assert started.status_code == 202 and started.json()["data"] == {"status": "RUNNING"}
    for _ in range(200):
        if not jobs.running(ws.store, "t1", "p1", "reading"):
            break
        time.sleep(0.01)
    assert calls and calls[0][0][3] == sub["id"] and calls[0][1]["sheets"] == ["Reference"]
    template = c.post("/api/v1/projects/p1/client-data", headers=H,
                      files=[("files", ("filled.xlsx", build_template(), XLSX))]).json()["data"]["files"]
    tid = next(f["id"] for f in template if f["file"] == "filled.xlsx")
    refused = c.post(f"/api/v1/projects/p1/client-data/{tid}:read", headers=H)
    assert refused.status_code == 409 and "cell by cell" in refused.json()["detail"]


@pytest.mark.req("T-42")
def test_the_data_request_lists_what_only_the_client_sends_on_start_and_downloads_as_the_workbook(setup):
    # page review 1 (the owner's decision 2b of 2026-10-29): the CRO's day-one data request, from the data plan
    from modeler_project.requirements import RequirementMatrix, client_request

    c, ws = setup
    expected = client_request(RequirementMatrix.from_content(ws.latest(ArtifactKind.REQUIREMENTS, "main").content))
    assert expected, "the core template asks the client for something even before the brief is filled"
    start = c.get("/api/v1/projects/p1/brief", headers=H).json()["data"]["start"]
    assert [line["req_id"] for line in start["client_request"]] == [line.req_id for line in expected]
    r = c.get("/api/v1/projects/p1/client-data/request.xlsx", headers=H)
    assert r.status_code == 200 and r.headers["content-type"] == XLSX
    assert r.headers["content-disposition"] == 'attachment; filename="p1-data-request.xlsx"'
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames[0] == "Request" and wb["Request"]["A1"].value.startswith("Data request: Exampleamide (p1), ")
    rows = [[cell.value for cell in row] for row in wb["Request"].iter_rows(min_row=5)]
    assert [row[1] for row in rows] == [line.what for line in expected]


def test_a_withdrawn_client_file_is_shown_but_not_read_into_the_project(setup):
    # the document library, PR 2: a withdrawn file is kept and opened, but not classified, read or mapped until restored
    from modeler_project.documents import DocumentLibrary

    c, ws = setup
    view = c.post("/api/v1/projects/p1/client-data", headers=H, files=[("files", ("raw.xlsx", _raw_workbook(), XLSX))]).json()["data"]
    sub = view["files"][0]
    DocumentLibrary(ws).withdraw(sub["sha256"], by="u1", reason="the client sent a corrected file")
    assert c.get(f"/api/v1/projects/p1/client-data/{sub['id']}/sheets/Sheet1", headers=H).status_code == 200
    refused = c.post(f"/api/v1/projects/p1/client-data/{sub['id']}/sheets/Misc:classify", headers=H,
                     json={"category": "PRODUCT_INFO", "reason": "batch list"})
    assert refused.status_code == 409 and "the client sent a corrected file" in refused.json()["detail"]
    assert c.post(f"/api/v1/projects/p1/client-data/{sub['id']}:read", headers=H).status_code == 409



def test_the_clients_data_is_confirmed_inline_by_group_with_no_reason_asked(setup):
    # plan 2026-11-03 §3.3 (the owner, 2026-11-03): a group loads once a person confirms it; an open question blocks it;
    # the selection is confirmed with no reason; a settled question stays shown with its answer
    c, ws = setup
    from modeler_project.dataset_register import propose_dataset
    from modeler_project.datasets import ObservedDataset, Origin, Series, new_dataset_id
    from modeler_project.evidence import SourceRef

    propose_dataset(ws, ObservedDataset(
        id=new_dataset_id(), kind="profile", study={"study_id": "EX-7", "route": "oral", "dose_mg": 10, "n": 12,
                                                    "n_timepoints": 3, "statistic": "mean", "formulation": "ir_tablet"},
        analyte="parent", matrix="plasma", time_unit="h", unit="ng/ml",
        series=(Series(name="mean", statistic="arithmetic_mean", times=(1, 2, 6), values=(40.0, 30.0, 10.0)),),
        origin=Origin.CLIENT, extraction="CELL", provider="CLIENT", source=SourceRef(title="pk.csv"), quote="row"), actor="u")
    page = c.get("/api/v1/projects/p1/client-review", headers=H).json()["data"]
    group = next(g for g in page["groups"] if g["id"] == "study:EX-7")
    assert page["to_confirm"] >= 1 and group["state"] == "to_confirm" and group["open"] == 1
    blocked = c.post("/api/v1/projects/p1/client-review:confirm", headers=H, json={"group": group["id"]})
    assert blocked.status_code == 409 and "settle 1 open item" in blocked.json()["detail"]
    food = group["issues"][0]
    picked = c.post("/api/v1/projects/p1/client-review:select", headers=H,
                    json={"group": group["id"], "issue": food["id"], "option": "fasted"})
    assert picked.status_code == 200, picked.text
    after = next(g for g in picked.json()["data"]["groups"] if g["id"] == group["id"])
    assert after["issues"][0]["selected"] == "fasted" and after["open"] == 0            # settled, and still shown
    todo = c.get("/api/v1/projects/p1/inputs", headers=H).json()["data"]["todo"]
    assert any(t["kind"] == "confirm" and t["target"] == group["id"] and t["tab"] == "studies" for t in todo)
    done = c.post("/api/v1/projects/p1/client-review:confirm", headers=H, json={"group": group["id"]})
    assert done.status_code == 200
    confirmed = next(g for g in done.json()["data"]["groups"] if g["id"] == group["id"])
    assert confirmed["state"] == "confirmed" and confirmed["confirmed_by"] == "u1"
    assert c.post("/api/v1/projects/p1/client-review:confirm", headers=H, json={"group": "study:nope"}).status_code == 404


# --- I4: a client's PDF or Word file read for its data ----------------------------------------------------------------


def test_a_client_pdf_is_read_by_the_agent_and_its_data_wait_on_inputs(setup, monkeypatch):
    """I4: the PDF's pages are listed by code at upload; :read starts the reading agent on it (409 while agents are off);
    what code accepts lands in its study group, to confirm, with the page and quote it came from."""
    from modeler_agents.llm import ChatResult, ToolCall
    from modeler_api import agent_jobs, client_api, intake_jobs, jobs
    from modeler_project.delivery_eval import synthetic_pdf

    c, ws = setup
    pdf = synthetic_pdf([["Clinical Study Synopsis: Study EX-7",
                          ("Twelve healthy subjects (n = 12) received a single oral dose of 10 mg as one tablet after an "
                           "overnight fast.")]])
    sub = c.post("/api/v1/projects/p1/client-data", headers=H,
                 files=[("files", ("EX-7 synopsis.pdf", pdf, "application/pdf"))]).json()["data"]["files"][0]
    page = c.get("/api/v1/projects/p1/client-data", headers=H).json()["data"]
    listed = next(f for f in page["files"] if f["id"] == sub["id"])
    assert listed["inventory"][0]["page"] == 1 and listed["inventory"][0]["holds"] == "design"
    off = c.post(f"/api/v1/projects/p1/client-data/{sub['id']}:read", headers=H)
    assert off.status_code == 409 and "agents are off" in off.json()["detail"]

    class Configured:
        provider, model = "test", "scripted"

    calls, run_document_job = [], client_api.run_document_job
    monkeypatch.setattr(agent_jobs, "chat_model", lambda agent=None: (Configured(), None))
    monkeypatch.setattr(intake_jobs, "run_document_job", lambda *args, **kwargs: calls.append(args))
    started = c.post(f"/api/v1/projects/p1/client-data/{sub['id']}:read", headers=H)
    assert started.status_code == 202 and started.json()["data"] == {"status": "RUNNING"}
    for _ in range(200):
        if not jobs.running(ws.store, "t1", "p1", "reading"):
            break
        time.sleep(0.01)
    assert calls and calls[0][3] == sub["id"]

    quote = "a single oral dose of 10 mg"

    class Scripted:
        provider, model = "test", "scripted"

        def __init__(self):
            self.turns = [[("propose_study_facts", {"study_id": "EX-7", "facts": [
                {"fact": "dose", "value": 10, "unit": "mg", "page": 1, "quote": quote},
                {"fact": "dose", "value": 20, "unit": "mg", "page": 1, "quote": quote}]})], []]

        def complete(self, messages, tools):
            calls = self.turns.pop(0)
            return ChatResult(content="one study's dose", finish_reason="", model="s",
                              usage={"input_tokens": 1, "output_tokens": 1},
                              tool_calls=tuple(ToolCall(id=str(i), name=n, arguments=a) for i, (n, a) in enumerate(calls)))

    result = run_document_job(ws.store, "t1", "p1", sub["id"], model=Scripted())
    assert (result["facts"], result["refused"], result["status"]) == (1, 1, "COMPLETED")
    page = c.get("/api/v1/projects/p1/client-data", headers=H).json()["data"]
    read = next(f for f in page["files"] if f["id"] == sub["id"])["document_reads"][-1]
    assert read["run_id"] == result["run_id"] and "must state the dose 20 mg" in read["refused"][0]
    review = c.get("/api/v1/projects/p1/client-review", headers=H).json()["data"]
    group = next(g for g in review["groups"] if g["id"] == "study:EX-7")
    assert group["state"] == "to_confirm" and group["items"] == []                    # a study only the synopsis describes
    dose = next(f for f in group["facts"] if f["field"] == "dose_mg")
    assert dose["value"] == "10" and dose["source"]["page"] == 1 and dose["source"]["quote"] == quote
    run = c.get(f"/api/v1/projects/p1/agent-runs/{result['run_id']}", headers=H).json()["data"]
    assert run["run"]["agent"] == "A4-document-reading"


def test_each_file_carries_its_tag_which_places_it_and_a_changed_tag_moves_it(setup):
    """Plan 2026-11-05 §3.1 (the owner, 2026-11-05: every file went under Clinical studies): the page shows each client
    file in the area of its data, by its tag; another kind read from its content is offered; a changed tag moves it."""
    import json

    c, _ws = setup
    tags = {"Data_Q3.xlsx": {"kind": "formulation", "study": ""}}       # as added on Products and dissolution
    up = c.post("/api/v1/projects/p1/client-data", headers=H, data={"tags": json.dumps(tags)},
                files=[("files", ("Data_Q3.xlsx", _raw_workbook(), XLSX)),
                       ("files", ("Dissolution pH 6.8 notes.md", b"# Dissolution\nUSP 2, 50 rpm", "text/markdown"))])
    assert up.status_code == 201, up.text
    files = {f["file"]: f for f in c.get("/api/v1/projects/p1/client-data", headers=H).json()["data"]["files"]}
    data_q3, notes = files["Data_Q3.xlsx"], files["Dissolution pH 6.8 notes.md"]
    assert (data_q3["tag"]["kind"], data_q3["tag"]["by"]) == ("formulation", "u1")
    assert data_q3["tag_proposal"]["kind"] == "clinical" and data_q3["tag_proposal"]["decided"] == "open"
    assert (notes["tag"]["kind"], notes["tag"]["by"]) == ("formulation", "code")        # untagged: its name's
    moved = c.post(f"/api/v1/projects/p1/documents/{data_q3['sha256']}:tag", headers=H, json={"kind": "clinical"})
    assert moved.status_code == 200, moved.text
    after = {f["file"]: f for f in c.get("/api/v1/projects/p1/client-data", headers=H).json()["data"]["files"]}["Data_Q3.xlsx"]
    assert after["tag"]["kind"] == "clinical" and after["tag_proposal"]["decided"] == "used"


def test_a_study_card_carries_each_datasets_points_and_codes_statistics(setup):
    """Build C (plan 2026-11-05 §3.2; the owner: "no data points, no graph, no statistics"): each dataset on its study's
    card with its points and the platform's NCA of each profile series."""
    c, _ws = setup
    wb = load_workbook(io.BytesIO(c.get("/api/v1/client-data/template.xlsx", headers=H).content))
    header = [x.value.rstrip("*") for x in wb["Studies"][1]]
    values = {"study_id": "CL-1", "design": "SD", "population": "healthy", "n": 12, "route": "oral", "dose": 10,
              "dose_unit": "mg", "formulation": "ir_tablet", "food_state": "fasted"}
    wb["Studies"].append([values.get(h) for h in header])
    for t, v in ((0.5, 20.0), (1, 41.0), (2, 30.5), (4, 12.0)):
        wb["PK_Summary"].append(["CL-1", None, t, "h", "arithmetic_mean", v, None, None, 12, "ng/ml"])
    assert c.post("/api/v1/projects/p1/client-data", headers=H, files=[("files", ("client.xlsx", _save(wb), XLSX))]).status_code == 201
    group = next(g for g in c.get("/api/v1/projects/p1/client-review", headers=H).json()["data"]["groups"] if g["id"] == "study:CL-1")
    (item,) = [i for i in group["items"] if i["kind"] == "dataset"]
    data = item["data"]
    assert (data["kind"], data["unit"], data["time_unit"], data["blinded"]) == ("profile", "ng/ml", "h", False)
    (series,) = data["series"]
    assert series["times"] == [0.5, 1, 2, 4] and series["values"] == [20.0, 41.0, 30.5, 12.0]
    assert series["stats"]["c_max"] == 41.0 and series["stats"]["t_max"] == 1 and series["stats"]["points"] == 4


def test_a_sheet_read_by_code_on_arrival_is_finished_on_its_card_and_reread_when_reclassified(setup):
    """Build C2 (plan 2026-11-05 §3.1): each data sheet is read by code when the file arrives; what the sheet does not
    say is asked on its study's card, and the answer saves the reading; a sheet a person calls data is read at once."""
    c, _ws = setup
    c.post("/api/v1/projects/p1/client-data", headers=H, files=[("files", ("BE_230-23.xlsx", _be_workbook(), XLSX))])
    groups = c.get("/api/v1/projects/p1/client-review", headers=H).json()["data"]["groups"]
    card = next(g for g in groups if any(i["kind"] == "draft" for i in g["items"]))
    draft = next(i for i in card["items"] if i["kind"] == "draft")
    assert card["open"] >= 1 and "n" in draft["draft"]["needs"] and draft["data"]["series"]      # drawn before it is saved
    answers = {"n": 2, "formulation": "mr", "purpose": "external_validation", "food_state": "fasted"}
    bad = c.post("/api/v1/projects/p1/client-review:finish", headers=H,
                 json={"file": draft["draft"]["sid"], "sheet": draft["draft"]["sheet"], "answers": {**answers, "purpose": "x"}})
    assert bad.status_code == 422 and "what the study is for" in bad.json()["detail"]
    done = c.post("/api/v1/projects/p1/client-review:finish", headers=H, json={
        "file": draft["draft"]["sid"], "sheet": draft["draft"]["sheet"],
        "answers": {k: v for k, v in answers.items() if k in draft["draft"]["needs"]}})
    assert done.status_code == 200, done.text
    card = next(g for g in done.json()["data"]["groups"] if g["id"] == card["id"])
    assert [i["kind"] for i in card["items"]] == ["dataset"] and card["items"][0]["data"]["series"]

    # a sheet code left unsorted, then called concentrations by a person: read at once
    wb = Workbook()
    sheet = wb.active
    sheet.title = "Notes"
    for row in (["Study ABC-9, 25 mg oral tablet, fasted"], ["Subject", "Time (h)", "Conc (ng/mL)"], ["001", 1, 22.4],
                ["001", 2, 15.0], ["002", 1, 20.0], ["002", 2, 14.1]):
        sheet.append(row)
    view = c.post("/api/v1/projects/p1/client-data", headers=H, files=[("files", ("misc.xlsx", _save(wb), XLSX))]).json()["data"]
    misc = next(f for f in view["files"] if f["file"] == "misc.xlsx")

    def notes_draft() -> bool:
        groups = c.get("/api/v1/projects/p1/client-review", headers=H).json()["data"]["groups"]
        return any(i["kind"] == "draft" and i["draft"]["sid"] == misc["id"] for g in groups for i in g["items"])

    for category, drafted in (("OTHER", False), ("PK_INDIVIDUAL", True)):
        r = c.post(f"/api/v1/projects/p1/client-data/{misc['id']}/sheets/Notes:classify", headers=H,
                   json={"category": category, "reason": "said by a person"})
        assert r.status_code == 200, r.text
        assert notes_draft() is drafted


def test_a_client_document_is_read_by_the_agent_on_arrival_when_agents_are_on(setup, monkeypatch):
    """Build C2: a PDF or Word file goes to the reading agent when it arrives, in the background (agents on)."""
    from modeler_api import agent_jobs, intake_jobs, jobs
    from modeler_project.delivery_eval import synthetic_pdf

    c, ws = setup

    class Configured:
        provider, model = "test", "scripted"

    calls = []
    monkeypatch.setattr(agent_jobs, "chat_model", lambda agent=None: (Configured(), None))
    monkeypatch.setattr(intake_jobs, "run_document_job", lambda *args, **kwargs: calls.append(args[3]))
    pdf = synthetic_pdf([["Study EX-8: twelve subjects received a single oral dose of 10 mg after an overnight fast."]])
    up = c.post("/api/v1/projects/p1/client-data", headers=H, files=[("files", ("EX-8 synopsis.pdf", pdf, "application/pdf"))])
    assert up.status_code == 201, up.text
    for _ in range(200):
        if not jobs.running(ws.store, "t1", "p1", "reading"):
            break
        time.sleep(0.01)
    assert calls == [up.json()["data"]["read"][0]["id"]]


def _nc_workbook(last: float = 12.3) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Reference"
    ws.append(["Study 230-23: plasma desvenlafaxine (ng/mL), 50 mg, fasting"])
    ws.append(["Subject No.", "Period", "Pre-dose", "1.00", "2.00", "4.00 h", "8.00", "24.00"])
    ws.append(["001", "I", "BLQ", 40.5, 80.2, 95.0, 60.1, last])
    ws.append(["002", "II", "BLQ", 35.0, 70.4, 88.8, 55.5, "n.c."])
    ws.append([])
    ws.append(["BLQ: below 1.0 ng/mL; n.c.: not collected"])
    return _save(wb)


class _Reader:
    """A4 as a script: the turns' tool calls, then done."""

    provider, model = "test", "scripted"

    def __init__(self, turns):
        self.turns = list(turns)

    def complete(self, messages, tools):
        from modeler_agents.llm import ChatResult, ToolCall

        calls = self.turns.pop(0) if self.turns else []
        return ChatResult(content="done", finish_reason="", model="s", usage={"input_tokens": 1, "output_tokens": 1},
                          tool_calls=tuple(ToolCall(id=str(i), name=n, arguments=a) for i, (n, a) in enumerate(calls)))


@pytest.mark.req("T-47")
def test_the_reading_agent_does_on_arrival_what_code_could_not(setup):
    """Plan 2026-11-05 §3.1, build F: with agents on, a sheet code could not sort is sorted, and one whose code reading
    has a problem is read again by the agent. The agent's reading replaces code's only when its check is clean; one it
    cannot resolve leaves code's, saying so, and is not tried again. Each reading says what it left out (the record)."""
    from modeler_api import intake_jobs
    from modeler_project.client_data import submission

    c, ws = setup
    files = c.post("/api/v1/projects/p1/client-data", headers=H,      # agents off here: nothing runs in the background
                   files=[("files", ("230-23 Fasting Reference.xlsx", _nc_workbook(), XLSX)),
                          ("files", ("raw.xlsx", _raw_workbook(), XLSX))]).json()["data"]["read"]
    sid, raw = files[0]["id"], files[1]["id"]
    code = submission(ws, sid)["readings"]["Reference"]
    assert code["by"] == "code" and code["problems"] == ["'n.c.' is not a number"]
    assert intake_jobs.problem_sheets(submission(ws, sid)) == ["Reference"]
    assert any(line["kind"] == "ignored" and "n.c." in line["text"] for line in code["cleaning"])

    fixed = {**code["form"], "missing_tokens": ["n.c."]}
    result = intake_jobs.run_arrival_job(ws.store, "t1", "p1", sid, model=_Reader([[("propose_reading", {"form": fixed})]]))
    assert [(r["sheet"], r["adopted"], r["saved"]) for r in result["read"]] == [("Reference", True, [])]  # facts still to give
    agent = submission(ws, sid)["readings"]["Reference"]
    assert agent["by"].startswith("agent:") and agent["problems"] == [] and set(agent["needs"]) == {"n", "formulation", "purpose"}
    assert any(line["kind"] == "no_sample" and "n.c." in line["text"] for line in agent["cleaning"])
    assert intake_jobs.problem_sheets(submission(ws, sid)) == []
    (item,) = [i for g in c.get("/api/v1/projects/p1/client-review", headers=H).json()["data"]["groups"]
               for i in g["items"] if i["kind"] == "draft" and i["draft"]["sid"] == sid]
    assert item["draft"]["by"].startswith("agent:") and item["draft"]["cleaning"]

    # the agent's reading has the same problem: code's stays, said so, and the sheet is not tried again
    other = c.post("/api/v1/projects/p1/client-data", headers=H,
                   files=[("files", ("230-24 Fasting Reference.xlsx", _nc_workbook(last=11.9), XLSX))]).json()["data"]["read"][0]["id"]
    unresolved = intake_jobs.run_arrival_job(ws.store, "t1", "p1", other,
                                             model=_Reader([[("propose_reading", {"form": submission(ws, other)["readings"]["Reference"]["form"]})]]))
    assert [(r["sheet"], r["adopted"]) for r in unresolved["read"]] == [("Reference", False)]
    stays = submission(ws, other)["readings"]["Reference"]
    assert stays["by"] == "code" and stays["agent_tried"] and "read this sheet too and could not resolve it" in stays["notes"][-1]
    assert intake_jobs.problem_sheets(submission(ws, other)) == []

    # a sheet code could not sort: the agent sorts it with a header quote
    sort = [[("classify_sheet", {"sheet": "Misc", "category": "PRODUCT_INFO", "cell": "Misc!A1",
                                 "quote": "Shipped with the courier"})]]
    assert intake_jobs.run_arrival_job(ws.store, "t1", "p1", raw, model=_Reader(sort))["sorted"] == 1
    assert {t["sheet"]: t["by"][:6] for t in submission(ws, raw)["triage"]}["Misc"] == "agent:"


# ---- the reading queue (plan 2026-11-10, R1): no file the agent is to read is dropped -------------------------------

class _Configured:
    provider, model = "test", "scripted"


def _hold_reading(ws) -> object:
    """Another worker's live reading lease (a reading runs elsewhere)."""
    import json as _json
    from datetime import UTC, datetime

    from modeler_storage.jobs import FileJobRegistry

    lease = FileJobRegistry(ws.store.root)._path("t1", "p1", "reading")
    lease.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).isoformat()
    lease.write_text(_json.dumps({"owner": "worker-2:4242:x", "host": "worker-2", "pid": 4242, "started_at": now,
                                  "heartbeat_at": now}))
    return lease


def _settle(ws) -> None:
    """Until no reading runs and nothing waits that a running reading would take."""
    from modeler_api import jobs
    from modeler_project.reading_queue import ReadingQueue

    for _ in range(500):
        if not jobs.running(ws.store, "t1", "p1", "reading") and not any(
                i.state == "reading" for i in ReadingQueue(ws).items()):
            return
        time.sleep(0.01)
    raise AssertionError("the reading did not finish")


def _pdf(text: str) -> bytes:
    from modeler_project.delivery_eval import synthetic_pdf

    return synthetic_pdf([[text]])


@pytest.mark.req("T-47")
def test_files_arriving_while_a_reading_runs_are_queued_and_read_once_it_is_free(setup, monkeypatch):
    from modeler_api import agent_jobs, intake_jobs
    from modeler_project.reading_queue import ReadingQueue

    c, ws = setup
    calls = []
    monkeypatch.setattr(agent_jobs, "chat_model", lambda agent=None: (_Configured(), None))
    monkeypatch.setattr(intake_jobs, "run_document_job", lambda *a, **k: calls.append(a[3]) or {"status": "COMPLETED",
                                                                                                  "datasets": 1})
    lease = _hold_reading(ws)
    up = c.post("/api/v1/projects/p1/client-data", headers=H, files=[
        ("files", ("EX-8 synopsis.pdf", _pdf("Study EX-8: twelve subjects, 10 mg, fasted."), "application/pdf")),
        ("files", ("EX-9 synopsis.pdf", _pdf("Study EX-9: twelve subjects, 20 mg, fed."), "application/pdf"))])
    assert up.status_code == 201, up.text
    sids = [r["id"] for r in up.json()["data"]["read"]]
    time.sleep(0.05)
    assert calls == []                                                     # the other reading still runs
    assert [(i.sid, i.state) for i in ReadingQueue(ws).items()] == [(sids[0], "queued"), (sids[1], "queued")]
    lease.unlink()                                                         # it finished elsewhere
    assert c.get("/api/v1/projects/p1/client-data", headers=H).status_code == 200   # the page starts the reading
    _settle(ws)
    assert calls == sids
    items = ReadingQueue(ws).items()
    assert [i.state for i in items] == ["done", "done"] and items[0].found == {"datasets": 1}


@pytest.mark.req("T-47")
def test_one_file_that_fails_is_marked_and_the_others_are_still_read(setup, monkeypatch):
    from modeler_api import agent_jobs, intake_jobs
    from modeler_project.reading_queue import ReadingQueue

    c, ws = setup
    calls = []

    def read(*args, **kwargs):
        calls.append(args[3])
        if len(calls) == 1:
            raise RuntimeError("the model provider timed out")
        return {"status": "COMPLETED", "facts": 2}

    monkeypatch.setattr(agent_jobs, "chat_model", lambda agent=None: (_Configured(), None))
    monkeypatch.setattr(intake_jobs, "run_document_job", read)
    up = c.post("/api/v1/projects/p1/client-data", headers=H, files=[
        ("files", ("A.pdf", _pdf("Study A: 10 mg."), "application/pdf")),
        ("files", ("B.pdf", _pdf("Study B: 20 mg."), "application/pdf"))])
    assert up.status_code == 201, up.text
    _settle(ws)
    items = ReadingQueue(ws).items()
    assert len(calls) == 2 and [i.state for i in items] == ["failed", "done"]
    assert "timed out" in items[0].note and items[1].found == {"facts": 2}


@pytest.mark.req("T-47")
def test_files_are_queued_with_agents_off_and_read_once_agents_are_on(setup, monkeypatch):
    from modeler_api import agent_jobs, intake_jobs
    from modeler_project.reading_queue import ReadingQueue

    c, ws = setup
    calls = []
    monkeypatch.setattr(intake_jobs, "run_document_job", lambda *a, **k: calls.append(a[3]) or {"status": "COMPLETED"})
    up = c.post("/api/v1/projects/p1/client-data", headers=H,
                files=[("files", ("A.pdf", _pdf("Study A: 10 mg."), "application/pdf"))])
    assert up.status_code == 201
    assert [i.state for i in ReadingQueue(ws).items()] == ["queued"] and calls == []
    monkeypatch.setattr(agent_jobs, "chat_model", lambda agent=None: (_Configured(), None))
    c.get("/api/v1/projects/p1/client-data", headers=H)
    _settle(ws)
    assert calls == [up.json()["data"]["read"][0]["id"]] and ReadingQueue(ws).items()[0].state == "done"


@pytest.mark.req("T-47")
def test_a_file_uploaded_again_before_it_was_read_is_queued_and_read_once(setup, monkeypatch):
    from modeler_api import agent_jobs, intake_jobs
    from modeler_project.reading_queue import ReadingQueue

    c, ws = setup
    calls = []
    monkeypatch.setattr(intake_jobs, "run_document_job", lambda *a, **k: calls.append(a[3]) or {"status": "COMPLETED"})
    pdf = _pdf("Study A: 10 mg.")
    for _ in range(2):    # agents off: the first upload is not read; the same file again is not queued twice
        assert c.post("/api/v1/projects/p1/client-data", headers=H,
                      files=[("files", ("A.pdf", pdf, "application/pdf"))]).status_code == 201
    assert len(ReadingQueue(ws).items()) == 1
    monkeypatch.setattr(agent_jobs, "chat_model", lambda agent=None: (_Configured(), None))
    ReadingQueue(ws).recover()
    assert c.post("/api/v1/projects/p1/client-data", headers=H,      # a repeat, agents on: the waiting item is read
                  files=[("files", ("A.pdf", pdf, "application/pdf"))]).status_code == 201
    _settle(ws)
    assert len(calls) == 1 and [i.state for i in ReadingQueue(ws).items()] == ["done"]


@pytest.mark.req("T-47")
def test_a_persons_read_while_another_reading_runs_waits_its_turn(setup, monkeypatch):
    from modeler_api import agent_jobs, intake_jobs
    from modeler_project.reading_queue import ReadingQueue

    c, ws = setup
    calls = []
    sub = c.post("/api/v1/projects/p1/client-data", headers=H,
                 files=[("files", ("230-23_Fasting_Reference.xlsx", _be_workbook(), XLSX))]).json()["data"]["files"][0]
    monkeypatch.setattr(agent_jobs, "chat_model", lambda agent=None: (_Configured(), None))
    monkeypatch.setattr(intake_jobs, "run_reading_job", lambda *a, **k: calls.append((a[3], k["sheets"])) or {
        "status": "COMPLETED", "sheets": [{"sheet": "Reference", "proposed": True, "run_id": "ar_1"}]})
    lease = _hold_reading(ws)
    queued = c.post(f"/api/v1/projects/p1/client-data/{sub['id']}:read", headers=H, json={"sheets": ["Reference"]})
    assert queued.status_code == 202 and queued.json()["data"] == {"status": "QUEUED"}
    lease.unlink()
    c.get("/api/v1/projects/p1/client-data", headers=H)
    _settle(ws)
    read = [i for i in ReadingQueue(ws).items() if i.task == "read"]
    assert calls == [(sub["id"], ["Reference"])]
    assert read[0].state == "done" and read[0].found == {"sheets_proposed": 1} and read[0].run_ids == ("ar_1",)


@pytest.mark.req("T-47")
def test_a_queued_document_with_no_text_or_withdrawn_is_failed_with_why_not_read(setup, monkeypatch):
    from modeler_api import agent_jobs, intake_jobs
    from modeler_project.documents import DocumentLibrary
    from modeler_project.reading_queue import ReadingQueue

    c, ws = setup
    calls = []
    monkeypatch.setattr(intake_jobs, "run_document_job", lambda *a, **k: calls.append(a[3]) or {"status": "COMPLETED"})
    up = c.post("/api/v1/projects/p1/client-data", headers=H,
                files=[("files", ("A.pdf", _pdf("Study A: 10 mg."), "application/pdf"))]).json()["data"]["read"][0]
    DocumentLibrary(ws).withdraw(up["sha256"], by="u1", reason="wrong study")
    monkeypatch.setattr(agent_jobs, "chat_model", lambda agent=None: (_Configured(), None))
    c.get("/api/v1/projects/p1/client-data", headers=H)
    _settle(ws)
    item = ReadingQueue(ws).items()[0]
    assert calls == [] and item.state == "failed" and "withdrawn (wrong study)" in item.note


@pytest.mark.req("T-47")
def test_files_stored_before_one_is_refused_are_still_queued(setup, monkeypatch):
    from modeler_project.reading_queue import ReadingQueue

    c, ws = setup
    up = c.post("/api/v1/projects/p1/client-data", headers=H, files=[
        ("files", ("A.pdf", _pdf("Study A: 10 mg."), "application/pdf")),
        ("files", ("broken.xlsx", b"not a workbook", XLSX))])
    assert up.status_code == 422, up.text
    assert [i.file for i in ReadingQueue(ws).items()] == ["A.pdf"]


class _Down:
    """A model provider that is down."""

    provider, model = "test", "down"

    def complete(self, messages, tools):
        from modeler_agents.run import LLMUnavailableError

        raise LLMUnavailableError("the provider answered 503")


@pytest.mark.req("T-47")
def test_a_workbook_read_on_arrival_while_the_provider_is_down_is_failed_and_not_marked_tried(setup):
    # the R1 review: the arrival reading of a workbook carries the agent's failure, so the queue says it failed, and a
    # sheet the agent never got to read is not marked as tried (it is read again next time)
    from modeler_api import intake_jobs
    from modeler_project.client_data import submission

    c, ws = setup
    sid = c.post("/api/v1/projects/p1/client-data", headers=H,
                 files=[("files", ("230-23 Fasting Reference.xlsx", _nc_workbook(), XLSX))]).json()["data"]["read"][0]["id"]
    result = intake_jobs.run_arrival_job(ws.store, "t1", "p1", sid, model=_Down())
    failed, note, _runs, _found = intake_jobs._outcome(result)
    assert failed and "503" in note
    assert intake_jobs.problem_sheets(submission(ws, sid)) == ["Reference"]          # still to be read by the agent


@pytest.mark.req("T-47")
def test_a_file_whose_reading_failed_is_queued_again_when_it_is_added_again(setup, monkeypatch):
    from modeler_api import agent_jobs, intake_jobs
    from modeler_project.reading_queue import ReadingQueue

    c, ws = setup
    outcomes = [{"status": "LLM_UNAVAILABLE", "error": "the provider answered 503"}, {"status": "COMPLETED", "facts": 1}]
    monkeypatch.setattr(agent_jobs, "chat_model", lambda agent=None: (_Configured(), None))
    monkeypatch.setattr(intake_jobs, "run_document_job", lambda *a, **k: outcomes.pop(0))
    monkeypatch.setattr(intake_jobs, "_needs_agent", lambda content: False)   # as if the failed run left a record
    pdf = _pdf("Study A: 10 mg.")
    first = c.post("/api/v1/projects/p1/client-data", headers=H, files=[("files", ("A.pdf", pdf, "application/pdf"))])
    sid = first.json()["data"]["read"][0]["id"]
    ReadingQueue(ws).add([(sid, "A.pdf")], task="arrival", by="u1")   # (`_needs_agent` is patched: queue it by hand)
    c.get("/api/v1/projects/p1/client-data", headers=H)
    _settle(ws)
    readings = lambda: [i.state for i in ReadingQueue(ws).items() if i.task != "map"]
    assert readings() == ["failed"]
    c.post("/api/v1/projects/p1/client-data", headers=H, files=[("files", ("A.pdf", pdf, "application/pdf"))])
    _settle(ws)
    assert readings() == ["failed", "done"]


@pytest.mark.req("T-47")
def test_a_refused_file_does_not_stop_the_files_after_it(setup):
    from modeler_project.client_data import submissions
    from modeler_project.reading_queue import ReadingQueue

    c, ws = setup
    up = c.post("/api/v1/projects/p1/client-data", headers=H, files=[
        ("files", ("broken.xlsx", b"not a workbook", XLSX)),
        ("files", ("B.pdf", _pdf("Study B: 20 mg."), "application/pdf"))])
    assert up.status_code == 422 and "broken.xlsx" in up.json()["detail"] and "added: B.pdf" in up.json()["detail"]
    assert [f["file"] for f in submissions(ws)] == ["B.pdf"] and [i.file for i in ReadingQueue(ws).items()] == ["B.pdf"]


@pytest.mark.req("T-47")
def test_the_drain_takes_no_more_items_once_its_lease_is_taken_over(setup, monkeypatch):
    from modeler_api import intake_jobs
    from modeler_project.reading_queue import ReadingQueue

    _c, ws = setup
    calls = []
    monkeypatch.setattr(intake_jobs, "_run_item", lambda store, t, p, item, model: calls.append(item.sid) or {})
    ReadingQueue(ws).add([("file-a", "a.pdf"), ("file-b", "b.pdf")], task="read", by="u1")
    held = iter([True, False])
    intake_jobs.drain(ws.store, "t1", "p1", _Configured(), held=lambda: next(held))
    assert calls == ["file-a"] and [i.state for i in ReadingQueue(ws).items()] == ["done", "queued"]


@pytest.mark.req("T-47")
def test_a_file_stored_but_never_queued_is_queued_when_inputs_is_opened(setup):
    # the R1 review: a file stored before the queue existed (or by a request that stopped before queuing it) is found
    from modeler_project.reading_queue import ReadingQueue

    c, ws = setup
    up = c.post("/api/v1/projects/p1/client-data", headers=H,
                files=[("files", ("A.pdf", _pdf("Study A: 10 mg."), "application/pdf"))]).json()["data"]["read"][0]
    queue_file = ws.store.root / "t1" / "projects" / "p1" / "reading-queue.json"
    queue_file.unlink()                                          # as before the queue
    assert ReadingQueue(ws).items() == []
    c.get("/api/v1/projects/p1/client-data", headers=H)
    assert [(i.sid, i.state) for i in ReadingQueue(ws).items()] == [(up["id"], "queued")]


@pytest.mark.req("T-47")
def test_the_reading_tray_lists_each_file_and_reads_a_failed_one_again(setup, monkeypatch):
    # plan 2026-11-10, R3: the tray says, per file, queued / reading / done / failed with what was found or why it failed,
    # whether agents are on, and reads a file again on request
    from modeler_api import agent_jobs, intake_jobs

    c, ws = setup
    tray = c.get("/api/v1/projects/p1/reading-queue", headers=H).json()["data"]
    assert tray["items"] == [] and tray["agents"]["enabled"] is False and tray["counts"]["queued"] == 0
    up = c.post("/api/v1/projects/p1/client-data", headers=H, files=[
        ("files", ("A.pdf", _pdf("Study A: 10 mg."), "application/pdf")),
        ("files", ("B.pdf", _pdf("Study B: 20 mg."), "application/pdf"))]).json()["data"]["read"]
    tray = c.get("/api/v1/projects/p1/reading-queue", headers=H).json()["data"]
    assert [(i["file"], i["state"]) for i in tray["items"]] == [("A.pdf", "queued"), ("B.pdf", "queued")]
    assert tray["counts"] == {"queued": 2, "reading": 0, "done": 0, "failed": 0}   # agents off: they wait

    outcomes = {up[0]["id"]: [{"status": "COMPLETED", "datasets": 2, "facts": 3, "run_id": "ar_1"}],
                up[1]["id"]: [{"status": "LLM_UNAVAILABLE", "error": "the provider answered 503", "run_id": "ar_2"},
                              {"status": "COMPLETED", "facts": 1, "run_id": "ar_3"}]}
    monkeypatch.setattr(agent_jobs, "chat_model", lambda agent=None: (_Configured(), None))
    monkeypatch.setattr(intake_jobs, "run_document_job", lambda *a, **k: outcomes[a[3]].pop(0))
    c.get("/api/v1/projects/p1/reading-queue", headers=H)                     # the tray starts the reading
    _settle(ws)
    tray = c.get("/api/v1/projects/p1/reading-queue", headers=H).json()["data"]
    a, b = [i for i in tray["items"] if i["task"] != "map"]   # (map items: the R4 retry of an unfinished pass)
    assert (a["state"], a["found"], a["run_ids"]) == ("done", {"datasets": 2, "facts": 3}, ["ar_1"])
    assert (b["state"], b["note"]) == ("failed", "the provider answered 503")
    again = c.post(f"/api/v1/projects/p1/reading-queue/{b['id']}:again", headers=H)
    assert again.status_code == 202 and again.json()["data"]["status"] in ("RUNNING", "QUEUED")
    _settle(ws)
    last = [i for i in c.get("/api/v1/projects/p1/reading-queue", headers=H).json()["data"]["items"] if i["task"] != "map"][-1]
    assert (last["file"], last["task"], last["state"], last["found"]) == ("B.pdf", "read", "done", {"facts": 1})
    assert c.post("/api/v1/projects/p1/reading-queue/q-99:again", headers=H).status_code == 404


@pytest.mark.req("T-47")
def test_the_tray_counts_files_not_readings_and_read_again_refuses_what_it_cannot_do(setup, monkeypatch):
    # the R3 review: a file read twice counts once (its latest reading); "Read again" is refused while the file waits or
    # is read, and on a workbook with nothing left for the agent
    from modeler_api import agent_jobs, client_api, intake_jobs
    from modeler_project.reading_queue import ReadingQueue

    c, ws = setup
    up = c.post("/api/v1/projects/p1/client-data", headers=H,
                files=[("files", ("A.pdf", _pdf("Study A: 10 mg."), "application/pdf"))]).json()["data"]["read"][0]
    outcomes = [{"status": "LLM_UNAVAILABLE", "error": "503"}, {"status": "COMPLETED", "facts": 1}]
    monkeypatch.setattr(agent_jobs, "chat_model", lambda agent=None: (_Configured(), None))
    monkeypatch.setattr(intake_jobs, "run_document_job", lambda *a, **k: outcomes.pop(0))
    c.get("/api/v1/projects/p1/reading-queue", headers=H)
    _settle(ws)
    failed = ReadingQueue(ws).items()[0]
    assert c.post(f"/api/v1/projects/p1/reading-queue/{failed.id}:again", headers=H).status_code == 202
    _settle(ws)
    tray = c.get("/api/v1/projects/p1/reading-queue", headers=H).json()["data"]
    assert len(tray["items"]) == 2 and tray["counts"] == {"queued": 0, "reading": 0, "done": 1, "failed": 0}
    ReadingQueue(ws).add([(up["id"], "A.pdf")], task="read", by="u1")          # waiting again
    busy = c.post(f"/api/v1/projects/p1/reading-queue/{failed.id}:again", headers=H)
    assert busy.status_code == 409 and "queued already" in busy.json()["detail"]

    monkeypatch.setattr(agent_jobs, "chat_model", lambda agent=None: (None, "off"))
    sub = c.post("/api/v1/projects/p1/client-data", headers=H,
                 files=[("files", ("230-23_Fasting_Reference.xlsx", _be_workbook(), XLSX))]).json()["data"]["read"][0]
    item = ReadingQueue(ws).add([(sub["id"], "230-23_Fasting_Reference.xlsx")], task="arrival", by="u1")[0]
    while (waiting := ReadingQueue(ws).take()) is not None:                    # A.pdf's Read, the workbook's map item
        ReadingQueue(ws).finish(waiting.id, "done")
    monkeypatch.setattr(intake_jobs, "_needs_agent", lambda content: False)
    monkeypatch.setattr(intake_jobs, "unread_sheets", lambda content: [])
    monkeypatch.setattr(client_api, "unread_sheets", lambda content: [])
    nothing = c.post(f"/api/v1/projects/p1/reading-queue/{item.id}:again", headers=H)
    assert nothing.status_code == 409 and "no data sheet is left to read" in nothing.json()["detail"]


@pytest.mark.req("T-47")
def test_each_queued_file_is_read_as_started_by_the_person_who_added_it(setup, monkeypatch):
    # the merge with the admin console (2026-11-10): agent runs record who started them (`jobs.started_by`); a drain
    # reads files several people added, so it sets each file's own
    from modeler_api import intake_jobs, jobs
    from modeler_project.reading_queue import ReadingQueue

    _c, ws = setup
    seen = []
    monkeypatch.setattr(intake_jobs, "_run_item", lambda *a: seen.append((a[3].sid, jobs.started_by.get())) or {})
    ReadingQueue(ws).add([("file-a", "a.pdf")], task="arrival", by="alice")
    ReadingQueue(ws).add([("file-b", "b.pdf")], task="read", by="bob")
    intake_jobs.drain(ws.store, "t1", "p1", _Configured())
    assert seen == [("file-a", "alice"), ("file-b", "bob")]


class _Mapper:
    """The delivery pass and the readings as a script: the pass names each file's study from its name; a reading
    proposes nothing. It keeps every first user message, to see what each run was told."""

    provider, model = "test", "scripted"

    def __init__(self):
        self.users: list[str] = []

    def complete(self, messages, tools):
        import re

        from modeler_agents.llm import ChatResult, ToolCall

        user = next(m["content"] for m in messages if m["role"] == "user")
        calls = []
        if not any(m["role"] == "tool" for m in messages):
            self.users.append(user)
            if "New files:" in user:   # the delivery pass: each file's study from its name
                calls = [("propose_facts", {"sid": sid, "facts": [{"fact": "study", "value": study, "source": "name",
                                                                    "quote": study}]})
                         for name, sid in re.findall(r"## (\S+) [^(]*\(sid (file-\w+)", user)
                         if (study := name.split()[0].split("_")[0])]
        return ChatResult(content="done", finish_reason="", model="s", usage={"input_tokens": 1, "output_tokens": 1},
                          tool_calls=tuple(ToolCall(id=str(i), name=n, arguments=a) for i, (n, a) in enumerate(calls)))


@pytest.mark.req("T-47")
def test_a_delivery_is_mapped_together_first_and_each_reading_is_told_the_map(setup, monkeypatch):
    # plan 2026-11-10, R4 (the owner's decision 2): files of one upload are mapped together before each is read; each
    # reading is told what the map says of its file and the others; a clean workbook is mapped too
    from modeler_api import agent_jobs
    from modeler_project.client_data import delivery_map
    from modeler_project.reading_queue import ReadingQueue

    c, ws = setup
    model = _Mapper()
    monkeypatch.setattr(agent_jobs, "chat_model", lambda agent=None: (model, None))
    up = c.post("/api/v1/projects/p1/client-data", headers=H, files=[
        ("files", ("093-26_synopsis.pdf", _pdf("Study 093-26: 50 mg, fasted."), "application/pdf")),
        ("files", ("094-26_synopsis.pdf", _pdf("Study 094-26: 50 mg, fed."), "application/pdf"))])
    assert up.status_code == 201, up.text
    _settle(ws)
    sids = [r["id"] for r in up.json()["data"]["read"]]
    passes = [u for u in model.users if "New files:" in u]
    assert len(passes) == 1 and all(f"sid {sid}" in passes[0] for sid in sids)     # both files, one pass
    readings = [u for u in model.users if "New files:" not in u]
    assert len(readings) == 2
    assert all("The delivery map" in u and "every value you propose must still be quoted from this file" in u
               for u in readings)
    assert "- study: 093-26" in readings[0] and "- 094-26_synopsis.pdf: study 094-26" in readings[0]
    assert sorted(delivery_map(ws)["looked_at"]) == sorted(sids)
    tray = c.get("/api/v1/projects/p1/reading-queue", headers=H).json()["data"]
    assert tray["mapped"] == {sids[0]: "study 093-26", sids[1]: "study 094-26"}
    assert [i.state for i in ReadingQueue(ws).items()] == ["done", "done"]

    one = c.post("/api/v1/projects/p1/client-data", headers=H,         # a single file: checked against the map
                 files=[("files", ("230-23_Fasting_Reference.xlsx", _be_workbook(), XLSX))]).json()["data"]["read"][0]
    _settle(ws)
    single = [u for u in model.users if "New files: 1." in u]
    assert single and "The map already says, of files delivered before" in single[0] and "093-26_synopsis.pdf" in single[0]
    assert one["id"] in delivery_map(ws)["looked_at"]


@pytest.mark.req("T-47")
def test_a_pass_that_does_not_finish_is_tried_again_a_few_times_then_the_files_are_read_without_the_map(setup, monkeypatch):
    # the R4 review: a pass stopped by the provider marked its files as mapped, and nothing mapped them again
    from modeler_api import intake_jobs
    from modeler_project.client_data import delivery_map
    from modeler_project.reading_queue import ReadingQueue

    _c, ws = setup
    queue = ReadingQueue(ws)
    queue.add([("file-a", "a.pdf"), ("file-b", "b.pdf")], task="read", by="u1")
    tried = []

    def down(store, t, p, sids, *, model):   # the pass, with the provider down: tried, not finished
        tried.append(list(sids))
        intake_jobs.record_delivery_map(ws, files={}, links=[], looked_at=[], refused=[], summary="503", run_id=None,
                                        by="agent:t", tried=sids, status="LLM_UNAVAILABLE")
        return {"status": "LLM_UNAVAILABLE", "files": len(sids)}

    monkeypatch.setattr(intake_jobs, "run_delivery_job", down)
    for _ in range(intake_jobs.MAP_TRIES + 2):
        intake_jobs.map_waiting(ws.store, "t1", "p1", _Configured(), queue)
    assert tried == [["file-a", "file-b"]] * intake_jobs.MAP_TRIES       # tried again, then given up
    mapped = delivery_map(ws)
    assert mapped["looked_at"] == [] and mapped["tries"] == {"file-a": 2, "file-b": 2}
    assert mapped["runs"][-1]["status"] == "LLM_UNAVAILABLE"


def test_the_reading_waits_for_the_rest_of_a_delivery_sent_in_batches(setup):
    import threading

    from modeler_api import intake_jobs
    from modeler_project.reading_queue import ReadingQueue

    _c, ws = setup
    queue = ReadingQueue(ws)
    queue.add([("file-1", "1.pdf")], task="arrival", by="u1")
    later = threading.Timer(0.05, lambda: queue.add([("file-2", "2.pdf")], task="arrival", by="u1"))
    later.start()
    intake_jobs.settle(queue, quiet_s=0.15, max_s=2.0)
    later.join()
    assert [i.sid for i in queue.items()] == ["file-1", "file-2"]           # the second batch arrived while it waited


@pytest.mark.req("T-47")
def test_a_withdrawn_file_is_left_out_of_what_the_map_tells_a_reading(setup):
    from modeler_api import intake_jobs
    from modeler_project.client_data import record_delivery_map
    from modeler_project.documents import DocumentLibrary

    c, ws = setup
    up = c.post("/api/v1/projects/p1/client-data", headers=H, files=[
        ("files", ("A.pdf", _pdf("Study A: 10 mg."), "application/pdf")),
        ("files", ("B.pdf", _pdf("Study B: 20 mg."), "application/pdf"))]).json()["data"]["read"]
    a, b = up[0], up[1]
    record_delivery_map(ws, files={b["id"]: {"file": "B.pdf", "facts": {"study": {"value": "B", "quote": "B", "where": "file name"}},
                                             "sheets": {}}},
                        links=[{"kind": "study", "names": ["B", "Study Bee"], "sid": b["id"], "page": 1, "locator": "p. 1",
                                "quote": "Study B (Study Bee)"}], looked_at=[a["id"], b["id"]], refused=[], summary="",
                        run_id=None, by="agent:t")
    assert "B.pdf: study B" in intake_jobs.map_note(ws, a["id"])
    DocumentLibrary(ws).withdraw(b["sha256"], by="u1", reason="wrong study")
    note = intake_jobs.map_note(ws, a["id"])
    assert "B.pdf" not in note and "Study Bee" not in note


@pytest.mark.req("T-47")
def test_documents_added_before_reading_for_data_are_listed_and_read_on_request(setup):
    # the owner, 2026-11-11: a delivery added as annexes before R2 stayed stored only ("Nothing taken from it yet"); the
    # tray lists them and reads them for data on request, leaving out what an agent fetched or a person withdrew
    from modeler_project.client_data import submissions
    from modeler_project.documents import DocumentLibrary
    from modeler_project.reading_queue import ReadingQueue

    c, ws = setup
    added = c.post("/api/v1/projects/p1/documents", headers=H, data={"role": "annex", "step": "inputs"}, files=[
        ("files", ("093-26 Summary Statistics.pdf", _pdf("Study 093-26: Cmax 40 ng/mL."), "application/pdf")),
        ("files", ("094-26 Outlier Report.pdf", _pdf("Study 094-26: subject 7 excluded."), "application/pdf")),
        ("files", ("notes.md", b"# Notes", "text/markdown"))]).json()["data"]["documents"]
    DocumentLibrary(ws).withdraw(added[1]["sha256"], by="u1", reason="superseded")
    tray = c.get("/api/v1/projects/p1/reading-queue", headers=H).json()["data"]
    assert tray["unread_documents"] == ["093-26 Summary Statistics.pdf"]          # not the withdrawn one, nor Markdown
    assert submissions(ws) == [] and tray["items"] == []

    read = c.post("/api/v1/projects/p1/documents:read-for-data", headers=H)
    assert read.status_code == 202 and read.json()["data"] == {"reading": ["093-26 Summary Statistics.pdf"], "not_read": []}
    assert [s["file"] for s in submissions(ws)] == ["093-26 Summary Statistics.pdf"]
    assert [(i.file, i.state) for i in ReadingQueue(ws).items() if i.task == "arrival"] == [("093-26 Summary Statistics.pdf", "queued")]
    entry = DocumentLibrary(ws).entry(added[0]["sha256"])
    assert entry.relates_to is not None and entry.relates_to.step == "inputs"          # what it relates to is kept
    roles = {d["name"]: d["role"] for d in c.get("/api/v1/projects/p1/documents", headers=H).json()["data"]["documents"]}
    assert roles["093-26 Summary Statistics.pdf"] == "annex"                            # its library role too
    again = c.get("/api/v1/projects/p1/reading-queue", headers=H).json()["data"]
    assert again["unread_documents"] == []                                               # read once, not listed again
    assert c.post("/api/v1/projects/p1/documents:read-for-data", headers=H).json()["data"]["reading"] == []
