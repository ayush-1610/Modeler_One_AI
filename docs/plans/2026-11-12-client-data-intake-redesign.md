# Client data in, read right: redesign of the intake (proposal, 2026-11-12)

Status: **APPROVED by the owner 2026-11-12, with conditions (§10); revision 3; being built.**
- Revision 1 (2026-11-12): four agents explored the problem; the options were compared (§3–§5).
- Revision 2 (2026-11-12): the owner's own design, worked out in a separate conversation ("The Universal PBPK Curation
  Pipeline", 39 pages), was reviewed against the code, the engine catalog and the evidence (§6). The two designs are
  merged into one for Modeler One (§7–§8).
- Revision 3 (2026-11-12): the owner's decisions on the eight questions (§10). The gates are locked (§7.1); the builds
  run in parallel against shared contracts (`2026-11-12-intake-contracts.md`), §8.

If approved, this replaces the reading half of `2026-11-10-add-data-agent-reads-everything.md` (R4's delivery map as
context only; the document reader copying values). It keeps what works there: the R1 reading queue, the R3 tray, the
vault, the recipe and the review cards.

## 1. The owner's ask (2026-11-12)
1. The client's data arrives unstructured, cluttered and unarranged, and its patterns change with every delivery
   (dissolution and formulation data, clinical study data, sometimes forms). Getting all of it into the project, fast,
   correctly, in the shape the tool accepts and valid for PBPK, is hard for the agent too. Stop adding to the current
   path; explore, with several agents in depth, the best way to do it.
2. Having worked out a design of their own, the owner asked for a rational review of it and a proposal of what the tool
   should have to reach the goal, "making the best of all possible".

## 2. How this was explored
Four agents in parallel, each with its own question; the claims this plan rests on were then checked in the code by
hand (marked ✔ below).

| Agent | Question | Read |
|-------|----------|------|
| 1 | What the pipeline does today, file kind by file kind, and why it underperforms | intake, agents, API jobs, evals, CHANGELOG 11-03 → 11-12 |
| 2 | What the tool must receive: target models and PBPK validity, per data kind | CPF, datasets, studies, dissolution, validate, engine scripts |
| 3 | State of the art in parsing and LLM extraction (web) | OmniDocBench, RD-TableBench, SpreadsheetLLM, Auto-Tables, AutoPK, LangExtract … |
| 4 | Pharma and PBPK data standards, vendor practice, LLM accuracy (web, PubMed) | OSP docs and OSPSuite-R v12.4.0 source, CDISC PC/PP/EX/DM, ADNCA, NONMEM, PBBM template |

Revision 2 adds the owner's document (§6), read in full, and three checks in the repository: the requirement
templates (`pbpk_domain/requirements/*.yaml`), the analysis templates and rulesets, and the harvested engine catalog
(`services/engine-worker/golden/catalog.json`) for the sub-domains the document names.

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

## 6. The owner's design (2026-11-12), reviewed

### 6.1 Its goal and idea
A pipeline that takes **any** client delivery, whatever its format or layout, loses **nothing**, gives values that are
**exactly** right and valid for PBPK, serves **any** PBPK application (pediatric, pregnancy, biologics, DDI, dermal,
ocular …), and lets people review only the exceptions. Its means: eight stages (universal ingestion, semantic layer,
mapping layer, delivery ledger, deterministic compute, validation and coverage audit, review by exception, output),
five invariants, a five-axis routing vector per document (population, modality, route, context, document role) that
selects a modular sub-schema library, and three reviewer surfaces (scientist, analyst, engineer).

### 6.2 Where the two designs agree
They were worked out separately and agree on the core, which is reassuring:
parse once and keep structure; **the LLM never copies a number**; every value anchored to its source; validity checked
in code; people review exceptions; a layout seen before needs no LLM call; build in steps, starting with an answer key.
The document's comparison was made against a six-line summary of revision 1, not the plan; several of the gaps it
lists were already in it (prose facts, a check that every table is mapped or marked "not data", source spans, links
and duplicates, the client specification).

### 6.3 What it adds, and we take
| From the owner's design | Why it is right | Where it lands (§7) |
|-------------------------|-----------------|---------------------|
| **A silent-loss metric**: every numeric cell of every located table is mapped or excluded with a reason; any other cell is silent loss | Omissions are 60–74% of extraction errors (§4.2); a count makes "nothing missed" checkable | §7.7, release condition |
| **Append and supersede**, never overwrite; a correction is a new fact with a reason | Part 11 audit trail; matches our audit chains | §7.6 |
| **Derived facts** carry their input facts and the compute module's version | A converted SD or a free-base dose can be replayed and audited | §7.6 |
| **Anchor integrity**: every fact resolves to its anchor after a re-parse | Catches parser drift when a library is upgraded | §7.7 |
| **Mapping cache with sign-off and version** | The approved mapping is the validated, replayable record | §7.4 |
| **Knowing what it does not know**: an unsupported format, a study outside scope, a missing schema is flagged and never processed with generic rules | Honest coverage; matches the ground rule "never invent" | §7.3, §7.9 |
| **Document role** (synopsis, concentration listing, bioanalytical report, dissolution report, CoA …) to pick the extractor | Different documents need different readers | §7.3 |
| **Relation facts** (a DDI ratio links victim and perpetrator arms; test vs reference) | DDI and VBE results are relations, not flat values | §7.6 |
| **A pipeline-health view** (cache hit rate, parser failures, coverage, OCR cliffs) | Shows where the pipeline is blind before a model is wrong | §7.8, admin console |
| **"Confirm per study" can become a rubber stamp** | True; it needs the source beside each exception, and more (§7.8 spot check) | §7.8 |

### 6.4 What we change or leave out, and why
| In the owner's design | Rational view | Instead |
|-----------------------|---------------|---------|
| "Zero data loss guarantee", "exactly perfect output", "100% of schema-required fields per released study" | Not provable as stated. The coverage audit only counts what the parser located: a table it never found has no cells to count. And a field can be missing because the client never sent it; that is a gap to fill, not an extraction failure | A measurable goal (§7.1): nothing located is dropped silently, content outside every region is listed, every required input has a status (found, conflicting, or missing → client, literature or not needed) |
| **The document decides the domain** (a five-axis vector per document selects the sub-schemas) | Backwards for a regulated model. Under ICH M15 the question of interest and context of use decide what the model needs; one pediatric study in an adult VBE project does not make it a pediatric model | The **project's application** selects the requirement templates (they exist, §6.5); each study carries its own population, route and food tags (`StudyRecord` enums exist), and a study outside the application is flagged |
| **System parameters extracted from client files** (ontogeny functions, gestational physiology series, FcRn expression, organ weights) | These come from the engine's population and ontogeny databases, not from client data; our template already says so (`REQ-sp.ontogeny`: `default_provider: LIBRARY`). The check "pediatric study simulated with adult physiology" is a model-building check | Kept out of intake. Population physiology comes from PK-Sim (the catalog has `Pregnant`, `Preterm` and ontogeny); the builder and S0 readiness check it |
| **Modeling rules inside curation** (fu,p defaulted to 1%, AUCR outside 0.80–1.25 needs sensitivity, Fa = Fg = 1 defaults) | These are modeling decisions, SME-governed; ours live in the rulesets and the MAP (`ddi_static_screening.yaml`) | Unchanged: rulesets, `UNVERIFIED`, owner and SME approval |
| **Sub-schemas for dermal, ocular, ADC, oligonucleotides, gene therapy**, compute modules for dermal flux and ocular scaling (GastroPlus MechDermA and OCAT named) | Our engine is PK-Sim. None of these is in the harvested catalog (no hits for dermal, ocular or FcRn); extracting data the engine cannot use is wasted work | Out of scope until the owner extends the engine; such data is kept in the library and flagged "outside the tool's modeling scope" (§7.9) |
| **LLM confidence scores** (0.92, 0.97) drive review | A model's stated confidence is not calibrated and cannot be validated | Evidence levels computed by code: person-confirmed > approved mapping > new mapping > prose > digitized (§7.6) |
| **Outputs to Neo4j, SQL, Simcyp and GastroPlus** | One engine, one system of record (CPF). A graph database adds infrastructure for joins a relational ledger already does | CPF and `ObservedDataset` to PK-Sim (unchanged); the ledger relational (PostgreSQL path) or in the artifact store; an intake record in the M15 package; an OSP-importer export if wanted |
| **Fine-tuning prompts from reviewers' corrections** | Silent model change breaks validation (GAMP 5, Part 11) | A correction becomes an approved mapping and a gold-set case; a prompt or model change goes through change control with its evaluation score |
| **z-factor, IVIVC deconvolution** as compute modules | z-factor is not a PK-Sim construct (never invent PK-Sim names); PK-Sim takes Weibull, a table or particle dissolution, and we already fit Weibull in PK-Sim's parameterization | Later, with its own plan, if an application needs IVIVC |
| **Every format** (PPTX, HTML, XML, SAS XPT, email, ZIP, images) at once | Breadth costs effort; worth it only for what clients send | Prioritized from real deliveries (§10, decision 5: a 30-day inventory); anything unsupported says so, never silent |
| **Composition sums to 100 ± 0.5%** | Compositions are often in mg per unit | Sums to the stated unit weight or to 100%; the tolerance is SME-governed |
| **Three reviewer surfaces** | A small team; one review surface is enough | Review on the study and product cards; the engineer's view in the admin console |

### 6.5 What the tool already has that the document asks for
| The document asks for | Already in the tool |
|-----------------------|---------------------|
| A modular sub-schema library: required fields, conditional fields, validity rules, versioned and reviewable | **Requirement templates** `pbpk_domain/requirements/`: `core_small_molecule.yaml` (27 items) and `app_ddi`, `app_food_effect`, `app_fih`, `app_special_populations`, `app_vbe`. Each item: CPF target, PK-Sim building block and location (harvested), unit, REQUIRED / CONDITIONAL with `when`, the MS-01 stage that needs it, the conditions to record, the default source, plausibility. Versioned, `UNVERIFIED`, SME-governed |
| Routing to the sub-schemas | The project's application, set at Start from the proposal, selects the templates; analysis templates `vbe-crossover`, `ddi-cyp3a4-victim` |
| A schema-gap queue that blocks release | The data plan and the P3 gate (each need: from the client, from literature, or not needed) and S0 readiness |
| Population and sub-domain tags | `StudyRecord` enums: route, food state, formulation, special population (pediatric, hepatic, renal, pregnancy, elderly) |
| Conflicts kept, never auto-picked | `client_review`: conflicts settled by a person, aliases, duplicates |
| Accept/reject with audit trail | Signatures with step-up, the audit chains (Part 11) |
| Raw source beside the value | The source viewer (centre peek on every page, I1b); extend it to the cell or the box |
| Deterministic compute | NCA, unit conversion, Weibull fit, f2 (`pbpk_domain`); four unit tables to merge into one |
| Engineer surface | The admin console (built 2026-11-10/11) |

What is missing is the **connection**: intake does not yet report against the requirement items, and the pieces above
see only what the readers deliver.

## 7. The merged design for Modeler One

### 7.1 The goal, measurable: the gates (locked 2026-11-12)
The owner approved the design against their own reading of six gates, on condition that the gate texts be locked.
This is the locked set: the owner's six, in the owner's numbering, plus the two things only revision 2 had (every file
accounted for, now inside G2; the time target, G7). For every delivery, on every route (Start, Add data, an Inputs tab):
- **G1 Scored against an answer key.** A value-level answer key for a real delivery exists, written by people who did
  not build the pipeline (§10, decision 8), and the pipeline is scored against it value by value: by field, by study,
  by sub-domain. The accuracy target is set after the baseline.
- **G2 No silent loss.** Every file is read, partly read (the regions not read listed) or unsupported (and why).
  Every located table, paragraph group and figure is mapped or excluded with a reason; every numeric cell of a mapped
  table is used or excluded by a stated rule; text outside every region is listed by page.
  **Silent loss = 0 is a release condition.**
- **G3 Every released fact resolves to an immutable anchor** (file hash, parser version, cell / page + box / text
  span / figure) or to a signed person's entry; a derived value to its inputs and the compute version; a cross-file
  fact to its three anchors (§7.6).
- **G4 Requirement coverage per study, never globally.** Each study is checked against the requirement templates that
  *its own* routing activates: the project's application, plus the study's population, modality, route and context
  tags. A study whose routing no authored template covers is a **schema gap: it blocks release** and is never counted
  as done against another checklist. Each item is found (anchored), conflicting, or missing → asked of the client,
  taken from literature, or signed "not needed".
- **G5 Validity rules pass, or every failure carries a recorded scientist's override** (who, when, why).
- **G6 Signed confirmation per study**, with the spot check done (§7.8) and the audit trail.
- **G7 Time.** From the files' arrival to a reviewable exception list for a typical study: 15 minutes with a GPU and a
  warm mapping cache; 45–60 minutes without a GPU. It does not cover a first-seen layout, a cold cache, or heavy
  scanned or figure content. Each stage's time is recorded per delivery, so the gate is measured.

This replaces "any data, exactly perfect" with what can be proven to a reviewer or a regulator.

### 7.2 Seven rules
1. **Parse once, keep structure.** No re-parsing downstream.
2. **A number in a cell or a text layer is read by code, never typed by a model.** The LLM proposes where and what.
3. **Every fact has an anchor**; nothing enters the ledger without one.
4. **Append and supersede**; a correction never overwrites.
5. **Arithmetic is code**: units, conversions, NCA, fits, each versioned, each derived fact naming its inputs.
6. **The application decides what is required**; documents only supply facts. What is outside the application or the
   engine is flagged, never forced into a generic schema.
7. **People review exceptions, and only confirmed facts reach the model** (CPF stays the system of record).

### 7.3 The stages, mapped to what exists
| # | Stage | Builds on (exists) | New |
|---|-------|--------------------|-----|
| 1 | **Intake and parse once** → source model with anchors | vault (sha), `grid`, `documents` | pdfplumber words and tables for PDF (Docling behind the same interface, §10.2); Word tables as grids, images kept; CSV dialect and encoding; ZIP unpacked; anchors with parser version; content outside every region listed; unsupported formats said so. OCR and images: with the GPU (§10, decision 4) |
| 2 | **Identify**: document role, table kind, study / product / batch identity | `triage`, `delivery_pass`, delivery map | Several tables per sheet or page, tables across pages; table kinds beyond PK and dissolution; rules first, a short LLM call for the rest |
| 3 | **Map and extract**: table mapper, prose extractor, figures | `recipe`, `apply`, `sheet_reader`, `pdf_figures`, digitizer | Mapping spec v2 (§7.4); cache with sign-off; prose under a strict check (§7.5); figures suggest-only (owner, 2026-11-10) |
| 4 | **Ledger**: facts, entities, links, conflicts, relations | CLIENT_SUBMISSION artifacts, `client_review`, audit chains | The ledger (§7.6): partial facts, append and supersede, derived and relation facts |
| 5 | **Compute** | `nca`, `units`, `parameter_units`, `dissolution` (Weibull, f2) | One unit library instead of four; SE/CV% → SD with n; salt → free base; dose per kg; each a derived fact |
| 6 | **Checks and coverage audit** | `validate`, `check_profile`, evidence checks, data plan, P3 gate, requirement templates | Coverage (G2), requirement status per study (G4), PK-Sim import constraints, PBPK checks with overrides (G5) (§7.7) |
| 7 | **Review by exception** | study and product cards, source viewer, signatures, admin console | Cell / box highlight, exceptions first, spot check, coverage panel, pipeline-health page (§7.8) |
| 8 | **Land** | CPF, `ObservedDataset`, `pksim.py`, M15 package | D1's landing fixes (§3.3); the intake record (facts with anchors) in the M15 package |

### 7.4 Mapping spec v2 (the LLM's only output for a table)
Widen `modeler_intake.recipe` (already deterministic, already multi-table, OSP unit names): several tables per sheet
or page; a column or a cell for each constant (dose, n, unit, LLOQ, analyte, matrix, medium, pH); per-column units;
BLQ and missing-sample tokens (`BLQ`, `<LLOQ`, `NS`, `NR`); wide-to-long (subjects, times or vessels across); a table
spanning pages; a `kind` for every table kind. The LLM receives the header band, a few rows and the caption, never the
numeric body. Code validates the spec (cells exist, units known, every constant cites a cell) before executing it.
An approved spec is stored under its layout fingerprint with its version and approver; the same layout later is
mapped with no LLM call, and a layout that differs falls back to the LLM, never to a silent skip.

### 7.5 Prose facts
Synopses state design facts in sentences (dose, subjects, route, fasting, regimen, batch, dissolution method). Here
the LLM extracts values, section by section, under a stricter check than today's `value_stated_in_quote`: the quote
must contain the field's label and exactly one number equal to the value, in the same clause; code parses the unit.
Each fact lands in the ledger against its study, never directly on a dataset. Tables are never read as prose.

### 7.6 The ledger
Long form, one fact per value, append-only:
`id · delivery · entity (study, arm, product, batch, analyte, subject) · field (a requirement target or a ledger
field) · value · unit · verbatim text · anchor (file sha, parser version, locator: sheet!cell, page/table/row/col +
box, page/paragraph/span, page/figure) · method (cell, pdf table, prose, digitized, derived, person) · mapping id and
version, or model and prompt hash · derived from (fact ids) + compute version · status (proposed, confirmed,
superseded, excluded + reason) · supersedes · signed by / at`.

Rules: append and supersede with a reason; entity resolution through aliases (`client_review` exists), every merge a
quoted link; two facts that disagree on the same entity and field are both kept and the pair goes to review;
relation facts for DDI ratios and test-vs-reference; partial facts welcome, and a "what this study still needs" list is
computed from the requirement templates. No LLM confidence: the **evidence level** is computed (person-confirmed >
approved mapping > new mapping > prose > digitized).

**Cross-file facts (the owner's decision 3):** a fact stated in one file may fill a study read from another only when
(1) the link is explicit and anchored: a study id, protocol number or literal cross-reference, itself a link fact with
its own anchor (the same drug name or similar dates never qualify); (2) the match is unique (several candidates → the
conflict queue, nothing filled); (3) the fact is stored as `cross_file_linked` with three anchors: the stating file's,
the receiving study's and the link's; (4) a reviewer confirms it on first use per study, and later facts through the
same link inherit that confirmation; (5) every later view, the model's inputs included, shows that it was joined.

Entities, borrowing the SDTM PC/EX/DM row grain and PP parameter codes, OSP importer metadata, NONMEM-style doses:

| Entity | Key fields | Lands in (today's model) |
|--------|-----------|--------------------------|
| Study, Arm | id, design (parallel/crossover), period, sequence, washout, population tag, n dosed / evaluable | `StudyRecord` |
| Product, Batch | role (test/reference), dosage form, release, strength and its basis, lot, particle size | brief products, `form.{name}` |
| DoseEvent | arm, amount, unit, basis (salt/free base), route, time, infusion duration, meal (type, kcal, fat, time) | dose, `dose_phases`, `meals` |
| Analyte | name, role (parent/metabolite/enantiomer/sum), molecular weight | `ModelSystem.analytes` |
| Observation | arm, subject, analyte, matrix, nominal and actual time, time reference, value, verbatim, unit, LLOQ, censored, excluded + why | `Series` (individual) |
| SummaryPoint | arm, analyte, matrix, time, statistic, value, spread kind (SD/SE/CV%/geoSD/CI), n at that time | `Series` (mean) |
| PKParameter | code, interval, statistic, value, unit, spread, n | `ReportedPK` |
| Relation | kind (DDI ratio, test vs reference), the two arms, parameter, ratio, 90% CI | (nothing today) |
| Excretion | interval, amount or % dose, cumulative or per interval | (nothing today, L-f) |
| DissolutionRun | batch, apparatus, rpm, volume, medium, pH, temperature, surfactant, % basis, per-vessel points | `ProfileKey` / `Profile` |
| InVitroMeasurement | CPF id, value, unit, typed conditions (pH, temperature, system, fu,inc), measured/predicted | `EvidenceItem` |

### 7.7 Checks and the coverage audit (all code; thresholds that judge acceptance are SME-governed, `UNVERIFIED`)
- **Coverage (G2):** per file, per region and per cell (silent loss counted and shown), content outside every region
  listed by page, anchor integrity after any re-parse (G3).
- **Requirements (G4):** per study, every item of the templates its routing activates, with its status; a routing no
  template covers is a schema gap that blocks release; a missing item drafts a line in the client request (exists,
  build J) or a literature task (A2).
- **Overrides (G5):** a failed check is cleared only by a scientist's recorded override (who, when, why); the
  scorecard shows it from then on.
- **What PK-Sim's import accepts** (from the OSP docs and OSPSuite-R v12.4.0): one LLOQ per observed dataset; error as
  arithmetic or geometric SD only (SE and CV% converted with n, or refused); unique times per dataset; the molecular
  weight consistent with the compound; units known to the harvested dimensions.
- **Profiles:** analyte and matrix explicit; BLQ kept as censored with its LLOQ, never 0 or dropped; a BLQ rule stated
  wherever BLQ markers appear; nominal and actual time, time zero tied to a dose event; statistic, spread kind and n
  per time.
- **Dose and design:** salt vs free base applied once; dose = k × strength; infusion duration for IV; the fed meal
  stated; crossover period and lot per period.
- **NCA:** recomputed from the profile and compared with the reported table (exists for Cmax and AUClast; widen).
- **Dissolution:** method metadata present for every profile (apparatus, rpm, volume, medium, pH, temperature,
  surfactant, n vessels); times increasing; % within range (exists); the same lots as the clinical batches.
- **Compound values:** physical bounds, fu in (0, 1], conditions recorded (exist in `evidence.py`); solubility by pH
  kept as a table, not as conflicts.
- **Composition:** sums to the stated unit weight or 100%.
- **Duplicates:** the same profile as a table and as a plot → the table wins.
- Output: a scorecard per study and per product, not a pass/fail flag.

### 7.8 Review by exception
- One card per study and per product: the chart, the rows, and a click on any value opens its source with the cell or
  box highlighted. Failed checks and missing inputs first, by severity; conflicts side by side with both anchors.
- **A new mapping is shown as a mapping** (header → field, unit, BLQ token) for one-click accept or edit; once
  accepted it is cached (§7.4).
- **Spot check against rubber-stamping (the owner's decision 6):** before a study is confirmed, **100 values, drawn
  by strata**, are shown with their source for the person to tick; a study with fewer than 100 numeric values is
  checked in full. Strata: every table type present, every unit class (mass, concentration, time, percentage, ratio),
  every BLQ marker form, every digitized fact, every cross-file fact, every derived fact with its inputs.
  **Never sampled, always verified:** the values that decide the model for the study's routing (the template items
  marked so), and any value with a scientist's override. The draw is seeded from the ledger's state, so an auditor can
  reproduce it. The numbers (100; which items are always verified) sit in a ruleset file marked `UNVERIFIED`.
- Confirmation is signed (step-up, exists), per study or product; corrections supersede.
- **Coverage panel** per delivery: files, regions, silent loss, requirement status.
- **Pipeline health** in the admin console: mapping-cache hit rate, parser failures, unsupported files, regions
  outside any table, unresolved anchors.

### 7.9 Applications and sub-domains: universal in mechanism, explicit in scope
Adding a sub-domain is (1) the engine supporting it (names harvested), (2) its requirement template (SME-governed,
`UNVERIFIED`, owner's approval, version bump), (3) its landing shapes, (4) its checks. The intake mechanism does not
change. Where each stands:

| Application | Requirement template | Engine (harvested catalog) | What intake must add |
|-------------|----------------------|----------------------------|----------------------|
| Small molecule, IV and oral (APP-01) | `core_small_molecule.yaml` | yes | this plan |
| Food effect | `app_food_effect.yaml` | yes | meal kcal and fat kept (L-h) |
| VBE | `app_vbe.yaml`, `vbe-crossover` | yes | individual crossover rows (period, sequence, lot); dissolution per lot, test vs reference |
| DDI | `app_ddi.yaml`, `ddi-cyp3a4-victim`, `ddi_static_screening.yaml` | yes (perpetrators from the OSP library) | fm with provenance; Ki / IC50 / kinact with fu,inc; DDI ratios with 90% CI as relation facts (no landing shape today) |
| Special populations (pediatric, hepatic, renal, pregnancy, elderly) | `app_special_populations.yaml` | populations include `Pregnant`, `Preterm`; ontogeny present | population tag and demographics per study (age, gestational week, Child-Pugh, eGFR); physiology from the engine, never from client files |
| First in human | `app_fih.yaml` | species Rat, Mouse, Dog, Beagle, Minipig, Monkey, Rabbit | species per observation |
| Metabolites (stage SM) | MS-01 v1.3 | yes | analyte carried to the campaign (L-d) |
| Biologics (mAb, proteins): **roadmap 1** | draft checklist (inert) | PK-Sim has a large-molecule model, but the harvested catalog has no FcRn entries | harvest, then template and builder; a named scientist first |
| Dermal / transdermal: **roadmap 2** | draft checklist (inert) | no hits in the harvested catalog: PK-Sim has no built-in skin model | an engine decision first (a MoBi model or another engine), then as above |
| Ocular: **roadmap 3** | draft checklist (inert) | no hits in the harvested catalog: PK-Sim has no built-in eye model | as dermal |
| Inhalation, ADC, oligonucleotides, gene therapy | none | no hits in the harvested catalog | outside the tool's modeling scope; kept in the library, flagged |

**The owner's decision 2 (2026-11-12):** biologics, then dermal, then ocular are on the roadmap; each needs a named
scientist before its build starts. What this plan builds for them now: a **draft checklist** each (the client data to
ask for and how to check it), in the requirement-template format, marked `DRAFT` / `UNVERIFIED`, every PK-Sim location
`TO_HARVEST`, kept where the application registry does not load it, so no project can select it and no gate reads it.
What it does not build: calculators for FcRn recycling, skin flux or ocular scaling. Those would be model results
computed outside PK-Sim, which the ground rules exclude; they wait for the engine work above.

### 7.10 Speed
Parse once; map tables in parallel (A2 already runs 4 at once); LLM output is a small spec, not rows; a known layout
costs no LLM call. The target is G7 (§7.1): arrival to a reviewable exception list for a typical study in 15 minutes
with a GPU and a warm mapping cache, 45–60 minutes without a GPU; each stage's time is recorded per delivery.

### 7.11 Front door, both ways
Send each client, with the data request, the template (`client_template.py`, read with no AI) and a short data
specification: BLQ token and LLOQ, nominal and actual times, statistic and spread kind, dose basis, analyte and
matrix, one tab per study, dissolution conditions per profile (from the PBBM report template). A delivery that follows
it is read exactly; one that does not goes through the pipeline. On the way back, every missing requirement drafts a
line of the next client request.

## 8. Builds (revision 3: built in parallel against shared contracts)
The owner's instruction (2026-11-12): do all at once, no approval gate between builds except the locked-file PR. The
builds share code-level contracts (`docs/plans/2026-11-12-intake-contracts.md`: the models, the stores, who owns which
file), are built side by side, then merged, wired and reviewed. D6 follows the merge because a review screen needs
the others' real output; that is an engineering order, not an approval gate.

| Build | Scope | Gate | Where it goes |
|-------|-------|------|---------------|
| D0 | **The scoring harness only.** Answer-key format at value level, the scorer (by field, study, sub-domain; coverage and silent loss), the comparison of two analysts' keys, the baseline runbook for the server. The key itself is written by the scientist's analysts (§10, decision 8), never by this pipeline's builders | G1 | main line |
| D1a | **Landing fixes outside locked files:** the BLQ rule named and recorded (today's silent omission becomes an explicit, selectable rule, `UNVERIFIED`); SE and CV% converted to SD with n, as derived values; analyte and matrix carried to the campaign; n per timepoint; urine datasets | L-a, L-b, L-d, L-e, L-f | main line |
| D1b | **Locked file:** `run_pi.R` takes the error type (arithmetic or geometric SD) instead of naming every SD arithmetic | L-c | **its own PR**, merged only with the owner's approval (§10, decision 7) |
| D2 | **Source model:** parse once with anchors and parser version; PDF words and tables; Word grids and images; CSV dialects; ZIP unpacked and inventoried; several tables per sheet, tables across pages; content outside regions listed; unsupported formats said so; document role and table kind by rule; the **format inventory** tool (§10, decision 5) | G2, R-a … R-f | main line |
| D3 | **Mapper:** mapping spec v2, the cache with sign-off, rules first and the LLM for the rest (it never sees a numeric cell), the prose extractor under the strict check | U-a, U-b, U-e, U-f | main line |
| D4 | **Ledger and compute:** facts with anchors, append and supersede, partial facts, links, conflicts, relation facts, cross-file facts under the owner's five conditions; derived facts | G3, U-c, L-g, L-h | main line |
| D5 | **Checks and coverage audit:** silent loss, requirement status per study with the schema gap, PK-Sim import constraints, PBPK checks with overrides; missing items into the client request | G2, G4, G5 | main line (thresholds in an `UNVERIFIED` ruleset file) |
| D6 | **Review by exception:** source highlight, exceptions first, mapping accept, the spot check, signed confirmation, coverage panel; pipeline health in the admin console | G6, U-d | main line, after the merge |
| SD | **Sub-domain draft checklists** (biologics, dermal, ocular), inert (§7.9) | — | main line, outside the locked requirement templates |
| D7 | **Front door:** the data specification and the template with the data request | §7.11 | next |
| by evidence | OCR and images (GPU approved, §10 decision 4: adapters once the hardware and the format inventory are in); the hybrid plot digitizer; adapters for PPTX, email, SAS XPT, HTML/XML after the 30-day inventory; DDI relation landing | — | each its own build |

## 9. What stays
The vault and CLIENT_SUBMISSION artifacts; `modeler_intake.grid`; recipe + apply + validate + records; the cleaning
record; quote normalization; the reading queue and the tray (R1, R3); `ObservedDataset`, the dataset and dissolution
registers; `client_review` (group confirm, conflicts, aliases); the requirement templates, the data plan and the P3
gate; signatures and audit chains; `run_tool_loop`, AgentRun and the usage report; the PDF figures and the calibrated
digitizer; the template's no-AI path; the eval harnesses as scaffolding.

## 10. The owner's decisions (2026-11-12)
| # | Question | Decision |
|---|----------|----------|
| 1 | The merged design, gates as definition of done | **Approved**, on two conditions that are not waived: G4 is judged per study routing, never globally; a schema gap blocks release. Both are in the locked gates (§7.1) |
| 2 | Biologics, dermal, ocular | **On the roadmap**, in that order; each needs a named scientist before its build starts (§7.9) |
| 3 | Cross-file facts | **Yes**, under five conditions: explicit anchored link, unique match, `cross_file_linked` with three anchors, a reviewer's confirmation on first use per study, visible downstream (§7.6) |
| 4 | GPU | **Yes, to be provisioned**: one 24 GB-class card as the minimum; it is what the 15-minute target assumes. Without it the target is 45–60 minutes (G7) |
| 5 | Formats | **Plan for** ZIP, PPTX, email with attachments, images, SAS XPT / SAS7BDAT, HTML / XML. **Run a 30-day format inventory on real intake before the adapters' scope is frozen**: files by extension, scanned against native PDFs, documents with figures (D2 builds the tool) |
| 6 | Spot check | **Adopted**: 100 values per study drawn by strata, all values when a study has fewer; the model-deciding values and every overridden value always verified (§7.8) |
| 7 | D1 on the locked `run_pi.R` | **Its own PR**: a named reviewer who owns `run_pi.R` and one engineer who did not write the change; a before/after record attached; a rollback plan; **the owner's approval before merge** |
| 8 | The D0 answer key; the time target | **The scientist owns the key; a trained analyst fills it; a second analyst verifies it independently, disagreements to the scientist; the engineer builds the harness; whoever built the pipeline does not write the key.** The 15-minute target stays, as defined in G7 |

The owner's instruction with these: **do all at once**, D0 to D6 and the sub-domain checklists in parallel, with no
approval gate between builds beyond the locked-file PR of decision 7.

### 10.1 Three mismatches between the decisions and the plan, and how each was settled
The decisions were written without revision 2's text at hand. Where they and the plan differ, this is what was done:
1. **The gates.** The decisions' G1–G6 are not revision 2's G1–G6 (they have no "every file accounted for" and no
   time gate; revision 2 had no explicit override or sign-off gate). The locked set (§7.1) keeps the owner's six, in
   the owner's numbering, and adds the other two. The approval was conditional on this lock.
2. **What D1 is.** Decision 7 describes D1 as a fix to which files are read, with "no output change beyond files that
   were being dropped". D1 is the landing: files are read, and then BLQ points, SE and CV% errors and the analyte are
   lost before the fit (§3.3). Fixing that changes what the fit receives, by intent. So D1 is built to change as little
   as it can: the BLQ rule becomes explicit with today's behaviour as its default until the SME chooses another; the
   conversions are recorded as derived values; the one locked change (`run_pi.R`, the error type) is alone in its PR.
   The "before/after record" of decision 7 is, for this D1, what the campaign's profile holds before and after for a
   fixture (points, errors, analyte), not a list of files. The owner decides on the PR.
3. **Sub-domains.** Decision 2 says no sub-domain build starts without a named scientist; the closing instruction says
   to author all sub-domain schemas now. Settled as §7.9: draft checklists only, inert, `UNVERIFIED`, no scientist
   named yet; no calculators outside PK-Sim.

### 10.2 Deviations from revision 2, recorded
- **One unit library instead of four** (§7.3 stage 5) waits: one of the four tables is the locked `parameter_units.py`.
  New code calls the existing unit functions and adds no fifth table.
- **Docling** is not added in this build: its model weights could not be fetched in the build session, so it could not
  be tested. The built-in PDF path is pdfplumber (text-layer words, tables); the parser sits behind an interface so
  Docling can be added and scored on the server (D0) before it is trusted.
- **OCR and images**: the interface is built and a scanned page is reported as needing OCR; the engine itself comes
  with the GPU (decision 4).
- The builds go on the session's one branch, one commit per build, because this session may push there only; the
  locked-file change goes on its own branch and PR, as decision 7 requires.

## 11. Risks
- No public benchmark on PK listings: D0's gold set is the only proof, and it is small at first.
- Multi-table sheets with hierarchical headers are mis-bounded by every tool; the locate step needs its own tests.
- The coverage audit cannot see a table the parser never located; "content outside every region" is the safety net.
- The in-house model's mapping quality is unmeasured; D0 scores it before D3 relies on it.
- On scans, OCR text is the source: a string match cannot catch an OCR digit error (two engines + a person).
- Plot digitizing carries ~2–5% error on top of errors in the published figures.
- The spot check and the exceptions add review time; D0 measures whether review time falls overall.
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
- The owner's design: "The Universal PBPK Curation Pipeline (Merged, Sub-Domain-Complete, Multi-Reviewer
  Specification)", a conversation the owner shared on 2026-11-12 (not in the repository).
