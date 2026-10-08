"""Observed datasets in the register: propose, decide, digitize, and which data-plan needs they meet (plan §9).

Datasets are DATASET artifacts (a new version per decision). A dataset from a figure is built here from the person's
axis calibration and picked pixels (`pbpk_domain.digitize`); its values are computed by code, never typed, and it is
usable only after the person approved the overlay of the computed points on the figure.
"""

from __future__ import annotations

from typing import Any

from modeler_project.artifacts import ArtifactKind
from modeler_project.datasets import (
    DatasetError,
    Digitization,
    ObservedDataset,
    Origin,
    Series,
    check_dataset,
    new_dataset_id,
)
from modeler_project.evidence import EvidenceState, SourceRef
from modeler_project.requirements import RequirementItem
from modeler_project.workspace import Workspace
from pbpk_domain.campaign.split import StudyClass, classify
from pbpk_domain.digitize import AxisCalibration, Calibration, digitize


def datasets(ws: Workspace) -> list[ObservedDataset]:
    return [ObservedDataset.from_content(v.content) for v in ws.list(ArtifactKind.DATASET)]


def dataset(ws: Workspace, dataset_id: str) -> ObservedDataset | None:
    version = ws.latest(ArtifactKind.DATASET, dataset_id)
    return ObservedDataset.from_content(version.content) if version is not None else None


def propose_dataset(ws: Workspace, dataset: ObservedDataset, *, actor: str, mol_weight: float | None = None) -> ObservedDataset:
    checked = check_dataset(dataset, mol_weight=mol_weight).model_copy(
        update={"state": EvidenceState.PROPOSED, "proposed_by": actor})
    if ws.latest(ArtifactKind.DATASET, checked.id) is not None:
        raise DatasetError(f"dataset {checked.id} already exists")
    ws.commit(ArtifactKind.DATASET, checked.id, checked.to_content(), actor=actor,
              reason=f"proposed {checked.study.get('study_id')} ({checked.origin.value.lower()})")
    return checked


def _latest(ws: Workspace, dataset_id: str) -> ObservedDataset:
    version = ws.latest(ArtifactKind.DATASET, dataset_id)
    if version is None:
        raise DatasetError(f"no dataset {dataset_id}")
    return ObservedDataset.from_content(version.content)


def decide_dataset(ws: Workspace, dataset_id: str, *, state: EvidenceState, reason: str, by: str) -> ObservedDataset:
    if not reason.strip():
        raise DatasetError("a decision needs a reason")
    dataset = _latest(ws, dataset_id)
    if state is EvidenceState.ACCEPTED and dataset.origin is Origin.FIGURE_DIGITIZED and not (
            dataset.digitization and dataset.digitization.overlay_approved_by):
        raise DatasetError("approve the overlay of the digitized points on the figure first")
    decided = dataset.model_copy(update={"state": state, "decided_by": by, "decision_reason": reason})
    ws.commit(ArtifactKind.DATASET, dataset_id, decided.to_content(), actor=by, reason=f"{state.value.lower()}: {reason}")
    return decided


def approve_overlay(ws: Workspace, dataset_id: str, *, by: str) -> ObservedDataset:
    dataset = _latest(ws, dataset_id)
    if dataset.digitization is None:
        raise DatasetError("this dataset was not digitized")
    digitization = dataset.digitization.model_copy(update={"overlay_approved_by": by})
    updated = check_dataset(dataset.model_copy(update={"digitization": digitization}))
    ws.commit(ArtifactKind.DATASET, dataset_id, updated.to_content(), actor=by,
              reason="overlay of the digitized points approved against the figure")
    return updated


def digitized_dataset(*, study: dict[str, Any], doc_sha256: str, page: int, locator: str, calibration: dict[str, Any],
                      pixels: dict[str, list[tuple[float, float]]], time_unit: str, unit: str,
                      statistic: str = "arithmetic_mean", n: int | None = None, source: SourceRef | None = None,
                      provider: str = "LITERATURE", purpose: str = "model_building") -> ObservedDataset:
    """Build a dataset from a person's axis calibration and picked points (series name → pixels)."""
    cal = Calibration(x=AxisCalibration(**calibration["x"]), y=AxisCalibration(**calibration["y"]))
    series = []
    worst = {"x": 0.0, "y": 0.0}
    for name, picked in pixels.items():
        points = digitize(cal, [tuple(p) for p in picked])
        series.append(Series(name=name, statistic=statistic, times=tuple(p.x for p in points),
                             values=tuple(p.y for p in points), n=n))
        for p in points:
            worst["x"], worst["y"] = max(worst["x"], p.dx), max(worst["y"], p.dy)
    ref = (source or SourceRef()).model_copy(update={"doc_sha256": doc_sha256, "page": page, "locator": locator})
    return ObservedDataset(
        id=new_dataset_id(), kind="profile", study=study, time_unit=time_unit, unit=unit, series=tuple(series),
        origin=Origin.FIGURE_DIGITIZED, extraction="FIGURE_DIGITIZED", source=ref,
        digitization=Digitization(page=page, calibration=calibration, pixels=pixels, resolution=worst),
        provider=provider, purpose=purpose)  # type: ignore[arg-type]


_CLASS_TARGETS = {
    "IV-SD": {StudyClass.IV_SD},
    "PO-SOL-FASTED / PO-IR-FASTED": {StudyClass.PO_SOL_FASTED, StudyClass.PO_IR_FASTED},
    "PO-FED": {StudyClass.PO_FED},
    "PO-MD": {StudyClass.PO_MD},
    "DDI": {StudyClass.DDI},
    "SPECIAL": {StudyClass.SPECIAL},
    "PRECLINICAL": {StudyClass.PRECLINICAL},
}


def dataset_matches(requirement: RequirementItem, dataset: ObservedDataset) -> bool:
    """Whether an accepted dataset meets a dataset need of the data plan (MS-01 §3.3 classes)."""
    if requirement.kind != "dataset":
        return False
    try:
        record = dataset.study_record()
    except ValueError:
        return False
    target = requirement.target
    if target in _CLASS_TARGETS:
        return classify(record) in _CLASS_TARGETS[target]
    if target == "EXTERNAL":
        return dataset.purpose == "external_validation"
    if target == "urine":
        return "urine" in record.matrices
    if target == "lloq":
        return record.lloq is not None
    if target == "BE study":
        return dataset.provider == "CLIENT" and dataset.purpose in ("external_validation", "application_verification")
    return False

