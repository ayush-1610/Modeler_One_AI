"""Reading a project's uploads into the Data room (plan 2026-11-21 v2 §5 stage 1): every file read once per reader
version, in parallel, scans by our OCR engine; a file already read (same bytes, same reader) is not read again.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor

from modeler_intake.room import RoomFile, expand_uploads, mark_duplicates, read_file
from modeler_intake.source import SOURCE_VERSION
from modeler_project.dataroom.model import FileView
from modeler_project.dataroom.store import DataRoomStore


def _read_one(args: tuple[str, bytes, bool]) -> RoomFile:
    path, data, use_ocr = args
    ocr = None
    if use_ocr:
        from modeler_intake.ocr import RapidOcr

        ocr = RapidOcr()
    return read_file(path, data, ocr=ocr)


def file_view(room: RoomFile) -> FileView:
    return FileView(path=room.path, name=room.name, sha256=room.sha256, kind=room.kind, pages=room.pages,
                    ocr_pages=room.ocr_pages, turned_pages=room.turned_pages, state=room.state, reason=room.reason,
                    duplicate_of=room.duplicate_of, same_content_as=room.same_content_as)


def read_uploads(store: DataRoomStore, *, use_ocr: bool = True, workers: int | None = None,
                 progress: Callable[[int, int, str], None] | None = None) -> list[FileView]:
    """Read every upload of the project (archives unpacked) and store the files and their documents."""
    uploads = [(u["name"], store.upload_bytes(u["sha256"])) for u in store.uploads()]
    expanded, unreadable = expand_uploads(uploads)
    known = {f.sha256: f for f in store.files()}
    todo: list[tuple[str, bytes]] = []
    cached: dict[str, RoomFile] = {}
    seen: set[str] = set()
    for path, data in expanded:
        sha = hashlib.sha256(data).hexdigest()
        if sha in seen:
            continue
        seen.add(sha)
        doc = store.doc(sha) if sha in known else None
        if doc is not None and doc.parser_version.startswith(f"{SOURCE_VERSION}+"):
            f = known[sha]
            cached[sha] = RoomFile(path=path, name=f.name, sha256=sha, size_bytes=len(data), kind=f.kind, read_as=f.name,
                                   state=f.state, reason=f.reason, pages=f.pages, ocr_pages=f.ocr_pages,
                                   turned_pages=f.turned_pages, document=doc,
                                   text_sha256=_text_sha(doc))
        else:
            todo.append((path, data))
    done = 0
    total = len(todo)
    workers = workers or max(1, min(4, (os.cpu_count() or 2) - 1))
    if todo:
        if workers > 1 and total > 1:
            with ProcessPoolExecutor(max_workers=workers) as pool:
                for room in pool.map(_read_one, [(p, d, use_ocr) for p, d in todo]):
                    cached[room.sha256] = room
                    done += 1
                    if progress:
                        progress(done, total, room.path)
        else:
            for p, d in todo:
                room = _read_one((p, d, use_ocr))
                cached[room.sha256] = room
                done += 1
                if progress:
                    progress(done, total, room.path)
    ordered: list[tuple[str, bytes, RoomFile | None]] = []
    first: set[str] = set()
    for path, data in expanded:
        sha = hashlib.sha256(data).hexdigest()
        ordered.append((path, data, None if sha in first else cached[sha].model_copy(update={"path": path})))
        first.add(sha)
    rooms = unreadable + mark_duplicates(ordered)
    for room in rooms:
        if room.document is not None and room.duplicate_of is None:
            store.put_doc(room.sha256, room.document)
    views = [file_view(r) for r in rooms]
    store.set_files(views)
    return views


def _text_sha(doc) -> str:
    from modeler_intake.room import _normal, document_text

    text = "\n".join(line for _, lines in document_text(doc) for line in lines)
    return hashlib.sha256(_normal(text).encode()).hexdigest()
