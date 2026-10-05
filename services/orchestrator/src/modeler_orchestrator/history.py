"""The change ledger and the influence map (plan §12.3 N5, N6; T-54): which parameter change moved which verdict.

**Ledger.** Every change of the campaign's working parameter set (a fit, a joint refit, a feedback decision) is an
entry: the stage, what caused it, the parameters that changed (before → after), and — filled in as the studies are
judged again under the new parameter set — every study whose verdict changed (before → after, with the model set of
each). A verdict that changes is therefore always explained by the entry that introduced the parameter set it was
judged on. Trial estimates that were not kept (a joint fit the rules rejected) do not move the record.

**Influence map.** Parameters × studies. The structural layer says which studies' simulations contain a parameter
(compound parameters: all; a formulation's parameters: the studies of that product; food parameters: fed studies),
from the signed MAP's scenarios. The quantitative layer is the normalized local sensitivity of AUC and Cmax from the
engine's sensitivity task (S6), where it ran. Stored per model set; drawn as a heat map on the monitor.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse


def _cpf_records(uri: str) -> dict[str, dict[str, Any]] | None:
    path = Path(unquote(urlparse(uri).path))
    if urlparse(uri).scheme != "file" or not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return {p["id"]: p for p in doc.get("parameters", [])}


def parameter_changes(before_uri: str, after_uri: str) -> list[dict[str, Any]] | None:
    """What changed between two CPFs: value, status or the stage that fitted it (None: a CPF is not readable here)."""
    before, after = _cpf_records(before_uri), _cpf_records(after_uri)
    if before is None or after is None:
        return None
    out = []
    for pid in sorted(set(before) | set(after)):
        b, a = before.get(pid, {}), after.get(pid, {})
        if (b.get("value"), b.get("status"), b.get("fitted_at_stage")) != (a.get("value"), a.get("status"), a.get("fitted_at_stage")):
            out.append({"parameter": pid, "before": b.get("value"), "after": a.get("value"), "unit": a.get("unit") or b.get("unit"),
                        "status": a.get("status"), "fitted_at_stage": a.get("fitted_at_stage")})
    return out


def study_verdict(study: dict[str, Any]) -> str:
    """A study's verdict from a round's per-study metrics: fail if AUC or Cmax is out of limits, pass if judged."""
    flags = [study.get("auc_in_limits"), study.get("cmax_in_limits")]
    if any(f is False for f in flags):
        return "fail"
    return "pass" if any(f is True for f in flags) else "not judged"


class Ledger:
    """The campaign's change ledger (kept on the monitor record, so a resumed campaign continues it)."""

    def __init__(self, entries: list[dict] | None = None, verdicts: dict[str, dict] | None = None, current: str = ""):
        self.entries: list[dict] = list(entries or [])
        self.verdicts: dict[str, dict] = dict(verdicts or {})   # study -> its latest verdict on the working set
        self.current = current                                   # the working parameter set (CPF content hash)

    def change(self, *, stage: str, kind: str, reason: str, before: tuple[str, str], after: tuple[str, str]) -> dict:
        """A new working parameter set: (uri, sha) before and after."""
        changes = parameter_changes(before[0], after[0])
        entry = {"seq": len(self.entries) + 1, "stage": stage, "kind": kind, "reason": reason, "cpf_before": before[1],
                 "cpf_after": after[1], "changes": changes or [], "verdicts": [],
                 **({"note": "the CPFs are not readable here; parameter changes not listed"} if changes is None else {})}
        self.entries.append(entry)
        self.current = after[1]
        return entry

    def judged(self, *, stage: str, cpf_sha: str, model_set: str | None, studies: list[dict]) -> None:
        """A round judged on `cpf_sha`: verdicts that changed since the study was last judged attach to the entry
        that introduced this parameter set. Rounds on any other set (a trial estimate) leave the record alone."""
        if self.current and cpf_sha != self.current:
            return
        self.current = cpf_sha
        entry = next((e for e in reversed(self.entries) if e["cpf_after"] == cpf_sha), None)
        for study in studies:
            sid, verdict = str(study.get("study_id")), study_verdict(study)
            previous = self.verdicts.get(sid)
            if previous and previous["cpf"] != cpf_sha and previous["verdict"] != verdict and entry is not None:
                entry["verdicts"].append({"study_id": sid, "stage": stage, "before": previous["verdict"], "after": verdict,
                                          "model_set_before": previous.get("model_set"), "model_set_after": model_set})
            self.verdicts[sid] = {"verdict": verdict, "cpf": cpf_sha, "model_set": model_set, "stage": stage}

    def to_content(self) -> dict[str, Any]:
        return {"entries": self.entries, "verdicts": self.verdicts, "current": self.current}

    @classmethod
    def from_content(cls, content: dict[str, Any] | None) -> Ledger:
        content = content or {}
        return cls(content.get("entries"), content.get("verdicts"), content.get("current", ""))


def _first(values: dict[str, float], *names: str) -> float | None:
    return next((values[n] for n in names if values.get(n) is not None), None)


def _contains(pid: str, scenarios: list[dict[str, Any]]) -> bool:
    """Whether a study's simulations contain the parameter (from the MAP's scenarios)."""
    if pid.startswith("form."):
        name = pid.split(".")[1]
        # a scenario without a name uses the CPF's only formulation (`resolve_formulation_name`)
        return any(s.get("formulation_name") == name or (s.get("formulation_name") is None and s.get("route") == "oral"
                                                         and s.get("formulation") != "solution") for s in scenarios)
    if pid.startswith("food."):
        return any(s.get("food_state") == "fed" for s in scenarios)
    return True


def influence_map(map_doc: dict[str, Any], cpf_uri: str, prediction: dict | None, *, cpf_sha: str) -> dict[str, Any]:
    """Parameters (fitted, fittable or predicted) × the studies the MAP simulates, structural and quantitative.
    The quantitative cell is the engine's normalized sensitivity (AUC over the observed window, else to infinity;
    Cmax), present only for the parameters S6 ranked among a study's most influential."""
    records = _cpf_records(cpf_uri) or {}
    scenarios = map_doc.get("scenarios", [])
    studies = sorted({s["study_id"] for s in scenarios})
    of_study = {sid: [s for s in scenarios if s["study_id"] == sid] for sid in studies}
    params = sorted(pid for pid, r in records.items() if r.get("status") in ("FITTED", "PREDICTED") or r.get("fit_policy"))
    sensitivity = (prediction or {}).get("sensitivity") or {}
    cells: dict[str, dict[str, dict[str, Any]]] = {}
    for pid in params:
        row = {}
        for sid in studies:
            values = {r["pk_parameter"]: r["value"] for r in sensitivity.get(sid, []) if r.get("parameter") == pid}
            row[sid] = {"structural": _contains(pid, of_study[sid]), "auc": _first(values, "AUC_tEnd", "AUC_inf"),
                        "cmax": _first(values, "C_max")}
        cells[pid] = row
    return {"cpf_sha256": cpf_sha, "parameters": params, "studies": studies, "cells": cells,
            "quantitative": bool(sensitivity), "status": {pid: records[pid].get("status") for pid in params},
            "fitted_at_stage": {pid: records[pid].get("fitted_at_stage") for pid in params}}
