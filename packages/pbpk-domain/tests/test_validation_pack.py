from __future__ import annotations

import pytest

from pbpk_domain.report.validation_pack import (
    Requirement,
    build_pack,
    parse_junit_summary,
    render_validation_pack,
)

REQS = (
    Requirement(id="T-06", title="Authentication and authorization",
                user_requirement="Only authorised project members may act, and signatures require step-up auth.",
                functional_spec="Keycloak OIDC; realm roles + project membership; loa2 step-up for signatures.",
                category="regulatory", risk="high"),
    Requirement(id="T-23", title="Reproducibility gate",
                user_requirement="A submitted model package must reproduce identically.",
                functional_spec="Hashed bundle + rerun_all.R; re-run compared within 1e-6.",
                category="regulatory", risk="high"),
    Requirement(id="F-999", title="Uncovered requirement",
                user_requirement="A requirement with no test yet.",
                functional_spec="Not implemented.", risk="low"),
)

TRACE = {
    "T-06": ["services/api/tests/test_auth.py::test_valid_step_up_signature_is_created"],
    "T-23": ["packages/pbpk-domain/tests/test_reproducibility.py::test_generate_rerun_script_covers_every_snapshot",
             "packages/pbpk-domain/tests/test_reproducibility.py::test_tampered_file_fails_integrity_with_a_diff"],
    # F-999 intentionally absent -> a gap
}

JUNIT = """<?xml version="1.0"?>
<testsuites>
  <testsuite name="pytest" tests="10" failures="1" errors="0" skipped="2" time="1.0"/>
</testsuites>
"""


def test_build_pack_traces_and_finds_gaps():
    pack = build_pack(REQS, TRACE)
    by_id = {c.requirement.id: c for c in pack.coverage}
    assert by_id["T-06"].covered and len(by_id["T-06"].tests) == 1
    assert len(by_id["T-23"].tests) == 2  # sorted, deduped
    assert not by_id["F-999"].covered
    assert pack.gaps() == (REQS[2],)
    assert pack.fully_traced is False


def test_fully_traced_when_no_gaps():
    pack = build_pack(REQS[:2], {"T-06": ["a::t"], "T-23": ["b::t"]})
    assert pack.fully_traced is True
    assert pack.gaps() == ()


@pytest.mark.req("T-32")
def test_parse_junit_summary_reads_totals():
    oq = parse_junit_summary(JUNIT)
    assert oq.total == 10 and oq.failed == 1 and oq.skipped == 2
    assert oq.passed == 7  # total - failed - errors - skipped
    assert oq.green is False


def test_parse_junit_summary_single_suite_element():
    xml = '<testsuite name="p" tests="3" failures="0" errors="0" skipped="0"/>'
    oq = parse_junit_summary(xml)
    assert oq.total == 3 and oq.green is True and oq.passed == 3


def test_render_contains_urs_fs_rtm_and_oq():
    pack = build_pack(REQS, TRACE, oq=parse_junit_summary(JUNIT))
    md = render_validation_pack(pack, system_name="Modeler One", version="0.1.0")
    assert "User Requirements Specification" in md
    assert "Functional Specification" in md
    assert "Requirement Trace Matrix" in md
    assert "test_valid_step_up_signature_is_created" in md
    assert "**GAP**" in md  # F-999 shows as a gap in the RTM
    assert "Traceability gaps" in md and "F-999" in md
    assert "7 passed" in md and "FAIL" in md  # OQ summary (1 failure)
    assert "Installation Qualification" in md and "Performance Qualification" in md


def test_render_without_oq_notes_missing_evidence():
    md = render_validation_pack(build_pack(REQS[:2], TRACE))
    assert "No OQ evidence supplied" in md


def _write(tmp_path, name, record):
    import json

    path = tmp_path / name
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


PRODUCTION_RUN = {"engine_kind": "pksim", "deployment": "production", "status": "COMPLETED", "package": True,
                  "report_issues": 0, "reproduction": True, "broken": 0, "elapsed_seconds": 540,
                  "stages": [{"stage": "S0", "status": "PASSED"}, {"stage": "S1", "status": "ESCALATED"}]}


@pytest.mark.req("T-32")
def test_pq_passes_only_on_a_production_pksim_run_that_reproduces_within_the_hour():
    from pbpk_domain.report.validation_pack import pq_checks

    assert {c["result"] for c in pq_checks(PRODUCTION_RUN)} == {"pass"}            # an escalated stage is recorded, not judged
    pilot = {c["id"]: c for c in pq_checks({**PRODUCTION_RUN, "deployment": "pilot"})}
    assert pilot["PQ-02"]["result"] == "fail" and "not Part 11" in pilot["PQ-02"]["note"]
    old = {c["id"]: c["result"] for c in pq_checks({**PRODUCTION_RUN, "deployment": None})}
    assert old["PQ-02"] == "not_checked"                                            # a campaign that predates the record
    slow = {c["id"]: c["result"] for c in pq_checks({**PRODUCTION_RUN, "elapsed_seconds": 3700, "engine_kind": "stub",
                                                     "broken": 2, "reproduction": False})}
    assert slow["PQ-07"] == slow["PQ-01"] == slow["PQ-04"] == slow["PQ-06"] == "fail"
    unbuilt = {c["id"]: c["result"] for c in pq_checks({**PRODUCTION_RUN, "package": False, "report_issues": None})}
    assert unbuilt["PQ-03"] == unbuilt["PQ-05"] == unbuilt["PQ-06"] == "fail"


@pytest.mark.req("T-32")
def test_iq_and_pq_render_with_their_verdicts_and_never_as_a_pass_when_missing(tmp_path):
    from pbpk_domain.report.validation_pack import load_qualification, pq_checks

    missing = render_validation_pack(build_pack(REQS[:2], TRACE))
    assert "Helm" not in missing and "qualify.sh iq" in missing and "pq.json" in missing
    iq = load_qualification(_write(tmp_path, "iq.json", {"schema": "iq/1", "recorded_at": "2026-10-22T10:00:00+00:00",
        "subject": "adt-server", "checks": [
            {"id": "IQ-01", "item": "Deployed from main", "expected": "main", "found": "main @ abc", "result": "pass"},
            {"id": "IQ-06", "item": "PostgreSQL", "expected": "16", "found": "not installed", "result": "not_checked",
             "note": "pilot | files"}]}))
    pq = load_qualification(_write(tmp_path, "pq.json", {"schema": "pq/1", "recorded_at": "2026-10-22T11:00:00+00:00",
        "subject": "T-56 campaign c1", "checks": pq_checks({**PRODUCTION_RUN, "deployment": "pilot"})}))
    assert (iq.kind, iq.verdict, pq.kind, pq.verdict) == ("IQ", "INCOMPLETE", "PQ", "FAIL")
    md = render_validation_pack(build_pack(REQS[:2], TRACE, iq=iq, pq=pq))
    assert "IQ verdict: **INCOMPLETE**" in md and "PQ verdict: **FAIL**" in md
    assert "| IQ-06 | PostgreSQL | 16 | not installed (pilot \\| files) | not checked |" in md
    assert "| PQ-02 |" in md and "**FAIL**" in md
    with pytest.raises(ValueError, match="not an IQ or PQ record"):
        load_qualification(_write(tmp_path, "x.json", {"schema": "other"}))
