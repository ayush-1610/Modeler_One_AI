# Client data in, read right: redesign of the intake (proposal, 2026-11-12)

Status: **PROPOSAL, for the owner's decisions (§8).** No code changed. If approved, it replaces the reading half of
`2026-11-10-add-data-agent-reads-everything.md` (R4's delivery map as context only; the document reader copying values)
and keeps what works (R1 reading queue, R3 tray, the vault, the recipe, the review cards).

## 1. The owner's ask (2026-11-12)
The client's data arrives unstructured, cluttered and unarranged. Getting all of it into the project, fast, correctly,
in the shape the tool accepts and valid for PBPK, is hard for the agent too. Stop adding to the current path; explore,
with several agents in depth, the best way to do it.

## 2. How this was explored
Four agents in parallel, each with its own question; the claims this plan rests on were then checked in the code by
hand (marked ✔ below).

| Agent | Question | Read |
|-------|----------|------|
| 1 | What the pipeline does today, file kind by file kind, and why it underperforms | intake, agents, API jobs, evals, CHANGELOG 11-03 → 11-12 |
| 2 | What the tool must receive: target models and PBPK validity, per data kind | CPF, datasets, studies, dissolution, validate, engine scripts |
| 3 | State of the art in parsing and LLM extraction (web) | OmniDocBench, RD-TableBench, SpreadsheetLLM, Auto-Tables, AutoPK, LangExtract … |
| 4 | Pharma and PBPK data standards, vendor practice, LLM accuracy (web, PubMed) | OSP docs and OSPSuite-R v12.4.0 source, CDISC PC/PP/EX/DM, ADNCA, NONMEM, PBBM template |

Limits: arxiv, FDA, CDISC and OSP's own site were blocked from the cloud session; OSP facts were read from its GitHub
sources (docs repository, OSPSuite-R tag v12.4.0). Paper numbers marked *secondary* come from abstracts or summaries.
No search query carried a project, client, drug or study name.

## 3. Why the current pipeline cannot get there
The problem is three problems, and today each is only half solved:
**reading** (getting the file's structure out), **understanding** (what each table is, which study, arm, analyte),
and **landing** (the shape the model needs, with PBPK checks). Nothing measures the result value by value.

### 3.1 Reading: structure is lost before anything sees it
| # | Finding | Evidence |
|---|---------|----------|
| R-a | PDF text only (pypdf), no table structure; Word tables flattened to `" \| "` text in ~3,500-character pseudo-pages; Word images dropped | `modeler_intake/documents.py:112-148` |
| R-b | A profile must come from one page; a table running over pages is partial or refused; one bad row refuses the series | `document_reader.py:220-241` |
| R-c | One sheet = one category = one table; a second table on a sheet is "not data"; side-by-side media collapse into one | `triage.py:89-119`, `cleaning.py:85-90`, `sheet_form.py:502` |
| R-d | No OCR: a scanned PDF fails; scanned pages inside a text PDF are silently empty | `documents.py:122`, `intake_jobs.py:222` |
| R-e | CSV: comma only, strict UTF-8; `.tsv` stored but never read | `grid.py:177-187`, `client_data.py:47` |
| R-f | Each workbook is parsed 3–5 times on its way through | `documents.py`, `client_data.py:369`, `delivery_pass.py:364`, `intake_jobs.py:126`, `sheet_intake.py:349` |

### 3.2 Understanding: the LLM does the wrong half of the job
| # | Finding | Evidence |
|---|---------|----------|
| U-a ✔ | **Only individual PK, summary PK and dissolution sheets are read.** NCA, design, demographics, product/batch and bioanalytical (LLOQ) sheets are sorted and then never read; workbooks never reach the document reader | `sheet_intake.py:28-29, 217` |
| U-b ✔ | **For PDF and Word, the LLM copies every number** into its tool call; code checks only that *some* number in the quote equals the value (or 100×). A mean placed in the SD column, or two subjects swapped, passes. SD and the NCA unit are not checked | `citations.py:33-39`, `document_reader.py:244-287` |
| U-c ✔ | **The delivery map cannot fill what drafts lack.** Its fields are study, product, role, strength, batch, food, medium, pH: not dose, n, route or purpose, which are what every concentration sheet waits for. It is "context, never a value", and code reads the sheets before the pass runs | `delivery_map.py:7,15`; `client_data.py:400` vs `intake_jobs.py:353` |
| U-d | Every concentration sheet waits for a person ("what the study is for" is never set by code; offers are never applied unasked) | `sheet_intake.py:72-82`, `client_review.py:51` |
| U-e | Five overlapping extractors with their own rules (code sheet reading, sheet reader, document reader, study offers, delivery map); the recipe's header-fingerprint reuse is computed but nothing looks it up | `recipe.py:4`, `recipe_review.py:151` |
| U-f | Speed: one serial worker per project; up to 30 LLM turns per document, every row quoted (bound by output tokens); the whole history re-sent each turn | `intake_jobs.py:347-372`, `llm.py:322-358` |

U-a and U-c together likely explain the owner's "I can't see any difference" after R4.

### 3.3 Landing: a perfect reader would still lose data on the way to the model
| # | Finding | Evidence |
|---|---------|----------|
| L-a ✔ | **BLQ points are dropped** before the campaign's profile (no censoring, no M3; OSP's own PI default keeps them at LLOQ) | `inputs.py:318` |
| L-b ✔ | **SE and CV% are silently dropped**; only SD reaches the fit | `inputs.py:321` |
| L-c ✔ | **Every SD is sent as arithmetic**, a geometric SD included | `run_pi.R:55` (locked) |
| L-d ✔ | **The analyte stops at the dataset**: the study catalog copies `dataset.study` only, so a metabolite profile is judged as parent plasma | `inputs.py` `study_catalog` |
| L-e | `n` per timepoint collapses to one number; one unit, time unit and LLOQ per dataset | `client_data.py:157,604`, `datasets.py` |
| L-f | Urine never becomes a dataset ("%" rejected; no "urine" matrix in the template), so urine-gated fits never fire from client data | `datasets.py:174`, `client_template.py:76` |
| L-g | No Study, Arm or Product entity: links live in strings and free-text notes; `ObservedDataset.study` must already validate as a full `StudyRecord`, so a partial extraction is refused | `datasets.py:75`, `client_data.py:251` |
| L-h | Meal kcal/fat, temperature and surfactant are read and then dropped; the dose basis (salt vs free base) is captured and used nowhere | `client_data.py:116-136`, `dissolution.py:46`, `brief.py:151` |

### 3.4 Measurement
Only synthetic sets exist (reading_eval 11 sheets, arrival_eval 4, delivery_eval 12 with a scripted "perfect reader").
The only live-model number: `qwen-coder` 6/11 sheets alone, 8/11 with code's reading kept (2026-10-22). The R6 report
compares metadata and point counts, not numbers. **No value-level accuracy on a real delivery exists.**

## 4. What the evidence says
1. **Born-digital values must never pass through OCR or an LLM.** Read cells with openpyxl / python-docx; read PDF
   text-layer words with their coordinates. (Agent 3; standard practice.)
2. **LLMs copying numbers is the error source.** A 27-study review: numeric extraction 47–88% vs categorical 74–96%,
   and **omissions are 60–74% of errors**; Claude 3.5 over 23,069 cells: 6.6% error, 57% of it a value put in the
   wrong field. Mean/SD extraction from trials: 24–56% correct. (Agent 4, PubMed/Consensus, *secondary*.)
3. **The pattern that works: the LLM writes the mapping, code reads the values.** Auto-Tables (VLDB 2023) reshapes
   >70% of messy tables with an 8-operator program; EVAPORATE-CODE+ beats direct extraction with ~110× fewer tokens;
   AutoPK's two-stage pipeline cut a small model's hallucinations from 60–95% to 8–14% on 605 PK tables. OSP's own
   importer (saved importer configuration XML) and Monolix data formatting (saved, replayable steps over an untouched
   file) are the same idea. (Agents 3, 4.)
4. **Classify each table, then map it per kind**; text beats page images unless the layout is complex; use vision
   only when there is no text layer. (Agent 3.)
5. **Auditability comes from deterministic re-execution, not from replaying the LLM** (identical requests give
   different completions; models retire). Store the LLM's answer as a signed proposal; reproduce from the approved,
   versioned mapping over the hashed file. (Agent 3.)
6. **Put structure upstream where possible**: CRO bioanalytical data-transfer specifications fix the BLQ token,
   missing-sample codes, nominal vs actual time and the BLQ rule; the PBBM report template (Mol Pharm 2025) lists the
   dissolution and formulation inputs regulators expect. (Agent 4.)
7. **Parsers on our constraints** (on-prem, CPU, client files stay on the server since 2026-10-06): Docling (MIT,
   ~0.8 s/page median on x86 CPU, page + bbox provenance) is the best CPU option; PaddleOCR-VL (Apache-2.0) or MinerU
   2.5 lead on scans and complex tables but need a GPU (MinerU's license changed; check it); cloud parsers are out.
   No benchmark exists on PK concentration listings: we must build our own gold set. (Agent 3.)

## 5. Options compared
| | Option | Correctness | Speed | Part 11 audit | Effort | Verdict |
|-|--------|-------------|-------|---------------|--------|---------|
| A | Keep the path; fix U-a, U-c, the quote check, add pdfplumber | better, but PDFs still copied by the LLM | still serial, turn-bound | as today | S | The R1–R6 pattern again: no step change |
| **B** | **Structure first: parse once → LLM proposes a typed mapping per table → code reads every value → a delivery ledger → PBPK checks in code → review by exception** | **highest: numbers never pass through the model** | **cost scales with tables, not rows; a known layout costs 0 LLM calls** | **replayable mapping over hashed files** | M–L | **Recommended backbone** |
| C | Front door: a data-request specification the client fills (the template exists: `client_template.py`) | exact, no AI | instant | exact | S | **Recommended alongside B**: it cannot cover legacy deliveries alone |
| D | A code-writing agent (free Python per file in a sandbox) | flexible; agents still pick wrong cells (SpreadsheetBench v2 < 35%) | medium | code recorded, but arbitrary code is hard to validate | M | No: B's typed mapping gives the same reach, validated |
| E | Better parser + LLM emits values as JSON | better parsing, same transcription errors | medium | weak | M | Take its parser, not its extraction |
| F | CDISC SDTM/ADaM first | exact | slow to build | strong | L | Overkill for summary tables (owner set I5 aside); **borrow the row grain only** |

## 6. Recommendation: B, with C as the front door, and the landing fixed first

### 6.1 Five rules
1. **A number in a cell or a text layer is read by code, never typed by a model.** The LLM proposes *where* and
   *what* (table region, header → field, unit, BLQ token, analyte, matrix, study, arm); code reads the value.
2. **Each file is parsed once** into a source model; everything downstream reads that, nothing re-opens the file.
3. **One mapping language** for every table, whether from a sheet, a PDF or a Word file: the existing recipe, widened.
   It is the record: versioned, hashed, re-executed on demand, reused when the same header comes again.
4. **Facts accumulate in one delivery ledger**, partial is allowed, and each fact keeps its own source span: a dose
   quoted in the synopsis fills the study of the PK table it is linked to, with both quotes.
5. **Every PBPK validity rule is code** (§6.6); a person confirms per study, and sees first what failed.

### 6.2 The pipeline
```
upload ─► vault (sha) ─► PARSE once (code) ─────────────────► source model
                         xlsx/xls/csv/tsv: cells, merges, formats, comments (openpyxl / grid)
                         docx: tables as cell grids, paragraphs, images (python-docx)
                         pdf: words + bboxes (pdfplumber), table grids (Docling, CPU), pages, figures
                         scan: flagged; OCR later (GPU decision, §8 q4)
        ─► LOCATE (code) table regions, header bands, several per sheet/page, tables across pages stitched
        ─► CLASSIFY + MAP (LLM, short, per table, parallel)    output = mapping spec, schema-checked
              kind (concentration listing, mean profile, NCA, design, demographics, dose, product/batch,
              dissolution, LLOQ/bioanalytical, physchem, not data + why); column → field; unit; BLQ token;
              constants with their cell; wide → long; study / arm / analyte / matrix
              known header fingerprint → reuse the approved mapping, no LLM call
        ─► EXECUTE (code) the mapping over the source model → typed rows, each with its cell or bbox
        ─► PROSE FACTS (LLM, synopsis text only): dose, n, route, design, food, batch; checked by a strict,
              label-aware quote rule (§6.4)
        ─► LEDGER (code): studies, arms, products, doses, observations, links across files
        ─► CHECKS (code): PBPK validity, completeness, consistency, duplicates (§6.6)
        ─► REVIEW by exception on the study / product card → confirm → datasets, CPF evidence (system of record)
```

### 6.3 Mapping spec v2 (the LLM's only output for a table)
Widen `modeler_intake.recipe` (already deterministic, already multi-table, OSP unit names): several tables per
sheet or page; a column or a cell for each constant (dose, n, unit, LLOQ, analyte, matrix, medium, pH); per-column
units; BLQ and missing-sample tokens (`BLQ`, `<LLOQ`, `NS`, `NR`); wide-to-long (subjects across, times across,
vessels across); a table spanning pages; a `kind` for every table kind above, not only PK and dissolution. Code
validates the spec (cells exist, units known, every constant cites a cell) before executing it. Wire the header
fingerprint so a layout seen once is never sent to the LLM again.

### 6.4 Prose facts
Synopses state design facts in sentences. Here the LLM does extract values, under a stricter check than
`value_stated_in_quote`: the quote must contain the field's label (dose, subjects, route, fasting …) and exactly one
number equal to the value, in the same clause; the value's unit is parsed by code. Each fact lands in the ledger
against its study, never directly on a dataset.

### 6.5 The delivery ledger (canonical intermediate)
Long form, one row per observation or dose event, every row with a `SourceSpan` (file sha, sheet!cell or page+bbox,
verbatim text, extraction method: cell / pdf-table / prose / digitized / manual). Borrowed: the SDTM PC/EX/DM row
grain and PP-style parameter codes; OSP importer metadata; NONMEM-style dose events. Skipped: SUPPQUAL, visits,
define.xml.

| Entity | Key fields | Lands in (today's model) |
|--------|-----------|--------------------------|
| Study, Arm | id, design (parallel/crossover), period, sequence, washout, population, n dosed / evaluable | `StudyRecord` |
| Product, Batch | role (test/reference), dosage form, release, strength and its basis, lot, particle size | brief products, `form.{name}` |
| DoseEvent | arm, amount, unit, basis (salt/free base), route, time, infusion duration, meal (type, kcal, fat, time) | dose, `dose_phases`, `meals` |
| Analyte | name, role (parent/metabolite/enantiomer/sum), molecular weight | `ModelSystem.analytes` |
| Observation | arm, subject, analyte, matrix, nominal and actual time, time reference, value, verbatim text, unit, LLOQ, censored, excluded + why | `Series` (individual) |
| SummaryPoint | arm, analyte, matrix, time, statistic, value, spread kind (SD/SE/CV%/geoSD/CI), n at that time | `Series` (mean) |
| PKParameter | code, interval, statistic, value, unit, spread, n | `ReportedPK` |
| Excretion | interval, amount or % dose, cumulative or per interval | (nothing today, L-f) |
| DissolutionRun | batch, apparatus, rpm, volume, medium, pH, temperature, surfactant, % basis, per-vessel points | `ProfileKey` / `Profile` |
| InVitroMeasurement | CPF id, value, unit, typed conditions (pH, temperature, system, fu,inc), measured/predicted | `EvidenceItem` |
| Link | same study / product / batch / analyte, with the quote that joins them | delivery map, `client_review` |

The ledger accepts partial facts. A "what this study still needs" list is computed from it, and nothing reaches a
dataset until the study it belongs to is complete and confirmed.

### 6.6 PBPK checks in code (proposal; acceptance-type thresholds are SME-governed and stay UNVERIFIED)
- **Completeness (omissions are the main failure):** every table the parser located is mapped or marked "not data"
  with a reason; every study named anywhere has its profile, design and dose, or an open gap; rows found vs subjects ×
  timepoints the design implies.
- **Profiles:** analyte and matrix explicit; BLQ kept as censored with its LLOQ, never 0 or dropped; nominal and actual
  time, time zero tied to a dose event; statistic, spread kind and n per time; SE and CV% converted to SD in code
  with n stated; geometric vs arithmetic kept to the engine.
- **Dose and design:** salt vs free-base basis applied once; dose = k × strength; infusion duration for IV; fed meal
  stated; crossover period and lot per period.
- **NCA:** recomputed from the profile and compared with the reported table (exists for Cmax/AUClast at 20%; widen).
- **Dissolution:** apparatus, rpm, volume, medium, pH, temperature, surfactant, n vessels; individual vessels where
  given; the same lots as the clinical batches; plateau and t=0 checks (exist).
- **Duplicates:** the same profile as a table and as a plot → the table wins; a plot is suggested only where no table
  holds it (owner's decision of 2026-11-10).

### 6.7 Review by exception
One card per study and per product: the chart, the rows with their source highlighted on click, and the checks; what
failed or is missing is listed first. A study whose every check passes, and whose mappings are reused or already
approved, is confirmed in one action. Nothing loads unconfirmed (unchanged). "What the study is for" is pre-selected
from route, food state and formulation against the data plan, and confirmed with the study.

### 6.8 Speed
Parse once; map each table in parallel (A2 already runs 4 at once); LLM output is a small spec, not rows; a known
layout costs no LLM call. Proposed target for the owner to set: a 20-file delivery read, mapped and checked within
15 minutes on the server, the person's review excluded.

### 6.9 Front door: the data-request specification
Send each client, with the data request, the template (`client_template.py`, read with no AI) and a short data
specification: BLQ token and LLOQ, nominal and actual times, statistic and spread kind, dose basis, analyte and
matrix, one tab per study, dissolution conditions per profile (from the PBBM report template). A delivery that follows
it is read exactly; one that does not goes through B.

## 7. Builds (each its own PR to `main`; smallest and most certain first)
| Build | Scope | Fixes | Locked files |
|-------|-------|-------|--------------|
| D0 | **Measure first.** A gold set from the owner's real delivery (the R6 answer key, extended to every value, kept on the server), scored cell by cell; today's pipeline scored as the baseline | §3.4 | none |
| D1 | **Landing fixes:** BLQ kept as censored; SE/CV% converted to SD with n; analyte and matrix carried to the campaign; n per timepoint; urine datasets; error type sent as arithmetic or geometric | L-a … L-f | `run_pi.R` (L-c), likely `split.py`: owner's approval, own PR |
| D2 | **Source model:** parse once; pdfplumber words + Docling tables for PDF; Word tables as grids and images kept; CSV dialect and encoding sniffing; table regions, several per sheet, tables across pages | R-a … R-f | none |
| D3 | **Mapping spec v2 + the mapper:** every table kind, schema-checked, executed by code; fingerprint reuse; replaces the document reader's value copying and the sheet reader's one-table limit; prose facts under §6.4 | U-a, U-b, U-e, U-f | none (the recipe and records are not locked) |
| D4 | **Delivery ledger + checks:** partial facts, cross-file fill with quoted links, completeness and consistency checks | U-c, U-d, L-g, L-h | maybe `cpf/models.py` for dose basis: owner's approval |
| D5 | **Review by exception** on the study and product cards | U-d | none |
| D6 | **Front door:** the data specification and the template sent with the data request | §6.9 | none |
| later | OCR for scans (GPU decision); the hybrid plot digitizer (vision model reads ticks, code fits axes, replot overlay) | R-d, figures | — |

D0 and D1 do not depend on the redesign and should go first: D0 tells us whether each later build helped, D1 stops
losing data that is already read correctly.

## 8. Decisions for the owner
1. **Direction:** B as the backbone with C as the front door (§5), replacing the LLM's copying of numbers wherever a
   file has them as cells or text?
2. **Cross-file facts:** may a fact quoted in one file (a synopsis's dose) fill the study of another file (its PK
   table) when a quoted link joins them? Today every value must be quoted from its own file.
3. **D1 science fixes** touch locked files (`run_pi.R`; possibly `split.py`, `cpf/models.py`): approve a dedicated PR?
4. **Server hardware:** does it have, or can it get, a GPU (16–24 GB)? It decides OCR for scans and the stronger
   table models; without one, scans stay manual and Docling runs on CPU.
5. **Speed target:** keep 15 minutes for a 20-file delivery (§6.8), or set another.
6. **Gold set:** D0 needs the delivery's answer key at value level. Who writes it, and does it stay on the server only?

## 9. What stays
The vault and CLIENT_SUBMISSION artifacts; `modeler_intake.grid`; recipe + apply + validate + records; the cleaning
record; quote normalization; the reading queue and the tray (R1, R3); `ObservedDataset`, the dataset and dissolution
registers; `client_review` (group confirm, conflicts, aliases); `run_tool_loop`, AgentRun and the usage report; the
PDF figures and the calibrated digitizer; the template's no-AI path; the eval harnesses as scaffolding.

## 10. Risks
- No public benchmark on PK listings: D0's gold set is the only proof, and it is small at first.
- Multi-table sheets with hierarchical headers are mis-bounded by every tool; the locate step needs its own tests.
- The in-house model's mapping quality is unmeasured; D0 scores it before D3 relies on it.
- On scans, OCR text is the source: a string match cannot catch an OCR digit error (two engines + a person).
- Plot digitizing carries ~2–5% error on top of errors in the published figures.
- License: Docling MIT; check MinerU's current license and avoid Marker (RAIL weights) and WebPlotDigitizer v4 (AGPL).

## Sources (the main ones)
- OSP importer and PI LLOQ options: `Open-Systems-Pharmacology/docs` (part-5 import-edit-observed-data,
  parameter-identification); OSPSuite-R v12.4.0 (`createImporterConfigurationForFile`, `loadDataSetsFromExcel`);
  esqlabsR importer configuration example.
- CDISC: ADaMIG-NCA v1.0 (2021) via the admiral `pk_adnca` vignette and the aNCA manual.
- Docling: arXiv 2501.17887; OmniDocBench leaderboard (github.com/opendatalab/OmniDocBench); RD-TableBench (Reducto,
  vendor-run).
- Auto-Tables arXiv 2307.14565; EVAPORATE arXiv 2304.09433; SpreadsheetLLM arXiv 2407.09025; AutoPK arXiv 2510.00039
  (doi 10.1109/ictai66417.2025.00051); LangExtract (Google Developers blog).
- LLM nondeterminism: Thinking Machines, "Defeating nondeterminism in LLM inference".
- PBBM: report template doi 10.1021/acs.molpharmaceut.5c00225; parameterization workshop doi
  10.1021/acs.molpharmaceut.4c00526.
- Digitized vs reported Cmax: Wojtyniak et al. 2020, CPT:PSP (PubMed 32543786).
- BLQ methods: Beal 2001, doi 10.1023/a:1012299115260.
