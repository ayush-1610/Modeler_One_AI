"""D3: the mapping cache (contracts §5, §6.2, §8.5; plan §7.4): versions by layout, a person's approval or rejection,
lookup preferring the approved version, the model's typed text never stored, the chain and one audit event per
decision. Software test data (the made-up Exampleamide)."""

from __future__ import annotations

import json
import threading

import pytest

from modeler_intake import synthetic
from modeler_intake.anchors import AnchorError, sha256_of
from modeler_intake.mapping.execute import execute
from modeler_intake.mapping.fingerprint import layout_fingerprint
from modeler_intake.mapping.rules import map_by_rule
from modeler_intake.mapping.validate import validate_spec
from modeler_intake.mapping_spec import Cite, ColumnMap, Constant, MappingSpec
from modeler_intake.source import parse_document, region_grid
from modeler_intake.source_model import Region, RegionGrid
from modeler_project.intake_fixtures import write_truth
from modeler_project.intake_store import IntakeStore
from modeler_project.ledger_view import LedgerView
from modeler_project.mapping_cache import MappingCache, mapping_id_of
from modeler_project.store import FileProjectStore
from modeler_project.workspace import Workspace

pytestmark = pytest.mark.req("T-47", "T-05", "F-404")

FP = "f" * 64
SHA = "a" * 64
REGION = "rg-0123456789"
SPEC = MappingSpec(kind="pk_summary", layout="wide_series", header_rows=1, first_data_row=2, field="concentration",
                   time_unit="h", time_unit_cite=Cite(row=1, column=1),
                   columns=(ColumnMap(column=1, role="time"), ColumnMap(column=2, role="value")),
                   constants=(Constant(field="study_id", cite=Cite(near="caption", line=1), pattern=r"Study (\S+),",
                                       text="230-23"),
                              Constant(field="food_state", cite=Cite(near="caption", line=1), text="fasted")))
OTHER = SPEC.model_copy(update={"statistic": "arithmetic_mean"})
THIRD = SPEC.model_copy(update={"statistic": "median"})


@pytest.fixture
def ws(tmp_path) -> Workspace:
    return Workspace(FileProjectStore(tmp_path), "t1", "p1")


def _propose(cache: MappingCache, spec: MappingSpec = SPEC, fingerprint: str = FP, origin: str = "rule"):
    return cache.propose(fingerprint, spec, origin=origin, origin_detail="sheet_form/rules-1", first_seen=(SHA, REGION),
                         by="code")


def _events(ws: Workspace) -> list:
    return [r.event for r in ws.store.audit("t1").records() if r.event.action.startswith("intake.mapping.")]


def test_propose_approve_reject_and_versions(ws):
    cache = MappingCache(ws)
    first = _propose(cache)
    assert (first.mapping_id, first.version, first.fingerprint, first.origin) == (mapping_id_of(FP), 1, FP, "rule")
    assert first.mapping_id == "mp-ffffffffffff" and first.first_seen == (SHA, REGION)
    assert _propose(cache) == first                                      # the same spec: that version, nothing appended
    second = _propose(cache, OTHER, origin="llm")
    assert _propose(cache) == first                                      # the first spec again, after another: still v1
    third = _propose(cache, THIRD)                                       # a spec no version holds: a version
    assert [(e.version, e.origin) for e in cache.entries()] == [(1, "rule"), (2, "llm"), (3, "rule")]
    assert (second.version, third.version) == (2, 3)
    assert cache.get(first.mapping_id) == third and cache.get(first.mapping_id, 2) == second
    assert cache.get(first.mapping_id, 4) is None and cache.get("mp-000000000000") is None
    assert [cache.status(first.mapping_id, v) for v in (1, 2, 3, 4)] == ["proposed", "proposed", "proposed", None]

    approved = cache.approve(first.mapping_id, 1, by="u-reviewer", note="checked on the Fasting sheet")
    assert (approved.status, approved.why, approved.by) == ("approved", "checked on the Fasting sheet", "u-reviewer")
    rejected = cache.reject(first.mapping_id, 3, by="u-reviewer", why="reads the SD column as values")
    assert rejected.status == "rejected"
    assert cache.approved() == {(first.mapping_id, 1)}
    assert [cache.status(first.mapping_id, v) for v in (1, 2, 3)] == ["approved", "proposed", "rejected"]
    # a later decision on a version stands: the approval withdrawn
    cache.reject(first.mapping_id, 1, by="u-reviewer", why="the unit cite was wrong")
    assert cache.approved() == set() and cache.status(first.mapping_id, 1) == "rejected"
    with pytest.raises(ValueError, match="says why"):
        cache.reject(first.mapping_id, 2, by="u-reviewer", why=" ")
    with pytest.raises(KeyError):
        cache.approve(first.mapping_id, 9, by="u-reviewer")
    with pytest.raises(AnchorError):
        cache.approve("mp-../../x", 1, by="u-reviewer")


def test_a_stored_spec_has_no_constant_text(ws):
    cache = MappingCache(ws)
    entry = _propose(cache)
    assert [c.text for c in entry.spec.constants] == [None, None]
    assert [c.pattern for c in entry.spec.constants] == [r"Study (\S+),", None]       # the pattern is how code reads it
    (line,) = IntakeStore(ws).mappings.entries("entry")
    assert line.body["spec"]["schema"] == "mapping/2"
    assert [c["text"] for c in line.body["spec"]["constants"]] == [None, None]
    raw = IntakeStore(ws).mappings.path.read_text()
    assert "230-23" not in raw and "fasted" not in raw
    # the text the model typed makes no other version: it is not part of what is stored
    assert _propose(cache, SPEC.model_copy(update={"constants": tuple(c.model_copy(update={"text": "x"})
                                                                      for c in SPEC.constants)})) == entry


def test_lookup_prefers_the_approved_version(ws):
    cache = MappingCache(ws)
    assert cache.lookup(FP) is None
    first = _propose(cache)
    assert cache.lookup(FP) == (first, "proposed")
    second = _propose(cache, OTHER)
    assert cache.lookup(FP) == (second, "proposed")                      # the latest version not rejected
    cache.approve(first.mapping_id, 1, by="u-reviewer")
    assert cache.lookup(FP) == (first, "approved")                       # an approved version wins over a later proposal
    cache.reject(first.mapping_id, 2, by="u-reviewer", why="not this layout")
    assert cache.lookup(FP) == (first, "approved")
    cache.reject(first.mapping_id, 1, by="u-reviewer", why="withdrawn")
    assert cache.lookup(FP) is None                                      # every version rejected: the region falls through
    assert cache.lookup("e" * 64) is None
    with pytest.raises(AnchorError):
        cache.lookup("not a fingerprint")


def test_the_same_spec_proposed_by_two_threads_is_stored_once(ws):
    barrier = threading.Barrier(4)
    got: list = []

    def propose() -> None:
        cache = MappingCache(ws)
        barrier.wait()
        got.append(_propose(cache))

    threads = [threading.Thread(target=propose) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(IntakeStore(ws).mappings.entries("entry")) == 1
    assert {(e.mapping_id, e.version) for e in got} == {(mapping_id_of(FP), 1)} and len(got) == 4


def test_the_chain_verifies_and_an_edited_line_is_found(ws):
    cache = MappingCache(ws)
    entry = _propose(cache)
    cache.approve(entry.mapping_id, 1, by="u-reviewer")
    log = IntakeStore(ws).mappings
    assert log.verify() == []
    lines = log.path.read_text().splitlines()
    edited = json.loads(lines[1])
    edited["body"]["status"] = "rejected"                                 # an approval quietly turned around
    log.path.write_text("\n".join([lines[0], json.dumps(edited)]) + "\n")
    assert [(p.seq, p.problem) for p in log.verify()] == [(2, "hash")]


def test_one_audit_event_per_decision_carries_the_specs_hash(ws):
    cache = MappingCache(ws)
    entry = _propose(cache)
    _propose(cache, OTHER)
    assert _events(ws) == []                                              # a proposal is no decision: no event
    cache.approve(entry.mapping_id, 1, by="u-reviewer", note="checked")
    cache.approve(entry.mapping_id, 1, by="u-reviewer", note="checked again")     # already approved: nothing new
    cache.reject(entry.mapping_id, 2, by="u-lead", why="the SD column read as values")
    events = _events(ws)
    assert [(e.action, e.actor, e.reason) for e in events] == [
        ("intake.mapping.approve", "u-reviewer", "checked"), ("intake.mapping.reject", "u-lead", "the SD column read as values")]
    decisions = IntakeStore(ws).mappings.entries("decision")
    assert len(decisions) == 2
    for event, line, version in zip(events, decisions, (1, 2), strict=True):
        assert event.resource_type == "intake" and event.resource_id == f"p1/{entry.mapping_id}/{version}"
        assert event.after == {"mapping_id": entry.mapping_id, "version": version,
                               "spec_sha256": sha256_of(cache.get(entry.mapping_id, version).spec), "row_hash": line.hash}


def test_an_approval_raises_the_values_read_under_that_version_and_a_rejection_lowers_them(ws):
    """The ledger's fold reads the cache's decisions: values read under a version are `new_mapping` until a person
    approves it, `approved_mapping` after, and `new_mapping` again when the approval is withdrawn."""
    write_truth(ws, [synthetic.word_report()], approved=False)
    cache = MappingCache(ws)
    (entry,) = cache.entries()

    def levels() -> set[str]:
        return {v.level for v in LedgerView(ws).values() if v.mapping is not None and v.mapping.mapping_id == entry.mapping_id}

    assert levels() == {"new_mapping"} and cache.lookup(entry.fingerprint) == (entry, "proposed")
    cache.approve(entry.mapping_id, entry.version, by="u-reviewer")
    assert levels() == {"approved_mapping"} and cache.approved() == {(entry.mapping_id, entry.version)}
    cache.reject(entry.mapping_id, entry.version, by="u-reviewer", why="the SD column was read as the mean")
    assert levels() == {"new_mapping"} and cache.lookup(entry.fingerprint) is None


def test_a_cached_spec_is_found_by_layout_and_reads_each_sheets_own_title(ws):
    """The Fasting sheet's approved spec maps the Fed sheet (another title, other subjects): the same fingerprint, and
    validate_spec re-reads the study and dose from the Fed sheet's own caption."""
    messy = synthetic.messy_workbook()
    fasting, fed = (synthetic.truth_grid(messy, t) for t in ("fasting-individual", "fed-individual"))
    spec = next(t.spec for t in messy.tables if t.id == "fasting-individual")
    cache = MappingCache(ws)
    entry = cache.propose(layout_fingerprint(fasting), spec, origin="person", origin_detail="u-reviewer",
                          first_seen=(sha256_of("messy"), fasting.region_id), by="u-reviewer")
    cache.approve(entry.mapping_id, entry.version, by="u-reviewer")
    hit, status = cache.lookup(layout_fingerprint(fed))
    assert (hit, status) == (entry, "approved")
    assert [f for f in validate_spec(hit.spec, fed) if f.severity == "error"] == []
    constants = {c.field: c.value for c in execute(hit.spec, fed).constants}
    assert (constants["study_id"], constants["dose"], constants["food_state"]) == ("231-24", 100.0, "fed")


def test_a_store_without_a_file_root_has_an_empty_cache():
    class NoRoot:
        root = None

    cache = MappingCache(Workspace(NoRoot(), "t1", "p1"))                # type: ignore[arg-type]
    assert cache.lookup(FP) is None and cache.entries() == [] and cache.approved() == set()
    with pytest.raises(RuntimeError, match="no file root"):
        _propose(cache)


def test_a_spec_a_person_rejected_comes_back_rejected_never_as_a_fresh_proposal(ws):
    """The rules make the same spec again on every run: `propose` returns the rejected version, appending nothing, and
    the caller (W) reads its status and goes on to the LLM; a rejection is never undone by a re-proposal."""
    cache = MappingCache(ws)
    first = _propose(cache)
    cache.reject(first.mapping_id, 1, by="u1", why="wrong columns")
    assert cache.lookup(FP) is None
    again = _propose(cache)
    assert (again.version, cache.status(again.mapping_id, again.version)) == (1, "rejected")
    other = _propose(cache, OTHER, origin="llm")                         # another spec: a new version
    assert (other.version, cache.status(other.mapping_id, 2)) == (2, "proposed")
    back = _propose(cache)                                               # the rejected spec after another: still v1
    assert (back.version, cache.status(back.mapping_id, back.version)) == (1, "rejected")
    assert [e.version for e in cache.entries()] == [1, 2] and cache.lookup(FP)[0].version == 2


# --- one layout, several tables: the cache generalises a rule mapping (seam finding SEAM-2) ---------------------------------


def test_the_same_spec_as_any_stored_version_is_that_version_again(ws):
    """Two tables of one layout that need two specs take turns on every run: `propose` answers with the version that
    already holds the spec, whichever it is (not only the latest), so a re-run appends nothing."""
    cache = MappingCache(ws)
    first, second = _propose(cache), _propose(cache, OTHER, origin="llm")
    for _run in range(3):
        assert (_propose(cache), _propose(cache, OTHER, origin="llm")) == (first, second)
    assert [e.version for e in cache.entries()] == [1, 2] and len(IntakeStore(ws).mappings.entries()) == 2
    cache.approve(first.mapping_id, 1, by="u-reviewer")                  # a decision changes nothing of this
    assert _propose(cache) == first and [e.version for e in cache.entries()] == [1, 2]


def test_candidates_are_the_approved_versions_newest_first_then_the_proposed_never_a_rejected_one(ws):
    cache = MappingCache(ws)
    assert cache.candidates(FP) == []
    specs = [SPEC, OTHER, THIRD, SPEC.model_copy(update={"statistic": "geometric_mean"}),
             SPEC.model_copy(update={"statistic": "individual"})]
    one, two, three, four, five = (_propose(cache, spec) for spec in specs)
    assert cache.candidates(FP) == [(five, "proposed"), (four, "proposed"), (three, "proposed"), (two, "proposed"),
                                    (one, "proposed")]
    cache.approve(one.mapping_id, 1, by="u-reviewer")
    cache.approve(one.mapping_id, 3, by="u-reviewer")
    cache.reject(one.mapping_id, 4, by="u-reviewer", why="reads the SD column as values")
    assert cache.candidates(FP) == [(three, "approved"), (one, "approved"), (five, "proposed"), (two, "proposed")]
    assert cache.lookup(FP) == cache.candidates(FP)[0]                   # lookup keeps its meaning: the first candidate
    cache.reject(one.mapping_id, 3, by="u-reviewer", why="withdrawn")    # the latest decision of a version stands
    assert cache.candidates(FP) == [(one, "approved"), (five, "proposed"), (two, "proposed")]
    assert cache.candidates("e" * 64) == []
    with pytest.raises(AnchorError):
        cache.candidates("not a fingerprint")


def _mapped_as_the_pipeline_maps(cache: MappingCache, file, wheres: tuple[str, ...]) -> list:
    """§6.2's mapping order with no model, for the file's table regions at `wheres` (D2's parse): the cache's
    candidates, each validated on the region's own grid, the first that passes; else the rules, proposed. Per region:
    (how it was mapped, the entry, what it reads)."""
    doc = parse_document(file.data, file.name)
    by_where = {r.where: r for r in doc.regions if r.kind == "table"}
    out = []
    for where in wheres:
        region = by_where[where]
        grid = region_grid(doc, region.id)
        fingerprint = layout_fingerprint(grid)
        hit = next(((entry, status) for entry, status in cache.candidates(fingerprint)
                    if not [f for f in validate_spec(entry.spec, grid) if f.severity == "error"]), None)
        if hit is None:
            mapped = map_by_rule(grid, region, filename=file.name, drug=synthetic.DRUG, document_role=doc.role)
            entry = cache.propose(fingerprint, mapped.spec, origin="rule", origin_detail=mapped.rule,
                                  first_seen=(doc.file_sha256, region.id), by="code")
            hit = (entry, "rule")
        out.append((hit[1], hit[0], execute(hit[0].spec, grid)))
    return out


def test_two_sheets_of_one_layout_share_one_version_and_a_second_run_appends_nothing(ws):
    """The Fasting and the Fed sheet of the delivery's workbook: one layout, one mapping id. By rule both get the same
    spec, so ONE version; a second run writes nothing; after a person's approval both read through the approved
    version, each with its own study, dose and food state."""
    messy = next(f for f in synthetic.delivery() if f.name == synthetic.messy_workbook().name)
    wheres = ("s:'Fasting'!A2:G14", "s:'Fed'!A2:G14")
    cache = MappingCache(ws)

    def stated(result) -> tuple:
        constants = {c.field: c.value for c in result.constants}
        return constants["study_id"], constants["dose"], constants["food_state"], len(result.rows)

    first = _mapped_as_the_pipeline_maps(cache, messy, wheres)
    assert [(how, entry.mapping_id, entry.version) for how, entry, _r in first] == [
        ("rule", first[0][1].mapping_id, 1), ("proposed", first[0][1].mapping_id, 1)]
    assert [stated(result) for _h, _e, result in first] == [("230-23", 50.0, "fasted", 36), ("231-24", 100.0, "fed", 36)]
    lines = len(IntakeStore(ws).mappings.entries())
    assert lines == 1
    again = _mapped_as_the_pipeline_maps(cache, messy, wheres)
    assert [(how, entry.version) for how, entry, _r in again] == [("proposed", 1), ("proposed", 1)]
    assert len(IntakeStore(ws).mappings.entries()) == lines             # the second run appended nothing
    entry = first[0][1]
    cache.approve(entry.mapping_id, entry.version, by="u-reviewer")
    approved = _mapped_as_the_pipeline_maps(cache, messy, wheres)
    assert [(how, e.version) for how, e, _r in approved] == [("approved", 1), ("approved", 1)]
    assert [stated(result) for _h, _e, result in approved] == [("230-23", 50.0, "fasted", 36), ("231-24", 100.0, "fed", 36)]
    assert [e.version for e in cache.entries()] == [1] and len(IntakeStore(ws).mappings.entries()) == lines + 1


def test_an_approved_version_is_not_shadowed_by_a_later_one_of_the_same_layout(ws):
    """Two tables of one layout whose specs differ (one title states a dose, the other a food state): each has its own
    approved version. `lookup` answers with the later one only; `candidates` offers both, so each table finds the
    version that reads on its own grid and neither is mapped by rule again."""
    body = [["Time (h)", "Conc (ng/mL)"], [0.5, 2.5], [1, 3.5]]
    dosed = RegionGrid.from_rows(body, caption=["Study 230-77: Exampleamide plasma concentrations after 50 mg"])
    fed = RegionGrid.from_rows(body, caption=["Study 230-78 (fed): Exampleamide plasma concentrations"])
    fingerprint = layout_fingerprint(dosed)
    assert fingerprint == layout_fingerprint(fed)
    region = Region(id=dosed.region_id, kind="table", where="s:'T'!A2:B4", table_kind="pk_summary")
    cache = MappingCache(ws)
    for grid in (dosed, fed):
        mapped = map_by_rule(grid, region, filename="listing.xlsx", drug=synthetic.DRUG)
        entry = cache.propose(fingerprint, mapped.spec, origin="rule", origin_detail=mapped.rule, first_seen=(SHA, REGION),
                              by="code")
        cache.approve(entry.mapping_id, entry.version, by="u-reviewer")
    assert [e.version for e in cache.entries()] == [1, 2] and cache.lookup(fingerprint)[0].version == 2

    def passing(grid: RegionGrid) -> list[tuple[int, str]]:
        return [(entry.version, status) for entry, status in cache.candidates(fingerprint)
                if not [f for f in validate_spec(entry.spec, grid) if f.severity == "error"]]

    assert passing(dosed) == [(1, "approved")] and passing(fed) == [(2, "approved")]
    constants = {c.field: c.value for c in execute(cache.get(entry.mapping_id, 1).spec, dosed).constants}
    assert (constants["study_id"], constants["dose"]) == ("230-77", 50.0)
