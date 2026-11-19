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
               "reported": [{"parameter": "Cmax", "value": 4.2, "unit": "ng/ml", "variability": "0.6 SD", "quote": "4.2 (0.6)"}],
               "quote": "[Fasting row 4] A4=001 | B4=BLQ | C4=3.0", "note": "confirmed on Delivery (cf-3); 3.0 read",
               "decision_reason": "Cmax 4.2 as reported", "source": {"locator": "Fasting!4:9", "title": "a.xlsx"},
               "digitization": {"page": 2, "pixels": {"mean": [[10.0, 20.0]]}, "calibration": {"x": {}, "y": {}}}}
    out = redact_dataset(dataset)
    assert out["blinded"] and out["study"] == dataset["study"] and out["series"][0]["times"] == [1, 2]
    assert out["series"][0]["values"] == [None, None] and out["series"][0]["error"] is None
    # round 7: the reported PK's spread and quote, the dataset's quote (its sheet's first row) and note, the picked points
    # and the reason's digits go too; the place in the file, the source and the calibration stay
    assert out["reported"][0] == {"parameter": "Cmax", "value": None, "unit": "ng/ml", "variability": "", "quote": ""}
    assert (out["quote"], out["note"], out["decision_reason"]) == ("[Fasting row 4]", "", "Cmax •.• as reported")
    assert out["source"] == dataset["source"] and out["digitization"] == {**dataset["digitization"], "pixels": {}}
    assert redact_dataset({**dataset, "quote": "Table 2: Cmax 4.2"})["quote"] == ""      # a quote that is no row: left out
    assert redact_row({"study_id": "po-10", "profile": {"values": [1]}, "n": 12}) == {"study_id": "po-10", "n": 12,
                                                                                     "blinded": True}


def test_the_list_says_why_each_study_is_on_it(tmp_path, monkeypatch):
    """Round 4: why a study is on the project's blinding list, in words (a card the list withholds says it): the plan's
    S5 or S6, the study split's before a plan, a dataset entered for external validation; the list is these studies."""
    from modeler_project import FileProjectStore, Workspace, blinding, roles
    from modeler_project import plan as plan_module

    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    monkeypatch.setattr(roles, "proposed_roles", lambda _ws: {"230-25": "S5", "230-26": "S6", "230-23": "S3"})
    monkeypatch.setattr(plan_module, "current", lambda _ws: (None, None))
    assert blinding.external_why(ws) == {"230-25": "the study split proposes it for S5 (external validation), before a plan",
                                         "230-26": "the study split proposes it for S6 (the application), before a plan"}
    monkeypatch.setattr(plan_module, "current", lambda _ws: (None, object()))
    assert blinding.external_why(ws)["230-25"] == "the plan places it in S5 (external validation)"
    assert blinding.external_studies(ws) == {"230-25", "230-26"}
    assert blinding.listed_why(ws, {"blinding": {"on": True}}, None) == blinding.external_why(ws)
    assert blinding.listed_why(ws, {"blinding": {"on": False}}, None) == {}
    assert blinding.blinded_studies(ws, {"blinding": {"on": True}}, None) == {"230-25", "230-26"}
