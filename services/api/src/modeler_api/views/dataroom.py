"""The Data room's answers beside the room itself (plan 2026-11-21 v2 §9 "API"): its uploads, its background run, and
the source viewer's file, part and page. The room is the engine's own model (`modeler_project.dataroom.DataRoomView`).
"""

from __future__ import annotations

from typing import Literal

from modeler_api.views.common import View


class RoomUpload(View):
    """One upload as stored: a file or an archive, its bytes in the project's blobs."""

    name: str
    sha256: str
    size_bytes: int
    by: str
    at: str


class RoomUploads(View):
    uploads: list[RoomUpload]


class RoomUploaded(View):
    """What an upload added: `added` the uploads of this request (a file sent twice is stored once), `uploads` all."""

    added: list[RoomUpload]
    uploads: list[RoomUpload]


class RoomRunStage(View):
    id: str
    label: str
    agent: str                       # the console's agent that does it (A6 … A10), "" for code
    state: Literal["waiting", "running", "done", "skipped", "failed", "paused"]
    done: int
    total: int
    note: str


class RoomRunPause(View):
    """Why and where a run paused (plan 2026-11-24 §4), and when it resumes by itself. `provider_unavailable`: no model of
    an agent's chain could answer (it resumes after 10, then 20, then 40 minutes; then `resume_at` is null and a person
    resumes it); `budget_cap`: a paid model's cap is reached (it resumes when the cap is raised or the agent switched
    to a free model); `no_model`: the agent's chosen model cannot be used (it resumes when it is set up). An
    administrator's change of a model, a key or the cap resumes it at once; nothing finished is read again."""

    reason: Literal["provider_unavailable", "budget_cap", "no_model"]
    said: str                        # the reason in a plain sentence
    detail: str                      # the provider's own words, when there are any
    stage: str                       # the stage it stopped in
    where: str                       # that stage as the page says it ("extraction")
    per_file: bool                   # a stage that goes file by file: `done` of `total` files
    done: int
    total: int
    at: str
    resume_at: str | None            # when it resumes by itself; null: it waits for a change or a person


class RoomRun(View):
    """The Data room's background run (`modeler_agents.dataroom.run_room`): each stage with its live counts and note,
    and, for a paused run, why and where it paused (`pause`)."""

    state: Literal["idle", "running", "done", "failed", "paused"]
    stages: list[RoomRunStage]
    agents: dict[str, str]           # agent -> provider/model it ran on
    error: str
    started_at: str | None
    finished_at: str | None
    pause: RoomRunPause | None


class RoomRunEstimateAgent(View):
    agent: str
    provider: str                    # "" when the agent has no model
    model: str
    paid: bool


class RoomRunEstimate(View):
    """What the next run is expected to cost on paid models (`modeler_agents.dataroom.cost`; plan 2026-11-24 §2.4), from
    the files still to read and their sizes: tokens ≈ characters / 4, per file 8.5 to 10 calls and 9,000 to 13,000
    output tokens (measured, §2.2), each agent's measured share at its model's list price. `paid` false: no agent starts on a
    paid model, and the run costs nothing in dollars. The caps a paid run stops at, and this month's paid spend."""

    paid: bool
    files: int
    characters: int
    calls_low: int
    calls_high: int
    input_tokens_low: int
    input_tokens_high: int
    output_tokens_low: int
    output_tokens_high: int
    usd: float
    usd_low: float
    usd_high: float
    agents: list[RoomRunEstimateAgent]
    basis: str
    run_cap_usd: float
    month_cap_usd: float
    month_spent_usd: float


class SourcePage(View):
    page: int
    width: float                     # points: a chip's box (points, top-left origin) is drawn on this
    height: float


class SourceFile(View):
    """A delivered file as the source viewer opens it: its pages (with their size) or its parts of lines."""

    sha256: str
    name: str
    path: str
    kind: str
    pages: list[SourcePage]
    parts: list[str]


class SourceCell(View):
    text: str
    ref: str                         # a sheet cell's A1 address, a Word table cell (t1/r2/c3), a paragraph
    box: tuple[float, float, float, float] | None   # a page cell: its words' box, points, top-left origin


class SourceLine(View):
    number: int
    cells: list[SourceCell]


class SourcePart(View):
    """One part of a file (a sheet, a Word or text body, a page's lines), numbered as the agents read it."""

    sha256: str
    name: str
    lines: list[SourceLine]


class PublicationItem(View):
    target: str                      # the input it sets: a CPF id (phys.mw, form.<name>.weibull.t50) or a dataset's study
    value: str                       # as it will be sent, with its unit


class RoomPublication(View):
    """What "Send to the model" would send now (`modeler_project.dataroom.publish.plan_publication`, nothing written),
    what keeps it from being sent, and what is sent otherwise than the files might suggest (a fasted arm's meals left
    out, water not stated, a release a Weibull curve does not describe), in words."""

    evidence: list[PublicationItem]
    datasets: list[PublicationItem]
    blocked: list[str]
    notes: list[str]


class RoomPublished(View):
    """What was sent, signed: items written, items already in the project (skipped), the Data room's earlier items it
    replaced (superseded), the publication whose record keeps what the send rested on, and the signature."""

    evidence: int
    datasets: int
    skipped: int
    superseded: int
    publication: str                 # its record: dataroom/publications/<publication>.json
    basis_sha256: str                # of the record's basis, which the signature covers
    notes: list[str]
    signature_id: str
    manifestation: str


class DataGrant(View):
    """One cloud service a project's client files may be sent to: the client's written permission it rests on."""

    service: str               # groq, nvidia, bedrock, openai_compat
    label: str
    basis: str
    reference: str
    expires: str               # YYYY-MM-DD, "" for none
    by: str
    at: str
    in_force: bool


class DataService(View):
    service: str
    label: str


class DataChange(View):
    in_house_only: bool
    services: list[str]
    by: str
    at: str
    reason: str


class DataPermissionsView(View):
    """Where this project's client files may be sent for an AI model to read (the governance review, 2026-11-22):
    in-house only unless a cloud service has the client's recorded permission. `services`: every cloud service there
    is; `history`: each change, newest first."""

    in_house_only: bool
    you_change_it: bool        # the project's owner or an administrator (the owner, 2026-11-24)
    who_changes_it: str        # in words: "the project's owner, Ana, or an administrator"
    grants: list[DataGrant]
    services: list[DataService]
    history: list[DataChange]
