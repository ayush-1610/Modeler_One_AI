"""What the Data room's "Send to the model" rests on, read in one place (plan 2026-11-24 §7, phase 4: a modeller does not
type again at Start or on Review & sign what the delivery already said).

Start (`brief_from_room`, `steps.room_advice`), the model plan (`plan.structure_from_brief`), the MAP's limitations and the
VBE panel (`review.applications`) read the room only through `room_basis`: the question card a person confirmed, the
applications decision, every decision with its reason, the open required data requests, the NCA findings the data do
not reproduce, the convention of the arithmetic mean (below the LLOQ counted as 0), the room's plan roles, its products,
each study arm's route, dose and food, and a paired BE summary from the room's own NCA.

It reads the live room today (`dataroom.room_view`, `DataRoomStore`). Once "Send to the model" writes a snapshot of what
the send rested on, `room_basis` reads that instead: here, and nowhere else.

`ROOM_TO_BRIEF` maps the room's applications to the brief's application codes; the owner reviews it (it decides which
MS-01 rules apply, e.g. APP-12's food-effect rule).
"""

from __future__ import annotations

import math
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from modeler_intake.room_specs import QuestionCard
from modeler_project.brief import Citation
from modeler_project.dataroom import room_view
from modeler_project.dataroom.checklist import DECISION, NONE, applications_decision, chosen_applications
from modeler_project.dataroom.model import Chip, DataRoomView, RoomDecision, RoomStudy, Value
from modeler_project.dataroom.publish import slug
from modeler_project.dataroom.store import DataRoomStore
from modeler_project.workspace import Workspace

# The Data room's applications (`dataroom.checklist.APPLICATIONS`, the requirement drafts per context of use) and the
# brief's application codes (`brief.APPLICATIONS`) they stand for. Each code was checked against the brief's label on
# 2026-11-24; THE OWNER REVIEWS THIS TABLE (it decides which MS-01 rules apply: APP-12 keeps fed studies out of the fit).
ROOM_TO_BRIEF: dict[str, tuple[str, ...]] = {
    "pbbm_bridging_vbe": ("APP-11", "APP-14"),        # absorption and formulation; virtual bioequivalence (app_vbe.yaml)
    "food_effect": ("APP-12",),                         # food effect
    "acid_reducing_agents": ("APP-13",),                # pH-dependent DDI
    "ddi_victim": ("APP-03",),                          # enzyme DDI: the drug a CYP or UGT substrate
    "ddi_perpetrator": ("APP-03",),                     # enzyme DDI: the drug inhibits or induces
    "transporter_ddi": ("APP-04",),                     # transporter DDI
    "pediatric": ("APP-06",),                           # pediatric extrapolation
    "organ_impairment.renal_impairment": ("APP-08",),   # renal impairment
    "organ_impairment.hepatic_impairment": ("APP-07",),  # hepatic impairment
    "fih_dose_prediction": ("APP-02",),                 # FIH translation
    "special_populations.pregnancy": ("APP-09",),       # pregnancy and lactation
    "special_populations.geriatrics": ("APP-10",),      # geriatrics, obesity, ethnicity
    "special_populations.ethnicity": ("APP-10",),       # geriatrics, obesity, ethnicity
    NONE: ("APP-01",),                                  # none of these: model build and verification
}

SOURCE = "the Data room"
# the template's metrics (vbe-crossover `pk` step, PK-Sim's own names) and the room's NCA value for each
BE_METRICS: dict[str, str] = {"AUC_inf": "auc_inf", "C_max": "cmax"}
TEST_ROLES = ("test", "reformulated")
REFERENCE_ROLES = ("reference", "original")


def brief_codes(applications: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """The brief's application codes for the room's applications (`ROOM_TO_BRIEF`), in code order."""
    return tuple(sorted({code for a in applications for code in ROOM_TO_BRIEF.get(a, ())}))


class _B(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RoomCite(_B):
    """Where a delivered file says it: the file, its sha256, the part (p3, sheet:Name, body) and the quote."""

    file: str
    sha256: str
    part: str = ""
    quote: str

    def citation(self) -> Citation | None:
        """As a brief citation; None when the file's sha256 or the quote is not known."""
        if not re.fullmatch(r"[0-9a-f]{64}", self.sha256) or not self.quote.strip():
            return None
        page = int(self.part[1:]) if re.fullmatch(r"p\d+", self.part) and int(self.part[1:]) >= 1 else 1
        name = self.file.rsplit("/", 1)[-1]
        return Citation(doc_sha256=self.sha256, page=page, quote=self.quote, locator=self.part,
                        source=f"Data room: {name}")


class DecisionLine(_B):
    id: str
    title: str
    chosen: str                      # the option's label ("" while it waits)
    suggested: bool                  # the person took the room's suggestion (or none was chosen yet: `waiting`)
    waiting: bool
    reason: str = ""                 # the person's reason
    why: str = ""                    # the room's own reason for its suggestion
    by: str = ""
    at: str = ""
    # left for Inputs (the owner's D1; plan 2026-11-26 §9, slice 5b): the population, sex or meal template not chosen
    # in the room; `chosen` is the room's suggestion, proposed to Inputs, where a person confirms or changes it
    on_inputs: bool = Field(default=False, exclude_if=lambda v: not v)


class RequestLine(_B):
    id: str
    area: str
    title: str
    why: str
    required: bool                   # False: a draft's "usually needed" item


class ProductLine(_B):
    name: str
    role: str                        # the card's word: reference, test, original, reformulated, other
    formulation: str                 # the CPF formulation name the send gives it (`publish.slug`)
    sent: bool                       # the room has a release input for it: the send makes it a CPF formulation


class StatedLine(_B):
    """A value as the delivery states it, with where."""

    text: str
    value: float | str | None = None
    unit: str = ""
    cites: tuple[RoomCite, ...] = ()


class ArmLine(_B):
    """One arm of a clinical study, as the room sends it."""

    study: str
    treatment: str
    study_id: str                    # the observed dataset's study id after the send: "<study>-<treatment>"
    product: str = ""
    product_role: str = ""
    plan_role: str = ""              # the room's plan: calibration, verification, prediction
    plan_why: str = ""
    route: StatedLine | None = None
    dose: StatedLine | None = None
    food: StatedLine | None = None
    population: StatedLine | None = None   # healthy, patients … as written
    population_db: str = ""                # the PK-Sim population the room chose for the study
    sex: StatedLine | None = None


class BeMetric(_B):
    metric: str                      # AUC_inf, C_max (the template's names)
    gmr: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    between_subject_cv_percent: float | None = None
    n: int = 0


class BeSummary(_B):
    """A test-against-reference summary from the room's own NCA, paired by subject in the analysis set sent."""

    study: str
    test: str
    reference: str
    analysis_set: str
    metrics: tuple[BeMetric, ...] = ()
    source: str = ""
    stated: tuple[StatedLine, ...] = ()    # the delivery's own BE results (study.be_result), as written


class RoomBasis(_B):
    source: Literal["live", "snapshot"] = "live"
    card: QuestionCard
    confirmed: bool
    applications: tuple[str, ...] = ()      # the room's application ids in force (`none`: the core items only)
    application_labels: tuple[str, ...] = ()
    applications_chosen: bool = False       # a person chose them; False: as read from the question card
    applications_reason: str = ""
    card_cites: dict[str, tuple[RoomCite, ...]] = {}   # the card's quotes by field (question.text, question.regulator …)
    products: tuple[ProductLine, ...] = ()
    dosage_forms: tuple[StatedLine, ...] = ()  # product.dosage_form and product.release as written
    arms: tuple[ArmLine, ...] = ()
    decisions: tuple[DecisionLine, ...] = ()
    open_requests: tuple[RequestLine, ...] = ()
    nca_differ: tuple[str, ...] = ()
    blq: tuple[str, ...] = ()
    be: tuple[BeSummary, ...] = ()
    full: bool = True                        # False: the card and the applications only (`room_basis(full=False)`)
    basis_sha256: str = ""                   # source "snapshot": the sha256 of the send's basis its signature covers

    @property
    def codes(self) -> tuple[str, ...]:
        """The brief's application codes for the room's applications."""
        return brief_codes(self.applications or (NONE,))


# --- the reader -------------------------------------------------------------------------------------------------------


def room_basis(ws: Workspace, *, full: bool = True) -> RoomBasis | None:
    """What the room's send rests on, or None when the project has no Data room or no question card: the newest send's
    snapshot once the room was sent ("snapshot", the record its signature covers), else the live room ("live"). So the
    brief, the plan, the MAP and the VBE panel take what was sent, and a decision changed in the room later reaches
    them only with the next send. `full=False` reads the live card and applications decision only (no assembly of the
    room): what Start's advice and the Inputs check need, which follow the room as it is now."""
    store = DataRoomStore(ws)
    if not store.available:
        return None
    if full and (sent := sent_basis(store)) is not None:
        return sent
    card, confirmed = store.question()
    if card is None:
        return None
    if not full:
        made = store.decisions()
        decision = applications_decision(card, made)
        paths = {f.path: f.sha256 for f in store.files()}
        return _card_part(card, confirmed, decision, paths).model_copy(update={"full": False})
    return basis_from_view(room_view(store))


def sent_basis(store: DataRoomStore) -> RoomBasis | None:
    """The newest send's reading of the room (`publish.publication_basis`, format 2 on), or None before the first send
    or when the newest send was recorded before the snapshot was kept (the live room is read then, as it was)."""
    sends = store.publications()
    if not sends:
        return None
    newest = sends[-1]
    kept = (newest.get("basis") or {}).get("room_basis")
    if not kept:
        return None
    return RoomBasis.model_validate(kept).model_copy(update={"source": "snapshot",
                                                             "basis_sha256": str(newest.get("basis_sha256", ""))})


def _cite(chip: Chip) -> RoomCite | None:
    return RoomCite(file=chip.file, sha256=chip.sha256, part=chip.part, quote=chip.text) if chip.text.strip() else None


def _stated(v: Value | None) -> StatedLine | None:
    if v is None:
        return None
    return StatedLine(text=v.as_written or str(v.value or ""), value=v.value, unit=v.unit,
                      cites=tuple(c for chip in v.sources if (c := _cite(chip)) is not None))


def _card_part(card: QuestionCard, confirmed: bool, decision: RoomDecision | None, paths: dict[str, str]) -> RoomBasis:
    apps = chosen_applications(decision)
    picked = (decision.chosen or decision.suggested) if decision else NONE
    cites: dict[str, list[RoomCite]] = {}
    for fact in card.quotes:
        if fact.quote.strip():
            cites.setdefault(fact.field, []).append(RoomCite(file=fact.file, sha256=paths.get(fact.file, ""), part=fact.part,
                                                             quote=fact.quote))
    return RoomBasis(card=card, confirmed=confirmed, applications=tuple(a.id for a in apps) or ((NONE,) if picked == NONE else ()),
                     application_labels=tuple(a.label for a in apps), applications_chosen=bool(decision and decision.chosen),
                     applications_reason=(decision.reason or decision.why) if decision else "",
                     card_cites={k: tuple(v) for k, v in cites.items()})


def basis_from_view(view: DataRoomView) -> RoomBasis | None:
    """The basis from an assembled room (pure: the tests build rooms in memory)."""
    if view.question is None:
        return None
    decision = next((d for d in view.decisions if d.id == DECISION), None)
    basis = _card_part(view.question, view.question_confirmed, decision, {f.path: f.sha256 for f in view.files})
    sent = {r.owner for r in view.inputs if r.block == "formulation" and r.name == "Formulation_Tablet_Weibull"}
    products = tuple(ProductLine(name=p.name, role=p.role, formulation=slug(p.name), sent=p.name in sent)
                     for p in view.question.products)
    forms = tuple(s for v in view.products if v.key.startswith(("product.dosage_form", "product.release"))
                  and (s := _stated(v)) is not None)
    return basis.model_copy(update={
        "products": products, "dosage_forms": forms, "arms": tuple(_arms(view)), "decisions": tuple(_decisions(view)),
        "open_requests": tuple(RequestLine(id=r.id, area=r.area, title=r.title, why=r.why,
                                           required=not r.why.startswith("Usually needed"))
                               for r in view.requests if r.status == "open"),
        "nca_differ": tuple(_nca_differ(view)), "blq": tuple(_blq(view)), "be": tuple(_be(view, products))})


def _decisions(view: DataRoomView) -> list[DecisionLine]:
    out = []
    for d in view.decisions:
        left = d.on_inputs and not d.chosen
        pick = d.suggested if left else d.chosen
        label = next((o.label for o in d.options if o.id == pick), pick or "") if pick else ""
        out.append(DecisionLine(id=d.id, title=d.title, chosen=label, suggested=left or d.chosen == d.suggested,
                                waiting=not d.chosen and not left, reason=d.reason, why=d.why, by=d.by, at=d.at,
                                on_inputs=left))
    return out


def _chosen_set(view: DataRoomView, study: RoomStudy) -> str:
    made = next((d for d in view.decisions if d.id == f"analysis-set:{study.study_id}"), None)
    return (made.chosen or made.suggested) if made else "modeling"


def _arms(view: DataRoomView) -> list[ArmLine]:
    out = []
    for study in view.studies:
        sid = study.study_id
        fact = {key: next((v for v in study.facts if v.key.startswith(key)), None)
                for key in ("study.route", "study.dose", "study.population", "study.sex")}
        population = next((r for r in view.inputs if r.block == "individual" and r.owner == sid and r.name == "Population"), None)
        for arm in study.arms:
            owner = f"{sid} · {arm.treatment}"
            food = next((r for r in view.inputs if r.block == "protocol" and r.name == "Food state" and r.owner in (owner, sid)
                         and r.value in ("fed", "fasted")), None)
            row = next((p for p in view.plan if p.observed.startswith(f"{sid} ") and f" {arm.treatment} (N" in p.observed), None)
            out.append(ArmLine(
                study=sid, treatment=arm.treatment, study_id=f"{sid}-{arm.treatment}", product=arm.product,
                product_role=arm.role, plan_role=row.role if row else "", plan_why=row.why if row else "",
                route=_stated(fact["study.route"]), dose=_stated(fact["study.dose"]),
                food=StatedLine(text=str(food.value), value=food.value,
                                cites=tuple(c for chip in food.sources if (c := _cite(chip)) is not None)) if food else None,
                population=_stated(fact["study.population"]), sex=_stated(fact["study.sex"]),
                population_db=str(population.value) if population and population.value else ""))
    return out


def _nca_differ(view: DataRoomView) -> list[str]:
    out = []
    for study in view.studies:
        rep = study.nca_reproduction
        if rep is None or not rep.differ:
            continue
        which = [f"subject {n.subject}" + (f" period {n.period}" if n.period else "") + f" {metric}"
                 for n in study.nca for metric, tier in n.tiers.items() if tier == "differ"]
        listed = "; ".join(which[:6]) + (f"; and {len(which) - 6} more" if len(which) > 6 else "")
        out.append(f"{study.study_id}: {rep.differ} of the client's {rep.compared} NCA values are not reproduced by the "
                   f"Data room's NCA under any setting tried ({listed}); the data differ from the client's and the client "
                   f"is asked why" + (f" (tiers: {rep.tiers})" if rep.tiers else ""))
    return out


def _blq(view: DataRoomView) -> list[str]:
    out = []
    for study in view.studies:
        chosen = _chosen_set(view, study)
        profiles = [p for p in study.profiles if p.analysis_set == chosen]
        if not profiles:
            continue
        counted = sum(pt.n_blq for p in profiles for pt in p.points)
        label = next((s.label for s in study.sets if s.name == chosen), chosen)
        lloq = f" ({study.lloq:g} {study.concentration_unit})".rstrip() if study.lloq is not None else ""
        out.append(f"{study.study_id}: the observed arithmetic mean profiles sent to the model count a concentration below "
                   f"the LLOQ{lloq} as 0 ({counted} such {'value' if counted == 1 else 'values'} in the "
                   f"{label.lower()}); the geometric means leave them out")
    return out


def _paired(study: RoomStudy, subjects: set[str], test: str, reference: str, metric: str) -> tuple[list[float], list[float]]:
    """Each subject's test and reference value of `metric` (a replicate's occasions as their geometric mean)."""
    def per_subject(trt: str) -> dict[str, float]:
        logs: dict[str, list[float]] = {}
        for n in study.nca:
            value = getattr(n, metric)
            if n.treatment == trt and n.subject in subjects and isinstance(value, float) and value > 0 and math.isfinite(value):
                logs.setdefault(n.subject, []).append(math.log(value))
        return {s: math.exp(sum(v) / len(v)) for s, v in logs.items()}

    t, r = per_subject(test), per_subject(reference)
    both = sorted(set(t) & set(r))
    return [t[s] for s in both], [r[s] for s in both]


def _be(view: DataRoomView, products: tuple[ProductLine, ...]) -> list[BeSummary]:
    from pbpk_domain.bioequivalence import paired_crossover_ci
    from pbpk_domain.vbe import between_subject_cv

    roles = {p.name: p.role for p in products}
    out = []
    for study in view.studies:
        tests = [a for a in study.arms if roles.get(a.product, a.role) in TEST_ROLES]
        refs = [a for a in study.arms if roles.get(a.product, a.role) in REFERENCE_ROLES]
        stated = tuple(s for v in study.facts if v.key.startswith("study.be_result") and (s := _stated(v)) is not None)
        if not (tests and refs):
            continue
        test, ref = tests[0], refs[0]
        chosen = _chosen_set(view, study)
        members = set(next((s.subjects for s in study.sets if s.name == chosen), ()))
        metrics = []
        for name, field in BE_METRICS.items():
            t, r = _paired(study, members, test.treatment, ref.treatment, field)
            if len(t) < 2:
                metrics.append(BeMetric(metric=name, n=len(t)))
                continue
            ci = paired_crossover_ci(t, r)
            metrics.append(BeMetric(metric=name, gmr=round(ci.geometric_mean_ratio, 4), ci_low=round(ci.ci_lower, 4),
                                    ci_high=round(ci.ci_upper, 4), n=ci.n,
                                    between_subject_cv_percent=round(between_subject_cv(r), 1) if len(r) > 1 else None))
        label = next((s.label for s in study.sets if s.name == chosen), chosen)
        source = (f"{SOURCE}: study {study.study_id}, {test.product or test.treatment} (arm {test.treatment}) against "
                  f"{ref.product or ref.treatment} (arm {ref.treatment}), paired by subject in the {label.lower()}, from the "
                  "room's own NCA of the delivered concentrations (AUC_inf linear-up/log-down, Cmax observed); GMR: the "
                  "paired geometric mean ratio; CV: the reference arm's between-subject CV, as the F-304 gate computes it")
        out.append(BeSummary(study=study.study_id, test=test.product, reference=ref.product, analysis_set=chosen,
                             metrics=tuple(metrics), source=source, stated=stated))
    return out


__all__ = ["BE_METRICS", "ROOM_TO_BRIEF", "ArmLine", "BeMetric", "BeSummary", "DecisionLine", "ProductLine", "RequestLine",
           "RoomBasis", "RoomCite", "StatedLine", "basis_from_view", "brief_codes", "room_basis"]
