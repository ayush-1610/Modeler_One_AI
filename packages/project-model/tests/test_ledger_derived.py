"""Derived facts (contracts §6.3, §8.6): the SD of an arithmetic mean from its SE with the n of that time point, then
with the series' n, none without an n, from a CV%; nothing for a geometric mean; the SD is a spread fact (value None)
on its input's entity, field, time and statistic, equal to `spread.sd_from_se`; a dose in g or µg becomes a dose in
mg; each derived fact names its inputs and its compute; `derive` twice adds nothing; superseding an input supersedes
the derived fact."""

from __future__ import annotations

import pytest

from modeler_intake import synthetic
from modeler_project.intake_store import IntakeStore
from modeler_project.ledger import Ledger
from modeler_project.ledger_compute import COMPUTE, DOSE_TO_MG, SD_FROM_CV, SD_FROM_SE, derivations
from modeler_project.ledger_view import LedgerView, is_spread_fact
from modeler_project.workspace import Workspace
from pbpk_domain import spread

from .test_ledger_support import make_ws, record_rows, record_table

pytestmark = pytest.mark.req("T-47", "T-05", "F-404")

STUDY = (("study_id", "230-41", None), ("analyte", synthetic.DRUG, None))


@pytest.fixture
def ws(tmp_path) -> Workspace:
    return make_ws(tmp_path)


def _spread_facts(ledger: Ledger) -> list:
    return [v for v in ledger.values() if is_spread_fact(v)]


def test_the_sd_of_a_mean_from_its_se_with_the_n_of_each_time_point(ws):
    ledger = Ledger(ws)
    recorded = record_table(ledger, synthetic.messy_workbook(), "fasting-metabolite")
    made = ledger.derive()
    means = {v.id: v for v in ledger.values() if v.id.startswith(f"{recorded.extract}#") and v.spread_kind == "SE"}
    assert len(made) == len(means) == 5                       # time 0 is BLQ with no SE: nothing to derive
    for fact in made:
        (source,) = fact.derived_from
        mean = means[source]
        assert (fact.value, fact.spread_kind, fact.compute, fact.method, fact.anchor) == (None, "SD", SD_FROM_SE, "derived", None)
        assert fact.spread == spread.sd_from_se(mean.spread, mean.n_at) and fact.n == mean.n_at
        assert (fact.entity, fact.field, fact.time, fact.time_unit, fact.statistic, fact.conditions, fact.unit) == (
            mean.entity, mean.field, mean.time, mean.time_unit, mean.statistic, mean.conditions, mean.unit)
        state = ledger.value(fact.id)
        assert is_spread_fact(state) and state.level == mean.level == "approved_mapping" and state.file_sha256 is None
        assert state.status == "proposed" and state.verbatim == ""
    # the landing keeps the ORIGINAL spread: the input still says SE
    assert {v.spread_kind for v in means.values()} == {"SE"}


def test_the_series_n_when_a_point_states_none_and_nothing_without_an_n(ws):
    ledger = Ledger(ws)
    rows = ({"time": 1, "value": 12.0, "spread": 1.5, "spread_kind": "SE"}, {"time": 2, "value": 9.0, "spread": 1.1,
                                                                            "spread_kind": "SE"})
    record_rows(ledger, sheet="S1", region="rg-0000000001", caption="Study 230-41, n = 12, Exampleamide plasma",
                rows=rows, constants=(*STUDY, ("n", 12.0, None)))
    made = ledger.derive()
    n_fact = next(v for v in ledger.values(field="n"))
    assert n_fact.value == 12 and isinstance(n_fact.value, int)
    assert len(made) == 2 and all(f.derived_from[1] == n_fact.id and f.n == 12 for f in made)
    assert sorted(f.spread for f in made) == sorted(spread.sd_from_se(se, 12) for se in (1.5, 1.1))
    # another study with an SE and no n anywhere: nothing
    record_rows(ledger, sheet="S2", region="rg-0000000002", caption="Study 230-42, Exampleamide plasma", rows=rows,
                constants=(("study_id", "230-42", None), ("analyte", synthetic.DRUG, None)))
    assert ledger.derive() == []
    # two different n for one study: no series' n either
    record_rows(ledger, sheet="S3", region="rg-0000000003", caption="Study 230-42, n = 10", constants=(
        ("study_id", "230-42", None), ("n", 10.0, None)))
    record_rows(ledger, sheet="S4", region="rg-0000000004", caption="Study 230-42, n = 11", constants=(
        ("study_id", "230-42", None), ("n", 11.0, None)))
    assert ledger.derive() == []


def test_the_sd_from_a_cv_percent_and_nothing_for_a_geometric_mean_or_a_median(ws):
    ledger = Ledger(ws)
    rows = ({"time": 1, "value": 20.0, "spread": 15.0, "spread_kind": "CV%", "n": 8},
            {"time": 2, "value": 10.0, "spread": 1.5, "spread_kind": "SE", "n": 8, "statistic": "geometric_mean"},
            {"time": 3, "value": 8.0, "spread": 1.2, "spread_kind": "geoSD", "statistic": "geometric_mean"},
            {"time": 4, "value": 6.0, "spread": 22.0, "spread_kind": "geoCV%", "n": 8, "statistic": "geometric_mean"},
            {"time": 5, "value": 4.0, "spread": 0.9, "spread_kind": "SE", "n": 8, "statistic": "median"},
            {"time": 6, "value": 3.0, "spread": 0.4, "spread_kind": "SD", "n": 8})
    record_rows(ledger, sheet="S1", region="rg-0000000001", caption="Study 230-41: Exampleamide plasma", rows=rows,
                constants=STUDY)
    (fact,) = ledger.derive()
    assert fact.compute == SD_FROM_CV and fact.time == 1 and fact.spread == spread.sd_from_cv_percent(15.0, 20.0) == 3.0
    assert fact.n == 8 and fact.statistic == "arithmetic_mean"


def test_a_dose_in_g_or_ug_becomes_a_dose_in_mg(ws):
    ledger = Ledger(ws)
    for i, (dose, unit) in enumerate(((0.5, "g"), (250.0, "µg"), (40.0, "mg"), (2.0, "mg/kg"), (100.0, "ug")), start=1):
        record_rows(ledger, sheet=f"S{i}", region=f"rg-000000000{i}", caption=f"Study 230-5{i}, {dose} {unit}",
                    constants=((("study_id", f"230-5{i}", None)), ("dose", dose, unit)))
    made = sorted(ledger.derive(), key=lambda f: f.value)
    assert [(f.value, f.unit, f.compute) for f in made] == [(0.1, "mg", DOSE_TO_MG), (0.25, "mg", DOSE_TO_MG),
                                                             (500.0, "mg", DOSE_TO_MG)]
    assert DOSE_TO_MG == f"{COMPUTE}/dose_to_mg" and COMPUTE == "compute-1"
    for fact in made:
        (source,) = fact.derived_from
        written = ledger.value(source)
        assert written.field == "dose" and written.unit in ("g", "µg", "ug") and fact.entity == written.entity
        assert ledger.value(fact.id).level == written.level and ledger.value(fact.id).anchor is None


def test_derive_twice_adds_nothing_and_a_value_of_no_study_is_not_derived_from(ws):
    ledger = Ledger(ws)
    workbook = synthetic.messy_workbook()
    for table in ("fasting-metabolite", "fasting-individual"):
        record_table(ledger, workbook, table)
    record_rows(ledger, sheet="S9", region="rg-0000000009", caption="Exampleamide plasma, no study stated",
                rows=({"time": 1, "value": 5.0, "spread": 0.5, "spread_kind": "SE", "n": 6},),
                constants=(("analyte", synthetic.DRUG, None),))
    first = ledger.derive()
    assert first and all(ledger.value(f.id).entity.study is not None for f in first)
    store = IntakeStore(ws)
    head = store.facts.head()
    assert ledger.derive() == [] and store.facts.head() == head
    assert Ledger(ws).derive() == [] and derivations(LedgerView(ws)) == []
    assert store.facts.verify() == []


def test_superseding_an_input_supersedes_its_derived_fact(ws):
    ledger = Ledger(ws)
    rows = ({"time": 1, "value": 12.0, "spread": 1.5, "spread_kind": "SE", "n": 6},
            {"time": 2, "value": 9.0, "spread": 1.0, "spread_kind": "SE", "n": 6})
    record_rows(ledger, sheet="S1", region="rg-0000000001", caption="Study 230-41: Exampleamide plasma", rows=rows,
                constants=STUDY)
    first = {f.time: f for f in ledger.derive()}
    # the table read again under a new mapping version, the SE at 1 h now 1.6: a new extract supersedes the old one
    corrected = ({**rows[0], "spread": 1.6}, rows[1])
    record_rows(ledger, sheet="S1", region="rg-0000000001", caption="Study 230-41: Exampleamide plasma", rows=corrected,
                constants=STUDY, version=2)
    second = {f.time: f for f in ledger.derive()}
    assert set(second) == {1, 2} and second[1].spread == spread.sd_from_se(1.6, 6)
    for time in (1, 2):
        old = ledger.value(first[time].id)
        assert (old.status, old.superseded_by) == ("superseded", second[time].id)
        assert second[time].supersedes == first[time].id
    assert len(_spread_facts(ledger)) == 2
    # a person corrects the mean at 2 h and states no spread: its derived SD has no input left, and is excluded
    point = next(v for v in ledger.values(field="concentration") if v.time == 2)
    ledger.enter(value=9.4, why="the corrected listing", by="u", supersedes=point.id)
    assert ledger.derive() == []
    gone = ledger.value(second[2].id)
    assert gone.status == "excluded" and point.id in gone.status_reason
    assert [f.time for f in _spread_facts(ledger)] == [1]
    # the person corrects it again with a spread: a new SD from the corrected point
    fresh = next(v for v in ledger.values(field="concentration") if v.time == 2 and v.method == "person")
    ledger.enter(value=9.4, spread=1.2, spread_kind="SE", n=6, why="the SE as well", by="u", supersedes=fresh.id)
    (made,) = ledger.derive()
    assert made.time == 2 and made.spread == spread.sd_from_se(1.2, 6) and ledger.value(made.id).level == "person_confirmed"


def test_a_derived_fact_whose_input_comes_back_comes_back_with_it(ws):
    ledger = Ledger(ws)
    record_rows(ledger, sheet="S1", region="rg-0000000001", caption="Study 230-41: Exampleamide plasma", constants=STUDY,
                rows=({"time": 1, "value": 12.0, "spread": 1.5, "spread_kind": "SE", "n": 6},))
    (derived,) = ledger.derive()
    (point,) = [v for v in ledger.values(field="concentration") if not is_spread_fact(v)]
    corrected = ledger.enter(value=12.4, why="a typing error", by="u", supersedes=point.id)
    assert ledger.derive() == [] and ledger.value(derived.id).status == "excluded"
    ledger.exclude(corrected.id, why="the listing was right after all", by="u")      # the correction is undone
    assert ledger.value(point.id).status == "proposed"
    assert ledger.derive() == []                                     # the same SD as before: that fact, not a new one
    assert (ledger.value(derived.id).status, ledger.value(derived.id).spread) == ("proposed", spread.sd_from_se(1.5, 6))
    assert len(_spread_facts(ledger)) == 1


def test_a_derived_number_with_no_finite_form_is_not_derived(ws):
    """An SD that overflows (an SE near the largest float) has no JSON form: nothing is derived, the rest is."""
    ledger = Ledger(ws)
    rows = ({"time": 1, "value": 12.0, "spread": 1.5e308, "spread_kind": "SE", "n": 16},
            {"time": 2, "value": 1.0e10, "spread": 1.0e300, "spread_kind": "CV%", "n": 16},
            {"time": 3, "value": 9.0, "spread": 1.0, "spread_kind": "SE", "n": 16})
    record_rows(ledger, sheet="S1", region="rg-0000000001", caption="Study 230-41: Exampleamide plasma", rows=rows,
                constants=STUDY)
    (fact,) = ledger.derive()
    assert fact.time == 3 and fact.spread == spread.sd_from_se(1.0, 16) == 4.0
    assert ledger.derive() == [] and IntakeStore(ws).facts.verify() == []
