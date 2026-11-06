"""Start pre-filled from the proposal's own words where the intake agent left a field empty (the owner, 2026-11-06:
"making sure everything is there; the user will just see through and only change in case ... wrong"). A synthetic
proposal modelled on a generic ER product (software test data, made-up text)."""

from __future__ import annotations

import pytest

from modeler_project import FileProjectStore, Workspace
from modeler_project.brief import FieldStatus, empty_brief
from modeler_project.brief_ops import edit_field
from modeler_project.documents import DocumentLibrary
from modeler_project.start_drafts import read_for_start

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
    assert (value["scope.pbpk_model"], value["scope.site_of_action"]) == ("full", "systemic")     # the builder's defaults
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
    assert paths == ["scope.pbpk_model", "scope.site_of_action"]
