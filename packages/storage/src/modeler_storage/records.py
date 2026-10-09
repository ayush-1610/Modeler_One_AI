"""The read-model records several processes share (phase 9, rule B2: a typed contract at a process edge).

A record is what is stored in the per-tenant JSON documents (`filestore`) and what the read API answers with. Its
writers build it through the model, so a key added or renamed on one side fails on that side's tests, not in the
browser. Keys keep the names they have on disk (the web's camelCase included): the shapes are typed as they are.

- `ProjectRecord` (`projects.json`): written by the API (create project, project start, the model system, blinding);
  read by the API and by the orchestrator, which reads `exploratory` before an S4/S5 gate is signed.
- `ProposalRecord` (`proposals.json`): an agent's parameter proposal awaiting a curator (the review inbox).
"""

from __future__ import annotations

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
