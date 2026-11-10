# Add data: the reading agent reads every file it is given, together (plan, 2026-11-10)

Status: **DRAFT, for the owner's decisions (§5).** Nothing here is built yet.

## 1. What the owner saw
The owner added a whole client delivery at once with **+ Add data** in the sidebar (Desvenlafaxine: PK and concentration
tables for 093-26 and 094-26, individual and mean plots in Word, study-report synopses and concentration listings in
PDF, an IV study, an outlier report, dissolution workbooks with several sheets, media and pH, a data-request workbook).
The agent did not start on them. Uploading files again from the Dissolution and Studies tabs on Inputs did start it.
The owner's requirement: one upload of everything, and the agent works through all of it with the context of the other
files (which study, which product, which formulation, which medium and pH) and puts each value where the model needs it,
quoted, for a person to confirm.

## 2. What the code does today (traced 2026-11-10)
Both routes use the same endpoint and the same background reader: `POST /projects/{id}/client-data` →
`ingest` per file → `intake_jobs.read_later` → one `reading` job that runs `run_arrival_job` file by file
(A4 document reading for PDF/Word; A4 triage and sheet reading for workbook sheets code could not sort or read cleanly).
The routes differ in what reaches that reader, and in what happens when the reader is busy:

| # | Gap | Where | Effect on the owner's upload |
|---|-----|-------|------------------------------|
| G1 | A file marked as a **document** (Annex, Paper, Context, Other) goes to `POST /documents`, which stores it and **never reads it for data**. "Add data" guesses *Annex* for every name that matches no rule. | `AddData.tsx` `guessGoes`, `lib/fileTags.ts` `guessTag` fallback; `brief_api.upload_documents` | Summary statistics, outlier report, mean plots, the IV study and other PDFs/Word files were stored but never read. |
| G2 | **One reading job per project, and a busy one drops the new files.** `read_later` returns `False` when a reading is running (from Start, an earlier upload, or a button) and nothing queues them or tells anyone. | `intake_jobs.read_later` → `jobs.start(... busy=...)` | Files added while Start's reading still ran were never read. A later upload on a tab found the reader free, so "it works from the tab". |
| G3 | A file already uploaded (same bytes) is a **repeat** and is skipped. | `client_api.upload_client_files` (`not r.get("repeat")`), `_needs_agent` | Re-adding a file does not start a reading. |
| G4 | **Each file is read alone.** The agent sees one file at a time, so 093-26's PK table, concentration table, plots and synopsis are not read as one study, and a dissolution sheet is not linked to the product or batch a synopsis names. | `run_arrival_job`, `document_reader.read_and_record` | Facts in one file that explain another (dose, formulation, fed/fasted, batch, medium) are not used. |
| G5 | **No status.** "Add data" closes with "added as client data"; nothing says the agent is reading, how far it got, what it found or that it was skipped. | `AddData.tsx`, Inputs | The owner cannot tell whether the agent is working. |
| G6 | **Agents off → silent.** With no chat model configured, `read_later` returns `False` with no message. | `agent_jobs.chat_model` | To be checked on the server. |
| G7 | **Figures** (plots in Word/PDF) are digitized only when a person asks (evidence digitize), not on arrival. | `evidence_api` digitize | Mean and individual plots are not turned into data. |

## 3. Proposed workflow
One rule: **every file added with "Add data", on any page, is read by the agent unless the person says not to.**

1. **Upload (unchanged UI, one change):** the per-file choice becomes *what it is* (clinical, dissolution, …, or
   "document") plus a checkbox **"Read for data"**, on by default for every PDF, Word and workbook, including documents
   (fixes G1). Proposal and literature papers keep their own readers.
2. **A reading queue per project, not a single slot (G2, G3):** arrivals are appended to a persisted queue
   (`reading-queue` artifact: file, why, added by, state). One worker drains it in order; a new upload while it runs
   adds to the queue instead of being dropped. A file can be put back in the queue by hand ("Read again").
3. **Read as a delivery, not file by file (G4):** before the per-file readings, one **delivery pass** (A4, short) reads
   every new file's name, sheet names, headers and first page, and drafts a **delivery map**: which files belong to
   which study (093-26, 094-26, 230-23, 231-23), which product/strength/batch, fed or fasted, which sheets are
   dissolution and with which medium and pH. Code checks every link against a quote. Each per-file reading then gets
   the map as context, so a synopsis's dose and design reach the PK and concentration tables of the same study.
4. **Figures on arrival (G7):** a page whose text says it is a plot with no table behind it is queued for the
   existing digitizer, marked as digitized data (lower trust, never preferred over a table of the same values).
5. **Status everywhere (G5, G6):** "Add data" ends with "The agent is reading 17 files" and a link; Inputs shows a
   **reading tray**: queued / reading / done / needs you, per file, with what was found (n datasets, n dissolution
   profiles, n facts) and what was refused and why. With agents off, the tray says so and lists each file's manual route.
6. **Nothing enters the model unconfirmed (unchanged):** every value stays a proposal on its study or product card with
   its quote, until a person confirms it (CPF stays the system of record; ground rules unchanged).

## 4. Builds (each its own PR, smallest first)
| Build | Scope | Fixes |
|-------|-------|-------|
| R1 | Reading queue (persisted), arrivals appended, drained by one worker; "busy" no longer drops files; repeats can be re-queued. API + test. | G2, G3 |
| R2 | "Read for data" on documents in Add data (default on); `/documents` uploads with it set go through `ingest` as client files too. | G1 |
| R3 | Reading tray on Inputs + status line in Add data; agents-off message. API `GET …/reading-queue`, OpenAPI updated. | G5, G6 |
| R4 | Delivery pass and delivery map as context for each reading; links quoted and checked by code. | G4 |
| R5 | Figures on arrival through the existing digitizer, marked as digitized. | G7 |
| R6 | Acceptance: the owner's Desvenlafaxine delivery (17 files) end to end on the server; every value found listed against what a person reads in the files. | — |

R1–R3 are small and make the current agent dependable. R4–R5 are the larger science-facing part; they touch the
reading agents' prompts and code's checks, so they each get a CHANGELOG entry and the owner's review of the evaluation.

## 5. Decisions for the owner
1. Read documents (annex, paper, other) for data by default (§3.1), or only when ticked?
2. Delivery pass (R4) before every multi-file upload, or only when more than N files arrive?
3. Figures digitized on arrival (R5), or only proposed ("this page is a plot: digitize?")?
4. Order: R1 → R2 → R3 first (dependability), then R4/R5?
