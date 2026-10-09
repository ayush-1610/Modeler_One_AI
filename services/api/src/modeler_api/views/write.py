"""Answers of `write_api`, the guided create-project flow: the stored studies, a model system, the campaign inputs
staged by `campaign:prepare` (phase 9c). A created project answers its record; a put CPF answers its view."""

from __future__ import annotations

from modeler_api.views.common import Number, View


class StudiesStored(View):
    stored: int
    total: int


class SystemView(View):
    """The project's model system as stored (`pbpk_domain.system`): compounds, roles, products, analytes."""

    name: str
    compounds: list[str]
    roles: dict[str, str]                       # compound -> parent | metabolite
    products: dict[str, dict[str, Number]]      # product -> {dosed compound: dose fraction}
    analytes: list[str]
    sha256: str


class StudyAssignment(View):
    study_id: str
    assignment: str


class CampaignInputs(View):
    """`campaign:prepare`: the staged CPF, MAP and observed PK a campaign starts from; a model system adds its own."""

    map_id: str
    compound: str
    cpf_uri: str
    cpf_sha256: str
    map_uri: str
    map_sha256: str
    observed_uri: str
    stages: list[str]
    tier: str
    studies: list[StudyAssignment]
    origins: dict[str, str | None]              # each study's observed-data origin (plan §9.4)
    not_evaluable: list[str]
    system_uri: str | None = None
    system_sha256: str | None = None
    model_system_sha256: str | None = None
    not_evaluated: list[str] | None = None
