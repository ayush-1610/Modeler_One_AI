# Inputs and client data: page review 2 (plan)

Status: **design for the owner** (2026-11-03). Page review 2 of `docs/plans/2026-10-23-page-by-page-review.md`.

## The owner's ask (2026-11-03)
- **All project data captured on Inputs:** the compound, the client's formulation and dissolution data, the clinical
  studies, and anything else the project needs.
- **A structured page:** parameters grouped logically, scalable, easy to navigate, find and manage.
- **Unstructured client data:**
  - every client organises its data differently, across many files, formats, sheets and documents;
  - the data are scattered, and sometimes contradictory, which must be flagged;
  - one robust way must bring them together, read each in its context, and map it to the project's parameters, data
    and metadata.
- **An AI agent for it**, designed or extended: ingest, analyse, contextualise and organise, with particular attention
  to dissolution and clinical studies.
- **A clear review interface:**
  - inspect the data;
  - check each value's context and source;
  - edit or correct;
  - **explicitly accept and confirm before anything is loaded into the project.**

## 1. What exists today
**The page** (`apps/web/components/inputs/InputsWorkspace.tsx`): five tabs in PK-Sim's building blocks.
- **Compound:** one row per input, sources and alternatives beneath.
- **Formulations:** the proposal's products, each solid study's formulation, dissolution.
- **Individuals:** each study's individual.
- **Simulation settings.**
- **Studies:** the study table, plus the client's files and sheets (`components/client/`).
- **Beside the tabs:** a "still missing to run" list and the readiness checks.

**The client-data pipeline** (`modeler_project.client_data`, `modeler_intake`):
1. **Every file is stored as a document first** (`DocumentLibrary`): workbooks become quotable rows, PDF and Word
   become pages.
2. **The client-data template is read cell by cell, with no AI** (`client_template`). Each study arm becomes an
   observed dataset; physico-chemistry and in vitro rows become evidence; dissolution and product rows are kept.
3. **Any other workbook is triaged sheet by sheet:**
   - code classifies first (`triage`, 11 categories);
   - agent A4 classifies the sheets code leaves OTHER (`sheet_triage`), quoting the header cell, which code checks.
4. **Each data sheet is read through a reading form:**
   - code fills it first (`sheet_form.suggest`);
   - A4 corrects it (`sheet_reader.propose_reading`), and every unit, LLOQ, dose and n must cite a cell that holds it;
   - a person checks the preview and saves. The saved reading is a confirmed **recipe**, reused without AI when the
     same layout arrives again (`recipe`, header fingerprint).
5. **Applied by code** (`apply`, `validate`): canonical records (`ConcentrationObservation`,
   `DissolutionObservation`), each keeping its cells. From them come observed datasets (origin CLIENT) and
   dissolution profiles (`dissolution_register`), with Weibull fits, f2 and a release model a person proposes.
6. **Reconciliation against the data plan** (`client_data.reconcile`): per client item, delivered, partial, missing or
   not available, and what arrived that the plan did not ask for.
7. **PDF and Word files** are documents that A1 (the brief) and A2 (parameter values) read and cite. **No agent reads
   client data out of them.**

**Conflicts:**
- **Parameters:** values beyond 2-fold conflict, and a person keeps one (D-32, `sources.select`).
- **Template brief check:** the template's study facts are checked against the brief (`_brief_mismatches`).
- **NCA check:** our NCA of a mean profile is checked against the reported NCA (20 %).

**How values enter:** D-27 (owner, 2026-10-18) says values flow in without a per-item decision, and a person reviews
everything once, at the MAP signature. Client sheets are the exception today: nothing is read until a person saves the
sheet's reading.

## 2. The gaps
| # | Gap | Today |
|---|---|---|
| G1 | **Client documents are not read for client data.** A CSR, a protocol synopsis, a formulation or dissolution report, or a bioanalytical report in PDF or Word yields no study design, dose, demographics, PK table, composition or dissolution profile. | Only workbooks are read; documents serve A1 and A2 |
| G2 | **No picture across files.** One study is often spread over a protocol (design), a demographics sheet, a dosing sheet and a PK sheet, under different names ("Study 001", "D1690C00001", "MB102-001"). Each sheet is read alone, so nothing links them, and nothing finds the same data given twice or given differently. | Parameter conflicts only (D-32) |
| G3 | **Contradictions within the client's data are not flagged:** a dose of 10 mg in the protocol and 5 mg in the PK sheet; n = 12 against n = 14; two LLOQs; one batch's dissolution reported twice with different values; a product's strength. | Not detected |
| G4 | **One staged review is missing.** The sheet reader confirms one sheet at a time. Nothing shows everything the client sent and what it became (values, studies, products, profiles), with its source, open questions and conflicts, and one place to confirm it. | Spread over the Studies and Formulations tabs |
| G5 | **Study and product metadata are thin.** Study: design, arms, regimen, route, food, population, demographics, analyte, matrix, LLOQ, bioanalytical method. Product: strength, batch, composition, dissolution conditions. Only some of these are captured. | Partly in `StudyRecord`, `DissolutionObservation` and the brief's products |
| G6 | **The page's organisation** (the owner's notes of 2026-10-23): raw ids as labels, the same source line repeated on every row, no grouping by building block, 40 identical individual forms, long tables, no profile preview, and the Studies tab carrying the client's files. | §4.1 of the page-review plan |
| G7 | **Other file types:** CDISC SAS transport files (SDTM PC/PP/DM/EX, ADaM ADPC) are the usual form of clinical data from sponsors. Scanned PDFs and images are not read. | Not read |

## 3. The design

### 3.1 The page: domains, not one long list
A left rail with the data domains replaces the five tabs. Each domain shows its progress (what is in, what needs you,
what is missing) and opens on a structured view:

| Domain | What it holds | Organised by |
|---|---|---|
| **Client data** (new, first) | Every file the client sent, what the agent found in it, and the review where it is confirmed (§3.3) | File, then what each item became |
| **Compound** | The CPF's inputs | Building block sections: identity and physico-chemistry · binding and partitioning · permeability and absorption · elimination by process (each enzyme, renal, biliary, transporters) · DDI parameters · metabolites. Each row has a plain label from the registry (`parameters/registry.yaml`), one source line with the others behind "n more", and a chip for fixed, measured or fittable |
| **Products and dissolution** | Each product (test, reference, solution) | One card per product: strength, batch, composition (as reported), dissolution profiles as a chart per medium, the Weibull fit, the release model, f2 against its reference, and the studies that use it |
| **Clinical studies** | Each study | One card per study, grouped by kind (IV, oral fasted, fed, multiple dose, DDI, special populations): design, arms, dose and regimen, route, product, food, population and demographics, analyte, matrix, LLOQ, the observed profile as a chart, the NCA, the role proposed, and the files and cells it came from |
| **Populations and individuals** | The populations the proposal names, and each study's individual | Grouped: the studies sharing one individual are one line; a patient study given the healthy default is a warning |
| **Simulation settings** | Calculation methods, values set on the simulation, solvers | One summary line until something differs from PK-Sim's defaults |

**Across all domains:**
- one search box over labels, ids, values and sources;
- filters: needs you, conflicts, from the client, from the literature, missing;
- "still missing to run" stays on the side, and each item opens where it is settled.

### 3.2 The client-data agent
It **extends A4** from one sheet at a time to the client's whole delivery. Code does what code can, the agent proposes
the rest, and every proposal is checked by code before a person sees it (principles 3–5 of the start-up plan §14.1).
Proposed name: **A4 · Client Data Agent**, in six stages.

1. **Ingest** (code; exists for workbooks, PDF and Word). Every file goes to the document library. New:
   - CDISC SAS transport files (`.xpt`): SDTM PC, PP, DM, EX and ADaM ADPC are read by code, with no AI, because the
     standard defines every column;
   - scanned PDFs are flagged as needing OCR (not read in this plan).
2. **Inventory:** what each file holds.
   - Sheets: code first, as today.
   - Documents: the agent lists the sections, tables and figures that hold project data (study design, demographics,
     PK table, dissolution table, composition, bioanalytical method). Each item cites its page and a heading or
     caption quote, which code checks.
3. **Extract:** each item read into a canonical record that keeps its source.
   - Sheets through a confirmed reading (recipes, as today).
   - Document tables row by row: each row's quote must contain its numbers, as A3 does for papers.
   - Study facts and product facts field by field, each with its quote.
   - Code converts every unit; the agent never computes a number.
4. **Contextualise:** link every record to what it describes.
   - A **study registry** with aliases ("Study 001" = "D1690C00001"): the agent proposes the link with the quote that
     shows it (a protocol number on the CSR's cover), and code checks it.
   - Arms, products, batches and analytes are linked the same way.
   - Each record gets its context: fasted or fed, dose, statistic (individual, mean, geometric mean), matrix.
   - What no file states becomes a question for the person, never a guess.
5. **Reconcile** (code). Across all records of one study, product or batch, code finds:
   - **duplicates:** the same values from two files, which become one item with both sources;
   - **contradictions:** the same field with different values. They are shown side by side and never resolved
     silently; tolerances are a provisional data rule for the SME, like D-32;
   - **gaps** against the data plan (`reconcile`, as today).
6. **Map:** to the project's targets, each with "where it goes" in plain words:
   - evidence for CPF parameters;
   - observed datasets (profiles, or reported PK);
   - dissolution profiles;
   - products and formulations;
   - study facts and demographics.

   **Nothing loads until a person confirms it** (§3.3).

**Evaluation** (start-up plan principle 7): `reading_eval` grows from single sheets to client deliveries.
- Each delivery is a synthetic set of files with a known answer:
  - a protocol PDF;
  - a demographics sheet;
  - a PK workbook in another layout;
  - a dissolution report;
  - a planted contradiction.
- The agent is scored on what it found, linked, mapped and flagged. Real client files are scored only on the server.

### 3.3 The review: "Client data"
One screen, the first domain on Inputs, laid out in three columns.
- **The files strip at the top:** each file with its type, its status (stored, read, n items found, questions,
  conflicts), and the agent's progress while it runs.
- **Left:** what the delivery became, grouped by target (compound values, products and dissolution, clinical studies,
  not mapped). Each group shows counts: to review, conflicts, questions, confirmed.
- **Centre:** the items of the selected group, as cards.
  - An item shows its value, unit and the PK-Sim unit it becomes, what it maps to (a plain label), its context (study,
    arm, product, batch), and the agent's confidence.
  - A dataset item shows its profile as a chart, and a dissolution item its curves.
  - A study item shows its facts with the files each came from.
- **Right:** the source, always visible for the selected item. A sheet shows the grid with the cited cells
  highlighted; a document shows the page with the quote highlighted.
- **A conflict card** shows the values side by side with their sources. The person keeps one, or splits them (they
  are different things: two arms, two batches), or rejects both, with a reason.
- **A question card** (a unit not stated, an LLOQ missing, a study link unsure) asks for the one answer it needs.
- **Actions:**
  - edit a value, unit, target or context inline (code re-checks it);
  - reject with a reason;
  - confirm one item, or **confirm a whole group** once it has no open question or conflict.
- **Confirming loads** the items into the project: evidence, datasets, profiles, study facts. It is an audited event
  (who, when, what, from which files), not an electronic signature. The signature stays at the MAP.
- **Afterwards:** what was confirmed shows in the domains with its client source. A file sent again is compared with
  what it replaces, and only the changes need confirming.

### 3.4 What changes against D-27
D-27 lets values flow in without a per-item decision. The owner's ask adds an explicit confirmation **for client
data**: nothing from a client file loads until a person confirms it. That is today's rule for sheets, widened to every
client file and grouped, so it stays quick. The literature and the published model keep D-27 unless the owner decides
otherwise (question 1).

## 4. The build, in PRs to `main`
| PR | What | Locked files |
|---|---|---|
| **I1 · The page** | The domain rail, the compound sections with plain labels, product cards, study cards with profile charts, populations grouped, settings as one line, search and filters. No new data | None |
| **I2 · The review** | "Client data": the staging area for what workbooks give today. Items, groups, the source panel with highlighted cells, edit, reject, confirm one or a group, loading on confirm, and its audit event | None |
| **I3 · Across files** | The study, product and batch registry with aliases. Code's reconciliation: duplicates, contradictions, gaps. The conflict and question cards. The tolerances as a data rule, UNVERIFIED (version 0.1) | None (a new `client_reconciliation.yaml`, SME-governed once the SME signs) |
| **I4 · Documents** | A4 reads client PDF and Word: inventory, table extraction with verbatim checks, study and product facts | None |
| **I5 · CDISC** | SDTM PC, PP, DM, EX and ADaM ADPC read by code from `.xpt`, with no AI (a new dependency for reading SAS transport files, to be approved) | None |
| **I6 · The evaluation** | Synthetic client deliveries with known answers; the agent's score per stage | None |

Each PR: a CHANGELOG entry, the coverage table if a stage changes, tests and a browser test, and a screenshot in the PR.

## 5. For the owner
1. **Confirmation:**
   - **Scope:** only client data (recommended), or also the literature agent's values and the published model's?
   - **Granularity:** per group (a study, a product, a set of compound values) with per-item edits (recommended), or
     every item one by one?
2. **File types, in order:** Excel and CSV (today), then PDF and Word (I4), then CDISC `.xpt` (I5)? Scanned PDFs and
   images (OCR) later?
3. **Contradiction rules** (a provisional data rule for the SME):
   - Text and categorical fields (route, food, study design, product): exact match after normalising.
   - Dose, n and strength: exact.
   - Concentrations and dissolution: the same 10 % as D-32.

   Agreed?
4. **Product detail:** record the composition and manufacturing details as reported (shown, not used by the model).
   Only strength, release and dissolution conditions feed PK-Sim. Agreed?
5. **Order:** I1 (the page) and I2 (the review) first, then I3 across files, then I4 documents? Or the review and the
   agent first?
6. **A clickable mockup** of the review screen (§3.3) before I2 is built: yes or no?
