"""Compound Parameter Framework (CPF): the versioned system of record for a compound (MS-01 §2).

One document holds every parameter of a compound — physchem, binding, distribution, elimination,
formulation, DDI — each with a value, unit, status, fit policy, plausibility range, provenance and an
engine binding. Every simulation (IV, oral, fed, validation, application) is regenerated from this one
document; stages never hand-edit simulation-level overrides, they produce a new CPF version and rebuild.

- `models`: the parameter record and the CPF document, with versioning and JSON-Schema export.
- `completeness`: the S0 readiness gate (§2.2 completeness rule).
- `binding`: resolve each parameter's engine binding against an engine catalog (T-02); no guessing.
- `build`: regenerate a PK-Sim snapshot from a CPF plus a system and a list of scenarios.
"""

from pbpk_domain.cpf.binding import BindingError, BuildPlan, ParameterBinding, bind
from pbpk_domain.cpf.build import BuildReport, Scenario, build_from_cpf
from pbpk_domain.cpf.completeness import CompletenessReport, check_completeness
from pbpk_domain.cpf.models import (
    CPF,
    EngineBinding,
    FitPolicy,
    ParameterRecord,
    ParameterStatus,
    Plausibility,
    Provenance,
)

__all__ = [
    "CPF",
    "BindingError",
    "BuildPlan",
    "BuildReport",
    "CompletenessReport",
    "EngineBinding",
    "FitPolicy",
    "ParameterBinding",
    "ParameterRecord",
    "ParameterStatus",
    "Plausibility",
    "Provenance",
    "Scenario",
    "bind",
    "build_from_cpf",
    "check_completeness",
]
