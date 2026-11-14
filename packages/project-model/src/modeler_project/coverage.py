"""The coverage audit of a client file (plan G2, contracts §6.4): "no silent loss" as a number.

A region of a file is `mapped`, `excluded` (by a rule of `coverage.excluded_by_rule` in the rules file, a `not_data`
mapping, or a person's `RegionDecision`, each with its reason) or `unread`. The count is one sentence, shared with the
mapper (§6.2): every cell of a mapped table region that holds a number (`has_number`; a merged copy is not counted, its
origin is) is used or excluded by a stated rule, else it is silent loss. So

    silent_loss = the unaccounted cells of mapped table regions
                + every cell with a number of an unread `table` or `table_like_text` region (`Region.numeric_cells`).

Unread prose is listed, not counted. A file's coverage also lists its content outside every region by page or sheet
and its unresolved anchors; `outside_numeric` counts the outside items with a number that are neither page furniture,
nor cited by a mapped region's constant (`RegionOutcome.cited`), nor accepted as not data by a `RegionDecision` of scope
`outside`. `values_unassigned` (the active values of the file with no study and no product that are not a compound's,
a value that names a batch alone included: `ledger_view.is_unassigned`) is given by the caller from the ledger, as
`values_unassigned` counts them.

No grid is needed: `outcome_from` turns the mapper's in-memory `ExtractResult` into the compact `RegionOutcome` the
pipeline stores, and `file_coverage` counts from the outcomes and `Region.numeric_cells` alone. The coverage file
(`coverage/<sha>.json`) is the current truth: it is recomputed from the stored outcomes, every decision and the source
cache whenever a person excludes regions or assigns values (§6.6).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from modeler_intake.anchors import AnchorError, parse_locator
from modeler_intake.mapping_spec import ExtractResult
from modeler_intake.source_model import AnchorProblem, OutsideItem, Region, SourceDocument
from modeler_project.intake_records import (
    CoverageSummary,
    FileCoverage,
    FileRecord,
    RegionCoverage,
    RegionDecision,
    RegionOutcome,
)
from modeler_project.intake_rules import IntakeRules
from modeler_project.intake_rules import rules as load_rules
from modeler_project.ledger_models import MappingUse
from modeler_project.ledger_view import LedgerReader, is_spread_fact, is_unassigned

MAX_LOCATORS = 200                                 # a RegionOutcome and a RegionCoverage name at most this many cells
_STATES = ("mapped", "excluded", "unread")
_ORIGINS = ("cache", "rule", "llm", "person")
# The kinds of region whose cells with a number are counted: a table, and an unruled table located in text
_COUNTED = ("table", "table_like_text")
# CellUse.use values that set a cell aside by a stated rule (a row rule, an ignored column with its reason, a missing
# token); every other use but "unaccounted" puts the cell to use. A cell set aside with no rule named is unaccounted.
_SET_ASIDE = ("excluded", "missing")
# The kinds of region a person's RegionDecision of each scope may exclude: `regions` any region, `unread_prose` only
# prose, `figures` only figures (a table's numbers never leave silent loss through a prose or figure decision)
_SCOPE_KINDS: dict[str, tuple[str, ...] | None] = {"regions": None, "unread_prose": ("prose",), "figures": ("figure",)}


def outcome_from(region: Region, result: ExtractResult | None, *, state: str, reason: str = "",
                 mapping: MappingUse | None = None, origin: str | None = None) -> RegionOutcome:
    """The compact outcome of one region that the pipeline stores: what was done with it and, for a mapped table,
    how many of its cells with a number went to each use (from `result.cell_use`: a merged copy is never numeric, so
    each cell counts once), the unaccounted ones by locator (at most 200) with their true count, the context lines its
    constants cited and the decimal convention. An excluded or unread region keeps `Region.numeric_cells`.

    A cell set aside (`excluded`, `missing`) with no rule named is not "excluded by a stated rule": it is unaccounted.
    `numeric_cells` is never below `Region.numeric_cells`, so cells the result leaves out of `cell_use` stay counted
    (and silent, `_region_coverage`) instead of vanishing from the count.

    A mapped table region needs its `ExtractResult`; an excluded region needs its reason (a `not_data` mapping's, a
    rule's): either missing is a misuse (ValueError), never a content problem."""
    if state not in _STATES:
        raise ValueError(f"a region's state is one of {_STATES}, not {state!r}")
    if origin is not None and origin not in _ORIGINS:
        raise ValueError(f"a mapping's origin is one of {_ORIGINS}, not {origin!r}")
    if state == "excluded" and not reason.strip():
        raise ValueError(f"region {region.id}: an excluded region needs its reason")
    if state == "mapped" and result is None and region.kind in _COUNTED:
        raise ValueError(f"region {region.id}: a mapped table needs its extraction result to be counted")
    if result is None:
        return RegionOutcome(region_id=region.id, state=state, reason=reason, mapping=mapping, origin=origin,  # type: ignore[arg-type]
                             numeric_cells=region.numeric_cells)
    uses: dict[str, int] = {}
    unaccounted: list[str] = []
    numeric = 0
    for cell in result.cell_use:
        if not cell.numeric:
            continue
        numeric += 1
        use = "unaccounted" if cell.use in _SET_ASIDE and not cell.rule.strip() else cell.use
        uses[use] = uses.get(use, 0) + 1
        if use == "unaccounted":
            unaccounted.append(cell.locator)
    return RegionOutcome(region_id=region.id, state=state, reason=reason, mapping=mapping, origin=origin,  # type: ignore[arg-type]
                         numeric_cells=max(numeric, region.numeric_cells), uses=dict(sorted(uses.items())),
                         unaccounted=tuple(unaccounted[:MAX_LOCATORS]), unaccounted_count=len(unaccounted),
                         cited=tuple(dict.fromkeys(result.cited)), decimal=result.decimal)


def file_coverage(file: FileRecord, doc: SourceDocument, outcomes: Sequence[RegionOutcome],
                  decisions: Sequence[RegionDecision] = (), anchor_problems: Sequence[AnchorProblem] = (), *,
                  values_unassigned: int = 0, rules: IntakeRules | None = None) -> FileCoverage:
    """The coverage of one file: every region with what was done with it and its counts, the content outside every
    region, the unresolved anchors and the summary. Mapped regions are counted from their outcomes alone; unread
    regions from `Region.numeric_cells`; the document is needed only for its regions and outside items (no grid).

    For each region, in order: a person's `RegionDecision` of this file that lists it excludes it with its reason,
    whatever its outcome, when the decision's scope covers the region's kind (scope `regions` any region,
    `unread_prose` a prose region, `figures` a figure: a decision of another scope that lists a table is not applied
    to it); else its outcome; else, with no outcome or an unread one, a rule of `coverage.excluded_by_rule` for its kind
    (a figure) excludes it with the rule's reason; else it is unread. A decision of scope `outside` accepts the outside items it lists as not data. A decision names regions by
    id, and a region's id does not depend on the parser version (§4.2), so a decision made under an earlier version
    still applies to the same region after a re-parse. The source document must be the file's (else ValueError)."""
    rules = rules or load_rules()
    if values_unassigned < 0:
        raise ValueError("values_unassigned is a count")
    if doc.file_sha256 != file.sha256:
        raise ValueError(f"the source document is of file {doc.file_sha256[:12]}, not of {file.sha256[:12]}")
    mine = [d for d in decisions if d.file_sha256 == file.sha256]
    by_region = {o.region_id: o for o in outcomes}
    kinds = {region.id: region.kind for region in doc.regions}
    excluded_by: dict[str, RegionDecision] = {}
    for decision in mine:                                   # in log order: the latest decision naming a region wins
        if decision.scope not in _SCOPE_KINDS:
            continue
        allowed = _SCOPE_KINDS[decision.scope]
        for region_id in decision.regions:
            if allowed is None or kinds.get(region_id) in allowed:
                excluded_by[region_id] = decision
    applied: list[str] = []
    regions: list[RegionCoverage] = []
    for region in doc.regions:
        outcome = by_region.get(region.id)
        decision = excluded_by.get(region.id)
        if decision is not None:
            applied.append(decision.id)
            base = outcome or RegionOutcome(region_id=region.id, state="excluded", numeric_cells=region.numeric_cells)
            outcome = base.model_copy(update={"state": "excluded", "reason": f"{decision.id}: {decision.why}"})
        elif outcome is None or outcome.state == "unread":
            rule = rules.coverage.excluded_by_rule.get(region.kind)
            if rule is not None:
                outcome = RegionOutcome(region_id=region.id, state="excluded",
                                        reason=f"coverage.excluded_by_rule.{region.kind}: {rule}",
                                        numeric_cells=region.numeric_cells)
            elif outcome is None:
                outcome = RegionOutcome(region_id=region.id, state="unread",
                                        reason="no mapping or reading was recorded for this region",
                                        numeric_cells=region.numeric_cells)
        regions.append(_region_coverage(region, outcome))

    cited = _Places(c for r in regions if r.outcome.state == "mapped" for c in r.outcome.cited)
    accepted = _Places(())
    for decision in mine:
        if decision.scope == "outside":
            places = _Places(decision.regions)
            if any(item.where in places for item in doc.outside):
                applied.append(decision.id)
            accepted = accepted | places
    outside_numeric = sum(1 for item in doc.outside if _counts(item, cited, accepted))

    mapped = [r for r in regions if r.outcome.state == "mapped" and r.region.kind in _COUNTED]
    unread_counted = [r for r in regions if r.outcome.state == "unread" and r.region.kind in _COUNTED]
    cells_silent = sum(r.silent_count for r in mapped)
    summary = CoverageSummary(
        state=doc.state, reason=doc.reason, regions=len(regions),
        regions_mapped=sum(1 for r in regions if r.outcome.state == "mapped"),
        regions_excluded=sum(1 for r in regions if r.outcome.state == "excluded"),
        regions_unread=sum(1 for r in regions if r.outcome.state == "unread"),
        numeric_cells=sum(r.numeric_cells for r in mapped), cells_used=sum(r.used for r in mapped),
        cells_excluded=sum(r.excluded for r in mapped), cells_silent=cells_silent,
        silent_loss=cells_silent + sum(r.silent_count for r in unread_counted),
        outside_items=len(doc.outside), outside_numeric=outside_numeric, values_unassigned=values_unassigned,
        needs_ocr_pages=tuple(p.number for p in doc.pages if p.needs_ocr), anchors_unresolved=len(anchor_problems))
    return FileCoverage(file=file, summary=summary, regions=tuple(regions), outside=doc.outside,
                        anchor_problems=tuple(anchor_problems), decisions=tuple(dict.fromkeys(applied)),
                        computed_at=_now())


def silent_loss(coverages: Iterable[CoverageSummary]) -> int:
    """The silent loss of several files (a subject's deliveries): the sum of theirs."""
    return sum(c.silent_loss for c in coverages)


def values_unassigned(reader: LedgerReader, file_sha256: str) -> int:
    """What a caller gives `file_coverage` as `values_unassigned`: the file's active values that belong to no subject
    (`ledger_view.is_unassigned`: no study and no product, and not a compound field; a batch alone is no subject). A
    product's dissolution and a compound's logP have their own subject; a derived spread fact is never a value of its
    own."""
    return sum(1 for v in reader.values(file_sha256=file_sha256)
               if is_unassigned(v.entity, v.field) and not is_spread_fact(v))


# --- counting --------------------------------------------------------------------------------------------------------


def _region_coverage(region: Region, outcome: RegionOutcome) -> RegionCoverage:
    """A region's counts. A mapped table: its cells with a number (never fewer than `Region.numeric_cells`), those put
    to use, those set aside by a stated rule and the unaccounted rest (silent); a cell the outcome does not account
    for at all is silent too, so an outcome that undercounts its region (a `cell_use` that leaves cells out, a stored
    outcome with too small a count) can never hide a loss. An unread table: every cell with a number is silent.
    Anything else (an excluded region, prose, a figure): nothing is silent."""
    if region.kind not in _COUNTED:
        return RegionCoverage(region=region, outcome=outcome, numeric_cells=outcome.numeric_cells, used=0, excluded=0,
                              silent=(), silent_count=0)
    numeric = max(outcome.numeric_cells, region.numeric_cells)
    if outcome.state == "excluded":
        return RegionCoverage(region=region, outcome=outcome, numeric_cells=numeric, used=0, excluded=numeric,
                              silent=(), silent_count=0)
    if outcome.state == "unread":
        return RegionCoverage(region=region, outcome=outcome, numeric_cells=numeric, used=0, excluded=0, silent=(),
                              silent_count=numeric)
    set_aside = sum(n for use, n in outcome.uses.items() if use in _SET_ASIDE)
    used = sum(n for use, n in outcome.uses.items() if use not in _SET_ASIDE and use != "unaccounted")
    silent = max(outcome.unaccounted_count, outcome.uses.get("unaccounted", 0), numeric - used - set_aside)
    return RegionCoverage(region=region, outcome=outcome, numeric_cells=numeric, used=used,
                          excluded=set_aside, silent=outcome.unaccounted[:MAX_LOCATORS], silent_count=silent)


def _counts(item: OutsideItem, cited: _Places, accepted: _Places) -> bool:
    """Whether an outside item counts in `outside_numeric`: it holds a number, is not page furniture, is not a line a
    mapped region's constant cited, and no person accepted it as not data."""
    if not item.numeric or item.furniture:
        return False
    return item.where not in cited and item.where not in accepted


_SHEET_RANGE = re.compile(r"^s:'((?:[^']|'')+)'!([A-Z]{1,3})([1-9][0-9]*):([A-Z]{1,3})([1-9][0-9]*)$")


class _Places:
    """A set of places named by locator texts: a locator is the same place as another when `anchors.same_place` says
    so (every part but a PDF box); a sheet range (a context line written as one range) holds the cells inside it."""

    def __init__(self, texts: Iterable[str]):
        self.keys: set[tuple] = set()
        self.ranges: list[tuple[str, int, int, int, int]] = []
        for text in texts:
            match = _SHEET_RANGE.match(text)
            if match is None:
                self.keys.add(_place_key(text))
                continue
            sheet, c0, r0, c1, r1 = match.groups()
            self.ranges.append((sheet.replace("''", "'"), int(r0), _column(c0), int(r1), _column(c1)))

    def __or__(self, other: _Places) -> _Places:
        both = _Places(())
        both.keys, both.ranges = self.keys | other.keys, [*self.ranges, *other.ranges]
        return both

    def __contains__(self, text: object) -> bool:
        if not isinstance(text, str):
            return False
        key = _place_key(text)
        if key in self.keys:
            return True
        if key[:2] != ("place", "sheet_cell") or not self.ranges:
            return False
        parts = dict(key[2:])
        cell = re.fullmatch(r"([A-Z]{1,3})([1-9][0-9]*)", parts["cell"])
        if cell is None:
            return False
        row, column = int(cell.group(2)), _column(cell.group(1))
        return any(parts["sheet"] == sheet and min(r0, r1) <= row <= max(r0, r1) and min(c0, c1) <= column <= max(c0, c1)
                   for sheet, r0, c0, r1, c1 in self.ranges)


def _column(letters: str) -> int:
    number = 0
    for letter in letters:
        number = number * 26 + ord(letter) - ord("A") + 1
    return number


def _place_key(text: str) -> tuple:
    """A locator's identity (§4.1: the box of a PDF span is never compared), or the text itself when it is not a
    single locator."""
    try:
        locator = parse_locator(text)
    except AnchorError:
        return ("text", text)
    # equal exactly when anchors.same_place holds: every part of the locator but its box
    return ("place", locator.kind, *sorted(locator.model_dump(exclude={"box", "kind"}).items()))


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
