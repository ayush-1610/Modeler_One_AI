"""The platform owner's console, build A + B (docs/plans/2026-11-10-admin-console.md): who is signed in; every company
with its people, projects and agent use; one company in full; the agents' use per agent, project, person, company and
day. Only `modeler-admin` opens it, and each look is an audit event. Synthetic runs, written through the run store."""

from __future__ import annotations

import json
import threading

import pytest
from fastapi.testclient import TestClient

from modeler_agents.run_store import FileRunStore
from modeler_agents.usage_report import cost, read_runs
from modeler_api import jobs
from modeler_api.auth import get_verifier
from modeler_api.main import app
from modeler_project import FileProjectStore

pytestmark = pytest.mark.req("T-05")

PEOPLE = {"owner": ("platform", ["modeler-admin"]), "ana": ("acme", ["modeler-viewer", "modeler-curator"]),
          "ben": ("beta", ["modeler-viewer", "modeler-curator"])}


class _Verifier:
    """`Bearer ana` signs in as ana, in her company, with her roles."""

    def verify(self, token: str) -> dict:
        tenant, roles = PEOPLE[token]
        return {"sub": token, "name": token.title(), "tenant_id": tenant, "realm_access": {"roles": roles},
                "projects": [], "acr": "loa1"}


@pytest.fixture
def client(tmp_path, api_settings):
    api_settings(read_root=str(tmp_path))
    app.dependency_overrides[get_verifier] = _Verifier
    yield TestClient(app)
    app.dependency_overrides.clear()


def _as(who: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {who}"}


def _create(client: TestClient, who: str, name: str) -> str:
    answer = client.post("/api/v1/projects", json={"name": name, "compound": "Exampleamide"}, headers=_as(who))
    assert answer.status_code == 201, answer.text
    return answer.json()["data"]["id"]


def _run(root, tenant: str, project: str, agent: str, by: str | None, turns: list[tuple[int, int, int]],
         status: str = "COMPLETED") -> str:
    store = FileRunStore(root, project_id=project)
    run_id = store.start_run(tenant_id=tenant, agent=agent, provider="litellm", model="qwen-coder", campaign_id=None,
                             budget={"max_turns": 10}, started_by=by)
    for seq, (turn, tokens_in, tokens_out) in enumerate(turns, start=1):
        usage = {"input_tokens": tokens_in, "output_tokens": tokens_out}
        store.record_step(run_id=run_id, seq=seq, kind="model_turn", content={"type": "model_turn", "turn": turn,
                                                                               "usage": usage}, usage=usage)
    store.finish_run(run_id=run_id, status=status, input_tokens=sum(t[1] for t in turns),
                     output_tokens=sum(t[2] for t in turns), cost_usd=0.0, summary={})
    return run_id


def _views(tmp_path, tenant: str) -> list[dict]:
    lines = (tmp_path / tenant / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    return [e for e in (json.loads(line)["event"] for line in lines) if e["action"] == "admin.view"]


@pytest.fixture
def platform(client, tmp_path):
    acme = _create(client, "ana", "Renal Demo")
    beta = _create(client, "ben", "Hepatic Demo")
    _run(tmp_path, "acme", acme, "A1-proposal-intake", "ana", [(1, 1000, 100), (2, 1500, 100)])
    _run(tmp_path, "acme", acme, "A2-literature", "ana", [(1, 4000, 300)], status="INCOMPLETE")
    _run(tmp_path, "acme", acme, "A2-sources", None, [])                    # code only, and before runs named who
    _run(tmp_path, "beta", beta, "A1-proposal-intake", "ben", [(1, 2000, 50)])
    return {"acme": acme, "beta": beta}


def test_only_the_platform_owner_opens_the_console(client, platform):
    me = client.get("/api/v1/me", headers=_as("owner")).json()["data"]
    assert me == {"user_id": "owner", "name": "Owner", "tenant_id": "platform", "roles": ["modeler-admin"], "admin": True}
    assert client.get("/api/v1/me", headers=_as("ana")).json()["data"]["admin"] is False
    for path in ("/api/v1/admin/overview", "/api/v1/admin/companies/acme", "/api/v1/admin/usage"):
        refused = client.get(path, headers=_as("ana"))
        assert refused.status_code == 403 and "modeler-admin" in refused.json()["detail"]
    assert client.get("/api/v1/admin/overview").status_code == 401


def test_the_overview_gives_each_company_its_people_projects_and_agent_use(client, platform, tmp_path):
    client.post(f"/api/v1/projects/{_create(client, 'ana', 'Old Demo')}:archive", json={"reason": "a test project"},
                headers=_as("ana"))
    data = client.get("/api/v1/admin/overview", headers=_as("owner")).json()["data"]
    acme = next(c for c in data["companies"] if c["tenant_id"] == "acme")
    assert (acme["people"], acme["projects"], acme["archived"]) == (1, 1, 1)
    assert (acme["usage"]["runs"], acme["usage"]["failed_runs"], acme["usage"]["input_tokens"]) == (3, 1, 6500)
    assert data["total"]["runs"] == 4 and data["priced_as"] == "claude-opus-5-5"
    assert data["system"]["store"] is True and "enabled" in data["system"]["agents"]
    # the look is on the owner's own audit chain
    assert [(e["actor"], e["after"]["page"]) for e in _views(tmp_path, "platform")] == [("owner", "overview")]


def test_a_companys_page_lists_its_people_and_projects_with_their_use_and_is_audited_there(client, platform, tmp_path):
    data = client.get("/api/v1/admin/companies/acme", headers=_as("owner")).json()["data"]
    (ana,) = data["people"]
    assert (ana["name"], ana["projects"], ana["usage"]["runs"]) == ("Ana", [platform["acme"]], 2)   # the code run: nobody's
    (project,) = data["projects"]
    assert (project["name"], project["members"], project["archived"], project["usage"]["runs"]) == ("Renal Demo", ["Ana"],
                                                                                                    False, 3)
    assert [(e["actor"], e["after"]["page"]) for e in _views(tmp_path, "acme")] == [("owner", "company")]
    assert client.get("/api/v1/admin/companies/nobody", headers=_as("owner")).status_code == 404


def test_usage_per_agent_project_person_company_and_day_priced_on_a_chosen_model(client, platform, tmp_path):
    data = client.get("/api/v1/admin/usage?priced_as=claude-sonnet-5-5", headers=_as("owner")).json()["data"]
    runs = read_runs(tmp_path, code_runs=True)
    assert data["total"]["usd"] == pytest.approx(sum(cost(r, "claude-sonnet-5-5", cached=True) for r in runs), abs=1e-4)
    assert data["prices"] == {"input": 2.0, "cache_write_5m": 2.5, "cache_read": 0.1, "output": 10.0}
    people = {g["label"]: g["usage"]["runs"] for g in data["by_person"]}
    assert people == {"Ana (acme)": 2, "Ben (beta)": 1, "not recorded (runs before 2026-11-10)": 1}
    assert {g["key"]: g["usage"]["runs"] for g in data["by_agent"]} == {"A1-proposal-intake": 2, "A2-literature": 1,
                                                                         "A2-sources": 1}
    assert {g["label"] for g in data["by_project"]} == {"Renal Demo (acme)", "Hepatic Demo (beta)"}
    assert len(data["runs"]) == 4 and {r["started_by_name"] for r in data["runs"]} == {"Ana", "Ben", None}
    only_beta = client.get("/api/v1/admin/usage?tenant_id=beta", headers=_as("owner")).json()["data"]
    assert [g["key"] for g in only_beta["by_company"]] == ["beta"]
    later = client.get("/api/v1/admin/usage?since=2999-01-01", headers=_as("owner")).json()["data"]
    assert later["total"]["runs"] == 0 and later["runs"] == []
    assert [e["after"].get("company") for e in _views(tmp_path, "platform")] == [None, "beta", None]


def test_a_job_knows_who_started_it_and_each_agent_run_records_it(tmp_path):
    seen: list[str | None] = []
    done = threading.Event()

    def target() -> None:
        seen.append(jobs.started_by.get())
        done.set()

    jobs.start(FileProjectStore(tmp_path), "acme", "p1", "research", target, busy="busy", by="ana")
    assert done.wait(5) and seen == ["ana"]
    assert jobs.started_by.get() is None                                     # the request's own thread is untouched
