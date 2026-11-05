"""The evaluation set for reading a client's delivery across files (docs/plans/2026-11-03-inputs-and-client-data.md §3.4,
build I6, grown alongside from I3 on).

Each delivery is a small set of synthetic client files with a known answer: the groups the client's data must form,
the conflicts, differences and questions that must be flagged on them, the links to ask about, and what must be found
the same across files (made one, with a note). `score` runs a delivery through the real path (the library, the tags,
`client_data.ingest`, `client_review.groups`) and says what was found, what was missed and what was flagged that the
answer does not hold. Software test data with made-up numbers: it measures the reading, never a model.

Real client deliveries are scored the same way on the server, with the answer a person writes for them.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from modeler_intake.client_template import build_template


@dataclass(frozen=True)
class DeliveryFile:
    name: str
    build: Callable[[], bytes]
    tag: tuple[str, str] | None = None          # (kind, study) as the person tags it at upload


@dataclass(frozen=True)
class Delivery:
    name: str
    files: tuple[DeliveryFile, ...]
    groups: tuple[str, ...]                     # the group ids the data must form
    flags: tuple[str, ...] = ()                 # "<group>|<issue key prefix>:<kind>" for every conflict, difference, link
    notes: tuple[str, ...] = ()                 # a phrase each "found the same" note must hold, by group: "<group>|<phrase>"


@dataclass
class Score:
    delivery: str
    found: list[str] = field(default_factory=list)
    missed: list[str] = field(default_factory=list)
    unexpected: list[str] = field(default_factory=list)

    @property
    def perfect(self) -> bool:
        return not self.missed and not self.unexpected


def _template(*, studies: list[dict[str, Any]] = (), summary: list[tuple] = (), dissolution: list[tuple] = (),
              note: str = "") -> Callable[[], bytes]:
    def build() -> bytes:
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(build_template()))
        header = [c.value.rstrip("*") for c in wb["Studies"][1]]
        for study in studies:
            wb["Studies"].append([study.get(h) for h in header])
        for row in summary:
            wb["PK_Summary"].append(list(row))
        for row in dissolution:
            wb["Dissolution"].append(list(row))
        if note:
            wb["README"]["A1"] = note
        out = io.BytesIO()
        wb.save(out)
        return out.getvalue()

    return build


def _study(study_id: str, *, dose: float = 10, n: int = 12) -> dict[str, Any]:
    return {"study_id": study_id, "design": "SD", "population": "healthy", "n": n, "route": "oral", "dose": dose,
            "dose_unit": "mg", "formulation": "ir_tablet", "food_state": "fasted", "lloq": 0.5, "lloq_unit": "ng/ml"}


def _pk(study_id: str, values: tuple[float, ...], n: int = 12) -> list[tuple]:
    return [(study_id, None, t, "h", "arithmetic_mean", v, None, None, n, "ng/ml") for t, v in zip((0.5, 1, 2, 4, 8), values,
                                                                                              strict=True)]


def _diss(at_30: float) -> list[tuple]:
    return [("Test 10 mg tablet", "TEST", 10, "B1", "USP 2 paddle", 50, "phosphate", 6.8, 900, 37, None, t, "min", v, v + 1, v - 1)
            for t, v in ((15, 55), (30, at_30), (45, 97))]


PK = (18.0, 42.0, 31.0, 13.0, 4.2)

DELIVERIES: tuple[Delivery, ...] = (
    Delivery("one study, two doses and two subject counts", (
        DeliveryFile("EX-101_protocol_PK.xlsx", _template(studies=[_study("EX-101", dose=10, n=14)], summary=_pk("EX-101", PK, 14))),
        DeliveryFile("EX-101_PK_sheet.xlsx", _template(studies=[_study("EX-101", dose=5, n=12)], summary=_pk("EX-101", PK, 12))),
    ), groups=("study:EX-101",), flags=("study:EX-101|dose_mg:conflict", "study:EX-101|n:difference"),
       notes=("study:EX-101|gives the same profile",)),
    Delivery("the same profile sent twice", (
        DeliveryFile("PK_v1.xlsx", _template(studies=[_study("EX-1")], summary=_pk("EX-1", PK))),
        DeliveryFile("PK_v2.xlsx", _template(studies=[_study("EX-1")], summary=_pk("EX-1", PK), note="sent again")),
    ), groups=("study:EX-1",), notes=("study:EX-1|gives the same profile",)),
    Delivery("one study written two ways, its profiles differing", (
        DeliveryFile("site_a.xlsx", _template(studies=[_study("EX-202")], summary=_pk("EX-202", PK))),
        DeliveryFile("site_b.xlsx", _template(studies=[_study("ex 202")], summary=_pk("ex 202", (18.0, 55.0, 31.0, 13.0, 4.2)))),
    ), groups=("study:EX-202",), flags=("study:EX-202|profile:conflict",), notes=("study:EX-202|Also called ex 202",)),
    Delivery("a study named at upload that its sheet calls otherwise", (
        DeliveryFile("Data_Q3_final.xlsx", _template(studies=[_study("Study 101")], summary=_pk("Study 101", PK)),
                     tag=("clinical", "EXZ-101")),
    ), groups=("study:Study 101",), flags=("link|Study 101:link",)),
    Delivery("a dissolution profile given twice, 14 points apart", (
        DeliveryFile("release.xlsx", _template(dissolution=_diss(85))),
        DeliveryFile("stability.xlsx", _template(dissolution=_diss(71))),
    ), groups=("product:Test 10 mg tablet",), flags=("product:Test 10 mg tablet|profile:conflict",)),
)


def _flag(issue: dict[str, Any]) -> str:
    """An issue as the answer names it: "<group>|<what>:<kind>" ("study:EX-101|dose_mg:conflict"), or a link question
    as "link|<the sheet's name>:link"."""
    scope, _, key = issue["id"].partition("|")
    return f"{scope}|{key if issue['kind'] == 'link' else key.split(':', 1)[0]}:{issue['kind']}"


def score(delivery: Delivery, ws: Any, *, by: str = "eval") -> Score:
    """Read one delivery into an empty project workspace and compare what was found with the answer."""
    from modeler_project.client_data import ingest
    from modeler_project.client_review import groups
    from modeler_project.documents import DocumentLibrary

    library = DocumentLibrary(ws)
    for f in delivery.files:
        ingest(ws, library, f.build(), f.name, by=by, tag=f.tag)
    found = groups(ws)
    result = Score(delivery.name)
    ids = {g["id"] for g in found}
    flagged = {_flag(i) for g in found for i in g["issues"]}
    notes = {(g["id"], n) for g in found for n in g["notes"]}
    expected = [*(f"group {g}" for g in delivery.groups), *(f"flag {f}" for f in delivery.flags),
                *(f"note {n}" for n in delivery.notes)]
    for item in expected:
        what, _, key = item.partition(" ")
        hit = (key in ids if what == "group" else key in flagged if what == "flag"
               else any(g == key.split("|", 1)[0] and key.split("|", 1)[1] in n for g, n in notes))
        (result.found if hit else result.missed).append(item)
    result.unexpected = [f"group {g}" for g in sorted(ids - set(delivery.groups)) if g.startswith(("study:", "product:"))]
    result.unexpected += [f"flag {f}" for f in sorted(flagged - set(delivery.flags))]
    return result
