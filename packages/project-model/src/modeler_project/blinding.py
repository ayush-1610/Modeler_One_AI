"""External-validation data blinded until the MAP is signed (ICH M15 §4.1; plan §11.4, D-15; ARCHITECTURE_PACK §2.5).

ICH M15 asks for the analysis plan to be fixed before the data it will be judged on are looked at. With blinding on, the
**values** of every external dataset — placed in S5 or S6 on the plan, proposed there by the MS-01 split before a plan
exists (D-33), or entered for external validation — are left out of every view until a MAP is signed; their metadata (route, dose, food, design, n, sampling times) stays, because the
split is decided on it. A curator who must check a blinded dataset (digitization, acceptance) reveals it for that one
request with a reason, and the reveal is an event on the audit chain.

The setting is per project (D-15): an explicit choice by the MIDD lead, recorded with its reason, or by default on
when the human-confirmed model risk tier in the brief is high. A copy of a paper outside the platform is outside its
reach; it covers what the platform shows, and that includes a stored file that holds a blinded study's values: its
original is not served, its pages come with their digits masked and the digitizer does not draw it until the MAP is
signed (`blinded_sources`; final review INT-3).
"""

from __future__ import annotations

import re
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
    """Study ids judged externally: the plan's S5 / S6 placements or, before a plan exists, the roles the MS-01 split
    proposes (D-33: blinding follows the S5 role from the moment a study is read), and datasets entered for external
    validation (`external_why`, which says why each is)."""
    return set(external_why(ws))


ROLE_WORDS = {"S5": "external validation", "S6": "the application"}


def external_why(ws: Workspace) -> dict[str, str]:
    """`external_studies`, each with why it is on the list, in words (final review round 4: a study the sheet form read
    is withheld by the list, and its card says why, so a wrong name match is seen): "the plan places it in S5 (external
    validation)", "the study split proposes it for S5 (external validation), before a plan", "a dataset of it is entered
    for external validation". A study on the list for several reasons is said by the first."""
    from modeler_project.dataset_register import datasets
    from modeler_project.plan import current
    from modeler_project.roles import proposed_roles

    planned = current(ws)[1] is not None
    out: dict[str, str] = {}
    for sid, role in proposed_roles(ws).items():
        if role in EXTERNAL_ROLES:
            words = f"{role} ({ROLE_WORDS.get(role, role)})"
            out[sid] = f"the plan places it in {words}" if planned else f"the study split proposes it for {words}, before a plan"
    for dataset in datasets(ws):
        if dataset.purpose in EXTERNAL_PURPOSES:
            out.setdefault(str(dataset.study.get("study_id")), f"a dataset of it is entered for {dataset.purpose.replace('_', ' ')}")
    return out


def blinded_studies(ws: Workspace, project: dict[str, Any] | None, model_risk: str | None) -> set[str]:
    """The studies whose values are withheld now (empty when blinding is off or a MAP is signed)."""
    return set(listed_why(ws, project, model_risk))


def listed_why(ws: Workspace, project: dict[str, Any] | None, model_risk: str | None) -> dict[str, str]:
    """`blinded_studies`, each with why it is on the project's blinding list (`external_why`)."""
    if not setting(project, model_risk)["on"] or map_signed(ws):
        return {}
    return external_why(ws)


def study_key(study_id: Any) -> str:
    """A study's name as the readers compare it (`client_review._key`): case, spaces and punctuation make no other
    study. A delivery study, a client-review group and a dataset of one name are one study for blinding."""
    return re.sub(r"[^A-Z0-9]", "", str(study_id).upper())


_ROW = re.compile(r"^\[[^\]\n]+? row \d+\]")
_DIGIT = re.compile(r"\d")

# what `redact_dataset` withholds of a dataset, as its version history's paths (`deps.hidden_paths`)
WITHHELD_PATHS = ("series", "reported", "quote", "note", "decision_reason", "digitization")


def redact_dataset(content: dict[str, Any]) -> dict[str, Any]:
    """A dataset's view without its values (D-15): its series' values and errors; its reported PK's values, spread and
    quotes; its own quote, which for a dataset read from a sheet is the sheet's first row verbatim, values and all
    ("[Fed row 4] A4=101 | B4=BLQ | C4=5.2 …"), down to the place it names ("[Fed row 4]", all the page reads of it,
    `words.datasetPlace`); its note left out and the digits of the reason it was decided with masked (a person may have
    quoted a value; the delivery's rule, `intake_decisions.mask`); a digitized figure's picked points left out (with the
    calibration kept they would give the values). Its times, units, study record (the split's metadata) and source kept
    (final review round 7: the quote and note were served with a blinded study's values in them)."""
    series = [{**s, "values": [None] * len(s.get("values") or []), "error": None} for s in content.get("series", [])]
    reported = [{**r, "value": None, "variability": "", "quote": ""} for r in content.get("reported", [])]
    place = _ROW.match(str(content.get("quote") or ""))
    out = {**content, "series": series, "reported": reported, "quote": place.group(0) if place else "", "note": "",
           "decision_reason": _DIGIT.sub("•", str(content.get("decision_reason") or "")), "blinded": True}
    if isinstance(content.get("digitization"), dict):
        out["digitization"] = {**content["digitization"], "pixels": {}}
    return out


def redact_row(row: dict[str, Any]) -> dict[str, Any]:
    """A study-catalog row without its observed profile."""
    return {k: v for k, v in row.items() if k != "profile"} | {"blinded": True}
