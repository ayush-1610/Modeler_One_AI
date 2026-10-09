"""Legacy Excel 97–2003 workbooks read into the same grid as an .xlsx (xlrd, owner-approved 2026-10-09)."""

from __future__ import annotations

from pathlib import Path

import pytest

from modeler_intake.grid import read_workbook, read_workbook_bytes

pytestmark = pytest.mark.req("T-47")

XLS = Path(__file__).parent / "fixtures" / "legacy-study.xls"


def test_an_xls_workbook_is_a_grid_with_sheet_references_and_merged_ranges():
    grid = read_workbook_bytes(XLS.read_bytes(), "legacy-study.xls")
    assert list(grid.sheets) == ["PK", "Info"]
    pk = grid.sheets["PK"]
    assert pk.cells[(1, 1)].value == "Study EX-101 plasma concentrations"
    assert pk.cells[(1, 3)].merged_from == pk.cells[(1, 1)].ref        # the merged title covers A1:C1
    assert pk.cells[(2, 2)].value == "Conc (ng/mL)"
    assert [pk.cells[(r, 1)].value for r in range(3, 7)] == [0.5, 1, 2, 4]  # whole numbers read as int, as openpyxl
    assert pk.cells[(4, 2)].value == 48.2 and pk.cells[(4, 2)].ref.endswith("B4")
    info = grid.sheets["Info"]
    assert info.cells[(1, 2)].value == 50
    assert info.cells[(2, 2)].value.isoformat() == "2024-03-05T00:00:00"  # naive, as Excel and openpyxl keep it
    assert info.cells[(3, 2)].value is True


def test_the_file_and_the_bytes_read_the_same():
    from_file = read_workbook(XLS, "x")
    from_bytes = read_workbook_bytes(XLS.read_bytes(), "legacy-study.xls")
    assert {k: v.value for k, v in from_file.sheets["PK"].cells.items()} == \
           {k: v.value for k, v in from_bytes.sheets["PK"].cells.items()}
