"""Exclusions flagged, never deleted (plan 2026-11-24 §8 feature 4).

Each flag is a `Problem` on the study naming the subject and the occasion, with its reason and the rule's limit
(`dataroom_rules.yaml` flags, the literature review's proposal, UNVERIFIED). A flagged profile stays in every set: the
sponsor's population with its flags, as regulators expect; a person decides what to leave out.

- FLAG_PREDOSE: a pre-dose concentration above the rules' % of the profile's Cmax (not on a multiple-dose study's later
  days, whose pre-dose sample is a trough);
- FLAG_AUC_EXTRAPOLATED: more of AUC0–inf extrapolated than the rules allow;
- FLAG_TERMINAL_SPAN: the λz points span fewer half-lives than the rules ask for a reliable t½;
- FLAG_SAMPLE_WINDOW: a sample taken outside the window around its nominal time, where the data give actual times;
- FLAG_VOMITING: vomiting at or before the rules' multiple of the arm's median Tmax, for immediate release, only where
  the delivery states the event (its file's words, never the agent's note).
"""

from __future__ import annotations

import re
import statistics
from collections.abc import Mapping, Sequence

from modeler_project.dataroom.model import CheckedFact, Problem, Sample
from modeler_project.dataroom.rules import Rules
from pbpk_domain.nca import NcaResult

_VOMIT = re.compile(r"(?i)\bvomit\w*|\bemesis\b|\bemetic\b")
_SUBJECT_WORDS = re.compile(r"(?i)\b(?:subjects?|patients?|volunteers?|participants?)\s*(?:no\.?|number|#)?\s*"
                            r"([A-Za-z]{0,4}[-\s]?\d[\w-]*(?:\s*(?:,|and|&)\s*[A-Za-z]{0,4}[-\s]?\d[\w-]*)*)")
_TIME = re.compile(r"(?i)(\d+(?:\.\d+)?)\s*(h|hr|hrs|hours?|min|mins|minutes?)\b")
_MODIFIED = re.compile(r"(?i)modified|extended|delayed|controlled|sustained|prolonged|enteric|gastro[-\s]?resistant")


def _hours(number: str, unit: str) -> float:
    return float(number) / (60.0 if unit.lower().startswith("min") else 1.0)


def vomiting_events(facts: Sequence[CheckedFact], subjects: Sequence[str]) -> list[tuple[str, CheckedFact, float | None]]:
    """Each subject a checked fact states vomited, with the time after the dose its quote writes (None: no time). The
    subject and time come from the quote, the file's words; the fact's value names the subjects of a subject list."""
    from modeler_project.dataroom.clinical import subject_id, subjects_in

    known = set(subjects)
    out: list[tuple[str, CheckedFact, float | None]] = []
    for f in facts:
        if not f.ok or not _VOMIT.search(f.fact.quote):
            continue
        quote = f.fact.quote
        named = [subject_id(x) for m in _SUBJECT_WORDS.finditer(quote) for x in re.split(r"\s*(?:,|and|&)\s*", m.group(1))]
        who = [s for s in named if s in known]
        if not who and f.fact.field in ("study.excluded_subjects", "study.vomiting"):
            who = [s for s in subjects_in(f.fact.value, subjects) if s in known]
        if not who and subject_id(f.fact.subject) in known:
            who = [subject_id(f.fact.subject)]
        after = quote[_VOMIT.search(quote).start():]  # type: ignore[union-attr]
        hit = _TIME.search(after)
        for s in dict.fromkeys(who):
            out.append((s, f, _hours(hit.group(1), hit.group(2)) if hit else None))
    return out


def exclusion_flags(*, by_profile: Mapping[tuple[str, str], Mapping[float, Sample]], treatment_of: Mapping[tuple[str, str], str],
                    results: Mapping[tuple[str, str], NcaResult], label: str, later_days: set[str],
                    facts: Sequence[CheckedFact], periods: Sequence[str], release: str, rules: Rules) -> list[Problem]:
    """The study's exclusion flags (module note). `later_days`: a multiple-dose study's occasions after the first, where
    a pre-dose sample is a trough and AUC to infinity and a single-dose t½ have no meaning; `release`: the products' release as the files
    write it ("" when not stated)."""
    from modeler_project.dataroom.clinical import _period_named

    cfg = rules.flags
    out: list[Problem] = []

    def where(key: tuple[str, str]) -> str:
        occasion = key[1].split(":", 1)[1]
        return f"subject {key[0]}" + (f", {label} {occasion}" if occasion else "")

    for key, got in sorted(by_profile.items()):
        occasion = key[1].split(":", 1)[1]
        res = results.get(key)
        cmax = res.c_max if res else max((x.value for x in got.values() if x.value is not None), default=None)
        # a pre-dose concentration above the rules' share of the profile's Cmax (carry-over, or a dose before the dose)
        if cmax and occasion not in later_days:
            for t, x in sorted(got.items()):
                if t <= 0 and x.value is not None and x.value > 0 and 100 * x.value / cmax > cfg.predose_max_percent_of_cmax:
                    out.append(Problem(code="FLAG_PREDOSE", where=x.chip, message=(
                        f"{where(key)}: pre-dose {x.text} is {100 * x.value / cmax:.1f} % of its Cmax ({cmax:.4g}), above "
                        f"{cfg.predose_max_percent_of_cmax:g} %: carry-over or an earlier dose; flagged, kept in the sets")))
        if res is not None and occasion not in later_days and res.auc_inf:
            share = 100 * (res.auc_inf - res.auc_last) / res.auc_inf
            if share > cfg.auc_extrapolated_max_percent:
                out.append(Problem(code="FLAG_AUC_EXTRAPOLATED", message=(
                    f"{where(key)}: {share:.1f} % of AUC0–inf is extrapolated, above {cfg.auc_extrapolated_max_percent:g} %: "
                    "its AUC0–inf is unreliable (sampling too short); flagged, AUC0–t kept")))
        if res is not None and occasion not in later_days and res.t_half and res.t_terminal_first is not None:
            span = (res.t_last - res.t_terminal_first) / res.t_half
            if span < cfg.terminal_span_min_half_lives:
                out.append(Problem(code="FLAG_TERMINAL_SPAN", message=(
                    f"{where(key)}: the λz points span {res.t_last - res.t_terminal_first:g} h, {span:.2f} half-lives "
                    f"(t½ {res.t_half:.3g} h), under {cfg.terminal_span_min_half_lives:g}: its t½ is unreliable; "
                    "flagged, kept")))
        # a sample outside the window around its nominal time (actual times given)
        for t, x in sorted(got.items()):
            if t <= 0 or x.actual_h is None or x.missing:
                continue
            window = max(cfg.sample_window_percent / 100 * t, cfg.sample_window_min_minutes / 60)
            if abs(x.actual_h - t) > window + 1e-9:
                out.append(Problem(code="FLAG_SAMPLE_WINDOW", where=x.chip, message=(
                    f"{where(key)}: the {t:g} h sample was taken at {x.actual_h:g} h ({60 * (x.actual_h - t):+.0f} min), "
                    f"outside ± {60 * window:.0f} min (the larger of {cfg.sample_window_percent:g} % and "
                    f"{cfg.sample_window_min_minutes:g} min, a placeholder for the SME); flagged, kept")))
    # vomiting: only where the delivery states the event
    tmax_of: dict[str, list[float]] = {}
    for key, res in results.items():
        tmax_of.setdefault(treatment_of.get(key, ""), []).append(res.t_max)
    modified = bool(_MODIFIED.search(release)) and "immediate" not in release.lower()
    subjects = sorted({k[0] for k in by_profile})
    for subject, fact, hours in vomiting_events(facts, subjects):
        named = _period_named(fact.fact.quote, periods)
        mine = sorted(k for k in by_profile if k[0] == subject)
        keys = [k for k in mine if k[1].split(":", 1)[1] == named] or mine
        if modified:
            out.append(Problem(code="FLAG_VOMITING", severity="info", where=fact.chip, message=(
                f"subject {subject}: the files state vomiting; the products are {release.strip()} (not immediate release), "
                "so the 2 × median Tmax rule does not apply: a person judges it")))
            continue
        if hours is None:
            out.append(Problem(code="FLAG_VOMITING", where=fact.chip, message=(
                f"subject {subject}: the files state vomiting with no time after the dose: the rule (at or before "
                f"{cfg.vomiting_max_tmax_multiple:g} × the median Tmax) cannot be applied; ask the time")))
            continue
        for key in keys:
            tmaxes = tmax_of.get(treatment_of.get(key, ""), [])
            if not tmaxes:
                continue
            limit = cfg.vomiting_max_tmax_multiple * statistics.median(tmaxes)
            said = "" if release.strip() else "; the delivery does not state the release, the rule is for immediate release"
            inside = hours <= limit + 1e-9
            out.append(Problem(code="FLAG_VOMITING", severity="warning" if inside else "info", where=fact.chip, message=(
                f"{where(key)}: vomited {hours:g} h after the dose, "
                + (f"at or before {cfg.vomiting_max_tmax_multiple:g} × the median Tmax of treatment "
                   f"{treatment_of.get(key, '')} ({limit:.3g} h): the whole dose may not have been absorbed; flagged, kept "
                   "in the sets (a person decides)" if inside else
                   f"after {cfg.vomiting_max_tmax_multiple:g} × the median Tmax ({limit:.3g} h): the rule keeps it")
                + said)))
    return out
