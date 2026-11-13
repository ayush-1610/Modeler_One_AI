"""T-47, T-21: the scorer (contracts §8.1, §13) finds the truth of the synthetic files at 100 % and names each error.

The ledger tests write the truth with `intake_fixtures.write_truth` (the contract's convention for D0, D5, W and D6)
and score it through `from_ledger` against `key_from_truth`; the errors are made on the values code read, so each is
known. The baseline adapter reads a project built by today's `client_data.ingest`. No PK-Sim, no model, no real key:
the files are the synthetic Exampleamide ones.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from modeler_intake import synthetic
from modeler_project import FileProjectStore, Workspace
from modeler_project.brief import empty_brief
from modeler_project.client_data import ingest
from modeler_project.documents import DocumentLibrary
from modeler_project.intake_fixtures import write_truth
from modeler_project.intake_records import CoverageSummary, FileCoverage, FileRecord, RunRecord, StageTiming
from modeler_project.intake_store import IntakeStore
from modeler_project.ledger_models import EntityRef, Fact, StatusChange
from modeler_project.ledger_view import LedgerView
from modeler_project.reading_queue import ReadingQueue
from modeler_project.value_key import SCHEMA, ValueKey, key_from_truth, load_key, write_key
from modeler_project.value_score import (
    Extracted,
    coverage_totals,
    from_ledger,
    from_stores,
    main,
    masked_anchor,
    public,
    public_coverage,
    render,
    score,
    timings,
)

pytestmark = pytest.mark.req("T-47", "T-21")

HEADER = {"schema": SCHEMA, "delivery": "D-001", "analyst": "Analyst Alpha", "date": "2026-11-13", "status": "verified"}
SHA = "a" * 64
WORKBOOK = f"{SHA}@workbook/1.0+openpyxl3.1.5#s:'Listing'!C4"
CSV = f"{SHA}@delimited/1.0#s:'listing'!C4"
PDF = f"{SHA}@pdfplumber/1.0+pdfplumber0.11.4#p:2/t:1/r:4/c:3@212.40,318.02,251.10,329.50"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@pytest.fixture(scope="module")
def delivery() -> tuple[synthetic.SyntheticFile, ...]:
    return synthetic.delivery()


@pytest.fixture(scope="module")
def truth_key(delivery) -> ValueKey:
    return load_key(key_from_truth(delivery), "truth.xlsx")


@pytest.fixture(scope="module")
def ledger(tmp_path_factory, delivery) -> Workspace:
    """The truth of delivery() in a ledger, read only by the tests that use it."""
    ws = Workspace(FileProjectStore(tmp_path_factory.mktemp("ledger")), "t1", "p1")
    write_truth(ws, delivery)
    return ws


def _ex(**values: Any) -> Extracted:
    """A value code read, for hand-made cases: a workbook cell of listing.xlsx unless told otherwise."""
    base = dict(file="listing.xlsx", study="230-23", arm="", analyte="Exampleamide", matrix="plasma", subject="001",
                field="concentration", time_min=30.0, value="12.1", verbatim="12.1", censored=False, lloq=None,
                unit="ng/mL", method="cell", anchor=WORKBOOK, id="x-1")
    return Extracted(**{**base, **values})


def _row(**values: str) -> dict[str, str]:
    base = {"file": "listing.xlsx", "where": "Listing", "table": "Table 1", "study": "230-23", "analyte": "Exampleamide",
            "matrix": "plasma", "subject": "001", "field": "concentration", "time": "0.5", "time_unit": "h",
            "value": "12.1", "unit": "ng/mL"}
    return {**base, **values}


def _key(rows: list[dict[str, str]], studies: tuple[dict[str, str], ...] = (), not_data: tuple[dict[str, str], ...] = ()
         ) -> ValueKey:
    return load_key(write_key(HEADER, rows, studies, not_data), "key.xlsx")


def _verdicts(scored: dict[str, Any]) -> dict[int, str]:
    return {r["row"]: r["verdict"] for r in scored["rows"]}


def _clean(totals: dict[str, int], n: int) -> bool:
    return totals["found"] == totals["scored"] == totals["key_rows"] == n and not any(
        totals[v] for v in ("found_rounded", "wrong_value", "wrong_unit", "missing", "unexpected", "unusable",
                            "attributes_differ", "labels_differ", "places_unread"))


# --- the truth ---------------------------------------------------------------------------------------------------------


def test_the_truth_of_the_synthetic_files_scores_100_percent(ledger, delivery, truth_key):
    extracted = from_ledger(ledger)
    scored = score(truth_key, extracted)
    totals = scored["totals"]
    assert _clean(totals, sum(len(f.values) for f in delivery)), totals
    # the one value read beyond the truth is the ledger's own cross-file link (the PDF's synopsis names the workbook's
    # study): it joins files, the analysts do not write it, so it is outside the key, not unexpected
    outside = [e for e in extracted if not any(r["found"] and r["found"]["id"] == e.id for r in scored["rows"])]
    assert [e.field for e in outside] == ["link.study_id"] and totals["outside_key"] == 1
    assert scored["by_field"]["concentration"]["found"] == sum(1 for f in delivery for v in f.values
                                                              if v.field == "concentration")
    # the prose facts (a scripted model's) and the PDF and Word tables are scored too
    assert {r["found"]["method"] for r in scored["rows"]} == {"cell", "pdf_table", "docx_table", "prose"}
    # with the statistic, spread, spread kind and n of every mean the truth states, all checked and all equal
    stated = [r for r in scored["rows"] if r["expected"]["attributes"].get("spread")]
    assert len(stated) >= 40 and {"SD", "SE"} <= {r["expected"]["attributes"]["spread_kind"] for r in stated}


def test_the_template_truth_scores_100_percent_on_its_own(tmp_path):
    template = synthetic.template_workbook()
    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    write_truth(ws, [template])
    scored = score(load_key(key_from_truth([template]), "truth.xlsx"), from_ledger(ws))
    assert _clean(scored["totals"], len(template.values)), scored["totals"]
    assert scored["totals"]["outside_key"] == 0


# --- errors, each under its verdict, field and study ----------------------------------------------------------------


def _pick(extracted: list[Extracted], **want: Any) -> int:
    hits = [i for i, e in enumerate(extracted) if all(getattr(e, k) == v for k, v in want.items())]
    assert len(hits) == 1, (want, hits)
    return hits[0]


def _key_row(key: ValueKey, **want: str) -> int:
    hits = [r.row for r in key.rows if all(getattr(r, k) == v for k, v in want.items())]
    assert len(hits) == 1, (want, hits)
    return hits[0]


def test_each_error_is_reported_under_its_verdict_field_and_study(ledger, truth_key):
    extracted = from_ledger(ledger)
    fasting = dict(study="230-23", analyte="Exampleamide", field="concentration")
    fed = dict(study="231-24", field="concentration")
    wrong = _pick(extracted, **fasting, subject="003", time_min=120.0)                  # 22.6
    unit = _pick(extracted, **fed, subject="101", time_min=30.0)                        # 5.2 ng/mL
    first, second = _pick(extracted, **fasting, subject="001", time_min=30.0), _pick(extracted, **fasting, subject="002",
                                                                                       time_min=30.0)
    omitted = _pick(extracted, **fed, subject="102", time_min=60.0)
    extra = _pick(extracted, **fed, subject="103", time_min=30.0)
    changed = list(extracted)
    changed[wrong] = changed[wrong].model_copy(update={"value": "23.6"})
    changed[unit] = changed[unit].model_copy(update={"unit": "µg/mL"})
    changed[first] = extracted[first].model_copy(update={"subject": "002"})            # the two subjects swapped
    changed[second] = extracted[second].model_copy(update={"subject": "001"})
    changed.append(extracted[extra].model_copy(update={"time_min": 5000.0, "id": "extra"}))   # a time the key has not
    del changed[omitted]
    scored = score(truth_key, changed)

    rows = {name: _key_row(truth_key, file="messy-delivery.xlsx", field="concentration", study=study, subject=subject,
                           time=time)
            for name, study, subject, time in (("wrong", "230-23", "003", "2"), ("unit", "231-24", "101", "0.5"),
                                               ("first", "230-23", "001", "0.5"), ("second", "230-23", "002", "0.5"),
                                               ("omitted", "231-24", "102", "1"))}
    verdicts = _verdicts(scored)
    assert {name: verdicts[row] for name, row in rows.items()} == {
        "wrong": "wrong_value", "unit": "wrong_unit", "first": "wrong_value", "second": "wrong_value", "omitted": "missing"}
    totals = scored["totals"]
    assert (totals["wrong_value"], totals["wrong_unit"], totals["missing"], totals["unexpected"]) == (3, 1, 1, 1)
    assert (totals["errors"], totals["omissions"], totals["found"]) == (5, 1, totals["scored"] - 5)
    assert [(u["field"], u["study"], u["id"]) for u in scored["unexpected"]] == [("concentration", "23124", "extra")]
    concentration = scored["by_field"]["concentration"]
    assert (concentration["wrong_value"], concentration["wrong_unit"], concentration["missing"],
            concentration["unexpected"]) == (3, 1, 1, 1)
    assert {k: v for k, v in scored["by_study"]["23023"].items() if v and k != "found"} == {"wrong_value": 3}
    assert {k: v for k, v in scored["by_study"]["23124"].items() if v and k != "found"} == {
        "wrong_unit": 1, "missing": 1, "unexpected": 1}
    row = next(r for r in scored["rows"] if r["row"] == rows["wrong"])
    assert (row["expected"]["value"], row["found"]["value"], row["found"]["method"]) == ("22.6", "23.6", "cell")


def test_blq_above_range_and_missing_tokens():
    rows = [_row(time=str(t), value=v) for t, v in enumerate(
        ("BLQ", "<0.5", "<0.5", "NS", "NS", "BLQ", ">1000", "BLQ", "BLOQ", ">1000", ">1000", "NS", "<0.5"), start=1)]
    extracted = [
        _ex(time_min=60.0, value=None, verbatim="BLQ", censored=True),                     # BLQ: censored
        _ex(time_min=120.0, value=None, verbatim="<0.5", censored=True, lloq="0.5"),       # <0.5: censored at 0.5
        _ex(time_min=180.0, value=None, verbatim="<0.2", censored=True, lloq="0.2"),       # <0.5: another LLOQ
        _ex(time_min=240.0, value=None, verbatim="NS"),                                    # NS: no value
        _ex(time_min=300.0, value="3.2", verbatim="3.2"),                                  # NS: but a value
        _ex(time_min=360.0, value="0.4", verbatim="0.4"),                                  # BLQ: but a value
        _ex(time_min=420.0, value=None, verbatim=">1000", uloq="1000"),                    # above the range at 1000
        _ex(time_min=480.0, value=None, verbatim="NS"),                                    # BLQ: no value, not censored
        _ex(time_min=540.0, value=None, verbatim="<0.5", censored=True, lloq="0.5"),       # BLOQ: any LLOQ
        _ex(time_min=600.0, value=None, verbatim=">1000"),                                 # >1000 written, no uloq read
        _ex(time_min=660.0, value=None, verbatim=">1000", uloq="100"),                     # >1000 read as above 100
        # 12 (720 min): NS, and nothing read: what the key says
        _ex(time_min=780.0, value=None, verbatim="<0.5", censored=True, lloq="0.5", lloq_unit="µg/mL"),  # LLOQ's unit
    ]
    scored = score(_key(rows), extracted)
    assert _verdicts(scored) == {2: "found", 3: "found", 4: "wrong_value", 5: "found", 6: "wrong_value", 7: "wrong_value",
                                 8: "found", 9: "wrong_value", 10: "found", 11: "wrong_value", 12: "wrong_value",
                                 13: "found", 14: "wrong_unit"}
    absent = next(r for r in scored["rows"] if r["row"] == 13)
    assert (absent["how"], absent["found"], scored["totals"]["found_absent"], scored["totals"]["missing"]) == (
        "absent", None, 1, 0)


def test_12_40_equals_12_4_and_rounding_is_for_a_workbook_number_cell_only():
    key = _key([_row(time=str(t), value="12.40") for t in range(1, 6)])
    extracted = [
        _ex(time_min=60.0, value="12.4", method="pdf_table", anchor=PDF),                  # the written decimal: equal
        _ex(time_min=120.0, value="12.4037", method="cell", anchor=WORKBOOK),              # 12.4037 under 0.00 shows 12.40
        _ex(time_min=180.0, value="12.4037", method="pdf_table", anchor=PDF),              # a PDF's text is exact
        _ex(time_min=240.0, value="12.4037", method="cell", anchor=CSV),                   # so is a delimited file's
        _ex(time_min=300.0, value="12.4051", method="cell", anchor=WORKBOOK),              # rounds to 12.41
    ]
    scored = score(key, extracted)
    assert _verdicts(scored) == {2: "found", 3: "found_rounded", 4: "wrong_value", 5: "wrong_value", 6: "wrong_value"}
    rounded = next(r for r in scored["rows"] if r["verdict"] == "found_rounded")
    assert (rounded["how"], rounded["expected"]["value"], rounded["found"]["value"]) == ("rounded", "12.40", "12.4037")
    assert scored["totals"]["found_rounded"] == 1 and scored["totals"]["found"] == 1


def test_a_workbook_mean_stored_as_12_4037_is_found_rounded_against_the_12_40_it_shows(ledger, truth_key):
    rows = [r.model_dump(exclude={"row"}) for r in truth_key.rows]
    target = next(i for i, r in enumerate(rows) if r["value"] == "12.4037")
    rows[target]["value"] = "12.40"
    key = load_key(write_key(HEADER, rows, (), truth_key.not_data), "key.xlsx")
    scored = score(key, from_ledger(ledger))
    assert scored["totals"]["found_rounded"] == 1 and scored["totals"]["found"] == scored["totals"]["scored"] - 1
    assert _verdicts(scored)[key.rows[target].row] == "found_rounded"


def test_a_spreadsheet_tie_rounds_away_from_zero_and_a_text_file_never_rounds():
    key = _key([_row(time="1", value="12.3"), _row(time="2", value="0.13"), _row(time="3", value="12.41"),
                _row(time="4", value="3"), _row(time="5", value="12.40"),
                _row(time="6", value="12.40", file="c.csv", where="c")])
    extracted = [
        _ex(time_min=60.0, value="12.25"),                     # a spreadsheet shows 12.25 under 0.0 as 12.3
        _ex(time_min=120.0, value="0.125"),                    # and 0.125 under 0.00 as 0.13
        _ex(time_min=180.0, value="12.405"),
        _ex(time_min=240.0, value="2.5"),
        _ex(time_min=300.0, value="12.4037", anchor=None),     # today's stores: no anchor, a workbook's file name
        _ex(time_min=360.0, value="12.4037", file="c.csv", anchor=None),    # a delimited file's text stays exact
    ]
    assert _verdicts(score(key, extracted)) == {2: "found_rounded", 3: "found_rounded", 4: "found_rounded",
                                                5: "found_rounded", 6: "found_rounded", 7: "wrong_value"}


def test_a_thousands_separator_is_settled_by_its_table_never_guessed():
    auc = dict(file="report.pdf", where="2", subject="", time="", time_unit="")
    rows = [_row(**auc, field="pk.AUC_last", value="1,523", unit="ng*h/mL"),
            _row(**auc, field="pk.Cmax", value="31.4", unit="ng/mL"),                       # a decimal point: 1,523 is 1523
            _row(**{**auc, "where": "3"}, field="pk.AUC_last", value="1,523", unit="ng*h/mL"),   # alone: ambiguous
            _row(**{**auc, "where": "4"}, field="pk.AUC_inf", value="1 612,5", unit="ng*h/mL")]  # space groups
    pdf = dict(file="report.pdf", subject="", time_min=None, method="pdf_table", anchor=PDF)
    read = [_ex(**pdf, field="pk.AUC_last", value="1523", verbatim="1,523", unit="ng*h/mL", id="a"),
            _ex(**pdf, field="pk.Cmax", value="31.4", unit="ng/mL", id="c"),
            _ex(**pdf, field="pk.AUC_inf", value="1612.5", verbatim="1 612,5", unit="ng*h/mL", id="i")]
    key = _key(rows)
    scored = score(key, read)
    assert _verdicts(scored) == {2: "found", 3: "found", 5: "found"}
    assert [(u["row"], u["reason"].partition(" (")[0]) for u in scored["unusable"]] == [
        (4, "the value's separator is ambiguous")]
    # the 1000-fold misread is a wrong value, never found
    misread = [read[0].model_copy(update={"value": "1.523"}), *read[1:]]
    assert _verdicts(score(key, misread))[2] == "wrong_value"


def test_the_tolerance_applies_only_where_asked():
    key = _key([_row(time="1", value="12.4"), _row(time="2", value="12.4")])
    extracted = [_ex(time_min=60.0, value="12.5"), _ex(time_min=120.0, value="12.5", method="digitized", anchor=None)]
    assert _verdicts(score(key, extracted)) == {2: "wrong_value", 3: "wrong_value"}
    scored = score(key, extracted, tolerance=0.01)
    assert _verdicts(scored) == {2: "found", 3: "wrong_value"} and scored["totals"]["found_by_tolerance"] == 1
    assert _verdicts(score(key, extracted, digitized_tolerance=0.01)) == {2: "wrong_value", 3: "found"}
    assert _verdicts(score(key, extracted, tolerance=0.001, digitized_tolerance=0.001)) == {2: "wrong_value",
                                                                                            3: "wrong_value"}
    for bad in (-0.1, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="relative tolerance"):
            score(key, extracted, tolerance=bad)


def test_units_compare_through_their_table_and_nothing_is_converted():
    key = _key([_row(time="1", unit="ng/mL"), _row(time="2", unit="ng/mL"),
                _row(field="pk.AUC_last", time="", time_unit="", unit="ng*h/mL")])
    extracted = [_ex(time_min=60.0, unit="NG/ML"), _ex(time_min=120.0, unit="µg/L"),
                 _ex(time_min=None, field="pk.AUC_last", unit="ng*h/ml")]
    assert _verdicts(score(key, extracted)) == {2: "found", 3: "wrong_unit", 4: "found"}


def test_rows_the_scorer_cannot_use_are_listed_never_dropped():
    rows = [_row(time="1", value=""), _row(time="2", value="12.3 (4.5)"), _row(time="1:30"), _row(time="3", time_unit=""),
            _row(time="4", time_unit="fortnights"), _row(time="0.5")]
    scored = score(_key(rows), [_ex()])
    assert [(u["row"], u["reason"]) for u in scored["unusable"]] == [
        (2, "the value is empty"), (3, "the value is not a number, a BLQ form, an above-range form or a missing token"),
        (4, "the time is not a number"), (5, "the time has no unit"), (6, "the time unit is not known")]
    totals = scored["totals"]
    assert (totals["key_rows"], totals["unusable"], totals["scored"], totals["found"], totals["missing"]) == (6, 5, 1, 1, 0)


def test_names_of_the_studies_sheet_and_the_arm_folded_into_a_study_id():
    key = _key([_row(time="1"), _row(time="2", study="231-24", arm="Test")],
               studies=({"study": "230-23", "names": "Study 23023; EX-230"},))
    extracted = [_ex(time_min=60.0, study="Study 23023"), _ex(time_min=120.0, study="231-24-TEST", arm="")]
    # the arm folded into the study id is today's stores' (the command sets fold_arm for --source stores only)
    scored = score(key, extracted, fold_arm=True)
    assert _verdicts(scored) == {2: "found", 3: "found"}
    # for the ledger, a value attached to a study "231-24-TEST" with no arm is attached to another study
    scored = score(key, extracted)
    assert _verdicts(scored) == {2: "found", 3: "missing"} and scored["totals"]["unexpected"] == 1
    # an arm the value states must be the key's
    assert _verdicts(score(key, [_ex(time_min=60.0, study="EX-230"), _ex(time_min=120.0, study="231-24", arm="Ref")],
                           fold_arm=True)) == {2: "found", 3: "missing"}


def test_a_value_read_in_one_of_two_files_is_paired_with_that_files_row():
    dose = dict(field="dose", subject="", analyte="", matrix="", time="", time_unit="", unit="mg", value="50")
    key = _key([_row(**dose, file="report.pdf", where="1"), _row(**dose)])          # the PDF's row comes first
    read = _ex(field="dose", subject="", analyte="", matrix="", time_min=None, value="50", unit="mg", id="w")
    scored = score(key, [read])
    assert _verdicts(scored) == {2: "missing", 3: "found"}
    assert scored["by_method"]["cell"]["found"] == 1 and scored["by_method"]["(none)"]["missing"] == 1


def test_subjects_are_codes_a_swap_of_1_01_and_10_1_is_seen():
    key = _key([_row(subject="1-01", value="5.0"), _row(subject="10-1", value="7.0")])
    swapped = [_ex(subject="1-01", value="7.0", id="a"), _ex(subject="10-1", value="5.0", id="b")]
    assert _verdicts(score(key, swapped)) == {2: "wrong_value", 3: "wrong_value"}


def test_the_attributes_a_key_states_are_checked_on_the_paired_value():
    mean = dict(subject="", statistic="arithmetic_mean", spread="1.92", spread_kind="SD", n="5")
    rows = [_row(time=str(t), value="12.4", **mean) for t in range(1, 5)] + [_row(time="5", subject="", value="12.4")]
    m = dict(subject="", value="12.4", statistic="arithmetic_mean", spread="1.92", spread_kind="SD", n="5")
    extracted = [_ex(time_min=60.0, **m),                                             # all agree
                 _ex(time_min=120.0, **{**m, "spread": "0.86", "spread_kind": "SE"}),     # an SE taken for the SD
                 _ex(time_min=180.0, **{**m, "n": "6", "statistic": "geometric_mean"}),
                 _ex(time_min=240.0, **{**m, "spread": "1.9234", "statistic": "Mean"}),   # a stored SD shown 1.92
                 _ex(time_min=300.0, **{**m, "spread": "9.9"})]                       # the key states none: not checked
    scored = score(_key(rows), extracted)
    assert _verdicts(scored) == {2: "found", 3: "found", 4: "found", 5: "found", 6: "found"}
    assert {r["row"]: r["attributes_differ"] for r in scored["rows"]} == {
        2: [], 3: ["spread", "spread_kind"], 4: ["statistic", "n"], 5: [], 6: []}
    assert scored["totals"]["attributes_differ"] == 2 and scored["by_attribute"]["n"] == 1
    assert public(scored)["rows"][1]["attributes_differ"] == ["spread", "spread_kind"]
    report = render(scored)
    assert "## Attributes that differ" in report and "| 3 | concentration | study of key row 2 | found | spread, " \
        "spread_kind |" in report
    # one value twice, told apart by its statistic or occasion only: a swap is seen, and agreeing values pair
    cmax = dict(field="pk.Cmax", subject="", time="", time_unit="")
    key = _key([_row(**cmax, value="31.4", statistic="geometric_mean"), _row(**cmax, value="33.0", statistic="arithmetic_mean")])
    c = dict(field="pk.Cmax", subject="", time_min=None)
    swapped = [_ex(**c, value="33.0", statistic="geometric_mean", id="g"),
               _ex(**c, value="31.4", statistic="arithmetic_mean", id="a")]
    assert {r["row"]: r["attributes_differ"] for r in score(key, swapped)["rows"]} == {2: ["statistic"], 3: ["statistic"]}
    days = _key([_row(time="1", value="5.0", occasion="Day 1"), _row(time="1", value="5.0", occasion="Day 14")])
    read = [_ex(time_min=60.0, value="5.0", occasion="Day 14", id="d14"),
            _ex(time_min=60.0, value="5.0", occasion="Day 1", id="d1")]
    assert {r["row"]: (r["found"]["id"], r["attributes_differ"]) for r in score(days, read)["rows"]} == {
        2: ("d1", []), 3: ("d14", [])}


def test_repeats_pair_as_multisets_never_on_the_anchor():
    dose = dict(field="dose", subject="", analyte="", matrix="", time="", time_unit="", unit="mg")
    caption, prose = _ex(field="dose", subject="", analyte="", matrix="", time_min=None, value="50", unit="mg", id="a"), \
        _ex(field="dose", subject="", analyte="", matrix="", time_min=None, value="50", unit="mg", method="prose",
            anchor=PDF, file="report.pdf", id="b")
    twice = _key([_row(**dose, value="50"), _row(**dose, value="50", file="report.pdf", where="2")])
    assert _verdicts(score(twice, [caption, prose])) == {2: "found", 3: "found"}
    # one of two repeats wrong: the equal one is found, the other is a wrong value, whatever their order
    other = prose.model_copy(update={"value": "60"})
    assert sorted(_verdicts(score(twice, [other, caption])).values()) == ["found", "wrong_value"]
    # a value read twice where the key has it once: the second is unexpected in a place the key covers ...
    once = _key([_row(**dose, value="50")])
    scored = score(once, [caption, caption.model_copy(update={"id": "c"})])
    assert (scored["totals"]["found"], scored["totals"]["unexpected"]) == (1, 1)
    # ... and outside the key in a file it does not cover; a value of the key row's own file is taken first
    scored = score(once, [prose, caption])
    assert scored["rows"][0]["found"]["id"] == "a" and scored["totals"]["unexpected"] == 0
    assert scored["totals"]["outside_key"] == 1


def test_a_token_lloq_restated_as_a_fact_is_not_unexpected():
    key = _key([_row(time="0", value="<0.5"), _row(time="", time_unit="", field="lloq", value="0.5", subject="")])
    token = _ex(time_min=0.0, value=None, verbatim="<0.5", censored=True, lloq="0.5", id="v")
    restated = _ex(time_min=None, subject="", field="lloq", value="0.5", verbatim="<0.5", id="l1")
    footnote = _ex(time_min=None, subject="", field="lloq", value="0.5", verbatim="LLOQ 0.5 ng/mL",
                   anchor=f"{SHA}@workbook/1.0#s:'Listing'!A20", id="l2")
    scored = score(key, [token, restated, footnote])
    # the key's LLOQ row takes the footnote's, a value that restates nothing; the one at the token's cell restates the
    # token's LLOQ and is outside the key, not unexpected
    assert _verdicts(scored) == {2: "found", 3: "found"}
    assert next(r for r in scored["rows"] if r["row"] == 3)["found"]["id"] == "l2"
    assert (scored["totals"]["unexpected"], scored["totals"]["outside_key"]) == (0, 1)
    # an LLOQ fact anywhere else that the key does not have is unexpected
    other = footnote.model_copy(update={"value": "0.2", "anchor": f"{SHA}@workbook/1.0#s:'Listing'!A21", "id": "l3"})
    assert score(key, [token, restated, footnote, other])["totals"]["unexpected"] == 1
    # an LLOQ fact at the token's cell with another number restates nothing: a value of its own, judged
    wrong = restated.model_copy(update={"value": "5", "id": "l4"})
    scored = score(key, [token, wrong, footnote])
    assert _verdicts(scored) == {2: "found", 3: "found"} and [u["id"] for u in scored["unexpected"]] == ["l4"]


def test_a_not_data_table_and_a_where_set_what_the_key_covers():
    key = _key([_row(time="1")], not_data=({"file": "listing.xlsx", "where": "Notes", "table": "comments",
                                            "reason": "free text"},))
    covered = _ex(time_min=60.0, anchor=f"{SHA}@workbook/1.0#s:'Notes'!B2", id="n")
    elsewhere = _ex(time_min=60.0, anchor=f"{SHA}@workbook/1.0#s:'Other'!B2", id="o")
    scored = score(key, [_ex(time_min=60.0), covered, elsewhere])
    assert [u["id"] for u in scored["unexpected"]] == ["n"] and scored["totals"]["outside_key"] == 1


def test_a_page_range_covers_every_page_in_it_and_an_unread_place_is_listed():
    pdf3 = PDF.replace("#p:2/", "#p:3/")
    on_two = _ex(file="report.pdf", method="pdf_table", anchor=PDF)
    extra = _ex(file="report.pdf", method="pdf_table", anchor=pdf3, subject="999", id="y")
    ranged = score(_key([_row(file="report.pdf", where="2-3")]), [on_two, extra])
    assert (ranged["totals"]["unexpected"], ranged["totals"]["outside_key"]) == (1, 0)
    page = score(_key([_row(file="report.pdf", where="2")]), [on_two, extra])
    assert (page["totals"]["unexpected"], page["totals"]["outside_key"]) == (0, 1)
    # a misspelt sheet: the key's place names nothing a value of that file was read in
    key = _key([_row(time="1"), _row(time="2", where="Lisitng"), _row(time="3", where="Lisitng")])
    scored = score(key, [_ex(time_min=60.0)])
    assert scored["places_unread"] == [{"first_row": 3, "rows": 2, "file": "listing.xlsx", "where": "Lisitng"}]
    assert public(scored)["places_unread"] == [{"first_row": 3, "rows": 2}] and "Lisitng" not in render(scored)
    assert score(key, [_ex(time_min=60.0, anchor=None)])["places_unread"] == []     # no anchor: not judged


def test_a_spread_fact_is_not_a_value_and_an_excluded_value_is_not_read(tmp_path, delivery, truth_key):
    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    ids = write_truth(ws, delivery)
    view = LedgerView(ws)
    mean = next(v for v in view.values() if v.statistic == "arithmetic_mean" and v.field == "concentration"
                and v.value is not None)
    store = IntakeStore(ws)
    spread = Fact(id="", delivery="dl-1", entity=EntityRef(study=mean.entity.study, analyte=mean.entity.analyte),
                  field="concentration", value=None, time=mean.time, time_unit=mean.time_unit, statistic="arithmetic_mean",
                  spread=1.5, spread_kind="SD", method="derived", derived_from=(mean.id,), compute="spread-1/sd_from_se",
                  by="code", at=_now())
    store.facts.append("fact", lambda seq: spread.model_copy(update={"id": f"f-{seq}"}).model_dump(mode="json"))
    assert _clean(score(truth_key, from_ledger(ws))["totals"], len(truth_key.rows))
    excluded = next(iter(ids.values()))
    store.facts.append("status", StatusChange(target=excluded, status="excluded", reason="a test", by="u",
                                              at=_now()).model_dump(mode="json"))
    totals = score(truth_key, from_ledger(ws))["totals"]
    assert (totals["missing"], totals["found"]) == (1, len(truth_key.rows) - 1)


# --- the baseline: today's stores ----------------------------------------------------------------------------------


def test_the_stores_adapter_on_a_project_built_by_ingest(tmp_path):
    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    library = DocumentLibrary(ws)
    template, messy = synthetic.template_workbook(), synthetic.messy_workbook()
    for file in (template, messy):
        ingest(ws, library, file.data, file.name, by="u", brief=empty_brief(synthetic.DRUG, by="u"))
    extracted = from_stores(ws)
    assert all(e.anchor is None and e.arm == "" for e in extracted)          # today's stores keep neither
    common = dict(file=template.name, where="PK_Individual", analyte=synthetic.DRUG, matrix="plasma", unit="ng/ml")
    rows = [
        # the template's arm is part of today's study id (EXA-101-TEST): a key's study and arm still find it
        _row(**common, study="EXA-101", arm="TEST", subject="001", time="61.8", time_unit="min", value="12.4"),
        _row(**common, study="EXA-101", arm="TEST", subject="", field="pk.Cmax", time="", time_unit="", value="31.4"),
        _row(file=template.name, where="Studies", study="EXA-101", arm="TEST", analyte="", matrix="", subject="",
             field="dose", time="", time_unit="", value="10", unit="mg"),
        _row(**{**common, "where": "PK_Summary"}, study="EXA-101", arm="RLD", subject="", time="0.5", value="11.8"),
        # the messy workbook's sheet read on arrival and waiting for a person: its points
        _row(file=messy.name, where="Fasting", study="230-23", subject="001", time="0.5", value="12.1"),
        _row(file=messy.name, where="Fasting", study="230-23", subject="004", time="1", value=">1000"),
        # the template's dissolution rows: one vessel
        _row(file=template.name, where="Dissolution", study="", analyte="", matrix="", subject="",
             product="Exampleamide 10 mg tablet", batch="B123", vessel="vessel_1", field="percent_dissolved",
             conditions="apparatus=USP 2 paddle;rpm=50;medium=0.1 N HCl;ph=1.2;volume_ml=900;temperature_c=37",
             time="15", time_unit="min", value="62.1", unit=""),
    ]
    scored = score(_key(rows), extracted, fold_arm=True)
    assert _verdicts(scored) == {2: "found", 3: "found", 4: "found", 5: "found", 6: "found", 7: "missing", 8: "found"}
    # today's draft leaves the above-range point out: the baseline says so as an omission, and reads what the key
    # does not hold in the files it covers as unexpected
    assert scored["totals"]["unexpected"] > 0 and scored["totals"]["outside_key"] == 0
    # the stores' dataset keeps the template's reported Cmax with its geometric mean and CV%
    cmax = next(r for r in scored["rows"] if r["row"] == 3)["found"]
    assert cmax["attributes"] == {"statistic": "geometric_mean", "spread": "18.2", "spread_kind": "CV%"}


def test_the_baseline_names_the_missing_rows_it_read_under_other_labels(tmp_path):
    """Today's stores keep labels another way than the key's convention (a dose with no analyte or product, a PK
    parameter with its dataset's analyte): the verdicts stay §13's, and the diagnostic says which rows these are."""
    template = synthetic.template_workbook()
    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    ingest(ws, DocumentLibrary(ws), template.data, template.name, by="u", brief=empty_brief(synthetic.DRUG, by="u"))
    key = load_key(key_from_truth([template]), "truth.xlsx")
    scored = score(key, from_stores(ws), fold_arm=True)
    totals = scored["totals"]
    differ = {d["row"]: d for d in scored["labels_differ"]}
    assert 0 < totals["labels_differ"] <= totals["missing"]
    assert all(_verdicts(scored)[row] == "missing" for row in differ)                   # no verdict changes
    dose = next(d for d in differ.values() if d["field"] == "dose")
    assert {"analyte", "matrix", "product", "batch"} <= set(dose["labels"])
    cmax = next(d for d in differ.values() if d["field"] == "pk.Cmax")
    assert cmax["labels"] == ["analyte", "matrix"]
    report = render(scored)
    assert "## Missing rows whose value was read under other labels (diagnostic)" in report
    assert synthetic.DRUG not in report and "EXA-101" not in report


# --- time and coverage -----------------------------------------------------------------------------------------------


def _record(sha: str, name: str, delivery: str = "dl-1") -> FileRecord:
    return FileRecord(file_id=f"fl-{sha[:12]}", sha256=sha, name=name, size_bytes=10, delivery=delivery, by="u",
                      at="2026-11-13T10:00:00.000Z")


def _summary(silent: int, **more: Any) -> CoverageSummary:
    return CoverageSummary(state="read", regions=4, regions_mapped=3, regions_excluded=1, regions_unread=0,
                           numeric_cells=120, cells_used=110, cells_excluded=10 - silent, cells_silent=silent,
                           silent_loss=silent, outside_items=2, **more)


def _project_with_runs(ws: Workspace, files: list[tuple[str, str]]) -> None:
    """files.jsonl, runs.jsonl and the coverage files of one delivery, as W and D5 write them: the first file done
    (its coverage since recomputed), the second done (no coverage file yet), the third still queued."""
    store = IntakeStore(ws)
    store.files.append("delivery", {"id": "dl-1", "by": "u", "at": "2026-11-13T10:00:00.000Z"})
    for sha, name in files:
        store.files.append("file", _record(sha, name).model_dump(mode="json"))
    stages = (StageTiming(stage="parse", seconds=3.375, ok=True), StageTiming(stage="map", seconds=0.125, ok=True),
              StageTiming(stage="ledger", seconds=9.875, ok=True))
    for n, (sha, _name) in enumerate(files, start=1):
        queued = RunRecord(run_id=f"run-{n}", file_id=f"fl-{sha[:12]}", sha256=sha, delivery="dl-1", state="queued",
                           queued_at="2026-11-13T10:00:01.000Z", by="code")
        store.runs.append("run", queued.model_dump(mode="json"))
        if n == 3:
            continue
        done = queued.model_copy(update={"state": "done", "started_at": "2026-11-13T10:01:00.000Z",
                                         "finished_at": f"2026-11-13T10:0{4 + n}:30.000Z", "stages": stages,
                                         "coverage": _summary(3 if n == 1 else 0)})
        store.runs.append("run", done.model_dump(mode="json"))
    sha, name = files[0]
    store.put_coverage(FileCoverage(file=_record(sha, name), summary=_summary(0), regions=(), outside=(),
                                    anchor_problems=(), computed_at=_now()))


def test_timings_and_coverage_from_runs_and_the_coverage_files(tmp_path):
    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    files = [("1" * 64, "listing.xlsx"), ("2" * 64, "report.pdf"), ("3" * 64, "notes.docx")]
    _project_with_runs(ws, files)
    queue = ReadingQueue(ws)
    queue.add([("file-111111111111", "listing.xlsx")], task="arrival", by="u")
    queue.finish(queue.take().id, "done")

    times = timings(ws)
    d = times["deliveries"]["dl-1"]
    assert (d["files"], d["runs"], d["done"], d["queued"], d["failed"]) == (3, 3, 2, 1, 0)
    assert d["stages"]["parse"] == {"seconds": 6.75, "longest": 3.375, "runs": 2, "failed": 0}
    assert d["last_end"] == "2026-11-13T10:06:30.000Z" and d["arrival_to_end_seconds"] is None   # one still waits
    assert (times["queue"]["items"], times["queue"]["done"]) == (1, 1)

    cover = coverage_totals(ws)
    assert (cover["files"], cover["by_state"]) == (3, {"no coverage": 2, "read": 1})
    assert cover["current"]["silent_loss"] == 0 and cover["at_run_end"]["silent_loss"] == 3
    assert cover["at_run_end"]["regions"] == 8 and cover["differs"] == ["1" * 64]
    per_file = {f["name"]: (f["state"], f["run_state"]) for f in cover["per_file"]}
    assert per_file == {"listing.xlsx": ("read", "done"), "report.pdf": (None, "done"), "notes.docx": (None, "queued")}


def test_a_delivery_whose_runs_all_ended_has_its_time_from_arrival(tmp_path):
    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    _project_with_runs(ws, [("1" * 64, "listing.xlsx"), ("2" * 64, "report.pdf")])
    d = timings(ws)["deliveries"]["dl-1"]
    assert (d["first_arrival"], d["last_end"], d["arrival_to_end_seconds"]) == (
        "2026-11-13T10:00:00.000Z", "2026-11-13T10:06:30.000Z", 390.0)
    assert timings(Workspace(FileProjectStore(tmp_path / "empty"), "t1", "p1"))["deliveries"] == {}


# --- the report and the command --------------------------------------------------------------------------------------

_CODE = re.compile(r"[0-9a-f]{12}@[a-z0-9_]+/[A-Za-z0-9.+_-]+#(s:#[1-9][0-9]*![A-Z]{1,3}[1-9][0-9]*|[pdx]:[^`]*)"
                   r"|[0-9a-f]{12}|dl-[0-9]+")


def _secrets(key: ValueKey, extracted: list[Extracted]) -> set[str]:
    """Every value, label, place and file name of the key and of the values code read, and the key's analyst."""
    out = {key.analyst, key.delivery}
    for r in key.rows:
        out |= {r.value, r.file, r.where, r.table, r.note, r.time, r.study, r.arm, r.analyte, r.matrix, r.subject,
                r.product, r.batch, r.vessel, r.period, *(p.partition("=")[2] for p in r.conditions.split(";"))}
    for e in extracted:
        out |= {e.value or "", e.verbatim, e.file, e.study, e.arm, e.analyte, e.matrix, e.subject, e.product, e.batch,
                e.vessel, e.period, *(p.partition("=")[2] for p in e.conditions.split(";"))}
    return {s.strip() for s in out if s and s.strip()}


def _projection(report: str) -> str:
    """The report less what may hold digits and is no value: each backticked anchor, id or sha256 (checked to be
    one), a study or tag named by its row, and each table cell that is a count."""
    for span in re.findall(r"`([^`]*)`", report):
        assert _CODE.fullmatch(span), span
    text = re.sub(r"`[^`]*`", " ", report)
    text = re.sub(r"study of key row \d+|as in Studies row \d+", " ", text)
    return re.sub(r"(?<=\|) (0|[1-9][0-9]*) (?=\|)", " ", text)


def _leaks(text: str, secrets: set[str]) -> list[str]:
    return sorted(s for s in secrets if re.search(rf"(?<![\w.]){re.escape(s)}(?![\w.])", text))


def _public_json_leaks(shown: dict[str, Any], secrets: set[str]) -> list[str]:
    """The secrets a public JSON holds, once each anchor is checked to be a masked one (then blanked: its parser
    version may read as a number) and each study or tag named by its row is cut."""
    blob = json.dumps(shown, ensure_ascii=False)
    for anchor in re.findall(r'"anchor": "([^"]*)"', blob):
        assert anchor == "" or _CODE.fullmatch(anchor), anchor
    blob = re.sub(r'"anchor": "[^"]*"', '"anchor": ""', blob)
    return _leaks(re.sub(r"study of key row \d+|as in Studies row \d+", " ", blob),
                  {s for s in secrets if not re.fullmatch(r"0|[1-9][0-9]*", s)})


def _scored_with_errors(ws: Workspace, key: ValueKey) -> tuple[dict[str, Any], list[Extracted]]:
    extracted = from_ledger(ws)
    changed = [e.model_copy(update={"value": "99.9"}) if e.subject == "003" and e.time_min == 120.0 else e
               for e in extracted if not (e.subject == "102" and e.time_min == 60.0)]
    changed.append(extracted[0].model_copy(update={"time_min": 9999.0, "id": "extra"}))
    return score(key, changed), changed


def test_the_default_report_holds_no_value_no_label_and_no_file_name(tmp_path, delivery, truth_key):
    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    write_truth(ws, delivery)
    store = IntakeStore(ws)
    shas = [line.body["sha256"] for line in store.files.entries("file")]
    for n, sha in enumerate(shas, start=1):
        run = RunRecord(run_id=f"run-{n}", file_id=f"fl-{sha[:12]}", sha256=sha, delivery="dl-1", state="done",
                        queued_at="2026-11-13T10:00:01.000Z", finished_at="2026-11-13T10:07:00.000Z", by="code",
                        stages=(StageTiming(stage="parse", seconds=3.375, ok=True),),
                        coverage=_summary(n, reason="the sheet Fasting of messy-delivery.xlsx"))
        store.runs.append("run", run.model_dump(mode="json"))
    scored, extracted = _scored_with_errors(ws, truth_key)
    assert scored["totals"]["wrong_value"] == 1 and scored["totals"]["missing"] == 1 and scored["unexpected"]
    secrets = _secrets(truth_key, extracted)
    assert {"230-23", "231-24", synthetic.DRUG, "001", "BLQ", "<0.5", "12.4037", "messy-delivery.xlsx", "Fasting",
            truth_key.analyst} <= secrets

    report = render(scored, timings=timings(ws), coverage=coverage_totals(ws))
    assert _leaks(_projection(report), secrets) == []
    assert "wrong_value" in report and "## Time (G7)" in report and "## Coverage (G2)" in report
    # every masked anchor is the value's own: its file, its cell, the sheet by its number in the report
    shown = public(scored)
    for row, masked in zip(scored["rows"], shown["rows"], strict=True):
        if row["verdict"] != "found":
            assert row["found"] is None or (masked["anchor"] and f"`{masked['anchor']}`" in report)
    # the JSON that may leave the server holds none of them either: its ids are the ledger's, its anchors masked
    assert _public_json_leaks(shown, secrets) == []
    assert {r["id"] for r in shown["rows"] if r["id"]} <= {e.id for e in extracted}

    with_values = render(scored, timings=timings(ws), coverage=coverage_totals(ws), with_values=True)
    for row in scored["rows"]:
        if row["verdict"] != "found":
            assert row["expected"]["value"] in with_values
            assert row["expected"]["labels"]["study"] in with_values and row["expected"]["file"] in with_values
            if row["found"]:
                assert row["found"]["value"] in with_values
    for f in delivery:
        assert f.name in with_values
    assert truth_key.analyst in with_values and "230-23" in with_values and "231-24" in with_values
    # the coverage that may leave the server holds no file name and no reason (free text)
    assert all(f["name"] == "" and f["at_run_end"]["reason"] == "" for f in public_coverage(coverage_totals(ws))["per_file"])


def test_a_sheet_in_a_masked_anchor_is_numbered_in_the_report_never_hashed():
    sheets: dict[str, dict[str, int]] = {}
    first = masked_anchor(f"{SHA}@workbook/1.0+openpyxl3.1.5#s:'Study 230-23'!C4", sheets)
    again = masked_anchor(f"{SHA}@workbook/1.0+openpyxl3.1.5#s:'Study 230-23'!D9", sheets)
    second = masked_anchor(f"{SHA}@workbook/1.0+openpyxl3.1.5#s:'Study 231-24'!C4", sheets)
    other = masked_anchor(f"{'b' * 64}@workbook/1.0+openpyxl3.1.5#s:'Study 231-24'!C4", sheets)
    assert (first, again, second, other) == ("aaaaaaaaaaaa@workbook/1.0+openpyxl3.1.5#s:#1!C4",
                                             "aaaaaaaaaaaa@workbook/1.0+openpyxl3.1.5#s:#1!D9",
                                             "aaaaaaaaaaaa@workbook/1.0+openpyxl3.1.5#s:#2!C4",
                                             "bbbbbbbbbbbb@workbook/1.0+openpyxl3.1.5#s:#1!C4")
    assert masked_anchor(PDF) == PDF.replace("a" * 64, "a" * 12)          # a PDF locator names no label


def test_routing_tags_show_a_vocabulary_word_and_otherwise_their_studies_row():
    key = _key([_row(time="1"), _row(time="2", study="231-24")],
               studies=({"study": "230-23", "population": "healthy", "application": "Programme X"},
                        {"study": "231-24", "population": "patient", "application": "Programme Y"}))
    scored = score(key, [_ex(time_min=60.0)])
    assert set(scored["by_tag"]["population"]) == {"healthy", "patient"}
    shown = public(scored)
    assert set(shown["by_tag"]["population"]) == {"healthy", "patient"}       # the field's words: no client text
    assert set(shown["by_tag"]["application"]) == {"as in Studies row 2", "as in Studies row 3"}
    assert set(shown["by_study"]) == {"study of key row 2", "study of key row 3"}
    report = render(scored)
    assert "Programme" not in report and "230-23" not in report and "| healthy | 1 |" in report


def test_the_command_refuses_a_broken_hash_chain_unless_told(tmp_path, capsys, delivery):
    root = tmp_path / "root"
    ws = Workspace(FileProjectStore(root), "t1", "p1")
    write_truth(ws, delivery)
    key = tmp_path / "key.xlsx"
    key.write_bytes(key_from_truth(delivery))
    path = IntakeStore(ws).facts.path
    lines = path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):                          # one fact's value edited after it was written
        entry = json.loads(line)
        if entry["kind"] == "fact" and entry["body"].get("field") == "dose":
            entry["body"]["value"] = 999
            lines[i] = json.dumps(entry)
            break
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    base = ["--root", str(root), "--project", "p1", "--key", str(key)]
    assert main(base) == 2
    assert "hash chain of the intake logs is broken (facts line" in capsys.readouterr().err
    assert main([*base, "--accept-broken-chain"]) == 0
    report = capsys.readouterr().out
    assert report.startswith("# Value score\n\n**The hash chain of the intake logs is broken") and "| facts |" in report
    assert main([*base, "--accept-broken-chain", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["score"]["chain_problems"][0]["log"] == "facts"


def _tree(root: Path) -> dict[str, tuple[int, int]]:
    return {str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file()}


def test_the_command_scores_compares_writes_the_template_and_writes_nothing_in_the_root(tmp_path, capsys, delivery):
    root = tmp_path / "root"
    ws = Workspace(FileProjectStore(root), "t1", "p1")
    write_truth(ws, delivery)
    ingest(ws, DocumentLibrary(ws), delivery[0].data, delivery[0].name, by="u", brief=empty_brief(synthetic.DRUG, by="u"))
    key = tmp_path / "key.xlsx"
    key.write_bytes(key_from_truth(delivery))
    before = _tree(root)
    base = ["--root", str(root), "--project", "p1", "--key", str(key)]

    assert main(base) == 0
    out = capsys.readouterr().out
    assert "# Value score" in out and f"| found | {len(load_key(key.read_bytes(), key.name).rows)} |" in out
    assert "230-23" not in out
    assert main([*base, "--tenant", "t1", "--json"]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["score"]["totals"]["found"] == body["score"]["totals"]["scored"] and body["score"]["source"] == "ledger"
    assert "230-23" not in json.dumps(body) and all(f["name"] == "" for f in body["coverage"]["per_file"])
    assert main([*base, "--json", "--with-values"]) == 0
    assert "230-23" in capsys.readouterr().out
    assert main([*base, "--source", "stores"]) == 0
    assert "| source | stores |" in capsys.readouterr().out
    # the stores' ids are built from sheet and series names: the JSON that may leave the server withholds them
    assert main([*base, "--source", "stores", "--json"]) == 0
    body = json.loads(capsys.readouterr().out)
    loaded = load_key(key.read_bytes(), key.name)
    secrets = _secrets(loaded, from_stores(ws) + from_ledger(ws))
    assert "Fasting" in secrets and _public_json_leaks(body["score"], secrets) == []
    assert body["score"]["options"]["fold_arm"] is True
    assert any(r["id"] and r["id"].startswith("value ") for r in body["score"]["rows"] + body["score"]["unexpected"])
    assert main([*base, "--with-values"]) == 0
    assert "never send this report" in capsys.readouterr().out

    report = tmp_path / "out" / "report.md"
    report.parent.mkdir()
    assert main([*base, "--out", str(report)]) == 0 and report.read_text(encoding="utf-8").startswith("# Value score")
    capsys.readouterr()
    assert main([*base, "--out", str(root / "report.md")]) == 2                     # never inside the root
    assert "writes nothing there" in capsys.readouterr().err
    template = tmp_path / "template.xlsx"
    assert main(["--template", str(template)]) == 0 and load_key(template.read_bytes(), "t.xlsx").rows == ()
    assert main(["--root", str(root), "--template", str(root / "t.xlsx")]) == 2
    assert main(["--key", str(key), "--compare", str(key)]) == 0
    assert "agree on every row" in capsys.readouterr().out

    bad = tmp_path / "bad.xlsx"
    bad.write_bytes(b"no workbook")
    assert main(["--root", str(root), "--project", "p1", "--key", str(bad)]) == 2
    assert main(["--root", str(root), "--project", "nope", "--key", str(key)]) == 2
    assert main(["--root", str(tmp_path / "none"), "--project", "p1", "--key", str(key)]) == 2
    assert main(["--root", str(root), "--project", "p1"]) == 2
    assert main([*base, "--tolerance", "-1"]) == 2
    capsys.readouterr()
    assert _tree(root) == before                                                   # read-only
