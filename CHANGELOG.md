# Changelog

Every notable change to Modeler One, newest first. **Any commit that changes behaviour adds an entry here in the
same commit** — see `CLAUDE.md`. Each entry says what changed, why, and the commit, so the history survives a change
of person, session or AI model.

Status words: **Added** new capability · **Changed** behaviour altered · **Fixed** a defect, with its impact ·
**Known gap** a limitation we know about and have not yet fixed · **Docs** / **Infra** as named.

Where things stand right now, stage by stage, is in `docs/CONTINUATION_PACKAGE.md` §4 (pipeline coverage).

---

## [Unreleased] — make the pipeline do real PBPK, S0 → S7
Plan: `docs/plans/2026-09-24-s0-s7-real-pbpk.md`. Scope agreed 2026-09-24: complete every MS-01 stage, prove it on
published OSP models against their real clinical data on real PK-Sim. DDI / paediatric application templates follow.

### Changed — Inputs opens once Start is done (page review 1, decision 7)
The owner's decision 7 of 2026-10-29.
- **Before:** Inputs, opened by its address before Start was done, showed a red banner and let the person work.
- **Now:** Inputs that have not begun are blocked until Start is done. The page says what Start still needs and links
  to it; the workspace is not shown, so nothing is gathered for a question not yet set.
- **Inputs that have begun stay open,** with the red banner, as in the step bar (#105). A project whose Start gains a
  requirement later, such as the M15 texts of #106, is never locked out of inputs it already gathered.
- **A project with no Start** (made through the API without a proposal: scripts, templates, the reference runs) keeps
  the banner and is never blocked, since it has no Start to finish.
- **The guard is the page.** The API still accepts inputs before Start is done, as the agents and the reference runs
  build projects through it.
- **Tests:**
  - The browser specs that open Inputs now finish Start first, through the API as a person would (`finishStart` in
    `e2e/fixtures/inputs.ts`). The helper checks that Start is done.
  - `start-project.spec.ts` shows Inputs blocked, then open once Start is done.

### Added — a project is archived, never deleted (page review 1, decision 5)
The owner's decision 5 of 2026-10-29 ("archive"). A project is a Part 11 record: its signed MAP, campaigns and audit
trail cite it.
- **Archive:** `POST /projects/{id}:archive` hides a project from the Projects list, with a reason.
  - Nothing it holds is changed or erased, and it still opens by its address.
  - It is refused while one of the project's campaigns is queued or running.
- **Restore:** `POST /projects/{id}:restore`, with a reason.
- **Where it lives:** both are audit events (`project.archive`, `project.restore`) in the tenant's chain. The state is
  kept per tenant in `<root>/<tenant>/archive.json` (`modeler_project.archive`), like the memberships.
- **The list:** `GET /projects` marks each project's archive (who, when, why). The Projects page hides archived
  projects until **Show archived**, and has **Archive** and **Restore**, each asking why.
- **History:** a project's audit trail (`GET /projects/{id}/audit`) now includes the events on the project itself: its
  members and its archive. Before, it listed only its artifacts' events, so member changes were in the chain but not
  in the project's History.
- **Tests:**
  - `test_project_archive`: archive and restore with their reasons and audit events, refused with no reason, with a
    running campaign or for a person who may not open the project; History lists both.
  - `projects-archive.spec.ts`: the page flow.

### Changed — the evidence grade is a versioned rubric, and a prediction never outgrades a measurement (8c; UNVERIFIED)
The owner's decision 8c of 2026-10-29: the grade carries what the parameter's status says, so the grade and the status
no longer point at different parameters (PI-2b, `docs/plans/2026-10-23-parameter-identification-review.md`).
- **Before:** the A–D grade was code in `evidence.assess`, not SME-governed data.
  - It already graded a PREDICTED source C, below any measurement.
  - But a publication reporting an in silico value (a predicted logP, say) was a PUBLICATION source, and graded A.
  - A human in vitro clearance (microsomes, hepatocytes, recombinant enzymes) got the same A as one from a clinical
    study.
  - Only rat, dog, mouse and monkey counted as animal, so a pig or rabbit value could be graded A while flagged
    `species_mismatch`.
- **Now:** the rubric is `modeler_project/evidence_grading.yaml` 0.1 (UNVERIFIED), read by `evidence.assess`. Its rules
  are read in order, and the first that applies gives the grade. It keeps the earlier rules and adds three:
  - **A value its own source calls predicted is C.** The recorded conditions' values are read for "predicted", "in
    silico", "QSAR" and "QSPR"; their names are not (`measured or predicted` names a condition).
  - **A human in vitro value is B where an in vivo value can exist:** clearance (`elim.*`), transport (`transp.*`)
    and permeability (`perm.*`). Parameters measured only in vitro (logP, pKa, fu, solubility) are not affected.
  - **More species count as animal** (minipig, pig, rabbit, guinea pig, hamster, cynomolgus, marmoset).
- **Impact:**
  - Which source a model input keeps can change where two sources of one kind differ in grade (`source_selection.yaml`
    orders within a source by grade).
  - The grade the signed MAP records for PI-2b's choice can change, so a non-identifiable pair may fix the other
    parameter.
  - An item is graded when it is proposed. Items already in a project keep their grade, so a project can hold grades
    from both rubrics.
  - Each new item records the rule that gave its grade and the rubric version (`EvidenceItem.grade_reason`,
    `grade_rubric`, new optional fields; empty on items graded before 0.1). The API contract gains both.
  - No locked file is touched.
- **For the SME (`docs/SME_SIGNOFF.md`):** the rules and their order, the words, which parameters an in vivo study can
  measure, and whether a human in vitro value should be B for each of them.
- **Tests (`test_evidence`):**
  - the earlier grades, unchanged;
  - the rubric names only checks the code knows;
  - each new rule;
  - over every source type, extraction and system: a prediction is never graded above a measured value.

### Changed — the agent drafts the ICH M15 assessment and a person confirms it (page review 1; UNVERIFIED)
The owner's decisions 1b and 4 of 2026-10-29, recorded with all 14 answers in `docs/plans/2026-10-23-page-by-page-review.md`
§4.3.
- **Before:** the intake agent only extracted. It could quote the proposal's own description of model influence and
  decision consequence, but never rated them. With no such words, the ratings stood with no reason, and Start did not
  ask for one.
- **The draft:** a new agent tool, `draft_risk_assessment`, runs once the question of interest and context of use are
  recorded.
  - It suggests both ratings, each with one or two sentences on why, built from those two fields and citing their
    quotes.
  - All four values are stored with a new brief status, **`DRAFTED`**: written by an agent from the brief, stated in
    no document. `DRAFTED` is not a value: `brief.value()` reads it as `None` until a person confirms or changes it.
  - The suggested ratings are new fields (`m15.influence_suggested`, `m15.consequence_suggested`), filled only by the
    draft, never by a quote.
  - The ratings that count, the tier and the justification stay human-only (`HUMAN_ONLY`, unchanged). The agent never
    writes them.
  - The proposal's own words (EXTRACTED) and anything a person set are kept over a draft.
- **Start:** the suggested ratings are preselected in the model risk, and they count once the person saves them.
  - Under the ratings, **How the model is used** and **What a wrong decision means** each show the draft, marked as
    one, with **Confirm** and **Change**.
  - Start is not done until both are in a person's words or confirmed by one. With no agent, the person writes them.
- **Review & sign:** the credibility block shows both texts to the signer (`ReviewRisk.influence_text`,
  `consequence_text`; a draft no person confirmed is not shown). They are not yet under the MAP hash: that is a locked
  `map.py` change, for its own PR.
- **Impact:** a project whose Start was done but has no M15 texts now shows Start as needing you. With #105, its later
  steps stay open. The T-56 proof (`deploy/proof/run_t56.py`) now writes both texts in the person's words.
- **For the SME (`docs/SME_SIGNOFF.md`):** the rating guidance in the agent's prompt, and whether a preselected
  suggestion anchors the person's rating.
- **Tests:**
  - `test_proposal_intake`: the draft, what it refuses, that it stays `DRAFTED`, and a person's word kept.
  - `test_steps`: written, drafted, extracted and confirmed.
  - `test_brief_api`: a scripted draft confirmed through `PUT /brief`.
  - `start-step.spec.ts`: the manual path.
  - `review-sign.spec.ts`: the signer sees the texts.

### Fixed — a project that has moved past Start is never locked out of its later steps
- **The defect (from the Start page PR, #104):** the step bar locked Inputs, Review & sign and Run whenever Start was
  not done. A project whose Start gains a requirement later lost its links to its plan and its campaign, even with a
  signed MAP or a campaign running. This includes projects created before #104's Start checks, and any later
  required field.
- **Now:** only the steps that have not begun wait on Start. A step that has begun (done, running or needing you)
  always opens.
- **Test:** `review-sign.spec.ts` checks a project whose Start is not done but whose inputs are: Inputs opens, and
  Run (not begun) waits on Start. Against the old step bar the check fails (Inputs locked).

### Changed — the Start page, rebuilt from the owner's marks (page review 1)
The owner marked the 48 elements of Start between 2026-10-25 and 2026-10-28 (review page `FLcNRsUrnCJcEcDTkDhqzE`,
collection `decisions`). Plan: `docs/plans/2026-10-23-page-by-page-review.md` §4.
- **What waits on the person is marked where it is.** The side panel ("Waiting on you") is gone.
  - Each field that still needs the person is marked red, with a ⚠ line saying why. Open questions show on their own
    field.
  - A bar at the bottom says how many are left. "Continue to Inputs" stays disabled until none is.
  - The step bar locks the steps after Start until it is done. Inputs, reached by its address, says so in a red
    banner. It is not blocked, because 13 browser specs open it directly.
  - The API sends each problem with its field (`start.issues`: path and message); `start.problems` is unchanged.
- **Dropped from Start:**
  - the title, the agent chip and the intro line;
  - the "what the files are" selector: a workbook goes to the client's data, every other file to the documents;
  - InChIKey (MW is shown on Inputs as `phys.mw`, with its source);
  - the hint paragraph and the open-questions list;
  - "How the model is used" and "What a wrong decision means";
  - the data checklist: items, who provides each, status, inline warnings, the count line;
  - "Proposal notes": the other brief fields, products, populations, what the proposal says about data, and the
    prediction scenarios.
- **What stays behind the screen:**
  - The brief keeps all the dropped fields, and the data plan is still derived from it on every change.
  - The data plan's provider override stays in the API (`PUT …/requirements/{req_id}`), with no screen.
  - Nothing gated on the checklist: only the `doctor` report reads its "blocking" list.
- **Moved:**
  - History, from the step bar to a "Record" column on the Projects page;
  - the internal target, from the notes to under the model risk;
  - the dose, from the notes to each route on the product line;
  - the document viewer, from the side panel to a dialog that opens from a value's source.
- **Changed:**
  - **Applications:** each says, by its plain name, what data it adds (`application_additions()`, read from the
    requirement templates' `applies_to`).
  - **Pathways:** the kinds and the stated names are one list: each enzyme, transporter or route with its kind.
    - A pathway the published OSP model has and the proposal does not name is flagged, with "Add it"
      (`feasibility.pathways_not_named`).
  - **Nonlinearity and enterohepatic recycling:** each is yes / no / not stated.
  - **The model risk** shows the tier's criteria and the ruleset version beside it ("medium: AUC within 1.5-fold and
    Cmax within 1.5-fold, in 80% of studies").
  - **Internal target:** a target looser than the tier allows (MS-01 §8, `loosest_internal_target`) is now marked at
    Start. Before, it was refused only when the MAP was generated.
  - **What is modelled:** modality, PBPK model and site of action read as one line once all three are supported.
- **Science (the data plan; for the SME, UNVERIFIED):** "no" to nonlinearity is stored as not applicable, and the data
  plan now reads that as linear pharmacokinetics.
  - Items that apply only when nonlinearity is stated (Km, Vmax) drop out.
  - Before, "no" left them undetermined.
  - The requirement templates are unchanged.
- **Planned, not built:**
  - The project document library, which takes over Start's file list and viewer:
    `docs/plans/2026-10-28-project-document-library.md`.
  - The product types the owner asked to plan (large molecule, other modality, minimal PBPK, local site of action):
    the page-review plan §4.
- **Tests:**
  - `test_steps`, `test_requirements` and `test_brief_api` gained cases.
  - `start-step.spec.ts` was rewritten, and `start-project.spec.ts` updated.
  - `client-data-guided.spec.ts` now checks what arrived through the API.

### Changed — a non-identifiable pair is fixed and refitted (PI-2b, MS-01 fix_and_refit; locked `map.py`; UNVERIFIED)
The owner's decision of 2026-10-25 ("PI-2b: build it"), with the owner's rule for "the more reliable source"; plan
`docs/plans/2026-10-23-parameter-identification-review.md` PI-2b. It closes PI-2's known gap.
- **Before:** a fit whose two parameters were correlated beyond |r| > 0.95 was flagged (PI-2), but the pair never
  reached the diagnosis, and MS-01's `fix_and_refit` would have fitted nothing (its target `a|b` matched no
  parameter, and its op was not recognised as a fit).
- **The pairs reach the diagnosis.** `assess_round` hands the best start's pairs beyond 0.95 to the diagnosis as
  `correlated_pairs`, strongest first (`assess_fit` orders them). diag-rules' `non_identifiable_pair` then permits
  `fix_and_refit a|b`. The ruleset is unchanged (0.6).
- **The owner's rule** (`pbpk_domain.identifiability`): fix the parameter with the more reliable source at its source
  value from the signed MAP, then refit.
  - More reliable is the higher evidence grade (A–D), and a measured value (status FIXED) beats a predicted one
    (PREDICTED).
  - Grade is compared when both have one. Status is compared when both are measured or predicted; FITTED and DERIVED
    are not ranked.
  - Where grade and status point at different parameters, the grade decides (the owner, 2026-10-27; to be revisited
    with the SME).
  - A tie is never guessed: equal grade and status, or a pair neither comparison ranks. The round escalates to the
    modeller, and the reason names both parameters' grade and status.
  - A parameter that is not in the signed MAP's table (another compound of a model system) cannot be fixed at a signed
    value, so it escalates too.
- **The round** (`campaign_activities`, for both the local and the Temporal runner):
  - it writes a new CPF version with the fixed parameter back at its signed value and status, with no fit and no CI,
    and `supersedes` naming the fitted value;
  - it builds the snapshot from that version, and fits the previous fit's other parameters;
  - the fixed parameter stays out of the stage's later fits, and the fixed version carries forward even when the
    refit produces no estimate;
  - the build and the diagnosis each write a note naming which parameter is fixed, at what value, and why.
- **Locked `campaign/map.py`, approved by the owner (2026-10-27) after seeing the diff:** `MapParameter.grade`. The signing route
  records each input's kept source grade from the review table (`review.grades`, `plan.map_from_plan`).
  - The grade is left out of the content hash when unset, so a MAP signed before keeps its hash.
  - It is not compared with the campaign CPF (D-36), which does not carry grades.
  - The reference runs and the published-model paths sign no grades.
- **Records:** `docs/SME_SIGNOFF.md` (the rule, the 0.95 limit, the order of grade and status). The OpenAPI snapshot and
  the web types gain the optional `grade`. Locked hashes refreshed.
- **Impact:** a campaign whose fit finds a non-identifiable pair now acts on it: it refits with one parameter fixed, or
  escalates where the signed sources cannot rank the pair. Before, such a round chose another rule's action, or
  escalated with no permitted action. Verdicts and every other decision are unchanged. A parameter at its bound still
  escalates first (`param_at_bound`).
- **PK-Sim:** `dapagliflozin-refit` before (run 40206672048, `main` 35e0954) and after (run 40739239767, this branch,
  3d7e38c) give the same result:
  - S1 escalates after the clearance fit, with UGT1A9 clspec at its lower bound and UGT2B7 clspec at its upper bound.
  - GMFE goes from 2.478 / 2.516 to 1.412 / 2.291.
  - No pair passes |r| > 0.95, so `fix_and_refit` is not reached here: a parameter at its bound escalates first.
- **What the full fit note now shows** (the reference summary prints it whole):
  - Every clearance's 95 % CI is wider than its estimate and reaches below zero: UGT1A9 0.040 [−0.031, 0.111], UGT2B7
    0.066 [−0.39, 0.52], hepatic CYP 0.963 [−0.66, 2.59].
  - Only 59 % of the starts reach the best solution.
  - The one IV study does not separate the three parallel clearances. This is the case PI-4 (fit a common factor on
    parallel pathways) is for.
  - It is also the kind of `POORLY_DETERMINED` finding the PI-3 decision watches for: a linear-scale Hessian CI that
    reaches below zero for a positive parameter.

### Docs — log-scale fitting stays linear for now; a parameter transform is proposed to OSP (PI-3, decided)
The owner's decision of 2026-10-25: options (c) + (b) of `docs/plans/2026-10-23-parameter-identification-review.md` PI-3.
- **Why a decision was needed:** `ospsuite.parameteridentification` 2.2.0 writes the optimiser's values straight into
  its simulation batches (`SimulationBatch$addRunValues`), so a log scale cannot be added through its public API. Found
  on PK-Sim in engine-image run 40079660726; see the PI-2 entry below.
- **(c) Stay linear for now.** The fits keep the log-sampled multi-start, which spreads the starts over the decades.
  `run_pi.R` is unchanged.
- **(b) Propose a transform upstream.** The draft feature request is
  `docs/upstream/2026-10-25-osp-pi-log-scale-request.md`. It is not sent until the owner approves its text. Once OSP
  releases a transform, it is adopted only after it is pinned and re-qualified in the engine image (a locked
  Dockerfile change, in its own PR).
- **(a) Revisited only on evidence.** Our own log-space optimisation, which drives the package's internal objective
  function, is reconsidered only if `POORLY_DETERMINED` or `NO_CI` findings show up often in real fits.
- **Verified on PK-Sim after #100 and #101 merged:** `dapagliflozin-refit` on `main` 35e0954 (Actions run 40206672048,
  engine 12.4.4, PI 2.2.0) gives the same result as the recorded refit (run 39286267822). S0 PASSED. S1 ESCALATED
  after the clearance fit, with UGT1A9 clspec at its lower bound (0.0399) and UGT2B7 clspec at its upper bound
  (0.066). GMFE: baseline 2.478 / 2.516, after the fit 1.412 / 2.291. The Boulton 2013 IV Cmax is 0.44× (PE −56 %).
  PI-2 changed the record, not the result.

### Changed — every fit records its CI and its parameters' correlations (PI-2; locked `run_pi.R`; UNVERIFIED)
The owner's decision of 2026-10-24 ("approve run_pi.R PR"); plan `docs/plans/2026-10-23-parameter-identification-review.md` F2.
- **Before:** `fitting.assess_fit` could flag a correlated pair or a wide CI, but it was never given either, and
  `run_pi.R` did not export the correlations. A fit whose parameters the data cannot separate passed unflagged.
- **`run_pi.R` exports the correlations.** It writes the correlation of each pair of fitted parameters from the
  Hessian CI (`ciDetails$corMat`), keyed by CPF id. When no CI could be estimated, it writes why (`ci_error`, for
  example a covariance that is not positive definite, itself a sign the parameters are not all identifiable).
- **`assess_round` judges them.** It gives the best start's correlations and 95 % CIs to `assess_fit`, which flags:
  - `HIGHLY_CORRELATED` for a pair beyond MS-01's |r| > 0.95;
  - `POORLY_DETERMINED` for a CI wider than its estimate;
  - `NO_CI` when there is no CI.
- **Each stage's notes show the result:** every estimate with its 95 % CI, and the strong pairs.
- **Not yet acted on (known gap):** the correlations are recorded and flagged, but they are not handed to the
  diagnosis (`correlated_pairs` stays empty).
  - **Why:** MS-01's action for a non-identifiable pair ("fix the one with the more reliable source; refit",
    diag-rules `fix_and_refit`) is not carried out by the runner yet. Its target `a|b` matches no parameter, so the
    round would fit nothing.
  - **Next:** PI-2b, which needs the owner's choice of the value to fix at.
- **Fixed in passing:**
  - **The CV unit.** The engine's CV is a fraction (sd / |estimate|), and the CPF stored it as `cv_percent`
    unchanged. It is now ×100.
  - **The model-system fit reasons.** `_build_fit_request` reused the name `why` for an analyte lookup, so in a model
    system the round's list of reasons why a fit did not run was replaced, and appending to it raised
    `AttributeError` (from #97). A regression test now covers it.
- **Golden (locked `pi_smoke.R`):** a two-parameter Aciclovir fit (lipophilicity and tubular secretion, at the path the
  package's own tests fit) must report its correlation, or why there is none.
  - **Passed on PK-Sim** (engine-image run 40080162775 on a90d450, PK-Sim 12.3.173, ospsuite 12.4.4, PI 2.2.0): the
    Hessian CI was estimated and `r(Lipophilicity, TSspec) = 0.42`. The single and weighted smoke cases, the golden
    tasks, the Aciclovir benchmark fit (41 evaluations, objective 6.57) and the Weibull check passed unchanged.
- **Not done: log-scale optimisation (PI-3).**
  - **Tried:** a `PIParameters` subclass that applies 10^x.
  - **Why it cannot work:** `ospsuite.parameteridentification` 2.2.0 writes the optimiser's raw values into its
    simulation batches (`SimulationBatch$addRunValues`) and never calls `PIParameters$setValue`. The package has
    no parameter transform.
  - **Found on PK-Sim:** this PR's first engine run set the secretion to its log10 (−0.30), and the simulation failed
    (run 40079660726).
  - **What would work:** driving the package's internal objective function directly, or a transform added upstream.
    That is a decision for the owner.
- **Impact:**
  - **The record:** fits gain findings and notes. More fits are marked "not acceptable", but no run uses that flag to
    decide anything.
  - **Unchanged:** the estimates, the verdicts and every decision.

### Fixed — the engine image builds again: parameter identification 2.2.0 pinned to its release (PI-1; locked file)
The owner's decision of 2026-10-24 ("pin 2.2.0"). The OSP r-universe now serves only `ospsuite.parameteridentification`
2.3.0, so every engine-image build since 2026-10-23 stopped at its own version check (2.3.0 is not the qualified
engine), `main` included (run 39964142511 on the #97 merge). No new image could be published.
- **`services/engine-worker/Dockerfile`** installs PI 2.2.0 from its release tag `v2.2.0` (commit `cb9e9e58`), as
  ospsuite 12.4.4 already is. The package is pure R; its declared Imports are installed first, and 2.3.0 is never
  installed.
- **Integrity:** the downloaded source must hash to `PI_TREE_SHA256`, the sha256 over every file's sha256 in byte
  order of path. It was computed from the tagged commit's 132 tracked files. A file-tree hash is used because
  GitHub's archive bytes are not promised stable, while the files are. A changed source fails the build.
- **The qualified set is unchanged:** ospsuite 12.4.4, PI 2.2.0, rSharp 1.2.2, checked by the same version guard.
  The golden suite, the PI smoke test and the Weibull check run in the image as the publish gate.
- **Impact:** none on results; the engine is the qualified one. The image digest changes (rebuilt), so the next
  image registration and IQ-05 record the new digest.

### Docs — two plans for the owner: parameter identification, and a page-by-page review (2026-10-23)
- **`docs/plans/2026-10-23-parameter-identification-review.md`** answers the owner's question "are we fitting?".
  - Parameter identification works on PK-Sim (the reference refits), but no fit has yet run in a T-56 campaign.
  - Findings against PBPK practice:
    - parallel hepatic pathways are fitted together from plasma data that cannot separate them;
    - the identifiability checks (correlations, confidence intervals) are wired but never fed;
    - the optimiser works on a linear scale over six decades;
    - parameters are chosen by rule, not by sensitivity.
  - A plan of steps PI-0 to PI-8 follows, each needing the owner's decision; the science steps also need the SME.
- **`docs/plans/2026-10-23-page-by-page-review.md`** proposes how to review the 13 pages the owner exported: map
  every element, the owner decides, one PR per page. It records a first pass of what the exports show, for example
  the Run page saying "No observed data yet" during a campaign, and the inbox mixing test fixtures with real items.
- **Impact:** none. Nothing is built until the owner decides.

### Docs — the URS covers every traced requirement: version 2, DRAFT for QA review (T-32; locked file)
The owner approved drafting it on 2026-10-23 ("URS: yes, draft it"). `docs/validation/requirements.yaml` had 11
requirements, while the tests traced 42 ids: the validation pack listed 31 of them with no requirement behind them.
- **Version 2 has 44 requirements**, each with its user requirement, its functional specification, a category and a
  GAMP risk (22 regulatory, 20 functional, 2 performance; 25 high, 17 medium, 2 low). It adds the CPF and builder (T-03,
  T-10), results ingestion (T-08), the MAP generator (T-16), escalations (T-17), the digitizer (T-19), the agent
  evaluation sets (T-21), CI (T-25), published-model projects (T-26), engine identity (T-28), application templates
  (T-31), the validation pack itself (T-32), the start-up pipeline T-40 to T-56, the decisions D6 and D7, and F-402 and
  F-404.
- **Rewritten:** T-05 is now the Part 11 records in PostgreSQL (append-only, migrations with their sha256, backups that
  restore), and T-06 adds project members and the refusal of the DEV verifier in production. Each functional
  specification states what is built and what the traced tests verify, not what was planned; SME-governed content
  stays UNVERIFIED.
- **Corrected:** version 1 used F-401 for the audit trail. In ARCHITECTURE_PACK, F-401 is the ICH M15 assessment
  table and F-404 the audit trail. The audit-chain test now traces to F-404, and the M15 tests to F-401.
- **Tests tagged** (markers only, no test changed): F-401 (4 M15 tests), F-402 (blinding, and a pilot start only on a
  signed MAP and its CPF), F-404 (every signature is an audit event), T-06 on project members and the production
  verifier, T-05 on production's PostgreSQL records, T-08 on results ingestion and the results API, T-16 on
  `test_map.py`, T-17 on `escalation:resolve`. The project-scoped CPF store test moved from T-08 to T-03, the
  requirement it verifies.
- **Verified:** the pack built from the full trace matrix has no gap, and no traced id lacks a requirement.
- **Still needed:** QA review of the draft; then its status is set and the version noted here.
- **Impact:** no behaviour change. The locked-file hashes are refreshed for `requirements.yaml`.

### Fixed — a campaign says whether it fitted, and why not (from the T-56 re-run of 2026-10-23)
The owner's T-56 re-run on PK-Sim (`camp_5a30f5fda3c547f18b597d6e7a08040c`) escalated at S1 after 5 seconds and was
stopped. Its S1 record showed only round 1 "baseline" and round 2 "branch dist.partition_method" (the IV Cmax 0.54×),
with no word on why the next action of the distribution rule, "fit phys.logp", was never tried. The reasons went only
to the API's log, at a level the server does not keep. So nothing on the record could tell a person whether parameter
identification ran. Now the stage's notes say it:
- **Which candidates the diagnosis could fit** at the stage, and which it could not (no fit bounds, or no such parameter
  or engine path). A candidate missing its D-37 bounds is visible here (most likely this run: its plan was signed
  before D-37 was deployed; to be confirmed on the server).
- **Why a planned fit did not run:** no fittable parameter, no observed profile of the stage's studies, the fit not
  specifiable, or no model file (`.pkml`) exported for it.
- **What each parameter identification did:** its parameters, how many starts ran, the best objective, a bound reached
  and how far the starts agree; or that no start gave an estimate.
- **Why the stage escalated:** the causes found, the actions tried, and that no permitted action was left.
- **The T-56 trace** (`run_t56.py trace`) lists each stage's outcome, rounds and notes, and counts the parameter
  identifications run; `pq.json` lists them too.
- **PQ-07 (the 1-hour goal)** is judged only on a campaign that reached its report; on one that stopped early it is
  "not checked" (it read "pass, 0 min" for this run).
- **The monitor's time budget** is the signed MAP's total (8 h by default), not a one-hour placeholder: the run already
  followed the MAP's stage budgets (S1 96 min here); only the display was wrong.
- **Impact:** no science change; what runs and how it is judged are unchanged. `RoundDiagnosis` gains `notes`.

### Added — validation pack V1: Installation and Performance Qualification (T-32)
The one item buildable while the owner and the SME decide (the owner's plan, 2026-10-15). GAMP 5 asks for IQ, OQ and
PQ; until now the pack had only OQ, and its IQ and PQ sections said "pending Helm/k3s", a deployment that does not exist.
- **IQ: `deploy/server/qualify.sh iq`** (read-only; `deploy/server/qualify.py`, standard library only) writes an
  `iq/1` record and prints ten checks:
  - **IQ-01** deployed from a clean `main` (`deploy/dev/deploy_to_server.sh` now records the commit, the branch and
    whether the tree was clean in `.deployed.json` on the server, and warns when it is not a clean `main`);
  - **IQ-02** every locked file matches its recorded sha256;
  - **IQ-03** the dependency locks and the runtimes (recorded);
  - **IQ-04** the PK-Sim R packages (`ospsuite`, `ospsuite.parameteridentification`) match the engine catalog the
    builder's names were harvested from;
  - **IQ-05** the engine identity the API stamps on every run is that catalog's hash;
  - **IQ-06** PostgreSQL 16 holds every migration with its file's sha256 (`postgres.sh applied`, new);
  - **IQ-07** Keycloak is the version `keycloak.sh` pins;
  - **IQ-08 to IQ-10** the API answers, the deployment is production with Keycloak sign-in, the web answers.

  A piece that is not installed is "not checked", which leaves the IQ **incomplete**, never passed.
- **PQ: `run_t56.py trace` also writes `pq.json`**, judged by `validation_pack.pq_checks`: real PK-Sim; a production
  run (every signature Part 11); the package built; every number traced; no MAR issue; the reproduction passed; within
  the 1-hour goal. The stages' outcomes are recorded, not judged: a model can fail validation while the system works.
  The T-56 campaign of 2026-10-22 predates the deployment record, so its PQ is **incomplete** (PQ-02 not checked); a
  new run on the pilot records PQ-02 as a FAIL, as it should.
- **A campaign records the deployment it ran under** (`CampaignRecord.deployment`: development, pilot or production;
  "pilot, then production" if it was resumed elsewhere), so PQ never takes the deployment from the day of the trace.
  Campaigns run before this have none, and PQ says "not checked".
- **The pack:** `ValidationPack` gains `iq` and `pq`; sections 6 and 7 show each check and the verdict (PASS, FAIL or
  INCOMPLETE), or say how to produce the record. `python -m pbpk_domain.report.validation_pack` renders a full pack
  from files. CI's call is unchanged (no IQ or PQ there).
- **Not done:** the URS (`docs/validation/requirements.yaml`) still has 11 requirements; extending it to Part 11
  records, step-up signatures, members, backups and blinding needs the owner's approval (a locked file, QA review).
- **Impact:** no science change. The API contract gains `CampaignRecord.deployment` (OpenAPI and web types regenerated).
### Fixed — Next.js 16.4.0 → 16.4.2: three security advisories, one critical (web only)
`npm audit` reports Next.js 16.0.0–16.4.0 as critical: unauthenticated remote code execution in the Image Optimization
API when SVG files are used (GHSA-2464-fhr4-w9xw), remote code execution in `use cache` functions that return typed
arrays (GHSA-673q-mjm6-r5xr), and a denial of service in the App Router through Server Actions (GHSA-p3m5-59mp-jv5r).
Next's own build now stops on 16.4.0, so `npm run build` failed. `apps/web` moves to the patch release 16.4.2
(2026-10-15; `package.json` floor `^16.4.2`, so a fresh install cannot fall back), with only Next's own packages
changing in the lock file. `npm audit`: 0 vulnerabilities. No code change, no new dependency.

### Changed (science) — the diagnosis may fit MS-01's candidates within MS-01's default bounds (D-37; UNVERIFIED)
The owner's decision of 2026-10-20 ("yes, after T-56"); T-56 ran on PK-Sim on 2026-10-22. Redesign §2 D-37.
- **Before:** S1–S3 fitted only what a person freed on Review & sign. The diagnosis named its candidates per stage, but
  `campaign_activities._fittable_candidates` drops one with neither a fit policy nor a plausibility range, and an
  assembled CPF has neither. So in a project where nobody freed a fit, the stages could only judge the starting model.
- **Now:** every MS-01 fit candidate of a stage (`ModelPlan.fit_candidates`) that a person neither estimates nor holds
  fixed gets MS-01 §2.2's default bounds and scale (`fit_bounds.yaml` 0.1, UNVERIFIED) as its fit policy, at the stages it
  is a candidate at (`plan.default_fits`, `estimation.ms01_default`). The diagnosis may then fit it there; it never has
  to. On the published Dapagliflozin model, 10 of its 11 candidates get one: the three hepatic clspec (S1, S2;
  [0.0001, 100] l/µmol/min, log), logP (S1; ±1.5), the GFR fraction (S1; [0, 3]), the cellular and intestinal
  permeabilities, the reference solubility and the tablet's Weibull t50 and shape. The measured fu stays fixed.
- **No default for:** a candidate MS-01 gives none for (the 0.1–10× fallback stays a proposal a person confirms), one
  MS-01 keeps fixed (a measured fu), one whose start value lies outside the default, and one the CPF already bounds.
- **A person keeps a candidate fixed** with a reason (`POST plan/fits/{id}:hold`) and lets the diagnosis fit it again
  (`:release`); after the signature each is a MAP deviation (D-14). Estimating a candidate replaces its hold; taking a
  person's fit back leaves MS-01's default. A hold survives a rebase while the parameter is still a candidate.
- **Signed and checked:** the staged campaign CPF and the MAP's parameter table carry the defaults (fit stages, bounds,
  scale), so the signature covers them and D-36 compares them at start. The MAP's limitations list each one and say the
  bounds are UNVERIFIED until the SME signs; a hold is a plan change in the MAP's rationale, with who and why.
- **Review & sign:** the estimation table shows "the diagnosis may fit it in S1" with the bounds, a filter for those
  rows, **Keep fixed** and, on a held row, **Let the diagnosis fit it**. The validator's budget warning counts a stage
  with a default candidate as a fit stage.
- **Deviation from the approved wording, and why:** the owner approved the defaults "as plausibility". They are written as
  a fit policy instead. The run takes the same bounds from either, but the plausibility field has no scale and two run
  paths read only a fit policy:
  - the multi-start draws its start values on a log scale only from a fit policy (`campaign_activities._is_log_scale`),
    so a six-decade clearance range would have been sampled linearly, with almost every start above 1 l/µmol/min;
  - the joint refinement SJ refits only parameters with a fit policy (`joint.joint_parameters`), so a candidate fitted
    in S1–S3 within a plausibility range alone would never be refined jointly.

  Plausibility stays what the CPF schema says it is: the range fitting must never exceed.
- **Impact:** a project where nobody freed a fit now lets the diagnosis fit, so its verdicts can change and its fits take
  more of a stage's time. MAPs already signed, and the CPFs staged with them, are unchanged; a plan signed again carries
  the defaults. The reference runs do not go through the plan and are unchanged. No locked file changes.
- **Known gap, for the owner (a locked engine script):** `run_pi.R` drives BOBYQA on each parameter's linear value
  (in its base unit) whatever the recorded scale; only the start values are drawn on a log scale. Over MS-01's six-decade
  clearance range a local search from a distant start can converge slowly or stop at a bound. Fitting log-scaled
  parameters on their logarithm inside `run_pi.R` would fix it; that changes a locked engine script and the qualified
  image, so it waits for the owner's approval in its own PR.
- **PK-Sim evidence:** none yet. T-56 run again on the server after this merges shows the effect on Dapagliflozin.
### Verified on PK-Sim — T-56, Dapagliflozin from a mock proposal to a traced package (2026-10-22; records only)
- **The owner ran the T-56 kit on the server's PK-Sim** after R5 (`deploy/proof/run_t56.py` prepare → accept → the MAP
  signed in the web app → start → trace). Campaign `camp_bc05bdd4096748298bf2048921baae46`, engine `pksim`
  (`Rscript run_job.R`).
- **The acceptance holds** ("a reviewer can trace every number in the MAR to its source", plan §19 T-56). `trace.md`
  resolves:
  - every one of the CPF's 42 parameters to its evidence and the published model (the 16 values held for a check
    accepted by the owner, the rest flowed in, D-27);
  - every one of the 40 judged studies to its dataset and publication (the "client" fed study to its cells);
  - every number in the MAR (17 evidence-index entries).

  The MAR has no report issue, its re-run reproduced, and no link is broken.
- **Time:** the campaign took 9 min of its 60-min budget.
- **Limits, as the kit states:** the inputs are the published model's values, not a literature search, and the "client"
  study is published data in the client template. The campaign's stage verdicts are in its MAR, not in the trace. This
  run is the first PQ evidence for the validation pack.

### Changed — the unwired mapping agent is retired; the reading agent's score on the server's model
- **The score** (`python -m modeler_agents.evals.sheet_reading`, the 11 synthetic layouts of
  `modeler_intake.reading_eval`, the owner's server, `qwen-coder` behind LiteLLM):
  - the reading agent A4 reads 6/11 sheets exactly;
  - code's filling (`suggest`) reads 5/11;
  - the tool keeps code's filling where the agent proposes nothing, so together they read **8/11** (the agent gives no
    reading for `long-subject-time` and `wide-subjects`, which code reads exactly);
  - both miss `minutes-subj-columns` (subject columns in minutes) and `unit-in-note`, and `report-table`'s values.
- **Removed:** `modeler_agents/data_mapping.py` (Anthropic-only, wired to nothing since A4 replaced it in R3c) and its
  test, as the redesign's R3c decided on this score. `recipe_review` names its real callers.
- **Impact:** none at run time: no route or job used it.

### Changed — R5: the old pages are removed; a published OSP model is a source on Inputs
Redesign `docs/plans/2026-10-19-p0-p5-redesign.md` §5 and §8 (R5, the owner's choice 2026-10-20).
- **What moved first, so nothing is lost:**
  - Start's **Proposal notes** edit the brief's lists in place (products, populations, the data plan's lines, scenarios):
    add one, change a field, remove one with the reason.
  - The Inputs step's **Studies** tab gains the client's file upload and the client-data template, **Every dataset**
    (its values, its source; a blinded one revealed with a reason; a digitized figure used once a person confirms the
    overlay; leave one out with a reason or use it again), the digitizer, the observed-data agent and what the client
    sent beyond the checklist. A typed table names its analyte and product in a model system. `?tab=studies` opens the
    tab (the project page's **Add data**).
  - The **Compound** tab lists the papers the literature agent could not read, to store them.
- **A published OSP model of the drug as a source** (the redesign's replacement for Quick start):
  `POST /projects/{id}/evidence:published-model` proposes the model's parameter values citing it (`OSP_LIBRARY`, its
  ValueOrigin as the quote) and its clinical datasets citing their publications (`modeler_project.published_model`, the
  rules the T-56 kit already used, now shared). They flow in like every other source and rank below the client and the
  literature (D-32); nothing is accepted. Only a model of the project's drug is taken (422 otherwise), and taking it
  twice adds nothing. `GET /inputs` lists the drug's published models (`published_models`).
- **Removed:** the Quick start wizard (`/projects/new`) and its links; the brief, Literature, Client data and Add data
  pages (`/brief`, `/evidence`, `/client-data`, `/intake`) with `BriefReview`, `EvidenceReview`, `ObservedData`,
  `DataIntake` and the client-data page component (`components/client/ClientData.tsx` is now `ClientFiles.tsx`: the files,
  the sheet reader and dissolution); the routes only they used: `evidence:approve`, `client-data:approve`,
  `inputs:accept`, `inputs:publish` (and `InputsPage.published`), with `close_register` (both), `accept_inputs` and the
  publication record; the approval-based phases (`GET /phases`, `Workspace.phases`, `PhaseStatus`), replaced by
  `GET /projects/{id}/stale` for the History page; the Stepper's links to the old Inputs pages. The project doctor reports
  the four steps. The template API stays (the reference runs and scripts use it).
- **The T-56 kit** (`deploy/proof/run_t56.py`): `accept` no longer accepts every item or the inputs; it settles what the
  Inputs step leaves to a person (the values held until checked, each pathway's process type, the client study's
  formulation, the healthy adult default) and checks readiness. On the stub engine it reaches the **same CPF** (42
  parameters, the same values and units) and the **same 40 studies** as accepting every item, and its trace counts every
  dataset not left out.
- **Fixed in passing:** the Inputs page's background assembly cleared the message of what the person had just done when
  it finished after it (seen as a missing "files stored" notice).
- **Why:** R0–R4 built the four steps; R5 retires what they replaced (redesign §5), so there is one path through the tool
  and no approval left that gates nothing.
- **Impact:** no science change: the CPF builder, the MAP, the split, the rulesets and the campaign are untouched, and
  the kit's CPF is the same. API contract: the four routes and `/phases` are gone (404), `/stale` and
  `evidence:published-model` are new, `InputsPage` gains `published_models` and loses `published`; the OpenAPI snapshot and
  the web types are regenerated. Projects that approved a register before R5 keep it as a record. Browser flows moved to
  the new screens (`blinding`, `digitize`, `digitize-pdf-figure`, `client-data`, `client-data-guided`, `model-system`,
  `start-project`); `new-project.spec.ts` becomes `campaign-monitor.spec.ts` (the monitor, TEST ONLY, an unrecorded
  campaign) and `published-model.spec.ts` is new.

### Changed — UI/UX pass, PR 4: the frame around every page (web only)
- **What:** a "Skip to the page" link as the first Tab stop (it lands on a zero-size point at the start of the page, so the
  next Tab is the page's first control); the sidebar's links say which page is current (`aria-current`) and the list is
  named "Main"; `app/loading.tsx`, `app/error.tsx` and `app/not-found.tsx` replace Next's defaults. A page that fails to draw
  now says so, with the browser's message and the server-log reference, a "Try again" button and a way back; an address with
  no page says so with the sidebar still there. `e2e/shell.spec.ts` covers the three.
- **Why:** the audit found no way past the sidebar for a keyboard, no marked current page, and a blank or default Next screen
  on a failure or a retired address (the old pages are about to be removed).
- **Impact:** appearance and keyboard behaviour only; no page, testid, text or API call changed. Each page keeps rendering its
  own `<main>` (there is no wrapper landmark, which would nest two).

### Changed — UI/UX pass, PR 3: kit tabs, a banner, and a labelled table scroller (web only)
- **What:** `components/kit/Tabs.tsx` (a tablist that answers the arrow keys, Home and End, has only the selected tab in
  the Tab order, and names each panel by its tab) and `Banner` and a `label` option on `DataTable` in `components/kit`
  (the label is read aloud as a caption, and the scrolling box can be reached and scrolled from the keyboard). The Inputs
  workspace's hand-built tab strip uses them, and the Start checklist's table is labelled; a tab's open-item count is now
  read as "N open". Unchanged for every other page: `.tabs`, `.banner` and `.table-scroll` keep their rules.
- **Why:** the audit found tab buttons with no panel, no arrow-key movement and a count read as a bare number, and
  scrolling tables a keyboard user cannot reach.
- **Impact:** appearance and keyboard behaviour only; testids, texts and API calls unchanged (`tab-<id>` and
  `inputs-notice` kept). Plan, evidence and Review & sign pages are untouched.

### Changed — UI/UX pass, PR 2: one dialog for the signing step-up, an escalation's pop-up and the signature confirmation (web only)
- **What:** a kit `Dialog` (`components/kit/Dialog.tsx`, styles in `kit.css`) replaces three hand-built modals. Each is now
  named by its title, takes focus when it opens and gives it back when it closes, keeps Tab inside, and closes on
  Escape (step-up: cancel; pop-up: "Decide later"; signature confirmation: back to the decision, unless a signature is being
  sent). Dialogs nest: Escape and Tab act on the innermost only. The signature confirmation's inline styles and its own
  overlay colour are gone, and its Cancel button now sits left of "Sign & submit", as in the step-up.
- **Why:** the audit found a signing dialog (21 CFR 11.200) that a keyboard user could tab out of, with no accessible
  name beyond a label, no Escape, and a title styled as a 12 px grey caption.
- **Impact:** appearance and keyboard behaviour only; every testid, text and API call is unchanged. The Review & sign
  drop dialog shares the `.dialog` rules and is untouched. Covered by `escalation-popup.spec.ts` (focus, Tab, nested
  Escape, focus returned, the step-up opened by a stubbed 403 and cancelled with Escape); the Keycloak sign-in itself is
  still `oidc-signing.spec.ts`, which needs a test Keycloak and was not run here.

### Added — UI/UX pass, PR 0: test hooks and a guard for the caveats a restyle must not hide (web only)
- **What:** (1) `data-testid`s beside the class-selected elements the e2e specs lean on: `campaign-status` and
  `campaign-stage-<Sx>` on the campaign page, `start-document` on the Start document viewer; no class, text or layout
  changed. (2) `e2e/protected-text.spec.ts`: Start's "not supported yet" gate and the waiting list must be visible,
  unclipped and not painted in their background colour, in light and dark (to be extended to "provisional (SME)",
  "UNVERIFIED" and "TEST ONLY" as those screens are restyled). (3) The e2e web server's readiness probe moves from
  `/projects/new` to `/`, so the run no longer depends on a page the old-page removal deletes.
- **Why:** the audit found that no spec asserts the caveats (`toContainText` passes on hidden text) and that deleting
  `/projects/new` would make every e2e run wait out its 300 s start-up timeout.
- **Impact:** none on behaviour; no API, locked file or dependency touched. First of the per-page UI/UX series on the
  design foundation (redesign plan §7).

### Changed — UI/UX pass, PR 1: readable text, a visible control edge, a clean step bar (web only, colours only)
- **What:** in `globals.css`, `kit.css`, `start.css` and `inputs.css`:
  - New text-grade tokens `--pass-ink`, `--warn-ink`, `--fail-ink` and `--ink-quiet`. Chips, banners, provenance tags,
    flags, table headers, `h3`, the eyebrow and the step bar's states use them; `--ink-faint` is left for non-text.
    In dark each twin equals its base colour, so dark is unchanged apart from `--ink-quiet`.
  - `--primary` / `--on-primary` for the filled button (white on it 5.2:1, was 4.3:1) and `--control-border` for
    inputs (3.2:1, was 1.2:1). `--sim` stays the chart colour.
  - The step bar's circles no longer pick up `client-data.css`'s amber `.step-n` tint; "needs you" keeps an
    explicit amber one. The theme toggle's focus ring is drawn inside its box instead of being clipped.
- **Why:** the audit measured light-theme text at 2.7–4.5:1 where it carries words (the chip that says "provisional
  (SME)" was 3.6:1), and form-control edges at 1.2–1.4:1 (WCAG 1.4.3, 1.4.11).
- **Test fix, same PR:** `new-project.spec.ts` "the wizard shows the API's own reason" typed `[]` into step 2's "Edit as JSON"
  when CI was slow (it did not wait for step 3), uploaded the real studies and so saw no refusal; it now waits for step 3.
- **Impact:** appearance only; no text, testid, class name, API or dependency changed. Light and dark screenshots
  checked on Start, a project's page and the home page. Still below AA, left to the page that owns the sheet:
  `--ink-faint` text in `plan.css`, `review.css`, `brief.css` and `client-data.css`.

### Added — Review & sign shows the applications: the VBE panel, and what the campaign does with each of the brief's (R4c)
- **What** (`docs/plans/2026-10-19-p0-p5-redesign.md` §3.3, "VBE, its own panel" and "Other applications"; map rows
  `m-vbe`, `p1-apps`, `p1-scen-other`):
  - **The VBE panel.** The `vbe-crossover` template's inputs are set on Review & sign, saved with a reason through
    `PUT plan/structure` (key `applications`):
    - the TEST and reference formulations, chosen from the CPF's;
    - the intra-subject variability: a PK-Sim parameter path, its CV and its source, never defaulted. The path is free
      text; the engine checks it before the trials run, and an unknown path stops the VBE (owner, 2026-10-19);
    - subjects per trial, trials, seed and the probability-of-success threshold, empty until given;
    - the limits: standard 80–125 %, or NTI, marked "[VERIFY], unverified";
    - an optional observed BE study. Without one, the panel says the result will be NOT VALIDATED (F-304).
    - What the validator still says of the application is listed in the panel. "Add the VBE application" is offered
      when the brief names APP-11 or APP-14 and the plan has none.
  - **The brief's applications, each with what the campaign does with it** (`plan.APPLICATION_SUPPORT`):
    - **runs at S6:** APP-14;
    - **the campaign:** APP-01 and APP-11, which the stages themselves answer;
    - **partly supported:** APP-12 (fed studies are judged at S5; the S3 fed fit has no engine path yet);
    - **not supported yet:** the rest (DDI, PGx, special populations, tissue exposure, regimen predictions, …).
    - The brief's prediction scenarios are listed, marked "not simulated yet".
  - **The validator:**
    - **new warning `application-unsupported`** for each partly supported or not-supported application. Acknowledged,
      it becomes a limitation of the MAP, so the signed MAP and the MAR say it (owner, 2026-10-19: a warning, never a
      block);
    - **new error:** a VBE crossover needs at least 2 subjects per trial (the engine refuses fewer);
    - each application problem has its own violation id (they all shared one).
  - **S6's note** no longer promises "the other application templates … are the next phase". It now reads "S6
    characterises the validated model: sensitivity and prediction intervals of the internal studies"; the unrun
    applications are in the MAP's limitations instead.
  - **API:** `GET /projects/{id}/plan/review` gains `applications` (the pinned templates with their input specs, values,
    problems, formulation and limit choices, and the addable ones) and `application_support`. `Structure` gains
    `application_codes`, read from the brief on every rebase. The OpenAPI snapshot and web types are regenerated.
- **Why:** a project whose brief names APP-14 got a VBE application with empty inputs, which blocks signing, and nothing
  on the web could fill them. And the applications the campaign cannot run were said only by a note at S6, after the
  MAP was signed.
- **Impact:**
  - **No science change.** The inputs and their rules are the template's (`vbe-crossover` 0.2.0-draft, SME-locked,
    unchanged); the support statuses state what the code runs. No locked file changes.
  - **A brief that names an application S6 does not run now has a warning to acknowledge before signing.** The T-56
    kit acknowledges its APP-12 warning, so its MAP names that limitation.
  - Tests:
    - `test_plan.py`: the warnings and their limitation, the subject minimum, one id per problem;
    - `test_review.py`: the applications view and the support table with the brief's scenarios;
    - `test_plan_api.py`: the VBE inputs set through the API and shown with what is left;
    - `test_local_runner.py`: S6's note;
    - new browser flow `applications.spec.ts`. The e2e fixture can now enter brief fields before the data plan is
      derived.

### Fixed — the review inbox shows the next escalation of a campaign it just resumed
- **What:** a signed decision in the review inbox resumes its campaign in the background, and the campaign may escalate
  again (an S5 decision is followed by the S4/S5 signature). The inbox read the escalations once, right after the
  decision, so a campaign slower than that read never showed its next decision until the page was reloaded. The inbox
  now reads again every 4 s (`AutoRefresh`, as the campaign monitor does); a decision being typed keeps its state.
- **Why:** the browser flow `feedback.spec.ts` failed on this race three times in CI (#60, #76, #84). It was reproduced
  locally by pausing the resumed campaign 4 s before it continues, and passes with the fix under the same pause.
- **Impact:** web only; no API or science change.

### Changed (science) — the signed MAP binds the fit bounds and the internal target, and the verdicts follow it (R4d, D-35, D-36)
- **What** (locked files `campaign/map.py` and `acceptance.py`, changed with the owner's approval of 2026-10-19):
  - **The MAP's parameter table carries what the run may fit within.** Each parameter now records its fit policy's
    bounds (`MapParameter.bounds`: lower, upper, scale) and the plausibility range the run falls back on
    (`MapParameter.plausibility`), the two sources `fit_spec` takes bounds from. Both are under the signature.
  - **The MAP records the internal target** (`MapAcceptance.internal_target_pe`). `generate_map` refuses one looser
    than the tier: at most (1 − 1/f) × 100 with f the tier's tightest AUC/Cmax fold limit, i.e. 33.3 % at medium,
    20 % at high and 50 % at low (`acceptance.loosest_internal_target`, now the plan's validator's rule as well).
  - **The verdicts apply it** (MS-01 §8: "Stricter MAP criteria (e.g. |PE| ≤ 10 %) are allowed for internal groups;
    they must never be looser than the tier").
    - An internal (`fitting`) AUC or Cmax passes only within the tier's limit **and** |PE| ≤ t %. The limit reads,
      e.g., "0.67-1.5-fold and |PE| ≤ 20 %".
    - Validation (external, S5) comparisons and DDI ratios are judged by the tier alone. The group fractions are
      unchanged.
  - **D-35: a campaign is judged by the criteria its MAP was signed with** (`MapAcceptance.as_ruleset`), no longer by
    the ruleset file at run time. A ruleset change applies from the next MAP version.
  - **D-36: a campaign runs on the parameters its MAP signed.** The start compares the CPF with the MAP's parameter
    table (`map.cpf_differences`: a parameter on one side only, or a different value, unit, status, fit stages,
    bounds or plausibility). Pilot and production refuse a departing or unreadable CPF with 409, naming the
    differences (`run_guard.require_cpf_matches_map`). A development run starts and says so in its S0 notes.
  - **The plan follows:** `map_from_plan` passes the plan's target into the MAP. The limitation "the verdicts do not
    apply it yet" is gone: the target is a criterion now.
  - **The reports show it:** the review page says the target is applied; the MAR's conclusion and its M15 table
    (technical criteria) name it; the campaign monitor shows it (`CampaignRecord.internalTargetPe`).
- **Correction to R4b's record:** R4b said "the signed MAP does not carry the fit bounds". They were in fact under the
  signature, but only as text: every fit is a plan change written into `split_rationale` ("fitted in S1 [lo, hi]
  scale"). What was missing was a structured record of them and any check that the run's CPF matches the MAP. R4d
  adds both.
- **Why:** the owner's decision of 2026-10-19: the Part 11 signature must cover the bounds the run fits within, and a
  stricter target the person sets must change the verdicts, not only be stated.
- **Impact:**
  - **Signatures already given stay valid.** Each new field is left out of the content hash while unset, as empty
    `applications` already were. Two MAPs signed by the code on `main` before this change (with and without a fit,
    `packages/pbpk-domain/tests/fixtures/`) read back with their signed hash. A MAP signed before R4d is compared, at
    the start, on what it recorded: its fits' bounds are not checked (they are in its rationale text only).
  - **Verdicts:** unchanged without a target, and unchanged with the criteria recorded today (both 2026.2-draft).
    With a target, internal studies are judged more strictly. Still UNVERIFIED, like the ruleset; the application to
    AUC and Cmax of internal groups only is listed for the SME (`docs/SME_SIGNOFF.md`).
  - **A new MAP hash** for any MAP that records bounds, plausibility or a target. The reference runs' refit MAPs are
    unsigned development MAPs.
  - **Verified on PK-Sim** (`dapagliflozin-refit`, Actions run 39286267822, engine 12.4.4, on this branch): identical to
    the recorded refit. S0 passes with no departure note. S1 escalates after the clearance fit, with UGT1A9 clspec at
    its lower bound (0.0399). The GMFE is 2.478 / 2.516 at baseline and 1.412 / 2.291 after the fit.
  - **API contract:** `MapParameter`, `MapAcceptance` and `CampaignRecord` gain fields; the OpenAPI snapshot and web
    types are regenerated.
  - **Locked files:** `campaign/map.py` and `acceptance.py`, hashes refreshed in `docs/architecture/locked-files.json`.
  - Tests:
    - `test_map.py`: the signed-on-main fixtures, bounds and plausibility under the hash, the target's range, the
      recorded criteria judging as the ruleset;
    - `test_acceptance.py`: the target on internal AUC/Cmax only;
    - `test_evaluate_round_activity.py`: the MAP's target and its signed criteria judge the round;
    - `test_run_integrity.py`: a pilot refuses a CPF with other bounds, or none to read;
    - `test_local_runner.py`: S0 notes a development departure;
    - `test_plan*.py`: the MAP carries the target, and the staged CPF matches the signed MAP;
    - `review-sign.spec.ts`: the target is shown as applied.

### Fixed — a figure picked from a PDF's figure list keeps its crop (R3d)
- **What:** the digitizer draws each view (document, page, zoom, crop) asynchronously, and an older drawing still in
  flight could land last. Opening the digitizer starts drawing the whole page; picking a figure at once starts the
  cropped drawing; when the whole page finished second, it was drawn over the figure, and the canvas showed the whole
  page while the crop stayed set. Now only the latest drawing reaches the canvas (`Digitizer.tsx`).
- **Why:** CI's browser flow `digitize-pdf-figure.spec.ts` failed on PR #82 (the canvas stayed 1200 × 1600 instead
  of the figure's 800 × 600). It was reproduced locally by holding the whole-page drawing until the crop was drawn,
  and passes with the fix under the same hold.
- **Impact:** web only; no API or science change. The digitized values were never affected: the axes and the points
  are picked in the frame shown, and calibration maps them within it. What could be wrong is the recorded crop, which
  then named the figure while the person had worked on the whole page.

### Changed (science) — Review & sign gains the estimation plan, the validation plan and the tier's acceptance criteria; fit bounds are proposed from MS-01 §2.2 (R4b, D-34)
- **What** (`docs/plans/2026-10-19-p0-p5-redesign.md` §3.3; D-34, owner decision 2026-10-19):
  - **The estimation plan** (map rows `p5-fit`, `m-bounds`): one table of every numeric parameter, fixed or estimated,
    with its start value and source (citation and grade from the review table), the MS-01 stages it is a fit candidate
    at, the fit's stages, bounds, scale and reason, and the bounds proposed for it. **Estimate** opens a form filled
    from the proposal; the reason stays required, because a fit is the person's choice. **Fix it** removes a fit.
    Filters: estimated, MS-01 candidates, flagged.
  - **The bounds proposal follows MS-01 §2.2's "Default bounds"** (`modeler_project/fit_bounds.yaml`, a data rule,
    **version 0.1, UNVERIFIED** for the SME; `modeler_project.estimation`). Each row copies MS-01's cell word for word,
    and a test parses MS-01 §2.2 and fails if the two drift or a row with bounds is missing:
    - relative bounds around the start value (fu predicted [0.5×, 2×], solubility [1×, 100×], Km and transporters
      [0.1×, 10×], Weibull and particle d50 [0.5×, 2×]); the start value ± 1.5 for a measured logP; absolute bounds
      as written (perm, CLspec, total CL, GFR fraction, TS CLspec, biliary CL, EHC fraction, fed solubility factor,
      a predicted logP), **used only when the parameter is stored in MS-01's unit**. Otherwise, and where MS-01
      gives none, 0.1–10× the start value (the redesign's rule, §6 item 2), with a note;
    - each proposal is kept within the registry's physical bounds when the parameter is stored in the registry's
      unit; none is proposed (with the reason) when the bounds would have no width or a log scale needs a positive
      start value;
    - **MS-01 keeps a measured fu fixed:** nothing is proposed for it.
  - **The validator checks a fit's bounds** (`plan.validate`):
    - error `fit`: a lower bound not below the upper (`PUT plan/fits/{id}` refuses it with 422);
    - error `fit-plausible`: a bound beyond the physical bounds (MS-01 §2.2: "the MAP may narrow them, never widen
      them beyond plausibility");
    - warning `fit-default`: bounds wider than MS-01's default. Acknowledged, it becomes a limitation of the MAP, as
      every acknowledged warning does;
    - warning `fit-fixed`: estimating a parameter MS-01 keeps fixed (a measured fu).
  - **The validation plan:** what S4 (internal) and S5 (external) judge under the MAP the plan generates, their studies
    (from `stage_coverage`, a blinded one marked) or why a stage has none, and what follows a failure: S4 escalates
    and is never refitted (MS-01 §4); at S5 the person chooses an MS-01 §6.6 path, signed as a deviation.
  - **The tier's acceptance criteria**, under Credibility: the limits of the chosen tier from the ruleset the MAP
    records (`pbpk_acceptance_criteria.yaml` 2026.2-draft, UNVERIFIED; medium: AUC and Cmax within 1.5-fold, DDI ratios
    Guest δ 2, 80 % of comparisons within), and an optional **internal target** |prediction error| ≤ t %
    (`Structure.internal_target_pe`, seeded from the brief's `acceptance.internal_target_pe`, set on the page with a
    reason through `PUT plan/structure`).
    - **Stricter than the tier only** (MS-01 §8): error `target` when t > (1 − 1/f) × 100, with f the tier's smallest
      fold limit, which keeps the ratio band inside [1/f, f] (medium 33.3 %, high 20 %, low 50 %).
    - **Stated, not yet applied:** a set target adds "Internal target |prediction error| ≤ t % (MS-01 §8): stated in
      the plan; the verdicts do not apply it yet" to the MAP's limitations. Applying it changes the locked
      `acceptance.py` and is R4d's.
  - **API:** `GET /projects/{id}/plan/review` gains `estimation`, `bounds_rule`, `validation` and `acceptance`; the
    structure key `internal_target_pe`. `docs/api/openapi.json` and the web types are regenerated.
- **Why:** the approved Review & sign screen (R1, redesign §3.3) lists the estimation plan with proposed bounds, the
  validation plan and the tier's criteria among what the signer sees. The owner chose MS-01's own default bounds over
  the generic 0.1–10× rule (2026-10-19), because they are the SME's text.
- **Impact:**
  - **Science:** a fit's bounds are now checked against MS-01's defaults and the physical bounds; the proposal only
    fills a form, so no plan changes unless a person saves it. Existing fits outside MS-01's defaults now show a
    `fit-default` warning to acknowledge before signing; one beyond the physical bounds blocks signing. The values
    are MS-01's, UNVERIFIED until the SME signs (`docs/SME_SIGNOFF.md`).
  - **The start value may now sit on a bound** (`lower ≤ start ≤ upper`, was strict): MS-01's own solubility default,
    [1×, 100×] the measured value, puts the start on the lower bound, which the strict check refused.
  - **Fixed in passing:**
    - a saved fit with inverted bounds made `GET /plan/review` fail (500) and was not refused when saved;
    - changing the time budget on Review & sign failed with 500: a number in the plan's diff did not fit the
      response's text field (R4a's budget control). The diff now shows numbers as text.
  - Tests: `test_estimation.py` (the rule word for word against MS-01, each kind of default, units, physical bounds,
    the findings); `test_plan.py` (the four bounds rules, the target rule and its limitation); `test_plan_api.py`
    (the review's new parts against `stage_coverage` and the ruleset, a 422 on inverted bounds, the budget change);
    `review-sign.spec.ts` gains a browser flow (estimate logP with the proposed bounds, the validation plan, the
    criteria, a target refused at 40 % and stated at 20 %).
- **Known gaps:**
  - **The signed MAP does not carry the fit bounds:** `MapParameter` has none, and the bounds travel in the campaign
    CPF beside the MAP. Putting them under the signature changes the locked `map.py`: one locked-file PR after R4b
    (owner-approved in principle, 2026-10-19), with R4d.
  - **The verdicts read the ruleset at run time** (`evaluate(comparisons, model_risk)`), not the criteria the MAP
    records. Noted for that same PR.
  - **The campaign fits only what the plan frees:** a candidate with neither a fit nor a plausibility range is not
    fitted. MS-01's defaults could become the candidates' plausibility; that is a science change, for the owner.

### Added — the reading agent proposes how to read each client sheet, checked by code; an evaluation set scores it (R3c)
- **What** (`docs/plans/2026-10-19-p0-p5-redesign.md` §3.2 and §4):
  - **The reading agent** (A4's second job, `modeler_agents.sheet_reader`) starts from code's first filling of the
    reading form (`sheet_form.suggest`, kept as the starting point and the fallback) and proposes the reading with
    `propose_reading`. It can see more rows with `read_rows`.
  - **Code checks every proposal before it is kept:**
    - the form is valid;
    - each quote is in the cell it cites and states the value it is cited for;
    - the units, LLOQ, dose, n and strength each stand on a quote. Only a unit may be declared unstated (the person
      is told); an LLOQ, a dose, an n or a strength is never guessed;
    - the reading applies to the sheet without a problem (`to_proposal`, `review_proposal`), exactly as a confirmed
      reading would.

    The agent hears what code read, or what to fix, and proposes again.
  - **Nothing is read into the project by the agent.** An accepted reading is kept on the client file
    (`client_data.record_reading`). The sheet then opens on it, marked as the agent's, and the person checks,
    corrects and saves it once (`:map`), as before.
  - **API:**
    - `POST /projects/{id}/client-data/{sid}:read` runs the agent in the background over the file's data sheets not
      yet read, or the sheets named. It is one agent run per sheet (`A4-sheet-reading`), each in the run log.
    - `GET …/sheets/{sheet}` answers the agent's form when there is one, with `proposed_by` and `run_id`.
    - The page view gains `reading`.
  - **Web:**
    - the client's sheets are listed and read on the Inputs **Studies** tab (`ClientFiles`, shared with the Client
      data page);
    - **Read the data sheets (agent)** on each workbook, and **reading proposed** on a sheet waiting for the person;
    - the reader says who filled the form in.
  - **Evaluation set** (`modeler_intake.reading_eval`, T-21): 11 client sheets in the layouts real files use. They
    cover times down and across, long and wide subjects, Mean / SD rows, BLQ and no-sample tokens, units in titles and
    notes, a report table with a source line, geometric means with a CV column, decimal commas, and twelve dissolution
    vessels.
    - Each sheet is written from its known answer, so the answer is known by construction; software test data, never
      observed data.
    - A reader is scored on reading without a problem, the values at their times, the units, the statistic, the LLOQ
      and the dose.
    - The person's reading kept with each case scores 11/11, which checks the cases and the scorer agree.
    - `uv run python -m modeler_agents.evals.sheet_reading [--reader agent]` prints the table.
  - **One lock helper:** `Workspace.editing(kind, id)`. The client file's writers (triage, readings, confirmed
    mappings) take it, so the agent's run and a person's save on the same file never drop each other's change. The
    brief's lock from the lost-update fix moves onto it.
  - Saving a sheet no longer says to accept the datasets on the Literature page; under D-27 they flow into the inputs.
- **Why:** the owner found reading client sheets the hardest part of P0–P5: about 30 fields per sheet, filled by a
  regex guess. The reading agent fills them, and code keeps it honest. The evaluation set makes "better" measurable
  before and after each change, for code and agent alike.
- **Code's baseline** (`suggest`, unchanged): 5 of 11 sheets read exactly.
  - Two more read without a problem but with the wrong values: a decimal-comma export read its N column as
    concentrations, and a report table's "SD (ng/mL)" column was dropped. A person must catch these today.
  - Four fail to read: a no-sample token, an n stated only in a note, "Subj 1" headers taken as a subject column, and
    numeric time headers taken as data.
  - `test_code_alone_reads_these_sheets_today` pins this list, so a change to `suggest` shows here.
- **The agent's score is not taken here:** the build container reaches no model. It is to be run on the server's model,
  where the owner's real files are scored too (never committed). Whether the unwired mapping agent (`data_mapping.py`)
  is rewired or retired follows that score.
- **Impact:** no science change. The reading rules, the checks a confirmed reading passes, and what reaches the
  project are unchanged; the agent only fills the form a person still checks and saves. Agents stay off unless a
  provider is configured (D-16), and with them off the page works as before.

### Added — the digitizer reads figures inside a PDF: a figure list, crop and zoom (R3d)
- **What** (`docs/plans/2026-10-19-p0-p5-redesign.md` §3.2; the owner's note: the digitizer must also read "figures
  that are images inside a PDF", with zoom and crop):
  - **`GET /projects/{id}/documents/{sha256}/figures`** lists the images placed on each page of a PDF, with where each
    sits, as fractions of the page as shown (`modeler_intake.documents.pdf_figures`). The page's own rotation is
    applied.
    - The positions come from the pages' drawing instructions: the transformation matrix through q/Q/cm and nested
      forms. Nothing is decoded.
    - Images smaller than 8 % of the page (logos) are left out; a file that is not a PDF lists none.
  - **The digitizer** (`Digitizer.tsx`):
    - a **figure list** for a PDF: picking a figure crops the page to it;
    - **Crop to a region** (two corners) for a figure drawn as lines;
    - **zoom** 1–4×, in a box that scrolls.
    - The page is drawn off screen and only the crop is shown. Changing the document, page, crop or zoom starts the
      calibration again, because the pixels' frame changed.
  - **The dataset keeps the frame:** `Digitization.crop` (fractions of the page) and `scale` (the render scale). They
    are optional, so earlier datasets load unchanged. The card says "cropped to the figure".
- **Why:** published PK figures are usually images inside a paper's PDF. Before, the digitizer showed the whole page
  at one scale, too small to pick points well.
- **Impact:**
  - **No science change:** the calibration maths (`pbpk_domain.digitize`) is unchanged, and a cropped, zoomed view
    gives the same values as the whole page (test).
  - **No new dependency:** decoding the images would need Pillow, which only rdkit pulls in.
  - API contract: the figures route, plus `crop` and `scale` on `DigitizeBody` and `Digitization`. The OpenAPI
    snapshot and the web types are regenerated.
  - Tests:
    - `test_pdf_figures.py`: a placed image, an image inside a form with its matrix, a rotated page, a logo left out;
    - a cropped-frame test in `test_datasets.py`;
    - the browser flow `digitize-pdf-figure.spec.ts`, on a PDF written by the test: picked from the list, cropped to
      exactly the figure's 800 × 600 pixels, digitized within the resolution of the truth, the crop kept.
- **Order:** R3d came before R3c. The reading agent needs a live model to score its evaluation set, and the model runs
  on the server.

### Fixed — two quick edits of the brief both land (Start's pickers no longer drop a choice)
- **What:** everything that changes the brief now reads, changes and commits it under one per-project lock
  (`brief_api._brief_edits`: a file lock beside the project's artifacts, held across threads and workers). That covers
  the routes (`PUT /brief`, `brief/items:remove`, `brief/questions/{id}`) and A1's merge of its reading into the
  latest brief, which runs while the person picks on the Start screen.
- **Why:** each edit read the latest brief, changed it and committed the next version. The Start screen saves every
  pick at once, so two picks a moment apart both read one version, and the later commit, built on it, overwrote the
  other's change. Both requests answered 200, and the choice was silently lost.
  - Found as an intermittent browser-test failure, "PBPK model: not set yet" after picking it
    (`start-step.spec.ts`).
  - Reproduced by `test_two_quick_edits_of_the_brief_both_land` and
    `test_an_edit_made_while_the_agent_merges_its_reading_is_kept`; both fail without the lock.
- **Impact:** no data or contract change. A second edit waits until the first has committed, then builds on it.
- **Known gap:** other read-modify-write routes have the same pattern (the evidence register, datasets, the plan).
  Their edits are rarer and come one at a time from their pages. Not changed here; each is checked in its own change.

### Added — Review & sign, the third step: one review table and the model's credibility around the MS-01 canvas (R4a)
- **What** (`docs/plans/2026-10-19-p0-p5-redesign.md` §3.3; D-27: "a person reviews everything once, at the MAP
  signature"):
  - **`/projects/{id}/plan` is now Step 3 · Review & sign**, on the kit, full width so the 960-px stage graph keeps its
    place beside Overall Data:
    - **the signature on top:** Approve and Sign, the MAP version, deviations to sign (D-14), and running the campaign;
    - **Studies and roles:** the MS-01 canvas as before (Overall Data, the D3 stage graph dragged with a reason, D1
      and D2), then each study's role, whether it is blinded (D-15), its demographics, and **Leave out** / **Include
      again** with a reason;
    - **The inputs, the review table** (map row `m-exclude`): every model input with its value, the source the CPF
      keeps and its quote, grade and flags, who or what supplied it (an agent, the client's file read by code, a
      person, the system), how many other sources agree, and a confidence.
      - The confidence is **display only**: it sums up the grade, the flags and the agreement, and decides nothing
        (D-32 picks the value).
      - Filters: flagged, changed by a person, from an agent, waiting on you.
      - **Exclude** sets the kept source aside with a reason; the next source takes its place and the plan asks to be
        brought up to date. Excluding an input's only source says so first.
    - **Credibility (ICH M15):** the model risk (the R0 control, beside Start's ratings and justification); the time
      budget split stage by stage **as the MAP signs it** (MS-01's fixed shares, D-31); and the limitations the MAP
      names;
    - the live validator and the changes from the MS-01 default, as before.
  - **`GET /projects/{id}/plan/review`** (`modeler_project.review`, typed `ReviewPage`): the rows, the filter counts, the
    studies, the risk, the stage budgets and the limitations. It is read only: an input or a study is excluded through
    the Inputs routes (`evidence/{id}:decide`, `inputs/choices`).
  - **The evidence view says who supplied and who decided each value** (`proposed_by`, `decided_by`, `extraction`).
- **Changed (MAP):** **the assumptions the brief states are limitations of the MAP** (map row `p1-assump`): each becomes
  "Assumption stated in the brief: …" in `split_limitations`, after the MS-01 split's own and before the acknowledged
  warnings (`plan.map_limitations`). The plan's structure carries them (`Structure.assumptions`), read again from the
  brief on every rebase. A brief with no assumptions gives the same MAP as before.
- **Why:** the approved Review & sign screen (R1). It is where D-27's one review happens, so it shows every value with
  its source.
- **Impact:**
  - **No science change** beyond the limitations above: the page shows what the plan and the inputs already hold, and
    the split and limitations are the MAP's own (checked against `map_from_plan` in the API test).
  - API contract: the review route and its models; `EvidenceView` gains three fields; `Structure.assumptions`.
    `docs/api/openapi.json` and the web types are regenerated.
  - **Fixed in passing:** the OpenAPI enum of a low / medium / high field could come out as high / medium / low,
    depending on which module was imported first: `typing` caches `Literal[...] | None` as equal whatever the order.
    Every such field now uses one order.
  - Tests: `test_review.py` (who supplied a value, the confidence, the filter counts, the MAP's limitations with the
    brief's assumptions); `test_plan_api.py` (the review route against the MAP the plan generates). New browser flow
    `review-sign.spec.ts` (the table, a filter, an exclusion with the agreeing source taking over, the stage split and
    the limitations); `model-plan.spec.ts` keeps its test ids.
- **Known gap:**
  - **Not yet on the page** (R4b–R4d): the estimation plan as one table with proposed bounds, the validation plan, the
    tier's acceptance criteria with a stricter project target, the VBE panel and the other applications, and verdicts
    applying the stricter target (a locked-file change for the owner's approval).
  - The browser flows cannot run in this session's sandbox (no port, no browser); the owner's local run passed 21 of
    21 (Chrome, 2026-10-19), with `review-sign.spec.ts` and `model-plan.spec.ts` among them.

### Added — Inputs, the second step of the new flow: one workspace, five tabs, "Still missing to run" (R3b)
- **What** (`docs/plans/2026-10-19-p0-p5-redesign.md` §3.2; it builds on R3a):
  - **`/projects/{id}/inputs` is rebuilt as one workspace** on the kit (`InputsWorkspace`), in PK-Sim's building blocks:
    Compound, Formulations, Individuals, Simulation settings and Studies.
    - The side list **Still missing to run** shows the live to-do list; each item opens its tab and scrolls to where it
      is settled. Readiness is shown beside it.
    - The page assembles the inputs once when they are missing or stale (an upstream change such as the brief).
      Every change made on it reassembles them on the server.
    - **No Accept, Approve or "Hand to the model plan" button** (D-27): when nothing is missing, the panel links to
      Review & sign. The API routes stay for the T-56 kit until R5.
  - **Compound** (and the value rows of the other tabs):
    - one row per model input: the kept value in its PK-Sim unit, the kept source with its grade, "+N agree" for
      sources within 10 %, and the state (in the model, keep one, check it, missing);
    - the sources and alternatives open under the row; a source can be excluded with a reason;
    - what waits on a person is settled in the row: keep one, check a held value, correct, pKa, the process;
    - **Add a value** types a value into the row with its unit, source and quote, filed under the row's checklist
      item (`req_id`).
  - **Formulations:** the formulation of each solid study, and the dissolution profiles with their Weibull fit and f2
    (the Client data page's card, reused).
  - **Individuals:** each study's individual, entered or **Use the healthy adult default** (D-29), and the values set
    on the individual.
    - The population is chosen from the six harvested PK-Sim human databases. Pregnant and Preterm are left out
      because they need gestational inputs a study does not carry.
    - `:study` now refuses a population that is not one of them.
  - **Simulation settings:** the calculation methods (`dist.partition_method`, `dist.permeability_method`), the values
    set on the simulation, and each study's solver settings.
  - **Studies:**
    - each study with its facts, the role the MS-01 split proposes (read-only, D-33), blinded, demographics, the
      multiple-dose regimen editor, and **Leave out** / **Include again** with a reason;
    - **Add observed data:** the client's sheets (the reader until R3c), the client-data template, the digitizer, or
      a table typed in by hand (`POST /datasets`).
  - **API, `GET /projects/{id}/inputs`** (`modeler_project.inputs_view`, typed in `views/inputs.py`):
    - `compound` rows (`CompoundRow`, with `EvidenceView` sources and `AlternativeView` alternatives);
    - `studies` rows (`InputStudyRow`);
    - `study_options`: the study record's enums and the harvested populations;
    - `selection_rule`;
    - every to-do item names its `tab` (`inputs.tab_of`);
    - the records' `block` is the tab id.
- **Why:** the approved Inputs screen (R1). It is the typed view R3a deferred, and the one place where values from
  every source meet.
- **Impact:**
  - **No science change:** the page shows what R3a assembles.
  - The old `ModelInputs` page is gone. The Literature and Client data pages stay reachable from the step bar until
    R5.
  - API contract: the `InputsPage` fields above. `docs/api/openapi.json` and the web types are regenerated.
  - Tests: `test_inputs_view.py` (rows, tabs, studies, the population guard, the harvested list).
  - Browser flows:
    - new `inputs-workspace.spec.ts`;
    - `model-inputs.spec.ts` now reaches ready inputs and Review & sign with no acceptance;
    - `inputs-todo.spec.ts` opens items from the side list;
    - a light and a dark screenshot.
- **Found while building it, and fixed in R3a (#76):** a value proposed after an assembly reached the CPF only on the
  next manual assembly (`inputs_key`).

### Changed (science) — values flow into the model inputs without a per-item decision; one rule picks the value a parameter takes (R3a, D-32, D-33)
- **What** (`docs/plans/2026-10-19-p0-p5-redesign.md` §3.2 and §4; D-27: "agents and code fill; a person reviews
  everything once at the MAP signature"):
  - **Every value counts unless a person excluded it** (REJECTED, always with a reason). The CPF assembly, the study
    catalog and the to-do list read every evidence item and dataset that is not excluded (`sources.included`), not
    only ACCEPTED ones. A digitized dataset still needs its overlay approved. ACCEPTED stays a valid state, so
    `:decide` and the T-56 kit keep working. Coverage, blocking and the P2/P3/P4 approvals are unchanged until R4/R5.
  - **Source selection, D-32** (`modeler_project/sources.py`, `source_selection.yaml` **version 0.1, UNVERIFIED** until
    the SME signs, T-30; the owner's decisions of 2026-10-18). Per CPF id, after conversion to the PK-Sim unit:
    - values within **10 %** of the kept value agree: one value, every source listed in its provenance ("agreed by N
      other source(s)") and in the assembly report;
    - values within **2-fold**: the **best source wins** (client report, client file, regulatory review, publication,
      database, OSP library, proposal, predicted, assumption; within a source the higher grade A–D, then the value more
      sources agree with, then the earlier). The others are listed as alternatives "differs by N %" for the review;
    - values **beyond 2-fold** conflict: the parameter stays out of the CPF until a person keeps one (`:choose`);
    - **never averaged:** the kept number is always one source's own. A value a person accepted outranks values only
      proposed; two accepted values in conflict still wait on a person. Words agree only when equal.
  - **Held values:** a value carrying `needs_conversion`, `outside_physical_range`, `species_mismatch`, `check:`,
    `statement:` or `refiled:` enters only once a person accepts or corrects it. These are non-blocking "review" items
    on the to-do list. `refiled:` is new: `:correct` adds it when the correction moves a value to another parameter.
  - **Two acid (or two base) pKa values from different sources** wait on a person as a "pka" item, instead of becoming
    two ionisable groups.
  - **A2 misfiling rules in code** (`evidence.file_check`, called by `evidence_agent.propose_value`, which refuses with
    "MISFILED" and the reason; the cases found on the owner's real project, 2026-10-06):
    - a quote stating protein binding with a "%" unit on `bind.fu` is stored as "% bound" (code computes fu = 1 − bound);
      any other unit is refused;
    - a fraction excreted unchanged in urine is refused as `elim.renal.gfr_fraction` and pointed to `elim.fe_urine`;
    - a sentence is refused as the value of a numeric parameter;
    - the target check is `target_problem`, not a prefix match.
  - **Study facts:**
    - **demographics are never silent (D-29):** `ObservedDataset.demographics_choice` ("entered" or
      "healthy_adult_default"). Readiness adds "demographics stated (D-29)", and the to-do list shows one
      "demographics" item per study with neither demographics, nor a published individual, nor the default chosen.
      A chosen default becomes a plan limitation that reaches the MAP: "simulated with the healthy adult default
      (European_ICRP_2002, male, 30 years), chosen by a person (D-29)";
    - **a multiple-dose study needs its regimen:** readiness adds "multiple-dose regimens", with a "regimen" to-do per
      study missing its number of doses or interval. Before, such a study was run as a single dose;
    - new `POST /projects/{id}/datasets/{dataset_id}:study` sets a study's facts and the demographics choice, and
      re-checks the dataset.
  - **Roles before the plan, and blinding by them (D-33):** `roles.proposed_roles` gives each study the role the MS-01
    split proposes (S1–S3, S5, S6 or supportive) as soon as the inputs are assembled, and the plan's placements once a
    plan exists. Blinding (D-15) hides a study proposed for S5 or S6 from that moment, not only after the plan.
  - **The inputs assemble themselves** (`inputs.refresh_inputs`): every route that changes evidence, datasets, client
    data or choices re-assembles the inputs when they are missing or have changed. "Changed" is staleness, or a new
    `inputs_key` (`inputs.inputs_key`): the readiness records a key over what the assembly read (the brief, the
    checklist, the choices, every evidence item and dataset at its version). A new value is a new artifact, which makes
    nothing stale, so without the key it reached the CPF only on the next manual assembly. The plan needs **ready and
    current** inputs (`inputs.inputs_ready`; 409 with the reason), no longer the P4 approval.
  - **The Model inputs page keeps up until R3b replaces it:** its to-do list shows the new items (a held value with
    Accept / Reject, "Use the healthy adult default", a multiple-dose study's doses and interval; each study item names
    its `dataset_id`), and its text no longer says values come only from accepted evidence.
- **Fixed** (science):
  - **`inputs:publish` dropped study facts:** `dose_phases`, `meals`, `inactive_processes`,
    `default_simulation_values`, `solver`, `water_ml_per_kg`, `demographics`, `published_individual`, `analyte` and
    `product` never reached a campaign. They do now.
  - **A client mg/kg dose was read as mg:** the client mapping now sets `dose_per_kg` when the dose unit is mg/kg.
- **Why:** the owner's map (2026-10-17) dropped per-item Accept/Reject, and asked that agreeing sources become one
  value with all of them as sources (the "Conflicts (P4)" note). A2 misfiled values on the real project, and the model
  needed MD regimens and demographics that no screen captured.
- **Impact:**
  - Fewer decisions: agreeing values no longer conflict (0.70 vs 0.73 is one value with two sources), and a proposed
    value reaches the CPF without being accepted. What a person must still decide is on the to-do list: conflicts,
    held values, pKa kinds, demographics and regimens.
  - The T-56 kit chooses the healthy adult default, in the owner's name, for each study the proposal gives no
    demographics for.
  - **No PK-Sim run is needed for this change:** the reference runs (`deploy/reference/run_reference.py`) start their
    campaigns from the OSP snapshot through `POST /projects` and `campaign:prepare`. They never pass through the CPF
    assembly or `inputs:publish`, so the published templates' results cannot move.
  - API contract: `DatasetBody.demographics_choice`, the `:study` route, and `ObservedDataset.demographics_choice`.
    `docs/api/openapi.json` and the web types are regenerated.
  - Tests: `test_sources.py`, `test_roles.py` and the misfiling test are new; the inputs, to-do, doctor, inputs-API and
    plan-API tests and the D-29 browser fixture are updated. `inputs-todo.spec.ts` now settles a 2-fold conflict
    (0.70 vs 0.30), shows two agreeing logP values taken without a decision, and checks the held refiled value.
- **Deviation from the plan:** the typed `GET /projects/{id}/inputs` view (compound and study rows, the missing list)
  moves to R3b, where the Inputs page that reads it is built.
- **Known gap:** D-32's thresholds and order, and the D-29 default, are listed for the SME (`docs/SME_SIGNOFF.md` §2).
  Values are compared within one PK-Sim unit, so a value with no conversion is held.

### Changed — Start, completed: one upload with the client's files, no approval left, pathway kinds, the viewer on the proposal (R2b follow-up)
- **What** (`docs/plans/2026-10-19-p0-p5-redesign.md` §3.1 and §5; what #73 left for later, or missed):
  - **One upload for the proposal and the client's files** (map rows `p0-files`, `p3-upload`):
    - `POST /projects:initiate` takes `client_files` and reads each one into Inputs, as an upload there would (a filled
      template at once, any other workbook triaged). A file that cannot be read is answered with the reason
      (`ProjectStarted.client_files`), and the project still starts.
    - On `/projects/start`, each file says what it is, guessed from its type and changeable: proposal or annex, or
      client data. Before, a workbook given at the start was stored as a page of the proposal.
  - **No approval is left at Start** (D-27; §5 schedules these for R2, #73 had kept them for the T-56 kit until R5):
    - `POST /projects/{id}/brief:approve` and `POST /projects/{id}/requirements:approve` are removed, with
      `RequirementsPage.brief_status`.
    - The full brief page loses its approve button and its Data plan and Feasibility tabs (`DataPlan.tsx` is removed):
      Start's checklist shows both. The page stays as #73 intends, to edit the products, populations and data-plan
      statements until Inputs and Review & sign take them over (R3, R4), and it no longer asks "why" for an edit.
    - **The checklist's provider and literature cross-check are changed in place on Start** (map rows `p1-provider`,
      `p1-crosscheck`), so nothing the Data plan tab did is lost. A person's choice is kept across re-derivations, as
      before.
    - The project title and type, the products and the data-plan statements are no longer `required`: they are
      proposal notes, and the full brief's "what it still lacks" lists only what Start needs.
    - The client-data page's first step reads the checklist as current or behind the brief, not as approved.
  - **The kinds of pathway, picked at Start** (new `scope.pathways`: hepatic, gut-wall, renal filtration, renal
    secretion, biliary, transporter). They decide the checklist's `pathway` items. Before, only the words of
    `scope.pathways_stated` did, so a brief naming only its enzymes ("UGT1A9") dropped the renal-clearance item even
    for a drug cleared renally.
  - **Start's document viewer opens on the proposal.** Documents are stored by content hash, so a client file or the
    PubChem record could be listed first and the viewer opened on it.
  - **A1 is no longer shown the person-only fields** (the ICH M15 ratings, the risk and its justification), which it
    was refused on anyway.
  - **The T-56 kit** no longer approves anything: it fills the ratings and the scope gates, and checks that Start is
    done.
- **Why:** the plan's R2 scope (§3.1 one upload, §5 the R2 removals) and two defects found while merging the two R2b
  implementations (#73 kept; #74, which duplicated it, replaced by this change).
- **Impact:**
  - **Science: nothing changes in the model.** The data checklist differs only where `scope.pathways` is set; the
    T-56 kit's checklist is identical with and without its new brief fields (checked).
  - **API contract:** two routes removed; `client_files` on `POST /projects:initiate`; `ClientFileStarted`;
    `RequirementsPage.brief_status` removed. `docs/api/openapi.json` and the web types are regenerated.
  - **Tests:** `test_brief_api.py` (the data plan with no approval and a kept override; one upload with a refused
    file), `test_requirements.py` (pathway kinds), `test_brief.py` (proposal notes not required); the T-56 kit test;
    `start-project.spec.ts` rewritten (one upload, the viewer on the proposal despite a client CSV listed first, the
    provider changed in place, the full brief with no approval). Here: 1364 passed, 23 skipped; 14 failed only because
    this sandbox cannot download Temporal's test server (`test_campaign_workflows.py`, untouched). Ruff, the web
    typecheck and the web build pass.
- **Known gap:** the browser flows were walked through in the running app (stub engine) but not run by Playwright here:
  this session's sandbox can bind no port and start no browser. CI runs them.

### Added — Start, the first step of the new flow: one screen, no approvals (R2b)
- **What** (`docs/plans/2026-10-19-p0-p5-redesign.md` §3.1; D-27, D-28):
  - **A new Start screen** (`/projects/{id}/start`; the create flow now lands there). Six blocks on one page, built
    from the kit:
    1. the drug, its PubChem identity with one molecular weight, and the files, with an upload that sends workbooks
       to client data and the rest to the documents;
    2. the short brief: question, context of use and applications, plus BCS class, pathways (suggested from the
       harvested expression library), nonlinearity and recycling;
    3. the ICH M15 model risk;
    4. the scope gates;
    5. the data checklist;
    6. the proposal notes, collapsed and never required.

    Every value shows the words it was read from, opened on its page beside. A side panel lists what Start still
    waits on. There is no approve button: the one review is at the MAP signature (D-27). The old brief page and its
    approval routes stay for the T-56 kit until R5.
  - **No reason is asked for a brief edit** (`p1-why` dropped). `edit_field` takes an optional note; the record keeps
    who and when, and the audit trail the value before and after. `PUT /brief` takes an optional `reason`; without
    one, the version records the fields changed. An edit answers the open question on its field.
  - **The model risk, from its two ratings.** New human-only fields `m15.influence_rating`, `m15.consequence_rating`
    and `m15.risk_justification`, which the intake agent may not set.
    - The tier must lie in the range `pbpk_domain.m15.allowed_model_risk` admits (locked module, only read): an edit
      outside it is refused with 422.
    - When the ratings differ, Start waits on a justification.
    - The picker reads the admitted tiers from the API (`start.risk.admitted`), so the rule is written once.
  - **Scope gates (D-28)**, `feasibility.scope_gates`: modality, PBPK model (new `scope.pbpk_model`: full or
    minimal), site of action (new `scope.site_of_action`), formulation types (new `scope.formulation_types`: the MS-01
    split's kinds, then liposome, amorphous solid dispersion, long-acting injectable, inhaled, dermal and other) and
    the scenarios' routes.
    - A minimal model, a local site of action, a product type outside the split's kinds, or a route the builder does
      not make is "not supported yet" at Start.
    - Modified release is "limited", in the words the feasibility check already used.
    - The same lines reach the feasibility report.
  - **Start's state** (`steps.start_problems`) reads all of it. Start is done when the question, its context of use
    and applications are set, the risk is rated, set and justified, every gate is set and supported, and no question
    on the short brief is open. Proposal notes never hold it up.
  - **The data checklist follows the brief.** `data_plan.refresh_data_plan` re-derives the requirement matrix and the
    feasibility report whenever a saved brief makes them stale: at start, after extraction and after each edit. No
    derive button and no approval.
  - **The plan reads the brief on every rebase.** `plan:rebase` rebuilds the structure from the latest brief
    (`structure_from_brief`) and keeps the keys a person set on the canvas (`plan.keep_locked`). So a changed
    question, context of use, applications or model risk now reaches the plan and the MAP, where before it was read
    only once.
  - **The brief answer** gains `start` (problems, gates, risk, pathway suggestions), and its catalog gains
    `short_brief`, `short_group_fields` and `option_labels`. The OpenAPI snapshot and `api-types.ts` are regenerated.
- **Why:** the owner found P0–P1 too slow. A field-by-field review with a reason for each edit and two approvals is
  replaced by one screen that asks only what the model, the MAP and the scope need.
- **Impact:**
  - **Existing briefs keep working:** the new fields are optional. A tier set without ratings is not range-checked,
    but Start shows "needs you" until both ratings are given.
  - **No science module changed:** the M15 rule and the split's formulation kinds are read from their locked modules,
    nothing in S0–S7 changes, and no PK-Sim result is affected.
  - **The intake agent's prompt** lists the new fields (its prompt is built from the catalog). The three M15 fields
    are refused to it, like the tier.
- **Tests:**
  - `test_steps.py`: Start done with no approval; the refusals; the M15 range; open questions;
  - `test_brief.py`: an edit with no reason answers its question;
  - `test_brief_api.py`: no-reason edits, the refused tier, the checklist kept current;
  - `test_plan_api.py`: a brief edit reaches the plan on rebase while a person's choice stays;
  - e2e `start-step.spec.ts`: the manual path, with a liposome refused and Start done. `start-project.spec.ts`
    follows the new redirect.

### Infra — the API image's base comes from Google's mirror instead of AWS ECR Public
- **What:** `services/api/Dockerfile` now starts from `mirror.gcr.io/library/python:3.12-slim` instead of
  `public.ecr.aws/docker/library/python:3.12-slim`. Both serve the same official image: the same digest for this tag,
  `sha256:a6e34c59…`, on 2026-10-18.
- **Why:** AWS ECR Public answered `429 Too Many Requests - Data limit exceeded` to GitHub's runners four times on
  2026-10-18 (#67, #68, #70, #71). Each time, the "API image" check failed before any of our code was built, and the
  job had to be re-run.
- **Impact:**
  - **Nothing changes in the image:** the same Python base, and still nothing pulled from Docker Hub. `ci.yml` is
    unchanged and no locked file is touched.
  - **Checked here:** the new base pulls with the same digest and runs (Python 3.12.15). The full build is checked by
    CI, because this container cannot reach GHCR's blob host for the `uv` layer.

### Added — the redesign's foundation: light and dark themes, four steps instead of seven phases (R2a)
- **What** (`docs/plans/2026-10-19-p0-p5-redesign.md` §3 and §7; the owner found the screens dull and hard to move
  through):
  - **Light by default, dark on request.**
    - `globals.css` defines every colour as a token: light on `:root`, dark under `prefers-color-scheme` and under
      `[data-theme="dark"]`. The teal (predicted) / amber (observed) pair keeps its meaning in both.
    - A new `--on-sim` keeps the primary button readable on teal in both themes.
    - A theme toggle in the sidebar (Auto / Light / Dark) is remembered in the browser and applied before the first
      paint.
  - **The step bar replaces the P0–P6 rail on every project page.** Start, Inputs, Review & sign and Run each show
    done, needs you, running or not started, and the step the page belongs to says what it is waiting on. While the
    Inputs step still spans three pages (until R3), they are linked under it.
  - **`GET /projects/{id}/steps`** (`modeler_project.steps`) reads each step from content, never from an approval
    (D-27):
    - **Start:** the drug, the question, its context of use and the model risk are set;
    - **Inputs:** the latest readiness check passed and is current;
    - **Review & sign:** the MAP is signed and current;
    - **Run:** from the project's campaigns.

    `/phases` stays for the T-56 kit and the history page.
  - **A small kit** (`components/kit`, `app/styles/kit.css`): PageShell, SidePanel, EmptyState, InlineIssue,
    DataTable and Stepper, in plain CSS on the tokens, with no new dependency. The rebuilt screens use it, starting
    with Start (R2b).
- **Impact:**
  - Pages look the same apart from the theme and the step bar; no flow changes.
  - API contract: one new route. `docs/api/openapi.json` and the web types are regenerated.
  - Tests: `test_steps.py` (10), `test_steps_api.py`, `start-project.spec.ts` on the step bar. Dev e2e 18/18.

### Docs — the P0–P5 redesign on paper: four steps, one review (R1)
- **What:**
  - `docs/plans/2026-10-19-p0-p5-redesign.md` turns the owner's 104 field-map decisions (2026-10-17) and answers
    (2026-10-18) into four steps: **Start** (P0 + P1), **Inputs** (P2 + P3 + P4, three tabs), **Review & sign** (P5),
    and **Run**. For each screen it gives the map rows it carries, what moves or is removed (route, page, tests,
    replacement, PR), the agents' roles, the open SME items, and the acceptance targets (under 30 person decisions on
    the owner's project; the T-56 kit reaching the same CPF and study roles).
  - Decisions **D-27** (no per-item review; one review at the MAP signature, superseding §14.1 rule 2 of the start-up
    plan step by step), **D-28** (out-of-scope products refused at Start), **D-29** (demographics entered or an
    explicit healthy-adult default, recorded as a limitation) and **D-30** (SME thresholds advisory until signed),
    recorded in `2026-09-25-project-startup-pipeline.md` §21, with **D-31** after the screen review.
  - Wireframes for the owner's approval: a private page with Approve / Change per screen.
- **Why:** the owner found P0–P5 "near to impossible" to get through on real data (2026-10-15) and asked for the flow
  to be redesigned on paper before anything is rebuilt.
- **The owner approved all six screens on 2026-10-18**, with notes, now folded in (§9 of the document):
  - the Individuals and Simulation settings tabs described (population database, demographics, calculation methods,
    solver settings);
  - minimal PBPK refused at Start;
  - a prominent template / manual-entry fallback on Studies;
  - study roles proposed in Studies and changed in Review, with blinding following S5;
  - the tier's acceptance criteria and a stricter-only project target on Review;
  - VBE in its own panel;
  - the fixed per-stage budget split. This is **D-31**, no per-stage overrides, enforced in R0.
- **Impact:** documentation only. The rebuild starts with R2 (the design foundation, then Start).

### Changed (science) — a campaign runs within its signed MAP, starts only when it is signed, and never assumes the model risk (R0)
- **What** (plan `docs/plans/2026-10-18-run-integrity.md`; the owner's order of 2026-10-18: "fix them first", with the
  time budget "set at signing"):
  - **Each stage runs within the signed MAP's limits** (`local_runner.LocalExecutor._limits`). The stage's time is the
    budget set at the start (`stage_budgets_seconds`, as the reference runs do), else the MAP's `stage_plan` budget,
    else 30 min as before. Its rounds are the MAP's `max_rounds` (MS-01), else the request's. Every stage's notes
    say which limits it ran with and where they came from ("Limits: 34 min (the signed MAP), at most 2 round(s) (the
    signed MAP)"). Before this the runner ignored the MAP: 30 min and 4 rounds for every stage.
    - **Science impact:** **S3 now runs at most 2 rounds** (MS-01's stage plan; it ran 4). S1, S2 and SM keep 4. Stage
      times are MS-01's fractions of the campaign budget: S1 and S2 20 %, SJ 15 %, S3 7 %, S4 and S5 5 %, S6 20 %.
  - **The campaign's time budget is the person's, set in the plan** (P5 "Time budget (hours)", structure key
    `campaign_budget_seconds`, 10 min to 48 h). **Default 8 h**, so that the smallest fit stage (S3, 7 %) gets 34 min,
    more than the 30 min every stage had before. `campaign:prepare` takes it too. It is a maximum: a stage ends when it
    passes. The plan warns at signing when a stage with a fit gets no more than a fit's 15-min reserve
    (`plan.FIT_RESERVE_S`, equal to the runner's by test), instead of the stage escalating at run time.
  - **No campaign starts on an unsigned MAP outside development** (`modeler_api.run_guard`): in pilot and production
    `POST /campaigns` answers 409 unless the MAP is SIGNED, or a `map_approval` signature is recorded on its exact
    bytes. Development (tests, the reference runs) still starts unsigned MAPs.
  - **No per-stage budget overrides outside development** (the owner's decision on the screens, 2026-10-18: "keep the
    guardrails strict"). In pilot and production, a `POST /campaigns` that sets `stage_budgets_seconds` answers 422.
    Each stage gets its MS-01 share of the signed budget; a campaign that needs more time gets a larger budget in the
    plan, signed again. The reference runs, which are development, still set their own.
  - **The model risk is never assumed** (ICH M15: it decides the acceptance criteria):
    - the plan takes it only from the brief's `acceptance.tier`. Unset, the validator blocks the signature ("Set the
      model risk…"), and it is set in the plan with a reason (new `RiskAndBudget` control);
    - `POST /campaigns` requires `model_risk`; `campaign:prepare` takes it from the body or the question, else 422;
    - `POST /projects` with a question requires the question's `model_risk` (422 otherwise); a project without a
      question needs none;
    - the web's run button passes the prepared tier, not a fixed "medium".
  - **Every e-signature is an audit event** (`part11.record_signature`: `signature.create` with the record's sha256,
    meaning and method), so a `map_approval` signature is found in pilot's file mode too, not only in PostgreSQL.
  - **The P6 rail shows the run:** "running" while a campaign of the project exists, "completed" once one completes,
    read from the runner's campaign store (no artifact is written; the CAMPAIGN kind has no owner in the locked
    `boundaries.toml`).
  - **A waiting decision opens on the project and campaign pages** (`EscalationPopup`, the owner's map note on
    2026-10-17): the same signed decision as in the review inbox, with "Decide later". The inbox still lists them all.
- **Why:** the owner's map review (2026-10-17) and guide (4A.1–4A.3, 1.4, 3.7, 3.8) found that the runner ignored the
  signed MAP, a campaign could start unsigned, the model risk silently defaulted to medium in four places, and the P6
  rail never moved.
- **Impact:**
  - S3 fits stop after 2 rounds instead of 4 and escalate sooner.
  - **Verified on PK-Sim (2026-10-18, engine 12.4.4, Actions runs 39131983498 and 39132704379 on 2ab39c9): nothing
    else moved.** Each Dapagliflozin reference task gives the same result as run 37922984864 before R0:
    - round trip: 25 of 34 identical within 1e-6 of the peak, 3 within 1e-3, 6 labelled by design;
    - as-is: S1 escalates on the Boulton 2013 IV microdose Cmax, 0.52× (AUC / Cmax GMFE 1.391 / 1.92). The stage
      now notes "Limits: 90 min (set at the start), at most 4 round(s) (the signed MAP)";
    - refit: S1 escalates after the clearance fit, with UGT1A9 clspec at its lower bound (GMFE 2.478 / 2.516 at
      baseline, 1.412 / 2.291 after the fit).
  - **S3's 2-round limit is not yet exercised on PK-Sim:** none of these campaigns reaches S3. It is covered by
    `test_each_stage_runs_within_the_signed_maps_limits_and_says_where_they_came_from`. Reaching S3 on the published
    models waits on the S1 IV Cmax question (`docs/SME_SIGNOFF.md` §1).
  - Callers must state the model risk: `deploy/proof/run_t56.py` now puts `acceptance.tier` "medium" in its brief
    (the person's rating for T-56); the reference runs, case studies and showcase seeders already passed one.
  - API contract: `CampaignStartRequest.model_risk` required; `PrepareRequest` gains `model_risk` (optional) and
    `campaign_budget_seconds`; `ProjectCreate.model_risk` has no default. `docs/api/openapi.json` and the web types
    are regenerated.
  - Tests: `services/api/tests/test_run_integrity.py` (6), plan and runner tests, and two browser flows
    (`escalation-popup.spec.ts`, the model plan setting the risk). Dev e2e 18/18.
- **Known gap:**
  - **The 1-hour goal does not fit MS-01's fractions.** S3's 7 % of 1 h is 4 min, under a fit's 15-min reserve, so
    S3 cannot fit within an hour. A fitting S3 needs a budget of more than 3.6 h (4 h with a metabolite stage). Either
    the SME changes the fractions or the reserve, or the goal is restated. Listed for the SME and the owner.
  - **The Temporal path** (`modeler_orchestrator.campaign`, built, not deployed) still uses 30 min and the request's
    rounds per stage. It is brought in line when Temporal is deployed.

### Docs — production readiness recorded: the two new seams and the go-live order (P4)
- **What:**
  - `docs/ARCHITECTURE_BOUNDARIES.md` §7 records the audit mirror (P2) and project memberships (P3): who owns each,
    which way it points, and the rule that keeps it safe. Neither adds a boundary exception.
  - `docs/CONTINUATION_PACKAGE.md` §4 is dated 2026-10-15. §4.3 gains a production-readiness row (K1–K3, P1–P3,
    PRs #60–#65). §4.4 gains the ordered go-live steps (merge, deploy, PostgreSQL, Keycloak, users, secrets,
    restart, checks), pointing to `deploy/keycloak/README.md` for the details.
- **Why:** the approved production-readiness plan ends with the records. The next session, or the owner, should
  find the go-live order in one place.
- **Impact:** documentation only.

### Added — a project opens to its creator and the people they add, recorded and audited (T-06, P3)
- **What** (plan `docs/plans/2026-10-15-project-members.md`; owner-approved 2026-10-15, including the locked
  `auth.py`):
  - **Memberships kept by the platform** (`modeler_project.members`, per tenant in `<read_root>/<tenant>/members.json`):
    - a new project's creator is its first member (`POST /projects` and `POST /projects:initiate`);
    - a member adds a person who has signed in to the tenant at least once, and removes one with a reason;
    - a project keeps its last member;
    - every change is an audit event (`project.member.add`, `project.member.remove`), so production also keeps it in
      PostgreSQL (P2).
  - **Access** (`modeler_api.memberships.admit`, called by the locked `auth.current_principal`): a person opens the
    projects in their token's `projects` claim *and* those they are a member of. Each person who signs in is
    remembered, so a member can add them.
  - **The project list** shows only the projects the person may open.
  - **Routes:** `GET /projects/{id}/members`, `POST /projects/{id}/members`, `POST /projects/{id}/members:remove`
    (members only; refusals are 409 with the reason).
  - **The web:** a Members panel on the project page.
  - **Unchanged:** the DEV principal's `*` (pilot, development) still opens every project. The creator is recorded,
    and the panel says that memberships take effect under Keycloak sign-in.
- **Fixed on the way:** `POST /projects` with the name of an existing project the person may not open used to
  overwrite that project's record. It now gets a new id, as `POST /projects:initiate` already did, and does not join
  the other project.
- **Locked file changed:** `services/api/src/modeler_api/auth.py` (`current_principal` adds the platform
  memberships). Hashes refreshed.
- **Why:** before this, a project made in the web stayed closed to its own creator under Keycloak until an
  administrator added its id to their `projects` attribute.
- **Verified:**
  - `services/api/tests/test_project_members.py` (8 tests): the creator opens the project and others get 403; the
    list is filtered; adding needs a person who has signed in; removing needs a reason and keeps the last member;
    non-members can neither see nor change members; a same-named project does not join another's; the token's claim
    still admits; the DEV principal is unchanged. Each change is checked in the audit chain.
  - `apps/web/e2e/members.spec.ts` (dev mode), and `oidc-signing.spec.ts` against Keycloak 26.7.5: a person creates a
    project, a colleague who signed in is refused, is added in the Members panel, and then opens it.
- **Impact:** OpenAPI gains the three member routes (`docs/api/openapi.json`, `apps/web/lib/api-types.ts`). The
  Keycloak `projects` attribute becomes optional: it is needed only for projects made before this change or outside
  the web.

### Added — production keeps its Part 11 records in PostgreSQL, where the API cannot change them (T-05/T-06, P2)
- **What** (plan `docs/plans/2026-10-15-part11-records-postgres.md`; owner-approved 2026-10-15, including the locked
  files below):
  - **Audit events** go through `modeler_storage.part11`:
    - the file chain (`modeler_project.audit.AuditLog`) calls an injected mirror inside its lock, *before* a line is
      written;
    - the record goes into `audit_events` with the file chain's own hashes, after any records the database lacks
      (the pilot's history, a past outage), in order;
    - a database that refuses, or is ahead of the file chain, or does not link to it, stops the append and so the
      action. No event exists only in the file.
  - **Every signature is a row.** The sign points in use (`signatures_api`, `plan_api` approve, the local escalation
    resolve) write it right after `sign_after_step_up`, before the signed record is applied. The signer is upserted
    into `users` by token subject.
  - **Tenants:** the file chain names them (`dev`) and the schema keys them by UUID. They map through `tenants.slug`,
    and the hashes cover the name, exactly as the file chain computed them.
  - **Production requires it** (`modeler_api.config.check_part11`): `MODELER_PART11_STORE=postgres`, and the
    database must answer, with its Part 11 tables, before the API serves anything. Pilot and development keep the
    files only.
  - **`postgres.sh env`** prints the lines for the secrets file.
  - **`postgres.sh verify`** (`python -m modeler_api.part11 verify`, also nightly) checks every tenant's copy against
    its file chain, with the deployment's own settings. The database URL is never a command-line argument.
- **Locked files changed:**
  - `packages/project-model/src/modeler_project/audit.py`: the `AuditMirror` hook;
  - `packages/project-model/src/modeler_project/store.py`: the store passes it on;
  - `services/api/migrations/0004_part11_records.sql`, new: `signatures.record_id` becomes text, because records are
    named, not UUIDs; `users.email` becomes nullable, because a token may carry none. Applied migrations are never
    edited.
- **Why:** the owner approved production readiness on 2026-10-15. A file chain shows a tampered line, but nothing
  stopped a whole rewritten chain. The database copy cannot be changed by the API's own login.
- **Verified** (`services/api/tests/test_part11_postgres.py`: 6 tests against PostgreSQL 16 set up by `postgres.sh`,
  through the API's login, run as an ordinary account):
  - events reach the database with identical hashes, and `verify` is clean;
  - the pilot's history is backfilled in order;
  - a refusing database leaves the file unwritten;
  - a rewritten file line is reported, and a shortened file chain stops the append;
  - a signature taken through `POST /signatures` is one row (`oidc:` method, printed name), and recording it again
    is refused;
  - the verify command checks every tenant with the deployment's settings.

  Also: `test_production_start.py` (production starts only with the Part 11 store, which is asked first) and the 4
  P1 deploy tests.
- **Impact:**
  - nothing changes until a deployment sets `MODELER_PART11_STORE=postgres`;
  - on the server, `postgres.sh install` and `postgres.sh env` come before the switch to production (README);
  - the other records (projects, campaigns) stay in the file stores;
  - the Temporal-path routes, not deployed, are unchanged.

### Added — PostgreSQL on the server without sudo; Keycloak on it; nightly backups with a restore check (T-05, P1)
- **What:** `deploy/server/postgres.sh` (`install`, `migrate`, `start`, `stop`, `status`, `backup`, `restore-check`):
  - **Install:** PostgreSQL 16 from conda-forge (it publishes `postgresql` 16 for linux-64), under
    `~/modeler-postgres`.
  - **Network:** it listens on `127.0.0.1` and its own socket only, with scram-sha-256 authentication.
  - **Passwords:** random, in mode-600 files, and passed by environment or standard input, never in a process's
    arguments.
  - **Roles:**
    - `modeler_owner` owns the schema and only runs migrations;
    - `modeler` is the API's login. Its privileges exclude UPDATE, DELETE and TRUNCATE on every table guarded by
      the `reject_mutation` trigger, and it cannot disable those triggers or drop the tables;
    - `keycloak` owns Keycloak's database.
  - **Migrations:** `services/api/migrations` are applied once each, in a transaction, recorded with their sha256.
    A migration that changes after it was applied stops `migrate`.
  - **Backups:** of both databases, mode 600, kept 14 days. `restore-check` restores the latest into scratch
    databases and compares every table.
- **Keycloak:** `keycloak.sh` uses PostgreSQL when `MODELER_KEYCLOAK_DB=postgres`, with its password by environment.
  `keycloak.sh migrate-db` moves every realm, user and authenticator enrolment from the file database. The export
  is private and deleted afterwards, and the file database is kept as the way back.
- **The stack:**
  - `run_modeler.sh`, `stop_modeler.sh` and `status_modeler.sh` run PostgreSQL with the stack once it is installed;
  - the watchdog's health check includes it;
  - `install_autostart.sh` adds the nightly backup and restore check (02:17).
- **Why:** the owner approved the production-readiness plan, including PostgreSQL, on 2026-10-15. Keycloak's
  `dev-file` database is deprecated for production, and the Part 11 records need a database that refuses changes.
- **Verified:**
  - **`packages/storage/tests/test_postgres_deploy.py`** (4 tests, run as an ordinary account against PostgreSQL 16):
    - each migration is applied once, and a re-run applies none;
    - the secrets are mode 600, and the server listens on `127.0.0.1` only;
    - the API's login is refused UPDATE, DELETE and TRUNCATE on `audit_events` and `signatures`, and cannot disable
      the trigger or drop the table;
    - a changed migration stops `migrate`;
    - a backup restores completely.

    The tests are skipped where there is no PostgreSQL 16 or under root.
  - **`keycloak.sh migrate-db`** moved this session's test Keycloak: all realms, 10 users, and a user's password and
    TOTP. `e2e/oidc-signing.spec.ts` then passed against Keycloak on PostgreSQL.
- **Impact:** nothing changes on a server until `postgres.sh install` is run. The platform's own records still live in
  the file stores until P2.
- **Found for P2:** the schema keys every row on a UUID `tenant_id`, while the platform's tenants are names (`dev`). P2
  maps them through the `tenants` table (`slug`).

### Changed — the server runs as production once Keycloak is configured, with the web over HTTPS (T-06, K3)
- **What:**
  - **`deploy/server/_env.sh`** reads `~/.modeler-secrets.env` first.
    - With `MODELER_OIDC_ISSUER` there, it runs `MODELER_DEPLOYMENT=production` without `MODELER_DEV_AUTH`. The API
      then refuses the DEV verifier, and every signature is a Part 11 signature.
    - Otherwise it stays a **pilot** with the DEV sign-in, which is not Part 11, as before.
  - **`deploy/server/keycloak.sh env`** prints every line the switch needs:
    - the realm;
    - `MODELER_WEB_URL` over HTTPS;
    - the web's certificate (`MODELER_WEB_TLS_*`), the one Keycloak serves.
  - **`apps/web/server.mjs`** serves Next's own request handler behind `node:https`, because `next start` has no
    HTTPS. So the sign-in cookies are Secure, and no password or token crosses the network in clear.
  - **`run_modeler.sh`, `stop_modeler.sh` and `status_modeler.sh`:**
    - they start, stop and report Keycloak with the stack;
    - the watchdog's health check includes Keycloak once it is needed;
    - they print the deployment and the web's scheme.
- **Why:** the owner's item 5 (2026-10-12): Keycloak before production. The pilot's DEV sign-in is not Part 11.
- **Verified:**
  - `tests/architecture/test_engine_identity.py` now sources `_env.sh` both ways: pilot with the DEV sign-in over HTTP,
    and production without it over HTTPS. It replaces the check that only read the pilot line.
  - `e2e/oidc-signing.spec.ts` passes in a real browser against the HTTPS web (`server.mjs`, the keytool PKCS#12 from
    `keycloak.sh`) and HTTPS Keycloak 26.7.5: sign-in, a refused signature, the step-up with TOTP enrolment, the retry
    accepted, a second step-up, and sign-out.
- **Impact:**
  - nothing changes on the server until the owner adds the lines and restarts;
  - existing pilot records keep their DEV signatures, marked as not Part 11;
  - new Part 11 work is best kept in its own tenant (the Keycloak users' `tenant_id`), because the pilot's projects are
    under `dev`.
- **Known gap (an owner decision, not changed):** the API admits a person only to the projects listed in their
  `projects` attribute (`require_project`, locked `auth.py`). A project created in the web is not reachable until an
  administrator adds its id in Keycloak.

### Added — the web app signs in through Keycloak, and every signature asks for the password and the code again (T-06, K2)
- **What:** with `MODELER_OIDC_ISSUER` set, the web uses the Authorization Code flow with PKCE (S256) against the
  `modeler` realm. Nothing new is installed: Web Crypto and `fetch` only.
  - **Routes:**
    - `app/auth/login` checks the state, nonce and return path, so it cannot be an open redirect;
    - `app/auth/callback` exchanges the code over the back channel, and checks the state and the ID token's nonce,
      issuer and audience;
    - `app/auth/logout` ends the Keycloak session too.
  - **The tokens live in httpOnly cookies,** which the browser's code never reads. They are Secure when the web is
    served over HTTPS.
  - **`proxy.ts`** (Next 16):
    - it refreshes the access token over the back channel when it is about to expire;
    - it puts the person's own token on every `/api/*` call, replacing the DEV bearer the browser's code sends;
    - without a session, a page goes to the sign-in and an API call answers 401.
  - **Server components' reads (`serverGet`) use the person's token.** It is read from the cookie through a
    server-only dynamic import, so the browser bundle holds none of it (checked: no session cookie name in
    `.next/static`).
  - **The one call to Keycloak's token endpoint is `identityToken` in `lib/api.ts`,** so rule B6 holds unchanged
    ("only the client fetches").
  - **The layout reads the signed-in name through `lib/session.ts`.**
  - **A signature refused for want of a step-up** (403 `STEP_UP_REQUIRED` / `STEP_UP_STALE`) opens the
    `StepUpDialog`. It says why and opens Keycloak's loa2 check in a small window on the person's click, so the page
    keeps what they typed. The client then sends the signature once more. This covers the MAP, plan and escalation
    signatures, which all go through `lib/api.ts`.
  - **The sidebar** shows the signed-in person and a "Sign out" link.
- **Unchanged without `MODELER_OIDC_ISSUER`:** the DEV sign-in, which is not Part 11. The 16 dev-mode browser flows pass
  unchanged.
- **Verified in a real browser** (`e2e/oidc-signing.spec.ts`, Playwright and Chromium) against Keycloak 26.7.5 with the
  realm imported and served by `keycloak.sh` (HTTPS front channel, HTTP back channel):
  - sign-in through Keycloak, and the name in the sidebar;
  - a signature without a step-up is refused: the proxy replaced the browser's DEV bearer with the person's own token;
  - an escalation decision opens the dialog. The Keycloak window asks for the password and enrols the authenticator,
    then closes, and the decision is sent again and accepted;
  - a second step-up asks for the password and the code again. The signature records `auth_method` `oidc:loa2` and
    the person's printed name;
  - sign-out leaves no session.

  The spec runs only with `E2E_OIDC_ISSUER` set. CI keeps the dev-mode flows; adding a Keycloak service to CI is a
  change to the locked `ci.yml`, for the owner to approve.
- **Impact:** nothing changes on the server until the switch to production (K3) sets the variables.

### Fixed / Added — the Keycloak realm imports and works; Keycloak runs on the server without sudo (T-06, K1)
- **Fixed:** `deploy/keycloak/realm-modeler.json` could not have worked. Importing it into Keycloak 26.7.5 found:
  - **The import failed:** `Unrecognized field "__comment"`.
  - **Its `clientScopes` list replaced Keycloak's built-in scopes.** Tokens would have carried no `sub`, `auth_time`,
    `acr` or realm roles.
  - **Keycloak 26's user profile dropped the undeclared `tenant_id` and `projects` attributes.** The API would have
    refused every token ("no tenant claim").
  - **There was no `modeler-api` audience**, so the API's audience check would have refused every token.
  - **The `signing` flow was bound to nothing**, so asking for `acr=loa2` would never have triggered it.
- **Now:**
  - the claims and the audience are mappers on the `modeler-web` client;
  - the user profile declares `tenant_id` and `projects` as admin-only attributes;
  - the browser flow `modeler browser` has levels: loa1 is the password; loa2 is the password and the TOTP again,
    with a max age of 0, so each signature re-verifies both factors (21 CFR 11.200);
  - the redirect URIs cover `localhost`, `127.0.0.1` and `192.168.1.10` on port 3000;
  - "forgot password" is off, because no mail server is configured.
- **Verified on Keycloak 26.7.5** in this session, through the browser flow over HTTP forms:
  - **Sign-in:** asks only for the password. The token has `acr=loa1`, the audience `modeler-api`, the tenant, the
    projects and the roles. `JwksTokenVerifier` accepts it, and `ensure_step_up` refuses to sign
    (`STEP_UP_REQUIRED`).
  - **First step-up:** asks for the password and enrols the TOTP. The token has `acr=loa2` and a new `auth_time`, and
    signing is allowed.
  - **Second step-up:** asks for the password and the TOTP again.
  - The same results held with the server script's HTTPS front channel and HTTP back channel. Re-running `install`
    kept the users and their TOTP.
- **Added:**
  - **`deploy/server/keycloak.sh`** (`install`, `admin`, `start`, `stop`, `status` and `env`):
    - Java 21 from conda-forge and Keycloak 26.7.5 from Maven Central, checked against a pinned sha256 (no sudo);
    - a self-signed certificate made once, or the person's own;
    - HTTPS for browsers on 8443, because Keycloak's Secure cookies fail on plain HTTP away from localhost;
    - HTTP on 8080 for the API's key set and the web server's code exchange;
    - the administrator's password is typed only into Keycloak's own prompt.
  - `deploy/keycloak/README.md`.
  - `services/api/tests/test_keycloak_realm.py`, which guards each fix above.
- **Impact:** nothing changes until the stack is pointed at Keycloak: the web sign-in and the switch to `production`
  come next. The server still runs `pilot` with the DEV verifier.
- **Known gap:** Keycloak's database is its embedded file database (`dev-file`, deprecated by Keycloak for
  production). PostgreSQL is a follow-up.
### Infra — CI no longer pulls from Docker Hub (owner-approved 2026-10-12; locked `ci.yml`)
- **What:**
  - The Trivy job runs `ghcr.io/aquasecurity/trivy:0.74.0`, pinned by digest, instead of `aquasec/trivy:latest`.
    The scan settings are unchanged.
  - The API image (`services/api/Dockerfile`) uses the builtin Dockerfile frontend instead of
    `# syntax=docker/dockerfile:1.7`, which used no 1.7 feature.
  - Its base is the Docker official `python:3.12-slim` as AWS ECR Public mirrors it
    (`public.ecr.aws/docker/library/python`, the same image digest as Docker Hub's on 2026-10-13).
- **Why:** on 2026-10-09 the "API image" and "Trivy" checks failed on `main` and on #57 and #58 before any test ran.
  The causes were a 504 from `auth.docker.io` while pulling the frontend, and Docker Hub's unauthenticated pull limit
  for `aquasec/trivy`. Those checks then stayed red on `main` (bc79976).
- **Impact:** no behaviour of the product changes. The two checks depend on GHCR and ECR Public instead of Docker Hub.
- **Known gap:** the engine image still pulls from Docker Hub (`rocker/r-ver` and `dockerfile:1.7`). Its Dockerfile is
  locked and the image is qualified, so a change would alter its digest and needs its own PR and approval.

### Verified on PK-Sim — the model systems, the engine occasion and the system refit (2026-10-09; records only)
- **The Itraconazole and Verapamil systems as-is** (reference run 37947587365 on `main` c2cfd2e) both **escalate at
  S1, before SM**, on the published models' IV Cmax while AUC is in band:
  - Itraconazole, Heykants 1989 IV 100 mg: Cmax 2.14× (AUC GMFE 1.016);
  - Verapamil, McAllister 1982 IV 10 mg (5-min infusion): racemic-sum Cmax 3.10× (stage GMFE AUC 1.198 / Cmax 1.594).
    S1 also judges R-Verapamil (Eichelbaum 1984) and S-Verapamil (Abernethy 1993) on their own analytes, which shows
    MS-01 v1.3 gating at work on PK-Sim.

  Both IV studies **round-trip identically** to the published simulations (run 37922984864: McAllister 6.8e-08,
  Heykants 0). So this is the published models' own early IV peak judged by our S1 Cmax criterion, not a builder
  defect; Dapagliflozin as-is shows the same pattern (S1 IV Cmax 0.52×). Whether S1 should judge a short infusion's
  Cmax is an acceptance-criteria question for the SME (`docs/SME_SIGNOFF.md` §1). Until it is answered, an as-is run
  cannot reach SM.
- **The engine occasion** (`run_job.R` `variability` + `occasion_seed`, B6 PR 3) passed its golden case inside the
  engine image on PK-Sim (engine-image run 37958733969, job 113915823199): "same 6 individuals, seeds 11 and 12 differ,
  seed 11 reproduces, an unknown path stops".
- **The Verapamil system refit** (reference run 37951203929 on `main` fe978bd, 12 045 s) **escalates at S1**: "a fitted
  parameter sits at its bound".
  - The R-Verapamil formation kcats `elim.hepatic.CYP3A4@Norverapamil.kcat` and `@D617.kcat` end at their lower bounds
    (3.49 and 4.40 against the published 34.9 and 44.0, started at 2×). The McAllister racemic-sum AUC is still 0.46×.
  - The cause: the refit shifts every compound's identified parameters at once, but S1 fits only the parent's own
    candidates. The co-parent's shifted kcats (S-Verapamil at 2×) and the shared shifts (logP +0.5, cellular
    permeability ×2, P-gp ×2) are left at their starts, and they drive the racemic sum.
  - It is recorded as an open science question in `docs/SME_SIGNOFF.md` §6: fit a co-parent against a racemic sum at
    S1, or shift one compound at a time. Nothing is changed.

### Added — an illustrative virtual bioequivalence on PK-Sim, the proof of the VBE machinery (T-31 B6 PR 7)
- **What:** `run_reference.py vbe Dapagliflozin` and the reference workflow task `dapagliflozin-vbe` run S6's own VBE
  step (`run_vbe`) on real PK-Sim.
  - **Model:** the published Dapagliflozin model as imported, not a campaign-validated one.
  - **Reference:** the published `IC tablet (Chang 2015)`.
  - **TEST:** an invented `Test tablet`, the same Weibull tablet with t50 × 1.5. Provenance is `assumed`, described as
    illustrative.
  - **Design:** taken from Chang 2015 study 2 (10 mg fasted).
  - **Variability:** `Organism|Lumen|Stomach|Gastric emptying time` at an illustrative 30 % CV. The path is harvested
    from the OSP Ketoconazole and Alfentanil snapshots, and the engine refuses it if the simulation does not have it.
  - **Size:** 20 trials × 24 subjects, seed 2026, PoS threshold 80 %.

  Every output is labelled ILLUSTRATIVE: it shows the machinery working on PK-Sim and is not clinical or regulatory
  evidence. Without an observed BE study, the F-304 gate reports it NOT_VALIDATED.
- **Why:** step 8 of the VBE design, a proof on PK-Sim. Only a PK-Sim run counts as evidence that the two arms, the
  occasions and the trials work end to end.
- **Result on PK-Sim** (reference run 37965688096, job 113939339374, ILLUSTRATIVE): **RUN** in 156 s.
  - 480 individuals, none excluded; 20 trials × 24; occasion seeds 4053 and 4054.
  - **AUC_inf:** GMR median 0.979 (5–95 % 0.977–0.982), PoS 100 %, simulated between-subject CV 27.2 %.
  - **C_max:** GMR median 0.880 (0.877–0.889), PoS 100 %, CV 32.0 %.
  - Joint PoS 100 %. Validation: **NOT_VALIDATED** (no observed BE study, as designed).
  - The slower TEST tablet (t50 × 1.5) lowers Cmax about 12 % and leaves AUC almost unchanged, the expected
    direction.
  - The narrow trial-to-trial GMR spread says the illustrative 30 % CV on gastric emptying moves Dapagliflozin
    exposure little. Which parameters carry intra-subject variability is the SME's question (D-26).
- **Impact:** a new reference task, which runs only when dispatched.

### Added — the MAR, the M15 table and the campaign monitor report the virtual bioequivalence (T-31 B6 PR 6)
- **What:**
  - **MAR §6 (Prediction)** gains the S6 VBE (`campaign_mar._vbe_parts`):
    - `vbe_design`: the template and version, the formulations, the design study, trials × subjects, the individuals
      and how many were excluded, the variability with its sources, the seeds, the limits (flagged when not
      verified), and the threshold;
    - `vbe_results`: per metric the PoS, the GMR median and 5–95 %, and the simulated between-subject CV, plus the
      joint PoS;
    - `vbe_validation`: the F-304 checks against the observed study, when one was given.

    A result that is not validated opens the section in bold: "not validated … does not support a bioequivalence
    decision on its own". The same goes in §8 (limitations) and §9 (conclusion), together with the DRAFT /
    UNVERIFIED template and any limits that are not verified. A VBE that did not run says why.
  - **M15:** a second assessment table, because the VBE is its own question of interest (M15 Appendix 1). It holds
    the technical criteria (the CI limits per trial, the PoS threshold, F-304) and the validation status.
  - **Campaign monitor:** a "Virtual bioequivalence (S6)" card (`components/campaign/Vbe.tsx`).
    - A chip shows the validation status.
    - A warning banner appears before any number when the result is not validated, or when the VBE did not run.
    - Below it: the PoS per metric, the GMR median and 5–95 %, the between-subject CV, and the joint PoS against
      the threshold.
- **Why:** step 7 of the VBE design. A reviewer sees the VBE's design, result and validation status in the report and
  on the monitor, with an unvalidated result never shown as a pass.
- **Impact:** campaigns without a VBE render exactly as before (no new sections, one M15 table).
- **Tests:**
  - `test_vbe_report.py`: the unvalidated, validated and not-run MARs; `check_report` passes; the second M15 table;
  - `e2e/vbe.spec.ts`: a seeded campaign, software test data with no engine run; the card shows "not validated"
    before its 91 % joint PoS.

### Added — the F-304 validation gate: a VBE result is judged against the observed BE study, or it is "not validated" (T-31 B6 PR 5; template `vbe-crossover` 0.2.0-draft; science, UNVERIFIED, D-26)
- **What:**
  - **New template input `observed_be`.** It is optional and never defaulted, and gives the observed BE study
    (REQ-vbe.be_study): per metric, its geometric mean ratio and between-subject CV, plus a source that is required.
    `check_inputs` refuses a value that is not above 0 and refuses a missing source.
  - **The gate** (`pbpk_domain.vbe.validation_gate`). For every metric the observed study names, it checks two
    things:
    - the simulated reference arm's between-subject CV (√(exp(s²) − 1) of the log exposures) lies within the
      template's fold of the observed CV. The fold is 1.5, now a number in the template, `verified: false`;
    - the observed GMR lies within the simulated trials' 5–95 %.

    The result is PASSED or FAILED, naming each check. With no observed study, or one whose metrics are not
    simulated, the result is NOT_VALIDATED and never a pass (real-data rule, D-19).
  - **The S6 VBE result** carries the gate (`validation`: status, checks, source, fold, whether the criterion is
    verified), and the S6 note states it.
- **Why:** step 6 of the VBE design. A probability of success means something only if the model reproduces an
  observed BE study.
- **Impact:**
  - The template is now 0.2.0-draft, so a MAP that pinned 0.1.0-draft is told its pin moved (`MapApplication.problems`).
    No such MAP has run.
  - The 1.5-fold CV criterion stays `[VERIFY]` for the SME.
- **Tests:**
  - `test_vbe.py`: the CV formula, and no study → NOT_VALIDATED;
  - `test_analysis_templates.py`: `observed_be` is optional, and complete with a source when given;
  - `test_vbe_s6.py`: an observed study the model reproduces → PASSED, one it does not → FAILED with both checks named.

### Added — S6 runs the MAP's virtual bioequivalence: two arms, the same individuals, K trials, the probability of success (T-31 B6 PR 4; science, UNVERIFIED, D-26)
- **What:** when the signed MAP pins `vbe-crossover`, S6 runs it from the final CPF (`modeler_orchestrator.vbe_activities`).
  1. **Design.** The trial copies the reference product's own oral single-dose study in the MAP (a fasted one first),
     else another oral single-dose study given as a CPF formulation. The TEST and reference arms are that scenario
     with each product's CPF formulation, built by the round builder.
  2. **Arms.**
     - The TEST arm's population job creates K·n individuals from the person's seed.
     - The reference arm loads exactly those individuals (the TEST arm's `population.csv`).
     - Each arm has its own occasion (the engine's intra-subject variability, B6 PR 3), seeded 2s+1 and 2s+2 from
       the person's seed and recorded.
  3. **Trials** (`pbpk_domain.vbe`).
     - PK-Sim's `pk_analyses.csv` gives AUC_inf and C_max per individual for the named plasma output. A file with
       several outputs is never guessed.
     - An individual without a positive exposure in both arms is excluded and named.
     - The rest form whole trials of n in id order. Each trial is judged by the template's CI on the geometric mean
       ratio (`paired_crossover_ci`).
     - The result is the probability of success per metric and jointly (both metrics pass in the same trial), set
       against the person's threshold, plus the GMR median and its 5–95 %.
  4. **What the result carries:** the template and version, the design study, the formulations, the limits and
     their source and verified flag, the seeds, and the variability.
     - It is always marked "not validated" until the F-304 gate against observed BE data runs (next PR).
     - A VBE that cannot run is `NOT_RUN` with the reason: an input missing, no design study, an arm that cannot be
       built, or an engine stop (e.g. an unknown variability path). It never falls back to a default.
  5. **The S6 notes** state the result in one line.
- **Why:** step 5 of the VBE design. The question of interest is answered by the signed template and the person's
  inputs, on the validated model.
- **Impact:**
  - A MAP without applications runs S6 exactly as before.
  - The number is real evidence only from PK-Sim. The tests use a scripted engine that writes PK-Sim-shaped files,
    and the proof on PK-Sim is B6 PR 7.
- **Tests:**
  - `test_vbe.py`: PK-Sim's own `pk_analyses.csv`, where the two outputs are never guessed; identical vs 30 % apart
    products; exclusions; whole trials only;
  - `test_vbe_s6.py`: two arms each with its own formulation, the same individuals, occasion seeds 11 and 12, K
    trials, and the NOT_RUN reasons.

### Added — the engine's population task runs an occasion: the same individuals, each arm its own seeded variability (T-31 B6 PR 3; locked `run_job.R` and `golden_tasks.R`; science, UNVERIFIED, D-26)
- **What:** the `population` task takes `variability: [{path, cv_percent}]` and an `occasion_seed`.
  - **The occasion:** each individual's value of each listed parameter is multiplied by a log-normal factor with a
    median of 1 and that CV (σ = √ln(1 + CV²)), drawn from the occasion seed (Mersenne-Twister, inversion).
  - **The value multiplied:** the population's own value where the population varies the parameter, else the
    simulation's.
  - **No invented paths:** each path must be a parameter of the simulation (`getParameter(…, stopIfNotFound = TRUE)`);
    an unknown path stops the job.
  - **What is written:**
    - `population.csv` holds the individuals before the occasion, so the other arm loads exactly the same people;
    - `occasion.json` records the seed, the individual ids, and every factor, so an arm can be reproduced.
- **Why:** step 4 of the VBE design. A crossover's TEST and reference arms are the same subjects on two occasions:
  between-subject variability is shared, and within-subject variability is drawn per arm.
- **Impact:**
  - A population job without `variability` runs exactly as before.
  - The median-1 factor and the choice of varied parameters are UNVERIFIED for the PBPK SME. The CV and its source
    are the person's inputs (REQ-vbe.variability, never defaulted).
- **Tests:** a golden case on PK-Sim (`golden_tasks.R`, run in the engine-image CI) varies the compound's
  lipophilicity, harvested from the simulation at run time, by 20 % across occasions. It checks four things:
  - two arms load the same 6 individuals;
  - seeds 11 and 12 give different PK;
  - seed 11 reproduces its PK;
  - an unknown path stops the job.

### Added — the MAP carries the applications its question pins (T-31 B6 PR 2; locked `map.py`, D-26)
- **What:**
  - **`MapDocument.applications`** (`MapApplication`): each application S6 will run, recorded as three things:
    - its analysis template;
    - that template's version, pinned from the registry (`MapApplication.pinned`);
    - the person's inputs.

    `problems(cpf)` names what an application still needs: an unknown or moved template, a missing or invalid input
    (`check_inputs`), and a formulation input that names no CPF formulation (`form.{name}.*`).
  - **Signing refuses an incomplete application.** `MapDocument.sign` refuses a MAP whose application lacks an
    input. A `never_default` input (VBE's variability, trial size, seed and PoS threshold) is named, never filled in.
  - **The content hash leaves out an empty `applications`.** Every MAP signed before this change keeps its hash and
    its signature.
  - **`campaign:prepare`** takes `applications: [{template, inputs}]`:
    - an unknown template answers 422;
    - the answer lists `application_problems` (API contract: `docs/api/openapi.json` and the web types).
  - **The P5 plan:**
    - a brief that asks for APP-14 starts the plan with the `vbe-crossover` application and no inputs;
    - the validator raises one blocking `application` violation per missing input, so the MAP is not generated or
      signed until the person gives them (`PUT /plan/structure`, key `applications`, with a reason);
    - the diff shows the pinned template.
- **Why:** step 3 of the VBE design (`docs/plans/2026-10-06-t31-vbe-template.md`). The signed MAP binds what S6 runs
  and with which inputs, so a VBE result traces back to a signature and never to a default.
- **Impact:**
  - A MAP without applications is unchanged: the same JSON hash and the same signatures.
  - Plans whose brief has no APP-14 are unchanged.
  - MS-01 §9 (what the MAP contains) does not list applications yet. It is SME-governed, so the line goes in at its
    next revision; the T-30 sign-off list names it.
- **Tests:**
  - `test_map_applications.py`: the hash without applications, version pinning, the refused signature, the CPF
    formulation check;
  - `test_plan.py`: the brief seeds the application, the validator blocks it, the inputs are given, and the MAP carries
    them;
  - `test_write_api.py`: prepare carries the applications, names what they still need, and refuses an unknown
    template.

### Added — analysis templates as a typed, locked registry; the VBE crossover template (T-31 B6 PR 1; science, UNVERIFIED, D-26)
- **What:**
  - **Registry:** `pbpk_domain.analysis_templates` is a typed loader (`AnalysisTemplate`, `load_template`,
    `list_templates`, `check_inputs`, `resolved_limits`) for the versioned recipe of each PBPK application. The DDI
    template moves there from `templates/analysis/`. Templates are locked and SME-governed like the rulesets (a new
    lock pattern).
  - **`vbe-crossover` 0.1.0-draft (APP-11, APP-14):**
    - It requires a validated oral model, TEST and reference formulations, and the dissolution, BE-study and
      variability data items.
    - Steps: shared individuals across arms, a seeded occasion per arm, AUC_inf and C_max, per-trial GMR with a
      90 % CI, the probability of success, and the F-304 variability gate.
    - Limits: standard 0.80–1.25 at a 90 % CI (default, verified), and NTI 0.90–1.1111 marked [VERIFY].
  - **Never defaulted:** the intra-subject variability (parameter, CV, source), the subjects per trial, the trials,
    the seed and the PoS threshold.
    - The schema refuses a default for any of them, and `check_inputs` names each until it is given.
    - A variability entry without its source, or with a CV of 0, is refused.
  - **`app_vbe.yaml` 2026.2-draft:** `REQ-vbe.variability` has no default provider (NOT_STATED). The data plan
    says who gives it.
- **Why:** the owner's decision D-26 (2026-10-09). A made-up variability or trial size would decide the virtual
  trials' probability of success.
- **Impact:**
  - No campaign runs VBE yet: the MAP carrying the application, the engine variability and the S6 step follow
    (B6 PRs 2–4).
  - VBE projects' data plans now show the variability as "not stated" until someone is named.
- **Tests:** `test_analysis_templates.py`.

### Added — the model system on the project page, in the upload form and in the MAR (multi-compound phase 3, B5 PR 4)
- **What:**
  - **`GET /projects/{id}/system`** (`ProjectSystem`, `modeler_api.system_view`): the project's model system, or none
    for a single compound. It lists:
    - every compound with its role, and whether its CPF is there;
    - the formation links;
    - the products with each compound's dose fraction;
    - each analyte, with the compounds it informs and the stages that judge it (MS-01 v1.3 §6.5);
    - the stored links, which a client edits and puts back.

    API contract: `docs/api/openapi.json` and the generated web types.
  - **System panel** on the project page (`components/system/SystemPanel.tsx`): the compounds, formation, products and
    analytes. The dose fraction of every product is edited in place and saved through `PUT /projects/{id}/system`.
    An empty or non-positive fraction is refused before it is sent, because it is never defaulted (owner decision 2).
  - **Data intake:** in a project with a system, each uploaded study names the analyte it measures (each option says
    where it is judged) and the product it gives. Both are chosen, never guessed, and the study is not saved without
    them.
  - **MAR §3 lists the model system** (multi-compound plan §3.5), as of the final CPF from the bundle's
    `cpf/system.json`:
    - each compound's role, what forms it, and its CPF version and content hash;
    - every product's dose fractions;
    - each analyte, with the compounds it informs and where it is judged;
    - the system's content hash.
- **Why:** phase 3 of the multi-compound plan. A person can now see and correct what a system campaign simulates and
  judges, and the report says it.
- **Impact:** single-compound projects show no panel, and the upload form and the MAR are unchanged for them.
- **Tests:**
  - `test_model_system_campaign.py`: the panel's read;
  - `test_metabolite_stage.py`: the MAR tables;
  - `e2e/model-system.spec.ts`: the panel, a refused empty fraction, a saved one, and the upload form's analyte and
    product choices;
  - browser flows: 15 of 15 pass.

### Added — the reference refit frees every compound of a model system (`reference/refit.py`, `run_reference.py`)
- **What:** `run_reference.py campaign <model> --mode refit --system` frees each compound's identified parameters,
  shifted and bounded as approved on 2026-09-24.
  - A parent's (and a co-parent's) are fitted at the parent stages.
  - A metabolite's own clearance and logP are fitted at SM. Its absorption and cellular permeability stay as published,
    because it is formed, not dosed.
  - The rate that forms each metabolite also gets SM in its fit policy (`refit_cpf(role=, formation=)`).
  - The report keys the freed parameters by fit id (`S-Norverapamil::…`) and reads each final value from the system
    as of the final CPF.
  - A new matrix task, `verapamil-system-refit`: OSP Verapamil identified its norverapamils' CYP3A4 kcat, P-gp kcat and
    logP, so its refit exercises SM. Itraconazole's metabolites carry no identified parameter.
- **Why:** to prove stage SM on PK-Sim (plan B7). The as-is system campaigns judge the published values; only a refit
  makes SM fit.
- **Impact:** single-compound refits are unchanged. Tested in `test_metabolite_stage.py`; locally smoke-run on the
  stub engine up to the first PK-Sim simulation, which is not evidence.

### Verified on PK-Sim — `main` after the architecture refactor and B1–B4 gives the same results as before it
- **The runs:** reference run 37922984864 (2026-10-09, `main` at 1bff09d, engine 12.4.4) compared with run
  36079717728 (2026-09-25, before phases 1–9 and 8).
- **Campaigns, identical to every printed digit** (predicted AUC, Cmax, t½, the GMFEs, the fitted estimates and the
  escalation):
  - Dapagliflozin as-is: S1 escalates on the Boulton 2013 IV microdose Cmax, 0.52×;
  - Rifampicin as-is: S1, Sanofi 2013 300 mg IV Cmax, 1.59×;
  - Rifampicin refit: S1, VPC 3/6;
  - Dapagliflozin refit: S1 after the clearance fit, UGT1A9 clspec at its lower bound.
- **Round trips, the same counts and rows:**

  | Model | Identical within 1e-6 | Within 1e-3 (solver level) | Labelled by design |
  |---|---|---|---|
  | Dapagliflozin | 25 / 34 | 3 | 6 |
  | Rifampicin | 21 / 22 | 1 | 1 |
  | Midazolam | 85 / 88 | 0 | 3 |
  | Itraconazole system | 16 / 54 | 37 | 9 |
  | Verapamil system | 71 / 75 | 2 | 2 |
  | Dabigatran system | 3 / 10 | 7 | 0 |
- **What this means:** the refactor and B1–B4 changed no PK-Sim result. The Stone 2004 exclusion does not reach S1,
  where the Rifampicin refit stops, and the SJ study weights are not reached either.
- **Still open:** the four campaign escalations are open science items, recorded before this session: the Dapagliflozin
  IV microdose Cmax, the Rifampicin IV Cmax, the Rifampicin VPC, and the UGT1A9 bound. Only these PK-Sim runs count as
  evidence.

### Changed — MS-01 v1.3: a model system's every analyte judged on its own; metabolites fitted at a new stage SM (multi-compound phase 2, PR 3; locked `map.py`, `split.py`, `acceptance.py`, `diagnostics.py`, rulesets and MS-01; science, UNVERIFIED, D-25)
- **What:**
  - **Split (§3.3 rule 7):** each analyte of a model system is split on its own: the fitted parent's plasma, a
    co-parent's, a sum's and each metabolite's own data. Before, the published Itraconazole system's 24
    hydroxy-itraconazole studies competed with the parent's in every class and all landed EXTERNAL, so no metabolite
    ever had data to train on. A single compound has one analyte and is split exactly as before.
  - **Gating (§6.5, `system.gated(stage)`, `system.subjects`):**
    - a co-parent's plasma (S-Verapamil, Dabigatran given IV) is gated at the parent stages and fits that compound;
    - a molar sum of parents sharing one molecular weight (racemic Verapamil) is gated and fits both enantiomers
      together (`a+S-Verapamil::a`);
    - a metabolite's plasma, or a molar sum of metabolites sharing one weight, is reported at S1–S3 and gated at SM,
      SJ, S4 and S5;
    - a sum of a parent and a metabolite, a mass sum, and a molar sum of different weights are never gated.
  - **Stage SM (§4 SM):** after S3 and before SJ, planned only when the MAP has internal metabolite data. A metabolite
    study that trains a parent stage is also planned at SM, where it is gated. The fit candidates are the metabolite's
    own clearance (clspec, kcat, transporter kcat, GFR fraction), its formation rate, and its logP.
    - The formation rate is the rate of the process that forms the metabolite, on the compound that forms it
      (`system.formation_targets`: the published model's `Metabolite` link). In Itraconazole that is the parent's
      CYP3A4 kcat for hydroxy-itraconazole, and hydroxy's own CYP3A4 kcat for keto-itraconazole.
    - A formation fit on the parent is re-judged at S1–S3 by the no-regression gate.
    - SM takes 10 % of the campaign budget when planned, and every other stage keeps 90 % of its share; a single
      compound's plan and budgets are unchanged.
    - SJ refines what S1–S3 and SM fitted (`TRAINING_STAGES`). A metabolite study planned twice is judged there once,
      gated.
  - **Diagnosis:** each analyte's studies are diagnosed apart (`diagnose_round`: `_subject_candidates`,
    `_qualify_action`, `_merge_diagnoses`), and the actions are qualified for the compounds they inform.
    - An escalate rule anywhere escalates the round.
    - diag-rules 0.6 adds `metabolite_clearance` (t½ and AUC off the same way: the metabolite's own clearance, then its
      logP) and `metabolite_formation` (AUC off with t½ right: the formation rate, evidence `formation_off`, computed at
      SM only).
    - The fallback, the optimiser rules and the at-bound escalation also hold at SM.
  - **Acceptance (§8, criteria 2026.2-draft):** every analyte is its own group (`Comparison.analyte`), held to the
    parent's tier limits. That is the conservative placeholder until an SME sets metabolite criteria; no limit changed.
  - **Runners:** `CAMPAIGN_STAGES` includes SM. A MAP that does not plan SM makes it "absent" (`plan_stage`): the
    runner passes over it, and the monitor never lists it (`_planned_stages`). The MAR shows SM when it ran.
  - **Versions:** `MS01_VERSION` 1.3, diag-rules 0.6, acceptance criteria 2026.2-draft. All UNVERIFIED pending SME
    sign-off; the D-25 row is in the start-up plan's decision record.
- **Why:** the owner approved multi-compound phase 2 on 2026-10-09 ("do them all now"). Phase 1 simulated a system's
  every compound but fitted and judged the parent alone; its metabolite, co-parent and racemic-sum data informed
  nothing.
- **Impact:**
  - Single-compound campaigns are unchanged, apart from the MAP's standard version (1.3): no SM in the plan, the
    same split and budgets, and the same diagnosis (one subject).
  - System campaigns now train on more studies (each analyte's best), judge more groups, and may fit metabolite and
    co-parent parameters.
  - Not yet proven on PK-Sim: the Itraconazole and Verapamil system campaigns and a system refit follow (B7).
- **Tests:**
  - `test_metabolite_stage.py`: SM planning, budgets, the single-compound plan unchanged, rule 7, per-analyte
    acceptance;
  - `test_metabolite_diagnosis.py`: the formation rate on the parent, the metabolite's own clearance, a tried action,
    and a racemic sum fitting both enantiomers;
  - SM rules in `test_diagnostics.py`;
  - the Verapamil campaign tests updated to v1.3.

### Added — a fit can move another compound of a model system (multi-compound phase 2, PR 2; science, D-25)
- **What:**
  - **Fit ids:** in a model system, another compound's parameter is fitted as `<compound>::<CPF id>`
    (`fit_spec.qualify`, `split_fit_id`, `fit_owner`, `by_compound`). The fitted compound's own ids stay bare, so
    every existing target, rule and fit spec is unchanged.
  - **System-aware fit steps:** `resolve_fit_ids`, `build_fit_spec` (each parameter at its own compound's PK-Sim
    path), `_fittable_candidates`, the joint refinement's `joint_parameters`, and the fit request (the observed data of
    each study converted with its analyte's molecular weight).
  - **Applying a fit:** each estimate goes back into the CPF of the compound it names, with its own version and
    provenance. The new parent version names each compound the fit moved, with its version and content hash.
  - **Where the state lives (`modeler_orchestrator.round_system`):** a system campaign writes the system as of each
    new CPF version beside it, as `<stem>.system.json`. Every later round, the joint fit, a new-evidence decision
    and the S7 bundle (`cpf/system.json`) read it from there. A CPF with nothing beside it uses the campaign's
    starting system, as before.
- **Why:** MS-01 v1.3, the owner's go-ahead on 2026-10-09 (still UNVERIFIED). Gating a metabolite needs its own
  clearance and distribution to be fittable. A co-parent enantiomer needs its own parameters. Each CPF stays the
  record of its own compound's parameters (the plan's §3.1: no merged CPF with prefixed ids).
- **Impact:**
  - Single-compound campaigns are unchanged: no qualified id is ever produced, and no system file is written.
  - Nothing proposes a qualified target yet. The gating and stage SM that use it are PR 3.
- **Tests:** `test_fit_spec_system.py`, on the published OSP Itraconazole system. `test_round_system.py` covers
  apply, carry forward, the joint plan and single-compound behavior.

### Infra — the reference workflow runs a chosen subset of tasks (`reference-models.yml`, unlocked)
- **What:** a `tasks` input on the manual dispatch takes comma-separated task names. Every step of a task not
  named is skipped, so its job ends in seconds; empty runs every task, as before.
- **Why:** plan B7. The real-PK-Sim evidence for `main` (the refactor's round trip and as-is, then each science
  change's refit) needs a few tasks at a time, not the whole 2–3 hour matrix.
- **Impact:** none on CI. The workflow is manual only.

### Changed — the Weibull release equation is confirmed on PK-Sim (locked `golden/**` and `engine-image.yml`; science)
- **What:**
  - **New check:** the engine-image qualification runs a new check on PK-Sim. `golden/weibull_check.R` runs the OSP
    Dapagliflozin "IC tablet (Chang 2015)" simulation (t50 30 min, shape 0.6, lag 0) and finds the formulation's
    dissolved-fraction quantity among the simulation's own paths (harvested, never typed). `golden/compare_weibull.py`
    compares that curve with `pbpk_domain.dissolution.weibull_fraction` at every output time, within 1 % of the dose.
    The result is recorded as `weibull` in `golden.json`.
  - **The first run passed:** engine-image run 37919482630, PK-Sim 12.3.173 and ospsuite 12.4.4. It compared
    `Organism|Lumen|Dapagliflozin|Fraction dissolved` over 601 points. The maximum deviation was 4.2e-05 of the dose;
    the fraction at 30 min was 0.499965.
  - **`ENGINE_CONFIRMED = True`:** `dissolution.ENGINE_CHECK` cites that run. A proposed Weibull t50, shape or lag
    now carries the check in its conditions (`engine check`) instead of the `unconfirmed` flag.
- **Why:** the plan's harvest rule. The equation was written from PK-Sim's parameterization, and every fit said so
  until PK-Sim's own curve was compared. VBE (T-31) rests on this equation.
- **Impact:**
  - The client-data page no longer shows "equation not yet compared with PK-Sim's own curve".
  - Weibull values proposed from client dissolution data no longer carry the `unconfirmed` flag.
  - The fit itself is unchanged (`weibull-pksim-1`).
  - The f2 conditions and the dissolution checks are still the UNVERIFIED `dissolution_similarity.yaml` ruleset.
- **Tests:** `test_dissolution.py`, `test_dissolution_register.py`, and `e2e/client-data.spec.ts`.

### Fixed — a reported analyte no longer diagnoses the fitted compound (multi-compound phase 2, PR 1; science)
- **What:** `diagnose_round` builds its PK residuals only from gated studies. A model system's reported analyte (a
  metabolite, a sum, a study marked `gated: false` by the evaluation) is still judged and reported on its own, but its
  residuals no longer reach the diagnostic rules.
- **Why:** the evaluation already kept those studies out of the stage gate, but the diagnosis read every study row. A
  metabolite's under-prediction could fire `clearance_off` and propose a fit of the parent's clearance, moving the
  parent to explain data it does not produce.
- **Impact:** single-compound campaigns are unchanged (every study is gated). In a system, only the parent's own data
  drives its diagnosis until the metabolite stage of phase 2 lands. Test:
  `test_diagnose_round_activity.py::test_a_reported_analyte_never_diagnoses_the_fitted_compound`.

### Changed — the enterohepatic recycling fraction is placed and fitted on the Individual (parameter registry 1.2; locked registry and `pksim_paths.py`; science, UNVERIFIED)
- **What:**
  - **Placement:** `elim.ehc_fraction` is no longer refused. It is set on the Individual at `Organism|Liver|EHC
    continuous fraction`, where MS-01 §2.2 places it. The path is harvested from the OSP reference snapshots:
    Dapagliflozin, Midazolam, Rifampicin, Verapamil and Itraconazole set it on their individual, and their simulation
    parameters are written from the same root.
  - **Registry 1.2:** placement `model`, stored as a fraction, with physical bounds [0, 1]. A new registry field,
    `pksim_individual`, names the path (`parameters.individual_paths`).
  - **P4:** binds the value to the Individual, as a published model's `indiv.*` value is bound
    (`cpf.build.individual_parameters` places it).
  - **Fitting:** `pksim_paths` resolves an Individual-bound parameter to its own path, so MS-01's "secondary peak → fit
    `elim.ehc_fraction`" (diag-rules, S2 candidates) can fit it. Before, the fit specification could not be built.
- **Why:** it was refused in registry 1.1 for want of a harvested path. The path exists in the reference snapshots, so
  nothing is invented.
- **Impact:**
  - The parameter vocabulary snapshot changes only on `elim.ehc_fraction`: placement, storage family, bounds, and no
    refusal.
  - The strict xfail in `test_parameter_vocabulary.py` is gone.
  - The registry stays UNVERIFIED, version 1.1 → 1.2.
  - Locked hashes are refreshed: the registry, `pksim_paths.py` and the vocabulary snapshot.

### Changed — the joint refinement weighs every study equally (MS-01 v1.1 SJ, D-04; locked `run_pi.R` and `golden/pi_smoke.R`; science, UNVERIFIED)
- **What:**
  - **The weight:** in a joint fit (SJ, and the joint fit that answers a regression), a study of n points among N
    points over k studies weighs each of its residuals by √(N / (k·n)) (`pbpk_domain.fit_spec.study_weights`). Points
    below LLOQ do not count.
  - **Why this weight:** the engine's parameter identification multiplies each residual by its weight before
    squaring (ospsuite.parameteridentification 2.2.0, `PIOutputMapping$addObservedDataSets(weights =)`, verified in
    its source). So every study adds the same N / k to the weighted sum of squares, and the mean squared weight stays
    1.
  - **The engine:** `run_pi.R` passes `observed.weight` to the engine when the spec carries one. A spec without
    weights runs as before, so stage fits keep equal weight per point, as they always had.
  - **PK-Sim check:** `golden/pi_smoke.R` adds a weighted run on PK-Sim. A weight of 2 on one dataset must leave the
    estimate where it is and multiply the objective by 4.
  - **MS-01 v1.1 §SJ:** the "Weighting" line now says how the weight is applied. The rule itself is unchanged and stays
    UNVERIFIED pending SME sign-off.
- **Why:** D-04 asked each study to contribute equally. Until now the joint fit weighted every point equally and
  recorded that as a known gap ("waits for run_pi.R weights").
- **Impact:**
  - A joint fit now gives a short profile the same say as a dense one, which changes SJ estimates on real data. The
    stage note says so.
  - The engine-image CI qualifies the weighted run on PK-Sim, and the Dapagliflozin refit is re-run on the reference
    workflow.
  - The locked-file hashes are refreshed: `run_pi.R`, `pi_smoke.R` and MS-01.

### Changed — OSP Rifampicin's Stone 2004 dataset is excluded from the reference import (the owner's D5 decision, 2026-10-09; data)
- **What:**
  - A new `pbpk_domain/reference/exclusions.yaml` records each dataset of a published OSP model that is left out,
    with its reason, who decided, and when.
  - `pbpk_domain.reference.import_osp_snapshot` and `import_osp_system` take those datasets out of the snapshot before
    the locked importer runs. They add each one to the import's `skipped` list as "excluded (owner, 2026-10-09, D5):
    <reason>".
  - The reference runner, the showcase seeder, the wizard's templates and the T-56 kit all import through them.
- **First entry:** Rifampicin, "Stone 2004 - Day 14 of Rifampin alone … 600 mg … (n=26)".
  - It is labelled mg/l with values about 1000× below the other 600 mg profiles (likely µg/l).
  - The published model never simulates it, so its unit cannot be checked against the model's own use.
  - Until now it sat in the Rifampicin fitting set.
- **Why:** the open data issue for the owner (continuation §4.1, D5). The published data are never altered; a
  relabel to µg/l was declined as a guess.
- **Impact:**
  - The Rifampicin import has 52 studies instead of 53, and names the excluded one with its reason.
  - Every other model imports as before, as a test checks.
  - The Rifampicin refit on PK-Sim is re-run without it (reference workflow).
- **Known gap closed (records only):** diag-rules 0.4 (2026-09-24) already lets the clearance rule fit Michaelis-Menten
  `kcat`. The entry further down that still calls the Rifampicin refit "held" is superseded by that change.

### Infra — the browser flows run in CI (locked `ci.yml`, owner-approved 2026-10-09)
- **What:** CI gains a job, `e2e` ("Browser flows (Playwright, stub engine)"). It:
  - syncs the workspace;
  - installs the web dependencies and Chromium;
  - runs `npm run e2e`, all 14 specs;
  - uploads the Playwright traces on failure.

  The release evidence pack now also waits on it. The locked-file hash is refreshed.
- **Why:** the specs ran only locally, so a change that broke a page passed CI. This was an owner item marked "needs
  approval".
- **Impact:** about 5 minutes per CI run. The stub engine is a software fixture, so a pass proves UI → API → runner →
  monitor, never the pharmacology.

### Changed — production refuses the DEV verifier; the server becomes a pilot deployment (the owner's decision, 2026-10-09)
- **What:**
  - `MODELER_DEPLOYMENT` gains a third value, `pilot`. It is held to production's engine settings (an explicit object
    store, an engine command, a real engine digest), but it may still sign in with the API's DEV verifier.
  - A production deployment now refuses to start when `MODELER_DEV_AUTH` is set (`modeler_api.config.check_auth`,
    called at startup). The locked `auth.py` is unchanged.
  - `deploy/server/_env.sh` sets `MODELER_DEPLOYMENT=pilot`, because the server signs in with the DEV verifier until
    Keycloak is deployed.
  - `/health` answers the deployment and the verifier (`dev`, `oidc` or `none`). This is an API contract change; the
    snapshot and web types are updated.
- **Why:** a DEV signature stands in for Part 11 step-up and must never become a production record (21 CFR 11.200).
  Before this change the server ran `production` with the DEV verifier.
- **Impact:**
  - Tests: production with dev auth refuses to start; a pilot with dev auth starts and says so in `/health`; a pilot
    without its engine settings refuses to start.
  - **Deviation:** the plan's "pilot" banner on the monitor and in the MAR is not built. The web app does not read
    `/health` yet, and the runner that writes the MAR does not know the verifier. `/health` carries the fact for when
    it does.
  - **The owner's next step:** deploy Keycloak, then switch to `production` and drop `MODELER_DEV_AUTH`.

### Changed — the web app moves to Next.js 16.4; npm audit is clean
- **What:**
  - `npm audit fix` updated `sharp`, `source-map-js` and the transitive `postcss`.
  - The two remaining findings cleared only with Next.js 16, so `next` moves from 15.5 to 16.4.0: Next's SSG/ISR cache
    poisoning advisory, and the PostCSS it bundles (GHSA-qx2v-qp2m-jg93, GHSA-6g55-p6wh-862q, GHSA-fxqj-rqcc-2cmp,
    GHSA-r28c-9q8g-f849).
  - React was already 19. Next 16 builds with Turbopack and rewrote `tsconfig.json` itself (`jsx: react-jsx`, plus
    the dev types path).
- **Why:** the owner's open item, "review the npm audit findings".
- **Impact:** `npm audit` reports 0 vulnerabilities. Typecheck, build and the 14 e2e specs pass on Next 16.

### Added — legacy Excel 97–2003 workbooks (.xls) are read (`xlrd`, owner-approved 2026-10-09)
- **What:**
  - **Grid:** `modeler_intake.grid` reads `.xls` through `xlrd` into the same grid as `.xlsx`: values with their
    sheet!A1 references, merged ranges carried to every cell they cover, dates as datetimes, and whole numbers as
    integers, as openpyxl gives them.
  - **Documents:** read into quotable pages, and recognized by the compound-file signature. A damaged file is refused
    with the reason.
  - **Client data and the start page** accept `.xls`.
  - **Test fixture:** `tests/fixtures/legacy-study.xls` was written once with xlwt 1.3.0, which is not a dependency.
- **Why:** client data often arrives as `.xls`. Before, it was refused with "save it as .xlsx", the known gap of the
  guided reader.
- **Impact:** a new dependency, `xlrd` 2.0.2 (BSD, pure Python), for `modeler-intake`.

### Changed — the engine runs behind a port; no boundary exception is left; phase 8 is done (architecture phase 8c; locked `boundaries.toml`)
- **What:**
  - **The engine port:** `modeler_contracts.ports.EngineFactory`, with `engine_factory()` to load it.
    - The engine worker registers its subprocess runner under the `modeler.engines` entry point
      (`modeler_engine.runner:subprocess_engine`).
    - `local_runner.default_engine` builds the engine through the port, so the orchestrator no longer imports
      `modeler_engine`. Both packages sit on layer 5.
  - **The S3 object store:** `S3ObjectStore` with its presigned URLs moves unchanged from `modeler_orchestrator.storage`
    to `modeler_storage.objects`, because it is persistence. `modeler-storage` now declares `boto3` (already in the
    lock) and `modeler-contracts`; the orchestrator, which no longer uses `boto3`, drops it.
  - **The tests that reached into the orchestrator moved:**
    - the CPF test of `_fittable_candidates` is now `orchestrator/tests/test_fittable_candidates.py`;
    - the engine's object-store test reads `modeler_storage.objects`.
  - **`boundaries.toml`** has no `[[allow]]` entries left; the 4 exceptions are gone. Its hash is refreshed, since the
    file is locked; the exceptions were recorded on 2026-10-07 as "goes behind an engine port".
- **Why:** coupling C3 and rule B4. These were the last 4 recorded exceptions to the layer rule (48 on 2026-10-07).
  Phase 8 is now done: 8a, 8b and 8c.
- **Impact:**
  - No behaviour changes: the same engine runs with the same command and identity.
  - The API image installs every workspace package, so the entry point is registered there as on the server.

### Changed — job state lives beside the data, not in one process; a decision is applied once (architecture phase 8b)
- **What:**
  - **Agent jobs:** each project's agent job (A1 extraction, A2/A3 research, A4 triage, A5 planning) holds a lease,
    `<root>/<tenant>/jobs/<project>/<kind>.json`.
    - The lease is kept by `modeler_storage.jobs.FileJobRegistry` and started through `modeler_api.jobs`.
    - It replaces the four module-level `_RUNNING` sets and thread locks in `brief_api`, `evidence_api`, `client_api`
      and `plan_api`.
    - The job renews its lease every 30 s and releases it when it ends, including on an error.
    - A lease is stale, and is taken over, when it has not been renewed for 120 s or when its process is gone on this
      host. A job lost in a crash or restart therefore never blocks its project.
    - Every worker sees the same `running` flag and refuses a second start with the same 409 text.
  - **Read model:** the read-modify-write collections hold an `flock` on the document while they rewrite it:
    projects, studies, campaigns, escalations and proposals. The lock is `pbpk_domain.atomic_io.file_lock`.
  - **Agent run records:** written atomically, and changed under their lock.
  - **Decisions:** removing an escalation is the claim on its decision (`FileWriteStore.remove_escalation` now
    answers whether it removed one).
    - A second decision on the same escalation is refused with 409 **before** a signature is taken, in the API.
    - It is refused again in the runner, so a campaign never continues twice.
  - **Guardrail:** `tests/architecture/test_process_state.py` fails on new module-level mutable state: a set, a
    thread lock or event, a queue, or an empty collection. The one exception is the audit chain's in-process lock,
    which comes before its cross-process `flock`.
- **Why:**
  - Coupling C8: state kept in one process holds only for the process that owns it. A second worker started the same
    agent job again, showed it as not running, and two simultaneous decisions could both continue a campaign.
  - The 2026-10-07 known gap: upserts were not locked, so two writers could lose an update.
- **Impact:**
  - The answers and texts are unchanged, and the OpenAPI snapshot is unchanged.
  - New tests:
    - leases: claim, release, a stale lease taken over by age and by a dead pid, a lease held by another process,
      and a background job releasing its lease after an error;
    - two processes upserting one collection lose no row;
    - an escalation is removed once, and a decision already taken is refused before any signature;
    - an extraction running on another worker shows and refuses a second start;
    - concurrent proposals on one agent run are all recorded.
  - `packages/storage/tests` joins the test paths.
- **Deviation from the plan:**
  - The plan named a separate campaign lease. Claiming the escalation does the same job with no new state, because
    every paused campaign has exactly one open escalation.
  - The plan's two-uvicorn-workers test became cross-process tests of the registry, plus an API test with a lease
    held by another worker. They prove the same thing without a flaky server start.

### Fixed — an artifact version or blob is never seen half written, and approvals lock across processes (architecture phase 8a; locked `store.py`, owner-approved 2026-10-09)
- **What:** in the Part 11 artifact store (`modeler_project.store.FileProjectStore`):
  - **Versions:** a version is written to a temporary file in its folder, flushed to disk, then hard-linked into
    `vNNNN.json`. The link fails when the version exists, so a version stays write-once.
  - **Blobs:** written the same way. Two writers of the same bytes no longer collide.
  - **Approvals:** `approvals.jsonl` is appended under `flock` instead of a lock held only within one process.
  - On a filesystem without hard links, the store falls back to an exclusive create.
  - The file mode stays 0644. The audit chain already locked across processes and is unchanged.
- **Why:**
  - The known gap recorded on 2026-10-07: the store created a version file and then filled it, so the API could
    read an empty version while an agent job wrote one.
  - Phase 8 (C8, job state out of the process): with a second worker process, a thread lock protects nothing.
- **Impact:**
  - The layout, names and immutability are unchanged, and so is every stored byte.
  - New tests:
    - a rival write of an existing version is refused and leaves no temporary file;
    - a reader polling while 15 large versions are written never sees a partial one;
    - 8 simultaneous identical blobs make one file;
    - two processes appending 150 approvals each lose none.
  - The locked-file hash is refreshed.

### Changed — the evidence and observed-data answers are typed, and the web's untyped helpers are gone; phase 9 is done (architecture phase 9e; API contract)
- **What:**
  - **Typed routes:** the last 5 routes that answered an open stored object now answer the owner's content model.
    - `POST /projects/{id}/evidence` answers the stored `EvidenceItem` (`modeler_project.evidence`).
    - `POST datasets`, `datasets:digitize`, `datasets/{id}:overlay` and `datasets/{id}:reveal` answer the stored
      `ObservedDataset` (`modeler_project.datasets`).
    - The evidence page's items (`EvidencePage.evidence`, and `corrected` after a correction) are the same
      `EvidenceItem`.
    - `EvidencePage.datasets` stays an open row. Before the MAP is signed, an external study's row is redacted (D-15):
      it has no values and carries `blinded`, so it is not an `ObservedDataset`.
  - **Schemas:** `EvidenceItem`, `ObservedDataset` and `Digitization` mark their defaulted fields as always present
    in the answer schema, because they are always dumped whole (as the plan's models did in 9b).
    - `Series`, `ReportedPK` and `SourceRef` keep their defaults optional. They are request schemas too, and marking
      them would split each into an input and an output schema, renaming existing ones.
  - **`:reveal` reads through the owner:** it answers the dataset as `ObservedDataset` parses it, not the raw stored
    content. A dataset stored before a field existed now shows that field's default.
  - **Ratchet:** `[response] open` is empty, like `untyped`. Every JSON route of every router has a response model,
    and a new open or untyped route needs the owner's approval.
  - **Web:**
    - The evidence review uses the generated `EvidenceItem`, replacing its 25-line hand type.
    - The observed-data panel uses `ObservedDataset`, and narrows only the redacted list rows.
    - The digitizer and the reveal drop their casts.
    - `lib/api.ts` loses `apiGet`, `apiSend`, `apiUpload` and `serverRead`; nothing called them. `apiFile` stays for
      file downloads.
    - `test_web_client.py` fails if a removed helper comes back, or if the client exports a new function that takes
      a bare URL.
- **Why:** rules B2 and B6, plan `docs/plans/2026-10-09-phase-9-typed-api.md` step 9e, and the owner's decision that
  stored content in the contract reuses its owner's model.
- **Impact:**
  - **API contract change:** the OpenAPI snapshot gains 7 schemas: the 3 models, the `EvidenceState` and `Extraction`
    enums, and 2 envelopes.
    - `EvidencePage`, `EvidenceChoice` and `EvidenceCorrection` type their evidence items.
    - The unused open envelope `Envelope_dict_str__Any__` is gone.
    - `SourceRef`, `Series` and `ReportedPK` are unchanged.
  - The answers are unchanged, as the conftest guard checks, except that `:reveal` now fills defaults on an old
    dataset.
  - Phase 9 is done.

### Changed — the campaign monitor, the review inbox and the remaining routes are typed; every route has a model (architecture phase 9d; API contract)
- **What:**
  - **Shared records:** `modeler_storage.records` gains `CampaignRecord` (with `StageRecord`, `RoundRecord`,
    `RealDataSummary` and `EngineIdentity`) and `EscalationRecord` (with `EscalationOption`).
    - The orchestrator's runner writes them, and the API answers with them.
    - The runner now checks every monitor record and every escalation against these models before it writes. A key
      the model does not know fails the runner's own tests.
    - Each record is still stored exactly as the runner builds it, so the stored bytes are unchanged; metrics may
      hold NaN, which a re-dump would change.
    - Keys the monitor gained over time have defaults, so a record written by an earlier build still reads.
    - The monitor's science blocks stay open objects, each owned by its own module: the goodness-of-fit series, the
      S6 prediction, the S7 package record, the ledger, the influence map, the S5 diagnosis and the decisions.
  - **Typed routes:** the last 12 untyped routes declare response models (`views/campaigns.py`, `views/system.py`):
    - **From the read model:** campaigns, a campaign, its S7 package, the escalation inbox.
    - **No envelope, as before:** `map:generate` (the `MapDocument`), campaign start, signature, run results (one of
      two shapes).
    - **The system routes:** health, snapshot preview, M15 validation, run submission.
    - **New test:** a run submission's success path, which no test reached before.
  - **Ratchet:** `[response] untyped` is empty. The response test now counts a union of models as typed.
  - **Web:**
    - A typed `post` replaces `rawPost` for the routes that answer without the envelope. It wraps their answer in an
      envelope, so they compose with `useMutation`.
    - The campaign, round, stage, real-data, engine and escalation types are generated aliases. The science blocks
      are narrowed as the pages read them.
    - The escalation decision runs through `useMutation`.
    - `test_web_client.py` now also treats an answer without the envelope as typed.
- **Why:** rules B2 and B6, plan `docs/plans/2026-10-09-phase-9-typed-api.md` step 9d, and the owner's decision that
  records crossing a process edge get one model, written and read through it.
- **Impact:**
  - **API contract change:** the OpenAPI snapshot gains the 12 operations' response schemas and 37 schemas,
    including the MAP document's, and changes none.
  - The answers are unchanged, as the conftest guard checks.
  - Stored monitor records are byte-identical.
  - The 5 routes that answer an open stored object (`[response] open`) are next, in 9e.

### Changed — the project, CPF, study, template and guided-flow answers are typed (architecture phase 9c; API contract)
- **What:**
  - **Shared records:** a new `modeler_storage.records` holds `ProjectRecord` (with `QuestionRecord` and
    `BlindingChoice`) and `ProposalRecord`.
    - The read model's own records: the API writes the project, and the orchestrator reads it before an S4/S5 gate.
    - The three writers build through the record and store only the keys they set: create project, project start,
      and the model system and blinding updates. A key added or renamed on one side now fails that side's tests.
    - `modeler-storage` declares its `pydantic` dependency, which was already used through `pbpk-domain`.
  - **Typed routes:** 12 routes of `read_api`, `write_api` and `templates_api` declare response models (`views/read.py`,
    `views/write.py`, `views/templates.py`): projects, a project, the CPF view (GET and PUT), studies, proposals,
    templates, create project, the model system, the studies upload and `campaign:prepare`.
    - A study row is the upload's shape as stored for the project. A blinded row has no profile and carries
      `blinded`.
    - A template's CPF and studies stay open objects, because they are the template's own documents.
  - **Test fixtures:** they now store records in the real shape. Two fixtures had stored a project without
    `openQuestions` and `risk`, and study rows without a dose or profile times.
  - **Ratchet:** `[response] untyped` shrinks from 24 to 12, and the locked hash is refreshed.
  - **Web:**
    - `lib/reads.ts` reads the projects, project, CPF, studies and proposals with `serverGet`. `lib/writes.ts` sends
      the project writes by route.
    - `Project`, `Question`, `CpfParameter`, `Proposal`, `StudyRow` and the template types are generated aliases.
    - The new-project wizard reads the templates with `useResource`.
    - `RiskChip` shows any recorded rating, leaving one outside low/medium/high uncoloured.
    - The compound page passes the decoded compound to the typed client, which encodes it.
- **Why:** rules B2 and B6, plan `docs/plans/2026-10-09-phase-9-typed-api.md` step 9c, and the owner's decision to
  give records shared across a process edge one model.
- **Impact:**
  - **API contract change:** the OpenAPI snapshot gains the 12 operations' response schemas and 27 schemas, and
    changes none. The answers are unchanged, as the conftest guard checks.
  - **Known risk on deployed data:** a stored project or study row with a key the models do not declare now fails
    its read with a 500 that names the key, where it used to pass through.
    - Every writer since 2026-09-19 writes only declared keys: the project keys `exploratory`, `pipeline` and
      `blinding` are covered.
    - A row written by hand or by an older build would show up on the project list or studies page; fix such a
      row in `projects.json` / `studies.json`.

### Changed — the P5 model plan answers are typed, and the canvas reads them through the hooks (architecture phase 9b; API contract)
- **What:**
  - **API:** the 13 routes of `plan_api` declare response models (`modeler_api/views/plan.py`).
    - `PlanPage` is the plan page. Its `plan` is the owner's `ModelPlan` model (phase 9 decision: stored content is
      described by its owner's model).
    - The placement dry run answers `PlacementPreview`, `plan:sign` answers `PlanSigned` (the page plus its
      `signature`), and `plan:draft` answers `DraftStart`.
    - The plan's content models (`ModelPlan`, `Placement`, `FitChoice`, `Proposal`, `Structure`, `StudyView`,
      `Deviation`, `Violation`) mark a field with a default as always present in the answer schema
      (`json_schema_serialization_defaults_required`). The plan is always dumped whole, so the generated web types
      need no guards for those fields. Stored content and validation are unchanged.
    - A new test reaches every route no test had reached: `plan:view`, the dry run, fits set and removed, a structure
      choice, `plan:rebase` and `plan:draft`. The conftest guard checks each answer against the handler's own value.
    - `[response] untyped` in `boundaries.toml` shrinks from 37 to 24 routes, and the locked hash is refreshed.
  - **Web:**
    - `lib/plan.ts`: its hand-written types become aliases of the generated ones, and `planApi` calls each route by
      name, with the bodies checked against the request models.
    - `PlanCanvas` reads the plan with `useResource`, which also refreshes while A5 is drafting, and makes every change
      with `useMutation`. The dry run stays a plain call.
    - The blinding panel's change now reloads the plan as well.
    - Removed: the unused `planApi.get` / `unlock`, `ROLES` and `PlanEnvelope`.
- **Why:** rules B2 and B6, plan `docs/plans/2026-10-09-phase-9-typed-api.md` step 9b. The canvas mirrored the plan
  page by hand, and a renamed key would have passed every check.
- **Impact:**
  - **API contract change:** the OpenAPI snapshot gains the 13 operations' response schemas and 29 schemas. No
    existing schema, request or parameter changed. The answers are unchanged, as the conftest guard checks.
  - **Web behavior:**
    - After a change, the canvas reads the plan again; it used to take the change's answer.
    - The canvas now refreshes every few seconds while A5 drafts.
    - A dissolution profile with no release model now says so; the page assumed one.

### Changed — the response-model ratchet covers every router (architecture phase 9a; locked file, owner-approved)
- **What:**
  - **Ratchet coverage:** `tests/architecture/test_response_models.py` now checks every router.
    `[response] routers` in the locked `boundaries.toml` adds `plan_api`, `campaign_api`, `read_api`, `results_api`,
    `signatures_api`, `templates_api`, `write_api` and `system_api`.
  - **Untyped rule:** a route without a pydantic response model now counts as untyped. Only a handler annotated to
    return a `Response` (a file download) is exempt. Before, the test took any route without a response model for a
    file, so `read_api`, `templates_api` and the routes in `main.py` were never counted. The two download handlers
    that had no annotation (`documents/{sha}/raw`, `campaigns/{id}/package/{artifact}`) now say `-> FileResponse`.
  - **Open answers:** a second list, `[response] open`, records the routes typed only as an envelope of an open
    object (`Envelope[dict[str, Any]]`).
  - **Recorded lists:** today's 37 untyped routes and 5 open answers are written to `boundaries.toml`. Both lists only
    shrink. The locked hash is refreshed.
  - **`system_api` router:** the 4 routes that lived on the app in `main.py` (`/health`, `model-versions/preview`,
    `m15/validate`, `runs`) move unchanged to a new router, `modeler_api.system_api`, where the ratchet sees them.
- **Why:** rule B2 and the owner's decision of 2026-10-08 to type every remaining route (plan
  `docs/plans/2026-10-09-phase-9-typed-api.md`). Without these lists, nothing stopped a new untyped route in
  those routers.
- **Impact:** no behaviour change. The paths, handlers and answers are unchanged, and the OpenAPI snapshot is
  identical.

### Changed — one stylesheet per feature; phase 7 done (architecture phase 7d, CSS)
- **What:** `apps/web/app/globals.css` now holds only the base: tokens, type, layout, the shared components, and the
  few review classes several pages use (tabs, citations, editors, quotes, flags). Each feature's rules moved to their
  own file in `apps/web/app/styles/`: `campaign`, `pipeline` (the phase rail), `brief`, `evidence`, `client-data`,
  `plan` and `inputs`. The root layout imports them after the base sheet.
- **Why:** rule B6, plan step 7d. Every page's styles lived in one 470-line sheet, so a page's look could not be
  found or changed on its own.
- **Impact:** no visual change. All 277 rules are kept, none changed. The files load in the order the rules had in
  the single sheet, and the production build still emits one stylesheet in that order. Three rule pairs changed
  relative position; each pair shares only a modifier (`wide`, `muted`) under different anchors (`.rf` / `.flow-col`
  / `main`, `.problems` / `.dag-node-head`), so they never match the same element.

### Changed — the review pages read with `useResource` and change with `useMutation` (architecture phase 7d, hooks)
- **What:**
  - **Hooks:** `apps/web/lib/hooks.ts`, on `@tanstack/react-query`. It was already a dependency, unused until now, so
    no dependency is added. `components/Providers.tsx` gives the app one query cache per tab, with no retries and no
    refetch on window focus.
    - `useResource(route, params, { select, poll })` reads a typed route.
    - `useMutation().run(() => send(…))` makes a change. When it succeeds, the page's resources are read again and
      its server-rendered parts, the phase rail among them, are re-rendered.
  - **Pages moved onto them:** brief, data plan, document viewer, client data, sheet reader, literature evidence,
    observed data, digitizer, model inputs and the to-do list, and the blinding panel of the plan canvas. This
    replaces each page's own load / `useEffect` / `setInterval` / `router.refresh()` code. The plan canvas itself, the
    campaign pages and the escalation decision keep their own loading, because their routes are not typed yet.
  - **Removed:** `planApi.blinding` and the `Blinding` alias in `lib/plan.ts` (no caller left).
  - **Guard:** `tests/architecture/test_web_client.py` adds a check that only `lib/hooks.ts` imports the typed browser
    read `get`. A page that reads around the hooks fails.
- **Why:** rule B6, plan `docs/plans/2026-10-08-phase-7-frontend.md` step 7d. Each page hand-wrote fetch-then-refresh.
  The brief, data plan, evidence and observed-data pages never refreshed the phase rail, so it showed a status that
  their own change had made stale until the next navigation.
- **Impact (web only; no API change):**
  - A successful change on any of these pages now refreshes the phase rail.
  - A change is followed by a fresh read of the page's resources. Before, some pages used the change's answer
    directly; now there is one extra GET per change.
  - The observed-data and client-data pages now read again every few seconds while an agent runs, as the brief and
    evidence pages already did. Their datasets and sheet triage appear without a reload.
  - On the brief page, every change (not only extract and approve) disables the action buttons while it runs.
  - After a sheet is saved, the sheet reader shows that it was read before.

### Changed — the web app calls the API through one client, typed by route (architecture phase 7c)
- **What:**
  - **One client:** `lib/api.ts` is the only module that fetches. The transport that `lib/writes.ts` duplicated
    (`authed`, `failure`, `rawPost`, `apiGet` / `apiSend` / `apiUpload`) moved into it, and `lib/writes.ts` keeps only
    its domain calls. The browser bearer is `BROWSER_TOKEN` (was `WEB_TOKEN` in `lib/writes.ts`).
  - **Typed by route:** a call names its route as the contract does, `get("/api/v1/projects/{project_id}/brief",
    { project_id })`. The path parameters, the body and the answer type follow from the generated `paths`; `send`
    (POST / PUT), `upload` (multipart) and `serverGet` (server components) work the same way. Each parameter is
    URL-encoded.
  - **Pages moved onto it:** the brief, data plan, document viewer, client-data, sheet reader, evidence, observed data,
    digitizer, inputs and start pages, and `lib/pipeline.ts`. Request bodies are now checked against the request
    models (`OverrideRequest`, `ManualEvidence`, `DigitizeBody`, `ChoiceRequest`, `Decision` …), and the closed value
    sets a page sends come from the contract (providers, source types, decision states, choice kinds).
  - **Downloads:** `apiFile` replaces the three raw `fetch` calls (the package files, the client-data template, a
    stored figure).
  - **Still untyped:** routes the contract does not type yet (P5 plan, campaigns, CPF, projects, templates, the read
    API) keep `apiGet` / `apiSend` / `serverRead` with a hand-written answer type.
  - **Removed dead code** from `lib/api.ts`: `apiPost`, `apiPostAuth`, `createSignature`, `decideEscalation` (its body
    no longer matched the API), `SignaturePayload` and `QuestionStatus`. None had a caller.
  - **New guard** `tests/architecture/test_web_client.py`: no `fetch` outside `lib/api.ts`, and no call of an untyped
    helper on a route whose answer the contract types.
- **Why:** rule B6, one API client; plan `docs/plans/2026-10-08-phase-7-frontend.md` step 7c. Two transports had
  drifted (one without the bearer or error handling), and a page could call a route that does not exist or send a body
  the API rejects, which only the browser found.
- **Impact:**
  - No API change; the OpenAPI snapshot is unchanged.
  - A failed download now shows the API's own reason (or the HTTP status), like every other call. The digitizer now
    reports a failed figure fetch, where it tried to draw the error answer as an image.
  - `ArtifactView.content` may be null, as the contract states; the pages already read it with `?.`.

### Changed — the pages read every typed answer as its generated type (architecture phase 7b; API contract)
- **What:**
  - **Pages on generated types:** `lib/pipeline.ts`, the client-data, evidence, inputs and start pages, and the
    escalation resolve call now use the generated models (`Schema<…>`). Stored content inside an answer is typed with
    `Narrow<Schema<…>, {…}>`, which accepts only keys the answer has.
  - **Generation flag:** `--default-non-nullable false`, so a field with a default is optional in the generated types
    (request bodies, and answers sent with unset keys left out).
  - **Tightened API models:**
    - phase ids are `Literal["P0".."P6"]`;
    - phase and artifact statuses use their enums (`PhaseStatus`, `ArtifactStatus`);
    - change kinds are `added` / `removed` / `changed`;
    - dissolution `problems` are strings;
    - `RunSummary`'s keys are required, as `run_store.start_run` has always written them (`finished_at` stays null
      until a run ends).
  - The phase row model is renamed `PhaseStatus` → `PhaseRow`.
- **Why:** rules B2 and B6. Pages hand-wrote answer shapes the contract already described.
- **Impact (an API contract change for clients):**
  - The OpenAPI snapshot gains enum schemas (`PhaseStatus`, `ArtifactStatus`) and tighter field types, and renames
    the row schema to `PhaseRow`. The values sent are unchanged; the conftest guard compares every typed answer with
    the handler's return value.
  - The brief page's null guard from 7a is removed, now that `RunSummary` states what run records hold.
  - The campaign, results, read and plan pages keep hand-written types until those routers are typed.

### Added — the web app's API types are generated from the contract (architecture phase 7a; new dev dependency)
- **What:**
  - `openapi-typescript` is a new dev dependency of `apps/web`, pinned to exactly `7.13.0` (approved by the owner,
    2026-10-08). It generates code only and adds nothing to the app bundle.
  - `npm run api-types` writes `apps/web/lib/api-types.ts` from `docs/api/openapi.json`, and the file is committed.
  - `npm run typecheck` (the CI web job) first checks the file against the snapshot and fails while it is out of date.
    The OpenAPI contract test's message now says to regenerate both.
  - `Schema<"Name">` in `lib/api.ts` names a generated response model.
  - The brief page's answer types (`BriefView`, `DocumentView`, `Impact`) are now generated. The stored brief content
    stays hand-typed.
- **Why:** rule B2. The web app hand-wrote every answer's shape, and nothing checked those types against what the API
  sends. Plan: `docs/plans/2026-10-08-phase-7-frontend.md`.
- **Impact:**
  - The generated types surfaced one gap. The contract allows an agent run's `status` and `summary` to be null, and the
    brief page read them unguarded. The page is now null-safe.
  - No API change, and the OpenAPI snapshot is unchanged.
  - `npm audit` reports four findings in packages that were already in the lock file: `next` (moderate), and `postcss`,
    `sharp` and `source-map-js` (high). None comes from `openapi-typescript`. They are left for a separate change.

### Changed — only the owner modules read stored artifact content; C6 closed, phase 6 done (architecture phase 6f)
- **What:**
  - `modeler_project.documents` gains a `DocumentRecord` content model, which also writes, and `document_record()`.
    Document metadata (name, pages, hash, role, note) is read through it by `brief_api`, `evidence_api` and the
    agents `evidence_agent`, `observed_data_agent` and `proposal_intake`.
  - New owner accessors:
    - `client_data.submission`;
    - `dataset_register.dataset`;
    - `evidence_register.access_requests`;
    - `inputs.cpf_assembly`, `catalog_rows` and `readiness_report`.
  - `client_api`, `doctor`, `inputs_api`, `plan_api` and `project_api` use them, and so do `deps.model_risk` (through
    `plan.current`) and `blinding.external_studies` (through the plan and `dataset_register.datasets`).
- **Why:** coupling C6 and rule B3. A stored key was read in a dozen modules outside its owner, so changing it broke
  pages and agents nobody had touched.
- **Impact:**
  - No behaviour change: the API answers are unchanged (the conftest guard), the OpenAPI snapshot is unchanged, and
    the stored content is unchanged. A test shows a document's stored keys are the ones written before and read back
    through `DocumentRecord`.
  - `boundaries.toml` (locked): raw content reads go from 40 to 0, so `[owner_exceptions]` is empty, and the hash is
    refreshed. A new raw read or a write by a non-owner now fails CI without an approved entry.
  - Phase 6 is done: C5 and C6 are closed. Next is phase 7 (frontend seams); its `openapi-typescript` dependency is to
    be approved first.

### Changed — one writer per artifact kind; the MAP gets an owner module (architecture phase 6e)
- **What:**
  - **brief:** `modeler_project.brief_ops.save_brief` now writes it, taking over the five `ws.commit` calls in
    `brief_api` (project start, A1 extraction, edit, item removal, a question answered). Provenance is kept as before.
  - **cpf/published:** the hand-off record to the campaign path is written by `modeler_project.inputs.record_publication`
    and read by `publication`, through a `Publication` content model. `inputs_api.publish` calls it.
  - **map:** a new owner module, `modeler_project.map_artifact`, holds the `MapArtifact` / `MapSignature` content model
    and the functions `latest_map`, `signed_map` and `record_signed_map`.
    - `plan:sign` records the signed MAP through it.
    - The plan page's MAP block, `_signed_map` and `blinding.map_signed` read through it, instead of from the raw
      stored JSON.
    - MAP generation (`pbpk_domain.campaign.map`, locked) is untouched.
- **Why:** coupling C6 and rule B3. Before, a router wrote the MAP and blinding read its signature from raw JSON, so a
  change to one stored key could break a page nobody had touched.
- **Impact:**
  - No behaviour change: same answers (the conftest guard), and the same stored content.
  - New round-trip tests show that the MAP versions written by `plan:sign` and the hand-off record keep the keys the
    routers wrote, and read back byte for byte; the audit chain hashes content.
  - `test_map_artifact.py` covers the owner, including that an unsigned MAP gains no null keys.
  - `boundaries.toml` (locked): the three writer exceptions are gone. Raw content reads go from 48 to 40 (`plan_api`
    10 → 3, `blinding` 4 → 3), and the hash is refreshed.

### Changed — P4, project and escalation answers are typed; C5 closed (architecture phase 6d; API contract)
- **What:**
  - `modeler_api.views.inputs`, `views.project` and `views.escalations` hold the response models. They are declared
    by the 6 routes of `inputs_api`, the 9 of `project_api` (phases, artifacts, history, impact, audit, blinding,
    reveal) and the 5 escalation routes.
  - The escalation routes keep answering without the envelope, as the owner chose; they use
    `responses.answers_without_envelope`.
  - Every route of the guarded routers is now typed, so `[response] untyped` is empty. It stays in `boundaries.toml`,
    so a new route cannot answer untyped.
- **Why:** coupling C5 and rule B2, closed by this change.
- **Impact (an API contract change for clients):**
  - The OpenAPI snapshot gains the 2xx schemas of these 20 operations, plus 27 schemas. Nothing else changed.
  - The answers are unchanged; the conftest guard compares each one with the handler's return value.
  - The typing found a test fake of the campaign runner's `resolve` that answered only `{"status": …}`. The real
    `local_runner.resolve_escalation` always sends `campaign_id`, `stage` and `action`, so the fake now answers as the
    runner does.
  - A new test reaches `inputs:propose-identity`.
  - `boundaries.toml` (locked): `[response] untyped` goes from 20 to 0, and its hash is refreshed.

### Changed — P2/P3 answers are typed (architecture phase 6c; API contract)
- **What:**
  - `modeler_api.views.evidence` and `modeler_api.views.client_data` hold the response models. The 12 routes of
    `evidence_api` and the 8 JSON routes of `client_api` declare them; the template download answers with a file.
  - The merged answers are typed as they are, one model each, built by inheritance:
    - a value kept or corrected, plus the page;
    - files uploaded, plus the page;
    - a release model proposed, plus the page;
    - a confirmed sheet reading: preview, datasets and page. Where the preview and the page both name `dissolution`,
      the page's wins, as before.
  - An answer that is a stored artifact's content (an evidence item, a dataset) is typed as `StoredContent` until
    phase 6e gives its kind a content model.
- **Why:** coupling C5 and rule B2. This continues 6b, and the response shapes are kept, as the owner chose.
- **Impact (an API contract change for clients):**
  - The OpenAPI snapshot gains the 2xx schemas of these 20 operations, plus 34 schemas. Nothing else changed.
  - The answers are unchanged; the conftest guard compares each one with the handler's own return value.
  - New tests reach 4 routes no test had reached: `evidence:research`, `access-requests/{id}:fulfil`, the success
    path of `evidence:approve`, and `client-data/{id}:triage`.
  - `boundaries.toml` (locked): `[response] untyped` goes from 40 to 20, and its hash is refreshed.

### Changed — P0/P1 answers are typed: `Envelope[T]` and `modeler_api.views` (architecture phase 6b; API contract)
- **What:**
  - `modeler_api.responses` gains `Envelope[T]`, `Meta` and `ErrorItem`. `answers(Model)` gives a route its
    `response_model=Envelope[Model]` and `response_model_exclude_unset=True`.
  - New `modeler_api.views` holds the response models:
    - `common`: version, approval, impact, agents status, run summary, document;
    - `brief`: project start, documents, document page, the brief page with its catalog, an extraction start, a
      previewed edit, an agent run;
    - `requirements`: the data plan page.
  - The 11 JSON routes of `brief_api` and the 4 of `requirements_api` declare them. The raw document download stays
    untyped, because it answers with a file.
- **Why:** coupling C5 and rule B2. A renamed or dropped key in a page passed every check and failed in the browser.
  The owner chose to type today's shapes as they are (2026-10-08).
- **Impact (an API contract change for clients):**
  - The OpenAPI snapshot gains the 2xx response schemas of these 15 operations, plus 33 schemas. No request,
    parameter or existing schema changed.
  - The answers themselves are unchanged. A new guard in `services/api/tests/conftest.py` compares every typed answer
    in the API tests with the handler's own return value: a dropped, added or coerced value fails the test.
  - A new test reaches the 4 brief routes no test had called: document upload, `brief:extract`, `items:remove` and
    `questions/{id}`.
  - Models use `extra="forbid"`, so a handler that returns an undeclared key now answers 500 instead of passing it
    through untyped. The tests catch this before a release.
  - `boundaries.toml` (locked): `[response] untyped` goes from 55 to 40, and its hash is refreshed.

### Added — phase 6 guardrails: response models and artifact owners (architecture phase 6a)
- **What:** two shrink-only ratchets, with no code change.
  - `tests/architecture/test_response_models.py` covers every route of the P0–P4 routers and the escalation routes.
    Each route needs a pydantic response model, or must be listed under `[response] untyped` in `boundaries.toml`.
    Today that list holds 55 routes; the 2 file downloads are not counted.
  - `tests/architecture/test_artifact_owners.py`: `[owners]` names one module per artifact kind. Only that module
    commits the kind, and only owner modules read stored content raw. Today's exceptions are recorded:
    - 3 writers: `brief_api` (brief), `inputs_api` (cpf), `plan_api` (map);
    - 48 raw reads in 12 modules, as exact counts.
  - A new plan doc, `docs/plans/2026-10-08-phase-6-contracts.md`, covers 6a–6f.
- **Why:** rules B2 and B3, couplings C5 (untyped answers) and C6 (artifact content without an owner). The owner
  approved both ratchets on 2026-10-08, and chose to keep today's response shapes, typing them as they are.
- **Impact:**
  - No behaviour change.
  - `tests/architecture/boundaries.toml` (locked) gains the `[response]`, `[owners]` and `[owner_exceptions]`
    sections, and its hash is refreshed.
  - From now on, a new untyped route, a write by a non-owner, or a new raw content read fails CI, and so does a fixed
    exception that stays listed.
  - The `ARCHITECTURE_BOUNDARIES.md` guardrail table gains both tests; it also had a stray blank line that split it.

### Changed — services out of the routers (architecture phase 5d; phase 5 done)
- **What:**
  - Data-plan derivation moved from `requirements_api` (a router) to the project service
    `modeler_project.data_plan.derive_data_plan`. With no brief it raises `NoBriefError`, which the router turns into
    the same 404 ("no brief to derive the data plan from").
  - The study upload request models (`ObservedProfile`, `StudyUpload`, `StudiesUpload`) and the observed PK per
    profile moved from `write_api` to `modeler_api.studies`. The private `write_api._observed_from_studies` is now the
    public `studies.observed_from_studies`, and `deploy/reference/run_reference.py` imports it from there.
  - The project CPF view moved from `read_api` to `modeler_api.cpf_view`, and `read_api` re-exports it.
  - A new project-model test covers the service: the missing brief, overrides kept across re-derivations, and both
    artifacts derived from the brief.
- **Why:** couplings C3 and C4 (routers imported other routers for business logic). Plan:
  `docs/plans/2026-10-08-phase-5-services.md`.
- **Impact:**
  - No behaviour change: the same routes, models, artifacts and messages. The OpenAPI snapshot is unchanged, and
    `deploy/proof/run_t56.py` is unchanged.
  - `tests/architecture/boundaries.toml` (locked) drops the last 4 router exceptions (8 → 4), and its hash is
    refreshed. None of the router or seam kind remain.
  - Phase 5 is done: exceptions went 35 → 4. What remains is the orchestrator's engine import (an engine port) and 2
    package tests.

### Changed — deterministic helpers out of the agents package; one list of recipe constant keys (architecture phase 5c)
- **What:**
  - The quote check moved from `modeler_agents.citations` to `modeler_intake.citations`, unchanged.
  - The deterministic half of the data-mapping agent moved to `modeler_intake.recipe_review`, unchanged: the proposal
    models, `to_recipe`, `check_evidence` and `review_proposal`. `modeler_agents.data_mapping` keeps the prompt and
    `propose_mapping`.
  - Recipe constant keys (C9) now have one owner: `modeler_intake.recipe.ConstantKey`, `CONSTANT_KEYS` and
    `NUMERIC_CONSTANTS`. The review, `apply` and the recipe's schema text read them, and a test keeps the sheet form's
    keys inside them.
  - The agents package declares `pbpk-domain`, which it already imported (`CPF`, `Issue`). It is a workspace package
    that was installed through `modeler_intake`, so this adds no new third-party dependency; `uv.lock` gains two lines.
- **Why:**
  - Couplings C4 and C9: the API imported deterministic code from the agents package, and four modules each listed the
    constant keys.
  - Deviation from the plan: the quote check went to `modeler_intake`, not `modeler_project`. The recipe review (L2)
    needs it, and L2 cannot import L3.
  - Plan: `docs/plans/2026-10-08-phase-5-services.md`.
- **Impact:**
  - No behaviour change: the same checks, messages and records. The proposal's JSON schema that the model is given is
    unchanged, and so is the OpenAPI snapshot.
  - `tests/architecture/boundaries.toml` (locked) drops 3 exceptions: the 2 seam exceptions (`citations`,
    `data_mapping`) and the `declared` agents → `pbpk_domain` one. That leaves 11 → 8; its hash is refreshed.
  - The tests moved with the code: `data-intake` has `test_citations.py` and `test_recipe_review.py`. The agents'
    `test_data_mapping.py` checks only the agent's own work.

### Changed — every agent job reaches the agents through `modeler_api.agent_jobs` (architecture phase 5b)
- **What:**
  - `modeler_api.agent_jobs`, the declared seam, is now the only API module that imports `modeler_agents` (bar the two
    deterministic helpers that move in 5c). It gives the routers:
    - the configured model: `chat_model`, `require_chat_model`, `agents_status`;
    - the run records: `AgentRun` (start, log each step, finish), `project_runs`, `run_record`, `run_steps`;
    - one entry point per agent: A1 `proposal_intake`, A2/A3 `literature_research`, A4 `sheet_triage`, A5 `planning`.
  - `brief_api`, `client_api`, `evidence_api` and `plan_api` call these instead of importing `modeler_agents.llm`,
    `run_store` and the agent modules. Four copies of the run-record bookkeeping (start, step counter, finish) and of
    the "agents off" 409 became one each.
  - The seam imports `modeler_agents` only when called, as before, so an API with agents off does not load the
    provider SDKs.
- **Why:** coupling C4 and rule B4 (the HTTP layer depended on the agents package's modules). Plan:
  `docs/plans/2026-10-08-phase-5-services.md`.
- **Impact:**
  - No behaviour change: same routes, run ids, actors (`agent:<run_id>`), step sequence, summaries and 409 messages.
    The run detail still reads a run's steps only after checking the run belongs to the viewer's project and tenant.
    The OpenAPI snapshot is unchanged.
  - `tests/architecture/boundaries.toml` (locked) drops the 14 seam exceptions that no longer occur (seam 16 → 2;
    25 → 11 overall), and its hash is refreshed.
  - `make test` shows only the 15 known environment failures.

### Changed — routers share `modeler_api.deps`, not each other (architecture phase 5a)
- **What:**
  - New `modeler_api.deps`, a module that defines no route. It holds what every phase router imported from
    `project_api` (a router): roles, the project store dependency, `workspace_for`, `parse_kind`, `version_view`,
    `impact_view`, and the blinding views (`blinded_studies`, `redact`, `hidden_paths`, `blinding_view`,
    `project_record`, `model_risk`).
  - `agents_status` moved from `brief_api` to `modeler_api.agent_jobs`, the declared seam to the agents package.
  - The routers now import from these two modules. `project_api` re-exports `get_project_store`, so
    `app.dependency_overrides[project_api.get_project_store]` still works.
- **Why:** coupling C3 (`project_api` was a hub; routers imported routers). Plan:
  `docs/plans/2026-10-08-phase-5-services.md`.
- **Impact:**
  - No behaviour change: same routes and models (the OpenAPI snapshot is unchanged).
  - `tests/architecture/boundaries.toml` (locked) drops the 10 exceptions that no longer occur (router 14 → 4; 35 → 25
    overall), and its hash is refreshed.
  - `make test` shows only the 15 known environment failures.

### Changed — one default per MODELER_* variable; a production deployment must set them
- **Decided by the owner on 2026-10-08.** Closes the "one variable, several defaults" known gap. Everything lives in
  `modeler_contracts.runtime`.
- **Development defaults:**
  - **Object store:** `LOCAL_OBJECT_STORE` in the API and the orchestrator alike. Before, the API defaulted to
    `s3://modeler-dev`, so the two disagreed.
  - **Engine command:** the local runner's default is now the stub engine, labelled a software fixture on every page.
    Before, it was `Rscript run_job.R`.
  - **Engine id:** the engine names itself: `ospsuite-12.4.4` for PK-Sim (from the qualified catalog, kept equal by a
    test) and `software-fixture:stub_engine` / `:analytical_engine` for the fixtures. Before, it was `local` /
    `unknown`. No record of a fixture run names PK-Sim.
  - **Digest:** the all-zero placeholder. Before, it was `local`, `unknown` or empty depending on the module.
- **Production (`MODELER_DEPLOYMENT=production`):** the API (lifespan), the local runner CLI and both Temporal
  workers refuse to start unless the object store, the engine command and a real digest are set.
  - Accepted digests are `sha256:<hex>` (a container image) and `catalog:sha256:<hex>`.
  - The placeholder and malformed values are refused.
  - An unknown `MODELER_DEPLOYMENT` value is refused.
- **The server (`deploy/server/_env.sh`)** is now a production deployment.
  - It records `MODELER_IMAGE_DIGEST=catalog:sha256:<digest of golden/catalog.json>`, the same hash the engine
    registration records as `catalog_sha256` (today `4ae49f74…`). This server runs PK-Sim from its own installation,
    not the published image, so recording the image's digest would name an engine the run never used.
  - Before, it recorded the all-zero placeholder.
- **Impact:**
  - Development runs that relied on the implicit `Rscript run_job.R` now run the stub: set `MODELER_ENGINE_COMMAND` to
    use PK-Sim (the server and the Mac docker flow already do).
  - Memoized engine runs are keyed by the digest, so the server re-runs once after the change instead of reusing
    entries recorded under the placeholder.
  - The server still runs with `MODELER_DEV_AUTH=1` (single node, no Keycloak). Production does not refuse dev auth
    yet; that needs its own decision.
- **Tests:**
  - `packages/run-contracts/tests/test_runtime_defaults.py`: defaults, production refusals, engine ids;
  - `tests/architecture/test_engine_identity.py`: the qualified engine id equals the catalog's, the API and
    orchestrator share one object-store default, and the server's computed digest equals the registration's;
  - `services/api/tests/test_production_start.py`: the API does not start in production without its settings;
  - the orchestrator's development and production engine defaults.
### Infra — the web fonts are self-hosted (no request to Google at build or run time)
- **What:** IBM Plex Sans (variable, weights 400–600) and IBM Plex Mono (400, 500) are now loaded with
  `next/font/local` from `apps/web/app/fonts/`, instead of `next/font/google`.
  - Files: the Latin `.woff2` files Google Fonts serves for these families (Sans v23, Mono v20) and the licence, SIL
    Open Font License 1.1 (`OFL.txt`, IBM's text from github.com/IBM/plex).
  - No npm package is added.
  - sha256: Sans `e2291e84…`, Mono 400 `08949f72…`, Mono 500 `01d28544…`.
- **Why** (the owner's decision, 2026-10-08):
  - the web CI job failed once when the Google Fonts download did;
  - the server and the app no longer depend on a third-party request;
  - every build uses the same font files, which matters for a reviewable, reproducible package.
- **Impact:**
  - Same typefaces, weights, CSS variables (`--font-sans`, `--font-mono`) and `display: swap`.
  - The production build references only `/_next/static/media/*.woff2`, with no Google URL.
  - `npm run typecheck` and `npm run build` pass.

### Science — total hepatic clearance is placed, the EHC fraction says why it is not (registry 1.1, phase 4e)
- **Decided by the owner on 2026-10-08.** The parameter registry
  (`pbpk_domain/parameters/registry.yaml`, SME content) goes from 1.0 to 1.1 and stays UNVERIFIED pending SME
  sign-off.
- **(a) `elim.hepatic.total_cl` is an alias of `elim.hepatic.total.plasma_clearance`:**
  - **Why:** a value under `total_cl` satisfied S0's elimination requirement while nothing placed it, so a model could
    start with no clearance.
  - **Now:** a value under `total_cl` is filed under the id PK-Sim's `LiverClearance` "Plasma clearance" is bound
    to, which is harvested and in ml/min/kg. The canonical id converts to ml/min/kg as well, and S0's message names
    it.
  - MS-01 §2.2's `total_cl` row is unchanged and stays valid through the alias.
- **(b) `elim.ehc_fraction` is refused with its reason:**
  - **Why:** MS-01 places it on the Individual (`Organism|Liver|EHC continuous fraction`), and that path is not
    harvested yet.
  - **Before:** the value went into the CPF unbound, and the reason given was the misleading "no harvested PK-Sim
    process".
  - **Now:** it is kept out of the CPF with the real reason, in P4's to-do list and in target corrections.
  - The data plan still asks for it. Harvesting the path from a real exported simulation on the server is the follow-up.
- **(c) A total hepatic clearance is recorded `InVivo`:** `elim.hepatic.total.*` and the alias get the ValueOrigin
  method InVivo, because MS-01 gives the source as clinical. Enzyme CLspec, Km and Vmax stay InVitro.
- **Code:**
  - `pbpk_domain.parameters` gains `alias_of` / `refused` (validated), `canonical()` and `refusal()`;
  - `placement` and `process_bindings.binding_candidates` resolve aliases;
  - `modeler_project.inputs` files an alias under its canonical id and reports a refusal.
- **Tests:**
  - evidence under `total_cl` lands in the CPF as `elim.hepatic.total.plasma_clearance`, 0.3 l/h/kg → 5 ml/min/kg,
    bound to `LiverClearance`, InVivo;
  - an `ehc_fraction` value is refused with its reason;
  - a CPF whose only pathway is total plasma clearance passes S0, and the software builder places `LiverClearance`
    with nothing unplaceable;
  - the vocabulary test's `total_cl` xfail is removed; the `ehc_fraction` xfail stays, with the new reason.
- **Characterization snapshot (`docs/architecture/parameter-vocabulary.json`), reviewed diff:**
  - `total_cl`: placement and binding;
  - `total.plasma_clearance`: storage unit;
  - `elim.hepatic.total.*`: InVivo;
  - `ehc_fraction`: refusal text;
  - the S0 message, and the two new table entries.
- **Impact:** a compound described by its total hepatic clearance now gets that clearance in the model. A result
  counts only on real PK-Sim: building such a CPF on the server's PK-Sim is the follow-up.

### Changed — the locked consumers read the parameter registry (architecture phase 4d)
- **What** (locked files, approved by the owner 2026-10-08):
  - `pbpk_domain.parameter_units`: `_TARGETS = parameters.storage_targets()`, and `target_family` delegates to
    `parameters.storage_family`, which includes the suffix rules for CLspec, Km and Weibull shape;
  - `pbpk_domain.pksim_paths`: `_COMPOUND_PARAM = parameters.compound_parameters()`, with the same harvested names;
  - `pbpk_domain.cpf.build`: `_PROCESS_FAMILIES` and `REFERENCE_ELIMINATION` come from the registry.
- **Kept in `parameter_units`:** the unit-alias tables, and the CLspec `ConversionError` message. That message covers
  every `.clspec` id without a storage unit (e.g. `transp.<t>.clspec`), not just the registry's `elim.hepatic` rule,
  so moving it would have changed what those ids answer.
- **Impact:**
  - No hand-kept copy of a CPF id table is left in code (C1). The AST guard in
    `tests/architecture/test_parameter_registry.py` now covers these three tables as well.
  - No behaviour change: the characterization snapshot is unchanged.
  - Only the three files' hashes moved in `docs/architecture/locked-files.json`.

### Changed — the unlocked consumers read the parameter registry (architecture phase 4c)
- **What:** these consumers now read `pbpk_domain.parameters` instead of keeping their own copies:
  - **`modeler_project.inputs`:** model and reference ids and prefixes, the builder unit, the ValueOrigin in-vivo /
    in-vitro prefixes, and `placement()`, which delegates to `parameters.placement`;
  - **`modeler_project.evidence`:** physical bounds, and `numeric_target` via `parameters.storage_family`;
  - **`pbpk_domain.cpf.completeness`:** `check_completeness` collects the ids with a value and provenance and reports
    `parameters.unmet_s0` (messages and ids from the registry's S0 list);
  - **`pbpk_domain.cpf.process_bindings`:** `is_process_id` uses the registry's process families.

  The module-level names stay, because other modules and tests import them.
- **Guards:**
  - An AST test fails if a switched table is written as a literal again.
  - A test checks that the blank template's parameters (`templates_api._BLANK_PARAMETERS`) meet every S0 requirement.
    That table stays a template's choice: neutral pKa, and total hepatic clearance bound as the OSP models bind it.
- **Why:** coupling C1. An id added to one copy and not the others once produced a model without the value.
- Impact: none on behaviour. The characterization snapshot (`docs/architecture/parameter-vocabulary.json`), the 4b
  equality tests and the phase 1 vocabulary test (with its strict xfails for the drift) are unchanged and pass.
  `make test`: 15 failures, all known to this environment (14 Temporal test-server downloads, 1 vault-permission test
  when run as root); they pass in CI. Still on copies: the locked `parameter_units`, `pksim_paths` and `cpf.build`
  (4d, with the owner's approval).

### Science (governance) — one CPF parameter registry, v1.0 UNVERIFIED (architecture phase 4b)
- **What:** a new SME-governed data file, `packages/pbpk-domain/src/pbpk_domain/parameters/registry.yaml` (v1.0,
  `UNVERIFIED`, locked as SME content; approved by the owner 2026-10-08). For every CPF id or id family it states:
  - placement (model / reference / process family);
  - storage unit;
  - PK-Sim compound parameter (harvested);
  - builder unit;
  - review bounds;
  - ValueOrigin method family;
  - the S0 gate's requirements and messages.

  Its loader, `pbpk_domain.parameters` (frozen pydantic, validated), answers the questions the scattered tables answered
  and derives each of them.
- **No new science:** the content is the code tables of 2026-10-08 moved over unchanged. No id, unit, bound or fit
  stage is added. Process parameter names and units stay in the harvested process table. The known drift is
  reproduced as is, with a `drift:` note naming the science PR 4e:
  - `elim.hepatic.total_cl` converts and satisfies S0, but has no placement;
  - `elim.ehc_fraction` converts, but has no placement.
- **Proof:**
  - `packages/pbpk-domain/tests/test_parameter_registry.py`: `parameter_units._TARGETS` exactly (and
    `target_family` over a corpus), `pksim_paths._COMPOUND_PARAM`, `build.REFERENCE_ELIMINATION` /
    `_PROCESS_FAMILIES`, `is_process_id`, the S0 report of `check_completeness` (messages, ids, and what each id or
    combination satisfies), the IVIVE reason, and schema validation.
  - `tests/architecture/test_parameter_registry.py`: the `modeler_project.inputs` and `evidence` tables, and, for all
    101 ids of the 4a snapshot, placement, storage family, process id, bounds, ValueOrigin method, S0 and compound path.
  - In total, 340 tests. Changing two entries in a scratch copy made 11 of them fail.
- Impact: none on behaviour. No consumer reads the registry yet (4c: unlocked consumers; 4d: the locked ones, their own
  PR). The characterization snapshot is unchanged.

### Infra — the parameter vocabulary is recorded before the registry replaces it (architecture phase 4a)
- **What:** `tests/architecture/test_parameter_characterization.py` records the snapshot
  `docs/architecture/parameter-vocabulary.json`, which holds two things:
  - **24 tables:** storage units, unit aliases, PK-Sim compound names, process prefixes, reference elimination,
    alternatives, model and reference ids, placeholders, pathway targets, in-vivo/in-vitro prefixes, physical bounds,
    the MAP's fit candidates, and the blank template's parameters;
  - **101 ids, with what each vocabulary function answers:** placement, target problem, storage family and conversion,
    numeric, process id, binding candidates, compound path, bounds, ValueOrigin method, and the S0 requirement satisfied.

  The ids come from the tables, the harvested process table, the requirement templates, the MAP, MS-01 §2.2, and edge
  probes.
- **Why:** phase 4 derives these tables from one registry (plan `docs/plans/2026-10-08-parameter-registry.md`). Every
  refactor step must leave the answers unchanged. Only the science PR changes them, with the owner's approval, and
  its snapshot diff is the review.
- **Already visible in the snapshot:**
  - `elim.hepatic.total_cl` satisfies S0's elimination requirement but has no placement.
  - `elim.ehc_fraction` converts but has no placement.
  - `value_origin_method` files total hepatic plasma clearance as `InVitro`, while MS-01 gives its source as clinical.

  All three are for the science PR (4e).
- Impact: none on behaviour (tests and docs only). No locked or SME-governed file changes.

### Fixed — the qualified engine image is published from `main` (it never had been)
- **What broke:** on every `main` push the Engine image workflow qualified the image (golden round trip, fitting smoke,
  engine tasks, benchmark all pass) and then failed at "Push image by digest" in under a second. The image name is
  `ghcr.io/${{ github.repository }}/modeler-engine`, i.e. `ghcr.io/ayush-1610/Modeler_One_AI/…`; Docker refuses
  upper-case repository names (`invalid reference format: repository name … must be lowercase`), so `docker tag` failed
  before anything was pushed. The SBOM, cosign signature and `engine_images` registration record after it had never
  run, although T-12 was marked done.
- **Change** (locked file `.github/workflows/engine-image.yml`, approved by the owner 2026-10-08): the push step
  lower-cases the name (`ghcr.io/ayush-1610/modeler_one_ai/modeler-engine`); the registration record step runs from the
  locked workspace with uv 0.5.11 (`uv run --frozen --package modeler-engine-worker`, as CI does) instead of a bare
  `pip install` into the runner's system Python. The qualification gate, and what a pull request runs, are unchanged.
- **Checked here:** the Docker CLI rejects the old name and parses the new one; the record step's command, run verbatim
  with uv 0.5.11 on the real `golden/catalog.json`, prints a `BUILT` record (`ospsuite-12.4.4`, snapshot version 80).
- Impact: the next `main` push touching the engine publishes the qualified image by digest, with SBOM, keyless cosign
  signature and registration record as workflow evidence. Nothing references the GHCR name yet (deploy and dev scripts
  use the local `modeler-engine:ospsuite-12.4.4` tag).
- **Confirmed on `main`** (`542e78d`, Engine image run 37741579858): qualification, push, SBOM, cosign and the
  registration record all passed. Published as `ghcr.io/ayush-1610/modeler_one_ai/modeler-engine@sha256:9f5e14e6…8998a12`
  (full digest in `docs/CONTINUATION_PACKAGE.md` §4.3, T-12).

### Changed — storage out of the API; the API and the orchestrator no longer import each other (architecture phase 3b)
- **Why:** the orchestrator imported the API package for its file read model and database repositories (declared as a
  dependency), while the API lazily imported the orchestrator to start and resolve campaigns: neither could change
  alone, and storage changes needed edits in both (coupling C7).
- **Moved unchanged** into `modeler_storage` (L2): `filestore` (campaign/project/CPF read model), `db` (models,
  repositories, session) and `tenancy`; only import paths changed. All importers in the repository were updated (API
  routers and tests, orchestrator, `deploy/reference/run_reference.py`); no compatibility shims.
- **Port:** `modeler_contracts.ports.CampaignRunner` names the five operations the API needs (start, the signature gate,
  the feedback guardrails, the decision digest, resolve); `modeler_orchestrator.campaign_runner.LocalCampaignRunner`
  forwards to the existing functions; the API obtains it only in `modeler_api.execution` (`runner: RunnerDep`), and
  tests override `get_campaign_runner` instead of patching `_launch_local_campaign` (removed).
- **Packages:** the orchestrator depends on `modeler-storage` instead of `modeler-api`; the API now declares
  `modeler-storage`, `modeler-orchestrator` and `modeler-intake` (it already imported them). The two whole-stack tests
  (`test_guided_flow_integration`, `test_model_system_campaign`) moved to the API's tests.
- **Guardrails:** 13 recorded boundary exceptions are gone (48 → 35); the ratchet test confirms none is left stale.
- Impact: no behaviour change (same code paths, same files and tables, OpenAPI snapshot unchanged).

### Changed — the Postgres audit trail moves to the new storage package (architecture phase 3a)
- **What:** new workspace package `modeler_storage` (L2, `packages/storage`, depends on SQLAlchemy only). The Postgres
  audit trail `modeler_api/compliance/audit.py` moves there as `modeler_storage/audit.py`, **byte for byte**: its
  sha256 (`956009f7…`) is the same before and after, and `test_compliance` still proves the JSONL and Postgres chains
  hash identically. Importers updated (`modeler_api.db.repositories`, three API tests); the API declares the package.
- **Why:** phase 3 moves the persistence the orchestrator needs out of the API package; the database repositories use
  this audit trail, so it moves first. It is a locked file, so it moves alone in its own PR, with the owner's approval.
- **Locked-file records:** the manifest's audit pattern follows the file (layer L6 → L2); the docstring of the locked
  `modeler_project/audit.py` names the new path (one line); `boundaries.toml` places `modeler_storage` on L2.
- Impact: none at run time (same code, same hashes, same tables); `uv.lock` gains the workspace package only.

### Changed — configuration is read in one place per process and injected (architecture phase 2)
- **Why:** configuration was read in ~20 modules. API tests patched `get_settings` router by router, so a router that
  started reading a setting in a new helper broke other routers' tests; the orchestrator and engine read 15 `MODELER_*`
  variables straight from `os.environ` in 10 modules.
- **API:** `modeler_api.config` is the only reader (`Settings`; new fields `image_digest`, `logs`, replacing the direct
  reads in `write_api` and the doctor). Routers and dependency providers receive it as `settings: SettingsDep`; the
  helpers below a view that still call `get_settings()` (blinding's project record, `plan_api._exploratory`) see the
  same object, until phase 5 makes blinding a service. `use_settings` / `reload_settings` replace patching in tests:
  `services/api/tests/conftest.py` gives an `api_settings(...)` fixture and re-reads `MODELER_*` before each test.
- **Orchestrator and engine worker:** `modeler_contracts.runtime.runtime_env()` reads every `MODELER_*` they use, on
  each call; every call site keeps its default exactly (`get(name, default)`, `require(name)` → `KeyError` as before).
- **Guardrail:** `tests/architecture/test_config_reads.py` fails when a module outside `[config]` in `boundaries.toml`
  reads the environment or a test patches `get_settings`. `boundaries.toml` (locked) gains the `[config]` list,
  approved with the phase 2 plan; its hash is refreshed.
- **Deviation from the plan, recorded:** threading settings through every `_view` (about 35 call sites) is left to
  phase 5, and `main.py` keeps one import-time read for CORS (uvicorn imports `modeler_api.main:app`); a `create_app`
  factory needs `main`'s own endpoints moved into a router first (phase 5).
- **Known gap — one variable, several defaults** (unchanged; the owner decides): `MODELER_OBJECT_STORE_URI`
  (orchestrator `file:///tmp/modeler-object-store`, API `s3://modeler-dev`), `MODELER_IMAGE_DIGEST` (`local`,
  `unknown`, empty, `sha256:` + zeros), `MODELER_ENGINE_COMMAND` (`Rscript run_job.R`, `Rscript /engine/run_job.R`),
  `MODELER_ENGINE_ID` (`local`, `unknown`).
- Impact: no behaviour change (same variables, same defaults; the OpenAPI snapshot is unchanged). 819 tests pass.

### Fixed — the engine image builds again on the qualified ospsuite 12.4.4
- **What broke:** the OSP r-universe serves only its newest build. Since ospsuite 12.4.5 replaced 12.4.4 there, the
  engine Dockerfile's version check stopped every build ("engine versions differ from the qualified set"), on `main`
  and on every PR touching the engine.
- **Change** (locked file `services/engine-worker/Dockerfile`, approved by the owner): ospsuite 12.4.4 is installed from
  its release commit (`4f37d444…`, "Release 12.4.4", OSPSuite-R #1995), whose source ships the .NET and native
  libraries in `inst/lib`; the source tree's `.Rprofile` (renv) is removed before `R CMD INSTALL`. The other packages
  still come from the r-universe; rSharp stays on its 1.2.2 tag; the version check is unchanged.
- **Both versions were qualified in CI on real ospsuite** (image build, golden round trip, fitting smoke, engine tasks,
  benchmark; PR #4 for 12.4.4, trial PR #5 for 12.4.5): both pass, and the parameter-identification smoke gives the same
  numbers on both (objective 6.571829 in 41 evaluations; Lipophilicity −1.281569, TSspec 0.795285 1/min).
- **Kept 12.4.4:** it is the qualified engine the server runs, and the version `golden/catalog.json`, every MAP's
  `software_versions` and the harvested PK-Sim paths name; 12.4.5 would change all of them for no numerical difference
  (its notes: an rSharp ≤ 1.2.3 pin and plot legend order). 12.4.5 is a verified, no-change upgrade candidate.
- The release archive is pinned by its sha256 (`87f9fb38…9efb05`, from the first qualified build), checked before
  installing.
- Impact: no engine change; the qualification gate runs again.

### Infra — architecture guardrails (phase 1): layers, API contract, parameter vocabulary, locked files
- **Why:** changes to agents and pipeline pages kept breaking unrelated code (the T-56 kit twice from P4 evidence
  checks, the MS-01 study record from a study "purpose", a count shown as `[object Object]`, an id outside the
  builder's vocabulary passing S0). Nothing enforced which package may use which. `docs/ARCHITECTURE_BOUNDARIES.md`
  draws the layers L0–L7, the rules, the coupling map and phases 2–8; `tests/architecture/` enforces them.
- **Added** `test_import_boundaries.py`: imports point down only (lazy imports count), every workspace import is a
  declared dependency, the API reaches the orchestrator / agents through one seam module each, routers do not import
  routers, package tests obey the layers. Today's 48 exceptions are listed with reasons in
  `tests/architecture/boundaries.toml`; a new violation fails, and so does an exception that no longer occurs.
- **Added** `test_openapi_contract.py`: the API's OpenAPI document must equal `docs/api/openapi.json` (87 paths,
  113 schemas); an intended contract change rewrites it (`UPDATE_SNAPSHOTS=1`) with a CHANGELOG entry.
- **Added** `test_parameter_vocabulary.py`: the CPF id lists in `parameter_units`, `pksim_paths`, `cpf.build`,
  `cpf.completeness`, `modeler_project.inputs` and `modeler_project.evidence` stay consistent until the phase 4
  registry. **Known gap** recorded as strict xfail: `elim.hepatic.total_cl` and `elim.ehc_fraction` convert to a
  storage unit but nothing places them, and S0's message still offers `elim.hepatic.total_cl` (science fix in phase 4,
  with the owner's approval; no behaviour changed here).
- **Added** locked files (approved by the owner): `docs/architecture/locked-files.json` lists 30 patterns (69 files:
  SME-governed rulesets, requirement templates, MS-01; core CPF schema and builder, harvested names and units,
  acceptance / MAP / split / diagnostics / M15 / reproducibility, both audit chains, signatures, auth, migrations,
  engine scripts / golden / image, CI, `CLAUDE.md`, the boundary exceptions) with their SHA-256;
  `test_locked_files.py` fails on any change. `CLAUDE.md` gains a "Boundaries and locked files" section.
- **Added** CI jobs `web` (`npm ci`, typecheck, production build — the web app was never built in CI) and
  `api-image` (build, import check, `/health`).
- **Fixed** `services/api/Dockerfile` installed 3 of the packages the API imports, so the image could not start; it
  now installs the locked workspace like the server (`uv sync --frozen --no-dev --all-packages`, uv pinned to CI's
  0.5.11). Checked in a scratch copy: every package installs, `modeler_api.main` imports, `/health` answers.
- **Fixed** the CI secret scan, red on `main` since the 2026-10-07 merge: gitleaks read `key="elim.hepatic.CYP3A4"` in two
  tests as an API key. `.gitleaks.toml` keeps the default rules and allows a finding only when the "secret" is a
  dotted CPF id.
- Impact: no application behaviour changed. New boundary violations, contract changes and locked-file edits now
  fail `make test` and CI instead of surfacing in an unrelated feature.

### Infra — every branch merged into `main`; `main` is the one integration branch
- 2026-10-07: GitHub `main` (62bceff, 24 Sep) was 85 commits behind the work, which lived on `main-1czavz` and
  `claude/amazing-newton-2phig7`, with the atomic-write fix on `claude/vbe-template`. All were merged (no conflicts;
  786 tests pass) and `main` fast-forwarded to the result; the server is deployed from it. `main-1czavz` and
  `claude/vbe-template` are deleted; `claude/amazing-newton-2phig7` stays until its session finishes, then merges in.
- `CLAUDE.md` now says: branch from `origin/main`, merge back into `main`, deploy only from `main`.

### Fixed — a campaign's JSON is never read half written, and a started campaign is readable at once
- **Atomic writes** (`pbpk_domain.atomic_io`: temporary file in the same directory, `fsync`, `os.replace`). The
  single-node runner rewrites `campaigns.json` from its own thread while the API serves it; a plain `write_text`
  truncates the live file first, so a GET could read it empty (`JSONDecodeError: Expecting value`, the T-56 kit test
  about 1 run in 6–8). Every JSON or file the API reads while a campaign runs now goes through it: the file store
  (`_write_json`, `materialize` — campaigns, escalations, projects, studies, CPF, systems, staged inputs), stage
  evidence, S6 results, the package record and zip, the rendered MAR (`mar.md`; pandoc's `mar.docx` and Typst's
  `mar.pdf` are rendered to a temporary file and swapped in only on success), fit specs and fitted-CPF versions,
  feedback-cycle and joint MAPs, and the run memo (which was already replaced atomically, now also `fsync`-ed). The
  reader has no retries.
- **The first campaign record is written before its id is returned** (`local_runner.start_campaign`, used by
  `POST /projects/{pid}/campaigns`). The id was handed out while the runner thread had not yet written anything, so a
  GET right after the start could 404 (`KeyError: 'data'` in the same test, about 1 run in 30). The record now exists,
  as QUEUED, when the start returns.
- `test_t56_kit.py`: 40 of 40 runs pass (before: 1 failure in 6–8). `make test` 777 passed, lint clean.
- **Known gap, not changed here:** the project store (`modeler_project.store.put`) creates an artifact version file and
  then fills it, so the API can read an empty version while an agent job (A1/A2/A4/A5) writes one; and the file
  store's read-modify-write upserts are not locked, so two writers in one process could lose an update.

### Changed — reference checks run on the server; the PK-Sim workflow is manual
- `.github/workflows/reference-models.yml` no longer runs on push (only "Run workflow" by hand): the reference set runs
  on the server's PK-Sim (`bash deploy/reference/run_all.sh`), and the repository goes private. Last full run on
  Actions (run 35, da2b2c8): every round-trip pair identical, within 1e-3 of the peak, or labelled by design;
  Ketoconazole's parent-only curves 90–100 % of the published (2 % before its compound settings).

### Fixed — compound settings beyond MW and halogens; the water of administrations given together (run 33)
- A compound's other parameters in the published snapshot are imported by their PK-Sim name and unit (`cmpd.<name>`,
  bound to the Compound building block) and written back. OSP Ketoconazole sets "Enable supersaturation" 1, "Treat
  precipitated drug as" 0, its aqueous diffusion coefficient and drug density; without them every Ketoconazole curve
  was ~2 % of the published one (run 33, parent-only and system round trips).
- A dose given as several administrations at 0 h (OSP Verapamil Ratiopharm 1989: two tablets, 3.5 ml/kg each) is
  given with their combined water (7 ml/kg); run 33 had the right dose but 3.5 ml/kg (Cmax +14 %).
- Run 33 also: Verapamil system 69 of 75 identical (60 in run 26).

### Changed — round-trip summaries separate solver-level residuals from real differences
- The headline now also counts pairs off by more than 1e-6 but at most 1e-3 of the peak with AUC and Cmax within
  1e-3 ("solver level"), and the pairs labelled by design. Acceptance (T-10) is unchanged: identical means 1e-6.
  Run 33 (PK-Sim, all fixes to 9768b96): Voriconazole 2/2, Clarithromycin 17/17, Digoxin 44/44 identical; the
  Itraconazole system's day-1 studies from 40–50 % off to ≤ 4e-5; the Verapamil system as-is campaign passed S2, S4
  and S5 on the published clinical data and waits at the S6 signature. Residuals of 1e-6 to 4e-4 remain unexplained.

### Fixed — administrations at the same moment are one dose (found by run 26)
- A published protocol that gives a dose as several administrations at one moment (OSP Verapamil Ratiopharm 1989:
  two 40 mg tablets, one schema each, both at 0 h) was read as its first administration: the study's product got half
  the dose (AUC ratio 0.45 in run 26). The dose is now the total given at each moment, when every moment gives the
  same.

### Fixed — water per dose; every meal of the simulated regimen (found by run 26)
- The published simulations set the water per application: OSP Itraconazole Barone 1993 gives 2.82 ml/kg with the
  first dose and 3.5 after. The water is read per dose (for a product given as several bins, from each dose's first
  application); one volume for all doses stays `water_ml_per_kg`, a different first dose becomes a regimen phase
  (`DosePhase.water_ml_per_kg`, written on that phase's schema item).
- A day-1 profile of a multiple-dose study is simulated with the whole regimen but kept only the meals of its
  sampled window: OSP Itraconazole Hardin 1988 day 1 had one breakfast of 14. Every meal within the simulated regimen
  is now given. Run 26: the day-1 studies were 40–50 % off over the simulated span, their day-15 twins identical.

### Fixed — the water given with an oral dose is the published one (found by run 26)
- Every oral protocol was built with PK-Sim's default "Volume of water/body weight" (3.5 ml/kg). The OSP models set
  others: Verapamil 2 ml/kg, Itraconazole 1.37 and 2.82, Dabigatran 2, Ketoconazole 0. The importer reads the
  published simulation's value (else its protocol's) into `StudyRecord.water_ml_per_kg`, and the build writes it on
  every dosed compound's protocol. Run 26: Verapamil Maeda 2011 and Blume 1989 were ~10 % off with every compared
  parameter identical (the protocol is not part of that comparison).

### Added — the Ketoconazole model system
- A metabolite the published simulations form (their `MetaboliteName`) is a member and a formation link even when the
  building block names none (OSP Ketoconazole: n-deacetyl-ketoconazole → n-deacetyl-n-hydroxy-ketoconazole by FMO3);
  the metabolite most selecting simulations form is taken. A cellular permeability of 0 (a published input for that
  metabolite) is accepted.
- CI round trip and example project for the Ketoconazole system. The parent-only Ketoconazole round trip is ~35×
  off by design (its metabolites inhibit its CYP3A4 / P-gp clearance); its template says so.

### Fixed — older snapshots' expression, simulation calculation methods and solver settings (found by run 26)
- A snapshot written before PK-Sim 10 (OSP Voriconazole) keeps each individual's enzymes under "Molecules" and has no
  ExpressionProfiles documents; the importer read none and the builder used the library's CYP2C19 profile (gut
  relative expression 0.013 instead of 0.324). Each such enzyme is now converted to a profile document: the harvested
  library profile of the same protein (paths, localization) with the individual's relative expressions, reference
  concentration, half-lives and ontogeny. Other proteins or localizations are left unconverted.
- A compound's calculation methods are taken from what most of its published simulations use. OSP Voriconazole's
  simulations all use "Poulin and Theil", its compound building block says "PK-Sim Standard" (fat partition
  coefficient 1.6 vs 20.6 in run 26). Recorded in the import notes.
- A published simulation's own solver settings (OSP Dabigatran Härtter 2012: RelTol 1e-09) are carried by its study
  (`StudyRecord.solver`) and written to its simulation.
- Run 26 also confirmed on PK-Sim: Clarithromycin 17 of 17 identical (the suspension fix), Alfentanil 13 of 15
  (Kharasch 2012 fixed), Digoxin 44 of 44.

### Added — model your own compound from the wizard; a user guide
- New starting point "Your own compound": the parameters the S0 gate requires (molecular weight, logP, pKa or
  neutral, fraction unbound, solubility, and total hepatic clearance bound as PK-Sim's LiverClearance "Plasma
  clearance", harvested from OSP Digoxin), each marked missing. The CPF table takes each value and its source
  directly; saving it opens the project's CSV data intake. Before, every project had to start from a published model.
- Fixed in the S0 gate: a `phys.pka.neutral` record marked missing (no value, no source) satisfied the pKa
  requirement. MS-01 §2.2 asks for a documented statement, so it now needs a value and a source like the others.
- `docs/USING_THE_TOOL.md`: deploying, loading the examples, what a campaign does, the package, your own compound.

### Added — the S7 package carries the PK-Sim project file of every bundled simulation
- S7 converts every bundled snapshot to its PK-Sim project (`pksim/<stem>.pksim5`) on the engine's
  `convert_to_project` task (PK-Sim loads the snapshot and saves the project; proven in every CI run's golden step)
  and puts it in `package.zip` beside the snapshot, results, CPF, MAP, fits and MAR: the file a reviewer opens in
  PK-Sim. A conversion that fails is named on the package (`project_notes`); the release still depends only on the
  reproduction check (D13). The package view lists the projects.
- `deploy/server/seed_examples.sh`: loads every worked example into the running tool on the server and runs its
  campaigns on PK-Sim in the background (refuses to start below 5 GB free).
- CI: the Trivy scan ran from `aquasecurity/trivy-action@0.28.0`, a tag withdrawn upstream, so the job could not
  start; it now runs Aqua's official image with the same settings (report-only, as before).

### Fixed — each project keeps its own CPF; system projects list every compound; readable study ids
- The file store kept one CPF per compound for the whole tenant (`cpf/<compound>.json`): two projects on the same
  drug (an as-published and a refit Dapagliflozin; the Itraconazole model and its system) overwrote each other's
  parameters. CPFs are now kept per project (`cpf/<project>/<compound>.json`); a project without its own still reads
  one stored the old way, so existing deployments keep working.
- `PUT /projects/{id}/system` adds every compound of the system to the project (the project page listed only the
  parent: Esomeprazole without R-omeprazole).
- A dataset whose "Study Id" is a bare number or a word (OSP Omeprazole: 2, "Median"; Ketoconazole: 9) is named after
  its data sheet or its own name: `regardh1990-2`, `boyce-2012-9-female-ketoconazole` instead of `2-0`, `9-0`.
- Added `deploy/showcase/seed_examples.py`: loads every example (the published OSP models with their clinical data,
  refit twins for Dapagliflozin and Rifampicin, the four model systems, the illustrative Aciclovir check) into the
  running tool through the API, and runs their campaigns a few at a time on the engine.

### Fixed — a tablet's "Use as suspension" setting is imported (found by run 24)
- Weibull formulations were always built with "Use as suspension" = 1, the value in the Dapagliflozin, Midazolam and
  Itraconazole tablets. OSP Clarithromycin's tablet, Voriconazole's and Dabigatran's capsule set 0. The value is now
  imported (`form.{name}.weibull.suspension`) and built; it is never a fit target.
- Run 24: every oral Clarithromycin curve was 1.2–1.6 % of the peak off (16 of 17 pairs), with every compared
  parameter identical.

### Fixed — DDI arms and paediatric studies are no longer fitted (found by run 24)
- A dataset named "with Perpetrator (X)" or "after Perpetrator (X)" (not placebo) is a DDI arm: `co_medication = X`
  (OSP Midazolam Greenblatt 2003 grapefruit juice, Reitman 2011 rifampicin; Digoxin Reitman 2011, Gurley 2008b
  echinacea). A dataset of the perpetrator itself (OSP Itraconazole's own plasma) is not. Run 24 fitted the
  grapefruit-juice arm in Midazolam S3.
- A study whose individual is under 18 is `special_population = pediatric` (OSP Itraconazole Abdel-Rahman 2007,
  four age groups). Run 24 fitted the 12–16 y group in S1 of the Itraconazole system.
- MS-01's classification is unchanged: these are data labels the importer now reads. The round trip still builds the
  paediatric studies in the published child individual; the campaign classes them SPECIAL.

### Changed — reference logs end with a recap
- `deploy/reference/run_reference.py` prints the headline and every round-trip pair outside 1e-6 again at the end of
  the log: the parameter lists run long, and log tails missed the result.

### Fixed — a model value the published simulation leaves at its default stays default
- The model's simulation-level values (`sim.*`, `sim[route].*`) were applied to every simulation of the route. A
  published simulation that does not set one keeps PK-Sim's default. The study now names those paths
  (`StudyRecord.default_simulation_values`), and the build leaves them out of that simulation only
  (`SimulationSpec.default_parameters`).
- Found by run 24: OSP Alfentanil's Kharasch 2012 oral simulation keeps the default gut-wall permeabilities (22 paths),
  and our curve was off (AUC ratio 0.32). Also affects Metformin Caille 1993 fed (3 paths).
- Impact: round-trip fidelity only; a campaign fit of these values is unchanged for the other studies.

### Fixed — a process the published simulation switches off stays off (poor metabolisers)
- A study whose published simulation leaves out processes the model's other simulations use now carries them as
  `inactive_processes` (per compound; the importer compares each simulation's process selection with the one most of
  them share). The builder leaves them out of that simulation only. OSP Omeprazole's poor-metaboliser studies (Uno
  2007, FDA esomeprazole) lose CYP2C19 on both enantiomers; OSP Metformin's Morrissey 2016 keeps only glomerular
  filtration. Before, both were built with every process: the PM curves ran on EM clearance.
- Such a study is marked with a genotype ("<compound> without <processes>"), so the campaign classes it PGX and keeps
  it out of S1–S3 (MS-01 §3.3 rule 4, unchanged). The round trip plans it as an ordinary scenario, because it checks
  the build against the published simulation. Omeprazole's system round trip goes from 9 to 14 pairs.
- Carried through `StudyRecord`, `MapScenario`, the study upload API and `SimulationSpec.inactive_processes`.
  Impact: needs a PK-Sim round trip to confirm (Actions is blocked; `deploy/reference/run_all.sh omeprazole`).

### Added — try it: 12 published models in the wizard; reference checks on the server; the plan to the goal
- The create-project wizard offers every single-compound OSP library model that imports S0-ready (Rifampicin,
  Midazolam, Alfentanil, Alprazolam, Clarithromycin, Digoxin, Metformin, Raltegravir, Ketoconazole, Voriconazole,
  Itraconazole) beside Dapagliflozin, each with its real clinical studies; descriptions name only the processes the
  model imports. A project takes the compound name the published model uses (`ketoconazole`, `Voriconazole1`).
- `deploy/reference/run_all.sh`: the CI reference matrix (read from the workflow) on this machine's PK-Sim, N tasks
  at a time, with a summary — for the server while GitHub Actions cannot start jobs.
- Plan: `docs/plans/2026-09-24-remaining-to-goal.md` — what remains, in order, with estimates and the decisions
  needed.

### Added — every meal as given: timing, template and values
- A fed study got one meal, the MAP's template, at its dose. The published simulations give meals before or after the
  dose and one per dosing day: Midazolam Bornemann 1986 dosed 1 h before a high-fat breakfast (a fasted study with a
  meal 1 h later; 0.015 of the peak off on run 14 and unlabelled) and 1 h after one; Itraconazole a breakfast with
  each daily dose plus standard meals (up to 32 meals; day-15 fed pairs were 0.98 off); Metformin meals 7.5-15 min
  before the dose and a 300 / 500 kcal standard meal (changed template values).
- `StudyRecord.meals` / `Meal` (time after the first dose, negative before it; PK-Sim template; name; changed values)
  carried by the API upload and the MAP scenario. Round build: one meal event per distinct meal with its values
  (`MealEventSpec.parameters`), each at its time (`SimulationSpec.event_times`); a meal before the dose starts the
  simulation and the dose follows (protocol start time), as the published simulations do. Empty: a fed study's meal is
  the MAP template at the dose, as before.
- Importer: the meals of the linked published simulation, relative to its first dose, within the study's sampled
  window; the data keep the meal's clock when the meal comes first. A fasted study whose first meal is at or before
  the dose contradicts its report and gets none. Also fixed: the time shift of a dataset recorded in minutes was
  subtracted in hours.

### Added — solubility and intestinal permeability per product and food state (owner-approved 2026-09-24)
- A published model can give a study's simulation another alternative of a compound property depending on the product
  given and the food state: OSP Itraconazole's solubility "Capsule fasted", "Capsule fed", "Solution fed" (default
  "Solution fasted"); OSP Ketoconazole's intestinal permeability "Fit fed" (default "Fit fasted"). One CPF value per
  property made every Itraconazole capsule and fed round trip differ (9 of 41 identical as a system).
- CPF: each non-default alternative's values are `<id>@<alternative>` records (`phys.solubility.ref@Capsule fed`,
  `phys.solubility.ref_ph@...`, `perm.intestinal@Fit fed`, same units as the default's) and `alt.select` (JSON) holds
  the rules {group, formulation, food, alternative}. `cpf.build.alternatives_for` picks, for an oral study, the rule
  for its CPF formulation (none when dissolved) and food state, else the rule for any formulation in that food state,
  else the default. IV studies use the default.
- Importer: per (formulation, food state) of the oral studies, the alternative most of their published simulations use
  becomes a rule; one alternative for every product of a food state becomes a single any-product rule. A study whose
  published simulation uses another alternative than the model selects is labelled (Ketoconazole Boyce 2010 (9) and
  Wire 2007 (94): named fasted, simulated with "Fit fed" in the published model). A pH-solubility-table alternative is
  named, not placed per product.
- Builder: `CompoundSpec.solubility_alternatives` / `intestinal_permeability_alternatives` are written after the
  default (IsDefault false, as published) and `SimulationSpec.alternatives` selects one per simulation; an unknown
  alternative is refused.
- Fitting: a fit of the default's value (`phys.solubility.ref`, `.ref_ph`, `perm.intestinal`) leaves out the studies
  whose simulation selects another alternative of that group; setting the value there would overwrite their
  alternative. The alternatives' own values are not fitted: MS-01 and diag-rules name only the default (a change
  there is SME-governed).
- Food state from the published simulation's name: when a dataset reports none, the importer used "fasted" unless the
  published simulation has a meal. OSP Ketoconazole's fed studies have no meal event (the model represents the fed
  state by "Fit fed") and all its datasets report no food state, so 16 fed studies were classed fasted. A simulation
  named with "fed" or "fasted" (as a word, not both) now gives the study that food state, with the reason in its
  reference (also Metformin's 8 fed studies, unchanged in outcome).
- Result (offline, on the regenerated snapshots): every Itraconazole study selects the solubility its published
  simulation uses (single compound and system); Ketoconazole 51 of 53 (the two above labelled). All 15 vendored models
  stay S0-ready. To be confirmed on PK-Sim when CI runners are available again.

### Fixed — the published model's own expression profiles, simulation values and formulations (run-14 round trips)
- **Expression profiles are imported verbatim.** The builder gave every protein the library's copy of its profile,
  harvested from another OSP model, plus only the numeric values that differed. The copies also differ in what is not
  a number, and in values the published profile leaves at the PK-Sim default: Clarithromycin's P-gp has no ontogeny
  where the library's copy has one (ontogeny factor 1e-14 in our model, oral curves 1-2 % off); Metformin leaves MATE1
  and OCT1 unexpressed in brain, muscle and colon where the library's copy expresses them (0 of 40 pairs identical);
  ABCB1 differs in transport type and localization in five models. Each profile of the published individual is now a
  CPF record `expr.profile.<molecule>` (the document as JSON, binding `ExpressionProfileDocument`), and a study's own
  published individual carries its profiles (`PublishedIndividual.profiles`); the builder uses them instead of the
  library's, and the `expr.*` values on top. The library stays the default for a CPF without them. Every
  regenerated profile checked (Clarithromycin, Metformin x28 individuals, Ketoconazole, Verapamil, Midazolam) equals
  the published one. The build report names the proteins given their own profile.
- **The majority simulation value is imported.** A compound value the simulations set with any disagreement was
  dropped: Metformin's brain cell permeability, 0.02 cm/min in 38 of 39 simulations, 0.023 in one. Now the value a
  strict majority of a route's setting simulations use (and at least half of the route's simulations) is imported;
  a tie is still named and not imported.
- **A simulation's own values are labelled.** A published simulation that sets compound values the model does not
  carry (a minority value) is labelled on its study as differing by design, naming the first path.
- **Dose counts of named DosingIntervals.** The label comparing doses now counts a published DI_12_12 / DI_24
  protocol (PK-Sim repeats while time < End time): Raltegravir's MD pairs "19 dose(s) as the study gave them; the
  published simulation gives 20", Kassahun 2007 (single dose) likewise; the study's own schedule is unchanged.
- **A liquid given a release model by the published model is simulated with it.** Raltegravir's granules in
  suspension (Rhee 2014) use "Weibull (granules)" in the published simulation; we dissolved them (AUC 2.3x). The study
  keeps its MS-01 class (suspension).
- **A later session of a named-interval simulation gets its schedule.** OSP Alfentanil "Kharasch 2011b IV 1 mg" is
  DI_24 to 48 h (two sessions); its "simultaneous" datasets start at 24.08 h and were simulated as one dose at 0 h (AUC
  0.51x on run 17). A dataset that starts after a named-interval protocol's second dose now takes its schedule; one
  sampled from 0 h stays single-dose (Raltegravir Kassahun 2007). A published profile entry whose value the CPF
  repeats keeps its value origin.
- Run 17 (8bf41e6), before the profile fix: Alfentanil 11/15 identical (all IV boluses 2e-8, oral with the oral-only
  gut-wall values 2e-7); the rest are the two sessions above and Kharasch 2012 oral in its own individual.
  Itraconazole as a system, as-is: S0 passes; S1 escalates on Abdel-Rahman 2007 12-16 y (published model vs
  clinical data, AUC 2.19x) in its own paediatric individual.
- Run 14 otherwise: Digoxin 38/39 identical (the other was the Kirch loading dose, now placed as phases);
  Raltegravir 14/19 (the rest labelled or fixed above); Itraconazole as a system 9/41 identical with the metabolites
  simulated, every solution-fasted pair within 2e-4, the capsule and fed pairs off because the published simulations
  select other solubility alternatives per formulation and food state (one alternative is imported; open question).

### Added — loading-dose and phased regimens (OSP Voriconazole: 0 -> 12 importable studies)
- A regimen whose doses differ or are unevenly spaced is now simulated as the published protocol writes it: one
  schema per phase (Start time, NumberOfRepetitions, TimeBetweenRepetitions) with one item at the phase's dose and,
  for an infusion, its own infusion time. New `StudyRecord.dose_phases` / `DosePhase` (start, dose, number of doses,
  interval, infusion time; `dose_mg` is the first dose), carried by the API upload and the MAP scenario; builder
  `DosePhaseSpec` on every protocol spec. Harvested shapes: Voriconazole "Purkin et al. 2003 B" (6 mg/kg IV bolus
  twice 12 h apart, then 3 mg/kg every 12 h from 24 h), "Purkin et al. 2003 A" (one dose, then every 12 h from 48 h),
  "Saari et al. vrz_oral" (400 mg twice, then 200 mg twice).
- Importer: a published schema protocol whose phases differ in dose or infusion time, or whose doses are not evenly
  spaced, becomes the study's phases. A dose the dataset reports must be the regimen's first dose or its total;
  otherwise the study is skipped with the reason. The published regimen must start at 0 h.
- Studies recovered: Voriconazole 0 -> 12 (S0-ready; its 10 Saari 2006 subjects are dosed with midazolam and stay DDI
  arms, not simulated), Metformin 41 -> 48 (779.9 mg then 584.9 mg), Digoxin +3 (twice daily for 2 days, then daily),
  Alprazolam +2 (Kroboth 1988: 1 mg over 2 min, then 0.576 mg over 8 h; Fleishaker 1994), Rifampicin +1 (Chattopadhyay
  2018). For every one checked (Purkin A/B, Kroboth, Ding, Johne) each administration (time, dose, unit, route,
  infusion time) is identical to the published protocol. They were skipped before, or (Kroboth) simulated as repeated
  identical doses in the version before 8bf41e6.
- A model system splits every phase by the product's dose fractions.
- Diagnostics leave a phased study out of the dose-normalised AUC trend (its first dose is not its exposure dose).
- A binned product given in phases is refused (no published protocol does it).
- Voriconazole snapshot vendored (commit f482aa1); round-trip CI job.

### Fixed — round-trip defects found on PK-Sim (CI run 14): Dabigatran oral 2-fold, Alfentanil/Alprazolam/Midazolam
- **A process can run on another molecule of the individual than it names.** The OSP Dabigatran simulations select
  DabiEtex's `ABCB1-FIT` transport on the individual's `P-gp`, which has its own modified profile ("new ref. conc.").
  We selected it on `ABCB1` with the library's ABCB1 profile, so every oral curve was ~2-fold off although all 10 640
  parameters compared equal (the paths differ by molecule name, so the diff could not see it). The importer now records
  a selection the compound's own simulations run elsewhere, by majority, as a categorical CPF record
  `molecule.<selection>` (binding `ProcessSelection`); the builder selects the process and interactions on that
  molecule and expresses it instead. A simulation that maps it differently is labelled (Ketoconazole's DDI arms).
- **IV bolus.** Published `IntravenousBolus` protocols (Start time and InputDose, no infusion time; harvested from
  Alfentanil, Midazolam, Digoxin, Metformin, Verapamil) were rejected as "IV with no infusion time": every Alfentanil
  IV study was skipped. New `IntravenousBolusProtocolSpec`; an `iv_bolus` study without an infusion time is built as
  a bolus (an infusion study without one still raises). Alfentanil 7 -> 18 studies, Midazolam +16 IV studies,
  Metformin +1.
- **Simulation values are decided per route.** Alfentanil sets its gut-wall permeabilities in 3 of 4 oral simulations
  and none of 8 IV ones, so the all-simulation majority dropped them (22 parameters off in every oral round trip).
  Alprazolam sets its PI permeability in all IV simulations and no oral one, and the majority applied it to the oral
  ones too (0.046 instead of the compound's 0.76 cm/min). Now: a value common to every route stays `sim.<path>`;
  otherwise a route gets `sim[oral].<path>` / `sim[iv].<path>` (`EngineBinding.route`), applied only to its
  simulations. CPF JSON schema regenerated.
- **An unset plasma protein binding partner stays unset.** Alprazolam and all Verapamil compounds leave it unset
  (PK-Sim stores 2); we wrote "Albumin" (stored 1). The CPF records `bind.partner = unspecified` and the builder omits
  the field, as the published snapshot does; no enum value is guessed.
- **Schedules of mixed or loading-dose protocols.** A schedule taken from a published protocol now counts only the
  study's own route: Midazolam's IV Mikus 2017 study was simulated as two IV doses (the protocol gives oral 4 mg at 0 h
  and IV 2 mg at 6 h); now one IV dose, and both arms labelled "the published simulation also gives an oral /
  intravenous dose". A protocol whose administrations differ in dose or infusion time (Alprazolam Kroboth 1988, 1 mg
  over 2 min then 0.576 mg over 8 h; Digoxin Kirch 1986 loading doses) was simulated as repeated identical doses
  (2-fold off); such studies are now skipped with the reason. A binned product's bins at one moment count as one
  administration.
- A model system's import now labels its studies with the link's feedback (alternatives, selection mappings) as the
  single-compound import does.
- Run 14 results otherwise: every parameter identical for Dapagliflozin, Rifampicin, Midazolam; remaining curve
  differences are labelled by design or solver noise (<= 2e-5 of the peak at 250-500 mg Dapagliflozin).

### Added — particle dissolution and binned products (OSP Ketoconazole: 5 -> 53 importable studies)
- `Formulation_Particles` (Noyes-Whitney, monodisperse), harvested from the Ketoconazole model: the unstirred water
  layer thickness (mm), the size distribution type (only 0, monodisperse, is placed; another is named), the mean
  particle radius (converted to µm; published in mm or µm). CPF `form.{name}.type = Particles`,
  `form.{name}.particles.{thickness,radius,distribution}`; builder `ParticleFormulationSpec`.
- Binned products: a tablet given as several particle-size bins at once ("PD_tablet_3Bins_B1..B3": 99.0 / 0.90 /
  0.10 % of the dose). CPF `form.{product}.type = ParticleBins` with `form.{product}.bins` (each bin and its mass
  fraction, from the published protocol, 12 digits: the published splits differ in the 7th and each is kept). The
  protocol is written as published: one schema item per bin keyed by its formulation, the water with the first only,
  one repetition 0 h apart for a single dose; the simulation selects every bin (Key = Name). A multiple-dose regimen
  becomes schema repetitions. A study linked to a binned protocol never falls back to its first bin alone.
- A "solution" the published model gives as a particle formulation (Ketoconazole's 8 nm PD_solution, dissolution
  still limited by solubility) is simulated with it; other solutions stay dissolved.
- Importer: a binned protocol's dose is the sum of its bins at the same moment; an unreported formulation is
  classified from the published formulation's name; a dataset whose molecule matches the compound on letters only is
  the parent's ("voriconazole" for Voriconazole1). A dose that is not reported, where the published protocol gives a
  loading dose, is named as such (Voriconazole's own studies); loading-dose regimens are not placed yet.
- Ketoconazole snapshot vendored; round-trip CI job. Library: 21 of 24 importable models S0-ready as single
  compounds (plus Dabigatran as a system); Warfarin (no compartment, racemic data) and Voriconazole (loading doses)
  remain named gaps.

### Added — campaigns on a model system (phase 1 wiring)
- API: `PUT /projects/{id}/system` stores the system's links (`SystemLinks`: roles, formation, products, observers,
  analytes) next to each compound's CPF, refusing it until every compound's CPF is there. `campaign:prepare` on a
  project with a system requires a parent as the fitted compound, converts each study's observed data with its
  analyte's molecular weight, stages `system.json` (URI and hash in the response, `model_system_sha256` in the MAP),
  and names the studies it cannot evaluate yet (`not_evaluated`: a mass-concentration sum such as Dabigatran's `SUM`,
  or a molar sum of compounds with different molecular weights).
- MAP scenarios carry the analyte's output path and `gated`: only the fitted parent's plasma enters the acceptance
  gate, the fit and the VPC; metabolite and sum studies are evaluated on their own curve and reported beside the gate
  (owner decision 3). A fit or validation stage whose studies are all reported analytes is SKIPPED with that reason
  (Verapamil's IV data are racemic sums), not escalated.
- Orchestrator: `system_uri` travels campaign -> stage -> round; the round build uses the system with the parent's
  current (fitted) CPF; S0 checks every compound; evaluation reads each study on its analyte's output from the
  engine bundle (unit-checked; a missing output is a finding); the S7 bundle includes `cpf/system.json`.
- `run_reference.py campaign <Drug> --system`; CI jobs for the Verapamil and Itraconazole systems as published.
- Fixed: `@activity.defn(name="diagnose_round")` had been left on the `_off` helper by an earlier edit in this
  session, so the Temporal worker registered the helper under that name; a test now guards the registration.

### Added — model systems, phase 1 step 4 (engine): every selected output in the result bundle
- `run_job.R` keeps each peripheral-venous output a simulation selects (every compound's plasma, the sum observers)
  under `profiles[<sim>].outputs[<path>]` with its own unit (a mass-sum observer reports mass concentration); the
  first compound's plasma stays the top-level curve, so existing readers are unchanged. Columns are matched exactly
  (`<path> [<unit>]`); a selected output without a column is a warning in the engine log. The engine image must be
  rebuilt (CI builds it per job).
- Still to do for campaigns on a system: store the `ModelSystem` with the project (API), carry the analyte's output
  path in the MAP scenario, and evaluate each study on its analyte's curve (report only for non-parent analytes, owner
  decision 3).

### Added — model systems, phase 1 step 3: building and round-tripping systems
- Builder: a simulation holds several compounds (`SimulationSpec.co_compounds`, each dosed by its own protocol or only
  formed); a process forming a metabolite carries `Metabolite` and is selected with `MetaboliteName`; published
  `ObserverSets` are emitted verbatim and selected; outputs are every compound's plasma plus the analytes' paths.
- `build_from_system`: every compound from its own CPF, formation set on the forming process, all compounds'
  proteins expressed, the individual from the CPF carrying it, each compound's `sim.*` values where it takes part.
- Round build: a study's product becomes one protocol per dosed compound at dose x fraction (Verapamil 80 mg TID ->
  2 x 37.03 mg), the metabolites they form are simulated with them, and the sum observers whose compounds are present
  are computed.
- `system_roundtrip_inputs` / `run_reference.py roundtrip <Drug> --system`: each pair compared on its study's analyte at
  the same output path on both sides (`reference_compare.R` reads the pair's `output`). CI jobs for Verapamil,
  Omeprazole, Dabigatran and Itraconazole.
- Fixed: a study's own individual now gets its own expression-profile categories for every protein (Omeprazole's
  Japanese individual reused "Healthy", which carries the main individual's CPF values, and the build refused it).

### Added — model systems, phase 1 steps 1–2: data model and import (plan `2026-09-24-multi-compound.md`, approved)
- `pbpk_domain.system.ModelSystem`: one CPF per compound (unchanged), roles (parent = dosed, metabolite = only
  formed), formation links, **products** (what a study administers: each dosed compound's fraction of the reported
  dose, carrying the salt and enantiomer split — required, never defaulted), published sum observers copied
  verbatim, and analytes with the output path the published simulations read. `ModelSystem.single(cpf)` is today's
  single-compound case.
- `import_osp_system`: the system around the main parent — its enantiomer family, compounds a published sum
  observer adds, and everything they form; DDI co-drugs stay out. Each study names its analyte (compound or sum, from
  its molecule, the observer name, or the published output mapping) and its product (from the published protocols).
  Verapamil: 74 studies on 6 analytes (racemic sums, enantiomers, norverapamil), products including
  `R-Verapamil 0.462875 + S-Verapamil 0.462875` (120 mg HCl -> 2 x 55.545 mg). Omeprazole: esomeprazole vs racemic
  products. Dabigatran: prodrug -> CES1/CES2 -> dabigatran -> UGT2B15 -> glucuronide, and the mass-weighted `SUM`.
  Itraconazole: 63 studies incl. 22 hydroxy-itraconazole. Warfarin's datasets name no compartment for a single
  enantiomer and stay skipped (named).
- `StudyRecord` / `StudyUpload` gain `analyte` and `product`. Verapamil, Omeprazole and Dabigatran snapshots vendored.
- Not yet: building and simulating systems (step 3), engine outputs and round trip per analyte (step 4).

### Fixed — what the PK-Sim runs of 9e617f6 showed (run 36009097300)
- **Round trips now match to ~5e-5 of the peak where they were off.** Midazolam oral was 1.4–3.7× the published curve;
  with the per-simulation gut-wall permeabilities it is within 5e-5 (AUC ratio 1.00003) for every oral study, the six
  per-kg IV studies are now found and match, and Yu 2004 in its own Korean individual is within 2e-5.
- **The remaining systematic ~5e-5 was the individual's Seed.** The parameter diff showed every organ-volume
  percentile slightly different (`Organism|Stomach|Volume|Percentile` 0.50086 published vs 0.50032 ours): PK-Sim
  draws them from `Individuals[].Seed`, and the builder used the campaign's seed. The published seed is now a CPF
  record (`indiv.seed`, the `Seed` key harvested from the snapshot) applied to every subject built from the CPF; a
  per-study published individual carries its own. Seeds are signed 32-bit, as published (Alprazolam -2063117500).
- **Diagnostics never saw the fit's optimiser evidence.** `assess_fit` found parameters at a bound, correlated pairs and
  disagreeing starts, but the findings stopped at the fit round: the refit of the published Dapagliflozin model left
  UGT1A9 clspec at its 0.1x bound and the next round reported "no diagnostic rule matched". `FitRoundOutcome` now
  carries them structured, the post-fit pass passes them in `RoundContext.fit_signals`, and the existing escalate /
  fix-and-refit / switch-algorithm rules (MS-01 §5, diag-rules unchanged) act on them.
- **The IV distribution rule could never fire.** Its evidence (early concentrations < 2 x tmax off, Vss off) was
  hard-wired off. It is now computed from the prediction read at the observed sampling times: the geometric-mean
  ratio over the early samples, and the Vss ratio (MRT/AUC with the infusion correction; dose cancels), judged
  against the ruleset's own 0.8–1.25 band. The refit's IV Cmax 0.44 with AUC in limits is that rule's case.
- `run_reference.py`: `--out` is resolved to an absolute path (the evaluate jobs failed on a relative file URI).

### Added — the OSP model library through the importer: 20 of 25 published models S0-ready (3 before)
Every published JSON snapshot of github.com/Open-Systems-Pharmacology (25; Gemfibrozil, Theophylline, Repaglinide and
Trimethoprim ship only a binary `.pksim5` project) was imported; each gap found was fixed from the snapshots' own
names and units, or is named. Six small models are vendored as fixtures with their commits
(`services/engine-worker/golden/fixtures/SOURCES.md`) and each process type / edge case has a regression test
(`test_reference_library.py`).
- **Process types** (builder `HarvestedProcess`, a table of harvested parameter names and units per type; an
  unlisted name is refused): intrinsic first-order (Alfentanil), recombinant-CYP MM and first-order (Efavirenz,
  Itraconazole), total hepatic clearance (Digoxin, Cimetidine), renal clearance (Clarithromycin), Hill transport
  (Metformin PMAT), vesicular-assay transport (Rosuvastatin), irreversible / mixed / noncompetitive inhibition
  (Clarithromycin, Atazanavir, Fluconazole). Systemic selections harvested: `Total Hepatic Clearance-<source>`
  (Hepatic), `Renal Clearances-<source>` (Renal).
- **Two pathways on one enzyme** (Alprazolam CYP3A4 alpha-OH / 4-OH) were one process: processes are now keyed by
  data source, and colliding CPF ids name it (`elim.hepatic.CYP3A4@alpha-OH pathway.kcat`).
- **Multi-compound snapshots** (11 models) were refused. The parent (the compound most simulations dose, or the one
  named) is imported; a study whose published simulation doses another drug is a DDI arm (`co_medication`); one whose
  metabolites act on the parent's clearing protein (Itraconazole's hydroxy-, keto-, N-desalkyl-itraconazole on
  CYP3A4) is labelled "differs by design" in the round trip. Interactions come from the compound's own simulations
  only, not DDI arms. Processes no own simulation selects are named, not built.
- **Units**: nmol↔pmol per mg microsomal protein / per pmol enzyme or transporter, µM, 1/h, ml/h/kg, l/h/kg, l/h,
  pmol/ml/min, mg/dl. **Vmax 0** is a published input when kcat carries the rate (Cimetidine, S-Warfarin,
  Clarithromycin microsomes); a microsomal process without kcat leaves it to PK-Sim's formula.
- **pH-solubility tables** (Raltegravir, Voriconazole): `phys.solubility.table` (pH, mg/l points), written as PK-Sim's
  `Solubility table` TableFormula; S0 completeness accepts it as the reference solubility.
- **Several solubility alternatives** (Carbamazepine, Erythromycin, Itraconazole): the one most own simulations use is
  imported; studies simulated with another are labelled. Exact per-study alternatives are a named follow-up.
- **Metadata edge cases** (every value in the library): routes "po", "iv", "capsule", "IV_30min_infusion",
  "30-min infusion" (infusion time read), genotype filed as route ("EM"/"PM") or none → the published protocol's
  application type; a dose without unit is mg only when the dataset name repeats it, else the published protocol's
  dose; no administration times → the published protocol's schedule; food states "Breakfast", "Light breakfast",
  "Semifed" → fed, "Semifasted"/"Unknown"/mixed → the published simulation's meal state; a dataset with no study id
  → its own name (Clarithromycin's 17 datasets collided on ""); a garbled molecule name ("Fluvoxaminekjujhöjö") is
  accepted only where the published model maps the dataset onto the parent's plasma output. All noted per study.
- **Expression library 16 → 40 proteins** (CYP1A2/2A6/2B6/2C8/2C9/2C19/2D6/3A5, OCT1/2, MATE1, OAT3, BCRP, OATP1B3,
  OATP2B1, PMAT, MRP2, CES1/2, FMO3, UGT2B15, …) from library clones (`harvest_expression_library.py --library`, commit
  recorded per entry). Existing entries are unchanged, so existing models build identically.
- **Fixed — fit paths for transport, inhibition and induction were never harvested and were wrong.** `pksim_paths`
  assumed they share the metabolism container (`<C>-<M>-<source>|p`); the published PIs' `LinkedParameters` show
  `<C>|<M>-<source>|p`. A transporter kcat fit (diag-rules 0.4) would have addressed a path that does not exist.
  Shapes are now harvested per type (intrinsic FO, recombinant CYP, total hepatic clearance added); a type with no
  harvested path raises and is not offered for fitting.
- Portfolio: fetches the vendored fixture, then the raw file, then a shallow `git clone`; a split failure is a row.

### Fixed — a study the published model simulates in its own individual was regenerated in the main one
- **Per-study published individual.** `StudyRecord.published_individual` (reference import) carries the individual a
  published model uses for one study when it differs from the main one: its complete physiology overrides (replacing
  the CPF's `indiv.*` for that study, so a value the main individual sets and this one does not stays at the PK-Sim
  default, never invented) and its expression values that differ from the library, built under the subject's own
  profile category. Cases: Rifampicin `acocella-1972a-day-7` in the "EHC off" individual (round-trip AUC 1.043 before);
  Midazolam `yu-2004-control-cyp3a5-3-3` in the Korean individual (CYP3A4 3.63 vs 4.32 µmol/l, round-trip AUC 0.91).
- **Study weight and height are now written into the individual.** `OriginData.Weight` (kg) / `Height` (cm) were held
  back until harvested; the OSP Midazolam model's Korean individual sets both, so the builder emits a study's recorded
  mean weight/height and PK-Sim scales the physiology to it. Impact: any study with a recorded weight is now simulated
  at that weight instead of the population default for its age and sex. The reference importer takes both from the
  published individual's OriginData; the write API keeps `published_individual` on upload.

### Changed — diag-rules 0.5 (UNVERIFIED): exposure fallback rule (approved by the project owner, 2026-09-24)
- New rule `exposure_fallback`: when a fitting study's AUC is off by more than 1.5-fold (either direction) and no other
  rule's evidence is present, fit clearance first (`elim.hepatic.{enzyme}.clspec`, `elim.hepatic.{enzyme}.kcat`,
  `transp.{name}.kcat`), then `phys.logp`. Evidence `exposure_off`; threshold `exposure_fallback_fold: 1.5`. A rule
  marked `fallback: true` fires only when no specific rule matched, so the clearance, absorption and first-pass rules
  keep their own order.
- Why: refitting the published Dapagliflozin and Rifampicin models from shifted starts escalated at round 1 with
  "no diagnostic rule matched" while AUC was 2-fold off. The clearance rule needs t1/2 to move with AUC; with several
  parameters wrong at once they point opposite ways.
- Impact: those refits now proceed to a clearance fit. Ruleset version bumped to 0.5; stays UNVERIFIED pending SME
  sign-off. `docs/PBPK_MODELING_WORKFLOW.md` §5 table gains the row.

### Fixed — Midazolam round trip on real PK-Sim: oral curves 1.4–3.7× the published ones (run 36003028399)
- **Gut-wall permeabilities set per simulation were dropped.** The published Midazolam model sets the PI-identified
  `Neighborhoods|<segment>_int_<segment>_cell|Midazolam|P (interstitial<->intracellular)` (11 gut segments, 22 values)
  in its simulations. The importer only took `<Compound>|…` paths, so our oral simulations had PK-Sim's default gut-wall
  permeability and far less intestinal first-pass (IV matched to 0.3 %; oral AUC 1.2–2.7× and Cmax 2.2–3.7× high,
  worst at microdoses where gut CYP3A4 is not saturated). Any compound path the simulations set is now a `sim.*`
  record when every simulation setting it agrees and at least half set it; a simulation that leaves it at the default
  is named in the notes (Midazolam: the 30-min IV infusion).
- **The published expression profile now wins over the library copy.** The builder used the harvested library profile
  (CYP3A4 from the Dapagliflozin model, `t1/2 (liver)` 37 h); the Midazolam and Rifampicin models use 36 h, which sets
  the enzyme turnover that induction acts on. Each value of the published individual's profiles that differs from the
  library becomes an `expr.<path>` record (ExpressionProfile building block) applied over the library profile at build.
- **Published simulations named with "/" (`iv 0.075 mg/kg (1 min)`) were reported "not exported".** PK-Sim writes the
  "/" as a subdirectory; `reference_compare.R` now lists the export recursively and falls back to an alphanumeric
  name match. Its parameter diff skips wildcard paths (`Organism|R*T`), which `getQuantityValuesByPath` rejects.
- Impact: 6 Midazolam IV studies join the round trip; oral Midazolam and Rifampicin induction are regenerated from the
  published values. Re-run pending on real PK-Sim.

### Changed — reference workflow
- `run_reference.py evaluate <drug>`: the published model judged on every study it can simulate by the pipeline's own
  evaluation (GMFE, within 1.25/1.5/2-fold of AUC and Cmax), one engine run; matrix jobs for the three drugs.
  `roundtrip.study_snapshot` builds that snapshot. The workflow no longer cancels a running set on push.

### Fixed — the model regenerated from a published CPF was not the published model (found preparing the round trip)
- **Simulation-level compound values were dropped.** Every published Dapagliflozin simulation sets
  `Dapagliflozin|logP (veg.oil/water)` = 2.083 (drives Rodgers & Rowland tissue partitioning) and the measured
  blood/plasma ratio 0.88. The CPF now carries them as `sim.<path>` records (Simulation building block), and the
  builder writes them into every simulation's `Parameters`.
- **Inhibition and induction never acted.** The builder selected `CompetitiveInhibition` / `Induction` among the
  compound's `Processes`. PK-Sim selects them as the simulation's `Interactions`
  (`{"Name": "<Molecule>-<DataSource>", "MoleculeName", "CompoundName"}`, harvested from the OSP Rifampicin snapshot),
  so rifampicin's auto-induction of its own metabolism (AADAC) and transport (P-gp, OATP1B1) would have been
  silently off. Now written as interactions. The old test that asserted the wrong selection is corrected.
- **Rifampicin imports** (51 plasma studies from its 13 sources; 38 datasets named and not used): values the paper
  identified are recognised by `ValueOrigin.Method` too, so they are `FITTED`. Studies are linked through the
  paper's own parameter identifications (`ParameterIdentifications[].OutputMappings`) as well as the simulations.
  Every OSP regimen notation is read (`(S0-T24-R14)`, `(S-0,T-24,R-7)`, `0-24-48-…`, mixed). A linked
  multiple-dose protocol applies only when the dataset was sampled after the second dose; irregular schedules are
  named, not simulated. IV infusion times come from the published simulation's override, else from the dataset's
  description. Free-text formulations are classified by their words. An antacid arm is a DDI study and a
  liver-disease arm a hepatic-impairment study, and neither is fitted. Interactions the published simulations
  never select (DDI with victim drugs: CYP2C8, CYP2C9, BCRP, OATP1B3, OATP2B1, CYP1A2, CYP2E1) are named and left
  for the DDI phase. The study upload now keeps `co_medication`.
- **`docker_engine.sh` on Linux** runs the engine as the calling user (the job directory is 0700; the image's uid
  10001 could not write there).

### Verified on PK-Sim — first reference results (GitHub runner, qualified engine 12.4.4 / rSharp 1.2.2)
- **Dapagliflozin round trip:** 28 of 34 published simulations regenerated from the imported CPF agree within 6.3e-5
  of the peak (AUC and Cmax within 0.005 %), the same small offset in every pair. Not yet the 1e-6 bar; a
  parameter-by-parameter model diff is added to locate it. The IV pair's 100 % "difference" was a harness bug (see
  below). The Chang 2015 fed tablet (Cmax 0.71×) and the five Komoroski MAD day-1 datasets (AUC 13.7×) differ by
  design: we simulate the reported meal and the real 14-dose regimen, while the published model approximates them
  as fasted / single dose. They are now labelled so.
- **Rifampicin round trip:** first pair within 4e-5 of the peak (run interrupted; rerun queued).
- **Dapagliflozin as-is campaign escalated at S1** on the IV microdose Cmax (0.48×), while the published model and
  ours agree. The cause was our evaluation, fixed below. **Refit:** the clearance fit cut the S1 AUC error from 2.6×
  to 1.46×, then the stage failed on `BudgetTooSmallError` (a 1800 s stage on a 4-core runner).

### Fixed — evaluation and NCA defects the PK-Sim runs exposed (science; flagged for SME review)
- **The prediction is read at the observed sampling times** before NCA. Predicted and observed AUC, Cmax, tmax and t½
  now come from identical sampling. Before, the simulated grid (every 6 min) was reduced over the observed window,
  so the IV microdose sampled from 5 min was scored on a 6-min value (Cmax 0.48×). `ObservedPK.sample_times`.
- **Simulations are sampled every minute for the first 2 h**, then as before (two output intervals, as the OSP
  reference simulations use). Early IV and distribution-phase samples are resolved.
- **NCA terminal phase:** only points after Cmax; trailing points that do not decline are left out of λz (they stay
  in AUClast); adjusted-R² ties within 1e-4 take more points (the standard best-fit rule). The Boulton 2013 IV data
  (last two points identical, assay limit) gave t½ = 275 h; now 9.5 h from 8 points.
- **A stage that cannot fit its remaining budget escalates with the best CPF so far** (`budget_exhausted`, D8),
  instead of failing and losing its rounds. Reference runs set the stage budget for their host
  (`REFERENCE_STAGE_BUDGET_S`; 1.5 h per stage on a 4-core runner, where the server has 48 cores).
- **Round-trip harness:** samples are paired by time (PK-Sim always outputs t = 0, so a published dose at 60 min
  shifted the indices and showed a false 100 % difference), and deliberate differences are labelled.
- Test fixture fixed: its observed Cmax was not the Cmax of its observed profile.

### Added — Midazolam, and the edge cases it brings (third reference model)
- **Microsomal Michaelis-Menten metabolism** (`MetabolizationLiverMicrosomes_MM`: in-vitro Vmax per mg microsomal
  protein, microsomal enzyme content, Km, kcat; names and units from the OSP Midazolam model) is placed by the builder;
  **specific binding** (GABRG2) is imported. Midazolam imports S0-ready: 79 real studies, 72 paired with a published
  simulation.
- **Per-kg doses** (`0.05 mg/kg`) are simulated as PK-Sim `mg/kg` InputDose (scaled by the individual's weight, as
  the published protocols do); µg doses are converted. A study carries `dose_per_kg`; the S2 dose-level choice and
  the dose-normalised diagnostic compare like units only.
- **Any regular regimen** (e.g. every 6 h) is built as a repeated protocol schema (`NumberOfRepetitions` /
  `TimeBetweenRepetitions`, the structure of the OSP multiple-dose protocols); named DosingIntervals (DI_24, DI_12_12)
  stay as they were. Before, such a study was not simulated.
- **Study demographics** reach the MAP: the upload keeps `demographics`, and the importer sets them from the
  individual the published simulation uses (e.g. an Asian_Tanaka_1996 study is simulated in that population).
- **A formulation named only by its product** ("Dormicum") is recorded as `other`: judged, never used to train
  absorption or release; syrups and injections given orally are solutions.

### Changed — diag-rules 0.4 (owner-approved 2026-09-24, still UNVERIFIED pending SME sign-off)
- **The clearance rule may fit Michaelis-Menten catalytic rates** (`elim.hepatic.{enzyme}.kcat`,
  `transp.{name}.kcat`), after first-order `clspec` and before renal clearance and logP; the S1/S2 stage plan permits
  them. Before, a compound cleared by saturable metabolism or transport (rifampicin: AADAC, OATP1B1, P-gp) could
  never have its clearance fitted, only escalated or hidden in logP. The Rifampicin refit is no longer held.

### Added — the OSP library portfolio
- `deploy/reference/portfolio.py` fetches every OSP library model (`Open-Systems-Pharmacology/<Drug>-Model`), imports
  it, checks S0 and the split, and, on the engine, round-trips each published simulation. The table of what the tool
  can and cannot take, drug by drug, is the work list for the next fixes. Runs in the reference workflow.

### Fixed — the engine image was not the qualified engine
- **The Dockerfile pinned nothing but R and .NET.** Built today it pulled rSharp 2.0.0 (needs .NET 10) with the
  .NET 8 runtime, and PK-Sim could not start (`No .NET 10 runtime was found`; first reference run). The qualified
  engine (golden/catalog.json) is ospsuite 12.4.4 / PI 2.2.0 / rSharp 1.2.2. rSharp is now installed from its
  tagged 1.2.2 release, and the build fails unless all three versions match.

### Added — reference runs on real PK-Sim (GitHub Actions)
- `deploy/reference/run_reference.py` (round trip / as-is / refit) and `.github/workflows/reference-models.yml`. The
  workflow builds the pinned engine image on a GitHub runner, where CRAN and the OSP r-universe are reachable (they
  are not from the development container). `reference_compare.R` compares each published simulation with our
  regenerated one on identical time points (tolerance 1e-6 of the peak). The refit (`pbpk_domain.reference.refit`)
  frees what the published model identified within the user-approved bounds (0.1×–10×; logP ±1.5), from shifted
  starts. Campaigns stop at the S6 signature gate; CI never signs.
- **Known gap (needs approval, SME-governed):** the diagnostics clearance rule offers only first-order `clspec`,
  GFR fraction, tubular secretion and logP as fit targets. A Michaelis-Menten `kcat` (rifampicin's AADAC metabolism,
  P-gp / OATP1B1 transport) can never be fitted, so the Rifampicin refit is held.

### Added — the reference importer: a published OSP model becomes a CPF and its real clinical studies (Phase 4)
- **`pbpk_domain.reference.import_osp_snapshot`** turns a published single-compound OSP model snapshot into a CPF
  plus its plasma studies in the API's upload shape. The data are real: they are the OSP model's own clinical
  datasets. Values, units and provenance are copied from the snapshot (a value the published model identified stays
  `FITTED`, a literature value `FIXED`); no fit policy is invented. A study's route, dose, formulation, food state
  and regimen come from the dataset's metadata. Where a dataset leaves one open, the published simulation that runs
  it fills the gap, and the study's reference says so. Display units of the same dimension (e.g. fu in %, solubility
  in mg/l, a transporter concentration in µmol/l) are converted to the unit the builder requires. Any other unit
  pair raises an error.
- **Dapagliflozin imports complete and S0-ready**: 28 CPF records (3 UGT/CYP clearances, GFR, physchem, both
  permeabilities, the Weibull tablet, 7 individual physiology values) and 40 plasma studies from 13 publications
  (IV microdose, solution, capsules, tablet, fed, multiple dose, renal impairment). The MS-01 split assigns the IV
  microdose to S1, solution / Dissolved-capsule studies to S2, the fed tablet to S3, and 32 external studies to S5.
  The four T2DM / renal-impairment arms are SPECIAL and never fitted. Every stage's snapshot builds, and it carries
  the published process values and individual physiology exactly (asserted in the tests). The 15 datasets not
  imported (urine/feces fractions → T-11, metabolites) are each named with the reason. **Not yet proven on PK-Sim**:
  the 1e-6 round trip against OSP's own outputs and the full campaign need the engine host.
- **Gaps the other reference models expose (named, not fixed):** Rifampicin's DDI targets (CYP2C8, CYP2C9, BCRP,
  OATP1B3, OATP2B1, CYP1A2, CYP2E1) have no harvested expression profile, so S0 refuses it; its capsules are
  described in free text; 33 of its IV datasets link to no simulation that gives an infusion time. Midazolam needs
  `MetabolizationLiverMicrosomes_MM` and `SpecificBinding` placement and per-kg doses. The Itraconazole snapshot holds
  4 compounds.
- **The CPF can carry an individual's changed physiology** (`indiv.<PK-Sim path>` records bound to the Individual
  building block). Every subject the CPF is simulated in gets them as path-addressed `Individuals[].Parameters`,
  the structure the OSP reference snapshots use. The published Dapagliflozin model sets the gallbladder's EHC
  continuous fraction to 1 and fits the colon's effective surface-area factors. Without these the regenerated
  model would not be the published one.

### Fixed — "create a new project" failed where the user could not see why, and showed made-up data
Found by driving the wizard end to end in a browser (new Playwright flows, below).
- **The wizard's own starting CPF could not start a campaign.** The pre-filled Aciclovir set had
  `elim.renal.gfr_fraction` with no engine binding. Since S0 began refusing unplaceable clearance parameters, it
  was refused at S0. Fixed: the template carries the GFR binding (tested).
- **Errors vanished.** The web client parsed every answer as a success envelope. A FastAPI refusal (`{"detail": …}`,
  e.g. 422) had neither `data` nor `errors`, so the wizard did nothing and said nothing. A proxy failure was reported
  as "Could not reach the API" with no status. Every write now reports the API's own reason (validation errors
  field by field), or the HTTP status with a hint when the web server cannot reach the API. MAP-signature and
  campaign-start refusals carry their reason too. The Run button checked `if (!signed)` on what is now a result
  object; corrected.
- **"Showing sample data — the API is not reachable" was wrong and hid the real state.** Any failed read (including
  a 404 for a campaign whose monitor record had not been written yet, right after Start) made the page show a
  hard-coded sample campaign/project with that banner. Pages now show the actual problem (unreachable with its
  cause, the API's error, or "not recorded yet — this page checks again"), never sample data. The sample data are
  deleted (`lib/fixtures.ts` → `lib/types.ts`, types only).
- **No pre-made demo project.** The sidebar's hard-coded "Example project: Aciclovir FIH" links and the server's
  first-run seeding of that project (`deploy/server/run_modeler.sh`, `deploy/dev/read-root/`) are removed. Every
  project is created in the wizard.

### Added — project templates from the API, and a monitor that says what produced the numbers
- **`GET /api/v1/templates`, `GET /api/v1/templates/{id}`** serve the wizard's starting points. The first is the
  published **Dapagliflozin OSP model with its real clinical data** (imported live from the reference snapshot;
  `MODELER_REFERENCE_MODELS_DIR` overrides the location). The second is the Aciclovir illustrative quick check,
  labelled "not clinical data". The wizard gains a step 0 "Start from", shows the CPF and the studies as tables (JSON
  still editable), lists the source datasets not used and why, and lets the modeler set the M15 model risk.
- **Every campaign records its engine** (`engine`: PK-Sim / software fixture / injected, from
  `MODELER_ENGINE_COMMAND`). A campaign run on `stub_engine.py` or `analytical_engine.py` carries a red "Not a PBPK
  result" banner on the monitor, so a software-fixture run cannot be mistaken for model evidence (CLAUDE.md rule).
- **Playwright acceptance flows** (`apps/web/e2e`, `npm --prefix apps/web run e2e`). The config starts its own API
  and web server on a fresh data directory. On the stub engine by default the flows prove the software path only:
  wizard from the published model → CPF → 40 studies → MAP (S0 → S7) → signature → campaign → monitor. The same
  flow runs on PK-Sim with `E2E_ENGINE_COMMAND`. Three more flows: the API not answering, the API refusing a step,
  and an unknown campaign. On the stub engine the Dapagliflozin campaign passes S0 and escalates at S1 (the
  synthetic curve is 13 000-fold off), which is the gate working. No fit is tried because the imported published
  CPF has no fit policies.

### Fixed — the study upload dropped who was studied
- **`POST /projects/{id}/studies` silently discarded `population_type` and `special_population`**, although the MAP's
  split reads them. A renal-impairment or patient study was therefore classified as healthy and could train the
  healthy-volunteer model (MS-01 §3.2 forbids it). The upload now keeps both, so such a study is classified SPECIAL.

### Fixed — what the project doctor found on the real project: the sheet reader's guesses and the literature agent's filings
- From the owner's doctor report (2026-10-06, ER tablet, 12 client files, 51 evidence items):
- **Sheet reader (my defects, 4740c8c):** file names with underscores ("230-23_Fasting_Reference.Data…") defeated
  the word-bounded patterns, so every arm got a bare study id ("230", "093"; both 230-23 arms under one id), no
  fed / fasted and no Test / Reference; "Same settings as the last sheet" copied dose, route and formulation, which
  turned the Nichols 2012 IV 50 mg infusion into "oral 100 mg ER"; and a CRO sheet's Mean / SD / CV / Geo Mean columns
  were read as subjects, the whole dataset labelled geometric means. Now: names are read as words (decimal points
  kept); IV studies get their own id (`…-IV`) and the infusion time stated in the name is offered; summary columns
  are left out and named; a mean statistic only for a lone mean column; "Same layout as the last sheet" copies the
  layout only (columns, units, LLOQ, cell texts), never the rows or the study; what the study is for and the food
  state of an oral study must be chosen (they defaulted silently before). Reading a sheet again can **replace** the
  earlier reading (its datasets rejected with that reason, its dissolution records dropped).
- **Evidence the agent misfiled:** fu 0.3 from "plasma protein binding is low (30 %)" (the bound share), the
  fraction excreted unchanged in urine (0.45) as PK-Sim's GFR fraction, pathway sentences as values, DrugBank
  predictions as measured, permeabilities of 6–7.5 cm/min. Added: code converts "% bound" to fu (1 − bound) and
  "% unbound"; review flags, recomputed on read so stored items show them too (binding quoted for fu, urine quoted
  for the GFR fraction, a statement filed as a value, DrugBank as source); a physical bound on intestinal
  permeability (≤ 1 cm/min) and fe; reference ids `elim.fe_urine` and `elim.fm.<enzyme>` (kept in the CPF to constrain
  the fitted elimination, never placed, never counted as the S0 elimination pathway); a correction can turn a
  sentence into a number only when the quote states that number ("Km = 290 µM" → elim.hepatic.CYP3A4.km 290 µmol/l);
  assembly keeps a sentence under a numeric parameter out of the CPF. The A2 prompt now states these rules.
- **To-do and doctor:** datasets sharing a study id and oral studies without a food state are listed; the doctor
  prints the review flags per parameter.
- **The sheet's own mean profile is read next to the subjects.** The campaign judges a study on a mean profile; a
  dataset of individual subjects only is kept for the population evaluation, so the project's BE and Nichols data,
  read as subjects, gave P4 nothing to judge on. A CRO sheet's Mean column (times down, with its SD) or Mean row
  (times across) is now read as one more series of the same study ("Mean", with the study's N); the subjects stay.
  The person can change or clear it in the form.
- Impact: no model value changes by itself; the owner's project needs its sheets re-read (replacing the earlier
  readings) and its evidence settled. Tests: `test_sheet_form.py` (the project's real file names, the CRO wide
  layout), `test_inputs_todo.py` (misfilings, % bound, quoted number, fe), `test_client_api.py` (replace), e2e.
- Known gap: `services/api/tests/test_t56_kit.py` fails about 1 run in 6, also before this change (a campaign file
  read while the local runner writes it); suggested as a separate fix.

### Fixed — P4 put names the model does not use into the CPF; the Model inputs page now settles each open item (owner, real project)
- Owner's report (2026-10-06): P1–P3 approved, P4 "not ready" with a readiness list and no way to act on it. From the
  screenshots: six accepted fu values, five for `elim`, five for the GFR fraction, permeability and solubility; two
  pKa values without acid / base; a template target `elim.hepatic.{enzyme}.km/vmax`; and a CPF record named
  "plasma protein binding".
- **Fixed (science):** assembly put any accepted target into the CPF. The builder skips ids it does not know, so
  "plasma protein binding" sat in the CPF without reaching PK-Sim, and a single value under the data plan's
  placeholder `elim` would have passed the S0 "at least one elimination pathway" check while the model had no
  clearance (the failure CLAUDE.md warns about). Assembly now keeps out of the CPF, and names, every id that is not a
  compound field or family the builder reads, a process parameter of the harvested table, or a reference value
  (`dist.bp_ratio`, shown as "kept for checks; PK-Sim computes it"). A hand-entered value must name such a parameter
  (or its data-plan item's own placeholder).
- **Added:** typed assembly issues and a to-do list (`GET /inputs` → `todo`) with what settles each: several accepted
  values (`POST /evidence/{id}:choose`: keep one, the others rejected with the person's reason); a placeholder,
  template or unknown target and a pKa without acid / base (`POST /evidence/{id}:correct`: the original kept,
  rejected, pointing at a corrected copy with the same source and quote; a copy filed under another parameter is
  proposed again with its converted value, because a new name can change what the number means); missing S0 values
  with the proposals waiting and the molecular weight from the brief's PubChem record (`POST /inputs:propose-identity`,
  quoted from the stored record); datasets to accept, with why individual-only studies are not judged by the campaign;
  the formulation of solid studies. The Model inputs page shows it as "What stops readiness", re-assembling after each
  decision.
- **Added:** the project doctor (`python -m modeler_api.doctor`): a project's state as a shareable Markdown report
  (phases, data plan, client files and reconciliation, evidence per parameter with conflicts and unknown names,
  dataset metadata, readiness and to-do, last audit events, recent API errors), without observed values or secrets.
- Impact: CPFs assembled before this change may contain records under unknown names; re-assembling drops them and
  lists them to correct. Tests: `test_inputs_todo.py` (the project's state reproduced and settled), `test_inputs_api.py`,
  `test_evidence_api.py`, `test_doctor.py`, e2e `inputs-todo.spec.ts`.

### Changed — the Client data page reads any client spreadsheet with a guided form; P3 says what stops it (owner, real project)
- Owner's report (2026-10-06), second round on the same ER-tablet project: Approve stayed disabled although every item
  had been "marked", and reading a sheet meant writing a JSON recipe. Reproduced on a replica (same applications,
  workbooks laid out the way CROs send them). Causes:
  - **"Cross-check in literature" never unblocked an item** until a literature value had been found *and* accepted,
    while the refusal told the person to switch it on. The page now offers **Get it from the literature instead**
    (the item's provider becomes LITERATURE: P2 takes it over, P3 no longer waits) next to **Not from the client**;
    a cross-check that is still waiting says so, and the refusal names it.
  - **BE data with the sampling times across the top** (one row per subject, Pre-dose first, Mean / SD rows under the
    subjects, BLQ / NS cells) could not be read at all: a recipe needed one time column. Recipes take `time_row`
    (times from a header row; a unit written in a header must be the table's, no conversion guessed; a pre-dose sample
    is nominal time 0) and `missing_tokens` (cells that mean no sample, skipped; declared by the person, shown in the
    recipe). Series of one subject with several rows are labelled subject / period.
  - "Intra- and inter-subject variability" is expected from the client by the VBE template but nothing a client file
    holds can deliver it; the page says where it usually comes from (the BE statistical report) and lets the person
    decide.
- **Guided sheet reader** (`modeler_intake.sheet_form`, `GET /projects/{id}/client-data/{sid}/sheets/{sheet}`): the
  sheet is shown next to a form filled in from the sheet itself (header and data rows, layout, subject / period /
  value / SD / N columns, statistic; units, LLOQ, dose, pH, rpm, volume, batch, apparatus, medium quoted from their
  cells as recipe evidence, a quote dropped when the person changes what it supports; study id, food state, route and
  release type from the file name, said so). "Check what will be read" shows the series, times, first values with
  their cells and the problems in words, grouped; "Save" keeps the recipe (JSON visible on request, still the record).
  `:map` accepts the form or a recipe. External values are hidden in the check while blinding is on (D-15).
- Page layout: five progress steps (data plan, files, sheets read, plan items, approval) with the approve button at
  the top; "What stops approval" lists each blocking item with how to deliver it and the decisions; every sheet shows
  whether it was read; optional items no longer show as red "missing". Sheet triage calls a sheet that names its
  subjects individual data even when Mean / SD rows follow.
- Impact: no model value changes; nothing is read without a person's check and save. Tests: `test_sheet_form.py`
  (CRO BE layout, dissolution vessels, published means, a non-data sheet), `test_intake.py` (times across),
  `test_client_data.py` (literature instead, cross-check refusal), `test_client_api.py` (sheet view, form mapping),
  e2e `client-data-guided.spec.ts` (five files read, two items decided, P3 approved) and `client-data.spec.ts`.
- Known gap: legacy `.xls` files are not read (convert to `.xlsx`; reading them needs a new dependency, not added
  without the owner's approval). A sheet read twice adds new datasets; the old ones are rejected on the Literature
  page.

### Fixed — P3 could not be closed with dissolution and BE data in the client's own spreadsheets (found on a real project)
- Found on the owner's first real project (an ER tablet, VBE + food effect): twelve client workbooks uploaded, none in
  the client-data template, and the P3 gate had no way forward. Three defects:
  - **Mapped dissolution never counted.** The reconciliation read dissolution only from the template's rows; records
    from a confirmed mapping recipe built profiles but left "Release model of the product" and "RLD and Test
    dissolution in the same media" MISSING.
  - **"RLD and Test dissolution" could never be delivered**, even from the template: being a dataset item it was
    matched as a PK study. It now needs a TEST and an RLD / REFERENCE profile in the same medium and pH (PARTIAL,
    with the reason, when only one role arrived).
  - **A study's purpose in the study facts broke the dataset**: it was copied into the MS-01 study record, which
    refuses unknown fields, so a BE study mapped "for external validation" matched no data-plan item. The purpose now
    goes on the dataset only.
- A mapping recipe can name a dissolution profile's product, role (TEST, RLD, REFERENCE, SOLUTION, OTHER; others are
  flagged), strength and medium volume; profiles from mapped sheets carry them, so f2 pairs and the release-model item
  work as for the template. Product names compare as the data plan does (case and punctuation aside); a profile named
  for another product is shown as such instead of a bare "missing". A blank constant in a recipe is "not stated"
  (it used to fail as "could not convert ''"); a word where a number belongs is named with its sheet.
- Client data page: the mapper offers a dissolution recipe (chosen from the sheet's triage, or by hand) and a
  "the study is for" choice (model building / external validation / application verification) for PK sheets.
- Impact: no model value changes; datasets mapped before this change keep the purpose they were stored with. Tests:
  `test_client_data.py` (mapped profiles, test-vs-reference, product mismatch), `test_intake.py`, `test_data_mapping.py`,
  `test_client_api.py` (purpose), e2e `client-data.spec.ts` (dissolution sheet mapped in the browser).

### Changed — the agents use the in-house model (LiteLLM → Ollama qwen3-coder) with web search; Gemini and Groq removed (D-16)
- Owner's decision (2026-10-06): `modeler_agents.llm` now has one provider, `litellm` — the company's LiteLLM proxy in
  front of Ollama `qwen3-coder:30b`, model alias `qwen-coder`. Configuration only from the environment:
  `MODELER_LLM_PROVIDER=litellm`, `LITELLM_BASE` (default `http://127.0.0.1:4000/v1`), `LITELLM_KEY`,
  `MODELER_LLM_MODEL` (default `qwen-coder`), `MODELER_LLM_TIMEOUT_S` (default 600: a 30B model on a long document
  needs minutes per turn). The Gemini and Groq providers are removed; selecting them is refused with the setting to
  use instead (a server still configured for Gemini says so in plain words). Client documents no longer leave the
  company's server.
- Errors now say what to fix: a rejected key (401/403, not retried, "check LITELLM_KEY"); an unknown model (lists what
  the proxy serves, from `GET /models`); an unreachable proxy ("is LiteLLM running, is LITELLM_BASE right?"); a timeout
  (names `MODELER_LLM_TIMEOUT_S`); tool calls the model writes into its text (`<tool_call>{…}</tool_call>`, Qwen's
  format) are read as tool calls; arguments that are not JSON go back to the model to resend (as before).
- `modeler_agents.web_search`: Ollama's web search (`OLLAMA_API_KEY`, `https://ollama.com/api/web_search`):
  `web_search(query)`, `ask(question)` (the owner's reference loop: the model calls `web_search`, the results go back as
  tool messages, the final answer is returned), and `chat(messages, tools)` in `llm`. A2 and A3 get `web_search` when
  the key is set; every result page is stored as a document first, so a value is still quoted from a stored page and
  checked verbatim (D-09: the web finds sources, it is never itself the citation).
- `python -m modeler_agents.llm_check [--search] [--ask "…"]`: the served models, a reply, a tool call, a web search
  and a searched answer, with the environment the API will use; never prints a key.
- Verified with mocked HTTP (`test_llm.py`, `test_web_search.py`); the cloud container reaches neither the owner's
  proxy nor ollama.com, so the live check runs on the server.

### Docs — agents verified live on Gemini; the free-tier limit noted
- A1 (proposal intake) ran live on the owner's Gemini key (2026-10-06, in the cloud container, keys only in the
  environment of the run, nothing stored): `gemini-flash-lite-latest` completed with 45 brief fields accepted, each with
  a verbatim quote, 6 rejected by the code checks, and open questions for the missing items. The key is on the free
  tier: 20 requests a day per model; `gemini-flash-latest` (an alias of `gemini-3.8-flash`) had spent its quota, so its
  runs end `LLM_UNAVAILABLE` (HTTP 429). `deploy/server/_env.sh` now says so and names the model override. Groq could
  not be reached from the container (proxy 403); it is untested here.

### Added — the S5 diagnosis shows MS-01 §6.6's own decision tree; a P4 process type can be chosen first
- `feedback.diagnose` places each failing external study on MS-01 §6.6 (1: it differs from the training studies in a
  documented way → limitation; 2: else another external study of its class is left and the class may learn → learn;
  3: else not achievable → limitation) and states the resulting suggestion. It is MS-01 v1.0's existing tree applied
  by code, not a new rule; the decision card and the monitor show it beside the options, and the person still decides
  and signs.
- `PUT /inputs/choices` (process) offers the harvested process types of the accepted evidence when no CPF is assembled
  yet; before, a choice made before the first assembly was refused as "not a harvested process".

### Added — external values blinded until the MAP is signed (D-15, ICH M15 §4.1)
- Per project (`GET/PUT /projects/{id}/blinding`, MIDD lead, with a reason, on the audit chain); by default on when the
  human-confirmed model risk is high (the plan's, else the brief's acceptance tier). While on and no MAP is signed, the
  values of external studies (placed in S5 / S6, or entered for external validation) are withheld from the evidence
  page, dataset artifacts and their history, and the study catalog (`modeler_project.blinding`, applied in
  `project_api.redact`); metadata and times stay. A curator reveals one dataset for a check with a reason
  (`POST /datasets/{id}:reveal`, an audit event). The MAP signature lifts it.
- UI: blinded datasets say so on the evidence page with "Reveal for this check"; the plan page shows the state and the
  switch (`blinding.spec.ts`).
- Known limit: source documents (papers, the client's raw files) are not blinded; blinding covers what the platform shows.
- Fixed the same day: the study list published at P4 for the campaign path (`GET /projects/{id}/studies`) still carried
  blinded studies' profiles; it is redacted the same way. The drop dialog now says when a move is a MAP deviation (D-14).

### Added — MAP deviations after the signature (D-14, ICH M15 §4.2)
- Once the MAP is signed, a change on the canvas (placement, fit, structure, acknowledgement, A5 decision, rebase on
  new inputs; not the layout) is no longer refused: it is recorded on the plan as a deviation (kind, target, what
  changed, reason, who, against which signed MAP version) and applies to nothing until the MIDD lead signs it.
  Signing (`POST /plan:sign`, step-up, record type `map-deviation`) makes a new MAP version that supersedes the signed
  one, states every deviation in its rationale and limitations, restages the campaign inputs and marks the deviations
  signed. Signing with nothing changed is refused. The canvas lists pending deviations, renames the button "Sign the
  deviation(s)" and hides "Run" until they are signed (`model-plan.spec.ts` covers it).
- Why: D-14 (owner: deviation with signature). Refusing every change after signature forced a new project for a
  correction; an unrecorded change would break the link between a campaign and the plan it ran.

### Added — the T-56 proof kit: Dapagliflozin from a mock proposal through P0 → P6, with a trace report
- `deploy/proof/run_t56.py` (and `deploy/proof/README.md`) drives the API the web app uses: **prepare** starts a
  project from a mock technical proposal (`deploy/proof/dapagliflozin/proposal.md`, labelled MOCK, no values), fills the
  brief by hand from it (each field citing its section), derives the data plan, proposes every parameter of the
  published OSP Dapagliflozin model as evidence citing the model and its ValueOrigin text (42, `OSP_LIBRARY`, each on
  its data-plan item or carried with its group's item, said so), proposes the 39 clinical datasets the model carries
  with their PubMed link and figure (statistic as the snapshot records it), and delivers the fed arm of Kasichayanula
  2011a in the client-data template as the mock client's study. **accept** records the owner's decisions under their
  own name (`--as`) up to P5 and stops before the MAP signature (a person's act, step-up, in the web app); **start**
  runs the campaign from the signed MAP; **trace** writes `trace.md` — every CPF parameter → evidence → source, every
  judged study → dataset → publication, the ledger, the MAR's evidence index — and exits 1 on any broken link.
- Verified in software (`services/api/tests/test_t56_kit.py`): P0 → P5 with nothing blocking, the campaign refused before
  the signature, a stub-engine campaign started from the signed MAP, the trace complete with "Not a PBPK result" stated.
- **Departures from Appendix A, and why:** no dissolution table (no measured profile is public; the release item is
  answered from the published model's Weibull, with the reason, rather than inventing data); no scripted canvas move
  (the MS-01 default already keeps 33 studies external, and a move is the reviewer's choice); no fits by default
  (every value is the published one; freeing parameters on D1/D2 is the reviewer's choice, so the default run judges
  the published model through P0–P5); A2 is not used (the values are entered by the manual path; A2 needs a provider
  key). The PK-Sim run itself is the server's (`deploy/proof/README.md`).

### Changed — MS-01 v1.2 (UNVERIFIED): external-validation feedback cycles (T-55, plan §12.3 N4 / §12.4, D-05, D-06)
- **Science change, owner-approved (D-05: one learn cycle per class, more only by a signed deviation; D-06: new evidence
  re-judges the same external studies, flagged, with a model-risk review), UNVERIFIED pending SME sign-off; MS-01
  bumped to v1.2** (`docs/PBPK_MODELING_WORKFLOW.md` status line and §6.6; `campaign.map.MS01_VERSION`).
- **Diagnosis** (`modeler_orchestrator.feedback.diagnose`, `LocalExecutor._diagnose_s5`): when S5 fails, each failing
  external study with the metric that failed, the direction (predicted / observed), its class, how it differs from the
  training studies (fed with no fed training, formulation, dose range, multiple dose), and the parameters acting on it —
  the engine's sensitivity for that study from the models S5 simulated (`prepare_feedback_sensitivity`), else the
  structural map. Per class: the external studies left, the learn cycles used, and whether learn is possible.
- **The decision** (review inbox, `POST /campaigns/{id}/feedback:decide` or `escalation:resolve` at S5), signed; the
  signature binds the decision's content (`feedback.decision_digest`). Guardrails are checked before the signature
  (`check_feedback`, 409): only failing studies can be learned; a class with no other external study cannot learn
  ("not achievable", recorded); the cycle cap; new evidence must name a CPF parameter, give the value in the CPF's
  own unit (no conversion), inside its plausibility range, with its source.
  - *limitation* (`accept_best`): recorded on S5 (and in the MAR's limitations), the campaign goes on to the S4/S5
    signature.
  - *learn*: a new MAP version (supersedes the signed one, signed by the decision) moves the studies to INTERNAL at the
    stage their class trains and S4; cycle c+1 runs [S(k), SJ, S4, S5, S6 …] — the affected stage only (MS-01 §6.6),
    SJ re-judges and refines every internal study — and S5 judges the external studies left.
  - *new evidence*: CPF vN+1 with the parameter fixed at the measured value (provenance: measured, source, the value it
    supersedes); cycle c+1 re-runs S1 → S5; S5 is noted "prompted by S5 … model-risk review (D-06)".
  - *stop* (`abort`): recorded.
- **Record**: campaign `cycle`, `feedback` (every decision), `feedbackPending` (the diagnosis while waiting); rounds and
  ledger entries carry their cycle (a learn is a ledger event, a new value a parameter change); the MAR's development
  history names the cycle. A cycle's artifacts never overwrite an earlier cycle's: `CampaignRequest.cycle` /
  `RoundContext.cycle` suffix round stems, fitted-CPF files and the SJ map (`-c2`; cycle 1 names unchanged).
- **UI**: the review inbox shows the diagnosis, disables an option the guardrails forbid with the reason, asks for the
  studies (learn) or the measured value and source (new evidence); the monitor shows the feedback timeline, the
  pending diagnosis, and a Cycle column on rounds.
- Verified on the scripted executor with a real MAP and CPF (fed-1 fails S5 → learn → S3 refit with fed-1, no-regression,
  SJ, S4, S5 on fed-2 and fed-3; a single fed study cannot learn; new evidence re-runs S1 → S5 with the value fixed),
  the API (refusal before signature, signature bound to the content) and the browser (seeded S5 failure → signed
  limitation). **Known gaps:** the Temporal workflow does not run feedback cycles (single-node only, like SJ); A6 does
  not propose a feedback decision; the PK-Sim acceptance (Dapagliflozin fed failure → learn → S5 on the remaining fed
  study) is the server's.
- **Departures from plan §12.3 / §12.4:** (1) the "work queue" is the persisted continuation — a decision writes the
  cycle's stage list into the campaign's resume state and the existing `LocalExecutor.run` runs it — rather than a
  rewrite of `run` as a queue: the same behaviour, and a cycle survives a restart the way an escalation does.
  (2) Quantitative influence is computed after S5 on the failing studies and in S6 on the internal studies, not after
  SJ (one more engine pass per campaign for a view S6 already gives); the structural map is there throughout.

### Added — the change ledger and the influence map (T-54, plan §12.3 N5 / N6)
- **Change ledger** (`modeler_orchestrator.history.Ledger`, kept on the campaign record as `ledger`): every change of
  the working parameter set is an entry (a fit round in S1–S3, a joint estimate that was kept) with the stage, the
  cause, the parameters that changed (value before → after, unit, status, fitting stage; read from both CPFs, or a note
  when they are not readable) and every study verdict the new set moved (fail → pass, pass → fail, with the model sets).
  A study's verdict comes from its round flags (AUC or Cmax out of limits = fail). A verdict that changes is attached
  to the entry that introduced the parameter set it was judged on; a trial estimate that was not kept (a rejected
  joint fit) moves nothing. A resumed campaign continues its ledger.
- **Influence map** (`history.influence_map`, campaign record `influence`): fitted, fittable and predicted parameters
  × the studies the signed MAP simulates. Structural layer: whether the parameter is in the study's simulation
  (compound parameters: every study; `form.<name>.*`: the studies of that product; `food.*`: fed studies). Quantitative
  layer: the engine's normalized local sensitivity of AUC and Cmax from S6, for the parameters S6 ranked among a
  study's most influential. Recomputed after every stage on the working parameter set.
- **Monitor**: "Model development history" (the ledger) and "Influence map" (heat map; blank = not in the simulation)
  cards. **MAR**: section 4 gains the SJ subsection when SJ ran and "Model development history" (table
  `development_history`) from the ledger.
- Why: with the non-linear backend a verdict can change because of a later stage's fit; the reviewer must be able to
  see which change caused it (plan §12.1, §12.3). Verified on the scripted executor (S2's fit makes po-1 pass and
  breaks iv-1, the joint refit mends iv-1: both listed under the change that caused them) and on the stub engine in
  the browser (structural map only; the stub's numbers are not evidence). The sensitivities in the map are PK-Sim's
  once S6 runs on the server.

### Changed — MS-01 v1.1 (UNVERIFIED): stage SJ, joint refinement, and the budget split (T-53, plan §12.3 N3, D-04)
- **Science change, owner-approved (D-04: SJ yes, equal weights per study, S1-CI guard, budget S1 20 / S2 20 / S3 7 /
  SJ 15 %), UNVERIFIED pending SME sign-off; MS-01 bumped to v1.1** (`docs/PBPK_MODELING_WORKFLOW.md`, status line,
  new §4 SJ, §7; `campaign.map.MS01_VERSION`, `STAGE_PLAN["SJ"]`, `BUDGET_FRACTION`).
- **SJ** (`modeler_orchestrator.joint`, `LocalExecutor._run_joint`): between S3 and S4, one parameter identification
  over every internal study of S1–S3 at once, refitting the parameters those stages fitted from their sequential
  estimates; a parameter fitted at S1 is held within its S1 95 % CI (compensation guard). Round 1 judges every internal
  study on the sequential estimates; round 2 is the joint fit. The joint estimate is kept only if every internal
  study passes and the agreement (mean AUC / Cmax GMFE) is no worse; otherwise the sequential estimates stay and the
  stage says why. Nothing fitted in S1–S3: SJ is skipped. The joint round is judged on a derived MAP next to the
  signed one (its internal scenarios relabeled SJ), so the evaluation code is unchanged.
- **A regression (T-52) is first answered by a joint fit** over the stages up to the regressing one; the stage passes
  with the joint estimate if it restores every study, else escalates with the regression and the joint attempt named.
- Campaign stages are now S0, S1, S2, S3, **SJ**, S4, S5, S6, S7 (`CAMPAIGN_STAGES`); the MAP's stage plan has SJ
  (540 s of a 60-minute budget). A fit action may name several parameters (`fit a+b`, `_build_fit_request`; one target
  resolves as before). The Temporal workflow skips SJ with the reason (single-node only, like S6/S7). The D3 canvas
  shows the SJ node.
- **Known gap:** equal weight per study (D-04) needs weights per output mapping in `run_pi.R`; until verified, points
  are weighted equally and the stage records it. All of this runs on the stub engine and a scripted executor here;
  the PK-Sim acceptance (Dapagliflozin joint fit ≥ sequential on every internal study, budget measured) is the server's.

### Added — the no-regression gate (T-52, plan §12.3 N2)
- When a fit stage (S2, S3) passes with a parameter set different from the one it started from, every earlier fit stage
  that had passed is simulated again from the new model set and judged against its own gate (its internal studies
  only; external studies stay unseen until S5). Each re-check is a round on that stage ("no-regression check with S2's
  CPF", with its model set). A study that passed before and fails now is a regression: the stage escalates with reason
  `regression` and the findings name the earlier stage and why, so the campaign stops before S4 instead of S4
  escalating later as if something unrelated broke. A stage that did not change the parameter set triggers no re-check.
- Why: a parameter fitted at S2 or S3 that also acts on IV studies (logP, fu, a clearance) was not re-checked against S1
  until S4 (plan §12.1). The joint refit that resolves a regression is T-53.
- Verified on a scripted executor (control flow); the PK-Sim acceptance (a deliberate S2 logP change that breaks S1
  is caught before S4) is to run on the server.

### Added — Lane B start: model sets and memoized engine runs (T-51, plan §12.3 N1 / N7)
- **Memoized runs** (`modeler_orchestrator.memo.MemoEngine`): an engine job is keyed by its task, the content hash of
  every input, its options (seeds included) and the engine (command and image digest). An identical job that already
  succeeded, whose outputs are still there with their hashes, gets those outputs copied into its own output directory
  and a manifest marked "memoized"; no engine process starts. A missing or changed output, or a failed earlier run, is a
  miss. S7's reproduction re-runs (`-S7-rerun-`) always run (D13). On by default for the configured engine; an injected
  engine (tests) only when asked (`run_campaign(memo=True)` or `MODELER_MEMO=1`). Memo records live under
  `<read root>/<tenant>/memo/`.
- **Model sets**: every judged round records `modelSet` (CPF content hash, engine, hash of the stage's MAP scenarios,
  builder version, an id), so each verdict names the one parameter set it judged.
- Why: propagation and joint refinement (T-52 / T-53) re-simulate every internal study after each change; without
  memoization a repeated cycle would cost the engine time twice. Verified with stub engines only (a second identical
  campaign starts no engine job); the saving on PK-Sim is to be measured on the server.

### Added — P5 model plan: the canvas (D1, D2, D3), live validator, A5, MAP from plan, signature (T-50)
- **ModelPlan** (`modeler_project.plan`, MODEL_PLAN/main): starts as the MS-01 default computed exactly as today
  (`split_studies`, the MAP's own training-stage rule, the stage plan's fit candidates resolved on CPF v1, budgets);
  each study's role (S1 / S2 / S3 train, S5 external, S6 application, supportive), fit choices, structure (objective,
  context of use, model risk, food effect, planned applications, from the brief), A5 rationales and proposals,
  acknowledged warnings and the canvas layout. A person's change carries a reason and is **userLocked**: rebasing on
  new inputs or a structure change moves only unlocked placements; A5 cannot touch a locked one.
- **Live validator** (MS-01 §3.3 rules 1, 3, 4, 5; class ↔ training stage; profile needed to train; core vs applied
  studies; fit stages and bounds; reasons; real data). Errors block; warnings block until acknowledged with a reason
  and then become MAP limitations. A drop is validated (dry run) before the person confirms it.
- **MAP from plan** (`map_from_plan`): the plan's placements as the split, its fits as the campaign CPF's fit policies,
  its changes and acknowledged warnings in the MAP's rationale and limitations, through `generate_map` unchanged (one
  public helper added to `campaign/map.py`: `training_stages`). With no change it equals `generate_map` (content hash).
- **Agent A5** (`modeler_agents.planning_agent`): explains every assignment and proposes departures with reasons;
  code refuses a proposal on a person's choice or one that breaks a rule; the person accepts or rejects each in the diff.
- **Sign** (`POST /plan:sign`, role modeler-reviewer = MIDD lead, D-07): refused while anything is open; the MAP is
  generated, signed from the token's step-up (meaning Approved, bound to its content hash), the campaign inputs are
  staged like `campaign:prepare` (campaign CPF, signed MAP, observed PK with origins), plan and MAP are approved (P5
  gate). Later changes are refused (a MAP deviation, D-14).
- Web `/projects/{id}/plan`: "Overall Data" side panel; D3 development and validation DAG with native HTML5 drag and
  drop onto nodes, the arrows into a stage and the training layer, node re-layout; D1 disposition and D2 absorption /
  formulation (read-mostly, D-13) with fit forms; the validator; the diff (MS-01 default → plan, A5 proposals); Approve
  and Sign; Run the campaign (P6). Integration plan and departures from plan §11.4 (no React Flow; new data placed by
  the default and marked; edge drops) in `docs/P5_PLAN_CANVAS.md`.
- Fixed: the P4 readiness read the brief's food-effect application by code (`APP-12`) against stored labels
  (`APP-12 food effect`), so food effect in question was never seen there; both P4 and P5 now read the code.
- **Known gap:** A5 has run only against a scripted model; MAP deviations after signature (D-14) and project-wide
  blinding of external values (D-15) are not built yet.

### Added — P4 model inputs: CPF v1 from accepted evidence, the study catalog, readiness (T-49)
- **CPF v1 is assembled, never typed** (`modeler_project.inputs`): one record per accepted evidence item, its value in
  the PK-Sim unit (logP in the builder's "Log Units"; pKa as `phys.pka.{acid|base}.i` from the stated conditions), its
  provenance carried into PK-Sim's `ValueOrigin`: Source and **Method** from the harvested enums only (Method values
  harvested from the OSP fixtures: InVitro, InVivo, Assumption, ParameterIdentification, Other, Unknown), the citation,
  locator, evidence source type and grade in the description, and the evidence id@version on the record
  (`Provenance.method`, `Provenance.evidence`, new optional fields; the builder writes Method only when set). Two
  accepted values for one parameter are named, never averaged or chosen between.
- **Process parameters are bound from the harvested table** (`pbpk_domain.cpf.process_bindings`, the OSP import's
  process table, now public as `PROCESS_PARAMETERS` / `PROCESS_FAMILY`): GFR fraction, total hepatic / renal clearance
  bind directly; a quantity carried by several process types (`CLspec/[Enzyme]` on `MetabolizationSpecific_FirstOrder`
  and `rCYP450_FirstOrder`) waits for a person's choice with a reason (`InputChoices`, also the formulation a solid
  study used and studies left out); a value in another unit than the builder places is named.
- **Study catalog** from the accepted datasets (origin kept; the mean / median series is the judged profile; PK-parameter
  and individual-only datasets are listed as not judged by the current campaign, with why).
- **Readiness** (READINESS/main): the S0 rules (completeness, placeable pathways, expression profiles, from
  `pbpk_domain`), formulations of solid studies, observed data to judge on, the real-data rule, the default MS-01 split,
  and a **software build of every planned simulation** (`build_stage_snapshot` on a default MAP). Loading the snapshots
  into PK-Sim (the engine dry run) needs the engine and is stated as not run here. P4 closes with a named acceptance
  when ready; `inputs:publish` hands CPF v1 and the judged studies (with their origin) to the campaign path.
- API `/projects/{id}/inputs` (`:assemble`, `/choices`, `:accept`, `:publish`); web `/projects/{id}/inputs` with tabs
  mirroring PK-Sim's building blocks (Compound, Formulations, Individuals, Simulation settings), Studies and Readiness;
  P3 and P4 pages refresh the phase rail after each action. Playwright covers the flow.
- **Known gap:** the engine dry run (PK-Sim loads every snapshot) runs on the server; `ValueOrigin.Method` in built
  snapshots is untested on PK-Sim until that run (the values are those of the OSP snapshots PK-Sim loads).

### Added — dissolution: canonical profiles, checks, f2 and the Weibull fit in PK-Sim's parameterization (T-48)
- **Profiles** (`pbpk_domain.dissolution`, `modeler_project.dissolution_register`): every client file's dissolution rows
  (template, or a confirmed mapping recipe) become canonical profiles, one per product × role × strength × batch ×
  apparatus × rpm × medium × pH × volume, with times in minutes, per-vessel values, mean, SD, CV, n and the source cells
  (DISSOLUTION artifacts, rebuilt idempotently; a profile repeated in a later file is replaced by it, and the replacement
  is noted).
- **Checks** say which release model the data support: Weibull; Dissolved (≥ 85 % within 15 min, MS-01 §4 S2); or
  Table, for release that plateaus well below complete (refused as a Weibull release model; table formulations are not
  placed by the builder yet). Means above 110 %, dissolution at t = 0 and falling means are flagged.
- **f2** for each TEST profile against the RLD / REFERENCE profile under the same conditions, computed only when its
  conditions hold (12 units, ≥ 3 points, one point after 85 %, CV ≤ 20 % early / ≤ 10 % later); otherwise the reasons;
  both ≥ 85 % within 15 min is similar without f2. Conditions are ruleset data: **new ruleset
  `rulesets/dissolution_similarity.yaml` (2026.1-draft, UNVERIFIED)**, owner-approved with the plan, awaiting SME sign-off.
- **Weibull fit**: deterministic least squares of t50 and shape (lag 0, as the OSP tablets have it), with standard
  errors and RMSE, in PK-Sim's parameterization (`Dissolution time (50% dissolved)` min, `Dissolution shape`, `Lag time`
  min, harvested from the OSP formulation catalog): fraction dissolved = 1 − exp(−ln 2 · ((t − lag)/t50)^shape). A person
  proposes a profile as a formulation's release model (D-12: the choice is a planning decision); its values become
  evidence (`form.<name>.type`, `form.<name>.weibull.t50/shape/lag`, extraction COMPUTED, grade C) to accept like any
  other. Evidence assessment now keeps flags that start with `unconfirmed`.
- Web: a Dissolution card on the L2b page (mean points with the fitted curve, t50 / shape ± SE, f2 verdicts with the
  ruleset version, propose-as-release-model). Playwright covers it.
- **Known gap:** the equation has not yet been compared with PK-Sim's own release curve on the engine (plan harvest
  rule; acceptance "within 1 %"): `ENGINE_CONFIRMED` is False and every proposed Weibull value carries the
  `unconfirmed` flag until that run is recorded on the server (e.g. the OSP Dapagliflozin IC tablet, t50 30 min, shape
  0.6, dissolved fraction over time against the equation).

### Added — P3 client data: the client-data template, sheet triage, agent A4 and reconciliation (T-47)
- **Client-data template** (`modeler_intake.client_template`, `GET /client-data/template.xlsx`, plan §10.2, D-11):
  README plus Studies, PK_Individual, PK_Summary, PK_Parameters, Dissolution, Product, Physchem_InVitro, Urine_Feces;
  one column list builds the download and reads the upload, so they cannot drift. Read with no AI: typed per column,
  enumerations checked, BLQ / `<LLOQ` kept as below-LLOQ, every value with its cell; a value that does not parse (a
  decimal comma, a unit in the cell), a value outside the allowed list, a missing required value, a renamed column are
  reported with their cell, never guessed.
- **Into the project** (`modeler_project.client_data`): each study arm becomes an observed dataset (origin CLIENT,
  extraction CELL; individual series per subject, summary series per statistic, NCA rows as reported PK; locator and
  the quoted row line point at the cells); each Physchem_InVitro row an evidence item quoted from its row and matched to
  its data-plan item (graded like any other evidence: a row that does not state a required condition is grade B).
  Dissolution, product and urine/feces rows are kept with their cells for T-48 / T-49. Doses and products that the
  brief does not mention are listed as questions (plan §10.1 step 7). The same bytes uploaded again change nothing.
- **Any other workbook** (`modeler_intake.triage`): each sheet is classified by the words of its first rows, quoting
  the deciding cell; undecided sheets go to **agent A4** (`modeler_agents.sheet_triage`), whose classification is
  recorded only when code finds its quoted header in that cell; a person can change any. Data are read from such a
  sheet only with a mapping recipe a person confirms (preview shows records, problems and open questions; confirming
  needs none). PDF, Word, CSV and Markdown files are stored as citable documents (owner, §3 #15).
- **Reconciliation** (plan §10.1 step 6): per client item of the data plan, delivered / partial (e.g. "2 of 3 promised
  media", from the proposal's own words) / missing / not available, and what arrived that the plan did not promise.
  The P3 gate (CLIENT_SUBMISSION/register, named approval) refuses while a required client item is missing; the person
  skips it as not available or switches on the literature cross-check (owner, R-07).
- Web: the L2b page `/projects/{id}/client-data` (template download, upload, per-file sheet triage with changes and
  reasons, problems with their cells, recipe mapping with preview, reconciliation with skip / cross-check, approval).
  Playwright: template downloaded, a filled template and a raw workbook uploaded, the decimal comma named at its cell,
  a sheet reclassified with a reason, the client dataset shown with origin client.
- **Known gap:** A4 has not run against a live provider yet (scripted model in tests); the data-mapping agent that
  drafts recipes still uses the older Anthropic client and is not wired to the L2b page (a person writes the recipe).

### Added — the real-data rule: only real observed data can sign off a model (T-46, plan §9.4, D-19)
- **Why:** a campaign could reach "passed" on the illustrative Aciclovir profile or on simulated data, and nothing on
  the monitor or in the MAR said so ("without any data we completed results").
- **Origin everywhere** (`pbpk_domain.data_origin`, shared with `modeler_project.datasets`): a study upload takes
  `origin` (CLIENT, LITERATURE, FIGURE_DIGITIZED, OSP_LIBRARY, SYNTHETIC, ILLUSTRATIVE; anything else is refused);
  `campaign:prepare` writes it into the observed PK and returns each study's origin and the studies with no observed
  data (not evaluable). The OSP templates and the showcase systems label their studies OSP_LIBRARY; the illustrative
  Aciclovir profile is relabelled ILLUSTRATIVE; the dev case studies (analytical stand-in data) SYNTHETIC. The CSV
  intake asks where the data come from (its example data is ILLUSTRATIVE).
- **Verdicts say what they rest on:** every round records how many judged studies were real and from which origin.
  A pass judged on data that is not real is shown as **"TEST ONLY: no real observed data"** (or "origin not recorded
  for n of m"), on the monitor (red banner, per-round "n of m real") and in the MAR round tables. A study without
  observed data is not evaluable and never counts.
- **The S4/S5 signature is refused** (API 409, before a signature is taken; the runner refuses too) when any stage
  S1–S5 judged a study that is synthetic, illustrative or of unrecorded origin, unless the project is
  **exploratory** (`POST /projects` `exploratory`; the wizard sets it for the illustrative example, the dev case
  studies and the showcase's illustrative check). Stopping the campaign stays possible.
- Impact: the local-runner tests now label their golden PK-Sim data SYNTHETIC in exploratory projects and expect
  TEST ONLY verdicts. A project created through the API without origins can no longer sign S4/S5 until each study's
  origin is recorded.
- **Known gap:** the Temporal backend (`escalation:decide`) does not apply the signature refusal yet; the local
  backend is what runs today. Accepted P2 datasets do not yet flow into the campaign's studies (T-49).

### Added — P2 observed data: datasets with their origin, agent A3 and the figure digitizer (T-45)
- **Observed datasets** (`modeler_project.datasets`, `dataset_register`): every clinical PK dataset is a DATASET
  artifact (proposed → accepted / rejected with a reason) carrying the study design, analyte and matrix, one or more
  series (statistic, error kind, n, values below LLOQ kept as such), reported PK parameters, the source page and
  locator, and its **origin** (CLIENT, LITERATURE, FIGURE_DIGITIZED, OSP_LIBRARY, SYNTHETIC, ILLUSTRATIVE). Code flags
  what a person must look at: too few time points, a profile that never declines, a reported AUC or Cmax that the
  profile's own NCA does not reproduce (> 20 %), a design that contradicts the data plan. Coverage now includes the
  data plan's observed-data needs.
- **Agent A3** (`modeler_agents.observed_data_agent`): extracts tables only when every row carries a verbatim quote
  from the stored page that contains that row's time and value (checked by code; one bad row refuses the whole
  table); figures become digitization requests for a person, never values the agent reads off a picture.
- **Digitizer** (`pbpk_domain.digitize`, web `Digitizer`): a person calibrates two references per axis (linear or
  log) on the PDF page or uploaded image and clicks the points; code maps pixels to values and records the click
  resolution. A digitized dataset can be accepted only after its overlay is approved by a named person. Uploads now
  take PNG / JPEG figures (stored as documents without text).
- API `/projects/{id}/datasets` (manual entry, `:digitize`, `:overlay`, `:decide`) and `evidence:research?agent=A3`;
  the L2a page gains an Observed data tab. Playwright: a drawn figure with markers at known values is digitized to
  within 1 % of the truth (1 h → 0.999 h / 100.3, 2 h → 1.996 h / 75.4, 4 h → 3.99 h / 50.5), approved and accepted.

### Added — P2 literature evidence: the evidence register and agent A2 (T-44)
- **Evidence register** (`modeler_project.evidence`, `evidence_register`): every value that may enter a model is an
  EVIDENCE artifact (proposed → accepted / rejected, each decision a new version with its reason) carrying the
  source (document page, locator, title, authors, year, DOI / PMID / URL), the verbatim quote, the conditions, the
  extraction method, the purpose and the provider. **Code** converts the stated value to the PK-Sim storage unit
  (`pbpk_domain.parameter_units`: plain unit changes only; CLint → CLspec is IVIVE and waits for a person) and grades
  it A–D (plan §8.4) with flags (value not in the quote, missing conditions, species mismatch, physically impossible
  value). Conflicts (> 2-fold between items of one parameter) are computed when read, shown side by side, never
  averaged. Coverage per data-plan item; the P2 gate closes only when every required literature item has accepted
  evidence or is recorded as not available (which changes the data plan, re-approved).
- **Agent A2** (`modeler_agents.evidence_agent`) on the provider-agnostic loop: searches Europe PMC, reads abstracts
  and open-access full texts (`modeler_agents.sources`: JATS → text with tables as rows) and the uploaded documents;
  every text is stored as a document before it can be cited, and every proposal is checked by code against exactly
  that text. Papers that are not open access become access requests that a person fulfils by uploading the PDF.
  Europe PMC is unreachable from the build container (tested with a mocked API); the server must reach it (D-17).
- API `/projects/{id}/evidence` (view, `:research`, manual proposal with a checked quote or a DOI / PMID / URL,
  `:decide`, `:approve`) and access-request fulfilment; data-plan items can be marked not available. Web: the L2a page
  (`/projects/{id}/evidence`) with proposals side by side per item, grades, flags, quotes and the source page; the
  Playwright flow covers the manual path.

### Added — the P1 data plan and the feasibility check (T-42 / T-43)
- **Requirement templates** (`pbpk_domain/requirements/*.yaml`, **UNVERIFIED**, version 2026.1-draft; owner-approved
  with the plan, awaiting SME sign-off): the core small-molecule template (MS-01 §2.2 parameters with their PK-Sim
  locations as MS-01 records them, the MS-01 §3.3 observed-data needs) and application templates for VBE, food
  effect, DDI, special populations and FIH. Items not in the harvested catalog are marked *to harvest*, never named.
- **The data plan** (`modeler_project.requirements`): derived deterministically from the brief. A condition is
  true, false or *undetermined* when the brief does not say (shown, never assumed); formulation items repeat per
  solid product. Each item's provider comes from a person's override (kept across re-derivations), else the
  proposal's own data-plan statement (its words shown), else the template default; a client item can be flagged for
  a literature cross-check (D-02). P2 searches exactly the literature items and the flagged client items.
- **The feasibility check** (`modeler_project.feasibility`, plan §7.5): each feature the brief needs (modality,
  routes, release types, expression profiles of the named proteins, clearance processes, populations,
  applications) as supported, limited, needs harvest, not supported or undetermined, with the route to support.
- API `/projects/{id}/requirements` (derive, view, override with a reason, approve); approving the brief derives the
  data plan at once, and the P1 gate closes when both are approved. Web: *Data plan* and *Feasibility* tabs on
  the P1 page; the Playwright flow covers them.

### Added — P0 initiate and the P1 Project Brief (T-41), with agent A1
- **Start a project from its technical proposal** (`/projects/start`, `POST /api/v1/projects:initiate`): the drug
  name, any context, and any number of PDF, Word, Markdown, text, CSV or Excel files. Each file is kept unchanged in
  the write-once blob store and read into quotable pages (`modeler_intake.documents`: pypdf, python-docx, openpyxl);
  a PDF without a text layer is reported as needing OCR, never guessed. The typed context is stored as a document
  too, so it can be cited like the proposal. The earlier wizard stays as the quick start.
- **The Project Brief** (`modeler_project.brief`, plan §6): one fixed schema for every project, sections A–J; every
  field is a record with status (entered, extracted, retrieved, computed, edited, confirmed, missing, not
  applicable), citations (document hash, page, verbatim quote, locator) and a confidence grade. Lists (products with
  TEST / RLD roles, scenarios, populations, the data plan of who provides what) are groups. Approval (D-07: a named
  "Reviewed" approval) is refused while a required field is missing or a question is open.
- **Agent A1** (`modeler_agents.proposal_intake`): proposes one field at a time; code accepts it only if the field
  and option exist, the number fits, and the quote is found verbatim on the cited page; rejections go back to the
  model with the reason. A field a person entered, edited, confirmed or marked not applicable is never overwritten
  (merged after the run, so edits made during it survive), and the M15 ratings and risk tier are never proposed.
  Live on Gemini (`gemini-3.1-flash-lite`) with a synthetic proposal: 36 fields accepted with verified quotes,
  2 rejected by the citation check. Agent runs and every step are kept per tenant (`FileRunStore`).
- **Drug identity**: PubChem lookup stored as a retrieved-record document (values quoted from exactly what PubChem
  returned) and an RDKit cross-check (formula, MW, InChIKey, halogen counts; a stated MW that disagrees with the
  structure raises a question). PubChem is blocked from the build container; it must be reachable from the server.
- **The L1 review page** (`/projects/{id}/brief`): the brief by section beside the source document, citation chips
  that open the page with the quote marked, inline edits that require a reason and can preview their impact, open
  questions, and what blocks approval. Playwright flow `e2e/start-project.spec.ts` (upload → brief → edit → history)
  passes against the real API.

### Added — agents on Gemini or Groq (decision D-16)
- **`modeler_agents.llm`**: one OpenAI-compatible client for the owner's two providers (Gemini, Groq) and a
  provider-agnostic tool loop: the model calls tools, deterministic handlers check and record what it proposes and
  answer it (rejections included), and every model turn and tool result goes to the agent run's step log. Retries
  with backoff on overload / rate limits (429, 5xx), no retry on a refusal. Selected by `MODELER_LLM_PROVIDER`
  (`gemini` | `groq` | unset = agents off, manual paths only); keys only from `GEMINI_API_KEY` / `GROQ_API_KEY`.
- **Gemini needs its thought signature echoed back**: a follow-up turn whose function call lost
  `extra_content.google.thought_signature` is refused (HTTP 400, seen live on 2026-10-05). The loop returns each
  call exactly as the provider sent it. Verified live on the owner's key: tool calls work on `gemini-flash-latest`,
  `gemini-3.5-flash`, `gemini-3.1-flash-lite`; the pro models are over the key's free quota and the free tier
  throttles quickly (429). Groq is unreachable from this build container (network policy) and untested live.
- **Server**: `deploy/server/_env.sh` sources `~/.modeler-secrets.env` (owner-only, outside the repository;
  template `deploy/server/modeler-secrets.env.example`). The keys pasted into the plan should be rotated.

### Added — project start-up pipeline, T-40: versioned artifacts, staleness, impact preview, audit chain
- **New workspace package `packages/project-model` (`modeler_project`)**, the spine every phase P0–P6 stores into
  (plan §13). An artifact version is immutable (written once), hashed, and names the exact upstream versions it was
  derived from. An edit creates the next version and needs a reason; everything made from the old version is
  reported **stale** with that reason (computed, never stored, so it cannot drift), never deleted or silently
  redone. Approvals bind a version's hash and are refused for stale or superseded versions.
- **Impact preview** (`POST /api/v1/projects/{id}/impact`): the field changes an edit would make and every
  artifact it would make stale, with the effect (re-derive, re-review, signature needed: a signed MAP is superseded
  and its campaigns invalidated) before anything is saved.
- **Single-node audit trail**: every commit and approval is appended to a per-tenant hash chain
  (`<root>/<tenant>/audit.jsonl`) with the same event shape and row hash as the Postgres `audit_events` table (a
  test pins identical hashes), so it migrates unchanged. Before this the single-node store kept no audit trail.
- API: `/projects/{id}/phases`, `/artifacts`, `/artifacts/{kind}/{id}` (+`?version=`), `/history`, `/audit`. Web:
  a **phase rail** (P0–P6 with status) on project pages and a **History** page (stale items with reasons, every
  version with its field changes and approvals, the audit trail and whether its chain verifies).

### Docs
- **The start-up pipeline plan is approved (owner, v0.2, 2026-10-05) and its build has started.** The owner answered
  D-03 (fold tiers + symmetric PE limits + the proposal's own criteria, all metrics gating; ruleset change
  owner-approved, stays UNVERIFIED) and D-16 (Gemini or Groq), and approved the rest as recommended; the plan's new
  §21 records how the build applies each answer, and the owner's P5 canvas specification is kept in §5.2. **Two API
  keys the owner pasted into the plan were removed before commit**: keys come only from host environment variables.
  The branch now also carries the parallel session's work (`main-1czavz`, merged so this build sits on the current
  importer, wizard and runner).
- **Draft plan: the project start-up pipeline (P0–P6) and a non-linear model backend**
  (`docs/plans/2026-09-25-project-startup-pipeline.md`, DRAFT, awaiting the owner's answers and approval; nothing
  built). Why: campaigns so far were judged against illustrative or self-simulated profiles, and every input (CPF,
  studies) is typed in as raw JSON with no document intake, literature work, client Excel handling, reviewable plan
  or way to edit an early decision later. The plan puts phase-gated, multi-agent intake in front of S0 (technical
  proposal → Project Brief, literature and client data with provenance, PK-Sim input pages, a three-diagram planning
  canvas), a rule that only real observed data can pass, and a non-linear backend (no-regression gate, a joint
  refinement stage SJ over all internal studies, external-validation feedback cycles, influence map). SJ and any
  criterion change are MS-01 / ruleset proposals that need explicit approval. Impact: none until approved; it does
  not replace the 2026-09-24 plan, whose Phase 4 continues.
- **Added `CHANGELOG.md` (this file) and `CLAUDE.md`.** There was no change log and the continuation doc was 50
  commits out of date; project context lived only in commit messages and a private assistant memory, so it was lost
  whenever the session or AI model changed. `CLAUDE.md` is loaded into every Claude Code session, which is what makes
  the "record every change" rule stick.
- **Rewrote `docs/CONTINUATION_PACKAGE.md` §4 to the truth**, with a pipeline-coverage table (S0–S7).

### Fixed — the pipeline now runs S0 → S5 (plan item 1.1, plus defects found running it on PK-Sim)
Proven on real PK-Sim (the engine image under Docker on the Mac): an Aciclovir campaign started from a wrong renal
clearance (GFR fraction 0.4) runs S0 → S5 and completes — S1 baseline fails (AUC 2.06-fold), the fit recovers
GFR fraction 1.272, the fitted model passes in the same round (AUC 1.008-fold); S2/S3 are skipped (no oral or
fed study, MS-01 §6.2/§6.7), S4 re-validates the fitted model and passes, S5 is recorded as not achievable (no
external study). The data are the example's illustrative IV profile, not clinical data — real-data proof is Phase 4.
- **R0 — the UI only ever asked for S0 → S1.** The Run button and the new-project wizard hard-coded
  `stages: ["S0", "S1"]`, and `campaign:prepare` defaulted to S0 → S2. Both now run every stage; a stage with no
  data is skipped with its reason instead of being left out.
- **R1 — S4 and S5 now simulate.** The MAP gives every internal study an S4 scenario and every external study of a
  core class (IV, oral fasted, fed, multiple dose, MR, other) an S5 scenario. DDI / PGX / special-population studies
  are named in S5's notes as validating their S6 application (MS-01 §3.3 rule 4).
- **R2 — validation mode.** S4/S5 simulate the final CPF once and judge it; they never diagnose or fit. A failure
  escalates with the MS-01 §6.6 choices (record a limitation and continue, or stop) — no blind retry.
- **A stage with nothing to simulate is SKIPPED with its documented reason** (new stage status), instead of running
  an empty round and escalating. New `plan_stage` activity, used by both the single-node runner and Temporal.
- **S5 judges fasted and fed as separate groups** (MS-01 §8): acceptance comparisons carry a group.
- **R13 (raised to critical) — a fit is judged in the round it happens.** The round simulated the CPF *before* the
  fit and evaluated that, so a successful fit was scored on stale values, its action counted as tried, and the stage
  could run out of actions and escalate although the fit worked. The round now re-simulates the fitted CPF
  (`phase="postfit"`) and judges that. Same change in the Temporal workflow.
- **The campaign's fit could never start** (found on PK-Sim). The fit spec named its models after the round's
  snapshot file, but the engine names exported models after its input (`snapshot-<simulation>.pkml`). Now one
  constant, `ROUND_SNAPSHOT_INPUT`, drives both.
- **Fitting a dimensionless parameter crashed the engine** (found on PK-Sim, GFR fraction). A null unit came back
  from `run_job.R`'s re-serialisation as `{}`; the spec now omits it and `run_pi.R` only accepts a real string.
- **Observed data are converted to the engine's units before any comparison** (new `pbpk_domain.units`). The
  gate compared predicted AUC/Cmax (µmol/l, minutes) with observed values in whatever the study reported — an
  upload in hours or ng/ml was judged 60-fold or MW-fold off. `campaign:prepare` now converts every profile to
  minutes and µmol/l (unknown units → 422), and the fit declares the molar dimension (it declared µmol/l data as
  a mass concentration).
- **The prediction is reduced over the observed window at both ends** (`ObservedPK.t_first`): an IV study sampled
  from 5 min, or a steady-state study sampled over its last interval, was scored against area never measured.
- **Each simulation covers its study's sampling window** (was a fixed 24 h, truncating longer studies).
- **Multiple-dose studies can be simulated**: `dosing_interval_h` / `n_doses` on the study, mapped to the PK-Sim
  schedules found in the OSP reference snapshots only (`DI_24`, `DI_12_12`). Verified on PK-Sim: q12h × 4 gives
  exactly 4 doses, q24h × 3 gives 3 (PK-Sim doses while t < End time).
- **A validation stage simulates every study it can and names the rest** ("NOT SIMULATED: …"); one study the
  builder cannot place yet (e.g. a tablet) no longer stops the others from being judged.
- Monitor rounds no longer say "improved" for a round that merely tried an action; they say passed / no pass, and
  carry per-study and per-group results. Stage notes (skip reasons, studies not simulated) are shown under the stage
  rail. Each stage keeps its own goodness-of-fit plot (`gofByStage`).

### Fixed — enzymes and transporters now act on PK-Sim (plan item 1.2, R4)
- **Every enzyme-cleared drug had been simulated with zero metabolic clearance.** The CPF build never gave the
  individual an expression profile for the enzymes its processes name, so the processes had no protein to act on.
  Proven on PK-Sim: a UGT1A9-cleared compound (CLspec 0.4 l/µmol/min) built the old way gives AUC(0–48 h) 1242.7
  µmol·min/l — identical to no clearance at all. The run looked valid; nothing warned.
- **Expression library harvested from the OSP reference models** (`pbpk_domain/data/expression_library.json`,
  `scripts/harvest_expression_library.py`): 16 proteins (CYP3A4, CYP1A1, UGT1A1/1A4/1A9/2B7, AADAC, P-gp, ABCB1,
  ABCG2, OATP1B1, …) copied verbatim with their per-organ relative expression, half-lives, transport directions and
  ontogeny, each with its source model recorded. A profile needs those tables — with only a reference concentration
  every organ's relative expression is zero and the process still does nothing.
- The CPF build gives every subject the harvested profile of every process protein. Same compound, now: AUC 112.8
  µmol·min/l, t½ 8.5 h — the enzyme clears the drug.
- **S0 refuses a CPF whose process names a protein with no harvested profile** (MS-01 §S0), instead of running a
  model that silently eliminates nothing. Build notes name each profile's source.
- **Transporter direction was being dropped.** The builder wrote `TransporterType`; the snapshot key (per the
  engine-harvested catalog) is `TransportType`, so PK-Sim ignored it and defaulted the direction — an influx
  transporter such as OATP1B1 would have been modelled wrongly. The test fixture that "confirmed" the old key was
  hand-written; corrected.

### Fixed — tablets and the S3 formulation stage (plan item 1.3, R5), and a unit defect in every fit
- **Tablets and capsules can be simulated.** CPF formulations (`form.{name}.type` Weibull | Dissolved,
  `form.{name}.weibull.{t50,shape,lag}`, MS-01 §2.2) become PK-Sim `Formulation_Tablet_Weibull` /
  `Formulation_Dissolved`; lag defaults to 0 min and "use as suspension" to 1, as in every published OSP tablet
  (Dapagliflozin, Midazolam, Itraconazole). A study names its formulation (`formulation_name`); an unnamed one in a
  CPF with exactly one formulation uses it, and the build note says so. Anything else is a named build error.
- **S2 / S3 routing follows MS-01**: an immediate-release solid trains S2 when it dissolves rapidly (its formulation
  is Dissolved) or when no solution study exists (§6.3, the tablet is the S2 reference with its in-vitro Weibull
  fixed); otherwise it trains S3 and S2 uses the solution studies only (§4 S2).
- **S3 can fit the formulation**: Weibull t50 / shape are fitted per simulation at the paths harvested from PK-Sim
  (`Events|<protocol>|<formulation>|Dissolution time (50% dissolved)`, `…|Dissolution shape`, `…|Lag time`), only in
  the simulations that use that formulation, within the CPF fit policy ([0.5×, 2×] of the in-vitro fit).
- **diag-rules 0.2 → 0.3 (UNVERIFIED)**: S3 release-rate rules (too slow / too fast → fit t50, then shape) — the
  MS-01 §4 S3 sub-loop; before this a formulation stage could only escalate. Their evidence is new: `release_slow`
  / `release_fast` = Cmax off with AUC in limits, tmax not contradicting. The absorption evidence's "tmax > 1.25-fold"
  cannot fire at ordinary sampling density (seen on PK-Sim: Cmax 0.80-fold, sampled tmax 90 vs 102 min), so reusing
  it left the rule dead. Flagged for SME review with the rest of the ruleset.
- **Every fit of a parameter whose CPF unit differs from PK-Sim's base unit was stored wrongly** (found on PK-Sim,
  known-truth campaign). `ospsuite.parameteridentification` 2.2.0 drives the optimiser in the parameter's *base*
  unit whatever `PIParameters$unit` says, and setting the unit does not convert the bounds. An intestinal
  permeability "fitted in cm/min" was really fitted in dm/min: the engine found 2.79e-6 dm/min (≈ the truth), we
  stored 2.79e-6 cm/min — 10× too low — and the "fitted" model got worse. `run_pi.R` now converts bounds and start
  to the base unit and estimates, SDs and CIs back to the CPF's unit. logP, GFR fraction, CLspec and t50 share
  their units with PK-Sim, which is why earlier fits looked right; permeabilities and solubility did not.
- **Fit starts run in parallel on the single-node runner**, as many at once as the multistart plan assumed (cores ÷
  simulations per start), capped by the machine's CPUs; `MODELER_FIT_WORKERS` overrides it (e.g. on a laptop's
  Docker engine). They ran one after another, multiplying a planned fit's time by up to 32.

### Added — S6 prediction and S7 report & reproducible package (plan Phase 2, R8/R9)
- **S6 and S7 are campaign stages** (`CAMPAIGN_STAGES` S0–S7; MAP budget split per MS-01 §7: S6 20 %, S7 7 %).
- **Signature gate before S6** (MS-01 §4 S6 "runs only after S4 and S5 are signed", decision D5): after S5 the
  campaign pauses as `AWAITING_SIGNATURE` with a review-inbox item; a signed **approve** (new decision, API and web)
  resumes it into S6/S7.
- **S6** re-simulates the internal studies from the final CPF, then per study runs a local sensitivity analysis over
  every FITTED/PREDICTED parameter (engine `sensitivity`) and propagates the fitted parameters' SD — 200 draws,
  log-normal for log-scaled parameters, truncated to the fit bounds — through an engine `batch` to 5/50/95 %
  intervals of AUC and Cmax (`pbpk_domain.campaign.prediction`). Parameter correlations are not propagated yet.
  Application templates (DDI, paediatric, organ impairment, VBE) remain the next phase (T-31).
- **The engine's batch task converts run values to base units** (`options.parameter_units`), the same trap as the fit.
- **S7** assembles the data bundle from evidence each stage persists as it finishes (`evidence/<stage>.json`: rounds,
  final metrics, notes, the judged snapshot and outputs — so the package survives the pause for signature): final
  CPF, MAP, observed data, S4/S5 snapshots and result tables, every fit's specs and results, S6. Every bundled
  snapshot is **re-run on a fresh engine process** and compared at 1e-6; the MAR (`report/campaign_mar.py`, ICH M15
  Appendix 2 structure, every number an evidence reference) records the verdict and the data-bundle hash; the
  package zip (manifest + `rerun_all.R`) is written **only if reproduction passed** (D13), else S7 escalates.
- **DOCX and PDF/A-2b without TeX**: pandoc 3.9 (`pypandoc-binary`) and Typst 0.15 (`typst`, PDF/A-2b with embedded
  fonts) are pinned in `uv.lock`, so the report renderer is reproducible; the LaTeX route remains as a fallback.
- **S0 refuses a CPF with an elimination/transport parameter the builder cannot place** (no engine binding).
  Found when a finished report listed "NOT PLACED IN THE MODEL: elim.renal.gfr_fraction" yet concluded the model
  met its tier — the simulation had no renal clearance at all. Test fixtures that carried the unbound parameter fixed.
- Verified on the server's PK-Sim with the known-truth campaign (before the S0 and renderer changes): S0 → S5, the
  signature, S6 and S7 completed in 264 s; S6 ranked GFR fraction first for AUC (−0.84) and the tablet t50 for its
  Cmax (−0.35); S7 reproduced 7 of 7 result tables and released a 147-file package. The prediction intervals were
  degenerate because noise-free synthetic data identify the parameters almost exactly (SD 4e-12) — the draws were
  applied; real clinical data (Phase 4) will give real intervals.

- **Package API and monitor** — `GET /campaigns/{id}/package` (verdict, hashes, available artifacts; no server
  paths) and `GET /campaigns/{id}/package/{package.zip|mar.pdf|mar.docx|mar.md}`. The zip is refused with 409 while
  reproduction has not passed (D13); only files inside the object store are served; project membership applies. The
  campaign monitor shows the S6 sensitivity/intervals and a Report & package card with the downloads. Verified in
  the live tool on the server: a known-truth S0 → S7 campaign (266 s) whose PDF/A-2b report, DOCX and 152-entry zip
  download through the tool.

### Known gap — Phase 2 still open
- The Temporal workflow does not run S6/S7 (it marks them SKIPPED with that reason); the single-node runner does.
- The M15 table's model influence and decision consequence are not captured by the MAP yet; the report says so.

### Verified — the whole S0 → S5 loop on real PK-Sim, by known-truth recovery (2026-09-24, server engine)
A "true" Aciclovir model (IV, oral solution, a Weibull tablet) was simulated on PK-Sim to produce the observed
profiles; the campaign started from a wrong model — intestinal permeability 10× too low, tablet release (t50) 55
instead of 30 min — at **high** model risk (1.25-fold, every study within). It completed in 201 s: S2 fitted
permeability back to 4e-05 cm/min (the truth, exactly), S3 fitted t50 back to 30 min (exactly), S4 re-validated
every trained study (VPC 100 % each), S5 judged two external tablets, a solution and a multiple-dose study as the
fasted group, all within 1.25-fold. Synthetic data: this proves the machinery, not clinical validity (Phase 4).

### Added — visual predictive check, the MS-01 population gate (plan item 1.5, R7)
- After a stage's PK gate passes at S1, S2 and S4, each study's exported model is run across a 100-individual
  virtual population built from the study's demographics (population, sex, age range; seed recorded); the engine
  returns the 5/50/95 % band (`vpc.json`, new `options.vpc` on the `population` task). The gate needs ≥ 80 % of the
  observed points inside the 5–95 % band (MS-01 S1). A failure escalates as `vpc_coverage_below_80` — no fit action
  addresses variability. Coverage and band are stored per study with each round, for the monitor's plot.
- A study's VPC age range is its reported one (`Demographics.age_min/age_max`), else the mean ± 10 years (adults
  from 18) — a MAP default the modeler signs, flagged for SME review like every MS-01 [SME] value.
- The VPC **gates S1 and S2** (MS-01 §4: S1 gate, S2 "as S1"); at **S4 it is reported, not gated** — MS-01 lists
  "VPC per study" in the S4 report while its gate is the PK acceptance table. (First implemented as gating S4 too;
  corrected when a known-truth run escalated at S4 on a VPC of 70 %.)
- Same step in the Temporal workflow (`prepare_vpc_jobs` / `evaluate_vpc` activities).

### Added — fitted parameters keep their precision
- The CPF record of a fitted parameter now carries its **SD, CV and 95 % CI** (`ParameterRecord.uncertainty`, from
  the engine's Hessian CI estimate, in the CPF's unit). They were dropped after the fit; MS-01 S4 needs them in the
  parameter table and S6 needs them to propagate uncertainty. CPF JSON Schema regenerated.

### Changed — diagnostics ruleset `diag-rules` 0.1 → 0.2 (UNVERIFIED; change approved by the project owner)
- **R6 — the clearance rule offers renal clearance before logP**: `fit elim.renal.gfr_fraction`, then
  `fit elim.renal.ts_clspec`, then `fit phys.logp`. Under 0.1 a renally cleared compound with wrong renal clearance
  could only be "fixed" by bending logP — seen on PK-Sim, where it moved AUC from 2.06- to 1.89-fold by distorting
  distribution. MS-01 §2.2's condition (renal fits only with urine/fe data) is enforced per compound by the CPF fit
  policy. Awaiting SME sign-off (T-30).

### Infra
- **Mac Docker engine fallback** (`deploy/dev/docker_engine.sh`): runs a job in the linux/amd64 engine image with
  the job directory mounted at the same path, so `EngineRunner` works unchanged. Golden round trip passes in the
  container (~21 s). A development fallback — not the qualified, digest-pinned production image.
- **`deploy/dev/deploy_to_server.sh`**: rsync + dependencies + web build + restart, as one command.
- **Server redeployed** to the current build (it was running a 2026-09-20 build), autostart installed, engine gate
  (`golden_roundtrip.R`, `verify_run_round.sh`) passes there. Tailscale installed in userspace mode, awaiting login.

### Known gap — found while fixing the above
- `modeler_intake` keeps its own unit tables; they should use `pbpk_domain.units` so there is one source.

### Known gap — diagnosed 2026-09-24 (the reason every campaign stopped at S1)
Tracked as R1–R13 in the plan. The critical ones:
- **R1 — S4 and S5 never simulated anything.** `campaign/map.py::_scenarios` only created scenarios for INTERNAL
  studies in three classes (IV → S1, oral fasted → S2, fed → S3). Nothing was ever tagged S4, and EXTERNAL studies
  were skipped outright, so internal and external validation had no work and escalated.
- **R2 — the runner had no validation mode**; every stage was treated as a fit loop.
- **R4 — enzyme-cleared drugs were never metabolised on real PK-Sim.** The CPF build never attached expression
  profiles to the individual, so CYP/UGT processes had no enzyme to act on.
- **R5 — only oral solutions/suspensions could be built**; tablets and capsules raised, and S3 did not exist.
- **R8/R9 — S6 and S7 were not part of the pipeline** even though sensitivity, population, parameter CIs, the MAR
  generator and the reproducibility bundle all exist and are engine-verified.
- **R11 — the 2026-09-24 case studies were not PBPK.** With the engine host down they ran on a one-compartment
  analytical stand-in. Their four defect findings stand; their numbers are not simulation results.

---

## 2026-09-24

### Added
- **Twelve end-to-end case studies** driven through the real API (`deploy/dev/case_studies/`), evidence in
  `reports/case-studies/` (gitignored). *Ran on the analytical stand-in, not PK-Sim — see Known gap R11.* (84533d3)
- **Analytical stand-in engine** `deploy/dev/analytical_engine.py`: one-compartment model driven by the CPF's real
  values, with a parameter-identification task. A software fixture only; never a simulation result. (84533d3)
- **Review-inbox decisions act on the campaign**: `escalation:resolve` endpoint + `resolve_escalation()` apply
  retry / accept best / abort to a stopped single-node campaign, signing from the token's step-up (no password on the
  wire) *before* applying anything. (310c1a2)
- **Server lifecycle scripts in the repo** (`deploy/server/`): run / stop / status, shared `_env.sh`, and
  `install_autostart.sh` (no-root `@reboot` + 5-minute watchdog that respects a deliberate stop). They previously
  existed only on the server. (122ba94)
- **Sudo-optional Tailscale setup** `deploy/server/setup_tailscale.sh` (userspace mode when there is no root).
  (afcb76d, ee1b407)
- **Interface redesign** as a dark instrument (IBM Plex; teal = predicted, amber = observed) and a **fold-error
  gauge** showing predicted/observed on a log scale against the ICH M15 tier band. (0854342)

### Fixed
- **AUC compared over mismatched time windows** — prediction reduced over the simulation window, observation over
  its sampling window. A perfect model of a slowly eliminated drug was reported at +101% error and escalated.
  Predictions are now reduced over the observed window (`ObservedPK.t_last`). *Would have produced false failures on
  real submissions.* (84533d3)
- **Fit candidates not checked against the compound** — a renal drug spent a round fitting a hepatic enzyme it does
  not have. Candidates are now filtered to real, bounded, stage-permitted parameters with an engine path. (84533d3)
- **An engine crash hung the campaign at RUNNING** with the error hidden; stage failures are now recorded with the
  actual message. (84533d3)
- **Missing input file raised** where every caller expects graceful degradation. (84533d3)
- **The model silently had no clearance** — a process parameter without an `engine_binding` was dropped by the
  builder with no warning. Now reported as "NOT PLACED IN THE MODEL". (3aca992)
- **Snapshot integrity check always failed through `EngineRunner`** — the build hashed the canonical snapshot but the
  runner hashed the file bytes. Masked because server tests called `run_job.R` directly. (ba0a9ab)
- Tailscale version lookup parsed a key that does not exist; now uses the `latest` redirect. (ee1b407)

### Changed
- **Real runnable example** replaces the static Example-A mock screens; one-click "Run campaign"; real data intake
  (CSV upload, column mapping); studies merge by id instead of being replaced. (9c1be08)
- Example CPF calibrated: bound GFR clearance, MS-01 fit policies, real pKa records. (3aca992)
- All three escalation decisions now require a signature, matching `decision_options()`. (310c1a2)

### Docs
- Moved `SESSION_HANDOFF.md` into `docs/`. (999c8ca)

## 2026-09-20 → 2026-09-23

### Added
- **Guided "New project" wizard**: project → CPF → studies → MAP & sign → run, opening the live monitor. (ba0a9ab)
- **Single entry point** — the web app proxies `/api/*` to the backend: one URL, no CORS. (d4017db)
- **Deployed on the server as one tool**: Node via nvm, web + API + engine behind `http://<server>:3000`.

## 2026-09-19

### Added
- **Single-node execution mode (no Docker / no Temporal needed)**: `LocalExecutor` runs the MS-01 loop in-process
  using the same activities as the Temporal path; `FileReadStore`/`FileWriteStore` persistence seam;
  `MODELER_EXECUTION_BACKEND=local|temporal`. (3e48fa4)
- **Create-project write API** and `campaign:prepare` (MAP + NCA-derived observed PK). (b4a3526)
- **Web app** (T-26/27/28) with live read APIs for projects, CPF, campaigns, escalations, proposals.
  (817c14d, fdeaf91, acfffa7)
- **T-09** population, sensitivity and batch engine tasks, verified on the engine. (bca33e8)
- **T-24** MAR generation and rendering (DOCX / PDF-A via pandoc, Markdown fallback). (01ff5fa)
- **T-12** engine image CI, qualification gate, registration record. (c26c923)
- **T-20** agent run persistence, token/cost budgets, provider-failure handling. (5003e6f)
- **T-23** `rerun_all.R` generation; byte-exact reproduction verified on the engine. (fe2cc69)
- **T-32** validation pack generator (URS/FS, RTM, OQ evidence). (467335f)

## 2026-09-18

### Added
- **Fit loop, end to end** — CPF → PK-Sim parameter paths harvested from the engine; PI spec built; estimates
  applied to a new CPF version; strategist bounds threaded through. Verified on the engine: PI recovered GFR fraction
  1.0 from a 0.4 start. (cf4a843, 712b8ac, 83a1571, a13e746, d2ac368)
- **T-11** observed-data coverage: molar units, urine/feces fractions, geometric statistics, LLOQ. (c444720)
- **T-17** escalations, deviations and signed decisions API. (47322d0)
- **T-23 core** reproducibility gate and submission bundle. (7f36c8e)
- **T-06** Keycloak OIDC authentication and step-up signatures. (101e605)
- Auth-guarded campaign / run APIs; `GET /runs/{id}/results`. (8281c65, 9e438b8)
- **T-25** CI pipeline and requirement trace matrix. (bc5835a)

## 2026-09-17

### Added
- **T-18** deterministic NCA. (6997975)
- **Round loop wired**: build → simulate on the engine → evaluate against the tier gate → diagnose → choose action.
  (27516d6, d1386ff, 0588bd0, 2abd0a9, 902158f)
- **T-14** diagnostics ruleset; **T-15** strategist agent. (0588bd0, 2abd0a9)

### Fixed
- **`ValueOrigin.Source` enum** — a raw CPF label made PK-Sim *silently drop the simulation*. Every CPF-built
  campaign would have produced nothing. Caught by the first on-engine smoke. (6de102d)
- `run_job.R` matched the wrong result-CSV names for multi-simulation snapshots. (8e8ef8b)

## 2026-09-16

### Added
- Repository under git. Platform scaffold, engine verified on Linux (T-01), catalog harvest (T-02), CPF (T-03),
  study split (T-04). (ab20736)
- **T-10** builder coverage: Michaelis-Menten metabolism, transporters, inhibition, induction, specific binding,
  multiple-dose protocols, meal events. (0afed52, a201367)
- **T-13** campaign workflows; **T-05** campaign persistence with RLS and append-only audit; **T-07** object store;
  **T-08** results ingestion; **T-09** cancellation; **T-16** MAP generator.
  (fdb5f0d, e103d6f, c32831b, 17a98b1, dec21ab, 7b4ce26, 147f6d5)

### Docs
- Continuation package recorded T-10/T-13 progress — its last update until 2026-09-24. (cdc8a7a)

---

## Sessions and AI models
Work on this repository has been done across several sessions and Claude models. When the model or session changes,
record it here so a reader knows which context produced which work.

| Date | Model (from commit trailers) | What it did |
|---|---|---|
| 2026-09-16 → 20 | Claude Opus 4.8 | Planning (MS-01, engineering plan), T-01 → T-32 core, web app, single-node execution, create-project flow |
| 2026-09-23 → 24 | Claude Opus 5 | Real example, calibration, review decisions, server scripts, autostart, case studies, redesign |
| 2026-09-24 → | Claude Opus 5.5 | Diagnosis of the S1 stop; S0 → S7 plan and execution; this change log |
| 2026-09-24 (cloud session) | Claude Opus 5.5 | Phase 4 reference importer (Dapagliflozin real data), wizard templates, e2e flow. No PK-Sim in this container (CRAN / r-universe blocked): engine proof stays on the server |
| 2026-09-25 | per commit trailer (new session) | Plan for the project start-up pipeline (P0–P6) and the non-linear backend (draft, awaiting approval) |
| 2026-10-05 (cloud session) | Claude Opus 5.5 | Built the approved start-up pipeline P0–P5 (T-40 → T-50) and the non-linear backend T-51 → T-55 (MS-01 v1.1 SJ, v1.2 feedback cycles, both UNVERIFIED); verified in software only — no PK-Sim in this container, T-56 is the server's |
| 2026-10-06 (worktree `claude/vbe-template`) | Claude Opus 5.5 | Atomic writes for every file the API reads during a campaign; first campaign record written before the id is returned (T-56 kit test flake); T-31 VBE template |
| 2026-10-07 (cloud session, branch `enterprise-architecture-refactor`) | per commit trailer | Structural health check of the code base; locked-file list proposed and approved; phase 1 architecture guardrails (`docs/ARCHITECTURE_BOUNDARIES.md`, `tests/architecture/`), web and API-image CI jobs, API Dockerfile and secret-scan fixes |
| 2026-10-08 → 09 (cloud session) | per commit trailer | Architecture refactor phases 2–9 to the end (no boundary exception left); the owner's items (pilot deployment refuses DEV auth in production, e2e in CI, npm audit, `.xls`); science B1–B6: Stone 2004 exclusion, PI study weights, EHC placement, Weibull confirmed on PK-Sim, multi-compound phase 2 (MS-01 v1.3, stage SM, D-25) and the web system panel, the VBE application end to end (template, MAP applications, engine occasion, S6 trials, F-304 gate, report, illustrative PK-Sim proof, D-26); PK-Sim evidence through GitHub Actions; `docs/SME_SIGNOFF.md` |
| 2026-10-19 (desktop session, branches `r2b-start`, `r2b-followup`) | Claude Opus 5.5 (1M context) | The PR #72 and #73 merge conflicts (`CHANGELOG.md`) resolved. A second R2b (#74) built before #73 was found; the owner kept #73, and what #74 had that #73 lacked came as the R2b follow-up (one upload with the client's files, the R2 approvals removed, pathway kinds, the viewer on the proposal); then R4a, Review & sign (branch `review-sign`). No GitHub access from this sandbox: the owner pushes |
