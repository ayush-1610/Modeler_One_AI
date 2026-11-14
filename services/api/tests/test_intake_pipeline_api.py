"""T-47, T-20: the intake pipeline beside today's readers, through the API (contracts §2, §6.5, §8.9; build W).

With `intake_pipeline="both"` every arriving file is stored and recorded first, read by today's reader exactly as before
(the upload answer and the legacy pages are the same as in `legacy`), and read by the pipeline's own job with or without
a model. A ZIP is read member by member. A file today's reader refuses is still recorded, with the reason and its bytes.
With a scripted model (`modeler_agents.evals.scripted.Scripted`, never a live one) a table no rule maps is mapped by an
agent run named `A4-table-mapper`, which is shown no digit of the table's body, and the prose by a run named `A4-prose`.
In `legacy` nothing is written under `intake/`. Every run leaves one `intake.run` audit event with the hash of its line.
Software test data (the made-up Exampleamide): no PK-Sim, no model's judgement.
"""

from __future__ import annotations

import dataclasses
import hashlib
import io
import random
import re
import threading
import time
import types
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from modeler_agents.evals.scripted import Scripted
from modeler_api import agent_jobs, intake_pipeline_jobs, jobs, platform_settings, project_api
from modeler_api.auth import get_verifier
from modeler_api.main import app
from modeler_intake import synthetic
from modeler_intake.source import paragraphs, parse_document
from modeler_project import ArtifactKind, FileProjectStore, Workspace, datasets, evidence, intake_files, intake_pipeline
from modeler_project.brief import empty_brief
from modeler_project.intake_store import IntakeStore
from modeler_project.ledger_view import LedgerView
from modeler_project.mapping_cache import MappingCache
from modeler_project.requirements import derive
from modeler_storage.filestore import FileWriteStore

pytestmark = pytest.mark.req("T-47", "T-20")
H = {"Authorization": "Bearer t"}
BINARY = "application/octet-stream"
PAGES = ("client-data", "client-review", "reading-queue", "inputs")
BROKEN = ("broken.pdf", b"%PDF-1.4 not really a PDF")
UNSUPPORTED = ("trial.xpt", b"HEADER RECORD*******LIBRARY HEADER RECORD")


class FakeVerifier:
    def verify(self, token):
        return {"sub": "u1", "name": "Dev User", "tenant_id": "t1", "realm_access": {"roles": ["modeler-curator"]},
                "projects": ["*"], "acr": "loa2", "auth_time": int(time.time())}


@dataclasses.dataclass
class Project:
    client: TestClient
    store: FileProjectStore
    ws: Workspace

    def upload(self, *files: tuple[str, bytes]):
        return self.client.post("/api/v1/projects/p1/client-data", headers=H,
                                files=[("files", (name, data, BINARY)) for name, data in files])

    def page(self, name: str):
        return self.client.get(f"/api/v1/projects/p1/{name}", headers=H)

    def settle(self) -> None:
        """Until neither background job runs and no run waits (the intake job has drained)."""
        for _ in range(6000):
            if not (jobs.running(self.store, "t1", "p1", "intake") or jobs.running(self.store, "t1", "p1", "reading")
                    or intake_pipeline.pending(self.ws)):
                return
            time.sleep(0.01)
        raise AssertionError("the background jobs did not finish")

    def runs(self):
        return intake_pipeline.runs(self.ws)

    def run_events(self):
        return [r.event for r in self.store.audit("t1").records() if r.event.action == "intake.run"]

    def blob(self, sha256: str) -> bytes | None:
        path = self.store.blob_path("t1", "p1", sha256)
        return path.read_bytes() if path is not None else None


@pytest.fixture
def project(tmp_path, api_settings, monkeypatch):
    """`project(mode)`: a new project store whose API runs with `intake_pipeline=mode`, agents off unless a test gives
    a model. The random ids of today's readers (datasets, evidence) follow one seeded sequence per project, so the
    answers of two projects given the same requests can be compared whole."""
    monkeypatch.delenv("MODELER_LLM_PROVIDER", raising=False)
    made: list[Project] = []

    def make(mode: str) -> Project:
        if made:
            made[-1].settle()                 # one project at a time: its jobs are done before the settings change
        root = tmp_path / f"{mode}-{len(made)}"
        store = FileProjectStore(root / "projects")
        api_settings(read_root=str(root / "read-root"), execution_backend="local", intake_pipeline=mode)
        app.dependency_overrides[get_verifier] = lambda: FakeVerifier()
        app.dependency_overrides[project_api.get_project_store] = lambda: store
        FileWriteStore(str(root / "read-root")).put_project("t1", {
            "id": "p1", "name": "P1", "compounds": [synthetic.DRUG], "openQuestions": 0, "risk": "medium", "questions": [],
            "pipeline": True})
        ws = Workspace(store, "t1", "p1")
        brief = empty_brief(synthetic.DRUG, by="u1")
        first = ws.commit(ArtifactKind.BRIEF, "main", brief.to_content(), actor="u1", reason="start")
        ws.commit(ArtifactKind.REQUIREMENTS, "main", derive(brief).to_content(), derived_from=[first.ref], actor="u1",
                  reason="derived")
        seeded = random.Random(7)
        ids = types.SimpleNamespace(uuid4=lambda: uuid.UUID(int=seeded.getrandbits(128), version=4))
        monkeypatch.setattr(datasets, "uuid", ids)
        monkeypatch.setattr(evidence, "uuid", ids)
        made.append(Project(TestClient(app), store, ws))
        return made[-1]

    yield make
    for one in made:
        one.settle()
    app.dependency_overrides.clear()


_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:\+00:00|Z)")


def _same(answer: Any) -> Any:
    """An answer with what differs between ANY two runs of the same request taken out: the times and the request's id.
    Everything else is compared as it is."""
    if isinstance(answer, dict):
        return {k: _same(v) for k, v in answer.items() if k != "request_id"}
    if isinstance(answer, list | tuple):
        return [_same(v) for v in answer]
    return _TIME.sub("<time>", answer) if isinstance(answer, str) else answer


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _good() -> list[tuple[str, bytes]]:
    """A workbook, a PDF and the filled template: what today's reader accepts."""
    return [(f.name, f.data) for f in (synthetic.messy_workbook(), synthetic.pdf_report(unruled_table=False),
                                       synthetic.template_workbook())]


# --- coexistence: today's answers are unchanged ------------------------------------------------------------------------


def _legacy_answers(one: Project) -> dict[str, Any]:
    """The same requests against one project: two uploads (accepted files; a broken, an unsupported and a good file) and,
    once the background jobs are done, the four legacy pages."""
    word = synthetic.word_report()
    out = {"upload": one.upload(*_good()), "refused": one.upload(BROKEN, UNSUPPORTED, (word.name, word.data))}
    one.settle()
    out.update({name: one.page(name) for name in PAGES})
    return {name: (r.status_code, r.json()) for name, r in out.items()}


def test_the_upload_answers_and_the_legacy_pages_are_the_same_in_both_and_legacy(project):
    legacy = _legacy_answers(project("legacy"))
    both_project = project("both")
    both = _legacy_answers(both_project)
    assert [legacy[name][0] for name in ("upload", "refused", *PAGES)] == [201, 422, 200, 200, 200, 200]
    assert legacy["refused"][1]["detail"] == (
        "broken.pdf: the PDF could not be read: Stream has ended unexpectedly; trial.xpt: unsupported file type .xpt: "
        "use PDF, DOCX, Markdown, text, JSON, CSV, XLSX, PNG or JPEG (added: design-report.docx)")
    assert both["refused"] == legacy["refused"]                               # the same 422 and the same detail
    assert _same(both["upload"]) == _same(legacy["upload"])
    assert [f["file"] for f in legacy["upload"][1]["data"]["read"]] == [name for name, _data in _good()]
    for name in PAGES:                                                        # after the intake job has drained
        assert _same(both[name]) == _same(legacy[name]), name
    assert _same(legacy["inputs"]) != legacy["inputs"][1]                     # (only times and request ids are set aside)
    # the comparison is not empty: the pages hold the files, their sheets and the queue
    assert len(legacy["client-data"][1]["data"]["files"]) == 4 and legacy["reading-queue"][1]["data"]
    # and in `both` the pipeline did read every file meanwhile, the refused ones included
    assert [r.state for r in both_project.runs()] == ["done"] * 6
    assert LedgerView(both_project.ws).values()


def test_the_other_arrival_routes_answer_as_in_legacy_and_record_one_delivery_per_request(project):
    word, pdf = synthetic.word_report(), synthetic.pdf_report(unruled_table=False)

    def requests(one: Project) -> dict[str, Any]:
        c = one.client
        started = c.post("/api/v1/projects:initiate", headers=H, data={"drug_name": synthetic.DRUG, "extract": "false"},
                         files=[("files", ("proposal.txt", b"A PBPK model of Exampleamide for an oral tablet.", "text/plain")),
                                ("client_files", (word.name, word.data, BINARY)), ("client_files", (*BROKEN, BINARY))])
        added = c.post("/api/v1/projects/p1/documents", headers=H, data={"role": "annex", "read": "true"},
                       files=[("files", (pdf.name, pdf.data, BINARY))])
        again = c.post("/api/v1/projects/p1/documents:read-for-data", headers=H)
        one.settle()
        return {name: (r.status_code, r.json()) for name, r in (("started", started), ("added", added), ("again", again))}

    legacy = requests(project("legacy"))
    both_project = project("both")
    both = requests(both_project)
    assert [legacy[name][0] for name in ("started", "added", "again")] == [201, 201, 202]
    assert _same(both) == _same(legacy)
    assert [f["problem"] for f in legacy["started"][1]["data"]["client_files"]] == [
        None, "the PDF could not be read: Stream has ended unexpectedly"]
    assert legacy["added"][1]["data"]["reading"] == [pdf.name]
    # in `both`: the project's start is one delivery (a file read, a file refused), the library document another
    started = Workspace(both_project.store, "t1", both["started"][1]["data"]["project_id"])
    files = intake_files.files(started)
    assert [(f.name, f.delivery, f.legacy_refusal) for f in files] == [
        (word.name, "dl-1", None), ("broken.pdf", "dl-1", "the PDF could not be read: Stream has ended unexpectedly")]
    assert files[0].legacy_sid and [r.state for r in intake_pipeline.runs(started)] == ["done", "done"]
    (document,) = intake_files.files(both_project.ws)
    assert (document.name, document.delivery, document.by) == (pdf.name, "dl-1", "u1") and document.legacy_sid
    assert [r.state for r in both_project.runs()] == ["done"]


# --- what `both` adds ---------------------------------------------------------------------------------------------------


def test_a_zip_gives_one_entry_per_accepted_member_and_a_422_naming_a_refused_member(project):
    one = project("both")
    word, pdf, messy = synthetic.word_report(), synthetic.pdf_report(unruled_table=False), synthetic.messy_workbook()
    whole = synthetic.zipped(word, pdf, name="reports.zip")
    answer = one.upload((whole.name, whole.data))
    assert answer.status_code == 201, answer.text
    read = answer.json()["data"]["read"]
    assert [r["file"] for r in read] == [f"reports.zip/{word.name}", f"reports.zip/{pdf.name}"]
    assert [r["sha256"] for r in read] == [_sha(word.data), _sha(pdf.data)] and all(r["id"] for r in read)
    # a member today's reader refuses: the others are added, and the answer names the member with its reason
    broken = dataclasses.replace(word, name=BROKEN[0], data=BROKEN[1])
    part = synthetic.zipped(messy, broken, name="mixed.zip")
    refused = one.upload((part.name, part.data))
    assert refused.status_code == 422
    assert refused.json()["detail"] == ("mixed.zip/broken.pdf: the PDF could not be read: Stream has ended unexpectedly "
                                        f"(added: mixed.zip/{messy.name})")
    one.settle()
    # each archive and each member is a file of its request's delivery; a member names its container
    files = intake_files.files(one.ws)
    assert [(f.name, f.container.member if f.container else None) for f in files] == [
        ("reports.zip", None), (word.name, word.name), (pdf.name, pdf.name),
        ("mixed.zip", None), (messy.name, messy.name), ("broken.pdf", "broken.pdf")]
    first, second = (d["id"] for d in intake_files.deliveries(one.ws))
    assert [f.delivery for f in files] == [first] * 3 + [second] * 3
    assert files[1].container.sha256 == _sha(whole.data) and files[1].container.name == "reports.zip"
    assert [bool(f.legacy_sid) for f in files] == [False, True, True, False, True, False]
    assert files[5].legacy_refusal == "the PDF could not be read: Stream has ended unexpectedly"
    runs = one.runs()
    assert [r.state for r in runs] == ["done"] * 6 and runs[0].parser == "zip"
    assert {f["file"] for f in one.page("client-data").json()["data"]["files"]} == {word.name, pdf.name, messy.name}


def test_a_zip_asked_to_be_read_for_data_is_read_member_by_member_in_both_and_not_read_in_legacy(project):
    from modeler_api.intake_jobs import ingest_for_reading
    from modeler_project.documents import DocumentLibrary

    word, messy = synthetic.word_report(), synthetic.messy_workbook()
    broken = dataclasses.replace(word, name=BROKEN[0], data=BROKEN[1])
    archive = synthetic.zipped(word, broken, messy, name="annex.zip")
    legacy = project("legacy")
    assert ingest_for_reading(legacy.ws, DocumentLibrary(legacy.ws), [(archive.name, archive.data)], by="u1") == (
        [], [], ["annex.zip: not read for data (only PDF, Word and workbook files are)"])              # as today
    one = project("both")
    sids, reading, not_read = ingest_for_reading(one.ws, DocumentLibrary(one.ws), [(archive.name, archive.data)], by="u1")
    assert reading == [f"annex.zip/{word.name}", f"annex.zip/{messy.name}"] and len(sids) == 2
    assert not_read == ["annex.zip/broken.pdf: not read for data (the PDF could not be read: Stream has ended unexpectedly)"]
    assert [f.name for f in intake_files.files(one.ws)] == ["annex.zip", word.name, "broken.pdf", messy.name]
    assert len({f.delivery for f in intake_files.files(one.ws)}) == 1 and intake_pipeline.pending(one.ws)
    assert intake_pipeline_jobs.kick(one.store, "t1", "p1", by="u1")           # the route's read_later does this
    one.settle()
    assert [r.state for r in one.runs()] == ["done"] * 4


def test_a_broken_and_an_unsupported_file_are_recorded_with_the_reason_and_their_bytes(project):
    one = project("both")
    refused = one.upload(BROKEN, UNSUPPORTED)
    assert refused.status_code == 422
    reasons = dict(part.split(": ", 1) for part in refused.json()["detail"].split("; "))
    assert set(reasons) == {"broken.pdf", "trial.xpt"}
    one.settle()
    files = {f.name: f for f in intake_files.files(one.ws)}
    assert set(files) == {"broken.pdf", "trial.xpt"}
    for name, data in (BROKEN, UNSUPPORTED):
        record = files[name]
        assert (record.sha256, record.size_bytes, record.legacy_sid) == (_sha(data), len(data), None)
        assert record.legacy_refusal == reasons[name]                        # what today's reader said
        assert one.blob(record.sha256) == data                               # stored although it was refused
    # the pipeline says why it read nothing of each: its run is done, with the file's state and reason
    states = {r.sha256: r for r in one.runs()}
    broken, unsupported = states[_sha(BROKEN[1])], states[_sha(UNSUPPORTED[1])]
    assert (broken.state, broken.coverage.state) == ("done", "unreadable") and broken.coverage.reason
    assert (unsupported.state, unsupported.coverage.state, unsupported.coverage.reason) == (
        "done", "unsupported", "no parser for .xpt")
    assert one.page("client-data").json()["data"]["files"] == []             # today's pages do not list them, as before


def test_the_intake_job_reads_every_file_with_agents_off(project):
    one = project("both")
    assert agent_jobs.chat_model("A4") == (None, None)
    delivery = synthetic.delivery()
    answer = one.upload(*((f.name, f.data) for f in delivery))
    # today's reader refuses the listing (it is not UTF-8); the pipeline reads it all the same
    assert answer.status_code == 422 and answer.json()["detail"].startswith("concentrations.csv: ")
    one.settle()
    runs = {r.sha256: r for r in one.runs()}
    assert len(runs) == 4 and all(r.state == "done" and r.by == "u1" for r in runs.values())
    counted = {f.name: runs[_sha(f.data)].counters for f in delivery}
    assert {name: (c.mapped_by_rule, c.unmapped, c.values, c.llm_runs) for name, c in counted.items()} == {
        "messy-delivery.xlsx": (4, 4, 114, 0), "study-report.pdf": (3, 0, 30, 0), "design-report.docx": (1, 0, 6, 0),
        "concentrations.csv": (1, 0, 8, 0)}
    for run in runs.values():
        assert [s.stage for s in run.stages] == list(intake_pipeline.STAGES) and all(s.ok for s in run.stages)
        assert run.agent_runs == () and IntakeStore(one.ws).coverage(run.sha256).summary == run.coverage
    listing = runs[_sha(delivery[3].data)]
    assert listing.coverage.silent_loss == 0 and len(LedgerView(one.ws).values(file_sha256=listing.sha256)) >= 8
    # with no model: no agent run at all, and no reading job (today's flow starts it only with a model)
    assert agent_jobs.project_runs(one.store.root, "t1", "p1") == []
    assert not jobs.running(one.store, "t1", "p1", "intake") and not jobs.running(one.store, "t1", "p1", "reading")
    # the same files again: recorded as repeats of a second delivery, and nothing is read twice
    one.upload(*((f.name, f.data) for f in delivery))
    one.settle()
    assert len(one.runs()) == 4 and [f.repeat for f in intake_files.files(one.ws)] == [False] * 4 + [True] * 4
    assert not intake_pipeline_jobs.kick(one.store, "t1", "p1")               # nothing waits


def test_a_run_left_running_by_a_job_that_stopped_is_recovered_at_the_next_kick(project):
    one = project("both")
    word = synthetic.word_report()
    delivery = intake_files.open_delivery(one.ws, by="u1")
    record = intake_files.record_arrival(one.ws, word.data, word.name, delivery=delivery, by="u1")
    intake_pipeline.enqueue(one.ws, [record], by="u1")
    taken = intake_pipeline.take(one.ws)                      # as a job that stopped with it (a restart): nothing waits
    assert taken.state == "running" and not intake_pipeline.pending(one.ws) and intake_pipeline.unfinished(one.ws)
    assert intake_pipeline_jobs.kick(one.store, "t1", "p1", by="u1")
    one.settle()
    (run,) = one.runs()
    assert (run.state, run.attempt, run.run_id) == ("done", 2, taken.run_id) and not intake_pipeline.unfinished(one.ws)
    assert not intake_pipeline_jobs.kick(one.store, "t1", "p1")


def test_a_job_that_cannot_take_a_run_ends_and_does_not_start_itself_again(project, monkeypatch):
    one = project("both")
    word = synthetic.word_report()
    delivery = intake_files.open_delivery(one.ws, by="u1")
    record = intake_files.record_arrival(one.ws, word.data, word.name, delivery=delivery, by="u1")
    intake_pipeline.enqueue(one.ws, [record], by="u1")
    tried: list[int] = []
    real = intake_pipeline.take

    def no_space(ws):
        tried.append(1)
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(intake_pipeline, "take", no_space)
    assert intake_pipeline_jobs.kick(one.store, "t1", "p1", by="u1")
    for _ in range(2000):
        if not jobs.running(one.store, "t1", "p1", "intake"):
            break
        time.sleep(0.005)
    time.sleep(0.2)                                          # were it to start itself again, it would by now
    assert tried == [1] and not jobs.running(one.store, "t1", "p1", "intake")
    assert intake_pipeline.pending(one.ws) and [r.state for r in one.runs()] == ["queued"]      # nothing lost: it waits
    monkeypatch.setattr(intake_pipeline, "take", real)
    assert intake_pipeline_jobs.kick(one.store, "t1", "p1", by="u1")       # the next arrival (or page) starts it again
    one.settle()
    assert [r.state for r in one.runs()] == ["done"]


@pytest.mark.req("F-404", "T-05")
def test_every_run_leaves_one_intake_run_audit_event_with_the_hash_of_its_line(project):
    one = project("both")
    one.upload(*_good())
    one.upload(BROKEN)
    one.settle()
    runs = one.runs()
    events = one.run_events()
    assert len(runs) == 4 and sorted(e.resource_id for e in events) == sorted(f"p1/{r.run_id}" for r in runs)
    last = {e.body["run_id"]: e for e in IntakeStore(one.ws).runs.entries("run")}        # each run's last line
    for event in events:
        run_id = event.resource_id.split("/", 1)[1]
        line = last[run_id]
        assert (event.actor, event.resource_type) == ("code", "intake")
        assert event.after["row_hash"] == line.hash and event.after["state"] == line.body["state"] == "done"
        assert (event.after["run"], event.after["file_sha256"]) == (run_id, line.body["sha256"])
        assert event.after["ledger_head"] == line.body["ledger_head"]
    assert one.store.audit("t1").verify() is None and IntakeStore(one.ws).runs.verify() == []
    assert IntakeStore(one.ws).files.verify() == [] and IntakeStore(one.ws).facts.verify() == []
    # an edited run line no longer matches the hash its event holds
    log = IntakeStore(one.ws).runs
    lines = log.path.read_text(encoding="utf-8").splitlines()
    lines[-1] = lines[-1].replace('"state":"done"', '"state":"failed"')
    log.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert [p.problem for p in log.verify()] == ["hash"]


def test_legacy_writes_nothing_under_intake(project):
    one = project("legacy")
    assert not intake_pipeline_jobs.enabled()
    whole = synthetic.zipped(synthetic.word_report(), name="reports.zip")
    assert one.upload(*_good()).status_code == 201
    refused = one.upload(BROKEN, (whole.name, whole.data))
    assert refused.status_code == 422 and "reports.zip: unsupported file type .zip" in refused.json()["detail"]   # as today
    one.settle()
    assert not IntakeStore(one.ws).base.exists()
    assert intake_files.files(one.ws) == [] and one.runs() == [] and one.run_events() == []
    assert not intake_pipeline_jobs.kick(one.store, "t1", "p1") and intake_pipeline_jobs.sweep(one.store, "t1", "p1") == 0
    assert intake_pipeline_jobs.open_delivery(one.ws, by="u1") == "" and not IntakeStore(one.ws).base.exists()


def test_sweep_queues_the_files_stored_before_the_pipeline_ran(project, api_settings, tmp_path):
    one = project("legacy")
    assert one.upload(*_good()).status_code == 201
    one.settle()
    # the switch is set to `both` on the same store (the next deployment): the stored files are recorded and read once
    api_settings(read_root=str(tmp_path / "legacy-0" / "read-root"), execution_backend="local", intake_pipeline="both")
    assert intake_pipeline_jobs.sweep(one.store, "t1", "p1") == 3 and intake_pipeline_jobs.sweep(one.store, "t1", "p1") == 0
    assert intake_pipeline_jobs.kick(one.store, "t1", "p1", by="u1")
    one.settle()
    assert [r.state for r in one.runs()] == ["done"] * 3 and {r.by for r in one.runs()} == {"code"}
    assert len({f.delivery for f in intake_files.files(one.ws)}) == 1


# --- the LLM stages, with the scripted model ----------------------------------------------------------------------------

_URINE = ((0, 4, 7.31, 0.146), (4, 8, 5.62, 0.112), (8, 12, 3.94, 0.079), (12, 24, 1.87, 0.037))


def _urine_workbook() -> bytes:
    """One table no rule maps (urine excretion by interval), as the synthetic workbook's Urine sheet lays it out."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Urine"
    ws.append([f"Study 230-31: {synthetic.DRUG} urine excretion (mg) by collection interval"])
    ws.append(["Interval start (h)", "Interval end (h)", "Amount (mg)", "Fraction of dose"])
    for row in _URINE:
        ws.append(list(row))
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _models(monkeypatch, pipeline: Scripted) -> Scripted:
    """The scripted model for the intake job only. Today's reading job, which starts beside it once a model is
    configured, gets a model of its own that answers nothing, so it takes none of the pipeline's turns (§2)."""
    other = Scripted([])
    lock = threading.Lock()

    class Quiet:                       # the reading job's conversations run side by side: one answer at a time
        provider, model = other.provider, other.model

        def complete(self, messages, tools):
            with lock:
                return other.complete(messages, tools)

    monkeypatch.setattr(agent_jobs, "chat_model", lambda agent=None: (
        (pipeline if threading.current_thread().name.startswith("intake-") else Quiet()), None))
    return other


@pytest.mark.req("T-21")
def test_a_first_seen_table_is_mapped_by_a_run_named_a4_table_mapper_whose_prompt_holds_no_body_digit(project, monkeypatch):
    one = project("both")
    spec = synthetic.URINE_SPEC.model_dump(mode="json", by_alias=True, exclude_none=True)
    model = Scripted([[("propose_mapping", {"spec": spec})], []])
    _models(monkeypatch, model)
    assert one.upload(("urine.xlsx", _urine_workbook())).status_code == 201
    one.settle()
    (run,) = one.runs()
    assert run.state == "done" and (run.counters.mapped_by_llm, run.counters.unmapped, run.counters.llm_runs) == (1, 0, 1)
    assert model.answers == ["ACCEPTED"] and len(model.received) == 2          # code accepted it; the model then stopped
    # one agent run, named A4-table-mapper, counted under A4 like every other A4 run, started by who sent the file
    (run_id,) = run.agent_runs
    mine = [r for r in agent_jobs.project_runs(one.store.root, "t1", "p1") if r["agent"] == "A4-table-mapper"]
    assert [r["run_id"] for r in mine] == [run_id]
    record = mine[0]
    assert (record["status"], record["provider"], record["model"], record["started_by"]) == ("COMPLETED", "scripted", "scripted", "u1")
    assert platform_settings.agent_of(record["agent"]) == "A4"
    usage = [u for u in agent_jobs.recorded_usage(one.store.root) if u["run_id"] == run_id]
    assert len(usage) == 1 and (usage[0]["agent"], usage[0]["input_tokens"], usage[0]["output_tokens"]) == ("A4-table-mapper", 2, 2)
    steps = agent_jobs.run_steps(one.store.root, run_id)
    assert [s["kind"] for s in steps] == ["model_turn", "tool_result", "model_turn"]
    # the prompt holds no digit of the table's body: every body cell is shown with its digits as "#"
    prompt = model.user()
    body = prompt.split("Body rows", 1)[1].split("Columns over all body rows", 1)[0]
    assert "# | # | #.# | #.#" in body and not re.search(r"\d", re.sub(r"row \d+:", "", body.split("\n", 1)[1]))
    sent = " ".join(str(m.get("content", "")) for turn in model.received for m in turn)
    for row in _URINE:
        assert not any(str(number) in sent for number in row[2:]), row
    assert "230-31" in prompt and "Amount (mg)" in prompt                      # its caption and header, verbatim
    # the mapping waits for a person's approval in the cache, and code read the values from the cells
    outcome = next(r.outcome for r in IntakeStore(one.ws).coverage(run.sha256).regions)
    assert (outcome.state, outcome.origin) == ("mapped", "llm") and run.coverage.silent_loss == 0
    cache = MappingCache(one.ws)
    entry = cache.get(outcome.mapping.mapping_id, outcome.mapping.version)
    assert (entry.origin, entry.by, cache.status(entry.mapping_id, entry.version)) == ("llm", f"agent:{run_id}", "proposed")
    assert entry.origin_detail.startswith("scripted/scripted prompt ") and entry.origin_detail.endswith(f" run {run_id}")
    ledger = LedgerView(one.ws)
    amounts = [v for v in ledger.values(field="excretion.amount")]
    assert [(v.value, v.unit) for v in amounts] == [(row[2], "mg") for row in _URINE]
    assert {ledger.entity(v.entity.study).label for v in amounts} == {"230-31"}
    assert {v.level for v in amounts} == {"new_mapping"}


@pytest.mark.req("T-21")
def test_the_prose_is_read_by_a_run_named_a4_prose_and_only_what_code_checks_is_kept(project, monkeypatch):
    one = project("both")
    pdf = synthetic.pdf_report(unruled_table=False)
    doc = parse_document(pdf.data, pdf.name)
    shown = [p for region in doc.regions if region.kind == "prose" for p in paragraphs(doc, region.id)]
    at = next(i for i, p in enumerate(shown, start=1) if "50 mg" in p.text)   # the pipeline numbers them from 1
    quote = f"{synthetic.DRUG} was given as a single oral dose of 50 mg."
    model = Scripted([[("state_fact", {"field": "dose", "value": 500, "quote": quote, "paragraph": at, "study": "230-23"}),
                       ("state_fact", {"field": "dose", "value": 50, "quote": quote, "paragraph": at, "study": "230-23"})], []])
    _models(monkeypatch, model)
    assert one.upload((pdf.name, pdf.data)).status_code == 201
    one.settle()
    (run,) = one.runs()
    assert run.state == "done" and (run.counters.mapped_by_rule, run.counters.mapped_by_llm, run.counters.llm_runs) == (3, 0, 1)
    refused, accepted = model.answers
    assert refused.startswith("REFUSED: ") and accepted.startswith("ACCEPTED")
    (run_id,) = run.agent_runs                                                # the rules mapped the tables: no mapper run
    record = next(r for r in agent_jobs.project_runs(one.store.root, "t1", "p1") if r["run_id"] == run_id)
    assert (record["agent"], record["status"], platform_settings.agent_of(record["agent"])) == ("A4-prose", "COMPLETED", "A4")
    assert not re.search(r"\| *\d", model.user())                              # paragraphs only, never a table's rows
    prose = [v for v in LedgerView(one.ws).values(field="dose") if v.method == "prose"]
    assert [(v.value, v.unit, v.verbatim) for v in prose] == [(50.0, "mg", quote)]
    region = next(r.outcome for r in IntakeStore(one.ws).coverage(run.sha256).regions if r.region.kind == "prose")
    assert (region.state, region.origin) == ("mapped", "llm") and run_id in region.reason
