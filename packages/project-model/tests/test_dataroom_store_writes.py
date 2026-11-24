"""The Data room's stored answers survive a crash and say what they were made from (plan 2026-11-24 §4): every answer is
written to a temporary file and renamed into place, so a crash while writing leaves the previous answer whole; a review
names the extraction it checked, so a run (or a paused run resumed) does not check it again."""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

from modeler_intake.room_specs import Extraction
from modeler_project.dataroom import DataRoomStore
from modeler_project.dataroom import store as store_module
from modeler_project.store import FileProjectStore
from modeler_project.workspace import Workspace
from pbpk_domain import atomic_io

pytestmark = pytest.mark.req("T-47")
SHA = "a" * 64


class _NoRename:
    """The atomic writer's `os`, whose rename fails: a crash between the temporary file and its rename."""

    def __getattr__(self, name: str):
        return getattr(os, name)

    @staticmethod
    def replace(_src, _dst):
        raise OSError("the disk went away before the rename")


def _store(tmp_path) -> DataRoomStore:
    return DataRoomStore(Workspace(FileProjectStore(tmp_path), "t1", "p1"))


def test_a_crash_while_an_answer_is_written_leaves_the_previous_answer_whole(tmp_path, monkeypatch):
    store = _store(tmp_path)
    store.put_extraction(Extraction(file="conc.tsv"), SHA, agent={"agent": "A8", "model": "first"})
    path = store.base / "extractions" / f"{SHA}.json"
    before = path.read_bytes()
    monkeypatch.setattr(atomic_io, "os", _NoRename())
    with pytest.raises(OSError, match="before the rename"):
        store.put_extraction(Extraction(file="conc.tsv", not_found=["A-01"]), SHA, agent={"agent": "A8", "model": "second"})
    with pytest.raises(OSError):
        store.put_review(SHA, [{"table": 1, "issue": "x"}], agent="A9", extraction=store.extraction_stamp(SHA))
    monkeypatch.undo()
    assert path.read_bytes() == before and store.extraction(SHA)[1]["model"] == "first"
    assert sorted(p.name for p in path.parent.iterdir()) == [f"{SHA}.json"]          # no half-written file left over
    assert store.review(SHA) is None


def test_the_store_writes_no_answer_in_place():
    tree = ast.parse(Path(store_module.__file__).read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
    assert not [n.func.attr for n in calls if n.func.attr in ("write_text", "write_bytes")]
    opened = [ast.unparse(n.args[0]) for n in calls if n.func.attr == "open" and n.args]
    assert opened == ["'a'"]                          # only the append-only logs, under their lock


def test_a_review_stands_while_the_extraction_it_checked_does(tmp_path):
    store = _store(tmp_path)
    assert not store.review_current(SHA) and store.extraction_stamp(SHA) == ""
    store.put_extraction(Extraction(file="conc.tsv"), SHA, agent={"agent": "A8"})
    store.put_review(SHA, [], agent="A9", extraction=store.extraction_stamp(SHA))
    assert store.review_current(SHA)
    store.put_extraction(Extraction(file="conc.tsv", not_found=["A-01"]), SHA, agent={"agent": "A8"})
    assert not store.review_current(SHA)                                  # made again: checked again
    store.put_review(SHA, [], agent="A9")                                 # a review kept before reviews named theirs
    assert not store.review_current(SHA)
