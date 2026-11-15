"""T-44: the P2 evidence endpoints — manual path, decisions, gate; the A2 run with a scripted model."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from modeler_api import project_api
from modeler_api.auth import get_verifier
from modeler_api.main import app
from modeler_project import ArtifactKind, FileProjectStore, Workspace
from modeler_project.brief import empty_brief
from modeler_project.requirements import derive

pytestmark = pytest.mark.req("T-44")
H = {"Authorization": "Bearer t"}


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


def test_manual_evidence_needs_a_source_and_is_graded(setup):
    c, _ws = setup
    no_source = c.post("/api/v1/projects/p1/evidence", headers=H, json={
        "req_id": "REQ-bind.fu", "target": "bind.fu", "value": 9.0, "unit": "%", "source_type": "PUBLICATION"})
    assert no_source.status_code == 422 and "cite the source" in no_source.json()["detail"]
    ok = c.post("/api/v1/projects/p1/evidence", headers=H, json={
        "req_id": "REQ-bind.fu", "target": "bind.fu", "value": 9.0, "unit": "%", "source_type": "REGULATORY_REVIEW",
        "doi": "10.1/fda-review", "conditions": {"species": "human", "matrix": "plasma", "method": "ED",
                                                 "drug concentration": "1 µM"}})
    item = ok.json()["data"]
    assert ok.status_code == 201 and item["value_pksim"] == pytest.approx(0.09) and item["state"] == "PROPOSED"

    # agents off: the structured sources alone, by code (plan 2026-11-05 §3.3); A3 still needs a model
    started = c.post("/api/v1/projects/p1/evidence:research", headers=H)
    assert started.status_code == 202 and started.json()["data"]["provider"] == "code"
    refused = c.post("/api/v1/projects/p1/evidence:research?agent=A3", headers=H)
    assert refused.status_code == 409 and "agents are off" in refused.json()["detail"]
    from modeler_api import jobs
    _wait_until_idle(jobs, _ws.store, "p1")

    view = c.post(f"/api/v1/projects/p1/evidence/{item['id']}:decide", headers=H,
                  json={"state": "ACCEPTED", "reason": "FDA review table 3"}).json()["data"]
    fu = next(r for r in view["coverage"] if r["req_id"] == "REQ-bind.fu")
    assert fu["status"] == "ACCEPTED" and "REQ-phys.logp" in view["blocking"]   # what the literature still owes, shown


def test_research_job_runs_a2_and_records_the_run(setup):
    from modeler_agents.llm import ChatResult
    from modeler_api.evidence_api import run_research_job

    c, ws = setup

    class Quiet:
        provider, model = "test", "s"

        def complete(self, messages, tools):
            return ChatResult(content="nothing found", tool_calls=(), finish_reason="", usage={}, model="s")

    result = run_research_job(ws.store, "t1", "p1", model=Quiet())
    assert result["status"] == "COMPLETED"
    view = c.get("/api/v1/projects/p1/evidence", headers=H).json()["data"]
    assert view["runs"][0]["run_id"] == result["run_id"]


@pytest.mark.req("T-45", "T-19")
def test_observed_data_manual_digitized_overlay_and_coverage(setup):
    c, ws = setup
    from modeler_project.documents import DocumentLibrary

    study = {"study_id": "doe-2019-iv-5mg", "reference": "Doe 2019", "n": 8, "route": "iv_infusion", "dose_mg": 5,
             "infusion_time_min": 30, "statistic": "mean_sd"}
    no_source = c.post("/api/v1/projects/p1/datasets", headers=H, json={"study": study, "series": [
        {"times": [0.5, 1, 2], "values": [80, 60, 40]}]})
    assert no_source.status_code == 422 and "cite the source" in no_source.json()["detail"]

    doc = DocumentLibrary(ws).add(b"Figure 2 shows the fed arm", "fig.txt", role="paper", by="u1")
    cal = {"x": {"p1": 100, "v1": 0, "p2": 700, "v2": 24}, "y": {"p1": 500, "v1": 0, "p2": 100, "v2": 200}}
    made = c.post("/api/v1/projects/p1/datasets:digitize", headers=H, json={
        "study": study, "doc_sha256": doc.content["sha256"], "page": 1, "locator": "Figure 2", "calibration": cal,
        "pixels": {"mean": [[125, 300], [150, 350], [200, 400]]}, "time_unit": "h", "unit": "ng/ml", "n": 8})
    assert made.status_code == 201, made.text
    ds = made.json()["data"]
    assert ds["series"][0]["times"] == [1.0, 2.0, 4.0] and ds["series"][0]["values"] == [100.0, 75.0, 50.0]
    assert "digitized: overlay not yet approved" in ds["flags"]
    early = c.post(f"/api/v1/projects/p1/datasets/{ds['id']}:decide", headers=H, json={"state": "ACCEPTED", "reason": "ok"})
    assert early.status_code == 422 and "overlay" in early.json()["detail"]
    assert c.post(f"/api/v1/projects/p1/datasets/{ds['id']}:overlay", headers=H).status_code == 200
    view = c.post(f"/api/v1/projects/p1/datasets/{ds['id']}:decide", headers=H,
                  json={"state": "ACCEPTED", "reason": "overlay matches the figure"}).json()["data"]
    iv = next(r for r in view["coverage"] if r["req_id"] == "REQ-obs.iv_sd")
    assert iv["status"] == "ACCEPTED" and iv["accepted"] == [ds["id"]]


def test_a_hand_entered_value_must_name_a_parameter_the_model_uses(setup):
    c = setup[0] if isinstance(setup, tuple) else setup
    body = {"req_id": "REQ-bind.fu", "value": 30, "unit": "%", "source_type": "PUBLICATION", "doi": "10.2147/x", "quote": "30% bound"}
    wrong = c.post("/api/v1/projects/p1/evidence", headers=H, json={**body, "target": "plasma protein binding"})
    assert wrong.status_code == 422 and "not a parameter the model uses" in wrong.json()["detail"]
    assert c.post("/api/v1/projects/p1/evidence", headers=H, json={**body, "target": "bind.fu"}).status_code == 201


@pytest.mark.req("T-44", "T-49")
def test_a_value_pksim_takes_only_by_name_must_be_one_of_its_names(setup):
    """Plan 2026-11-14 §5 (the fill round's API follow-ups): the plasma protein binding partner is one of PK-Sim's names,
    read from the model builder's own type (`CompoundSpec.binding_partner`). Any other value, a number or a name written
    otherwise, is refused with the names, and nothing is stored; the Inputs row offers the same names."""
    from typing import get_args

    from modeler_project.evidence_register import items
    from pbpk_domain.snapshot.builder import CompoundSpec

    c, ws = setup
    names = [w for arg in get_args(CompoundSpec.model_fields["binding_partner"].annotation) for w in get_args(arg)]
    assert names and all(isinstance(w, str) for w in names)
    body = {"req_id": "REQ-bind.partner", "target": "bind.partner", "source_type": "ASSUMPTION"}
    for wrong in ("albumin", "human serum albumin", 1.0):
        refused = c.post("/api/v1/projects/p1/evidence", headers=H, json={**body, "value": wrong})
        assert refused.status_code == 422, wrong
        detail = refused.json()["detail"]
        assert detail["code"] == "NOT_ALLOWED" and detail["allowed"] == names and all(n in detail["message"] for n in names)
    assert items(ws) == []
    stored = c.post("/api/v1/projects/p1/evidence", headers=H, json={**body, "value": names[0]})
    assert stored.status_code == 201 and stored.json()["data"]["value"] == names[0]
    # a word for another input is not checked against these names (its row has none)
    assert c.post("/api/v1/projects/p1/evidence", headers=H, json={"req_id": "REQ-bind.fu", "target": "bind.fu", "value": 0.1,
                                                                   "source_type": "ASSUMPTION"}).status_code == 201
    rows = {r["id"]: r for r in c.get("/api/v1/projects/p1/inputs", headers=H).json()["data"]["compound"]}
    assert rows["bind.partner"]["allowed"] == names and rows["bind.fu"]["allowed"] == []


@pytest.mark.req("T-44", "T-49")
def test_a_binding_partner_that_is_not_one_of_pksims_names_enters_the_model_by_no_persons_route(setup):
    """Review of the fill round's API follow-ups: the name check holds on every route a person lets a value into the
    model by, not only `POST /evidence`. A name filed under another input and corrected into bind.partner is refused, so
    is accepting or keeping one a literature agent proposed; nothing is written. A value let in without a person's route
    (a signed delivery's landing, one stored before the check) is said on its Inputs row. A published model's
    "unspecified", which the model builder reads as not set, is accepted."""
    from modeler_project.evidence import EvidenceItem, EvidenceState, Extraction, SourceRef, SourceType, new_id
    from modeler_project.evidence_register import decide, items, propose
    from modeler_project.inputs import allowed_values, refresh_inputs
    from modeler_project.requirements import RequirementMatrix
    from pbpk_domain.cpf.build import UNSPECIFIED_PARTNER

    c, ws = setup
    names = list(allowed_values("bind.partner"))
    base = "/api/v1/projects/p1/evidence"

    def refused(answer) -> bool:
        detail = answer.json()["detail"]
        return answer.status_code == 422 and detail["code"] == "NOT_ALLOWED" and detail["allowed"] == names

    def versions() -> int:
        return sum(1 for _ in ws.list(ArtifactKind.EVIDENCE))

    # filed under another input (which takes any word), then corrected into bind.partner: refused, nothing written
    filed = c.post(base, headers=H, json={"req_id": "REQ-bind.partner", "target": "dist.partition_method", "value": "albumin",
                                          "source_type": "ASSUMPTION"})
    assert filed.status_code == 201, filed.text
    before = versions()
    corrected = c.post(f"{base}/{filed.json()['data']['id']}:correct", headers=H,
                       json={"target": "bind.partner", "reason": "it is the binding partner"})
    assert refused(corrected) and versions() == before
    assert [(e.target, e.state) for e in items(ws)] == [("dist.partition_method", EvidenceState.PROPOSED)]

    # a literature agent's proposal ("bound to albumin"): a person can neither accept it nor keep it
    matrix = RequirementMatrix.from_content(ws.latest(ArtifactKind.REQUIREMENTS, "main").content)
    requirement = matrix.get("REQ-bind.partner")

    def proposal(value: str) -> EvidenceItem:
        item = EvidenceItem(id=new_id(), req_id=requirement.req_id, target="bind.partner", value=value, unit=None,
                            source_type=SourceType.PUBLICATION, source=SourceRef(doi="10.1/partner", title="A paper"),
                            quote=f"the drug is bound to {value}", extraction=Extraction.MANUAL, purpose="model_building",
                            provider="LITERATURE")
        return propose(ws, item, actor="agent:A2", requirement=requirement)

    agent = proposal("albumin")
    before = versions()
    assert refused(c.post(f"{base}/{agent.id}:decide", headers=H, json={"state": "ACCEPTED", "reason": "the paper says so"}))
    assert refused(c.post(f"{base}/{agent.id}:choose", headers=H, json={"reason": "the one to keep"}))
    assert versions() == before
    # rejecting it is a person's route too, and is never refused
    assert c.post(f"{base}/{agent.id}:decide", headers=H, json={"state": "REJECTED", "reason": "not PK-Sim's name"}).status_code == 200

    # let in without a person's route: kept in the model, and its row says the model builder cannot take it
    landed = proposal("human serum albumin")
    decide(ws, landed.id, state=EvidenceState.ACCEPTED, reason="a signed delivery", by="u1")
    refresh_inputs(ws, by="u1")
    rows = {r["id"]: r for r in c.get("/api/v1/projects/p1/inputs", headers=H).json()["data"]["compound"]}
    row = rows["bind.partner"]
    assert (row["state"], row["value"], row["allowed"]) == ("kept", "human serum albumin", names)
    assert row["message"] and all(n in row["message"] for n in names)
    assert c.post(f"{base}/{landed.id}:decide", headers=H, json={"state": "REJECTED", "reason": "not PK-Sim's name"}).status_code == 200

    # a published model that leaves the partner unset: accepted, and its row says nothing
    unset = proposal(UNSPECIFIED_PARTNER)
    accepted = c.post(f"{base}/{unset.id}:decide", headers=H, json={"state": "ACCEPTED", "reason": "the OSP model's"})
    assert accepted.status_code == 200, accepted.text
    rows = {r["id"]: r for r in c.get("/api/v1/projects/p1/inputs", headers=H).json()["data"]["compound"]}
    assert (rows["bind.partner"]["state"], rows["bind.partner"]["value"], rows["bind.partner"]["message"]) == (
        "kept", UNSPECIFIED_PARTNER, None)
    # and one of PK-Sim's names is taken on every route
    named = proposal(names[1])
    assert c.post(f"{base}/{named.id}:choose", headers=H, json={"reason": "the paper's"}).status_code == 200


def _wait_until_idle(jobs, store, project_id: str) -> None:
    for _ in range(200):
        if not jobs.running(store, "t1", project_id, "research"):
            return
        time.sleep(0.01)


def test_research_start_paper_fulfilment_and_the_closed_register_answer_through_their_typed_models(setup, monkeypatch):
    # phase 6c: these three routes had no test that reached their answer (the conftest guard checks each answer)
    from modeler_api import agent_jobs, evidence_api, jobs
    from modeler_project.evidence_register import request_access
    from modeler_project.requirements import RequirementMatrix, RequirementOverride, literature_items

    c, ws = setup

    class Configured:
        provider, model = "test", "scripted"

    calls = []
    monkeypatch.setattr(agent_jobs, "chat_model", lambda agent=None: (Configured(), None))
    monkeypatch.setattr(evidence_api, "run_research_job", lambda *args, **kwargs: calls.append(kwargs))
    started = c.post("/api/v1/projects/p1/evidence:research?agent=A3", headers=H)
    assert started.status_code == 202 and started.json()["data"] == {"started": True, "provider": "test", "model": "scripted"}
    _wait_until_idle(jobs, ws.store, "p1")
    assert calls[0]["agent"] == "A3"

    request_id, _ = request_access(ws, title="A paywalled binding study", authors="A. Author", doi="10.1/x", journal=None,
                                   year=2020, needed_for="REQ-bind.fu", by="agent:t")
    view = c.post(f"/api/v1/projects/p1/access-requests/{request_id}:fulfil", headers=H,
                  files=[("file", ("paper.txt", b"The fraction unbound in plasma was 9 %.", "text/plain"))]).json()["data"]
    assert next(r for r in view["access_requests"] if r["id"] == request_id)["status"] == "FULFILLED"

    matrix = RequirementMatrix.from_content(ws.latest(ArtifactKind.REQUIREMENTS, "main").content)
    waived = tuple(RequirementOverride(req_id=i.req_id, status="WAIVED", reason="not needed in this test", by="u1")
                   for i in literature_items(matrix))
    ws.commit(ArtifactKind.REQUIREMENTS, "main", derive(empty_brief("Exampleamide", by="u1"), waived).to_content(),
              derived_from=[ws.latest(ArtifactKind.BRIEF, "main").ref], actor="u1", reason="every literature item waived")
    assert c.get("/api/v1/projects/p1/evidence", headers=H).json()["data"]["blocking"] == []   # nothing left to find


def test_a_withdrawn_document_is_no_longer_a_source_for_new_values(setup):
    # the document library, PR 2: a person restores a withdrawn document before citing it again
    from modeler_project.documents import DocumentLibrary

    c, ws = setup
    library = DocumentLibrary(ws)
    doc = library.add(b"The unbound fraction in human plasma was 9 % (equilibrium dialysis).", "paper.md", role="paper",
                      by="u1")
    sha = doc.content["sha256"]
    library.withdraw(sha, by="u1", reason="a different salt form")
    body = {"req_id": "REQ-bind.fu", "target": "bind.fu", "value": 9.0, "unit": "%", "source_type": "PUBLICATION",
            "doc_sha256": sha, "page": 1, "quote": "unbound fraction in human plasma was 9 %"}
    refused = c.post("/api/v1/projects/p1/evidence", headers=H, json=body)
    assert refused.status_code == 409 and "a different salt form" in refused.json()["detail"]
    library.restore(sha, by="u1", reason="the right salt form")
    assert c.post("/api/v1/projects/p1/evidence", headers=H, json=body).status_code == 201


def test_a_paper_the_research_agent_stores_is_listed_with_its_source_and_what_is_held(setup):
    # the document library, PR 3 (the owner's answer 13): open-access full text only, with where it came from
    import httpx

    from modeler_agents.llm import ChatResult, ToolCall
    from modeler_agents.sources import EuropePMC
    from modeler_api.evidence_api import run_research_job

    c, ws = setup
    hits = {"resultList": {"result": [{"id": "111", "source": "MED", "pmid": "111", "pmcid": "PMC9", "doi": "10.1/oa",
                                       "title": "Pharmacokinetics of exampleamide", "pubYear": "2019", "isOpenAccess": "Y"}]}}
    jats = "<article><body><sec><p>The fraction unbound in human plasma was 9.1 %.</p></sec></body></article>"

    def transport(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json=hits)
        return httpx.Response(200, text=jats) if request.url.path.endswith("/PMC9/fullTextXML") else httpx.Response(404)

    class Reader:
        provider, model = "test", "s"

        def __init__(self):
            self.turns = [[("search_literature", {"query": "exampleamide"})], [("read_full_text", {"paper_id": "111"})], []]

        def complete(self, messages, tools):
            calls = self.turns.pop(0) if self.turns else []   # the second pass, on what is left, ends at once
            return ChatResult(content="done", finish_reason="", model="s", usage={},
                              tool_calls=tuple(ToolCall(id=f"c{i}", name=n, arguments=a) for i, (n, a) in enumerate(calls)))

    result = run_research_job(ws.store, "t1", "p1", model=Reader(), europe_pmc=EuropePMC(transport=httpx.MockTransport(transport)))
    assert result["status"] == "COMPLETED"
    (row,) = c.get("/api/v1/projects/p1/library", headers=H).json()["data"]["documents"]
    assert row["source"] == "agent" and row["role"] == "paper"
    assert {k: row["retrieved"][k] for k in ("source", "held", "pmid", "doi", "url")} == {
        "source": "Europe PMC", "held": "full_text", "pmid": "111", "doi": "10.1/oa", "url": "https://doi.org/10.1/oa"}


def test_the_literature_runs_progress_is_answered_small_for_the_page_to_follow(setup, monkeypatch):
    """Plan 2026-11-05 §3.3: the Inputs page shows the literature agent's progress (turns of its budget, values proposed
    so far) in place of a red "already running"."""
    from modeler_api import agent_jobs, jobs

    c, ws = setup
    idle = c.get("/api/v1/projects/p1/literature-run", headers=H)
    assert idle.status_code == 200, idle.text
    assert idle.json()["data"] == {"running": False, "run": None, "turns": 0, "max_turns": None, "proposed": 0, "sources": None}

    class Configured:
        provider, model = "test", "scripted"

    run = agent_jobs.AgentRun(ws.store.root, tenant_id="t1", project_id="p1", agent="A2-literature", model=Configured(),
                              max_turns=40)
    for turn in (1, 2, 3):
        run.log_step({"type": "model_turn", "turn": turn})
        run.log_step({"type": "tool_result", "turn": turn, "tool": "search", "result": "…"})
    c.post("/api/v1/projects/p1/evidence", headers=H, json={
        "req_id": "REQ-bind.fu", "target": "bind.fu", "value": 9.0, "unit": "%", "source_type": "REGULATORY_REVIEW",
        "doi": "10.1/fda-review"})                                      # a person's value: not the agent's
    from modeler_project.evidence import EvidenceItem, SourceRef, SourceType
    from modeler_project.evidence_register import propose

    propose(ws, EvidenceItem(id="ev-agent1", req_id="REQ-bind.fu", target="bind.fu", value=8.0, unit="%",
                             source_type=SourceType.PUBLICATION, source=SourceRef(doi="10.1/paper"), quote="fu was 8%"),
            actor=run.actor)
    monkeypatch.setattr(jobs, "running", lambda store, tenant, project, kind: kind == "research")
    now = c.get("/api/v1/projects/p1/literature-run", headers=H).json()["data"]
    assert now["running"] and now["run"]["run_id"] == run.run_id and now["run"]["finished_at"] is None
    assert (now["turns"], now["max_turns"], now["proposed"]) == (3, 40, 1)


def test_the_compound_sources_run_at_the_start_and_their_values_flow_in(setup, monkeypatch):
    """Build B (plan 2026-11-05 §3.3): PubChem, the FDA label and ChEMBL are read by code when the search starts (at the
    project's start, or on Inputs), before the literature agent; the page shows what each gave."""
    from modeler_agents.evals import structured_answers
    from modeler_api import agent_jobs, jobs
    from modeler_api.compound_jobs import start_compound_job
    from modeler_project.brief import empty_brief as brief_for

    c, ws = setup
    ws.commit(ArtifactKind.BRIEF, "main", brief_for(structured_answers.DRUG, by="u1").to_content(), actor="u1", reason="drug")
    monkeypatch.setattr(agent_jobs, "structured_clients", structured_answers.clients)
    assert start_compound_job(ws.store, "t1", "p1", by="u1")                       # agents off: the sources alone
    _wait_until_idle(jobs, ws.store, "p1")
    view = c.get("/api/v1/projects/p1/literature-run", headers=H).json()["data"]
    assert not view["running"] and view["run"]["agent"] == "A2-sources" and view["proposed"] == 8
    assert [(s["name"], s["values"]) for s in view["sources"]["summary"]["sources"]] == [
        ("PubChem", 5), ("FDA label", 1), ("ChEMBL", 2)]
    evidence = c.get("/api/v1/projects/p1/evidence", headers=H).json()["data"]["evidence"]
    assert {e["target"] for e in evidence} >= {"phys.mw", "phys.logp", "bind.fu", "phys.solubility.ref", "phys.pka.acid.1"}
    # stored, not assembled: Inputs has not begun, so it stays blocked until Start is done (decision 7)
    assert ws.latest(ArtifactKind.READINESS, "main") is None
    assert c.post("/api/v1/projects/p1/inputs:assemble", headers=H).status_code == 200   # as the page does when opened
    inputs = c.get("/api/v1/projects/p1/inputs", headers=H).json()["data"]
    mw = next(r for r in inputs["compound"] if r["id"] == "phys.mw")
    assert mw["state"] == "kept" and mw["value"] == 393.9                    # flowed in, no click (D-27)


def test_the_drugs_disposition_is_drafted_on_start_once_the_fda_label_is_stored(setup):
    """Build K (the owner, 2026-11-07): the proposal's reading can finish before the compound job stores the FDA label; the
    job then drafts on Start what the label states of the drug's disposition, for the fields still empty."""
    from modeler_api.compound_jobs import _disposition_on_start
    from modeler_project.brief import empty_brief as brief_for
    from modeler_project.documents import DocumentLibrary

    c, ws = setup
    ws.commit(ArtifactKind.BRIEF, "main", brief_for("Exampleamide", by="u1").to_content(), actor="u1", reason="drug")
    DocumentLibrary(ws).add_text("12.3 Pharmacokinetics The pharmacokinetics of exampleamide are linear and dose-proportional "
                                 "over 10 to 40 mg. Exampleamide is metabolized by CYP3A4.", "fda-label-exampleamide-20240101.txt",
                                 role="retrieved_record", by="system")
    assert _disposition_on_start(ws, by="code:start-reading") == ["scope.pathways", "scope.pathways_stated", "scope.nonlinearity"]
    fields = c.get("/api/v1/projects/p1/brief", headers=H).json()["data"]["brief"]["fields"]
    assert (fields["scope.nonlinearity"]["status"], fields["scope.nonlinearity"]["value"]) == ("DRAFTED", "linear")
    assert fields["scope.pathways_stated"]["value"] == ["CYP3A4"]
    assert _disposition_on_start(ws, by="code:start-reading") == []          # drafted once
