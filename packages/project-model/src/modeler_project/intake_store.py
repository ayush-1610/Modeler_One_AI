"""The intake's stores (contracts §5): hash-chained logs beside the artifacts, the source cache, extracts, coverage.

Everything lives under `<root>/<tenant>/projects/<project>/intake/`; client bytes stay where they are
(`ws.store.put_blob`). A store with no file root has no intake store (`available` is False: the pipeline is off, as the
reading queue is).

    files.jsonl              delivery, file, legacy                     (W)
    runs.jsonl               RunRecord lines                            (W)
    mappings.jsonl           entry, decision                            (D3)
    ledger/facts.jsonl       fact, extract, status                      (D4)
    ledger/entities.jsonl    entity, alias, merge                       (D4)
    ledger/extracts/<id>.json.gz   TableExtract, content-addressed, write-once
    review.jsonl             override, disposition, choice, link, assignment, region, spot_draw, spot_check,
                             confirmation, landed                        (D6)
    source/<sha256>/<parser>@<parser_version>.json.gz    SourceDocument cache
    coverage/<sha256>.json   the current FileCoverage

**A log line** is `{"seq", "at", "kind", "body", "prev", "hash"}` with hash = sha256(prev + "\\n" +
canonical({"seq", "at", "kind", "body"})), the first prev 64 zeros. `append*` holds `file_lock(path)` (an flock on
`<path>.lock`, across threads and processes, NOT reentrant: never append to a log from inside its own append), re-reads
the head, writes whole lines, flushes and fsyncs. A crash can leave one torn last line, a fragment with no newline:
`verify` reports it, `entries` ignores it, and the next append truncates it under the lock (it was never acknowledged).
A whole line (one that ends in a newline) that is not a log line is never torn, it is corruption: `verify` reports
"hash", `entries` raises and `append` refuses. A changed, removed or reordered line breaks `verify`. A batch
(`append_many`, the rows of one `append_if`) is written with one write and is not atomic: a crash can leave its first
lines whole and cut a later one, and the whole lines stand. Writers are idempotent (`append_if` decides from what is
there), so a retry completes the batch. The line stored is exactly the canonical body that is hashed; a body with a
non-finite number is refused before anything is written (ValueError).

**No path is built from input.** Every id and sha256 is checked with `anchors.check_id` before use; `source` opens only a
(parser, version) pair `source_versions` lists, `extract` only an id an `extract` line of facts.jsonl names, `coverage`
only a sha256 a `file` line of files.jsonl names; anything else is a KeyError (None for `source` and `coverage`).
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import re
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from modeler_intake.anchors import AnchorError, canonical, check_id, sha256_of
from modeler_intake.source_model import SourceDocument
from modeler_project.intake_records import FileCoverage
from modeler_project.ledger_models import ChainHead, TableExtract
from modeler_project.workspace import Workspace
from pbpk_domain.atomic_io import atomic_write_bytes, file_lock

log = logging.getLogger(__name__)

GENESIS = "0" * 64
_PARSER = re.compile(r"[a-z0-9_]+")
_VERSION = re.compile(r"[A-Za-z0-9.+_-]+")
_SOURCE_FILE = re.compile(r"([a-z0-9_]+)@([A-Za-z0-9.+_-]+)\.json\.gz")


class ChainEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    seq: int
    at: str
    kind: str
    body: dict[str, Any]
    prev: str
    hash: str


class ChainProblem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    seq: int
    problem: Literal["hash", "prev", "seq", "torn_tail"]


Row = tuple[str, dict[str, Any] | Callable[[int], dict[str, Any]]]     # (kind, body or a function of the line's seq)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _chain_hash(prev: str, seq: int, at: str, kind: str, body: dict[str, Any]) -> str:
    """The hash a line carries: sha256(prev + "\\n" + canonical({"seq", "at", "kind", "body"}))."""
    return hashlib.sha256((prev + "\n" + canonical({"seq": seq, "at": at, "kind": kind, "body": body})).encode("utf-8")).hexdigest()


class ChainedLog:
    """An append-only, hash-chained JSON-lines log (see the module docstring). With no path (a store with no root) it
    reads as empty and refuses to append."""

    def __init__(self, path: Path | None):
        self.path = path

    # --- reading ---------------------------------------------------------------------------------------------------

    def _lines(self) -> tuple[list[str], bool]:
        """The whole lines (each ended by a newline) and whether a torn fragment (no newline) follows them."""
        if self.path is None or not self.path.exists():
            return [], False
        raw = self.path.read_bytes().decode("utf-8", errors="replace")
        parts = raw.split("\n")
        tail = parts.pop()                    # "" when the file ends with a newline
        return [p for p in parts if p.strip()], bool(tail.strip())

    def entries(self, kind: str | None = None) -> list[ChainEntry]:
        """Every line (of `kind`), in order; read without the lock; a torn last line is ignored. A line inside the log
        that is not a line of this format is corruption, and raises."""
        lines, _torn = self._lines()
        out = []
        for number, line in enumerate(lines, start=1):
            try:
                entry = ChainEntry.model_validate_json(line)
            except ValueError as exc:
                raise ValueError(f"{self.path}: line {number} is not a log line ({exc.__class__.__name__})") from exc
            if kind is None or entry.kind == kind:
                out.append(entry)
        return out

    def head(self) -> ChainHead:
        """The last line's (seq, hash); seq 0 and 64 zeros when the log is empty."""
        entries = self.entries()
        return ChainHead(seq=entries[-1].seq, hash=entries[-1].hash) if entries else ChainHead(seq=0, hash=GENESIS)

    def verify(self) -> list[ChainProblem]:
        """Every break of the chain: a line whose hash does not match its content, whose prev is not the hash before it,
        whose seq is not the next, and a torn last line. Empty when the log is whole."""
        lines, torn = self._lines()
        problems: list[ChainProblem] = []
        prev, expected = GENESIS, 1
        for line in lines:
            try:
                entry = ChainEntry.model_validate_json(line)
            except ValueError:
                problems.append(ChainProblem(seq=expected, problem="hash"))
                expected += 1
                continue
            if entry.seq != expected:
                problems.append(ChainProblem(seq=entry.seq, problem="seq"))
            if entry.prev != prev:
                problems.append(ChainProblem(seq=entry.seq, problem="prev"))
            if _chain_hash(entry.prev, entry.seq, entry.at, entry.kind, entry.body) != entry.hash:
                problems.append(ChainProblem(seq=entry.seq, problem="hash"))
            prev, expected = entry.hash, entry.seq + 1
        if torn:
            problems.append(ChainProblem(seq=expected, problem="torn_tail"))
        return problems

    # --- appending -------------------------------------------------------------------------------------------------

    def _repair(self) -> list[ChainEntry]:
        """Under the lock: truncate a torn last fragment (never acknowledged) and return the entries. A whole line that
        is not a log line is corruption: `entries` raises, and nothing is appended to a corrupt log."""
        assert self.path is not None
        _lines, torn = self._lines()
        if torn:
            data = self.path.read_bytes()
            cut = data.rfind(b"\n") + 1                  # the end of the last whole line (0: none)
            log.warning("intake log %s: a torn last line (%d bytes) was removed before appending", self.path, len(data) - cut)
            with open(self.path, "r+b") as handle:
                handle.truncate(cut)
                handle.flush()
                os.fsync(handle.fileno())
        return self.entries()

    def _write(self, entries: list[ChainEntry], rows: Sequence[Row]) -> list[ChainEntry]:
        assert self.path is not None
        last = entries[-1] if entries else None
        prev, seq = (last.hash, last.seq) if last else (GENESIS, 0)
        written: list[ChainEntry] = []
        lines = []
        for kind, body in rows:
            seq += 1
            given = body(seq) if callable(body) else body
            data = json.loads(canonical(given))           # what is stored is exactly what is hashed (no NaN: ValueError)
            if not isinstance(data, dict):
                raise TypeError(f"a {kind} line's body is a JSON object, not {type(data).__name__}")
            at = _now()
            digest = _chain_hash(prev, seq, at, kind, data)
            written.append(ChainEntry(seq=seq, at=at, kind=kind, body=data, prev=prev, hash=digest))
            line = {"seq": seq, "at": at, "kind": kind, "body": data, "prev": prev, "hash": digest}
            lines.append(json.dumps(line, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")
            prev = digest
        if lines:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "ab") as handle:
                handle.write("".join(lines).encode("utf-8"))
                handle.flush()
                os.fsync(handle.fileno())
        return written

    def _locked(self) -> Any:
        if self.path is None:
            raise RuntimeError("the project store has no file root: the intake pipeline is off")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        return file_lock(self.path)

    def append(self, kind: str, body: dict[str, Any] | Callable[[int], dict[str, Any]]) -> ChainEntry:
        """Append one line; a callable body gets the line's seq (for an id "<prefix>-<seq>")."""
        return self.append_many([(kind, body)])[0]

    def append_many(self, rows: Sequence[Row]) -> list[ChainEntry]:
        """Append several lines at once, in order, under one lock."""
        with self._locked():
            return self._write(self._repair(), rows)

    def append_if(self, decide: Callable[[list[ChainEntry]], Sequence[Row]]) -> list[ChainEntry]:
        """Read, decide and append under ONE lock: `decide` gets the current entries and returns the rows to append
        (none: nothing). Every check-then-append uses it. `decide` must not touch the same log."""
        with self._locked():
            entries = self._repair()
            return self._write(entries, decide(entries))


class IntakeStore:
    """The intake's files of one project (see the module docstring)."""

    def __init__(self, ws: Workspace):
        self.ws = ws
        root = getattr(ws.store, "root", None)
        self.available = root is not None
        self.base: Path | None = (Path(root) / ws.tenant_id / "projects" / ws.project_id / "intake") if root is not None else None
        base = self.base
        self.files = ChainedLog(base / "files.jsonl" if base else None)
        self.runs = ChainedLog(base / "runs.jsonl" if base else None)
        self.mappings = ChainedLog(base / "mappings.jsonl" if base else None)
        self.facts = ChainedLog(base / "ledger" / "facts.jsonl" if base else None)
        self.entities = ChainedLog(base / "ledger" / "entities.jsonl" if base else None)
        self.review = ChainedLog(base / "review.jsonl" if base else None)

    def _base(self) -> Path:
        if self.base is None:
            raise RuntimeError("the project store has no file root: the intake pipeline is off")
        return self.base

    # --- the source cache --------------------------------------------------------------------------------------------

    def source_versions(self, sha256: str) -> list[tuple[str, str]]:
        """The (parser, parser version) pairs cached for a file; [] for none (and for a sha256 that is not one)."""
        try:
            check_id("sha256", sha256)
        except AnchorError:
            return []
        if self.base is None:
            return []
        folder = self.base / "source" / sha256
        if not folder.is_dir():
            return []
        found = []
        for path in folder.iterdir():
            match = _SOURCE_FILE.fullmatch(path.name)
            if match is not None:
                found.append((match.group(1), match.group(2)))
        return sorted(found)

    def source(self, sha256: str, parser: str, parser_version: str) -> SourceDocument | None:
        """The cached source model of a file under one parser version; None when not cached (or not an id)."""
        if (parser, parser_version) not in self.source_versions(sha256):
            return None
        path = self._base() / "source" / sha256 / f"{parser}@{parser_version}.json.gz"
        return SourceDocument.model_validate_json(gzip.decompress(path.read_bytes()))

    def put_source(self, doc: SourceDocument) -> str:
        """Cache a source model (atomic write); returns sha256_of(the document)."""
        check_id("sha256", doc.file_sha256)
        if not _PARSER.fullmatch(doc.parser) or not _VERSION.fullmatch(doc.parser_version):
            raise AnchorError(f"not a parser and version: {doc.parser!r} {doc.parser_version!r}")
        text = canonical(doc)
        path = self._base() / "source" / doc.file_sha256 / f"{doc.parser}@{doc.parser_version}.json.gz"
        atomic_write_bytes(path, gzip.compress(text.encode("utf-8"), mtime=0))
        return sha256_of(doc)

    # --- extracts ------------------------------------------------------------------------------------------------------

    def extract(self, extract_id: str) -> TableExtract:
        """An extract an `extract` line of facts.jsonl names; KeyError for any other id."""
        try:
            check_id("extract", extract_id)
        except AnchorError as exc:
            raise KeyError(extract_id) from exc
        if not any(e.body.get("id") == extract_id for e in self.facts.entries("extract")):
            raise KeyError(extract_id)
        return self._extract_file(extract_id)

    def _extract_file(self, extract_id: str) -> TableExtract:
        """The extract file of a checked id that a line names (the ledger's fold has the line already)."""
        check_id("extract", extract_id)
        path = self._base() / "ledger" / "extracts" / f"{extract_id}.json.gz"
        if not path.exists():
            raise KeyError(extract_id)
        return TableExtract.model_validate_json(gzip.decompress(path.read_bytes()))

    def put_extract(self, extract: TableExtract) -> tuple[str, str]:
        """Store an extract by its content (write-once): (extract id, content sha256). Write it before the ledger line
        that names it."""
        check_id("sha256", extract.file_sha256)
        text = canonical(extract)
        content_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
        extract_id = f"tx-{content_sha256[:16]}"
        path = self._base() / "ledger" / "extracts" / f"{extract_id}.json.gz"
        if path.exists():
            stored = gzip.decompress(path.read_bytes()).decode("utf-8")
            if hashlib.sha256(stored.encode("utf-8")).hexdigest() != content_sha256:
                raise ValueError(f"{extract_id}: a stored extract with this id holds other content")
            return extract_id, content_sha256
        atomic_write_bytes(path, gzip.compress(text.encode("utf-8"), mtime=0))
        return extract_id, content_sha256

    # --- coverage ------------------------------------------------------------------------------------------------------

    def coverage(self, sha256: str) -> FileCoverage | None:
        """The current coverage of a file a `file` line of files.jsonl names; None otherwise."""
        try:
            check_id("sha256", sha256)
        except AnchorError:
            return None
        if self.base is None or not any(e.body.get("sha256") == sha256 for e in self.files.entries("file")):
            return None
        path = self.base / "coverage" / f"{sha256}.json"
        return FileCoverage.model_validate_json(path.read_bytes()) if path.exists() else None

    def put_coverage(self, coverage: FileCoverage) -> None:
        sha256 = check_id("sha256", coverage.file.sha256)
        atomic_write_bytes(self._base() / "coverage" / f"{sha256}.json", canonical(coverage).encode("utf-8"))

    # --- the audit trail -----------------------------------------------------------------------------------------------

    def audit(self, *, actor: str, action: str, resource_id: str, after: dict[str, Any], reason: str | None = None) -> None:
        """One audit event (one per run, per decision; never one per fact), resource type "intake"."""
        self.ws.store.audit(self.ws.tenant_id).append(
            actor=actor, action=action, resource_type="intake", resource_id=f"{self.ws.project_id}/{resource_id}",
            after=after, reason=reason)
