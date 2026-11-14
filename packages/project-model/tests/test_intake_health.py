"""Pipeline health for the administrator (plan §7.8, contracts §8.10): the counters `intake_health.summary` reads from
the run lines of two companies' projects, per company and pooled; counts only, and nothing repaired."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest

from modeler_project import intake_health as health
from modeler_project.intake_records import CoverageSummary, FileRecord, RunCounters, RunRecord, StageTiming
from modeler_project.intake_store import IntakeStore
from modeler_project.store import FileProjectStore
from modeler_project.workspace import Workspace

pytestmark = pytest.mark.req("T-47", "F-404", "T-05")

EARLY, LATE = "2026-11-10T08:00:00.000Z", "2026-11-12T08:00:00.000Z"


def _sha(name: str) -> str:
    return hashlib.sha256(name.encode()).hexdigest()


def _coverage(state: str = "read", **counts: int) -> CoverageSummary:
    base = dict(regions=4, regions_mapped=3, regions_excluded=0, regions_unread=1, numeric_cells=100, cells_used=90,
                cells_excluded=5, cells_silent=5, silent_loss=5, outside_items=3, outside_numeric=1)
    return CoverageSummary(state=state, reason="" if state == "read" else f"{state}: a made-up reason",  # type: ignore[arg-type]
                           **{**base, **counts})


class Project:
    """One project's intake logs, written as the pipeline writes them."""

    def __init__(self, root, tenant: str, project: str):
        self.ws = Workspace(FileProjectStore(root), tenant, project)
        self.store = IntakeStore(self.ws)
        self.runs = 0

    def file(self, name: str) -> str:
        sha = _sha(f"{self.ws.tenant_id}/{self.ws.project_id}/{name}")
        self.store.files.append("file", FileRecord(file_id=f"fl-{sha[:12]}", sha256=sha, name=name, size_bytes=10,
                                                   delivery="dl-1", by="code", at=EARLY).model_dump(mode="json"))
        return sha

    def run(self, name: str, *, state: str = "done", at: str = EARLY, coverage: CoverageSummary | None = None,
            stages: tuple[tuple[str, float, bool], ...] = (("parse", 1.0, True),), sha: str | None = None,
            **counters: int) -> str:
        sha = sha or self.file(name)
        self.runs += 1
        run_id = f"run-{self.runs}"
        queued = RunRecord(run_id=run_id, file_id=f"fl-{sha[:12]}", sha256=sha, delivery="dl-1", state="queued",
                           queued_at=at, by="code")
        self.store.runs.append("run", queued.model_dump(mode="json"))
        if state != "queued":
            ended = queued.model_copy(update={
                "state": state, "started_at": at, "finished_at": None if state == "running" else at,
                "stages": tuple(StageTiming(stage=s, seconds=t, ok=ok) for s, t, ok in stages),  # type: ignore[arg-type]
                "counters": RunCounters(**counters), "coverage": coverage,
                "error": "ValueError: a made-up failure" if state == "failed" else ""})
            self.store.runs.append("run", ended.model_dump(mode="json"))
        return sha


@pytest.fixture
def root(tmp_path):
    """Two companies. Company A: two projects; company B: one."""
    a1 = Project(tmp_path, "company-a", "p1")
    a1.run("pk.xlsx", coverage=_coverage(), stages=(("parse", 1.0, True), ("map", 0.2, True), ("execute", 0.5, True)),
           regions=4, tables=4, mapped_by_cache=3, unmapped=1, values=120, outside_items=3, anchors_checked=120)
    a1.run("report.pdf", coverage=_coverage("partly_read", silent_loss=12, regions_unread=2, outside_numeric=0),
           stages=(("parse", 9.0, True), ("map", 0.4, True), ("map_llm", 30.0, True)), regions=6, tables=5,
           mapped_by_rule=2, mapped_by_llm=1, unmapped=2, values=40, needs_ocr_pages=3, llm_runs=1, outside_items=7,
           anchors_checked=40, anchors_unresolved=2)
    a1.run("raw.dat", coverage=_coverage("unsupported", regions=0, regions_mapped=0, regions_unread=0, numeric_cells=0,
                                         cells_used=0, cells_excluded=0, cells_silent=0, silent_loss=0, outside_items=0,
                                         outside_numeric=0), stages=(("parse", 0.1, True),))
    a1.run("LEGACY.DAT", coverage=_coverage("unsupported", regions=0, regions_mapped=0, regions_unread=0, numeric_cells=0,
                                            cells_used=0, cells_excluded=0, cells_silent=0, silent_loss=0, outside_items=0,
                                            outside_numeric=0), stages=(("parse", 0.1, True),))
    a1.run("README", coverage=_coverage("unsupported", silent_loss=0, regions_unread=0, outside_numeric=0),
           stages=(("parse", 0.1, True),))
    a2 = Project(tmp_path, "company-a", "p2")
    a2.run("broken.xlsx", state="failed", stages=(("parse", 2.0, False),))
    a2.run("waiting.xlsx", state="queued", at=LATE)
    b1 = Project(tmp_path, "company-b", "p1")
    b1.run("locked.pdf", at=LATE, coverage=_coverage("unreadable", silent_loss=0, regions_unread=0, outside_numeric=0),
           stages=(("parse", 4.0, True),))
    # a file run twice: its latest run counts (the first one left a table unread, the second read it from the cache)
    twice = b1.run("pk.xlsx", coverage=_coverage(), stages=(("parse", 3.0, True),), mapped_by_rule=1, unmapped=1, values=10)
    b1.run("pk.xlsx", sha=twice, at=LATE, coverage=_coverage(silent_loss=0, regions_unread=0, outside_numeric=0),
           stages=(("parse", 2.0, True), ("ledger", 0.3, True)), regions=2, tables=2, mapped_by_cache=2, values=20)
    b1.run("failing.docx", state="failed", at=LATE, stages=(("parse", 1.0, True), ("ledger", 0.2, False)), regions=1)
    (tmp_path / "not-a-company").mkdir()                              # a folder with no projects is no company
    return tmp_path


def test_the_counters_from_the_run_lines_of_two_companies(root):
    found = health.summary(root)
    assert [c["tenant"] for c in found["companies"]] == ["company-a", "company-b"] and found["since"] is None
    a, b = found["companies"]
    assert (a["projects"], a["files"], a["runs"]) == (2, 7, 7) and (b["projects"], b["files"], b["runs"]) == (1, 3, 4)
    assert a["files_by_state"] == {"read": 1, "partly_read": 1, "unsupported": 3, "unreadable": 0, "failed": 1, "waiting": 1}
    assert b["files_by_state"] == {"read": 1, "partly_read": 0, "unsupported": 0, "unreadable": 1, "failed": 1, "waiting": 0}
    # where each table's mapping came from, and the shares of their sum (the cache hit rate)
    assert a["mapping"] == {"cache": 3, "rule": 2, "llm": 1, "unread": 3}
    assert a["mapping_shares"] == {"cache": 3 / 9, "rule": 2 / 9, "llm": 1 / 9, "unread": 3 / 9}
    assert b["mapping"] == {"cache": 2, "rule": 0, "llm": 0, "unread": 0} and b["mapping_shares"]["cache"] == 1.0
    # a run that failed at the parse stage, and a file parsed as unreadable; a later failure is not the parser's
    assert (a["parser_failures"], b["parser_failures"]) == (1, 1)
    assert a["unsupported_by_extension"] == {"(none)": 1, ".dat": 2} and b["unsupported_by_extension"] == {}
    assert (a["outside_items"], a["outside_numeric"], a["anchors_checked"], a["anchors_unresolved"]) == (10, 1, 160, 2)
    assert (a["needs_ocr_pages"], a["silent_loss"], a["regions"], a["regions_unread"], a["values"], a["llm_runs"]) == (
        3, 17, 10, 3, 160, 1)
    assert (b["values"], b["silent_loss"], b["regions"], b["anchors_unresolved"]) == (20, 0, 3, 0)
    # stage times: the count, the median and the 90th percentile (nearest rank) of the samples
    assert a["stage_seconds"]["parse"] == {"n": 6, "median": 0.55, "p90": 9.0}
    assert a["stage_seconds"]["map"] == {"n": 2, "median": pytest.approx(0.3), "p90": 0.4}
    assert a["stage_seconds"]["map_llm"] == {"n": 1, "median": 30.0, "p90": 30.0} and "ledger" not in a["stage_seconds"]
    assert b["stage_seconds"] == {"ledger": {"n": 2, "median": 0.25, "p90": 0.3}, "parse": {"n": 3, "median": 2.0, "p90": 4.0}}
    # in all: the sums, and the percentiles over the pooled samples (never a median of medians)
    everything = found["all"]
    assert (everything["projects"], everything["files"], everything["runs"]) == (3, 10, 11)
    assert everything["files_by_state"] == {s: a["files_by_state"][s] + b["files_by_state"][s] for s in health.FILE_STATES}
    assert everything["mapping"] == {"cache": 5, "rule": 2, "llm": 1, "unread": 3}
    assert everything["mapping_shares"]["cache"] == 5 / 11 and sum(everything["mapping_shares"].values()) == pytest.approx(1.0)
    assert everything["stage_seconds"]["parse"] == {"n": 9, "median": 1.0, "p90": 9.0}
    assert everything["parser_failures"] == 2 and everything["damaged_logs"] == 0
    # counts only: no file name, no project name, no value of a client
    text = json.dumps(found)
    assert not any(word in text for word in ("pk.xlsx", "report.pdf", "locked", "raw.dat", "p1", "p2", "made-up"))
    assert json.loads(text) == found


def test_one_company_and_a_period(root):
    only = health.summary(root, tenant="company-b")
    assert [c["tenant"] for c in only["companies"]] == ["company-b"]
    assert only["all"] == {k: v for k, v in only["companies"][0].items() if k != "tenant"}
    # an id the root does not list gives no company: it is compared with the listing, never joined into a path
    for unknown in ("company-c", "../company-a", "company-a/projects/p1", "", "."):
        nothing = health.summary(root, tenant=unknown)
        assert nothing["companies"] == [] and nothing["all"]["files"] == 0 and nothing["all"]["stage_seconds"] == {}
    # since: the runs queued at or after it; a file's earlier run is then not counted
    recent = health.summary(root, since=datetime(2026, 11, 11, tzinfo=UTC))
    a, b = recent["companies"]
    assert recent["since"] == "2026-11-11T00:00:00+00:00"
    assert (a["files"], a["runs"], a["files_by_state"]["waiting"]) == (1, 1, 1) and a["mapping"]["cache"] == 0
    assert (b["files"], b["runs"]) == (3, 3) and b["files_by_state"] == {
        "read": 1, "partly_read": 0, "unsupported": 0, "unreadable": 1, "failed": 1, "waiting": 0}
    naive = health.summary(root, since=datetime.fromisoformat("2026-11-11T00:00:00"))    # a naive moment is read as UTC
    assert naive["since"] == recent["since"] and naive["all"]["runs"] == recent["all"]["runs"]
    assert health.summary(root, since=datetime(2027, 1, 1, tzinfo=UTC))["all"]["runs"] == 0
    # a root that does not exist, or holds nothing, reads as empty
    assert health.summary(root / "nowhere")["companies"] == []


def test_a_damaged_log_is_counted_and_never_repaired(root):
    log = root / "company-b" / "projects" / "p1" / "intake" / "runs.jsonl"
    whole = health.summary(root)
    assert IntakeStore(Workspace(FileProjectStore(root), "company-b", "p1")).runs.verify() == []
    # a changed line that is still a log line: the chain says so, the counters read what the file holds
    text = log.read_text(encoding="utf-8")
    log.write_text(text.replace('"values":20', '"values":21'), encoding="utf-8")
    assert [p.problem for p in IntakeStore(Workspace(FileProjectStore(root), "company-b", "p1")).runs.verify()] == ["hash"]
    assert health.summary(root)["companies"][1]["values"] == 21
    # a line that is no log line: the log is damaged; it is counted, its runs are not, and the file is left as it is
    damaged = text.replace("\n", "\nnot a log line\n", 1)
    log.write_text(damaged, encoding="utf-8")
    found = health.summary(root)
    b = found["companies"][1]
    assert (b["damaged_logs"], b["runs"], b["files"]) == (1, 0, 0) and found["all"]["damaged_logs"] == 1
    assert found["companies"][0] == whole["companies"][0] and log.read_text(encoding="utf-8") == damaged
