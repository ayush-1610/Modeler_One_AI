# 13 · Glossary

Terms as this repository uses them, for the post-MAP scope (campaign on PK-Sim → submission package). Each entry
points at where the term is defined or enforced. Paths are relative to the repository root.

## Regulatory and governance

| Term | Meaning in this repo | Where |
|---|---|---|
| **ICH M15** | ICH guideline on model-informed drug development. Supplies the model-risk tiers (low / medium / high), the credibility assessment and the Model Analysis Report structure (Appendix 2) | `packages/pbpk-domain/src/pbpk_domain/m15.py`; `report/campaign_mar.py` |
| **21 CFR Part 11** | FDA rule on electronic records and signatures. Drives step-up signatures, the hash-chained audit trail and append-only tables | `services/api/src/modeler_api/part11.py`; `services/api/migrations/0001_core.sql` |
| **Model risk / tier** | The ICH M15 rating a person assigns (never assumed). Selects the acceptance limits | `m15.py:17-39`; `campaign_api.py:39` (required on start) |
| **SME** | Subject-matter expert (PBPK lead, clinical pharmacology, QA) who must sign SME-governed content | `docs/SME_SIGNOFF.md` |
| **UNVERIFIED / DRAFT / SME_APPROVED** | Governance status of a ruleset or template. Every post-MAP ruleset is UNVERIFIED or DRAFT today | `pbpk_domain/rulesets/*.yaml`; `docs/SME_SIGNOFF.md` |
| **Locked file** | A file listed and hashed in `docs/architecture/locked-files.json`; changes need the owner's approval in its own PR | `tests/architecture/test_locked_files.py` |
| **Deployment kind** | `development`, `pilot` or `production`. Pilot accepts the DEV verifier; only production signatures are Part 11 | `packages/run-contracts/src/modeler_contracts/runtime.py` |
| **DEV verifier** | `DevVerifier` / `MODELER_DEV_AUTH`: any bearer becomes a fixed principal with a fresh loa2 step-up. Development and pilot only | `services/api/src/modeler_api/auth.py:90-112` |
| **Step-up (loa2)** | Re-authentication with password + TOTP at signing; the API requires `acr == loa2` and `auth_time` within 300 s | `auth.py:163-169`; `deploy/keycloak/realm-modeler.json` |
| **Signature meaning** | One of Authored, Reviewed, Approved, QA Released. Every escalation decision is recorded as Approved | `services/api/src/modeler_api/compliance/signatures.py:22`; `escalations.py:47` |
| **IQ / OQ / PQ** | Installation / operational / performance qualification evidence in the validation pack | `pbpk_domain/report/validation_pack.py`; `deploy/server/qualify.sh` |
| **URS** | User requirements specification (44 requirements, DRAFT for QA) | `docs/validation/requirements.yaml` |

## Procedure and plan

| Term | Meaning | Where |
|---|---|---|
| **MS-01** | The PBPK modelling standard the platform executes (v1.3; v1.0 finalised, v1.1–1.3 UNVERIFIED) | `docs/PBPK_MODELING_WORKFLOW.md`; `campaign/map.py:81` |
| **CPF** | Compound Parameter Framework: immutable, versioned per-compound parameter document (value, unit, status, fit policy, plausibility, provenance, engine binding, uncertainty). The system of record; every simulation is regenerated from it | `pbpk_domain/cpf/models.py` |
| **Parameter status** | FIXED, PREDICTED, FITTED, DERIVED… A fit writes FITTED with `fitted_at_stage` | `cpf/models.py`; `fit_spec.py:280-306` |
| **Fit policy** | Stages at which a parameter may be fitted, with bounds and scale (linear / log) | `cpf/models.py:33-47` |
| **Plausibility** | The range a value may never leave; fit policy ⊆ plausibility | `cpf/models.py:50-61,166-171` |
| **Fit group** | Parameters fitted as one factor ("Use as Factor", PI-4 B2) | `cpf/models.py:64-88`; `run_pi.R:100-290` |
| **MAP** | Model Analysis Plan: signed, hashed plan holding the parameter table, studies and split, stage plan with budgets and round limits, scenarios, acceptance criteria, internal target, applications, risk assessment | `pbpk_domain/campaign/map.py:335-414` |
| **MAP deviation** | A post-signature change that makes a new MAP version superseding the signed one (D-14); a feedback "learn" decision writes one | `map.py:403-414`; `orchestrator/feedback.py:218-249` |
| **D-35 / D-36 / D-37** | Owner decisions: runs are judged by the criteria signed in the MAP (D-35); a pilot/production run's CPF must equal the MAP's parameter table (D-36); unfreed MS-01 candidates are fitted within MS-01 default bounds (D-37) | `campaign_activities.py:786-789`; `run_guard.py:85-105`; `modeler_project/plan.py:911-942` |
| **D-19 real-data rule** | A verdict judged on data that is not real may not be signed outside an exploratory project ("TEST ONLY") | `pbpk_domain/data_origin.py`; `local_runner.py:1178-1182` |
| **Study class** | IV-SD, PO-SOL-FASTED, PO-IR-FASTED, PO-FED, PO-MD, PO-MR, PO-OTHER, DDI, PGX, SPECIAL, PRECLINICAL | `campaign/split.py:23-34` |
| **INTERNAL / EXTERNAL / SUPPORTIVE** | Study roles: train (fit), validate (blind), context only | `split.py:42-45` |
| **Scenario** | A MAP row describing one study's simulation at one stage (route, dose, formulation, food state, population, analyte) | `map.py:208-260` |
| **Stage plan** | Per stage: fit candidates, branches, max rounds, budget seconds | `map.py:41-81, 625-674` |

## Campaign mechanics

| Term | Meaning | Where |
|---|---|---|
| **Campaign** | One execution of the signed MAP's stages S0→S7 for a compound (`camp_<uuid>`) | `services/api/src/modeler_api/campaign_api.py` |
| **Stage** | S0 readiness, S1 IV, S2 oral fasted, S3 formulation/fed, SM metabolites, SJ joint refinement, S4 internal validation, S5 external validation, S6 prediction, S7 report & package | `modeler_contracts/runs.py:194`; `local_runner.py:79-83` |
| **Round** | One build → simulate → (fit) → evaluate → diagnose → choose cycle inside a training stage | `local_runner.py:996-1048` |
| **Gate** | The stage's pass test: acceptance criteria (+ VPC at S1/S2) | `campaign/evaluate.py`; `campaign/vpc.py` |
| **Escalation** | A stop that waits for a signed human decision (retry, accept_best, abort; validation: limitation or stop) | `local_runner.py:92-109, 417-423` |
| **Signature gate (S6)** | The pause before S6 until the S4/S5 evaluation is signed ("approve") | `local_runner.py:476-487` |
| **Feedback cycle** | S5 failure handling: limitation, learn (studies move to internal, MAP deviation), new evidence (measured value), stop; cycle counter c | `orchestrator/feedback.py` |
| **No-regression gate** | After a training stage changes the CPF, every earlier passed stage is re-judged on the new CPF | `local_runner.py:834-858` |
| **SJ / S1-CI guard** | Joint refit of all training-stage parameters over every internal study with equal study weights; S1-fitted parameters held inside their S1 95 % CI | `orchestrator/joint.py` |
| **fix_and_refit** | For a correlated pair (|r| > 0.95), fix the better-sourced parameter at its signed value and refit the other | `pbpk_domain/identifiability.py`; `campaign_activities.py:224-293` |
| **Permitted action** | An action string `"{op} {target}"` the diagnostics ruleset allows at this stage (`fit`, `fix_and_refit`, `branch`, `switch`, `switch_algorithm`) | `pbpk_domain/diagnostics.py` |
| **Strategist** | Chooser among permitted actions; deterministic first-untried today (LLM decider unwired) | `services/agents/src/modeler_agents/strategist.py` |
| **Model set** | Identity of what a verdict judged: CPF hash + engine key + stage scenario hash + builder version | `orchestrator/memo.py:107-119` |
| **Memoised run** | Reuse of an identical earlier successful engine job's outputs; S7 re-runs exempt | `orchestrator/memo.py` |
| **Change ledger** | Every working-parameter-set change and the verdicts it moved | `orchestrator/history.py` |
| **Influence map** | Parameters × studies, structural (from MAP scenarios) and quantitative (S6 sensitivities) | `history.py` |
| **Model system** | Several compounds simulated together (parent, metabolites, enantiomers), with analytes and products | `pbpk_domain/system.py` |
| **Analyte / gated / reported** | What a study measures; whether it enters a stage's gate or is only shown | `system.py:204-246` |

## PK, fitting and evaluation

| Term | Meaning | Where |
|---|---|---|
| **NCA** | Non-compartmental analysis: linear-up/log-down AUC from the first sample, terminal phase by adjusted R² over ≥ 3 points | `pbpk_domain/nca.py` |
| **Fold error / ratio** | predicted ÷ observed; passes a tier when 1/f ≤ ratio ≤ f | `acceptance.py:104-120` |
| **GMFE** | Geometric mean fold error = 10^mean\|log10(ratio)\| | `metrics.py:41-45` |
| **Guest limits** | Variable acceptance range for DDI ratios, limit = (δ(R−1)+1)/R, δ = 2 | `metrics.py:58-71` |
| **Internal target** | MAP's stricter \|PE\| ≤ t % on internal AUC/Cmax (default 10 %, UNVERIFIED) | `acceptance.py:38-44` |
| **VPC** | Visual predictive check: share of observed points inside the 5–95 % band of a 100-individual population; gate ≥ 80 % at S1/S2 | `campaign/vpc.py` |
| **PI** | Parameter identification in `ospsuite.parameteridentification` 2.2.0, one start per engine job | `services/engine-worker/r/run_pi.R` |
| **Multistart** | 4–32 Latin-hypercube starts sized to the time budget | `pbpk_domain/fitting.py:116-140` |
| **BOBYQA / DEoptim** | Optimisers; the platform always uses BOBYQA | `fit_spec.py:220` |
| **Hessian CI** | Confidence interval from the Hessian at the optimum; correlations from its covariance | `run_pi.R:206-233` |
| **Sensitivity (S6)** | Local ±10 % sensitivity of AUC/Cmax to FITTED/PREDICTED parameters | `campaign/prediction.py:30-52` |
| **Uncertainty (S6)** | 200 independent draws of fitted parameters → P5/P50/P95 of AUC and Cmax | `prediction.py:54-118` |
| **VBE** | Virtual bioequivalence: K trials × n virtual subjects, TEST vs reference arm, 90 % CI of the GMR, probability of success (PoS) | `pbpk_domain/vbe.py`; `orchestrator/vbe_activities.py` |
| **F-304 gate** | VBE validation against an observed BE study; NOT_VALIDATED without one | `vbe.py:72-100` |

## Engine and package

| Term | Meaning | Where |
|---|---|---|
| **OSP / ospsuite / PK-Sim** | Open Systems Pharmacology suite; the R package `ospsuite` 12.4.4 drives PK-Sim 12.3 on .NET 8 | `services/engine-worker/Dockerfile` |
| **Snapshot** | PK-Sim project JSON (schema v80/81) the builder writes and `runSimulationsFromSnapshot` runs | `pbpk_domain/snapshot/builder.py` |
| **pkml** | A single simulation exported from PK-Sim; input to PI, population, sensitivity and batch tasks | `run_job.R` |
| **.pksim5** | A PK-Sim project file; S7 writes one per bundled simulation (`convert_to_project`) | `orchestrator/package_activities.py` |
| **ValueOrigin** | PK-Sim provenance block (Source, Method, Description); Source restricted to the harvested enum | `snapshot/models.py:21-78` |
| **Engine catalog** | Harvested PK-Sim names, units, process types (`golden/catalog.json`) | `services/engine-worker/r/harvest_catalog.R`; `pbpk_domain/catalog.py` |
| **Engine job / manifest** | `EngineJob` in, `EngineManifest` (status, outputs with sha256, warnings, engine_info) out | `modeler_contracts/runs.py:20-60` |
| **Software fixture** | `stub_engine.py` / `analytical_engine.py`: test engines, never PBPK evidence; labelled "Not a PBPK result" | `deploy/dev/`; `runtime.py:61-85` |
| **Engine kind** | `pksim`, `software-fixture` or `unknown`, derived from the engine command's basename | `runtime.py:61-76` |
| **Bundle / package** | S7 output: data bundle with manifest and hashes, MAR, `rerun_all.R`, PK-Sim projects; zipped only if reproduction passed | `pbpk_domain/reproducibility.py`; `package_activities.py` |
| **Reproducibility gate** | S7 re-runs every bundled simulation on a fresh engine process and compares result tables at 1e-6 | `package_activities.py`; `reproducibility.py` |
| **MAR** | Model Analysis Report (ICH M15 Appendix 2) in Markdown, DOCX and PDF/A-2b, with an evidence index | `pbpk_domain/report/mar.py`, `campaign_mar.py`, `render.py` |
| **T-56 kit** | Scripted end-to-end proof P0 → P6 on the server, producing `trace.md` and `pq.json` | `deploy/proof/` |
| **LocalExecutor** | The single-node in-process campaign runner actually used | `orchestrator/local_runner.py` |
| **Temporal path** | `ModelingCampaignWorkflow` / `StageLoopWorkflow` / `FitRoundWorkflow`: built and tested, not deployed | `orchestrator/campaign.py`, `fitting.py`, `workflows.py` |
