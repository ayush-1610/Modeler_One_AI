"""The Data room's run end to end with a scripted model (plan 2026-11-21 v2 §9 "Proof built in"): read, triage,
extract, write; a submission whose quote is not in the file is sent back with the reason and corrected; a stage with
no model is skipped and says so. No paid model is called; the delivery is synthetic (Exampleamide).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from modeler_agents.dataroom import run_room
from modeler_agents.llm import ChatResult, ToolCall
from modeler_project.dataroom import DataRoomStore, room_view
from modeler_project.store import FileProjectStore
from modeler_project.workspace import Workspace

pytestmark = pytest.mark.req("T-47")

TIMES = (0, 1, 2, 4, 8, 12)
CONC = "SUB\tTRT\tPER\t" + "\t".join(f"{t:g}" for t in TIMES) + "\n" + "".join(
    f"{s}\t{t}\t{p}\t0\t{10 + s}\t{20 + s}\t{15 + s}\t{8 + s}\t{3 + s}\n"
    for s in (1, 2, 3, 4) for t, p in (("A", "1"), ("B", "2")))
SYNOPSIS = "# Study EX-02\n\nTreatments: A = reference product; B = test product.\nEach subject received 50 mg.\n"


class Scripted:
    """A chat model that answers by the submit tool it is offered, from a script, and says DONE after "saved"."""

    provider, model = "scripted", "v1"

    def __init__(self, answers: dict[str, list[dict[str, Any]]]):
        self.answers = {k: list(v) for k, v in answers.items()}
        self.seen: list[str] = []

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ChatResult:
        last = messages[-1]
        if last["role"] == "tool" and str(last.get("content", "")).startswith("saved") and "problems" not in last["content"]:
            return ChatResult(content="DONE", tool_calls=(), finish_reason="stop", usage={}, model=self.model)
        if last["role"] == "tool":
            self.seen.append(last["content"])
        submit = next(t["function"]["name"] for t in tools if t["function"]["name"].startswith("submit_"))
        user = messages[1]["content"]
        answer = _triage(user) if submit == "submit_triage" else self.answers[submit].pop(0)
        return ChatResult(content="", tool_calls=(ToolCall(id=f"c{len(self.seen)}", name=submit, arguments=answer,
                                                           raw_arguments=json.dumps(answer)),),
                          finish_reason="tool_calls", usage={}, model=self.model)


def _triage(user: str) -> dict[str, Any]:
    path = user.split("File: ", 1)[1].split(" (", 1)[0]
    return {"path": path, "purpose": "used", "topics": ["clinical_concentrations"], "reason": "the study's data"}


def _store(tmp_path) -> DataRoomStore:
    store = DataRoomStore(Workspace(FileProjectStore(tmp_path), "t1", "p1"))
    store.add_upload("conc.tsv", CONC.encode(), by="user:m")
    store.add_upload("synopsis.md", SYNOPSIS.encode(), by="user:m")
    return store


def _extraction(store: DataRoomStore) -> list[dict[str, Any]]:
    from modeler_intake.room import document_parts

    conc = next(f for f in store.files() if f.name == "conc.tsv")
    part = document_parts(store.doc(conc.sha256))[0].name
    table = {"file": "conc.tsv", "kind": "concentrations", "about": "EX-02", "part": part, "header_lines": [1],
             "first_line": 2, "last_line": 9, "time_unit": "h", "value_unit": "ng/mL", "zero_means_blq": True,
             "columns": [{"index": 1, "role": "subject"}, {"index": 2, "role": "treatment"}, {"index": 3, "role": "period"}]
             + [{"index": 4 + i, "role": "value", "time": t} for i, t in enumerate(TIMES)]}
    wrong = {"field": "study.dose", "subject": "EX-02", "value": "500", "unit": "mg", "quote": "Each subject received 500 mg."}
    right = {"field": "study.dose", "subject": "EX-02", "value": "50", "unit": "mg", "quote": "Each subject received 50 mg."}
    code = {"field": "study.treatment_code", "subject": "A", "value": "reference product",
            "quote": "A = reference product; B = test product."}
    return [{"file": "conc.tsv", "tables": [table]},                       # conc.tsv
            {"file": "synopsis.md", "facts": [wrong, code]},              # synopsis: a misread dose, sent back …
            {"file": "synopsis.md", "facts": [right, code]}]              # … and corrected


def test_a_run_reads_sorts_extracts_and_a_refused_fact_is_corrected_by_the_model(tmp_path):
    store = _store(tmp_path)
    run_room(store, chat_for=lambda agent: None, actor="user:m", stages=["read"], use_ocr=False, workers=1)
    model = Scripted({"submit_extraction": _extraction(store),
                      "submit_writing": [{"findings": {"clinical": "EX-02: 4 subjects in the modeling set."},
                                          "requests": {}}]})
    doc = run_room(store, chat_for=lambda agent: model, actor="user:m", stages=["triage", "extract", "write"], use_ocr=False)
    assert doc["state"] == "done", doc["error"]
    assert {s["id"]: s["state"] for s in doc["stages"]}["extract"] == "done"
    assert any("the quote is not in" in seen for seen in model.seen)        # the misread dose was sent back
    view = room_view(store)
    (study,) = view.studies
    assert {s.name: len(s.subjects) for s in study.sets}["modeling"] == 4
    assert next(v.value for v in study.facts if v.key.startswith("study.dose")) == 50.0
    assert [a.treatment for a in study.arms] == ["A"]
    assert next(s.finding for s in view.sections if s.id == "clinical") == "EX-02: 4 subjects in the modeling set."
    assert doc["agents"] == {"A7": "scripted/v1", "A8": "scripted/v1", "A10": "scripted/v1"}


def test_a_stage_with_no_model_is_skipped_and_says_so(tmp_path):
    store = _store(tmp_path)
    doc = run_room(store, chat_for=lambda agent: None, actor="user:m", use_ocr=False, workers=1)
    states = {s["id"]: (s["state"], s["note"]) for s in doc["stages"]}
    assert doc["state"] == "done" and states["read"][0] == "done" and states["read"][1].startswith("2 files")
    assert states["extract"][0] == "skipped" and "no AI model is set up for A8" in states["extract"][1]
    assert [f.name for f in room_view(store).files] == ["conc.tsv", "synopsis.md"]


def test_the_writer_may_not_bring_a_number_of_its_own(tmp_path):
    store = _store(tmp_path)
    run_room(store, chat_for=lambda agent: None, actor="user:m", stages=["read"], use_ocr=False, workers=1)
    model = Scripted({"submit_writing": [{"findings": {"files": "2 files read; 97 % complete."}, "requests": {}},
                                         {"findings": {"files": "2 files read."}, "requests": {}}]})
    run_room(store, chat_for=lambda agent: model, actor="user:m", stages=["write"], use_ocr=False)
    assert any("a number that is not in the material" in seen for seen in model.seen)
    assert store.writing()["findings"] == {"files": "2 files read."}


def test_one_run_reads_the_files_and_then_sorts_every_one_of_them(tmp_path):
    # the read stage's files once replaced the run's per-file filter, so a run that read and then sorted sorted nothing
    store = _store(tmp_path)
    doc = run_room(store, chat_for=lambda agent: Scripted({}) if agent == "A7" else None, actor="user:m",
                   stages=["read", "triage"], use_ocr=False, workers=1)
    assert doc["state"] == "done", doc["error"]
    assert {s["id"]: s["note"] for s in doc["stages"]}["triage"] == "2 files sorted"
    assert all(f.triage is not None for f in store.files())


def test_a_stage_whose_model_does_not_answer_goes_on_with_the_next_and_says_so(tmp_path):
    # the owner, 2026-11-22: "no question card (LLM_UNAVAILABLE: litellm … no answer within 600 s)"; the stage now goes
    # on with the chain's next model, records who wrote the card, and says what happened
    from modeler_agents.llm import HEALTH, FallbackChat
    from modeler_agents.run import LLMUnavailableError

    class Silent:
        provider, model = "litellm", "qwen-coder"

        def complete(self, messages, tools):
            raise LLMUnavailableError("litellm unavailable: no answer within 600 s")

    card = {"question": "Is EX-02's test product bioequivalent?", "products": [{"name": "test product", "role": "test"}],
            "checklist": [], "quotes": []}
    store = _store(tmp_path)
    run_room(store, chat_for=lambda agent: None, actor="user:m", stages=["read"], use_ocr=False, workers=1)
    HEALTH.reset()
    chain = FallbackChat([Silent(), Scripted({"submit_question": [card]})], labels=["Qwen Coder", "Nemotron Ultra"])
    doc = run_room(store, chat_for=lambda agent: chain, actor="user:m", stages=["question"], use_ocr=False)
    note = {s["id"]: s["note"] for s in doc["stages"]}["question"]
    assert note.startswith("question card drafted") and "Qwen Coder could not answer (no answer in time): went on with Nemotron Ultra" in note
    assert doc["agents"]["A6"] == "Qwen Coder then Nemotron Ultra"
    raw = store._read_json("question.json")
    assert raw["by"] == "agent:A6:Nemotron Ultra"
    steps = store.agent_steps()
    assert any(s["type"] == "model_switch" and s["to"] == "Nemotron Ultra" for s in steps)
    assert any(s["type"] == "model_turn" and s["stage"] == "question" for s in steps)
    HEALTH.reset()


def test_each_answer_names_its_author_the_report_says_how_it_was_made_and_each_run_is_kept(tmp_path):
    # the governance review, 2026-11-22: who wrote each file's reading, where it ran, the prompt; a run audited when it
    # starts and kept when it ends
    store = _store(tmp_path)
    run_room(store, chat_for=lambda agent: None, actor="user:m", stages=["read"], use_ocr=False, workers=1)
    model = Scripted({"submit_extraction": _extraction(store),
                      "submit_writing": [{"findings": {"clinical": "EX-02: 4 subjects in the modeling set."}, "requests": {}}]})
    run_room(store, chat_for=lambda agent: model, actor="user:m", stages=["triage", "extract", "write"], use_ocr=False)
    authors = {(a["stage"], a["file"]): a for a in store.authors()}
    assert ("extract", "conc.tsv") in authors and ("write", "") in authors and ("triage", "synopsis.md") in authors
    assert authors[("extract", "conc.tsv")]["identity"] == "scripted/v1" and authors[("extract", "conc.tsv")]["prompt"]
    view = room_view(store)
    rows = {(m.stage, m.file): m for m in view.made_by}
    assert rows[("extract", "conc.tsv")].model == "scripted/v1" and rows[("extract", "conc.tsv")].service == "scripted"
    assert view.made_summary.startswith("Models: scripted/v1 on scripted for 2 files")
    assert "Code read and checked every value" in view.made_summary
    runs = store.runs()
    assert [r["state"] for r in runs] == ["done", "done"] and runs[-1]["actor"] == "user:m"
    starts = [r.event for r in store.ws.store.audit("t1").records() if r.event.action == "dataroom.run.start"]
    assert len(starts) == 2 and starts[-1].after["stages"] == ["triage", "extract", "write"]


def test_the_checker_starts_on_another_model_than_the_one_that_wrote_the_extraction(tmp_path):
    # plan §9's second opinion (the governance review, 2026-11-22): A9 is not A8's model when the chain has another
    from modeler_agents.llm import HEALTH, FallbackChat

    store = _store(tmp_path)
    run_room(store, chat_for=lambda agent: None, actor="user:m", stages=["read"], use_ocr=False, workers=1)
    writer = Scripted({"submit_extraction": _extraction(store)})
    run_room(store, chat_for=lambda agent: writer, actor="user:m", stages=["triage", "extract"], use_ocr=False)

    class Other(Scripted):
        provider, model = "scripted2", "v2"

    review = {"tables": [{"table": 1, "ok": True, "issue": ""}]}
    HEALTH.reset()
    chain = FallbackChat([Scripted({"submit_review": [review] * 3}), Other({"submit_review": [review] * 3})],
                         labels=["Writer", "Other"])
    run_room(store, chat_for=lambda agent: chain, actor="user:m", stages=["check"], use_ocr=False)
    check = [a for a in store.authors() if a["stage"] == "check"]
    assert check and all(a["identity"] == "scripted2/v2" and a["note"] == "" for a in check)
    alone = Scripted({"submit_review": [review] * 3})                 # no other model: said, not hidden
    run_room(store, chat_for=lambda agent: alone, actor="user:m", stages=["check"], use_ocr=False, redo=["check"])
    last = [a for a in store.authors() if a["stage"] == "check"][-1]
    assert last["note"] == "not a second opinion: the same model wrote the extraction"
    HEALTH.reset()


def test_what_the_checker_finds_goes_back_to_the_extractor_once(tmp_path):
    # a new delivery, 2026-11-24: A9 saw a column described wrongly, but A8 never heard of it. Now each file A9 flags is
    # extracted again with the issue in its prompt, then checked again; one round only.
    store = _store(tmp_path)
    run_room(store, chat_for=lambda agent: None, actor="user:m", stages=["read"], use_ocr=False, workers=1)
    first = _extraction(store)
    model = Scripted({"submit_extraction": first + [first[0]],       # conc.tsv again, on the checker's word
                      "submit_review": [{"tables": [{"table": 1, "ok": False, "issue": "column 3 is the period"}]},
                                        {"tables": [{"table": 1, "ok": True, "issue": ""}]}]})
    prompts: list[str] = []
    complete = model.complete

    def recording(messages, tools):
        prompts.append(messages[1]["content"])
        return complete(messages, tools)

    model.complete = recording  # type: ignore[method-assign]
    doc = run_room(store, chat_for=lambda agent: model, actor="user:m", stages=["triage", "extract", "check"],
                   use_ocr=False)
    note = next(s["note"] for s in doc["stages"] if s["id"] == "check")
    assert "1 flagged file extracted again with the checker's issues; 0 still have issues" in note
    again = sorted({p for p in prompts if "A checker read your earlier description" in p})   # one conversation, two calls
    assert len(again) == 1 and "column 3 is the period" in again[0] and "File: conc.tsv" in again[0]
    assert store.reviews() == {}


def test_the_question_stage_reads_a_digest_of_every_file_first():
    """A6 took 2 to 9 minutes (2026-11-24): it spent its 14 turns opening files one by one and guessing part names. Code
    now gives it every file's parts and the lines that may state the question, products and design, quotable as
    written; a table's rows are left to its description."""
    from modeler_agents.dataroom.stages import question_digest
    from modeler_intake.room import read_file
    from modeler_project.dataroom.model import FileView

    letter = read_file("Cover letter.txt", (b"Dear team,\nWe ask for a PBPK model that supports the switch from the "
                                            b"clinical formulation (reference) to the commercial formulation (test).\n"
                                            b"Kind regards\n"))
    conc = read_file("conc.csv", b"Subject,Day,Time,Conc,Unit\n301,1,0.5,12.5,nmol/L\n301,1,1,30.1,nmol/L\n")
    docs = {f.path: (FileView(path=f.path, name=f.path, sha256=f.sha256, kind=f.kind, state=f.state), f.document)
            for f in (letter, conc)}
    digest = question_digest(docs, ["Cover letter.txt"])
    assert digest.index("=== Cover letter.txt") < digest.index("=== conc.csv")
    assert "We ask for a PBPK model that supports the switch" in digest         # the request, as written
    assert "parts: sheet:conc (3 lines)" in digest                              # a part named, never guessed
    assert "301 | 1 | 0.5" not in digest                                         # a table's row is not a quote
    assert len(question_digest(docs, budget=60)) < 200                          # past the budget, a file is named only
