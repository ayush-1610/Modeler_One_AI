"""The 30-day format inventory over a read root (plan §10, decision 5; contracts §6.1): what clients send, by format,
before the adapters' scope is frozen.

    python -m modeler_project.format_inventory --root R [--tenant T] [--since DATE] [--json] [--out F]

The files are the ones each project of the store holds: the `file` lines of `intake/files.jsonl` and the DOCUMENT
artifacts, read through their owners (`intake_store.ChainedLog`, `documents.document_record`), each counted once by its
bytes' sha256; the bytes are the project's blobs. A ZIP member recorded beside its ZIP (a `file` line with a container)
is counted once, inside the ZIP the inventory expands. `--since` keeps the files that arrived on or after a date. The counts
are `modeler_intake.source.inventory`'s. Nothing is written under the root: the report is printed, or written to `--out`
(which must lie outside the root). A file whose bytes are missing is named on stderr and not counted.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

from pydantic import ValidationError

from modeler_intake.source.inventory import FormatInventory, inventory
from modeler_project.artifacts import ArtifactKind
from modeler_project.documents import document_record
from modeler_project.intake_records import FileRecord
from modeler_project.intake_store import ChainedLog
from modeler_project.store import FileProjectStore


def _day(text: str) -> date:
    return date.fromisoformat(text)


def _arrived(at: str | datetime) -> date | None:
    try:
        moment = at if isinstance(at, datetime) else datetime.fromisoformat(at)
    except ValueError:
        return None
    return (moment if moment.tzinfo else moment.replace(tzinfo=UTC)).astimezone(UTC).date()


def stored_files(root: Path, *, tenant: str | None = None, since: date | None = None,
                 missing: list[str] | None = None) -> Iterator[tuple[str, bytes]]:
    """(name, bytes) of every client file the store holds (see the module docstring), each sha256 once."""
    store = FileProjectStore(root)
    seen: set[str] = set()
    tenants = [tenant] if tenant else sorted(t.name for t in root.iterdir() if (t / "projects").is_dir())
    for tenant_id in tenants:
        projects = root / tenant_id / "projects"
        if not projects.is_dir():
            continue
        for project in sorted(p.name for p in projects.iterdir() if p.is_dir()):
            found: list[tuple[str, str, date | None, str | None]] = []      # sha256, name, arrival, container
            log = projects / project / "intake" / "files.jsonl"
            try:
                entries = ChainedLog(log).entries("file") if log.exists() else []
            except ValueError as exc:                      # a damaged log is named, never repaired here
                entries = []
                if missing is not None:
                    missing.append(f"{tenant_id}/{project}: intake/files.jsonl not read ({exc})")
            if entries:
                for entry in entries:
                    try:
                        record = FileRecord.model_validate(entry.body)
                    except ValidationError:
                        continue
                    found.append((record.sha256, record.name, _arrived(record.at),
                                  record.container.sha256 if record.container else None))
            for kind, artifact_id in store.keys(tenant_id, project, ArtifactKind.DOCUMENT):
                versions = store.versions(tenant_id, project, kind, artifact_id)
                if versions:
                    record = document_record(versions[-1])
                    found.append((record.sha256, record.name, _arrived(versions[0].created_at), None))
            listed = {sha for sha, _name, _arrived_on, _container in found}
            for sha, name, arrived, container in found:
                if sha in seen or (since is not None and (arrived is None or arrived < since)):
                    continue
                if container is not None and container in listed:
                    continue                               # counted inside its ZIP
                seen.add(sha)
                path = store.blob_path(tenant_id, project, sha)
                if path is None:
                    if missing is not None:
                        missing.append(f"{tenant_id}/{project}: {name} ({sha[:12]}...)")
                    continue
                yield name, path.read_bytes()


def render(found: FormatInventory) -> str:
    """The inventory as a short text report."""
    lines = [f"files: {found.files} (and {found.zip_members} inside ZIPs)", "by extension:"]
    lines += [f"  {ext:10} {n}" for ext, n in found.by_extension.items()] or ["  (none)"]
    lines += [f"PDF: {found.pdf_native} native, {found.pdf_scanned} scanned, {found.pdf_mixed} mixed",
              f"documents with figures: {found.with_figures}", "unsupported:"]
    lines += [f"  {ext:10} {n}" for ext, n in found.unsupported.items()] or ["  (none)"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="What clients send, by format (the format inventory).")
    parser.add_argument("--root", required=True, help="the project store root (on the server: ~/modeler-data/read-root)")
    parser.add_argument("--tenant", help="one tenant (all when left out)")
    parser.add_argument("--since", type=_day, help="only files that arrived on or after this date (YYYY-MM-DD)")
    parser.add_argument("--json", action="store_true", help="print the inventory as JSON")
    parser.add_argument("--out", help="write the report to this file (outside the root) instead of printing it")
    args = parser.parse_args(argv)
    root = Path(args.root).expanduser()
    if not args.root.strip() or not root.is_dir():
        print(f"no project store at {args.root!r}: give its folder (on the server, ~/modeler-data/read-root)", file=sys.stderr)
        return 2
    if args.out and Path(args.out).expanduser().resolve().is_relative_to(root.resolve()):
        print(f"--out {args.out} lies inside the root: the inventory writes nothing there", file=sys.stderr)
        return 2
    if args.tenant and not (root / args.tenant / "projects").is_dir():
        print(f"no tenant {args.tenant!r} in this store", file=sys.stderr)
        return 2
    missing: list[str] = []
    found = inventory(stored_files(root, tenant=args.tenant, since=args.since, missing=missing))
    for line in missing:
        print(f"bytes missing, not counted: {line}", file=sys.stderr)
    text = json.dumps(found.model_dump(mode="json"), indent=1) if args.json else render(found)
    if args.out:
        Path(args.out).expanduser().write_text(text + "\n", encoding="utf-8")
        print(f"written to {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
