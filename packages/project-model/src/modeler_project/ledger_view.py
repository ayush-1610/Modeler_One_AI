"""The ledger's read side (contracts §4.5): `LedgerReader`, and `LedgerView`, the fold over the stores.

A `LedgerView` is a SNAPSHOT: it folds the logs once, lazily, on first use, reading each log once, so its heads, its
head and its values describe one state. One instance per request: a route and every function it calls share it. It
reads the ledger's two logs and the extracts they name, the `decision` lines of mappings.jsonl (which mapping versions
are approved) and the `confirmation`, `link` and `assignment` lines of review.jsonl. `conflicts()` and
`pending_links()` are D4's (`ledger.Ledger`); here they raise NotImplementedError. A subclass that writes calls
`refresh()` after a write, so the next read folds again.

Subjects (§6.6): a study, a product, and the project's compound. `values(study=S)` and `values(product=P)` are the
values whose entity names S or P; `values(compound=True)` the values of a compound-level field (a CPF id) with no
study, product or batch. `values(unassigned=True)` is the "study not stated" list: values with no study, no product
and no batch whose field is not compound-level (a product's dissolution and a compound's logP have their own subject).

The rules the fold applies (and the ledger's writes keep):
- status is never stored on a fact. `superseded`: a later item that is not excluded names it in `supersedes` (a fact
  names a fact or a value id; an extract names extracts, and a superseded extract supersedes all its values).
  `excluded`: the last `StatusChange` of the value (or of its extract, whichever is later) says so, or its cross-file
  link was refused (reason: the refusal). `confirmed`: the CURRENT confirmation of a subject binds it: its fact id, or
  its extract id, and not the value among the record's `excluded`, while the value still belongs to that subject
  (after assignments and merges). A subject's current confirmation is its latest one that no other confirmation names
  in `supersedes`. Otherwise `proposed`. In that order of precedence.
- an `Assignment` gives its targets (fact, extract or value ids) their study and arm, later ones over earlier ones;
  entity ids are followed through merges.
- `cross_file` is set for every value whose file differs from its study's home file (the file of the study entity's
  source anchor); the link is the assignment that put it there, else an active `link.*` fact of that file on that
  study, else the merge that joined that file's study into this one.
- evidence level: `person` or confirmed → person_confirmed; cell, pdf_table, docx_table → approved_mapping when its
  mapping version's last decision is approved, else new_mapping; prose → prose; digitized → digitized; derived → the
  lowest level of its inputs.
- `values()` returns every value, a derived spread fact included: such a fact qualifies the value it derives from and
  is never a value of its own, which its readers (conflicts, the landing, the scorer) skip with `is_spread_fact`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from modeler_intake.anchors import AnchorError, anchor_text, parse_anchor, parse_locator, sha256_of
from modeler_intake.fields import field as field_def
from modeler_project.intake_records import Assignment, Confirmation, LinkConfirmation, MappingDecision
from modeler_project.intake_store import GENESIS, ChainEntry, IntakeStore
from modeler_project.ledger_models import (
    ChainHead,
    Conflict,
    CrossFile,
    Entity,
    EntityRef,
    EntityType,
    EvidenceLevel,
    ExtractRef,
    Fact,
    Merge,
    Method,
    PendingLink,
    StatusChange,
    TableExtract,
    ValueState,
)
from modeler_project.workspace import Workspace

_LEVELS: tuple[EvidenceLevel, ...] = ("digitized", "prose", "new_mapping", "approved_mapping", "person_confirmed")
_TABLE_METHOD: dict[str, Method] = {"sheet_cell": "cell", "pdf_cell": "pdf_table", "docx_cell": "docx_table"}
_ENTITY_PARTS = ("study", "arm", "product", "batch", "analyte")


class LedgerReader(Protocol):
    def head(self) -> ChainHead: ...                              # the facts log's head

    def heads(self) -> dict[str, str]: ...                        # facts, entities, mappings, review: each log's head hash

    def entities(self, type: EntityType | None = None) -> list[Entity]: ...

    def entity(self, entity_id: str) -> Entity | None: ...        # follows merges

    def values(self, *, study: str | None = None, product: str | None = None, field: str | None = None,
               file_sha256: str | None = None, unassigned: bool = False, compound: bool = False,
               active: bool = True) -> list[ValueState]: ...
        # unassigned: no study, product or batch, and not a compound field; compound: the compound subject's values

    def value(self, value_id: str) -> ValueState | None: ...

    def conflicts(self, *, study: str | None = None, product: str | None = None) -> list[Conflict]: ...

    def pending_links(self, *, study: str | None = None) -> list[PendingLink]: ...

    def digest(self, *, study: str | None = None, product: str | None = None, compound: bool = False) -> str: ...
        # sha256 over the sorted (id, value, unit, anchor) of the subject's active values: no status, so recording the
        # confirmation does not make its own draw stale; an exclusion or a supersession changes the set of ids


def is_spread_fact(value: ValueState) -> bool:
    """A derived spread fact (§4.5, §6.3): no value, a spread, computed by `spread-<n>/...`. It qualifies the value it
    derives from and is never a value of its own: no conflict, no landing value, not scored. A BLQ value (no value,
    censored) is not one."""
    return (value.value is None and value.spread is not None and value.method == "derived"
            and (value.compute or "").startswith("spread-"))


def is_compound_field(name: str) -> bool:
    """Whether a field is compound-level (a CPF id of the parameter registry)."""
    found = field_def(name)
    return found is not None and found.level == "compound"


def in_subject(entity: EntityRef, field: str, subject_type: str, subject: str) -> bool:
    """Whether a value of this entity and field belongs to that subject (§6.6): a study or product its entity names,
    or the compound (subject id "compound"): a compound-level field with no study, product or batch."""
    if subject_type == "study":
        return entity.study == subject
    if subject_type == "product":
        return entity.product == subject
    return (subject_type == "compound" and entity.study is None and entity.product is None and entity.batch is None
            and is_compound_field(field))


def is_unassigned(entity: EntityRef, field: str) -> bool:
    """A value of no subject, shown as "study not stated" (§6.3): no study, no product, no batch, not a compound field."""
    return entity.study is None and entity.product is None and entity.batch is None and not is_compound_field(field)


@dataclass(frozen=True)
class _Snapshot:
    head: ChainHead
    heads: dict[str, str]
    entities: dict[str, Entity]          # id -> entity, in log order
    merged: dict[str, str]               # from id -> into id
    values: dict[str, ValueState]        # value id -> state, in log order


@dataclass
class _Raw:
    """One value before its status is known."""

    id: str
    seq: int
    entity: EntityRef
    state: dict                          # ValueState fields but entity, status, level, cross_file
    extract: str | None                  # the extract id of an extract's value
    derived_from: tuple[str, ...]
    method: Method
    approved: bool


class LedgerView:
    """The read side, a per-request snapshot of the ledger (see the module docstring)."""

    def __init__(self, ws: Workspace):
        self.ws = ws
        self.store = IntakeStore(ws)
        self._snapshot: _Snapshot | None = None

    # --- LedgerReader --------------------------------------------------------------------------------------------------

    def head(self) -> ChainHead:
        return self._fold().head

    def heads(self) -> dict[str, str]:
        return dict(self._fold().heads)

    def entities(self, type: EntityType | None = None) -> list[Entity]:
        """The entities not merged into another (of `type`), in the order they were created."""
        snap = self._fold()
        return [e for e in snap.entities.values() if e.id not in snap.merged and (type is None or e.type == type)]

    def entity(self, entity_id: str) -> Entity | None:
        snap = self._fold()
        return snap.entities.get(_follow(snap.merged, entity_id))

    def values(self, *, study: str | None = None, product: str | None = None, field: str | None = None,
               file_sha256: str | None = None, unassigned: bool = False, compound: bool = False,
               active: bool = True) -> list[ValueState]:
        """The values that pass every filter given, in log order: of a study, of a product, of a field, of a file;
        `unassigned`: of no subject ("study not stated"); `compound`: of the compound subject; `active` (default):
        proposed or confirmed."""
        snap = self._fold()
        study = _follow(snap.merged, study) if study is not None else None
        product = _follow(snap.merged, product) if product is not None else None
        return [v for v in snap.values.values()
                if (study is None or v.entity.study == study) and (product is None or v.entity.product == product)
                and (field is None or v.field == field) and (file_sha256 is None or v.file_sha256 == file_sha256)
                and (not unassigned or is_unassigned(v.entity, v.field))
                and (not compound or in_subject(v.entity, v.field, "compound", "compound"))
                and (not active or v.status in ("proposed", "confirmed"))]

    def value(self, value_id: str) -> ValueState | None:
        return self._fold().values.get(value_id)

    def conflicts(self, *, study: str | None = None, product: str | None = None) -> list[Conflict]:
        raise NotImplementedError("conflicts are the ledger's (modeler_project.ledger.Ledger)")

    def pending_links(self, *, study: str | None = None) -> list[PendingLink]:
        raise NotImplementedError("pending links are the ledger's (modeler_project.ledger.Ledger)")

    def digest(self, *, study: str | None = None, product: str | None = None, compound: bool = False) -> str:
        """sha256 over the sorted (id, value, unit, anchor) of the subject's active values: a study's, a product's or
        (compound=True) the compound's; with none of them, every active value of the project."""
        rows = sorted(([v.id, v.value, v.unit, v.anchor] for v in self.values(study=study, product=product,
                                                                             compound=compound)),
                      key=lambda row: row[0])
        return sha256_of(rows)

    def refresh(self) -> None:
        """Drop the snapshot: the next read folds the logs again (the ledger's write side calls it after a write)."""
        self._snapshot = None

    # --- the fold ------------------------------------------------------------------------------------------------------

    def _fold(self) -> _Snapshot:
        if self._snapshot is None:
            self._snapshot = self._build()
        return self._snapshot

    def _build(self) -> _Snapshot:
        store = self.store
        # each log is read once: the heads and the values below describe the same lines
        fact_lines, entity_lines = store.facts.entries(), store.entities.entries()
        mapping_lines, review_lines = store.mappings.entries(), store.review.entries()
        heads = {"facts": _head(fact_lines).hash, "entities": _head(entity_lines).hash,
                 "mappings": _head(mapping_lines).hash, "review": _head(review_lines).hash}
        entities: dict[str, Entity] = {}
        merges: list[Merge] = []
        for line in entity_lines:
            if line.kind == "entity":
                entity = Entity.model_validate(line.body)
                entities[entity.id] = entity
            elif line.kind == "merge":
                merges.append(Merge.model_validate(line.body))
        merged = {m.from_id: m.into_id for m in merges}

        decisions: dict[tuple[str, int], str] = {}
        for line in mapping_lines:
            if line.kind != "decision":
                continue
            decision = MappingDecision.model_validate(line.body)
            decisions[(decision.mapping_id, decision.version)] = decision.status
        approved = {key for key, status in decisions.items() if status == "approved"}

        confirmations: list[Confirmation] = []
        links: dict[tuple[str, str], LinkConfirmation] = {}
        assignments: list[Assignment] = []
        for line in review_lines:
            if line.kind == "confirmation":
                confirmations.append(Confirmation.model_validate(line.body))
            elif line.kind == "link":
                link = LinkConfirmation.model_validate(line.body)
                links[(_follow(merged, link.study), link.file_sha256)] = link
            elif line.kind == "assignment":
                assignments.append(Assignment.model_validate(line.body))

        raws: list[_Raw] = []
        extract_values: dict[str, list[str]] = {}
        changes: dict[str, tuple[int, StatusChange]] = {}
        superseders: list[tuple[str, tuple[str, ...]]] = []           # (superseding item, what it names)
        for line in fact_lines:
            if line.kind == "fact":
                fact = Fact.model_validate(line.body)
                raws.append(_fact_raw(fact, line.seq, approved))
                if fact.supersedes:
                    superseders.append((fact.id, (fact.supersedes,)))
            elif line.kind == "extract":
                ref = ExtractRef.model_validate(line.body)
                extract = store._extract_file(ref.id)
                made = _extract_raws(ref, extract, line.seq, approved)
                raws.extend(made)
                extract_values[ref.id] = [r.id for r in made]
                if ref.supersedes:
                    superseders.append((ref.id, ref.supersedes))
            elif line.kind == "status":
                change = StatusChange.model_validate(line.body)
                changes[change.target] = (line.seq, change)

        def last_change(raw: _Raw) -> StatusChange | None:
            own = changes.get(raw.id)
            of_extract = changes.get(raw.extract) if raw.extract else None
            picked = max((c for c in (own, of_extract) if c is not None), key=lambda c: c[0], default=None)
            return picked[1] if picked else None

        def excluded_item(item: str) -> bool:
            change = changes.get(item)
            return change is not None and change[1].status == "excluded"

        superseded_by: dict[str, str] = {}
        for item, named in superseders:
            if excluded_item(item):
                continue
            for target in named:
                superseded_by[target] = item

        # assignments and merges give each value its entity
        assigned: dict[str, Assignment] = {}
        for assignment in assignments:
            for target in assignment.targets:
                for value_id in extract_values.get(target, [target]):
                    assigned[value_id] = assignment
        for raw in raws:
            entity = raw.entity
            if raw.id in assigned:
                entity = entity.model_copy(update={"study": assigned[raw.id].study, "arm": assigned[raw.id].arm})
            raw.entity = entity.model_copy(update={part: _follow(merged, getattr(entity, part))
                                                   for part in _ENTITY_PARTS if getattr(entity, part) is not None})

        # cross-file: a value read from a file other than its study's home file
        def home(study: str) -> str | None:
            entity = entities.get(study)
            if entity is None or entity.source is None:
                return None
            try:
                return parse_anchor(entity.source).file_sha256
            except AnchorError:
                return None

        link_facts: dict[tuple[str, str], str] = {}
        for raw in raws:
            file = raw.state["file_sha256"]
            change = last_change(raw)
            if raw.state["field"].startswith("link.") and raw.entity.study and file and raw.id not in superseded_by \
                    and (change is None or change.status != "excluded"):
                link_facts.setdefault((raw.entity.study, file), raw.id)
        merge_links: dict[tuple[str, str], str] = {}
        for merge in merges:
            source = entities.get(merge.from_id)
            from_home = home(merge.from_id) if source is not None else None
            if from_home:
                merge_links[(_follow(merged, merge.into_id), from_home)] = merge.link_fact or f"merge:{merge.from_id}"

        cross: dict[str, CrossFile] = {}
        for raw in raws:
            study, file = raw.entity.study, raw.state["file_sha256"]
            if study is None or file is None:
                continue
            study_home = home(study)
            if study_home is None or study_home == file:
                continue
            link = (assigned[raw.id].id if raw.id in assigned
                    else link_facts.get((study, file)) or merge_links.get((study, file)) or "")
            cross[raw.id] = CrossFile(stating_fact=raw.id, link_fact=link, receiving_study=study)

        # confirmations: each subject's current one binds the values it lists that still belong to that subject
        by_id = {raw.id: raw for raw in raws}
        replaced = {c.supersedes for c in confirmations if c.supersedes}
        current: dict[tuple[str, str], Confirmation] = {}
        for confirmation in confirmations:                     # in log order: a later one of a subject replaces it
            if confirmation.id in replaced:
                continue
            subject = confirmation.subject
            if confirmation.subject_type in ("study", "product"):
                subject = _follow(merged, subject)
            current[(confirmation.subject_type, subject)] = confirmation
        bound: dict[str, str] = {}
        for (subject_type, subject), confirmation in current.items():
            record = confirmation.record
            left_out = {str(item) for item in record.get("excluded", ())}
            listed = [str(row[0]) for row in record.get("facts", ())]
            listed += [value_id for row in record.get("extracts", ()) for value_id in extract_values.get(str(row[0]), [])]
            for value_id in listed:
                raw = by_id.get(value_id)
                if raw is not None and value_id not in left_out \
                        and in_subject(raw.entity, raw.state["field"], subject_type, subject):
                    bound[value_id] = confirmation.id

        # status, then level (a derived value takes the lowest level of its inputs)
        statuses: dict[str, tuple[str, str, str | None]] = {}
        for raw in raws:
            by = superseded_by.get(raw.id) or (superseded_by.get(raw.extract) if raw.extract else None)
            change = last_change(raw)
            refusal = None
            if raw.id in cross and raw.id not in assigned:
                link = links.get((raw.entity.study or "", raw.state["file_sha256"] or ""))
                refusal = link if link is not None and not link.confirmed else None
            if by is not None:
                statuses[raw.id] = ("superseded", "", by)
            elif change is not None and change.status == "excluded":
                statuses[raw.id] = ("excluded", change.reason, None)
            elif refusal is not None:
                statuses[raw.id] = ("excluded", refusal.why or "the cross-file link was refused", None)
            elif raw.id in bound:
                statuses[raw.id] = ("confirmed", "", None)
            else:
                statuses[raw.id] = ("proposed", "", None)

        levels: dict[str, EvidenceLevel] = {}

        def level(value_id: str, seen: frozenset[str] = frozenset()) -> EvidenceLevel:
            if value_id in levels:
                return levels[value_id]
            raw = by_id.get(value_id)
            if raw is None or value_id in seen:
                return "digitized"
            if raw.method == "person" or statuses[value_id][0] == "confirmed":
                found: EvidenceLevel = "person_confirmed"
            elif raw.method in ("cell", "pdf_table", "docx_table"):
                found = "approved_mapping" if raw.approved else "new_mapping"
            elif raw.method == "prose":
                found = "prose"
            elif raw.method == "derived":
                inputs = [level(i, seen | {value_id}) for i in raw.derived_from]
                found = min(inputs, key=_LEVELS.index) if inputs else "digitized"
            else:
                found = "digitized"
            levels[value_id] = found
            return found

        values: dict[str, ValueState] = {}
        for raw in raws:
            status, reason, by = statuses[raw.id]
            values[raw.id] = ValueState(
                **raw.state, entity=raw.entity, cross_file=cross.get(raw.id), status=status, status_reason=reason,
                superseded_by=by, confirmation=bound.get(raw.id), level=level(raw.id))
        return _Snapshot(head=_head(fact_lines), heads=heads, entities=entities, merged=merged, values=values)


def _head(entries: list[ChainEntry]) -> ChainHead:
    """A log's head from the lines read: the last line's (seq, hash); seq 0 and 64 zeros when there is none."""
    return ChainHead(seq=entries[-1].seq, hash=entries[-1].hash) if entries else ChainHead(seq=0, hash=GENESIS)


def _follow(merged: dict[str, str], entity_id: str) -> str:
    seen = set()
    while entity_id in merged and entity_id not in seen:
        seen.add(entity_id)
        entity_id = merged[entity_id]
    return entity_id


def _fact_raw(fact: Fact, seq: int, approved: set[tuple[str, int]]) -> _Raw:
    file = parse_anchor(fact.anchor).file_sha256 if fact.anchor else None
    state = dict(
        id=fact.id, field=fact.field, value=fact.value, unit=fact.unit, verbatim=fact.verbatim, file_sha256=file,
        time=fact.time, time_unit=fact.time_unit, time_actual=fact.time_actual, statistic=fact.statistic,
        spread=fact.spread, spread_kind=fact.spread_kind, n_at=fact.n, interval=fact.interval,
        interval_kind=fact.interval_kind, interval_level=fact.interval_level, censored=fact.censored, lloq=fact.lloq,
        lloq_unit=fact.lloq_unit, uloq=fact.uloq, conditions=dict(fact.conditions), relation=fact.relation,
        anchor=fact.anchor, locators=dict(fact.locators), method=fact.method, mapping=fact.mapping,
        derived_from=fact.derived_from, compute=fact.compute, table_kind=None, delivery=fact.delivery)
    mapped = fact.mapping is not None and (fact.mapping.mapping_id, fact.mapping.version) in approved
    return _Raw(id=fact.id, seq=seq, entity=fact.entity, state=state, extract=None, derived_from=fact.derived_from,
                method=fact.method, approved=mapped)


def _extract_raws(ref: ExtractRef, x: TableExtract, seq: int, approved: set[tuple[str, int]]) -> list[_Raw]:
    def anchored(locator: str | None) -> str | None:
        return anchor_text(x.file_sha256, x.parser, x.parser_version, locator) if locator else None

    is_approved = (x.mapping.mapping_id, x.mapping.version) in approved
    out = []
    for i in range(x.n):
        locators = {role: anchored(loc) for role, loc in (
            ("time", x.time_locator[i]), ("time_actual", x.time_actual_locator[i]), ("unit", x.unit_locator[i]),
            ("spread", x.spread_locator[i]), ("n", x.n_locator[i]), ("lloq", x.lloq_locator[i])) if loc}
        pair = x.interval_locator[i]
        if pair is not None:
            locators["interval_low"], locators["interval_high"] = anchored(pair[0]), anchored(pair[1])
        locators.update({role: anchored(loc) for role, loc in x.entity_locators[x.entity_ix[i]].items() if loc})
        condition_ix = x.condition_ix[i]
        if condition_ix is not None:
            locators.update({name: anchored(loc) for name, loc in x.condition_locators[condition_ix].items() if loc})
        low, high = x.interval_low[i], x.interval_high[i]
        unit_ix = x.unit_ix[i]
        value_id = f"{ref.id}#{i}"
        state = dict(
            id=value_id, field=x.fields[x.field_ix[i]], value=x.value[i],
            unit=x.units[unit_ix] if unit_ix is not None else None, verbatim=x.verbatim[i], file_sha256=x.file_sha256,
            time=x.time[i], time_unit=x.time_unit[i], time_actual=x.time_actual[i], statistic=x.statistic[i],
            spread=x.spread[i], spread_kind=x.spread_kind[i], n_at=x.n_at[i],
            interval=(low, high) if low is not None and high is not None else None, interval_kind=x.interval_kind[i],
            interval_level=x.interval_level[i], censored=x.censored[i], lloq=x.lloq[i], lloq_unit=x.lloq_unit[i],
            uloq=x.uloq[i], conditions=dict(x.conditions[condition_ix]) if condition_ix is not None else {},
            relation=None, anchor=anchored(x.locator[i]), locators=locators,
            method=_TABLE_METHOD.get(parse_locator(x.locator[i]).kind, "cell"), mapping=ref.mapping, derived_from=(),
            compute=None, table_kind=x.kind, delivery=ref.delivery)
        out.append(_Raw(id=value_id, seq=seq, entity=x.entities[x.entity_ix[i]], state=state, extract=ref.id,
                        derived_from=(), method=state["method"], approved=is_approved))
    return out
