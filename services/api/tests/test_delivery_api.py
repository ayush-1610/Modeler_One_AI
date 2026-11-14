"""T-47: the Delivery section through the API (contracts 2026-11-12 §8.10, §6.6, §2; build D6-API).

Every test uploads the synthetic files through today's upload route with `intake_pipeline="both"`, lets the intake job
read them (agents off: no model, live or scripted, is needed), and then works only through the `/delivery` routes: the
page, a subject's card, a value's source, the mappings, a person's decisions, the spot check, the signed confirmation
and the landing; what a blinded study withholds (D-15) on every route; the refusals; the legacy card's guard; the
`legacy` switch.

Software test data (the made-up Exampleamide): no PK-Sim, no model's judgement. A landed dataset is checked by the
platform's own code, not simulated.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import io
import random
import re
import time
import types
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from openpyxl import Workbook
from pydantic import BaseModel

from modeler_agents.evals.scripted import Scripted
from modeler_api import admin_api, agent_jobs, client_api, delivery_routes, jobs, project_api
from modeler_api.auth import get_verifier
from modeler_api.main import app
from modeler_api.views.common import View
from modeler_intake import synthetic
from modeler_intake.document_reading import name_key
from modeler_intake.mapping.fingerprint import layout_fingerprint
from modeler_intake.source import parse_document, region_grid
from modeler_project import (
    ArtifactKind,
    FileProjectStore,
    Workspace,
    client_data,
    datasets,
    evidence,
    intake_landing,
    intake_pipeline,
)
from modeler_project import intake_review as review
from modeler_project.blinding import redact_dataset
from modeler_project.brief import empty_brief
from modeler_project.dataset_points import card_points
from modeler_project.dataset_register import dataset, propose_dataset
from modeler_project.dataset_register import datasets as all_datasets
from modeler_project.datasets import ObservedDataset, Origin, Series
from modeler_project.evidence import EvidenceState, SourceRef
from modeler_project.intake_rules import RULES_SHA256
from modeler_project.intake_store import IntakeStore
from modeler_project.ledger_models import Entity
from modeler_project.ledger_view import LedgerView
from modeler_project.mapping_cache import MappingCache
from modeler_project.requirements import derive
from modeler_storage.filestore import FileWriteStore

from .test_intake_pipeline_api import _models, _urine_workbook

pytestmark = pytest.mark.req("T-47")

BINARY = "application/octet-stream"
# who a bearer token signs in: a curator with a fresh step-up, the same without one, and a viewer
TOKENS = {"t": (["modeler-curator"], "loa2"), "plain": (["modeler-curator"], "loa1"), "viewer": (["modeler-viewer"], "loa2")}
OUTSIDE_NOTE = "s:'Summary'!A10"            # the workbook's stray note with a number (an outside number)
LOOSE = (b"Time (h),Mean concentration (ng/mL),SD\n0.5,11.5,2.1\n1,24.25,4.4\n2,18.75,3.9\n4,9.5,1.7\n")
FACTS_230_23 = {"route": "oral", "formulation": "ir_tablet", "intended_use": "model_building", "n": 24}
PAGES = ("client-data", "client-review", "reading-queue", "inputs")


class FakeVerifier:
    def verify(self, token):
        roles, acr = TOKENS[token]
        return {"sub": "u1", "name": "Dev User", "tenant_id": "t1", "realm_access": {"roles": roles}, "projects": ["*"],
                "acr": acr, "auth_time": int(time.time())}


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclasses.dataclass
class Project:
    client: TestClient
    store: FileProjectStore
    ws: Workspace
    api: str = "/api/v1/projects/p1"

    def get(self, path: str, token: str = "t", **params: Any):
        return self.client.get(f"{self.api}/{path}", headers=_auth(token), params=params or None)

    def post(self, path: str, body: Any = None, token: str = "t"):
        return self.client.post(f"{self.api}/{path}", headers=_auth(token), json=body)

    def upload(self, *files: tuple[str, bytes]):
        return self.client.post(f"{self.api}/client-data", headers=_auth("t"),
                                files=[("files", (name, data, BINARY)) for name, data in files])

    def settle(self) -> None:
        """Until neither background job runs and no run waits or is being read."""
        for _ in range(6000):
            if not (jobs.running(self.store, "t1", self.ws.project_id, "intake")
                    or jobs.running(self.store, "t1", self.ws.project_id, "reading") or intake_pipeline.unfinished(self.ws)):
                return
            time.sleep(0.01)
        raise AssertionError("the background jobs did not finish")

    def deliver(self, *files: synthetic.SyntheticFile | tuple[str, bytes], preload: bool = True) -> None:
        """The files uploaded as one delivery and read by the intake job. `preload`: each synthetic file's truth specs
        are in the mapping cache, approved (a person signed the layouts off earlier)."""
        given = [(f.name, f.data) if isinstance(f, synthetic.SyntheticFile) else f for f in files]
        if preload:
            _preload(self.ws, [f for f in files if isinstance(f, synthetic.SyntheticFile)])
        assert self.upload(*given).status_code == 201
        self.settle()

    def events(self, action: str | None = None) -> list[Any]:
        return [r.event for r in self.store.audit("t1").records() if action is None or r.event.action == action]

    def page(self, token: str = "t") -> dict[str, Any]:
        answer = self.get("delivery", token)
        assert answer.status_code == 200, answer.text
        return answer.json()["data"]

    def subject(self, label: str) -> str:
        """The path of a subject's card, by its label."""
        row = next(s for s in self.page()["subjects"] if s["label"] == label)
        return f"delivery/subjects/{row['subject_type']}/{row['subject']}"

    def card(self, path: str, token: str = "t") -> dict[str, Any]:
        answer = self.get(path, token)
        assert answer.status_code == 200, answer.text
        return answer.json()["data"]


def _preload(ws: Workspace, files) -> None:
    cache = MappingCache(ws)
    for file in files:
        doc = parse_document(file.data, file.name)
        regions = {r.where: r for r in doc.regions}
        for table in file.tables:
            region = regions[table.where]
            entry = cache.propose(layout_fingerprint(region_grid(doc, region.id)), table.spec, origin="person",
                                  origin_detail="the truth", first_seen=(doc.file_sha256, region.id), by="u1")
            cache.approve(entry.mapping_id, entry.version, by="u1", note="the truth")


@pytest.fixture
def project(tmp_path, api_settings, monkeypatch):
    """`project(mode="both", blinding=False, project_id="p1")`: a new project whose API runs with that intake switch,
    agents off. The store and the read root are one directory, as in a deployment, so a signature's audit event and
    the intake's are on one chain. Dataset and evidence ids follow one seeded sequence per project."""
    monkeypatch.delenv("MODELER_LLM_PROVIDER", raising=False)
    made: list[Project] = []

    def make(mode: str = "both", *, blinding: bool = False, project_id: str = "p1", beside: Project | None = None) -> Project:
        if made:
            made[-1].settle()                 # one project at a time: its jobs are done before the settings change
        if beside is None:
            root = tmp_path / f"{mode}-{len(made)}"
            store = FileProjectStore(root)
            api_settings(read_root=str(root), execution_backend="local", intake_pipeline=mode)
            app.dependency_overrides[get_verifier] = lambda: FakeVerifier()
            app.dependency_overrides[project_api.get_project_store] = lambda: store
        else:                                 # a second project of the same company, in the same store
            root, store = Path(beside.store.root), beside.store
        record = {"id": project_id, "name": project_id.upper(), "compounds": [synthetic.DRUG], "openQuestions": 0,
                  "risk": "medium", "questions": [], "pipeline": True}
        if blinding:
            record["blinding"] = {"on": True, "reason": "external validation is blinded until the MAP is signed"}
        FileWriteStore(str(root)).put_project("t1", record)
        ws = Workspace(store, "t1", project_id)
        brief = empty_brief(synthetic.DRUG, by="u1")
        first = ws.commit(ArtifactKind.BRIEF, "main", brief.to_content(), actor="u1", reason="start")
        ws.commit(ArtifactKind.REQUIREMENTS, "main", derive(brief).to_content(), derived_from=[first.ref], actor="u1",
                  reason="derived")
        seeded = random.Random(7)
        ids = types.SimpleNamespace(uuid4=lambda: uuid.UUID(int=seeded.getrandbits(128), version=4))
        monkeypatch.setattr(datasets, "uuid", ids)
        monkeypatch.setattr(evidence, "uuid", ids)
        made.append(Project(TestClient(app), store, ws, api=f"/api/v1/projects/{project_id}"))
        return made[-1]

    yield make
    for one in made:
        one.settle()
    app.dependency_overrides.clear()


def _accept_note(p: Project, workbook: synthetic.SyntheticFile):
    """The workbook's stray note with a number accepted as not data (it blocks every subject of the delivery)."""
    return p.post("delivery/regions:exclude", {"file_sha256": _sha(workbook.data), "regions": [OUTSIDE_NOTE],
                                               "scope": "outside", "why": "a working note, not data"})


def _decide(p: Project, path: str, facts: dict[str, Any] | None = None) -> dict[str, Any]:
    """A reviewer's decisions on a card, each through its route: the facts no file states entered, each cross-file
    link confirmed, each missing required item disposed, each other failed check overridden. The card after them."""
    for field, value in (facts or {}).items():
        answer = p.post(f"{path}:enter", {"field": field, "value": value, "why": "from the protocol"})
        assert answer.status_code == 200, answer.text
    card = p.card(path)
    for link in card["links"]:
        if link["state"] != "refused":
            answer = p.post(f"{path}:link", {"file_sha256": link["file_sha256"], "link_fact": link["link_fact"],
                                             "confirmed": True, "why": "the same study"})
            assert answer.status_code == 200, answer.text
    card = p.card(path)
    for check in card["checks"]:
        if check["severity"] != "fail" or check["overridden"]:
            continue
        if check["code"] == "REQUIRED_ITEM_UNDISPOSED":
            for item in card["requirements"]:
                if item["status"] == "missing" and item["req_id"] in check["message"]:
                    answer = p.post(f"{path}:dispose", {"req_id": item["req_id"], "disposition": "ask_client", "why": "asked"})
                    assert answer.status_code == 200, answer.text
        else:
            answer = p.post(f"{path}:override", {"check_id": check["id"], "why": "read against the source: as written"})
            assert answer.status_code == 200, answer.text
    return p.card(path)


def _spot_check(p: Project, path: str) -> dict[str, Any]:
    """The spot check drawn and every wanted value ticked ok, in one request."""
    drawn = p.post(f"{path}/spot-check:draw")
    assert drawn.status_code == 200, drawn.text
    draw = drawn.json()["data"]
    ticked = p.post(f"{path}/spot-check", {"draw_id": draw["draw"]["id"],
                                           "ticks": [{"value_id": v, "ok": True} for v in draw["wanted"]]})
    assert ticked.status_code == 200, ticked.text
    return ticked.json()["data"]


def _ready(p: Project, label: str = "230-23", facts: dict[str, Any] | None = None) -> str:
    """The synthetic workbook delivered and one study with nothing left to block its confirmation; its card's path."""
    workbook = synthetic.messy_workbook()
    if not IntakeStore(p.ws).files.entries("file"):
        p.deliver(workbook)
        assert _accept_note(p, workbook).status_code == 200
    path = p.subject(label)
    _decide(p, path, FACTS_230_23 if facts is None else facts)
    _spot_check(p, path)
    return path


# --- the page ---------------------------------------------------------------------------------------------------------


def test_the_page_lists_every_delivery_with_its_files_their_coverage_the_subjects_and_the_request(project):
    p = project()
    workbook, pdf, word = synthetic.messy_workbook(), synthetic.pdf_report(unruled_table=False), synthetic.word_report()
    p.deliver(workbook, pdf, word)
    page = p.page("viewer")                                               # a reader's page
    assert page["enabled"] is True and page["running"] is False and page["agents"]["enabled"] is False
    assert page["rules"] == {"version": "0.1", "status": "UNVERIFIED", "sha256": RULES_SHA256}
    (delivery,) = page["deliveries"]
    assert (delivery["id"], delivery["by"]) == ("dl-1", "u1")
    files = {f["name"]: f for f in delivery["files"]}
    assert set(files) == {workbook.name, pdf.name, word.name}
    for name, file in files.items():
        assert file["state"] == "read" and file["sha256"] and file["legacy_sid"] and not file["repeat"], name
        assert file["run"]["state"] == "done" and file["run"]["error"] == "" and file["blinded"] is False
        # every stage has its time
        assert [s["stage"] for s in file["run"]["stages"]] == list(intake_pipeline.STAGES)
        assert all(s["ok"] and s["seconds"] >= 0 for s in file["run"]["stages"])
        assert file["coverage"]["silent_loss"] == 0 and file["coverage"]["state"] == "read"
        assert len(file["regions"]) == file["coverage"]["regions"]
    # the workbook: every table mapped from the cache by an approved version; its stray note is the one outside number
    book = files[workbook.name]
    assert {(r["kind"], r["state"], r["origin"], r["mapping_status"]) for r in book["regions"]} == {
        ("table", "mapped", "cache", "approved")}
    assert all(r["used"] + r["excluded"] == r["numeric_cells"] and r["silent"] == 0 for r in book["regions"])
    assert [o for o in book["outside"] if o["counted"]] == [
        {"where": OUTSIDE_NOTE, "text": "Note: 3 samples were re-assayed on day 14", "region": None, "counted": True}]
    assert book["coverage"]["outside_numeric"] == 1
    # the PDF's prose is unread and says why (no model); the Word figure is excluded by the rule
    prose = next(r for r in files[pdf.name]["regions"] if r["kind"] == "prose")
    assert (prose["state"], prose["mapping_id"]) == ("unread", None) and "no model is configured" in prose["reason"]
    figure = next(r for r in files[word.name]["regions"] if r["kind"] == "figure")
    assert figure["state"] == "excluded" and figure["reason"].startswith("coverage.excluded_by_rule.figure")
    # the totals are the files' coverage, added up
    covered = [f["coverage"] for f in files.values()]
    totals = page["totals"]
    assert totals["files"] == 3 and totals["files_by_state"] == {"read": 3}
    for name in ("regions", "regions_mapped", "regions_excluded", "regions_unread", "silent_loss", "outside_numeric",
                 "values_unassigned"):
        assert totals[name] == sum(c[name] for c in covered), name
    assert (totals["silent_loss"], totals["outside_numeric"], totals["values_unassigned"]) == (0, 1, 0)
    assert totals["values"] == len(LedgerView(p.ws).values()) > 100
    # the subjects: the studies and the products, with their counts; no blockers (the card computes them)
    subjects = {s["label"]: s for s in page["subjects"]}
    assert {"230-23", "231-24", "230-25", "230-26", "230-27", "Exampleamide IR tablet", "Comparamide tablet"} == set(subjects)
    study = subjects["230-23"]
    assert (study["subject_type"], study["confirm_on"], study["confirmation"], study["loaded_elsewhere"]) == (
        "study", "delivery", None, [])
    assert study["values"] == sum(study["by_level"].values()) == sum(study["by_method"].values()) > 0
    assert study["files"] == [_sha(workbook.data)] and study["deliveries"] == ["dl-1"] and study["blinded"] is False
    assert "blockers" not in study
    assert [a["label"] for a in subjects["230-26"]["arms"]] == ["Cohort 1", "Cohort 2"]
    assert [b["label"] for b in subjects["Exampleamide IR tablet"]["batches"]] == ["L2301"]
    assert page["unassigned"] == [] and page["mappings"] == []
    # the client request: one line per item still to ask for, naming its study or product
    asked = {(line["req_id"], line["what"]) for line in page["request"]}
    assert ("REQ-sys.demographics", "Demographics of every study (age, sex, population, weight) — study 230-23") in asked
    assert any(line["product"] == "Exampleamide IR tablet" for line in page["request"])
    # nobody without a role reads it, and a project the person is no member of is refused as everywhere
    assert p.client.get(f"{p.api}/delivery").status_code == 401


def test_run_queues_files_again_as_new_runs_and_the_page_says_running_until_they_are_read(project):
    p = project()
    workbook, word = synthetic.messy_workbook(), synthetic.word_report()
    p.deliver(workbook, word)
    assert [r.state for r in intake_pipeline.runs(p.ws)] == ["done", "done"]
    # a reader may not; an id that is no sha256 and a file that never arrived are refused, and nothing is queued
    assert p.post("delivery:run", token="viewer").status_code == 403
    assert p.post("delivery:run", {"files": ["../../etc/passwd"]}).status_code == 422
    unknown = p.post("delivery:run", {"files": [_sha(b"never sent")]})
    assert unknown.status_code == 404 and unknown.json()["detail"]["code"] == "UNKNOWN"
    assert len(intake_pipeline.runs(p.ws)) == 2
    # one file named: one new run of it, by the person who asked
    one = p.post("delivery:run", {"files": [_sha(word.data)]})
    assert one.status_code == 202 and one.json()["data"]["status"] in ("RUNNING", "QUEUED")
    p.settle()
    runs = intake_pipeline.runs(p.ws)
    assert [(r.sha256, r.state, r.by) for r in runs[2:]] == [(_sha(word.data), "done", "u1")]
    # none named: every file of the project
    assert p.post("delivery:run").status_code == 202
    p.settle()
    runs = intake_pipeline.runs(p.ws)
    assert sorted(r.sha256 for r in runs[3:]) == sorted([_sha(workbook.data), _sha(word.data)])
    assert all(r.state == "done" for r in runs) and len(p.events("intake.run")) == 5
    # the same bytes under the same mappings: nothing new in the ledger, and the page shows each file's latest run
    page = p.page()
    assert page["running"] is False and page["totals"]["files"] == 2
    assert {f["run"]["run_id"] for f in page["deliveries"][0]["files"]} == {r.run_id for r in runs[3:]}


def test_the_page_says_running_while_a_run_waits(project):
    p = project()
    word = synthetic.word_report()
    p.deliver(word)
    record = intake_landing.file_records(IntakeStore(p.ws))[_sha(word.data)]
    (queued,) = intake_pipeline.enqueue(p.ws, [record], by="u1", again=True)   # queued, and no job started for it yet
    assert intake_pipeline.pending(p.ws)
    # the page starts the job for a run that waits, says so, and shows the file as waiting until its run is done
    seen = [p.page()]
    while seen[-1]["running"]:
        time.sleep(0.01)
        seen.append(p.page())
    assert seen[0]["running"] is True and seen[-1]["running"] is False
    assert seen[-1]["deliveries"][0]["files"][0]["run"]["run_id"] == queued.run_id
    assert seen[-1]["deliveries"][0]["files"][0]["state"] == "read"
    waiting = [f for page in seen for d in page["deliveries"] for f in d["files"] if f["state"] == "waiting"]
    assert all(f["run"]["state"] in ("queued", "running") and f["reason"] for f in waiting)


# --- a study: reviewed, spot-checked, signed and landed -----------------------------------------------------------------


@pytest.mark.req("T-47", "F-404", "T-05")
def test_a_studys_card_shows_exceptions_first_and_each_decision_is_one_audited_line(project):
    p = project()
    workbook = synthetic.messy_workbook()
    p.deliver(workbook)
    path = p.subject("230-23")
    card = p.card(path, "viewer")
    assert (card["subject_type"], card["label"], card["blinded"], card["confirm_on"]) == ("study", "230-23", False, "delivery")
    assert card["rules"]["status"] == "UNVERIFIED" and card["confirmation"] is None and "signature" not in card
    # exceptions first: the blockers, the schema gap, the failed checks before the rest, the missing item before the found
    assert [b["code"] for b in card["blockers"]] == ["OUTSIDE_NUMBERS", "SCHEMA_GAP", "CHECK_FAILED", "SPOT_CHECK"]
    assert [(g["tag"], g["reason"]) for g in card["gaps"]] == [("route", "no route is stated for this study")]
    severities = [c["severity"] for c in card["checks"]]
    assert severities == sorted(severities, key=("fail", "warn", "info").index) and severities[0] == "fail"
    assert {c["code"] for c in card["checks"] if c["severity"] == "fail"} == {
        "LANDING_FIELD_MISSING", "ABOVE_RANGE", "REQUIRED_ITEM_UNDISPOSED"}
    assert [(r["req_id"], r["status"]) for r in card["requirements"]] == [
        ("REQ-sys.demographics", "missing"), ("REQ-obs.bioanalytical", "found")]
    assert card["conflicts"] == [] and card["links"] == [] and card["mappings"] == []
    # what the landing would hold back, or why it cannot be planned yet
    assert card["held"] == [] and "the study record needs n" in card["landing_problem"]
    assert card["spot_check"] == {"state": "none", "draw_id": None, "drawn": 0, "wanted": 0}
    # its values by table, each with the tuple it is read with and its source reference
    tables = {t["id"]: t for t in card["tables"]}
    assert sum(len(t["values"]) for t in tables.values()) == card["values"]
    individual = next(t for t in tables.values() if t["table_kind"] == "pk_individual")
    assert (individual["kind"], individual["file"], individual["mapping_status"], individual["waiting"]) == (
        "table", workbook.name, "approved", False)
    value = next(v for v in individual["values"] if v["verbatim"] == "25.2")
    assert (value["value"], value["unit"], value["time"], value["time_unit"], value["statistic"]) == (25.2, "ng/mL", 2.0, "h", "individual")
    assert value["labels"] == {"study": "230-23", "analyte": synthetic.DRUG, "subject": "001", "matrix": "plasma"}
    assert value["anchor"].startswith(_sha(workbook.data)) and set(value["locators"]) >= {"time", "unit", "subject", "study"}
    assert (value["level"], value["status"], value["censored"], value["blinded"]) == ("approved_mapping", "proposed", False, False)
    assert any(v["censored"] and v["value"] is None and v["lloq"] == 0.5 for v in individual["values"])   # a BLQ value
    facts = next(t for t in tables.values() if t["kind"] == "facts")
    assert {v["field"] for v in facts["values"]} >= {"dose", "food_state", "lloq"}

    # --- refusals: nothing is written ---
    head = IntakeStore(p.ws).review.head()
    failed = next(c for c in card["checks"] if c["code"] == "ABOVE_RANGE")
    required = next(c for c in card["checks"] if c["code"] == "REQUIRED_ITEM_UNDISPOSED")
    body = {"check_id": failed["id"], "why": "read against the source: as written"}
    assert p.post(f"{path}:override", body, token="viewer").status_code == 403
    assert p.post(f"{path}:override", {"check_id": failed["id"], "why": ""}).status_code == 422       # a reason is asked
    assert p.post(f"{path}:override", {"check_id": "../ck-1", "why": "x"}).status_code == 422
    assert p.post(f"{path}:override", {"check_id": "ck-0123456789ab", "why": "x"}).status_code == 404
    settled = p.post(f"{path}:override", {"check_id": required["id"], "why": "x"})                     # a disposition settles it
    assert settled.status_code == 409 and settled.json()["detail"]["code"] == "CONFLICT"
    assert p.post(f"{path}:dispose", {"req_id": "REQ-not.an.item", "disposition": "ask_client", "why": "x"}).status_code == 404
    assert p.post(f"{path}:dispose", {"req_id": "REQ-sys.demographics", "disposition": "ignore", "why": "x"}).status_code == 422
    assert p.post(f"{path}:enter", {"field": "not_a_field", "value": 1, "why": "x"}).status_code == 422
    assert p.post(f"{path}:enter", {"field": "route", "value": "oral", "why": "x", "supersedes": "f-99999"}).status_code == 404
    assert p.post(f"{path}:enter", {"field": "route", "value": "oral", "why": "x", "arm": "arm-99999"}).status_code == 404
    assert p.post(f"{path}:choose", {"conflict_id": "cx-0123456789", "keep": "f-1", "why": "x"}).status_code == 404
    assert p.post(f"{path}:link", {"file_sha256": _sha(workbook.data), "confirmed": True}).status_code == 404
    assert p.post("delivery/subjects/study/st-99999:override", body).status_code == 404
    assert p.post("delivery/subjects/study/not an id:override", body).status_code == 422
    assert p.post("delivery/subjects/batch/ba-6:override", body).status_code == 422                    # not a subject type
    assert p.get("delivery/subjects/product/" + path.rsplit("/", 1)[1]).status_code == 404            # a study is no product
    assert IntakeStore(p.ws).review.head() == head and p.events("intake.override") == []

    # --- the decisions, each one line and one audit event with the line's hash ---
    done = p.post(f"{path}:override", body).json()["data"]
    assert next(c for c in done["checks"] if c["id"] == failed["id"])["overridden"] is True
    assert done["checks"][-1]["id"] == failed["id"] or not done["checks"][0]["overridden"]            # a cleared check sinks
    done = p.post(f"{path}:dispose", {"req_id": "REQ-sys.demographics", "disposition": "ask_client", "why": "asked"}).json()["data"]
    assert next(r for r in done["requirements"] if r["req_id"] == "REQ-sys.demographics")["status"] == "ask_client"
    assert all(c["overridden"] for c in done["checks"] if c["id"] == required["id"])        # settled: cleared, or gone
    assert "REQUIRED_ITEM_UNDISPOSED" not in {c["code"] for c in done["checks"] if not c["overridden"]}
    done = p.post(f"{path}:enter", {"field": "route", "value": "oral", "why": "from the protocol"}).json()["data"]
    assert done["gaps"] == [] and "SCHEMA_GAP" not in [b["code"] for b in done["blockers"]]
    entered = next(v for t in done["tables"] if t["id"] == "facts:entered" for v in t["values"] if v["field"] == "route")
    assert (entered["value"], entered["method"], entered["level"], entered["anchor"]) == ("oral", "person", "person_confirmed", None)
    lines = {e.kind: e for e in IntakeStore(p.ws).review.entries()}
    for action, kind in (("intake.override", "override"), ("intake.disposition", "disposition")):
        (event,) = p.events(action)
        assert event.after["row_hash"] == lines[kind].hash and event.actor == "u1" and event.resource_type == "intake"
    (entry,) = p.events("intake.entry")
    assert entry.after["fact"] == entered["id"] and entry.reason == "from the protocol"
    # a correction supersedes the value it names and keeps its place; the old value stays readable
    old = next(v for v in individual["values"] if v["verbatim"] == "25.2")
    fixed = p.post(f"{path}:enter", {"value": 25.4, "supersedes": old["id"], "why": "a typing error in the file"})
    assert fixed.status_code == 200, fixed.text
    new = next(v for t in fixed.json()["data"]["tables"] for v in t["values"] if v["value"] == 25.4)
    assert (new["time"], new["labels"]["subject"], new["unit"], new["method"]) == (2.0, "001", "ng/mL", "person")
    assert old["id"] not in {v["id"] for t in fixed.json()["data"]["tables"] for v in t["values"]}
    assert LedgerView(p.ws).value(old["id"]).status == "superseded"


@pytest.mark.req("T-47", "F-403", "T-06", "F-404", "T-05")
def test_the_spot_check_is_drawn_ticked_once_in_one_request_and_the_confirmation_is_signed_and_landed(project):
    p = project()
    workbook = synthetic.messy_workbook()
    p.deliver(workbook)
    assert _accept_note(p, workbook).status_code == 200
    path = p.subject("230-23")
    card = _decide(p, path, FACTS_230_23)
    assert [b["code"] for b in card["blockers"]] == ["SPOT_CHECK"] and card["landing_problem"] is None

    # --- the spot check ---
    assert p.post(f"{path}/spot-check:draw", token="viewer").status_code == 403
    spot = p.post(f"{path}/spot-check:draw").json()["data"]
    draw = spot["draw"]
    assert spot["state"] == "drawn" and spot["record"] is None and spot["blinded"] is False
    assert spot["wanted"] == [*draw["always"], *draw["sampled"]] and draw["carried"] == {}
    assert set(draw["heads"]) == {"facts", "entities", "mappings", "review", "rules"} and draw["heads"]["rules"] == RULES_SHA256
    assert [v["value"]["id"] for v in spot["values"]] == spot["wanted"]
    # each value with the tuple it is ticked for and its source reference; the dose is always verified
    dose = next(v for v in spot["values"] if v["value"]["field"] == "dose")
    assert dose["reason"] == "always:field" and dose["wanted"] and dose["ok"] is None
    assert (dose["value"]["value"], dose["value"]["unit"], dose["value"]["labels"]["study"]) == (50.0, "mg", "230-23")
    assert dose["value"]["anchor"] and p.get("delivery/source", value=dose["value"]["id"]).status_code == 200
    person = next(v for v in spot["values"] if v["value"]["method"] == "person")      # a person's entry has no source
    assert person["value"]["anchor"] is None and person["reason"] and person["inputs"] == []
    assert p.get("delivery/source", value=person["value"]["id"]).status_code == 404
    assert p.post(f"{path}/spot-check:draw").json()["data"]["draw"] == draw            # the same state: the same draw
    assert p.card(path)["spot_check"] == {"state": "drawn", "draw_id": draw["id"], "drawn": len(spot["wanted"]),
                                         "wanted": len(spot["wanted"])}
    ticks = [{"value_id": v, "ok": True} for v in spot["wanted"]]
    # refused: a reader, another subject's draw, a draw that is none, ticks that are not every value once
    other = p.subject("231-24")
    assert p.post(f"{path}/spot-check", {"draw_id": draw["id"], "ticks": ticks}, token="viewer").status_code == 403
    assert p.post(f"{other}/spot-check", {"draw_id": draw["id"], "ticks": ticks}).status_code == 404
    assert p.post(f"{path}/spot-check", {"draw_id": "sd-99999", "ticks": ticks}).status_code == 404
    assert p.post(f"{path}/spot-check", {"draw_id": "../sd-1", "ticks": ticks}).status_code == 422
    assert p.post(f"{path}/spot-check", {"draw_id": draw["id"], "ticks": ticks[:-1]}).status_code == 422
    assert p.post(f"{path}/spot-check", {"draw_id": draw["id"], "ticks": [*ticks, ticks[0]]}).status_code == 422
    assert p.events("intake.spot_check") == []

    # --- nothing is signed while a blocker exists (the spot check is not ticked yet) ---
    blocked = p.post(f"{path}:confirm")
    assert blocked.status_code == 409 and blocked.json()["detail"]["code"] == "SPOT_CHECK"
    assert [b["code"] for b in blocked.json()["detail"]["blockers"]] == ["SPOT_CHECK"]
    assert p.events("signature.create") == [] and review.confirmations(p.ws) == []

    # every tick in one request, accepted once
    ticked = p.post(f"{path}/spot-check", {"draw_id": draw["id"], "ticks": ticks})
    assert ticked.status_code == 200 and ticked.json()["data"]["state"] == "complete"
    assert ticked.json()["data"]["wanted"] == [] and all(v["ok"] for v in ticked.json()["data"]["values"])
    assert p.post(f"{path}/spot-check", {"draw_id": draw["id"], "ticks": ticks}).status_code == 200    # the same again: one line
    changed = [{**ticks[0], "ok": False}, *ticks[1:]]
    assert p.post(f"{path}/spot-check", {"draw_id": draw["id"], "ticks": changed}).status_code == 409
    (event,) = p.events("intake.spot_check")
    assert (event.after["ok"], event.after["not_ok"], event.after["draw"]) == (len(ticks), 0, draw["id"])
    card = p.card(path)
    assert card["blockers"] == [] and card["spot_check"]["state"] == "complete" and card["spot_check"]["wanted"] == 0

    # --- the confirmation: a writer, with a step-up ---
    assert p.post(f"{path}:confirm", token="viewer").status_code == 403
    refused = p.post(f"{path}:confirm", token="plain")
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "STEP_UP_REQUIRED"
    assert p.events("signature.create") == [] and review.confirmations(p.ws) == [] and all_datasets(p.ws) == []
    signed = p.post(f"{path}:confirm")
    assert signed.status_code == 200, signed.text
    done = signed.json()["data"]
    (confirmation,) = review.confirmations(p.ws)
    assert done["signature"] == {"signature_id": confirmation.signature_id, "manifestation": confirmation.manifestation}
    assert re.fullmatch(r"Dev User \| Reviewed \| \d{4}-\d\d-\d\d \d\d:\d\d:\d\d UTC", confirmation.manifestation)
    shown = done["confirmation"]
    assert (shown["id"], shown["by"], shown["printed_name"], shown["record_sha256"]) == (
        confirmation.id, "u1", "Dev User", confirmation.record_sha256)
    assert shown["current"] is True and shown["rules"] == {"version": "0.1", "status": "UNVERIFIED", "sha256": RULES_SHA256}
    assert shown["coverage"] == {"files": 1, "silent_loss": 0, "regions_unread": 0, "outside_numeric": 0, "values_unassigned": 0}
    assert shown["held"] == card["held"] and shown["landed"]["pending"] == card["held"]
    # the three events, in order, each binding the next: the signature the record's hash, the confirmation the
    # signature and its line, the landing the confirmation and its line
    mine = [e for e in p.events() if e.action in ("signature.create", "intake.confirm", "intake.land")]
    assert [e.action for e in mine] == ["signature.create", "intake.confirm", "intake.land"]
    signature, confirm, land = mine
    study_id = path.rsplit("/", 1)[1]
    assert (signature.resource_type, signature.resource_id) == ("intake-confirmation", f"p1/delivery/study/{study_id}")
    assert signature.after == {"signature_id": confirmation.signature_id, "record_sha256": confirmation.record_sha256,
                               "meaning": "Reviewed", "auth_method": "oidc:loa2"}
    assert signature.reason == confirmation.manifestation and signature.actor == "u1"
    lines = {e.kind: e for e in IntakeStore(p.ws).review.entries() if e.kind in ("confirmation", "landed")}
    assert confirm.after == {"confirmation": confirmation.id, "record_sha256": confirmation.record_sha256,
                             "signature_id": confirmation.signature_id, "row_hash": lines["confirmation"].hash}
    assert land.after["confirmation"] == confirmation.id and land.after["row_hash"] == lines["landed"].hash
    assert p.store.audit("t1").verify() is None and IntakeStore(p.ws).review.verify() == []
    # landed: the study's datasets, accepted, named after the confirmation and its signature
    landed = [dataset(p.ws, i) for i in shown["landed"]["datasets"]]
    assert len(landed) == 2 and land.after["datasets"] == shown["landed"]["datasets"]
    for found in landed:
        assert found.state is EvidenceState.ACCEPTED and found.origin is Origin.CLIENT
        assert found.decision_reason == f"confirmed on Delivery ({confirmation.id}, signature {confirmation.signature_id})"
        assert found.study["study_id"] == "230-23" and found.study["n"] == 24 and found.study["route"] == "oral"
    assert all(v["status"] == "confirmed" and v["confirmation"] == confirmation.id
               for t in done["tables"] for v in t["values"])
    row = next(s for s in p.page()["subjects"] if s["label"] == "230-23")
    assert row["confirmation"]["landed"] is True and row["confirmation"]["current"] is True
    assert row["confirmation"]["signature_id"] == confirmation.signature_id
    # the same record confirmed again: nothing is signed twice, nothing lands twice
    again = p.post(f"{path}:confirm", token="plain")
    assert again.status_code == 200 and again.json()["data"]["signature"] == done["signature"]
    assert len(p.events("signature.create")) == len(p.events("intake.confirm")) == len(p.events("intake.land")) == 1
    assert len(review.confirmations(p.ws)) == 1
    # the legacy card shows the landed profile with the BLQ rule it is judged with and how many points it leaves out
    groups = p.get("client-review").json()["data"]["groups"]
    shown_points = [item["data"] for g in groups for item in g["items"] if item["id"] in shown["landed"]["datasets"]]
    assert shown_points and all(d["blq_rule"] == "omit" and d["blq_omitted"] == sum(
        1 for s in d["series"] for v in s["values"] if v is None) for d in shown_points)
    assert any(d["blq_omitted"] > 0 for d in shown_points)


@pytest.mark.req("T-47", "F-403", "T-06")
def test_nothing_is_signed_while_a_blocker_exists_whoever_asks(project):
    p = project()
    workbook = synthetic.messy_workbook()
    p.deliver(workbook)
    path = p.subject("230-23")
    # with a step-up and without one: the blockers answer first, each with its code, and nothing is signed
    for token in ("t", "plain"):
        refused = p.post(f"{path}:confirm", token=token)
        assert refused.status_code == 409 and refused.json()["detail"]["code"] == "CONFIRMATION_REFUSED"
        assert [b["code"] for b in refused.json()["detail"]["blockers"]] == [
            "OUTSIDE_NUMBERS", "SCHEMA_GAP", "CHECK_FAILED", "SPOT_CHECK"]
    # each blocker cleared in turn still leaves the confirmation refused until none is left
    assert _accept_note(p, workbook).status_code == 200
    _decide(p, path, FACTS_230_23)
    last = p.post(f"{path}:confirm")
    assert last.status_code == 409 and [b["code"] for b in last.json()["detail"]["blockers"]] == ["SPOT_CHECK"]
    # a failed tick blocks too: the value does not match its source
    draw = p.post(f"{path}/spot-check:draw").json()["data"]
    ticks = [{"value_id": v, "ok": i > 0, "note": "" if i else "the file says 52"} for i, v in enumerate(draw["wanted"])]
    assert p.post(f"{path}/spot-check", {"draw_id": draw["draw"]["id"], "ticks": ticks}).json()["data"]["state"] == "failed"
    failed = p.post(f"{path}:confirm")
    assert failed.status_code == 409 and failed.json()["detail"]["code"] == "SPOT_CHECK"
    assert p.events("signature.create") == [] and p.events("intake.confirm") == [] and p.events("intake.land") == []
    assert review.confirmations(p.ws) == [] and all_datasets(p.ws) == []
    # a subject with no value has nothing to sign
    empty = p.post("delivery/subjects/compound/compound:confirm")
    assert empty.status_code == 409 and empty.json()["detail"]["code"] == "CONFLICT"
    assert p.events("signature.create") == []


@pytest.mark.req("T-47", "F-403", "T-06", "F-404", "T-05")
def test_an_interrupted_landing_completes_on_a_second_confirm_with_no_new_signature(project, monkeypatch):
    p = project()
    path = _ready(p)
    real = intake_landing.land
    calls: list[str] = []

    def stopped(ws, library, confirmation, plan, *, by):
        calls.append(confirmation.id)
        if len(calls) == 1:                       # the process stops after the confirmation's line, before the landing
            raise RuntimeError("the worker was restarted")
        return real(ws, library, confirmation, plan, by=by)

    monkeypatch.setattr(intake_landing, "land", stopped)
    with pytest.raises(RuntimeError, match="restarted"):
        p.post(f"{path}:confirm")
    (confirmation,) = review.confirmations(p.ws)
    assert [len(p.events(a)) for a in ("signature.create", "intake.confirm", "intake.land")] == [1, 1, 0]
    assert all_datasets(p.ws) == [] and review.landed(p.ws, confirmation.id) is None
    # the card says it: signed, not landed
    card = p.card(path)
    assert card["confirmation"]["id"] == confirmation.id and card["confirmation"]["landed"] is None
    assert next(s for s in p.page()["subjects"] if s["label"] == "230-23")["confirmation"]["landed"] is False
    # the second confirm lands it: no step-up is asked, no signature is made, the first one stands
    second = p.post(f"{path}:confirm", token="plain")
    assert second.status_code == 200, second.text
    done = second.json()["data"]
    assert done["signature"] == {"signature_id": confirmation.signature_id, "manifestation": confirmation.manifestation}
    assert [len(p.events(a)) for a in ("signature.create", "intake.confirm", "intake.land")] == [1, 1, 1]
    assert calls == [confirmation.id, confirmation.id] and len(review.confirmations(p.ws)) == 1
    landed = done["confirmation"]["landed"]["datasets"]
    assert len(landed) == 2 and all(dataset(p.ws, i).state is EvidenceState.ACCEPTED for i in landed)
    assert all(dataset(p.ws, i).decision_reason.endswith(f"signature {confirmation.signature_id})") for i in landed)
    # a landing the code refuses after the signature answers 409 and says how to complete it
    monkeypatch.setattr(intake_landing, "land", lambda *a, **k: (_ for _ in ()).throw(intake_landing.LandingError("no")))
    other = _ready(p, "231-24", {"route": "oral", "formulation": "ir_tablet", "intended_use": "model_building", "n": 12})
    refused = p.post(f"{other}:confirm")
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "LANDING_INCOMPLETE"
    assert "no new signature" in refused.json()["detail"]["message"] and len(p.events("signature.create")) == 2
    monkeypatch.setattr(intake_landing, "land", real)
    assert p.post(f"{other}:confirm", token="plain").status_code == 200
    assert len(p.events("signature.create")) == 2 and len(p.events("intake.land")) == 2


# --- a product and the compound ---------------------------------------------------------------------------------------------


@pytest.mark.req("T-47", "F-403", "T-06", "F-404", "T-05")
def test_a_product_is_reviewed_and_confirmed_and_its_dissolution_lands_through_the_register(project):
    p = project()
    workbook = synthetic.messy_workbook()
    p.deliver(workbook)
    path = p.subject("Exampleamide IR tablet")
    card = p.card(path)
    assert (card["subject_type"], card["label"], card["gaps"], card["links"]) == ("product", "Exampleamide IR tablet", [], [])
    assert [b["code"] for b in card["blockers"]] == ["OUTSIDE_NUMBERS", "CHECK_FAILED", "SPOT_CHECK"]
    assert [(r["req_id"], r["scope"], r["status"]) for r in card["requirements"]] == [
        ("REQ-form.release@exampleamide-ir-tablet", "product", "missing")]
    assert {t["table_kind"] for t in card["tables"] if t["kind"] == "table"} >= {"dissolution"}
    assert any("only dissolution lands" in text for text in card["held"]) and card["landing_problem"] is None
    # refusals of a product's card: an arm is a study's, a link joins a study, a batch must be this product's
    assert p.post(f"{path}:enter", {"field": "strength_mg", "value": 50, "why": "x", "arm": "arm-1"}).status_code == 422
    assert p.post(f"{path}:link", {"file_sha256": _sha(workbook.data), "confirmed": True}).status_code == 422
    assert p.post(f"{path}:enter", {"field": "strength_mg", "value": 50, "why": "x", "batch": "ba-8"}).status_code == 422
    assert p.post(f"{path}:confirm").status_code == 409 and p.events("signature.create") == []
    # reviewed through the routes, then signed
    assert _accept_note(p, workbook).status_code == 200
    card = _decide(p, path)
    assert [b["code"] for b in card["blockers"]] == ["SPOT_CHECK"]
    assert _spot_check(p, path)["state"] == "complete"
    assert p.post(f"{path}:confirm", token="plain").json()["detail"]["code"] == "STEP_UP_REQUIRED"
    signed = p.post(f"{path}:confirm")
    assert signed.status_code == 200, signed.text
    done = signed.json()["data"]
    assert done["signature"]["manifestation"].startswith("Dev User | Reviewed | ")
    landed = done["confirmation"]["landed"]
    assert landed["dissolution_records"] > 0 and landed["datasets"] == [] and landed["pending"] == card["held"]
    (signature,) = p.events("signature.create")
    assert signature.resource_id == f"p1/{path.replace('subjects/', '')}" and signature.resource_type == "intake-confirmation"
    assert [len(p.events(a)) for a in ("intake.confirm", "intake.land")] == [1, 1]
    # its dissolution profiles are in the register, from the client's file
    profiles = p.get("client-data").json()["data"]["dissolution"]["profiles"]
    assert profiles and {str(prof.get("product", prof.get("formulation", ""))) for prof in profiles}


@pytest.mark.req("T-47", "F-403", "T-06", "F-404", "T-05")
def test_the_compound_has_its_own_card_spot_check_and_signature(project):
    p = project()
    p.deliver(synthetic.messy_workbook())
    path = "delivery/subjects/compound/compound"
    assert "compound" not in {s["subject_type"] for s in p.page()["subjects"]}       # no compound value yet: no row
    card = p.card(path)
    assert (card["subject_type"], card["subject"], card["label"], card["values"]) == ("compound", "compound", "compound", 0)
    assert card["requirements"] == [] and card["tables"] == [] and card["confirmation"] is None
    assert p.get("delivery/subjects/compound/st-1").status_code == 404                # the compound's id is "compound"
    assert p.post(f"{path}/spot-check:draw").status_code == 200                       # an empty draw, and nothing to sign
    assert p.post(f"{path}:confirm").json()["detail"]["code"] == "CONFLICT"
    # a compound-level value entered by a person; a study's field is not the compound's
    assert p.post(f"{path}:enter", {"field": "dose", "value": 50, "unit": "mg", "why": "x"}).status_code == 422
    assert p.post(f"{path}:dispose", {"req_id": "REQ-phys.logp", "disposition": "literature", "why": "x"}).status_code == 404
    entered = p.post(f"{path}:enter", {"field": "phys.logp", "value": 2.4, "why": "the certificate of analysis says so"})
    assert entered.status_code == 200, entered.text
    card = entered.json()["data"]
    (table,) = card["tables"]
    (value,) = table["values"]
    assert (table["id"], value["field"], value["value"], value["method"], value["labels"]) == (
        "facts:entered", "phys.logp", 2.4, "person", {})
    row = next(s for s in p.page()["subjects"] if s["subject_type"] == "compound")
    assert (row["subject"], row["label"], row["values"], row["confirm_on"], row["files"]) == ("compound", "compound", 1, "delivery", [])
    card = _decide(p, path)
    assert [b["code"] for b in card["blockers"]] == ["SPOT_CHECK"]
    spot = _spot_check(p, path)
    assert spot["state"] == "complete" and [v["value"]["id"] for v in spot["values"]] == [value["id"]]
    assert p.post(f"{path}:confirm", token="plain").json()["detail"]["code"] == "STEP_UP_REQUIRED"
    signed = p.post(f"{path}:confirm")
    assert signed.status_code == 200, signed.text
    done = signed.json()["data"]
    (confirmation,) = review.confirmations(p.ws)
    assert (confirmation.subject_type, confirmation.subject) == ("compound", "compound")
    assert done["signature"]["signature_id"] == confirmation.signature_id
    (signature,) = p.events("signature.create")
    assert signature.resource_id == "p1/delivery/compound/compound" and signature.after["record_sha256"] == confirmation.record_sha256
    assert [len(p.events(a)) for a in ("intake.confirm", "intake.land")] == [1, 1]
    landed = done["confirmation"]["landed"]
    assert landed["datasets"] == [] and (landed["evidence"] or landed["pending"])     # evidence, proposed or held: listed


# --- conflicts and cross-file links ---------------------------------------------------------------------------------------


def _late_samples() -> tuple[str, bytes]:
    """A second workbook that names study 230-23 in its title: its values join that study across files."""
    book = Workbook()
    sheet = book.active
    sheet.title = "Late"
    sheet.append(["Study 230-23, 50 mg, fasted"])
    sheet.append(["Time (h)", "Mean concentration (ng/mL)", "SD"])
    for row in ((36, 1.25, 0.4), (48, 0.75, 0.2), (72, 0.55, 0.1)):
        sheet.append(row)
    raw = io.BytesIO()
    book.save(raw)
    return "late-samples.xlsx", raw.getvalue()


@pytest.mark.req("T-47", "F-404", "T-05")
def test_a_cross_file_link_is_confirmed_or_refused_and_a_conflict_is_settled_by_a_choice(project):
    p = project()
    p.deliver(synthetic.messy_workbook())
    late = _late_samples()
    p.deliver(late, preload=False)
    path = p.subject("230-23")
    card = p.card(path)
    (link,) = card["links"]
    assert (link["state"], link["file"], link["study_label"], link["values"] > 0) == ("unconfirmed", late[0], "230-23", True)
    assert link["candidates"] == [{"id": card["subject"], "label": "230-23"}]
    assert "LINK_UNCONFIRMED" in [b["code"] for b in card["blockers"]]
    joined = [v for t in card["tables"] if t["file"] == late[0] for v in t["values"]]
    assert joined and all(v["cross_file"] for v in joined)
    # the rule's mapping of the late table is new: it waits for a person, on the card and on the page
    (waiting,) = card["mappings"]
    assert (waiting["status"], waiting["origin"], waiting["used_in"][0]["file"]) == ("proposed", "rule", late[0])
    assert [m["mapping_id"] for m in p.page()["mappings"]] == [waiting["mapping_id"]]
    # refusals: a file with no link, a study the link does not name, refusing without a reason
    body = {"file_sha256": link["file_sha256"], "link_fact": link["link_fact"], "confirmed": True}
    assert p.post(f"{path}:link", body, token="viewer").status_code == 403
    assert p.post(f"{path}:link", {**body, "file_sha256": "not-a-sha"}).status_code == 422
    assert p.post(f"{path}:link", {**body, "file_sha256": _sha(b"another file")}).status_code == 404
    other = p.subject("231-24").rsplit("/", 1)[1]
    assert p.post(f"{path}:link", {**body, "study": other}).status_code == 422
    assert p.post(f"{path}:link", {**body, "confirmed": False}).status_code == 422
    assert p.events("intake.link") == []
    # confirmed: the link no longer blocks; refused with a reason: the file's values leave the study
    confirmed = p.post(f"{path}:link", {**body, "why": "the same study"}).json()["data"]
    assert "LINK_UNCONFIRMED" not in [b["code"] for b in confirmed["blockers"]]
    assert confirmed["links"] == []                                                         # nothing waits any more
    refused = p.post(f"{path}:link", {**body, "confirmed": False, "why": "another protocol"})
    assert refused.status_code == 200, refused.text
    assert [link["state"] for link in refused.json()["data"]["links"]] == ["refused"]
    assert not [v for t in refused.json()["data"]["tables"] if t["file"] == late[0] for v in t["values"]]
    events = p.events("intake.link")
    assert len(events) == 2 and events[1].reason == "another protocol"
    lines = IntakeStore(p.ws).review.entries("link")
    assert [e.after["row_hash"] for e in events] == [line.hash for line in lines]

    # --- a conflict: a person enters another dose than the file states ---
    entered = p.post(f"{path}:enter", {"field": "dose", "value": 60, "unit": "mg", "why": "the protocol says 60 mg"}).json()["data"]
    (conflict,) = entered["conflicts"]
    assert (conflict["field"], conflict["kind"], conflict["labels"]) == ("dose", "value", {"study": "230-23"})
    assert "CONFLICT_OPEN" in {c["code"] for c in entered["checks"] if c["severity"] == "fail"}
    values = {v["id"]: v for t in entered["tables"] for v in t["values"]}
    mine = next(i for i in conflict["values"] if values[i]["method"] == "person")
    file_value = next(i for i in conflict["values"] if values[i]["method"] != "person")
    choice = {"conflict_id": conflict["id"], "keep": mine, "why": "the protocol governs"}
    assert p.post(f"{path}:choose", choice, token="viewer").status_code == 403
    assert p.post(f"{path}:choose", {**choice, "keep": "f-99999"}).status_code == 422       # not one of its values
    assert p.post(f"{path}:choose", {**choice, "keep": "../f-1"}).status_code == 422
    assert p.post(f"{p.subject('231-24')}:choose", choice).status_code == 404               # another study's card
    assert p.events("intake.choice") == []
    chosen = p.post(f"{path}:choose", choice)
    assert chosen.status_code == 200, chosen.text
    after = chosen.json()["data"]
    assert after["conflicts"] == [] and "CONFLICT_OPEN" not in {c["code"] for c in after["checks"]}
    kept = {v["id"] for t in after["tables"] for v in t["values"]}
    assert mine in kept and file_value not in kept and LedgerView(p.ws).value(file_value).status == "excluded"
    (event,) = p.events("intake.choice")
    assert event.after["row_hash"] == IntakeStore(p.ws).review.entries("choice")[0].hash and event.reason == "the protocol governs"


# --- the "study not stated" values, what is not data, and the mappings ---------------------------------------------------------


@pytest.mark.req("T-47", "F-404", "T-05")
def test_study_not_stated_values_are_assigned_or_their_table_is_excluded_and_the_coverage_follows(project):
    p = project()
    workbook = synthetic.messy_workbook()
    p.deliver(workbook, ("loose-profile.csv", LOOSE))
    loose = _sha(LOOSE)
    page = p.page()
    assert page["totals"]["values_unassigned"] == 4 and len(page["unassigned"]) == 4
    first = page["unassigned"][0]
    assert (first["field"], first["value"], first["unit"], first["time"], first["statistic"], first["spread"]) == (
        "concentration", 11.5, "ng/mL", 0.5, "arithmetic_mean", 2.1)
    assert first["labels"] == {} and first["file"] == "loose-profile.csv" and first["blinded"] is False
    assert p.get("delivery/source", value=first["id"]).status_code == 200                # its source is one click away
    file = next(f for d in page["deliveries"] for f in d["files"] if f["sha256"] == loose)
    (region,) = file["regions"]
    assert (region["state"], region["origin"], region["mapping_status"]) == ("mapped", "rule", "proposed")
    # every subject of the delivery is blocked until they are assigned or excluded
    study_path = p.subject("231-24")
    study = study_path.rsplit("/", 1)[1]
    assert "UNASSIGNED_VALUES" in [b["code"] for b in p.card(study_path)["blockers"]]
    extract = first["id"].split("#")[0]
    body = {"targets": [extract], "study": study, "why": "the fed arm, per the client's e-mail"}
    # refusals: a reader, no reason, an id that is none, a study that is none, no subject named
    assert p.post("delivery/values:assign", body, token="viewer").status_code == 403
    assert p.post("delivery/values:assign", {**body, "why": ""}).status_code == 422
    assert p.post("delivery/values:assign", {**body, "targets": ["../../ledger/facts"]}).status_code == 422
    assert p.post("delivery/values:assign", {**body, "targets": ["tx-0123456789abcdef"]}).status_code == 404
    assert p.post("delivery/values:assign", {**body, "study": "st-99999"}).status_code == 404
    assert p.post("delivery/values:assign", {**body, "study": "x/../y"}).status_code == 422
    assert p.post("delivery/values:assign", {"targets": [extract], "why": "x"}).status_code == 422
    assert p.events("intake.assign") == []
    assigned = p.post("delivery/values:assign", body)
    assert assigned.status_code == 200, assigned.text
    after = assigned.json()["data"]
    assert after["unassigned"] == [] and after["totals"]["values_unassigned"] == 0          # the stored coverage follows
    assert next(s for s in after["subjects"] if s["subject"] == study)["values"] == \
        next(s for s in page["subjects"] if s["subject"] == study)["values"] + 4
    (event,) = p.events("intake.assign")
    assert event.after["row_hash"] == IntakeStore(p.ws).review.entries("assignment")[0].hash
    assert "UNASSIGNED_VALUES" not in [b["code"] for b in p.card(study_path)["blockers"]]

    # --- excluded as not data: the table's values are set aside, its cells are no silent loss ---
    exclusion = {"file_sha256": loose, "regions": [region["region_id"]], "scope": "regions", "why": "a duplicate of the Fed sheet"}
    assert p.post("delivery/regions:exclude", exclusion, token="viewer").status_code == 403
    assert p.post("delivery/regions:exclude", {**exclusion, "file_sha256": "../" + loose[3:]}).status_code == 422
    assert p.post("delivery/regions:exclude", {**exclusion, "file_sha256": _sha(b"never sent")}).status_code == 404
    assert p.post("delivery/regions:exclude", {**exclusion, "regions": ["rg-../../x"]}).status_code == 422
    assert p.post("delivery/regions:exclude", {**exclusion, "regions": ["rg-0123456789"]}).status_code == 404
    assert p.post("delivery/regions:exclude", {**exclusion, "scope": "figures"}).status_code == 422   # a table is no figure
    assert p.post("delivery/regions:exclude", {**exclusion, "scope": "everything"}).status_code == 422
    assert p.post("delivery/regions:exclude", {**exclusion, "regions": ["s:'Summary'!A10"], "scope": "outside"}).status_code == 404
    assert p.events("intake.region") == []
    excluded = p.post("delivery/regions:exclude", exclusion)
    assert excluded.status_code == 200, excluded.text
    after = excluded.json()["data"]
    file = next(f for d in after["deliveries"] for f in d["files"] if f["sha256"] == loose)
    assert file["regions"][0]["state"] == "excluded" and exclusion["why"] in file["regions"][0]["reason"]
    assert (file["coverage"]["silent_loss"], file["coverage"]["regions_excluded"]) == (0, 1)
    assert next(s for s in after["subjects"] if s["subject"] == study)["values"] == \
        next(s for s in page["subjects"] if s["subject"] == study)["values"]
    # the workbook's stray note accepted as not data: the outside number no longer counts
    assert _accept_note(p, workbook).json()["data"]["totals"]["outside_numeric"] == 0
    book = next(f for d in p.page()["deliveries"] for f in d["files"] if f["name"] == workbook.name)
    assert [o["counted"] for o in book["outside"] if o["where"] == OUTSIDE_NOTE] == [False]
    events = p.events("intake.region")
    assert [e.after["row_hash"] for e in events] == [line.hash for line in IntakeStore(p.ws).review.entries("region")]
    assert len(events) == 2


@pytest.mark.req("T-47", "F-404", "T-05")
def test_a_mapping_is_shown_approved_rejected_and_edited_and_each_decision_reads_its_file_again(project):
    p = project()
    p.deliver(("loose-profile.csv", LOOSE))
    loose = _sha(LOOSE)
    (row,) = p.page()["mappings"]
    assert (row["status"], row["origin"], row["kind"], row["waiting"]) == ("proposed", "rule", "pk_summary", False)
    path = f"delivery/mappings/{row['mapping_id']}"
    shown = p.get(path, "viewer")
    assert shown.status_code == 200, shown.text
    mapping = shown.json()["data"]
    # header -> role, field, unit; the tokens and rules; the redacted sample; the versions and where it is in use
    assert (mapping["version"], mapping["status"], mapping["layout"], mapping["field"]) == (1, "proposed", "long", "concentration")
    columns = {c["header"]: c for c in mapping["columns"]}
    assert columns["Time (h)"]["role"] == "time" and columns["Mean concentration (ng/mL)"]["role"] == "value"
    assert columns["SD"]["role"] == "spread" and columns["SD"]["spread_kind"] == "SD"
    assert set(mapping["tokens"]) == {"below_lloq", "missing"} and isinstance(mapping["rules"], list)
    sample = mapping["sample"]
    assert (sample["file"], sample["n_cols"], sample["header"], sample["blinded"]) == (
        "loose-profile.csv", 3, [["Time (h)", "Mean concentration (ng/mL)", "SD"]], False)
    assert sample["body"][0] == ["#.#", "#.#", "#.#"] and not any(ch.isdigit() for row in sample["body"] for cell in row for ch in cell)
    assert [(v["version"], v["status"], v["decisions"]) for v in mapping["versions"]] == [(1, "proposed", [])]
    assert [(u["file"], u["state"]) for u in mapping["used_in"]] == [("loose-profile.csv", "mapped")]
    assert mapping["findings"] == [] and mapping["spec"]["schema"] == "mapping/2" and mapping["queued"] == []
    assert p.get(path, version=1).json()["data"] == mapping and p.get(path, version=7).status_code == 404
    # refusals
    assert p.get("delivery/mappings/mp-0123456789ab").status_code == 404
    assert p.get("delivery/mappings/..%2F..%2Fmappings").status_code in (404, 422)
    assert p.get("delivery/mappings/not-a-mapping").status_code == 422
    assert p.post(f"{path}:approve", {"version": 1}, token="viewer").status_code == 403
    assert p.post(f"{path}:approve", {"version": 7}).status_code == 404
    assert p.post(f"{path}:reject", {"version": 1, "why": ""}).status_code == 422          # a rejection says why
    assert p.post(f"{path}:reject", {"version": 1}).status_code == 422
    assert p.post("delivery/mappings/mp-0123456789ab:reject", {"version": 1, "why": "x"}).status_code == 404
    assert p.events("intake.mapping.approve") == [] and p.events("intake.mapping.reject") == []
    runs = len(intake_pipeline.runs(p.ws))

    # --- rejected: its file is queued again, and until that run is done its table waits ---
    rejected = p.post(f"{path}:reject", {"version": 1, "why": "the SD column is withdrawn"})
    assert rejected.status_code == 200, rejected.text
    after = rejected.json()["data"]
    assert (after["status"], after["queued"], after["waiting"]) == ("rejected", [loose], True)
    assert [(u["state"]) for u in after["used_in"]] == ["waiting"]                         # its earlier values are still active
    assert after["versions"][0]["decisions"][0]["why"] == "the SD column is withdrawn"
    (event,) = p.events("intake.mapping.reject")
    assert event.after["version"] == 1 and event.reason == "the SD column is withdrawn"
    p.settle()
    assert len(intake_pipeline.runs(p.ws)) == runs + 1
    page = p.page()
    (region,) = page["deliveries"][0]["files"][0]["regions"]
    assert (region["state"], region["mapping_id"]) == ("unread", None) and "a person rejected" in region["reason"]
    assert page["totals"]["silent_loss"] == 12 and page["mappings"] == []                  # its cells are counted, never dropped
    # the same rejection again decides nothing new
    assert p.post(f"{path}:reject", {"version": 1, "why": "again"}).json()["data"]["queued"] == []
    assert len(p.events("intake.mapping.reject")) == 1
    p.settle()

    # --- edited: a person's version, checked by code on its table ---
    spec = dict(mapping["spec"])
    assert p.post(f"{path}:edit", {"spec": spec, "why": "x"}, token="viewer").status_code == 403
    assert p.post(f"{path}:edit", {"spec": {**spec, "layout": "sideways"}, "why": "x"}).status_code == 422
    unreadable = p.post(f"{path}:edit", {"spec": {**spec, "first_data_row": 99}, "why": "x"})
    assert unreadable.status_code == 422 and unreadable.json()["detail"]["code"] == "MAPPING_INVALID"
    assert unreadable.json()["detail"]["findings"]
    assert p.post(f"{path}:edit", {"spec": spec, "why": "x", "file_sha256": loose}).status_code == 422   # both or neither
    assert p.post(f"{path}:edit", {"spec": spec, "why": "x", "file_sha256": _sha(b"never sent"),
                                   "region_id": region["region_id"]}).status_code == 404
    same = p.post(f"{path}:edit", {"spec": spec, "why": "the same spec"})                  # version 1 again: rejected
    assert same.status_code == 409 and "rejected" in same.json()["detail"]["message"]
    assert p.events("intake.mapping.edit") == [] and len(MappingCache(p.ws).entries()) == 1
    # code reads the header: a spec that calls the "SD" column an SE is refused, with the finding
    wrong = [{**c, "spread_kind": "SE"} if c["role"] == "spread" else c for c in spec["columns"]]
    refused = p.post(f"{path}:edit", {"spec": {**spec, "columns": wrong}, "why": "x"})
    assert refused.status_code == 422 and [f["code"] for f in refused.json()["detail"]["findings"]] == ["SPREAD_KIND_NOT_STATED"]
    columns = [{"column": c["column"], "role": "ignore", "reason": "the client withdrew this column"} if c["role"] == "spread"
               else c for c in spec["columns"]]
    edited = p.post(f"{path}:edit", {"spec": {**spec, "columns": columns}, "why": "the client withdrew the SD column",
                                     "file_sha256": loose, "region_id": region["region_id"]})
    assert edited.status_code == 200, edited.text
    version = edited.json()["data"]
    assert (version["version"], version["status"], version["origin"], version["origin_detail"]) == (2, "proposed", "person", "u1")
    assert version["queued"] == [loose] and [v["version"] for v in version["versions"]] == [1, 2]
    (event,) = p.events("intake.mapping.edit")
    line = [e for e in IntakeStore(p.ws).mappings.entries("entry")][-1]
    assert event.after == {"mapping_id": row["mapping_id"], "version": 2, "row_hash": line.hash,
                           "spec_sha256": event.after["spec_sha256"]} and event.reason == "the client withdrew the SD column"
    p.settle()
    # the rule's own version is rejected, so the person's version, though it waits for approval, is the one read with
    page = p.page()
    (region,) = page["deliveries"][0]["files"][0]["regions"]
    assert (region["state"], region["origin"], region["mapping_version"], region["mapping_status"]) == ("mapped", "cache", 2, "proposed")
    assert [(m["version"], m["status"], m["origin"]) for m in page["mappings"]] == [(2, "proposed", "person")]
    assert {v["spread"] for v in page["unassigned"]} == {None} and page["totals"]["silent_loss"] == 0
    assert {v["level"] for v in page["unassigned"]} == {"new_mapping"}

    # --- approved: its values are read under an approved mapping, and the file is read again ---
    approved = p.post(f"{path}:approve", {"version": 2, "note": "checked against the client's e-mail"})
    assert approved.status_code == 200, approved.text
    assert (approved.json()["data"]["status"], approved.json()["data"]["queued"]) == ("approved", [loose])
    (event,) = p.events("intake.mapping.approve")
    assert (event.after["version"], event.reason) == (2, "checked against the client's e-mail")
    p.settle()
    page = p.page()
    assert page["mappings"] == [] and {v["level"] for v in page["unassigned"]} == {"approved_mapping"}
    (region,) = page["deliveries"][0]["files"][0]["regions"]
    assert (region["state"], region["mapping_version"], region["mapping_status"]) == ("mapped", 2, "approved")
    assert all(r.state == "done" for r in intake_pipeline.runs(p.ws))


# --- a value's source, and what a request may name ---------------------------------------------------------------------------


def test_the_source_shows_a_values_cell_and_its_time_unit_and_label_cells_by_role(project):
    p = project()
    workbook, pdf = synthetic.messy_workbook(), synthetic.pdf_report(unruled_table=False)
    p.deliver(workbook, pdf)
    card = p.card(p.subject("230-23"))
    value = next(v for t in card["tables"] for v in t["values"] if v["verbatim"] == "25.2")
    answer = p.get("delivery/source", "viewer", value=value["id"])
    assert answer.status_code == 200, answer.text
    source = answer.json()["data"]
    assert (source["kind"], source["file"], source["sha256"], source["value_id"], source["blinded"]) == (
        "grid", workbook.name, _sha(workbook.data), value["id"], False)
    assert source["title"] == "Study 230-23, 50 mg, fasted" and (source["page"], source["box"]) == (None, None)
    marked = {c["role"]: c for c in source["cells"] if c["highlighted"]}
    assert (marked["value"]["text"], marked["value"]["locator"]) == ("25.2", "s:'Fasting'!E4")
    assert (marked["time"]["text"], marked["subject"]["text"]) == ("2", "001")
    assert any("unit" in role for role in marked) and len(source["cells"]) > len(marked)
    # by its anchor: the same place, with no value named
    by_anchor = p.get("delivery/source", anchor=value["anchor"]).json()["data"]
    assert by_anchor["value_id"] is None and by_anchor["region_id"] == source["region_id"]
    assert [c["locator"] for c in by_anchor["cells"] if c["highlighted"]] == ["s:'Fasting'!E4"]
    # a PDF table's value: the page and the box, to draw it
    pdf_value = next(v for t in p.card(p.subject("230-25"))["tables"] if t["kind"] == "table" for v in t["values"])
    drawn = p.get("delivery/source", value=pdf_value["id"]).json()["data"]
    assert drawn["file"] == pdf.name and drawn["page"] == 2 and len(drawn["page_size"]) == 2 and drawn["blinded"] is False
    assert any(c["highlighted"] and c["role"] == "value" for c in drawn["cells"])
    # one of them, not both, not neither
    assert p.get("delivery/source").status_code == 422
    assert p.get("delivery/source", value=value["id"], anchor=value["anchor"]).status_code == 422
    assert p.client.get(f"{p.api}/delivery/source", params={"value": value["id"]}).status_code == 401


def test_ids_and_anchors_with_dots_slashes_or_another_projects_are_refused(project):
    p = project()
    workbook = synthetic.messy_workbook()
    p.deliver(workbook)
    other = project(project_id="p2", beside=p)                    # another project of the same company, the same store
    other.deliver(("loose-profile.csv", LOOSE))
    theirs = other.page()["unassigned"][0]
    assert other.get("delivery/source", value=theirs["id"]).status_code == 200          # theirs, in their project
    mine = next(v for t in p.card(p.subject("230-23"))["tables"] if t["kind"] == "table" for v in t["values"])
    sha, rest = mine["anchor"].split("@", 1)
    hostile_values = ["..", "../p2", "../../p2/intake/ledger/facts", "f-1/../../p2", "/etc/passwd", "tx-../../x#1",
                      f"{mine['id']}/..", "f-1%2F..", "p2/f-1", "tx-0123456789abcdef#0/../1"]
    for text in hostile_values:
        assert p.get("delivery/source", value=text).status_code == 422, text
    hostile_anchors = ["..", "../p2", f"../{mine['anchor']}", f"{sha}/../{sha}@{rest}", f"{sha}@../../p2/{rest.split('/', 1)[1]}",
                       f"{sha}@workbook/../../x#s:'Fasting'!E4", f"/{mine['anchor']}", mine["anchor"] + "/../x",
                       f"../../p2/intake/source/{sha}@{rest}"]
    for text in hostile_anchors:
        assert p.get("delivery/source", anchor=text).status_code == 422, text
    # another project's value and anchor: well formed, and not this project's
    unknown = p.get("delivery/source", value=theirs["id"])
    assert unknown.status_code == 404 and unknown.json()["detail"]["code"] == "UNKNOWN"
    foreign = p.get("delivery/source", anchor=theirs["anchor"])
    assert foreign.status_code == 404 and "this project" in foreign.json()["detail"]["message"]
    assert _sha(LOOSE) not in {f.sha256 for f in intake_landing.file_records(IntakeStore(p.ws)).values()}
    # a file of this project under a parser version nobody cached: no path is tried
    assert p.get("delivery/source", anchor=f"{sha}@workbook/9.9#s:'Fasting'!E4").status_code == 409
    # the same for every other id a request names
    assert p.get(f"delivery/mappings/{other.page()['mappings'][0]['mapping_id']}").status_code == 404
    assert p.post("delivery:run", {"files": [_sha(LOOSE)]}).status_code == 404
    assert p.post("delivery/regions:exclude", {"file_sha256": _sha(LOOSE), "regions": ["rg-0123456789"], "why": "x"}).status_code == 404
    assert p.post("delivery/values:assign", {"targets": [theirs["id"]], "study": "st-1", "why": "x"}).status_code == 404
    assert p.get("delivery/subjects/study/..").status_code in (404, 422)
    assert p.get("delivery/subjects/study/st-1%2F..%2F..").status_code in (404, 422)
    # and nothing of the other project is in this one's answers
    assert "loose-profile" not in p.get("delivery").text and len(other.page()["deliveries"]) == 1


# --- blinding (D-15) ------------------------------------------------------------------------------------------------------------


def _secrets(ws: Workspace, label: str) -> list[re.Pattern[str]]:
    """The concentrations of a study as its files write them, each as a pattern that finds it in an answer's text and
    nothing else (a time, an id or a moment is no match)."""
    reader = LedgerView(ws)
    (study,) = [e for e in reader.entities("study") if e.label == label]
    values = reader.values(study=study.id, field="concentration", active=False)
    times = {v.time for v in values}
    texts = {v.verbatim for v in values if "." in v.verbatim and v.value is not None and v.value > 5 and v.value not in times}
    assert len(texts) > 10
    return [re.compile(r"(?<![\d.])" + re.escape(text) + r"(?!\d)") for text in sorted(texts)]


def _leaks(patterns: list[re.Pattern[str]], text: str) -> list[str]:
    return [p.pattern for p in patterns if p.search(text)]


@pytest.mark.req("T-47", "F-402")
def test_a_blinded_studys_values_blq_counts_and_source_cells_are_withheld_on_every_route(project):
    p = project(blinding=True)
    workbook, pdf = synthetic.messy_workbook(), synthetic.pdf_report(unruled_table=False)
    p.deliver(workbook, pdf)
    path, pdf_path = p.subject("230-23"), p.subject("230-25")
    secrets = [*_secrets(p.ws, "230-23"), *_secrets(p.ws, "230-25")]
    open_card = p.card(path)
    assert open_card["blinded"] is False and len(_leaks(secrets, p.get(path).text)) > 10       # shown until it is blinded
    value = next(v for t in open_card["tables"] for v in t["values"] if v["verbatim"] == "25.2")
    blq = next(v for t in open_card["tables"] for v in t["values"] if v["censored"])
    pdf_value = next(v for t in p.card(pdf_path)["tables"] if t["kind"] == "table" for v in t["values"])
    mapping = f"delivery/mappings/{value['mapping_id']}"
    assert p.get(mapping).json()["data"]["sample"]["body"] and p.get("delivery/source", value=value["id"]).json()["data"]["blinded"] is False
    drawn = p.post(f"{path}/spot-check:draw").json()["data"]                                   # drawn before it was blinded

    # the studies are for external validation: blinded from that moment, in the answer of the entry itself
    answers = []
    for one in (path, pdf_path):
        entered = p.post(f"{one}:enter", {"field": "intended_use", "value": "external_validation", "why": "the plan says so"})
        assert entered.status_code == 200 and entered.json()["data"]["blinded"] is True
        answers.append(entered)

    # --- every route that answers with the study ---
    failed = next(c for c in answers[0].json()["data"]["checks"]
                  if c["severity"] == "fail" and c["code"] != "REQUIRED_ITEM_UNDISPOSED")
    answers += [
        p.get("delivery"), p.get("delivery", "viewer"), p.get(path), p.get(pdf_path), p.get(path, "viewer"),
        p.post(f"{path}:override", {"check_id": failed["id"], "why": "as written"}),
        p.post(f"{path}:dispose", {"req_id": "REQ-sys.demographics", "disposition": "ask_client", "why": "asked"}),
        p.post(f"{path}:enter", {"field": "route", "value": "oral", "why": "from the protocol"}),
        p.post(f"{path}:enter", {"value": 99.5, "supersedes": value["id"], "why": "a typing error"}),
        p.get("delivery/source", value=blq["id"]), p.get("delivery/source", anchor=value["anchor"]),
        p.get("delivery/source", value=pdf_value["id"]), p.get("delivery/source", anchor=pdf_value["anchor"]),
        p.get(mapping), p.get(mapping, version=1), p.post(f"{mapping}:approve", {"version": 1, "note": "again"}),
        p.get(f"delivery/mappings/{pdf_value['mapping_id']}"),
        _accept_note(p, workbook),
    ]
    p.settle()
    for answer in answers:
        assert answer.status_code == 200, (answer.request.url, answer.text[:300])
        assert _leaks(secrets, answer.text) == [], answer.request.url
    # the card: every value of the study without what D-15 withholds, and no way to count the values below the LLOQ
    card = p.card(path)
    rows = [v for t in card["tables"] for v in t["values"]]
    assert card["blinded"] is True and len(rows) > 60
    for row in rows:
        assert row["blinded"] is True, row["id"]
        assert [row[k] for k in ("value", "verbatim", "spread", "interval", "lloq", "uloq", "censored")] == [None] * 7, row["id"]
        assert row["field"] and row["anchor"] is not None or row["method"] == "person"      # its place and field stay
    assert any(row["time"] is not None and row["unit"] == "ng/mL" for row in rows)           # times and units stay
    assert all(c["message"] is None and c["values"] == [] for c in card["checks"])
    assert "BLQ_PRESENT" in {c["code"] for c in card["checks"]}                               # that a check ran is shown
    assert card["held"] is None and card["landing_problem"] is None
    assert "BLINDED" in [b["code"] for b in card["blockers"]]
    assert not any(ch.isdigit() for b in card["blockers"] if b["code"] == "BLINDED" for ch in b["detail"].replace("D-15", ""))
    # the page: the row says blinded; a file that holds its values shows no caption, no outside text
    page = p.page()
    by_label = {s["label"]: s for s in page["subjects"]}
    assert by_label["230-23"]["blinded"] is True and by_label["230-25"]["blinded"] is True
    assert by_label["231-24"]["blinded"] is False and by_label["230-26"]["blinded"] is False
    for file in page["deliveries"][0]["files"]:
        assert file["blinded"] is True and all(r["caption"] is None for r in file["regions"])
        assert all(o["text"] is None for o in file["outside"])
    # the source: every cell with a number and every cell a value is anchored at (a "BLQ" mark) is blank, the digits of
    # the title are masked, and a PDF's page is not given (drawn from the file it would show the values)
    for asked in ({"value": blq["id"]}, {"anchor": value["anchor"]}, {"value": pdf_value["id"]}):
        source = p.get("delivery/source", **asked).json()["data"]
        assert source["blinded"] is True and (source["page"], source["page_size"], source["box"]) == (None, None, None)
        assert all(c["text"] == "" for c in source["cells"] if c["numeric"])
        assert not any(ch.isdigit() for ch in source["title"]) and "BLQ" not in {c["text"] for c in source["cells"]}
        assert any(c["highlighted"] for c in source["cells"])                                # where it is stays shown
    assert "•" in p.get("delivery/source", value=blq["id"]).json()["data"]["title"]
    # the mapping's sample of its table: no body row at all, no digit of its context
    sample = p.get(mapping).json()["data"]["sample"]
    assert sample["blinded"] is True and sample["body"] == [] and sample["body_rows"] == []
    assert not any(ch.isdigit() for line in sample["context"] for ch in line["text"])
    # another study of the same project is not blinded: its values are shown as before
    neighbour = p.card(p.subject("231-24"))
    assert neighbour["blinded"] is False and all(v["blinded"] is False for t in neighbour["tables"] for v in t["values"])
    assert any(v["value"] is not None and v["verbatim"] for t in neighbour["tables"] for v in t["values"])

    # --- what a blinded study refuses ---
    again = p.post(f"{path}/spot-check:draw")
    assert again.status_code == 409 and again.json()["detail"]["code"] == "BLINDED"
    ticks = {"draw_id": drawn["draw"]["id"], "ticks": [{"value_id": v, "ok": True} for v in drawn["wanted"]]}
    ticked = p.post(f"{path}/spot-check", ticks)
    assert ticked.status_code == 409 and ticked.json()["detail"]["code"] == "BLINDED"
    assert p.events("intake.spot_check") == []
    for token in ("t", "plain"):
        refused = p.post(f"{path}:confirm", token=token)
        assert refused.status_code == 409 and refused.json()["detail"]["code"] == "BLINDED"
        assert "BLINDED" in [b["code"] for b in refused.json()["detail"]["blockers"]]
        assert _leaks(secrets, refused.text) == []
    assert p.events("signature.create") == [] and review.confirmations(p.ws) == []
    # a dataset's points on the legacy card: a blinded profile names its BLQ rule and gives no count
    profile = ObservedDataset(id="ds-0123456789", kind="profile", origin=Origin.CLIENT, provider="CLIENT",
                              study={"study_id": "230-23", "n": 24, "route": "oral", "dose_mg": 50.0, "formulation": "ir_tablet",
                                     "food_state": "fasted", "n_timepoints": 3, "lloq": 0.5},
                              series=(Series(name="mean", times=(1, 2, 4), values=(None, 25.2, 12.1), n=24),))
    shown, withheld = card_points(profile.to_content()), card_points(redact_dataset(profile.to_content()))
    assert (shown["blq_rule"], shown["blq_omitted"]) == ("omit", 1) and (withheld["blq_rule"], withheld["blq_omitted"]) == ("omit", None)
    assert withheld["blinded"] is True and set(withheld["series"][0]["values"]) == {None}


@pytest.mark.req("T-47", "F-402")
def test_with_blinding_off_or_no_external_purpose_nothing_is_withheld(project):
    p = project()                                                         # the project's blinding is off (medium risk)
    p.deliver(synthetic.messy_workbook())
    path = p.subject("230-23")
    entered = p.post(f"{path}:enter", {"field": "intended_use", "value": "external_validation", "why": "the plan says so"})
    card = entered.json()["data"]
    assert card["blinded"] is False and all(v["blinded"] is False for t in card["tables"] for v in t["values"])
    assert any(v["censored"] for t in card["tables"] for v in t["values"]) and card["held"] is not None
    assert p.post(f"{path}/spot-check:draw").status_code == 200


# --- nothing is loaded twice: the legacy card's guard -------------------------------------------------------------------------


def _legacy_dataset(p: Project, workbook: synthetic.SyntheticFile, study_id: str, sheet: str, key: str) -> ObservedDataset:
    """A dataset as today's sheet reader saves one: proposed, a client's, listed by a recipe of its sheet."""
    sha = _sha(workbook.data)
    found = ObservedDataset(
        id="ds-" + hashlib.sha256(key.encode()).hexdigest()[:10], kind="profile", origin=Origin.CLIENT, extraction="CELL",
        provider="CLIENT", source=SourceRef(doc_sha256=sha, page=1, title=workbook.name),
        study={"study_id": study_id, "n": 6, "route": "oral", "dose_mg": 50.0, "formulation": "ir_tablet",
               "food_state": "fasted", "n_timepoints": 3, "statistic": "mean", "lloq": 0.5},
        series=(Series(times=(1.0, 2.0, 4.0), values=(3.0, 4.0, 2.0), n=6),))
    made = propose_dataset(p.ws, found, actor="code")
    client_data.record_mapping(p.ws, client_data.submission_id(sha), dataset_ids=[made.id], dissolution=[], by="code",
                               recipe={"recipe_id": f"legacy-{key}", "version": 1, "tables": [{"sheet": sheet}]})
    return made


def _group_of(p: Project, dataset_id: str) -> dict[str, Any]:
    groups = p.get("client-review").json()["data"]["groups"]
    return next(g for g in groups if any(item["id"] == dataset_id for item in g["items"]))


def test_the_legacy_client_review_confirm_refuses_what_delivery_confirmed(project):
    p = project()
    workbook = synthetic.messy_workbook()
    path = _ready(p)
    # before Delivery confirms it, the legacy card may still load the study (nothing is covered yet)
    early = _legacy_dataset(p, workbook, "230-23", "Fasting", "early")
    client_api._not_on_delivery(p.ws, [dataset(p.ws, early.id)])                          # no refusal
    assert p.card(path)["loaded_elsewhere"] == [early.id]
    signed = p.post(f"{path}:confirm")
    assert signed.status_code == 200, signed.text
    (confirmation,) = review.confirmations(p.ws)
    assert dataset(p.ws, early.id).state is EvidenceState.REJECTED                         # the landing replaced it
    # a reading of the same sheet and study saved on the legacy card afterwards: its group cannot be confirmed
    late = _legacy_dataset(p, workbook, "230-23", "Fasting", "late")
    group = _group_of(p, late.id)
    assert group["state"] != "confirmed"
    refused = p.post("client-review:confirm", {"group": group["id"]})
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"]["code"] == "LOADED_ON_DELIVERY" and confirmation.id in refused.json()["detail"]["message"]
    assert dataset(p.ws, late.id).state is EvidenceState.PROPOSED
    assert len([d for d in all_datasets(p.ws) if d.state is EvidenceState.ACCEPTED]) == 2   # only what Delivery landed
    # by source, never by name: the same sheet under a study id made from the file name is covered too
    by_name = _legacy_dataset(p, workbook, "messy-delivery", "Fasting", "by-name")
    by_name = by_name.model_copy(update={"series": (Series(times=(2.0,), values=(25.2,), n=6),)})   # a point of the bound table
    with pytest.raises(Exception) as caught:
        client_api._not_on_delivery(p.ws, [by_name])
    assert caught.value.status_code == 409 and caught.value.detail["code"] == "LOADED_ON_DELIVERY"
    # another study's table on another sheet is not covered: the legacy card still confirms it
    free = _legacy_dataset(p, workbook, "231-24", "Fed", "free")
    client_api._not_on_delivery(p.ws, [dataset(p.ws, free.id)])
    assert review.covered_by_confirmation(p.ws, dataset(p.ws, free.id)) is None
    # the two other legacy doors: finishing a sheet Delivery landed, and reading it in again
    sid = client_data.submission_id(_sha(workbook.data))
    finish = p.post("client-review:finish", {"file": sid, "sheet": "Fasting", "answers": {"n": 24}})
    assert finish.status_code == 409 and finish.json()["detail"]["code"] == "LOADED_ON_DELIVERY"
    content = client_data.submission(p.ws, sid)
    assert client_api._delivery_recipes(content, {"Fasting"}) == [confirmation.id]
    assert client_api._delivery_recipes(content, {"Fed"}) == []
    unsaved = dataset(p.ws, late.id).model_copy(update={"id": "ds-notsavedyet", "source": SourceRef(doc_sha256=_sha(workbook.data),
                                                                                               title=workbook.name)})
    assert review.covered_by_confirmation(p.ws, unsaved) is None                           # not saved: no sheet on record
    with pytest.raises(Exception) as caught:                                              # asked with the sheets it reads
        client_api._not_on_delivery(p.ws, [unsaved], sheets={"Fasting"})
    assert caught.value.detail["code"] == "LOADED_ON_DELIVERY"
    client_api._not_on_delivery(p.ws, [unsaved], sheets={"Urine2"})                       # a sheet Delivery bound nothing from


# --- the switch ---------------------------------------------------------------------------------------------------------------


def test_in_legacy_the_page_answers_enabled_false_and_no_other_delivery_route_does_anything(project):
    p = project("legacy")
    workbook = synthetic.messy_workbook()
    assert p.upload((workbook.name, workbook.data)).status_code == 201
    p.settle()
    for token in ("t", "viewer"):
        page = p.page(token)
        assert page["enabled"] is False and page["running"] is False
        assert (page["deliveries"], page["subjects"], page["unassigned"], page["mappings"], page["request"]) == ([], [], [], [], [])
        assert page["totals"]["files"] == 0 and page["rules"]["status"] == "UNVERIFIED"
    sha, why = _sha(workbook.data), {"why": "x"}
    subject = "delivery/subjects/study/st-1"
    posts = {
        "delivery:run": None, "delivery/values:assign": {"targets": ["f-1"], "study": "st-1", **why},
        "delivery/regions:exclude": {"file_sha256": sha, "regions": ["rg-0123456789"], **why},
        "delivery/mappings/mp-0123456789ab:approve": {"version": 1},
        "delivery/mappings/mp-0123456789ab:reject": {"version": 1, **why},
        "delivery/mappings/mp-0123456789ab:edit": {"spec": {}, **why},
        f"{subject}:override": {"check_id": "ck-0123456789ab", **why},
        f"{subject}:dispose": {"req_id": "REQ-x", "disposition": "ask_client", **why},
        f"{subject}:choose": {"conflict_id": "cx-0123456789", "keep": "f-1", **why},
        f"{subject}:link": {"file_sha256": sha, "confirmed": True}, f"{subject}:enter": {"field": "route", "value": "oral", **why},
        f"{subject}:confirm": None, f"{subject}/spot-check:draw": None,
        f"{subject}/spot-check": {"draw_id": "sd-1", "ticks": []}}
    gets = ["delivery/source?value=f-1", "delivery/mappings/mp-0123456789ab", subject]
    answers = [p.post(path, body) for path, body in posts.items()] + [p.get(path) for path in gets]
    for answer in answers:
        assert answer.status_code == 409, (answer.request.url, answer.text)
        assert answer.json()["detail"]["code"] == "INTAKE_PIPELINE_OFF"
    # every /delivery route but the page was asked, and nothing was written: no intake folder, no event
    mounted = {(m, r.path) for r in client_api.router.routes if isinstance(r, APIRoute) and "/delivery" in r.path for m in r.methods}
    assert len(mounted) == len(posts) + len(gets) + 1 == 18
    assert not (Path(p.store.root) / "t1" / "projects" / "p1" / "intake").exists()
    assert [e.action for e in p.events() if e.action.startswith(("intake.", "signature."))] == []


_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:\+00:00|Z)")


def _same(answer: Any) -> Any:
    """An answer without what differs between any two runs of the same request: the times and the request's id."""
    if isinstance(answer, dict):
        return {k: _same(v) for k, v in answer.items() if k != "request_id"}
    if isinstance(answer, list | tuple):
        return [_same(v) for v in answer]
    return _TIME.sub("<time>", answer) if isinstance(answer, str) else answer


def test_no_legacy_routes_answer_changes_when_the_delivery_section_is_read(project):
    files = [synthetic.messy_workbook(), synthetic.pdf_report(unruled_table=False), synthetic.template_workbook()]

    def pages(one: Project) -> dict[str, Any]:
        return {name: (r.status_code, _same(r.json())) for name in PAGES for r in [one.get(name)]}

    legacy = project("legacy")
    assert legacy.upload(*[(f.name, f.data) for f in files]).status_code == 201
    legacy.settle()
    assert legacy.page()["enabled"] is False
    expected = pages(legacy)
    both = project("both")
    assert both.upload(*[(f.name, f.data) for f in files]).status_code == 201
    both.settle()
    before = pages(both)
    # the Delivery section read through: the page (which sweeps and starts the job), every card, a source, a mapping
    page = both.page()
    assert page["enabled"] is True and len(page["subjects"]) >= 4
    for row in page["subjects"]:
        card = both.card(f"delivery/subjects/{row['subject_type']}/{row['subject']}")
        for value in [v for t in card["tables"] for v in t["values"] if v["anchor"]][:1]:
            assert both.get("delivery/source", value=value["id"]).status_code == 200
    for row in page["mappings"]:
        assert both.get(f"delivery/mappings/{row['mapping_id']}").status_code == 200
    both.settle()
    after = pages(both)
    assert [status for status, _body in expected.values()] == [200, 200, 200, 200]
    for name in PAGES:
        assert before[name] == expected[name], name          # mounted and running beside today's readers: the same answer
        assert after[name] == expected[name], name           # and reading the Delivery section changes none of them
    assert len(expected["client-data"][1]["data"]["files"]) == 3 and expected["client-review"][1]["data"]["groups"]
    # the filled client-data template is confirmed on its legacy card: Delivery shows it read-only
    template_subjects = [s for s in page["subjects"] if s["confirm_on"] == "client-review"]
    assert template_subjects
    row = template_subjects[0]
    refused = both.post(f"delivery/subjects/{row['subject_type']}/{row['subject']}:confirm")
    assert refused.status_code == 409 and "LOADED_ON_CLIENT_REVIEW" in [b["code"] for b in refused.json()["detail"]["blockers"]]


# --- the module's shape ---------------------------------------------------------------------------------------------------------


def test_delivery_routes_defines_no_router_and_imports_no_module_that_defines_one():
    source = Path(delivery_routes.__file__)

    def calls_api_router(path: Path) -> bool:
        return any(isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", None)) == "APIRouter"
                   for node in ast.walk(ast.parse(path.read_text())))

    package = source.parent
    routers = {"modeler_api." + ".".join(path.relative_to(package).with_suffix("").parts)
               for path in package.rglob("*.py") if calls_api_router(path)}
    assert {"modeler_api.client_api", "modeler_api.admin_api"} <= routers and "modeler_api.delivery_routes" not in routers
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source.read_text())):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported |= {node.module, *(f"{node.module}.{alias.name}" for alias in node.names)}
    assert any(name.startswith("modeler_api.") for name in imported)
    assert sorted(name for name in imported if any(name == r or name.startswith(r + ".") for r in routers)) == []
    # its handlers are client_api's routes: mounted on that router, covered by the response ratchet
    assert not hasattr(delivery_routes, "router")
    handlers = {r.endpoint for r in client_api.router.routes if isinstance(r, APIRoute) and "/delivery" in r.path}
    assert len(handlers) == 18 and all(h.__module__ == "modeler_api.delivery_routes" for h in handlers)


def test_every_delivery_route_and_the_admin_pipeline_route_has_a_typed_answer():
    routes = [r for router in (client_api.router, admin_api.router) for r in router.routes
              if isinstance(r, APIRoute) and ("/delivery" in r.path or r.path.endswith("/admin/pipeline"))]
    assert len(routes) == 19
    names = set()
    for route in routes:
        model = route.response_model
        assert isinstance(model, type) and issubclass(model, BaseModel), route.path
        data = model.model_fields["data"].annotation
        assert isinstance(data, type) and issubclass(data, View), route.path           # a model, never Envelope[dict]
        names.add(data.__name__)
        assert route.response_model_exclude_unset is True
    assert names == {"DeliveryPage", "DeliverySubject", "DeliverySource", "DeliveryMapping", "DeliverySpotCheck",
                     "TriageStart", "PipelineHealth"}
    # no new model takes the name of a schema the API already published: FastAPI would rename both
    schemas = app.openapi()["components"]["schemas"]
    assert not [name for name in schemas if name.startswith("modeler_api__views__delivery")]
    assert {"DeliveryPage", "DeliveryValue", "DeliveryRun", "DeliveryEntry", "PipelineHealth", "TriageStart"} <= set(schemas)


def _raw_workbook(study: str = "230-31") -> tuple[str, bytes]:
    """A client's own workbook (not the template): one individual table under a title that names its study. The rules
    read a study id written like "230-31" from the title; one written like "ABC-1" they do not read."""
    book = Workbook()
    sheet = book.active
    sheet.title = "Sheet1"
    for row in ([f"Study {study}, 25 mg oral tablet, fasted"],
                ["Subject", "Time (h)", f"{synthetic.DRUG} plasma concentration (ng/mL)"],
                ["001", 0.5, 10.1], ["001", 1, 22.4], ["001", 2, 15.0], ["002", 0.5, 9.8], ["002", 1, 20.0], ["002", 2, 14.1]):
        sheet.append(row)
    raw = io.BytesIO()
    book.save(raw)
    return "raw.xlsx", raw.getvalue()


RECIPE = {"tables": [{
    "record_type": "concentration_time", "sheet": "Sheet1", "header_rows": 2, "first_data_row": 3,
    "columns": [{"column": "A", "role": "subject_id"}, {"column": "B", "role": "time"}, {"column": "C", "role": "value"}],
    "time_unit": "h", "value_unit": "ng/mL", "statistic": "individual",
    "constants": [{"key": "study_id", "value": "230-31"}, {"key": "analyte", "value": "parent"},
                  {"key": "matrix", "value": "plasma"}, {"key": "dose", "value": "25"}, {"key": "dose_unit", "value": "mg"},
                  {"key": "route", "value": "oral"}, {"key": "formulation", "value": "ir_tablet"},
                  {"key": "food_state", "value": "fasted"}],
    "evidence": [{"cell": "Sheet1!C2", "quote": "ng/mL", "supports": "value unit"},
                 {"cell": "Sheet1!A1", "quote": "25 mg", "supports": "dose"}]}]}


def test_reading_a_sheet_in_again_on_the_legacy_card_is_refused_once_delivery_confirmed_its_study(project):
    p = project()
    name, data = _raw_workbook()
    p.deliver((name, data), preload=False)
    sid = client_data.submission_id(_sha(data))
    reading = {"proposal": RECIPE, "study": {"n": 2, "design": "SD", "purpose": "model_building"}}
    # before Delivery confirms the study, today's sheet reader saves its reading as before (the guard refuses nothing)
    first = p.post(f"client-data/{sid}:map", {**reading, "confirm": True})
    assert first.status_code == 200, first.text
    (legacy_id,) = first.json()["data"]["datasets"]
    assert dataset(p.ws, legacy_id).state is EvidenceState.PROPOSED
    path = p.subject("230-31")
    assert p.card(path)["loaded_elsewhere"] == [legacy_id]                 # Delivery shows what the legacy card holds
    _decide(p, path, {"n": 2, "intended_use": "model_building", "formulation": "ir_tablet"})
    _spot_check(p, path)
    signed = p.post(f"{path}:confirm")
    assert signed.status_code == 200, signed.text
    (confirmation,) = review.confirmations(p.ws)
    assert signed.json()["data"]["confirmation"]["landed"]["rejected_legacy"] == [legacy_id]
    assert dataset(p.ws, legacy_id).decision_reason == f"replaced by Delivery confirmation {confirmation.id}"
    (landed_id,) = landed = signed.json()["data"]["confirmation"]["landed"]["datasets"]
    assert dataset(p.ws, landed_id).study["study_id"] == "230-31" and len(dataset(p.ws, landed_id).series) == 2
    # now the same reading is refused, with or without `replace` (which would reject what the signature landed)
    for extra in ({}, {"replace": True}):
        refused = p.post(f"client-data/{sid}:map", {**reading, "confirm": True, **extra})
        assert refused.status_code == 409, refused.text
        assert refused.json()["detail"]["code"] == "LOADED_ON_DELIVERY" and confirmation.id in refused.json()["detail"]["message"]
    assert p.post(f"client-data/{sid}:map", reading).status_code == 200    # a preview reads nothing in: not refused
    assert all(dataset(p.ws, i).state is EvidenceState.ACCEPTED for i in landed)
    assert [d.id for d in all_datasets(p.ws) if d.state is EvidenceState.ACCEPTED] == landed


def test_a_dose_entered_in_grams_gets_its_mg_fact_and_the_draw_shows_it_with_its_input(project):
    p = project()
    p.deliver(synthetic.pdf_report(unruled_table=False))
    path = p.subject("230-25")                                        # its table states no dose
    assert "DOSE_MISSING" in {c["code"] for c in p.card(path)["checks"]}
    entered = p.post(f"{path}:enter", {"field": "dose", "value": 0.5, "unit": "g", "why": "from the protocol"})
    assert entered.status_code == 200, entered.text
    values = {v["id"]: v for t in entered.json()["data"]["tables"] for v in t["values"]}
    (person,) = [v for v in values.values() if v["method"] == "person"]
    (derived,) = [v for v in values.values() if v["method"] == "derived"]
    assert (person["value"], person["unit"]) == (0.5, "g")                # as entered: the unit is never renamed
    assert (derived["field"], derived["value"], derived["unit"], derived["derived_from"]) == ("dose", 500.0, "mg", [person["id"]])
    assert derived["compute"].endswith("dose_to_mg") and derived["anchor"] is None
    assert "DOSE_MISSING" not in {c["code"] for c in entered.json()["data"]["checks"]}
    # a derived value is always verified, shown with its input
    draw = p.post(f"{path}/spot-check:draw").json()["data"]
    shown = next(v for v in draw["values"] if v["value"]["id"] == derived["id"])
    assert shown["reason"].startswith("always:") and shown["wanted"] is True
    assert [(i["id"], i["value"], i["unit"]) for i in shown["inputs"]] == [(person["id"], 0.5, "g")]


# --- a study or a product a person names when assigning ---------------------------------------------------------------------


def _dissolution_workbook() -> tuple[str, bytes]:
    """A dissolution table that states its batch and its method, and no product."""
    book = Workbook()
    sheet = book.active
    sheet.title = "Dissolution"
    for row in (["Batch L9001, paddle, 50 rpm, 900 mL pH 6.8 phosphate buffer"], ["Time (min)", "Mean % dissolved"],
                [10, 41.0], [20, 73.5], [30, 92.25]):
        sheet.append(row)
    raw = io.BytesIO()
    book.save(raw)
    return "dissolution-L9001.xlsx", raw.getvalue()


def _all_targets(values: list[dict[str, Any]]) -> list[str]:
    """Targets that name every one of these values: a table's values by its extract, a fact by its id."""
    return list(dict.fromkeys(v["id"].split("#")[0] for v in values))


@pytest.mark.req("T-47", "F-403", "T-06", "F-404", "T-05")
def test_a_person_names_the_study_of_a_table_whose_title_the_rules_do_not_read_and_it_is_confirmed_and_landed(project):
    p = project()
    name, data = _raw_workbook("ABC-1")
    p.deliver((name, data), preload=False)
    page = p.page()
    # the title "Study ABC-1, …" is not read as a study id: no study exists, and every value is "study not stated"
    assert page["subjects"] == [] and page["totals"]["values_unassigned"] == len(page["unassigned"]) == 10
    assert {v["field"] for v in page["unassigned"]} == {"concentration", "analyte", "dose", "route", "food_state"}
    targets = _all_targets(page["unassigned"])
    body = {"targets": targets, "new_study": "ABC-1", "why": "the table's title says Study ABC-1"}
    entities = len(IntakeStore(p.ws).entities.entries("entity"))
    # refused, and nothing is written: a reader; a name with no letter or digit; one too long; an id and a name at once;
    # no subject at all
    assert p.post("delivery/values:assign", body, token="viewer").status_code == 403
    for wrong in ({"new_study": "  "}, {"new_study": "—"}, {"new_study": "A" * 81}, {"new_study": "ABC-1", "study": "st-1"},
                  {"new_study": None}, {"new_study": "ABC-1", "why": ""}, {"new_study": "ABC-1", "arm": "arm-99999"}):
        refused = p.post("delivery/values:assign", {**body, **wrong})
        assert refused.status_code in (404, 422), (wrong, refused.text)
    invalid = p.post("delivery/values:assign", {**body, "new_study": "ABC-1", "study": "st-1"})
    assert invalid.status_code == 422 and invalid.json()["detail"]["code"] == "INVALID"
    assert len(IntakeStore(p.ws).entities.entries("entity")) == entities
    assert p.events("intake.entity") == [] and p.events("intake.assign") == []

    # named: the study is created and the values are its own
    assigned = p.post("delivery/values:assign", body)
    assert assigned.status_code == 200, assigned.text
    page = assigned.json()["data"]
    (row,) = page["subjects"]
    assert (row["subject_type"], row["label"], row["values"], row["confirm_on"], row["blinded"]) == ("study", "ABC-1", 10, "delivery", False)
    assert page["unassigned"] == [] and page["totals"]["values_unassigned"] == 0
    line = IntakeStore(p.ws).entities.entries("entity")[-1]
    assert (line.body["id"], line.body["label"], line.body["source"], line.body["by"]) == (row["subject"], "ABC-1", None, "u1")
    (created,) = p.events("intake.entity")                                 # one event for the creation, with the line's hash
    assert created.after == {"entity": row["subject"], "type": "study", "label": "ABC-1", "row_hash": line.hash}
    assert (created.actor, created.reason) == ("u1", "the table's title says Study ABC-1")
    (event,) = p.events("intake.assign")                                   # and the assignment's own, as before
    assert event.after["row_hash"] == IntakeStore(p.ws).review.entries("assignment")[0].hash
    assert [e.action for e in p.events() if e.action in ("intake.entity", "intake.assign")] == ["intake.entity", "intake.assign"]
    # never a duplicate: the same name again, however it is spelt, is refused and names the study that exists
    for label in ("ABC-1", "abc 1", "Abc1"):
        again = p.post("delivery/values:assign", {**body, "new_study": label})
        assert again.status_code == 409 and again.json()["detail"]["code"] == "CONFLICT"
        assert f"'ABC-1' exists already ({row['subject']})" in again.json()["detail"]["message"]
    assert len(p.events("intake.entity")) == 1 and len(IntakeStore(p.ws).entities.entries("entity")) == entities + 1

    # its card: its values are its own (no cross-file value, no link to confirm), and it is reviewed like any study
    path = p.subject("ABC-1")
    card = p.card(path)
    assert (card["label"], card["links"], card["values"]) == ("ABC-1", [], 10)
    assert not any(v["cross_file"] for t in card["tables"] for v in t["values"])
    assert "LINK_UNCONFIRMED" not in [b["code"] for b in card["blockers"]] and "UNASSIGNED_VALUES" not in [b["code"] for b in card["blockers"]]
    assert all(v["labels"]["study"] == "ABC-1" for t in card["tables"] for v in t["values"])
    card = _decide(p, path, {"n": 2, "intended_use": "model_building", "formulation": "ir_tablet"})
    assert [b["code"] for b in card["blockers"]] == ["SPOT_CHECK"] and card["landing_problem"] is None
    assert _spot_check(p, path)["state"] == "complete"
    assert p.post(f"{path}:confirm", token="plain").json()["detail"]["code"] == "STEP_UP_REQUIRED"
    signed = p.post(f"{path}:confirm")
    assert signed.status_code == 200, signed.text
    done = signed.json()["data"]
    (confirmation,) = review.confirmations(p.ws)
    assert confirmation.record["label"] == "ABC-1" and confirmation.record["links"] == [] and len(confirmation.record["assignments"]) == 1
    (landed_id,) = done["confirmation"]["landed"]["datasets"]
    landed = dataset(p.ws, landed_id)
    assert landed.state is EvidenceState.ACCEPTED and landed.origin is Origin.CLIENT
    assert landed.study["study_id"] == "ABC-1" and landed.study["dose_mg"] == 25.0 and landed.study["n"] == 2
    assert landed.source.doc_sha256 == _sha(data) and not [f for f in landed.flags if f.startswith("cross_file")]
    assert {s.name: s.values for s in landed.series} == {"001": (10.1, 22.4, 15.0), "002": (9.8, 20.0, 14.1)}
    assert [len(p.events(a)) for a in ("signature.create", "intake.confirm", "intake.land")] == [1, 1, 1]
    assert p.store.audit("t1").verify() is None and IntakeStore(p.ws).entities.verify() == []


@pytest.mark.req("T-47", "F-404", "T-05")
def test_a_person_names_the_product_of_a_dissolution_table_that_states_only_its_batch(project):
    p = project()
    workbook = synthetic.messy_workbook()
    name, data = _dissolution_workbook()
    p.deliver(workbook, (name, data))
    page = p.page()
    loose = [v for v in page["unassigned"] if v["file"] == name]
    points = [v for v in loose if v["field"] == "percent_dissolved"]
    # the table names its batch and no product: a batch alone is no subject, so its values are "study not stated"
    assert len(points) == 3 and {v["labels"].get("batch") for v in points} == {"L9001"} and not any("product" in v["labels"] for v in loose)
    (batch,) = {v["entity"]["batch"] for v in points}
    assert points[0]["conditions"] == {"apparatus": "paddle", "medium": "phosphate", "ph": "6.8", "rpm": "50", "volume_ml": "900"}
    body = {"targets": _all_targets(loose), "new_product": "Exampleamide capsule", "batch": batch,
            "why": "the client's e-mail names the product of batch L9001"}
    other_batch = next(s for s in page["subjects"] if s["label"] == "Exampleamide IR tablet")["batches"][0]["id"]
    # refused: a product that exists, by its key; a batch of another product; a product id and a new name at once
    exists = p.post("delivery/values:assign", {**body, "new_product": "exampleamide IR  TABLET"})
    assert exists.status_code == 409 and "'Exampleamide IR tablet' exists already (pr-" in exists.json()["detail"]["message"]
    assert p.post("delivery/values:assign", {**body, "batch": other_batch}).status_code == 422
    assert p.post("delivery/values:assign", {**body, "product": "pr-1"}).status_code == 422
    assert p.events("intake.entity") == []
    assigned = p.post("delivery/values:assign", body)
    assert assigned.status_code == 200, assigned.text
    after = assigned.json()["data"]
    row = next(s for s in after["subjects"] if s["label"] == "Exampleamide capsule")
    assert (row["subject_type"], row["values"], row["files"], row["arms"]) == ("product", len(loose), [_sha(data)], [])
    assert row["batches"] == [{"id": batch, "label": "L9001"}]             # the batch its values name, kept by the assignment
    assert not [v for v in after["unassigned"] if v["file"] == name]
    (created,) = p.events("intake.entity")
    line = IntakeStore(p.ws).entities.entries("entity")[-1]
    assert created.after == {"entity": row["subject"], "type": "product", "label": "Exampleamide capsule", "row_hash": line.hash}
    assert len(p.events("intake.assign")) == 1
    # its card, as any product's: its values with their batch, its dissolution table, its checks
    path = f"delivery/subjects/product/{row['subject']}"
    card = p.card(path)
    assert (card["label"], card["values"], card["blinded"]) == ("Exampleamide capsule", len(loose), False)
    values = [v for t in card["tables"] for v in t["values"]]
    assert {v["labels"]["product"] for v in values} == {"Exampleamide capsule"} and {v["labels"]["batch"] for v in values} == {"L9001"}
    assert {t["table_kind"] for t in card["tables"] if t["kind"] == "table"} == {"dissolution"}
    assert p.post(f"{path}/spot-check:draw").status_code == 200
    # a study and a product named in one assignment: both are created, each with its event
    both = project(project_id="p2", beside=p)
    both.deliver(_raw_workbook("ABC-2"), preload=False)
    made = both.post("delivery/values:assign", {"targets": _all_targets(both.page()["unassigned"]), "new_study": "ABC-2",
                                                "new_product": "Exampleamide oral solution", "why": "the cover letter"})
    assert made.status_code == 200, made.text
    assert {(s["subject_type"], s["label"]) for s in made.json()["data"]["subjects"]} == {
        ("study", "ABC-2"), ("product", "Exampleamide oral solution")}
    assert [e.after["type"] for e in both.events("intake.entity") if e.resource_id.startswith("p2/")] == ["study", "product"]


@pytest.mark.req("T-47", "F-402")
def test_a_study_a_person_named_is_blinded_like_any_other(project):
    p = project(blinding=True)
    p.deliver(_raw_workbook("ABC-1"), preload=False)
    secrets = [re.compile(r"(?<![\d.])" + re.escape(text) + r"(?!\d)") for text in ("10.1", "22.4", "9.8", "14.1")]
    before = p.get("delivery")
    assert len(_leaks(secrets, before.text)) == 4                         # "study not stated" values are shown
    targets = _all_targets(before.json()["data"]["unassigned"])
    named = p.post("delivery/values:assign", {"targets": targets, "new_study": "ABC-1", "why": "the title"})
    path = p.subject("ABC-1")
    assert named.status_code == 200 and p.card(path)["blinded"] is False  # naming a study blinds nothing by itself
    value = next(v for t in p.card(path)["tables"] if t["kind"] == "table" for v in t["values"])
    blinded = p.post(f"{path}:enter", {"field": "intended_use", "value": "external_validation", "why": "the plan says so"})
    assert blinded.status_code == 200 and blinded.json()["data"]["blinded"] is True
    answers = [blinded, p.get("delivery"), p.get(path), p.get("delivery/source", value=value["id"]),
               p.get(f"delivery/mappings/{value['mapping_id']}")]
    for answer in answers:
        assert answer.status_code == 200 and _leaks(secrets, answer.text) == [], answer.request.url
    rows = [v for t in p.card(path)["tables"] for v in t["values"]]
    assert len(rows) == 11 and all(v["blinded"] and v["value"] is None and v["verbatim"] is None for v in rows)
    assert next(s for s in p.page()["subjects"] if s["label"] == "ABC-1")["blinded"] is True
    assert p.post(f"{path}/spot-check:draw").json()["detail"]["code"] == "BLINDED"
    assert p.post(f"{path}:confirm").json()["detail"]["code"] == "BLINDED" and p.events("signature.create") == []


# --- an ambiguous link, a product blinded through a study, stale draws, a mapping the table mapper made ---------------------


@pytest.mark.req("T-47", "F-404", "T-05")
def test_an_ambiguous_link_is_settled_by_choosing_one_of_the_studies_it_names(project):
    p = project()
    workbook = synthetic.messy_workbook()
    p.deliver(workbook)
    first = p.subject("230-23").rsplit("/", 1)[1]
    # another file's study 230-23 that was never joined to the workbook's (as a person who kept them apart left it)
    store = IntakeStore(p.ws)
    second = store.entities.append("entity", lambda seq: Entity(
        id=f"st-{seq}", type="study", label="230-23", key=name_key("230-23"), source=f"{'c' * 64}@workbook/1.0#s:'Cover'!A1",
        by="u1", at="2026-11-14T08:00:00.000Z").model_dump(mode="json")).body["id"]
    late = _late_samples()                                                # a third file whose title says "Study 230-23"
    p.deliver(late, preload=False)
    rows = [s for s in p.page()["subjects"] if s["label"] == "230-23"]
    assert len(rows) == 2                                                 # two candidates: nothing was joined
    local = next(s for s in rows if s["files"] == [_sha(late[1])])["subject"]
    assert local not in (first, second)
    path = f"delivery/subjects/study/{local}"
    card = p.card(path)
    (link,) = card["links"]
    assert (link["state"], link["study"], link["file"], link["link_fact"]) == ("ambiguous", local, late[0], None)
    assert link["candidates"] == [{"id": first, "label": "230-23"}, {"id": second, "label": "230-23"}]
    assert "LINK_UNCONFIRMED" in [b["code"] for b in card["blockers"]]
    assert not any(v["cross_file"] for t in card["tables"] for v in t["values"])
    body = {"file_sha256": link["file_sha256"], "confirmed": True, "why": "the late samples of the workbook's study"}
    # refused: a study the link does not name, an id that is none, a reader
    other = p.subject("231-24").rsplit("/", 1)[1]
    assert p.post(f"{path}:link", {**body, "study": other}).status_code == 422
    assert p.post(f"{path}:link", {**body, "study": "st-99999"}).status_code == 422
    assert p.post(f"{path}:link", {**body, "study": "../st-1"}).status_code == 422
    assert p.post(f"{path}:link", {**body, "study": first}, token="viewer").status_code == 403
    assert p.events("intake.link") == [] and store.entities.entries("merge") == []
    # one candidate refused, with the reason: it is no longer a candidate, and the link still waits
    refused = p.post(f"{path}:link", {**body, "study": second, "confirmed": False, "why": "another protocol's 230-23"})
    assert refused.status_code == 200, refused.text
    (still,) = refused.json()["data"]["links"]
    assert (still["state"], still["candidates"]) == ("ambiguous", [{"id": first, "label": "230-23"}])
    assert refused.json()["data"]["subject"] == local and store.entities.entries("merge") == []
    # the other chosen: the file's own study is merged into it, and the answer is the card of the study it became
    chosen = p.post(f"{path}:link", {**body, "study": first})
    assert chosen.status_code == 200, chosen.text
    merged = chosen.json()["data"]
    assert (merged["subject"], merged["label"], merged["links"]) == (first, "230-23", [])
    assert "LINK_UNCONFIRMED" not in [b["code"] for b in merged["blockers"]]
    joined = [v for t in merged["tables"] if t["file"] == late[0] for v in t["values"]]
    assert joined and all(v["cross_file"] and v["entity"]["study"] == first for v in joined)
    (merge,) = store.entities.entries("merge")
    assert (merge.body["from_id"], merge.body["into_id"], merge.body["by"]) == (local, first, "u1")
    events = p.events("intake.link")
    assert [e.reason for e in events] == ["another protocol's 230-23", "the late samples of the workbook's study"]
    assert [e.after["row_hash"] for e in events] == [line.hash for line in store.review.entries("link")]
    # the page lists one study 230-23 now, and the old id answers with the study it became
    (row,) = [s for s in p.page()["subjects"] if s["label"] == "230-23"]
    assert row["subject"] == first and sorted(row["files"]) == sorted([_sha(workbook.data), _sha(late[1])])
    assert p.card(path)["subject"] == first


@pytest.mark.req("T-47", "F-402")
def test_a_product_is_blinded_through_a_blinded_studys_value_on_every_route_and_the_compound_never_is(project):
    p = project(blinding=True)
    workbook = synthetic.messy_workbook()
    p.deliver(workbook)
    assert _accept_note(p, workbook).status_code == 200
    study_path, product_path = p.subject("230-23"), p.subject("Exampleamide IR tablet")
    secrets = _secrets(p.ws, "230-23")
    value = next(v for t in p.card(study_path)["tables"] for v in t["values"] if v["verbatim"] == "25.2")
    product = next(s for s in p.page()["subjects"] if s["label"] == "Exampleamide IR tablet")
    # a person says which product the study dosed: the study's profile is that product's too
    assigned = p.post("delivery/values:assign", {"targets": [value["id"].split("#")[0]], "product": product["subject"],
                                                 "batch": product["batches"][0]["id"], "why": "the study dosed this batch"})
    assert assigned.status_code == 200, assigned.text
    entered = p.post("delivery/subjects/compound/compound:enter", {"field": "phys.logp", "value": 2.4, "why": "the CoA"})
    assert entered.status_code == 200
    open_card = p.card(product_path)
    mine = [v for t in open_card["tables"] for v in t["values"]]
    of_study = [v for v in mine if v["labels"].get("study") == "230-23"]
    assert open_card["blinded"] is False and len(of_study) == 42 and len(_leaks(secrets, p.get(product_path).text)) > 10
    drawn = p.post(f"{product_path}/spot-check:draw").json()["data"]       # drawn while nothing was withheld
    failed = next(c for c in open_card["checks"] if c["severity"] == "fail" and c["code"] != "REQUIRED_ITEM_UNDISPOSED")

    blinded = p.post(f"{study_path}:enter", {"field": "intended_use", "value": "external_validation", "why": "the plan"})
    assert blinded.status_code == 200 and blinded.json()["data"]["blinded"] is True
    # the product is blinded with the study: every route that answers with it withholds the study's values
    answers = [p.get("delivery"), p.get(product_path), p.get(product_path, "viewer"),
               p.post(f"{product_path}:override", {"check_id": failed["id"], "why": "as written"}),
               p.post(f"{product_path}:dispose", {"req_id": open_card["requirements"][0]["req_id"], "disposition": "ask_client",
                                                  "why": "asked"}),
               p.post(f"{product_path}:enter", {"field": "strength_mg", "value": 50, "why": "the label"}),
               p.get("delivery/source", value=value["id"]), p.get("delivery/source", anchor=value["anchor"]),
               p.get(f"delivery/mappings/{value['mapping_id']}")]
    for answer in answers:
        assert answer.status_code == 200, (answer.request.url, answer.text[:300])
        assert _leaks(secrets, answer.text) == [], answer.request.url
    card = p.card(product_path)
    rows = [v for t in card["tables"] for v in t["values"]]
    theirs = [v for v in rows if v["labels"].get("study") == "230-23"]
    assert card["blinded"] is True and len(theirs) == 42
    assert all(v["blinded"] and [v[k] for k in ("value", "verbatim", "spread", "lloq", "censored")] == [None] * 5 for v in theirs)
    # the product's own values (its dissolution, its strength) are no study's: they are shown, and say so
    own = [v for v in rows if "study" not in v["labels"]]
    assert own and all(v["blinded"] is False for v in own) and any(v["field"] == "percent_dissolved" and v["value"] for v in own)
    assert all(c["message"] is None and c["values"] == [] for c in card["checks"]) and card["held"] is None
    assert "BLINDED" in [b["code"] for b in card["blockers"]]
    assert next(s for s in p.page()["subjects"] if s["subject"] == product["subject"])["blinded"] is True
    # its spot check can be neither drawn nor ticked, and it cannot be confirmed
    assert p.post(f"{product_path}/spot-check:draw").json()["detail"]["code"] == "BLINDED"
    ticks = {"draw_id": drawn["draw"]["id"], "ticks": [{"value_id": v, "ok": True} for v in drawn["wanted"]]}
    assert p.post(f"{product_path}/spot-check", ticks).json()["detail"]["code"] == "BLINDED"
    for token in ("t", "plain"):
        refused = p.post(f"{product_path}:confirm", token=token)
        assert refused.status_code == 409 and refused.json()["detail"]["code"] == "BLINDED"
    assert p.events("signature.create") == [] and p.events("intake.spot_check") == []
    # another product, with no value of the study, is open; and the compound's values are no study's: never blinded
    assert p.card(p.subject("Comparamide tablet"))["blinded"] is False
    compound = p.card("delivery/subjects/compound/compound")
    assert compound["blinded"] is False and [v["value"] for t in compound["tables"] for v in t["values"]] == [2.4]
    assert next(s for s in p.page()["subjects"] if s["subject_type"] == "compound")["blinded"] is False
    assert p.post("delivery/subjects/compound/compound/spot-check:draw").status_code == 200


@pytest.mark.req("T-47", "F-403", "T-06", "F-404", "T-05")
def test_a_stale_draw_is_drawn_again_with_its_ok_ticks_carried_and_a_failed_tick_stays_until_the_value_is_corrected(project):
    p = project()
    workbook = synthetic.messy_workbook()
    p.deliver(workbook)
    assert _accept_note(p, workbook).status_code == 200
    path = p.subject("230-23")
    _decide(p, path, FACTS_230_23)

    def enter(body: dict[str, Any]) -> dict[str, Any]:
        answer = p.post(f"{path}:enter", {**body, "why": "from the protocol"})
        assert answer.status_code == 200, answer.text
        return answer.json()["data"]

    def ticks(spot: dict[str, Any], wrong: str | None = None) -> dict[str, Any]:
        return {"draw_id": spot["draw"]["id"], "ticks": [{"value_id": v, "ok": v != wrong, "note": "" if v != wrong else "the file says 26.2"}
                                                         for v in spot["wanted"]]}

    # --- a draw goes stale when the subject's values change: its ticks are refused, and it is drawn again ---
    first = p.post(f"{path}/spot-check:draw").json()["data"]
    assert first["state"] == "drawn" and first["wanted"]
    assert enter({"field": "age_mean", "value": 33.0})["spot_check"] == {
        "state": "stale", "draw_id": first["draw"]["id"], "drawn": len(first["wanted"]), "wanted": 0}
    stale = p.post(f"{path}/spot-check", ticks(first))
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "STALE"
    assert p.events("intake.spot_check") == []
    second = p.post(f"{path}/spot-check:draw").json()["data"]
    assert second["draw"]["id"] != first["draw"]["id"] and second["state"] == "drawn" and second["draw"]["carried"] == {}
    assert p.post(f"{path}/spot-check", ticks(first)).json()["detail"]["code"] == "STALE"      # the old draw stays refused

    # --- one tick says a value does not match its source: the spot check has failed ---
    wrong = next(v["value"]["id"] for v in second["values"] if v["value"]["id"].startswith("tx-") and v["value"]["value"] is not None)
    ticked = p.post(f"{path}/spot-check", ticks(second, wrong))
    assert ticked.status_code == 200 and ticked.json()["data"]["state"] == "failed"
    record = ticked.json()["data"]["record"]
    assert [t for t in record["ticks"] if not t["ok"]] == [{"value_id": wrong, "ok": False, "note": "the file says 26.2"}]
    ok_before = {t["value_id"] for t in record["ticks"] if t["ok"]}
    assert [b["code"] for b in p.card(path)["blockers"]] == ["SPOT_CHECK"]

    # --- another change: the next draw carries the ok ticks, and holds the failed value as failed, with no new tick ---
    assert enter({"field": "weight_mean_kg", "value": 71.5})["spot_check"]["state"] == "stale"
    third = p.post(f"{path}/spot-check:draw").json()["data"]
    assert third["state"] == "failed" and third["draw"]["id"] not in (first["draw"]["id"], second["draw"]["id"])
    by_id = {v["value"]["id"]: v for v in third["values"]}
    assert (by_id[wrong]["reason"], by_id[wrong]["wanted"], by_id[wrong]["carried_by"], by_id[wrong]["ok"]) == (
        "always:failed", False, None, None)
    assert wrong in third["draw"]["always"] and wrong not in third["wanted"]
    carried = {i for i, v in by_id.items() if v["carried_by"] is not None}
    assert carried == ok_before & set(by_id) and len(carried) > 5
    assert all(by_id[i]["carried_by"] == record["id"] and not by_id[i]["wanted"] for i in carried)
    assert third["draw"]["carried"] == dict.fromkeys(sorted(carried), record["id"])
    assert set(third["wanted"]) == set(by_id) - carried - {wrong}                     # only what is new is ticked
    assert p.post(f"{path}/spot-check", {**ticks(third), "ticks": [*ticks(third)["ticks"], {"value_id": wrong, "ok": True}]}
                  ).status_code == 422                                                # a failed value takes no new tick
    again = p.post(f"{path}/spot-check", ticks(third))
    assert again.status_code == 200 and again.json()["data"]["state"] == "failed"     # ticked, and still failed
    refused = p.post(f"{path}:confirm")
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "SPOT_CHECK"
    assert "does not match its source" in refused.json()["detail"]["blockers"][0]["detail"] and p.events("signature.create") == []

    # --- only a correction clears it: the value is superseded, the draw is new, its ok ticks carry over ---
    corrected = enter({"value": 26.2, "supersedes": wrong})
    assert corrected["spot_check"]["state"] == "stale"
    _decide(p, path)                                                                  # what the correction changed, reviewed
    last = p.post(f"{path}/spot-check:draw").json()["data"]
    assert last["state"] == "drawn" and wrong not in {v["value"]["id"] for v in last["values"]}
    assert not [v for v in last["values"] if v["reason"] == "always:failed"]
    assert all(v["wanted"] != (v["carried_by"] is not None) for v in last["values"])
    assert {v["carried_by"] for v in last["values"] if v["carried_by"]} <= {record["id"], again.json()["data"]["record"]["id"]}
    done = p.post(f"{path}/spot-check", ticks(last))
    assert done.status_code == 200 and done.json()["data"]["state"] == "complete"
    assert len(p.events("intake.spot_check")) == 3
    card = p.card(path)
    assert card["blockers"] == [] and card["spot_check"]["state"] == "complete"
    signed = p.post(f"{path}:confirm")
    assert signed.status_code == 200, signed.text
    (confirmation,) = review.confirmations(p.ws)
    assert confirmation.record["spot_check"].startswith(done.json()["data"]["record"]["id"] + ":")
    # the signature binds the corrected value, not the one the tick refused
    fixed = next(v["id"] for t in corrected["tables"] for v in t["values"] if v["value"] == 26.2 and v["method"] == "person")
    assert [row[1] for row in confirmation.record["facts"] if row[0] == fixed] == ["26.2"]
    assert wrong in confirmation.record["excluded"]                       # its table is bound without the superseded value
    ledger = LedgerView(p.ws)
    assert (ledger.value(wrong).status, ledger.value(wrong).superseded_by, ledger.value(fixed).status) == ("superseded", fixed, "confirmed")
    assert len(p.events("signature.create")) == 1 and signed.json()["data"]["confirmation"]["landed"]["datasets"]


@pytest.mark.req("T-47", "T-21", "F-403", "T-06")
def test_a_table_the_table_mapper_mapped_blocks_until_a_person_approves_its_mapping(project, monkeypatch):
    p = project()
    spec = synthetic.URINE_SPEC.model_dump(mode="json", by_alias=True, exclude_none=True)
    model = Scripted([[("propose_mapping", {"spec": spec})], []])         # a scripted model, never a live one
    _models(monkeypatch, model)
    data = _urine_workbook()
    p.deliver(("urine.xlsx", data), preload=False)
    assert model.answers == ["ACCEPTED"] and len(model.received) == 2      # code accepted its mapping; the model stopped
    page = p.page()
    assert page["agents"]["enabled"] is True and page["running"] is False
    (file,) = page["deliveries"][0]["files"]
    (region,) = file["regions"]
    assert (region["state"], region["origin"], region["mapping_status"], file["coverage"]["silent_loss"]) == ("mapped", "llm", "proposed", 0)
    assert [s["stage"] for s in file["run"]["stages"] if s["stage"] == "map_llm" and s["ok"]] == ["map_llm"]
    # the mapping waits for a person: on the page, with who made it (the agent run named A4-table-mapper)
    (waiting,) = page["mappings"]
    (run,) = [r for r in agent_jobs.project_runs(p.store.root, "t1", "p1") if r["agent"] == "A4-table-mapper"]
    assert (waiting["status"], waiting["origin"], waiting["by"]) == ("proposed", "llm", f"agent:{run['run_id']}")
    assert waiting["origin_detail"].startswith("scripted/scripted prompt ") and waiting["origin_detail"].endswith(run["run_id"])
    mapping_path = f"delivery/mappings/{waiting['mapping_id']}"
    shown = p.get(mapping_path).json()["data"]
    assert (shown["origin"], shown["status"], shown["kind"], shown["findings"]) == ("llm", "proposed", spec["kind"], [])
    assert not any(ch.isdigit() for row in shown["sample"]["body"] for cell in row for ch in cell)
    # its values are in the ledger at level new_mapping, and that blocks the study's confirmation
    path = p.subject("230-31")
    card = p.card(path)
    values = [v for t in card["tables"] if t["kind"] == "table" for v in t["values"]]
    assert values and {v["level"] for v in values} == {"new_mapping"} and {t["mapping_status"] for t in card["tables"] if t["kind"] == "table"} == {"proposed"}
    assert [m["mapping_id"] for m in card["mappings"]] == [waiting["mapping_id"]]
    (unapproved,) = [c for c in card["checks"] if c["code"] == "MAPPING_NOT_APPROVED"]
    assert unapproved["severity"] == "fail" and not unapproved["overridden"] and "no person has approved" in unapproved["message"]
    assert "CHECK_FAILED" in [b["code"] for b in card["blockers"]]
    # everything else reviewed: the confirmation is still refused, for the mapping alone
    reviewed = p.card(path)
    facts = {"n": 6, "dose": 50, "route": "oral", "formulation": "ir_tablet", "intended_use": "model_building"}
    for field, fact in facts.items():
        assert p.post(f"{path}:enter", {"field": field, "value": fact, "why": "from the protocol",
                                        **({"unit": "mg"} if field == "dose" else {})}).status_code == 200
    reviewed = p.card(path)
    for check in reviewed["checks"]:
        if check["severity"] == "fail" and not check["overridden"] and check["code"] != "MAPPING_NOT_APPROVED":
            if check["code"] == "REQUIRED_ITEM_UNDISPOSED":
                for item in reviewed["requirements"]:
                    if item["status"] == "missing" and item["req_id"] in check["message"]:
                        assert p.post(f"{path}:dispose", {"req_id": item["req_id"], "disposition": "ask_client", "why": "asked"}).status_code == 200
            else:
                assert p.post(f"{path}:override", {"check_id": check["id"], "why": "as written"}).status_code == 200
    _spot_check(p, path)
    refused = p.post(f"{path}:confirm")
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "CHECK_FAILED"
    assert refused.json()["detail"]["blockers"][0]["ids"] == [unapproved["id"]] and p.events("signature.create") == []

    # --- a person approves the mapping: the file is read again from the cache, with no new model turn ---
    approved = p.post(f"{mapping_path}:approve", {"version": waiting["version"], "note": "read against the sheet"})
    assert approved.status_code == 200, approved.text
    assert (approved.json()["data"]["status"], approved.json()["data"]["queued"]) == ("approved", [_sha(data)])
    p.settle()
    assert len(model.received) == 2 and model.answers == ["ACCEPTED"]     # the approved version is read from the cache
    assert [r.state for r in intake_pipeline.runs(p.ws)] == ["done", "done"]
    assert len([r for r in agent_jobs.project_runs(p.store.root, "t1", "p1") if r["agent"] == "A4-table-mapper"]) == 1
    page = p.page()
    (region,) = page["deliveries"][0]["files"][0]["regions"]
    assert (region["state"], region["origin"], region["mapping_status"]) == ("mapped", "cache", "approved") and page["mappings"] == []
    card = p.card(path)
    assert {v["level"] for t in card["tables"] if t["kind"] == "table" for v in t["values"]} == {"approved_mapping"}
    assert "MAPPING_NOT_APPROVED" not in {c["code"] for c in card["checks"]} and card["mappings"] == []
    # the same values under the same mapping: the draw stands, and the confirmation is possible
    assert card["spot_check"]["state"] == "complete" and card["blockers"] == []
    signed = p.post(f"{path}:confirm")
    assert signed.status_code == 200, signed.text
    (confirmation,) = review.confirmations(p.ws)
    assert [row[2] for row in confirmation.record["mappings"]] == ["approved"]
    assert signed.json()["data"]["signature"]["signature_id"] == confirmation.signature_id
    assert [len(p.events(a)) for a in ("signature.create", "intake.confirm", "intake.land")] == [1, 1, 1]
    # urine excretion is kept in the ledger and not landed: the card said so before the signature, and the record does
    assert any("excretion" in text for text in signed.json()["data"]["confirmation"]["held"])


def test_a_subjects_card_is_computed_once_per_request(project, monkeypatch):
    p = project()
    p.deliver(synthetic.word_report())
    path = p.subject("230-27")
    calls: list[str] = []
    real = review._card
    monkeypatch.setattr(review, "_card", lambda *a, **k: calls.append(a[2]) or real(*a, **k))
    card = p.get(path)
    assert card.status_code == 200 and card.json()["data"]["blockers"] and card.json()["data"]["checks"]
    assert len(calls) == 1                                    # the card and its blockers: the checks run once
    calls.clear()
    assert p.post(f"{path}/spot-check:draw").status_code == 200 and calls == []      # a draw needs no card
