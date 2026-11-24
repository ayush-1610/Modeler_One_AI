"""The client's NCA reproduced, its method found (plan 2026-11-24 §8 feature 3).

Where our NCA and the client's differ, code computes every profile again with each combination of the settings a
client may have used (`dataroom_rules.yaml` nca.reproduce: the integration rule, nominal or actual times, the BLQ rule,
the λz window), keeps the combination that reproduces most of the client's values for the whole study, and puts each
value in a tier: reproduced with our own settings (pass), reproduced only with the settings found (explained), within
the investigate tier (a setting differs), or beyond it under every setting tried (the data differ: ask the client).
The tiers are the literature review's proposal (docs/research/2026-11-24-clinical-pk-data-curation.md §3), UNVERIFIED.

The NCA itself is `pbpk_domain.nca` (its `integration` and `terminal_points` options); nothing here re-implements it.
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from modeler_project.dataroom.model import NcaReproduction, NcaSettings, Sample
from modeler_project.dataroom.rules import BlqRule, Rules
from pbpk_domain.nca import NcaResult, nca

ROLES = ("cmax", "tmax", "auc_t", "auc_inf", "t_half", "lambda_z")
_LAMBDA_ROLES = ("auc_inf", "t_half", "lambda_z")
DIMENSIONS = ("integration", "time_basis", "blq", "lambda_z")
DIMENSION_WORDS = {"integration": "the integration rule", "time_basis": "the time basis", "blq": "the BLQ rule",
                   "lambda_z": "the λz window"}
# a percentage difference counted in the search is capped, so one wild value does not choose the settings
_CAP = 100.0


@dataclass(frozen=True)
class Variant:
    integration: str          # "linear-up/log-down" | "linear"
    time_basis: str           # "nominal" | "actual"
    blq: int                  # index into the rules' BLQ rules
    lambda_z: str | int       # "best_fit" | the last n points

    def get(self, dimension: str) -> str | int:
        return getattr(self, dimension)

    def but(self, dimension: str, value: str | int) -> Variant:
        return Variant(**{**self.__dict__, dimension: value})


def profile_points(samples: Sequence[Sample], *, time_basis: str, blq: BlqRule,
                   lloq: float | None) -> tuple[list[float], list[float]]:
    """A profile's points for NCA under one setting: nominal or actual times (a pre-dose sample stays at its nominal
    time), and below the LLOQ before and after the first quantifiable sample as the rule says. A missing sample is never
    a point."""
    out: list[tuple[float, float]] = []
    seen = False
    for s in sorted(samples, key=lambda s: s.time_h):
        if s.missing:
            continue
        t = s.actual_h if time_basis == "actual" and s.actual_h is not None and s.time_h > 0 else s.time_h
        if s.value is not None and s.value > 0:
            seen = True
            out.append((t, s.value))
        elif not seen:
            if blq.before == "zero":
                out.append((t, 0.0))
        elif blq.after == "zero":
            out.append((t, 0.0))
        elif blq.after == "half_lloq" and lloq:
            out.append((t, lloq / 2))
    out.sort(key=lambda p: p[0])
    return [t for t, _ in out], [c for _, c in out]


def _values(res: NcaResult) -> dict[str, float | None]:
    return {"cmax": res.c_max, "tmax": res.t_max, "auc_t": res.auc_last, "auc_inf": res.auc_inf, "t_half": res.t_half,
            "lambda_z": res.lambda_z}


def _difference(role: str, ours: float | None, theirs: float) -> float | None:
    """Ours − the client's: hours for Tmax, else percent of the client's value."""
    if ours is None:
        return None
    if role == "tmax":
        return round(ours - theirs, 4)
    return None if theirs == 0 else round(100.0 * (ours - theirs) / theirs, 3)


@dataclass
class Profile:
    key: tuple[str, str]
    samples: Sequence[Sample]
    client: Mapping[str, float]


@dataclass(frozen=True)
class Outcome:
    """One profile's result: the settings' values, its differences and each value's tier."""

    values: dict[str, float | None]
    differences: dict[str, float]
    tiers: dict[str, str]
    note: str = ""


class Reproduction:
    """The search over the settings for one study, and each profile's outcome under the settings found."""

    def __init__(self, profiles: Sequence[Profile], rules: Rules, *, lloq: float | None) -> None:
        self.rules, self.lloq = rules, lloq
        cfg = rules.nca.reproduce
        self.profiles = [p for p in profiles if p.client]
        has_actual = any(s.actual_h is not None for p in self.profiles for s in p.samples)
        self.options: dict[str, list[str | int]] = {
            "integration": list(cfg.integration),
            "time_basis": [b for b in cfg.time_basis if b == "nominal" or has_actual] or ["nominal"],
            "blq": [i for i, r in enumerate(cfg.blq) if r.after != "half_lloq" or lloq],
            "lambda_z": list(cfg.lambda_z),
        }
        self.ours = Variant(*(self.options[d][0] for d in DIMENSIONS))   # type: ignore[arg-type]
        self._cache: dict[tuple[tuple[str, str], Variant], dict[str, float | None] | None] = {}

    # --- one profile under one setting ------------------------------------------------------------------------------

    def values(self, p: Profile, v: Variant) -> dict[str, float | None] | None:
        key = (p.key, v)
        if key not in self._cache:
            ts, cs = profile_points(p.samples, time_basis=v.time_basis, blq=self.rules.nca.reproduce.blq[v.blq],
                                    lloq=self.lloq)
            if len(ts) < 2 or sum(1 for c in cs if c > 0) < 3:
                self._cache[key] = None
            else:
                res = nca(ts, cs, integration=v.integration,  # type: ignore[arg-type]
                          terminal_points=None if v.lambda_z == "best_fit" else int(v.lambda_z))
                self._cache[key] = _values(res)
        return self._cache[key]

    def differences(self, p: Profile, v: Variant) -> dict[str, float]:
        got = self.values(p, v) or {}
        out = {}
        for role, theirs in p.client.items():
            if role in ROLES and (d := _difference(role, got.get(role), theirs)) is not None:
                out[role] = d
        return out

    def off(self, role: str, d: float | None) -> bool:
        if d is None:
            return True
        limit = self.rules.nca.tmax_tolerance_h if role == "tmax" else self.rules.nca.reproduce.pass_percent
        return abs(d) > limit + 1e-9

    def _score(self, v: Variant) -> tuple[int, float]:
        """How well a setting reproduces the study: the client's values it misses, then their summed difference."""
        missed, total = 0, 0.0
        for p in self.profiles:
            diffs = self.differences(p, v)
            for role in p.client:
                if role not in ROLES:
                    continue
                d = diffs.get(role)
                missed += self.off(role, d)
                if d is not None and role != "tmax":
                    total += min(abs(d), _CAP)
        return missed, round(total, 9)

    # --- the study ---------------------------------------------------------------------------------------------------

    def search(self) -> Variant:
        """The setting that reproduces most of the client's values (then the smallest summed difference); a tie keeps
        the rules' order, ours first."""
        variants = [Variant(*combo) for combo in itertools.product(*(self.options[d] for d in DIMENSIONS))]  # type: ignore[arg-type]
        return min(variants, key=self._score)

    def told_apart(self, found: Variant) -> tuple[tuple[str, ...], dict[str, str]]:
        """Which settings the client's values decide: changing one alone misses more of them. A setting the values
        do not decide is said, with why (no other choice; no value depends on it; the alternatives reproduce as many)."""
        best = self._score(found)
        decided, why = [], {}
        for dim in DIMENSIONS:
            others = [x for x in self.options[dim] if x != found.get(dim)]
            if not others:
                why[dim] = ("the data give no actual sampling times" if dim == "time_basis" else
                            "the study states no LLOQ" if dim == "blq" else "no other setting to try")
                continue
            scores = [self._score(found.but(dim, x)) for x in others]
            if all(s[0] > best[0] for s in scores):
                decided.append(dim)
            elif all(self._same(found, found.but(dim, x)) for x in others):
                why[dim] = "no value the client gives depends on it"
            else:
                why[dim] = "another setting reproduces as many of the client's values"
        return tuple(decided), why

    def _same(self, a: Variant, b: Variant) -> bool:
        """The two settings give every value the client gives alike."""
        for p in self.profiles:
            x, y = self.values(p, a) or {}, self.values(p, b) or {}
            if any(x.get(role) != y.get(role) for role in p.client if role in ROLES):
                return False
        return True

    def outcome(self, p: Profile, found: Variant) -> Outcome:
        """The profile's differences and tiers under the settings found; a profile whose λz-dependent values are off
        tries the other λz windows for itself (a λz window is chosen per subject in many analyses)."""
        cfg = self.rules.nca.reproduce
        used, note = found, ""
        diffs = self.differences(p, found)
        lam_off = [r for r in _LAMBDA_ROLES if r in p.client and self.off(r, diffs.get(r))]
        if lam_off:
            for window in self.options["lambda_z"]:
                if window == found.lambda_z:
                    continue
                trial = self.differences(p, found.but("lambda_z", window))
                if not any(self.off(r, trial.get(r)) for r in _LAMBDA_ROLES if r in p.client):
                    used = found.but("lambda_z", window)
                    diffs = {**diffs, **{r: trial[r] for r in _LAMBDA_ROLES if r in trial}}
                    note = f"λz over {lambda_words(window)} for this profile reproduces the client's"
                    break
        mine = self.differences(p, self.ours)
        tiers: dict[str, str] = {}
        variants = None
        for role in p.client:
            if role not in ROLES:
                continue
            d = diffs.get(role)
            if not self.off(role, mine.get(role)):
                tiers[role] = "pass"
            elif not self.off(role, d):
                tiers[role] = "explained"
            elif role != "tmax" and d is not None and abs(d) <= cfg.investigate_percent + 1e-9:
                tiers[role] = "investigate"
            else:
                if variants is None:
                    variants = [Variant(*c) for c in itertools.product(*(self.options[x] for x in DIMENSIONS))]  # type: ignore[arg-type]
                rescued = any(not self.off(role, self.differences(p, v).get(role)) for v in variants)
                # ours not computable (no terminal phase): nothing to compare, so investigate, never "the data differ"
                tiers[role] = "investigate" if rescued or d is None else "differ"
        return Outcome(values=self.values(p, used) or {}, differences=diffs, tiers=tiers, note=note)


def lambda_words(window: str | int) -> str:
    return "the best adjusted R²" if window == "best_fit" else f"the last {window} points"


def settings_words(v: Variant, rules: Rules) -> NcaSettings:
    return NcaSettings(integration="linear trapezoidal" if v.integration == "linear" else "linear-up/log-down",
                       time_basis=f"{v.time_basis} times", blq=rules.nca.reproduce.blq[v.blq].label(),
                       lambda_z=lambda_words(v.lambda_z))


def reproduction(profiles: Sequence[Profile], rules: Rules, *, lloq: float | None
                 ) -> tuple[NcaReproduction | None, dict[tuple[str, str], Outcome], Variant | None]:
    """The study's reproduction (None when the client gives no value to compare), each profile's outcome, and the
    settings found."""
    search = Reproduction(profiles, rules, lloq=lloq)
    if not search.profiles:
        return None, {}, None
    found = search.search()
    decided, not_told = search.told_apart(found)
    outcomes = {p.key: search.outcome(p, found) for p in search.profiles}
    counts = {t: sum(1 for o in outcomes.values() for x in o.tiers.values() if x == t)
              for t in ("pass", "explained", "investigate", "differ")}
    compared = sum(counts.values())
    cfg = rules.nca.reproduce
    words = settings_words(found, rules)
    parts = [words.integration, words.time_basis, words.blq, f"λz by {words.lambda_z}"]
    named = []
    for dim, part in zip(DIMENSIONS, parts, strict=True):
        named.append(part if dim in decided else f"{part} ({not_told.get(dim, 'not told apart')})")
    tiers = (f"≤ {cfg.pass_percent:g} % reproduced; {cfg.pass_percent:g}–{cfg.investigate_percent:g} % investigate (a "
             f"setting differs); > {cfg.investigate_percent:g} % under every setting tried: the data differ, ask "
             f"({rules.label()}: the literature's proposal, awaiting the SME)")
    tail = [f"{counts['pass'] + counts['explained']} of {compared} of the client's values reproduced within "
            f"{cfg.pass_percent:g} %" + (f" ({counts['explained']} only with these settings)" if counts["explained"] else "")]
    if counts["investigate"]:
        tail.append(f"{counts['investigate']} to investigate")
    if counts["differ"]:
        tail.append(f"{counts['differ']} beyond {cfg.investigate_percent:g} %: the data differ, ask the client")
    summary = "the client's NCA is reproduced with: " + "; ".join(named) + ". " + "; ".join(tail)
    return (NcaReproduction(settings=words, told_apart=decided, not_told=not_told, compared=compared,
                            passed=counts["pass"], explained=counts["explained"], investigate=counts["investigate"],
                            differ=counts["differ"], tiers=tiers, summary=summary),
            outcomes, found)
