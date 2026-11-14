"""Rules before the LLM (contracts §6.2): today's no-AI reading and the client-data template, as mapping specs v2.

`map_by_rule` reuses today's rules without touching them: it turns the region into a `SheetGrid` whose first rows are
the region's context lines above and its caption (so `sheet_form.suggest` sees the title cells it reads dose, study id,
n and matrix from) and then the region, calls `suggest` (category from the region's table kind) and converts its form
with `from_sheet_form`: a title cell becomes a `near` cite (`caption`, `above` or `below`). A sheet region stands at its
own place on its own sheet, so `suggest` sees exactly the sheet around the table; a PDF or Word table is laid out as a
sheet, its context lines first. Because it sees one table at a time, the one-table-per-sheet limit of `suggest` no
longer loses a second table.

Values `suggest` assumes without a cell (unit "ng/ml", time unit "h", matrix "plasma", route "oral", a study id made
from the file name) are NOT carried into the spec: a spec states only what a `Cite` supports, and every constant and
unit is one code reads again at its cite; what is missing becomes a requirement gap or a person's entry. Today's
`SheetForm` has one mean row and a mean SD column, no SD row and no N row: the rules map what it maps, and the rest of
such a table is `unaccounted`, counted, never dropped. A column today's form takes for a subject's values although its
header names only a spread or a count ("SE", "n": `validate.not_a_value_header`) is NOT read as values: it stays
unaccounted too, never mapped as a concentration.

A rule spec never holds a value of its own table, so two tables of one layout get ONE spec (one version in the mapping
cache) and each reads its own title. A name (study id, analyte, batch, product, medium, apparatus) is cited where it
stands and read there by its SHAPE (`SHAPES`: today's reader of that name, written so `reading.pattern_problem` passes
it), never by a pattern that writes the name itself; a name with no shape is cited only where a cell holds nothing
else. The below-LLOQ and no-sample tokens are the rule's whole vocabulary (`recipe.DEFAULT_BELOW_LLOQ_TOKENS`,
`sheet_form.MISSING_TOKENS`), not the tokens one table happens to hold.

The arm (`treatment`) is the one reading today's form does not make: where the caption or a line above the table names
exactly one arm ("Cohort 1", "Treatment A": `ARM_SHAPE`, on a line the field registry's cue for `treatment` finds), it
is cited there, so two cohort tables of one study land on two arms. Where no arm is stated, none is guessed.

`template_spec` reads a client-data template sheet exactly (`client_template.SHEETS` is the one column list).
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from openpyxl.utils import column_index_from_string, get_column_letter
from pydantic import BaseModel, ConfigDict

from modeler_intake import fields
from modeler_intake.anchors import AnchorError, SheetCell, parse_locator
from modeler_intake.client_template import PK_PARAMETERS, SHEETS
from modeler_intake.grid import Cell, SheetGrid, as_text
from modeler_intake.mapping.execute import execute
from modeler_intake.mapping.reading import (
    DecimalMark,
    decimal_convention,
    read_cited,
    read_constant,
    read_text_constant,
    same_name,
)
from modeler_intake.mapping.validate import not_a_value_header, validate_spec
from modeler_intake.mapping_spec import Cite, ColumnMap, Constant, KeyMap, MappingError, MappingSpec, RowRule
from modeler_intake.recipe import DEFAULT_BELOW_LLOQ_TOKENS
from modeler_intake.sheet_form import _STUDY_ID, MISSING_TOKENS, SheetForm, suggest
from modeler_intake.source_model import DocumentRole, GridCell, Region, RegionGrid, is_numeric_text

RULES = "rules-1"
_SYNTHETIC_SHEET = "Table"
_CITABLE_LINES = 3                 # a Cite names context lines 1 to 3 (a fourth caption line is read by no constant)
# the table kinds today's form reads (concentration-time and dissolution); any other kind goes to the LLM or a person
_RULE_KINDS = frozenset({"pk_individual", "pk_summary", "dissolution"})
_CATEGORY_OF_KIND: Mapping[str, str] = {kind: category for category, kind in fields.KIND_OF_CATEGORY.items()
                                        if category != "OTHER"}
# a recipe constant key -> its ledger field (dose_unit is the dose's unit, not a value of its own)
_FIELD_OF_KEY: Mapping[str, str] = {"study_id": "study_id", "analyte": "analyte", "matrix": "matrix", "dose": "dose",
                                    "route": "route", "formulation": "formulation", "food_state": "food_state", "n": "n",
                                    "batch": "batch", "medium": "medium", "ph": "ph", "apparatus": "apparatus", "rpm": "rpm",
                                    "product": "product", "role": "product_role", "strength_mg": "strength_mg",
                                    "volume_ml": "volume_ml", "infusion_time_min": "infusion_time_min"}

# --- names by their shape -----------------------------------------------------------------------------------------------
# How a rule spec reads a name at its cite: by the name's shape, never by the name. Each is today's reader of that name
# (`sheet_form._STUDY_ID`, `_BATCH`, `_MEDIUM`, `_APPARATUS`), written flat so that `reading.pattern_problem` passes it
# (no repeated group that holds a repeat, at most three open repeats, one group), and reading a whole token only, never
# a part of a longer one ("230-23" is not stated by "230-23-A"). Tried in order; the rules cite a name with the first
# shape that reads, exactly once at the cite, the name today's form found; a name no shape reads there is left out of
# the spec with a note (a person enters it, or the requirement is a gap), never cited by a pattern that writes it.
_WHOLE = (r"(?<![\w-])", r"(?![\w-])")                                   # no letter, digit or hyphen before, none after
_DIGITS = r"\d\d\d?\d?"                                                # two to four digits
_MORE = rf"(?:[-/]{_DIGITS})?"                                            # one more group of a study id
# a study id: digits in two or more groups (230-23), or letters, a hyphen and digits (EX-201)
_STUDY_SHAPE = rf"[A-Z]{{0,4}}{_DIGITS}[-/]{_DIGITS}{_MORE}{_MORE}|[A-Z]{{1,4}}-{_DIGITS}{_MORE}{_MORE}"
_MATRIX_WORDS = r"(?:plasma|serum|whole blood|blood|urine)"
# an analyte's name where a title writes one: a word, but none of the commonest words a title of another table writes at
# the same place ("Mean plasma concentrations": a statistic is no analyte; a cached spec then does not read there and the
# table is mapped anew). The list is short on purpose (a pattern holds at most 200 characters): it is no vocabulary.
_NAME = rf"{_WHOLE[0]}(?!(?:mean|median|individual|total|human|plasma|serum|blood|urine|the|of|in|and)\b)([A-Z][\w-]*)"
# the medium's word; "buffer" after it belongs to it ("phosphate buffer" is one medium, not two)
_MEDIUM_SHAPE = (rf"(?i){_WHOLE[0]}(0\.1\s*n\s*hcl|hcl|acetate|phosphate|citrate|fassif|fessif|fassgf|sgf|sif|water|buffer|PB)"
                 rf"{_WHOLE[1]}(?:\s+buffer\b)?")
# "USP apparatus 2 (paddle)" is one apparatus, not two
_APPARATUS_SHAPE = (rf"(?i){_WHOLE[0]}(usp\s?(?:apparatus\s?)?(?:type\s?)?(?:iii|ii|iv|i|[1-4])|paddle|basket){_WHOLE[1]}"
                    r"(?:\s?\((?:paddle|basket)\))?")
# The arm a caption names ("Cohort 1", "Treatment A", "Arm B", "Group 2"): one of the words the field registry's cue for
# `treatment` announces an arm with (never a second list), and the short name after it (a number, or a capital letter
# with at most one digit). Not a plural ("Cohorts 1 and 2"), and not the first of a range or a list ("Cohort 1-3",
# "Cohort 1 and 2", "Treatment A/B"): those name more than one arm.
_ARM_WORDS = "|".join(re.findall(r"\\b([a-z]+)s\?\\b", fields.FIELDS["treatment"].cue))
ARM_SHAPE = (rf"{_WHOLE[0]}((?i:{_ARM_WORDS})\s+(?:\d\d?\d?|[A-Z]\d?)){_WHOLE[1]}"
             r"(?!\s?(?:&|/|-|–|and\b|or\b|to\b)\s?(?:\d|[A-Z]\b))")
SHAPES: Mapping[str, tuple[str, ...]] = {
    # after the word that announces it (the field registry's cue: "Study 230-23: ... doses of 10-30 mg" names one
    # study), else wherever a token of its shape stands
    "study_id": (rf"(?i)\bstudy\s+({_STUDY_SHAPE}){_WHOLE[1]}",          # "Study 230-23 (protocol EX-201)": the study
                 rf"(?i)(?:{fields.FIELDS['study_id'].cue})\s+({_STUDY_SHAPE}){_WHOLE[1]}",
                 rf"(?i){_WHOLE[0]}({_STUDY_SHAPE}){_WHOLE[1]}"),
    "batch": (rf"(?i)\b(?:batch|lot)\s*(?:no\.?|number)?[\s#:]*{_WHOLE[0]}([A-Z0-9][A-Z0-9/_.-]*[A-Z0-9/_-])",),
    # "Exampleamide plasma concentrations", "plasma concentrations of Exampleamide", "plasma Exampleamide concentrations",
    # "Exampleamide in plasma", "Exampleamide concentrations in plasma"
    "analyte": (rf"(?i){_NAME}\s+{_MATRIX_WORDS}\b",
                rf"(?i)\bconcentrations?\s+of\s+{_NAME}",
                rf"(?i)\b{_MATRIX_WORDS}\s+{_NAME}\s+concentrations?\b",
                rf"(?i){_NAME}\s+in\s(?:human\s)?{_MATRIX_WORDS}\b",
                rf"(?i){_NAME}\s+(?:concentrations?|levels?)\b"),
    # the product a title names before its batch ("Exampleamide IR tablet, batch L2301")
    "product": (r"(?i)^(?:dissolution of\s+)?(.+?),?\s+(?:batch|lot)\b",),
    "medium": (_MEDIUM_SHAPE,),
    "apparatus": (_APPARATUS_SHAPE,),
    "treatment": (ARM_SHAPE,),                  # read by `_arm` from the caption or a line above, not from today's form
}


class _B(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RuleMapping(_B):
    spec: MappingSpec
    rule: str                               # the rule's name and version (origin_detail of the cache entry)
    notes: tuple[str, ...]


# --- the region as a sheet ----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Placement:
    """Where the region and its context lines stand on the sheet `suggest` reads."""

    sheet: SheetGrid
    origin: tuple[int, int]                                   # the sheet (row, column) of the region's (1, 1)
    lines: Mapping[tuple[int, int], tuple[str, int]]          # the sheet (row, column) of a context cell -> (near, line)
    n_rows: int
    n_cols: int

    def cite(self, ref: str) -> Cite | None:
        """The relative cite of a "Sheet!A1" reference of `suggest`'s evidence; None for a cell outside the region and
        its context."""
        sheet, _, coordinate = ref.rpartition("!")
        match = re.fullmatch(r"\$?([A-Z]{1,3})\$?(\d+)", coordinate.strip().upper())
        if sheet != self.sheet.name or match is None:
            return None
        row, column = int(match.group(2)), column_index_from_string(match.group(1))
        r, c = row - self.origin[0] + 1, column - self.origin[1] + 1
        if 1 <= r <= self.n_rows and 1 <= c <= self.n_cols:
            return Cite(row=r, column=c)
        if (row, column) in self.lines:
            near, line = self.lines[(row, column)]
            return Cite(near=near, line=line) if line <= _CITABLE_LINES else None  # type: ignore[arg-type]
        return None


def _sheet_position(locator: str) -> tuple[str, int, int] | None:
    try:
        parsed = parse_locator(locator)
    except AnchorError:
        return None
    if not isinstance(parsed, SheetCell):
        return None
    match = re.fullmatch(r"([A-Z]{1,3})(\d+)", parsed.cell)
    return parsed.sheet, int(match.group(2)), column_index_from_string(match.group(1))


def _context(grid: RegionGrid) -> list[tuple[str, int, tuple[GridCell, ...]]]:
    """Every context line: (near, line number, its cells)."""
    return [*(("caption", i, (cell,)) for i, cell in enumerate(grid.caption, start=1)),
            *(("above", i, cells) for i, cells in enumerate(grid.above, start=1)),
            *(("below", i, cells) for i, cells in enumerate(grid.below, start=1))]


def _true_placement(grid: RegionGrid) -> dict[str, tuple[int, int]] | None:
    """Every cell's own (row, column) when the region and its context are cells of one sheet; else None."""
    positions: dict[str, tuple[int, int]] = {}
    sheets = set()
    origins = set()
    for (r, c), cell in grid.cells.items():
        found = _sheet_position(cell.locator)
        if found is None:
            return None
        sheets.add(found[0])
        origins.add((found[1] - r + 1, found[2] - c + 1))
        positions[cell.locator] = (found[1], found[2])
    for _near, _line, cells in _context(grid):
        for cell in cells:
            found = _sheet_position(cell.locator)
            if found is None:
                return None
            sheets.add(found[0])
            positions[cell.locator] = (found[1], found[2])
    if len(sheets) != 1 or len(origins) != 1:
        return None
    return positions


def _placement(grid: RegionGrid) -> _Placement:
    """The sheet `suggest` reads for this region: a sheet region and its context at their own places on their own
    sheet; any other region laid out from row 1 (its lines above, furthest first, then its caption, then the region)."""
    true = _true_placement(grid)
    lines: dict[tuple[int, int], tuple[str, int]] = {}
    placed: dict[tuple[int, int], GridCell] = {}
    if true is not None and grid.cells:
        name = next(_sheet_position(c.locator) for c in grid.cells.values())[0]  # type: ignore[index]
        (r, c), cell = next(iter(grid.cells.items()))
        origin = (true[cell.locator][0] - r + 1, true[cell.locator][1] - c + 1)
        for (r, c), cell in grid.cells.items():
            placed[(origin[0] + r - 1, origin[1] + c - 1)] = cell
        for near, line, cells in _context(grid):
            for cell in cells:
                lines[true[cell.locator]] = (near, line)
                placed[true[cell.locator]] = cell
    else:
        name = _SYNTHETIC_SHEET
        row = 0
        for near, line, cells in [*reversed([x for x in _context(grid) if x[0] == "above"]),
                                  *[x for x in _context(grid) if x[0] == "caption"]]:
            row += 1
            for column, cell in enumerate(cells, start=1):
                lines[(row, column)] = (near, line)
                placed[(row, column)] = cell
        origin = (row + 1, 1)
        for (r, c), cell in grid.cells.items():
            placed[(origin[0] + r - 1, c)] = cell
        bottom = origin[0] + grid.n_rows - 1
        for near, line, cells in [x for x in _context(grid) if x[0] == "below"]:
            for column, cell in enumerate(cells, start=1):
                lines[(bottom + line, column)] = (near, line)
                placed[(bottom + line, column)] = cell
    where = {cell.locator: position for position, cell in placed.items()}
    cells = {}
    for (row, column), cell in placed.items():
        origin_ref = None
        if cell.merged_from is not None and cell.merged_from in where:
            r0, c0 = where[cell.merged_from]
            origin_ref = f"{name}!{get_column_letter(c0)}{r0}"
        cells[(row, column)] = Cell(name, row, column, cell.value, merged_from=origin_ref)
    sheet = SheetGrid(name=name, max_row=max((r for r, _c in cells), default=1), max_column=max((c for _r, c in cells), default=1),
                      cells=cells)
    return _Placement(sheet=sheet, origin=origin, lines=lines, n_rows=grid.n_rows, n_cols=grid.n_cols)


# --- today's form as a spec ---------------------------------------------------------------------------------------------


def _region_rows_end(place: _Placement, first: int) -> int:
    """The last sheet row of the block of rows from `first` that `apply` reads with no last row: up to the first empty
    row, inside the region."""
    last = first
    bottom = place.origin[0] + place.n_rows - 1
    while last + 1 <= bottom and not place.sheet.row_is_empty(last + 1):
        last += 1
    return last


def _agrees(name: str, value: str, text: str, decimal: DecimalMark) -> Constant | None:
    """The constant that states `value` in `text`, when code reads it there under the region's decimal convention (None
    when it does not: a range "10-30 mg" or an ambiguous "1.000 mg" in a comma region states no one dose)."""
    definition = fields.field(name)
    if definition is None or not text.strip():
        return None
    if definition.value in ("number", "integer"):
        reading = read_constant(name, text, decimal=decimal)
        try:
            wanted = float(value)
        except ValueError:
            return None
        if reading is not None and math.isclose(float(reading[0]), wanted, rel_tol=1e-9):
            return Constant(field=name, cite=Cite(row=1, column=1))
        return None
    if definition.value == "choice":
        return Constant(field=name, cite=Cite(row=1, column=1)) if fields.read_choice(name, text) == value else None
    wanted = value.strip()
    if not wanted or (name == "study_id" and _STUDY_ID.fullmatch(wanted) is None):
        return None                                 # a study id made from the file name's stem is never a cell's
    if _is_name(name, text.strip(), wanted):
        return Constant(field=name, cite=Cite(row=1, column=1))        # the cell holds the name and nothing else
    # the name by its shape, never written into the pattern: another table of this layout reads its own name there
    for shape in SHAPES.get(name, ()):
        constant = Constant(field=name, cite=Cite(row=1, column=1), pattern=shape)
        read = read_text_constant(constant, text)
        if read is not None and _is_name(name, read, wanted):
            return constant
    return None


def _is_name(name: str, read: str, wanted: str) -> bool:
    """Whether what is read at a cite is the name today's form found (case, spaces and punctuation aside). An analyte
    may also be one name built on the drug's ("Exampleamide-M1" in a metabolite's table): the analyte is then the one
    the table states, never the drug."""
    if same_name(read, wanted):
        return True
    return (name == "analyte" and re.fullmatch(r"\S+", read) is not None
            and re.search(rf"(?<![^\W_]){re.escape(wanted)}(?![^\W_])", read, re.IGNORECASE) is not None)


def _candidates(place: _Placement, grid: RegionGrid, first_data_row: int, evidence: Sequence[str]) -> list[tuple[Cite, str]]:
    """The places a constant may be cited at, the evidence cells first: the context lines and the header rows."""
    out: list[tuple[Cite, str]] = []
    for ref in evidence:
        cite = place.cite(ref)
        if cite is not None:
            out.extend((cite, cell.text) for cell in _cells_at(grid, cite))
    for near, line, cells in _context(grid):
        if line <= _CITABLE_LINES:
            out.extend((Cite(near=near, line=line), cell.text) for cell in cells)    # type: ignore[arg-type]
    for (row, column), cell in sorted(grid.cells.items()):
        if row < first_data_row and cell.merged_from is None:
            out.append((Cite(row=row, column=column), cell.text))
    return out


def _cells_at(grid: RegionGrid, cite: Cite) -> tuple[GridCell, ...]:
    if cite.near is not None:
        return grid.context(cite.near, cite.line)
    cell = grid.cell(cite.row or 0, cite.column or 0)
    return (cell,) if cell.locator else ()


def _constants(form: SheetForm, place: _Placement, grid: RegionGrid, first_data_row: int,
               notes: list[str]) -> list[Constant]:
    stated = {**form.constants, **{k: v for k, v in form.study.items() if k not in form.constants}}
    decimal = decimal_convention(grid)
    found: list[Constant] = []
    for key, value in stated.items():
        name = _FIELD_OF_KEY.get(key)
        if name is None or not str(value).strip() or any(c.field == name for c in found):
            continue
        evidence = [e.cell for e in form.evidence if e.field == key]
        for cite, text in _candidates(place, grid, first_data_row, evidence):
            constant = _agrees(name, str(value), text, decimal)
            if constant is not None:
                found.append(constant.model_copy(update={"cite": cite}))
                break
        else:
            notes.append(f"{name} {value!r} is not stated once in a cell of this table or its context (not written, written "
                         "as a range or a list, or ambiguous under the table's decimal mark): left out of the spec (a "
                         "person enters it, or the requirement is a gap).")
    if form.kind != "dissolution":
        arm = _arm(grid, notes)
        if arm is not None:
            found.append(arm)
    return found


def _arm(grid: RegionGrid, notes: list[str]) -> Constant | None:
    """The arm the table's caption, or a line above it, names: cited at that line and read there by `ARM_SHAPE` (no
    name is written into the spec, so two cohort tables of one layout share one spec and land on two arms). The line is
    found by the field registry's cue for `treatment`. None when no such line names exactly one arm: an arm is never
    guessed (two tables of one study with no arm stated are then a conflict a person settles)."""
    cue = re.compile(fields.FIELDS["treatment"].cue, re.IGNORECASE)
    for near, line, cells in _context(grid):
        if near == "below" or line > _CITABLE_LINES or not any(cue.search(cell.text) for cell in cells):
            continue
        constant = Constant(field="treatment", cite=Cite(near=near, line=line), pattern=ARM_SHAPE)  # type: ignore[arg-type]
        if len(read_cited(constant, cells)) == 1:
            return constant
        notes.append(f"The {near} line {line} writes an arm, a treatment, a cohort, a group or a period but names no one "
                     "arm of this table: no arm is read (a person assigns it).")
    return None


def from_sheet_form(form: SheetForm, grid: RegionGrid) -> MappingSpec:
    """Today's `suggest` result as a v2 spec of this region: the form's rows and columns made relative to the region,
    every unit, LLOQ and constant only with the cite where code reads it (a title cell becomes a `near` cite). ValueError
    when the form does not read inside this region."""
    return _from_form(form, grid, _placement(grid), [])


def _from_form(form: SheetForm, grid: RegionGrid, place: _Placement, notes: list[str]) -> MappingSpec:
    r0, c0 = place.origin

    def row(sheet_row: int) -> int:
        return sheet_row - r0 + 1

    def col(letter: str) -> int:
        return column_index_from_string(letter) - c0 + 1

    first = row(form.first_data_row)
    if not 1 <= first <= grid.n_rows:
        raise ValueError("the form's data do not start inside this region")
    header = row(form.header_row) if form.header_row >= r0 else 0
    header = max(0, min(header, first - 1))
    last_sheet = form.last_data_row if form.last_data_row is not None else _region_rows_end(place, form.first_data_row)
    mean_row = form.mean_row if form.layout == "times_across" and form.subject_column else None
    if mean_row is not None and mean_row > last_sheet and all(place.sheet.row_is_empty(r) for r in range(last_sheet + 1, mean_row)):
        last_sheet = mean_row
    elif mean_row is not None and mean_row > last_sheet:
        notes.append(f"The mean row {mean_row} is not next to the subjects: not read by the rules.")
        mean_row = None
    last = row(last_sheet)
    dissolution = form.kind == "dissolution"
    columns: list[ColumnMap] = []
    values = [col(c) for c in form.value_columns]
    if any(not 1 <= c <= grid.n_cols for c in values):
        raise ValueError("the form's value columns are not inside this region")
    several = len(values) > 1                 # the form's own count: a subject's column stays one when its neighbour is left out
    values = _value_columns(values, form, grid, header, notes)
    if not values and not (form.layout == "times_down" and form.mean_column and not dissolution):
        raise ValueError("the form's value columns hold spreads or counts, not values")
    wide = form.layout == "times_down" and several and not form.subject_column
    series_role = "vessel" if dissolution else "subject"
    if form.layout == "times_down" and form.time_column:
        columns.append(ColumnMap(column=col(form.time_column), role="time"))
    if form.subject_column:
        columns.append(ColumnMap(column=col(form.subject_column), role="subject"))
    if form.group_column:
        columns.append(ColumnMap(column=col(form.group_column), role="period"))
    for c in values:
        if wide and header >= 1:
            columns.append(ColumnMap(column=c, role="value", series=Cite(row=header, column=c), series_role=series_role))
        else:
            columns.append(ColumnMap(column=c, role="value"))
    if form.layout == "times_down" and len(values) == 1 and not several:
        if form.sd_column:
            columns.append(ColumnMap(column=col(form.sd_column), role="spread", spread_kind="SD", of=values[0]))
        if form.n_column:
            columns.append(ColumnMap(column=col(form.n_column), role="n", of=values[0]))
    if form.layout == "times_down" and form.mean_column and not dissolution:
        mean = col(form.mean_column)
        columns.append(ColumnMap(column=mean, role="value", statistic=form.mean_statistic))
        if form.mean_sd_column:
            columns.append(ColumnMap(column=col(form.mean_sd_column), role="spread", spread_kind="SD", of=mean))
    row_rules: tuple[RowRule, ...] = ()
    if mean_row is not None and form.subject_column:
        label = as_text(place.sheet.cell(mean_row, form.subject_column).value)
        if label:
            row_rules = (RowRule(column=col(form.subject_column), pattern=re.escape(label), role=form.mean_statistic),)
    individual = form.statistic == "individual" and bool(values)       # no subject's column left: the mean profile only
    has_subjects = bool(form.subject_column) or (wide and header >= 1)
    summary = form.statistic if values else form.mean_statistic
    statistic = summary if not individual else ("individual" if has_subjects else None)
    unit = _unit(form, place, "value_unit", form.value_unit)
    time_unit = _unit(form, place, "time_unit", form.time_unit)
    lloq = next((place.cite(e.cell) for e in form.evidence if e.field == "lloq"), None) if form.lloq is not None else None
    spec = MappingSpec(
        kind="dissolution" if dissolution else ("pk_individual" if individual else "pk_summary"),
        layout="wide_times" if form.layout == "times_across" else ("long" if form.subject_column or not wide else "wide_series"),
        header_rows=header, first_data_row=first, last_data_row=None if last >= grid.n_rows else last,
        columns=tuple(columns), time_row=header if form.layout == "times_across" else None,
        field="percent_dissolved" if dissolution else "concentration",
        time_unit=time_unit[0] if time_unit else None, time_unit_cite=time_unit[1] if time_unit else None,
        value_unit=unit[0] if unit else None, value_unit_cite=unit[1] if unit else None, statistic=statistic,
        lloq=lloq, below_lloq_tokens=tuple(t for t in form.below_lloq_tokens if not is_numeric_text(t)),
        missing_tokens=tuple(form.missing_tokens), row_rules=row_rules,
        constants=tuple(_constants(form, place, grid, first, notes)))
    return _without_unstated(spec, grid, notes)


def _value_columns(values: list[int], form: SheetForm, grid: RegionGrid, header: int, notes: list[str]) -> list[int]:
    """The form's value columns without those whose header names only a spread or a count (`validate_spec` refuses
    such a value column): today's form takes an "SE" or an "n" column next to a Mean column for a subject's values.
    Left out with a note, their cells stay unaccounted and counted."""
    kept: list[int] = []
    for c in values:
        texts = [grid.cell(r, c).text for r in range(1, header + 1) if not (form.layout == "times_across" and r == header)]
        named = next(((t, what) for t in texts if (what := not_a_value_header(t, None)) is not None), None)
        if named is None:
            kept.append(c)
        else:
            notes.append(f"Column {get_column_letter(c)} of the table ({named[0]!r}) holds {named[1]}, not values: not read "
                         "by the rules (its cells stay unaccounted).")
    return kept


def _unit(form: SheetForm, place: _Placement, name: str, typed: str) -> tuple[str, Cite] | None:
    for evidence in form.evidence:
        if evidence.field == name:
            cite = place.cite(evidence.cell)
            if cite is not None:
                return typed, cite
    return None


def _without_unstated(spec: MappingSpec, grid: RegionGrid, notes: list[str]) -> MappingSpec:
    """The spec without a unit, LLOQ or constant that code does not read at its cite (validate_spec's findings): each
    left out with a note, never carried unread."""
    for _round in range(4):
        errors = [f for f in validate_spec(spec, grid) if f.severity == "error"]
        drop = {f.location for f in errors if f.code in ("UNIT_NOT_STATED", "UNIT_NOT_CITED", "CONSTANT_NOT_STATED",
                                                         "CELL_OUTSIDE_REGION")}
        if not drop:
            return spec
        update: dict[str, object] = {}
        if "value_unit" in drop or "value_unit_cite" in drop:
            update.update(value_unit=None, value_unit_cite=None)
        if "time_unit" in drop or "time_unit_cite" in drop:
            update.update(time_unit=None, time_unit_cite=None)
        if "lloq" in drop:
            update["lloq"] = None
        kept = tuple(c for i, c in enumerate(spec.constants) if f"constants[{i}] ({c.field})" not in drop)
        update["constants"] = kept
        notes.extend(f"{f.location}: {f.message} (left out of the spec)" for f in errors if f.location in drop)
        spec = spec.model_copy(update=update)
    return spec


def map_by_rule(grid: RegionGrid, region: Region, *, filename: str = "", drug: str = "",
                products: Sequence[Mapping[str, str]] = (), document_role: DocumentRole = "other") -> RuleMapping | None:
    """A spec for this region by rule, or None (no rule maps this layout): a client-data template sheet by
    `template_spec`; a concentration-time or dissolution table by today's `suggest`, converted by `from_sheet_form`
    and kept only when it validates on this region and reads at least one value."""
    sheet = _sheet_name(grid)
    if sheet is not None and (sheet in SHEETS or sheet == "README"):
        spec = template_spec(sheet, grid)
        if spec is not None and not any(f.severity == "error" for f in validate_spec(spec, grid)):
            note = f"the client-data template's {sheet} sheet, read by its header"
            return RuleMapping(spec=spec, rule=f"template/{RULES}", notes=(note,))
    if region.table_kind not in _RULE_KINDS:
        return None
    place = _placement(grid)
    form, notes = suggest(place.sheet, category=_CATEGORY_OF_KIND.get(region.table_kind, ""), filename=filename, drug=drug,
                          products=[dict(p) for p in products])
    if not form.value_columns or (form.layout == "times_down" and not form.time_column):
        return None
    form = form.model_copy(update=_vocabulary(form))
    more: list[str] = []
    try:
        spec = _from_form(form, grid, place, more)
        result = execute(spec, grid)
    except (ValueError, MappingError):
        return None
    if not any(r.value is not None or r.censored for r in result.rows):
        return None
    return RuleMapping(spec=spec, rule=f"sheet_form/{RULES}", notes=(*notes, *more))


def _vocabulary(form: SheetForm) -> dict[str, list[str]]:
    """The rule's whole token vocabulary, whichever of its tokens this table's cells hold: today's below-LLOQ tokens
    (and any other "<..." word the form found) and today's no-sample tokens. `suggest` lists only the tokens it sees, so
    two tables of one layout (one with an "NS" cell, one without) would get two specs."""
    known = {t.upper() for t in DEFAULT_BELOW_LLOQ_TOKENS}
    other = [t for t in form.below_lloq_tokens if t.strip().upper() not in known]
    return {"below_lloq_tokens": [*DEFAULT_BELOW_LLOQ_TOKENS, *other], "missing_tokens": list(MISSING_TOKENS)}


def _sheet_name(grid: RegionGrid) -> str | None:
    found = {p[0] for c in grid.cells.values() if (p := _sheet_position(c.locator)) is not None}
    return found.pop() if len(found) == 1 else None


# --- the client-data template ---------------------------------------------------------------------------------------------

_README_HEADER = ("Sheet", "Column", "Required", "Allowed values", "Notes")
_LABELS = {"study_id": "study", "treatment": "arm", "subject_id": "subject", "period": "period", "product": "product",
           "batch": "batch", "analyte": "analyte", "matrix": "matrix"}
_CONDITIONS = ("apparatus", "rpm", "medium", "ph", "volume_ml", "temperature_c", "surfactant", "interval_start_h",
               "interval_end_h")
_KINDS = {"Studies": "study_design", "PK_Individual": "pk_individual", "PK_Summary": "pk_summary",
          "PK_Parameters": "pk_parameters", "Dissolution": "dissolution", "Product": "product_batch",
          "Physchem_InVitro": "physchem_invitro", "Urine_Feces": "excretion"}
_FREE_TEXT = "the measurement's conditions, method and report are kept with the source: no condition field holds free text"


def _template_column(sheet: str, name: str, i: int, index: Mapping[str, int]) -> ColumnMap:
    """One template column's role (the template's own column names, `client_template.SHEETS`)."""
    if name in _LABELS:
        return ColumnMap(column=i, role=_LABELS[name])  # type: ignore[arg-type]
    if name in ("nominal_time", "time"):
        return ColumnMap(column=i, role="time")
    if name == "actual_time":
        return ColumnMap(column=i, role="time_actual")
    if name == "time_unit":
        return ColumnMap(column=i, role="time_unit")
    if name == "blq_flag":
        return ColumnMap(column=i, role="blq_flag", of=index["concentration"])
    if name == "statistic":
        return ColumnMap(column=i, role="statistic")
    if name == "variability":
        return ColumnMap(column=i, role="spread", of=index["value"])
    if name == "sd":
        return ColumnMap(column=i, role="spread", spread_kind="SD", of=index["mean"])
    if name == "variability_kind":
        return ColumnMap(column=i, role="spread_kind")
    if name == "n" and sheet in ("PK_Summary", "Dissolution"):
        return ColumnMap(column=i, role="n", of=index["value" if sheet == "PK_Summary" else "mean"])
    if name == "unit":
        of = next(index[x] for x in ("amount", "value", "concentration") if x in index)
        return ColumnMap(column=i, role="unit", of=of)
    if name in ("lloq_unit", "dose_unit"):
        return ColumnMap(column=i, role="unit", of=index["lloq" if name == "lloq_unit" else "dose"])
    if name == "parameter":
        return ColumnMap(column=i, role="parameter")
    if name in _CONDITIONS:
        return ColumnMap(column=i, role="condition", condition=name)
    if name.startswith("vessel_"):
        return ColumnMap(column=i, role="value", field="percent_dissolved", statistic="individual",
                         series=Cite(row=1, column=i), series_role="vessel")
    if name == "mean":
        return ColumnMap(column=i, role="value", field="percent_dissolved", statistic="arithmetic_mean")
    if name == "role":
        return ColumnMap(column=i, role="value", field="product_role")
    if name == "amount":
        return ColumnMap(column=i, role="value", field="excretion.amount")
    if name == "concentration":
        return ColumnMap(column=i, role="value", field="concentration", statistic="individual")
    if name in ("conditions", "method", "report_reference"):
        return ColumnMap(column=i, role="ignore", reason=_FREE_TEXT)
    if name == "value":
        return ColumnMap(column=i, role="value", field="concentration" if sheet == "PK_Summary" else None)
    if fields.field(name) is not None:
        return ColumnMap(column=i, role="value", field=name)
    return ColumnMap(column=i, role="ignore", reason="a template column no ledger field holds")


def template_spec(sheet_name: str, grid: RegionGrid) -> MappingSpec | None:
    """A client-data template sheet's spec, exactly: one header row of the template's column names (a required column
    marked "*"), one record per row from row 2. The README's column guide is a `not_data` table. None when the region's
    header is not the template's header of that sheet."""
    header = tuple(grid.cell(1, c).text.strip().rstrip("*").strip() for c in range(1, grid.n_cols + 1))
    if sheet_name == "README":
        if header != _README_HEADER:
            return None
        return MappingSpec(kind="not_data", layout="long", header_rows=1, first_data_row=2,
                           not_data_reason="the template's column guide (sheet, column, required, allowed values, notes): "
                                           "instructions for the client, not data")
    columns = SHEETS.get(sheet_name)
    if columns is None or header != tuple(c.name for c in columns) or grid.n_rows < 2:
        return None
    index = {name: i for i, name in enumerate(header, start=1)}
    mapped = tuple(_template_column(sheet_name, name, i, index) for name, i in index.items())
    keys: tuple[KeyMap, ...] = ()
    if sheet_name == "PK_Parameters":
        keys = tuple(KeyMap(pattern=re.escape(p), field=f"pk.{p}") for p in PK_PARAMETERS)
    elif sheet_name == "Physchem_InVitro":
        written = dict.fromkeys(t for r in range(2, grid.n_rows + 1) if (t := grid.cell(r, index["parameter"]).text.strip()))
        keys = tuple(KeyMap(pattern=re.escape(t), field=t) for t in written if fields.field(t) is not None
                     and fields.field(t).level == "compound")  # type: ignore[union-attr]
    concentration = sheet_name in ("PK_Individual", "PK_Summary")
    return MappingSpec(kind=_KINDS[sheet_name], layout="key_value" if sheet_name in ("PK_Parameters", "Physchem_InVitro")
                       else "long", header_rows=1, first_data_row=2, columns=mapped, keys=keys,
                       below_lloq_tokens=tuple(DEFAULT_BELOW_LLOQ_TOKENS) if concentration else ())


