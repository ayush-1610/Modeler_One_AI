# The client's data, reviewed where it belongs, and agents that work from the start (plan, 2026-11-05)

Status: **approved by the owner, being built** (revision 2: the owner's answers to §5, 2026-11-05; build A done).
Follows `2026-11-03-inputs-and-client-data.md` (I1–I4c, merged), whose
builds made the parts work one by one; the owner's use of them on a real delivery (14 files: BE workbooks, dissolution
profiling workbooks, the technical proposal) shows that together they do not yet give a clear, usable page. I5 (CDISC)
is set aside until later (the owner, 2026-11-05).

## The owner's ask (2026-11-05), with the two screenshots of the Inputs page
- **Everything went into Clinical studies.** Every client file is listed there, dissolution workbooks included, though
  each was tagged at upload. There is no way, after the agents, to say what a file or sheet really is and move it.
- **What is shown is not data.** "Random data": no data points, no graph, no metadata, no statistics, no separation
  between datasets, no categories. Cluttered, unorganised, confusing, even for a clean, labelled delivery; a real client
  sends messy workbooks (unreliable or irrelevant data, half the information here and there, mixed): the agent must
  recognise, clean and bring everything into the project.
- **Upload where the data belongs:** an "add files" button on Products and dissolution and on Clinical studies.
- **The compound agent is far too slow and thin:** 20–25 minutes without basic compound details that should take
  seconds. It should start as soon as the drug is known (on Start, while the person and A1 work there) and have the
  compound's values ready when the person reaches Inputs; and read any study or dissolution files already uploaded.
- **Start: the agent fetched little**, and not the most important fields: the question of interest, the context of use
  and the applications; the model risk (model influence, decision consequence, the model risk, how the model is used,
  what a wrong decision means, the internal target); the formulation types; the routes. It should propose them,
  **pre-selected**, for the person to confirm.
- **Plan it properly, step by step, user-friendly**, together; the owner can help with pages and examples.

## 1. What went wrong, and why (from the code; the server's run logs still to read, §4 step 0)
| What the owner saw | Why |
|---|---|
| Every client file under Clinical studies | The list of client files (`components/client/ClientFiles.tsx`) is drawn only on the Studies tab (`StudiesTab.tsx`). The upload tag (I1a) is stored and shown, but nothing places a file by it. |
| Dissolution not on Products and dissolution | Only the client-data template's Dissolution sheet, and sheets a person has read and saved, reach the dissolution register. Any other workbook waits for a person to open each sheet's reading form (or for A4 to propose a reading, which a person must still save). With 14 files that is dozens of manual steps, so nothing arrived. |
| "Random data", no points, graph, metadata, statistics | A file card shows the sheet-by-sheet triage (category, "Read this sheet"), not data. Data appear only after a reading is saved, and then as rows of text on the study card; the profile chart exists only for dissolution profiles already in the register. There is no per-study view of the points, no plot, no statistics. |
| Nothing to re-categorise after the agents | A file's tag can be changed in the Document Library, and a sheet's category under "change" on its line, but neither moves anything and neither is offered where the data is reviewed. |
| Compound agent 20–25 min, basics missing | A2 starts only when a person clicks "Ask the literature for what is missing". It searches Europe PMC and reads papers through the server's model, turn by turn (up to 120 turns). It uses no structured source. PubChem's record is fetched at Start for the drug's identity, but its molecular weight never becomes an input, so "Missing for S0 · Molecular weight" stays. |
| Start fields empty | A1 is told to "extract only what the documents state" and to mark a field missing otherwise. The context of use, the applications, the formulation types and the routes are usually implied by a proposal, not written as such, so A1 leaves them. The M15 ratings are, by the owner's decision of 2026-10-29 (#116), never proposed: the agent's suggestion is hidden until the person rates, so as not to anchor them. |

## 2. What a good result looks like (the target)
1. The person uploads the delivery once (on Start, on "+ Add data", or on the tab the data belongs to). Within a few
   minutes, without opening a single form, each study and each product appears **in its own tab, as data**: a chart of
   its profile(s), the table of points, its metadata, a few statistics, the files and cells it came from, and what is
   uncertain, each a question on its card.
2. Anything misread is fixed where it is seen: "this sheet is dissolution, not a study", "these two are one study",
   "ignore this sheet", "this column is the SD"; the change re-reads what depends on it.
3. Nothing loads until a person confirms the card (I2's rule holds); the review is the page, not a chain of forms.
4. When the person reaches Inputs, the compound's basic values are already there, with their sources, and the
   literature search is visibly working on the rest.
5. On Start, every field the proposal speaks to, directly or by implication, is proposed and pre-selected, each with
   the quote it rests on, for the person to confirm or change.

## 3. The design (built directly, no mockup first: §5 q6)

### 3.1 One intake pipeline: every client file read on arrival, landing where it belongs
- **On upload, from anywhere**, each file goes through the same steps in the background, and the page shows its progress:
  1. stored and tagged (I1a); the tab it was uploaded on sets its tag;
  2. **sorted**: each sheet (code's triage, then A4 for what code cannot sort) or each document page (code's inventory);
  3. **read automatically**: the template by code; any other data sheet by code's first reading (11/11 on the
     evaluation set since #134), then A4 where code's reading has a problem; documents by A4 (I4). Every reading is
     checked by code as today;
  4. **cleaned, with a record**: what was ignored (empty rows, notes, summary rows, irrelevant sheets), what was
     corrected (decimal commas, units converted by code), what is uncertain (a question on the card). Nothing silently;
  5. **placed**: each study on Clinical studies, each product on Products and dissolution, each compound value on
     Compound, "to confirm".
- **The person's tag is the default, the content can disagree:** a dissolution-tagged workbook with a concentration
  sheet asks on its card which it is ("this sheet reads like plasma concentrations; the file was tagged dissolution").
- **Re-categorise anywhere:** every card and every file has "this is…" (a study's data, dissolution, compound values,
  not data) and "belongs to…" (another study or product). The re-reading follows.
- **Messy deliveries are the design case**, not the exception: half a study in one file and half in another (I3 links
  them), irrelevant sheets (kept, marked "not data", one click to restore), unreliable values (flags from code's checks:
  a time going backwards, a value above 10× its neighbours, a BLQ above the LLOQ, a unit inconsistent with the dose).

### 3.2 The review: each study and each product as data
- **Clinical studies — one card per study (and arm):**
  - metadata: design, dose and regimen, route, food, dosage form, n, population and demographics, analyte, matrix, LLOQ,
    each with its source and peek (as today);
  - **a chart** of each profile (mean ± SD, or each subject), linear and log scale, BLQ points marked;
  - **the table of points** (time, value, SD, n, BLQ), with the cell each came from;
  - **statistics computed by code**: Cmax, tmax, AUC (from the points), compared with any NCA the client reported;
  - the files it came from, what was linked or set aside, and the questions and conflicts (I2–I4) on the card.
- **Products and dissolution — one card per product:** each medium's profile as a chart (mean ± SD, the vessels), the
  conditions (apparatus, rpm, medium, pH, volume), the batch, the Weibull fit, f2 against its reference, the release
  model, the composition as reported (I4b), and the files.
- **The files view** (a drawer, as today, made useful): per file, what it became (which studies and products, how many
  points), what was ignored, what is uncertain, its tag, "re-read" and "this is…".
- **Add files** on Clinical studies and on Products and dissolution (tag preset from the tab), as well as "+ Add data".

### 3.3 Compound inputs: fast, from the project's start
- **Structured sources first, by code, in seconds** (no LLM), each value with its source and grade
  (`evidence_grading.yaml`): PubChem (molecular weight and formula; computed XLogP flagged as predicted; experimental
  annotations such as pKa, logP and solubility where PubChem cites them), the FDA label (openFDA: §12.3 protein
  binding, volume, half-life, metabolism and excretion, quoted), and others the owner approves (§5 q2).
- **Started when the drug is known**, at project creation, in the background while the person and A1 work on Start;
  then A2 (literature) on what is still missing, with a time budget, its progress shown ("12 of 18 inputs found; now
  searching fu"), never a red "already running" banner.
- **Faster literature search:** what takes the time is the server model's turns; the plan is to measure first (step 0),
  then search per input in parallel, cap turns per input, and reuse what other projects of the same drug found (with
  the person's consent per project).

### 3.4 Start: every field proposed and pre-selected
- A1 proposes the context of use, the applications, the formulation types and the routes **from what the proposal
  implies**, each with the quote that supports it, marked "proposed by the agent" and pre-selected; the person confirms
  or changes. A field the proposal says nothing about stays a question.
- The model risk: the agent's influence and consequence suggestions, with "how the model is used" and "what a wrong
  decision means", **pre-selected** (this reverses the owner's decision of 2026-10-29, §5 q1); the risk tier and the
  internal target follow from the ratings as today; the person's confirmation is recorded.
- A1 is measured on real proposals (its evaluation set, P1's open item) so "nominal" becomes a number.

## 4. The build, in steps (each a PR to `main`, each with its browser test and screenshots)
Revision 2 (the owner's answers, §5): built directly, no mockup first (q6); the owner tests each build and sends
corrections. Step 0 (diagnose on the server) waits for the owner: the session cannot reach the server, and the owner
will check the builder with their own files later (q4), so the builds use the uploaded files and synthetic ones.
1. **A, quick fixes (S): built** (branch `inputs-r1-files-by-tab`).
   - Each client file is shown on the area its tag names: formulation on Products and dissolution, in vitro on
     Compound, clinical and bioanalytical on Clinical studies. A file tagged "other" whose content code reads as another
     kind is shown where that reading puts it, with the reading on its card ("Its content reads as clinical study: sheet
     “Sheet1” holds individual concentrations… Use it / Keep"); kept "other", it waits in the files view, which the rail
     counts ("1 to place").
   - "This file is…" on every file card and in the files view; a changed tag moves the file at once.
   - "Add files" at the top of Clinical studies, Products and dissolution, and Compound. A file takes the area's tag
     unless its name says what it is (a deviation from §3.1's "the tab sets its tag", recorded here: a workbook named
     "Dissolution …" dropped on Clinical studies still goes to Products and dissolution, which is the owner's first
     complaint); the notice names each file that went elsewhere and why.
   - The files view (the rail's "The client's files") lists every file with what it is, what it gave and "Open on
     <area>", which opens the area at the file.
   - The literature agent's progress replaces the red "already running": how long, its turn of the budget, the values
     proposed so far (`GET /projects/{id}/literature-run`, small, asked every 5 s while it runs); its end is said once.
   - Moved to B: the molecular weight from PubChem as an input (it belongs with the other structured sources).
2. **B, compound values from the start (M):** structured sources by code, started at project creation, then A2 on what
   is still missing, budgeted, with its progress (§3.3; q2, q3).
3. **C, the intake pipeline and the data cards (L):** automatic reading on upload (§3.1), "this is…" and "belongs
   to…" for each sheet and card, and one card per study and per product with its chart, points, metadata, statistics
   and files, reviewed one by one (§3.2; q5).
4. **D, Start proposals (M):** A1's implied fields with their quotes, and the M15 ratings pre-selected with the
   agent's reasons (§3.4; q1).
5. **The evaluation grows:** messy deliveries (the owner's own files, which the owner will use to check the builder,
   and synthetic ones modelled on them) scored end to end: placed right, read right, cleaned with a record, nothing
   silent.

## 5. Questions for the owner, and the answers (2026-11-05)
Answers, in the owner's words where quoted:
1. **Pre-select, with the reason.** "preselect (with reason, why?)": the agent's rating is pre-selected and its reason
   shown beside it; the person confirms or changes it. This reverses the decision of 2026-10-29 (#116).
2. **Sources:** "all of these and other which are accepted by FDA, or regulatory bodies and which are peer revise
   sources. ignore which ask for licenses." PubChem, openFDA / DailyMed labels, ChEMBL and other free regulatory or
   peer-reviewed sources; none that needs a licence (no DrugBank).
3. **Yes, start at project creation**, for now: "the goal is to get the data in place faster and correctly with
   sources"; load and cost are looked at later.
4. **Real files:** the owner has other data to check the builder with afterwards; for now, build and test with the
   uploaded files or synthetic ones.
5. **One by one:** "one by one study/product/data", easy to review, each clearly told apart from the others.
6. **Build directly**, no mockup: the owner tests and sends corrections.

The questions as asked:
1. **Pre-selected ratings:** on 2026-10-29 you chose to hide the agent's M15 suggestion until you rate, so it does not
   anchor you. Pre-selecting it reverses that. Pre-select (you confirm or change), or keep it hidden?
2. **Structured sources** the server may use for compound values: PubChem (in use), openFDA / DailyMed labels, ChEMBL,
   others? (DrugBank needs a licence.)
3. **Start the compound search at project creation**, in parallel with A1 on the server's model: acceptable for load
   and cost?
4. **Real files:** may the 14 files of this project (or de-identified copies) be used to build the evaluation set and
   to diagnose? Any other typical messy deliveries?
5. **Reviewing a large delivery:** per study and product on their tabs (as planned), or also file by file in one
   place first?
6. **Working together:** you offered to make pages. A mockup from me first (as last time), then your marks; or your
   pages first, which I then build to?
