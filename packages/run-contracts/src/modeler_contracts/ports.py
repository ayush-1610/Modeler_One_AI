"""Ports: what one process needs from another, as interfaces (docs/ARCHITECTURE_BOUNDARIES.md, rule B4).

The API starts and steers single-node campaigns through `CampaignRunner`; the orchestrator implements it
(`modeler_orchestrator.campaign_runner.LocalCampaignRunner`) and the API obtains it in one seam module
(`modeler_api.execution`). Neither package imports the other's internals.

The orchestrator runs engine jobs through `EngineFactory` (phase 8c): the engine worker registers its implementation
under the `modeler.engines` entry point (`modeler_engine.runner:subprocess_engine`) and `engine_factory` loads it, so
the two packages on layer 5 never import each other.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Protocol

from modeler_contracts.runs import CampaignRequest, EngineJob, EngineManifest

ENGINE_ENTRY_POINTS = "modeler.engines"
EngineRun = Callable[[EngineJob], EngineManifest]


class CampaignRunner(Protocol):
    def start(self, request: CampaignRequest, *, read_root: str, project: str, question: str, model_risk: str) -> None:
        """Record the campaign (QUEUED) and run it in the background; the id is readable once this returns."""

    def gate_refusal(self, campaign: dict[str, Any], project: dict[str, Any] | None) -> str | None:
        """Why the S4/S5 evaluation of this campaign may not be signed (no real data outside an exploratory project)."""

    def check_feedback(self, campaign: dict[str, Any], stage: str, action: str, payload: dict[str, Any] | None) -> None:
        """A feedback decision's guardrails, checked before it is signed (ValueError: refused)."""

    def decision_digest(self, campaign_id: str, stage: str, action: str, payload: dict[str, Any] | None) -> str:
        """What a feedback signature binds: the decision and its content."""

    def resolve(self, *, read_root: str, tenant_id: str, campaign_id: str, stage: str, action: str,
                payload: dict[str, Any] | None, signature_id: str, printed_name: str, note: str) -> dict[str, Any]:
        """Apply a signed review-inbox decision (LookupError: no such escalation; ValueError: not allowed)."""


class EngineFactory(Protocol):
    def __call__(self, *, command: Sequence[str], engine_id: str, image_digest: str) -> EngineRun:
        """An engine that runs each job with `command` (`Rscript run_job.R`, a fixture) and records its identity."""


def engine_factory(name: str = "subprocess") -> EngineFactory:
    """The installed engine implementation registered as `name` under the `modeler.engines` entry point."""
    from importlib.metadata import entry_points

    found = entry_points(group=ENGINE_ENTRY_POINTS, name=name)
    if not found:
        raise LookupError(f"no engine {name!r} is installed (entry point group {ENGINE_ENTRY_POINTS!r}): "
                          "install modeler-engine-worker")
    return next(iter(found)).load()
