"""D3: the layout fingerprint a cached mapping is found by, and the header band (contracts §6.2, §8.5). The same
layout is the same fingerprint wherever it stands and whatever its subjects and times; one more column or another
header word is another layout. Software test data (the made-up Exampleamide)."""

from __future__ import annotations

import pytest

from modeler_intake import synthetic
from modeler_intake.mapping.fingerprint import header_band, layout_fingerprint, norm
from modeler_intake.source_model import RegionGrid

pytestmark = pytest.mark.req("T-47")

ROWS = [["Subject", "Exampleamide (ng/mL) at 0 h", "at 1 h", "at 2 h"], ["S01", "BLQ", 12.1, 30.4], ["S02", "BLQ", 10.5, 28.2],
        ["Mean", "BLQ", 11.3, 29.3]]


def _grid(rows=ROWS, **kwargs) -> RegionGrid:
    return RegionGrid.from_rows(rows, **kwargs)


def test_norm_folds_case_space_and_digits():
    assert norm("  Time (H)  after  dose 12 ") == "time (h) after dose #"
    assert norm("S01") == norm("S117") == "s#"


def test_equal_under_another_sheet_name_offset_subjects_and_times():
    base = layout_fingerprint(_grid())
    assert layout_fingerprint(_grid(sheet="Fed", first_cell="C7")) == base
    other_subjects = [ROWS[0], ["S11", "BLQ", 9.0, 20.0], ["S12", "BLQ", 8.0, 21.0], ROWS[3]]
    assert layout_fingerprint(_grid(other_subjects)) == base
    other_times = [["Subject", "Exampleamide (ng/mL) at 0 h", "at 4 h", "at 12 h"], *ROWS[1:]]
    assert layout_fingerprint(_grid(other_times)) == base
    assert layout_fingerprint(_grid(caption=["Study 999-01, 10 mg"], above=[["a note"]])) == base   # context is not layout


def test_the_messy_workbooks_two_individual_sheets_share_one_layout():
    """"Fasting" and "Fed": another sheet, another study title, other subject numbers: one fingerprint."""
    messy = synthetic.messy_workbook()
    fasting = synthetic.truth_grid(messy, "fasting-individual")
    fed = synthetic.truth_grid(messy, "fed-individual")
    assert layout_fingerprint(fasting) == layout_fingerprint(fed)
    assert layout_fingerprint(fasting) != layout_fingerprint(synthetic.truth_grid(messy, "fasting-metabolite"))


def test_different_with_one_more_column_or_another_header_word():
    base = layout_fingerprint(_grid())
    wider = [[*row, x] for row, x in zip(ROWS, ("at 4 h", 1.0, 2.0, 3.0), strict=True)]
    assert layout_fingerprint(_grid(wider)) != base
    renamed = [["Patient", *ROWS[0][1:]], *ROWS[1:]]
    assert layout_fingerprint(_grid(renamed)) != base
    another_label = [*ROWS[:3], ["Median", "BLQ", 11.3, 29.3]]
    assert layout_fingerprint(_grid(another_label)) != base             # the body's row labels are part of the layout


def test_header_band_ends_above_the_first_row_of_numbers():
    assert header_band(_grid()) == 1
    assert header_band(RegionGrid.from_rows([["Time", "Conc"], ["(h)", "(ng/mL)"], [1, 2.5], [2, 3.5]])) == 2
    assert header_band(RegionGrid.from_rows([[1, 2.5], [2, 3.5]])) == 0
    five = [[f"h{i}", f"x{i}"] for i in range(6)] + [[1, 2]]
    assert header_band(RegionGrid.from_rows(five)) == 4                 # at most 4
    text_heavy = synthetic.truth_grid(synthetic.messy_workbook(), "summary-parameters")
    assert header_band(text_heavy) == 1                                  # no row with two bare numbers: the first row only
    assert header_band(RegionGrid.from_rows([["A", "B"], ["NS", "BLQ"], [1, 2]])) == 1   # tokens stand where numbers stand


def test_a_row_of_values_written_with_their_spread_mark_or_unit_ends_the_band():
    """Composite values are body: the band ends above them, and a marked value in the first body row does not move it."""
    summary = RegionGrid.from_rows([["Statistic", "N", "Cmax (ng/mL)", "AUC"], ["Mean (SD)", 24, "12.3 (4.5)", "120 (30)"],
                                    ["Geo mean (CV%)", 24, "11.8 (35)", "115 (28)"], ["Median", 24, 11.0, 118]])
    assert header_band(summary) == 1
    marked, blq = (_grid([ROWS[0], ["S01", first, 12.1, 30.4], *ROWS[2:]]) for first in ("12.3*", "BLQ"))
    assert header_band(marked) == header_band(blq) == 1
    assert layout_fingerprint(marked) == layout_fingerprint(blq)
    for cells in (["12.3 ± 4.5", "9.1 ± 2.2"], ["0.95 (0.88-1.03)", "1.02 (0.97-1.08)"], ["12.3 ng/mL", "9.1 ng/mL"],
                  ["5.2, 20.1", "3.3, 8.4"], ["0.5 h", "1 h"]):
        assert header_band(RegionGrid.from_rows([["A", "B"], ["Label", "Other"], cells])) == 2
    # a header word with a number is no value
    assert header_band(RegionGrid.from_rows([["Time (h)", "90% CI lower", "90% CI upper"], [1, 8.1, 12.3]])) == 1
    # first-column times written with their unit are no labels of the layout
    times = [["Time", "Conc (ng/mL)"], ["0.5 h", 2.5], ["1 h", 3.5]]
    other = [["Time", "Conc (ng/mL)"], ["2 h", 2.5], ["4.5 h", 3.5], ["8 h", 1.0]]
    assert layout_fingerprint(_grid(times)) == layout_fingerprint(_grid(other))
