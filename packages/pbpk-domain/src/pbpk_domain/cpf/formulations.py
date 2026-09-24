"""Formulations in the CPF (MS-01 §2.2): ``form.{name}.type`` and ``form.{name}.weibull.{t50,shape,lag}``.

A solid oral study (tablet, capsule) is simulated with the formulation it names: a Weibull release (PK-Sim
``Formulation_Tablet_Weibull``) or, for a rapidly dissolving product (> 85 % in 15 min, MS-01 §4 S2), ``Dissolved``.
The Weibull values are the in-vitro dissolution fit; S3 may adjust t50 and shape in vivo within the parameter's fit
policy ([0.5×, 2×] of the in-vitro fit). Lag time defaults to 0 min and "Use as suspension" to 1, as in every
published OSP tablet model (Dapagliflozin, Midazolam, Itraconazole reference snapshots).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from pbpk_domain.cpf.models import CPF, ParameterRecord, ParameterStatus
from pbpk_domain.snapshot.builder import (
    DissolvedFormulationSpec,
    Measured,
    ParticleFormulationSpec,
    WeibullFormulationSpec,
)

# form.{name}.type values the builder can place. Lint80, particle dissolution and table release are MS-01
# formulation types the builder does not place yet (T-10 tail).
WEIBULL = "Weibull"
DISSOLVED = "Dissolved"
# Particle dissolution (Noyes-Whitney, monodisperse) and a product given as several particle-size bins at once, as the
# OSP Ketoconazole model writes them: form.{name}.particles.{thickness,radius,distribution}; form.{product}.bins is the
# bins' names and mass fractions (JSON), taken from the published protocol that doses them together.
PARTICLES = "Particles"
PARTICLE_BINS = "ParticleBins"
SUPPORTED_TYPES = (WEIBULL, DISSOLVED, PARTICLES, PARTICLE_BINS)
PARTICLE_PARAMETERS = {
    "thickness": ("Thickness (unstirred water layer)", "mm"),
    "radius": ("Particle radius (mean)", "µm"),
    "distribution": ("Type of particle size distribution", None),
}

# Weibull CPF key -> the PK-Sim formulation parameter (harvested from an exported simulation on ospsuite 12.4.4,
# 2026-09-24: "Events|<protocol>|<formulation>|Dissolution time (50% dissolved)", "…|Dissolution shape", "…|Lag time").
WEIBULL_PARAMETERS = {
    "t50": "Dissolution time (50% dissolved)",
    "shape": "Dissolution shape",
    "lag": "Lag time",
}


class FormulationError(ValueError):
    """A formulation the CPF does not define completely, or of a type the builder cannot place (never guessed)."""


@dataclass(frozen=True)
class CpfFormulation:
    name: str
    type: str
    t50_min: float | None = None
    shape: float | None = None
    lag_min: float = 0.0
    thickness_mm: float | None = None
    radius_um: float | None = None
    distribution: float = 0.0
    bins: tuple[tuple[CpfFormulation, float], ...] = ()  # PARTICLE_BINS: each bin and its mass fraction

    def to_spec(self) -> WeibullFormulationSpec | DissolvedFormulationSpec | ParticleFormulationSpec:
        if self.type == DISSOLVED:
            return DissolvedFormulationSpec(name=self.name)
        if self.type == PARTICLES:
            return ParticleFormulationSpec(name=self.name, thickness=Measured(value=self.thickness_mm, unit="mm"),
                                           radius=Measured(value=self.radius_um, unit="µm"),
                                           distribution_type=self.distribution)
        if self.type == PARTICLE_BINS:
            raise FormulationError(f"{self.name!r} is a product of several bins: use to_specs()")
        return WeibullFormulationSpec(name=self.name, dissolution_time_50_min=self.t50_min, shape=self.shape,
                                      lag_time_min=self.lag_min)

    def to_specs(self) -> tuple[list, tuple[tuple[str, float], ...]]:
        """(the formulation specs the product needs, its bins as (formulation, mass fraction)); no bins for a single
        formulation."""
        if self.type != PARTICLE_BINS:
            return [self.to_spec()], ()
        return [b.to_spec() for b, _f in self.bins], tuple((b.name, f) for b, f in self.bins)


def _present(record: ParameterRecord | None) -> bool:
    return record is not None and record.status is not ParameterStatus.MISSING and record.value is not None


def formulation_names(cpf: CPF) -> tuple[str, ...]:
    """The formulation names the CPF defines (``form.{name}.…``), in CPF order."""
    names: dict[str, None] = {}
    for record in cpf.with_prefix("form"):
        parts = record.id.split(".")
        if len(parts) >= 3:
            names.setdefault(parts[1], None)
    return tuple(names)


def cpf_formulation(cpf: CPF, name: str) -> CpfFormulation:
    """The named formulation from the CPF. Raises FormulationError when it is missing, incomplete, or of a type
    the builder cannot place."""
    type_record = cpf.get(f"form.{name}.type")
    if not _present(type_record):
        raise FormulationError(f"the CPF defines no formulation {name!r} (form.{name}.type)")
    kind = str(type_record.value)
    if kind not in SUPPORTED_TYPES:
        raise FormulationError(f"formulation {name!r} is of type {kind!r}; the builder places {', '.join(SUPPORTED_TYPES)}")
    if kind == DISSOLVED:
        return CpfFormulation(name=name, type=kind)
    if kind == PARTICLES:
        values = {key: cpf.get(f"form.{name}.particles.{key}") for key in PARTICLE_PARAMETERS}
        missing = [f"form.{name}.particles.{k}" for k in ("thickness", "radius") if not _present(values[k])]
        if missing:
            raise FormulationError(f"particle formulation {name!r} needs {', '.join(missing)}")
        distribution = values["distribution"].numeric_value if _present(values["distribution"]) else 0.0
        return CpfFormulation(name=name, type=kind, thickness_mm=values["thickness"].numeric_value,
                              radius_um=values["radius"].numeric_value, distribution=distribution)
    if kind == PARTICLE_BINS:
        record = cpf.get(f"form.{name}.bins")
        if not _present(record):
            raise FormulationError(f"binned product {name!r} needs form.{name}.bins (its bins and mass fractions)")
        bins = tuple((cpf_formulation(cpf, entry["formulation"]), float(entry["fraction"]))
                     for entry in json.loads(str(record.value)))
        if any(b.type == PARTICLE_BINS for b, _f in bins):
            raise FormulationError(f"binned product {name!r}: a bin cannot itself be a binned product")
        return CpfFormulation(name=name, type=kind, bins=bins)
    values = {key: cpf.get(f"form.{name}.weibull.{key}") for key in WEIBULL_PARAMETERS}
    missing = [f"form.{name}.weibull.{k}" for k in ("t50", "shape") if not _present(values[k])]
    if missing:
        raise FormulationError(f"Weibull formulation {name!r} needs {', '.join(missing)} (the in-vitro dissolution fit)")
    lag = values["lag"].numeric_value if _present(values["lag"]) else 0.0
    return CpfFormulation(name=name, type=kind, t50_min=values["t50"].numeric_value, shape=values["shape"].numeric_value,
                          lag_min=lag)


def resolve_formulation_name(cpf: CPF, requested: str | None) -> tuple[str, str | None]:
    """The CPF formulation a solid study uses, and a note when it was not named explicitly.

    A study that names its formulation uses it. One that does not, in a CPF defining exactly one formulation, uses
    that one — recorded in the note, because it is an assignment the modeler should see. Anything else raises."""
    if requested:
        return requested, None
    names = formulation_names(cpf)
    if len(names) == 1:
        return names[0], f"formulation not named by the study; the CPF's only formulation {names[0]!r} was used"
    if not names:
        raise FormulationError("the study is a solid oral form but the CPF defines no formulation (form.{name}.type)")
    raise FormulationError(f"the study does not name its formulation and the CPF defines several: {', '.join(names)}")


def weibull_parameter_path(param_id: str, *, protocol: str) -> str | None:
    """The PK-Sim simulation path of a ``form.{name}.weibull.{key}`` parameter under a protocol, or None when the id
    is not a Weibull parameter."""
    parts = param_id.split(".")
    if len(parts) != 4 or parts[0] != "form" or parts[2] != "weibull" or parts[3] not in WEIBULL_PARAMETERS:
        return None
    return f"Events|{protocol}|{parts[1]}|{WEIBULL_PARAMETERS[parts[3]]}"
