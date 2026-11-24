"""The Data room's five agents (plan 2026-11-21 v2 §9). Each reads a file through tools over its numbered lines and
answers only through a submit tool whose handler runs code's checks: a refused quote, a table line that cannot be
placed, an unknown field is sent straight back to the model, which corrects and submits again. The model never types
a value into the room: it says where a value is and what it means; code reads it.

Each stage is `stage(store, model, *, actor, redo, step) -> note`, called by `run.run_room`.

The per-file stages (A7 triage, A8 extraction, A9 check) look in the tenant's answer cache first
(`modeler_project.dataroom.answer_cache`): a file already answered with every input the same (the file, its reading,
the prompt, the model and its effort, the question card's fields the prompt uses …) is answered from it, with no model
call, and the author record says so. A stage asked to redo (`redo`) asks the model again.

Their requests start with the same bytes for every file of a delivery, so a provider's prompt cache serves the rest of
the files: one fixed instruction text and one fixed tool list (a tool takes the file as an argument; no name,
description or schema names it), then the delivery's block (`shared`: the question, the products, the checklist), then
the file's own block last.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from typing import Any

from pydantic import BaseModel, ValidationError

from modeler_agents.dataroom.run import unavailable
from modeler_agents.llm import ChatModel, LoopOutcome, Tool, run_tool_loop
from modeler_intake.room import LINES_VERSION, Part, document_parts, parts_sha256, unmarked
from modeler_intake.room_specs import FIELDS, ROLES, TOPICS, Extraction, FileTriage, QuestionCard
from modeler_intake.source_model import SourceDocument
from modeler_project.dataroom import room_view
from modeler_project.dataroom.answer_cache import AnswerCache, AnswerKey, CachedAnswer, stable_sha256
from modeler_project.dataroom.clinical import colliding_samples
from modeler_project.dataroom.extract import check_fact, read_table
from modeler_project.dataroom.model import FileView
from modeler_project.dataroom.store import DataRoomStore

# dataroom-5: one instruction text for every file (the extractor's fields and table roles moved to the file's block),
# the delivery's block before the file's, and the answer cache (plan 2026-11-24 §5 items 2 and 3). A change of any
# prompt text, tool or constant that shapes a request (MAX_LINES, PREVIEW_LINES, FOCUS_CHARS' use …) is a new version:
# the answer cache's key holds it.
PROMPT_VERSION = "dataroom-5"
MAX_LINES = 120          # lines one read returns
PREVIEW_LINES = 80       # lines of each of the first parts the triage agent sees (40 misjudged a LIMS export, 2026-11-24)

Step = Callable[..., None]

_COMMON = """You work in a PBPK/PBBM modelling team (PK-Sim, the Open Systems Pharmacology suite). A client sent a
delivery of files: clinical study reports, concentration and PK tables, protocols, dissolution and solubility reports,
compositions, specifications, labels, literature. Every file has been read for you into numbered parts (p<page> for a
PDF page, sheet:<name> for a sheet or a delimited export, body for Word and text files) of numbered lines; the cells of
a line are separated by " | ". Scanned pages were read by OCR and may hold small reading errors.

Rules that always hold:
- Never type a value for the room. Say WHERE a value is (file, part, lines, cell positions) and WHAT it means; code
  reads every number from the cells you name. A fact is a value with the verbatim quote (one to three lines, copied
  exactly) it comes from; code checks the quote is in the file and the value in the quote.
- Never guess. What a file does not say stays unsaid; a missing input becomes a data request, not an assumption.
- Use the tools to look; answer only by calling the submit tool. If it answers with problems, fix them and submit
  again. When it answers "saved", reply with the single word DONE."""


def _parts(doc: SourceDocument) -> list[Part]:
    return document_parts(doc)


def _numbered(part: Part, first: int, last: int) -> str:
    lines = [ln for ln in part.lines if first <= ln.number <= last][:MAX_LINES]
    return "\n".join(f"{part.name} L{ln.number}: {ln.text}" for ln in lines) or "(no lines there)"


def _outline(doc: SourceDocument, *, preview: int = 3, max_parts: int = 400) -> str:
    out = []
    for part in _parts(doc)[:max_parts]:
        head = " / ".join(ln.text[:90] for ln in part.lines[:preview])
        out.append(f"{part.name}: {len(part.lines)} lines · {head}")
    return "\n".join(out) or "(nothing read)"


# words that mark a page as holding a topic's inputs: code picks the pages an agent reads first (fewer tokens, the
# same answer: the agent may still open any other page with its tools)
TOPIC_WORDS: dict[str, tuple[str, ...]] = {
    "clinical_design": ("crossover", "cross-over", "randomi", "period", "washout", "open label", "single dose", "sequence"),
    "clinical_disposition": ("completed", "withdrawn", "dropout", "drop-out", "discontinu", "dosed in", "enrolled",
                             "statistical analysis", "excluded"),
    "clinical_demographics": ("age", "weight", "height", "bmi", "male", "female", "asian", "caucasian", "ethnic"),
    "dosing_and_meals": ("fast", "meal", "breakfast", "lunch", "water", "administered", "dose"),
    "bioanalysis": ("lloq", "loq", "quantitation", "lc-ms", "calibration", "analyte"),
    "clinical_concentrations": ("concentration", "ng/ml", "time (h", "hrs"),
    "clinical_pk": ("cmax", "auc", "tmax", "t1/2", "half-life"),
    "be_statistics": ("90%", "confidence interval", "ratio", "geometric", "bioequivalen"),
    "dissolution": ("dissolution", "rpm", "paddle", "basket", "% drug", "released", "vessel"),
    "solubility": ("solubility", "mg/ml", "saturation"),
    "particle_size": ("d10", "d50", "d90", "particle size", "psd"),
    "composition": ("mg/tablet", "mg/tab", "composition", "excipient", "qty", "% w/w", "core", "quantity"),
    "manufacturing": ("granulat", "blend", "compression", "coating", "process"),
    "drug_substance": ("molecular weight", "pka", "log p", "logp", "melting", "polymorph", "bcs", "hydrochloride"),
    "adme": ("bioavailability", "protein binding", "metaboli", "cyp", "half-life", "excreted", "volume of distribution",
             "clearance", "food"),
    "label": ("indications", "dosage", "pharmacokinetics", "absorption", "distribution", "metabolism", "elimination"),
    "question": ("objective", "purpose", "scope", "pbbm", "pbpk", "bioequivalen", "reformulat", "health canada", "fda",
                 "ema", "request", "deliverable", "context of use", "virtual"),
}
FOCUS_CHARS = 14000      # the pages shown to the extractor up front (about 3,500 tokens); run_room(focus_chars=…)



def _loop(store: DataRoomStore, stage: str, file: str, model: ChatModel, saved: list[BaseModel], **kw: Any) -> Any:
    """`run_tool_loop` with each turn written to the room's record of the agents' turns (which model answered, each
    tool's answer, each switch to another model).

    One step (one file in one stage, or the delivery's question or writing) is one model's work: when the chain moves to
    its next model in the middle of it, the step starts again from its beginning there, and what the earlier model
    submitted is dropped (`saved` emptied), so the answer kept and its author are the next model's (plan 2026-11-24 §4).
    A step that no model of the chain could answer, for a reason that passes (no answer in time, a rate limit or a
    quota, the service down or refusing its key), and that saved nothing, pauses the run (`RunPaused`): nothing of it is
    kept, and the run resumes at this step. A request too long for the model is the caller's to shorten."""
    def log(step: dict[str, Any]) -> None:
        store.log_agent_step(stage=stage, file=file, model=getattr(model, "label", f"{model.provider}/{model.model}"),
                             step=step)
    outcome = run_tool_loop(model, log_step=log, on_restart=saved.clear, **kw)
    if outcome.status == "LLM_UNAVAILABLE" and outcome.failure != "context" and not saved:
        raise unavailable(outcome.answered_by, outcome.error)
    return outcome

def _too_large(error: str) -> bool:
    return "413" in error or any(w in error.lower() for w in ("too large", "context length", "context window"))


def _focus(doc: SourceDocument, topics: Sequence[str], budget: int = FOCUS_CHARS) -> str:
    """The lines of the pages most likely to hold the topics' inputs, best first, within the budget; the whole file
    when it fits."""
    parts = _parts(doc)
    whole = [(p, "\n".join(f"{p.name} L{ln.number}: {ln.text}" for ln in p.lines)) for p in parts]
    if sum(len(t) for _p, t in whole) <= budget:
        return "\n\n".join(t for _p, t in whole)
    words = [w for t in (topics or list(TOPIC_WORDS)) for w in TOPIC_WORDS.get(t, ())] or [w for ws in TOPIC_WORDS.values() for w in ws]
    scored = sorted(((sum(t.lower().count(w) for w in words), i) for i, (_p, t) in enumerate(whole)), reverse=True)
    chosen, used = [], 0
    for score, i in scored:
        if score == 0 or used >= budget:
            break
        text = whole[i][1][: budget - used]
        chosen.append((i, text))
        used += len(text)
    if not any(i == 0 for i, _t in chosen) and used < budget:
        chosen.append((0, whole[0][1][: max(0, budget - used)]))
    return "\n\n".join(t for _i, t in sorted(chosen)) or "(no page names the topics; use the tools)"


def _doc_tools(docs: dict[str, tuple[FileView, SourceDocument]]) -> list[Tool]:
    """Tools over the files (path -> (file, document))."""

    def get(path: str) -> SourceDocument:
        if path not in docs:
            raise KeyError(f"no file {path!r}; the files are: {', '.join(list(docs)[:60])}")
        return docs[path][1]

    def outline(file: str) -> str:
        return _outline(get(file))

    def read_lines(file: str, part: str, first: int = 1, last: int = 60) -> str:
        found = {p.name: p for p in _parts(get(file))}
        if part not in found:
            raise KeyError(f"{file} has no part {part!r}; it has {', '.join(list(found)[:40])}")
        return _numbered(found[part], int(first), int(last))

    def search(text: str, file: str = "") -> str:
        want = unmarked(text)
        hits = []
        for path, (_f, doc) in docs.items():
            if file and path != file:
                continue
            for part in _parts(doc):
                for ln in part.lines:
                    if want and want in unmarked(ln.text):
                        hits.append(f"{path} · {part.name} L{ln.number}: {ln.text[:200]}")
                        if len(hits) >= 40:
                            return "\n".join(hits) + "\n(first 40 shown)"
        return "\n".join(hits) or "(not found)"

    string = {"type": "string"}
    return [
        Tool("outline", "The parts of a file, each with its number of lines and its first lines.",
             {"type": "object", "properties": {"file": string}, "required": ["file"]}, outline),
        Tool("read_lines", f"Numbered lines of one part of a file (at most {MAX_LINES} per call).",
             {"type": "object", "properties": {"file": string, "part": string, "first": {"type": "integer"},
                                               "last": {"type": "integer"}}, "required": ["file", "part"]}, read_lines),
        Tool("search", "Lines containing a text (case and spacing ignored), in one file or in all.",
             {"type": "object", "properties": {"text": string, "file": string}, "required": ["text"]}, search),
    ]


def _submit_tool(name: str, schema: type[BaseModel], check: Callable[[BaseModel], list[str]], saved: list[BaseModel],
                 description: str) -> Tool:
    def handler(**arguments: Any) -> str:
        try:
            answer = schema.model_validate(arguments)
        except ValidationError as exc:
            return f"not saved: the answer does not fit the form: {exc.errors()[:8]}"
        problems = check(answer)
        saved[:] = [answer]
        if problems:
            return ("saved, with problems; fix them and submit again (or leave out what cannot be fixed):\n- "
                    + "\n- ".join(problems[:30]))
        return "saved"

    return Tool(name, description, schema.model_json_schema(), handler)


# --- the answer cache (plan 2026-11-24 §5 item 2) ------------------------------------------------------------------------

def _answering(model: ChatModel, avoid: str = "") -> Any:
    """The model a new conversation of `model` starts on (a chain: its first model that is not resting and not `avoid`),
    found without starting one: its identity and effort are in the answer cache's key."""
    if hasattr(model, "start") and hasattr(model, "models"):
        return model.models[model.start(avoid)]
    return model


def _answer_key(store: DataRoomStore, stage: str, model: ChatModel, path: str, f: FileView, doc: SourceDocument, *,
                system: str, tools: list[Tool], user: str, shared: str = "", inputs: dict[str, str],
                avoid: str = "") -> AnswerKey:
    """Every input that can change this stage's answer for this file (`answer_cache` lists them)."""
    m = _answering(model, avoid)
    effort = getattr(m, "effort", None) or getattr(m, "reasoning_effort", None) or ""
    return AnswerKey(tenant=store.ws.tenant_id, stage=stage, prompt_version=PROMPT_VERSION, file_sha256=f.sha256,  # type: ignore[arg-type]
                     path=path, reader=f"{doc.parser}/{doc.parser_version}; lines {LINES_VERSION}",
                     text_sha256=parts_sha256(_parts(doc)), model=f"{m.provider}/{m.model}",
                     endpoint=str(getattr(m, "base_url", "") or ""), effort=str(effort), inputs=inputs,
                     request_sha256=stable_sha256({"system": system, "tools": [t.schema() for t in tools],
                                                   "task": shared + user}))


def _accepted(schema: type[BaseModel], answer: dict[str, Any], check: Callable[[BaseModel], list[str]]) -> bool:
    """A cached answer still fits its form and passes code's checks against this project's file."""
    try:
        return not check(schema.model_validate(answer))
    except Exception:  # noqa: BLE001 - an answer code can no longer read is not reused; the model is asked instead
        return False


def _cached(cache: AnswerCache, key: AnswerKey, accept: Callable[[dict[str, Any]], bool]) -> CachedAnswer | None:
    hit = cache.get(key)
    return hit if hit is not None and accept(hit.answer) else None


def _record_reuse(store: DataRoomStore, stage: str, path: str, hit: CachedAnswer, key: AnswerKey, note: str = "") -> None:
    """A cached answer used: the run's record says so, and the author is the model that wrote it."""
    store.log_agent_step(stage=stage, file=path, model=hit.author, step={
        "type": "answer_reused", "from_project": hit.project, "from_run": hit.run, "key": key.digest()})
    store.record_author(stage=stage, file=path, model=hit.author, identity=hit.identity, prompt=key.prompt_version,
                        note=hit.note + note)


def _remember(store: DataRoomStore, cache: AnswerCache, key: AnswerKey, answer: BaseModel, outcome: LoopOutcome) -> None:
    """An answer code accepted, kept for the next run with the same inputs; not when another model than the key's
    finished it (a chain that switched): the key would then name a model that did not write it."""
    if outcome.answered_on == key.model:
        cache.put(key, answer.model_dump(mode="json"), author=outcome.answered_by, identity=outcome.answered_on,
                  run=str(store.run().get("started_at") or ""))


def _reuse_note(reused: int) -> str:
    return (f"; {reused} answered from an earlier run (same file, same question, same model: no model call)"
            if reused else "")


def _used_files(store: DataRoomStore) -> dict[str, tuple[FileView, SourceDocument]]:
    out = {}
    for f in store.files():
        if f.duplicate_of or f.same_content_as or f.state not in ("read", "partly_read"):
            continue
        doc = store.doc(f.sha256)
        if doc is not None:
            out[f.path] = (f, doc)
    return out


# --- A6: the question ---------------------------------------------------------------------------------------------------

QUESTION_SYSTEM = _COMMON + """

Your job (A6): from the proposal, the client's request (an email, a screenshot), the protocols and reports, say what
the modelling must answer, for which regulator, with which approach, the products compared (reference, test, original,
reformulated, as the files name them), the context of use, and the checklist of inputs the question needs. Tailor this
standard checklist to the question (drop what it does not need, add what it does):
A formulation and manufacturing: composition of every product (qualitative and quantitative), manufacturing process
  and its changes, the changed excipient and its share.
B in vitro: dissolution of every product and batch in every medium tested (QC and biorelevant pH 1.2, 4.5, 6.8), with
  apparatus, speed, volume and units; particle size; the drug product specification.
C drug substance and disposition: MW (salt and free base), pKa, logP/logD, solubility vs pH, permeability, fraction
  unbound, blood-to-plasma ratio, metabolism (enzymes, fm), elimination, IV or absolute bioavailability data.
D clinical: per study the design, dose, products and batches per treatment, fasting and meals, water, sampling times,
  LLOQ, demographics, disposition (who completed, who was excluded and why), individual concentrations, the client's
  NCA and BE results.
Each checklist item gets topics from: """ + ", ".join(TOPICS) + """.
Each product is {"name": as the files name it, "role": reference | test | original | reformulated | other}.
Work from the digest: it names every file, its parts and the lines code found that may state the question, the
products and the design, each exactly as written (quote from them). Open a file only for a quote you still need, by a
part the digest names. A quote is a sentence a document states, never a line of a data table. Keep the checklist
short: one item per input the question needs (25 at most), its why in 12 words at most. Submit once the card is whole."""


_ASKS = re.compile(r"(?i)\b(?:objective|aim|purpose|question|scope|request|propos|deliverable|waiver|biowaiver|"
                   r"bioequivalen|food[- ]effect|virtual|PBPK|PBBM|safe space|specification|FDA|EMA|PMDA|MHRA|agency|"
                   r"regulator|submission|ANDA|NDA|MAA|variation|bridg|comparab)")
_PRODUCTS = re.compile(r"(?i)\b\d+(?:[.,]\d+)?\s*(?:mg|µg|mcg)\b.{0,60}\b(?:tablet|capsule|suspension|solution|granule|"
                       r"formulation|film-coated)|\b(?:reference|test product|comparator|RLD|new formulation|current "
                       r"formulation|batch|lot)\b")
DIGEST_CHARS = 7000      # the digest A6 reads first: every file, its parts, the lines that may state the question


def question_digest(docs: dict[str, tuple[FileView, SourceDocument]], order: Sequence[str] = (),
                    budget: int = DIGEST_CHARS, per_file: int = 8) -> str:
    """What code reads from every file before A6 starts, so A6 writes the question card from one page and does not
    open the files one by one (2026-11-24: A6 took 2 to 9 minutes, every run spending its 14 turns reading files one
    call at a time, guessing part names: "sheet:Sheet1", "body" for a text export). Per file: its kind, its parts with
    their lines, its first line, and the lines that may state the question, a product or the design, as written."""
    out, used = [], 0
    for path in list(order) + [p for p in docs if p not in order]:
        f, doc = docs[path]
        parts = _parts(doc)
        names = ", ".join(f"{p.name} ({len(p.lines)} lines)" for p in parts[:8]) + (
            f", and {len(parts) - 8} more" if len(parts) > 8 else "")
        lines = [f"=== {path} ({f.kind}) · parts: {names or 'none read'}"]
        seen: set[str] = set()
        for part in parts:
            for ln in part.lines:
                text = ln.text.strip()
                if not text or text in seen or text.count("|") >= 4:      # a table's row is read from its description
                    continue
                first = part is parts[0] and ln.number == next((x.number for x in part.lines if x.text.strip()), 0)
                if first or _ASKS.search(text) or _PRODUCTS.search(text) or _DESIGN.search(text):
                    seen.add(text)
                    lines.append(f"{part.name} L{ln.number}: {text[:240]}")
                if len(lines) > per_file:
                    break
            if len(lines) > per_file:
                break
        block = "\n".join(lines)
        if used + len(block) > budget:
            out.append(f"=== {path} ({f.kind}) · parts: {names or 'none read'}")
            used += len(out[-1])
            continue
        out.append(block)
        used += len(block)
    return "\n".join(out)


def question(store: DataRoomStore, model: ChatModel, *, actor: str, redo: bool, step: Step, only: set[str] | None = None,
             focus_chars: int = FOCUS_CHARS) -> str:
    card, confirmed = store.question()
    if card is not None and (confirmed or not redo):
        return "the question card is already there" + (" and confirmed" if confirmed else "")
    docs = _used_files(store)
    listing = "\n".join(f"- {p} ({f.kind}, {f.pages or ''} pages)" for p, (f, _d) in docs.items())
    # the files most likely to state the question first: the proposal, the request, files the triage tagged so
    def weight(path: str, f: FileView) -> int:
        t = store.triage(f.sha256)
        name = path.lower()
        return (3 * any(w in name for w in ("proposal", "request", "scope", "email", "pasted", "letter"))
                + 2 * bool(t and set(t.topics) & {"question", "regulatory"}) + (f.kind in ("docx", "image")))
    order = [p for p, _v in sorted(docs.items(), key=lambda kv: -weight(kv[0], kv[1][0]))]
    ranked = [(p, docs[p]) for p in order[:3]]
    per_file = max(800, focus_chars // 4)
    digest = question_digest(docs, order)
    material = "\n\n".join(f"=== {p}\n{_focus(d, ['question'], budget=per_file)}" for p, (_f, d) in ranked)
    saved: list[BaseModel] = []

    def check(answer: BaseModel) -> list[str]:
        problems = []
        for fact in answer.quotes:  # type: ignore[attr-defined]
            if fact.file not in docs:
                problems.append(f"quote for {fact.field}: no file {fact.file!r}")
                continue
            got = check_fact(fact, docs[fact.file][1], file=fact.file, sha256=docs[fact.file][0].sha256)
            if not got.ok:
                problems.append(f"quote for {fact.field}: {got.problem}")
        return problems

    submit = _submit_tool("submit_question", QuestionCard, check, saved,
                          "Submit the question card (with the quotes it rests on).")
    tools = _doc_tools(docs) + [submit]
    step(0, 1, "reading the proposal and the request")
    # first from the digest and the pages alone, with no file to open: a model given the tools opened the files one per
    # turn even with the digest in hand (2026-11-24); the tools come back only when no card could be saved
    outcome = _loop(store, "question", "", model, saved, system=QUESTION_SYSTEM, tools=[submit], max_turns=3, user=(
        f"The delivery, as code read it (every file, its parts, the lines that may state the question):\n{digest}\n\n"
        f"The pages most likely to state the question:\n{material}\n\n"
        "Write the question card from these now (each quote with its file), and submit it."))
    if not saved and not _too_large(outcome.error):
        outcome = _loop(store, "question", "", model, saved, system=QUESTION_SYSTEM, tools=tools, max_turns=8, user=(
            f"The delivery, as code read it (every file, its parts, the lines that may state the question):\n{digest}\n\n"
            f"The pages most likely to state the question:\n{material}\n\n"
            "Write the question card (each quote with its file); open a file only for a quote you still need."))
    if not saved and _too_large(outcome.error):
        material = "\n\n".join(f"=== {p}\n{_focus(d, ['question'], budget=per_file // 3)}" for p, (_f, d) in ranked[:2])
        outcome = _loop(store, "question", "", model, saved, system=QUESTION_SYSTEM, tools=tools, max_turns=8, user=(
            f"The delivery's files:\n{listing}\n\nThe pages most likely to state the question:\n{material}\n\n"
            "Write the question card (each quote with its file)."))
    if not saved:
        return f"no question card ({outcome.status}{': ' + outcome.error if outcome.error else ''})"
    # the model whose submission was saved: in a chain, the one the conversation ended on
    store.set_question(saved[0], by=f"agent:A6:{outcome.answered_by}", confirmed=False)  # type: ignore[arg-type]
    store.record_author(stage="question", file="", model=outcome.answered_by, identity=outcome.answered_on,
                        prompt=PROMPT_VERSION)
    step(1, 1, "question card drafted: confirm it")
    return "question card drafted: confirm it"


# --- A7: triage -----------------------------------------------------------------------------------------------------------

TRIAGE_SYSTEM = _COMMON + """

Your job (A7): say what one file is for. purpose: "used" (it holds inputs or data the modelling needs), "context"
(background worth keeping: literature, a method, a certificate that matters), "not_needed" (administrative papers,
declarations, a duplicate printout), with one plain sentence why. topics from: """ + ", ".join(TOPICS) + """. Name the
study (its number) and the products the file is about, as written."""


_DESIGN = re.compile(r"(?i)\b(?:cross-?over|parallel[- ]group|randomi[sz]ed|open[- ]label|single[- ]dose|multiple[- ]dose|"
                     r"once daily|food[- ]effect|bioequivalence|relative bioavailability|steady[- ]state)\b")
_SUBJECTS = re.compile(r"(?i)\b\d+\s+(?:healthy\s+)?(?:subjects|volunteers|patients|participants)\b|\bsubjects? (?:were|was) "
                       r"(?:excluded|withdrawn|randomi[sz]ed|enrolled|dosed)")
_DOSE = re.compile(r"(?i)\b\d+(?:[.,]\d+)?\s*mg\b")


def _holds_inputs(doc: SourceDocument) -> str:
    """Why a file must be extracted whatever the agent sorted it as: it states a study's design, its subjects and a dose,
    as a protocol or a synopsis does (a new delivery, 2026-11-24: the synopsis was sorted as context, never extracted,
    and the treatment codes, the dose, the design and an excluded subject were lost). "" when it does not."""
    text = "\n".join(line.text for part in document_parts(doc) for line in part.lines)
    design, subjects, dose = _DESIGN.search(text), _SUBJECTS.search(text), _DOSE.search(text)
    if design and subjects and dose:
        return f"it states the design ({design.group(0)!r}), the subjects ({subjects.group(0)!r}) and a dose ({dose.group(0)!r})"
    return ""


def triage(store: DataRoomStore, model: ChatModel, *, actor: str, redo: bool, step: Step, only: set[str] | None = None,
          focus_chars: int = FOCUS_CHARS, reuse: bool | None = None) -> str:
    """A7 on each used file not sorted yet (all of them on `redo`). `reuse`: answer from the tenant's answer cache when
    every input is the same (default: unless redoing)."""
    docs = {p: v for p, v in _used_files(store).items() if only is None or p in only}
    todo = [(p, f, d) for p, (f, d) in docs.items() if redo or store.triage(f.sha256) is None]
    card, _confirmed = store.question()
    context = f"The question: {card.question}\n" if card else ""      # the delivery's block: the same for every file
    cache, reused = AnswerCache(store.ws), 0
    reuse = not redo if reuse is None else reuse
    step(0, len(todo))
    for done, (path, f, doc) in enumerate(todo, start=1):
        saved: list[BaseModel] = []
        def checked(a: BaseModel, path: str = path, doc: SourceDocument = doc) -> list[str]:
            if a.path != path:  # type: ignore[attr-defined]
                return [f"path must be {path!r}"]
            why = _holds_inputs(doc) if a.purpose != "used" else ""  # type: ignore[attr-defined]
            return [f"this file holds inputs ({why}): sort it as used, so it is extracted"] if why else []

        tool = _submit_tool("submit_triage", FileTriage, checked, saved, "Submit the file's triage.")
        text = "\n\n".join(_numbered(part, 1, PREVIEW_LINES) for part in _parts(doc)[:2])
        task = f"File: {path} ({f.kind}, {f.pages} pages; parts: {len(_parts(doc))})\n\nIts first lines:\n{text}"
        key = _answer_key(store, "triage", model, path, f, doc, system=TRIAGE_SYSTEM, tools=[tool], shared=context,
                          user=task, inputs={"question": stable_sha256(card.question if card else "")})
        hit = _cached(cache, key, lambda a, checked=checked: _accepted(FileTriage, a, checked)) if reuse else None
        if hit is not None:
            store.put_triage(FileTriage.model_validate(hit.answer), f.sha256)
            _record_reuse(store, "triage", path, hit, key)
            reused += 1
            step(done, len(todo), path)
            continue
        sorted_by = _loop(store, "triage", path, model, saved, system=TRIAGE_SYSTEM, tools=[tool], max_turns=4,
                          shared=context, user=task)
        if saved:
            store.put_triage(saved[0], f.sha256)  # type: ignore[arg-type]
            store.record_author(stage="triage", file=path, model=sorted_by.answered_by, identity=sorted_by.answered_on,
                                prompt=PROMPT_VERSION)
            if not checked(saved[0]):
                _remember(store, cache, key, saved[0], sorted_by)
        step(done, len(todo), path)
    return f"{len(todo)} files sorted" + _reuse_note(reused)


# --- A8: extraction -----------------------------------------------------------------------------------------------------

_TOPIC_FIELDS = {"clinical_design": ("study.",), "clinical_disposition": ("study.",), "clinical_demographics": ("study.",),
                 "dosing_and_meals": ("study.",), "bioanalysis": ("study.",), "clinical_concentrations": ("study.",),
                 "clinical_pk": ("study.",), "be_statistics": ("study.",), "dissolution": ("dissolution.", "product.", "batch."),
                 "composition": ("product.", "batch."), "manufacturing": ("product.", "batch."), "solubility": ("substance.",),
                 "particle_size": ("substance.", "batch."), "drug_substance": ("substance.",), "adme": ("adme.",),
                 "label": ("adme.", "substance.", "product."), "question": ("question.",)}
_TOPIC_KINDS = {"clinical_concentrations": ("concentrations",), "clinical_pk": ("pk_parameters",),
                "clinical_demographics": ("demographics",), "clinical_disposition": ("disposition",),
                "dissolution": ("dissolution",), "composition": ("composition",), "solubility": ("solubility",),
                "particle_size": ("particle_size",), "be_statistics": ("be_statistics",), "drug_substance": ("physchem",)}


# The extractor's instructions: word for word the same for every file (dataroom-5), so a delivery's files share one
# cached start. What differs per file, the fields and table kinds its topics need, is in the file's block
# (`extract_vocabulary`).
EXTRACT_SYSTEM = _COMMON + """

Your job (A8): for one file, find every input the checklist asks for and answer with:
1. table descriptions: kind, part, header lines, first and last data line, summary lines (the client's mean or RSD
   rows), and for each cell position its role. A column whose header is a time gets "time" (as the header writes it);
   side-by-side blocks (a batch, a product) get "group" as written. One description per page a table covers. The
   table kinds and the roles of their columns are listed with the file ("Table kinds").
   Concentrations: each value cell gets role "value" and its time; give the time unit and the concentration unit as
   written; zero_means_blq when the file writes values below the LLOQ as 0. A marker is either below the LLOQ (BLQ,
   <LLOQ) or a missing sample (".", NS), never both. A table's shared values (medium, pH, volume, rpm, apparatus,
   study) go in constants only as a file writes them, and each is also a fact.
2. facts, each with its verbatim quote, in the fields listed with the file ("Fact fields"; a new dotted name only when
   none fits).
   subject: what the fact is about (a study number, a treatment code, a batch). product: the question card's product
   name when the fact concerns one. One fact per treatment code (subject = the code; value = what the documents say
   it is, e.g. "Refamide 100 mg (reference product)"). Each batch or lot a file links to a product is a fact
   product.batch (value = the batch, product = the product). Subject lists (completed, excluded) hold the numbers
   only; the reason goes in note.
3. not_found: the checklist ids you looked for here and did not find."""


def extract_vocabulary(topics: Sequence[str]) -> str:
    """The table kinds with their column roles and the fact fields one file's topics need (all of them when the triage
    gave no topic), given in the file's block: a small model's context holds the file rather than the whole vocabulary,
    and the instructions stay the same for every file."""
    prefixes = {p for t in topics for p in _TOPIC_FIELDS.get(t, ())} or {f.split(".")[0] + "." for f in FIELDS}
    kinds = {k for t in topics for k in _TOPIC_KINDS.get(t, ())} or set(ROLES)
    fields = "\n".join(f"   {k}: {v}" for k, v in FIELDS.items() if k.startswith(tuple(prefixes)))
    roles = "\n".join(f"   {k}: {', '.join(v)}" for k, v in ROLES.items() if k in kinds)
    return f"Table kinds (kind: the roles of its columns) for this file:\n{roles}\nFact fields for this file:\n{fields}"


def _extraction_problems(answer: Extraction, path: str, f: FileView, doc: SourceDocument) -> list[str]:
    problems = []
    for i, table in enumerate(answer.tables, start=1):
        got = read_table(table.model_copy(update={"file": path}), doc, file=path, sha256=f.sha256)
        problems += [f"table {i} ({table.kind}, {table.part}): {p.message}" for p in got.problems if p.severity == "error"]
        if not got.rows and not got.problems:
            problems.append(f"table {i} ({table.kind}, {table.part}): no data lines in {table.first_line}–{table.last_line}")
        if table.kind == "concentrations" and got.rows and (why := colliding_samples(got)):
            problems.append(f"table {i} ({table.kind}, {table.part}): {why}")
        unknown = {c.role for c in table.columns} - set(ROLES.get(table.kind, ())) - {"unit", "value", "time"}
        if unknown and table.kind in ROLES:
            problems.append(f"table {i}: roles not known for {table.kind}: {', '.join(sorted(unknown))}")
    for fact in answer.facts:
        got = check_fact(fact.model_copy(update={"file": path}), doc, file=path, sha256=f.sha256)
        if not got.ok:
            problems.append(f"fact {fact.field} = {fact.value!r}: {got.problem}")
    return problems


def extract(store: DataRoomStore, model: ChatModel, *, actor: str, redo: bool, step: Step, only: set[str] | None = None,
            focus_chars: int = FOCUS_CHARS, feedback: dict[str, list[dict[str, Any]]] | None = None,
            reuse: bool | None = None) -> str:
    """A8 on each used file. `feedback`: the checker's issues per file, for a second pass on the files it flagged (a new
    delivery, 2026-11-24: A9 saw a Day column described as a group, but its finding never reached A8). `reuse`: answer
    from the tenant's answer cache when every input is the same (default: unless redoing)."""
    docs = {p: v for p, v in _used_files(store).items() if only is None or p in only}
    card, _confirmed = store.question()
    checklist = "\n".join(f"- {c.id} [{c.area}] {c.label} (topics: {', '.join(c.topics)})" for c in (card.checklist if card else ()))
    products = "\n".join(f"- {p.name} ({p.role})" for p in (card.products if card else ()))
    # the delivery's block, the same for every file and before the file's own (one cached start for all of them)
    delivery = (f"The question: {card.question if card else '(not set)'}\nThe products:\n{products or '(not set)'}\n"
                f"The checklist:\n{checklist or '(not set)'}\n\n")
    asked = stable_sha256(None if card is None else {          # the card's fields the prompt shows, nothing else
        "question": card.question, "products": [[p.name, p.role] for p in card.products],
        "checklist": [[c.id, c.area, c.label, list(c.topics)] for c in card.checklist]})
    cache, reused = AnswerCache(store.ws), 0
    reuse = not redo if reuse is None else reuse
    todo = []
    for path, (f, doc) in docs.items():
        t = store.triage(f.sha256)
        if t is not None and t.purpose != "used":
            continue
        if redo or store.extraction(f.sha256) is None:
            todo.append((path, f, doc, t))
    failed: list[str] = []
    step(0, len(todo))
    for done, (path, f, doc, t) in enumerate(todo, start=1):
        saved: list[BaseModel] = []
        tool = _submit_tool("submit_extraction", Extraction,
                            lambda a, path=path, f=f, doc=doc: _extraction_problems(a, path, f, doc), saved,
                            "Submit this file's tables and facts.")
        # the file goes to the tools as an argument (`file`) or by the tool's own handler: every name, description and
        # schema is the same for every file
        tools = [x for x in _doc_tools({path: (f, doc)}) if x.name != "search"] + [_search_one(path, doc), tool]
        topics = list(t.topics) if t else []
        said = _feedback_text((feedback or {}).get(path, []))

        def user(budget: int, path: str = path, f: FileView = f, doc: SourceDocument = doc, t: FileTriage | None = t,
                 topics: list[str] = topics, said: str = said) -> str:
            """The file's own block, after the delivery's."""
            return (f"File: {path} ({f.kind}; "
                    f"{'OCR on pages ' + ', '.join(map(str, f.ocr_pages)) if f.ocr_pages else 'text layer'})"
                    f"{'; the triage says: ' + t.reason if t else ''}\n\n{extract_vocabulary(topics)}\n\nIts parts: "
                    f"{', '.join(f'{p.name} ({len(p.lines)} lines)' for p in _parts(doc)[:120])}\n\n"
                    f"The pages most likely to hold what the checklist needs (open others with the tools):\n"
                    f"{_focus(doc, topics, budget=budget)}" + said)
        budget = max(2000, focus_chars)
        task = user(budget)
        key = _answer_key(store, "extract", model, path, f, doc, system=EXTRACT_SYSTEM, tools=tools, shared=delivery,
                          user=task, inputs={
                              "question": asked, "focus_chars": str(budget), "feedback": stable_sha256(said) if said else "",
                              "triage": stable_sha256(None if t is None else {"topics": topics, "reason": t.reason})})
        # an extraction made again on the checker's issues says how many it answered: it is not sent back again
        sent_back = {"checker_issues": str(len(feedback[path]))} if feedback and path in feedback else {}

        def problems(a: BaseModel, path: str = path, f: FileView = f, doc: SourceDocument = doc) -> list[str]:
            return _extraction_problems(a, path, f, doc)  # type: ignore[arg-type]

        hit = _cached(cache, key, lambda a, problems=problems: _accepted(Extraction, a, problems)) if reuse else None
        if hit is not None:
            _record_reuse(store, "extract", path, hit, key)
            store.put_extraction(Extraction.model_validate(hit.answer), f.sha256, agent={
                "agent": "A8", "model": hit.author, "identity": hit.identity, "prompt": PROMPT_VERSION, "reused": hit.note,
                **sent_back})
            reused += 1
            step(done, len(todo), path)
            continue
        outcome = _loop(store, "extract", path, model, saved, system=EXTRACT_SYSTEM, shared=delivery, user=task,
                        tools=tools, max_turns=14)
        if not saved and _too_large(outcome.error):      # a provider's per-request limit: the same, with fewer pages
            outcome = _loop(store, "extract", path, model, saved, system=EXTRACT_SYSTEM, shared=delivery,
                            user=user(budget // 3),
                            tools=tools, max_turns=10)
        if not saved:
            failed.append(f"{path}: no answer ({outcome.status}{': ' + outcome.error[:200] if outcome.error else ''})")
        if saved:
            answer = saved[0].model_copy(update={"file": path})
            store.record_author(stage="extract", file=path, model=outcome.answered_by, identity=outcome.answered_on,
                                prompt=PROMPT_VERSION)
            store.put_extraction(answer, f.sha256, agent={"agent": "A8", "model": outcome.answered_by,
                                                          "identity": outcome.answered_on,  # type: ignore[arg-type]
                                                          "prompt": PROMPT_VERSION, **sent_back})
            if not problems(answer):
                _remember(store, cache, key, answer, outcome)
        step(done, len(todo), path)
    store.set_stage_notes("extract", failed)
    return (f"{len(todo) - len(failed)} of {len(todo)} files extracted" + (f"; {len(failed)} gave no answer" if failed else "")
            + _reuse_note(reused))


def _feedback_text(issues: list[dict[str, Any]]) -> str:
    """The checker's issues on an earlier description of this file, for the extractor's second pass."""
    if not issues:
        return ""
    lines = "\n".join(f"- table {i.get('table', '?')}: {i.get('issue', '')}" for i in issues[:12])
    return ("\n\nA checker read your earlier description of this file against its pages and found:\n" + lines +
            "\nDescribe the file again. Where an issue is right, correct the description; where it is wrong, keep what "
            "the pages show.")


def _search_one(path: str, doc: SourceDocument) -> Tool:
    def search(text: str) -> str:
        want = unmarked(text)
        hits = [f"{part.name} L{ln.number}: {ln.text[:200]}" for part in _parts(doc) for ln in part.lines
                if want and want in unmarked(ln.text)]
        return "\n".join(hits[:40]) + ("\n(first 40 shown)" if len(hits) > 40 else "") if hits else "(not found)"

    return Tool("search", "Lines of this file containing a text (case and spacing ignored).",
                {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}, search)


# --- A9: the checker ---------------------------------------------------------------------------------------------------

CHECK_SYSTEM = _COMMON + """

Your job (A9): a second reader. You get one file's table descriptions, each with the header lines and the first data
lines as code read them. Each data line is shown as its cells separated by " ; ", each cell as role@time[group]=text:
the role the description gave the column, the time written above it (if any), its side-by-side group (if any), then
the cell's text as the file writes it. That is code's display, not the file's layout: never report the separators or
the role names as a fault of the file. Say for each table whether the roles fit the headers (a time under the right
column, the treatment code not taken for the period, a study day or visit not left as a mere group, a batch block not
shifted by one cell, below-LLOQ markers not counted as missing samples). Answer with the submit tool: one item per
table, ok true or false, and the issue in one sentence a correction can act on."""


class _Review(BaseModel):
    tables: list[dict[str, Any]]


def check(store: DataRoomStore, model: ChatModel, *, actor: str, redo: bool, step: Step, only: set[str] | None = None,
          focus_chars: int = FOCUS_CHARS, reuse: bool | None = None, recheck: bool = False) -> str:
    """A9 on each file whose extraction has tables. A file whose review checked its extraction as it now stands is not
    checked again (a second run, a paused run resumed), unless `redo`. `reuse`: answer from the tenant's answer cache
    when every input is the same (default: unless redoing). `recheck`: the look after the extractor's second pass
    (`run._check_again`), a step of its own in the cache: the same extraction checked again is asked again, not answered
    with the first look."""
    docs = {p: v for p, v in _used_files(store).items() if only is None or p in only}
    todo = [(p, f, d, got[0]) for p, (f, d) in docs.items() if (got := store.extraction(f.sha256)) and got[0].tables
            and (redo or not store.review_current(f.sha256))]
    issues = 0
    cache, reused = AnswerCache(store.ws), 0
    reuse = not redo if reuse is None else reuse
    step(0, len(todo))
    for done, (path, f, doc, ext) in enumerate(todo, start=1):
        parts = {p.name: p for p in _parts(doc)}
        shown = []
        for i, table in enumerate(ext.tables, start=1):
            read = read_table(table, doc, file=path, sha256=f.sha256)
            head = "\n".join(_numbered(parts[table.part], k, k) for k in table.header_lines if table.part in parts)
            rows = "\n".join(" ; ".join(f"{c.role}{'@' + format(c.time, 'g') if c.time is not None else ''}"
                                        f"{'[' + c.group + ']' if c.group else ''}={c.text}" for c in r.cells)
                             for r in read.rows[:3])
            shown.append(f"Table {i} ({table.kind}, {table.part}, lines {table.first_line}–{table.last_line}):\n{head}\n{rows}")
        saved: list[BaseModel] = []
        tool = _submit_tool("submit_review", _Review, lambda a: [], saved, "Submit the review: {tables: [{table, ok, issue}]}.")
        # a second opinion: the checker starts on another model than the one that wrote the extraction (plan §9; the
        # governance review, 2026-11-22), when the chain has one
        author = ((store.extraction(f.sha256) or (None, {}))[1] or {}).get("identity", "")
        task = f"File: {path}\n\n" + "\n\n".join(shown)
        key = _answer_key(store, "check", model, path, f, doc, system=CHECK_SYSTEM, tools=[tool], user=task, avoid=author,
                          inputs={"extraction": stable_sha256([x.model_dump(mode="json") for x in ext.tables]),
                                  "look": "again, after the extractor's second pass" if recheck else "first"})
        hit = _cached(cache, key, lambda a: _accepted(_Review, a, lambda r: [])) if reuse else None
        if hit is not None:
            same = bool(author) and hit.identity == author
            _record_reuse(store, "check", path, hit, key,
                          note="; not a second opinion: the same model wrote the extraction" if same else "")
            review = [x for x in _Review.model_validate(hit.answer).tables if not x.get("ok", True)]
            issues += len(review)
            store.put_review(f.sha256, review, agent=hit.author, extraction=store.extraction_stamp(f.sha256))
            reused += 1
            step(done, len(todo), path)
            continue
        checker = model.conversation(avoid=author) if hasattr(model, "conversation") else model
        done_check = _loop(store, "check", path, checker, saved, system=CHECK_SYSTEM, tools=[tool], max_turns=4, user=task)
        same = bool(author) and done_check.answered_on == author
        store.record_author(stage="check", file=path, model=done_check.answered_by, identity=done_check.answered_on,
                            prompt=PROMPT_VERSION,
                            note="not a second opinion: the same model wrote the extraction" if same else "")
        if saved:
            review = [t for t in saved[0].tables if not t.get("ok", True)]  # type: ignore[attr-defined]
            issues += len(review)
            store.put_review(f.sha256, review, agent=done_check.answered_by, extraction=store.extraction_stamp(f.sha256))
            _remember(store, cache, key, saved[0], done_check)
        step(done, len(todo), path)
    return f"{len(todo)} files checked, {issues} issues" + _reuse_note(reused)


# --- A10: the writer ------------------------------------------------------------------------------------------------------

WRITE_SYSTEM = _COMMON + """

Your job (A10): write, in plain English for a modeler and a regulator, one finding line per section of the Data room
(at most 25 words, the most important thing first) and the wording of each data request as a short polite request to
the client. Use only numbers that appear in the material you are given; write no number of your own."""


class _Writing(BaseModel):
    findings: dict[str, str]
    requests: dict[str, str]


def _numbers_ok(text: str, allowed: str) -> bool:
    return all(n in allowed for n in re.findall(r"\d+(?:\.\d+)?", text))


def write(store: DataRoomStore, model: ChatModel, *, actor: str, redo: bool, step: Step, only: set[str] | None = None,
          focus_chars: int = FOCUS_CHARS) -> str:
    view = room_view(store)
    material = json.dumps({
        "sections": [{"id": s.id, "title": s.title, "finding": s.computed, "status": s.status} for s in view.sections],
        "studies": [{"study": s.study_id, "sets": {x.label: len(x.subjects) for x in s.sets}, "excluded": s.excluded,
                     "exposures": [e.model_dump() for e in s.exposures]} for s in view.studies],
        "dissolution": [{"product": d.product, "batch": d.batch, "medium": d.medium, "very_rapid": d.very_rapid,
                         "plateau": d.plateau} for d in view.dissolution],
        "requests": [{"title": r.title, "why": r.why} for r in view.requests],
        "decisions": [{"title": d.title, "suggested": d.suggested} for d in view.decisions]}, ensure_ascii=False)
    saved: list[BaseModel] = []

    def checked(a: BaseModel) -> list[str]:
        bad = [k for k, v in {**a.findings, **a.requests}.items() if not _numbers_ok(v, material)]  # type: ignore[attr-defined]
        return [f"{k}: a number that is not in the material" for k in bad]

    tool = _submit_tool("submit_writing", _Writing, checked, saved,
                        "Submit {findings: {section id: line}, requests: {request title: wording}}.")
    step(0, 1, "writing")
    written = _loop(store, "write", "", model, saved, system=WRITE_SYSTEM, tools=[tool], max_turns=6, user=material)
    if not saved:
        return "nothing written"
    a = saved[0]
    store.put_writing({k: v for k, v in a.findings.items() if _numbers_ok(v, material)},  # type: ignore[attr-defined]
                      {k: v for k, v in a.requests.items() if _numbers_ok(v, material)},  # type: ignore[attr-defined]
                      agent=written.answered_by, basis={s.id: s.computed for s in view.sections})
    store.record_author(stage="write", file="", model=written.answered_by, identity=written.answered_on,
                        prompt=PROMPT_VERSION)
    step(1, 1, "written")
    return "findings and request wording written"


__all__: Sequence[str] = ("check", "extract", "question", "triage", "write")
