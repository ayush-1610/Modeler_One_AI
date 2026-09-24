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
    Simulation,
    SimulationCompound,
    Snapshot,
    ValueOrigin,
    expression_profile_reference,
)
from pbpk_domain.snapshot.validation import process_selection_for, validate_references

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
        return _check(v, unit="µmol/l/min", label="Vmax")

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
        return _check(v, unit="µmol/l/min", label="Vmax")

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


ProcessSpec = Annotated[
    FirstOrderMetabolism
    | MichaelisMentenMetabolism
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
    intestinal_permeability: Measured | None = None
    permeability: Measured | None = None
    pka: list[PkaSpec] = Field(default_factory=list, max_length=3)  # PK-Sim supports up to 3 pKa values [VERIFY]
    halogens: dict[Literal["F", "Cl", "Br", "I"], int] = Field(default_factory=dict)
    binding_partner: Literal["Albumin", "Glycoprotein", "Unknown"] = "Albumin"
    processes: list[ProcessSpec] = Field(default_factory=list)
    calculation_methods: tuple[str, ...] = DEFAULT_COMPOUND_CALCULATION_METHODS
    alternative_name: str = "Measured"

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
            "plasma_protein_binding_partner": self.binding_partner,
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
        if self.solubility is not None:
            fields["solubility"] = [
                ParameterAlternative(
                    name=alt,
                    parameters=[
                        self.solubility.to_parameter(name="Solubility at reference pH"),
                        Parameter(name="Reference pH", value=self.solubility_reference_ph),
                    ],
                )
            ]
        if self.intestinal_permeability is not None:
            fields["intestinal_permeability"] = [
                ParameterAlternative(
                    name=alt,
                    parameters=[
                        self.intestinal_permeability.to_parameter(name="Specific intestinal permeability (transcellular)")
                    ],
                )
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
    seed: int = Field(ge=0, le=2**31 - 1)
    expression: list[ExpressionSpec] = Field(default_factory=list)
    calculation_methods: tuple[str, ...] = DEFAULT_INDIVIDUAL_CALCULATION_METHODS
    # Physiology overrides addressed by full path (e.g. "Organism|Liver|EHC continuous fraction"), as the OSP
    # reference individuals carry them in `Individuals[].Parameters`; paths are copied from a reference, never made up.
    parameters: dict[str, Measured] = Field(default_factory=dict)

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


class _MultipleDoseMixin(Spec):
    """Adds regular multiple-dose scheduling: a PK-Sim DosingInterval (e.g. ``DI_24`` once daily,
    ``DI_12_12`` twice daily) plus the End time up to which dosing repeats. ``Single`` is one dose."""

    dosing_interval: str = "Single"
    end_time: Measured | None = None

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


class OralProtocolSpec(_MultipleDoseMixin):
    kind: Literal["oral"] = "oral"
    name: str = Field(min_length=1)
    dose: Measured
    start_time_h: float = Field(default=0.0, ge=0)
    water_volume_ml_per_kg: float = Field(default=3.5, ge=0)

    @field_validator("dose")
    @classmethod
    def _dose(cls, v: Measured) -> Measured:
        return _check(v, unit="mg", label="InputDose")

    def to_protocol(self) -> Protocol:
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
        return _check(v, unit="mg", label="InputDose")

    def to_protocol(self) -> Protocol:
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


ProtocolSpec = Annotated[OralProtocolSpec | IntravenousProtocolSpec, Field(discriminator="kind")]


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


FormulationSpec = Annotated[DissolvedFormulationSpec | WeibullFormulationSpec, Field(discriminator="kind")]


class MealEventSpec(Spec):
    """A meal event that applies a PK-Sim meal template (e.g. "Meal: High-fat breakfast (Human)")."""

    name: str = Field(min_length=1)
    template: str = Field(min_length=1)

    def to_event(self) -> Event:
        return Event(name=self.name, template=self.template)


class SimulationSpec(Spec):
    name: str = Field(min_length=1)
    subject: str
    compound: str
    protocol: str
    formulation: str | None = None
    end_time_h: float = Field(gt=0)
    resolution_pts_per_h: float = Field(default=10.0, gt=0)
    model: str = "4Comp"
    additional_outputs: tuple[str, ...] = ()
    events: tuple[str, ...] = ()  # meal-event names applied in this simulation, each starting at t=0
    event_start_time_h: float = Field(default=0.0, ge=0)


# --- builder --------------------------------------------------------------------------------------


class SnapshotBuilder:
    def __init__(self, snapshot_version: int = SNAPSHOT_VERSION_PKSIM_12):
        if snapshot_version not in (SNAPSHOT_VERSION_PKSIM_12, SNAPSHOT_VERSION_PKSIM_13):
            raise ValueError(f"unsupported snapshot version {snapshot_version}")
        self._version = snapshot_version
        self._compounds: dict[str, CompoundSpec] = {}
        self._subjects: dict[str, SubjectSpec] = {}
        self._protocols: dict[str, OralProtocolSpec | IntravenousProtocolSpec] = {}
        self._formulations: dict[str, DissolvedFormulationSpec | WeibullFormulationSpec] = {}
        self._events: dict[str, MealEventSpec] = {}
        self._simulations: dict[str, SimulationSpec] = {}

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

    def add_formulation(self, spec: DissolvedFormulationSpec | WeibullFormulationSpec) -> SnapshotBuilder:
        self._register(self._formulations, "formulation", spec)
        return self

    def add_event(self, spec: MealEventSpec) -> SnapshotBuilder:
        self._register(self._events, "event", spec)
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
        }
        fields.update({key: items for key, items in sections.items() if items})

        snapshot = Snapshot(**fields)
        issues.extend(validate_references(snapshot))
        if issues:
            raise SnapshotBuildError(issues)
        return snapshot

    def _simulation(self, spec: SimulationSpec) -> Simulation:
        compound_fields: dict = {"name": spec.compound}
        compound = self._compounds.get(spec.compound)
        if compound is not None:
            compound_fields["calculation_methods"] = list(compound.calculation_methods)
            alternatives = compound.selected_alternatives()
            if alternatives:
                compound_fields["alternatives"] = alternatives
            selections = [
                sel for p in compound.processes if (sel := process_selection_for(p.to_process())) is not None
            ]
            if selections:
                compound_fields["processes"] = selections
        protocol_fields: dict = {"name": spec.protocol}
        if spec.formulation is not None:
            protocol_fields["formulations"] = [FormulationSelection(name=spec.formulation, key="Formulation")]
        compound_fields["protocol"] = ProtocolSelection(**protocol_fields)

        sim_fields: dict = {
            "name": spec.name,
            "model": spec.model,
            "solver": {},
            "output_schema": [
                OutputInterval(
                    parameters=[
                        Parameter(name="Start time", value=0.0, unit="h"),
                        Parameter(name="End time", value=spec.end_time_h, unit="h"),
                        Parameter(name="Resolution", value=spec.resolution_pts_per_h, unit="pts/h"),
                    ]
                )
            ],
            "output_selections": [PLASMA_OUTPUT_PATH.format(compound=spec.compound), *spec.additional_outputs],
            "individual": spec.subject,
            "compounds": [SimulationCompound(**compound_fields)],
        }
        if spec.events:
            sim_fields["events"] = [
                {"Name": name, "StartTime": {"Value": spec.event_start_time_h, "Unit": "h"}} for name in spec.events
            ]
        return Simulation(**sim_fields)
