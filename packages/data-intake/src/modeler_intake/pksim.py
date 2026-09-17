"""Canonical concentration/excretion records -> PK-Sim observed data (snapshot ``ObservedData`` entries).

Structure mirrors observed data in the OSP reference models (Dapagliflozin/Rifampicin/Midazolam/Itraconazole):
a value column with dimension ``Concentration (mass)`` (target ``µg/l``), ``Concentration (molar)`` (target
``µmol/l``) or ``Fraction`` (urine/feces, dimensionless), a time base grid, an optional variability related
column (``ArithmeticStdDev`` in the value's unit, or ``GeometricStdDev`` as a dimensionless factor), the LLOQ
recorded on the value column's ``DataInfo.LLOQ`` (VERIFIED against the Rifampicin/Midazolam models), and the OSP
naming pattern ``Study - Grouping - Molecule - Route - Dose - Compartment - agg. (n=N)``.

Mass and molar are separate OSP dimensions; PK-Sim converts between them with the molecular weight carried on
each column (``DataInfo.MolWeight``), so records are kept in their reported dimension rather than converted here.
"""

from __future__ import annotations

import unicodedata
from collections import defaultdict
from typing import Any

from modeler_intake.records import ConcentrationObservation
from modeler_intake.validate import (
    FRACTION_MATRICES,
    FRACTION_UNITS,
    MASS_CONCENTRATION_UNITS,
    TIME_UNITS,
    canonical_unit,
)

TARGET_MASS_UNIT = "µg/l"
TARGET_MOLAR_UNIT = "µmol/l"

# Canonical unit -> factor to the target unit of its dimension.
_MASS_TO_UG_PER_L = {
    "pg/l": 1e-6, "ng/l": 1e-3, "µg/l": 1.0, "mg/l": 1e3, "g/l": 1e6,
    "pg/ml": 1e-3, "ng/ml": 1.0, "µg/ml": 1e3, "mg/ml": 1e6,
}
_MOLAR_TO_UMOL_PER_L = {
    "fmol/l": 1e-9, "pmol/l": 1e-6, "nmol/l": 1e-3, "µmol/l": 1.0, "mmol/l": 1e3, "mol/l": 1e6,
    "fmol/ml": 1e-6, "pmol/ml": 1e-3, "nmol/ml": 1.0, "µmol/ml": 1e3, "mmol/ml": 1e6, "mol/ml": 1e9,
}

# matrix -> (organ, compartment) for the observed-data quantity path (harvested from the reference models).
_MATRIX = {
    "plasma": ("Peripheral Venous Blood", "Plasma"),
    "urine": ("Kidney", "Urine"),
    "feces": ("Lumen", "Feces"),
}
# statistic -> the OSP value-column path suffix, and its variability AuxiliaryType (none for individual/median).
_STATISTIC_PATH = {"arithmetic_mean": "ArithmeticMean", "geometric_mean": "GeometricMean", "median": "Median", "individual": "Individual"}
_STATISTIC_SD = {"arithmetic_mean": "ArithmeticStdDev", "geometric_mean": "GeometricStdDev"}
_ROUTE = {"oral": "PO", "po": "PO", "iv": "IV", "intravenous": "IV"}


class ObservedDataConversionError(ValueError):
    pass


def _property(name: str, value: str | float) -> dict[str, Any]:
    return {"Name": name, "Value": value, "Type": "Double" if isinstance(value, float) else "String"}


def _dose_label(record: ConcentrationObservation) -> str:
    if record.dose is None:
        return "."
    return f"{record.dose:g} {record.dose_unit or ''}".strip()


def _series_name(record: ConcentrationObservation, compartment: str, n: int | None) -> str:
    route = _ROUTE.get((record.route or "").lower(), record.route or ".")
    suffix = f"agg. (n={n})" if record.statistic != "individual" else f"ind. {record.series}"
    grouping = record.series if record.statistic != "individual" else (record.formulation or record.study_id)
    return " - ".join([record.study_id, grouping, record.analyte, route, _dose_label(record), compartment, suffix])


def _resolve_dimension(matrix: str, unit: str) -> tuple[str, str | None, float]:
    """(dimension, target unit, factor to target) for a record's matrix + unit. Raises if unsupported."""
    if matrix in FRACTION_MATRICES:
        canon = canonical_unit(unit, FRACTION_UNITS)
        if canon is None:
            raise ObservedDataConversionError(f"unit {unit!r} is not a fraction unit for matrix {matrix!r}")
        return "Fraction", (canon or None), 1.0  # dimensionless: unit "" is stored as null
    mass = canonical_unit(unit, MASS_CONCENTRATION_UNITS)
    if mass in _MASS_TO_UG_PER_L:
        return "Concentration (mass)", TARGET_MASS_UNIT, _MASS_TO_UG_PER_L[mass]
    molar = canonical_unit(unit, {k: k for k in _MOLAR_TO_UMOL_PER_L} | {"nm": "nmol/l", "µm": "µmol/l", "um": "µmol/l", "mm": "mmol/l", "pm": "pmol/l", "fm": "fmol/l"})
    if molar in _MOLAR_TO_UMOL_PER_L:
        return "Concentration (molar)", TARGET_MOLAR_UNIT, _MOLAR_TO_UMOL_PER_L[molar]
    raise ObservedDataConversionError(f"unit {unit!r} is not a supported concentration unit")


def to_observed_data(records: list[ConcentrationObservation], molecular_weight_g_per_mol: float) -> list[dict[str, Any]]:
    """One observed-data entry per series (study, analyte, matrix, dose, series label, statistic)."""
    groups: dict[tuple, list[ConcentrationObservation]] = defaultdict(list)
    for record in records:
        groups[(record.study_id, record.analyte, record.matrix, record.dose, record.series, record.statistic)].append(record)

    entries = []
    for (_, _, matrix, _, _, statistic), items in groups.items():
        matrix_key = matrix.lower()
        if matrix_key not in _MATRIX:
            raise ObservedDataConversionError(f"matrix {matrix!r} is not supported (plasma, urine, feces)")
        if statistic not in _STATISTIC_PATH:
            raise ObservedDataConversionError(f"statistic {statistic!r} is not supported yet")
        organ, compartment = _MATRIX[matrix_key]

        items = sorted(items, key=lambda r: r.time)
        first = items[0]
        dimension, unit, factor = _resolve_dimension(matrix_key, first.unit)
        time_unit = canonical_unit(first.time_unit, TIME_UNITS)
        if time_unit is None:
            raise ObservedDataConversionError(f"time unit {first.time_unit!r} is not recognised")
        if any(_resolve_dimension(matrix_key, r.unit) != (dimension, unit, factor) or canonical_unit(r.time_unit, TIME_UNITS) != time_unit for r in items):
            raise ObservedDataConversionError(f"series {first.series!r} mixes units")

        kept = [r for r in items if r.value is not None]
        censored = len(items) - len(kept)
        n = first.n if statistic != "individual" else 1
        name = _series_name(first, compartment, n)
        base_path = f"{name}|ObservedData|{organ}|{compartment}|{first.analyte}"

        value_info: dict[str, Any] = {"Origin": "Observation", "AuxiliaryType": "Undefined", "MolWeight": molecular_weight_g_per_mol}
        if first.lloq is not None:  # LLOQ recorded on the value column, in the column's unit (verified round trip)
            value_info["LLOQ"] = first.lloq * factor
        column: dict[str, Any] = {
            "Name": "Avg" if statistic != "individual" else "Measurement",
            "QuantityInfo": {"Path": f"{base_path}|{_STATISTIC_PATH[statistic]}"},
            "DataInfo": value_info,
            "Values": [r.value * factor for r in kept],
            "Dimension": dimension,
            "Unit": unit,
        }

        sd_aux = _STATISTIC_SD.get(statistic)
        if sd_aux and any(r.sd is not None for r in kept):
            if sd_aux == "GeometricStdDev":  # a dimensionless multiplicative factor, not in the value's unit
                related = {
                    "Name": "Var",
                    "QuantityInfo": {"Path": f"{base_path}|{sd_aux}"},
                    "DataInfo": {"Origin": "ObservationAuxiliary", "AuxiliaryType": sd_aux, "MolWeight": molecular_weight_g_per_mol},
                    "Values": [r.sd if r.sd is not None else "NaN" for r in kept],
                    "Dimension": "Dimensionless", "Unit": None,
                }
            else:
                related = {
                    "Name": "Var",
                    "QuantityInfo": {"Path": f"{base_path}|{sd_aux}"},
                    "DataInfo": {"Origin": "ObservationAuxiliary", "AuxiliaryType": sd_aux, "MolWeight": molecular_weight_g_per_mol},
                    "Values": [r.sd * factor if r.sd is not None else "NaN" for r in kept],
                    "Dimension": dimension, "Unit": unit,
                }
            column["RelatedColumns"] = [related]

        comment = f"{censored} value(s) below LLOQ ({first.lloq:g} {first.unit}) not reported" if censored and first.lloq else "."
        cells = sorted({ref for r in items for ref in r.source.cells.values()})
        entries.append(
            {
                "Name": name,
                "ExtendedProperties": [
                    _property("Study Id", first.study_id),
                    _property("Grouping", first.series),
                    _property("Data type", "individual" if statistic == "individual" else "aggregated"),
                    *([_property("N", float(n))] if n is not None else []),
                    _property("Molecule", first.analyte),
                    _property("Species", "Human"),
                    _property("Organ", organ),
                    _property("Compartment", compartment),
                    _property("Route", _ROUTE.get((first.route or "").lower(), first.route or ".")),
                    _property("Dose", _dose_label(first)),
                    _property("Formulation", first.formulation or "."),
                    _property("Food state", first.food_state or "."),
                    _property("Source", f"sha256:{first.source.file_sha256} cells {cells[0]}..{cells[-1]}"),
                    _property("Comment", unicodedata.normalize("NFC", comment)),
                ],
                "Columns": [column],
                "BaseGrid": {
                    "Name": "Time",
                    "QuantityInfo": {"Path": f"{name}|Time", "Type": "Time"},
                    "DataInfo": {"Origin": "BaseGrid", "AuxiliaryType": "Undefined"},
                    "Values": [r.time for r in kept],
                    "Dimension": "Time",
                    "Unit": time_unit,
                },
            }
        )
    return entries
