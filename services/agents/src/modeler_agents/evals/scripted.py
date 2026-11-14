"""One scripted model for the intake's tests (contracts §8.5, §10): it stands in for the configured model, turn by turn.

`Scripted(turns)` answers each model turn with the next list of tool calls, `(tool name, arguments)`; an empty list (or
no list left) ends the run with no tool call. It keeps what code answered (`answers`: every tool answer, in order) and
what it was sent (`received`: the messages of each turn), so a test asserts on the tool answers ("ACCEPTED",
"REJECTED: ...", "REFUSED: ...": `run_tool_loop` never raises a handler's error) and reads what a model would have
seen (no digit of a table body in a table mapper's prompt). Software test scaffolding: never a model's judgement.

`answers` is read from the messages of the next turn, so a run cut short at `max_turns` (INCOMPLETE) would miss its
last turn's answers: pass `log_step=model.log_step` to the agent and every answer is kept as the loop logs it.
"""

from __future__ import annotations

import copy
from typing import Any

from modeler_agents.llm import ChatResult, ToolCall


class Scripted:
    """A `ChatModel` that plays a script of tool calls (see the module docstring)."""

    provider = "scripted"
    model = "scripted"

    def __init__(self, turns: list[list[tuple[str, dict[str, Any]]]]):
        self.turns = [list(turn) for turn in turns]
        self.answers: list[str] = []
        self.received: list[list[dict[str, Any]]] = []
        self.logged = False                     # True once log_step keeps the answers (then the messages do not)

    def log_step(self, step: dict[str, Any]) -> None:
        """The agent run's step log, as `run_tool_loop` calls it: every tool answer is kept, the last turn's included."""
        self.logged = True
        if step.get("type") == "tool_result":
            self.answers.append(str(step.get("result", "")))

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ChatResult:
        self.received.append(copy.deepcopy(messages))
        if not self.logged:
            tool_answers = [str(m.get("content", "")) for m in messages if m.get("role") == "tool"]
            self.answers += tool_answers[len(self.answers):]
        calls = self.turns.pop(0) if self.turns else []
        turn = len(self.received)
        return ChatResult(content="done" if not calls else "", finish_reason="tool_calls" if calls else "stop",
                          model=self.model, usage={"input_tokens": 1, "output_tokens": 1},
                          tool_calls=tuple(ToolCall(id=f"t{turn}c{i}", name=name, arguments=dict(arguments))
                                           for i, (name, arguments) in enumerate(calls)))

    def system(self) -> str:
        """The system prompt of the first turn ("" before any turn)."""
        return next((str(m["content"]) for m in self.received[0] if m.get("role") == "system"), "") if self.received else ""

    def user(self) -> str:
        """The user message of the first turn: everything the model was shown of its input ("" before any turn)."""
        return next((str(m["content"]) for m in self.received[0] if m.get("role") == "user"), "") if self.received else ""
