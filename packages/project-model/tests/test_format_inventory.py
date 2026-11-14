"""The format inventory CLI over a read root (contracts §6.1, §8.4): it reads the names of the files from
`intake/files.jsonl` and the DOCUMENT artifacts, counts them from their blobs, prints the report and writes nothing."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest

from modeler_intake import synthetic
from modeler_intake.source import inventory, zip_members
from modeler_intake.source_model import ContainerRef
from modeler_project import FileProjectStore, Workspace
from modeler_project.documents import DocumentLibrary
from modeler_project.format_inventory import main, stored_files
from modeler_project.intake_records import FileRecord
from modeler_project.intake_store import ChainedLog

pytestmark = pytest.mark.req("T-47")


def _record(data: bytes, name: str, at: str, container: ContainerRef | None = None) -> dict:
    sha = hashlib.sha256(data).hexdigest()
    return FileRecord(file_id="fl-" + sha[:12], sha256=sha, name=name, size_bytes=len(data), delivery="dl-1", by="u1",
                      at=at, container=container).model_dump(mode="json")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A store with two projects: a library document in one, intake files (one of them the same bytes, one with its
    bytes missing, one old) in the other."""
    store = FileProjectStore(tmp_path / "root")
    report, listing, word = synthetic.pdf_report(), synthetic.delimited(), synthetic.word_report()
    DocumentLibrary(Workspace(store, "t1", "p1")).add(report.data, report.name, role="client_file", by="u1")
    log = ChainedLog(tmp_path / "root" / "t1" / "projects" / "p2" / "intake" / "files.jsonl")
    for file, at in ((listing, "2026-11-10T09:00:00.000Z"), (report, "2026-11-10T09:00:01.000Z"),
                     (word, "2026-01-02T10:00:00.000Z")):
        store.put_blob("t1", "p2", file.data)
        log.append("file", _record(file.data, file.name, at))
    log.append("file", _record(b"never stored", "lost.csv", "2026-11-11T08:00:00.000Z"))
    return tmp_path / "root"


def _snapshot(root: Path) -> dict[str, tuple[int, int, str]]:
    return {str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
            for p in sorted(root.rglob("*")) if p.is_file()}


def test_the_cli_prints_the_report_and_writes_nothing(root: Path, capsys):
    before = _snapshot(root)
    assert main(["--root", str(root)]) == 0
    out, err = capsys.readouterr()
    assert _snapshot(root) == before                                                        # nothing written, nothing touched
    assert "files: 3 (and 0 inside ZIPs)" in out and "PDF: 1 native, 0 scanned, 0 mixed" in out
    assert "documents with figures: 1" in out
    assert "bytes missing, not counted: t1/p2: lost.csv" in err


def test_the_json_report_is_the_inventory_of_the_stored_files_each_sha_once(root: Path, capsys):
    assert main(["--root", str(root), "--tenant", "t1", "--json"]) == 0
    printed = json.loads(capsys.readouterr().out)
    files = list(stored_files(root))
    assert sorted(name for name, _data in files) == ["concentrations.csv", "design-report.docx", "study-report.pdf"]
    assert printed == inventory(files).model_dump(mode="json")
    assert printed["by_extension"] == {".csv": 1, ".docx": 1, ".pdf": 1} and printed["files"] == 3


def test_since_keeps_the_files_that_arrived_on_or_after_a_date(root: Path, capsys):
    assert sorted(n for n, _d in stored_files(root, since=date(2026, 11, 1))) == ["concentrations.csv", "study-report.pdf"]
    assert main(["--root", str(root), "--since", "2026-11-01", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["files"] == 2


def test_out_writes_the_report_outside_the_root_and_never_inside(root: Path, tmp_path: Path, capsys):
    before = _snapshot(root)
    assert main(["--root", str(root), "--out", str(root / "t1" / "report.txt")]) == 2
    assert _snapshot(root) == before and "inside the root" in capsys.readouterr().err
    target = tmp_path / "inventory.txt"
    assert main(["--root", str(root), "--out", str(target)]) == 0
    assert target.read_text(encoding="utf-8").startswith("files: 3")


def test_a_missing_root_or_tenant_is_refused(tmp_path: Path, capsys):
    assert main(["--root", str(tmp_path / "nowhere")]) == 2
    (tmp_path / "empty").mkdir()
    assert main(["--root", str(tmp_path / "empty"), "--tenant", "t9"]) == 2
    assert main(["--root", str(tmp_path / "empty")]) == 0 and "files: 0" in capsys.readouterr().out


def test_a_zip_member_recorded_beside_its_zip_is_counted_once_inside_it(tmp_path: Path, capsys):
    store = FileProjectStore(tmp_path / "root")
    bundle = synthetic.zipped(synthetic.delimited(), synthetic.word_report(), name="batch.zip")
    log = ChainedLog(tmp_path / "root" / "t1" / "projects" / "p3" / "intake" / "files.jsonl")
    at = "2026-11-10T09:00:00.000Z"
    store.put_blob("t1", "p3", bundle.data)
    log.append("file", _record(bundle.data, bundle.name, at))                    # the ZIP first, as W records it
    sha = hashlib.sha256(bundle.data).hexdigest()
    for member, data in zip_members(bundle.data, bundle.name):
        store.put_blob("t1", "p3", data)
        log.append("file", _record(data, f"{bundle.name}/{member}", at, ContainerRef(sha256=sha, name=bundle.name,
                                                                                    member=member)))
    files = list(stored_files(tmp_path / "root"))
    assert [name for name, _data in files] == ["batch.zip"]
    assert main(["--root", str(tmp_path / "root"), "--json"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert (printed["files"], printed["zip_members"], printed["by_extension"]) == (1, 2, {".csv": 1, ".docx": 1,
                                                                                       ".zip": 1})
