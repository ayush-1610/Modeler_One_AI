"""P5 · the model plan (plan §11, review layer L3; T-50): who trains, who validates, what is fitted, and why.

The **default** is computed by code exactly as the MAP is generated today: the MS-01 §3.3 split (`split_studies`), the
stage each internal study trains (`training_stages`, the MAP's own rule), the stage plan, fit candidates and budgets
(`generate_map`). Agent **A5** drafts a rationale for every assignment and may propose departures, each with a reason;
proposals wait for a person (the diff). A person's change is **userLocked**: a later default recomputation or agent pass
never overwrites it. Every change is checked by the **live validator** (MS-01 rules); the plan can be signed only with
no error and every warning acknowledged with a reason. On signature the MAP is generated deterministically from the
plan: its assignments become the split, its fit choices the CPF's fit policies, its changes and reasons go into the
MAP's rationale and limitations. With no change, the MAP equals `generate_map` on the default split.

A study's **role** on the D3 canvas: ``S1`` / ``S2`` / ``S3`` (trains that stage, INTERNAL; re-simulated in S4), ``S5``
(external validation, EXTERNAL), ``S6`` (verifies a planned application: DDI, PGx, special population, preclinical;
EXTERNAL), ``SUPPORTIVE`` (context only).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from modeler_project.artifacts import ArtifactKind, ArtifactVersion
from modeler_project.brief import ProjectBrief
from modeler_project.workspace import Workspace
from pbpk_domain.campaign.map import FIT_STAGES, S5_CLASSES, STAGE_PLAN, MapDocument, generate_map, training_stages
from pbpk_domain.campaign.split import (
    FLAGGED_CLASSES,
    Assignment,
    FoodState,
    QuestionOfInterest,
    SplitResult,
    StudyClass,
    StudyRecord,
    StudySplit,
    split_studies,
)
from pbpk_domain.cpf.models import CPF, FitPolicy, Scale
from pbpk_domain.data_origin import REAL_ORIGINS
from pbpk_domain.fit_spec import resolve_fit_ids
from pbpk_domain.m15 import Rating

MAIN = "main"
Role = Literal["S1", "S2", "S3", "S5", "S6", "SUPPORTIVE"]
ROLES: tuple[str, ...] = ("S1", "S2", "S3", "S5", "S6", "SUPPORTIVE")
TRAINING = ("S1", "S2", "S3")
_ASSIGNMENT = {"S1": Assignment.INTERNAL, "S2": Assignment.INTERNAL, "S3": Assignment.INTERNAL,
               "S5": Assignment.EXTERNAL, "S6": Assignment.EXTERNAL, "SUPPORTIVE": Assignment.SUPPORTIVE}
ENGINE_DIGEST = "sha256:" + "0" * 64


class PlanError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


# The plan's stored content is always dumped whole (`to_content`), so in the API contract (phase 9b) a field with a
# default is still always present: the answer schema marks it required.
_CONTENT = ConfigDict(frozen=True, extra="forbid", json_schema_serialization_defaults_required=True)


class Placement(BaseModel):
    model_config = _CONTENT

    role: Role
    by: str = "default"              # default | agent:<run> | a person's user id
    userLocked: bool = False
    reason: str = ""
    at: datetime | None = None


class FitChoice(BaseModel):
    model_config = _CONTENT

    stages: tuple[str, ...]
    lower: float
    upper: float
    scale: Literal["linear", "log"] = "linear"
    by: str
    userLocked: bool = True
    reason: str = Field(min_length=1)


class Proposal(BaseModel):
    """An A5 departure from the plan, shown in the diff until a person accepts or rejects it."""

    model_config = _CONTENT

    id: str
    kind: Literal["role", "fit"]
    target: str                       # study id, or parameter id
    value: dict[str, Any]             # {"role": …} or a FitChoice without by/userLocked
    reason: str
    by: str
    status: Literal["PENDING", "ACCEPTED", "REJECTED"] = "PENDING"
    decided_by: str | None = None
    decision_reason: str = ""


class Structure(BaseModel):
    model_config = _CONTENT

    objective: str = "Predict exposure for the question of interest"
    context_of_use: str = "Model-informed decision"
    model_risk: Literal["low", "medium", "high"] = "medium"
    food_effect_in_question: bool = False
    measured_fed_solubility: bool = False
    planned_applications: tuple[str, ...] = ()   # flagged classes with a planned S6 application (MS-01 rule 4)
    locked: tuple[str, ...] = ()                  # structure keys a person set (userLocked)
    reasons: dict[str, str] = Field(default_factory=dict)


class StudyView(BaseModel):
    """What the plan knows about a study (from the P4 catalog): enough to plan and validate, no observed values."""

    model_config = _CONTENT

    study_id: str
    study_class: str
    score: float
    route: str
    dose_mg: float
    formulation: str
    food_state: str
    design: str
    n: int
    origin: str
    evaluable: bool
    kind: str = "profile"
    purpose: str = ""
    default_role: Role
    new: bool = False


class Deviation(BaseModel):
    """A change to the plan after its MAP was signed (D-14, ICH M15 §4.2): it applies to campaigns only once the MIDD
    lead signs it, which makes a new MAP version superseding the signed one."""

    model_config = _CONTENT

    kind: str                         # role | fit | fit removed | unlock | structure | acknowledged | proposal
    target: str
    change: str                       # what changed, in words ("S2 → S5", "fitted in S1 [0.1, 10]")
    reason: str
    by: str
    at: datetime
    against_map: int                  # the signed MAP version it deviates from
    signature_id: str | None = None   # set when signed
    signed_map: int | None = None     # the MAP version that carries it


class ModelPlan(BaseModel):
    model_config = _CONTENT

    schema_id: str = Field(default="model-plan/1", alias="schema")
    compound: str
    studies: tuple[StudyView, ...]
    placements: dict[str, Placement]
    fits: dict[str, FitChoice] = Field(default_factory=dict)
    structure: Structure = Field(default_factory=Structure)
    default_rationale: tuple[str, ...] = ()
    default_limitations: tuple[str, ...] = ()
    rationale: dict[str, str] = Field(default_factory=dict)      # target -> A5's (or a person's) explanation
    proposals: tuple[Proposal, ...] = ()
    acknowledged: dict[str, str] = Field(default_factory=dict)   # violation id -> the person's reason
    layout: dict[str, dict[str, float]] = Field(default_factory=dict)  # canvas positions: a view, not the record
    fit_candidates: dict[str, tuple[str, ...]] = Field(default_factory=dict)  # stage -> concrete CPF ids (MS-01 §4)
    budgets: dict[str, int] = Field(default_factory=dict)
    deviations: tuple[Deviation, ...] = ()   # changes after the MAP was signed (D-14), pending until signed

    def pending_deviations(self) -> tuple[Deviation, ...]:
        return tuple(d for d in self.deviations if d.signature_id is None)

    def to_content(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)

    @classmethod
    def from_content(cls, content: dict[str, Any]) -> ModelPlan:
        return cls.model_validate(content)

    def study(self, study_id: str) -> StudyView:
        found = next((s for s in self.studies if s.study_id == study_id), None)
        if found is None:
            raise PlanError(f"no study {study_id} in the plan")
        return found


# Which flagged study class verifies which application of the brief (MS-01 §3.3 rule 4: planned applications).
_APPLICATION_CLASSES = {"APP-03": "DDI", "APP-04": "DDI", "APP-13": "DDI", "APP-05": "PGX", "APP-06": "SPECIAL",
                        "APP-07": "SPECIAL", "APP-08": "SPECIAL", "APP-09": "SPECIAL", "APP-10": "SPECIAL",
                        "APP-02": "PRECLINICAL"}


def applications(brief: ProjectBrief | None) -> set[str]:
    """The brief's application codes (``APP-12``), from its labels (``APP-12 food effect``)."""
    return {str(a).split(" ", 1)[0] for a in ((brief.value("qoi.applications") if brief else None) or [])}


def structure_from_brief(brief: ProjectBrief | None, *, measured_fed_solubility: bool = False) -> Structure:
    """The plan's structure as the brief states it (each a default a person may change with a reason)."""
    apps = applications(brief)
    tier = brief.value("acceptance.tier") if brief else None
    return Structure(objective=str((brief.value("qoi.text") if brief else None) or Structure().objective),
                     context_of_use=str((brief.value("qoi.context_of_use") if brief else None) or Structure().context_of_use),
                     model_risk=tier if tier in ("low", "medium", "high") else "medium",
                     food_effect_in_question="APP-12" in apps, measured_fed_solubility=measured_fed_solubility,
                     planned_applications=tuple(sorted({_APPLICATION_CLASSES[a] for a in apps if a in _APPLICATION_CLASSES})))


# --- the default (MS-01, exactly as generate_map) --------------------------------------------------------------


def _records(rows: list[dict[str, Any]]) -> list[StudyRecord]:
    fields = set(StudyRecord.model_fields)
    return [StudyRecord.model_validate({k: v for k, v in r.items() if k in fields}) for r in rows]


def _question(structure: Structure) -> QuestionOfInterest:
    return QuestionOfInterest(food_effect=structure.food_effect_in_question,
                              measured_fed_solubility=structure.measured_fed_solubility,
                              planned_applications=frozenset(StudyClass(c) for c in structure.planned_applications))


def _role(split_row: StudySplit, train: dict[str, str | None]) -> Role:
    if split_row.assignment is Assignment.INTERNAL:
        return train.get(split_row.study_id) or "SUPPORTIVE"  # type: ignore[return-value]
    if split_row.assignment is Assignment.EXTERNAL:
        return "S5" if split_row.study_class in S5_CLASSES else "S6"
    return "SUPPORTIVE"


def _sampling_end_h(rows: list[dict[str, Any]]) -> dict[str, float]:
    hours = {"min": 1 / 60, "h": 1.0, "day": 24.0}
    return {r["study_id"]: max(r["profile"]["times"]) * hours[r["profile"]["time_unit"]]
            for r in rows if r.get("profile") and r["profile"]["time_unit"] in hours}


def default_map(cpf: CPF, rows: list[dict[str, Any]], structure: Structure, *, split: SplitResult | None = None,
                campaign_budget_seconds: int = 3600) -> tuple[MapDocument, SplitResult]:
    """The MAP exactly as `generate_map` makes it today (the split computed by MS-01 unless one is given)."""
    records = _records(rows)
    split = split or split_studies(records, _question(structure))
    doc = generate_map(compound=cpf.compound, cpf=cpf, studies=records, split=split, objective=structure.objective,
                       context_of_use=structure.context_of_use, food_effect_in_question=structure.food_effect_in_question,
                       model_risk=Rating(structure.model_risk), engine_image_digest=ENGINE_DIGEST,
                       software_versions={"ospsuite": "12.4.4"}, sampling_end_h=_sampling_end_h(rows),
                       campaign_budget_seconds=campaign_budget_seconds)
    return doc, split


def _candidates(cpf: CPF) -> dict[str, tuple[str, ...]]:
    """Per fit stage, the concrete CPF parameters MS-01 lets it fit (the stage plan's templated candidates)."""
    out = {}
    for stage in FIT_STAGES:
        ids = [cid for target in STAGE_PLAN[stage]["fit_candidates"] for cid in resolve_fit_ids(cpf, target)]
        out[stage] = tuple(dict.fromkeys(i for i in ids if isinstance(cpf.get(i).value, int | float)))
    return out


def build_default(cpf: CPF, rows: list[dict[str, Any]], structure: Structure) -> ModelPlan:
    map_doc, split = default_map(cpf, rows, structure)
    train = training_stages(_records(rows), split, cpf)
    by_id = {r["study_id"]: r for r in rows}
    studies, placements = [], {}
    for s in split.splits:
        r = by_id[s.study_id]
        role = _role(s, train)
        studies.append(StudyView(study_id=s.study_id, study_class=s.study_class.value, score=round(s.score, 3),
                                 route=str(r["route"]), dose_mg=float(r["dose_mg"]), formulation=str(r.get("formulation", "")),
                                 food_state=str(r.get("food_state", "fasted")), design=str(r.get("design", "SD")), n=int(r["n"]),
                                 origin=str(r.get("origin") or "UNRECORDED"), evaluable=bool(r.get("evaluable", "profile" in r)),
                                 kind="profile" if r.get("profile") else "pk_parameters", purpose=str(r.get("purpose", "")),
                                 default_role=role))
        placements[s.study_id] = Placement(role=role)
    return ModelPlan(compound=cpf.compound, studies=tuple(studies), placements=placements, structure=structure,
                     default_rationale=split.rationale, default_limitations=split.limitations,
                     fit_candidates=_candidates(cpf), budgets={p.stage: p.budget_seconds for p in map_doc.stage_plan})


def rebase(previous: ModelPlan | None, fresh: ModelPlan) -> ModelPlan:
    """Recompute on new inputs: the default follows the data, a person's (userLocked) choices are kept, agent
    rationales and pending proposals for studies that still exist are kept, studies new since `previous` are marked."""
    if previous is None:
        return fresh
    old_ids = {s.study_id for s in previous.studies}
    studies = tuple(s.model_copy(update={"new": s.study_id not in old_ids}) for s in fresh.studies)
    ids = {s.study_id for s in studies}
    placements = {sid: (previous.placements[sid] if sid in previous.placements and previous.placements[sid].userLocked else p)
                  for sid, p in fresh.placements.items()}
    candidates = {i for ids_ in fresh.fit_candidates.values() for i in ids_}
    structure = fresh.structure
    if previous.structure.locked:
        structure = previous.structure
    return fresh.model_copy(update={
        "studies": studies, "placements": placements, "structure": structure,
        "fits": {k: v for k, v in previous.fits.items() if k in candidates or v.userLocked},
        "rationale": {k: v for k, v in previous.rationale.items() if k in ids or "." in k or k.startswith("structure")},
        "proposals": tuple(p for p in previous.proposals if p.target in ids or p.kind == "fit"),
        "acknowledged": previous.acknowledged, "layout": previous.layout,
    })


# --- the live validator ----------------------------------------------------------------------------------------


class Violation(BaseModel):
    model_config = ConfigDict(frozen=True, json_schema_serialization_defaults_required=True)

    id: str
    severity: Literal["error", "warning"]
    rule: str
    target: str
    message: str
    acknowledged: str | None = None


def _split_of(plan: ModelPlan) -> SplitResult:
    splits = tuple(StudySplit(study_id=s.study_id, study_class=StudyClass(s.study_class), score=s.score,
                              assignment=_ASSIGNMENT[plan.placements[s.study_id].role]) for s in plan.studies)
    return SplitResult(splits=splits, rationale=plan.default_rationale, limitations=plan.default_limitations)


def validate(plan: ModelPlan, cpf: CPF, rows: list[dict[str, Any]], *, exploratory: bool = False) -> list[Violation]:
    """Every MS-01 rule the canvas enforces (plan §11.4). Errors block the signature; warnings need an acknowledgment."""
    out: list[Violation] = []

    def add(severity: str, rule: str, target: str, message: str) -> None:
        vid = f"{rule}:{target}"
        out.append(Violation(id=vid, severity=severity, rule=rule, target=target, message=message,  # type: ignore[arg-type]
                             acknowledged=plan.acknowledged.get(vid) if severity == "warning" else None))

    split = _split_of(plan)
    train = training_stages(_records(rows), split, cpf)
    for s in plan.studies:
        p = plan.placements[s.study_id]
        cls = StudyClass(s.study_class)
        if p.by not in ("default",) and not p.by.startswith("agent:") and not p.reason.strip():
            add("error", "reason", s.study_id, f"{s.study_id}: a manual move needs a reason")
        if p.role in TRAINING:
            if cls in FLAGGED_CLASSES:
                add("error", "rule-4", s.study_id, f"{s.study_id} is a {cls.value} study: MS-01 §3.3 rule 4 never lets it "
                                                   "train S1–S3; it verifies its application (S6) or is supportive")
            elif train.get(s.study_id) is None:
                add("error", "stage", s.study_id, f"{s.study_id} ({cls.value}) trains no stage under MS-01 (S1 IV, S2 fasted "
                                                  "oral, S3 fed / formulation); validate it in S5")
            elif train[s.study_id] != p.role:
                add("error", "stage", s.study_id, f"{s.study_id} ({cls.value}) trains {train[s.study_id]}, not {p.role}")
            if cls is StudyClass.PO_FED and plan.structure.food_effect_in_question:
                add("error", "rule-5", s.study_id, f"{s.study_id}: food effect is the question, so no fed study is fitted "
                                                   "(MS-01 §3.3 rule 5); validate it externally")
            if not s.evaluable:
                add("error", "profile", s.study_id, f"{s.study_id} has no concentration profile (PK parameters or individual "
                                                    "data only): it cannot train a profile fit")
        if p.role == "S6" and cls not in FLAGGED_CLASSES:
            add("error", "rule-4", s.study_id, f"{s.study_id} ({cls.value}) is a core study: it validates in S5, S6 verifies "
                                               "DDI / PGx / special-population / preclinical applications")
        if p.role == "S5" and cls not in S5_CLASSES:
            add("error", "rule-4", s.study_id, f"{s.study_id} ({cls.value}) validates its S6 application, not the base model")
        if p.role == "S5" and not s.evaluable:
            add("warning", "judged", s.study_id, f"{s.study_id} has no profile: the current campaign cannot judge it in S5")
        if p.role != "SUPPORTIVE" and s.origin not in {o.value for o in REAL_ORIGINS} and not exploratory:
            add("warning", "real-data", s.study_id, f"{s.study_id} is {s.origin.lower()} data: the S4/S5 evaluation judged on "
                                                    "it cannot be signed in this project (plan §9.4)")
    roles = {s.study_id: plan.placements[s.study_id].role for s in plan.studies}
    by_class = {c: [s for s in plan.studies if s.study_class == c.value] for c in StudyClass}
    if by_class[StudyClass.IV_SD] and not any(roles[s.study_id] == "S1" for s in by_class[StudyClass.IV_SD]):
        add("warning", "rule-1", "S1", "no IV study trains S1: distribution and clearance are identified from oral data, "
                                       "confounded with bioavailability (MS-01 decision tree §6.1)")
    fasted = by_class[StudyClass.PO_SOL_FASTED] + by_class[StudyClass.PO_IR_FASTED]
    if fasted and not any(roles[s.study_id] in ("S2", "S3") for s in fasted):
        add("warning", "rule-1", "S2", "no fasted oral study trains absorption: oral exposure is predicted, not fitted "
                                       "(MS-01 decision tree §6.2)")
    categories = (("fasted oral", lambda s: s.route == "oral" and s.food_state == FoodState.FASTED.value),
                  ("fed", lambda s: s.route == "oral" and s.food_state == FoodState.FED.value),
                  ("multiple-dose", lambda s: s.design.upper() == "MD"))
    for label, predicate in categories:
        members = [s for s in plan.studies if predicate(s)]
        # a study the campaign cannot judge (no profile) does not cover a category
        if len(members) >= 2 and not any(roles[s.study_id] == "S5" and s.evaluable for s in members):
            add("warning", "rule-3", label, f"no external {label} study: this category is not validated externally "
                                            "(MS-01 §3.3 rule 3)")
    for pid, fit in plan.fits.items():
        record = cpf.get(pid)
        if record is None or not isinstance(record.value, int | float):
            add("error", "fit", pid, f"{pid}: not a numeric parameter of the CPF")
            continue
        if not set(fit.stages) <= set(FIT_STAGES):
            add("error", "fit", pid, f"{pid}: fitted only in S1–S3 (MS-01 §4), not {', '.join(fit.stages)}")
        if not fit.lower < float(record.value) < fit.upper:
            add("error", "fit", pid, f"{pid}: the start value {record.value:g} lies outside [{fit.lower:g}, {fit.upper:g}]")
        if fit.scale == "log" and fit.lower <= 0:
            add("error", "fit", pid, f"{pid}: a log-scaled fit needs a positive lower bound")
        off = [st for st in fit.stages if pid not in plan.fit_candidates.get(st, ())]
        if off:
            add("warning", "fit-candidate", pid, f"{pid} is not an MS-01 fit candidate at {', '.join(off)} (MS-01 §4 stage plan)")
        trained = [st for st in fit.stages if any(r == st for r in roles.values())]
        if not trained:
            add("warning", "fit-data", pid, f"{pid}: no study trains {', '.join(fit.stages)}, so nothing will fit it")
    return out


def blocking(violations: list[Violation]) -> list[Violation]:
    return [v for v in violations if v.severity == "error" or not v.acknowledged]


# --- changes ---------------------------------------------------------------------------------------------------


def place(plan: ModelPlan, study_id: str, role: str, *, by: str, reason: str) -> ModelPlan:
    """A person places a study (drag and drop on D3): the placement is userLocked with the reason."""
    plan.study(study_id)
    if role not in ROLES:
        raise PlanError(f"{role!r} is not a role ({', '.join(ROLES)})")
    if not reason.strip():
        raise PlanError("a manual move needs a reason (one sentence at least)")
    placements = {**plan.placements, study_id: Placement(role=role, by=by, userLocked=True, reason=reason, at=_now())}  # type: ignore[arg-type]
    return plan.model_copy(update={"placements": placements})


def unlock(plan: ModelPlan, study_id: str) -> ModelPlan:
    """Give a study back to the default (its lock removed)."""
    view = plan.study(study_id)
    return plan.model_copy(update={"placements": {**plan.placements, study_id: Placement(role=view.default_role)}})


def set_fit(plan: ModelPlan, parameter: str, fit: dict[str, Any] | None, *, by: str, reason: str) -> ModelPlan:
    fits = dict(plan.fits)
    if fit is None:
        fits.pop(parameter, None)
    else:
        fits[parameter] = FitChoice(**fit, by=by, userLocked=True, reason=reason)
    return plan.model_copy(update={"fits": fits})


def set_structure(plan: ModelPlan, key: str, value: Any, *, by: str, reason: str) -> ModelPlan:
    if key not in Structure.model_fields or key in ("locked", "reasons"):
        raise PlanError(f"{key!r} is not a structure choice")
    if not reason.strip():
        raise PlanError("a structure change needs a reason")
    current = plan.structure.model_dump()
    current[key] = value
    current["locked"] = tuple(dict.fromkeys([*plan.structure.locked, key]))
    current["reasons"] = {**plan.structure.reasons, key: f"{reason} ({by})"}
    return plan.model_copy(update={"structure": Structure.model_validate(current)})


def acknowledge(plan: ModelPlan, violation_id: str, *, by: str, reason: str) -> ModelPlan:
    if not reason.strip():
        raise PlanError("an acknowledgment needs a reason")
    return plan.model_copy(update={"acknowledged": {**plan.acknowledged, violation_id: f"{reason} ({by})"}})


def add_proposal(plan: ModelPlan, kind: str, target: str, value: dict[str, Any], *, reason: str, by: str) -> tuple[ModelPlan, str]:
    """An agent's departure. Refused (with why) when it touches a person's choice; otherwise PENDING in the diff."""
    if kind == "role":
        plan.study(target)
        if plan.placements[target].userLocked:
            return plan, f"REFUSED: {target} was placed by a person ({plan.placements[target].reason}); it is not overwritten"
        if value.get("role") not in ROLES:
            return plan, f"REFUSED: {value.get('role')!r} is not a role"
    elif kind == "fit":
        if target in plan.fits and plan.fits[target].userLocked:
            return plan, f"REFUSED: the fit of {target} was set by a person; it is not overwritten"
    proposal = Proposal(id=f"pr-{uuid.uuid4().hex[:8]}", kind=kind, target=target, value=value, reason=reason, by=by)  # type: ignore[arg-type]
    pending = [p for p in plan.proposals if not (p.status == "PENDING" and p.kind == kind and p.target == target)]
    return plan.model_copy(update={"proposals": (*pending, proposal)}), f"PROPOSED {proposal.id}"


def decide_proposal(plan: ModelPlan, proposal_id: str, *, accept: bool, by: str, reason: str) -> ModelPlan:
    proposal = next((p for p in plan.proposals if p.id == proposal_id), None)
    if proposal is None or proposal.status != "PENDING":
        raise PlanError(f"no pending proposal {proposal_id}")
    if not reason.strip():
        raise PlanError("a decision needs a reason")
    if accept:
        why = f"accepted {proposal.by}'s proposal: {proposal.reason} — {reason}"
        if proposal.kind == "role":
            plan = place(plan, proposal.target, proposal.value["role"], by=by, reason=why)
        else:
            plan = set_fit(plan, proposal.target, proposal.value, by=by, reason=why)
    decided = proposal.model_copy(update={"status": "ACCEPTED" if accept else "REJECTED", "decided_by": by,
                                          "decision_reason": reason})
    return plan.model_copy(update={"proposals": tuple(decided if p.id == proposal_id else p for p in plan.proposals)})


def diff(plan: ModelPlan) -> list[dict[str, Any]]:
    """Everything that departs from the MS-01 default: placements, fits, structure, and the agent's pending proposals."""
    out = []
    for s in plan.studies:
        p = plan.placements[s.study_id]
        if p.role != s.default_role:
            out.append({"kind": "role", "target": s.study_id, "from": s.default_role, "to": p.role, "by": p.by,
                        "reason": p.reason, "status": "APPLIED"})
    for pid, fit in plan.fits.items():
        out.append({"kind": "fit", "target": pid, "from": "fixed", "to": f"fitted in {', '.join(fit.stages)} "
                    f"[{fit.lower:g}, {fit.upper:g}] {fit.scale}", "by": fit.by, "reason": fit.reason, "status": "APPLIED"})
    for key in plan.structure.locked:
        out.append({"kind": "structure", "target": key, "from": "brief / default", "to": getattr(plan.structure, key),
                    "by": "person", "reason": plan.structure.reasons.get(key, ""), "status": "APPLIED"})
    for pr in plan.proposals:
        if pr.status == "PENDING":
            to = pr.value.get("role") if pr.kind == "role" else f"fitted in {', '.join(pr.value.get('stages', []))}"
            current = plan.placements[pr.target].role if pr.kind == "role" else ("fitted" if pr.target in plan.fits else "fixed")
            out.append({"kind": pr.kind, "target": pr.target, "from": current, "to": to, "by": pr.by, "reason": pr.reason,
                        "status": "PENDING", "proposal": pr.id})
    return out


# --- MAP from plan ---------------------------------------------------------------------------------------------


def campaign_cpf(plan: ModelPlan, cpf: CPF) -> CPF:
    """CPF v1 with the plan's fit choices as fit policies (status and values unchanged)."""
    records = []
    for record in cpf.parameters:
        fit = plan.fits.get(record.id)
        if fit is not None:
            record = record.model_copy(update={"fit_policy": FitPolicy(stage=fit.stages, lower=fit.lower, upper=fit.upper,
                                                                       scale=Scale(fit.scale))})
        records.append(record)
    return CPF(compound=cpf.compound, version=cpf.version, parameters=tuple(records), note=cpf.note)


def plan_split(plan: ModelPlan) -> SplitResult:
    """The plan's assignments as the MAP's split; its departures and acknowledged warnings recorded with their reasons."""
    base = _split_of(plan)
    changes = [f"Plan change: {d['target']} {d['from']} → {d['to']} by {d['by']}: {d['reason']}"
               for d in diff(plan) if d["status"] == "APPLIED"]
    return base.model_copy(update={"rationale": (*plan.default_rationale, *changes)})


def map_from_plan(plan: ModelPlan, cpf: CPF, rows: list[dict[str, Any]], *, exploratory: bool = False,
                  acknowledged_limitations: bool = True) -> MapDocument:
    """The MAP, deterministically, from the plan. Refused while the validator has a blocking violation."""
    violations = validate(plan, cpf, rows, exploratory=exploratory)
    if blocking(violations):
        raise PlanError("the plan has open rule violations: " + "; ".join(v.message for v in blocking(violations)))
    split = plan_split(plan)
    limits = [f"{v.message} — acknowledged: {v.acknowledged}" for v in violations if v.severity == "warning" and v.acknowledged]
    split = split.model_copy(update={"limitations": (*plan.default_limitations, *(limits if acknowledged_limitations else []))})
    doc, _ = default_map(campaign_cpf(plan, cpf), rows, plan.structure, split=split)
    return doc


# --- persistence ---------------------------------------------------------------------------------------------


def current(ws: Workspace) -> tuple[ArtifactVersion | None, ModelPlan | None]:
    version = ws.latest(ArtifactKind.MODEL_PLAN, MAIN)
    return version, (ModelPlan.from_content(version.content) if version else None)


def save(ws: Workspace, plan: ModelPlan, *, by: str, reason: str, derived_from=()) -> ArtifactVersion:
    version, _ = current(ws)
    upstream = tuple(derived_from) or (version.derived_from if version else ())
    return ws.commit(ArtifactKind.MODEL_PLAN, MAIN, plan.to_content(), derived_from=upstream, actor=by, reason=reason)
