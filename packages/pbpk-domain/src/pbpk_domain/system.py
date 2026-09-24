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
