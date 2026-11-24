"""The Data room's run, stage by stage (see the package docstring)."""

from __future__ import annotations

import traceback
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from modeler_agents.llm import ChatModel
from modeler_project.dataroom.reading import read_uploads
from modeler_project.dataroom.store import DataRoomStore

# (id, what the page says while it runs, the agent that does it or "" for code)
RUN_STAGES: tuple[tuple[str, str, str], ...] = (
    ("read", "Reading the files", ""),
    ("question", "Understanding the question", "A6"),
    ("triage", "Sorting the files", "A7"),
    ("extract", "Extracting", "A8"),
    ("check", "Checking every number", "A9"),
    ("write", "Putting it together", "A10"),
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class _Run:
    """The run's record in the store, written after each step."""

    def __init__(self, store: DataRoomStore, stages: Sequence[str], actor: str):
        self.store = store
        self.doc: dict[str, Any] = {
            "state": "running", "started_at": _now(), "finished_at": None, "actor": actor, "error": "",
            "stages": [{"id": sid, "label": label, "agent": agent, "state": "waiting" if sid in stages else "skipped",
                        "done": 0, "total": 0, "note": ""} for sid, label, agent in RUN_STAGES],
            "agents": {}}
        self.save()

    def save(self) -> None:
        self.store.set_run(self.doc)

    def stage(self, sid: str) -> dict[str, Any]:
        return next(s for s in self.doc["stages"] if s["id"] == sid)

    def step(self, sid: str, **update: Any) -> None:
        self.stage(sid).update(update)
        self.save()


def _why(error: str) -> str:
    """A switch's reason in a few plain words."""
    e = error.lower()
    if "no answer within" in e:
        return "no answer in time"
    if "daily limit" in e or "per day" in e:
        return "its daily limit was spent"
    if "rejected the key" in e:
        return "its key was refused"
    if "longer than" in e or "context window" in e:
        return "the request was too long for it"
    if "resting" in e:
        return "it failed a moment ago"
    return "its service did not answer"


def _check_again(store: DataRoomStore, chat_for: Callable[[str], ChatModel | str | None], actor: str,
                 files: Sequence[str] | None, focus_chars: int | None, agent_stages: Any, redo: Sequence[str] = ()) -> str:
    """The checker's findings back to the extractor, once: each file A9 flagged is extracted again with its issues in
    the prompt, then checked again (a new delivery, 2026-11-24: A9 saw the error, A8 never heard of it). Bounded to one
    round, so a run cannot loop; what A9 still finds after it stays on the room as before. Both steps use the answer
    cache unless the run was asked to redo their stage (`redo`)."""
    flagged = {path: issues for path, issues in store.reviews().items() if issues and (not files or path in files)}
    extractor = chat_for("A8") if flagged else None
    checker = chat_for("A9") if flagged else None
    if not flagged or extractor is None or isinstance(extractor, str) or checker is None or isinstance(checker, str):
        return ""
    noop = lambda *_a, **_k: None
    agent_stages.extract(store, extractor, actor=actor, redo=True, only=set(flagged), step=noop,
                         focus_chars=focus_chars or agent_stages.FOCUS_CHARS, feedback=flagged, reuse="extract" not in redo)
    agent_stages.check(store, checker, actor=actor, redo=True, only=set(flagged), step=noop,
                       focus_chars=focus_chars or agent_stages.FOCUS_CHARS, reuse="check" not in redo, recheck=True)
    still = sum(1 for path, issues in store.reviews().items() if path in flagged and issues)
    return (f"{len(flagged)} flagged {'file' if len(flagged) == 1 else 'files'} extracted again with the checker's "
            f"issues; {still} still {'has' if still == 1 else 'have'} issues")


def run_room(store: DataRoomStore, *, chat_for: Callable[[str], ChatModel | str | None], actor: str,
             stages: Sequence[str] | None = None, redo: Sequence[str] = (), use_ocr: bool = True,
             workers: int | None = None, files: Sequence[str] | None = None,
             focus_chars: int | None = None) -> dict[str, Any]:
    """Run the Data room's stages in order and return the run's record (also in `store.run()`). `files` limits the
    agents' per-file stages (triage, extract, check) to those paths (a file added later, one to read again).
    `focus_chars` is the page budget an agent gets up front (default `stages.FOCUS_CHARS`; less for a model with a small
    per-request limit, such as GroqCloud's free tier)."""
    from modeler_agents.dataroom import stages as agent_stages

    wanted = list(stages) if stages is not None else [sid for sid, _l, _a in RUN_STAGES]
    run = _Run(store, wanted, actor)
    # who started which stages on which files, on the project's audit chain (the governance review, 2026-11-22)
    store.audit(actor=actor, action="dataroom.run.start", resource_id="run",
                after={"stages": wanted, "files": list(files or []), "redo": list(redo)})
    try:
        for sid, _label, agent in RUN_STAGES:
            if sid not in wanted:
                continue
            run.step(sid, state="running")
            if sid == "read":
                # its own name: `files` is the caller's filter of the agents' stages, which the files read must not replace
                read = read_uploads(store, use_ocr=use_ocr, workers=workers,
                                    progress=lambda done, total, path: run.step("read", done=done, total=total, note=path))
                run.step("read", state="done", done=len(read), total=len(read),
                         note=f"{len(read)} files, {sum(len(f.ocr_pages) for f in read)} scanned pages read by OCR")
                continue
            model = chat_for(agent)
            if model is None or isinstance(model, str):      # none set up, or none this project's files may go to
                run.step(sid, state="skipped", note=model or f"no AI model is set up for {agent}: the admin console sets one")
                continue
            run.doc["agents"][agent] = f"{model.provider}/{model.model}"
            note = getattr(agent_stages, sid)(store, model, actor=actor, redo=sid in redo, only=set(files) if files else None,
                                              focus_chars=focus_chars or agent_stages.FOCUS_CHARS,
                                              step=lambda done, total, note="", _sid=sid: run.step(_sid, done=done, total=total,
                                                                                                    note=note))
            note = note or run.stage(sid)["note"]
            if sid == "check" and (again := _check_again(store, chat_for, actor, files, focus_chars, agent_stages, redo)):
                note += f"; {again}"
            switches = getattr(model, "switches", [])
            if switches:
                # said where the run is shown (the governance review: the switch is told, with what went where)
                run.doc["agents"][agent] = " then ".join(dict.fromkeys([switches[0]["from"], *(x["to"] for x in switches)]))
                said = dict.fromkeys(f"{x['from']} could not answer ({_why(x['why'])}): went on with {x['to']}"
                                     for x in switches)
                note += "; " + "; ".join(said)
            run.step(sid, state="done", note=note)
        run.doc["state"] = "done"
    except Exception as exc:  # noqa: BLE001 - a failed run is recorded with its reason, never left "running"
        run.doc["state"] = "failed"
        run.doc["error"] = f"{type(exc).__name__}: {exc}"
        run.doc["trace"] = traceback.format_exc()[-4000:]
        for s in run.doc["stages"]:
            if s["state"] == "running":
                s["state"] = "failed"
    run.doc["finished_at"] = _now()
    run.save()
    store.append_run({k: run.doc.get(k) for k in ("started_at", "finished_at", "state", "actor", "agents", "error")}
                     | {"stages": [{k: s.get(k) for k in ("id", "state", "done", "total", "note")} for s in run.doc["stages"]]})
    return run.doc
