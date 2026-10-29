"""The four steps of the redesigned flow, and where each stands (docs/plans/2026-10-19-p0-p5-redesign.md §3).

Start (P0 + P1), Inputs (P2 + P3 + P4), Review & sign (P5) and Run (P6). A step's state comes from what is filled
and what is missing, never from a phase approval (D-27: a person reviews everything once, at the MAP signature).
Run is read by the API from the runner's campaign store; the other three are read here from the workspace.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from modeler_project.artifacts import ArtifactKind, ArtifactStatus
from modeler_project.brief import (
    SHORT_BRIEF,
    START_REQUIRED,
    FieldStatus,
    ProjectBrief,
    definition_of,
    risk_check,
)
from modeler_project.feasibility import scope_gates
from modeler_project.map_artifact import latest_map
from modeler_project.workspace import Workspace
from pbpk_domain.acceptance import loosest_internal_target

MAIN = "main"

StepId = Literal["start", "inputs", "review", "run"]
StepState = Literal["done", "needs_you", "running", "not_started"]

STEP_LABELS: dict[str, str] = {"start": "Start", "inputs": "Inputs", "review": "Review & sign", "run": "Run"}


class Step(BaseModel):
    model_config = ConfigDict(frozen=True)

    step: StepId
    label: str
    state: StepState
    reasons: tuple[str, ...] = ()


def _step(step: StepId, state: StepState, *reasons: str) -> Step:
    return Step(step=step, label=STEP_LABELS[step], state=state, reasons=tuple(reasons))


class StartIssue(BaseModel):
    """One thing Start still needs, on the brief field it belongs to, so the screen marks that field (page review 1)."""

    model_config = ConfigDict(frozen=True)

    path: str
    message: str


def start_issues(brief: ProjectBrief) -> list[StartIssue]:
    """What Start still needs (redesign §3.1): the question and its applications, the model risk (ICH M15, never
    assumed) and an internal target no looser than its tier (MS-01 §8), the scope gates (D-28: anything the builder
    cannot model is refused here), and the open questions on the short brief. Proposal notes never hold Start up."""
    issues = [StartIssue(path=path, message=f"{definition_of(path).label}: not set yet") for path in START_REQUIRED
              if brief.value(path) in (None, "", []) and brief.get(path).status is not FieldStatus.NOT_APPLICABLE]
    issues += [StartIssue(path="acceptance.tier", message=m) for m in risk_check(brief).problems]
    target, tier = brief.value("acceptance.internal_target_pe"), brief.value("acceptance.tier")
    if target not in (None, "") and tier:
        widest = loosest_internal_target(str(tier))
        if not 0 < float(target) <= widest + 1e-9:
            issues.append(StartIssue(path="acceptance.internal_target_pe",
                                     message=f"Internal target: at most {widest:.1f} % at the {tier} tier (MS-01 §8: never "
                                             f"looser than the tier), {float(target):g} % given"))
    for gate in scope_gates(brief):
        if gate.state == "not_set":
            issues.append(StartIssue(path=gate.path, message=f"{gate.label}: not set yet"))
        elif gate.state == "not_supported":
            issues.append(StartIssue(path=gate.path, message=f"{gate.label}: {gate.message}"))
    short = set(SHORT_BRIEF)
    issues += [StartIssue(path=q.field, message=f"Open question on {definition_of(q.field).label}: {q.question}")
               for q in brief.questions if q.status == "open" and q.field in short]
    return issues


def start_problems(brief: ProjectBrief) -> list[str]:
    """`start_issues` as the step's reasons."""
    return [issue.message for issue in start_issues(brief)]


def start_step(ws: Workspace) -> Step:
    version = ws.latest(ArtifactKind.BRIEF, MAIN)
    if version is None:
        return _step("start", "not_started", "Start the project from its proposal")
    reasons = start_problems(ProjectBrief.from_content(version.content))
    return _step("start", "needs_you", *reasons) if reasons else _step("start", "done")


def inputs_step(ws: Workspace) -> Step:
    version = ws.latest(ArtifactKind.READINESS, MAIN)
    if version is None:
        return _step("inputs", "not_started", "The model inputs have not been put together yet")
    if ws.status(version) is ArtifactStatus.STALE:
        return _step("inputs", "needs_you", "The inputs changed since they were last checked: check them again")
    content = version.content
    if not content.get("ready"):
        failing = [c["check"] for c in content.get("checks", []) if not c.get("ok")]
        return _step("inputs", "needs_you", *(failing or ["The inputs are not ready to run"]))
    return _step("inputs", "done")


def review_step(ws: Workspace) -> Step:
    latest = latest_map(ws)
    if latest is not None:
        version, artifact = latest
        if artifact.signed and ws.status(version) is not ArtifactStatus.STALE:
            return _step("review", "done")
        if artifact.signed:
            return _step("review", "needs_you", "The plan changed after the MAP was signed: review and sign again")
    if ws.latest(ArtifactKind.MODEL_PLAN, MAIN) is not None or latest is not None:
        return _step("review", "needs_you", "Review the plan, then approve and sign the MAP")
    return _step("review", "not_started", "The plan is built once the inputs are ready")


def run_step(campaign_statuses: list[str]) -> Step:
    """Run, from the statuses of the project's campaigns in the runner's store."""
    if not campaign_statuses:
        return _step("run", "not_started", "A campaign starts once the MAP is signed")
    if any(s in ("ESCALATED", "AWAITING_SIGNATURE") for s in campaign_statuses):
        return _step("run", "needs_you", "A campaign is waiting for your decision")
    if any(s in ("QUEUED", "RUNNING") for s in campaign_statuses):
        return _step("run", "running")
    if any(s == "COMPLETED" for s in campaign_statuses):
        return _step("run", "done")
    return _step("run", "needs_you", "The last campaign stopped without completing: see its record")


def project_steps(ws: Workspace, campaign_statuses: list[str]) -> list[Step]:
    return [start_step(ws), inputs_step(ws), review_step(ws), run_step(campaign_statuses)]
