"""Messy client deliveries scored end to end (plan 2026-11-05 §4 step 5): each sheet placed right, read right, asking
only what it does not say, its record of what was left out holding what it must, and no sheet silent. Code alone (agents
off); software test data with made-up numbers."""

from __future__ import annotations

import pytest

from modeler_project import FileProjectStore, Workspace
from modeler_project.arrival_eval import DELIVERIES, score

pytestmark = pytest.mark.req("T-47")


@pytest.mark.parametrize("delivery", DELIVERIES, ids=[d.name for d in DELIVERIES])
def test_each_messy_delivery_is_read_as_its_answer_says(delivery, tmp_path):
    result = score(delivery, Workspace(FileProjectStore(tmp_path), "t1", "p1"))
    assert result.perfect, f"missed {result.missed}; unexpected {result.unexpected}"
    assert len(result.found) >= 3 * len([s for s in delivery.sheets if s.place != "not data"])


def test_a_data_sheet_no_reading_accounts_for_is_said_silent(tmp_path, monkeypatch):
    # the "nothing silent" check itself: with code's reading on arrival switched off, the data sheet is caught
    from modeler_project import sheet_intake

    monkeypatch.setattr(sheet_intake, "read_on_arrival", lambda *args, **kwargs: {})
    delivery = next(d for d in DELIVERIES if "shipping log" in d.name)
    result = score(delivery, Workspace(FileProjectStore(tmp_path), "t1", "p1"))
    assert result.unexpected == ["silent EX-77 bioanalysis.xlsx!Conc"] and not result.perfect
