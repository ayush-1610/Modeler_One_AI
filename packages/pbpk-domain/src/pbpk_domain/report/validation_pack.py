"""Validation pack generator (task T-32): URS/FS, requirement trace matrix and OQ evidence.

GAMP 5 / 21 CFR Part 11 computer-system validation asks for a documented line from each user requirement
to a functional specification to the tests that verify it and the evidence those tests passed. This module
assembles that pack from artifacts the platform already produces: requirements declared here (keyed by the
same ids used in ``@pytest.mark.req``), the trace matrix emitted by the ``req`` plugin (task T-25), and the
JUnit results of the test run (Operational Qualification evidence from CI). IQ and PQ are stubbed until the
deployment (T-29) and staging-run infrastructure exist.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

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
) -> ValidationPack:
    """Cross the declared requirements with the trace matrix (req id -> test node ids) into a validation pack."""
    coverage = tuple(
        RequirementCoverage(requirement=req, tests=tuple(sorted(trace_matrix.get(req.id, []))))
        for req in requirements
    )
    return ValidationPack(requirements=requirements, coverage=coverage, oq=oq)


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

    out += ["", "## 6 Installation Qualification (IQ)", "",
            "_Pending deployment automation (T-29): IQ evidence is generated from the Helm/k3s release state._",
            "", "## 7 Performance Qualification (PQ)", "",
            "_Pending staging campaign runs (T-29): PQ evidence is generated from a full campaign on staging._", ""]
    return "\n".join(out).rstrip() + "\n"
