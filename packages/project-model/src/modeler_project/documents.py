"""The project's document library: uploaded files as DOCUMENT artifacts with quotable pages (plan P0, §6, §8).

The raw bytes go to the write-once blob store under their SHA-256; the extracted page texts go to a second blob; the
DOCUMENT artifact (id ``doc-<first 12 hex of the sha>``) records the metadata and both hashes. Agents and people cite
``(doc_sha256, page, quote)``; `DocumentLibrary.page_text` answers the deterministic citation check and `search` the
agents' keyword search. Retrieved database records (e.g. a PubChem answer) are stored the same way, as role
``retrieved_record``, so a value taken from a database is quoted from exactly what the database returned.

The library's own record (docs/plans/2026-10-28-project-document-library.md, PR 2; the owner's answers 11 and 12 of
2026-10-29) is kept beside the artifacts in ``<root>/<tenant>/projects/<pid>/library.json``: what each document relates
to (a step and, optionally, a task) and whether a person withdrew it. A withdrawn document is never erased: the table
marks it, the values already taken from it keep their citation, and the agents' view of the library
(``DocumentLibrary(ws, for_agents=True)``) no longer lists, searches or reads it. It is not a new version of the
DOCUMENT artifact, because the brief and the client data derive from the documents and a new version would mark them
stale. Each change is an audit event with its reason, written atomically under a cross-process file lock.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from modeler_intake.documents import extract_document
from modeler_project.artifacts import ArtifactKind, ArtifactVersion
from modeler_project.workspace import Workspace
from pbpk_domain.atomic_io import atomic_write_text, file_lock

DocumentRole = Literal["proposal", "annex", "context", "client_file", "paper", "retrieved_record", "other"]
# the steps a document can relate to: `modeler_project.steps.StepId`, repeated so the library does not import the step rules
RelatedStep = Literal["start", "inputs", "review", "run"]
_WORD = re.compile(r"[a-z0-9µ%.]+")


class LibraryError(ValueError):
    """A library change the rules refuse (no reason given)."""


class RelatesTo(BaseModel):
    """What a document relates to, as the person adding it said: a step and, optionally, a task within it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    step: RelatedStep
    task: str = Field(default="", max_length=120)


class Withdrawal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    by: str
    at: str
    reason: str


class LibraryEntry(BaseModel):
    """The library's record of one document, beside its DOCUMENT artifact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    relates_to: RelatesTo | None = None
    withdrawn: Withdrawal | None = None


@dataclass(frozen=True)
class DocumentHit:
    """Same shape as `modeler_agents.parameter_curation.DocumentHit`, so the library serves those agents too."""

    doc_sha256: str
    title: str
    page: int
    snippet: str


def document_id(sha256: str) -> str:
    return f"doc-{sha256[:12]}"


class DocumentRecord(BaseModel):
    """DOCUMENT content: a stored file's metadata, the hash of its bytes and the hash of its page texts. This module is
    the kind's owner (phase 6, rule B3): readers take a document's name, pages or hash from here, not the stored JSON."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    kind: str
    media_type: str
    size_bytes: int
    sha256: str
    pages_sha256: str
    n_pages: int
    role: str
    warnings: tuple[str, ...]
    note: str

    def to_content(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def document_record(version: ArtifactVersion) -> DocumentRecord:
    return DocumentRecord.model_validate(version.content)


class DocumentLibrary:
    def __init__(self, ws: Workspace, *, for_agents: bool = False):
        """`for_agents`: the agents' view, without the documents a person withdrew (the owner's answer 12)."""
        self.ws = ws
        self.for_agents = for_agents
        self._pages: dict[str, list[str]] = {}
        root = getattr(ws.store, "root", None)
        self._ledger = Path(root) / ws.tenant_id / "projects" / ws.project_id / "library.json" if root else None

    def add(self, data: bytes, filename: str, *, role: DocumentRole, by: str, note: str = "",
            relates_to: RelatesTo | None = None) -> ArtifactVersion:
        """Store a file and its pages; uploading the same bytes again returns the existing document. `relates_to` is
        recorded either way: it is what the person adding it says now."""
        doc = extract_document(data, filename)
        existing = self.ws.latest(ArtifactKind.DOCUMENT, document_id(doc.sha256))
        if existing is not None:
            if relates_to is not None:
                self.relate(doc.sha256, relates_to, by=by)
            return existing
        store = self.ws.store
        store.put_blob(self.ws.tenant_id, self.ws.project_id, data)
        pages_json = json.dumps([p.text for p in doc.pages], ensure_ascii=False).encode("utf-8")
        pages_sha = store.put_blob(self.ws.tenant_id, self.ws.project_id, pages_json)
        record = DocumentRecord(name=doc.name, kind=doc.kind, media_type=doc.media_type, size_bytes=doc.size_bytes,
                                sha256=doc.sha256, pages_sha256=pages_sha, n_pages=len(doc.pages), role=role,
                                warnings=tuple(doc.warnings), note=note)
        version = self.ws.commit(ArtifactKind.DOCUMENT, document_id(doc.sha256), record.to_content(), actor=by,
                                 reason=f"uploaded {doc.name} ({role})")
        if relates_to is not None:
            self.relate(doc.sha256, relates_to, by=by)
        return version

    def add_text(self, text: str, name: str, *, role: DocumentRole, by: str, note: str = "") -> ArtifactVersion:
        return self.add(text.encode("utf-8"), name if name.endswith((".md", ".txt")) else f"{name}.md", role=role, by=by,
                        note=note)

    def documents(self) -> list[ArtifactVersion]:
        versions = self.ws.list(ArtifactKind.DOCUMENT)
        if not self.for_agents:
            return versions
        hidden = {sha for sha, entry in self.entries().items() if entry.withdrawn}
        return [v for v in versions if document_record(v).sha256 not in hidden]

    def by_sha(self, sha256: str) -> ArtifactVersion | None:
        if self.for_agents and self.entry(sha256).withdrawn:
            return None
        return self.ws.latest(ArtifactKind.DOCUMENT, document_id(sha256))

    # --- the library's record: what a document relates to, and withdrawal -----------------------------------

    def entries(self) -> dict[str, LibraryEntry]:
        if self._ledger is None or not self._ledger.exists():
            return {}
        rows = json.loads(self._ledger.read_text(encoding="utf-8"))["documents"]
        return {sha: LibraryEntry.model_validate(row) for sha, row in rows.items()}

    def entry(self, sha256: str) -> LibraryEntry:
        return self.entries().get(sha256, LibraryEntry())

    def _change(self, sha256: str, *, by: str, action: str, reason: str | None, **fields: Any) -> LibraryEntry:
        if self._ledger is None:
            raise LibraryError("this project store keeps no library record")
        with file_lock(self._ledger):
            entries = self.entries()
            before = entries.get(sha256, LibraryEntry())
            after = before.model_copy(update=fields)
            if after == before:
                return before
            entries[sha256] = after
            self._ledger.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(self._ledger, json.dumps(
                {"documents": {sha: e.model_dump(mode="json") for sha, e in sorted(entries.items())}},
                indent=1, sort_keys=True, ensure_ascii=False))
            self.ws.store.audit(self.ws.tenant_id).append(
                actor=by, action=action, resource_type="document",
                resource_id=f"{self.ws.project_id}/{document_id(sha256)}",
                before={k: before.model_dump(mode="json")[k] for k in fields},
                after={k: after.model_dump(mode="json")[k] for k in fields}, reason=reason)
        return after

    def _known(self, sha256: str) -> None:
        if self.ws.latest(ArtifactKind.DOCUMENT, document_id(sha256)) is None:
            raise KeyError(f"no document {sha256[:12]} in this project")

    def relate(self, sha256: str, relates_to: RelatesTo, *, by: str) -> LibraryEntry:
        """Record what a document relates to (answer 11: the roles, plus the step and task it relates to)."""
        self._known(sha256)
        return self._change(sha256, by=by, action="document.relate", reason=None, relates_to=relates_to)

    def withdraw(self, sha256: str, *, by: str, reason: str) -> LibraryEntry:
        """Withdraw a document with a reason (answer 12): hidden from the agents and marked, never erased."""
        self._known(sha256)
        if not reason.strip():
            raise LibraryError("say why the document is withdrawn (the reason is kept in the audit trail)")
        if self.entry(sha256).withdrawn:
            return self.entry(sha256)
        return self._change(sha256, by=by, action="document.withdraw", reason=reason.strip(),
                            withdrawn=Withdrawal(by=by, at=datetime.now(UTC).isoformat(), reason=reason.strip()))

    def restore(self, sha256: str, *, by: str, reason: str) -> LibraryEntry:
        """Put a withdrawn document back in use, with a reason."""
        self._known(sha256)
        if not reason.strip():
            raise LibraryError("say why the document is restored (the reason is kept in the audit trail)")
        return self._change(sha256, by=by, action="document.restore", reason=reason.strip(), withdrawn=None)

    def pages(self, sha256: str) -> list[str]:
        if self.for_agents and self.entry(sha256).withdrawn:
            return []
        if sha256 not in self._pages:
            version = self.by_sha(sha256)
            if version is None:
                return []
            path = self.ws.store.blob_path(self.ws.tenant_id, self.ws.project_id, document_record(version).pages_sha256)
            self._pages[sha256] = json.loads(path.read_text(encoding="utf-8")) if path else []
        return self._pages[sha256]

    # --- the DocumentStore protocol the agents use ------------------------------------------------------------

    def page_text(self, doc_sha256: str, page: int) -> str | None:
        pages = self.pages(doc_sha256)
        return pages[page - 1] if 0 < page <= len(pages) else None

    def search(self, query: str, max_results: int = 8) -> list[DocumentHit]:
        """Keyword search over every page: pages ranked by how many query words they contain, then by frequency."""
        words = [w for w in _WORD.findall(query.lower()) if len(w) > 1]
        if not words:
            return []
        scored: list[tuple[int, int, str, int, str, str]] = []
        for version in self.documents():
            record = document_record(version)
            sha = record.sha256
            for number, text in enumerate(self.pages(sha), start=1):
                lowered = text.lower()
                present = [w for w in words if w in lowered]
                if not present:
                    continue
                count = sum(lowered.count(w) for w in present)
                first = min(lowered.find(w) for w in present)
                snippet = text[max(0, first - 120): first + 240].replace("\n", " ")
                scored.append((-len(present), -count, sha, number, record.name, snippet))
        scored.sort()
        return [DocumentHit(doc_sha256=sha, title=name, page=page, snippet=snippet)
                for _, _, sha, page, name, snippet in scored[:max_results]]
