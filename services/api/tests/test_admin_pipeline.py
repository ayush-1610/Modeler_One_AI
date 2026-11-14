"""Pipeline health for the administrator, through the API (contracts 2026-11-12 §8.10; plan §7.8): `GET
/api/v1/admin/pipeline` answers the counters `intake_health.summary` reads from the intake pipeline's own run lines, per
company and in all. Only `modeler-admin` opens it, and each look is an `admin.view` event on the owner's audit chain.

The run lines are written as the pipeline writes them (made-up counts: no client file, no value, no PK-Sim)."""

from __future__ import annotations

import hashlib
import json

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from modeler_api import admin_api
from modeler_api.auth import get_verifier
from modeler_api.main import app
from modeler_api.views.admin import PipelineHealth
from modeler_project import FileProjectStore, Workspace
from modeler_project.intake_records import CoverageSummary, FileRecord, RunCounters, RunRecord, StageTiming
from modeler_project.intake_store import IntakeStore

pytestmark = pytest.mark.req("T-47", "F-404", "T-05")

EARLY, LATE = "2026-11-10T08:00:00.000Z", "2026-11-12T08:00:00.000Z"
PEOPLE = {"owner": ("platform", ["modeler-admin"]), "ana": ("acme", ["modeler-viewer", "modeler-curator"]),
          "rev": ("acme", ["modeler-reviewer"])}


class _Verifier:
    """`Bearer ana` signs in as ana, in her company, with her roles."""

    def verify(self, token: str) -> dict:
        tenant, roles = PEOPLE[token]
        return {"sub": token, "name": token.title(), "tenant_id": tenant, "realm_access": {"roles": roles},
                "projects": [], "acr": "loa1"}


def _as(who: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {who}"}


def _coverage(state: str = "read", **counts: int) -> CoverageSummary:
    base = dict(regions=4, regions_mapped=3, regions_excluded=0, regions_unread=1, numeric_cells=100, cells_used=90,
                cells_excluded=5, cells_silent=5, silent_loss=5, outside_items=3, outside_numeric=1)
    return CoverageSummary(state=state, reason="" if state == "read" else f"{state}: a made-up reason",  # type: ignore[arg-type]
                           **{**base, **counts})


def _run(root, tenant: str, project: str, name: str, n: int, *, state: str = "done", at: str = EARLY,
         coverage: CoverageSummary | None = None, stages: tuple[tuple[str, float, bool], ...] = (("parse", 1.0, True),),
         **counters: int) -> None:
    """One file and its run, as the pipeline's logs hold them once the run ended."""
    store = IntakeStore(Workspace(FileProjectStore(root), tenant, project))
    sha = hashlib.sha256(f"{tenant}/{project}/{name}".encode()).hexdigest()
    store.files.append("file", FileRecord(file_id=f"fl-{sha[:12]}", sha256=sha, name=name, size_bytes=10, delivery="dl-1",
                                          by="code", at=at).model_dump(mode="json"))
    queued = RunRecord(run_id=f"run-{n}", file_id=f"fl-{sha[:12]}", sha256=sha, delivery="dl-1", state="queued",
                       queued_at=at, by="code")
    store.runs.append("run", queued.model_dump(mode="json"))
    if state != "queued":
        store.runs.append("run", queued.model_copy(update={
            "state": state, "started_at": at, "finished_at": at,
            "stages": tuple(StageTiming(stage=s, seconds=t, ok=ok) for s, t, ok in stages),  # type: ignore[arg-type]
            "counters": RunCounters(**counters), "coverage": coverage,
            "error": "ValueError: a made-up failure" if state == "failed" else ""}).model_dump(mode="json"))


@pytest.fixture
def client(tmp_path, api_settings):
    """Two companies. acme: a workbook read from the cache, a PDF partly read (a rule, the LLM, OCR needed), an
    unsupported file and a file whose parser failed; beta: one workbook read by a rule, later, and a file that waits."""
    api_settings(read_root=str(tmp_path))
    app.dependency_overrides[get_verifier] = _Verifier
    _run(tmp_path, "acme", "p1", "pk.xlsx", 1, coverage=_coverage(), regions=4, tables=4, mapped_by_cache=3, unmapped=1,
         values=120, outside_items=3, anchors_checked=120,
         stages=(("parse", 1.0, True), ("map", 0.2, True), ("execute", 0.5, True)))
    _run(tmp_path, "acme", "p1", "report.pdf", 2, regions=6, tables=5, mapped_by_rule=2, mapped_by_llm=1, unmapped=2,
         values=40, needs_ocr_pages=3, llm_runs=1, outside_items=7, anchors_checked=40, anchors_unresolved=2,
         coverage=_coverage("partly_read", silent_loss=12, regions_unread=2, outside_numeric=0),
         stages=(("parse", 9.0, True), ("map", 0.4, True), ("map_llm", 30.0, True)))
    _run(tmp_path, "acme", "p2", "raw.dat", 1, stages=(("parse", 0.1, True),),
         coverage=_coverage("unsupported", regions=0, regions_mapped=0, regions_unread=0, numeric_cells=0, cells_used=0,
                            cells_excluded=0, cells_silent=0, silent_loss=0, outside_items=0, outside_numeric=0))
    _run(tmp_path, "acme", "p2", "broken.pdf", 2, state="failed", stages=(("parse", 2.0, False),))
    _run(tmp_path, "beta", "p1", "summary.xlsx", 1, at=LATE, coverage=_coverage(silent_loss=0, regions_unread=0),
         regions=2, tables=2, mapped_by_rule=2, values=30, stages=(("parse", 3.0, True),))
    _run(tmp_path, "beta", "p1", "late.xlsx", 2, at=LATE, state="queued")
    yield TestClient(app)
    app.dependency_overrides.clear()


def _views(tmp_path, tenant: str) -> list[dict]:
    path = tmp_path / tenant / "audit.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    return [e for e in (json.loads(line)["event"] for line in lines) if e["action"] == "admin.view"]


def test_the_counters_come_from_the_run_lines_of_two_companies_and_in_all(client, tmp_path):
    answer = client.get("/api/v1/admin/pipeline", headers=_as("owner"))
    assert answer.status_code == 200, answer.text
    data = answer.json()["data"]
    assert data["since"] is None and data["generated_at"]
    acme, beta = data["companies"]
    assert (acme["tenant"], beta["tenant"]) == ("acme", "beta") and acme["name"] == ""
    assert (acme["projects"], acme["files"], acme["runs"]) == (2, 4, 4)
    assert acme["files_by_state"] == {"read": 1, "partly_read": 1, "unsupported": 1, "unreadable": 0, "failed": 1,
                                      "waiting": 0}
    # the mapping sources as counts and as shares of their sum (the cache hit rate is `cache`)
    assert acme["mapping"] == {"cache": 3, "rule": 2, "llm": 1, "unread": 3}
    assert acme["mapping_shares"] == {"cache": 3 / 9, "rule": 2 / 9, "llm": 1 / 9, "unread": 3 / 9}
    assert acme["parser_failures"] == 1 and acme["unsupported_by_extension"] == {".dat": 1}
    assert (acme["outside_items"], acme["outside_numeric"], acme["anchors_unresolved"], acme["needs_ocr_pages"]) == (10, 1, 2, 3)
    assert (acme["silent_loss"], acme["regions"], acme["regions_unread"], acme["values"], acme["llm_runs"]) == (17, 10, 3, 160, 1)
    # each stage's median and 90th percentile, over the files' latest runs
    assert acme["stage_seconds"]["parse"] == {"n": 4, "median": 1.5, "p90": 9.0}
    assert acme["stage_seconds"]["map_llm"] == {"n": 1, "median": 30.0, "p90": 30.0}
    assert beta["files_by_state"] == {"read": 1, "partly_read": 0, "unsupported": 0, "unreadable": 0, "failed": 0,
                                      "waiting": 1}
    assert beta["mapping"] == {"cache": 0, "rule": 2, "llm": 0, "unread": 0} and beta["mapping_shares"]["rule"] == 1.0
    # in all: the two companies pooled (a median over every sample, never a median of medians)
    pooled = data["all"]
    assert (pooled["projects"], pooled["files"], pooled["runs"]) == (3, 6, 6)
    assert pooled["files_by_state"] == {"read": 2, "partly_read": 1, "unsupported": 1, "unreadable": 0, "failed": 1,
                                        "waiting": 1}
    assert pooled["mapping"] == {"cache": 3, "rule": 4, "llm": 1, "unread": 3}
    assert pooled["stage_seconds"]["parse"] == {"n": 5, "median": 2.0, "p90": 9.0} and pooled["damaged_logs"] == 0
    # counts only: no file name, no project id anywhere in the answer
    assert not any(name in answer.text for name in ("pk.xlsx", "report.pdf", "broken.pdf", "summary.xlsx", '"p1"', '"p2"'))
    # `since`: the runs queued from that day
    later = client.get("/api/v1/admin/pipeline", headers=_as("owner"), params={"since": "2026-11-11"}).json()["data"]
    assert later["since"] == "2026-11-11T00:00:00+00:00"
    assert [(c["tenant"], c["files"]) for c in later["companies"]] == [("acme", 0), ("beta", 2)]
    assert client.get("/api/v1/admin/pipeline", headers=_as("owner"), params={"since": "yesterday"}).status_code == 422


def test_the_route_needs_admin_and_leaves_an_admin_view_event(client, tmp_path):
    for who in ("ana", "rev"):                      # a curator and a reviewer of a company: not the platform's owner
        refused = client.get("/api/v1/admin/pipeline", headers=_as(who))
        assert refused.status_code == 403 and "modeler-admin" in refused.json()["detail"]
    assert client.get("/api/v1/admin/pipeline").status_code == 401
    assert _views(tmp_path, "platform") == [] and _views(tmp_path, "acme") == []       # a refused look leaves no event
    assert client.get("/api/v1/admin/pipeline", headers=_as("owner")).status_code == 200
    assert client.get("/api/v1/admin/pipeline", headers=_as("owner"), params={"since": "2026-11-11"}).status_code == 200
    views = _views(tmp_path, "platform")                                               # one event per look, on the owner's chain
    assert [(e["actor"], e["resource_type"], e["resource_id"], e["after"]) for e in views] == [
        ("owner", "tenant", "platform", {"page": "pipeline", "since": None}),
        ("owner", "tenant", "platform", {"page": "pipeline", "since": "2026-11-11"})]
    assert FileProjectStore(tmp_path).audit("platform").verify() is None               # and the chain holds
    assert _views(tmp_path, "acme") == [] and _views(tmp_path, "beta") == []           # nothing is written to a company


def test_the_route_has_a_typed_answer():
    (route,) = [r for r in admin_api.router.routes if isinstance(r, APIRoute) and r.path == "/api/v1/admin/pipeline"]
    assert route.methods == {"GET"} and route.response_model.model_fields["data"].annotation is PipelineHealth
