"""Start pre-filled from the proposal's own words where the intake agent left a field empty (the owner, 2026-11-06:
"making sure everything is there; the user will just see through and only change in case ... wrong"). A synthetic
proposal modelled on a generic ER product (software test data, made-up text)."""

from __future__ import annotations

import pytest

from modeler_project import FileProjectStore, Workspace
from modeler_project.brief import FieldStatus, empty_brief
from modeler_project.brief_ops import edit_field
from modeler_project.documents import DocumentLibrary
from modeler_project.start_drafts import LINEAR, read_for_start

pytestmark = pytest.mark.req("T-41")

PROPOSAL = """Technical proposal: PBPK modelling support for Exampleamide Succinate ER Tablets

1. Introduction
Exampleamide Succinate Extended Release Tablets are being developed in two strengths: 50 mg and 100 mg for the Canadian market.
Two pilot bioequivalence studies in healthy volunteers (single oral dose, fasting) showed a lower Cmax for the test product.

2. Objective
The objective of this work is to develop and verify a PBPK model of exampleamide and to evaluate, through virtual bioequivalence trials, whether the test formulation is bioequivalent to the reference product.

3. Scope
The dissolution profiles of both products in 900 mL phosphate buffer solution pH 6.8 will be used as input.
The modelling results are intended to support the regulatory submission to Health Canada.
"""


@pytest.fixture
def library(tmp_path) -> DocumentLibrary:
    lib = DocumentLibrary(Workspace(FileProjectStore(tmp_path), "t1", "p1"))
    lib.add(PROPOSAL.encode(), "Technical Proposal.md", role="proposal", by="u")
    return lib


def test_every_start_field_the_agent_left_empty_is_drafted_from_the_proposals_words(library):
    brief, paths = read_for_start(library, empty_brief("Exampleamide", by="u"))
    value = {p: brief.get(p).value for p in paths}
    assert value["qoi.text"].startswith("The objective of this work is to develop and verify a PBPK model")
    assert value["qoi.context_of_use"] == "The modelling results are intended to support the regulatory submission to Health Canada."
    assert value["qoi.applications"] == ["APP-14 virtual bioequivalence", "APP-11 absorption and formulation"]
    assert value["scope.formulation_types"] == ["mr"]                  # extended release; the buffer solution is a medium
    assert value["scenarios[0].route"] == "oral"
    # one scenario per strength the proposal names (the owner, 2026-11-08), each fasting as the proposal says
    assert [(value[f"scenarios[{i}].dose"], value[f"scenarios[{i}].route"]) for i in (0, 1)] == [(50.0, "oral"), (100.0, "oral")]
    assert value["scenarios[0].food_state"] == value["scenarios[1].food_state"] == "fasted"
    assert brief.get("scenarios[1].dose").citations[0].quote.startswith("Exampleamide Succinate Extended Release Tablets")
    assert (value["scope.pbpk_model"], value["scope.site_of_action"]) == ("full", "systemic")     # the builder's defaults
    assert value["drug.modality"] == "small_molecule"                  # an ER tablet
    for path in paths:
        record = brief.get(path)
        assert record.status is FieldStatus.DRAFTED and brief.value(path) is None and "read by code" in record.note
    for path in ("qoi.text", "qoi.context_of_use", "scope.formulation_types", "scenarios[0].route"):
        cite = brief.get(path).citations[0]
        assert cite.page == 1 and cite.quote in " ".join(PROPOSAL.split()) and cite.quote.endswith(".")   # a sentence
    assert brief.get("scope.formulation_types").citations[0].quote.startswith("Exampleamide Succinate Extended Release")
    assert not brief.get("scope.pbpk_model").citations                 # a default rests on no quote, and says so


def test_what_a_person_or_the_agent_set_is_kept(library):
    brief = edit_field(empty_brief("Exampleamide", by="u"), "qoi.text", value="my own question", status=FieldStatus.EDITED, by="u")
    brief, paths = read_for_start(library, brief)
    assert "qoi.text" not in paths and brief.value("qoi.text") == "my own question"
    _again, more = read_for_start(library, brief)
    assert more == []                                                  # its own drafts are not drafted twice


def test_with_no_proposal_only_the_defaults_are_drafted(tmp_path):
    empty = DocumentLibrary(Workspace(FileProjectStore(tmp_path), "t1", "p2"))
    _brief, paths = read_for_start(empty, empty_brief("Exampleamide", by="u"))
    assert paths == ["scope.pbpk_model", "scope.site_of_action"]       # no structure, no product: no modality


# The drug's disposition (the owner, 2026-11-07: "it still does not fill all"): the proposal first, else the FDA label
# code stored at the project's start. Made-up label text in the style of a pharmacokinetics section.
LABEL = """12.3 Pharmacokinetics
The single-dose pharmacokinetics of exampleamide are linear and dose-proportional in a dose range of 50 to 600 mg/day.
Metabolism: Exampleamide is primarily metabolized by conjugation (mediated by UGT isoforms) and, to a minor extent, through oxidative metabolism.
CYP3A4 is the cytochrome P450 isozyme mediating the oxidative metabolism (N-demethylation) of exampleamide.
The CYP2D6 metabolic pathway is not involved.
Elimination: Approximately 45% of exampleamide is excreted unchanged in urine at 72 hours after oral administration.
"""


def test_the_disposition_the_proposal_is_silent_on_is_drafted_from_the_fda_label(library):
    library.add_text(LABEL, "fda-label-exampleamide-20240101.txt", role="retrieved_record", by="system")
    brief, paths = read_for_start(library, empty_brief("Exampleamide", by="u"))
    for path in ("drug.bcs_class",):
        assert path not in paths                                       # neither says it: left for the person
    assert brief.get("scope.pathways_stated").value == ["UGT", "CYP3A4"]          # CYP2D6 "is not involved"
    assert brief.get("scope.pathways").value == ["hepatic_metabolism", "renal_filtration"]
    assert brief.get("scope.nonlinearity").value == LINEAR                       # Start shows "no": linear PK
    assert "scope.ehc" not in paths                                    # not stated anywhere: "not stated" stays
    for path in ("scope.pathways", "scope.pathways_stated", "scope.nonlinearity"):
        record = brief.get(path)
        assert record.status is FieldStatus.DRAFTED and brief.value(path) is None
        assert "from the FDA label (the proposal does not state it)" in record.note
        assert all(c.source == "FDA label" and c.quote in " ".join(LABEL.split()) for c in record.citations)


def test_what_the_proposal_states_of_the_disposition_wins_over_the_label(tmp_path):
    lib = DocumentLibrary(Workspace(FileProjectStore(tmp_path), "t1", "p3"))
    lib.add((PROPOSAL + "\n4. The drug\nExampleamide is a BCS Class III compound. Exposure increases less than dose-proportionally "
             "above 200 mg because of saturable absorption. Enterohepatic recirculation of the glucuronide was reported.\n").encode(),
            "Technical Proposal.md", role="proposal", by="u")
    lib.add_text(LABEL, "fda-label-exampleamide-20240101.txt", role="retrieved_record", by="system")
    brief, _paths = read_for_start(lib, empty_brief("Exampleamide", by="u"))
    assert brief.get("drug.bcs_class").value == "III"
    assert brief.get("scope.nonlinearity").value.startswith("Exposure increases less than dose-proportionally")
    assert brief.get("scope.ehc").value is True
    assert "from the proposal" in brief.get("scope.nonlinearity").note
    assert brief.get("scope.pathways_stated").value == ["UGT", "CYP3A4"]          # the proposal names none: the label's


def test_a_persons_not_stated_or_no_is_never_drafted_over(library):
    library.add_text(LABEL, "fda-label-exampleamide-20240101.txt", role="retrieved_record", by="system")
    brief = edit_field(empty_brief("Exampleamide", by="u"), "scope.nonlinearity", value=None, status=FieldStatus.NOT_APPLICABLE,
                       by="u")
    brief = edit_field(brief, "scope.pathways", value=None, status=FieldStatus.MISSING, by="u")
    brief, paths = read_for_start(library, brief)
    assert "scope.nonlinearity" not in paths and "scope.pathways" not in paths
    assert brief.get("scope.nonlinearity").status is FieldStatus.NOT_APPLICABLE
