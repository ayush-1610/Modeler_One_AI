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
