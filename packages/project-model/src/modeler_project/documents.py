"""The project's document library: uploaded files as DOCUMENT artifacts with quotable pages (plan P0, §6, §8).

The raw bytes go to the write-once blob store under their SHA-256; the extracted page texts go to a second blob; the
DOCUMENT artifact (id ``doc-<first 12 hex of the sha>``) records the metadata and both hashes. Agents and people cite
``(doc_sha256, page, quote)``; `DocumentLibrary.page_text` answers the deterministic citation check and `search` the
agents' keyword search. Retrieved database records (e.g. a PubChem answer) are stored the same way, as role
``retrieved_record``, so a value taken from a database is quoted from exactly what the database returned.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from modeler_intake.documents import extract_document
from modeler_project.artifacts import ArtifactKind, ArtifactVersion
from modeler_project.workspace import Workspace

DocumentRole = Literal["proposal", "annex", "context", "client_file", "paper", "retrieved_record", "other"]
_WORD = re.compile(r"[a-z0-9µ%.]+")


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
    def __init__(self, ws: Workspace):
        self.ws = ws
        self._pages: dict[str, list[str]] = {}

    def add(self, data: bytes, filename: str, *, role: DocumentRole, by: str, note: str = "") -> ArtifactVersion:
        """Store a file and its pages; uploading the same bytes again returns the existing document."""
        doc = extract_document(data, filename)
        existing = self.ws.latest(ArtifactKind.DOCUMENT, document_id(doc.sha256))
        if existing is not None:
            return existing
        store = self.ws.store
        store.put_blob(self.ws.tenant_id, self.ws.project_id, data)
        pages_json = json.dumps([p.text for p in doc.pages], ensure_ascii=False).encode("utf-8")
        pages_sha = store.put_blob(self.ws.tenant_id, self.ws.project_id, pages_json)
        record = DocumentRecord(name=doc.name, kind=doc.kind, media_type=doc.media_type, size_bytes=doc.size_bytes,
                                sha256=doc.sha256, pages_sha256=pages_sha, n_pages=len(doc.pages), role=role,
                                warnings=tuple(doc.warnings), note=note)
        return self.ws.commit(ArtifactKind.DOCUMENT, document_id(doc.sha256), record.to_content(), actor=by,
                              reason=f"uploaded {doc.name} ({role})")

    def add_text(self, text: str, name: str, *, role: DocumentRole, by: str, note: str = "") -> ArtifactVersion:
        return self.add(text.encode("utf-8"), name if name.endswith((".md", ".txt")) else f"{name}.md", role=role, by=by,
                        note=note)

    def documents(self) -> list[ArtifactVersion]:
        return self.ws.list(ArtifactKind.DOCUMENT)

    def by_sha(self, sha256: str) -> ArtifactVersion | None:
        return self.ws.latest(ArtifactKind.DOCUMENT, document_id(sha256))

    def pages(self, sha256: str) -> list[str]:
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
