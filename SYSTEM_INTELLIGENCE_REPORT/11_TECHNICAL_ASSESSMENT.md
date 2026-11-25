# 11 · Technical quality and engineering assessment (post-MAP scope)

**Method.** Six evidence slices (see `evidence/`) plus the lead investigator's own reading of the orchestration spine.
Findings are **CONFIRMED** (the code path is unambiguous from the cited lines; not executed against PK-Sim) or
**POTENTIAL** (plausible, depends on data or deployment). **(L)** marks findings the lead investigator re-verified line
by line. Severity is the investigator's judgement for a product whose goal is a regulator-reviewable package:
**Critical** (undermines a Part 11 control or the scientific claim), **High**, **Medium**, **Low**.

## 1. Scorecard

| Dimension | Rating | Basis |
|---|---|---|
| Modularity / layering | Strong | L0–L7 layers enforced by tests with zero recorded exceptions; pure L0 domain; one engine port |
| Determinism and provenance | Good | CPF versions with provenance and CI; model sets; memo keyed by content; seeded multistart |
| Scientific completeness | Partial | S1–S7 implemented, but 3 action types are no-ops, 5 evidences never computed, fed sub-loop impossible, S6 limited |
| Compliance controls (Part 11) | Weak in places | step-up signatures and a hash chain exist; gate enforcement, signature binding, separation of duties, deliverable signatures and event audit have confirmed gaps |
| Reliability | Weak | in-process daemon threads, no recovery, no cancel, one failed start fails a stage |
| Scalability | Limited | single node; whole-file JSON stores; no cross-campaign CPU scheduling |
| Performance | Adequate for simple compounds | 0.506 s per simulation; 75.9× batch speedup on 47 cores; model-system refits exceed 1 h |
| Test coverage | Broad but stub-only | 1,205 in-scope tests; every S1–S7 behaviour runs on stub/scripted engines in CI |
| Observability | Minimal | no logging configuration, metrics or tracing in scope |
| Security architecture | Mixed | OIDC + step-up, RLS and append-only tables designed; client-supplied `file://` paths trusted at the API |
| Dependency management | Mixed | `uv.lock` and pinned engine image; the server installs unpinned R packages; CI actions on mutable tags |
| Deployment readiness | Pilot | one server, rsync deploy, cron watchdog; distributed design not deployed |
| Maintainability | Moderate | large hotspot functions; duplicated loop control in two execution paths that have drifted |

## 2. Confirmed defects

### 2.1 Compliance and record integrity

| ID | Sev. | Finding | Evidence |
|---|---|---|---|
| C-01 (L) | Critical | The decision action is never checked against the escalation's offered options. `accept_best` at the S6 signature gate marks S6 ACCEPTED, skips the D-19 real-data refusal and S6, and runs S7. `retry` is also accepted at S4/S5, where MS-01 offers none | `services/api/src/modeler_api/escalations.py:202, 248`; `services/orchestrator/src/modeler_orchestrator/local_runner.py:1277-1306` |
| C-02 (L) | Critical | `map_signed` accepts any JSON at the client-supplied `file://` URI whose `status` is `SIGNED` with a truthy `signature`; the content hash is not recomputed and the signature is not looked up | `run_guard.py:46-65`; no `content_sha256()` comparison anywhere at start |
| C-03 | High | The run guard reads arbitrary `file://` paths named by the client, and its D-36 error echoes the pydantic exception (which includes a truncated `input_value`), so fragments of server files can leak to a project owner | `run_guard.py:38-43, 93-100` |
| C-04 (L) | High | Inputs are not bound at start: the client's `cpf_sha256` is never recomputed; `map_sha256` and `observed_sha256` are never set; the client's `stages` list is honoured, so omitting S1–S5 makes the D-19 check pass vacuously | `campaign_api.py:55-62`; `pbpk_domain/data_origin.py:75-88` |
| C-05 (L) | High | `campaign:prepare` rewrites `prep/{question_id}/{cpf,map,observed}.json` in place while a campaign started from them keeps reading those paths | `write_api.py:260-266`; `local_runner.py:593-600` |
| C-06 | High | Nothing signs the MAR, the package, the final CPF or a QA release in the deployed path; the Temporal final-CPF signal has no sender | `pbpk_domain/report/campaign_mar.py:414-420`; `campaign.py:396-404` |
| C-07 | High | The S4/S5 evaluation signature binds `sha256("cid:stage:action")`, not the evaluation content; its meaning is Approved, not Reviewed | `escalations.py:258-270` |
| C-08 (L) | High | No separation of duties: `may_change(signing=True)` admits the owner whatever their realm role, so a curator can start a campaign and sign its escalations and evaluation; no check that the signer differs from the starter | `ownership.py:54-65` |
| C-09 | Medium | The one-click Run button prepares, signs (`map_approval` via the generic route, no role check) and starts in one click; the MAP is never shown | `apps/web/components/RunCampaignButton.tsx:28-64`; `signatures_api.py:26-49` |
| C-10 (L) | High | A stage that escalates and is then accepted never writes its evidence: the MAR says "not run", an accepted S4/S5 is neither bundled nor reproduced, the signed S5 limitation never reaches the MAR | `local_runner.py:554-556, 1277-1286`; `campaign_mar.py:272-275` |
| C-11 | High | Fixture and pilot output can pass as evidence: the MAR and zip carry no engine kind or deployment; a stub campaign releases an "exportable" package; DEV-verifier signatures are stored as `oidc:loa2`; the campaign page shows no deployment banner and no engine banner when `engine` is null | `compliance/signatures.py:114`; `auth.py:102`; `apps/web/app/campaigns/[campaignId]/page.tsx:106`; `services/orchestrator/tests/test_local_runner.py:551` |
| C-12 | Medium | Campaign start, stage verdicts, S7 release and downloads write no audit event; only signatures are chained | grep: no audit call in orchestrator, `campaign_api.py`, `read_api.py` |
| C-13 | Medium | A signature is recorded before the decision is claimed; a lost race or a 422 leaves a signature for a decision that was not applied | `escalations.py:270-281`; `filestore.py:183-194` |
| C-14 | Medium | `part11 verify` does not detect a truncated file chain and does not compare signature rows | `packages/storage/src/modeler_storage/part11.py:159-177` |
| C-15 | Medium | Temporal `escalation:decide` and `deviations` take a password and second factor in the body, the tenant from a header, no bearer; always 503 (R-S06) | `escalations.py:83-84, 100-179` |
| C-16 | Low | A campaign without a project, or a project with no owner on record, lets any authenticated tenant user (QA included) sign a decision | `escalations.py:236-239`; `ownership.py:65` |
| C-17 | Low | Every decision is recorded with meaning Approved, abort included; the rationale is optional | `escalations.py:47, 203` |

### 2.2 Model-building and scientific correctness

| ID | Sev. | Finding | Evidence |
|---|---|---|---|
| S-01 (L) | High | "Accept the best round" accepts the latest round's CPF (both paths); fit estimates are applied without comparing with the pre-fit objective or verdict | `local_runner.py:649-650`; `campaign.py:123-124`; `campaign_activities.py:619-671` |
| S-02 (L) | High | `branch` (partition/permeability method), `switch` (Michaelis-Menten) and `switch_algorithm` (DEoptim) are offered, marked tried and change nothing; the optimiser is always BOBYQA | `campaign_activities.py:221, 438`; `pbpk_domain/fit_spec.py:220` |
| S-03 | High | Five evidences are never computed (secondary peak, MD accumulation, permeability shape, two fed signals), so the EHC, time-dependent clearance, permeability-limited, fed-solubility and gastric-emptying rules cannot fire | `pbpk_domain/diagnostics.py:42-63`; `campaign_activities.py:999-1000` |
| S-04 | High | The S3 fed sub-loop cannot run: `food.fed_solubility_factor` has no placement or engine path, and a value under that id is silently left out of the model without being reported as unresolved | `pbpk_domain/parameters/registry.yaml:102`; `pksim_paths.py:65-71`; `cpf/build.py:596-606` |
| S-05 (L) | Medium | The IV distribution rule cannot fire for an IV bolus: the profile-shape evidence returns None without an infusion time | `pbpk_domain/campaign/evaluate.py:222` |
| S-06 | Medium | `run_pi.R` sets no objective, weighting or BLQ options, so SD weighting and LLOQ handling are PI 2.2.0 defaults (weighting "none" per CHANGELOG); `docs/WORKFLOW_AND_AUTOMATION.md:105` claims SD weighting | `run_pi.R` (grep); CHANGELOG:5207-5210 |
| S-07 | Medium | A study the engine drops (missing CSV or plasma column) is only a `WARNING` no code reads; the gate judges the remaining studies without saying so | `run_job.R:87-111`; `campaign_activities.py:738-755` |
| S-08 | Medium | S6 is limited: ±10 % local sensitivity only (no EMA 10×/30× worst case), independent uncertainty draws (no covariance), rejection sampling without an iteration cap | `pbpk_domain/campaign/prediction.py:30-100` |
| S-09 | Medium | Fits from feedback cycle ≥ 2 are not found by the bundle: the fit directory uses `round_id` without `-c<k>` while provenance `run` includes it | `campaign_activities.py:404` vs `:639`; `package_activities.py:283-287` |
| S-10 | Medium | A VBE that did not run puts the template version ("0.2" from `0.2.0-draft`) in MAR prose; the bare-number lint then withholds the package | `campaign_mar.py:182-186`; `report/mar.py:27`; `package_activities.py:411` |
| S-11 | Medium | Every fed study gets the MAP's single meal template ("Meal: High-fat breakfast (Human)"); `meal_type` is ignored | `campaign/map.py:546, 640` |
| S-12 | Medium (static trace) | `elim.ehc_fraction`, placed on the Individual, is likely also listed as an unplaced elimination parameter, which would fail S0 | `cpf/build.py:596-606`; `campaign_activities.py:153` |
| S-13 | Low | The MAP's "CV > 50 %" escalation trigger is not enforced (POORLY_DETERMINED is not passed to diagnostics) | `pbpk_domain/fitting.py:193-242`; `diagnostics.py:50-55` |
| S-14 | Low | Planner assumes 40 evaluations per start and 48 cores by default while the spec allows 200 evaluations; a null `convergence` is treated as converged | `campaign_activities.py:66-68, 407`; `fitting_activities.py:110` |
| S-15 | Low | Reproduction compares with `abs_tol=1e-6` besides `rel_tol`, which lets percent-level differences pass at low µmol/l concentrations | `pbpk_domain/reproducibility.py:123` |
| S-16 | Low | The web page hard-codes the tier fold limits instead of reading the signed MAP | `apps/web/app/campaigns/[campaignId]/page.tsx:73` |

### 2.3 Reliability and operations

| ID | Sev. | Finding | Evidence |
|---|---|---|---|
| O-01 (L) | Critical | Campaigns run on daemon threads in the API process. A restart (every deploy, the watchdog) loses them; the lifespan hook resumes only Data room runs; the record stays RUNNING; there is no cancel, stop or resume route | `local_runner.py:1153-1169, 1308-1316`; `services/api/src/modeler_api/main.py:44-56` |
| O-02 (L) | High | Locally, one failed or timed-out PI start fails the whole stage (thread pool re-raises), and there is no fit deadline cancellation (`deadline_reached=False`) | `local_runner.py:1050-1069`; `services/engine-worker/src/modeler_engine/runner.py:129-137` |
| O-03 | Medium | Exceptions outside the stage `try` (S0 planning, `plan_stage`, no-regression, `_influence`, flush) kill the thread silently | `local_runner.py:453-560` |
| O-04 | Medium | Duplicate starts: no idempotency key, no campaign lease, and "Run the campaign (P6)" has no busy state | `PlanCanvas.tsx:373-380`; `services/api/src/modeler_api/jobs.py:22` |
| O-05 | Medium | `~/modeler-data` (all campaign records, CPFs, outputs, packages) is not backed up; no retention or disk guard; root disk reported 95 % full | `deploy/server/postgres.sh:148-161`; `docs/CONTINUATION_PACKAGE.md:46` |
| O-06 (L) | Medium | One `campaigns.json` per tenant holds every campaign (GOF series, VPC bands, ledger) and is rewritten whole at each of 18 flush points; every read loads it all | `packages/storage/src/modeler_storage/filestore.py:142-175`; `read_api.py:128-155` |
| O-07 | Low | Engine subprocesses start in their own session and can outlive the API; `stop_modeler.sh` kills any Next.js process of the user | `runner.py:179`; `deploy/server/stop_modeler.sh:20-21` |
| O-08 | Low | No cross-campaign CPU scheduling; ospsuite's default core count per job can oversubscribe when fits, populations and batches run together | `local_runner.py:145-153`; `run_job.R` |

### 2.4 Engine plane and supply chain

| ID | Sev. | Finding | Evidence |
|---|---|---|---|
| E-01 | High | Engine identity is asserted, not measured: the server digest is the hash of the committed `catalog.json`; the engine id is hard-coded `ospsuite-12.4.4` from the script name; the MAP's `software_versions` is a literal; `engine_manifest.json` versions are never compared | `deploy/server/_env.sh:57-61`; `modeler_contracts/runtime.py:59-85`; `write_api.py:253` |
| E-02 | High | The memo key ignores the content of `run_job.R` / `run_pi.R`; a fix deployed by rsync keeps serving old memoised outputs | `local_runner.py:1072-1075`; `memo.py:46-50` |
| E-03 | Medium | The catalog binding gate (`cpf.binding.bind`) has no production caller; the committed catalog lacks 8 process types and 1 formulation type that vendored fixtures use | `pbpk_domain/cpf/binding.py:55`; `services/engine-worker/golden/catalog.json` |
| E-04 | Medium | The CI golden gate never runs `run_job.R simulate` (CSV → profiles mapping, with an open naming note) or `parameter_identification` through `run_job.R`; `golden.json` is a literal `true` | `.github/workflows/engine-image.yml:50-74`; `run_job.R:65-66` |
| E-05 | Medium | The digest-pinned, cosign-signed image is consumed by nothing; its base is tag-pinned, rSharp unhashed; the server installs the newest PI while `run_pi.R` overrides private 2.2.0 internals | `Dockerfile:12-77`; `scripts/ubuntu_engine_check.sh:92-107`; `run_pi.R:235-290` |
| E-06 | Low | The engine env allow-list drops `MODELER_ENGINE_IMAGE` and `DOCKER_*`, so the Docker shim always runs its default tag | `runner.py:28`; `deploy/dev/docker_engine.sh:19` |
| E-07 | Low | The analytical fixture writes JSON into `*.pkml` files | `deploy/dev/analytical_engine.py:240-244` |

### 2.5 Package integrity

| ID | Sev. | Finding | Evidence |
|---|---|---|---|
| P-01 | Medium | `rerun_all.R`, shipped for reviewers, is never executed by the platform or any test; no comparison script ships with it | `reproducibility.py:155-186`; `package_activities.py:294-307` |
| P-02 | Medium | The zip is not byte-reproducible (`writestr` timestamps); the manifest covers neither `manifest.json` nor `rerun_all.R`; `package_sha256` is a list hash, not a zip hash | `reproducibility.py:44-47, 189-209` |
| P-03 | Low | `verify_bundle_integrity` has no production caller; downloads are not re-verified | `reproducibility.py:89-104`; `read_api.py:215-234` |
| P-04 | Low | Server `file://` paths leak into `evidence/*.json` inside the zip and into `resume` on the campaign record | `local_runner.py:479-480, 721-726` |
| P-05 | Low | S6 numbers are not reproduced; `prediction/s6.json` lacks the VBE result | `package_activities.py:238-240` |
| P-06 | Low | The M15 table renders only the four rated rows; `technical_criteria` and evaluation text are computed but not rendered; `validate_table` is not run at S7 | `report/mar.py:298-310` |
| P-07 | Low | The Package tab attributes every withheld package to reproduction, even when the cause is a report issue | `page.tsx:308-310` |

### 2.6 Architecture and unfinished paths

| ID | Sev. | Finding | Evidence |
|---|---|---|---|
| A-01 (L) | Medium | The Temporal path cannot complete a campaign: SJ/S6/S7 SKIPPED, no no-regression or feedback cycles, signed MAP limits ignored, no monitor record, `map_signed`/`accept_final_cpf` signals never sent, decisions 503 | `campaign.py:64-66, 342-364, 396-404`; `escalations.py:83-84` |
| A-02 (L) | Medium | Temporal resume pairs the starting CPF's URI with the final CPF's hash, discarding fits | `campaign_store.py:52-55` |
| A-03 (L) | Low | `ingest_results` is a placeholder; the results API reads a path ingest never writes and has no role/project check | `activities.py:24-30`; `results_api.py:30-36` |
| A-04 (L) | Low | Postgres status enums omit QUEUED, AWAITING_SIGNATURE, ABORTED (campaign) and SKIPPED (stage) | `services/api/migrations/0002_campaigns.sql` |
| A-05 (L) | Low | The LLM strategist is built but unwired; if wired, its bounds override is checked only for lo < hi, not against the signed MAP | `campaign_activities.py:1054-1073`; `strategist.py:88-98` |

### 2.7 UI and quality

| ID | Sev. | Finding | Evidence |
|---|---|---|---|
| U-01 | Medium | The UI offers actions the API refuses ("Approve and Sign" to curators; "Run the campaign" to non-owner reviewers); orphan escalations are decidable in the UI and answer 404 | `PlanCanvas.tsx:224, 312, 373`; `read_api.py:298-299` |
| U-02 | Low | Monitor polling stops at ESCALATED/AWAITING_SIGNATURE, so a decision taken elsewhere is not reflected until reload | `AutoRefresh.tsx:8-15`; `page.tsx:122` |
| Q-01 | Medium | No real-engine test runs on a change to the builder, evaluation or orchestrator; full PK-Sim campaigns are manual dispatch only | `.github/workflows/engine-image.yml` (path filter); `reference-models.yml:15-16` |
| Q-02 | Medium | The Temporal suite downloads its test server at run time and fails rather than skips without network | `services/orchestrator/tests/test_campaign_workflows.py:113` |
| Q-03 | Low | 29 in-scope test files carry no `req` tag (incl. `test_acceptance.py`, the S0→S7 test); the trace matrix counts collected, not passed, tests | `conftest.py:27-48`; `validation_pack.py:133-135` |
| Q-04 | Low | No logging configuration, metrics or tracing; `activity.logger` INFO messages are dropped on the local path | grep in scope |
| Q-05 | Low | The lock guard does not lock itself; the orchestrator, `campaign/evaluate.py`, fitting, NCA, VBE and report code are unlocked; no CODEOWNERS | `docs/architecture/locked-files.json` |
| Q-06 | Low | Ruff runs only its minimal default rules; CI's `PYTHON_VERSION: "3.12"` is never used by a step | `pyproject.toml`; `ci.yml:28` |

## 3. Potential concerns (not demonstrated)

- Keycloak's HTTP listener (8080) may bind all interfaces (`deploy/server/keycloak.sh:189-191`).
- A refreshed token may lose `acr=loa2` between the pop-up and the retry (untested against the realm).
- The printed name on a signature comes from user-editable profile fields (`auth.py:52`).
- Model-system S6 CSV parsing takes the first plasma column, which may be the wrong compound (`prediction.py:109, 128`).
- PK-Sim CSV matching by `endsWith` can confuse simulations whose names share a suffix (`run_job.R:83`).
- A DOCX render error is not caught and would FAIL S7 (`render.py:114-117`); PDF/A-2b output is not validated.

## 4. LocalExecutor vs Temporal (summary)

Both call the same activities; loop control is written twice and has drifted: budgets (signed MAP vs request/1800 s),
retry (fresh stage vs consumed round), fit deadline (none vs cancellation), failed start (stage FAILED vs tolerated),
`BudgetTooSmallError` (escalate vs uncaught), SJ / no-regression / S6 gate / S6 / S7 / feedback (present vs absent),
monitor (`campaigns.json` vs Postgres rows only). Full table: `evidence/E_quality.md` §6.

## 5. Test and lint results (run in this container, 2026-11-25)

| Run | Result |
|---|---|
| Orchestrator, engine worker, contracts | 149 passed, 14 failed (Temporal test-server download blocked), 7 skipped |
| pbpk-domain, storage, architecture | 923 passed, 5 skipped |
| API (all) + strategist | 431 passed, 11 skipped (in scope: 83 + 13 passed) |
| **In-scope total** | **1,168 passed, 14 failed, 23 skipped of 1,205** |
| `ruff check` (scope and repo) | all checks passed (minimal rule set) |

Python 3.13.18 (no `.python-version`; CI intends 3.12). Skips need Docker, PostgreSQL 16 as non-root, or a reference
snapshot. Nothing ran PK-Sim.

## 6. Technical debt hotspots

- Size: `local_runner.py` 1,411 lines (`LocalExecutor.run` 154 lines; also holds the monitor writer, engine selection,
  escalation resolution, feedback start and a CLI), `campaign_activities.py` 1,106, `snapshot/builder.py` 1,302,
  `cpf/build.py` 750, `campaign/map.py` 696, `report/campaign_mar.py` (`assemble_campaign_mar` 183 lines).
- Eleven separate `file://` → `Path` helpers with different error behaviour.
- The MAP is re-parsed several times per round.
- Stale documentation: the continuation doc's test count (758 vs 3,647 collected repo-wide), MinIO "not built", T-23/T-24
  "not wired", the M15 capture gap, the log-scale limitation, and "rebuild the server's engine image" (the server runs
  no image). See `evidence/F_docs_deploy.md` §6.
