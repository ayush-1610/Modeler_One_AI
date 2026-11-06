"""Score the intake agent (A1) on proposals with a known answer (plan 2026-11-05 §3.4: "A1 is measured on real proposals
(its evaluation set, P1's open item) so 'nominal' becomes a number").

    uv run python -m modeler_agents.evals.proposal_intake                  # the answer itself, through A1's tools
    uv run python -m modeler_agents.evals.proposal_intake --reader agent   # A1 on the model (MODELER_LLM_*, the server)

Each proposal is a synthetic technical proposal of the kind a sponsor sends (software test data, made-up studies), with
the answer a person writes for the fields Start needs:
- **stated**: the proposal says it; A1 must record it (EXTRACTED) with a quote code finds on the page;
- **implied**: the proposal implies it (the context of use, the applications, the formulation types, the routes); A1
  must propose it (DRAFTED) with the quote and why;
- **absent**: the proposal says nothing about it; A1 must leave it empty (a value there is invented);
- **the ICH M15 draft**: the ratings A1 suggests must fall in the range a reviewer would accept.
An enum, number or list must equal the answer (a list as a set; one of several accepted values when the answer gives
them); a text must hold the answer's words. The "answer" reader makes the tool calls a perfect reader would, through
A1's own tools, so every answer is known to pass code's checks; the agent is scored against the same answer, exactly as
the API runs it. The owner's real proposals are scored only on the server, with the answer a person writes for them.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

Kind = Literal["stated", "implied", "absent", "draft"]


@dataclass(frozen=True)
class Expect:
    path: str
    kind: Kind
    value: Any = None                          # an enum, number or list; a tuple of values: any one of them
    words: tuple[str, ...] = ()                # a text: words its value must hold
    quote: str = ""                            # the answer reader's quote (stated, implied)
    why: str = ""                              # the answer reader's reason (implied)
    unit: str = ""


@dataclass(frozen=True)
class Proposal:
    name: str
    drug: str
    text: str
    expects: tuple[Expect, ...]
    risk_texts: tuple[str, str] = ("", "")     # the answer reader's "how the model is used", "what a wrong decision means"
    why_tier: str = ""                         # and why the stricter tier fits, when its ratings differ


@dataclass
class Score:
    proposal: str
    right: list[str] = field(default_factory=list)
    wrong: list[str] = field(default_factory=list)       # a value other than the answer's
    missed: list[str] = field(default_factory=list)      # stated or implied, left empty
    invented: list[str] = field(default_factory=list)    # absent, yet set
    status: list[str] = field(default_factory=list)      # right value, recorded as the wrong kind (stated as a draft …)

    @property
    def checks(self) -> int:
        return len(self.right) + len(self.wrong) + len(self.missed) + len(self.invented)


FOOD_EFFECT = """Technical proposal: PBPK modelling of Exampleamide food effect

Background. Exampleamide 25 mg immediate-release film-coated tablets are approved for use in the fasted state.

Objective. To predict the effect of a high-fat meal on the exposure (AUC and Cmax) of the 25 mg immediate-release tablet.

Approach. A PBPK model will be built in PK-Sim from the client's single-dose studies, in which healthy volunteers received
a single oral dose of 25 mg under fasted conditions, and verified against the published fed study.

Use of the results. The predicted fed/fasted ratios will support the labelling of the tablet with respect to food, in
place of a dedicated clinical food-effect study of the new strength.
"""

DDI = """Proposal for a PBPK-based drug-drug interaction assessment of Ziprolamide

Ziprolamide is eliminated mainly by CYP3A4. The sponsor asks whether co-administration with the strong CYP3A4 inhibitor
itraconazole requires a dose adjustment.

Scope of work. Build and verify a PBPK model of Ziprolamide from the sponsor's intravenous and oral studies (10 mg IV
infusion over 30 minutes; 40 mg oral capsule, fasted), then simulate the interaction with itraconazole 200 mg once daily.

Deliverables. A modelling report suitable for submission to the FDA, supporting the drug interaction section of the label.
"""

PAEDIATRIC = """Statement of work: paediatric dose selection for Exampletide oral suspension

The sponsor plans a paediatric study of Exampletide oral suspension in children aged 2 to 11 years. The adult PBPK model
will be extrapolated to children to select starting doses that match the adult exposure after a 100 mg oral dose.

The model output will inform the paediatric investigation plan; the doses will be confirmed in the clinical study.
"""

VBE = """Technical proposal: virtual bioequivalence of Exampleamide ER 50 mg tablets

The client has developed a generic Exampleamide extended-release 50 mg tablet. Two pilot BE studies in healthy volunteers
(single oral dose, fasting) failed to show bioequivalence for Cmax against the reference product.

Objective: to use PBPK modelling with the dissolution profiles of both products to run virtual bioequivalence trials,
and to support a request to waive an additional clinical BE study of the 25 mg strength.
"""

PROPOSALS: tuple[Proposal, ...] = (
    Proposal("food effect of an IR tablet", "Exampleamide", FOOD_EFFECT, (
        Expect("qoi.text", "stated", words=("high-fat", "25 mg"),
               quote="To predict the effect of a high-fat meal on the exposure (AUC and Cmax) of the 25 mg immediate-release "
                     "tablet", value=None),
        Expect("qoi.context_of_use", "implied", words=("label",),
               quote="will support the labelling of the tablet with respect to food",
               why="the predicted fed/fasted ratios are to support the food statement of the label"),
        Expect("qoi.applications", "implied", value=["APP-12 food effect"], quote="predict the effect of a high-fat meal",
               why="predicting a meal's effect on exposure is a food-effect application"),
        Expect("scope.formulation_types", "implied", value=["ir_tablet"], quote="25 mg immediate-release film-coated tablets",
               why="the only product the proposal names is an immediate-release tablet"),
        Expect("scenarios[0].route", "stated", value="oral", quote="a single oral dose of 25 mg"),
        Expect("scenarios[0].dose", "stated", value=25.0, unit="mg", quote="a single oral dose of 25 mg"),
        Expect("scenarios[0].food_state", "stated", value="fasted", quote="under fasted conditions"),
        Expect("drug.salt_form", "absent"),
        Expect("m15.influence_suggested", "draft", value=("medium", "high")),
        Expect("m15.consequence_suggested", "draft", value=("medium", "high")),
    ), risk_texts=("The labelling claim rests on the model in place of a clinical food-effect study of the new strength",
                   "A wrong prediction would misstate how patients should take the tablet with food"),
       why_tier="The model replaces a clinical study for a labelling claim, so the stricter risk is the one to meet"),
    Proposal("a CYP3A4 interaction for the label", "Ziprolamide", DDI, (
        Expect("qoi.text", "stated", words=("itraconazole",),
               quote="whether co-administration with the strong CYP3A4 inhibitor itraconazole requires a dose adjustment"),
        Expect("qoi.context_of_use", "implied", words=("label",),
               quote="supporting the drug interaction section of the label",
               why="the report is to support the interaction section of the label for submission"),
        Expect("qoi.applications", "implied", value=["APP-03 enzyme DDI"], quote="strong CYP3A4 inhibitor itraconazole",
               why="an interaction through CYP3A4 inhibition is an enzyme-mediated DDI"),
        Expect("scope.formulation_types", "implied", value=["ir_capsule", "solution"],
               quote="10 mg IV infusion over 30 minutes; 40 mg oral capsule, fasted",
               why="an IV infusion is given as a solution; the oral capsule is not said to be modified release"),
        Expect("scenarios[0].route", "stated", value="iv_infusion", quote="10 mg IV infusion over 30 minutes"),
        Expect("scenarios[1].route", "stated", value="oral", quote="40 mg oral capsule"),
        Expect("drug.salt_form", "absent"),
        Expect("m15.influence_suggested", "draft", value=("medium", "high")),
        Expect("m15.consequence_suggested", "draft", value=("high",)),
    ), risk_texts=("The dose recommendation with itraconazole in the label would rest mainly on the model",
                   "A wrong recommendation could expose patients to toxic concentrations with a strong inhibitor"),
       why_tier="A label dose adjustment with a strong inhibitor rests on the model, so the stricter risk applies"),
    Proposal("paediatric extrapolation of a suspension", "Exampletide", PAEDIATRIC, (
        Expect("qoi.text", "stated", words=("starting doses", "adult exposure"),
               quote="to select starting doses that match the adult exposure after a 100 mg oral dose"),
        Expect("qoi.context_of_use", "implied", words=("paediatric",),
               quote="The model output will inform the paediatric investigation plan",
               why="the model informs the paediatric investigation plan, and the doses are confirmed clinically"),
        Expect("qoi.applications", "implied", value=["APP-06 pediatric extrapolation"],
               quote="The adult PBPK model will be extrapolated to children",
               why="extrapolating the adult model to children is a paediatric extrapolation"),
        Expect("scope.formulation_types", "implied", value=["suspension"], quote="Exampletide oral suspension",
               why="the product named is an oral suspension"),
        Expect("drug.salt_form", "absent"),
        Expect("m15.influence_suggested", "draft", value=("low", "medium")),
        Expect("m15.consequence_suggested", "draft", value=("medium", "high")),
    ), risk_texts=("The model proposes starting doses that a clinical study then confirms",
                   "A wrong starting dose could under- or over-expose children until the study corrects it"),
       why_tier="Children are dosed from the model before the study confirms it, so the stricter risk is kept"),
    Proposal("virtual bioequivalence and a waiver", "Exampleamide", VBE, (
        Expect("qoi.text", "stated", words=("bioequivalence",),
               quote="to use PBPK modelling with the dissolution profiles of both products to run virtual bioequivalence "
                     "trials"),
        Expect("qoi.context_of_use", "implied", words=("waive",),
               quote="to support a request to waive an additional clinical BE study of the 25 mg strength",
               why="the virtual trials are to support a waiver of a clinical BE study"),
        Expect("qoi.applications", "implied", value=["APP-14 virtual bioequivalence"],
               quote="run virtual bioequivalence trials", why="the objective is virtual bioequivalence trials"),
        Expect("scope.formulation_types", "implied", value=["mr"], quote="extended-release 50 mg tablet",
               why="an extended-release tablet is a modified-release product"),
        Expect("scenarios[0].food_state", "stated", value="fasted", quote="single oral dose, fasting"),
        Expect("drug.salt_form", "absent"),
        Expect("m15.influence_suggested", "draft", value=("high",)),
        Expect("m15.consequence_suggested", "draft", value=("medium", "high")),
    ), risk_texts=("The waiver of a clinical BE study would rest on the model alone",
                   "A wrong conclusion would let a product that is not bioequivalent reach patients"),
       why_tier="A waiver in place of a clinical study rests on the model alone, so the stricter risk applies"),
)


# --- the answer, as tool calls through A1's own tools -----------------------------------------------------------------

class AnswerModel:
    """A perfect reader: the tool calls the answer implies, in one turn each, then done (no model)."""

    provider, model = "answer", "answer"

    def __init__(self, proposal: Proposal, sha: str):
        from modeler_agents.llm import ToolCall

        def call(i: int, name: str, args: dict[str, Any]) -> ToolCall:
            return ToolCall(id=f"a{i}", name=name, arguments=args)

        calls, i = [], 0
        for e in proposal.expects:
            if e.kind not in ("stated", "implied"):
                continue
            value = e.value if e.value is not None else e.quote
            if e.kind == "stated":
                args = {"path": e.path, "value": value, "quote": e.quote, "doc_sha256": sha, "page": 1}
                calls.append(call(i, "propose_field", {**args, **({"unit": e.unit} if e.unit else {})}))
            else:
                calls.append(call(i, "propose_implied", {"path": e.path, "value": value, "quote": e.quote,
                                                         "doc_sha256": sha, "page": 1, "why": e.why}))
            i += 1
        ratings = {e.path: e.value[-1] for e in proposal.expects if e.kind == "draft"}
        if ratings:
            calls.append(call(i, "draft_risk_assessment", {
                "influence": ratings["m15.influence_suggested"], "consequence": ratings["m15.consequence_suggested"],
                "how_the_model_is_used": proposal.risk_texts[0], "what_a_wrong_decision_means": proposal.risk_texts[1],
                "why_this_tier": proposal.why_tier}))
        self.turns = [[c] for c in calls]

    def complete(self, messages, tools):
        from modeler_agents.llm import ChatResult

        calls = tuple(self.turns.pop(0)) if self.turns else ()
        return ChatResult(content="" if calls else "done", finish_reason="", tool_calls=calls,
                          usage={"input_tokens": 0, "output_tokens": 0}, model="answer")


# --- the score ------------------------------------------------------------------------------------------------------

def _matches(e: Expect, value: Any) -> bool:
    if e.value is None:
        text = str(value or "").lower()
        return bool(text) and all(w.lower() in text for w in e.words)
    if isinstance(e.value, tuple):
        return value in e.value
    if isinstance(e.value, list):
        return set(value or []) == set(e.value)
    if isinstance(e.value, float):
        try:
            return abs(float(value) - e.value) < 1e-9
        except (TypeError, ValueError):
            return False
    return value == e.value


def read(proposal: Proposal, model_for: Callable[[Proposal, str], Any], *, max_turns: int = 80) -> Any:
    """A1 on one proposal, in an empty project, as the API runs it; the brief it leaves."""
    from modeler_agents.proposal_intake import IntakeContext, run_proposal_intake
    from modeler_project import FileProjectStore, Workspace
    from modeler_project.brief import empty_brief
    from modeler_project.documents import DocumentLibrary, document_record

    with tempfile.TemporaryDirectory() as root:
        library = DocumentLibrary(Workspace(FileProjectStore(root), "eval", "p1"))
        doc = library.add(proposal.text.encode(), "proposal.md", role="proposal", by="eval")
        ctx = IntakeContext(library=library, brief=empty_brief(proposal.drug, by="eval"), actor="agent:eval")
        return run_proposal_intake(model_for(proposal, document_record(doc).sha256), ctx, max_turns=max_turns).brief


def score(proposal: Proposal, brief: Any) -> Score:
    """The brief A1 left against the answer."""
    from modeler_project.brief import FieldStatus

    result = Score(proposal.name)
    for e in proposal.expects:
        record = brief.get(e.path)
        value = record.value if record.status not in (FieldStatus.MISSING, FieldStatus.NOT_APPLICABLE) else None
        label = f"{e.path} ({e.kind})"
        if e.kind == "absent":
            (result.invented if value not in (None, "", []) else result.right).append(label)
        elif value in (None, "", []):
            result.missed.append(label)
        elif not _matches(e, value):
            result.wrong.append(f"{label}: {value!r}")
        else:
            result.right.append(label)
            wanted = {"stated": FieldStatus.EXTRACTED, "implied": FieldStatus.DRAFTED, "draft": FieldStatus.DRAFTED}[e.kind]
            if record.status is not wanted:
                result.status.append(f"{label}: {record.status.value}")
    return result


def evaluate(model_for: Callable[[Proposal, str], Any]) -> list[Score]:
    return [score(p, read(p, model_for)) for p in PROPOSALS]


def report(scores: list[Score]) -> str:
    total = sum(s.checks for s in scores)
    right = sum(len(s.right) for s in scores)
    counts = {kind: sum(len(getattr(s, kind)) for s in scores) for kind in ("wrong", "missed", "invented", "status")}
    lines = [(f"{right} of {total} fields right ({100 * right / total:.0f} %); {counts['wrong']} wrong, "
              f"{counts['missed']} missed, {counts['invented']} invented, {counts['status']} recorded as the wrong kind")]
    for s in scores:
        lines.append(f"  {s.proposal}: {len(s.right)}/{s.checks}")
        lines += [f"    {kind}: {item}" for kind in ("wrong", "missed", "invented", "status") for item in getattr(s, kind)]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reader", choices=("answer", "agent"), default="answer")
    parser.add_argument("--json", help="also write the scores here, as JSON")
    args = parser.parse_args(argv)
    if args.reader == "agent":
        from modeler_agents.llm import chat_model_from_env

        model = chat_model_from_env()
        if model is None:
            print("no model configured: set MODELER_LLM_PROVIDER (and its key) and run this on the server", file=sys.stderr)
            return 2
        scores = evaluate(lambda _p, _sha: model)
    else:
        scores = evaluate(AnswerModel)
    print(f"reader: {args.reader}\n{report(scores)}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump([{"proposal": s.proposal, "right": s.right, "wrong": s.wrong, "missed": s.missed,
                        "invented": s.invented, "status": s.status} for s in scores], handle, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
