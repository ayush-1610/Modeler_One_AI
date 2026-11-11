"""The admin console's E (docs/plans/2026-11-10-admin-console.md, answer 2): a monthly spend and token limit per
company, project or person, a warning to the administrator at 80 % and when it is reached; never a stop, and never
shown to the companies' people. A change needs a fresh step-up and a reason, and is an audit event on the owner's chain."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from modeler_agents.run_store import FileRunStore
from modeler_api import admin_api
from modeler_api.auth import get_verifier
from modeler_api.config import get_settings
from modeler_api.main import app

pytestmark = pytest.mark.req("T-05")

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
    api_settings(read_root=str(tmp_path))
    app.dependency_overrides[get_verifier] = _Verifier
    yield TestClient(app)
    app.dependency_overrides.clear()


def _as(who: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {who}"}


def _run(root, tenant: str, project: str, by: str, tokens_in: int, tokens_out: int) -> None:
    store = FileRunStore(root, project_id=project)
    run_id = store.start_run(tenant_id=tenant, agent="A2-literature", provider="litellm", model="qwen-coder",
                             campaign_id=None, budget={"max_turns": 10}, started_by=by)
    usage = {"input_tokens": tokens_in, "output_tokens": tokens_out}
    store.record_step(run_id=run_id, seq=1, kind="model_turn", content={"type": "model_turn", "turn": 1, "usage": usage},
                      usage=usage)
    store.finish_run(run_id=run_id, status="COMPLETED", input_tokens=tokens_in, output_tokens=tokens_out, cost_usd=0.0,
                     summary={})


@pytest.fixture
def acme(client, tmp_path) -> str:
    pid = client.post("/api/v1/projects", json={"name": "Renal Demo", "compound": "Exampleamide"},
                      headers=_as("ana")).json()["data"]["id"]
    _run(tmp_path, "acme", pid, "ana", 1000, 100)                          # 1 100 tokens this month
    return pid


def _set(client: TestClient, who: str = "owner", **body) -> object:
    return client.put("/api/v1/admin/limits", json={"reason": "budget", **body}, headers=_as(who))


def _audit(tmp_path) -> list[dict]:
    lines = (tmp_path / "platform" / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line)["event"] for line in lines]


def test_the_administrator_is_warned_at_80_percent_and_when_a_limit_is_reached(client, tmp_path, acme):
    assert _set(client, scope="company", tenant_id="acme", tokens=1300).status_code == 200      # 85 %: a warning
    assert _set(client, scope="person", tenant_id="acme", subject="ana", tokens=1000).status_code == 200   # 110 %: reached
    page = _set(client, scope="project", tenant_id="acme", subject=acme, tokens=10_000, usd=500.0).json()["data"]
    rows = {r["id"]: r for r in page["limits"]}
    assert [r["id"] for r in page["limits"]] == ["person:acme/ana", "company:acme", f"project:acme/{acme}"]   # fullest first
    assert (rows["company:acme"]["used_tokens"], rows["company:acme"]["tokens_share"], rows["company:acme"]["level"]) \
        == (1100, round(1100 / 1300, 4), "warn")
    assert (rows["person:acme/ana"]["level"], rows["person:acme/ana"]["label"]) == ("over", "Ana (acme)")
    project = rows[f"project:acme/{acme}"]
    assert project["level"] == "ok" and project["label"] == "Renal Demo (acme)"
    assert project["used_usd"] > 0 and project["usd_share"] == round(project["used_usd"] / 500.0, 4)
    assert [w["id"] for w in page["warnings"]] == ["person:acme/ana", "company:acme"]
    overview = client.get("/api/v1/admin/overview", headers=_as("owner")).json()["data"]
    assert [(w["id"], w["level"]) for w in overview["warnings"]] == [("person:acme/ana", "over"), ("company:acme", "warn")]
    assert overview["month"] == datetime.now(UTC).strftime("%Y-%m")
    (target,) = [t for t in page["targets"] if t["tenant_id"] == "acme"]
    assert ([p["name"] for p in target["projects"]], [p["name"] for p in target["people"]]) == (["Renal Demo"], ["Ana"])


def test_a_change_needs_a_step_up_and_a_reason_and_is_audited_and_a_limit_is_removed_with_both_measures_empty(client, tmp_path, acme):
    stale = _set(client, "owner-stale", scope="company", tenant_id="acme", tokens=1300)
    assert stale.status_code == 403 and stale.json()["detail"]["code"] == "STEP_UP_REQUIRED"
    _set(client, scope="company", tenant_id="acme", tokens=1300)
    _set(client, scope="company", tenant_id="acme", tokens=2000, usd=50.0, reason="more for the pilot")
    removed = _set(client, scope="company", tenant_id="acme", reason="no limit for now").json()["data"]
    assert removed["limits"] == [] and [h["reason"] for h in removed["history"]] == ["no limit for now", "more for the pilot",
                                                                                      "budget"]
    events = [e for e in _audit(tmp_path) if e["action"].startswith("admin.limit.")]
    assert [(e["action"], e["before"], e["after"]) for e in events] == [
        ("admin.limit.set", None, {"usd": None, "tokens": 1300}),
        ("admin.limit.set", {"usd": None, "tokens": 1300}, {"usd": 50.0, "tokens": 2000}),
        ("admin.limit.remove", {"usd": 50.0, "tokens": 2000}, None)]
    assert events[1]["reason"] == "more for the pilot" and events[0]["resource_id"] == "company:acme"


def test_a_limit_names_something_that_exists_and_is_above_zero(client, acme):
    for body, status, why in (({"scope": "company", "tenant_id": "nope", "tokens": 5}, 404, "no company"),
                              ({"scope": "project", "tenant_id": "acme", "subject": "p-x", "tokens": 5}, 409, "no project"),
                              ({"scope": "person", "tenant_id": "acme", "subject": "zed", "tokens": 5}, 409, "no person"),
                              ({"scope": "person", "tenant_id": "acme", "tokens": 5}, 409, "names the company and"),
                              ({"scope": "company", "tenant_id": "acme", "usd": 0}, 409, "above zero"),
                              ({"scope": "company", "tenant_id": "acme"}, 409, "no limit to remove")):
        refused = _set(client, **body)
        assert refused.status_code == status and why in refused.json()["detail"], (body, refused.text)


def test_only_the_administrator_sees_or_sets_a_limit_and_each_month_starts_again(client, acme, tmp_path):
    _set(client, scope="person", tenant_id="acme", subject="ana", tokens=1000)
    assert client.get("/api/v1/admin/limits", headers=_as("ana")).status_code == 403
    assert _set(client, "ana", scope="person", tenant_id="acme", subject="ana", tokens=10).status_code == 403
    assert "limit" not in client.get(f"/api/v1/projects/{acme}", headers=_as("ana")).text.lower()
    month, rows = admin_api._limit_rows(get_settings(), admin_api.DEFAULT_PRICE, now=datetime(2099, 1, 15, tzinfo=UTC))
    assert month == "2099-01" and (rows[0]["used_tokens"], rows[0]["level"]) == (0, "ok")   # a new month, nothing used yet
