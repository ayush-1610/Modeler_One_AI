"""Where the page shows each part of a room (plan 2026-11-26 §9, slice 5a): the layers map (`dataroom_layers.yaml`,
`layers.place`) applied to one assembled room, so the page draws what the API says and never places a value itself.

Each section of each group lists what it will hold (`holds`, the map's words, shown while it is empty) and:
- `parts`: what it draws (the question, product values, the composition, substance values, solubility, the dose card,
  dissolution profiles, studies, observed profiles, the BE results, other analytes, files, requests, the plan);
- `values`: the keys of the values placed there (a value's field, `field:<field>`, placed by the map; promoted to Model
  Input Data when the question's applications require it);
- `dissolution`: the dissolution profiles it shows (the selected release inputs under In Vitro Release Input, the rest
  under Dissolution in Other Media and Batches, the map's `unselected`);
- `decisions`: the decisions it holds, each on the value it decides;
- a `count` and a `status` (the room's own status of what it shows, `empty` when it holds nothing).

Today's sections (`DataRoomView.sections`) stay as they were: their findings and statuses are what a layout section
shows; `legacy` names the one an old address (`?section=clinical`) opens.
"""

from __future__ import annotations

from collections.abc import Iterable

from modeler_project.dataroom.layers import Layers, load_layers
from modeler_project.dataroom.model import (
    DataRoomView,
    LayoutGroup,
    LayoutSection,
    NeedItem,
    Problem,
    RoomDecision,
    Value,
)

# what each section draws (the parts of a room view), by the map's group/section
PARTS: dict[str, tuple[str, ...]] = {
    "question/question": ("question", "requirements"),
    "model_input/products": ("products",),
    "model_input/substance": ("substance", "solubility", "dose_card"),
    "model_input/release": ("dissolution", "inputs_choices"),
    "model_input/design": ("studies", "design_values", "inputs_choices"),
    "model_input/observed": ("observed", "be"),
    "model_input/scenarios": ("plan", "inputs"),
    "supporting/formulation_differences": ("products", "composition"),
    "supporting/solid_state": ("substance",),
    "supporting/other_dissolution": ("dissolution", "f2"),
    "supporting/conduct": ("conduct_values", "exclusions"),
    "supporting/other_analytes": ("other_analytes",),
    "supporting/literature": ("adme",),
    "supporting/other_context": ("other_values",),
    "source/files": ("files",),
    "requests/requests": ("requests",),
}
# the room's own section whose status (and finding) a layout section shows, and the old address it answers
LEGACY: dict[str, str] = {
    "question/question": "requirements", "model_input/products": "formulation", "model_input/substance": "substance",
    "model_input/release": "dissolution", "model_input/design": "clinical", "model_input/observed": "observed",
    "model_input/scenarios": "plan", "supporting/formulation_differences": "formulation",
    "supporting/solid_state": "substance", "supporting/other_dissolution": "dissolution", "supporting/conduct": "clinical",
    "supporting/literature": "adme", "source/files": "files", "requests/requests": "requests",
}
# where each old address now opens (the first section that shows it)
OLD_ADDRESSES: dict[str, str] = {"requirements": "question", "formulation": "products", "substance": "substance",
                                 "solubility": "substance", "dissolution": "release", "clinical": "design",
                                 "observed": "observed", "plan": "scenarios", "inputs": "scenarios", "adme": "literature",
                                 "files": "files", "requests": "requests", "decisions": "design"}
# the section each kind of decision belongs to, by its id's prefix
DECISION_SECTION: dict[str, str] = {"analysis-set": "model_input/observed", "analyte": "model_input/observed",
                                    "dose-arms": "model_input/design", "population": "model_input/design",
                                    "sex": "model_input/design", "meal": "model_input/design",
                                    "release": "model_input/release", "release-model": "model_input/release",
                                    "solubility-ref": "model_input/substance", "media-ph-convention": "supporting/other_dissolution",
                                    "applications": "question/question"}
_STATUS_RANK = {"missing": 3, "attention": 2, "ok": 1, "empty": 0}
# where each of the room's own checks is shown (slice 5d): on what it concerns. A check no entry names is about reading
# the files (a refused fact, a line not found, a table read with a problem): shown with the files
CHECK_SECTION: dict[str, str] = {
    "DOSE_BASIS_UNKNOWN": "model_input/substance", "DOSE_BASIS_NEEDS_MW": "model_input/substance",
    "SALT_MW_NOT_HEAVIER": "model_input/substance", "UNIT_UNKNOWN": "model_input/substance",
    "LOT_TWO_PRODUCTS": "model_input/products", "LOT_CONFLICT": "model_input/products",
    "LOOKS_SIMULATED": "model_input/observed",
    "NO_TIME_FOR_VALUES": "model_input/release", "TIME_WITHOUT_VALUES": "model_input/release", "NOT_SINK": "model_input/release",
    "PROFILE_PRODUCT_UNKNOWN": "supporting/other_dissolution",
}
READING_CHECKS = "source/files"
# the checks a person must settle, as "Needs you" names them (slice 5d); the room's other checks are shown on their item
NEEDS_YOU: dict[str, str] = {
    "DOSE_BASIS_UNKNOWN": "Is the dose the salt's or the free base's?",
    "DOSE_BASIS_NEEDS_MW": "The dose needs both molecular weights",
    "SALT_MW_NOT_HEAVIER": "The salt's molecular weight is not above the base's",
    "LOOKS_SIMULATED": "Concentrations that look simulated",
    "LOT_TWO_PRODUCTS": "One lot named for two products",
    "LOT_CONFLICT": "A lot written two ways",
    "FILE_NAMES_NOT_THE_DRUG": "A file that never names the drug",
    "PERSONAL_DATA": "Personal data in the delivery",
    "SAMPLE_CONFLICT": "One sample with two values",
    "SPREADSHEET_ERROR": "A spreadsheet formula error where a value was expected",
    "BE_CSR_DIFFERS": "The bioequivalence result differs from the CSR's",
    "NCA_DIFFERS": "The client's NCA is not reproduced",
    "COMPLETERS_DIFFER": "The completers differ between the report and the data",
    "DOSED_DIFFERS": "The number dosed differs between the report and the data",
    "MEAN_ROW_DIFFERS": "The client's mean row differs from the units",
    "RSD_ROW_DIFFERS": "The client's RSD row differs from the units",
}
# a client's number that the data do not give: said as a conflict to settle, not a check
_DIFFERS = frozenset({"NCA_DIFFERS", "MEAN_ROW_DIFFERS", "RSD_ROW_DIFFERS", "COMPLETERS_DIFFER", "DOSED_DIFFERS", "BE_CSR_DIFFERS"})
# a study's own check, by the section of what it concerns (else Observed PK)
_STUDY_CHECK_SECTION = {"COMPLETERS_DIFFER": "model_input/design", "DOSED_DIFFERS": "model_input/design"}
_SEVERITY_RANK = {"error": 2, "warning": 1, "info": 0}


def _field(value: Value) -> str:
    """A value's vocabulary field: its key without the subject ("substance.pka[drug]" → "substance.pka")."""
    return value.key.split("[", 1)[0]


def _decision_section(d: RoomDecision) -> str:
    return DECISION_SECTION.get(d.id.split(":", 1)[0], "question/question")


def _selected_release(view: DataRoomView) -> set[str]:
    """The dissolution profiles chosen (else suggested) as each product's release input."""
    return {d.chosen or d.suggested for d in view.decisions if d.id.startswith("release:")}


def build_layout(view: DataRoomView, *, required: Iterable[str] = (), layers: Layers | None = None) -> tuple[LayoutGroup, ...]:
    """The room's groups and sections, each with what it shows (`required`: the vocabulary entries the question's
    applications require, `layers.required_keys`)."""
    layers = layers or load_layers()
    need = frozenset(required)
    placed: dict[str, list[str]] = {}

    def put(ref: str, key: str) -> None:
        placed.setdefault(ref, []).append(key)

    for value in (*view.substance, *view.adme, *view.products):
        put(layers.place(f"field:{_field(value)}", required=need).ref, value.key)
    # each study's own values (its design, conduct and population facts); its computed demographics are its design's
    for study in view.studies:
        for value in study.facts:
            ref = ("model_input/design" if value.key.startswith(f"study.{study.study_id}.")
                   else layers.place(f"field:{_field(value)}", required=need).ref)
            put(ref, value.key)
    selected = _selected_release(view)
    dissolution = {"model_input/release": [d.id for d in view.dissolution if d.id in selected],
                   "supporting/other_dissolution": [d.id for d in view.dissolution if d.id not in selected]}
    checks: dict[str, list[int]] = {}
    for i, problem in enumerate(view.problems):
        checks.setdefault(CHECK_SECTION.get(problem.code, READING_CHECKS), []).append(i)
    decisions: dict[str, list[str]] = {}
    for d in view.decisions:
        if not d.on_inputs:              # population, sex and meal template are chosen on Inputs (D1): proposals here
            decisions.setdefault(_decision_section(d), []).append(d.id)
    old = {s.id: s for s in view.sections}
    counts = {
        "question/question": int(view.question is not None),
        "model_input/design": len(view.studies), "model_input/observed": len(view.studies),
        "model_input/scenarios": len(view.plan), "supporting/formulation_differences": len(view.composition),
        "supporting/conduct": sum(len(s.excluded) for s in view.studies), "supporting/other_analytes": len(view.other_analytes),
        "model_input/substance": len(view.solubility) + int(view.dose_card is not None),
        "supporting/other_dissolution": len(view.f2), "source/files": len(view.files), "requests/requests": len(view.requests),
    }
    groups: list[LayoutGroup] = []
    for g in layers.groups:
        sections = []
        for s in g.sections:
            ref = f"{g.id}/{s.id}"
            values = tuple(placed.get(ref, ()))
            profiles = tuple(dissolution.get(ref, ()))
            placed_checks = tuple(checks.get(ref, ()))
            count = counts.get(ref, 0) + len(values) + len(profiles) + len(placed_checks)
            legacy = old.get(LEGACY.get(ref, ""))
            status = (legacy.status if legacy else "ok") if count else "empty"
            sections.append(LayoutSection(
                id=s.id, ref=ref, title=s.title, holds=s.holds, parts=PARTS.get(ref, ("other_values",)), values=values,
                dissolution=profiles, decisions=tuple(decisions.get(ref, ())), checks=placed_checks, count=count, status=status,
                finding=legacy.finding if legacy and count else "", legacy=LEGACY.get(ref, ""),
                answers=tuple(a for a, home in OLD_ADDRESSES.items() if home == s.id)))
        groups.append(LayoutGroup(id=g.id, title=g.title, meaning=g.meaning, sections=tuple(sections),
                                  status=max((x.status for x in sections), key=lambda st: _STATUS_RANK.get(st, 0),
                                             default="empty")))
    return tuple(groups)


def _written(v: Value) -> str:
    return (v.as_written or f"{v.value if v.value is not None else ''} {v.unit}").strip()


def needs_you(view: DataRoomView, layout: Iterable[LayoutGroup]) -> tuple[NeedItem, ...]:
    """What needs a person first (slice 5d), each with the one section where it is done, in this order: the question to
    write or confirm, what holds an error, the values and client numbers that disagree, the checks a person must settle
    (`NEEDS_YOU`), then the decisions waiting (each comes with its suggestion). The population, sex and meal template are
    Inputs' (D1): not here."""
    sections = [s for g in layout for s in g.sections]
    home = {key: s.id for s in sections for key in s.values}
    selected = {d for s in sections if s.id == "release" for d in s.dissolution}
    out: list[NeedItem] = []
    if view.question is None or not view.question.question:
        out.append(NeedItem(id="question", kind="question", title="Write the question the modelling must answer",
                            section="question"))
    elif not view.question_confirmed:
        out.append(NeedItem(id="question", kind="question", title="Confirm the question", detail=view.question.question,
                            section="question"))
    decisions = []
    for d in view.decisions:
        if d.chosen or d.on_inputs:
            continue
        label = next((o.label for o in d.options if o.id == d.suggested), d.suggested)
        decisions.append(NeedItem(id=f"decision:{d.id}", kind="decision", title=d.title,
                                  detail=f"Suggested: {label}" + (f" ({d.why})" if d.why else ""),
                                  section=_decision_section(d).split("/", 1)[1], sources=d.evidence[:3]))
    values = [*view.substance, *view.adme, *view.products, *(v for s in view.studies for v in s.facts)]
    conflicts = [NeedItem(id=f"conflict:{v.key}", kind="conflict", title=f"{v.label}: the sources disagree",
                          detail=" vs ".join(_written(x) for x in (v, *v.others)), section=home.get(v.key, "substance"),
                          sources=(*v.sources, *(c for o in v.others for c in o.sources))[:4])
                 for v in values if v.status == "conflict"]
    # the checks to settle, one line per kind of check on one item (a study, a profile, the delivery)
    grouped: dict[tuple[str, str, str], list[Problem]] = {}
    for p in view.problems:
        if p.code in NEEDS_YOU:
            grouped.setdefault((p.code, "", CHECK_SECTION.get(p.code, READING_CHECKS)), []).append(p)
    for study in view.studies:
        for p in study.problems:
            if p.code in NEEDS_YOU:
                ref = _STUDY_CHECK_SECTION.get(p.code, "model_input/observed")
                grouped.setdefault((p.code, study.study_id, ref), []).append(p)
    for profile in view.dissolution:
        for p in profile.problems:
            if p.code in NEEDS_YOU:
                ref = "model_input/release" if profile.id in selected else "supporting/other_dissolution"
                grouped.setdefault((p.code, f"{profile.batch or profile.product}, {profile.medium}", ref), []).append(p)
    errors, checks = [], []
    for (code, owner, ref), found in grouped.items():
        worst = max((p.severity for p in found), key=lambda sev: _SEVERITY_RANK[sev])
        item = NeedItem(id=f"check:{code}:{owner}", kind="conflict" if code in _DIFFERS else "check",
                        title=(f"{owner}: " if owner else "") + NEEDS_YOU[code], detail=found[0].message,
                        section=ref.split("/", 1)[1], severity=worst, count=len(found),
                        sources=tuple(p.where for p in found if p.where)[:3])
        (errors if worst == "error" else conflicts if item.kind == "conflict" else checks).append(item)
    return (*out, *errors, *conflicts, *checks, *decisions)


def required_from_drafts(items: Iterable[object]) -> frozenset[str]:
    """The vocabulary entries the question requires: the room fields of its requirement items that are required or
    usually needed for it (each item's id is a draft item's, `drafts.Drafts.item`)."""
    from modeler_project.dataroom.drafts import load_drafts
    from modeler_project.dataroom.layers import required_keys

    drafts = load_drafts()
    wanted = [d for i in items if getattr(i, "level", "") in ("required", "usually_needed")
              and (d := drafts.item(getattr(i, "id", ""))) is not None]
    return required_keys(wanted)


__all__ = ["CHECK_SECTION", "DECISION_SECTION", "LEGACY", "NEEDS_YOU", "OLD_ADDRESSES", "PARTS", "READING_CHECKS", "build_layout",
           "needs_you", "required_from_drafts"]
