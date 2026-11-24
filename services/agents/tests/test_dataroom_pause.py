"""Runs that pause and resume where they stopped (plan 2026-11-24 §4) and the hard cap for paid models (§2.4; the owner's
decision D3), with counting fake models: no real model is called. The delivery is the made-up Exampleamide
(`modeler_project.dataroom.synthetic`), never client data.

- a provider that does not answer pauses the run (never fails it), with where it stopped and when it resumes;
- a resumed run makes no model call for any (file × stage) answer already stored;
- the rests grow 10, 20, 40 minutes while a resume finishes nothing, then a person resumes it;
- a paid model's cap pauses the run; a chain never fails over to its free model on it; a free model is never capped;
- a switch in the middle of a step starts that step again on the next model, whose answer (and name) is the one kept;
- the checker does not check again a file whose review checked its extraction as it now stands.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

import pytest

from modeler_agents.dataroom import run_room
from modeler_agents.llm import HEALTH, ChatResult, FallbackChat, ToolCall
from modeler_agents.run import LLMUnavailableError
from modeler_agents.spend import SpendBudget, guard_paid
from modeler_project.dataroom import DataRoomStore
from modeler_project.dataroom.synthetic import delivery_zip, seed
from modeler_project.store import FileProjectStore
from modeler_project.workspace import Workspace

pytestmark = pytest.mark.req("T-47")

PAID = ("bedrock", "anthropic")
CARD = {"question": "Is the reformulated Exampleamide tablet bioequivalent to Refamide?", "products": [], "checklist": [],
        "quotes": []}
_FILE = re.compile(r"File: (.+?)(?: \(|\n|$)")


class Counting:
    """A chat model that answers each step through its submit tool with an answer code accepts (an empty extraction, a
    review with no issue), says DONE after "saved", and counts its calls by (submit tool, file). With `fail` (a submit
    tool and a number of its calls), it fails from there on like a rate-limited provider."""

    provider, model = "nvidia", "nemotron"

    def __init__(self, fail: tuple[str, int] | None = None, usage: dict[str, int] | None = None):
        self.calls: list[tuple[str, str]] = []
        self.fail = fail
        self.usage = usage or {}

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ChatResult:
        submit = next(t["function"]["name"] for t in tools if t["function"]["name"].startswith("submit_"))
        found = _FILE.search(messages[1]["content"])
        file = found.group(1) if found and submit != "submit_question" else ""
        if self.fail and submit == self.fail[0] and sum(1 for s, _f in self.calls if s == submit) >= self.fail[1]:
            raise LLMUnavailableError("nvidia unavailable: HTTP 429: Too Many Requests")
        self.calls.append((submit, file))
        last = messages[-1]
        if last["role"] == "tool" and str(last["content"]).startswith("saved") and "problems" not in last["content"]:
            return ChatResult(content="DONE", tool_calls=(), finish_reason="stop", usage=self.usage, model=self.model)
        answer = {"submit_question": CARD, "submit_triage": {"path": file, "purpose": "used", "reason": "the study's data"},
                  "submit_extraction": {"file": file}, "submit_review": {"tables": []},
                  "submit_writing": {"findings": {}, "requests": {}}}[submit]
        return ChatResult(content="", tool_calls=(ToolCall(id=f"c{len(self.calls)}", name=submit, arguments=answer,
                                                           raw_arguments=json.dumps(answer)),),
                          finish_reason="tool_calls", usage=self.usage, model=self.model)

    def files(self, submit: str) -> list[str]:
        return list(dict.fromkeys(f for s, f in self.calls if s == submit))


class PaidModel(Counting):
    provider, model = "bedrock", "anthropic.claude-opus-5-5"


def _read(tmp_path) -> tuple[DataRoomStore, list[str]]:
    store = DataRoomStore(Workspace(FileProjectStore(tmp_path), "t1", "p1"))
    store.add_upload("Exampleamide delivery.zip", delivery_zip(), by="user:m")
    run_room(store, chat_for=lambda agent: None, actor="user:m", stages=["read"], use_ocr=False, workers=1)
    used = [f.path for f in store.files() if not f.duplicate_of and not f.same_content_as and f.state in ("read", "partly_read")]
    return store, used


def _minutes(pause: dict[str, Any]) -> float:
    return (datetime.fromisoformat(pause["resume_at"]) - datetime.fromisoformat(pause["at"])).total_seconds() / 60


def test_a_provider_that_does_not_answer_pauses_the_run_and_the_resumed_run_asks_nothing_finished_again(tmp_path):
    store, used = _read(tmp_path)
    first = Counting(fail=("submit_extraction", 6))              # three files extracted (two calls each), then 429s
    doc = run_room(store, chat_for=lambda agent: first, actor="user:m", use_ocr=False)

    # paused, not failed: why in a plain sentence, where (the stage, its files done), and when it resumes by itself
    assert doc["state"] == "paused" and doc["error"] == "" and doc["finished_at"] is None
    pause = doc["pause"]
    assert (pause["reason"], pause["stage"], pause["where"], pause["per_file"]) == (
        "provider_unavailable", "extract", "extraction", True)
    assert (pause["done"], pause["total"]) == (3, len(used))
    assert pause["said"] == "nvidia/nemotron could not answer (too many requests: its rate limit was reached)."
    assert "HTTP 429" in pause["detail"] and _minutes(pause) == 10
    states = {s["id"]: s["state"] for s in doc["stages"]}
    assert states == {"read": "done", "question": "done", "triage": "done", "extract": "paused", "check": "waiting",
                      "write": "waiting"}
    done_before = first.files("submit_extraction")[:3]
    assert all(store.extraction(f.sha256) is not None for f in store.files() if f.path in done_before)

    # resumed (by the clock): nothing finished is asked of a model again, the rest is done once
    again = Counting()
    doc = run_room(store, chat_for=lambda agent: again, actor="system:dataroom-resume", resume="auto")
    assert doc["state"] == "done", doc.get("error")
    assert again.files("submit_question") == [] and again.files("submit_triage") == []
    assert sorted(again.files("submit_extraction")) == sorted(set(used) - set(done_before))
    assert not set(again.files("submit_extraction")) & set(done_before)
    assert len(again.files("submit_writing")) == 1
    extract = next(s for s in doc["stages"] if s["id"] == "extract")
    assert (extract["done"], extract["total"]) == (len(used), len(used))          # counted over the whole run
    assert doc["pause"] is None and doc["resumes"][0]["how"] == "auto" and doc["resumes"][0]["stage"] == "extract"
    assert [r["state"] for r in store.runs()] == ["done", "paused", "done"]        # the read, the pause, the end
    resumed = [r.event for r in store.ws.store.audit("t1").records() if r.event.action == "dataroom.run.resume"]
    assert len(resumed) == 1 and resumed[0].actor == "system:dataroom-resume"
    assert resumed[0].after["run_id"] == doc["run_id"]

    # and once everything is stored, a resume or a new run asks no model anything but the writing
    nothing = Counting()
    run_room(store, chat_for=lambda agent: nothing, actor="user:m", use_ocr=False)
    assert {s for s, _f in nothing.calls} == {"submit_writing"}


def test_the_rests_grow_while_a_resume_finishes_nothing_and_then_a_person_resumes_it(tmp_path):
    store, _used = _read(tmp_path)
    run_room(store, chat_for=lambda agent: Counting(fail=("submit_extraction", 0)), actor="user:m", use_ocr=False)
    rests = [_minutes(store.run()["pause"])]
    for _ in range(3):
        doc = run_room(store, chat_for=lambda agent: Counting(fail=("submit_extraction", 0)), actor="clock", resume="auto")
        rests.append(_minutes(doc["pause"]) if doc["pause"]["resume_at"] else None)
    assert rests == [10, 20, 40, None]                   # then it stays paused: a person resumes it
    doc = run_room(store, chat_for=lambda agent: Counting(fail=("submit_extraction", 0)), actor="user:m", resume="now")
    assert _minutes(doc["pause"]) == 10                  # a person's resume starts the rests again
    # a run that is not paused is not resumed
    done = run_room(store, chat_for=lambda agent: Counting(), actor="user:m", resume="now")
    assert done["state"] == "done"
    assert run_room(store, chat_for=lambda agent: Counting(), actor="user:m", resume="now") == store.run()


def test_a_chosen_model_that_cannot_be_used_pauses_and_no_model_at_all_is_skipped_as_before(tmp_path):
    store, _used = _read(tmp_path)
    problem = "this project's files may not be sent to NVIDIA: record the client's permission for it"
    doc = run_room(store, chat_for=lambda agent: problem if agent == "A7" else None, actor="user:m", use_ocr=False)
    assert doc["state"] == "paused" and doc["pause"]["reason"] == "no_model" and doc["pause"]["resume_at"] is None
    assert doc["pause"]["said"] == f"A7's model cannot be used: {problem}."
    assert {s["id"]: s["state"] for s in doc["stages"]}["question"] == "skipped"     # agents off for A6: as before


def test_a_paid_models_cap_pauses_the_run_and_a_raised_cap_lets_it_go_on(tmp_path):
    # $1 a call: 250,000 input tokens at Claude Opus 5.5's $4 a million
    store, used = _read(tmp_path)
    paid = PaidModel(usage={"input_tokens": 250_000, "output_tokens": 0})
    rows: list[dict[str, Any]] = []
    budget = SpendBudget(run_cap=2.5, month_cap=90, record=rows.append)
    doc = run_room(store, chat_for=lambda agent: guard_paid(paid, budget, PAID, agent), actor="user:m", use_ocr=False)
    assert doc["state"] == "paused" and doc["pause"]["reason"] == "budget_cap" and doc["pause"]["resume_at"] is None
    assert doc["pause"]["said"] == "The run reached its $2.5 limit for paid models (Admin → Limits)."
    assert len(paid.calls) == 3 and budget.run_spent == pytest.approx(3.0)     # the call that crosses the cap finishes
    assert [r["agent"] for r in rows] == ["A6", "A6", "A7"] and rows[0]["usd"] == pytest.approx(1.0)
    assert store.question()[0] is not None                                     # the question card was stored

    raised = SpendBudget(run_cap=100, month_cap=900, run_spent=budget.run_spent)
    again = PaidModel(usage={"input_tokens": 250_000, "output_tokens": 0})
    doc = run_room(store, chat_for=lambda agent: guard_paid(again, raised, PAID, agent), actor="admin", resume="now")
    assert doc["state"] == "done" and again.files("submit_question") == []
    assert sorted(again.files("submit_triage")) == sorted(used)                  # the step the cap stopped is done again

    # the month's cap, platform-wide: no paid call at all
    store2, _u = _read(tmp_path / "other")
    month = SpendBudget(run_cap=10, month_cap=90, month_spent=lambda: 90.0)
    never = PaidModel()
    doc = run_room(store2, chat_for=lambda agent: guard_paid(never, month, PAID, agent), actor="user:m", use_ocr=False)
    assert doc["pause"]["said"] == "Paid models reached this month's $90 limit (Admin → Limits)." and never.calls == []


def test_a_cap_never_fails_over_to_the_free_model_and_a_free_model_is_never_capped(tmp_path):
    HEALTH.reset()
    store, _used = _read(tmp_path)
    spent = SpendBudget(run_cap=1, month_cap=90, run_spent=1.0)
    paid, free = PaidModel(), Counting()
    chain = FallbackChat([paid, free], labels=["Claude", "Nemotron Ultra"])
    guarded = guard_paid(chain, spent, PAID, "A6")
    assert guarded is chain and guarded.models[1] is free and guarded.models[0] is not paid
    doc = run_room(store, chat_for=lambda agent: guarded if agent == "A6" else None, actor="user:m", use_ocr=False)
    assert doc["pause"]["reason"] == "budget_cap" and paid.calls == [] and free.calls == []
    alone = Counting()
    assert guard_paid(alone, spent, PAID) is alone                              # free: as it is, warn-only limits
    HEALTH.reset()


def test_a_switch_in_the_middle_of_a_step_starts_it_again_on_the_next_model_whose_answer_is_kept(tmp_path):
    # plan §4: the next model restarts the step (one file, one stage) rather than going on with the other's conversation
    HEALTH.reset()

    class Falls:
        provider, model = "litellm", "qwen-coder"

        def __init__(self):
            self.requests = 0

        def complete(self, messages, tools):
            self.requests += 1
            if self.requests == 1:            # submits a card with a quote no file holds: saved, with problems …
                card = {**CARD, "question": "the first model's card",
                        "quotes": [{"field": "question.regulator", "value": "FDA", "quote": "not in any file", "file": "x.md"}]}
                return ChatResult(content="", tool_calls=(ToolCall(id="a1", name="submit_question", arguments=card,
                                                                   raw_arguments=json.dumps(card)),),
                                  finish_reason="tool_calls", usage={}, model=self.model)
            raise LLMUnavailableError("litellm unavailable: no answer within 600 s")   # … then stops answering

    class Next(Counting):
        def __init__(self, submits: bool):
            super().__init__()
            self.submits, self.first_request = submits, 0

        def complete(self, messages, tools):
            self.first_request = self.first_request or len(messages)
            if not self.submits:
                return ChatResult(content="I cannot.", tool_calls=(), finish_reason="stop", usage={}, model=self.model)
            return super().complete(messages, tools)

    store, _used = _read(tmp_path)
    nxt = Next(submits=True)
    chain = FallbackChat([Falls(), nxt], labels=["Qwen Coder", "Nemotron Ultra"])
    run_room(store, chat_for=lambda agent: chain if agent == "A6" else None, actor="user:m", stages=["question"])
    card, _confirmed = store.question()
    assert card is not None and card.question == CARD["question"]              # the next model's card, not the first's
    assert nxt.first_request == 2                                              # its own start: instructions and task only
    assert store._read_json("question.json")["by"] == "agent:A6:Nemotron Ultra"
    assert [a["identity"] for a in store.authors() if a["stage"] == "question"] == ["nvidia/nemotron"]

    # the next model saves nothing: the first model's half-done card is not kept under the next model's name
    HEALTH.reset()
    store2, _u = _read(tmp_path / "other")
    chain = FallbackChat([Falls(), Next(submits=False)], labels=["Qwen Coder", "Nemotron Ultra"])
    doc = run_room(store2, chat_for=lambda agent: chain if agent == "A6" else None, actor="user:m", stages=["question"])
    assert store2.question()[0] is None and doc["state"] == "done"
    assert next(s["note"] for s in doc["stages"] if s["id"] == "question").startswith("no question card")
    HEALTH.reset()


def test_the_checker_does_not_check_again_a_file_whose_review_checked_its_extraction_as_it_stands(tmp_path):
    store, _used = _read(tmp_path)
    seed(store, by="test")                       # the extractions A8 would write, tables described
    first = Counting()
    run_room(store, chat_for=lambda agent: first, actor="user:m", stages=["check"])
    checked = first.files("submit_review")
    assert checked and all(store.review_current(f.sha256) for f in store.files() if f.path in checked)
    again = Counting()
    run_room(store, chat_for=lambda agent: again, actor="user:m", stages=["check"])
    assert again.calls == []
    # an extraction made again is checked again, alone
    one = next(f for f in store.files() if f.path == checked[0])
    extraction, agent = store.extraction(one.sha256)
    store.put_extraction(extraction, one.sha256, agent={**agent, "model": "another"})
    after = Counting()
    run_room(store, chat_for=lambda agent: after, actor="user:m", stages=["check"])
    assert after.files("submit_review") == [checked[0]]
    redo = Counting()
    run_room(store, chat_for=lambda agent: redo, actor="user:m", stages=["check"], redo=["check"])
    assert sorted(redo.files("submit_review")) == sorted(checked)
