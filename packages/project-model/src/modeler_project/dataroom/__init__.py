"""The Data room (plan 2026-11-21 v2): from any client delivery to an evidence report and traced PK-Sim inputs.

The agents describe (tables, quoted facts); code reads, checks and computes (`extract`, `clinical`, `invitro`,
`assemble`); the modeler decides (`store.decide`). `room_view` gives the whole room as the page and the report show it.
"""

from __future__ import annotations

from modeler_project.dataroom.assemble import Inputs, assemble
from modeler_project.dataroom.model import DataRoomView, MadeBy
from modeler_project.dataroom.store import DataRoomStore


def room_inputs(store: DataRoomStore) -> Inputs:
    """What the room is assembled from, read from the store: only the documents an extraction points into are loaded."""
    question, confirmed = store.question()
    files = store.files()
    extractions = store.extractions()
    wanted = {t.file or e.file for e in extractions for t in e.tables} | {f.file or e.file for e in extractions for f in e.facts}
    by_path = {f.path: f.sha256 for f in files}
    docs = {sha: d for path in wanted if (sha := by_path.get(path)) and (d := store.doc(sha)) is not None}
    return Inputs(files=files, docs=docs, question=question, question_confirmed=confirmed, extractions=extractions,
                  decisions=store.decisions(), entered=store.entered(), request_edits=store.request_edits(),
                  reviews=store.reviews(), writing=store.writing())


def room_view(store: DataRoomStore) -> DataRoomView:
    """The room assembled from the store."""
    view = assemble(room_inputs(store))
    made = made_by(store.authors(), store.agent_steps())
    return view.model_copy(update={"made_by": made, "made_summary": made_summary(made)})


STAGE_WORDS = {"question": "the question card", "triage": "sorting", "extract": "reading", "check": "checking",
               "write": "the findings"}


def _service(identity: str) -> str:
    from modeler_project.data_permissions import CLOUD_SERVICES, IN_HOUSE

    provider = identity.split("/", 1)[0]
    return "our server" if provider in IN_HOUSE else CLOUD_SERVICES.get(provider, provider or "unknown")


def made_by(authors: list[dict], steps: list[dict]) -> tuple[MadeBy, ...]:
    """Who wrote each stage's latest answer for each file, with the models that could not answer before it."""
    switches: dict[tuple[str, str], list[str]] = {}
    for s in steps:
        if s.get("type") == "model_switch":
            why = str(s.get("why", ""))
            short = ("no answer in time" if "no answer within" in why else "a daily limit spent" if "daily" in why
                     else "resting after a failure" if "resting" in why else "a second opinion" if "second opinion" in why
                     else "its service did not answer")
            switches.setdefault((s.get("stage", ""), s.get("file", "")), []).append(f"{s.get('from')} → {s.get('to')} ({short})")
    latest: dict[tuple[str, str], dict] = {}
    for a in authors:
        latest[(a["stage"], a["file"])] = a
    order = list(STAGE_WORDS)
    return tuple(MadeBy(stage=a["stage"], file=a["file"], model=a["model"], service=_service(a.get("identity", "")),
                        prompt=a.get("prompt", ""), at=a.get("at", ""), note=a.get("note", ""),
                        switches=tuple(dict.fromkeys(switches.get((a["stage"], a["file"]), []))))
                 for a in sorted(latest.values(), key=lambda a: (order.index(a["stage"]) if a["stage"] in order else 9,
                                                                  a["file"])))


def made_summary(made: tuple[MadeBy, ...]) -> str:
    """One sentence for the report: which models read the files, where they ran, and that code checked every value."""
    reading = [m for m in made if m.stage == "extract"]
    if not made:
        return ""
    counts: dict[tuple[str, str], int] = {}
    for m in reading or made:
        counts[(m.model, m.service)] = counts.get((m.model, m.service), 0) + 1
    unit = "file" if reading else "step"
    parts = [f"{model} on {service} for {n} {unit}{'s' if n != 1 else ''}" for (model, service), n in counts.items()]
    switched = sum(1 for m in made if m.switches)
    return ("Models: " + "; ".join(parts) + (f" ({switched} after another model could not answer)" if switched else "")
            + ". Code read and checked every value; a modeler confirms each.")


__all__ = ["DataRoomStore", "DataRoomView", "Inputs", "assemble", "made_by", "made_summary", "room_inputs", "room_view"]
