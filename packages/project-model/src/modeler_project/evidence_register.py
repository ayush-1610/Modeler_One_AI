"""Working with the evidence register: propose, decide, see conflicts and coverage, close the phase (plan §5.2 P2).

Evidence items are EVIDENCE artifacts (one per item, a new version per decision). Conflicts and coverage are computed
when read, from the latest versions, so they always reflect the current state. The phase register
(EVIDENCE/register-literature) is a snapshot of the accepted items and the coverage at approval time, derived from
the data plan and from each accepted item's version: a later change to any of them makes the approved register stale.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from modeler_project.artifacts import ArtifactKind
from modeler_project.evidence import EvidenceItem, EvidenceState, assess, flag_conflicts
from modeler_project.requirements import RequirementItem, RequirementMatrix, literature_items
from modeler_project.workspace import Workspace

REGISTER_LITERATURE = "register-literature"


class EvidenceError(ValueError):
    pass


def items(ws: Workspace) -> list[EvidenceItem]:
    """Latest version of every evidence item, with conflicts flagged."""
    loaded = [EvidenceItem.from_content(v.content) for v in ws.list(ArtifactKind.EVIDENCE) if v.id.startswith("ev-")]
    return flag_conflicts(sorted(loaded, key=lambda i: (i.target, i.proposed_at)))


def propose(ws: Workspace, item: EvidenceItem, *, actor: str, requirement: RequirementItem | None = None,
            value_in_quote: bool | None = None) -> EvidenceItem:
    """Grade and store a new proposal (PROPOSED)."""
    if ws.latest(ArtifactKind.EVIDENCE, item.id) is not None:
        raise EvidenceError(f"evidence {item.id} already exists")
    assessed = assess(item, required_conditions=requirement.conditions if requirement else (), value_in_quote=value_in_quote)
    assessed = assessed.model_copy(update={"state": EvidenceState.PROPOSED, "proposed_by": actor})
    ws.commit(ArtifactKind.EVIDENCE, item.id, assessed.to_content(), actor=actor,
              reason=f"proposed {item.target} = {item.value} {item.unit or ''}".strip())
    return assessed


def decide(ws: Workspace, evidence_id: str, *, state: EvidenceState, reason: str, by: str,
           value_pksim: float | None = None, unit_pksim: str | None = None) -> EvidenceItem:
    """A person accepts or rejects a proposal (or reopens it). Accepting may set the PK-Sim value by hand, e.g. when the
    unit change was not automatic; that is recorded as the conversion."""
    version = ws.latest(ArtifactKind.EVIDENCE, evidence_id)
    if version is None:
        raise EvidenceError(f"no evidence {evidence_id}")
    if not reason.strip():
        raise EvidenceError("a decision needs a reason")
    item = EvidenceItem.from_content(version.content)
    update: dict[str, Any] = {"state": state, "decided_by": by, "decided_at": datetime.now(UTC), "decision_reason": reason}
    if value_pksim is not None:
        update.update(value_pksim=value_pksim, unit_pksim=unit_pksim,
                      conversion=f"set by {by} on acceptance: {value_pksim:g} {unit_pksim or ''}".strip(),
                      flags=tuple(f for f in item.flags if not f.startswith("needs_conversion")))
    if state is EvidenceState.ACCEPTED and update.get("value_pksim", item.value_pksim) is None and isinstance(item.value, int | float):
        raise EvidenceError(f"{item.target}: give the value in the PK-Sim unit to accept it ({'; '.join(item.flags)})")
    decided = item.model_copy(update=update)
    ws.commit(ArtifactKind.EVIDENCE, evidence_id, decided.to_content(), actor=by, reason=f"{state.value.lower()}: {reason}")
    return decided


@dataclass(frozen=True)
class Coverage:
    req_id: str
    label: str
    target: str
    criticality: str
    applies: str
    provider: str
    status: str                 # ACCEPTED | PROPOSED | CONFLICTING | NOT_FOUND | NOT_AVAILABLE | WAIVED
    accepted: tuple[str, ...]
    proposed: tuple[str, ...]


def _matches(requirement: RequirementItem, item: EvidenceItem) -> bool:
    if item.req_id:
        return item.req_id == requirement.req_id
    base = requirement.target.split("{", 1)[0].rstrip(".")
    return item.target == requirement.target or item.target.startswith(base + ".") or item.target == base


def coverage(matrix: RequirementMatrix, evidence: list[EvidenceItem]) -> list[Coverage]:
    """For every literature item of the data plan: what was found, accepted, or not found."""
    out = []
    for requirement in literature_items(matrix):
        mine = [e for e in evidence if _matches(requirement, e)]
        accepted = tuple(e.id for e in mine if e.state is EvidenceState.ACCEPTED)
        proposed = tuple(e.id for e in mine if e.state is EvidenceState.PROPOSED)
        if requirement.status in ("NOT_AVAILABLE", "WAIVED"):
            status = requirement.status
        elif accepted:
            status = "ACCEPTED"
        elif any(any(f.startswith("conflict") for f in e.flags) for e in mine if e.state is EvidenceState.PROPOSED):
            status = "CONFLICTING"
        elif proposed:
            status = "PROPOSED"
        else:
            status = "NOT_FOUND"
        out.append(Coverage(req_id=requirement.req_id, label=requirement.label, target=requirement.target,
                            criticality=requirement.criticality, applies=requirement.applies, provider=requirement.provider,
                            status=status, accepted=accepted, proposed=proposed))
    return out


def blocking(rows: list[Coverage]) -> list[Coverage]:
    """Required, applicable literature items with nothing accepted and not marked not available (plan P2 gate)."""
    return [r for r in rows if r.criticality == "REQUIRED" and r.applies == "yes" and r.provider == "LITERATURE"
            and r.status not in ("ACCEPTED", "NOT_AVAILABLE", "WAIVED")]


def close_register(ws: Workspace, matrix_ref, matrix: RequirementMatrix, *, by: str, note: str = "",
                   printed_name: str = "") -> None:
    """Snapshot the accepted literature evidence and approve it (named approval, D-07)."""
    evidence = items(ws)
    rows = coverage(matrix, evidence)
    gaps = blocking(rows)
    if gaps:
        raise EvidenceError("required literature items still open: " + ", ".join(r.req_id for r in gaps))
    accepted = [ws.latest(ArtifactKind.EVIDENCE, e.id) for e in evidence if e.state is EvidenceState.ACCEPTED
                and e.provider == "LITERATURE"]
    content = {"accepted": [v.ref.model_dump(mode="json") for v in accepted],
               "coverage": [r.__dict__ | {"accepted": list(r.accepted), "proposed": list(r.proposed)} for r in rows]}
    version = ws.commit(ArtifactKind.EVIDENCE, REGISTER_LITERATURE, content,
                        derived_from=[matrix_ref, *[v.ref for v in accepted]], actor=by, reason="literature evidence closed")
    ws.approve(version.ref, by=by, printed_name=printed_name, meaning="Reviewed", note=note)


def request_access(ws: Workspace, *, title: str, authors: str, doi: str | None, journal: str | None, year: int | None,
                   needed_for: str, by: str) -> tuple[str, bool]:
    """File a request for a paper the tools cannot read legally (deduplicated by DOI or title)."""
    key = (doi or title).strip().lower()
    for version in ws.list(ArtifactKind.ACCESS_REQUEST):
        if (version.content.get("doi") or version.content["title"]).strip().lower() == key:
            return version.id, False
    request_id = f"acc-{uuid.uuid4().hex[:8]}"
    ws.commit(ArtifactKind.ACCESS_REQUEST, request_id, {"title": title, "authors": authors, "doi": doi, "journal": journal,
                                                        "year": year, "needed_for": needed_for, "status": "OPEN",
                                                        "fulfilled_by": None}, actor=by, reason="full text needed")
    return request_id, True


def fulfil_access(ws: Workspace, request_id: str, *, doc_sha256: str, by: str) -> None:
    version = ws.latest(ArtifactKind.ACCESS_REQUEST, request_id)
    if version is None:
        raise EvidenceError(f"no access request {request_id}")
    ws.commit(ArtifactKind.ACCESS_REQUEST, request_id, {**version.content, "status": "FULFILLED", "fulfilled_by": doc_sha256},
              actor=by, reason="full text supplied")
