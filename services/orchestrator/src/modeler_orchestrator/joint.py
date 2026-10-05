"""SJ joint refinement (plan §12.3 N3; MS-01 v1.1 §4 SJ, UNVERIFIED, owner-approved D-04; T-53).

After S3 — and whenever the no-regression gate (N2) finds that a later fit broke an earlier stage — one parameter
identification runs over the internal studies of the stages involved at once, refitting the parameters those stages
fitted, from their sequential estimates. Rules (D-04):

* bounds are the fit policies; a parameter fitted at S1 stays within its S1 95 % confidence interval (the compensation
  guard: an absorption misfit must not be absorbed by bending clearance) unless a signed decision widens it;
* the joint estimate is kept only if every internal study passes its gate and the agreement does not get worse
  (mean of the AUC and Cmax GMFE); otherwise the sequential parameter set stays and the attempt is recorded;
* each study is meant to contribute equally (D-04); PK-Sim weights per output mapping are not passed by the fit
  specification yet, so points are weighted equally until `run_pi.R` support is verified (known gap).

This module holds the pieces that are not engine work: which parameters, which bounds, which studies, and the score.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from pbpk_domain.campaign.map import FIT_STAGES

JOINT = "SJ"


def _path(uri: str) -> Path:
    return Path(unquote(urlparse(uri).path))


@dataclass(frozen=True)
class JointPlan:
    fit_ids: tuple[str, ...]
    bounds: dict[str, list[float]]          # the S1-CI guard, per parameter (absent: the fit policy's bounds)
    guarded: tuple[str, ...]                # parameters held within their S1 CI
    notes: tuple[str, ...] = ()


def joint_parameters(cpf: Any, stages: tuple[str, ...]) -> JointPlan:
    """The parameters `stages` fitted (status FITTED there, with a fit policy), and the S1-CI guard bounds."""
    ids, bounds, guarded, notes = [], {}, [], []
    for record in cpf.parameters:
        if record.status.value != "FITTED" or record.fitted_at_stage not in stages or record.fit_policy is None:
            continue
        ids.append(record.id)
        if record.fitted_at_stage == "S1":
            u = record.uncertainty
            if u is not None and u.ci95_lower is not None and u.ci95_upper is not None:
                lo, hi = max(record.fit_policy.lower, u.ci95_lower), min(record.fit_policy.upper, u.ci95_upper)
                if lo < hi:
                    bounds[record.id] = [lo, hi]
                    guarded.append(record.id)
                    continue
            notes.append(f"{record.id}: fitted at S1 without a 95 % CI; the S1-CI guard cannot hold it (fit policy bounds)")
    return JointPlan(tuple(ids), bounds, tuple(guarded), tuple(notes))


def joint_map(map_uri: str, stages: tuple[str, ...], *, tag: str) -> tuple[str, str, list[str]]:
    """A MAP whose scenarios are the training scenarios of `stages`, relabeled SJ, written next to the signed MAP
    (which is not changed): (uri, sha256, study ids). Evaluation reads a stage's scenarios by its name, so the joint
    round is judged on exactly these studies with their fitting role."""
    doc = json.loads(_path(map_uri).read_text(encoding="utf-8"))
    scenarios = [{**s, "stage": JOINT} for s in doc.get("scenarios", []) if s.get("stage") in stages and s["stage"] in FIT_STAGES]
    derived = {**doc, "scenarios": scenarios}
    out = _path(map_uri).with_name(f"map-{JOINT}-{tag}.json")
    data = json.dumps(derived, ensure_ascii=False).encode("utf-8")
    out.write_bytes(data)
    return out.as_uri(), hashlib.sha256(data).hexdigest(), [s["study_id"] for s in scenarios]


def agreement(evaluation: Any) -> float | None:
    """The score the joint estimate must not worsen: the mean of the AUC and Cmax GMFE (lower is better)."""
    values = [evaluation.metrics.get(q, {}).get("gmfe") for q in ("AUC", "Cmax")]
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None
