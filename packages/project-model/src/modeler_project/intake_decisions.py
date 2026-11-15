"""A person's decisions on a delivery, each with who made it, when, why and what it is about (plan 2026-11-14 §2.2.4;
final review INT-1, INT-6, INT-8).

The study card lists, before "Confirm and sign", every decision its signature binds: the subject's own (a check
accepted as is, a required item settled, a fact entered or corrected, a disagreement kept, a link between files, values
linked to it) and the clean-up of its files (a table or a note marked as not data and its restore, a table layout
approved or rejected); the clean-up decided in the delivery's other files is bound too (contracts §11.10: the gate is
per delivery). `decisions` reads them from the intake's logs, where each line already holds who, when and why, so the
card does not read the audit trail. The audit trail's view masks the why of a decision about a blinded study or about a
file that holds a blinded study's values (`blinded_records`): the delivery's own rule (D-15), digits masked, as a
region decision's why is on the delivery page.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import ValidationError

from modeler_intake.anchors import AnchorError, SheetCell, parse_anchor
from modeler_project.intake_landing import COMPOUND
from modeler_project.intake_records import (
    Assignment,
    Choice,
    LinkConfirmation,
    MappingDecision,
    Override,
    RegionDecision,
    RequirementDisposition,
)
from modeler_project.intake_store import IntakeStore
from modeler_project.ledger_view import LedgerReader, is_compound_field
from modeler_project.workspace import Workspace

Kind = Literal["override", "disposition", "entry", "choice", "link", "assign", "not_data", "restore", "layout"]
_DIGIT = re.compile(r"\d")


def mask(text: str) -> str:
    """What D-15 leaves of a person's words about a blinded study: every digit masked (a person may have quoted a value),
    as the delivery masks a region decision's why and a failed run's message."""
    return _DIGIT.sub("•", text)


@dataclass(frozen=True)
class PersonDecision:
    """One decision of a person. `id`: the line's id (ov-n, dp-n, f-n, ch-n, lk-n, as-n, rd-n), or a layout's
    "<mapping id>/<version>/<n>" (its n-th decision). `subjects`: the studies, products and the compound it is about
    (ledger ids followed through merges; "compound"); `files`: the files it is about (sha256s): a layout's are every
    file one of whose tables a version of it reads now."""

    id: str
    kind: Kind
    by: str
    at: str
    why: str
    subjects: frozenset[str]
    files: frozenset[str]
    record: dict[str, Any]


def blinded_files(reader: LedgerReader, hidden: Collection[str]) -> set[str]:
    """The files that hold a value of a blinded study (`intake_review.blinded_subjects`), active or not: their captions,
    outside text, table bodies, page texts and the why of decisions about them are not shown (one rule for the
    delivery page, the client files' page and a document's pages)."""
    if not hidden:
        return set()
    return {v.file_sha256 for v in reader.values(active=False) if v.file_sha256 and v.entity.study in hidden}


def blinded_sheets(reader: LedgerReader, hidden: Collection[str]) -> dict[str, set[str]]:
    """The sheets of each workbook a blinded study's values were read from (by the file's sha256): the sheet form does
    not show or read them until the plan is signed. A file's other sheets (another study's) stay open."""
    out: dict[str, set[str]] = {}
    if not hidden:
        return out
    for value in reader.values(active=False):
        if value.entity.study not in hidden or not value.file_sha256:
            continue
        for text in (value.anchor, *value.locators.values()):
            try:
                locator = parse_anchor(text).locator if text else None
            except AnchorError:
                continue
            if isinstance(locator, SheetCell):
                out.setdefault(value.file_sha256, set()).add(locator.sheet)
    return out


def _resolved(reader: LedgerReader, entity_id: str | None) -> str | None:
    if entity_id is None:
        return None
    if entity_id == COMPOUND:
        return COMPOUND
    found = reader.entity(entity_id)
    return found.id if found is not None else entity_id


def _value_subjects(reader: LedgerReader, value_id: str) -> tuple[set[str], set[str]]:
    """The subjects and the file of a value (by its id), as the ledger holds it now."""
    found = reader.value(value_id)
    if found is None:
        return set(), set()
    subjects = {s for s in (found.entity.study, found.entity.product) if s}
    if not subjects and is_compound_field(found.field):
        subjects.add(COMPOUND)
    return subjects, {found.file_sha256} if found.file_sha256 else set()


def target_values(reader: LedgerReader, target: str) -> list[Any]:
    """The values a target of an assignment names: a fact, one value of an extract, or every value of an extract."""
    if "#" in target or not target.startswith("tx-"):
        found = reader.value(target)
        return [found] if found is not None else []
    return [v for v in reader.values(active=False) if v.id.startswith(f"{target}#")]


def _layout_files(store: IntakeStore, shas: Iterable[str]) -> dict[str, set[str]]:
    """The files each mapping (by id, any version) reads a table of now, from the files' stored coverage."""
    out: dict[str, set[str]] = {}
    for sha in sorted(set(shas)):
        coverage = store.coverage(sha)
        for found in (coverage.regions if coverage is not None else ()):
            if found.outcome.mapping is not None:
                out.setdefault(found.outcome.mapping.mapping_id, set()).add(sha)
    return out


def decisions(ws: Workspace, *, reader: LedgerReader) -> list[PersonDecision]:
    """Every decision a person made on the project's deliveries, in the order of their logs (the review log, the
    person's entries, the layout decisions)."""
    store = IntakeStore(ws)
    if not store.available:
        return []
    out: list[PersonDecision] = []

    def add(record: Any, kind: Kind, subjects: Iterable[str | None], files: Iterable[str | None], *,
            line_id: str | None = None, why: str | None = None) -> None:
        body = record.model_dump(mode="json") if hasattr(record, "model_dump") else dict(record)
        out.append(PersonDecision(id=line_id or str(body["id"]), kind=kind, by=str(body.get("by", "")),
                                  at=str(body.get("at", "")), why=str(why if why is not None else body.get("why", "")),
                                  subjects=frozenset(s for s in subjects if s), files=frozenset(f for f in files if f),
                                  record=body))

    for entry in store.review.entries():
        try:
            if entry.kind == "override":
                o = Override.model_validate(entry.body)
                add(o, "override", [_resolved(reader, o.subject)], [])
            elif entry.kind == "disposition":
                d = RequirementDisposition.model_validate(entry.body)
                add(d, "disposition", [_resolved(reader, d.subject)], [])
            elif entry.kind == "choice":
                c = Choice.model_validate(entry.body)
                subjects, files = _value_subjects(reader, c.keep)
                add(c, "choice", subjects, files)
            elif entry.kind == "link":
                link = LinkConfirmation.model_validate(entry.body)
                add(link, "link", [_resolved(reader, link.study)], [link.file_sha256])
            elif entry.kind == "assignment":
                a = Assignment.model_validate(entry.body)
                files = {v.file_sha256 for t in a.targets for v in target_values(reader, t) if v.file_sha256}
                add(a, "assign", [_resolved(reader, a.study), _resolved(reader, a.product)], files)
            elif entry.kind == "region":
                r = RegionDecision.model_validate(entry.body)
                add(r, "restore" if r.restores else "not_data", [], [r.file_sha256])
        except ValidationError:
            continue
    for entry in store.facts.entries("fact"):
        body = entry.body
        if body.get("method") != "person" or not body.get("id"):
            continue
        subjects, _files = _value_subjects(reader, str(body["id"]))
        add(body, "entry", subjects, [], why=str(body.get("reason", "")))
    uses = _layout_files(store, (f.body.get("sha256") for f in store.files.entries("file") if f.body.get("sha256")))
    seen: dict[tuple[str, int], int] = {}
    for entry in store.mappings.entries("decision"):
        try:
            m = MappingDecision.model_validate(entry.body)
        except ValidationError:
            continue
        n = seen[(m.mapping_id, m.version)] = seen.get((m.mapping_id, m.version), 0) + 1
        add(m, "layout", [], uses.get(m.mapping_id, ()), line_id=f"{m.mapping_id}/{m.version}/{n}")
    return out


def blinded_records(decided: Iterable[PersonDecision], *, hidden: Collection[str], files: Collection[str],
                    blinded_subjects: Collection[str] = ()) -> set[str]:
    """The ids of the decisions whose why is masked now: about a blinded study (`hidden`, or a product or the compound
    the caller found blinded, `blinded_subjects`), or about a file that holds a blinded study's values (`files`)."""
    out = set()
    for d in decided:
        if d.subjects & set(hidden) or d.subjects & set(blinded_subjects) or d.files & set(files):
            out.add(d.id)
    return out


def blinded_audit(ws: Workspace, *, reader: LedgerReader, hidden: Collection[str]) -> set[str]:
    """The intake events of the audit trail whose reason is masked now, by their resource (the project's id left off):
    a decision's line id, a layout's "<mapping id>/<version>", an entity's id. A decision about a blinded study
    (`hidden`), a product one of whose values is a blinded study's, or a file that holds one's values; a study, arm,
    product or batch named with a reason under a blinded study. Empty with nothing blinded."""
    if not hidden:
        return set()
    files = blinded_files(reader, hidden)
    products = {v.entity.product for v in reader.values() if v.entity.product and v.entity.study in hidden}
    decided = decisions(ws, reader=reader)
    masked = blinded_records(decided, hidden=hidden, files=files, blinded_subjects=products)
    out = {d.id.rsplit("/", 1)[0] if d.kind == "layout" else d.id for d in decided if d.id in masked}
    for kind in ("study", "arm", "product", "batch"):
        for entity in reader.entities(kind):  # type: ignore[arg-type]
            if entity.id in hidden or entity.id in products or entity.parent in hidden or entity.parent in products:
                out.add(entity.id)
    return out
