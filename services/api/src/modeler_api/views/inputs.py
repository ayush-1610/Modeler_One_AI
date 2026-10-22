"""Answers of `inputs_api`: the Inputs step (redesign §3.2) — the CPF assembled from the evidence not excluded, one row
per model input with its sources, one row per study, readiness and what is still missing to run."""

from __future__ import annotations

from typing import Any, Literal

from modeler_api.views.common import Number, VersionView, View

InputsTab = Literal["compound", "formulations", "individuals", "settings", "studies"]


class EvidenceView(View):
    """An evidence item as the page shows it (`inputs.evidence_view`): the value in both units, its source and grade."""

    id: str
    target: str
    value: Number | str | None
    unit: str | None
    value_pksim: Number | None
    unit_pksim: str | None
    state: str
    confidence: str
    flags: list[str]
    provider: str
    source_type: str
    conditions: dict[str, Any]
    source: dict[str, Any]
    quote: str
    extraction: str                   # TEXT, TABLE, FIGURE_DIGITIZED or CELL (a client template read by code)
    proposed_by: str                  # who supplied it: "agent:<run>", a person's id, or the system reading a file
    decided_by: str | None            # who last accepted, corrected or excluded it


class AlternativeView(EvidenceView):
    """A source the selection did not keep (D-32): how far it stands from the kept value."""

    relation: Literal["agrees", "differs", "conflicts"]
    differs_pct: Number | None


class CompoundRow(View):
    """One model input (`inputs_view.compound_rows`): kept, in conflict, held for a check, or missing."""

    id: str
    tab: InputsTab
    state: Literal["kept", "conflict", "held", "missing"]
    req_id: str | None                            # the data-checklist item a value typed into the row is filed under
    value: Number | str | None
    unit: str | None
    status: str | None
    placement: str | None
    binding: dict[str, str | None] | None
    candidates: list[str]
    sources: list[EvidenceView]                   # the kept value's source first, then the sources that agree
    alternatives: list[AlternativeView]
    message: str | None


class InputStudyRow(View):
    """One study (`inputs_view.study_rows`): its facts without observed values, proposed role, blinding, demographics."""

    study_id: str
    dataset_id: str | None
    origin: str | None
    purpose: str | None
    evaluable: bool
    facts: dict[str, Any]
    role: str | None
    role_source: Literal["proposed", "plan"]
    blinded: bool
    excluded: str | None
    demographics: Literal["entered", "published", "default", "missing"]
    regimen_missing: bool


class CpfVersion(VersionView):
    """The assembled CPF's version, and the assembly report (what came from which evidence)."""

    assembly: dict[str, Any]


class PublishedModel(View):
    """A published OSP model of the project's drug, which the Inputs step can take as a source."""

    id: str
    name: str


class InputsPage(View):
    cpf: CpfVersion | None
    records: list[dict[str, Any]]          # each CPF parameter record, with its block, placement and binding candidates
    catalog: VersionView | None            # the study catalog, external values withheld until the MAP is signed (D-15)
    readiness: VersionView | None
    choices: dict[str, Any]                # modeler_project.inputs.InputChoices
    todo: list[dict[str, Any]]             # what stands between the inputs and readiness, by kind and tab (inputs.todo)
    compound: list[CompoundRow]            # every model input on its tab
    studies: list[InputStudyRow]
    study_options: dict[str, list[str]]    # route, formulation, food state, purpose, sex, PK-Sim population (harvested)
    selection_rule: str                    # the source-selection rule that picked the values (D-32), with its status
    published_models: list[PublishedModel]  # the published OSP models of the drug, a source like any other


class IdentityProposal(InputsPage):
    """The structure proposed as evidence (its id), and the page."""

    evidence: str
