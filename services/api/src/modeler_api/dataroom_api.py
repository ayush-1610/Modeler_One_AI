"""The Data room's API (plan 2026-11-21 v2 §5, §9 "API"), under `/projects/{project_id}/dataroom`.

- `uploads`: the client's delivery, many files or a zip, stored as they came (`DataRoomStore.add_upload`); `import-existing`:
  an existing project's recorded client files added as uploads, each once (`reading.import_existing`).
- `run`: the background run (`agent_jobs.dataroom_run`, the one seam to the agents, rule B4): the files read by code,
  OCR included, then A6-A10 where each has a model; one run at a time per project (409 while one runs). Its record,
  with each stage's live counts, is `GET run`. A run that stops for a reason that passes (a provider down or
  rate-limited, a paid model's cap, a chosen model that cannot be used) is paused, not failed: it resumes by itself,
  when the administrator changes what stopped it, or now (`run:resume`), where it stopped (`dataroom_runs`). `GET
  run/estimate`: what the next run is expected to cost on paid models, asked once before a paid run starts.
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

import contextlib
import hashlib
import json
import threading
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, File, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from modeler_api import agent_jobs, dataroom_runs, jobs
from modeler_api.auth import Principal, ensure_step_up
from modeler_api.compliance.signatures import SignatureMeaning, Signer, sign_after_step_up
from modeler_api.config import SettingsDep
from modeler_api.deps import Reader, StoreDep, Writer, workspace_for
from modeler_api.part11 import record_signature
from modeler_api.responses import Envelope, answers, envelope
from modeler_api.views.dataroom import (
    RoomPublication,
    RoomPublished,
    RoomRun,
    RoomRunEstimate,
    RoomUploaded,
    RoomUploads,
    SourceFile,
    SourcePart,
)
from modeler_intake.room import Part, document_parts, page_png, reading_pdf
from modeler_intake.room_specs import QuestionCard
from modeler_project import ProjectStore
from modeler_project.dataroom import DataRoomStore, DataRoomView, room_view
from modeler_project.dataroom.checklist import DECISION as APPLICATIONS_DECISION
from modeler_project.dataroom.model import FileView, Value
from modeler_project.dataroom.publish import (
    Publication,
    basis_sha256,
    plan_publication,
    publication_basis,
    publication_id,
    publication_record,
    publish,
)
from modeler_project.dataroom.reading import import_existing
from modeler_project.inputs import refresh_inputs
from modeler_project.members import Memberships

router = APIRouter(prefix="/api/v1", tags=["dataroom"])

BASE = "/projects/{project_id}/dataroom"
BUSY = dataroom_runs.BUSY
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


_SKIP = {"run.json", "uploads.json"}       # neither changes the room (the files read do, in files.json); nor do the
# publications' records (publications/<id>.json), which say what each send rested on
_rooms: _Memo[tuple[str, str, str], DataRoomView] = _Memo(8)        # (tenant, project, stamp) -> the room


def _stamp(base: Path | None) -> str:
    """What the room is assembled from, as it stands: every file of the store but the run's and the uploads' records,
    each by its path, time and size."""
    digest = hashlib.sha256()
    if base is not None and base.is_dir():
        for path in sorted(base.rglob("*")):
            name = path.name
            if (name.startswith(".") or name.endswith(".lock") or (path.parent == base and name in _SKIP)
                    or path.relative_to(base).parts[0] == "publications" or not path.is_file()):
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


_PAUSE_KEYS = (("reason", "provider_unavailable"), ("said", ""), ("detail", ""), ("stage", ""), ("where", ""),
               ("per_file", False), ("done", 0), ("total", 0), ("at", ""), ("resume_at", None))


def _run_view(room: DataRoomStore, running: bool, raw: dict[str, Any] | None = None) -> dict[str, Any]:
    """The run's record as the page reads it; a run left "running" by a job that is gone (a restart) is failed."""
    raw = room.run() if raw is None else raw
    state = raw.get("state", "idle")
    stages = [{k: s.get(k, d) for k, d in (("id", ""), ("label", ""), ("agent", ""), ("state", "waiting"), ("done", 0),
                                            ("total", 0), ("note", ""))} for s in raw.get("stages", [])]
    error = str(raw.get("error") or "")
    if state == "running" and not running:
        state, error = "failed", STOPPED
        stages = [{**s, "state": "failed" if s["state"] == "running" else s["state"]} for s in stages]
    pause = raw.get("pause") if state == "paused" else None
    return {"state": state, "stages": stages, "agents": dict(raw.get("agents") or {}), "error": error,
            "started_at": raw.get("started_at"), "finished_at": raw.get("finished_at"),
            "pause": {k: pause.get(k, d) for k, d in _PAUSE_KEYS} if pause else None}


@router.get(f"{BASE}/run", **answers(RoomRun))
def get_dataroom_run(project_id: str, principal: Reader, store: StoreDep) -> dict[str, Any]:
    room = _room(project_id, principal, store)
    return envelope(_run_view(room, jobs.running(store, principal.tenant_id, project_id, "dataroom")))


@router.get(f"{BASE}/run/estimate", **answers(RoomRunEstimate))
def estimate_dataroom_run(project_id: str, principal: Reader, store: StoreDep) -> dict[str, Any]:
    """What the next run is expected to cost on the paid models its agents start on, from the files still to read and
    their sizes (plan 2026-11-24 §2.4): the page asks once before a paid run starts. `paid` false: it costs nothing."""
    return envelope(agent_jobs.dataroom_estimate(_room(project_id, principal, store)))


@router.post(f"{BASE}/run:resume", status_code=202, **answers(RoomRun))
def resume_dataroom_run(project_id: str, principal: Writer, store: StoreDep) -> dict[str, Any]:
    """Resume a paused run now, where it stopped (plan 2026-11-24 §4): the stages and files it finished are not run
    again. 409 when the run is not paused, or one is running."""
    room = _room(project_id, principal, store)
    raw = room.run()
    if raw.get("state") != "paused":
        raise HTTPException(status_code=409, detail="the run is not paused: there is nothing to resume")
    if not dataroom_runs.resume(store, principal.tenant_id, project_id, by=principal.user_id, how="now"):
        raise HTTPException(status_code=409, detail=BUSY)
    # the page reads it as running at once; the job itself moves the record on, under the project's lease
    stages = [{**s, "state": "waiting" if s.get("state") == "paused" else s.get("state")} for s in raw.get("stages", [])]
    return envelope(_run_view(room, True, {**raw, "state": "running", "pause": None, "error": "", "stages": stages}))


@router.post(f"{BASE}/run", status_code=202, **answers(RoomRun))
def start_dataroom_run(project_id: str, principal: Writer, store: StoreDep, body: RoomRunStart | None = None) -> dict[str, Any]:
    """Run the Data room in the background: the files read (OCR included), then the agents that have a model. Each
    stage's answers are kept per file, so a second run redoes only what is new, unless `redo` names the stage. A run
    that stops for a reason that passes is paused, not failed, and resumes where it stopped (`run:resume`)."""
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
    # the run's first record is written now, so the page that started it reads it as running at once
    dataroom_runs.begin(store, room, by=principal.user_id, stages=body.stages, redo=body.redo, files=body.files)
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
    if body.confirmed:
        _draft_brief(room, principal)
    return _answer(room, principal)


def _draft_brief(room: DataRoomStore, principal: Principal) -> None:
    """Start's brief drafted from what the room now holds (plan 2026-11-24 §7, B4): the confirmed card, the applications
    decision, what was sent. Drafts only: a person's value is never overwritten. A missing card or brief never fails the
    room's own route."""
    from modeler_project.brief_from_room import RoomError, draft_brief_from_room

    with contextlib.suppress(RoomError):
        draft_brief_from_room(room.ws, by=principal.user_id)


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
    if decision_id == APPLICATIONS_DECISION:
        _draft_brief(room, principal)
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
            "blocked": list(plan.blocked), "notes": list(plan.notes)}


@router.get(f"{BASE}/publication", **answers(RoomPublication))
def get_dataroom_publication(project_id: str, principal: Reader, store: StoreDep) -> dict[str, Any]:
    """What "Send to the model" would send now (evidence items and observed datasets), what blocks it (a study already
    in the project through Delivery or Inputs too), and what is sent otherwise than the files might suggest; nothing is
    written."""
    room = _room(project_id, principal, store)
    return envelope(_publication(plan_publication(room_of(room), by=principal.user_id, ws=room.ws)))


class RoomPublish(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=2000, description="why the inputs are sent now (kept with the signature)")


@router.post(f"{BASE}/publish", **answers(RoomPublished))
def publish_dataroom(project_id: str, principal: Writer, store: StoreDep, settings: SettingsDep,
                     body: RoomPublish) -> dict[str, Any]:
    """Send the room's confirmed inputs to the model: compound and release values as accepted evidence, each arm's mean
    profile as an accepted observed dataset, so Review & sign starts from them. Signed with the token's recent step-up
    (403 `STEP_UP_REQUIRED`); refused (409 with every reason, nothing signed) while anything blocks it. Sending again
    adds only what changed, and what it replaces is rejected, superseded by this publication. What the send rested on
    (the confirmed question, the applications, every decision with its reason, the open data requests, the NCA values
    the data do not reproduce, the means' BLQ convention) is kept as the publication's record
    (`dataroom/publications/<id>.json`), and the signature covers its sha256."""
    room = _room(project_id, principal, store)
    if not body.reason.strip():
        raise HTTPException(status_code=422, detail="say why the inputs are sent now")
    view, by, reason = room_of(room), principal.user_id, body.reason.strip()
    plan = plan_publication(view, by=by, ws=room.ws)
    if plan.blocked:
        raise HTTPException(status_code=409, detail={"code": "NOT_READY", "message": "not sent to the model: "
                                                     + " · ".join(plan.blocked), "blocked": list(plan.blocked)})
    ensure_step_up(principal)       # the signature comes from the token's recent step-up, never a password
    basis = publication_basis(view, plan, question=room.question_record())
    digest = basis_sha256(basis)
    pub_id = publication_id()
    record = json.dumps({"evidence": [e.id for e in plan.evidence], "datasets": [d.id for d in plan.datasets],
                         "publication": pub_id, "basis_sha256": digest}, sort_keys=True)
    signature = sign_after_step_up(signer=Signer(user_id=by, printed_name=principal.printed_name),
                                   meaning=SignatureMeaning.REVIEWED, record_type="dataroom-publication",
                                   record_id=f"{project_id}/dataroom/publication/{pub_id}",
                                   record_sha256=hashlib.sha256(record.encode()).hexdigest(), acr=principal.acr or "")
    record_signature(settings, principal.tenant_id, signature)
    try:
        written = publish(room.ws, view, by=by, reason=reason, publication=pub_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    room.put_publication(pub_id, publication_record(pub_id, basis=basis, plan=plan, written=written, by=by, reason=reason,
                                                    signature_id=signature.signature_id, signed_record=record))
    counts = {k: written[k] for k in ("evidence", "datasets", "skipped", "superseded")}
    room.audit(actor=by, action="dataroom.publish", resource_id=f"publication/{pub_id}",
               after={**counts, "superseded_ids": written["superseded_evidence"] + written["superseded_datasets"],
                      "basis_sha256": digest, "signature_id": signature.signature_id}, reason=reason)
    _draft_brief(room, principal)  # before the inputs are refreshed, so their readiness reads the new brief
    refresh_inputs(room.ws, by=by)  # the inputs follow every change (redesign §3.2)
    return envelope({**counts, "publication": pub_id, "basis_sha256": digest, "notes": list(plan.notes),
                     "signature_id": signature.signature_id, "manifestation": signature.manifestation()})


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
