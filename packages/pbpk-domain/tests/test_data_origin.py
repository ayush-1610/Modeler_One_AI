"""T-46: the real-data rule (plan §9.4, D-19). Only real observed data can sign off a model."""

from __future__ import annotations

import pytest

from pbpk_domain.data_origin import TEST_ONLY, real_data_summary, signature_refusal

pytestmark = pytest.mark.req("T-46")


def _study(study_id: str, *, observed: bool = True) -> dict:
    return {"study_id": study_id, "observed_auc": 10.0 if observed else None, "observed_cmax": None}


def test_real_judged_studies_are_passable_and_counted_by_origin():
    summary = real_data_summary({"a": "CLIENT", "b": "LITERATURE", "c": "CLIENT"},
                                [_study("a"), _study("b"), _study("c")])
    assert summary["passable"] and summary["real"] == 3 and summary["byOrigin"] == {"CLIENT": 2, "LITERATURE": 1}
    assert summary["label"] == ""


def test_synthetic_or_illustrative_data_is_test_only():
    only = real_data_summary({"a": "SYNTHETIC", "b": "ILLUSTRATIVE"}, [_study("a"), _study("b")])
    assert not only["passable"] and only["label"] == TEST_ONLY and only["notReal"] == ["a", "b"]
    mixed = real_data_summary({"a": "SYNTHETIC", "b": "CLIENT"}, [_study("a"), _study("b")])
    assert not mixed["passable"] and mixed["real"] == 1 and mixed["label"] == "1 of 2 judged studies are test data"


def test_an_unrecorded_origin_is_not_taken_as_real():
    summary = real_data_summary({"a": None, "b": "nonsense"}, [_study("a"), _study("b")])
    assert not summary["passable"] and summary["byOrigin"] == {"UNRECORDED": 2}
    assert summary["label"] == "origin not recorded for 2 of 2 judged studies"


def test_a_study_without_observed_data_is_not_evaluable():
    summary = real_data_summary({"a": "CLIENT"}, [_study("a"), _study("b", observed=False)])
    assert summary["passable"] and summary["judged"] == 1 and summary["notEvaluable"] == ["b"]
    nothing = real_data_summary({}, [_study("b", observed=False)])
    assert not nothing["passable"] and nothing["label"] == "not evaluable: no observed data"


def test_the_signature_is_refused_outside_an_exploratory_project():
    test_only = {"S1": real_data_summary({"a": "SYNTHETIC"}, [_study("a")]),
                 "S4": real_data_summary({"b": "CLIENT"}, [_study("b")])}
    refusal = signature_refusal(test_only, exploratory=False)
    assert refusal and "S1: TEST ONLY" in refusal and "(a)" in refusal and "S4" not in refusal
    assert signature_refusal(test_only, exploratory=True) is None
    assert signature_refusal({"S4": test_only["S4"]}, exploratory=False) is None
