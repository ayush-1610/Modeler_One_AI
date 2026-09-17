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
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict

from pbpk_domain.acceptance import load_acceptance_ruleset
from pbpk_domain.campaign.split import (
    DEFAULT_DEMOGRAPHICS,
    Assignment,
    SplitResult,
    StudyClass,
    StudyRecord,
)
from pbpk_domain.cpf.models import CPF
from pbpk_domain.m15 import Rating

# Per-stage fitting plan (MS-01 §4). Candidate ids use `{enzyme}`/`{name}` where the concrete parameter is
# resolved from the CPF at build time. Branches are discrete method choices, compared not fitted.
STAGE_PLAN: dict[str, dict] = {
    "S0": {"fit_candidates": (), "branches": (), "max_rounds": 1},
    "S1": {
        "fit_candidates": ("elim.hepatic.{enzyme}.clspec", "phys.logp", "elim.renal.gfr_fraction", "perm.cellular", "bind.fu"),
        "branches": ("dist.partition_method", "dist.permeability_method"),
        "max_rounds": 4,
    },
    "S2": {
        "fit_candidates": ("perm.intestinal", "phys.solubility.ref", "elim.ehc_fraction",
                           "elim.hepatic.{enzyme}.km", "elim.hepatic.{enzyme}.vmax", "elim.hepatic.{enzyme}.clspec"),
        "branches": (),
        "max_rounds": 4,
    },
    "S3": {"fit_candidates": ("form.{name}.weibull.t50", "form.{name}.weibull.shape", "food.fed_solubility_factor"),
           "branches": (), "max_rounds": 2},
    "S4": {"fit_candidates": (), "branches": (), "max_rounds": 1},
    "S5": {"fit_candidates": (), "branches": (), "max_rounds": 1},
}

# Campaign-budget split (MS-01 §7). S0–S5 are run by the campaign workflow; S6/S7 are separate tasks.
BUDGET_FRACTION = {"S0": 0.01, "S1": 0.25, "S2": 0.25, "S3": 0.12, "S4": 0.05, "S5": 0.05}

# Which stage each internal study class trains.
_CLASS_STAGE = {
    StudyClass.IV_SD: "S1",
    StudyClass.PO_SOL_FASTED: "S2",
    StudyClass.PO_IR_FASTED: "S2",
    StudyClass.PO_FED: "S3",
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
    infusion_time_min: float | None
    formulation: str
    food_state: str
    meal_template: str | None
    n_subjects: int
    population: str
    sex: str
    age_years: float
    weight_kg: float | None = None
    height_cm: float | None = None


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


def _scenarios(studies: list[StudyRecord], split: SplitResult, *, meal_template: str) -> tuple[MapScenario, ...]:
    by_id = {s.study_id: s for s in studies}
    scenarios = []
    for row in split.splits:
        if row.assignment is not Assignment.INTERNAL:
            continue
        stage = _CLASS_STAGE.get(row.study_class)
        if stage is None:
            continue
        study = by_id[row.study_id]
        demo = study.demographics or DEFAULT_DEMOGRAPHICS
        scenarios.append(MapScenario(
            study_id=study.study_id, stage=stage, route=study.route.value, dose_mg=study.dose_mg,
            infusion_time_min=study.infusion_time_min,
            formulation=study.formulation.value, food_state=study.food_state.value,
            meal_template=meal_template if study.food_state.value == "fed" else None, n_subjects=study.n,
            population=demo.population, sex=demo.sex.value, age_years=demo.age_years,
            weight_kg=demo.weight_kg, height_cm=demo.height_cm,
        ))
    return tuple(scenarios)


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
) -> MapDocument:
    """Produce the MAP (version 1, DRAFT) from the standard and the campaign's inputs (MS-01 §9)."""
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
        scenarios=_scenarios(studies, split, meal_template=meal_template),
        diagnostics_ruleset_version=diagnostics_ruleset_version,
        acceptance=_acceptance(model_risk),
        engine_image_digest=engine_image_digest,
        software_versions=dict(software_versions),
        seeds={"campaign": seed},
    )
