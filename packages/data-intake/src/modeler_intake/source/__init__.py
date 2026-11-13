"""Parse once, locate, resolve (docs/plans/2026-11-12-intake-contracts.md §6.1; build D2).

A client file is parsed once into a `SourceDocument` (`source_model`, §4.2): every sheet cell, PDF word and ruled table
with its box, the Word body in order, the figures, the regions located in it by rule (tables, prose, unruled tables,
figures) and what lies outside them. Every value is later read from `region_grid` and anchored (§4.1); `resolve`,
`check_anchors` and `source_view` read an anchor back against the same or a newer parse.

    parse.py      parser_for, parse_document, zip_members, the limits and reading parameters
    workbook.py   .xlsx/.xlsm (openpyxl) and .xls (xlrd) cells, number formats, merges, hidden sheets
    delimited.py  .csv/.tsv: encoding and delimiter by the standard library
    docx.py       Word body, tables as grids, figures; tables, captions, context and prose located
    pdf.py        pdfplumber words, ruled tables, images, OCR need; continued tables, furniture, prose located
    text.py       .txt/.md/.json lines
    archive.py    ZIP members, one nested level, limits
    regions.py    sheet location, region ids, region_grid, paragraphs, as_workbook_grid
    roles.py      document role and table kind by rule
    resolve.py    resolve, check_anchors, source_view
    inventory.py  the format inventory of a set of files
"""

from modeler_intake.source.inventory import FormatInventory, inventory
from modeler_intake.source.parse import (
    MAX_MEMBER_BYTES,
    MAX_MEMBERS,
    MAX_TOTAL_BYTES,
    NEEDS_OCR_MAX_CHARS,
    SOURCE_VERSION,
    TABLE_LIKE_NUMERIC_SHARE,
    parse_document,
    parser_for,
    zip_members,
)
from modeler_intake.source.regions import as_workbook_grid, paragraphs, region_grid
from modeler_intake.source.resolve import check_anchors, resolve, source_view

__all__ = [
    "MAX_MEMBERS",
    "MAX_MEMBER_BYTES",
    "MAX_TOTAL_BYTES",
    "NEEDS_OCR_MAX_CHARS",
    "SOURCE_VERSION",
    "TABLE_LIKE_NUMERIC_SHARE",
    "FormatInventory",
    "as_workbook_grid",
    "check_anchors",
    "inventory",
    "paragraphs",
    "parse_document",
    "parser_for",
    "region_grid",
    "resolve",
    "source_view",
    "zip_members",
]
