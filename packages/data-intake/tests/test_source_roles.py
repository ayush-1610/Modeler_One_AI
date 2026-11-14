"""Document role and table kind by rule (contracts §6.1 "Role and kind"), each with the evidence that decided it: the
locator of the deciding cell or line, and its words."""

from __future__ import annotations

import io

import pytest
from openpyxl import Workbook

from modeler_intake import synthetic
from modeler_intake.anchors import anchor_text
from modeler_intake.client_template import TEMPLATE_ID
from modeler_intake.source import parse_document, resolve

pytestmark = pytest.mark.req("T-47")


def _evidence_resolves(doc, evidence: str) -> None:
    """The evidence's locator resolves in the document to a text holding its quote."""
    locator, quote = evidence.split(": ", 1)
    found = resolve(doc, anchor_text(doc.file_sha256, doc.parser, doc.parser_version, locator))
    assert quote.split(" (")[0] in found.text or found.text in quote, (evidence, found.text)


@pytest.mark.parametrize(("build", "role", "evidence"), [
    (synthetic.messy_workbook, "data_workbook", "8 table regions: s:'Fasting'!A2:G14"),
    (synthetic.template_workbook, "client_template", "s:'README'!A1: ModelerOne_ClientData_v1"),
    (synthetic.delimited, "concentration_listing", "s:'concentrations'!A2: Subject"),
    (synthetic.pdf_report, "study_report", "p:1/w:1-4@"),
    (synthetic.scanned_pdf, "certificate_of_analysis", "p:1/w:1-6@"),
    (synthetic.word_report, "study_report", "d:p:1/ch:0-12: Study design"),
])
def test_the_document_role_is_decided_by_rule_with_its_evidence(build, role, evidence):
    file = build()
    doc = parse_document(file.data, file.name)
    assert doc.role == role
    assert doc.role_evidence.startswith(evidence)
    if doc.role_evidence.startswith(("s:", "p:", "d:")):
        _evidence_resolves(doc, doc.role_evidence)


def test_each_table_kind_is_triages_on_the_regions_own_grid_with_the_deciding_cell():
    undecided = {"dissolution-summary": "undecided between DISSOLUTION and PK_SUMMARY",
                 "summary-parameters": "undecided between PK_SUMMARY and PK_PARAMETERS"}
    for file in (*synthetic.delivery(), synthetic.template_workbook()):
        doc = parse_document(file.data, file.name)
        regions = {r.id: r for r in doc.regions}
        for table in file.tables:
            region = regions[synthetic.truth_grid(file, table.id).region_id]
            if table.id in undecided:                    # a tie in triage's words: unknown, and the note says why
                assert (region.table_kind, region.kind_evidence) == ("unknown", undecided[table.id])
                continue
            assert region.table_kind == table.kind, table.id
            _evidence_resolves(doc, region.kind_evidence)
        for region in doc.regions:
            if region.kind != "table":
                assert (region.table_kind, region.kind_evidence) == ("unknown", "")


def test_the_deciding_cell_is_the_regions_own_even_with_two_tables_on_a_sheet():
    file = synthetic.messy_workbook()
    doc = parse_document(file.data, file.name)
    individual, metabolite = [r for r in doc.regions if r.where.startswith("s:'Fasting'!")]
    assert individual.kind_evidence == "s:'Fasting'!A2: Subject" and individual.table_kind == "pk_individual"
    assert metabolite.kind_evidence.startswith("s:'Fasting'!A20: Table 2.") and metabolite.table_kind == "pk_summary"


def test_a_templates_sheets_are_known_by_their_name_and_its_guide_is_not_data():
    file = synthetic.template_workbook()
    doc = parse_document(file.data, file.name)
    kinds = {r.where.split("!")[0]: (r.table_kind, r.kind_evidence) for r in doc.regions}
    assert kinds["s:'README'"] == ("not_data", "s:'README'!A1: ModelerOne_ClientData_v1 (the template's column guide)")
    assert kinds["s:'Studies'"] == ("study_design", "s:'Studies'!A1: study_id* (template sheet)")
    assert kinds["s:'Urine_Feces'"][0] == "excretion"


@pytest.mark.parametrize("written", [TEMPLATE_ID + " ", " " + TEMPLATE_ID, TEMPLATE_ID])
def test_a_readme_whose_template_id_carries_spaces_is_the_template_and_never_raises(written):
    workbook = Workbook()
    workbook.active.title = "README"
    workbook.active["A1"] = written
    out = io.BytesIO()
    workbook.save(out)
    doc = parse_document(out.getvalue(), "readme only.xlsx")                    # no template sheet beside it
    assert doc.state == "read" and doc.role == "client_template"
    assert doc.role_evidence == f"s:'README'!A1: {TEMPLATE_ID}"
    _evidence_resolves(doc, doc.role_evidence)
