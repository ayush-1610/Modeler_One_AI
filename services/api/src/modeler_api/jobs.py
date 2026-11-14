"""A project's background jobs, started once across every API worker (docs/ARCHITECTURE_BOUNDARIES.md, phase 8, C8).

An agent job (A1 extraction, A2/A3 research, A4 triage and sheet reading, A5 planning) and the intake pipeline's job
(`intake`, with or without a model: `intake_pipeline_jobs`) run on a thread of the worker that started them;
its lease lives under the project store's root (`modeler_storage.jobs`), so a second worker refuses a duplicate start
with the same 409 and reports the job as running on every page. The person who started a job is known to everything it
runs (`started_by`), so each agent run records who started it (the admin console's usage per person, 2026-11-10).
"""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar
from typing import Literal

from fastapi import HTTPException

from modeler_project import ProjectStore
from modeler_storage.jobs import FileJobRegistry

Kind = Literal["extraction", "research", "triage", "reading", "planning", "intake"]

# who started the job running on this thread (a subject); None outside a job
started_by: ContextVar[str | None] = ContextVar("started_by", default=None)


def _registry(store: ProjectStore) -> FileJobRegistry:
    return FileJobRegistry(store.root)  # FileProjectStore: the root every worker of the deployment shares


def start(store: ProjectStore, tenant_id: str, project_id: str, kind: Kind, target: Callable[..., None], *,
          busy: str, by: str, name: str | None = None, after: Callable[[], None] | None = None,
          checked: bool = False) -> None:
    """Run `target` in the background as the project's `kind` job, started by the person `by`; 409 `busy` while one is
    running anywhere. `after` runs once the job is released; `checked`: `target` gets a function saying whether the job
    still holds its lease."""

    def as_started(*args: object) -> None:
        started_by.set(by)
        target(*args)

    if not _registry(store).run_in_background(tenant_id, project_id, kind, as_started, name=name, after=after,
                                              checked=checked):
        raise HTTPException(status_code=409, detail=busy)


def running(store: ProjectStore, tenant_id: str, project_id: str, kind: Kind) -> bool:
    """Whether the project's `kind` job is running, on this worker or another."""
    return _registry(store).running(tenant_id, project_id, kind)
