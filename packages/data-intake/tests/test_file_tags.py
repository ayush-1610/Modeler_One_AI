"""File tags at upload (docs/plans/2026-11-03-inputs-and-client-data.md §3.1): code pre-fills a tag from the file's name
and proposes another from its content, quoting what prompted it; it never decides."""

from __future__ import annotations

import pytest

from modeler_intake.file_tags import default_tag, from_pages, from_triage, guess_from_name

pytestmark = pytest.mark.req("T-47")


@pytest.mark.parametrize(("name", "kind"), [
    ("Examplazine_technical_proposal.pdf", "proposal"),
    ("EXZ-101_PK_concentrations.xlsx", "clinical"),
    ("EXZ-101_CSR_synopsis.pdf", "clinical"),
    ("Dissolution_report_B2045_B2051.pdf", "formulation"),
    ("Bioanalytical_validation_LCMS.docx", "bioanalytical"),
    ("In_vitro_ADME_summary.xlsx", "in_vitro"),
    ("caco2_permeability.csv", "in_vitro"),
    ("Data_Q3_final.xlsx", None),
])
def test_the_name_prefills_the_tag(name, kind):
    assert guess_from_name(name) == kind


def test_an_untagged_client_file_is_its_names_kind_or_other():
    assert default_tag("Data_Q3_final.xlsx") == "other"
    assert default_tag("proposal_annex.pdf") == "other"       # a client file is never "proposal"
    assert default_tag("pk_profiles.csv") == "clinical"


def test_a_workbook_proposes_the_kind_most_of_its_sheets_hold_with_the_header_quoted():
    rows = [{"sheet": "Conc", "category": "PK_INDIVIDUAL", "evidence_cell": "Conc!A1", "evidence_quote": "Subject"},
            {"sheet": "Dosing", "category": "STUDIES", "evidence_cell": "", "evidence_quote": ""},
            {"sheet": "Notes", "category": "OTHER", "evidence_cell": "", "evidence_quote": ""}]
    hint = from_triage(rows)
    assert hint is not None and hint.kind == "clinical"
    assert "“Conc”" in hint.why and "Conc!A1" in hint.why and "2 of 2 data sheets" in hint.why
    tie = [{"sheet": "Diss", "category": "DISSOLUTION"}, {"sheet": "Conc", "category": "PK_INDIVIDUAL"}]
    assert from_triage(tie) is None and from_triage([{"sheet": "N", "category": "OTHER"}]) is None


def test_a_document_proposes_a_kind_only_when_its_text_says_so_clearly():
    report = ["Dissolution report. Batch B2045.", "USP apparatus II (paddle) at 50 rpm; % dissolved at 30 min."]
    hint = from_pages(report)
    assert hint is not None and hint.kind == "formulation" and "(page 1)" in hint.why and "paddle" in hint.why
    assert from_pages(["Minutes of the kick-off meeting."]) is None
    assert from_pages([]) is None                                   # a scan has no text: nothing is proposed
