"""Canonical concentration records -> PK-Sim observed data (snapshot ``ObservedData`` entries).

Structure mirrors observed data in a PK-Sim 12 snapshot (OSP Dapagliflozin model): dimension
``Concentration (mass)`` with unit ``µg/l`` or ``mg/l``, time base grid in ``h``, arithmetic SD as a related
column with ``AuxiliaryType: ArithmeticStdDev``, missing values as ``"NaN"``, and the OSP naming pattern
``Study - Grouping - Molecule - Route - Dose - Compartment - agg. (n=N)``.

Not yet confirmed against the engine and therefore rejected rather than guessed: molar units, matrices other
than plasma, geometric statistics, and how PK-Sim stores LLOQ. Values below LLOQ are left out of the series and
counted in the ``Comment`` property until the LLOQ encoding is verified by an engine round trip.
"""

from __future__ import annotations

import unicodedata
from collections import defaultdict
from typing import Any

from modeler_intake.records import ConcentrationObservation
from modeler_intake.validate import CONCENTRATION_UNITS, TIME_UNITS, canonical_unit

TARGET_UNIT = "µg/l"
_TO_MICROGRAM_PER_L = {"pg/ml": 1e-3, "ng/ml": 1.0, "µg/ml": 1e3, "mg/ml": 1e6, "ng/l": 1e-3, "µg/l": 1.0, "mg/l": 1e3}
_MATRIX = {"plasma": ("Peripheral Venous Blood", "Plasma")}
_ROUTE = {"oral": "PO", "po": "PO", "iv": "IV", "intravenous": "IV"}
_STATISTIC_PATH = {"arithmetic_mean": "ArithmeticMean", "individual": "Concentration"}


class ObservedDataConversionError(ValueError):
    pass


def _property(name: str, value: str | float) -> dict[str, Any]:
    return {"Name": name, "Value": value, "Type": "Double" if isinstance(value, float) else "String"}


def _dose_label(record: ConcentrationObservation) -> str:
    if record.dose is None:
        return "."
    return f"{record.dose:g} {record.dose_unit or ''}".strip()


def _series_name(record: ConcentrationObservation, n: int | None) -> str:
    route = _ROUTE.get((record.route or "").lower(), record.route or ".")
    suffix = f"agg. (n={n})" if record.statistic != "individual" else f"ind. {record.series}"
    grouping = record.series if record.statistic != "individual" else (record.formulation or record.study_id)
    return " - ".join([record.study_id, grouping, record.analyte, route, _dose_label(record), "Plasma", suffix])


def to_observed_data(records: list[ConcentrationObservation], molecular_weight_g_per_mol: float) -> list[dict[str, Any]]:
    """One observed-data entry per series (study, analyte, dose, series label, statistic)."""
    groups: dict[tuple, list[ConcentrationObservation]] = defaultdict(list)
    for record in records:
        groups[(record.study_id, record.analyte, record.matrix, record.dose, record.series, record.statistic)].append(record)

    entries = []
    for (_, _, matrix, _, _, statistic), items in groups.items():
        if matrix.lower() not in _MATRIX:
            raise ObservedDataConversionError(f"matrix {matrix!r} is not supported yet; only plasma is verified")
        if statistic not in _STATISTIC_PATH:
            raise ObservedDataConversionError(f"statistic {statistic!r} is not supported yet")
        organ, compartment = _MATRIX[matrix.lower()]

        items = sorted(items, key=lambda r: r.time)
        first = items[0]
        unit = canonical_unit(first.unit, CONCENTRATION_UNITS)
        if unit not in _TO_MICROGRAM_PER_L:
            raise ObservedDataConversionError(f"unit {first.unit!r} is not a verified mass concentration unit")
        time_unit = canonical_unit(first.time_unit, TIME_UNITS)
        if time_unit is None or any(canonical_unit(r.unit, CONCENTRATION_UNITS) != unit or r.time_unit != first.time_unit for r in items):
            raise ObservedDataConversionError(f"series {first.series!r} mixes units")

        factor = _TO_MICROGRAM_PER_L[unit]
        kept = [r for r in items if not r.below_lloq and r.value is not None]
        excluded = len(items) - len(kept)
        n = first.n if statistic != "individual" else 1
        name = _series_name(first, n)

        column: dict[str, Any] = {
            "Name": "Avg" if statistic != "individual" else "Measurement",
            "QuantityInfo": {"Path": f"{name}|ObservedData|{organ}|{compartment}|{first.analyte}|{_STATISTIC_PATH[statistic]}"},
            "DataInfo": {"Origin": "Observation", "AuxiliaryType": "Undefined", "MolWeight": molecular_weight_g_per_mol},
            "Values": [r.value * factor for r in kept],
            "Dimension": "Concentration (mass)",
            "Unit": TARGET_UNIT,
        }
        if statistic == "arithmetic_mean" and any(r.sd is not None for r in kept):
            column["RelatedColumns"] = [
                {
                    "Name": "Var",
                    "QuantityInfo": {"Path": f"{name}|ObservedData|{organ}|{compartment}|{first.analyte}|ArithmeticStdDev"},
                    "DataInfo": {"Origin": "ObservationAuxiliary", "AuxiliaryType": "ArithmeticStdDev", "MolWeight": molecular_weight_g_per_mol},
                    "Values": [r.sd * factor if r.sd is not None else "NaN" for r in kept],
                    "Dimension": "Concentration (mass)",
                    "Unit": TARGET_UNIT,
                }
            ]

        comment = f"{excluded} value(s) below LLOQ ({first.lloq:g} {first.unit}) excluded" if excluded and first.lloq else "."
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
