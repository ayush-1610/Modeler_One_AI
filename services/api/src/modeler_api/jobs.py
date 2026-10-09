"""A project's background jobs, started once across every API worker (docs/ARCHITECTURE_BOUNDARIES.md, phase 8, C8).

An agent job (A1 extraction, A2/A3 research, A4 triage, A5 planning) runs on a thread of the worker that started it;
its lease lives under the project store's root (`modeler_storage.jobs`), so a second worker refuses a duplicate start
with the same 409 and reports the job as running on every page.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from fastapi import HTTPException

from modeler_project import ProjectStore
from modeler_storage.jobs import FileJobRegistry

Kind = Literal["extraction", "research", "triage", "planning"]


def _registry(store: ProjectStore) -> FileJobRegistry:
    return FileJobRegistry(store.root)  # FileProjectStore: the root every worker of the deployment shares


def start(store: ProjectStore, tenant_id: str, project_id: str, kind: Kind, target: Callable[[], None], *,
          busy: str, name: str | None = None) -> None:
    """Run `target` in the background as the project's `kind` job; 409 `busy` while one is running anywhere."""
    if not _registry(store).run_in_background(tenant_id, project_id, kind, target, name=name):
        raise HTTPException(status_code=409, detail=busy)


def running(store: ProjectStore, tenant_id: str, project_id: str, kind: Kind) -> bool:
    """Whether the project's `kind` job is running, on this worker or another."""
    return _registry(store).running(tenant_id, project_id, kind)
