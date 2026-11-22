"""Send to the model (plan 2026-11-21 v2 §4, §5 step 9): the Data room's confirmed inputs land in the stores the rest of
the platform reads, each with its source, so Review & sign, Run and the reports work unchanged.

- every compound input with a value (CPF id) and each product's release (form.<name>.type Weibull and its t50, shape
  and lag, fitted by code to the chosen profile) become evidence items, proposed and accepted under the publication;
- every study arm's mean profile in the chosen analysis set becomes an observed dataset (arithmetic mean ± SD and the
  geometric mean, N per time), its study record the arm's design, dose, water, meals and individual.

`plan_publication` builds and checks everything and writes nothing; `publish` writes it, idempotently (an item already
published with the same content is skipped). Nothing is published while a decision it depends on waits or an input it
needs is Missing: the plan lists what blocks it.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict

from modeler_project.dataroom.model import Chip, DataRoomView, InputRow, StudyView
from modeler_project.datasets import ObservedDataset, Origin, Series, check_dataset
from modeler_project.evidence import EvidenceItem, EvidenceState, Extraction, SourceRef, SourceType
from modeler_project.workspace import Workspace


class Publication(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence: tuple[EvidenceItem, ...] = ()
    datasets: tuple[ObservedDataset, ...] = ()
    blocked: tuple[str, ...] = ()         # what keeps the publication from being sent, in words


def _id(prefix: str, *parts: Any) -> str:
    return f"{prefix}-dr{hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:10]}"


def _source(chips: tuple[Chip, ...]) -> tuple[SourceRef, str, Extraction]:
    if not chips:
        return SourceRef(), "", Extraction.COMPUTED
    c = chips[0]
    page = int(c.part[1:]) if re.fullmatch(r"p\d+", c.part) else None
    locator = c.ref or f"{c.part} line {c.line}" + (f" cell {c.cell}" if c.cell else "")
    kind = Extraction.CELL if c.ref else (Extraction.TABLE if c.cell else Extraction.TEXT)
    return SourceRef(doc_sha256=c.sha256 or None, page=page, locator=locator, title=c.file), c.text, kind


def slug(name: str) -> str:
    """A product's CPF formulation name: its words joined ("Exampleamide 100 mg (test)" -> Exampleamide_100_mg_test)."""
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")[:60] or "product"


def _evidence(row: InputRow, target: str, value: float | str, *, by: str, note: str) -> EvidenceItem:
    source, quote, kind = _source(row.sources)
    computed = row.status == "calculated"
    return EvidenceItem(
        id=_id("ev", target, value, row.unit, [c.model_dump() for c in row.sources]), target=target, value=value,
        unit=row.unit or None, source_type=SourceType.CLIENT_REPORT if row.sources else SourceType.PREDICTED,
        source=source, quote=quote, extraction=Extraction.COMPUTED if computed else kind, provider="CLIENT",
        purpose="model_building", proposed_by=by, note=note)


def _dataset(view: StudyView, treatment: str, set_name: str, *, rows: list[InputRow], by: str,
             formulation_name: str | None) -> tuple[ObservedDataset | None, str]:
    owner = f"{view.study_id} · {treatment}"
    profile = next((p for p in view.profiles if p.treatment == treatment and p.analysis_set == set_name), None)
    if profile is None or profile.n_subjects == 0:
        return None, f"{owner}: no subject of the chosen set has this arm's profile"
    get = {r.name: r for r in rows if r.owner in (view.study_id, owner)}
    dose = get.get("InputDose")
    if dose is None or not isinstance(dose.value, float):
        return None, f"{owner}: the dose is missing"
    food = get.get("Food state")
    if food is None or food.value not in ("fed", "fasted"):
        return None, f"{view.study_id}: the study does not say fed or fasted"
    population, sex = get.get("Population"), get.get("Gender")
    age, weight, height = get.get("Age"), get.get("Weight"), get.get("Height")
    demographics: dict[str, Any] | None = None
    if population and population.value and age and isinstance(age.value, float):
        if not sex or sex.value not in ("MALE", "FEMALE"):
            return None, f"{view.study_id}: the individual's sex is not known"
        demographics = {"population": population.value, "sex": sex.value, "age_years": age.value}
        if weight and isinstance(weight.value, float):
            demographics["weight_kg"] = weight.value
        if height and isinstance(height.value, float):
            demographics["height_cm"] = height.value
    water = get.get("Volume of water/body weight")
    meals = []
    for r in rows:
        if r.block == "event" and r.owner == view.study_id:
            if r.value is None:
                return None, f"{view.study_id}: its meal times could not be read ({r.note})"
            for t in re.findall(r"-?\d+(?:\.\d+)?", str(r.value)):
                meals.append({"time_h": float(t), "template": r.name, "name": r.name.split(": ", 1)[-1]})
    points = profile.points
    times = tuple(p.time_h for p in points)
    arith = tuple(None if (p.mean is None or (p.n_geo == 0 and p.mean == 0)) else p.mean for p in points)
    n = profile.n_subjects
    study = {"study_id": f"{view.study_id}-{treatment}", "n": n, "design": "SD",
             "crossover": len(view.periods) > 1, "route": "oral", "dose_mg": dose.value,
             "formulation": "ir_tablet" if formulation_name else "solution", "formulation_name": formulation_name,
             "food_state": food.value, "meals": meals,
             "water_ml_per_kg": water.value if water and isinstance(water.value, float) else None,
             "demographics": demographics, "statistic": "mean_sd", "n_timepoints": len(times)}
    if view.lloq is not None:
        study["lloq"] = view.lloq
    series = (Series(name="arithmetic mean", statistic="arithmetic_mean", times=times, values=arith,
                     error=tuple(p.sd for p in points), error_kind="SD", n=n,
                     n_at=tuple(p.n for p in points) if len({p.n for p in points}) > 1 else None),
              Series(name="geometric mean", statistic="geometric_mean", times=times, values=tuple(p.geomean for p in points),
                     n=n, n_at=tuple(p.n_geo for p in points) if len({p.n_geo for p in points}) > 1 else None))
    unit = view.concentration_unit.replace("mL", "ml").replace("L", "l")
    label = next((s.label for s in view.sets if s.name == set_name), set_name)
    dataset = ObservedDataset(
        id=_id("ds", view.study_id, treatment, set_name, times, arith), kind="profile", study=study, time_unit="h", unit=unit,
        series=series, origin=Origin.CLIENT, extraction="TABLE", provider="CLIENT", purpose="model_building",
        proposed_by=by, demographics_choice="entered" if demographics else None,
        note=f"Data room: the mean of the {label.lower()} ({n} subjects in this arm); below the LLOQ counted 0 in the "
             "arithmetic mean and left out of the geometric mean")
    try:
        return check_dataset(dataset), ""
    except ValueError as exc:
        return None, f"{owner}: {exc}"


_BLOCKING_STUDY = ("TIME_UNIT_NOT_STATED", "UNIT_NOT_STATED", "SAMPLE_CONFLICT", "NO_CONCENTRATIONS")


def plan_publication(view: DataRoomView, *, by: str) -> Publication:
    blocked: list[str] = []
    waiting = [d.title for d in view.decisions if not d.chosen]
    if waiting:
        blocked.append("decisions waiting: " + "; ".join(waiting))
    if not view.question_confirmed:
        blocked.append("the question card is not confirmed")
    rows = list(view.inputs)
    evidence: list[EvidenceItem] = []
    for row in rows:
        if row.block != "compound":
            continue
        if row.status == "conflict":
            blocked.append(f"{row.label}: the sources disagree; choose one (enter it) before sending")
        elif row.value is not None and row.status != "missing":
            if not isinstance(row.value, float):
                blocked.append(f"{row.label}: {row.value!r} is not one number")
            else:
                evidence.append(_evidence(row, row.name, row.value, by=by, note=f"Data room: {row.label}"))
    names = {r.name for r in rows if r.block == "compound" and r.value is not None}
    if "phys.solubility.ref" in names and "phys.solubility.ref_ph" not in names:
        blocked.append("the reference solubility has no pH: choose a solubility with its pH, or enter the pH")
    chosen = {d.id: d.chosen or d.suggested for d in view.decisions}
    formulations: dict[str, str] = {}
    for row in rows:
        if row.block != "formulation":
            continue
        name = slug(row.owner)
        if row.name == "Formulation_Tablet_Weibull":
            if chosen.get(f"release-model:{row.owner}") == "particles":
                blocked.append(f"{row.owner}: particle dissolution needs the particle size and solubility entered as "
                               "inputs; send it with the Weibull release, or enter them")
                continue
            fitted = [r for r in rows if r.block == "formulation" and r.owner == row.owner and r.name in (
                "Dissolution time (50% dissolved)", "Dissolution shape") and isinstance(r.value, float)]
            if len(fitted) < 2:
                blocked.append(f"{row.owner}: its Weibull fit did not give t50 and shape (too few time points)")
                continue
            formulations[row.owner] = name
            evidence.append(_evidence(row, f"form.{name}.type", "Weibull", by=by, note=f"Data room: {row.owner}"))
            continue
        key = {"Dissolution time (50% dissolved)": "t50", "Dissolution shape": "shape", "Lag time": "lag"}.get(row.name)
        if key and isinstance(row.value, float) and row.owner in formulations:
            evidence.append(_evidence(row, f"form.{name}.weibull.{key}", row.value, by=by, note=f"Data room: {row.note}"))
    from modeler_project.evidence import assess

    for item in evidence:
        flags = assess(item).flags
        if item.unit and any(f.startswith("needs_conversion") for f in flags):
            blocked.append(f"{item.target}: {item.value} {item.unit} cannot be converted to PK-Sim's unit; enter it in "
                           "PK-Sim's unit")
    datasets: list[ObservedDataset] = []
    for study in view.studies:
        bad = [p.message for p in study.problems if p.code in _BLOCKING_STUDY]
        if bad:
            blocked.append(f"{study.study_id}: " + "; ".join(bad))
            continue
        set_name = chosen.get(f"analysis-set:{study.study_id}", "modeling")
        arm_codes = {a.treatment for a in study.arms}
        treatments = {p.treatment for p in study.profiles}
        if treatments - arm_codes:
            blocked.append(f"{study.study_id}: what treatment {', '.join(sorted(treatments - arm_codes))} stands for is not "
                           "given (its product is unknown)")
        for arm in study.arms:
            if arm.treatment not in treatments:
                continue
            if not arm.product:
                blocked.append(f"{study.study_id} arm {arm.treatment}: its product is not known ({arm.meaning or 'no meaning given'})")
                continue
            if arm.product not in formulations:
                blocked.append(f"{study.study_id} arm {arm.treatment}: {arm.product} has no release input (no dissolution "
                               "profile of it was read); its data request asks for one")
                continue
            got, why = _dataset(study, arm.treatment, set_name, rows=rows, by=by, formulation_name=formulations[arm.product])
            if got is None:
                blocked.append(why)
            else:
                datasets.append(got)
    return Publication(evidence=tuple(evidence), datasets=tuple(datasets), blocked=tuple(dict.fromkeys(blocked)))


def publish(ws: Workspace, view: DataRoomView, *, by: str, reason: str) -> dict[str, int]:
    """Write the publication (refused while anything blocks it); idempotent."""
    from modeler_project import dataset_register, evidence_register

    plan = plan_publication(view, by=by)
    if plan.blocked:
        raise ValueError("not sent to the model: " + " · ".join(plan.blocked))
    written = {"evidence": 0, "datasets": 0, "skipped": 0}
    for item in plan.evidence:
        from modeler_project.artifacts import ArtifactKind

        if ws.latest(ArtifactKind.EVIDENCE, item.id) is not None:
            written["skipped"] += 1
            continue
        proposed = evidence_register.propose(ws, item, actor=by, value_in_quote=bool(item.quote) or None)
        # a value with no unit (a pH, a shape factor) is its own PK-Sim value: the person sending it accepts it as such;
        # a value whose unit code cannot convert was refused by the plan
        unitless = proposed.value_pksim is None and isinstance(item.value, int | float) and not item.unit
        evidence_register.decide(ws, item.id, state=EvidenceState.ACCEPTED, reason=f"sent from the Data room: {reason}", by=by,
                                 value_pksim=float(item.value) if unitless else None)  # type: ignore[arg-type]
        written["evidence"] += 1
    for dataset in plan.datasets:
        if dataset_register.dataset(ws, dataset.id) is not None:
            written["skipped"] += 1
            continue
        dataset_register.propose_dataset(ws, dataset, actor=by)
        dataset_register.decide_dataset(ws, dataset.id, state=EvidenceState.ACCEPTED, reason=f"sent from the Data room: {reason}",
                                        by=by)
        written["datasets"] += 1
    return written
