"""What a dataset carries to the campaign beyond its values (plan 2026-11-12 L-a, L-b, L-d, L-e; contracts §8.2, D1a).

Before, the profile the campaign judges lost four things on the way: the points below the LLOQ were dropped with no
rule named (L-a), an SE or a CV% was dropped and only an SD reached the fit (L-b), the analyte and the matrix stopped at
the dataset so a metabolite or a serum profile was judged as the parent's plasma (L-d), and n per time point collapsed
to one number (L-e). This module decides what the profile and its catalog row say about each, by the one rules file
(`intake_rules.yaml`, `landing`: PROVISIONAL, UNVERIFIED until the SME signs):

- **BLQ**: today's rule, now named: the points below the LLOQ are left out of the fit and of NCA, the LLOQ kept. The
  profile says how many (`blq`), the row names the rule only (`blq_rule`), so a blinded row, whose profile is withheld,
  shows no count. No other rule is offered until the SME chooses one.
- **Spread**: an arithmetic mean's SD as today; its SE (with n) and CV% converted to an SD by `pbpk_domain.spread`, the
  same functions the ledger's derived SD calls, and the conversion named (`sd_from`), but only when the spread kind and
  n were read by code from cells, entered by a person, or the dataset was accepted by one (a reading model's n is
  checked against no quote); a geometric mean's SD sent as reported with its PK-Sim error type (`sd_type`,
  `GeometricStdDev`), and a warning that reading the legacy template's "SD" beside a geometric mean as a geometric
  factor is an assumption (contracts §11.5); every other spread (SE with no n, a geometric mean's SE or CV%, any spread
  of a median, a spread missing at a kept point) kept verbatim with its own unit (`spread`), never converted, and named
  (`warnings`). A geometric spread is never converted.
- **Analyte and matrix**: a profile of anything but the modelled compound is listed and not evaluable (the Project path
  builds no model system); a blood or serum profile is judged against the plasma output as before, with a warning; a
  urine or feces profile (a matrix the field vocabulary names, outside the rules' list) is not judged; a matrix the
  vocabulary does not name is judged as before, with a warning, for a person to confirm.
- **n per time**: carried (`n_at`) only when it varies.

Keys are added only when they apply, so the profile and the row of an unaffected dataset (the parent in plasma, an
arithmetic SD or no spread, no point below the LLOQ, one n) are exactly today's, and so is every PI spec built from them.
None of the new row keys is a `StudyRecord` field: the MS-01 split never sees them.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from typing import Any, Literal

from modeler_intake.document_reading import name_key
from modeler_intake.fields import FIELDS
from modeler_project.datasets import ObservedDataset, Series
from modeler_project.evidence import EvidenceState
from modeler_project.intake_rules import RULES_STATUS, RULES_VERSION, rules
from pbpk_domain import spread

PLASMA = "plasma"
CROSS_FILE = "cross_file:"   # the flag the Delivery landing writes on a dataset joined across files (contracts §6.3)
_STATISTIC_WORDS = {"arithmetic_mean": "arithmetic mean", "geometric_mean": "geometric mean", "median": "median"}
# how a dataset's matrix is judged against the plasma output (`matrix_judgement`)
MatrixJudgement = Literal["plasma", "as_plasma", "unnamed", "not_judged"]


def _rules_named() -> str:
    return f"intake rules {RULES_VERSION}, {RULES_STATUS}"


def is_parent(analyte: str, parent_names: Collection[str]) -> bool:
    """Whether a dataset's analyte is the modelled compound: the rules' parent words ("", "parent") or one of the
    brief's names for the drug (its name and synonyms), compared as names (case, spaces and punctuation aside)."""
    words = {name_key(w) for w in (*rules().landing.parent_words, *parent_names)}
    return name_key(analyte) in words


def matrix_key(matrix: str) -> str:
    """A matrix as the landing compares it: the first of the field vocabulary's matrix choices whose cue the words state
    (`fields.FIELDS["matrix"]`, in its order, plasma first: `human plasma`, `Plasma (K2EDTA)` and `blood plasma` are
    plasma, `whole blood` is blood), else the words themselves, case and outer spaces aside."""
    text = matrix.strip().lower()
    cues = FIELDS["matrix"].choice_cues
    return next((choice for choice, cue in cues.items() if re.search(cue, text, re.IGNORECASE)), text)


def matrix_judgement(matrix: str) -> MatrixJudgement:
    """How a profile in this matrix is judged against the model's plasma output:

    - ``plasma``: as today;
    - ``as_plasma``: a matrix the rules judge against the plasma output with a warning (`matrix_as_plasma_with_warning`:
      blood, serum);
    - ``not_judged``: a matrix the field vocabulary names (urine, feces) that the rules do not judge against plasma;
    - ``unnamed``: words the vocabulary does not recognise (CSF, a blank): judged as today, with a warning, because
      code cannot tell what they mean; a person confirms."""
    key = matrix_key(matrix)
    if key == PLASMA:
        return "plasma"
    if key in {matrix_key(m) for m in rules().landing.matrix_as_plasma_with_warning}:
        return "as_plasma"
    return "not_judged" if key in FIELDS["matrix"].choices else "unnamed"


def judged_as_plasma(matrix: str) -> bool:
    """Whether a profile in this matrix is judged against the plasma output (every matrix but a named non-plasma one
    outside the rules' list, `matrix_judgement`)."""
    return matrix_judgement(matrix) != "not_judged"


def blq(series: Series) -> dict[str, Any] | None:
    """The BLQ rule and how many points of the series it left out of the profile; None when no point is below the
    LLOQ (a None value is a point below the LLOQ, `Series.values`; the readers leave a missing value out of the series)."""
    omitted = sum(1 for v in series.values if v is None)
    return {"rule": rules().landing.blq_rule, "omitted": omitted} if omitted else None


def spread_confirmed(dataset: ObservedDataset) -> bool:
    """Whether a dataset's spread kind and n may be converted into an SD: read by code from the source's cells
    (`CELL`), entered by a person (`MANUAL`), or the dataset accepted by a person. A reading model's n and spread kind
    (`TABLE`, still proposed) are checked against no quote, so its SE or CV% stays as reported until a person accepts."""
    return dataset.extraction in ("CELL", "MANUAL") or dataset.state is EvidenceState.ACCEPTED


def _spread_unit(series: Series, unit: str) -> str:
    if series.error_kind == "CV%":
        return "%"
    if series.statistic == "geometric_mean" and series.error_kind == "SD":
        return ""                                     # a geometric SD is a dimensionless factor
    return unit


def _verbatim(series: Series, errors: list[float | None], unit: str, why: str) -> dict[str, Any]:
    return {"sd": None, "spread": {"kind": series.error_kind, "values": errors, "unit": _spread_unit(series, unit)},
            "warnings": [why]}


def judged_sd(series: Series, kept: Sequence[int], *, unit: str = "", convert: bool = True) -> dict[str, Any]:
    """The profile's spread keys for the kept points (`kept`: indices into the series, the points with a value).

    Always ``sd`` (a list aligned with the kept points, or None, as today); then, only when they apply, ``sd_from``
    (an SE or a CV% converted, `pbpk_domain.spread`), ``sd_type`` (a geometric SD, the rules' `geometric_sd_sent_as`),
    ``spread`` (kept verbatim: kind, values, unit) and ``warnings``. `unit` is the series' concentration unit as
    reported: the unit of a verbatim SE or SD (a CV% is in %, a geometric factor has none). `convert` False
    (`spread_confirmed`): an SE or a CV% is kept verbatim. As today, an SD is given only when every kept point has a
    spread: never a None inside it."""
    if series.error is None or series.error_kind == "none":
        return {"sd": None}
    landing = rules().landing
    errors: list[float | None] = [series.error[i] for i in kept]
    statistic, kind = series.statistic, series.error_kind
    words = _STATISTIC_WORDS.get(statistic, statistic)
    if any(e is None for e in errors):
        return _verbatim(series, errors, unit, f"the {kind} of the {words} is kept as reported: not every point has one; "
                                               "the fit has no SD for it")
    present: list[float] = [e for e in errors if e is not None]
    if statistic == "arithmetic_mean" and kind == "SD":
        return {"sd": present}
    if statistic == "geometric_mean" and kind == "SD":
        warnings = [(f"the SD of the geometric mean is sent as reported, as a geometric SD factor "
                     f"({landing.geometric_sd_sent_as}); that the source's SD is a geometric factor is an "
                     "assumption for the SME to confirm (a legacy template cannot say which)")]
        if any(e < 1 for e in present):          # exp(sigma) >= 1: a value below 1 is not a geometric factor
            warnings.append("a value below 1 cannot be a geometric SD factor (a factor is at least 1): the label is "
                            "likely wrong for this series; the SME decides what it is")
        return {"sd": present, "sd_type": landing.geometric_sd_sent_as, "warnings": warnings}
    if kind in landing.sd_from.get(statistic, ()):
        if not convert:
            return _verbatim(series, errors, unit, f"the {kind} is kept as reported, not converted to an SD: its kind and "
                                                   "n were given by the reading model, not read by code from cells or "
                                                   "confirmed by a person; accepting the dataset converts it")
        if kind == "SE":
            n_each = [series.n_at[i] for i in kept] if series.n_at is not None else [series.n] * len(kept)
            if all(n is not None and n >= 1 for n in n_each):
                return {"sd": [spread.sd_from_se(se, n) for se, n in zip(present, n_each, strict=True)],  # type: ignore[arg-type]
                        "sd_from": {"kind": "SE", "method": "se_times_sqrt_n",
                                    "n": "per_time" if series.n_at is not None else "series", "version": spread.VERSION}}
            return _verbatim(series, errors, unit, "the SE is kept as reported, not converted to an SD: n is not known "
                                                   "for every point (SD = SE × √n needs it); the fit has no SD for it")
        if kind == "CV%":
            means = [series.values[i] for i in kept]
            return {"sd": [spread.sd_from_cv_percent(cv, m) for cv, m in zip(present, means, strict=True)],  # type: ignore[arg-type]
                    "sd_from": {"kind": "CV%", "method": "cv_percent_times_mean", "version": spread.VERSION}}
    if statistic == "geometric_mean":
        why = (f"the {kind} of the geometric mean is kept as reported, not converted (nothing is converted for a "
               "geometric mean); the fit has no SD for it")
    elif statistic == "median":
        why = f"the {kind} of the median is kept as reported: a median's spread is not an SD; the fit has no SD for it"
    else:
        why = f"the {kind} of the {words} is kept as reported, not converted by the intake rules; the fit has no SD for it"
    return _verbatim(series, errors, unit, why)


def joined_from(flags: Sequence[str]) -> list[str]:
    """What a dataset's `cross_file:` flags say it was joined from (the text after the prefix), in order."""
    return [f.removeprefix(CROSS_FILE).strip() for f in flags if f.startswith(CROSS_FILE)]


def matrix_note(sid: str, matrix: str, judged: bool) -> str:
    """The catalog's note for a profile that is not measured in plasma (`matrix_judgement`)."""
    shown = matrix.strip() or "a matrix that is not stated"
    if not judged:
        return f"{sid}: measured in {shown}: not evaluable, no model output is judged against it"
    if matrix_judgement(matrix) == "unnamed":
        return (f"{sid}: measured in {shown}, a matrix the intake rules do not name: judged against the plasma output as "
                "before, for a person to confirm")
    return f"{sid}: measured in {shown}, judged against the plasma output"


def landing_limitations(rows: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    """The MAP limitations the study catalog's landing implies, one per study and kind: the BLQ rule applied (named,
    with the rules' version and status; no count, so nothing of a blinded study's values is said), each SE or CV%
    converted to an SD, each geometric SD sent as a factor, each spread kept verbatim, each analyte that is not the
    modelled compound, each matrix that is not plasma and each cross-file join. Every line a rule of the intake rules
    decides names their version and status (UNVERIFIED until the SME signs). () for a catalog of parent plasma profiles
    with an arithmetic SD or none and no point below the LLOQ, so such a plan is unchanged."""
    out: list[str] = []
    named = _rules_named()
    for row in rows:
        sid = row["study_id"]
        profile = row.get("profile") or {}
        if rule := row.get("blq_rule"):
            out.append(f"{sid}: the points below the LLOQ are left out of the fit and of NCA, the LLOQ kept (BLQ rule "
                       f"{rule!r}, {named})")
        sd_from = profile.get("sd_from") or {}
        if sd_from.get("kind") == "SE":
            n = "per time point" if sd_from.get("n") == "per_time" else "of the series"
            out.append(f"{sid}: the SD the fit is given is derived from the reported SE and n {n} (SD = SE × √n, "
                       f"{sd_from.get('version')}; {named})")
        elif sd_from.get("kind") == "CV%":
            out.append(f"{sid}: the SD the fit is given is derived from the reported CV% and the mean (SD = CV% × mean "
                       f"/ 100, {sd_from.get('version')}; {named})")
        if profile.get("sd_type"):
            out.append(f"{sid}: the SD of the geometric mean is sent as reported, as a geometric SD factor "
                       f"({profile['sd_type']}); that it is a geometric factor is an assumption for the SME ({named})")
        if verbatim := profile.get("spread"):
            out.append(f"{sid}: the reported {verbatim.get('kind')} is kept as reported, not converted; the fit has no "
                       f"SD for this profile ({named})")
        if analyte := row.get("measured_analyte"):
            out.append(f"{sid}: measures {analyte}, not the modelled compound: not evaluable without a model system "
                       f"({named})")
        if "measured_matrix" in row:
            matrix = str(row["measured_matrix"])
            shown = matrix.strip() or "a matrix that is not stated"
            if matrix_judgement(matrix) == "not_judged":
                out.append(f"{sid}: measured in {shown}: not judged, no model output is judged against it ({named})")
            elif not row.get("profile"):         # not judged for another reason (its analyte, individuals only ...)
                out.append(f"{sid}: measured in {shown} ({named})")
            elif matrix_judgement(matrix) == "unnamed":
                out.append(f"{sid}: measured in {shown}, a matrix the intake rules do not name: judged against the plasma "
                           f"output as before, for a person to confirm ({named})")
            else:
                out.append(f"{sid}: measured in {shown}, judged against the plasma output ({named})")
        for joined in row.get("joined_from") or ():
            out.append(f"{sid}: values joined from another file ({joined})")
    return tuple(out)
