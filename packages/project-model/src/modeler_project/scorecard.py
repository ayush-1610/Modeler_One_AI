"""The scorecard of a subject (plan §7.7: "a scorecard per study and per product, not a pass/fail flag"; contracts §6.4).

A study, a product and the project's compound (subject id "compound") each get one: the coverage of the files its
values come from, its requirement statuses and schema gaps, its checks with those a person cleared, its open conflicts
and pending cross-file links, the count of its active values by evidence level and by method, and its blockers.

The blockers this module computes are every reason a confirmation refuses but three, which the review adds (the spot
check, a dataset loaded on the legacy card, a blinded study):
- `SILENT_LOSS`: a cell with a number in the subject's files that is neither used nor excluded by a stated rule;
- `OUTSIDE_NUMBERS`: an item with a number outside every region that nobody accepted as not data;
- `UNASSIGNED_VALUES`: a value of the subject's deliveries that belongs to no study, product or the compound;
- `SCHEMA_GAP`: a study whose routing no authored template covers (never cleared by an override);
- `CHECK_FAILED`: a check at severity `fail` that no override cleared;
- `LINK_UNCONFIRMED`: a cross-file link to the study that no reviewer confirmed (unconfirmed or ambiguous).

An `Override` of the subject clears the check it names: the check stays listed and its id is in `overridden`. A
`REQUIRED_ITEM_UNDISPOSED` or `CONFLICT_OPEN` failure is settled by a `RequirementDisposition` or a `Choice`, not by an
override (§11.22): a disposition of the subject's item clears it; a choice clears the conflict itself, so the check is
gone the next time the checks run.

A missing REQUIRED item that applies blocks whatever checks the caller passes: the scorecard adds its
`REQUIRED_ITEM_UNDISPOSED` result itself (`intake_checks.required_item_checks`, the same id) when `checks` lacks it,
so checks run without the requirements can never unblock it.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Literal

from modeler_project.coverage import silent_loss
from modeler_project.intake_checks import SETTLED_BY_RECORD, required_item_checks, result_id, sort_results
from modeler_project.intake_records import (
    Blocker,
    CheckResult,
    CoverageSummary,
    Override,
    RequirementDisposition,
    RequirementStatus,
    SchemaGap,
    Scorecard,
)
from modeler_project.intake_rules import IntakeRules
from modeler_project.ledger_models import Conflict
from modeler_project.ledger_view import LedgerReader, in_subject
from modeler_project.study_routing import subject_values

COMPOUND = "compound"                     # the compound's subject id (§6.6)
# A pending link that still blocks: one no reviewer confirmed, or one with several candidate studies
_PENDING = ("unconfirmed", "ambiguous")


def scorecard(reader: LedgerReader, *, subject_type: Literal["study", "product", "compound"], subject: str,
              coverage: Sequence[CoverageSummary], requirements: Sequence[RequirementStatus], gaps: Sequence[SchemaGap],
              checks: Sequence[CheckResult], overrides: Sequence[Override] = (),
              dispositions: Sequence[RequirementDisposition] = (), rules: IntakeRules | None = None) -> Scorecard:
    """The subject's scorecard (see the module docstring). `coverage` holds the summaries of the files of the
    subject's deliveries (silent loss is judged per delivery, §11.10); `requirements`, `gaps` and `checks` are what
    `study_requirements`, `study_routing` and `intake_checks` gave for the subject; `rules` the rules file the checks
    were run with (the loaded one by default), for the severity of a `REQUIRED_ITEM_UNDISPOSED` the scorecard adds."""
    subject = _resolved(reader, subject_type, subject)
    present = {c.id for c in checks}
    added = [c for c in required_item_checks(reader, subject_type=subject_type, subject=subject,
                                             requirements=requirements, rules=rules) if c.id not in present]
    checks = tuple(sort_results((*checks, *added))) if added else tuple(checks)
    label = COMPOUND if subject_type == "compound" else _label(reader, subject)
    values = subject_values(reader, subject_type, subject)
    conflicts = _conflicts(reader, subject_type, subject)
    links = list(reader.pending_links(study=subject)) if subject_type == "study" else []
    overridden = _overridden(reader, subject_type, subject, checks, overrides, dispositions)
    lost = silent_loss(coverage)
    outside = sum(c.outside_numeric for c in coverage)
    unassigned = sum(c.values_unassigned for c in coverage)
    blockers: list[Blocker] = []
    if lost:
        blockers.append(Blocker(code="SILENT_LOSS", detail=f"{lost} cells with a number in the subject's files are "
                                "neither used nor excluded by a stated rule"))
    if outside:
        blockers.append(Blocker(code="OUTSIDE_NUMBERS", detail=f"{outside} items with a number outside every table "
                                "are not accepted as not data"))
    if unassigned:
        blockers.append(Blocker(code="UNASSIGNED_VALUES", detail=f"{unassigned} values of the subject's deliveries "
                                "name no study: assign or exclude them"))
    if gaps:
        blockers.append(Blocker(code="SCHEMA_GAP", detail="; ".join(_gap(g) for g in gaps)))
    failed = [c for c in checks if c.severity == "fail" and c.id not in overridden]
    if failed:
        blockers.append(Blocker(code="CHECK_FAILED", detail=f"{len(failed)} failed checks: "
                                + ", ".join(sorted({c.code for c in failed})), ids=tuple(c.id for c in failed)))
    pending = [link for link in links if link.state in _PENDING]
    if pending:
        blockers.append(Blocker(code="LINK_UNCONFIRMED", detail=f"{len(pending)} cross-file links wait for a reviewer",
                                ids=tuple(link.id for link in pending)))
    return Scorecard(subject_type=subject_type, subject=subject, label=label, coverage=tuple(coverage),
                     silent_loss=lost, requirements=tuple(requirements), gaps=tuple(gaps), checks=tuple(checks),
                     overridden=tuple(c.id for c in checks if c.id in overridden), conflicts=tuple(conflicts),
                     links=tuple(links), values=len(values), by_level=dict(sorted(Counter(v.level for v in values).items())),
                     by_method=dict(sorted(Counter(v.method for v in values).items())), blockers=tuple(blockers))


def _overridden(reader: LedgerReader, subject_type: str, subject: str, checks: Sequence[CheckResult],
                overrides: Sequence[Override], dispositions: Sequence[RequirementDisposition]) -> set[str]:
    """The ids of the subject's checks a person cleared: by an override (not a check a disposition or a choice settles),
    or, for a missing required item, by a disposition of that item for the subject."""
    ids = {c.id: c for c in checks}
    cleared = {o.check_id for o in overrides if _resolved(reader, subject_type, o.subject) == subject
               and o.check_id in ids and ids[o.check_id].code not in SETTLED_BY_RECORD}
    for disposition in dispositions:
        if _resolved(reader, subject_type, disposition.subject) == subject:
            expected = result_id("REQUIRED_ITEM_UNDISPOSED", subject, (), disposition.req_id)
            if expected in ids:
                cleared.add(expected)
    return cleared


def _conflicts(reader: LedgerReader, subject_type: str, subject: str) -> list[Conflict]:
    if subject_type == "study":
        return reader.conflicts(study=subject)
    if subject_type == "product":
        return reader.conflicts(product=subject)
    return [c for c in reader.conflicts() if in_subject(c.entity, c.field, "compound", COMPOUND)]


def _resolved(reader: LedgerReader, subject_type: str, subject: str) -> str:
    if subject_type == "compound":
        return subject
    entity = reader.entity(subject)
    return entity.id if entity is not None else subject


def _label(reader: LedgerReader, subject: str) -> str:
    entity = reader.entity(subject)
    return entity.label if entity is not None else subject


def _gap(gap: SchemaGap) -> str:
    return f"{gap.tag} {gap.value}: {gap.reason}" if gap.value else f"{gap.tag}: {gap.reason}"
