import pytest

from modeler_intake.pksim import ObservedDataConversionError, to_observed_data
from modeler_intake.records import ConcentrationObservation, SourceRef


def record(time, value, *, sd=None, below=False, statistic="arithmetic_mean", unit="ng/mL", matrix="plasma", lloq=0.5, n=12):
    return ConcentrationObservation(
        study_id="XYZ-101", analyte="Example-A", matrix=matrix, series="10 mg fasted", statistic=statistic,
        time=time, time_unit="h", value=None if below else value, unit=unit, below_lloq=below, lloq=lloq,
        sd=sd, n=n, dose=10, dose_unit="mg", route="oral", food_state="Fasted",
        source=SourceRef(file_sha256="f" * 64, recipe_id="r", recipe_version=1, cells={"time": f"S!A{int(time * 10)}", "value": f"S!B{int(time * 10)}"}),
    )


def test_mean_series_matches_pksim_snapshot_structure():
    (entry,) = to_observed_data([record(1, 25.0, sd=4.0), record(0.5, 12.0, sd=2.0), record(24, 0, below=True)], 325.8)
    assert entry["Name"] == "XYZ-101 - 10 mg fasted - Example-A - PO - 10 mg - Plasma - agg. (n=12)"
    column = entry["Columns"][0]
    assert column["Dimension"] == "Concentration (mass)" and column["Unit"] == "µg/l"
    assert column["Values"] == [12.0, 25.0]  # ng/ml == µg/l, sorted by time, censored value dropped
    assert column["QuantityInfo"]["Path"].endswith("|ObservedData|Peripheral Venous Blood|Plasma|Example-A|ArithmeticMean")
    assert column["DataInfo"]["LLOQ"] == 0.5  # LLOQ recorded on the value column
    assert column["RelatedColumns"][0]["DataInfo"]["AuxiliaryType"] == "ArithmeticStdDev"
    assert column["RelatedColumns"][0]["Values"] == [2.0, 4.0]
    assert entry["BaseGrid"]["Values"] == [0.5, 1.0] and entry["BaseGrid"]["Unit"] == "h"
    props = {p["Name"]: p["Value"] for p in entry["ExtendedProperties"]}
    assert props["N"] == 12.0 and props["Route"] == "PO"
    assert props["Comment"].startswith("1 value(s) below LLOQ")


def test_mass_unit_conversion():
    (entry,) = to_observed_data([record(1, 2.0, unit="mg/L")], 300.0)
    assert entry["Columns"][0]["Values"] == [2000.0]  # mg/l -> µg/l
    assert entry["Columns"][0]["Dimension"] == "Concentration (mass)"


def test_molar_units_use_the_molar_dimension():
    (entry,) = to_observed_data([record(1, 2.0, unit="nmol/L", sd=0.4)], 300.0)
    column = entry["Columns"][0]
    assert column["Dimension"] == "Concentration (molar)" and column["Unit"] == "µmol/l"
    assert column["Values"] == [pytest.approx(0.002)]  # 2 nmol/l -> 0.002 µmol/l
    assert column["RelatedColumns"][0]["Values"] == [pytest.approx(0.0004)]  # arithmetic SD scales too


def test_geometric_mean_sd_is_a_dimensionless_factor():
    rows = [record(1, 20.0, sd=1.5, statistic="geometric_mean"), record(4, 8.0, sd=1.6, statistic="geometric_mean")]
    (entry,) = to_observed_data(rows, 300.0)
    column = entry["Columns"][0]
    assert column["QuantityInfo"]["Path"].endswith("|Example-A|GeometricMean")
    var = column["RelatedColumns"][0]
    assert var["DataInfo"]["AuxiliaryType"] == "GeometricStdDev"
    assert var["Dimension"] == "Dimensionless" and var["Unit"] is None
    assert var["Values"] == [1.5, 1.6]  # geometric SD is a unitless factor, NOT scaled by the value factor


def test_median_has_no_variability_column():
    (entry,) = to_observed_data([record(1, 5.0, statistic="median")], 300.0)
    column = entry["Columns"][0]
    assert column["QuantityInfo"]["Path"].endswith("|Example-A|Median")
    assert "RelatedColumns" not in column


def test_individual_series_uses_individual_suffix():
    (entry,) = to_observed_data([record(1, 5.0, statistic="individual")], 300.0)
    assert entry["Columns"][0]["QuantityInfo"]["Path"].endswith("|Example-A|Individual")


def test_urine_fraction_series():
    rows = [record(4, 0.10, unit="", matrix="urine", lloq=None), record(24, 0.42, unit="", matrix="urine", lloq=None)]
    (entry,) = to_observed_data(rows, 300.0)
    column = entry["Columns"][0]
    assert column["Dimension"] == "Fraction" and column["Unit"] is None  # dimensionless -> null unit
    assert column["QuantityInfo"]["Path"].endswith("|ObservedData|Kidney|Urine|Example-A|ArithmeticMean")
    assert column["Values"] == [0.10, 0.42]
    assert entry["Name"].endswith("- Urine - agg. (n=12)")


def test_percent_fraction_kept_as_percent():
    (entry,) = to_observed_data([record(24, 42.0, unit="%", matrix="feces", lloq=None)], 300.0)
    column = entry["Columns"][0]
    assert column["Dimension"] == "Fraction" and column["Unit"] == "%"
    assert column["QuantityInfo"]["Path"].endswith("|ObservedData|Lumen|Feces|Example-A|ArithmeticMean")


def test_mixed_units_and_unsupported_matrix_are_rejected():
    with pytest.raises(ObservedDataConversionError, match="mixes units"):
        to_observed_data([record(1, 2.0, unit="mg/L"), record(2, 3.0, unit="nmol/L")], 300.0)
    with pytest.raises(ObservedDataConversionError, match="not supported"):
        to_observed_data([record(1, 2.0, matrix="csf")], 300.0)
