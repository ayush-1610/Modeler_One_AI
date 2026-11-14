"""Which requirement templates a study activates, and the schema gaps (plan G4, contracts §6.4).

G4 is judged per study, never globally (the owner's decision 1): each study is checked against the templates that its
own routing activates, and a study whose routing no authored template covers is a schema gap, which blocks release
and is never counted as done against another checklist.

A study's tags are its own facts (`species`, `population`, `special_population`, `route`, `food_state`,
`formulation`, `design`, `co_medication`, `genotype`) and two of the project's brief (`modality`, `applications`); a
tag no fact states is absent, never assumed. A choice field's value is read as one of its choices (`fields.read_choice`);
a text that states none of them, or several, is kept as written and is *unread* (`unread`): never coerced to "other",
so a route written "intravenous" (bolus or infusion?) is not taken for route other, nor a food state written
"postprandial" for fasted. A routing tag the rules or a `when` read whose value is unread is a schema gap naming the
text, until a person states the value; a `when` that reads it is undetermined. A bool is a statement of presence (True:
"yes") or absence (False: absent). A study whose facts state several values of one tag (a fasted and a fed arm)
carries them all, joined by "; ".

Statements of absence written as text ("none", "n/a", "not genotyped") are not read as absence: the rules file has no
list of them, and D5 writes none (the SME's rules). So a co-medication written "none" passes `present: true`, and a
species written "Humans" fails `not_in: [Human]` (tags compare by name_key, with no synonyms). Both are recorded by a
test and reported to the integrator.

The templates a study activates (`route`): the rules file's `routing.core`, the templates the project's applications
select (`requirements.load_templates()`, `applies_to` against the applications: read-only reuse), and every
`routing.by_tag` template whose tag test the study passes. A tag matching `routing.gaps`, a study with no route fact,
or a template the rules name that is not loaded, is a `SchemaGap`. The routing table is the rules file's
(`intake_rules.yaml`, UNVERIFIED): nothing here names a template, a tag value or an APP code.

A requirement item's `when` is evaluated per study (`study_when`): its route and food keys with the study's own route
and food state, every other key with the brief (`requirements.evaluate_when`, one key at a time). The food key never
takes the brief's food state, so a fasted study of a food-effect project is not treated as fed.

`subject_values` and `study_matrix` are the small read helpers the other D5 modules share.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from typing import Any, Literal

from modeler_intake.document_reading import name_key
from modeler_intake.fields import field as field_def
from modeler_intake.fields import read_choice
from modeler_project.brief import ProjectBrief
from modeler_project.intake_records import Routing, SchemaGap
from modeler_project.intake_rules import IntakeRules, TagRule
from modeler_project.intake_rules import rules as load_rules
from modeler_project.ledger_models import ValueState
from modeler_project.ledger_view import LedgerReader, is_spread_fact
from modeler_project.requirements import evaluate_when, load_templates

SubjectType = Literal["study", "product", "compound"]
# A study's own tags, each read from the active values of the field of that name
FACT_TAGS = ("species", "population", "special_population", "route", "food_state", "formulation", "design",
             "co_medication", "genotype")
# The brief's tags
BRIEF_TAGS = ("modality", "applications")
SEPARATOR = "; "                          # several values of one tag (a fasted and a fed arm)
NO_ROUTE = "no route is stated for this study"
PRESENT = "yes"                           # a bool True as a tag: the thing is stated present


# --- the subject's values (shared by the D5 modules) ------------------------------------------------------------------


def subject_values(reader: LedgerReader, subject_type: SubjectType, subject: str, *, field: str | None = None,
                   spread_facts: bool = False) -> list[ValueState]:
    """The active values of a subject (§6.6): a study's, a product's, or the compound's (subject id "compound"); a
    derived spread fact only on request (it qualifies the value it derives from and is never a value of its own)."""
    if subject_type == "study":
        found = reader.values(study=subject, field=field)
    elif subject_type == "product":
        found = reader.values(product=subject, field=field)
    elif subject_type == "compound":
        found = reader.values(compound=True, field=field)
    else:
        raise ValueError(f"a subject is a study, a product or the compound, not {subject_type!r}")
    return [v for v in found if spread_facts or not is_spread_fact(v)]


def stated(value: ValueState) -> bool:
    """Whether a value states something: a value, or a censored one (a BLQ states that it is below its LLOQ)."""
    return value.censored or (value.value is not None and str(value.value).strip() != "")


def matrix_choice(label: str | None) -> str | None:
    """A matrix label as the matrix field's choice ("whole blood" -> blood), else the label as written."""
    if label is None or not label.strip():
        return None
    return read_choice("matrix", label) or label.strip()


def study_matrix(values: Iterable[ValueState]) -> str | None:
    """A study's single stated matrix (§4.5 and `EntityRef`: a value with no matrix label takes its study's single
    active `matrix` fact; none: MATRIX_MISSING): from its `matrix` facts only, as the landing reads it (an LLOQ's
    matrix label says which profile the LLOQ is for, not the matrix of values that state none); None when the study
    states none or several."""
    found = {choice for value in values if value.field == "matrix" and stated(value)
             if (choice := matrix_choice(str(value.value))) is not None}
    return found.pop() if len(found) == 1 else None


# --- tags ------------------------------------------------------------------------------------------------------------


def study_tags(reader: LedgerReader, study: str, *, brief: ProjectBrief | None) -> dict[str, str]:
    """The study's routing tags: its own facts (species, population, special_population, route, food_state,
    formulation, design, co_medication, genotype) and the brief's modality and applications. A tag no fact states is
    absent; several values of one tag are joined by "; " in sorted order."""
    tags: dict[str, str] = {}
    for name in FACT_TAGS:
        found = sorted({t for v in reader.values(study=study, field=name) if not is_spread_fact(v)
                        if (t := tag_value(name, v.value)) is not None})
        if found:
            tags[name] = SEPARATOR.join(found)
    if brief is not None:
        modality = brief.value("drug.modality")
        if modality is not None and str(modality).strip():
            tags["modality"] = str(modality).strip()
        codes = sorted(application_codes(brief.value("qoi.applications") or ()))
        if codes:
            tags["applications"] = SEPARATOR.join(codes)
    return tags


def tag_value(field: str, value: Any) -> str | None:
    """A fact's value as a tag: a choice field's choice (`fields.read_choice`), else the text as written, which for a
    choice field is unread (`unread`), never coerced to a choice; a bool True is "yes" (stated present), False and an
    empty value None (absent)."""
    if isinstance(value, bool):
        text = PRESENT if value else ""
    else:
        text = "" if value is None else str(value).strip()
    if not text:
        return None
    definition = field_def(field)
    if definition is not None and definition.value == "choice":
        if text in definition.choices:
            return text
        return read_choice(field, text) or text
    return text


def unread(tag: str, value: str) -> bool:
    """Whether a tag value is unread: its field is a choice field and the value is none of its choices (the text as
    written, which `read_choice` could not read as one choice)."""
    definition = field_def(tag)
    return definition is not None and definition.value == "choice" and value not in definition.choices


def tag_values(tags: Mapping[str, str], tag: str) -> tuple[str, ...]:
    """The values of one tag (several are joined by "; ")."""
    text = tags.get(tag, "")
    return tuple(part.strip() for part in text.split(SEPARATOR.strip()) if part.strip())


def application_codes(applications: Iterable[str]) -> set[str]:
    """The APP codes of a list of applications as the brief writes them ("APP-14 virtual bioequivalence" -> APP-14)."""
    return {str(a).strip().split(" ", 1)[0] for a in applications if str(a).strip()}


# --- routing ---------------------------------------------------------------------------------------------------------


def route(study: str, tags: Mapping[str, str], *, applications: Collection[str],
          rules: IntakeRules | None = None) -> Routing:
    """The templates a study activates and its schema gaps (see the module docstring), from the rules file's
    `routing`: the core, the templates the project's applications select, the `by_tag` templates its tags pass; the
    `gaps` its tags match, no route stated, a routing tag whose value is unread (`unread`: a tag the rules' `by_tag`
    or `gaps`, or a `when`, read), or a template the rules name that is not loaded."""
    rules = rules or load_rules()
    templates = {t["id"]: t for t in load_templates()}
    codes = application_codes(applications)
    activated: list[str] = []
    gaps: list[SchemaGap] = []
    if rules.routing.core in templates:
        activated.append(rules.routing.core)
    else:
        gaps.append(SchemaGap(study=study, tag="core", value=rules.routing.core,
                              reason=f"routing.core names {rules.routing.core!r}, which is not a loaded template"))
    for template in templates.values():
        scope = template.get("applies_to")
        if scope != "all" and codes & set(scope or ()):
            activated.append(template["id"])
    for rule in rules.routing.by_tag:
        matched = tag_match(rule, tags)
        if matched is None or rule.template is None:
            continue
        if rule.template in templates:
            activated.append(rule.template)
        else:
            gaps.append(SchemaGap(study=study, tag=rule.tag, value=matched,
                                  reason=f"routing.by_tag names {rule.template!r}, which is not a loaded template"))
    for rule in rules.routing.gaps:
        matched = tag_match(rule, tags)
        if matched is not None:
            gaps.append(SchemaGap(study=study, tag=rule.tag, value=matched, reason=rule.reason or "routing.gaps"))
    if not tag_values(tags, "route"):
        gaps.append(SchemaGap(study=study, tag="route", value="", reason=NO_ROUTE))
    read = dict.fromkeys((*(r.tag for r in (*rules.routing.by_tag, *rules.routing.gaps)), *_OWN_KEYS.values()))
    for tag in read:
        for value in tag_values(tags, tag):
            if unread(tag, value):
                gaps.append(SchemaGap(study=study, tag=tag, value=value, reason=unread_reason(tag, value)))
    return Routing(study=study, tags=dict(tags), templates=tuple(dict.fromkeys(activated)), gaps=tuple(gaps))


def unread_reason(tag: str, value: str) -> str:
    """The reason of the schema gap of an unread routing tag: the text as written and the choices it is none of."""
    definition = field_def(tag)
    choices = ", ".join(definition.choices) if definition is not None else ""
    return f"{tag} written {value!r} reads as none (or more than one) of {choices}: a person states it"


def tag_match(rule: TagRule, tags: Mapping[str, str]) -> str | None:
    """The tag values a rule of `routing.by_tag` or `routing.gaps` matches ("; "-joined), "" when it matches an absent
    tag (`present: false`), None when it does not match. `present`: the tag is stated (or not); `in`: one of its values
    is listed; `not_in`: one of its values is not listed (an absent tag matches neither). Values compare by name_key."""
    values = tag_values(tags, rule.tag)
    if rule.present is True and not values:
        return None
    if rule.present is False and values:
        return None
    hits = list(values)
    if rule.in_ is not None:
        listed = {name_key(x) for x in rule.in_}
        hits = [v for v in hits if name_key(v) in listed]
        if not hits:
            return None
    if rule.not_in is not None:
        listed = {name_key(x) for x in rule.not_in}
        hits = [v for v in hits if name_key(v) not in listed]
        if not hits:
            return None
    return SEPARATOR.join(hits)


# --- `when`, per study -----------------------------------------------------------------------------------------------

# The `when` keys a study's own tags answer: route from its route, food from its food state
_OWN_KEYS = {"route": "route", "food": "food_state"}


def study_when(when: Mapping[str, Any] | None, tags: Mapping[str, str], *, brief: ProjectBrief | None) -> bool | None:
    """A requirement item's `when`, for one study: True, False, or None (undetermined). The route and food keys are
    answered by the study's own route and food state (absent, or a value that is unread and none of the listed ones
    matched: undetermined); every other key by the brief, one key at a time through `requirements.evaluate_when` (no
    brief: undetermined). Never the brief's food state for a study: a fasted study of a food-effect project is not fed.
    Keys are ANDed as `evaluate_when` does."""
    if not when:
        return True
    results: list[bool | None] = []
    for key, wanted in when.items():
        if key in _OWN_KEYS:
            tag = _OWN_KEYS[key]
            values = tag_values(tags, tag)
            known = {name_key(v) for v in values if not unread(tag, v)}
            listed = {name_key(str(w)) for w in (wanted if isinstance(wanted, list | tuple) else (wanted,))}
            if known & listed:
                results.append(True)
            elif not values or len(known) < len(values):
                results.append(None)
            else:
                results.append(False)
        else:
            results.append(None if brief is None else evaluate_when({key: wanted}, brief))
    if any(r is False for r in results):
        return False
    return None if any(r is None for r in results) else True
