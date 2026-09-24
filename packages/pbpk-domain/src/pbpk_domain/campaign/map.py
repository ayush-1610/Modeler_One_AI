"""The Modeling Analysis Plan (MAP), generated from the standard (MS-01 §9, task T-16).

The MAP is the signed, versioned plan a campaign runs against: objective and context of use, the CPF
parameter table with source and fit policy, the study catalogue with class/score/assignment and the split
rationale, the per-stage plan (permitted fit candidates, branches, budgets, max rounds), the acceptance
tier and criteria, the diagnostics ruleset version, the engine image and software versions, seeds, and
what triggers escalation. It is generated deterministically from the CPF, studies, split, question and
tier; signing freezes a version, and any change after signing produces a new version whose predecessor's
campaigns are invalidated.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict

from pbpk_domain.acceptance import load_acceptance_ruleset
from pbpk_domain.campaign.split import (
    DEFAULT_DEMOGRAPHICS,
    Assignment,
    DosePhase,
    Meal,
    PublishedIndividual,
    SplitResult,
    StudyClass,
    StudyRecord,
)
from pbpk_domain.cpf.models import CPF
from pbpk_domain.m15 import Rating
from pbpk_domain.system import ModelSystem

# Per-stage fitting plan (MS-01 §4). Candidate ids use `{enzyme}`/`{name}` where the concrete parameter is
# resolved from the CPF at build time. Branches are discrete method choices, compared not fitted.
STAGE_PLAN: dict[str, dict] = {
    "S0": {"fit_candidates": (), "branches": (), "max_rounds": 1},
    "S1": {
        "fit_candidates": ("elim.hepatic.{enzyme}.clspec", "elim.hepatic.{enzyme}.kcat", "transp.{name}.kcat",
                           "phys.logp", "elim.renal.gfr_fraction", "elim.renal.ts_clspec", "perm.cellular", "bind.fu"),
        "branches": ("dist.partition_method", "dist.permeability_method"),
        "max_rounds": 4,
    },
    "S2": {
        "fit_candidates": ("perm.intestinal", "phys.solubility.ref", "elim.ehc_fraction",
                           "elim.hepatic.{enzyme}.km", "elim.hepatic.{enzyme}.vmax", "elim.hepatic.{enzyme}.clspec",
                           "elim.hepatic.{enzyme}.kcat", "transp.{name}.kcat"),
        "branches": (),
        "max_rounds": 4,
    },
    "S3": {"fit_candidates": ("form.{name}.weibull.t50", "form.{name}.weibull.shape", "food.fed_solubility_factor"),
           "branches": (), "max_rounds": 2},
    "S4": {"fit_candidates": (), "branches": (), "max_rounds": 1},
    "S5": {"fit_candidates": (), "branches": (), "max_rounds": 1},
    "S6": {"fit_candidates": (), "branches": (), "max_rounds": 1},
    "S7": {"fit_candidates": (), "branches": (), "max_rounds": 1},
}

# Campaign-budget split (MS-01 §7).
BUDGET_FRACTION = {"S0": 0.01, "S1": 0.25, "S2": 0.25, "S3": 0.12, "S4": 0.05, "S5": 0.05, "S6": 0.20, "S7": 0.07}

# Stage kinds (MS-01 §4). S1–S3 are round loops that may fit; S4/S5 simulate the final CPF once and judge it,
# never fitting — a validation failure escalates rather than refits.
FIT_STAGES = ("S1", "S2", "S3")
VALIDATION_STAGES = ("S4", "S5")

# Which stage each internal study class trains. Every study that trains a stage is re-simulated in S4.
_CLASS_STAGE = {
    StudyClass.IV_SD: "S1",
    StudyClass.PO_SOL_FASTED: "S2",
    StudyClass.PO_IR_FASTED: "S2",
    StudyClass.PO_FED: "S3",
}
# External studies S5 simulates: fasted, fed, multiple dose, other dose, other formulation (MS-01 §4 S5).
# DDI / PGX / SPECIAL / PRECLINICAL studies validate their S6 application instead (MS-01 §3.3 rule 4).
_S5_CLASSES = frozenset({
    StudyClass.IV_SD, StudyClass.PO_SOL_FASTED, StudyClass.PO_IR_FASTED, StudyClass.PO_FED,
    StudyClass.PO_MD, StudyClass.PO_MR, StudyClass.PO_OTHER,
})
# Why a stage with no scenario is skipped. Each is a documented limitation, carried into the stage's findings.
_SKIP_REASON = {
    "S1": "No internal IV study: S1 has nothing to fit; distribution and clearance are identified from oral data "
          "at S2 (MS-01 decision tree §6.1).",
    "S2": "No internal fasted oral single-dose study: S2 has nothing to fit; oral exposure is predicted, not "
          "fitted (MS-01 decision tree §6.2).",
    "S3": "No internal fed or formulation study: S3 has nothing to fit; fed exposure, where relevant, is predicted "
          "and judged in S5 (MS-01 decision tree §6.7).",
    "S4": "No study was fitted, so there is nothing to validate internally.",
    "S5": "No external study: external validation is not achievable — a documented limitation (MS-01 §3.3 rule 2).",
    "S6": "No internal study to predict from: sensitivity and uncertainty need the validated simulations of S4.",
}

ESCALATION_TRIGGERS = (
    "maximum rounds reached without passing the gate",
    "stage time budget exhausted",
    "a fitted parameter sits at its bound",
    "two fitted parameters correlate > 0.95 after fixing one",
    "CV > 50% on a parameter the question of interest depends on",
    "no permitted diagnostic action left to try",
    "multiple-dose accumulation mismatch (possible time-dependent clearance)",
    "external validation fails (decision tree §6.6)",
)


class MapStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"


class MapParameter(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    value: float | str | None
    unit: str | None
    status: str
    source: str | None
    fittable_stages: tuple[str, ...] = ()


class MapStudy(BaseModel):
    model_config = ConfigDict(frozen=True)
    study_id: str
    study_class: str
    score: float
    assignment: str


class MapStagePlan(BaseModel):
    model_config = ConfigDict(frozen=True)
    stage: str
    budget_seconds: int
    fit_candidates: tuple[str, ...]
    branches: tuple[str, ...]
    max_rounds: int


class MapScenario(BaseModel):
    """One internal study's simulation plan — what `build_round_snapshot` turns into a simulation.

    Carries the studied individual's demographics (population, sex, age) so the round build can construct the
    PK-Sim individual; ``infusion_time_min`` is the IV infusion duration (required for an IV scenario)."""
    model_config = ConfigDict(frozen=True)
    study_id: str
    stage: str
    route: str
    dose_mg: float
    dose_per_kg: bool = False  # dose_mg per kg body weight (PK-Sim InputDose in mg/kg)
    infusion_time_min: float | None
    formulation: str
    food_state: str
    meal_template: str | None
    meals: tuple[Meal, ...] = ()  # every meal as given (StudyRecord.meals)
    n_subjects: int
    population: str
    sex: str
    age_years: float
    weight_kg: float | None = None
    height_cm: float | None = None
    study_class: str = ""
    formulation_name: str | None = None  # the CPF formulation a solid oral study used (form.{name}.*)
    # Multiple-dose regimen (a dose every `dosing_interval_h`, `n_doses` times); None for a single dose.
    dosing_interval_h: float | None = None
    n_doses: int | None = None
    # A regimen whose doses differ (loading, then maintenance), phase by phase (StudyRecord.dose_phases).
    dose_phases: tuple[DosePhase, ...] = ()
    # The study's last sampling time: the simulation must cover it, or the prediction is scored on a shorter
    # window than the observation.
    sim_end_time_h: float | None = None
    # A reference model's own individual for this study (physiology and expression that differ from the main one).
    published_individual: PublishedIndividual | None = None
    # A model system's analyte the study measures and the product it administers (None: the single compound).
    analyte: str | None = None
    product: str | None = None
    # the analyte's simulation output (a compound's plasma or a published sum observer) and whether the study enters
    # the acceptance gate and the fit — phase 1: only the fitted parent's plasma (owner decision 3, 2026-09-24)
    analyte_output: str | None = None
    gated: bool = True
    # The VPC population's age range (the study's own, else the MS-01 default ±10 y around the mean; `vpc.age_range`).
    vpc_age_min: float | None = None
    vpc_age_max: float | None = None


class MapAcceptance(BaseModel):
    model_config = ConfigDict(frozen=True)
    tier: str
    ruleset: str
    criteria: dict


class MapSignature(BaseModel):
    model_config = ConfigDict(frozen=True)
    printed_name: str
    meaning: str
    signed_at: datetime
    signature_id: str | None = None
    content_sha256: str = ""


class MapDocument(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: int = 1
    compound: str
    objective: str
    context_of_use: str
    food_effect_in_question: bool
    model_risk: Rating
    cpf_parameters: tuple[MapParameter, ...]
    studies: tuple[MapStudy, ...]
    split_rationale: tuple[str, ...]
    split_limitations: tuple[str, ...]
    stage_plan: tuple[MapStagePlan, ...]
    scenarios: tuple[MapScenario, ...]
    diagnostics_ruleset_version: str
    acceptance: MapAcceptance
    engine_image_digest: str
    software_versions: dict[str, str]
    seeds: dict[str, int]
    escalation_triggers: tuple[str, ...] = ESCALATION_TRIGGERS
    status: MapStatus = MapStatus.DRAFT
    signature: MapSignature | None = None
    supersedes_sha256: str | None = None
    # a model system's content hash (pbpk_domain.system.ModelSystem.sha256) when the campaign simulates one
    model_system_sha256: str | None = None

    # --- identity & lifecycle --------------------------------------------------------------------

    def content_sha256(self) -> str:
        """Hash of the plan's substance (everything except its status, signature and this hash)."""
        content = self.model_dump(mode="json", exclude={"status", "signature"})
        return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def sign(self, *, printed_name: str, meaning: str = "Approved", signature_id: str | None = None,
             when: datetime | None = None) -> MapDocument:
        """Return the signed MAP. The signature binds this version's content hash."""
        if self.status is MapStatus.SIGNED:
            raise ValueError("MAP is already signed; revise it to create a new version")
        signature = MapSignature(
            printed_name=printed_name, meaning=meaning, signed_at=when or datetime.now(UTC),
            signature_id=signature_id, content_sha256=self.content_sha256(),
        )
        return self.model_copy(update={"status": MapStatus.SIGNED, "signature": signature})

    def revise(self, **changes) -> MapDocument:
        """Return a new DRAFT version with `changes` applied. If this version was signed, the new version
        supersedes it and campaigns bound to this version's hash must be invalidated by the caller."""
        supersedes = self.content_sha256() if self.status is MapStatus.SIGNED else self.supersedes_sha256
        return self.model_copy(update={
            **changes, "version": self.version + 1, "status": MapStatus.DRAFT,
            "signature": None, "supersedes_sha256": supersedes,
        })

    @property
    def invalidates_prior_campaigns(self) -> bool:
        return self.supersedes_sha256 is not None


def _acceptance(model_risk: Rating) -> MapAcceptance:
    ruleset = load_acceptance_ruleset()
    tier = ruleset["tiers"][str(model_risk)]
    return MapAcceptance(tier=str(model_risk), ruleset=f"{ruleset['id']}@{ruleset['version']}", criteria=tier)


def _training_stage(study: StudyRecord, study_class: StudyClass, cpf: CPF, have_solution: bool) -> str | None:
    """The stage an internal study trains. An immediate-release solid trains S2 when it dissolves rapidly (its CPF
    formulation is Dissolved) or when there is no solution study to train S2 (MS-01 §6.3, the tablet is then the S2
    reference with its in-vitro Weibull fixed); otherwise its release is handled in S3 and S2 uses the solution
    studies only (MS-01 §4 S2)."""
    stage = _CLASS_STAGE.get(study_class)
    if study_class is StudyClass.PO_IR_FASTED and have_solution:
        from pbpk_domain.cpf.formulations import DISSOLVED, FormulationError, cpf_formulation, resolve_formulation_name

        try:
            name, _ = resolve_formulation_name(cpf, study.formulation_name)
            if cpf_formulation(cpf, name).type != DISSOLVED:
                return "S3"
        except FormulationError:
            return "S3"  # release not defined: it belongs to the formulation stage, which will say why it cannot build
    return stage


def _scenario_stages(assignment: Assignment, study_class: StudyClass, train: str | None = None) -> tuple[str, ...]:
    """The stages a study is simulated in: an internal study trains its stage and is re-simulated in S4; an
    external study of a core class is judged in S5. Anything else (flagged classes, supportive studies) has no
    S0–S5 scenario."""
    if assignment is Assignment.INTERNAL:
        train = train or _CLASS_STAGE.get(study_class)
        return (train, "S4") if train else ()
    if assignment is Assignment.EXTERNAL and study_class in _S5_CLASSES:
        return ("S5",)
    return ()


def _scenarios(studies: list[StudyRecord], split: SplitResult, *, meal_template: str, cpf: CPF | None = None,
               sampling_end_h: Mapping[str, float] | None = None) -> tuple[MapScenario, ...]:
    by_id = {s.study_id: s for s in studies}
    ends = sampling_end_h or {}
    have_solution = any(r.assignment is Assignment.INTERNAL and r.study_class is StudyClass.PO_SOL_FASTED for r in split.splits)
    scenarios = []
    for row in split.splits:
        study = by_id[row.study_id]
        demo = study.demographics or DEFAULT_DEMOGRAPHICS
        multiple = study.is_multiple_dose
        train = _training_stage(study, row.study_class, cpf, have_solution) if cpf is not None else None
        from pbpk_domain.campaign.vpc import age_range

        vpc_ages = age_range(demo.age_years, demo.age_min, demo.age_max)
        for stage in _scenario_stages(row.assignment, row.study_class, train):
            scenarios.append(MapScenario(
                study_id=study.study_id, stage=stage, route=study.route.value, dose_mg=study.dose_mg,
                dose_per_kg=study.dose_per_kg,
                infusion_time_min=study.infusion_time_min,
                formulation=study.formulation.value, food_state=study.food_state.value,
                meal_template=meal_template if study.food_state.value == "fed" else None,
                meals=study.meals, n_subjects=study.n,
                population=demo.population, sex=demo.sex.value, age_years=demo.age_years,
                weight_kg=demo.weight_kg, height_cm=demo.height_cm, study_class=row.study_class.value,
                formulation_name=study.formulation_name,
                dosing_interval_h=study.dosing_interval_h if multiple else None,
                n_doses=study.n_doses if multiple else None,
                dose_phases=study.dose_phases,
                sim_end_time_h=ends.get(study.study_id),
                published_individual=study.published_individual,
                analyte=study.analyte, product=study.product,
                vpc_age_min=vpc_ages[0], vpc_age_max=vpc_ages[1],
            ))
    return tuple(scenarios)


@dataclass(frozen=True)
class StageCoverage:
    """What one stage simulates under a MAP, and why it is skipped when there is nothing to simulate."""
    stage: str
    kind: str                           # "fit" | "validate" | "readiness"
    studies: tuple[str, ...]
    skip_reason: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)


def stage_coverage(map_doc: MapDocument, stage: str) -> StageCoverage:
    """The studies `stage` simulates under this MAP; a stage with none is skipped with its documented reason.

    For S5 the notes also name every external study that is *not* judged there — flagged studies validate their
    S6 application (rule 4) — so the record shows each study's fate, not just the ones that ran."""
    kind = ("validate" if stage in VALIDATION_STAGES else "fit" if stage in FIT_STAGES
            else "predict" if stage == "S6" else "report" if stage == "S7" else "readiness")
    # S6 predicts from the internal studies' simulations (the final CPF); S7 packages whatever the campaign made.
    source = "S4" if stage == "S6" else stage
    studies = tuple(dict.fromkeys(s.study_id for s in map_doc.scenarios if s.stage == source))
    notes: list[str] = []
    if stage == "S5":
        judged = set(studies)
        for row in map_doc.studies:
            if row.study_id in judged:
                continue
            if row.assignment == Assignment.EXTERNAL.value:
                notes.append(f"{row.study_id} ({row.study_class}) validates the planned {row.study_class} application "
                             "in S6, not S5 (MS-01 §3.3 rule 4)")
            elif row.assignment == Assignment.SUPPORTIVE.value:
                notes.append(f"{row.study_id} ({row.study_class}) is supportive context only; not simulated")
    skip = _SKIP_REASON.get(stage) if kind in ("fit", "validate", "predict") and not studies else None
    if skip is None and kind in ("fit", "validate") and studies and map_doc.model_system_sha256:
        gated_studies = {s.study_id for s in map_doc.scenarios if s.stage == source and s.gated}
        if not gated_studies:
            # a model system whose studies here all measure a metabolite or a sum (Verapamil's IV data are racemic):
            # reported beside the gate in phase 1, so nothing judges or fits this stage (owner decision 3)
            skip = (f"no study of this stage measures the fitted parent's plasma: {', '.join(studies)} measure other "
                    "analytes of the model system, reported but not gated or fitted in phase 1")
    return StageCoverage(stage=stage, kind=kind, studies=studies, skip_reason=skip, notes=tuple(notes))


def _system_scenarios(scenarios: tuple[MapScenario, ...], system: ModelSystem | None, fitted: str) -> tuple[MapScenario, ...]:
    """Each scenario of a model system names its analyte's output path and whether it is gated (fitted parent only)."""
    if system is None:
        return scenarios
    from pbpk_domain.system import gated

    return tuple(s.model_copy(update={
        "analyte_output": system.analytes[s.analyte].output_path if s.analyte in system.analytes else None,
        "gated": gated(system, s.analyte, fitted)}) for s in scenarios)


def generate_map(
    *,
    compound: str,
    cpf: CPF,
    studies: list[StudyRecord],
    split: SplitResult,
    objective: str,
    context_of_use: str,
    food_effect_in_question: bool,
    model_risk: Rating,
    engine_image_digest: str,
    software_versions: dict[str, str],
    seed: int = 1,
    campaign_budget_seconds: int = 3600,
    diagnostics_ruleset_version: str | None = None,
    meal_template: str = "Meal: High-fat breakfast (Human)",
    sampling_end_h: Mapping[str, float] | None = None,
    system: ModelSystem | None = None,
) -> MapDocument:
    """Produce the MAP (version 1, DRAFT) from the standard and the campaign's inputs (MS-01 §9).

    ``sampling_end_h`` maps a study to its last observed time (hours) so each simulation covers the whole
    sampled window."""
    if diagnostics_ruleset_version is None:
        from pbpk_domain.diagnostics import diag_ruleset_version

        diagnostics_ruleset_version = diag_ruleset_version()
    parameters = tuple(
        MapParameter(
            id=p.id, value=p.value, unit=p.unit, status=p.status.value,
            source=p.provenance.source_type if p.provenance else None,
            fittable_stages=p.fit_policy.stage if p.fit_policy else (),
        )
        for p in cpf.parameters
    )
    study_rows = tuple(
        MapStudy(study_id=s.study_id, study_class=s.study_class.value, score=round(s.score, 3), assignment=s.assignment.value)
        for s in split.splits
    )
    stage_plan = tuple(
        MapStagePlan(
            stage=stage, budget_seconds=round(campaign_budget_seconds * BUDGET_FRACTION[stage]),
            fit_candidates=plan["fit_candidates"], branches=plan["branches"], max_rounds=plan["max_rounds"],
        )
        for stage, plan in STAGE_PLAN.items()
    )
    return MapDocument(
        compound=compound,
        objective=objective,
        context_of_use=context_of_use,
        food_effect_in_question=food_effect_in_question,
        model_risk=model_risk,
        cpf_parameters=parameters,
        studies=study_rows,
        split_rationale=split.rationale,
        split_limitations=split.limitations,
        stage_plan=stage_plan,
        scenarios=_system_scenarios(_scenarios(studies, split, meal_template=meal_template, cpf=cpf,
                                               sampling_end_h=sampling_end_h), system, cpf.compound),
        model_system_sha256=system.sha256 if system is not None else None,
        diagnostics_ruleset_version=diagnostics_ruleset_version,
        acceptance=_acceptance(model_risk),
        engine_image_digest=engine_image_digest,
        software_versions=dict(software_versions),
        seeds={"campaign": seed},
    )
