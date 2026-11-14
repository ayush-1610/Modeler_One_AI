"""The intake rebuild's L2 contract code (docs/plans/2026-11-12-intake-contracts.md §4.1-§4.4, §10): anchors and their
grammar, the source model's number tests, `canonical`, the field vocabulary, and the shared synthetic files, each opened
with its own library and shown to hold its truth."""

from __future__ import annotations

import csv
import datetime as clock
import hashlib
import io
import types
import zipfile
from datetime import datetime

import docx
import pdfplumber
import pytest
from openpyxl import load_workbook
from openpyxl.utils import range_boundaries

from modeler_intake import synthetic
from modeler_intake.anchors import (
    ID_PATTERNS,
    RANGE,
    Anchor,
    AnchorError,
    DocxCell,
    DocxSpan,
    FigureRef,
    PdfCell,
    PdfSpan,
    SheetCell,
    TextSpan,
    anchor_text,
    canonical,
    check_id,
    format_anchor,
    format_locator,
    parse_anchor,
    parse_locator,
    same_place,
    sha256_of,
)
from modeler_intake.client_template import SHEETS, is_template, read_client_workbook
from modeler_intake.fields import (
    CONDITION_FIELDS,
    FIELDS,
    KIND_OF_CATEGORY,
    LABEL_FIELDS,
    field,
    known_unit,
    read_choice,
    unit_class,
    unit_table,
    units_in,
)
from modeler_intake.grid import read_workbook_bytes
from modeler_intake.mapping_spec import Cite, Constant, MappingSpec
from modeler_intake.source_model import RegionGrid, SourceDocument, has_number, is_numeric_text
from modeler_intake.triage import SheetCategory

pytestmark = pytest.mark.req("T-47")

SHA = "9c1e" + "0" * 58 + "77"
LOCATORS = (
    (SheetCell(sheet="PK Summary", cell="C12"), "s:'PK Summary'!C12"),
    (SheetCell(sheet="O'Brien's #1!", cell="AA100"), "s:'O''Brien''s #1!'!AA100"),
    (PdfCell(page=12, table=1, row=4, column=3, box=(212.4, 318.02, 251.1, 329.5)),
     "p:12/t:1/r:4/c:3@212.40,318.02,251.10,329.50"),
    (PdfSpan(page=1, first_word=5, last_word=9, box=(56.0, 100.0, 300.25, 110.0)), "p:1/w:5-9@56.00,100.00,300.25,110.00"),
    (DocxCell(table=2, row=3, column=1), "d:t:2/r:3/c:1"),
    (DocxSpan(paragraph=4, start=0, end=17), "d:p:4/ch:0-17"),
    (TextSpan(line=12, start=3, end=9), "x:l:12/ch:3-9"),
    (FigureRef(page=3, index=1, box=(10.0, 20.0, 30.0, 40.0)), "p:3/f:1@10.00,20.00,30.00,40.00"),
    (FigureRef(index=2), "d:f:2"),
)


# --- anchors -------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("locator", "text"), LOCATORS, ids=[t for _l, t in LOCATORS])
def test_every_locator_kind_round_trips_as_text_and_inside_an_anchor(locator, text):
    assert format_locator(locator) == text
    assert parse_locator(text) == locator
    anchor = Anchor(file_sha256=SHA, parser="pdfplumber", parser_version="1.0+pdfplumber0.11.4", locator=locator)
    written = format_anchor(anchor)
    assert written == f"{SHA}@pdfplumber/1.0+pdfplumber0.11.4#{text}"
    assert parse_anchor(written) == anchor
    assert anchor_text(SHA, "pdfplumber", "1.0+pdfplumber0.11.4", text) == written
    assert Anchor.model_validate_json(anchor.model_dump_json()) == anchor


@pytest.mark.parametrize("text", [
    "s:PK!C12",                                     # a sheet is always quoted
    "s:'a'b'!C1",                                   # a quote inside is doubled
    "s:''!C1",                                      # an empty sheet name
    "s:'T'!c1", "s:'T'!A0", "s:'T'!A01", "s:'T'!ABCD1",
    "s:'T\x01'!A1",                                 # a control character
    "s:'T'!A1\n",
    "p:0/t:1/r:1/c:1@1.00,2.00,3.00,4.00",          # pages, tables, rows, columns count from 1
    "p:1/t:1/r:1/c:1@1.0,2.00,3.00,4.00",           # a box has 2 decimals
    "p:1/t:1/r:1/c:1@-0.00,2.00,3.00,4.00",         # one spelling of zero
    "p:1/t:1/r:1/c:1@01.00,2.00,3.00,4.00",
    "p:1/t:1/r:1/c:1",                              # a PDF cell has its box
    "p:1/w:3-2@1.00,2.00,3.00,4.00",                # a span does not end before it starts
    "d:p:1/ch:5-3", "d:p:1/ch:01-3", "x:l:0/ch:0-3",
    "d:t:1/r:1", "p:1/f:1", "d:f:0", "../../etc/passwd", "", "s:'T'!A1:B2",
])
def test_a_locator_outside_its_grammar_or_character_set_is_refused(text):
    with pytest.raises(AnchorError):
        parse_locator(text)


@pytest.mark.parametrize("text", [
    f"{SHA.upper()}@workbook/1.0#s:'T'!A1",          # sha256 is lower-case hex
    f"{SHA[:-1]}@workbook/1.0#s:'T'!A1",
    f"{SHA}@Workbook/1.0#s:'T'!A1",                  # parser [a-z0-9_]+
    f"{SHA}@work-book/1.0#s:'T'!A1",
    f"{SHA}@workbook/1.0/x#s:'T'!A1",                # version [A-Za-z0-9.+_-]+
    f"{SHA}@workbook/1 0#s:'T'!A1",
    f"{SHA}@workbook/1.0#s:'T'!A1\n",
    f"{SHA}@workbook/1.0#../x", f"{SHA}@workbook/#s:'T'!A1", f"{SHA}#s:'T'!A1",
])
def test_an_anchor_part_outside_its_character_set_is_refused(text):
    with pytest.raises(AnchorError):
        parse_anchor(text)


def test_formatting_refuses_what_the_grammar_cannot_write():
    for bad in (SheetCell(sheet="", cell="A1"), SheetCell(sheet="a\nb", cell="A1"), SheetCell(sheet="T", cell="a1"),
                PdfCell(page=0, table=1, row=1, column=1, box=(0, 0, 1, 1)), DocxSpan(paragraph=1, start=4, end=2),
                FigureRef(page=1, index=1), FigureRef(index=1, box=(0, 0, 1, 1)),
                PdfSpan(page=1, first_word=1, last_word=1, box=(0, 0, float("nan"), 1))):
        with pytest.raises(AnchorError):
            format_locator(bad)
    with pytest.raises(AnchorError):
        anchor_text("..", "workbook", "1.0", "s:'T'!A1")
    with pytest.raises(AnchorError):
        anchor_text(SHA, "workbook", "1.0", "s:T!A1")


def test_same_place_compares_identity_and_never_the_box():
    a = PdfCell(page=2, table=1, row=4, column=3, box=(212.4, 318.02, 251.1, 329.5))
    assert same_place(a, a.model_copy(update={"box": (212.0, 318.0, 251.0, 330.0)}))
    assert not same_place(a, a.model_copy(update={"row": 5}))
    span = PdfSpan(page=1, first_word=3, last_word=4, box=(1, 2, 3, 4))
    assert same_place(span, span.model_copy(update={"box": (9, 9, 9, 9)}))
    assert same_place(FigureRef(page=1, index=2, box=(1, 2, 3, 4)), FigureRef(page=1, index=2, box=(5, 6, 7, 8)))
    assert not same_place(SheetCell(sheet="T", cell="A1"), SheetCell(sheet="U", cell="A1"))
    assert not same_place(DocxCell(table=1, row=1, column=1), SheetCell(sheet="T", cell="A1"))
    assert RANGE.fullmatch("s:'Fasting'!A2:G14") and RANGE.fullmatch("p:2/t:1") and RANGE.fullmatch("d:p:2-3")
    assert not RANGE.fullmatch("s:'Fasting'!A2")


def test_ids_from_a_request_are_checked_before_use():
    good = {"sha256": SHA, "extract": "tx-0123456789abcdef", "value": "tx-0123456789abcdef#12", "region": "rg-5d2a90c1e4",
            "mapping": "mp-5b0c2a9e41d7", "file": "fl-9c1e00000000", "line": "f-41", "conflict": "cx-0123456789",
            "check": "ck-0123456789ab"}
    assert set(good) == set(ID_PATTERNS)
    for kind, text in good.items():
        assert check_id(kind, text) == text
    for kind, text in good.items():
        for bad in ("..", "/", "../p2/intake/files.jsonl", text + "/..", text + "\n", "", f"{text} "):
            with pytest.raises(AnchorError):
                check_id(kind, bad)
    for line in ("st-5", "cf-3", "run-7", "dl-2", "arm-3"):
        assert check_id("line", line) == line
    for bad in ("f-0", "f-01", "abcd-1", "F-1"):
        with pytest.raises(AnchorError):
            check_id("line", bad)
    with pytest.raises(AnchorError):
        check_id("value", "tx-0123456789abcdef#01")
    with pytest.raises(KeyError):                            # an unknown kind is the caller's bug, not bad input
        check_id("store", "f-1")


# --- numbers in text -----------------------------------------------------------------------------------------------


BARE = ("12.5", "-3", "−3", "+4", "<0.5", "> 1000", "≤0.1", "1,234.5", "12,5", "1.234,5", ".5", "1e-3", "2.5E+4",
        "55%", "55 %", " 7 ", "１２")
HOLD = ("12.3 (4.5)", "12.3 ± 4.5", "0.95 (0.88-1.03)", "12.3*", "12.3 ng/mL", "1 234.5", "S01", "2 h", "<LLOQ 0.5",
        "Study 230-23", "CV% 12", "vessel_1", "15.01.2024", "1.2.3", "2024-01-15", "12:30")
BARE += ("1,234", "1.234.567", "12.345.678,9", "1,234,567.89")       # thousands groups of exactly three digits
NONE = ("BLQ", "NS", "", "Mean", "  ", "ND", "n/a")


def test_a_bare_number_and_a_cell_with_a_number_are_told_apart():
    for text in BARE:
        assert is_numeric_text(text), text
        assert has_number(text), text
    for text in HOLD:
        assert not is_numeric_text(text), text
        assert has_number(text), text
    for text in NONE:
        assert not is_numeric_text(text), text
        assert not has_number(text), text


# --- canonical -----------------------------------------------------------------------------------------------------


def test_canonical_dumps_a_model_by_its_aliases_sorted_and_compact():
    spec = MappingSpec(kind="not_data", layout="long", header_rows=0, first_data_row=1, not_data_reason="µ notes")
    text = canonical(spec)
    assert '"schema":"mapping/2"' in text and "schema_id" not in text
    assert "µ" in text and ", " not in text and ": " not in text
    assert canonical({"b": spec, "a": [spec]}) == '{"a":[' + text + '],"b":' + text + "}"
    assert sha256_of(spec) == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert MappingSpec.model_validate_json(text) == spec
    assert canonical({"b": 1, "a": (1.5, None)}) == '{"a":[1.5,null],"b":1}'
    for bad in (float("nan"), float("inf"), -float("inf")):                  # no JSON form: nothing hashed that cannot be stored
        with pytest.raises(ValueError):
            canonical({"value": bad})


def test_a_model_with_a_schema_alias_reads_back_by_its_name_too():
    spec = synthetic.INDIVIDUAL_SPEC
    assert MappingSpec.model_validate(spec.model_dump(mode="json")) == spec                     # "schema_id"
    assert MappingSpec.model_validate(spec.model_dump(mode="json", by_alias=True)) == spec      # "schema"
    doc = SourceDocument(file_sha256=SHA, name="x.csv", size_bytes=3, format="csv", parser="delimited",
                         parser_version="1.0", state="read")
    assert SourceDocument.model_validate(doc.model_dump(mode="json")) == doc
    assert "schema_id" not in canonical(doc) and SourceDocument.model_validate_json(canonical(doc)) == doc


def test_a_cite_is_a_cell_or_a_context_line():
    assert Cite(row=1, column=2).near is None and Cite(near="below", line=3).row is None
    for bad in (dict(row=1), dict(column=2), dict(row=1, column=2, near="caption"), dict(), dict(near="above", line=4)):
        with pytest.raises(ValueError):
            Cite(**bad)
    with pytest.raises(ValueError):
        Constant(field="dose", cite=Cite(near="caption"), extra=1)


# --- the field vocabulary ------------------------------------------------------------------------------------------

# A template column that is not a field of the same name is read by a mapping role (mapping_spec.Role) or is a field
# under another name: the label columns, the time and unit columns, the spread and its kind, the vessels ...
TEMPLATE_ROLES = {"subject_id": "subject", "role": "product_role", "nominal_time": "time", "actual_time": "time_actual",
                  "time": "time", "time_unit": "time_unit", "unit": "unit", "lloq_unit": "unit", "blq_flag": "blq_flag",
                  "statistic": "statistic", "value": "value", "variability": "spread", "variability_kind": "spread_kind",
                  "parameter": "parameter", "mean": "value", "sd": "spread", "amount": "excretion.amount",
                  "conditions": "ignore", "method": "ignore", "report_reference": "reference",
                  **{f"vessel_{i}": "vessel" for i in range(1, 13)}}


def test_the_fields_cover_every_column_of_the_client_data_template():
    from typing import get_args

    from modeler_intake.mapping_spec import Role

    roles = set(get_args(Role))
    for sheet, columns in SHEETS.items():
        for column in columns:
            name = column.name
            if field(name) is not None:
                continue
            target = TEMPLATE_ROLES.get(name)
            assert target is not None, f"{sheet}.{name} is neither a field nor a mapped template column"
            assert target in roles or field(target) is not None, f"{sheet}.{name} -> {target}"
    assert set(CONDITION_FIELDS) <= set(FIELDS) and set(LABEL_FIELDS) <= set(FIELDS)
    assert all(field(f"pk.{p}") is not None for p in ("AUC_last", "AUC_inf", "Cmax", "tmax", "t_half", "Ctrough", "CL/F", "Vz/F"))
    assert field("relation.ddi_ratio.AUC_inf").unit_class == "ratio"
    assert field("phys.logp").level == "compound" and field("elim.hepatic.CYP3A4.clint") is not None
    assert field("food.fed_solubility_factor") is not None and field("phys.logp@shake_flask") is not None   # a template target
    assert field("nonsense") is None and field("bogus.logp") is None
    assert field("alt.foo") is None and field("alt.select") is not None      # alt.select is an exact id, not a family
    assert field("phys.") is None and field("phys.logp x") is None
    assert set(KIND_OF_CATEGORY) == {c.value for c in SheetCategory} and KIND_OF_CATEGORY["OTHER"] == "unknown"
    assert field("special_population").choices == ("pediatric", "hepatic_impairment", "renal_impairment", "pregnancy", "elderly")


def test_a_units_class_is_its_fields_and_only_existing_tables_check_it():
    for unit, canonical_unit in (("mg", "mg"), ("g", "g"), ("µg", "µg"), ("μg", "µg"), ("ug", "µg"), ("mcg", "µg"),
                                 ("mg/kg", "mg/kg"), ("MG", "mg")):
        assert known_unit("dose", unit) == canonical_unit, unit
    assert known_unit("dose", "kg") is None and known_unit("dose", "ng/mL") is None
    assert known_unit("rpm", "rpm") is None and unit_class("rpm") == "other" and unit_table("other") is None
    assert known_unit("particle_size_d50_um", "µm") is None and units_in("particle_size_d50_um", "Particle size d50 (µm)") == ()
    assert known_unit("concentration", "µm") == "µmol/l"        # why a unit's class is never read from its text
    assert known_unit("concentration", "ng/mL") == "ng/ml" and known_unit("time", "hr") == "h"
    assert known_unit("percent_dissolved", "%") == "%" and known_unit("pk.Cmax", "ng/mL") is None
    # only `is None` is "not known": a fraction of 1 is canonically "" (validate.FRACTION_UNITS); a missing unit is None
    assert known_unit("percent_dissolved", "fraction") == "" and known_unit("excretion.fraction", "frac") == ""
    for missing in ("", "  "):
        assert known_unit("percent_dissolved", missing) is None and known_unit("dose", missing) is None
    assert units_in("concentration", "Exampleamide plasma concentration (ng/mL) by time after dose (h)") == ("ng/mL",)
    assert units_in("time", "Exampleamide plasma concentration (ng/mL) by time after dose (h)") == ("h",)
    assert units_in("dose", "Study 230-23, 50 mg, fasted") == ("mg",)
    assert units_in("percent_dissolved", "batch L2301 (% dissolved)") == ("%",)


def test_read_choice_reads_every_choice_column_of_the_templates_studies_row():
    file = synthetic.template_workbook()
    (studies,) = [t for t in file.tables if t.id == "template-studies"]
    header = [h.rstrip("*") for h in studies.rows[0]]
    row = dict(zip(header, studies.rows[1], strict=True))
    choices = [name for name in header if (f := field(name)) is not None and f.value == "choice" and row[name]]
    assert {"design", "crossover", "population", "route", "dose_unit", "salt_or_base", "product_role", "formulation",
            "food_state", "matrix", "intended_use"} <= set(choices)
    for name in choices:
        assert read_choice(name, row[name]) == row[name], name
    for name, text, choice in (("special_population", "pediatric", "pediatric"), ("population", "healthy volunteers", "healthy"),
                               ("crossover", "a two-way cross-over", "yes"), ("matrix", "faeces", "feces"),
                               ("child_pugh", "Child-Pugh B", "B"), ("release", "extended release", "ER"),
                               ("route", "given orally", "oral"), ("food_state", "fasted, then a standard meal", None),
                               ("route", "subcutaneous", None), ("route", "another route: other", "other"),
                               ("matrix", "plasma and serum", None), ("route", "IV infusion", "iv_infusion"),
                               ("dose", "50 mg", None), ("route", "", None)):
        assert read_choice(name, text) == choice, (name, text)


# --- the synthetic files -------------------------------------------------------------------------------------------


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, datetime):
        return value.isoformat()
    return repr(value) if isinstance(value, float) else str(value)


_BUILDERS = (synthetic.messy_workbook, synthetic.pdf_report, synthetic.scanned_pdf, synthetic.word_report,
             synthetic.delimited, synthetic.template_workbook)


def test_the_builders_are_deterministic_and_the_delivery_is_their_set():
    for build in _BUILDERS:
        assert build().data == build().data, build.__name__
    names = [f.name for f in synthetic.delivery()]
    assert names == ["messy-delivery.xlsx", "study-report.pdf", "design-report.docx", "concentrations.csv"]
    assert synthetic.DRUG == "Exampleamide"


def test_a_file_built_at_another_time_has_the_same_bytes(monkeypatch):
    import openpyxl.packaging.core
    import openpyxl.writer.excel

    first = {build.__name__: build().data for build in _BUILDERS}

    class Later(clock.datetime):                    # the libraries' clock, a year and some hours on
        @classmethod
        def now(cls, tz=None):
            return clock.datetime(2027, 5, 6, 7, 8, 9, tzinfo=tz)

    later = types.SimpleNamespace(datetime=Later, timezone=clock.timezone, date=clock.date)
    monkeypatch.setattr(openpyxl.writer.excel, "datetime", later)
    monkeypatch.setattr(openpyxl.packaging.core, "datetime", later)
    for build in _BUILDERS:
        assert build().data == first[build.__name__], build.__name__


def test_the_messy_workbook_opens_with_openpyxl_and_holds_its_truth():
    file = synthetic.messy_workbook()
    wb = load_workbook(io.BytesIO(file.data))
    assert wb.sheetnames == ["Fasting", "Fed", "Dissolution", "Summary", "Urine", "Product", "Notes"]
    assert wb["Notes"].sheet_state == "hidden" and all(wb[s].sheet_state == "visible" for s in wb.sheetnames[:-1])
    assert {"A2:A3", "B2:G2"} <= {str(r) for r in wb["Fasting"].merged_cells.ranges}
    assert len([t for t in file.tables if t.where.startswith("s:'Fasting'!")]) == 2           # two tables on one sheet
    assert {t.where for t in file.tables if t.where.startswith("s:'Dissolution'!")} == {"s:'Dissolution'!A3:G9",
                                                                                         "s:'Dissolution'!I3:L9"}
    mean = wb["Fasting"]["C11"]
    assert mean.value == 12.4037 and mean.number_format == "0.00"
    assert {wb["Urine"].cell(r, 4).number_format for r in range(3, 7)} == {"0.0%"}
    data = load_workbook(io.BytesIO(file.data), data_only=True)
    for table in file.tables:
        sheet, cells = table.where[3:].split("'!")
        col0, row0, col1, row1 = range_boundaries(cells)
        ws = data[sheet.replace("''", "'")]
        written = tuple(tuple(_cell_text(ws.cell(r, c).value) for c in range(col0, col1 + 1)) for r in range(row0, row1 + 1))
        assert written == table.rows, table.id
        for line, text in enumerate(table.caption, start=1):
            assert ws.cell(row0 - len(table.caption) + line - 1, col0).value == text
    for value in file.values:
        sheet, cell = parse_locator(value.locator).sheet, parse_locator(value.locator).cell
        assert value.value in _cell_text(data[sheet][cell].value), (value.table, value.locator, value.value)
    assert read_workbook_bytes(file.data, file.name).sheet("Fasting").cell(3, 1).merged_from == "Fasting!A2"
    assert file.outside == ("s:'Summary'!A10",) and has_number(data["Summary"]["A10"].value)


def _words(page) -> list[str]:
    return [w["text"] for w in page.extract_words()]


def test_the_pdf_report_opens_with_pdfplumber_which_finds_its_words_and_ruled_tables():
    file = synthetic.pdf_report()
    with pdfplumber.open(io.BytesIO(file.data)) as pdf:
        assert len(pdf.pages) == 6
        for page in pdf.pages:
            assert _words(page)[-4:] == ["Page", str(page.page_number), "of", "6"]          # a page number on every page
        for value in file.values:                                                          # every word span is its words
            for role, locator in (("value", value.locator), *value.locators):
                found = parse_locator(locator)
                if found.kind != "pdf_span":
                    continue
                text = " ".join(_words(pdf.pages[found.page - 1])[found.first_word - 1: found.last_word])
                expected = value.value if role == "value" and value.table == "" else None
                table = next((t for t in file.tables if t.id == value.table), None)
                if expected is None and table is not None:
                    expected = text if text in (*table.caption, *table.below) else "<not a context line>"
                if expected is None and role == "study":
                    expected = "230-23"
                assert text == expected, (value.field, role, locator, text)
        for table in file.tables:                                                          # the ruled tables, joined
            rows: list[tuple[str, ...]] = []
            for k, number in enumerate(table.pages):
                (found,) = pdf.pages[number - 1].find_tables()
                extracted = [tuple(cell or "" for cell in row) for row in found.extract()]
                rows += extracted[table.header_rows:] if k else extracted
            assert tuple(rows) == table.rows, table.id
        continued = pdf.pages[2].find_tables()[0].extract()
        assert continued[0] == list(file.tables[0].rows[0])                               # the header repeated on page 3
        assert "(continued)" in " ".join(_words(pdf.pages[2])[:12])
        assert pdf.pages[5].find_tables() == [] and "Cmax" in _words(pdf.pages[5])         # unruled: words, no table
        for table in file.tables:                    # a PDF region id from pdfplumber's own box and first row (§4.2)
            (found,) = pdf.pages[table.pages[0] - 1].find_tables()
            x0, top, x1, bottom = (round(v) for v in found.bbox)
            first_row = " ".join(t for t in found.extract()[0] if t)
            sha = hashlib.sha256(file.data).hexdigest()
            text = f"p:{table.pages[0]}/box:{x0},{top},{x1},{bottom}/{first_row}|{sha}"
            assert synthetic.truth_grid(file, table.id).region_id == "rg-" + hashlib.sha256(text.encode()).hexdigest()[:10]
        grid = synthetic.truth_grid(file, "report-table5")
        for cell in grid.cells.values():                                                   # each cell's locator is pdfplumber's cell
            locator = parse_locator(cell.locator)
            found = pdf.pages[locator.page - 1].find_tables()[locator.table - 1]
            assert found.rows[locator.row - 1].cells[locator.column - 1] == pytest.approx(locator.box)
            assert found.extract()[locator.row - 1][locator.column - 1] == cell.text
    with pdfplumber.open(io.BytesIO(synthetic.pdf_report(unruled_table=False).data)) as pdf:
        assert len(pdf.pages) == 5


def test_the_scanned_pdf_has_a_page_with_no_text_layer():
    file = synthetic.scanned_pdf()
    with pdfplumber.open(io.BytesIO(file.data)) as pdf:
        text_page, image_page = pdf.pages
        assert len(text_page.chars) > 20 and not text_page.images
        assert image_page.chars == [] and image_page.extract_words() == [] and len(image_page.images) == 1


def test_the_word_report_opens_with_python_docx_merged_header_line_break_and_image():
    file = synthetic.word_report()
    doc = docx.Document(io.BytesIO(file.data))
    paragraphs = doc.paragraphs
    assert paragraphs[0].text == "Study design" and paragraphs[0].style.name == "Heading 1"
    assert [p.text for p in paragraphs[1:4]] == [*file.prose[1:], file.tables[0].caption[0]]
    (table,) = doc.tables
    assert table.cell(0, 1)._tc is table.cell(0, 2)._tc                                     # merged across
    assert table.cell(0, 0)._tc is table.cell(1, 0)._tc                                     # merged down
    assert table.cell(1, 1).text == "Mean\n(arithmetic)"                                    # a line break stays in the cell
    assert len(doc.inline_shapes) == 1
    for r, row in enumerate(file.tables[0].rows):
        for c, text in enumerate(row):
            if text:
                assert table.cell(r, c).text == text
    for value in file.values:
        found = parse_locator(value.locator)
        if found.kind == "docx_cell":
            assert table.cell(found.row - 1, found.column - 1).text == value.value
        else:
            text = paragraphs[found.paragraph - 1].text[found.start:found.end]
            assert text == value.value or (value.table and value.value in text), value


@pytest.mark.parametrize(("sep", "decimal_comma", "encoding"), [(";", True, "cp1252"), ("\t", False, "utf-16"),
                                                                 (",", True, "utf-8")])
def test_a_delimited_file_reads_back_with_its_dialect(sep, decimal_comma, encoding):
    file = synthetic.delimited(sep=sep, decimal_comma=decimal_comma, encoding=encoding)
    rows = list(csv.reader(io.StringIO(file.data.decode(encoding)), delimiter=sep))
    assert rows[0] == [file.tables[0].caption[0]]
    assert tuple(tuple(r) for r in rows[1:]) == file.tables[0].rows
    assert ("µg/L" in rows[1][2]) and (("12,5" in rows[3]) == decimal_comma)
    if encoding == "utf-16":
        assert file.data[:2] in (b"\xff\xfe", b"\xfe\xff") and file.format == "tsv"
    if encoding == "cp1252":
        with pytest.raises(UnicodeDecodeError):
            file.data.decode("utf-8")


def test_a_zip_holds_its_members():
    members = (synthetic.delimited(), synthetic.scanned_pdf())
    file = synthetic.zipped(*members, name="batch.zip")
    archive = zipfile.ZipFile(io.BytesIO(file.data))
    assert archive.namelist() == ["concentrations.csv", "scanned.pdf"]
    assert [archive.read(m.name) for m in members] == [m.data for m in members]
    assert file.format == "zip" and file.values == ()


def test_the_filled_template_is_a_template_and_every_data_sheet_is_read():
    file = synthetic.template_workbook()
    workbook = read_workbook_bytes(file.data, file.name)
    assert is_template(workbook)
    read = read_client_workbook(workbook)
    assert read.issues == []
    assert {t.id for t in file.tables} == {f"template-{s.lower()}" for s in SHEETS} | {"template-readme"}
    (readme,) = [t for t in file.tables if t.id == "template-readme"]
    assert readme.kind == readme.spec.kind == "not_data" and readme.spec.not_data_reason
    assert not [v for v in file.values if v.table == "template-readme"]
    # the README's own lines with a number are the template's text: furniture, never outside numbers (SEAM-10)
    assert (file.outside, file.furniture) == ((), ("s:'README'!A1", "s:'README'!A3", "s:'README'!A4", "s:'README'!A9"))
    for sheet, rows in read.rows.items():
        (table,) = [t for t in file.tables if t.id == f"template-{sheet.lower()}"]
        assert len(rows) == len(table.rows) - 1 > 0


# --- the truth as a grid -------------------------------------------------------------------------------------------


def _all_files():
    return (*synthetic.delivery(), synthetic.pdf_report(), synthetic.template_workbook(),
            synthetic.delimited(sep="\t", decimal_comma=False, encoding="utf-16"))


def test_truth_grid_gives_each_truth_value_its_locator():
    for file in _all_files():
        for table in file.tables:
            grid = synthetic.truth_grid(file, table.id)
            assert (grid.n_rows, grid.n_cols) == (len(table.rows), len(table.rows[0])), table.id
            assert grid.region_id == check_id("region", grid.region_id)
            assert [c.text for c in grid.caption] == list(table.caption)
            assert [" | ".join(c.text for c in line) for line in grid.below] == list(table.below)
            for (r, c), cell in grid.cells.items():
                if cell.merged_from is None:
                    assert cell.text == table.rows[r - 1][c - 1], (table.id, r, c)
                else:
                    assert table.rows[r - 1][c - 1] == "" and cell.merged_from != cell.locator
            places = {cell.locator: (r, c) for (r, c), cell in grid.cells.items()}
            for value in (v for v in file.values if v.table == table.id):
                for locator in (value.locator, *(at for _role, at in value.locators)):
                    anchor = grid.anchor_of(locator)
                    assert parse_anchor(anchor).file_sha256 == hashlib.sha256(file.data).hexdigest()
                    assert same_place(parse_anchor(anchor).locator, parse_locator(locator))
                if value.locator in places:
                    r, c = places[value.locator]
                    assert grid.cell(r, c).merged_from is None
                    assert grid.anchor(r, c) == grid.anchor_of(value.locator)
                    assert value.value in grid.cell(r, c).text


def test_from_rows_places_a_grid_and_its_context_on_a_sheet():
    grid = RegionGrid.from_rows([["Time (h)", "Conc"], [0.5, "BLQ"], [1.0, 12.4037], [None, "12,5"]], first_cell="B4",
                                caption=["Study X"], above=[["note 1", "x"]], below=[["LLOQ 0.5 ng/mL"]])
    assert (grid.n_rows, grid.n_cols) == (4, 2)
    assert grid.cell(1, 1).locator == "s:'T'!B4" and grid.cell(2, 1).text == "0.5" and grid.cell(3, 1).text == "1"
    assert grid.cell(3, 2).text == "12.4037" and grid.cell(3, 2).type == "number"
    # typed as a sheet types them: a str is a text cell, its value as written; only an int or float is a stored number
    assert grid.cell(4, 2).type == "text" and grid.cell(4, 2).value == "12,5" and grid.cell(2, 2).type == "text"
    assert RegionGrid.from_rows([["<0.5", 0.5]]).cell(1, 1).type == "text"
    assert grid.cell(4, 1).type == "empty" and grid.cell(9, 9).locator == ""
    assert grid.context("caption", 1)[0].locator == "s:'T'!B3" and grid.context("caption", 2) == ()
    assert [c.locator for c in grid.context("above", 1)] == ["s:'T'!B2", "s:'T'!C2"]
    assert grid.context("below", 1)[0].locator == "s:'T'!B8" and grid.context("below", 0) == ()
    assert grid.anchor(2, 2).endswith("#s:'T'!C5") and grid.anchor_of("s:'T'!B8") == grid.anchor_of(grid.below[0][0].locator)
    with pytest.raises(AnchorError):
        grid.anchor_of("s:'T'!Z99")
    with pytest.raises(AnchorError):
        grid.anchor(4, 1)
    with pytest.raises(ValueError):
        RegionGrid.from_rows([["a"]], first_cell="A1", caption=["no room above A1"])
    # by default the region starts below its caption and the lines above; its default id is a region id
    titled = RegionGrid.from_rows([["Subject", "0.5"], ["001", "12.1"]], caption=["Study 230-23, 50 mg, fasted"],
                                  above=[["Sponsor X"]])
    assert titled.cell(1, 1).locator == "s:'T'!A3" and titled.context("caption", 1)[0].locator == "s:'T'!A2"
    assert titled.context("above", 1)[0].locator == "s:'T'!A1"
    assert check_id("region", titled.region_id) == titled.region_id
    assert RegionGrid.from_rows([["a"]]).cell(1, 1).locator == "s:'T'!A1"


def test_every_cell_with_a_number_of_a_synthetic_workbook_is_accounted_for():
    """In a truth table, in a truth table's context, declared outside, or the template's own text: nothing with a
    number is unaccounted."""
    for file in (synthetic.messy_workbook(), synthetic.template_workbook()):
        wb = load_workbook(io.BytesIO(file.data))
        accounted = set(file.outside) | set(file.furniture)
        for table in file.tables:
            sheet, cells = table.where[3:].split("'!")
            col0, row0, col1, row1 = range_boundaries(cells)
            accounted |= {format_locator(SheetCell(sheet=sheet.replace("''", "'"), cell=f"{ws_col}{r}"))
                          for r in range(row0, row1 + 1) for ws_col in _letters(col0, col1)}
            grid = synthetic.truth_grid(file, table.id)
            accounted |= {c.locator for c in (*grid.caption, *(c for line in (*grid.above, *grid.below) for c in line))}
        for ws in wb.worksheets:
            for row in ws.iter_rows():
                for cell in row:
                    if cell.value is not None and has_number(_cell_text(cell.value)):
                        locator = format_locator(SheetCell(sheet=ws.title, cell=cell.coordinate))
                        assert locator in accounted, (file.name, locator, cell.value)


def _letters(col0: int, col1: int) -> list[str]:
    from openpyxl.utils import get_column_letter

    return [get_column_letter(c) for c in range(col0, col1 + 1)]


def test_pdfplumber_is_available():
    major, minor = (int(p) for p in pdfplumber.__version__.split(".")[:2])
    assert (major, minor) >= (0, 11)
