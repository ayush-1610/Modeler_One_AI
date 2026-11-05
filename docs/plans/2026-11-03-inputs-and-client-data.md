# Inputs and client data: page review 2 (plan)

Status: **design agreed** (2026-11-03, revision 3, the owner's comments on the mockup). Page review 2 of
`docs/plans/2026-10-23-page-by-page-review.md`. Building: I1 and I2 first (§4).

**Mockup:** a clickable mockup on the owner's design canvas (private to the owner):
https://claude.ai/artifact/39yzfdipNQpwmKyZcyked6. Four screens, example data (a made-up drug, Examplazine):
1. Start from proposal (and "+ Add data" in the sidebar): upload and tag;
2. Inputs, Clinical studies: confirm inline;
3. Inputs, Products and dissolution;
4. Inputs, Compound: client values to confirm.

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

## The owner's answers (2026-11-03), on revision 1
**The page:**
- **Upload and tag at the start.** When the project is set up, the user uploads all files at once and tags each at a
  high level:
  - formulation or dissolution;
  - clinical study, optionally naming which one;
  - bioanalytical;
  - in vitro or physico-chemistry;
  - other.
- **Tags are hints to the agent, not facts.** If a file's content says otherwise, the agent proposes a different tag
  instead of trusting the label.
- **"+ Add data"** stays available later, with the same tagging.
- **No "Client data" area on Inputs.** What the agent extracts lands, marked "to confirm", where it belongs:
  - Products and dissolution;
  - Clinical studies;
  - Compound: the client's in vitro and physico-chemistry values (fu, permeability, enzyme kinetics, solubility).
    Compound therefore keeps a confirm step for client values.
- **Contradictions and the agent's questions** appear on the study or product card they concern.
- **One "To confirm (n)" counter and filter** across all areas replaces the separate review screen.
- **Clicking a value** opens its source, with the cell or quote highlighted.
- **The per-file view** becomes a side drawer, or the Document Library, rather than an area of its own.
- **Why this helps the agent:**
  - the tags narrow what it looks for in each file;
  - a study named at upload makes linking across files easier;
  - every question is asked where the user is already looking.
- **The separate "Client data" review screen:** "may be, but not sure it is required now." It is deferred (§3.3).

**The six questions:**
1. **Who confirms what:**
   - client data only;
   - per group (a study, a product, a set of compound values), with item-level edits;
   - items with an open conflict or question cannot be confirmed until settled, so a group confirm never waves them
     through.
2. **File types, in order:**
   - Excel and CSV (today);
   - then PDF and Word;
   - then CDISC `.xpt` (SDTM PC, PP, DM, EX; ADaM ADPC), moved earlier if clients usually send SDTM or ADaM;
   - OCR later; until then, scans are flagged "needs OCR" so nothing is silently skipped.
3. **Contradiction rules:** agreed, plus two additions (§3.5). Provisional, UNVERIFIED for the SME.
4. **Product detail:** keep composition and manufacturing as reported, shown, not used by the model. Nothing reported
   but unused is ever silently turned into a model value.
5. **Build order** (§4):
   - (a) file tagging at Start, and the Inputs page structure without a "Client data" area;
   - (b) inline "to confirm" review with the source panel, for what workbooks give today;
   - (c) linking across files (study, product and batch aliases) and contradictions;
   - (d) PDF and Word;
   - (e) CDISC `.xpt`;
   - (f) the evaluation set, grown alongside from (c) on.
6. **Mockup:** yes, of Start tagging and the inline confirm cards with the source panel, first (above).

## The owner's comments on the mockup (2026-11-03), revision 3
- **Tagging lives on the "Start from proposal" page** (the creation form, `/projects/start`) and in **"+ Add data"** in
  the left panel, which exists already. The project's Start step is unchanged. Option A + D of §3.7 is agreed.
- **No reasons asked, anywhere.** A conflict offers its options; the person selects one and then confirms the
  selection with a final button. The same holds for an explained difference and for an edit.
- **The source opens in a centre peek:** a modal in the centre of the screen over a dimmed, still-visible page (like
  Notion's centre peek). It opens from a small icon at the top right of each parameter card, and shows the source with
  the cell or quote highlighted. **Every project page that shows a source uses it.**
- **A resolved conflict stays where it was,** showing the final value with the alternative beside it, so the person
  sees what was decided. It can be changed until the group is confirmed.
- **File types:** Excel, CSV, Word and PDF are the common and important ones (how sponsors usually store and share
  formulation and clinical data: LIMS and Empower exports to Excel or PDF for dissolution, Excel or CSV exports for PK
  concentrations, PDF or Word for CSRs, protocols and validation reports). CDISC `.xpt` is optional, later.
- **The goal:** the client's data, whatever they send, loaded into the project correctly, clearly and easily. Then the
  compound's parameters fetched by the literature agent, in the project's context, with better tasks so that every
  input is found and filled, and the Inputs page ready for the next steps.

## 1. What exists today
**The page** (`apps/web/components/inputs/InputsWorkspace.tsx`): five tabs in PK-Sim's building blocks.
- **Compound:** one row per input, sources and alternatives beneath.
- **Formulations:** the proposal's products, each solid study's formulation, dissolution.
- **Individuals:** each study's individual.
- **Simulation settings.**
- **Studies:** the study table, plus the client's files and sheets (`components/client/`).
- **Beside the tabs:** a "still missing to run" list and the readiness checks.

**Where files arrive:**
- **The "Start a project" form** (`apps/web/app/projects/start/page.tsx`): one upload for the technical proposal, its
  annexes and the client's data files, sent as `files` and `client_files` to `projects:initiate`.
- **"+ Add data"** (`apps/web/components/library/AddData.tsx`): any time later, with what the file relates to and
  where it goes (client, annex, paper, context, proposal, other).
- **The Start page** (`apps/web/components/start/Blocks.tsx`) only lists the file names; it has no upload since #113.

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
| G4 | **No confirm step for client data beyond one sheet.** The sheet reader confirms one sheet at a time. Nothing shows, where the data lands, what the client's files became (values, studies, products, profiles), with its source, open questions and conflicts, and a way to confirm it. | Spread over the Studies and Formulations tabs |
| G5 | **Study and product metadata are thin.** Study: design, arms, regimen, route, food, population, demographics, analyte, matrix, LLOQ, bioanalytical method. Product: strength, batch, composition, dissolution conditions. Only some of these are captured. | Partly in `StudyRecord`, `DissolutionObservation` and the brief's products |
| G6 | **The page's organisation** (the owner's notes of 2026-10-23): raw ids as labels, the same source line repeated on every row, no grouping by building block, 40 identical individual forms, long tables, no profile preview, and the Studies tab carrying the client's files. | §4.1 of the page-review plan |
| G7 | **Other file types:** CDISC SAS transport files (SDTM PC/PP/DM/EX, ADaM ADPC) are the usual form of clinical data from sponsors. Scanned PDFs and images are not read. | Not read |
| G8 | **Files arrive untagged.** The upload says only "client" or not; nothing tells the agent that a file is a dissolution report or which study a PK sheet belongs to. | Role only (client, annex, paper, context, proposal, other) |

## 3. The design

### 3.1 Upload and tag (mockup screen 1)
Files are tagged **where they already arrive** (option A + D, §3.7, agreed): the "Start from proposal" page and "+ Add
data" in the left panel. The project's Start step is unchanged.
- **One upload** for everything: the proposal, its annexes and the client's files.
- **A tag per file**, from one short list:
  - technical proposal (the brief);
  - formulation or dissolution;
  - clinical study, with an optional study name ("EXZ-101");
  - bioanalytical;
  - in vitro or physico-chemistry;
  - other.
- **Code pre-fills the tag** where it can (a file name, a sheet name, a header row); the person changes it in one
  click. A file left untagged is "other": the agent then looks at everything in it.
- **The tag is a hint, not a fact.** The tag the person chose is kept, the agent's proposal sits beside it with the
  quote or cell that prompted it ("sheet Conc has the header Subject, Time, Conc"), and the person keeps one. Nothing is
  re-tagged silently.
- **Scans** are marked "needs OCR" at upload and listed as not read, so nothing is skipped without a trace.
- **"+ Add data"** asks the same tag, beside its existing "relates to".
- **Stored:** the tag, the optional study name and who set them, on the file's document record in the library, with
  the agent's proposal and the person's choice in its history.

### 3.2 The page: domains, with the client's data in its home
A left rail with the data domains replaces the five tabs. There is **no "Client data" domain**: the client's data
lands, marked "to confirm", in the domain it belongs to.

| Domain | What it holds | Organised by |
|---|---|---|
| **Compound** | The CPF's inputs, and the client's in vitro and physico-chemistry values to confirm | Building block sections: identity and physico-chemistry · binding and partitioning · permeability and absorption · elimination by process (each enzyme, renal, biliary, transporters) · DDI parameters · metabolites. Each row has a plain label from the registry (`parameters/registry.yaml`), one source line with the others behind "n more", and a chip for fixed, measured or fittable. A client value sits in its row beside the literature, marked "to confirm" |
| **Products and dissolution** | Each product (test, reference, solution) | One card per product: strength, batches, dissolution conditions and profiles as a chart per medium, the Weibull fit, the release model, f2 against its reference, the studies that use it, and composition and manufacturing **as reported, not used by the model** (§3.6) |
| **Clinical studies** | Each study | One card per study, grouped by kind (IV, oral fasted, fed, multiple dose, DDI, special populations): design, arms, dose and regimen, route, product, food, population and demographics, analyte, matrix, LLOQ, the observed profile as a chart, the NCA, the role proposed, and the files and cells it came from ("linked across 3 files") |
| **Populations and individuals** | The populations the proposal names, and each study's individual | Grouped: the studies sharing one individual are one line; a patient study given the healthy default is a warning |
| **Simulation settings** | Calculation methods, values set on the simulation, solvers | One summary line until something differs from PK-Sim's defaults |

**Across all domains:**
- **"To confirm (n)"** at the top of the rail: one counter over every area, and a filter that shows only what waits
  for the person. Each domain in the rail shows its own count.
- one search box over labels, ids, values and sources;
- filters: to confirm, conflicts, from the client, from the literature, missing;
- "still missing to run" stays on the side, and each item opens where it is settled;
- **"Files"**: a side drawer listing each file and what it gave ("EXZ-101: 1 dataset; a dose that disagrees"),
  linking to the Document Library for the full file.

### 3.3 Confirm inline (mockup screens 2–4)
The review happens on the cards, in each domain.
- **A group** is a study, a product, or a set of compound values from one delivery. It shows "to confirm · n" until
  confirmed, then "confirmed by you · loaded".
- **Each value** carries its source: the file and the cell, page or quote. **A small icon at the top right of each
  parameter card opens the source in a centre peek:** a modal in the centre of the screen over the dimmed, still-visible
  page, with the sheet's grid and the cell highlighted, or the page with the quote highlighted. The same peek serves
  every project page that shows a source (the brief on Start, the inputs, the MAP review).
- **A conflict card** sits on the card it concerns: the values side by side, each with its source. The person selects
  one, or that they are different things (two cohorts, a release and a stability run), and confirms the selection with
  a final button. **No reason is asked.** What the agent noticed that may explain it is shown ("the sheet's title says
  Stability 6 M"); it never decides.
- **A resolved conflict stays in place:** the final value, marked "resolved", with the alternative beside it and its
  source. It can be changed until the group is confirmed.
- **A question card** asks for the one answer it needs (a paddle speed not stated, an LLOQ missing, a batch no other
  file names, the pH of a Caco-2 run), offering the answer another file gives where one exists.
- **A difference marked explained:** n dosed against n PK-evaluable is a difference, not a conflict, once the person
  marks it explained (§3.5).
- **Item-level edits:** any item can be edited before the group is confirmed; the change and the old value are
  recorded, and code re-checks the item.
- **The group confirm** is disabled while any of its items has an open conflict or question, and says how many are
  open. Confirming loads the group (evidence, datasets, profiles, study and product facts) in one audited event (who,
  when, what, the options shown and the one selected, from which files). It is not an electronic signature; the
  signature, with the person's justification, stays at the MAP.
- **Afterwards:** a confirmed value shows in its row with its client source. A file sent again is compared with what
  it replaces, and only the changes return to "to confirm".
- **The literature and the published model** keep D-27: their values flow in with quotes and grades and are reviewed
  at the MAP signature (the owner's answer 1). The page says so where they appear.

**The separate "Client data" review screen (revision 1, §3.3) is deferred.** The inline review covers the owner's
ask. If large deliveries later need one place to go through a whole delivery file by file, the Document Library can
gain that view; nothing in the inline design blocks it.

### 3.4 The client-data agent
It **extends A4** from one sheet at a time to the client's whole delivery. Code does what code can, the agent proposes
the rest, and every proposal is checked by code before a person sees it (principles 3–5 of the start-up plan §14.1).
Proposed name: **A4 · Client Data Agent**, in six stages.

1. **Ingest** (code; exists for workbooks, PDF and Word). Every file goes to the document library with its tag.
   - CDISC SAS transport files (`.xpt`): SDTM PC, PP, DM, EX and ADaM ADPC are read by code, with no AI, because the
     standard defines every column (build (e)).
   - Scanned PDFs and images are flagged "needs OCR" and not read in this plan.
2. **Inventory:** what each file holds, **starting from its tag**.
   - The tag narrows the search: a "formulation or dissolution" file is searched for products, batches, composition,
     conditions and dissolution tables first; a "clinical study" file for design, dosing, demographics and PK.
   - When the content disagrees with the tag, the agent proposes another tag, quoting what it found (§3.1).
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
   - A **study registry** with aliases ("Study 101" = "EXZ-101"): the agent proposes the link with the quote that
     shows it (a protocol number on the CSR's cover), and code checks it. **A study named at upload seeds the
     registry**, so the agent links to it rather than guessing.
   - Arms, products, batches and analytes are linked the same way. A batch or study no other file names becomes a
     question on the card, never a guess.
   - Each record gets its context: fasted or fed, dose, statistic (individual, mean, geometric mean), matrix.
5. **Reconcile** (code). Across all records of one study, product or batch, code finds:
   - **duplicates:** the same values from two files, which become one item with both sources;
   - **contradictions:** the same field with different values, by the rules in §3.5. They are shown side by side on the
     card and never resolved silently;
   - **gaps** against the data plan (`reconcile`, as today).
6. **Map:** to the project's targets, each with "where it goes" in plain words:
   - evidence for CPF parameters (Compound);
   - observed datasets, profiles or reported PK (Clinical studies);
   - dissolution profiles, products and formulations (Products and dissolution);
   - study facts and demographics (Clinical studies, Populations).

   **Nothing loads until a person confirms the group** (§3.3).

**Evaluation** (start-up plan principle 7), grown alongside from build (c): `reading_eval` grows from single sheets to
client deliveries.
- Each delivery is a synthetic set of files with a known answer:
  - a protocol PDF;
  - a demographics sheet;
  - a PK workbook in another layout;
  - a dissolution report;
  - a mis-tagged file;
  - a planted contradiction, and a planted explained difference (n dosed against n evaluable).
- The agent is scored on what it found, tagged, linked, mapped and flagged. Real client files are scored only on the
  server.

### 3.5 When values count as contradicting (provisional, UNVERIFIED)
A data rule, `client_reconciliation.yaml`, version 0.1, **UNVERIFIED** until the SME signs it; SME-governed from then
on.

| Field | Contradiction when |
|---|---|
| Text and categorical (route, food, study design, product, analyte, matrix) | They differ after normalising (case, spacing, known synonyms) |
| Dose, strength | They differ **after unit conversion** (10 mg and 10000 µg agree) |
| n | They differ, unless the person marks the difference **explained** (n dosed against n PK-evaluable) |
| Concentrations, dissolution | They differ by more than 10 %, as for D-32 |

### 3.6 Product detail
- Composition, manufacturing and other reported details are **kept as reported**, shown on the product card under
  "as reported, not used by the model": context for the reviewer and the report.
- Only strength, release and the dissolution conditions and profiles feed PK-Sim.
- **Nothing reported but unused is ever silently turned into a model value.**

### 3.7 Start against Inputs: where tagging happens (decided: A + D)
The owner's answer 4 of 2 November: "all inputs in inputs page, start page will structure the project". Tagging at
upload splits the flow: upload and tagging at the start, all reading, reviewing and confirming on Inputs.

What the code shows: **files already arrive before the Start page.** The "Start a project" form takes the proposal and
the client's files in one upload; "+ Add data" takes the rest later. The Start page itself only lists the names (§1).

| Option | Where tags are set | Answer 4 | The agent |
|---|---|---|---|
| **A (recommended)** | On the creation form and in "+ Add data", where files already arrive | Holds: nothing is read or confirmed at the start, and the Start page stays about structure, with at most one line ("9 client files received; their data is read on Inputs") | Reads in the background from the moment of upload, with the tags |
| B | On the Start page, as a step of its own | Bent: Start gains an inputs task | The same, but only once the step is done |
| C | On Inputs, in an intake strip, files uploaded untagged | Holds fully | Starts later, without hints; tagging moves away from the moment the person knows the files best |
| D | Editable any time, in the files drawer or the Document Library | Holds | A changed tag re-reads only that file |

**Agreed: A + D** (the owner, 2026-11-03). The tag is set at the one moment files are uploaded, which is where the person knows best what
each file is, and it stays editable later. Answer 4 holds in substance: the Start page structures the project, and
every value is read, reviewed and confirmed on Inputs. The mockup (screen 1) shows A.

## 4. The build, in PRs to `main`
In the owner's order (answer 5).

| PR | What | Locked files |
|---|---|---|
| **I1 · Tags and the page** (a) | Tags at upload on the "Start from proposal" page and "+ Add data" (§3.1): the tag list, code's pre-fill, the study name, "needs OCR" for scans, the tag on the document record. The domain rail without a "Client data" area (§3.2): compound sections with plain labels, product cards, study cards with profile charts, populations grouped, settings as one line, search, filters, the files drawer, and the centre peek for sources on every project page. No new data | None |
| **I2 · Confirm inline** (b) | For what workbooks give today: "to confirm" on the cards in each domain, the "To confirm (n)" counter and filter, the source panel with highlighted cells, item-level edits, select-then-confirm for each conflict, resolved conflicts kept in place, the group confirm, loading on confirm and its audit event. The agent's tag proposal shown beside the person's | None |
| **I3 · Across files** (c) | The study, product and batch registry with aliases, seeded by the study names given at upload. Code's reconciliation: duplicates, contradictions, gaps. The conflict, question and explained-difference cards on the study and product cards. The rules of §3.5 as `client_reconciliation.yaml` 0.1, UNVERIFIED. The evaluation set starts here (f) | None (a new data rule, SME-governed once the SME signs) |
| **I4 · Documents** (d) | A4 reads client PDF and Word: inventory from the tag, table extraction with verbatim checks, study and product facts, landing as "to confirm" on the cards | None |
| **I5 · CDISC** (e), optional | SDTM PC, PP, DM, EX and ADaM ADPC read by code from `.xpt`, with no AI (a new dependency for reading SAS transport files, to be approved). Later: Excel, CSV, Word and PDF come first (the owner, 2026-11-03) | None |
| **I6 · The evaluation** (f) | Built alongside from I3: synthetic deliveries with known answers, the agent's score per stage, one more delivery per build | None |

Each PR: a CHANGELOG entry, the coverage table if a stage changes, tests and a browser test, and a screenshot in the PR.

**Progress (2026-11-05).** I1 (#126, #127), I2 (#128) and A2's tasking (#129) are merged. I3 is in its PR: study aliases (ids written differently, a link asked when an upload tag names the study otherwise), a profile given twice loaded once, differing profiles and dissolution a conflict, and the first five deliveries of I6. **Deviation:** product and batch aliases (a product or batch written two ways) move to after I4, since the names they are matched by come from the documents I4 reads (a protocol's "also known as", a certificate of analysis); in I3 a product is matched by its exact name, as the dissolution register keys it.

**Progress (2026-11-05, later).** I3 is merged (#130). I4 is in its PR: code's page inventory of a client PDF or Word file, and the reading agent's proposals (study facts, concentration and NCA tables, dissolution tables, study-name links, figures to digitize), each checked by code against its page and landing in its study or product to confirm. **Deviation:** demographics and composition are listed by the inventory but not yet proposed as values (the study record's demographics and the product card's "as reported" composition follow); scans stay unread until OCR.

## 5. For the owner
Settled on 2026-11-03: tagging (A + D), the file-type order (CDISC optional), the mockup comments. Next: the builds,
in order, each a PR to `main`; then the literature agent's compound parameters (A2: better tasks, the project's context,
every needed input found).
