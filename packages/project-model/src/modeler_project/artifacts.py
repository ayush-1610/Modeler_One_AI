"""Artifact versions: the unit every project phase produces (plan §13.1).

An `ArtifactVersion` is immutable: kind, id, version number, the content (a JSON object), its SHA-256, and the exact
upstream versions it was derived from. Approval is recorded separately (an `Approval` bound to the version's hash),
so approving never rewrites the version it approves.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ArtifactKind(StrEnum):
    """What a phase produces (plan §5.2). Order follows the phases."""

    DOCUMENT = "document"            # P0: an uploaded file (raw bytes in the vault; content = metadata + page index)
    BRIEF = "brief"                  # P1: the Project Brief (§6)
    REQUIREMENTS = "requirements"    # P1: the requirement matrix / data plan (§7)
    FEASIBILITY = "feasibility"      # P1/P4: what the PK-Sim builder can and cannot produce for this brief (§7.5)
    EVIDENCE = "evidence"            # P2/P3: one proposed or accepted value or dataset with its source (§8)
    DATASET = "dataset"              # P2/P3: an observed dataset (clinical profile, PK parameters) with its origin (§9)
    CLIENT_SUBMISSION = "client_submission"  # P3: client files, recipes and the reconciliation (§10)
    DISSOLUTION = "dissolution"      # P3: a canonical dissolution profile and its release-model fit (§10.3)
    CPF = "cpf"                      # P4: the compound parameter framework assembled from accepted evidence
    STUDY_CATALOG = "study_catalog"  # P4: the studies the plan can assign (StudyRecord per dataset)
    READINESS = "readiness"          # P4: S0 completeness + PK-Sim dry run
    MODEL_PLAN = "model_plan"        # P5: assignments, structure choices, rationale, canvas layout (§11)
    MAP = "map"                      # P5: the Model Analysis Plan generated from the approved model plan
    CAMPAIGN = "campaign"            # P6: a campaign run against a signed MAP


# The phase each kind belongs to (plan §5.1). P6 campaigns live in the runner's own store and are linked by reference.
PHASE_OF: dict[ArtifactKind, str] = {
    ArtifactKind.DOCUMENT: "P0",
    ArtifactKind.BRIEF: "P1",
    ArtifactKind.REQUIREMENTS: "P1",
    ArtifactKind.FEASIBILITY: "P1",
    ArtifactKind.EVIDENCE: "P2",
    ArtifactKind.DATASET: "P2",
    ArtifactKind.CLIENT_SUBMISSION: "P3",
    ArtifactKind.DISSOLUTION: "P3",
    ArtifactKind.CPF: "P4",
    ArtifactKind.STUDY_CATALOG: "P4",
    ArtifactKind.READINESS: "P4",
    ArtifactKind.MODEL_PLAN: "P5",
    ArtifactKind.MAP: "P5",
    ArtifactKind.CAMPAIGN: "P6",
}


class ArtifactStatus(StrEnum):
    DRAFT = "DRAFT"            # committed, not yet approved
    APPROVED = "APPROVED"      # an approval binds this version's hash
    SUPERSEDED = "SUPERSEDED"  # a newer version of the same artifact exists
    STALE = "STALE"            # derived from an upstream version that has since changed


class ArtifactRef(BaseModel):
    """A pointer to one version of one artifact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ArtifactKind
    id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._:-]+$")
    version: int = Field(ge=1)

    @property
    def key(self) -> tuple[ArtifactKind, str]:
        return (self.kind, self.id)

    def label(self) -> str:
        return f"{self.kind.value}/{self.id}@v{self.version}"


def content_sha256(content: Any) -> str:
    """SHA-256 of the canonical JSON of `content` (sorted keys, compact), the same convention as snapshots."""
    payload = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ArtifactVersion(BaseModel):
    """One immutable version of an artifact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ArtifactKind
    id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._:-]+$")
    version: int = Field(ge=1)
    content: dict[str, Any]
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    derived_from: tuple[ArtifactRef, ...] = ()
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"     # a user id, or "agent:<run id>", or "system" for deterministic derivations
    reason: str = ""               # why this version exists (an edit needs one; a first version says what made it)

    @property
    def ref(self) -> ArtifactRef:
        return ArtifactRef(kind=self.kind, id=self.id, version=self.version)

    @classmethod
    def create(cls, *, kind: ArtifactKind, id: str, version: int, content: dict[str, Any],
               derived_from: tuple[ArtifactRef, ...] = (), created_by: str = "system", reason: str = "") -> ArtifactVersion:
        return cls(kind=kind, id=id, version=version, content=content, sha256=content_sha256(content),
                   derived_from=tuple(derived_from), created_by=created_by, reason=reason)


class Approval(BaseModel):
    """A person's approval of one artifact version (plan §16). Bound to the version's content hash, so a changed
    version is never covered by an earlier approval. `signature_id` is set when the gate needs a Part 11 signature
    (L3 / P6); L1 / L2 approvals are simple named approvals (D-07)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ref: ArtifactRef
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    meaning: str = Field(min_length=1)          # "Reviewed" | "Approved"
    by: str = Field(min_length=1)
    printed_name: str = ""
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    signature_id: str | None = None
    note: str = ""
