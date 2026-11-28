"""Start from the Data room (plan 2026-11-24 §7, phase 4, B4): what the delivery already said is not typed again.

The Data room's question card, once a person confirmed it, its applications decision and what its studies state are
drafted into the brief through the agents' path (`brief_ops.agent_set`, DRAFTED, each with the quotes it rests on):

- the question of interest (`qoi.text`) and the context of use from the card;
- the applications (`qoi.applications`) from the room's applications by `room_basis.ROOM_TO_BRIEF` (the owner reviews
  the table);
- the agencies from the card's regulator, by name (FDA, EMA, PMDA, CDSCO, Health Canada, TGA, NMPA, MHRA; anything else is
  left for a person);
- the products and their roles from the card (reference and original as REFERENCE, test and reformulated as TEST);
- one scenario per study arm the room sends (route, dose in mg, fed or fasted, product, population), merged with the
  scenarios Start already holds: a scenario whose fields agree is completed, the others are added;
- the formulation types from the dosage forms the delivery states (else, for the products the room sends with a release
  profile, an immediate-release tablet: what the send makes of them);
- the populations from the studies (healthy or patients as stated, the PK-Sim population the room chose, the sex);
then the ICH M15 ratings by the rule, as Start drafts them (`risk_draft.draft_risk`).

A draft is not a value until a person confirms or changes it. A field a person set (or marked not stated), and a value a
document states (EXTRACTED, RETRIEVED, COMPUTED), are never overwritten: where they differ from the room, Start advises
(`steps.room_advice`). An earlier draft (the intake agent's, code's, or the room's own) gives way to the room's: the card
is a person's confirmed word on the question.
"""

from __future__ import annotations

import re
from typing import Any

from modeler_project.artifacts import ArtifactKind
from modeler_project.brief import Citation, FieldStatus, ProjectBrief
from modeler_project.brief_ops import BRIEF_ID, agent_set, locked, save_brief
from modeler_project.plan import application_label
from modeler_project.risk_draft import draft_risk
from modeler_project.room_basis import ArmLine, RoomBasis, RoomCite, StatedLine, room_basis
from modeler_project.start_drafts import _MR, FORMS, ROUTES
from modeler_project.workspace import Workspace

CODE = "code:data-room"
NOTE = "from the Data room ({where}): {why}"

AGENCIES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("FDA", re.compile(r"\bU\.?S\.? ?FDA\b|\bFDA\b|Food and Drug Administration")),
    ("EMA", re.compile(r"\bEMA\b|European Medicines Agency")),
    ("PMDA", re.compile(r"\bPMDA\b|Pharmaceuticals and Medical Devices Agency")),
    ("CDSCO", re.compile(r"\bCDSCO\b|Central Drugs Standard Control")),
    ("Health Canada", re.compile(r"Health Canada", re.IGNORECASE)),
    ("TGA", re.compile(r"\bTGA\b|Therapeutic Goods Administration")),
    ("NMPA", re.compile(r"\bNMPA\b|National Medical Products Administration")),
    ("MHRA", re.compile(r"\bMHRA\b|Medicines and Healthcare products Regulatory Agency")),
)
# the card's product roles and the brief's (`brief.PRODUCT_ROLES`); a draft a person confirms or changes
PRODUCT_ROLES = {"reference": "REFERENCE", "original": "REFERENCE", "test": "TEST", "reformulated": "TEST", "other": "OTHER"}
_HEALTHY = re.compile(r"\bhealthy\b", re.IGNORECASE)
_PATIENTS = re.compile(r"\bpatients?\b", re.IGNORECASE)
_SEX = {"MALE": "male", "FEMALE": "female", "MIXED": "male and female"}


class RoomError(ValueError):
    pass


def _cites(cites: tuple[RoomCite, ...] | list[RoomCite]) -> tuple[Citation, ...]:
    return tuple(dict.fromkeys(c for cite in cites if (c := cite.citation()) is not None))


def _stated_cites(*lines: StatedLine | None) -> tuple[Citation, ...]:
    return _cites([c for line in lines if line is not None for c in line.cites])


def _by_a_person(by: str | None) -> bool:
    return bool(by) and not str(by).startswith(("agent:", "code:", "system"))


def writable(brief: ProjectBrief, path: str) -> bool:
    """Whether the room may draft `path`: empty, or an earlier draft. A person's value (or their "not stated"), and a
    value a document or a database states, are kept."""
    record = brief.get(path)
    if locked(brief, path) or record.status in (FieldStatus.EXTRACTED, FieldStatus.RETRIEVED, FieldStatus.COMPUTED):
        return False
    if record.status in (FieldStatus.MISSING, FieldStatus.NOT_APPLICABLE) and _by_a_person(record.by):
        return False
    return record.status in (FieldStatus.MISSING, FieldStatus.DRAFTED)


def _same(a: Any, b: Any) -> bool:
    norm = (lambda v: sorted(map(str, v)) if isinstance(v, list | tuple) else " ".join(str(v).split()).lower()
            if isinstance(v, str) else v)
    return norm(a) == norm(b)


def agencies(regulator: str) -> list[str]:
    """The brief's agencies a regulator's words name, in the brief's order."""
    return [name for name, pattern in AGENCIES if pattern.search(regulator or "")]


def route_of(text: str) -> str | None:
    """The brief's route a study's route words give (as Start reads a proposal: an infusion, a bolus, by mouth)."""
    return next((option for option, pattern in ROUTES if pattern.search(text or "")), None)


def _dose_mg(line: StatedLine | None) -> float | None:
    if line is None or not isinstance(line.value, int | float) or isinstance(line.value, bool):
        return None
    return float(line.value) if line.unit.strip().lower() == "mg" else None


def formulation_types(basis: RoomBasis) -> tuple[list[str], tuple[Citation, ...], str]:
    """The formulation types the delivery states (a dosage form, with "extended release" read as modified release), else
    an immediate-release tablet for each product the send gives a release profile; the citations and why."""
    found: dict[str, StatedLine] = {}
    for line in basis.dosage_forms:
        for option, pattern, _not_medium in FORMS:
            if pattern.search(line.text):
                found.setdefault("mr" if option in ("ir_tablet", "ir_capsule") and _MR.search(line.text) else option, line)
        if _MR.search(line.text):
            found.setdefault("mr", line)
    if found:
        return list(found), _stated_cites(*found.values()), "the dosage forms the delivery states"
    if any(p.sent for p in basis.products):
        return ["ir_tablet"], (), "the products it sends with a release profile go to the model as immediate-release tablets"
    return [], (), ""


def _scenario(arm: ArmLine) -> dict[str, tuple[Any, tuple[Citation, ...]]]:
    out: dict[str, tuple[Any, tuple[Citation, ...]]] = {}
    if arm.route and (route := route_of(arm.route.text)):
        out["route"] = (route, _stated_cites(arm.route))
    if (dose := _dose_mg(arm.dose)) is not None:
        out["dose"] = (dose, _stated_cites(arm.dose))
    if arm.food and arm.food.value in ("fed", "fasted"):
        out["food_state"] = (arm.food.value, _stated_cites(arm.food))
    if arm.product:
        out["product"] = (arm.product, ())
    if arm.population and arm.population.text.strip():
        out["population"] = (arm.population.text.strip(), _stated_cites(arm.population))
    return out


def _population(arm: ArmLine) -> dict[str, tuple[Any, tuple[Citation, ...]]]:
    text = arm.population.text if arm.population else ""
    kind = "healthy" if _HEALTHY.search(text) else "patient" if _PATIENTS.search(text) else None
    if kind is None:
        return {}
    out: dict[str, tuple[Any, tuple[Citation, ...]]] = {"kind": (kind, _stated_cites(arm.population))}
    if arm.population_db:
        out["ethnicity"] = (arm.population_db, ())
    if arm.sex and arm.sex.text.strip():
        out["sex"] = (arm.sex.text.strip(), _stated_cites(arm.sex))
    return out


class _Drafter:
    def __init__(self, brief: ProjectBrief, basis: RoomBasis):
        self.brief, self.basis = brief, basis
        self.drafted: list[str] = []
        self.kept: list[str] = []

    def put(self, path: str, value: Any, why: str, cites: tuple[Citation, ...] = (), where: str = "its question card") -> None:
        if value in (None, "", []):
            return
        record = self.brief.get(path)
        if not writable(self.brief, path):
            if record.value not in (None, "", []) and not _same(record.value, value):
                self.kept.append(path)
            return
        if record.status is FieldStatus.DRAFTED and record.by == CODE and _same(record.value, value):
            return                                       # the room's draft as it stands: no new version
        self.brief = agent_set(self.brief, path, value=value, unit=None, citations=cites, status=FieldStatus.DRAFTED,
                               confidence=None, by=CODE, note=NOTE.format(where=where, why=why))
        self.drafted.append(path)

    def group(self, group: str, wanted: list[dict[str, tuple[Any, tuple[Citation, ...]]]], keys: tuple[str, ...],
              why: str, where: str) -> None:
        """Each wanted item onto the group: an item whose values agree (or are empty) is completed, the rest are added."""
        used: set[int] = set()
        for item in wanted:
            items = self.brief.groups.get(group, ())
            index = next((i for i in range(len(items)) if i not in used and all(
                self.brief.get(f"{group}[{i}].{k}").value in (None, "", []) or _same(self.brief.get(f"{group}[{i}].{k}").value, v)
                for k, (v, _c) in item.items() if k in keys)), len(items))
            used.add(index)
            for field, (value, cites) in item.items():
                self.put(f"{group}[{index}].{field}", value, why, cites, where)


def draft_from_room(brief: ProjectBrief, basis: RoomBasis, *, proposal: list[str] | tuple[str, ...] = ()
                    ) -> tuple[ProjectBrief, list[str], list[str]]:
    """The brief with the room's drafts (pure); the paths drafted, and the paths kept because a person or a document set
    another value. Refused unless a person confirmed the room's question card."""
    if not basis.confirmed:
        raise RoomError("the Data room's question card is not confirmed yet: confirm it there first")
    card, cites = basis.card, basis.card_cites
    d = _Drafter(brief, basis)
    d.put("qoi.text", card.question.strip(), "the question the delivery must answer", _cites(cites.get("question.text", ())))
    d.put("qoi.context_of_use", card.context_of_use.strip(), "how the model will be used",
          _cites(cites.get("question.context_of_use", ())))
    chosen = "chosen in the Data room" if basis.applications_chosen else "as read from the question card"
    labels = [application_label(c) for c in basis.codes]
    d.put("qoi.applications", labels, f"{', '.join(basis.application_labels) or 'none of the drafts (core items only)'}, "
          f"{chosen}", _cites([c for f in ("question.text", "question.approach", "question.context_of_use")
                               for c in cites.get(f, ())]), "its applications decision")
    d.put("proj.agencies", agencies(card.regulator), f"the regulator “{card.regulator}”",
          _cites(cites.get("question.regulator", ())))
    product_cites = _cites([c for f in ("product.name", "product.role") for c in cites.get(f, ())])
    d.group("products", [{"name": (p.name, product_cites), "role": (PRODUCT_ROLES.get(p.role, "OTHER"), product_cites)}
                         for p in basis.products], ("name",), "the card's products and their roles", "its question card")
    scenarios: list[dict[str, tuple[Any, tuple[Citation, ...]]]] = []
    for arm in basis.arms:
        s = _scenario(arm)
        if s and all(not _same({k: v for k, (v, _c) in s.items()}, {k: v for k, (v, _c) in o.items()}) for o in scenarios):
            scenarios.append(s)
    d.group("scenarios", scenarios, ("route", "dose", "food_state", "product"),
            "a study arm the room sends (route, dose, food state, product)", "its studies")
    forms, form_cites, why = formulation_types(basis)
    d.put("scope.formulation_types", forms, why, form_cites, "its products")
    populations: list[dict[str, tuple[Any, tuple[Citation, ...]]]] = []
    for arm in basis.arms:
        p = _population(arm)
        if p and all(not _same({k: v for k, (v, _c) in p.items()}, {k: v for k, (v, _c) in o.items()}) for o in populations):
            populations.append(p)
    d.group("populations", populations, ("kind", "ethnicity"), "a study's subjects (the PK-Sim population the room chose)",
            "its studies")
    brief, risk = draft_risk(d.brief, proposal=proposal)
    return brief, d.drafted + risk, list(dict.fromkeys(d.kept))


def draft_brief_from_room(ws: Workspace, *, by: str) -> dict[str, Any]:
    """Draft the brief from the project's Data room and save it (a new version only when something was drafted); the
    data plan follows. `by`: who asked (a person, or the room's own route once it is wired). Returns the paths drafted,
    the paths kept (a person's or a document's value that differs from the room), and Start's advice."""
    from modeler_project.data_plan import refresh_data_plan
    from modeler_project.documents import DocumentLibrary
    from modeler_project.start_drafts import sentences
    from modeler_project.steps import room_advice

    basis = room_basis(ws)
    if basis is None:
        raise RoomError("the Data room has no question card yet")
    proposal = [s.text for s in sentences(DocumentLibrary(ws))]
    with ws.editing(ArtifactKind.BRIEF, BRIEF_ID):
        version = ws.latest(ArtifactKind.BRIEF, BRIEF_ID)
        if version is None:
            raise RoomError("this project has no brief yet")
        brief, drafted, kept = draft_from_room(ProjectBrief.from_content(version.content), basis, proposal=proposal)
        if drafted:
            save_brief(ws, brief, actor=by, reason=f"drafted from the Data room: {', '.join(dict.fromkeys(drafted))}")
            refresh_data_plan(ws, actor=by, reason="derived from the brief")
    return {"drafted": list(dict.fromkeys(drafted)), "kept": kept,
            "advice": [a.message for a in room_advice(brief, basis)]}


#: the brief's fields the room's question card answers, confirmed with the card (D3)
CARD_FIELDS = ("qoi.text", "qoi.context_of_use")


def confirm_card_in_brief(ws: Workspace, *, by: str) -> list[str]:
    """One question card (the owner's D3, 2026-11-27; plan 2026-11-27-one-way-in step 4): the person who confirms the Data
    room's question card has confirmed the question of interest and the context of use, so Start does not ask again.
    Only the room's own drafts of them (`CODE`, DRAFTED from that card) are confirmed, as `by`; a value a person or a
    document gave Start is never changed (where it differs, Start advises, `steps.room_advice`). Returns the paths
    confirmed (none: no new version)."""
    from modeler_project.brief_ops import edit_field

    with ws.editing(ArtifactKind.BRIEF, BRIEF_ID):
        version = ws.latest(ArtifactKind.BRIEF, BRIEF_ID)
        if version is None:
            return []
        brief = ProjectBrief.from_content(version.content)
        done = []
        for path in CARD_FIELDS:
            record = brief.get(path)
            if record.status is FieldStatus.DRAFTED and record.by == CODE and record.value not in (None, "", []):
                brief = edit_field(brief, path, status=FieldStatus.CONFIRMED, by=by,
                                   note="confirmed with the Data room's question card")
                done.append(path)
        if done:
            save_brief(ws, brief, actor=by, reason=f"confirmed with the Data room's question card: {', '.join(done)}")
    return done


__all__ = ["AGENCIES", "CARD_FIELDS", "CODE", "PRODUCT_ROLES", "RoomError", "agencies", "confirm_card_in_brief",
           "draft_brief_from_room", "draft_from_room", "formulation_types", "route_of", "writable"]
