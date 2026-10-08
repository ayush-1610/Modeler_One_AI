"""P4 answers of `inputs_api`: the model inputs page (the CPF assembled from accepted evidence, the studies, readiness)."""

from __future__ import annotations

from typing import Any

from modeler_api.views.common import StoredContent, VersionView, View


class CpfVersion(VersionView):
    """The assembled CPF's version, and the assembly report (what came from which evidence)."""

    assembly: dict[str, Any]


class InputsPage(View):
    cpf: CpfVersion | None
    records: list[dict[str, Any]]          # each CPF parameter record, with its block, placement and binding candidates
    catalog: VersionView | None            # the study catalog, external values withheld until the MAP is signed (D-15)
    readiness: VersionView | None
    choices: dict[str, Any]                # modeler_project.inputs.InputChoices
    published: StoredContent | None        # the hand-off record to the campaign path
    todo: list[dict[str, Any]]             # what stands between the inputs and readiness, by kind (inputs.todo)


class IdentityProposal(InputsPage):
    """The structure proposed as evidence (its id), and the page."""

    evidence: str
