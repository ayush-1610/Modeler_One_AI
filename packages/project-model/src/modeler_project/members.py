"""Who may open a project (production readiness P3, 2026-10-15).

Keycloak tokens carry a `projects` claim, but a project made in the web would stay closed to its own creator until an
administrator added its id there. The platform therefore keeps its own memberships, per tenant in
`<root>/<tenant>/members.json`: a project's creator is its first member, and members add the people who have signed
in to the tenant at least once. The API admits a person to a project in their token's claim or in these memberships
(`modeler_api.memberships`). Every change is an audit event, so a production deployment also keeps it in PostgreSQL
(P2). Writes are atomic under a cross-process file lock; a project never loses its last member.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from modeler_project.audit import AuditLog
from pbpk_domain.atomic_io import atomic_write_text, file_lock


class MembershipError(ValueError):
    """A membership change the rules refuse (an unknown person, the last member)."""


@dataclass(frozen=True)
class Person:
    subject: str  # the token's subject: stable, unlike a name
    name: str


@dataclass(frozen=True)
class Member:
    subject: str
    name: str
    added_by: str
    added_at: str


class Memberships:
    def __init__(self, root: Path, tenant_id: str, audit: AuditLog):
        self.path = Path(root) / tenant_id / "members.json"
        self.audit = audit

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"people": {}, "projects": {}}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, doc: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.path, json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False))

    # --- reads -----------------------------------------------------------------------------------------------

    def projects_of(self, subject: str) -> frozenset[str]:
        return frozenset(pid for pid, members in self._read()["projects"].items() if subject in members)

    def members(self, project_id: str) -> list[Member]:
        doc = self._read()
        rows = doc["projects"].get(project_id, {})
        name = lambda s: doc["people"].get(s, {}).get("name", s)
        return sorted((Member(subject=s, name=name(s), added_by=name(r["added_by"]), added_at=r["added_at"])
                       for s, r in rows.items()), key=lambda m: m.added_at)

    def people(self) -> list[Person]:
        return sorted((Person(subject=s, name=p["name"]) for s, p in self._read()["people"].items()), key=lambda p: p.name)

    # --- writes ----------------------------------------------------------------------------------------------

    def remember(self, subject: str, name: str) -> None:
        """A person who signed in to this tenant, so a member can add them (written only when new or renamed)."""
        if self._read()["people"].get(subject, {}).get("name") == name:
            return
        with file_lock(self.path):
            doc = self._read()
            doc["people"][subject] = {"name": name}
            self._write(doc)

    def add(self, project_id: str, subject: str, *, by: str, reason: str) -> None:
        with file_lock(self.path):
            doc = self._read()
            if subject not in doc["people"]:
                raise MembershipError("only a person who has signed in to this workspace can be added")
            members = doc["projects"].setdefault(project_id, {})
            if subject in members:
                return
            members[subject] = {"added_by": by, "added_at": datetime.now(UTC).isoformat()}
            self.audit.append(actor=by, action="project.member.add", resource_type="project", resource_id=project_id,
                              after={"member": subject}, reason=reason)
            self._write(doc)

    def remove(self, project_id: str, subject: str, *, by: str, reason: str) -> None:
        if not reason.strip():
            raise MembershipError("say why the person no longer has access")
        with file_lock(self.path):
            doc = self._read()
            members = doc["projects"].get(project_id, {})
            if subject not in members:
                return
            if len(members) == 1:
                raise MembershipError("a project keeps at least one member: add someone else first")
            del members[subject]
            self.audit.append(actor=by, action="project.member.remove", resource_type="project", resource_id=project_id,
                              before={"member": subject}, reason=reason)
            self._write(doc)
