"""Conflicts (contracts §6.3, §8.6): two active values of one entity (labels included), field, time, statistic and
conditions that differ are both kept and listed; different units are a unit conflict and nothing is converted; values
that differ only in their conditions or a label are not a conflict (a solubility at another pH, a profile in another
medium, plasma beside urine of one arm, Day 1 beside Day 14); a derived fact does not conflict with its input; after a
person's `Choice` the other values are excluded."""

from __future__ import annotations

import pytest

from modeler_intake import synthetic
from modeler_intake.anchors import AnchorError
from modeler_project.intake_records import Choice
from modeler_project.intake_store import IntakeStore
from modeler_project.ledger import Ledger
from modeler_project.workspace import Workspace

from .test_ledger_support import AT, make_ws, record_rows, record_table

pytestmark = pytest.mark.req("T-47", "T-05", "F-404")

A, B = "a" * 64, "b" * 64


@pytest.fixture
def ws(tmp_path) -> Workspace:
    return make_ws(tmp_path)


def _table(ledger: Ledger, *, sha: str = A, sheet: str, region: str, caption: str, dose: tuple[float, str] | None = None,
           rows: tuple[dict, ...] = (), study: str = "230-40", field: str = "concentration") -> list[str]:
    """A small table naming a study (and the drug, for concentrations), with a dose in its caption when given; the ids
    of its values, then of its facts."""
    constants = [("study_id", study, None)]
    if field == "concentration":
        constants.append(("analyte", synthetic.DRUG, None))
    if dose is not None:
        constants.append(("dose", dose[0], dose[1]))
    recorded = record_rows(ledger, sha=sha, sheet=sheet, region=region, caption=caption, rows=rows, field=field,
                           constants=tuple(constants))
    return [*(f"{recorded.extract}#{i}" for i in range(len(rows)) if recorded.extract), *recorded.facts]


def _dose_ids(ledger: Ledger) -> list[str]:
    return [v.id for v in ledger.values(field="dose")]


def test_two_values_that_disagree_are_both_kept_and_listed(ws):
    ledger = Ledger(ws)
    plasma = {"matrix": "plasma"}
    first = _table(ledger, sheet="S1", region="rg-0000000001", caption="Study 230-40, 50 mg", dose=(50.0, "mg"),
                   rows=({"time": 1, "value": 12.0, "labels": plasma}, {"time": 2, "value": 9.0, "labels": plasma}))
    second = _table(ledger, sheet="S2", region="rg-0000000002", caption="Study 230-40, 60 mg", dose=(60.0, "mg"),
                    rows=({"time": 1, "value": 12.0, "labels": plasma}, {"time": 2, "value": 9.5, "labels": plasma}))
    found = {c.field: c for c in ledger.conflicts()}
    assert set(found) == {"dose", "concentration"}
    assert found["dose"].kind == "value" and set(found["dose"].values) == set(_dose_ids(ledger))
    concentration = found["concentration"]
    assert concentration.kind == "value" and concentration.time == 2 and set(concentration.values) == {first[1], second[1]}
    assert concentration.entity.matrix == "plasma" and ledger.entity(concentration.entity.study).label == "230-40"
    assert all(ledger.value(i).status == "proposed" for c in found.values() for i in c.values)    # all kept
    assert concentration.id.startswith("cx-") and len(concentration.id) == 13
    assert [c.id for c in Ledger(ws).conflicts()] == [c.id for c in ledger.conflicts()]    # stable while nothing changes
    study = concentration.entity.study
    assert {c.id for c in ledger.conflicts(study=study)} == {c.id for c in found.values()}
    assert ledger.conflicts(study="st-999") == [] and ledger.conflicts(product="pr-1") == []


def test_a_unit_conflict_is_listed_and_nothing_is_converted(ws):
    ledger = Ledger(ws)
    _table(ledger, sheet="S1", region="rg-0000000001", caption="Study 230-40, 50 mg", dose=(50.0, "mg"),
           rows=({"time": 1, "value": 12.0},))
    _table(ledger, sheet="S2", region="rg-0000000002", caption="Study 230-40, 0.05 g", dose=(0.05, "g"),
           rows=({"time": 1, "value": 12.0},))
    _table(ledger, sheet="S3", region="rg-0000000003", caption="Study 230-40",
           rows=({"time": 2, "value": 9.0, "unit": "ng/mL"}, {"time": 3, "value": 5.0, "unit": "NG/ML"}))
    _table(ledger, sheet="S4", region="rg-0000000004", caption="Study 230-40",
           rows=({"time": 2, "value": 9.0, "unit": "µg/L"}, {"time": 3, "value": 5.0, "unit": "ng/ml"}))
    found = {c.field: c for c in ledger.conflicts()}
    assert sorted((c.field, c.kind, c.time) for c in found.values()) == [("concentration", "unit", 2), ("dose", "unit", None)]
    assert sorted((ledger.value(i).value, ledger.value(i).unit) for i in found["dose"].values) == [(0.05, "g"), (50.0, "mg")]
    assert sorted(ledger.value(i).unit for i in found["concentration"].values) == ["ng/mL", "µg/L"]
    # ng/mL and NG/ML are one unit (the concentration table's spelling); µg/L is another, even when it means the same


def test_values_that_differ_only_in_their_conditions_or_a_label_are_not_a_conflict(ws):
    ledger = Ledger(ws)
    # a solubility at two pH (a compound field: no study)
    _table(ledger, sheet="S1", region="rg-0000000001", caption="Study 230-40", field="phys.solubility.ref",
           rows=({"value": 0.12, "unit": "mg/mL", "conditions": {"ph": "1.2"}, "statistic": None},
                 {"value": 0.03, "unit": "mg/mL", "conditions": {"ph": "6.8"}, "statistic": None}))
    # a profile in two media; plasma beside urine of one arm; Day 1 beside Day 14; a mean beside a median
    _table(ledger, sheet="S2", region="rg-0000000002", caption="Study 230-40",
           rows=({"time": 1, "value": 40.0, "field": "percent_dissolved", "unit": "%", "conditions": {"medium": "HCl buffer"}},
                 {"time": 1, "value": 25.0, "field": "percent_dissolved", "unit": "%", "conditions": {"medium": "phosphate"}},
                 {"time": 2, "value": 9.0, "labels": {"matrix": "plasma"}},
                 {"time": 2, "value": 3.0, "labels": {"matrix": "urine"}},
                 {"time": 4, "value": 6.0, "labels": {"occasion": "Day 1"}},
                 {"time": 4, "value": 8.0, "labels": {"occasion": "Day 14"}},
                 {"time": 6, "value": 2.0},
                 {"time": 6, "value": 1.8, "statistic": "median"}))
    assert ledger.conflicts() == []
    # the same pH written another way is the same condition: a conflict
    _table(ledger, sheet="S3", region="rg-0000000003", caption="Study 230-40", field="phys.solubility.ref",
           rows=({"value": 0.20, "unit": "mg/mL", "conditions": {"ph": "1,20"}, "statistic": None},))
    (found,) = ledger.conflicts()
    assert found.field == "phys.solubility.ref" and found.entity.study is None and len(found.values) == 2


def test_times_within_the_ledger_resolution_are_one_time(ws):
    ledger = Ledger(ws)
    _table(ledger, sheet="S1", region="rg-0000000001", caption="Study 230-40",
           rows=({"time": 1, "value": 12.0}, {"time": 4, "value": 6.0}))
    _table(ledger, sheet="S2", region="rg-0000000002", caption="Study 230-40",
           rows=({"time": 60.5, "time_unit": "min", "value": 11.0}, {"time": 242, "time_unit": "min", "value": 5.0}))
    (found,) = ledger.conflicts()                       # 1 h and 60.5 min are one time; 4 h and 242 min are not
    assert sorted(ledger.value(i).value for i in found.values) == [11.0, 12.0]


def test_a_derived_fact_does_not_conflict_with_its_input(ws):
    ledger = Ledger(ws)
    _table(ledger, sheet="S1", region="rg-0000000001", caption="Study 230-40, 0.5 g", dose=(0.5, "g"),
           rows=({"time": 1, "value": 12.0, "statistic": "arithmetic_mean"},))
    (derived,) = [f for f in ledger.derive() if f.field == "dose"]
    assert (derived.value, derived.unit) == (500.0, "mg")
    assert ledger.conflicts() == []


def test_after_a_choice_the_other_values_are_excluded(ws):
    ledger = Ledger(ws)
    _table(ledger, sheet="S1", region="rg-0000000001", caption="Study 230-40, 50 mg", dose=(50.0, "mg"))
    _table(ledger, sheet="S2", region="rg-0000000002", caption="Study 230-40, 60 mg", dose=(60.0, "mg"))
    _table(ledger, sheet="S3", region="rg-0000000003", caption="Study 230-40, 50 mg", dose=(50.0, "mg"))
    (conflict,) = ledger.conflicts()
    by_value = {}
    for value_id in conflict.values:
        by_value.setdefault(ledger.value(value_id).value, []).append(value_id)
    keep, other = by_value[50.0][0], by_value[60.0][0]
    choice = Choice(id="ch-1", conflict_id=conflict.id, keep=keep, why="the protocol states 50 mg", by="u-1", at=AT)
    store = IntakeStore(ws)
    store.review.append("choice", choice.model_dump(mode="json"))        # D6's choose writes the line and audits it
    with pytest.raises(ValueError):
        ledger.apply_choice(choice.model_copy(update={"keep": "f-999"}))
    with pytest.raises(AnchorError):
        ledger.apply_choice(choice.model_copy(update={"conflict_id": "cx-../x"}))
    changes = ledger.apply_choice(choice)
    assert [c.target for c in changes] == [other]                        # the same reading as the one kept stays
    excluded = ledger.value(other)
    assert excluded.status == "excluded" and "ch-1" in excluded.status_reason and conflict.id in excluded.status_reason
    assert excluded.value == 60.0                                        # still readable
    assert all(ledger.value(i).status == "proposed" for i in by_value[50.0])
    assert ledger.conflicts() == []
    heads = store.facts.head()
    assert ledger.apply_choice(choice) == [] and store.facts.head() == heads      # settled: nothing again


def test_a_choice_that_excludes_a_correction_also_excludes_the_value_it_brings_back(ws):
    ledger = Ledger(ws)
    _table(ledger, sheet="S1", region="rg-0000000001", caption="Study 230-40, 55 mg", dose=(55.0, "mg"))
    (written,) = _dose_ids(ledger)
    corrected = ledger.enter(value=60.0, why="the amendment", by="u-1", supersedes=written)
    _table(ledger, sheet="S2", region="rg-0000000002", caption="Study 230-40, 50 mg", dose=(50.0, "mg"))
    (conflict,) = ledger.conflicts()
    keep = next(i for i in conflict.values if ledger.value(i).value == 50.0)
    assert set(conflict.values) == {corrected.id, keep}
    changes = ledger.apply_choice(Choice(id="ch-2", conflict_id=conflict.id, keep=keep, why="the protocol", by="u-1", at=AT))
    # excluding the correction brings back the value it corrected (55 mg): the choice excludes that one too
    assert [c.target for c in changes] == [corrected.id, written]
    assert ledger.conflicts() == [] and [v.value for v in ledger.values(field="dose")] == [50.0]


def test_a_spread_fact_and_a_missing_value_take_no_part(ws):
    ledger = Ledger(ws)
    workbook = synthetic.messy_workbook()
    record_table(ledger, workbook, "fasting-metabolite")
    ledger.derive()
    assert any(v.method == "derived" for v in ledger.values()) and ledger.conflicts() == []
    # the missing "NS" sample of subject 005 states nothing: no conflict with another file's number at that time
    record_table(ledger, workbook, "fasting-individual")
    missing = next(v for v in ledger.values() if v.verbatim == "NS")
    assert missing.value is None and not missing.censored and ledger.conflicts() == []


def test_two_names_of_one_study_are_not_a_conflict(ws):
    """A study named "230-40" in one file and "LOC-7 (protocol 230-40)" in another is one study once the link joins
    them: the two study_id facts name it, they do not disagree about data; the arm-level doses do."""
    ledger = Ledger(ws)
    _table(ledger, sha=A, sheet="S1", region="rg-0000000001", caption="Study 230-40, 50 mg", dose=(50.0, "mg"))
    record_rows(ledger, sha=B, sheet="S2", region="rg-0000000002", caption="Study LOC-7 (protocol 230-40), 60 mg",
                constants=(("study_id", "LOC-7", None), ("link.protocol", "230-40", None), ("dose", 60.0, "mg")))
    ledger.link_files()
    assert sorted(v.value for v in ledger.values(field="study_id")) == ["230-40", "LOC-7"]
    assert len({v.entity.study for v in ledger.values(field="study_id")}) == 1
    (conflict,) = ledger.conflicts()
    assert conflict.field == "dose" and sorted(ledger.value(i).value for i in conflict.values) == [50.0, 60.0]


def test_two_arms_of_one_study_that_state_two_lloqs_are_not_a_conflict(ws):
    """An `lloq` fact is on (study, analyte, matrix); two arms (two assays) may state two LLOQs. D5 compares LLOQs per
    profile, (study, arm, analyte, matrix): the ledger lists no conflict, and both facts are kept."""
    ledger = Ledger(ws)
    plasma = {"matrix": "plasma"}
    for i, (cohort, lloq) in enumerate((("Cohort 1", 0.5), ("Cohort 2", 1.0)), start=1):
        record_rows(ledger, sheet=f"S{i}", region=f"rg-000000000{i}", caption=f"Study 230-40, {cohort}, LLOQ {lloq} ng/mL",
                    rows=({"time": 1, "value": 12.0 * i, "labels": plasma},),
                    constants=(("study_id", "230-40", None), ("treatment", cohort, None), ("analyte", synthetic.DRUG, None),
                               ("lloq", lloq, "ng/mL")))
    lloqs = ledger.values(field="lloq")
    assert sorted(v.value for v in lloqs) == [0.5, 1.0] and {v.entity.arm for v in lloqs} == {None}
    assert len({(v.entity.study, v.entity.analyte, v.entity.matrix) for v in lloqs}) == 1
    assert ledger.conflicts() == []


def test_two_values_at_a_time_too_large_to_convert_are_still_compared(ws):
    """A time whose conversion to minutes overflows is compared as written: two values that disagree there are listed."""
    ledger = Ledger(ws)
    _table(ledger, sheet="S1", region="rg-0000000001", caption="Study 230-40", rows=({"time": 1e307, "value": 5.0},))
    _table(ledger, sheet="S2", region="rg-0000000002", caption="Study 230-40", rows=({"time": 1e307, "value": 6.0},))
    (found,) = ledger.conflicts()
    assert found.field == "concentration" and sorted(ledger.value(i).value for i in found.values) == [5.0, 6.0]


def test_one_studys_analyte_named_in_two_files_is_compared_across_them(ws):
    """Analytes are resolved inside their file, so a study's analyte named in a workbook and in a report is two entities;
    once the report's label joins the workbook's study, their values of one analyte name still meet: a conflict. Values
    of no study from two files are never compared (nothing says they are one entity)."""
    ledger = Ledger(ws)
    for sha, value, region in ((A, 31.2, "rg-0000000001"), (B, 35.0, "rg-0000000002")):
        record_rows(ledger, sha=sha, sheet="S1", region=region, caption="Study EXA-101: Exampleamide", field="pk.Cmax",
                    rows=({"value": value},), constants=(("study_id", "EXA-101", None), ("analyte", synthetic.DRUG, None)))
    analytes = [v.entity.analyte for v in ledger.values(field="pk.Cmax")]
    assert len(set(analytes)) == 2 and len({v.entity.study for v in ledger.values(field="pk.Cmax")}) == 1
    (conflict,) = ledger.conflicts()
    assert conflict.field == "pk.Cmax" and sorted(ledger.value(i).value for i in conflict.values) == [31.2, 35.0]
    # no study: two files' values of one analyte name stay apart
    for sha, value, region in ((A, 1.0, "rg-0000000003"), (B, 2.0, "rg-0000000004")):
        record_rows(ledger, sha=sha, sheet="S3", region=region, caption="Exampleamide plasma, no study stated",
                    rows=({"time": 1, "value": value},), constants=(("analyte", synthetic.DRUG, None),))
    assert [c.field for c in ledger.conflicts()] == ["pk.Cmax"]
