"""The estimation plan's bounds (redesign §3.3; D-34): the bounds proposed for a parameter a person frees, and what the
plan's validator checks about a fit's bounds.

The proposal follows MS-01 §2.2's "Default bounds" (`fit_bounds.yaml`, a provisional data rule UNVERIFIED until the SME
signs): relative bounds around the start value, the start value ± a margin, or absolute bounds as written (only when the
parameter is stored in MS-01's unit), each clipped to the registry's physical bounds (`parameters.physical_bounds`,
only when the parameter is stored in the registry's unit). A parameter MS-01 gives no default for gets the redesign's
0.1–10× the start value. MS-01 keeps a measured fu fixed: nothing is proposed for it.

Nothing here changes the plan: a proposal fills the form a person confirms with a reason (`plan.set_fit`).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from functools import lru_cache
from importlib import resources
from typing import Any, Literal

import yaml

from pbpk_domain import parameters
from pbpk_domain.cpf.models import ParameterRecord, ParameterStatus

Scale = Literal["linear", "log"]
_DIMENSIONLESS = {"", "-", "–", "none", "dimensionless", "fraction", "log units", "u"}


@dataclass(frozen=True)
class BoundsRule:
    id: str
    unit: str
    ms01: str
    by_kind: dict[str, Any]          # measured / predicted / any → "fixed" or {relative|additive|absolute: …}
    row: str = ""

    def matches(self, cpf_id: str) -> bool:
        if "{" not in self.id:
            return parameters.canonical(cpf_id) == parameters.canonical(self.id)
        pattern = "^" + re.sub(r"\\\{[a-z]+\\\}", "[^.]+", re.escape(self.id)) + "$"
        return re.match(pattern, cpf_id) is not None


@dataclass(frozen=True)
class Rule:
    version: str
    status: str
    source: str
    fallback: dict[str, Any]
    bounds: tuple[BoundsRule, ...]


@lru_cache
def rule() -> Rule:
    raw = yaml.safe_load(resources.files("modeler_project").joinpath("fit_bounds.yaml").read_text(encoding="utf-8"))
    rows = tuple(BoundsRule(id=r["id"], unit=str(r["unit"]), ms01=str(r["ms01"]), row=str(r.get("row", "")),
                            by_kind={k: r[k] for k in ("measured", "predicted", "any") if k in r}) for r in raw["bounds"])
    return Rule(version=str(raw["version"]), status=raw["status"], source=raw["source"], fallback=raw["fallback"], bounds=rows)


@dataclass(frozen=True)
class BoundsProposal:
    """The bounds proposed for one parameter, and on what basis. No bounds (`lower` None) with a note when none can be
    proposed; `fixed` when MS-01 keeps the parameter fixed."""

    lower: float | None
    upper: float | None
    scale: Scale | None
    basis: str                       # e.g. "MS-01 §2.2, predicted: [0.5×, 2×]" or "no MS-01 default: 0.1–10×"
    note: str = ""
    fixed: bool = False
    from_ms01: bool = False

    def to_content(self) -> dict[str, Any]:
        return asdict(self)


def unit_key(unit: str | None) -> str:
    """A unit as compared here: case and µ/μ folded, and every way of writing "dimensionless" the same."""
    text = (unit or "").strip().lower().replace("μ", "µ")
    return "" if text in _DIMENSIONLESS else text


def _ms01_row(record_id: str) -> BoundsRule | None:
    return next((r for r in rule().bounds if r.matches(record_id)), None)


def _kind(record: ParameterRecord) -> str:
    return "predicted" if record.status is ParameterStatus.PREDICTED else "measured"


def _storage_unit(cpf_id: str) -> str | None | bool:
    """The unit the registry's physical bounds are written in (False when the registry has none for this id)."""
    canonical = parameters.canonical(cpf_id)
    entry = next((r for r in parameters.registry().parameters if r.key == canonical and r.suffix is None), None)
    return entry.storage if entry and entry.physical_bounds else False


def physical_range(record: ParameterRecord) -> tuple[float, float] | None:
    """The registry's physical bounds for this parameter, when it is stored in the registry's unit (else None: bounds
    in another unit are never applied)."""
    bounds = parameters.physical_bounds().get(parameters.canonical(record.id))
    storage = _storage_unit(record.id)
    if bounds is None or storage is False or unit_key(record.unit) != unit_key(storage or ""):
        return None
    return bounds


def _fmt(x: float) -> str:
    return f"{x:g}"


def proposed_bounds(record: ParameterRecord) -> BoundsProposal:
    """MS-01 §2.2's default bounds for this parameter around its start value (`fit_bounds.yaml`), clipped to the physical
    bounds; the redesign's 0.1–10× when MS-01 gives none."""
    if not isinstance(record.value, int | float) or isinstance(record.value, bool):
        return BoundsProposal(None, None, None, "", note="not a number: nothing to fit")
    start = float(record.value)
    row = _ms01_row(record.id)
    kind = _kind(record)
    spec = (row.by_kind.get(kind) or row.by_kind.get("any")) if row else None
    label = f"MS-01 §2.2, {kind}" if row is not None and kind in row.by_kind else "MS-01 §2.2"
    note = ""
    if row is not None and spec == "fixed":
        return BoundsProposal(None, None, None, f"{label}: fixed", fixed=True, from_ms01=True,
                              note=f"MS-01 §2.2 keeps a {kind} {record.id} fixed ({row.ms01})")
    if row is not None and spec and "absolute" in spec and unit_key(record.unit) != unit_key(row.unit):
        note = (f"MS-01's default is in {row.unit}; this value is in {record.unit or 'no unit'}, so the "
                "0.1–10× default is proposed instead")
        spec = None
    from_ms01 = row is not None and bool(spec)
    if not spec:
        spec = rule().fallback
    if "relative" in spec:
        lo_f, hi_f = (float(x) for x in spec["relative"])
        lower, upper, scale = start * lo_f, start * hi_f, "log"
        basis = f"[{_fmt(lo_f)}×, {_fmt(hi_f)}×] the start value"
    elif "additive" in spec:
        margin = float(spec["additive"])
        lower, upper, scale = start - margin, start + margin, "linear"
        basis = f"the start value ± {_fmt(margin)}"
    else:
        lower, upper = (float(x) for x in spec["absolute"])
        scale = "log" if lower > 0 else "linear"
        unit = row.unit if row and unit_key(row.unit) else ""
        basis = f"[{_fmt(lower)}, {_fmt(upper)}] {unit}".strip()
    basis = f"{label}: {basis}" if from_ms01 else f"no MS-01 default: {basis}"
    physical = physical_range(record)
    if physical is not None and (lower < physical[0] or upper > physical[1]):
        lower, upper = max(lower, physical[0]), min(upper, physical[1])
        note = (note + "; " if note else "") + f"clipped to the physical bounds [{_fmt(physical[0])}, {_fmt(physical[1])}]"
    if scale == "log" and lower <= 0:
        return BoundsProposal(None, None, None, basis, from_ms01=from_ms01,
                              note=(note + "; " if note else "") + "a log scale needs a positive start value: set the bounds")
    if not lower < upper:
        return BoundsProposal(None, None, None, basis, from_ms01=from_ms01,
                              note=(note + "; " if note else "") + "the bounds have no width at this start value: set them")
    if not lower <= start <= upper:
        return BoundsProposal(None, None, None, basis, from_ms01=from_ms01,
                              note=(note + "; " if note else "") + f"the start value {_fmt(start)} lies outside "
                                   f"[{_fmt(lower)}, {_fmt(upper)}]: check the value or set the bounds")
    return BoundsProposal(float(f"{lower:.6g}"), float(f"{upper:.6g}"), scale, basis, note=note, from_ms01=from_ms01)  # type: ignore[arg-type]


def fit_findings(record: ParameterRecord, lower: float, upper: float) -> list[tuple[str, str, str]]:
    """What the validator says about a fit's bounds beyond the plan's own rules: (severity, rule, message).
    - error `fit-plausible`: a bound beyond the physical bounds (MS-01 §2.2: never widen them beyond plausibility);
    - warning `fit-default`: wider than MS-01's default (the MAP may narrow it; widening is said and acknowledged);
    - warning `fit-fixed`: MS-01 keeps this parameter fixed."""
    out: list[tuple[str, str, str]] = []
    physical = physical_range(record)
    if physical is not None and (lower < physical[0] or upper > physical[1]):
        message = (f"{record.id}: the bounds [{_fmt(lower)}, {_fmt(upper)}] reach beyond the physical bounds "
                   f"[{_fmt(physical[0])}, {_fmt(physical[1])}] (MS-01 §2.2: never wider than plausibility)")
        out.append(("error", "fit-plausible", message))
    proposal = proposed_bounds(record)
    if proposal.fixed:
        out.append(("warning", "fit-fixed", f"{record.id}: {proposal.note}; estimating it is a departure from MS-01"))
    elif proposal.from_ms01 and proposal.lower is not None and proposal.upper is not None:
        def slack(x: float) -> float:   # the proposal is rounded to 6 significant digits; a sign-safe margin
            return 1e-6 * max(1.0, abs(x))

        if lower < proposal.lower - slack(proposal.lower) or upper > proposal.upper + slack(proposal.upper):
            message = (f"{record.id}: the bounds [{_fmt(lower)}, {_fmt(upper)}] are wider than MS-01's default "
                       f"[{_fmt(proposal.lower)}, {_fmt(proposal.upper)}] ({proposal.basis}); say why")
            out.append(("warning", "fit-default", message))
    return out
