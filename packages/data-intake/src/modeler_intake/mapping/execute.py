"""A mapping spec executed by code over one region's grid (contracts §6.2): every value read, every cell accounted for.

The same executor serves a sheet range, a PDF table and a Word table: every coordinate of the spec is relative to the
region, every constant and unit is re-read from the region's own cells and context lines, and every number is read by
`parse_cell` under the region's decimal convention (decided by code, never the model's).

**The count, one sentence for D3 and D5:** every cell of a mapped region that holds a number (`has_number`; a merged
copy is not counted, its origin is) ends as value, time, spread, n, lloq, interval, label, condition, header, constant,
unit, missing or excluded (by a row rule, an ignored column with its reason, or a token); otherwise it is
`unaccounted`, and every unaccounted cell is silent loss. An unparseable value cell is a finding `UNPARSEABLE_VALUE`
and `unaccounted`; a non-numeric spread or n is a finding, never an exception.

What a row of the region gives:
- a value column of a number field: one `ExtractedRow` per non-empty cell (a missing token gives a row with no value,
  its cell `missing`); a value column of a choice, name or text field: a row with `text_value` (D4 writes it as a fact);
- the labels of its row (label columns, the column's series label, the table's label and naming constants), its time
  and actual time, its statistic, spread, n, interval, LLOQ and unit, each with the locator of the cell it is read from;
- time, actual time, conditions, statistic, spread, n, interval and the sample labels (period, sequence, occasion,
  vessel) qualify a measured value only (a field of level observation or compound): a product's strength or a study's
  n on the same row takes the row's study, arm, product, batch, analyte and matrix, not its time.
Constants: a condition constant goes into every measured row's conditions, a label constant (matrix ...) into every
row's labels, a naming constant (study_id, treatment, analyte, product, batch) into `constants` and every row's labels;
every other constant, and the table's LLOQ, into `constants` (D4 writes them as scalar facts). A constant's number is
read under the region's decimal convention, as a cell's is.

Never overwritten, never assumed:
- a value takes one spread, one n and one interval: a second (another SD row, a CV% column) is a finding
  `QUALIFIER_TWICE` and its cell stays `unaccounted`, never written over the first;
- a qualifier row (SD, N, CI rows) qualifies the statistic row of its own time, labels and conditions (the nearest
  above, else below); with none, `QUALIFIER_WITHOUT_VALUE` and its cells stay `unaccounted`;
- a unit a cell writes itself is the most specific: a time cell's "15 min" is minutes whatever the column or the
  table says (`TIME_UNIT_CONFLICT` when they differ), a value cell's "45 %" is percent (`UNIT_CONFLICT`);
- an LLOQ column's number qualifies its row's value, censored or not, with the LLOQ column's own unit (its typed and
  cited unit, else the unit its header writes, else a table-wide value unit), never the value column's own unit.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from modeler_intake import fields
from modeler_intake.mapping.fingerprint import header_band
from modeler_intake.mapping.reading import (
    MARKERS,
    ParsedCell,
    Reading,
    cite_cells,
    decimal_convention,
    is_context,
    match_text,
    nfkc,
    parse_cell,
    read_cited,
    read_constant,
    read_level,
    read_spread_kind,
    read_statistic,
    read_text_constant,
    read_time,
    same_unit,
    split_cell,
    unit_at,
    unit_of_cell,
    writes_decimal,
)
from modeler_intake.mapping.validate import LABEL_ROLES, ROW_WIDE, unit_field, validate_spec, value_field
from modeler_intake.mapping_spec import (
    CellUse,
    ColumnMap,
    Constant,
    ExtractedConstant,
    ExtractedRow,
    ExtractResult,
    KeyMap,
    MappingError,
    MappingSpec,
    RowRule,
)
from modeler_intake.source_model import Finding, GridCell, RegionGrid, has_number

__all__ = ["ParsedCell", "decimal_convention", "execute", "parse_cell", "read_constant", "read_text_constant", "split_cell"]

# the naming constants: listed as constants (D4's scalar facts) and written on every row as the label of their role
NAMING = {"study_id": "study", "treatment": "arm", "analyte": "analyte", "product": "product", "batch": "batch"}
MEASURED = frozenset({"observation", "compound"})
SAMPLE_LABELS = frozenset({"period", "sequence", "occasion", "vessel"})     # a sample's labels: measured values only
STATISTIC_RULES = frozenset({"arithmetic_mean", "geometric_mean", "median"})
QUALIFIER_RULES = frozenset({"spread", "n", "interval_low", "interval_high"})
_YES = frozenset({"yes", "y", "true", "1", "x", "blq"})
_NO = frozenset({"no", "n", "false", "0", ""})


def execute(spec: MappingSpec, grid: RegionGrid) -> ExtractResult:
    """The spec executed over the grid: its rows, its constants and the use of every non-empty cell. MappingError when
    `validate_spec` has an error-severity finding; otherwise never raises (a problem with a cell is a finding)."""
    findings = validate_spec(spec, grid)
    errors = [f for f in findings if f.severity == "error"]
    if errors:
        raise MappingError("; ".join(f"{f.code} {f.location}: {f.message}" for f in errors))
    return _Run(spec, grid, findings).result()


def _interval_kind(texts: Sequence[str]) -> tuple[str | None, float | None]:
    """An interval's kind and level from the words around it: a CI (with its level when one is written), a min-max
    range, or None (not stated: INTERVAL_KIND_UNSTATED)."""
    joined = " ".join(texts)
    if re.search(r"\bci\b|confidence", joined, re.IGNORECASE):
        return "CI", read_level(joined)
    if re.search(r"\bmin\w*\b|\bmax\w*\b|\brange\b", joined, re.IGNORECASE):
        return "range", None
    return None, None


@dataclass
class _Value:
    """One value being read: the ExtractedRow's fields, filled in by the row, its qualifiers and its qualifier rows."""

    row: int
    column: int
    measured: bool
    data: dict[str, Any] = field(default_factory=dict)


class _Run:
    def __init__(self, spec: MappingSpec, grid: RegionGrid, findings: Sequence[Finding]):
        self.spec, self.grid = spec, grid
        self.findings: list[Finding] = list(findings)
        self.decimal = decimal_convention(grid)
        self.uses: dict[tuple[int, int], CellUse] = {}
        self.cited: list[str] = []
        self.values_by_cell: dict[tuple[int, int], _Value] = {}
        self.value_columns = [c for c in spec.columns if c.role == "value"]
        self.last = min(spec.last_data_row or grid.n_rows, grid.n_rows)
        self.data_rows = range(spec.first_data_row, self.last + 1)
        self.decimal_rows = {c: frozenset(r for r in self.data_rows if (x := grid.cell(r, c)).text and x.merged_from is None
                                          and writes_decimal(x.text, self.decimal)) for c in range(1, grid.n_cols + 1)}
        self.noted: set[str] = set()
        self.at = {c.locator: pos for pos, c in grid.cells.items()}
        self.filled_rows = frozenset(r for (r, _c) in grid.cells)

    # --- bookkeeping -------------------------------------------------------------------------------------------------

    def find(self, code: str, location: str, message: str, severity: str = "error", once: str = "") -> None:
        if once:
            if once in self.noted:
                return
            self.noted.add(once)
        self.findings.append(Finding(code=code, location=location, message=message, severity=severity))  # type: ignore[arg-type]

    def use(self, row: int, column: int, use: str, rule: str = "", *, force: bool = False) -> None:
        cell = self.grid.cell(row, column)
        if not cell.locator or ((row, column) in self.uses and not force):
            return
        numeric = cell.merged_from is None and has_number(cell.text)
        self.uses[(row, column)] = CellUse(row=row, column=column, locator=cell.locator, numeric=numeric, use=use,  # type: ignore[arg-type]
                                           rule=rule)

    def cite(self, cell: GridCell) -> None:
        if is_context(self.grid, cell) and cell.locator not in self.cited:
            self.cited.append(cell.locator)

    def has_decimal(self, row: int, column: int) -> bool:
        return bool(self.decimal_rows.get(column, frozenset()) - {row})

    def parse(self, cell: GridCell, row: int, column: int, *, tokens: bool = True) -> ParsedCell:
        return parse_cell(cell, decimal=self.decimal, column_has_decimal=self.has_decimal(row, column),
                          below_lloq_tokens=self.spec.below_lloq_tokens if tokens else (),
                          missing_tokens=self.spec.missing_tokens if tokens else ())

    def qualifiers(self, role: str, column: ColumnMap) -> list[ColumnMap]:
        """The columns of `role` that qualify a value column: `of` it, or any (of None) when it is the only value column
        or the role stands for the whole row (unit, blq_flag, spread_kind)."""
        single = len(self.value_columns) == 1
        return [c for c in self.spec.columns if c.role == role and (c.of == column.column or (
            c.of is None and (single or role in ROW_WIDE)))]

    # --- what the spec states once ------------------------------------------------------------------------------------

    def read_constants(self) -> None:
        self.constants: list[ExtractedConstant] = []
        self.label_constants: dict[str, tuple[str, str]] = {}
        self.condition_constants: dict[str, tuple[str, str]] = {}
        for constant in self.spec.constants:
            reading = self.read_one(constant)
            if reading is None:
                continue
            locator = reading.cell.locator
            if constant.field in fields.CONDITION_FIELDS:
                self.condition_constants[constant.field] = (reading.written if isinstance(reading.value, float)
                                                            else str(reading.value), locator)
            elif constant.field in fields.LABEL_FIELDS:
                self.label_constants[constant.field] = (str(reading.value), locator)
            else:
                self.constants.append(ExtractedConstant(field=constant.field, value=reading.value, unit=reading.unit,
                                                        verbatim=reading.cell.text, locator=locator))
                if constant.field in NAMING:
                    self.label_constants[NAMING[constant.field]] = (str(reading.value), locator)
        self.table_lloq = None
        if self.spec.lloq is not None:
            reading = self.read_one(Constant(field="lloq", cite=self.spec.lloq))
            if reading is not None:
                self.table_lloq = (float(reading.value), reading.unit, reading.cell.locator)
                self.constants.append(ExtractedConstant(field="lloq", value=reading.value, unit=reading.unit,
                                                        verbatim=reading.cell.text, locator=reading.cell.locator))
        self.column_lloq: dict[int, tuple[float, str | None, str]] = {}
        self.column_level: dict[int, tuple[float | None, str]] = {}
        for column in self.spec.columns:
            if column.lloq is not None:
                reading = self.read_one(Constant(field="lloq", cite=column.lloq))
                if reading is not None:
                    self.column_lloq[column.column] = (float(reading.value), reading.unit, reading.cell.locator)
            if column.level is not None:
                for cell in cite_cells(self.grid, column.level):
                    level = read_level(cell.text, decimal=self.decimal)
                    if level is not None:
                        self.column_level[column.column] = (level, cell.locator)
                        self.mark_cited(cell, "constant")
                        break

    def read_one(self, constant: Constant) -> Reading | None:
        readings = read_cited(constant, cite_cells(self.grid, constant.cite), decimal=self.decimal)
        if len(readings) != 1 or readings[0].value is None:
            return None                                       # validate_spec refused it already
        self.mark_cited(readings[0].cell, "constant")
        return readings[0]

    def mark_cited(self, cell: GridCell, use: str) -> None:
        """A cited cell: a context line's leaves the outside count; a region cell of a data row is put to its use."""
        self.cite(cell)
        position = self.at.get(cell.locator)
        if position is not None and position[0] in self.data_rows:
            self.use(position[0], position[1], use)

    def read_units(self) -> None:
        band = max(self.spec.header_rows, header_band(self.grid))
        self.band_cells = [c for (r, _c), c in sorted(self.grid.cells.items()) if r <= band]
        self.spec_unit = None
        unit_class_field = unit_field(self.spec)
        self.spec_unit_class = fields.unit_class(unit_class_field) if unit_class_field else None
        if self.spec.value_unit is not None and unit_class_field is not None:
            self.spec_unit = self.typed_unit(unit_class_field, self.spec.value_unit, self.spec.value_unit_cite)
        self.spec_time_unit = None
        if self.spec.time_unit is not None:
            self.spec_time_unit = self.typed_unit("time", self.spec.time_unit, self.spec.time_unit_cite)
        self.column_unit: dict[int, tuple[str, str] | None] = {}
        for column in self.spec.columns:
            if column.unit is None:
                continue
            if column.role in ("time", "time_actual"):
                self.column_unit[column.column] = self.typed_unit("time", column.unit, column.unit_cite)
            elif column.role == "value":
                name = value_field(self.spec, column) or unit_class_field
                if name is not None:
                    self.column_unit[column.column] = self.typed_unit(name, column.unit, column.unit_cite)
            elif column.role == "lloq":
                self.column_unit[column.column] = self.typed_unit("lloq", column.unit, column.unit_cite)

    def typed_unit(self, name: str, typed: str, cite) -> tuple[str, str] | None:
        """A typed unit as code finds it written at its cite (no cite: in the header band): (as written, locator)."""
        cells = cite_cells(self.grid, cite) if cite is not None else self.band_cells
        found = unit_at(name, typed, cells)
        if found is None:
            return None
        written, cell = found
        self.mark_cited(cell, "unit")
        return written, cell.locator

    # --- the header, the time row and the series --------------------------------------------------------------------

    def header(self) -> None:
        values = {c.column for c in self.value_columns}
        time_row = self.spec.time_row
        for (row, column), cell in self.grid.cells.items():
            if row >= self.spec.first_data_row:
                continue
            if row == time_row and column in values:
                continue                                          # read below, with the times
            if row <= self.spec.header_rows:
                self.use(row, column, "header", "merged_copy" if cell.merged_from else "")
        self.row_times: dict[int, tuple[float | None, str | None, str | None]] = {}
        if time_row is None:
            return
        for column in self.value_columns:
            cell = self.grid.cell(time_row, column.column)
            if not cell.locator:
                self.row_times[column.column] = (None, None, None)
                continue
            if cell.merged_from is not None:
                cell = GridCell(text=cell.text, value=cell.value, type=cell.type, locator=cell.merged_from)
            time, unit, problem = read_time(cell, self.decimal, self.has_decimal(time_row, column.column))
            if problem:
                self.find("UNPARSEABLE_TIME", cell.locator, problem)
                self.use(time_row, column.column, "unaccounted", "unparseable")
                self.row_times[column.column] = (None, None, "problem")
                continue
            self.use(time_row, column.column, "time")
            self.row_times[column.column] = (time, unit, cell.locator)

    def series(self, column: ColumnMap) -> tuple[str, str] | None:
        if column.series is None:
            return None
        cells = cite_cells(self.grid, column.series)
        if not cells or not cells[0].text.strip():
            return None
        return cells[0].text.strip(), cells[0].locator

    def key_of(self, text: str) -> KeyMap | None:
        stripped = nfkc(text).strip()
        return next((key for key in self.spec.keys if match_text(key.pattern, stripped)), None)

    # --- the rows ------------------------------------------------------------------------------------------------------

    def rule_of(self, row: int) -> RowRule | None:
        for rule in self.spec.row_rules:
            cell = self.grid.cell(row, rule.column)
            if cell.text.strip() and match_text(rule.pattern, nfkc(cell.text).strip()):
                return rule
        return None

    def rows(self) -> None:
        self.row_keys: dict[int, tuple[float | None, dict[str, str], dict[str, str]]] = {}
        statistic_rows: list[int] = []
        qualifier_rows: list[tuple[int, RowRule]] = []
        key_qualifiers: list[tuple[int, KeyMap]] = []
        for row in self.data_rows:
            if row not in self.filled_rows:
                continue
            rule = self.rule_of(row)
            if rule is not None and rule.role == "exclude":
                for (r, c) in self.grid.cells:
                    if r == row:
                        self.use(r, c, "excluded", f"row_rule:{rule.pattern}")
                continue
            if rule is not None:
                self.use(row, rule.column, "label", f"row_rule:{rule.pattern}")
            if rule is not None and rule.role in QUALIFIER_RULES:
                qualifier_rows.append((row, rule))
                continue
            key = None
            if self.spec.layout == "key_value":
                parameter = next((c for c in self.spec.columns if c.role == "parameter"), None)
                text = self.grid.cell(row, parameter.column).text if parameter is not None else ""
                key = self.key_of(text) if text.strip() else None
                if key is None:
                    self.find("UNMAPPED_KEY", f"row {row}", f"no key maps the row label {text.strip()!r}: its values "
                                                            "are not read", "warn")
                    continue
                if key.spread_kind is not None and key.statistic is None and self.is_key_qualifier(key):
                    key_qualifiers.append((row, key))
                    self.labels(row, None, statistic_row=True)
                    continue
            if rule is not None:
                statistic_rows.append(row)
            self.read_row(row, rule, key)
        for row, rule in qualifier_rows:
            self.qualifier_row(row, rule, statistic_rows)
        for row, key in key_qualifiers:
            self.key_qualifier_row(row, key)

    def is_key_qualifier(self, key: KeyMap) -> bool:
        """A key that names a spread of another key's values (the same field, a spread kind and no statistic)."""
        return any(k is not key and k.field == key.field and k.spread_kind is None for k in self.spec.keys)

    def labels(self, row: int, skip: int | None, *, statistic_row: bool) -> dict[str, tuple[str, str]]:
        found: dict[str, tuple[str, str]] = {}
        for column in self.spec.columns:
            if column.role not in LABEL_ROLES or column.column == skip:
                continue
            cell = self.grid.cell(row, column.column)
            if not cell.text.strip():
                continue
            self.use(row, column.column, "label")
            if statistic_row and column.role == "subject":
                continue                                             # a mean is no subject's
            found[column.role] = (cell.text.strip(), cell.merged_from or cell.locator)
        return found

    def conditions(self, row: int) -> dict[str, tuple[str, str]]:
        found: dict[str, tuple[str, str]] = {}
        for column in self.spec.columns:
            if column.role != "condition" or column.condition is None:
                continue
            cell = self.grid.cell(row, column.column)
            if cell.text.strip():
                self.use(row, column.column, "condition")
                found[column.condition] = (cell.text.strip(), cell.merged_from or cell.locator)
        return found

    def row_cell(self, row: int, role: str) -> tuple[GridCell, ColumnMap] | None:
        column = next((c for c in self.spec.columns if c.role == role), None)
        if column is None:
            return None
        cell = self.grid.cell(row, column.column)
        return (cell, column) if cell.text.strip() else None

    def read_row(self, row: int, rule: RowRule | None, key: KeyMap | None) -> None:
        statistic_row = rule is not None
        labels = self.labels(row, rule.column if rule else None, statistic_row=statistic_row)
        conditions = self.conditions(row)
        time, time_problem = self.time_of(row)
        actual = self.actual_time_of(row)
        statistic_text = self.row_cell(row, "statistic")
        row_statistic = None
        if statistic_text is not None:
            self.use(row, statistic_text[1].column, "label")
            row_statistic = read_statistic(statistic_text[0].text)
            if row_statistic is None:
                self.find("STATISTIC_NOT_READ", statistic_text[0].locator, f"{statistic_text[0].text.strip()!r} names no "
                                                                           "statistic code reads", "warn")
        spread_kind_cell = self.row_cell(row, "spread_kind")
        row_spread_kind = None
        if spread_kind_cell is not None:
            self.use(row, spread_kind_cell[1].column, "label")
            row_spread_kind = read_spread_kind(spread_kind_cell[0].text)
            if row_spread_kind is None:
                self.find("SPREAD_KIND_NOT_READ", spread_kind_cell[0].locator,
                          f"{spread_kind_cell[0].text.strip()!r} names no spread kind code reads", "warn")
        if rule is not None:
            self.row_keys[row] = (time[0] if time else None, {k: v[0] for k, v in labels.items()},
                                  {k: v[0] for k, v in conditions.items()})
        for column in self.value_columns:
            self.read_value(row, column, labels=labels, conditions=conditions, time=time, time_problem=time_problem,
                            actual=actual, rule=rule, key=key, row_statistic=row_statistic, row_spread_kind=row_spread_kind)

    def time_of(self, row: int) -> tuple[tuple[float | None, str | None, str | None] | None, bool]:
        """The nominal time of a row (long and wide_series: its time column): ((time, unit, locator) or None, problem)."""
        if self.spec.time_row is not None:
            return None, False
        found = self.row_cell(row, "time")
        if found is None:
            return None, False
        cell, column = found
        if cell.merged_from is not None:
            cell = GridCell(text=cell.text, value=cell.value, type=cell.type, locator=cell.merged_from)
        time, unit, problem = read_time(cell, self.decimal, self.has_decimal(row, column.column))
        if problem:
            self.find("UNPARSEABLE_TIME", cell.locator, problem)
            self.use(row, column.column, "unaccounted", "unparseable")
            return None, True
        self.use(row, column.column, "time")
        own = self.column_unit.get(column.column)
        return (time, own[0] if own else None, unit, cell.locator), False

    def actual_time_of(self, row: int) -> tuple[float, str, str | None, int] | None:
        """The actual time of a row: (time, locator, the unit its cell writes, its column), or None."""
        found = self.row_cell(row, "time_actual")
        if found is None:
            return None
        cell, column = found
        time, unit, problem = read_time(cell, self.decimal, self.has_decimal(row, column.column))
        if problem:
            self.find("UNPARSEABLE_TIME", cell.locator, problem)
            self.use(row, column.column, "unaccounted", "unparseable")
            return None
        self.use(row, column.column, "time")
        own = self.column_unit.get(column.column)
        return time, cell.locator, unit or (own[0] if own else None), column.column  # type: ignore[return-value]

    def time_unit_of(self, row: int, own: str | None, written_in_cell: str | None, locator: str | None) -> str | None:
        """A time's unit as written. The unit the time cell writes itself ("15 min") is the most specific and wins;
        else the row's time-unit cell, the time column's own unit, the table's. When the cell's own unit differs from
        another the table states, TIME_UNIT_CONFLICT (warn): the cell's is kept, never replaced."""
        others: list[str] = []
        found = self.row_cell(row, "time_unit")
        if found is not None:
            self.use(row, found[1].column, "unit")
            written = unit_of_cell("time", found[0].text)
            if written is not None:
                others.append(written)
        if own is not None:
            others.append(own)
        if self.spec_time_unit is not None:
            others.append(self.spec_time_unit[0])
        if written_in_cell is None:
            return others[0] if others else None
        differing = [u for u in others if not same_unit("time", written_in_cell, u)]
        if differing:
            self.find("TIME_UNIT_CONFLICT", locator or f"row {row}", f"the time cell writes {written_in_cell!r} and the "
                                                                     f"table states {differing[0]!r}: the cell's unit is "
                                                                     "kept", "warn")
        return written_in_cell

    def read_value(self, row: int, column: ColumnMap, *, labels: dict[str, tuple[str, str]],
                   conditions: dict[str, tuple[str, str]], time, time_problem: bool, actual, rule: RowRule | None,
                   key: KeyMap | None, row_statistic: str | None, row_spread_kind: str | None) -> None:
        cell = self.grid.cell(row, column.column)
        if not cell.text.strip():
            return
        if cell.merged_from is not None:
            self.use(row, column.column, "excluded", "merged_copy")
            return
        series = self.series(column)
        if key is not None:
            name = key.field
        elif column.series_role == "parameter":
            found = self.key_of(series[0]) if series else None
            if found is None:
                self.find("UNMAPPED_KEY", cell.locator, "no key maps this column's header: its values are not read", "warn",
                          once=f"series-key:{column.column}")
                self.use(row, column.column, "unaccounted")
                return
            key, name = found, found.field
        else:
            name = value_field(self.spec, column)
        definition = fields.field(name) if name else None
        if definition is None:
            self.use(row, column.column, "unaccounted")
            return
        measured = definition.level in MEASURED
        if measured and time_problem:
            self.use(row, column.column, "unaccounted", "time_unparseable")
            return
        value = _Value(row=row, column=column.column, measured=measured)
        data = value.data
        data.update(field=name, verbatim=cell.text, locator=cell.locator)
        merged_labels = dict(self.label_constants)
        merged_labels.update(labels)
        if series is not None and column.series_role in LABEL_ROLES:
            merged_labels[column.series_role] = series
        if column.series is not None and column.series.row is not None:
            self.use(column.series.row, column.series.column, "header")
        row_conditions = dict(self.condition_constants)
        row_conditions.update(conditions)
        if series is not None and column.series_role == "condition" and column.condition:
            row_conditions[column.condition] = series
        if not measured:
            merged_labels = {k: v for k, v in merged_labels.items() if k not in SAMPLE_LABELS}
            row_conditions = {}
        data["labels"] = {k: v[0] for k, v in merged_labels.items()}
        data["label_locators"] = {k: v[1] for k, v in merged_labels.items()}
        data["conditions"] = {k: v[0] for k, v in row_conditions.items()}
        data["condition_locators"] = {k: v[1] for k, v in row_conditions.items()}
        if definition.value in ("number", "integer"):
            if not self.read_number_value(value, cell, column, definition.value):
                return
        else:
            text = cell.text.strip()
            choice = fields.read_choice(name, text) if definition.value == "choice" else text
            if choice is None:
                self.find("CHOICE_NOT_READ", cell.locator, f"{text!r} states no {name} code reads; kept as written", "warn")
            data["text_value"] = choice or text
            self.use(row, column.column, "value")
        if measured:
            self.qualify(value, column, time=time, actual=actual, rule=rule, key=key, row_statistic=row_statistic,
                         row_spread_kind=row_spread_kind, has_subject="subject" in merged_labels)
        if data.get("censored") and data.get("lloq") is None:
            self.stated_lloq(value, column)
        self.values_by_cell[(row, column.column)] = value

    def read_number_value(self, value: _Value, cell: GridCell, column: ColumnMap, kind: str) -> bool:
        row, data = value.row, value.data
        parts = split_cell(cell.text, column.cell_form) if column.cell_form != "value" else (cell.text, None, None)
        main = cell if column.cell_form == "value" else GridCell(text=parts[0], value=parts[0], type="text",
                                                                 locator=cell.locator)
        parsed = self.parse(main, row, column.column)
        if parsed.problem:
            self.find("UNPARSEABLE_VALUE", cell.locator, parsed.problem)
            self.use(row, column.column, "unaccounted", "unparseable")
            return False
        if parsed.missing:
            self.use(row, column.column, "missing", f"missing_token:{nfkc(cell.text).strip()}")
        else:
            self.use(row, column.column, "value")
        if parsed.marker:
            self.find("MARKED_VALUE", cell.locator, f"the value carries the mark {parsed.marker!r} (a footnote)", "info")
        number = parsed.value
        if kind == "integer" and number is not None and not number.is_integer():
            self.find("NOT_AN_INTEGER", cell.locator, f"{data['field']} is a whole number; the cell writes {cell.text!r}",
                      "warn")
        data.update(value=number, censored=parsed.censored, uloq=parsed.uloq)
        self.read_unit(value, cell, column, parts)
        if parsed.censored and parsed.lloq is not None:
            data.update(lloq=parsed.lloq, lloq_unit=data.get("unit"), lloq_locator=cell.locator)   # "<0.5": its own
        if column.cell_form in ("value (spread)", "value ± spread") and parts[1] is not None:
            spread = self.parse(GridCell(text=parts[1], value=parts[1], type="text", locator=cell.locator), row,
                                column.column, tokens=False)
            if spread.value is None:
                self.find("UNPARSEABLE_SPREAD", cell.locator, f"the spread {parts[1]!r} is no number code reads: the value "
                                                              "is kept, its spread is not", "warn")
                self.use(row, column.column, "value", "spread_unparsed", force=True)
            else:
                data.update(spread=spread.value, spread_kind=column.spread_kind, spread_verbatim=parts[1],
                            spread_locator=cell.locator)
        if column.cell_form == "value (low-high)" and parts[1] is not None and parts[2] is not None:
            low = self.parse(GridCell(text=parts[1], value=parts[1], type="text", locator=cell.locator), row,
                             column.column, tokens=False)
            high = self.parse(GridCell(text=parts[2], value=parts[2], type="text", locator=cell.locator), row,
                              column.column, tokens=False)
            if low.value is None or high.value is None:
                self.find("UNPARSEABLE_INTERVAL", cell.locator, f"the interval {parts[1]!r}-{parts[2]!r} is not two numbers: "
                                                                "the value is kept, its interval is not", "warn")
                self.use(row, column.column, "value", "interval_unparsed", force=True)
            else:
                self.set_interval(value, (low.value, high.value), (cell.locator, cell.locator), column, [column])
        return True

    def read_unit(self, value: _Value, cell: GridCell, column: ColumnMap, parts: tuple[str, str | None, str | None]) -> None:
        row, data = value.row, value.data
        name = data["field"]
        if cell.number_format.strip().endswith("%") and isinstance(cell.value, int | float) and not isinstance(cell.value, bool):
            data.update(unit="%", unit_locator=cell.locator)
            self.find("PERCENT_FORMAT", cell.locator, "the cell's number format is a percentage: read times 100, unit %",
                      "info", once=f"percent:{column.column}")
            return
        if column.cell_form == "value unit" and parts[2] is not None:
            data.update(unit=unit_of_cell(name, parts[2]), unit_locator=cell.locator)
            return
        stated: tuple[str, str] | None = None
        for unit_column in self.qualifiers("unit", column):
            found = self.grid.cell(row, unit_column.column)
            if found.text.strip():
                self.use(row, unit_column.column, "unit")
                stated = (unit_of_cell(name, found.text), found.merged_from or found.locator)  # type: ignore[assignment]
                break
        if stated is None and column.column in self.column_unit and self.column_unit[column.column] is not None:
            stated = self.column_unit[column.column]
        if stated is None and self.spec_unit is not None and fields.unit_class(name) == self.spec_unit_class:
            stated = self.spec_unit
        if isinstance(cell.value, str) and re.search(rf"%\s*[{MARKERS}]*$", nfkc(cell.text).strip()):
            if stated is not None and stated[0] and not same_unit(name, "%", stated[0]):
                self.find("UNIT_CONFLICT", cell.locator, f"the cell writes '%' and the table states {stated[0]!r}: the "
                                                         "cell's unit is kept", "warn")
            data.update(unit="%", unit_locator=cell.locator)                 # the unit the cell writes itself
            return
        if stated is not None:
            data.update(unit=stated[0], unit_locator=stated[1])

    def stated_lloq(self, value: _Value, column: ColumnMap) -> None:
        """A censored value's LLOQ when neither its cell ("<0.5") nor its row's LLOQ column states one: the LLOQ cited
        for its column, else the table's."""
        data = value.data
        if column.column in self.column_lloq:
            number, unit, locator = self.column_lloq[column.column]
            data.update(lloq=number, lloq_unit=unit, lloq_locator=locator)
        elif self.table_lloq is not None:
            number, unit, locator = self.table_lloq
            data.update(lloq=number, lloq_unit=unit, lloq_locator=locator)

    def lloq_unit(self, lloq_column: ColumnMap) -> str | None:
        """The unit of an LLOQ column's numbers: its own typed and cited unit, else the one unit its header writes, else
        a value unit stated for the whole table (a context line, or the header band with no cite); never the value
        column's own unit, which is written for that column only."""
        own = self.column_unit.get(lloq_column.column)
        if own is not None:
            return own[0]
        for row in range(1, self.spec.first_data_row):
            header = self.grid.cell(row, lloq_column.column)
            found = fields.units_in("lloq", nfkc(header.text)) if header.text.strip() else ()
            if len(found) == 1:
                self.mark_cited(header, "unit")
                return found[0]
        if self.spec_unit is not None and self.spec_unit_class == "concentration" and (
                self.spec.value_unit_cite is None or self.spec.value_unit_cite.near is not None):
            return self.spec_unit[0]
        return None

    def twice(self, cell: GridCell, row: int, column: int, what: str) -> None:
        """A second spread, n or interval for one value: a finding, and the cell stays unaccounted (never written over
        the first)."""
        self.find("QUALIFIER_TWICE", cell.locator, f"a second {what} for one value: the first is kept, this one is not "
                                                   "read (exclude one with a reason)", "warn")
        self.use(row, column, "unaccounted", "qualifier_twice", force=True)

    def qualify(self, value: _Value, column: ColumnMap, *, time, actual, rule: RowRule | None, key: KeyMap | None,
                row_statistic: str | None, row_spread_kind: str | None, has_subject: bool) -> None:
        """A measured value's time, actual time, statistic, spread, n, interval, BLQ flag and LLOQ column."""
        row, data = value.row, value.data
        if self.spec.time_row is not None:
            found = self.row_times.get(column.column)
            if found is not None and found[0] is not None:
                data.update(time=found[0], time_unit=self.time_unit_of(row, None, found[1], found[2]), time_locator=found[2])
        elif time is not None:
            data.update(time=time[0], time_unit=self.time_unit_of(row, time[1], time[2], time[3]), time_locator=time[3])
        if actual is not None:
            unit = data.get("time_unit")
            if actual[2] is not None and unit is not None and not same_unit("time", actual[2], unit):
                self.find("TIME_UNIT_CONFLICT", actual[1], f"the actual time is written in {actual[2]!r}, the nominal time "
                                                           f"in {unit!r}: the actual time is not read", "warn")
                self.use(row, actual[3], "unaccounted", "time_unit_conflict", force=True)
            else:
                data.update(time_actual=actual[0], time_actual_locator=actual[1])
        statistic = (rule.role if rule is not None and rule.role in STATISTIC_RULES else None) or row_statistic or (
            key.statistic if key is not None else None) or column.statistic or self.spec.statistic
        if statistic is None and has_subject:
            statistic = "individual"
        data["statistic"] = statistic
        for spread_column in self.qualifiers("spread", column):
            cell = self.grid.cell(row, spread_column.column)
            if not cell.text.strip():
                continue
            parsed = self.parse(cell, row, spread_column.column, tokens=False)
            if parsed.value is None:
                self.find("UNPARSEABLE_SPREAD", cell.locator, f"the spread {cell.text.strip()!r} is no number code reads",
                          "warn")
                self.use(row, spread_column.column, "unaccounted", "unparseable")
                continue
            if data.get("spread") is not None:
                self.twice(cell, row, spread_column.column, "spread")
                continue
            self.use(row, spread_column.column, "spread")
            data.update(spread=parsed.value, spread_kind=spread_column.spread_kind or row_spread_kind or (
                key.spread_kind if key is not None else None), spread_verbatim=cell.text.strip(), spread_locator=cell.locator)
        if data.get("spread") is not None and data.get("spread_kind") is None and column.spread_kind is not None:
            data["spread_kind"] = column.spread_kind
        for n_column in self.qualifiers("n", column):
            cell = self.grid.cell(row, n_column.column)
            if cell.text.strip():
                self.set_n(value, cell, n_column.column)
        lows, highs = self.qualifiers("interval_low", column), self.qualifiers("interval_high", column)
        if lows and highs:
            low_cell, high_cell = self.grid.cell(row, lows[0].column), self.grid.cell(row, highs[0].column)
            if low_cell.text.strip() and high_cell.text.strip():
                low = self.parse(low_cell, row, lows[0].column, tokens=False)
                high = self.parse(high_cell, row, highs[0].column, tokens=False)
                if low.value is None or high.value is None:
                    self.find("UNPARSEABLE_INTERVAL", low_cell.locator, "the interval's bounds are not two numbers", "warn")
                    self.use(row, lows[0].column, "unaccounted", "unparseable")
                    self.use(row, highs[0].column, "unaccounted", "unparseable")
                elif data.get("interval") is not None:
                    self.twice(low_cell, row, lows[0].column, "interval")
                    self.twice(high_cell, row, highs[0].column, "interval")
                else:
                    self.use(row, lows[0].column, "interval")
                    self.use(row, highs[0].column, "interval")
                    self.set_interval(value, (low.value, high.value), (low_cell.locator, high_cell.locator), column,
                                      [lows[0], highs[0]])
        for flag_column in self.qualifiers("blq_flag", column):
            cell = self.grid.cell(row, flag_column.column)
            if not cell.text.strip():
                continue
            self.use(row, flag_column.column, "label")
            flag = nfkc(cell.text).strip().lower()
            if flag in _YES:
                if data.get("value") is not None:
                    self.find("BLQ_FLAG_WITH_VALUE", cell.locator, "the row is flagged below the LLOQ and writes a number: "
                                                                   "the value is kept as censored", "warn")
                data["censored"] = True
            elif flag not in _NO:
                self.find("BLQ_FLAG_NOT_READ", cell.locator, f"{cell.text.strip()!r} is not yes or no", "warn")
        for lloq_column in self.qualifiers("lloq", column):
            self.row_lloq(value, lloq_column)

    def row_lloq(self, value: _Value, lloq_column: ColumnMap) -> None:
        """The LLOQ its row's LLOQ column writes, for the value whether it is censored or not (an LLOQ cell always lands
        on a value); a value whose own cell writes another LLOQ ("<0.5") keeps its own (LLOQ_DIFFERS)."""
        row, data = value.row, value.data
        cell = self.grid.cell(row, lloq_column.column)
        if not cell.text.strip():
            return
        parsed = self.parse(cell, row, lloq_column.column, tokens=False)
        if parsed.value is None:
            self.find("UNPARSEABLE_LLOQ", cell.locator, f"the LLOQ {cell.text.strip()!r} is no number code reads", "warn")
            self.use(row, lloq_column.column, "unaccounted", "unparseable")
            return
        if data.get("lloq") is not None and data["lloq"] != parsed.value:
            self.find("LLOQ_DIFFERS", cell.locator, f"the value's own cell writes the LLOQ {data['lloq']!r}; this column "
                                                    f"writes {cell.text.strip()!r}: the cell's own is kept", "warn")
            self.use(row, lloq_column.column, "unaccounted", "lloq_differs")
            return
        self.use(row, lloq_column.column, "lloq")
        if data.get("lloq") is None:
            data.update(lloq=parsed.value, lloq_unit=self.lloq_unit(lloq_column), lloq_locator=cell.merged_from or cell.locator)

    def set_n(self, value: _Value, cell: GridCell, column: int, rule: str = "") -> None:
        row, col = self.at[cell.locator]
        parsed = self.parse(cell, row, col, tokens=False)
        if parsed.value is None or not parsed.value.is_integer():
            self.find("UNPARSEABLE_N", cell.locator, f"the n {cell.text.strip()!r} is no whole number", "warn")
            self.use(row, col, "unaccounted", "unparseable")
            return
        if value.data.get("n") is not None:
            self.twice(cell, row, col, "n")
            return
        self.use(row, col, "n", rule)
        value.data.update(n=int(parsed.value), n_locator=cell.locator)

    def set_interval(self, value: _Value, bounds: tuple[float, float], locators: tuple[str, str], column: ColumnMap,
                     columns: Sequence[ColumnMap], words: Sequence[str] = ()) -> None:
        level = self.column_level.get(column.column) or next((self.column_level[c.column] for c in columns
                                                              if c.column in self.column_level), None)
        if level is not None:
            kind, number = "CI", level[0]
        else:
            headers = [*words, *(self.grid.cell(r, c.column).text for c in columns for r in range(1, self.spec.first_data_row))]
            kind, number = _interval_kind(headers)
            if kind is None:
                self.find("INTERVAL_KIND_UNSTATED", locators[0], "no CI level and no min-max is written for this interval",
                          "warn", once=f"interval:{column.column}")
        value.data.update(interval=bounds, interval_kind=kind, interval_level=number, interval_locators=locators)

    # --- qualifier rows (SD, N, CI rows under a Mean row) -------------------------------------------------------------

    def qualifier_target(self, row: int, rule: RowRule, statistic_rows: Sequence[int]) -> int | None:
        """The statistic row a qualifier row qualifies: of its own time, labels and conditions (a time, label or
        condition the qualifier row leaves empty matches any), the nearest above, else the nearest below; none when its
        time cell writes no time code reads (UNPARSEABLE_TIME)."""
        time_column = next((c.column for c in self.spec.columns if c.role == "time"), None)
        time, problem = (None, False) if time_column == rule.column else self.time_of(row)
        if problem:
            return None
        labels = {k: v[0] for k, v in self.labels(row, rule.column, statistic_row=True).items()}
        conditions = {k: v[0] for k, v in self.conditions(row).items()}

        def agrees(target: int) -> bool:
            target_time, target_labels, target_conditions = self.row_keys.get(target, (None, {}, {}))
            if time is not None and target_time is not None and not math.isclose(time[0], target_time, rel_tol=1e-9):
                return False
            if any(target_labels.get(k, v) != v for k, v in labels.items()):
                return False
            return all(target_conditions.get(k, v) == v for k, v in conditions.items())

        candidates = [r for r in statistic_rows if agrees(r)]
        above = [r for r in candidates if r < row]
        below = [r for r in candidates if r > row]
        return above[-1] if above else (below[0] if below else None)

    def qualifier_row(self, row: int, rule: RowRule, statistic_rows: Sequence[int]) -> None:
        target = self.qualifier_target(row, rule, statistic_rows)
        for column in self.value_columns:
            cell = self.grid.cell(row, column.column)
            if not cell.text.strip() or cell.merged_from is not None:
                continue
            value = self.values_by_cell.get((target, column.column)) if target is not None else None
            if value is None or not value.measured:
                self.find("QUALIFIER_WITHOUT_VALUE", cell.locator, f"a {rule.role} row with no value of a statistic row of "
                                                                   "its time and labels to qualify in this column", "warn",
                          once=f"q:{row}")
                continue
            if rule.role == "spread":
                parsed = self.parse(cell, row, column.column, tokens=False)
                if parsed.value is None:
                    self.find("UNPARSEABLE_SPREAD", cell.locator, f"the spread {cell.text.strip()!r} is no number code "
                                                                  "reads", "warn")
                    self.use(row, column.column, "unaccounted", "unparseable")
                    continue
                if value.data.get("spread") is not None:
                    self.twice(cell, row, column.column, "spread")
                    continue
                self.use(row, column.column, "spread", f"row_rule:{rule.pattern}")
                value.data.update(spread=parsed.value, spread_kind=rule.spread_kind, spread_verbatim=cell.text.strip(),
                                  spread_locator=cell.locator)
            elif rule.role == "n":
                self.set_n(value, cell, column.column, f"row_rule:{rule.pattern}")
            else:
                self.interval_bound(value, cell, row, column, rule)

    def interval_bound(self, value: _Value, cell: GridCell, row: int, column: ColumnMap, rule: RowRule) -> None:
        parsed = self.parse(cell, row, column.column, tokens=False)
        if parsed.value is None:
            self.find("UNPARSEABLE_INTERVAL", cell.locator, "the interval bound is no number code reads", "warn")
            self.use(row, column.column, "unaccounted", "unparseable")
            return
        bounds = value.data.setdefault("_bounds", {})
        if rule.role in bounds or value.data.get("interval") is not None:
            self.twice(cell, row, column.column, "interval bound")
            return
        self.use(row, column.column, "interval", f"row_rule:{rule.pattern}")
        bounds[rule.role] = (parsed.value, cell.locator, self.grid.cell(row, rule.column).text)
        if "interval_low" in bounds and "interval_high" in bounds:
            low, high = bounds["interval_low"], bounds["interval_high"]
            self.set_interval(value, (low[0], high[0]), (low[1], high[1]), column, [column], words=(low[2], high[2]))

    def key_qualifier_row(self, row: int, key: KeyMap) -> None:
        for column in self.value_columns:
            cell = self.grid.cell(row, column.column)
            if not cell.text.strip() or cell.merged_from is not None:
                continue
            earlier = [v for (r, c), v in self.values_by_cell.items() if c == column.column and r < row
                       and v.data.get("field") == key.field]
            if not earlier:
                self.find("QUALIFIER_WITHOUT_VALUE", cell.locator, f"a {key.spread_kind} row with no {key.field} value "
                                                                   "above it in this column", "warn", once=f"k:{row}")
                continue
            parsed = self.parse(cell, row, column.column, tokens=False)
            if parsed.value is None:
                self.find("UNPARSEABLE_SPREAD", cell.locator, f"the spread {cell.text.strip()!r} is no number code reads",
                          "warn")
                self.use(row, column.column, "unaccounted", "unparseable")
                continue
            if earlier[-1].data.get("spread") is not None:
                self.twice(cell, row, column.column, "spread")
                continue
            self.use(row, column.column, "spread", f"key:{key.pattern}")
            earlier[-1].data.update(spread=parsed.value, spread_kind=key.spread_kind, spread_verbatim=cell.text.strip(),
                                    spread_locator=cell.locator)

    # --- the result ----------------------------------------------------------------------------------------------------

    def ignored(self) -> None:
        for column in self.spec.columns:
            if column.role != "ignore":
                continue
            for row in self.data_rows:
                self.use(row, column.column, "excluded", "column:ignore")

    def result(self) -> ExtractResult:
        if self.spec.kind == "not_data":
            for (row, column) in self.grid.cells:
                self.use(row, column, "excluded", "not_data")
            return self.finish([], [])
        self.read_constants()
        self.read_units()
        self.header()
        self.ignored()
        self.rows()
        for column, (_n, _u, locator) in self.column_lloq.items():
            if not any(v.data.get("lloq_locator") == locator for (_r, c), v in self.values_by_cell.items() if c == column):
                self.find("LLOQ_UNUSED", locator, "this column's LLOQ qualifies no censored value of the column", "info")
        rows = []
        for (_row, _column), value in sorted(self.values_by_cell.items()):
            data = {k: v for k, v in value.data.items() if not k.startswith("_")}
            rows.append(ExtractedRow(**data))
        return self.finish(rows, self.constants)

    def finish(self, rows: list[ExtractedRow], constants: list[ExtractedConstant]) -> ExtractResult:
        for (row, column) in self.grid.cells:
            self.use(row, column, "unaccounted")
        return ExtractResult(rows=tuple(rows), constants=tuple(constants),
                             cell_use=tuple(self.uses[k] for k in sorted(self.uses)), cited=tuple(self.cited),
                             decimal=self.decimal, findings=tuple(self.findings))
