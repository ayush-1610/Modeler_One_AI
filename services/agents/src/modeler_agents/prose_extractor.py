"""Agent A4 · Prose facts (contracts §6.2, plan §7.5): the design facts a report states in sentences, under a strict check.

Synopses and design sections state facts in sentences (the dose, the subjects, the route, the fasting state, the
regimen, the batch). The model is shown a file's prose paragraphs, never a table's text (a paragraph whose locator is a
table's is left out), and states each fact with `state_fact`: the field, the value, the quote that states it, the
paragraph, and the study and arm when the paragraph or its heading names them. Code checks each one (`check`, a
closure the pipeline builds over `modeler_intake.mapping.prose_check.check_prose_fact`): the quote in the paragraph,
the field's label and exactly one number of its class in one clause, the labels written there. The model hears
"ACCEPTED: <code's reading>" or "REFUSED: <why>". The facts returned are the check's (code's numbers, units, names and
spans), never the model's arguments; each stands on its own check, so a conversation cut short still returns the facts
code accepted before it stopped (status says how it ended). Each lands in the ledger against its study at the level
`prose`, never directly on a dataset.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict

from modeler_agents.llm import ChatModel, Tool, run_tool_loop
from modeler_intake import fields as vocabulary
from modeler_intake.mapping.prose_check import ProseFactError
from modeler_intake.mapping_spec import ProseCheck, ProseFact, ProseParagraph
from modeler_intake.source_model import number_text

SYSTEM_PROMPT = """You read the prose of a client's clinical or product report (a synopsis, a design section, a certificate) and state the facts it gives, one at a time, each with the words that state it. A program checks every fact against its paragraph and keeps only what the paragraph itself states. You are shown paragraphs of text only, never a table.

Call state_fact once per fact:
- field: one of the fields listed in the message.
- value: a number as the sentence writes it, without its unit (code reads the unit after it; never convert a unit, never turn 45% into 0.45); a choice as listed; a name exactly as written.
- quote: the clause or sentence that states it, copied word for word from the paragraph (at least 12 characters). The field's label (dose, subjects, rpm, batch ...) and exactly one number of the field's kind must stand in the same clause: a clause ends at ";", at "." followed by a space, and at " and ". A sentence such as "mean 12.4 (SD 3.1)" states two numbers and is not a fact of either.
- paragraph: the paragraph's number as shown.
- study and arm: the study or arm the fact belongs to, only when that paragraph or its heading writes it, exactly as written; leave them out otherwise.

Code answers ACCEPTED with its own reading, or REFUSED with why. Do not repeat a refused fact unchanged; a fact the paragraph does not state in one clause is left out. State every fact of the listed fields that the paragraphs give, calling several tools in one turn, then answer with one line on what you found."""

PROMPT_SHA256 = hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()

# a paragraph's own locator (a Word paragraph, a text line, PDF words), never a table's (s:, p:/t:, d:t:)
_PROSE_LOCATOR = re.compile(r"(d:p:|x:l:|p:[1-9][0-9]*/w:)")

_TOOL = {
    "type": "object", "required": ["field", "value", "quote", "paragraph"],
    "properties": {
        "field": {"type": "string", "description": "one of the fields listed"},
        "value": {"type": ["number", "string"], "description": "the number as written (no unit), the choice, or the name"},
        "quote": {"type": "string", "description": "the clause or sentence that states it, word for word"},
        "paragraph": {"type": "integer", "description": "the paragraph's number as shown"},
        "study": {"type": "string", "description": "the study, only as the paragraph or its heading writes it"},
        "arm": {"type": "string", "description": "the arm, only as the paragraph or its heading writes it"}}}


class ProseReading(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    facts: tuple[ProseFact, ...]             # the check's facts (code's readings and spans), in the order accepted
    rejected: tuple[str, ...]                # every "REFUSED: ..." answer, in order
    status: str                              # the loop's: COMPLETED, INCOMPLETE or LLM_UNAVAILABLE
    usage: dict[str, int]
    prompt_sha256: str


@dataclass
class _Reading:
    paragraphs: dict[int, ProseParagraph]
    fields: tuple[str, ...]
    check: ProseCheck
    facts: list[ProseFact] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)

    def refuse(self, why: str) -> str:
        answer = f"REFUSED: {why}"
        self.rejected.append(answer)
        return answer


def _shown(fact: ProseFact) -> str:
    value = number_text(fact.value) if isinstance(fact.value, float) else fact.value
    labels = "".join(f", {kind} {label!r}" for kind, label in (("study", fact.study_label), ("arm", fact.arm_label)) if label)
    return f"{fact.field} = {value}{' ' + fact.unit if fact.unit else ''}{labels}"


def state_fact(ctx: _Reading, *, field: Any, value: Any, quote: Any, paragraph: Any, study: Any = None,
               arm: Any = None) -> str:
    if field not in ctx.fields:
        return ctx.refuse(f"{field!r} is not one of the fields asked: {', '.join(ctx.fields)}")
    if isinstance(paragraph, bool) or not isinstance(paragraph, int | str) or not str(paragraph).strip().isdigit() \
            or int(paragraph) not in ctx.paragraphs:
        return ctx.refuse(f"paragraph {paragraph!r} is not one of the paragraphs shown "
                          f"({', '.join(str(i) for i in ctx.paragraphs)})")
    for name, label in (("study", study), ("arm", arm)):
        if label is not None and not isinstance(label, str):
            return ctx.refuse(f"{name} is a label as the paragraph writes it, not {label!r}")
    try:
        fact = ctx.check(field, value, quote if isinstance(quote, str) else "", int(paragraph), study or None, arm or None)
    except ProseFactError as exc:
        return ctx.refuse(str(exc))
    if any(f.field == fact.field and f.locator == fact.locator and f.study_label == fact.study_label
           and f.arm_label == fact.arm_label for f in ctx.facts):
        return f"ACCEPTED (already stated): {_shown(fact)}"
    ctx.facts.append(fact)
    return f"ACCEPTED: {_shown(fact)}"


def _describe(name: str) -> str:
    definition = vocabulary.field(name)
    if definition is None:
        raise ValueError(f"{name!r} is not a field of the ledger's vocabulary")
    kind = {"number": "a number", "integer": "a whole number", "choice": "one of " + ", ".join(definition.choices),
            "name": "a name as written", "text": "a text as written"}[definition.value]
    unit = "" if definition.unit_class in ("none", "other", "ratio") else f", with its {definition.unit_class} unit"
    return f"- {name}: {kind}{unit}"


def _paragraph(p: ProseParagraph) -> str:
    heading = f' (under the heading "{p.heading}")' if p.heading.strip() else ""
    return f"Paragraph {p.index}{heading}:\n{p.text}"


def extract_prose(model: ChatModel, *, paragraphs: Sequence[ProseParagraph], fields: Sequence[str], check: ProseCheck,
                  max_turns: int = 8, log_step: Callable[[dict[str, Any]], None] = lambda step: None,
                  context: str = "") -> ProseReading:
    """Ask the model for the facts of `fields` the paragraphs state; `check` (field, value, quote, paragraph number,
    study, arm) -> ProseFact judges each one and raises ProseFactError for a fact it refuses (module docstring).
    A paragraph whose locator is a table's is never shown. `context` is appended to the user message."""
    shown = {p.index: p for p in paragraphs if _PROSE_LOCATOR.match(p.locator) and p.text.strip()}
    asked = tuple(dict.fromkeys(fields))
    described = [_describe(name) for name in asked]
    ctx = _Reading(paragraphs=shown, fields=asked, check=check)
    tool = Tool(name="state_fact", description="State one fact a paragraph gives, with the clause that states it. Code "
                "checks it against the paragraph and answers ACCEPTED with its reading or REFUSED with why.",
                parameters=_TOOL, handler=lambda **kw: state_fact(ctx, **kw))
    user = ("Fields to look for:\n" + "\n".join(described) + "\n\n" + "\n\n".join(_paragraph(p) for p in shown.values()))
    if context:
        user += f"\n\n{context}"
    if not shown or not asked:
        return ProseReading(facts=(), rejected=(), status="COMPLETED", usage={"input_tokens": 0, "output_tokens": 0},
                            prompt_sha256=PROMPT_SHA256)
    outcome = run_tool_loop(model, system=SYSTEM_PROMPT, user=user, tools=[tool], max_turns=max_turns, log_step=log_step)
    return ProseReading(facts=tuple(ctx.facts), rejected=tuple(ctx.rejected), status=outcome.status,
                        usage=dict(outcome.usage), prompt_sha256=PROMPT_SHA256)
