"""The project start-up pipeline (phases P0–P6, `docs/plans/2026-09-25-project-startup-pipeline.md`).

Every phase output is an immutable, hashed artifact version that names the exact upstream versions it was derived
from. An edit creates a new version; whatever was derived from the old one becomes *stale* (shown with its reason),
never deleted or silently recomputed. Signed or approved versions are never changed, only superseded.
"""

from modeler_project.artifacts import (
    Approval,
    ArtifactKind,
    ArtifactRef,
    ArtifactStatus,
    ArtifactVersion,
    content_sha256,
)
from modeler_project.diff import Change, diff
from modeler_project.store import FileProjectStore, ImmutableVersionError, ProjectStore
from modeler_project.workspace import ImpactItem, ImpactReport, PhaseStatus, StaleItem, Workspace

__all__ = [
    "Approval",
    "ArtifactKind",
    "ArtifactRef",
    "ArtifactStatus",
    "ArtifactVersion",
    "Change",
    "FileProjectStore",
    "ImmutableVersionError",
    "ImpactItem",
    "ImpactReport",
    "PhaseStatus",
    "ProjectStore",
    "StaleItem",
    "Workspace",
    "content_sha256",
    "diff",
]
