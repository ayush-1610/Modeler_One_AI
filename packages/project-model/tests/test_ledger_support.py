"""Hand-built inputs for the ledger's tests (contracts §8.6, §10): what D3's executor and its strict prose check give,
made by hand from the synthetic truth (`synthetic.truth_grid` gives every locator), so the ledger is tested on its own.

The builders follow the spec of each truth table as D3 executes it: a constant of a condition field goes into every
row's conditions and one of a label field (matrix) into every row's labels, each with its locator; every other
constant (the study id, the treatment, the analyte, the product, the batch, a dose, a food state, the table's LLOQ) is
listed in `constants`, which name the entities of every row; a row's own labels (subject, vessel, a product column)
refine them. A censored value carries the LLOQ its LLOQ cell states (a "<0.5" token's own number, else the table's
line). Shared by the test_ledger*.py files; the test below checks the builders against the truth.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import replace
from typing import Any

import pytest

from modeler_intake import synthetic
from modeler_intake.anchors import sha256_of
from modeler_intake.fields import field, read_choice
from modeler_intake.mapping_spec import ExtractedConstant, ExtractedRow, ExtractResult, MappingSpec, ProseFact
from modeler_intake.source_model import Region, RegionGrid
from modeler_intake.synthetic import PARSERS, TRUTH_PARSER_VERSION, SyntheticFile, TruthTable, truth_grid
from modeler_project.intake_fixtures import TRUTH_MODEL
from modeler_project.intake_records import FileRecord, MappingDecision, MappingEntry
from modeler_project.intake_store import IntakeStore
from modeler_project.ledger import ExtractionContext, Ledger, Recorded
from modeler_project.store import FileProjectStore
from modeler_project.workspace import Workspace

pytestmark = pytest.mark.req("T-47", "T-05", "F-404")

AT = "2026-11-12T10:00:00.000Z"
# a constant that names an entity of every row: field -> the label role it fills
NAMING = {"study_id": "study", "treatment": "arm", "analyte": "analyte", "product": "product", "batch": "batch"}


def make_ws(tmp_path) -> Workspace:
    """A project with a file root (the intake store is available)."""
    return Workspace(FileProjectStore(tmp_path), "t1", "p1")


def sha_of(file: SyntheticFile) -> str:
    return hashlib.sha256(file.data).hexdigest()


def file_record(sha: str, name: str, *, size: int = 1, delivery: str = "dl-1") -> FileRecord:
    return FileRecord(file_id=f"fl-{sha[:12]}", sha256=sha, name=name, size_bytes=size, delivery=delivery, by="code", at=AT)


def context(file: SyntheticFile, *, delivery: str = "dl-1", run_id: str | None = None,
            parser_version: str = TRUTH_PARSER_VERSION) -> ExtractionContext:
    sha = sha_of(file)
    return ExtractionContext(delivery=delivery, run_id=run_id, file=file_record(sha, file.name, size=len(file.data),
                                                                               delivery=delivery),
                             parser=PARSERS[file.format], parser_version=parser_version)


def mapping_entry(spec: MappingSpec, *, version: int = 1, first_seen: tuple[str, str] = ("0" * 64, "rg-0000000000"),
                  fingerprint: str | None = None) -> MappingEntry:
    """A mapping as the cache keeps it (no Constant.text); its id from the spec's hash, as write_truth makes it."""
    stored = spec.model_copy(update={"constants": tuple(c.model_copy(update={"text": None}) for c in spec.constants)})
    fingerprint = fingerprint or sha256_of(stored)
    return MappingEntry(mapping_id=f"mp-{fingerprint[:12]}", version=version, fingerprint=fingerprint, spec=stored,
                        origin="person", origin_detail="synthetic truth", first_seen=first_seen, by="code", at=AT)


def approve(ws: Workspace, entry: MappingEntry) -> None:
    """The mapping's entry and an `approved` decision in mappings.jsonl (as D3's cache would write them)."""
    store = IntakeStore(ws)
    store.mappings.append("entry", entry.model_dump(mode="json", by_alias=True))
    store.mappings.append("decision", MappingDecision(mapping_id=entry.mapping_id, version=entry.version, status="approved",
                                                      by="u", at=AT).model_dump(mode="json"))


def truth_table(file: SyntheticFile, table_id: str) -> TruthTable:
    (found,) = [t for t in file.tables if t.id == table_id]
    return found


def region_of(grid: RegionGrid, kind: str = "unknown", where: str = "s:'T'!A1:B2") -> Region:
    return Region(id=grid.region_id, kind="table", where=where, table_kind=kind, n_rows=grid.n_rows, n_cols=grid.n_cols)


def number(text: str) -> float | None:
    text = text.strip().replace("−", "-")
    if not text:
        return None
    if re.fullmatch(r"-?\d+,\d+", text):
        text = text.replace(",", ".")
    return float(text)


def _reading(text: str) -> tuple[float | None, bool, float | None, float | None]:
    """(value, censored, a token's LLOQ, uloq) of a value cell as written."""
    text = text.strip().rstrip("*†‡")
    if text.upper() == "BLQ":
        return None, True, None, None
    if text.startswith("<"):
        return None, True, number(text[1:]), None
    if text.startswith(">"):
        return None, False, None, number(text[1:])
    try:
        return number(text), False, None, None
    except ValueError:
        return None, False, None, None                      # a missing token ("NS")


def texts_of(grid: RegionGrid) -> dict[str, str]:
    """locator -> text of every cell of a grid and of its context lines."""
    cells = (*grid.cells.values(), *grid.caption, *(c for line in (*grid.above, *grid.below) for c in line))
    return {c.locator: c.text for c in cells}


def result_of(file: SyntheticFile, table_id: str, *, drop: tuple[str, ...] = ()) -> ExtractResult:
    """The ExtractResult D3's executor gives for one truth table (`drop`: constant fields left out, as a spec that does
    not read them)."""
    table = truth_table(file, table_id)
    grid = truth_grid(file, table_id)
    texts = texts_of(grid)
    body = {c.locator for c in grid.cells.values() if c.merged_from is None}
    constant_fields = {c.field for c in table.spec.constants} - set(drop)
    by_constant = {NAMING[f] for f in constant_fields if f in NAMING}
    values = [v for v in file.values if v.table == table_id]
    lloqs = {v.locator: v for v in values if v.field == "lloq"}
    rows, constants = [], []
    for v in values:
        at = dict(v.locators)
        found = field(v.field)
        assert found is not None, v.field
        numeric = found.value in ("number", "integer")
        if v.field in constant_fields or (v.field == "lloq" and v.locator not in body):   # a table's LLOQ line
            if v.field in drop:
                continue
            value = number(v.value) if numeric else (read_choice(v.field, v.value) or v.value) if found.value == "choice" \
                else v.value
            constants.append(ExtractedConstant(field=v.field, value=value, unit=v.unit or None, verbatim=texts[v.locator],
                                               locator=v.locator))
            continue
        if v.field in drop:
            continue
        labels: dict[str, str] = {}
        label_locators: dict[str, str] = {}
        for role, text in (("study", v.study), ("arm", v.arm), ("analyte", v.analyte), ("product", v.product),
                           ("batch", v.batch)):
            if text and role not in by_constant and NAMING_FIELD[role] not in drop:
                labels[role] = text
                if role in at:
                    label_locators[role] = at[role]
        for role, text in (("subject", v.subject), ("period", v.period), ("occasion", v.occasion), ("vessel", v.vessel),
                           ("matrix", v.matrix)):
            if text:
                labels[role] = text
                if role in at:
                    label_locators[role] = at[role]
        if "parameter" in at:
            label_locators["parameter"] = at["parameter"]
        common = dict(
            field=v.field, labels=labels, label_locators=label_locators, conditions=dict(v.conditions),
            condition_locators={name: at[name] for name, _v in v.conditions if name in at}, time=number(v.time),
            time_unit=v.time_unit or None, time_locator=at.get("time"), time_actual=number(v.time_actual),
            time_actual_locator=at.get("time_actual"), verbatim=texts[v.locator], locator=v.locator, unit=v.unit or None,
            unit_locator=at.get("unit"), statistic=v.statistic or None, spread=number(v.spread),
            spread_kind=v.spread_kind or None, spread_locator=at.get("spread"), n=int(v.n) if v.n else None,
            n_locator=at.get("n"))
        if numeric:
            value, censored, lloq, uloq = _reading(v.value)
            lloq_unit = (v.unit or None) if lloq is not None else None
            lloq_at = at.get("lloq")
            if censored and lloq is None and lloq_at in lloqs:
                lloq, lloq_unit = number(lloqs[lloq_at].value), lloqs[lloq_at].unit or None
            rows.append(ExtractedRow(**common, value=value, censored=censored, lloq=lloq, lloq_unit=lloq_unit,
                                     lloq_locator=lloq_at if lloq is not None else None, uloq=uloq))
        else:
            rows.append(ExtractedRow(**common, text_value=v.value))
    decimal = "comma" if any(re.fullmatch(r"-?\d+,\d+", t) for row in table.rows for t in row) else "point"
    return ExtractResult(rows=tuple(rows), constants=tuple(constants), cell_use=(), decimal=decimal, findings=())


NAMING_FIELD = {role: name for name, role in NAMING.items()}


def record_table(ledger: Ledger, file: SyntheticFile, table_id: str, *, approved: bool = True, version: int = 1,
                 delivery: str = "dl-1", run_id: str | None = None, drop: tuple[str, ...] = (),
                 parser_version: str = TRUTH_PARSER_VERSION) -> Recorded:
    """Record one truth table as the pipeline would: its grid, its region, its mapping (approved by default)."""
    table = truth_table(file, table_id)
    grid = truth_grid(file, table_id)
    if parser_version != TRUTH_PARSER_VERSION:
        grid = replace(grid, parser_version=parser_version)
    entry = mapping_entry(table.spec, version=version, first_seen=(sha_of(file), grid.region_id))
    if approved:
        approve(ledger.ws, entry)
    return ledger.record_extraction(region=region_of(grid, table.kind, table.where), grid=grid, mapping=entry,
                                    result=result_of(file, table_id, drop=drop),
                                    context=context(file, delivery=delivery, run_id=run_id, parser_version=parser_version))


def prose_of(file: SyntheticFile) -> list[ProseFact]:
    """The prose facts the strict check returns for a file's truth sentences (code's numbers, the spans)."""
    out = []
    for v in file.values:
        if v.table:
            continue
        found = field(v.field)
        assert found is not None
        value = number(v.value) if found.value in ("number", "integer") else (read_choice(v.field, v.value) or v.value)
        quote = next(p for p in file.prose if re.search(rf"(?<!\S){re.escape(v.value)}", p))
        out.append(ProseFact(field=v.field, value=value, unit=v.unit or None, quote=quote, study_label=v.study or None,
                             locator=v.locator, study_locator=dict(v.locators).get("study")))
    return out


def record_file(ledger: Ledger, file: SyntheticFile, **kwargs) -> list[Recorded]:
    """Every truth table of a file, then its prose (read by the scripted model)."""
    out = [record_table(ledger, file, table.id, **kwargs) for table in file.tables]
    facts = prose_of(file)
    if facts:
        out.append(ledger.record_prose(facts=facts, model=TRUTH_MODEL, context=context(file)))
    return out


def grid_from_rows(rows, *, sha: str, region_id: str = "rg-0000000001", caption: tuple[str, ...] = (),
                   below: tuple[tuple[str, ...], ...] = (), sheet: str = "T", first_cell: str | None = None,
                   parser: str = "workbook", parser_version: str = "1.0") -> RegionGrid:
    """A small sheet table for the tests that need a layout the truth has not (`RegionGrid.from_rows`), in file `sha`."""
    grid = RegionGrid.from_rows(rows, region_id=region_id, caption=caption, below=below, sheet=sheet, first_cell=first_cell)
    return replace(grid, file_sha256=sha, parser=parser, parser_version=parser_version)


def sheet_context(sha: str, *, name: str = "made-up.xlsx", delivery: str = "dl-1", run_id: str | None = None,
                  parser_version: str = "1.0") -> ExtractionContext:
    return ExtractionContext(delivery=delivery, run_id=run_id, file=file_record(sha, name, delivery=delivery),
                             parser="workbook", parser_version=parser_version)


def record_rows(ledger: Ledger, *, sheet: str, region: str, caption: str, rows: tuple[dict, ...] = (),
                constants: tuple[tuple[str, Any, str | None], ...] = (), field: str = "concentration", sha: str = "a" * 64,
                kind: str = "pk_summary", version: int = 1) -> Recorded:
    """A small table the truth has not: a caption (every constant is read from it: (field, value, unit)), and one row
    per given value (`time`, `time_unit`, `value`, `unit`, `field`, `labels`, `conditions`, `statistic`, `spread`,
    `spread_kind`, `n`), each time, label, condition, spread and n in a cell of its own row."""
    names = sorted({name for row in rows for name in (*row.get("labels", {}), *row.get("conditions", {}))})
    qualifiers = [q for q in ("spread", "n") if any(q in row for row in rows)]
    header = ["Time", "Value", *names, *qualifiers]
    body = [[row.get("time", ""), row["value"], *({**row.get("labels", {}), **row.get("conditions", {})}.get(n, "")
                                                  for n in names), *(row.get(q, "") for q in qualifiers)] for row in rows]
    grid = grid_from_rows([header, *body], sha=sha, sheet=sheet, region_id=region, caption=(caption,))
    cap = grid.caption[0]
    out = []
    for r, row in enumerate(rows, start=2):
        labels, conditions = dict(row.get("labels", {})), dict(row.get("conditions", {}))
        at = {n: grid.cell(r, 3 + i).locator for i, n in enumerate([*names, *qualifiers])}
        timed = row.get("time") is not None
        out.append(ExtractedRow(
            field=row.get("field", field), labels=labels, label_locators={k: at[k] for k in labels},
            conditions=conditions, condition_locators={k: at[k] for k in conditions}, time=row.get("time"),
            time_unit=row.get("time_unit", "h") if timed else None, time_locator=grid.cell(r, 1).locator if timed else None,
            value=row["value"], verbatim=str(row["value"]), locator=grid.cell(r, 2).locator, unit=row.get("unit", "ng/mL"),
            statistic=row.get("statistic", "arithmetic_mean"), spread=row.get("spread"), spread_kind=row.get("spread_kind"),
            spread_locator=at["spread"] if "spread" in row else None, n=row.get("n"),
            n_locator=at["n"] if "n" in row else None))
    result = ExtractResult(rows=tuple(out), cell_use=(), findings=(), constants=tuple(
        ExtractedConstant(field=name, value=value, unit=unit, verbatim=cap.text, locator=cap.locator)
        for name, value, unit in constants))
    spec = MappingSpec(kind=kind, layout="long", header_rows=1, first_data_row=2)
    return ledger.record_extraction(region=region_of(grid), grid=grid, mapping=mapping_entry(spec, version=version),
                                    result=result, context=sheet_context(sha))


def test_the_hand_built_results_follow_the_truth():
    """Every truth value of every table of the delivery is a row or a constant, with its truth locator; every row
    carries the locators of its truth value."""
    for file in synthetic.delivery():
        for table in file.tables:
            result = result_of(file, table.id)
            truth = [v for v in file.values if v.table == table.id]
            given = {r.locator for r in result.rows} | {c.locator for c in result.constants}
            assert {v.locator for v in truth} == given, table.id
            assert len(result.rows) + len(result.constants) == len(truth), table.id
            for row in result.rows:
                (value,) = [v for v in truth if v.locator == row.locator and v.field == row.field]
                at = dict(value.locators)
                assert row.time_locator == at.get("time") and row.unit_locator == at.get("unit"), value
        assert len(prose_of(file)) == len([v for v in file.values if not v.table])
