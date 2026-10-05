"""External-validation feedback: learn and confirm (plan §12.3 N4, §12.4; decisions D-05, D-06; T-55).

When S5 fails the campaign stops for a signed decision (FEEDBACK_PENDING). Code diagnoses each failing external
study: the metric that failed, the direction, its class, the parameters that act on it (the influence map, N5) and how
it differs from the training studies in a documented way. The person then chooses:

* **limitation** (`accept_best`): the failure is recorded as a limitation, the context of use restricted, and the
  campaign continues to the S4/S5 signature (MS-01 §6.6 path 1);
* **learn**: the failing studies move to the internal set — a MAP deviation, drafted here and signed by the decision
  (ICH M15 §4.2) — and the campaign re-enters at the stage their class trains, runs SJ with them, S4 on every internal
  study, and S5 on the external studies left (MS-01 §6.6 path 2, executed by the engine);
* **new evidence**: one parameter is replaced by a better *measured* value (never fitted to the failing study); the
  whole chain re-runs from the new CPF and S5 re-judges the same studies, flagged as prompted by S5 (D-06);
* **stop** (`abort`).

Guardrails (code, not advice): a learned study is spent (internal from then on) and external claims rest only on the
studies left; a class with no other external study cannot learn — its external validation is "not achievable" and
says so; one learn cycle per class (D-05), a further one only with a signed deviation reason; every cycle is in the
change ledger and the MAR's model development history.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from modeler_orchestrator.history import study_verdict

LEARN_CAP_PER_CLASS = 1  # D-05: one learn cycle per class; more only by a signed deviation
FEEDBACK_ACTIONS = ("accept_best", "learn", "new_evidence", "abort")
PROMPTED_BY_S5 = "prompted by S5"


def _path(uri: str) -> Path:
    return Path(unquote(urlparse(uri).path))


def _ratio(pred: Any, obs: Any) -> float | None:
    return pred / obs if isinstance(pred, int | float) and isinstance(obs, int | float) and obs > 0 else None


def learn_stage(scenario: dict[str, Any], scenarios: list[dict[str, Any]], cpf: Any = None) -> str:
    """The stage a learned study trains, as the MAP would have placed it (plan §12.3 N4): IV → S1; fed → S3; another
    formulation → S3 when a solution study trains S2 and the product's release is not 'dissolved' (MS-01 §6.3), else
    S2; another dose or a multiple-dose regimen → S2."""
    if scenario.get("route") != "oral":
        return "S1"
    if scenario.get("food_state") == "fed":
        return "S3"
    solution_trains = any(s.get("stage") == "S2" and s.get("formulation") == "solution" for s in scenarios)
    if scenario.get("formulation") == "solution" or not solution_trains:
        return "S2"
    if cpf is not None:
        from pbpk_domain.cpf.formulations import DISSOLVED, FormulationError, cpf_formulation, resolve_formulation_name

        try:
            name, _ = resolve_formulation_name(cpf, scenario.get("formulation_name"))
            if cpf_formulation(cpf, name).type == DISSOLVED:
                return "S2"
        except FormulationError:
            pass
    return "S3"


def _differences(scenario: dict[str, Any], scenarios: list[dict[str, Any]]) -> list[str]:
    """How an external study differs from the training studies, in documented terms (route, food, product, dose)."""
    train = [s for s in scenarios if s.get("stage") in ("S1", "S2", "S3")]
    out = []
    if scenario.get("food_state") == "fed" and not any(s.get("food_state") == "fed" for s in train):
        out.append("fed, and no fed study trains the model")
    same_route = [s for s in train if s.get("route") == scenario.get("route")]
    if scenario.get("route") == "oral" and scenario.get("formulation") not in {s.get("formulation") for s in same_route}:
        out.append(f"formulation {scenario.get('formulation')} is not among the trained formulations")
    doses = [s["dose_mg"] for s in same_route if isinstance(s.get("dose_mg"), int | float)]
    dose = scenario.get("dose_mg")
    if doses and isinstance(dose, int | float) and not min(doses) <= dose <= max(doses):
        out.append(f"dose {dose:g} mg is outside the trained range {min(doses):g}–{max(doses):g} mg")
    if (scenario.get("n_doses") or 1) > 1 and not any((s.get("n_doses") or 1) > 1 for s in same_route):
        out.append("multiple dose; every training study is a single dose")
    return out


def _influences(study_id: str, influence: dict | None, limit: int = 5) -> list[dict[str, Any]]:
    """The parameters acting on the study: by sensitivity when the engine ran it, else every one in its simulation."""
    cells = (influence or {}).get("cells", {})
    rows = [{"parameter": p, "auc": c.get("auc"), "cmax": c.get("cmax")}
            for p, by_study in cells.items() if (c := by_study.get(study_id)) and c.get("structural")]
    rows.sort(key=lambda r: max(abs(r["auc"] or 0), abs(r["cmax"] or 0)), reverse=True)
    return rows[:limit]


def diagnose(map_doc: dict[str, Any], studies: list[dict[str, Any]], *, influence: dict | None,
             history: list[dict[str, Any]], cpf: Any = None) -> dict[str, Any]:
    """The S5 failure, study by study and class by class, and the decisions it allows."""
    scenarios = map_doc.get("scenarios", [])
    s5 = {s["study_id"]: s for s in scenarios if s.get("stage") == "S5"}
    klass = {s["study_id"]: s.get("study_class", "") for s in map_doc.get("studies", [])}
    failing = []
    for st in studies:
        sid = str(st.get("study_id"))
        if sid not in s5 or study_verdict(st) != "fail":
            continue
        ratios = {"AUC": _ratio(st.get("predicted_auc"), st.get("observed_auc")),
                  "Cmax": _ratio(st.get("predicted_cmax"), st.get("observed_cmax"))}
        failed = [q for q, flag in (("AUC", st.get("auc_in_limits")), ("Cmax", st.get("cmax_in_limits"))) if flag is False]
        directions = {"over-predicted" if (ratios[q] or 1) > 1 else "under-predicted" for q in failed if ratios[q]}
        failing.append({
            "study_id": sid, "class": klass.get(sid, ""), "group": st.get("group"), "failed": failed,
            "ratio": {q: round(r, 3) for q, r in ratios.items() if r is not None},
            "direction": " and ".join(sorted(directions)) or "not determined",
            "learn_stage": learn_stage(s5[sid], scenarios, cpf), "differences": _differences(s5[sid], scenarios),
            "influences": _influences(sid, influence),
        })
    failing_ids = {f["study_id"] for f in failing}
    classes: dict[str, dict[str, Any]] = {}
    for f in failing:
        c = classes.setdefault(f["class"], {"failing": [], "unspent": [], "cycles": 0})
        c["failing"].append(f["study_id"])
    for name, c in classes.items():
        c["unspent"] = sorted(sid for sid in s5 if klass.get(sid) == name and sid not in failing_ids)
        c["cycles"] = sum(1 for h in history if h.get("action") == "learn" and name in h.get("classes", []))
        if not c["unspent"]:
            c["learn"] = {"possible": False, "reason": f"external validation of {name} not achievable: no other external "
                                                         f"{name} study is left to confirm a learned model"}
        elif c["cycles"] >= LEARN_CAP_PER_CLASS:
            c["learn"] = {"possible": True, "needs_deviation": True,
                          "reason": f"{name} already had {c['cycles']} learn cycle(s) (cap {LEARN_CAP_PER_CLASS}, D-05): "
                                    "another needs a signed deviation reason"}
        else:
            c["learn"] = {"possible": True, "reason": f"confirmed afterwards on {', '.join(c['unspent'])}"}
    learnable = [n for n, c in classes.items() if c["learn"]["possible"]]
    options = [
        {"id": "accept_best", "label": "Record a limitation and continue (restrict the context of use, MS-01 §6.6)",
         "requiresSignature": True},
        {"id": "learn", "label": "Learn: move the failing studies to the internal set and re-run from the stage they train "
                                 "(a MAP deviation; S5 then judges the external studies left)", "requiresSignature": True,
         **({} if learnable else {"disabled": "; ".join(c["learn"]["reason"] for c in classes.values()) or "no failing study"})},
        {"id": "new_evidence", "label": "New evidence: replace one parameter by a measured value and re-run the chain "
                                        f"(S5 re-judges the same studies, flagged '{PROMPTED_BY_S5}')", "requiresSignature": True},
        {"id": "abort", "label": "Stop the campaign", "requiresSignature": True},
    ]
    not_achievable = [c["learn"]["reason"] for c in classes.values() if not c["learn"]["possible"]]
    return {"failing": failing, "classes": classes, "options": options, "notAchievable": not_achievable}


def check_learn(learn: list[str], diagnosis: dict[str, Any], *, beyond_cap: str = "") -> list[str]:
    """The guardrails of a learn decision (ValueError when one forbids it); returns the classes it learns."""
    by_id = {f["study_id"]: f for f in diagnosis.get("failing", [])}
    if not learn:  # nothing named and no failing study's class may learn
        raise ValueError("; ".join(diagnosis.get("notAchievable", [])) or "no failing study to learn")
    unknown = [s for s in learn if s not in by_id]
    if unknown:
        raise ValueError(f"only studies that failed S5 can be learned (not: {', '.join(unknown)})")
    classes = sorted({by_id[s]["class"] for s in learn})
    for name in classes:
        c = diagnosis["classes"][name]
        left = [s for s in c["unspent"] if s not in learn]
        if not c["learn"]["possible"] or not left:
            raise ValueError(c["learn"]["reason"] if not c["learn"]["possible"]
                             else f"external validation of {name} not achievable: no external study would be left")
        if c["learn"].get("needs_deviation") and not beyond_cap.strip():
            raise ValueError(c["learn"]["reason"])
    return classes


def learn_map(map_uri: str, learn: list[str], diagnosis: dict[str, Any], *, cycle: int, reason: str, signature_id: str,
              printed_name: str, beyond_cap: str = "") -> tuple[str, str, dict[str, Any]]:
    """The MAP deviation for a learn decision: the studies move from external (S5) to internal (their training stage
    and S4); the signed MAP is revised (new version, superseding it) and signed by the decision. Raises ValueError
    when a guardrail forbids it. Returns (uri, sha256 of the file, the deviation record)."""
    from pbpk_domain.campaign.map import MapDocument

    classes = check_learn(learn, diagnosis, beyond_cap=beyond_cap)
    by_id = {f["study_id"]: f for f in diagnosis.get("failing", [])}
    doc = MapDocument.model_validate_json(_path(map_uri).read_text(encoding="utf-8"))
    stages = {s: by_id[s]["learn_stage"] for s in learn}
    scenarios = []
    for sc in doc.scenarios:
        if sc.study_id in stages and sc.stage == "S5":
            scenarios += [sc.model_copy(update={"stage": stages[sc.study_id]}), sc.model_copy(update={"stage": "S4"})]
        else:
            scenarios.append(sc)
    studies = tuple(s.model_copy(update={"assignment": "INTERNAL"}) if s.study_id in stages else s for s in doc.studies)
    left = {n: [s for s in diagnosis["classes"][n]["unspent"] if s not in learn] for n in classes}
    statement = (f"Deviation (feedback cycle {cycle}, signed {signature_id}): "
                 + "; ".join(f"{s} moved from external to internal (trains {k})" for s, k in stages.items())
                 + f" after failing S5. Reason: {reason or 'not given'}. External claims for "
                 + "; ".join(f"{n} rest on {', '.join(v)}" for n, v in left.items()) + " only."
                 + (f" Beyond the learn-cycle cap (D-05): {beyond_cap.strip()}" if beyond_cap.strip() else ""))
    revised = doc.revise(studies=studies, scenarios=tuple(scenarios),
                         split_rationale=(*doc.split_rationale, statement),
                         split_limitations=(*doc.split_limitations, statement))
    signed = revised.sign(printed_name=printed_name, signature_id=signature_id)
    data = signed.model_dump_json().encode("utf-8")
    out = _path(map_uri).with_name(f"map-cycle{cycle}.json")
    out.write_bytes(data)
    deviation = {"cycle": cycle, "kind": "learn", "studies": list(learn), "stages": stages, "classes": classes,
                 "map_version": signed.version, "supersedes": signed.supersedes_sha256, "signature_id": signature_id,
                 "statement": statement, "beyond_cap": beyond_cap.strip() or None}
    return out.as_uri(), hashlib.sha256(data).hexdigest(), deviation


def check_evidence(cpf_uri: str, *, parameter: str, value: float, unit: str | None, reference: str):
    """The guardrails of new evidence (ValueError when one forbids it): the parameter exists and is numeric, the
    value is in the CPF's own unit — no conversion is made — inside its plausibility range, with its source.
    Returns (the CPF, the replacement record)."""
    from pbpk_domain.cpf import CPF, ParameterRecord, ParameterStatus, Provenance

    if not reference.strip():
        raise ValueError("new evidence needs its source (a reference or the client's document)")
    cpf = CPF.model_validate_json(_path(cpf_uri).read_text(encoding="utf-8"))
    record = cpf.get(parameter)
    if record is None:
        raise ValueError(f"the CPF has no parameter {parameter!r}")
    if isinstance(record.value, str):
        raise ValueError(f"{parameter} is categorical; new evidence replaces a numeric value")  # noqa: TRY004 - a decision input (422)
    if (unit or None) != (record.unit or None):
        raise ValueError(f"{parameter} is stored in {record.unit or 'no unit'}; give the value in that unit (no conversion "
                         "is made)")
    p = record.plausibility
    if p is not None and not p.lower <= value <= p.upper:
        raise ValueError(f"{value} is outside {parameter}'s plausibility range {p.lower}–{p.upper}")
    replaced = ParameterRecord.model_validate({
        **record.model_dump(), "value": float(value), "status": ParameterStatus.FIXED, "fitted_at_stage": None,
        "fit_policy": None, "uncertainty": None,
        "provenance": Provenance(source_type="measured", reference=reference.strip(),
                                 supersedes=f"{record.value} ({record.status.value})").model_dump(),
    })
    return cpf, replaced


def new_evidence_cpf(cpf_uri: str, *, parameter: str, value: float, unit: str | None, reference: str, cycle: int,
                     campaign_id: str, failing: list[str]) -> tuple[str, str]:
    """CPF vN+1 with one parameter replaced by a measured value (D-06), fixed so it is not fitted again."""
    cpf, replaced = check_evidence(cpf_uri, parameter=parameter, value=value, unit=unit, reference=reference)
    updated = cpf.replace(replaced, note=f"feedback cycle {cycle}: {parameter} replaced by a measured value "
                                         f"({reference.strip()}), {PROMPTED_BY_S5} ({', '.join(failing)})")
    data = updated.model_dump_json().encode("utf-8")
    out = _path(cpf_uri).parent / f"{campaign_id}-evidence-c{cycle}.json"
    out.write_bytes(data)
    return out.as_uri(), hashlib.sha256(data).hexdigest()


def decision_digest(campaign_id: str, stage: str, action: str, payload: dict[str, Any] | None) -> str:
    """What a feedback signature binds: the decision and its content (studies learned, the evidence given)."""
    body = json.dumps({"campaign": campaign_id, "stage": stage, "action": action, "payload": payload or {}}, sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()
