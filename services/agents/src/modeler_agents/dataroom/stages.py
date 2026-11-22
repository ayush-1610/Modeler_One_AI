"""The Data room's five agents (plan 2026-11-21 v2 §9). Each reads a file through tools over its numbered lines and
answers only through a submit tool whose handler runs code's checks: a refused quote, a table line that cannot be
placed, an unknown field is sent straight back to the model, which corrects and submits again. The model never types
a value into the room: it says where a value is and what it means; code reads it.

Each stage is `stage(store, model, *, actor, redo, step) -> note`, called by `run.run_room`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from typing import Any

from pydantic import BaseModel, ValidationError

from modeler_agents.llm import ChatModel, Tool, run_tool_loop
from modeler_intake.room import Part, document_parts, unmarked
from modeler_intake.room_specs import FIELDS, ROLES, TOPICS, Extraction, FileTriage, QuestionCard
from modeler_intake.source_model import SourceDocument
from modeler_project.dataroom import room_view
from modeler_project.dataroom.extract import check_fact, read_table
from modeler_project.dataroom.model import FileView
from modeler_project.dataroom.store import DataRoomStore

PROMPT_VERSION = "dataroom-2"
MAX_LINES = 120          # lines one read returns
PREVIEW_LINES = 40       # lines of each of the first parts the triage agent sees

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



def _loop(store: DataRoomStore, stage: str, file: str, model: ChatModel, **kw: Any) -> Any:
    """`run_tool_loop` with each turn written to the room's record of the agents' turns (which model answered, each
    tool's answer, each switch to another model)."""
    def log(step: dict[str, Any]) -> None:
        store.log_agent_step(stage=stage, file=file, model=getattr(model, "label", f"{model.provider}/{model.model}"),
                             step=step)
    return run_tool_loop(model, log_step=log, **kw)

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
Each product is {"name": as the files name it, "role": reference | test | original | reformulated | other}."""


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
    ranked = sorted(docs.items(), key=lambda kv: -weight(kv[0], kv[1][0]))[:4]
    per_file = max(800, focus_chars // 4)
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

    tools = _doc_tools(docs) + [_submit_tool("submit_question", QuestionCard, check, saved,
                                             "Submit the question card (with the quotes it rests on).")]
    step(0, 1, "reading the proposal and the request")
    outcome = _loop(store, "question", "", model, system=QUESTION_SYSTEM, tools=tools, max_turns=14, user=(
        f"The delivery's files:\n{listing}\n\nThe pages most likely to state the question:\n{material}\n\n"
        "Write the question card (each quote with its file)."))
    if not saved and _too_large(outcome.error):
        material = "\n\n".join(f"=== {p}\n{_focus(d, ['question'], budget=per_file // 3)}" for p, (_f, d) in ranked[:2])
        outcome = _loop(store, "question", "", model, system=QUESTION_SYSTEM, tools=tools, max_turns=8, user=(
            f"The delivery's files:\n{listing}\n\nThe pages most likely to state the question:\n{material}\n\n"
            "Write the question card (each quote with its file)."))
    if not saved:
        return f"no question card ({outcome.status}{': ' + outcome.error if outcome.error else ''})"
    # the model whose submission was saved: in a chain, the one the conversation ended on
    store.set_question(saved[0], by=f"agent:A6:{outcome.answered_by}", confirmed=False)  # type: ignore[arg-type]
    step(1, 1, "question card drafted: confirm it")
    return "question card drafted: confirm it"


# --- A7: triage -----------------------------------------------------------------------------------------------------------

TRIAGE_SYSTEM = _COMMON + """

Your job (A7): say what one file is for. purpose: "used" (it holds inputs or data the modelling needs), "context"
(background worth keeping: literature, a method, a certificate that matters), "not_needed" (administrative papers,
declarations, a duplicate printout), with one plain sentence why. topics from: """ + ", ".join(TOPICS) + """. Name the
study (its number) and the products the file is about, as written."""


def triage(store: DataRoomStore, model: ChatModel, *, actor: str, redo: bool, step: Step, only: set[str] | None = None,
          focus_chars: int = FOCUS_CHARS) -> str:
    docs = {p: v for p, v in _used_files(store).items() if only is None or p in only}
    todo = [(p, f, d) for p, (f, d) in docs.items() if redo or store.triage(f.sha256) is None]
    card, _confirmed = store.question()
    context = f"The question: {card.question}\n" if card else ""
    for done, (path, f, doc) in enumerate(todo, start=1):
        saved: list[BaseModel] = []
        tool = _submit_tool("submit_triage", FileTriage, lambda a, path=path: [] if a.path == path else
                            [f"path must be {path!r}"], saved, "Submit the file's triage.")
        text = "\n\n".join(_numbered(part, 1, PREVIEW_LINES) for part in _parts(doc)[:2])
        _loop(store, "triage", path, model, system=TRIAGE_SYSTEM, tools=[tool], max_turns=4, user=(
            f"{context}File: {path} ({f.kind}, {f.pages} pages; parts: {len(_parts(doc))})\n\nIts first lines:\n{text}"))
        if saved:
            store.put_triage(saved[0], f.sha256)  # type: ignore[arg-type]
        step(done, len(todo), path)
    return f"{len(todo)} files sorted"


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


def extract_system(topics: Sequence[str]) -> str:
    """The extractor's instructions for one file: the fields and table kinds its topics need (all of them when the
    triage gave no topic), so a small model's context holds the file rather than the vocabulary."""
    prefixes = {p for t in topics for p in _TOPIC_FIELDS.get(t, ())} or {f.split(".")[0] + "." for f in FIELDS}
    kinds = {k for t in topics for k in _TOPIC_KINDS.get(t, ())} or set(ROLES)
    fields = "\n".join(f"   {k}: {v}" for k, v in FIELDS.items() if k.startswith(tuple(prefixes)))
    roles = "\n".join(f"   {k}: {', '.join(v)}" for k, v in ROLES.items() if k in kinds)
    return _COMMON + f"""

Your job (A8): for one file, find every input the checklist asks for and answer with:
1. table descriptions: kind, part, header lines, first and last data line, summary lines (the client's mean or RSD
   rows), and for each cell position its role. A column whose header is a time gets "time" (as the header writes it);
   side-by-side blocks (a batch, a product) get "group" as written. One description per page a table covers. Roles:
{roles}
   Concentrations: each value cell gets role "value" and its time; give the time unit and the concentration unit as
   written; zero_means_blq when the file writes values below the LLOQ as 0. A marker is either below the LLOQ (BLQ,
   <LLOQ) or a missing sample (".", NS), never both. A table's shared values (medium, pH, volume, rpm, apparatus,
   study) go in constants only as a file writes them, and each is also a fact.
2. facts, each with its verbatim quote. Fields (a new dotted name only when none fits):
{fields}
   subject: what the fact is about (a study number, a treatment code, a batch). product: the question card's product
   name when the fact concerns one. One fact per treatment code (subject = the code; value = what the documents say
   it is, e.g. "Refamide 100 mg (reference product)"). Each batch or lot a file links to a product is a fact
   product.batch (value = the batch, product = the product). Subject lists (completed, excluded) hold the numbers
   only; the reason goes in note.
3. not_found: the checklist ids you looked for here and did not find."""


EXTRACT_SYSTEM = extract_system(())   # the whole vocabulary (kept for reference and tests)


def _extraction_problems(answer: Extraction, path: str, f: FileView, doc: SourceDocument) -> list[str]:
    problems = []
    for i, table in enumerate(answer.tables, start=1):
        got = read_table(table.model_copy(update={"file": path}), doc, file=path, sha256=f.sha256)
        problems += [f"table {i} ({table.kind}, {table.part}): {p.message}" for p in got.problems if p.severity == "error"]
        if not got.rows and not got.problems:
            problems.append(f"table {i} ({table.kind}, {table.part}): no data lines in {table.first_line}–{table.last_line}")
        unknown = {c.role for c in table.columns} - set(ROLES.get(table.kind, ())) - {"unit", "value", "time"}
        if unknown and table.kind in ROLES:
            problems.append(f"table {i}: roles not known for {table.kind}: {', '.join(sorted(unknown))}")
    for fact in answer.facts:
        got = check_fact(fact.model_copy(update={"file": path}), doc, file=path, sha256=f.sha256)
        if not got.ok:
            problems.append(f"fact {fact.field} = {fact.value!r}: {got.problem}")
    return problems


def extract(store: DataRoomStore, model: ChatModel, *, actor: str, redo: bool, step: Step, only: set[str] | None = None,
            focus_chars: int = FOCUS_CHARS) -> str:
    docs = {p: v for p, v in _used_files(store).items() if only is None or p in only}
    card, _confirmed = store.question()
    checklist = "\n".join(f"- {c.id} [{c.area}] {c.label} (topics: {', '.join(c.topics)})" for c in (card.checklist if card else ()))
    products = "\n".join(f"- {p.name} ({p.role})" for p in (card.products if card else ()))
    todo = []
    for path, (f, doc) in docs.items():
        t = store.triage(f.sha256)
        if t is not None and t.purpose != "used":
            continue
        if redo or store.extraction(f.sha256) is None:
            todo.append((path, f, doc, t))
    failed: list[str] = []
    for done, (path, f, doc, t) in enumerate(todo, start=1):
        saved: list[BaseModel] = []
        tool = _submit_tool("submit_extraction", Extraction,
                            lambda a, path=path, f=f, doc=doc: _extraction_problems(a, path, f, doc), saved,
                            "Submit this file's tables and facts.")
        tools = [x for x in _doc_tools({path: (f, doc)}) if x.name != "search"] + [_search_one(path, doc), tool]
        topics = list(t.topics) if t else []

        def user(budget: int, path: str = path, f: FileView = f, doc: SourceDocument = doc, t: FileTriage | None = t,
                 topics: list[str] = topics) -> str:
            return (f"The question: {card.question if card else '(not set)'}\nThe products:\n{products or '(not set)'}\n"
                    f"The checklist:\n{checklist or '(not set)'}\n\nFile: {path} ({f.kind}; "
                    f"{'OCR on pages ' + ', '.join(map(str, f.ocr_pages)) if f.ocr_pages else 'text layer'})"
                    f"{'; the triage says: ' + t.reason if t else ''}\n\nIts parts: "
                    f"{', '.join(f'{p.name} ({len(p.lines)} lines)' for p in _parts(doc)[:120])}\n\n"
                    f"The pages most likely to hold what the checklist needs (open others with the tools):\n"
                    f"{_focus(doc, topics, budget=budget)}")
        budget = max(2000, focus_chars)
        outcome = _loop(store, "extract", path, model, system=extract_system(topics), user=user(budget), tools=tools,
                        max_turns=14)
        if not saved and _too_large(outcome.error):      # a provider's per-request limit: the same, with fewer pages
            outcome = _loop(store, "extract", path, model, system=extract_system(topics), user=user(budget // 3),
                            tools=tools, max_turns=10)
        if not saved:
            failed.append(f"{path}: no answer ({outcome.status}{': ' + outcome.error[:200] if outcome.error else ''})")
        if saved:
            answer = saved[0].model_copy(update={"file": path})
            store.put_extraction(answer, f.sha256, agent={"agent": "A8", "model": outcome.answered_by,  # type: ignore[arg-type]
                                                         "prompt": PROMPT_VERSION})
        step(done, len(todo), path)
    store.set_stage_notes("extract", failed)
    return f"{len(todo) - len(failed)} of {len(todo)} files extracted" + (f"; {len(failed)} gave no answer" if failed else "")


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
lines as code read them (role = cell text). Say for each table whether the roles fit the headers (a time under the
right column, the treatment code not taken for the period, a batch block not shifted by one cell). Answer with the
submit tool: one item per table, ok true or false, and the issue in one sentence."""


class _Review(BaseModel):
    tables: list[dict[str, Any]]


def check(store: DataRoomStore, model: ChatModel, *, actor: str, redo: bool, step: Step, only: set[str] | None = None,
          focus_chars: int = FOCUS_CHARS) -> str:
    docs = {p: v for p, v in _used_files(store).items() if only is None or p in only}
    todo = [(p, f, d, got[0]) for p, (f, d) in docs.items() if (got := store.extraction(f.sha256)) and got[0].tables]
    issues = 0
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
        done_check = _loop(store, "check", path, model, system=CHECK_SYSTEM, tools=[tool], max_turns=4,
                           user=f"File: {path}\n\n" + "\n\n".join(shown))
        if saved:
            review = [t for t in saved[0].tables if not t.get("ok", True)]  # type: ignore[attr-defined]
            issues += len(review)
            store.put_review(f.sha256, review, agent=done_check.answered_by)
        step(done, len(todo), path)
    return f"{len(todo)} files checked, {issues} issues"


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
        "sections": [s.model_dump() for s in view.sections],
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
    written = _loop(store, "write", "", model, system=WRITE_SYSTEM, tools=[tool], max_turns=6, user=material)
    if not saved:
        return "nothing written"
    a = saved[0]
    store.put_writing({k: v for k, v in a.findings.items() if _numbers_ok(v, material)},  # type: ignore[attr-defined]
                      {k: v for k, v in a.requests.items() if _numbers_ok(v, material)},  # type: ignore[attr-defined]
                      agent=written.answered_by)
    step(1, 1, "written")
    return "findings and request wording written"


__all__: Sequence[str] = ("check", "extract", "question", "triage", "write")
