"""A formulation's release model, chosen on Inputs (the owner's D1; plan 2026-11-26 §8, the release model on Inputs).

The Data room sends a product's release as the Weibull fit of its chosen dissolution profile. When that profile levels
off below 100 %, the room's facts make the release model a choice: the Weibull curve as measured, or particle
dissolution (the plateau as the solubility limit). The room suggests one and sends the Weibull fit with that suggestion
as a proposal (`EvidenceItem.proposed["release_model"]` on `form.<name>.type`); a person answers it here:

- **confirm** the Weibull fit: the proposal is taken as it is;
- **hold** the formulation for particle dissolution, with a reason: its Weibull values are set aside (rejected, the
  reason recorded) and the formulation waits. Inputs cannot hold a particle radius and the unstirred-layer thickness
  yet: the parameter registry (a locked file of harvested PK-Sim names and units) has no entry for them, so a particle
  formulation is built only once the owner approves that change. Until then the readiness check says so;
- **use the Weibull fit after all** for a held formulation: its values are taken again.

Nothing is decided without a person; every step is a new version of the evidence items, with who and why.
"""

from __future__ import annotations

from typing import Any, Literal

from modeler_project.evidence import EvidenceItem, EvidenceState
from modeler_project.workspace import Workspace

# the reason a held formulation's Weibull values were set aside starts with this (how a held formulation is known)
HELD = "particle dissolution chosen on Inputs (D1)"
# why a held formulation is not built, as the readiness check says it
HELD_WHY = ("particle dissolution was chosen on Inputs, and Inputs cannot hold a particle radius and the unstirred-layer "
            "thickness yet (the parameter registry has no entry for them: the owner's decision); use the Weibull fit, or "
            "wait for that")


class ReleaseChoiceError(ValueError):
    """A release-model answer that cannot be made: no such formulation, or a reason missing."""


def _formulation(target: str) -> str | None:
    """The formulation a `form.<name>.…` target is about."""
    parts = target.split(".")
    return parts[1] if len(parts) >= 3 and parts[0] == "form" else None


def _items(ws: Workspace, name: str) -> list[EvidenceItem]:
    from modeler_project.evidence_register import items

    return [e for e in items(ws) if _formulation(e.target) == name]


def release_states(ws: Workspace) -> dict[str, dict[str, Any]]:
    """Each formulation whose release model waits on a person or was held, by name: `{"state": "proposed", "evidence_id",
    **the proposal}` or `{"state": "held", "evidence_id", "reason", "by"}`. A formulation whose answer is given (or that
    had no proposal) is not listed."""
    from modeler_project.evidence_register import items

    out: dict[str, dict[str, Any]] = {}
    types = [e for e in items(ws) if e.target.startswith("form.") and e.target.endswith(".type")]
    for e in types:
        name = _formulation(e.target)
        if name is None:
            continue
        taken = any(o.state is EvidenceState.ACCEPTED for o in types if _formulation(o.target) == name and o.id != e.id)
        if e.state is EvidenceState.ACCEPTED and e.proposed and "release_model" in e.proposed:
            out[name] = {"state": "proposed", "evidence_id": e.id, **e.proposed["release_model"]}
        elif e.state is EvidenceState.REJECTED and e.decision_reason.startswith(HELD) and not taken:
            out[name] = {"state": "held", "evidence_id": e.id, "reason": e.decision_reason[len(HELD):].lstrip(": "),
                         "by": e.decided_by or ""}
    return out


def set_release_model(ws: Workspace, name: str, *, model: Literal["weibull", "particles"], reason: str = "",
                      by: str) -> dict[str, Any]:
    """A person's answer to a formulation's release model (see the module): "weibull" confirms the proposal, or takes a
    held formulation's Weibull values again; "particles" holds it, with a reason. Returns what changed."""
    from modeler_project.evidence_register import decide

    state = release_states(ws).get(name)
    if state is None:
        raise ReleaseChoiceError(f"{name}: no release model waits for an answer")
    weibull = [e for e in _items(ws, name) if e.target == f"form.{name}.type" or ".weibull." in e.target]
    if model == "particles":
        if not reason.strip():
            raise ReleaseChoiceError("say why particle dissolution, not the Weibull fit the room suggests")
        if state["state"] == "held":
            raise ReleaseChoiceError(f"{name} is held for particle dissolution already")
        _answered(ws, state["evidence_id"], by=by, what="particle dissolution")
        held = []
        for e in weibull:
            if e.state is not EvidenceState.REJECTED:
                decide(ws, e.id, state=EvidenceState.REJECTED, reason=f"{HELD}: {reason.strip()}", by=by)
                held.append(e.id)
        return {"formulation": name, "model": "particles", "held": held}
    if state["state"] == "proposed":
        _answered(ws, state["evidence_id"], by=by, what="the Weibull fit, as proposed")
        return {"formulation": name, "model": "weibull", "confirmed": state["evidence_id"]}
    taken = []
    for e in weibull:
        if e.state is EvidenceState.REJECTED and e.decision_reason.startswith(HELD):
            decide(ws, e.id, state=EvidenceState.ACCEPTED,
                   reason="the Weibull fit used after all (Inputs, D1)" + (f": {reason.strip()}" if reason.strip() else ""),
                   by=by)
            taken.append(e.id)
    return {"formulation": name, "model": "weibull", "taken": taken}


def _answered(ws: Workspace, evidence_id: str, *, by: str, what: str) -> None:
    """The proposal answered: a new version of the type item without it (the evidence register's own write)."""
    from modeler_project.evidence_register import EvidenceError, answer_proposal

    try:
        answer_proposal(ws, evidence_id, reason=f"release model answered on Inputs (D1): {what}", by=by)
    except EvidenceError as exc:
        raise ReleaseChoiceError(str(exc)) from exc


__all__ = ["HELD", "HELD_WHY", "ReleaseChoiceError", "release_states", "set_release_model"]
