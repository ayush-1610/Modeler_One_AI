"""The Data room's run, stage by stage (see the package docstring).

A run ends in one of three states (plan 2026-11-24 §4):
- `done`;
- `failed`: an error in our code, its trace kept. A provider's failure never fails a run;
- `paused`, for a reason that passes, with that reason (`pause.reason`) said in a plain sentence, the stage it stopped
  in and the files of that stage done:
  - `provider_unavailable`: no model of an agent's chain could answer (no answer in time, a rate limit or a quota, the
    service down or refusing its key). It resumes by itself after a rest of 10, then 20, then 40 minutes
    (`pause.resume_at`); a resume that finishes more work starts the rests again at 10. After the third it stays
    paused, and a person resumes it;
  - `budget_cap`: a paid model's cap is reached (`modeler_agents.spend`). It waits for the cap to be raised or the
    agent to be switched to a free model;
  - `no_model`: the agent's model is chosen but cannot be used (no active key, a configuration the console refuses, no
    model this project's files may go to). It waits for the model to be set up.
  The API resumes a run by itself when its time comes, and at once when the administrator changes a model, a key or the
  cap (`modeler_api.dataroom_runs`). An agent with no model at all (agents off) is skipped and says so, as before.

`run_room(..., resume="auto" | "now")` resumes a paused run in the same record. The stages finished before the pause are
not run again; the stage it paused in goes on without the files it already did (`attempted`); and every stage skips the
(file × stage) answers already stored. Nothing finished is asked of a model again.
"""

from __future__ import annotations

import traceback
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

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
# where a paused run stopped, as the page says it ("Paused at extraction: 7 of 11 files done")
WHERE = {"read": "reading", "question": "the question", "triage": "sorting", "extract": "extraction",
         "check": "checking", "write": "writing"}
PER_FILE = ("triage", "extract", "check")       # the stages that step file by file (each step's note is the file)
REST_MINUTES = (10, 20, 40)                      # the rests before a paused run resumes by itself; then a person does
PauseReason = Literal["provider_unavailable", "budget_cap", "no_model"]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class RunPaused(Exception):
    """The run stops for a reason that passes: it is paused, never failed. `said` is the reason in a plain sentence;
    `detail` the provider's own words, when there are any."""

    def __init__(self, reason: PauseReason, said: str, detail: str = ""):
        super().__init__(said)
        self.reason, self.said, self.detail = reason, said, detail


def unavailable(label: str, error: str) -> RunPaused:
    """No model of a chain could answer one step: the run pauses there."""
    return RunPaused("provider_unavailable", f"{label or 'The AI model'} could not answer ({_why(error)}).", error)


class _Run:
    """The run's record in the store, written after each step."""

    def __init__(self, store: DataRoomStore, doc: dict[str, Any]):
        self.store = store
        self.doc = doc
        self.save()

    @classmethod
    def new(cls, store: DataRoomStore, stages: Sequence[str], actor: str, run_id: str, params: dict[str, Any]) -> _Run:
        return cls(store, {
            "run_id": run_id, "state": "running", "started_at": _now(), "finished_at": None, "actor": actor, "error": "",
            "params": params, "pause": None, "auto_resumes": 0, "resumes": [],
            "stages": [{"id": sid, "label": label, "agent": agent, "state": "waiting" if sid in stages else "skipped",
                        "done": 0, "total": 0, "note": ""} for sid, label, agent in RUN_STAGES],
            "agents": {}})

    def save(self) -> None:
        self.store.set_run(self.doc)

    def stage(self, sid: str) -> dict[str, Any]:
        return next(s for s in self.doc["stages"] if s["id"] == sid)

    def step(self, sid: str, **update: Any) -> None:
        stage = self.stage(sid)
        finished = update.get("state") == "done" and stage.get("state") != "done"
        if finished or update.get("done", 0) > stage.get("done", 0):
            self.doc["auto_resumes"] = 0          # work finished since the last pause: the rests start again at 10 minutes
        stage.update(update)
        self.save()

    def pause(self, reason: PauseReason, said: str, detail: str = "") -> None:
        stage = next((s for s in self.doc["stages"] if s["state"] == "running"), None)
        if stage is not None:
            stage["state"] = "paused"
        tries = int(self.doc.get("auto_resumes") or 0)
        rest = REST_MINUTES[tries] if reason == "provider_unavailable" and tries < len(REST_MINUTES) else None
        now = datetime.now(UTC)
        self.doc["state"] = "paused"
        self.doc["pause"] = {
            "reason": reason, "said": said, "detail": detail[:600], "stage": stage["id"] if stage else "",
            "where": WHERE.get(stage["id"], stage["id"]) if stage else "", "per_file": bool(stage and stage["id"] in PER_FILE),
            "done": int(stage.get("done") or 0) if stage else 0, "total": int(stage.get("total") or 0) if stage else 0,
            "at": now.isoformat(timespec="seconds"),
            "resume_at": (now + timedelta(minutes=rest)).isoformat(timespec="seconds") if rest else None}


def _resumed(store: DataRoomStore, by: str, how: str) -> tuple[_Run, str] | None:
    """The paused run, running again in its own record, and the stage it stopped in (None when it is not paused)."""
    doc = store.run()
    if doc.get("state") != "paused":
        return None
    pause = doc.get("pause") or {}
    where = str(pause.get("stage") or "")
    for s in doc.get("stages", []):
        if s["state"] == "paused":
            s["state"] = "waiting"
    # a resume by the clock counts towards the rests; a person's, or one an administrator's change made, starts them again
    tries = int(doc.get("auto_resumes") or 0) + 1 if how == "auto" else 0
    doc.update(state="running", error="", finished_at=None, pause=None, auto_resumes=tries)
    doc.setdefault("resumes", []).append({"at": _now(), "by": by, "how": how, "stage": where, "reason": pause.get("reason")})
    store.audit(actor=by, action="dataroom.run.resume", resource_id="run",
                after={"how": how, "stage": where, "reason": pause.get("reason"), "run_id": doc.get("run_id")})
    return _Run(store, doc), where


def _why(error: str) -> str:
    """A switch's or a pause's reason in a few plain words."""
    e = error.lower()
    if "no answer within" in e or "timed out" in e:
        return "no answer in time"
    if "daily limit" in e or "per day" in e:
        return "its daily limit was spent"
    if "429" in e or "rate limit" in e or "too many requests" in e:
        return "too many requests: its rate limit was reached"
    if "quota" in e or "insufficient" in e or "credit balance" in e:
        return "its quota was spent"
    if "rejected the key" in e or "refused the credentials" in e:
        return "its key was refused"
    if "longer than" in e or "context window" in e:
        return "the request was too long for it"
    if "resting" in e:
        return "it failed a moment ago"
    return "its service did not answer"


def _check_again(store: DataRoomStore, chat_for: Callable[[str], ChatModel | str | None], actor: str,
                 files: Sequence[str] | None, focus_chars: int | None, agent_stages: Any) -> str:
    """The checker's findings back to the extractor, once: each file A9 flagged is extracted again with its issues in
    the prompt, then checked again (a new delivery, 2026-11-24: A9 saw the error, A8 never heard of it). One round per
    extraction: an extraction made on the checker's issues (`checker_issues`) is checked again but never sent back, so a
    run cannot loop, and a run resumed after a pause in the middle of the round finishes it (the files already sent back
    are only checked) without sending a file back twice. What A9 still finds after it stays on the room as before."""
    flagged: dict[str, list[dict[str, Any]]] = {}
    pending: set[str] = set()                       # sent back before a pause, not yet checked again
    for f in store.files():
        if f.duplicate_of or f.same_content_as or f.state not in ("read", "partly_read") or (files and f.path not in files):
            continue
        got = store.extraction(f.sha256)
        if got is None:
            continue
        sent_back = bool((got[1] or {}).get("checker_issues"))
        current = store.review_current(f.sha256)
        if sent_back and not current:
            pending.add(f.path)
        elif not sent_back and current and (issues := (store.review(f.sha256) or {}).get("issues")):
            flagged[f.path] = issues
    extractor = chat_for("A8") if flagged else None
    checker = chat_for("A9") if flagged or pending else None
    if (checker is None or isinstance(checker, str)
            or (flagged and (extractor is None or isinstance(extractor, str)))):
        return ""
    noop = lambda *_a, **_k: None
    if flagged:
        agent_stages.extract(store, extractor, actor=actor, redo=True, only=set(flagged), step=noop,
                             focus_chars=focus_chars or agent_stages.FOCUS_CHARS, feedback=flagged)
    # an extraction made again is checked again; one that got no new answer keeps its review and is not asked again
    agent_stages.check(store, checker, actor=actor, redo=False, only=set(flagged) | pending, step=noop,
                       focus_chars=focus_chars or agent_stages.FOCUS_CHARS)
    said = []
    if flagged:
        still = sum(1 for path, issues in store.reviews().items() if path in flagged and issues)
        said.append(f"{len(flagged)} flagged {'file' if len(flagged) == 1 else 'files'} extracted again with the checker's "
                    f"issues; {still} still {'has' if still == 1 else 'have'} issues")
    if pending:
        said.append(f"{len(pending)} {'file' if len(pending) == 1 else 'files'} extracted again before the pause checked again")
    return "; ".join(said)


def run_room(store: DataRoomStore, *, chat_for: Callable[[str], ChatModel | str | None], actor: str,
             stages: Sequence[str] | None = None, redo: Sequence[str] = (), use_ocr: bool = True,
             workers: int | None = None, files: Sequence[str] | None = None,
             focus_chars: int | None = None, resume: Literal["auto", "now"] | None = None,
             run_id: str | None = None) -> dict[str, Any]:
    """Run the Data room's stages in order and return the run's record (also in `store.run()`). `files` limits the
    agents' per-file stages (triage, extract, check) to those paths (a file added later, one to read again).
    `focus_chars` is the page budget an agent gets up front (default `stages.FOCUS_CHARS`; less for a model with a small
    per-request limit, such as GroqCloud's free tier).

    `resume`: go on with the paused run in the store, with the stages, files and redo it was started with (the record
    unchanged when it is not paused): "auto" when the clock resumes it, "now" when a person or an administrator's change
    does; `actor` is who resumed it. `run_id`: the new run's id (the paid spend's ledger names it); a new one when none."""
    from modeler_agents.dataroom import stages as agent_stages
    from modeler_agents.spend import BudgetCapReached

    paused_at = ""
    if resume:
        got = _resumed(store, actor, resume)
        if got is None:
            return store.run()
        run, paused_at = got
        params = run.doc.get("params") or {}
        wanted = list(params.get("stages") or [sid for sid, _l, _a in RUN_STAGES])
        redo, files = list(params.get("redo") or []), list(params.get("files") or []) or None
        focus_chars, use_ocr = params.get("focus_chars"), bool(params.get("use_ocr", use_ocr))
        actor = str(run.doc.get("actor") or actor)          # the stages' work stays the run's starter's
    else:
        wanted = list(stages) if stages is not None else [sid for sid, _l, _a in RUN_STAGES]
        params = {"stages": wanted, "redo": list(redo), "files": list(files or []), "focus_chars": focus_chars,
                  "use_ocr": use_ocr}
        run = _Run.new(store, wanted, actor, run_id or uuid.uuid4().hex[:12], params)
        # who started which stages on which files, on the project's audit chain (the governance review, 2026-11-22)
        store.audit(actor=actor, action="dataroom.run.start", resource_id="run",
                    after={"stages": wanted, "files": list(files or []), "redo": list(redo), "run_id": run.doc["run_id"]})
    try:
        for sid, _label, agent in RUN_STAGES:
            if sid not in wanted or run.stage(sid)["state"] in ("done", "skipped"):    # finished before a pause
                continue
            only: set[str] | None = set(files) if files else None
            base = 0
            if sid == paused_at:
                # where a resumed run goes on: the files this stage already did are not done again, even with `redo`
                base = int(run.stage(sid).get("done") or 0)
                if attempted := set(run.stage(sid).get("attempted") or ()):
                    only = (only if only is not None else {f.path for f in store.files()}) - attempted
            run.step(sid, state="running")
            if sid == "read":
                # its own name: `files` is the caller's filter of the agents' stages, which the files read must not replace
                read = read_uploads(store, use_ocr=use_ocr, workers=workers,
                                    progress=lambda done, total, path: run.step("read", done=done, total=total, note=path))
                run.step("read", state="done", done=len(read), total=len(read),
                         note=f"{len(read)} files, {sum(len(f.ocr_pages) for f in read)} scanned pages read by OCR")
                continue
            model = chat_for(agent)
            if model is None:                                # agents off, or this one switched off: skipped, as before
                run.step(sid, state="skipped", note=f"no AI model is set up for {agent}: the admin console sets one")
                continue
            if isinstance(model, str):                       # one chosen that cannot be used: wait for it to be set up
                raise RunPaused("no_model", f"{agent}'s model cannot be used: {model.rstrip('.')}.", model)
            run.doc["agents"][agent] = f"{model.provider}/{model.model}"

            def step(done: int, total: int, note: str = "", _sid: str = sid, _base: int = base) -> None:
                if _sid in PER_FILE and note and done:       # the file just done: a resumed stage does not do it again
                    run.stage(_sid).setdefault("attempted", []).append(note)
                run.step(_sid, done=_base + done, total=_base + total, note=note)

            note = getattr(agent_stages, sid)(store, model, actor=actor, redo=sid in redo, only=only,
                                              focus_chars=focus_chars or agent_stages.FOCUS_CHARS, step=step)
            note = note or run.stage(sid)["note"]
            if sid == "check" and (again := _check_again(store, chat_for, actor, files, focus_chars, agent_stages)):
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
    except RunPaused as exc:
        run.pause(exc.reason, exc.said, exc.detail)
    except BudgetCapReached as exc:
        run.pause("budget_cap", exc.said[:1].upper() + exc.said[1:] + ".", str(exc))
    except Exception as exc:  # noqa: BLE001 - a failed run is recorded with its reason, never left "running"
        run.doc["state"] = "failed"
        run.doc["error"] = f"{type(exc).__name__}: {exc}"
        run.doc["trace"] = traceback.format_exc()[-4000:]
        for s in run.doc["stages"]:
            if s["state"] == "running":
                s["state"] = "failed"
    run.doc["finished_at"] = None if run.doc["state"] == "paused" else _now()
    run.save()
    store.append_run({k: run.doc.get(k) for k in ("run_id", "started_at", "finished_at", "state", "actor", "agents", "error")}
                     | {"pause": run.doc.get("pause"),
                        "stages": [{k: s.get(k) for k in ("id", "state", "done", "total", "note")} for s in run.doc["stages"]]})
    return run.doc
