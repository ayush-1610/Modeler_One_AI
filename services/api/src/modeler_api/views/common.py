"""Pieces several pages share: an artifact version, an impact report, the agents' status and runs, a document."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

Number = int | float


class View(BaseModel):
    """A response body as its handler builds it: every key declared, nothing added or coerced."""

    model_config = ConfigDict(extra="forbid")


class Ref(View):
    kind: str
    id: str
    version: int


class ApprovalView(View):
    ref: Ref
    record_sha256: str
    meaning: str
    by: str
    printed_name: str
    at: str
    signature_id: str | None
    note: str


class VersionView(View):
    """`deps.version_view`: an artifact version's identity, status, provenance and approvals (content when asked)."""

    kind: str
    id: str
    version: int
    sha256: str
    status: str
    stale_reasons: list[str]
    created_at: str
    created_by: str
    reason: str
    derived_from: list[Ref]
    approvals: list[ApprovalView]
    content: dict[str, Any] | None = None


class ChangeView(View):
    path: str
    before: Any
    after: Any
    kind: str


class AffectedView(View):
    ref: Ref
    status: str
    effect: str
    needs_signature: bool


class ImpactView(View):
    """`deps.impact_view`: what a change would replace and which downstream artifacts it makes stale."""

    target: Ref | None
    unchanged: bool
    changes: list[ChangeView]
    affected: list[AffectedView]
    notes: list[str]


class AgentsStatus(View):
    """`agent_jobs.agents_status`: whether an LLM provider is configured (provider and model when it is)."""

    enabled: bool
    problem: str | None = None
    provider: str | None = None
    model: str | None = None


class RunSummary(View):
    """One agent run as a page lists it (the run record's own keys; any may be missing from an old record)."""

    run_id: str | None
    agent: str | None
    status: str | None
    provider: str | None = None
    model: str | None
    started_at: str | None
    finished_at: str | None
    summary: dict[str, Any] | None


class DocumentView(View):
    id: str
    sha256: str
    name: str
    kind: str
    role: str
    n_pages: int
    size_bytes: int
    warnings: list[str]
    uploaded_at: str
    uploaded_by: str


class DataPlanStatus(View):
    """The data plan version a phase page is computed from, and its status."""

    version: int
    status: str


# A stored artifact's content as the handler returns it (an evidence item, a dataset, a client file): its owner module
# gives the kind a content model in phase 6e; until then the answer is typed down to this.
StoredContent = dict[str, Any]

