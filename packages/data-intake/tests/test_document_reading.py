"""Reading a client's PDF or Word file (plan 2026-11-03 §3.4, I4): code's inventory of the pages, and the checks every
proposed fact passes (its quote states it; code converts the dose)."""

from __future__ import annotations

import pytest

from modeler_intake.document_reading import FactError, check_fact, check_quote, inventory, names_in, text_in

PAGES = [
    "Clinical Study Report\nProtocol EXZ-101 (Study 101)\nSubjects received a single oral dose of 10 mg after an overnight fast.",
    "Table 3: Mean (SD) plasma concentrations (ng/mL) by time (h)\n0.5 18.0 (4.1)\n1 42.0 (9.0)\nCmax 44.1 ng/mL",
    "Dissolution of the test tablet, USP 2 paddle, 50 rpm\nTime (min) % dissolved\n15 55",
    "Figure 2: Mean plasma concentration-time profile",
]


@pytest.mark.req("T-47")
def test_the_inventory_lists_what_each_page_holds_in_the_order_the_tag_asks_for():
    clinical = inventory(PAGES, "clinical")
    assert [(i.page, i.holds) for i in clinical][:3] == [(1, "design"), (2, "pk_table"), (2, "nca")]
    assert next(i for i in clinical if i.holds == "figure").page == 4
    assert "Table 3" in next(i for i in clinical if i.holds == "pk_table").line   # the page's own line, quoted
    formulation = inventory(PAGES, "formulation")
    assert formulation[0].holds == "dissolution" and formulation[0].page == 3


@pytest.mark.req("T-47")
@pytest.mark.parametrize(("fact", "value", "unit", "quote", "sets"), [
    ("dose", 10, "mg", "a single oral dose of 10 mg", {"dose_mg": 10.0, "dose_per_kg": False}),
    ("dose", 500, "µg", "an intravenous dose of 500 µg", {"dose_mg": 0.5, "dose_per_kg": False}),
    ("dose", 500, "mcg", "an intravenous dose of 500 mcg", {"dose_mg": 0.5, "dose_per_kg": False}),
    ("dose", 2, "mg/kg", "dosed at 2 mg/kg body weight", {"dose_mg": 2.0, "dose_per_kg": True}),
    ("n", 12, None, "Twelve healthy subjects (n = 12)", {"n": 12}),
    ("lloq", 0.5, "ng/mL", "LLOQ of 0.5 ng/mL", {"lloq": 0.5, "lloq_unit": "ng/mL"}),
    ("route", "iv_infusion", None, "as a 30-minute intravenous infusion", {"route": "iv_infusion"}),
    ("route", "oral", None, "one film-coated tablet", {"route": "oral"}),
    ("food_state", "fasted", None, "after an overnight fast", {"food_state": "fasted"}),
    ("food_state", "fed", None, "30 minutes after a high-fat breakfast", {"food_state": "fed"}),
    ("formulation", "mr", None, "the extended-release tablet", {"formulation": "mr"}),
    ("design", "MD", None, "once daily for 7 days", {"design": "MD"}),
])
def test_a_fact_its_quote_states_sets_the_study_record(fact, value, unit, quote, sets):
    assert check_fact(fact, value, unit, quote) == sets


@pytest.mark.req("T-47")
@pytest.mark.parametrize(("fact", "value", "unit", "quote", "problem"), [
    ("dose", 10, "mg", "a single oral dose of 5 mg", "must state the dose 10 mg"),
    ("dose", 10, "mg", "a single oral dose of 10 µg", "must state the dose 10 mg"),
    ("dose", 10, "tablets", "10 tablets", "dose unit"),
    ("n", 14, None, "Twelve healthy subjects (n = 12)", "number of subjects"),
    ("lloq", 0.5, "ng/mL", "LLOQ of 0.5 µg/L", "must state the LLOQ"),
    ("food_state", "fed", None, "after an overnight fast", "does not say food_state is fed"),
    ("route", "oral", None, "a 30-minute intravenous infusion", "does not say route is oral"),
    ("route", "subcutaneous", None, "a subcutaneous injection", "route 'subcutaneous'"),
    ("age", 30, None, "aged 30 years", "unknown fact"),
])
def test_a_fact_its_quote_does_not_state_is_refused_with_the_reason(fact, value, unit, quote, problem):
    with pytest.raises(FactError, match=problem):
        check_fact(fact, value, unit, quote)


@pytest.mark.req("T-47")
def test_names_and_quotes_are_checked_as_written():
    assert names_in("Protocol EXZ-101 (Study 101)", "EXZ 101", "study-101")    # case, spaces, punctuation aside
    assert not names_in("Protocol EXZ-101", "EXZ-101", "Study 101")
    assert text_in("USP 2 paddle", "Apparatus: USP 2 paddle at 50 rpm") and not text_in("basket", "USP 2 paddle")
    assert check_quote(PAGES[0], "single oral dose of 10 mg") is None
    assert check_quote(PAGES[0], "single oral dose of 20 mg") == "the quote is not on that page verbatim"
    assert check_quote(None, "anything at all") == "no such page in this file"
