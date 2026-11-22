"""The Data room (plan 2026-11-21 v2): from any client delivery to an evidence report and traced PK-Sim inputs.

The agents describe (tables, quoted facts); code reads, checks and computes (`extract`, `clinical`, `invitro`,
`assemble`); the modeler decides (`store.decide`). `room_view` gives the whole room as the page and the report show it.
"""

from __future__ import annotations

from modeler_project.dataroom.assemble import Inputs, assemble
from modeler_project.dataroom.model import DataRoomView
from modeler_project.dataroom.store import DataRoomStore


def room_view(store: DataRoomStore) -> DataRoomView:
    """The room assembled from the store: only the documents an extraction points into are loaded."""
    question, confirmed = store.question()
    files = store.files()
    extractions = store.extractions()
    wanted = {t.file or e.file for e in extractions for t in e.tables} | {f.file or e.file for e in extractions for f in e.facts}
    by_path = {f.path: f.sha256 for f in files}
    docs = {sha: d for path in wanted if (sha := by_path.get(path)) and (d := store.doc(sha)) is not None}
    return assemble(Inputs(files=files, docs=docs, question=question, question_confirmed=confirmed, extractions=extractions,
                           decisions=store.decisions(), entered=store.entered(), request_edits=store.request_edits(),
                           reviews=store.reviews(), writing=store.writing()))


__all__ = ["DataRoomStore", "DataRoomView", "Inputs", "assemble", "room_view"]
