"""P1 answers of `requirements_api`: the data plan page."""

from __future__ import annotations

from typing import Any

from modeler_api.views.common import VersionView, View


class RequirementCounts(View):
    applicable: int
    by_provider: dict[str, int]
    undetermined: int
    to_harvest: int


class RequirementsPage(View):
    artifact: VersionView
    matrix: dict[str, Any]
    counts: RequirementCounts
    feasibility: dict[str, Any]
    brief_status: str | None
