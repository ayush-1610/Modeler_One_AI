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
