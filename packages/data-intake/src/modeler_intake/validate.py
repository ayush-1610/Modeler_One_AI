"""Deterministic validation of canonical records. Problems are reported, never silently fixed."""

from __future__ import annotations

import unicodedata
from collections import defaultdict

from modeler_intake.records import ConcentrationObservation, DissolutionObservation
from pbpk_domain.issues import Issue

# Canonical spellings follow OSP unit names; aliases cover common spreadsheet spellings.
CONCENTRATION_UNITS = {
    "pg/ml": "pg/ml", "ng/ml": "ng/ml", "µg/ml": "µg/ml", "ug/ml": "µg/ml", "mcg/ml": "µg/ml", "mg/ml": "mg/ml",
    "ng/l": "ng/l", "µg/l": "µg/l", "ug/l": "µg/l", "mg/l": "mg/l",
    "nmol/l": "nmol/l", "nm": "nmol/l", "µmol/l": "µmol/l", "umol/l": "µmol/l", "µm": "µmol/l",
}
TIME_UNITS = {"min": "min", "minute": "min", "minutes": "min", "h": "h", "hr": "h", "hrs": "h", "hour": "h", "hours": "h",
              "day": "day(s)", "days": "day(s)", "d": "day(s)"}


def canonical_unit(unit: str, table: dict[str, str]) -> str | None:
    key = unicodedata.normalize("NFKC", unit).strip().lower().replace("μ", "µ")
    return table.get(key)


def validate_concentrations(records: list[ConcentrationObservation]) -> list[Issue]:
    issues: list[Issue] = []
    series: dict[tuple, list[ConcentrationObservation]] = defaultdict(list)
    for record in records:
        where = record.source.cells.get("value", "?")
        for field in ("study_id", "analyte", "matrix"):
            if not getattr(record, field):
                issues.append(Issue("MISSING_CONSTANT", where, f"{field} is required for concentration data"))
        if canonical_unit(record.unit, CONCENTRATION_UNITS) is None:
            issues.append(Issue("UNKNOWN_UNIT", where, f"concentration unit {record.unit!r} is not recognised"))
        if canonical_unit(record.time_unit, TIME_UNITS) is None:
            issues.append(Issue("UNKNOWN_UNIT", where, f"time unit {record.time_unit!r} is not recognised"))
        if record.time < 0:
            issues.append(Issue("NEGATIVE_TIME", record.source.cells["time"], "time must be >= 0"))
        if record.value is not None and record.value < 0:
            issues.append(Issue("NEGATIVE_VALUE", where, "concentration must be >= 0"))
        if record.below_lloq and record.lloq is None:
            issues.append(Issue("LLOQ_MISSING", where, "value is below LLOQ but no LLOQ is known; set it in the recipe"))
        if record.statistic != "individual" and record.value is not None and record.n is None:
            issues.append(Issue("N_MISSING", where, "aggregated values need the number of subjects"))
        series[(record.study_id, record.analyte, record.matrix, record.series, record.dose)].append(record)

    for key, items in series.items():
        seen: dict[float, str] = {}
        previous = None
        for item in items:
            ref = item.source.cells["time"]
            if item.time in seen:
                issues.append(Issue("DUPLICATE_TIME", ref, f"time {item.time:g} already given at {seen[item.time]} for series {key[3]!r}"))
            seen.setdefault(item.time, ref)
            if previous is not None and item.time < previous:
                issues.append(Issue("TIME_NOT_INCREASING", ref, f"time {item.time:g} follows {previous:g} in series {key[3]!r}"))
            previous = item.time
    return issues


def validate_dissolution(records: list[DissolutionObservation], max_percent: float = 110.0) -> list[Issue]:
    issues: list[Issue] = []
    for record in records:
        where = record.source.cells.get("value", "?")
        if not record.batch or not record.medium:
            issues.append(Issue("MISSING_CONSTANT", where, "batch and medium are required for dissolution data"))
        if not 0 <= record.percent_dissolved <= max_percent:
            issues.append(Issue("DISSOLUTION_OUT_OF_RANGE", where, f"{record.percent_dissolved:g}% is outside 0-{max_percent:g}%"))
        if record.ph is not None and not 0 <= record.ph <= 14:
            issues.append(Issue("PH_OUT_OF_RANGE", where, f"pH {record.ph:g} is outside 0-14"))
        if canonical_unit(record.time_unit, TIME_UNITS) is None:
            issues.append(Issue("UNKNOWN_UNIT", where, f"time unit {record.time_unit!r} is not recognised"))
    return issues
