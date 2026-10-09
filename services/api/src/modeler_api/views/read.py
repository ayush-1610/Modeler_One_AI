"""Answers of `read_api` and `write_api` on the API-owned records: projects, a compound's CPF view, observed studies,
the review inbox's parameter proposals (phase 9c).

A project and a proposal are the read model's own records (`modeler_storage.records`), which their writers build
through; a study row is the upload's shape (`modeler_api.studies.StudyUpload`) as stored for the project.
"""

from __future__ import annotations

from pydantic import ConfigDict

from modeler_api.studies import ObservedProfile, StudyUpload
from modeler_api.views.common import Number, View
from modeler_storage.records import ProjectRecord, ProposalRecord


class Projects(View):
    projects: list[ProjectRecord]


class CpfParameterRow(View):
    id: str
    value: str | None                       # shown as entered (`str(value)`)
    unit: str | None
    status: str                             # lower case: fixed, fitted, predicted, missing …
    source: str
    reference: str
    fittableStages: list[str]


class CpfView(View):
    """`cpf_view.project_cpf_view`: the compound screen's parameter rows and the S0 completeness."""

    compound: str
    version: int
    completeness: Number
    ready: bool
    missing: list[str]
    parameters: list[CpfParameterRow]


class StudyRow(StudyUpload):
    """An observed study as stored for the project. D-15: a blinded external study comes without its profile."""

    model_config = ConfigDict(extra="forbid")

    project: str
    profile: ObservedProfile | None = None   # type: ignore[assignment]
    blinded: bool = False


class Studies(View):
    studies: list[StudyRow]


class Proposals(View):
    proposals: list[ProposalRecord]
