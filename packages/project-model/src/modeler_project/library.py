"""The project document library as a table (docs/plans/2026-10-28-project-document-library.md, PR 1; the owner's
decisions 10–13 of 2026-10-29).

One row per stored document: its name, who added it (a person, an agent or the system), its role, format and pages,
its versions, and what it contributed to the project. The contribution is computed, never typed: the evidence values,
the observed datasets and the brief fields that cite the document, each with its value and where it is used. A document
nothing cites says so. The library itself is `modeler_project.documents` (one per project, write-once blobs, audited).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from modeler_project.artifacts import ArtifactKind
from modeler_project.brief import ProjectBrief
from modeler_project.dataset_register import datasets
from modeler_project.documents import DocumentLibrary, document_id, document_record
from modeler_project.evidence_register import items as evidence_items
from modeler_project.workspace import Workspace

Used = Literal["value", "dataset", "brief"]


class Contribution(BaseModel):
    """One thing the project took from a document."""

    model_config = ConfigDict(frozen=True)

    kind: Used                     # an evidence value, an observed dataset, a brief field
    target: str                    # the CPF id, the study, the brief path
    value: str                     # as stated, with its unit
    state: str                     # PROPOSED / ACCEPTED / REJECTED, or the brief field's status
    page: int | None = None
    step: Literal["start", "inputs"] = "inputs"


class LibraryRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    sha256: str
    name: str
    role: str
    format: str                    # the file kind (pdf, docx, xlsx, md…)
    n_pages: int
    size_bytes: int
    added_at: str
    added_by: str
    source: Literal["person", "agent", "system"]
    versions: int
    contributions: tuple[Contribution, ...]


def _source(by: str) -> Literal["person", "agent", "system"]:
    return "agent" if by.startswith("agent:") else "system" if by == "system" else "person"


def _shown(value: Any, unit: str | None) -> str:
    one = lambda v: f"{v:g}" if isinstance(v, float) else str(v)
    text = "; ".join(map(one, value)) if isinstance(value, list | tuple) else one(value)
    return f"{text} {unit}".strip() if unit else text


def _brief_citations(brief: ProjectBrief) -> list[tuple[str, Contribution]]:
    out = []
    records = [(path, record) for path, record in brief.fields.items()]
    records += [(f"{group}[{i}].{field}", record) for group, rows in brief.groups.items() for i, row in enumerate(rows)
                for field, record in row.items()]
    for path, record in records:
        for c in record.citations:
            out.append((c.doc_sha256, Contribution(kind="brief", target=path, value=_shown(record.value, record.unit),
                                                   state=record.status.value, page=c.page, step="start")))
    return out


def library_rows(ws: Workspace) -> list[LibraryRow]:
    """Every document of the project, oldest first, with what cites it."""
    cited: dict[str, list[Contribution]] = defaultdict(list)
    for item in evidence_items(ws):
        if item.source.doc_sha256:
            cited[item.source.doc_sha256].append(Contribution(
                kind="value", target=item.target, value=_shown(item.value, item.unit), state=item.state.value,
                page=item.source.page))
    for observed in datasets(ws):
        if observed.source.doc_sha256:
            series = len(observed.series) or len(observed.reported)
            cited[observed.source.doc_sha256].append(Contribution(
                kind="dataset", target=str(observed.study.get("study_id", observed.id)),
                value=f"concentration profile, {series} series" if observed.kind == "profile"
                else f"{len(observed.reported)} PK parameters", state=observed.state.value, page=observed.source.page))
    brief = ws.latest(ArtifactKind.BRIEF, "main")
    if brief is not None:
        for sha, contribution in _brief_citations(ProjectBrief.from_content(brief.content)):
            cited[sha].append(contribution)
    rows = []
    for version in DocumentLibrary(ws).documents():
        record = document_record(version)
        history = ws.versions(ArtifactKind.DOCUMENT, document_id(record.sha256))
        first = history[0] if history else version
        rows.append(LibraryRow(
            sha256=record.sha256, name=record.name, role=record.role, format=record.kind, n_pages=record.n_pages,
            size_bytes=record.size_bytes, added_at=first.created_at.isoformat(), added_by=first.created_by,
            source=_source(first.created_by), versions=len(history) or 1, contributions=tuple(cited.get(record.sha256, ()))))
    return sorted(rows, key=lambda r: r.added_at)
