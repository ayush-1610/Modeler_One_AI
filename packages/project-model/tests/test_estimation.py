"""R4b (redesign §3.3, D-34): the bounds proposed for a fitted parameter follow MS-01 §2.2's "Default bounds", copied as a
provisional data rule (`fit_bounds.yaml`); the validator's findings on a fit's bounds."""

from __future__ import annotations

from pathlib import Path

import pytest

from modeler_project.estimation import fit_findings, proposed_bounds, rule
from pbpk_domain.cpf.models import ParameterRecord, ParameterStatus

pytestmark = pytest.mark.req("T-50")
MS01 = Path(__file__).resolve().parents[3] / "docs" / "PBPK_MODELING_WORKFLOW.md"


def _record(pid: str, value: float, unit: str | None = None, *, predicted: bool = False) -> ParameterRecord:
    return ParameterRecord(id=pid, value=value, unit=unit, status=ParameterStatus.PREDICTED if predicted else ParameterStatus.FIXED)


def _cells(line: str) -> list[str]:
    """A markdown table row's cells: a `|` inside backticks, or escaped, is text."""
    cells, cell, code, i = [], "", False, 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and line[i + 1:i + 2] == "|":
            cell, i = cell + "|", i + 2
            continue
        if ch == "`":
            code = not code
        if ch == "|" and not code:
            cells.append(cell.strip())
            cell = ""
        else:
            cell += ch
        i += 1
    return cells[1:]


def _ms01_default_bounds() -> dict[str, str]:
    """MS-01 §2.2: the first id of each row → its "Default bounds" cell."""
    text = MS01.read_text(encoding="utf-8")
    section = text[text.index("### 2.2 Canonical parameters"):text.index("### 2.3")]
    out = {}
    for line in section.splitlines():
        if not line.startswith("| `"):
            continue
        cells = _cells(line)
        out[cells[0].split("`")[1]] = cells[5]
    return out


def test_the_rule_is_ms01_s_default_bounds_word_for_word_and_covers_every_row_that_has_one():
    table = _ms01_default_bounds()
    assert rule().status == "UNVERIFIED" and rule().source.startswith("MS-01 v1.3 §2.2")
    for row in rule().bounds:
        assert table[row.row or row.id] == row.ms01, row.id
    with_bounds = {k for k, v in table.items() if v != "–" and not k.startswith("pd.")}   # PD: out of MS-01 v1.0's scope
    assert with_bounds == {row.row or row.id for row in rule().bounds}


def test_each_kind_of_ms01_default_around_the_start_value():
    fu = proposed_bounds(_record("bind.fu", 0.12))
    assert fu.fixed and fu.lower is None and "keeps a measured bind.fu fixed" in fu.note
    assert (p := proposed_bounds(_record("bind.fu", 0.12, predicted=True))).lower == 0.06 and p.upper == 0.24 and p.scale == "log"
    assert (p := proposed_bounds(_record("phys.logp", 2.3, "Log Units"))).lower == pytest.approx(0.8) and p.scale == "linear"
    assert (p := proposed_bounds(_record("phys.logp", 2.3, "Log Units", predicted=True))).lower == -2 and p.upper == 7
    assert (p := proposed_bounds(_record("perm.intestinal", 1e-4, "cm/min"))).lower == 1e-7 and p.upper == 1e-2
    assert (p := proposed_bounds(_record("elim.hepatic.CYP3A4.clspec", 0.5, "l/µmol/min"))).upper == 100
    assert proposed_bounds(_record("elim.hepatic.total.plasma_clearance", 5.0, "ml/min/kg")).upper == 30   # via the alias
    assert (p := proposed_bounds(_record("elim.renal.gfr_fraction", 1.0))).basis == "MS-01 §2.2: [0, 3]" and p.scale == "linear"
    assert (p := proposed_bounds(_record("phys.solubility.ref", 0.05, "mg/ml"))).lower == 0.05 and p.upper == 5.0


def test_bounds_in_another_unit_are_never_applied_and_a_parameter_ms01_leaves_open_gets_0_1_to_10x():
    clspec = proposed_bounds(_record("elim.hepatic.CYP3A4.clspec", 0.5, "1/min"))
    assert (clspec.lower, clspec.upper) == (0.05, 5.0) and "MS-01's default is in l/µmol/min" in clspec.note
    assert not clspec.from_ms01
    bp = proposed_bounds(_record("dist.bp_ratio", 1.2))
    assert (bp.lower, bp.upper, bp.basis) == (0.12, 12.0, "no MS-01 default: [0.1×, 10×] the start value")


def test_a_proposal_stays_within_the_physical_bounds_or_says_why_there_is_none():
    fu = proposed_bounds(_record("bind.fu", 0.8, predicted=True))
    assert (fu.lower, fu.upper) == (0.4, 1.0) and "clipped to the physical bounds [0, 1]" in fu.note
    fu_percent = proposed_bounds(_record("bind.fu", 80.0, "%", predicted=True))   # bounds in another unit: not applied
    assert (fu_percent.lower, fu_percent.upper) == (40.0, 160.0)
    lag = proposed_bounds(_record("form.tab.weibull.lag", 0.0, "min"))
    assert lag.lower is None and "positive start value" in lag.note


def test_the_validator_s_findings_on_a_fit_s_bounds():
    gfr = fit_findings(_record("elim.renal.gfr_fraction", 1.0), 0.1, 12)
    assert [(s, r) for s, r, _ in gfr] == [("error", "fit-plausible"), ("warning", "fit-default")]
    assert fit_findings(_record("bind.fu", 0.12), 0.06, 0.24)[0][:2] == ("warning", "fit-fixed")
    assert fit_findings(_record("bind.fu", 0.12, predicted=True), 0.06, 0.24) == []         # MS-01's own default
    assert fit_findings(_record("bind.fu", 0.12, predicted=True), 0.08, 0.2) == []          # narrower: allowed
    assert fit_findings(_record("dist.bp_ratio", 1.2), 0.01, 15) == []                      # no MS-01 default to widen
    assert fit_findings(_record("phys.logp", -1.56, "Log Units"), -3.06, -0.06) == []        # its own default, negative values
