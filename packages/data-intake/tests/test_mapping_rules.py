"""D3: rules before the LLM (contracts §6.2, §8.5). Today's no-AI reading (`sheet_form.suggest`) as a v2 spec reads
what today's recipe reads, one region at a time; a title cell becomes a `near` cite; no value `suggest` assumes without
a cell reaches the spec; a filled client-data template is read exactly. Software test data (the made-up Exampleamide),
never observed data."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from openpyxl.utils import get_column_letter

from modeler_intake import synthetic
from modeler_intake.anchors import SheetCell, format_locator
from modeler_intake.grid import SheetGrid, as_text, read_workbook_bytes
from modeler_intake.mapping.execute import execute
from modeler_intake.mapping.rules import RULES, from_sheet_form, map_by_rule, template_spec
from modeler_intake.mapping_spec import Cite, ExtractResult
from modeler_intake.reading_eval import CASES, Case, workbook
from modeler_intake.recipe_review import RecipeProposal, review_proposal
from modeler_intake.sheet_form import suggest, to_proposal
from modeler_intake.source_model import GridCell, Region, RegionGrid, has_number, number_text

pytestmark = pytest.mark.req("T-47")


# --- a sheet's table region as §6.1 locates it (D2's parser is not in this worktree) ---------------------------------


def _grid_cell(sheet: SheetGrid, row: int, column: int) -> GridCell | None:
    cell = sheet.cell(row, column)
    value = cell.value
    if value is None or value == "":
        return None
    locator = format_locator(SheetCell(sheet=sheet.name, cell=f"{get_column_letter(column)}{row}"))
    merged = None
    if cell.merged_from:
        origin = cell.merged_from.rpartition("!")[2]
        merged = format_locator(SheetCell(sheet=sheet.name, cell=origin))
    if isinstance(value, bool):
        return GridCell(text="TRUE" if value else "FALSE", value=value, type="bool", locator=locator, merged_from=merged)
    if isinstance(value, int | float):
        return GridCell(text=number_text(value), value=value, type="number", locator=locator, merged_from=merged)
    if isinstance(value, datetime | date):
        return GridCell(text=value.isoformat(), value=value.isoformat(), type="date", locator=locator, merged_from=merged)
    return GridCell(text=str(value), value=str(value), type="text", locator=locator, merged_from=merged)


def _span(sheet: SheetGrid, row: int) -> tuple[int, int] | None:
    columns = [c for c in range(1, sheet.max_column + 1) if as_text(sheet.cell(row, c).value)]
    return (columns[0], columns[-1]) if columns else None


def _numbers(sheet: SheetGrid, rows) -> int:
    return sum(has_number(as_text(sheet.cell(r, c).value)) for r in rows for c in range(1, sheet.max_column + 1))


def _locate(sheet: SheetGrid) -> RegionGrid:
    """The sheet's table region: blocks of non-empty rows (one empty row joined when the rows on both sides span the
    same columns and the row after it holds a number), the block with most cells holding a number, its single-cell text
    rows on top as the caption, the non-empty rows among the 3 above the caption and the 3 below as context lines."""
    filled = [r for r in range(1, sheet.max_row + 1) if _span(sheet, r)]
    blocks: list[list[int]] = []
    for row in filled:
        if blocks and (row == blocks[-1][-1] + 1 or (row == blocks[-1][-1] + 2 and _span(sheet, row) == _span(
                sheet, blocks[-1][-1]) and _numbers(sheet, [row]))):
            blocks[-1].append(row)
        else:
            blocks.append([row])
    block = max(blocks, key=lambda b: _numbers(sheet, b))
    caption = []
    while len(block) > 2 and _span(sheet, block[0])[0] == _span(sheet, block[0])[1] and \
            isinstance(sheet.cell(block[0], _span(sheet, block[0])[0]).value, str):
        caption.append(block.pop(0))
    top, bottom = block[0], block[-1]
    first = min(_span(sheet, r)[0] for r in block)
    last = max(_span(sheet, r)[1] for r in block)
    cells = {}
    for r in range(top, bottom + 1):
        for c in range(first, last + 1):
            made = _grid_cell(sheet, r, c)
            if made is not None:
                cells[(r - top + 1, c - first + 1)] = made

    def line(row: int) -> tuple[GridCell, ...]:
        return tuple(x for c in range(first, last + 1) if (x := _grid_cell(sheet, row, c)) is not None)

    head = caption[0] if caption else top
    above = tuple(line(r) for r in range(head - 1, head - 4, -1) if r >= 1 and line(r))
    below = tuple(line(r) for r in range(bottom + 1, bottom + 4) if line(r))
    return RegionGrid(file_sha256="0" * 64, parser="workbook", parser_version="1.0+test", region_id="rg-0000000000",
                      n_rows=bottom - top + 1, n_cols=last - first + 1, cells=cells,
                      caption=tuple(_grid_cell(sheet, r, _span(sheet, r)[0]) for r in caption), above=above, below=below)


# --- the eleven sheets of today's evaluation set ------------------------------------------------------------------------


def _kind(case: Case) -> str:
    if case.answer.kind == "dissolution":
        return "dissolution"
    return "pk_individual" if case.answer.statistic == "individual" else "pk_summary"


def _region(case: Case) -> tuple[RegionGrid, Region]:
    grid = _locate(workbook(case).sheets[case.sheet])
    return grid, Region(id=grid.region_id, kind="table", where="s:'x'!A1:B2", table_kind=_kind(case))


def _profiles(points) -> list:
    by_series: dict = {}
    for series, statistic, time, value, censored in points:
        by_series.setdefault((series, statistic), []).append((round(time, 9), value, censored))
    return sorted((statistic, sorted(profile)) for (_series, statistic), profile in by_series.items())


def _applied(case: Case, form) -> list:
    """What today's recipe reads from the case's sheet: (series, statistic, time, value or None below the LLOQ, BLQ)."""
    grid = workbook(case)
    review = review_proposal(grid, RecipeProposal.model_validate(to_proposal(form, grid.sheets[case.sheet])), recipe_id="t")
    if case.answer.kind == "dissolution":
        return _profiles((r.vessel, None, r.time, r.percent_dissolved, False) for r in review.dissolution)
    return _profiles((r.series, r.statistic, r.time, None if r.below_lloq else r.value, r.below_lloq)
                     for r in review.concentrations)


def _executed(case: Case, result: ExtractResult) -> list:
    rows = [r for r in result.rows if not (r.value is None and not r.censored and r.uloq is None)]   # no sample: no point
    dissolution = case.answer.kind == "dissolution"
    return _profiles((tuple(sorted((k, v) for k, v in r.labels.items() if k in ("subject", "period", "vessel"))),
                      None if dissolution else r.statistic, r.time, r.value, r.censored) for r in rows)


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_todays_form_as_a_v2_spec_reads_what_todays_recipe_reads(case):
    sheet = workbook(case).sheets[case.sheet]
    form = suggest(sheet, filename=case.file, drug=case.drug)[0]
    grid, region = _region(case)
    spec = from_sheet_form(form, grid)
    result = execute(spec, grid)
    assert _executed(case, result) == _applied(case, form)
    mapped = map_by_rule(grid, region, filename=case.file, drug=case.drug)
    assert mapped is not None and mapped.rule == f"sheet_form/{RULES}"
    assert _executed(case, execute(mapped.spec, grid)) == _applied(case, form)


def test_a_title_cell_read_by_suggest_becomes_a_near_cite():
    case = next(c for c in CASES if c.name == "be-times-across")
    grid, region = _region(case)
    mapped = map_by_rule(grid, region, filename=case.file, drug=case.drug)
    spec = mapped.spec
    title = "Study 230-23: plasma concentrations of desvenlafaxine (ng/mL) after a single 50 mg dose"
    assert [c.text for c in grid.above[0]] == [title] and [c.text for c in grid.caption] == ["Time (hr)"]
    assert (spec.time_unit, spec.time_unit_cite) == ("h", Cite(near="caption", line=1))         # "Time (hr)"
    assert (spec.value_unit, spec.value_unit_cite) == ("ng/mL", Cite(near="above", line=1))
    assert spec.lloq == Cite(near="below", line=1)                                              # "... (1.00 ng/mL) ..."
    assert {c.field: c.cite for c in spec.constants} == {"analyte": Cite(near="above", line=1),
                                                         "matrix": Cite(near="above", line=1),
                                                         "dose": Cite(near="above", line=1)}
    # the form's study id ("230-23-REF") and food state ("fasted") come from the file's name: not in the spec
    assert any(n.startswith("study_id '230-23-REF'") for n in mapped.notes)
    assert any(n.startswith("food_state 'fasted'") for n in mapped.notes)
    result = execute(spec, grid)
    assert {c.field: c.value for c in result.constants} == {"analyte": "desvenlafaxine", "dose": 50.0, "lloq": 1.0}
    assert {r.labels["matrix"] for r in result.rows} == {"plasma"}
    assert set(result.cited) == {grid.above[0][0].locator, grid.caption[0].locator, grid.below[0][0].locator}


def test_no_value_suggest_assumes_without_a_cell_reaches_the_spec():
    rows = [["Time", "Conc"], [0.5, 2.5], [1, 3.5], [2, 1.5]]
    book = __import__("openpyxl").Workbook()
    sheet = book.active
    sheet.title = "Data"
    for row in rows:
        sheet.append(row)
    import io

    buffer = io.BytesIO()
    book.save(buffer)
    grid_book = read_workbook_bytes(buffer.getvalue(), "Study_230-77_fasting_oral.xlsx")
    form, _notes = suggest(grid_book.sheets["Data"], filename="Study_230-77_fasting_oral.xlsx", drug="Exampleamide")
    assert (form.value_unit, form.time_unit, form.constants["matrix"], form.constants["route"]) == ("ng/ml", "h", "plasma",
                                                                                                    "oral")
    assert form.constants["study_id"].startswith("230-77")                  # made from the file name
    grid = _locate(grid_book.sheets["Data"])
    region = Region(id=grid.region_id, kind="table", where="s:'Data'!A1:B4", table_kind="pk_summary")
    mapped = map_by_rule(grid, region, filename="Study_230-77_fasting_oral.xlsx", drug="Exampleamide")
    spec = mapped.spec
    assert (spec.value_unit, spec.time_unit, spec.constants) == (None, None, ())
    assert any("left out of the spec" in n for n in mapped.notes)
    assert [r.value for r in execute(spec, grid).rows] == [2.5, 3.5, 1.5]


# --- one table at a time, any format ------------------------------------------------------------------------------------


def test_the_rules_read_each_table_of_a_sheet_on_its_own_and_count_what_the_form_cannot_read():
    messy = synthetic.messy_workbook()
    fasting = synthetic.truth_grid(messy, "fasting-individual")
    region = Region(id=fasting.region_id, kind="table", where="s:'Fasting'!A2:G14", table_kind="pk_individual")
    mapped = map_by_rule(fasting, region, filename=messy.name, drug=synthetic.DRUG)
    result = execute(mapped.spec, fasting)
    subjects = [r for r in result.rows if r.labels.get("subject")]
    assert len(subjects) == 36 and {r.labels["study"] for r in subjects} == {"230-23"}
    assert {c.field for c in mapped.spec.constants} == {"study_id", "dose", "food_state", "analyte", "matrix"}
    unaccounted = [u for u in result.cell_use if u.use == "unaccounted" and u.numeric]
    assert len(unaccounted) == 21                            # the Mean, SD, N and CV% rows: counted, never dropped
    metabolite = synthetic.truth_grid(messy, "fasting-metabolite")
    second = map_by_rule(metabolite, region.model_copy(update={"table_kind": "pk_summary"}), filename=messy.name,
                         drug=synthetic.DRUG)
    read = execute(second.spec, metabolite)
    assert [r.value for r in read.rows if r.statistic == "arithmetic_mean"] == [1.12, 2.35, 3.1, 2.21, 0.95]
    # today's form takes its BLQ tokens from the subjects' columns only: the Mean column's "BLQ" is a finding
    assert [(f.code, f.location) for f in read.findings] == [("UNPARSEABLE_VALUE", "s:'Fasting'!B22")]
    # the drug's name is not the metabolite's: "Exampleamide" is not stated by "Exampleamide-M1"
    assert "analyte" not in {c.field for c in second.spec.constants}


def test_the_rules_read_a_pdf_table_laid_out_as_a_sheet():
    report = synthetic.pdf_report()
    grid = synthetic.truth_grid(report, "report-table6")
    region = Region(id=grid.region_id, kind="table", where="p:4/t:1", table_kind="pk_summary")
    mapped = map_by_rule(grid, region, filename=report.name, drug=synthetic.DRUG)
    result = execute(mapped.spec, grid)
    assert [(r.time, r.value, r.spread, r.n) for r in result.rows][:2] == [(0.5, 3.2, 0.8, 8), (1.0, 5.8, 1.2, 8)]
    constants = {c.field: (c.value, c.locator) for c in result.constants}
    assert constants["dose"][0] == 10.0 and constants["dose"][1].startswith("p:4/w:1-13@")      # the caption's span
    assert constants["study_id"][0] == "230-26"


def test_a_kind_today_s_form_does_not_read_has_no_rule():
    messy = synthetic.messy_workbook()
    grid = synthetic.truth_grid(messy, "product-batches")
    region = Region(id=grid.region_id, kind="table", where="s:'Product'!A1:H3", table_kind="product_batch")
    assert map_by_rule(grid, region, filename=messy.name) is None


# --- the client-data template -----------------------------------------------------------------------------------------------


def test_template_spec_reads_every_sheet_of_a_filled_template_exactly():
    """Nominal and actual time, blq_flag, the statistic and variability_kind columns, the Dissolution conditions and the
    Urine_Feces intervals: the same rows, constants and cell uses as the truth's approved spec (which
    test_mapping_execute proves equal to the truth)."""
    template = synthetic.template_workbook()
    for table in template.tables:
        grid = synthetic.truth_grid(template, table.id)
        sheet = table.where.split("'")[1]
        spec = template_spec(sheet, grid)
        assert spec is not None, sheet
        mine, truth = execute(spec, grid), execute(table.spec, grid)
        assert (mine.rows, mine.constants) == (truth.rows, truth.constants), sheet
        assert [(u.locator, u.use) for u in mine.cell_use] == [(u.locator, u.use) for u in truth.cell_use], sheet
        region = Region(id=grid.region_id, kind="table", where=table.where, table_kind=table.kind)
        mapped = map_by_rule(grid, region, filename=template.name, document_role="client_template")
        assert mapped is not None and mapped.rule == f"template/{RULES}" and mapped.spec == spec


def test_template_spec_refuses_a_sheet_whose_header_is_not_the_templates():
    template = synthetic.template_workbook()
    grid = synthetic.truth_grid(template, "template-pk_individual")
    assert template_spec("PK_Summary", grid) is None
    assert template_spec("Notes", grid) is None
    renamed = RegionGrid.from_rows([["study", "treatment"], ["EXA-1", "TEST"]])
    assert template_spec("Studies", renamed) is None


def test_a_fourth_caption_line_is_cited_by_no_constant_and_the_table_is_still_mapped():
    """A Cite names context lines 1 to 3: a caption of four lines leaves the fourth uncited, never the table unmapped."""
    rows = [["Time (h)", "Conc (ng/mL)"], [0.5, 2.5], [1, 3.5], [2, 1.5]]
    grid = RegionGrid.from_rows(rows, caption=["Exampleamide", "plasma", "concentrations", "Study 230-77, 50 mg"])
    region = Region(id=grid.region_id, kind="table", where="s:'T'!A5:B8", table_kind="pk_summary")
    mapped = map_by_rule(grid, region, filename="listing.xlsx", drug=synthetic.DRUG)
    assert mapped is not None
    assert all(c.cite.near is None or c.cite.line <= 3 for c in mapped.spec.constants)
    assert [r.value for r in execute(mapped.spec, grid).rows] == [2.5, 3.5, 1.5]


@pytest.mark.parametrize(("caption", "rows"), [
    ("Study 230-23: plasma Exampleamide (ng/mL) after single doses of 10-30 mg, pooled",
     [["Time (h)", "Conc (ng/mL)"], [0.5, 2.5], [1, 3.5], [2, 1.5]]),
    ("Studie 230-23: Exampleamide im Plasma (ng/mL) nach 1.000 mg",
     [["Zeit (h)", "Konz (ng/mL)"], ["0,5", "2,5"], ["1", "3,25"], ["2", "1,5"]]),
])
def test_the_rules_leave_out_a_dose_written_as_a_range_or_ambiguously(caption, rows):
    """No model involved: a range "10-30 mg" states no dose of 30 mg, and "1.000 mg" under decimal commas is no dose of
    1 mg. The rules leave the dose out with a note; the table is still read."""
    grid = RegionGrid.from_rows(rows, caption=[caption])
    region = Region(id=grid.region_id, kind="table", where="s:'T'!A2:B5", table_kind="pk_summary")
    mapped = map_by_rule(grid, region, filename="listing.xlsx", drug=synthetic.DRUG)
    assert mapped is not None and all(c.field != "dose" for c in mapped.spec.constants)
    assert any(n.startswith("dose ") and "range or a list" in n for n in mapped.notes)
    result = execute(mapped.spec, grid)
    assert "dose" not in {c.field for c in result.constants} and len(result.rows) == 3
