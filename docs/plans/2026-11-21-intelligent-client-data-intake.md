# Intelligent client-data intake: from any delivery to verified PK-Sim inputs (plan, 2026-11-21)

**Status:** proposed, waiting for the owner's approval. Nothing in this plan is built yet.

**Supersedes:** the client-data parts of `2026-11-14-inputs-task-first.md` (the sheet-form reader and the delivery
pipeline as the way client data enters the model). That plan's page work stays in the code until this plan's
replacement is proven on real deliveries (§10).

**Why this plan exists.** Seven review rounds made the Inputs page consistent, but the owner's real deliveries still
came out wrong (2026-11-19: a crossover concentration table read as one series; facts not in any file shown as if
read; studies split; a dose in a Word file not used; the owner's own data hidden by blinding). The cause was the
approach, not the screens: rule-based readers built and tested on synthetic files, two reading paths, and no real
delivery with a known right answer. This plan starts from what a PBPK/PBBM modeler actually needs and from real
deliveries.

---

## 1. The owner's decisions this plan rests on (2026-11-21)

| # | Question | Owner's answer |
|---|---|---|
| 1 | The system reads *any* delivery, understands the project's question, extracts only what the model needs with sources, flags conflicts and gaps, and prepares PK-Sim inputs. No per-format ETL. | Yes (corrections will be flagged later) |
| 2 | Shape: question first, then targeted extraction, then explicit modeler decisions | Yes, to be judged on real use |
| 3 | Cinacalcet: formulation from fitted release of the dissolution data, or mechanistic particle dissolution? | **Fit release from the dissolution data** |
| 4 | Model switch: one global switch, or per agent? | **Per agent** |
| 5 | Third model | `openai/gpt-oss-120b` on **GroqCloud** (Qwen Coder in-house and Claude stay) |

## 2. What real deliveries look like (and why no fixed ETL works)

Every delivery is different because the **question of interest** differs: virtual bioequivalence, a post-approval
reformulation (PBBM), food effect, DDI, a special population, first-in-human. The question decides which data matter.

The cinacalcet delivery (48 files, Parts A to D plus a proposal) is one example of thousands:

- **Most of it does not feed the model.** Ascorbic acid monographs, TSE/BSE and nitrosamine declarations, a patent,
  13 specification and test-procedure files.
- **Key facts are scanned or split across files.**
  - Scanned with no text layer: the individual demographics (12 pages), the protocol (54 pages), the meal details,
    the manufacturing summary and the dissolution test procedure.
  - The treatment codes ("B = test, A = reference") are defined only in a side `.txt` file.
  - Who counts for analysis (dosed per period, completed, statistical set, AUC set) is in prose, with a reason per
    subject.
- **The same data come twice.** The concentration table and the PK parameters each come in two formats; the same
  particle-size file sits in two parts.
- **Conflicts are normal.**
  - The BE batch number is written three different ways across the files.
  - The reference product carries different brand names and lots in the clinical study and in the dissolution
    comparison.
  - The coating breakdown does not sum to the coat weight.
- **Modeling-relevant details hide in operational text.**
  - Meals at 4, 9, 13 and 24 h after dosing explain a second peak about an hour after the first meal in most profiles.
  - An antiemetic was given before dosing.
- **Gaps that block the question.** There is no reference-product dissolution profile, and no data with and without
  ascorbic acid.

The earlier deliveries (Exampleamide, Clientamide, Desvenlafaxine) showed further shapes:
- stacked subject blocks;
- dose and n in a Word summary;
- dissolution per vessel in Excel;
- crossovers with Test and Reference arms.

**Conclusion:** the system must *understand* each delivery against its question, not parse known layouts.

## 3. What the system must produce: two outputs from one evidence base

The owner's kick-off report (Cinacalcet Project Kickoff Report v2, slides 7–14) is the reference for the first output.

### 3.1 The evidence report (for the people)

One page per area, each with:

1. **A one-line finding.** For example "a weak base with low, pH-dependent solubility; the dissolution model rests
   on these inputs".
2. **Tables with Property | Value | Source | Status.**
   - Status is one of: Verified (consistent sources) · Single source · Sponsor data · Literature · Calculated ·
     Conflict · TBD.
3. **Headline numbers computed from the data.** For example: the fold change in solubility between two pH values;
   how much of the dose can dissolve in a given volume; the share of profiles that rise after a meal; the share of
   AUC that accrues after it.
4. **Charts with their context.**
   - Solubility versus pH.
   - Dissolution per medium, product against product, with f2.
   - Mean concentration per arm, with the meal marked.
   - The subject flow, from dosed to the analysis set.
5. **Comparison matrices.**
   - Original versus reformulated composition, per component.
   - Process changes.
6. **Numbered data requests** for every gap or conflict.
   - Coded by area: A formulation/manufacturing, B in vitro, C drug substance/disposition, D clinical.
   - For example D-01 "Explanation of subject 12 and the final locked analysis dataset".
7. **The simulation plan** (slide 14). Each simulation (formulation + condition) is paired with its observed data and
   its role: development, calibration, verification or prediction.

The areas are:
- Question and context of use;
- Drug substance (physico-chemistry);
- ADME and disposition;
- Formulation and what changed;
- Solubility;
- In vitro dissolution;
- Clinical design and populations;
- Observed PK;
- Data requests;
- Simulation plan.

The report is shown in the platform and can be exported (PDF; slides later).

### 3.2 The model inputs (for PK-Sim)

The exact numbers that go into the PK-Sim project, each traced to its evidence. All PK-Sim names below are from the
harvested catalog (`services/engine-worker/golden/catalog.json`) and the reference snapshot
(`golden/example_snapshot.json`).

- **Compound:**
  - molecular weight, lipophilicity, pKa, solubility (the reference value and the pH table), fraction unbound,
    permeability;
  - clearance processes (e.g. `MetabolizationSpecific_FirstOrder`, `GlomerularFiltration`) with their parameters.
- **Formulation per product and batch:**
  - from the fitted dissolution release (the owner's choice for cinacalcet): `Formulation_Tablet_Weibull` with
    `Dissolution time (50% dissolved)`, `Dissolution shape`, `Lag time`;
  - `Formulation_Dissolved` for solutions;
  - which medium's profile is fitted is a recorded modeler decision.
- **Individual and population:**
  - a population database (e.g. `Asian_Tanaka_1996`, `European_ICRP_2002`), sex, and the age, weight and height
    from the study's demographics;
  - ranges and size for virtual trials.
- **Protocol:** `ApplicationType`, `DosingInterval`, `InputDose`, `Infusion time`, `Start time`.
- **Events:** meals at their stated times (e.g. `Meal: Standard (Human)`, `Meal: High-fat breakfast (Human)`). The
  choice of template is a recorded decision when the meal composition is unknown.
- **Observed data:**
  - one table per arm, aggregated (mean, its spread type and N at each time) and individual;
  - with `Study Id`, `Grouping`, `Data type`, `N`, `Molecule`, `Organ`, `Compartment`, `Route`, `Dose`,
    `Formulation`, `Food state`.
- **Evaluation targets (not PK-Sim inputs):** Cmax, AUC and Tmax per arm (geometric and arithmetic), BE ratios and
  90 % CI, f2. They judge the simulations, in the existing acceptance and VBE checks.

These feed the existing CPF and snapshot builder. A PK-Sim name not yet harvested (e.g. a table formulation) is
harvested from the engine before it is used.

## 4. Principles

1. **Question first.** The project's question decides the required inputs; everything else is triaged out with a
   reason.
2. **Nothing invented.**
   - Every value is read (with file, page and cell or quote), computed (with the rule and its inputs), entered by a
     person, or marked missing.
   - Never defaulted silently.
   - The rate of invented values must be zero in every test.
3. **The agent proposes, code verifies, the modeler decides.**
   - An AI model reads and proposes.
   - Deterministic code checks every number and quote against the source and does all arithmetic (means, NCA, f2,
     fits, unit conversions).
   - Modeling judgments are shown as decisions with evidence and a suggestion. Examples: the analysis set, the
     population, the formulation type and medium, meal templates, outliers, and calibration versus verification.
4. **Generic, not per case.** No reader written for one layout. The same agents, tools and schemas handle any
   delivery. New cases improve prompts, tools and tests, not special branches.
5. **Measured, not assumed.** Real deliveries with known answers score every stage and every model before anything
   is trusted.
6. **Model-agnostic.** Any agent can run on Qwen Coder, Claude or gpt-oss-120b, chosen per agent.
7. **Traceable for regulators.** Every PK-Sim input links back to its evidence and decision. The existing audit chain
   and signatures record who confirmed what (21 CFR Part 11, ICH M15).

## 5. The flow

| Stage | What happens | Who | Output |
|---|---|---|---|
| 1. Intake | Files stored as received (hash, type, pages); archives unpacked; duplicates found by content; scanned pages detected and read by OCR or a vision model | Code (+ vision model for scans) | Inventory with a text layer for every page |
| 2. Question | The proposal, request email and data plan read; context of use, products to compare and required inputs drafted from the platform's data-plan templates (`requirements/*.yaml`), tailored to the question | Agent drafts, **owner confirms** | Question card + checklist |
| 3. Triage | Every file and page classified (clinical data, design, demographics, composition, manufacturing, dissolution, drug substance, ADME, literature, regulatory paperwork) and linked to checklist items, or set aside with a reason | Agent, code checks coverage | File map: what each file is for |
| 4. Extraction | Per checklist item, the agent reads the relevant pages and tables with tools (text, OCR, table parsing in a sandbox, spreadsheet reading) and returns typed records (§6) with citations | Agent | Proposed evidence records |
| 5. Verification | Every number is matched to its cited cell or text; every quote is found verbatim; units parsed; a second pass (another prompt, or another model) checks the semantic mapping (treatment codes, arms, which batch) | Code + second agent pass | Verified records, rejections with reasons |
| 6. Assembly | Facts joined across files: one study record, arms, subject flow, analysis sets with their rule, product → batch → dissolution links; derived numbers computed | Code | The evidence base (§6) |
| 7. Status and gaps | Each item gets its status (§3.1); conflicts listed; data requests drafted with codes and wording | Code + agent drafts wording | Status table, conflict list, data requests |
| 8. Decisions | Decision cards (analysis set, population, formulation type and medium, meal events, outliers, calibration/verification split), each with evidence, options and a suggestion | **Modeler decides** | Recorded decisions |
| 9. Outputs | The evidence report (§3.1) and the PK-Sim inputs (§3.2), both from the same evidence base and decisions | Code | Report + CPF + snapshot inputs |

New files can arrive at any time. They re-enter at stage 1, and only what they change is redone.

## 6. The evidence base (the canonical data model)

Generic record types. Every field carries its source and status. These are CDISC-shaped where a standard exists
(SDTM PC, DM, EX, TA; ADaM ADPC, ADSL), so a client's CDISC datasets load directly.

| Record | Key fields |
|---|---|
| Project question | question, regulator, products compared, context of use, required-input checklist |
| Document | file, hash, pages, type, scanned?, duplicate-of, relevance |
| Drug substance property | property (MW, pKa, logP/logD, solubility at pH/medium/temperature, fu, B/P, permeability, particle size d10/d50/d90, solid form), value, unit, conditions |
| ADME fact | absorption, distribution, metabolism (enzymes, fm), elimination, food effect, DDI; value or statement |
| Product | name, role (Test/Reference/original/reformulated), strength, dosage form, release type, manufacturer |
| Composition | product, component, amount per unit, function, grade; process step changes |
| Batch | product, batch number(s) as written, lot aliases, use (BE study, dissolution, stability), API batch, particle size |
| Dissolution run | batch, medium, pH, surfactant, volume, apparatus, speed, temperature, n units; values per unit per time; mean, spread type, CV |
| Study | id, title, design (parallel/crossover, periods, sequences, washout), single/multiple dose, fasted/fed, meal times and type, co-medication, sampling schedule, analyte, matrix, LLOQ, bioanalytical method |
| Arm / treatment | study, treatment code and meaning, product, batch, dose, route, regimen |
| Subject | id, sequence, demographics (age, sex, weight, height, BMI, race), disposition (dosed per period, completed, reason) |
| Concentration | subject, period, treatment, nominal time, actual time, value, unit, BLQ flag |
| PK result | subject or summary, parameter, value, statistic (arithmetic/geometric), set |
| Analysis set | name, rule, subjects in/out with reasons, which outputs use it |
| Decision | topic, options, evidence, choice, by whom, when |
| Data request | code, area, text, linked items, status |
| Simulation plan row | formulation + condition, observed data, role |

## 7. The agents

| Agent | Job | Tools | Default model (switchable per agent) |
|---|---|---|---|
| Reader | Text, OCR and page images; scanned-page detection | PDF/Word/Excel/text readers, OCR, page render | A vision-capable model for scans (Claude); gpt-oss-120b is text-only |
| Question | Context of use and checklist from the proposal and templates | Template library, document search | Any |
| Triage | Classify files and pages; link them to checklist items | Document search | Any (fast/cheap) |
| Extractor | Typed records with citations, per checklist item | Page and table readers, a Python sandbox to parse tables, unit library | Strongest available |
| Checker | Second pass on mappings (codes, arms, batches); asks the extractor to redo | Same, read-only | A different model from the extractor where possible |
| Writer | Findings, data-request wording, report text (never numbers) | Evidence base (read-only) | Any |

All numbers are code-checked (§4.3). Prompts and schemas are generic and versioned. Each agent's output is cached per
document hash, so re-runs are cheap.

## 8. Three models, switched per agent

- **What exists today:**
  - Per-agent provider choice in the admin console (`platform_settings.AGENT_PROVIDERS`).
  - The in-house model through LiteLLM (Qwen Coder).
  - Claude on Amazon Bedrock (Opus, Sonnet, Haiku).
- **Add:** a **GroqCloud** provider for `openai/gpt-oss-120b`.
  - It uses Groq's OpenAI-compatible API (`https://api.groq.com/openai/v1`), as in the owner's example.
  - The key is entered once in the admin console and stored like the other keys, never in code or chat.
  - Settings: `reasoning_effort` (low, medium, high), temperature, max tokens.
- **One click per agent:**
  - Each agent's row in the admin console gets three buttons (Qwen Coder · Claude · gpt-oss-120b) and shows the
    model in use.
  - A per-project override is possible later if needed.
- **Capability check before a switch:**
  - Tool calling, structured output and vision are marked per model.
  - An agent that needs vision (scanned pages) warns before being switched to a text-only model.
- **Same tests for all three.** The evaluation (§9) runs on each model, so the choice per agent is based on scores,
  cost and speed.
- **Data protection.** Client files go to whichever provider an agent uses. GroqCloud is a third-party cloud; the
  owner confirms per client whether that is allowed. The page says which provider each agent sends data to.

## 9. Proof: evaluation on real deliveries

| Case | Source of truth |
|---|---|
| Cinacalcet (PBBM, reformulation) | The owner's kick-off report v2, kept outside the repository (client-confidential): its analysis set, geometric-mean Cmax and AUC per arm, Tmax, f2 per medium, solubility table, composition and process-change tables, data requests |
| Desvenlafaxine (VBE) | The owner's PK-Sim entries for it (to be provided) |
| Exampleamide / Clientamide | Synthetic: kept only as regression tests, never as proof |
| 2–3 new deliveries from the owner | The owner's own extraction |

**Scores per case and per model:**
- found / missed / wrong for each checklist item;
- exact match of the numbers that go to PK-Sim;
- invented values (must be 0);
- valid citations;
- conflicts found (recall);
- correct data requests;
- time and cost per delivery.

A stage is done only when it meets its target on every real case. A target is never lowered to pass.

## 10. What happens to today's code

- **Kept:**
  - the file store;
  - the audit chains and signatures;
  - the CPF and snapshot builder;
  - NCA, f2 and the Weibull fit (`pbpk_domain.nca`, `pbpk_domain.dissolution`);
  - the data-plan templates;
  - the blinding rules;
  - the agents' provider layer;
  - the steps after Inputs (plan, runs, acceptance).
- **Replaced behind a switch:**
  - the sheet-form reader and the delivery pipeline as the way client data enters the model;
  - the Inputs page's two-path cards.

  Both stay available until the new flow passes §9 on the real cases. Then the owner decides to retire them.
- **Locked files and SME rules are not touched** (rulesets, requirement levels, MS-01, CPF schema, builder). If a
  change is needed there, it goes in its own PR with the owner's approval, as CLAUDE.md requires.

## 11. Phases (each ends with a check the owner can see)

| Phase | Builds | Done when |
|---|---|---|
| P0 | GroqCloud provider and one-click per-agent switch; the evaluation harness; the cinacalcet truth set from the kick-off report | A test call works on all three models; the harness scores a dummy run |
| P1 | Intake (stage 1) and the question (stage 2) | On cinacalcet: every file inventoried, every scan read, the checklist matches the proposal's data requirements A–D |
| P2 | Triage and extraction with verification (stages 3–5), clinical and dissolution first, then composition, drug substance and ADME | Cinacalcet numbers match the truth set; zero invented values; each model scored |
| P3 | Assembly, status, data requests, decision cards (stages 6–8) | The cinacalcet subject flow (dosed per period, completed, statistical set, proposed set, AUC set), its conflicts (batch, reference lot, coating) and data requests reproduced |
| P4 | Outputs (stage 9): the evidence report in the platform and as a PDF; the PK-Sim inputs through the builder | The report matches slides 7–14 in content; the PK-Sim project builds and runs on the real engine with traced inputs |
| P5 | Run on the owner's new deliveries; fix what fails; re-score all cases | All real cases at target; then the owner decides on retiring the old paths |

## 12. What I need from the owner

1. **GroqCloud.** An API key, entered in the admin console (not in chat). Also: may client data be sent to Groq, and
   from which server? The server must be able to reach `api.groq.com`.
2. **Truth for the real cases:**
   - the numbers you would enter in PK-Sim for cinacalcet (or the project file once built);
   - the same for Desvenlafaxine;
   - for the 2–3 new deliveries, the delivery plus your kick-off report or extraction.
3. **Vision and OCR.** For scanned pages, may we use Claude (vision) or an OCR engine on the server?
4. **Decision defaults.** Your usual choices:
   - population database for Indian subjects;
   - which dissolution medium you fit Weibull to;
   - default meal template when the composition is unknown;
   - analysis-set rules (e.g. exclude subjects with all samples below the LLOQ).

   The system then suggests these and records your choice.
5. **Blinding at intake.** Should values be hidden while data is being checked, or only from model building
   (MS-01)?

## 13. Risks

- **Scanned and complex tables.** OCR errors on numbers. Mitigation: numbers from scans are always marked "from a
  scan" and need confirmation unless a second source agrees.
- **Model variation.** The same prompt gives different answers across models. Mitigation: code verification, the
  checker pass, and per-model scores.
- **Cost and speed of large deliveries** (hundreds of pages). Mitigation: triage first, per-item extraction, a cache
  per document hash.
- **Scope creep in the report.** It shows what the question needs, not everything in the files.
