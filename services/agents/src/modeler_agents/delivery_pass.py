"""Agent A4 · The delivery pass (docs/plans/2026-11-10-add-data-agent-reads-everything.md, R4; the owner's decision 2):
before the files of a delivery are read one by one, the agent looks at all of them together and drafts the delivery
map: which study, product (test or reference), strength, batch, fed or fasted, medium and pH each file, or each sheet of
a workbook, is about; and which two names in different files are one study, product or batch.

The agent sees each new file's name, its sheets' headers or its first page, and what the map already says about the
files of earlier uploads (a single file is checked against the map). Every value is quoted from the file (a page, a
cell, or the file's name) and checked by code: the quote is there verbatim, and it states the value (the name, the
number with its unit, a word for fed or fasted, test or reference). What code refuses is told to the agent and kept.

The map is context, not data: each file's own reading is told what the map says, and every value it proposes is still
quoted from that file. A link becomes the question a person answers on Inputs (`client_review`), as a document's do.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from modeler_agents.llm import ChatModel, LoopOutcome, Tool, run_tool_loop
from modeler_agents.sheet_reader import _cell_text
from modeler_intake.citations import normalize_for_match
from modeler_intake.document_reading import CHOICES, check_quote, supports_choice, text_in
from modeler_intake.grid import WorkbookGrid
from modeler_project.delivery_map import FIELDS, file_line
from modeler_project.documents import DocumentLibrary

PAGE_CHARS = 6000
OVERVIEW_CHARS = 1400        # a document's first page, in the first message
WORKBOOK_CHARS = 3000        # a workbook's sheets together (each named; each its share of the rows)
HEADER_ROWS = 8
HEADER_COLUMNS = 12
LINK_KINDS = ("study", "product", "batch")
ROLES = tuple(r for r in CHOICES["role"] if r != "OTHER")
FOOD = CHOICES["food_state"]
_MG = re.compile(r"(?<![a-zµ])mg(?![a-z])", re.IGNORECASE)
_PH = re.compile(r"\bpH\b", re.IGNORECASE)

SYSTEM_PROMPT = """You are A4, mapping a client's delivery before each file is read. You see every new file of the
delivery together: its name, the headers of each sheet of a workbook, or the first page of a PDF or Word file, and what
the map already says about files delivered before.

For each file, and for each sheet of a workbook whose sheets differ (one sheet per medium or pH, per product, per study),
say what it is about with propose_facts: study (the study code), product, role (TEST, RLD or REFERENCE), strength_mg,
batch, food_state (fasted or fed), medium, ph. Give only what the file states: each fact needs a quote copied exactly
from where it is written, with its source: "page" (and the page), "cell" (and the cell, e.g. "pH 6.8!A1"), "sheet"
(words of the sheet's own name, for a sheet's facts, e.g. "pH 4.5"), or "name" (words of the file's name, e.g. "093-26"
in "093-26-Desvenlafaxine-PK Table.xlsx"). A number is quoted with its unit ("50 mg", "pH 6.8"). A file holding two
products, strengths or conditions gives them per sheet, or leaves them out.

When two files give one study, product or batch two names ("Study 093-26" and "Protocol DVS-BE-01"; "APL 50" and
"Test product"), propose_link with a quote from a page or cell that writes both names and says they are one. Never
guess a link from similar names or from file names.

Use read_page and read_sheet when the overview is not enough. Propose nothing you cannot quote. Code checks every quote
and tells you what it refused; fix it or leave it. When every file is mapped as far as its text allows, stop."""


@dataclass
class DeliveryFile:
    sid: str
    file: str
    sha: str
    kind: str
    workbook: WorkbookGrid | None = None
    pages: list[str] = field(default_factory=list)


@dataclass
class DeliveryContext:
    library: DocumentLibrary
    files: list[DeliveryFile]
    actor: str
    mapped: dict[str, Any] = field(default_factory=dict)       # the map before this pass (earlier uploads)
    found: dict[str, dict[str, Any]] = field(default_factory=dict)   # sid -> {"file", "facts", "sheets"}
    links: list[dict[str, Any]] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)

    def file(self, sid: str) -> DeliveryFile | None:
        return next((f for f in self.files if f.sid == sid), None)

    def refuse(self, what: str, why: str) -> str:
        self.refused.append(f"{what}: {why}")
        return f"REFUSED {what}: {why}"


def _parse(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


_TOKEN = re.compile(r"[A-Za-z0-9]+")
_MG_VALUE = re.compile(r"(\d+(?:\.\d+)?)\s*mg(?![a-z/])", re.IGNORECASE)
_PH_VALUE = re.compile(r"\bpH\s*[:=]?\s*(\d{1,2}(?:\.\d+)?)", re.IGNORECASE)
MIN_CELL_QUOTE = 3


def tokens(text: str) -> list[str]:
    """Words and numbers, case aside; an underscore or hyphen separates them ("Fast_230-23" is fast, 230, 23)."""
    return [t.lower() for t in _TOKEN.findall(text)]


def tokens_in(value: str, text: str) -> bool:
    """Whether the value's words and numbers stand in the text in a row, as whole words ("093-26" in "Study 093/26",
    not "93" in "093-26")."""
    want, have = tokens(value), tokens(text)
    return bool(want) and any(have[i:i + len(want)] == want for i in range(len(have) - len(want) + 1))


def _source(ctx: DeliveryContext, f: DeliveryFile, item: dict[str, Any], *, sheet: str = "") -> tuple[str | None, str]:
    """(why the quote's source is refused or None, where it is: "p. 2", "Sheet!A1", "file name", "sheet name")."""
    quote = str(item.get("quote") or "")
    source = item.get("source")
    if not quote.strip():
        return "no quote", ""
    if source == "name":
        ok = tokens_in(quote, f.file)
        return (None if ok else "the quote is not words of the file's name"), "file name"
    if source == "sheet":
        if not sheet:
            return "a sheet-name source is for a sheet's facts (give the sheet)", ""
        ok = tokens_in(quote, sheet)
        return (None if ok else "the quote is not words of the sheet's name"), "sheet name"
    if source == "page":
        page = item.get("page")
        if not isinstance(page, int) or not f.pages:
            return "a page source needs a page of a PDF or Word file", ""
        why = check_quote(f.pages[page - 1] if 0 < page <= len(f.pages) else None, quote)
        return why, f"p. {page}"
    if source == "cell":
        cell = str(item.get("cell") or "")
        if f.workbook is None:
            return "a cell source needs a workbook", ""
        text = _cell_text(f.workbook, cell)
        if text is None:
            return f"no cell {cell!r} in this workbook (write it as Sheet!A1)", ""
        if len(normalize_for_match(quote)) < MIN_CELL_QUOTE:
            return f"quote at least {MIN_CELL_QUOTE} characters of the cell", ""
        ok = tokens_in(quote, text) or normalize_for_match(quote).lower() in normalize_for_match(text).lower()
        return (None if ok else f"the quote is not in cell {cell}"), cell
    return "source must be page, cell, sheet or name", ""


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def check_value(field_name: str, value: Any, quote: str) -> tuple[str | None, Any]:
    """(why the value is refused or None, the value kept): the quote must state it. A number stands next to its unit
    ("50 mg", "pH 6.8"); a name is the quote's whole words; a word says fed or fasted, test or reference."""
    text = str(value).strip() if value is not None else ""
    spaced = re.sub(r"[_\-]+", " ", quote)
    if field_name not in FIELDS:
        return f"unknown fact {field_name!r} (one of {', '.join(FIELDS)})", None
    if field_name in ("strength_mg", "ph"):
        number = _number(value)
        if number is None:
            return "a number is needed", None
        if field_name == "ph" and not 0 <= number <= 14:
            return "a pH is between 0 and 14", None
        stated = _MG_VALUE.findall(spaced) if field_name == "strength_mg" else _PH_VALUE.findall(spaced)
        if not any(abs(float(s) - number) < 1e-9 for s in stated):
            unit = "mg" if field_name == "strength_mg" else "pH"
            return f"the quote does not state {number:g} with its {unit} (\"50 mg\", \"pH 6.8\")", None
        return None, number
    if not text:
        return "no value", None
    if field_name == "role":
        role = text.upper()
        if role not in ROLES:
            return f"role is one of {', '.join(ROLES)}", None
        return (None, role) if supports_choice(role, spaced) else ("the quote does not say it", None)
    if field_name == "food_state":
        food = text.lower()
        if food not in FOOD:
            return "food_state is fasted or fed", None
        return (None, food) if supports_choice(food, spaced) else ("the quote does not say it", None)
    if field_name == "study":
        return (None, text) if tokens_in(text, quote) else ("the quote does not write the study's name as whole words", None)
    return (None, text) if tokens_in(text, quote) or text_in(text, quote) else ("the quote does not write it", None)


def propose_facts(ctx: DeliveryContext, *, sid: str, facts: Any, sheet: str = "") -> str:
    f = ctx.file(sid)
    if f is None:
        return ctx.refuse(f"facts of {sid}", "not a file of this pass")
    if sheet and (f.workbook is None or sheet not in f.workbook.sheets):
        return ctx.refuse(f"facts of {f.file} sheet {sheet}", "no such sheet")
    items = _parse(facts)
    if not isinstance(items, list) or not items:
        return ctx.refuse(f"facts of {f.file}", "facts must be a list of {fact, value, source, quote}")
    entry = ctx.found.setdefault(sid, {"file": f.file, "facts": {}, "sheets": {}})
    into = entry["sheets"].setdefault(sheet, {"facts": {}})["facts"] if sheet else entry["facts"]
    answers = []
    for item in items:
        if not isinstance(item, dict):
            answers.append(ctx.refuse(f"a fact of {f.file}", "each fact is an object"))
            continue
        name = str(item.get("fact") or "")
        what = f"{name} of {f.file}" + (f" sheet {sheet}" if sheet else "")
        why, where = _source(ctx, f, item, sheet=sheet)
        if why:
            answers.append(ctx.refuse(what, why))
            continue
        why, value = check_value(name, item.get("value"), str(item["quote"]))
        if why:
            answers.append(ctx.refuse(what, why))
            continue
        earlier = into.get(name, {}).get("value")
        refines = isinstance(earlier, str) and isinstance(value, str) and tokens_in(earlier, value)   # a fuller name
        if name in into and earlier != value and not refines:   # one value per file or sheet: a file with two is per sheet
            answers.append(ctx.refuse(what, f"already {into[name]['value']} here; a file holding more than one gives it "
                                            "per sheet, or leaves it out"))
            continue
        into[name] = {"value": value, "quote": str(item["quote"])[:400], "where": where}
        answers.append(f"ACCEPTED {what} = {value}")
    if sheet and not into:
        entry["sheets"].pop(sheet, None)
    return "\n".join(answers)


def propose_link(ctx: DeliveryContext, *, kind: str, names: Any, sid: str, quote: str, source: str = "page",
                 page: int | None = None, cell: str = "") -> str:
    pair = _parse(names)
    what = f"link {pair}"
    if kind not in LINK_KINDS:
        return ctx.refuse(what, f"kind is one of {', '.join(LINK_KINDS)}")
    if not isinstance(pair, list) or len(pair) != 2 or not all(isinstance(n, str) and n.strip() for n in pair):
        return ctx.refuse(what, "names must be the two names")
    a, b = tokens(pair[0]), tokens(pair[1])
    if not a or not b or a == b or tokens_in(pair[0], pair[1]) or tokens_in(pair[1], pair[0]):
        return ctx.refuse(what, "the two names are the same name, or one is part of the other")
    if source not in ("page", "cell"):
        return ctx.refuse(what, "a link is quoted from a page or a cell that says the two are one")
    f = ctx.file(sid)
    if f is None:
        return ctx.refuse(what, f"{sid} is not a file of this pass")
    why, where = _source(ctx, f, {"quote": quote, "source": source, "page": page, "cell": cell})
    if why:
        return ctx.refuse(what, why)
    if not (tokens_in(pair[0], quote) and tokens_in(pair[1], quote)):
        return ctx.refuse(what, "the quote must write both names")
    ctx.links.append({"kind": kind, "names": [pair[0].strip(), pair[1].strip()], "sid": sid, "page": page if source == "page" else None,
                      "locator": where, "quote": quote[:400]})
    return f"ACCEPTED {kind} link {pair[0]} = {pair[1]}"


def read_page(ctx: DeliveryContext, *, sid: str, page: int) -> str:
    f = ctx.file(sid)
    if f is None or not f.pages:
        return f"{sid}: not a PDF or Word file of this pass"
    if not 0 < page <= len(f.pages):
        return f"{f.file} has pages 1 to {len(f.pages)}"
    return f"{f.file}, p. {page}:\n{f.pages[page - 1][:PAGE_CHARS]}"


def read_sheet(ctx: DeliveryContext, *, sid: str, sheet: str) -> str:
    f = ctx.file(sid)
    if f is None or f.workbook is None:
        return f"{sid}: not a workbook of this pass"
    if sheet not in f.workbook.sheets:
        return f"{f.file} has no sheet {sheet!r}; its sheets: {', '.join(f.workbook.sheets)}"
    return f"{f.file}, sheet {sheet}:\n{f.workbook.sheets[sheet].preview(max_rows=15, max_columns=20)}"


def overview(f: DeliveryFile) -> str:
    """What the agent first sees of a file: every sheet's name and the first rows of each (each sheet its share of the
    budget, so no sheet is left out), or the first page of a PDF or Word file."""
    if f.workbook is not None:
        names = list(f.workbook.sheets)
        share = max(120, WORKBOOK_CHARS // max(1, len(names)))
        parts, used = [f"sheets: {', '.join(names)}"], 0
        for name in names:
            if used >= WORKBOOK_CHARS:   # every sheet is named above; read_sheet for the rest
                parts.append("(the other sheets' rows: read_sheet)")
                break
            preview = f.workbook.sheets[name].preview(max_rows=HEADER_ROWS, max_columns=HEADER_COLUMNS)
            shown = preview if len(preview) <= share else preview[:share] + " …"
            parts.append(f"sheet {name}:\n{shown}")
            used += len(shown)
        return "\n".join(parts)
    if f.pages:
        text = f"{len(f.pages)} pages; p. 1:\n{f.pages[0]}"
        return text if len(text) <= OVERVIEW_CHARS else text[:OVERVIEW_CHARS] + " …(read_page for more)"
    return "(no text: a scan, or a file kind with nothing to read)"


def brief_for(ctx: DeliveryContext, *, drug: str) -> str:
    lines = [f"Drug: {drug or 'not named'}. New files: {len(ctx.files)}."]
    earlier = [(entry.get("file", sid), file_line(entry)) for sid, entry in ctx.mapped.get("files", {}).items()
               if not ctx.file(sid)]
    earlier = [(name, line) for name, line in earlier if line]
    if earlier:
        lines.append("The map already says, of files delivered before (check the new files against it):")
        lines += [f"- {name}: {line}" for name, line in earlier[:40]]
    for f in ctx.files:
        lines.append(f"\n## {f.file} (sid {f.sid}, {f.kind})\n{overview(f)}")
    return "\n".join(lines)


def build_tools(ctx: DeliveryContext) -> list[Tool]:
    s, i = {"type": "string"}, {"type": "integer"}
    fact = {"type": "object", "properties": {"fact": {"type": "string", "enum": list(FIELDS)}, "value": {},
                                             "source": {"type": "string", "enum": ["page", "cell", "sheet", "name"]},
                                             "page": i, "cell": s, "quote": s},
            "required": ["fact", "value", "source", "quote"]}
    return [
        Tool("read_page", "Read one page of a PDF or Word file of this delivery.",
             {"type": "object", "properties": {"sid": s, "page": i}, "required": ["sid", "page"]},
             lambda **kw: read_page(ctx, **kw)),
        Tool("read_sheet", "Read the first rows of one sheet of a workbook of this delivery.",
             {"type": "object", "properties": {"sid": s, "sheet": s}, "required": ["sid", "sheet"]},
             lambda **kw: read_sheet(ctx, **kw)),
        Tool("propose_facts", "What one file (or one sheet of a workbook: give `sheet`) is about, each fact quoted.",
             {"type": "object", "properties": {"sid": s, "sheet": s, "facts": {"type": "array", "items": fact}},
              "required": ["sid", "facts"]}, lambda **kw: propose_facts(ctx, **kw)),
        Tool("propose_link", "Two names one file writes for one study, product or batch, quoted.",
             {"type": "object", "properties": {"kind": {"type": "string", "enum": list(LINK_KINDS)},
                                               "names": {"type": "array", "items": s}, "sid": s,
                                               "source": {"type": "string", "enum": ["page", "cell"]},
                                               "page": i, "cell": s, "quote": s},
              "required": ["kind", "names", "sid", "quote"]}, lambda **kw: propose_link(ctx, **kw)),
    ]


def run_delivery_pass(model: ChatModel, ctx: DeliveryContext, *, drug: str = "", max_turns: int | None = None,
                      log_step: Callable[[dict[str, Any]], None] = lambda s: None) -> LoopOutcome:
    """Map the files of `ctx`; what code accepted is on `ctx.found` and `ctx.links`, what it refused on `ctx.refused`."""
    turns = max_turns if max_turns is not None else min(30, 6 + len(ctx.files))
    return run_tool_loop(model, system=SYSTEM_PROMPT, user=brief_for(ctx, drug=drug), tools=build_tools(ctx),
                         max_turns=turns, log_step=log_step)


def map_and_record(model: ChatModel, ws: Any, library: DocumentLibrary, sids: list[str], *, actor: str, drug: str = "",
                   run_id: str | None = None, max_turns: int | None = None,
                   log_step: Callable[[dict[str, Any]], None] = lambda s: None) -> tuple[DeliveryContext, LoopOutcome]:
    """Map these client files (their submissions) together, against what the map already says, and record on the map
    what code accepted (`client_data.record_delivery_map`). Every file given is marked as looked at, found or not."""
    from modeler_intake.grid import read_workbook_bytes
    from modeler_project.client_data import READABLE_DOCUMENTS, delivery_map, record_delivery_map, submission

    files: list[DeliveryFile] = []
    for sid in dict.fromkeys(sids):
        content = submission(ws, sid)
        if content is None:
            continue
        f = DeliveryFile(sid=sid, file=str(content["file"]), sha=str(content["sha256"]), kind=str(content.get("kind", "")))
        if content.get("kind") in READABLE_DOCUMENTS:
            f.pages = library.pages(f.sha)
        else:
            path = ws.store.blob_path(ws.tenant_id, ws.project_id, f.sha)
            if path is not None:
                try:
                    f.workbook = read_workbook_bytes(path.read_bytes(), f.file)
                except ValueError:
                    f.workbook = None
        files.append(f)
    mapped = delivery_map(ws)
    hidden = {sid for sid in mapped["files"] if (c := submission(ws, sid)) is None
              or (library.has_record and library.entry(c["sha256"]).withdrawn is not None)}   # gone, or withdrawn
    mapped = {**mapped, "files": {k: v for k, v in mapped["files"].items() if k not in hidden},
              "links": [link for link in mapped["links"] if link.get("sid") not in hidden]}
    ctx = DeliveryContext(library=library, files=files, actor=actor, mapped=mapped)
    outcome = run_delivery_pass(model, ctx, drug=drug, max_turns=max_turns, log_step=log_step)
    # a pass that did not finish (the provider down, the turns used up) marks as looked at only the files it mapped;
    # the others are tried again (`intake_jobs.map_waiting`), at most a few times
    done = outcome.status == "COMPLETED"
    record_delivery_map(ws, files=ctx.found, links=ctx.links,
                        looked_at=[f.sid for f in files if done or f.sid in ctx.found], refused=ctx.refused,
                        summary=outcome.final_text or (outcome.error or ""), run_id=run_id, by=actor,
                        tried=[f.sid for f in files], status=outcome.status)
    return ctx, outcome
