"""T-47: the Data room's API (plan 2026-11-21 v2 §5, §9 "API") on a synthetic delivery (the made-up Exampleamide,
`modeler_project.dataroom.synthetic`; never client data): uploads, the background run with agents off, the room, the
modeler's word (question, decision, entered value, request), "Send to the model" signed with the step-up, and the
source viewer's pages and parts. The agents' answers are written straight into the store, as A6-A8 would submit them.
"""

from __future__ import annotations

import time

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from modeler_api import dataroom_api, project_api
from modeler_api.auth import get_verifier
from modeler_api.main import app
from modeler_project import FileProjectStore, Workspace
from modeler_project.dataroom import DataRoomStore
from modeler_project.dataroom.synthetic import FOLDER, delivery, delivery_zip, seed
from modeler_storage.jobs import FileJobRegistry

pytestmark = pytest.mark.req("T-47")
H = {"Authorization": "Bearer t"}
API = "/api/v1/projects/p1/dataroom"


class FakeVerifier:
    roles: tuple[str, ...] = ("modeler-curator",)
    step_up = True

    def verify(self, token):
        return {"sub": "u1", "name": "Dev User", "tenant_id": "t1", "realm_access": {"roles": list(self.roles)},
                "projects": ["*"], "acr": "loa2" if self.step_up else "loa1", "auth_time": int(time.time())}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    store = FileProjectStore(tmp_path)
    monkeypatch.delenv("MODELER_LLM_PROVIDER", raising=False)
    verifier = FakeVerifier()
    app.dependency_overrides[get_verifier] = lambda: verifier
    app.dependency_overrides[project_api.get_project_store] = lambda: store
    yield TestClient(app), store, verifier
    app.dependency_overrides.clear()


def _run(c: TestClient, **body) -> dict:
    started = c.post(f"{API}/run", headers=H, json=body)
    assert started.status_code == 202, started.text
    assert started.json()["data"]["state"] == "running"
    for _ in range(600):
        run = c.get(f"{API}/run", headers=H).json()["data"]
        if run["state"] != "running":
            return run
        time.sleep(0.1)
    raise AssertionError("the run did not finish")


def _read(c: TestClient) -> dict:
    up = c.post(f"{API}/uploads", headers=H, files=[("files", ("delivery.zip", delivery_zip(), "application/zip"))])
    assert up.status_code == 201, up.text
    return _run(c)


def test_a_delivery_is_uploaded_and_read_with_agents_off_every_agent_stage_saying_why_it_waits(setup):
    c, store, _v = setup
    assert c.get(f"{API}/run", headers=H).json()["data"] == {"state": "idle", "stages": [], "agents": {}, "error": "",
                                                             "started_at": None, "finished_at": None, "pause": None}
    assert c.post(f"{API}/run", headers=H, json={}).status_code == 409          # nothing to read yet
    run = _read(c)
    assert run["state"] == "done" and run["error"] == ""
    stages = {s["id"]: s for s in run["stages"]}
    assert stages["read"]["state"] == "done" and stages["read"]["note"] == "10 files, 0 scanned pages read by OCR"
    for sid in ("question", "triage", "extract", "check", "write"):
        assert stages[sid]["state"] == "skipped" and "no AI model is set up" in stages[sid]["note"]
    again = c.post(f"{API}/uploads", headers=H, files=[("files", ("delivery.zip", delivery_zip(), "application/zip"))])
    assert len(again.json()["data"]["uploads"]) == 1                             # the same bytes are stored once
    room = c.get(API, headers=H).json()["data"]
    assert len(room["files"]) == 10 and room["studies"] == [] and room["question"] is None
    assert [s["id"] for s in room["sections"]][:2] == ["files", "substance"]
    assert next(s for s in room["sections"] if s["id"] == "files")["finding"] == "10 files read"
    # one run at a time: a run held anywhere refuses a second start
    lease = FileJobRegistry(store.root).claim("t1", "p1", "dataroom")
    try:
        assert c.post(f"{API}/run", headers=H, json={}).status_code == 409
    finally:
        FileJobRegistry(store.root).release(lease)
    assert c.post(f"{API}/run", headers=H, json={"stages": ["read", "nothing"]}).status_code == 422
    # a run left "running" by a job that is gone (a restart) reads as failed, with why
    DataRoomStore(Workspace(store, "t1", "p1")).set_run({"state": "running", "stages": [{"id": "read", "state": "running"}]})
    stopped = c.get(f"{API}/run", headers=H).json()["data"]
    assert stopped["state"] == "failed" and "restarted" in stopped["error"] and stopped["stages"][0]["state"] == "failed"


def test_the_room_is_assembled_from_the_agents_answers_and_the_modelers_word_is_audited(setup):
    c, store, _v = setup
    _read(c)
    ws = Workspace(store, "t1", "p1")
    seed(DataRoomStore(ws))
    room = c.get(API, headers=H).json()["data"]
    (study,) = room["studies"]
    sets = {s["name"]: len(s["subjects"]) for s in study["sets"]}
    assert (sets["dosed"], sets["completed"], sets["modeling"], sets["auc"]) == (8, 7, 6, 5)
    assert "LLOQ" in study["excluded"]["3"] and study["nca_method_client"] == "linear trapezoidal"
    assert {d["medium"] for d in room["dissolution"]} == {"pH 6.8 phosphate buffer", "pH 1.2 HCl"}
    assert all(d["weibull_curve"] for d in room["dissolution"])
    assert next(v for v in room["substance"] if v["key"].startswith("substance.mw"))["status"] == "verified"
    # the room is kept until a file it is made from changes
    assert dataroom_api.room_of(DataRoomStore(ws)) is dataroom_api.room_of(DataRoomStore(ws))

    # the question card, confirmed: its checklist's missing item becomes a data request
    card = room["question"]
    assert not room["question_confirmed"]
    confirmed = c.put(f"{API}/question", headers=H, json={"card": card, "confirmed": True, "reason": "as drafted"})
    assert confirmed.status_code == 200 and confirmed.json()["data"]["question_confirmed"]
    assert any("Particle size" in r["title"] for r in confirmed.json()["data"]["requests"])

    # a decision: an option it does not offer is refused, another than the suggestion needs a reason
    decision = "population:EX-01"
    assert c.post(f"{API}/decisions/{decision}", headers=H, json={"chosen": "Martian_2099"}).status_code == 400
    assert c.post(f"{API}/decisions/{decision}", headers=H, json={"chosen": "European_ICRP_2002"}).status_code == 422
    assert c.post(f"{API}/decisions/nothing:here", headers=H, json={"chosen": "x"}).status_code == 404
    chosen = c.post(f"{API}/decisions/{decision}", headers=H, json={"chosen": "European_ICRP_2002", "reason": "sensitivity run"})
    assert chosen.status_code == 200, chosen.text
    made = next(d for d in chosen.json()["data"]["decisions"] if d["id"] == decision)
    assert (made["chosen"], made["by"], made["reason"]) == ("European_ICRP_2002", "Dev User", "sensitivity run")
    # a decision whose id holds a slash and spaces (a product's name) is reached by its encoded path
    release = next(d for d in made and chosen.json()["data"]["decisions"] if d["id"].startswith("release:Refamide"))
    path = release["id"].replace(" ", "%20")
    assert c.post(f"{API}/decisions/{path}", headers=H, json={"chosen": release["suggested"]}).status_code == 200

    # a value entered by a person fills the missing input and closes its request
    logp = next(r for r in chosen.json()["data"]["requests"] if r["input"] == "phys.logp")
    assert c.post(f"{API}/entered", headers=H, json={"key": "phys.logp", "label": "Lipophilicity", "value": 2.4,
                                                     "unit": "Log Units", "reason": ""}).status_code == 422
    entered = c.post(f"{API}/entered", headers=H, json={"key": "phys.logp", "label": "Lipophilicity", "value": 2.4,
                                                        "unit": "Log Units", "reason": "the client's e-mail of 2026-11-20"})
    room = entered.json()["data"]
    row = next(r for r in room["inputs"] if r["name"] == "phys.logp")
    assert (row["value"], row["status"], row["note"]) == (2.4, "entered", "the client's e-mail of 2026-11-20")
    assert not any(r["title"] == logp["title"] for r in room["requests"])

    # a data request's wording and status
    request = room["requests"][0]["id"]
    edited = c.patch(f"{API}/requests/{request}", headers=H, json={"wording": "Please send the actual sampling times.",
                                                                    "status": "not_needed"})
    got = next(r for r in edited.json()["data"]["requests"] if r["id"] == request)
    assert (got["wording"], got["status"]) == ("Please send the actual sampling times.", "not_needed")
    assert c.patch(f"{API}/requests/Z-99", headers=H, json={"status": "open"}).status_code == 404
    assert c.patch(f"{API}/requests/{request}", headers=H, json={}).status_code == 422

    actions = [r.event.action for r in store.audit("t1").records() if r.event.resource_type == "dataroom"]
    for action in ("dataroom.upload", "dataroom.run", "dataroom.question.confirm", "dataroom.decide", "dataroom.enter",
                   "dataroom.request"):
        assert action in actions


def test_send_to_the_model_waits_on_the_decisions_then_is_signed_once_with_the_step_up(setup):
    c, store, verifier = setup
    _read(c)
    room_store = DataRoomStore(Workspace(store, "t1", "p1"))
    seed(room_store, confirmed=True)
    plan = c.get(f"{API}/publication", headers=H).json()["data"]
    assert plan["blocked"] and plan["blocked"][0].startswith("decisions waiting") and plan["evidence"]
    refused = c.post(f"{API}/publish", headers=H, json={"reason": "inputs confirmed"})
    assert refused.status_code == 409 and refused.json()["detail"]["blocked"] == plan["blocked"]
    for d in c.get(API, headers=H).json()["data"]["decisions"]:
        room_store.decide(d["id"], d["suggested"], by="u1", reason="as suggested")
    plan = c.get(f"{API}/publication", headers=H).json()["data"]
    assert plan["blocked"] == [] and len(plan["datasets"]) == 2
    assert {"target": "phys.mw", "value": "412.5 g/mol"} in plan["evidence"]
    verifier.step_up = False
    unsigned = c.post(f"{API}/publish", headers=H, json={"reason": "inputs confirmed"})
    assert unsigned.status_code == 403 and unsigned.json()["detail"]["code"] == "STEP_UP_REQUIRED"
    verifier.step_up = True
    sent = c.post(f"{API}/publish", headers=H, json={"reason": "inputs confirmed"})
    assert sent.status_code == 200, sent.text
    data = sent.json()["data"]
    assert (data["evidence"], data["datasets"], data["skipped"]) == (len(plan["evidence"]), 2, 0)
    assert "Reviewed" in data["manifestation"] and data["signature_id"]
    again = c.post(f"{API}/publish", headers=H, json={"reason": "again"}).json()["data"]
    assert (again["evidence"], again["datasets"], again["skipped"]) == (0, 0, len(plan["evidence"]) + 2)


def test_the_source_viewer_draws_a_page_as_it_was_read_and_numbers_a_sheets_lines(setup):
    c, _store, _v = setup
    _read(c)
    files = {f["path"]: f for f in c.get(API, headers=H).json()["data"]["files"]}
    pdf = files[f"{FOLDER}/Clinical/EX-01 synopsis.pdf"]
    info = c.get(f"{API}/files/{pdf['sha256']}", headers=H).json()["data"]
    assert info["pages"] == [{"page": 1, "width": 612.0, "height": 792.0}] and info["parts"] == []
    page = c.get(f"{API}/files/{pdf['sha256']}/pages/1.png?scale=1", headers=H)
    assert page.status_code == 200 and page.headers["content-type"] == "image/png" and page.content[:4] == b"\x89PNG"
    assert int.from_bytes(page.content[16:20], "big") == 612
    assert c.get(f"{API}/files/{pdf['sha256']}/pages/2.png", headers=H).status_code == 404
    lines = c.get(f"{API}/files/{pdf['sha256']}/parts/p1", headers=H).json()["data"]["lines"]
    assert lines[2]["cells"][0]["text"].startswith("Treatments: A = Refamide") and lines[2]["cells"][0]["box"]
    sheet = files[f"{FOLDER}/In vitro/Solubility.tsv"]
    info = c.get(f"{API}/files/{sheet['sha256']}", headers=H).json()["data"]
    assert info["pages"] == [] and info["parts"] == ["sheet:Solubility"]
    assert c.get(f"{API}/files/{sheet['sha256']}/pages/1.png", headers=H).status_code == 404
    part = c.get(f"{API}/files/{sheet['sha256']}/parts/sheet:Solubility", headers=H).json()["data"]
    assert [c["text"] for c in part["lines"][1]["cells"]] == ["Water", "6.5", "0.21"]
    assert part["lines"][1]["cells"][2]["ref"] == "C2"
    assert c.get(f"{API}/files/{'0' * 64}", headers=H).status_code == 404
    assert c.get(f"{API}/files/{sheet['sha256']}/parts/sheet:Nothing", headers=H).status_code == 404
    assert len(delivery()) == 10


def test_an_existing_projects_client_files_open_in_the_data_room_once(setup):
    c, store, _v = setup
    from modeler_project.intake_files import open_delivery, record_arrival

    ws = Workspace(store, "t1", "p1")
    opened = open_delivery(ws, by="u1")
    files = delivery()
    for path in (f"{FOLDER}/In vitro/Solubility.tsv", f"{FOLDER}/Literature/Label.md"):
        record_arrival(ws, files[path], path.rsplit("/", 1)[-1], delivery=opened, by="u1")
    first = c.post(f"{API}/import-existing", headers=H).json()["data"]
    assert [u["name"] for u in first["added"]] == ["Solubility.tsv", "Label.md"] and len(first["uploads"]) == 2
    again = c.post(f"{API}/import-existing", headers=H).json()["data"]
    assert again["added"] == [] and len(again["uploads"]) == 2
    assert _run(c)["stages"][0]["note"] == "2 files, 0 scanned pages read by OCR"


def test_a_reader_reads_the_room_and_changes_nothing(setup):
    c, _store, verifier = setup
    verifier.roles = ("modeler-viewer",)
    assert c.get(API, headers=H).status_code == 200
    up = c.post(f"{API}/uploads", headers=H, files=[("files", ("delivery.zip", delivery_zip(), "application/zip"))])
    assert up.status_code == 403
    assert c.post(f"{API}/run", headers=H, json={}).status_code == 403


def test_every_dataroom_route_is_typed():
    # the router is not in the locked list of guarded routers ([response] in boundaries.toml); it is held to the same rule
    for route in dataroom_api.router.routes:
        assert isinstance(route, APIRoute)
        model = route.response_model
        assert route.path.endswith(".png") or (model is not None and hasattr(model, "model_fields")), route.path
