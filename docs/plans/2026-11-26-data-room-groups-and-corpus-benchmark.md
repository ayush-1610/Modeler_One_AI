# The Data room, regrouped by purpose, and the corpus benchmark

**Status:** APPROVED by the owner on 2026-11-26 (decisions in §1). Phases 0 and 1 are built on the session branch
`claude/exciting-galileo-x1ziov`; §8 says what is done and what was measured. Nothing here changes a locked file.

**Where it comes from:** the owner's corpus audit of 30 of their PBPK/PBBM project folders (2023–2026, client
confidential, kept outside the repository) and the assessment of it against this codebase (2026-11-25/26, session
notes, not committed). Two findings drive this plan:

1. The Data room reads everything a client sends, which is right, but shows it by type of file (14 sections), so much
   of what the page shows does not feed the model. Across the audited projects, of 108 original client files about 40
   never reached a model; what did was almost always concentrations, dissolution, the BE statistics and demographics.
2. Whether the room works on any client delivery has been measured on synthetic deliveries only. The audited projects
   hold 292 client files across 17 projects: real CRO deliveries with known answers, the test set the room lacks.

---

## 1. The owner's decisions (2026-11-26)

| # | Decision |
|---|---|
| D1 | Population, sex, meal template and release model are **chosen on Inputs**. The Data room records the delivery's facts behind them (e.g. a stated meal's composition) and Inputs proposes the choice from them, with their source. PK-Sim's defaults apply when the client states nothing; templates (disease populations, meal sets) are added to Inputs later, names harvested from PK-Sim only. |
| D2 | The groups get formal names: **Question and Context of Use · Model Input Data · Supporting Evidence · Source Records · Data Requests** (sections in §3). |
| D3 | The within-subject CV is **computed by code** from subject-level crossover data, compared with the CRO's stated CV when there is one, and shown **To confirm**. |
| D4 | **One prompt version per agent**, so a change to one agent's instructions no longer discards every agent's cached answers. |
| D5 | New dependencies approved for phase 2: SAS datasets (`pyreadstat` or `pandas`), PowerPoint (`python-pptx`), Apple Numbers (`numbers-parser`). |
| D6 | The corpus is the benchmark. Now: scored on the server's in-house model only (the data-permission rule). Once the room of phases 2–5 is ready, every project's client data is run through it, and then any AI service may be used. |
| D7 | A modeler confirms the answer key of each delivery (a few hours each; the audit's registers do much of the work). |

## 2. What the corpus shows about client data

Formats of the 292 client files (17 projects): 281 open today (PDF, scans through OCR, Excel, Word, CSV, text tables,
images, ZIP). The 11 that do not: 4 CDISC SAS datasets (`adsl`, `ex`, `pc`, `pp`; P30), 3 PowerPoint files holding
dissolution data or BE ratios (P07, P27, P30), 2 Apple Numbers concentration tables (P05), 1 Apple Pages file (P29) and
one stray `.dll`.

Shapes the room meets, and where they stand:

| Shape | Projects | Today | After the plan |
|---|---|---|---|
| Long concentration tables (subject, period, treatment, time, value) | P02, P03, P18, P27 | read | read |
| Wide tables, times across, CRO Mean/SD rows; tokens `M`, `NR` (non-responder), `N.Av`, `#REF!` | P05, P15, P17, P29 | mostly; `NR`, `#REF!` not in the vocabulary | read |
| Mean-only profiles | P07, P15, P19, P20 | read (the statistic must be stated) | read |
| BE statistics (GMR, CI, CVw) in PDF, Word, Excel; scanned SAS output | P02, P03, P05, P20 | GMR and CI; no CVw | with CVw (D3) |
| CDISC SAS datasets | P30 | not opened | mapped by code, no agent |
| Dissolution, one medium | P01–P05, P18, P20 | read | read |
| Multi-stage pH-shift dissolution (delayed release) | P17 | one medium per profile | a stage column |
| Solubility, API properties, particle size, composition | P03, P05, P17, P18, P20 | read; unstated units asked | read |
| Urine excretion rate and Ae per interval | P08 | read, not landed | landed |
| Baseline-corrected endogenous drug, tissue data, release over weeks | P08, P13, P15, P28, P29 | read | read, flagged outside the model's scope |

## 3. The groups and sections (D2)

`packages/project-model/src/modeler_project/dataroom/dataroom_layers.yaml`, read by `modeler_project.dataroom.layers`.
Code places every extracted fact and table: an agent never decides where a value belongs.

| Group | Sections | Holds |
|---|---|---|
| Question and Context of Use | Question and Context of Use | the regulator, the question, the products and their roles |
| Model Input Data | Test and Reference Products · Drug Substance Properties · In Vitro Release Input · Clinical Study Design · Observed PK and BE Outcome · Simulation Scenarios | values that parameterise, calibrate or validate the model; sent to Inputs |
| Supporting Evidence | Formulation Differences (Q1/Q2) · Solid-State and Particle Characterization · Dissolution in Other Media and Batches · Study Conduct and Deviations · Label and Literature PK · Other Delivered Facts | values that justify a decision without entering the model |
| Source Records | All Source Files | every file, fully read and kept, with what it gave |
| Data Requests | Data Requests | what to ask the client |

Rules:
- Every fact field and table kind of `modeler_intake.room_specs` has its own placement (a test fails naming a new one).
- A field the open vocabulary does not know goes to **Other Delivered Facts**: kept and shown, never lost.
- **Question-driven:** an entry the question's applications require (the requirement drafts' REQUIRED or
  USUALLY_NEEDED items) moves to its Model Input Data section where the map allows it (`promote_to`): the meal's
  composition for a food-effect question, particle size where release is particle dissolution, a measured fu.
- **Selection-driven:** a dissolution profile that is not the selected release input is shown under Dissolution in
  Other Media and Batches.
- The map decides where the page shows a value, never whether it is read, checked or kept.

Today's 14 sections map as follows (phase 5 builds the page): Overview → the page's top (readiness, what the data
says, what needs a person); Files → All Source Files; Requirements → the coverage counter behind each Model Input Data
section; Drug substance, Solubility → Drug Substance Properties (solid-state facts to Supporting Evidence); ADME → Label
and Literature PK; Formulation → Test and Reference Products and Formulation Differences; Dissolution → In Vitro Release
Input and Dissolution in Other Media; Clinical studies → Clinical Study Design and Study Conduct; Observed PK → Observed
PK and BE Outcome; Decisions → each on the value it decides, and the D1 choices to Inputs; Data requests → Data
Requests; Simulation plan → Simulation Scenarios; PK-Sim inputs → the hand-off to Inputs.

## 4. One prompt version per agent (D4)

`services/agents/src/modeler_agents/dataroom/stages.py`: `PROMPT_VERSIONS` (A6 … A10) and `prompt_version(stage)`
replace the single `PROMPT_VERSION`. The answer cache's key holds the stage's agent version, and each answer's author
record names it. All five start at `dataroom-6`, the version they shared, so no answer cached before the split is
lost. A change to `_COMMON` (every agent's first instructions) is a new version of every agent.

## 5. The canonical observation record (phase 1b)

The principle: fix the shape, never the size. One row per measurement with fixed columns (study, arm, analyte, matrix,
subject, period, sequence, field, nominal time, value, unit, censored, LLOQ, statistic); 360 hours and 500 samples is
more rows, never another shape; a column a record does not know is kept, never dropped.

**Deviation from the approved plan (recorded as CLAUDE.md asks):** the plan said "build the canonical record". Two
already exist: the intake ledger's `ValueState` / `EntityRef` (`ledger_models.py`) and the value scorer's `Extracted`
(`value_score.py`, D0), whose labels already follow CDISC's PC domain closely. A third would have split the truth. What
was missing was the Data room's way into them: `dataroom/scoring.py` `from_dataroom(ws)` now gives the room's reading as
`Extracted`, so the room is scored by the same scorer, key format (value-key/2) and verdicts as the intake pipeline.
Phase 2's SAS reader maps CDISC PC/PP/EX/ADSL into the same record.

## 6. The corpus benchmark (phase 0)

A delivery's files (outside git) are read into a Data room project; its answer key (value-key/2, outside git) is
scored against the room's reading:

    uv run python -m modeler_project.value_score --root <read-root> --project <id> --key <key.xlsx> --source dataroom

The report gives, per key row, found, wrong value, wrong unit or missing, the values unexpected, and totals by field and
study. A change to the room is kept only if the score rises and nothing that was right turns wrong.

Answer keys: drafted by code from the delivery's own files and the audit's registers (status `draft`), then confirmed by
a modeler (D7). Level 1 (does a file open) needs no key: the run records each file's state.

On the server, per delivery (the agents on the in-house model, D6):
1. Create a project and drop the delivery on its Data room page; press Run (the admin console's in-house model for
   A6–A10). The Files section shows each file's state.
2. Score the run against the delivery's key with the command above (`--project` is the project's id; `--root` is
   `~/modeler-data/read-root`). The default report leaves values and file names out; `--with-values` keeps them, on the
   server only.
3. Keep the report beside the key, outside git. A change to the room is judged by the same two steps on every delivery.

Confidentiality: the deliveries and answer keys are client data. They stay outside the repository (as the owner's
cinacalcet sample did), on the server under `~/modeler-data` or the owner's drive. The repository holds the harness and
its tests on the synthetic deliveries only.

## 7. Phases and order

| Phase | What | Check |
|---|---|---|
| 0 | Answer keys and the benchmark harness; a baseline score | per file and per value, on the server's in-house model |
| 1 | Per-agent prompt versions (1a); the canonical observation record (1b); the group map (1c) | unit tests; no score drops |
| 2 | Formats: SAS with CDISC domains mapped by code; PowerPoint; Numbers; "export as …" requests for the rest | the 11 unopened corpus files |
| 3 | Code-computed findings: CVw (D3), the CSR GMR/CI comparison (±0.5 pp), the BE zone, the salt/base dose card, detectors (simulator exports, lot conflicts, wrong summary rows, a file about another drug, personal data) | each catches its corpus case |
| 4 | Agents: the extractor learns the CVw column, a dissolution stage column and the NR / #REF! tokens; the checker checks Model Input Data first; the writer gets the new sections | score rises |
| 5 | The page in its groups; the D1 choices on Inputs with the room's facts as proposals; empty and reading states | "Send to Inputs" sends identical values on the synthetic deliveries and the corpus |
| 6 | Inputs templates: disease populations and meal sets from PK-Sim's harvested catalogue; custom meals from client values | engine dry run on the server |
| 7 | Every corpus delivery through the finished room (D6); the bar for unattended use | a published score per delivery |

## 8. Status

| Item | State |
|---|---|
| 1a per-agent prompt versions | **Built**: `stages.py`; tests in `services/agents/tests/test_dataroom_cache.py` (a new extractor version asks only the extractor again) |
| 1b the long-form record | **Built as an adapter** (§5): `dataroom/scoring.py`; `assemble.read_extractions` and `dataroom.room_inputs` shared with the room; `Sample.subject_text`; tests in `test_dataroom_scoring.py` |
| 1c the group map | **Built**: `dataroom_layers.yaml` 0.1, `layers.py`; tests in `test_dataroom_layers.py`. Not yet read by the page (phase 5) |
| 2a formats | **Built**: `modeler_intake.source.sas`, `.pptx`, `.numbers`; send-as reasons for known unread formats (`parse.SEND_AS`). Corpus: of the 7 files no parser read, 6 open (4 SAS datasets and a deck read, a deck partly read); the legacy `.ppt` asks for .pptx or PDF |
| 2b analytes and CDISC by code | **Built** (owner's choice A, 2026-11-26). **Analyte as a room dimension:** `Sample.analyte` (the line's analyte cell, else the table's constant); a study that measured several analytes is viewed once per analyte; decision `analyte:<study>` (suggested: the drug the delivery names, else the first analyte not marked a metabolite or a labelled compound); `DataRoomView.studies` holds the modeled analyte, `other_analytes` the rest; layers 0.2 put those under Supporting Evidence, *Metabolites and Other Analytes* (`not_modeled`); lines naming no analyte in such a study are said (ANALYTE_NOT_NAMED); `colliding_samples` keys on the analyte; the scorer emits it; A8 `dataroom-7` (an analyte column in a PK table). **CDISC described by code** (`dataroom/cdisc.py`, `cdisc-1`): SDTM PC and DM / ADSL, one table per study; agents A8 and A9 skip what code described. **P30, code only, no AI service (session files):** PC and ADSL described (4 pooled studies each); 4 studies × 3–4 analytes (the drug, two metabolites, a 13C-labelled tracer) viewed apart, the drug suggested in each; the occasion is PCGRPID ("Period n"), never VISIT (a profile's 24 h sample is on "Day 1", its 48 h sample on "Day 2"); BLQ ("<", "<0.500") and NOT DONE "MS" read; 2 "N.R." results said, not read. **Deviation from the row above:** PP and EX are left to the agents. P30's PP holds model-based and NCA values side by side (PPSCAT) with 716 repeated (subject, analyte, group, parameter) keys, and its analyte names differ from PC's; tying a period to its treatment needs EX or ADSL TRTxxP, a join a table description does not express. Until then a study whose data names no treatment says so (NO_TREATMENT): its NCA and sets are shown, no mean profile per arm |
| 2c treatment and PK parameters | **Built.** A new table kind, `dosing` (what each subject was given on each occasion); SDTM EX described by code as one (product, dose with its unit, route, form, frequency; the occasion EXGRPID, EPOCH or EXTPT naming a period). Concentration data that name no treatment take each profile's from it (`clinical.assignments`, TREATMENT_FROM_DOSING); decision `dose-arms:<study>` when a product was given at several doses (suggested one arm per dose when a subject had two doses on two occasions, or at most four doses each given to two subjects or more; else one arm, each subject's own dose). Long PK tables (`parameter`, `value`, `unit` roles; `clinical.pk_role` knows CDISC codes and written names); SDTM PP described by code from its non-compartmental lines only, when each parameter is given once per subject, analyte and occasion; PK values whose analyte the concentration data do not name are said (PK_ANALYTE_NOT_IN_DATA); the scorer reads long PK rows. A8's prompt (still `dataroom-7`, unreleased) gains the kind and roles. **P30, code only:** EX, PC, PP and ADSL described; every study now has arms, mean profiles and exposures (the 3-period study's 0.5 mg and 1 mg periods two arms, suggested from a subject given both; the IV study's individual doses one arm); the client's NCA beside ours in the two single-dose studies (Cmax and Tmax equal on every profile shown; AUC within 1.3 % in one study, flagged to investigate, likely actual times; reproduced 100 of 100 in the other); the two multiple-dose studies' PP repeats each parameter per day within a period and is left to the agents. **Deviation:** ADSL TRTxxP is not used (TRT02P/TRT03P empty for a 3-period study whose periods EX tells apart by dose). ADaM ADPC / ADPP wait for a delivery that has them. **Known gap:** actual sampling times (PCDTC against the dose's EXSTDTC) are not derived |
| 3a BE statistics by code | **Built.** `pbpk_domain.bioequivalence`: `crossover_be` (the 2×2 analysis, equal to the ANOVA with sequence, subject within sequence, period and treatment, checked against a least-squares fit; the paired form when the sequences are not known), `parallel_be`, `be_zone` (R55). `dataroom/bestats.py`: each study's GMR, 90 % CI, CVw (D3) and conclusion (R50) for Cmax, AUC0–t and AUC0–inf, test against reference as the question card names them, on the analysis set the modeler chose, from our NCA and from the client's; the CSR's BE table (a new role `cv` for its stated CV) reproduced within 0.5 percentage points or said (R01, BE_CSR_DIFFERS); a replicate design or unknown roles said (BE_NOT_COMPUTED). `RoomStudy.be`; rules 0.4 `be` (UNVERIFIED; the values are the owner's plan's and the audit's R01/R50). Not shown on the page yet (phase 5). **P03 (a real BE delivery, code only):** the CSR's GMRs and 90 % CIs reproduced within 0.05 pp (Cmax, 34 subjects) and 0.13 pp (AUC0–t, AUC0–inf, 31 subjects); the AUCs on the AUC set, as the CSR did (on the modeling set they were up to 1.1 pp off). P30 has no test/reference product (a PBPK, not a BE, delivery): nothing to compute |
| 0 the benchmark | **Built**: `value_score --source dataroom`. First real measure (code only, session files): P03's concentration table described as a modeler would, against a draft key generated from the file: 1,678 of 1,678 measured values right, none unexpected; 146 BLQ-coded zeros censored by the room, written "0.000" in the draft key (the key's convention is the modeler's); 3 SAS-output BE ratios missing (file not described). **Level 1, every format (code only, OCR on):** the 96 client files packaged with the audit (102 once 2 ZIPs are unpacked; 17 projects; 2,087 pages, 199 by OCR): 94 read, 1 partly read (a Word file's comments are not read), 7 not opened: 4 SAS datasets, 2 PowerPoint `.pptx`, 1 legacy `.ppt` (phase 2's formats); no crash. The agents' baseline on the server is next |
