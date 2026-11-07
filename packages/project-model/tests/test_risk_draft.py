"""The ICH M15 ratings drafted by the rule `m15_draft.yaml` when the intake agent left them empty (the owner, 2026-11-07;
the rule approved the same day, UNVERIFIED). Made-up contexts of use."""

from __future__ import annotations

import pytest

from modeler_project.brief import FieldStatus, empty_brief
from modeler_project.brief_ops import agent_set, edit_field
from modeler_project.risk_draft import draft_risk, ruleset

pytestmark = pytest.mark.req("T-50")


def _brief(use: str, *, question: str = "Exposure of the ER tablet after a single oral dose", apps=()):
    brief = empty_brief("Exampleamide", by="u")
    for path, value in (("qoi.text", question), ("qoi.context_of_use", use), ("qoi.applications", list(apps) or None)):
        if value:
            brief = agent_set(brief, path, value=value, unit=None, citations=(), status=FieldStatus.DRAFTED, confidence=None,
                              by="code:start-reading")
    return brief


def _drafts(brief) -> dict[str, object]:
    return {p: brief.get(p).value for p in ("m15.influence_suggested", "m15.consequence_suggested", "m15.risk_justification")}


def test_a_model_in_place_of_a_clinical_study_is_high_influence_and_the_stricter_tier_is_given_its_reason():
    brief, paths = draft_risk(_brief("Virtual bioequivalence in lieu of a clinical BE study for the 50 mg strength."))
    assert _drafts(brief)["m15.influence_suggested"] == "high" and _drafts(brief)["m15.consequence_suggested"] == "medium"
    assert "the stricter, high" in _drafts(brief)["m15.risk_justification"]
    assert "stands in place of a clinical study" in brief.get("m15.influence").value
    for path in paths:
        record = brief.get(path)
        assert record.status is FieldStatus.DRAFTED and brief.value(path) is None      # never a rating until saved
        assert record.by == "code:m15-draft-rule" and "m15_draft 0.1 (UNVERIFIED)" in record.note


def test_a_submission_alongside_clinical_data_is_medium_and_children_raise_the_consequence():
    brief, _paths = draft_risk(_brief("The results support the regulatory submission to Health Canada.",
                                      apps=["APP-06 pediatric extrapolation"]))
    assert (_drafts(brief)["m15.influence_suggested"], _drafts(brief)["m15.consequence_suggested"]) == ("medium", "high")
    assert "children" in brief.get("m15.consequence").value
    assert "the stricter, high: the decision consequence is high" in brief.get("m15.risk_justification").value


def test_internal_use_is_low_and_a_narrow_therapeutic_index_stated_in_the_proposal_is_read():
    brief, _paths = draft_risk(_brief("To guide the formulation team's choice between two prototypes."))
    assert (_drafts(brief)["m15.influence_suggested"], _drafts(brief)["m15.consequence_suggested"]) == ("low", "medium")
    nti, _ = draft_risk(_brief("To guide the formulation team's choice between two prototypes."),
                        proposal=["Exampleamide has a narrow therapeutic index.", "Patients were treated for 4 weeks."])
    assert nti.get("m15.consequence_suggested").value == "high"
    assert "narrow therapeutic index" in nti.get("m15.consequence").value


def test_acronyms_are_read_as_words_only():
    # "patients" holds "nti", "standard" holds "nda": neither is a narrow therapeutic index or a new drug application
    brief, _paths = draft_risk(_brief("A standard exploratory analysis for the patients in the team's own trials."))
    assert (_drafts(brief)["m15.influence_suggested"], _drafts(brief)["m15.consequence_suggested"]) == ("low", "medium")


def test_nothing_is_drafted_over_the_agents_suggestion_a_persons_rating_or_without_a_context_of_use():
    agent = agent_set(_brief("in lieu of a clinical study"), "m15.influence_suggested", value="medium", unit=None, citations=(),
                      status=FieldStatus.DRAFTED, confidence=None, by="agent:r1")
    assert draft_risk(agent)[1] == []
    rated = edit_field(_brief("in lieu of a clinical study"), "m15.influence_rating", value="low", status=FieldStatus.EDITED,
                       by="u")
    assert draft_risk(rated)[1] == []
    assert draft_risk(_brief(""))[1] == []


def test_the_rule_is_provisional_and_versioned():
    rules = ruleset()
    assert (rules["version"], rules["status"]) == ("0.1", "UNVERIFIED")
    assert [r.rating for r in rules["influence"]] == ["high", "medium", "low"]
