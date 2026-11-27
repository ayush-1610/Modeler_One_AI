"""Where the page shows each part of a room (plan 2026-11-26 §9, slice 5a): the layers map (`dataroom_layers.yaml`,
`layers.place`) applied to one assembled room, so the page draws what the API says and never places a value itself.

Each section of each group lists:
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
from modeler_project.dataroom.model import DataRoomView, LayoutGroup, LayoutSection, RoomDecision, Value

# what each section draws (the parts of a room view), by the map's group/section
PARTS: dict[str, tuple[str, ...]] = {
    "question/question": ("question", "requirements"),
    "model_input/products": ("products",),
    "model_input/substance": ("substance", "solubility", "dose_card"),
    "model_input/release": ("dissolution",),
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
            count = counts.get(ref, 0) + len(values) + len(profiles)
            legacy = old.get(LEGACY.get(ref, ""))
            status = (legacy.status if legacy else "ok") if count else "empty"
            sections.append(LayoutSection(
                id=s.id, ref=ref, title=s.title, parts=PARTS.get(ref, ("other_values",)), values=values,
                dissolution=profiles, decisions=tuple(decisions.get(ref, ())), count=count, status=status,
                finding=legacy.finding if legacy and count else "", legacy=LEGACY.get(ref, ""),
                answers=tuple(a for a, home in OLD_ADDRESSES.items() if home == s.id)))
        groups.append(LayoutGroup(id=g.id, title=g.title, meaning=g.meaning, sections=tuple(sections),
                                  status=max((x.status for x in sections), key=lambda st: _STATUS_RANK.get(st, 0),
                                             default="empty")))
    return tuple(groups)


def required_from_drafts(items: Iterable[object]) -> frozenset[str]:
    """The vocabulary entries the question requires: the room fields of its requirement items that are required or
    usually needed for it (each item's id is a draft item's, `drafts.Drafts.item`)."""
    from modeler_project.dataroom.drafts import load_drafts
    from modeler_project.dataroom.layers import required_keys

    drafts = load_drafts()
    wanted = [d for i in items if getattr(i, "level", "") in ("required", "usually_needed")
              and (d := drafts.item(getattr(i, "id", ""))) is not None]
    return required_keys(wanted)


__all__ = ["DECISION_SECTION", "LEGACY", "OLD_ADDRESSES", "PARTS", "build_layout", "required_from_drafts"]
