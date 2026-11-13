"""Cross-file links (contracts §6.3): the owner's five conditions, as code.

A study of one file is joined to a study of another only through an ANCHORED link: (1) the `link.study_id` fact
`ledger_entities.resolve` writes at the second file's label cell, or an explicit `link.protocol` /
`link.cross_reference` fact (a cell or a quoted sentence) about the file's OWN study (a study whose home file is the
fact's file, not merged into another) whose names, together, name exactly one study of another file, which
`Ledger.link_files` turns into a `Merge` of the file's study with `link_fact` set. A link fact on a study of another
file (the file's label joined it through `link.study_id`, or an earlier merge did) joins nothing more: it never merges
two studies of other files. An upload tag, the same drug or similar dates never qualify, and nothing here reads them.
(2) Two or more candidate studies: an ambiguous `PendingLink`, nothing joined, until a person confirms one
(`LinkConfirmation` with the study chosen: the file's study is then merged into it).
(3) The fold sets `cross_file` (the value's, the link's and the receiving study's anchors) on every value whose file
is not its study's home file. (4) Those values wait for a `LinkConfirmation` of (study, file): one confirmation covers
every later value through the same link; a refusal excludes them (the fold); a person's assignment or merge is itself
the confirmation. (5) `cross_file` is on every view; the landing writes it on the dataset.

Matching a link's text to a study is by `label_key` only: the study's label, or a `study_id`, `reference` or
`link.protocol` value its home file states. Never by similarity.

A value joined to a study of another file through a link code made is used as joined (a derived fact from it, a series'
n) only once a person confirmed that (study, file) link (`link_settled`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from modeler_intake.anchors import sha256_of
from modeler_project.intake_records import LinkConfirmation
from modeler_project.ledger_entities import home_file, label_key, now, review_targets
from modeler_project.ledger_models import Alias, Entity, Merge, PendingLink, ValueState
from modeler_project.ledger_view import LedgerReader

EXPLICIT = ("link.protocol", "link.cross_reference")
# the values a study's home file states that name it, besides its label
_NAMES_A_STUDY = ("study_id", "reference", "link.protocol")
_ACTIVE = ("proposed", "confirmed")
# a link a person made: an assignment, or a merge with no link fact (the fold's "merge:<from id>")
_BY_A_PERSON = ("as-", "merge:")


def _pending_id(*parts: str | None) -> str:
    return "pl-" + sha256_of([p or "" for p in parts])[:10]


def link_facts(reader: LedgerReader) -> list[ValueState]:
    """The active facts whose field starts with "link."."""
    return [v for v in reader.values() if v.field.startswith("link.")]


def _studies(reader: LedgerReader) -> tuple[dict[str, Entity], dict[str, str | None], dict[str, set[str]]]:
    """The surviving studies, their home files and the keys that name each (its label's, and those its home file
    states)."""
    studies = {e.id: e for e in reader.entities("study")}
    homes = {sid: home_file(e) for sid, e in studies.items()}
    names = {sid: {label_key(e.label)} for sid, e in studies.items()}
    for value in reader.values():
        sid = value.entity.study
        if value.field in _NAMES_A_STUDY and sid in names and isinstance(value.value, str) \
                and value.file_sha256 is not None and value.file_sha256 == homes[sid] and label_key(value.value):
            names[sid].add(label_key(value.value))
    return studies, homes, names


def _count(reader: LedgerReader, study: str) -> int:
    return len(reader.values(study=study))


def explicit_links(reader: LedgerReader) -> tuple[list[Merge], list[PendingLink]]:
    """The merges the explicit links call for (not written: `Ledger.link_files` writes them) and the ambiguous ones.
    The `link.protocol` and `link.cross_reference` facts of file F about F's OWN study S (S's home file is F) name, by
    key, studies of OTHER files: together exactly one, C: merge S into C (`link_fact` the first fact that names it); two
    or more: one ambiguous pending link, nothing merged; none: nothing yet. A link fact on a study whose home is another
    file (F's label joined it, or S was merged already) joins nothing: it never merges two studies of other files, so a
    re-run proposes nothing more. A link fact that names no study of its own (S None) joins nothing: its file's values
    wait for a person's assignment."""
    _studies_by_id, homes, names = _studies(reader)
    named: dict[tuple[str, str], list[tuple[ValueState, list[str]]]] = {}       # (file, S) -> its link facts
    for fact in link_facts(reader):
        if fact.field not in EXPLICIT or not isinstance(fact.value, str):
            continue
        key, file, local = label_key(fact.value), fact.file_sha256, fact.entity.study
        if not key or file is None or local is None or homes.get(local) != file:
            continue
        candidates = sorted(sid for sid, keys in names.items()
                            if key in keys and sid != local and homes[sid] not in (None, file))
        named.setdefault((file, local), []).append((fact, candidates))
    merges: list[Merge] = []
    pending: list[PendingLink] = []
    for (file, local), facts in named.items():
        candidates = sorted({c for _fact, found in facts for c in found})
        if not candidates:
            continue
        first = next(fact for fact, found in facts if found)
        if len(candidates) == 1:
            merges.append(Merge(type="study", from_id=local, into_id=candidates[0], link_fact=first.id,
                                why=f"{first.field} {first.value!r} names that study (fact {first.id})", by="code",
                                at=now()))
        else:
            pending.append(PendingLink(id=_pending_id(file, local, first.id), link_fact=first.id, study=local,
                                       file_sha256=file, values=_count(reader, local), candidates=tuple(candidates),
                                       state="ambiguous"))
    return merges, pending


def _ambiguous(reader: LedgerReader, *, review: Mapping[str, Any] | None = None,
               aliases: Sequence[Alias] = ()) -> list[PendingLink]:
    """The studies `resolve` made file-local because their label named two or more studies of other files: a study
    created when studies of other files with its key, or with a key a confirmed alias sends it to (today's review
    record, the ledger's alias lines), existed already. One ambiguous pending link per such study, its candidates
    those earlier studies (followed through merges). The first study of a label waits on nothing."""
    studies = reader.entities("study")                      # not merged, in the order they were created
    homes = {e.id: home_file(e) for e in studies}
    out = []
    for i, study in enumerate(studies):
        home = homes[study.id]
        if home is None:
            continue
        written = label_key(study.label)
        keys = {written, *review_targets("study", written, None, review or {})}
        aliased = {found.id for alias in aliases if alias.type == "study" and alias.key == study.key
                   and (found := reader.entity(alias.entity)) is not None}
        candidates = sorted(other.id for other in studies[:i]
                            if homes[other.id] not in (None, home) and (label_key(other.label) in keys or other.id in aliased))
        if candidates:
            out.append(PendingLink(id=_pending_id(home, study.id), link_fact=None, study=study.id, file_sha256=home,
                                   values=_count(reader, study.id), candidates=tuple(candidates), state="ambiguous"))
    return out


def latest_confirmations(reader: LedgerReader, confirmations: Sequence[LinkConfirmation]
                         ) -> dict[tuple[str, str], LinkConfirmation]:
    """The latest confirmation of each (study, file), the study followed through merges."""
    out: dict[tuple[str, str], LinkConfirmation] = {}
    for confirmation in confirmations:
        entity = reader.entity(confirmation.study)
        out[(entity.id if entity is not None else confirmation.study, confirmation.file_sha256)] = confirmation
    return out


def link_settled(value: ValueState, latest: Mapping[tuple[str, str], LinkConfirmation]) -> bool:
    """Whether a value may be used as part of its study (condition 4): it is not a cross-file value, a person joined it
    (an assignment, or a merge a person made), or the latest confirmation of its (study, file) link is confirmed."""
    cross = value.cross_file
    if cross is None or cross.link_fact.startswith(_BY_A_PERSON):
        return True
    decided = latest.get((cross.receiving_study, value.file_sha256 or ""))
    return decided is not None and decided.confirmed


def confirmed_merges(reader: LedgerReader, confirmations: Sequence[LinkConfirmation], *,
                     review: Mapping[str, Any] | None = None, aliases: Sequence[Alias] = ()) -> list[Merge]:
    """An ambiguous link a person settled (a `LinkConfirmation` of one of its candidates and the file, confirmed): the
    merge of the file's study into the study chosen (not written: `Ledger.link_files` writes it)."""
    latest = latest_confirmations(reader, confirmations)
    out = []
    for link in [*_ambiguous(reader, review=review, aliases=aliases), *explicit_links(reader)[1]]:
        if link.study is None:
            continue
        chosen = [c for c in link.candidates if (lc := latest.get((c, link.file_sha256))) is not None and lc.confirmed]
        if len(chosen) == 1:
            lc = latest[(chosen[0], link.file_sha256)]
            out.append(Merge(type="study", from_id=link.study, into_id=chosen[0], link_fact=link.link_fact,
                             why=f"link confirmed ({lc.id}): {lc.why or 'the same study'}", by=lc.by, at=now()))
    return out


def pending_links(reader: LedgerReader, confirmations: Sequence[LinkConfirmation], *,
                  review: Mapping[str, Any] | None = None, aliases: Sequence[Alias] = ()) -> list[PendingLink]:
    """The links a reviewer has to settle, or has refused:
    - `unconfirmed`: values joined to a study of another file through a link (a link fact or a merge code made), per
      (receiving study, file), while no `LinkConfirmation` of that (study, file) is confirmed; `values` counts the
      active ones. One confirmation covers every later value of that file through the link;
    - `refused`: the latest confirmation of that (study, file) refused it (the fold excludes those values);
    - `ambiguous`: a label or an explicit link that names two or more studies of other files; nothing joined. A
      candidate the person confirmed is merged by `link_files`; one the person refused is no longer a candidate.
    A value a person assigned, or joined by a person's merge, is confirmed by that decision. `review` (today's review
    record) and `aliases` (the ledger's alias lines) give the alias candidates of an ambiguous label, as `resolve`
    saw them."""
    latest = latest_confirmations(reader, confirmations)
    out: list[PendingLink] = []
    groups: dict[tuple[str, str], list[ValueState]] = {}
    for value in reader.values(active=False):
        if value.cross_file is None or value.file_sha256 is None or value.status == "superseded":
            continue
        groups.setdefault((value.cross_file.receiving_study, value.file_sha256), []).append(value)
    for (study, file), members in groups.items():
        decided = latest.get((study, file))
        if decided is not None and decided.confirmed:
            continue
        by_code = [v for v in members if not v.cross_file.link_fact.startswith(_BY_A_PERSON)]
        if decided is None:
            waiting = [v for v in by_code if v.status in _ACTIVE]
            if not waiting:
                continue
            state, count, link = "unconfirmed", len(waiting), waiting[0].cross_file.link_fact
        else:
            state, count = "refused", len(by_code)
            link = by_code[0].cross_file.link_fact if by_code else members[0].cross_file.link_fact
            if not by_code:
                continue
        out.append(PendingLink(id=_pending_id(file, study), link_fact=link if link.startswith("f-") else None,
                               study=study, file_sha256=file, values=count, candidates=(study,), state=state))
    for link in [*_ambiguous(reader, review=review, aliases=aliases), *explicit_links(reader)[1]]:
        decided = [latest.get((c, link.file_sha256)) for c in link.candidates]
        if any(d is not None and d.confirmed for d in decided):
            continue                                        # settled: link_files merges it
        open_candidates = tuple(c for c, d in zip(link.candidates, decided, strict=True) if d is None)
        if open_candidates:
            out.append(link.model_copy(update={"candidates": open_candidates}))
        else:
            out.append(link.model_copy(update={"state": "refused"}))
    return out
