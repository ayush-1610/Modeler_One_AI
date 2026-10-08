"""The P1 data plan as a project service (plan §7, T-42 / T-43): derived from the latest brief.

The requirement matrix (REQUIREMENTS/main) and the feasibility report (FEASIBILITY/main) are deterministic derivations
of the brief (BRIEF/main), so a brief edit makes them stale and re-deriving brings them up to date. A person's
overrides are kept across re-derivations; `extra` adds or replaces one.
"""

from __future__ import annotations

from modeler_project.artifacts import ArtifactKind
from modeler_project.brief import ProjectBrief
from modeler_project.feasibility import check
from modeler_project.requirements import RequirementMatrix, RequirementOverride, derive
from modeler_project.workspace import Workspace

MAIN = "main"


class NoBriefError(LookupError):
    """The project has no brief to derive the data plan from."""


def derive_data_plan(ws: Workspace, *, actor: str, reason: str, extra: RequirementOverride | None = None) -> None:
    """(Re-)derive the requirement matrix and the feasibility report from the latest brief."""
    brief_version = ws.latest(ArtifactKind.BRIEF, MAIN)
    if brief_version is None:
        raise NoBriefError("no brief to derive the data plan from")
    brief = ProjectBrief.from_content(brief_version.content)
    previous_version = ws.latest(ArtifactKind.REQUIREMENTS, MAIN)
    previous = RequirementMatrix.from_content(previous_version.content) if previous_version else None
    overrides = list(previous.overrides) if previous else []
    if extra is not None:
        overrides = [o for o in overrides if o.req_id != extra.req_id] + [extra]
    matrix = derive(brief, tuple(overrides), previous=previous)
    ws.commit(ArtifactKind.REQUIREMENTS, MAIN, matrix.to_content(), derived_from=[brief_version.ref], actor=actor,
              reason=reason)
    ws.commit(ArtifactKind.FEASIBILITY, MAIN, check(brief).to_content(), derived_from=[brief_version.ref], actor=actor,
              reason=reason)
