"""The requirement drafts per context of use (the owner's decision D5, 2026-11-24), loaded for the Data room's checklist.

The drafts live in ``pbpk_domain.requirement_drafts.context_of_use`` and stay UNVERIFIED: drafted from the literature,
awaiting the owner's and the SME's review. The Data room shows them, labelled so (`LABEL`), as the checklist of what
the question needs (`modeler_project.dataroom.checklist`). No data plan, client request of the data plan,
reconciliation, gate or live template reads them: ``modeler_project.requirements.load_templates`` still lists only
the locked templates, and every draft's ``applies_to`` stays empty.

`load_drafts` reads the twelve files once, checks their shape (the item keys ``core.yaml`` documents, the five
statuses, a trigger in the grammar over the property vocabulary on every CONDITIONAL item and on no other, overrides
that name core items, room fields in the Data room's vocabulary, sub-contexts their file declares) and refuses a file
that breaks it. `Drafts.items_for` gives a context of use's list: the core items it does not override, then its own.
"""

from __future__ import annotations

from functools import lru_cache
from importlib import resources
from typing import Any, Literal, get_args

import yaml
from pydantic import BaseModel, ConfigDict

from modeler_intake.room_specs import FIELDS, TOPICS, TableKind

PACKAGE = "pbpk_domain.requirement_drafts.context_of_use"
COU_FILES = ("ddi_victim", "ddi_perpetrator", "transporter_ddi", "food_effect", "pediatric", "organ_impairment",
             "pbbm_bridging_vbe", "acid_reducing_agents", "fih_dose_prediction", "special_populations")
#: how the page and every request name the drafts' standing
LABEL = "draft, UNVERIFIED (awaiting the owner's and the SME's review)"

Status = Literal["REQUIRED", "USUALLY_NEEDED", "CONDITIONAL", "OPTIONAL", "NOT_NEEDED"]
Kind = Literal["parameter", "dataset", "formulation", "system", "activity"]
_ROOM = {"field": set(FIELDS), "table": set(get_args(TableKind)), "topic": set(TOPICS)}
# a draft item's keys, as core.yaml documents them, and the names they take here
_RENAMED = {"cou_status": "status", "escalates_to_required_when": "escalates"}


class DraftError(ValueError):
    """A draft file that breaks the shape core.yaml documents."""


class _B(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Condition(_B):
    """One leaf of a trigger: a property compared with a value; ``sme``: a cut-off the SME sets, none written."""

    property: str
    test: Literal["equals", "in", "any_of", "above", "below", "sme"]
    value: bool | str | float | tuple[str, ...] | None = None
    direction: Literal["above", "below", ""] = ""
    source: str = ""                  # the threshold_source of a cut-off a cited source states


class Trigger(_B):
    """A CONDITIONAL item's trigger: ``any`` or ``all`` of its parts, or one condition (``is``)."""

    op: Literal["any", "all", "is"]
    parts: tuple[Trigger, ...] = ()
    condition: Condition | None = None

    def conditions(self) -> tuple[Condition, ...]:
        return (self.condition,) if self.condition else tuple(c for p in self.parts for c in p.conditions())


class DraftItem(_B):
    id: str
    file: str                         # the draft it is in: core, a context of use, or context_only
    label: str
    group: str
    kind: Kind
    status: Status
    why: str
    alternatives: tuple[str, ...] = ()
    room_fields: tuple[str, ...] = ()
    room_gap: bool | None = None
    data_category: str
    default_provider: str
    sources: tuple[str, ...]
    note: str
    record_with: tuple[str, ...] = ()
    subcontext: str = ""
    overrides: tuple[str, ...] = ()
    escalates: str = ""
    trigger_text: str = ""
    trigger: Trigger | None = None
    kept_as: str = ""
    trigger_request_text: str = ""
    triggers_request_for: tuple[str, ...] = ()
    context_for: tuple[str, ...] = ()


class PropertyDef(_B):
    name: str
    about: str
    type: str
    how: Literal["code", "brief", "ask"]
    determined_by: str
    room_fields: tuple[str, ...] = ()
    brief_fields: tuple[str, ...] = ()


class DraftFile(_B):
    name: str
    id: str
    version: str
    status: str
    context_of_use: str
    subcontexts: dict[str, str] = {}
    items: tuple[DraftItem, ...]


class Drafts(_B):
    core: DraftFile
    files: dict[str, DraftFile]       # the contexts of use, by file name
    context_only: DraftFile
    properties: dict[str, PropertyDef]

    def version(self) -> str:
        versions = sorted({f.version for f in (self.core, self.context_only, *self.files.values())})
        return f"requirement drafts per context of use {', '.join(versions)} ({self.core.status})"

    def items_for(self, file: str, subcontext: str = "") -> tuple[DraftItem, ...]:
        """A context of use's list: the core items it does not override, then its own items (of `subcontext` alone when
        one is named). An unknown file or sub-context is refused."""
        cou = self.files.get(file)
        if cou is None:
            raise KeyError(f"no requirement draft for {file!r}")
        if subcontext and subcontext not in cou.subcontexts:
            raise KeyError(f"{file} has no sub-context {subcontext!r}")
        own = tuple(i for i in cou.items if not subcontext or i.subcontext == subcontext)
        overridden = {target for i in own for target in i.overrides}
        return tuple(i for i in self.core.items if i.id not in overridden) + own

    def item(self, item_id: str) -> DraftItem | None:
        return next((i for f in (self.core, self.context_only, *self.files.values()) for i in f.items if i.id == item_id),
                    None)


def _trigger(node: Any, where: str) -> Trigger:
    if not isinstance(node, dict) or not node:
        raise DraftError(f"{where}: a trigger is a mapping")
    for op in ("any", "all"):
        if op in node:
            parts = node[op]
            if len(node) != 1 or not isinstance(parts, list) or len(parts) < 2:
                raise DraftError(f"{where}: '{op}' takes a list of two conditions or more, and nothing beside it")
            return Trigger(op=op, parts=tuple(_trigger(p, where) for p in parts))
    keys = set(node)
    tests = keys & {"equals", "in", "any_of", "above", "below", "threshold"}
    if "property" not in node or len(tests) != 1 or keys - tests - {"property", "threshold_source", "direction"}:
        raise DraftError(f"{where}: a condition names one property and one test: {node}")
    (test,) = tests
    value = node[test]
    if test == "threshold":
        if value != "SME" or node.get("direction") not in ("above", "below") or "threshold_source" in node:
            raise DraftError(f"{where}: an SME cut-off is written {{direction: above|below, threshold: SME}}")
        return Trigger(op="is", condition=Condition(property=node["property"], test="sme", direction=node["direction"]))
    if test in ("above", "below"):
        if isinstance(value, bool) or not isinstance(value, int | float) or not str(node.get("threshold_source", "")).strip():
            raise DraftError(f"{where}: a number in a trigger needs the source that states it")
        return Trigger(op="is", condition=Condition(property=node["property"], test=test, value=float(value),
                                                    source=str(node["threshold_source"])))
    if "direction" in node or "threshold_source" in node:
        raise DraftError(f"{where}: direction and threshold_source go with a cut-off only")
    if test in ("in", "any_of"):
        if not isinstance(value, list) or not value:
            raise DraftError(f"{where}: '{test}' takes a list")
        value = tuple(str(v) for v in value)
    elif not isinstance(value, bool | str):
        raise DraftError(f"{where}: 'equals' takes true, false or a word")
    return Trigger(op="is", condition=Condition(property=node["property"], test=test, value=value))


def _item(raw: dict[str, Any], file: str, documented: set[str]) -> DraftItem:
    where = f"{file}.yaml {raw.get('id', '?')}"
    unknown = set(raw) - documented
    if unknown:
        raise DraftError(f"{where}: keys core.yaml does not document: {sorted(unknown)}")
    data = {_RENAMED.get(k, k): v for k, v in raw.items()}
    if "trigger" in data:
        data["trigger"] = _trigger(data["trigger"], where)
    if isinstance(data.get("overrides"), str):
        data["overrides"] = [data["overrides"]]
    for key in ("alternatives", "room_fields", "sources", "record_with", "overrides", "triggers_request_for", "context_for"):
        if key in data:
            data[key] = tuple(data[key])
    try:
        item = DraftItem.model_validate({**data, "file": file})
    except ValueError as e:
        raise DraftError(f"{where}: {e}") from e
    if (item.status == "CONDITIONAL") != (item.trigger is not None) or (item.status == "CONDITIONAL") != bool(item.trigger_text):
        raise DraftError(f"{where}: a trigger (with its words) on a CONDITIONAL item, and on no other")
    if (item.status == "USUALLY_NEEDED") != bool(item.escalates):
        raise DraftError(f"{where}: when it becomes REQUIRED, on a USUALLY_NEEDED item, and on no other")
    for entry in item.room_fields:
        prefix, _, value = entry.partition(":")
        if value not in _ROOM.get(prefix, set()):
            raise DraftError(f"{where}: {entry!r} is not in the Data room's vocabulary")
    return item


def _file(name: str, documented: set[str]) -> tuple[DraftFile, dict[str, Any]]:
    raw = yaml.safe_load(resources.files(PACKAGE).joinpath(f"{name}.yaml").read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("applies_to") != [] or not str(raw.get("status", "")).startswith("DRAFT"):
        raise DraftError(f"{name}.yaml: a draft is DRAFT_UNVERIFIED and applies to no project")
    items = tuple(_item(i, name, documented) for i in raw.get("items") or ())
    subcontexts = {str(k): str(v) for k, v in (raw.get("subcontexts") or {}).items()}
    for item in items:
        if (item.subcontext or None) not in ({None} if not subcontexts else set(subcontexts)):
            raise DraftError(f"{name}.yaml {item.id}: sub-context {item.subcontext!r} is not one the file declares")
    return DraftFile(name=name, id=raw["id"], version=str(raw["version"]), status=raw["status"],
                     context_of_use=raw["context_of_use"], subcontexts=subcontexts, items=items), raw


@lru_cache(maxsize=1)
def load_drafts() -> Drafts:
    """The twelve drafts, read once and checked; a file that breaks the documented shape raises `DraftError`."""
    core_raw = yaml.safe_load(resources.files(PACKAGE).joinpath("core.yaml").read_text(encoding="utf-8"))
    documented = set(core_raw["item_keys"])
    core, _ = _file("core", documented)
    files = {name: _file(name, documented)[0] for name in COU_FILES}
    context_only, _ = _file("context_only", documented)
    properties = {name: PropertyDef(name=name, **{k: tuple(v) if isinstance(v, list) else v for k, v in d.items()})
                  for name, d in core_raw["properties"].items()}
    every = [core, context_only, *files.values()]
    ids = [i.id for f in every for i in f.items]
    if len(ids) != len(set(ids)):
        raise DraftError("an item id appears twice across the drafts")
    core_ids = {i.id for i in core.items}
    for f in every:
        for item in f.items:
            if item.overrides and (f.name not in COU_FILES or not set(item.overrides) <= core_ids):
                raise DraftError(f"{f.name}.yaml {item.id}: only a context of use overrides, and only core items")
            for c in item.trigger.conditions() if item.trigger else ():
                if c.property not in properties:
                    raise DraftError(f"{f.name}.yaml {item.id}: the trigger names {c.property!r}, not in the vocabulary")
            if item.kept_as and f.name != "context_only":
                raise DraftError(f"{f.name}.yaml {item.id}: only context_only.yaml keeps material as context")
    return Drafts(core=core, files=files, context_only=context_only, properties=properties)


__all__ = ["COU_FILES", "LABEL", "Condition", "DraftError", "DraftFile", "DraftItem", "Drafts", "PropertyDef", "Trigger",
           "load_drafts"]
