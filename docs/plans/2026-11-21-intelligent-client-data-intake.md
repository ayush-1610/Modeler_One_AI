# Data room: from any client delivery to verified PK-Sim inputs (plan v2, 2026-11-22)

**Status:** approved in direction by the owner on 2026-11-21 and 2026-11-22. Build starts after this version.
**Replaces:** v1 of this file (2026-11-21). **Supersedes** the client-data parts of `2026-11-14-inputs-task-first.md`:
the sheet-form reader and the delivery pipeline as the way client data enter the model.
**Worked example:** the cinacalcet PBBM delivery. Its numbers are client-confidential, so they are kept outside the
repository. The owner received them as a visual walkthrough of the screens.

---

## 0. In one paragraph

A client sends a delivery: a zip of PDFs, Word files, spreadsheets, text exports and scans. The **Data room**:
1. reads every file, including scans, with our own OCR engine;
2. understands what the project must answer;
3. finds only the data the model needs, and shows each value with the file, page and line it came from;
4. checks every number against the source and recomputes what can be recomputed;
5. lists what is missing or contradictory as numbered data requests;
6. asks the modeler only for real modeling choices.

It produces two things from the same verified data:
- a clean, visual **evidence report**, in the spirit of the owner's kick-off report;
- the exact **PK-Sim inputs**, each traceable to its source.

Nothing is invented. Any of the three AI models (Qwen Coder, Claude, gpt-oss-120b on GroqCloud) can do the reading,
chosen per agent with one click.

## 1. The owner's decisions (log)

| Date | Question | Decision |
|---|---|---|
| 2026-11-21 | Generic intelligent system, not per-format ETL | Yes |
| 2026-11-21 | Question first → targeted extraction → explicit modeler decisions | Yes |
| 2026-11-21 | Cinacalcet formulation: fitted release or particle dissolution | Fitted release from the dissolution data |
| 2026-11-21 | Model switch global or per agent | Per agent |
| 2026-11-21 | Third model | `openai/gpt-oss-120b` on GroqCloud |
| 2026-11-22 | Client data to Groq | Allowed |
| 2026-11-22 | The PK-Sim answer key | The platform defines what PK-Sim needs, in which format (§7) |
| 2026-11-22 | More deliveries | Not now; build with what we have |
| 2026-11-22 | Scanned pages | Our own OCR engine (self-hosted, no data leaves the server for OCR) |
| 2026-11-22 | Population for Indian subjects | Use the closest database for now; **backlog: build more population physiology templates** (§12) |
| 2026-11-22 | Which dissolution medium the release is fitted to | Show every product, batch, medium and pH available; the choice is made later, per project |
| 2026-11-22 | Meal composition not given | Use a default template, or the literature/web definition, and say so |
| 2026-11-22 | Analysis-set rules | The platform decides; the rules in §8 apply and can be overridden |
| 2026-11-22 | Blinding during data checking | Not required. Recommendation below; the owner confirms |

**Blinding: recommendation.** Do not hide values while the data are being read and checked. That matches how the
owner works: the kick-off report shows the test arm that is later used for verification. Scientific integrity
(ICH M15, pre-specification) comes from two things:
1. **declaring each dataset's role** (calibration, verification, prediction) in the simulation plan, and having it
   signed with the Modeling Analysis Plan before any calibration starts;
2. the audit trail, which records who saw and decided what, and when.

The Data room therefore shows all values. The existing blinding switch remains for the model-building steps, for any
project or regulator that requires it, but it is off by default for new projects. Changing the MS-01 blinding rule
itself is an SME decision and is not part of this plan.

## 2. What we have today

| Area | What it does today | Verdict |
|---|---|---|
| Start (proposal reader, agent A1) | Reads the proposal, drafts drug, question, application template | **Keep**; its output seeds the question (§5, stage 2) |
| Data plan (`requirements/*.yaml`, `requirements:derive`) | The required inputs per application template (core small molecule, VBE, food effect, DDI, FIH, special populations) | **Keep** as the starting checklist (SME-governed, unchanged) |
| Client files: upload and store | Files stored by hash in the project | **Keep** |
| Sheet-form reader (`modeler_intake.sheet_form`) | Guesses a spreadsheet's layout with patterns (time, subject and value columns) | **Replace**: it misread real tables (stacked subjects, codes defined in other files) |
| Delivery pipeline (ledger, mappings, spot check, signed confirmation) | Cell-level ledger of every value, table mapper, prose extractor, per-subject cards, 117-value spot check, Part 11 signature | **Replace as the entry path**. Keep its good parts: anchored values, signature, audit. Its heavy per-cell review and two-path cards go |
| Inputs page (7 areas, two paths, To do) | Shows both readings side by side, many states | **Replace** with the Data room. The old page stays reachable for existing projects until the switch-over (§11) |
| Blinding at intake | Hides values of studies marked for validation | **Off at intake** (§1) |
| Evidence store (`EvidenceItem`), observed datasets (`ObservedDataset`, `StudyRecord`), dissolution register | Where accepted values, profiles and study facts live | **Keep: the Data room publishes into them**, so everything after Inputs keeps working |
| CPF, snapshot builder, PK-Sim engine, campaign S0–S7, MAP, acceptance, VBE, reports | Model building, running, judging | **Keep, unchanged** |
| NCA (`pbpk_domain.nca`), f2 and Weibull fit (`pbpk_domain.dissolution`) | Deterministic science functions | **Keep, reused** for the derived numbers |
| Agents A1–A5, provider layer (LiteLLM in-house, Claude on Bedrock), per-agent console setting | The AI edge | **Keep and extend**: GroqCloud provider, one-click switch, new Data room agents |
| Audit trail, signatures, auth, locked files | Part 11 | **Keep, unchanged** |
| Design: blue gradient square logo, blue palette | The visual identity | **Change**: new logo, calmer spacing and the brand palette of the kick-off deck (§10) |

## 3. What is not in line with the new system, and why

1. **Readers that guess layouts with patterns.** Real deliveries defeat them: stacked subject blocks, a treatment code
   explained in another file, units in headers, "." for missing, scanned tables. The new system has the AI *describe*
   a table (which column is the subject, the period, the treatment, the times) and code reads the numbers.
2. **Two reading paths for the same files.** Today two different answers have to be reconciled on the page. There will
   be one path.
3. **Cell-by-cell review and a random spot check of 117 values.** This is replaced by:
   - code verification of every value;
   - cross-checks, e.g. recomputing the client's own Cmax from the individual data;
   - one confirmation per section.
4. **No understanding of the question.** Today every file is read the same way. The new flow starts from what the
   project must answer.
5. **No place for derived evidence.** Mean profiles, analysis sets, f2, solubility per dose, composition differences and
   the simulation plan had no home. They become first-class, with their rules shown.
6. **Silent defaults.** Today "plasma", "oral", "healthy" and "model building" could be filled in when the files never
   said so. The new rule: every value is read, computed, entered or *missing*. Never defaulted silently.
7. **Facts in scans and prose were unreachable.** Demographics and the protocol were scanned. Meal times and exclusions
   were in sentences. The OCR engine and the fact extraction (with verbatim quotes) make them reachable.

## 4. What changes, and how the switch happens

- **New code, beside the old.**
  - A Data room engine in the existing layers (§9).
  - A new API under `/projects/{id}/dataroom`.
  - A new Inputs page.
- **New projects** open the Data room as their Inputs step.
- **Existing projects** keep the old page, with a link to "Open in the Data room", which reads their stored files again.
- The Data room **publishes** into the same stores the old path filled: evidence items, observed datasets, study
  records, dissolution profiles. So Review & sign, Run and reports work unchanged.
- When the Data room reaches its targets on the real deliveries (§13), the owner decides to retire the old reading paths
  and their screens. Their code is then removed in one change.

## 5. The flow, as you will use it

Example: a new PBBM project for a reformulated tablet.

**1. Start.** You create the project and attach the proposal (as today). The proposal reader drafts the question.

**2. Drop the client's delivery.** Drag the zip, or many files, onto the Data room. A progress panel shows each stage
with live counts:
> Reading 48 files · 12 scanned, reading them · Understanding the question · Sorting files (31 relevant, 17 set
> aside) · Extracting · Checking every number · Putting it together

You can leave and come back. Each stage is cached, so adding one file later redoes only what it changes.

**3. The question card (you confirm).** The question card shows:
- what must be answered: "Does the reformulation change in vivo performance relative to the reference product?";
- for whom: Health Canada;
- the products compared: reference, original test, reformulated test;
- the context of use;
- the checklist of required inputs, from the data-plan templates and tailored to the question.

You can add or remove items, then confirm.

**4. Overview.** One screen:
- the question;
- four headline numbers: files read, inputs found, data requests, decisions waiting;
- the sections with a status dot each;
- the conflicts that need attention first.

**5. The sections.** Each section has:
- a one-line finding at the top;
- one to three cards below: tables (Property · Value · Source · Status), headline numbers and charts;
- data requests at the bottom;
- a source chip on every value (e.g. "CSR p. 12"). Clicking it opens the page with the line highlighted.

The sections:

| Section | What you see |
|---|---|
| Files | Every file with its type, pages and purpose (Used · Context · Not needed, with the reason); scans marked "read by OCR"; duplicates grouped |
| Drug substance | MW, salt and dose basis, pKa, logP/logD, solubility vs pH, particle size, solid form, melting point; status per row |
| ADME and disposition | Absorption, distribution, metabolism, elimination: the label and literature facts with sources; food effect; what must come from elsewhere |
| Formulation | Composition per product side by side (changed rows highlighted); excipient functions; process changes; the new excipient and its share of the core |
| Solubility | Solubility per pH or medium (bar chart); the volume needed to dissolve the dose; what that means for release |
| Dissolution | Every product × batch × medium × pH: mean profile with spread (n units), method (apparatus, speed, volume, temperature); f2 where it applies, with the rule ("> 85 % in 15 min: f2 not needed"); Weibull fit per profile, shown but not chosen |
| Clinical studies | Per study: design (crossover, periods, washout, single or multiple dose), products and batches per treatment, fasting and meals, co-medication, sampling, bioanalysis (LLOQ), demographics; the subject flow (dosed per period → completed → client's statistical set → proposed modeling set → AUC set) |
| Observed PK | Mean profile per arm (arithmetic and geometric, ± spread, N per time) with meals marked; exposure metrics (Cmax, AUC, Tmax; geometric means), our recomputation beside the client's; the client's BE result; headline observations (e.g. a second rise after the meal) |
| Decisions | Every modeling choice waiting for you, each with evidence, options and a suggestion |
| Data requests | All requests, coded A (formulation and manufacturing), B (in vitro), C (drug substance and disposition), D (clinical); editable wording; export to Word or PDF to send to the client |
| Simulation plan | Rows of formulation + condition, the observed data each is compared with, and its role (development, calibration, verification, prediction) |
| PK-Sim inputs | The model inputs per building block (§7), each with value, unit, PK-Sim name, source and status; "Send to the model" publishes them |

**6. Decisions.** A decision card looks like this:
> **Analysis set for the observed profiles.** Suggested: *33 subjects*, which is the completers minus one subject
> with every sample below the LLOQ.
>
> Other options: the client's statistical set (35), all dosed subjects (48).
>
> Evidence: the synopsis (p. 4, exclusion reasons), the concentration table (the subject's rows are all zero).
> [Choose] [Enter a reason]

**7. Missing or contradictory data.** Each one shows as a data request, e.g. "B-01 Reference product dissolution, same
method, n = 12". You can also:
- enter a value yourself, which is recorded as entered by you, with your reason;
- mark an item "not needed for this question".

**8. Report.** "Export report" produces the evidence report as a PDF: the same pages as the screen, with your logo.
This is the kick-off report, generated.

**9. Send to the model.** When the required inputs are confirmed, "Send to the model" publishes them, signed. Review &
sign then starts from them.

## 6. Status words (as in the kick-off report)

| Status | Meaning | Colour |
|---|---|---|
| Verified | Two independent sources agree, or our recomputation reproduces the client's number | green |
| Sponsor data | From the client's own reports or data, one source | amber |
| Literature | From a publication, label or database | blue-grey |
| Calculated | Computed by the platform from verified inputs (the rule is shown) | violet |
| Entered | Entered by a person, with a reason | grey |
| Conflict | Sources disagree beyond tolerance (both shown) | red |
| Missing | Needed and not found; a data request exists | red outline |

## 7. The PK-Sim inputs: what the platform produces, and in which format

This is the answer key format. For each project, the platform produces this sheet and builds the PK-Sim project from
it through the existing CPF and snapshot builder. Every PK-Sim name below comes from the harvested catalog
(`services/engine-worker/golden/catalog.json`), the reference snapshot or the parameter registry
(`pbpk_domain/parameters/registry.yaml`).

### 7.1 Compound (CPF parameters)

Each row has: CPF id · PK-Sim name · value · unit · source · status.

- `phys.mw` (Molecular weight), with the salt and free-base basis stated.
- `phys.pka.base.*` / `phys.pka.acid.*` (pKa and type).
- `phys.logp` (Lipophilicity).
- `phys.solubility.ref` + `phys.solubility.ref_ph` (reference solubility and its pH), and the solubility-vs-pH table
  where PK-Sim takes it.
- `bind.fu` (Fraction unbound) and `dist.bp_ratio`.
- `perm.intestinal`.
- Elimination processes, with their PK-Sim process names (e.g. `MetabolizationSpecific_FirstOrder` for an enzyme,
  `GlomerularFiltration`).

A value not in the client data is looked up by the existing literature and compound-source agents and marked
Literature, or it stays Missing with a data request.

### 7.2 Formulations (one per product and batch)

- `Formulation_Tablet_Weibull` with `Dissolution time (50% dissolved)` [min], `Dissolution shape`, `Lag time` [min],
  fitted to the chosen dissolution profile.
- Every available profile has its fit shown, and the choice is a decision.
- `Formulation_Dissolved` for a solution.

The product's composition and batch are attached as context, not as PK-Sim parameters.

### 7.3 Individual and population (per study)

- Population database (from the harvested list, e.g. `Asian_Tanaka_1996`, `European_ICRP_2002`), sex, age, weight and
  height from the study's demographics (mean, and ranges for a virtual population).
- The individual carries the study's mean weight and height (as the Demographics model already supports).

### 7.4 Protocol (per treatment)

- Application type (oral; IV with its infusion time), dose (mg, as free base), dosing interval and number of doses.
- The water taken with the dose (ml per kg).

### 7.5 Events

Meals at their stated times after the dose:
- the PK-Sim template `Meal: Standard (Human)` unless the composition says otherwise;
- `Meal: High-fat breakfast (Human)` for an FDA high-fat breakfast.

The template choice is recorded as a decision when the composition is not given.

### 7.6 Observed data (per arm)

One aggregated series per treatment arm in the modeling analysis set:
- times in h and concentrations in the stated unit;
- arithmetic mean with SD;
- the geometric mean as a second series;
- N at each time.

Individual profiles are kept for virtual-population work. Metadata: `Study Id`, `Grouping`, `Data type`, `N`,
`Molecule`, `Organ`/`Compartment`, `Route`, `Dose`, `Formulation`, `Food state`.

### 7.7 Evaluation targets (not PK-Sim inputs)

Cmax, AUC0–t, AUC0–inf and Tmax per arm (geometric and arithmetic), the client's BE ratios with 90 % CI, f2 values,
and partial AUCs where the question needs them. They feed the acceptance and VBE checks.

### 7.8 Simulation plan

Each row: formulation + condition · observed data · role. It is signed with the MAP.

## 8. Rules the platform applies (shown on screen, overridable with a reason)

**Analysis sets (clinical).**
- *Dosed*: received at least one dose.
- *Completed*: received every treatment of the design and completed sampling (from the disposition table and text).
- *Evaluable profile*: at least three quantifiable concentrations after dosing. A profile with every sample below the
  LLOQ is flagged as a possible non-absorber or dosing error, and becomes a data request.
- **Modeling set (default):** completed ∩ evaluable in every period.
- *AUC set*: the modeling set with complete sampling to the last scheduled time in every arm.
- The client's own sets (e.g. the statistical analysis list) are shown beside these; any difference is explained or
  becomes a data request.

**Mean profiles.**
- Computed per arm at nominal times, as arithmetic mean ± SD and geometric mean.
- Values below the LLOQ before dosing count as 0. After dosing, they count as 0 in the arithmetic mean and are
  excluded from the geometric mean.
- N is shown at each time.

**Recomputation.**
- NCA per subject (linear-up/log-down) is compared with the client's PK file. A difference beyond 1 % is a conflict
  with both values shown.
- Cmax and AUC geometric means are recomputed for the sets above.

**Dissolution.**
- Mean and spread per time from the unit values. The client's average row is checked against it (to rounding).
- f2 only when both profiles are below 85 % at 15 minutes, using the standard f2 rules.
- A Weibull fit on every profile. A plateau below 100 % is flagged, because it may need a table formulation.

**Solubility.** The volume needed to dissolve the dose, and the dose fraction that can dissolve in 250 mL and in the
medium volume, per pH.

**Units.** Converted by the existing unit library. The original as-written value is always kept.

**Meals.** The template is chosen per §7.5. Composition is never assumed silently.

**Population.** The closest harvested database for the study's ethnicity; this is a decision card. Building more
population templates is in the backlog (§12).

## 9. How the intelligence works (technical)

**Principle:** the AI reads and describes; code extracts, checks and computes; the modeler decides.

| Stage | Where (layer) | What |
|---|---|---|
| Inventory | `modeler_intake` (L2, no AI) | Hash, type, page count, duplicates by content; archives unpacked; the text layer per page (pypdfium2); OCR per scanned page with **RapidOCR** (self-hosted ONNX, CPU, pip-installed: no admin rights needed on the server), keeping each word with its position; Word and Excel read natively; delimited text sniffed |
| Tables | `modeler_intake` | Tables found in spreadsheets, delimited text, and PDF/OCR text, by token positions; each cell gets a stable id (doc · page · table · row · column) |
| Question and checklist | `modeler_agents` (L4) | Agent reads the proposal, request email and data-plan templates; proposes context of use, products compared and checklist |
| Triage | `modeler_agents` | Agent classifies each file and page and links it to checklist items, or sets it aside with a reason |
| Extraction | `modeler_agents` | Per checklist item the agent returns either a **table description** or a **fact with a verbatim quote**. A table description is not numbers: e.g. "rows are subject × treatment; column A = subject, B = sequence, C = treatment, D = period; columns E–W are times in h from the header; '.' = missing; treatment codes defined in file X line Y". Agent tools: list documents, search pages, read page, read table preview, read cells |
| Verification | `modeler_project` (L3, code) | Code applies each table description and reads every number from the cells. Each quote must be found verbatim in the page text, and the value must occur in it. Units are parsed, and plausibility checked (time order, ranges, sums). A second agent pass (the checker, ideally another model) reviews the mappings: codes, arms, batches. Anything failing is sent back once with the reason, then shown as a problem |
| Assembly | `modeler_project` (code) | Joins facts across files (one study record, arms, subjects, batches ↔ products ↔ dissolution); applies §8; computes derived numbers with the existing NCA, f2 and Weibull functions |
| Status, conflicts, data requests | code + Writer agent | Status per value (§6); conflicts by tolerance; data requests drafted (the Writer words them, never writes numbers) |
| Publishing | `modeler_project` | Confirmed sections become evidence items, study records, observed datasets and dissolution profiles in the existing stores, with source references |
| API | `modeler_api` (L6) | `/projects/{id}/dataroom/...`: upload, run, status, sections, sources (page image with highlight), decisions, requests, report export, publish. Typed responses (OpenAPI snapshot updated) |
| Page | `apps/web` (L7) | The Data room (§10) |

**Agents and models (one click per agent in the admin console):**

| Agent | Needs | Suggested default |
|---|---|---|
| Question | reasoning | Claude or gpt-oss-120b |
| Triage | speed, many short calls | gpt-oss-120b (Groq is fast) or Qwen Coder |
| Extractor | the strongest reading | Claude or gpt-oss-120b; scored on the real cases |
| Checker | a second opinion | a different model from the Extractor |
| Writer | clear English | any |

OCR is not an AI model. It is our own engine, so scans never leave the server.

**GroqCloud.**
- A new provider in the admin console: an API key, the model `openai/gpt-oss-120b`, `reasoning_effort` (low, medium,
  high).
- It uses Groq's OpenAI-compatible endpoint `https://api.groq.com/openai/v1` with the platform's existing
  OpenAI-compatible client.
- The key is stored encrypted, like the other keys.
- **One click per agent:** each agent row shows three buttons (Qwen Coder · Claude · gpt-oss-120b). The active one is
  highlighted, and the change is recorded with who and when.

**Proof built in.**
- Each run records the model and prompt version per agent.
- An evaluation command scores a run against an answer key: found, missed, wrong, invented values (must be 0), exact
  match of PK-Sim inputs, valid citations, time and cost.
- The cinacalcet answer key lives outside the repository (confidential). The repository's tests use an anonymized
  fixture with the same structure (stacked crossover table, codes in a side file, scanned demographics, multi-medium
  dissolution) and recorded model answers, so CI never calls a paid model.

## 10. Design

**Principles.** Only what matters, every number with its source, calm space.
- One finding per section, large.
- At most three cards per screen before scrolling.
- Tables with four columns at most by default; details open on click.
- No engine words.

**Layout.**
- A left rail of sections, each with a status dot.
- A content column up to 1120 px wide.
- An 8 px spacing grid, with 32 px between cards and 24 px inside them.
- Type scale 13 / 15 / 20 / 28 px.

**Palette (from the kick-off deck).**

| Role | Colour |
|---|---|
| Brand, headings | Deep indigo `#3B1F7A` |
| Text | Ink `#141A33` |
| Reference series | Indigo `#4B2A99` |
| Test, original | Teal `#1A9AA6` |
| Reformulated | Magenta `#C2307A` |
| Statuses | Green `#1E7B45` · amber `#9A5B00` · red `#B3261E` |

**Charts.** Plotly, already in the app, with a single shared style: thin lines, dots at the data, events (meals) as a
dashed rule with a label, and units on the axes.

**Source viewer.** A side drawer with the page image and the line or cell highlighted, the file name and page, and
"Open file".

**Logo.** The blue square goes. The new mark is a curve rising from a dose point and settling, drawn as a single line
through small nodes (echoing the kick-off deck's network motif), on a transparent background: no box. Three variants
were shown to the owner; the chosen one is used in the app and on the exported report.

## 11. Build steps, and what you will see after each

| Step | Builds | You will see |
|---|---|---|
| 1 | GroqCloud provider; one-click per-agent switch; new logo and palette tokens | Admin → Agents with three buttons per agent; the new logo |
| 2 | Inventory and OCR engine; tables from every file type | The Files section: every file with its type, pages, "read by OCR", duplicates |
| 3 | Question and checklist agent; triage | The question card and checklist; files sorted into Used, Context and Not needed, with reasons |
| 4 | Extraction and verification (clinical, dissolution, composition, drug substance, ADME) | The sections filled, with source chips and statuses |
| 5 | Assembly and rules (§8); decisions; data requests; simulation plan | Subject flow, mean profiles, exposure metrics, dissolution charts, f2 and fits, decision cards, data requests |
| 6 | PK-Sim inputs; publishing into the existing stores; report export | The PK-Sim inputs section; "Send to the model"; the PDF report |
| 7 | Evaluation on the cinacalcet delivery with each model; fixes until the targets are met | A score table per model |
| 8 | Records, tests, merge to `main`, deploy instructions | The same on the server after deploy |

Everything is delivered together at the end, as asked. Questions that block a step are asked when they arise.

## 12. Backlog (recorded, not in this build)

- **Population physiology templates** beyond PK-Sim's databases (e.g. Indian adults): anthropometry and organ scaling
  from literature, validated against published PK; needs the owner's and an SME's review.
- Slides export of the report (PPTX), in addition to PDF.
- A client portal for sending data requests and receiving answers.
- Biorelevant media and precipitation modeling, when a question needs it.
- Retiring the old reading paths (after §13 is met).

## 13. Targets (when the Data room counts as working)

On every real delivery available:
- every required input found or listed as missing;
- zero invented values;
- the PK-Sim inputs exactly as the modeler would enter them;
- the client's own reported numbers reproduced where recomputable (e.g. Cmax and AUC geometric means per arm);
- every source chip opens the right page and line;
- a full delivery processed in under 20 minutes on the server.

## 14. What the owner does

1. **GroqCloud key**, entered once:
   - Admin console → Keys → Add → GroqCloud → paste the key → Save → make active.
   - Then Admin → Agents → click "gpt-oss-120b" on the agents to use it.
   - The server must be able to reach `api.groq.com` (outbound HTTPS).
2. **Deploy** after the build: on the Mac, from a checkout of `main`, run `bash deploy/dev/deploy_to_server.sh`. The OCR
   engine installs with the Python packages; nothing to install by hand.
3. **Try it** on the cinacalcet delivery: create a project, attach the proposal, drop the zip.
4. **Tell us** what is wrong or missing. Each correction becomes a test case.
