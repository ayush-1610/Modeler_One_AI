"""Observed studies as uploaded: the request model and the observed PK derived from each profile.

The study upload (`POST .../studies`), the P4 hand-off to the campaign path (`inputs:publish`) and the P5 signature
(`plan:sign`) all read these; a module of its own so no router imports another.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from pbpk_domain.data_origin import DataOrigin


class ObservedProfile(BaseModel):
    times: list[float] = Field(min_length=1)
    values: list[float] = Field(min_length=1)
    time_unit: str = "min"
    unit: str = "µmol/l"
    sd: list[float] | None = None
    lloq: float | None = None


class StudyUpload(BaseModel):
    study_id: str = Field(min_length=1)
    reference: str = ""
    n: int = Field(default=12, gt=0)
    design: str = "SD"
    dosing_interval_h: float | None = Field(default=None, gt=0)  # multiple dose: one dose every N hours…
    n_doses: int | None = Field(default=None, gt=0)              # …this many times
    # a regimen whose doses differ (loading, then maintenance): [{start_h, dose_mg, n_doses, interval_h,
    # infusion_time_min}] in time order, dose_mg its first dose (StudyRecord.dose_phases)
    dose_phases: list[dict[str, Any]] = Field(default_factory=list)
    route: str = "oral"
    dose_mg: float = Field(gt=0)
    dose_per_kg: bool = False  # dose_mg is per kg body weight
    infusion_time_min: float | None = None
    formulation: str = "solution"
    formulation_name: str | None = None  # a tablet/capsule study: the CPF formulation it used (form.{name}.*)
    food_state: str = "fasted"
    # every meal as given: [{time_h (after the first dose; negative: before), template, name, parameters}]
    meals: list[dict[str, Any]] = Field(default_factory=list)
    # process selections the study's simulation leaves out (compound -> names): a phenotype such as a CYP2C19 poor
    # metaboliser; such a study is a genotype (PGx) study
    inactive_processes: dict[str, list[str]] = Field(default_factory=dict)
    # simulation-level model values (full paths) the study's simulation leaves at PK-Sim's default
    default_simulation_values: list[str] = Field(default_factory=list)
    solver: dict[str, float] = Field(default_factory=dict)  # the published simulation's own solver settings
    water_ml_per_kg: float | None = Field(default=None, ge=0)  # water with an oral dose; None: PK-Sim's 3.5 ml/kg
    # Who was studied: a patient or special population (e.g. renal impairment) is classified SPECIAL by the split
    # (MS-01 §3.2) and never fits the healthy-volunteer model; without these it would be taken as healthy.
    population_type: str = "healthy"
    special_population: str | None = None
    co_medication: str | None = None  # a co-medicated arm is a DDI study (MS-01 §3.2), never the drug alone
    # The studied individual (population, sex, age, age range): the round build simulates the study in it.
    demographics: dict[str, Any] | None = None
    # A reference model's own individual for this study (reference import only): physiology overrides and expression
    # values, paths and units copied from the published snapshot (StudyRecord.published_individual).
    published_individual: dict[str, Any] | None = None
    analyte: str | None = None  # a model system's analyte (compound or sum) the study measures
    product: str | None = None  # the system's product the study administers
    n_timepoints: int = Field(default=10, gt=0)
    lloq: float | None = None
    profile: ObservedProfile
    # Where the data came from (plan §9.4). None: not recorded, which is never taken as real.
    origin: DataOrigin | None = None


class StudiesUpload(BaseModel):
    studies: list[StudyUpload] = Field(min_length=1)


def observed_from_studies(rows: list[dict[str, Any]], mol_weight: float | None) -> dict[str, Any]:
    """Deterministic NCA per uploaded profile → the observed PK the gate (auc/cmax) and the fit (profile) read.

    Each profile is first converted to the engine's units (minutes, µmol/l — `pbpk_domain.units`), so predicted
    and observed AUC/Cmax are compared in the same units whatever the study reported. Raises UnitError."""
    from pbpk_domain.nca import nca
    from pbpk_domain.units import normalize_profile

    observed: dict[str, Any] = {}
    for row in rows:
        profile = row.get("profile")
        if not profile:
            continue
        canonical = normalize_profile(profile, mol_weight)
        result = nca(list(canonical["times"]), list(canonical["values"]))
        observed[row["study_id"]] = {
            "auc": result.auc_last, "cmax": result.c_max, "tmax": result.t_max, "thalf": result.t_half,
            "profile": canonical, "origin": row.get("origin"),
        }
    return observed
