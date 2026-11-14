"""The synthetic truth located exactly, in every format (contracts §8.4, §10, §13 "D2 reproduces these truth
conventions"): every truth table of every shared synthetic file is a region D2 finds, with the truth's range and region
id (a PDF table's id hashed from its page, box and first row); its grid is the truth's grid (cell texts, types and
values, locators by identity, merge origins, caption and context lines); and every locator of every truth value, the
value's own cell and every cell it is read with, is a cell of a region D2 finds or of its context."""

from __future__ import annotations

import pytest

from modeler_intake import synthetic
from modeler_intake.anchors import parse_locator, same_place
from modeler_intake.source import paragraphs, parse_document, region_grid

pytestmark = pytest.mark.req("T-47")


def _files() -> tuple[synthetic.SyntheticFile, ...]:
    return (*synthetic.delivery(), synthetic.pdf_report(), synthetic.scanned_pdf(), synthetic.template_workbook(),
            synthetic.delimited(sep="\t", decimal_comma=False, encoding="utf-16"),
            synthetic.delimited(sep=",", decimal_comma=False, encoding="utf-8"))


def _ids(files) -> list[str]:
    return [f"{f.name}-{k}" for k, f in enumerate(files)]


FILES = _files()


def _same(a: str, b: str) -> bool:
    return same_place(parse_locator(a), parse_locator(b))


def _line_texts(lines) -> list[str]:
    return [" | ".join(c.text for c in line) for line in lines]


@pytest.mark.parametrize("file", FILES, ids=_ids(FILES))
def test_every_truth_table_is_a_region_whose_grid_is_the_truths(file):
    doc = parse_document(file.data, file.name)
    assert doc.state == ("partly_read" if file.name == "scanned.pdf" else "read"), (file.name, doc.reason)
    regions = {r.id: r for r in doc.regions}
    for table in file.tables:
        truth = synthetic.truth_grid(file, table.id)
        region = regions.get(truth.region_id)
        assert region is not None and region.kind == "table" and region.where == table.where, table.id
        grid = region_grid(doc, region.id)
        assert (grid.region_id, grid.n_rows, grid.n_cols) == (truth.region_id, truth.n_rows, truth.n_cols), table.id
        assert (grid.file_sha256, grid.parser, grid.parser_version) == (doc.file_sha256, doc.parser, doc.parser_version)
        assert set(grid.cells) == set(truth.cells), table.id
        for place, cell in truth.cells.items():
            mine = grid.cells[place]
            assert (mine.text, mine.type, mine.value, mine.number_format) == \
                (cell.text, cell.type, cell.value, cell.number_format), (table.id, place)
            assert _same(mine.locator, cell.locator), (table.id, place)
            assert (mine.merged_from is None) == (cell.merged_from is None), (table.id, place)
            if cell.merged_from is not None:
                assert _same(mine.merged_from, cell.merged_from), (table.id, place)
        assert [[grid.cell(r, c).text for c in range(1, grid.n_cols + 1)] for r in range(1, grid.n_rows + 1)] == \
            [[text if not truth.cell(r, c).merged_from else truth.cell(r, c).text for c, text in enumerate(row, 1)]
             for r, row in enumerate(table.rows, 1)], table.id
        assert [c.text for c in grid.caption] == list(table.caption) == [c.text for c in truth.caption], table.id
        assert _line_texts(grid.above) == list(table.above) == _line_texts(truth.above), table.id
        assert _line_texts(grid.below) == list(table.below) == _line_texts(truth.below), table.id
        for mine, cell in zip((*grid.caption, *(c for line in (*grid.above, *grid.below) for c in line)),
                              (*truth.caption, *(c for line in (*truth.above, *truth.below) for c in line)), strict=True):
            assert _same(mine.locator, cell.locator), (table.id, cell.text)


@pytest.mark.parametrize("file", FILES, ids=_ids(FILES))
def test_every_locator_of_every_truth_value_is_a_cell_of_a_region_found(file):
    doc = parse_document(file.data, file.name)
    places: dict[str, list[str]] = {}                 # region id -> the locators of its cells and context lines
    for region in doc.regions:
        if region.kind == "table":
            grid = region_grid(doc, region.id)
            places[region.id] = [c.locator for c in (*grid.cells.values(), *grid.caption,
                                                     *(c for line in (*grid.above, *grid.below) for c in line))]
    prose = [p for r in doc.regions if r.kind == "prose" for p in paragraphs(doc, r.id)]
    for value in file.values:
        if value.table == "":                         # a prose value: a span inside a prose region's paragraph
            span = parse_locator(value.locator)
            holder = [p for p in prose if _inside(span, p.locator)]
            assert len(holder) == 1, (file.name, value.field, value.locator)
            for _role, locator in value.locators:
                assert any(_inside(parse_locator(locator), p.locator) for p in prose), (file.name, value.field, locator)
            continue
        truth_id = synthetic.truth_grid(file, value.table).region_id
        mine = places[truth_id]
        for role, locator in (("value", value.locator), *value.locators):
            assert any(_same(found, locator) for found in mine), (file.name, value.table, value.field, role, locator)
            assert region_grid(doc, truth_id).anchor_of(next(f for f in mine if _same(f, locator)))


def _inside(span, paragraph_range: str) -> bool:
    """Whether a span locator lies inside a prose paragraph's range (a PDF word range, a Word or text paragraph)."""
    if span.kind == "pdf_span":
        page, words = paragraph_range.removeprefix("p:").split("/w:")
        first, last = (int(v) for v in words.split("-"))
        return int(page) == span.page and first <= span.first_word <= span.last_word <= last
    number = span.paragraph if span.kind == "docx_span" else span.line
    first, last = (int(v) for v in paragraph_range.split(":")[-1].split("-"))
    return first <= number <= last


@pytest.mark.parametrize("file", FILES, ids=_ids(FILES))
def test_the_numbers_outside_every_region_and_context_are_the_truths_and_nothing_else(file):
    doc = parse_document(file.data, file.name)
    free = sorted(o.where for o in doc.outside if o.numeric and not o.furniture and o.region is None)
    assert free == sorted(file.outside), file.name
    for item in doc.outside:                          # an outside item names a region only as one of its context lines
        if item.region is not None:
            grid = region_grid(doc, item.region)
            assert any(c.locator == item.where for line in (*grid.above, *grid.below) for c in line), item.where
