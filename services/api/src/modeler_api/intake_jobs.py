"""The client's files read in the background when they arrive (plan 2026-11-05 §3.1), by the reading agent (A4) when
agents are on, one file after the other in one `reading` job. A service, not a router: the client-data upload, the
project's start and a person's "Read" all go through it.

Every file to read is an item of the project's reading queue (plan 2026-11-10, R1: `modeler_project.reading_queue`);
the `reading` job drains it, one item after the other, and looks again once it is released, so a file that arrives
while another is read waits its turn instead of being dropped. A file that fails is marked failed with why, and the
others are still read. Code reads each data sheet at once, on arrival (`modeler_project.sheet_intake`); the
agent then does what code could not:
- each PDF or Word file, read for its data (I4, build C2);
- the sheets code could not sort, sorted with a header quote, then read by code like the others;
- each sheet whose code reading has a problem, read again by the agent: its reading replaces code's only when its check
  is clean, and is saved at once when nothing is left to ask (`sheet_intake.adopt_agent_reading`).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException

from modeler_api import agent_jobs, jobs
from modeler_intake.grid import read_workbook_bytes
from modeler_project import ArtifactKind, ProjectStore, Workspace
from modeler_project.brief import ProjectBrief
from modeler_project.client_data import READABLE_DOCUMENTS, ClientDataError, record_reading, set_triage, submission
from modeler_project.documents import DocumentLibrary
from modeler_project.reading_queue import QueueItem, ReadingQueue
from modeler_project.sheet_intake import (
    READ,
    adopt_agent_reading,
    agent_could_not,
    has_problem,
    products_of,
    read_on_arrival,
)

log = logging.getLogger(__name__)
# the sheets a person's "Read" reads when none is named: the data sheets no saved reading has read yet
READABLE = ("PK_INDIVIDUAL", "PK_SUMMARY", "DISSOLUTION")
BUSY = "a reading run is already in progress"


def run_document_job(store: ProjectStore, tenant_id: str, project_id: str, sid: str, *, model,
                     max_turns: int = 30) -> dict[str, Any]:
    """A4 reads one client PDF or Word file for project data (plan 2026-11-03 §3.4, I4): study facts, profiles, NCA
    tables, dissolution profiles and links between two names of a study, each quoted and checked by code. What code
    accepted is recorded on the file and waits on Inputs, in its study or product, until a person confirms it."""
    ws = Workspace(store, tenant_id, project_id)
    if submission(ws, sid) is None:
        raise ClientDataError(f"no client file {sid}")
    version = ws.latest(ArtifactKind.BRIEF, "main")
    brief = ProjectBrief.from_content(version.content) if version else None
    run = agent_jobs.AgentRun(store.root, tenant_id=tenant_id, project_id=project_id,  # type: ignore[attr-defined]
                              agent="A4-document-reading", model=model, max_turns=max_turns)
    ctx, outcome = agent_jobs.document_reading(model, ws=ws, library=DocumentLibrary(ws), sid=sid,
                                               drug=brief.drug_name if brief else "", actor=run.actor, run_id=run.run_id,
                                               max_turns=max_turns, log_step=run.log_step)
    summary = {"datasets": len(ctx.datasets), "facts": len(ctx.facts), "dissolution_rows": len(ctx.dissolution),
               "links": len(ctx.links), "refused": len(ctx.refused), "summary": outcome.final_text[:2000],
               "error": outcome.error}
    run.finish(outcome, summary)
    return {"run_id": run.run_id, "status": outcome.status, **summary}


def undecided_sheets(content: dict[str, Any]) -> list[str]:
    """The sheets code could not sort (left "other" by code), for the agent to sort."""
    return [t["sheet"] for t in content.get("triage", []) if t["category"] == "OTHER" and t.get("by") == "code"]


def problem_sheets(content: dict[str, Any]) -> list[str]:
    """The data sheets code read on arrival whose reading has a problem, not saved yet, the agent not tried yet."""
    read = {t.get("sheet") for m in content.get("mappings", []) if not m.get("replaced_by") for t in m["recipe"].get("tables", [])}
    return [sheet for sheet, d in (content.get("readings") or {}).items()
            if d.get("by") == "code" and sheet not in read and not d.get("agent_tried") and has_problem(d)]


def _needs_agent(content: dict[str, Any]) -> bool:
    if content.get("repeat"):
        return False
    if content.get("kind") in READABLE_DOCUMENTS:
        return not content.get("document_reads")
    return not content.get("template") and bool(undecided_sheets(content) or problem_sheets(content))


def run_arrival_job(store: ProjectStore, tenant_id: str, project_id: str, sid: str, *, model) -> dict[str, Any]:
    """What the agent does for one file that has arrived: a document read for its data; a workbook's sheets sorted where
    code could not, then each sheet whose code reading has a problem read again. Each run is logged like any agent run."""
    ws = Workspace(store, tenant_id, project_id)
    content = submission(ws, sid)
    if content is None:
        raise ClientDataError(f"no client file {sid}")
    if content.get("kind") in READABLE_DOCUMENTS:
        return run_document_job(store, tenant_id, project_id, sid, model=model)
    path = ws.store.blob_path(tenant_id, project_id, content["sha256"])
    if content.get("template") or path is None:
        return {"status": "COMPLETED", "sorted": 0, "read": []}
    workbook = read_workbook_bytes(path.read_bytes(), content["file"])
    version = ws.latest(ArtifactKind.BRIEF, "main")
    brief = ProjectBrief.from_content(version.content) if version else None
    drug, products, library = brief.drug_name if brief else "", products_of(brief), DocumentLibrary(ws)
    out: dict[str, Any] = {"status": "COMPLETED", "sorted": 0, "read": []}
    if undecided := undecided_sheets(content):
        run = agent_jobs.AgentRun(store.root, tenant_id=tenant_id, project_id=project_id,  # type: ignore[attr-defined]
                                  agent="A4-sheet-triage", model=model, max_turns=6)
        ctx, outcome = agent_jobs.sheet_triage(model, workbook=workbook, sheets=undecided, actor=run.actor, max_turns=6,
                                               log_step=run.log_step)
        for triaged in ctx.accepted:
            set_triage(ws, sid, triaged, by=ctx.actor, reason=triaged.note or "A4, header quoted")
        run.finish(outcome, {"classified": len(ctx.accepted), "rejected": len(ctx.rejected), "error": outcome.error})
        out["sorted"] = len(ctx.accepted)
        if data := [t.sheet for t in ctx.accepted if t.category.value in READ]:    # read by code, as on arrival
            read_on_arrival(ws, library, sid, workbook, by=run.actor, drug=drug, products=products, sheets=data)
    content = submission(ws, sid) or content
    categories = {t["sheet"]: t["category"] for t in content.get("triage", [])}
    for sheet in problem_sheets(content):
        run = agent_jobs.AgentRun(store.root, tenant_id=tenant_id, project_id=project_id,  # type: ignore[attr-defined]
                                  agent="A4-sheet-reading", model=model, max_turns=8)
        reading = agent_jobs.sheet_reading(model, workbook=workbook, sheet=sheet, drug=drug, actor=run.actor,
                                           category=categories.get(sheet, ""), products=products, max_turns=8,
                                           log_step=run.log_step)
        if reading.form is not None:
            result = adopt_agent_reading(ws, library, sid, workbook, sheet, reading.form, reading.notes, by=run.actor,
                                         run_id=run.run_id)
        else:                             # no reading code accepted: code's draft stays, marked as tried
            agent_could_not(ws, sid, sheet, content["readings"][sheet], by=run.actor, run_id=run.run_id,
                            why="it proposed no reading code accepts")
            result = {"adopted": False, "saved": []}
        run.finish(reading.outcome, {"sheet": sheet, **result, "refused": len(reading.rejected), "error": reading.outcome.error})
        out["read"].append({"sheet": sheet, "run_id": run.run_id, **result})
    return out


def unread_sheets(content: dict[str, Any]) -> list[str]:
    """The file's data sheets that no confirmed reading has read yet."""
    read = {t.get("sheet") for m in content.get("mappings", []) if not m.get("replaced_by") for t in m["recipe"].get("tables", [])}
    return [t["sheet"] for t in content.get("triage", []) if t["category"] in READABLE and t["sheet"] not in read]


def run_reading_job(store: ProjectStore, tenant_id: str, project_id: str, sid: str, *, model, sheets: list[str] | None = None,
                    max_turns: int = 8) -> dict[str, Any]:
    """A4 proposes how to read each data sheet not read yet (or the sheets named), one agent run per sheet. A reading
    code accepted is kept on the file for the person to check, correct and save; nothing is read into the project here."""
    ws = Workspace(store, tenant_id, project_id)
    content = submission(ws, sid)
    if content is None:
        raise ClientDataError(f"no client file {sid}")
    library = DocumentLibrary(ws)
    if (withdrawn := library.entry(content["sha256"]).withdrawn) is not None:
        raise ClientDataError(f"{content['file']} was withdrawn ({withdrawn.reason})")
    path = store.blob_path(tenant_id, project_id, content["sha256"])
    if path is None:
        raise ClientDataError("the file's bytes are not in the store")
    workbook = read_workbook_bytes(path.read_bytes(), content["file"])
    version = ws.latest(ArtifactKind.BRIEF, "main")
    brief = ProjectBrief.from_content(version.content) if version else None
    products = products_of(brief)
    categories = {t["sheet"]: t["category"] for t in content.get("triage", [])}
    results = []
    for sheet in [s for s in (sheets or unread_sheets(content)) if s in workbook.sheets]:
        run = agent_jobs.AgentRun(store.root, tenant_id=tenant_id, project_id=project_id,  # type: ignore[attr-defined]
                                  agent="A4-sheet-reading", model=model, max_turns=max_turns)
        reading = agent_jobs.sheet_reading(model, workbook=workbook, sheet=sheet, drug=brief.drug_name if brief else "",
                                           actor=run.actor, category=categories.get(sheet, ""), products=products,
                                           max_turns=max_turns, log_step=run.log_step)
        if reading.form is not None:
            record_reading(ws, sid, sheet=sheet, form=reading.form.model_dump(mode="json"), notes=reading.notes, by=run.actor,
                           run_id=run.run_id)
        summary = {"sheet": sheet, "proposed": reading.form is not None, "refused": len(reading.rejected),
                   "summary": reading.outcome.final_text[:2000], "error": reading.outcome.error}
        run.finish(reading.outcome, summary)
        results.append({"run_id": run.run_id, "status": reading.outcome.status, **summary})
    return {"status": "COMPLETED", "sheets": results}


class NotReadable(ClientDataError):
    """A queued file the agent cannot read: gone, withdrawn, or a document with no text."""


def _readable(ws: Workspace, sid: str) -> dict[str, Any]:
    """The file's record, when the agent can read it (the guards of a person's "Read", for every queued file)."""
    content = submission(ws, sid)
    if content is None:
        raise NotReadable(f"no client file {sid}")
    library = DocumentLibrary(ws)
    if (withdrawn := library.entry(content["sha256"]).withdrawn) is not None:
        raise NotReadable(f"withdrawn ({withdrawn.reason}); restore it in the Project Document Library to read it")
    if content.get("kind") in READABLE_DOCUMENTS and not any(page.strip() for page in library.pages(content["sha256"])):
        raise NotReadable("no text to read (a scan needs OCR)")
    return content


def _run_item(store: ProjectStore, tenant_id: str, project_id: str, item: QueueItem, model) -> dict[str, Any]:
    content = _readable(Workspace(store, tenant_id, project_id), item.sid)
    if item.task == "arrival":
        return run_arrival_job(store, tenant_id, project_id, item.sid, model=model)
    if content.get("kind") in READABLE_DOCUMENTS:
        return run_document_job(store, tenant_id, project_id, item.sid, model=model)
    return run_reading_job(store, tenant_id, project_id, item.sid, model=model, sheets=list(item.sheets) or None)


def _outcome(result: dict[str, Any]) -> tuple[bool, str, tuple[str, ...], dict[str, int]]:
    """(failed, note, run ids, counts) of one item's result, whatever kind of reading it was."""
    parts = [result, *result.get("read", []), *result.get("sheets", [])]
    run_ids = tuple(str(p["run_id"]) for p in parts if p.get("run_id"))
    errors = [str(p["error"]) for p in parts if p.get("error")]
    found = {k: int(result[k]) for k in ("datasets", "facts", "dissolution_rows", "links", "refused", "sorted")
             if isinstance(result.get(k), int)}
    if result.get("sheets"):
        found["sheets_proposed"] = sum(1 for p in result["sheets"] if p.get("proposed"))
    if result.get("read"):
        found["sheets_adopted"] = sum(1 for p in result["read"] if p.get("adopted"))
    failed = bool(errors) or str(result.get("status", "COMPLETED")) not in ("COMPLETED", "")
    return failed, "; ".join(errors) or str(result.get("summary") or ""), run_ids, found


def drain(store: ProjectStore, tenant_id: str, project_id: str, model) -> None:
    """The reading job: every waiting item, one after the other, until none is left. One that fails is marked failed
    and the next is read."""
    queue = ReadingQueue(Workspace(store, tenant_id, project_id))
    queue.recover()
    while (item := queue.take()) is not None:
        try:
            failed, note, run_ids, found = _outcome(_run_item(store, tenant_id, project_id, item, model) or {})
        except NotReadable as exc:
            queue.finish(item.id, "failed", note=str(exc))
            continue
        except Exception as exc:     # one file's failure never stops the others
            log.exception("reading %s (%s) failed", item.file, item.sid)
            queue.finish(item.id, "failed", note=f"{type(exc).__name__}: {exc}")
            continue
        queue.finish(item.id, "failed" if failed else "done", note=note, run_ids=run_ids, found=found)


def kick(store: ProjectStore, tenant_id: str, project_id: str) -> bool:
    """Start the reading job when something waits and agents are on; True when it started. While a reading runs this
    does nothing: the running job takes what was queued, and looks again once it is released."""
    model, _problem = agent_jobs.chat_model()
    if model is None:
        return False
    if not ReadingQueue(Workspace(store, tenant_id, project_id)).pending():
        return False
    try:
        jobs.start(store, tenant_id, project_id, "reading", lambda: drain(store, tenant_id, project_id, model), busy=BUSY,
                   name=f"reading-{project_id}", after=lambda: _kick_quietly(store, tenant_id, project_id))
    except HTTPException:
        return False
    return True


def _kick_quietly(store: ProjectStore, tenant_id: str, project_id: str) -> None:
    try:
        kick(store, tenant_id, project_id)
    except Exception:
        log.exception("could not look again at the reading queue of %s", project_id)


def queue_reading(store: ProjectStore, tenant_id: str, project_id: str, sid: str, *, by: str,
                  sheets: tuple[str, ...] = ()) -> str:
    """A person's "Read" for one file: queued, and the reading job started if none runs. "RUNNING" when this started
    the job, "QUEUED" when it waits behind another reading."""
    ws = Workspace(store, tenant_id, project_id)
    queue = ReadingQueue(ws)
    content = submission(ws, sid) or {}
    if not queue.available:   # a store without a queue: read at once, as before the queue
        model, _problem = agent_jobs.chat_model()
        jobs.start(store, tenant_id, project_id, "reading",
                   lambda: _run_item(store, tenant_id, project_id, QueueItem(
                       id="q-0", sid=sid, file=str(content.get("file", sid)), task="read", sheets=sheets, added_by=by,
                       added_at=""), model), busy=BUSY, name=f"reading-{project_id}")
        return "RUNNING"
    queue.add([(sid, str(content.get("file", sid)))], task="read", by=by, sheets=sheets)
    return "RUNNING" if kick(store, tenant_id, project_id) else "QUEUED"


def read_later(store: ProjectStore, tenant_id: str, project_id: str, sids: list[str], *, by: str = "code") -> bool:
    """The agent's part for the files that have just arrived (`run_arrival_job`): each file that needs the agent is
    queued, whether a reading runs or not (and whether or not it was uploaded before, so long as it is not read yet),
    and the reading job started if none runs. True when this started it. With agents off the files wait in the queue,
    and are read once agents are on (each file also keeps its buttons: "Read the data in this file", "Sort the
    sheets", "Read this sheet")."""
    ws = Workspace(store, tenant_id, project_id)
    queue = ReadingQueue(ws)
    todo = [(sid, str(content["file"])) for sid in dict.fromkeys(sids)
            if (content := submission(ws, sid)) is not None and _needs_agent(content)]
    if not queue.available:   # a store without a queue: as before it, read now or not at all
        model, _problem = agent_jobs.chat_model()
        if model is None or not todo:
            return False

        def job() -> None:
            for sid, _name in todo:
                run_arrival_job(store, tenant_id, project_id, sid, model=model)

        try:
            jobs.start(store, tenant_id, project_id, "reading", job, busy=BUSY, name=f"arrival-{project_id}")
        except HTTPException:
            return False
        return True
    if todo:
        queue.add(todo, task="arrival", by=by)
    return kick(store, tenant_id, project_id)
