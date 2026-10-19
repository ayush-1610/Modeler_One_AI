"""Each study's role before Review & sign (redesign §3.2, the Studies tab): proposed by the MS-01 split, shown read-only.

The role is the one the plan's default would give (`plan.build_default`): the stage an internal study trains (S1–S3),
S5 for an external study S5 judges, S6 for one that verifies an application, or supportive. Once a plan exists its
placements are the roles, and they change only there, with a reason (Step 3). Blinding follows the S5 role from the
moment a study is read (D-33).
"""

from __future__ import annotations

from modeler_project.artifacts import ArtifactKind
from modeler_project.brief import ProjectBrief
from modeler_project.workspace import Workspace


def proposed_roles(ws: Workspace) -> dict[str, str]:
    """study id -> S1 | S2 | S3 | S5 | S6 | SUPPORTIVE, from the plan when there is one, else from the MS-01 split of
    the current study catalog ({} before the inputs are first assembled)."""
    from modeler_project.inputs import catalog_rows, current_cpf
    from modeler_project.plan import _question, _records, _role, current, structure_from_brief
    from pbpk_domain.campaign.map import training_stages
    from pbpk_domain.campaign.split import split_studies
    from pbpk_domain.cpf.models import CPF

    _version, plan = current(ws)
    if plan is not None:
        return {sid: p.role for sid, p in plan.placements.items()}
    rows = catalog_rows(ws)
    if not rows:
        return {}
    brief_version = ws.latest(ArtifactKind.BRIEF, "main")
    brief = ProjectBrief.from_content(brief_version.content) if brief_version else None
    cpf = current_cpf(ws) or CPF(compound=brief.drug_name if brief else "compound", parameters=())
    records = _records(rows)
    structure = structure_from_brief(brief, measured_fed_solubility=cpf.get("food.fed_solubility_factor") is not None)
    split = split_studies(records, _question(structure))
    train = training_stages(records, split, cpf)
    return {s.study_id: _role(s, train) for s in split.splits}
