"""Values another project of the same drug found, reused here with the person's consent (plan 2026-11-05 §3.3: "reuse
what other projects of the same drug found (with the person's consent per project)").

Only what the literature and the public sources gave (publications, regulatory reviews, databases such as PubChem, the
FDA label and ChEMBL, the OSP library) is offered; a client's data never leaves its project. Each value is proposed
here anew, graded again like any proposal, with its original source, quote and locator; the document its quote is in is
copied into this project's library (stored by its content hash, so the quote still resolves here). The note says where
it came from and who chose to reuse it. Nothing is accepted by the reuse: a person decides each value here, as always.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from modeler_project.brief import ProjectBrief
from modeler_project.documents import DocumentLibrary, document_record
from modeler_project.evidence import EvidenceItem, EvidenceState, SourceType, new_id
from modeler_project.evidence_register import items, propose
from modeler_project.requirements import RequirementItem
from modeler_project.workspace import Workspace

REUSABLE = frozenset({SourceType.PUBLICATION, SourceType.REGULATORY_REVIEW, SourceType.DATABASE, SourceType.OSP_LIBRARY})


def same_drug(a: ProjectBrief | None, b: ProjectBrief | None) -> bool:
    """The same compound: the same InChIKey when both projects have one, else the same name (case and spacing aside)."""
    if a is None or b is None:
        return False
    keys = [str(x.value("drug.inchikey") or "").strip().upper() for x in (a, b)]
    if all(keys):
        return keys[0] == keys[1]
    names = [" ".join(x.drug_name.lower().split()) for x in (a, b)]
    return bool(names[0]) and names[0] == names[1]


def _key(e: EvidenceItem) -> tuple[str, ...]:
    where = e.source.doi or e.source.pmid or e.source.doc_sha256 or e.source.url or e.source.title
    return (e.target, str(e.value), e.unit or "", where or "", " ".join(e.quote.split()))


def offered(here: Workspace, other: Workspace) -> list[EvidenceItem]:
    """The other project's literature and public-source values (not rejected) this project does not hold yet."""
    held = {_key(e) for e in items(here)}
    return [e for e in items(other) if e.provider == "LITERATURE" and e.source_type in REUSABLE
            and e.state is not EvidenceState.REJECTED and _key(e) not in held]


def summary(values: list[EvidenceItem]) -> list[str]:
    """What the values are, for the offer: "logP (PubChem)", "fu (a publication)" …"""
    out: dict[str, None] = {}
    for e in values:
        source = e.source.title or e.source_type.value.replace("_", " ").lower()
        out[f"{e.target} ({source})"] = None
    return list(out)


def reuse(here: Workspace, other: Workspace, *, project_name: str, by: str,
          requirements: Mapping[str, RequirementItem] | None = None) -> list[str]:
    """Propose here each value `offered` from `other`, with its document copied; the ids of the new proposals."""
    library, theirs = DocumentLibrary(here), DocumentLibrary(other)
    records = {r.sha256: r for r in map(document_record, theirs.documents())}
    mine = {r.sha256 for r in map(document_record, library.documents())}
    made = []
    for e in offered(here, other):
        sha = e.source.doc_sha256
        if sha and sha not in mine:
            if sha not in records:
                continue                         # its document is not in the other project's library: not reused
            path = other.store.blob_path(other.tenant_id, other.project_id, sha)
            if path is None:
                continue                         # the quote's document is not in the store: the value is not offered
            record = records[sha]
            library.add(path.read_bytes(), record.name, role=record.role, by=by,  # type: ignore[arg-type]
                        note=f"copied from project {project_name} ({other.project_id}) with the value(s) reused from it")
            mine.add(sha)
        note = (f"reused from project {project_name} ({other.project_id}, {e.id}) with {by}'s consent"
                + (f"; {e.note}" if e.note else ""))
        copy = e.model_copy(update={"id": new_id(), "state": EvidenceState.PROPOSED, "decided_by": None,
                                    "decided_at": None, "decision_reason": "", "note": note})
        made.append(propose(here, copy, actor=by, requirement=(requirements or {}).get(e.req_id or "")).id)
    return made


def offer_view(here: Workspace, other: Workspace, *, name: str) -> dict[str, Any] | None:
    """One other project's offer, or None when it has nothing new for this one."""
    values = offered(here, other)
    if not values:
        return None
    return {"project_id": other.project_id, "name": name, "values": len(values), "what": summary(values)[:12]}
