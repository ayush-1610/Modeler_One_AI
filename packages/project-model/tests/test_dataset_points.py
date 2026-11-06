"""Build C (plan 2026-11-05 §3.2): a dataset on its study's card as data: its points, and code's statistics of each
profile series by the platform's NCA (software test data)."""

from __future__ import annotations

import pytest

from modeler_project.blinding import redact_dataset
from modeler_project.dataset_points import card_points
from modeler_project.datasets import ObservedDataset, Origin, ReportedPK, Series, new_dataset_id
from pbpk_domain.nca import nca

pytestmark = pytest.mark.req("T-47", "T-18")


def _dataset(**kw) -> ObservedDataset:
    base = {"id": new_dataset_id(), "kind": "profile",
            "study": {"study_id": "EX-1", "route": "oral", "dose_mg": 10, "formulation": "solution", "food_state": "fasted",
                      "n": 12, "n_timepoints": 5, "lloq": 0.5},
            "series": (Series(name="mean", times=(0.5, 1, 2, 4, 24), values=(10.0, 20.0, 15.0, 8.0, None),
                              error=(2.0, 3.0, 2.5, 1.0, 0.0), error_kind="SD", n=12),),
            "origin": Origin.CLIENT, "provider": "CLIENT"}
    return ObservedDataset(**(base | kw))


def test_a_profiles_statistics_are_the_platforms_nca_of_its_points_below_the_lloq_left_out():
    points = card_points(_dataset().to_content())
    (series,) = points["series"]
    expected = nca([0.5, 1, 2, 4], [10.0, 20.0, 15.0, 8.0])
    assert series["stats"]["c_max"] == 20.0 and series["stats"]["t_max"] == 1
    assert series["stats"]["auc_last"] == pytest.approx(expected.auc_last) and series["stats"]["t_half"] == pytest.approx(expected.t_half)
    assert (series["stats"]["points"], series["stats"]["blq"]) == (4, 1)
    assert series["values"][-1] is None and series["error"] == [2.0, 3.0, 2.5, 1.0, 0.0]
    assert (points["lloq"], points["unit"], points["time_unit"], points["blinded"]) == (0.5, "ng/ml", "h", False)


def test_a_blinded_dataset_shows_its_times_only_and_no_statistics():
    points = card_points(redact_dataset(_dataset(reported=(ReportedPK(parameter="Cmax", value=21.0, unit="ng/ml"),)).to_content()))
    (series,) = points["series"]
    assert points["blinded"] and series["stats"] is None and set(series["values"]) == {None}
    assert series["times"] == [0.5, 1, 2, 4, 24] and points["reported"][0]["value"] is None


def test_reported_pk_is_shown_as_reported_and_a_series_too_short_gets_no_statistics():
    reported = _dataset(kind="pk_parameters", series=(),
                        reported=(ReportedPK(parameter="AUC_inf", value=310.0, unit="ng*h/ml", statistic="geometric_mean"),))
    assert card_points(reported.to_content())["reported"] == [
        {"parameter": "AUC_inf", "value": 310.0, "unit": "ng*h/ml", "statistic": "geometric_mean"}]
    short = _dataset(series=(Series(name="mean", times=(1, 2), values=(5.0, None)),))
    assert card_points(short.to_content())["series"][0]["stats"] is None
