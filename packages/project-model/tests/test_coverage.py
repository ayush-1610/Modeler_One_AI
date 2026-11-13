"""The coverage audit (plan G2, contracts §6.4): every cell with a number of a mapped table is used or excluded by a
stated rule, every unread table counts whole, prose is listed, figures are excluded by the rule, outside numbers are
counted unless accepted, and an unsupported file is a row with its reason."""

from __future__ import annotations

import hashlib
from functools import lru_cache

import pytest

from modeler_intake import synthetic
from modeler_intake.mapping_spec import CellUse, ExtractResult
from modeler_intake.source_model import AnchorProblem, OutsideItem, Page, Region, RegionGrid, SourceDocument, has_number
from modeler_project.coverage import MAX_LOCATORS, file_coverage, outcome_from, silent_loss, values_unassigned
from modeler_project.intake_fixtures import write_truth
from modeler_project.intake_records import FileRecord, RegionDecision, RegionOutcome
from modeler_project.intake_rules import rules
from modeler_project.intake_store import IntakeStore
from modeler_project.ledger_models import EntityRef, Fact, MappingUse
from modeler_project.ledger_view import LedgerView, is_spread_fact
from modeler_project.store import FileProjectStore
from modeler_project.workspace import Workspace

pytestmark = pytest.mark.req("T-47", "T-42")

AT = "2026-11-13T09:00:00.000Z"
MAPPING = MappingUse(mapping_id="mp-0123456789ab", version=1)


@lru_cache(maxsize=1)
def _messy() -> synthetic.SyntheticFile:
    return synthetic.messy_workbook()


def _sha(file: synthetic.SyntheticFile) -> str:
    return hashlib.sha256(file.data).hexdigest()


def _record(sha: str, name: str = "messy-delivery.xlsx") -> FileRecord:
    return FileRecord(file_id=f"fl-{sha[:12]}", sha256=sha, name=name, size_bytes=1, delivery="dl-1", by="code", at=AT)


def _numeric(grid: RegionGrid) -> int:
    return sum(1 for c in grid.cells.values() if has_number(c.text) and c.merged_from is None)


def _region(grid: RegionGrid, where: str = "s:'T'!A1:B2", kind: str = "table") -> Region:
    return Region(id=grid.region_id, kind=kind, where=where, n_rows=grid.n_rows, n_cols=grid.n_cols,  # type: ignore[arg-type]
                  numeric_cells=_numeric(grid))


def _result(grid: RegionGrid, *, header_rows: int = 1, unaccounted: tuple[str, ...] = (), cited: tuple[str, ...] = (),
            excluded: tuple[str, ...] = (), rule: str = "row_rule:cv ?%") -> ExtractResult:
    """What the mapper's executor gives for a grid: every non-empty cell with its use (a merged copy never numeric); an
    excluded cell names the rule that set it aside."""
    uses = []
    for (row, column), cell in sorted(grid.cells.items()):
        numeric = has_number(cell.text) and cell.merged_from is None
        use = ("unaccounted" if cell.locator in unaccounted else "excluded" if cell.locator in excluded
               else ("time" if row <= header_rows else "value") if numeric else "header")
        uses.append(CellUse(row=row, column=column, locator=cell.locator, numeric=numeric, use=use,  # type: ignore[arg-type]
                            rule=rule if use == "excluded" else ""))
    return ExtractResult(rows=(), constants=(), cell_use=tuple(uses), cited=cited, findings=())


def _doc(sha: str, regions: tuple[Region, ...], outside: tuple[OutsideItem, ...] = (), *, state: str = "read",
         reason: str = "", pages: tuple[Page, ...] = ()) -> SourceDocument:
    return SourceDocument(file_sha256=sha, name="messy-delivery.xlsx", size_bytes=1, format="xlsx", parser="workbook",
                          parser_version=synthetic.TRUTH_PARSER_VERSION, state=state, reason=reason,  # type: ignore[arg-type]
                          regions=regions, outside=outside, pages=pages)


def _decision(sha: str, regions: tuple[str, ...], scope: str = "regions", n: int = 1) -> RegionDecision:
    return RegionDecision(id=f"rd-{n}", file_sha256=sha, parser_version=synthetic.TRUTH_PARSER_VERSION, regions=regions,
                          scope=scope, why="a person read it: not data", by="u-1", at=AT)  # type: ignore[arg-type]


def test_a_fully_mapped_table_has_no_silent_loss():
    file = _messy()
    table = next(t for t in file.tables if t.id == "fasting-individual")
    grid = synthetic.truth_grid(file, table.id)
    region = _region(grid, table.where)
    outcome = outcome_from(region, _result(grid, header_rows=table.header_rows), state="mapped", mapping=MAPPING,
                           origin="cache")
    assert outcome.numeric_cells == region.numeric_cells > 40 and outcome.unaccounted_count == 0
    assert outcome.uses == {"time": 6, "value": region.numeric_cells - 6}
    coverage = file_coverage(_record(_sha(file)), _doc(_sha(file), (region,)), [outcome])
    summary = coverage.summary
    assert (summary.silent_loss, summary.cells_silent, summary.regions_mapped) == (0, 0, 1)
    assert summary.numeric_cells == summary.cells_used == region.numeric_cells
    assert coverage.regions[0].silent == () and coverage.regions[0].outcome == outcome


def test_one_unaccounted_cell_with_a_number_counts_one_and_is_named_by_its_locator():
    file = _messy()
    grid = synthetic.truth_grid(file, "summary-parameters")
    cell = grid.cell(2, 3)
    assert cell.text == "31.2 (4.1)"                       # a "mean (SD)" cell left unsplit: no cell_form on its column
    region = _region(grid)
    outcome = outcome_from(region, _result(grid, unaccounted=(cell.locator,)), state="mapped", mapping=MAPPING,
                           origin="rule")
    coverage = file_coverage(_record(_sha(file)), _doc(_sha(file), (region,)), [outcome])
    assert coverage.summary.silent_loss == coverage.summary.cells_silent == 1
    assert coverage.regions[0].silent == (cell.locator,) == outcome.unaccounted


def test_250_unaccounted_cells_count_250_and_name_200():
    grid = RegionGrid.from_rows([[f"{r}.{c} (x)" for c in range(10)] for r in range(25)])
    region = _region(grid)
    outcome = outcome_from(region, _result(grid, header_rows=0, unaccounted=tuple(c.locator for c in grid.cells.values())),
                           state="mapped", mapping=MAPPING, origin="llm")
    assert (outcome.unaccounted_count, len(outcome.unaccounted)) == (250, MAX_LOCATORS)
    coverage = file_coverage(_record("a" * 64), _doc("a" * 64, (region,)), [outcome])
    assert coverage.summary.silent_loss == 250 and coverage.regions[0].silent_count == 250
    assert len(coverage.regions[0].silent) == 200


def test_an_unread_table_counts_every_cell_with_a_number():
    file = _messy()
    grid = synthetic.truth_grid(file, "fasting-metabolite")
    region = _region(grid)
    unruled = Region(id="rg-00000000aa", kind="table_like_text", where="p:6/w:1-40", numeric_cells=7)
    unread = outcome_from(region, None, state="unread", reason="no rule or cached mapping fits; no model is configured")
    coverage = file_coverage(_record(_sha(file)), _doc(_sha(file), (region, unruled)), [unread])
    assert coverage.summary.silent_loss == region.numeric_cells + 7 and coverage.summary.regions_unread == 2
    assert coverage.summary.cells_silent == 0                # of mapped tables only
    assert coverage.regions[0].outcome.reason.startswith("no rule") and coverage.regions[1].silent_count == 7


def test_a_not_data_mapping_and_a_region_decision_exclude_with_their_reason():
    file = _messy()
    readme, other = (RegionGrid.from_rows([["About this file", "v 1.2"], ["Sheet", "2 rows"]], region_id=f"rg-{i:010d}")
                     for i in (1, 2))
    sha = _sha(file)
    first, second = _region(readme), _region(other)
    not_data = outcome_from(first, None, state="excluded", reason="not data: the template's README", mapping=MAPPING,
                            origin="cache")
    decision = _decision(sha, (second.id,))
    elsewhere = _decision("b" * 64, (first.id, second.id), n=2)          # another file's decision applies nowhere here
    coverage = file_coverage(_record(sha), _doc(sha, (first, second)), [not_data], [decision, elsewhere])
    assert coverage.summary.silent_loss == 0 and coverage.summary.regions_excluded == 2
    reasons = [r.outcome.reason for r in coverage.regions]
    assert reasons == ["not data: the template's README", "rd-1: a person read it: not data"]
    assert coverage.decisions == ("rd-1",)
    # without the decision, the second region is unread and its numbers are silent loss
    assert file_coverage(_record(sha), _doc(sha, (first, second)), [not_data]).summary.silent_loss == second.numeric_cells


def test_a_decision_overrides_a_mapped_outcome_and_excluded_cells_are_counted_as_excluded():
    grid = RegionGrid.from_rows([["Time", "Conc"], ["1", "10"], ["2", "CV 12%"]])
    region = _region(grid)
    cv = grid.cell(3, 2).locator
    outcome = outcome_from(region, _result(grid, excluded=(cv,)), state="mapped", mapping=MAPPING, origin="rule")
    coverage = file_coverage(_record("c" * 64), _doc("c" * 64, (region,)), [outcome])
    assert (coverage.summary.cells_used, coverage.summary.cells_excluded, coverage.summary.silent_loss) == (3, 1, 0)
    decided = file_coverage(_record("c" * 64), _doc("c" * 64, (region,)), [outcome], [_decision("c" * 64, (region.id,))])
    assert decided.regions[0].outcome.state == "excluded" and decided.summary.regions_mapped == 0


def test_a_figure_is_excluded_by_the_rule():
    figure = Region(id="rg-00000000ff", kind="figure", where="p:4/f:1", numeric_cells=3)
    coverage = file_coverage(_record("d" * 64), _doc("d" * 64, (figure,)), [])
    (only,) = coverage.regions
    assert only.outcome.state == "excluded" and coverage.summary.regions_excluded == 1 and coverage.summary.silent_loss == 0
    assert rules().coverage.excluded_by_rule["figure"] in only.outcome.reason
    # the rule is the rules file's: without it the figure is unread (still never counted: it is not a table)
    loaded = rules()
    copy = loaded.model_copy(update={"coverage": loaded.coverage.model_copy(update={"excluded_by_rule": {}})})
    without = file_coverage(_record("d" * 64), _doc("d" * 64, (figure,)), [], rules=copy)
    assert without.regions[0].outcome.state == "unread" and without.summary.silent_loss == 0


def test_unread_prose_is_listed_not_counted():
    prose = Region(id="rg-0000000abc", kind="prose", where="p:1/w:1-60", numeric_cells=5)
    coverage = file_coverage(_record("e" * 64), _doc("e" * 64, (prose,)), [
        outcome_from(prose, None, state="unread", reason="no model is configured: prose is read by A4-prose")])
    assert coverage.summary.regions_unread == 1 and coverage.summary.silent_loss == 0
    assert coverage.regions[0].region == prose and coverage.regions[0].silent_count == 0


def test_an_outside_number_counts_unless_furniture_cited_or_accepted():
    file = _messy()
    sha = _sha(file)
    grid = synthetic.truth_grid(file, "fasting-individual")
    region = _region(grid)
    lloq_line = grid.below[0][0].locator                       # the LLOQ footnote, a context line a constant cites
    (note,) = file.outside                                      # the workbook's outside number
    outside = (
        OutsideItem(where=note, text="Note: 3 subjects withdrew", numeric=True),
        OutsideItem(where=lloq_line, text="LLOQ = 0.5 ng/mL", numeric=True, region=region.id),
        OutsideItem(where="p:2/w:80-81@500.00,780.00,520.00,790.00", text="Page 2", numeric=True, furniture=True),
        OutsideItem(where="p:3/w:1-9@72.00,90.00,300.00,100.00", text="Assay run 7 of 9", numeric=True),
        OutsideItem(where="s:'Fasting'!A30", text="Prepared by the sponsor", numeric=False),
    )
    outcome = outcome_from(region, _result(grid, header_rows=2, cited=(lloq_line,)), state="mapped", mapping=MAPPING,
                           origin="cache")
    coverage = file_coverage(_record(sha), _doc(sha, (region,), outside), [outcome])
    assert coverage.summary.outside_items == 5 and coverage.summary.outside_numeric == 2
    assert coverage.outside == outside
    # a decision of scope outside accepts items as not data; a PDF span is the same place whatever its box
    accept = _decision(sha, (note, "p:3/w:1-9@70.00,88.00,310.00,101.00"), scope="outside")
    accepted = file_coverage(_record(sha), _doc(sha, (region,), outside), [outcome], [accept])
    assert accepted.summary.outside_numeric == 0 and accepted.decisions == ("rd-1",)
    # a cited line counts only while the region that cites it is mapped
    unread = outcome_from(region, None, state="unread", reason="no mapping")
    assert file_coverage(_record(sha), _doc(sha, (region,), outside), [unread]).summary.outside_numeric == 3
    # a context line cited, or a block accepted, as one sheet range holds the cells inside it
    row = int(lloq_line.rsplit("!A", 1)[1])
    as_range = outcome_from(region, _result(grid, header_rows=2, cited=(f"s:'Fasting'!A{row}:G{row}",)), state="mapped",
                            mapping=MAPPING, origin="cache")
    ranged = file_coverage(_record(sha), _doc(sha, (region,), outside), [as_range],
                           [_decision(sha, ("s:'Summary'!A9:C12", "p:3/w:1-9@0.00,0.00,1.00,1.00"), scope="outside")])
    assert ranged.summary.outside_numeric == 0


def test_the_truth_workbook_fully_mapped_leaves_its_one_outside_number():
    file = _messy()
    sha = _sha(file)
    regions, outcomes, cited = [], [], []
    for table in file.tables:
        grid = synthetic.truth_grid(file, table.id)
        lines = [c.locator for c in (*grid.caption, *(c for line in (*grid.above, *grid.below) for c in line))]
        region = _region(grid, table.where)
        regions.append(region)
        outcomes.append(outcome_from(region, _result(grid, header_rows=table.header_rows, cited=tuple(lines)),
                                     state="mapped", mapping=MAPPING, origin="cache"))
        cited += lines
    outside = tuple(OutsideItem(where=loc, text="a note with 3 numbers", numeric=True) for loc in file.outside)
    context = tuple(OutsideItem(where=loc, text="a context line 1", numeric=True) for loc in cited)
    coverage = file_coverage(_record(sha), _doc(sha, tuple(regions), outside + context), outcomes)
    assert coverage.summary.regions_mapped == len(file.tables) and coverage.summary.silent_loss == 0
    assert coverage.summary.outside_numeric == len(file.outside) == 1


def test_unassigned_values_unresolved_anchors_and_ocr_pages_are_in_the_summary():
    problem = AnchorProblem(id="tx-0123456789abcdef#3", anchor=f"{'f' * 64}@pdfplumber/1.0+x#p:2/t:1/r:4/c:3@1,2,3,4",
                            problem="text_differs", found="12.4")
    pages = tuple(Page(number=n, width=595.0, height=842.0, needs_ocr=n == 2, n_chars=0 if n == 2 else 900, words=(),
                       tables=()) for n in (1, 2))
    coverage = file_coverage(_record("f" * 64), _doc("f" * 64, (), state="partly_read", reason="page 2 needs OCR",
                                                     pages=pages), [], anchor_problems=[problem], values_unassigned=3)
    summary = coverage.summary
    assert (summary.values_unassigned, summary.anchors_unresolved, summary.needs_ocr_pages) == (3, 1, (2,))
    assert (summary.state, summary.reason) == ("partly_read", "page 2 needs OCR") and coverage.anchor_problems == (problem,)
    with pytest.raises(ValueError):
        file_coverage(_record("f" * 64), _doc("f" * 64, ()), [], values_unassigned=-1)
    with pytest.raises(ValueError, match="source document"):
        file_coverage(_record("e" * 64), _doc("f" * 64, ()), [])                  # another file's source: a misuse


def test_an_unsupported_file_is_a_coverage_row_with_its_reason():
    coverage = file_coverage(_record("9" * 64, "slides.pptx"), _doc("9" * 64, (), state="unsupported",
                                                                     reason="no parser for .pptx"), [])
    assert (coverage.summary.state, coverage.summary.reason) == ("unsupported", "no parser for .pptx")
    assert coverage.summary.regions == coverage.summary.silent_loss == 0 and coverage.file.name == "slides.pptx"


def test_an_outcome_is_refused_when_it_cannot_be_counted():
    grid = RegionGrid.from_rows([["Time", "Conc"], ["1", "10"]])
    region = _region(grid)
    with pytest.raises(ValueError, match="extraction result"):
        outcome_from(region, None, state="mapped")
    with pytest.raises(ValueError, match="reason"):
        outcome_from(region, None, state="excluded")
    with pytest.raises(ValueError, match="state"):
        outcome_from(region, None, state="done")
    # an outcome that undercounts its cells cannot hide a loss: what it does not account for is silent
    short = RegionOutcome(region_id=region.id, state="mapped", numeric_cells=3, uses={"value": 1})
    assert file_coverage(_record("8" * 64), _doc("8" * 64, (region,)), [short]).summary.silent_loss == 2


def test_a_result_that_leaves_cells_with_a_number_out_cannot_hide_them():
    file = _messy()
    grid = synthetic.truth_grid(file, "fasting-individual")
    region = _region(grid)
    full = _result(grid, header_rows=2)
    cut = ExtractResult(rows=(), constants=(), cell_use=full.cell_use[:-10], findings=())          # its last 10 left out
    left_out = sum(1 for c in full.cell_use[-10:] if c.numeric)
    assert left_out > 0
    outcome = outcome_from(region, cut, state="mapped", mapping=MAPPING, origin="rule")
    assert outcome.numeric_cells == region.numeric_cells                  # never below the region's own count
    coverage = file_coverage(_record(_sha(file)), _doc(_sha(file), (region,)), [outcome])
    assert coverage.summary.silent_loss == coverage.summary.cells_silent == left_out
    assert coverage.summary.numeric_cells == region.numeric_cells
    # an empty cell_use counts every cell with a number; so does a stored outcome whose count is 0
    empty = outcome_from(region, ExtractResult(rows=(), constants=(), cell_use=(), findings=()), state="mapped")
    assert file_coverage(_record(_sha(file)), _doc(_sha(file), (region,)), [empty]).summary.silent_loss == region.numeric_cells
    stored = RegionOutcome(region_id=region.id, state="mapped", numeric_cells=0)
    assert file_coverage(_record(_sha(file)), _doc(_sha(file), (region,)), [stored]).summary.silent_loss == region.numeric_cells


def test_a_cell_set_aside_with_no_rule_named_is_unaccounted():
    grid = RegionGrid.from_rows([["Time", "Conc"], ["1", "10"], ["2", "CV 12%"]])
    region = _region(grid)
    cv = grid.cell(3, 2).locator
    named = outcome_from(region, _result(grid, excluded=(cv,)), state="mapped", mapping=MAPPING, origin="rule")
    assert named.uses["excluded"] == 1 and named.unaccounted_count == 0
    unnamed = outcome_from(region, _result(grid, excluded=(cv,), rule=""), state="mapped", mapping=MAPPING, origin="rule")
    assert "excluded" not in unnamed.uses and unnamed.unaccounted == (cv,) and unnamed.unaccounted_count == 1
    coverage = file_coverage(_record("c" * 64), _doc("c" * 64, (region,)), [unnamed])
    assert (coverage.summary.cells_excluded, coverage.summary.silent_loss) == (0, 1) and coverage.regions[0].silent == (cv,)
    missing = ExtractResult(rows=(), constants=(), cell_use=(
        CellUse(row=1, column=1, locator="s:'T'!A1", numeric=True, use="missing", rule=""),
        CellUse(row=2, column=1, locator="s:'T'!A2", numeric=True, use="missing", rule="missing_token:NS")), findings=())
    two = Region(id="rg-00000000a2", kind="table", where="s:'T'!A1:A2", numeric_cells=2)
    assert outcome_from(two, missing, state="mapped").uses == {"missing": 1, "unaccounted": 1}


def test_a_prose_or_figure_decision_never_excludes_a_table():
    grid = RegionGrid.from_rows([["Time", "Conc"], ["1", "10"], ["2", "12"]])
    table = _region(grid)
    prose = Region(id="rg-0000000abc", kind="prose", where="p:1/w:1-60", numeric_cells=5)
    figure = Region(id="rg-00000000ff", kind="figure", where="p:4/f:1", numeric_cells=3)
    doc = _doc("7" * 64, (table, prose, figure))
    for scope in ("unread_prose", "figures"):
        decided = file_coverage(_record("7" * 64), doc, [], [_decision("7" * 64, (table.id, prose.id, figure.id), scope)])
        states = {r.region.kind: r.outcome.state for r in decided.regions}
        assert states["table"] == "unread" and decided.summary.silent_loss == table.numeric_cells
    prose_only = file_coverage(_record("7" * 64), doc, [], [_decision("7" * 64, (table.id, prose.id), "unread_prose")])
    assert [r.outcome.state for r in prose_only.regions] == ["unread", "excluded", "excluded"]    # the figure by its rule
    assert prose_only.decisions == ("rd-1",)
    regions = file_coverage(_record("7" * 64), doc, [], [_decision("7" * 64, (table.id,), "regions")])
    assert regions.regions[0].outcome.state == "excluded" and regions.summary.silent_loss == 0
    nothing = file_coverage(_record("7" * 64), doc, [], [_decision("7" * 64, (table.id,), "figures")])
    assert nothing.decisions == () and nothing.summary.silent_loss == table.numeric_cells


def test_silent_loss_sums_the_files():
    one = file_coverage(_record("1" * 64), _doc("1" * 64, (Region(id="rg-0000000001", kind="table", where="s:'A'!A1:B2",
                                                                      numeric_cells=4),)), [])
    two = file_coverage(_record("2" * 64), _doc("2" * 64, (Region(id="rg-0000000002", kind="table", where="s:'B'!A1:B2",
                                                                      numeric_cells=6),)), [])
    assert silent_loss([one.summary, two.summary]) == 10 and silent_loss([]) == 0


def test_values_unassigned_counts_the_values_of_no_subject(tmp_path):
    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    files = synthetic.delivery()
    write_truth(ws, files)
    shas = [_sha(f) for f in files]
    assert [values_unassigned(LedgerView(ws), sha) for sha in shas] == [0] * len(files)   # products and the compound
    anchor = f"{shas[0]}@workbook/{synthetic.TRUTH_PARSER_VERSION}#s:'Fasting'!A40"         # a table that names no study
    store = IntakeStore(ws)
    loose = store.facts.append("fact", lambda seq: Fact(
        id=f"f-{seq}", delivery="dl-1", entity=EntityRef(matrix="plasma"), field="concentration", value=4.2, unit="ng/mL",
        anchor=anchor, method="cell", by="code", at=AT).model_dump(mode="json")).body["id"]
    store.facts.append("fact", lambda seq: Fact(
        id=f"f-{seq}", delivery="dl-1", entity=EntityRef(), field="concentration", value=None, spread=1.0, spread_kind="SD",
        method="derived", derived_from=(loose,), compute="spread-1/sd_from_se", by="code", at=AT).model_dump(mode="json"))
    store.facts.append("fact", lambda seq: Fact(
        id=f"f-{seq}", delivery="dl-1", entity=EntityRef(), field="phys.pka", value=9.1, method="cell",
        anchor=anchor.replace("A40", "A41"), by="code", at=AT).model_dump(mode="json"))
    reader = LedgerView(ws)
    assert values_unassigned(reader, shas[0]) == 1                     # the spread fact qualifies it; the pKa is the compound's
    assert [v.id for v in reader.values(unassigned=True) if not is_spread_fact(v)] == [loose]
