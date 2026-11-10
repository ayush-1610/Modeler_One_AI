"""The admin console's C and D (docs/plans/2026-11-10-admin-console.md): each agent's model chosen in the console, and
the providers' keys kept sealed under the master key, write-only, rotated (add, test, make active, retire). Only
`modeler-admin` opens them; every change needs a fresh step-up and is an audit event naming no secret."""

from __future__ import annotations

import base64
import json
import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from modeler_api import agent_jobs
from modeler_api import platform_settings as ps
from modeler_api.auth import get_verifier
from modeler_api.main import app

pytestmark = pytest.mark.req("T-05")

MASTER = base64.b64encode(b"m" * 32).decode()
SECRET = "sk-litellm-0123456789-abcd"
PEOPLE = {"owner": ("platform", ["modeler-admin"]), "ana": ("acme", ["modeler-viewer", "modeler-curator"])}


class _Verifier:
    """`Bearer owner` is the platform's owner with a fresh step-up; `Bearer owner-stale` without one."""

    def verify(self, token: str) -> dict:
        who = token.removesuffix("-stale")
        tenant, roles = PEOPLE[who]
        fresh = not token.endswith("-stale")
        return {"sub": who, "name": who.title(), "tenant_id": tenant, "realm_access": {"roles": roles}, "projects": [],
                "acr": "loa2" if fresh else "loa1", "auth_time": int(time.time()) if fresh else None}


@pytest.fixture
def client(tmp_path, api_settings):
    api_settings(read_root=str(tmp_path), master_key=MASTER)
    app.dependency_overrides[get_verifier] = _Verifier
    yield TestClient(app)
    app.dependency_overrides.clear()


def _as(who: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {who}"}


def _litellm(client: TestClient, key: str = SECRET) -> str:
    body = {"provider": "litellm", "label": "proxy on the server", "reason": "first key",
            "fields": {"base_url": "http://127.0.0.1:4000/v1", "key": key}}
    page = client.post("/api/v1/admin/keys", json=body, headers=_as("owner"))
    assert page.status_code == 200, page.text
    return page.json()["data"]["keys"][0]["id"]


def _audit(tmp_path) -> list[dict]:
    lines = (tmp_path / "platform" / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line)["event"] for line in lines]


def test_keys_are_sealed_shown_by_their_last_four_characters_and_never_answered(client, tmp_path):
    key_id = _litellm(client)
    stored = (tmp_path / "_platform" / "keys.json").read_text(encoding="utf-8")
    assert SECRET not in stored and "sealed" in stored
    page = client.get("/api/v1/admin/keys", headers=_as("owner"))
    assert SECRET not in page.text
    (key,) = page.json()["data"]["keys"]
    assert (key["id"], key["state"], key["last4"], key["plain"]) == (key_id, "new", {"key": "abcd"},
                                                                     {"base_url": "http://127.0.0.1:4000/v1"})
    assert page.json()["data"]["master_key"] is True
    # the audit trail names the key by its last 4 characters, never its secret
    (event,) = [e for e in _audit(tmp_path) if e["action"] == "admin.key.add"]
    assert event["after"]["last4"] == {"key": "abcd"} and event["reason"] == "first key" and SECRET not in json.dumps(event)
    # the platform's folder is not a company
    assert [c["tenant_id"] for c in client.get("/api/v1/admin/overview", headers=_as("owner")).json()["data"]["companies"]] \
        == ["platform"]


def test_rotation_a_new_key_made_active_retires_the_old_one_and_an_old_active_key_is_due(client, tmp_path):
    first = _litellm(client)
    assert client.post(f"/api/v1/admin/keys/{first}:activate", json={"reason": "in use"}, headers=_as("owner")).status_code == 200
    second = _litellm(client, "sk-litellm-rotated-wxyz")
    page = client.post(f"/api/v1/admin/keys/{second}:activate", json={"reason": "rotation"}, headers=_as("owner")).json()
    states = {k["id"]: k["state"] for k in page["data"]["keys"]}
    assert states == {first: "retired", second: "active"}
    again = client.post(f"/api/v1/admin/keys/{first}:activate", json={"reason": "back"}, headers=_as("owner"))
    assert again.status_code == 409 and "only a new key" in again.json()["detail"]
    store = ps.KeyStore(str(tmp_path), MASTER)
    later = datetime.now(UTC) + timedelta(days=ps.ROTATE_AFTER_DAYS)
    (active,) = [k for k in store.view(later) if k["state"] == "active"]
    assert active["due"] is True and active["active_days"] >= ps.ROTATE_AFTER_DAYS
    assert client.post(f"/api/v1/admin/keys/{second}:retire", json={"reason": "leaked"},
                       headers=_as("owner")).json()["data"]["keys"][0]["state"] == "retired"
    assert [e["action"] for e in _audit(tmp_path)].count("admin.key.activate") == 2


def test_an_agent_runs_on_the_model_and_active_key_the_console_sets_without_a_restart(client, tmp_path):
    page = client.get("/api/v1/admin/agents", headers=_as("owner")).json()["data"]
    assert [a["provider"] for a in page["agents"]] == ["environment"] * 5      # as the server's environment says
    off = client.put("/api/v1/admin/agents/A1", json={"provider": "off", "reason": "A1 paused"}, headers=_as("owner"))
    assert off.json()["data"]["agents"][0]["runs_on"] == {"enabled": False, "problem": "off in the admin console (A1 paused)"}
    assert agent_jobs.chat_model("A1") == (None, None)
    on = client.put("/api/v1/admin/agents/A1", json={"provider": "litellm", "model": "qwen-coder", "reason": "back on"},
                    headers=_as("owner")).json()["data"]
    assert "no active key" in on["agents"][0]["runs_on"]["problem"]
    key_id = _litellm(client)
    client.post(f"/api/v1/admin/keys/{key_id}:activate", json={"reason": "in use"}, headers=_as("owner"))
    model, problem = agent_jobs.chat_model("A1")
    assert problem is None and (model.provider, model.model, model.base_url) == ("litellm", "qwen-coder",
                                                                                 "http://127.0.0.1:4000/v1")
    assert agent_jobs.chat_model("A2")[0] is None        # A2 still follows the environment (no provider set in tests)
    history = client.get("/api/v1/admin/agents", headers=_as("owner")).json()["data"]["history"]
    assert [(h["agent"], h["provider"], h["reason"]) for h in history] == [("A1", "litellm", "back on"), ("A1", "off", "A1 paused")]
    assert client.put("/api/v1/admin/agents/A9", json={"provider": "off", "reason": "x"},
                      headers=_as("owner")).status_code == 409


def test_a_key_test_says_whether_it_answers_and_is_kept_with_the_key(client, monkeypatch):
    key_id = _litellm(client)
    seen: list[tuple[str, dict]] = []
    monkeypatch.setattr(agent_jobs, "test_key", lambda provider, fields: seen.append((provider, fields)) or (True, "answers"))
    (key,) = client.post(f"/api/v1/admin/keys/{key_id}:test", headers=_as("owner")).json()["data"]["keys"]
    assert seen == [("litellm", {"base_url": "http://127.0.0.1:4000/v1", "key": SECRET})]     # opened for the test only
    assert (key["test_ok"], key["test_message"]) == (True, "answers") and key["tested_at"]


def test_only_the_owner_changes_settings_and_only_with_a_fresh_step_up(client):
    for method, path, body in (("get", "/api/v1/admin/agents", None), ("get", "/api/v1/admin/keys", None),
                               ("put", "/api/v1/admin/agents/A1", {"provider": "off", "reason": "x"})):
        assert client.request(method, path, json=body, headers=_as("ana")).status_code == 403
    stale = client.put("/api/v1/admin/agents/A1", json={"provider": "off", "reason": "x"}, headers=_as("owner-stale"))
    assert stale.status_code == 403 and stale.json()["detail"]["code"] == "STEP_UP_REQUIRED"
    added = client.post("/api/v1/admin/keys", json={"provider": "litellm", "reason": "x", "fields": {"base_url": "h", "key": "k"}},
                        headers=_as("owner-stale"))
    assert added.status_code == 403


def test_without_a_master_key_nothing_is_stored_and_a_wrong_one_opens_nothing(tmp_path, api_settings):
    with pytest.raises(ps.SettingsError, match="no master key"):
        ps.KeyStore(str(tmp_path), "").add("litellm", "", {"base_url": "h", "key": "k"}, by="owner")
    record = ps.KeyStore(str(tmp_path), MASTER).add("bedrock", "", {"aws_region": "ap-south-1", "api_key": "bedrock-key-1234"},
                                                    by="owner")
    other = base64.b64encode(b"x" * 32).decode()
    with pytest.raises(ps.SettingsError, match="cannot be opened"):
        ps.KeyStore(str(tmp_path), other).fields(record["id"])
    with pytest.raises(ps.SettingsError, match="Bedrock API key, or an AWS access key"):
        ps.KeyStore(str(tmp_path), MASTER).add("bedrock", "", {"aws_region": "ap-south-1", "aws_access_key": "AKIA"}, by="owner")


def test_a_refused_key_is_never_echoed_back(client):
    # no reason: refused by the handler, not by the validator (whose 422 would repeat the body and its secret)
    refused = client.post("/api/v1/admin/keys", json={"provider": "litellm", "fields": {"base_url": "h", "key": SECRET}},
                          headers=_as("owner"))
    assert refused.status_code == 409 and SECRET not in refused.text
    wrong = client.post("/api/v1/admin/keys", json={"provider": "nope", "reason": "x", "fields": {"key": SECRET}},
                        headers=_as("owner"))
    assert wrong.status_code == 409 and SECRET not in wrong.text
