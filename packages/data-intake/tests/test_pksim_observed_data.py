import pytest

from modeler_intake.pksim import ObservedDataConversionError, to_observed_data
from modeler_intake.records import ConcentrationObservation, SourceRef


def record(time, value, *, sd=None, below=False, statistic="arithmetic_mean", unit="ng/mL", matrix="plasma"):
    return ConcentrationObservation(
        study_id="XYZ-101", analyte="Example-A", matrix=matrix, series="10 mg fasted", statistic=statistic,
        time=time, time_unit="h", value=None if below else value, unit=unit, below_lloq=below, lloq=0.5,
        sd=sd, n=12, dose=10, dose_unit="mg", route="oral", food_state="Fasted",
        source=SourceRef(file_sha256="f" * 64, recipe_id="r", recipe_version=1, cells={"time": f"S!A{int(time * 10)}", "value": f"S!B{int(time * 10)}"}),
    )


def test_mean_series_matches_pksim_snapshot_structure():
    (entry,) = to_observed_data([record(1, 25.0, sd=4.0), record(0.5, 12.0, sd=2.0), record(24, 0, below=True)], 325.8)
    assert entry["Name"] == "XYZ-101 - 10 mg fasted - Example-A - PO - 10 mg - Plasma - agg. (n=12)"
    column = entry["Columns"][0]
    assert column["Dimension"] == "Concentration (mass)" and column["Unit"] == "µg/l"
    assert column["Values"] == [12.0, 25.0]  # ng/ml == µg/l, sorted by time, BLQ excluded
    assert column["QuantityInfo"]["Path"].endswith("|ObservedData|Peripheral Venous Blood|Plasma|Example-A|ArithmeticMean")
    assert column["RelatedColumns"][0]["DataInfo"]["AuxiliaryType"] == "ArithmeticStdDev"
    assert column["RelatedColumns"][0]["Values"] == [2.0, 4.0]
    assert entry["BaseGrid"]["Values"] == [0.5, 1.0] and entry["BaseGrid"]["Unit"] == "h"
    props = {p["Name"]: p["Value"] for p in entry["ExtendedProperties"]}
    assert props["N"] == 12.0 and props["Route"] == "PO"
    assert props["Comment"].startswith("1 value(s) below LLOQ")


def test_unit_conversion_and_unsupported_inputs():
    (entry,) = to_observed_data([record(1, 2.0, unit="mg/L")], 300.0)
    assert entry["Columns"][0]["Values"] == [2000.0]
    with pytest.raises(ObservedDataConversionError, match="only plasma"):
        to_observed_data([record(1, 2.0, matrix="urine")], 300.0)
    with pytest.raises(ObservedDataConversionError, match="verified mass"):
        to_observed_data([record(1, 2.0, unit="nmol/L")], 300.0)
