"""Requirement coverage per study and per product (plan G4, contracts §6.4).

A study's items are the items of the templates its routing activates (`study_routing.route`) that the rules file
scopes to a study (`routing.item_scope.study`); a product's are those scoped to a product (`routing.item_scope.product`),
of the core template and the templates the project's applications select. Every other template item is the project's
(the data plan, where it stays) and is never a study's or a product's: it is not listed here and blocks nothing.

Each item is judged against the subject's active values, by the rules file's `routing.item_fields`:
- `found`: every `all` field (and one `any` field, when listed) has an active value of the subject (an `lloq` is
  also stated by a concentration value that carries its own LLOQ, a "<0.5" cell, as `intake_checks` reads it); with `per`, for
  every distinct such entity part of the subject's concentration values (an analyte, a matrix) a value of each `all`
  field with the same part (a part a value leaves unstated is not compared); with `conditions`, every active value of
  the `all` fields carries those conditions;
- `conflicting`: found, and one of those values is in an open conflict (`LedgerReader.conflicts`);
- otherwise `missing`, until a person's `RequirementDisposition` for the subject and item says `ask_client`,
  `literature` or `not_needed` (the latest one counts; a found item stays found);
- `not_applicable`: the item's `when` is false for the subject (`study_routing.study_when`: the study's own route and
  food state, the brief for the rest), or a per-product item (`per: solid_product`) for a product that is not solid.

A per-product item keeps its `@` id (`REQ-form.release@<slug>`): the data plan's id when the matrix has the item for a
product of that name, else the same slug rule applied to the ledger's product label. A missing item drafts a line of
the client request (`request_lines`).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from modeler_intake.client_template import SHEET_FOR_CATEGORY
from modeler_intake.document_reading import name_key
from modeler_project.brief import APPLICATIONS, ProjectBrief
from modeler_project.intake_records import RequirementDisposition, RequirementStatus, StudyRequirements
from modeler_project.intake_rules import IntakeRules, ItemFields
from modeler_project.intake_rules import rules as load_rules
from modeler_project.ledger_models import ValueState
from modeler_project.ledger_view import LedgerReader
from modeler_project.requirements import _SOLID, RequestLine, RequirementMatrix, _slug, load_templates
from modeler_project.study_routing import (
    application_codes,
    matrix_choice,
    route,
    stated,
    study_matrix,
    study_tags,
    study_when,
    subject_values,
)

# The field whose values `per` ranges over: the subject's concentration profile (contracts §4.7, the YAML's comment)
PER_FIELD = "concentration"
# A field a value of another field states as its own attribute (`ValueState.lloq`): a censored concentration written
# "<0.5" states the LLOQ of its profile, as `intake_checks` counts it for ONE_LLOQ_PER_PROFILE and BLQ_WITHOUT_LLOQ
CARRIED = {"lloq": PER_FIELD}
REQUESTED = ("missing", "ask_client")      # what the client request asks for: an item not found, or one a person said to ask


def requirement_status(reader: LedgerReader, study: str, *, brief: ProjectBrief | None, matrix: RequirementMatrix | None,
                       dispositions: Sequence[RequirementDisposition] = (),
                       rules: IntakeRules | None = None) -> StudyRequirements:
    """The study's routing (templates and schema gaps) and the status of each of its study-scoped items."""
    rules = rules or load_rules()
    study = _resolved(reader, study)
    tags = study_tags(reader, study, brief=brief)
    routing = route(study, tags, applications=_applications(brief, matrix), rules=rules)
    scoped = set(rules.routing.item_scope.get("study", ()))
    templates = {t["id"]: t for t in load_templates()}
    values = subject_values(reader, "study", study)
    conflicted = _conflicted(reader.conflicts(study=study))
    items: dict[str, RequirementStatus] = {}
    for template_id in routing.templates:
        for raw in templates[template_id]["items"]:
            if raw["id"] not in scoped or raw["id"] in items:
                continue
            applies = _applies(raw, study_when(raw.get("when"), tags, brief=brief))
            items[raw["id"]] = _status(raw, template_id, raw["id"], "study", study, raw["label"], applies,
                                       rules.routing.item_fields.get(raw["id"]), values, conflicted, dispositions, reader)
    return StudyRequirements(routing=routing, items=tuple(items.values()))


def product_requirements(reader: LedgerReader, product: str, *, brief: ProjectBrief | None,
                         matrix: RequirementMatrix | None, dispositions: Sequence[RequirementDisposition] = (),
                         rules: IntakeRules | None = None) -> tuple[RequirementStatus, ...]:
    """The status of each product-scoped item of the core template and of the templates the project's applications
    select, for one product. Its `when` is evaluated with the route and food state of the studies whose values name
    the product, and the brief for the rest."""
    rules = rules or load_rules()
    product = _resolved(reader, product)
    entity = reader.entity(product)
    label = entity.label if entity is not None else product
    values = subject_values(reader, "product", product)
    tags = _product_tags(reader, values)
    codes = application_codes(_applications(brief, matrix))
    scoped = set(rules.routing.item_scope.get("product", ()))
    conflicted = _conflicted(reader.conflicts(product=product))
    solid = _is_solid(label, values, matrix)
    out: dict[str, RequirementStatus] = {}
    for template in load_templates():
        scope = template.get("applies_to")
        if template["id"] != rules.routing.core and not (scope != "all" and codes & set(scope or ())):
            continue
        for raw in template["items"]:
            if raw["id"] not in scoped:
                continue
            per_product = raw.get("per") == "solid_product"
            req_id = _product_req_id(raw["id"], label, matrix) if per_product else raw["id"]
            if req_id in out:
                continue
            applies = "no" if per_product and not solid else _applies(raw, study_when(raw.get("when"), tags, brief=brief))
            out[req_id] = _status(raw, template["id"], req_id, "product", product, f"{raw['label']} — {label}", applies,
                                  rules.routing.item_fields.get(raw["id"]), values, conflicted, dispositions, reader)
    return tuple(out.values())


def request_lines(statuses: Iterable[RequirementStatus], *, labels: Mapping[str, str]) -> list[RequestLine]:
    """One line of the client request per item still to ask for: missing, or a person said to ask the client (an
    item that does not apply, is found, or comes from literature or is not needed asks nothing). `labels` gives each
    subject's label (a study's id as written, a product's name): a study's line names its study, a product's line its
    product. `why` is what the item serves (an application, or the model itself) and `sheet` where it goes in the
    client-data workbook, as `requirements.client_request` writes them."""
    serves, categories = _serves()
    out: list[RequestLine] = []
    seen: set[tuple[str, str | None]] = set()
    for status in statuses:
        if status.status not in REQUESTED or status.applies == "no" or (status.req_id, status.subject) in seen:
            continue
        seen.add((status.req_id, status.subject))
        who = labels.get(status.subject or "", status.subject or "")
        what = f"{status.label} — study {who}" if status.scope == "study" and who else status.label
        out.append(RequestLine(req_id=status.req_id, what=what, why=serves.get(status.template, ""),
                               required=status.criticality == "REQUIRED",
                               product=(who or None) if status.scope == "product" else None,
                               sheet=SHEET_FOR_CATEGORY.get(categories.get(status.req_id.partition("@")[0], ""), "")))
    return out


# --- judging an item ---------------------------------------------------------------------------------------------------


def _status(raw: dict[str, Any], template: str, req_id: str, scope: str, subject: str, label: str, applies: str,
            spec: ItemFields | None, values: Sequence[ValueState], conflicted: set[str],
            dispositions: Sequence[RequirementDisposition], reader: LedgerReader) -> RequirementStatus:
    base = dict(req_id=req_id, template=template, label=label, scope=scope, subject=subject,
                criticality=str(raw.get("criticality", "")), applies=applies)
    if applies == "no":
        return RequirementStatus(**base, status="not_applicable")
    found = _found(spec, values) if spec is not None else None
    if found is not None:
        status = "conflicting" if conflicted & set(found) else "found"
        return RequirementStatus(**base, status=status, values=found)
    disposition = _disposition(dispositions, reader, subject, req_id)
    if disposition is not None:
        return RequirementStatus(**base, status=disposition.disposition, disposition=disposition.id)
    return RequirementStatus(**base, status="missing")


def _found(spec: ItemFields, values: Sequence[ValueState]) -> tuple[str, ...] | None:
    """The ids of the values that make an item found, or None when it is not (see the module docstring)."""
    by_field: dict[str, list[ValueState]] = {}
    for value in values:
        if stated(value):
            by_field.setdefault(value.field, []).append(value)
        for name, carrier in CARRIED.items():
            if value.field == carrier and getattr(value, name, None) is not None:
                by_field.setdefault(name, []).append(value)
    if not spec.all and not spec.any:
        return None
    used: list[ValueState] = []
    for name in spec.all:
        if not by_field.get(name):
            return None
        used += by_field[name]
    if spec.any:
        hits = [v for name in spec.any for v in by_field.get(name, [])]
        if not hits:
            return None
        used += hits
    if spec.per:
        matrix = study_matrix(values)
        groups = {tuple(_part(v, part, matrix) for part in spec.per) for v in by_field.get(PER_FIELD, [])}
        for group in groups:
            for name in spec.all:
                if not any(_same_parts(group, tuple(_part(v, part, matrix) for part in spec.per))
                           for v in by_field[name]):
                    return None
    if spec.conditions:
        for name in spec.all:
            if any(not (v.conditions.get(c) or "").strip() for v in by_field[name] for c in spec.conditions):
                return None
    return tuple(dict.fromkeys(v.id for v in used))


def _part(value: ValueState, part: str, study_matrix: str | None) -> str | None:
    """A value's entity part for `per`: an entity id or a label; the matrix as its choice, the study's single matrix
    when the value has none."""
    if part == "matrix":
        return matrix_choice(value.entity.matrix) or study_matrix
    found = getattr(value.entity, part, None)
    return None if found is None else str(found)


def _same_parts(group: tuple[str | None, ...], parts: tuple[str | None, ...]) -> bool:
    """Whether a value's parts fit a group: equal where both state the part (an LLOQ stated for the whole study fits
    each analyte of it)."""
    return all(a is None or b is None or a == b for a, b in zip(group, parts, strict=True))


def _disposition(dispositions: Sequence[RequirementDisposition], reader: LedgerReader, subject: str,
                 req_id: str) -> RequirementDisposition | None:
    found = None
    for disposition in dispositions:                 # in log order: the latest one counts
        if disposition.req_id == req_id and _resolved(reader, disposition.subject) == subject:
            found = disposition
    return found


def _applies(raw: dict[str, Any], when: bool | None) -> str:
    if raw.get("criticality") == "CONDITIONAL" and raw.get("when") == {}:
        when = True                                  # recommended without condition (requirements.derive does the same)
    return {True: "yes", False: "no", None: "undetermined"}[when]


# --- the subject -------------------------------------------------------------------------------------------------------


def _resolved(reader: LedgerReader, entity_id: str) -> str:
    """An entity id followed through merges (an unknown id stays as it is)."""
    entity = reader.entity(entity_id)
    return entity.id if entity is not None else entity_id


def _conflicted(conflicts: Iterable[Any]) -> set[str]:
    return {value_id for conflict in conflicts for value_id in conflict.values}


def _applications(brief: ProjectBrief | None, matrix: RequirementMatrix | None) -> tuple[str, ...]:
    """The project's application codes: the brief's; with no brief, those of the templates the data plan used."""
    if brief is not None:
        return tuple(sorted(application_codes(brief.value("qoi.applications") or ())))
    if matrix is None:
        return ()
    used = {t.split("@", 1)[0] for t in matrix.templates}
    return tuple(sorted({code for t in load_templates() if t["id"] in used and t.get("applies_to") != "all"
                         for code in t.get("applies_to") or ()}))


def _product_tags(reader: LedgerReader, values: Sequence[ValueState]) -> dict[str, str]:
    """The route and food state of the studies whose values name the product (what a product item's `when` reads)."""
    studies = sorted({v.entity.study for v in values if v.entity.study})
    merged: dict[str, set[str]] = {}
    for study in studies:
        tags = study_tags(reader, study, brief=None)
        for tag in ("route", "food_state"):
            if tag in tags:
                merged.setdefault(tag, set()).update(p.strip() for p in tags[tag].split(";"))
    return {tag: "; ".join(sorted(found)) for tag, found in merged.items()}


def _is_solid(label: str, values: Sequence[ValueState], matrix: RequirementMatrix | None) -> bool:
    """Whether a product is solid, as `requirements.derive` decides it: the data plan lists the per-product item for a
    product of that name, or its name, dosage form or release (IR, DR, ER) says so."""
    key = name_key(label)
    if matrix is not None and any(i.product and name_key(i.product) == key for i in matrix.items):
        return True
    texts = [label, *(str(v.value) for v in values if v.field == "dosage_form" and v.value is not None)]
    releases = {str(v.value) for v in values if v.field == "release" and v.value is not None}
    return bool(_SOLID.search(" ".join(texts))) or bool(releases & {"IR", "DR", "ER"})


def _product_req_id(base: str, label: str, matrix: RequirementMatrix | None) -> str:
    """A per-product item's id: the data plan's for a product of the same name, else `<id>@<slug of the label>`."""
    if matrix is not None:
        key = name_key(label)
        for item in matrix.items:
            if item.req_id.partition("@")[0] == base and item.product and name_key(item.product) == key:
                return item.req_id
    return f"{base}@{_slug(label)}"


def _serves() -> tuple[dict[str, str], dict[str, str]]:
    """What each template serves (`requirements.client_request`'s wording) and each item's data category."""
    names = {option.split(" ", 1)[0]: option.split(" ", 1)[1] for option in APPLICATIONS}
    serves: dict[str, str] = {}
    categories: dict[str, str] = {}
    for template in load_templates():
        scope = template.get("applies_to")
        serves[template["id"]] = ("the model itself" if scope == "all"
                                  else " and ".join(names.get(code, code) for code in scope or ()))
        for raw in template["items"]:
            categories.setdefault(raw["id"], raw.get("data_category", "other"))
    return serves, categories
