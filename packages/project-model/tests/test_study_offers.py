"""What a study's data sheet does not say, offered from the project (build L; the owner, 2026-11-08). Made-up text."""

from __future__ import annotations

import pytest

from modeler_project.brief import Citation, FieldStatus, empty_brief
from modeler_project.brief_ops import agent_set
from modeler_project.start_drafts import Sentence
from modeler_project.study_offers import Context, offers, preselect

pytestmark = pytest.mark.req("T-47")

PROPOSAL = Citation(doc_sha256="a" * 64, page=1, quote="two strengths: 50 mg and 100 mg", source="Technical Proposal.pdf")
BE = (("external_validation", "Bioequivalence study data (reference arm at least)", "REQ-vbe.be_study"),)


def _brief():
    brief = empty_brief("Exampleamide", by="u")
    for path, value in (("scenarios[0].dose", 50.0), ("scenarios[1].dose", 100.0), ("scope.formulation_types", ["mr"])):
        brief = agent_set(brief, path, value=value, unit=None, citations=(PROPOSAL,), status=FieldStatus.DRAFTED,
                          confidence=None, by="code:start-reading")
    return brief


def _sentence(text: str, source: str = "Technical Proposal.pdf") -> Sentence:
    return Sentence(text, "b" * 64, 2, source)


NEEDS = ["dose", "n", "formulation", "purpose"]


def test_with_no_document_naming_the_study_start_and_the_data_plan_answer_what_they_can():
    found = offers(Context((), _brief(), BE), "093-26-TEST", NEEDS)
    assert [o["value"] for o in found["dose"]] == ["50", "100"] and preselect(found["dose"]) is None   # which strength?
    assert preselect(found["formulation"]) == "mr" and "the proposal's product on Start" in found["formulation"][0]["label"]
    assert preselect(found["purpose"]) == "external_validation"
    assert "REQ-vbe.be_study" in found["purpose"][0]["label"] and found["purpose"][0]["source"] is None
    assert "n" not in found                                            # nothing holds it: the person gives it


def test_a_document_naming_the_study_gives_the_dose_the_subjects_and_the_form_with_its_quote():
    ctx = Context((_sentence("Study 093/26 enrolled 24 healthy subjects."),
                   _sentence("In study 093-26 each subject received one 100 mg extended-release tablet, fasting."),
                   _sentence("Study 230-23 used the 50 mg strength."),                 # another study: not read here
                   _sentence("Doses of 50 mg and 100 mg were given.", "093-26 Protocol.pdf")),   # two doses: not read
                  _brief(), BE)
    found = offers(ctx, "093-26-TEST", NEEDS)
    assert preselect(found["dose"]) == "100" and found["dose"][0]["document"] and found["dose"][0]["source"]["page"] == 2
    assert [o["value"] for o in found["dose"]] == ["100", "50"]        # the document's first, then Start's other strength
    assert preselect(found["n"]) == "24"
    assert preselect(found["formulation"]) == "mr"
    assert "Study 093-26" not in found["dose"][0]["label"] and "Technical Proposal.pdf, p. 2" in found["dose"][0]["label"]


def test_a_study_named_without_a_number_or_outside_a_bioequivalence_project_gets_no_guess():
    assert offers(Context((_sentence("The pilot study enrolled 12 subjects."),), None, ()), "PILOT", NEEDS) == {}
    no_plan = offers(Context((), _brief(), ()), "093-26-TEST", ["purpose"])
    assert no_plan == {}                                               # no bioequivalence item in the data plan
    iv = offers(Context((), _brief(), BE), "093-26-IV", ["purpose"])
    assert iv == {}                                                    # an IV study is not a test or reference arm


def test_the_number_of_subjects_is_counted_from_the_sheets_own_subject_columns():
    points = {"series": [{"name": f"00{i} / I", "statistic": "individual"} for i in range(1, 7)]
              + [{"name": "Mean", "statistic": "mean", "n": None}]}
    found = offers(Context((), None, ()), "230-23-REF", ["n"], points)
    assert preselect(found["n"]) == "6" and "6 subjects' columns (001 / I … 006 / I)" in found["n"][0]["label"]
    verified = offers(Context((), None, ()), "230-23-REF", ["n"], {"series": [{"name": "Mean", "statistic": "mean", "n": 24}]})
    assert preselect(verified["n"]) == "24"
    assert offers(Context((), None, ()), "230-23-REF", ["n"], {"series": [{"name": "Mean", "statistic": "mean"}]}) == {}
