"""Payloads that cross process boundaries (API -> Temporal -> engine worker).

Plain dataclasses so Temporal's default JSON converter can serialize them and every service can
import them without pulling in web or scientific dependencies.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

RUN_TASKS = ("simulate", "dry_run", "convert_to_project", "pk_analysis", "population")


@dataclass
class EngineInput:
    name: str  # bare file name inside the job's inputs/ directory
    uri: str
    sha256: str


@dataclass
class EngineJob:
    job_id: str
    tenant_id: str
    task: str
    inputs: list[EngineInput]
    outputs_uri: str
    options: dict[str, Any] = field(default_factory=dict)
    timeout_s: int = 600


@dataclass
class OutputFile:
    name: str
    uri: str
    sha256: str
    size_bytes: int


@dataclass
class EngineManifest:
    job_id: str
    status: str
    engine_id: str
    image_digest: str
    started_at: str
    finished_at: str
    inputs: dict[str, str]
    outputs: list[OutputFile]
    warnings: list[str]
    engine_info: dict[str, Any]
    stderr_tail: str


@dataclass
class RunRequest:
    run_id: str
    tenant_id: str
    snapshot_uri: str
    snapshot_sha256: str
    task: str = "simulate"
    options: dict[str, Any] = field(default_factory=dict)
    resource_class: str = "s"
    timeout_s: int = 600


@dataclass
class PopulationRunRequest:
    run_id: str
    tenant_id: str
    snapshot_uri: str
    snapshot_sha256: str
    population_size: int
    seed: int
    chunk_size: int = 100
    options: dict[str, Any] = field(default_factory=dict)
    chunk_timeout_s: int = 3600


@dataclass
class RunOutcome:
    run_id: str
    status: str
    manifest: EngineManifest | None = None


@dataclass
class ReviewRequest:
    record_type: str
    record_id: str
    record_sha256: str
    required_meaning: str
    timeout_days: int = 14


@dataclass
class ReviewDecision:
    approved: bool
    signature_id: str | None = None
    comment: str = ""


@dataclass
class FitParameterBounds:
    name: str
    lower: float
    upper: float
    log_scale: bool = False


@dataclass
class FitRoundRequest:
    round_id: str
    tenant_id: str
    base_spec_uri: str  # PI spec without start values (simulations, parameters, output mappings, algorithm)
    base_spec_sha256: str
    parameters: list[FitParameterBounds]
    simulations_per_evaluation: int
    evaluations_per_start: int
    seconds_per_simulation: float  # from the engine benchmark on the target hardware
    cores: int
    budget_seconds: int = 3600
    reserved_seconds: int = 900  # validation runs, report generation, safety margin
    seed: int = 1
    model_inputs: list[EngineInput] = field(default_factory=list)  # .pkml files named in the base spec


@dataclass
class FitStartOutcome:
    start_index: int
    status: str  # SUCCEEDED | FAILED | CANCELLED_AT_DEADLINE
    estimates: dict[str, float] = field(default_factory=dict)
    objective: float | None = None
    converged: bool = False
    evaluations: int = 0
    manifest: EngineManifest | None = None


@dataclass
class FitRoundOutcome:
    round_id: str
    planned_starts: int
    starts: list[FitStartOutcome]
    acceptable: bool
    findings: list[str]
    best_start_index: int | None
    deadline_reached: bool


def derive_chunk_seed(run_seed: int, chunk_index: int) -> int:
    """Deterministic per-chunk seed; stays within a signed 32-bit int for R and PK-Sim."""
    digest = hashlib.sha256(f"{run_seed}:{chunk_index}".encode()).digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFFFFFF
