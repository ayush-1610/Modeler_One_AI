"""The admin console's C and D (docs/plans/2026-11-10-admin-console.md): each agent's model chosen in the console, and
the providers' keys kept sealed under the master key, write-only, rotated (add, test, make active, retire). Only
`modeler-admin` opens them; every change needs a fresh step-up and is an audit event naming no secret."""

from __future__ import annotations

import base64
import json
import logging
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
FAKE_BEDROCK = "b" * 16                   # a made-up key, built so the secret scan does not read it as one
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
    assert [a["provider"] for a in page["agents"]] == ["environment"] * len(ps.AGENTS)   # as the server's environment says
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
    assert client.put("/api/v1/admin/agents/A11", json={"provider": "off", "reason": "x"},
                      headers=_as("owner")).status_code == 409


def test_a_projects_pages_say_why_the_agents_are_off_in_words_and_the_admin_console_names_the_setting(client, monkeypatch, caplog):
    """Final review round 7: a hover title on Client files read "agents are off (MODELER_LLM_PROVIDER not set)". A
    project's pages say it in words; the admin console still names the setting (and the server's log does)."""
    monkeypatch.delenv("MODELER_LLM_PROVIDER", raising=False)
    page = agent_jobs.agents_status("A4")
    assert page == {"enabled": False, "problem": agent_jobs.AGENTS_OFF} and "MODELER_" not in page["problem"]
    assert "MODELER_LLM_PROVIDER" in agent_jobs.agents_status("A4", admin=True)["problem"]
    with caplog.at_level(logging.INFO, logger="modeler_api.agent_jobs"):
        agent_jobs.log_agents_status()                       # at the server's start, by the setting to change
    assert "MODELER_LLM_PROVIDER not set" in caplog.text
    monkeypatch.setattr(agent_jobs, "chat_model", lambda agent=None: (None, "MODELER_LLM_PROVIDER=bedrock needs BEDROCK_REGION"))
    assert agent_jobs.agents_status("A4")["problem"] == agent_jobs.AGENTS_MISCONFIGURED
    assert "BEDROCK_REGION" in agent_jobs.agents_status("A4", admin=True)["problem"]


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
    bedrock = {"aws_region": "ap-south-1", "api_key": FAKE_BEDROCK}
    record = ps.KeyStore(str(tmp_path), MASTER).add("bedrock", "", bedrock, by="owner")
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


def test_an_agent_on_claude_on_bedrock_takes_its_model_effort_fallback_and_the_active_bedrock_key(client):
    fields = {"aws_region": "ap-south-1", "api_key": FAKE_BEDROCK}
    page = client.post("/api/v1/admin/keys", json={"provider": "bedrock", "label": "AWS", "fields": fields, "reason": "Claude"},
                       headers=_as("owner")).json()["data"]
    key_id = page["keys"][0]["id"]
    client.post(f"/api/v1/admin/keys/{key_id}:activate", json={"reason": "in use"}, headers=_as("owner"))
    body = {"provider": "bedrock", "model": "anthropic.claude-opus-5-5", "effort": "high",
            "fallback": "anthropic.claude-sonnet-5-5", "reason": "A1 on Claude"}
    row = client.put("/api/v1/admin/agents/A1", json=body, headers=_as("owner")).json()["data"]["agents"][0]
    assert (row["provider"], row["effort"], row["fallback"]) == ("bedrock", "high", "anthropic.claude-sonnet-5-5")
    assert row["runs_on"] == {"enabled": True, "provider": "bedrock", "model": "anthropic.claude-opus-5-5", "then": []}
    model, problem = agent_jobs.chat_model("A1")
    assert problem is None and (model.effort, model.fallback) == ("high", "anthropic.claude-sonnet-5-5")
    page = client.get("/api/v1/admin/agents", headers=_as("owner")).json()["data"]
    assert "xhigh" in page["efforts"] and "anthropic.claude-haiku-5-5" in page["claude_models"]
    for wrong, why in (({"effort": "extreme"}, "effort is one of"),
                       ({"fallback": "anthropic.claude-opus-5-5"}, "must differ from the model")):
        refused = client.put("/api/v1/admin/agents/A1", json=body | wrong, headers=_as("owner"))
        assert refused.status_code == 409 and why in refused.json()["detail"]


def test_every_agent_switches_in_one_step_and_back_and_a_provider_without_an_active_key_is_refused(client, tmp_path):
    """The owner, 2026-11-11: switch between Claude on Bedrock and the in-house model easily, for when one is lost."""
    claude = {"provider": "bedrock", "model": "anthropic.claude-opus-5-5", "effort": "medium",
              "fallback": "anthropic.claude-sonnet-5-5", "reason": "Claude for every agent"}
    refused = client.put("/api/v1/admin/agents", json=claude, headers=_as("owner"))
    assert refused.status_code == 409 and "has no active key" in refused.json()["detail"]
    assert ps.AgentSettings(str(tmp_path)).doc()["current"] == {}                          # nothing changed
    stale = client.put("/api/v1/admin/agents", json=claude, headers=_as("owner-stale"))
    assert stale.status_code == 403 and stale.json()["detail"]["code"] == "STEP_UP_REQUIRED"

    fields = {"aws_region": "ap-south-1", "api_key": FAKE_BEDROCK}
    key_id = client.post("/api/v1/admin/keys", json={"provider": "bedrock", "fields": fields, "reason": "Claude"},
                         headers=_as("owner")).json()["data"]["keys"][0]["id"]
    client.post(f"/api/v1/admin/keys/{key_id}:activate", json={"reason": "in use"}, headers=_as("owner"))
    page = client.put("/api/v1/admin/agents", json=claude, headers=_as("owner")).json()["data"]
    assert {(a["provider"], a["model"], a["effort"]) for a in page["agents"]} == {("bedrock", "anthropic.claude-opus-5-5", "medium")}
    assert all(agent_jobs.chat_model(a)[0].model == "anthropic.claude-opus-5-5" for a in ps.AGENTS)

    # Bedrock lost: every agent back on the server's own (in-house) model in one step, no key needed for that
    back = client.put("/api/v1/admin/agents", json={"provider": "environment", "reason": "Bedrock access lost"},
                      headers=_as("owner")).json()["data"]
    assert [a["provider"] for a in back["agents"]] == ["environment"] * len(ps.AGENTS)
    events = [e for e in _audit(tmp_path) if e["action"] == "admin.agent.set"]
    assert len(events) == 2 * len(ps.AGENTS) and {e["resource_id"] for e in events} == set(ps.AGENTS)
    assert events[-1]["after"] == {"provider": "environment", "model": "", "effort": "", "fallback": "", "every_agent": True}
    assert events[-1]["before"]["provider"] == "bedrock" and events[-1]["reason"] == "Bedrock access lost"
    assert client.put("/api/v1/admin/agents", json={"provider": "off", "reason": "x"}, headers=_as("ana")).status_code == 403


FAKE_GROQ = "g" * 20                      # a made-up key, built so the secret scan does not read it as one
GPT_OSS = {"provider": "groq", "model": "openai/gpt-oss-120b", "effort": "medium", "reason": "one-click switch"}


def test_the_data_rooms_five_agents_are_switched_each_on_its_own_by_their_run_names():
    """Plan 2026-11-21 v2 §9: A6 … A10, so a run named "A10-…" takes A10's setting, not A1's."""
    assert list(ps.AGENTS)[5:] == ["A6", "A7", "A8", "A9", "A10"]
    assert ps.AGENTS["A10"] == "A10 · Data room: writes findings and requests"
    assert [ps.agent_of(name) for name in ("A10-writer", "A1-proposal", "A9", "A6-question", "A11-x", "B1-y")] == [
        "A10", "A1", "A9", "A6", None, None]


def test_gpt_oss_on_groqcloud_takes_one_key_its_effort_and_runs_an_agent_from_the_console(client, tmp_path):
    keys = client.get("/api/v1/admin/keys", headers=_as("owner")).json()["data"]
    (groq,) = [p for p in keys["providers"] if p["id"] == "groq"]
    assert (groq["label"], groq["fields"]) == ("gpt-oss-120b on GroqCloud",
                                               [{"name": "api_key", "label": "GroqCloud API key", "secret": True, "required": True}])
    missing = client.post("/api/v1/admin/keys", json={"provider": "groq", "reason": "x", "fields": {}}, headers=_as("owner"))
    assert missing.status_code == 409 and "GroqCloud API key" in missing.json()["detail"]
    key_id = client.post("/api/v1/admin/keys", json={"provider": "groq", "fields": {"api_key": FAKE_GROQ}, "reason": "Groq"},
                         headers=_as("owner")).json()["data"]["keys"][0]["id"]
    assert FAKE_GROQ not in (tmp_path / "_platform" / "keys.json").read_text(encoding="utf-8")
    client.post(f"/api/v1/admin/keys/{key_id}:activate", json={"reason": "in use"}, headers=_as("owner"))

    row = next(a for a in client.put("/api/v1/admin/agents/A8", json=GPT_OSS, headers=_as("owner")).json()["data"]["agents"]
               if a["agent"] == "A8")
    assert (row["provider_label"], row["effort"], row["fallback"]) == ("gpt-oss-120b on GroqCloud", "medium", "")
    assert row["runs_on"] == {"enabled": True, "provider": "groq", "model": "openai/gpt-oss-120b", "then": []}
    assert ps.model_env(str(tmp_path), MASTER, "A8") == {"MODELER_LLM_PROVIDER": "groq", "GROQ_API_KEY": FAKE_GROQ,
                                                         "MODELER_LLM_MODEL": "openai/gpt-oss-120b", "MODELER_LLM_EFFORT": "medium"}
    model, problem = agent_jobs.chat_model("A8")
    assert problem is None and (model.base_url, model.reasoning_effort) == ("https://api.groq.com/openai/v1", "medium")
    # GroqCloud's efforts are its own (Claude's xhigh and max are not), and a fallback is Claude's alone
    for effort in ("xhigh", "max", "extreme"):
        refused = client.put("/api/v1/admin/agents/A8", json=GPT_OSS | {"effort": effort}, headers=_as("owner"))
        assert refused.status_code == 409 and "effort on GroqCloud is one of low, medium, high" in refused.json()["detail"]
    page = client.put("/api/v1/admin/agents/A8", json=GPT_OSS | {"effort": "", "fallback": "x", "reason": "its default"},
                      headers=_as("owner")).json()["data"]
    row = next(a for a in page["agents"] if a["agent"] == "A8")
    assert (row["effort"], row["fallback"], row["choice"]) == ("", "", "gpt-oss-120b")
    assert ps.model_env(str(tmp_path), MASTER, "A8")["MODELER_LLM_EFFORT"] == ""
    assert page["groq_efforts"] == ["low", "medium", "high"] and "xhigh" in page["efforts"]


def test_each_agent_row_offers_four_one_click_models_the_active_one_marked_and_a_keyless_one_said(client, tmp_path):
    page = client.get("/api/v1/admin/agents", headers=_as("owner")).json()["data"]
    choices = {c["id"]: c for c in page["choices"]}
    assert [c["label"] for c in page["choices"]] == ["Qwen Coder", "Claude", "gpt-oss-120b", "Nemotron Ultra"]
    assert {i: (c["provider"], c["model"], c["effort"]) for i, c in choices.items()} == {
        "qwen-coder": ("litellm", "qwen-coder", ""), "claude": ("bedrock", "anthropic.claude-opus-5-5", ""),
        "gpt-oss-120b": ("groq", "openai/gpt-oss-120b", "medium"),
        "nemotron-ultra": ("nvidia", "nvidia/nemotron-3-ultra-550b-a55b", "")}
    assert all(c["tools"] for c in page["choices"]) and [i for i, c in choices.items() if c["reads_scans"]] == ["claude"]
    assert not any(c["has_active_key"] for c in page["choices"])          # no key yet: each button says "Add a key"
    assert {a["choice"] for a in page["agents"]} == {None}

    key_id = client.post("/api/v1/admin/keys", json={"provider": "groq", "fields": {"api_key": FAKE_GROQ}, "reason": "Groq"},
                         headers=_as("owner")).json()["data"]["keys"][0]["id"]
    client.post(f"/api/v1/admin/keys/{key_id}:activate", json={"reason": "in use"}, headers=_as("owner"))
    page = client.put("/api/v1/admin/agents/A7", json=GPT_OSS, headers=_as("owner")).json()["data"]
    assert {c["id"]: c["has_active_key"] for c in page["choices"]} == {"qwen-coder": False, "claude": False, "gpt-oss-120b": True,
                                                                   "nemotron-ultra": False}
    rows = {a["agent"]: a for a in page["agents"]}
    assert (rows["A7"]["choice"], rows["A7"]["set_by"], rows["A7"]["reason"]) == ("gpt-oss-120b", "owner", "one-click switch")
    assert {a: r["choice"] for a, r in rows.items() if a != "A7"} == dict.fromkeys(set(ps.AGENTS) - {"A7"})
    (event,) = [e for e in _audit(tmp_path) if e["action"] == "admin.agent.set"]
    assert (event["actor"], event["resource_id"], event["reason"]) == ("owner", "A7", "one-click switch")
    assert event["after"] == {"provider": "groq", "model": "openai/gpt-oss-120b", "effort": "medium", "fallback": ""}
    assert page["history"][0] == {"agent": "A7", "provider": "groq", "model": "openai/gpt-oss-120b", "by": "owner",
                                  "at": page["history"][0]["at"], "reason": "one-click switch"}
    # a custom model chosen under "More…" is no one-click choice
    custom = client.put("/api/v1/admin/agents/A7", json=GPT_OSS | {"model": "openai/gpt-oss-20b", "reason": "smaller"},
                        headers=_as("owner")).json()["data"]
    assert next(a for a in custom["agents"] if a["agent"] == "A7")["choice"] is None


def test_a_groqcloud_key_test_lists_its_models_and_asks_none(monkeypatch):
    """The test reads GroqCloud's list of models (no model is asked, so it costs nothing); here the list is faked."""
    from modeler_agents import llm

    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(llm.OpenAICompatChat, "list_models",
                        lambda self: seen.append((self.base_url, self._headers["Authorization"])) or ["openai/gpt-oss-120b", "x"])
    assert agent_jobs.test_key("groq", {"api_key": FAKE_GROQ}) == (True, "answers; serves openai/gpt-oss-120b")
    assert seen == [("https://api.groq.com/openai/v1", f"Bearer {FAKE_GROQ}")]
    monkeypatch.setattr(llm.OpenAICompatChat, "list_models", lambda self: ["llama"])
    assert agent_jobs.test_key("groq", {"api_key": FAKE_GROQ}) == (False, "answers, but openai/gpt-oss-120b is not among its 1 models")
    monkeypatch.setattr(llm.OpenAICompatChat, "list_models", lambda self: [])
    ok, message = agent_jobs.test_key("groq", {"api_key": FAKE_GROQ})
    assert not ok and "check the key" in message



def test_another_openai_compatible_service_runs_an_agent_with_its_own_address_key_and_model(client, tmp_path):
    """For a free or cheaper service the owner chooses (Cerebras, NVIDIA's API catalog …): no code change, a key and a
    model on the agent's row."""
    key = "c" * 20
    keys = client.get("/api/v1/admin/keys", headers=_as("owner")).json()["data"]
    (other,) = [p for p in keys["providers"] if p["id"] == "openai_compat"]
    assert [f["name"] for f in other["fields"]] == ["base_url", "api_key"]
    key_id = client.post("/api/v1/admin/keys", json={"provider": "openai_compat", "reason": "free tier",
                                                     "fields": {"base_url": "https://api.example.ai/v1", "api_key": key}},
                         headers=_as("owner")).json()["data"]["keys"][0]["id"]
    client.post(f"/api/v1/admin/keys/{key_id}:activate", json={"reason": "in use"}, headers=_as("owner"))
    client.put("/api/v1/admin/agents/A8", json={"provider": "openai_compat", "model": "gpt-oss-120b", "reason": "try it"},
               headers=_as("owner"))
    assert ps.model_env(str(tmp_path), MASTER, "A8") == {
        "MODELER_LLM_PROVIDER": "openai_compat", "OPENAI_COMPAT_BASE": "https://api.example.ai/v1", "OPENAI_COMPAT_KEY": key,
        "MODELER_LLM_MODEL": "gpt-oss-120b"}
    model, problem = agent_jobs.chat_model("A8")
    assert problem is None and (model.provider, model.base_url, model.model) == (
        "openai_compat", "https://api.example.ai/v1", "gpt-oss-120b")
    # the Models page's "More…" form offers it with the model typed: a provider that needs a model, no one-click model
    page = client.get("/api/v1/admin/agents", headers=_as("owner")).json()["data"]
    assert {"id": "openai_compat", "label": "Another OpenAI-compatible service", "needs_model": True,
            "has_active_key": True} in page["providers"]
    assert not any(c["provider"] == "openai_compat" for c in page["choices"])
    assert next(a for a in page["agents"] if a["agent"] == "A8")["model"] == "gpt-oss-120b"


def test_an_nvidia_key_runs_an_agent_on_nemotron_ultra_with_one_click(client, tmp_path):
    # the owner, 2026-11-22: NVIDIA's API catalog as a free cloud model; its address is fixed, so only the key is asked
    key_id = client.post("/api/v1/admin/keys", json={"provider": "nvidia", "fields": {"api_key": "nvapi-test-0000"},
                                                      "reason": "NVIDIA trial"}, headers=_as("owner")).json()["data"]["keys"][0]["id"]
    client.post(f"/api/v1/admin/keys/{key_id}:activate", json={"reason": "in use"}, headers=_as("owner"))
    page = client.put("/api/v1/admin/agents/A8", json={"provider": "nvidia", "model": "nvidia/nemotron-3-ultra-550b-a55b",
                                                        "reason": "one-click switch"}, headers=_as("owner")).json()["data"]
    assert next(a for a in page["agents"] if a["agent"] == "A8")["choice"] == "nemotron-ultra"
    env = ps.model_env(str(tmp_path), MASTER, "A8")
    assert env == {"MODELER_LLM_PROVIDER": "nvidia", "NVIDIA_API_KEY": "nvapi-test-0000",
                   "MODELER_LLM_MODEL": "nvidia/nemotron-3-ultra-550b-a55b"}
    from modeler_agents.llm import chat_model_from_env

    model = chat_model_from_env(env)
    assert (model.provider, model.base_url) == ("nvidia", "https://integrate.api.nvidia.com/v1")


def test_the_models_every_agent_goes_on_with_are_set_in_order_and_an_agent_then_runs_on_a_chain(client, tmp_path, monkeypatch):
    # the owner, 2026-11-22: "if any model is unavailable, switch at that moment to another, so the task continues"
    from modeler_agents.llm import FallbackChat
    from modeler_api import agent_jobs

    page = client.get("/api/v1/admin/agents", headers=_as("owner")).json()["data"]
    assert page["chain"]["choices"] == [] and "receives the client's files" in page["chain"]["notice"]
    assert all(c["terms"] for c in page["choices"])
    refused = client.put("/api/v1/admin/agent-chain", json={"choices": ["no-such-model"], "reason": "x"}, headers=_as("owner"))
    assert refused.status_code == 409 and "unknown model choice" in refused.json()["detail"]
    for provider, fields in (("groq", {"api_key": FAKE_GROQ}), ("nvidia", {"api_key": "nvapi-test-0000"})):
        key_id = client.post("/api/v1/admin/keys", json={"provider": provider, "fields": fields, "reason": "keys"},
                             headers=_as("owner")).json()["data"]["keys"][0]["id"]
        client.post(f"/api/v1/admin/keys/{key_id}:activate", json={"reason": "in use"}, headers=_as("owner"))
    client.put("/api/v1/admin/agents/A6", json=GPT_OSS, headers=_as("owner"))
    page = client.put("/api/v1/admin/agent-chain", json={"choices": ["nemotron-ultra", "gpt-oss-120b"], "reason": "free tiers"},
                      headers=_as("owner")).json()["data"]
    assert page["chain"]["choices"] == ["nemotron-ultra", "gpt-oss-120b"] and page["chain"]["reason"] == "free tiers"
    (event,) = [e for e in _audit(tmp_path) if e["action"] == "admin.agent.chain"]
    assert event["after"] == {"choices": ["nemotron-ultra", "gpt-oss-120b"]} and event["before"] == {"choices": []}
    model, problem = agent_jobs.chat_model("A6")
    assert problem is None and isinstance(model, FallbackChat)
    assert model.labels == ["groq/openai/gpt-oss-120b", "Nemotron Ultra"]     # its own model is not listed twice
    row = next(a for a in page["agents"] if a["agent"] == "A6")
    assert row["runs_on"]["then"] == ["Nemotron Ultra"]
