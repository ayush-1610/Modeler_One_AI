"""T-47: the Data room's runs that pause and resume (plan 2026-11-24 §4) and the hard cap for paid models (§2.4; the
owner's decision D3), through the API: a paused run read with why and where; Resume now for the roles that start a run;
the clock resuming a due run, and every paused run picked up when the API starts; the estimate before a paid run; a paid
run paused at the cap and resumed when the administrator raises it; a model's, a key's or a permission's change resuming
the runs it may unblock. Fake models only, never a real one; the delivery is the made-up Exampleamide."""

from __future__ import annotations

import base64
import json
import re
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from modeler_agents.llm import ChatResult, ToolCall
from modeler_api import agent_jobs, dataroom_runs
from modeler_api import platform_settings as ps
from modeler_api.auth import get_verifier
from modeler_api.main import app
from modeler_project import FileProjectStore, Workspace
from modeler_project.dataroom import DataRoomStore
from modeler_project.dataroom.synthetic import delivery_zip

pytestmark = pytest.mark.req("T-47")
MASTER = base64.b64encode(b"m" * 32).decode()
API = "/api/v1/projects/p1/dataroom"
STAGES = ("read", "question", "triage", "extract", "check", "write")
PEOPLE = {"t": ("u1", "t1", ["modeler-curator"]), "viewer": ("u2", "t1", ["modeler-viewer"]),
          "owner": ("owner", "platform", ["modeler-admin"])}


class _Verifier:
    def verify(self, token: str) -> dict:
        sub, tenant, roles = PEOPLE[token]
        return {"sub": sub, "name": sub.title(), "tenant_id": tenant, "realm_access": {"roles": roles}, "projects": ["*"],
                "acr": "loa2", "auth_time": int(time.time())}


def _as(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client(tmp_path, api_settings, monkeypatch):
    monkeypatch.delenv("MODELER_LLM_PROVIDER", raising=False)
    api_settings(read_root=str(tmp_path), master_key=MASTER)
    app.dependency_overrides[get_verifier] = _Verifier
    yield TestClient(app)
    app.dependency_overrides.clear()


def _room(root, tenant: str = "t1", project: str = "p1") -> DataRoomStore:
    return DataRoomStore(Workspace(FileProjectStore(root), tenant, project))


def _paused(room: DataRoomStore, reason: str, resume_at: datetime | None = None) -> None:
    """A run's record as a run on a model leaves it when it pauses at extraction, 3 of 8 files done."""
    states = {"read": "done", "question": "done", "triage": "done", "extract": "paused", "check": "waiting", "write": "waiting"}
    room.set_run({"run_id": "r1", "state": "paused", "started_at": "2026-11-24T10:00:00+00:00", "finished_at": None,
                  "actor": "u1", "error": "", "agents": {}, "auto_resumes": 0, "resumes": [],
                  "params": {"stages": list(STAGES), "redo": [], "files": [], "focus_chars": None, "use_ocr": False},
                  "stages": [{"id": s, "label": s, "agent": "", "state": states[s], "done": 3 if s == "extract" else 0,
                              "total": 8 if s == "extract" else 0, "note": ""} for s in STAGES],
                  "pause": {"reason": reason, "said": "Nemotron Ultra could not answer (its service did not answer).",
                            "detail": "nvidia unavailable: HTTP 503", "stage": "extract", "where": "extraction",
                            "per_file": True, "done": 3, "total": 8, "at": "2026-11-24T10:05:00+00:00",
                            "resume_at": resume_at.isoformat(timespec="seconds") if resume_at else None}})


def _done(room: DataRoomStore, timeout: float = 30.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        doc = room.run()
        if doc.get("state") == "done":
            return doc
        time.sleep(0.05)
    raise AssertionError(f"the run did not finish: {room.run()}")


def test_a_paused_run_is_read_with_why_and_where_and_an_editor_resumes_it_now(client, tmp_path):
    room = _room(tmp_path)
    assert client.post(f"{API}/run:resume", headers=_as("t")).status_code == 409          # nothing paused
    _paused(room, "provider_unavailable", datetime.now(UTC) + timedelta(minutes=10))
    run = client.get(f"{API}/run", headers=_as("viewer")).json()["data"]
    assert run["state"] == "paused" and run["error"] == ""
    assert {k: run["pause"][k] for k in ("reason", "stage", "where", "per_file", "done", "total")} == {
        "reason": "provider_unavailable", "stage": "extract", "where": "extraction", "per_file": True, "done": 3, "total": 8}
    assert run["pause"]["resume_at"] and next(s for s in run["stages"] if s["id"] == "extract")["state"] == "paused"
    assert client.post(f"{API}/run:resume", headers=_as("viewer")).status_code == 403     # the roles that start a run
    resumed = client.post(f"{API}/run:resume", headers=_as("t"))
    assert resumed.status_code == 202 and resumed.json()["data"]["state"] == "running"
    doc = _done(room)                     # agents off here: the stages left skip, each waiting for a model
    assert {s["id"]: s["state"] for s in doc["stages"]}["extract"] == "skipped" and doc["resumes"][0]["by"] == "u1"
    events = [r.event for r in FileProjectStore(tmp_path).audit("t1").records() if r.event.action == "dataroom.run.resume"]
    assert len(events) == 1 and events[0].after["how"] == "now" and events[0].after["reason"] == "provider_unavailable"
    assert client.post(f"{API}/run:resume", headers=_as("t")).status_code == 409


def test_the_clock_resumes_a_due_run_and_the_api_picks_up_every_paused_run_when_it_starts(client, tmp_path, monkeypatch):
    monkeypatch.setattr(dataroom_runs, "SLACK_S", 0.05)
    store = FileProjectStore(tmp_path)
    due, later, waits = _room(tmp_path, "t1", "p1"), _room(tmp_path, "t1", "p2"), _room(tmp_path, "t2", "p3")
    _paused(due, "provider_unavailable", datetime.now(UTC) - timedelta(seconds=1))
    _paused(later, "provider_unavailable", datetime.now(UTC) + timedelta(days=1))      # its timer never fires in a test
    _paused(waits, "budget_cap")
    assert not dataroom_runs.resume(store, "t1", "p2", by=dataroom_runs.CLOCK, how="auto")   # not due yet
    assert not dataroom_runs.resume(store, "t2", "p3", by=dataroom_runs.CLOCK, how="auto")   # the cap: never the clock
    assert {(t, p) for t, p, _d in dataroom_runs.paused_runs(store)} == {("t1", "p1"), ("t1", "p2"), ("t2", "p3")}
    assert dataroom_runs.pick_up(store) == 2                                       # a timer for each run with a time
    doc = _done(due)
    assert doc["resumes"][0]["how"] == "auto" and doc["resumes"][0]["by"] == dataroom_runs.CLOCK
    assert later.run()["state"] == "paused" and waits.run()["state"] == "paused"


def test_the_estimate_says_what_a_paid_run_would_cost_and_nothing_for_free_models(client, tmp_path, monkeypatch):
    up = client.post(f"{API}/uploads", headers=_as("t"), files=[("files", ("delivery.zip", delivery_zip(), "application/zip"))])
    assert up.status_code == 201
    free = client.get(f"{API}/run/estimate", headers=_as("viewer")).json()["data"]
    assert not free["paid"] and free["usd"] == 0.0 and free["files"] == 10 and free["run_cap_usd"] == 10.0

    class _Opus:
        provider, model = "bedrock", "anthropic.claude-opus-5-5"

    monkeypatch.setattr(agent_jobs, "project_model", lambda agent, ws: (_Opus(), None) if agent == "A8" else (None, None))
    paid = client.get(f"{API}/run/estimate", headers=_as("t")).json()["data"]
    assert paid["paid"] and 0 < paid["usd_low"] <= paid["usd"] <= paid["usd_high"]
    assert [a["agent"] for a in paid["agents"] if a["paid"]] == ["A8"] and paid["month_cap_usd"] == 90.0
    assert "characters / 4" in paid["basis"]


_FILE = re.compile(r"File: (.+?)(?: \(|\n|$)")


class _PaidFake:
    """Claude Opus 5.5 on Bedrock, faked: each call costs $1 (250,000 input tokens at $4 a million); it answers each step
    through its submit tool and says DONE after "saved"."""

    provider, model = "bedrock", "anthropic.claude-opus-5-5"

    def __init__(self):
        self.calls = 0

    def complete(self, messages, tools):
        self.calls += 1
        usage = {"input_tokens": 250_000, "output_tokens": 0}
        last = messages[-1]
        if last["role"] == "tool" and str(last["content"]).startswith("saved") and "problems" not in last["content"]:
            return ChatResult(content="DONE", tool_calls=(), finish_reason="stop", usage=usage, model=self.model)
        submit = next(t["function"]["name"] for t in tools if t["function"]["name"].startswith("submit_"))
        found = _FILE.search(messages[1]["content"])
        file = found.group(1) if found else ""
        answer = {"submit_question": {"question": "Is the reformulated tablet bioequivalent?"},
                  "submit_triage": {"path": file, "purpose": "used", "reason": "data"},
                  "submit_extraction": {"file": file}, "submit_review": {"tables": []},
                  "submit_writing": {"findings": {}, "requests": {}}}[submit]
        return ChatResult(content="", tool_calls=(ToolCall(id=f"c{self.calls}", name=submit, arguments=answer,
                                                           raw_arguments=json.dumps(answer)),),
                          finish_reason="tool_calls", usage=usage, model=self.model)


def test_a_paid_run_pauses_at_the_cap_and_raising_the_cap_resumes_it(client, tmp_path, monkeypatch):
    fake = _PaidFake()
    monkeypatch.setattr(agent_jobs, "project_model", lambda agent, ws: (fake, None))
    page = client.get("/api/v1/admin/limits", headers=_as("owner")).json()["data"]["paid"]
    assert (page["run_usd"], page["month_usd"], page["set_by"], page["providers"]) == (10.0, 90.0, None, ["bedrock", "anthropic"])
    assert client.put("/api/v1/admin/limits/paid", json={"run_usd": 100, "month_usd": 90, "reason": "x"},
                      headers=_as("owner")).status_code == 409            # a run's cap above the month's
    assert client.put("/api/v1/admin/limits/paid", json={"run_usd": 2.5, "month_usd": 90, "reason": "x"},
                      headers=_as("t")).status_code == 403                # the administrator's alone
    set_ = client.put("/api/v1/admin/limits/paid", json={"run_usd": 2.5, "month_usd": 90, "reason": "a test's cap"},
                      headers=_as("owner"))
    assert set_.status_code == 200 and set_.json()["data"]["paid"]["run_usd"] == 2.5

    up = client.post(f"{API}/uploads", headers=_as("t"), files=[("files", ("delivery.zip", delivery_zip(), "application/zip"))])
    assert up.status_code == 201
    assert client.post(f"{API}/run", headers=_as("t"), json={}).status_code == 202
    room = _room(tmp_path)
    deadline = time.monotonic() + 60
    while room.run().get("state") in ("running", None) and time.monotonic() < deadline:
        time.sleep(0.05)
    run = client.get(f"{API}/run", headers=_as("t")).json()["data"]
    assert run["state"] == "paused" and run["pause"]["reason"] == "budget_cap" and run["pause"]["resume_at"] is None
    assert run["pause"]["said"] == "The run reached its $2.5 limit for paid models (Admin → Limits)."
    rows = ps.PaidSpend(str(tmp_path)).rows()
    assert len(rows) == 3 == fake.calls and {(r["tenant_id"], r["project_id"]) for r in rows} == {("t1", "p1")}
    assert {r["run_id"] for r in rows} == {room.run()["run_id"]}
    limits = client.get("/api/v1/admin/limits", headers=_as("owner")).json()["data"]["paid"]
    assert (limits["paused_runs"], limits["month_spent_usd"]) == (1, 3.0)

    raised = client.put("/api/v1/admin/limits/paid", json={"run_usd": 60, "month_usd": 90, "reason": "the demo needs more"},
                        headers=_as("owner"))
    assert raised.status_code == 200
    doc = _done(room, timeout=60)
    assert doc["resumes"][0]["by"] == "owner" and fake.calls > 3
    events = [r.event for r in FileProjectStore(tmp_path).audit("platform").records() if r.event.action == "admin.paid_cap.set"]
    assert [(e.before["run_usd"], e.after["run_usd"], e.reason) for e in events][-1] == (2.5, 60.0, "the demo needs more")


def test_the_months_paid_spend_counts_every_agents_paid_calls(client, tmp_path, monkeypatch):
    # A2 on a paid model is metered on the same ledger (no cap: it only warns); its spend counts towards the month's cap
    # a Data room run stops at
    researcher = agent_jobs._metered(_PaidFake(), "A2", str(tmp_path))
    for _ in range(2):
        researcher.complete([{"role": "system", "content": ""}, {"role": "user", "content": "x"}],
                            [{"type": "function", "function": {"name": "submit_writing"}}])
    rows = ps.PaidSpend(str(tmp_path)).rows()
    assert [r["agent"] for r in rows] == ["A2", "A2"] and ps.PaidSpend(str(tmp_path)).month_usd() == 2.0
    assert client.put("/api/v1/admin/limits/paid", json={"run_usd": 1, "month_usd": 2, "reason": "a test's month"},
                      headers=_as("owner")).status_code == 200
    extractor = _PaidFake()
    monkeypatch.setattr(agent_jobs, "project_model", lambda agent, ws: (extractor, None))
    up = client.post(f"{API}/uploads", headers=_as("t"), files=[("files", ("delivery.zip", delivery_zip(), "application/zip"))])
    assert up.status_code == 201
    assert client.post(f"{API}/run", headers=_as("t"), json={}).status_code == 202
    room = _room(tmp_path)
    deadline = time.monotonic() + 60
    while room.run().get("state") in ("running", None) and time.monotonic() < deadline:
        time.sleep(0.05)
    pause = room.run()["pause"]
    assert pause["reason"] == "budget_cap" and pause["said"] == "Paid models reached this month's $2 limit (Admin → Limits)."
    assert extractor.calls == 0


def test_a_change_of_a_model_a_key_or_a_permission_resumes_the_runs_it_may_unblock(client, tmp_path):
    rate, cap, nokey = _room(tmp_path, "t1", "p1"), _room(tmp_path, "t1", "p2"), _room(tmp_path, "t2", "p3")
    _paused(rate, "provider_unavailable", datetime.now(UTC) + timedelta(days=1))
    _paused(cap, "budget_cap")
    _paused(nokey, "no_model")
    # a key added: the provider that did not answer and the model without a key go on; the cap does not move
    added = client.post("/api/v1/admin/keys", headers=_as("owner"), json={
        "provider": "groq", "reason": "a new key", "fields": {"api_key": "gsk-test"}})
    assert added.status_code == 200, added.text
    _done(rate)
    _done(nokey)
    assert cap.run()["state"] == "paused"
    # a model switched: every paused run goes on (a paid model for a free one included)
    switched = client.put("/api/v1/admin/agents/A8", headers=_as("owner"), json={"provider": "off", "reason": "free for now"})
    assert switched.status_code == 200, switched.text
    _done(cap)
    # the client's permission recorded: the project's run that no allowed model could do goes on
    _paused(rate, "no_model")
    page = client.put("/api/v1/projects/p1/data-permissions", headers=_as("t"), json={
        "in_house_only": False, "reason": "the client's letter", "services": {"groq": {"reference": "L-1"}}})
    assert page.status_code == 200, page.text
    _done(rate)
