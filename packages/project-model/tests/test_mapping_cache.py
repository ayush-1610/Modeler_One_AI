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
from modeler_intake.mapping.validate import validate_spec
from modeler_intake.mapping_spec import Cite, ColumnMap, Constant, MappingSpec
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
    third = _propose(cache)                                              # the first spec again, after another: a version
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
