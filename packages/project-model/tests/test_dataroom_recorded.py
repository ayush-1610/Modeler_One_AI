"""T-47: a real model's answers on the synthetic delivery, recorded once and replayed through code's checks (plan
2026-11-21 v2 §9 "Proof built in"; the continuation package's open item: an anonymized fixture with recorded answers).

`fixtures/dataroom/exampleamide-recorded.json` holds what every Data room agent (A6-A10) submitted for the made-up
Exampleamide delivery (`modeler_project.dataroom.synthetic`), answered by Nemotron Ultra on NVIDIA's API catalog on
2026-11-22. No model is called here: the answers are put in a store, and code reads every value from the files and
checks every quote, as in a run. The room they give is compared with the room from the hand-written answers (`seed`):
the numbers a model reaches through code must be the same, and what the model missed must be said, not hidden.

Replaying them found four faults, each fixed in code and tested in `test_dataroom.py`: "BLQ" listed both as a missing
sample and below the LLOQ, treatment codes "meaning" themselves with a product claimed from a data row (a data row is
no statement: such a quote is refused), a method's conditions typed by the agent, and the agent's note deciding bound
or unbound (fu 0.97 instead of 0.03).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from modeler_intake.room_specs import Extraction, FileTriage, QuestionCard
from modeler_project.dataroom import DataRoomStore, room_view
from modeler_project.dataroom.reading import read_uploads
from modeler_project.dataroom.synthetic import delivery, seed
from modeler_project.store import FileProjectStore
from modeler_project.workspace import Workspace

pytestmark = pytest.mark.req("T-47")
RECORDED = json.loads((Path(__file__).parent / "fixtures" / "dataroom" / "exampleamide-recorded.json").read_text())


def _room(root: Path, fill):
    store = DataRoomStore(Workspace(FileProjectStore(root), "t1", "p1"))
    for name, data in delivery().items():
        store.add_upload(name, data, by="test")
    read_uploads(store, use_ocr=False, workers=1)
    fill(store)
    return room_view(store)


def _recorded(store: DataRoomStore) -> None:
    files = {f.path: f for f in store.files()}
    store.set_question(QuestionCard.model_validate(RECORDED["question"]), by="recorded", confirmed=True)
    for path, triage in RECORDED["triage"].items():
        store.put_triage(FileTriage.model_validate(triage), files[path].sha256)
    for path, extraction in RECORDED["extractions"].items():
        store.put_extraction(Extraction.model_validate(extraction), files[path].sha256,
                             agent={"agent": "A8", "model": RECORDED["model"], "prompt": "recorded"})


@pytest.fixture(scope="module")
def rooms(tmp_path_factory):
    key = _room(tmp_path_factory.mktemp("key"), lambda s: seed(s, confirmed=True))
    got = _room(tmp_path_factory.mktemp("recorded"), _recorded)
    return key, got


def test_the_recorded_answers_give_the_same_study_sets_exposures_and_arms(rooms):
    key, got = rooms
    (k,), (g,) = key.studies, got.studies
    assert {s.name: s.subjects for s in g.sets} == {s.name: s.subjects for s in k.sets}
    assert {(e.treatment, e.metric, e.statistic): e.value for e in g.exposures} == pytest.approx(
        {(e.treatment, e.metric, e.statistic): e.value for e in k.exposures})
    assert [(a.treatment, a.role, a.product) for a in g.arms] == [(a.treatment, a.role, a.product) for a in k.arms]
    assert set(g.excluded) == set(k.excluded) == {"3", "4"}


def test_the_recorded_answers_give_the_same_dissolution_solubility_and_compound_values(rooms):
    key, got = rooms
    assert {(d.batch, d.ph): d.mean for d in got.dissolution} == {(d.batch, d.ph): d.mean for d in key.dissolution}
    assert {s.ph: s.solubility_mg_ml for s in got.solubility} == {s.ph: s.solubility_mg_ml for s in key.solubility}
    compound = {r.name: r.value for r in got.inputs if r.block == "compound"}
    assert compound == {r.name: r.value for r in key.inputs if r.block == "compound"}
    assert compound["bind.fu"] == 0.03                       # from "Plasma protein binding: 97 %", the note aside
    def fits(view):
        return sorted((r.label, str(r.value)) for r in view.inputs if r.block == "formulation")

    assert fits(got) == fits(key)                           # the same Weibull fits, product by product


def test_what_the_model_missed_or_got_wrong_is_said_not_hidden(rooms):
    _key, got = rooms
    codes = [p.code for p in got.problems]
    # its own descriptions, refused with the reason: BLQ listed as missing too, and codes "meaning" themselves
    assert "TOKEN_BOTH_MISSING_AND_BLQ" in codes
    refused = [p.message for p in got.problems if p.code == "FACT_REFUSED"]
    # every refusal is a quote of a table's line (per-subject demographics, mean rows, codes "meaning" themselves): the
    # tables' descriptions give those values, and the comparisons above show nothing was lost
    assert refused and all("a line of a data table" in m for m in refused)
    assert sum(m.startswith("a treatment code") for m in refused) == 4
    # it did not link the batches to their products: each release is the batch's, and the send says so
    assert {r.owner for r in got.inputs if r.block == "formulation"} == {"LOT-R", "LOT-T", "LOT-X"}
    assert not got.f2                                       # with no products, no test is compared with its reference


def test_the_answer_key_scores_itself_full_and_the_recorded_run_says_what_it_missed(rooms):
    """`synthetic.score_room`, the calibration's answer key (deploy/dev/calibrate_dataroom.py): the key's own room scores
    every row OK; Nemotron's recorded run is the free model's baseline on the same 60 rows: 51 OK, 4 wrong (the
    regulator, the design, the meal times, the population), 5 missing (the three f2 pairs, molar mass and pKa)."""
    from modeler_project.dataroom.synthetic import score_room

    key, got = rooms
    own = score_room(key, key)
    assert own and all(status == "OK" for status, *_ in own)
    rows = score_room(got, key)
    assert len(rows) == len(own)
    counts = {s: sum(r[0] == s for r in rows) for s in ("OK", "WRONG", "MISSING")}
    assert len(rows) == 60 and counts["OK"] >= 51           # a change that loses a value the recorded run had shows here
