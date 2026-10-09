"""Answers of `templates_api`: the new-project wizard's starting points (phase 9c)."""

from __future__ import annotations

from modeler_api.views.common import StoredContent, View


class TemplateSummary(View):
    id: str
    blank: bool
    name: str
    compound: str
    question: str
    model_risk: str
    real_data: bool
    description: str


class Templates(View):
    templates: list[TemplateSummary]


class TemplateContent(TemplateSummary):
    """A starting point in full. The CPF and the studies are the template's own documents, in the upload shapes they
    are sent back in (a reference model's CPF, the blank one's empty parameters; studies with their origin)."""

    cpf: StoredContent
    studies: list[StoredContent]
    skipped: list[str]
    notes: list[str]
    source: str
