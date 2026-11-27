"""The Data room scored value by value (plan 2026-11-26 §5, §6): its reading in the value scorer's long form, against a
key written from the delivery's own file, through the same scorer as the intake pipeline (D0). The delivery is the
made-up Exampleamide one; no model is called (`synthetic.seed` writes what the agents would have answered)."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

from modeler_project.dataroom import DataRoomStore
from modeler_project.dataroom.reading import read_uploads
from modeler_project.dataroom.scoring import from_dataroom
from modeler_project.dataroom.synthetic import FOLDER, SUBJECTS, TIMES, delivery, seed
from modeler_project.store import FileProjectStore
from modeler_project.value_key import SCHEMA, load_key, write_key
from modeler_project.value_score import main, score
from modeler_project.workspace import Workspace

pytestmark = pytest.mark.req("T-47")
CONC = f"{FOLDER}/Clinical/EX-01 concentrations.tsv"


@pytest.fixture
def room(tmp_path: Path) -> Workspace:
    ws = Workspace(FileProjectStore(tmp_path / "root"), "t1", "p1")
    store = DataRoomStore(ws)
    for name, data in delivery().items():
        store.add_upload(name, data, by="user:m")
    read_uploads(store, use_ocr=False, workers=1)
    seed(store, confirmed=True)
    return ws


def _key_rows(subject: str, *, change: dict[float, str] | None = None) -> list[dict[str, str]]:
    """The key an analyst writes for one subject's concentrations, read here with the csv module from the file itself
    (never through the room), with `change` making some values wrong on purpose."""
    text = delivery()[CONC]
    lines = list(csv.reader(io.StringIO(text.decode() if isinstance(text, bytes) else text), delimiter="\t"))
    header, rows = lines[0], lines[1:]
    out = []
    for row in rows:
        if row[0] != subject:
            continue
        for time, value in zip(header[4:], row[4:], strict=True):
            written = (change or {}).get(float(time), value)
            out.append({"file": CONC.rsplit("/", 1)[1], "study": "EX-01", "arm": row[3], "subject": row[0],
                        "period": row[2], "sequence": row[1], "field": "concentration", "time": time,
                        "time_unit": "h", "value": written, "unit": "ng/mL"})
    return out


def _key(rows: list[dict[str, str]]) -> bytes:
    return write_key({"schema": SCHEMA, "delivery": "exampleamide", "analyst": "test", "date": "2026-11-26",
                      "status": "verified"}, rows)


def test_the_room_gives_every_concentration_pk_parameter_and_dissolution_mean_in_long_form(room):
    got = from_dataroom(room)
    by_field: dict[str, int] = {}
    for e in got:
        by_field[e.field] = by_field.get(e.field, 0) + 1
    assert by_field["concentration"] == len(SUBJECTS) * 2 * len(TIMES)          # one per subject, period and time
    assert by_field["pk.Cmax"] == by_field["pk.tmax"] == by_field["pk.AUC_last"] > 0
    assert by_field["percent_dissolved"] > 0
    one = next(e for e in got if e.field == "concentration" and e.subject == "001" and e.time_min == 60.0)
    assert (one.study, one.unit, one.method) == ("EX-01", "ng/mL", "dataroom") and one.period in ("1", "2")
    assert all(e.statistic == "mean" and e.unit == "%" for e in got if e.field == "percent_dissolved")


def test_a_key_written_from_the_file_scores_found_and_a_changed_value_scores_wrong(room):
    got = from_dataroom(room)
    right = score(load_key(_key(_key_rows("001")), "key.xlsx"), got)
    assert right["totals"]["found"] == len(SUBJECTS[:1]) * 2 * len(TIMES)
    assert right["totals"]["wrong_value"] == right["totals"]["missing"] == 0

    wrong = score(load_key(_key(_key_rows("001", change={2.0: "999"})), "key.xlsx"), got)
    assert wrong["totals"]["wrong_value"] == 2                                   # both periods at 2 h
    assert wrong["totals"]["found"] == right["totals"]["found"] - 2


def test_the_scorer_command_reads_the_room_with_source_dataroom(room, tmp_path, capsys):
    key = tmp_path / "key.xlsx"
    key.write_bytes(_key(_key_rows("002")))
    code = main(["--root", str(tmp_path / "root"), "--project", "p1", "--key", str(key), "--source", "dataroom", "--json"])
    assert code == 0
    import json

    body = json.loads(capsys.readouterr().out)
    assert body["score"]["source"] == "dataroom"
    assert body["score"]["totals"]["found"] == 2 * len(TIMES) and body["score"]["totals"]["missing"] == 0
