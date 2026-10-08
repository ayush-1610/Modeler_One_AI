"""The deterministic quote checks applied to every value an agent or a person cites (moved from the agents package)."""

from __future__ import annotations

from modeler_intake.citations import quote_appears_in, value_stated_in_quote

PAGE = (
    "Plasma protein binding was determined by equilibrium dialysis. The fraction un-\n"
    "bound in human plasma was 3.1% (n = 6) and was independent of concentration."
)


def test_quote_matching_tolerates_layout_but_not_edits():
    assert quote_appears_in(PAGE, "The fraction unbound in human plasma was 3.1%")
    assert not quote_appears_in(PAGE, "The fraction unbound in human plasma was 2.1%")
    assert not quote_appears_in(PAGE, "3.1%")


def test_value_statement_detection():
    assert value_stated_in_quote(0.031, "was 3.1% (n = 6)")
    assert value_stated_in_quote(3.1, "was 3.1% (n = 6)")
    assert not value_stated_in_quote(0.05, "was 3.1% (n = 6)")
