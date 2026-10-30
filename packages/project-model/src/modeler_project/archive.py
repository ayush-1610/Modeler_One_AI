"""Archived projects (page review 1, the owner's decision 5 of 2026-10-29: archive, never delete).

A project is a Part 11 record: its signed MAP, its campaigns and its audit trail cite it, so it is never erased. An
archived project is hidden from the Projects list and keeps everything it holds; it opens by its address, and a person
restores it. The archive is kept per tenant in `<root>/<tenant>/archive.json`. Archiving and restoring each need a
reason and are audit events, like the memberships (`modeler_project.members`). Writes are atomic under a cross-process
file lock.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from modeler_project.audit import AuditLog
from pbpk_domain.atomic_io import atomic_write_text, file_lock


class ArchiveError(ValueError):
    """An archive change the rules refuse (no reason)."""


@dataclass(frozen=True)
class Archived:
    by: str
    at: str
    reason: str


class ProjectArchive:
    def __init__(self, root: Path, tenant_id: str, audit: AuditLog):
        self.path = Path(root) / tenant_id / "archive.json"
        self.audit = audit

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"projects": {}}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, doc: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.path, json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False))

    def archived(self) -> dict[str, Archived]:
        """Every archived project of the tenant, with who archived it, when and why."""
        return {pid: Archived(**row) for pid, row in self._read()["projects"].items()}

    def archive(self, project_id: str, *, by: str, reason: str) -> None:
        if not reason.strip():
            raise ArchiveError("say why the project is archived (the reason is kept in the audit trail)")
        with file_lock(self.path):
            doc = self._read()
            if project_id in doc["projects"]:
                return
            doc["projects"][project_id] = {"by": by, "at": datetime.now(UTC).isoformat(), "reason": reason.strip()}
            self.audit.append(actor=by, action="project.archive", resource_type="project", resource_id=project_id,
                              after={"archived": True}, reason=reason.strip())
            self._write(doc)

    def restore(self, project_id: str, *, by: str, reason: str) -> None:
        if not reason.strip():
            raise ArchiveError("say why the project is restored (the reason is kept in the audit trail)")
        with file_lock(self.path):
            doc = self._read()
            if project_id not in doc["projects"]:
                return
            before = doc["projects"].pop(project_id)
            self.audit.append(actor=by, action="project.restore", resource_type="project", resource_id=project_id,
                              before={"archived": True, **before}, after={"archived": False}, reason=reason.strip())
            self._write(doc)
