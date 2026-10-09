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


class SystemCompound(View):
    compound: str
    role: str                               # parent | metabolite
    has_cpf: bool


class SystemFormation(View):
    """A process of `compound` that forms `metabolite` (the published model's `Metabolite` link)."""

    compound: str
    metabolite: str
    process: str                            # internal name : molecule
    data_source: str


class SystemAnalyte(View):
    """What a study can measure, and where MS-01 v1.3 judges it (§6.5)."""

    name: str
    kind: str                               # compound | observer
    informs: list[str]                      # the compounds whose parameters its studies inform (none: not evaluated)
    judged_at: list[str]                    # the stages that gate it
    note: str = ""                          # why it is not evaluated, when it is not


class SystemDetail(View):
    name: str
    fitted: str                             # the parent a campaign's CPF is (the system's first parent)
    compounds: list[SystemCompound]
    formation: list[SystemFormation]
    products: dict[str, dict[str, Number]]  # product -> {dosed compound: dose fraction}
    analytes: list[SystemAnalyte]
    sha256: str | None                      # None until every compound has its CPF
    problem: str = ""                       # why the system cannot be assembled yet


class ProjectSystem(View):
    """`GET /projects/{id}/system`: the project's model system, or none for a single compound. `links` is the stored
    document a client edits and puts back (`PUT /projects/{id}/system`)."""

    system: SystemDetail | None
    links: dict[str, object] | None

