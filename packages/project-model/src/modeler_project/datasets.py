"""Observed datasets with their origin (plan §9): the data a model is trained and judged on.

A dataset is a clinical concentration-time profile (one or more series) or a table of reported PK parameters only
(AUC, Cmax … without a profile: usable to judge a prediction, not to fit one). Each carries the study record the MS-01
split needs, where it came from (`origin`) and how it was extracted, and is checked by code: units known, times in
order, values not negative, and our NCA of a mean profile against the reported NCA when both exist (> 20 % apart is
flagged, usually a digitization or unit problem). The origin is what the real-data rule reads (§9.4): synthetic and
illustrative data can run the pipeline but can never produce a pass outside an exploratory project.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from modeler_project.evidence import EvidenceState, SourceRef
from pbpk_domain.campaign.split import StudyRecord
from pbpk_domain.data_origin import REAL_ORIGINS, DataOrigin
from pbpk_domain.nca import nca
from pbpk_domain.units import UnitError, is_molar, minutes_per, umol_per_l_per

Origin = DataOrigin  # the six origins of the real-data rule, shared with the campaign path (pbpk_domain.data_origin)
NCA_TOLERANCE = 0.20  # reported vs recomputed NCA [SME]

# A dataset is always dumped whole (`to_content`), so in the API contract (phase 9e) a field with a default is still
# always present. `Series`, `ReportedPK` and `SourceRef` are request schemas too, and keep their defaults optional.
_CONTENT = ConfigDict(frozen=True, extra="forbid", json_schema_serialization_defaults_required=True)


class Series(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = "mean"
    statistic: Literal["individual", "arithmetic_mean", "geometric_mean", "median"] = "arithmetic_mean"
    times: tuple[float, ...]
    values: tuple[float | None, ...]          # None = below LLOQ
    error: tuple[float, ...] | None = None
    error_kind: Literal["SD", "SE", "CV%", "none"] = "none"
    n: int | None = None


class ReportedPK(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    parameter: Literal["AUC_last", "AUC_inf", "Cmax", "tmax", "t_half", "Ctrough", "CL/F", "Vz/F"]
    value: float
    unit: str
    statistic: str = "arithmetic_mean"
    variability: str = ""
    quote: str = ""


class Digitization(BaseModel):
    model_config = _CONTENT

    page: int
    calibration: dict[str, Any]           # x / y: p1, v1, p2, v2, scale
    pixels: dict[str, list[tuple[float, float]]]   # series name -> picked pixels
    resolution: dict[str, float]          # max data units per pixel, x and y
    overlay_approved_by: str | None = None


class ObservedDataset(BaseModel):
    model_config = _CONTENT

    id: str
    kind: Literal["profile", "pk_parameters"]
    study: dict[str, Any]                 # validated as a StudyRecord (MS-01 §3.1)
    analyte: str = "parent"
    matrix: str = "plasma"
    time_unit: str = "h"
    unit: str = "ng/ml"
    series: tuple[Series, ...] = ()
    reported: tuple[ReportedPK, ...] = ()
    origin: Origin
    extraction: Literal["TABLE", "FIGURE_DIGITIZED", "CELL", "MANUAL", "OSP_SNAPSHOT"] = "MANUAL"
    source: SourceRef = Field(default_factory=SourceRef)
    quote: str = ""
    digitization: Digitization | None = None
    purpose: str = "model_building"
    provider: Literal["CLIENT", "LITERATURE"] = "LITERATURE"
    flags: tuple[str, ...] = ()
    state: EvidenceState = EvidenceState.PROPOSED
    proposed_by: str = ""
    proposed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    decided_by: str | None = None
    decision_reason: str = ""
    note: str = ""

    def to_content(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def from_content(cls, content: dict[str, Any]) -> ObservedDataset:
        return cls.model_validate(content)

    @property
    def real(self) -> bool:
        return self.origin in REAL_ORIGINS

    def study_record(self) -> StudyRecord:
        return StudyRecord.model_validate(self.study)


def new_dataset_id() -> str:
    return f"ds-{uuid.uuid4().hex[:10]}"


class DatasetError(ValueError):
    pass


def _nca_check(dataset: ObservedDataset, mol_weight: float | None) -> list[str]:
    flags = []
    reported = {r.parameter: r for r in dataset.reported}
    means = [s for s in dataset.series if s.statistic != "individual"]
    if not means or not ({"AUC_last", "Cmax"} & set(reported)):
        return flags
    series = means[0]
    pairs = [(t, v) for t, v in zip(series.times, series.values, strict=True) if v is not None]
    if len(pairs) < 3:
        return flags
    result = nca([t for t, _ in pairs], [v for _, v in pairs])
    for key, ours, unit_power in (("Cmax", result.c_max, 0), ("AUC_last", result.auc_last, 1)):
        rep = reported.get(key)
        if rep is None or ours <= 0:
            continue
        try:
            # put the reported value in the dataset's concentration (and time) units before comparing; between two
            # mass (or two molar) units the molecular weight cancels, so any placeholder serves
            conc_unit, _, time_unit = rep.unit.partition("*") if "*" in rep.unit else (rep.unit, "", "")
            mw = mol_weight if mol_weight else (1.0 if is_molar(conc_unit.strip()) == is_molar(dataset.unit) else None)
            factor = umol_per_l_per(conc_unit.strip(), mw) / umol_per_l_per(dataset.unit, mw)
            if unit_power and time_unit.strip():
                factor *= minutes_per(time_unit.strip()) / minutes_per(dataset.time_unit)
        except UnitError:
            flags.append(f"reported {key} unit {rep.unit!r} not comparable (state it as concentration*time, e.g. ng/ml*h)")
            continue
        theirs = rep.value * factor
        if abs(ours - theirs) / theirs > NCA_TOLERANCE:
            flags.append(f"nca_mismatch {key}: profile gives {ours:.4g}, reported {theirs:.4g} "
                         f"({(ours / theirs - 1) * 100:+.0f} %)")
    return flags


def check_dataset(dataset: ObservedDataset, *, mol_weight: float | None = None) -> ObservedDataset:
    """Validate the study record and the data; return the dataset with its flags. Raises DatasetError when unusable."""
    try:
        record = StudyRecord.model_validate(dataset.study)
    except ValueError as exc:
        raise DatasetError(f"study record: {exc}") from exc
    try:
        minutes_per(dataset.time_unit)
        umol_per_l_per(dataset.unit, mol_weight if mol_weight else 1.0)
    except UnitError as exc:
        raise DatasetError(str(exc)) from exc
    if dataset.kind == "profile" and not dataset.series:
        raise DatasetError("a profile dataset needs at least one series")
    if dataset.kind == "pk_parameters" and not dataset.reported:
        raise DatasetError("a PK-parameter dataset needs at least one reported parameter")
    flags: list[str] = []
    for series in dataset.series:
        if len(series.times) != len(series.values):
            raise DatasetError(f"series {series.name}: {len(series.times)} times but {len(series.values)} values")
        if list(series.times) != sorted(series.times):
            raise DatasetError(f"series {series.name}: times are not in order")
        if any(v is not None and v < 0 for v in series.values):
            raise DatasetError(f"series {series.name}: negative concentration")
        if series.error is not None and len(series.error) != len(series.times):
            raise DatasetError(f"series {series.name}: error column length differs")
        if series.statistic != "individual" and series.n is None and record.n <= 1:
            flags.append(f"series {series.name}: mean values without N")
        if any(v is None for v in series.values) and record.lloq is None:
            flags.append(f"series {series.name}: values below LLOQ but no LLOQ stated")
    if dataset.origin is Origin.FIGURE_DIGITIZED and (dataset.digitization is None or not dataset.digitization.overlay_approved_by):
        flags.append("digitized: overlay not yet approved")
    flags.extend(_nca_check(dataset, mol_weight))
    if dataset.kind == "pk_parameters":
        flags.append("PK parameters only: judges a prediction, cannot train a profile fit")
    return dataset.model_copy(update={"flags": tuple(dict.fromkeys(flags))})
