# Client-data intake rebuild: the code-level contracts (2026-11-12)

Status: **contract for the parallel builds** of `2026-11-12-client-data-intake-redesign.md` (revision 3; "the plan").
Eight builds (D0, D1a, D1b, D2, D3, D4, D5, SD) are written side by side, each in its own worktree from the commit
that holds the contract code (§7), against this file; W (wiring) and D6 (review) follow the merge. Where this file and the plan differ, the plan's gates
(§7.1) and the owner's decisions (§10) win and the difference is listed in §11.

How to read it: §4 to §6 are the types and signatures every builder imports; §7 is the code one engineer commits
first; §8 is one brief per build. Verified against the code at `ab1e725`; "probe" means a read-only run in the
architect's session (no file of the repository changed).

Revision 2 (2026-11-13): three reviews (governance, science and data fidelity, parallel buildability; 49 findings)
were checked against the code and resolved in this file; §12 lists each finding and where it was settled.

## 1. Principles and what does not change

1. **Beside, not instead.** The new pipeline is new modules. Today's readers, routes, cards, tests and e2e specs stay
   byte for byte, except D1a's landing changes (§8.2) and the hooks W and D6 add after the merge (§8.9, §8.10).
2. **Parallel builders create new files only.** D1a alone edits existing files, and only those named in §8.2.
3. **No locked file changes in the main line**: no new `ArtifactKind`, no new file under a locked pattern, no new
   reader of the environment, no migration. D1b is the one locked change, alone on its branch.
4. **A number is read by code.** The LLM's only outputs are a mapping spec (tables) and quoted facts that code
   re-reads (prose). No digit of a table body is ever in a prompt (§4.4).
5. **Every value has an anchor** (§4.1) or is a person's entry bound by a signature, or names its inputs (derived).
6. **Append and supersede.** Every new record is a line of an append-only, hash-chained file beside the artifacts.
7. **Model inputs are written only by their owner modules** (`dataset_register`, `dissolution_register` through
   `client_data.record_mapping`, `evidence_register`), and only by a signed confirmation.
8. **Units are never renamed.** A value's unit class is its **field's** (`fields.FIELDS`), never guessed from the unit
   text (the tables read `µm` and `mm` as molar concentrations). The unit is checked against the existing table of
   that class: concentration `validate.CONCENTRATION_UNITS`, time `validate.TIME_UNITS`, percentage
   `validate.FRACTION_UNITS`, mass the dose units today's fact check accepts (`document_reading._MG_PER` and `mg/kg`,
   imported by `fields`, never retyped). Outside its table a unit is kept verbatim and raised by `UNIT_NOT_IN_TABLES`; a
   field whose class has no table (ratio, other: PK-parameter units, rpm, mL, µm, kg) keeps its unit unchecked and
   says so (`UNIT_NOT_CHECKED`, info). No new unit table (§11.23).
9. **Science choices keep today's behaviour by default** (BLQ rule, residual weighting, geometric spreads). Anything
   that judges data sits in one `UNVERIFIED` YAML (§4.7).

Unchanged, and not to be edited by any parallel build: `modeler_intake/{grid,recipe,apply,records,recipe_review,
sheet_form,triage,cleaning,validate,documents,document_reading,citations,client_template,pksim}.py`;
`modeler_project/{client_review,reading_queue,documents,library,delivery_map,delivery_report,requirements,
dataset_register,dissolution_register,evidence_register,blinding,dataset_points}.py`; every agent module; every router
and view; the web app; every locked file. `StudyRecord`, `ArtifactKind`, `records.SourceRef` and the v1 recipe keep
their shape. The API contract changes in the parallel phase by exactly one optional field (`Series.n_at`, D1a).

Guardrails every new module must pass (`tests/architecture`):
- imports point down (L0 `pbpk_domain`, L2 `modeler_intake`, L3 `modeler_project`, L4 `modeler_agents`, L6
  `modeler_api`); a package's tests obey the same rule (an intake test cannot import `modeler_project`: that is why
  `canonical` and `sha256_of` live in L2, `DI/anchors.py`, and `DI/synthetic.py` writes its PDF itself);
- no `os.environ`; options arrive as arguments;
- no module-level `set()`, `dict()`/`{}`, `[]`, `Lock()`, `defaultdict()`, `deque()`, `Queue()`; use tuples,
  `frozenset({...})`, non-empty literals or an `lru_cache` function;
- `test_artifact_owners.py` counts **any** `x.content[...]`, `x.content.get(...)` or `**x.content` in a non-owner
  module: never name an attribute `content` in new code (this contract uses `body`), and read stored artifacts only
  through their owner's functions (`client_data.submission()`, `dataset_register.datasets()`, ...);
- models are frozen pydantic: `ConfigDict(frozen=True, extra="forbid")`, tuples for sequences; ruff, line 130.

## 2. Coexistence and the switch

One field on `modeler_api.config.Settings` (W adds it):

```python
# What runs when a client file arrives. "both": today's readers, and the new pipeline with its own surface
# (Inputs → Delivery). "legacy": today's readers only; the new pipeline writes nothing.
intake_pipeline: Literal["both", "legacy"] = "both"          # MODELER_INTAKE_PIPELINE
```

| | `legacy` | `both` (default) |
|---|---|---|
| A file arrives (Start, Add data, an Inputs tab, a library document read for data) | `client_data.ingest`, as today | the bytes are stored and recorded first (`intake_files.record_arrival`), then `ingest` exactly as today (same answer, same 422), then one pipeline run is queued per file |
| Background | the `reading` job, only with a model (unchanged) | the same, plus the `intake` job, which starts with or without a model |
| Deterministic stages (parse, locate, rule and cache mapping, execute, ledger, compute, checks, coverage) | off | every file, agents on or off |
| LLM stages (`A4-table-mapper`, `A4-prose`) | off | only when the console's A4 setting gives a model |
| Surfaces | today's cards | today's cards, and the Delivery section (D6) |
| Reaching the model | a legacy card's confirm (unsigned) | that, or a signed Delivery confirmation |

**Why `both` is the default.** On the next deployment every arriving file, and (through `sweep` on the first open
of Inputs) every file already stored, gets its source model, its ledger and its coverage numbers with agents off:
the owner sees the coverage panel and the ledger for every file. Nothing of today's flow depends on it: the hook
adds one file append to the upload request and a second background job with its own lease; a failure of the new
pipeline is caught in its job and never reaches a legacy answer. `legacy` is the rollback: set the variable, restart.

**The API test suite runs `legacy` unless a test asks.** Several existing API tests script the A4 model turn by
turn (`Scripted`); a second consumer of that model would take their turns, and a second background thread would
append audit events between their assertions. W adds one autouse fixture to `services/api/tests/conftest.py`
(`monkeypatch.setenv("MODELER_INTAKE_PIPELINE", "legacy")`); new tests call `api_settings(..., intake_pipeline="both")`.
W's coexistence test (§8.9) proves the legacy answers, upload and page routes, are identical in both modes. The e2e
suite runs the default; the build container has no browser, so it first runs on the Mac or the server, before the
first deployment with `both` (W's and D6's CHANGELOG entries say so).

**Nothing is loaded twice.** The first confirmation wins; the other surface shows it and refuses a second one.
- **Overlap is decided by source, never by name** (`intake_landing.legacy_overlap`): a client dataset overlaps a
  Delivery subject when it comes from a file the confirmation binds values from (`source.doc_sha256`), from one of the
  bound sheets (a recipe of that file's submission naming the sheet lists the dataset) or pages (`source.page`), and
  either its study key equals the subject's label key or one of its points equals a bound value of that sheet or page
  (the same time in minutes and the same number). A legacy study id made from the file name (`sheet_form.py:513-519`)
  therefore still overlaps; another study's table on the same sheet does not.
- *Delivery first.* `intake_landing.land` writes the subject's datasets through `dataset_register` (origin `CLIENT`,
  `ACCEPTED`, `note` naming the confirmation), its dissolution rows through `client_data.record_delivery_rows` (§6.6),
  and then calls `client_data.record_mapping(ws, sid, recipe={"recipe_id": "delivery-<cf id>", "version": 1, "tables":
  [{"sheet": <each sheet or "p<page>" the bound values are anchored in>}]}, dataset_ids=..., dissolution=[],
  replaces=<the legacy recipes of those sheets>)`. With no legacy edit this makes `sheet_intake._read_sheets` count the
  sheets as read: their drafts leave the legacy card, `finish` refuses them, and the legacy study group shows the
  landed datasets as confirmed. `land` rejects, through `dataset_register.decide_dataset`, every still `PROPOSED`
  overlapping client dataset (reason: "replaced by Delivery confirmation cf-n").
- *Legacy first.* The Delivery card lists `loaded_elsewhere` (the non-rejected overlapping client datasets). While one
  of them is `ACCEPTED` the Delivery confirmation is refused (409 `LOADED_ON_CLIENT_REVIEW`); rejecting it on the
  legacy card frees it.
- *Guards (D6, in `both` only).* `client-review:confirm`, `client-review:finish` and `client-data/{sid}:map` with
  `confirm` refuse (409 `LOADED_ON_DELIVERY`) what a signed Delivery confirmation already covers, by the same overlap
  (`intake_review.covered_by_confirmation`).
- A filled client-data template is read exactly by today's no-AI path and is confirmed on its legacy card only; the
  Delivery section shows its coverage and ledger read-only (`confirm_on: "client-review"`).
- Last line of defence, unchanged: `inputs.study_catalog` uses one dataset per study id and names the other.

## 3. Module map

Owner: **C** contract code (§7), then the build. `PD` = `packages/pbpk-domain/src/pbpk_domain`, `DI` =
`packages/data-intake/src/modeler_intake`, `PM` = `packages/project-model/src/modeler_project`, `AG` =
`services/agents/src/modeler_agents`, `API` = `services/api/src/modeler_api`, `WEB` = `apps/web`.

| Layer | Path | Owner | Holds |
|---|---|---|---|
| L0 | `PD/spread.py` | C | SE and CV% to SD, versioned (pure) |
| L0 | `PD/units.py`, `PD/fit_spec.py` (edits) | D1a | geometric SD left unscaled; `pi_observed(error_type=)` |
| L0 | `PD/requirement_drafts/{__init__.py,biologics.yaml,dermal.yaml,ocular.yaml}` | SD | inert draft checklists |
| L2 | `DI/anchors.py` | C | anchor models and grammar; id patterns; `canonical`, `sha256_of` (one canonical form for L2 tests and L3 stores) |
| L2 | `DI/source_model.py` | C | source model, regions, `RegionGrid`, engine Protocols |
| L2 | `DI/fields.py` | C | ledger field vocabulary, table kinds, document roles |
| L2 | `DI/mapping_spec.py` | C | mapping spec v2, extraction results, LLM input and prose models |
| L2 | `DI/synthetic.py` | C | shared synthetic files with their truth |
| L2 | `DI/source/{__init__,parse,workbook,delimited,docx,pdf,text,archive,regions,roles,resolve,inventory}.py` | D2 | parse once, locate, resolve, format inventory (core) |
| L2 | `DI/mapping/{__init__,fingerprint,rules,validate,execute,redact,prose_check}.py` | D3 | spec v2 executor, rules, fingerprint, redaction, strict prose check |
| L3 | `PM/intake_rules.yaml`, `PM/intake_rules.py` | C | the one `UNVERIFIED` rules file and its typed loader |
| L3 | `PM/intake_store.py` | C | `ChainedLog`; `IntakeStore` (the logs, the source cache, extract and coverage files, the audit helper) |
| L3 | `PM/ledger_models.py` | C | entities, facts, extracts, value states, `ChainHead` (pure models, no store) |
| L3 | `PM/intake_records.py` | C | file, run, mapping, coverage, check, requirement, review records (pure models) |
| L3 | `PM/ledger_view.py` | C | `LedgerReader`, `LedgerView` (the read-side fold over the store) |
| L3 | `PM/intake_fixtures.py` | C | `write_truth`: the synthetic truth written into a ledger, one convention for D0, D5, W and D6 tests |
| L3 | `PM/format_inventory.py` | D2 | the inventory CLI over a read root |
| L3 | `PM/mapping_cache.py` | D3 | mapping cache: versions, approval |
| L3 | `PM/{ledger,ledger_entities,ledger_compute,ledger_links}.py` | D4 | the ledger's writes, entity resolution, derived and cross-file facts |
| L3 | `PM/{coverage,study_routing,study_requirements,intake_checks,scorecard}.py` | D5 | G2, G4, G5 |
| L3 | `PM/{value_key,value_score,key_compare}.py` | D0 | value-level key, scorer, two-key comparison |
| L3 | `PM/profile_landing.py`; edits in `PM/{datasets,client_data,sheet_intake,inputs,plan}.py` | D1a | landing fixes |
| L3 | `PM/{intake_files,intake_pipeline}.py` | W | arrival record, stage runner, run queue |
| L3 | `PM/{intake_review,intake_landing,intake_health}.py`; edits in `PM/{datasets,client_data,sheet_intake,dataset_points}.py` | D6 | review state, spot check, confirmation, landing, health counters |
| L4 | `AG/{table_mapper,prose_extractor}.py`, `AG/evals/scripted.py` | D3 | the two LLM stages; one shared scripted model |
| L5 | `services/orchestrator/src/modeler_orchestrator/campaign_activities.py` (edit) | D1a | passes the error type |
| L5 | `services/engine-worker/r/run_pi.R` (edit, locked) | D1b | labels the error type |
| L6 | `API/intake_pipeline_jobs.py`; edits in `API/{config,jobs,agent_jobs,client_api,brief_api,intake_jobs}.py` | W | switch, arrival hook, `intake` job, LLM ports |
| L6 | `API/delivery_routes.py`, `API/views/delivery.py`; edits in `API/{client_api,admin_api}.py`, `API/views/{admin,client_data}.py` | D6 | routes and response models |
| L7 | `WEB/components/delivery/*`, `WEB/app/styles/delivery.css`, `WEB/app/admin/pipeline/page.tsx`, edits listed in §8.10 | D6 | Delivery section, pipeline health |
| docs | `docs/evaluations/value-key-runbook.md` | D0 | server runbook |
| other | `services/api/tests/conftest.py`, `deploy/server/modeler-secrets.env.example` (edits) | W | the suite's `legacy` default; the variable documented |

## 4. Data contracts

All models: `from __future__ import annotations`; `class B(BaseModel): model_config = ConfigDict(frozen=True,
extra="forbid")`. Notation: `class X(B): a: int; b: str = ""` lists the fields of `X` (an indented line under it
continues the list); a field without a default is required. Indices are 1-based (pages, rows, columns, tables,
paragraphs, words) unless stated. An id made by a store is `<prefix>-<seq>`, the sequence number of the line that
created it in its log (`f-41`, `ov-12`, `cf-3`, `run-7`, `dl-2`, `st-5`).

### 4.1 Anchors (`DI/anchors.py`)

An anchor is immutable for one `(file sha256, parser, parser version)`. It is stored as text.

```
anchor   = sha256 "@" parser "/" version "#" locator          ; sha256 [0-9a-f]{64}; parser [a-z0-9_]+; version [A-Za-z0-9.+_-]+
locator  = "s:" sheet "!" a1                                   ; sheet cell (a merged cell: its top-left); a1 [A-Z]{1,3}[1-9][0-9]*; n [1-9][0-9]*
         | "p:" page "/t:" n "/r:" n "/c:" n "@" box          ; PDF table cell
         | "p:" page "/w:" n "-" n "@" box                    ; PDF word span (first-last word of the page)
         | "d:t:" n "/r:" n "/c:" n                           ; Word table cell (a merged cell: its top-left)
         | "d:p:" n "/ch:" n "-" n                            ; Word paragraph, characters start-end (end exclusive, 0-based)
         | "x:l:" n "/ch:" n "-" n                            ; text file line, characters
         | "p:" page "/f:" n "@" box | "d:f:" n               ; figure
range    = "s:" sheet "!" a1 ":" a1 | "p:" page "/t:" n | "d:t:" n | "p:" page "/w:" n "-" n | "d:p:" n "-" n | "x:l:" n "-" n
sheet    = "'" text with every ' doubled "'"                  ; always quoted
box      = x0 "," top "," x1 "," bottom                       ; PDF points from the page's top-left, 2 decimals
```

```python
Box = tuple[float, float, float, float]
class SheetCell(B):  kind: Literal["sheet_cell"] = "sheet_cell"; sheet: str; cell: str
class PdfCell(B):    kind: Literal["pdf_cell"] = "pdf_cell"; page: int; table: int; row: int; column: int; box: Box
class PdfSpan(B):    kind: Literal["pdf_span"] = "pdf_span"; page: int; first_word: int; last_word: int; box: Box
class DocxCell(B):   kind: Literal["docx_cell"] = "docx_cell"; table: int; row: int; column: int
class DocxSpan(B):   kind: Literal["docx_span"] = "docx_span"; paragraph: int; start: int; end: int
class TextSpan(B):   kind: Literal["text_span"] = "text_span"; line: int; start: int; end: int
class FigureRef(B):  kind: Literal["figure"] = "figure"; page: int | None = None; index: int; box: Box | None = None
Locator = Annotated[SheetCell | PdfCell | PdfSpan | DocxCell | DocxSpan | TextSpan | FigureRef, Field(discriminator="kind")]
class Anchor(B):     file_sha256: str; parser: str; parser_version: str; locator: Locator
class AnchorError(ValueError): ...
def format_locator(locator: Locator) -> str
def parse_locator(text: str) -> Locator                      # AnchorError
def format_anchor(anchor: Anchor) -> str
def parse_anchor(text: str) -> Anchor                        # AnchorError, also for a part outside its character set
def anchor_text(file_sha256: str, parser: str, parser_version: str, locator: str) -> str
def same_place(a: Locator, b: Locator) -> bool               # equal identity (below); the box is never compared
ID_PATTERNS: Mapping[str, re.Pattern]   # sha256 ^[0-9a-f]{64}$; extract ^tx-[0-9a-f]{16}$; value ^tx-[0-9a-f]{16}#(0|[1-9][0-9]*)$;
                                        # region ^rg-[0-9a-f]{10}$; mapping ^mp-[0-9a-f]{12}$; file ^fl-[0-9a-f]{12}$;
                                        # a store's line id ^[a-z]{1,3}-[1-9][0-9]*$ (f-41, st-5, cf-3, run-7 ...)
def check_id(kind: str, text: str) -> str                    # the text, or AnchorError: an id from a request is checked before use
def canonical(value: Any) -> str        # json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False); a pydantic
                                        # model is dumped first with model_dump(mode="json", by_alias=True) (so `schema`, not `schema_id`)
def sha256_of(value: Any) -> str        # sha256 of canonical(value), hex
```

**Identity.** A sheet cell is its sheet and cell; a `PdfCell` is (page, table, row, column); a `PdfSpan` is (page,
first word, last word); a Word cell or span, a text span and a figure by their numbers. A PDF box is carried for the
viewer and for `check_anchors` (box overlap after a re-parse), and is not part of the identity: `resolve`,
`same_place` and every test compare identities, so two parsers' boxes for one cell need not agree to the hundredth.

Example: `9c1e...77@workbook/1.0+openpyxl3.1.5#s:'PK Summary'!C12`; `...@pdfplumber/1.0+pdfplumber0.11.4#p:12/t:1/r:4/c:3@212.40,318.02,251.10,329.50`.

`parser_version` is `<SOURCE_VERSION>+<library><library version>`: a change of D2's own reading or locating rules, or
a library upgrade, is a new version, which triggers a re-parse and the anchor-integrity check (§6.1).

### 4.2 Source model (`DI/source_model.py`)

```python
FileFormat = Literal["xlsx", "xlsm", "xls", "csv", "tsv", "docx", "pdf", "text", "markdown", "json", "zip", "image", "other"]
DocState = Literal["read", "partly_read", "unsupported", "unreadable"]
CellType = Literal["number", "text", "bool", "date", "empty"]
NUMERIC_TEXT: re.Pattern   # ^[<>≤≥]?\s*[-+]?(\d+([.,]\d+)*|[.,]\d+)([eE][-+]?\d+)?\s*%?$, matched after NFKC with U+2212 as "-"
def is_numeric_text(text: str) -> bool        # a BARE number: typing a cell and the header band's "#" (§6.2), nothing else
def has_number(text: str) -> bool             # any digit after NFKC: the one definition of "a cell with a number" for
                                              # locating regions, Region.numeric_cells, CellUse.numeric and silent loss
# "12.3 (4.5)", "12.3 ± 4.5", "0.95 (0.88-1.03)", "12.3*", "12.3 ng/mL", "1 234.5" are not bare numbers, but they hold
# numbers: a mapped table must account for them (as a value with cell_form, a label, a constant ...) or they are silent loss.

class ContainerRef(B): sha256: str; name: str; member: str                 # the ZIP a document came out of
class Finding(B):      code: str; location: str; message: str; severity: Literal["error", "warn", "info"] = "error"

class SheetCellValue(B):  # sparse: only non-empty cells
    row: int; column: int; value: float | int | str | bool | None; text: str; type: CellType
    number_format: str = ""; merged_from: str | None = None    # merged_from: the origin's A1; the value is copied, as grid.py does
    # text, exactly: a number cell -> the shortest round-trip form of the stored value (repr; an integer without ".0":
    # 12.4037, 12.4, 3), never the formatted display ("12.40" under 0.00) nor the % scaling; a date -> ISO 8601; a bool ->
    # "TRUE"/"FALSE"; a text cell -> its text as stored. A row's `verbatim` is this text; check_anchors compares it.
class Sheet(B):   name: str; index: int; max_row: int; max_column: int; hidden: bool = False; cells: tuple[SheetCellValue, ...]
class Word(B):    index: int; text: str; box: Box
class TableCell(B): row: int; column: int; text: str; box: Box | None = None; row_span: int = 1; col_span: int = 1
class PageTable(B): index: int; box: Box | None; n_rows: int; n_cols: int; cells: tuple[TableCell, ...]; engine: str
class Page(B):    number: int; width: float; height: float; rotation: int = 0; needs_ocr: bool = False; n_chars: int
                  words: tuple[Word, ...]; tables: tuple[PageTable, ...]; n_images: int = 0
class Paragraph(B): index: int; text: str; style: str = ""
class BodyItem(B):  kind: Literal["paragraph", "table"]; paragraph: Paragraph | None = None; table: PageTable | None = None
class Figure(B):    index: int; page: int | None = None; box: Box | None = None; name: str = ""; width: int = 0; height: int = 0
class RegionPart(B): page: int; table: int; n_rows: int; header_rows_repeated: int = 0     # one page's piece of a continued table
                     caption: str = ""                                                       # that part's own caption, as written

TableKind = fields.TableKind; DocumentRole = fields.DocumentRole
class Region(B):
    id: str     # sheet, Word, text: "rg-" + sha256(where + "|" + file sha256)[:10]; a PDF table: "rg-" + sha256("p:<first page>
                # /box:<its box rounded to whole points>/" + <its first row's text> + "|" + file sha256)[:10], so a parser
                # that finds one more table on a page does not renumber the others' regions
    kind: Literal["table", "prose", "figure", "table_like_text"]
    where: str                               # a `range` of §4.1 (a continued PDF table: its first part)
    parts: tuple[RegionPart, ...] = ()
    caption: str = ""; caption_locator: str | None = None
    table_kind: TableKind = "unknown"; kind_evidence: str = ""    # by rule: the locator and words that decided it
    n_rows: int = 0; n_cols: int = 0
    numeric_cells: int = 0                   # cells with has_number; a merged copy is not counted (its origin is, once)
    notes: tuple[str, ...] = ()              # e.g. "rows 9-11 joined across empty row 8"
class OutsideItem(B):                        # content in no region: a locator and at most 200 characters
    where: str; text: str; numeric: bool     # numeric: has_number(text)
    furniture: bool = False                  # page furniture: a page number, or a line repeated at the same place on most pages
    region: str | None = None                # a line of that region's context (RegionGrid.above / below), which a constant may cite

class SourceDocument(B):
    schema_id: Literal["source/1"] = Field(default="source/1", alias="schema")
    file_sha256: str; name: str; size_bytes: int; format: FileFormat
    parser: str; parser_version: str
    container: ContainerRef | None = None
    state: DocState; reason: str = ""                      # required for partly_read, unsupported, unreadable
    role: DocumentRole = "other"; role_evidence: str = ""
    encoding: str | None = None; delimiter: str | None = None
    sheets: tuple[Sheet, ...] = (); pages: tuple[Page, ...] = (); body: tuple[BodyItem, ...] = ()
    figures: tuple[Figure, ...] = (); regions: tuple[Region, ...] = (); outside: tuple[OutsideItem, ...] = ()
    members: tuple[str, ...] = ()                           # ZIP: member paths; each member is its own document
    warnings: tuple[str, ...] = ()

@dataclass(frozen=True)
class GridCell: text: str; value: float | int | str | bool | None; type: CellType; locator: str; number_format: str = ""
                merged_from: str | None = None    # a merged copy: may serve as a header or label, is never a value, is never
                                                  # counted (the origin is counted once, where it stands)
@dataclass(frozen=True)
class RegionGrid:
    """One table region as a grid in its own coordinates (row 1, column 1 = the region's top-left): what the mapping
    reads, the same for a sheet range, a PDF table (its parts joined, repeated headers dropped) and a Word table.
    Its context is what a constant may cite: the caption, up to 3 lines directly above it and up to 3 lines directly
    below the region, only lines that belong to no other region (a sheet line: that row's non-empty cells; a PDF or
    Word line: one cell, its span locator)."""
    file_sha256: str; parser: str; parser_version: str; region_id: str; n_rows: int; n_cols: int
    cells: Mapping[tuple[int, int], GridCell]
    caption: tuple[GridCell, ...] = (); above: tuple[tuple[GridCell, ...], ...] = (); below: tuple[tuple[GridCell, ...], ...] = ()
                                               # above[0] is the line directly above (the caption, when there is one, is apart)
    def cell(self, row: int, column: int) -> GridCell          # an empty GridCell when absent
    def anchor(self, row: int, column: int) -> str             # anchor text of that cell
    def context(self, near: Literal["caption", "above", "below"], line: int) -> tuple[GridCell, ...]   # () when absent
    def anchor_of(self, locator: str) -> str                   # anchor text of a locator of this grid or its context
    @classmethod
    def from_rows(cls, rows: Sequence[Sequence[str | float | int | None]], *, region_id: str = "rg-test",
                  first_cell: str = "A1", sheet: str = "T", caption: Sequence[str] = (),
                  above: Sequence[Sequence[str]] = (), below: Sequence[Sequence[str]] = ()) -> RegionGrid
                  # tests: a grid with sheet-cell locators; synthetic.truth_grid gives the true locators of every format

class PdfTableEngine(Protocol):       # a second table engine (Docling ...): none is passed today
    name: str; version: str
    def tables(self, data: bytes, page: int) -> Sequence[PageTable]: ...
class OcrEngine(Protocol):            # none is passed today; a scanned page is reported as needing OCR
    name: str; version: str
    def words(self, data: bytes, page: int) -> Sequence[Word]: ...

class Resolved(B):   text: str; locator: str; region_id: str | None; page: int | None = None; box: Box | None = None
class ViewCell(B):   row: int; column: int; text: str; numeric: bool; locator: str; highlighted: bool = False
                     role: str | None = None   # highlighted: "value", "time", "unit", "spread", "n", "lloq" or a label role
class SourceView(B):                   # what the review shows beside a value (D2 builds it, D6 serves it)
    kind: Literal["grid", "text"]; title: str; region_id: str | None
    n_rows: int = 0; n_cols: int = 0; cells: tuple[ViewCell, ...] = ()     # grid: the region's cells (and its context lines,
                                                                           # negative rows above, rows past n_rows below);
                                                                           # the value's cell and the cells of its time, unit,
                                                                           # labels, spread, n and LLOQ highlighted with their role
    text: str = ""; span: tuple[int, int] | None = None                    # text: the paragraph and the span in it
    page: int | None = None; page_size: tuple[float, float] | None = None; box: Box | None = None   # PDF: to draw the page
class AnchorProblem(B): id: str; anchor: str; problem: Literal["not_found", "text_differs"]; found: str = ""
```

### 4.3 Field vocabulary (`DI/fields.py`)

Names are the client-data template's column names (`client_template.SHEETS`) wherever one exists, so the ledger and
the no-AI path say the same thing. Nothing here is a PK-Sim name.

```python
Statistic = recipe.Statistic                       # individual | arithmetic_mean | geometric_mean | median
SpreadKind = Literal["SD", "SE", "CV%", "geoSD", "geoCV%"]      # a CI or a min-max pair is an interval (§4.4), not a spread
IntervalKind = Literal["CI", "range"]
UnitClass = Literal["mass", "concentration", "time", "percentage", "ratio", "other", "none"]
TableKind = Literal["pk_individual", "pk_summary", "pk_parameters", "dissolution", "study_design", "demographics",
                    "product_batch", "bioanalytical", "physchem_invitro", "excretion", "composition", "ddi_relation",
                    "not_data", "unknown"]
KIND_OF_CATEGORY: Mapping[str, TableKind]          # triage.SheetCategory value -> TableKind (OTHER -> unknown)
DocumentRole = Literal["client_template", "data_workbook", "concentration_listing", "study_report", "synopsis",
                       "bioanalytical_report", "dissolution_report", "certificate_of_analysis", "product_information", "other"]
class FieldDef(B):
    name: str; value: Literal["number", "integer", "choice", "name", "text"]
    level: Literal["study", "arm", "product", "batch", "analyte", "observation", "compound", "condition", "label"]
    unit_class: UnitClass = "none"; choices: tuple[str, ...] = (); cue: str = ""    # cue: regex of the label a sentence must carry
    choice_cues: dict[str, str] = Field(default_factory=dict)  # choice -> regex stating it, for the choices supports_choice lacks
FIELDS: Mapping[str, FieldDef]
def field(name: str) -> FieldDef | None            # also answers for "pk.<parameter>" and for a CPF id (level compound)
def unit_class(field: str) -> UnitClass            # the FIELD's declared class; never inferred from the unit text
MASS_UNITS: Mapping[str, float]                    # document_reading._MG_PER (mg, g, µg) imported, never retyped
def unit_table(unit_class: UnitClass) -> Mapping[str, str] | None
    # concentration: validate.CONCENTRATION_UNITS; time: validate.TIME_UNITS; percentage: validate.FRACTION_UNITS;
    # mass: MASS_UNITS's keys and "mg/kg" (the template's dose_unit choices), aliases folded by document_reading._dose_unit
    # (ug, mcg -> µg); ratio, other, none: None (no table exists: the unit is kept and not checked)
def known_unit(field: str, unit: str) -> str | None     # canonical spelling in the table of the field's class; None outside
                                                       # it, or when the class has no table (then UNIT_NOT_CHECKED, never a fail)
def units_in(field: str, text: str) -> tuple[str, ...]  # the units of the field's class a text writes (code's reading of a
    # cited header, title or clause): concentration through document_reading._CONC_UNIT, mass through _DOSE_UNIT,
    # time and percentage by token through their table; a class with no table: () (a typed unit must then be in the
    # cited text verbatim, case aside)
CONDITION_FIELDS: tuple[str, ...]   # medium, ph, apparatus, rpm, volume_ml, temperature_c, surfactant, interval_start_h,
                                    # interval_end_h, cumulative, component: what tells two runs or intervals apart
LABEL_FIELDS: tuple[str, ...]       # subject, period, sequence, occasion, vessel, matrix: written on EntityRef as labels
def read_choice(field: str, text: str) -> str | None
    # the one choice a text states: the whole text equal to a choice (name_key); else document_reading.supports_choice for
    # route, food_state, formulation, design and product_role (its cues), FieldDef.choice_cues for every other choice
    # field; None when none or several match. "other" only when the text holds the word "other".
LEGACY_FACT_NAMES: Mapping[str, str]               # weight_mean_kg -> weight_mean, percent_female -> female_percent (document_reading)
```

`fields` imports three private names of `document_reading` (`_MG_PER`, `_DOSE_UNIT`, `_CONC_UNIT`) and its
`_dose_unit` folding, read-only: the file stays unchanged and the dose units stay in one place.

| Level | Fields (value type, unit class in brackets when it has one; choices from the named constant) |
|---|---|
| study, arm | `study_id` name · `treatment` name (the arm) · `reference` text · `design` choice SD, MD · `crossover` choice yes, no · `population` choice healthy, patient · `special_population` choice (`split.SpecialPopulation`'s five) · `species` name · `n`, `n_evaluable` integer · `age_mean`, `age_min`, `age_max` number · `weight_mean_kg`, `height_mean_cm` number (other) · `percent_female` number (percentage) · `n_female` integer · `child_pugh` choice A, B, C · `egfr` number (other) · `gestational_week` number · `ethnicity`, `genotype`, `co_medication` text · `route` choice `client_template.ROUTES` + other · `dose` number (mass) · `dose_unit` choice mg, mg/kg · `salt_or_base` choice base, salt · `infusion_time_min`, `dosing_interval_h` number (time) · `n_doses` integer · `food_state` choice fasted, fed · `meal_type` text · `meal_kcal` number (other) · `meal_fat_g` number (mass) · `formulation` choice `FORMULATIONS` · `intended_use` choice `USES` · `lloq` number (concentration; per study, analyte and matrix) · `matrix` choice plasma, blood, serum, urine, feces (also a label) |
| label | `subject`, `period`, `sequence`, `occasion` (a day or visit of a multiple-dose study), `vessel` name · `matrix` (above) |
| analyte | `analyte` name · `analyte_role` choice parent, metabolite, enantiomer, sum · `molecular_weight` number (other) |
| product, batch | `product` name · `product_role` choice `ROLES` · `batch` name · `strength_mg` number (mass) · `dosage_form` text · `release` choice IR, DR, ER · `particle_size_d10_um`, `_d50_um`, `_d90_um` number (other) · `particle_size_method`, `polymorph`, `salt_form` text |
| condition | `apparatus`, `medium`, `surfactant` text · `rpm`, `volume_ml`, `temperature_c` number (other) · `ph` number · `interval_start_h`, `interval_end_h` number (time) · `cumulative` choice yes, no · `component` name |
| observation | `concentration` (concentration) · `percent_dissolved` (percentage) · `excretion.amount` (other: mass or molar, no table holds molar amounts) · `excretion.fraction` (percentage) · `pk.<p>` for p in `client_template.PK_PARAMETERS` (other) · `composition.amount` (mass) |
| relation | `relation.ddi_ratio.<p>`, `relation.test_vs_reference.<p>` (ratio; `Fact.relation`, `Fact.interval`) |
| link | `link.study_id`, `link.protocol`, `link.cross_reference` (name; the value is the other file's study label or protocol) |
| compound | the CPF id of the parameter registry, as the requirement templates' `target` writes it (`phys.logp`, `bind.fu`, ...), with `conditions` (other) |

`choice_cues` (C writes them; a reading check, not a reconciliation rule): `matrix` plasma, blood (whole blood),
serum, urine, feces/faeces; `salt_or_base` salt, free base or base; `population` healthy (volunteers), patient(s);
`special_population` pediatric/paediatric, hepatic, renal, pregnan(t|cy), elderly; `crossover` cross-over → yes,
parallel → no; `release` immediate → IR, delayed → DR, extended/prolonged → ER; `analyte_role` parent, metabolite,
enantiomer, sum/total; `cumulative` cumulative → yes, per interval → no; `child_pugh` "Child-Pugh A" ... . A
`client_template` choice column (`intended_use`, `dose_unit`, `role` ...) is read by whole-text equality.

### 4.4 Mapping spec v2 and extraction (`DI/mapping_spec.py`)

A new model beside `recipe.py`; the v1 recipe, `apply.py` and stored recipes are untouched and stay readable. Every
coordinate is **relative to the region**: a cell is (row, column) with row 1, column 1 its top-left; a line of its
context is (`near`, `line`). No `Cite` holds an absolute locator, so a cached spec reads each new region's own cells
and lines (a second sheet with the same layout takes its own title, never the first sheet's), does not depend on the
sheet name or on where the table sits, and one executor serves sheet, PDF and Word tables.

```python
Layout = Literal["long", "wide_series", "wide_times", "key_value"]
# long: one row per value; a record table (one row per study or product, one column per field: the template's Studies
# and Product sheets) is long with one value column per field. wide_series: times down a column, one value column per
# series. wide_times: times across the header (time_row), one row per series. key_value: a label column says what each
# row is (keys).
Role = Literal["time", "time_actual", "time_unit", "value", "spread", "spread_kind", "statistic", "n", "lloq", "blq_flag",
               "interval_low", "interval_high", "subject", "arm", "period", "sequence", "occasion", "study", "analyte",
               "matrix", "product", "batch", "vessel", "other_arm", "parameter", "condition", "unit", "ignore"]
# time: the nominal time; time_actual: the actual sampling time beside it; time_unit, unit, statistic, spread_kind,
# blq_flag: a column that states it row by row (the template's time_unit, unit, statistic, variability_kind, blq_flag)
CellForm = Literal["value", "value (spread)", "value ± spread", "value (low-high)", "value unit"]
class Cite(B):       # where a thing is stated, relative to the region; exactly one of (row and column) or near
    row: int | None = None; column: int | None = None                        # a cell of the region
    near: Literal["caption", "above", "below"] | None = None; line: int = Field(default=1, ge=1, le=3)   # a context line
class ColumnMap(B):
    column: int; role: Role
    field: str | None = None            # a value column's field; None: MappingSpec.field
    condition: str | None = None        # role condition, or series_role condition: a fields.CONDITION_FIELDS name
    unit: str | None = None; unit_cite: Cite | None = None      # per-column unit: must be a unit code finds at the cite
    statistic: Statistic | None = None
    spread_kind: SpreadKind | None = None; of: int | None = None  # spread, n, lloq, interval_*: the value column they qualify
    cell_form: CellForm = "value"       # a value cell that also writes its spread, interval or unit: code splits it
    lloq: Cite | None = None            # this column's own LLOQ (a metabolite's assay); wins over MappingSpec.lloq
    level: Cite | None = None           # interval columns and "value (low-high)": where the CI level is written (code reads it)
    series: Cite | None = None; series_role: Role | None = None   # wide_series: the header cell naming this column
    reason: str = ""                    # role ignore: why its cells are not data
class RowRule(B):    # rows told apart by the text of one of their cells (fullmatch, case-insensitive)
    column: int; pattern: str
    role: Literal["exclude", "arithmetic_mean", "geometric_mean", "median", "spread", "n", "interval_low", "interval_high"]
    spread_kind: SpreadKind | None = None; reason: str = ""     # reason required for exclude
class KeyMap(B):     pattern: str; field: str; statistic: Statistic | None = None; spread_kind: SpreadKind | None = None
class Constant(B):   # a fact stated once for the whole table: a title's study id and dose, a footnote's LLOQ
    field: str; cite: Cite
    pattern: str | None = None          # name and text fields: a regex with one group that must match the cited text exactly
                                        # once (its group is the value); None: the whole cited text. Never for a number
                                        # (read_constant) or a choice (fields.read_choice)
    text: str | None = None             # the model's reading of a name or choice: compared with code's at proposal
                                        # (CONSTANT_NOT_STATED), then dropped: MappingCache stores the spec with text None,
                                        # and the value is ALWAYS what code reads from the cited text on each use
class MappingSpec(B):
    schema_id: Literal["mapping/2"] = Field(default="mapping/2", alias="schema")
    kind: TableKind; layout: Layout
    header_rows: int = Field(ge=0); first_data_row: int = Field(ge=1); last_data_row: int | None = None   # None: the region's end
    columns: tuple[ColumnMap, ...] = ()
    time_row: int | None = None                                  # wide_times
    keys: tuple[KeyMap, ...] = ()                                # key_value
    field: str | None = None                                     # default field of the value columns
    time_unit: str | None = None; time_unit_cite: Cite | None = None
    value_unit: str | None = None; value_unit_cite: Cite | None = None
    time_reference: Literal["first_dose", "last_dose", "occasion_dose"] | None = None; time_reference_cite: Cite | None = None
    statistic: Statistic | None = None                           # None: not stated; code sets "individual" only for a table
                                                                 # with a subject column, never by default
    lloq: Cite | None = None                                     # one LLOQ for the table: code reads number and unit
    below_lloq_tokens: tuple[str, ...] = (); missing_tokens: tuple[str, ...] = ()
                                                                 # the decimal convention is code's, per region (§6.2)
    row_rules: tuple[RowRule, ...] = (); constants: tuple[Constant, ...] = ()
    not_data_reason: str = ""                                    # required when kind == "not_data"
    questions: tuple[str, ...] = ()

class ExtractedRow(B):      # one value, long form, with the locator of every cell it was read from
    field: str
    labels: dict[str, str]              # role -> the label as written: study, arm, period, sequence, occasion, subject,
                                        # analyte, matrix, product, batch, vessel, other_arm
    label_locators: dict[str, str] = Field(default_factory=dict)          # role -> the cell (or context line) that wrote it
    conditions: dict[str, str] = Field(default_factory=dict)              # CONDITION_FIELDS name -> as written (2 media,
    condition_locators: dict[str, str] = Field(default_factory=dict)      # 2 intervals, 2 pH: never a conflict)
    time: float | None = None; time_unit: str | None = None; time_locator: str | None = None          # nominal time
    time_actual: float | None = None; time_actual_locator: str | None = None
    value: float | None = None; text_value: str | None = None; verbatim: str; locator: str
    unit: str | None = None; unit_locator: str | None = None
    censored: bool = False; lloq: float | None = None; lloq_unit: str | None = None; lloq_locator: str | None = None
    uloq: float | None = None           # above the range (">1000"): value None, the limit kept
    statistic: Statistic | None = None
    spread: float | None = None; spread_kind: SpreadKind | None = None; spread_verbatim: str | None = None
    spread_locator: str | None = None
    interval: tuple[float, float] | None = None; interval_kind: IntervalKind | None = None; interval_level: float | None = None
    interval_locators: tuple[str, str] | None = None
    n: int | None = None; n_locator: str | None = None
class ExtractedConstant(B): field: str; value: float | str; unit: str | None = None; verbatim: str; locator: str
    # a constant of a condition field goes into every row's conditions, of a label field (matrix ...) into every row's
    # labels, with its locator; only the others are listed here (D4 writes them as scalar facts)
class CellUse(B):
    row: int; column: int
    locator: str; numeric: bool         # numeric: has_number(text); a merged copy is never numeric (its origin counts once)
    use: Literal["value", "time", "spread", "n", "lloq", "interval", "label", "condition", "header", "constant", "unit",
                 "missing", "excluded", "unaccounted"]
    rule: str = ""                      # which rule or token put it there ("missing_token:NS", "row_rule:cv ?%", "column:ignore")
class ExtractResult(B):
    rows: tuple[ExtractedRow, ...]; constants: tuple[ExtractedConstant, ...]
    cell_use: tuple[CellUse, ...]       # one entry for EVERY non-empty cell of the region (in memory; stored compactly, §4.6)
    cited: tuple[str, ...] = ()         # the context lines' locators the constants read (they leave the outside count)
    decimal: Literal["point", "comma"] = "point"     # the region's convention, decided by code
    findings: tuple[Finding, ...]
class MappingError(ValueError): ...

class ColumnProfile(B): column: int; numbers: int; texts: int; empty: int; distinct_texts: tuple[str, ...]   # at most 12, redacted
class ContextLine(B): near: Literal["caption", "above", "below"]; line: int; text: str    # verbatim, at most 200 characters
class RedactedTable(B):     # everything the table mapper is shown of one table
    region_id: str; file_name: str; document_role: DocumentRole; kind_by_rule: TableKind
    n_rows: int; n_cols: int
    context: tuple[ContextLine, ...]    # the caption and the lines above and below (RegionGrid's): the model cites a
                                        # constant by its (near, line), code reads it
    header_rows: int; header: tuple[tuple[str, ...], ...]                   # the header band (§6.2), bare numbers redacted
    body_rows: tuple[int, ...]; body: tuple[tuple[str, ...], ...]           # the first 5 and last 3 body rows, redacted
    profile: tuple[ColumnProfile, ...]                                      # over all body rows
class ProseParagraph(B): index: int; text: str; locator: str               # a `range` of §4.1; never a table's text
                         heading: str = ""; heading_locator: str | None = None   # the heading above it, where a label may stand
class ProseFact(B):
    field: str; value: float | str      # the value CODE parsed from the clause (§6.2), never the model's
    unit: str | None = None             # parsed by code from the clause
    quote: str
    study_label: str | None = None; arm_label: str | None = None
    locator: str                        # the span of the value itself inside the paragraph
    study_locator: str | None = None; arm_locator: str | None = None        # the spans where the labels are written
```

**Redaction, exactly** (`mapping.redact.redact_cell`): each maximal run of digits (`\d+`, after NFKC) becomes `#`,
separators kept; the result is cut at 40 characters. So `12.5` → `#.#`, `12,5` → `#,#`, `1.234,5` → `#.#,#`, `<0.5` →
`<#.#`, `S01` → `S#`, `2 h` → `# h`, `BLQ` → `BLQ`. It applies to every body cell, every `distinct_texts` entry, every
cell of the header band that is a bare number (`is_numeric_text`: times across the top are read by code through
`time_row`), and every finding message returned to the model (`REJECTED: ...`). Invariant, tested on what
`header_band` actually chooses: **no digit of a body cell is in the payload.** Header words and the context lines are
verbatim ("50 mg" in a title is read by code through a `Cite`, never copied by the model); a context line holds only
text that belongs to no table region.

Example (subjects down, times across, summary rows under them, a title line above the region), as the cache stores it:

```json
{"schema": "mapping/2", "kind": "pk_individual", "layout": "wide_times", "header_rows": 2, "first_data_row": 3,
 "time_row": 2, "field": "concentration", "time_unit": "h", "time_unit_cite": {"row": 1, "column": 2},
 "value_unit": "ng/mL", "value_unit_cite": {"row": 1, "column": 2}, "statistic": "individual",
 "below_lloq_tokens": ["BLQ"], "missing_tokens": ["NS"],
 "columns": [{"column": 1, "role": "subject"}, {"column": 2, "role": "value"}, {"column": 3, "role": "value"}],
 "row_rules": [{"column": 1, "pattern": "mean", "role": "arithmetic_mean"},
               {"column": 1, "pattern": "sd", "role": "spread", "spread_kind": "SD"}, {"column": 1, "pattern": "n", "role": "n"},
               {"column": 1, "pattern": "cv ?%", "role": "exclude", "reason": "CV% restates the SD and the mean"}],
 "lloq": {"near": "below", "line": 1},
 "constants": [{"field": "study_id", "cite": {"near": "above", "line": 1}, "pattern": "Study (\\S+),"},
               {"field": "dose", "cite": {"near": "above", "line": 1}},
               {"field": "food_state", "cite": {"near": "above", "line": 1}}]}
```

### 4.5 The ledger (`PM/ledger_models.py` pure models; `PM/ledger_view.py` the read side)

```python
# PM/ledger_models.py: models only; it imports no store (intake_store imports it, ledger_view imports both)
EntityType = Literal["study", "arm", "product", "batch", "analyte"]
class Entity(B):  id: str; type: EntityType; label: str; key: str; parent: str | None = None; source: str | None = None; by: str; at: str
                  # id: st-n, arm-n, pr-n, ba-n, an-n. key: name_key(label). parent: an arm's study, a batch's product.
                  # source: the anchor that first named it (None: a person); its file is the entity's home file
class Alias(B):   type: EntityType; key: str; parent: str | None = None; entity: str; source: str; by: str; at: str
                  # source: "exact" | "review:<aliases list>" (today's person-confirmed alias) | "link:<fact id>" | "person"
class Merge(B):   type: EntityType; from_id: str; into_id: str; link_fact: str | None = None; why: str; by: str; at: str
class EntityRef(B):
    study: str | None = None; arm: str | None = None; product: str | None = None; batch: str | None = None
    analyte: str | None = None                                              # entity ids
    subject: str | None = None; period: str | None = None; sequence: str | None = None; occasion: str | None = None
    vessel: str | None = None; matrix: str | None = None                    # labels as written (matrix read with
                                                                            # fields.read_choice where a choice is needed)
    # Any part may be None: partial facts are welcome. A value with no matrix label takes its study's single active
    # matrix fact; none: MATRIX_MISSING
Method = Literal["cell", "pdf_table", "docx_table", "prose", "digitized", "derived", "person"]
class MappingUse(B): mapping_id: str; version: int
class ModelUse(B):   provider: str; model: str; prompt_sha256: str; agent_run: str
class Relation(B):   kind: Literal["ddi_ratio", "test_vs_reference"]; other: EntityRef; parameter: str
class CrossFile(B):  stating_fact: str; link_fact: str; receiving_study: str
                     # computed by the fold, never stored (§6.3). G3's three anchors: the stating value's, the link's (a
                     # link fact, or the review record of a person's assignment or merge), the receiving study entity's source
class Fact(B):              # a scalar value: a constant, a prose fact, a text-valued row, a relation row, a derived or a person's value
    id: str                                   # "f-<seq of its line>"
    delivery: str; run_id: str | None = None
    entity: EntityRef; field: str
    value: float | int | str | bool | None; unit: str | None = None   # the unit as written, never renamed
    verbatim: str = ""                        # the source text as written ("" for derived)
    conditions: dict[str, str] = Field(default_factory=dict)
    time: float | None = None; time_unit: str | None = None; time_actual: float | None = None
    statistic: Statistic | None = None; spread: float | None = None; spread_kind: SpreadKind | None = None; n: int | None = None
    interval: tuple[float, float] | None = None; interval_kind: IntervalKind | None = None; interval_level: float | None = None
    censored: bool = False; lloq: float | None = None; lloq_unit: str | None = None; uloq: float | None = None
    relation: Relation | None = None
    anchor: str | None = None                 # anchor text; None only for derived and person facts
    locators: dict[str, str] = Field(default_factory=dict)   # role -> anchor text of its time, unit, label, spread, n, LLOQ cells
    method: Method
    mapping: MappingUse | None = None; model: ModelUse | None = None
    derived_from: tuple[str, ...] = (); compute: str | None = None   # e.g. "spread-1/sd_from_se", "compute-1/dose_to_mg"
    supersedes: str | None = None             # a fact id or a value id "<extract id>#<i>"
    reason: str = ""
    by: str; at: str                          # "code", "agent:<run id>" or a user id

class TableExtract(B):      # the numeric values of one table under one mapping, column-wise; one file per extract
    schema_id: Literal["extract/1"] = Field(default="extract/1", alias="schema")
    file_sha256: str; parser: str; parser_version: str; region_id: str      # NO delivery and no run: identity is content
    mapping: MappingUse; kind: TableKind; decimal: Literal["point", "comma"]
    entities: tuple[EntityRef, ...]; entity_locators: tuple[dict[str, str], ...]    # small dictionaries; entity_locators:
    fields: tuple[str, ...]; units: tuple[str, ...]                                 # role -> the cell that named it here
    conditions: tuple[dict[str, str], ...]; condition_locators: tuple[dict[str, str], ...]
    n: int                                    # values; every column below has length n (None where a value has none)
    entity_ix: tuple[int, ...]; field_ix: tuple[int, ...]; unit_ix: tuple[int | None, ...]; condition_ix: tuple[int | None, ...]
    time: tuple[float | None, ...]; time_unit: tuple[str | None, ...]; time_actual: tuple[float | None, ...]
    value: tuple[float | None, ...]; verbatim: tuple[str, ...]
    censored: tuple[bool, ...]; lloq: tuple[float | None, ...]; lloq_unit: tuple[str | None, ...]; uloq: tuple[float | None, ...]
    statistic: tuple[str | None, ...]
    spread: tuple[float | None, ...]; spread_kind: tuple[str | None, ...]; n_at: tuple[int | None, ...]
    interval_low: tuple[float | None, ...]; interval_high: tuple[float | None, ...]
    interval_kind: tuple[str | None, ...]; interval_level: tuple[float | None, ...]
    locator: tuple[str, ...]                  # the value cell of each value: its own anchor
    time_locator: tuple[str | None, ...]; time_actual_locator: tuple[str | None, ...]; unit_locator: tuple[str | None, ...]
    spread_locator: tuple[str | None, ...]; n_locator: tuple[str | None, ...]; lloq_locator: tuple[str | None, ...]
    interval_locator: tuple[tuple[str, str] | None, ...]
    # Text-valued rows (route, apparatus, sex) and relation rows are written as Facts, never into an extract
class ExtractRef(B):        # the extract's line in the ledger
    id: str                                   # "tx-" + content_sha256[:16]
    content_sha256: str; file_sha256: str; region_id: str; mapping: MappingUse; kind: TableKind; n: int
    studies: tuple[str, ...]; products: tuple[str, ...]
    delivery: str; run_id: str | None; supersedes: tuple[str, ...] = (); by: str; at: str
class StatusChange(B): target: str; status: Literal["excluded", "proposed"]; reason: str; by: str; at: str
                  # target: a fact id, an extract id, or a value id "<extract id>#<index, 0-based>"

Status = Literal["proposed", "confirmed", "superseded", "excluded"]
EvidenceLevel = Literal["digitized", "prose", "new_mapping", "approved_mapping", "person_confirmed"]   # ascending
class ValueState(B):        # one value as every reader sees it, whether a fact or the i-th value of an extract
    id: str; entity: EntityRef; field: str; value: float | int | str | bool | None; unit: str | None; verbatim: str
    file_sha256: str | None = None            # the file it was read from (None: derived, person)
    time: float | None = None; time_unit: str | None = None; time_actual: float | None = None; statistic: str | None = None
    spread: float | None = None; spread_kind: str | None = None; n_at: int | None = None
    interval: tuple[float, float] | None = None; interval_kind: str | None = None; interval_level: float | None = None
    censored: bool = False; lloq: float | None = None; lloq_unit: str | None = None; uloq: float | None = None
    conditions: dict[str, str] = Field(default_factory=dict); relation: Relation | None = None
    anchor: str | None; locators: dict[str, str] = Field(default_factory=dict)   # role -> anchor text (time, unit, labels ...)
    method: Method; mapping: MappingUse | None = None
    derived_from: tuple[str, ...] = (); compute: str | None = None; cross_file: CrossFile | None = None
    status: Status; status_reason: str = ""; superseded_by: str | None = None; confirmation: str | None = None
    level: EvidenceLevel; table_kind: TableKind | None = None; delivery: str
class Conflict(B):    id: str; entity: EntityRef; field: str; time: float | None; values: tuple[str, ...]; kind: Literal["value", "unit"]
                      # id: "cx-" + sha256(key)[:10]; values: the value ids that disagree; all are kept
class PendingLink(B): id: str; link_fact: str | None; study: str | None; file_sha256: str; values: int
                      candidates: tuple[str, ...]; state: Literal["unconfirmed", "ambiguous", "refused"]
                      # ambiguous: two or more studies match, nothing was joined; unconfirmed: joined, waits for a reviewer
class ChainHead(B):   seq: int; hash: str

# PM/ledger_view.py
class LedgerReader(Protocol):
    def head(self) -> ChainHead: ...                              # the facts log's head
    def heads(self) -> dict[str, str]: ...                        # facts, entities, mappings, review: each log's head hash
    def entities(self, type: EntityType | None = None) -> list[Entity]: ...
    def entity(self, entity_id: str) -> Entity | None: ...        # follows merges
    def values(self, *, study: str | None = None, product: str | None = None, field: str | None = None,
               file_sha256: str | None = None, unassigned: bool = False, active: bool = True) -> list[ValueState]: ...
    def value(self, value_id: str) -> ValueState | None: ...
    def conflicts(self, *, study: str | None = None, product: str | None = None) -> list[Conflict]: ...
    def pending_links(self, *, study: str | None = None) -> list[PendingLink]: ...
    def digest(self, *, study: str | None = None, product: str | None = None) -> str: ...
        # sha256 over the sorted (id, value, unit, anchor) of the subject's active values: no status, so recording the
        # confirmation does not make its own draw stale; an exclusion or a supersession changes the set of ids
class LedgerView:           # the read side, in the contract: a SNAPSHOT that folds the logs once, lazily, on first use
    def __init__(self, ws: Workspace): ...
    # implements head, heads, entities, entity, values, value, digest. It reads the ledger's two logs and the extracts
    # they name, the `decision` lines of mappings.jsonl (which mapping versions are approved) and the `confirmation`,
    # `link` and `assignment` lines of review.jsonl. One instance per request: a route and every D5 function it calls
    # share it. conflicts() and pending_links() raise NotImplementedError here: D4's Ledger implements them.
```

Rules the fold applies (and D4's writes keep): status is never stored on a fact. `superseded`: a later active fact
or extract names it in `supersedes` (a superseded extract supersedes all its values). `excluded`: its last
`StatusChange` says so, or its cross-file link was refused (reason: the refusal). `confirmed`: a signed confirmation
binds it. Otherwise `proposed`. An `Assignment` (§4.6) gives its targets their study and arm. `cross_file` is set for
every value whose file differs from its study's home file (§6.3). Evidence level, computed: `person` or confirmed →
`person_confirmed`; `cell`, `pdf_table`, `docx_table` → `approved_mapping` when its mapping version is approved, else
`new_mapping`; `prose` → `prose`; `digitized` → `digitized`; `derived` → the lowest level of its inputs. No model
confidence exists anywhere. A **spread fact** (value None, spread set: a derived SD) qualifies the value it derives
from: it is never a value of its own (no conflict, no landing value, not scored by D0).

```json
{"id": "f-41", "delivery": "dl-3", "run_id": "run-7", "entity": {"study": "st-2", "arm": "arm-3"}, "field": "dose",
 "value": 50.0, "unit": "mg", "verbatim": "Study 230-23, 50 mg, fasted", "method": "cell",
 "anchor": "9c1e...77@workbook/1.0+openpyxl3.1.5#s:'Fasting'!A1", "mapping": {"mapping_id": "mp-5b0c2a9e41d7", "version": 1},
 "by": "code", "at": "2026-11-12T10:03:22Z"}
```

### 4.6 Operational records (`PM/intake_records.py`)

```python
class FileRecord(B):
    file_id: str                         # "fl-" + sha256[:12]
    sha256: str; name: str; size_bytes: int; delivery: str            # delivery: "dl-<seq>", one per arrival request
    container: ContainerRef | None = None; repeat: bool = False       # repeat: the same bytes arrived before
    legacy_sid: str | None = None; legacy_refusal: str | None = None  # what today's ingest did with it: None on the
                                         # `file` line, filled from the file's later `legacy` line by intake_files.files()
    by: str; at: str
StageName = Literal["parse", "map", "map_llm", "execute", "prose", "ledger", "compute", "checks", "coverage"]
class StageTiming(B): stage: StageName; seconds: float; ok: bool; detail: str = ""
class RunCounters(B):
    regions: int = 0; tables: int = 0; mapped_by_cache: int = 0; mapped_by_rule: int = 0; mapped_by_llm: int = 0
    unmapped: int = 0; values: int = 0; facts: int = 0; outside_items: int = 0; needs_ocr_pages: int = 0
    anchors_checked: int = 0; anchors_unresolved: int = 0; llm_runs: int = 0
class CoverageSummary(B):
    state: DocState; reason: str = ""
    regions: int; regions_mapped: int; regions_excluded: int; regions_unread: int
    numeric_cells: int; cells_used: int; cells_excluded: int; cells_silent: int      # cells with a number, of mapped tables
    silent_loss: int                     # cells_silent + the numeric cells of unread table and table_like_text regions
    outside_items: int
    outside_numeric: int = 0             # outside items with a number, not furniture, not cited by a constant, not accepted
    values_unassigned: int = 0           # active values of this file with no study, not assigned or excluded
    needs_ocr_pages: tuple[int, ...] = (); anchors_unresolved: int = 0
class RunRecord(B):                      # one line per state change of a run; the latest line of a run_id is its state
    run_id: str; file_id: str; sha256: str; delivery: str
    state: Literal["queued", "running", "done", "failed"]; attempt: int = 0
    queued_at: str; started_at: str | None = None; finished_at: str | None = None; by: str
    parser: str | None = None; parser_version: str | None = None; source_sha256: str | None = None
    stages: tuple[StageTiming, ...] = (); counters: RunCounters = RunCounters()
    coverage: CoverageSummary | None = None; ledger_head: str | None = None
    agent_runs: tuple[str, ...] = (); error: str = ""

class MappingEntry(B):
    mapping_id: str                      # "mp-" + fingerprint[:12]
    version: int; fingerprint: str; spec: MappingSpec
    origin: Literal["rule", "llm", "person"]; origin_detail: str    # rule name and version | provider/model + prompt sha256 + agent run | user id
    first_seen: tuple[str, str]          # (file sha256, region id)
    by: str; at: str
class MappingDecision(B): mapping_id: str; version: int; status: Literal["approved", "rejected"]; why: str = ""; by: str; at: str

class RegionOutcome(B):     # stored compactly (the full cell_use stays in memory): what D5 counts, with no grid
    region_id: str; state: Literal["mapped", "excluded", "unread"]; reason: str = ""
    mapping: MappingUse | None = None; origin: Literal["cache", "rule", "llm", "person"] | None = None
    numeric_cells: int = 0                           # cells with a number in the region (merged copies not counted)
    uses: dict[str, int] = Field(default_factory=dict)        # CellUse.use -> cells with a number put to that use
    unaccounted: tuple[str, ...] = (); unaccounted_count: int = 0   # locators (at most 200) and the true count
    cited: tuple[str, ...] = ()                      # context-line locators its constants read
    decimal: Literal["point", "comma"] | None = None
class RegionCoverage(B): region: Region; outcome: RegionOutcome; numeric_cells: int; used: int; excluded: int
                         silent: tuple[str, ...]; silent_count: int  # locators of unaccounted numeric cells (at most 200), count
class FileCoverage(B):   file: FileRecord; summary: CoverageSummary; regions: tuple[RegionCoverage, ...]
                         outside: tuple[OutsideItem, ...]; anchor_problems: tuple[AnchorProblem, ...]
                         decisions: tuple[str, ...] = (); computed_at: str     # the RegionDecision ids applied
    # coverage/<sha>.json is the CURRENT truth (recomputed by exclude_regions and assign); a run line's summary is a
    # snapshot "at run end"

class CheckResult(B):
    id: str                              # "ck-" + sha256(code + subject + sorted(values) + detail key)[:12]: stable while nothing changes
    code: str; severity: Literal["fail", "warn", "info"]
    subject_type: Literal["study", "product", "compound", "file"]; subject: str
    message: str; values: tuple[str, ...] = (); rule: str = ""      # rule: the key of intake_rules.yaml it applied
class SchemaGap(B):       study: str; tag: str; value: str; reason: str
class RequirementStatus(B):
    req_id: str; template: str; label: str; scope: Literal["study", "product", "project"]; subject: str | None
    criticality: str; applies: Literal["yes", "no", "undetermined"]
    status: Literal["found", "conflicting", "missing", "ask_client", "literature", "not_needed", "not_applicable"]
    values: tuple[str, ...] = (); disposition: str | None = None
class Routing(B):         study: str; tags: dict[str, str]; templates: tuple[str, ...]; gaps: tuple[SchemaGap, ...]
class StudyRequirements(B): routing: Routing; items: tuple[RequirementStatus, ...]
class Blocker(B):         code: Literal["SILENT_LOSS", "OUTSIDE_NUMBERS", "UNASSIGNED_VALUES", "SCHEMA_GAP", "CHECK_FAILED",
                                        "LINK_UNCONFIRMED", "SPOT_CHECK", "LOADED_ON_CLIENT_REVIEW", "BLINDED"]
                          detail: str; ids: tuple[str, ...] = ()
class Scorecard(B):
    subject_type: Literal["study", "product", "compound"]; subject: str; label: str
    coverage: tuple[CoverageSummary, ...]; silent_loss: int
    requirements: tuple[RequirementStatus, ...]; gaps: tuple[SchemaGap, ...]
    checks: tuple[CheckResult, ...]; overridden: tuple[str, ...]    # check ids cleared by an override or a disposition
    conflicts: tuple[Conflict, ...]; links: tuple[PendingLink, ...]
    values: int; by_level: dict[str, int]; by_method: dict[str, int]
    blockers: tuple[Blocker, ...]        # D5: all but SPOT_CHECK, LOADED_ON_CLIENT_REVIEW and BLINDED, which D6 adds

# review.jsonl: who, when, why on every line. No signature of their own: the confirmation binds them.
# (RequirementDisposition, not Disposition: the plan routes already publish a schema named Disposition, §8.10.)
class Override(B):         id: str; subject: str; check_id: str; why: str = Field(min_length=1); by: str; at: str          # ov-n
class RequirementDisposition(B): id: str; subject: str; req_id: str; disposition: Literal["ask_client", "literature", "not_needed"]
                           why: str = Field(min_length=1); by: str; at: str                     # dp-n; review.jsonl kind `disposition`
class Choice(B):           id: str; conflict_id: str; keep: str; why: str = Field(min_length=1); by: str; at: str         # ch-n
class LinkConfirmation(B): id: str; link_fact: str | None; study: str; file_sha256: str; confirmed: bool               # lk-n
                           why: str = ""; by: str; at: str     # per (study, file); an ambiguous link: `study` is the one chosen
class Assignment(B):       id: str; targets: tuple[str, ...]; study: str; arm: str | None = None                       # as-n
                           why: str = Field(min_length=1); by: str; at: str    # values with no study (fact, extract or value ids)
class RegionDecision(B):   id: str; file_sha256: str; parser_version: str; regions: tuple[str, ...]
                           scope: Literal["regions", "unread_prose", "figures", "outside"] = "regions"
                           # outside: `regions` lists the outside items' locators accepted as not data
                           why: str = Field(min_length=1); by: str; at: str                                               # rd-n
class SpotCheckDraw(B):
    id: str; subject_type: str; subject: str; seed: str; subject_digest: str; rules_version: str                           # sd-n
    heads: dict[str, str]                       # facts, entities, mappings, review: each log's head hash, and the rules file's sha256
    always: tuple[str, ...]; sampled: tuple[str, ...]; strata: dict[str, str]   # value id -> stratum (or "always:<reason>")
    carried: dict[str, str] = Field(default_factory=dict)                       # value id -> the earlier spot check that ticked it
    by: str; at: str
class SpotTick(B):         value_id: str; ok: bool; note: str = ""     # one tick covers value, unit, time, labels and statistic
class SpotCheckRecord(B):  id: str; draw_id: str; ticks: tuple[SpotTick, ...]; by: str; at: str                           # sc-n
class Confirmation(B):
    id: str; subject_type: Literal["study", "product", "compound"]; subject: str                                          # cf-n
    record_sha256: str; record: dict[str, Any]         # the canonical record the hash and the signature bind (§6.6)
    signature_id: str; manifestation: str; by: str; printed_name: str; at: str; supersedes: str | None = None
class Landed(B):           confirmation: str; datasets: tuple[str, ...]; evidence: tuple[str, ...]; dissolution_records: int
                           rejected_legacy: tuple[str, ...]
                           pending: tuple[str, ...]; at: str   # "<what>: <reason>" for each thing not landed or landed PROPOSED
```

### 4.7 The rules file (`PM/intake_rules.yaml`, loader `PM/intake_rules.py`)

One file for every threshold or list that judges data (precedent: `m15_draft.yaml`, `client_reconciliation.yaml`).
C writes it exactly as below; a builder who needs another value asks the integrator. `intake_rules.rules() ->
IntakeRules` (frozen pydantic, `lru_cache`), `RULES_VERSION = rules().version`, `RULES_SHA256` (sha256 of the file's
bytes), `RULES_STATUS = rules().status`. The loader refuses a `geometric_sd_sent_as` outside `spread.ERROR_TYPES` (§4.8)
and an `item_fields` key absent from `item_scope`. C's test pins the file's sha256 to its version (a literal
`{"0.1": "<sha256>"}`), so an edit without a version bump fails the suite; every confirmation binds version, status and
sha256 (§6.6). The file is not under a locked pattern; locking it is requested of the owner (§11.24).

```yaml
# Every threshold and list the client-data intake judges data with (plan 2026-11-12, contracts §4.7).
# PROVISIONAL: UNVERIFIED until the SME signs. Read by modeler_project.intake_rules; a change here is a science
# change (CHANGELOG entry, version bump, the owner's approval).
version: "0.1"
status: UNVERIFIED
landing:
  blq_rule: omit                  # the only rule: points below the LLOQ are left out of the fit and of NCA, the LLOQ kept
  blq_rules: [omit]               # no other rule is offered until the SME chooses
  parent_words: ["", parent]      # with the drug's name and its synonyms in the brief
  matrix_as_plasma_with_warning: [blood, serum]
  sd_from: {arithmetic_mean: [SE, "CV%"]}     # nothing is converted for a geometric mean
  # Which (statistic, spread kind as the ledger has it) lands as which Series.error_kind; any other pair lands no error,
  # stays in the ledger, is named in the dataset's note and raises GEOMETRIC_SPREAD_VERBATIM or SPREAD_NOT_CONVERTED
  spreads_landed:
    arithmetic_mean: {SD: SD, SE: SE, "CV%": "CV%"}
    geometric_mean: {geoSD: SD}   # a source that SAYS geometric SD; a plain "SD" beside a geometric mean is ambiguous (§11.5)
  geometric_sd_sent_as: GeometricStdDev       # the error type such a series is sent with (spread.ERROR_TYPES, §8.2)
coverage:
  excluded_by_rule:
    figure: "figures are listed; a person digitizes one on request (the owner, 2026-11-10)"
ledger:
  time_resolution_min: 1          # two times this close (after conversion to minutes) are one time: conflicts, DUPLICATE_TIME
routing:
  core: req-core-small-molecule
  by_tag:
    - {tag: special_population, present: true, template: req-app-special-populations}
    - {tag: species, not_in: [Human], template: req-app-fih}
    - {tag: co_medication, present: true, template: req-app-ddi}
    - {tag: food_state, in: [fed], template: req-app-food-effect}
  gaps:
    - {tag: modality, in: [large_molecule, other], reason: "no requirement template for this modality"}
    - {tag: route, in: [other], reason: "no requirement template for this route"}
    - {tag: genotype, present: true, reason: "no requirement template for a genotype study (APP-05)"}
  item_scope:
    study: [REQ-sys.demographics, REQ-obs.bioanalytical, REQ-fe.meal]
    product: [REQ-form.release, REQ-vbe.rld_dissolution]
  # found: `all` fields (and one of `any`) have active values; `per`: repeated for every such entity part of the
  # subject's concentration values; `conditions`: every such value carries them. Proposals for the SME.
  item_fields:
    REQ-sys.demographics: {all: [population], any: [age_mean, age_min, weight_mean_kg, percent_female]}
    REQ-obs.bioanalytical: {all: [lloq], per: [analyte, matrix]}
    REQ-fe.meal: {any: [meal_type, meal_kcal]}
    REQ-form.release: {all: [percent_dissolved], conditions: [apparatus, medium]}
    REQ-vbe.rld_dissolution: {all: [percent_dissolved], conditions: [apparatus, medium, ph]}
  population_covariates:          # a proposal for the SME: a study so tagged needs one of these (POPULATION_COVARIATE_MISSING)
    pediatric: [age_mean, age_min]
    hepatic_impairment: [child_pugh]
    renal_impairment: [egfr]
    pregnancy: [gestational_week]
    elderly: [age_mean, age_min]
checks:
  composition_sum_tolerance_percent: 0.5    # the owner's design named 0.5 %; SME-governed (plan §6.4)
  mw_relative_tolerance: 0.01     # a proposal: a written MW's rounding stays inside it, a salt form's MW does not (MW_INCONSISTENT)
  dose_multiple_relative_tolerance: 0.01    # a proposal: dose / strength within this of a whole number (DOSE_NOT_MULTIPLE_OF_STRENGTH)
  severity:                       # every code of intake_checks.CHECKS; fail needs an override, a disposition or a fix
    fail: [ONE_LLOQ_PER_PROFILE, BLQ_WITHOUT_LLOQ, LLOQ_UNIT_DIFFERS, DUPLICATE_TIME, UNIT_MISSING, UNIT_NOT_IN_TABLES,
           MATRIX_NOT_PLASMA, ANALYTE_MISSING, MATRIX_MISSING, DOSE_MISSING, INFUSION_TIME_MISSING, LANDING_FIELD_MISSING,
           STATISTIC_MISSING, SPREAD_KIND_MISSING, TIME_REFERENCE_UNSTATED, NEGATIVE_VALUE, ABOVE_RANGE,
           DISSOLUTION_METHOD_INCOMPLETE, DISSOLUTION_OUT_OF_RANGE, CONFLICT_OPEN, REQUIRED_ITEM_UNDISPOSED,
           MAPPING_NOT_APPROVED, MW_INCONSISTENT]
    warn: [SPREAD_NOT_CONVERTED, GEOMETRIC_SPREAD_VERBATIM, N_MISSING, NCA_MISMATCH, DOSE_BASIS_UNSTATED,
           DOSE_NOT_MULTIPLE_OF_STRENGTH, CROSSOVER_PERIOD_MISSING, DISSOLUTION_LOT_NOT_CLINICAL, DISSOLUTION_RUNS_NOT_KEYED,
           COMPOSITION_SUM, TIMES_NOT_INCREASING, EXCRETION_NOT_LANDED, OCCASIONS_NOT_LANDED, ZERO_AFTER_QUANTIFIABLE,
           POPULATION_COVARIATE_MISSING, MARKED_VALUE]
    info: [ANALYTE_NOT_PARENT, BLQ_PRESENT, DUPLICATE_TABLE_AND_PLOT, UNIT_NOT_CHECKED]
spot_check:
  size: 100                       # the owner's decision 6
  min_per_stratum: 2              # a proposal, so that every stratum is seen: for the SME
  strata: [table_kind, unit_class, blq_form, cross_file]   # unit class: the field's (fields.unit_class)
  unit_classes: [mass, concentration, time, percentage, ratio]
  # never sampled, always verified. The templates mark no item as deciding the model, so this list is a proposal for
  # the SME: the numeric study facts the study record takes
  always_verify_fields: [dose, n, lloq, strength_mg, infusion_time_min, dosing_interval_h, n_doses]
  always_verify_methods: [digitized, derived]   # every value read from a figure; every derived value, with its inputs
  always_verify_cross_file: [scalar, link]      # a cross-file scalar fact and each link fact; cross-file TABLE values are
                                                # the stratum cross_file (§11.29: the owner confirms this reading)
```

The `routing` table is new SME-type content (the templates carry no population, route or modality field); it follows
the fields `StudyRecord` and the brief already have and stays `UNVERIFIED` until the SME reviews it (§11.20).

Thresholds that already exist are reused, not copied: `datasets.NCA_TOLERANCE`, `pbpk_domain.dissolution.load_rules()`
(`profile.max_percent`), `client_reconciliation.yaml` (`relative_tolerance`).

### 4.8 Spread conversion (`PD/spread.py`)

```python
VERSION = "spread-1"
def sd_from_se(se: float, n: int) -> float                     # se * sqrt(n); ValueError when n < 1
def sd_from_cv_percent(cv_percent: float, mean: float) -> float  # cv_percent * mean / 100 (arithmetic mean only)
# The two error types PK-Sim's observed data take, typed once (harvested: both occur as `AuxiliaryType` in
# services/engine-worker/golden/fixtures/*.json: GeometricStdDev in Midazolam and Rifampicin, ArithmeticStdDev in most;
# C's test asserts both occur). fit_spec,
# units, profile_landing, campaign_activities and the rules loader import them; run_pi.R accepts these two only (§8.3).
ARITHMETIC_SD = "ArithmeticStdDev"; GEOMETRIC_SD = "GeometricStdDev"; ERROR_TYPES = (ARITHMETIC_SD, GEOMETRIC_SD)
```

The ledger's derived SD (§6.3) and D1a's profile SD call these same two functions, so the number a reviewer sees beside
its inputs is the number the campaign gets.

## 5. Stores

All under `<root>/<tenant>/projects/<project>/intake/` (`root = getattr(ws.store, "root", None)`; without a root
`IntakeStore.available` is False and the pipeline is off, as the reading queue is). Client bytes stay where they are:
`ws.store.put_blob` / `blob_path` (the vault of the plan).

| Record | File | Kind | Written by | Read by |
|---|---|---|---|---|
| deliveries and every arriving file | `files.jsonl` | chained log: `delivery` (`{id, by, at}`), `file` (`FileRecord`), `legacy` (what today's ingest did with a file) | W | all |
| pipeline runs (queue, stage times, counters) | `runs.jsonl` | chained log of `RunRecord` | W | D0, D6 |
| parsed source model | `source/<sha256>/<parser>@<parser_version>.json.gz` | cache, atomic write; never evicted while a value names that version | W (D2's output) | W, D6 |
| coverage detail | `coverage/<sha256>.json` | latest `FileCoverage`, atomic write | W (D5's output) | D6 |
| mapping cache | `mappings.jsonl` | chained log: `entry` (`MappingEntry`), `decision` (`MappingDecision`) | D3 | W, D5, D6 |
| ledger | `ledger/facts.jsonl` | chained log: `fact`, `extract` (`ExtractRef`), `status` (`StatusChange`) | D4 | all |
| | `ledger/entities.jsonl` | chained log: `entity`, `alias`, `merge` | D4 | all |
| | `ledger/extracts/<extract id>.json.gz` | `TableExtract`, content-addressed, write-once | D4 | all |
| review state | `review.jsonl` | chained log: `override`, `disposition`, `choice`, `link`, `assignment`, `region`, `spot_draw`, `spot_check`, `confirmation`, `landed` | D6 | D4 (links, confirmations), D5, D0, `LedgerView` |

`PM/intake_store.py` (C; `canonical` and `sha256_of` are imported from `modeler_intake.anchors`, one canonical form for
L2 and L3):

```python
class ChainEntry(B): seq: int; at: str; kind: str; body: dict[str, Any]; prev: str; hash: str
    # hash = sha256(prev + "\n" + canonical({"seq": seq, "at": at, "kind": kind, "body": body})); the first prev is 64 zeros
class ChainProblem(B): seq: int; problem: Literal["hash", "prev", "seq", "torn_tail"]
Row = tuple[str, dict[str, Any] | Callable[[int], dict[str, Any]]]     # (kind, body or a function of the line's seq)
class ChainedLog:
    def __init__(self, path: Path): ...
    def append(self, kind: str, body: dict[str, Any] | Callable[[int], dict[str, Any]]) -> ChainEntry   # the callable gets the line's seq
    def append_many(self, rows: Sequence[Row]) -> list[ChainEntry]
    def append_if(self, decide: Callable[[list[ChainEntry]], Sequence[Row]]) -> list[ChainEntry]
        # read, decide and append under ONE lock: `decide` gets the current entries and returns the rows to append (none:
        # nothing). Every check-then-append uses it: ledger_entities.resolve (get or create), Ledger.record_extraction
        # (idempotence), MappingCache.propose, intake_pipeline.enqueue and sweep, record_spot_check (once per draw),
        # record_confirmation (a double submit gives one line). `decide` must not touch the same log.
    def entries(self, kind: str | None = None) -> list[ChainEntry]
    def head(self) -> ChainHead                                   # seq 0 and 64 zeros when empty (ChainHead: ledger_models)
    def verify(self) -> list[ChainProblem]
class IntakeStore:
    def __init__(self, ws: Workspace): ...
    available: bool
    files: ChainedLog; runs: ChainedLog; mappings: ChainedLog; facts: ChainedLog; entities: ChainedLog; review: ChainedLog
    def source(self, sha256: str, parser: str, parser_version: str) -> SourceDocument | None
    def put_source(self, doc: SourceDocument) -> str             # returns sha256_of(the document)
    def source_versions(self, sha256: str) -> list[tuple[str, str]]
    def extract(self, extract_id: str) -> TableExtract            # KeyError
    def put_extract(self, extract: TableExtract) -> tuple[str, str]      # (extract id, content sha256); write-once
    def coverage(self, sha256: str) -> FileCoverage | None
    def put_coverage(self, coverage: FileCoverage) -> None
    def audit(self, *, actor: str, action: str, resource_id: str, after: dict[str, Any], reason: str | None = None) -> None
        # ws.store.audit(tenant).append(..., resource_type="intake", resource_id=f"{project}/{resource_id}")
```

**No path is built from input.** Every id and sha256 is checked with `anchors.check_id` before use; `source` opens
only a `(parser, version)` pair `source_versions(sha256)` lists (a directory listing under `source/<sha256>/`, the
sha256 checked first), `extract` only an id that an `extract` line of `facts.jsonl` names, `coverage` only a sha256 a
`file` line of `files.jsonl` names; anything else is a `KeyError` (None for `source` and `coverage`). C's test passes
`..`, `/` and a foreign project's path in every part.

A line of a log, and an extract (three values of one subject; `locator` is each value's own cell; the other columns,
all of length `n`, are omitted here when every entry is null):

```json
{"seq": 41, "at": "2026-11-12T10:03:22.512Z", "kind": "fact", "body": {"id": "f-41", "field": "dose", "...": "..."},
 "prev": "ab12...", "hash": "77f0..."}
{"schema": "extract/1", "file_sha256": "9c1e...77", "parser": "workbook", "parser_version": "1.0+openpyxl3.1.5",
 "region_id": "rg-5d2a90c1e4", "mapping": {"mapping_id": "mp-5b0c2a9e41d7", "version": 1}, "kind": "pk_individual",
 "decimal": "point", "entities": [{"study": "st-5", "arm": "arm-6", "analyte": "an-7", "subject": "001"}],
 "entity_locators": [{"subject": "s:'Fasting'!A5", "study": "s:'Fasting'!A1"}],
 "fields": ["concentration"], "units": ["ng/mL"], "conditions": [], "condition_locators": [], "n": 3,
 "entity_ix": [0, 0, 0], "field_ix": [0, 0, 0], "unit_ix": [0, 0, 0], "condition_ix": [null, null, null],
 "time": [0.0, 0.5, 1.0], "time_unit": ["h", "h", "h"], "value": [null, 12.1, 30.4], "verbatim": ["BLQ", "12.1", "30.4"],
 "censored": [true, false, false], "lloq": [0.5, null, null], "lloq_unit": ["ng/mL", null, null],
 "statistic": ["individual", "individual", "individual"],
 "locator": ["s:'Fasting'!B5", "s:'Fasting'!C5", "s:'Fasting'!D5"],
 "time_locator": ["s:'Fasting'!B4", "s:'Fasting'!C4", "s:'Fasting'!D4"], "unit_locator": ["s:'Fasting'!B3", "s:'Fasting'!B3", "s:'Fasting'!B3"],
 "lloq_locator": ["s:'Fasting'!A12", null, null]}
```

**Atomicity and locking.** `append*` takes `pbpk_domain.atomic_io.file_lock(path)` (an flock on `<path>.lock`, across
threads and processes, **not reentrant**: never append to a log from inside its own append), re-reads the head, writes
whole lines, `flush`, `fsync`. A crash can leave one torn last line: `verify` reports `torn_tail`; the next `append`
truncates it under the lock (the line was never acknowledged) and logs a warning. `entries` reads without a lock and
ignores a torn tail. Cache and coverage files use `atomic_write_bytes`. Extract files are written before the ledger
line that names them. A log is read whole per request (thousands of lines at most: table values live in extracts, and
a confirmation binds an extract by its id and content hash, never value by value); a request folds the ledger once
(`LedgerView` is a snapshot shared by everything the request calls); nothing is cached at module level.

**Tampering.** A changed, removed or reordered line breaks `verify`. Each audit event carries the hash it covers, so
the tenant's audit chain (and its Postgres mirror in production) pins the heads of these files.

**Audit events** (one per run, per decision; never one per fact). `resource_type` is `"intake"`.

| Action | When | `after` |
|---|---|---|
| `intake.run` | a run ends, done or failed (also for an unsupported file) | `{run, file_sha256, state, row_hash, ledger_head, values, silent_loss}` |
| `intake.mapping.approve` / `.reject` | a mapping version is decided | `{mapping_id, version, spec_sha256, row_hash}`; `reason` = why |
| `intake.entry` | a person enters or corrects a value | `{fact, row_hash}`; `reason` = why |
| `intake.override` | a failed check is overridden | `{override, check_id, row_hash}`; `reason` = why |
| `intake.disposition` | ask the client, literature, not needed | `{disposition, req_id, row_hash}`; `reason` = why |
| `intake.choice`, `intake.link`, `intake.assign`, `intake.region` | a conflict is settled, a cross-file link confirmed or refused, values assigned to a study, regions or outside items excluded | `{id, row_hash}`; `reason` = why |
| `intake.spot_check` | the ticks are recorded (once) | `{spot_check, draw, ok, not_ok, row_hash}` |
| `signature.create` (existing) | the confirmation is signed | as `record_signature` writes it |
| `intake.confirm` | the confirmation is recorded | `{confirmation, record_sha256, signature_id, row_hash}` |
| `intake.land` | the landing ends | `{confirmation, datasets, evidence, dissolution_records, row_hash}` |
| `artifact.create` / `artifact.revise` (existing) | each dataset, evidence item, submission the landing writes | by `Workspace.commit` |

## 6. Stage interfaces

Error rule for every stage function: a problem with a file's **content** is a returned finding or state, never an
exception; an exception means a bug or a misuse and fails the run at that stage (§6.5).

### 6.1 Parse and locate (D2, L2)

```python
# DI/source/parse.py
SOURCE_VERSION = "1.0"
MAX_MEMBERS = 500; MAX_MEMBER_BYTES = documents.MAX_BYTES; MAX_TOTAL_BYTES = 1024 ** 3
def parser_for(data: bytes, filename: str) -> tuple[str, str]            # (parser, parser_version) without parsing
NEEDS_OCR_MAX_CHARS = 20; TABLE_LIKE_NUMERIC_SHARE = 0.5     # reading parameters: a change is a new SOURCE_VERSION
def parse_document(data: bytes, filename: str, *, container: ContainerRef | None = None,
                   pdf_table_engines: Sequence[PdfTableEngine] = (), ocr: OcrEngine | None = None) -> SourceDocument
    # total: never raises for content; the same bytes give the same document
def zip_members(data: bytes, filename: str) -> list[tuple[str, bytes]]    # file members, one level of nested ZIP; ValueError past a limit
# DI/source/regions.py
def region_grid(doc: SourceDocument, region_id: str) -> RegionGrid        # KeyError (unknown), ValueError (not a table);
                                                                          # with its context (caption, above, below)
def as_workbook_grid(doc: SourceDocument) -> WorkbookGrid                 # today's grid from the same parse (workbook formats)
def paragraphs(doc: SourceDocument, region_id: str) -> list[ProseParagraph]   # with the heading above each
# DI/source/resolve.py
def resolve(doc: SourceDocument, anchor: str) -> Resolved                 # AnchorError: other file or version, or not found;
                                                                          # compares identities (§4.1), never boxes
def check_anchors(doc: SourceDocument, items: Iterable[tuple[str, str, str]]) -> list[AnchorProblem]
    # (id, anchor text, verbatim) of values read under ANOTHER parser version: each must be found again in `doc`, with
    # the same text: a sheet or Word cell by its locator; a PDF cell or span by text and box overlap >= 0.5
def source_view(doc: SourceDocument, anchor: str, *, also: Mapping[str, str] = {}) -> SourceView   # AnchorError
    # `also`: role -> anchor text of the value's time, unit, label, spread, n and LLOQ cells (ValueState.locators),
    # highlighted with their role in the same view
# DI/source/inventory.py
class FormatInventory(B): files: int; by_extension: dict[str, int]; pdf_native: int; pdf_scanned: int; pdf_mixed: int
                          with_figures: int; unsupported: dict[str, int]; zip_members: int
def inventory(files: Iterable[tuple[str, bytes]]) -> FormatInventory
# PM/format_inventory.py:  python -m modeler_project.format_inventory --root R [--tenant T] [--since DATE] [--json] [--out F]
def main(argv: list[str] | None = None) -> int                            # reads names from intake/files.jsonl and DOCUMENT artifacts; writes nothing
```

| Format | Parser name | Reads | State when it cannot |
|---|---|---|---|
| `.xlsx .xlsm` | `workbook` (openpyxl, `data_only=True`) | every non-empty cell with value, text (§4.2: a number's shortest round-trip form, never its display), type, **number format**, merge origin; hidden sheets flagged; a formula with no cached value → finding `FORMULA_NO_VALUE` | `unreadable` (corrupt) |
| `.xls` | `workbook` (xlrd) | the same | `unreadable` |
| `.csv .tsv` | `delimited` | delimiter among `, ; tab |` (`csv.Sniffer`, then the most consistent column count over 50 lines); encoding: BOM, UTF-8, then cp1252 with a warning; every cell text, typed by `is_numeric_text` | `unreadable` (binary) |
| `.docx` | `docx` (python-docx) | body in order: paragraphs (with style) and tables as grids (a merged cell once, with its spans); inline images listed as figures | `unreadable` |
| `.pdf` | `pdfplumber` | per page: size, rotation, words with boxes, ruled tables (`lines` strategy) with cell boxes, image count, `needs_ocr`; extra tables from `pdf_table_engines`, words from `ocr`, when given | `partly_read` (some pages need OCR, listed), `unreadable` (all do, or encrypted) |
| `.txt .md .json` | `text` | lines as paragraphs | `unreadable` |
| `.zip` | `zip` | members listed; each member is parsed by its own call with `container` | `unreadable` (encrypted, over a limit) |
| `.png .jpg` | `image` | one figure | `unsupported`: "an image has no text layer; no OCR engine is registered" |
| anything else (`.doc .pptx .xpt .sas7bdat .html .xml .msg .eml` ...) | `none` | nothing | `unsupported`: "no parser for <ext>" |

Workbooks are read by D2's own module, not through `grid.read_workbook_bytes`, because that drops number formats (a
cell formatted `55%` reads `0.55`) and hidden state; a test proves the two give the same values and merge copies for
the same file, and `as_workbook_grid` hands the legacy grid to `sheet_form.suggest` with no second parse.

**Locate** (inside `parse_document`; rules, no LLM). "A number" is `has_number` throughout (§4.2).
- *Sheets*: blocks of non-empty cells separated by an empty row or an empty column. **One** empty row inside a block
  does not split it when the rows on both sides span the same columns and the row after it holds a number (a Mean / SD
  / N group set off by a blank row, a blank row between header and body): the join is recorded in `Region.notes`. A
  row after the gap that holds no number (a caption or a new header) starts a new block. A block with at least 2 rows
  and 2 cells holding a number is a `table` region (several per sheet; side-by-side blocks are separate); single-cell
  text rows directly above it are its caption; up to 3 rows above that and 3 below that belong to no region are its
  context lines (`RegionGrid.above`, `below`). Every other non-empty cell is an `OutsideItem` (context lines too, with
  `region` set).
- *PDF*: each ruled table is a region. A table that starts a page continues the last table of the page before (the
  **same region**: `parts`, each with its own caption; the repeated header is dropped from the grid and counted in
  `header_rows_repeated`) only when all hold: the earlier part is the last block of its page; it has the same column
  count; it repeats the earlier part's header row or has none; and the text between the two parts is nothing, page
  furniture, or the first part's caption again (equal after removing "continued", "cont.", "cont'd" with their
  brackets, case and spacing; numbers are kept). A different caption ("Table 6 ... Cohort 2" after "Table 5 ...
  Cohort 1") starts a new region. Words in no table are grouped into lines and paragraphs; consecutive paragraphs form
  `prose` regions; a block whose share of numeric tokens reaches `TABLE_LIKE_NUMERIC_SHARE` is a `table_like_text`
  region (an unruled table: located, not gridded). A line repeated at the same place on most pages, or a page number,
  is page furniture (`OutsideItem.furniture`). A page with at most `NEEDS_OCR_MAX_CHARS` characters and an image has
  `needs_ocr`.
- *Word*: each table is a region; paragraphs between tables form `prose` regions (a heading starts a new one).
- *Figures*: one `figure` region each.
- *Role and kind*: `SourceDocument.role` from the words of the first pages or sheets (`document_reading.inventory`'s
  patterns, `triage`'s words, `client_template.is_template`); each table's `table_kind` from `triage.triage_sheet` on
  the region's own grid, mapped by `KIND_OF_CATEGORY`, with the deciding cell in `kind_evidence`.

### 6.2 Map and execute (D3)

```python
# DI/mapping/fingerprint.py
def header_band(grid: RegionGrid) -> int
    # the rows above the first row with two or more cells that are bare numbers or BLQ-like tokens; at most 4; when no
    # row has two, the first row only (a text-heavy product or design table never sends its body as "header")
def layout_fingerprint(grid: RegionGrid) -> str
    # sha256 of "\x1f".join(["cols=<n_cols>", *("<r>:<c>:<norm(text)>" for the header band's non-empty cells, relative
    # r and c), "labels=" + ",".join(sorted(set(norm(first-column non-numeric text of each body row))))])
    # norm: NFKC, casefold, whitespace collapsed, every digit run -> "#". Independent of sheet name, offsets and context.
# DI/mapping/rules.py
RULES = "rules-1"
class RuleMapping(B): spec: MappingSpec; rule: str; notes: tuple[str, ...]
def map_by_rule(grid: RegionGrid, region: Region, *, filename: str = "", drug: str = "", products: Sequence[Mapping[str, str]] = (),
                document_role: DocumentRole = "other") -> RuleMapping | None      # None: no rule maps this layout
def from_sheet_form(form: SheetForm, grid: RegionGrid) -> MappingSpec               # today's suggest result as a v2 spec
def template_spec(sheet_name: str, grid: RegionGrid) -> MappingSpec | None          # a client-data template sheet, exactly
# DI/mapping/validate.py
def validate_spec(spec: MappingSpec, grid: RegionGrid) -> tuple[Finding, ...]       # reads only the grid and its context
# DI/mapping/execute.py
class ParsedCell(B): value: float | None; censored: bool = False; lloq: float | None = None; uloq: float | None = None
                     missing: bool = False; marker: str = ""; problem: str = ""   # marker: a trailing *, †, ‡ (MARKED_VALUE)
def decimal_convention(grid: RegionGrid) -> Literal["point", "comma"]
    # the legacy detector's rule (sheet_form._decimal_comma) on the region: "comma" when at least 2 text cells match
    # sheet_form._COMMA_DECIMAL; never the model's choice
def parse_cell(cell: GridCell, *, decimal: Literal["point", "comma"], column_has_decimal: bool, below_lloq_tokens: Sequence[str],
               missing_tokens: Sequence[str]) -> ParsedCell
def split_cell(text: str, form: CellForm) -> tuple[str, str | None, str | None]   # (value text, spread/low text, unit/high text)
def read_constant(field: str, text: str) -> tuple[float | str, str | None] | None   # the field's own reader; None: not stated once
def read_text_constant(constant: Constant, text: str) -> str | None   # name and text fields: the pattern's group (or the whole
                                                                      # text) when it matches exactly once; choice: read_choice
def execute(spec: MappingSpec, grid: RegionGrid) -> ExtractResult
    # MappingError when validate_spec has an error-severity finding; otherwise never raises
# DI/mapping/redact.py
def redact_cell(text: str) -> str
def redact(grid: RegionGrid, region: Region, *, file_name: str, document_role: DocumentRole) -> RedactedTable
def redact_findings(findings: Sequence[Finding]) -> str          # "REJECTED: ..." with every message through redact_cell
# DI/mapping/prose_check.py
class ProseFactError(ValueError): ...
def check_prose_fact(field: str, value: Any, quote: str, paragraph: ProseParagraph, *, study: str | None = None,
                     arm: str | None = None) -> ProseFact
```

`map_by_rule` reuses today's rules without touching them: it turns the region into a `SheetGrid` whose first rows are
the region's context lines above (so `suggest` sees the title cells it reads dose, study id, n and matrix from,
`sheet_form.py:471-545`) and then the region, calls `sheet_form.suggest` (category from `region.table_kind`), and
converts with `from_sheet_form` (a title cell becomes a `near: "above"` cite). Because it sees one table at a time, the
one-table-per-sheet limit of `suggest` no longer loses a second table. Values `suggest` assumes without a cell (unit
`ng/ml`, time unit `h`, matrix `plasma`, route `oral`, a study id made from the file name) are **not** carried into the
spec: a spec states only what a `Cite` supports; what is missing becomes a requirement gap or a person's entry. Today's
`SheetForm` has one mean row and a mean SD column, no SD row and no N row (`sheet_form.py:125-129`): the rules map
what it maps, and the rest of such a table is `unaccounted`, counted, never dropped (§8.9 measures how far rules reach).

`validate_spec` findings (error unless marked): `CELL_OUTSIDE_REGION` (a cell cite outside the region, a context line
that does not exist), `LAYOUT` (no time source, two nominal time sources, no value column, `of` not a value column,
`time_row` not above the data, a `cell_form` on a non-value column, a `condition` not in `CONDITION_FIELDS`),
`UNKNOWN_FIELD`, `NUMBER_TYPED` (a `Constant.text` or `pattern` on a number field), `CONSTANT_NOT_STATED` (number:
`read_constant` does not find exactly one; name and text: the pattern does not match exactly once, or code's reading
differs from `Constant.text` by `name_key`; choice: `fields.read_choice` finds none, several, or another than
`Constant.text`), `UNIT_NOT_CITED` (a unit with no cite that the header band does not write), `UNIT_NOT_STATED` (a
typed unit is not one of `fields.units_in` of its cited text, or, for a class with no table, not in that text
verbatim), `UNIT_NOT_IN_TABLES` (warn, only for a field whose class has a table: kept verbatim), `BAD_PATTERN`,
`TOKEN_IS_NUMBER`, `REASON_MISSING`. On a cache hit `validate_spec` re-reads every constant and every unit from the
new region's own cells and context: a title that states another study or dose is read as such; a header that writes
another unit fails `UNIT_NOT_STATED`, and the region falls through to the rules.

`execute`: reads every value cell; `cell_use` has an entry for every non-empty cell, with its locator and whether it
holds a number. **The count, one sentence for D3 and D5:** every cell of a mapped region that holds a number
(`has_number`; a merged copy is not counted, its origin is) must end as value, time, spread, n, lloq, interval, label,
condition, header, constant, unit, missing or excluded (by a row rule, an ignored column with its reason, or a token);
otherwise it is `unaccounted`, and every unaccounted cell is silent loss. An unparseable value cell is a finding
`UNPARSEABLE_VALUE` and `unaccounted`. A cell whose number format ends in `%` is read times 100 with unit `%`
(finding `PERCENT_FORMAT`, info). The unit written for a value is the unit token code finds at the cite (as written),
never the model's typing. `cell_form` other than `value`: `split_cell` splits "12.3 (4.5)", "12.3 ± 4.5", "0.95
(0.88-1.03)", "12.3 ng/mL"; each part is parsed by `parse_cell`.

`parse_cell` (U+2212 read as "-"; a trailing `*`, `†` or `‡` is cut into `marker`; `>x` gives `uloq = x`, value None;
`<x` or a below-LLOQ token gives `censored`, `lloq = x`). Under the region's convention:
- `point`: `12.5` → 12.5; `1,234.5` → 1234.5; `1,234` → 1234 when `column_has_decimal` (another cell of the column
  writes a decimal point), else `problem = "ambiguous"`; `12,5` → ambiguous; `1 234.5` (groups of three) → 1234.5.
- `comma`: `12,5` → 12.5; `1.234,5` → 1234.5; `1.234` → 1234 when `column_has_decimal` (another cell writes a
  decimal comma), else ambiguous; `12.5` and `0.125` → ambiguous.
A number stored as a number is taken as it is. Today's `parse_numeric` (it reads `1.5` as 15 under decimal commas) is
not reused. A non-numeric spread or n cell is a finding, never an exception.

`check_prose_fact`, strict and label-aware: (1) the quote is in the paragraph verbatim (`citations.quote_appears_in`);
(2) the clause of the quote that holds the value (split at `;`, at `.` followed by a space, and at ` and `) matches
the field's `cue`; (3) number fields: that clause holds **exactly one** number of the field's unit class (for a class
with a table: a number followed by one of `fields.units_in`; for none: any number) and it equals the value (no
times-100 rule); choice fields: `fields.read_choice` on the clause gives the value; name and text fields:
`document_reading.names_in` (a contiguous match, never the bag-of-words `text_in`, which passes an invented "230-24"
over "230-23 and 231-24"); (4) the unit is parsed by code from the clause and the **number stored is the one code
parsed**, never the model's; (5) `study` and `arm`, when given, must each be written (`names_in`) in the same paragraph
or its heading, and their spans are returned (`study_locator`, `arm_locator`), else `ProseFactError`; with no label the
ledger's rule applies (§6.3); (6) the returned `locator` is the span of the number (or name) itself.

```python
# PM/mapping_cache.py (L3)
class MappingCache:
    def __init__(self, ws: Workspace): ...
    def lookup(self, fingerprint: str) -> tuple[MappingEntry, str] | None   # (latest approved version, "approved"), else
                                                                           # (latest not rejected, "proposed"); None
    def propose(self, fingerprint: str, spec: MappingSpec, *, origin: str, origin_detail: str, first_seen: tuple[str, str],
                by: str) -> MappingEntry        # stores the spec with every Constant.text set to None; the same spec as
                                                # the latest version: that entry, nothing appended (append_if)
    def approve(self, mapping_id: str, version: int, *, by: str, note: str = "") -> MappingDecision   # audit intake.mapping.approve
    def reject(self, mapping_id: str, version: int, *, by: str, why: str) -> MappingDecision          # audit intake.mapping.reject
    def entries(self) -> list[MappingEntry]
    def get(self, mapping_id: str, version: int | None = None) -> MappingEntry | None
    def approved(self) -> set[tuple[str, int]]
# AG/table_mapper.py (L4)
SYSTEM_PROMPT: str; PROMPT_SHA256: str
class TableMapping(B): spec: MappingSpec | None; rejected: tuple[str, ...]; status: str; usage: dict[str, int]; prompt_sha256: str
def map_table(model: ChatModel, *, table: RedactedTable, check: Callable[[MappingSpec], tuple[Finding, ...]], max_turns: int = 4,
              log_step: Callable[[dict[str, Any]], None] = ..., context: str = "") -> TableMapping
    # tools: propose_mapping(spec) -> "ACCEPTED" | redact_findings(findings) ("REJECTED: ..." with every message
    # redacted); not_data(reason). The function receives the redacted table only; `check` is a closure over the grid
    # that stays in L2/L3.
# AG/prose_extractor.py (L4)
ProseCheck = Callable[[str, Any, str, int, str | None, str | None], ProseFact]   # field, value, quote, paragraph, study, arm
class ProseReading(B): facts: tuple[ProseFact, ...]; rejected: tuple[str, ...]; status: str; usage: dict[str, int]; prompt_sha256: str
def extract_prose(model: ChatModel, *, paragraphs: Sequence[ProseParagraph], fields: Sequence[str],
                  check: ProseCheck, max_turns: int = 8,
                  log_step: Callable[[dict[str, Any]], None] = ..., context: str = "") -> ProseReading
    # tool: state_fact(field, value, quote, paragraph, study?, arm?) -> "ACCEPTED" | "REFUSED: <why>" (check raises
    # ProseFactError); the facts returned are check's (code's numbers and spans), never the model's arguments
# AG/evals/scripted.py
class Scripted: provider = "scripted"; model = "scripted"; def __init__(self, turns: list[list[tuple[str, dict]]]); answers: list[str]
```

Mapping order per table region (W runs it): cache (`lookup`; the entry is used only when `validate_spec` passes on
this grid, constants and units re-read from this region, otherwise it is a different layout and falls through) →
`map_by_rule` → the LLM, when a model is configured → otherwise the region is `unread` ("no rule or cached mapping
fits; no model is configured"). A rule or LLM spec is stored with `propose` and executed at once at level
`new_mapping`; a person's approval raises its values to `approved_mapping`. Never a silent skip.

### 6.3 Ledger (D4, L3)

```python
# PM/ledger.py
class ExtractionContext(B): delivery: str; run_id: str | None; file: FileRecord; parser: str; parser_version: str
                            document_role: DocumentRole = "other"; drug: str = ""
class Recorded(B): extract: str | None; facts: tuple[str, ...]; entities: tuple[str, ...]; superseded: tuple[str, ...]
class Ledger(LedgerView):                       # the write side; also implements conflicts() and pending_links()
    def record_extraction(self, *, region: Region, grid: RegionGrid, mapping: MappingEntry, result: ExtractResult,
                          context: ExtractionContext) -> Recorded
        # non-condition, non-label constants and text-valued or relation rows -> scalar facts; numeric rows -> one
        # TableExtract; labels -> entities (resolved inside the file first); stated LLOQs -> lloq facts. Identity below.
    def record_prose(self, *, facts: Sequence[ProseFact], model: ModelUse, context: ExtractionContext) -> Recorded
    def enter(self, *, entity: EntityRef | None = None, field: str | None = None, value: Any, unit: str | None = None,
              time: float | None = None, time_unit: str | None = None, statistic: Statistic | None = None,
              spread: float | None = None, spread_kind: SpreadKind | None = None, n: int | None = None,
              conditions: Mapping[str, str] | None = None, censored: bool | None = None, lloq: float | None = None,
              lloq_unit: str | None = None, why: str, by: str, supersedes: str | None = None) -> Fact
        # a person's entry or correction; audit intake.entry. `supersedes` may name a fact or a value id; the new fact
        # inherits that value's entity, field, time, time unit, statistic, conditions and unit unless given, so a
        # corrected point stays in its series
    def exclude(self, target: str, *, why: str, by: str) -> StatusChange
    def derive(self, *, context: ExtractionContext | None = None) -> list[Fact]     # ledger_compute; idempotent
    def link_files(self, *, context: ExtractionContext | None = None) -> list[Merge]  # ledger_links: explicit link facts; idempotent
# PM/ledger_entities.py
def resolve(ledger: Ledger, *, type: EntityType, label: str, parent: str | None = None, source: str | None,
            file_sha256: str | None, by: str) -> tuple[Entity, Fact | None]
    # Inside the file first: the same name_key under the same parent among the entities whose home file is this one;
    # then an alias a person confirmed in today's review record (client_data.review_record: aliases, product_aliases,
    # batch_aliases) or a ledger alias; then, for a study, ANOTHER file's study with the same key or a confirmed alias:
    # that study is returned WITH a new `link.study_id` fact anchored at this label's cell (the second element); two or
    # more such studies: a new file-local study and a PendingLink (ambiguous); else a new entity. Never by similarity.
    # An arm is resolved inside its study; a batch inside its product. Get-or-create runs under entities.append_if.
def merge(ledger: Ledger, *, type: EntityType, from_id: str, into_id: str, link_fact: str | None, why: str, by: str) -> Merge
# PM/ledger_compute.py
COMPUTE = "compute-1"
def derivations(reader: LedgerReader) -> list[Fact]             # facts to add, each with derived_from and compute; no anchor
# PM/ledger_links.py
def link_facts(reader: LedgerReader) -> list[ValueState]        # active facts whose field starts with "link."
def explicit_links(reader: LedgerReader) -> tuple[list[Merge], list[PendingLink]]   # link.protocol / link.cross_reference
def pending_links(reader: LedgerReader, confirmations: Sequence[LinkConfirmation]) -> list[PendingLink]
```

- **Identity of an extract** (one active extract per file, region and mapping id). The content hashed for the id
  has no delivery and no run (`ExtractRef` carries them). `record_extraction` runs under `facts.append_if`: an active
  extract of the same `(file sha256, region id, mapping id)` whose values equal the new ones (entity ids followed
  through merges) → nothing is written, whatever the delivery, run or mapping version; otherwise the new extract
  supersedes **every** earlier active extract of that file's region (`ExtractRef.supersedes`), whatever the delivery,
  parser version or mapping version. A repeat arrival of the same bytes therefore adds nothing. After a re-parse (a new
  parser version): when `check_anchors` finds every value of an extract again with the same text, the extract stays
  (its anchors and the old source cache are kept) and nothing is written; otherwise the new extract supersedes it and
  the subject's confirmation and draw go stale. An earlier extract whose region no longer exists is superseded by the
  run (a `status` line, reason "region gone after re-parse") and listed as an anchor problem.
- **Entities of a table**: its constants (`study_id`, `treatment`, `analyte`, `product`, `batch`) name the entities
  of every row; a row's own labels (subject, period, sequence, occasion, arm, vessel, analyte, matrix) refine them;
  matrix and the other `LABEL_FIELDS` are labels on `EntityRef`, conditions go to the value's `conditions`. A table or
  a sentence that names no study gives values with `study=None`: kept, shown as "study not stated", never guessed
  from the file name; a person assigns them (`Assignment`, §6.6) or excludes them, and until then the studies of that
  delivery are blocked (`UNASSIGNED_VALUES`). A prose fact with no `study_label` takes the file's study only when the
  file's facts name exactly one.
- **LLOQ**: every stated LLOQ (a column's own, the table's, a token's `<0.5`) is written once as a fact `lloq` on
  (study, analyte, matrix) with its unit as written and its anchor; a value's `lloq` stays on the value. LLOQs are
  compared per (study, arm, analyte, matrix): two in one profile is `ONE_LLOQ_PER_PROFILE`; another unit than the
  values' is `LLOQ_UNIT_DIFFERS`, never converted.
- **Derived facts** (v1, `compute-1`): (a) the SD of an arithmetic mean point from its SE (`spread.sd_from_se`, n of
  that time point, else the series' n; no n → nothing derived, D5 warns) or CV% (`sd_from_cv_percent`): a **spread
  fact** on the same entity, field, time, statistic and conditions, `value` None, `spread` the SD, `spread_kind` "SD",
  `derived_from` (the value id), `compute` "spread-1/sd_from_se" or "spread-1/sd_from_cv_percent"; nothing for a
  geometric mean. The landing writes the ORIGINAL spread and D1a's profile computes the same number with the same
  function (§4.8). (b) A `dose` written in g or µg: a `dose` fact in mg (`fields.MASS_UNITS`), `compute`
  "compute-1/dose_to_mg", always verified with its input. A derived fact never conflicts with its inputs. A dose from a
  strength times a unit count is **not** derived (a check compares them); salt to free base and per-kg doses are not
  derived in this build (no agreed inputs, §11.8).
- **Conflicts**: two active values with the same entity (labels included), field, time (`ledger.time_resolution_min`),
  statistic and `conditions` that differ. Numbers are compared when their units have the same canonical spelling
  (`fields.known_unit`, or the same text for a class with no table); different units → a `unit` conflict, nothing
  converted. Both stay; a `Choice` excludes the others. Values that differ only in `conditions` or a label (a
  solubility at another pH, a profile in another medium, plasma beside urine, Day 1 beside Day 14) are not a conflict.
- **Cross-file facts**, the owner's five conditions as code. An entity's **home file** is the file of its source
  anchor. (1) A study of one file is joined to a study of another only through an anchored link: the `link.study_id`
  fact `resolve` writes at the second file's label cell, or an explicit `link.protocol` / `link.cross_reference` fact
  (a cell or a quoted sentence) that `link_files` resolves to exactly one study and turns into a `Merge` with
  `link_fact` set; a person's upload tag, the same drug or similar dates never qualify. (2) Two or more candidate
  studies: a `PendingLink` (ambiguous), nothing joined. (3) The fold sets `ValueState.cross_file = CrossFile(stating_fact
  = the value's id, link_fact, receiving_study)` on every value whose file is not its study's home file: the value's
  anchor, the link's and the study entity's source are the three anchors. (4) Those values count as unconfirmed
  (`LINK_UNCONFIRMED`) until one `LinkConfirmation` of (study, file) is confirmed; every later value through the same
  link inherits it; a refused link excludes them (and the person may assign them elsewhere); a person's `Assignment`
  or merge is itself the confirmation, bound by the signature. (5) `cross_file` is on every view, and the landing
  writes it into the dataset's `flags` (`cross_file: <file> via <link>`, which D1a's `check_dataset` keeps) and
  `note`.
- **Relations**: rows of a `ddi_relation` table (or a test-against-reference table) are written as facts with
  `relation` (the other arm, from the `other_arm` label) and `interval` (low, high, kind, level from the interval
  columns or a "value (low-high)" cell); they have no landing shape (§11.33).
- **Occasions**: values with an `occasion` label keep it on their entity; a profile with more than one occasion is held
  back at the landing (§6.6, §11.27).
- **Excretion**: `excretion.*` facts are kept; no dataset is made from them (deferred, §11.8).

### 6.4 Checks and coverage (D5, L3)

```python
# PM/coverage.py
def outcome_from(region: Region, result: ExtractResult | None, *, state: str, reason: str = "", mapping: MappingUse | None = None,
                 origin: str | None = None) -> RegionOutcome      # the compact outcome W stores (counts from result.cell_use)
def file_coverage(file: FileRecord, doc: SourceDocument, outcomes: Sequence[RegionOutcome], decisions: Sequence[RegionDecision] = (),
                  anchor_problems: Sequence[AnchorProblem] = (), *, values_unassigned: int = 0,
                  rules: IntakeRules | None = None) -> FileCoverage
    # mapped regions are counted from their outcomes alone; unread regions from Region.numeric_cells; the document is
    # needed only for its regions and outside items. No grid.
def silent_loss(coverages: Iterable[CoverageSummary]) -> int
# PM/study_routing.py
def study_tags(reader: LedgerReader, study: str, *, brief: ProjectBrief | None) -> dict[str, str]
    # species, population, special_population, route, food_state, formulation, design, co_medication, genotype (the
    # study's own facts); modality and applications (the brief). A tag no fact states is absent.
def route(study: str, tags: Mapping[str, str], *, applications: Collection[str], rules: IntakeRules | None = None) -> Routing
# PM/study_requirements.py
def requirement_status(reader: LedgerReader, study: str, *, brief: ProjectBrief | None, matrix: RequirementMatrix | None,
                       dispositions: Sequence[RequirementDisposition] = (), rules: IntakeRules | None = None) -> StudyRequirements
def product_requirements(reader: LedgerReader, product: str, *, brief: ProjectBrief | None, matrix: RequirementMatrix | None,
                         dispositions: Sequence[RequirementDisposition] = (), rules: IntakeRules | None = None) -> tuple[RequirementStatus, ...]
def request_lines(statuses: Iterable[RequirementStatus], *, labels: Mapping[str, str]) -> list[RequestLine]   # requirements.RequestLine
# PM/intake_checks.py
CHECKS: tuple[str, ...]                        # every code of intake_rules.yaml checks.severity, and no other
def run_checks(reader: LedgerReader, *, subject_type: Literal["study", "product", "compound"], subject: str,
               requirements: Sequence[RequirementStatus] = (), mol_weight: float | None = None,
               parent_names: Collection[str] = (), rules: IntakeRules | None = None) -> tuple[CheckResult, ...]
# PM/scorecard.py
def scorecard(reader: LedgerReader, *, subject_type: Literal["study", "product", "compound"], subject: str,
              coverage: Sequence[CoverageSummary], requirements: Sequence[RequirementStatus], gaps: Sequence[SchemaGap],
              checks: Sequence[CheckResult], overrides: Sequence[Override] = (),
              dispositions: Sequence[RequirementDisposition] = ()) -> Scorecard
```

- **Coverage.** A region is `mapped`, `excluded` (a rule of `coverage.excluded_by_rule`, a `not_data` mapping, or a
  person's `RegionDecision`, each with its reason) or `unread`. The count is §6.2's sentence: every cell of a mapped
  region that holds a number (`has_number`, merged copies not counted) is used or excluded by a stated rule, else it
  is silent loss; `silent_loss` = those unaccounted cells + every cell with a number of unread `table` and
  `table_like_text` regions (`Region.numeric_cells`). Unread prose is listed, not counted. A file's coverage also
  lists its outside items by page or sheet and its unresolved anchors; `outside_numeric` counts the outside items
  with a number that are not furniture, not cited by a mapped region's constant (`RegionOutcome.cited`) and not
  accepted by a `RegionDecision` of scope `outside` (one per file may list them all with its reason): above zero it is
  the blocker `OUTSIDE_NUMBERS`. `values_unassigned` (given by the caller from the ledger) above zero is the blocker
  `UNASSIGNED_VALUES` for the studies of that delivery. The coverage file is the current truth: `exclude_regions` and
  `assign` (§6.6) recompute it from the stored outcomes, all decisions and the source cache, and store it.
- **Routing and G4.** Templates a study activates: `routing.core`, the templates the project's applications select
  (`requirements.load_templates()`, `applies_to` against the brief's applications: read-only reuse), and `by_tag`.
  A tag matching `routing.gaps`, or a study with no `route` fact, is a `SchemaGap`. Item status is judged for
  `item_scope.study` items per study and `item_scope.product` items per product; every other item is `scope:
  "project"` and is not a study's blocker. `when` is evaluated with the study's own route and food state and the
  brief's remaining keys (never `requirements.evaluate_when`'s APP-12 shortcut). `found`: the `item_fields` are active
  values (with `per`: for every analyte and matrix of the study's concentration values; with `conditions`: each such
  value carries them); `conflicting`: one of them is in a conflict; `missing` until a `RequirementDisposition` sets
  `ask_client`, `literature` or `not_needed`. The `@` suffix of a per-product id is kept (`REQ-form.release@<slug>`).
- **Checks** (plan §7.7), each a `CheckResult` with the rule it applied; every threshold comes from the rules file
  (`checks.*`, `ledger.time_resolution_min`) or an existing one (`datasets.NCA_TOLERANCE`,
  `dissolution.load_rules()`). `LANDING_FIELD_MISSING`: a `StudyRecord` field the landing needs (n, dose, route, the
  formulation of an oral study, `intended_use`) has no active value. `MAPPING_NOT_APPROVED`: a value of the subject is
  at level `new_mapping`. `MATRIX_NOT_PLASMA`: a concentration profile measured in a matrix of
  `landing.matrix_as_plasma_with_warning`. `UNIT_NOT_IN_TABLES`: only for a field whose class has a table
  (`fields.known_unit` is None); the value is kept with its unit as written, nothing is refused or renamed;
  `UNIT_NOT_CHECKED` (info) names the units of fields with no table. `STATISTIC_MISSING`: a value with no statistic
  and no subject; `SPREAD_KIND_MISSING`: a spread of unknown kind (neither lands). `TIME_REFERENCE_UNSTATED`: a study
  whose design is MD with no stated time reference. `LLOQ_UNIT_DIFFERS`, `NEGATIVE_VALUE` (a negative concentration:
  `check_dataset` would refuse it), `ABOVE_RANGE` (a value written `>x`), `ZERO_AFTER_QUANTIFIABLE` (a 0 after the
  first quantifiable point: BLQ written as zero), `MARKED_VALUE` (a footnote mark on a value),
  `POPULATION_COVARIATE_MISSING` (`routing.population_covariates`), `DISSOLUTION_RUNS_NOT_KEYED` (two runs whose
  `ProfileKey` is equal while temperature or surfactant differ), `OCCASIONS_NOT_LANDED`. `fail` blocks until fixed,
  overridden (`Override`) or, for `REQUIRED_ITEM_UNDISPOSED` and `CONFLICT_OPEN`, settled by a
  `RequirementDisposition` or a `Choice`. A `SchemaGap` cannot be overridden. An override lets the subject be
  confirmed; it never makes the landing write what `check_dataset` refuses (§6.6 holds that back, listed).

### 6.5 The stage runner and the jobs (W)

```python
# PM/intake_files.py (L3)
def open_delivery(ws: Workspace, *, by: str) -> str
def record_arrival(ws: Workspace, data: bytes, filename: str, *, delivery: str, by: str, container: ContainerRef | None = None) -> FileRecord
    # put_blob, then one files.jsonl line; the same bytes again: a `repeat` line
def note_legacy(ws: Workspace, file_id: str, *, sid: str | None, refusal: str | None) -> None
def files(ws: Workspace) -> list[FileRecord]
# PM/intake_pipeline.py (L3)
class MapRequest(B): region_id: str; table: RedactedTable
class MapAnswer(B):  region_id: str; spec: MappingSpec | None; origin_detail: str; agent_run: str | None; error: str = ""
class LlmPorts:      # a frozen dataclass: how L3 reaches the LLM stages without importing L4; None: no model is configured
    map_tables: Callable[[Sequence[MapRequest], Callable[[str, MappingSpec], tuple[Finding, ...]]], Sequence[MapAnswer]]
    extract_prose: Callable[[Sequence[ProseParagraph], ProseCheck], tuple[Sequence[ProseFact], ModelUse | None]]
def enqueue(ws: Workspace, files: Sequence[FileRecord], *, by: str) -> list[RunRecord]
    # under runs.append_if: not twice while one waits or runs; a repeat of a sha256 whose latest run is done under the
    # current parser version is recorded (files.jsonl) and queues nothing
def take(ws: Workspace) -> RunRecord | None
def recover(ws: Workspace) -> int                                # runs left `running`: queued again, failed after 2 attempts
def pending(ws: Workspace) -> bool
def sweep(ws: Workspace, *, by: str = "code") -> int             # stored client files (client_data.submissions) with no run:
                                                                 # recorded under one delivery and queued (append_if); how many
def run_file(ws: Workspace, run: RunRecord, *, llm: LlmPorts | None = None, brief: ProjectBrief | None = None,
             matrix: RequirementMatrix | None = None, clock: Callable[[], float] = time.monotonic) -> RunRecord   # never raises
# API/intake_pipeline_jobs.py (L6)
class MemberRefusals(ValueError):    # a ZIP some of whose members today's ingest refused
    accepted: list[dict[str, Any]]; refused: list[str]           # "<zip>/<member>: <reason>"
def receive(ws, library, data: bytes, filename: str, *, by: str, delivery: str, ingest: Callable[..., dict],
            **ingest_kwargs) -> list[dict[str, Any]]             # one ingest answer per file or accepted member
def kick(store: ProjectStore, tenant_id: str, project_id: str, *, by: str = "code") -> bool
def drain(store: ProjectStore, tenant_id: str, project_id: str, held: Callable[[], bool] | None = None) -> None
def ports(store: ProjectStore, tenant_id: str, project_id: str) -> LlmPorts | None
```

`run_file`, stage by stage; each is timed into `StageTiming` and guarded: an exception ends the run `failed` at that
stage with `detail = "<Type>: <message>"`, later stages are skipped, the line and the `intake.run` event are still
written, and the next run is taken.

| Stage | Does |
|---|---|
| `parse` | `parser_for`; `IntakeStore.source` hit → use it; else `parse_document` and `put_source`. When values of this file exist under another parser version: `check_anchors` against the new document; problems go to the run and the coverage |
| `map` | per table region: fingerprint; cache, then rules (§6.2); template sheets by `template_spec` |
| `map_llm` | the regions left, through `llm.map_tables` (4 at a time; one agent run each, named `A4-table-mapper`); skipped with no model |
| `execute` | `execute` per mapped region; `coverage.outcome_from` gives each `RegionOutcome` |
| `prose` | `prose` regions through `llm.extract_prose` (run `A4-prose`); skipped with no model: the regions stay `unread` with that reason |
| `ledger` | `record_extraction`, `record_prose` |
| `compute` | `derive`, `link_files` |
| `checks` | routing, requirement status and checks for the studies and products the file touched (timed for G7 and so a failure shows on the run; the cards recompute on read) |
| `coverage` | `file_coverage` (with the file's unassigned values), `put_coverage`; summary ("at run end") and `ledger_head` into the run |

`receive` (every arrival route calls it in place of `ingest`, with the legacy `ingest` passed in so monkeypatches still
apply): in `legacy` it returns `[ingest(...)]`, exceptions unchanged. In `both`, for a file that is not a ZIP:
`record_arrival` first, then the legacy `ingest` with the caller's arguments; its answer is returned as a one-entry
list, unchanged, and its exceptions propagate unchanged after `note_legacy(refusal=...)` (so an unsupported or
unreadable file is stored and recorded before it is refused: G2, decision F); then `enqueue`. A ZIP is recorded, then
expanded (`zip_members`) and each member goes through the same steps with its `container`; the answer is one entry per
accepted member, its `file` shown as `<zip>/<member>`; when a member is refused, `MemberRefusals` carries the accepted
entries and the refused members. The three callers extend their lists: the upload answer lists one `read` entry per
accepted member and, when some were refused, answers 422 naming each refused member with the accepted ones listed as
today ("(added: ...)").

`kick` starts the project's `intake` job (`jobs.Kind` gains `"intake"`; its own lease, beside `reading`) whenever a
run waits, with or without a model. `drain`: `recover`, then `take` → `run_file` until none is left; `ports` is read
once per run through `agent_jobs.chat_model("A4")`.

### 6.6 Review, confirmation and landing (D6, L3)

**Subjects.** A study, a product, and the project's **compound** (one per project, subject id `compound`): the facts of
a compound-level field (a CPF id: a physchem or in vitro table, a CoA's molecular weight) belong to no study or
product, so they are confirmed on their own card with their own signature (decision E's record, for that subject).
The compound card has coverage of its files, checks, the spot check and the confirmation; its requirement items stay
the project's (the data plan). Values with no study are listed under "study not stated" until a person assigns or
excludes them.

```python
# PM/intake_review.py      (every function that reads the ledger takes the request's one LedgerView: `reader`)
SubjectType = Literal["study", "product", "compound"]
def subjects(ws: Workspace, *, reader: LedgerReader) -> list[dict[str, Any]]
    # studies, products and the compound with counts and confirmation state; blockers are computed by the subject
    # route only (the polled page never recomputes every card)
def unassigned(ws: Workspace, *, reader: LedgerReader) -> list[ValueState]    # the "study not stated" list
def card(ws: Workspace, subject_type: SubjectType, subject: str, *, reader, brief, matrix, mol_weight: float | None) -> Scorecard
def override(ws, *, subject: str, check_id: str, why: str, by: str) -> Override
def dispose(ws, *, subject: str, req_id: str, disposition: str, why: str, by: str) -> RequirementDisposition
def choose(ws, *, conflict_id: str, keep: str, why: str, by: str) -> Choice
def confirm_link(ws, *, link_fact: str | None, study: str, file_sha256: str, confirmed: bool, why: str, by: str) -> LinkConfirmation
def assign(ws, *, targets: Sequence[str], study: str, arm: str | None, why: str, by: str) -> Assignment
    # audit intake.assign; recomputes and stores the coverage of the files concerned
def exclude_regions(ws, *, file_sha256: str, regions: Sequence[str], scope: str, why: str, by: str) -> RegionDecision
    # audit intake.region; recomputes file_coverage from the stored outcomes, ALL RegionDecisions and the source
    # cache, and stores it (put_coverage) in the same call
def draw_spot_check(ws, subject_type: SubjectType, subject: str, *, reader, by: str) -> SpotCheckDraw
def record_spot_check(ws, draw_id: str, ticks: Sequence[SpotTick], *, by: str) -> SpotCheckRecord     # once per draw (append_if)
def spot_check_state(ws, subject_type: SubjectType, subject: str, *, reader) -> Literal["none", "drawn", "failed", "complete", "stale"]
def blockers(ws, subject_type: SubjectType, subject: str, *, reader, brief, matrix, mol_weight, blinded: bool) -> tuple[Blocker, ...]
def bound_record(ws, subject_type: SubjectType, subject: str, *, reader, brief, matrix, mol_weight) -> tuple[dict[str, Any], str]
def record_confirmation(ws, *, subject_type: SubjectType, subject: str, record: dict[str, Any], record_sha256: str, signature_id: str,
                        manifestation: str, by: str, printed_name: str) -> Confirmation      # append_if: one line per record_sha256
def landing_incomplete(ws, subject_type: SubjectType, subject: str, record_sha256: str) -> Confirmation | None
    # a confirmation of that record hash with no `landed` line
def covered_by_confirmation(ws, dataset: ObservedDataset) -> Confirmation | None             # by the overlap of §2
def blinded_subjects(ws, project: dict[str, Any] | None, model_risk: str | None) -> set[str]
# PM/intake_landing.py
class LandingError(ValueError): ...
class LandingPlan(B): datasets: tuple[ObservedDataset, ...]
                      dissolution: tuple[tuple[str, tuple[dict[str, Any], ...]], ...]   # (client file sid, template-shaped rows)
                      evidence: tuple[EvidenceItem, ...]                                # each already through evidence.assess
                      held: tuple[str, ...]                                             # "<what>: <reason>" (table below)
                      reject_legacy: tuple[str, ...]; sheets: tuple[tuple[str, str], ...]
def legacy_overlap(ws, subject_type: SubjectType, subject: str, *, reader) -> list[ObservedDataset]    # §2, by source
def plan_landing(ws, library, subject_type: SubjectType, subject: str, *, reader, matrix: RequirementMatrix | None,
                 mol_weight: float | None) -> LandingPlan
    # builds and checks everything (check_dataset, StudyRecord, evidence.assess), writes nothing; LandingError names a
    # missing StudyRecord field. Dataset ids are "ds-" + sha256(subject digest + "|" + arm + "|" + analyte + "|" + matrix)[:10]
def land(ws, library, confirmation: Confirmation, plan: LandingPlan, *, by: str) -> Landed
    # idempotent: what already exists is skipped; names the confirmation in each dataset's note and decision reason
# PM/client_data.py (D6 adds it beside record_mapping: client-file content has one owner)
def record_delivery_rows(ws: Workspace, sid: str, rows: Sequence[dict[str, Any]], *, tag: str, by: str) -> int
    # appends template-shaped dissolution rows to the submission's `dissolution` (what profiles_from_rows reads), each
    # carrying `tag` ("delivery-<cf id>"), replacing earlier rows of the same tag; then the register rebuilds
# PM/intake_health.py
def summary(root: Path, *, tenant: str | None = None, since: datetime | None = None) -> dict[str, Any]
```

**Spot check** (decision 6; numbers and lists from `spot_check` of the rules file). Candidates: the subject's active
values that are numeric **or censored** (a BLQ value is a candidate: its marker form is a stratum). `always` (never
sampled): values of `always_verify_fields`; every value of a check that carries an override; every value whose method
is in `always_verify_methods` (digitized; derived, shown with its inputs); every cross-file scalar fact and every link
fact (`always_verify_cross_file`). Strata of the rest: table kind; unit class (the field's); BLQ marker form (the
verbatim of a censored value); cross-file table values. `sampled`: everything when the rest has at most `size` values;
else `min_per_stratum` from each stratum, then the remainder in proportion (largest remainder). Within a stratum,
values are ordered by `sha256(seed + value id)` and the first k are taken: no random generator. `seed = sha256(facts
head hash + "|" + subject + "|" + rules version)`, stored with `heads` (the facts, entities, mappings and review logs'
heads and the rules file's sha256: everything the candidates, `always` and the strata depend on) and `subject_digest`,
so an auditor can recompute the draw. A tick covers the tuple a value is read with: value, unit, time, labels and
statistic; the draw lists each value with `ValueState.locators`, and its source view highlights each of those cells
with its role. Ticks arrive once, as one record. A draw is `stale` when `reader.digest(subject)` differs from its
`subject_digest`; a new draw carries over (`carried`) the ok ticks of values whose id, value and anchor are unchanged,
so only new or changed values are ticked again. `complete`: every value of `always` and `sampled` is ticked ok or
carried.

**Confirmation** (decision E). `bound_record` is

```json
{"schema": "confirmation/1", "project": "<id>", "subject_type": "study", "subject": "st-2", "label": "230-23",
 "subject_digest": "<sha256>", "facts": [["f-41", "50.0", "mg"]], "extracts": [["tx-1f0c...", "<content sha256>"]],
 "excluded": ["tx-1f0c...#7"], "assignments": ["as-1:<row hash>"], "mappings": [["mp-5b0c2a9e41d7", 1, "approved"]],
 "overrides": ["ov-3:<row hash>"], "dispositions": ["dp-1:<row hash>"], "choices": [], "links": ["lk-2:<row hash>"],
 "regions": ["rd-1:<row hash>"], "spot_check": "sc-4:<row hash>",
 "coverage": {"files": 3, "silent_loss": 0, "regions_unread": 0, "outside_numeric": 0, "values_unassigned": 0},
 "requirements": [["REQ-obs.bioanalytical", "found"]], "checks": [["ONE_LLOQ_PER_PROFILE", "ck-...", "overridden"]],
 "held": ["ev phys.logp: outside_physical_range (lands PROPOSED)"],
 "rules": {"version": "0.1", "status": "UNVERIFIED", "sha256": "<sha256 of intake_rules.yaml>"}}
```

sorted and hashed with `sha256_of`. Extract values are bound by the extract's id and content hash plus the ids
excluded from it; scalar facts by id, value and unit; the subject digest pins the set (no global ledger head, so a
fact of another study does not change this record). The route (§8.10): first, `landing_incomplete` for the freshly
computed record hash: if a confirmation of the same record exists with no `landed` line, it goes straight to `land`
(its blockers were evaluated when it was signed; no new signature). Otherwise every refusal first (`blockers` empty,
`plan_landing` passes); `ensure_step_up`; `sign_after_step_up(meaning=SignatureMeaning.REVIEWED,
record_type="intake-confirmation", record_id=f"{project_id}/delivery/{subject_type}/{subject}", record_sha256=...)`;
`record_signature`; `record_confirmation`; `land`; `refresh_inputs`. Role: `Writer` (what today's
`client-review:confirm` uses). A confirmation refuses while there is silent loss, an outside number not accepted, or
an unassigned value in the subject's deliveries, a schema gap, a failed check without an override, an unconfirmed
cross-file link, an incomplete or stale spot check, a dataset already accepted on the legacy card, or (§11.1) the
subject is blinded. What the landing holds back is in the record (`held`) and on the card before signing.

**What the landing writes** (`plan_landing`; decision I holds in the ledger, where every unit stays as written; the
landing writes only what the model's code accepts and holds the rest back, listed, while the rest of the subject
lands: §11.23).

| What | Lands as | Held back (in `held` and `Landed.pending`, with the reason) |
|---|---|---|
| Concentration values of one (arm, analyte, matrix) | one `ObservedDataset`: `study` = the `StudyRecord` fields the facts give (`study_id` = the study's label, or `<study>-<arm>` when it has several arms, as `client_data._arm_id` does); series = individuals by subject, then one per statistic; `origin=CLIENT`, `provider="CLIENT"`, `extraction="CELL"` (sheets) or `"TABLE"` (PDF, Word), `purpose` = `intended_use`, `source=SourceRef(doc_sha256=<file>, page=..., locator="Delivery confirmation cf-n")`; proposed, then `decide_dataset(ACCEPTED, reason="confirmed on Delivery (cf-n, signature <id>)")` | a unit `pbpk_domain.units` does not know (`check_dataset` would refuse it, override or not); a negative value; more than one occasion (`OCCASIONS_NOT_LANDED`, §11.27); two or more LLOQs in the profile with no person's `lloq` entry for that (study, analyte, matrix) |
| Time | the dataset's `time_unit` as `min`, `h` or `day` (the canonical of `validate.TIME_UNITS`, "day(s)" written `day`: `inputs` and `dissolution` read only these three); the nominal time, or the actual time when every point of the series has one (as `client_data` does today), named in the note | a time unit outside `validate.TIME_UNITS` |
| Spread | by `landing.spreads_landed`: an arithmetic mean's SD, SE or CV% as `Series.error_kind` SD, SE, CV% (the original; D1a's profile converts SE and CV% with `PD/spread`); a geometric mean's geoSD as `SD` (D1a sends it as `geometric_sd_sent_as`). Every other pair (a plain "SD", SE or CV% beside a geometric mean; geoSD or geoCV% beside an arithmetic mean; any spread of a median) lands no error, stays in the ledger and is named in the note | a spread of unknown kind (`SPREAD_KIND_MISSING`) |
| Interval (CI, range) | nothing (a `Series` has none); named in the note | — |
| BLQ | the value None, the LLOQ in the study record: today's rule, named on the profile and the row (D1a) | — |
| n per time | `Series.n_at` (D1a), `n` the first | — |
| Dose | `dose_mg`: a dose written in mg as it is; in g or µg the derived mg fact (always verified with its input); `mg/kg`: `dose_mg` = the number and `dose_per_kg` true, as `document_reading.check_fact` does | a dose unit outside the mass table |
| Cross-file | `flags` gains `cross_file: <file> via <link>` (kept by D1a's `check_dataset`) and the `note` names it | — |
| PK parameters | `reported` (its unit as written: `ReportedPK.unit` is free text) | — |
| Dissolution | template-shaped rows (`values`: product, role, strength_mg, batch, apparatus, rpm, medium, ph, volume_ml, time, time_unit, vessel_1 … vessel_12 and/or mean, sd, n; `cells`: each value's locator) through `client_data.record_delivery_rows`, tag `delivery-<cf id>`; the register rebuilds (`profiles_from_rows` keeps a summary's SD and n) | two runs whose `ProfileKey` is equal while their temperature or surfactant differ (`DISSOLUTION_RUNS_NOT_KEYED`: one would overwrite the other); a file with no client-file record (today's `ingest` refused it: §11.13) |
| Compound and product evidence (a CPF id field) | `evidence_register.propose(value_in_quote=True)`, then `decide(ACCEPTED)` | an item `evidence.assess` flags with one of `sources.rule().hold_flags` (`needs_conversion`, `outside_physical_range`, `species_mismatch`, `check:` ...): proposed and left `PROPOSED` for a person, as `source_selection.yaml` requires; listed on the card before signing |
| Excretion, product attributes other than dissolution, relations | nothing (§11.8, §11.28, §11.33) | always |

## 7. Contract code: committed once, before the parallel builds

One engineer writes exactly this, with no behaviour beyond what §4 and §5 state, and commits it to the integration
line (the session's branch, plan §10.2; one commit carrying its CHANGELOG entry, §9). Every builder branches from that
commit.

| File | Content |
|---|---|
| `packages/data-intake/pyproject.toml`, `uv.lock` | `pdfplumber>=0.11` (MIT; brings pdfminer.six, pypdfium2), named in the plan §10.2: already added at `ab1e725`; C only checks it imports |
| `DI/anchors.py` | §4.1 (models, grammar with its character sets, identity, `ID_PATTERNS`, `check_id`, `canonical`, `sha256_of`) |
| `DI/source_model.py` | §4.2 (models, `is_numeric_text`, `has_number`, `RegionGrid` with its context, the two Protocols) |
| `DI/fields.py` | §4.3 (vocabulary, `unit_class`, `MASS_UNITS`, `unit_table`, `known_unit`, `units_in`, `read_choice`, the choice cues) |
| `DI/mapping_spec.py` | §4.4 (models only) |
| `DI/synthetic.py` | §10: the shared synthetic files with their truth, each truth table's approved spec, `truth_grid`; its own PDF writer (no `modeler_project` import) |
| `PD/spread.py` | §4.8 (the two formulas, `ERROR_TYPES`) |
| `PM/intake_rules.yaml`, `PM/intake_rules.py` | §4.7 (`RULES_VERSION`, `RULES_STATUS`, `RULES_SHA256`; the loader's two refusals) |
| `PM/intake_store.py` | §5 (`ChainedLog` with `append_if`, `IntakeStore` opening only listed names) |
| `PM/ledger_models.py` | §4.5 (pure models, `ChainHead`) |
| `PM/intake_records.py` | §4.6 (pure models) |
| `PM/ledger_view.py` | §4.5 (`LedgerReader`, `LedgerView`: the fold, a per-request snapshot) |
| `PM/intake_fixtures.py` | `write_truth(ws, files, *, delivery="dl-1", approved=True) -> dict[str, str]` (truth value -> value id): the synthetic truth written as entities, extracts and facts through `IntakeStore` exactly as §4.5 and §5 say, its mappings proposed and (by default) approved. D0, D5, W and D6 test against it; D4's own tests do not (they test the writes) |
| `packages/data-intake/tests/test_intake_contracts.py` | anchor text round-trips for every locator kind; a part outside its character set is refused; `same_place` ignores the box; `is_numeric_text` and `has_number` tables (U+2212, "12.3 (4.5)", "12.3*"); `canonical` of a model uses the alias; every synthetic file opens with its own library (openpyxl, python-docx, pdfplumber) and shows its truth; `truth_grid` gives each truth value its locator; `fields` covers every template column; `known_unit` takes mg, g, µg, mg/kg for dose and refuses nothing for rpm (None, no table); `read_choice` reads every choice column of the template's Studies row |
| `packages/project-model/tests/test_intake_store.py` | a chain verifies; an edited, removed or swapped line is found; a torn tail is repaired by the next append; two processes appending lose nothing; `append_if` decides under the lock (two threads, one line); `..`, `/` and a foreign project's path in every id part are refused; `LedgerView` folds supersede, exclude, assignment, a refused link, cross-file and levels; `write_truth` round-trips through `LedgerView`; the rules file loads, is `UNVERIFIED`, and its sha256 equals the one pinned for its version |
| `packages/pbpk-domain/tests/test_spread.py` | the two formulas; both `ERROR_TYPES` occur as `AuxiliaryType` in `services/engine-worker/golden/fixtures/*.json` |

Markers (§10): `T-47` on all three; the store test also `T-05` and `F-404` (chains). Acceptance: `uv run ruff check .`,
the three test files, `uv run pytest tests/architecture -q` green (the lock test included: nothing here is under a
locked pattern).

## 8. Per-build briefs

Common to all: branch from the contract commit; no edit outside the files you own; no edit of CHANGELOG, the
continuation document, the OpenAPI snapshot, the web types, any `pyproject.toml` or `uv.lock` (§9); return your
CHANGELOG entry as text (the integrator squashes your branch into one commit that carries it, §9). Import ledger
models from `modeler_project.ledger_models`, records from `intake_records`, the read side from `ledger_view`.
Acceptance always includes `uv run ruff check .` and `uv run pytest tests/architecture -q`.
The 15 baseline failures (14 in `services/orchestrator/tests/test_campaign_workflows.py`, and
`packages/data-intake/tests/test_intake.py::test_vault_is_content_addressed_write_once_and_verifiable`) are not yours.
Tests use the made-up drug `Exampleamide`, no client name, no PK-Sim, no live model.

### 8.1 D0: the scoring harness (G1)

Goal: score a delivery value by value against a key the scientist's analysts wrote. D0 writes no real key.

Owns: `PM/value_key.py`, `PM/value_score.py`, `PM/key_compare.py`, `docs/evaluations/value-key-runbook.md`,
`packages/project-model/tests/{test_value_key,test_value_score,test_key_compare}.py`. Shared files: none.
`delivery_report.py`, the v1 YAML key and its report are untouched and keep working.

The key is a workbook, read with `modeler_intake.grid.read_workbook_bytes`; a key cell that is not text in a text
column is refused with its cell named (so `0123`, `001`, `12.40` and `1:30` are never re-typed by a loader).

| Sheet | Columns |
|---|---|
| `Header` | `schema` (`value-key/2`), `delivery`, `analyst`, `date`, `status` (draft, verified, adjudicated) |
| `Key` (one row per expected value) | `file`, `where` (sheet or page), `table`, `study`, `arm`, `analyte`, `matrix`, `subject`, `field` (§4.3), `time`, `time_unit`, `value` (as written: a number, a BLQ form such as `BLQ` or `<0.5`, or a missing token), `unit`, `note` |
| `Studies` (optional) | `study`, `names` (other spellings, `;`-separated), then one column per routing tag (`population`, `special_population`, `route`, `food_state`, `application`) |
| `Not data` (optional) | `file`, `where`, `table`, `reason` |

`time_unit` and the two optional sheets are additions to the lead's column list (§11.9).

```python
# PM/value_key.py
class ValueKeyError(ValueError): ...                               # names the sheet and cell
class KeyRow(B): row: int; file: str; where: str; table: str; study: str; arm: str; analyte: str; matrix: str; subject: str
                 field: str; time: str; time_unit: str; value: str; unit: str; note: str
class ValueKey(B): schema_id: str; delivery: str; analyst: str; date: str; status: str; rows: tuple[KeyRow, ...]
                   studies: tuple[dict[str, str], ...]; not_data: tuple[dict[str, str], ...]
def load_key(data: bytes, filename: str) -> ValueKey
def template_workbook() -> bytes                                   # the empty key, value columns formatted as text
def key_from_truth(files: Sequence[SyntheticFile], *, analyst: str = "test") -> bytes     # tests only
# PM/value_score.py
class Extracted(B): file: str; study: str; arm: str; analyte: str; matrix: str; subject: str; field: str
                    time_min: float | None; value: str | None; verbatim: str; censored: bool; lloq: str | None; unit: str | None
                    method: str; anchor: str | None; id: str     # value: the number as code read it; verbatim: as written
def from_ledger(ws: Workspace) -> list[Extracted]                  # LedgerView: active values (spread facts are not values)
def from_stores(ws: Workspace) -> list[Extracted]                  # the baseline: datasets, waiting drafts' points, dissolution records, study facts
Verdict = Literal["found", "found_rounded", "wrong_value", "wrong_unit", "missing", "unexpected"]
def score(key: ValueKey, extracted: Sequence[Extracted], *, tolerance: float = 0.0, digitized_tolerance: float = 0.0) -> dict[str, Any]
def timings(ws: Workspace) -> dict[str, Any]                       # per delivery, per stage, from runs.jsonl; the baseline: the reading queue's timestamps
def coverage_totals(ws: Workspace) -> dict[str, Any]               # files by state, regions, silent loss: the coverage files
                                                                   # (current) and each file's latest run line ("at run end")
def render(scored: dict[str, Any], *, timings: dict | None = None, coverage: dict | None = None, with_values: bool = False) -> str
    # Markdown. Default: counts, field names, verdicts and anchors only, studies by key-row number; no value, no study
    # label, no file name (the report is what leaves the server). with_values: expected and found values and labels, to
    # read on the server only
def main(argv: list[str] | None = None) -> int
    # python -m modeler_project.value_score --root R --project P [--tenant T] --key K.xlsx [--source ledger|stores]
    #   [--tolerance X] [--digitized-tolerance X] [--compare K2.xlsx] [--template OUT.xlsx] [--with-values] [--json]
    #   [--out F]; writes nothing in the root
# PM/key_compare.py
def compare(a: ValueKey, b: ValueKey) -> dict[str, Any]            # only_a, only_b, value_differs, unit_differs, where_differs, not_data_differs
def render_comparison(result: dict[str, Any]) -> str
```

Scoring rules: join on (study, arm, analyte, matrix, subject, field, time in minutes), **never on the anchor**; names
by `document_reading.name_key` and the key's `names`; the stores adapter has no arm (today it is part of the study
id), so a key's (study, arm) also matches the id `name_key(study + arm)`. Values: exact on the written decimal
(`Decimal(key) == Decimal(extracted)`, so `12.40` equals `12.4`). Nearest workable form of decision R for workbook
cells (§11.30): a workbook number cell's text is its stored value (§4.2: `12.4037` under a `0.00` format shows
`12.40`), so a value read from a workbook cell (method `cell`) that is not exactly equal but equals the key when
rounded half-even to the key's written decimals is `found_rounded`, counted apart from `found`; text cells, PDF and
Word stay exact. `tolerance` is relative and off by default; `digitized_tolerance` applies to values whose method is
`digitized`. A BLQ form expects `censored` (and the LLOQ when
the key writes `<0.5`); a missing token expects no value. Units through `canonical_unit`, else case-folded text.
`unexpected`: an extracted value in a (file, table) the key covers with no key row. Totals by field, by study and by
each `Studies` tag; omissions (`missing`) counted apart from errors. No pass threshold in code (G1 sets it after the
baseline). A key row the scorer cannot use is listed, never dropped.

Tests (`pytestmark = pytest.mark.req("T-47", "T-21")`):
- `test_value_key.py`: the template round-trips; a numeric cell in `value`, `time`, `subject` or `study` is refused
  with its cell; an unknown `field` is refused; the v1 YAML key still loads through `delivery_report.load_key`.
- `test_value_score.py`: the truth of the synthetic files, written into a ledger through `IntakeStore` and the
  contract models, scores 100 %; one wrong value, one wrong unit, one swapped subject pair, one omitted row and one
  extra value are each reported under the right verdict, field and study; BLQ and missing tokens; `12.40` against
  12.4; a workbook cell storing 12.4037 against a key `12.40` is `found_rounded`, a PDF `12.4037` against `12.40` is
  `wrong_value`; the tolerance only where asked; the stores adapter on a project built by `client_data.ingest`;
  timings and coverage sections from `runs.jsonl` and the coverage files; the CLI through `main([...])` with
  `capsys`; the default report holds no value and no study label of the key (asserted on every key value and label),
  `--with-values` holds them.
- `test_key_compare.py`: each class of disagreement; identical keys give none.

The ledger tests write the truth with `intake_fixtures.write_truth`.

Acceptance: `uv run pytest packages/project-model/tests/test_value_key.py packages/project-model/tests/test_value_score.py packages/project-model/tests/test_key_compare.py -q`.

Runbook (`value-key-runbook.md`): who writes the key (decision 8), where it lives on the server (never in the
repository), the baseline (`--source stores`, today's pipeline) and the new pipeline (`--source ledger`) on the same
project, and what lands (`--source stores` again after the Delivery confirmations: units, LLOQ and spreads change at
the landing), the two-analyst comparison and adjudication, what to send back (the default report, which holds no
value and no label, and the usage report; never the key, never a `--with-values` report).

Must not: write or commit a real key or report; import `modeler_agents`; change `delivery_report.py`.

### 8.2 D1a: landing fixes outside locked files (L-a, L-b, L-d, L-e)

Goal: stop losing BLQ counts, SE and CV%, the analyte and n per time on the way to the campaign, while every
existing fit, split and stored record stays as it is.

Owns (new): `PM/profile_landing.py`; `packages/project-model/tests/test_profile_landing.py`,
`packages/pbpk-domain/tests/test_error_type.py`, `services/orchestrator/tests/test_fit_error_type.py`.
Owns the edits below; no other parallel build touches these files.

| File | Change, exactly |
|---|---|
| `PM/datasets.py` | `Series.n_at: tuple[int | None, ...] | None = None` (n per time point, aligned with `times`; None: one n, in `n`). `check_dataset`: a wrong length is a `DatasetError`; the dataset's existing flags that start with `cross_file:` are kept (one line: today every flag is recomputed, which would erase the Delivery landing's join, §6.3 condition 5) |
| `PM/client_data.py` | `_series_from_summary` and `datasets_from_observations`: set `n_at` **only when the points' n are not all equal** (`n` stays the first non-null, as today). `_series_from_individuals`: a row with no concentration and no BLQ mark is left out of the series and named (`Issue("NO_VALUE", ...)`); `blq_flag: yes` on an empty cell is BLQ. Today both read as below the LLOQ. Nothing else |
| `PM/sheet_intake.py` | `_points`: the same `n_at`, as a key only when set |
| `PM/inputs.py` | `_profile`, `study_catalog`, and the `assemble` call that passes the parent's names (below) |
| `PM/plan.py` | `build_default`: `default_limitations` gains `profile_landing.landing_limitations(rows)` |
| `PD/units.py` | `normalize_profile`: when `profile.get("sd_type") == spread.GEOMETRIC_SD` the `sd` values are left unscaled (a geometric SD is a dimensionless factor); the verbatim `spread` key is never touched (it carries its own unit) |
| `PD/fit_spec.py` | `pi_observed(..., error_type: str | None = None)`: `observed["error_type"] = error_type` only when `sd` is non-empty and `error_type` is not None and not `spread.ARITHMETIC_SD`; a value outside `spread.ERROR_TYPES` is a `ValueError` |
| `services/orchestrator/.../campaign_activities.py` | `_build_fit_request`: `error_type=profile.get("sd_type")` (no literal: the name comes from the profile, which took it from `spread`) |

```python
# PM/profile_landing.py
def is_parent(analyte: str, parent_names: Collection[str]) -> bool      # name_key(analyte) in {name_key(w) for w in (*rules().landing.parent_words, *parent_names)}
def blq(series: Series) -> dict[str, Any] | None                        # {"rule": rules().landing.blq_rule, "omitted": k} when k > 0
def judged_sd(series: Series, kept: Sequence[int]) -> dict[str, Any]    # the profile keys below
def landing_limitations(rows: Sequence[Mapping[str, Any]]) -> tuple[str, ...]
```

`_profile` keeps choosing the first non-individual series and keeps `times`, `values`, `time_unit`, `unit`, `sd`,
`lloq` exactly as today for a series with an arithmetic `SD` or no spread and no BLQ. As today, `sd` is given only
when every kept point has a spread (never a None inside it). It adds keys **only when they
apply** (so an unaffected project's catalog content, and its hash, do not change):

| Case | Keys added to the profile |
|---|---|
| k points below the LLOQ left out | `"blq": {"rule": "omit", "omitted": k}` |
| arithmetic mean with SE, n known (that point's `n_at`, else `n`) | `"sd"` = SE × √n; `"sd_from": {"kind": "SE", "method": "se_times_sqrt_n", "n": "per_time" or "series", "version": "spread-1"}` |
| arithmetic mean with CV% | `"sd"` = CV% × mean / 100; `"sd_from": {"kind": "CV%", "method": "cv_percent_times_mean", "version": "spread-1"}` |
| SE with no n; any spread of a geometric mean other than `SD`; any spread of a median | no `sd`; `"spread": {"kind": ..., "values": [...], "unit": ...}` verbatim (its unit: the profile's source unit for SE, `%` for CV%, `""` for a geometric factor; `normalize_profile` never scales it); `"warnings": [...]` |
| geometric mean with `SD` | `"sd"` verbatim, `"sd_type"` = `rules().landing.geometric_sd_sent_as` (`GeometricStdDev`, the mapping `modeler_intake/pksim.py` already uses), a warning that the factor is sent as reported. The Delivery landing writes this pair only for a source that said geometric SD (§6.6); a legacy template row cannot say which (its `VARIABILITY` is SD, CV%, SE), so for legacy data the label stays an assumption, named in the warning (§11.5) |
| the series has `n_at` | `"n_at"` aligned with the kept points |

`study_catalog(ws, picked, *, parent_names: tuple[str, ...] = ())`: among datasets of one study id the parent's wins,
then plasma (the sort key gains `not is_parent(...)` and then `matrix != "plasma"` in front; today every dataset is a
parent in plasma, so no winner changes), and the note names what was left out ("`<sid>`: the `<matrix>` profile is
not used: the plasma one is"). The row gains, only when they apply: `measured_analyte` (not the parent),
`measured_matrix` (not plasma), `blq_rule` (the rule's name; the COUNT stays in `profile["blq"]`, so a blinded row,
whose profile `blinding.redact_row` removes, shows no count), and `joined_from` (when the dataset carries a
`cross_file:` flag). A row whose analyte is not the parent gets `evaluable: False`, **no `profile`**, and the note
"`<sid>`: a profile of `<analyte>`, not of the modelled compound: not evaluable without a model system". A blood or
serum row is judged as today and gets the note "`<sid>`: measured in `<matrix>`, judged against the plasma output".
`assemble` passes the brief's drug name and `drug.synonyms`. None of the new keys is a `StudyRecord` field, so
`plan._records` and `inputs.readiness` drop them as they drop `origin` today. The error-type names come from
`pbpk_domain.spread` (§4.8), never typed here.

Tests:
- `test_profile_landing.py` (`pytest.mark.req("T-49", "T-45", "T-47")`): each row of the table above; a profile and a
  catalog row of a parent, plasma, arithmetic-SD or no-spread, no-BLQ dataset are **equal to today's dicts** (pinned
  literally); the MS-01 split of a parent-only catalog is equal with and without the change, and equal for the parent
  rows when a metabolite row is added (`split_studies(_records(rows))`), with
  `{"measured_analyte", "measured_matrix", "blq_rule", "joined_from"}.isdisjoint(StudyRecord.model_fields)`; a
  metabolite dataset is listed, not evaluable, with its reason, and never wins over the parent's; a serum dataset
  keeps its profile and carries the warning, and a plasma dataset of the same study wins over a blood one whatever
  their creation order; `n_at` set only when n varies; an empty template concentration is no longer a BLQ point; a
  median with SE gives `spread` with its unit and a warning; a `cross_file:` flag survives `check_dataset` (and
  `set_study_facts`) and gives the row `joined_from`; `landing_limitations` names the BLQ rule, each conversion,
  each non-plasma matrix and each cross-file join.
- `test_error_type.py` (`pytest.mark.req("T-13")`): `pi_observed` for an arithmetic SD and for no SD is **byte-equal**
  to today's block (`json.dumps` compared with a literal); the key appears only for `GeometricStdDev`; another name is
  a `ValueError`; no value of the block is None; `normalize_profile` leaves a geometric factor and a verbatim `spread`
  unscaled and scales an arithmetic SD as today.
- `test_fit_error_type.py`: `_build_fit_request` on a geometric profile writes `error_type` into `pi_spec`; on today's
  fixture the spec bytes and `base_spec_sha256` are unchanged.

Existing tests: a read-only probe over the project-model, API and agents suites (764 tests) found **no** dataset
reaching `study_catalog` with a non-parent analyte, a non-plasma matrix, a BLQ in the judged series, SE, CV% or a
geometric mean; no template row with an empty concentration; no series whose n varies. So no existing test pins the
behaviour D1a changes, and these must stay green **untouched**: `test_inputs.py::test_a_complete_compound_assembles_
builds_and_is_accepted`, `test_client_data.py::test_a_filled_template_becomes_client_datasets_and_evidence_quoted_
from_their_rows`, `test_dataset_points.py::test_a_profiles_statistics_are_the_platforms_nca_of_its_points_below_the_
lloq_left_out`, `test_datasets.py::test_dataset_checks_and_the_nca_cross_check`, `test_sheet_intake.py::test_a_be_arm_
is_read_on_arrival_and_waits_on_its_study_for_what_the_sheet_does_not_say`, `test_fit_spec.py::test_build_fit_spec_
structure_and_path`, `::test_a_joint_fit_weighs_every_study_equally`, `test_units.py::test_profile_in_hours_and_ng_
per_ml_becomes_minutes_and_umol_per_l`, `test_split.py` (all), `test_metabolite_stage.py::test_each_analyte_is_split_
on_its_own`, `test_build_round_activity.py::test_fit_action_emits_a_fit_request`, `::test_fit_on_a_molar_profile_
declares_the_molar_dimension`, `test_write_api.py::test_prepare_converts_observed_data_to_engine_units`, `test_plan_
api.py` (all). The one existing test that changes: `tests/architecture/test_openapi_contract.py::test_openapi_matches_
the_committed_contract` fails on the D1a branch, naming exactly `Series.n_at`; the integrator refreshes the snapshot
and the web types at the merge. The e2e specs were not run here: D1a checks `apps/web/e2e/fixtures/*.py` for a
non-parent analyte before handing over.

Acceptance: `uv run pytest packages/project-model/tests packages/pbpk-domain/tests services/orchestrator/tests/test_build_round_activity.py services/orchestrator/tests/test_fit_error_type.py services/api/tests/test_plan_api.py services/api/tests/test_write_api.py -q`;
`uv run pytest tests/architecture -q` with only the OpenAPI test failing as described.

Must not: touch `run_pi.R`, `split.py`, `map.py` or any locked file; set a residual weighting; offer another BLQ rule;
put a None in the PI spec; convert a geometric spread; add a key to `StudyRecord`; change `dataset_points.py`,
`blinding.py` (`n_at` holds counts, not values: nothing to redact) or any view; make a urine dataset.

### 8.3 D1b: `run_pi.R` labels the error type (L-c; locked; its own branch and PR)

Goal: the engine labels an observed error with its true type when the spec says so. Nothing else.

Owns: `services/engine-worker/r/run_pi.R` (`build_dataset` only), `docs/architecture/locked-files.json` (that file's
hash, by `UPDATE_LOCKED=1 uv run pytest tests/architecture/test_locked_files.py`), and, because it is its own PR, its
own CHANGELOG entry. Branch from `origin/main`; not merged with the others; merged only with the owner's approval,
a named reviewer who owns `run_pi.R`, and one engineer who did not write it (decision 7).

```r
  if (!is.null(sd)) {
    # the spec names the type only when it is not arithmetic (pbpk_domain.fit_spec.pi_observed): absent = as before.
    # The two names are pbpk_domain.spread.ERROR_TYPES (harvested from the golden fixtures); anything else stops.
    error_type <- if (!is.null(observed$error_type)) observed$error_type else "ArithmeticStdDev"
    if (!(error_type %in% c("ArithmeticStdDev", "GeometricStdDev"))) stop(paste("unknown error_type:", error_type))
    dataset$yErrorType <- error_type
    if (error_type == "ArithmeticStdDev") dataset$yErrorUnit <- observed$unit  # a geometric SD is dimensionless
  }
```

`"GeometricStdDev"` is in the repository only as a snapshot `AuxiliaryType` (the golden fixtures) and in
`modeler_intake/pksim.py`; as an R `yErrorType` it was read in the ospsuite 12.4.4 source (`DataErrorType`), not run:
this container has no R. So the PR's evidence is produced on the server, with the image rebuilt from
`services/engine-worker/Dockerfile`:
1. the engine-image gate (`engine-image.yml`) green;
2. before/after record (plan §10.1 item 2): for one fixture with an arithmetic SD, the `pi_spec` bytes, the dataset's
   `yErrorType` and unit, the objective and the estimates, identical before and after;
3. the same fixture with `error_type: "GeometricStdDev"`: `yErrorType` reads back `GeometricStdDev`, no error unit is
   set, and the objective equals the arithmetic-labelled run (the PI package's default residual weighting is "none",
   so the error does not enter the objective: this run is what confirms it on the engine);
4. rollback: revert the commit and the hash; the Python side keeps sending the key, which the old script ignores.

Must not: set `objectiveFunctionOptions` or any weighting (an SME decision, §11.4); touch `golden/**`, the Dockerfile
or any Python file.

### 8.4 D2: the source model (G2, R-a to R-f)

Goal: one parse per file into a structure-preserving model with immutable anchors; nothing located is lost.

Owns: `DI/source/*` (the files of §3), `PM/format_inventory.py`, `packages/data-intake/tests/test_source_*.py`,
`packages/data-intake/tests/test_anchor_resolve.py`, `packages/project-model/tests/test_format_inventory.py`.
Shared files: none. Implements §6.1.

Tests (`pytestmark = pytest.mark.req("T-47")`), each against `modeler_intake.synthetic` and its truth:
- `test_source_workbook.py`: every table of the messy workbook is its own region with the truth's range (two tables
  on one sheet, side-by-side blocks, a Mean / SD / N group joined across one empty row and noted, a second table
  after a caption not joined); a merged two-row header keeps its origin and its copies are not counted; every truth
  value's cell has the truth's text (a computed 12.4037 shown as `12.40` has text `12.4037`); `Region.numeric_cells`
  counts "12.3 (4.5)" and "12.3*" cells; the context lines above and below are the truth's and hold no other region's
  cell; values and merge copies equal `grid.read_workbook_bytes` for the same bytes and for
  `fixtures/legacy-study.xls`; a `0.0%` format is kept; a hidden sheet is flagged; a corrupt `.xlsx` is `unreadable`
  with its reason, not an exception.
- `test_source_delimited.py`: `;` with decimal commas in cp1252; tab; UTF-16 with BOM; the encoding and delimiter
  are recorded.
- `test_source_pdf.py`: words carry boxes inside the page; each ruled table's cells equal the truth; the table
  continued over two pages (its title repeated "(continued)") is one region with two parts, each with its caption,
  and its repeated header dropped once; two tables with the same header on consecutive pages under different captions
  stay two regions; a PDF region id does not change when an extra table is found on the page; text outside the tables
  is listed by page and the page number is furniture; the scanned page has `needs_ocr` and the document is
  `partly_read` naming it; an unruled table is a `table_like_text` region; a stub `PdfTableEngine` and a stub
  `OcrEngine` passed in are used.
- `test_source_docx.py`: tables as grids (a merged header once, with its span; a line break inside a cell stays in
  the cell), paragraphs in order, the image listed as a figure.
- `test_source_archive.py`: members with their container; one nested level; the limits; an encrypted ZIP.
- `test_source_unsupported.py`: `.doc`, `.pptx`, `.xpt`, `.msg`, an empty file, a file over `MAX_BYTES`: a state and a
  reason, never an exception; parsing the same bytes twice gives equal documents (`modeler_intake.anchors.sha256_of`
  equal: the L2 function, so the test imports nothing of `modeler_project`).
- `test_source_roles.py`: document role and table kind by rule, with the evidence cell.
- `test_anchor_resolve.py`: every truth value's anchor resolves to its text (PDF anchors compared by identity, never by
  box); a wrong sha256, version or cell raises `AnchorError`; `check_anchors` across a version bump finds every value
  again, and reports a moved or changed one; `source_view` highlights the anchored cell and, with `also`, its time,
  unit and label cells with their roles, and gives page, page size and box for a PDF.
- `test_source_inventory.py`, `test_format_inventory.py`: counts by extension, native against scanned PDFs, documents
  with figures; the CLI over a read root prints the report and writes nothing.

Acceptance: `uv run pytest packages/data-intake/tests -q --deselect packages/data-intake/tests/test_intake.py::test_vault_is_content_addressed_write_once_and_verifiable`;
`uv run pytest packages/project-model/tests/test_format_inventory.py -q`.

Must not: edit `grid.py`, `documents.py`, `triage.py` or any existing module; call an LLM; add a dependency (encoding
by the standard library); register an OCR or second table engine; read `modeler_project`; keep module-level
registries.

### 8.5 D3: the mapper (U-a, U-b, U-e, U-f)

Goal: a typed mapping per table, executed by code over any source format; rules and the cache before the LLM; the LLM
never sees a number of the body; prose facts under the strict check.

Owns: `DI/mapping/*`, `PM/mapping_cache.py`, `AG/table_mapper.py`, `AG/prose_extractor.py`, `AG/evals/scripted.py`;
tests `packages/data-intake/tests/test_mapping_*.py`, `packages/data-intake/tests/test_prose_check.py`,
`packages/project-model/tests/test_mapping_cache.py`, `services/agents/tests/{test_table_mapper,test_prose_extractor}.py`.
Shared files: none (`agent_jobs.py` is W's). Implements §6.2. Grids in tests come from `RegionGrid.from_rows` on the
truth tables of `modeler_intake.synthetic` (D2's parser is not in your worktree).

Tests (`pytest.mark.req("T-47")`; the agents' files `pytest.mark.req("T-47", "T-21")`):
- `test_mapping_execute.py`: each layout; every truth value of the synthetic tables comes out with its truth locator;
  BLQ, `<0.5` (with its LLOQ), `NS`; Mean, SD and N rows become a mean series with spread and n per time; a second
  spread column with `of`; per-column units; decimal commas including the ambiguous `1.5`; a `%` number format;
  `cell_use` covers every non-empty cell and an unmapped numeric cell is `unaccounted`; a non-numeric SD cell is a
  finding, not an exception.
- `test_mapping_validate.py`: one test per finding code of §6.2.
- `test_mapping_rules.py`: for each of the 11 `reading_eval.CASES`, `from_sheet_form(suggest(...))` executed on the
  sheet's region gives the same (series, time, value, BLQ) set as `apply_recipe` on today's recipe; no unstated
  default (unit, matrix, route, study id from the file name) is in the spec; `template_spec` reads a filled template
  sheet exactly.
- `test_mapping_fingerprint.py`: equal under another sheet name, another offset, other subject numbers and other
  sampling times; different with one more column or another header word.
- `test_mapping_redact.py`: no digit of any body cell of any synthetic table is in the redacted payload; the header
  and caption are verbatim; `distinct_texts` shows `BLQ` and `NS`.
- `test_prose_check.py`: the label and exactly one number in the clause; "mean 12.4 (SD 3.1)" refused for a mean
  when the clause holds two numbers of the class; the times-100 reading refused; the unit parsed by code; a name by
  `text_in`; a choice by `supports_choice`; the locator spans the number.
- `test_mapping_cache.py` (also `"T-05"`): propose, approve, reject, versions; `lookup` prefers the approved version;
  the chain verifies and an edited line is found; one audit event per decision carrying the spec's hash.
- `test_table_mapper.py`: a scripted model's valid spec is accepted; an invalid one is answered `REJECTED` with the
  findings and a corrected one accepted; a spec that types a number is refused; the user message holds no digit of the
  body; `INCOMPLETE` gives no spec.
- `test_prose_extractor.py`: only facts the check accepts are returned; a refused fact's reason is in the answers; a
  table's text is never in the input.

Acceptance: `uv run pytest packages/data-intake/tests packages/project-model/tests/test_mapping_cache.py services/agents/tests/test_table_mapper.py services/agents/tests/test_prose_extractor.py -q`
(with the vault test deselected).

Must not: edit `recipe.py`, `apply.py`, `sheet_form.py`, `recipe_review.py`, `sheet_reader.py`, `document_reader.py`;
reuse `apply.parse_numeric` or `citations.value_stated_in_quote` for the new checks; let a function in `AG` take a
`RegionGrid` or a `SourceDocument`; add an agent id; import `modeler_storage` or `modeler_contracts` in `AG`.

### 8.6 D4: the ledger (G3, U-c, L-g, L-h)

Goal: the long-form, append-only record of every value with its anchor: partial facts, entities, conflicts, derived,
relation and cross-file facts.

Owns: `PM/{ledger,ledger_entities,ledger_compute,ledger_links}.py`; tests
`packages/project-model/tests/test_ledger*.py`. Shared files: none. Implements §6.3 on `IntakeStore`, `LedgerView`
and the models of §4.5. Inputs in tests are `ExtractResult`s built by hand from the synthetic truth.

Tests (`pytestmark = pytest.mark.req("T-47", "T-05")`):
- `test_ledger.py`: a recorded extraction gives one extract whose every value has its own locator and a stable id
  (`tx-...#i`); recording it again adds nothing; a new mapping version supersedes the earlier extract; a fact with no
  study is kept; `enter` with `supersedes` leaves the old fact readable and marks it superseded; `exclude` needs a
  reason; the chains verify; no audit event per fact (`intake.entry` only for a person's entry).
- `test_ledger_entities.py`: the same name written three ways is one entity; an alias a person confirmed in today's
  review record is reused; two similar but different names stay two; an arm resolves inside its study; `merge` keeps
  both ids resolvable.
- `test_ledger_conflicts.py`: both values kept and listed; a unit conflict is not converted; solubility at two pH is
  not a conflict; after a `Choice` the others are excluded.
- `test_ledger_derived.py`: SD from SE with n per time, then with the series' n; none without n; from CV%; nothing
  for a geometric mean; each derived fact names its inputs and `compute`; `derive` twice adds nothing; superseding an
  input supersedes the derived fact.
- `test_ledger_cross_file.py`: one test per condition (no anchored link → nothing; two candidates → a pending link,
  nothing filled; the filled fact carries its three anchors; unconfirmed until a `LinkConfirmation`, then inherited by
  a later fill through the same link; `cross_file` on the value's view).
- `test_ledger_relations.py`: a DDI ratio with its 90 % CI links two arms.

Acceptance: `uv run pytest packages/project-model/tests/test_ledger.py packages/project-model/tests/test_ledger_entities.py packages/project-model/tests/test_ledger_conflicts.py packages/project-model/tests/test_ledger_derived.py packages/project-model/tests/test_ledger_cross_file.py packages/project-model/tests/test_ledger_relations.py packages/project-model/tests/test_intake_store.py -q`.

Must not: commit an artifact or add an `ArtifactKind`; write to `client_review`'s record (read aliases through
`client_data.review_record`); merge entities by similarity; store a status or a confidence on a fact; make a dataset.

### 8.7 D5: checks and the coverage audit (G2, G4, G5)

Goal: make "no silent loss" a number, judge requirements per study with the schema gap, and return every validity
finding as a typed result a scientist can override.

Owns: `PM/{coverage,study_routing,study_requirements,intake_checks,scorecard}.py`; tests
`packages/project-model/tests/{test_coverage,test_study_routing,test_study_requirements,test_intake_checks,test_scorecard}.py`.
Shared files: none (`intake_rules.yaml` is C's: ask the integrator for a change). Implements §6.4 against
`LedgerReader` (tests use `LedgerView` over lines written through `IntakeStore`, and a small fake for `conflicts`).

Tests (`pytestmark = pytest.mark.req("T-47", "T-42")`):
- `test_coverage.py`: a fully mapped table has silent loss 0; one unaccounted numeric cell counts 1 and is named; an
  unread table counts all its numeric cells; a `not_data` mapping and a `RegionDecision` exclude with their reason; a
  figure is excluded by the rule; unread prose is listed, not counted; outside items and unresolved anchors are in the
  summary; an unsupported file is a coverage row with its reason.
- `test_study_routing.py`: an adult oral fasted study in a VBE project activates the core and the VBE template; a
  pediatric study in the same project also activates the special-populations template; a fed study the food-effect
  one, and a fasted study of a food-effect project is **not** treated as fed; route `other`, a genotype study and a
  large molecule are schema gaps; a study with no route fact is a gap.
- `test_study_requirements.py`: found, conflicting, missing, then each disposition; a per-product item keeps its `@`
  id; project-scope items are not a study's; every `req_id` of `item_scope` and `item_fields` exists in the loaded
  templates (the rules file cannot drift from the locked YAMLs); `request_lines` gives one line per missing item.
- `test_intake_checks.py`: one test per code of `CHECKS`; `set(CHECKS)` equals the codes of `checks.severity`; blood
  or serum fails `MATRIX_NOT_PLASMA`; a unit outside the tables fails `UNIT_NOT_IN_TABLES` and the value is unchanged;
  a check id is stable across two runs and changes when its values change.
- `test_scorecard.py`: blockers for silent loss, a gap, a failed check, an open conflict, an unconfirmed link; an
  override clears its check and stays listed; a gap is not cleared by an override.

Acceptance: the five test files; `packages/project-model/tests/test_requirements.py` still green.

Must not: edit `requirements.py`, the templates or `client_data.reconcile`; put a threshold in code; invent a
template id, an APP code or a PK-Sim name; refuse or rename a unit; call `requirements.evaluate_when` with the brief's
food state for a study.

### 8.8 SD: three inert draft checklists

Goal: for biologics, dermal and ocular, what to ask of the client and how to check it, as drafts no project can
select and no gate reads.

Owns: `PD/requirement_drafts/{__init__.py,biologics.yaml,dermal.yaml,ocular.yaml}`,
`packages/project-model/tests/test_requirement_drafts.py` (it needs `requirements.load_templates`, which L0 tests
cannot import). Shared files: none.

Each file: a comment block saying it is a draft and why it is inert; `id: req-draft-<name>`; `version: "0.1-draft"`;
`status: "DRAFT / UNVERIFIED"`; `applies_to: []`; `engine_support:` one honest sentence (biologics: "PK-Sim has a
large-molecule model; the harvested catalog has no FcRn entry, so nothing here can be placed today"; dermal and
ocular: "no hit in the harvested catalog: PK-Sim has no built-in model; an engine decision comes first");
`named_scientist: null`; `items:` in the requirement-item schema (`id` starting `REQ-DRAFT-`, `label`, `kind`,
`target`, `group`, `criticality`, optional `unit`, `conditions`, `note`, `needed_for`), every item with
`pksim_status: TO_HARVEST` and **no `pksim` key**; every `kind: parameter` target starts with `draft.` (no CPF id is
claimed). No calculator, no default value, no acceptance threshold.

Test (`pytest.mark.req("T-42")`): the three files load as YAML; mandatory keys present; ids unique and all
`REQ-DRAFT-`; `applies_to == []`; status as above; no `pksim` key anywhere; no parameter target is a registry id;
`requirements.load_templates()` returns six templates and none of the draft ids; `derive` on a brief with every
application picked contains no `REQ-DRAFT-` item; `importlib.resources.files("pbpk_domain.requirement_drafts")` holds
exactly the three files.

Acceptance: the test; `uv run pytest tests/architecture/test_locked_files.py tests/architecture/test_parameter_characterization.py -q` green.

Must not: put a file in `pbpk_domain/requirements/`; give a PK-Sim name, path or unit; add an APP code.

### 8.9 W: wiring (after the merge)

Goal: the switch, the arrival hook, the run queue with per-stage times (G7), the `intake` job, the two LLM stages
behind the seam. Built on the merged D2 to D5.

Owns (new): `PM/intake_files.py`, `PM/intake_pipeline.py`, `API/intake_pipeline_jobs.py`; tests
`packages/project-model/tests/{test_intake_files,test_intake_pipeline}.py`,
`services/api/tests/test_intake_pipeline_api.py`.

Edits (W's alone at this stage):
- `API/config.py`: the field of §2. `deploy/server/modeler-secrets.env.example`: the variable, commented.
- `API/jobs.py`: `Kind` gains `"intake"`.
- `API/agent_jobs.py`: `table_mapping(model, **kw)` and `prose_extraction(model, **kw)`, each importing its agent
  inside the function (copy `sheet_reading`).
- `API/client_api.py` (`upload_client_files`), `API/brief_api.py` (`_read_client_file`), `API/intake_jobs.py`
  (`ingest_for_reading`): open one delivery per request and call `intake_pipeline_jobs.receive(..., ingest=ingest)`
  in place of `ingest(...)`; `intake_jobs.read_later` ends with `intake_pipeline_jobs.kick`; the upload's refused
  branch kicks too. Answers, status codes and messages unchanged. In `both`, `ingest_for_reading` hands a `.zip` to
  `receive` (which expands it) instead of answering "not read for data".
- `services/api/tests/conftest.py`: the autouse fixture of §2.

Implements §6.5. `ports` wraps each LLM call in an `agent_jobs.AgentRun` (`agent="A4-table-mapper"` or `"A4-prose"`,
`model`, `max_turns`), logs steps with `"type"` keys under a lock, runs up to 4 table conversations at once
(`ThreadPoolExecutor`, the `run_research_per_input` pattern), and records `ModelUse` (provider, model, prompt hash,
run id). A cache or rule mapping makes no agent run.

Tests:
- `test_intake_files.py` (`T-47`, `T-05`): bytes stored before the line; a repeat; a container; the chain.
- `test_intake_pipeline.py` (`T-47`): with no model, each synthetic file's ledger values equal its truth, value by
  value, each resolving through its anchor (`value_score.score` gives 100 %); every stage has a time; a parser that raises
  fails that run at `parse` and the next file still runs; an unsupported file ends `done` with its state and reason;
  a second run of the same file adds nothing; a bumped parser version re-parses, checks the anchors and reports the
  counts; the mapping order (cache, rule, then unread with the reason); a second file with the same layout under
  another sheet name is mapped by the cache; `sweep` queues stored files once.
- `test_intake_pipeline_api.py` (`T-47`, `T-20`), with `api_settings(read_root=..., intake_pipeline="both")`: the
  upload answer equals the `legacy` answer for the same files (a workbook, a PDF, the template, a broken file: same
  422 and detail); the broken and the unsupported file are in `files.jsonl` with the reason and their bytes are in the
  store; the `intake` job runs with agents off; with a scripted model (`modeler_agents.evals.scripted.Scripted`) a
  first-seen table is mapped by a run named `A4-table-mapper` counted under A4, and its prompt holds no body digit;
  in `legacy` nothing is written under `intake/`; one `intake.run` audit event per run with the line's hash.

Acceptance: `make test` with only the 15 baseline failures; `uv run ruff check .`; `tests/architecture` green; the
existing e2e specs green with the default `both` (`npm --prefix apps/web run e2e`, where a browser is installed; else
the integrator runs them before D6 starts).

Must not: change `kick` or `drain` of the legacy `reading` job, the reading queue, `QueueTask`, or a legacy answer;
call `modeler_agents` outside `agent_jobs`; parse in the upload request; add a route (D6).

### 8.10 D6: review by exception (after W; G6, U-d)

Goal: the Delivery section: coverage, exceptions first, the source beside every value, mapping accept, spot check,
signed confirmation, landing; pipeline health for the administrator.

Owns (new): `PM/{intake_review,intake_landing,intake_health}.py`; `API/delivery_routes.py`, `API/views/delivery.py`;
`WEB/components/delivery/*`, `WEB/app/styles/delivery.css`, `WEB/app/admin/pipeline/page.tsx`,
`WEB/e2e/delivery.spec.ts`, `WEB/e2e/fixtures/delivery.py`; tests
`packages/project-model/tests/{test_intake_review,test_intake_landing,test_intake_health}.py`,
`services/api/tests/{test_delivery_api,test_admin_pipeline}.py`.

Edits: `API/client_api.py` (one line: `delivery_routes.mount(router)`; the three guards of §2); `API/admin_api.py`
and `API/views/admin.py` (one route, one model); `PM/datasets.py` (`Series.error: tuple[float | None, ...] | None`,
so a BLQ row without a spread no longer drops the series' spread), `PM/client_data.py` and `PM/sheet_intake.py` (the
three all-or-nothing drops), `API/views/client_data.py` (`SeriesPoints.error` nullable entries; `DatasetPoints` gains
`blq_rule: str | None`, `blq_omitted: int`), `PM/dataset_points.py` (fills them), `WEB/components/inputs/
DatasetView.tsx` (shows them; null-safe errors), `WEB/components/inputs/InputsWorkspace.tsx` (one slot beside
`ReadingTray`), `WEB/app/layout.tsx` (the stylesheet, before `design.css`), `WEB/lib/admin.ts`,
`WEB/components/admin/AdminParts.tsx`, `WEB/e2e/admin-console.spec.ts` (the address), the upload accept lists.

`delivery_routes.py` defines module-level handlers and `def mount(router: APIRouter) -> None`, and never calls
`APIRouter(...)`: the routes then belong to `client_api.router`, so the locked response ratchet
(`test_response_models.py`) covers them with no locked change, and no router imports a router. Every handler:
`workspace_for`, a response model in `views/delivery.py` (a `View`, every key declared, `Number = int | float`),
`envelope(...)`. Prefix `/api/v1/projects/{project_id}`.

| Route | Role | Answer (`views/delivery.py`) |
|---|---|---|
| GET `/delivery` (runs `sweep` and `kick` in `both`) | Reader | `DeliveryPage`: `enabled`, `running`, `agents`, deliveries with their files (state, reason, coverage summary, run state, stage times), totals (files by state, regions, silent loss), studies and products (label, counts, blockers, confirmation, `loaded_elsewhere`, `confirm_on`), mappings waiting, request lines |
| GET `/delivery/studies/{study}`, `/delivery/products/{product}` | Reader | `DeliverySubject`: the scorecard with exceptions first (gaps, failed checks, conflicts, links, missing items, new mappings), values grouped by table, spot-check state, confirmation with its signature manifestation |
| GET `/delivery/source?value=<id>` or `?anchor=<text>` | Reader | `DeliverySource`: a `SourceView` (§4.2) plus `file`, `sha256`, `value_id` |
| GET `/delivery/mappings/{mapping_id}` | Reader | `DeliveryMapping`: header → role, field, unit, tokens, rules; the redacted sample; versions and decisions |
| POST `/delivery/mappings/{mapping_id}:approve`, `:reject`, `:edit` | Writer | `DeliveryMapping` (`:edit` stores a person's version and queues the file's run again) |
| POST `/delivery/studies/{study}:override`, `:dispose`, `:choose`, `:link`, `:enter`; POST `/delivery/regions:exclude` | Writer | `DeliverySubject` (regions: `DeliveryPage`) |
| POST `/delivery/studies/{study}/spot-check:draw` | Writer | `DeliverySpotCheck`: the draw; each value with its source reference |
| POST `/delivery/studies/{study}/spot-check` (all ticks, once) | Writer | `DeliverySpotCheck` |
| POST `/delivery/studies/{study}:confirm`, `/delivery/products/{product}:confirm` | Writer, step-up | `DeliverySubject` with `signature {signature_id, manifestation}` |
| POST `/delivery:run` (`{files?}`), 202 | Writer | `TriageStart` (existing) |
| GET `/api/v1/admin/pipeline` (`admin_api`, guard `Admin`, an `admin.view` event) | Admin | `PipelineHealth`: per company and in all: files by state, mapping source shares (cache, rule, LLM, unread), parser failures, unsupported by extension, outside items, unresolved anchors, pages needing OCR, stage time median and p90 |

Blinding (D-15): `blinded_subjects` = studies whose `intended_use` is one of `blinding.EXTERNAL_PURPOSES` while
`blinding.setting` is on and no MAP is signed, plus the studies of landed datasets in `blinding.blinded_studies`. For
such a study every route above withholds `value`, `verbatim`, spreads and LLOQ (`None`, `blinded: true`), as
`blinding.redact_dataset` does, and `/delivery/source` blanks every numeric cell of a region that holds a value of a
blinded study. Its spot check cannot be drawn and its confirmation is refused with `BLINDED` (§11.1).

Web: `components/delivery/` holds `DeliverySection` (the coverage panel: files, regions, silent loss, requirement
status; polls while running), `SubjectCard` (exceptions first; `useTableView`'s `keep` rows), `ValueSource` (a grid
with the anchored cell highlighted; for a PDF the page drawn with pdfjs and the box over it, as `Digitizer.tsx`
does, scaled by `page_size`; prose with the span marked), `MappingReview`, `SpotCheck` (ticks in local state, one
submit), `ConfirmDialog` (`Dialog size="narrow"`, says what is signed; step-up is handled by `withSession`). Reads
with `useResource`, writes with `useMutation` and `send`; types from `Schema<"...">`; a `data-testid` on every
element a spec uses (`delivery-file-${id}`, `delivery-subject-${id}`, `delivery-value-${id}`, `spot-tick-${id}`,
`delivery-confirm-${id}`); no inline static style; colours from tokens. The legacy cards and their test ids are not
touched.

Tests:
- `test_intake_review.py` (`T-47`, `T-05`): the draw is the same for the same ledger state and differs after a
  change; strata and `always` as specified; a study with fewer values than `size` is checked whole; ticks are
  accepted once; a failed tick blocks; a correction makes the draw stale and the next draw carries the unchanged
  ticks; every blocker; `bound_record` changes when a value, a mapping version, an override, a disposition, the spot
  check, the coverage or a requirement status changes; one audit event per decision with the line's hash.
- `test_intake_landing.py` (`T-47`, `T-45`, `T-48`): a confirmed study becomes accepted client datasets whose values
  equal the truth; the sheets count as read for `sheet_intake` and their legacy drafts are gone; a proposed legacy
  dataset of the same study is rejected with the reason; an accepted one refuses the confirmation; a second `land` of
  the same confirmation writes nothing; dissolution records become profiles through the register; a cross-file fact
  is flagged on the dataset; `plan_landing` names a missing `StudyRecord` field instead of raising later.
- `test_delivery_api.py` (`T-47`, `T-05`, `T-50`), `api_settings(read_root=str(tmp_path), intake_pipeline="both")`:
  each route's happy path and refusals; the confirm route answers 403 `STEP_UP_REQUIRED` without step-up, and with it
  writes `signature.create`, `intake.confirm` and `intake.land`; nothing is signed when a blocker exists; a blinded
  study's values and source cells are withheld on every route; the legacy `client-review:confirm` refuses what
  Delivery confirmed; in `legacy` the page answers `enabled: false`; no legacy route's answer changes.
- `test_intake_health.py`, `test_admin_pipeline.py` (`T-05`): the counters from run lines of two companies; the route
  needs `Admin` and leaves an `admin.view` event.
- `e2e/delivery.spec.ts`: upload the synthetic workbook and PDF, see the coverage panel with silent loss 0, open a
  value's source with its cell highlighted, accept a mapping, tick the spot check, confirm, and see the study loaded
  on Inputs once.

Acceptance: `make test`, `make lint`, `UPDATE_SNAPSHOTS=1 uv run pytest tests/architecture/test_openapi_contract.py`
then `npm --prefix apps/web run api-types` (in the worktree; the integrator regenerates both at the merge, §9),
`npm --prefix apps/web run typecheck`, `npm --prefix apps/web run build`, `npm --prefix apps/web run e2e`.

Must not: add an `APIRouter`; send one request per tick; sign before every refusal has been checked; write a dataset,
evidence item or submission except through its owner; change a legacy card or test id; show a blinded value.

## 9. The shared-file protocol

- **Only the integrator edits**: `CHANGELOG.md`, `docs/CONTINUATION_PACKAGE.md`, `docs/api/openapi.json`,
  `apps/web/lib/api-types.ts`, every `pyproject.toml`, `uv.lock`, `PM/intake_rules.yaml`, and this file.
- Each builder returns, as text: its CHANGELOG entry (what changed, why, impact; science changes named as such), the
  files it created and edited, the tests it added, its acceptance output, and anything it had to assume.
- Merge order: C, then D0, D2, D3, D4, D5, SD and D1a in any order (they share no file). After D1a the integrator
  refreshes the OpenAPI snapshot (`UPDATE_SNAPSHOTS=1 uv run pytest tests/architecture/test_openapi_contract.py`) and
  the web types (`npm --prefix apps/web run api-types`) for `Series.n_at`, in the commit that carries D1a's CHANGELOG
  entry. Then W, then D6, one at a time on the integration line. D6 changes the API contract: it regenerates the
  snapshot and the web types in its worktree to build against, and the integrator regenerates them again at the merge
  (they are generated files: never merged by hand). The integrator updates §4.1 of the continuation document when a
  stage changes status and adds the session row to the CHANGELOG table.
- D1b is not part of this merge: its own branch from `origin/main`, its own PR with its own CHANGELOG entry and the
  refreshed hash, merged by the owner's approval only.
- A builder who finds the contract wrong stops and reports it; nobody widens a model, adds a field to a shared record
  or edits another build's file on their own. A fix to §4 to §6 is made once, by the integrator, in the contract code.

## 10. Test strategy

- **Shared synthetic files** (`DI/synthetic.py`, C), each built in memory and returned with its truth, so every build
  tests against the same files without needing another build's code:

```python
DRUG = "Exampleamide"
@dataclass(frozen=True)
class TruthTable: id: str; kind: TableKind; where: str; rows: tuple[tuple[str, ...], ...]; header_rows: int
                  merges: tuple[str, ...] = (); pages: tuple[int, ...] = ()        # rows: cell texts as written, "" empty
@dataclass(frozen=True)
class TruthValue: table: str; field: str; study: str; arm: str; analyte: str; matrix: str; subject: str
                  time: str; time_unit: str; value: str; unit: str; locator: str  # value as written (BLQ, <0.5, NS included)
@dataclass(frozen=True)
class SyntheticFile: name: str; data: bytes; format: FileFormat; tables: tuple[TruthTable, ...]; values: tuple[TruthValue, ...]
                     outside: tuple[str, ...] = (); prose: tuple[str, ...] = (); notes: str = ""
def messy_workbook() -> SyntheticFile    # sheet 1: a title cell, an individual table with a merged two-row header, BLQ, <0.5 and NS,
                                         # Mean / SD / N rows, then a gap and a second (summary, SE) table; sheet 2: two dissolution
                                         # blocks side by side; a footnote; a hidden sheet
def pdf_report() -> SyntheticFile        # page 1: a synopsis in sentences (dose, n, route, fasted); page 2-3: one ruled table continued
                                         # with its header repeated; page 3: a second ruled table and a footnote; page 4: an unruled table
def scanned_pdf() -> SyntheticFile       # one text page, one page that is only an image
def word_report() -> SyntheticFile       # design sentences, a table with a merged header, an image
def delimited(sep: str = ";", decimal_comma: bool = True, encoding: str = "cp1252") -> SyntheticFile
def zipped(*files: SyntheticFile, name: str = "delivery.zip") -> SyntheticFile
def template_workbook() -> SyntheticFile # a filled client-data template (client_template.build_template)
def delivery() -> tuple[SyntheticFile, ...]   # the set W, D0 and D6 run end to end
```

  The PDF is written by hand (text and ruling lines as content-stream operators, Helvetica, latin-1), as
  `delivery_eval.synthetic_pdf` does; C's contract test proves pdfplumber finds its tables and words.
- **Unit tests per build** against the truth (`RegionGrid.from_rows` for D3; hand-built `ExtractResult`s for D4;
  `LedgerView` over written lines for D0 and D5). **End to end** in W: every truth value of `delivery()` is in the
  ledger with an anchor that resolves to its text, scored by D0 at 100 %, with agents off.
- **LLM**: always `modeler_agents.evals.scripted.Scripted`; tests assert on the tool answers (`ACCEPTED`,
  `REJECTED: ...`), because `run_tool_loop` never raises a handler error. A redaction test in D3 and again in W reads
  the messages the scripted model received. No live model in the suite; D0 scores a live model on the server.
- **No PK-Sim**: nothing here runs the engine. D1a's proof is byte equality of today's specs; D1b's evidence is
  produced on the server (§8.3). `deploy/dev/stub_engine.py` and `analytical_engine.py` ignore the new key and prove
  nothing about it.
- **Not testable in this container, so given an interface only**: OCR (`OcrEngine`), a second PDF table engine
  (`PdfTableEngine`; Docling's weights cannot be fetched), a live LLM, PK-Sim, the step-up dialog (the DEV verifier
  always carries a fresh loa2), the admin page in the standard e2e (the DEV principal is not an administrator: API
  tests only).
- **Chains and audit**: every store test tampers with a line and expects `verify` to find it; every decision test
  counts audit events (one per decision, none per fact).
- Markers: `T-47` on all intake tests; `T-21` on agent and scorer tests; `T-05` where a chain, an audit event or a
  signature is asserted; `T-42` for requirements; `T-13`, `T-45`, `T-49` in D1a. No new requirement id (the list is
  locked).

## 11. Risks and open questions for the lead

Where a decision of the lead does not fit the code as stated, the nearest workable form is given.

1. **Blinded studies against the spot check (decisions P and E).** P withholds a blinded study's values on every new
   route; the spot check needs them. As specified, a blinded study cannot be spot-checked, so it cannot be confirmed
   on Delivery before the MAP is signed; it can still be confirmed on the legacy card (unsigned, values withheld), as
   today. *Recommended:* keep that for this build and ask the owner whether a spot check of a blinded study may show
   its values to the one person doing it, recorded as such (`saw_blinded_values` on the record and the audit event).
2. **The legacy `reading` job is not changed (decision B).** Making `intake_jobs.kick` start with no model changes
   today's behaviour and its tests. *Workable form, specified:* a second job kind `intake` with its own queue
   (`runs.jsonl`) that starts with or without a model. Cost: in `both`, a PDF is read by the model twice when agents
   are on (today's document reader and `A4-prose`). *Recommended:* accept it for the comparison period; D0 scores
   both; a third value of the switch (new pipeline only) comes after the baseline.
3. **Existing API tests run `legacy` (decision C).** Forced by scripted models (§2). The deployment default is still
   `both`, covered by W's coexistence test and the e2e suite. *Recommended:* accept.
4. **D1b changes no fit, by reading, not by running.** That the SD and its type do not enter the objective was read
   in the PI package source at the pinned commit; item 3 of §8.3 is the first run that shows it. Turning the
   weighting on stays an SME decision. Until D1b merges, the main line sends `error_type` for a geometric SD and the
   old script labels it arithmetic, as it does today, with no numerical effect. *Recommended:* accept; do not hold the
   main line for D1b.
5. **A spread reported with a geometric mean is ambiguous.** D1a labels an `SD` beside a geometric mean
   `GeometricStdDev` (what `pksim.py` already does) and converts nothing. Whether it is a geometric SD factor, a
   geometric CV or an arithmetic SD is the SME's call, as are other BLQ rules and the CV-to-GSD formula.
   *Recommended:* keep the warning on the profile and in the MAP limitation until the SME answers.
6. **D1a's contract change.** `Series.n_at` is in the OpenAPI snapshot, so D1a's branch fails that one test until the
   integrator refreshes it (§9): the only exception to "builders touch no shared file". `n_at` is set only when n
   varies, so stored datasets and existing answers do not change. BLQ "shown wherever the dataset is shown" needs a
   view change: D1a puts the rule and count on the profile, the row and the MAP limitation; the study card shows them
   in D6. *Recommended:* accept.
7. **A BLQ row without a spread drops its series' spread** (`client_data.py:156`, `:602`; `sheet_intake.py:158`),
   because `Series.error` cannot hold a missing entry. Nearly every summary table has a BLQ pre-dose row.
   *Recommended:* D6 widens `Series.error` to nullable entries with the view and the card (listed in §8.10), because
   the landing needs it; it is an API contract change, so it is not in D1a.
8. **Urine and excreta (decision O).** The ledger keeps `excretion.*` facts; nothing lands; D5 raises
   `EXCRETION_NOT_LANDED` and the requirement item `REQ-obs.urine` stays a project-scope gap. Interval against
   cumulative and the dose basis are SME decisions. Salt-to-base and per-kg derivations are likewise not built.
9. **D0's key columns.** `time_unit` and the optional `Studies` and `Not data` sheets are added to the lead's list
   (a time needs its unit; the by-tag score and the coverage comparison need the other two). The stores adapter has
   no arm, so it joins on study plus arm folded into the id. *Recommended:* accept.
10. **Silent loss is judged per delivery, not per study.** An unmapped table belongs to no study, so a study's
    confirmation refuses while any file of its deliveries has silent loss. A person can exclude regions with one
    reasoned decision per file. *Recommended:* accept; it is the literal reading of G2.
11. **Unruled PDF tables** are located as `table_like_text` and stay unread (silent loss) until a second table engine
    is registered or a person excludes them. Multi-table sheets with stacked headers will be mis-bounded sometimes:
    the mapping's `validate_spec` and the coverage count are the net. *Recommended:* accept and measure in D0.
12. **A person's upload tag is not a cross-file link** (decision 3, condition 1: the link must be anchored). It only
    suggests where to look. *Recommended:* accept.
13. **Unsupported files (decision F).** They are stored and recorded before today's `ingest` refuses them; the upload
    still answers 422 (legacy unchanged), and the file is listed in Delivery with its reason. A file the new parser
    reads but today's `ingest` refuses (a `;`-separated or cp1252 CSV) has no client-file record: its datasets land,
    its dissolution records cannot (`record_mapping` needs the record) and wait. A ZIP is expanded in `both`, so its
    members also reach today's readers: the one place `both` changes a legacy answer (a ZIP is refused today).
    *Recommended:* accept; widen today's CSV reading in a later build if the inventory shows such files.
14. **The signature.** Meaning `Reviewed`, role `Writer`, record type `intake-confirmation`. The owner may prefer
    `Approved` or the reviewer role; changing it is one line. The landing is not atomic (several artifact commits):
    it is planned and checked before signing and is idempotent after (§6.6).
15. **Mapping cache per project** (decision D). A layout approved in one project is not reused in the next.
    *Recommended:* keep per project now; consider a per-company cache, with its own approval, after the baseline.
16. **Performance (G7).** The `intake` job parses in a thread of the API worker; a large PDF holds the interpreter.
    Stage times are recorded, so it will show. *Recommended:* measure first; move `parse` to a worker process if the
    server's numbers ask for it.
17. **Disk.** Source caches of versions a value still names are never evicted; re-parses add files. A cleanup tool is
    a later build.
18. **What `_profile` judges** is still the first non-individual series (a median listed first wins over a mean), and
    the catalog still takes one dataset per study id. Not changed here; worth an SME decision.
19. **Study identity at landing.** The ledger has stable entity ids; a landed dataset's `study_id` is the study's
    label (with the arm when there are several), because `StudyRecord` and every page key on that string. A rename on
    a legacy card after landing is not followed back into the ledger.
20. **Requirement scope.** Only the items listed in `routing.item_scope` are judged per study or product; every other
    template item stays the project's, where the P3 gate still enforces nothing. G4 as built is the per-study part
    plus the schema gap. *Recommended:* the SME reviews `routing` (it is `UNVERIFIED`) before the first real delivery
    is confirmed.
21. **Existing projects after D1a.** A stored client dataset whose analyte is written differently from the brief's drug
    name and synonyms (a salt name, an abbreviation) becomes "not evaluable" at the next assembly, with the note saying
    why. No test project has one (probe). *Recommended:* before deploying, list every dataset's analyte against its
    brief on the server and add the synonyms that are the parent; the note tells the person what to do otherwise.
22. **What blocks a confirmation beyond decision E's list.** E's list is kept as written. An unapproved mapping, a
    required per-study item with no disposition, an open conflict and a missing landing field are *checks* at severity
    `fail` in the rules file, so they block as "a failed check"; the first and the last can be overridden with a
    reason, the other two are settled by a disposition or a choice. *Recommended:* the SME confirms the severities.
