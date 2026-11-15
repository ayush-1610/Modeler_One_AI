"""A person's link that a re-read of its table keeps (plan 2026-11-14 §5, "Final review fixes: linking"; review OWN-1).

An assignment (`intake_records.Assignment`, a line of review.jsonl) gives values their study or product by their ids:
a fact id, an extract id (every value of that table) or a value id "<extract>#<i>". A table read again so that a value
reads differently (a person corrects its layout and approves the version, a re-parse moves a value) is written as a NEW
extract that supersedes the earlier one, with new value ids; a fact read with another content is a new fact that
supersedes the earlier one (`ledger` module docstring). The assignment then names no active value, and the person's
link was lost without a word: the values were back on the "study not stated" list.

`carry` (the pipeline's ledger stage, after its recordings) carries the link over. An item recorded now (an extract, a
fact) has as predecessors the earlier items of the same table: an extract of the same file with the same region id,
or one its `supersedes` lines join to it (either way: a re-parse may give one table another region id); the facts a
fact supersedes. The latest assignment in force on a predecessor (the last assignment line that names it or one of its
values), when it is later than every assignment that names the item itself, is
- carried when it covered the whole predecessor (each of its values but those a person set aside one by one): ONE
  `assignment` line for that assignment, naming every item it is carried to, with its study, arm, product, batch and
  analyte, by "code", its why "carried over from as-n after a re-read: <the person's why>"; one `intake.assign`
  event (actor "code") with the line's hash and `carried_from`;
- not carried when it covered only part of the table (the rest had a study of its own, or was linked elsewhere): which
  part it would cover now cannot be told, so the link waits for a person, and `waiting` gives the page what it was
  (where the values went, who linked them and why), so the link row comes back pre-filled with it and says why.
Nothing is carried into an item whose own reading names a study or a product (the file now says where its values go),
and a predecessor a person set aside (marked as not data) carries nothing. A carried link is the person's link, as it
was: no arm check is run on it again (`intake_review.assign` checks a person's new link).

`file_links` says which links are in force on a file's values (what each covers there), so the page can offer to link
them elsewhere: a link is changed by linking again (review INT-5).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from modeler_project.intake_records import Assignment
from modeler_project.intake_store import ChainEntry, IntakeStore
from modeler_project.ledger_entities import now
from modeler_project.ledger_models import ExtractRef, Fact, StatusChange, ValueState

CARRIED = "carried over from {} after a re-read"


@dataclass(frozen=True)
class Waiting:
    """A link a re-read did not carry over: `items` (extract or fact ids, active now) were read from the table that
    `assignment` linked, in part (`whole` false), or whole before links were carried over."""

    items: tuple[str, ...]
    assignment: Assignment
    whole: bool


class _Logs:
    """The facts log's extracts, facts and status lines, and the review log's assignments, each read once."""

    def __init__(self, store: IntakeStore, facts: list[ChainEntry] | None = None):
        self.extracts: dict[str, ExtractRef] = {}
        self.facts: dict[str, Fact] = {}
        self.status: dict[str, StatusChange] = {}               # target -> its last status line
        for line in store.facts.entries() if facts is None else facts:
            if line.kind == "extract":
                ref = ExtractRef.model_validate(line.body)
                self.extracts[ref.id] = ref
            elif line.kind == "fact":
                fact = Fact.model_validate(line.body)
                self.facts[fact.id] = fact
            elif line.kind == "status":
                change = StatusChange.model_validate(line.body)
                self.status[change.target] = change
        self.assignments = [Assignment.model_validate(e.body) for e in store.review.entries("assignment")]
        # value id -> (the index of the last assignment naming it or its extract, that assignment)
        self.in_force: dict[str, tuple[int, Assignment]] = {}
        for index, assignment in enumerate(self.assignments):
            for target in assignment.targets:
                ref = self.extracts.get(target)
                for value in ([f"{target}#{i}" for i in range(ref.n)] if ref is not None else [target]):
                    self.in_force[value] = (index, assignment)

    def values(self, item: str) -> list[str]:
        ref = self.extracts.get(item)
        return [f"{item}#{i}" for i in range(ref.n)] if ref is not None else [item]

    def excluded_by_person(self, item: str) -> bool:
        change = self.status.get(item)
        return change is not None and change.status == "excluded" and change.by != "code"

    def names_subject(self, item: str) -> bool:
        """Whether the item's own reading names a study or a product (before any assignment)."""
        ref = self.extracts.get(item)
        if ref is not None:
            return bool(ref.studies or ref.products)
        fact = self.facts.get(item)
        return fact is None or bool(fact.entity.study or fact.entity.product)

    def own(self, item: str) -> int:
        """The index of the latest assignment in force on one of the item's values (-1: none)."""
        return max((self.in_force[v][0] for v in self.values(item) if v in self.in_force), default=-1)

    def predecessors(self, item: str) -> list[str]:
        """The earlier items of the same table: the extracts of its file with its region id or joined to it by the
        supersedes lines (either way), or the facts it supersedes, one after the other."""
        ref = self.extracts.get(item)
        if ref is None:
            out, seen = [], {item}
            fact = self.facts.get(item)
            while fact is not None and fact.supersedes and fact.supersedes not in seen and fact.supersedes in self.facts:
                seen.add(fact.supersedes)
                out.append(fact.supersedes)
                fact = self.facts[fact.supersedes]
            return out
        of_file = {r.id: r for r in self.extracts.values() if r.file_sha256 == ref.file_sha256}
        joined: dict[str, set[str]] = {i: set() for i in of_file}
        for r in of_file.values():
            for old in r.supersedes:
                if old in joined:
                    joined[r.id].add(old)
                    joined[old].add(r.id)
        found, todo = {item}, [item]
        while todo:
            for other in joined[todo.pop()]:
                if other not in found:
                    found.add(other)
                    todo.append(other)
        found |= {r.id for r in of_file.values() if r.region_id == ref.region_id}
        return sorted(found - {item})

    def latest(self, item: str) -> tuple[int, Assignment, bool] | None:
        """The latest assignment on a predecessor of `item` that is later than any naming `item` itself, and whether it
        covered that predecessor whole; None when there is none."""
        mine = self.own(item)
        best: tuple[int, Assignment, bool] | None = None
        for old in self.predecessors(item):
            if self.excluded_by_person(old):
                continue
            values = [v for v in self.values(old) if v == old or not self.excluded_by_person(v)]
            given = [self.in_force[v] for v in values if v in self.in_force]
            if not given:
                continue
            index, assignment = max(given, key=lambda g: g[0])
            if index <= mine or (best is not None and index <= best[0]):
                continue
            best = (index, assignment, len(given) == len(values) and all(g[0] == index for g in given))
        return best


def carry(store: IntakeStore, items: Iterable[str]) -> list[Assignment]:
    """Carry each person's link over to the items recorded now (the module docstring): one `assignment` line and one
    `intake.assign` event per link carried. The caller refreshes its reader after."""
    logs = _Logs(store)
    carried: dict[int, tuple[Assignment, list[str]]] = {}
    for item in dict.fromkeys(items):
        if item not in logs.extracts and item not in logs.facts:
            continue
        if logs.names_subject(item):
            continue
        found = logs.latest(item)
        if found is None or not found[2]:
            continue
        index, assignment, _whole = found
        carried.setdefault(index, (assignment, []))[1].append(item)
    out: list[Assignment] = []
    for assignment, targets in carried.values():
        why = f"{CARRIED.format(assignment.id)}: {assignment.why}"
        draft = assignment.model_copy(update={"id": "as-0", "targets": tuple(targets), "why": why, "by": "code", "at": now()})
        entry = store.review.append("assignment", lambda seq, d=draft: d.model_copy(update={"id": f"as-{seq}"}).model_dump(mode="json"))
        record = Assignment.model_validate(entry.body)
        store.audit(actor="code", action="intake.assign", resource_id=record.id, reason=why,
                    after={"id": record.id, "row_hash": entry.hash, "carried_from": assignment.id})
        out.append(record)
    return out


def waiting(store: IntakeStore, items: Sequence[str]) -> list[Waiting]:
    """The links a re-read did not carry over to these items (active items with values on the "study not stated" list):
    one per assignment, with the items it covered part of, or the whole of when it was made before links were carried."""
    if not items or not store.review.entries("assignment"):
        return []
    logs = _Logs(store)
    found: dict[int, tuple[Assignment, list[str], bool]] = {}
    for item in dict.fromkeys(items):
        if (item not in logs.extracts and item not in logs.facts) or logs.names_subject(item):
            continue
        latest = logs.latest(item)
        if latest is None:
            continue
        index, assignment, whole = latest
        was = found.get(index)
        found[index] = (assignment, [*(was[1] if was else []), item], whole and (was[2] if was else True))
    return [Waiting(items=tuple(targets), assignment=assignment, whole=whole) for assignment, targets, whole in found.values()]


@dataclass(frozen=True)
class FileLink:
    """A person's link in force on values of one file (a link carried over is the person's link): the assignment, what it
    covers there (an extract id when it covers every active value of that table, else value ids; fact ids) and how many
    values. A link is changed by linking again (an assignment replaces the earlier one whole): these are the targets."""

    assignment: Assignment
    targets: tuple[str, ...]
    values: int


def file_links(store: IntakeStore, values: Sequence[ValueState]) -> dict[str, list[FileLink]]:
    """The links in force on these values (the active ones: `LedgerReader.values()`), by file sha256: for each file, one
    per assignment that is the latest to name one of its values, in the order the assignments were made."""
    assignments = [Assignment.model_validate(e.body) for e in store.review.entries("assignment")]
    if not assignments:
        return {}
    of_item: dict[str, list[ValueState]] = {}
    for value in values:
        if value.file_sha256:
            of_item.setdefault(value.id.split("#")[0], []).append(value)
    in_force: dict[str, int] = {}
    for index, assignment in enumerate(assignments):
        for target in assignment.targets:
            for value in ([target] if "#" in target else [v.id for v in of_item.get(target, [])]):
                in_force[value] = index
    out: dict[str, dict[int, list[str]]] = {}
    counts: dict[tuple[str, int], int] = {}
    for item, members in of_item.items():
        given = [(v, in_force[v.id]) for v in members if v.id in in_force]
        for index in dict.fromkeys(i for _v, i in given):
            mine = [v for v, i in given if i == index]
            sha = mine[0].file_sha256 or ""
            whole = len(mine) == len(members) and "#" in members[0].id
            out.setdefault(sha, {}).setdefault(index, []).extend([item] if whole or "#" not in members[0].id else [v.id for v in mine])
            counts[(sha, index)] = counts.get((sha, index), 0) + len(mine)
    return {sha: [FileLink(assignment=assignments[i], targets=tuple(targets), values=counts[(sha, i)])
                  for i, targets in sorted(by_index.items())] for sha, by_index in out.items()}
