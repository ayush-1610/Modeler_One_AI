# 02 · Feature catalog (post-MAP scope)

45 features from a signed MAP to a downloaded package. Each card gives the fields the brief asks for; the same data is
in `FEATURE_INVENTORY.csv`. Status values: **implemented** (code path complete and tested, on stub engines in CI unless
noted), **partial** (works with stated gaps), **placeholder** (exists but does nothing useful), **unwired** (built, no
production caller), **not deployed**. Defect IDs refer to `11_TECHNICAL_ASSESSMENT.md`. "Implemented" never means
"proven on clinical data": see `00_EXECUTIVE_SUMMARY.md` §3.

## 1. Summary

| Group | ID | Feature | Status |
|---|---|---|---|
| Campaign start and planning | F01 | Campaign start with run guard | implemented (gaps C-02, C-04) |
|  | F02 | One-click Run campaign | implemented (gaps C-05, C-09) |
|  | F03 | S0 readiness gate | implemented |
|  | F04 | Stage planning from the signed MAP | implemented |
| Model building and engine | F05 | Snapshot regeneration from the CPF | implemented |
|  | F06 | Engine job execution | implemented |
|  | F07 | Parameter identification multistart | implemented (gap O-02) |
|  | F08 | Fit written back to the CPF | implemented (gap S-01) |
|  | F09 | Fit judged in its own round | implemented |
| Evaluation, diagnosis and decision | F10 | Acceptance evaluation | implemented |
|  | F11 | VPC gate | implemented |
|  | F12 | Diagnostics ruleset | partial (S-03, S-05) |
|  | F13 | Strategist action choice | implemented (deterministic only) |
|  | F14 | fix_and_refit identifiability | implemented |
|  | F21 | Escalation with signed decision | implemented (gaps C-01, C-08) |
| Refinement and validation | F15 | No-regression gate | implemented (software) |
|  | F16 | SJ joint refinement | implemented (UNVERIFIED) |
|  | F17 | Model systems and SM stage | partial (software) |
|  | F18 | S4 internal validation | implemented |
|  | F19 | S5 external validation | implemented |
|  | F20 | S5 feedback cycles | implemented (UNVERIFIED) |
| Prediction (S6) | F22 | S6 signature gate | implemented (gap C-01) |
|  | F23 | S6 sensitivity | partial |
|  | F24 | S6 uncertainty intervals | partial |
|  | F25 | Virtual bioequivalence | implemented (DRAFT) |
| Report and package (S7) | F26 | S7 data bundle | implemented (gaps C-10, S-09) |
|  | F27 | Reproducibility gate | implemented |
|  | F28 | PK-Sim project export | implemented (unproven on server) |
|  | F29 | MAR generation and rendering | partial |
|  | F30 | M15 credibility table | partial |
|  | F31 | Package release and download | implemented (gaps C-06, C-11, P-02) |
| Traceability | F32 | Memoised engine runs | implemented (gap E-02) |
|  | F33 | Model sets | implemented |
|  | F34 | Change ledger | implemented |
|  | F35 | Influence map | implemented |
| User interface | F36 | Campaign monitor | implemented |
|  | F37 | Escalation pop-up and decision form | implemented |
|  | F38 | Fixture and test-only banners | partial (gap C-11) |
| Compliance and qualification | F39 | Part 11 signatures and audit chain | implemented (gaps C-11, C-12) |
|  | F40 | Postgres Part 11 copy and verify | implemented (production) |
|  | F41 | Engine health check | implemented |
|  | F42 | Validation pack (IQ/OQ/PQ) | implemented, not executed end to end |
|  | F43 | T-56 end-to-end kit | implemented |
| Alternative and supporting paths | F44 | Temporal campaign workflows | partial, not deployed |
|  | F45 | Reference model runner | implemented |

## 2. Feature cards

### F01 · Campaign start with run guard

- **Purpose:** Start the MS-01 campaign on the signed MAP
- **Problem it solves:** Runs only on what was signed
- **User:** Modeller (owner)
- **Where:** Run page / plan page; POST /projects/{id}/campaigns
- **Inputs:** CPF, MAP, observed URIs and hashes, model risk, stages
- **Processing:** Role, membership, owner; outside development: MAP signed, no budget override, CPF equals MAP table; build CampaignRequest; dispatch local thread or Temporal
- **Outputs:** campaign_id, QUEUED record
- **Depends on:** run_guard, execution seam, LocalExecutor
- **Configuration:** MODELER_DEPLOYMENT, MODELER_EXECUTION_BACKEND, MODELER_READ_ROOT
- **Validation:** 409 unsigned MAP or CPF != MAP; 422 budget override; model_risk required
- **Errors and edge cases:** MAP signature trusted from the file's own status; CPF hash not recomputed; duplicate starts possible
- **Source:** services/api/src/modeler_api/campaign_api.py:44-81; services/api/src/modeler_api/run_guard.py:46-105
- **Status:** implemented (gaps C-02, C-04)

### F02 · One-click Run campaign

- **Purpose:** Prepare, sign and start in one action
- **Problem it solves:** Shortcut for owners
- **User:** Project owner
- **Where:** /projects/{id}/campaigns
- **Inputs:** Project question and studies
- **Processing:** campaign:prepare -> POST /signatures (map_approval) -> start
- **Outputs:** Running campaign
- **Depends on:** write_api, signatures_api, campaign_api
- **Configuration:** -
- **Validation:** Owner + step-up
- **Errors and edge cases:** MAP never shown before signing; bypasses reviewer-only plan:sign; staging path overwritten
- **Source:** apps/web/components/RunCampaignButton.tsx:28-64; services/api/src/modeler_api/write_api.py:182-293
- **Status:** implemented (gaps C-05, C-09)

### F03 · S0 readiness gate

- **Purpose:** Refuse a campaign whose CPF cannot build a working model
- **Problem it solves:** Silent missing pathways
- **User:** System
- **Where:** LocalExecutor S0
- **Inputs:** CPF (+ model system)
- **Processing:** Completeness check; unplaceable process ids; missing expression profiles; per compound in a system
- **Outputs:** PASSED or ESCALATED S0_not_ready with findings
- **Depends on:** pbpk_domain.cpf
- **Configuration:** -
- **Validation:** MW, logP, fu, solubility, pKa or neutral, an elimination pathway
- **Errors and edge cases:** ehc_fraction may be flagged unplaced (static trace)
- **Source:** services/orchestrator/src/modeler_orchestrator/campaign_activities.py:113-162
- **Status:** implemented

### F04 · Stage planning from the signed MAP

- **Purpose:** Decide each stage's kind, limits and studies
- **Problem it solves:** The run follows what was signed
- **User:** System
- **Where:** plan_stage, _limits
- **Inputs:** MAP stage plan and scenarios
- **Processing:** kind (fit, validate, joint, predict, report, absent), skip reason, budget and rounds with their source
- **Outputs:** StagePlan; stage note naming the limit source
- **Depends on:** pbpk_domain.campaign.map
- **Configuration:** request budgets only in development
- **Validation:** Budget: request > MAP > 1800 s; rounds: MAP > 4
- **Errors and edge cases:** Budget checked only at round start
- **Source:** services/orchestrator/src/modeler_orchestrator/campaign_activities.py:165-194; services/orchestrator/src/modeler_orchestrator/local_runner.py:593-612
- **Status:** implemented

### F05 · Snapshot regeneration from the CPF

- **Purpose:** Build every stage's PK-Sim simulations from the system of record
- **Problem it solves:** No hand-edited simulations
- **User:** System
- **Where:** build_round_snapshot
- **Inputs:** CPF, MAP scenarios, model system, seed
- **Processing:** Scenarios -> individuals, protocols, formulations, events, processes, expression, outputs -> snapshot JSON
- **Outputs:** Snapshot file + exact-bytes sha256; build notes (NOT PLACED, NOT ACTIVE, NOT SIMULATED)
- **Depends on:** cpf.build, snapshot.builder, round_build
- **Configuration:** -
- **Validation:** Storage units only; ValueOrigin coerced to harvested enum; unbuildable scenario fails a fit stage
- **Errors and edge cases:** Fed meal template ignores meal_type; fed solubility factor silently not placed
- **Source:** packages/pbpk-domain/src/pbpk_domain/campaign/round_build.py; packages/pbpk-domain/src/pbpk_domain/cpf/build.py; packages/pbpk-domain/src/pbpk_domain/snapshot/builder.py
- **Status:** implemented

### F06 · Engine job execution

- **Purpose:** Run PK-Sim in isolation
- **Problem it solves:** GPL engine isolation, integrity
- **User:** System
- **Where:** EngineRunner + run_job.R
- **Inputs:** EngineJob (inputs with sha256, options, timeout)
- **Processing:** Stage inputs, verify hashes, write job.json, run subprocess, parse PROGRESS/WARNING, enforce timeout, hash outputs
- **Outputs:** EngineManifest
- **Depends on:** ospsuite 12.4.4, PK-Sim 12.3, .NET 8
- **Configuration:** MODELER_ENGINE_COMMAND, MODELER_ENGINE_ID, MODELER_IMAGE_DIGEST
- **Validation:** sha256 per input (Python and R)
- **Errors and edge cases:** Warnings unread; failures discard outputs; Linux only; no cancellation locally
- **Source:** services/engine-worker/src/modeler_engine/runner.py; services/engine-worker/r/run_job.R
- **Status:** implemented

### F07 · Parameter identification multistart

- **Purpose:** Fit parameters within the stage budget
- **Problem it solves:** Local optima, time budget
- **User:** System
- **Where:** fit rounds
- **Inputs:** FitRoundRequest (PI spec, bounds, pkml models)
- **Processing:** Plan 4-32 LHS starts; run one PI job per start in parallel; read pi_result.json; assess convergence, bounds, correlation, agreement
- **Outputs:** FitRoundOutcome (best start, CI, correlations, findings)
- **Depends on:** run_pi.R, ospsuite.parameteridentification 2.2.0
- **Configuration:** MODELER_FIT_WORKERS, MODELER_ENGINE_CORES
- **Validation:** Signed log scale must be honoured by the engine
- **Errors and edge cases:** One failed start fails the stage locally; BOBYQA only; planner assumes 40 evaluations per start
- **Source:** services/orchestrator/src/modeler_orchestrator/fitting_activities.py; packages/pbpk-domain/src/pbpk_domain/fitting.py; services/engine-worker/r/run_pi.R
- **Status:** implemented (gap O-02)

### F08 · Fit written back to the CPF

- **Purpose:** Keep the CPF the system of record
- **Problem it solves:** Traceable fitted values
- **User:** System
- **Where:** run_round
- **Inputs:** Best start's estimates and uncertainty
- **Processing:** New CPF version: FITTED, fitted_at_stage, provenance ParameterIdentification, SD/CV/CI95; other compounds' values into their CPF
- **Outputs:** CPF vN+1 file + hash
- **Depends on:** fit_spec.apply_fit_estimates
- **Configuration:** -
- **Validation:** Unknown compound refused
- **Errors and edge cases:** Applied without checking improvement
- **Source:** services/orchestrator/src/modeler_orchestrator/campaign_activities.py:619-697
- **Status:** implemented (gap S-01)

### F09 · Fit judged in its own round

- **Purpose:** Score the fitted model, not the pre-fit simulation
- **Problem it solves:** Fits credited a round late (R13)
- **User:** System
- **Where:** _run_round
- **Inputs:** Fitted CPF
- **Processing:** Re-simulate the fitted CPF (phase postfit) and evaluate that
- **Outputs:** Round verdict on the fitted model
- **Depends on:** -
- **Configuration:** -
- **Validation:** -
- **Errors and edge cases:** -
- **Source:** services/orchestrator/src/modeler_orchestrator/local_runner.py:1011-1024
- **Status:** implemented

### F10 · Acceptance evaluation

- **Purpose:** Judge a round by pre-specified risk-tiered criteria
- **Problem it solves:** Consistent, signed verdicts
- **User:** System
- **Where:** evaluate_round
- **Inputs:** Profiles, observed PK, MAP acceptance and roles
- **Processing:** Read prediction at observed times, NCA, fold-error verdicts, internal target, groups per role/analyte/food/quantity
- **Outputs:** RoundEvaluation (gate, metrics, findings)
- **Depends on:** pbpk_domain.acceptance, nca, metrics
- **Configuration:** MAP acceptance (signed)
- **Validation:** 1.25/1.5/2-fold; min fraction 1.0/0.8/0.8; |PE| <= internal target
- **Errors and edge cases:** Missing results never pass; rulesets UNVERIFIED
- **Source:** services/orchestrator/src/modeler_orchestrator/campaign_activities.py:700-797; packages/pbpk-domain/src/pbpk_domain/campaign/evaluate.py; packages/pbpk-domain/src/pbpk_domain/acceptance.py
- **Status:** implemented

### F11 · VPC gate

- **Purpose:** Check population variability covers the data
- **Problem it solves:** PK in band but variability wrong
- **User:** System
- **Where:** S1/S2 gate, S4 report
- **Inputs:** Exported pkml per study, demographics, seed
- **Processing:** Population job (100 individuals) -> 5/50/95 band -> coverage of observed points >= LLOQ
- **Outputs:** Coverage per study; escalation vpc_coverage_below_80
- **Depends on:** run_job.R population
- **Configuration:** -
- **Validation:** >= 80 % inside 5-95 %
- **Errors and edge cases:** Single-sex populations; weak test for mean data
- **Source:** services/orchestrator/src/modeler_orchestrator/campaign_activities.py:528-602; packages/pbpk-domain/src/pbpk_domain/campaign/vpc.py
- **Status:** implemented

### F12 · Diagnostics ruleset

- **Purpose:** Map failures to permitted actions
- **Problem it solves:** Unstructured trial and error
- **User:** System
- **Where:** diagnose_round
- **Inputs:** Per-study ratios, fit signals, stage candidates
- **Processing:** Evidence -> rules -> ordered permitted actions; fittable-candidate filter; model-system merge
- **Outputs:** RoundDiagnosis (causes, permitted actions or escalate)
- **Depends on:** diag_rules.yaml 0.6
- **Configuration:** -
- **Validation:** Escalate rules win; untried only
- **Errors and edge cases:** Five evidences never computed; bolus distribution never fires
- **Source:** services/orchestrator/src/modeler_orchestrator/campaign_activities.py:939-1051; packages/pbpk-domain/src/pbpk_domain/diagnostics.py
- **Status:** partial (S-03, S-05)

### F13 · Strategist action choice

- **Purpose:** Pick the next action
- **Problem it solves:** Bounded AI role
- **User:** System
- **Where:** choose_action
- **Inputs:** Permitted actions, tried actions
- **Processing:** First untried permitted action (LLM decider not wired)
- **Outputs:** ActionChoice
- **Depends on:** modeler_agents.strategist
- **Configuration:** -
- **Validation:** Only permitted, untried actions
- **Errors and edge cases:** branch/switch/switch_algorithm have no effect
- **Source:** services/orchestrator/src/modeler_orchestrator/campaign_activities.py:1054-1073
- **Status:** implemented (deterministic only)

### F14 · fix_and_refit identifiability

- **Purpose:** Resolve correlated parameter pairs
- **Problem it solves:** Non-identifiable fits
- **User:** System
- **Where:** diagnosis + round base
- **Inputs:** Correlated pair, signed MAP grades
- **Processing:** Fix the better-sourced parameter at its signed value; refit the other; escalate if undecidable
- **Outputs:** Fixed CPF version; note
- **Depends on:** pbpk_domain.identifiability
- **Configuration:** -
- **Validation:** |r| > 0.95
- **Errors and edge cases:** -
- **Source:** services/orchestrator/src/modeler_orchestrator/campaign_activities.py:224-293, 907-931
- **Status:** implemented

### F15 · No-regression gate

- **Purpose:** Keep earlier stages valid after a later fit
- **Problem it solves:** Later fits breaking earlier stages
- **User:** System
- **Where:** after a training stage
- **Inputs:** New CPF, passed stages
- **Processing:** Re-judge each earlier passed stage; joint remedy on regression
- **Outputs:** Findings; escalation regression
- **Depends on:** -
- **Configuration:** -
- **Validation:** -
- **Errors and edge cases:** Not on the Temporal path
- **Source:** services/orchestrator/src/modeler_orchestrator/local_runner.py:531-548, 834-858
- **Status:** implemented (software)

### F16 · SJ joint refinement

- **Purpose:** Refit all trained parameters together
- **Problem it solves:** Sequential compensation
- **User:** System
- **Where:** SJ stage
- **Inputs:** Fitted parameters, internal studies
- **Processing:** Derived MAP; S1-CI guard; equal study weights; keep only if every study passes and GMFE not worse
- **Outputs:** Joint CPF or sequential set kept
- **Depends on:** orchestrator.joint
- **Configuration:** -
- **Validation:** MS-01 v1.1 UNVERIFIED
- **Errors and edge cases:** Skipped on Temporal
- **Source:** services/orchestrator/src/modeler_orchestrator/local_runner.py:878-942; services/orchestrator/src/modeler_orchestrator/joint.py
- **Status:** implemented (UNVERIFIED)

### F17 · Model systems and SM stage

- **Purpose:** Parent, metabolites and enantiomers fitted to their own data
- **Problem it solves:** Multi-analyte models
- **User:** Modeller
- **Where:** SM stage, all stages
- **Inputs:** Model system document
- **Processing:** Per-analyte gating, qualified fit ids, formation targets, systems beside each CPF version
- **Outputs:** Per-analyte verdicts; system documents per CPF version
- **Depends on:** pbpk_domain.system; round_system
- **Configuration:** -
- **Validation:** MS-01 v1.3 UNVERIFIED
- **Errors and edge cases:** Systems escalate at S1 on PK-Sim so far
- **Source:** packages/pbpk-domain/src/pbpk_domain/system.py; services/orchestrator/src/modeler_orchestrator/round_system.py
- **Status:** partial (software)

### F18 · S4 internal validation

- **Purpose:** Re-judge the final CPF on every trained study
- **Problem it solves:** Stale or interacting stages
- **User:** System
- **Where:** S4
- **Inputs:** Final CPF
- **Processing:** Simulate once, judge, never fit
- **Outputs:** Verdict; escalation internal_validation_failed
- **Depends on:** -
- **Configuration:** -
- **Validation:** Options: limitation or stop
- **Errors and edge cases:** -
- **Source:** services/orchestrator/src/modeler_orchestrator/local_runner.py:679-708
- **Status:** implemented

### F19 · S5 external validation

- **Purpose:** Judge on blinded external studies
- **Problem it solves:** Overfitting
- **User:** System
- **Where:** S5
- **Inputs:** Final CPF, external scenarios
- **Processing:** Judge fasted and fed separately; unbuildable studies named
- **Outputs:** Verdict; escalation external_validation_failed
- **Depends on:** -
- **Configuration:** -
- **Validation:** Core classes only
- **Errors and edge cases:** Fed studies await the fed sub-loop
- **Source:** services/orchestrator/src/modeler_orchestrator/campaign_activities.py:726-729; services/orchestrator/src/modeler_orchestrator/local_runner.py:679-708
- **Status:** implemented

### F20 · S5 feedback cycles

- **Purpose:** Signed paths after an external failure
- **Problem it solves:** Ad-hoc refitting to validation data
- **User:** Modeller / reviewer
- **Where:** Feedback tab, decision form
- **Inputs:** S5 diagnosis, decision payload
- **Processing:** Diagnose failing studies; limitation, learn (MAP deviation), new evidence (measured value), stop; cycle counter
- **Outputs:** Cycle c+1 or limitation on record
- **Depends on:** orchestrator.feedback
- **Configuration:** -
- **Validation:** One learn per class (D-05); spent studies; evidence in CPF unit within plausibility
- **Errors and edge cases:** Cycle >= 2 fits missing from bundle
- **Source:** services/orchestrator/src/modeler_orchestrator/feedback.py; services/orchestrator/src/modeler_orchestrator/local_runner.py:1185-1361
- **Status:** implemented (UNVERIFIED)

### F21 · Escalation with signed decision

- **Purpose:** Human decision when the campaign cannot proceed
- **Problem it solves:** Silent continuation
- **User:** Owner / reviewer
- **Where:** Escalation pop-up; POST escalation:resolve
- **Inputs:** Action, rationale, payload, step-up token
- **Processing:** Checks, step-up signature, claim, apply, continue on a thread
- **Outputs:** Signature; campaign resumes/ends
- **Depends on:** part11, local_runner
- **Configuration:** -
- **Validation:** Open escalation; step-up loa2 <= 300 s
- **Errors and edge cases:** Action not checked against options; signer may be the starter
- **Source:** services/api/src/modeler_api/escalations.py:199-284; services/orchestrator/src/modeler_orchestrator/local_runner.py:1220-1318
- **Status:** implemented (gaps C-01, C-08)

### F22 · S6 signature gate

- **Purpose:** Require a signed S4/S5 evaluation before prediction
- **Problem it solves:** Unvalidated predictions
- **User:** Reviewer / owner
- **Where:** AWAITING_SIGNATURE
- **Inputs:** Campaign real-data summaries
- **Processing:** Pause; approve passes D-19 real-data rule; resume at S6
- **Outputs:** Signature; S6 runs
- **Depends on:** data_origin
- **Configuration:** project exploratory flag
- **Validation:** Non-real data refused outside exploratory projects
- **Errors and edge cases:** accept_best bypasses it
- **Source:** services/orchestrator/src/modeler_orchestrator/local_runner.py:476-487, 1178-1182
- **Status:** implemented (gap C-01)

### F23 · S6 sensitivity

- **Purpose:** Rank influential parameters
- **Problem it solves:** Which parameters matter
- **User:** System
- **Where:** S6
- **Inputs:** Final CPF, pkml
- **Processing:** Engine sensitivity task +/-10 % on FITTED/PREDICTED parameters; AUC and Cmax
- **Outputs:** Ranking (top 12 per study)
- **Depends on:** run_job.R sensitivity
- **Configuration:** -
- **Validation:** -
- **Errors and edge cases:** No EMA worst-case ranges
- **Source:** services/orchestrator/src/modeler_orchestrator/package_activities.py:105-160; packages/pbpk-domain/src/pbpk_domain/campaign/prediction.py
- **Status:** partial

### F24 · S6 uncertainty intervals

- **Purpose:** Propagate fitted-parameter uncertainty
- **Problem it solves:** Prediction confidence
- **User:** System
- **Where:** S6
- **Inputs:** FITTED records with SD
- **Processing:** 200 independent draws; engine batch; P5/P50/P95 of AUC and Cmax
- **Outputs:** Prediction intervals
- **Depends on:** run_job.R batch
- **Configuration:** -
- **Validation:** Truncated to bounds
- **Errors and edge cases:** No covariance; rejection sampling without cap
- **Source:** services/orchestrator/src/modeler_orchestrator/package_activities.py:204-240; packages/pbpk-domain/src/pbpk_domain/campaign/prediction.py:54-118
- **Status:** partial

### F25 · Virtual bioequivalence

- **Purpose:** TEST vs reference virtual crossover trials
- **Problem it solves:** BE probability before a clinical trial
- **User:** Modeller
- **Where:** S6, VBE card
- **Inputs:** MAP application inputs (never defaulted)
- **Processing:** Arms from CPF formulations; K*n individuals reused across arms; seeded occasions; trial CIs; PoS; F-304 gate
- **Outputs:** VBE result (PoS, GMR, validation status)
- **Depends on:** pbpk_domain.vbe; run_job.R population
- **Configuration:** template vbe-crossover 0.2.0-draft
- **Validation:** Standard 0.80-1.25 90 % CI
- **Errors and edge cases:** NOT_VALIDATED without observed BE; draft version string withholds package when VBE not run
- **Source:** services/orchestrator/src/modeler_orchestrator/vbe_activities.py; packages/pbpk-domain/src/pbpk_domain/vbe.py
- **Status:** implemented (DRAFT)

### F26 · S7 data bundle

- **Purpose:** Collect everything a reviewer needs
- **Problem it solves:** Scattered evidence
- **User:** System
- **Where:** S7
- **Inputs:** Stage evidence, final CPF, MAP, observed, snapshots, fits, S6
- **Processing:** Collect files, mark numeric tables, build manifest
- **Outputs:** Bundle file set, data_bundle_sha256
- **Depends on:** reproducibility
- **Configuration:** -
- **Validation:** -
- **Errors and edge cases:** Accepted stages missing; cycle >= 2 fits missing; server paths inside evidence
- **Source:** services/orchestrator/src/modeler_orchestrator/package_activities.py:252-291
- **Status:** implemented (gaps C-10, S-09)

### F27 · Reproducibility gate

- **Purpose:** Prove the results re-run identically
- **Problem it solves:** Irreproducible packages
- **User:** System
- **Where:** S7
- **Inputs:** Bundled S4/S5 snapshots
- **Processing:** Re-run each on a fresh engine process (never memoised); compare every Results.csv cell
- **Outputs:** Reproduction verdict
- **Depends on:** engine
- **Configuration:** -
- **Validation:** isclose rel 1e-6, abs 1e-6
- **Errors and edge cases:** Same host and engine; rerun_all.R not executed; S6 not re-run
- **Source:** services/orchestrator/src/modeler_orchestrator/package_activities.py:294-353; packages/pbpk-domain/src/pbpk_domain/reproducibility.py:107-147
- **Status:** implemented

### F28 · PK-Sim project export

- **Purpose:** Give reviewers .pksim5 projects
- **Problem it solves:** Open the model in PK-Sim
- **User:** Reviewer
- **Where:** S7
- **Inputs:** Snapshots
- **Processing:** Engine convert_to_project
- **Outputs:** pksim/*.pksim5
- **Depends on:** run_job.R
- **Configuration:** -
- **Validation:** -
- **Errors and edge cases:** Failure only a note; not yet run in a server campaign
- **Source:** services/orchestrator/src/modeler_orchestrator/package_activities.py:310-334
- **Status:** implemented (unproven on server)

### F29 · MAR generation and rendering

- **Purpose:** ICH M15 Appendix 2 report
- **Problem it solves:** Manual report writing
- **User:** Reviewer / regulator
- **Where:** S7; Package tab
- **Inputs:** MAP, CPF, evidence, S6, reproduction, ledger
- **Processing:** Assemble sections 1-9 with value tokens; lint unresolved tokens and bare numbers; render MD, DOCX (pandoc), PDF/A-2b (typst)
- **Outputs:** mar.md, mar.docx, mar.pdf; report issues
- **Depends on:** pandoc, typst
- **Configuration:** -
- **Validation:** No untraced number in prose
- **Errors and edge cases:** No signatures, figures; DOCX error not caught
- **Source:** packages/pbpk-domain/src/pbpk_domain/report/campaign_mar.py; packages/pbpk-domain/src/pbpk_domain/report/mar.py; packages/pbpk-domain/src/pbpk_domain/report/render.py
- **Status:** partial

### F30 · M15 credibility table

- **Purpose:** Model influence, consequence, risk
- **Problem it solves:** Credibility assessment
- **User:** Reviewer
- **Where:** MAR
- **Inputs:** MAP risk assessment
- **Processing:** Copy ratings into the MAR table
- **Outputs:** M15 table
- **Depends on:** pbpk_domain.m15
- **Configuration:** -
- **Validation:** -
- **Errors and edge cases:** Four rows rendered; validate_table not run at S7
- **Source:** packages/pbpk-domain/src/pbpk_domain/report/campaign_mar.py:152-176; packages/pbpk-domain/src/pbpk_domain/report/mar.py:298-310
- **Status:** partial

### F31 · Package release and download

- **Purpose:** Deliver the submission package
- **Problem it solves:** Unverified deliverables
- **User:** Owner / reviewer / QA
- **Where:** Package tab; GET package/{artifact}
- **Inputs:** S7 record
- **Processing:** Zip only if reproduced and lint clean; serve files under the object-store root
- **Outputs:** package.zip, mar.*
- **Depends on:** read_api
- **Configuration:** -
- **Validation:** 409 unless exportable
- **Errors and edge cases:** Not signed; not audited; zip not byte-reproducible; fixture runs exportable
- **Source:** services/orchestrator/src/modeler_orchestrator/package_activities.py:411-420; services/api/src/modeler_api/read_api.py:195-234
- **Status:** implemented (gaps C-06, C-11, P-02)

### F32 · Memoised engine runs

- **Purpose:** Skip identical engine work
- **Problem it solves:** Repeated cycles cost time
- **User:** System
- **Where:** MemoEngine
- **Inputs:** Job task, input hashes, options, engine key
- **Processing:** Reuse recorded outputs after re-hashing them
- **Outputs:** Copied outputs; manifest warning
- **Depends on:** -
- **Configuration:** MODELER_MEMO
- **Validation:** S7 re-runs never reused
- **Errors and edge cases:** Key ignores engine script content
- **Source:** services/orchestrator/src/modeler_orchestrator/memo.py
- **Status:** implemented (gap E-02)

### F33 · Model sets

- **Purpose:** Tie each verdict to one parameter set
- **Problem it solves:** Ambiguous verdicts
- **User:** Reviewer
- **Where:** Each judged round
- **Inputs:** CPF hash, engine key, scenarios, builder version
- **Processing:** Hash into ms-<id>
- **Outputs:** modelSet on each round
- **Depends on:** -
- **Configuration:** -
- **Validation:** -
- **Errors and edge cases:** Builder version is the package version
- **Source:** services/orchestrator/src/modeler_orchestrator/memo.py:107-119
- **Status:** implemented

### F34 · Change ledger

- **Purpose:** Explain every verdict change
- **Problem it solves:** Untraceable parameter changes
- **User:** Reviewer
- **Where:** Rounds tab; MAR history
- **Inputs:** CPF before/after, verdicts
- **Processing:** Entries per working-set change with parameter diffs and moved verdicts
- **Outputs:** Ledger
- **Depends on:** -
- **Configuration:** -
- **Validation:** -
- **Errors and edge cases:** -
- **Source:** services/orchestrator/src/modeler_orchestrator/history.py
- **Status:** implemented

### F35 · Influence map

- **Purpose:** Parameters x studies
- **Problem it solves:** Where a change acts
- **User:** Reviewer
- **Where:** Rounds tab
- **Inputs:** MAP scenarios, CPF, S6 sensitivities
- **Processing:** Structural layer + quantitative layer
- **Outputs:** Influence map
- **Depends on:** -
- **Configuration:** -
- **Validation:** -
- **Errors and edge cases:** Quantitative only after S6
- **Source:** services/orchestrator/src/modeler_orchestrator/history.py
- **Status:** implemented

### F36 · Campaign monitor

- **Purpose:** Watch a campaign live
- **Problem it solves:** Opaque long runs
- **User:** All roles
- **Where:** /campaigns/{id}
- **Inputs:** Campaign record
- **Processing:** Tabs: stages, fit, rounds, feedback, prediction, package; refresh every 2.5 s while running
- **Outputs:** Rendered monitor
- **Depends on:** read_api
- **Configuration:** -
- **Validation:** -
- **Errors and edge cases:** Polling stops at escalation; hard-coded tier limits; no deployment banner
- **Source:** apps/web/app/campaigns/[campaignId]/page.tsx
- **Status:** implemented

### F37 · Escalation pop-up and decision form

- **Purpose:** Decide with a step-up signature
- **Problem it solves:** Missed escalations
- **User:** Owner / reviewer
- **Where:** Shell overlay
- **Inputs:** Escalations feed
- **Processing:** Poll every 5 s; flash bar; options select; confirm; step-up pop-up and one retry
- **Outputs:** resolveEscalation call
- **Depends on:** Keycloak
- **Configuration:** -
- **Validation:** Only stored options shown
- **Errors and edge cases:** Orphan escalations decidable then 404
- **Source:** apps/web/components/campaign/EscalationPopup.tsx; apps/web/components/EscalationDecision.tsx
- **Status:** implemented

### F38 · Fixture and test-only banners

- **Purpose:** Never present fixture numbers as PBPK
- **Problem it solves:** Misreading stub results
- **User:** All roles
- **Where:** Campaign page
- **Inputs:** engine.kind, realData
- **Processing:** Red banner for non-PK-Sim; TEST ONLY for non-real data
- **Outputs:** Banners
- **Depends on:** runtime.engine_kind
- **Configuration:** -
- **Validation:** -
- **Errors and edge cases:** No banner when engine is null; not in list, MAR or zip
- **Source:** apps/web/app/campaigns/[campaignId]/page.tsx:104-121
- **Status:** partial (gap C-11)

### F39 · Part 11 signatures and audit chain

- **Purpose:** Electronic records and signatures
- **Problem it solves:** 21 CFR Part 11
- **User:** Signers, QA
- **Where:** All signing routes
- **Inputs:** Signer, meaning, record hash, step-up
- **Processing:** signature.create event on a SHA-256 chain; manifestation printed_name | meaning | UTC time
- **Outputs:** audit.jsonl entries
- **Depends on:** auth step-up
- **Configuration:** -
- **Validation:** loa2 within 300 s
- **Errors and edge cases:** Campaign events not audited; DEV signatures look like oidc:loa2
- **Source:** services/api/src/modeler_api/part11.py; services/api/src/modeler_api/compliance/signatures.py; packages/project-model/src/modeler_project/audit.py
- **Status:** implemented (gaps C-11, C-12)

### F40 · Postgres Part 11 copy and verify

- **Purpose:** Durable, append-only Part 11 records
- **Problem it solves:** File-only records
- **User:** QA / operator
- **Where:** Production
- **Inputs:** Audit events, signatures
- **Processing:** Mirror each event into Postgres before the file line; signature rows; nightly verify
- **Outputs:** audit_events, signatures rows
- **Depends on:** PostgreSQL 16
- **Configuration:** MODELER_PART11_STORE, MODELER_DATABASE_URL
- **Validation:** Append-only triggers; revoked UPDATE/DELETE
- **Errors and edge cases:** Verify misses file truncation
- **Source:** packages/storage/src/modeler_storage/part11.py
- **Status:** implemented (production)

### F41 · Engine health check

- **Purpose:** Show whether the engine is PK-Sim and answers
- **Problem it solves:** Silent misconfiguration
- **User:** Admin
- **Where:** /admin/system
- **Inputs:** Configured engine command
- **Processing:** Start the command with no job; read its usage line; cache 60 s
- **Outputs:** Engine status
- **Depends on:** subprocess
- **Configuration:** MODELER_ENGINE_COMMAND
- **Validation:** 20 s timeout
- **Errors and edge cases:** Fixture always reachable
- **Source:** services/api/src/modeler_api/engine_check.py:52-109
- **Status:** implemented

### F42 · Validation pack (IQ/OQ/PQ)

- **Purpose:** GAMP-style validation evidence
- **Problem it solves:** Qualification
- **User:** QA
- **Where:** CI and CLI
- **Inputs:** URS, trace matrix, JUnit, IQ and PQ JSON
- **Processing:** Render IQ/OQ/PQ checks to Markdown
- **Outputs:** Validation pack
- **Depends on:** qualify.sh, T-56 kit
- **Configuration:** -
- **Validation:** PQ requires production and real PK-Sim
- **Errors and edge cases:** IQ not run on server; PQ incomplete; trace matrix counts collected tests
- **Source:** packages/pbpk-domain/src/pbpk_domain/report/validation_pack.py; deploy/server/qualify.py
- **Status:** implemented, not executed end to end

### F43 · T-56 end-to-end kit

- **Purpose:** Scripted proof from proposal to package
- **Problem it solves:** PQ evidence
- **User:** Operator
- **Where:** deploy/proof
- **Inputs:** Mock proposal, published values
- **Processing:** P0 -> P5 via API, sign, start, watch, trace
- **Outputs:** trace.md, pq.json
- **Depends on:** API
- **Configuration:** -
- **Validation:** -
- **Errors and edge cases:** Last server run in pilot with no fit (2026-10-22)
- **Source:** deploy/proof/run_t56.py
- **Status:** implemented

### F44 · Temporal campaign workflows

- **Purpose:** Durable distributed execution
- **Problem it solves:** Single-node limits
- **User:** System
- **Where:** Not deployed
- **Inputs:** CampaignRequest
- **Processing:** ModelingCampaignWorkflow, StageLoopWorkflow, FitRoundWorkflow
- **Outputs:** CampaignOutcome
- **Depends on:** Temporal
- **Configuration:** MODELER_EXECUTION_BACKEND=temporal
- **Validation:** -
- **Errors and edge cases:** SJ/S6/S7 skipped; signals never sent; decisions 503; resume reverts CPF
- **Source:** services/orchestrator/src/modeler_orchestrator/campaign.py; services/orchestrator/src/modeler_orchestrator/fitting.py
- **Status:** partial, not deployed

### F45 · Reference model runner

- **Purpose:** Run published OSP models as is or refit
- **Problem it solves:** Benchmark against published models
- **User:** Developer
- **Where:** deploy/reference; manual CI
- **Inputs:** OSP library snapshots
- **Processing:** Import to CPF + studies, run campaigns or round trips on PK-Sim
- **Outputs:** JSON results
- **Depends on:** pbpk_domain.reference
- **Configuration:** -
- **Validation:** -
- **Errors and edge cases:** Stops at S6 gate; manual only
- **Source:** deploy/reference/run_reference.py; .github/workflows/reference-models.yml
- **Status:** implemented
