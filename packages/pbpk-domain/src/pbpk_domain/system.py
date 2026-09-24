"""A model system: the compounds a PBPK model simulates together (plan `docs/plans/2026-09-24-multi-compound.md`).

The CPF stays the system of record, one per compound, unchanged in schema and rules. A `ModelSystem` groups them and
records what only exists between compounds, every item taken from a published snapshot or entered by the user:

- ``roles``: parent — dosed by some product — or metabolite — only formed. A compound can be both dosed and formed
  (dabigatran: given IV, and formed from the prodrug dabigatran etexilate); it is then a parent.
- ``formation``: which process of which compound forms which metabolite (the snapshot's ``Metabolite`` /
  ``MetaboliteName``).
- ``products``: what a study administers, as the fraction of its reported dose each dosed compound receives. It
  carries the salt correction and the enantiomer ratio (Verapamil HCl racemate: 120 mg -> 2 x 55.545 mg; an
  esomeprazole study doses one enantiomer, a racemic omeprazole study both), so it is required input, never a default
  (owner decision 2, 2026-09-24). A study names its product.
- ``observers``: sums of compounds (racemic, parent + glucuronide), copied verbatim from a published ``ObserverSets``
  document; never composed here (owner decision 4).
- ``analytes``: what a study can measure — one compound, or an observer — with the output path the published model
  reads it at.

A single-compound project is `ModelSystem.single(cpf)`: one parent, fraction 1, its plasma as the only analyte.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pbpk_domain.cpf.models import CPF

PLASMA = "Organism|PeripheralVenousBlood|{compound}|Plasma (Peripheral Venous Blood)"

Role = Literal["parent", "metabolite"]


class Formation(BaseModel):
    """A process of ``compound`` that forms ``metabolite`` (keyed as the snapshot selects it: molecule-data source)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    compound: str
    internal_name: str
    molecule: str
    data_source: str
    metabolite: str


class Analyte(BaseModel):
    """What a study measures and where the simulation reports it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    kind: Literal["compound", "observer"]
    compound: str | None = None       # kind == "compound"
    observer: str | None = None       # kind == "observer": an ObserverSets name
    output_path: str                  # the simulation output (harvested for observers)


class ModelSystem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    compounds: tuple[CPF, ...] = Field(min_length=1)
    roles: dict[str, Role]
    formation: tuple[Formation, ...] = ()
    products: dict[str, dict[str, float]] = Field(default_factory=dict)  # product -> {dosed compound: dose fraction}
    observers: dict[str, dict[str, Any]] = Field(default_factory=dict)  # ObserverSets name -> verbatim document
    analytes: dict[str, Analyte] = Field(default_factory=dict)
    source: str = ""

    @model_validator(mode="after")
    def _consistent(self) -> ModelSystem:
        names = [c.compound for c in self.compounds]
        if len(set(names)) != len(names):
            raise ValueError("a compound appears twice in the system")
        if set(self.roles) != set(names):
            raise ValueError("every compound needs exactly one role")
        if not any(r == "parent" for r in self.roles.values()):
            raise ValueError("a system needs at least one parent (dosed) compound")
        for f in self.formation:
            if f.compound not in names or f.metabolite not in names:
                raise ValueError(f"formation {f.compound} -> {f.metabolite}: both must be compounds of the system")
        for product, fractions in self.products.items():
            if not fractions:
                raise ValueError(f"product {product!r} doses no compound")
            for compound, fraction in fractions.items():
                if compound not in names or self.roles[compound] != "parent":
                    raise ValueError(f"product {product!r}: only a parent compound is dosed ({compound!r})")
                if not fraction > 0:
                    raise ValueError(f"product {product!r}: the dose fraction of {compound!r} must be > 0")
        dosed = {c for fractions in self.products.values() for c in fractions}
        if dosed != {n for n, r in self.roles.items() if r == "parent"}:
            raise ValueError("every parent must be dosed by a product, with its fraction (required input, never defaulted)")
        for a in self.analytes.values():
            if a.kind == "compound" and a.compound not in names:
                raise ValueError(f"analyte {a.name!r}: no compound {a.compound!r}")
            if a.kind == "observer" and a.observer not in self.observers:
                raise ValueError(f"analyte {a.name!r}: no observer {a.observer!r}")
        return self

    @classmethod
    def single(cls, cpf: CPF) -> ModelSystem:
        name = cpf.compound
        return cls(name=name, compounds=(cpf,), roles={name: "parent"}, products={name: {name: 1.0}},
                   analytes={name: Analyte(name=name, kind="compound", compound=name, output_path=PLASMA.format(compound=name))})

    def cpf(self, compound: str) -> CPF:
        return next(c for c in self.compounds if c.compound == compound)

    @property
    def parents(self) -> tuple[str, ...]:
        return tuple(c.compound for c in self.compounds if self.roles[c.compound] == "parent")

    def formed_by(self, compound: str) -> tuple[Formation, ...]:
        return tuple(f for f in self.formation if f.compound == compound)

    def closure(self, dosed: tuple[str, ...]) -> tuple[str, ...]:
        """The dosed compounds and every metabolite they form, directly or through another metabolite, in system
        order: the compounds a simulation of those doses must contain."""
        wanted = set(dosed)
        grew = True
        while grew:
            grew = False
            for f in self.formation:
                if f.compound in wanted and f.metabolite not in wanted:
                    wanted.add(f.metabolite)
                    grew = True
        return tuple(c.compound for c in self.compounds if c.compound in wanted)

    @property
    def sha256(self) -> str:
        """Content hash for the MAP and the report: the CPFs' contents (not their timestamps) and the links."""
        doc = self.model_dump(mode="json", exclude={"compounds"})
        doc["compounds"] = [c.model_dump(mode="json", exclude={"created_at"}) for c in self.compounds]
        return hashlib.sha256(json.dumps(doc, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


class SystemLinks(BaseModel):
    """A model system without its CPFs: what a project stores next to its per-compound CPFs (the CPF store keeps each
    compound's record and versions; the links name the compounds and relate them)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    compounds: tuple[str, ...] = Field(min_length=1)  # system order
    roles: dict[str, Role]
    formation: tuple[Formation, ...] = ()
    products: dict[str, dict[str, float]] = Field(default_factory=dict)
    observers: dict[str, dict[str, Any]] = Field(default_factory=dict)
    analytes: dict[str, Analyte] = Field(default_factory=dict)
    source: str = ""


def links_of(system: ModelSystem) -> SystemLinks:
    doc = system.model_dump(exclude={"compounds"})
    return SystemLinks(compounds=tuple(c.compound for c in system.compounds), **doc)


def assemble(links: SystemLinks, cpfs: dict[str, CPF]) -> ModelSystem:
    """The system from its links and the current CPF of each compound; raises ValueError naming missing CPFs."""
    missing = [c for c in links.compounds if c not in cpfs]
    if missing:
        raise ValueError(f"no CPF for {', '.join(missing)}; put each compound's CPF before using the system")
    doc = links.model_dump(exclude={"compounds"})
    return ModelSystem(compounds=tuple(cpfs[c] for c in links.compounds), **doc)


def with_cpf(system: ModelSystem, cpf: CPF) -> ModelSystem:
    """The system with one compound's CPF replaced (the round's fitted version of the parent)."""
    if cpf.compound not in system.roles:
        raise ValueError(f"{cpf.compound!r} is not a compound of the {system.name} system")
    return system.model_copy(update={"compounds": tuple(cpf if c.compound == cpf.compound else c for c in system.compounds)})


def analyte_molecular_weight(system: ModelSystem, analyte: str) -> tuple[float | None, str | None]:
    """(molecular weight to convert the analyte's observed concentrations with, reason when it cannot be evaluated).

    A compound analyte uses its own MW. A molar sum observer (enantiomers) uses its compounds' MW when they share one;
    a mass-concentration observer (Dabigatran's free + glucuronide ``SUM``) or a molar sum of different MWs has no
    single MW, so its studies are not evaluated in phase 1 (named, never converted by a guess)."""
    a = system.analytes.get(analyte)
    if a is None:
        return None, f"no analyte {analyte!r} in the system"
    if a.kind == "compound":
        mw = system.cpf(a.compound).get("phys.mw")
        return (mw.numeric_value, None) if mw is not None else (None, f"{a.compound} has no molecular weight")
    observer = next((o for o in system.observers[a.observer].get("Observers", []) if o.get("Name") == a.name), {})
    if observer.get("Dimension") != "Concentration (molar)":
        return None, f"{a.name}: a {str(observer.get('Dimension', 'non-molar')).lower()} sum is not evaluated yet"
    refs = [r.get("Path", "") for r in (observer.get("Formula") or {}).get("References", [])]
    members = {p.split("|")[-2] for p in refs if p.endswith("|Concentration") and p.count("|") >= 2}
    weights = {system.cpf(m).get("phys.mw").numeric_value for m in members
               if m in system.roles and system.cpf(m).get("phys.mw") is not None}
    if len(weights) != 1:
        return None, f"{a.name}: its compounds do not share one molecular weight"
    return weights.pop(), None


def gated(system: ModelSystem, analyte: str | None, fitted: str) -> bool:
    """Whether a study on ``analyte`` enters the acceptance gate and the fit: only the fitted parent's own plasma in
    phase 1 (owner decision 3: metabolite and sum analytes are reported, not gated)."""
    if analyte is None:
        return True
    a = system.analytes.get(analyte)
    return a is not None and a.kind == "compound" and a.compound == fitted
