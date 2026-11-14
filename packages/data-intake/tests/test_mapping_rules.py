"""D3: rules before the LLM (contracts §6.2, §8.5). Today's no-AI reading (`sheet_form.suggest`) as a v2 spec reads
what today's recipe reads, one region at a time; a title cell becomes a `near` cite; no value `suggest` assumes without
a cell reaches the spec; a filled client-data template is read exactly. Software test data (the made-up Exampleamide),
never observed data."""

from __future__ import annotations

import re
from datetime import date, datetime

import pytest
from openpyxl.utils import get_column_letter

from modeler_intake import fields, synthetic
from modeler_intake.anchors import SheetCell, format_locator
from modeler_intake.grid import SheetGrid, as_text, read_workbook_bytes
from modeler_intake.mapping.execute import execute
from modeler_intake.mapping.fingerprint import layout_fingerprint
from modeler_intake.mapping.reading import pattern_problem
from modeler_intake.mapping.rules import ARM_SHAPE, RULES, SHAPES, from_sheet_form, map_by_rule, template_spec
from modeler_intake.mapping.validate import validate_spec
from modeler_intake.mapping_spec import Cite, ExtractResult
from modeler_intake.reading_eval import CASES, Case, workbook
from modeler_intake.recipe_review import RecipeProposal, review_proposal
from modeler_intake.sheet_form import _APPARATUS, _BATCH, _MEDIUM, _STUDY_ID, suggest, to_proposal
from modeler_intake.source import parse_document, region_grid
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
    means = [r for r in read.rows if r.statistic == "arithmetic_mean"]
    assert [r.value for r in means] == [None, 1.12, 2.35, 3.1, 2.21, 0.95]
    # the below-LLOQ tokens are the rule's vocabulary, not the tokens the subjects' columns hold: the Mean column's
    # "BLQ" is a mean below the LLOQ (the footnote's), not an unparseable cell
    assert (means[0].censored, means[0].lloq, means[0].locator) == (True, 0.2, "s:'Fasting'!B22")
    assert read.findings == ()
    # the drug's name is not the metabolite's: the table states "Exampleamide-M1", and that is the analyte read
    assert {c.field: c.value for c in read.constants}["analyte"] == synthetic.METABOLITE


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


# --- one layout, one spec: a rule spec holds no value of its own table (seam finding SEAM-2) -------------------------------


def _parsed(file: synthetic.SyntheticFile, *where: str) -> list[tuple[RegionGrid, Region]]:
    """The file's table regions at `where`, as D2 parses and locates them (the seam the rules are run on)."""
    doc = parse_document(file.data, file.name)
    by_where = {r.where: r for r in doc.regions if r.kind == "table"}
    return [(region_grid(doc, by_where[w].id), by_where[w]) for w in where]


def _no_value_of_the_table(spec, result: ExtractResult) -> None:
    """Every pattern of a rule spec is one of the rules' fixed shapes (the same for every table), and none writes a
    name this table states: a pattern says where and in what shape, never what."""
    for constant in spec.constants:
        assert constant.pattern is None or constant.pattern in SHAPES[constant.field], constant
    stated = [str(c.value) for c in result.constants if c.field in ("study_id", "treatment", "analyte", "product", "batch")]
    assert stated
    for pattern in {c.pattern for c in spec.constants if c.pattern is not None}:
        for name in stated:
            assert name.lower() not in pattern.lower() and re.escape(name).lower() not in pattern.lower(), (pattern, name)


def test_two_sheets_of_one_layout_map_by_rule_to_one_spec_and_each_reads_its_own_title():
    """The Fasting and the Fed sheet share one layout fingerprint, so one mapping id: the rules must give both ONE
    spec (the study id cited by its shape, never written into the pattern; the no-sample tokens the rule's own list,
    not the tokens one of the sheets happens to hold), or the cache gains a version on every run."""
    messy = synthetic.messy_workbook()
    (fasting, r1), (fed, r2) = _parsed(messy, "s:'Fasting'!A2:G14", "s:'Fed'!A2:G14")
    assert layout_fingerprint(fasting) == layout_fingerprint(fed)
    first = map_by_rule(fasting, r1, filename=messy.name, drug=synthetic.DRUG)
    second = map_by_rule(fed, r2, filename=messy.name, drug=synthetic.DRUG)
    assert first.spec == second.spec and first.rule == second.rule
    read = [execute(first.spec, grid) for grid in (fasting, fed)]
    for result in read:
        _no_value_of_the_table(first.spec, result)
    constants = [{c.field: c.value for c in result.constants} for result in read]
    assert [(c["study_id"], c["dose"], c["food_state"], c["analyte"]) for c in constants] == [
        ("230-23", 50.0, "fasted", synthetic.DRUG), ("231-24", 100.0, "fed", synthetic.DRUG)]
    assert [{r.labels["study"] for r in result.rows} for result in read] == [{"230-23"}, {"231-24"}]
    # the Fasting sheet's "NS" is still no sample, and the same numbers are counted on both sheets
    assert [u.rule for u in read[0].cell_use if u.use == "missing"] == ["missing_token:NS"]
    assert [sum(u.use == "unaccounted" and u.numeric for u in result.cell_use) for result in read] == [21, 21]


def test_every_shape_is_a_pattern_the_validator_runs_and_reads_what_todays_reader_reads():
    """A shape is today's reader of the name written flat: `pattern_problem` passes it (it is run on any table of the
    layout), it has one group, and on a title it reads the token `sheet_form`'s own reader finds, when that token
    stands whole (the literal pattern it replaces never read a part of a longer token either)."""
    for name, shapes in SHAPES.items():
        assert fields.field(name) is not None and fields.field(name).value in ("name", "text")
        for shape in shapes:
            assert pattern_problem(shape) is None and re.compile(shape).groups == 1, (name, shape)
    titles = ["Study 230-23, 50 mg, fasted", "Study EX-201, 10 mg tablet, fasted", "Table 14.2.1 Mean (SD) plasma concentrations",
              "Table 6. Study 230-26, Cohort 1 (10 mg): Exampleamide plasma concentrations, mean (SD)", "ABC123-45/678 and X-01",
              "230-23-REF", "Study 230-23-A, 50 mg", "12-34-56-78", "CSR_Table_14-2-1", "Protocol ABCDE-12", "study 1234/56",
              "X-1", "AB-123-45", "t1/2", "Exampleamide IR tablet, batch L2301 (% dissolved)", "Lot no. 12A/45.",
              "batch number: X-9_1", "Batch# 77B", "batches A1 and B2", "lots of water", "Lot: 22.5.A",
              "Dissolution of Test tablets 10 mg, batch B123, 900 mL pH 6.8 phosphate buffer, USP apparatus 2 (paddle), 50 rpm",
              "Medium: HCl buffer pH 1.2", "0.1 N HCl, 900 mL", "FaSSIF", "phosphate-buffered saline", "USP II, 75 rpm",
              "USP apparatus type 1 (basket)", "paddle, 50 rpm"]

    def reads(shape: str, text: str) -> list[str]:
        return [m.group(1) for m in re.finditer(shape, text)]

    def whole(found: re.Match, group: int) -> bool:
        text, (start, end) = found.string, found.span(group)
        return not re.match(r"[\w-]", text[start - 1:start] or " ") and not re.match(r"[\w-]", text[end:end + 1] or " ")

    for text in titles:
        assert reads(SHAPES["study_id"][-1], text) == [m.group(1) for m in _STUDY_ID.finditer(text) if whole(m, 1)], text
        assert reads(SHAPES["batch"][0], text) == [m.group(1) for m in _BATCH.finditer(text) if whole(m, 1)], text
        # one medium and one apparatus per title: the first the legacy reader finds, where the title names one whole
        for name, legacy, group in (("medium", _MEDIUM, 1), ("apparatus", _APPARATUS, 0)):
            first = legacy.search(text)
            assert reads(SHAPES[name][0], text) == ([first.group(group)] if first and whole(first, group) else []), (name, text)
    assert reads(SHAPES["study_id"][-1], "Study 230-23-A, 50 mg") == [] and reads(SHAPES["batch"][0], "batches A1 and B2") == []
    assert reads(SHAPES["medium"][0], "phosphate-buffered saline") == []
    # the word that announces a study picks it among the tokens of its shape; a range of doses is no second study
    ranged = "Study 230-23 (protocol EX-201): plasma Exampleamide (ng/mL) after single doses of 10-30 mg, pooled"
    assert [reads(shape, ranged) for shape in SHAPES["study_id"]] == [["230-23"], ["230-23", "EX-201"],
                                                                      ["230-23", "EX-201", "10-30"]]
    # an analyte's shape reads a name, never the statistic or the matrix a title of another table writes at its place
    analytes = {"Exampleamide plasma concentrations (ng/mL)": 0, "Mean plasma concentrations of Exampleamide-M1": 1,
                "Plasma Exampleamide concentrations (ng/mL)": 2, "Study 230-23: Exampleamide in human plasma": 3,
                "Exampleamide-M1 concentrations in plasma": 4}
    for text, index in analytes.items():
        read = [reads(shape, text) for shape in SHAPES["analyte"]]
        named = [i for i, found in enumerate(read) if found in (["Exampleamide"], ["Exampleamide-M1"])]
        assert named[0] == index, (text, read)                          # the first shape that reads the name there
    for text in ("Mean plasma concentrations", "Total plasma concentrations in the fed state", "Median serum levels"):
        assert [reads(shape, text) for shape in SHAPES["analyte"]] == [[], [], [], [], []], text
    assert reads(SHAPES["product"][0], "Exampleamide IR tablet, batch L2301 (% dissolved)") == ["Exampleamide IR tablet"]


@pytest.mark.parametrize(("file", "where"), [
    (synthetic.pdf_report(unruled_table=False), "p:2/t:1"), (synthetic.pdf_report(unruled_table=False), "p:4/t:1"),
    (synthetic.word_report(), "d:t:1"), (synthetic.delimited(), "s:'concentrations'!A2:C10"),
    (synthetic.messy_workbook(), "s:'Dissolution'!A3:G9"),
], ids=["pdf-table5", "pdf-table6", "word-table1", "delimited", "dissolution"])
def test_no_rule_spec_writes_a_name_of_its_own_table_into_a_pattern(file, where):
    ((grid, region),) = _parsed(file, where)
    mapped = map_by_rule(grid, region, filename=file.name, drug=synthetic.DRUG)
    result = execute(mapped.spec, grid)
    assert result.rows
    _no_value_of_the_table(mapped.spec, result)
    # every name the rules read before is still read, at its cite
    named = {c.field: c.value for c in result.constants if isinstance(c.value, str)}
    if where == "s:'Dissolution'!A3:G9":
        assert named["batch"] == "L2301" and {r.conditions["medium"] for r in result.rows} == {"HCl"}
    else:
        assert named["analyte"] == synthetic.DRUG and named["study_id"].startswith("230-2")


@pytest.mark.parametrize(("caption", "study", "analyte"), [
    ("Study 230-23 (protocol EX-201): Exampleamide plasma concentrations", "230-23", "Exampleamide"),
    ("230-23: Exampleamide in plasma", "230-23", "Exampleamide"),
    ("Exampleamide concentrations in plasma, Study 230-23", "230-23", "Exampleamide"),
    ("Study 230-23: N-desmethyl-Exampleamide plasma concentrations", "230-23", "N-desmethyl-Exampleamide"),
    ("Study 230-23-A: Exampleamide plasma concentrations", None, "Exampleamide"),       # "230-23" is a part of the id
    ("Study 230-23: mean plasma concentrations", "230-23", None),                       # no analyte is written
    ("Study 230-23 Exampleamide, plasma", "230-23", None),                              # no shape reads the name there
])
def test_a_name_is_read_by_its_shape_or_left_out_with_a_note_never_written_into_the_spec(caption, study, analyte):
    grid = RegionGrid.from_rows([["Time (h)", "Conc (ng/mL)"], [0.5, 2.5], [1, 3.5], [2, 1.5]], caption=[caption])
    region = Region(id=grid.region_id, kind="table", where="s:'T'!A2:B5", table_kind="pk_summary")
    mapped = map_by_rule(grid, region, filename="listing.xlsx", drug=synthetic.DRUG)
    result = execute(mapped.spec, grid)
    constants = {c.field: c.value for c in result.constants}
    assert (constants.get("study_id"), constants.get("analyte")) == (study, analyte)
    for constant in mapped.spec.constants:
        assert constant.pattern is None or constant.pattern in SHAPES[constant.field]
    for name, read in (("study_id", study), ("analyte", analyte)):
        assert (read is None) == any(n.startswith(f"{name} ") and "left out of the spec" in n for n in mapped.notes), mapped.notes
    assert [r.value for r in result.rows] == [2.5, 3.5, 1.5]


def test_a_dissolution_table_reads_its_product_batch_medium_and_apparatus_by_shape():
    """The brief's test product is cited where the title names it before its batch; the batch, the medium and the
    apparatus by today's readers' shapes. Another batch of the same layout gets the same spec and reads its own."""
    rows = [["Time (min)", "V1", "V2", "V3"], [5, 20.1, 22.3, 19.8], [10, 45.2, 44.1, 46.0], [15, 70.3, 69.9, 71.2]]
    products = [{"name": "Exampleamide IR tablet", "role": "TEST"}]
    specs, read = [], []
    for batch in ("L2301", "L2417"):
        grid = RegionGrid.from_rows(rows, caption=[f"Exampleamide IR tablet, batch {batch} (% dissolved)",
                                                   "900 mL phosphate buffer pH 6.8, USP apparatus 2 (paddle), 50 rpm"])
        region = Region(id=grid.region_id, kind="table", where="s:'D'!A3:D6", table_kind="dissolution")
        mapped = map_by_rule(grid, region, filename="Exampleamide_test_dissolution.xlsx", drug=synthetic.DRUG, products=products)
        specs.append(mapped.spec)
        result = execute(mapped.spec, grid)
        _no_value_of_the_table(mapped.spec, result)
        read.append(({c.field: c.value for c in result.constants if isinstance(c.value, str)}, result.rows[0].conditions))
    assert specs[0] == specs[1]
    # (the role "test" stands in the file's name only, in no cell: it is not in the spec)
    assert [names for names, _c in read] == [{"product": "Exampleamide IR tablet", "batch": "L2301"},
                                             {"product": "Exampleamide IR tablet", "batch": "L2417"}]
    assert read[0][1] == {"medium": "phosphate", "apparatus": "USP apparatus 2", "ph": "6.8", "rpm": "50", "volume_ml": "900"}


# --- a spread or a count is never read as a value (seam finding SEAM-3) ------------------------------------------------------


def test_the_rules_never_read_a_spread_or_a_count_column_as_concentrations():
    """The metabolite's summary table (Time (h) | Mean | SE | n): today's form takes the SE column for a subject's
    values. The rules read the mean profile only; the SE and n cells stay unaccounted and counted (§6.2), never
    concentrations; and the analyte is the one the table states (the metabolite), not the drug."""
    messy = synthetic.messy_workbook()
    ((grid, region),) = _parsed(messy, "s:'Fasting'!A21:D27")
    assert [grid.cell(1, c).text for c in range(1, 5)] == ["Time (h)", "Mean", "SE", "n"]
    mapped = map_by_rule(grid, region, filename=messy.name, drug=synthetic.DRUG)
    spec = mapped.spec
    assert [(c.column, c.role, c.statistic) for c in spec.columns] == [(1, "time", None), (2, "value", "arithmetic_mean")]
    assert spec.kind == "pk_summary"
    assert [f for f in validate_spec(spec, grid) if f.severity == "error"] == []
    result = execute(spec, grid)
    assert {r.locator.split("!")[1][0] for r in result.rows} == {"B"}                 # every value is a Mean cell
    assert [(r.value, r.statistic) for r in result.rows if r.value is not None] == [
        (1.12, "arithmetic_mean"), (2.35, "arithmetic_mean"), (3.1, "arithmetic_mean"), (2.21, "arithmetic_mean"),
        (0.95, "arithmetic_mean")]
    se_and_n = {u.locator: u.use for u in result.cell_use if u.numeric and u.locator.split("!")[1][0] in "CD"}
    assert len(se_and_n) == 11 and set(se_and_n.values()) == {"unaccounted"}          # 5 SE and 6 n: counted, not read
    assert any("SE" in note and "not read" in note for note in mapped.notes)
    constants = {c.field: c.value for c in result.constants}
    assert (constants["study_id"], constants["analyte"], constants["lloq"]) == ("230-23", synthetic.METABOLITE, 0.2)
    assert {r.labels["analyte"] for r in result.rows} == {synthetic.METABOLITE}
    _no_value_of_the_table(spec, result)


@pytest.mark.parametrize("subjects", [("S01",), ("S01", "S02")])
def test_a_subjects_column_stays_a_subjects_column_when_the_spread_next_to_it_is_left_out(subjects):
    """Time (h) | S01 | SE: the SE column is left out, and S01 is still read as the subject S01 (individual values),
    not as values with no subject."""
    rows = [["Time (h)", *subjects, "SE"], *([t, *([2.5 * t] * len(subjects)), 0.3] for t in (0.5, 1, 2))]
    grid = RegionGrid.from_rows(rows, caption=["Study 230-77: Exampleamide plasma concentrations (ng/mL)"])
    region = Region(id=grid.region_id, kind="table", where="s:'T'!A2:D5", table_kind="pk_individual")
    mapped = map_by_rule(grid, region, filename="listing.xlsx", drug=synthetic.DRUG)
    result = execute(mapped.spec, grid)
    assert sorted({(r.labels.get("subject"), r.statistic) for r in result.rows}) == [(s, "individual") for s in subjects]
    assert len(result.rows) == 3 * len(subjects) and all(r.value != 0.3 for r in result.rows)
    assert sum(u.use == "unaccounted" and u.numeric for u in result.cell_use) == 3


@pytest.mark.parametrize("header", [["Time (h)", "SE", "CV%"], ["Time (h)", "SEM", "n"], ["Time (h)", "SD", "N"]])
def test_a_table_whose_only_numbers_are_spreads_and_counts_has_no_rule(header):
    """Today's form takes two such columns for two subjects: with no value column left, no rule maps the table (it
    goes on to the LLM or a person), and nothing of it is read as a concentration."""
    grid = RegionGrid.from_rows([header, [0.5, 0.21, 6], [1, 0.41, 6], [2, 0.38, 5]],
                                caption=["Study 230-77: Exampleamide plasma concentrations"])
    region = Region(id=grid.region_id, kind="table", where="s:'T'!A2:C5", table_kind="pk_summary")
    assert map_by_rule(grid, region, filename="listing.xlsx", drug=synthetic.DRUG) is None


# --- the arm a caption names (seam finding SEAM-4) ---------------------------------------------------------------------------


def test_two_cohort_tables_of_one_study_read_two_arms_from_their_captions():
    """The report's Table 6 ("Study 230-26, Cohort 1 (10 mg)") and Table 7 ("... Cohort 2 (30 mg)"): one layout, one
    spec, and each lands on its own arm. With no arm read, both cohorts' means stand on one arm-less profile of the
    study and every time is a conflict a person would settle by discarding a cohort."""
    report = synthetic.pdf_report(unruled_table=False)
    (six, r6), (seven, r7) = _parsed(report, "p:4/t:1", "p:5/t:1")
    first = map_by_rule(six, r6, filename=report.name, drug=synthetic.DRUG)
    second = map_by_rule(seven, r7, filename=report.name, drug=synthetic.DRUG)
    assert layout_fingerprint(six) == layout_fingerprint(seven) and first.spec == second.spec
    (treatment,) = [c for c in first.spec.constants if c.field == "treatment"]
    assert treatment.cite == Cite(near="caption", line=1) and treatment.pattern == ARM_SHAPE
    read = [execute(first.spec, grid) for grid in (six, seven)]
    assert [{r.labels["arm"] for r in result.rows} for result in read] == [{"Cohort 1"}, {"Cohort 2"}]
    assert [{r.labels["study"] for r in result.rows} for result in read] == [{"230-26"}, {"230-26"}]
    constants = [{c.field: c.value for c in result.constants} for result in read]
    assert [(c["study_id"], c["treatment"], c["dose"]) for c in constants] == [("230-26", "Cohort 1", 10.0),
                                                                              ("230-26", "Cohort 2", 30.0)]
    for result in read:
        _no_value_of_the_table(first.spec, result)
    # the arm is read where the truth's approved spec reads it: the same name at the same place
    for table_id, grid, result in (("report-table6", six, read[0]), ("report-table7", seven, read[1])):
        truth = execute(next(t.spec for t in report.tables if t.id == table_id), grid)
        assert [(c.value, c.locator) for c in result.constants if c.field == "treatment"] == [
            (c.value, c.locator) for c in truth.constants if c.field == "treatment"]
        assert [r.label_locators["arm"] for r in result.rows] == [r.label_locators["arm"] for r in truth.rows]


def _summary(caption: str, above: list[list[str]] | None = None) -> tuple[RegionGrid, Region]:
    rows = [["Time (h)", "Mean (ng/mL)", "SD"], [0.5, 3.2, 0.8], [1, 5.8, 1.2], [2, 7.1, 1.5]]
    grid = RegionGrid.from_rows(rows, caption=[caption], above=above or [])
    return grid, Region(id=grid.region_id, kind="table", where="s:'T'!A2:C5", table_kind="pk_summary")


@pytest.mark.parametrize(("caption", "above", "arm", "cite"), [
    ("Study 230-26, Treatment A (fasted): Exampleamide plasma concentrations", None, "Treatment A", Cite(near="caption", line=1)),
    ("Study 230-26, Arm B: Exampleamide plasma concentrations", None, "Arm B", Cite(near="caption", line=1)),
    ("Study 230-26, GROUP 2, 30 mg: Exampleamide plasma concentrations", None, "GROUP 2", Cite(near="caption", line=1)),
    ("Exampleamide plasma concentrations, mean (SD)", [["Study 230-26, Cohort 3"]], "Cohort 3", Cite(near="above", line=1)),
])
def test_the_rules_read_the_arm_a_caption_or_a_line_above_names(caption, above, arm, cite):
    grid, region = _summary(caption, above)
    mapped = map_by_rule(grid, region, filename="report.xlsx", drug=synthetic.DRUG)
    (treatment,) = [c for c in mapped.spec.constants if c.field == "treatment"]
    assert (treatment.cite, treatment.pattern) == (cite, ARM_SHAPE)
    result = execute(mapped.spec, grid)
    assert {r.labels["arm"] for r in result.rows} == {arm}
    assert [c.value for c in result.constants if c.field == "treatment"] == [arm]


@pytest.mark.parametrize("caption", [
    "Study 230-26: Exampleamide plasma concentrations, mean (SD)",                  # no arm stated
    "Study 230-26, Cohorts 1 and 2 pooled: Exampleamide plasma concentrations",     # two arms, pooled
    "Study 230-26, Cohort 1 and Cohort 2: Exampleamide plasma concentrations",
    "Study 230-26, Cohort 1-3: Exampleamide plasma concentrations",                 # a range of arms
    "Study 230-26, Cohort 1 & 2: Exampleamide plasma concentrations",
    "Study 230-26: Exampleamide plasma concentrations by treatment group",          # the words, no name
    "Study 230-26: Exampleamide plasma concentrations after treatment a week later",
    "Study 230-26: Exampleamide plasma concentrations, group mean",
    "Study 230-26, Period 2, Treatment T: Exampleamide plasma concentrations",      # two names: which is the arm?
])
def test_no_arm_is_guessed_where_the_caption_states_none_or_more_than_one(caption):
    grid, region = _summary(caption)
    mapped = map_by_rule(grid, region, filename="report.xlsx", drug=synthetic.DRUG)
    assert mapped is not None and "treatment" not in {c.field for c in mapped.spec.constants}
    result = execute(mapped.spec, grid)
    assert all("arm" not in r.labels for r in result.rows) and len(result.rows) == 3


def test_the_arm_shape_is_built_on_the_field_registrys_cue_for_treatment():
    """The words that announce an arm are the registry's (`fields`: arm, treatment, cohort, group, period), never a
    second list: the shape reads one of them and the short name after it."""
    words = re.findall(r"\\b([a-z]+)s\?\\b", fields.FIELDS["treatment"].cue)
    assert "|".join(rf"\b{w}s?\b" for w in words) == fields.FIELDS["treatment"].cue and len(words) == 5
    assert pattern_problem(ARM_SHAPE) is None and re.compile(ARM_SHAPE).groups == 1
    for word in words:
        assert [m.group(1) for m in re.finditer(ARM_SHAPE, f"Study 230-26, {word.title()} 2 (30 mg)")] == [f"{word.title()} 2"]
