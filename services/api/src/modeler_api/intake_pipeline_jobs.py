"""The intake pipeline's hook on every arrival route and its background job (contracts §2, §6.5; build W; plan G7).

A service, not a router (the precedent is `intake_jobs`). What runs is the switch `Settings.intake_pipeline`
(MODELER_INTAKE_PIPELINE):
- `legacy`: today's readers only. `receive` is `[ingest(...)]`, exceptions unchanged, and nothing is written under
  `intake/`; `kick` starts nothing.
- `both` (the default): today's readers, and the new pipeline beside them. `receive` stores and records the bytes
  first (`intake_files.record_arrival`), then calls today's `ingest` exactly as the route did (its answer returned
  unchanged, its exceptions propagated unchanged after the refusal is noted), then queues one pipeline run per file. A
  ZIP is recorded, expanded (`zip_members`) and each member goes through the same steps with its container; the answer
  is one entry per accepted member (`file` shown as `<zip>/<member>`), and `MemberRefusals` names the members today's
  reader refused, with the accepted entries. The project's `intake` job (`kick`, `drain`; its own lease, beside the
  `reading` job) reads the runs with or without a model.

Every arrival route passes in its own `ingest` (so a test's monkeypatch of the route module still applies) and opens one
delivery per request (`open_delivery`). A failure of the new pipeline is caught and logged here or in its job, and never
reaches a legacy answer: the pipeline's writes in the request are guarded; parsing happens in the job, never in the
request.

The two LLM stages reach the model only through `ports` (built over `agent_jobs`, the API's one seam to the agents),
read once per run from the console's A4 setting: each table conversation is an agent run named `A4-table-mapper`, up
to 4 at a time; the prose is one run named `A4-prose`. A cache or rule mapping makes no agent run.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import PurePosixPath
from typing import Any

from fastapi import HTTPException

from modeler_api import agent_jobs, jobs
from modeler_api.config import get_settings
from modeler_intake.mapping_spec import MappingSpec, ProseCheck, ProseFact, ProseParagraph
from modeler_intake.source import zip_members
from modeler_intake.source.archive import is_zip_name
from modeler_intake.source_model import ContainerRef, Finding
from modeler_project import ArtifactKind, ProjectStore, Workspace, intake_files, intake_pipeline
from modeler_project.brief import ProjectBrief
from modeler_project.intake_pipeline import PROSE_FIELDS, LlmFailure, LlmPorts, MapAnswer, MapRequest
from modeler_project.intake_records import FileRecord
from modeler_project.intake_store import IntakeStore
from modeler_project.ledger_models import ModelUse
from modeler_project.requirements import RequirementMatrix

log = logging.getLogger(__name__)

BUSY = "the intake pipeline is already running for this project"
TABLE_WORKERS = 4                   # table conversations at once (G7)
TABLE_TURNS = 4                     # the table mapper's turns per table (`table_mapper.map_table`'s default)
PROSE_TURNS = 8                     # the prose extractor's turns per file (`prose_extractor.extract_prose`'s default)


class MemberRefusals(ValueError):
    """A ZIP some of whose members today's reader refused: the entries of the members it accepted, and each refused
    member as "<zip>/<member>: <reason>" (`problems`: the same as (path, reason) pairs)."""

    def __init__(self, accepted: list[dict[str, Any]], problems: list[tuple[str, str]]):
        self.accepted = accepted
        self.problems = problems
        self.refused = [f"{path}: {reason}" for path, reason in problems]
        super().__init__("; ".join(self.refused))


# --- the switch ----------------------------------------------------------------------------------------------------


def enabled() -> bool:
    """Whether the new pipeline runs beside today's readers (`intake_pipeline == "both"`)."""
    return get_settings().intake_pipeline == "both"


def _on(ws: Workspace) -> bool:
    return enabled() and IntakeStore(ws).available


def open_delivery(ws: Workspace, *, by: str) -> str:
    """One delivery per arrival request, in `both`; "" when the pipeline is off (nothing is written) or the delivery
    could not be recorded (logged: the request goes on as today)."""
    if not _on(ws):
        return ""
    try:
        return intake_files.open_delivery(ws, by=by)
    except Exception:
        log.exception("could not open a delivery in %s/%s", ws.tenant_id, ws.project_id)
        return ""


# --- an arrival ----------------------------------------------------------------------------------------------------


def _guarded(what: str, work: Callable[[], Any]) -> Any:
    """Run a write of the new pipeline inside a request: a failure is logged and never changes the legacy answer."""
    try:
        return work()
    except Exception:
        log.exception("intake pipeline: %s failed (the request goes on as today)", what)
        return None


def receive(ws: Workspace, library: Any, data: bytes, filename: str, *, by: str, delivery: str,
            ingest: Callable[..., dict[str, Any]], **ingest_kwargs: Any) -> list[dict[str, Any]]:
    """Today's `ingest` of one arriving file, with the new pipeline's record around it in `both` (the module
    docstring): one ingest answer per file or accepted member. In `legacy` this is `[ingest(...)]`, exceptions
    unchanged."""
    if not _on(ws):
        return [ingest(ws, library, data, filename, by=by, **ingest_kwargs)]
    if not delivery:
        delivery = open_delivery(ws, by=by)
    if is_zip_name(filename):
        return _receive_zip(ws, library, data, filename, by=by, delivery=delivery, ingest=ingest, **ingest_kwargs)
    record = _record(ws, data, filename, delivery=delivery, by=by)
    try:
        answer = ingest(ws, library, data, filename, by=by, **ingest_kwargs)
    except Exception as exc:
        _note(ws, record, sid=None, refusal=str(exc) or type(exc).__name__)
        _enqueue(ws, [record], by=by)
        raise
    _note(ws, record, sid=_sid(answer), refusal=None)
    _enqueue(ws, [record], by=by)
    return [answer]


def _record(ws: Workspace, data: bytes, filename: str, *, delivery: str, by: str,
            container: ContainerRef | None = None) -> FileRecord | None:
    if not delivery:
        return None
    return _guarded(f"recording {filename}", lambda: intake_files.record_arrival(ws, data, filename, delivery=delivery,
                                                                                 by=by, container=container))


def _note(ws: Workspace, record: FileRecord | None, *, sid: str | None, refusal: str | None) -> None:
    if record is not None:
        _guarded(f"noting what today's reader did with {record.name}",
                 lambda: intake_files.note_legacy(ws, record.file_id, sid=sid, refusal=refusal))


def _enqueue(ws: Workspace, records: Sequence[FileRecord | None], *, by: str) -> None:
    kept = [r for r in records if r is not None]
    if kept:
        _guarded("queuing a run", lambda: intake_pipeline.enqueue(ws, kept, by=by))


def _sid(answer: Any) -> str | None:
    return str(answer["id"]) if isinstance(answer, dict) and answer.get("id") else None


def _receive_zip(ws: Workspace, library: Any, data: bytes, filename: str, *, by: str, delivery: str,
                 ingest: Callable[..., dict[str, Any]], **ingest_kwargs: Any) -> list[dict[str, Any]]:
    """A ZIP: recorded, expanded, each member recorded (with its container), read by today's reader and queued."""
    archive = _record(ws, data, filename, delivery=delivery, by=by)
    try:
        members = zip_members(data, filename)
    except ValueError as exc:
        reason = str(exc).removeprefix(f"{filename}: ")
        _note(ws, archive, sid=None, refusal=reason)
        _enqueue(ws, [archive], by=by)
        raise ValueError(reason) from exc
    if not members:
        _note(ws, archive, sid=None, refusal="the archive holds no file")
        _enqueue(ws, [archive], by=by)
        raise ValueError("the archive holds no file")
    container_sha = archive.sha256 if archive is not None else ""
    records: list[FileRecord | None] = [archive]
    accepted: list[dict[str, Any]] = []
    problems: list[tuple[str, str]] = []
    for member, payload in members:
        name = PurePosixPath(member).name or member
        shown = f"{filename}/{member}"
        record = _record(ws, payload, name, delivery=delivery, by=by,
                         container=ContainerRef(sha256=container_sha, name=filename, member=member) if container_sha else None)
        records.append(record)
        try:
            answer = ingest(ws, library, payload, name, by=by, **ingest_kwargs)
        except ValueError as exc:
            _note(ws, record, sid=None, refusal=str(exc) or type(exc).__name__)
            problems.append((shown, str(exc)))
            continue
        _note(ws, record, sid=_sid(answer), refusal=None)
        accepted.append({**answer, "file": shown})
    _enqueue(ws, records, by=by)
    if problems:
        raise MemberRefusals(accepted, problems)
    return accepted


# --- the job ---------------------------------------------------------------------------------------------------------


def sweep(store: ProjectStore, tenant_id: str, project_id: str, *, by: str = "code") -> int:
    """In `both`: the client files stored before the pipeline ran, recorded and queued (`intake_pipeline.sweep`); how
    many runs it queued. Never raises (logged)."""
    ws = Workspace(store, tenant_id, project_id)
    if not _on(ws):
        return 0
    return _guarded("the sweep of stored files", lambda: intake_pipeline.sweep(ws, by=by)) or 0


def kick(store: ProjectStore, tenant_id: str, project_id: str, *, by: str = "code") -> bool:
    """Start the project's `intake` job when a run waits, or was left running by a job that stopped (a restart), with
    or without a model; True when it started (`by`: who set it going). While it runs this does nothing: the job takes
    what was queued, and looks again once it is released. Never raises: a failure is logged and the caller's answer
    is unchanged."""
    try:
        ws = Workspace(store, tenant_id, project_id)
        if not _on(ws) or not intake_pipeline.unfinished(ws):
            return False
        ended: list[bool] = []
        jobs.start(store, tenant_id, project_id, "intake",
                   lambda held: ended.append(_drain(store, tenant_id, project_id, held)),
                   busy=BUSY, by=by, name=f"intake-{project_id}",
                   after=lambda: _look_again(store, tenant_id, project_id, by=by, emptied=ended == [True]), checked=True)
    except HTTPException:
        return False
    except Exception:
        log.exception("could not start the intake pipeline of %s", project_id)
        return False
    return True


def _look_again(store: ProjectStore, tenant_id: str, project_id: str, *, by: str, emptied: bool) -> None:
    """Once the job is released: start it again for a run queued while it was finishing. Only after a job that emptied
    the queue (one that could not read or write the runs log would start again at once, for ever), and only for a run
    that waits (one left running is recovered at the next arrival, or the next open of the Delivery page)."""
    try:
        if emptied and enabled() and intake_pipeline.pending(Workspace(store, tenant_id, project_id)):
            kick(store, tenant_id, project_id, by=by)
    except Exception:
        log.exception("could not look again at the intake queue of %s", project_id)


def _context(ws: Workspace) -> tuple[ProjectBrief | None, RequirementMatrix | None]:
    brief_version = ws.latest(ArtifactKind.BRIEF, "main")
    matrix_version = ws.latest(ArtifactKind.REQUIREMENTS, "main")
    return (ProjectBrief.from_content(brief_version.content) if brief_version else None,
            RequirementMatrix.from_content(matrix_version.content) if matrix_version else None)


def drain(store: ProjectStore, tenant_id: str, project_id: str, held: Callable[[], bool] | None = None) -> None:
    """The intake job: the runs left `running` recovered, then every queued run read (`run_file`), one after the
    other, until none is left. The model is read once per run (`ports`). `held`: whether this job still holds its
    lease; once it does not (it went stale and another worker took over), it takes no more runs."""
    _drain(store, tenant_id, project_id, held)


def _drain(store: ProjectStore, tenant_id: str, project_id: str, held: Callable[[], bool] | None) -> bool:
    """`drain`; True when it ended because no run was left to take (False: the runs log could not be read or written,
    or the lease was lost)."""
    ws = Workspace(store, tenant_id, project_id)
    _guarded("recovering runs", lambda: intake_pipeline.recover(ws))
    while held is None or held():
        try:
            run = intake_pipeline.take(ws)
        except Exception:
            log.exception("intake pipeline: taking a run failed in %s", project_id)
            return False
        if run is None:
            return True
        jobs.started_by.set(run.by)        # each agent run records who sent the file (the admin console's usage)
        llm = _guarded("reading the model's setting", lambda: ports(store, tenant_id, project_id))
        context = _guarded("reading the brief and the data plan", lambda: _context(ws)) or (None, None)
        try:
            intake_pipeline.run_file(ws, run, llm=llm, brief=context[0], matrix=context[1])
        except Exception:      # run_file never raises; one file's failure never stops the others
            log.exception("intake run %s failed", run.run_id)
    return False


# --- the two LLM stages, through the agents seam ------------------------------------------------------------------


class _Ended:
    """What `AgentRun.finish` reads of an agent's result (its status and usage, zeros where the loop gave none); with
    no result (the agent raised), the run ends FAILED."""

    def __init__(self, result: Any = None):
        usage = dict(getattr(result, "usage", None) or {})
        self.status = str(getattr(result, "status", "FAILED"))
        self.usage = {**usage, "input_tokens": int(usage.get("input_tokens", 0)),
                      "output_tokens": int(usage.get("output_tokens", 0))}


def _failed(run: Any, exc: BaseException) -> None:
    """Close the record of an agent run whose agent raised (a run is started once and finished once), quietly."""
    try:
        run.finish(_Ended(), {"error": f"{type(exc).__name__}: {exc}"[:500]})
    except Exception:
        log.exception("could not close agent run %s", getattr(run, "run_id", "?"))


def _locked(lock: threading.Lock, log_step: Callable[[dict[str, Any]], None]) -> Callable[[dict[str, Any]], None]:
    def step(item: dict[str, Any]) -> None:
        with lock:
            log_step(item)
    return step


def ports(store: ProjectStore, tenant_id: str, project_id: str) -> LlmPorts | None:
    """The two LLM stages over the console's A4 model; None when no model is configured (agents off, or a setting
    that does not work: the LLM stages are then skipped and say so)."""
    model, _problem = agent_jobs.chat_model("A4")
    if model is None:
        return None
    root = store.root
    lock = threading.Lock()

    def map_tables(requests: Sequence[MapRequest],
                   check: Callable[[str, MappingSpec], tuple[Finding, ...]]) -> list[MapAnswer]:
        who = jobs.started_by.get()

        def one(request: MapRequest) -> MapAnswer:
            jobs.started_by.set(who)
            run = None
            try:
                run = agent_jobs.AgentRun(root, tenant_id=tenant_id, project_id=project_id, agent="A4-table-mapper",
                                          model=model, max_turns=TABLE_TURNS)
                result = agent_jobs.table_mapping(model, table=request.table,
                                                  check=lambda spec: check(request.region_id, spec),
                                                  max_turns=TABLE_TURNS, log_step=_locked(lock, run.log_step))
                run.finish(_Ended(result), {"region": request.region_id, "mapped": result.spec is not None,
                                            "rejected": len(result.rejected)})
                detail = f"{model.provider}/{model.model} prompt {result.prompt_sha256} run {run.run_id}"
                error = "" if result.spec is not None else (
                    f"{result.status}, {len(result.rejected)} proposals rejected" if result.rejected else result.status)
                return MapAnswer(region_id=request.region_id, spec=result.spec, origin_detail=detail,
                                 agent_run=run.run_id, error=error)
            except Exception as exc:      # one table's failure is its own answer: the other conversations go on
                log.exception("the table mapper failed on region %s", request.region_id)
                if run is not None:
                    _failed(run, exc)
                return MapAnswer(region_id=request.region_id, spec=None, origin_detail="",
                                 agent_run=run.run_id if run is not None else None, error=f"{type(exc).__name__}: {exc}")

        if not requests:
            return []
        with ThreadPoolExecutor(max_workers=min(TABLE_WORKERS, len(requests)), thread_name_prefix="a4-table") as pool:
            return list(pool.map(one, requests))

    def extract_prose(paragraphs: Sequence[ProseParagraph], check: ProseCheck) -> tuple[Sequence[ProseFact], ModelUse | None]:
        run = agent_jobs.AgentRun(root, tenant_id=tenant_id, project_id=project_id, agent="A4-prose", model=model,
                                  max_turns=PROSE_TURNS)
        try:
            result = agent_jobs.prose_extraction(model, paragraphs=paragraphs, fields=PROSE_FIELDS, check=check,
                                                 max_turns=PROSE_TURNS, log_step=_locked(lock, run.log_step))
        except Exception as exc:          # the pipeline leaves the prose unread with this error; the run's record is closed
            _failed(run, exc)
            raise LlmFailure(f"{type(exc).__name__}: {exc}", run.run_id) from exc
        run.finish(_Ended(result), {"facts": len(result.facts), "refused": len(result.rejected)})
        if result.status != "COMPLETED" and not result.facts:
            # the model did not answer (not reachable, or cut short before any fact): the prose is not read, and says so
            raise LlmFailure(f"the conversation ended {result.status} with no fact", run.run_id)
        return result.facts, ModelUse(provider=model.provider, model=model.model, prompt_sha256=result.prompt_sha256,
                                      agent_run=run.run_id)

    return LlmPorts(map_tables=map_tables, extract_prose=extract_prose)
