"""Deterministic construction of PK-Sim snapshots from validated platform specs.

Identical specs always produce the same snapshot and therefore the same content hash. Only
structures observed in real PK-Sim snapshots are emitted. Anything an engine version adds comes
from that engine's harvested catalog (engine qualification, F-405), never from guesses here.

Unit rule: every quantity must already be in the unit PK-Sim stores for it. The builder rejects
anything else instead of converting silently.
"""

from __future__ import annotations

import unicodedata
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pbpk_domain.issues import Issue
from pbpk_domain.snapshot.models import (
    AlternativeSelection,
    Compound,
    CompoundProcess,
    Event,
    ExpressionProfile,
    Formulation,
    FormulationSelection,
    Individual,
    OriginData,
    OutputInterval,
    Parameter,
    ParameterAlternative,
    PkaType,
    Protocol,
    ProtocolSelection,
    Quantity,
    Schema,
    SchemaItem,
    Simulation,
    SimulationCompound,
    Snapshot,
    ValueOrigin,
    expression_profile_reference,
)
from pbpk_domain.snapshot.validation import interaction_selection_for, process_selection_for, validate_references

SNAPSHOT_VERSION_PKSIM_12 = 80
SNAPSHOT_VERSION_PKSIM_13 = 81

# Read from a PK-Sim 12 snapshot (OSP Dapagliflozin model). The engine catalog supersedes these.
DEFAULT_COMPOUND_CALCULATION_METHODS = (
    "Cellular partition coefficient method - Rodgers and Rowland",
    "Cellular permeability - PK-Sim Standard",
)
DEFAULT_INDIVIDUAL_CALCULATION_METHODS = ("SurfaceAreaPlsInt_VAR1", "Body surface area - Mosteller")
PLASMA_OUTPUT_PATH = "Organism|PeripheralVenousBlood|{compound}|Plasma (Peripheral Venous Blood)"


class SnapshotBuildError(ValueError):
    def __init__(self, issues: list[Issue]):
        self.issues = issues
        super().__init__("; ".join(str(i) for i in issues))


def _nfc(unit: str | None) -> str | None:
    return None if unit is None else unicodedata.normalize("NFC", unit)


class Spec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Measured(Spec):
    """A value with its unit and provenance, as it will appear in the snapshot."""

    value: float
    unit: str | None = None
    origin: ValueOrigin | None = None

    def to_parameter(self, *, name: str | None = None, path: str | None = None) -> Parameter:
        fields: dict = {"value": self.value}
        if name is not None:
            fields["name"] = name
        if path is not None:
            fields["path"] = path
        if self.unit is not None:
            fields["unit"] = _nfc(self.unit)
        if self.origin is not None:
            fields["value_origin"] = self.origin
        return Parameter(**fields)


def _check(measured: Measured | None, *, unit: str | None, label: str, positive: bool = True) -> Measured | None:
    if measured is None:
        return None
    if _nfc(measured.unit) != _nfc(unit):
        raise ValueError(f"{label} must be given in {unit!r} (got {measured.unit!r}); convert before building")
    if positive and not measured.value > 0:
        raise ValueError(f"{label} must be > 0 (got {measured.value})")
    return measured


# --- compound -----------------------------------------------------------------------------------


class PkaSpec(Spec):
    type: Literal["Acid", "Base"]
    pka: float
    origin: ValueOrigin | None = None


class FirstOrderMetabolism(Spec):
    kind: Literal["MetabolizationSpecific_FirstOrder"] = "MetabolizationSpecific_FirstOrder"
    molecule: str = Field(min_length=1)
    data_source: str = Field(min_length=1)
    metabolite: str | None = None
    clearance_per_enzyme: Measured

    @field_validator("clearance_per_enzyme")
    @classmethod
    def _unit(cls, v: Measured) -> Measured:
        return _check(v, unit="l/µmol/min", label="CLspec/[Enzyme]")

    def to_process(self) -> CompoundProcess:
        fields: dict = {"internal_name": self.kind, "data_source": self.data_source, "molecule": self.molecule}
        if self.metabolite:
            fields["metabolite"] = self.metabolite
        fields["parameters"] = [self.clearance_per_enzyme.to_parameter(name="CLspec/[Enzyme]")]
        return CompoundProcess(**fields)


class GlomerularFiltration(Spec):
    kind: Literal["GlomerularFiltration"] = "GlomerularFiltration"
    data_source: str = Field(min_length=1)
    gfr_fraction: Measured
    species: str = "Human"

    @field_validator("gfr_fraction")
    @classmethod
    def _unit(cls, v: Measured) -> Measured:
        return _check(v, unit=None, label="GFR fraction")

    def to_process(self) -> CompoundProcess:
        return CompoundProcess(
            internal_name=self.kind,
            data_source=self.data_source,
            species=self.species,
            parameters=[self.gfr_fraction.to_parameter(name="GFR fraction")],
        )


class MichaelisMentenMetabolism(Spec):
    """Saturable enzyme metabolism (PK-Sim ``MetabolizationSpecific_MM``). Parameter names and units are
    from the OSP Rifampicin model; Vmax and Km are the identifiable pair (MS-01 §2.2), kcat and enzyme
    concentration are optional and only emitted when supplied."""

    kind: Literal["MetabolizationSpecific_MM"] = "MetabolizationSpecific_MM"
    molecule: str = Field(min_length=1)
    data_source: str = Field(min_length=1)
    metabolite: str | None = None
    vmax: Measured
    km: Measured
    kcat: Measured | None = None
    enzyme_concentration: Measured | None = None

    @field_validator("vmax")
    @classmethod
    def _vmax(cls, v: Measured) -> Measured:
        return _check(v, unit="µmol/l/min", label="Vmax", positive=False)

    @model_validator(mode="after")
    def _rate(self):
        # Vmax 0 is a real published input (Cimetidine, Dabigatran, S-Warfarin) when kcat carries the rate
        if not self.vmax.value > 0 and (self.kcat is None or not self.kcat.value > 0):
            raise ValueError("Vmax must be > 0 unless kcat is given")
        return self

    @field_validator("km")
    @classmethod
    def _km(cls, v: Measured) -> Measured:
        return _check(v, unit="µmol/l", label="Km")

    @field_validator("kcat")
    @classmethod
    def _kcat(cls, v: Measured | None) -> Measured | None:
        return _check(v, unit="1/min", label="kcat")

    @field_validator("enzyme_concentration")
    @classmethod
    def _conc(cls, v: Measured | None) -> Measured | None:
        return _check(v, unit="µmol/l", label="Enzyme concentration")

    def to_process(self) -> CompoundProcess:
        parameters = []
        if self.enzyme_concentration is not None:
            parameters.append(self.enzyme_concentration.to_parameter(name="Enzyme concentration"))
        parameters.append(self.vmax.to_parameter(name="Vmax"))
        parameters.append(self.km.to_parameter(name="Km"))
        if self.kcat is not None:
            parameters.append(self.kcat.to_parameter(name="kcat"))
        fields: dict = {"internal_name": self.kind, "data_source": self.data_source, "molecule": self.molecule, "parameters": parameters}
        if self.metabolite:
            fields["metabolite"] = self.metabolite
        return CompoundProcess(**fields)


class TransporterMichaelisMenten(Spec):
    """Saturable active transport (PK-Sim ``ActiveTransportSpecific_MM``). Names/units from the OSP
    Rifampicin model. The transporter needs an expression profile (``ExpressionSpec`` type Transporter)."""

    kind: Literal["ActiveTransportSpecific_MM"] = "ActiveTransportSpecific_MM"
    molecule: str = Field(min_length=1)
    data_source: str = Field(min_length=1)
    vmax: Measured
    km: Measured
    transporter_concentration: Measured | None = None
    kcat: Measured | None = None

    @field_validator("vmax")
    @classmethod
    def _vmax(cls, v: Measured) -> Measured:
        return _check(v, unit="µmol/l/min", label="Vmax", positive=False)

    @model_validator(mode="after")
    def _rate(self):
        # Vmax 0 is a real published input (Cimetidine, Dabigatran, S-Warfarin) when kcat carries the rate
        if not self.vmax.value > 0 and (self.kcat is None or not self.kcat.value > 0):
            raise ValueError("Vmax must be > 0 unless kcat is given")
        return self

    @field_validator("km")
    @classmethod
    def _km(cls, v: Measured) -> Measured:
        return _check(v, unit="µmol/l", label="Km")

    @field_validator("transporter_concentration")
    @classmethod
    def _conc(cls, v: Measured | None) -> Measured | None:
        return _check(v, unit="nmol/l", label="Transporter concentration")

    @field_validator("kcat")
    @classmethod
    def _kcat(cls, v: Measured | None) -> Measured | None:
        return _check(v, unit="1/min", label="kcat")

    def to_process(self) -> CompoundProcess:
        parameters = []
        if self.transporter_concentration is not None:
            parameters.append(self.transporter_concentration.to_parameter(name="Transporter concentration"))
        parameters.append(self.vmax.to_parameter(name="Vmax"))
        parameters.append(self.km.to_parameter(name="Km"))
        if self.kcat is not None:
            parameters.append(self.kcat.to_parameter(name="kcat"))
        return CompoundProcess(
            internal_name=self.kind, data_source=self.data_source, molecule=self.molecule, parameters=parameters
        )


class CompetitiveInhibition(Spec):
    """Reversible competitive inhibition of an enzyme/transporter (PK-Sim ``CompetitiveInhibition``)."""

    kind: Literal["CompetitiveInhibition"] = "CompetitiveInhibition"
    molecule: str = Field(min_length=1)
    data_source: str = Field(min_length=1)
    ki: Measured

    @field_validator("ki")
    @classmethod
    def _ki(cls, v: Measured) -> Measured:
        return _check(v, unit="µmol/l", label="Ki")

    def to_process(self) -> CompoundProcess:
        return CompoundProcess(
            internal_name=self.kind, data_source=self.data_source, molecule=self.molecule,
            parameters=[self.ki.to_parameter(name="Ki")],
        )


class Induction(Spec):
    """Enzyme/transporter induction (PK-Sim ``Induction``); Emax is dimensionless."""

    kind: Literal["Induction"] = "Induction"
    molecule: str = Field(min_length=1)
    data_source: str = Field(min_length=1)
    ec50: Measured
    emax: Measured

    @field_validator("ec50")
    @classmethod
    def _ec50(cls, v: Measured) -> Measured:
        return _check(v, unit="µmol/l", label="EC50")

    @field_validator("emax")
    @classmethod
    def _emax(cls, v: Measured) -> Measured:
        return _check(v, unit=None, label="Emax")

    def to_process(self) -> CompoundProcess:
        return CompoundProcess(
            internal_name=self.kind, data_source=self.data_source, molecule=self.molecule,
            parameters=[self.ec50.to_parameter(name="EC50"), self.emax.to_parameter(name="Emax")],
        )


class SpecificBinding(Spec):
    """Specific binding to a target (PK-Sim ``SpecificBinding``); names/units from the OSP Midazolam model."""

    kind: Literal["SpecificBinding"] = "SpecificBinding"
    molecule: str = Field(min_length=1)
    data_source: str = Field(min_length=1)
    koff: Measured
    kd: Measured

    @field_validator("koff")
    @classmethod
    def _koff(cls, v: Measured) -> Measured:
        return _check(v, unit="1/min", label="koff")

    @field_validator("kd")
    @classmethod
    def _kd(cls, v: Measured) -> Measured:
        return _check(v, unit="nmol/l", label="Kd")

    def to_process(self) -> CompoundProcess:
        return CompoundProcess(
            internal_name=self.kind, data_source=self.data_source, molecule=self.molecule,
            parameters=[self.koff.to_parameter(name="koff"), self.kd.to_parameter(name="Kd")],
        )


class MicrosomalMichaelisMenten(Spec):
    """Saturable metabolism scaled from liver microsomes (PK-Sim ``MetabolizationLiverMicrosomes_MM``). Names and
    units are from the OSP Midazolam model (CYP3A4, UGT1A4): the in-vitro Vmax per mg microsomal protein and, where
    the model sets it, the enzyme content of the microsomes; Km; and kcat, which the published model fits and which
    then governs the in-vivo rate."""

    kind: Literal["MetabolizationLiverMicrosomes_MM"] = "MetabolizationLiverMicrosomes_MM"
    molecule: str = Field(min_length=1)
    data_source: str = Field(min_length=1)
    metabolite: str | None = None
    km: Measured
    kcat: Measured | None = None  # absent: PK-Sim computes it from the in-vitro Vmax (its formula, not ours)
    in_vitro_vmax: Measured | None = None
    microsomal_content: Measured | None = None

    @model_validator(mode="after")
    def _rate(self) -> MicrosomalMichaelisMenten:
        if self.kcat is None and self.in_vitro_vmax is None:
            raise ValueError("a microsomal Michaelis-Menten process needs kcat or the in-vitro Vmax")
        return self

    @field_validator("km")
    @classmethod
    def _km(cls, v: Measured) -> Measured:
        return _check(v, unit="µmol/l", label="Km")

    @field_validator("kcat")
    @classmethod
    def _kcat(cls, v: Measured | None) -> Measured | None:
        return _check(v, unit="1/min", label="kcat")

    @field_validator("in_vitro_vmax")
    @classmethod
    def _vmax(cls, v: Measured | None) -> Measured | None:
        # 0 is a real published value (Clarithromycin, Fluvoxamine): the fitted kcat then carries the rate
        return _check(v, unit="pmol/min/mg mic. protein", label="In vitro Vmax for liver microsomes", positive=False)

    @field_validator("microsomal_content")
    @classmethod
    def _content(cls, v: Measured | None) -> Measured | None:
        return _check(v, unit="pmol/mg mic. protein", label="Content of CYP proteins in liver microsomes")

    def to_process(self) -> CompoundProcess:
        parameters = []
        if self.in_vitro_vmax is not None:
            parameters.append(self.in_vitro_vmax.to_parameter(name="In vitro Vmax for liver microsomes"))
        if self.microsomal_content is not None:
            parameters.append(self.microsomal_content.to_parameter(name="Content of CYP proteins in liver microsomes"))
        parameters.append(self.km.to_parameter(name="Km"))
        if self.kcat is not None:
            parameters.append(self.kcat.to_parameter(name="kcat"))
        fields: dict = {"internal_name": self.kind, "data_source": self.data_source, "molecule": self.molecule,
                        "parameters": parameters}
        if self.metabolite:
            fields["metabolite"] = self.metabolite
        return CompoundProcess(**fields)


# Process types placed by their harvested parameter names and units (the snapshots of the OSP model library,
# 2026-09-24; the builder's unit for each name, the importer converts to it). A name outside this table is refused:
# it would be a guessed parameter. Molecule-less types (total hepatic / renal clearance) carry a species instead.
HARVESTED_PROCESSES: dict[str, dict[str, str | None]] = {
    "MetabolizationIntrinsic_FirstOrder": {"Intrinsic clearance": "l/min", "Specific clearance": "1/min"},
    "rCYP450_MM": {"In vitro Vmax/recombinant enzyme": "pmol/min/pmol rec. enzyme", "Km": "µmol/l", "kcat": "1/min"},
    "rCYP450_FirstOrder": {"In vitro CL/recombinant enzyme": "µl/min/pmol rec. enzyme", "CLspec/[Enzyme]": "l/µmol/min"},
    "LiverClearance": {"Plasma clearance": "ml/min/kg", "Specific clearance": "1/min", "Fraction unbound (experiment)": None,
                       "Lipophilicity (experiment)": "Log Units", "Blood/Plasma concentration ratio": None},
    "KidneyClearance": {"Plasma clearance": "ml/min/kg", "Specific clearance": "1/min", "Fraction unbound (experiment)": None,
                        "Blood flow rate (kidney)": "l/min", "Body weight": "kg"},
    "ActiveTransportSpecific_Hill": {"Vmax": "µmol/l/min", "Km": "µmol/l", "Transporter concentration": "µmol/l",
                                     "Hill coefficient": None},
    "ActiveTransport_InVitro_VesicularAssay_MM": {"In vitro Vmax/transporter": "pmol/min/pmol transporter",
                                                  "Km": "µmol/l", "kcat": "1/min"},
    "IrreversibleInhibition": {"kinact": "1/min", "K_kinact_half": "µmol/l", "Ki": "µmol/l"},
    "MixedInhibition": {"Ki_c": "µmol/l", "Ki_u": "µmol/l"},
    "NoncompetitiveInhibition": {"Ki": "µmol/l"},
}
HARVESTED_SYSTEMIC = frozenset({"LiverClearance", "KidneyClearance"})


class HarvestedProcess(Spec):
    """A process of a type in HARVESTED_PROCESSES, written with exactly the parameters the CPF carries for it (PK-Sim
    computes the ones a snapshot leaves out, e.g. kcat from an in-vitro Vmax)."""

    kind: Literal["harvested"] = "harvested"
    internal_name: str
    molecule: str | None = None
    data_source: str = Field(min_length=1)
    metabolite: str | None = None
    species: str = "Human"
    parameters: dict[str, Measured] = Field(min_length=1)

    @model_validator(mode="after")
    def _harvested(self) -> HarvestedProcess:
        allowed = HARVESTED_PROCESSES.get(self.internal_name)
        if allowed is None:
            raise ValueError(f"process type {self.internal_name!r} has no harvested parameter table")
        if (self.internal_name in HARVESTED_SYSTEMIC) == bool(self.molecule):
            raise ValueError(f"{self.internal_name}: a molecule is required for a molecule-based process and "
                             "forbidden for a systemic one")
        for name, measured in self.parameters.items():
            if name not in allowed:
                raise ValueError(f"{self.internal_name}: parameter {name!r} is not a harvested name")
            _check(measured, unit=allowed[name], label=f"{self.internal_name} {name}", positive=False)
        return self

    def to_process(self) -> CompoundProcess:
        fields: dict = {"internal_name": self.internal_name, "data_source": self.data_source,
                        "parameters": [m.to_parameter(name=n) for n, m in self.parameters.items()]}
        if self.molecule:
            fields["molecule"] = self.molecule
        if self.metabolite:
            fields["metabolite"] = self.metabolite
        if self.internal_name in HARVESTED_SYSTEMIC or self.internal_name == "MetabolizationIntrinsic_FirstOrder":
            fields["species"] = self.species  # these types carry Species in the published snapshots
        return CompoundProcess(**fields)


ProcessSpec = Annotated[
    FirstOrderMetabolism
    | HarvestedProcess
    | MichaelisMentenMetabolism
    | MicrosomalMichaelisMenten
    | TransporterMichaelisMenten
    | CompetitiveInhibition
    | Induction
    | SpecificBinding
    | GlomerularFiltration,
    Field(discriminator="kind"),
]


class CompoundSpec(Spec):
    name: str = Field(min_length=1)
    molecular_weight: Measured
    lipophilicity: Measured
    fraction_unbound: Measured
    solubility: Measured | None = None
    solubility_reference_ph: float = Field(default=7.0, ge=0, le=14)
    # A measured pH-solubility table instead (pH, mg/l), written as PK-Sim's "Solubility table" TableFormula (the
    # structure harvested from the OSP Raltegravir and Voriconazole snapshots); `solubility_table_value` is its Value.
    solubility_table: tuple[tuple[float, float], ...] | None = None
    solubility_table_value: float | None = None
    intestinal_permeability: Measured | None = None
    permeability: Measured | None = None
    pka: list[PkaSpec] = Field(default_factory=list, max_length=3)  # PK-Sim supports up to 3 pKa values [VERIFY]
    halogens: dict[Literal["F", "Cl", "Br", "I"], int] = Field(default_factory=dict)
    # None leaves the partner unset, so PK-Sim applies its own default: as a published compound that does not set it
    # does (OSP Alprazolam, Verapamil; PK-Sim stores 2 there, where an explicit "Albumin" stores 1)
    binding_partner: Literal["Albumin", "Glycoprotein", "Unknown"] | None = "Albumin"
    processes: list[ProcessSpec] = Field(default_factory=list)
    calculation_methods: tuple[str, ...] = DEFAULT_COMPOUND_CALCULATION_METHODS
    alternative_name: str = "Measured"
    # A process selection the published simulations run on another molecule of the individual than the process
    # names (selection name -> MoleculeName): the OSP Dabigatran model selects its ``ABCB1-FIT`` transport on the
    # individual's ``P-gp``. Unset, a selection runs on the process's own molecule.
    selected_molecules: dict[str, str] = Field(default_factory=dict)
    # Further alternatives of a property group that a simulation selects by its product and food state, as the
    # published model does (OSP Itraconazole solubility "Capsule fed", Ketoconazole intestinal permeability "Fit fed"):
    # name -> (solubility at reference pH, reference pH) / permeability. Written after the default, IsDefault false.
    solubility_alternatives: dict[str, tuple[Measured, float]] = Field(default_factory=dict)
    intestinal_permeability_alternatives: dict[str, Measured] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _alternative_names(self):
        for label, names in (("solubility", self.solubility_alternatives), ("intestinal permeability",
                                                                          self.intestinal_permeability_alternatives)):
            if self.alternative_name in names:
                raise ValueError(f"a {label} alternative may not reuse the default's name {self.alternative_name!r}")
        if self.solubility_alternatives and self.solubility is None:
            raise ValueError("solubility alternatives need the default solubility")
        if self.intestinal_permeability_alternatives and self.intestinal_permeability is None:
            raise ValueError("intestinal permeability alternatives need the default intestinal permeability")
        for sol, _ph in self.solubility_alternatives.values():
            _check(sol, unit="mg/ml", label="Solubility at reference pH")
        for perm in self.intestinal_permeability_alternatives.values():
            _check(perm, unit="cm/min", label="Permeability")
        return self

    def alternatives_of(self, group: str) -> tuple[str, ...]:
        """Every alternative name of a simulation-selectable group ("COMPOUND_SOLUBILITY", ...), the default first."""
        extra = {"COMPOUND_SOLUBILITY": self.solubility_alternatives,
                 "COMPOUND_INTESTINAL_PERMEABILITY": self.intestinal_permeability_alternatives}.get(group, {})
        return (self.alternative_name, *extra)

    @field_validator("molecular_weight")
    @classmethod
    def _mw(cls, v: Measured) -> Measured:
        return _check(v, unit="g/mol", label="Molecular weight")

    @field_validator("lipophilicity")
    @classmethod
    def _logp(cls, v: Measured) -> Measured:
        return _check(v, unit="Log Units", label="Lipophilicity", positive=False)

    @field_validator("fraction_unbound")
    @classmethod
    def _fu(cls, v: Measured) -> Measured:
        _check(v, unit=None, label="Fraction unbound")
        if v.value > 1:
            raise ValueError(f"Fraction unbound must be in (0, 1] (got {v.value})")
        return v

    @field_validator("solubility")
    @classmethod
    def _solubility(cls, v: Measured | None) -> Measured | None:
        return _check(v, unit="mg/ml", label="Solubility at reference pH")

    @field_validator("intestinal_permeability", "permeability")
    @classmethod
    def _permeability(cls, v: Measured | None) -> Measured | None:
        return _check(v, unit="cm/min", label="Permeability")

    @field_validator("halogens")
    @classmethod
    def _halogens(cls, v: dict[str, int]) -> dict[str, int]:
        if any(n < 0 for n in v.values()):
            raise ValueError("halogen counts must be >= 0")
        return v

    def to_compound(self) -> Compound:
        alt = self.alternative_name
        fields: dict = {
            "name": self.name,
            "is_small_molecule": True,
            "lipophilicity": [
                ParameterAlternative(name=alt, parameters=[self.lipophilicity.to_parameter(name="Lipophilicity")])
            ],
            "fraction_unbound": [
                ParameterAlternative(
                    name=alt,
                    species="Human",
                    parameters=[self.fraction_unbound.to_parameter(name="Fraction unbound (plasma, reference value)")],
                )
            ],
        }
        if self.binding_partner is not None:
            fields["plasma_protein_binding_partner"] = self.binding_partner
        if self.solubility is not None:
            fields["solubility"] = [
                ParameterAlternative(
                    name=alt,
                    parameters=[
                        self.solubility.to_parameter(name="Solubility at reference pH"),
                        Parameter(name="Reference pH", value=self.solubility_reference_ph),
                    ],
                ),
                *(ParameterAlternative.model_validate({"Name": name, "IsDefault": False, "Parameters": [
                    sol.to_parameter(name="Solubility at reference pH").model_dump(by_alias=True, exclude_none=True),
                    {"Name": "Reference pH", "Value": ph}]}) for name, (sol, ph) in self.solubility_alternatives.items()),
            ]
        if self.solubility_table:
            table = Parameter(name="Solubility table", value=self.solubility_table_value if self.solubility_table_value
                              is not None else self.solubility_table[0][1], unit="mg/l")
            table = table.model_copy(update={"TableFormula": {
                "Name": "Solubility", "XName": "pH", "XDimension": "Dimensionless", "YName": "Solubility",
                "YDimension": "Concentration (mass)", "YUnit": "mg/l", "UseDerivedValues": False,
                "Points": [{"X": x, "Y": y, "RestartSolver": False} for x, y in self.solubility_table]}})
            fields["solubility"] = [ParameterAlternative(name=alt, parameters=[table])]
        if self.intestinal_permeability is not None:
            fields["intestinal_permeability"] = [
                ParameterAlternative(
                    name=alt,
                    parameters=[
                        self.intestinal_permeability.to_parameter(name="Specific intestinal permeability (transcellular)")
                    ],
                ),
                *(ParameterAlternative.model_validate({"Name": name, "IsDefault": False, "Parameters": [
                    perm.to_parameter(name="Specific intestinal permeability (transcellular)").model_dump(
                        by_alias=True, exclude_none=True)]})
                  for name, perm in self.intestinal_permeability_alternatives.items()),
            ]
        if self.permeability is not None:
            fields["permeability"] = [
                ParameterAlternative(name=alt, parameters=[self.permeability.to_parameter(name="Permeability")])
            ]
        if self.pka:
            fields["pka_types"] = [
                PkaType(type=p.type, pka=p.pka, **({"value_origin": p.origin} if p.origin else {})) for p in self.pka
            ]
        if self.processes:
            fields["processes"] = [p.to_process() for p in self.processes]
        fields["calculation_methods"] = list(self.calculation_methods)
        fields["parameters"] = [
            *(Parameter(name=h, value=float(n)) for h, n in sorted(self.halogens.items()) if n),
            self.molecular_weight.to_parameter(name="Molecular weight"),
        ]
        return Compound(**fields)

    def selected_alternatives(self) -> list[AlternativeSelection]:
        # Only permeability groups carried explicit selections in the reference snapshot.
        selections = []
        if self.permeability is not None:
            selections.append(AlternativeSelection(alternative_name=self.alternative_name, group_name="COMPOUND_PERMEABILITY"))
        if self.intestinal_permeability is not None:
            selections.append(
                AlternativeSelection(alternative_name=self.alternative_name, group_name="COMPOUND_INTESTINAL_PERMEABILITY")
            )
        return selections


# --- subject --------------------------------------------------------------------------------------


_ENZYME_LOCALIZATION = "Intracellular, BloodCellsIntracellular, VascEndosome"


class ExpressionSpec(Spec):
    """An enzyme, transporter or other-protein expression profile. Real OSP transporter profiles carry no
    Localization (PK-Sim supplies it for the named transporter), so it is emitted only when set; enzymes keep
    the standard intracellular localization by default.

    ``harvested`` is a profile copied verbatim from an OSP reference snapshot (`pbpk_domain.expression`): its
    per-organ relative expressions, half-lives, transport directions and ontogeny. Without those every organ's
    relative expression is zero and the protein's processes do nothing, so a campaign build always uses a
    harvested profile; the bare form (molecule and reference concentration only) exists for builder tests."""

    type: Literal["Enzyme", "Transporter", "OtherProtein"] = "Enzyme"
    molecule: str = Field(min_length=1)
    species: str = "Human"
    category: str = "Healthy"
    localization: str | None = None
    transporter_type: str | None = None  # e.g. "Efflux", "Influx"; Transporter profiles only
    ontogeny: str | None = None
    reference_concentration: Measured | None = None
    harvested: dict | None = None

    @field_validator("reference_concentration")
    @classmethod
    def _unit(cls, v: Measured | None) -> Measured | None:
        return _check(v, unit="µmol/l", label="Reference concentration")

    @property
    def reference(self) -> str:
        return expression_profile_reference(self.molecule, self.species, self.category)

    def to_profile(self) -> ExpressionProfile:
        if self.harvested is not None:
            return self._harvested_profile()
        fields: dict = {"type": self.type, "species": self.species, "molecule": self.molecule, "category": self.category}
        if self.reference_concentration is not None:
            fields["parameters"] = [
                self.reference_concentration.to_parameter(path=f"{self.molecule}|Reference concentration")
            ]
        localization = self.localization if self.localization is not None else (_ENZYME_LOCALIZATION if self.type == "Enzyme" else None)
        if localization is not None:
            fields["localization"] = localization
        if self.transporter_type is not None:
            fields["TransportType"] = self.transporter_type  # the snapshot key, as in the engine catalog
        if self.ontogeny:
            fields["ontogeny"] = {"Name": self.ontogeny}
        return ExpressionProfile(**fields)

    def _harvested_profile(self) -> ExpressionProfile:
        """The harvested profile under this spec's identity (category, species), with a reference-concentration
        override applied when one is set."""
        doc = dict(self.harvested or {})
        doc.update({"Type": self.type, "Species": self.species, "Molecule": self.molecule, "Category": self.category})
        if self.reference_concentration is not None:
            path = f"{self.molecule}|Reference concentration"
            override = self.reference_concentration.to_parameter(path=path).model_dump(by_alias=True, exclude_none=True)
            params = [p for p in doc.get("Parameters", []) if p.get("Path") != path]
            doc["Parameters"] = [override, *params]
        return ExpressionProfile.model_validate(doc)


class SubjectSpec(Spec):
    name: str = Field(min_length=1)
    species: str = "Human"
    population: str = "European_ICRP_2002"
    gender: Literal["MALE", "FEMALE"]
    age_years: float = Field(gt=0)
    seed: int = Field(ge=-(2**31), le=2**31 - 1)  # signed 32-bit, as published seeds are (Alprazolam: -2063117500)
    expression: list[ExpressionSpec] = Field(default_factory=list)
    calculation_methods: tuple[str, ...] = DEFAULT_INDIVIDUAL_CALCULATION_METHODS
    # Physiology overrides addressed by full path (e.g. "Organism|Liver|EHC continuous fraction"), as the OSP
    # reference individuals carry them in `Individuals[].Parameters`; paths are copied from a reference, never made up.
    parameters: dict[str, Measured] = Field(default_factory=dict)
    weight_kg: float | None = Field(default=None, gt=0)  # study mean; PK-Sim derives it from the population when absent
    height_cm: float | None = Field(default=None, gt=0)
    # The subject carries a published model's own individual for its study: its `parameters` are that individual's
    # complete set (the CPF's indiv.* records do not apply) and `expression_overrides` its profile values, applied
    # over the harvested library profiles under this subject's own profile category.
    own_physiology: bool = False
    expression_overrides: dict[str, Measured] = Field(default_factory=dict)
    # that individual's own published profiles, verbatim (molecule -> profile document), used instead of the shared ones
    expression_documents: dict[str, dict] = Field(default_factory=dict)

    def to_individual(self) -> Individual:
        fields: dict = {
            "name": self.name,
            "seed": self.seed,
            "origin_data": OriginData(
                calculation_methods=list(self.calculation_methods),
                species=self.species,
                population=self.population,
                gender=self.gender,
                age=Quantity(value=self.age_years, unit="year(s)"),
                weight=Quantity(value=self.weight_kg, unit="kg") if self.weight_kg is not None else None,
                height=Quantity(value=self.height_cm, unit="cm") if self.height_cm is not None else None,
            ),
        }
        if self.parameters:
            fields["parameters"] = [m.to_parameter(path=path) for path, m in self.parameters.items()]
        if self.expression:
            fields["expression_profiles"] = [e.reference for e in self.expression]
        return Individual(**fields)


# --- administration -------------------------------------------------------------------------------


def _check_end_time(v: Measured | None) -> Measured | None:
    if v is None:
        return None
    if _nfc(v.unit) not in ("day(s)", "h"):
        raise ValueError(f"End time must be in 'day(s)' or 'h' (got {v.unit!r})")
    return v


class DosePhaseSpec(Spec):
    """One phase of a regimen: ``repetitions`` doses of ``dose``, ``interval_h`` apart, the first at ``start_h``."""

    start_h: float = Field(ge=0)
    dose: Measured
    repetitions: int = Field(default=1, gt=0)
    interval_h: float = Field(default=0.0, ge=0)
    # an IV phase infused over its own time (OSP Alprazolam Kroboth 1988: 1 mg over 2 min, then 0.576 mg over 8 h);
    # None: the protocol's
    infusion_time_min: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _interval(self):
        if self.repetitions > 1 and self.interval_h <= 0:
            raise ValueError("a phase of several doses needs the interval between them")
        return self


class _MultipleDoseMixin(Spec):
    """Adds regular multiple-dose scheduling: a PK-Sim DosingInterval (e.g. ``DI_24`` once daily,
    ``DI_12_12`` twice daily) plus the End time up to which dosing repeats. ``Single`` is one dose."""

    dosing_interval: str = "Single"
    end_time: Measured | None = None
    # Any other regular regimen, as the OSP reference protocols write it (Dapagliflozin/Rifampicin "MD" protocols):
    # one schema item repeated `repetitions` times, `repetition_interval_h` apart (Schemas[].Parameters
    # NumberOfRepetitions / TimeBetweenRepetitions). Used when no named DosingInterval fits (e.g. every 6 h).
    repetitions: int | None = Field(default=None, gt=0)
    repetition_interval_h: float | None = Field(default=None, gt=0)
    # A regimen of consecutive phases whose doses differ (a loading dose, then maintenance), as the OSP Voriconazole
    # protocols write it ("Purkin et al. 2003 B": 6 mg/kg twice 12 h apart, then 3 mg/kg every 12 h from 24 h): one
    # schema per phase (Start time, NumberOfRepetitions, TimeBetweenRepetitions) with one item at the phase's dose.
    phases: tuple[DosePhaseSpec, ...] = ()

    @model_validator(mode="after")
    def _phases(self):
        if not self.phases:
            return self
        if self.repetitions is not None or self.dosing_interval != "Single":
            raise ValueError("a phased regimen is written by its phases, not repetitions or a DosingInterval")
        units = {_nfc(ph.dose.unit) for ph in self.phases} | {_nfc(self.dose.unit)}  # type: ignore[attr-defined]  # every subclass has a dose
        if len(units) != 1:
            raise ValueError(f"every phase is dosed in the protocol's dose unit (got {sorted(units)})")
        starts = [ph.start_h for ph in self.phases]
        if starts != sorted(starts):
            raise ValueError("phases are given in time order")
        return self

    @field_validator("end_time")
    @classmethod
    def _end(cls, v: Measured | None) -> Measured | None:
        return _check_end_time(v)

    @model_validator(mode="after")
    def _md_needs_end_time(self):
        if self.dosing_interval != "Single" and self.end_time is None:
            raise ValueError(f"multiple-dose protocol (DosingInterval {self.dosing_interval!r}) needs an end_time")
        return self

    def _dosing_parameters(self) -> list[Parameter]:
        return [self.end_time.to_parameter(name="End time")] if self.end_time is not None else []

    def _schema_protocol(self, application_type: str, item_parameters: list[Parameter],
                         formulation_key: str | None) -> Protocol | None:
        if self.phases:
            schemas = []
            for i, phase in enumerate(self.phases):
                parameters = [phase.dose.to_parameter(name="InputDose") if q.name == "InputDose"
                              else Parameter(name="Infusion time", value=phase.infusion_time_min, unit="min")
                              if q.name == "Infusion time" and phase.infusion_time_min is not None else q
                              for q in item_parameters]
                item = SchemaItem(name="Schema Item 1", application_type=application_type, formulation_key=formulation_key,
                                  parameters=[Parameter(name="Start time", value=0.0, unit="h"), *parameters])
                schemas.append(Schema(name=f"Schema {i + 1}", schema_items=[item], parameters=[
                    Parameter(name="Start time", value=phase.start_h, unit="h"),
                    Parameter(name="NumberOfRepetitions", value=float(phase.repetitions)),
                    Parameter(name="TimeBetweenRepetitions", value=phase.interval_h, unit="h"),
                ]))
            return Protocol(name=self.name, dosing_interval="Single", schemas=schemas, time_unit="h")
        if self.repetitions is None:
            return None
        item = SchemaItem(name="Schema Item 1", application_type=application_type, formulation_key=formulation_key,
                          parameters=[Parameter(name="Start time", value=0.0, unit="h"), *item_parameters])
        schema = Schema(name="Schema 1", schema_items=[item], parameters=[
            Parameter(name="Start time", value=getattr(self, "start_time_h", 0.0), unit="h"),
            Parameter(name="NumberOfRepetitions", value=float(self.repetitions)),
            Parameter(name="TimeBetweenRepetitions", value=self.repetition_interval_h, unit="h"),
        ])
        return Protocol(name=self.name, dosing_interval="Single", schemas=[schema], time_unit="h")


class OralProtocolSpec(_MultipleDoseMixin):
    kind: Literal["oral"] = "oral"
    name: str = Field(min_length=1)
    dose: Measured
    start_time_h: float = Field(default=0.0, ge=0)
    water_volume_ml_per_kg: float = Field(default=3.5, ge=0)
    # A product given as several particle-size bins at once (OSP Ketoconazole "PD_tablet_3Bins"): one schema item per
    # bin formulation (FormulationKey = its name) with its mass fraction of the dose, the water on the first item only.
    bins: tuple[tuple[str, float], ...] = ()

    @model_validator(mode="after")
    def _bins(self):
        if self.bins and abs(sum(f for _n, f in self.bins) - 1.0) > 1e-6:
            raise ValueError("the bins' mass fractions must sum to 1")
        if self.bins and self.phases:
            raise ValueError("a binned product given in phases is not placed yet (no published protocol does it)")
        return self

    def _bin_protocol(self) -> Protocol:
        items = [SchemaItem(name=f"Schema Item {i + 1}", application_type="Oral", formulation_key=name, parameters=[
                     Parameter(name="Start time", value=0.0, unit="h"),
                     self.dose.model_copy(update={"value": self.dose.value * fraction}).to_parameter(name="InputDose"),
                     Parameter(name="Volume of water/body weight", value=self.water_volume_ml_per_kg if i == 0 else 0.0,
                               unit="ml/kg")])
                 for i, (name, fraction) in enumerate(self.bins)]
        # a single dose is one repetition 0 h apart, as the published single-dose bin protocols write it
        repetitions, interval = (self.repetitions, self.repetition_interval_h) if self.repetitions else (1, 0.0)
        schema = Schema(name="Schema 1", schema_items=items, parameters=[
            Parameter(name="Start time", value=self.start_time_h, unit="h"),
            Parameter(name="NumberOfRepetitions", value=float(repetitions)),
            Parameter(name="TimeBetweenRepetitions", value=interval, unit="h"),
        ])
        return Protocol(name=self.name, dosing_interval="Single", schemas=[schema], time_unit="h")

    @field_validator("dose")
    @classmethod
    def _dose(cls, v: Measured) -> Measured:
        # "mg" or "mg/kg" (per body weight), the InputDose units of the OSP reference protocols (Midazolam).
        return _check(v, unit="mg/kg" if _nfc(v.unit) == "mg/kg" else "mg", label="InputDose")

    def to_protocol(self) -> Protocol:
        if self.bins:
            if self.dosing_interval != "Single":
                raise ValueError("a binned product is dosed by schema repetitions, not a named DosingInterval")
            return self._bin_protocol()
        schema = self._schema_protocol("Oral", [
            self.dose.to_parameter(name="InputDose"),
            Parameter(name="Volume of water/body weight", value=self.water_volume_ml_per_kg, unit="ml/kg"),
        ], "Formulation")
        if schema is not None:
            return schema
        return Protocol(
            name=self.name,
            application_type="Oral",
            dosing_interval=self.dosing_interval,
            parameters=[
                Parameter(name="Start time", value=self.start_time_h, unit="h"),
                self.dose.to_parameter(name="InputDose"),
                Parameter(name="Volume of water/body weight", value=self.water_volume_ml_per_kg, unit="ml/kg"),
                *self._dosing_parameters(),
            ],
        )


class IntravenousProtocolSpec(_MultipleDoseMixin):
    kind: Literal["intravenous"] = "intravenous"
    name: str = Field(min_length=1)
    dose: Measured
    start_time_h: float = Field(default=0.0, ge=0)
    infusion_time_min: float = Field(gt=0)

    @field_validator("dose")
    @classmethod
    def _dose(cls, v: Measured) -> Measured:
        # "mg" or "mg/kg" (per body weight), the InputDose units of the OSP reference protocols (Midazolam).
        return _check(v, unit="mg/kg" if _nfc(v.unit) == "mg/kg" else "mg", label="InputDose")

    def to_protocol(self) -> Protocol:
        schema = self._schema_protocol("Intravenous", [
            self.dose.to_parameter(name="InputDose"),
            Parameter(name="Infusion time", value=self.infusion_time_min, unit="min"),
        ], None)
        if schema is not None:
            return schema
        return Protocol(
            name=self.name,
            application_type="Intravenous",
            dosing_interval=self.dosing_interval,
            parameters=[
                Parameter(name="Start time", value=self.start_time_h, unit="h"),
                self.dose.to_parameter(name="InputDose"),
                Parameter(name="Infusion time", value=self.infusion_time_min, unit="min"),
                *self._dosing_parameters(),
            ],
        )


class IntravenousBolusProtocolSpec(_MultipleDoseMixin):
    """An IV bolus: PK-Sim ``IntravenousBolus`` with a start time and InputDose, no infusion time (harvested from the
    OSP Alfentanil, Midazolam, Digoxin, Metformin and Verapamil protocols, simple and schema form)."""

    kind: Literal["intravenous_bolus"] = "intravenous_bolus"
    name: str = Field(min_length=1)
    dose: Measured
    start_time_h: float = Field(default=0.0, ge=0)

    @field_validator("dose")
    @classmethod
    def _dose(cls, v: Measured) -> Measured:
        return _check(v, unit="mg/kg" if _nfc(v.unit) == "mg/kg" else "mg", label="InputDose")

    def to_protocol(self) -> Protocol:
        schema = self._schema_protocol("IntravenousBolus", [self.dose.to_parameter(name="InputDose")], None)
        if schema is not None:
            return schema
        return Protocol(
            name=self.name,
            application_type="IntravenousBolus",
            dosing_interval=self.dosing_interval,
            parameters=[
                Parameter(name="Start time", value=self.start_time_h, unit="h"),
                self.dose.to_parameter(name="InputDose"),
                *self._dosing_parameters(),
            ],
        )


ProtocolSpec = Annotated[OralProtocolSpec | IntravenousProtocolSpec | IntravenousBolusProtocolSpec, Field(discriminator="kind")]


class DissolvedFormulationSpec(Spec):
    kind: Literal["dissolved"] = "dissolved"
    name: str = Field(min_length=1)

    def to_formulation(self) -> Formulation:
        return Formulation(name=self.name, formulation_type="Formulation_Dissolved")


class WeibullFormulationSpec(Spec):
    kind: Literal["weibull"] = "weibull"
    name: str = Field(min_length=1)
    dissolution_time_50_min: float = Field(gt=0)
    lag_time_min: float = Field(default=0.0, ge=0)
    shape: float = Field(gt=0)
    use_as_suspension: bool = True

    def to_formulation(self) -> Formulation:
        return Formulation(
            name=self.name,
            formulation_type="Formulation_Tablet_Weibull",
            parameters=[
                Parameter(name="Dissolution time (50% dissolved)", value=self.dissolution_time_50_min, unit="min"),
                Parameter(name="Lag time", value=self.lag_time_min, unit="min"),
                Parameter(name="Dissolution shape", value=self.shape),
                Parameter(name="Use as suspension", value=1.0 if self.use_as_suspension else 0.0),
            ],
        )


class ParticleFormulationSpec(Spec):
    """Particle dissolution (PK-Sim ``Formulation_Particles``, Noyes-Whitney) with a monodisperse size distribution,
    as the OSP Ketoconazole model writes it: the unstirred water layer thickness, the distribution type (0:
    monodisperse, the only one placed here) and the mean particle radius. Dissolution is limited by the compound's
    solubility, so a "solution" given as 8 nm particles (the model's PD_solution) still respects it."""

    kind: Literal["particles"] = "particles"
    name: str = Field(min_length=1)
    thickness: Measured
    radius: Measured
    distribution_type: float = 0.0

    @field_validator("thickness")
    @classmethod
    def _thickness(cls, v: Measured) -> Measured:
        return _check(v, unit="mm", label="Thickness (unstirred water layer)")

    @field_validator("radius")
    @classmethod
    def _radius(cls, v: Measured) -> Measured:
        return _check(v, unit="µm", label="Particle radius (mean)")

    @field_validator("distribution_type")
    @classmethod
    def _monodisperse(cls, v: float) -> float:
        if v != 0.0:
            raise ValueError("only the monodisperse particle size distribution (type 0) is placed; its other parameters "
                             "are not harvested yet")
        return v

    def to_formulation(self) -> Formulation:
        return Formulation(
            name=self.name,
            formulation_type="Formulation_Particles",
            parameters=[
                self.thickness.to_parameter(name="Thickness (unstirred water layer)"),
                Parameter(name="Type of particle size distribution", value=self.distribution_type),
                self.radius.to_parameter(name="Particle radius (mean)"),
            ],
        )


FormulationSpec = Annotated[DissolvedFormulationSpec | WeibullFormulationSpec | ParticleFormulationSpec,
                            Field(discriminator="kind")]


class MealEventSpec(Spec):
    """A meal event that applies a PK-Sim meal template (e.g. "Meal: High-fat breakfast (Human)")."""

    name: str = Field(min_length=1)
    template: str = Field(min_length=1)

    def to_event(self) -> Event:
        return Event(name=self.name, template=self.template)


class CoCompoundSpec(Spec):
    """Another compound of a model system in the simulation: dosed with its own protocol (an enantiomer, a co-dosed
    parent) or, with no protocol, only formed (a metabolite)."""

    name: str = Field(min_length=1)
    protocol: str | None = None
    formulation: str | None = None
    formulation_bins: tuple[str, ...] = ()


class SimulationSpec(Spec):
    name: str = Field(min_length=1)
    subject: str
    compound: str
    protocol: str
    formulation: str | None = None
    # a binned product: every bin formulation, each selected under its own key (Key = Name, as published)
    formulation_bins: tuple[str, ...] = ()
    end_time_h: float = Field(gt=0)
    resolution_pts_per_h: float = Field(default=10.0, gt=0)
    model: str = "4Comp"
    additional_outputs: tuple[str, ...] = ()
    events: tuple[str, ...] = ()  # meal-event names applied in this simulation, each starting at t=0
    event_start_time_h: float = Field(default=0.0, ge=0)
    # Simulation-level values addressed by full path (e.g. "<Compound>|logP (veg.oil/water)"), as the OSP reference
    # simulations carry them in `Simulations[].Parameters`.
    parameters: dict[str, Measured] = Field(default_factory=dict)
    co_compounds: tuple[CoCompoundSpec, ...] = ()
    # the main compound's alternative per group (GroupName -> AlternativeName) where it is not the default
    alternatives: dict[str, str] = Field(default_factory=dict)
    observer_sets: tuple[str, ...] = ()  # ObserverSets (added with SnapshotBuilder.add_observer_set) this computes


# --- builder --------------------------------------------------------------------------------------


# The first hours after the (first) dose are sampled densely: an IV peak and the distribution phase change within
# minutes (the Dapagliflozin IV microdose is sampled from 5 min), and the evaluation reads the curve at the observed
# sampling times. Two output intervals, as the OSP reference simulations use (e.g. 0-2 h dense, then coarser).
EARLY_WINDOW_H = 2.0
EARLY_RESOLUTION_PTS_PER_H = 60.0


def _output_schema(spec: SimulationSpec) -> list[OutputInterval]:
    def interval(start: float, end: float, resolution: float) -> OutputInterval:
        return OutputInterval(parameters=[
            Parameter(name="Start time", value=start, unit="h"),
            Parameter(name="End time", value=end, unit="h"),
            Parameter(name="Resolution", value=resolution, unit="pts/h"),
        ])

    if spec.end_time_h <= EARLY_WINDOW_H:
        return [interval(0.0, spec.end_time_h, max(spec.resolution_pts_per_h, EARLY_RESOLUTION_PTS_PER_H))]
    return [interval(0.0, EARLY_WINDOW_H, max(spec.resolution_pts_per_h, EARLY_RESOLUTION_PTS_PER_H)),
            interval(EARLY_WINDOW_H, spec.end_time_h, spec.resolution_pts_per_h)]


class SnapshotBuilder:
    def __init__(self, snapshot_version: int = SNAPSHOT_VERSION_PKSIM_12):
        if snapshot_version not in (SNAPSHOT_VERSION_PKSIM_12, SNAPSHOT_VERSION_PKSIM_13):
            raise ValueError(f"unsupported snapshot version {snapshot_version}")
        self._version = snapshot_version
        self._compounds: dict[str, CompoundSpec] = {}
        self._subjects: dict[str, SubjectSpec] = {}
        self._protocols: dict[str, OralProtocolSpec | IntravenousProtocolSpec] = {}
        self._formulations: dict[str, DissolvedFormulationSpec | WeibullFormulationSpec | ParticleFormulationSpec] = {}
        self._events: dict[str, MealEventSpec] = {}
        self._simulations: dict[str, SimulationSpec] = {}
        self._observer_sets: dict[str, dict] = {}

    @staticmethod
    def _register(registry: dict, kind: str, spec) -> None:
        if spec.name in registry:
            raise ValueError(f"duplicate {kind} name {spec.name!r}")
        registry[spec.name] = spec

    def add_compound(self, spec: CompoundSpec) -> SnapshotBuilder:
        self._register(self._compounds, "compound", spec)
        return self

    def add_subject(self, spec: SubjectSpec) -> SnapshotBuilder:
        self._register(self._subjects, "subject", spec)
        return self

    def add_protocol(self, spec: OralProtocolSpec | IntravenousProtocolSpec) -> SnapshotBuilder:
        self._register(self._protocols, "protocol", spec)
        return self

    def add_formulation(self, spec: DissolvedFormulationSpec | WeibullFormulationSpec | ParticleFormulationSpec) -> SnapshotBuilder:
        self._register(self._formulations, "formulation", spec)
        return self

    def add_event(self, spec: MealEventSpec) -> SnapshotBuilder:
        self._register(self._events, "event", spec)
        return self

    def add_observer_set(self, document: dict) -> SnapshotBuilder:
        """A published ObserverSets entry, copied verbatim (never composed here)."""
        self._observer_sets[document["Name"]] = document
        return self

    def add_simulation(self, spec: SimulationSpec) -> SnapshotBuilder:
        self._register(self._simulations, "simulation", spec)
        return self

    @classmethod
    def from_cpf(cls, cpf, subjects, scenarios, *, snapshot_version=None):
        """Regenerate a snapshot from a CPF, subjects and scenarios (see `pbpk_domain.cpf.build`)."""
        from pbpk_domain.cpf.build import build_from_cpf

        return build_from_cpf(cpf, subjects, scenarios, snapshot_version=snapshot_version)

    def build(self) -> Snapshot:
        issues: list[Issue] = []

        profiles: dict[str, ExpressionProfile] = {}
        for subject in self._subjects.values():
            for expression in subject.expression:
                profile = expression.to_profile()
                existing = profiles.setdefault(profile.reference_name, profile)
                if existing != profile:
                    issues.append(
                        Issue(
                            "CONFLICTING_EXPRESSION_PROFILE",
                            f"Subjects[{subject.name}]",
                            f"{profile.reference_name!r} is defined differently by another subject",
                        )
                    )

        fields: dict = {"version": self._version}
        if self._version >= SNAPSHOT_VERSION_PKSIM_13:
            fields["application_name"] = "PK-Sim"
        sections = {
            "expression_profiles": list(profiles.values()),
            "individuals": [s.to_individual() for s in self._subjects.values()],
            "compounds": [c.to_compound() for c in self._compounds.values()],
            "formulations": [f.to_formulation() for f in self._formulations.values()],
            "protocols": [p.to_protocol() for p in self._protocols.values()],
            "events": [e.to_event() for e in self._events.values()],
            "simulations": [self._simulation(s) for s in self._simulations.values()],
            "observer_sets": list(self._observer_sets.values()),
        }
        fields.update({key: items for key, items in sections.items() if items})

        snapshot = Snapshot(**fields)
        issues.extend(validate_references(snapshot))
        if issues:
            raise SnapshotBuildError(issues)
        return snapshot

    def _simulation_compound(self, name: str, protocol: str | None, formulation: str | None,
                             bins: tuple[str, ...] = (), chosen: dict[str, str] | None = None,
                             ) -> tuple[SimulationCompound, list[dict]]:
        compound_fields: dict = {"name": name}
        compound = self._compounds.get(name)
        interactions: list[dict] = []
        if compound is not None:
            mapped = compound.selected_molecules
            interactions = [
                {**sel, "MoleculeName": mapped[sel["Name"]]} if sel["Name"] in mapped else sel for p in compound.processes
                if (sel := interaction_selection_for(p.to_process(), name)) is not None
            ]
            compound_fields["calculation_methods"] = list(compound.calculation_methods)
            alternatives = compound.selected_alternatives()
            for group, alternative in (chosen or {}).items():
                if alternative not in compound.alternatives_of(group):
                    raise ValueError(f"{name}: no {group} alternative {alternative!r} "
                                     f"(has {', '.join(compound.alternatives_of(group))})")
                alternatives = [a for a in alternatives if a.group_name != group]
                alternatives.append(AlternativeSelection(alternative_name=alternative, group_name=group))
            if alternatives:
                compound_fields["alternatives"] = alternatives
            selections = [
                sel.model_copy(update={"molecule_name": mapped[sel.name]}) if sel.molecule_name and sel.name in mapped else sel
                for p in compound.processes if (sel := process_selection_for(p.to_process())) is not None
            ]
            if selections:
                compound_fields["processes"] = selections
        if protocol is not None:
            protocol_fields: dict = {"name": protocol}
            if bins:
                protocol_fields["formulations"] = [FormulationSelection(name=b, key=b) for b in bins]
            elif formulation is not None:
                protocol_fields["formulations"] = [FormulationSelection(name=formulation, key="Formulation")]
            compound_fields["protocol"] = ProtocolSelection(**protocol_fields)
        return SimulationCompound(**compound_fields), interactions

    def _simulation(self, spec: SimulationSpec) -> Simulation:
        entries = [self._simulation_compound(spec.compound, spec.protocol, spec.formulation, spec.formulation_bins,
                                             spec.alternatives),
                   *(self._simulation_compound(c.name, c.protocol, c.formulation, c.formulation_bins) for c in spec.co_compounds)]
        interactions = [sel for _entry, sels in entries for sel in sels]
        plasma = [PLASMA_OUTPUT_PATH.format(compound=name) for name in (spec.compound, *(c.name for c in spec.co_compounds))]

        sim_fields: dict = {
            "name": spec.name,
            "model": spec.model,
            "solver": {},
            "output_schema": _output_schema(spec),
            "output_selections": list(dict.fromkeys([*plasma, *spec.additional_outputs])),
            "individual": spec.subject,
            "compounds": [entry for entry, _sels in entries],
        }
        if spec.observer_sets:
            sim_fields["observer_sets"] = [{"Name": name} for name in spec.observer_sets]
        if interactions:
            sim_fields["interactions"] = interactions
        if spec.parameters:
            sim_fields["parameters"] = [m.to_parameter(path=path) for path, m in spec.parameters.items()]
        if spec.events:
            sim_fields["events"] = [
                {"Name": name, "StartTime": {"Value": spec.event_start_time_h, "Unit": "h"}} for name in spec.events
            ]
        return Simulation(**sim_fields)
