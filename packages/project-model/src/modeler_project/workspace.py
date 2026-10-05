"""One project's artifacts: commit, approve, staleness, impact preview, phase status, history (plan §13).

Rules:
- A commit creates the next version of an artifact; re-committing identical content with identical upstream refs is a
  no-op (returns the current version), so deterministic re-derivation does not create empty versions.
- A version is STALE when any upstream version it names is no longer the latest of its artifact, or is itself stale.
  Staleness is computed, never stored: it cannot drift from the facts.
- Approval binds a version's content hash. A stale or superseded version cannot be approved.
- Every commit and approval is an audit event on the tenant's hash chain.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from modeler_project.artifacts import (
    PHASE_OF,
    Approval,
    ArtifactKind,
    ArtifactRef,
    ArtifactStatus,
    ArtifactVersion,
    content_sha256,
)
from modeler_project.diff import Change, diff
from modeler_project.store import ProjectStore


class PhaseStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    IN_REVIEW = "IN_REVIEW"      # produced, not approved yet
    APPROVED = "APPROVED"
    STALE = "STALE"              # approved or drafted on inputs that have since changed


# The artifacts whose approval closes each phase (plan §16). `None` as id: any artifact of that kind counts.
PHASE_GATES: dict[str, tuple[tuple[ArtifactKind, str | None], ...]] = {
    "P0": ((ArtifactKind.DOCUMENT, None),),
    "P1": ((ArtifactKind.BRIEF, "main"), (ArtifactKind.REQUIREMENTS, "main")),
    "P2": ((ArtifactKind.EVIDENCE, "register-literature"),),
    "P3": ((ArtifactKind.CLIENT_SUBMISSION, "register"),),
    "P4": ((ArtifactKind.READINESS, "main"),),
    "P5": ((ArtifactKind.MODEL_PLAN, "main"), (ArtifactKind.MAP, "main")),
    "P6": ((ArtifactKind.CAMPAIGN, None),),
}
PHASE_LABELS = {
    "P0": "Initiate", "P1": "Brief & data plan", "P2": "Literature", "P3": "Client data",
    "P4": "Model inputs", "P5": "Model plan", "P6": "Run",
}
# Kinds that need no approval: a document is a fact (its bytes), a campaign is judged by its own gates.
_NO_APPROVAL = {ArtifactKind.DOCUMENT, ArtifactKind.CAMPAIGN}

# What a change upstream means for each kind of dependent (plan §13.3).
_EFFECT = {
    ArtifactKind.BRIEF: "re-review the brief",
    ArtifactKind.REQUIREMENTS: "re-derive the data plan (automatic), then re-approve",
    ArtifactKind.FEASIBILITY: "re-run the feasibility check (automatic)",
    ArtifactKind.EVIDENCE: "re-review the evidence",
    ArtifactKind.ACCESS_REQUEST: "none (a request for a paper)",
    ArtifactKind.DATASET: "re-review the dataset",
    ArtifactKind.CLIENT_SUBMISSION: "re-review the client data and its reconciliation",
    ArtifactKind.DISSOLUTION: "re-fit the release model (automatic), then re-review",
    ArtifactKind.CPF: "re-assemble the CPF (automatic, new version)",
    ArtifactKind.STUDY_CATALOG: "re-assemble the study catalog (automatic)",
    ArtifactKind.READINESS: "re-run the S0 readiness check",
    ArtifactKind.MODEL_PLAN: "review on the canvas",
    ArtifactKind.MAP: "regenerate the MAP from the plan",
    ArtifactKind.CAMPAIGN: "results stale: continue (re-run the affected stages) or restart",
    ArtifactKind.DOCUMENT: "none (documents are immutable)",
}


@dataclass(frozen=True)
class StaleItem:
    ref: ArtifactRef
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ImpactItem:
    ref: ArtifactRef
    status: ArtifactStatus
    effect: str
    needs_signature: bool   # an approved/signed version will be superseded and must be signed again


@dataclass(frozen=True)
class ImpactReport:
    target: ArtifactRef | None          # the version that would be replaced (None: a new artifact)
    changes: tuple[Change, ...]
    affected: tuple[ImpactItem, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def unchanged(self) -> bool:
        return not self.changes


class Workspace:
    """The artifacts of one project of one tenant."""

    def __init__(self, store: ProjectStore, tenant_id: str, project_id: str):
        self.store = store
        self.tenant_id = tenant_id
        self.project_id = project_id

    # --- reads ------------------------------------------------------------------------------------------------

    def versions(self, kind: ArtifactKind, artifact_id: str) -> list[ArtifactVersion]:
        return self.store.versions(self.tenant_id, self.project_id, kind, artifact_id)

    def latest(self, kind: ArtifactKind, artifact_id: str) -> ArtifactVersion | None:
        versions = self.versions(kind, artifact_id)
        return versions[-1] if versions else None

    def get(self, ref: ArtifactRef) -> ArtifactVersion | None:
        versions = self.versions(ref.kind, ref.id)
        return versions[ref.version - 1] if 0 < ref.version <= len(versions) else None

    def list(self, kind: ArtifactKind | None = None) -> list[ArtifactVersion]:
        """The latest version of every artifact (of `kind`)."""
        out = []
        for k, artifact_id in self.store.keys(self.tenant_id, self.project_id, kind):
            latest = self.latest(k, artifact_id)
            if latest is not None:
                out.append(latest)
        return out

    def approvals_of(self, ref: ArtifactRef) -> list[Approval]:
        return [a for a in self.store.approvals(self.tenant_id, self.project_id) if a.ref == ref]

    # --- commit and approve -----------------------------------------------------------------------------------

    def commit(self, kind: ArtifactKind, artifact_id: str, content: dict[str, Any], *,
               derived_from: Iterable[ArtifactRef] = (), actor: str, reason: str,
               request_id: str | None = None) -> ArtifactVersion:
        """Store `content` as the next version of the artifact (or return the current one if nothing changed)."""
        upstream = tuple(derived_from)
        latest = self.latest(kind, artifact_id)
        if latest is not None and latest.sha256 == content_sha256(content) and latest.derived_from == upstream:
            return latest
        if latest is not None and not reason.strip():
            raise ValueError(f"{kind.value}/{artifact_id}: a new version needs a reason")
        version = ArtifactVersion.create(
            kind=kind, id=artifact_id, version=(latest.version + 1) if latest else 1, content=content,
            derived_from=upstream, created_by=actor, reason=reason,
        )
        self.store.put(self.tenant_id, self.project_id, version)
        self.store.audit(self.tenant_id).append(
            actor=actor, action="artifact.revise" if latest else "artifact.create", resource_type=kind.value,
            resource_id=f"{self.project_id}/{artifact_id}@v{version.version}",
            before=latest.sha256 if latest else None, after=version.sha256, reason=reason or None, request_id=request_id,
        )
        return version

    def approve(self, ref: ArtifactRef, *, by: str, printed_name: str = "", meaning: str = "Reviewed",
                signature_id: str | None = None, note: str = "", request_id: str | None = None) -> Approval:
        version = self.get(ref)
        if version is None:
            raise KeyError(f"no such version: {ref.label()}")
        status = self.status(version)
        if status is ArtifactStatus.SUPERSEDED:
            raise ValueError(f"{ref.label()} is superseded; approve the latest version")
        if status is ArtifactStatus.STALE:
            reasons = "; ".join(self.stale_reasons(version))
            raise ValueError(f"{ref.label()} is stale ({reasons}); bring it up to date before approving")
        approval = Approval(ref=ref, record_sha256=version.sha256, meaning=meaning, by=by, printed_name=printed_name,
                            signature_id=signature_id, note=note)
        self.store.add_approval(self.tenant_id, self.project_id, approval)
        self.store.audit(self.tenant_id).append(
            actor=by, action="artifact.approve", resource_type=ref.kind.value,
            resource_id=f"{self.project_id}/{ref.id}@v{ref.version}", after=version.sha256,
            reason=f"{meaning}{f': {note}' if note else ''}", request_id=request_id,
        )
        return approval

    # --- status and staleness ---------------------------------------------------------------------------------

    def stale_reasons(self, version: ArtifactVersion, _seen: frozenset | None = None) -> list[str]:
        seen = (_seen or frozenset()) | {version.ref.key}
        reasons: list[str] = []
        for up in version.derived_from:
            latest = self.latest(up.kind, up.id)
            if latest is None:
                reasons.append(f"{up.label()} no longer exists")
            elif latest.version > up.version:
                why = f" ({latest.reason})" if latest.reason else ""
                reasons.append(f"{up.kind.value}/{up.id} changed: v{up.version} → v{latest.version}{why}")
            elif up.key not in seen and self.stale_reasons(latest, seen):
                reasons.append(f"{up.label()} is itself stale")
        return reasons

    def status(self, version: ArtifactVersion) -> ArtifactStatus:
        latest = self.latest(version.kind, version.id)
        if latest is not None and latest.version > version.version:
            return ArtifactStatus.SUPERSEDED
        if self.stale_reasons(version):
            return ArtifactStatus.STALE
        if any(a.record_sha256 == version.sha256 for a in self.approvals_of(version.ref)):
            return ArtifactStatus.APPROVED
        return ArtifactStatus.DRAFT

    def stale(self) -> list[StaleItem]:
        out = []
        for version in self.list():
            reasons = self.stale_reasons(version)
            if reasons:
                out.append(StaleItem(ref=version.ref, reasons=tuple(reasons)))
        return out

    # --- dependents and impact --------------------------------------------------------------------------------

    def dependents(self, kind: ArtifactKind, artifact_id: str) -> list[ArtifactVersion]:
        """Latest versions that name any version of (kind, id) upstream, directly."""
        return [v for v in self.list() if any(up.key == (kind, artifact_id) for up in v.derived_from)]

    def impact(self, kind: ArtifactKind, artifact_id: str, new_content: dict[str, Any]) -> ImpactReport:
        """What saving `new_content` as the next version would change, without saving it (plan §13.2)."""
        latest = self.latest(kind, artifact_id)
        changes = tuple(diff(latest.content if latest else {}, new_content))
        if latest is None:
            return ImpactReport(target=None, changes=changes, affected=(), notes=("a new artifact: nothing depends on it yet",))
        if not changes:
            return ImpactReport(target=latest.ref, changes=(), affected=(), notes=("no change",))
        affected: list[ImpactItem] = []
        queue = [(kind, artifact_id)]
        visited = {(kind, artifact_id)}
        while queue:
            key = queue.pop(0)
            for dep in self.dependents(*key):
                if dep.ref.key in visited:
                    continue
                visited.add(dep.ref.key)
                status = self.status(dep)
                signed = any(a.signature_id for a in self.approvals_of(dep.ref) if a.record_sha256 == dep.sha256)
                approved = status is ArtifactStatus.APPROVED
                effect = _EFFECT.get(dep.kind, "review")
                if dep.kind is ArtifactKind.MAP and approved:
                    effect = "superseded when revised: the new version must be signed; campaigns bound to it are invalidated"
                affected.append(ImpactItem(ref=dep.ref, status=status, effect=effect, needs_signature=signed or (
                    approved and dep.kind in (ArtifactKind.MAP, ArtifactKind.MODEL_PLAN))))
                queue.append(dep.ref.key)
        return ImpactReport(target=latest.ref, changes=changes, affected=tuple(affected))

    # --- phases -----------------------------------------------------------------------------------------------

    def phases(self) -> dict[str, PhaseStatus]:
        """Each phase's status from its gate artifacts (plan §16)."""
        out: dict[str, PhaseStatus] = {}
        for phase, gates in PHASE_GATES.items():
            statuses: list[PhaseStatus] = []
            for kind, artifact_id in gates:
                if artifact_id is None:
                    present = self.list(kind)
                    statuses.append(PhaseStatus.APPROVED if present else PhaseStatus.NOT_STARTED)
                    continue
                version = self.latest(kind, artifact_id)
                if version is None:
                    statuses.append(PhaseStatus.NOT_STARTED)
                    continue
                status = self.status(version)
                if status is ArtifactStatus.STALE:
                    statuses.append(PhaseStatus.STALE)
                elif status is ArtifactStatus.APPROVED or kind in _NO_APPROVAL:
                    statuses.append(PhaseStatus.APPROVED)
                else:
                    statuses.append(PhaseStatus.IN_REVIEW)
            out[phase] = _worst(statuses)
        return out

    def history(self, kind: ArtifactKind, artifact_id: str) -> list[dict[str, Any]]:
        """Every version with its status, approvals and the field changes from the previous version."""
        versions = self.versions(kind, artifact_id)
        rows = []
        previous: dict[str, Any] = {}
        for version in versions:
            rows.append({
                "ref": version.ref,
                "sha256": version.sha256,
                "status": self.status(version),
                "created_at": version.created_at,
                "created_by": version.created_by,
                "reason": version.reason,
                "phase": PHASE_OF[kind],
                "approvals": self.approvals_of(version.ref),
                "changes": diff(previous, version.content),
            })
            previous = version.content
        return rows


def _worst(statuses: list[PhaseStatus]) -> PhaseStatus:
    """A phase is as far as its least advanced gate: nothing yet → not started; anything stale → stale; anything
    missing or unapproved → in review; else approved."""
    if not statuses or all(s is PhaseStatus.NOT_STARTED for s in statuses):
        return PhaseStatus.NOT_STARTED
    if PhaseStatus.STALE in statuses:
        return PhaseStatus.STALE
    if PhaseStatus.NOT_STARTED in statuses or PhaseStatus.IN_REVIEW in statuses:
        return PhaseStatus.IN_REVIEW
    return PhaseStatus.APPROVED
