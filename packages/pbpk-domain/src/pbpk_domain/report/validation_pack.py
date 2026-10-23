"""Validation pack generator (task T-32): URS/FS, requirement trace matrix, and IQ / OQ / PQ evidence.

GAMP 5 / 21 CFR Part 11 computer-system validation asks for a documented line from each user requirement
to a functional specification to the tests that verify it and the evidence those tests passed. This module
assembles that pack from artifacts the platform already produces: requirements declared here (keyed by the
same ids used in ``@pytest.mark.req``), the trace matrix emitted by the ``req`` plugin (task T-25), the
JUnit results of the test run (Operational Qualification evidence from CI), the server's installation record
(Installation Qualification: ``deploy/server/qualify.sh iq``) and a proof campaign's trace (Performance
Qualification: ``deploy/proof/run_t56.py trace`` writes ``pq.json``, judged by `pq_checks`). A qualification passes
only when every check passes; one not checked leaves it incomplete, and nothing missing is ever shown as a pass.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Requirement:
    id: str  # matches @pytest.mark.req(...), e.g. "T-06", "F-403"
    title: str
    user_requirement: str  # URS: what the user needs
    functional_spec: str  # FS: how the system meets it
    category: str = "functional"  # functional | regulatory | performance
    risk: str = "medium"  # GAMP risk-based classification: low | medium | high


@dataclass(frozen=True)
class OQResult:
    total: int
    passed: int
    failed: int
    errors: int
    skipped: int

    @property
    def green(self) -> bool:
        return self.failed == 0 and self.errors == 0


@dataclass(frozen=True)
class QualificationCheck:
    id: str
    item: str
    expected: str
    found: str
    result: str  # pass | fail | not_checked | recorded (a fact written down, nothing to compare it with)
    note: str = ""


@dataclass(frozen=True)
class Qualification:
    """An IQ or PQ record: what was checked, on which system or campaign, and when."""

    kind: str  # "IQ" | "PQ"
    recorded_at: str
    subject: str  # IQ: the host and its installation; PQ: the campaign
    checks: tuple[QualificationCheck, ...]

    @property
    def verdict(self) -> str:
        if any(c.result == "fail" for c in self.checks):
            return "FAIL"
        if not self.checks or any(c.result == "not_checked" for c in self.checks):
            return "INCOMPLETE"
        return "PASS"


QUALIFICATION_SCHEMAS = {"iq/1": "IQ", "pq/1": "PQ"}
ONE_HOUR_S = 3600  # the goal: simulations and parameter identification within an hour on our servers (CLAUDE.md)


def load_qualification(path: str | Path) -> Qualification:
    """An IQ or PQ record from its JSON (``iq/1`` from qualify.sh, ``pq/1`` from the T-56 trace)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    kind = QUALIFICATION_SCHEMAS.get(str(data.get("schema")))
    if kind is None:
        raise ValueError(f"{path}: not an IQ or PQ record (schema {data.get('schema')!r})")
    checks = tuple(QualificationCheck(**{k: str(c.get(k, "")) for k in ("id", "item", "expected", "found", "result", "note")})
                   for c in data.get("checks", []))
    return Qualification(kind=kind, recorded_at=str(data.get("recorded_at", "")), subject=str(data.get("subject", "")),
                         checks=checks)


def pq_checks(facts: Mapping[str, Any]) -> list[dict[str, str]]:
    """The PQ criteria judged on a proof campaign's facts (the T-56 trace): real PK-Sim, a production (Part 11) run,
    the package built, every number traced, a MAR without issues, the reproduction passed, and the 1-hour goal. The
    stages' outcomes are recorded, not judged: a model may fail validation while the system performs correctly."""
    def check(id_: str, item: str, expected: str, found: Any, ok: bool | None, note: str = "") -> dict[str, str]:
        result = "not_checked" if ok is None else ("pass" if ok else "fail")
        return {"id": id_, "item": item, "expected": expected, "found": str(found), "result": result, "note": note}

    deployment = facts.get("deployment")
    package = bool(facts.get("package"))
    elapsed = facts.get("elapsed_seconds")
    stages = facts.get("stages") or []
    return [
        check("PQ-01", "Engine", "real PK-Sim", facts.get("engine_kind") or "unknown", facts.get("engine_kind") == "pksim",
              "" if facts.get("engine_kind") == "pksim" else "a software fixture ran it: not PBPK evidence"),
        check("PQ-02", "Deployment the campaign ran under", "production (Keycloak sign-in; every signature Part 11)",
              deployment or "not recorded", None if deployment is None else deployment == "production",
              "the campaign predates the record of its deployment" if deployment is None
              else ("" if deployment == "production" else f"{deployment}: signed with the DEV verifier, not Part 11")),
        check("PQ-03", "Campaign reached its report (S7)", "a package with its MAR", facts.get("status") or "unknown", package),
        check("PQ-04", "Every number traces to its source", "0 broken links", facts.get("broken", "unknown"),
              None if facts.get("broken") is None else facts.get("broken") == 0),
        check("PQ-05", "MAR report issues", "0", facts.get("report_issues", "no MAR") if package else "no MAR",
              package and facts.get("report_issues") == 0),
        check("PQ-06", "Reproduction of the package", "re-run matches within 1e-6",
              "passed" if facts.get("reproduction") else "not passed", package and bool(facts.get("reproduction"))),
        check("PQ-07", "Wall-clock time (simulations and parameter identification)", f"≤ {ONE_HOUR_S // 60} min",
              "unknown" if elapsed is None else f"{float(elapsed) / 60:.0f} min",
              None if elapsed is None or not package else float(elapsed) <= ONE_HOUR_S,
              "" if package else "the campaign did not reach its report: its time to a result is not known"),
        check("PQ-08", "Stage outcomes", "recorded", ", ".join(f"{s.get('stage')} {s.get('status')}" for s in stages) or "none",
              None if not stages else True),
    ]


@dataclass(frozen=True)
class RequirementCoverage:
    requirement: Requirement
    tests: tuple[str, ...]

    @property
    def covered(self) -> bool:
        return len(self.tests) > 0


@dataclass(frozen=True)
class ValidationPack:
    requirements: tuple[Requirement, ...]
    coverage: tuple[RequirementCoverage, ...]
    oq: OQResult | None
    iq: Qualification | None = None
    pq: Qualification | None = None
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def gaps(self) -> tuple[Requirement, ...]:
        return tuple(c.requirement for c in self.coverage if not c.covered)

    @property
    def fully_traced(self) -> bool:
        return not self.gaps()


def load_requirements(path: str | Path) -> tuple[Requirement, ...]:
    """Load the URS/FS catalogue from a YAML file: a list of mappings with the Requirement fields."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []
    return tuple(
        Requirement(
            id=str(item["id"]), title=item["title"],
            user_requirement=item["user_requirement"], functional_spec=item["functional_spec"],
            category=item.get("category", "functional"), risk=item.get("risk", "medium"),
        )
        for item in data
    )


def load_trace_matrix(path: str | Path) -> dict[str, list[str]]:
    """Load the req-id -> test-node-ids map emitted by the trace-matrix plugin (T-25)."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_pack(
    requirements: tuple[Requirement, ...],
    trace_matrix: dict[str, list[str]],
    *,
    oq: OQResult | None = None,
    iq: Qualification | None = None,
    pq: Qualification | None = None,
) -> ValidationPack:
    """Cross the declared requirements with the trace matrix (req id -> test node ids) into a validation pack."""
    coverage = tuple(
        RequirementCoverage(requirement=req, tests=tuple(sorted(trace_matrix.get(req.id, []))))
        for req in requirements
    )
    return ValidationPack(requirements=requirements, coverage=coverage, oq=oq, iq=iq, pq=pq)


def parse_junit_summary(xml_text: str) -> OQResult:
    """Read the OQ totals from a pytest JUnit XML report (the <testsuite> attributes)."""
    root = ET.fromstring(xml_text)
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    total = failed = errors = skipped = 0
    for suite in suites:
        total += int(suite.get("tests", 0))
        failed += int(suite.get("failures", 0))
        errors += int(suite.get("errors", 0))
        skipped += int(suite.get("skipped", 0))
    passed = total - failed - errors - skipped
    return OQResult(total=total, passed=passed, failed=failed, errors=errors, skipped=skipped)


def render_validation_pack(pack: ValidationPack, *, system_name: str = "Modeler One", version: str = "") -> str:
    """Render the pack as Markdown (Pandoc input for the DOCX/PDF deliverable, via report.render)."""
    out: list[str] = [f"# {system_name} — Validation Pack", ""]
    if version:
        out.append(f"**System version:** {version}  ")
    out += [
        f"**Generated:** {pack.generated_at.isoformat()}  ",
        f"**Requirements:** {len(pack.requirements)}  ",
        f"**Fully traced:** {'yes' if pack.fully_traced else 'no — see gaps'}  ",
        "",
        "## 1 User Requirements Specification (URS)", "",
        "| ID | Requirement | Category | Risk |", "| --- | --- | --- | --- |",
    ]
    for r in pack.requirements:
        out.append(f"| {r.id} | {r.user_requirement} | {r.category} | {r.risk} |")

    out += ["", "## 2 Functional Specification (FS)", "", "| ID | Function |", "| --- | --- |"]
    for r in pack.requirements:
        out.append(f"| {r.id} | {r.functional_spec} |")

    out += ["", "## 3 Requirement Trace Matrix (RTM)", "",
            "| ID | Title | Verifying tests | Status |", "| --- | --- | --- | --- |"]
    for c in pack.coverage:
        tests = "<br>".join(f"`{t}`" for t in c.tests) if c.tests else "— none —"
        status = "traced" if c.covered else "**GAP**"
        out.append(f"| {c.requirement.id} | {c.requirement.title} | {tests} | {status} |")

    out += ["", "## 4 Operational Qualification (OQ)", ""]
    if pack.oq is not None:
        oq = pack.oq
        out += [
            (f"CI test run: **{oq.passed} passed**, {oq.failed} failed, {oq.errors} errors, "
             f"{oq.skipped} skipped of {oq.total}."),
            "",
            f"OQ verdict: {'PASS — all executed tests green' if oq.green else 'FAIL — see failures'}.",
        ]
    else:
        out.append("_No OQ evidence supplied (attach the CI JUnit report)._")

    if pack.gaps():
        out += ["", "## 5 Traceability gaps", "",
                "The following requirements have no verifying test and must be covered before release:", ""]
        out += [f"- {r.id} — {r.title}" for r in pack.gaps()]

    out += ["", "## 6 Installation Qualification (IQ)", ""]
    out += _qualification(pack.iq, missing="_Not run: run `bash deploy/server/qualify.sh iq` on the server and attach the "
                                           "JSON it writes._")
    out += ["", "## 7 Performance Qualification (PQ)", "",
            ("PQ passes only on a campaign run on real PK-Sim in production (every signature Part 11), whose package "
             "reproduces, whose every number traces to its source, within the 1-hour goal."), ""]
    out += _qualification(pack.pq, missing="_Not run: `deploy/proof/run_t56.py trace` writes `pq.json` for a proof "
                                           "campaign; attach it._")
    return "\n".join(out).rstrip() + "\n"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _qualification(record: Qualification | None, *, missing: str) -> list[str]:
    if record is None:
        return [missing]
    out = [f"Recorded {record.recorded_at} — {record.subject}.", "", f"{record.kind} verdict: **{record.verdict}**.", "",
           "| ID | Check | Expected | Found | Result |", "| --- | --- | --- | --- | --- |"]
    for c in record.checks:
        result = {"pass": "pass", "fail": "**FAIL**", "not_checked": "not checked", "recorded": "recorded"}.get(c.result, c.result)
        found = _cell(c.found) + (f" ({_cell(c.note)})" if c.note else "")
        out.append(f"| {c.id} | {_cell(c.item)} | {_cell(c.expected)} | {found} | {result} |")
    return out


def main(argv: list[str] | None = None) -> int:
    """Render the pack from files: the requirements, the trace matrix and, when given, the JUnit report and the IQ and
    PQ records."""
    import argparse

    parser = argparse.ArgumentParser(description="Render the validation pack (Markdown).")
    parser.add_argument("--requirements", default="docs/validation/requirements.yaml")
    parser.add_argument("--trace-matrix", required=True, help="the req plugin's JSON (req id -> tests)")
    parser.add_argument("--junit", help="the test run's JUnit XML (OQ)")
    parser.add_argument("--iq", help="deploy/server/qualify.sh iq's JSON")
    parser.add_argument("--pq", help="deploy/proof/run_t56.py trace's pq.json")
    parser.add_argument("--version", default="")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    oq = parse_junit_summary(Path(args.junit).read_text(encoding="utf-8")) if args.junit else None
    pack = build_pack(load_requirements(args.requirements), load_trace_matrix(args.trace_matrix), oq=oq,
                      iq=load_qualification(args.iq) if args.iq else None,
                      pq=load_qualification(args.pq) if args.pq else None)
    Path(args.out).write_text(render_validation_pack(pack, version=args.version), encoding="utf-8")
    print(f"{args.out}: IQ {pack.iq.verdict if pack.iq else 'not run'}, PQ {pack.pq.verdict if pack.pq else 'not run'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
