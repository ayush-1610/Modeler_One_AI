"""Entity resolution for the ledger (contracts §6.3): studies, arms, products, batches and analytes.

An entity is named by a label read from a cell or a sentence, and is resolved by code, never by similarity. Two labels
name one entity when their `label_key` is the same: `name_key` (case, spaces and punctuation aside), except that two
runs of digits the label writes apart stay apart, so "EXA-1-2" is not "EXA-12" and "230-23" not "23023" ("EXA-101" and
"EXA101" are one). The order:

1. inside the file first: the same `label_key` under the same parent among the entities whose home file is this one
   (an entity's home file is the file of its source anchor);
2. an arm or a batch, given its parent, inside that parent: the parent study or product scopes it, whichever file
   names it (the parent itself only ever spans files through an anchored link, below);
3. an alias: one a person confirmed in today's review record (`client_data.review_record`: `aliases`,
   `product_aliases`, `batch_aliases`), or a ledger alias (an `alias` line of entities.jsonl). Resolving through a
   review alias writes that alias into the ledger (source "review:<list>"), so the ledger says why;
4. a study only: ANOTHER file's study with the same key or a confirmed alias. Exactly one: that study is returned with
   a `link.study_id` fact anchored at this label's cell (a label this file already linked keeps its study, so a later
   file never makes an earlier link ambiguous). Two or more: a new file-local study, and the ledger's pending links
   show it as ambiguous (nothing is joined);
5. else a new entity, its source the anchor of the label.

Matrix, subject, period, sequence, occasion and vessel are labels on `EntityRef`, never entities. An upload tag, a drug
name or a date never joins anything: the only cross-file join of a study is an anchored link (§6.3, the owner's five
conditions). Get-or-create runs under `entities.append_if`, so two threads resolving one label create one entity.

`merge` joins two entities of one type (a link fact's study into the study it names, or a person's merge): both ids
stay resolvable (`LedgerView.entity` follows merges), and a merged entity is never merged again elsewhere. A merged
study's arm (a merged product's batch) with the name of one inside the target is merged with it in the same write: an
arm is resolved inside its study.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from modeler_intake.anchors import AnchorError, parse_anchor
from modeler_intake.document_reading import name_key
from modeler_project.intake_store import ChainEntry
from modeler_project.ledger_models import Alias, Entity, EntityRef, EntityType, Fact, MappingUse, Merge, Method, ModelUse

if TYPE_CHECKING:
    from modeler_project.ledger import Ledger

PREFIX: Mapping[str, str] = MappingProxyType({"study": "st", "arm": "arm", "product": "pr", "batch": "ba", "analyte": "an"})
# the review record's list of person-confirmed aliases for each type (client_review.ALIASES names them by link issue)
REVIEW_LISTS: Mapping[str, str] = MappingProxyType({"study": "aliases", "product": "product_aliases", "batch": "batch_aliases"})
# the types resolved inside their parent (an arm inside its study, a batch inside its product)
PARENTED = frozenset(("arm", "batch"))
CHILD: Mapping[str, EntityType] = MappingProxyType({"study": "arm", "product": "batch"})
_RUNS = re.compile(r"[A-Z0-9]+")


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def label_key(label: Any) -> str:
    """A label as resolution compares it: its `name_key`, with a "." kept between two runs of digits the label writes
    apart. `name_key` alone makes "EXA-1-2" and "EXA-12" (or "230-23" and "23023") one name; the digits of a study, an
    arm or a batch code are what tells two of them apart. Letters beside digits need no mark ("EXA-101" is "EXA101")."""
    out = ""
    for run in _RUNS.findall(str(label).upper()):
        if out and out[-1].isdigit() and run[0].isdigit():
            out += "."
        out += run
    return out


def home_file(entity: Entity) -> str | None:
    """The sha256 of an entity's home file: the file of its source anchor (None: a person's entity)."""
    if entity.source is None:
        return None
    try:
        return parse_anchor(entity.source).file_sha256
    except AnchorError:
        return None


class EntityBook:
    """The entities log folded: every entity line (merged ones included), the merges and the ledger aliases."""

    def __init__(self, entries: list[ChainEntry]):
        self.entities: dict[str, Entity] = {}
        self.merges: dict[str, Merge] = {}
        self.aliases: list[Alias] = []
        for line in entries:
            if line.kind == "entity":
                entity = Entity.model_validate(line.body)
                self.entities[entity.id] = entity
            elif line.kind == "merge":
                merge = Merge.model_validate(line.body)
                self.merges.setdefault(merge.from_id, merge)
            elif line.kind == "alias":
                self.aliases.append(Alias.model_validate(line.body))

    @property
    def merged(self) -> dict[str, str]:
        return {source: m.into_id for source, m in self.merges.items()}

    def follow(self, entity_id: str | None) -> str | None:
        """The id an entity id resolves to after merges (itself when it was never merged)."""
        seen = set()
        while entity_id is not None and entity_id in self.merges and entity_id not in seen:
            seen.add(entity_id)
            entity_id = self.merges[entity_id].into_id
        return entity_id

    def alive(self, entity_id: str | None) -> Entity | None:
        """The entity an id resolves to after merges."""
        found = self.follow(entity_id)
        return self.entities.get(found) if found is not None else None

    def named(self, type: EntityType, keys: frozenset[str], parent: str | None) -> list[Entity]:
        """Every entity line of `type` whose label has one of these `label_key`s, under this parent (parents followed
        through merges), in the order they were created."""
        return [e for e in self.entities.values()
                if e.type == type and label_key(e.label) in keys and self.follow(e.parent) == parent]


def follow_ref(ref: EntityRef, merged: Mapping[str, str]) -> EntityRef:
    """An EntityRef with its entity ids followed through merges."""
    def follow(entity_id: str | None) -> str | None:
        seen = set()
        while entity_id is not None and entity_id in merged and entity_id not in seen:
            seen.add(entity_id)
            entity_id = merged[entity_id]
        return entity_id

    parts = {part: follow(getattr(ref, part)) for part in ("study", "arm", "product", "batch", "analyte")
             if getattr(ref, part) is not None}
    return ref.model_copy(update=parts) if parts else ref


def review_targets(type: EntityType, key: str, parent: Entity | None, review: Mapping[str, Any]) -> frozenset[str]:
    """The `label_key`s a person-confirmed alias of today's review record sends this `label_key` to (a batch alias is
    kept within its product: "<product key>|<batch>")."""
    listed = review.get(REVIEW_LISTS.get(type, ""), {}) if type in REVIEW_LISTS else {}
    if not isinstance(listed, Mapping):
        return frozenset()
    found = set()
    for raw, target in listed.items():
        raw = str(raw)
        if type == "batch":
            product_key, _, raw = raw.partition("|")
            if parent is None or product_key != parent.key:
                continue
        if label_key(raw) == key and label_key(target) and label_key(target) != key:
            found.add(label_key(target))
    return frozenset(found)


def _linked_study(ledger: Ledger, key: str, file_sha256: str) -> tuple[str, Fact] | None:
    """A `link.study_id` fact this file already holds for this label, not superseded or excluded: the study it joined."""
    lines = ledger.store.facts.entries()
    gone = {line.body["supersedes"] for line in lines if line.kind == "fact" and line.body.get("supersedes")}
    status: dict[str, str] = {}
    for line in lines:
        if line.kind == "status":
            status[line.body["target"]] = line.body["status"]
    for line in lines:
        body = line.body
        if line.kind != "fact" or body.get("field") != "link.study_id" or not body.get("anchor"):
            continue
        if body["id"] in gone or status.get(body["id"]) == "excluded":
            continue
        try:
            same_file = parse_anchor(body["anchor"]).file_sha256 == file_sha256
        except AnchorError:
            continue
        if same_file and label_key(body.get("value")) == key and body.get("entity", {}).get("study"):
            return body["entity"]["study"], Fact.model_validate(body)
    return None


def resolve(ledger: Ledger, *, type: EntityType, label: str, parent: str | None = None, source: str | None,
            file_sha256: str | None, by: str, delivery: str = "", run_id: str | None = None, method: Method = "cell",
            mapping: MappingUse | None = None, model: ModelUse | None = None,
            review: Mapping[str, Any] | None = None) -> tuple[Entity, Fact | None]:
    """The entity a label names (the module docstring's order), and, when a study label of this file named another
    file's study, the `link.study_id` fact anchored at `source` (written once; the same label again returns it).

    `source` is the anchor text of the label's cell (None: a person's). `delivery`, `run_id`, `method`, `mapping` and
    `model` describe how the label was read, for that link fact; `review` is today's review record (read from
    `client_data.review_record` when not given)."""
    key, written = name_key(label), label_key(label)
    if not key:
        raise ValueError(f"a {type} label needs a letter or a digit: {label!r}")
    if review is None:
        from modeler_project.client_data import review_record

        review = review_record(ledger.ws)
    linked = _linked_study(ledger, written, file_sha256) if type == "study" and file_sha256 else None
    found: list[Entity] = []
    joined: list[bool] = []

    def decide(entries: list[ChainEntry]) -> list[tuple[str, Any]]:
        book = EntityBook(entries)
        parent_id = book.follow(parent)
        parent_entity = book.alive(parent_id)

        def local(entity: Entity) -> bool:
            return file_sha256 is None or home_file(entity) == file_sha256

        def done(entity: Entity, *, across: bool = False, rows: list[tuple[str, Any]] | None = None) -> list[tuple[str, Any]]:
            alive = book.alive(entity.id) or entity
            found.append(alive)
            joined.append(across)
            return rows or []

        # 1. inside the file first
        here = [e for e in book.named(type, frozenset((written,)), parent_id) if local(e)]
        if here:
            return done(here[0])
        # 2. an arm or a batch inside its parent, whichever file named it
        if type in PARENTED and parent_id is not None:
            scoped = book.named(type, frozenset((written,)), parent_id)
            if scoped:
                return done(scoped[0])
        # a study label this file already linked keeps its study
        if linked is not None and book.alive(linked[0]) is not None:
            return done(book.alive(linked[0]), across=True)
        # 3. an alias: the ledger's, then today's review record
        targets = review_targets(type, written, parent_entity, review)
        ledger_alias = [book.alive(a.entity) for a in book.aliases
                        if a.type == type and a.key == key and book.follow(a.parent) == parent_id]
        ledger_alias = [e for e in ledger_alias if e is not None]
        via_review = book.named(type, targets, parent_id) if targets else []
        alias_rows: list[tuple[str, Any]] = []
        if via_review and not ledger_alias:
            target = via_review[0]
            alias = Alias(type=type, key=key, parent=parent_id, entity=book.follow(target.id) or target.id,
                          source=f"review:{REVIEW_LISTS[type]}", by=by, at=now())
            alias_rows = [("alias", alias.model_dump(mode="json"))]
        aliased = ledger_alias + via_review
        if type != "study" or file_sha256 is None:
            if aliased:
                return done(aliased[0], rows=alias_rows)
        else:
            here_aliased = [e for e in aliased if local(e)]
            if here_aliased:
                return done(here_aliased[0], rows=alias_rows)
            # 4. a study: another file's study with the same key or a confirmed alias
            others: dict[str, Entity] = {}
            for entity in [*book.named("study", frozenset((written, *targets)), None), *aliased]:
                alive = book.alive(entity.id)
                if alive is not None and home_file(alive) not in (None, file_sha256):
                    others.setdefault(alive.id, alive)
            if len(others) == 1 and source is not None:
                return done(next(iter(others.values())), across=True, rows=alias_rows)
            # two or more: a new file-local study, which the pending links show as ambiguous; a label with no anchor of
            # its own cannot carry the link fact a join needs (condition 1): a new file-local study too

        # 5. a new entity
        def body(seq: int) -> dict[str, Any]:
            entity = Entity(id=f"{PREFIX[type]}-{seq}", type=type, label=label, key=key, parent=parent_id, source=source,
                            by=by, at=now())
            found.append(entity)
            joined.append(False)
            return entity.model_dump(mode="json")
        return [("entity", body)]

    ledger.store.entities.append_if(decide)
    entity, across = found[-1], joined[-1]
    if not across or type != "study":
        return entity, None
    if linked is not None and EntityBook(ledger.store.entities.entries()).follow(linked[0]) == entity.id:
        return entity, linked[1]
    if source is None or file_sha256 is None:
        return entity, None
    fact = Fact(id="", delivery=delivery, run_id=run_id, entity=EntityRef(study=entity.id), field="link.study_id",
                value=label, verbatim=label, anchor=source, method=method, mapping=mapping, model=model,
                by=f"agent:{model.agent_run}" if model is not None else by, at=now())
    written = ledger._write_facts([fact])[0]
    return entity, fact.model_copy(update={"id": written[0]})


def merge(ledger: Ledger, *, type: EntityType, from_id: str, into_id: str, link_fact: str | None, why: str, by: str) -> Merge:
    """Merge one entity into another of the same type (one `merge` line; both ids stay resolvable). The same merge again
    returns the line already written; a merge of an entity already merged elsewhere, of two types, or one that would
    make a cycle is a ValueError, an unknown id a KeyError.

    A study's arms and a product's batches are resolved inside their parent, so a merged study's arm with the name
    (`label_key`) of an arm of the study it joins is that arm: it is merged with it, in the same write (one more `merge`
    line each, with the same link fact and who). Otherwise two "Cohort 1" arms would stand in one study, their values
    split and their disagreements never seen. Arms of other names move with their study (their parent is followed)."""
    if not why or not why.strip():
        raise ValueError("a merge needs a reason")
    found: list[Merge] = []

    def decide(entries: list[ChainEntry]) -> list[tuple[str, Any]]:
        book = EntityBook(entries)
        for entity_id in (from_id, into_id):
            if entity_id not in book.entities:
                raise KeyError(entity_id)
            if book.entities[entity_id].type != type:
                raise ValueError(f"{entity_id} is a {book.entities[entity_id].type}, not a {type}")
        if from_id in book.merges:
            earlier = book.merges[from_id]
            if book.follow(earlier.into_id) == book.follow(into_id):
                found.append(earlier)
                return []
            raise ValueError(f"{from_id} is merged into {earlier.into_id} already")
        if book.follow(into_id) == from_id or from_id == into_id:
            raise ValueError(f"merging {from_id} into {into_id} would make a cycle")
        made = Merge(type=type, from_id=from_id, into_id=into_id, link_fact=link_fact, why=why.strip(), by=by, at=now())
        found.append(made)
        rows: list[tuple[str, Any]] = [("merge", made.model_dump(mode="json"))]
        child = CHILD.get(type)
        if child is not None:
            into_root = book.follow(into_id)
            targets: dict[str, Entity] = {}
            for entity in book.entities.values():                    # the first of each name inside the target
                if entity.type == child and entity.id not in book.merges and book.follow(entity.parent) == into_root:
                    targets.setdefault(label_key(entity.label), entity)
            for entity in book.entities.values():
                target = targets.get(label_key(entity.label))
                if entity.type == child and entity.id not in book.merges and book.follow(entity.parent) == from_id \
                        and target is not None:
                    rows.append(("merge", Merge(
                        type=child, from_id=entity.id, into_id=target.id, link_fact=link_fact, by=by, at=now(),
                        why=f"{child} {entity.label!r} is {target.label!r} inside {into_root} ({type} merge: "
                            f"{why.strip()})").model_dump(mode="json")))
        return rows

    ledger.store.entities.append_if(decide)
    ledger.refresh()
    return found[0]
