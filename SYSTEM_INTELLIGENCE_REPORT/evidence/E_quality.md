# E — Tests, CI, guardrails and engineering quality (post-MAP campaign scope, S1–S7)

Repository: `/workspace/Modeler_One_AI` at `1dbda7f` (2026-11-25, shallow clone of 193 commits). Audit date 2026-11-25.
Read-only: no tracked file was edited. `uv sync --all-packages` created `.venv/` (gitignored: `.gitignore:3 .venv/`);
pytest left only gitignored `__pycache__/` and `.ruff_cache/`. `git status --short` is clean.

Labels: **VERIFIED** = I ran it or read the code at the cited line. **INFERRED** = a conclusion from reading that I did
not execute.

---

## 1. Summary

- **Test run (VERIFIED, this container, Python 3.13.18):** 1,205 in-scope test items collected. **1,168 passed, 14
  failed, 23 skipped.** All 14 failures are `services/orchestrator/tests/test_campaign_workflows.py` (the whole Temporal
  suite). They fail because the Temporal test-server binary is downloaded from `temporal.download` at test time, and
  this container's proxy refuses that host (`curl` → `CONNECT tunnel failed, response 403`). They are not code
  failures, but the suite fails where it should skip. The 23 skips need Docker (testcontainers Postgres/MinIO),
  PostgreSQL 16 binaries run as a non-root user, or a PK-Sim snapshot file. For comparison, the whole repository
  collects 3,647 tests. `docs/CONTINUATION_PACKAGE.md:18` still says "758 Python tests".
- **Ruff (VERIFIED):** `ruff check` on the four in-scope packages and on the whole repo: "All checks passed!" (ruff
  0.16.7 from `uv.lock`). The rule set is ruff's minimal default (E4/E7/E9/F). `pyproject.toml [tool.ruff.lint]` only
  ignores C408 and selects nothing, so the lint gate is shallow.
- **Engine coverage:** in Python CI, every S1–S7 behaviour (round loop, fit application, VPC gate, SJ, no-regression,
  S6 sensitivity/uncertainty/VBE, S7 reproduction and package, the feedback cycles, escalation resolve) runs only
  against **in-test stub engines, a scripted executor, or `deploy/dev/stub_engine.py`**. The browser e2e also runs on the
  stub engine. Real PK-Sim runs only in `engine-image.yml`, as golden scripts triggered by changes to `engine-worker/` or
  `run-contracts/`. `reference-models.yml` (full campaigns on PK-Sim) runs on manual dispatch only. A change to the
  builder, evaluation or orchestrator therefore never triggers a real-engine run in CI.
- **Guardrails (VERIFIED, all 183 architecture items pass):** import layering, seams, typed responses, artifact owners,
  config readers, process-state, the OpenAPI snapshot, parameter vocabulary and registry, and locked-file hashes. The
  lock is a visibility mechanism, not enforcement:
  - `locked-files.json` and `test_locked_files.py` are not locked themselves.
  - There is no CODEOWNERS file.
  - Much of the science code is unlocked: `campaign/evaluate.py`, `fitting.py`, `fit_spec.py`, NCA, metrics, VBE and
    all of the orchestrator.
- **Two execution paths diverge.** The single-node `LocalExecutor` is the deployed path and implements S0–S7, SJ,
  no-regression, the S6 gate, VBE, S7 and the feedback cycles. The Temporal path skips SJ, S6 and S7 by design
  (`campaign.py:356-363`). It also cannot complete a campaign through the shipped API:
  - nothing sends the `map_signed` or `accept_final_cpf` signals;
  - its escalation endpoint's verifier always returns 503 and takes a password in the body;
  - its DB resume discards the fitted CPF.

  The two round loops are about 200 near-duplicate lines each, and their limits and retry semantics have drifted.
- **Most important defects** (detail in §8):
  1. Local campaigns run on daemon threads with no lease and no recovery at startup. A restart, or an exception
     outside the stage `try`, leaves a campaign at RUNNING for good.
  2. "Accept the best round" actually accepts the *latest* round's CPF, in both paths.
  3. The campaign start records no MAP or observed-data hash, and nobody re-hashes the client-supplied CPF.
  4. 29 in-scope test files carry no `req` tag, including `test_acceptance.py` and the Temporal suite. The validation
     pack therefore under-reports coverage.
  5. Observability is minimal: no `logging` in the orchestrator or engine worker beyond Temporal's `activity.logger`,
     no metrics, no tracing.

---

## 2. Test inventory (in-scope)

Notes on the columns:
- "# tests" = `def test_` count / collected items, where parametrisation changes it.
- "Engine":
  - *none* = pure logic, no engine;
  - *golden output* = reads `services/engine-worker/golden/` PK-Sim artefacts (real PK-Sim output files, but no engine
    call);
  - *in-test stub* = a Python class in the test that writes profiles;
  - *scripted* = `services/orchestrator/tests/scripted.py` `ScriptedExecutor`, which replaces `_run_round` with lookup
    tables;
  - *Temporal TS* = Temporal time-skipping test server with mocked activities;
  - *stub_engine.py* = `deploy/dev/stub_engine.py` run as a subprocess.
- No in-scope Python test runs Rscript or PK-Sim.

### 2a. Orchestrator, engine worker, contracts, storage, strategist

| Test file | Covers | # tests | Engine used | req tags |
|---|---|---|---|---|
| services/orchestrator/tests/test_local_runner.py | LocalExecutor end to end: S0 gate, S1 loop, escalation records, abort / accept_best / retry, engine-failure → FAILED, IV-only skips, S4 failure, VPC gate, S0→S7 with S6 signature gate and reproducible package (`:503`), package withheld on reproduction failure, synthetic-data signing refusal, memo, SJ, limits from the signed MAP, fit note | 27 / 27 | in-test `StubEngine`/`VpcStubEngine`/`FullStubEngine`/`PiStub` writing the golden PK-Sim profile | T-46 (2), T-51, T-53, T-13 — only 5 of 27 tagged; the S0→S7 test is untagged |
| services/orchestrator/tests/test_campaign_workflows.py | Temporal StageLoop and ModelingCampaign state machine: pass, rounds exhausted, deadline, abort / accept / retry signals, MAP signal, S0 not ready, resume skip, nothing-to-simulate skip, validation judged once, fit judged in its own round | 14 / 14 | Temporal TS, all activities mocked | none |
| services/orchestrator/tests/test_nonlinear.py | no-regression gate, SJ joint refinement, ledger/influence (control flow only) | 7 / 7 | scripted | T-52, T-53, T-54 |
| services/orchestrator/tests/test_feedback.py | S5 feedback cycles: learn / new evidence / limitation / stop, cycle cap, guardrails | 8 / 8 | scripted + real MAP/CPF | T-55 |
| services/orchestrator/tests/test_vbe_s6.py | S6 VBE trials (both arms, k trials judged) | 4 / 4 | in-test `ScriptedEngine` | T-31 |
| services/orchestrator/tests/test_build_round_activity.py | `build_round_snapshot` from local CPF + MAP | 12 / 12 | none | none |
| services/orchestrator/tests/test_run_round_activity.py | `run_round` from a manifest; run→evaluate chain | 9 / 9 | golden output (monkeypatched) | none |
| services/orchestrator/tests/test_evaluate_round_activity.py | `evaluate_round` PK reduction and tier gate | 6 / 6 | golden output | none |
| services/orchestrator/tests/test_diagnose_round_activity.py | `diagnose_round` → permitted actions via ruleset | 6 / 6 | golden output | none |
| services/orchestrator/tests/test_choose_action.py | strategist delegation within the permitted set | 4 / 4 | none | none |
| services/orchestrator/tests/test_fitting_activities.py | `plan_jobs` / `assess_round` | 7 / 7 | none (fabricated pi_result.json) | T-14 |
| services/orchestrator/tests/test_fix_and_refit.py | MS-01 fix_and_refit in round activities | 5 / 5 | none | T-14 |
| services/orchestrator/tests/test_fit_error_type.py | PI spec error type | 2 / 2 | none | T-13 |
| services/orchestrator/tests/test_fittable_candidates.py | fit candidate filtering | 1 / 1 | none | none |
| services/orchestrator/tests/test_metabolite_diagnosis.py | per-analyte diagnosis (SM) | 5 / 5 | golden output | T-14 |
| services/orchestrator/tests/test_round_system.py | a fit moving another compound in a model system | 7 / 7 | golden output | T-14 |
| services/orchestrator/tests/test_history.py | parameter diffs and influence map | 3 / 3 | none | T-54 |
| services/orchestrator/tests/test_memo.py | memoised engine runs, never for S7 | 2 / 2 | none | T-51 |
| services/orchestrator/tests/test_engine_identity.py | campaign records which engine ran (stub / analytical / PK-Sim labels) | 4 / 8 | stub_engine.py / analytical_engine.py identity only | T-28 |
| services/orchestrator/tests/test_campaign_store.py | Postgres resume and round rows | 2 / 2 | testcontainers Postgres (skipped here) | none |
| services/engine-worker/tests/test_runner.py | EngineRunner: integrity check, timeout kill, warnings | 4 / 4 | fake Python engine subprocess | none |
| services/engine-worker/tests/test_objectstore.py | presigned S3/MinIO I/O | 5 / 5 | testcontainers MinIO (skipped here) | none |
| services/engine-worker/tests/test_registration.py | engine_images registration gate | 6 / 6 | golden catalog | T-12 |
| packages/run-contracts/tests/test_runtime_defaults.py | MODELER_* defaults, production refusal | 7 / 15 | stub/analytical identity only | T-25 |
| packages/run-contracts/tests/test_contracts.py | dataclass round trip | 1 / 1 | none | none |
| packages/storage/tests/test_phase8_concurrency.py | job leases, file locks across processes | 11 / 11 | none | T-25 |
| packages/storage/tests/test_postgres_deploy.py | append-only Part 11 roles on real PG16 | 4 / 4 | PG16 binaries (skipped: root) | T-05 |
| services/agents/tests/test_strategist.py | strategist choice and fallback, LLM decider parsing | 13 / 13 | none | none |

### 2b. pbpk-domain (in-scope modules)

| Test file | Covers | # tests | Engine | req tags |
|---|---|---|---|---|
| test_acceptance.py | acceptance criteria (locked module) | 6 | none | **none** |
| test_diagnostics.py | diagnostics ruleset (locked) | 34 / 55 | none | D7, T-14 |
| test_evaluate_round.py | gate evaluation | 10 | golden output | D6, T-14, T-18 |
| test_round_build.py | stage snapshot build | 19 | golden output | T-10 |
| test_fit_spec.py / test_fit_spec_system.py | PI spec | 15 / 4 | none / golden | T-13 / T-14 |
| test_fitting.py | multistart plan and assessment | 5 | none | **none** |
| test_identifiability.py | identifiability | 7 / 9 | none | T-14 |
| test_nca.py | NCA | 9 | golden output | **none** |
| test_metrics_and_statistics.py | metrics | 9 | none | F-401 |
| test_vbe.py / test_vbe_report.py | VBE | 5 / 3 | golden / none | T-31 |
| test_model_system.py | model system | 15 / 18 | golden | T-03 |
| test_metabolite_stage.py | SM stage | 7 | golden | T-13 |
| test_reproducibility.py | bundle and reproduction (locked) | 13 | none | T-23 |
| test_mar.py / test_campaign_mar_history.py | MAR assembly | 11 / 1 | none | F-401, T-24 / T-54 |
| test_validation_pack.py | URS/RTM/OQ pack | 8 | none | T-32 |
| test_snapshot.py | snapshot models (1 skipped: needs `PBPK_REFERENCE_SNAPSHOT`) | 9 | none | **none** |
| test_cpf.py | CPF schema (locked) | 24 | none | **none** |
| test_split.py | data split (locked) | 23 | none | **none** |
| test_map.py / test_map_applications.py | MAP (locked) | 21 / 22, 4 | none | T-16, T-50 / T-31 |
| test_pksim_paths.py, test_units.py, test_builder_processes.py, test_catalog.py, test_engine_catalog.py, … | builder and harvested names | — | golden catalog | mixed; several untagged |

All 42 pbpk-domain test files: 730 items, 729 passed, 1 skipped.

### 2c. API (in-scope routers) and architecture

| Test file | Covers | # | Engine | req |
|---|---|---|---|---|
| services/api/tests/test_campaign_api.py | start (local), 503s, 403 | 5 | runner overridden | **none** |
| services/api/tests/test_escalations.py | Temporal-path `escalation:decide` and `/deviations` with fake verifier and signaler (password body) | 6 | none | **none** |
| services/api/tests/test_escalation_resolve.py | local `escalation:resolve`: step-up, stale step-up, 403, 404/422, already decided, test-data refusal, feedback binding | 11 | in-test stub via orchestrator | T-17, T-46, T-55 |
| services/api/tests/test_run_integrity.py | signed MAP, signed limits, CPF = MAP (pilot) | 8 | none | F-402, F-404, T-06, T-16 |
| services/api/tests/test_t56_kit.py | the T-56 kit: proposal → traced campaign, "Not a PBPK result" label | 2 | **stub_engine.py subprocess** | T-56 |
| services/api/tests/test_model_system_campaign.py | Verapamil system planned, built, judged per analyte | 4 | none (no engine run) | T-13 |
| services/api/tests/test_read_api.py | monitor, inbox, package reads, membership | 24 | none | T-06 |
| services/api/tests/test_results_api.py / test_results_ingestion.py | results reads and ingestion | 5 / 4 | golden output | T-08 |
| services/api/tests/test_compliance.py | audit chain and signatures | 6 | none | F-403, F-404, T-05 |
| services/api/tests/test_part11_postgres.py | Part 11 on PG16 (6 skipped here) | 6 | PG16 binaries | T-05, T-06 |
| services/api/tests/test_persistence.py | repositories (5 skipped here) | 5 | testcontainers | **none** |
| services/api/tests/test_admin_system.py, test_production_start.py | engine check, production refusals | 2, 6 | stub_engine.py | T-05, T-06, T-25 |
| tests/architecture/* (12 files) | §4 below | 45 defs / 183 items | none | T-25 (all) |

### 2d. Web (Playwright, `apps/web/e2e`, in-scope specs)

| Spec | Covers | tests | Engine |
|---|---|---|---|
| campaign-monitor.spec.ts | campaign from the project page to the monitor; unrecorded campaign; illustrative run shown "test only" | 3 | stub_engine.py (playwright.config.ts:21) |
| campaign-tabs.spec.ts | campaign page tabs | 2 | stub / seeded |
| escalation-popup.spec.ts | escalation flash bar, decision, step-up dialog | 3 | seeded read root |
| feedback.spec.ts | S5 feedback decision | 3 | seeded ("software test data, no engine run") |
| vbe.spec.ts | S6 VBE on the monitor | 2 | seeded |
| review-sign.spec.ts / review-tabs.spec.ts | Review & sign | 5 / 1 | seeded |
| records.spec.ts, published-model.spec.ts, model-system.spec.ts, acceptance.spec.ts | records, published model, system panel, every-page acceptance | 1, 1, 1, 3 | stub / seeded |
| oidc-signing.spec.ts | Keycloak sign-in and step-up signing | 8 | **not run in CI**: `testIgnore` unless `E2E_OIDC_ISSUER` is set (playwright.config.ts:31) |

The web app has no unit-test runner; it is checked by `typecheck`, `build` and these e2e flows.

### 2e. Behaviours covered only by stubs or fakes (VERIFIED by reading the tests)

Each of the following is exercised only by in-test stubs, the scripted executor, mocked Temporal activities, or
`stub_engine.py`. None runs on real PK-Sim in automated CI:
- the S1–S3 round loop with a fit applied and re-simulated;
- VPC gating;
- SJ joint refinement;
- the no-regression gate;
- the S6 sensitivity and uncertainty jobs;
- the S6 VBE trials;
- S7 reproduction, the `.pksim5` conversion and the package release;
- S5 feedback cycles;
- memoisation;
- escalation resolve;
- the Temporal state machine.

The evidence that these run on PK-Sim is the manual reference workflow and the server runs that
`docs/CONTINUATION_PACKAGE.md §4.1` records ("Done — PK-Sim"). I could not verify those here.

---

## 3. Test run results (VERIFIED)

Environment: Linux container, Python **3.13.18**. uv chose it because there is no `.python-version`. CI's
`PYTHON_VERSION: "3.12"` (`ci.yml:28`) is never used by any step. No Docker, no Rscript, running as root.

| Step | Command | Result | Wall time |
|---|---|---|---|
| sync | `uv sync --all-packages` | ok | 8.0 s |
| lint (scope) | `uv run ruff check services/orchestrator services/engine-worker packages/run-contracts packages/pbpk-domain` | All checks passed | <2 s |
| lint (repo) | `uv run ruff check .` | All checks passed | <2 s |
| A | `uv run pytest -q -p no:cacheprovider services/orchestrator/tests services/engine-worker/tests packages/run-contracts/tests` | **149 passed, 14 failed, 7 skipped** (170 items) | 25.7 s |
| B | `… packages/pbpk-domain/tests packages/storage/tests tests/architecture` | **923 passed, 5 skipped**, 1 warning (928 items) | 35.5 s |
| C | `… services/api/tests services/agents/tests/test_strategist.py` | **431 passed, 11 skipped** (442 items) | 170.7 s |

**In-scope totals:** 1,205 items = A (170) + B (928) + in-scope API files (94) + strategist (13). Results:
- **1,168 passed:** 149 + 923 + 83 + 13.
- **14 failed.**
- **23 skipped:** 7 + 5 + 11.

The out-of-scope API tests in run C: 335 passed, none failed.

**Failures (14, all `test_campaign_workflows.py`):**
- Every one raises `RuntimeError: Failed starting test server: error sending request for url
  (https://temporal.download/temporal-test-server/default?arch=amd64&platform=linux&sdk-name=sdk-python&sdk-version=1.32.0)`
  from `WorkflowEnvironment.start_time_skipping()` (`test_campaign_workflows.py:113`).
- I confirmed the host is blocked by the sandbox proxy (`curl` exit 56, `CONNECT tunnel failed, response 403`).
- The 14 tests are: stage_passes_on_first_round, stage_escalates_when_rounds_exhausted, stage_deadline_exhausted_before_any_round,
  stage_escalation_abort, stage_escalation_accept_best, stage_escalation_retry_then_pass, campaign_happy_path_s0_to_s2,
  campaign_rejected_when_map_not_signed, campaign_escalates_when_s0_not_ready, campaign_escalates_when_a_stage_escalates,
  campaign_resume_skips_completed_stage, campaign_skips_a_stage_with_nothing_to_simulate_and_continues,
  validation_stage_judges_once_and_never_diagnoses, a_fit_is_judged_on_the_fitted_model_in_its_own_round.
- I could not observe whether they pass when the binary is reachable. INFERRED: they pass on GitHub runners, as the
  continuation doc implies at line 18.

**Skips (23):**
- 2 × `test_campaign_store.py` and 5 × `test_objectstore.py`: testcontainers, no Docker socket.
- 4 × `test_postgres_deploy.py` and 6 × `test_part11_postgres.py`: "needs PostgreSQL 16 binaries and an ordinary
  account" (root here).
- 5 × `test_persistence.py`: no Docker.
- 1 × `test_snapshot.py:146`: `PBPK_REFERENCE_SNAPSHOT` unset.

**Warning:** a `PytestUnhandledThreadExceptionWarning` ("agent failed") is reported against
`test_a_job_held_by_another_process_is_running_here_and_cannot_be_claimed`. The exception was actually raised by the
previous test's background thread (`test_a_failing_background_job_still_releases_its_lease`,
`test_phase8_concurrency.py:91-102`). That test filters the warning, but its thread outlives it, so a thread leaks
between tests.

Slowest tests:
- `test_local_runner.py::test_campaign_runs_s0_to_s7_…` 9.2 s;
- `test_t56_kit.py::…traced_campaign` 19.1 s;
- `tests/architecture/test_openapi_contract.py` 4.6 s.

---

## 4. Guardrails and locked files in scope

### 4a. Architecture tests (`tests/architecture/`, all tagged T-25, VERIFIED all pass)

- `test_import_boundaries.py`: the layer order from `boundaries.toml [layers]`, declared dependencies, the seams
  (`modeler_orchestrator` only via `modeler_api.execution`, agents via `modeler_api.agent_jobs`), no router-to-router
  imports, tests obey layers, and stale exceptions fail. `boundaries.toml` now records **zero exceptions** (comment
  block, lines 28-38).
- `test_config_reads.py`: only `[config] readers` read `os.environ`. In scope: `modeler_contracts.runtime`,
  `modeler_engine.runner`, `modeler_api.config`.
- `test_response_models.py`: every router typed; `[response] untyped = []`, `open = []`.
- `test_artifact_owners.py`: one writer per artifact kind; `campaign = ""` (campaigns live in the runner's store).
- `test_process_state.py`: no module-level sets, locks or empty collections, except `modeler_project/audit.py:_LOCK`.
  It does **not** detect daemon threads or module globals assigned `None` (e.g. `campaign_activities._store`, `:72-73`).
- `test_openapi_contract.py`: `app.openapi()` must equal `docs/api/openapi.json`.
- `test_parameter_vocabulary.py`, `test_parameter_characterization.py`, `test_parameter_registry.py`: the parameter
  vocabulary snapshot (`docs/architecture/parameter-vocabulary.json`). Known drift is `xfail(strict=True)`
  (`ehc_fraction`).
- `test_engine_identity.py`: `QUALIFIED_ENGINE_ID` equals the catalog's id, the object-store default is shared, the
  server is a pilot until Keycloak is configured, and the server records the catalog digest.
- `test_locked_files.py`: SHA-256 of every file matched by a locked pattern; fails on edit, addition or removal.
- `test_web_client.py`: only `lib/api.ts` fetches; pages read through the hooks.

### 4b. Locked files that touch the post-MAP scope (`docs/architecture/locked-files.json`: 32 patterns, 76 files)

- **pbpk_domain core:**
  - `acceptance.py`, `campaign/map.py`, `campaign/split.py`, `diagnostics.py`, `m15.py`, `reproducibility.py`;
  - `cpf/models.py`, `cpf/build.py`, `snapshot/builder.py`, `reference/osp_import.py`, `pksim_paths.py`,
    `parameter_units.py`.
- **SME:**
  - `rulesets/*.yaml`: ddi_static_screening, diag_rules, dissolution_similarity, pbpk_acceptance_criteria;
  - `analysis_templates/*.yaml`: ddi-cyp3a4-victim, vbe-crossover;
  - `parameters/registry.yaml`;
  - `requirements/*.yaml` (6);
  - `docs/PBPK_MODELING_WORKFLOW.md` (MS-01).
- **Engine:** `services/engine-worker/r/*.R` (benchmark, harvest_catalog, run_job, run_pi), `golden/**` (36 files incl.
  16 OSP model fixtures, `catalog.json`, the golden R scripts, `compare_weibull.py`), `Dockerfile`,
  `.github/workflows/engine-image.yml`.
- **Records and signatures:** `modeler_storage/audit.py`, `modeler_api/compliance/signatures.py`,
  `modeler_api/auth.py`, `services/api/migrations/*.sql` (4).
- **Repo:** `ci.yml`, `conftest.py`, `tests/architecture/boundaries.toml`, `docs/validation/requirements.yaml`,
  `CLAUDE.md`.

**Not locked, though in scope and behaviour-critical (VERIFIED against the pattern list):**
- **Orchestrator:** all of `services/orchestrator/**` (`local_runner.py`, `campaign.py`, `campaign_activities.py`,
  `fitting_activities.py`, `package_activities.py`, `feedback.py`, `joint.py`, `memo.py`, `vbe_activities.py`).
- **pbpk_domain science:**
  - `campaign/evaluate.py`: the gate verdict itself;
  - `campaign/round_build.py`, `campaign/prediction.py`, `campaign/vpc.py`;
  - `fitting.py`, `fit_spec.py`, `identifiability.py`, `nca.py`, `metrics.py`, `vbe.py`, `system.py`;
  - `report/*`, `snapshot/models.py`, `snapshot/validation.py`.
- **Engine worker and contracts:**
  - `engine-worker/src/**` (`runner.py`, `worker.py`, `registration.py`);
  - `run-contracts` (`runs.py`; `runtime.py`, including the fixture-vs-PK-Sim classification `FIXTURE_ENGINES`,
    `PKSIM_ENGINES`, `:61-62`).
- **Storage:** `part11.py`, `jobs.py`, `filestore.py`, `records.py`, `db/*`.
- **API:** `escalations.py`, `campaign_api.py`, `run_guard.py`, `part11.py`, `signatures_api.py`.
- **CI and fixtures:** `.github/workflows/reference-models.yml`, `deploy/dev/stub_engine.py`,
  `deploy/dev/analytical_engine.py`.
- **The guard itself:** `docs/architecture/locked-files.json` and `tests/architecture/test_locked_files.py`. A PR can
  edit a locked file and rerun `UPDATE_LOCKED=1` in the same diff, and the test goes green. There is no `CODEOWNERS`.
  Branch protection is not visible from the repository.

---

## 5. CI workflows

| Workflow | Trigger | Jobs | Gates |
|---|---|---|---|
| `ci.yml` (locked) | push `main`, tags `v*`, PR → `main`, manual. Concurrency cancels the older run per ref | **lint** (`uv sync --frozen`, `ruff check .`); **test** (`pytest -q --trace-matrix reports/trace-matrix.md --junit-xml`, then the validation pack with `if: always()`, uploaded as artifact `validation-evidence`); **web** (`npm ci`, `typecheck` incl. the openapi-typescript drift check, `build`); **e2e** (Playwright, stub engine, 30 min); **api-image** (docker build, imports, `/health`); **secret-scan** (gitleaks 8.21.2, full history, `--exit-code 1`); **trivy** (fs scan vuln, secret and misconfig HIGH/CRITICAL, **`--exit-code 0` report-only**, SARIF upload `continue-on-error`); **release-evidence** (tags `v*` only, `needs` all, attaches the evidence tarball) | Failing lint, test, web, e2e, api-image or gitleaks marks the run red. Trivy and validation-pack gaps never fail. Only `release-evidence` uses `needs`. Which checks block a merge depends on GitHub branch protection, which is not in the repo (open question). |
| `engine-image.yml` (locked) | push `main` / tags `engine-*`, and PR, **path-filtered** to `services/engine-worker/**`, `packages/run-contracts/**` and the workflow file; manual | **build-qualify**: build amd64 → golden scripts inside the image (round trip, `pi_smoke`, `pi_relative_group`, `golden_tasks`, `benchmark.R` 400, Weibull curve from the Dapagliflozin IC tablet) → `compare_weibull.py` (≤1 %, exits 1 on miss) → on non-PR: GHCR push by digest, Syft SBOM, cosign keyless sign, `engine_images` registration record (artifact only) → upload evidence | Real PK-Sim gate: a failing golden script stops the job before push. **Benchmark is recorded, not gated** (no 1-hour threshold, `registration.py:19 REQUIRED_GOLDEN` has no benchmark). The uploaded evidence omits `artifacts/pi_relative_group/**` and `artifacts/weibull/**`. Changes to `packages/pbpk-domain/**` do not trigger it, although the Weibull comparison runs pbpk-domain code. |
| `reference-models.yml` (**not locked**) | **`workflow_dispatch` only**, optional `tasks` CSV | Matrix of 31 tasks (evaluate / roundtrip / as-is / refit / system / VBE / portfolio), each: build the engine image (GHA cache), golden round trip, `uv sync --all-packages` (**not `--frozen`**, `setup-uv@v6` unpinned), `deploy/reference/run_reference.py …`, upload JSON | Not a merge gate. 240-minute timeout, `fail-fast: false`. Campaigns stop at the S6 signature gate. |

Other CI notes (VERIFIED):
- **Secret scanning:** gitleaks with `.gitleaks.toml` (default rules plus an allowlist for dotted CPF ids). Trivy also
  runs a secret scanner, but report-only. gitleaks is fetched with `curl | tar` and no checksum check (`ci.yml:166-170`).
- **Supply chain:** Trivy is pinned by version and digest. `anchore/sbom-action@v0`, `sigstore/cosign-installer@v3`,
  `softprops/action-gh-release@v2`, `astral-sh/setup-uv@v5/@v6` and `actions/*@v4` are pinned to mutable tags.
- **Trace matrix:** `conftest.py` builds it from `@pytest.mark.req`. The marker is registered, but `--strict-markers`
  is not set (`pyproject.toml addopts = "--import-mode=importlib"`), so a mistyped marker name only warns.
- **Validation pack:** maps `docs/validation/requirements.yaml` (44 ids) to traced tests plus the JUnit OQ summary.
  Statically, every one of the 44 ids has at least one tagged test file. T-22 and T-30 are tagged in tests but absent
  from the YAML. Of the 1,205 in-scope items, 410 are untagged:
  - orchestrator 82 of 139;
  - pbpk-domain 259 of 730;
  - API in-scope 41 of 94;
  - engine-worker 14 of 15;
  - strategist 13 of 13.

  29 in-scope files have no tag at all (§8 D8).

---

## 6. LocalExecutor vs Temporal feature parity (VERIFIED by reading the code unless marked)

Both paths call the same activity functions: `plan_campaign`, `plan_stage`, `build_round_snapshot`,
`prepare_round_job`, `collect_pkml_inputs`, `run_round`, `evaluate_round`, `diagnose_round`, `choose_action`,
`prepare_vpc_jobs`, `evaluate_vpc` (`campaign_activities.py:1092-1106`), plus `plan_jobs` and `assess_round`. The loop
control is written twice:
- `local_runner.py:614-677` and `:996-1048`;
- `campaign.py:85-161` and `:227-289`.

| Feature | LocalExecutor (`local_runner.py`) | Temporal (`campaign.py`, `fitting.py`, `workflows.py`) |
|---|---|---|
| Deployed | **Yes.** `execution_backend = "local"` default (`config.py:21`); `execution.py:16-19` | Built, "not deployed" (`CONTINUATION_PACKAGE.md:707`) |
| Start | API `start_campaign` → `runner.start` → daemon thread (`:1153-1169`) | API `client.start_workflow("ModelingCampaignWorkflow", …)` (`campaign_api.py:64-73`); question, project and model_risk are dropped |
| S0 readiness | `:453-472` | `:332-341` |
| MAP signature | checked before start by `run_guard.require_signed_map` (pilot/production only) | waits in the workflow for a `map_signed` signal (`:342-349`). **No API code sends it** (grep): the campaign ends REJECTED after `signature_timeout_days` (default 14) |
| Stage budget / rounds | request → signed MAP `stage_plan` → 1800 s; rounds from the MAP or the request; source noted (`:593-612`) | request or 1800 s (`:64-66`); `max_rounds` from the request only. The signed MAP is ignored |
| Fit judged in its own round | yes (`:1011-1023`) | yes (`:251-262`) |
| Parallel fit starts | ThreadPool sized by `fit_workers` (`:1050-1069`) | `FitRoundWorkflow`, `asyncio.wait` with deadline (`fitting.py:50-61`) |
| Fit deadline cancellation | **no**: `deadline_reached=False` (`:1058`); relies on each job's `timeout_s` | yes: pending starts cancelled, `CANCELLED_AT_DEADLINE` |
| One fit start fails | `pool.map` re-raises → stage FAILED (INFERRED, `:1069`, `runner.py:136-137`) | tolerated: manifest None → start FAILED (`fitting.py:56-61`) |
| `BudgetTooSmallError` | escalates with the best CPF so far (`:640-646`) | not caught (INFERRED: activity error → `ACT_RETRY` × 3 → workflow failure) |
| VPC gate | yes (`:1028-1037`) | yes (`:184-207`) |
| S4/S5 validation | `_run_validation` (`:679-708`); options accept_best / abort | `_validate` (`:163-182`); any decision other than accept_best → ABORTED |
| SM metabolites | via `plan_stage` and `TRAINING_STAGES` | via `plan_stage` (INFERRED, runs as a StageLoop) |
| **SJ joint refinement** | `_run_joint` (`:878-942`) | **SKIPPED** with a finding (`:356-363`) |
| **No-regression gate** after a fit stage | `_no_regression` (`:834-858`) plus the joint remedy (`:532-547`) | **absent** |
| **S6 signature gate** (S4/S5 signed before S6) | AWAITING_SIGNATURE (`:476-487`) | **absent** (S6 skipped) |
| **S6 prediction / sensitivity / uncertainty / VBE** | `_run_prediction`, `_run_vbe` (`:732-781`) | **SKIPPED** |
| **S7 package, reproduction, .pksim5** | `_run_package` (`:783-832`) | **SKIPPED** |
| Escalation | stop the campaign; `escalations.json`; resume via `POST …/escalation:resolve` with an OIDC step-up signature (`escalations.py:216-284`) | block in the workflow on the `escalation_decided` signal (`:291-304`). `POST …/escalation:decide` takes `password` and `second_factor` in the body (`escalations.py:100-118`); its `get_verifier` always raises 503 (`:83-84`) and nothing overrides it |
| Retry semantics | re-runs the whole stage fresh (full `max_rounds`, `:1290-1317`) | continues the same loop and consumes a round (`:148-151`) |
| **S5 feedback cycles** (learn / new evidence / limitation) | `_diagnose_s5`, `_start_cycle` (`:944-975`, `:1321-1361`) | **absent**; `cycle` never set in `RoundContext` |
| Final CPF acceptance | not enforced: "collected after" (`:584`) | waits for an `accept_final_cpf` signal (`:397-404`); **no sender** |
| Progress and monitor | `campaigns.json` and `escalations.json` through `FileWriteStore`; per-stage evidence files | Postgres rounds via `CampaignStore` when `MODELER_DATABASE_URL` is set, else a log line (`campaign_activities.py:1076-1089`). **No `campaigns.json`**, so the monitor (`read_api.py:128-160`, FileReadStore) shows nothing |
| Resume after crash | **none**: daemon thread, no lease | Temporal replay; DB resume **reverts to the starting CPF** (`campaign_store.py:47-53`) |
| Memoisation, model sets, ledger, influence map, engine identity | yes | no |
| Retries | none (exception → FAILED stage) | `ACT_RETRY` (3); `ENGINE_RETRY` (2, non-retryable `InputIntegrityError` / `EngineError` / `EngineTimeout`, matching `modeler_engine/worker.py:43-48`) |
| Tests | 27 + 7 + 8 + 4 (stub / scripted) | 14 (mocked activities; fail here) |

Conclusion: the paths share the science activities, but the Temporal path is roughly the S0–S5 subset of an earlier
design. It is not reachable end to end through the API, and its tests exercise signals that production code never
sends.

---

## 7. Quality findings

### 7a. Size hotspots (VERIFIED, `wc -l` and an `ast` scan of functions of 90+ lines)
- **Files:**
  - `reference/osp_import.py` 2,084 (locked);
  - `orchestrator/local_runner.py` 1,411;
  - `snapshot/builder.py` 1,302 (locked);
  - `orchestrator/campaign_activities.py` 1,106;
  - `cpf/build.py` 750;
  - `campaign/map.py` 696;
  - `campaign/split.py` 540;
  - `campaign/round_build.py` 410;
  - `report/mar.py` 439;
  - `report/campaign_mar.py` 420;
  - `package_activities.py` 428;
  - `campaign.py` 431.
- **Functions:**
  - `osp_import._study` 253 lines;
  - `campaign_mar.assemble_campaign_mar` 183;
  - **`LocalExecutor.run` 154** (`local_runner.py:438`);
  - `osp_import.import_osp_system` 133;
  - `cpf/build._compound_from_cpf` 120;
  - `campaign_activities._build_fit_request` 114;
  - `diagnose_round` 112;
  - `resolve_escalation` 99;
  - `evaluate_round` 97;
  - `vbe_activities.run_vbe` 93.
- `local_runner.py` holds the executor, the monitor writer (`CampaignArtifactWriter`), engine selection, escalation
  resolution, the feedback-cycle start and a CLI.
- Test hotspot: `test_local_runner.py` 792 lines.

### 7b. Duplication
- **Two round loops:** about 200 lines each (§6), already diverging in budget source, retry semantics, deadline
  handling and error tolerance.
- **Eleven file:// → Path helpers** with different failure behaviour:
  - `local_runner._local_text/_local_json` (return None on a JSON error);
  - `campaign_activities._local_path/_load_local_text/_load_local_json` (`_load_local_json` raises on a JSON error,
    `:105-110`);
  - `_path` in `vbe_activities.py:52`, `memo.py:38`, `joint.py:32`, `package_activities.py:31`, `feedback.py:38`;
  - `package_activities._read_json`;
  - `engine-worker runner._local_path` (`:72`);
  - `api run_guard._file_bytes` (`:38`).
- **The MAP is re-parsed per round:** `_model_set` (`:983-986`), `_influence` (`:977-981`), `_limits` (cached per
  executor), `_campaign_writer` (twice, `:1122-1132`), `_planned_stages`.

### 7c. Error handling (VERIFIED)
- **Narrow catch in `LocalExecutor.run`:** the stage `try/except Exception` wraps only the dispatch
  (`local_runner.py:513-530`). Outside it, and therefore able to kill the daemon thread and leave the campaign RUNNING:
  - `plan_campaign` (`:454`) and `plan_stage` (`:488`);
  - `_no_regression` and the regression joint fit (`:534-547`);
  - `_influence` (`:553`);
  - `writer.flush`.

  The comment at `:525-526` states exactly this risk.
- **Silent swallows:**
  - `_persist` catches `OSError` and passes (`:727-730`; "S7 will say so");
  - `.pksim5` conversion failures become package notes (`:807-810`);
  - S5 sensitivity failures become notes (`:963-967`);
  - VBE engine failures are reported (`vbe_activities.py:134`).
- **Background jobs:** `modeler_storage.jobs.run_in_background` releases its lease in `finally`, but the exception
  reaches only `threading.excepthook`. Nothing logs it (`jobs.py:119-153`).
- **Engine errors:** typed (`InputIntegrityError`, `EngineFailedError`, `EngineTimeoutError`) and mapped to
  non-retryable Temporal `ApplicationError` types correctly (`worker.py:43-48`). Locally they become a FAILED stage
  with `type: message` findings.
- **Unfinished storage paths:** `fitting_activities._read_result` raises
  `NotImplementedError("reading results from object storage is provided by the storage adapter")` for non-file URIs
  (`:61`). The Temporal engine worker uses `LocalObjectStore`, with the comment "replace with the S3 store in deployed
  profiles" (`worker.py:30`). S3 is therefore unusable for parameter identification.

### 7d. Observability (VERIFIED by grep)
- `services/orchestrator`, `services/engine-worker`, `packages/run-contracts`, `packages/storage` and
  `packages/pbpk-domain` have **no `import logging` or `getLogger`**. The only log calls are 20
  `activity.logger.info/warning` calls in `campaign_activities.py` and `activities.py`. On the LocalExecutor path, which
  is the deployed one, these go to temporalio's logger. Nothing configures handlers (no `basicConfig` or `dictConfig`
  anywhere in scope), so INFO messages are dropped (INFERRED from Python's logging defaults).
- No metrics, tracing or error reporting: 0 hits for opentelemetry, prometheus, statsd, sentry or tracer. The
  architecture decision D9 plans kube-prometheus-stack, Loki and Tempo (`CONTINUATION_PACKAGE.md:61`); none is wired.
- Diagnostics live in the data instead: engine `stderr_tail` (last 4,000 characters) and warnings in each manifest
  (`runner.py:229-233`), stage notes and findings in `campaigns.json`, the Temporal path's `record_round` rows.
- `ingest_results` is a stub that only logs: "Phase 0 target: convert result CSVs to Parquet…" (`activities.py:24-30`).

### 7e. TODO and placeholder markers in scope
- `campaign.py:356-363`: "S6 prediction and S7 package … their Temporal wiring … is not built yet".
- `activities.py:27`: "Phase 0 target …".
- `fitting_activities.py:61`: `NotImplementedError` for object storage.
- `worker.py:30`: "replace with the S3 store in deployed profiles".
- `campaign_activities.py:1058-1062`: the LLM strategist "lands when per-tenant agents and that table are wired". Only
  the deterministic first-permitted-action path runs.
- There are no literal TODO, FIXME or XXX markers in scope.

### 7f. Configuration (VERIFIED)
- **Orchestrator and engine:** `modeler_contracts.runtime.VARIABLES` lists 19 MODELER_* variables, read on every call
  (`runtime.py:30-50`):
  - READ_ROOT, OBJECT_STORE_URI, ENGINE_COMMAND, ENGINE_ID, IMAGE_DIGEST;
  - ENGINE_CORES, ENGINE_CONCURRENCY, RESOURCE_CLASS, FIT_WORKERS, MEMO;
  - TEMPORAL_ADDRESS, TEMPORAL_NAMESPACE, DATABASE_URL;
  - S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY, S3_BUCKET, S3_REGION;
  - DEPLOYMENT.
- **API:** reads its own `Settings(env_prefix="MODELER_")`. Six variables are read by both.
- **Default mismatch:** `MODELER_DATABASE_URL` defaults to `postgresql+asyncpg://modeler:modeler@localhost:5432/modeler`
  in the API (`config.py:18`) but to `None` in the runtime. This contradicts the "one default per variable" rule; the
  architecture test checks only the object store and the digest.
- **No validation:** values are unvalidated strings. `int(override)` in `fit_workers` (`local_runner.py:149-150`) and
  `int(runtime_env().get("fit_workers","64"))` (`:1063`) raise inside a campaign on bad input.
- **Production check gaps:** `check_production` (`runtime.py:126-139`) requires an engine command and a real digest,
  but does **not** refuse a fixture engine such as `stub_engine.py`.
- **Deployment default:** `MODELER_DEPLOYMENT` unset means `development`. In development all three run guards are
  off: signed MAP, signed limits, CPF = MAP (`run_guard.py:70,79,88`).

---

## 8. Defects and risks

### CONFIRMED (from reading or running the code)

- **D1. Temporal resume discards fitted values.**
  - `CampaignStore.resume` returns `cpf_uri=request.cpf_uri` with `cpf_sha256=campaign.final_cpf_sha256 or
    request.cpf_sha256` (`campaign_store.py:50-53`).
  - The only writer of `final_cpf_sha256` is `CampaignRepository.set_campaign_status` (`repositories.py:60-69`), and
    no non-test code calls it.
  - So a resumed campaign skips the completed stages but continues from the **starting** CPF, losing the fits.
  - `record_round` sets a stage PASSED only on a gate pass (`:75-76`), so an ACCEPTED stage is never "completed" and
    reruns.
  - `test_campaign_store.py:94-116` asserts only `last_completed_stage`.
  - Severity: high for the Temporal path, which is not deployed.
- **D2. The Temporal path cannot complete through the API.**
  - Nothing sends `map_signed` or `accept_final_cpf` (grep across `services/` and `apps/web`).
  - `escalation:decide` depends on `get_verifier`, which always raises 503 (`escalations.py:83-84`), and nothing
    overrides it.
  - The Temporal path writes no monitor record, and SJ, S6 and S7 are skipped.
  - The Temporal tests send the signals directly (`test_campaign_workflows.py:235-308`), so they pass while the
    integration is broken.
- **D3. Temporal-path signing takes a password in the request body.**
  - `SignedDecisionRequest.password` and `DeviationRequest.password` (`escalations.py:100-118`) contradict CLAUDE.md
    ("never a password in a request").
  - Both handlers identify the tenant by an `x_tenant_id` header and take the signer from the body, with no
    `CurrentPrincipal` or `require_project` (`:140-180`).
  - Unreachable today because of the 503, but the routes are in the OpenAPI contract. Already known as R-S06
    (`CONTINUATION_PACKAGE.md:256`).
- **D4. Local campaigns are not durable.**
  - Campaigns run on daemon threads (`local_runner.py:1166-1168`, `:1314`) with no `FileJobRegistry` lease, unlike
    agent jobs.
  - `main.py:_lifespan` picks up only Data room runs (`:55`).
  - An API restart or deploy, or any exception outside the stage `try` (§7c), leaves `campaigns.json` at
    RUNNING/QUEUED forever with no escalation.
  - Severity: high for the "finish within an hour on our servers" goal and for audit completeness.
- **D5. "Accept the best" accepts the latest.**
  - Both loops overwrite `best_*` with the current round's CPF every round (`local_runner.py:650`, `campaign.py:124`).
  - The offered option is labelled "Accept the best round" (`local_runner.py:94`) or "Accept the best CPF found so far"
    (`escalations.py:43`).
  - No metric-based selection exists. Whether "latest" is intended is an SME and owner question, but the label does
    not match the behaviour.
- **D6. Limits differ between paths.** The Temporal stages ignore the signed MAP's `stage_plan` budget and rounds
  (`campaign.py:64-66`, `:366-373`). `run_guard`'s premise is that "the signed MAP also fixes each stage's time".
- **D7. Input hashes are not bound at start.**
  - `campaign_api.start_campaign` builds the `CampaignRequest` without `map_sha256` or `observed_sha256`
    (`campaign_api.py:55-61`). `CampaignStartRequest` has no such fields.
  - `cpf_sha256` is client-supplied, checked only for format, and never recomputed: no hashing in `campaign_api.py`,
    and none of the orchestrator's input reads verify hashes.
  - The engine runner verifies only the snapshot hashes the orchestrator computed itself (`runner.py:110-117`).
  - The run record can therefore carry a CPF hash that does not match the file used, and the MAP can be re-read from a
    mutable path mid-campaign.
- **D8. Trace-matrix gaps.** 29 in-scope test files have no `req` tag, so their tests never reach the RTM or the
  validation pack:
  - `test_acceptance.py` (locked acceptance), `test_cpf.py`, `test_split.py`, `test_fitting.py`, `test_nca.py`,
    `test_snapshot.py`;
  - `test_campaign_workflows.py`, `test_build_round_activity.py`, `test_evaluate_round_activity.py`,
    `test_diagnose_round_activity.py`, `test_run_round_activity.py`, `test_choose_action.py`;
  - `test_campaign_api.py`, `test_escalations.py`, `test_persistence.py`, `test_strategist.py`, `test_runner.py`,
    `test_objectstore.py`.

  Only 5 of 27 local-runner tests are tagged, and the S0→S7 end-to-end test (`test_local_runner.py:503`) is not. There
  is no `--strict-markers`.
- **D9. Non-hermetic Temporal tests.** They download a binary at test time and fail, rather than skip, without network
  (14 failures here). Docker- and PostgreSQL-dependent tests skip.
- **D10. CI blind spots.**
  - No automatic real-engine run for changes in `pbpk-domain/**` or `services/orchestrator/**`. The
    `engine-image.yml` path filter covers `services/engine-worker/**` and `packages/run-contracts/**` only.
  - Reference models are manual dispatch only.
  - The engine benchmark (the one-hour goal) is not gated.
  - Trivy and validation-pack gaps never fail.
  - The engine evidence upload omits the `pi_relative_group` and Weibull outputs.
  - `PYTHON_VERSION` is unused and the interpreter is unpinned; this audit ran on 3.13 while the project targets 3.12.
- **D11. Model sets cannot tell builder versions apart.** `model_set` records `builder_version =
  version("pbpk-domain")` (`memo.py:111-114`), which is "0.1.0" for every package (all pyprojects) and never changes
  with the builder.
- **D12. Documentation drift.**
  - `CONTINUATION_PACKAGE.md:18` says "758 Python tests"; 3,647 are collected.
  - The `local_runner.py` docstring says "S0 readiness → S1…S5" and "`modeler_engine.runner.EngineRunner`"; the code
    now runs S6/S7 and reaches the engine through `modeler_contracts.ports.engine_factory`.

### POTENTIAL (needs confirmation or an owner decision)

- **P1.** In the local path, one failed parameter-identification start may fail the whole stage (`pool.map`). This
  depends on whether `run_pi.R` exits non-zero for a non-converged or failed start.
- **P2.** `run_guard` accepts client-supplied `file://` `cpf_uri` and `map_uri` and reads them without confining them
  to the tenant's read root (`run_guard.py:38-44`, `:84-105`). `map_signed` trusts the document's own
  `"status": "SIGNED"` (`:56-57`). Possible cross-tenant or arbitrary-file reads, and a self-declared signature. Flag
  for the security slice.
- **P3.** For non-feedback decisions, including the S6 `approve`, the decision signature binds only
  `sha256("camp:stage:action")` (`escalations.py:267`). It does not bind the evaluation evidence or the CPF reviewed.
  This is a Part 11 §11.70 linkage question for QA.
- **P4.** Race between two concurrent decisions on one escalation: the pre-check (`escalations.py:243-246`) and the
  signature (`:261-270`) happen before the claim (`local_runner.py:1261`). Two concurrent requests can both record
  signatures, with one decision later refused (422). This contradicts the intent "no signature exists for a decision
  that was not applied".
- **P5.** No final CPF acceptance is enforced in the local path. The campaign reaches COMPLETED and S7 releases the
  package without a final-acceptance signature (`local_runner.py:584`).
- **P6.** Package release does not gate on the engine kind or the placeholder digest (`package_activities.py:415-419`).
  This is mitigated by the MAR's "Not a PBPK result" label (`test_t56_kit.py:75`) and the validation pack's PQ-01. A
  fixture engine command is also not refused in production (`runtime.py:126-139`).
- **P7.** One `campaigns.json` per tenant is rewritten whole on every flush under `file_lock` (`filestore.py:142-156`).
  This will contend and slow down as campaigns and rounds grow.
- **P8.** The PostgreSQL Part 11 tests skip silently wherever the binaries are missing. Nothing in CI asserts that they
  ran.
- **P9.** Unpinned third-party actions (`@v0`/`@v2`/`@v3`) and an unchecksummed gitleaks download are supply-chain risks
  in jobs that hold `packages: write` and `id-token: write`.
- **P10.** A thread leaks between tests in `test_phase8_concurrency.py` (§3 warning). Benign today, but it could make
  the tests flaky.

---

## 9. Open questions

1. Is the Temporal path still intended? If so it needs:
   - signal senders for MAP and final acceptance;
   - an OIDC-based decide endpoint with no password;
   - the resume CPF fix (D1);
   - S6 and S7 wiring and monitor writes.

   If not, removing it would take out about 900 lines of drifting duplicate control flow and the password route.
2. Which CI checks does branch protection on `main` require? Is the Temporal suite green on GitHub? The latest Actions
   runs and the `validation-evidence` JUnit would answer both, including whether `test_part11_postgres` and
   `test_postgres_deploy` ran or skipped.
3. Should "accept_best" select the best round by an agreement metric, as its label says, or the latest round?
4. Is a signed final CPF acceptance required before the S7 package is released?
5. Should `campaign/evaluate.py`, `fitting.py`, `fit_spec.py`, the NCA, metrics and VBE modules, and the engine-kind
   classification in `runtime.py` be added to the locked set, with `locked-files.json` and `test_locked_files.py`
   protected by CODEOWNERS?
6. Should a lightweight real-engine smoke test (for example the golden round trip, plus one S1 round on the example
   snapshot in the engine image) run on every PR touching `pbpk-domain/**` or `services/orchestrator/**`?
7. Does `run_pi.R` exit non-zero when an optimisation start fails? (Decides P1.)
8. Should the runner own a campaign lease and recover RUNNING campaigns at startup, mirroring
   `dataroom_runs.pick_up`?
