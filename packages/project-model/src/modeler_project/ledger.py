"""The ledger's write side (contracts §6.3): every value read from a client file, with its anchor, append-only.

`Ledger` is a `LedgerView` (the read side's fold, a snapshot) that also writes; after each write it calls `refresh()`,
so its next read folds again. It writes two chained logs (`ledger/facts.jsonl`: fact, extract, status;
`ledger/entities.jsonl`: entity, alias, merge) and content-addressed extract files. `conflicts()` and
`pending_links()` are the read side's (`ledger_view`): any `LedgerView` gives them, and this class inherits them.

What a mapped table becomes (`record_extraction`):
- its numeric rows: ONE `TableExtract` (column-wise, one entry per value with its own locator: `tx-<16 hex>#<i>`);
- its constants that are neither a condition nor a label (a caption's study id, dose, food state; the names of its
  entities included), its text-valued rows (route, dosage form, polymorph) and its relation rows (a DDI ratio with its
  CI and the other arm): scalar facts, one per value;
- its labels: entities, resolved inside the file first (`ledger_entities.resolve`); a study named in another file is
  that file's study, joined only through the `link.study_id` fact resolve anchors at this file's label;
- every LLOQ it states (the table's, a column's own, a token's "<0.5"): ONE `lloq` fact per (study, analyte, matrix)
  and number, with its unit as written and its anchor; each value keeps its own `lloq`.
A table that names no study gives values with no study: kept, never guessed from the file name.

Identity, so that a re-run is idempotent (a batch is not atomic: every writer decides from what is there, under the
log's lock):
- an extract: one active extract per table of a file. An active extract of the same file, region and mapping id (any
  version, §6.3) whose values equal the new ones (entity ids followed through merges; locators by their identity, a
  PDF box aside; the parser version aside) is kept and nothing is written, whatever the delivery, run or mapping
  version: the same bytes again, a re-parse whose anchors all hold, the same values after an entity merge, a new
  mapping version that reads every value the same (the kept extract names the version that read it; its evidence
  level follows that version's decision). Otherwise the new extract supersedes every earlier active extract of that
  region: a new mapping version that reads a value differently, a value moved by a re-parse. An extract whose region
  is gone after a re-parse is retired with a status line (`retire_regions`, reason "region gone after re-parse"); an
  earlier extract code set aside (superseded, retired) whose values are recorded again is the active one again.
  A region's id is the parser's (a PDF table's hashes its box), so a re-parse may give one table another id while
  every cell stays where it was. The table is then known by its cells, not its id: an extract of the same file and
  mapping id read under another parser version whose values equal the new ones by place is that extract (kept,
  nothing written, its confirmation still bound), whatever its region id; `retire_regions` does not retire an extract
  all of whose values `check_anchors` found again; and a new extract supersedes an active extract read under another
  parser version that reads one of its cells (`cells_in_common`), so one table never has two active extracts;
- a fact: the same field at the same place (its anchor's identity; for a table's fact, the study, arm, product and
  batch it is about; its analyte, labels, conditions and time) read by the same mapping (any version) with the same
  content is written once; another content there supersedes the active fact. Two tables that cite one line read it
  once (another mapping's active fact with the same reading is that fact); read differently, both stay (a conflict).
  A fact a person excluded or corrected is not written again;
- what an earlier recording of a region under the same mapping wrote and a later one no longer reads (a constant a
  corrected mapping version stops reading, a table that now has no numeric value) is set aside with a status line,
  reason "not read again ...", and set proposed again when it is read again.
Status is never stored on a fact (the fold computes it), and no confidence exists anywhere. No audit event is written
per fact: `enter` (a person's entry) writes `intake.entry`; runs and the review's decisions are audited by their
owners.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Collection, Mapping, Sequence
from types import MappingProxyType
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from modeler_intake.anchors import PdfCell, anchor_text, canonical, check_id, parse_locator
from modeler_intake.document_reading import name_key
from modeler_intake.fields import CONDITION_FIELDS, LABEL_FIELDS, DocumentRole, SpreadKind, Statistic, read_choice
from modeler_intake.fields import field as field_def
from modeler_intake.mapping_spec import ExtractedRow, ExtractResult, ProseFact
from modeler_intake.source_model import Region, RegionGrid
from modeler_project import ledger_compute, ledger_links
from modeler_project.intake_records import Choice, FileRecord, LinkConfirmation, MappingEntry
from modeler_project.intake_rules import IntakeRules
from modeler_project.intake_store import ChainEntry
from modeler_project.ledger_entities import EntityBook, follow_ref, home_file, label_key, merge, now, resolve
from modeler_project.ledger_models import (
    EntityRef,
    EntityType,
    ExtractRef,
    Fact,
    MappingUse,
    Merge,
    Method,
    ModelUse,
    Relation,
    StatusChange,
    TableExtract,
    ValueState,
)
from modeler_project.ledger_view import _NAMING, LedgerView, _label, _reading, _unit_key, is_compound_field
from modeler_project.workspace import Workspace

REGION_GONE = "region gone after re-parse"
# the reason a table's fact is set aside when a later recording of its region under the same mapping no longer reads it
NOT_READ_AGAIN = "not read again"
_ACTIVE = ("proposed", "confirmed")
_TABLE_METHODS = frozenset(("cell", "pdf_table", "docx_table"))
# the method of a table's facts, by the parser that read the file (a table read under another parser: by its locator)
_TABLE_METHOD: Mapping[str, Method] = MappingProxyType(
    {"workbook": "cell", "delimited": "cell", "pdfplumber": "pdf_table", "docx": "docx_table"})
_LOCATOR_METHOD: Mapping[str, Method] = MappingProxyType(
    {"sheet_cell": "cell", "pdf_cell": "pdf_table", "docx_cell": "docx_table"})
_ENTITY_PARTS: tuple[EntityType, ...] = ("study", "arm", "product", "batch", "analyte")
# the roles of a value's label cells (TableExtract.entity_locators); every other role is a qualifier or a condition.
# A key-value table's label cell is the role "parameter" (contracts §13)
_LABEL_ROLES = frozenset((*_ENTITY_PARTS, *LABEL_FIELDS, "other_arm", "parameter"))
# the entity parts a constant's fact is about, by its field's level (the synthetic truth's convention, §13)
_LEVEL_PARTS: Mapping[str, tuple[EntityType, ...]] = MappingProxyType({
    "study": ("study",), "arm": ("study", "arm"), "product": ("product",), "batch": ("product", "batch"),
    "analyte": ("study", "analyte"), "compound": ()})
_BOX = re.compile(r"@-?\d+\.\d{2},-?\d+\.\d{2},-?\d+\.\d{2},-?\d+\.\d{2}$")
# Across parser versions, two PDF cells of one page are one cell when their boxes overlap by at least half: the rule by
# which `check_anchors` finds a value again after a re-parse (contracts §6.1). A PDF cell's own numbers (table, row,
# column) are the parser's: one that finds another table on the page numbers the others anew
_SAME_PDF_CELL = 0.5
_LOCATOR_COLUMNS = ("locator", "time_locator", "time_actual_locator", "unit_locator", "spread_locator", "n_locator",
                    "lloq_locator")
# what makes two facts the same content: everything but who, when, which delivery or run, which agent run, and what
# it supersedes (its anchors and locators by their identity)
_NOT_CONTENT = frozenset(("id", "delivery", "run_id", "supersedes", "reason", "by", "at", "model"))


class _B(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ExtractionContext(_B):
    """Where the values come from: the arrival (delivery, run) and the file as parsed (parser and its version)."""

    delivery: str
    run_id: str | None
    file: FileRecord
    parser: str
    parser_version: str
    document_role: DocumentRole = "other"
    drug: str = ""


class Recorded(_B):
    """What one recording gave: the extract (None: no numeric value), the facts and entities it names (written now or
    found as they were), and what it superseded."""

    extract: str | None
    facts: tuple[str, ...]
    entities: tuple[str, ...]
    superseded: tuple[str, ...]


# --- identity -----------------------------------------------------------------------------------------------------


def place(locator: str) -> str:
    """A locator's identity as text: the locator without its PDF box (§4.1: the box is never compared)."""
    return _BOX.sub("", locator)


def anchor_place(anchor: str) -> str:
    """An anchor's identity: the file and the place, parser and parser version aside (a re-parse that finds the same
    cell is the same place)."""
    head, _, locator = anchor.partition("#")
    return f"{head.split('@', 1)[0]}#{place(locator)}"


def _box_share(a: Sequence[float], b: Sequence[float]) -> float:
    """The share of the smaller box that two boxes have in common: the anchor check's measure
    (`modeler_intake.source.pdf.overlap`; computed here so that the ledger does not load the parsers)."""
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    if width <= 0 or height <= 0:
        return 0.0
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return width * height / smaller if smaller > 0 else 0.0


def cells_in_common(old: Sequence[str], new: Sequence[str]) -> bool:
    """Whether two sets of cells of one file, located under two parser versions (locator texts), have a cell in common:
    the same place (§4.1's identity) for a sheet or Word cell; for a PDF cell the same page and boxes that overlap by
    at least half, as `check_anchors` finds a value again, never its table, row and column numbers."""
    boxes: dict[int, list[Sequence[float]]] = {}
    places: set[str] = set()
    for text in new:
        if not text:
            continue
        locator = parse_locator(text)
        if isinstance(locator, PdfCell):
            boxes.setdefault(locator.page, []).append(locator.box)
        else:
            places.add(place(text))
    for text in old:
        if not text:
            continue
        locator = parse_locator(text)
        if isinstance(locator, PdfCell):
            if any(_box_share(locator.box, box) >= _SAME_PDF_CELL for box in boxes.get(locator.page, ())):
                return True
        elif place(text) in places:
            return True
    return False


def _follow_relation(relation: Any, merged: Mapping[str, str]) -> Any:
    if not relation:
        return relation
    other = follow_ref(EntityRef.model_validate(relation["other"]), merged)
    return {**relation, "other": other.model_dump(mode="json")}


def _content(body: Mapping[str, Any], merged: Mapping[str, str], *, mapping: bool = True) -> str:
    """A fact's content as identity compares it: the mapping by its id, any version (`mapping=False`: the reading
    alone, whichever mapping read it)."""
    out = {k: v for k, v in body.items() if k not in _NOT_CONTENT and k != "mapping"}
    if mapping:
        out["mapping"] = _group(body)
    out["entity"] = follow_ref(EntityRef.model_validate(body["entity"]), merged).model_dump(mode="json")
    out["relation"] = _follow_relation(body.get("relation"), merged)
    out["anchor"] = anchor_place(body["anchor"]) if body.get("anchor") else None
    out["locators"] = {role: anchor_place(a) for role, a in (body.get("locators") or {}).items()}
    return canonical(out)


def _slot(body: Mapping[str, Any], merged: Mapping[str, str]) -> tuple[Any, ...] | None:
    """Where a fact stands: an anchored fact by its field, place, analyte, labels, conditions and time (a table's fact
    also by the study, arm, product and batch it is about: one cell a mapping reads for two arms is two readings, side
    by side, never one superseding the other); a derived fact by its compute and inputs; a person's entry nowhere (each
    is a decision of its own)."""
    if body.get("anchor"):
        entity = follow_ref(EntityRef.model_validate(body["entity"]), merged)
        about = (entity.study, entity.arm, entity.product, entity.batch) if body.get("mapping") else ()
        return ("anchored", body["field"], anchor_place(body["anchor"]), *about, entity.analyte, entity.subject,
                entity.period, entity.sequence, entity.occasion, entity.vessel, entity.matrix,
                canonical(body.get("conditions") or {}), body.get("time"))
    if body.get("method") == "derived":
        return ("derived", body.get("compute"), tuple(body.get("derived_from") or ()))
    return None


def _group(body: Mapping[str, Any]) -> str | None:
    """The mapping a table's fact was read by (any version): facts of two mappings at one place stand apart, so two
    tables that cite one title never supersede each other's reading of it."""
    mapping = body.get("mapping")
    return mapping.get("mapping_id") if mapping else None


def _comparable(extract: TableExtract, merged: Mapping[str, str]) -> str:
    """An extract's content as the identity rule compares it: entity ids through merges, locators by identity, the
    parser, its version and the region id it gave the table aside, the mapping by its id (any version, §6.3)."""
    body = extract.model_dump(mode="json")
    for name in ("schema_id", "parser", "parser_version", "region_id"):
        body.pop(name, None)
    body["mapping"] = extract.mapping.mapping_id
    body["entities"] = [follow_ref(e, merged).model_dump(mode="json") for e in extract.entities]
    body["entity_locators"] = [{r: place(loc) for r, loc in d.items()} for d in extract.entity_locators]
    body["condition_locators"] = [{r: place(loc) for r, loc in d.items()} for d in extract.condition_locators]
    for name in _LOCATOR_COLUMNS:
        body[name] = [place(loc) if loc else None for loc in getattr(extract, name)]
    body["interval_locator"] = [[place(p[0]), place(p[1])] if p else None for p in extract.interval_locator]
    return canonical(body)


def _typed(field: str, value: Any) -> Any:
    """A value as the ledger stores it: an integer field's whole number as an int, a choice as `read_choice` reads it
    (the text as written when it states none)."""
    found = field_def(field)
    if found is None:
        return value
    if found.value == "integer" and isinstance(value, float) and value.is_integer():
        return int(value)
    if found.value == "choice" and isinstance(value, str):
        return read_choice(field, value) or value
    return value


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _digits_in(number: float, quote: str) -> bool:
    """Whether a quote writes this number: its significant digits appear among the quote's digits (Unicode digits
    folded, so a "10⁻³" counts), whatever its decimal mark or grouping ("12,5", "1 234.5"). A loose test, for a number
    the strict prose check parsed from that quote: it refuses only a number the quote cannot have given."""
    significant = re.sub(r"\D", "", f"{abs(number):.15g}".split("e")[0]).strip("0")
    if not significant:
        return True                                        # zero: nothing to look for
    written = "".join(str(unicodedata.digit(c)) for c in re.findall(r"\d", unicodedata.normalize("NFKC", quote)))
    return significant in written


# --- the log's bookkeeping, read under the lock -----------------------------------------------------------------


class _FactsBook:
    """facts.jsonl folded as far as a writer needs: each line's body, the latest status line of each target, and what
    a later item that is not excluded supersedes."""

    def __init__(self, entries: list[ChainEntry]):
        self.facts: list[dict[str, Any]] = []
        self.extracts: list[tuple[int, ExtractRef]] = []
        self.changes: dict[str, dict[str, Any]] = {}                      # target -> its last status line's body
        superseders: list[tuple[str, str, tuple[str, ...]]] = []          # (item, its method, what it names)
        for line in entries:
            if line.kind == "fact":
                self.facts.append(line.body)
                if line.body.get("supersedes"):
                    superseders.append((line.body["id"], line.body.get("method", ""), (line.body["supersedes"],)))
            elif line.kind == "extract":
                ref = ExtractRef.model_validate(line.body)
                self.extracts.append((line.seq, ref))
                if ref.supersedes:
                    superseders.append((ref.id, "extract", ref.supersedes))
            elif line.kind == "status":
                self.changes[line.body["target"]] = line.body
        self.status: dict[str, str] = {target: body["status"] for target, body in self.changes.items()}
        self.superseded_by: dict[str, tuple[str, str]] = {}               # target -> (item, its method)
        for item, method, named in superseders:
            if self.status.get(item) == "excluded":
                continue
            for target in named:
                self.superseded_by[target] = (item, method)

    def active(self, item: str) -> bool:
        return item not in self.superseded_by and self.status.get(item) != "excluded"

    def set_aside_by_code(self, item: str, *reasons: str) -> bool:
        """Whether code excluded this item last, for a reason that starts with one of `reasons` (any reason when none
        is given). A person's exclusion is never undone by a writer."""
        change = self.changes.get(item)
        return (change is not None and change["status"] == "excluded" and change.get("by") == "code"
                and (not reasons or str(change.get("reason", "")).startswith(reasons)))

    def superseded_by_code(self, item: str) -> bool:
        """Whether an item stands superseded by a later reading (a person's correction does not count: what it
        corrected is not written again)."""
        return item in self.superseded_by and self.superseded_by[item][1] != "person"


# --- names, once per recording ------------------------------------------------------------------------------------


class _Names:
    """The entities one recording names, each label resolved once (cached by type, key and parent)."""

    def __init__(self, ledger: Ledger, context: ExtractionContext, *, method: Method, mapping: MappingUse | None,
                 model: ModelUse | None, anchor: Callable[[str], str]):
        from modeler_project.client_data import review_record

        self.ledger, self.context, self.method, self.mapping, self.model = ledger, context, method, mapping, model
        self.anchor = anchor
        self.review = review_record(ledger.ws)
        self.cache: dict[tuple[str, str, str | None], str] = {}
        self.entities: list[str] = []
        self.links: list[str] = []

    def get(self, type: EntityType, label: Any, parent: str | None, locator: str | None) -> str | None:
        if label is None or not name_key(str(label).strip()):
            return None
        label = str(label).strip()
        key = (type, label_key(label), parent)
        if key not in self.cache:
            source = self.anchor(locator) if locator else None
            entity, link = resolve(self.ledger, type=type, label=label, parent=parent, source=source,
                                   file_sha256=self.context.file.sha256, by="code", delivery=self.context.delivery,
                                   run_id=self.context.run_id, method=self.method, mapping=self.mapping, model=self.model,
                                   review=self.review)
            self.cache[key] = entity.id
            if entity.id not in self.entities:
                self.entities.append(entity.id)
            if link is not None and link.id not in self.links:
                self.links.append(link.id)
        return self.cache[key]

    def ref(self, labels: Mapping[str, str], locators: Mapping[str, str], field: str) -> EntityRef:
        """A row's EntityRef: its entities resolved (none for a compound field: it belongs to no study or product,
        §6.6), its labels as written."""
        parts: dict[str, str | None] = {}
        if not is_compound_field(field):
            parts["study"] = self.get("study", labels.get("study"), None, locators.get("study"))
            parts["arm"] = self.get("arm", labels.get("arm"), parts["study"], locators.get("arm"))
            parts["product"] = self.get("product", labels.get("product"), None, locators.get("product"))
            parts["batch"] = self.get("batch", labels.get("batch"), parts["product"], locators.get("batch"))
        parts["analyte"] = self.get("analyte", labels.get("analyte"), None, locators.get("analyte"))
        written = {role: str(labels[role]).strip() or None for role in LABEL_FIELDS if labels.get(role) is not None}
        return EntityRef(**parts, **written)


# --- the ledger -------------------------------------------------------------------------------------------------


class Ledger(LedgerView):
    """The ledger's write side (see the module docstring). Its `conflicts()` and `pending_links()` are the read side's
    (`LedgerView`), computed on this ledger's snapshot with its rules."""

    def __init__(self, ws: Workspace, *, rules: IntakeRules | None = None):
        super().__init__(ws, rules=rules)                   # None: the rules file (intake_rules.rules())
        self._versions: dict[str, str] = {}                 # extract id -> the parser version it was read under
        # (file, parser version) -> the extracts this ledger's recordings gave for that parse (written, or kept)
        self._recorded: dict[tuple[str, str], set[str]] = {}

    def _parser_version(self, extract_id: str) -> str:
        """The parser version an extract a line names was read under (its file is written once: it never changes)."""
        if extract_id not in self._versions:
            self._versions[extract_id] = self.store._extract_file(extract_id).parser_version
        return self._versions[extract_id]

    def _moved_here(self, ref: ExtractRef, parser_version: str, cells: Sequence[str]) -> bool:
        """Whether an extract of the file recorded under ANOTHER region id is of the table these cells are: only an
        extract read under another parser version can be (within one version a region's id is its table's), and it is
        when one of its values stands in one of the cells (`cells_in_common`)."""
        if self._parser_version(ref.id) == parser_version:
            return False
        return cells_in_common(self.store._extract_file(ref.id).locator, cells)

    # --- recording a table --------------------------------------------------------------------------------------

    def record_extraction(self, *, region: Region, grid: RegionGrid, mapping: MappingEntry, result: ExtractResult,
                          context: ExtractionContext) -> Recorded:
        """Record what executing `mapping` on this region gave (the module docstring says what each part becomes).
        Idempotent: the same result again writes nothing. A locator that is not a cell of this region or of its
        context, or a grid of another file, parser or region than the context's, is a ValueError (a bug, not
        content)."""
        sha = context.file.sha256
        if (grid.file_sha256, grid.parser, grid.parser_version, grid.region_id) != (
                sha, context.parser, context.parser_version, region.id):
            raise ValueError(f"region {region.id}: the grid ({grid.file_sha256[:12]}, {grid.parser}/{grid.parser_version},"
                             f" {grid.region_id}) is not the context's file and parser version")
        texts = {c.locator: c.text for c in grid.cells.values()}
        texts.update({c.locator: c.text for c in (*grid.caption, *(c for line in (*grid.above, *grid.below) for c in line))})

        def anchor(locator: str) -> str:
            if locator not in texts:
                raise ValueError(f"{locator!r} is not a cell of region {region.id} or of its context")
            return anchor_text(sha, context.parser, context.parser_version, locator)

        use = MappingUse(mapping_id=mapping.mapping_id, version=mapping.version)
        method = _TABLE_METHOD.get(context.parser) or next(
            (_LOCATOR_METHOD.get(parse_locator(loc).kind, "cell") for loc in texts), "cell")
        names = _Names(self, context, method=method, mapping=use, model=None, anchor=anchor)

        naming: dict[str, tuple[str, str]] = {}                # role -> (label, locator): the table's naming constants
        for constant in result.constants:
            role = _NAMING.get(constant.field)
            if role and role not in naming and isinstance(constant.value, str) and name_key(constant.value):
                naming[role] = (constant.value, constant.locator)

        rows: list[tuple[ExtractedRow, EntityRef, dict[str, str]]] = []
        for row in result.rows:
            labels = {r: str(v) for r, v in row.labels.items() if v is not None and str(v).strip()}
            locators = {r: loc for r, loc in row.label_locators.items() if loc}
            for role, (label, locator) in naming.items():          # the constants name every row; a row's own refine
                if role not in labels:
                    labels[role] = label
                    locators[role] = locator
            ref = names.ref(labels, locators, row.field)
            label_cells = {r: loc for r, loc in locators.items() if r in _LABEL_ROLES and (
                r == "parameter" or r == "other_arm" or (getattr(ref, r, None) if r in _ENTITY_PARTS else labels.get(r)))}
            for loc in label_cells.values():
                anchor(loc)
            rows.append((row, ref, label_cells))

        # the table's own entity, which its constants are about: the naming constants, else the one entity its rows name
        table: dict[str, str] = {}
        table_cells: dict[str, str] = {}
        for part in _ENTITY_PARTS:
            if part in naming:
                parent = table.get("study") if part == "arm" else table.get("product") if part == "batch" else None
                found = names.get(part, naming[part][0], parent, naming[part][1])
                if found is not None:
                    table[part], table_cells[part] = found, naming[part][1]
                continue
            named = {getattr(ref, part) for _row, ref, _cells in rows}
            if len(named) == 1 and None not in named:
                table[part] = named.pop()
                first = next((cells for _row, ref, cells in rows if part in cells), {})
                if part in first:
                    table_cells[part] = first[part]
        table_ref = EntityRef(**table)

        facts: list[Fact] = []
        base = dict(delivery=context.delivery, run_id=context.run_id, method=method, mapping=use, by="code")
        lloq_constants = []
        for constant in result.constants:
            if constant.field in CONDITION_FIELDS or constant.field in LABEL_FIELDS:
                continue                                       # on every row already (conditions, labels)
            if constant.field == "lloq":
                lloq_constants.append(constant)
                continue
            found = field_def(constant.field)
            parts = _LEVEL_PARTS.get(found.level if found is not None else "", _ENTITY_PARTS)
            entity = EntityRef(**{p: getattr(table_ref, p) for p in parts if getattr(table_ref, p)})
            facts.append(Fact(
                id="", entity=entity, field=constant.field, value=_typed(constant.field, constant.value), unit=constant.unit,
                verbatim=constant.verbatim, anchor=anchor(constant.locator),
                locators={p: anchor(table_cells[p]) for p in parts if getattr(entity, p) and p in table_cells},
                at=now(), **base))

        facts += self._lloq_facts(rows, lloq_constants, table_ref, texts, anchor, base)
        numeric: list[tuple[ExtractedRow, EntityRef, dict[str, str]]] = []
        for row, ref, cells in rows:
            if "other_arm" in row.labels or row.field.startswith("relation."):
                facts.append(self._relation_fact(row, ref, cells, names, mapping, anchor, base))
            elif row.text_value is not None and row.value is None:
                facts.append(Fact(
                    id="", entity=ref, field=row.field, value=_typed(row.field, row.text_value), unit=row.unit,
                    verbatim=row.verbatim, conditions=dict(row.conditions), time=row.time, time_unit=row.time_unit,
                    time_actual=row.time_actual, statistic=row.statistic, n=row.n, anchor=anchor(row.locator),
                    locators=_row_locators(row, cells, anchor), at=now(), **base))
            else:
                numeric.append((row, ref, cells))

        extract_id, superseded = None, ()
        if numeric:
            extract = _extract(numeric, file_sha256=sha, context=context, region_id=region.id, mapping=use,
                               kind=mapping.spec.kind, decimal=result.decimal, anchor=anchor)
            extract_id, superseded, _written = self._write_extract(
                extract, delivery=context.delivery, run_id=context.run_id, cells=[c.locator for c in grid.cells.values()])
            self._recorded.setdefault((sha, context.parser_version), set()).add(extract_id)
        written = self._write_facts(facts)
        ids = list(dict.fromkeys([*names.links, *(w[0] for w in written)]))
        own = {place(c.locator) for c in (*grid.cells.values(), *grid.caption)}
        lines = {place(c.locator) for line in (*grid.above, *grid.below) for c in line} - own
        # with an extract, `_write_extract` has settled the table's earlier extracts; with none (no numeric value is
        # read any more), the region's cells say which earlier extract of another region id was this table's
        retired = self._retire_unread(file_sha256=sha, region_id=region.id, mapping=use, own=own, lines=lines,
                                      kept={*ids, *([extract_id] if extract_id else [])},
                                      parser_version=context.parser_version,
                                      cells=() if extract_id else [c.locator for c in grid.cells.values()])
        self.refresh()
        return Recorded(extract=extract_id, facts=tuple(ids), entities=tuple(names.entities),
                        superseded=(*superseded, *(w[1] for w in written if w[1] and w[2]), *retired))

    def _retire_unread(self, *, file_sha256: str, region_id: str, mapping: MappingUse, own: Collection[str],
                       lines: Collection[str], kept: Collection[str], parser_version: str,
                       cells: Sequence[str]) -> list[str]:
        """After a recording of a region: what an earlier recording of it under the same mapping wrote and this one no
        longer reads is set aside with a status line (reason NOT_READ_AGAIN), so a constant a corrected mapping version
        stops reading does not stay active. An extract is the region's by its region id, or, read under another parser
        version than `parser_version` (a re-parse may give the region another id), by a value that stands in one of
        the region's `cells` (`_moved_here`; given only when this recording has no extract of its own, which would
        have superseded it). A table's fact of the same
        mapping is the region's when its anchor is one of the region's own places (`own`: its cells and caption, which
        no other region has); at a line above or below it (`lines`, which a neighbouring table of the same layout may
        cite too), only when an earlier version of the mapping read it, so two such tables never set each other's
        reading aside. Read again later, it is set proposed again (`_write_facts`, `_write_extract`). A person's
        entry, a prose fact and a derived fact are never touched; derived facts of a retired input are `derive`'s.
        Repeats while setting one aside brings back what it had superseded. A fact another table's mapping reads too
        (one line cited by two tables) is set aside with the mapping that wrote it; the other table writes its own
        reading at its next recording."""
        reason = f"{NOT_READ_AGAIN} by {mapping.mapping_id} v{mapping.version} (region {region_id})"
        retired: list[str] = []

        def decide(entries: list[ChainEntry]) -> list[tuple[str, Any]]:
            book = _FactsBook(entries)
            targets = [ref.id for _seq, ref in book.extracts
                       if ref.file_sha256 == file_sha256 and ref.mapping.mapping_id == mapping.mapping_id
                       and ref.id not in kept and book.active(ref.id)
                       and (ref.region_id == region_id or (cells and self._moved_here(ref, parser_version, cells)))]
            for body in book.facts:
                used = body.get("mapping")
                if body["id"] in kept or not used or used.get("mapping_id") != mapping.mapping_id \
                        or body.get("method") not in _TABLE_METHODS or not body.get("anchor") or not book.active(body["id"]):
                    continue
                head, _, locator = body["anchor"].partition("#")
                at = place(locator)
                if head.split("@", 1)[0] == file_sha256 and (
                        at in own or (at in lines and used.get("version") != mapping.version)):
                    targets.append(body["id"])
            retired.extend(targets)
            return [("status", StatusChange(target=target, status="excluded", reason=reason, by="code",
                                            at=now()).model_dump(mode="json")) for target in targets]

        for _round in range(16):
            if not self.store.facts.append_if(decide):
                break
        return retired

    def _lloq_facts(self, rows: Sequence[tuple[ExtractedRow, EntityRef, dict[str, str]]], constants: Sequence[Any],
                    table: EntityRef, texts: Mapping[str, str], anchor: Callable[[str], str],
                    base: Mapping[str, Any]) -> list[Fact]:
        """Every stated LLOQ once per (study, analyte, matrix) and number: a value's own LLOQ cell (the table's line, a
        column's own, a "<0.5" token), the table's LLOQ constant; a line or column before a token, which states the
        same number again. The unit is the one the LLOQ's own text states (`lloq_unit`, None when it states none); only
        a token takes its column's unit, with the unit cell among its locators. An LLOQ constant whose value is not a
        number is kept as written (a fact, for the checks), never dropped."""
        stated: list[tuple[bool, EntityRef, float | str, str | None, str, dict[str, str]]] = []
        for row, ref, cells in rows:
            if row.lloq is None or not row.lloq_locator:
                continue
            entity = EntityRef(study=ref.study, analyte=ref.analyte, matrix=ref.matrix)
            at = {p: cells[p] for p in ("study", "analyte", "matrix") if p in cells}
            token, unit = row.lloq_locator == row.locator, row.lloq_unit
            if token and unit is None:
                unit = row.unit
            if token and unit is not None and unit == row.unit and row.unit_locator:
                at["unit"] = row.unit_locator
            stated.append((token, entity, row.lloq, unit, row.lloq_locator, at))
        stated.sort(key=lambda s: s[0])                         # a stable sort: lines and columns before tokens
        used = {s[4] for s in stated}
        matrices = {ref.matrix for _row, ref, _cells in rows}
        matrix = matrices.pop() if len(matrices) == 1 else None
        first = next((cells for _row, ref, cells in rows if ref.matrix == matrix and matrix), {})
        for constant in constants:
            if constant.locator in used or constant.value is None:
                continue
            number = _number(constant.value)
            entity = EntityRef(study=table.study, analyte=table.analyte, matrix=matrix)
            cells = {p: loc for p, loc in first.items() if p in ("study", "analyte", "matrix") and getattr(entity, p)}
            stated.append((False, entity, number if number is not None else constant.value, constant.unit,
                           constant.locator, cells))
        out: list[Fact] = []
        seen: set[tuple[Any, ...]] = set()
        lines: set[tuple[Any, ...]] = set()                     # what a line or a column states, its unit aside
        for token, entity, value, unit, locator, cells in stated:
            number = _number(value)
            reading = float(f"{number:.12g}") if number is not None else " ".join(str(value).casefold().split())
            stating = (entity.study, entity.analyte, _label(entity.matrix), reading)
            key = (*stating, _unit_key("lloq", unit))
            if key in seen or (token and stating in lines):      # a token repeats the line's number: the line's fact
                continue
            seen.add(key)
            if not token:
                lines.add(stating)
            anchored = anchor(locator)                         # a cell of this region or its context, or a ValueError
            out.append(Fact(id="", entity=entity, field="lloq", value=float(number) if number is not None else value,
                            unit=unit, verbatim=texts[locator], anchor=anchored,
                            locators={p: anchor(loc) for p, loc in cells.items()}, at=now(), **base))
        return out

    def _relation_fact(self, row: ExtractedRow, ref: EntityRef, cells: Mapping[str, str], names: _Names,
                       mapping: MappingEntry, anchor: Callable[[str], str], base: Mapping[str, Any]) -> Fact:
        """A relation row: the value (a ratio), its interval, and the other arm it relates this arm to."""
        other = names.get("arm", row.labels.get("other_arm"), ref.study, row.label_locators.get("other_arm"))
        parts = row.field.split(".")
        if row.field.startswith("relation.") and len(parts) >= 3 and parts[1] in ("ddi_ratio", "test_vs_reference"):
            kind, parameter = parts[1], ".".join(parts[2:])
        else:
            kind = "ddi_ratio" if mapping.spec.kind == "ddi_relation" else "test_vs_reference"
            parameter = row.field.removeprefix("pk.")
        value = row.value if row.value is not None else row.text_value      # a ratio, else the text as written
        return Fact(
            id="", entity=ref, field=row.field, value=value, unit=row.unit, verbatim=row.verbatim,
            conditions=dict(row.conditions), time=row.time, time_unit=row.time_unit, time_actual=row.time_actual,
            statistic=row.statistic, spread=row.spread, spread_kind=row.spread_kind, n=row.n, interval=row.interval,
            interval_kind=row.interval_kind, interval_level=row.interval_level, censored=row.censored, lloq=row.lloq,
            lloq_unit=row.lloq_unit, uloq=row.uloq,
            relation=Relation(kind=kind, other=EntityRef(study=ref.study, arm=other), parameter=parameter),
            anchor=anchor(row.locator), locators=_row_locators(row, cells, anchor), at=now(), **base)

    # --- recording prose --------------------------------------------------------------------------------------------

    def record_prose(self, *, facts: Sequence[ProseFact], model: ModelUse, context: ExtractionContext) -> Recorded:
        """Record the facts the strict prose check accepted (code's numbers and spans). A study or arm label is
        resolved as a table's is (a study named in another file: joined through a link fact at the label's own span,
        read by the same model); a fact with no study label takes the file's study only when the file's values name
        exactly one; a compound field's fact belongs to no study.

        What the strict check guarantees is checked again before anything is written, since the ledger is the system
        of record: a label comes with its own span (never the value's: a join is anchored at the label), and a number
        is written in its quote (its significant digits, whatever the decimal mark or grouping). Otherwise a
        ValueError: a wiring bug, not content."""
        sha = context.file.sha256

        def anchor(locator: str) -> str:
            return anchor_text(sha, context.parser, context.parser_version, locator)

        for fact in facts:
            if fact.study_label is not None and name_key(fact.study_label) and not fact.study_locator:
                raise ValueError(f"a prose {fact.field} fact names study {fact.study_label!r} with no span of the label")
            if fact.arm_label is not None and name_key(fact.arm_label) and not fact.arm_locator:
                raise ValueError(f"a prose {fact.field} fact names arm {fact.arm_label!r} with no span of the label")
            number = _number(fact.value)
            found = field_def(fact.field)
            if number is not None and found is not None and found.value in ("number", "integer") \
                    and not _digits_in(number, fact.quote):
                raise ValueError(f"a prose {fact.field} fact stores {number!r}, which its quote does not write")

        names = _Names(self, context, method="prose", mapping=None, model=model, anchor=anchor)
        resolved: list[tuple[ProseFact, str | None]] = []
        for fact in facts:
            compound = is_compound_field(fact.field)
            resolved.append((fact, None if compound else names.get("study", fact.study_label, None, fact.study_locator)))
        self.refresh()
        named = {v.entity.study for v in self.values(file_sha256=sha) if v.entity.study}
        named |= {study for _f, study in resolved if study}
        only = next(iter(named)) if len(named) == 1 else None
        out: list[Fact] = []
        for fact, study in resolved:
            compound = is_compound_field(fact.field)
            if study is None and not compound:
                study = only
            arm = None if compound else names.get("arm", fact.arm_label, study, fact.arm_locator)
            locators = {}
            if fact.study_label and fact.study_locator and study:
                locators["study"] = anchor(fact.study_locator)
            if fact.arm_label and fact.arm_locator and arm:
                locators["arm"] = anchor(fact.arm_locator)
            out.append(Fact(id="", delivery=context.delivery, run_id=context.run_id, entity=EntityRef(study=study, arm=arm),
                            field=fact.field, value=_typed(fact.field, fact.value), unit=fact.unit, verbatim=fact.quote,
                            anchor=anchor(fact.locator), locators=locators, method="prose", model=model,
                            by=f"agent:{model.agent_run}", at=now()))
        written = self._write_facts(out)
        self.refresh()
        ids = list(dict.fromkeys([*names.links, *(w[0] for w in written)]))
        return Recorded(extract=None, facts=tuple(ids), entities=tuple(names.entities),
                        superseded=tuple(w[1] for w in written if w[1] and w[2]))

    # --- a person's entry and an exclusion ----------------------------------------------------------------------

    def enter(self, *, entity: EntityRef | None = None, field: str | None = None, value: Any, unit: str | None = None,
              time: float | None = None, time_unit: str | None = None, statistic: Statistic | None = None,
              spread: float | None = None, spread_kind: SpreadKind | None = None, n: int | None = None,
              conditions: Mapping[str, str] | None = None, censored: bool | None = None, lloq: float | None = None,
              lloq_unit: str | None = None, why: str, by: str, supersedes: str | None = None) -> Fact:
        """A person's entry or correction (method "person", no anchor: the signature binds it), audited `intake.entry`
        with the line's hash. `supersedes` names an active fact or value ("f-n", "tx-...#i"); the new fact inherits
        its entity, field, time, time unit, statistic, conditions and unit unless given, so a corrected point stays in
        its series, and the old value stays readable, superseded."""
        if not why or not why.strip():
            raise ValueError("an entry needs a reason")
        self.refresh()                                      # decide on the ledger as it is now, not a request's snapshot
        old: ValueState | None = None
        if supersedes is not None:
            if not supersedes.startswith("tx-"):
                check_id("line", supersedes)
            else:
                check_id("value", supersedes)
            old = self.value(supersedes)
            if old is None:
                raise KeyError(supersedes)
            if old.status not in _ACTIVE:
                raise ValueError(f"{supersedes} is {old.status}: only an active value is corrected")
            entity = entity if entity is not None else old.entity
            field = field if field is not None else old.field
            time = time if time is not None else old.time
            time_unit = time_unit if time_unit is not None else old.time_unit
            statistic = statistic if statistic is not None else old.statistic
            conditions = conditions if conditions is not None else old.conditions
            unit = unit if unit is not None else old.unit
        if field is None or field_def(field) is None:
            raise ValueError(f"not a ledger field: {field!r}")
        draft = Fact(id="", delivery=old.delivery if old is not None else "", entity=entity or EntityRef(), field=field,
                     value=_typed(field, value), unit=unit, conditions=dict(conditions or {}), time=time,
                     time_unit=time_unit, statistic=statistic, spread=spread, spread_kind=spread_kind, n=n,
                     censored=bool(censored), lloq=lloq, lloq_unit=lloq_unit, method="person", supersedes=supersedes,
                     reason=why.strip(), by=by, at=now())

        def decide(entries: list[ChainEntry]) -> list[tuple[str, Any]]:
            # under the lock: two people correcting one value at once give one correction, the other is refused
            if supersedes is not None:
                book = _FactsBook(entries)
                if any(item in book.superseded_by for item in (supersedes, supersedes.split("#")[0])):
                    raise ValueError(f"{supersedes} was superseded meanwhile: only an active value is corrected")
            return [("fact", lambda seq: draft.model_copy(update={"id": f"f-{seq}"}).model_dump(mode="json"))]

        (entry,) = self.store.facts.append_if(decide)
        fact = Fact.model_validate(entry.body)
        self.store.audit(actor=by, action="intake.entry", resource_id=fact.id, after={"fact": fact.id, "row_hash": entry.hash},
                         reason=why.strip())
        self.refresh()
        if supersedes is not None:
            self.retire_orphans()                           # a derived fact never outlives its input
        return fact

    def exclude(self, target: str, *, why: str, by: str) -> StatusChange:
        """Exclude a fact, an extract or one value of an extract, with the reason (a status line; the same exclusion
        again writes nothing). The decision that excludes it (a choice, a refused link) is audited by its owner."""
        if not why or not why.strip():
            raise ValueError("an exclusion needs a reason")
        kind = "value" if "#" in target else "extract" if target.startswith("tx-") else "line"
        check_id(kind, target)
        self.refresh()
        known = self.value(target) is not None if kind != "extract" else any(
            v.id.startswith(f"{target}#") for v in self.values(active=False))
        if not known:
            raise KeyError(target)
        change = self._exclude([target], why.strip(), by)[0]
        self.retire_orphans()                               # a derived fact never outlives its input
        return change

    def _exclude(self, targets: Sequence[str], reason: str, by: str) -> list[StatusChange]:
        return self._status(targets, "excluded", reason, by)

    def _status(self, targets: Sequence[str], status: Literal["excluded", "proposed"], reason: str,
                by: str) -> list[StatusChange]:
        """Status lines setting these targets' status, once each (a target whose last status line already says so for
        this reason is not written again)."""
        found: list[StatusChange] = []

        def decide(entries: list[ChainEntry]) -> list[tuple[str, Any]]:
            last: dict[str, StatusChange] = {}
            for line in entries:
                if line.kind == "status":
                    change = StatusChange.model_validate(line.body)
                    last[change.target] = change
            rows = []
            for target in dict.fromkeys(targets):
                earlier = last.get(target)
                if earlier is not None and earlier.status == status and earlier.reason == reason:
                    found.append(earlier)
                    continue
                change = StatusChange(target=target, status=status, reason=reason, by=by, at=now())
                found.append(change)
                rows.append(("status", change.model_dump(mode="json")))
            return rows

        self.store.facts.append_if(decide)
        self.refresh()
        return found

    # --- derived facts and links -----------------------------------------------------------------------------------

    def derive(self, *, context: ExtractionContext | None = None) -> list[Fact]:
        """Write the derived facts the ledger lacks (`ledger_compute.derivations`: an SD from an SE or a CV%, a dose in
        mg from g or µg), each naming its inputs and its compute; idempotent. A derived fact whose input is no longer
        active is superseded by the one its successor gives, or, when none is given, excluded with the reason."""
        self.refresh()
        made = ledger_compute.derivations(self, rules=self._rules(), confirmations=self._link_confirmations())
        if context is not None:
            made = [f.model_copy(update={"run_id": context.run_id}) for f in made]
        written = self._write_facts(made)
        self.refresh()
        # a derived fact code set aside (an input had gone, or waited for its link), whose inputs are all active and
        # settled again, is the same fact: back
        back = [w[0] for w in written if not w[2] and (state := self.value(w[0])) is not None and state.status == "excluded"
                and state.status_reason.startswith((ledger_compute.ORPHANED, ledger_compute.UNCONFIRMED))]
        if back:
            self._status(back, "proposed", "its inputs are active again", "code")
        self.retire_orphans()
        return [f.model_copy(update={"id": w[0], "supersedes": w[1]}) for f, w in zip(made, written, strict=True) if w[2]]

    def retire_orphans(self) -> list[StatusChange]:
        """Set aside every active derived fact an input of which is no longer active (superseded, excluded, a refused
        link) or is a cross-file value whose link no person has confirmed (`ledger_compute.orphans`), with the reason.
        Idempotent; writes nothing when none is found. `exclude`, `enter`, `apply_choice` and `link_files` call it; D6
        calls `derive` (which calls it) after it writes a `LinkConfirmation` or an `Assignment`, so a derived fact never
        outlives a refused link and one waits for a confirmed one. An excluded item supersedes nothing (the fold), so
        excluding a derived fact that had superseded an earlier one brings that one back: repeat until none is left."""
        changes: list[StatusChange] = []
        confirmations = self._link_confirmations()
        self.refresh()
        for _round in range(16):
            orphans = ledger_compute.orphans(self, confirmations)
            if not orphans:
                break
            for reason in dict.fromkeys(why for _f, why in orphans):
                changes += self._exclude([fid for fid, why in orphans if why == reason], reason, "code")
        return changes

    def link_files(self, *, context: ExtractionContext | None = None) -> list[Merge]:
        """Turn the explicit links into merges (`ledger_links.explicit_links`: the `link.protocol` and
        `link.cross_reference` facts of a file's own study that together name exactly one study of another file), and
        an ambiguous link a person confirmed into the merge of the file's study into the study chosen. Only a study
        whose home file is the link fact's file is ever merged by a link fact, so a re-run merges nothing more.
        Idempotent: only the merges written now are returned."""
        self.refresh()
        proposals = [*ledger_links.explicit_links(self)[0],
                     *ledger_links.confirmed_merges(self, self._link_confirmations(), **self._alias_sources())]
        made: list[Merge] = []
        for proposal in proposals:
            book = EntityBook(self.store.entities.entries())
            if proposal.from_id in book.merges or book.follow(proposal.into_id) == proposal.from_id:
                continue
            # only a link fact's own file's study is merged (condition 1): never a study of another file it sits on
            source = book.entities.get(proposal.from_id)
            stating = self.value(proposal.link_fact) if proposal.link_fact is not None else None
            if proposal.link_fact is not None and (source is None or stating is None
                                                   or home_file(source) != stating.file_sha256):
                continue
            made.append(merge(self, type=proposal.type, from_id=proposal.from_id, into_id=proposal.into_id,
                              link_fact=proposal.link_fact, why=proposal.why, by=proposal.by))
        self.refresh()
        if made:
            self.retire_orphans()             # a value a code merge joined waits for its link: so do its derived facts
        return made

    def _link_confirmations(self) -> list[LinkConfirmation]:
        """review.jsonl's `link` lines as they are now (a write decides on the log, not on a request's snapshot)."""
        return [LinkConfirmation.model_validate(line.body) for line in self.store.review.entries("link")]

    # --- choices (conflicts() and pending_links() are the read side's, inherited) ----------------------------------

    def apply_choice(self, choice: Choice) -> list[StatusChange]:
        """Settle a conflict as a person chose (the review's `choice` line, written and audited by its owner): every
        other value of the conflict that does not read as the kept one is excluded, the choice named in the reason.
        Excluding a correction brings back the value it corrected (the fold), so this repeats until the conflict is
        closed. A conflict that is no longer open gives nothing (the same choice again writes nothing)."""
        check_id("conflict", choice.conflict_id)
        reason = f"conflict {choice.conflict_id} settled by {choice.id}: {choice.keep} kept ({choice.why})"

        def reads(value_id: str) -> tuple[Any, ...] | None:
            value = self.value(value_id)
            return (_unit_key(value.field, value.unit), _reading(value)) if value is not None else None

        changes: list[StatusChange] = []
        self.refresh()
        for _round in range(16):
            conflict = next((c for c in self.conflicts() if c.id == choice.conflict_id), None)
            if conflict is None:
                break
            if choice.keep not in conflict.values:
                if not changes:
                    raise ValueError(f"{choice.keep} is not one of the values of {choice.conflict_id}")
                break
            kept = reads(choice.keep)
            others = [vid for vid in conflict.values if vid != choice.keep and reads(vid) != kept]
            if not others:
                break
            changes += self._exclude(others, reason, choice.by)
        if changes:
            self.retire_orphans()                           # a derived fact never outlives its input
        return changes

    # --- a re-parse ----------------------------------------------------------------------------------------------------

    def retire_regions(self, *, file_sha256: str, parser_version: str, regions: Collection[str], by: str = "code",
                       found: Collection[str] | None = None) -> list[StatusChange]:
        """After a re-parse under `parser_version`: every active extract of this file recorded under another parser
        version whose region is not among `regions` (the new document's region ids) is retired with a status line,
        reason "region gone after re-parse" (W lists it as an anchor problem). Idempotent.

        A region's id is the parser's, and a re-parse may change it while every cell stays (a PDF table's id hashes its
        box). So an extract whose region id is not among `regions` is still kept when its table is known to be there:
        - this ledger's own recordings under `parser_version` gave it (`record_extraction` kept it for a region of the
          new document, by its cells: `_write_extract`). A run that records the new document and then calls this, with
          the same `Ledger`, retires nothing it has just read again;
        - `found` names every active value of it. `found`: the ids of the values `check_anchors` found again in the new
          document, each at its place with the same text (the active values of the file read under another parser
          version that gave no `AnchorProblem`). §6.3: such an extract stays, and nothing is written. Give `found` when
          this is called before the recordings, or by another `Ledger` than the one that recorded.
        Without either, the region id alone decides, as before; the same table recorded again later is then set
        proposed again (two status lines, where the cases above write none)."""
        check_id("sha256", file_sha256)
        keep = frozenset(regions)
        recorded = frozenset(self._recorded.get((file_sha256, parser_version), ()))
        again = frozenset(found) if found is not None else None
        self.refresh()
        active = {v.id for v in self.values(file_sha256=file_sha256)} if again is not None else set()
        retired: list[StatusChange] = []

        def decide(entries: list[ChainEntry]) -> list[tuple[str, Any]]:
            book = _FactsBook(entries)
            rows = []
            for _seq, ref in book.extracts:
                if ref.file_sha256 != file_sha256 or ref.region_id in keep or not book.active(ref.id):
                    continue
                if ref.id in recorded or self._parser_version(ref.id) == parser_version:
                    continue
                if again is not None:
                    values = [value for i in range(ref.n) if (value := f"{ref.id}#{i}") in active]
                    if values and again.issuperset(values):
                        continue                              # every value is found again at its place: it stays
                change = StatusChange(target=ref.id, status="excluded", reason=REGION_GONE, by=by, at=now())
                retired.append(change)
                rows.append(("status", change.model_dump(mode="json")))
            return rows

        # an excluded extract supersedes nothing, so retiring one brings back the one it superseded: repeat until none
        for _round in range(16):
            if not self.store.facts.append_if(decide):
                break
        self.refresh()
        return retired

    # --- the writes ----------------------------------------------------------------------------------------------------

    def _write_facts(self, facts: Sequence[Fact]) -> list[tuple[str, str | None, bool]]:
        """Append these facts once each, under the facts log's lock: (fact id, the fact it supersedes, written now).

        A fact's place is its slot (`_slot`) and, for a table's fact, the mapping that read it (`_group`). A place that
        already holds the same content (active, or excluded or corrected by a person) is that fact; one that code set
        aside because a later recording did not read it (NOT_READ_AGAIN) is set proposed again. An active fact another
        mapping read at the same slot with the same reading is that fact too (two tables citing one title). Another
        content at its place supersedes the active fact there (unless the fact names what it supersedes); another
        mapping's different reading at that slot stays beside it (a conflict, both kept)."""
        if not facts:
            return []
        merged = EntityBook(self.store.entities.entries()).merged
        results: list[tuple[str, str | None, bool] | None] = [None] * len(facts)
        same_as: dict[int, int] = {}

        def decide(entries: list[ChainEntry]) -> list[tuple[str, Any]]:
            book = _FactsBook(entries)
            by_slot: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
            for body in book.facts:
                slot = _slot(body, merged)
                if slot is not None:
                    by_slot.setdefault(slot, []).append(body)
            contents: dict[tuple[str, bool], str] = {}

            def content(body: Mapping[str, Any], mapping: bool = True) -> str:
                key = (body["id"], mapping)
                if key not in contents:
                    contents[key] = _content(body, merged, mapping=mapping)
                return contents[key]

            rows: list[tuple[str, Any]] = []
            batch: dict[tuple[Any, str | None, str], int] = {}
            restored: list[str] = []
            for i, fact in enumerate(facts):
                body = fact.model_dump(mode="json")
                slot, wanted, group = _slot(body, merged), _content(body, merged), _group(body)
                supersedes = fact.supersedes
                if slot is not None:
                    there = by_slot.get(slot, [])
                    mine = [b for b in there if _group(b) == group]
                    kept = [b for b in mine if content(b) == wanted and not book.superseded_by_code(b["id"])]
                    if kept:
                        found = kept[-1]["id"]
                        results[i] = (found, None, False)
                        if book.set_aside_by_code(found, NOT_READ_AGAIN) and found not in restored:
                            restored.append(found)
                        continue
                    if group is not None and slot[0] == "anchored":
                        reading = _content(body, merged, mapping=False)
                        same = [b for b in there if _group(b) != group and book.active(b["id"])
                                and content(b, mapping=False) == reading]
                        if same:
                            results[i] = (same[-1]["id"], None, False)
                            continue
                    if (slot, group, wanted) in batch:
                        same_as[i] = batch[(slot, group, wanted)]
                        continue
                    batch[(slot, group, wanted)] = i
                    if supersedes is None:
                        active = [b for b in mine if book.active(b["id"])]
                        supersedes = active[-1]["id"] if active else None

                def make(seq: int, fact: Fact = fact, i: int = i, supersedes: str | None = supersedes) -> dict[str, Any]:
                    results[i] = (f"f-{seq}", supersedes, True)
                    return fact.model_copy(update={"id": f"f-{seq}", "supersedes": supersedes}).model_dump(mode="json")
                rows.append(("fact", make))
            rows += [("status", StatusChange(target=target, status="proposed", reason="read again", by="code",
                                             at=now()).model_dump(mode="json")) for target in restored]
            return rows

        self.store.facts.append_if(decide)
        for i, j in same_as.items():
            first = results[j]
            assert first is not None
            results[i] = (first[0], None, False)
        return [r for r in results if r is not None]

    def _write_extract(self, extract: TableExtract, *, delivery: str, run_id: str | None, cells: Sequence[str] = ()
                       ) -> tuple[str, tuple[str, ...], bool]:
        """Append the extract once (the module docstring's identity): (its id, what it supersedes, written now). The
        file is written under the lock, just before the line that names it.

        An extract of the region with these values that the ledger keeps (not superseded; a person's exclusion stands)
        is the one: nothing is written. An earlier one with these values that code set aside (superseded by a later
        recording: a rollback; retired when its region was gone and found again) is the one again: set proposed when
        code excluded it, and the extracts recorded after it excluded (an excluded item supersedes nothing).

        The table is the region's by its region id, or, for an extract read under another parser version (a re-parse
        may give the table another id while its cells stay), by its cells: one with these values, equal by place, is
        the one, as above; and an active one a value of which stands in a cell of the region (`cells`: the region's
        cells, else this extract's value cells; `_moved_here`) is of this table and is superseded with the region's
        own, so a table whose id changed never has two active extracts."""
        merged = EntityBook(self.store.entities.entries()).merged
        wanted = _comparable(extract, merged)
        out: list[tuple[str, tuple[str, ...], bool]] = []
        compared: dict[str, bool] = {}

        def equal(ref: ExtractRef) -> bool:
            if ref.id not in compared:
                compared[ref.id] = ref.mapping.mapping_id == extract.mapping.mapping_id and _comparable(
                    self.store._extract_file(ref.id), merged) == wanted
            return compared[ref.id]

        def kept(book: _FactsBook, same: list[ExtractRef]) -> bool:
            for ref in same:
                # the one the ledger keeps, or one a person excluded (that stands): nothing is written
                if not book.set_aside_by_code(ref.id) and (ref.id not in book.superseded_by
                                                           or book.status.get(ref.id) == "excluded"):
                    out.append((ref.id, (), False))
                    return True
            return False

        def decide(entries: list[ChainEntry]) -> list[tuple[str, Any]]:
            book = _FactsBook(entries)
            of_file = [ref for _seq, ref in book.extracts if ref.file_sha256 == extract.file_sha256]
            same = [ref for ref in of_file if ref.region_id == extract.region_id and equal(ref)]
            if kept(book, same):
                return []
            # the table under another region id: only an extract read under another parser version can be it
            elsewhere = [ref for ref in of_file if ref.region_id != extract.region_id
                         and self._parser_version(ref.id) != extract.parser_version]
            if not same:
                same = [ref for ref in elsewhere if (ref.n, ref.kind) == (extract.n, extract.kind) and equal(ref)]
                if kept(book, same):
                    return []
            moved = {ref.id for ref in elsewhere if book.active(ref.id)
                     and self._moved_here(ref, extract.parser_version, cells or extract.locator)}
            active = [ref for ref in of_file if book.active(ref.id) and (ref.region_id == extract.region_id or ref.id in moved)]
            back = same[-1] if same else None
            if back is not None:
                rows: list[tuple[str, Any]] = []
                if book.set_aside_by_code(back.id):
                    rows.append(("status", StatusChange(target=back.id, status="proposed", reason="recorded again",
                                                       by="code", at=now()).model_dump(mode="json")))
                later = [ref.id for ref in active if ref.id != back.id and ref.id not in back.supersedes]
                rows += [("status", StatusChange(target=target, status="excluded", by="code", at=now(),
                                                 reason=f"superseded: {back.id} recorded again").model_dump(mode="json"))
                         for target in later]
                out.append((back.id, tuple(later), bool(rows)))
                return rows
            extract_id, content_sha256 = self.store.put_extract(extract)      # never a line's id: that one is equal
            self._versions[extract_id] = extract.parser_version
            ref = ExtractRef(id=extract_id, content_sha256=content_sha256, file_sha256=extract.file_sha256,
                             region_id=extract.region_id, mapping=extract.mapping, kind=extract.kind, n=extract.n,
                             studies=tuple(sorted({e.study for e in extract.entities if e.study})),
                             products=tuple(sorted({e.product for e in extract.entities if e.product})),
                             delivery=delivery, run_id=run_id, supersedes=tuple(r.id for r in active), by="code", at=now())
            out.append((extract_id, ref.supersedes, True))
            return [("extract", ref.model_dump(mode="json"))]

        self.store.facts.append_if(decide)
        return out[0]


def _row_locators(row: ExtractedRow, cells: Mapping[str, str], anchor: Callable[[str], str]) -> dict[str, str]:
    """role -> anchor text of every cell a row's value is read with: its time, unit, spread, n, LLOQ, interval,
    label and condition cells."""
    out = {role: anchor(loc) for role, loc in (
        ("time", row.time_locator), ("time_actual", row.time_actual_locator), ("unit", row.unit_locator),
        ("spread", row.spread_locator), ("n", row.n_locator), ("lloq", row.lloq_locator)) if loc}
    if row.interval_locators is not None:
        out["interval_low"], out["interval_high"] = anchor(row.interval_locators[0]), anchor(row.interval_locators[1])
    out.update({role: anchor(loc) for role, loc in cells.items()})
    out.update({name: anchor(loc) for name, loc in row.condition_locators.items() if loc})
    return out


def _extract(rows: Sequence[tuple[ExtractedRow, EntityRef, dict[str, str]]], *, file_sha256: str,
             context: ExtractionContext, region_id: str, mapping: MappingUse, kind: Any, decimal: Any,
             anchor: Callable[[str], str]) -> TableExtract:
    """The numeric rows of one table as one column-wise extract: one `entities` entry per distinct (entity, label
    cells) pair and one `conditions` entry per distinct (conditions, cells) pair, so each value points at its own
    row's cells (contracts §13; `intake_fixtures.write_truth` writes the same)."""
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
    for row, ref, cells in rows:
        for loc in (row.locator, row.time_locator, row.time_actual_locator, row.unit_locator, row.spread_locator,
                    row.n_locator, row.lloq_locator, *(row.interval_locators or ()), *row.condition_locators.values()):
            if loc:
                anchor(loc)                                   # every locator is a cell of this region or its context
        entity_key = (ref.model_dump_json(), tuple(sorted(cells.items())))
        if entity_key not in entity_keys:
            entity_keys.append(entity_key)
            entities.append(ref)
            entity_locators.append(dict(cells))
        if row.field not in fields:
            fields.append(row.field)
        if row.unit and row.unit not in units:
            units.append(row.unit)
        condition = {k: str(v) for k, v in row.conditions.items()}
        condition_at = {k: loc for k, loc in row.condition_locators.items() if k in condition and loc}
        condition_key = (tuple(sorted(condition.items())), tuple(sorted(condition_at.items())))
        if condition and condition_key not in condition_keys:
            condition_keys.append(condition_key)
            conditions.append(condition)
            condition_locators.append(condition_at)
        low, high = row.interval if row.interval is not None else (None, None)
        values = dict(
            entity_ix=entity_keys.index(entity_key), field_ix=fields.index(row.field),
            unit_ix=units.index(row.unit) if row.unit else None,
            condition_ix=condition_keys.index(condition_key) if condition else None,
            time=row.time, time_unit=row.time_unit, time_actual=row.time_actual, value=row.value, verbatim=row.verbatim,
            censored=row.censored, lloq=row.lloq, lloq_unit=row.lloq_unit, uloq=row.uloq, statistic=row.statistic,
            spread=row.spread, spread_kind=row.spread_kind, n_at=row.n, interval_low=low, interval_high=high,
            interval_kind=row.interval_kind, interval_level=row.interval_level, locator=row.locator,
            time_locator=row.time_locator, time_actual_locator=row.time_actual_locator, unit_locator=row.unit_locator,
            spread_locator=row.spread_locator, n_locator=row.n_locator, lloq_locator=row.lloq_locator,
            interval_locator=row.interval_locators)
        for name, item in values.items():
            columns[name].append(item)
    return TableExtract(file_sha256=file_sha256, parser=context.parser, parser_version=context.parser_version,
                        region_id=region_id, mapping=mapping, kind=kind, decimal=decimal, entities=tuple(entities),
                        entity_locators=tuple(entity_locators), fields=tuple(fields), units=tuple(units),
                        conditions=tuple(conditions), condition_locators=tuple(condition_locators), n=len(rows),
                        **{name: tuple(items) for name, items in columns.items()})
