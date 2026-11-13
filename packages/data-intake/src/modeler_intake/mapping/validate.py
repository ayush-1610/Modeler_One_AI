"""A mapping spec checked against one region's grid and context, before anything is executed (contracts §6.2).

`validate_spec` reads only the grid and its context lines. Every constant and every unit is re-read from THIS region's
own cells and lines, so a cached spec applied to a new region reads its own title (another study, another dose) and a
header that writes another unit fails `UNIT_NOT_STATED`: the region is then a different layout and falls through to
the rules. Findings are errors unless marked:

- CELL_OUTSIDE_REGION: a cell cite (or a column, a row) outside the region, a context line that does not exist;
- LAYOUT: no time source where the kind needs one, two nominal time sources, no value column, `of` not a value
  column, `time_row` not above the data, a `cell_form` on a non-value column, a `condition` not in
  `fields.CONDITION_FIELDS`, a value column with no field ...;
- UNKNOWN_FIELD: a field `fields.field` does not know;
- NUMBER_TYPED: a `Constant.text` or `pattern` on a number field (code reads numbers, the model never types one);
- CONSTANT_NOT_STATED: a number `read_constant` does not find exactly once; a name or text the pattern does not match
  exactly once, or whose reading differs from `Constant.text` (by `name_key`); a choice `fields.read_choice` does not
  read, or reads as another than `Constant.text`; an LLOQ or a CI level not stated at its cite;
- UNIT_NOT_CITED: a unit with no cite that the header band does not write;
- UNIT_NOT_STATED: a typed unit that is not one of `fields.units_in` of its cited text (for a class with no table:
  not in that text verbatim);
- UNIT_NOT_IN_TABLES (warn): a typed unit outside the table of its field's class (kept verbatim); a unit belongs to a
  value, time or LLOQ column (an LLOQ column's own unit, never the value column's);
- BAD_PATTERN (a pattern `reading.pattern_problem` refuses: invalid, too long, or one that can backtrack without end),
  TOKEN_IS_NUMBER, REASON_MISSING;
- STATISTIC_NOT_STATED, SPREAD_KIND_NOT_STATED: a typed statistic or spread kind that the column's header, the row
  rule's labels or the key's labels name otherwise ("Geometric mean" typed arithmetic_mean, "SEM" typed SD);
- LAYOUT also: two spreads (or two n) for one value, as two columns or two row rules that both match rows ("exclude
  one with a reason"): the second would overwrite the first;
- HEADER_ROWS_HOLD_VALUES: a header row below the header band (`fingerprint.header_band`) whose value-column cells
  read as values under the column's cell_form: the spec's header swallows data rows, which would be counted as header;
- HEADER_HOLDS_NUMBERS (warn): another header row (not the time row) holds two or more values in cells the spec
  does not cite (counted as header).

Numbers of constants are read under the region's decimal convention (`execute.decimal_convention`), as cells are: in
a comma region "1.000 mg" is ambiguous, never 1 mg.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from modeler_intake import fields
from modeler_intake.mapping.fingerprint import header_band
from modeler_intake.mapping.reading import (
    MAX_MATCH_TEXT,
    DecimalMark,
    cite_cells,
    cite_exists,
    decimal_convention,
    match_text,
    nfkc,
    pattern_problem,
    read_cited,
    read_level,
    read_number,
    same_name,
    split_cell,
    spread_kind_agrees,
    statistic_agrees,
    unit_at,
    value_like,
)
from modeler_intake.mapping_spec import Cite, ColumnMap, Constant, MappingSpec
from modeler_intake.source_model import Finding, RegionGrid, is_numeric_text

# the kinds whose values are read against a time (a profile): a spec for one needs a time source
TIMED_KINDS = frozenset({"pk_individual", "pk_summary", "dissolution"})
# the roles that qualify one value column (ColumnMap.of)
QUALIFIERS = frozenset({"spread", "n", "lloq", "interval_low", "interval_high", "unit", "blq_flag", "spread_kind"})
# qualifiers that may stand for every value column of the row (of None, several value columns)
ROW_WIDE = frozenset({"unit", "blq_flag", "spread_kind"})
LABEL_ROLES = frozenset({"subject", "arm", "period", "sequence", "occasion", "study", "analyte", "matrix", "product",
                         "batch", "vessel", "other_arm", "parameter"})
SERIES_ROLES = LABEL_ROLES | {"condition"}
_TIME_REFERENCE_CUES = {
    "first_dose": r"\bfirst\b[^.;]*\bdos|\bsingle\b[^.;]*\bdos|after (?:the )?dos(?:e|ing)\b|post-?dose",
    "last_dose": r"\blast\b[^.;]*\bdos|\bfinal\b[^.;]*\bdos|steady[- ]state",
    "occasion_dose": r"\bday\b|\bvisit\b|\boccasion\b|\bperiod\b",
}


def _cites(spec: MappingSpec) -> Iterator[tuple[str, Cite]]:
    """Every cite of the spec, with where it stands."""
    for name in ("time_unit_cite", "value_unit_cite", "time_reference_cite", "lloq"):
        cite = getattr(spec, name)
        if cite is not None:
            yield name, cite
    for i, column in enumerate(spec.columns):
        for name in ("unit_cite", "lloq", "level", "series"):
            cite = getattr(column, name)
            if cite is not None:
                yield f"columns[{i}].{name}", cite
    for i, constant in enumerate(spec.constants):
        yield f"constants[{i}] ({constant.field})", constant.cite


def value_field(spec: MappingSpec, column: ColumnMap) -> str | None:
    """The field of a value column's values when it is one for the whole column (key_value tables and a series of
    parameters take theirs from the keys, row by row or column by column: None)."""
    if spec.layout == "key_value" or column.series_role == "parameter":
        return None
    return column.field or spec.field


def unit_field(spec: MappingSpec) -> str | None:
    """The field `MappingSpec.value_unit` is checked against: the spec's field, else the first value column's, else the
    first key's."""
    if spec.field:
        return spec.field
    for column in spec.columns:
        if column.role == "value" and column.field:
            return column.field
    return spec.keys[0].field if spec.keys else None


def _compiles(pattern: str) -> re.Pattern[str] | None:
    """The pattern compiled, or None when `reading.pattern_problem` refuses it (BAD_PATTERN)."""
    return None if pattern_problem(pattern) is not None else re.compile(pattern)


def validate_spec(spec: MappingSpec, grid: RegionGrid) -> tuple[Finding, ...]:
    """Every problem of `spec` on this grid and its context (see the module docstring). Reads only the grid."""
    out: list[Finding] = []

    def add(code: str, location: str, message: str, severity: str = "error") -> None:
        out.append(Finding(code=code, location=location, message=message, severity=severity))  # type: ignore[arg-type]

    if spec.kind == "not_data":
        if not spec.not_data_reason.strip():
            add("REASON_MISSING", "not_data_reason", "a table that is not data says why (not_data_reason)")
        return tuple(out)
    decimal = decimal_convention(grid)
    _bounds(spec, grid, add)
    _layout(spec, add)
    _fields_and_patterns(spec, add)
    _tokens_and_reasons(spec, add)
    _constants(spec, grid, decimal, add)
    _units(spec, grid, add)
    _header(spec, grid, decimal, add)
    _qualifiers(spec, grid, add)
    _statistics(spec, grid, add)
    return tuple(out)


def _bounds(spec: MappingSpec, grid: RegionGrid, add) -> None:
    if spec.first_data_row > grid.n_rows:
        add("CELL_OUTSIDE_REGION", "first_data_row", f"the region has {grid.n_rows} rows; the data cannot start at row "
                                                     f"{spec.first_data_row}")
    if spec.last_data_row is not None and spec.last_data_row > grid.n_rows:
        add("CELL_OUTSIDE_REGION", "last_data_row", f"the region has {grid.n_rows} rows")
    if spec.time_row is not None and not 1 <= spec.time_row <= grid.n_rows:
        add("CELL_OUTSIDE_REGION", "time_row", f"the region has {grid.n_rows} rows")
    for i, column in enumerate(spec.columns):
        if not 1 <= column.column <= grid.n_cols:
            add("CELL_OUTSIDE_REGION", f"columns[{i}]", f"the region has {grid.n_cols} columns")
    for i, rule in enumerate(spec.row_rules):
        if not 1 <= rule.column <= grid.n_cols:
            add("CELL_OUTSIDE_REGION", f"row_rules[{i}]", f"the region has {grid.n_cols} columns")
    for where, cite in _cites(spec):
        if not cite_exists(grid, cite):
            place = f"context line {cite.near} {cite.line}" if cite.near else f"cell row {cite.row}, column {cite.column}"
            add("CELL_OUTSIDE_REGION", where, f"the region has no {place}")


def _layout(spec: MappingSpec, add) -> None:
    columns = spec.columns
    if spec.header_rows >= spec.first_data_row:
        add("LAYOUT", "header_rows", "the header rows end above the first data row")
    if spec.last_data_row is not None and spec.last_data_row < spec.first_data_row:
        add("LAYOUT", "last_data_row", "the last data row is above the first")
    seen: set[int] = set()
    for i, column in enumerate(columns):
        if column.column in seen:
            add("LAYOUT", f"columns[{i}]", f"column {column.column} is mapped twice")
        seen.add(column.column)
    values = {c.column for c in columns if c.role == "value"}
    if not values:
        add("LAYOUT", "columns", "no value column")
    times = sum(c.role == "time" for c in columns) + (spec.time_row is not None)
    if times > 1:
        add("LAYOUT", "columns", "two nominal time sources (a time column and time_row, or two time columns)")
    if sum(c.role == "time_actual" for c in columns) > 1:
        add("LAYOUT", "columns", "two actual-time columns")
    if spec.layout == "wide_times" and spec.time_row is None:
        add("LAYOUT", "time_row", "no time source: a wide_times table reads its times from time_row")
    elif spec.layout != "wide_times" and spec.time_row is not None:
        add("LAYOUT", "time_row", "time_row is for a wide_times layout (times across the header)")
    elif spec.kind in TIMED_KINDS and times == 0:
        add("LAYOUT", "columns", f"no time source: a {spec.kind} table needs a time column")
    if spec.time_row is not None and spec.time_row >= spec.first_data_row:
        add("LAYOUT", "time_row", "time_row is not above the data")
    for i, column in enumerate(columns):
        where = f"columns[{i}]"
        if column.cell_form != "value" and column.role != "value":
            add("LAYOUT", where, f"cell_form {column.cell_form!r} on a {column.role} column")
        if column.role in QUALIFIERS:
            if column.of is not None and column.of not in values:
                add("LAYOUT", where, f"of names column {column.of}, which is not a value column")
            elif column.of is None and len(values) > 1 and column.role not in ROW_WIDE:
                add("LAYOUT", where, f"a {column.role} column of a table with several value columns says which (of)")
        if column.role == "condition" and column.condition not in fields.CONDITION_FIELDS:
            add("LAYOUT", where, f"condition {column.condition!r} is not one of {', '.join(fields.CONDITION_FIELDS)}")
        if (column.series is None) != (column.series_role is None):
            add("LAYOUT", where, "a series cite and its series_role go together")
        if column.series_role is not None:
            if column.series_role not in SERIES_ROLES:
                add("LAYOUT", where, f"series_role {column.series_role!r} does not name a label, a condition or a parameter")
            elif column.series_role == "condition" and column.condition not in fields.CONDITION_FIELDS:
                add("LAYOUT", where, f"condition {column.condition!r} is not one of {', '.join(fields.CONDITION_FIELDS)}")
            if column.series is not None and column.series.near is not None:
                add("LAYOUT", where, "a series is named by a header cell of its column (row and column)")
        if column.role == "value" and value_field(spec, column) is None and spec.layout != "key_value" \
                and column.series_role != "parameter":
            add("LAYOUT", where, "a value column with no field (ColumnMap.field or MappingSpec.field)")
    if spec.layout == "key_value" or any(c.series_role == "parameter" for c in columns):
        if not spec.keys:
            add("LAYOUT", "keys", "a key_value table (or a series of parameters) maps its labels to fields with keys")
        if spec.layout == "key_value" and not any(c.role == "parameter" for c in columns):
            add("LAYOUT", "columns", "a key_value table needs its parameter (label) column")


def _fields_and_patterns(spec: MappingSpec, add) -> None:
    named = [("field", spec.field)] + [(f"columns[{i}].field", c.field) for i, c in enumerate(spec.columns)]
    named += [(f"keys[{i}].field", k.field) for i, k in enumerate(spec.keys)]
    named += [(f"constants[{i}].field", c.field) for i, c in enumerate(spec.constants)]
    for where, name in named:
        if name is not None and fields.field(name) is None:
            add("UNKNOWN_FIELD", where, f"{name!r} is not a field of the ledger's vocabulary")
    for i, rule in enumerate(spec.row_rules):
        if (problem := pattern_problem(rule.pattern)) is not None:
            add("BAD_PATTERN", f"row_rules[{i}]", problem)
    for i, key in enumerate(spec.keys):
        if (problem := pattern_problem(key.pattern)) is not None:
            add("BAD_PATTERN", f"keys[{i}]", problem)
    for i, constant in enumerate(spec.constants):
        where = f"constants[{i}] ({constant.field})"
        definition = fields.field(constant.field)
        if definition is not None and definition.value in ("number", "integer"):
            if constant.text is not None or constant.pattern is not None:
                add("NUMBER_TYPED", where, "a number is read by code from its cite: give no text and no pattern")
            continue
        if constant.pattern is None:
            continue
        if definition is not None and definition.value == "choice":
            add("BAD_PATTERN", where, "a choice is read by its words (fields.read_choice): give no pattern")
            continue
        if (problem := pattern_problem(constant.pattern)) is not None:
            add("BAD_PATTERN", where, problem)
        elif re.compile(constant.pattern).groups != 1:
            add("BAD_PATTERN", where, "the pattern is a valid regular expression with exactly one group")


def _tokens_and_reasons(spec: MappingSpec, add) -> None:
    for name in ("below_lloq_tokens", "missing_tokens"):
        for token in getattr(spec, name):
            if is_numeric_text(token):
                add("TOKEN_IS_NUMBER", name, f"a token must not be a number ({token!r}): numbers are read by code")
    for i, rule in enumerate(spec.row_rules):
        if rule.role == "exclude" and not rule.reason.strip():
            add("REASON_MISSING", f"row_rules[{i}]", "an excluded row says why (reason)")
    for i, column in enumerate(spec.columns):
        if column.role == "ignore" and not column.reason.strip():
            add("REASON_MISSING", f"columns[{i}]", "an ignored column says why its cells are not data (reason)")


def _constants(spec: MappingSpec, grid: RegionGrid, decimal: DecimalMark, add) -> None:
    for i, constant in enumerate(spec.constants):
        _constant(f"constants[{i}] ({constant.field})", constant, grid, decimal, add)
    if spec.lloq is not None and cite_exists(grid, spec.lloq):
        _constant("lloq", Constant(field="lloq", cite=spec.lloq), grid, decimal, add)
    for i, column in enumerate(spec.columns):
        if column.lloq is not None and cite_exists(grid, column.lloq):
            _constant(f"columns[{i}].lloq", Constant(field="lloq", cite=column.lloq), grid, decimal, add)
        if column.level is not None and cite_exists(grid, column.level):
            texts = [c.text for c in cite_cells(grid, column.level)]
            if sum(read_level(t, decimal=decimal) is not None for t in texts) != 1:
                add("CONSTANT_NOT_STATED", f"columns[{i}].level", "the cited text does not state one confidence level "
                                                                  "(a number followed by %)")
    if spec.time_reference is not None:
        cite = spec.time_reference_cite
        if cite is None:
            add("CONSTANT_NOT_STATED", "time_reference", "a time reference is read from its cite (time_reference_cite)")
        elif cite_exists(grid, cite):
            text = " ".join(c.text for c in cite_cells(grid, cite))
            if not re.search(_TIME_REFERENCE_CUES[spec.time_reference], text, re.IGNORECASE):
                add("CONSTANT_NOT_STATED", "time_reference", f"the cited text does not state {spec.time_reference}: "
                                                             f"{text[:120]!r}")


def _constant(where: str, constant: Constant, grid: RegionGrid, decimal: DecimalMark, add) -> None:
    definition = fields.field(constant.field)
    if definition is None or not cite_exists(grid, constant.cite):
        return
    if definition.value in ("number", "integer") and (constant.text is not None or constant.pattern is not None):
        return                                                     # NUMBER_TYPED already
    if constant.pattern is not None and (definition.value == "choice" or _compiles(constant.pattern) is None):
        return                                                     # BAD_PATTERN already
    cells = cite_cells(grid, constant.cite)
    text = " | ".join(c.text for c in cells)
    readings = read_cited(constant, cells, decimal=decimal)
    if len(readings) == 1 and readings[0].value is None:
        add("CONSTANT_NOT_STATED", where, f"code reads {readings[0].written!r} as ambiguous in this {decimal}-decimal "
                                          f"region (a thousands group or a decimal): {text[:120]!r}")
        return
    if len(readings) != 1:
        what = {"number": "one number of its unit class", "integer": "one whole number", "choice": "one choice"}.get(
            definition.value, "the pattern exactly once" if constant.pattern else "one name (a single cell)")
        long = constant.pattern is not None and any(len(c.text) > MAX_MATCH_TEXT for c in cells)
        add("CONSTANT_NOT_STATED", where, f"code reads {len(readings)} readings where the cited text must state "
                                          f"{what}{' (a pattern is matched against at most 400 characters)' if long else ''}: "
                                          f"{text[:120]!r}")
        return
    if constant.text is not None and definition.value not in ("number", "integer"):
        found = str(readings[0].value)
        agree = found == constant.text if definition.value == "choice" else same_name(found, constant.text)
        if not agree:
            add("CONSTANT_NOT_STATED", where, f"code reads {found!r} at the cite, not {constant.text!r}")


def _band_cells(spec: MappingSpec, grid: RegionGrid) -> list:
    rows = max(spec.header_rows, header_band(grid))
    return [cell for (row, _c), cell in sorted(grid.cells.items()) if row <= rows]


def _unit(where: str, field: str, typed: str, cite: Cite | None, spec: MappingSpec, grid: RegionGrid, add) -> None:
    if cite is None:
        if unit_at(field, typed, _band_cells(spec, grid)) is None:
            add("UNIT_NOT_CITED", where, f"the unit {typed!r} has no cite and the header band does not write it")
            return
    elif cite_exists(grid, cite):
        cells = cite_cells(grid, cite)
        if unit_at(field, typed, cells) is None:
            text = " | ".join(c.text for c in cells)
            add("UNIT_NOT_STATED", where, f"the cited text does not write the unit {typed!r}: {text[:120]!r}")
            return
    else:
        return                                                    # CELL_OUTSIDE_REGION already
    if fields.unit_table(fields.unit_class(field)) is not None and fields.known_unit(field, typed) is None:
        add("UNIT_NOT_IN_TABLES", where, f"the unit {typed!r} is in no table of its class ({fields.unit_class(field)}); "
                                         "it is kept verbatim", "warn")


def _units(spec: MappingSpec, grid: RegionGrid, add) -> None:
    if spec.value_unit is not None:
        field = unit_field(spec)
        if field is not None and fields.field(field) is not None:
            _unit("value_unit", field, spec.value_unit, spec.value_unit_cite, spec, grid, add)
    if spec.time_unit is not None:
        _unit("time_unit", "time", spec.time_unit, spec.time_unit_cite, spec, grid, add)
    for i, column in enumerate(spec.columns):
        if column.unit is None:
            continue
        if column.role in ("time", "time_actual"):
            field = "time"
        elif column.role == "value":
            field = value_field(spec, column) or unit_field(spec)
        elif column.role == "lloq":
            field = "lloq"
        else:
            add("LAYOUT", f"columns[{i}].unit", f"a unit on a {column.role} column: units belong to value, time and lloq "
                                                "columns")
            continue
        if field == "time" or (field is not None and fields.field(field) is not None):
            _unit(f"columns[{i}].unit", field, column.unit, column.unit_cite, spec, grid, add)


def _cited_cells(spec: MappingSpec) -> set[tuple[int, int]]:
    """The region cells a spec cites (a series, a unit, an LLOQ, a level or a constant): read, never data."""
    return {(cite.row, cite.column) for _where, cite in _cites(spec) if cite.row is not None and cite.column is not None}


def _reads_as_value(text: str, column: ColumnMap, decimal: DecimalMark) -> bool:
    """Whether a header cell of a value column reads as one of its values (its cell_form split, then the number)."""
    main = split_cell(text, column.cell_form)[0] if column.cell_form != "value" else nfkc(text).strip()
    main = re.sub(r"^[<>≤≥]\s*|[*†‡]+$", "", main).removesuffix("%").strip()
    return read_number(main, decimal, column_has_decimal=True)[0] is not None


def _header(spec: MappingSpec, grid: RegionGrid, decimal: DecimalMark, add) -> None:
    band = header_band(grid)
    cited = _cited_cells(spec)
    values = [c for c in spec.columns if c.role == "value"]
    for row in range(1, min(spec.header_rows, grid.n_rows) + 1):
        if row == spec.time_row:
            continue
        cells = {c: cell for (r, c), cell in grid.cells.items() if r == row and cell.merged_from is None and (r, c) not in cited}
        read = [c for c in values if c.column in cells and _reads_as_value(cells[c.column].text, c, decimal)]
        if row > band and read:
            add("HEADER_ROWS_HOLD_VALUES", f"header row {row}",
                f"header row {row} is below the table's header band and its value cells read as values: the header "
                "rows end above the data (first_data_row)")
        elif sum(is_numeric_text(cell.text) or value_like(cell.text) for cell in cells.values()) >= 2:
            add("HEADER_HOLDS_NUMBERS", f"header row {row}", "a header row holds values: they are counted as header, not "
                                                             "read; is this row data?", "warn")


def _data_rows(spec: MappingSpec, grid: RegionGrid) -> range:
    return range(spec.first_data_row, min(spec.last_data_row or grid.n_rows, grid.n_rows) + 1)


def _rule_rows(spec: MappingSpec, grid: RegionGrid, i: int) -> list[int]:
    """The data rows a row rule matches (its cell's whole text, case aside)."""
    rule = spec.row_rules[i]
    if pattern_problem(rule.pattern) is not None:
        return []
    return [r for r in _data_rows(spec, grid) if (text := nfkc(grid.cell(r, rule.column).text).strip())
            and match_text(rule.pattern, text)]


def _qualifiers(spec: MappingSpec, grid: RegionGrid, add) -> None:
    """One spread and one n per value: two columns or two row rules that would give a value a second one."""
    values = [c.column for c in spec.columns if c.role == "value"]
    for role in ("spread", "n"):
        targets: dict[int, list[int]] = {}
        for i, column in enumerate(spec.columns):
            if role == "spread" and column.role == "value" and column.cell_form in ("value (spread)", "value ± spread"):
                targets.setdefault(column.column, []).append(i)           # the cell writes its own spread
            if column.role != role:
                continue
            target = column.of if column.of is not None else (values[0] if len(values) == 1 else None)
            if target is not None:
                targets.setdefault(target, []).append(i)
        for target, found in targets.items():
            if len(found) > 1:
                add("LAYOUT", f"columns[{found[1]}]", f"two {role}s for the values of column {target}: map one, and "
                                                      "ignore the other with a reason")
        rules = [i for i, rule in enumerate(spec.row_rules) if rule.role == role and _rule_rows(spec, grid, i)]
        patterns = {spec.row_rules[i].pattern for i in rules}
        if len(patterns) > 1:
            add("LAYOUT", f"row_rules[{rules[1]}]", f"two {role} row rules match rows of this table: a value takes one "
                                                    f"{role}; exclude the other rows with a reason")


def _header_texts(spec: MappingSpec, grid: RegionGrid, column: int) -> list[str]:
    return [grid.cell(r, column).text for r in range(1, min(spec.header_rows, grid.n_rows) + 1)
            if r != spec.time_row and grid.cell(r, column).text.strip()]


def _statistics(spec: MappingSpec, grid: RegionGrid, add) -> None:
    """A typed statistic or spread kind is checked against the words code reads where the table writes them."""
    for i, column in enumerate(spec.columns):
        texts = _header_texts(spec, grid, column.column)
        if column.role == "value" and column.statistic is not None:
            for text in texts:
                if not statistic_agrees(column.statistic, text):
                    add("STATISTIC_NOT_STATED", f"columns[{i}].statistic", f"the header {text[:60]!r} names another "
                                                                           f"statistic than {column.statistic}")
        if column.role in ("value", "spread") and column.spread_kind is not None:
            for text in texts:
                if not spread_kind_agrees(column.spread_kind, text):
                    add("SPREAD_KIND_NOT_STATED", f"columns[{i}].spread_kind", f"the header {text[:60]!r} names another "
                                                                               f"spread than {column.spread_kind}")
    for i, rule in enumerate(spec.row_rules):
        if rule.role == "exclude":
            continue
        labels = dict.fromkeys(grid.cell(r, rule.column).text.strip() for r in _rule_rows(spec, grid, i))
        for label in labels:
            if rule.role in ("arithmetic_mean", "geometric_mean", "median") and not statistic_agrees(rule.role, label):
                add("STATISTIC_NOT_STATED", f"row_rules[{i}]", f"the row label {label[:60]!r} names another statistic "
                                                               f"than {rule.role}")
            if rule.spread_kind is not None and not spread_kind_agrees(rule.spread_kind, label):
                add("SPREAD_KIND_NOT_STATED", f"row_rules[{i}]", f"the row label {label[:60]!r} names another spread "
                                                                 f"than {rule.spread_kind}")
    parameter = next((c.column for c in spec.columns if c.role == "parameter"), None)
    if spec.layout != "key_value" or parameter is None:
        return
    for row in _data_rows(spec, grid):
        label = nfkc(grid.cell(row, parameter).text).strip()
        key_index = next((k for k, key in enumerate(spec.keys) if label and match_text(key.pattern, label)), None)
        if key_index is None:
            continue
        key = spec.keys[key_index]
        if key.statistic is not None and not statistic_agrees(key.statistic, label):
            add("STATISTIC_NOT_STATED", f"keys[{key_index}]", f"the label {label[:60]!r} names another statistic than "
                                                              f"{key.statistic}")
        if key.spread_kind is not None and not spread_kind_agrees(key.spread_kind, label):
            add("SPREAD_KIND_NOT_STATED", f"keys[{key_index}]", f"the label {label[:60]!r} names another spread than "
                                                                f"{key.spread_kind}")
