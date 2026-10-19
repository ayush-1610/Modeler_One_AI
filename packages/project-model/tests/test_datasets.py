"""T-45 / T-19: observed datasets with origin and checks; the human-calibrated digitizer."""

from __future__ import annotations

import pytest

from modeler_project.datasets import (
    DatasetError,
    ObservedDataset,
    Origin,
    ReportedPK,
    Series,
    check_dataset,
    new_dataset_id,
)
from pbpk_domain.digitize import AxisCalibration, Calibration, CalibrationError, digitize

STUDY = {"study_id": "doe-2019-po-10mg", "reference": "Doe 2019", "n": 12, "route": "oral", "dose_mg": 10,
         "formulation": "ir_tablet", "n_timepoints": 6, "statistic": "mean_sd"}


def _ds(**kw):
    base = dict(id=new_dataset_id(), kind="profile", study=STUDY, time_unit="h", unit="ng/ml", origin=Origin.LITERATURE,
                series=(Series(times=(0.5, 1, 2, 4, 8, 12), values=(50, 120, 100, 60, 25, 10), n=12),))
    base.update(kw)
    return ObservedDataset(**base)


@pytest.mark.req("T-45")
def test_dataset_checks_and_the_nca_cross_check():
    ok = check_dataset(_ds(reported=(ReportedPK(parameter="Cmax", value=120, unit="ng/ml"),
                                     ReportedPK(parameter="AUC_last", value=540, unit="ng/ml*h"))))
    assert not any(f.startswith("nca_mismatch") for f in ok.flags) and ok.real
    off = check_dataset(_ds(reported=(ReportedPK(parameter="AUC_last", value=400, unit="ng/ml*h"),)))
    assert any(f.startswith("nca_mismatch AUC_last") for f in off.flags)
    with pytest.raises(DatasetError, match="not in order"):
        check_dataset(_ds(series=(Series(times=(2, 1), values=(1, 2)),)))
    with pytest.raises(DatasetError, match="study record"):
        check_dataset(_ds(study={**STUDY, "dose_mg": -1}))
    with pytest.raises(DatasetError, match="not recognised"):
        check_dataset(_ds(unit="bananas/ml"))
    params = check_dataset(_ds(kind="pk_parameters", series=(), reported=(ReportedPK(parameter="Cmax", value=1, unit="ng/ml"),)))
    assert any("cannot train" in f for f in params.flags)
    assert not _ds(origin=Origin.SYNTHETIC).real and not _ds(origin=Origin.ILLUSTRATIVE).real


@pytest.mark.req("T-19")
def test_digitizer_round_trip_within_two_percent_of_the_axis_range():
    cal = Calibration(x=AxisCalibration(p1=100, v1=0, p2=700, v2=24),
                      y=AxisCalibration(p1=500, v1=1, p2=100, v2=1000, scale="log"))
    truth = [(0.5, 50.0), (1, 120.0), (2, 100.0), (4, 60.0), (8, 25.0), (12, 10.0), (24, 1.5)]
    # where the true points sit on the figure, rounded to whole pixels as a person would click them
    pixels = [(round(cal.x.pixel(t)), round(cal.y.pixel(c))) for t, c in truth]
    points = digitize(cal, pixels)
    for (t, c), p in zip(truth, points, strict=True):
        assert abs(p.x - t) <= 0.02 * 24
        assert abs(p.y - c) / c <= 0.02 or abs(p.y - c) <= p.dy
    assert all(p.dx == pytest.approx(0.04) for p in points)
    with pytest.raises(CalibrationError, match="positive"):
        AxisCalibration(p1=1, v1=0, p2=2, v2=10, scale="log")


@pytest.mark.req("T-45")
def test_a_figure_digitized_in_a_cropped_zoomed_view_gives_the_same_values_and_keeps_its_frame():
    """R3d: the pixels of a crop are in that view's own frame; the calibration maps them all the same."""
    from modeler_project.dataset_register import digitized_dataset

    study = {"study_id": "fig-1", "n": 12, "route": "oral", "dose_mg": 10, "formulation": "solution", "food_state": "fasted",
             "n_timepoints": 3}
    whole = {"x": {"p1": 100, "v1": 0, "p2": 700, "v2": 12}, "y": {"p1": 500, "v1": 0, "p2": 100, "v2": 200}}
    page = digitized_dataset(study=study, doc_sha256="a" * 64, page=3, locator="Figure 2", calibration=whole,
                             pixels={"mean": [(150, 400), (200, 300), (300, 200)]}, time_unit="h", unit="ng/ml")
    # the same figure cropped to its box (offset 80, 40) and drawn at twice the scale
    zoom = {a: {**c, "p1": (c["p1"] - (80 if a == "x" else 40)) * 2, "p2": (c["p2"] - (80 if a == "x" else 40)) * 2}
            for a, c in whole.items()}
    cropped = digitized_dataset(study=study, doc_sha256="a" * 64, page=3, locator="Figure 2", calibration=zoom,
                                pixels={"mean": [((x - 80) * 2, (y - 40) * 2) for x, y in [(150, 400), (200, 300), (300, 200)]]},
                                time_unit="h", unit="ng/ml", crop=(0.1, 0.05, 0.9, 0.6), scale=4.0)
    assert cropped.series[0].times == pytest.approx(page.series[0].times)
    assert cropped.series[0].values == pytest.approx(page.series[0].values)
    assert (cropped.digitization.crop, cropped.digitization.scale) == ((0.1, 0.05, 0.9, 0.6), 4.0)
    assert page.digitization.crop is None and ObservedDataset.from_content(cropped.to_content()) == cropped
