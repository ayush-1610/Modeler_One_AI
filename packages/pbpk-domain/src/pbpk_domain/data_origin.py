"""The real-data rule (plan 2026-09-25 §9.4, decision D-19): only real observed data can sign off a model.

Every observed dataset carries where it came from. Data simulated by us (``SYNTHETIC``) or made up by hand for an
example (``ILLUSTRATIVE``) can run the pipeline, which is how the machinery is tested and demonstrated, but a verdict
judged on it is "TEST ONLY: no real observed data" and cannot be signed in a project that is not exploratory. A study
whose origin was never recorded is not taken as real either: the person who uploads it says what it is. A study with
no observed data at all is not evaluable and never counts toward a pass.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import StrEnum
from typing import Any


class DataOrigin(StrEnum):
    CLIENT = "CLIENT"                      # measured by or for the client, delivered to us
    LITERATURE = "LITERATURE"              # a published table or text
    FIGURE_DIGITIZED = "FIGURE_DIGITIZED"  # a published figure, digitized by a person
    OSP_LIBRARY = "OSP_LIBRARY"            # the clinical data of a published OSP model
    SYNTHETIC = "SYNTHETIC"                # simulated by us (known-truth tests): never evidence
    ILLUSTRATIVE = "ILLUSTRATIVE"          # hand-made example data: never evidence


REAL_ORIGINS = frozenset({DataOrigin.CLIENT, DataOrigin.LITERATURE, DataOrigin.FIGURE_DIGITIZED, DataOrigin.OSP_LIBRARY})
TEST_ONLY = "TEST ONLY: no real observed data"
UNRECORDED = "UNRECORDED"


def parse_origin(value: str | None) -> DataOrigin | None:
    """The origin a study was uploaded with, or None when it was not recorded (or is not one of the six)."""
    try:
        return DataOrigin(value) if value else None
    except ValueError:
        return None


def judged_studies(study_metrics: Iterable[Mapping[str, Any]]) -> tuple[list[str], list[str]]:
    """A round's studies split into (judged, not evaluable): judged ones had an observed AUC or Cmax to compare."""
    judged, not_evaluable = [], []
    for s in study_metrics:
        has_observed = s.get("observed_auc") is not None or s.get("observed_cmax") is not None
        (judged if has_observed else not_evaluable).append(str(s.get("study_id")))
    return judged, not_evaluable


def real_data_summary(origins: Mapping[str, str | None], study_metrics: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """What a round's verdict rests on (plan §9.4 item 3): how many judged studies are real, from which origin.

    ``passable`` is False when any judged study is not real (synthetic, illustrative or unrecorded) or when nothing
    was judged; ``label`` is what the monitor shows instead of a plain pass for such a round."""
    judged, not_evaluable = judged_studies(study_metrics)
    by_origin: dict[str, int] = {}
    not_real: list[str] = []
    for study_id in judged:
        origin = parse_origin(origins.get(study_id))
        key = origin.value if origin else UNRECORDED
        by_origin[key] = by_origin.get(key, 0) + 1
        if origin not in REAL_ORIGINS:
            not_real.append(study_id)
    real = len(judged) - len(not_real)
    if not judged:
        label = "not evaluable: no observed data"
    elif not_real and any(parse_origin(origins.get(s)) in (DataOrigin.SYNTHETIC, DataOrigin.ILLUSTRATIVE) for s in not_real):
        label = TEST_ONLY if real == 0 else f"{len(not_real)} of {len(judged)} judged studies are test data"
    elif not_real:
        label = f"origin not recorded for {len(not_real)} of {len(judged)} judged studies"
    else:
        label = ""
    return {"judged": len(judged), "real": real, "byOrigin": dict(sorted(by_origin.items())), "notReal": not_real,
            "notEvaluable": not_evaluable, "passable": bool(judged) and not not_real, "label": label}


def signature_refusal(summaries: Mapping[str, Mapping[str, Any]], *, exploratory: bool) -> str | None:
    """Why the S4/S5 evaluation may not be signed (None: it may). ``summaries`` maps a stage to the real-data summary
    of its judged round. An exploratory project may sign test data; its verdicts stay labelled TEST ONLY."""
    if exploratory:
        return None
    problems = []
    for stage, summary in sorted(summaries.items()):
        if summary.get("judged") and not summary.get("passable"):
            studies = ", ".join(summary.get("notReal", []))
            problems.append(f"{stage}: {summary.get('label')} ({studies})")
    if not problems:
        return None
    return ("The validation rests on observed data that is not real (plan §9.4, D-19): " + "; ".join(problems)
            + ". Upload the real clinical data with its origin, or mark the project exploratory.")
