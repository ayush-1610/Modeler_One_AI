"""What the Inputs step shows (redesign §3.2), read only: one row per model input with its sources, one row per study
with its facts and proposed role. Nothing here decides anything; the rows are built from the latest assembly (the
source selection of D-32), the evidence register, the study catalog and the person's choices.

A compound row's state is what the person sees on it:
- kept: the CPF carries one source's value, with the sources that agree and the alternatives beneath it;
- conflict: values more than 2-fold apart, out of the CPF until a person keeps one;
- held: only flagged values, which enter once a person checks them;
- missing: no value yet, for an input S0 needs;
- empty: no value yet for a model input the data plan owns that nothing waits on (asked for with `empty=True`): a row
  to fill, not a gap, so S0, readiness and the to-do list are what they were.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable
from typing import Any

from modeler_project.artifacts import ArtifactKind
from modeler_project.inputs import (
    MAIN,
    MODEL_IDS,
    allowed_values,
    catalog_rows,
    choices,
    cpf_assembly,
    current_cpf,
    elimination_pathways,
    evidence_view,
    placement,
    tab_of,
    value_problem,
)
from modeler_project.requirements import RequirementMatrix
from modeler_project.workspace import Workspace
from pbpk_domain.cpf.process_bindings import binding_candidates, is_process_id


def _requirement_of(matrix: RequirementMatrix | None, cpf_id: str) -> str | None:
    """The data-checklist item a value for this input is filed under: the item for the id itself, else the item whose
    target the id belongs to (a pKa group under phys.pka, a pathway under the "elim" placeholder)."""
    if matrix is None:
        return None
    owners = [i for i in matrix.items if cpf_id == i.target or cpf_id.startswith(i.target + ".")]
    return max(owners, key=lambda i: len(i.target)).req_id if owners else None


def _row(cpf_id: str, state: str, matrix: RequirementMatrix | None, **fields: Any) -> dict[str, Any]:
    return {"id": cpf_id, "tab": tab_of(cpf_id), "state": state, "req_id": _requirement_of(matrix, cpf_id), "value": None,
            "unit": None, "status": None, "placement": placement(cpf_id), "binding": None, "candidates": [], "sources": [],
            "alternatives": [], "message": None, "allowed": list(allowed_values(cpf_id)), **fields}


def compound_rows(ws: Workspace, todo: list[dict[str, Any]], *, empty: bool = False) -> list[dict[str, Any]]:
    """Every model input on its tab: the CPF's values with their sources, then what waits on a person (from the
    assembly's issues and the to-do list's missing inputs), in id order. `empty` (the Inputs page): also a row for
    every exact id of the parameter registry that PK-Sim takes (placement "model") and an item of this project's data
    plan owns, with no value yet; a family's members and an id no item owns are left out, never made up."""
    from modeler_project.evidence_register import items

    evidence = {e.id: e for e in items(ws)}

    def views(ids: Iterable[str]) -> list[dict[str, Any]]:
        return [evidence_view(evidence[i]) for i in ids if i in evidence]

    requirements = ws.latest(ArtifactKind.REQUIREMENTS, MAIN)
    matrix = RequirementMatrix.from_content(requirements.content) if requirements else None
    assembly = cpf_assembly(ws) or {}
    selections = assembly.get("sources", {})
    cpf = current_cpf(ws)
    rows: dict[str, dict[str, Any]] = {}
    for record in cpf.parameters if cpf else ():
        selection = selections.get(record.id, {})
        kept = selection.get("kept") or ((record.provenance.evidence or "").split("@")[0] if record.provenance else None)
        binding = record.engine_binding
        # a kept value the model builder cannot take (a binding partner kept before the check, or let in by a signed
        # delivery's landing): said on its row, so a person replaces it before a model is built
        rows[record.id] = _row(
            record.id, "kept", matrix, value=record.value, unit=record.unit, status=record.status.value,
            message=value_problem(record.id, record.value, unset=True) if record.value is not None else None,
            binding={"process": binding.process, "parameter": binding.parameter} if binding else None,
            candidates=[c.process for c in binding_candidates(record.id)]
            if is_process_id(record.id) and binding is None else [],
            sources=views([i for i in (kept, *selection.get("agreeing", ())) if i]),
            alternatives=[{**v, "relation": a["relation"], "differs_pct": a["differs_pct"]}
                          for a in selection.get("alternatives", ()) for v in views([a["id"]])])
    for issue in assembly.get("issues", []):
        target = issue["target"]
        if issue["kind"] == "conflict" and target not in rows:
            rows[target] = _row(target, "conflict", matrix, message=issue["message"],
                                alternatives=[{**v, "relation": "conflicts", "differs_pct": None}
                                              for v in views(issue["evidence"])])
        elif issue["kind"] == "review" and target not in rows:
            rows[target] = _row(target, "held", matrix, message=issue["message"], sources=views(issue["evidence"]))
    for entry in todo:
        if entry["kind"] == "missing" and entry["target"] not in rows:
            rows[entry["target"]] = _row(entry["target"], "missing", matrix, message=entry["message"], sources=entry["items"])
    if empty:
        present = {k.partition("@")[0] for k in rows}       # an alternative (`<id>@<name>`) fills its id's row
        for cpf_id in sorted(MODEL_IDS - present):
            if _requirement_of(matrix, cpf_id) is not None:
                rows[cpf_id] = _row(cpf_id, "empty", matrix)
        # the elimination pathways the builder places with one value (OWN-5): a row to fill each, with the unit its value
        # is stored in, so a pathway can be given on Compound as on To do (they are process parameters, not model ids)
        for pathway in elimination_pathways():
            if pathway["id"] not in present and _requirement_of(matrix, pathway["id"]) is not None:
                rows[pathway["id"]] = _row(pathway["id"], "empty", matrix, unit=pathway["unit"])
    return [rows[k] for k in sorted(rows)]


def _demographics_state(row: dict[str, Any]) -> str:
    if row.get("demographics"):
        return "entered"
    if row.get("published_individual"):
        return "published"
    return "default" if row.get("demographics_choice") == "healthy_adult_default" else "missing"


def study_rows(ws: Workspace, blinded: Collection[str] | Callable[[str], bool],
               why: Callable[[str], str | None] | None = None) -> list[dict[str, Any]]:
    """Each study as the Studies and Individuals tabs show it: its facts (no observed values), the role the MS-01 split
    proposes (the plan's once a plan exists; changed only there, D-33), whether it is blinded (D-15) and why
    (`blinded_why`, when `why` is given: the reason the evidence gives its datasets, so a study no card or sheet-form
    group holds is said with its reason too; final review round 7), its demographics (D-29) and whether its regimen is
    complete. Studies a person left out follow, with the reason. `blinded`: the blinded study ids, or the rule that says
    whether a study id is (`BlindedSources.withholds`); `why`: the reason for a blinded study id (`study_why`)."""
    held = blinded if callable(blinded) else blinded.__contains__

    def said(sid: str) -> dict[str, Any]:
        return {"blinded_why": why(sid) if held(sid) else None} if why is not None else {}
    from modeler_project.dataset_register import datasets
    from modeler_project.plan import current
    from modeler_project.roles import proposed_roles

    roles = proposed_roles(ws)
    role_source = "plan" if current(ws)[1] is not None else "proposed"
    rows = []
    for row in catalog_rows(ws):
        sid = str(row["study_id"])
        facts = {k: v for k, v in row.items() if k not in ("profile", "origin", "dataset_id", "purpose", "evaluable",
                                                          "demographics_choice")}
        rows.append({"study_id": sid, "dataset_id": row.get("dataset_id"), "origin": row.get("origin"),
                     "purpose": row.get("purpose"), "evaluable": bool(row.get("evaluable")), "facts": facts,
                     "role": roles.get(sid), "role_source": role_source, "blinded": held(sid), **said(sid), "excluded": None,
                     "demographics": _demographics_state(row),
                     "regimen_missing": row.get("design") == "MD"
                     and not (row.get("n_doses") and row.get("dosing_interval_h"))})
    left_out = choices(ws).excluded_studies
    for dataset in datasets(ws):
        sid = str(dataset.study.get("study_id"))
        if sid in left_out and not any(r["study_id"] == sid for r in rows):
            facts = dict(dataset.study)
            rows.append({"study_id": sid, "dataset_id": dataset.id, "origin": dataset.origin.value,
                         "purpose": dataset.purpose, "evaluable": False, "facts": facts, "role": None,
                         "role_source": role_source, "blinded": held(sid), **said(sid), "excluded": left_out[sid],
                         "demographics": _demographics_state({**facts, "demographics_choice": dataset.demographics_choice}),
                         "regimen_missing": False})
    return rows
