"""Where the Data room shows each value: its groups and sections (`dataroom_layers.yaml`, plan
docs/plans/2026-11-26-data-room-groups-and-corpus-benchmark.md §3).

The room is organised by what a value is for, not by the file it came from:

- **Question and Context of Use**: what the modelling must answer;
- **Model Input Data**: values from the delivery that parameterise, calibrate or validate the model (sent to Inputs);
- **Supporting Evidence**: values that justify a modelling decision without entering the model;
- **Source Records**: every file, fully read and kept;
- **Data Requests**: what to ask the client.

Code places a value; an agent never does (it says what the value is, `modeler_intake.room_specs`). A placement depends
only on the vocabulary entry (`field:<fact field>` or `table:<kind>`), on the question (an entry the question's
applications require moves to its Model Input Data section when the map allows it, `promote_to`), for a
dissolution entry, on whether its profile is the selected release input (`unselected`) and, for a clinical entry, on
whether its analyte is the one the model simulates (`not_modeled`: a metabolite's profiles are Supporting Evidence).

    layers = load_layers()
    layers.place("field:study.meal_composition")                        # supporting / conduct
    layers.place("field:study.meal_composition", required=need)         # model_input / design, for a food effect
    required_keys(drafts.items_for("food_effect"))                       # the entries a context of use requires
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from functools import lru_cache
from importlib import resources
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

FILE = "dataroom_layers.yaml"
#: the draft statuses that make an entry part of what the question needs
REQUIRING = ("REQUIRED", "USUALLY_NEEDED")
_PREFIXES = ("field:", "table:")


class _B(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SectionDef(_B):
    id: str
    title: str


class GroupDef(_B):
    id: str
    title: str
    meaning: str
    sections: tuple[SectionDef, ...]


class Entry(_B):
    """One vocabulary entry's placement, as `group/section` references."""

    at: str
    promote_to: str | None = None
    unselected: str | None = None
    not_modeled: str | None = None


class Placement(_B):
    """Where one value is shown, and why it is there."""

    group: str
    section: str
    promoted: bool = False           # moved to Model Input Data because the question requires it
    unselected: bool = False         # a dissolution value whose profile is not the selected release input
    not_modeled: bool = False        # a value of an analyte the model does not simulate (a metabolite, a tracer)
    default: bool = False            # an entry the map does not name: the vocabulary is open

    @property
    def ref(self) -> str:
        return f"{self.group}/{self.section}"


class Layers(_B):
    version: str
    groups: tuple[GroupDef, ...]
    default: str
    placements: dict[str, Entry]
    sha256: str = ""

    @model_validator(mode="after")
    def _references(self) -> Layers:
        known = {f"{g.id}/{s.id}" for g in self.groups for s in g.sections}
        ids = [g.id for g in self.groups]
        if len(ids) != len(set(ids)):
            raise ValueError("a group id is used twice")
        sections = [s.id for g in self.groups for s in g.sections]
        if len(sections) != len(set(sections)):
            raise ValueError("a section id is used twice")
        for ref in (self.default, *(r for e in self.placements.values()
                                    for r in (e.at, e.promote_to, e.unselected, e.not_modeled) if r)):
            if ref not in known:
                raise ValueError(f"{ref!r} is not a declared group/section")
        for key, entry in self.placements.items():
            if not key.startswith(_PREFIXES):
                raise ValueError(f"{key!r}: a placement key starts with 'field:' or 'table:'")
            if entry.promote_to and not entry.promote_to.startswith("model_input/"):
                raise ValueError(f"{key}: promote_to must name a Model Input Data section")
            if entry.unselected and not entry.at.startswith("model_input/release"):
                raise ValueError(f"{key}: only a release input entry has an 'unselected' section")
            if entry.not_modeled and not entry.not_modeled.startswith("supporting/"):
                raise ValueError(f"{key}: not_modeled must name a Supporting Evidence section")
        return self

    def group(self, group_id: str) -> GroupDef:
        return next(g for g in self.groups if g.id == group_id)

    def title(self, ref: str) -> str:
        """The section's title for a `group/section` reference."""
        group_id, section_id = ref.split("/", 1)
        return next(s.title for s in self.group(group_id).sections if s.id == section_id)

    def place(self, key: str, *, required: Iterable[str] = (), selected: bool = True, modeled: bool = True) -> Placement:
        """Where the value of vocabulary entry `key` is shown. `required`: the entries the question's applications
        require (`required_keys`); `selected`: for a dissolution entry, whether its profile is the release input;
        `modeled`: for a clinical entry, whether its analyte is the one the model simulates (decision analyte:<study>)."""
        entry = self.placements.get(key)
        if entry is None:
            group, section = self.default.split("/", 1)
            return Placement(group=group, section=section, default=True)
        ref, promoted, unselected, not_modeled = entry.at, False, False, False
        if entry.not_modeled and not modeled:
            ref, not_modeled = entry.not_modeled, True
        elif entry.unselected and not selected:
            ref, unselected = entry.unselected, True
        elif entry.promote_to and key in set(required):
            ref, promoted = entry.promote_to, True
        group, section = ref.split("/", 1)
        return Placement(group=group, section=section, promoted=promoted, unselected=unselected, not_modeled=not_modeled)


@lru_cache(maxsize=1)
def load_layers() -> Layers:
    """The map, read once and checked: every reference names a declared section."""
    text = resources.files("modeler_project.dataroom").joinpath(FILE).read_text(encoding="utf-8")
    raw: dict[str, Any] = yaml.safe_load(text)
    return Layers(**raw, sha256=hashlib.sha256(text.encode()).hexdigest())


def required_keys(items: Iterable[Any]) -> frozenset[str]:
    """The field and table entries the given requirement-draft items need (`DraftItem`: REQUIRED or USUALLY_NEEDED),
    in the map's `field:` / `table:` form."""
    return frozenset(r for item in items if getattr(item, "status", "") in REQUIRING
                     for r in getattr(item, "room_fields", ()) if r.startswith(_PREFIXES))


__all__ = ["FILE", "REQUIRING", "Entry", "GroupDef", "Layers", "Placement", "SectionDef", "load_layers", "required_keys"]
