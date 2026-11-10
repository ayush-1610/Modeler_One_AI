"""The project's reading queue (plan 2026-11-10, R1): every file to read is kept until it is read."""

from __future__ import annotations

import pytest

from modeler_project import FileProjectStore, Workspace
from modeler_project.reading_queue import KEEP_FINISHED, MAX_ATTEMPTS, ReadingQueue

pytestmark = pytest.mark.req("T-47")


def _queue(tmp_path) -> ReadingQueue:
    return ReadingQueue(Workspace(FileProjectStore(tmp_path), "t1", "p1"))


def test_files_are_queued_in_order_once_and_taken_one_after_the_other(tmp_path):
    q = _queue(tmp_path)
    assert q.available and not q.pending() and q.take() is None
    added = q.add([("file-a", "a.pdf"), ("file-b", "b.xlsx"), ("file-a", "a.pdf")], task="arrival", by="u1")
    assert [i.sid for i in added] == ["file-a", "file-b"]
    assert q.add([("file-a", "a.pdf")], task="arrival", by="u1") == []          # waiting already: not twice
    assert [i.sid for i in q.add([("file-a", "a.pdf")], task="read", by="u1")] == ["file-a"]   # a person's Read is its own
    first = q.take()
    assert first is not None and first.sid == "file-a" and first.state == "reading" and first.attempts == 1
    assert q.add([("file-a", "a.pdf")], task="arrival", by="u1") == []          # being read: not twice either
    q.finish(first.id, "done", note="read", run_ids=("ar_1",), found={"datasets": 2})
    done = next(i for i in q.items() if i.id == first.id)
    assert done.state == "done" and done.found == {"datasets": 2} and done.run_ids == ("ar_1",) and done.finished_at
    assert q.add([("file-a", "a.pdf")], task="arrival", by="u1")               # read: it can be queued again
    assert q.take().sid == "file-b" and q.pending()


def test_an_item_left_reading_by_a_stopped_worker_is_put_back_then_failed(tmp_path):
    q = _queue(tmp_path)
    q.add([("file-a", "a.pdf")], task="arrival", by="u1")
    for _ in range(MAX_ATTEMPTS - 1):
        assert q.take() is not None
        assert q.recover() == 1                       # the worker stopped while reading it: back in the queue
        assert q.items()[0].state == "queued"
    assert q.take() is not None
    assert q.recover() == 0
    failed = q.items()[0]
    assert failed.state == "failed" and "read it again" in failed.note and not q.pending()


def test_only_the_most_recent_finished_items_are_kept(tmp_path, monkeypatch):
    from modeler_project import reading_queue

    monkeypatch.setattr(reading_queue, "KEEP_FINISHED", 3)
    q = _queue(tmp_path)
    q.add([(f"file-{n}", f"{n}.pdf") for n in range(5)], task="arrival", by="u1")
    q.add([("file-waiting", "w.pdf")], task="read", by="u1")
    for _ in range(5):
        q.finish(q.take().id, "done")
    kept = q.items()
    assert [i.sid for i in kept] == ["file-2", "file-3", "file-4", "file-waiting"]   # a waiting item is never dropped
    assert KEEP_FINISHED >= 100


def test_a_store_without_a_root_keeps_no_queue():
    class Bare:
        pass

    q = ReadingQueue(Workspace(Bare(), "t1", "p1"))  # type: ignore[arg-type]
    assert not q.available and q.items() == [] and q.recover() == 0


def test_a_persons_read_waits_behind_the_same_read_being_read_and_a_documents_read_covers_its_arrival(tmp_path):
    # the R1 review: a Read being read fixed its sheets when it started, so the same Read asked again is queued; a
    # document's Read does what its waiting arrival would, so the arrival is dropped (read once)
    q = _queue(tmp_path)
    q.add([("file-a", "a.xlsx")], task="read", by="u1")
    assert q.take() is not None
    assert [i.state for i in q.add([("file-a", "a.xlsx")], task="read", by="u1")] == ["queued"]
    q.add([("file-d", "d.pdf")], task="arrival", by="code")
    q.add([("file-d", "d.pdf")], task="read", by="u1", supersede_arrival=True)
    assert [(i.sid, i.task) for i in q.items() if i.state == "queued"] == [("file-a", "read"), ("file-d", "read")]
