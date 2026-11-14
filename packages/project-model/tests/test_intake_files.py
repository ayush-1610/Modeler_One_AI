"""T-47, T-05, F-404: every arriving file is stored, then recorded in its delivery (contracts §5, §6.5; build W).

The bytes are in the project store before the line that names them; the same bytes in a later delivery are a repeat;
a ZIP's member names its container; what today's reader did with a file is folded into its record; the log is a hash
chain that finds an edited line."""

from __future__ import annotations

import hashlib
import json
import threading

import pytest

from modeler_intake.source_model import ContainerRef
from modeler_project import FileProjectStore, Workspace, intake_files
from modeler_project.intake_store import IntakeStore

pytestmark = pytest.mark.req("T-47", "T-05", "F-404")


@pytest.fixture
def ws(tmp_path) -> Workspace:
    return Workspace(FileProjectStore(tmp_path), "t1", "p1")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_the_bytes_are_stored_before_the_line_that_names_them(ws, monkeypatch):
    data = b"subject;time;conc\n1;0,5;12,1\n"
    delivery = intake_files.open_delivery(ws, by="u1")
    assert delivery == "dl-1" and intake_files.deliveries(ws)[0]["by"] == "u1"
    store = IntakeStore(ws)
    seen: list[bool] = []
    append_if = store.files.append_if.__func__        # the log every IntakeStore of this project writes

    def watched(log, decide):
        seen.append(ws.store.blob_path(ws.tenant_id, ws.project_id, _sha(data)) is not None)
        return append_if(log, decide)

    monkeypatch.setattr(type(store.files), "append_if", watched)
    record = intake_files.record_arrival(ws, data, "listing.csv", delivery=delivery, by="u1")
    assert seen == [True]                       # stored when the line was decided
    assert record.file_id == f"fl-{_sha(data)[:12]}" and record.size_bytes == len(data) and not record.repeat
    assert record.delivery == delivery and record.name == "listing.csv" and record.container is None
    assert ws.store.blob_path(ws.tenant_id, ws.project_id, record.sha256).read_bytes() == data
    assert intake_files.files(ws) == [record]


def test_a_delivery_must_be_opened_first(ws):
    with pytest.raises(KeyError):
        intake_files.record_arrival(ws, b"x", "a.txt", delivery="dl-9", by="u1")


def test_the_same_bytes_again_are_one_line_per_delivery_and_a_repeat_in_a_later_one(ws):
    data = b"the same bytes"
    first = intake_files.open_delivery(ws, by="u1")
    a = intake_files.record_arrival(ws, data, "a.txt", delivery=first, by="u1")
    again = intake_files.record_arrival(ws, data, "a-copy.txt", delivery=first, by="u1")
    assert again == a                            # the same request: nothing written
    second = intake_files.open_delivery(ws, by="u2")
    repeat = intake_files.record_arrival(ws, data, "a.txt", delivery=second, by="u2")
    assert repeat.repeat and repeat.delivery == second and repeat.file_id == a.file_id
    assert [r.delivery for r in intake_files.files(ws)] == [first, second]
    assert intake_files.file_record(ws, a.sha256, delivery=first) == a
    assert intake_files.file_record(ws, a.sha256) == repeat


def test_a_member_names_its_container(ws):
    delivery = intake_files.open_delivery(ws, by="u1")
    archive = intake_files.record_arrival(ws, b"PK-not-really", "delivery.zip", delivery=delivery, by="u1")
    box = ContainerRef(sha256=archive.sha256, name="delivery.zip", member="reports/listing.csv")
    member = intake_files.record_arrival(ws, b"a;b\n1;2\n", "listing.csv", delivery=delivery, by="u1", container=box)
    assert member.container == box and not member.repeat
    # the same bytes loose in the same delivery: another line (another container), marked a repeat
    loose = intake_files.record_arrival(ws, b"a;b\n1;2\n", "listing.csv", delivery=delivery, by="u1")
    assert loose.container is None and loose.repeat
    assert len(intake_files.files(ws)) == 3


def test_what_todays_reader_did_is_folded_into_the_files_latest_record(ws):
    delivery = intake_files.open_delivery(ws, by="u1")
    ok = intake_files.record_arrival(ws, b"%PDF-1.4 a", "a.pdf", delivery=delivery, by="u1")
    broken = intake_files.record_arrival(ws, b"not a pdf", "broken.pdf", delivery=delivery, by="u1")
    intake_files.note_legacy(ws, ok.file_id, sid="cs-1", refusal=None)
    intake_files.note_legacy(ws, broken.file_id, sid=None, refusal="broken.pdf is not a PDF file")
    by_name = {r.name: r for r in intake_files.files(ws)}
    assert (by_name["a.pdf"].legacy_sid, by_name["a.pdf"].legacy_refusal) == ("cs-1", None)
    assert (by_name["broken.pdf"].legacy_sid, by_name["broken.pdf"].legacy_refusal) == (None, "broken.pdf is not a PDF file")
    # the file line itself never carries it: the fold does
    lines = IntakeStore(ws).files.entries("file")
    assert all(line.body["legacy_sid"] is None and line.body["legacy_refusal"] is None for line in lines)


def test_stored_files_are_recorded_under_one_delivery_once(ws):
    a = ws.store.put_blob(ws.tenant_id, ws.project_id, b"one")
    b = ws.store.put_blob(ws.tenant_id, ws.project_id, b"two")
    made = intake_files.record_stored(ws, [(a, "one.txt"), (b, "two.txt"), ("0" * 64, "gone.txt")], by="code")
    assert [r.name for r in made] == ["one.txt", "two.txt"] and len({r.delivery for r in made}) == 1
    assert intake_files.record_stored(ws, [(a, "one.txt"), (b, "two.txt")], by="code") == made
    assert len(intake_files.deliveries(ws)) == 1 and len(intake_files.files(ws)) == 2


def test_two_threads_recording_the_same_bytes_write_one_line(ws):
    delivery = intake_files.open_delivery(ws, by="u1")
    out = []
    threads = [threading.Thread(target=lambda: out.append(intake_files.record_arrival(ws, b"x" * 1000, "x.txt",
                                                                                      delivery=delivery, by="u1")))
               for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len({r.model_dump_json() for r in out}) == 1 and len(intake_files.files(ws)) == 1


def test_the_files_log_is_a_hash_chain_that_finds_an_edited_line(ws):
    delivery = intake_files.open_delivery(ws, by="u1")
    record = intake_files.record_arrival(ws, b"abc", "a.txt", delivery=delivery, by="u1")
    intake_files.note_legacy(ws, record.file_id, sid=None, refusal="unsupported")
    log = IntakeStore(ws).files
    assert log.verify() == [] and [e.kind for e in log.entries()] == ["delivery", "file", "legacy"]
    lines = log.path.read_text(encoding="utf-8").splitlines()
    edited = json.loads(lines[1])
    edited["body"]["name"] = "b.txt"
    lines[1] = json.dumps(edited, ensure_ascii=False, separators=(",", ":"))
    log.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert [(p.seq, p.problem) for p in log.verify()] == [(2, "hash")]


def test_a_store_with_no_file_root_records_nothing():
    class NoRoot:
        pass

    ws = Workspace(NoRoot(), "t1", "p1")  # type: ignore[arg-type]
    assert intake_files.files(ws) == [] and intake_files.deliveries(ws) == []
    with pytest.raises(RuntimeError):
        intake_files.open_delivery(ws, by="u1")
