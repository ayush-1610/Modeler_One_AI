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
from typing import Any, get_args

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from openpyxl import Workbook
from pydantic import BaseModel

from modeler_agents.evals.scripted import Scripted
from modeler_api import admin_api, agent_jobs, client_api, delivery_routes, intake_pipeline_jobs, jobs, project_api
from modeler_api.auth import get_verifier
from modeler_api.main import app
from modeler_api.views.common import View
from modeler_intake import synthetic
from modeler_intake.document_reading import name_key
from modeler_intake.fields import CONDITION_FIELDS, FIELDS, LABEL_FIELDS, SpreadKind, Statistic
from modeler_intake.mapping.fingerprint import layout_fingerprint
from modeler_intake.mapping_spec import Role
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
from modeler_project.dataset_register import dataset, decide_dataset, propose_dataset
from modeler_project.dataset_register import datasets as all_datasets
from modeler_project.datasets import ObservedDataset, Origin, Series
from modeler_project.evidence import EvidenceState, SourceRef
from modeler_project.inputs import refresh_inputs
from modeler_project.intake_rules import RULES_SHA256
from modeler_project.intake_store import IntakeStore
from modeler_project.ledger import Ledger
from modeler_project.ledger_models import Entity
from modeler_project.ledger_view import LedgerView
from modeler_project.mapping_cache import MappingCache, mapping_id_of
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
        {"where": OUTSIDE_NOTE, "text": "Note: 3 samples were re-assayed on day 14", "region": None, "counted": True,
         "decision": None, "restored": None}]
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


@pytest.mark.req("T-47", "F-404", "T-05")
def test_a_reading_that_ends_while_an_answer_is_put_together_leaves_it_saying_reading(project, monkeypatch):
    """The runs are read before what a run writes (final review round 4): a reading that ends while the delivery page or
    a layout is put together leaves the answer saying the file is being read, so the page reads it again. It never says
    "not reading" beside the coverage from before the reading (To do kept a table's row the reading had cleared)."""
    p = project()
    p.deliver(("loose-profile.csv", LOOSE))
    record = intake_landing.file_records(IntakeStore(p.ws))[_sha(LOOSE)]
    (row,) = p.page()["mappings"]
    monkeypatch.setattr(intake_pipeline_jobs, "kick", lambda *args, **kwargs: False)     # no job: the test ends the run
    original = IntakeStore.coverage
    ended: list[str] = []

    def coverage(self: IntakeStore, sha256: str):
        found = original(self, sha256)                     # the coverage, read before the reading ends ...
        if not ended:                                      # ... and the reading ends right after, mid-answer
            ended.append(sha256)
            intake_pipeline.run_file(p.ws, intake_pipeline.take(p.ws))
        return found

    monkeypatch.setattr(IntakeStore, "coverage", coverage)
    for path, flag in (("delivery", "running"), (f"delivery/mappings/{row['mapping_id']}", "waiting")):
        ended.clear()
        (queued,) = intake_pipeline.enqueue(p.ws, [record], by="u1", again=True)
        mid = p.get(path).json()["data"]
        assert ended and mid[flag] is True, path                                            # read again: it was reading
        assert intake_pipeline.runs(p.ws)[-1].run_id == queued.run_id and intake_pipeline.runs(p.ws)[-1].state == "done"
        after = p.get(path).json()["data"]
        assert after[flag] is False, path                                                   # and now it is all current
    files = p.page()["deliveries"][0]["files"]
    assert [(f["state"], f["run"]["state"]) for f in files] == [("read", "done")]


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
    # the field a check names, and a unit check's unit, apart from its message: the page says them in words (round 6)
    above = next(c for c in card["checks"] if c["code"] == "ABOVE_RANGE")
    assert (above["field"], above["unit"]) == ("concentration", None) and above["message"].startswith("concentration: ")
    assert "n" in {c["field"] for c in card["checks"] if c["code"] == "LANDING_FIELD_MISSING"}
    unchecked = [c for c in card["checks"] if c["code"] == "UNIT_NOT_CHECKED"]
    assert unchecked and all(c["message"].startswith(f"{c['field']}: values in {c['unit']!r}") for c in unchecked)
    assert [(r["req_id"], r["status"]) for r in card["requirements"]] == [
        ("REQ-sys.demographics", "missing"), ("REQ-obs.bioanalytical", "found")]
    assert card["conflicts"] == [] and card["links"] == [] and card["mappings"] == []
    # what the landing would hold back, or why it cannot be planned yet
    assert card["held"] == [] and "the study record needs n" in card["landing_problem"]
    assert card["spot_check"] == {"state": "none", "draw_id": None, "drawn": 0, "always": 0, "wanted": 0, "recorded_by": None,
                                  "recorded_at": None}
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
    # of the values drawn, those always checked: drawn again in any new draw, their ticks with them (said before a
    # person's entry draws it again, final review round 3)
    always = len([v for v in spot["values"] if (v["reason"] or "").startswith("always:")])
    assert always and always == len(set(draw["always"]))
    assert p.card(path)["spot_check"] == {"state": "drawn", "draw_id": draw["id"], "drawn": len(spot["wanted"]), "always": always,
                                         "wanted": len(spot["wanted"]), "recorded_by": None, "recorded_at": None}
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
    # who recorded it and when, on the card (its one-line result); shown again by a read, which draws nothing (OWN-9)
    (record_line,) = [e for e in IntakeStore(p.ws).review.entries() if e.kind == "spot_check"]
    assert (card["spot_check"]["recorded_by"], card["spot_check"]["recorded_at"]) == ("u1", record_line.body["at"])
    draws = len([e for e in IntakeStore(p.ws).review.entries() if e.kind == "spot_draw"])
    shown = p.get(f"{path}/spot-check", token="viewer")
    assert shown.status_code == 200 and shown.json()["data"]["state"] == "complete"
    assert shown.json()["data"]["draw"]["id"] == draw["id"] and shown.json()["data"]["record"]["by"] == "u1"
    assert len([e for e in IntakeStore(p.ws).review.entries() if e.kind == "spot_draw"]) == draws

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
    assert row["confirmation"]["landed_datasets"] == shown["landed"]["datasets"]     # the page counts what loaded from it
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
    assert conflict["time_unit"] is None                                   # a dose has no time
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


SHORT = b"Time (h),Mean concentration (ng/mL),SD\n0.5,11.5,2.1\n1,24.25,4.4\n"


@pytest.mark.req("T-47", "F-404", "T-05")
def test_a_layout_is_shown_on_the_table_it_was_opened_from_and_says_how_each_version_reads_each_table(project):
    """Final review OWN-2, OWN-15: a layout opened from a table's row is shown on that table at the version named; every
    table of the layout says the version it is read with and whether the version shown reads it; a table the newest
    approved version cannot read stays with an older one, and its region says which and why."""
    p = project()
    p.deliver(("loose-profile.csv", LOOSE), ("short-profile.csv", SHORT))
    loose, short = _sha(LOOSE), _sha(SHORT)
    (row,) = p.page()["mappings"]
    path = f"delivery/mappings/{row['mapping_id']}"
    regions = {u["file_sha256"]: u["region_id"] for u in row["used_in"]}
    assert set(regions) == {loose, short}
    assert p.post(f"{path}:approve", {"version": 1, "note": "checked"}).status_code == 200
    p.settle()
    spec = p.get(path).json()["data"]["spec"]
    # a version that reads the long table to its last row: the short table has fewer rows
    edited = p.post(f"{path}:edit", {"spec": {**spec, "last_data_row": 5}, "why": "the table ends at row 5",
                                     "file_sha256": loose, "region_id": regions[loose]})
    assert edited.status_code == 200, edited.text
    assert (edited.json()["data"]["version"], edited.json()["data"]["sample"]["file_sha256"]) == (2, loose)
    p.settle()
    approved = p.post(f"{path}:approve", {"version": 2, "note": "checked", "file_sha256": short, "region_id": regions[short]})
    assert approved.status_code == 200, approved.text
    assert approved.json()["data"]["sample"]["file_sha256"] == short                       # shown on the table named
    p.settle()
    by_file = {f["sha256"]: f["regions"][0] for d in p.page()["deliveries"] for f in d["files"]}
    assert (by_file[loose]["mapping_version"], by_file[loose]["newer"]) == (2, None)
    held = by_file[short]
    assert (held["mapping_version"], held["newer"]["version"]) == (1, 2)
    assert [f["code"] for f in held["newer"]["findings"]] == ["CELL_OUTSIDE_REGION"]
    # the newest version shown on the short table: it does not read it; each table says how it is read
    shown = p.get(path, version=2, file_sha256=short, region_id=regions[short]).json()["data"]
    sample = shown["sample"]
    assert (sample["file"], sample["header_rows"], sample["header"], sample["body_rows"]) == (
        "short-profile.csv", 1, [["Time (h)", "Mean concentration (ng/mL)", "SD"]], [2, 3])
    tables = {t["file_sha256"]: t for t in shown["tables"]}
    assert (tables[loose]["version"], tables[loose]["reads"], tables[loose]["findings"], tables[loose]["newer"]) == (2, True, [], None)
    assert (tables[short]["version"], tables[short]["reads"], tables[short]["newer"]["version"]) == (1, False, 2)
    assert [f["code"] for f in tables[short]["findings"]] == ["CELL_OUTSIDE_REGION"]
    # version 1 on the same table reads both tables; the newer one that does not is still named beside the short one
    first = p.get(path, version=1, file_sha256=short, region_id=regions[short]).json()["data"]
    assert {t["file_sha256"]: (t["version"], t["reads"]) for t in first["tables"]} == {loose: (2, True), short: (1, True)}
    assert next(t for t in first["tables"] if t["file_sha256"] == short)["newer"]["version"] == 2
    # refusals: the table named by both or neither, a file that never arrived, a region of no table of this layout
    assert p.get(path, file_sha256=short).status_code == 422
    assert p.get(path, file_sha256=_sha(b"never sent"), region_id=regions[short]).status_code == 404
    assert p.get(path, file_sha256=short, region_id="rg-0123456789").status_code == 409
    assert p.post(f"{path}:approve", {"version": 2, "file_sha256": short}).status_code == 422


@pytest.mark.req("T-47", "F-404", "T-05")
def test_a_version_waiting_for_approval_says_which_tables_its_approval_moves_to_it_and_what_changes(project):
    """Final review round 3 (the gate-todo review): approving a layout version can move other tables of its layout to it
    (the pipeline's own choice: the fewest numbers unread, then the most facts read once, then the newest), which
    changes what they read. Before the approval, each table of the version says whether it moves and what changes; the
    approval then does exactly that."""
    p = project()
    p.deliver(("loose-profile.csv", LOOSE), ("short-profile.csv", SHORT))
    loose, short = _sha(LOOSE), _sha(SHORT)
    (row,) = p.page()["mappings"]
    path = f"delivery/mappings/{row['mapping_id']}"
    spec = p.get(path).json()["data"]["spec"]
    # a version that does not read the SD column, approved first: both tables are read with it, their SDs left unread
    columns = [c for c in spec["columns"] if c["role"] != "spread"]
    edited = p.post(f"{path}:edit", {"spec": {**spec, "columns": columns}, "why": "the SD column is read later"})
    assert edited.status_code == 200, edited.text
    p.settle()
    assert p.post(f"{path}:approve", {"version": 2, "note": "checked"}).status_code == 200
    p.settle()

    def read_with() -> list[tuple[int, int]]:
        regions = {f["sha256"]: f["regions"][0] for d in p.page()["deliveries"] for f in d["files"]}
        return [(regions[x]["mapping_version"], regions[x]["silent"]) for x in (loose, short)]

    assert read_with() == [(2, 4), (2, 2)]
    # version 1 waits for approval: approving it moves both tables to it, each then reading its SDs
    waiting = p.get(path, version=1).json()["data"]
    assert waiting["status"] == "proposed"
    assert {t["file_sha256"]: t["moves"] for t in waiting["tables"]} == {
        loose: {"from_version": 2, "unread_before": 4, "unread_after": 0, "facts_lost": [], "facts_gained": []},
        short: {"from_version": 2, "unread_before": 2, "unread_after": 0, "facts_lost": [], "facts_gained": []}}
    # the approved version moves nothing: it is what they are read with
    assert [t["moves"] for t in p.get(path, version=2).json()["data"]["tables"]] == [None, None]
    # approved, both are read with it, as it said; nothing is left to move
    assert p.post(f"{path}:approve", {"version": 1, "note": "checked"}).status_code == 200
    p.settle()
    assert read_with() == [(1, 0), (1, 0)]
    assert [t["moves"] for t in p.get(path, version=1).json()["data"]["tables"]] == [None, None]


@pytest.mark.req("T-47", "F-404", "T-05")
def test_a_read_tables_numbers_no_part_of_its_layout_reads_are_listed_with_why(project):
    """Final review OWN-2 (b): a read table's numbers its layout leaves unread are listed on its region, read-only, with
    the reason code's reading records: a value that is not a plain number, a column the layout does not read."""
    p = project()
    odd = b'Time (h),Mean concentration (ng/mL),SD\n0.5,11.5,2.1\n1,"1,2",4.4\n2,18.75,3.9\n'
    p.deliver(("odd-profile.csv", odd))
    page = p.page()
    (region,) = page["deliveries"][0]["files"][0]["regions"]
    # the value that is not a plain number, and its SD, which then qualifies no value
    assert (region["state"], region["silent"]) == ("mapped", 2)
    assert [(c["where"], c["text"], c["why"]) for c in region["silent_cells"]] == [
        ("s:'odd-profile'!B3", "1,2", "unparseable"), ("s:'odd-profile'!C3", "4.4", "")]
    # a version that does not read the SD column: its numbers are listed too, as read by no part of the layout
    (row,) = page["mappings"]
    path = f"delivery/mappings/{row['mapping_id']}"
    spec = p.get(path).json()["data"]["spec"]
    columns = [c for c in spec["columns"] if c["role"] != "spread"]
    edited = p.post(f"{path}:edit", {"spec": {**spec, "columns": columns}, "why": "the SD column is read later"})
    assert edited.status_code == 200, edited.text
    p.settle()
    assert p.post(f"{path}:approve", {"version": edited.json()["data"]["version"], "note": "checked"}).status_code == 200
    p.settle()
    (region,) = p.page()["deliveries"][0]["files"][0]["regions"]
    said = {c["text"]: c["why"] for c in region["silent_cells"]}
    assert said == {"1,2": "unparseable", "2.1": "", "4.4": "", "3.9": ""} and region["silent"] == 4


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
        p.post("delivery/regions:restore", {"file_sha256": _sha(workbook.data), "regions": [OUTSIDE_NOTE],
                                            "scope": "outside", "why": "a number after all"}),
    ]
    p.settle()
    for answer in answers:
        assert answer.status_code == 200, (answer.request.url, answer.text[:300])
        assert _leaks(secrets, answer.text) == [], answer.request.url
    # a person's layout refused on a blinded study's table: the validator's findings name no digit of it
    region_id = next(t["region_id"] for t in open_card["tables"] if any(v["id"] == value["id"] for v in t["values"]))
    broken = {**p.get(mapping).json()["data"]["spec"], "first_data_row": 99}
    refused = p.post("delivery/mappings:propose", {"file_sha256": value["file_sha256"], "region_id": region_id,
                                                   "spec": broken, "why": "a first layout"})
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "MAPPING_INVALID"
    assert not any(ch.isdigit() for f in refused.json()["detail"]["findings"] for ch in f["message"])
    assert _leaks(secrets, refused.text) == []
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
    assert all(c["field"] is None and c["unit"] is None for c in card["checks"])               # as its message (round 6)
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
    assert (p.card(path)["loaded_elsewhere"], p.card(path)["proposed_elsewhere"]) == ([], [early.id])   # not confirmed
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
        "delivery/regions:restore": {"file_sha256": sha, "regions": ["rg-0123456789"], **why},
        "delivery/mappings:propose": {"file_sha256": sha, "region_id": "rg-0123456789", "spec": {}, **why},
        "delivery/mappings/mp-0123456789ab:approve": {"version": 1},
        "delivery/mappings/mp-0123456789ab:reject": {"version": 1, **why},
        "delivery/mappings/mp-0123456789ab:edit": {"spec": {}, **why},
        f"{subject}:override": {"check_id": "ck-0123456789ab", **why},
        f"{subject}:dispose": {"req_id": "REQ-x", "disposition": "ask_client", **why},
        f"{subject}:choose": {"conflict_id": "cx-0123456789", "keep": "f-1", **why},
        f"{subject}:link": {"file_sha256": sha, "confirmed": True}, f"{subject}:enter": {"field": "route", "value": "oral", **why},
        f"{subject}:confirm": None, f"{subject}/spot-check:draw": None,
        f"{subject}/spot-check": {"draw_id": "sd-1", "ticks": []}}
    gets = ["delivery/source?value=f-1", "delivery/mappings/mp-0123456789ab", subject, "delivery/vocabulary", f"{subject}/spot-check"]
    answers = [p.post(path, body) for path, body in posts.items()] + [p.get(path) for path in gets]
    for answer in answers:
        assert answer.status_code == 409, (answer.request.url, answer.text)
        assert answer.json()["detail"]["code"] == "INTAKE_PIPELINE_OFF"
    # every /delivery route but the page was asked, and nothing was written: no intake folder, no event
    mounted = {(m, r.path) for r in client_api.router.routes if isinstance(r, APIRoute) and "/delivery" in r.path for m in r.methods}
    assert len(mounted) == len(posts) + len(gets) + 1 == 22
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
    assert len(handlers) == 22 and all(h.__module__ == "modeler_api.delivery_routes" for h in handlers)


def test_every_delivery_route_and_the_admin_pipeline_route_has_a_typed_answer():
    routes = [r for router in (client_api.router, admin_api.router) for r in router.routes
              if isinstance(r, APIRoute) and ("/delivery" in r.path or r.path.endswith("/admin/pipeline"))]
    assert len(routes) == 23
    names = set()
    for route in routes:
        model = route.response_model
        assert isinstance(model, type) and issubclass(model, BaseModel), route.path
        data = model.model_fields["data"].annotation
        assert isinstance(data, type) and issubclass(data, View), route.path           # a model, never Envelope[dict]
        names.add(data.__name__)
        assert route.response_model_exclude_unset is True
    assert names == {"DeliveryPage", "DeliverySubject", "DeliverySource", "DeliveryMapping", "DeliverySpotCheck",
                     "DeliveryMappingVocabulary", "TriageStart", "PipelineHealth"}
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
    assert p.card(path)["proposed_elsewhere"] == [legacy_id]               # Delivery shows what the legacy card holds
    assert p.card(path)["loaded_elsewhere"] == []                          # proposed: not in the model yet
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
        "state": "stale", "draw_id": first["draw"]["id"], "drawn": len(first["wanted"]),
        "always": len(set(first["draw"]["always"])), "wanted": 0, "recorded_by": None, "recorded_at": None}
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


@pytest.mark.req("T-47", "F-403", "T-06")
def test_the_card_says_which_decisions_draw_its_spot_check_again_as_the_review_rule_does(project):
    """A spot check drawn is drawn again when the subject's digest changes or a check accepted as is names a value the draw
    does not hold (`intake_review._stale`, unchanged). The card says it before each decision (final review round 4):
    `outside_draw` for "Accept as is", `computed` for the analyte stated. Settling a required item never draws it again;
    keeping one value of a disagreement always does; a refused link does when its file gives values."""
    p = project()
    workbook = synthetic.messy_workbook()
    p.deliver(workbook)
    late = _late_samples()                                  # its means name no analyte
    p.deliver(late, preload=False)
    assert _accept_note(p, workbook).status_code == 200
    path = p.subject("230-23")

    def state() -> str:
        return p.card(path)["spot_check"]["state"]

    def decide(route: str, body: dict[str, Any]) -> dict[str, Any]:
        answer = p.post(f"{path}:{route}", {**body, "why": "from the protocol"})
        assert answer.status_code == 200, answer.text
        return answer.json()["data"]

    # no draw: no value is outside it
    assert all(c["outside_draw"] == 0 for c in p.card(path)["checks"])
    (link,) = p.card(path)["links"]
    decide("link", {"file_sha256": link["file_sha256"], "link_fact": link["link_fact"], "confirmed": True})
    draw = p.post(f"{path}/spot-check:draw").json()["data"]["draw"]
    held = {*draw["always"], *draw["sampled"], *draw["carried"]}
    card = p.card(path)
    assert card["spot_check"]["state"] == "drawn"
    opened = {c["id"]: c for c in card["checks"] if c["severity"] == "fail" and not c["overridden"]}
    for check in opened.values():
        assert check["outside_draw"] == len({v for v in check["values"] if v not in held}), check["code"]
    # --- settling a required item changes no value: the draw stands ---
    item = next(r for r in card["requirements"] if r["status"] == "missing")
    decide("dispose", {"req_id": item["req_id"], "disposition": "ask_client"})
    assert state() == "drawn"
    # --- accepted as is: drawn again exactly when a value of the check is outside the draw ---
    inside = [c for c in opened.values() if c["values"] and not c["outside_draw"] and c["code"] not in ("ANALYTE_MISSING", "MAPPING_NOT_APPROVED")]
    outside = [c for c in opened.values() if c["outside_draw"]]
    assert inside and outside
    for check in inside:
        decide("override", {"check_id": check["id"]})
        assert state() == "drawn", check["code"]
    decide("override", {"check_id": outside[0]["id"]})
    assert state() == "stale"
    p.post(f"{path}/spot-check:draw")
    # --- the analyte stated: the values keep their ids, and only what is computed from them changes ---
    card = p.card(path)
    values = {v["id"]: v for t in card["tables"] for v in t["values"]}
    analytes = p.page()["analytes"]

    def state_analyte(ids: list[str], analyte: str) -> None:
        """As "State it…" does: the values linked again with what they are linked to, and the analyte."""
        first = values[ids[0]]["entity"]
        linked = {r: first[r] for r in ("study", "arm", "product", "batch") if first.get(r)}
        answer = p.post("delivery/values:assign", {"targets": ids, "why": "the bioanalytical report", "analyte": analyte, **linked})
        assert answer.status_code == 200, answer.text

    (missing,) = [c for c in card["checks"] if c["code"] == "ANALYTE_MISSING" and not c["overridden"]]
    assert missing["computed"] == 0                                    # nothing is computed from the late means
    state_analyte(missing["values"], analytes[0]["id"])
    assert state() == "drawn"
    # the metabolite's means come with an SE: an SD is computed from each, which their analyte linked again computes anew
    se = [v["id"] for v in values.values() if v["spread_kind"] == "SE" and v["entity"].get("analyte")]
    reader = LedgerView(p.ws)
    assert se and review.computed_from(reader, "study", card["subject"], se) == len(se)
    other = next(a["id"] for a in analytes if a["id"] != values[se[0]]["entity"]["analyte"])
    state_analyte(se, other)
    assert state() == "stale"
    p.post(f"{path}/spot-check:draw")
    # --- one value of a disagreement kept: the others are set aside, so the draw no longer describes the study ---
    entered = decide("enter", {"field": "dose", "value": 60, "unit": "mg"})
    p.post(f"{path}/spot-check:draw")
    conflict = next(c for c in p.card(path)["conflicts"] if c["field"] == "dose")
    assert entered["conflicts"] and state() == "drawn"
    decide("choose", {"conflict_id": conflict["id"], "keep": conflict["values"][0]})
    assert state() == "stale"
    p.post(f"{path}/spot-check:draw")
    # --- a link refused: its file's values leave the study ---
    assert link["values"] > 0
    decide("link", {"file_sha256": link["file_sha256"], "link_fact": link["link_fact"], "confirmed": False})
    assert state() == "stale"


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


# --- what a person fills in (plan 2026-11-14 §3): arms, batches, analytes; a table's first layout; demographics;
# --- a "not data" decision restored; the client-review groups of the same source

ODD = b"Hrs (h),Result (ng/mL)\n0.5,1.2\n1,2.3\n2,3.4\n"     # a table no rule reads: unread, with no model configured
ODD_SPEC = {"schema": "mapping/2", "kind": "pk_summary", "layout": "long", "header_rows": 1, "first_data_row": 2,
            "field": "concentration", "statistic": "arithmetic_mean", "time_unit": "h", "time_unit_cite": {"row": 1, "column": 1},
            "value_unit": "ng/mL", "value_unit_cite": {"row": 1, "column": 2},
            "columns": [{"column": 1, "role": "time"}, {"column": 2, "role": "value"}]}


@pytest.mark.req("T-47", "F-404", "T-05")
def test_values_are_assigned_to_a_new_arm_batch_or_analyte_never_a_duplicate(project):
    p = project()
    p.deliver(synthetic.messy_workbook(), synthetic.pdf_report(unruled_table=False), ("loose-profile.csv", LOOSE))
    page = p.page()
    extract = page["unassigned"][0]["id"].split("#")[0]
    subjects = {s["label"]: s for s in page["subjects"]}
    study, product = subjects["230-26"], subjects["Exampleamide IR tablet"]
    cohort = next(a for a in study["arms"] if a["label"] == "Cohort 1")
    body = {"targets": [extract], "study": study["subject"], "why": "the Test arm, per the file name"}
    entities = len(IntakeStore(p.ws).entities.entries("entity"))
    # refused, and nothing is written: an arm with no study; an arm by id and by name; a batch with no product; a name
    # too long; an analyte id that is no analyte's; an analyte by id and by name; an arm the study has, however spelt
    for wrong, status in (({"study": None, "product": product["subject"], "new_arm": "Test"}, 422),
                          ({"arm": cohort["id"], "new_arm": "Test"}, 422), ({"new_batch": "L2302"}, 422),
                          ({"new_arm": "T" * 81}, 422), ({"analyte": study["subject"]}, 404),
                          ({"new_analyte": "M1", "analyte": "an-99999"}, 422), ({"new_arm": "COHORT-1"}, 409)):
        refused = p.post("delivery/values:assign", {**body, **wrong})
        assert refused.status_code == status, (wrong, refused.text)
    duplicate = p.post("delivery/values:assign", {**body, "new_arm": "cohort 1"}).json()["detail"]
    assert duplicate["code"] == "CONFLICT"
    assert f"an arm named 'Cohort 1' exists already in '230-26' ({cohort['id']})" in duplicate["message"]
    assert len(IntakeStore(p.ws).entities.entries("entity")) == entities and p.events("intake.entity") == []
    assert p.events("intake.assign") == []

    # named: the arm is created in its study, the analyte beside it, and the values are theirs
    assigned = p.post("delivery/values:assign", {**body, "new_arm": "Test", "new_analyte": "M1"})
    assert assigned.status_code == 200, assigned.text
    after = assigned.json()["data"]
    row = next(s for s in after["subjects"] if s["subject"] == study["subject"])
    test = next(a for a in row["arms"] if a["label"] == "Test")
    assert [a["label"] for a in row["arms"]] == ["Cohort 1", "Cohort 2", "Test"] and after["unassigned"] == []
    view = LedgerView(p.ws)
    values = [v for v in view.values(study=study["subject"]) if v.id.startswith(extract)]
    analyte = view.entity(values[0].entity.analyte)
    assert len(values) == 4 and {v.entity.arm for v in values} == {test["id"]} and analyte.label == "M1"
    assert (analyte.type, analyte.parent, analyte.source) == ("analyte", None, None)
    assert [(e.after["type"], e.after["label"], e.after.get("parent")) for e in p.events("intake.entity")] == [
        ("arm", "Test", study["subject"]), ("analyte", "M1", None)]
    again = p.post("delivery/values:assign", {**body, "new_arm": "test"})
    assert again.status_code == 409 and test["id"] in again.json()["detail"]["message"]
    assert p.post("delivery/values:assign", {**body, "new_analyte": "m-1"}).status_code == 409

    # a batch in its product, never a duplicate there; an analyte by its id. The assignment replaces the earlier one
    batch = {"targets": [extract], "product": product["subject"], "analyte": analyte.id, "why": "the client's new batch"}
    assert p.post("delivery/values:assign", {**batch, "new_batch": "l2301"}).status_code == 409
    moved = p.post("delivery/values:assign", {**batch, "new_batch": "L2302"})
    assert moved.status_code == 200, moved.text
    row = next(s for s in moved.json()["data"]["subjects"] if s["subject"] == product["subject"])
    assert [b["label"] for b in row["batches"]] == ["L2301", "L2302"]
    values = [v for v in LedgerView(p.ws).values(product=product["subject"]) if v.id.startswith(extract)]
    assert len(values) == 4 and {v.entity.analyte for v in values} == {analyte.id} and {v.entity.study for v in values} == {None}
    # a new study and its first arm, in one assignment
    fresh = p.post("delivery/values:assign", {"targets": [extract], "new_study": "ABC-7", "new_arm": "Reference",
                                              "why": "the title says study ABC-7, reference arm"})
    assert fresh.status_code == 200, fresh.text
    row = next(s for s in fresh.json()["data"]["subjects"] if s["label"] == "ABC-7")
    assert [a["label"] for a in row["arms"]] == ["Reference"]
    # what the Inputs page offers for them: the brief's parent drug and the intake vocabulary's matrix words
    options = p.get("inputs").json()["data"]["study_options"]
    assert options["analyte"] == [synthetic.DRUG] and options["matrix"] == list(FIELDS["matrix"].choices)


@pytest.mark.req("T-47", "F-404", "T-05")
def test_a_table_no_layout_reads_gets_a_persons_first_layout_checked_on_it_and_read(project):
    p = project()
    p.deliver(("odd-profile.csv", ODD))
    sha = _sha(ODD)
    page = p.page()
    (region,) = page["deliveries"][0]["files"][0]["regions"]
    assert (region["state"], region["mapping_id"]) == ("unread", None) and page["mappings"] == []
    assert page["totals"]["silent_loss"] == 6
    body = {"file_sha256": sha, "region_id": region["region_id"], "spec": ODD_SPEC, "why": "hours, and the mean level"}
    # refused, and nothing is written: a reader; no reason; a file never sent; a region it has not; an id that is none;
    # not a spec; a spec that does not read the table (the validator's findings)
    assert p.post("delivery/mappings:propose", body, token="viewer").status_code == 403
    assert p.post("delivery/mappings:propose", {**body, "why": ""}).status_code == 422
    assert p.post("delivery/mappings:propose", {**body, "file_sha256": _sha(b"never sent")}).status_code == 404
    assert p.post("delivery/mappings:propose", {**body, "region_id": "rg-0123456789"}).status_code == 404
    assert p.post("delivery/mappings:propose", {**body, "region_id": "../rg-1"}).status_code == 422
    assert p.post("delivery/mappings:propose", {**body, "spec": {**ODD_SPEC, "layout": "sideways"}}).status_code == 422
    unreadable = p.post("delivery/mappings:propose", {**body, "spec": {**ODD_SPEC, "columns": [{"column": 2, "role": "value"}]}})
    assert unreadable.status_code == 422 and unreadable.json()["detail"]["code"] == "MAPPING_INVALID"
    assert "LAYOUT" in [f["code"] for f in unreadable.json()["detail"]["findings"]]
    assert MappingCache(p.ws).entries() == [] and p.events("intake.mapping.propose") == []

    # proposed: a person's version of the table's layout, its file read again
    proposed = p.post("delivery/mappings:propose", body)
    assert proposed.status_code == 200, proposed.text
    mapping = proposed.json()["data"]
    doc = parse_document(ODD, "odd-profile.csv")
    assert mapping["mapping_id"] == mapping_id_of(layout_fingerprint(region_grid(doc, region["region_id"])))
    assert (mapping["version"], mapping["status"], mapping["origin"], mapping["origin_detail"], mapping["queued"]) == (
        1, "proposed", "person", "u1", [sha])
    assert mapping["findings"] == [] and mapping["sample"]["file"] == "odd-profile.csv"
    (event,) = p.events("intake.mapping.propose")
    line = IntakeStore(p.ws).mappings.entries("entry")[-1]
    assert event.after == {"mapping_id": mapping["mapping_id"], "version": 1, "file_sha256": sha,
                           "region_id": region["region_id"], "spec_sha256": event.after["spec_sha256"], "row_hash": line.hash}
    assert event.reason == "hours, and the mean level"
    # the words a form edits a layout with: the intake package's own, never made up in the web
    vocabulary = mapping["vocabulary"]
    assert vocabulary["roles"] == list(get_args(Role)) and vocabulary["statistics"] == list(get_args(Statistic))
    assert vocabulary["spread_kinds"] == list(get_args(SpreadKind)) and vocabulary["cite_near"] == ["caption", "above", "below"]
    assert vocabulary["time_references"] == ["first_dose", "last_dose", "occasion_dose"] and "pk_summary" in vocabulary["kinds"]
    fields = {f["name"]: f for f in vocabulary["fields"]}
    assert set(fields) == {n for n, f in FIELDS.items() if not f.person_only} and fields["matrix"]["choices"] == list(FIELDS["matrix"].choices)
    assert (fields["concentration"]["level"], fields["concentration"]["unit_class"]) == ("observation", "concentration")
    assert vocabulary["conditions"] == list(CONDITION_FIELDS) and vocabulary["labels"] == list(LABEL_FIELDS)
    assert p.get(f"delivery/mappings/{mapping['mapping_id']}", "viewer").json()["data"]["vocabulary"] == vocabulary
    p.settle()
    page = p.page()
    (region,) = page["deliveries"][0]["files"][0]["regions"]
    assert (region["state"], region["origin"], region["mapping_version"], region["mapping_status"]) == (
        "mapped", "cache", 1, "proposed")
    assert page["totals"]["silent_loss"] == 0 and [v["value"] for v in page["unassigned"]] == [1.2, 2.3, 3.4]
    assert [(m["mapping_id"], m["origin"]) for m in page["mappings"]] == [(mapping["mapping_id"], "person")]
    # the same spec again is that version: nothing new is written
    same = p.post("delivery/mappings:propose", body)
    assert same.status_code == 200 and same.json()["data"]["version"] == 1 and len(p.events("intake.mapping.propose")) == 1
    p.settle()
    # once a person rejected it, the same spec is refused
    assert p.post(f"delivery/mappings/{mapping['mapping_id']}:reject", {"version": 1, "why": "the unit is µg/L"}).status_code == 200
    p.settle()
    refused = p.post("delivery/mappings:propose", body)
    assert refused.status_code == 409 and "rejected" in refused.json()["detail"]["message"]


@pytest.mark.req("T-47", "F-404")
def test_demographics_a_person_enters_on_the_card_are_found_for_the_study(project):
    p = project()
    p.deliver(synthetic.messy_workbook())
    path = p.subject("230-23")

    def demographics(card: dict[str, Any]) -> dict[str, Any]:
        return next(r for r in card["requirements"] if r["req_id"] == "REQ-sys.demographics")

    assert demographics(p.card(path))["status"] == "missing"
    for field, value in (("population", "healthy"), ("age_mean", 34.5)):            # field names: modeler_intake.fields
        answer = p.post(f"{path}:enter", {"field": field, "value": value, "why": "from the protocol synopsis"})
        assert answer.status_code == 200, answer.text
    card = p.card(path)
    found = demographics(card)
    entered = {v["id"] for t in card["tables"] if t["id"] == "facts:entered" for v in t["values"]}
    assert found["status"] == "found" and len(found["values"]) == 2 and set(found["values"]) <= entered
    assert not [c for c in card["checks"] if c["code"] == "REQUIRED_ITEM_UNDISPOSED" and not c["overridden"]
                and "REQ-sys.demographics" in (c["message"] or "")]
    assert not [line for line in p.page()["request"] if line["req_id"] == "REQ-sys.demographics" and "230-23" in line["what"]]


@pytest.mark.req("T-47", "F-404", "T-49")
def test_the_demographics_entered_on_the_card_land_as_the_studys_individual_and_are_not_asked_again(project):
    """OWN-6 (owner-job gap 1): one truth for a study's demographics. The card says what they make (`individual`), and
    the loading lands it: entered with the PK-Sim population database and the sex a person chose (D-29: never a
    default), the age, its range and the weight become the study's individual; the share of women is kept, said so.
    GET /inputs then has the study's demographics "entered", and its to-do does not ask for them again. A population
    that is not one of PK-Sim's names is refused; a layout never reads a column as the individual."""
    p = project()
    workbook = synthetic.messy_workbook()
    p.deliver(workbook)
    assert _accept_note(p, workbook).status_code == 200
    path = p.subject("230-23")
    for field, value in (*FACTS_230_23.items(), ("population", "healthy"), ("age_mean", 32), ("age_min", 21), ("age_max", 45),
                         ("weight_mean_kg", 74), ("percent_female", 50)):
        assert p.post(f"{path}:enter", {"field": field, "value": value, "why": "the clinical study report"}).status_code == 200
    card = p.card(path)
    stated = ["age_mean", "age_min", "age_max", "weight_mean_kg", "percent_female"]
    assert card["individual"] == {"demographics": None, "needs": ["individual_population", "individual_sex"], "why": "",
                                  "stated": stated, "kept": ["percent_female"]}
    held = [h for h in card["held"] if "demographics" in h]
    assert held == [("230-23: demographics not yet the study's individual (age_mean, age_min, age_max, weight_mean_kg, "
                     "percent_female): kept in the ledger; the individual needs individual_population, individual_sex")]
    # PK-Sim's own names only, on a study only
    refused = p.post(f"{path}:enter", {"field": "individual_population", "value": "Caucasian", "why": "the report"})
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "NOT_ALLOWED"
    assert "European_ICRP_2002" in refused.json()["detail"]["message"]
    assert p.post(f"{path}:enter", {"field": "individual_sex", "value": "both", "why": "the report"}).status_code == 422
    assert not [f for f in p.get("delivery/vocabulary").json()["data"]["fields"] if f["name"].startswith("individual_")]
    for field, value in (("individual_population", "European_ICRP_2002"), ("individual_sex", "female")):
        assert p.post(f"{path}:enter", {"field": field, "value": value, "why": "the protocol's population"}).status_code == 200
    card = p.card(path)
    individual = {"population": "European_ICRP_2002", "sex": "FEMALE", "age_years": 32.0, "age_min": 21.0, "age_max": 45.0,
                  "weight_kg": 74.0}
    assert card["individual"]["demographics"] == individual and card["individual"]["needs"] == []
    assert [h for h in card["held"] if "demographics" in h] == [
        ("230-23: demographics the individual does not carry (percent_female): kept in the ledger; the study's individual "
         "is one sex and one PK-Sim population, chosen by a person")]
    assert not [h for h in card["held"] if "no place in the study record" in h and "age_mean" in h]
    _decide(p, path)
    _spot_check(p, path)
    signed = p.post(f"{path}:confirm")
    assert signed.status_code == 200, signed.text
    landed = [dataset(p.ws, i) for i in signed.json()["data"]["confirmation"]["landed"]["datasets"]]
    assert landed and all(d.study["demographics"] == individual and d.demographics_choice == "entered" for d in landed)
    inputs = p.get("inputs").json()["data"]
    assert {s["study_id"]: s["demographics"] for s in inputs["studies"] if s["study_id"].startswith("230-23")} == {
        "230-23": "entered"}
    assert not [t for t in inputs["todo"] if t["kind"] == "demographics" and str(t["target"]).startswith("230-23")]


@pytest.mark.req("T-47", "F-404", "T-05")
def test_a_persons_not_data_decision_is_restored_with_a_reason_and_the_coverage_follows(project):
    p = project()
    workbook = synthetic.messy_workbook()
    p.deliver(workbook, ("loose-profile.csv", LOOSE))
    loose = _sha(LOOSE)

    def file(page: dict[str, Any]) -> dict[str, Any]:
        return next(f for d in page["deliveries"] for f in d["files"] if f["sha256"] == loose)

    # one value of the table set aside on its own first (as a choice that settles a conflict does): it stays so
    first = p.page()["unassigned"]
    Ledger(p.ws).exclude(first[1]["id"], why="the client corrected this point", by="u1")
    assert p.post("delivery/values:assign", {"targets": [first[0]["id"]], "new_study": "LOOSE-1",
                                             "why": "recompute the coverage"}).status_code == 200
    page = p.page()
    (region,) = file(page)["regions"]
    values = [v["id"] for v in page["unassigned"]]
    assert first[1]["id"] not in values and len(values) == 2
    body = {"file_sha256": loose, "regions": [region["region_id"]], "scope": "regions", "why": "data after all: the fed means"}
    nothing = p.post("delivery/regions:restore", body)                          # nothing is marked as not data yet
    assert nothing.status_code == 409 and nothing.json()["detail"]["code"] == "CONFLICT"
    assert "nothing to restore" in nothing.json()["detail"]["message"]
    excluded = p.post("delivery/regions:exclude", {**body, "why": "a duplicate of the Fed sheet"}).json()["data"]
    assert file(excluded)["regions"][0]["state"] == "excluded" and excluded["unassigned"] == []
    # refused, and nothing is written: a reader; no reason; a file never sent; a region it has not; a table under
    # scope figures; an outside item no person accepted
    assert p.post("delivery/regions:restore", body, token="viewer").status_code == 403
    assert p.post("delivery/regions:restore", {**body, "why": ""}).status_code == 422
    assert p.post("delivery/regions:restore", {**body, "file_sha256": _sha(b"never sent")}).status_code == 404
    assert p.post("delivery/regions:restore", {**body, "regions": ["rg-0123456789"]}).status_code == 404
    assert p.post("delivery/regions:restore", {**body, "scope": "figures"}).status_code == 422
    note = {"file_sha256": _sha(workbook.data), "regions": [OUTSIDE_NOTE], "scope": "outside", "why": "it is data"}
    assert p.post("delivery/regions:restore", note).status_code == 409
    assert p.events("intake.region.restore") == [] and len(IntakeStore(p.ws).review.entries("region")) == 1

    # restored: the table is read as before, its values are back, and the coverage follows
    restored = p.post("delivery/regions:restore", body)
    assert restored.status_code == 200, restored.text
    after = restored.json()["data"]
    (back,) = file(after)["regions"]
    assert (back["state"], back["origin"], back["mapping_id"], back["mapping_status"]) == (
        "mapped", region["origin"], region["mapping_id"], "proposed")
    assert file(after)["coverage"]["regions_excluded"] == 0 and file(after)["coverage"] == file(page)["coverage"]
    assert [v["id"] for v in after["unassigned"]] == values and after["totals"] == page["totals"]
    assert after["running"] is False                                            # nothing had to be read again
    # appended, never deleted: the exclusion stays, the restore names it; one audit event with the line's hash
    lines = IntakeStore(p.ws).review.entries("region")
    assert [line.body.get("restores") for line in lines] == [None, [lines[0].body["id"]]]
    (event,) = p.events("intake.region.restore")
    assert event.after == {"id": lines[1].body["id"], "restores": [lines[0].body["id"]], "row_hash": lines[1].hash}
    assert event.reason == body["why"]
    assert p.post("delivery/regions:restore", body).status_code == 409          # restored already: nothing to restore

    # a decision applied before the outcome it replaced was kept: restored, its file is read again
    assert p.post("delivery/regions:exclude", {**body, "why": "a duplicate after all"}).status_code == 200
    store = IntakeStore(p.ws)
    stored = store.coverage(loose)
    store.put_coverage(stored.model_copy(update={"regions": tuple(
        r.model_copy(update={"outcome": r.outcome.model_copy(update={"replaced": None})}) for r in stored.regions)}))
    runs = len(intake_pipeline.runs(p.ws))
    assert p.post("delivery/regions:restore", body).status_code == 200
    p.settle()
    assert len(intake_pipeline.runs(p.ws)) == runs + 1
    (back,) = file(p.page())["regions"]
    assert (back["state"], back["mapping_id"]) == ("mapped", region["mapping_id"])

    # an outside number accepted as not data is given back to the count the same way
    assert _accept_note(p, workbook).json()["data"]["totals"]["outside_numeric"] == 0
    counted = p.post("delivery/regions:restore", note)
    assert counted.status_code == 200, counted.text
    assert counted.json()["data"]["totals"]["outside_numeric"] == 1
    book = next(f for d in counted.json()["data"]["deliveries"] for f in d["files"] if f["name"] == workbook.name)
    assert [o["counted"] for o in book["outside"] if o["where"] == OUTSIDE_NOTE] == [True]


@pytest.mark.req("T-47", "F-404")
def test_a_subject_names_the_client_review_groups_of_the_same_source(project):
    p = project()
    workbook = synthetic.messy_workbook()
    p.deliver(workbook)
    assert all(s["legacy_groups"] == [] for s in p.page()["subjects"])
    legacy = _legacy_dataset(p, workbook, "230-23", "Fasting", "joined")
    rows = {s["label"]: s for s in p.page()["subjects"]}
    # proposed: read with the sheet form, not confirmed yet; accepted: in the model (review OWN-3)
    assert (rows["230-23"]["loaded_elsewhere"], rows["230-23"]["proposed_elsewhere"]) == ([], [legacy.id])
    assert rows["230-23"]["legacy_groups"] == [_group_of(p, legacy.id)["id"]]
    assert all(row["legacy_groups"] == [] for row in rows.values() if not row["proposed_elsewhere"])
    decide_dataset(p.ws, legacy.id, state=EvidenceState.ACCEPTED, reason="confirmed with the sheet form", by="u1")
    rows = {s["label"]: s for s in p.page()["subjects"]}
    assert (rows["230-23"]["loaded_elsewhere"], rows["230-23"]["proposed_elsewhere"]) == ([legacy.id], [])
    assert rows["230-23"]["legacy_groups"] == [_group_of(p, legacy.id)["id"]]
    assert p.card(p.subject("230-23"))["loaded_elsewhere"] == [legacy.id]


@pytest.mark.req("T-47", "F-404", "T-05")
def test_a_region_set_aside_already_is_refused_and_a_restore_undoes_every_decision_in_force(project):
    p = project()
    p.deliver(("loose-profile.csv", LOOSE))
    loose = _sha(LOOSE)
    page = p.page()
    (region,) = page["deliveries"][0]["files"][0]["regions"]
    values = sorted(v.id for v in LedgerView(p.ws).values(file_sha256=loose))
    body = {"file_sha256": loose, "regions": [region["region_id"]], "scope": "regions"}

    def restored_as_before(answer: Any) -> None:
        assert answer.status_code == 200, answer.text
        data = answer.json()["data"]
        (back,) = data["deliveries"][0]["files"][0]["regions"]
        assert back["state"] == "mapped" and data["totals"] == page["totals"]
        assert sorted(v["id"] for v in data["unassigned"]) == sorted(v["id"] for v in page["unassigned"])
        assert sorted(v.id for v in LedgerView(p.ws).values(file_sha256=loose)) == values

    assert p.post("delivery/regions:exclude", {**body, "why": "a duplicate of the Fed sheet"}).status_code == 200
    (decision,) = IntakeStore(p.ws).review.entries("region")
    # a second reviewer marks it again: refused (409), naming the decision in force with who made it, when and why (the
    # page words it: "u1 marked … as not data on …: “…”"), and nothing is written; so is an outside item accepted already
    again = p.post("delivery/regions:exclude", {**body, "why": "not data"})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "CONFLICT"
    assert again.json()["detail"]["decided"] == [{"id": decision.body["id"], "by": "u1", "at": decision.body["at"],
                                                  "why": "a duplicate of the Fed sheet", "where": region["where"]}]
    assert (f"already marked as not data: {region['where']} by u1 at {decision.body['at']} ({decision.body['id']}: a duplicate "
            "of the Fed sheet)") in again.json()["detail"]["message"]
    assert len(IntakeStore(p.ws).review.entries("region")) == 1 and len(p.events("intake.region")) == 1
    restored_as_before(p.post("delivery/regions:restore", {**body, "why": "data after all"}))

    # a log written before a second decision was refused holds two in force: the restore undoes both, and the values
    # the first one set aside are back (the second set nothing aside)
    assert p.post("delivery/regions:exclude", {**body, "why": "a duplicate after all"}).status_code == 200
    store = IntakeStore(p.ws)
    first = store.review.entries("region")[-1]
    second = store.review.append("region", lambda seq: {**first.body, "id": f"rd-{seq}", "why": "not data", "by": "u-other"})
    assert LedgerView(p.ws).values(file_sha256=loose) == []
    restore = p.post("delivery/regions:restore", {**body, "why": "data after all, again"})
    restored_as_before(restore)
    line = IntakeStore(p.ws).review.entries("region")[-1]
    assert line.body["restores"] == [first.body["id"], second.body["id"]]
    assert p.events("intake.region.restore")[-1].after["restores"] == line.body["restores"]


@pytest.mark.req("T-47", "F-404", "T-05", "T-06")
def test_a_restore_leaves_another_persons_exclusion_of_a_value_as_that_person_wrote_it(project):
    p = project()
    p.deliver(("loose-profile.csv", LOOSE))
    loose = _sha(LOOSE)
    page = p.page()
    (region,) = page["deliveries"][0]["files"][0]["regions"]
    one = page["unassigned"][1]["id"]
    extract = one.split("#")[0]
    Ledger(p.ws).exclude(one, why="the client corrected this point", by="u-other")      # as a choice that settles a conflict
    body = {"file_sha256": loose, "regions": [region["region_id"]], "scope": "regions"}
    assert p.post("delivery/regions:exclude", {**body, "why": "a duplicate of the Fed sheet"}).status_code == 200
    written = len(IntakeStore(p.ws).facts.entries("status"))
    assert all("restored_by" not in line.body for line in IntakeStore(p.ws).facts.entries("status"))   # written as before
    restored = p.post("delivery/regions:restore", {**body, "why": "data after all"})
    assert restored.status_code == 200, restored.text
    rd = IntakeStore(p.ws).review.entries("region")[-1].body["id"]
    # the restorer's lines only, each marked with the restore: nothing is written again in another person's name
    new = [line.body for line in IntakeStore(p.ws).facts.entries("status")[written:]]
    assert extract in {b["target"] for b in new} and one not in {b["target"] for b in new}
    assert {(b["status"], b["by"], b["restored_by"], b["reason"]) for b in new} == {("proposed", "u1", rd, f"{rd}: data after all")}
    # the value excluded on its own stays so, by its own line; the others of the table are back
    own = [line.body for line in IntakeStore(p.ws).facts.entries("status") if line.body["target"] == one]
    assert [(b["by"], b["status"]) for b in own] == [("u-other", "excluded")]
    value = LedgerView(p.ws).value(one)
    assert (value.status, value.status_reason) == ("excluded", "the client corrected this point")
    assert sorted(v["id"] for v in restored.json()["data"]["unassigned"]) == sorted(
        v["id"] for v in page["unassigned"] if v["id"] != one)
    # set aside again and restored again: the same, the value still by its own line
    assert p.post("delivery/regions:exclude", {**body, "why": "a duplicate after all"}).status_code == 200
    assert p.post("delivery/regions:restore", {**body, "why": "data after all, again"}).status_code == 200
    assert LedgerView(p.ws).value(one).status_reason == "the client corrected this point"
    assert {v.id for v in LedgerView(p.ws).values(file_sha256=loose)} == {v["id"] for v in page["unassigned"]} - {one}


@pytest.mark.req("T-47", "F-404", "T-05", "T-06")
def test_a_restore_that_undoes_a_decision_a_confirmation_binds_makes_it_not_current(project):
    p = project()
    path = _ready(p)                                    # the delivery's outside note accepted as not data
    study = path.rsplit("/", 1)[1]
    sha = _sha(synthetic.messy_workbook().data)
    signed = p.post(f"{path}:confirm")
    assert signed.status_code == 200 and signed.json()["data"]["confirmation"]["current"] is True
    (confirmation,) = review.confirmations(p.ws)

    def current() -> tuple[bool, bool]:
        row = next(s for s in p.page()["subjects"] if s["subject"] == study)
        return row["confirmation"]["current"], p.card(path)["confirmation"]["current"]

    # a decision made after the signature, and restored: the record never bound it, so it stays current
    other = p.card(p.subject("231-24"))
    table = next(t["region_id"] for t in other["tables"] if t["region_id"])
    aside = {"file_sha256": sha, "regions": [table], "scope": "regions"}
    assert p.post("delivery/regions:exclude", {**aside, "why": "a duplicate"}).status_code == 200
    assert p.post("delivery/regions:restore", {**aside, "why": "not a duplicate"}).status_code == 200
    assert current() == (True, True)
    # a record computed now, then the note it binds restored before it is signed: refused as stale
    record, record_sha = review.bound_record(p.ws, "study", study, reader=LedgerView(p.ws), brief=None, matrix=None,
                                             mol_weight=None)
    note = {"file_sha256": sha, "regions": [OUTSIDE_NOTE], "scope": "outside", "why": "a re-assay count after all"}
    restored = p.post("delivery/regions:restore", note)
    assert restored.status_code == 200, restored.text
    # the values are the ones it binds, but the note it saw set aside counts again: changed since signed
    assert confirmation.record["subject_digest"] == intake_landing.subject_digest(LedgerView(p.ws), "study", study)
    assert current() == (False, False)
    assert "OUTSIDE_NUMBERS" in [b["code"] for b in p.card(path)["blockers"]]
    with pytest.raises(review.ReviewError) as stale:
        review.record_confirmation(p.ws, subject_type="study", subject=study, record=record, record_sha256=record_sha,
                                   signature_id="sig-0001", manifestation="Reviewed", by="u1", printed_name="Dev User",
                                   blinded=False)
    assert stale.value.code == "STALE" and "restored" in str(stale.value)
    assert len(review.confirmations(p.ws)) == 1


@pytest.mark.req("T-47", "F-404", "T-05")
def test_a_relink_replaces_the_assignment_whole_and_the_page_gives_each_analyte_its_id(project):
    p = project()
    p.deliver(("loose-profile.csv", LOOSE))
    loose = _sha(LOOSE)
    page = p.page()
    assert page["analytes"] == []
    extract = page["unassigned"][0]["id"].split("#")[0]

    def analytes() -> set[str | None]:
        return {v.entity.analyte for v in LedgerView(p.ws).values(file_sha256=loose) if v.id.startswith(extract)}

    named = p.post("delivery/values:assign", {"targets": [extract], "new_study": "LOOSE-1", "new_analyte": "M1",
                                              "why": "the title names study LOOSE-1 and M1"})
    assert named.status_code == 200, named.text
    data = named.json()["data"]
    (m1,) = data["analytes"]
    study = next(s["subject"] for s in data["subjects"] if s["label"] == "LOOSE-1")
    assert m1["label"] == "M1" and analytes() == {m1["id"]}
    # linked again with no analyte: the assignment replaces the earlier one whole, so the stated analyte goes with it
    relinked = p.post("delivery/values:assign", {"targets": [extract], "study": study, "why": "the same study, arm unknown"})
    assert relinked.status_code == 200 and analytes() == {None}
    # a re-link that keeps it names it again, by the id the page gives
    kept = p.post("delivery/values:assign", {"targets": [extract], "study": study, "analyte": m1["id"],
                                             "why": "the same study, M1"})
    assert kept.status_code == 200 and analytes() == {m1["id"]} and kept.json()["data"]["analytes"] == [m1]


def _reread_without_sd(p: Project, loose: str) -> None:
    """The loose profile's layout corrected (its SD column not read) and approved: the file is read again under it, and
    its table becomes a new extract (new value ids) that supersedes the earlier one."""
    (row,) = [m for m in p.page()["mappings"] if m["used_in"][0]["file_sha256"] == loose]
    path = f"delivery/mappings/{row['mapping_id']}"
    spec = p.get(path).json()["data"]["spec"]
    region = row["used_in"][0]["region_id"]
    columns = [{"column": c["column"], "role": "ignore", "reason": "the client withdrew this column"} if c["role"] == "spread"
               else c for c in spec["columns"]]
    edited = p.post(f"{path}:edit", {"spec": {**spec, "columns": columns}, "why": "the client withdrew the SD column",
                                     "file_sha256": loose, "region_id": region})
    assert edited.status_code == 200, edited.text
    p.settle()
    approved = p.post(f"{path}:approve", {"version": edited.json()["data"]["version"], "note": "checked"})
    assert approved.status_code == 200, approved.text
    p.settle()


@pytest.mark.req("T-47", "F-404", "T-05")
def test_a_persons_link_survives_a_corrected_layout_with_one_audited_line_naming_it(project):
    p = project()
    p.deliver(synthetic.messy_workbook(), ("loose-profile.csv", LOOSE))
    loose = _sha(LOOSE)
    page = p.page()
    study = p.subject("231-24").rsplit("/", 1)[1]
    before = next(s for s in page["subjects"] if s["subject"] == study)["values"]
    old = page["unassigned"][0]["id"].split("#")[0]
    # linked as the page links them: every value of the file by its id, with an arm
    linked = p.post("delivery/values:assign", {"targets": [v["id"] for v in page["unassigned"]], "study": study,
                                               "new_arm": "Fed", "why": "the fed arm, per the client's e-mail"})
    assert linked.status_code == 200, linked.text
    (person,) = IntakeStore(p.ws).review.entries("assignment")
    _reread_without_sd(p, loose)
    page = p.page()
    # the table is a new extract, and the link went with it: nothing waits, the study holds its values
    new = next(v.id for v in LedgerView(p.ws).values(file_sha256=loose)).split("#")[0]
    assert new != old and page["unassigned"] == [] and page["relink"] == []
    assert page["totals"]["values_unassigned"] == 0
    assert next(s for s in page["subjects"] if s["subject"] == study)["values"] == before + 4
    first, carried = IntakeStore(p.ws).review.entries("assignment")
    assert first.hash == person.hash
    assert carried.body["targets"] == [new] and carried.body["by"] == "code"
    assert (carried.body["study"], carried.body["arm"]) == (person.body["study"], person.body["arm"])
    assert carried.body["why"] == f"carried over from {person.body['id']} after a re-read: the fed arm, per the client's e-mail"
    event = p.events("intake.assign")[-1]
    assert (event.actor, event.after["carried_from"], event.after["row_hash"]) == ("code", person.body["id"], carried.hash)
    # read again with the same layout: kept as it is, nothing carried twice
    assert p.post("delivery:run", {"files": [loose]}).status_code == 202
    p.settle()
    assert len(IntakeStore(p.ws).review.entries("assignment")) == 2 and p.page()["unassigned"] == []


@pytest.mark.req("T-47", "F-404", "T-05")
def test_a_link_that_covered_part_of_a_table_is_not_carried_and_the_page_says_where_it_went(project):
    p = project()
    p.deliver(("loose-profile.csv", LOOSE))
    loose = _sha(LOOSE)
    page = p.page()
    part = [v["id"] for v in page["unassigned"][:2]]
    linked = p.post("delivery/values:assign", {"targets": part, "new_study": "LOOSE-1", "why": "the first two times"})
    assert linked.status_code == 200, linked.text
    assert linked.json()["data"]["relink"] == []                 # nothing was read again yet
    study = next(s["subject"] for s in linked.json()["data"]["subjects"] if s["label"] == "LOOSE-1")
    _reread_without_sd(p, loose)
    page = p.page()
    # which part of the new reading the link would cover cannot be told: every value waits, with where it went before
    new = {v["id"].split("#")[0] for v in page["unassigned"]}
    assert len(page["unassigned"]) == 4 and len(new) == 1 and not new & {i.split("#")[0] for i in part}
    (relink,) = page["relink"]
    (person,) = IntakeStore(p.ws).review.entries("assignment")
    assert relink == {"targets": sorted(new), "assignment": person.body["id"], "study": study, "arm": None, "product": None,
                      "batch": None, "analyte": None, "labels": {"study": "LOOSE-1"}, "whole": False, "by": "u1",
                      "at": person.body["at"], "why": "the first two times"}
    # the study has no value left, so the page names it here: the row can still be linked to it
    assert study not in {s["subject"] for s in page["subjects"]}
    assert [e.actor for e in p.events("intake.assign")] == ["u1"]
    # linked again by the person: nothing waits any more
    again = p.post("delivery/values:assign", {"targets": sorted(new), "study": study, "why": "the whole table, LOOSE-1"})
    assert again.status_code == 200 and again.json()["data"]["relink"] == [] and again.json()["data"]["unassigned"] == []


def _arm_workbook(arm: str, *, period: bool, title: str | None = None) -> bytes:
    """A BE arm's workbook as a CRO sends it (the times across the top), under a title the rules do not read as a study
    id: subjects 001 to 004, with their period ("I", "II") when `period`. `title`: another title."""
    book = Workbook()
    sheet = book.active
    sheet.title = "Sheet1"
    times = ["1.00", "2.00", "4.00", "8.00"]
    sheet.append([title or f"Study ABC-1: plasma concentrations of {synthetic.DRUG} (ng/mL), {arm}, 50 mg, fasting"])
    sheet.append([])
    sheet.append(["Time (hr)"])
    sheet.append(["Subject No.", *(["Period"] if period else []), *times])
    for i in range(1, 5):
        sheet.append([f"{i:03d}", *(["I" if i % 2 else "II"] if period else []), *(round(10.0 * i / float(t), 2) for t in times)])
    raw = io.BytesIO()
    book.save(raw)
    return raw.getvalue()


@pytest.mark.req("T-47", "F-404", "T-05")
def test_two_files_with_the_same_subjects_are_refused_one_arm_of_a_study_whatever_the_page_sent(project):
    p = project()
    ref, test = _arm_workbook("Reference", period=False), _arm_workbook("Test", period=True)
    p.deliver(("abc-reference.xlsx", ref), ("abc-test.xlsx", test))
    page = p.page()
    of = {sha: _all_targets([v for v in page["unassigned"] if v["file_sha256"] == sha]) for sha in (_sha(ref), _sha(test))}
    assert all(of.values())
    n_test = len([v for v in page["unassigned"] if v["file_sha256"] == _sha(test)])
    analytes = {v["file_sha256"]: v["entity"].get("analyte") for v in page["unassigned"]}
    why = "the title names study ABC-1"
    # in one call: both files hold subject 001 (a period left out matches period I), whatever analyte each states
    both = p.post("delivery/values:assign", {"targets": [*of[_sha(ref)], *of[_sha(test)]], "new_study": "ABC-1", "why": why})
    assert both.status_code == 409, both.text
    detail = both.json()["detail"]
    assert detail["code"] == "CONFLICT" and "abc-reference.xlsx and abc-test.xlsx both hold subject 001" in detail["message"]
    assert "the new study (no arm) each file needs its own arm" in detail["message"]
    assert p.events("intake.assign") == [] and p.events("intake.entity") == []          # nothing is written
    made = p.post("delivery/values:assign", {"targets": of[_sha(ref)], "new_study": "ABC-1", "why": why})
    assert made.status_code == 200, made.text
    study = next(s for s in made.json()["data"]["subjects"] if s["label"] == "ABC-1")["subject"]
    # one at a time: what the study holds in that arm counts, with the analyte stated as the other file's or not at all
    for stated in ({}, {"analyte": analytes[_sha(ref)]} if analytes[_sha(ref)] else {}):
        refused = p.post("delivery/values:assign", {"targets": of[_sha(test)], "study": study, "why": why, **stated})
        assert refused.status_code == 409, refused.text
        assert refused.json()["detail"]["message"] == (
            "abc-test.xlsx holds subject 001, period I, which study ABC-1 (no arm) holds already from abc-reference.xlsx: "
            "each file needs its own arm")
    assert len(p.events("intake.assign")) == 1
    # each file its own arm: linked; the same file linked again to its own study is never refused by its own values
    armed = p.post("delivery/values:assign", {"targets": of[_sha(test)], "study": study, "new_arm": "Test", "why": why})
    assert armed.status_code == 200, armed.text
    again = p.post("delivery/values:assign", {"targets": of[_sha(ref)], "study": study, "why": "linked again"})
    assert again.status_code == 200, again.text
    # but not into the arm the other file holds
    test_arm = next(a["id"] for s in armed.json()["data"]["subjects"] if s["subject"] == study for a in s["arms"])
    mixed = p.post("delivery/values:assign", {"targets": of[_sha(ref)], "study": study, "arm": test_arm, "why": why})
    assert mixed.status_code == 409 and "arm Test" in mixed.json()["detail"]["message"]
    # each file says the link in force on its values: what it covers there, where it went, who, when, why (review INT-5)
    files = {f["sha256"]: f for d in p.page()["deliveries"] for f in d["files"]}
    (link,) = files[_sha(test)]["links"]
    assert (link["targets"], link["values"], link["study"], link["arm"], link["labels"], link["by"], link["why"]) == (
        of[_sha(test)], n_test, study, test_arm, {"study": "ABC-1", "arm": "Test"}, "u1", why)
    (again_link,) = files[_sha(ref)]["links"]
    assert again_link["why"] == "linked again" and again_link["arm"] is None
    # linked elsewhere by its targets: the link is replaced whole
    elsewhere = p.post("delivery/values:assign", {"targets": link["targets"], "new_study": "ABC-2", "why": "the wrong study"})
    assert elsewhere.status_code == 200, elsewhere.text
    moved = next(f for d in elsewhere.json()["data"]["deliveries"] for f in d["files"] if f["sha256"] == _sha(test))["links"]
    assert [(m["labels"], m["values"]) for m in moved] == [({"study": "ABC-2"}, n_test)]


@pytest.mark.req("T-47", "F-404", "T-05")
def test_the_arm_guard_refuses_only_what_would_be_one_series_and_never_what_stays_where_it_is(project):
    """Final review INT-4 (the round-1 guard's regression): the guard compares what the ledger compares (subject, period,
    analyte by name, matrix, field), and does not check values a request keeps in their study and arm."""
    p = project()
    # a plasma file and a urine file of one study, the same subjects and periods: two series, so one arm is fine
    plasma = _arm_workbook("Reference", period=True)
    urine = _arm_workbook("Reference", period=True, title=f"Study ABC-1: urine concentrations of {synthetic.DRUG} (ng/mL), "
                                                         "Reference, 50 mg, fasting")
    ref, test = _arm_workbook("Reference", period=False), _arm_workbook("Test", period=True)
    p.deliver(("abc-plasma.xlsx", plasma), ("abc-urine.xlsx", urine), ("abc-reference.xlsx", ref), ("abc-test.xlsx", test))
    page = p.page()
    of = {sha: _all_targets([v for v in page["unassigned"] if v["file_sha256"] == sha])
          for sha in (_sha(plasma), _sha(urine), _sha(ref), _sha(test))}
    matrices = {sha: {v["labels"].get("matrix") for v in page["unassigned"] if v["file_sha256"] == sha and v["labels"].get("subject")}
                for sha in (_sha(plasma), _sha(urine))}
    assert matrices == {_sha(plasma): {"plasma"}, _sha(urine): {"urine"}}, matrices
    made = p.post("delivery/values:assign", {"targets": of[_sha(plasma)], "new_study": "ABC-1", "why": "the plasma of ABC-1"})
    assert made.status_code == 200, made.text
    study = next(s for s in made.json()["data"]["subjects"] if s["label"] == "ABC-1")["subject"]
    urine_linked = p.post("delivery/values:assign", {"targets": of[_sha(urine)], "study": study, "why": "the urine of ABC-1"})
    assert urine_linked.status_code == 200, urine_linked.text
    # the original bypass is still refused: the Reference and the Test file into one arm, each with its own analyte id of
    # one name, in one call or one after the other
    analytes = {v["file_sha256"]: v["entity"].get("analyte") for v in page["unassigned"] if v["entity"].get("analyte")}
    both = p.post("delivery/values:assign", {"targets": [*of[_sha(ref)], *of[_sha(test)]], "new_study": "ABC-2",
                                              "why": "both arms"})
    assert both.status_code == 409 and "abc-reference.xlsx and abc-test.xlsx both hold subject 001" in both.json()["detail"]["message"]
    first = p.post("delivery/values:assign", {"targets": of[_sha(ref)], "new_study": "ABC-2", "why": "the Reference arm",
                                               **({"analyte": analytes[_sha(ref)]} if _sha(ref) in analytes else {})})
    assert first.status_code == 200, first.text
    abc2 = next(s for s in first.json()["data"]["subjects"] if s["label"] == "ABC-2")["subject"]
    second = p.post("delivery/values:assign", {"targets": of[_sha(test)], "study": abc2, "why": "the Test arm",
                                                **({"analyte": analytes[_sha(test)]} if _sha(test) in analytes else {})})
    assert second.status_code == 409 and "which study ABC-2 (no arm) holds already from abc-reference.xlsx" in second.text


@pytest.mark.req("T-47", "F-404", "T-05")
def test_stating_the_analyte_of_values_whose_files_name_their_study_is_never_refused_by_the_arm_guard(project):
    """Final review INT-4: the card's "State it…" for ANALYTE_MISSING keeps the values' study and arm, so nothing new sits
    beside them, and stating their analyte only narrows a match: the guard does not check them again."""
    p = project()
    named = _arm_workbook("x", period=True, title=f"Study 230-31, 50 mg, fasting: plasma concentrations of {synthetic.DRUG} (ng/mL)")
    bare = _arm_workbook("x", period=True, title="Study 230-31, 50 mg, fasting: concentrations (ng/mL)")
    p.deliver(("named-plasma.xlsx", named), ("named-bare.xlsx", bare))
    path = p.subject("230-31")
    card = p.card(path)
    values = {v["id"]: v for t in card["tables"] for v in t["values"]}
    missing = [c for c in card["checks"] if c["code"] == "ANALYTE_MISSING"]
    assert missing and card["conflicts"] == [], (missing, card["conflicts"])
    targets = missing[0]["values"]
    first_value = values[targets[0]]
    assert {values[t]["file_sha256"] for t in targets} == {_sha(bare)}
    analyte = next(a["id"] for a in p.page()["analytes"] if a["label"].lower() == synthetic.DRUG.lower())
    stated = p.post("delivery/values:assign", {"targets": targets, "why": "the report says what it measures", "analyte": analyte,
                                                **{r: first_value["entity"][r] for r in ("study", "arm") if first_value["entity"].get(r)}})
    assert stated.status_code == 200, stated.text
    assert not [c for c in p.card(path)["checks"] if c["code"] == "ANALYTE_MISSING"]


@pytest.mark.req("T-47", "F-404", "T-05")
def test_a_file_under_two_links_to_one_place_is_moved_whole_by_the_union_of_their_targets(project):
    """Final review INT-5: a file's facts (dose, fed state) and its table, linked by two links to one study and arm, are
    listed as two links on the file; "Link elsewhere…" sends the union of their targets, so nothing stays behind."""
    p = project()
    ref = _arm_workbook("Reference", period=False)
    p.deliver(("abc-reference.xlsx", ref))
    values = [v for v in p.page()["unassigned"] if v["file_sha256"] == _sha(ref)]
    facts, table = _all_targets([v for v in values if "#" not in v["id"]]), _all_targets([v for v in values if "#" in v["id"]])
    assert facts and table, values
    made = p.post("delivery/values:assign", {"targets": table, "new_study": "ABC-1", "new_arm": "Reference", "why": "the table"})
    assert made.status_code == 200, made.text
    study = next(s for s in made.json()["data"]["subjects"] if s["label"] == "ABC-1")
    reference = study["arms"][0]["id"]
    assert p.post("delivery/values:assign", {"targets": facts, "study": study["subject"], "arm": reference,
                                             "why": "the facts of the same arm"}).status_code == 200
    links = next(f for d in p.page()["deliveries"] for f in d["files"] if f["sha256"] == _sha(ref))["links"]
    assert [sorted(link["targets"]) for link in links] == [sorted(table), sorted(facts)]
    assert {(link["study"], link["arm"]) for link in links} == {(study["subject"], reference)}
    # moved together: one call with both links' targets; one link left, every value in the new arm, none in the old one
    union = list(dict.fromkeys(t for link in links for t in link["targets"]))
    moved = p.post("delivery/values:assign", {"targets": union, "study": study["subject"], "new_arm": "Test", "why": "the Test arm"})
    assert moved.status_code == 200, moved.text
    (link,) = next(f for d in moved.json()["data"]["deliveries"] for f in d["files"] if f["sha256"] == _sha(ref))["links"]
    assert link["labels"] == {"study": "ABC-1", "arm": "Test"} and link["values"] == len(values)
    arms = {v.entity.arm for v in LedgerView(p.ws).values(file_sha256=_sha(ref))}
    assert arms == {link["arm"]}


@pytest.mark.req("T-47", "F-404")
def test_the_sheet_forms_group_of_a_file_a_person_linked_to_a_study_is_named_on_that_study(project):
    p = project()
    ref, test = _arm_workbook("Reference", period=False), _arm_workbook("Test", period=True)
    p.deliver(("abc-reference.xlsx", ref), ("abc-test.xlsx", test))
    groups = {g["id"]: g for g in p.get("client-review").json()["data"]["groups"]}
    assert {"study:abc-REF", "study:abc-TEST"} <= set(groups)             # the sheet form read each under its own name
    page = p.page()
    of = {sha: [v["id"] for v in page["unassigned"] if v["file_sha256"] == sha] for sha in (_sha(ref), _sha(test))}
    # part of a file linked: some of its values are still of no study, so its group stays its own
    made = p.post("delivery/values:assign", {"targets": of[_sha(ref)][:2], "new_study": "ABC-1", "why": "the title"})
    assert made.status_code == 200, made.text
    study = next(s for s in made.json()["data"]["subjects"] if s["label"] == "ABC-1")
    assert study["legacy_groups"] == []
    # every value of each file linked to the study: their groups are the same source, named on its row
    whole = p.post("delivery/values:assign", {"targets": of[_sha(ref)], "study": study["subject"], "new_arm": "Reference",
                                              "why": "the title names study ABC-1, Reference"})
    assert whole.status_code == 200, whole.text
    armed = p.post("delivery/values:assign", {"targets": of[_sha(test)], "study": study["subject"], "new_arm": "Test",
                                              "why": "the title names study ABC-1, Test"})
    assert armed.status_code == 200, armed.text
    rows = {s["label"]: s for s in armed.json()["data"]["subjects"]}
    assert rows["ABC-1"]["legacy_groups"] == ["study:abc-REF", "study:abc-TEST"]
    assert (rows["ABC-1"]["loaded_elsewhere"], rows["ABC-1"]["proposed_elsewhere"]) == ([], [])


# --- the fill round's API follow-ups (plan 2026-11-14 §5): who decided, a table's first rows, the layout words -----------


@pytest.mark.req("T-47", "F-404", "T-05", "T-06")
def test_a_persons_not_data_decision_is_on_its_region_and_note_with_who_when_and_why_and_its_restore_stays(project):
    p = project()
    workbook = synthetic.messy_workbook()
    p.deliver(workbook, ("loose-profile.csv", LOOSE))
    loose, book, lloq = _sha(LOOSE), _sha(workbook.data), "s:'Fasting'!A16"   # the LLOQ line its table reads

    def file(page: dict[str, Any], sha: str) -> dict[str, Any]:
        return next(f for d in page["deliveries"] for f in d["files"] if f["sha256"] == sha)

    def note(page: dict[str, Any], where: str) -> dict[str, Any]:
        return next(o for o in file(page, book)["outside"] if o["where"] == where)

    def line(rd: str, *keys: str) -> dict[str, Any]:
        """A decision as its own line of the review log has it."""
        body = next(e.body for e in IntakeStore(p.ws).review.entries("region") if e.body["id"] == rd)
        return {k: body[k] for k in ("id", "by", "at", "why", *keys)}

    page = p.page()
    (region,) = file(page, loose)["regions"]
    assert (region["state"], region["decision"], region["restored"]) == ("mapped", None, None)
    # a note its table reads and the stray note: no decision on either, so the one not counted is its table's
    assert (note(page, lloq)["counted"], note(page, lloq)["decision"], note(page, lloq)["restored"]) == (False, None, None)
    assert (note(page, OUTSIDE_NOTE)["counted"], note(page, OUTSIDE_NOTE)["decision"]) == (True, None)

    # marked as not data: the region and both notes say who, when and why, from the decision's own line
    body = {"file_sha256": loose, "regions": [region["region_id"]], "scope": "regions"}
    assert p.post("delivery/regions:exclude", {**body, "why": "a duplicate of the Fed sheet"}).status_code == 200
    assert _accept_note(p, workbook).status_code == 200
    beside = {"file_sha256": book, "regions": [lloq], "scope": "outside"}
    marked = p.post("delivery/regions:exclude", {**beside, "why": "the assay's limit, said again"})
    assert marked.status_code == 200, marked.text
    page = marked.json()["data"]
    (excluded,) = file(page, loose)["regions"]
    first = excluded["reason"].split(":")[0]
    assert excluded["state"] == "excluded" and excluded["decision"] == line(first)
    assert (excluded["decision"]["by"], excluded["decision"]["why"], excluded["restored"]) == (
        "u1", "a duplicate of the Fed sheet", None)
    stray, cited = note(page, OUTSIDE_NOTE), note(page, lloq)
    assert stray["counted"] is False and stray["decision"]["why"] == "a working note, not data"
    assert cited["counted"] is False and cited["decision"] == line(cited["decision"]["id"])
    assert cited["decision"]["why"] == "the assay's limit, said again"
    assert note(page, "s:'Fed'!A16")["decision"] is None                       # the same words beside another table

    # restored: no decision is in force, and the restore stays on the record, naming the decision it undid
    restored = p.post("delivery/regions:restore", {**body, "why": "the fed means after all"}).json()["data"]
    (back,) = file(restored, loose)["regions"]
    again = back["restored"]["id"]
    assert (back["state"], back["decision"]) == ("mapped", None)
    assert back["restored"] == {**line(again), "restores": [first]} and back["restored"]["why"] == "the fed means after all"
    page = p.post("delivery/regions:restore", {**beside, "why": "a limit, said beside its table"}).json()["data"]
    cited = note(page, lloq)
    undone = cited["restored"]["restores"]
    assert (cited["counted"], cited["decision"]) == (False, None) and len(undone) == 1    # its table still reads it
    assert line(undone[0])["why"] == "the assay's limit, said again" and note(page, OUTSIDE_NOTE)["restored"] is None
    # set aside again: the new decision is in force, and the restore before it is still its record
    aside = p.post("delivery/regions:exclude", {**body, "why": "a duplicate after all"}).json()["data"]
    (excluded,) = file(aside, loose)["regions"]
    assert excluded["decision"]["why"] == "a duplicate after all" and excluded["decision"]["id"] not in (first, again)
    assert excluded["restored"]["id"] == again


# a table no rule reads, wider than what is shown of it, with a header cell longer than what is shown of a cell
WIDE = (",".join(["Item"] + [f"Q{d} result" for d in range(1, 35)] + ["x" * 100]) + "\n"
        + "\n".join(",".join([f"row {s}"] + [f"{s}.{d}" for d in range(1, 36)]) for s in range(1, 8)) + "\n").encode()


@pytest.mark.req("T-47", "F-404", "F-402")
def test_a_table_no_layout_reads_shows_its_first_rows_and_a_blinded_file_only_its_header_masked(project):
    p = project()
    p.deliver(("odd-profile.csv", ODD), ("wide-troughs.csv", WIDE))

    def regions(name: str) -> list[dict[str, Any]]:
        return next(f for d in p.page()["deliveries"] for f in d["files"] if f["name"] == name)["regions"]

    (region,) = regions("odd-profile.csv")
    first = {"n_rows": 4, "n_cols": 2, "header_rows": 1, "blinded": False,
             "rows": [["Hrs (h)", "Result (ng/mL)"], ["0.5", "1.2"], ["1", "2.3"], ["2", "3.4"]], "spans": [[1, 1]] * 4}
    assert region["state"] == "unread" and region["head"] == first
    # at most 5 rows and 30 columns of a wide table, each cell cut at 80 characters
    (wide,) = regions("wide-troughs.csv")
    head = wide["head"]
    assert wide["state"] == "unread" and (head["n_rows"], head["n_cols"], head["header_rows"]) == (8, 36, 1)
    assert len(head["rows"]) == 5 and {len(row) for row in head["rows"]} == {30} and head["spans"] == [[1] * 30] * 5
    assert head["rows"][0][:2] == ["Item", "Q1 result"] and head["rows"][4][:2] == ["row 4", "4.1"]
    # read with a person's layout: no rows (it has a layout to review); its layout rejected, its rows again
    proposed = p.post("delivery/mappings:propose", {"file_sha256": _sha(ODD), "region_id": region["region_id"],
                                                    "spec": ODD_SPEC, "why": "hours, and the mean level"})
    assert proposed.status_code == 200, proposed.text
    p.settle()
    (read,) = regions("odd-profile.csv")
    assert (read["state"], read["head"]) == ("mapped", None)
    mapping = proposed.json()["data"]["mapping_id"]
    assert p.post(f"delivery/mappings/{mapping}:reject", {"version": 1, "why": "the unit is µg/L"}).status_code == 200
    p.settle()
    (back,) = regions("odd-profile.csv")
    assert back["head"] == first

    # a file that holds a blinded study's values: the header band only, every digit masked, and no value
    b = project(blinding=True, project_id="p2")
    workbook = synthetic.messy_workbook()
    b.deliver(workbook)
    secrets = _secrets(b.ws, "230-23")
    path = b.subject("230-23")
    table = next(t for t in b.card(path)["tables"] if t["mapping_id"])
    entered = b.post(f"{path}:enter", {"field": "intended_use", "value": "external_validation", "why": "the plan says so"})
    assert entered.status_code == 200 and entered.json()["data"]["blinded"] is True
    for version in (table["mapping_version"], table["mapping_version"] + 1):     # the layout, then the rules' own reading
        rejected = b.post(f"delivery/mappings/{table['mapping_id']}:reject", {"version": version, "why": "not this layout"})
        assert rejected.status_code == 200, rejected.text
        b.settle()
    answer = b.get("delivery")
    book = next(f for d in answer.json()["data"]["deliveries"] for f in d["files"] if f["name"] == workbook.name)
    shown = [r for r in book["regions"] if r["head"] is not None]
    assert book["blinded"] is True and {r["where"] for r in shown} == {"s:'Fasting'!A2:G14", "s:'Fed'!A2:G14"}
    doc = parse_document(workbook.data, workbook.name)
    for r in shown:
        grid = region_grid(doc, r["region_id"])
        rows = r["head"]["rows"]
        assert r["head"]["blinded"] is True and 0 < len(rows) <= r["head"]["header_rows"]
        assert rows == [[re.sub(r"\d", "•", grid.cell(row, c).text.strip()) for c in range(1, min(grid.n_cols, 30) + 1)]
                        for row in range(1, len(rows) + 1)]
        assert not any(ch.isdigit() for row in rows for ch in "".join(row))
        # the title merged over the six time columns is drawn once: its first column spans them, the others are covered
        # (their text is the merged cell's, as a mapping reads a merged header)
        assert r["head"]["spans"][0] == [1, 6, 0, 0, 0, 0, 0] and len(set(rows[0][1:])) == 1
        assert grid.cell(1, 3).merged_from == grid.cell(1, 2).locator
    assert _leaks(secrets, answer.text) == []
    # what a person wrote about a blinded file has its digits masked too, its decision's id kept
    other = next(r for r in book["regions"] if r["state"] == "mapped")
    aside = b.post("delivery/regions:exclude", {"file_sha256": _sha(workbook.data), "regions": [other["region_id"]],
                                                "scope": "regions", "why": "rows 4 to 12 repeat 25.2"})
    assert aside.status_code == 200, aside.text
    noted = b.post("delivery/regions:exclude", {"file_sha256": _sha(workbook.data), "regions": [OUTSIDE_NOTE],
                                                "scope": "outside", "why": "3 samples, re-assayed"}).json()["data"]
    book = next(f for d in noted["deliveries"] for f in d["files"] if f["name"] == workbook.name)
    marked = next(r for r in book["regions"] if r["region_id"] == other["region_id"])
    assert marked["decision"]["why"] == "rows • to •• repeat ••.•"
    assert marked["reason"] == f"{marked['decision']['id']}: rows • to •• repeat ••.•"
    assert next(o for o in book["outside"] if o["where"] == OUTSIDE_NOTE)["decision"]["why"] == "• samples, re-assayed"


@pytest.mark.req("T-47", "F-404")
def test_the_layout_words_are_given_to_a_project_where_no_table_has_a_layout_yet(project):
    p = project()
    p.deliver(("odd-profile.csv", ODD))
    page = p.page()
    assert page["mappings"] == [] and not [r for d in page["deliveries"] for f in d["files"] for r in f["regions"]
                                          if r["mapping_id"]]
    answer = p.get("delivery/vocabulary", "viewer")
    assert answer.status_code == 200, answer.text
    vocabulary = answer.json()["data"]
    # the intake package's own words, the same every mapping answer gives
    assert vocabulary["roles"] == list(get_args(Role)) and vocabulary["statistics"] == list(get_args(Statistic))
    assert {f["name"] for f in vocabulary["fields"]} == {n for n, f in FIELDS.items() if not f.person_only} and vocabulary["labels"] == list(LABEL_FIELDS)
    (region,) = page["deliveries"][0]["files"][0]["regions"]
    proposed = p.post("delivery/mappings:propose", {"file_sha256": _sha(ODD), "region_id": region["region_id"],
                                                    "spec": ODD_SPEC, "why": "hours, and the mean level"})
    assert proposed.status_code == 200 and proposed.json()["data"]["vocabulary"] == vocabulary


# --- the final review: the decisions a signature binds, blinding on every view Inputs reads (INT-1..3, 6, 8, 11) -----------




def _decided(card: dict[str, Any], kind: str, scope: str = "subject") -> list[dict[str, Any]]:
    return [d for d in card["decisions"] if d["kind"] == kind and d["scope"] == scope]


@pytest.mark.req("T-47", "F-404", "T-05", "T-06")
def test_a_card_lists_every_decision_its_signature_binds_with_who_when_and_why(project):
    p = project()
    workbook = synthetic.messy_workbook()
    p.deliver(workbook, ("loose-profile.csv", LOOSE))
    path = p.subject("230-23")
    # the clean-up's blockers say whose files they count: the delivery's, not only the subject's own (INT-8)
    gate = {b["code"]: b["detail"] for b in p.card(path)["blockers"]}
    assert "in the delivery's files" in gate["OUTSIDE_NUMBERS"] and "in the delivery's files" in gate["UNASSIGNED_VALUES"]
    assert _accept_note(p, workbook).status_code == 200
    card = _decide(p, path, FACTS_230_23)
    # the values of a file of the same delivery linked to another study, and a table of that file set aside and given
    # back: the delivery's clean-up, which the signature binds too
    loose = [v["id"] for v in p.page()["unassigned"] if v["file"] == "loose-profile.csv"]
    linked = p.post("delivery/values:assign", {"targets": loose, "new_study": "XYZ-9", "why": "the fed means of XYZ-9"})
    assert linked.status_code == 200, linked.text
    (region,) = next(f for d in linked.json()["data"]["deliveries"] for f in d["files"] if f["name"] == "loose-profile.csv")["regions"]
    body = {"file_sha256": _sha(LOOSE), "regions": [region["region_id"]], "scope": "regions"}
    assert p.post("delivery/regions:exclude", {**body, "why": "a duplicate of the Fed sheet"}).status_code == 200
    assert p.post("delivery/regions:restore", {**body, "why": "the fed means after all"}).status_code == 200
    card = p.card(path)
    decisions = card["decisions"]
    assert [d["at"] for d in decisions] == sorted((d["at"] for d in decisions), reverse=True)        # newest first
    # each with who made it, when and why, read from its own line (no audit trail is read)
    assert all(d["by"] == "u1" and d["at"] and d["why"] for d in decisions)
    entered = {d["field"]: d for d in _decided(card, "entry")}
    assert {f: entered[f]["value"] for f in FACTS_230_23} == FACTS_230_23
    assert all(d["why"] == "from the protocol" and d["value_id"].startswith("f-") for d in entered.values())
    (accepted,) = _decided(card, "override")
    assert accepted["check_id"] in {c["id"] for c in card["checks"] if c["overridden"]}
    (asked,) = _decided(card, "disposition")
    assert (asked["req_id"], asked["disposition"], asked["why"]) == ("REQ-sys.demographics", "ask_client", "asked")
    (note,) = _decided(card, "not_data")                                  # the stray note of its own file
    assert (note["places"], note["files"], note["region_scope"]) == ([OUTSIDE_NOTE], [workbook.name], "outside")
    # the layouts of its own tables only, each naming every file it reads; the other tables' layouts are the delivery's
    own = {t["mapping_id"] for t in card["tables"] if t["mapping_id"]}
    assert {d["mapping_id"] for d in _decided(card, "layout")} == own
    assert all(d["status"] == "approved" and d["why"] == "the truth" and d["files"] == [workbook.name]
               for d in _decided(card, "layout"))
    assert _decided(card, "layout", "delivery")                         # e.g. the dissolution table's layout
    # the delivery's clean-up in its other file: the link to another study, the "not data" decision and its restore
    (link,) = _decided(card, "assign", "delivery")
    assert (link["files"], link["values"], link["linked_to"]) == (["loose-profile.csv"], len(loose), {"study": "XYZ-9"})
    (aside,) = _decided(card, "not_data", "delivery")
    (back,) = _decided(card, "restore", "delivery")
    assert aside["places"] == back["places"] == [region["where"]] and back["restores"] == [aside["id"]]
    # another study's card does not list 230-23's own decisions
    other = p.card(p.subject("231-24"))
    assert not {d["id"] for d in other["decisions"] if d["kind"] in ("entry", "override", "disposition")} & {d["id"] for d in decisions}

    # every override is listed, and a second one of a check accepted as is already is refused, naming who and when
    failed = next(c for c in card["checks"] if c["overridden"])
    again = p.post(f"{path}:override", {"check_id": failed["id"], "why": "a second reviewer's reading"})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "CONFLICT", again.text
    (said,) = again.json()["detail"]["decided"]
    assert (said["id"], said["by"], said["at"], said["why"]) == (accepted["id"], "u1", accepted["at"], accepted["why"])
    assert len(IntakeStore(p.ws).review.entries("override")) == 1 and len(p.events("intake.override")) == 1


@pytest.mark.req("T-47", "F-404", "T-05", "T-06")
def test_values_linked_to_a_study_are_its_decisions_and_say_how_many_are_still_its(project):
    p = project()
    p.deliver(("loose-profile.csv", LOOSE))
    loose = [v["id"] for v in p.page()["unassigned"]]
    assert p.post("delivery/values:assign", {"targets": loose, "new_study": "ABC-1", "new_arm": "Test",
                                              "why": "the protocol's Test arm"}).status_code == 200
    path = p.subject("ABC-1")
    (link,) = _decided(p.card(path), "assign")
    assert (link["values"], link["current"], link["linked_to"], link["files"]) == (
        len(loose), len(loose), {"study": "ABC-1", "arm": "Test"}, ["loose-profile.csv"])
    # linked again elsewhere: the first link stays on ABC-1's list, saying none of its values are its own now
    moved = p.post("delivery/values:assign", {"targets": loose, "new_study": "ABC-2", "why": "another study after all"})
    assert moved.status_code == 200, moved.text
    (first,) = _decided(p.card(path), "assign")
    assert (first["id"], first["current"]) == (link["id"], 0)


@pytest.mark.req("T-47", "F-402", "F-404")
def test_a_blinded_studys_decisions_and_audit_trail_withhold_its_values_and_reason_digits(project):
    p = project(blinding=True)
    workbook = synthetic.messy_workbook()
    p.deliver(workbook, ("loose-profile.csv", LOOSE))
    path = p.subject("230-23")
    # the delivery's clean-up in a file that holds no value of 230-23: in the card's fold, its why is said as written
    (region,) = next(f for d in p.page()["deliveries"] for f in d["files"] if f["sha256"] == _sha(LOOSE))["regions"]
    aside = p.post("delivery/regions:exclude", {"file_sha256": _sha(LOOSE), "regions": [region["region_id"]], "scope": "regions",
                                                 "why": "the 2nd copy of the 12 mg run"})
    assert aside.status_code == 200, aside.text
    why = "CSR 230-23 table 14.2.1: 50 mg oral, 24 subjects, Cmax 41.2 ng/mL kept for external validation"
    for field, value in (("route", "oral"), ("n", 24), ("intended_use", "external_validation")):
        answer = p.post(f"{path}:enter", {"field": field, "value": value, "why": why})
        assert answer.status_code == 200, answer.text
    assert _accept_note(p, workbook).status_code == 200          # a decision about a file that holds its values
    card = p.card(path)
    assert card["blinded"] is True
    entered = _decided(card, "entry")
    assert len(entered) == 3 and all(d["value"] is None for d in entered)
    assert all(not any(ch.isdigit() for ch in d["why"]) and "Cmax ••.• ng/mL" in d["why"] for d in entered)
    (note,) = _decided(card, "not_data")
    assert note["why"] == "a working note, not data"                       # no digit to mask
    # only what is about the blinded study or its files is masked: the fold's decision about the other file is not
    (other_file,) = _decided(card, "not_data", "delivery")
    assert (other_file["files"], other_file["why"]) == (["loose-profile.csv"], "the 2nd copy of the 12 mg run")
    # the audit trail's view: the reasons of the decisions about it are masked while it is blinded; the chain verifies
    trail = p.get("audit", limit=2000).json()["data"]
    entries = [e for e in trail["events"] if e["action"] == "intake.entry"]
    assert len(entries) == 3 and all("41.2" not in e["reason"] and "••.•" in e["reason"] for e in entries)
    assert trail["chain_verifies"] is True
    assert all("41.2" not in (e["reason"] or "") for e in trail["events"])
    # another study's decisions are not masked
    other = p.subject("231-24")
    assert p.post(f"{other}:enter", {"field": "n", "value": 12, "why": "protocol 231-24, 12 subjects"}).status_code == 200
    (said,) = [e for e in p.get("audit").json()["data"]["events"] if e["reason"] == "protocol 231-24, 12 subjects"]
    assert said["action"] == "intake.entry"
    # a decision about a file that holds a blinded study's values: the refusal of a second one names where, who, when
    again = _accept_note(p, workbook)
    assert again.status_code == 409 and again.json()["detail"]["code"] == "CONFLICT"
    assert again.json()["detail"]["decided"][0]["where"] == OUTSIDE_NOTE


@pytest.mark.req("T-47", "F-402")
def test_a_study_the_delivery_blinds_is_withheld_and_refused_on_the_sheet_form_and_in_the_client_files(project):
    p = project(blinding=True)
    workbook, pdf = synthetic.messy_workbook(), synthetic.pdf_report(unruled_table=False)
    p.deliver(workbook, pdf)
    sid, report = client_data.submission_id(_sha(workbook.data)), _sha(pdf.data)
    group = "study:231-24"                         # the sheet form read the Fed sheet as study 231-24, still to confirm
    before = next(g for g in p.get("client-review").json()["data"]["groups"] if g["id"] == group)
    assert before["blinded"] is False and before["state"] == "to_confirm"
    files = {f["file"]: f for f in p.get("client-data").json()["data"]["files"]}
    assert files[pdf.name]["blinded"] is False and any(i["line"] for i in files[pdf.name]["inventory"])
    assert p.get(f"client-data/{sid}/sheets/Fed").status_code == 200
    page = p.get(f"documents/{report}/pages/2").json()["data"]
    assert page["blinded"] is False and any(ch.isdigit() for ch in page["text"])
    # a figure the reading agent suggested from the report (agents are off here: recorded as its reading would)
    caption = "Figure 2. Study 230-25: mean plasma concentrations after 50 mg (n = 6)"
    client_data.record_document_reading(p.ws, client_data.submission_id(report), facts=[], dissolution=[], links=[], datasets=[],
                                        refused=[], digitization=[], summary="", run_id=None, by="u1",
                                        figures=[{"kind": "concentration_time", "page": 2, "quote": caption, "study_id": "230-25"}])
    (figure,) = p.get("reading-queue").json()["data"]["figures"]
    assert (figure["quote"], figure["study_id"], figure["digitizable"], figure["blinded"]) == (caption, "230-25", True, False)
    assert {d["sha256"]: d["blinded"] for d in p.get("documents").json()["data"]["documents"]}[report] is False
    assert p.get(f"documents/{report}/raw").status_code == 200

    # entered for external validation on its delivery card: the delivery blinds 231-24 and 230-25 (the report's)
    shown = {s.pattern for s in _secrets(p.ws, "230-23")}       # 230-23 stays open: a number it shares too is no leak
    secrets = [s for s in (*_secrets(p.ws, "231-24"), *_secrets(p.ws, "230-25")) if s.pattern not in shown]
    for label in ("231-24", "230-25"):
        entered = p.post(f"{p.subject(label)}:enter", {"field": "intended_use", "value": "external_validation",
                                                         "why": "the plan keeps it for external validation"})
        assert entered.status_code == 200 and entered.json()["data"]["blinded"] is True
    # the client review: its group says blinded and withholds what the sheet form read of it
    answer = p.get("client-review")
    blinded = next(g for g in answer.json()["data"]["groups"] if g["id"] == group)
    assert blinded["blinded"] is True
    assert all(f["value"] == "withheld (blinded)" and f["stored"] is None for f in blinded["facts"])
    (draft,) = [i for i in blinded["items"] if i["kind"] == "draft"]
    assert (draft["draft"]["answers"], draft["draft"]["offers"], draft["draft"]["prefill"], draft["draft"]["points"]) == ({}, {}, {}, None)
    assert _leaks(secrets, answer.text) == []
    assert next(g for g in answer.json()["data"]["groups"] if g["id"] == "study:230-23")["blinded"] is False
    # the sheet form refuses to read, finish or confirm it until the MAP is signed (409 BLINDED, as the delivery's card)
    for refused in (p.get(f"client-data/{sid}/sheets/Fed"),
                    p.post("client-review:finish", {"file": sid, "sheet": "Fed", "answers": {"purpose": "model_building"}}),
                    p.post("client-review:confirm", {"group": group})):
        assert refused.status_code == 409 and refused.json()["detail"]["code"] == "BLINDED", refused.text
        assert _leaks(secrets, refused.text) == []
    assert p.get(f"client-data/{sid}/sheets/Fasting").status_code == 200        # another study's sheet stays open
    assert not any(d.study.get("study_id") == "231-24" for d in all_datasets(p.ws))
    # the client files: a file that holds a blinded study's values gives no page's line, and its pages' digits are masked
    answer = p.get("client-data")
    files = {f["file"]: f for f in answer.json()["data"]["files"]}
    assert files[pdf.name]["blinded"] is True and files[workbook.name]["blinded"] is True
    assert files[pdf.name]["inventory"] and all(i["line"] is None for i in files[pdf.name]["inventory"])
    assert files[workbook.name]["readings"]["Fed"]["points"] is None and files[workbook.name]["readings"]["Fed"]["form"] is None
    assert "Fed" in files[workbook.name]["blinded_sheets"] and "Fasting" not in files[workbook.name]["blinded_sheets"]
    assert _leaks(secrets, answer.text) == []
    for number in (2, 3):
        page = p.get(f"documents/{report}/pages/{number}")
        assert page.status_code == 200 and page.json()["data"]["blinded"] is True
        assert not any(ch.isdigit() for ch in page.json()["data"]["text"]) and _leaks(secrets, page.text) == []
    # their originals are not served, the documents' list says so (the digitizer offers neither), and the figure the
    # report suggests says nothing it shows and is not offered for digitizing (final review INT-3)
    for sha in (report, _sha(workbook.data)):
        raw = p.get(f"documents/{sha}/raw")
        assert raw.status_code == 409 and raw.json()["detail"]["code"] == "BLINDED", raw.text
    listed = {d["sha256"]: d["blinded"] for d in p.get("documents").json()["data"]["documents"]}
    assert listed[report] is True and listed[_sha(workbook.data)] is True
    queue = p.get("reading-queue")
    (figure,) = queue.json()["data"]["figures"]
    assert (figure["quote"], figure["study_id"], figure["product"], figure["digitizable"], figure["blinded"]) == ("", "", "", False, True)
    assert (figure["file"], figure["page"]) == (pdf.name, 2) and "230-25" not in queue.text and _leaks(secrets, queue.text) == []
    (suggested,) = {f["file"]: f for f in p.get("client-data").json()["data"]["files"]}[pdf.name]["figure_suggestions"]
    assert (suggested["quote"], suggested["study_id"], suggested["blinded"]) == ("", "", True)
    # a file with no blinded value stays served
    assert p.get(f"documents/{_sha(LOOSE)}/raw").status_code in (200, 404)


@pytest.mark.req("T-47", "F-402")
def test_a_study_blinded_only_by_the_projects_list_is_withheld_on_the_sheet_form_as_the_delivery_withholds_one(project):
    """Final review INT-2 (b), INT-3: a study the project's blinding list holds (a dataset read for external validation)
    that no delivery study is: its sheet is not read, its group not confirmed, its file's original not served; the
    dataset's reveal for a check, with a reason on the audit chain, works as it did."""
    p = project(blinding=True)
    ref = _arm_workbook("Reference", period=False)
    p.deliver(("abc-reference.xlsx", ref))
    sid = client_data.submission_id(_sha(ref))
    group = "study:abc-REF"
    assert p.get(f"client-data/{sid}/sheets/Sheet1").status_code == 200
    assert p.get(f"documents/{_sha(ref)}/raw").status_code == 200
    answers = {"n": 4, "purpose": "external_validation", "route": "oral", "formulation": "ir_tablet", "food_state": "fasted", "dose": 50}
    finished = p.post("client-review:finish", {"file": sid, "sheet": "Sheet1", "answers": answers})
    assert finished.status_code == 200, finished.text
    (made,) = [d for d in all_datasets(p.ws) if d.study.get("study_id") == "abc-REF"]
    assert made.purpose == "external_validation"
    assert p.get("blinding").json()["data"]["on"] is True and not any(s["label"] == "abc-REF" for s in p.page()["subjects"])
    # on the project's list now: withheld as a study the delivery blinds is
    blinded = next(g for g in p.get("client-review").json()["data"]["groups"] if g["id"] == group)
    assert blinded["blinded"] is True and all(f["value"] == "withheld (blinded)" for f in blinded["facts"])
    # round 4: its card says why, from the list's own reason (no delivery study is there to give one)
    assert blinded["blinded_why"] == "the project's blinding list names it (study abc-REF): a dataset of it is entered for external validation"
    assert all(g["blinded_why"] is None for g in p.get("client-review").json()["data"]["groups"] if not g["blinded"])
    for refused in (p.get(f"client-data/{sid}/sheets/Sheet1"), p.post("client-review:confirm", {"group": group}),
                    p.get(f"documents/{_sha(ref)}/raw")):
        assert refused.status_code == 409 and refused.json()["detail"]["code"] == "BLINDED", refused.text
    files = {f["file"]: f for f in p.get("client-data").json()["data"]["files"]}
    assert files["abc-reference.xlsx"]["blinded"] is True and files["abc-reference.xlsx"]["blinded_sheets"] == ["Sheet1"]
    assert {d["sha256"]: d["blinded"] for d in p.get("documents").json()["data"]["documents"]}[_sha(ref)] is True
    page = p.get(f"documents/{_sha(ref)}/pages/1").json()["data"]
    assert page["blinded"] is True and not any(ch.isdigit() for ch in page["text"])
    # the dataset's reveal for a check is unchanged: its values, with the reason on the audit chain (never the file)
    shown = p.post(f"datasets/{made.id}:reveal", {"reason": "check the transcription"})
    assert shown.status_code == 200 and any(v is not None for s in shown.json()["data"]["series"] for v in s["values"])
    assert [e.reason for e in p.events("dataset.reveal")] == ["check the transcription"]
    assert p.get(f"documents/{_sha(ref)}/raw").status_code == 409
    # blinding off (as once the plan is signed): served and read again
    FileWriteStore(str(p.store.root)).put_project("t1", {"id": "p1", "name": "P1", "compounds": [synthetic.DRUG], "openQuestions": 0,
                                                         "risk": "medium", "questions": [], "pipeline": True,
                                                         "blinding": {"on": False, "reason": "the MIDD lead's choice"}})
    assert p.get(f"client-data/{sid}/sheets/Sheet1").status_code == 200 and p.get(f"documents/{_sha(ref)}/raw").status_code == 200


@pytest.mark.req("T-47", "F-402")
def test_a_study_the_delivery_blinds_has_its_datasets_withheld_wherever_the_sheet_form_says_they_are(project):
    """Final review round 6 (the owner's copy): a study the delivery blinds by its card's purpose, the project's list not
    holding it, while a dataset of its name is listed (read with the sheet form for model building before the card said
    anything; in the model on the owner's copy). The sheet form's card said its values are withheld, but the evidence
    redacted the list's studies only, so the dataset's line beside it offered "Show the points". One rule now
    (`BlindedSources.withholds`): the evidence withholds its points and says why, the client review's group of it, the
    inputs' Studies row and catalog, the Run page's studies and the reveal's audit follow the same rule."""
    p = project(blinding=True)
    workbook = synthetic.messy_workbook()
    p.deliver(workbook)
    sid = client_data.submission_id(_sha(workbook.data))
    answers = {"n": 6, "route": "oral", "formulation": "ir_tablet", "food_state": "fed", "dose": 100, "purpose": "model_building"}
    assert p.post("client-review:finish", {"file": sid, "sheet": "Fed", "answers": answers}).status_code == 200
    (read,) = [d for d in all_datasets(p.ws) if d.study.get("study_id") == "231-24"]

    def line() -> dict[str, Any]:
        return next(d for d in p.get("evidence").json()["data"]["datasets"] if d["id"] == read.id)

    shown = line()
    assert not shown.get("blinded") and any(v is not None for s in shown["series"] for v in s["values"])
    entered = p.post(f"{p.subject('231-24')}:enter", {"field": "intended_use", "value": "external_validation",
                                                       "why": "the plan keeps it for external validation"})
    assert entered.status_code == 200 and entered.json()["data"]["blinded"] is True
    assert "231-24" not in p.get("blinding").json()["data"]["external"]        # the delivery blinds it, not the list
    group = next(g for g in p.get("client-review").json()["data"]["groups"] if g["id"] == "study:231-24")
    why = "it is entered for external validation on its card"
    assert (group["blinded"], group["blinded_why"]) == (True, why)
    # the evidence: its points and reported PK withheld, with the reason the sheet form's card gives
    withheld = line()
    assert (withheld["blinded"], withheld["blinded_why"]) == (True, why)
    assert all(v is None for s in withheld["series"] for v in s["values"]) and all(r["value"] is None for r in withheld["reported"])
    assert "231-24" in p.get("evidence").json()["data"]["blinding"]["blinded"]
    # in the model (the owner's copy): its catalog row has no profile, its Studies row and the Run page say blinded
    decide_dataset(p.ws, read.id, state=EvidenceState.ACCEPTED, reason="confirmed with the sheet form", by="u1")
    refresh_inputs(p.ws, by="u1")
    inputs = p.get("inputs").json()["data"]
    assert next(r for r in inputs["studies"] if r["study_id"] == "231-24")["blinded"] is True
    (row,) = [r for r in inputs["catalog"]["content"]["studies"] if r["study_id"] == "231-24"]
    assert row["blinded"] is True and "profile" not in row
    assert line()["blinded"] is True
    run = p.client.get("/api/v1/projects/p1/studies", headers=_auth("t")).json()["data"]["studies"]
    assert next(s for s in run if s["study_id"] == "231-24")["blinded"] is True
    # its reveal for a check: its values, with the reason on the audit chain, as for a study the list holds
    revealed = p.post(f"datasets/{read.id}:reveal", {"reason": "check the transcription"})
    assert revealed.status_code == 200 and any(v is not None for s in revealed.json()["data"]["series"] for v in s["values"])
    assert [e.reason for e in p.events("dataset.reveal")] == ["check the transcription"]
    # its card's purpose corrected: no view withholds it any more
    (purpose,) = [v for v in LedgerView(p.ws).values(field="intended_use") if v.method == "person"]
    corrected = p.post(f"{p.subject('231-24')}:enter", {"supersedes": purpose.id, "value": "model_building",
                                                         "why": "entered on the wrong study"})
    assert corrected.status_code == 200 and corrected.json()["data"]["blinded"] is False, corrected.text
    assert not line().get("blinded") and any(v is not None for s in line()["series"] for v in s["values"])
    assert next(r for r in p.get("inputs").json()["data"]["studies"] if r["study_id"] == "231-24")["blinded"] is False


@pytest.mark.req("T-47", "F-402", "F-404")
def test_the_sheet_form_loads_a_study_only_for_what_its_delivery_card_says_it_is_for(project):
    """Final review INT-2 (a): a study entered for external validation on its delivery card is not read or loaded as model
    building through the sheet form (409 PURPOSE_DIFFERS naming both); with no purpose given, the card's is taken."""
    p = project()
    workbook = synthetic.messy_workbook()
    p.deliver(workbook)
    sid = client_data.submission_id(_sha(workbook.data))
    group = "study:231-24"                         # the sheet form read the Fed sheet as study 231-24, still to confirm
    answers = {"n": 6, "route": "oral", "formulation": "ir_tablet", "food_state": "fed", "dose": 100}
    # read as model building before the card said anything: saved, to confirm
    first = p.post("client-review:finish", {"file": sid, "sheet": "Fed", "answers": {**answers, "purpose": "model_building"}})
    assert first.status_code == 200, first.text
    (read,) = [d for d in all_datasets(p.ws) if d.study.get("study_id") == "231-24"]
    assert read.purpose == "model_building"
    entered = p.post(f"{p.subject('231-24')}:enter", {"field": "intended_use", "value": "external_validation",
                                                       "why": "the plan keeps it for external validation"})
    assert entered.status_code == 200, entered.text
    # the card says external validation: confirming the model-building reading is refused, naming both
    refused = p.post("client-review:confirm", {"group": group})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "PURPOSE_DIFFERS", refused.text
    message = refused.json()["detail"]["message"]
    assert "study 231-24 is entered for external validation on its card" in message and "says model building" in message
    assert dataset(p.ws, read.id).state is EvidenceState.PROPOSED
    # a sheet the sheet form has not saved yet (230-23's Fasting sheet), its card saying model building: another purpose is
    # refused before anything is saved, and with none given the card's is taken
    assert p.post(f"{p.subject('230-23')}:enter", {"field": "intended_use", "value": "model_building",
                                                   "why": "the protocol"}).status_code == 200
    fasting = {"n": 24, "route": "oral", "formulation": "ir_tablet", "food_state": "fasted", "dose": 50}
    other = p.post("client-review:finish", {"file": sid, "sheet": "Fasting", "answers": {**fasting, "purpose": "external_validation"}})
    assert other.status_code == 409 and other.json()["detail"]["code"] == "PURPOSE_DIFFERS", other.text
    assert "study 230-23 is entered for model building" in other.json()["detail"]["message"]
    assert not [d for d in all_datasets(p.ws) if d.study.get("study_id") == "230-23"]

    # a sheet-form group joined to a delivery study by its linked file (abc-REF on ABC-1): with no purpose given, the
    # purpose its card states is taken
    q = project(project_id="p2")
    ref = _arm_workbook("Reference", period=False)
    q.deliver(("abc-reference.xlsx", ref))
    linked = q.post("delivery/values:assign", {"targets": _all_targets(q.page()["unassigned"]), "new_study": "ABC-1",
                                                "why": "the title names study ABC-1"})
    assert linked.status_code == 200, linked.text
    row = next(s for s in linked.json()["data"]["subjects"] if s["label"] == "ABC-1")
    assert row["legacy_groups"] == ["study:abc-REF"]
    assert q.post(f"{q.subject('ABC-1')}:enter", {"field": "intended_use", "value": "external_validation",
                                                  "why": "kept for external validation"}).status_code == 200
    sheet = {"file": client_data.submission_id(_sha(ref)), "sheet": "Sheet1"}
    abc = {"n": 4, "route": "oral", "formulation": "ir_tablet", "food_state": "fasted", "dose": 50}
    said = q.post("client-review:finish", {**sheet, "answers": {**abc, "purpose": "model_building"}})
    assert said.status_code == 409 and "study ABC-1 is entered for external validation" in said.json()["detail"]["message"]
    taken = q.post("client-review:finish", {**sheet, "answers": abc})
    assert taken.status_code == 200, taken.text
    assert {d.purpose for d in all_datasets(q.ws) if d.study.get("study_id") == "abc-REF"} == {"external_validation"}


@pytest.mark.req("T-47", "F-402", "F-404")
def test_the_card_says_for_what_only_what_the_sheet_form_loaded_its_data_for(project):
    """Round 3, INT-2 the other way round (the remainders skeptic's probe): once the sheet form loaded a study's data for
    model building (read and confirmed), its delivery card cannot be set to external validation: 409 PURPOSE_DIFFERS
    naming both, nothing entered, the card unchanged. The same purpose is entered; a reading not confirmed yet (still
    proposed) does not hold the card, as `client-review:confirm` refuses it instead."""
    p = project()
    workbook = synthetic.messy_workbook()
    p.deliver(workbook)
    sid = client_data.submission_id(_sha(workbook.data))
    answers = {"n": 6, "route": "oral", "formulation": "ir_tablet", "food_state": "fed", "dose": 100, "purpose": "model_building"}
    assert p.post("client-review:finish", {"file": sid, "sheet": "Fed", "answers": answers}).status_code == 200
    assert p.post("client-review:confirm", {"group": "study:231-24"}).status_code == 200
    (loaded,) = [d for d in all_datasets(p.ws) if d.study.get("study_id") == "231-24"]
    assert (loaded.purpose, loaded.state) == ("model_building", EvidenceState.ACCEPTED)
    path = p.subject("231-24")
    before = len(LedgerView(p.ws).values(field="intended_use"))
    refused = p.post(f"{path}:enter", {"field": "intended_use", "value": "external_validation", "why": "the plan keeps it for validation"})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "PURPOSE_DIFFERS", refused.text
    message = refused.json()["detail"]["message"]
    assert "study 231-24 is in the model for model building, confirmed with the sheet form" in message
    assert "its card would say external validation" in message
    assert len(LedgerView(p.ws).values(field="intended_use")) == before and p.card(path)["blinded"] is False
    # what it was loaded for is entered; a correction of it to another purpose is refused the same way
    agreed = p.post(f"{path}:enter", {"field": "intended_use", "value": "model_building", "why": "as loaded"})
    assert agreed.status_code == 200, agreed.text
    (entered,) = [v for v in LedgerView(p.ws).values(field="intended_use") if v.method == "person"]
    again = p.post(f"{path}:enter", {"supersedes": entered.id, "value": "external_validation", "why": "changed my mind"})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "PURPOSE_DIFFERS", again.text
    # another study of the delivery, its data not loaded by the sheet form, takes any purpose
    assert p.post(f"{p.subject('230-23')}:enter", {"field": "intended_use", "value": "external_validation",
                                                   "why": "kept for validation"}).status_code == 200

    # settling a disagreement on the purpose is setting it: keeping another purpose is refused the same way
    other = p.post(f"{path}:enter", {"field": "intended_use", "value": "supportive", "why": "a second reading"})
    assert other.status_code == 409 and other.json()["detail"]["code"] == "PURPOSE_DIFFERS"


@pytest.mark.req("T-47", "F-402", "F-404")
def test_keeping_another_purpose_in_a_disagreement_is_refused_once_the_sheet_form_loaded_the_study(project):
    """Round 3, INT-2 the other way round: two purposes entered on a study's card disagree; once the sheet form loaded its
    data for one of them, keeping the other (`:choose`) is refused (409 PURPOSE_DIFFERS) and the disagreement stays
    open; keeping the one its data were loaded for settles it."""
    p = project()
    workbook = synthetic.messy_workbook()
    p.deliver(workbook)
    path = p.subject("231-24")
    for use in ("model_building", "external_validation"):
        entered = p.post(f"{path}:enter", {"field": "intended_use", "value": use, "why": "two readings of the protocol"})
        assert entered.status_code == 200, entered.text
    (conflict,) = [c for c in p.card(path)["conflicts"] if c["field"] == "intended_use"]
    sid = client_data.submission_id(_sha(workbook.data))
    answers = {"n": 6, "route": "oral", "formulation": "ir_tablet", "food_state": "fed", "dose": 100, "purpose": "model_building"}
    assert p.post("client-review:finish", {"file": sid, "sheet": "Fed", "answers": answers}).status_code == 200
    assert p.post("client-review:confirm", {"group": "study:231-24"}).status_code == 200
    by_use = {str(LedgerView(p.ws).value(i).value): i for i in conflict["values"]}
    refused = p.post(f"{path}:choose", {"conflict_id": conflict["id"], "keep": by_use["external_validation"], "why": "validation"})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "PURPOSE_DIFFERS", refused.text
    assert [c["id"] for c in p.card(path)["conflicts"] if c["field"] == "intended_use"] == [conflict["id"]]
    kept = p.post(f"{path}:choose", {"conflict_id": conflict["id"], "keep": by_use["model_building"], "why": "as loaded"})
    assert kept.status_code == 200, kept.text
    assert not [c for c in kept.json()["data"]["conflicts"] if c["field"] == "intended_use"]

def _named_studies(p: Project, *names: str) -> dict[str, str]:
    """One delivered arm workbook per name, its values linked to a new study of that name; label -> subject id."""
    books = {name: _arm_workbook(arm, period=False) for name, arm in zip(names, ("Reference", "Test", "Extra"), strict=False)}
    p.deliver(*((f"{name.replace(' ', '-').lower()}.xlsx", data) for name, data in books.items()))
    for name, data in books.items():
        mine = [v for v in p.page()["unassigned"] if v["file_sha256"] == _sha(data)]
        linked = p.post("delivery/values:assign", {"targets": _all_targets(mine), "new_study": name, "why": "the file's own title"})
        assert linked.status_code == 200, linked.text
    return {s["label"]: s["subject"] for s in p.page()["subjects"] if s["subject_type"] == "study"}


@pytest.mark.req("T-47", "F-402")
def test_the_projects_list_blinds_a_delivery_study_of_its_name_only_whole_and_the_card_says_why(project):
    """Round 3 (the remainders skeptic's side effect 3): a delivery study is blinded by the project's blinding list when
    its name is a listed study's, matched whole on the readers' key (case, spaces and punctuation aside), never as a
    prefix or a part: with "Study 1" listed, "Study 10" stays open. The page's row and the card say why, so a wrong
    match is seen; a study entered for external validation on its card says that instead."""
    p = project(blinding=True)
    ids = _named_studies(p, "Study 1", "Study 10")
    assert set(ids) == {"Study 1", "Study 10"}
    listed = ObservedDataset(id="ds-0a1b2c3d4e", kind="profile", origin=Origin.LITERATURE, purpose="external_validation",
                             study={"study_id": "STUDY-1", "n": 4, "route": "oral", "dose_mg": 50.0, "formulation": "ir_tablet",
                                    "food_state": "fasted", "n_timepoints": 3},
                             series=(Series(times=(1.0, 2.0, 4.0), values=(3.0, 4.0, 2.0), n=4),))
    propose_dataset(p.ws, listed, actor="u1")
    rows = {s["label"]: s for s in p.page()["subjects"]}
    assert rows["Study 1"]["blinded"] is True
    # the reason names the list's own (round 4): why the list holds the study
    listed_why = "the project's blinding list names it (study STUDY-1): a dataset of it is entered for external validation"
    assert rows["Study 1"]["blinded_why"] == listed_why
    assert (rows["Study 10"]["blinded"], rows["Study 10"]["blinded_why"]) == (False, None)
    card = p.card(f"delivery/subjects/study/{ids['Study 1']}")
    assert card["blinded"] is True and card["blinded_why"] == listed_why
    assert p.card(f"delivery/subjects/study/{ids['Study 10']}")["blinded_why"] is None
    # the rule itself: the whole key, never a prefix or a part
    why = review.blinded_why(p.ws, {"blinding": {"on": True}}, None)
    assert set(why) == {ids["Study 1"]}
    # entered for external validation on its card: said so
    assert p.post(f"delivery/subjects/study/{ids['Study 10']}:enter", {"field": "intended_use", "value": "external_validation",
                                                                       "why": "kept for validation"}).status_code == 200
    row = next(s for s in p.page()["subjects"] if s["label"] == "Study 10")
    assert (row["blinded"], row["blinded_why"]) == (True, "it is entered for external validation on its card")


@pytest.mark.req("T-47", "F-402")
def test_a_withheld_paper_names_the_blinded_study_it_is_withheld_for_and_waits_whole(project):
    """Round 3 (the remainders skeptic's side effect 1): a library paper one figure of which was digitized for a study on
    the project's blinding list is withheld whole (its original, its other figures, the digits of every page), as the
    delivery's rule withholds a file; the documents' list and its pages name the study it waits for (`blinded_by`), so
    the Digitizer and the source peek say why. Before, and for another paper, nothing is withheld or named."""
    p = project(blinding=True)
    pdf = synthetic.pdf_report(unruled_table=False)
    added = p.client.post(f"{p.api}/documents", headers=_auth("t"), data={"role": "paper"},
                          files=[("files", ("paper.pdf", pdf.data, "application/pdf"))])
    assert added.status_code == 201, added.text
    paper = added.json()["data"]["documents"][0]["sha256"]
    assert added.json()["data"]["documents"][0]["blinded_by"] == []
    digitized = ObservedDataset(id="ds-5f6e7d8c9b", kind="profile", origin=Origin.LITERATURE, extraction="FIGURE_DIGITIZED",
                                purpose="external_validation", source=SourceRef(doc_sha256=paper, page=2, title="paper.pdf"),
                                study={"study_id": "EXA-301", "n": 6, "route": "oral", "dose_mg": 50.0, "formulation": "ir_tablet",
                                       "food_state": "fasted", "n_timepoints": 3},
                                series=(Series(times=(1.0, 2.0, 4.0), values=(3.0, 4.0, 2.0), n=6),))
    propose_dataset(p.ws, digitized, actor="u1")
    shown = {d["sha256"]: d for d in p.get("documents").json()["data"]["documents"]}
    assert (shown[paper]["blinded"], shown[paper]["blinded_by"]) == (True, ["EXA-301"])
    for number in (1, 2):                                   # every page, not only the figure's
        page = p.get(f"documents/{paper}/pages/{number}").json()["data"]
        assert page["blinded"] is True and page["blinded_by"] == ["EXA-301"] and not any(ch.isdigit() for ch in page["text"])
    assert p.get(f"documents/{paper}/raw").status_code == 409


@pytest.mark.req("T-47", "T-42")
def test_a_tablet_study_whose_delivery_names_no_product_asks_the_client_for_its_products_release(project):
    """Round 3, owner-job gap 11: the client request (To do's "Ask the client") asks for the formulation or dissolution
    of the product a tablet study used when the delivery names no product and nothing here can set a release; a
    solution study asks nothing of it."""
    from modeler_project.study_requirements import UNNAMED_PRODUCT

    p = project()
    ids = _named_studies(p, "OJ-1", "OJ-2")
    for name, form in (("OJ-1", "ir_tablet"), ("OJ-2", "solution")):
        entered = p.post(f"delivery/subjects/study/{ids[name]}:enter", {"field": "formulation", "value": form, "why": "the protocol"})
        assert entered.status_code == 200, entered.text
    asked = [(line["req_id"], line["what"], line["required"]) for line in p.page()["request"] if line["req_id"] == "REQ-form.release"]
    assert asked == [("REQ-form.release", f"{UNNAMED_PRODUCT} — study OJ-1", True)]
