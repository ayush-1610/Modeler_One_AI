"""T-47, T-21: two analysts' keys of one delivery compared (decision 8: disagreements go to the scientist).

Identical keys give no disagreement; each class (only in A, only in B, another value, another unit, another place,
a Not data table one key lists) is found under its name, with both analysts' row numbers. Rows join as the scorer
joins them, never on where they say a value stands. The keys are the synthetic Exampleamide truth.
"""

from __future__ import annotations

import pytest

from modeler_intake import synthetic
from modeler_project.key_compare import DIFFERENCES, MORE_DIFFERENCES, compare, render_comparison
from modeler_project.value_key import SCHEMA, ValueKey, key_from_truth, load_key, write_key

pytestmark = pytest.mark.req("T-47", "T-21")

HEADER = {"schema": SCHEMA, "delivery": "D-001", "date": "2026-11-13", "status": "draft"}


def _row(**values: str) -> dict[str, str]:
    base = {"file": "listing.xlsx", "where": "Fasting", "table": "Table 1", "study": "230-23", "analyte": "Exampleamide",
            "matrix": "plasma", "subject": "001", "field": "concentration", "time": "0.5", "time_unit": "h",
            "value": "12.1", "unit": "ng/mL"}
    return {**base, **values}


def _key(rows: list[dict[str, str]], *, analyst: str, studies: tuple[dict[str, str], ...] = (),
         not_data: tuple[dict[str, str], ...] = ()) -> ValueKey:
    return load_key(write_key({**HEADER, "analyst": analyst}, rows, studies, not_data), "key.xlsx")


def _differences(result: dict) -> dict[str, int]:
    return {name: len(result[name]) for name in (*DIFFERENCES, *MORE_DIFFERENCES) if result[name]}


def test_identical_keys_give_no_disagreement():
    truth = load_key(key_from_truth(synthetic.delivery()), "truth.xlsx")
    result = compare(truth, truth)
    assert _differences(result) == {} and result["agree"] == len(truth.rows)
    assert "agree on every row" in render_comparison(result)
    template = load_key(key_from_truth([synthetic.template_workbook()]), "truth.xlsx")
    assert _differences(compare(template, template)) == {}


def test_the_same_reading_written_differently_is_no_disagreement():
    a = _key([_row(value="12.40"), _row(time="1", value="BLQ"), _row(time="2", value="NS"),
              _row(time="4", unit="ng/ml"), _row(time="8", study="230-23", arm="Test")], analyst="A",
             studies=({"study": "230-23", "names": "Study 23023"},))
    b = _key([_row(value="12.4"), _row(time="60", time_unit="min", value="BLOQ"), _row(time="2", value="not sampled"),
              _row(time="4", unit="ng/mL"), _row(time="8", study="Study 23023", arm="TEST")], analyst="B",
             studies=({"study": "Study 23023", "names": "230-23"},))          # one study, its names the other way round
    result = compare(a, b)
    assert _differences(result) == {} and result["agree"] == 5
    # a page by its number ("p. 2" is "2"); a thousands group its table settles, written without it by the other
    pdf = dict(file="report.pdf", subject="", field="pk.AUC_last", time="", time_unit="", unit="ng*h/mL")
    a = _key([_row(**pdf, where="p. 2", value="1,523"), _row(**{**pdf, "field": "pk.Cmax"}, where="p. 2", value="31.4")],
             analyst="A")
    b = _key([_row(**pdf, where="2", value="1523"), _row(**{**pdf, "field": "pk.Cmax"}, where="2", value="31.4")],
             analyst="B")
    result = compare(a, b)
    assert _differences(result) == {} and result["agree"] == 2


def test_each_class_of_disagreement_is_found_with_both_row_numbers():
    a = _key([_row(), _row(time="1", value="30.4"), _row(time="2", unit="ng/mL"), _row(time="4"),
              _row(time="8", value="5.0"), _row(subject="002")],
             analyst="A", not_data=({"file": "listing.xlsx", "where": "Notes", "table": "comments", "reason": "free text"},))
    b = _key([_row(), _row(time="1", value="30.5"), _row(time="2", unit="µg/L"), _row(time="4", where="Fed"),
              _row(time="12", value="1.0")],
             analyst="B", not_data=({"file": "listing.xlsx", "where": "Summary", "table": "NCA", "reason": "derived"},))
    result = compare(a, b)
    assert _differences(result) == {"only_a": 2, "only_b": 1, "value_differs": 1, "unit_differs": 1, "where_differs": 1,
                                    "not_data_differs": 2}
    assert result["agree"] == 1
    assert [(p["a"]["row"], p["b"]["row"], p["a"]["value"], p["b"]["value"]) for p in result["value_differs"]] == [
        (3, 3, "30.4", "30.5")]
    assert [(p["a"]["unit"], p["b"]["unit"]) for p in result["unit_differs"]] == [("ng/mL", "µg/L")]
    assert [(p["a"]["where"], p["b"]["where"]) for p in result["where_differs"]] == [("Fasting", "Fed")]
    assert [(r["row"], r["time"]) for r in result["only_a"]] == [(6, "8"), (7, "0.5")]
    assert [(r["row"], r["time"]) for r in result["only_b"]] == [(6, "12")]
    assert [(n["side"], n["table"]) for n in result["not_data_differs"]] == [("a", "comments"), ("b", "NCA")]
    text = render_comparison(result)
    for title in ("## Values differ", "## Units differ", "## Same value, another place", "## Only in A", "## Only in B",
                  "## Not data, listed by one key only"):
        assert title in text
    assert "| 3 | 3 | concentration at 1 h (study 230-23, analyte Exampleamide, matrix plasma, subject 001) | 30.4 ng/mL | " \
           "30.5 ng/mL |" in text
    assert "read on the server only" in text


def test_attributes_and_the_studies_sheet_are_compared_too():
    mean = dict(subject="", statistic="arithmetic_mean", spread="1.92", spread_kind="SD", n="5")
    a = _key([_row(**mean), _row(time="1", **mean)], analyst="A",
             studies=({"study": "230-23", "names": "Study 23023", "population": "healthy", "route": "oral"},
                      {"study": "231-24", "population": "healthy"}))
    b = _key([_row(**mean), _row(time="1", **{**mean, "spread": "0.86", "spread_kind": "SE"})], analyst="B",
             studies=({"study": "230-23", "population": "patient", "route": "Oral"},))
    result = compare(a, b)
    assert _differences(result) == {"attributes_differ": 1, "studies_differs": 2} and result["agree"] == 1
    assert [(p["a"]["row"], p["b"]["row"], p["attributes"]) for p in result["attributes_differ"]] == [
        (3, 3, ["spread", "spread_kind"])]
    assert result["studies_differs"] == [
        {"study": "230-23", "row_a": "2", "row_b": "2", "names": ["Study 23023", ""],
         "tags": {"population": ["healthy", "patient"]}},
        {"study": "231-24", "row_a": "3", "row_b": None, "only": "a"}]
    text = render_comparison(result)
    assert "agree on every row" not in text and "## Studies differ" in text and "## Attributes differ" in text
    assert "| 230-23 | 2 | 2 | names: Study 23023 / (none); population: healthy / patient |" in text
    assert "listed by key A only" in text


def test_a_perturbed_copy_of_the_truth_disagrees_where_it_was_changed():
    truth = load_key(key_from_truth(synthetic.delivery()), "truth.xlsx")
    rows = [r.model_dump(exclude={"row"}) for r in truth.rows]
    changed = next(i for i, r in enumerate(rows) if r["value"] == "30.4")
    rows[changed]["value"] = "34.0"
    dropped = rows.pop(next(i for i, r in enumerate(rows) if r["value"] == ">1000"))
    second = load_key(write_key({**HEADER, "analyst": "B"}, rows, (), truth.not_data), "b.xlsx")
    result = compare(truth, second)
    assert _differences(result) == {"value_differs": 1, "only_a": 1}
    assert result["value_differs"][0]["a"]["value"] == "30.4" and result["only_a"][0]["value"] == dropped["value"]
    assert result["agree"] == len(truth.rows) - 2
