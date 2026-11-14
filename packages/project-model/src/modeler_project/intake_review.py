"""The review of a delivery (contracts §6.6; plan §7.8, G6): cards, a person's decisions, the spot check and the signed
confirmation. The landing is `intake_landing`.

**Subjects.** A study, a product, and the project's compound (subject id "compound": the values of a compound-level
field with no study, product or batch). Values of no subject are the "study not stated" list (`unassigned`) until a
person assigns them (`assign`) or excludes the region they were read from (`exclude_regions`). An assignment may name
a NEW study or product (a table whose title the rules do not read as a study id): the ledger's write side creates it
(`Ledger.name_entity`, audited `intake.entity`), never a duplicate of one that exists.

**Decisions** are lines of `review.jsonl` (override, disposition, choice, link, assignment, region), each with who,
when and why, and one audit event carrying the line's hash. None has a signature of its own: the confirmation binds
them. A choice excludes the other values of its conflict (`Ledger.apply_choice`); a link confirmation or an assignment
is followed by `Ledger.derive`, so a derived fact never stands where its input still waits; a region decision of scope
`regions` also sets aside the values read from those regions (its extracts, and the facts anchored in its cells or
paragraphs), which is how a "study not stated" table is excluded. `assign` and `exclude_regions` recompute the coverage
of the files concerned from the stored outcomes, every region decision and the source cache, and store it.

**The spot check** (decision 6; every number and list from `intake_rules.yaml` `spot_check`). Candidates are the
subject's active values that are numeric or censored. Never sampled (`always`): the values of `always_verify_fields`;
the values of a check that carries an override (the checks the ledger alone gives: no brief, matrix or molecular
weight enters a draw, so an auditor recomputes it from the logs and the rules file); every digitized or derived value
(a derived value is shown with its inputs); every cross-file scalar fact and every link fact. The rest is drawn by
strata (table kind, the field's unit class, the BLQ marker form, cross-file): everything when at most `size` values,
else `min_per_stratum` from each stratum and the remainder in proportion (largest remainder); inside a stratum the
values are ordered by sha256(seed + value id), with no random generator. The draw stores its seed
(sha256(facts head + "|" + subject + "|" + rules version)), the four log heads, the rules file's sha256 and the
subject's digest. Ticks arrive once, as one record. A draw is stale when the subject's digest (or the rules file)
differs from the draw's, or an override made after it names a value it does not hold; the next draw carries the ok
ticks of the values still drawn (a value's id fixes its value and anchor: facts and extracts are append-only), so only
new or changed values are ticked again. A value whose latest tick failed is in every later draw as `always:failed`
and takes no new tick: only a correction, a supersession or an exclusion of the value clears it.

**The confirmation** (decision E). `bound_record` is the canonical record the signature binds; `blockers` is every
refusal. This module never signs and never sees a password. The route's order: `landing_incomplete` for the freshly
computed record hash (an interrupted landing completes with no new signature); else `prepare_confirmation`, which
checks every refusal in one call (no blocker left, the landing planned) and gives the record to sign; then the API's
step-up and signature, whose id is passed to `record_confirmation`; then `intake_landing.land`. `record_confirmation`
does not rely on the route: it refuses a record whose hash, subject or digest does not match, one that itself shows a
refusal (silent loss, an uncleared failed check, no spot check, a landing that cannot be planned), and whatever the
workspace and the ledger show now (`_own_refusals`: a file not read, a link that waits, a spot check that is not
complete, the legacy card, another study's accepted dataset, a blinded subject). A schema gap and a check that needs
the brief, the requirement matrix or the molecular weight are `prepare_confirmation`'s alone.

**Blinding (D-15)** is enforced here, so a route cannot forget it: `card`, `draw_spot_check`, `latest_spot_check`,
`prepare_confirmation` and `record_confirmation` need `blinded` (a required keyword, as `blockers` has it in the
contract; `is_blinded` gives it from `blinded_subjects`). `bound_record`, `intake_landing.plan_landing` and
`current_confirmation` have no such keyword and hold a blinded study's values: a route never answers with them; a blinded study's card names no value of a check, its spot check cannot be drawn, its
confirmation is refused with `BLINDED`; `shown` and `source_view` need the blinded studies (`hidden`) and withhold a
blinded study's value, verbatim, spread, interval, LLOQ, and in its source the cells with a number, the cells a value
is anchored at (the BLQ marks) and the digits of the title. No text this module
writes (a blocker's detail, a held-back reason) names a value, an LLOQ or a count of values below the LLOQ, and
`subjects` gives counts that say nothing of the values themselves.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Collection, Iterable, Sequence
from typing import Any, Literal

from pydantic import ValidationError

from modeler_intake.anchors import AnchorError, check_id, format_locator, parse_anchor, parse_locator, same_place, sha256_of
from modeler_intake.document_reading import name_key
from modeler_intake.fields import read_choice, unit_class
from modeler_intake.source import region_grid, resolve
from modeler_intake.source import source_view as document_view
from modeler_intake.source_model import SourceDocument, SourceView
from modeler_project import blinding, client_data, intake_landing
from modeler_project.brief import ProjectBrief
from modeler_project.coverage import file_coverage, values_unassigned
from modeler_project.dataset_register import dataset as dataset_of
from modeler_project.dataset_register import datasets as all_datasets
from modeler_project.datasets import ObservedDataset, Origin
from modeler_project.evidence import EvidenceState
from modeler_project.intake_checks import run_checks
from modeler_project.intake_landing import COMPOUND, SubjectType, resolve_subject, subject_digest
from modeler_project.intake_records import (
    Assignment,
    Blocker,
    Choice,
    Confirmation,
    FileCoverage,
    FileRecord,
    Landed,
    LinkConfirmation,
    Override,
    RegionDecision,
    RequirementDisposition,
    RequirementStatus,
    RunRecord,
    SchemaGap,
    Scorecard,
    SpotCheckDraw,
    SpotCheckRecord,
    SpotTick,
)
from modeler_project.intake_rules import RULES_SHA256, RULES_STATUS, RULES_VERSION, IntakeRules
from modeler_project.intake_rules import rules as load_rules
from modeler_project.intake_store import ChainEntry, IntakeStore
from modeler_project.ledger import Ledger
from modeler_project.ledger_entities import label_key, now
from modeler_project.ledger_models import EntityType, ExtractRef, ValueState
from modeler_project.ledger_view import LedgerReader, LedgerView, in_subject, is_spread_fact, is_unassigned
from modeler_project.requirements import RequirementMatrix
from modeler_project.scorecard import scorecard
from modeler_project.study_requirements import product_requirements, requirement_status
from modeler_project.study_routing import subject_values
from modeler_project.workspace import Workspace

SpotCheckState = Literal["none", "drawn", "failed", "complete", "stale"]
RECORD_SCHEMA = "confirmation/1"
FAILED_TICK = "always:failed"                    # a draw's stratum for a value whose latest tick, in an earlier draw, failed
LANDING_REFUSED = "the landing is refused"       # how a bound record's `held` says the landing cannot be planned
CONFIRM_ON_DELIVERY, CONFIRM_ON_CLIENT_REVIEW = "delivery", "client-review"
_SCOPES = ("regions", "unread_prose", "figures", "outside")
_SCOPE_KINDS: dict[str, tuple[str, ...] | None] = {"regions": None, "unread_prose": ("prose",), "figures": ("figure",)}
_REQ_ID = re.compile(r"REQ-[A-Za-z0-9_.@%+-]{1,160}")
_NUMBER = re.compile(r"[-+]?\d+(?:[.,]\d+)*(?:[eE][-+]?\d+)?")
_DIGIT = re.compile(r"\d")
_WAITING = ("queued", "running")
_LOGS = ("files", "runs", "mappings", "facts", "entities", "review")       # the intake's hash-chained logs


class ReviewError(ValueError):
    """A decision the review refuses, with a code a route can answer with: UNKNOWN (no such subject, value, file,
    region, draw or conflict), INVALID (an id or a field that is not one), CONFLICT (the state does not allow it),
    BLINDED (a blinded study, D-15), STALE (the draw no longer matches the subject)."""

    def __init__(self, code: Literal["UNKNOWN", "INVALID", "CONFLICT", "BLINDED", "STALE"], message: str):
        super().__init__(message)
        self.code = code


class ConfirmationRefused(ReviewError):
    """The subject cannot be confirmed yet: `blockers` says why (each with its code and detail)."""

    def __init__(self, blockers: Sequence[Blocker]):
        super().__init__("CONFLICT", "the confirmation is refused: " + "; ".join(f"{b.code}: {b.detail}" for b in blockers))
        self.blockers = tuple(blockers)


# --- small readers ----------------------------------------------------------------------------------------------------


def _lines(store: IntakeStore, kind: str) -> list[ChainEntry]:
    return store.review.entries(kind)


def _ref(entry: ChainEntry) -> str:
    """A review line as a record binds it: "<id>:<the line's hash>"."""
    return f"{entry.body.get('id')}:{entry.hash}"


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _why(text: str, what: str) -> str:
    if not isinstance(text, str) or not text.strip():
        raise ReviewError("INVALID", f"{what} needs a reason")
    return text.strip()


def _id(kind: str, text: Any, what: str) -> str:
    try:
        return check_id(kind, text)
    except AnchorError as exc:
        raise ReviewError("INVALID", f"{what}: {exc}") from exc


def _subject(reader: LedgerReader, subject_type: str, subject: str) -> str:
    try:
        return resolve_subject(reader, subject_type, subject)
    except KeyError as exc:
        raise ReviewError("UNKNOWN", f"no {subject_type} {subject!r} in this project's ledger") from exc
    except ValueError as exc:
        raise ReviewError("INVALID", str(exc)) from exc


def _any_subject(reader: LedgerReader, subject: str) -> tuple[SubjectType, str]:
    """A decision's subject: the compound, or a study or product of the ledger (followed through merges)."""
    if subject == COMPOUND:
        return "compound", COMPOUND
    _id("line", subject, "the subject")
    entity = reader.entity(subject)
    if entity is None or entity.type not in ("study", "product"):
        raise ReviewError("UNKNOWN", f"{subject!r} is not a study, a product or the compound of this project")
    return entity.type, entity.id  # type: ignore[return-value]


def _same_subject(reader: LedgerReader, subject_type: str, subject: str, other: str) -> bool:
    """Whether a record's subject is this one (a study or product followed through merges)."""
    if subject_type == "compound":
        return other == COMPOUND
    entity = reader.entity(other) if other != COMPOUND else None
    return entity is not None and entity.id == subject


def _values(reader: LedgerReader, subject_type: str, subject: str, *, spread_facts: bool = False) -> list[ValueState]:
    return subject_values(reader, subject_type, subject, spread_facts=spread_facts)  # type: ignore[arg-type]


def _file_lines(store: IntakeStore) -> list[FileRecord]:
    out = []
    for entry in store.files.entries("file"):
        try:
            out.append(FileRecord.model_validate(entry.body))
        except ValidationError:
            continue
    return out


def _delivery_files(store: IntakeStore, values: Iterable[ValueState]) -> list[str]:
    """The files of a subject's deliveries (§11.10: silent loss is judged per delivery): every file of a delivery one of
    its values arrived in (the delivery the ledger recorded the value under: the same bytes delivered again add
    nothing to the ledger, so a repeat arrival ties the subject to no later delivery), and every file a value was read
    from; sha256s, sorted."""
    values = list(values)
    deliveries = {v.delivery for v in values if v.delivery}
    shas = {v.file_sha256 for v in values if v.file_sha256}
    shas |= {f.sha256 for f in _file_lines(store) if f.delivery in deliveries}
    return sorted(shas)


def _coverages(store: IntakeStore, shas: Iterable[str]) -> list[FileCoverage]:
    return [found for sha in shas if (found := store.coverage(sha)) is not None]


def _runs(store: IntakeStore) -> dict[str, RunRecord]:
    """Each run's latest line, in the order of those lines (the run that wrote last is last)."""
    out: dict[str, RunRecord] = {}
    for entry in store.runs.entries():
        try:
            run = RunRecord.model_validate(entry.body)
        except ValidationError:
            continue
        out.pop(run.run_id, None)
        out[run.run_id] = run
    return out


def _unread_files(store: IntakeStore, files: Iterable[str]) -> list[Blocker]:
    """G2 for the files of a subject's deliveries: each needs a finished run and a coverage file, or its numbers were
    never counted. One `SILENT_LOSS` blocker for the files still being read (a run queued or running), one for the
    files not read (its latest run failed, it has no run, or it has no coverage file), each naming its files. A ZIP
    with no run of its own is not one of them: its members are the files that are read."""
    files = sorted(set(files))
    runs = _runs(store)
    latest: dict[str, RunRecord] = {}
    for run in runs.values():
        latest[run.sha256] = run
    waiting = sorted({r.sha256 for r in runs.values() if r.state in _WAITING and r.sha256 in files})
    out = []
    if waiting:
        out.append(Blocker(code="SILENT_LOSS", detail=f"{len(waiting)} files of the subject's deliveries are still being "
                           "read: their numbers are not counted yet", ids=tuple(f"fl-{sha[:12]}" for sha in waiting)))
    # an archive is read through its members (each a file of its own, with its run): it needs no run itself
    archives = {f.container.sha256 for f in _file_lines(store) if f.container is not None}
    unread: list[tuple[str, str]] = []
    for sha in files:
        if sha in waiting or (sha in archives and sha not in latest):
            continue
        run = latest.get(sha)
        why = ("no run" if run is None else "its run failed" if run.state != "done"
               else "no coverage file" if store.coverage(sha) is None else "")
        if why:
            unread.append((sha, why))
    if unread:
        names = intake_landing.file_records(store)
        listed = "; ".join(f"{names[sha].name if sha in names else sha[:12]} ({why})" for sha, why in unread)
        out.append(Blocker(code="SILENT_LOSS", detail=f"{len(unread)} files of the subject's deliveries were not read: "
                           f"{listed}. Their numbers are not counted: run them again, then confirm",
                           ids=tuple(f"fl-{sha[:12]}" for sha, _why in unread)))
    return out


def _templates(ws: Workspace, shas: Iterable[str]) -> set[str]:
    """Those of these files that are a filled client-data template (read by today's no-AI path, confirmed on its card)."""
    out = set()
    for sha in shas:
        sub = client_data.submission(ws, client_data.submission_id(sha))
        if sub is not None and sub.get("template"):
            out.add(sha)
    return out


def confirm_on(ws: Workspace, values: Iterable[ValueState]) -> str:
    """Where a subject with these values is confirmed (§2): "client-review" when every file they were read from is a
    filled client-data template (today's no-AI path reads it exactly; it is confirmed on its legacy card only, and
    Delivery shows its coverage and ledger read-only), else "delivery"."""
    files = {v.file_sha256 for v in values if v.file_sha256}
    return CONFIRM_ON_CLIENT_REVIEW if files and files <= _templates(ws, files) else CONFIRM_ON_DELIVERY


# --- the page's lists ---------------------------------------------------------------------------------------------------


def confirmations(ws: Workspace) -> list[Confirmation]:
    """Every confirmation recorded, in order."""
    return [Confirmation.model_validate(e.body) for e in _lines(IntakeStore(ws), "confirmation")]


def current_confirmation(ws: Workspace, subject_type: SubjectType, subject: str, *, reader: LedgerReader) -> Confirmation | None:
    """The subject's current confirmation: its latest one that no other confirmation names in `supersedes` (§13)."""
    found = confirmations(ws)
    replaced = {c.supersedes for c in found if c.supersedes}
    mine = [c for c in found if c.subject_type == subject_type and c.id not in replaced
            and _same_subject(reader, subject_type, subject, c.subject)]
    return mine[-1] if mine else None


def landed(ws: Workspace, confirmation_id: str) -> Landed | None:
    """The `landed` line of a confirmation, if its landing completed."""
    return intake_landing.landed(ws, confirmation_id)


def subjects(ws: Workspace, *, reader: LedgerReader) -> list[dict[str, Any]]:
    """The studies, the products and the compound that have active values (or a confirmation), each with its counts and
    its confirmation state: `subject_type`, `subject`, `label`, `values`, `by_level`, `by_method`, `files` (sha256s of
    the files its values were read from), `deliveries`, `confirmation` (None, or id, at, by, printed_name,
    signature_id, manifestation, record_sha256, `current`: the record still describes the subject's values, `landed`),
    `loaded_elsewhere` (the non-rejected legacy client datasets that overlap it by source, §2) and `confirm_on`
    ("client-review" when every file its values come from is a filled client-data template, which is confirmed on its
    legacy card; else "delivery"). No blockers: the subject's own route computes them. No count here tells anything
    of the values themselves, so a blinded study's row is shown as it is."""
    store = IntakeStore(ws)
    if not store.available:
        return []
    found = confirmations(ws)
    replaced = {c.supersedes for c in found if c.supersedes}
    done = {e.body.get("confirmation") for e in _lines(store, "landed")}
    legacy = [d for d in all_datasets(ws) if d.origin is Origin.CLIENT and not intake_landing.is_delivery_dataset(d)
              and d.state is not EvidenceState.REJECTED]
    rows = []
    listed: list[tuple[SubjectType, str, str]] = [("study", e.id, e.label) for e in reader.entities("study")]
    listed += [("product", e.id, e.label) for e in reader.entities("product")]
    listed.append(("compound", COMPOUND, COMPOUND))
    for subject_type, subject, label in listed:
        values = _values(reader, subject_type, subject)
        mine = [c for c in found if c.subject_type == subject_type and c.id not in replaced
                and _same_subject(reader, subject_type, subject, c.subject)]
        if not values and not mine:
            continue
        files = sorted({v.file_sha256 for v in values if v.file_sha256})
        confirmation = None
        if mine:
            last = mine[-1]
            confirmation = {"id": last.id, "at": last.at, "by": last.by, "printed_name": last.printed_name,
                            "signature_id": last.signature_id, "manifestation": last.manifestation,
                            "record_sha256": last.record_sha256, "landed": last.id in done,
                            "current": last.record.get("subject_digest") == subject_digest(reader, subject_type, subject)}
        elsewhere = [d.id for d in intake_landing.legacy_overlap(ws, subject_type, subject, reader=reader, candidates=legacy)]
        rows.append({"subject_type": subject_type, "subject": subject, "label": label, "values": len(values),
                     "by_level": dict(sorted(Counter(v.level for v in values).items())),
                     "by_method": dict(sorted(Counter(v.method for v in values).items())), "files": files,
                     "deliveries": sorted({v.delivery for v in values if v.delivery}), "confirmation": confirmation,
                     "loaded_elsewhere": elsewhere, "confirm_on": confirm_on(ws, values)})
    return rows


def unassigned(ws: Workspace, *, reader: LedgerReader) -> list[ValueState]:
    """The "study not stated" list: the active values of no subject (no study, no product, not a compound field), in
    log order; a derived spread fact is never a value of its own. No such value is a blinded study's."""
    del ws
    return [v for v in reader.values(unassigned=True) if not is_spread_fact(v)]


# --- the card ---------------------------------------------------------------------------------------------------------


def _overrides(store: IntakeStore) -> list[Override]:
    return [Override.model_validate(e.body) for e in _lines(store, "override")]


def _dispositions(store: IntakeStore) -> list[RequirementDisposition]:
    return [RequirementDisposition.model_validate(e.body) for e in _lines(store, "disposition")]


def _parent_names(brief: ProjectBrief | None) -> tuple[str, ...]:
    if brief is None:
        return ()
    from modeler_project.inputs import drug_names

    return tuple(n for n in drug_names(brief) if n)


def _card(ws: Workspace, subject_type: SubjectType, subject: str, *, reader: LedgerReader, brief: ProjectBrief | None,
          matrix: RequirementMatrix | None, mol_weight: float | None) -> Scorecard:
    store = IntakeStore(ws)
    subject = _subject(reader, subject_type, subject)
    dispositions, overrides = _dispositions(store), _overrides(store)
    requirements: Sequence[RequirementStatus] = ()
    gaps: Sequence[SchemaGap] = ()
    if subject_type == "study":
        found = requirement_status(reader, subject, brief=brief, matrix=matrix, dispositions=dispositions)
        requirements, gaps = found.items, found.routing.gaps
    elif subject_type == "product":
        requirements = product_requirements(reader, subject, brief=brief, matrix=matrix, dispositions=dispositions)
    checks = run_checks(reader, subject_type=subject_type, subject=subject, requirements=requirements,
                        mol_weight=mol_weight, parent_names=_parent_names(brief))
    coverage = [c.summary for c in _coverages(store, _delivery_files(store, _values(reader, subject_type, subject)))]
    return scorecard(reader, subject_type=subject_type, subject=subject, coverage=coverage, requirements=requirements,
                     gaps=gaps, checks=checks, overrides=overrides, dispositions=dispositions)


def card(ws: Workspace, subject_type: SubjectType, subject: str, *, reader: LedgerReader, brief: ProjectBrief | None,
         matrix: RequirementMatrix | None, mol_weight: float | None, blinded: bool) -> Scorecard:
    """The subject's scorecard (`scorecard.scorecard`): the coverage of the files of its deliveries (the stored
    coverage files, the current truth), its requirement statuses and schema gaps (a study's routing, a product's
    items; the compound's items stay the project's), its checks with those a person cleared, its conflicts and
    pending links, its counts and D5's blockers (`blockers` adds the review's). `blinded` (required: `is_blinded`):
    a blinded subject's checks name no value (which values are below the LLOQ, negative or marked says something of
    them), and nothing else on a card does. ReviewError UNKNOWN for a subject that is not one of the project's."""
    found = _card(ws, subject_type, subject, reader=reader, brief=brief, matrix=matrix, mol_weight=mol_weight)
    if not blinded:
        return found
    return found.model_copy(update={"checks": tuple(c.model_copy(update={"values": ()}) for c in found.checks)})


# --- a person's decisions ---------------------------------------------------------------------------------------------


def override(ws: Workspace, *, subject: str, check_id: str, why: str, by: str) -> Override:
    """Clear a failed check of a subject with a reason (never a schema gap, a conflict or a missing required item:
    `scorecard` ignores an override of those). One `override` line, one `intake.override` event."""
    why = _why(why, "an override")
    _id("check", check_id, "the check")
    _kind, subject = _any_subject(LedgerView(ws), subject)
    store = IntakeStore(ws)
    entry = store.review.append("override", lambda seq: Override(
        id=f"ov-{seq}", subject=subject, check_id=check_id, why=why, by=by, at=now()).model_dump(mode="json"))
    record = Override.model_validate(entry.body)
    store.audit(actor=by, action="intake.override", resource_id=record.id,
                after={"override": record.id, "check_id": check_id, "row_hash": entry.hash}, reason=why)
    return record


def dispose(ws: Workspace, *, subject: str, req_id: str, disposition: str, why: str, by: str) -> RequirementDisposition:
    """A person's disposition of a requirement item of a subject: ask the client, literature, or not needed. One
    `disposition` line, one `intake.disposition` event."""
    why = _why(why, "a disposition")
    if not isinstance(req_id, str) or _REQ_ID.fullmatch(req_id) is None:
        raise ReviewError("INVALID", f"not a requirement item's id: {req_id!r}")
    _kind, subject = _any_subject(LedgerView(ws), subject)
    try:
        draft = RequirementDisposition(id="dp-0", subject=subject, req_id=req_id, disposition=disposition,  # type: ignore[arg-type]
                                       why=why, by=by, at=now())
    except ValidationError as exc:
        raise ReviewError("INVALID", f"a disposition is ask_client, literature or not_needed, not {disposition!r}") from exc
    store = IntakeStore(ws)
    entry = store.review.append("disposition", lambda seq: draft.model_copy(update={"id": f"dp-{seq}"}).model_dump(mode="json"))
    record = RequirementDisposition.model_validate(entry.body)
    store.audit(actor=by, action="intake.disposition", resource_id=record.id,
                after={"disposition": record.id, "req_id": req_id, "row_hash": entry.hash}, reason=why)
    return record


def _value_id(text: Any, what: str) -> str:
    """A value's id: a fact ("f-41") or the i-th value of an extract ("tx-...#3")."""
    if isinstance(text, str) and text.startswith("tx-"):
        return _id("value", text, what)
    found = _id("line", text, what)
    if not found.startswith("f-"):
        raise ReviewError("INVALID", f"{what}: not a value's id: {text!r}")
    return found


def choose(ws: Workspace, *, conflict_id: str, keep: str, why: str, by: str) -> Choice:
    """Settle an open conflict: `keep` stays, the other values that read differently are excluded
    (`Ledger.apply_choice`). One `choice` line, one `intake.choice` event; the same choice again while the conflict is
    still open (a landing of the exclusions that was interrupted) writes nothing new and applies it."""
    why = _why(why, "a choice")
    _id("conflict", conflict_id, "the conflict")
    keep = _value_id(keep, "the value kept")
    ledger = Ledger(ws)
    conflict = next((c for c in ledger.conflicts() if c.id == conflict_id), None)
    if conflict is None:
        raise ReviewError("UNKNOWN", f"no open conflict {conflict_id}")
    if keep not in conflict.values:
        raise ReviewError("INVALID", f"{keep} is not one of the values of {conflict_id}")
    store = IntakeStore(ws)
    earlier: list[ChainEntry] = []

    def decide(entries: list[ChainEntry]) -> list[tuple[str, Any]]:
        same = [e for e in entries if e.kind == "choice" and e.body.get("conflict_id") == conflict_id and e.body.get("keep") == keep]
        if same:
            earlier.append(same[-1])
            return []
        return [("choice", lambda seq: Choice(id=f"ch-{seq}", conflict_id=conflict_id, keep=keep, why=why, by=by,
                                              at=now()).model_dump(mode="json"))]

    written = store.review.append_if(decide)
    entry = written[0] if written else earlier[0]
    record = Choice.model_validate(entry.body)
    ledger.apply_choice(record)
    if written:
        store.audit(actor=by, action="intake.choice", resource_id=record.id, after={"id": record.id, "row_hash": entry.hash},
                    reason=why)
    return record


def _known_file(store: IntakeStore, sha256: Any) -> FileRecord:
    _id("sha256", sha256, "the file")
    record = intake_landing.file_records(store).get(sha256)
    if record is None:
        raise ReviewError("UNKNOWN", "no file with that sha256 arrived in this project")
    return record


def confirm_link(ws: Workspace, *, link_fact: str | None, study: str, file_sha256: str, confirmed: bool, why: str,
                 by: str) -> LinkConfirmation:
    """Confirm or refuse a cross-file link, per (study, file): the values of that file joined to the study count as
    its own once confirmed; refused, the fold excludes them (a refusal needs its reason). For an ambiguous link `study`
    is the candidate chosen, and the file's own study is merged into it (`Ledger.link_files`). One `link` line, one
    `intake.link` event; then the derived facts follow (`Ledger.derive`). The same decision again writes nothing."""
    if not isinstance(confirmed, bool):
        raise ReviewError("INVALID", "a link is confirmed or refused")
    why = why.strip() if isinstance(why, str) else ""
    if not confirmed:
        why = _why(why, "refusing a link")
    if link_fact is not None and not _id("line", link_fact, "the link fact").startswith("f-"):
        raise ReviewError("INVALID", f"not a fact's id: {link_fact!r}")
    store = IntakeStore(ws)
    _known_file(store, file_sha256)
    ledger = Ledger(ws)
    _id("line", study, "the study")
    entity = ledger.entity(study)
    if entity is None or entity.type != "study":
        raise ReviewError("UNKNOWN", f"no study {study!r} in this project's ledger")
    if link_fact is not None and ledger.value(link_fact) is None:
        raise ReviewError("UNKNOWN", f"no fact {link_fact}")
    latest: dict[tuple[str, str], LinkConfirmation] = {}
    for line in _lines(store, "link"):
        earlier = LinkConfirmation.model_validate(line.body)
        target = ledger.entity(earlier.study)
        latest[(target.id if target is not None else earlier.study, earlier.file_sha256)] = earlier
    same = latest.get((entity.id, file_sha256))
    if same is not None and same.confirmed == confirmed:
        return same
    waiting = [p for p in ledger.pending_links() if p.file_sha256 == file_sha256
               and (p.study == entity.id or entity.id in p.candidates)]
    if not waiting and same is None:
        raise ReviewError("UNKNOWN", f"no cross-file link of study {entity.label} and that file waits for a decision")
    entry = store.review.append("link", lambda seq: LinkConfirmation(
        id=f"lk-{seq}", link_fact=link_fact, study=entity.id, file_sha256=file_sha256, confirmed=confirmed, why=why, by=by,
        at=now()).model_dump(mode="json"))
    record = LinkConfirmation.model_validate(entry.body)
    store.audit(actor=by, action="intake.link", resource_id=record.id, after={"id": record.id, "row_hash": entry.hash},
                reason=why or None)
    ledger.refresh()
    ledger.link_files()
    ledger.derive()
    return record


def _target_values(reader: LedgerReader, target: str) -> list[ValueState]:
    """The values a target of an assignment names: a fact, one value of an extract, or every value of an extract."""
    if "#" in target or not target.startswith("tx-"):
        found = reader.value(target)
        return [found] if found is not None else []
    return [v for v in reader.values(active=False) if v.id.startswith(f"{target}#")]


def _new_name(reader: LedgerReader, kind: EntityType, label: Any) -> str:
    """A label a person gives a new study or product, checked before anything is written: ReviewError INVALID for a
    label with no letter or digit (it has no key to be known by), with a control character or longer than 80
    characters; CONFLICT, naming it, when a study or product of that key exists already (never a duplicate: the values
    are assigned to that one)."""
    label = label.strip() if isinstance(label, str) else ""
    if not name_key(label) or not label_key(label) or len(label) > 80 or any(ord(ch) < 32 or ord(ch) == 127 for ch in label):
        raise ReviewError("INVALID", f"a new {kind}'s name is at most 80 characters with a letter or a digit, on one "
                                     f"line: {label!r}")
    same = [e for e in reader.entities(kind) if label_key(e.label) == label_key(label)]
    if same:
        raise ReviewError("CONFLICT", f"a {kind} named {same[0].label!r} exists already ({same[0].id}): assign the "
                                      "values to it")
    return label


def assign(ws: Workspace, *, targets: Sequence[str], study: str | None = None, arm: str | None = None,
           product: str | None = None, batch: str | None = None, why: str, by: str, new_study: str | None = None,
           new_product: str | None = None) -> Assignment:
    """Give values their subject (§13): a study (and its arm), a product (and its batch), or both; at least one of
    study or product. `targets` are fact, extract or value ids. One `assignment` line, one `intake.assign` event; then
    the derived facts follow (`Ledger.derive`) and the coverage of the files concerned is recomputed and stored.

    `new_study`, `new_product`: a label, as the person writes it, of a study or a product no file's label gave an
    entity (a table whose title the rules do not read as a study id, a dissolution table that names only its batch).
    The ledger's write side creates it (`Ledger.name_entity`: no source, so it has no home file and its values are
    not cross-file values; one `intake.entity` event) and the values are assigned to it. A study is named by `study`
    or by `new_study`, never both, and so a product. Never a duplicate: a label whose key a study (a product) already
    has is refused with CONFLICT, naming that one. Everything is checked before the entity is written.

    An arm (a batch) is assigned with its study (its product). One that no study (no product) owns, read from a table
    that names its arm or batch and nothing above it, is assigned with the one named here: left out, the assignment
    clears it, as an `Assignment` does."""
    why = _why(why, "an assignment")
    if not targets:
        raise ReviewError("INVALID", "an assignment names the values it assigns")
    for kind, known, named in (("study", study, new_study), ("product", product, new_product)):
        if known is not None and named is not None:
            raise ReviewError("INVALID", f"an assignment names an existing {kind} or a new one, not both")
    if study is None and product is None and new_study is None and new_product is None:
        raise ReviewError("INVALID", "an assignment names a study or a product")
    if arm is not None and study is None and new_study is None:
        raise ReviewError("INVALID", "an arm is assigned with its study")
    if batch is not None and product is None and new_product is None:
        raise ReviewError("INVALID", "a batch is assigned with its product")
    ledger = Ledger(ws)
    if new_study is not None:
        new_study = _new_name(ledger, "study", new_study)
    if new_product is not None:
        new_product = _new_name(ledger, "product", new_product)
    files: set[str] = set()
    checked: list[str] = []
    for target in dict.fromkeys(targets):
        if isinstance(target, str) and target.startswith("tx-") and "#" not in target:
            _id("extract", target, "a target")
        else:
            _value_id(target, "a target")
        found = _target_values(ledger, target)
        if not found:
            raise ReviewError("UNKNOWN", f"no value {target} in this project's ledger")
        files |= {v.file_sha256 for v in found if v.file_sha256}
        checked.append(target)

    def entity_of(entity_id: str | None, kind: str, parent: str | None, *, fresh: bool = False) -> str | None:
        """The entity an id names. An arm or a batch must be one of the study's or product's named (`parent`), or one
        nothing owns yet, which is assigned with the study or product named (`fresh`: the one being created)."""
        if entity_id is None:
            return None
        _id("line", entity_id, f"the {kind}")
        entity = ledger.entity(entity_id)
        if entity is None or entity.type != kind:
            raise ReviewError("UNKNOWN", f"no {kind} {entity_id!r} in this project's ledger")
        if kind in ("arm", "batch"):
            owner = ledger.entity(entity.parent) if entity.parent else None
            unowned = entity.parent is None and (parent is not None or fresh)
            if not unowned and (fresh or parent is None or owner is None or owner.id != parent):
                raise ReviewError("INVALID", f"{kind} {entity.label} is not one of that {'study' if kind == 'arm' else 'product'}'s")
        return entity.id

    study_id = entity_of(study, "study", None)
    product_id = entity_of(product, "product", None)
    arm_id = entity_of(arm, "arm", study_id, fresh=new_study is not None)
    batch_id = entity_of(batch, "batch", product_id, fresh=new_product is not None)
    # every refusal is behind us: only now is a study or a product the person names written, by the ledger's write side
    try:
        if new_study is not None:
            study_id = ledger.name_entity("study", new_study, by=by, why=why).id
        if new_product is not None:
            product_id = ledger.name_entity("product", new_product, by=by, why=why).id
    except ValueError as exc:               # named by another person meanwhile: never a duplicate
        raise ReviewError("CONFLICT", str(exc)) from exc
    try:
        draft = Assignment(id="as-0", targets=tuple(checked), study=study_id, arm=arm_id, product=product_id,
                           batch=batch_id, why=why, by=by, at=now())
    except ValidationError as exc:
        raise ReviewError("INVALID", f"not an assignment: {exc.errors()[0]['msg']}") from exc
    store = IntakeStore(ws)
    entry = store.review.append("assignment", lambda seq: draft.model_copy(update={"id": f"as-{seq}"}).model_dump(mode="json"))
    record = Assignment.model_validate(entry.body)
    store.audit(actor=by, action="intake.assign", resource_id=record.id, after={"id": record.id, "row_hash": entry.hash},
                reason=why)
    ledger.refresh()
    ledger.derive()
    for sha in sorted(files):
        _store_coverage(store, sha, ledger, needs_source=False)
    return record


def _source(store: IntakeStore, sha256: str) -> SourceDocument | None:
    """The file's cached source model as its latest finished run parsed it; else the one cached (the latest version)."""
    versions = store.source_versions(sha256)
    if not versions:
        return None
    done = [r for r in _runs(store).values() if r.sha256 == sha256 and r.state == "done" and r.parser and r.parser_version
            and (r.parser, r.parser_version) in versions]
    if done:
        last = max(done, key=lambda r: (r.finished_at or "", r.run_id))
        return store.source(sha256, last.parser, last.parser_version)  # type: ignore[arg-type]
    return store.source(sha256, *versions[-1])


def _region_decisions(store: IntakeStore) -> list[RegionDecision]:
    return [RegionDecision.model_validate(e.body) for e in _lines(store, "region")]


def _store_coverage(store: IntakeStore, sha256: str, reader: LedgerReader, *, needs_source: bool) -> FileCoverage | None:
    """Recompute a file's coverage from its stored outcomes, ALL region decisions and the source cache, and store it
    (the coverage file is the current truth, §6.4). A file with no coverage yet (no finished run) has none to
    recompute. With no cached source model: ReviewError when the caller needs the regions (`needs_source`), else only
    the count of unassigned values is brought up to date."""
    current = store.coverage(sha256)
    if current is None:
        return None
    left = values_unassigned(reader, sha256)
    doc = _source(store, sha256)
    if doc is None:
        if needs_source:
            raise ReviewError("CONFLICT", "the file's source model is not cached: run the file again, then decide")
        patched = current.model_copy(update={"summary": current.summary.model_copy(update={"values_unassigned": left}),
                                             "computed_at": now()})
        store.put_coverage(patched)
        return patched
    made = file_coverage(current.file, doc, [r.outcome for r in current.regions], _region_decisions(store),
                         current.anchor_problems, values_unassigned=left)
    store.put_coverage(made)
    return made


def _region_values(ledger: Ledger, store: IntakeStore, doc: SourceDocument, region_id: str) -> list[str]:
    """What the ledger holds of one region, as targets to exclude: its active extracts; the active facts anchored in
    its cells (a table's text-valued and relation rows) or, for a prose region, in its paragraphs; and the facts read
    from its caption or context lines that belong to no subject (the analyte and the LLOQ a "study not stated" table
    names: they would keep the delivery blocked). A caption fact that has its subject is not the region's alone (two
    tables may cite one title): it stays, on its subject's card."""
    region = next((r for r in doc.regions if r.id == region_id), None)
    if region is None:
        return []
    active = {v.id.split("#")[0] for v in ledger.values(file_sha256=doc.file_sha256) if v.id.startswith("tx-")}
    targets = [ref.id for ref in (ExtractRef.model_validate(e.body) for e in store.facts.entries("extract"))
               if ref.file_sha256 == doc.file_sha256 and ref.region_id == region_id and ref.id in active]
    cells = [parse_locator(c.locator) for c in region_grid(doc, region_id).cells.values()] if region.kind == "table" else []
    for value in ledger.values(file_sha256=doc.file_sha256):
        if value.id.startswith("tx-") or not value.anchor:
            continue
        try:
            found = resolve(doc, value.anchor)
        except AnchorError:
            continue
        if found.region_id != region_id:
            continue
        if region.kind == "table" and not is_unassigned(value.entity, value.field):
            place = parse_anchor(value.anchor).locator
            if not any(type(cell) is type(place) and same_place(cell, place) for cell in cells):
                continue
        targets.append(value.id)
    return targets


def exclude_regions(ws: Workspace, *, file_sha256: str, regions: Sequence[str], scope: str, why: str, by: str) -> RegionDecision:
    """A person's decision that regions of a file are not data, with the reason. `scope` says what `regions` lists:
    `regions` region ids of any kind, `unread_prose` prose regions, `figures` figure regions (a table's numbers never
    leave silent loss through a prose or figure decision), `outside` the locators of outside items accepted as not
    data. One `region` line, one `intake.region` event. A decision of scope `regions`, `unread_prose` or `figures`
    also excludes what the ledger read from those regions (how a "study not stated" table is excluded). The file's
    coverage is recomputed and stored in the same call."""
    why = _why(why, "excluding regions")
    if scope not in _SCOPES:
        raise ReviewError("INVALID", f"a region decision's scope is one of {', '.join(_SCOPES)}, not {scope!r}")
    if not regions:
        raise ReviewError("INVALID", "a region decision lists what it excludes")
    store = IntakeStore(ws)
    _known_file(store, file_sha256)
    doc = _source(store, file_sha256)
    if doc is None:
        raise ReviewError("CONFLICT", "the file's source model is not cached: run the file first, then decide")
    listed = tuple(dict.fromkeys(regions))
    if scope == "outside":
        items = []
        for text in listed:
            try:
                items.append(parse_locator(text))
            except AnchorError as exc:
                raise ReviewError("INVALID", f"not a locator: {text!r}") from exc
        places = [parse_locator(item.where) for item in doc.outside if _is_locator(item.where)]
        for text, place in zip(listed, items, strict=True):
            if not any(type(p) is type(place) and same_place(p, place) for p in places):
                raise ReviewError("UNKNOWN", f"{text} is not an item outside every region of that file")
    else:
        kinds = {r.id: r.kind for r in doc.regions}
        allowed = _SCOPE_KINDS[scope]
        for region_id in listed:
            _id("region", region_id, "a region")
            if region_id not in kinds:
                raise ReviewError("UNKNOWN", f"no region {region_id} in that file")
            if allowed is not None and kinds[region_id] not in allowed:
                raise ReviewError("INVALID", f"region {region_id} is a {kinds[region_id]}: scope {scope} excludes only "
                                             f"{' and '.join(allowed)} regions (a table's numbers leave silent loss only "
                                             "through scope regions)")
    entry = store.review.append("region", lambda seq: RegionDecision(
        id=f"rd-{seq}", file_sha256=file_sha256, parser_version=doc.parser_version, regions=listed, scope=scope,  # type: ignore[arg-type]
        why=why, by=by, at=now()).model_dump(mode="json"))
    record = RegionDecision.model_validate(entry.body)
    store.audit(actor=by, action="intake.region", resource_id=record.id, after={"id": record.id, "row_hash": entry.hash},
                reason=why)
    ledger = Ledger(ws)
    if scope != "outside":
        for region_id in listed:
            for target in _region_values(ledger, store, doc, region_id):
                ledger.exclude(target, why=f"{record.id}: {why}", by=by)
    _store_coverage(store, file_sha256, ledger, needs_source=True)
    return record


def _is_locator(text: str) -> bool:
    try:
        parse_locator(text)
    except AnchorError:
        return False
    return True


# --- the spot check ---------------------------------------------------------------------------------------------------


def _draws(store: IntakeStore) -> list[tuple[ChainEntry, SpotCheckDraw]]:
    return [(e, SpotCheckDraw.model_validate(e.body)) for e in _lines(store, "spot_draw")]


def _records(store: IntakeStore) -> list[tuple[ChainEntry, SpotCheckRecord]]:
    return [(e, SpotCheckRecord.model_validate(e.body)) for e in _lines(store, "spot_check")]


def _draws_of(store: IntakeStore, reader: LedgerReader, subject_type: str, subject: str) -> list[tuple[ChainEntry, SpotCheckDraw]]:
    return [(e, d) for e, d in _draws(store) if d.subject_type == subject_type and _same_subject(reader, subject_type, subject, d.subject)]


def _blq_form(value: ValueState) -> str:
    """The marker form of a censored value: its verbatim with every number written `x` ("<0.5" and "<1" are one form)."""
    return _NUMBER.sub("x", value.verbatim.strip()) or "censored" if value.censored else ""


def _stratum(value: ValueState, rules: IntakeRules) -> str:
    """A value's stratum: the rules' `spot_check.strata`, each as name=value, joined by "|"."""
    found = unit_class(value.field)
    parts = {"table_kind": value.table_kind or "fact",
             "unit_class": found if found in rules.spot_check.unit_classes else "other",
             "blq_form": _blq_form(value), "cross_file": "yes" if value.cross_file is not None else "no"}
    return "|".join(f"{name}={parts.get(name, '')}" for name in rules.spot_check.strata)


def _overridden_values(reader: LedgerReader, store: IntakeStore, subject_type: SubjectType, subject: str) -> set[str]:
    """The values of the subject's checks that carry an override. The checks are those the ledger alone gives (no
    requirements, brief or molecular weight), so the draw depends only on the logs and the rules file."""
    named = {o.check_id for o in _overrides(store) if _same_subject(reader, subject_type, subject, o.subject)}
    if not named:
        return set()
    return {vid for check in run_checks(reader, subject_type=subject_type, subject=subject) if check.id in named
            for vid in check.values}


def _always(value: ValueState, rules: IntakeRules, overridden: set[str]) -> str | None:
    """Why a value is never sampled, or None."""
    spot = rules.spot_check
    if value.field in spot.always_verify_fields and (_number(value.value) is not None or value.censored):
        return "always:field"
    if value.id in overridden:
        return "always:override"
    if value.method in spot.always_verify_methods:
        return f"always:{value.method}"
    if "link" in spot.always_verify_cross_file and value.field.startswith("link."):
        return "always:link"
    if "scalar" in spot.always_verify_cross_file and value.cross_file is not None and not value.id.startswith("tx-"):
        return "always:cross_file"
    return None


def _sample(strata: dict[str, list[str]], seed: str, size: int, minimum: int) -> list[str]:
    """`minimum` from each stratum, then the remainder of `size` in proportion to what is left of each (largest
    remainder); inside a stratum by sha256(seed + value id). Everything when the strata hold at most `size` values."""
    ordered = {name: sorted(ids, key=lambda vid: hashlib.sha256((seed + vid).encode("utf-8")).hexdigest())
               for name, ids in sorted(strata.items())}
    total = sum(len(ids) for ids in ordered.values())
    if total <= size:
        return [vid for ids in ordered.values() for vid in ids]
    take = {name: min(minimum, len(ids)) for name, ids in ordered.items()}
    left = {name: len(ids) - take[name] for name, ids in ordered.items()}
    remainder, pool = max(0, size - sum(take.values())), sum(left.values())
    if remainder and pool:
        shares = {name: remainder * left[name] / pool for name in ordered}
        for name in ordered:
            take[name] += int(shares[name])
        spare = remainder - sum(int(s) for s in shares.values())
        for name in sorted(ordered, key=lambda n: (-(shares[n] - int(shares[n])), n))[:spare]:
            take[name] += 1
    return [vid for name, ids in ordered.items() for vid in ids[:take[name]]]


def _latest_ticks(store: IntakeStore, draws: Sequence[tuple[ChainEntry, SpotCheckDraw]]) -> dict[str, tuple[str, bool]]:
    """value id -> (the spot check that last ticked it, whether that tick was ok), over the records of these draws."""
    mine = {d.id for _e, d in draws}
    last: dict[str, tuple[str, bool]] = {}
    for _entry, record in _records(store):
        if record.draw_id in mine:
            for tick in record.ticks:
                last[tick.value_id] = (record.id, tick.ok)
    return last


def draw_spot_check(ws: Workspace, subject_type: SubjectType, subject: str, *, reader: LedgerReader, by: str,
                    blinded: bool) -> SpotCheckDraw:
    """Draw the subject's spot check from the ledger's state (see the module docstring) and store it (`spot_draw`).
    The same state gives the same draw: asked again with nothing changed, the stored draw is returned and nothing is
    written. `blinded` (required: `is_blinded`): a blinded study's spot check cannot be drawn (ReviewError BLINDED),
    since a tick compares a value with its source."""
    subject = _subject(reader, subject_type, subject)
    if blinded:
        raise ReviewError("BLINDED", "the study is blinded until the MAP is signed (D-15): its values are withheld, so "
                                     "its spot check cannot be drawn")
    store = IntakeStore(ws)
    rules = load_rules()
    heads = {**reader.heads(), "rules": RULES_SHA256}
    seed = hashlib.sha256(f"{reader.head().hash}|{subject}|{rules.version}".encode()).hexdigest()
    overridden = _overridden_values(reader, store, subject_type, subject)
    earlier = _draws_of(store, reader, subject_type, subject)
    ticked = _latest_ticks(store, earlier)
    always: list[str] = []
    strata: dict[str, str] = {}
    by_stratum: dict[str, list[str]] = {}
    for value in _values(reader, subject_type, subject, spread_facts=True):
        # a value whose latest tick failed is in every later draw as failed: never sampled away, never ticked again
        reason = FAILED_TICK if ticked.get(value.id, ("", True))[1] is False else _always(value, rules, overridden)
        if reason is not None:
            always.append(value.id)
            strata[value.id] = reason
        elif _number(value.value) is not None or value.censored:
            name = _stratum(value, rules)
            by_stratum.setdefault(name, []).append(value.id)
            strata[value.id] = name
    sampled = _sample(by_stratum, seed, rules.spot_check.size, rules.spot_check.min_per_stratum)
    drawn = {*always, *sampled}
    carried = {vid: sc for vid, (sc, ok) in sorted(ticked.items()) if ok and vid in drawn}
    draft = SpotCheckDraw(id="sd-0", subject_type=subject_type, subject=subject, seed=seed,
                          subject_digest=subject_digest(reader, subject_type, subject), rules_version=rules.version,
                          heads=heads, always=tuple(always), sampled=tuple(sampled),
                          strata={vid: strata[vid] for vid in sorted(drawn)}, carried=carried, by=by, at=now())
    content = draft.model_dump(mode="json", exclude={"id", "by", "at", "heads"})
    found: list[ChainEntry] = []

    def decide(entries: list[ChainEntry]) -> list[tuple[str, Any]]:
        mine = [e for e in entries if e.kind == "spot_draw" and e.body.get("subject_type") == subject_type
                and _same_subject(reader, subject_type, subject, str(e.body.get("subject")))]
        if mine and {k: v for k, v in mine[-1].body.items() if k not in ("id", "by", "at", "heads")} == content \
                and not any(e.kind == "spot_check" and e.body.get("draw_id") == mine[-1].body.get("id") for e in entries):
            found.append(mine[-1])
            return []
        return [("spot_draw", lambda seq: draft.model_copy(update={"id": f"sd-{seq}"}).model_dump(mode="json"))]

    written = store.review.append_if(decide)
    return SpotCheckDraw.model_validate((written[0] if written else found[0]).body)


def record_spot_check(ws: Workspace, draw_id: str, ticks: Sequence[SpotTick], *, by: str) -> SpotCheckRecord:
    """Record the ticks of a draw, once, as one record (`spot_check`): one tick for every value of the draw that is
    not carried and did not fail in an earlier draw (`always:failed`), no other value, none twice. The draw must be its subject's latest and not stale. A second submission
    of the same ticks gets the stored record and writes nothing (two requests, one line); other ticks for a draw
    already recorded are refused. One `intake.spot_check` event."""
    _id("line", draw_id, "the draw")
    store = IntakeStore(ws)
    draws = _draws(store)
    draw = next((d for _e, d in draws if d.id == draw_id), None)
    if draw is None or not draw_id.startswith("sd-"):
        raise ReviewError("UNKNOWN", f"no spot-check draw {draw_id}")
    given = tuple(SpotTick.model_validate(t) for t in ticks)
    wanted = [vid for vid in (*draw.always, *draw.sampled)
              if vid not in draw.carried and draw.strata.get(vid) != FAILED_TICK]
    ids = [t.value_id for t in given]
    if len(set(ids)) != len(ids):
        raise ReviewError("INVALID", "a value is ticked twice")
    if set(ids) != set(wanted):
        missing, extra = sorted(set(wanted) - set(ids)), sorted(set(ids) - set(wanted))
        raise ReviewError("INVALID", "the ticks are sent once, for every value of the draw: "
                          + "; ".join(b for b in (f"{len(missing)} values not ticked" if missing else "",
                                                  f"{len(extra)} ticks for values not in the draw" if extra else "") if b))
    reader = LedgerView(ws)
    subject_type: SubjectType = draw.subject_type  # type: ignore[assignment]
    mine = _draws_of(store, reader, subject_type, _subject(reader, subject_type, draw.subject))
    existing = next((r for _e, r in _records(store) if r.draw_id == draw_id), None)
    if existing is None:
        if mine and mine[-1][1].id != draw_id:
            raise ReviewError("STALE", f"draw {draw_id} is not the subject's latest: tick {mine[-1][1].id}")
        if _stale(draw, reader, store):
            raise ReviewError("STALE", "the subject's values or its overrides changed since the draw: draw again, then tick")
    order = {vid: i for i, vid in enumerate(wanted)}
    given = tuple(sorted(given, key=lambda t: order[t.value_id]))
    found: list[ChainEntry] = []

    def decide(entries: list[ChainEntry]) -> list[tuple[str, Any]]:
        same = [e for e in entries if e.kind == "spot_check" and e.body.get("draw_id") == draw_id]
        if same:
            found.append(same[0])
            return []
        return [("spot_check", lambda seq: SpotCheckRecord(id=f"sc-{seq}", draw_id=draw_id, ticks=given, by=by,
                                                           at=now()).model_dump(mode="json"))]

    written = store.review.append_if(decide)
    if not written:
        stored = SpotCheckRecord.model_validate(found[0].body)
        if stored.ticks != given:
            raise ReviewError("CONFLICT", f"the ticks of draw {draw_id} are recorded already ({stored.id}): they are "
                                          "accepted once")
        return stored
    entry = written[0]
    record = SpotCheckRecord.model_validate(entry.body)
    store.audit(actor=by, action="intake.spot_check", resource_id=record.id,
                after={"spot_check": record.id, "draw": draw_id, "ok": sum(1 for t in given if t.ok),
                       "not_ok": sum(1 for t in given if not t.ok), "row_hash": entry.hash})
    return record


def _stale(draw: SpotCheckDraw, reader: LedgerReader, store: IntakeStore) -> bool:
    """Whether a draw no longer describes its subject: the subject's digest or the rules file differs from the
    draw's, or a value of a check that carries an override now (every such value is verified, never sampled:
    decision 6) is outside the draw: the override was made after it."""
    subject = _resolved(reader, draw)
    if draw.subject_digest != subject_digest(reader, draw.subject_type, subject) or draw.heads.get("rules") != RULES_SHA256:
        return True
    overridden = _overridden_values(reader, store, draw.subject_type, subject)  # type: ignore[arg-type]
    if not overridden:
        return False
    drawn = {*draw.always, *draw.sampled, *draw.carried}
    active = {v.id for v in _values(reader, draw.subject_type, subject, spread_facts=True)}
    return any(vid in active and vid not in drawn for vid in overridden)


def _resolved(reader: LedgerReader, draw: SpotCheckDraw) -> str:
    if draw.subject_type == "compound":
        return COMPOUND
    entity = reader.entity(draw.subject)
    return entity.id if entity is not None else draw.subject


def _latest_spot_check(store: IntakeStore, reader: LedgerReader, subject_type: str, subject: str
                       ) -> tuple[ChainEntry, SpotCheckDraw, ChainEntry | None, SpotCheckRecord | None] | None:
    """The subject's latest draw and its record (None: not ticked yet)."""
    mine = _draws_of(store, reader, subject_type, subject)
    if not mine:
        return None
    entry, draw = mine[-1]
    record = next(((e, r) for e, r in _records(store) if r.draw_id == draw.id), (None, None))
    return entry, draw, record[0], record[1]


def latest_spot_check(ws: Workspace, subject_type: SubjectType, subject: str, *, reader: LedgerReader,
                      blinded: bool) -> tuple[SpotCheckDraw | None, SpotCheckRecord | None]:
    """The subject's latest draw and its record of ticks (None: not drawn, not ticked), for the card. `blinded`
    (required): a study blinded after its draw shows the draw without its strata (a stratum says which values are
    below the LLOQ) and the record without its notes."""
    subject = _subject(reader, subject_type, subject)
    found = _latest_spot_check(IntakeStore(ws), reader, subject_type, subject)
    if found is None:
        return None, None
    _entry, draw, _line, record = found
    if blinded:
        draw = draw.model_copy(update={"strata": {}})
        if record is not None:
            record = record.model_copy(update={"ticks": tuple(t.model_copy(update={"note": ""}) for t in record.ticks)})
    return draw, record


def spot_check_state(ws: Workspace, subject_type: SubjectType, subject: str, *, reader: LedgerReader) -> SpotCheckState:
    """`none`: no draw; `stale`: the subject's digest (or the rules file) differs from the latest draw's, or an
    override made after the draw names a value the draw does not hold; `failed`: a
    tick of it says a value is wrong, or it holds a value whose tick failed in an earlier draw (`always:failed`: a
    failed tick is cleared only by correcting, superseding or excluding the value, never by drawing again); `complete`: every value of `always` and `sampled` is ticked ok or carried;
    `drawn`: it waits for its ticks."""
    subject = _subject(reader, subject_type, subject)
    store = IntakeStore(ws)
    found = _latest_spot_check(store, reader, subject_type, subject)
    if found is None:
        return "none"
    _entry, draw, _line, record = found
    if _stale(draw, reader, store):
        return "stale"
    ticks = {t.value_id: t.ok for t in record.ticks} if record is not None else {}
    if any(not ok for ok in ticks.values()) or FAILED_TICK in draw.strata.values():
        return "failed"
    done = all(ticks.get(vid) or vid in draw.carried for vid in (*draw.always, *draw.sampled))
    return "complete" if done else "drawn"


# --- blockers, the bound record, the confirmation ------------------------------------------------------------------------


_SPOT_DETAIL = {"none": "the spot check has not been drawn", "drawn": "the spot check waits for its ticks",
                "failed": "a tick of the spot check says a value does not match its source: correct or exclude it, then "
                          "draw again",
                "stale": "the subject's values or its overrides changed since the spot check was drawn: draw again "
                         "(unchanged ticks carry over)"}


def blockers(ws: Workspace, subject_type: SubjectType, subject: str, *, reader: LedgerReader, brief: ProjectBrief | None,
             matrix: RequirementMatrix | None, mol_weight: float | None, blinded: bool,
             card: Scorecard | None = None) -> tuple[Blocker, ...]:
    """Every reason the subject's confirmation is refused: the scorecard's (silent loss, outside numbers, unassigned
    values, a schema gap, a failed check without an override, an unconfirmed cross-file link), then what
    `_own_refusals` gives from the workspace and the ledger alone: a file of its deliveries that is still being read
    or was not read (a failed run, no run, no coverage file: its numbers are not counted, `SILENT_LOSS`), the spot
    check (`SPOT_CHECK`: not drawn, not ticked, failed or stale), a dataset already accepted on the legacy card, a
    subject whose files are all a filled client-data template, which is confirmed on its legacy card only, a value
    that another study's accepted dataset still holds (`LOADED_ON_CLIENT_REVIEW`), and a blinded study (`BLINDED`,
    §11.1). Empty: the confirmation may be signed. `card`: the subject's scorecard when the caller has just computed
    it from the same `reader` and the same brief, matrix and molecular weight (`card`), so a request that shows the
    card and its blockers runs the checks once; else it is computed here."""
    found = _own_card(reader, subject_type, subject, card) or _card(ws, subject_type, subject, reader=reader, brief=brief,
                                                                     matrix=matrix, mol_weight=mol_weight)
    own = _own_refusals(ws, IntakeStore(ws), reader, subject_type, found.subject, blinded=blinded, links=False)
    return (*found.blockers, *own)


def _own_card(reader: LedgerReader, subject_type: SubjectType, subject: str, card: Scorecard | None) -> Scorecard | None:
    """A card a caller hands in, checked to be this subject's (ReviewError INVALID for another's); None when none is."""
    if card is not None and (card.subject_type != subject_type or card.subject != _subject(reader, subject_type, subject)):
        raise ReviewError("INVALID", "the card given is another subject's")
    return card


def _own_refusals(ws: Workspace, store: IntakeStore, reader: LedgerReader, subject_type: SubjectType, subject: str, *,
                  blinded: bool, links: bool) -> list[Blocker]:
    """What refuses a confirmation and needs only the workspace and the ledger (no brief, requirement matrix or
    molecular weight), so `record_confirmation` checks it again on its own: the files of the subject's deliveries
    (`_unread_files`), with `links` its cross-file links that wait for a reviewer or are ambiguous (the scorecard
    gives them to `blockers`), the spot check, the legacy card, another study's accepted dataset
    (`_landed_by_others`), and blinding (`blinded`: the caller's `is_blinded`, which needs the project's setting)."""
    values = _values(reader, subject_type, subject)
    out = _unread_files(store, _delivery_files(store, values))
    if links and subject_type == "study":
        pending = [link for link in reader.pending_links(study=subject) if link.state in ("unconfirmed", "ambiguous")]
        if pending:
            out.append(Blocker(code="LINK_UNCONFIRMED", detail=f"{len(pending)} cross-file links wait for a reviewer",
                               ids=tuple(link.id for link in pending)))
    state = spot_check_state(ws, subject_type, subject, reader=reader)
    if state != "complete":
        out.append(Blocker(code="SPOT_CHECK", detail=_SPOT_DETAIL[state]))
    accepted = [d.id for d in intake_landing.legacy_overlap(ws, subject_type, subject, reader=reader)
                if d.state is EvidenceState.ACCEPTED]
    if accepted:
        out.append(Blocker(code="LOADED_ON_CLIENT_REVIEW", detail=f"{len(accepted)} datasets of the same source are "
                           "accepted on the client-review card: nothing is loaded twice (reject them there to confirm here)",
                           ids=tuple(accepted)))
    elif confirm_on(ws, values) == CONFIRM_ON_CLIENT_REVIEW:
        out.append(Blocker(code="LOADED_ON_CLIENT_REVIEW", detail="every file of this subject is a filled client-data "
                           "template, which today's reader reads exactly: it is confirmed on the client-review card, "
                           "and shown here read-only"))
    out.extend(_landed_by_others(ws, store, reader, subject_type, subject))
    if blinded:
        out.append(Blocker(code="BLINDED", detail="the study is blinded until the MAP is signed (D-15): its values are "
                           "withheld, so it cannot be spot-checked or confirmed here"))
    return out


def _landed_by_others(ws: Workspace, store: IntakeStore, reader: LedgerReader, subject_type: str,
                      subject: str) -> list[Blocker]:
    """Nothing is loaded twice: one blocker for each confirmation of ANOTHER study that bound a value which is this
    study's now (a person assigned it here after that study was confirmed) and whose landed dataset is still accepted.
    That study is confirmed again first (its landing sets the dataset aside), or the dataset is rejected on its card.
    Only a study has datasets: a product's and the compound's values are never in one. A study merged into this one
    is this study (its earlier dataset is set aside by this one's landing, `intake_landing._retire_earlier`)."""
    if subject_type != "study":
        return []
    mine = {v.id for v in _values(reader, "study", subject, spread_facts=True)}
    by_id = {c.id: c for c in confirmations(ws) if c.subject_type == "study"}
    out = []
    for line in _lines(store, "landed"):
        done = Landed.model_validate(line.body)
        other = by_id.get(done.confirmation)
        if other is None or not done.datasets or _same_subject(reader, "study", subject, other.subject):
            continue
        facts = {str(row[0]) for row in other.record.get("facts", ())}
        extracts = {str(row[0]) for row in other.record.get("extracts", ())}
        left_out = {str(item) for item in other.record.get("excluded", ())}
        shared = [v for v in mine if v in facts or ("#" in v and v.split("#")[0] in extracts and v not in left_out)]
        if not shared:
            continue
        accepted = [d for d in done.datasets if (found := dataset_of(ws, d)) is not None
                    and found.state is EvidenceState.ACCEPTED]
        if accepted:
            label = intake_landing.subject_label(reader, "study", other.subject)
            out.append(Blocker(code="LOADED_ON_CLIENT_REVIEW", ids=tuple(accepted), detail=(
                f"{len(shared)} values of this study were bound by confirmation {other.id} of study {label}, whose "
                f"datasets ({', '.join(accepted)}) are still accepted: nothing is loaded twice (confirm study {label} "
                "again first, which sets them aside, or reject them on their card)")))
    return out


def _text(value: Any) -> Any:
    """A fact's value as the record writes it: a number as its shortest text, a bool as true or false, text as it is."""
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    return repr(float(value)) if isinstance(value, float) else str(value)


def bound_record(ws: Workspace, subject_type: SubjectType, subject: str, *, reader: LedgerReader,
                 brief: ProjectBrief | None, matrix: RequirementMatrix | None, mol_weight: float | None,
                 card: Scorecard | None = None) -> tuple[dict[str, Any], str]:
    """The canonical record a confirmation binds (§6.6, `confirmation/1`) and its sha256 (`sha256_of`). Scalar facts
    are bound by id, value and unit; extract values by the extract's id and content hash, with the value ids left out
    (`excluded`: every value of a listed extract that is not an active value of this subject); the subject's digest
    pins the set, so a fact of another subject does not change the record. Each of the subject's review lines is
    bound by its id and line hash; the spot check by its record (or, when every value was carried, its draw); the
    coverage of its deliveries' files, its requirement statuses, its checks (cleared ones as "overridden", the rest by
    severity), what the landing holds back, and the rules file's version, status and sha256. `card`: the subject's
    scorecard when the caller has just computed it from the same reader, brief, matrix and molecular weight (as
    `blockers` takes it); else it is computed here."""
    found = _own_card(reader, subject_type, subject, card) or _card(ws, subject_type, subject, reader=reader, brief=brief,
                                                                     matrix=matrix, mol_weight=mol_weight)
    subject = found.subject
    store = IntakeStore(ws)
    values = _values(reader, subject_type, subject, spread_facts=True)
    ids = {v.id for v in values}
    facts = sorted([v.id, _text(v.value), v.unit] for v in values if not v.id.startswith("tx-"))
    extract_ids = {v.id.split("#")[0] for v in values if v.id.startswith("tx-")}
    extracts, excluded = [], []
    for line in store.facts.entries("extract"):
        ref = ExtractRef.model_validate(line.body)
        if ref.id in extract_ids:
            extracts.append([ref.id, ref.content_sha256])
            excluded += [f"{ref.id}#{i}" for i in range(ref.n) if f"{ref.id}#{i}" not in ids]
    decisions = {(e.body.get("mapping_id"), e.body.get("version")): e.body.get("status")
                 for e in store.mappings.entries("decision")}
    mappings = sorted({(v.mapping.mapping_id, v.mapping.version) for v in values if v.mapping is not None})

    def mine(kind: str, keep: Any) -> list[str]:
        return [_ref(e) for e in _lines(store, kind) if keep(e.body)]

    def of_subject(body: dict[str, Any]) -> bool:
        return _same_subject(reader, subject_type, subject, str(body.get("subject")))

    def assigned(body: dict[str, Any]) -> bool:
        named = body.get("study") if subject_type == "study" else body.get("product") if subject_type == "product" else None
        if named is not None and _same_subject(reader, subject_type, subject, str(named)):
            return True
        return any(v.id in ids for target in body.get("targets", ()) for v in _target_values(reader, str(target)))

    def kept(body: dict[str, Any]) -> bool:
        value = reader.value(str(body.get("keep")))
        return value is not None and in_subject(value.entity, value.field, subject_type, subject)

    files = _delivery_files(store, values)
    coverage = [c.summary for c in _coverages(store, files)]
    spot = _latest_spot_check(store, reader, subject_type, subject)
    spot_ref = None if spot is None else _ref(spot[2]) if spot[2] is not None else _ref(spot[0])
    try:
        held = list(intake_landing.plan_landing(ws, None, subject_type, subject, reader=reader, matrix=matrix,
                                                mol_weight=mol_weight).held)
    except intake_landing.LandingError as exc:
        held = [f"{LANDING_REFUSED}: {exc}"]
    record = {
        "schema": RECORD_SCHEMA, "project": ws.project_id, "subject_type": subject_type, "subject": subject,
        "label": found.label, "subject_digest": subject_digest(reader, subject_type, subject), "facts": facts,
        "extracts": sorted(extracts), "excluded": sorted(excluded), "assignments": mine("assignment", assigned),
        "mappings": [[mapping_id, version, decisions.get((mapping_id, version), "proposed")] for mapping_id, version in mappings],
        "overrides": mine("override", of_subject), "dispositions": mine("disposition", of_subject),
        "choices": mine("choice", kept),
        "links": mine("link", lambda body: subject_type == "study" and _same_subject(reader, "study", subject, str(body.get("study")))),
        "regions": mine("region", lambda body: body.get("file_sha256") in files), "spot_check": spot_ref,
        "coverage": {"files": len(coverage), "silent_loss": sum(c.silent_loss for c in coverage),
                     "regions_unread": sum(c.regions_unread for c in coverage),
                     "outside_numeric": sum(c.outside_numeric for c in coverage),
                     "values_unassigned": sum(c.values_unassigned for c in coverage)},
        "requirements": sorted([r.req_id, r.status] for r in found.requirements),
        "checks": sorted([c.code, c.id, "overridden" if c.id in found.overridden else c.severity] for c in found.checks),
        "held": held, "rules": {"version": RULES_VERSION, "status": RULES_STATUS, "sha256": RULES_SHA256},
    }
    return record, sha256_of(record)


def prepare_confirmation(ws: Workspace, library: Any, subject_type: SubjectType, subject: str, *, reader: LedgerReader,
                         brief: ProjectBrief | None, matrix: RequirementMatrix | None, mol_weight: float | None,
                         blinded: bool) -> tuple[dict[str, Any], str, intake_landing.LandingPlan]:
    """Every refusal of a confirmation, checked in one call BEFORE anything is signed: every intake log's hash chain
    verifies and the subject has an active value (ReviewError CONFLICT otherwise), `blockers` is empty
    (`ConfirmationRefused` carries them otherwise) and the landing can be planned (`intake_landing.LandingError` names
    a `StudyRecord` field no value gives). Returns the record to sign, its sha256 and the landing plan. Nothing is
    written. The route then asks for the step-up, signs the hash, and calls `record_confirmation` and
    `intake_landing.land`; a confirmation `landing_incomplete` finds skips all of this and lands."""
    _chains_verify(IntakeStore(ws))
    _nothing_to_confirm(reader, subject_type, _subject(reader, subject_type, subject))
    # the card once: its blockers and the record it is bound in are of the same computation
    card = _card(ws, subject_type, subject, reader=reader, brief=brief, matrix=matrix, mol_weight=mol_weight)
    found = blockers(ws, subject_type, subject, reader=reader, brief=brief, matrix=matrix, mol_weight=mol_weight,
                     blinded=blinded, card=card)
    if found:
        raise ConfirmationRefused(found)
    plan = intake_landing.plan_landing(ws, library, subject_type, subject, reader=reader, matrix=matrix,
                                       mol_weight=mol_weight)
    record, sha = bound_record(ws, subject_type, subject, reader=reader, brief=brief, matrix=matrix, mol_weight=mol_weight,
                               card=card)
    return record, sha, plan


def _chains_verify(store: IntakeStore) -> None:
    """A confirmation binds lines of the intake logs by their hashes: it is refused (ReviewError CONFLICT, naming the
    log) while a log's chain does not verify: a line changed, removed or out of order (`ChainedLog.verify`). A torn
    last line is no such break: it was never acknowledged, and the next append removes it."""
    for name in _LOGS:
        broken = [p for p in getattr(store, name).verify() if p.problem != "torn_tail"]
        if broken:
            raise ReviewError("CONFLICT", f"the intake log {name} does not verify ({len(broken)} breaks, the first at line "
                                          f"{broken[0].seq}: {broken[0].problem}): nothing is confirmed over a broken chain")


def _nothing_to_confirm(reader: LedgerReader, subject_type: SubjectType, subject: str) -> None:
    """A subject with no active value (the empty compound, a study whose values were all excluded) has nothing to
    sign: ReviewError CONFLICT. No blocker code says this, so it is no `Blocker`."""
    if not _values(reader, subject_type, subject, spread_facts=True):
        raise ReviewError("CONFLICT", "the subject has no active value: there is nothing to confirm")


def _record_refusals(record: dict[str, Any]) -> list[str]:
    """What a bound record itself shows that refuses a confirmation (a net under `blockers`, which the route checks
    before it signs): silent loss, outside numbers or unassigned values in its coverage, a failed check that nobody
    cleared, no spot check, a landing that cannot be planned."""
    coverage = record.get("coverage") or {}
    out = [name for name in ("silent_loss", "outside_numeric", "values_unassigned") if coverage.get(name)]
    failed = sorted({str(row[0]) for row in record.get("checks", ()) if len(row) == 3 and row[2] == "fail"})
    if failed:
        out.append("failed checks (" + ", ".join(failed) + ")")
    if not record.get("spot_check"):
        out.append("no spot check")
    if any(str(text).startswith(LANDING_REFUSED) for text in record.get("held", ())):
        out.append("the landing cannot be planned")
    return out


def record_confirmation(ws: Workspace, *, subject_type: SubjectType, subject: str, record: dict[str, Any], record_sha256: str,
                        signature_id: str, manifestation: str, by: str, printed_name: str, blinded: bool) -> Confirmation:
    """Record a signed confirmation (`confirmation`, id cf-n): one line per record hash, so a double submit gives one
    line and the first one back. The signature is the API's (step-up); its id and manifestation are passed in, never a
    password. It supersedes the subject's current confirmation. One `intake.confirm` event.

    The route signs only after `prepare_confirmation`; this function does not rely on that. It refuses, and writes
    nothing, when:
    - the record's hash is not `record_sha256`, the record is not this subject's, or its digest is no longer the
      subject's (ReviewError INVALID, STALE);
    - the subject has no active value, or an intake log's hash chain does not verify (ReviewError CONFLICT);
    - the record itself shows a refusal (`_record_refusals`: silent loss, outside numbers or unassigned values in its
      coverage, a failed check nobody cleared, no spot check, a landing that cannot be planned: ReviewError CONFLICT);
    - the workspace and the ledger show one now (`_own_refusals`, `ConfirmationRefused` with the blockers): a file of
      the subject's deliveries still being read or not read, a cross-file link that waits or is ambiguous, a spot
      check that is not complete (not drawn, not ticked, a failed tick, stale), a dataset of the same source accepted
      on the legacy card (or a subject of template files only), a value another study's accepted dataset still holds,
      or `blinded` (required: the caller's `is_blinded`; the project's blinding setting is not the ledger's to read).
    What it cannot see, and only `prepare_confirmation` checks: a schema gap, a check that fails only with the brief,
    the requirement matrix or the molecular weight, and a record computed with other ones than the route's."""
    _id("sha256", record_sha256, "the record's hash")
    if not isinstance(signature_id, str) or not signature_id.strip():
        raise ReviewError("INVALID", "a confirmation carries its signature's id")
    reader = LedgerView(ws)
    subject = _subject(reader, subject_type, subject)
    if sha256_of(record) != record_sha256:
        raise ReviewError("INVALID", "the record does not have that hash: the signature binds the record as computed")
    if record.get("schema") != RECORD_SCHEMA or record.get("project") != ws.project_id \
            or record.get("subject_type") != subject_type or record.get("subject") != subject:
        raise ReviewError("INVALID", "the record is not this subject's")
    if record.get("subject_digest") != subject_digest(reader, subject_type, subject):
        raise ReviewError("STALE", "the subject's values changed since the record was computed: compute it again")
    _nothing_to_confirm(reader, subject_type, subject)
    _chains_verify(IntakeStore(ws))
    shown = _record_refusals(record)
    if shown:
        raise ReviewError("CONFLICT", "the record shows what still refuses the confirmation (" + "; ".join(shown)
                          + "): every refusal is checked before a confirmation is signed")
    store = IntakeStore(ws)
    refusals = _own_refusals(ws, store, reader, subject_type, subject, blinded=blinded, links=True)
    if refusals:
        raise ConfirmationRefused(refusals)
    found: list[ChainEntry] = []

    def decide(entries: list[ChainEntry]) -> list[tuple[str, Any]]:
        mine = [e for e in entries if e.kind == "confirmation" and e.body.get("subject_type") == subject_type
                and _same_subject(reader, subject_type, subject, str(e.body.get("subject")))]
        same = [e for e in mine if e.body.get("record_sha256") == record_sha256]
        if same:
            found.append(same[0])
            return []
        replaced = {e.body.get("supersedes") for e in mine if e.body.get("supersedes")}
        current = [e.body.get("id") for e in mine if e.body.get("id") not in replaced]
        return [("confirmation", lambda seq: Confirmation(
            id=f"cf-{seq}", subject_type=subject_type, subject=subject, record_sha256=record_sha256, record=record,
            signature_id=signature_id, manifestation=manifestation, by=by, printed_name=printed_name, at=now(),
            supersedes=current[-1] if current else None).model_dump(mode="json"))]

    written = store.review.append_if(decide)
    if not written:
        return Confirmation.model_validate(found[0].body)
    entry = written[0]
    confirmation = Confirmation.model_validate(entry.body)
    store.audit(actor=by, action="intake.confirm", resource_id=confirmation.id,
                after={"confirmation": confirmation.id, "record_sha256": record_sha256, "signature_id": signature_id,
                       "row_hash": entry.hash})
    return confirmation


def landing_incomplete(ws: Workspace, subject_type: SubjectType, subject: str, record_sha256: str) -> Confirmation | None:
    """A confirmation of that record hash for the subject with no `landed` line: its landing was interrupted, and
    completes with no new signature (its refusals were checked when it was signed)."""
    reader = LedgerView(ws)
    subject = _subject(reader, subject_type, subject)
    store = IntakeStore(ws)
    done = {e.body.get("confirmation") for e in _lines(store, "landed")}
    for confirmation in confirmations(ws):
        if confirmation.subject_type == subject_type and confirmation.record_sha256 == record_sha256 \
                and confirmation.id not in done and _same_subject(reader, subject_type, subject, confirmation.subject):
            return confirmation
    return None


def covered_by_confirmation(ws: Workspace, dataset: ObservedDataset) -> Confirmation | None:
    """The signed Delivery confirmation that already covers a legacy client dataset, by the overlap of §2 (the file,
    the sheet or page, and the study's key or an equal point): the legacy routes refuse to confirm it again. None for
    a dataset the Delivery landed itself, one that is not a client file's, or one no confirmation covers."""
    if dataset.origin is not Origin.CLIENT or intake_landing.is_delivery_dataset(dataset) or dataset.source.doc_sha256 is None:
        return None
    store = IntakeStore(ws)
    if not store.available:
        return None
    found = confirmations(ws)
    replaced = {c.supersedes for c in found if c.supersedes}
    current = [c for c in found if c.subject_type == "study" and c.id not in replaced]
    if not current:
        return None
    reader = LedgerView(ws)
    for confirmation in current:
        entity = reader.entity(confirmation.subject)
        if entity is None:
            continue
        bound = [v for v in reader.values(study=entity.id) if v.confirmation == confirmation.id]
        if bound and intake_landing.bound_overlap(ws, reader, bound, entity.id, candidates=[dataset]):
            return confirmation
    return None


# --- blinding (D-15) ----------------------------------------------------------------------------------------------------


def blinded_subjects(ws: Workspace, project: dict[str, Any] | None, model_risk: str | None) -> set[str]:
    """The ledger's studies (entity ids) whose values are withheld now: with the project's blinding on and no MAP
    signed, every study one of whose active `intended_use` values is an external purpose
    (`blinding.EXTERNAL_PURPOSES`), and every study a dataset of which the Delivery landed is one of
    `blinding.blinded_studies` (the plan put it in S5 or S6, or it was entered for external validation). Empty when
    blinding is off or a MAP is signed."""
    store = IntakeStore(ws)
    if not store.available or not blinding.setting(project, model_risk)["on"] or blinding.map_signed(ws):
        return set()
    reader = LedgerView(ws)
    out = set()
    for value in reader.values(field="intended_use"):
        if value.entity.study and (read_choice("intended_use", str(value.value)) or str(value.value)) in blinding.EXTERNAL_PURPOSES:
            out.add(value.entity.study)
    hidden = blinding.blinded_studies(ws, project, model_risk)
    if hidden:
        by_confirmation = {c.id: c for c in confirmations(ws) if c.subject_type == "study"}
        for line in _lines(store, "landed"):
            done = Landed.model_validate(line.body)
            confirmation = by_confirmation.get(done.confirmation)
            entity = reader.entity(confirmation.subject) if confirmation is not None else None
            if entity is None:
                continue
            for dataset_id in done.datasets:
                found = dataset_of(ws, dataset_id)
                if found is not None and str(found.study.get("study_id")) in hidden:
                    out.add(entity.id)
    return out


def is_blinded(reader: LedgerReader, subject_type: SubjectType, subject: str, hidden: Collection[str]) -> bool:
    """Whether a subject is blinded: a study among `hidden` (`blinded_subjects`), or a product or the compound one of
    whose active values is a blinded study's. What `card`, `draw_spot_check` and `blockers` take as `blinded`."""
    if not hidden:
        return False
    subject = _subject(reader, subject_type, subject)
    if subject_type == "study":
        return subject in hidden
    return any(v.entity.study in hidden for v in _values(reader, subject_type, subject, spread_facts=True))


def withheld(value: ValueState) -> ValueState:
    """A value without what D-15 withholds: its value, verbatim, spread, interval, LLOQ and ULOQ (None, ""), and
    whether it is below the LLOQ (so no count of such values can be made). Its place, field, unit, time, labels and
    status stay, as a blinded dataset keeps its times and metadata (`blinding.redact_dataset`)."""
    return value.model_copy(update={"value": None, "verbatim": "", "spread": None, "interval": None, "lloq": None,
                                    "uloq": None, "censored": False, "status_reason": ""})


def shown(values: Iterable[ValueState], hidden: Collection[str]) -> list[tuple[ValueState, bool]]:
    """Values as a route may show them: (value, blinded), a blinded study's value `withheld`. `hidden` is required
    (`blinded_subjects`): every route that lists values goes through here."""
    return [(withheld(v), True) if v.entity.study in hidden else (v, False) for v in values]


def source_view(ws: Workspace, *, reader: LedgerReader, hidden: Collection[str], value: str | None = None,
                anchor: str | None = None) -> tuple[SourceView, FileRecord, str | None]:
    """What the review shows beside a value (`modeler_intake.source.source_view`): the view, the file's record and the
    value's id. Give a value's id (its cell highlighted, and its time, unit, label, spread, n and LLOQ cells by role)
    or an anchor text. The id or anchor is checked before use, and an anchor resolves only for a file with a
    `FileRecord` in this project, in a source model this project cached (§5: no path is built from input). In a
    region that holds a value of a blinded study (`hidden`), every cell with a number and every cell a value of the
    file is anchored at (a "BLQ" or a missing-sample mark has no digit) is blank, and every digit of a paragraph and
    of the title is masked. ReviewError INVALID, UNKNOWN, or CONFLICT when the source model is not cached."""
    if (value is None) == (anchor is None):
        raise ReviewError("INVALID", "give a value's id or an anchor, one of them")
    also: dict[str, str] = {}
    found: ValueState | None = None
    if value is not None:
        found = reader.value(_value_id(value, "the value"))
        if found is None:
            raise ReviewError("UNKNOWN", f"no value {value} in this project's ledger")
        if not found.anchor:
            raise ReviewError("UNKNOWN", f"{value} has no source: a person entered it, or code derived it from "
                                         f"{', '.join(found.derived_from) or 'other values'}")
        anchor, also = found.anchor, dict(found.locators)
    try:
        parsed = parse_anchor(anchor)  # type: ignore[arg-type]
    except AnchorError as exc:
        raise ReviewError("INVALID", f"not an anchor: {exc}") from exc
    store = IntakeStore(ws)
    file = _known_file(store, parsed.file_sha256)
    doc = store.source(parsed.file_sha256, parsed.parser, parsed.parser_version)
    if doc is None:
        raise ReviewError("CONFLICT", "the source model that anchor was read from is not cached: run the file again")
    try:
        view = document_view(doc, anchor, also=also)  # type: ignore[arg-type]
    except AnchorError as exc:
        raise ReviewError("UNKNOWN", f"the anchor names no place of {file.name}: {exc}") from exc
    if hidden and _holds_blinded(doc, view, reader, hidden):
        # a mark with no digit ("BLQ", a missing-sample mark) is a value too: the cells the file's values are anchored
        # at are blank with the cells that hold a number, so no value and no count of values below the LLOQ is shown
        anchored = {_locator(v.anchor) for v in reader.values(file_sha256=doc.file_sha256, active=False) if v.anchor}
        view = view.model_copy(update={
            "cells": tuple(c.model_copy(update={"text": ""}) if c.numeric or c.locator in anchored else c for c in view.cells),
            "text": _DIGIT.sub("•", view.text), "title": _DIGIT.sub("•", view.title)})
    return view, file, found.id if found is not None else None


def _holds_blinded(doc: SourceDocument, view: SourceView, reader: LedgerReader, hidden: Collection[str]) -> bool:
    """Whether the view's region holds a value of a blinded study: a value read from the region (its extract names
    it), or one whose anchor or label cells resolve into it; with no region, one anchored at the view's own place."""
    values = [v for v in reader.values(file_sha256=doc.file_sha256, active=False) if v.entity.study in hidden]
    if not values:
        return False
    if view.region_id is None:
        places = {c.locator for c in view.cells}
        return any(_locator(v.anchor) in places for v in values) or view.kind == "text"
    for value in values:
        for text in (value.anchor, *value.locators.values()):
            try:
                if text and resolve(doc, text).region_id == view.region_id:
                    return True
            except AnchorError:
                continue
    return False


def _locator(anchor: str | None) -> str:
    try:
        return format_locator(parse_anchor(anchor).locator) if anchor else ""
    except AnchorError:
        return ""
