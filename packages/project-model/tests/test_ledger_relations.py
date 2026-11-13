"""Relation facts (contracts §6.3, §8.6): a DDI ratio row with its 90 % CI (interval low, high and level) and the other
arm becomes one relation fact linking the two arms of its study; a test-against-reference row likewise. Relations are
facts, never extract values, and have no landing shape (§11.33)."""

from __future__ import annotations

import pytest

from modeler_intake import synthetic
from modeler_intake.anchors import parse_anchor
from modeler_intake.mapping_spec import ExtractedConstant, ExtractedRow, ExtractResult, MappingSpec
from modeler_project.ledger import Ledger
from modeler_project.workspace import Workspace

from .test_ledger_support import grid_from_rows, make_ws, mapping_entry, region_of, sheet_context

pytestmark = pytest.mark.req("T-47", "T-05", "F-404")

A = "a" * 64
CAPTION = f"Study DDI-1: {synthetic.DRUG} with and without Inhibitamide (made up), geometric mean ratios (90% CI)"


@pytest.fixture
def ws(tmp_path) -> Workspace:
    return make_ws(tmp_path)


def _ddi(ledger: Ledger, *, kind: str = "ddi_relation", field: str = "relation.ddi_ratio.{p}") -> tuple:
    rows = [["Parameter", "Test", "Reference", "Ratio", "90% CI low", "90% CI high"],
            ["AUC_inf", f"{synthetic.DRUG} + Inhibitamide", f"{synthetic.DRUG} alone", 2.41, 1.98, 2.93],
            ["Cmax", f"{synthetic.DRUG} + Inhibitamide", f"{synthetic.DRUG} alone", 1.52, 1.31, 1.77]]
    grid = grid_from_rows(rows, sha=A, sheet="DDI", caption=(CAPTION,))
    caption = grid.caption[0]
    extracted = []
    for r in (2, 3):
        parameter = grid.cell(r, 1).text
        extracted.append(ExtractedRow(
            field=field.format(p=parameter), labels={"arm": grid.cell(r, 2).text, "other_arm": grid.cell(r, 3).text},
            label_locators={"arm": grid.cell(r, 2).locator, "other_arm": grid.cell(r, 3).locator,
                            "parameter": grid.cell(r, 1).locator},
            value=float(grid.cell(r, 4).value), verbatim=grid.cell(r, 4).text, locator=grid.cell(r, 4).locator,
            statistic="geometric_mean", interval=(float(grid.cell(r, 5).value), float(grid.cell(r, 6).value)),
            interval_kind="CI", interval_level=90.0, interval_locators=(grid.cell(r, 5).locator, grid.cell(r, 6).locator)))
    result = ExtractResult(rows=tuple(extracted), cell_use=(), findings=(), constants=(
        ExtractedConstant(field="study_id", value="DDI-1", verbatim=CAPTION, locator=caption.locator),
        ExtractedConstant(field="analyte", value=synthetic.DRUG, verbatim=CAPTION, locator=caption.locator)))
    spec = MappingSpec(kind=kind, layout="long", header_rows=1, first_data_row=2)
    recorded = ledger.record_extraction(region=region_of(grid, kind), grid=grid, mapping=mapping_entry(spec), result=result,
                                        context=sheet_context(A))
    return grid, recorded


def test_a_ddi_ratio_row_with_its_ci_and_the_other_arm_becomes_a_relation_fact_linking_two_arms(ws):
    ledger = Ledger(ws)
    _grid, recorded = _ddi(ledger)
    assert recorded.extract is None                                # a relation is a fact, never an extract value
    relations = sorted((ledger.value(f) for f in recorded.facts if ledger.value(f).relation is not None),
                       key=lambda v: v.relation.parameter)
    assert [r.relation.parameter for r in relations] == ["AUC_inf", "Cmax"]
    auc = relations[0]
    assert (auc.field, auc.value, auc.interval, auc.interval_kind, auc.interval_level, auc.statistic) == (
        "relation.ddi_ratio.AUC_inf", 2.41, (1.98, 2.93), "CI", 90.0, "geometric_mean")
    assert auc.relation.kind == "ddi_ratio" and auc.method == "cell" and auc.status == "proposed"
    study = ledger.entity(auc.entity.study)
    test, reference = ledger.entity(auc.entity.arm), ledger.entity(auc.relation.other.arm)
    assert study.label == "DDI-1" and test.parent == reference.parent == study.id
    assert (test.label, reference.label) == (f"{synthetic.DRUG} + Inhibitamide", f"{synthetic.DRUG} alone")
    assert auc.relation.other.study == study.id
    assert relations[1].entity.arm == test.id and relations[1].relation.other.arm == reference.id   # one arm each
    assert auc.entity.analyte is not None and ledger.entity(auc.entity.analyte).label == synthetic.DRUG
    # every cell it is read with: the ratio, the CI's low and high, the two arms, the parameter, the study
    assert parse_anchor(auc.anchor).locator.cell == "D3"
    assert {role: parse_anchor(a).locator.cell for role, a in auc.locators.items()} == {
        "interval_low": "E3", "interval_high": "F3", "arm": "B3", "other_arm": "C3", "parameter": "A3",
        "study": "A1", "analyte": "A1"}
    # recording it again adds nothing; the two arms are two entities of the one study
    heads = (ledger.store.facts.head(), ledger.store.entities.head())
    _ddi(ledger)
    assert (ledger.store.facts.head(), ledger.store.entities.head()) == heads
    assert sorted(e.label for e in ledger.entities("arm")) == [f"{synthetic.DRUG} + Inhibitamide", f"{synthetic.DRUG} alone"]
    assert ledger.conflicts() == []


def test_a_test_against_reference_row_is_a_relation_by_its_table_kind(ws):
    ledger = Ledger(ws)
    _grid, recorded = _ddi(ledger, kind="pk_parameters", field="pk.{p}")
    relations = [ledger.value(f) for f in recorded.facts if ledger.value(f).relation is not None]
    assert {(r.relation.kind, r.relation.parameter, r.field) for r in relations} == {
        ("test_vs_reference", "AUC_inf", "pk.AUC_inf"), ("test_vs_reference", "Cmax", "pk.Cmax")}
    assert all(r.interval is not None and r.relation.other.arm != r.entity.arm for r in relations)
