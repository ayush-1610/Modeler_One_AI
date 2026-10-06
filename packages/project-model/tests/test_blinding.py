"""D-15: the blinding setting and what it withholds (the API applies it; test_plan_api covers the flow)."""

from __future__ import annotations

import pytest

from modeler_project.blinding import redact_dataset, redact_row, setting

pytestmark = pytest.mark.req("T-50")


def test_the_default_follows_the_model_risk_and_an_explicit_choice_wins():
    assert setting(None, "high")["on"] is True and setting(None, "medium")["on"] is False
    assert setting({"blinding": {"on": False, "reason": "client data are public"}}, "high") == {
        "on": False, "reason": "client data are public", "source": "project setting"}


def test_redaction_keeps_the_metadata_and_drops_the_values():
    dataset = {"study": {"study_id": "po-10", "dose_mg": 10}, "series": [{"times": [1, 2], "values": [3.0, None],
                                                                        "error": [0.1, 0.2]}],
               "reported": [{"parameter": "Cmax", "value": 4.2, "unit": "ng/ml"}]}
    out = redact_dataset(dataset)
    assert out["blinded"] and out["study"] == dataset["study"] and out["series"][0]["times"] == [1, 2]
    assert out["series"][0]["values"] == [None, None] and out["series"][0]["error"] is None
    assert out["reported"][0] == {"parameter": "Cmax", "value": None, "unit": "ng/ml"}
    assert redact_row({"study_id": "po-10", "profile": {"values": [1]}, "n": 12}) == {"study_id": "po-10", "n": 12,
                                                                                     "blinded": True}
