"""The synthetic truth written into a ledger (contracts §7): one convention for the tests of D0, D5, W and D6.

`write_truth` writes the truth of `modeler_intake.synthetic` files through `IntakeStore` exactly as §4.5 and §5 say:
the delivery and its files (files.jsonl, the bytes in the project store; a file whose bytes arrived before is a
`repeat`), each truth table's spec as a mapping entry (proposed and, by default, approved), the entities its labels
name, one `TableExtract` per table for its numeric values (with an `extract` line naming it), and a `fact` line for
every other value: a constant read from a caption or a footnote (the names of the table's entities included), a
text-valued row, a prose fact (with the scripted model's `ModelUse`, by the agent).

Entities are resolved as §6.3's `resolve` does: inside the file first (the same key under the same parent among the
entities whose home file is this one); then, for a study only, another file's study with the same key, returned with a
`link.study_id` fact at this file's label (its method: the label's, "prose" for a sentence); else a new entity. So an
analyte, a product or a batch named in two files is two entities, and cross-file values come out of the fold with
their link.

An extract holds one `entities` / `entity_locators` entry per distinct (entity, label cells) pair and one
`conditions` / `condition_locators` entry per distinct (conditions, cells) pair, so every value carries the label and
condition cells of its own row ("parameter" included for a key_value table). A censored value's LLOQ is the one its
`lloq` cell states: the number of a "<0.5" cell, else the table's LLOQ line (§5's example); a BLQ with no LLOQ cell
has none (BLQ_WITHOUT_LLOQ is then real).

Every stated LLOQ is an `lloq` fact, once per (study, analyte, matrix), number and unit (§6.3), as the ledger writes
it. A table's LLOQ line is a truth value of its own. A "<0.5" cell states one too: when no line or column of its table
states that number for the same (study, analyte, matrix), the first such cell gets an `lloq` fact, at the cell, with
its column's unit and the unit cell among its locators (`_token_lloqs`). That fact is no `TruthValue`, so it has no
key in `write_truth`'s answer: the ledger then holds one value more than the truth lists.

It is a fixture, not the pipeline: no parse, no mapping, no rule. The parser version is
`synthetic.TRUTH_PARSER_VERSION`, and a mapping's fingerprint is the sha256 of its spec, not D3's layout fingerprint
(a test that needs the mapping cache to find a table preloads it through `MappingCache` itself). D4's own tests do not
use it: they test the writes.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from modeler_intake.anchors import anchor_text, sha256_of
from modeler_intake.document_reading import name_key
from modeler_intake.fields import LABEL_FIELDS, field, known_unit, read_choice
from modeler_intake.source_model import GridCell
from modeler_intake.synthetic import PARSERS, TRUTH_PARSER_VERSION, SyntheticFile, TruthTable, TruthValue, truth_grid
from modeler_project.intake_records import FileRecord, MappingDecision, MappingEntry
from modeler_project.intake_store import ChainEntry, IntakeStore
from modeler_project.ledger_models import (
    Entity,
    EntityRef,
    EntityType,
    ExtractRef,
    Fact,
    MappingUse,
    Method,
    ModelUse,
    TableExtract,
)
from modeler_project.workspace import Workspace

PARSER_VERSION = TRUTH_PARSER_VERSION
_PREFIX = {"study": "st", "arm": "arm", "product": "pr", "batch": "ba", "analyte": "an"}
_TABLE_METHOD: dict[str, Method] = {"workbook": "cell", "delimited": "cell", "pdfplumber": "pdf_table", "docx": "docx_table"}
_TOKENS_BLQ = ("BLQ",)
# The roles of a value's label cells (entity_locators); every other role is a qualifier (time, unit, spread, n, lloq,
# intervals) or a condition
_LABEL_ROLES = frozenset(("study", "arm", "product", "batch", "analyte", *LABEL_FIELDS, "other_arm", "parameter"))
# The model a prose fact of the truth is read by: the scripted one (§6.2's `Scripted`), never a live model
TRUTH_MODEL = ModelUse(provider="scripted", model="scripted", prompt_sha256=hashlib.sha256(b"synthetic truth").hexdigest(),
                       agent_run="ar_000000000000")


def truth_key(file: SyntheticFile, value: TruthValue) -> str:
    """The key of one truth value in `write_truth`'s answer: "<file name>|<table>|<field>|<locator>"."""
    return f"{file.name}|{value.table}|{value.field}|{value.locator}"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _number(text: str) -> float | None:
    text = text.strip().replace("−", "-")
    if not text:
        return None
    if re.fullmatch(r"-?\d+,\d+", text):
        text = text.replace(",", ".")
    return float(text)


def _reading(text: str) -> tuple[float | None, bool, float | None, float | None]:
    """(value, censored, lloq, uloq) of a value as written: BLQ, "<x", ">x", a missing token, "12.3*"."""
    text = text.strip().rstrip("*†‡")
    if text.upper() in _TOKENS_BLQ:
        return None, True, None, None
    if text.startswith("<"):
        return None, True, _number(text[1:]), None
    if text.startswith(">"):
        return None, False, None, _number(text[1:])
    try:
        return _number(text), False, None, None
    except ValueError:
        return None, False, None, None                 # a missing token ("NS"): no value


class _Writer:
    def __init__(self, ws: Workspace, delivery: str, approved: bool):
        self.ws = ws
        self.store = IntakeStore(ws)
        self.delivery = delivery
        self.approved = approved
        self.linked: set[tuple[str, str]] = set()

    # --- entities --------------------------------------------------------------------------------------------------

    def entity(self, type: EntityType, label: str, parent: str | None, source: str | None, file_sha: str) -> Entity:
        """§6.3's resolve: inside the file first; then, for a study, the one study of another file with the same key
        (two or more: a new file-local study, nothing joined); else a new entity."""
        key = name_key(label)
        found: list[Entity] = []

        def decide(entries: list[ChainEntry]) -> list[tuple[str, Any]]:
            same = [e for e in (Entity.model_validate(line.body) for line in entries if line.kind == "entity")
                    if e.type == type and e.key == key and e.parent == parent]
            here = [e for e in same if _home(e) == file_sha]
            elsewhere = [e for e in same if _home(e) != file_sha] if type == "study" else []
            if here or len(elsewhere) == 1:
                found.append((here or elsewhere)[0])
                return []

            def body(seq: int) -> dict[str, Any]:
                entity = Entity(id=f"{_PREFIX[type]}-{seq}", type=type, label=label, key=key, parent=parent, source=source,
                                by="code", at=_now())
                found.append(entity)
                return entity.model_dump(mode="json")
            return [("entity", body)]

        self.store.entities.append_if(decide)
        return found[0]

    def entity_ref(self, value: TruthValue, anchor_of: dict[str, str], file_sha: str, method: Method) -> EntityRef:
        at = dict(value.locators)
        study = arm = product = batch = analyte = None
        if value.study:
            entity = self.entity("study", value.study, None, anchor_of.get(at.get("study", "")), file_sha)
            study = entity.id
            self._link(entity, value, anchor_of, file_sha, method)
        if value.arm and study:
            arm = self.entity("arm", value.arm, study, anchor_of.get(at.get("arm", "")), file_sha).id
        if value.product:
            product = self.entity("product", value.product, None, anchor_of.get(at.get("product", "")), file_sha).id
        if value.batch:
            batch = self.entity("batch", value.batch, product, anchor_of.get(at.get("batch", "")), file_sha).id
        if value.analyte:
            analyte = self.entity("analyte", value.analyte, None, anchor_of.get(at.get("analyte", "")), file_sha).id
        return EntityRef(study=study, arm=arm, product=product, batch=batch, analyte=analyte, subject=value.subject or None,
                         period=value.period or None, occasion=value.occasion or None, vessel=value.vessel or None,
                         matrix=value.matrix or None)

    def _link(self, study: Entity, value: TruthValue, anchor_of: dict[str, str], file_sha: str, method: Method) -> None:
        """A study first named in another file: one `link.study_id` fact at this file's label (§6.3), read as the label
        was (a table's method, or prose with its model)."""
        source = anchor_of.get(dict(value.locators).get("study", ""))
        if source is None or _home(study) in (None, file_sha):
            return
        if (study.id, file_sha) in self.linked:
            return
        self.linked.add((study.id, file_sha))
        self.fact(Fact(id="", delivery=self.delivery, entity=EntityRef(study=study.id), field="link.study_id",
                       value=value.study, verbatim=value.study, anchor=source, method=method,
                       model=TRUTH_MODEL if method == "prose" else None, by="code", at=_now()))

    # --- facts and extracts ----------------------------------------------------------------------------------------

    def fact(self, fact: Fact) -> str:
        """Append a fact once (the same anchor, field and value: the earlier line's id)."""
        found: list[str] = []

        def decide(entries: list[ChainEntry]) -> list[tuple[str, Any]]:
            for line in entries:
                if line.kind == "fact" and line.body.get("anchor") == fact.anchor and line.body.get("field") == fact.field \
                        and line.body.get("value") == fact.value:
                    found.append(line.body["id"])
                    return []

            def body(seq: int) -> dict[str, Any]:
                found.append(f"f-{seq}")
                return fact.model_copy(update={"id": f"f-{seq}"}).model_dump(mode="json")
            return [("fact", body)]

        self.store.facts.append_if(decide)
        return found[0]

    def mapping(self, table: TruthTable, file_sha: str, region_id: str) -> MappingUse:
        spec = table.spec.model_copy(update={"constants": tuple(c.model_copy(update={"text": None})
                                                                for c in table.spec.constants)})
        fingerprint = sha256_of(spec)
        mapping_id = f"mp-{fingerprint[:12]}"

        def decide(entries: list[ChainEntry]) -> list[tuple[str, Any]]:
            if any(line.kind == "entry" and line.body.get("mapping_id") == mapping_id for line in entries):
                return []
            entry = MappingEntry(mapping_id=mapping_id, version=1, fingerprint=fingerprint, spec=spec, origin="person",
                                 origin_detail="synthetic truth", first_seen=(file_sha, region_id), by="code", at=_now())
            return [("entry", entry.model_dump(mode="json", by_alias=True))]

        self.store.mappings.append_if(decide)
        if self.approved:
            def approve(entries: list[ChainEntry]) -> list[tuple[str, Any]]:
                if any(line.kind == "decision" and line.body.get("mapping_id") == mapping_id for line in entries):
                    return []
                decision = MappingDecision(mapping_id=mapping_id, version=1, status="approved", why="the synthetic truth",
                                           by="code", at=_now())
                return [("decision", decision.model_dump(mode="json"))]
            self.store.mappings.append_if(approve)
        return MappingUse(mapping_id=mapping_id, version=1)

    def extract(self, file_sha: str, parser: str, table: TruthTable, region_id: str, mapping: MappingUse,
                values: Sequence[TruthValue], refs: Sequence[EntityRef], verbatim: dict[str, str],
                lloqs: dict[str, tuple[str, str]]) -> str:
        entities: list[EntityRef] = []
        entity_locators: list[dict[str, str]] = []
        entity_keys: list[tuple[str, tuple[tuple[str, str], ...]]] = []
        fields: list[str] = []
        units: list[str] = []
        conditions: list[dict[str, str]] = []
        condition_locators: list[dict[str, str]] = []
        condition_keys: list[tuple[tuple[tuple[str, str], ...], tuple[tuple[str, str], ...]]] = []
        columns: dict[str, list[Any]] = {name: [] for name in (
            "entity_ix", "field_ix", "unit_ix", "condition_ix", "time", "time_unit", "time_actual", "value", "verbatim",
            "censored", "lloq", "lloq_unit", "uloq", "statistic", "spread", "spread_kind", "n_at", "interval_low",
            "interval_high", "interval_kind", "interval_level", "locator", "time_locator", "time_actual_locator",
            "unit_locator", "spread_locator", "n_locator", "lloq_locator", "interval_locator")}
        for value, ref in zip(values, refs, strict=True):
            at = dict(value.locators)
            labels = {role: at[role] for role in at if role in _LABEL_ROLES}
            entity_key = (ref.model_dump_json(), tuple(sorted(labels.items())))
            if entity_key not in entity_keys:                     # one entry per distinct (entity, label cells)
                entity_keys.append(entity_key)
                entities.append(ref)
                entity_locators.append(labels)
            if value.field not in fields:
                fields.append(value.field)
            if value.unit and value.unit not in units:
                units.append(value.unit)
            condition = dict(value.conditions)
            condition_at = {name: at[name] for name in condition if name in at}
            condition_key = (tuple(sorted(condition.items())), tuple(sorted(condition_at.items())))
            if condition and condition_key not in condition_keys:   # one entry per distinct (conditions, cells)
                condition_keys.append(condition_key)
                conditions.append(condition)
                condition_locators.append(condition_at)
            number, censored, lloq, lloq_unit, uloq = _censoring(value, lloqs)
            row = dict(
                entity_ix=entity_keys.index(entity_key), field_ix=fields.index(value.field),
                unit_ix=units.index(value.unit) if value.unit else None,
                condition_ix=condition_keys.index(condition_key) if condition else None,
                time=_number(value.time), time_unit=value.time_unit or None, time_actual=_number(value.time_actual),
                value=number, verbatim=verbatim[value.locator], censored=censored, lloq=lloq,
                lloq_unit=lloq_unit, uloq=uloq, statistic=value.statistic or None,
                spread=_number(value.spread), spread_kind=value.spread_kind or None, n_at=int(value.n) if value.n else None,
                interval_low=None, interval_high=None, interval_kind=None, interval_level=None, locator=value.locator,
                time_locator=at.get("time"), time_actual_locator=at.get("time_actual"), unit_locator=at.get("unit"),
                spread_locator=at.get("spread"), n_locator=at.get("n"), lloq_locator=at.get("lloq"), interval_locator=None)
            for name, item in row.items():
                columns[name].append(item)
        decimal = "comma" if any(re.fullmatch(r"-?\d+,\d+", t) for row in table.rows for t in row) else "point"
        extract = TableExtract(file_sha256=file_sha, parser=parser, parser_version=PARSER_VERSION, region_id=region_id,
                               mapping=mapping, kind=table.kind, decimal=decimal, entities=tuple(entities),
                               entity_locators=tuple(entity_locators), fields=tuple(fields), units=tuple(units),
                               conditions=tuple(conditions), condition_locators=tuple(condition_locators), n=len(values),
                               **{name: tuple(items) for name, items in columns.items()})
        extract_id, content_sha256 = self.store.put_extract(extract)
        ref_line = ExtractRef(id=extract_id, content_sha256=content_sha256, file_sha256=file_sha, region_id=region_id,
                              mapping=mapping, kind=table.kind, n=len(values),
                              studies=tuple(sorted({r.study for r in entities if r.study})),
                              products=tuple(sorted({r.product for r in entities if r.product})), delivery=self.delivery,
                              run_id=None, by="code", at=_now())

        def decide(entries: list[ChainEntry]) -> list[tuple[str, Any]]:
            if any(line.kind == "extract" and line.body.get("id") == extract_id for line in entries):
                return []
            return [("extract", ref_line.model_dump(mode="json"))]

        self.store.facts.append_if(decide)
        return extract_id


def _home(entity: Entity) -> str | None:
    """The sha256 of an entity's home file: the file of its source anchor (None: a person's entity)."""
    return entity.source.split("@", 1)[0] if entity.source else None


def _censoring(value: TruthValue, lloqs: dict[str, tuple[str, str]]
               ) -> tuple[float | None, bool, float | None, str | None, float | None]:
    """(value, censored, lloq, lloq unit, uloq) of a value as written; a censored value's LLOQ is its own "<x" (in the
    value's unit), else the number and unit its `lloq` cell states (the table's LLOQ line)."""
    number, censored, lloq, uloq = _reading(value.value)
    lloq_unit = (value.unit or None) if lloq is not None else None
    cited = dict(value.locators).get("lloq")
    if censored and lloq is None and cited in lloqs:
        text, unit = lloqs[cited]
        lloq, lloq_unit = _number(text), unit or None
    return number, censored, lloq, lloq_unit, uloq


def _stating(ref: EntityRef, number: float) -> tuple[Any, ...]:
    """What an LLOQ states, its unit aside: the (study, analyte, matrix) it is of and its number."""
    return (ref.study, ref.analyte, name_key(ref.matrix) if ref.matrix else None, float(f"{number:.12g}"))


def _token_lloqs(numeric: Sequence[TruthValue], refs: Sequence[EntityRef], lines: Sequence[tuple[EntityRef, float]],
                 lloqs: dict[str, tuple[str, str]]) -> list[tuple[TruthValue, EntityRef, float, str | None]]:
    """The LLOQs a table's "<x" cells state (§6.3): (the first cell that states it, its (study, analyte, matrix), the
    number, the unit), once per (study, analyte, matrix), number and unit. A token that repeats the number a line or a
    column of its table states for the same (study, analyte, matrix) states nothing new: `lines` are the table's LLOQ
    lines, and a value that cites an LLOQ cell other than its own adds that cell's number for its own entity."""
    stated = {_stating(ref, number) for ref, number in lines}
    tokens = []
    for value, ref in zip(numeric, refs, strict=True):
        cited = dict(value.locators).get("lloq")
        _number_read, _censored, lloq, lloq_unit, _uloq = _censoring(value, lloqs)
        if lloq is None or not cited:
            continue
        if cited != value.locator:
            stated.add(_stating(ref, lloq))                  # a line or a column's own LLOQ, cited by this value
        else:
            tokens.append((value, EntityRef(study=ref.study, analyte=ref.analyte, matrix=ref.matrix), lloq, lloq_unit))
    out = []
    seen: set[tuple[Any, ...]] = set()
    for value, entity, lloq, unit in tokens:
        known = known_unit("lloq", unit) if unit else None
        key = (*_stating(entity, lloq), ("known", known) if known is not None else ("text", (unit or "").strip()))
        if key in seen or _stating(entity, lloq) in stated:
            continue
        seen.add(key)
        out.append((value, entity, lloq, unit))
    return out


def _fact_value(value: TruthValue) -> float | int | str | None:
    found = field(value.field)
    if found is not None and found.value in ("number", "integer"):
        number, _censored, _lloq, _uloq = _reading(value.value)
        return int(number) if found.value == "integer" and number is not None else number
    if found is not None and found.value == "choice":
        return read_choice(value.field, value.value) or value.value
    return value.value


def write_truth(ws: Workspace, files: Sequence[SyntheticFile], *, delivery: str = "dl-1", approved: bool = True) -> dict[str, str]:
    """Write the truth of these files into the project's ledger; return truth value -> value id (keys: `truth_key`).
    Numeric values of a table are the i-th values of its extract ("tx-...#i"); every other value is a fact ("f-n").
    The `lloq` fact of a "<x" cell that no LLOQ line states (the module docstring) is written too, with no key."""
    writer = _Writer(ws, delivery, approved)
    store = writer.store
    if not store.available:
        raise RuntimeError("write_truth needs a project store with a file root")
    store.files.append_if(lambda entries: [] if any(e.kind == "delivery" and e.body.get("id") == delivery for e in entries)
                          else [("delivery", {"id": delivery, "by": "code", "at": _now()})])
    out: dict[str, str] = {}
    for file in files:
        if not file.values:
            continue
        file_sha = hashlib.sha256(file.data).hexdigest()
        ws.store.put_blob(ws.tenant_id, ws.project_id, file.data)
        record = FileRecord(file_id=f"fl-{file_sha[:12]}", sha256=file_sha, name=file.name, size_bytes=len(file.data),
                            delivery=delivery, by="code", at=_now())

        def file_line(entries: list[ChainEntry], record: FileRecord = record) -> list[tuple[str, Any]]:
            seen = [e for e in entries if e.kind == "file" and e.body.get("sha256") == record.sha256]
            if any(e.body.get("delivery") == delivery for e in seen):
                return []
            return [("file", record.model_copy(update={"repeat": bool(seen)}).model_dump(mode="json"))]
        store.files.append_if(file_line)
        parser = PARSERS[file.format]
        lloqs = {v.locator: (v.value, v.unit) for v in file.values if v.field == "lloq"}

        def anchored(locator: str, parser: str = parser, file_sha: str = file_sha) -> str:
            return anchor_text(file_sha, parser, PARSER_VERSION, locator)

        anchor_of = {loc: anchored(loc) for value in file.values for loc in (value.locator, *(at for _r, at in value.locators))}
        texts: dict[str, str] = {}
        for table in file.tables:
            grid = truth_grid(file, table.id)
            context = (*grid.caption, *(c for line in (*grid.above, *grid.below) for c in line))
            cells: tuple[GridCell, ...] = (*grid.cells.values(), *context)
            texts.update({c.locator: c.text for c in cells})
            body = {c.locator for c in grid.cells.values() if c.merged_from is None}
            mapping = writer.mapping(table, file_sha, grid.region_id)
            table_values = [v for v in file.values if v.table == table.id]
            numeric = [v for v in table_values if v.locator in body and (found := field(v.field)) is not None
                       and found.value in ("number", "integer")]
            method = _TABLE_METHOD.get(parser, "cell")
            refs: list[EntityRef] = []
            if numeric:
                refs = [writer.entity_ref(v, anchor_of, file_sha, method) for v in numeric]
                extract_id = writer.extract(file_sha, parser, table, grid.region_id, mapping, numeric, refs, texts, lloqs)
                out.update({truth_key(file, v): f"{extract_id}#{i}" for i, v in enumerate(numeric)})
            for value in table_values:
                if value in numeric:
                    continue
                out[truth_key(file, value)] = _write_fact(writer, value, anchor_of, file_sha, texts, lloqs, mapping, method)
            lines = [(writer.entity_ref(v, anchor_of, file_sha, method), number) for v in table_values
                     if v.field == "lloq" and v not in numeric and (number := _reading(v.value)[0]) is not None]
            for value, entity, lloq, unit in _token_lloqs(numeric, refs, lines, lloqs):
                at = dict(value.locators)
                cells = {part: at[part] for part in ("study", "analyte", "matrix") if part in at and getattr(entity, part)}
                if unit is not None and unit == (value.unit or None) and "unit" in at:
                    cells["unit"] = at["unit"]                 # a token takes its column's unit: the unit cell is cited
                writer.fact(Fact(id="", delivery=delivery, entity=entity, field="lloq", value=lloq, unit=unit,
                                 verbatim=texts[value.locator], anchor=anchor_of[value.locator],
                                 locators={role: anchor_of[loc] for role, loc in cells.items()}, method=method,
                                 mapping=mapping, by="code", at=_now()))
        for value in file.values:
            if value.table == "":
                line = next((p for p in file.prose if re.search(rf"(?<!\S){re.escape(value.value)}", p)), value.value)
                texts.setdefault(value.locator, line)
                out[truth_key(file, value)] = _write_fact(writer, value, anchor_of, file_sha, texts, lloqs, None, "prose")
    return out


def _write_fact(writer: _Writer, value: TruthValue, anchor_of: dict[str, str], file_sha: str, texts: dict[str, str],
                lloqs: dict[str, tuple[str, str]], mapping: MappingUse | None, method: Method) -> str:
    at = dict(value.locators)
    _value, censored, lloq, lloq_unit, uloq = _censoring(value, lloqs)
    found = field(value.field)
    numeric = found is not None and found.value in ("number", "integer")
    prose = method == "prose"
    fact = Fact(id="", delivery=writer.delivery, entity=writer.entity_ref(value, anchor_of, file_sha, method),
                field=value.field, value=_fact_value(value), unit=value.unit or None,
                verbatim=texts.get(value.locator, value.value), conditions=dict(value.conditions), time=_number(value.time),
                time_unit=value.time_unit or None, statistic=value.statistic or None, spread=_number(value.spread),
                spread_kind=value.spread_kind or None, n=int(value.n) if value.n else None,
                censored=censored if numeric else False, lloq=lloq if numeric else None,
                lloq_unit=lloq_unit if numeric else None, uloq=uloq if numeric else None, anchor=anchor_of[value.locator],
                locators={role: anchor_of[loc] for role, loc in at.items()}, method=method, mapping=mapping,
                model=TRUTH_MODEL if prose else None, by=f"agent:{TRUTH_MODEL.agent_run}" if prose else "code", at=_now())
    return writer.fact(fact)
