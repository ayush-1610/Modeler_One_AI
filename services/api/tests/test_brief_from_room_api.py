"""Plan 2026-11-24 §7, phase 4 (B4, B5): Start filled from the Data room through the API, on the synthetic delivery (the
made-up Exampleamide, `modeler_project.dataroom.synthetic`; never client data), its agents' answers written straight into
the store as A6-A8 would submit them. No AI model is called."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from modeler_api import project_api
from modeler_api.auth import get_verifier
from modeler_api.main import app
from modeler_project import FileProjectStore, Workspace
from modeler_project.dataroom import DataRoomStore, room_view
from modeler_project.dataroom.reading import read_uploads
from modeler_project.dataroom.synthetic import QUESTION, delivery_zip, seed

pytestmark = pytest.mark.req("T-41", "T-47")
H = {"Authorization": "Bearer t"}


class FakeVerifier:
    def verify(self, token):
        return {"sub": "u1", "name": "Dev User", "tenant_id": "t1", "realm_access": {"roles": ["modeler-curator"]},
                "projects": ["*"], "acr": "loa2", "auth_time": int(time.time())}


@pytest.fixture
def client(tmp_path, monkeypatch):
    store = FileProjectStore(tmp_path)
    monkeypatch.setenv("MODELER_READ_ROOT", str(tmp_path))
    monkeypatch.delenv("MODELER_LLM_PROVIDER", raising=False)
    from modeler_api.config import reload_settings

    reload_settings()
    app.dependency_overrides[get_verifier] = lambda: FakeVerifier()
    app.dependency_overrides[project_api.get_project_store] = lambda: store
    yield TestClient(app), store
    app.dependency_overrides.clear()
    reload_settings()


def _project(c: TestClient) -> str:
    started = c.post("/api/v1/projects:initiate", headers=H, data={"drug_name": "Exampleamide", "extract": "false",
                                                                    "context": "A reformulated tablet for a client."})
    assert started.status_code == 201, started.text
    return started.json()["data"]["project_id"]


def _room(store: FileProjectStore, pid: str, *, confirmed: bool) -> DataRoomStore:
    room = DataRoomStore(Workspace(store, "t1", pid))
    room.add_upload("delivery.zip", delivery_zip(), by="u1")
    read_uploads(room, use_ocr=False, workers=1)
    seed(room, confirmed=confirmed)
    return room


def test_start_is_filled_from_the_rooms_confirmed_card_and_advises_where_a_person_differs(client):
    c, store = client
    pid = _project(c)
    brief = f"/api/v1/projects/{pid}/brief"
    assert c.get(brief, headers=H).json()["data"]["start"]["room"] is None              # no Data room card: no button
    refused = c.post(f"{brief}:from-dataroom", headers=H)
    assert refused.status_code == 409 and "no question card" in refused.json()["detail"]

    room = _room(store, pid, confirmed=False)
    start = c.get(brief, headers=H).json()["data"]["start"]["room"]
    assert start["confirmed_card"] is False and start["question"] == QUESTION.question
    refused = c.post(f"{brief}:from-dataroom", headers=H)
    assert refused.status_code == 409 and "not confirmed" in refused.json()["detail"]

    room.set_question(QUESTION, by="u1", confirmed=True, reason="as read")
    for d in room_view(room).decisions:
        room.decide(d.id, d.suggested, by="u1", reason="as suggested")
    filled = c.post(f"{brief}:from-dataroom", headers=H)
    assert filled.status_code == 200, filled.text
    answer = filled.json()["data"]
    assert {"qoi.text", "qoi.context_of_use", "qoi.applications", "proj.agencies", "products[0].role",
            "scenarios[0].food_state", "scope.formulation_types"} <= set(answer["drafted"])
    assert answer["kept"] == [] and answer["advice"] == []
    view = c.get(brief, headers=H).json()["data"]
    record = view["brief"]["fields"]["qoi.text"]
    assert (record["status"], record["by"], record["value"]) == ("DRAFTED", "code:data-room", QUESTION.question)
    assert view["brief"]["fields"]["qoi.applications"]["value"] == ["APP-11 absorption and formulation",
                                                                    "APP-14 virtual bioequivalence"]
    assert view["start"]["room"] == {"confirmed_card": True, "question": QUESTION.question, "applications_chosen": True,
                                     "applications": ["APP-11 absorption and formulation", "APP-14 virtual bioequivalence"],
                                     "advice": []}
    # each draft waits on a person at Start, like the proposal's
    assert any(i["path"] == "qoi.text" and i["message"].endswith("confirm the draft, or change it")
               for i in view["start"]["issues"])

    # a person's own question: kept, and advised (never a block)
    edited = c.put(brief, headers=H, json={"changes": [{"path": "qoi.text", "status": "EDITED",
                                                        "value": "Predict exposure of the 50 mg tablet"}]})
    assert edited.status_code == 200, edited.text
    start = edited.json()["data"]["start"]
    (advice,) = start["room"]["advice"]
    assert advice["path"] == "qoi.text" and "the Data room's confirmed question card asks" in advice["message"]
    assert not any("Data room" in p for p in start["problems"])
    again = c.post(f"{brief}:from-dataroom", headers=H).json()["data"]
    assert again["drafted"] == [] and again["kept"] == ["qoi.text"] and len(again["advice"]) == 1
    assert c.get(brief, headers=H).json()["data"]["brief"]["fields"]["qoi.text"]["value"] == "Predict exposure of the 50 mg tablet"
