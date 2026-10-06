"""Atomic writes: a reader sees the previous complete document or the new one, never a partial one."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

from pbpk_domain.atomic_io import atomic_output, atomic_write_bytes, atomic_write_text


def test_a_concurrent_reader_never_sees_a_partial_document(tmp_path: Path) -> None:
    """The T-56 kit failure: the API read campaigns.json while the runner rewrote it (JSONDecodeError)."""
    path = tmp_path / "campaigns.json"
    atomic_write_text(path, json.dumps({"campaigns": [], "n": -1}))
    stop = threading.Event()
    bad: list[str] = []

    def reader() -> None:
        while not stop.is_set():
            text = path.read_text(encoding="utf-8")
            try:
                json.loads(text)
            except json.JSONDecodeError:
                bad.append(text[:40])

    thread = threading.Thread(target=reader)
    thread.start()
    try:
        for n in range(400):  # large documents make a partial read likely with a plain write_text
            atomic_write_text(path, json.dumps({"campaigns": [{"id": "c", "rounds": list(range(2000))}], "n": n}))
    finally:
        stop.set()
        thread.join()
    assert not bad, f"{len(bad)} partial reads, e.g. {bad[0]!r}"
    assert json.loads(path.read_text())["n"] == 399


def test_a_failed_write_leaves_the_previous_file_and_no_temporary(tmp_path: Path) -> None:
    path = tmp_path / "package.json"
    atomic_write_text(path, '{"exportable": true}')
    with pytest.raises(RuntimeError), atomic_output(path) as tmp:
        tmp.write_text("partial", encoding="utf-8")
        raise RuntimeError("the renderer failed")
    assert path.read_text() == '{"exportable": true}'
    assert [p.name for p in tmp_path.iterdir()] == ["package.json"]  # the temporary file was removed


def test_the_replaced_file_has_the_mode_a_plain_write_gives(tmp_path: Path) -> None:
    """mkstemp creates 0600; the swapped-in file must stay readable as a normally written one would be."""
    plain = tmp_path / "plain.json"
    plain.write_bytes(b"{}")
    atomic_write_bytes(tmp_path / "atomic.json", b"{}")
    assert os.stat(tmp_path / "atomic.json").st_mode & 0o777 == os.stat(plain).st_mode & 0o777


def test_missing_directories_are_created(tmp_path: Path) -> None:
    atomic_write_bytes(tmp_path / "a" / "b" / "evidence.json", b"[]")
    assert (tmp_path / "a" / "b" / "evidence.json").read_bytes() == b"[]"
