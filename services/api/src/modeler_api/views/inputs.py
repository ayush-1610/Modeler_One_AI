"""Answers of `inputs_api`: the Inputs step (redesign §3.2) — the CPF assembled from the evidence not excluded, one row
per model input with its sources, one row per study, readiness and what is still missing to run."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

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
    # the unit PK-Sim holds a value of its target in, for a value typed there by hand when the stated unit does not
    # convert (`inputs.pksim_unit`): "" no unit (dimensionless, a fraction); None not named (a placeholder such as "elim",
    # a template, an id the model does not place: filed under a concrete parameter first)
    pksim_unit: str | None


class AlternativeView(EvidenceView):
    """A source the selection did not keep (D-32): how far it stands from the kept value."""

    relation: Literal["agrees", "differs", "conflicts"]
    differs_pct: Number | None


class CompoundRow(View):
    """One model input (`inputs_view.compound_rows`): kept, in conflict, held for a check, missing (S0 needs it), or
    empty (a model input the data plan owns with no value yet: a row to fill, not counted as missing)."""

    id: str
    tab: InputsTab
    state: Literal["kept", "conflict", "held", "missing", "empty"]
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
    allowed: list[str]                            # the only values PK-Sim takes for it, by its names (the binding
                                                  # partner's, `inputs.allowed_values`); empty: any value its kind takes


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
    # why its values are withheld, in words (the reason the evidence gives its datasets); None when they are not. Left out
    # where a study's row is listed without it (Review & sign's studies)
    blinded_why: str | None = None
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


class ReleaseModelOption(View):
    value: str
    label: str
    detail: str = ""


class ReleaseModelRow(View):
    """A formulation's release model chosen on Inputs (the owner's D1): the Data room's proposal waiting on a person,
    or the formulation held for particle dissolution (`release_choice.release_states`)."""

    formulation: str
    state: Literal["proposed", "held"]
    evidence_id: str
    value: str = ""                        # proposed: the room's suggestion ("weibull") with its label and detail
    label: str = ""
    detail: str = ""
    why: str = ""
    sources: list[str] = Field(default_factory=list)
    other: ReleaseModelOption | None = None
    reason: str = ""                       # held: why, and who held it
    by: str = ""


class InputsPage(View):
    cpf: CpfVersion | None
    records: list[dict[str, Any]]          # each CPF parameter record, with its block, placement and binding candidates
    catalog: VersionView | None            # the study catalog, external values withheld until the MAP is signed (D-15)
    readiness: VersionView | None
    choices: dict[str, Any]                # modeler_project.inputs.InputChoices
    todo: list[dict[str, Any]]             # what stands between the inputs and readiness, by kind and tab (inputs.todo)
    compound: list[CompoundRow]            # every model input on its tab
    studies: list[InputStudyRow]
    # route, formulation, food state, purpose, sex, PK-Sim population (harvested); for the client data's values, matrix
    # (the intake vocabulary's words) and analyte (the brief's parent drug, a label: the Delivery page's `analytes`
    # give an existing analyte's id)
    study_options: dict[str, list[str]]
    selection_rule: str                    # the source-selection rule that picked the values (D-32), with its status
    published_models: list[PublishedModel]  # the published OSP models of the drug, a source like any other
    release_models: list[ReleaseModelRow] = Field(default_factory=list)  # chosen here (D1): Formulations shows them


class IdentityProposal(InputsPage):
    """The structure proposed as evidence (its id), and the page."""

    evidence: str
