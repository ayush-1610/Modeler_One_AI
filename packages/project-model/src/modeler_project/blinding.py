"""External-validation data blinded until the MAP is signed (ICH M15 §4.1; plan §11.4, D-15; ARCHITECTURE_PACK §2.5).

ICH M15 asks for the analysis plan to be fixed before the data it will be judged on are looked at. With blinding on, the
**values** of every external dataset — placed in S5 or S6 on the plan, or entered for external validation — are left out
of every view until a MAP is signed; their metadata (route, dose, food, design, n, sampling times) stays, because the
split is decided on it. A curator who must check a blinded dataset (digitization, acceptance) reveals it for that one
request with a reason, and the reveal is an event on the audit chain.

The setting is per project (D-15): an explicit choice by the MIDD lead, recorded with its reason, or by default on
when the human-confirmed model risk tier in the brief is high. Source documents are outside its reach (a paper is a
paper); it covers what the platform shows.
"""

from __future__ import annotations

from typing import Any

from modeler_project.workspace import Workspace

EXTERNAL_ROLES = ("S5", "S6")
EXTERNAL_PURPOSES = ("external_validation", "application_verification")


def setting(project: dict[str, Any] | None, model_risk: str | None) -> dict[str, Any]:
    """{on, source, reason, by, at}: the project's own choice, else the default for its model risk."""
    explicit = (project or {}).get("blinding")
    if explicit is not None:
        return {**explicit, "source": "project setting"}
    on = model_risk == "high"
    return {"on": on, "source": f"default for {model_risk or 'unrated'} model risk (D-15: on for high)", "reason": ""}


def map_signed(ws: Workspace) -> bool:
    from modeler_project.map_artifact import signed_map

    return signed_map(ws) is not None


def external_studies(ws: Workspace) -> set[str]:
    """Study ids judged externally: the plan's S5 / S6 placements, and datasets entered for external validation."""
    from modeler_project.dataset_register import datasets
    from modeler_project.plan import current

    out: set[str] = set()
    _version, plan = current(ws)
    if plan is not None:
        out |= {sid for sid, p in plan.placements.items() if p.role in EXTERNAL_ROLES}
    for dataset in datasets(ws):
        if dataset.purpose in EXTERNAL_PURPOSES:
            out.add(str(dataset.study.get("study_id")))
    return out


def blinded_studies(ws: Workspace, project: dict[str, Any] | None, model_risk: str | None) -> set[str]:
    """The studies whose values are withheld now (empty when blinding is off or a MAP is signed)."""
    if not setting(project, model_risk)["on"] or map_signed(ws):
        return set()
    return external_studies(ws)


def redact_dataset(content: dict[str, Any]) -> dict[str, Any]:
    """A dataset's view without its values: series values and errors, reported PK values (times and metadata kept)."""
    series = [{**s, "values": [None] * len(s.get("values") or []), "error": None} for s in content.get("series", [])]
    reported = [{**r, "value": None} for r in content.get("reported", [])]
    return {**content, "series": series, "reported": reported, "blinded": True}


def redact_row(row: dict[str, Any]) -> dict[str, Any]:
    """A study-catalog row without its observed profile."""
    return {k: v for k, v in row.items() if k != "profile"} | {"blinded": True}
