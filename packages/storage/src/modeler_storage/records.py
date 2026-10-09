"""The read-model records several processes share (phase 9, rule B2: a typed contract at a process edge).

A record is what is stored in the per-tenant JSON documents (`filestore`) and what the read API answers with. Its
writers build it through the model, so a key added or renamed on one side fails on that side's tests, not in the
browser. Keys keep the names they have on disk (the web's camelCase included): the shapes are typed as they are.

- `ProjectRecord` (`projects.json`): written by the API (create project, project start, the model system, blinding);
  read by the API and by the orchestrator, which reads `exploratory` before an S4/S5 gate is signed.
- `ProposalRecord` (`proposals.json`): an agent's parameter proposal awaiting a curator (the review inbox).
- `CampaignRecord` (`campaigns.json`): the campaign monitor, written by the orchestrator's runner as a campaign runs;
  read by the API (the monitor, the package) and by the runner when it resumes after a decision.
- `EscalationRecord` (`escalations.json`): a stage waiting on a signed decision, written by the runner.

The monitor's science blocks (the goodness-of-fit series, the S6 prediction, the S7 package record, the ledger, the
influence map, the S5 diagnosis and the feedback decisions) stay open objects here: each is its own module's document,
and gets a model there. Keys added to the monitor over time have defaults, so a record from an earlier build reads.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Record(BaseModel):
    """A stored record: every key declared, nothing added or coerced."""

    model_config = ConfigDict(extra="forbid")


class QuestionRecord(Record):
    """A question of interest the project answers."""

    id: str
    question: str
    application: str
    modelRisk: str | None
    stage: str
    failingCriteria: int


class BlindingChoice(Record):
    """The MIDD lead's blinding choice for the project (D-15), with its reason."""

    on: bool
    reason: str
    by: str
    at: str


class ProjectRecord(Record):
    id: str
    name: str
    compounds: list[str]
    openQuestions: int
    risk: str
    questions: list[QuestionRecord] = Field(default_factory=list)
    # a project that may sign verdicts judged on synthetic or illustrative data, labelled TEST ONLY (plan §9.4, D-19)
    exploratory: bool = False
    # a project started from its documents (P0–P6), not from the guided wizard
    pipeline: bool = False
    blinding: BlindingChoice | None = None

    def stored(self) -> dict[str, object]:
        """The record as stored: only the keys its writer set."""
        return self.model_dump(mode="json", exclude_unset=True)


class ProposalRecord(Record):
    id: str
    parameterId: str
    value: str
    unit: str | None
    quote: str
    reference: str
    agent: str


# --- the campaign monitor (the orchestrator writes it, the API answers with it) ---------------------------------

Number = int | float


class RealDataSummary(Record):
    """What a round's verdict rests on (`pbpk_domain.data_origin.real_data_summary`, plan §9.4)."""

    judged: int
    real: int
    byOrigin: dict[str, int]
    notReal: list[str]
    notEvaluable: list[str]
    passable: bool
    label: str


class RoundRecord(Record):
    round: int
    action: str
    aucGmfe: Number | None
    cmaxGmfe: Number | None
    verdict: str
    studies: list[dict[str, Any]] = Field(default_factory=list)   # per-study metrics (the gate's own documents)
    groups: list[dict[str, Any]] = Field(default_factory=list)
    vpc: dict[str, Any] = Field(default_factory=dict)
    findings: list[str] = Field(default_factory=list)
    realData: RealDataSummary | None = None
    modelSet: dict[str, Any] | None = None    # the parameter set, engine and scenarios the verdict judged (§12.3 N1)
    cycle: int = 1


class StageRecord(Record):
    stage: str
    label: str
    status: str                               # PENDING | RUNNING | PASSED | ACCEPTED | SKIPPED | ESCALATED | …
    rounds: list[RoundRecord]
    notes: list[str] = Field(default_factory=list)


class EngineIdentity(Record):
    """What produced the numbers: real PK-Sim, a software fixture, or an injected engine (never read as PBPK)."""

    kind: str
    command: str


class CampaignRecord(Record):
    id: str
    project: str
    compound: str
    question: str
    modelRisk: str
    budgetSeconds: int
    elapsedSeconds: int
    currentStage: str
    status: str
    stages: list[StageRecord]
    gof: list[dict[str, Any]] = Field(default_factory=list)
    gofByStage: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    prediction: dict[str, Any] | None = None
    package: dict[str, Any] | None = None
    engine: EngineIdentity | None = None
    observedOrigins: dict[str, str | None] = Field(default_factory=dict)
    realData: dict[str, RealDataSummary] = Field(default_factory=dict)
    ledger: dict[str, Any] | None = None
    influence: dict[str, Any] | None = None
    cycle: int = 1
    feedback: list[dict[str, Any]] = Field(default_factory=list)
    feedbackPending: dict[str, Any] | None = None
    resume: dict[str, Any] | None = None      # how the runner continues after a decision (its own document)

    def stored(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude_unset=True)


class EscalationOption(Record):
    id: str
    label: str
    requiresSignature: bool
    disabled: str | None = None               # why the decision is not open (the S5 learn cap, no study left)


class EscalationRecord(Record):
    id: str
    campaignId: str
    stage: str
    reasonCode: str
    evidence: str
    options: list[EscalationOption]
    feedback: dict[str, Any] | None = None    # the S5 failure's diagnosis (`modeler_orchestrator.feedback.diagnose`)

    def stored(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude_unset=True)
