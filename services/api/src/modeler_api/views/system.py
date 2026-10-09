"""Answers of the system routes and the run results (phase 9d): health, the snapshot preview, M15 validation, a run
submitted, and an ingested run's outputs."""

from __future__ import annotations

from modeler_api.views.common import Number, StoredContent, View


class Health(View):
    status: str


class SnapshotPreview(View):
    """A built and validated PK-Sim snapshot, not persisted; the snapshot is PK-Sim's own JSON."""

    snapshot_sha256: str
    snapshot_version: int
    snapshot: StoredContent


class M15Issue(View):
    code: str
    location: str
    message: str


class M15Validation(View):
    complete: bool
    allowed_model_risk: list[str] | None
    issues: list[M15Issue]


class RunAccepted(View):
    run_id: str
    status: str
    status_url: str


class RunOutputs(View):
    run_id: str
    output_paths: list[str]


class SeriesPoint(View):
    time: Number
    value: Number


class RunSeries(View):
    run_id: str
    path: str
    individual_id: int
    series: list[SeriesPoint]
