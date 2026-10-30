"""T-41: P0 initiate and the P1 brief through the API, with the agent scripted and PubChem stubbed."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from modeler_agents.llm import ChatResult, ToolCall
from modeler_api import brief_api, jobs, project_api
from modeler_api.auth import get_verifier
from modeler_api.main import app
from modeler_project import FileProjectStore
from modeler_project.identity import IdentityError

pytestmark = pytest.mark.req("T-41")
H = {"Authorization": "Bearer t"}
PROPOSAL = (b"PBPK model of exampleamide.\nObjective: predict exposure after a single oral dose of 50 mg in healthy adults.\n"
            b"The client will provide the clinical PK data of study EX-101.")


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


def _initiate(c) -> str:
    response = c.post("/api/v1/projects:initiate", headers=H, data={"drug_name": "Exampleamide", "extract": "false",
                                                                     "context": "Generic IR tablet project for a US client."},
                      files=[("files", ("proposal.txt", PROPOSAL, "text/plain"))])
    assert response.status_code == 201, response.text
    return response.json()["data"]["project_id"]


def test_initiate_creates_project_documents_and_a_first_brief(client):
    c, _ = client
    pid = _initiate(c)
    assert pid == "exampleamide-pbpk"
    docs = c.get(f"/api/v1/projects/{pid}/documents", headers=H).json()["data"]["documents"]
    assert sorted(d["role"] for d in docs) == ["context", "proposal"]
    proposal = next(d for d in docs if d["role"] == "proposal")
    page = c.get(f"/api/v1/projects/{pid}/documents/{proposal['sha256']}/pages/1", headers=H).json()["data"]
    assert "single oral dose of 50 mg" in page["text"]
    raw = c.get(f"/api/v1/projects/{pid}/documents/{proposal['sha256']}/raw", headers=H)
    assert raw.content == PROPOSAL
    view = c.get(f"/api/v1/projects/{pid}/brief", headers=H).json()["data"]
    assert view["brief"]["fields"]["drug.name"]["value"] == "Exampleamide"
    assert view["agents"]["enabled"] is False and view["blocking"] > 0
    project = c.get(f"/api/v1/projects/{pid}", headers=H)
    assert project.status_code == 200 and project.json()["data"]["compounds"] == ["Exampleamide"]


def test_unsupported_upload_is_refused(client):
    c, _ = client
    r = c.post("/api/v1/projects:initiate", headers=H, data={"drug_name": "X", "extract": "false"},
               files=[("files", ("scan.gif", b"GIF89a", "image/gif"))])
    assert r.status_code == 422 and "unsupported" in r.json()["detail"]


def test_extraction_with_a_scripted_agent_then_edit_and_preview(client):
    c, store = client
    pid = _initiate(c)
    sha = next(d["sha256"] for d in c.get(f"/api/v1/projects/{pid}/documents", headers=H).json()["data"]["documents"]
               if d["role"] == "proposal")

    class Scripted:
        provider, model = "test", "scripted"

        def __init__(self):
            self.turns = [[("propose_field", {"path": "scenarios[0].dose", "value": "50", "unit": "mg",
                                              "quote": "single oral dose of 50 mg", "doc_sha256": sha, "page": 1})], []]

        def complete(self, messages, tools):
            calls = self.turns.pop(0)
            return ChatResult(content="done", finish_reason="", model="s", usage={"input_tokens": 1, "output_tokens": 1},
                              tool_calls=tuple(ToolCall(id="c", name=n, arguments=a) for n, a in calls))

    def no_pubchem(name):
        raise IdentityError("PubChem is not reachable from this host")

    result = brief_api.run_extraction(store, "t1", pid, by="u1", model=Scripted(), fetch_identity=no_pubchem)
    assert result["status"] == "COMPLETED" and result["accepted"] == 1 and result["brief_version"] == 2
    run = c.get(f"/api/v1/projects/{pid}/agent-runs/{result['run_id']}", headers=H).json()["data"]
    assert run["run"]["status"] == "COMPLETED" and any(s["kind"] == "tool_result" for s in run["steps"])

    view = c.get(f"/api/v1/projects/{pid}/brief", headers=H).json()["data"]
    dose = view["brief"]["groups"]["scenarios"][0]["dose"]
    assert dose["status"] == "EXTRACTED" and dose["citations"][0]["quote"] == "single oral dose of 50 mg"

    edit = {"changes": [{"path": "scenarios[0].dose", "status": "EDITED", "value": 100, "note": "amendment 1"}],
            "reason": "client amended the dose"}
    preview = c.put(f"/api/v1/projects/{pid}/brief", headers=H, json={**edit, "preview": True}).json()["data"]["impact"]
    assert any(ch["path"].endswith("dose.value") for ch in preview["changes"])
    assert c.get(f"/api/v1/projects/{pid}/artifacts/brief/main", headers=H).json()["data"]["version"] == 2
    saved = c.put(f"/api/v1/projects/{pid}/brief", headers=H, json=edit).json()["data"]
    assert saved["artifact"]["version"] == 3 and saved["artifact"]["reason"] == "client amended the dose"

    # nothing is approved (D-27): the brief's approval is gone, the one review is the MAP signature
    assert c.post(f"/api/v1/projects/{pid}/brief:approve", headers=H, json={}).status_code == 404

    bad = c.put(f"/api/v1/projects/{pid}/brief", headers=H,
                json={"changes": [{"path": "drug.modality", "status": "EDITED", "value": "pill", "note": "x"}], "reason": "r"})
    assert bad.status_code == 422 and "not one of" in bad.json()["detail"]


@pytest.mark.req("T-50")
def test_the_agents_m15_draft_waits_on_a_person_who_confirms_it_in_place(client):
    # page review 1 (the owner's decisions 1b and 4 of 2026-10-29): suggested ratings and why, never a value until confirmed
    c, store = client
    pid = _initiate(c)
    sha = next(d["sha256"] for d in c.get(f"/api/v1/projects/{pid}/documents", headers=H).json()["data"]["documents"]
               if d["role"] == "proposal")
    why = {"how_the_model_is_used": "The exposure prediction supports dose selection alongside the clinical data",
           "what_a_wrong_decision_means": "A wrong exposure estimate could expose patients to too high a dose"}

    class Scripted:
        provider, model = "test", "scripted"

        def __init__(self):
            self.turns = [[("propose_field", {"path": "qoi.text", "value": "exposure after a single 50 mg oral dose",
                                              "quote": "predict exposure after a single oral dose of 50 mg", "doc_sha256": sha,
                                              "page": 1}),
                           ("propose_field", {"path": "qoi.context_of_use", "value": "healthy adults",
                                              "quote": "50 mg in healthy adults", "doc_sha256": sha, "page": 1})],
                          [("draft_risk_assessment", {"influence": "medium", "consequence": "high", **why})], []]

        def complete(self, messages, tools):
            calls = self.turns.pop(0)
            return ChatResult(content="done", finish_reason="", model="s", usage={"input_tokens": 1, "output_tokens": 1},
                              tool_calls=tuple(ToolCall(id="c", name=n, arguments=a) for n, a in calls))

    def no_pubchem(name):
        raise IdentityError("PubChem is not reachable from this host")

    result = brief_api.run_extraction(store, "t1", pid, by="u1", model=Scripted(), fetch_identity=no_pubchem)
    assert result["status"] == "COMPLETED" and result["accepted"] == 6
    view = c.get(f"/api/v1/projects/{pid}/brief", headers=H).json()["data"]
    fields = view["brief"]["fields"]
    assert fields["m15.influence_suggested"]["status"] == "DRAFTED" and fields["m15.influence_suggested"]["value"] == "medium"
    assert fields["m15.influence"]["value"] == why["how_the_model_is_used"]
    assert fields["m15.influence_rating"]["status"] == "MISSING"           # the rating itself waits on the person
    issues = [(i["path"], i["message"]) for i in view["start"]["issues"]]
    assert ("m15.influence", "How the model is used: confirm the intake agent's draft, or change it") in issues
    assert ("acceptance.tier", "Model influence: not rated yet") in issues   # the rating itself waits on the person
    confirmed = c.put(f"/api/v1/projects/{pid}/brief", headers=H, json={"changes": [
        {"path": "m15.influence", "status": "CONFIRMED"},
        {"path": "m15.consequence", "status": "EDITED", "value": "Too high a dose could harm patients"}]})
    assert confirmed.status_code == 200, confirmed.text
    view = c.get(f"/api/v1/projects/{pid}/brief", headers=H).json()["data"]
    assert {"m15.influence", "m15.consequence"}.isdisjoint(i["path"] for i in view["start"]["issues"])
    assert view["brief"]["fields"]["m15.influence"]["status"] == "CONFIRMED"
    assert view["brief"]["fields"]["m15.influence"]["by"] == "u1"


@pytest.mark.req("T-50")
def test_start_edits_ask_no_reason_refuse_a_risk_outside_its_m15_range_and_keep_the_checklist_current(client):
    """Redesign §3.1: the checklist exists from the start and follows each saved brief; D-28 gates and the ICH M15 risk
    are in the brief's answer; a tier its two ratings do not admit is refused."""
    c, _store = client
    pid = _initiate(c)
    checklist = c.get(f"/api/v1/projects/{pid}/requirements", headers=H)
    assert checklist.status_code == 200 and checklist.json()["data"]["artifact"]["status"] != "STALE"
    first = checklist.json()["data"]["artifact"]["version"]
    view = c.get(f"/api/v1/projects/{pid}/brief", headers=H).json()["data"]
    assert view["catalog"]["short_brief"][0] == "drug.name" and view["catalog"]["short_group_fields"]["scenarios"]
    assert {g["gate"]: g["state"] for g in view["start"]["gates"]}["pbpk_model"] == "not_set"
    assert "Model risk: not set yet (it is never assumed)" in view["start"]["problems"]
    assert "CYP3A4" in view["start"]["pathway_suggestions"]
    # page review 1: each issue names its field; the tier's criteria and loosest target; what each application adds
    issues = {i["path"]: i["message"] for i in view["start"]["issues"]}
    assert issues["acceptance.tier"] == "Model risk: not set yet (it is never assumed)"
    assert [i["message"] for i in view["start"]["issues"]] == view["start"]["problems"]
    risk = view["start"]["risk"]
    assert risk["criteria"]["medium"] == "AUC within 1.5-fold and Cmax within 1.5-fold, in 80% of studies"
    assert risk["target_max"]["medium"] == 33.3 and risk["ruleset"].endswith("(UNVERIFIED)")
    food = next(a for a in view["start"]["applications"] if a["code"] == "APP-12")
    assert food["name"] == "food effect" and "FaSSIF / FeSSIF solubility" in food["adds"]
    assert view["start"]["pathways_not_named"] == []

    def put(*changes, reason=""):
        return c.put(f"/api/v1/projects/{pid}/brief", headers=H, json={
            "changes": [{"path": p, "status": "EDITED", "value": v} for p, v in changes], **({"reason": reason} if reason else {})})

    rated = put(("m15.influence_rating", "high"), ("m15.consequence_rating", "high"))
    assert rated.status_code == 200, rated.text
    data = rated.json()["data"]
    assert data["artifact"]["reason"] == "edited: m15.influence_rating, m15.consequence_rating"
    assert data["start"]["risk"]["allowed"] == ["high"]
    refused = put(("acceptance.tier", "low"))
    assert refused.status_code == 422 and "admits a model risk of high, not low" in refused.json()["detail"]
    saved = put(("acceptance.tier", "high"), ("scope.pbpk_model", "minimal"), ("scenarios[0].route", "oral")).json()["data"]
    assert not saved["start"]["risk"]["problems"]
    assert "PBPK model: minimal PBPK: not supported yet" in saved["start"]["problems"]
    after = c.get(f"/api/v1/projects/{pid}/requirements", headers=H).json()["data"]
    assert after["artifact"]["version"] > first and after["artifact"]["status"] != "STALE"
    assert any(line["status"] == "NOT_SUPPORTED" and line["needed_because"] == "scope.pbpk_model"
               for line in after["feasibility"]["lines"])


@pytest.mark.req("T-42")
def test_the_data_plan_follows_every_brief_change_and_keeps_a_persons_override_with_no_approval(client):
    c, _ = client
    pid = _initiate(c)
    changes = [{"path": path, "status": "EDITED", "value": value} for path, value in (
        ("drug.modality", "small_molecule"), ("qoi.applications", ["APP-01"]), ("scenarios[0].route", "oral"),
        ("data_plan[0].item", "clinical PK of EX-101"), ("data_plan[0].category", "clinical_pk_oral"),
        ("data_plan[0].provider", "CLIENT"))]
    assert c.put(f"/api/v1/projects/{pid}/brief", headers=H, json={"changes": changes}).status_code == 200
    plan = c.get(f"/api/v1/projects/{pid}/requirements", headers=H).json()["data"]
    assert plan["artifact"]["status"] == "DRAFT" and plan["counts"]["applicable"] > 10      # current, never approved
    po = next(i for i in plan["matrix"]["items"] if i["req_id"] == "REQ-obs.po_fasted_range")
    assert po["provider"] == "CLIENT" and po["provider_statement"] == "clinical PK of EX-101"

    changed = c.put(f"/api/v1/projects/{pid}/requirements/REQ-phys.logp", headers=H,
                    json={"provider": "CLIENT", "reason": "the client measured logD7.4"}).json()["data"]
    logp = next(i for i in changed["matrix"]["items"] if i["req_id"] == "REQ-phys.logp")
    assert logp["provider"] == "CLIENT" and logp["provider_source"] == "override"
    c.put(f"/api/v1/projects/{pid}/brief", headers=H, json={"changes": [
        {"path": "drug.bcs_class", "status": "EDITED", "value": "II"}]})
    kept = c.get(f"/api/v1/projects/{pid}/requirements", headers=H).json()["data"]
    assert kept["artifact"]["version"] > changed["artifact"]["version"]                      # re-derived from the edit
    assert next(i for i in kept["matrix"]["items"] if i["req_id"] == "REQ-phys.logp")["provider_source"] == "override"
    assert c.post(f"/api/v1/projects/{pid}/requirements:approve", headers=H, json={}).status_code == 404


def test_one_upload_carries_the_proposal_and_the_clients_files(client):
    """Map rows p0-files and p3-upload: the client's files go straight to Inputs; one that cannot be read is reported
    with the reason, and the project still starts."""
    from modeler_intake.client_template import build_template

    c, _ = client
    xlsx = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    answer = c.post("/api/v1/projects:initiate", headers=H, data={"drug_name": "Exampleamide", "extract": "false"},
                    files=[("files", ("proposal.txt", PROPOSAL, "text/plain")),
                           ("client_files", ("ModelerOne_ClientData.xlsx", build_template(), xlsx)),
                           ("client_files", ("scan.gif", b"GIF89a", "image/gif"))])
    assert answer.status_code == 201, answer.text
    started = answer.json()["data"]
    assert [d["role"] for d in started["documents"]] == ["proposal"]
    template, refused = started["client_files"]
    assert template["template"] is True and template["id"] and template["problem"] is None
    assert refused["id"] is None and "unsupported" in refused["problem"]
    pid = started["project_id"]
    files = c.get(f"/api/v1/projects/{pid}/client-data", headers=H).json()["data"]["files"]
    assert [f["file"] for f in files] == ["ModelerOne_ClientData.xlsx"]


def test_documents_extraction_items_and_questions_answer_through_their_typed_models(client, monkeypatch):
    # phase 6b: every brief route answers through its response model (the conftest guard compares each answer with
    # what the handler returned); these four had no test that called them
    c, store = client
    started_jobs = []
    monkeypatch.setattr(brief_api, "run_extraction", lambda *args, **kwargs: started_jobs.append(kwargs))  # no PubChem
    pid = _initiate(c)
    added = c.post(f"/api/v1/projects/{pid}/documents", headers=H, data={"role": "annex"},
                   files=[("files", ("annex.txt", b"Annex: assay validation of EX-101.", "text/plain"))])
    assert added.status_code == 201 and [d["role"] for d in added.json()["data"]["documents"]] == ["annex"]

    started = c.post(f"/api/v1/projects/{pid}/brief:extract", headers=H, json={"context_note": "annex added"})
    assert started.status_code == 202 and started.json()["data"]["agents"] is False
    for _ in range(100):  # the background job ends at once; wait so it never overlaps the edits below
        if started_jobs and not jobs.running(store, "t1", pid, "extraction"):
            break
        time.sleep(0.01)
    assert started_jobs[0]["context_note"] == "annex added"

    item = {"changes": [{"path": "products[0].name", "status": "EDITED", "value": "50 mg tablet", "note": "from the PO"}],
            "reason": "first product"}
    assert c.put(f"/api/v1/projects/{pid}/brief", headers=H, json=item).status_code == 200
    removed = c.post(f"/api/v1/projects/{pid}/brief/items:remove", headers=H,
                     json={"group": "products", "index": 0, "reason": "entered twice"}).json()["data"]
    assert removed["brief"]["groups"].get("products", []) == []

    from modeler_project import ArtifactKind, Workspace
    from modeler_project.brief import ProjectBrief, Question

    ws = Workspace(store, "t1", pid)
    latest = ws.latest(ArtifactKind.BRIEF, "main")
    brief = ProjectBrief.from_content(latest.content)
    brief = brief.model_copy(update={"questions": (Question(id="q1", field="qoi.text", question="Which dose?"),)})
    ws.commit(ArtifactKind.BRIEF, "main", brief.to_content(), derived_from=latest.derived_from, actor="agent:t",
              reason="question raised")
    answered = c.post(f"/api/v1/projects/{pid}/brief/questions/q1", headers=H, json={"answer": "50 mg"}).json()["data"]
    assert answered["summary"]["open_questions"] == 0


def test_an_extraction_running_on_another_worker_is_shown_and_not_started_twice(client):
    # phase 8 (C8): the job's lease lives under the store's root, so a worker that did not start it sees it running
    # and refuses a second start with the same 409 (a lease another worker renewed just now)
    import json as _json
    from datetime import UTC, datetime

    from modeler_storage.jobs import FileJobRegistry

    c, store = client
    pid = _initiate(c)
    lease = FileJobRegistry(store.root)._path("t1", pid, "extraction")
    lease.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).isoformat()
    lease.write_text(_json.dumps({"owner": "worker-2:4242:x", "host": "worker-2", "pid": 4242, "started_at": now,
                                  "heartbeat_at": now}))
    assert c.get(f"/api/v1/projects/{pid}/brief", headers=H).json()["data"]["extraction_running"] is True
    second = c.post(f"/api/v1/projects/{pid}/brief:extract", headers=H, json={"context_note": ""})
    assert second.status_code == 409 and "already running" in second.json()["detail"]


def test_two_quick_edits_of_the_brief_both_land(client, monkeypatch):
    """The Start screen saves each pick at once: two edits a moment apart must both be kept. Each reads, changes and
    commits the latest brief; the later one, built on the version before the other, used to overwrite it silently."""
    import threading

    c, _ = client
    pid = _initiate(c)
    real = brief_api._apply_changes
    first = threading.Event()

    def slow(brief, changes, by):              # the first edit reads, then waits while the second one runs
        if not first.is_set():
            first.set()
            time.sleep(0.5)
        return real(brief, changes, by)

    monkeypatch.setattr(brief_api, "_apply_changes", slow)
    edits = [{"path": "scope.pbpk_model", "status": "EDITED", "value": "full"},
             {"path": "scope.site_of_action", "status": "EDITED", "value": "systemic"}]
    answers: list[int] = []

    def put(change):
        answers.append(c.put(f"/api/v1/projects/{pid}/brief", headers=H, json={"changes": [change]}).status_code)

    threads = [threading.Thread(target=put, args=(edits[0],))]
    threads[0].start()
    first.wait(5)
    threads.append(threading.Thread(target=put, args=(edits[1],)))
    threads[1].start()
    for t in threads:
        t.join(10)
    fields = c.get(f"/api/v1/projects/{pid}/brief", headers=H).json()["data"]["brief"]["fields"]
    assert answers == [200, 200]
    assert (fields["scope.pbpk_model"]["value"], fields["scope.site_of_action"]["value"]) == ("full", "systemic")


def test_an_edit_made_while_the_agent_merges_its_reading_is_kept(client, monkeypatch):
    """A1 runs while the person picks on the Start screen. Its result is merged into the latest brief and committed
    under the same lock as the person's edits, so an edit landing meanwhile is never overwritten by the merge."""
    import threading

    c, store = client
    pid = _initiate(c)
    real = brief_api._merge_agent_result
    merging = threading.Event()

    def slow(latest, brief, accepted_paths):     # A1 has read the latest brief and is merging into it
        merging.set()
        time.sleep(0.5)
        return real(latest, brief, accepted_paths)

    def no_pubchem(name):
        raise IdentityError("PubChem is not reachable from this host")

    monkeypatch.setattr(brief_api, "_merge_agent_result", slow)
    agent = threading.Thread(target=brief_api.run_extraction, args=(store, "t1", pid),
                             kwargs={"by": "u1", "fetch_identity": no_pubchem})
    agent.start()
    merging.wait(5)
    edit = c.put(f"/api/v1/projects/{pid}/brief", headers=H,
                 json={"changes": [{"path": "scope.pbpk_model", "status": "EDITED", "value": "full"}]})
    agent.join(10)
    fields = c.get(f"/api/v1/projects/{pid}/brief", headers=H).json()["data"]["brief"]["fields"]
    assert edit.status_code == 200
    assert fields["scope.pbpk_model"]["value"] == "full"


def test_the_library_lists_each_document_with_who_added_it_and_what_cites_it(client):
    # docs/plans/2026-10-28-project-document-library.md, PR 1: the table the library page shows
    c, _ = client
    pid = _initiate(c)
    docs = c.get(f"/api/v1/projects/{pid}/library", headers=H).json()["data"]["documents"]
    assert sorted(d["role"] for d in docs) == ["context", "proposal"]
    proposal = next(d for d in docs if d["role"] == "proposal")
    assert (proposal["name"], proposal["source"], proposal["added_by"], proposal["versions"]) == ("proposal.txt", "person",
                                                                                                    "u1", 1)
    assert proposal["contributions"] == []                     # nothing is read from it yet (agents off)
