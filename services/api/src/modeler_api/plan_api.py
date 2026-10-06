"""P5 · model plan (plan §11, review layer L3; T-50): the planning canvas's API.

`GET /plan` creates the plan from the accepted P4 inputs on first read (the MS-01 default, exactly as `generate_map`)
and returns it with the live validator, the diff against the default, the "Overall Data" (studies, CPF parameters,
dissolution profiles) and the D1 / D2 views. Each change (a drop on D3, a fit, a structure choice, an acknowledgment,
a decision on an A5 proposal) is a new ModelPlan version with its reason; a person's change is userLocked. A5 drafts
in the background. `plan:sign` is refused while any violation is open; otherwise it generates the MAP from the plan,
takes the Part 11 signature from the token's step-up (no password, D-07: the MIDD lead, role modeler-reviewer), stages
the campaign inputs as `campaign:prepare` does, and approves the plan and the MAP (P5 gate). P6 starts the campaign.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from modeler_api.auth import Principal, ensure_step_up, require_role
from modeler_api.brief_api import agents_status
from modeler_api.compliance.signatures import SignatureMeaning, Signer, sign_after_step_up
from modeler_api.config import get_settings
from modeler_api.project_api import Reader, StoreDep, Writer, version_view, workspace_for
from modeler_api.responses import envelope
from modeler_project import ArtifactKind, ProjectStore, Workspace
from modeler_project.brief import ProjectBrief
from modeler_project.inputs import MAIN as INPUTS_MAIN
from modeler_project.inputs import current_cpf
from modeler_project.plan import (
    MAIN,
    Deviation,
    ModelPlan,
    PlanError,
    acknowledge,
    blocking,
    build_default,
    campaign_cpf,
    current,
    decide_proposal,
    diff,
    map_from_plan,
    place,
    rebase,
    save,
    set_fit,
    set_structure,
    structure_from_brief,
    unlock,
    validate,
)
from pbpk_domain.campaign.map import MapDocument, MapStatus
from pbpk_domain.cpf.models import CPF

router = APIRouter(prefix="/api/v1", tags=["plan"])
MiddLead = Annotated[Principal, Depends(require_role("modeler-reviewer"))]
_RUNNING: set[tuple[str, str]] = set()
_LOCK = threading.Lock()


def _inputs(ws: Workspace) -> tuple[CPF, list[dict[str, Any]], list[Any]]:
    ready = ws.latest(ArtifactKind.READINESS, INPUTS_MAIN)
    if ready is None or ws.status(ready).value != "APPROVED":
        raise HTTPException(status_code=409, detail="accept the model inputs (P4) before planning")
    cpf = current_cpf(ws)
    catalog = ws.latest(ArtifactKind.STUDY_CATALOG, INPUTS_MAIN)
    rows = list(catalog.content["studies"]) if catalog else []
    if cpf is None or not rows:
        raise HTTPException(status_code=409, detail="the inputs have no CPF or no study")
    return cpf, rows, [ws.latest(ArtifactKind.CPF, INPUTS_MAIN).ref, catalog.ref, ready.ref]


def _exploratory(ws: Workspace) -> bool:
    settings = get_settings()
    if not settings.read_root:
        return False
    from modeler_api.filestore import FileReadStore

    project = FileReadStore(settings.read_root).get_project(ws.tenant_id, ws.project_id)
    return bool((project or {}).get("exploratory"))


def _brief(ws: Workspace) -> ProjectBrief | None:
    version = ws.latest(ArtifactKind.BRIEF, "main")
    return ProjectBrief.from_content(version.content) if version else None


def _ensure(ws: Workspace, by: str) -> tuple[Any, ModelPlan, CPF, list[dict[str, Any]]]:
    cpf, rows, refs = _inputs(ws)
    version, plan = current(ws)
    if plan is None:
        measured_fed = cpf.get("food.fed_solubility_factor") is not None
        plan = build_default(cpf, rows, structure_from_brief(_brief(ws), measured_fed_solubility=measured_fed))
        version = save(ws, plan, by=by, reason="the MS-01 default plan (split §3.3, stage plan, budgets)", derived_from=refs)
    return version, plan, cpf, rows


def _d1(cpf: CPF, plan: ModelPlan) -> dict[str, Any]:
    """D1 disposition: binding and distribution, then each elimination / transport pathway with its parameters."""
    def node(pid: str) -> dict[str, Any] | None:
        r = cpf.get(pid)
        if r is None:
            return None
        fit = plan.fits.get(pid)
        return {"id": pid, "value": r.value, "unit": r.unit, "status": r.status.value,
                "source": r.provenance.reference if r.provenance else None, "fit": fit.model_dump() if fit else None,
                "candidate_at": [st for st, ids in plan.fit_candidates.items() if pid in ids]}

    binding = [n for pid in ("bind.fu", "dist.bp_ratio", "bind.partner", "phys.logp") if (n := node(pid))]
    distribution = [n for r in cpf.parameters if r.id.startswith("dist.") and (n := node(r.id))]
    pathways: dict[str, dict[str, Any]] = {}
    for r in cpf.parameters:
        if r.engine_binding is None or not r.engine_binding.process:
            continue
        key = r.engine_binding.process
        lane = pathways.setdefault(key, {"process": key, "kind": "elimination" if r.id.startswith("elim.") else "transport"
                                         if r.id.startswith("transp.") else "other", "parameters": []})
        lane["parameters"].append(node(r.id))
    informed_by = [s.study_id for s in plan.studies if plan.placements[s.study_id].role == "S1"]
    return {"binding": binding, "distribution": distribution, "pathways": list(pathways.values()), "informed_by": informed_by}


def _d2(cpf: CPF, plan: ModelPlan, ws: Workspace) -> dict[str, Any]:
    """D2 absorption and formulation: one lane per formulation (solution, and each CPF formulation) with its studies."""
    from pbpk_domain.cpf.formulations import formulation_names

    absorption = [{"id": r.id, "value": r.value, "unit": r.unit, "status": r.status.value,
                   "fit": plan.fits[r.id].model_dump() if r.id in plan.fits else None,
                   "candidate_at": [st for st, ids in plan.fit_candidates.items() if r.id in ids]}
                  for r in cpf.parameters if r.id.startswith(("phys.solubility", "perm.intestinal", "food.", "elim.ehc"))]
    lanes = [{"name": "solution", "release": "dissolved (solution)", "parameters": [], "studies": [
        {"study_id": s.study_id, "food_state": s.food_state, "role": plan.placements[s.study_id].role}
        for s in plan.studies if s.route == "oral" and s.formulation in ("solution", "suspension")]}]
    for name in formulation_names(cpf):
        params = [{"id": r.id, "value": r.value, "unit": r.unit} for r in cpf.with_prefix(f"form.{name}")]
        kind = next((p["value"] for p in params if p["id"].endswith(".type")), "?")
        lanes.append({"name": name, "release": kind, "parameters": params, "studies": [
            {"study_id": s.study_id, "food_state": s.food_state, "role": plan.placements[s.study_id].role}
            for s in plan.studies if s.route == "oral" and s.formulation not in ("solution", "suspension")]})
    profiles = [{"id": v.id, "label": v.content["label"], "release_model": v.content["release_model"]}
                for v in ws.list(ArtifactKind.DISSOLUTION) if v.id != "comparisons"]
    return {"absorption": absorption, "lanes": lanes, "dissolution": profiles,
            "food_effect_in_question": plan.structure.food_effect_in_question,
            "measured_fed_solubility": plan.structure.measured_fed_solubility}


def _view(ws: Workspace, version, plan: ModelPlan, cpf: CPF, rows: list[dict[str, Any]]) -> dict[str, Any]:
    violations = validate(plan, cpf, rows, exploratory=_exploratory(ws))
    map_version = ws.latest(ArtifactKind.MAP, MAIN)
    return {
        "plan": plan.to_content(),
        "artifact": version_view(ws, version, with_content=False),
        "violations": [v.model_dump() for v in violations],
        "blocking": len(blocking(violations)),
        "diff": diff(plan),
        "overall_data": {
            "studies": [s.model_dump() | {"role": plan.placements[s.study_id].role,
                                          "userLocked": plan.placements[s.study_id].userLocked,
                                          "reason": plan.placements[s.study_id].reason,
                                          "rationale": plan.rationale.get(s.study_id, "")} for s in plan.studies],
            "parameters": [{"id": r.id, "value": r.value, "unit": r.unit, "status": r.status.value} for r in cpf.parameters],
        },
        "d1": _d1(cpf, plan),
        "d2": _d2(cpf, plan, ws),
        "map": ({**version_view(ws, map_version, with_content=False), "campaign": map_version.content.get("campaign"),
                 "map_sha256": map_version.content.get("map_sha256"),
                 "map_version": (map_version.content.get("map") or {}).get("version"),
                 "supersedes": (map_version.content.get("map") or {}).get("supersedes_sha256")} if map_version else None),
        # D-14: once a MAP is signed, every change is a deviation that waits for the MIDD lead's signature
        "signed": bool(map_version and map_version.content.get("signature")),
        "deviations": [d.model_dump(mode="json") for d in plan.deviations],
        "deviations_pending": len(plan.pending_deviations()),
        "agents": agents_status(), "running": (ws.tenant_id, ws.project_id) in _RUNNING,
    }


def _respond(ws: Workspace, by: str) -> dict[str, Any]:
    version, plan, cpf, rows = _ensure(ws, by)
    return envelope(_view(ws, version, plan, cpf, rows))


@router.get("/projects/{project_id}/plan")
def get_plan(project_id: str, principal: Writer, store: StoreDep) -> dict[str, Any]:
    return _respond(workspace_for(project_id, principal, store), principal.user_id)


@router.get("/projects/{project_id}/plan:view")
def read_plan(project_id: str, principal: Reader, store: StoreDep) -> dict[str, Any]:
    """Read-only view for viewers (the plan must exist)."""
    ws = workspace_for(project_id, principal, store)
    version, plan = current(ws)
    if plan is None:
        raise HTTPException(status_code=404, detail="no model plan yet")
    cpf, rows, _refs = _inputs(ws)
    return envelope(_view(ws, version, plan, cpf, rows))


def _signed_map(ws: Workspace) -> tuple[Any, MapDocument] | None:
    """The latest signed MAP (it carries a signature; a newer plan version makes it stale, not unsigned)."""
    version = ws.latest(ArtifactKind.MAP, MAIN)
    if version is None or not version.content.get("signature"):
        return None
    return version, MapDocument.model_validate(version.content["map"])


def _deviation(ws: Workspace, plan: ModelPlan, *, kind: str, target: str, change: str, reason: str,
               by: str) -> ModelPlan:
    """After the MAP is signed, a change is a deviation (D-14): recorded on the plan, pending the MIDD lead's signature."""
    signed = _signed_map(ws)
    if signed is None:
        return plan
    record = Deviation(kind=kind, target=target, change=change, reason=reason, by=by, at=datetime.now(UTC),
                       against_map=signed[1].version)
    return plan.model_copy(update={"deviations": (*plan.deviations, record)})


def _change(ws: Workspace, principal: Principal, fn, reason: str, *, dry_run: bool = False,
            deviation: tuple[str, str, str] | None = None) -> dict[str, Any]:
    """Apply a canvas change. ``deviation`` = (kind, target, change): what the change is if the MAP is already signed
    (D-14); None for a view-only change (the layout), which never deviates."""
    version, plan, cpf, rows = _ensure(ws, principal.user_id)
    if ws.status(version).value == "STALE":
        raise HTTPException(status_code=409, detail="the inputs changed since this plan: bring it up to date (rebase) first")
    try:
        changed = fn(plan)
    except (PlanError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    signed = _signed_map(ws) is not None
    if dry_run:  # the canvas asks what a move would do before the person confirms it: nothing is saved
        return envelope({"violations": [v.model_dump() for v in validate(changed, cpf, rows, exploratory=_exploratory(ws))],
                         "diff": diff(changed), "deviation": signed and deviation is not None})
    if deviation is not None:
        kind, target, what = deviation
        changed = _deviation(ws, changed, kind=kind, target=target, change=what, reason=reason, by=principal.user_id)
    version = save(ws, changed, by=principal.user_id,
                   reason=f"MAP deviation (pending signature): {reason}" if signed and deviation else reason)
    return envelope(_view(ws, version, changed, cpf, rows))


class PlacementRequest(BaseModel):
    role: Literal["S1", "S2", "S3", "S5", "S6", "SUPPORTIVE"]
    reason: str = Field(min_length=1)


@router.put("/projects/{project_id}/plan/placements/{study_id}")
def put_placement(project_id: str, study_id: str, body: PlacementRequest, principal: Writer, store: StoreDep,
                  dry_run: bool = False) -> dict[str, Any]:
    """A study dropped on a D3 node: placed by a person (userLocked), with the reason. ``dry_run`` validates only."""
    ws = workspace_for(project_id, principal, store)
    return _change(ws, principal, lambda p: place(p, study_id, body.role, by=principal.user_id, reason=body.reason),
                   f"{study_id} → {body.role}: {body.reason}", dry_run=dry_run,
                   deviation=("role", study_id, f"placed in {body.role}"))


@router.post("/projects/{project_id}/plan/placements/{study_id}:unlock")
def unlock_placement(project_id: str, study_id: str, principal: Writer, store: StoreDep) -> dict[str, Any]:
    ws = workspace_for(project_id, principal, store)
    return _change(ws, principal, lambda p: unlock(p, study_id), f"{study_id} back to the MS-01 default",
                   deviation=("unlock", study_id, "back to the MS-01 default"))


class FitRequest(BaseModel):
    stages: list[str] = Field(min_length=1)
    lower: float
    upper: float
    scale: Literal["linear", "log"] = "linear"
    reason: str = Field(min_length=1)


@router.put("/projects/{project_id}/plan/fits/{parameter}")
def put_fit(project_id: str, parameter: str, body: FitRequest, principal: Writer, store: StoreDep) -> dict[str, Any]:
    ws = workspace_for(project_id, principal, store)
    fit = {"stages": tuple(body.stages), "lower": body.lower, "upper": body.upper, "scale": body.scale}
    return _change(ws, principal, lambda p: set_fit(p, parameter, fit, by=principal.user_id, reason=body.reason),
                   f"fit {parameter} in {', '.join(body.stages)}: {body.reason}",
                   deviation=("fit", parameter, f"fitted in {', '.join(body.stages)} [{body.lower:g}, {body.upper:g}] {body.scale}"))


class ReasonRequest(BaseModel):
    reason: str = Field(min_length=1)


@router.post("/projects/{project_id}/plan/fits/{parameter}:remove")
def remove_fit(project_id: str, parameter: str, body: ReasonRequest, principal: Writer, store: StoreDep) -> dict[str, Any]:
    ws = workspace_for(project_id, principal, store)
    return _change(ws, principal, lambda p: set_fit(p, parameter, None, by=principal.user_id, reason=body.reason),
                   f"{parameter} fixed again: {body.reason}", deviation=("fit removed", parameter, "fixed again"))


class StructureRequest(BaseModel):
    key: Literal["objective", "context_of_use", "model_risk", "food_effect_in_question", "measured_fed_solubility",
                 "planned_applications"]
    value: Any
    reason: str = Field(min_length=1)


@router.put("/projects/{project_id}/plan/structure")
def put_structure(project_id: str, body: StructureRequest, principal: Writer, store: StoreDep) -> dict[str, Any]:
    """A structure choice; the default split depends on some of them, so non-locked placements follow the new default."""
    ws = workspace_for(project_id, principal, store)
    cpf, rows, _refs = _inputs(ws)

    def apply(plan: ModelPlan) -> ModelPlan:
        changed = set_structure(plan, body.key, body.value, by=principal.user_id, reason=body.reason)
        return rebase(changed, build_default(cpf, rows, changed.structure)).model_copy(update={"structure": changed.structure})

    return _change(ws, principal, apply, f"{body.key} = {body.value}: {body.reason}",
                   deviation=("structure", body.key, f"set to {body.value}"))


@router.post("/projects/{project_id}/plan/violations/{violation_id}:acknowledge")
def acknowledge_violation(project_id: str, violation_id: str, body: ReasonRequest, principal: Writer,
                          store: StoreDep) -> dict[str, Any]:
    ws = workspace_for(project_id, principal, store)
    return _change(ws, principal, lambda p: acknowledge(p, violation_id, by=principal.user_id, reason=body.reason),
                   f"acknowledged {violation_id}: {body.reason}",
                   deviation=("acknowledged", violation_id, "accepted as a limitation"))


class DecisionRequest(BaseModel):
    accept: bool
    reason: str = Field(min_length=1)


@router.post("/projects/{project_id}/plan/proposals/{proposal_id}:decide")
def decide(project_id: str, proposal_id: str, body: DecisionRequest, principal: Writer, store: StoreDep) -> dict[str, Any]:
    ws = workspace_for(project_id, principal, store)
    return _change(ws, principal,
                   lambda p: decide_proposal(p, proposal_id, accept=body.accept, by=principal.user_id, reason=body.reason),
                   f"{'accepted' if body.accept else 'rejected'} {proposal_id}: {body.reason}",
                   deviation=("proposal", proposal_id, "accepted" if body.accept else "rejected"))


class LayoutRequest(BaseModel):
    layout: dict[str, dict[str, float]]


@router.put("/projects/{project_id}/plan/layout")
def put_layout(project_id: str, body: LayoutRequest, principal: Writer, store: StoreDep) -> dict[str, Any]:
    ws = workspace_for(project_id, principal, store)
    return _change(ws, principal, lambda p: p.model_copy(update={"layout": body.layout}), "canvas layout")


@router.post("/projects/{project_id}/plan:rebase")
def rebase_plan(project_id: str, principal: Writer, store: StoreDep) -> dict[str, Any]:
    """New inputs (P4 changed): the default is recomputed, a person's choices are kept, new studies are marked."""
    ws = workspace_for(project_id, principal, store)
    version, plan, _cpf, _rows = _ensure(ws, principal.user_id)
    cpf, rows, refs = _inputs(ws)
    fresh = build_default(cpf, rows, plan.structure)
    rebased = _deviation(ws, rebase(plan, fresh), kind="rebase", target="inputs", by=principal.user_id,
                         change="re-placed on the current inputs (a person's choices kept, new studies placed by default)",
                         reason="the model inputs changed after the MAP was signed")
    version = save(ws, rebased, by=principal.user_id, reason="rebased on the current inputs", derived_from=refs)
    return envelope(_view(ws, version, ModelPlan.from_content(version.content), cpf, rows))


# --- A5 ---------------------------------------------------------------------------------------------------------


def run_planning_job(store: ProjectStore, tenant_id: str, project_id: str, *, model, max_turns: int = 20,
                     exploratory: bool = False) -> dict[str, Any]:
    from modeler_agents.planning_agent import PlanningContext, run_planning
    from modeler_agents.run_store import FileRunStore

    ws = Workspace(store, tenant_id, project_id)
    _version, plan, cpf, rows = _ensure(ws, "system")
    runs = FileRunStore(store.root, project_id=project_id)  # type: ignore[attr-defined]
    run_id = runs.start_run(tenant_id=tenant_id, agent="A5-planning", provider=model.provider, model=model.model,
                            campaign_id=None, budget={"max_turns": max_turns})
    seq = [0]

    def log_step(step: dict[str, Any]) -> None:
        seq[0] += 1
        runs.record_step(run_id=run_id, seq=seq[0], kind=step.get("type", "step"), content=step, usage=step.get("usage", {}))

    ctx = PlanningContext(plan=plan, cpf=cpf, rows=rows, actor=f"agent:{run_id}", exploratory=exploratory)
    brief = _brief(ws)
    outcome = run_planning(model, ctx, drug=brief.drug_name if brief else cpf.compound, max_turns=max_turns, log_step=log_step)
    # the plan may have changed while the agent worked: apply its rationales and proposals to the latest version
    _v, latest = current(ws)
    merged = latest.model_copy(update={
        "rationale": {**latest.rationale, **ctx.plan.rationale},
        "proposals": (*latest.proposals, *[p for p in ctx.plan.proposals if p.id not in {q.id for q in latest.proposals}
                                          and not (p.kind == "role" and latest.placements[p.target].userLocked)]),
    })
    save(ws, merged, by=ctx.actor, reason=f"A5 draft: {ctx.explained} rationales, {len(ctx.proposed)} proposals")
    summary = {"explained": ctx.explained, "proposed": ctx.proposed, "refused": ctx.refused, "summary": outcome.final_text[:2000],
               "error": outcome.error}
    runs.finish_run(run_id=run_id, status=outcome.status, input_tokens=outcome.usage["input_tokens"],
                    output_tokens=outcome.usage["output_tokens"], cost_usd=0.0, summary=summary)
    return {"run_id": run_id, "status": outcome.status, **summary}


@router.post("/projects/{project_id}/plan:draft", status_code=202)
def start_draft(project_id: str, principal: Writer, store: StoreDep) -> dict[str, Any]:
    from modeler_agents.llm import LLMConfigError, chat_model_from_env

    ws = workspace_for(project_id, principal, store)
    _ensure(ws, principal.user_id)
    try:
        model = chat_model_from_env()
    except LLMConfigError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if model is None:
        raise HTTPException(status_code=409, detail="agents are off: the MS-01 default stands; explain changes yourself")
    key = (principal.tenant_id, project_id)
    with _LOCK:
        if key in _RUNNING:
            raise HTTPException(status_code=409, detail="A5 is already drafting")
        _RUNNING.add(key)
    exploratory = _exploratory(ws)

    def job() -> None:
        try:
            run_planning_job(store, principal.tenant_id, project_id, model=model, exploratory=exploratory)
        finally:
            with _LOCK:
                _RUNNING.discard(key)

    threading.Thread(target=job, daemon=True).start()
    return envelope({"status": "RUNNING"})


# --- approve and sign -------------------------------------------------------------------------------------------


class SignRequest(BaseModel):
    note: str = ""


@router.post("/projects/{project_id}/plan:sign")
def sign_plan(project_id: str, body: SignRequest, principal: MiddLead, store: StoreDep) -> dict[str, Any]:
    """Approve and sign: the MAP generated from the plan, signed (Part 11, step-up), and the campaign inputs staged."""
    from modeler_api.filestore import FileWriteStore
    from modeler_api.write_api import _observed_from_studies

    ws = workspace_for(project_id, principal, store)
    version, plan, cpf, rows = _ensure(ws, principal.user_id)
    if ws.status(version).value == "STALE":
        raise HTTPException(status_code=409, detail="the inputs changed since this plan: rebase it first")
    previous = _signed_map(ws)
    pending = plan.pending_deviations()
    if previous is not None and not pending:
        raise HTTPException(status_code=409, detail=f"MAP v{previous[1].version} is signed and the plan has not changed since")
    exploratory = _exploratory(ws)
    try:
        doc = map_from_plan(plan, cpf, rows, exploratory=exploratory)
    except PlanError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if previous is not None:
        # D-14: the deviations make a new MAP version that supersedes the signed one and states each change
        old = previous[1]
        lines = tuple(f"Deviation from MAP v{d.against_map} ({d.kind}, {d.target}): {d.change}. Reason: {d.reason}"
                      for d in pending)
        doc = doc.model_copy(update={"version": old.version + 1, "supersedes_sha256": old.content_sha256(),
                                     "status": MapStatus.DRAFT, "signature": None,
                                     "split_rationale": (*doc.split_rationale, *lines),
                                     "split_limitations": (*doc.split_limitations, *lines)})
    settings = get_settings()
    if not settings.read_root:
        raise HTTPException(status_code=503, detail="Campaign inputs need a read root. Set MODELER_READ_ROOT.")
    ensure_step_up(principal)  # the signature comes from the token's recent step-up, never a password
    content_sha = doc.content_sha256()
    signature = sign_after_step_up(
        signer=Signer(user_id=principal.user_id, printed_name=principal.printed_name), meaning=SignatureMeaning.APPROVED,
        record_type="map-deviation" if previous else "map", record_id=f"{project_id}/plan-v{version.version}",
        record_sha256=content_sha, acr=principal.acr or "")
    signed = doc.sign(printed_name=principal.printed_name, signature_id=signature.signature_id)
    if pending:  # the deviations now carry their signature and the MAP version that holds them
        marked = tuple(d.model_copy(update={"signature_id": signature.signature_id, "signed_map": signed.version})
                       if d.signature_id is None else d for d in plan.deviations)
        plan = plan.model_copy(update={"deviations": marked})
        version = save(ws, plan, by=principal.user_id, reason=f"{len(pending)} deviation(s) signed into MAP v{signed.version}")

    # the campaign's inputs, staged like campaign:prepare: the campaign CPF (with the plan's fit policies), the
    # signed MAP, and the observed PK of the judged studies (with their origin)
    write = FileWriteStore(settings.read_root)
    prep = f"prep/plan-v{version.version}"
    run_cpf = campaign_cpf(plan, cpf)
    cpf_bytes = run_cpf.model_dump_json().encode("utf-8")
    map_bytes = signed.model_dump_json().encode("utf-8")
    mw = cpf.get("phys.mw")
    observed = _observed_from_studies([r for r in rows if r.get("profile")], mw.numeric_value if mw else None)
    cpf_path = write.materialize(principal.tenant_id, f"{prep}/cpf.json", cpf_bytes)
    map_path = write.materialize(principal.tenant_id, f"{prep}/map.json", map_bytes)
    observed_path = write.materialize(principal.tenant_id, f"{prep}/observed.json",
                                      json.dumps(observed, ensure_ascii=False).encode("utf-8"))
    from modeler_contracts.runs import CAMPAIGN_STAGES

    campaign = {"compound": cpf.compound, "map_id": f"map-{project_id}-v{signed.version}",
                "cpf_uri": cpf_path.as_uri(), "cpf_sha256": hashlib.sha256(cpf_bytes).hexdigest(),
                "map_uri": map_path.as_uri(), "observed_uri": observed_path.as_uri(), "stages": list(CAMPAIGN_STAGES),
                "question": plan.structure.objective, "model_risk": plan.structure.model_risk}
    map_version = ws.commit(ArtifactKind.MAP, MAIN, {"map": json.loads(map_bytes), "map_sha256": content_sha,
                                                     "signature": {"signature_id": signature.signature_id,
                                                                   "manifestation": signature.manifestation()},
                                                     "campaign": campaign},
                            derived_from=[version.ref], actor=principal.user_id,
                            reason=f"MAP v{signed.version} from plan v{version.version}"
                            + (f" ({len(pending)} deviation(s), superseding v{previous[1].version})" if previous else ""))
    for ref in (version.ref, map_version.ref):
        ws.approve(ref, by=principal.user_id, printed_name=principal.printed_name, meaning="Approved",
                   signature_id=signature.signature_id, note=body.note)
    return envelope(_view(ws, version, plan, cpf, rows) | {"signature": {"signature_id": signature.signature_id,
                                                                        "manifestation": signature.manifestation()}})
