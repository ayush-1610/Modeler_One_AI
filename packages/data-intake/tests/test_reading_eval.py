"""R3c: the evaluation set for reading client sheets scores a reading against the values each sheet was written from,
and code's first filling (`suggest`) is measured on it. Software test data, never observed data."""

from __future__ import annotations

import json

import pytest

from modeler_intake.reading_eval import CASES, evaluate, score, suggest_reader

pytestmark = pytest.mark.req("T-47", "T-21")


def _case(name: str):
    return next(c for c in CASES if c.name == name)


def test_the_scorer_catches_a_wrong_column_a_wrong_unit_and_a_guessed_lloq():
    case = _case("published-mean")
    assert score(case, case.form).exact
    assert not score(case, case.form.model_copy(update={"value_columns": ["D"]})).fields["values"]   # the N column
    assert not score(case, case.form.model_copy(update={"value_unit": "µg/mL"})).fields["units"]
    assert not score(case, case.form.model_copy(update={"lloq": 1.0})).fields["lloq"]
    assert score(case, None).fields == dict.fromkeys(score(case, None).fields, False)


def test_every_case_reads_back_its_own_answer():
    """The person's reading kept with each case gives back the values the case wrote: case and scorer agree."""
    assert [s.case for s in evaluate(lambda case, grid: case.form) if not s.exact] == []


def test_code_alone_reads_these_sheets_today():
    """The baseline the reading agent is measured against (code's first filling, unchanged by a person). A change to
    `suggest` that moves this list is a change in what a person must correct: update the list with the CHANGELOG."""
    scores = {s.case: s for s in evaluate(suggest_reader)}
    assert sorted(n for n, s in scores.items() if s.exact) == [
        "dissolution-vessels", "geometric-mean", "long-subject-time", "published-mean", "wide-subjects"]
    # two sheets read without a problem but with the wrong values: what a person must catch today
    assert {n for n, s in scores.items() if s.fields["read"] and not s.fields["values"]} == {"decimal-comma", "report-table"}


def test_the_cases_are_json_safe_for_the_run_record():
    assert json.loads(json.dumps([c.form.model_dump(mode="json") for c in CASES]))
