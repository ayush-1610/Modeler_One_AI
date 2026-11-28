"""The Data room's runs in the background: started, paused and resumed (plan 2026-11-24 §4).

A run is the project's `dataroom` job (`jobs.start`: one at a time per project, across every API worker), on a thread of
the worker that started it, as every agent job is. A run that pauses for a reason that passes writes when it resumes by
itself (`pause.resume_at`) in its own record, beside the data; no state is kept in a process (C8):
- the worker that ran it sets a timer for that moment (a daemon `threading.Timer`, the same kind of thread as a job);
- every API process, when it starts, sets one for each paused run of the store (`pick_up`), so a restart loses none; a
  run already due resumes at once;
- a timer resumes the run only if it is still paused and due, read again under the project's job lease, so two workers'
  timers (or a timer and a person) never resume it twice; a timer whose moment has moved on does nothing.
An administrator's change of a model, a key or the paid cap resumes at once the paused runs it may unblock
(`resume_paused`), and a person may resume one now (`POST …/dataroom/run:resume`).
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Collection
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import HTTPException

from modeler_api import agent_jobs, jobs
from modeler_project import ProjectStore, Workspace
from modeler_project.dataroom import DataRoomStore

BUSY = "the Data room is already running for this project"
REASONS = ("provider_unavailable", "budget_cap", "no_model")
CLOCK = "system:dataroom-resume"          # who resumes a run when its rest is over (the audit trail's actor)
SLACK_S = 1.0                             # a timer fires this long after the run is due, so it reads as due

_log = logging.getLogger(__name__)


def _room(store: ProjectStore, tenant_id: str, project_id: str) -> DataRoomStore:
    return DataRoomStore(Workspace(store, tenant_id, project_id))


def _after(store: ProjectStore, tenant_id: str, project_id: str, doc: dict[str, Any]) -> None:
    """A run that ended paused, with a time to resume by itself, gets its timer."""
    if doc.get("state") == "paused":
        schedule(store, tenant_id, project_id, (doc.get("pause") or {}).get("resume_at"))


def begin(store: ProjectStore, room: DataRoomStore, *, by: str, stages: list[str] | None = None,
          redo: list[str] | None = None, files: list[str] | None = None) -> None:
    """Start a run of `room` now: its first record written at once (each wanted stage waiting, the others skipped), so a
    page reads it as running, the start audited, then the job. The Data room's Run (`POST …/dataroom/run`) and a project
    started with its client's files (`projects:initiate`, plan 2026-11-27 step 1, D1) start a run this one way."""
    stages_all = agent_jobs.dataroom_stages()
    wanted = stages if stages is not None else [sid for sid, _label, _agent in stages_all]
    room.set_run({"state": "running", "started_at": None, "finished_at": None, "error": "", "agents": {},
                  "stages": [{"id": sid, "label": label, "agent": agent, "state": "waiting" if sid in wanted else "skipped",
                              "done": 0, "total": 0, "note": ""} for sid, label, agent in stages_all]})
    room.audit(actor=by, action="dataroom.run", resource_id="run",
               after={"stages": list(wanted), "redo": list(redo or ()), "files": list(files or ())})
    start(store, room.ws.tenant_id, room.ws.project_id, by=by, stages=list(wanted), redo=list(redo or ()),
          files=list(files or ()))


def start(store: ProjectStore, tenant_id: str, project_id: str, *, by: str, stages: list[str] | None,
          redo: list[str], files: list[str]) -> None:
    """Run the project's Data room in the background, started by `by`; 409 while one runs."""

    def job() -> None:
        doc = agent_jobs.dataroom_run(_room(store, tenant_id, project_id), actor=by, stages=stages, redo=redo, files=files)
        _after(store, tenant_id, project_id, doc)

    jobs.start(store, tenant_id, project_id, "dataroom", job, busy=BUSY, by=by, name=f"dataroom-{project_id}")


def resumable(doc: dict[str, Any], how: Literal["auto", "now"], reasons: Collection[str] = REASONS,
              now: datetime | None = None) -> bool:
    """Whether a run's record is a paused run to resume: paused for one of `reasons`, and, by the clock, due."""
    pause = doc.get("pause") or {}
    if doc.get("state") != "paused" or pause.get("reason") not in reasons:
        return False
    if how == "now":
        return True
    due = pause.get("resume_at")
    return bool(due) and datetime.fromisoformat(due) <= (now or datetime.now(UTC))


def resume(store: ProjectStore, tenant_id: str, project_id: str, *, by: str, how: Literal["auto", "now"],
           reasons: Collection[str] = REASONS) -> bool:
    """Resume the project's paused run in the background, where it stopped. False, and nothing started, when it is not
    paused (for one of `reasons`), not due yet (by the clock), or a run of the project is running."""
    if not resumable(_room(store, tenant_id, project_id).run(), how, reasons):
        return False

    def job() -> None:
        room = _room(store, tenant_id, project_id)
        if not resumable(room.run(), how, reasons):     # read again under the lease: another resumed it meanwhile
            return
        _after(store, tenant_id, project_id, agent_jobs.dataroom_run(room, actor=by, resume=how))

    try:
        jobs.start(store, tenant_id, project_id, "dataroom", job, busy=BUSY, by=by,
                   name=f"dataroom-resume-{project_id}")
    except HTTPException:            # a run of the project holds the lease: it is not paused for long
        return False
    return True


def _fire(store: ProjectStore, tenant_id: str, project_id: str) -> None:
    try:
        resume(store, tenant_id, project_id, by=CLOCK, how="auto")
    except Exception:  # noqa: BLE001 - a timer's thread has no caller: the reason goes to the server's log
        _log.exception("the Data room run of %s/%s could not be resumed", tenant_id, project_id)


def schedule(store: ProjectStore, tenant_id: str, project_id: str, resume_at: str | None) -> None:
    """A timer for the moment a paused run resumes by itself (none when it does not)."""
    if not resume_at:
        return
    delay = max(0.0, (datetime.fromisoformat(resume_at) - datetime.now(UTC)).total_seconds()) + SLACK_S
    timer = threading.Timer(delay, _fire, args=(store, tenant_id, project_id))
    timer.daemon = True
    timer.name = f"dataroom-timer-{project_id}"
    timer.start()


def paused_runs(store: ProjectStore) -> list[tuple[str, str, dict[str, Any]]]:
    """Every paused Data room run of the store: (company, project, its record)."""
    root = getattr(store, "root", None)
    if root is None or not Path(root).is_dir():
        return []
    out = []
    for path in sorted(Path(root).glob("*/projects/*/dataroom/run.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if doc.get("state") == "paused":
            out.append((path.parts[-5], path.parts[-3], doc))
    return out


def pick_up(store: ProjectStore) -> int:
    """At the API's start: a timer for every paused run that resumes by itself (one already due resumes at once).
    The number of timers set."""
    found = [(t, p, at) for t, p, doc in paused_runs(store) if (at := (doc.get("pause") or {}).get("resume_at"))]
    for tenant_id, project_id, at in found:
        schedule(store, tenant_id, project_id, at)
    return len(found)


def resume_paused(store: ProjectStore, *, by: str, reasons: Collection[str]) -> int:
    """Resume at once every paused run paused for one of `reasons` (the administrator changed what stopped it: a model,
    a key, the paid cap). The number resumed. A run the change did not unblock pauses again before its next model call."""
    return sum(resume(store, t, p, by=by, how="now", reasons=reasons) for t, p, _doc in paused_runs(store))
