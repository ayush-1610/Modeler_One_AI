"""The Data room's API (plan 2026-11-21 v2 §5, §9 "API"), under `/projects/{project_id}/dataroom`.

- `uploads`: the client's delivery, many files or a zip, stored as they came (`DataRoomStore.add_upload`); `import-existing`:
  an existing project's recorded client files added as uploads, each once (`reading.import_existing`).
- `run`: the background run (`agent_jobs.dataroom_run`, the one seam to the agents, rule B4): the files read by code,
  OCR included, then A6-A10 where each has a model; one run at a time per project (409 while one runs). Its record,
  with each stage's live counts, is `GET run`.
- `""`: the whole room (`modeler_project.dataroom.room_view`), as the page and the report show it. It is assembled
  from the store's files, so it is kept per project and assembled again only when one of them changed.
- the modeler's word: the question card, a decision, a value entered with its reason, a data request's wording or
  status. Each is audited by the store, as the signed-in person; each answers the room as it now is.
- "Send to the model": what would be sent now and what blocks it (`publication`, nothing written), and the sending
  itself (`publish`), signed with the token's recent step-up (never a password), 409 with every reason while anything
  blocks it (`modeler_project.dataroom.publish`).
- the source viewer: a delivered file's pages drawn as they were read (the reading copy made again from its bytes,
  `modeler_intake.room.reading_pdf`), each page's size in points so a chip's box is highlighted where it falls, and a
  sheet's or a body's numbered lines.

Reading is for the project's members; every change is for the roles that edit Inputs, and only the project's owner
(`ownership.owner_guard`, applied in `main.py`). No path is built from input that is not a checked sha256.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, File, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from modeler_api import agent_jobs, jobs
from modeler_api.auth import ensure_step_up
from modeler_api.compliance.signatures import SignatureMeaning, Signer, sign_after_step_up
from modeler_api.config import SettingsDep
from modeler_api.deps import Reader, StoreDep, Writer, workspace_for
from modeler_api.part11 import record_signature
from modeler_api.responses import Envelope, answers, envelope
from modeler_api.views.dataroom import (
    DataPermissionsView,
    RoomPublication,
    RoomPublished,
    RoomRun,
    RoomUploaded,
    RoomUploads,
    SourceFile,
    SourcePart,
)
from modeler_intake.room import Part, document_parts, page_png, reading_pdf
from modeler_intake.room_specs import QuestionCard
from modeler_project import ProjectStore
from modeler_project.dataroom import DataRoomStore, DataRoomView, room_view
from modeler_project.dataroom.model import FileView, Value
from modeler_project.dataroom.publish import Publication, plan_publication, publish
from modeler_project.dataroom.reading import import_existing
from modeler_project.inputs import refresh_inputs
from modeler_project.members import Memberships

router = APIRouter(prefix="/api/v1", tags=["dataroom"])

BASE = "/projects/{project_id}/dataroom"
BUSY = "the Data room is already running for this project"
STOPPED = "the run stopped before it finished (the server restarted): run it again"
# the room's answer carries every field, set or not (the engine's models mark each one required in the contract)
ROOM = {"response_model": Envelope[DataRoomView]}
PNG = {"response_class": Response, "responses": {200: {"content": {"image/png": {}}, "description": "the page as a PNG"}}}


# --- the room, kept per project until one of its files changes -----------------------------------------------------


class _Memo[K, V]:
    """What this process made from files, the most recently used `keep` of them. Not a job's state (coupling C8): every
    key names exactly what its value was made from (the store's stamp, a file's sha256), so another worker that holds
    none, or an older one, makes it again and never serves one made from other files."""

    def __init__(self, keep: int) -> None:
        self.keep = keep
        self.lock = threading.Lock()
        self.items: OrderedDict[K, V] = OrderedDict()

    def get(self, key: K, make: Callable[[], V]) -> V:
        with self.lock:
            if key in self.items:
                self.items.move_to_end(key)
                return self.items[key]
        value = make()
        with self.lock:
            self.items[key] = value
            while len(self.items) > self.keep:
                self.items.popitem(last=False)
        return value


_SKIP = {"run.json", "uploads.json"}       # neither changes the room (the files read do, in files.json)
_rooms: _Memo[tuple[str, str, str], DataRoomView] = _Memo(8)        # (tenant, project, stamp) -> the room


def _stamp(base: Path | None) -> str:
    """What the room is assembled from, as it stands: every file of the store but the run's and the uploads' records,
    each by its path, time and size."""
    digest = hashlib.sha256()
    if base is not None and base.is_dir():
        for path in sorted(base.rglob("*")):
            name = path.name
            if name.startswith(".") or name.endswith(".lock") or (path.parent == base and name in _SKIP) or not path.is_file():
                continue
            stat = path.stat()
            digest.update(f"{path.relative_to(base)}|{stat.st_mtime_ns}|{stat.st_size}\n".encode())
    return digest.hexdigest()


def room_of(room: DataRoomStore) -> DataRoomView:
    """The project's room, assembled again only when a file it is made from changed since it was last assembled."""
    return _rooms.get((room.ws.tenant_id, room.ws.project_id, _stamp(room.base)), lambda: room_view(room))


def _room(project_id: str, principal: Any, store: ProjectStore) -> DataRoomStore:
    room = DataRoomStore(workspace_for(project_id, principal, store))
    if not room.available:
        raise HTTPException(status_code=503, detail="the Data room keeps its files in the project store's folder, and this "
                                                    "server has none (MODELER_READ_ROOT)")
    return room


def _named(view: DataRoomView, principal: Any, store: ProjectStore) -> DataRoomView:
    """The room with each decision's maker named as the people list names them (the record keeps the subject)."""
    names = {principal.user_id: principal.printed_name}
    try:
        names |= {p.subject: p.name for p in Memberships(store.root, principal.tenant_id,  # type: ignore[attr-defined]
                                                         store.audit(principal.tenant_id)).people()}
    except (AttributeError, OSError, ValueError):   # a store with no file root keeps no people list
        pass
    if not any(d.by in names for d in view.decisions):
        return view
    return view.model_copy(update={"decisions": tuple(d.model_copy(update={"by": names.get(d.by, d.by)}) for d in view.decisions)})


def _answer(room: DataRoomStore, principal: Any) -> dict[str, Any]:
    return envelope(_named(room_of(room), principal, room.ws.store))


@router.get(BASE, **ROOM)
def get_dataroom(project_id: str, principal: Reader, store: StoreDep) -> dict[str, Any]:
    """The whole Data room: files, the question, every section's values with their sources and statuses, the
    decisions, data requests, simulation plan and PK-Sim inputs."""
    return _answer(_room(project_id, principal, store), principal)


# --- uploads -------------------------------------------------------------------------------------------------------


@router.get(f"{BASE}/uploads", **answers(RoomUploads))
def get_dataroom_uploads(project_id: str, principal: Reader, store: StoreDep) -> dict[str, Any]:
    return envelope({"uploads": _room(project_id, principal, store).uploads()})


@router.post(f"{BASE}/uploads", status_code=201, **answers(RoomUploaded))
async def upload_dataroom_files(project_id: str, principal: Writer, store: StoreDep,
                 files: Annotated[list[UploadFile], File()]) -> dict[str, Any]:
    """Store the client's delivery as it came: many files, a zip, or both (an archive is unpacked when the files are
    read). A file sent twice is stored once."""
    room = _room(project_id, principal, store)
    added = []
    for one in files:
        data = await one.read()
        if not data:
            raise HTTPException(status_code=422, detail=f"{one.filename or 'a file'} is empty")
        added.append(room.add_upload(one.filename or "file", data, by=principal.user_id))
    return envelope({"added": added, "uploads": room.uploads()})


@router.post(f"{BASE}/import-existing", **answers(RoomUploaded))
def import_existing_files(project_id: str, principal: Writer, store: StoreDep) -> dict[str, Any]:
    """An existing project's client files, as the earlier Inputs page recorded them, added as the Data room's uploads,
    each once (plan §4: "Open in the Data room" reads their stored files again). Run reads them."""
    room = _room(project_id, principal, store)
    added = import_existing(room, by=principal.user_id)
    return envelope({"added": added, "uploads": room.uploads()})


# --- the run -------------------------------------------------------------------------------------------------------


class RoomRunStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stages: list[str] | None = Field(default=None, description="the stages to run (none named: every stage)")
    redo: list[str] = Field(default_factory=list, description="stages whose kept answers are made again")
    files: list[str] = Field(default_factory=list, description="the per-file stages for these files only (their paths)")


def _run_view(room: DataRoomStore, running: bool) -> dict[str, Any]:
    """The run's record as the page reads it; a run left "running" by a job that is gone (a restart) is failed."""
    raw = room.run()
    state = raw.get("state", "idle")
    stages = [{k: s.get(k, d) for k, d in (("id", ""), ("label", ""), ("agent", ""), ("state", "waiting"), ("done", 0),
                                            ("total", 0), ("note", ""))} for s in raw.get("stages", [])]
    error = str(raw.get("error") or "")
    if state == "running" and not running:
        state, error = "failed", STOPPED
        stages = [{**s, "state": "failed" if s["state"] == "running" else s["state"]} for s in stages]
    return {"state": state, "stages": stages, "agents": dict(raw.get("agents") or {}), "error": error,
            "started_at": raw.get("started_at"), "finished_at": raw.get("finished_at")}


@router.get(f"{BASE}/run", **answers(RoomRun))
def get_dataroom_run(project_id: str, principal: Reader, store: StoreDep) -> dict[str, Any]:
    room = _room(project_id, principal, store)
    return envelope(_run_view(room, jobs.running(store, principal.tenant_id, project_id, "dataroom")))


@router.post(f"{BASE}/run", status_code=202, **answers(RoomRun))
def start_dataroom_run(project_id: str, principal: Writer, store: StoreDep, body: RoomRunStart | None = None) -> dict[str, Any]:
    """Run the Data room in the background: the files read (OCR included), then the agents that have a model. Each
    stage's answers are kept per file, so a second run redoes only what is new, unless `redo` names the stage."""
    room = _room(project_id, principal, store)
    body = body or RoomRunStart()
    stages = agent_jobs.dataroom_stages()
    known = [sid for sid, _label, _agent in stages]
    unknown = sorted({*(body.stages or ()), *body.redo} - set(known))
    if unknown:
        raise HTTPException(status_code=422, detail=f"no stage {', '.join(unknown)}: the stages are {', '.join(known)}")
    if body.files and (missing := sorted(set(body.files) - {f.path for f in room.files()})):
        raise HTTPException(status_code=422, detail=f"no file {', '.join(missing)} in the room")
    if not room.uploads():
        raise HTTPException(status_code=409, detail="nothing to read yet: add the client's files first")
    if jobs.running(store, principal.tenant_id, project_id, "dataroom"):
        raise HTTPException(status_code=409, detail=BUSY)
    wanted = body.stages if body.stages is not None else known
    # the run's first record, written now, so the page that started it reads it as running at once
    room.set_run({"state": "running", "started_at": None, "finished_at": None, "error": "", "agents": {},
                  "stages": [{"id": sid, "label": label, "agent": agent, "state": "waiting" if sid in wanted else "skipped",
                              "done": 0, "total": 0, "note": ""} for sid, label, agent in stages]})
    room.audit(actor=principal.user_id, action="dataroom.run", resource_id="run",
               after={"stages": list(wanted), "redo": list(body.redo), "files": list(body.files)})
    actor, ws = principal.user_id, room.ws

    def job() -> None:
        agent_jobs.dataroom_run(DataRoomStore(ws), actor=actor, stages=wanted, redo=body.redo, files=body.files)

    jobs.start(store, principal.tenant_id, project_id, "dataroom", job, busy=BUSY, by=principal.user_id,
               name=f"dataroom-{project_id}")
    return envelope(_run_view(room, True))


# --- the modeler's word --------------------------------------------------------------------------------------------


class RoomQuestionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    card: QuestionCard
    confirmed: bool = False
    reason: str = ""


@router.put(f"{BASE}/question", **ROOM)
def put_dataroom_question(project_id: str, principal: Writer, store: StoreDep, body: RoomQuestionBody) -> dict[str, Any]:
    """The question card as the modeler confirms or edits it (a confirmation is audited with its checklist)."""
    room = _room(project_id, principal, store)
    if not body.card.question.strip():
        raise HTTPException(status_code=422, detail="say what the modelling must answer")
    room.set_question(body.card, by=principal.user_id, confirmed=body.confirmed, reason=body.reason)
    return _answer(room, principal)


class RoomChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chosen: str = Field(description="the id of one of the decision's options")
    reason: str = ""


@router.post(f"{BASE}/decisions/{{decision_id:path}}", **ROOM)
def decide_in_dataroom(project_id: str, decision_id: str, principal: Writer, store: StoreDep, body: RoomChoice) -> dict[str, Any]:
    """Choose one of a decision's options, with the reason (a choice other than the suggestion needs one)."""
    room = _room(project_id, principal, store)
    decision = next((d for d in room_of(room).decisions if d.id == decision_id), None)
    if decision is None:
        raise HTTPException(status_code=404, detail="no such decision in the room")
    if body.chosen not in {o.id for o in decision.options}:
        raise HTTPException(status_code=400, detail=f"“{decision.title}” offers no such option")
    if body.chosen != decision.suggested and not body.reason.strip():
        raise HTTPException(status_code=422, detail="say why you chose another option than the one suggested")
    room.decide(decision_id, body.chosen, by=principal.user_id, reason=body.reason.strip())
    return _answer(room, principal)


class RoomEntered(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[A-Za-z0-9_.:\-\[\] ]{1,120}$", description="the input it fills (a PK-Sim input's name)")
    label: str = Field(min_length=1, max_length=200)
    value: float | str
    unit: str = Field(default="", max_length=40)
    reason: str = Field(min_length=1, max_length=2000, description="why this value: entered by a person, it needs one")


@router.post(f"{BASE}/entered", **ROOM)
def enter_dataroom_value(project_id: str, principal: Writer, store: StoreDep, body: RoomEntered) -> dict[str, Any]:
    """A value entered by a person, recorded as Entered with the reason."""
    room = _room(project_id, principal, store)
    if not body.reason.strip():
        raise HTTPException(status_code=422, detail="a value entered by a person needs its reason")
    if isinstance(body.value, str) and not body.value.strip():
        raise HTTPException(status_code=422, detail="enter the value")
    room.enter(Value(key=body.key, label=body.label, value=body.value, unit=body.unit, as_written=str(body.value),
                     status="entered"), by=principal.user_id, reason=body.reason.strip())
    return _answer(room, principal)


class RoomRequestEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    wording: str | None = Field(default=None, max_length=4000)
    status: Literal["open", "not_needed", "answered"] | None = None


@router.patch(f"{BASE}/requests/{{request_id}}", **ROOM)
def edit_dataroom_request(project_id: str, request_id: str, principal: Writer, store: StoreDep,
                 body: RoomRequestEdit) -> dict[str, Any]:
    """A data request's wording to the client, or its status (open, not needed for this question, answered)."""
    room = _room(project_id, principal, store)
    if not any(r.id == request_id for r in room_of(room).requests):
        raise HTTPException(status_code=404, detail="no such data request in the room")
    if body.wording is None and body.status is None:
        raise HTTPException(status_code=422, detail="give the wording or the status")
    room.edit_request(request_id, by=principal.user_id, wording=body.wording, status=body.status)
    return _answer(room, principal)


# --- send to the model ---------------------------------------------------------------------------------------------


def _with_unit(value: Any, unit: str | None) -> str:
    text = f"{value:g}" if isinstance(value, float) else str(value)
    return f"{text} {unit}" if unit else text


def _publication(plan: Publication) -> dict[str, Any]:
    return {"evidence": [{"target": e.target, "value": _with_unit(e.value, e.unit)} for e in plan.evidence],
            "datasets": [{"target": str(d.study.get("study_id", d.id)),
                          "value": f"{' and '.join(s.name for s in d.series)}, N = {d.study.get('n', '')}"} for d in plan.datasets],
            "blocked": list(plan.blocked)}


@router.get(f"{BASE}/publication", **answers(RoomPublication))
def get_dataroom_publication(project_id: str, principal: Reader, store: StoreDep) -> dict[str, Any]:
    """What "Send to the model" would send now (evidence items and observed datasets) and what blocks it; nothing is
    written."""
    room = _room(project_id, principal, store)
    return envelope(_publication(plan_publication(room_of(room), by=principal.user_id)))


class RoomPublish(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=2000, description="why the inputs are sent now (kept with the signature)")


@router.post(f"{BASE}/publish", **answers(RoomPublished))
def publish_dataroom(project_id: str, principal: Writer, store: StoreDep, settings: SettingsDep,
                     body: RoomPublish) -> dict[str, Any]:
    """Send the room's confirmed inputs to the model: compound and release values as accepted evidence, each arm's mean
    profile as an accepted observed dataset, so Review & sign starts from them. Signed with the token's recent step-up
    (403 `STEP_UP_REQUIRED`); refused (409 with every reason, nothing signed) while anything blocks it. Sending again
    adds only what changed."""
    room = _room(project_id, principal, store)
    if not body.reason.strip():
        raise HTTPException(status_code=422, detail="say why the inputs are sent now")
    view, by = room_of(room), principal.user_id
    plan = plan_publication(view, by=by)
    if plan.blocked:
        raise HTTPException(status_code=409, detail={"code": "NOT_READY", "message": "not sent to the model: "
                                                     + " · ".join(plan.blocked), "blocked": list(plan.blocked)})
    ensure_step_up(principal)       # the signature comes from the token's recent step-up, never a password
    record = json.dumps({"evidence": [e.id for e in plan.evidence], "datasets": [d.id for d in plan.datasets]}, sort_keys=True)
    signature = sign_after_step_up(signer=Signer(user_id=by, printed_name=principal.printed_name),
                                   meaning=SignatureMeaning.REVIEWED, record_type="dataroom-publication",
                                   record_id=f"{project_id}/dataroom/publication",
                                   record_sha256=hashlib.sha256(record.encode()).hexdigest(), acr=principal.acr or "")
    record_signature(settings, principal.tenant_id, signature)
    try:
        written = publish(room.ws, view, by=by, reason=body.reason.strip())
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    room.audit(actor=by, action="dataroom.publish", resource_id="publication",
               after={**written, "signature_id": signature.signature_id}, reason=body.reason.strip())
    refresh_inputs(room.ws, by=by)  # the inputs follow every change (redesign §3.2)
    return envelope({**written, "signature_id": signature.signature_id, "manifestation": signature.manifestation()})


# --- where the project's files may go (the governance review, 2026-11-22) -----------------------------------------


class DataGrantBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    basis: str = "the client's written consent"
    reference: str = ""             # the client's document: a letter, an email, a contract clause
    expires: str = ""               # YYYY-MM-DD; empty for none


class DataPermissionsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    in_house_only: bool = True
    services: dict[str, DataGrantBody] = Field(default_factory=dict)
    reason: str = ""


def _permissions(ws: Any) -> dict[str, Any]:
    from datetime import UTC, datetime

    from modeler_project.data_permissions import CLOUD_SERVICES, DataPermissions

    perms, today = DataPermissions(ws), datetime.now(UTC).date()
    doc = perms.doc()
    grants = [{"service": p, "label": CLOUD_SERVICES[p], **{k: g.get(k, "") for k in ("basis", "reference", "expires", "by", "at")},
               "in_force": perms.allows(p, today)} for p, g in doc["services"].items() if p in CLOUD_SERVICES]
    history = [{"in_house_only": h["in_house_only"], "services": sorted(h["services"]), "by": h["by"], "at": h["at"],
                "reason": h["reason"]} for h in reversed(doc.get("history", []))]
    return envelope({"in_house_only": doc["in_house_only"], "grants": grants, "history": history,
                     "services": [{"service": p, "label": label} for p, label in CLOUD_SERVICES.items()]})


@router.get("/projects/{project_id}/data-permissions", **answers(DataPermissionsView))
def get_data_permissions(project_id: str, principal: Reader, store: StoreDep) -> dict[str, Any]:
    """Where this project's client files may be sent for an AI model to read: in-house only unless a cloud service has
    the client's recorded permission."""
    return _permissions(workspace_for(project_id, principal, store))


@router.put("/projects/{project_id}/data-permissions", **answers(DataPermissionsView))
def put_data_permissions(project_id: str, principal: Writer, store: StoreDep, body: DataPermissionsBody) -> dict[str, Any]:
    """Record where this project's client files may go, as a whole: in-house only, or the cloud services the client
    allowed, each with the client's written permission (its reference) and when it ends. Confirmed with the step-up and
    audited; the agents follow it from their next request."""
    from modeler_project.data_permissions import DataPermissions, PermissionError_

    ws = workspace_for(project_id, principal, store)
    if not body.reason.strip():
        raise HTTPException(status_code=422, detail="say why (the client's permission, or why it is withdrawn)")
    ensure_step_up(principal)
    try:
        DataPermissions(ws).set(in_house_only=body.in_house_only,
                                services={p: g.model_dump() for p, g in body.services.items()},
                                by=principal.user_id, reason=body.reason)
    except PermissionError_ as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _permissions(ws)


# --- the source viewer ---------------------------------------------------------------------------------------------

_copies: _Memo[str, bytes | None] = _Memo(4)                      # sha256 -> the reading copy (a PDF), None: no pages
_pages: _Memo[tuple[str, int, float], bytes] = _Memo(32)          # (sha256, page, scale) -> the page as a PNG


def _file(room: DataRoomStore, sha256: str) -> FileView:
    found = next((f for f in room.files() if f.sha256 == sha256 and not f.duplicate_of), None)
    if found is None:
        raise HTTPException(status_code=404, detail="no such file in the room")
    return found


def _parts(room: DataRoomStore, file: FileView) -> list[Part]:
    doc = room.doc(file.sha256)
    return document_parts(doc) if doc is not None else []


@router.get(f"{BASE}/files/{{sha256}}", **answers(SourceFile))
def get_dataroom_file(project_id: str, sha256: str, principal: Reader, store: StoreDep) -> dict[str, Any]:
    """A delivered file as the source viewer opens it: its pages with their size in points, or its parts of lines."""
    room = _room(project_id, principal, store)
    file = _file(room, sha256)
    parts = _parts(room, file)
    return envelope({"sha256": file.sha256, "name": file.name, "path": file.path, "kind": file.kind,
                     "pages": [{"page": p.page, "width": p.width or 0.0, "height": p.height or 0.0}
                               for p in parts if p.page is not None],
                     "parts": [p.name for p in parts if p.page is None]})


@router.get(f"{BASE}/files/{{sha256}}/pages/{{page}}.png", **PNG)
def get_dataroom_page(project_id: str, sha256: str, page: int, principal: Reader, store: StoreDep,
             scale: Annotated[float, Query(ge=0.5, le=4.0)] = 1.5) -> Response:
    """One page of a delivered file drawn as it was read: the reading copy (a PDF turned upright, an image as a scan)
    made again from the file's bytes, so a chip's box falls where it is drawn."""
    room = _room(project_id, principal, store)
    file = _file(room, sha256)

    def copy() -> bytes | None:
        try:
            return reading_pdf(file.name, room.file_bytes(file.sha256))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="the file's bytes are not in the store") from exc

    pdf = _copies.get(file.sha256, copy)
    if pdf is None:
        raise HTTPException(status_code=404, detail=f"{file.name} is read as lines, not pages: open its parts")

    def draw() -> bytes:
        try:
            return page_png(pdf, page, scale=scale)
        except IndexError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    png = _pages.get((file.sha256, page, scale), draw)
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


@router.get(f"{BASE}/files/{{sha256}}/parts/{{part:path}}", **answers(SourcePart))
def get_dataroom_part(project_id: str, sha256: str, part: str, principal: Reader, store: StoreDep) -> dict[str, Any]:
    """One part of a delivered file (a sheet, a Word or text body, a page's lines), numbered as the agents read it."""
    room = _room(project_id, principal, store)
    found = next((p for p in _parts(room, _file(room, sha256)) if p.name == part), None)
    if found is None:
        raise HTTPException(status_code=404, detail="the file has no such part")
    return envelope({"sha256": sha256, "name": found.name,
                     "lines": [{"number": ln.number, "cells": [{"text": c.text, "ref": c.ref, "box": c.box} for c in ln.cells]}
                               for ln in found.lines]})
