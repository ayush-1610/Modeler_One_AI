"""Study classification and the internal/external data split (MS-01 §3).

Runs once, before any fitting, and its result is frozen in the MAP. Deterministic: the same studies and
question always produce the same classes, scores, assignments and rationale sentences. Nothing here runs
the engine; it decides which studies train the model (INTERNAL), which judge it (EXTERNAL) and which only
support an application (SUPPORTIVE), and records, in plain sentences, why — including every limitation.

The rules are MS-01 §3.2 (classification, information score) and §3.3 (the split algorithm). Where the
data cannot satisfy a rule (a class with a single study, a missing external category) the limitation is
recorded rather than silently worked around, because the MAP and the regulator need to see it.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StudyClass(str, Enum):
    IV_SD = "IV-SD"
    PO_SOL_FASTED = "PO-SOL-FASTED"
    PO_IR_FASTED = "PO-IR-FASTED"
    PO_FED = "PO-FED"
    PO_MD = "PO-MD"
    PO_MR = "PO-MR"
    PO_OTHER = "PO-OTHER"
    DDI = "DDI"
    PGX = "PGX"
    SPECIAL = "SPECIAL"
    PRECLINICAL = "PRECLINICAL"


# Classes that MS-01 never fits in S1–S3 (rule 4): they validate an application (S6) or are supportive.
FLAGGED_CLASSES = (StudyClass.DDI, StudyClass.PGX, StudyClass.SPECIAL, StudyClass.PRECLINICAL)
FASTED_ORAL_SD_CLASSES = (StudyClass.PO_SOL_FASTED, StudyClass.PO_IR_FASTED)


class Assignment(str, Enum):
    INTERNAL = "INTERNAL"      # used to fit the model
    EXTERNAL = "EXTERNAL"      # used to validate the model (not fitted)
    SUPPORTIVE = "SUPPORTIVE"  # flagged study with no planned application; context only


class Statistic(str, Enum):
    INDIVIDUAL = "individual"
    MEAN_SD = "mean_sd"
    MEAN = "mean"


class Route(str, Enum):
    IV_BOLUS = "iv_bolus"
    IV_INFUSION = "iv_infusion"
    ORAL = "oral"
    OTHER = "other"


class FoodState(str, Enum):
    FASTED = "fasted"
    FED = "fed"


class FormulationKind(str, Enum):
    SOLUTION = "solution"
    SUSPENSION = "suspension"
    IR_TABLET = "ir_tablet"
    IR_CAPSULE = "ir_capsule"
    MR = "mr"
    OTHER = "other"


class SpecialPopulation(str, Enum):
    PEDIATRIC = "pediatric"
    HEPATIC_IMPAIRMENT = "hepatic_impairment"
    RENAL_IMPAIRMENT = "renal_impairment"
    PREGNANCY = "pregnancy"
    ELDERLY = "elderly"


class Sex(str, Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"


class Demographics(BaseModel):
    """The representative individual a study is simulated with (MS-01 §2.3).

    Age, sex and population (ethnicity) define a typical PK-Sim individual; PK-Sim derives weight, height
    and organ sizes from the population physiology for that age and sex. A study mean ``weight_kg`` /
    ``height_cm`` is written into the individual's ``OriginData`` (``Weight`` in kg, ``Height`` in cm, keys harvested
    from the OSP Midazolam model's Korean individual) and PK-Sim scales the physiology to it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    population: str = "European_ICRP_2002"
    sex: Sex = Sex.MALE
    age_years: float = Field(default=30.0, gt=0)
    age_min: float | None = Field(default=None, ge=0)  # the study's reported age range, for its VPC population
    age_max: float | None = Field(default=None, gt=0)
    weight_kg: float | None = Field(default=None, gt=0)  # study mean, written to the individual's OriginData
    height_cm: float | None = Field(default=None, gt=0)


class PathValue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    value: float
    unit: str | None = None


class Meal(BaseModel):
    """One meal of a study (StudyRecord.meals)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    time_h: float                       # after the first dose; negative: before it
    template: str = Field(min_length=1)  # the PK-Sim meal template, e.g. "Meal: Standard (Human)"
    name: str = Field(min_length=1)     # as the published model names it
    parameters: dict[str, PathValue] = Field(default_factory=dict)  # values changed from the template


class DosePhase(BaseModel):
    """One phase of a regimen whose doses differ: ``n_doses`` doses of ``dose_mg`` (mg, or mg/kg for a per-kg study),
    ``interval_h`` apart, the first ``start_h`` after the regimen starts. A loading dose then maintenance is two
    phases (OSP Voriconazole, Saari 2006: 400 mg twice 12 h apart, then 200 mg every 12 h from 24 h)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    start_h: float = Field(ge=0)
    dose_mg: float = Field(gt=0)
    n_doses: int = Field(default=1, gt=0)
    interval_h: float | None = Field(default=None, gt=0)
    infusion_time_min: float | None = Field(default=None, gt=0)  # an IV phase's own infusion time; None: the study's

    @model_validator(mode="after")
    def _interval(self) -> DosePhase:
        if self.n_doses > 1 and self.interval_h is None:
            raise ValueError("a phase of several doses needs the interval between them")
        return self


class PublishedIndividual(BaseModel):
    """The individual a published model simulates one study in, when it differs from the model's main individual
    (the OSP Rifampicin model's "EHC off" individual for its 7-day study; the Midazolam model's Korean individual,
    CYP3A5 *3/*3, for Yu 2004). ``parameters`` is that individual's complete set of physiology overrides (it replaces
    the CPF's indiv.* records for this study: a value the main individual sets and this one does not is left at the
    PK-Sim default, never invented); ``expression`` holds its profile values that differ from the harvested library.
    Paths and units are copied from the snapshot."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    seed: int | None = Field(default=None, ge=-(2**31), le=2**31 - 1)  # the individual's Seed (organ-volume percentiles)
    parameters: dict[str, PathValue] = Field(default_factory=dict)
    expression: dict[str, PathValue] = Field(default_factory=dict)
    # its expression profiles copied verbatim (molecule -> profile document): localization, transport type, ontogeny
    profiles: dict[str, dict[str, Any]] = Field(default_factory=dict)


# The documented default when a study reports no demographics: the OSP reference 30-year-old European male.
DEFAULT_DEMOGRAPHICS = Demographics()


_ORAL_ROUTES = (Route.ORAL,)
_IV_ROUTES = (Route.IV_BOLUS, Route.IV_INFUSION)
_SOLUTION_FORMS = (FormulationKind.SOLUTION, FormulationKind.SUSPENSION)
_IR_SOLID_FORMS = (FormulationKind.IR_TABLET, FormulationKind.IR_CAPSULE)
_STAT_WEIGHT = {Statistic.INDIVIDUAL: 1.0, Statistic.MEAN_SD: 0.6, Statistic.MEAN: 0.4}


class StudyRecord(BaseModel):
    """A clinical study as it arrives from intake (MS-01 §3.1), reduced to the fields the split needs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    study_id: str = Field(min_length=1)
    reference: str = ""
    species: str = "Human"
    population_type: str = "healthy"  # "healthy" | "patient"
    special_population: SpecialPopulation | None = None
    n: int = Field(gt=0)
    design: str = "SD"  # "SD" | "MD"
    # Multiple-dose regimen, needed to simulate an MD study (a regular schedule: one dose every interval).
    dosing_interval_h: float | None = Field(default=None, gt=0)
    n_doses: int | None = Field(default=None, gt=0)
    # A regimen whose doses differ (loading, then maintenance), phase by phase; it then defines every administration,
    # `dose_mg` is its first dose and `dosing_interval_h` / `n_doses` are unset.
    dose_phases: tuple[DosePhase, ...] = ()
    crossover: bool = False
    route: Route = Route.ORAL
    dose_mg: float = Field(gt=0)
    dose_per_kg: bool = False  # dose_mg is mg per kg body weight (PK-Sim scales it by the individual's weight)
    infusion_time_min: float | None = Field(default=None, gt=0)  # required for an IV infusion; none: an IV bolus
    formulation: FormulationKind = FormulationKind.SOLUTION
    formulation_name: str | None = None  # the CPF formulation (form.{name}.*) a solid oral study used
    food_state: FoodState = FoodState.FASTED
    meal_type: str | None = None
    # every meal as given: h after the first dose (negative: before it), the PK-Sim meal template and its changed
    # values (OSP Midazolam Bornemann 1986: 1 h before / after a high-fat breakfast; OSP Itraconazole: a breakfast with
    # each daily dose and standard meals; Metformin: a 300 kcal standard meal). Empty: a fed study's meal is the MAP's
    # template at the dose; a fasted one has none.
    meals: tuple[Meal, ...] = ()
    # process selections (compound -> names) the study's simulation leaves out: a phenotype the model represents by
    # switching a pathway off (OSP Omeprazole CYP2C19 poor metabolisers: "CYP2C19-2C19 Linear Fit" not selected)
    inactive_processes: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    # simulation-level model values (full paths, `sim.*` / `sim[route].*` records) the study's simulation leaves at
    # PK-Sim's default: OSP Alfentanil's Kharasch 2012 oral simulation keeps the default gut-wall permeabilities that
    # its other oral simulations set to the identified values
    default_simulation_values: tuple[str, ...] = ()
    # solver settings the study's published simulation sets (OSP Dabigatran Härtter 2012: {"RelTol": 1e-09})
    solver: dict[str, float] = Field(default_factory=dict)
    demographics: Demographics | None = None  # the studied individual; DEFAULT_DEMOGRAPHICS when absent
    statistic: Statistic = Statistic.MEAN_SD
    n_timepoints: int = Field(gt=0)
    lloq: float | None = None
    matrices: frozenset[str] = frozenset({"plasma"})
    co_medication: str | None = None
    genotype: str | None = None
    multiple_dose_levels: bool = False  # the study itself reports more than one dose level
    published_individual: PublishedIndividual | None = None  # a reference model's own individual for this study
    # Model systems (several compounds): what the study measures and the product it administers (ModelSystem.analytes /
    # .products). None: the single compound's plasma, dosed as reported.
    analyte: str | None = None
    product: str | None = None

    @model_validator(mode="after")
    def _phases(self) -> StudyRecord:
        if not self.dose_phases:
            return self
        if self.dosing_interval_h is not None or self.n_doses is not None:
            raise ValueError(f"{self.study_id}: a phased regimen replaces dosing_interval_h / n_doses")
        if [p.start_h for p in self.dose_phases] != sorted(p.start_h for p in self.dose_phases):
            raise ValueError(f"{self.study_id}: dose phases are given in time order")
        if self.dose_phases[0].dose_mg != self.dose_mg:
            raise ValueError(f"{self.study_id}: dose_mg is the regimen's first dose")
        if not self.is_multiple_dose:
            raise ValueError(f"{self.study_id}: a phased regimen is a multiple-dose (MD) study")
        return self

    @property
    def is_multiple_dose(self) -> bool:
        return self.design.upper() == "MD"

    @property
    def is_iv(self) -> bool:
        return self.route in _IV_ROUTES

    @property
    def is_oral(self) -> bool:
        return self.route in _ORAL_ROUTES

    @property
    def has_excreta(self) -> bool:
        return bool(self.matrices & {"urine", "feces"})


# --- classification (MS-01 §3.2) -----------------------------------------------------------------


def classify(study: StudyRecord) -> StudyClass:
    """Assign exactly one class. Flagged conditions (non-human, special population, genotype,
    co-medication) take precedence because MS-01 never fits such studies in S1–S3; the remaining
    healthy-adult studies are classed by route, food state, dose design and formulation."""
    if study.species != "Human":
        return StudyClass.PRECLINICAL
    if study.special_population is not None or study.population_type != "healthy":
        return StudyClass.SPECIAL
    if study.genotype:
        return StudyClass.PGX
    if study.co_medication:
        return StudyClass.DDI

    if study.is_iv and not study.is_multiple_dose:
        return StudyClass.IV_SD
    if study.is_oral:
        if study.food_state is FoodState.FED:
            return StudyClass.PO_FED
        if study.is_multiple_dose:
            return StudyClass.PO_MD
        if study.formulation is FormulationKind.MR:
            return StudyClass.PO_MR
        # fasted, single dose, immediate release:
        if study.formulation in _SOLUTION_FORMS:
            return StudyClass.PO_SOL_FASTED
        if study.formulation in _IR_SOLID_FORMS:
            return StudyClass.PO_IR_FASTED
    return StudyClass.PO_OTHER


def information_score(study: StudyRecord) -> float:
    """`n × timepoints × weight`, weight = statistic weight plus 0.3 for urine/feces data and 0.3 for
    a study that spans several dose levels (MS-01 §3.2)."""
    weight = _STAT_WEIGHT[study.statistic]
    if study.has_excreta:
        weight += 0.3
    if study.multiple_dose_levels:
        weight += 0.3
    return study.n * study.n_timepoints * weight


# --- split (MS-01 §3.3) --------------------------------------------------------------------------


class QuestionOfInterest(BaseModel):
    """The parts of the question the split depends on (MS-01 §3.3 rules 4 and 5)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    food_effect: bool = False  # food effect is itself part of the question
    measured_fed_solubility: bool = False  # measured FeSSIF/FaSSIF ratio available -> no fed param fitted
    planned_applications: frozenset[StudyClass] = frozenset()  # flagged classes with a planned S6 application


class StudySplit(BaseModel):
    study_id: str
    study_class: StudyClass
    score: float
    assignment: Assignment


class SplitResult(BaseModel):
    splits: tuple[StudySplit, ...]
    rationale: tuple[str, ...]
    limitations: tuple[str, ...]

    def assignment_of(self, study_id: str) -> Assignment:
        for s in self.splits:
            if s.study_id == study_id:
                return s.assignment
        raise KeyError(study_id)

    def by_assignment(self, assignment: Assignment) -> tuple[str, ...]:
        return tuple(s.study_id for s in self.splits if s.assignment == assignment)


class _Planner:
    """Mutable working state for one split; produces a SplitResult."""

    def __init__(self, studies: Sequence[StudyRecord], question: QuestionOfInterest):
        self.studies = list(studies)
        self.question = question
        self.by_id = {s.study_id: s for s in self.studies}
        self.klass = {s.study_id: classify(s) for s in self.studies}
        self.score = {s.study_id: information_score(s) for s in self.studies}
        self.assignment: dict[str, Assignment] = {}
        self.rationale: list[str] = []
        self.limitations: list[str] = []
        self._by_class: dict[StudyClass, list[str]] = defaultdict(list)
        for s in self.studies:
            self._by_class[self.klass[s.study_id]].append(s.study_id)

    def _ranked(self, ids: Sequence[str]) -> list[str]:
        # highest score first; study_id as a stable tie-breaker so the result is deterministic.
        return sorted(ids, key=lambda i: (-self.score[i], i))

    def _in_class(self, *classes: StudyClass) -> list[str]:
        out: list[str] = []
        for c in classes:
            out.extend(self._by_class.get(c, []))
        return out

    # -- rule 4: flagged classes are never fitted -------------------------------------------------
    def _assign_flagged(self) -> None:
        for cls in FLAGGED_CLASSES:
            ids = self._by_class.get(cls, [])
            if not ids:
                continue
            if cls in self.question.planned_applications:
                for i in ids:
                    self.assignment[i] = Assignment.EXTERNAL
                self.rationale.append(
                    f"{len(ids)} {cls.value} study(ies) are external validation for the planned {cls.value} application (S6)."
                )
            else:
                for i in ids:
                    self.assignment[i] = Assignment.SUPPORTIVE
                self.rationale.append(
                    f"{len(ids)} {cls.value} study(ies) have no planned application and are kept as supportive context."
                )

    # -- rule 1/2: S1 IV -------------------------------------------------------------------------
    def _assign_s1(self) -> None:
        iv = self._ranked(self._by_class.get(StudyClass.IV_SD, []))
        if not iv:
            self.limitations.append(
                "No IV-SD study: distribution and clearance are identified from oral data at S2 (decision tree §6.1); "
                "volume of distribution and absolute clearance are confounded with bioavailability."
            )
            return
        best = iv[0]
        self.assignment[best] = Assignment.INTERNAL
        self.rationale.append(f"S1 (IV): {best} is the highest-scoring IV-SD study and trains distribution and elimination.")
        if len(iv) == 1:
            self.limitations.append("Only one IV-SD study: external validation of the IV model is not achievable (documented limitation).")

    # -- rule 1/2: S2 oral fasted, covering the lowest and highest dose --------------------------
    def _assign_s2(self) -> None:
        fasted = self._in_class(*FASTED_ORAL_SD_CLASSES)
        if not fasted:
            self.limitations.append(
                "No fasted oral single-dose study: oral absorption cannot be identified (decision tree §6.1/§6.3); "
                "S2 is skipped and oral exposure is predicted, not fitted."
            )
            return
        # Dose levels are compared in one unit: absolute doses when there are any, else per-kg doses.
        fasted = [i for i in fasted if not self.by_id[i].dose_per_kg] or fasted
        doses = sorted({self.by_id[i].dose_mg for i in fasted})
        # highest-scoring study at the lowest dose and at the highest dose (one study if a single dose level)
        picks: list[str] = []
        for target in {doses[0], doses[-1]}:
            at_dose = self._ranked([i for i in fasted if self.by_id[i].dose_mg == target])
            if at_dose:
                picks.append(at_dose[0])
        picks = list(dict.fromkeys(picks))  # dedupe, preserve order
        for i in picks:
            self.assignment[i] = Assignment.INTERNAL
        if len(doses) >= 2:
            self.rationale.append(
                f"S2 (oral fasted): {', '.join(picks)} train absorption across the lowest ({doses[0]:g} mg) and highest "
                f"({doses[-1]:g} mg) fasted single doses."
            )
        else:
            self.rationale.append(
                f"S2 (oral fasted): {picks[0]} trains absorption at the only available fasted single dose ({doses[0]:g} mg)."
            )
            self.limitations.append(
                "Fasted oral data cover a single dose level: dose-dependent absorption cannot be checked internally."
            )
        if len(fasted) == 1:
            self.limitations.append("Only one fasted oral SD study: external validation of oral absorption is not achievable (documented limitation).")

    # -- rule 5: fed-data decision ----------------------------------------------------------------
    def _assign_fed(self) -> None:
        fed = self._ranked(self._by_class.get(StudyClass.PO_FED, []))
        if not fed:
            if not self.question.food_effect and not self.question.measured_fed_solubility:
                self.limitations.append(
                    "A fed parameter would need fitting but no fed study is available (decision tree §6.7): "
                    "fed exposure is predicted from the meal model with unverified fed solubility."
                )
            return
        if self.question.food_effect:
            for i in fed:
                self.assignment.setdefault(i, Assignment.EXTERNAL)
            self.rationale.append(
                "Food effect is the question of interest: no fed parameter is fitted and all fed studies are external; "
                "fed exposure is predicted mechanistically from the meal model and measured fed solubility (rule 5)."
            )
            return
        if self.question.measured_fed_solubility:
            for i in fed:
                self.assignment.setdefault(i, Assignment.EXTERNAL)
            self.rationale.append("Measured fed solubility is available: no fed parameter is fitted and all fed studies are external (rule 5).")
            return
        # a fed parameter must be fitted: one fed study internal, the rest external
        best = fed[0]
        self.assignment[best] = Assignment.INTERNAL
        self.rationale.append(f"S3 (fed): {best} trains the fed-state solubility factor (no measured fed solubility; rule 5).")
        for i in fed[1:]:
            self.assignment.setdefault(i, Assignment.EXTERNAL)
        if len(fed) == 1:
            self.limitations.append("Only one fed study and it is used for fitting: fed external validation is not achievable (documented limitation).")

    # -- rule 3: everything else external, then guarantee external coverage -----------------------
    def _assign_remaining_external(self) -> None:
        for s in self.studies:
            self.assignment.setdefault(s.study_id, Assignment.EXTERNAL)

    def _external_ids(self) -> list[str]:
        return [i for i, a in self.assignment.items() if a == Assignment.EXTERNAL]

    def _rebalance_external_coverage(self) -> None:
        """Rule 3: whenever a category exists in the data but no EXTERNAL study covers it, move the
        lowest-scoring INTERNAL study of that category to EXTERNAL if its class holds ≥2 internal studies."""
        categories = (
            ("fasted oral", lambda s: s.is_oral and s.food_state is FoodState.FASTED),
            ("fed", lambda s: s.is_oral and s.food_state is FoodState.FED),
            ("multiple-dose", lambda s: s.is_multiple_dose),
        )
        for label, predicate in categories:
            exists = [s for s in self.studies if predicate(s)]
            if len(exists) < 2:
                # A category with a single study cannot be both fitted and externally validated; any such
                # limitation is recorded where that study is assigned, not here.
                continue
            if any(predicate(self.by_id[i]) for i in self._external_ids()):
                continue
            internal_ids = [s.study_id for s in exists if self.assignment.get(s.study_id) == Assignment.INTERNAL]
            by_class_counts: dict[StudyClass, list[str]] = defaultdict(list)
            for i in internal_ids:
                by_class_counts[self.klass[i]].append(i)
            movable = [i for i in internal_ids if len(by_class_counts[self.klass[i]]) >= 2]
            if not movable:
                self.limitations.append(f"No external {label} study is available and none can be freed for validation (documented limitation).")
                continue
            move = self._ranked(movable)[-1]  # lowest-scoring
            self.assignment[move] = Assignment.EXTERNAL
            self.rationale.append(f"Moved {move} from internal to external so the {label} category has external validation (rule 3).")

    def run(self) -> SplitResult:
        self._assign_flagged()
        self._assign_s1()
        self._assign_s2()
        self._assign_fed()
        self._assign_remaining_external()
        self._rebalance_external_coverage()
        splits = tuple(
            StudySplit(study_id=s.study_id, study_class=self.klass[s.study_id], score=self.score[s.study_id], assignment=self.assignment[s.study_id])
            for s in self.studies
        )
        return SplitResult(splits=splits, rationale=tuple(self.rationale), limitations=tuple(self.limitations))


def split_studies(studies: Sequence[StudyRecord], question: QuestionOfInterest | None = None) -> SplitResult:
    """Classify and split a study set into INTERNAL/EXTERNAL/SUPPORTIVE with rationale and limitations (MS-01 §3.3)."""
    return _Planner(studies, question or QuestionOfInterest()).run()
