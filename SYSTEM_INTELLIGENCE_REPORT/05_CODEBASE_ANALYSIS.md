# 05 · Codebase analysis (post-MAP scope)

Machine-readable module list with live line counts and lock status: `MODULE_INVENTORY.csv` (97 modules, 21 locked).

## 1. Repository structure (in-scope parts)

```text
Modeler_One_AI/                      uv workspace (pyproject.toml, uv.lock), Makefile, CLAUDE.md, CHANGELOG.md
├─ packages/
│  ├─ pbpk-domain/src/pbpk_domain/   L0 science: campaign/ (map, split, round_build, evaluate, vpc, prediction),
│  │                                 cpf/, snapshot/, acceptance, metrics, nca, diagnostics, fit_spec, fitting,
│  │                                 identifiability, system, vbe, bioequivalence, data_origin, m15, reproducibility,
│  │                                 report/ (mar, campaign_mar, render, validation_pack), rulesets/*.yaml,
│  │                                 parameters/registry.yaml, analysis_templates/*.yaml, catalog, pksim_paths
│  ├─ run-contracts/src/modeler_contracts/   L1: runs.py (contracts), runtime.py (MODELER_*), ports.py (engine port)
│  ├─ storage/src/modeler_storage/   L3: filestore, records, jobs, part11, audit, objects, db/
│  └─ project-model/src/modeler_project/     L3: plan (plan → MAP), audit (file chain), members, fit_bounds.yaml
├─ services/
│  ├─ orchestrator/src/modeler_orchestrator/ L5: local_runner (deployed), campaign/fitting/workflows/worker
│  │                                 (Temporal), campaign_activities, fitting_activities, package_activities,
│  │                                 feedback, joint, memo, history, vbe_activities, round_system, campaign_store
│  ├─ engine-worker/                 L5: src/modeler_engine (runner, worker, objectstore, registration),
│  │                                 r/ (run_job.R, run_pi.R, harvest_catalog.R, benchmark.R), golden/, scripts/, Dockerfile
│  ├─ agents/src/modeler_agents/strategist.py   L4 (deterministic in the campaign)
│  └─ api/src/modeler_api/           L6: main, campaign_api, escalations, run_guard, read_api, write_api, plan_api,
│                                    signatures_api, part11, compliance/, auth, ownership, memberships, execution,
│                                    results_api, system_api, engine_check; migrations/*.sql
├─ apps/web/                         L7: app/campaigns/[campaignId], app/projects/[projectId]/{plan,campaigns,history},
│                                    components/{campaign/*, EscalationDecision, RunCampaignButton, PackageDownloads,
│                                    StepUpDialog, AutoRefresh, plan/PlanCanvas}, lib/{api,hooks,reads,writes}.ts, e2e/
├─ deploy/                           dev/ (stub_engine, analytical_engine, docker_engine.sh, deploy_to_server.sh),
│                                    server/ (run/stop/status, _env.sh, postgres.sh, keycloak.sh, qualify.*),
│                                    proof/ (T-56 kit), reference/ (OSP model runs), keycloak/ (realm)
├─ tests/architecture/               layering, contracts, vocabulary, locked-file hashes
├─ docs/                             MS-01, ENGINEERING_PLAN, CONTINUATION_PACKAGE, SME_SIGNOFF, plans/, validation/
└─ .github/workflows/                ci.yml, engine-image.yml, reference-models.yml
```

## 2. Entry points and initialisation

| Entry point | What starts | Source |
|---|---|---|
| `uvicorn modeler_api.main:app` | API; lifespan: `runtime_env().check_production()`, `check_auth`, `check_part11`, agent status log, resume paused Data room runs (not campaigns) | `services/api/src/modeler_api/main.py:44-72` |
| `deploy/server/run_modeler.sh` | Postgres (if installed), Keycloak (if issuer set), uvicorn (single process, `0.0.0.0:8000`), Next.js | `deploy/server/run_modeler.sh:33-58` |
| `POST /api/v1/projects/{id}/campaigns` | a campaign thread | `campaign_api.py:44-81` → `local_runner.start_campaign` |
| `python -m modeler_orchestrator.local_runner spec.json` | a headless campaign | `local_runner.py:1384-1411` |
| `python -m modeler_orchestrator.worker` | Temporal worker (not deployed) | `worker.py` |
| `Rscript run_job.R job.json` | one engine job | `services/engine-worker/r/run_job.R` |
| `python deploy/proof/run_t56.py …` | the end-to-end proof kit | `deploy/proof/run_t56.py` |

## 3. Execution path: from the start button to the released package

1. `PlanCanvas.tsx:373-380` posts `view.map.campaign` → `lib/api.ts` (bearer via `proxy.ts`).
2. `campaign_api.start_campaign` → `run_guard` → `CampaignRequest` → `execution.RunnerDep` →
   `campaign_runner.LocalCampaignRunner.start` → `local_runner.start_campaign` (QUEUED record, daemon thread).
3. `LocalExecutor.run` (`local_runner.py:438-591`): `plan_campaign` (S0) → per stage `plan_stage` → `_run_stage` /
   `_run_validation` / `_run_joint` / `_run_prediction` / `_run_package`.
4. `_run_round` (`:996-1048`): `build_round_snapshot` (`campaign_activities.py:426`) → `pbpk_domain.campaign.round_build.
   build_stage_snapshot` → `cpf.build.build_from_cpf` → `snapshot.builder` → file + sha256 → `prepare_round_job` →
   `MemoEngine` → `EngineRunner.run` → `Rscript run_job.R` (`simulate`) → `profiles.json`.
5. Fit: `collect_pkml_inputs` → `fitting_activities.plan_jobs` (`pbpk_domain.fitting.plan_multistart`,
   `sample_start_values`) → N × `parameter_identification` jobs → `run_pi.R` → `assess_round` → `run_round` →
   `fit_spec.apply_fit_estimates` → CPF vN+1 → re-simulate.
6. `evaluate_round` → `pbpk_domain.campaign.evaluate.assess_round` → `acceptance.evaluate` → (VPC) →
   `diagnose_round` → `pbpk_domain.diagnostics.diagnose` → `choose_action` → `strategist.decide`.
7. Every step updates `CampaignArtifactWriter` → `FileWriteStore.upsert_campaign` → `campaigns.json`.
8. S6 gate → `escalations.resolve_escalation_decision` → `part11.record_signature` → `local_runner.resolve_escalation`.
9. `_run_package` → `package_activities.collect_bundle` → re-run jobs → `verify_package_reproduction` →
   `finish_package` → `report.campaign_mar.assemble_campaign_mar` → `report.render` →
   `reproducibility.write_bundle_zip` → `CampaignRecord.package`.
10. `read_api.get_campaign_package` and `read_api.download_campaign_artifact` serve the result.

## 4. Major modules (what, why, who calls, what it calls, data in/out)

| Module | Why it exists | Invoked by | Depends on / calls | Receives | Produces | Dependents |
|---|---|---|---|---|---|---|
| `local_runner` | the deployed campaign executor | API seam, CLI | activities, memo, feedback, joint, package activities, file stores | `CampaignRequest` | `CampaignOutcome`, monitor records, escalations, evidence | API decisions, web monitor |
| `campaign_activities` | science steps shared by both executors | `local_runner`, Temporal | `pbpk_domain`, strategist | `RoundContext`, manifests | `RoundBuild`, `EngineJob`, `RoundRunResult`, `RoundEvaluation`, `RoundDiagnosis`, `ActionChoice` | both executors |
| `package_activities` | S6 and S7 engine work and assembly | `local_runner` | reproducibility, report, prediction | evidence, final CPF, MAP | S6 result, package record, zip | read API |
| `EngineRunner` | isolate the GPL engine and check integrity | engine port, engine worker | subprocess, object store | `EngineJob` | `EngineManifest` | all engine work |
| `run_job.R` / `run_pi.R` | drive ospsuite / PK-Sim | runner | ospsuite 12.4.4, PI 2.2.0 | `job.json`, inputs | result files, `pi_result.json` | rounds, fits, S6, S7 |
| `campaign.map` | the signed plan as a typed document | API, orchestrator | split, acceptance, system | CPF, studies, plan | `MapDocument` (hashable, signable) | every stage |
| `campaign.round_build` + `cpf.build` + `snapshot.builder` | regenerate simulations from the CPF | `build_round_snapshot`, S6, S7, VBE | parameters registry, expression library | CPF, scenarios | PK-Sim snapshot | engine |
| `campaign.evaluate` + `acceptance` + `nca` | judge a round | `evaluate_round` | metrics | profiles, observed PK, criteria | verdicts, metrics, findings | diagnosis, monitor, MAR |
| `diagnostics` | deterministic failure → action mapping | `diagnose_round` | `diag_rules.yaml` | residual ratios, fit signals | permitted actions or escalation | strategist |
| `fit_spec` + `fitting` + `identifiability` | specify, plan and judge fits | activities, joint | pksim_paths | CPF, fit ids, observed | PI spec, multistart plan, assessment, new CPF | rounds, SJ |
| `report.*` + `reproducibility` | the deliverable | `package_activities` | pandoc, typst | evidence | MAR, manifest, zip | API downloads |
| `escalations` / `run_guard` / `signatures_api` / `part11` | human gates and Part 11 | web | auth, runner, audit chain | decisions, step-up tokens | signatures, resumed campaigns | orchestrator |
| `filestore` / `records` | persistence of the read model | orchestrator, API | atomic_io | records | JSON documents | everything that reads campaigns |

## 5. Configuration (names only; values never shown)

| Variable | Effect |
|---|---|
| `MODELER_DEPLOYMENT` | development (run guard off, stub engine default), pilot (DEV verifier allowed), production (Keycloak and Postgres Part 11 required) |
| `MODELER_EXECUTION_BACKEND` | `local` (default) or `temporal` |
| `MODELER_READ_ROOT`, `MODELER_OBJECT_STORE_URI` | record and object roots (`file://`) |
| `MODELER_ENGINE_COMMAND`, `MODELER_ENGINE_ID`, `MODELER_IMAGE_DIGEST` | engine executable and recorded identity |
| `MODELER_ENGINE_CORES`, `MODELER_FIT_WORKERS`, `MODELER_MEMO` | planner cores (default 48), parallel fit starts, memoisation |
| `MODELER_OIDC_ISSUER`, `MODELER_OIDC_*`, `MODELER_DEV_AUTH` | identity; the issuer's presence switches the server to production |
| `MODELER_PART11_STORE`, `MODELER_DATABASE_URL` | Postgres Part 11 copy (required in production) |
| `MODELER_TEMPORAL_ADDRESS`, `MODELER_TEMPORAL_NAMESPACE`, `MODELER_S3_*` | unused on the server |

Readers: `modeler_contracts.runtime` (orchestrator and engine) and `modeler_api.config` (API), enforced by
`tests/architecture/test_config_reads.py`. One default mismatch remains (`MODELER_DATABASE_URL`). Values are
unvalidated strings; a bad `MODELER_FIT_WORKERS` raises inside a campaign.

## 6. Build, dependencies, tests

- **Build:** `make sync` (`uv sync --all-packages`), `make test`, `make lint`; web `npm --prefix apps/web run typecheck`,
  `build`, `e2e`; engine `make engine-image` (Docker).
- **Python:** 3.12 intended (CI env var unused); 3.13.18 used in this audit.
- **Tests:** 65 test files under orchestrator, engine-worker and pbpk-domain alone; in-scope run 1,168 passed, 14 failed
  (Temporal test-server download blocked), 23 skipped. In CI every S1–S7 behaviour runs on stub or scripted engines;
  PK-Sim runs only in `engine-image.yml` golden scripts and the manual `reference-models.yml`. See
  `evidence/E_quality.md` §2–3 for the per-file inventory.
- **Trace matrix:** `@pytest.mark.req("T-xx")` → `conftest.py` → `reports/trace-matrix.md`; 29 in-scope files untagged.
- **Guardrails:** 183 architecture tests (layers, OpenAPI snapshot, vocabulary, locked-file hashes) all pass.

## 7. Error handling, logging, monitoring

- Engine errors are typed (`InputIntegrityError`, `EngineFailedError`, `EngineTimeoutError`); locally they become a FAILED
  stage with `Type: message` findings (`local_runner.py:524-530`); on Temporal they are non-retryable application errors.
- The stage `try` covers only the stage dispatch; S0 planning, `plan_stage`, the no-regression check, the influence map
  and flushes are outside it.
- Silent swallows by design: stage-evidence write errors, `.pksim5` conversion failures, S5 sensitivity failures, VBE
  engine failures (all become notes).
- Logging: 20 `activity.logger` calls and no logging configuration in scope; no metrics, tracing or error reporting.
  Diagnostics live in the data (stage notes, findings, manifest stderr tails).

## 8. Deployment configuration

`deploy/server/_env.sh` (environment), `run_modeler.sh` / `stop_modeler.sh` / `status_modeler.sh`,
`install_autostart.sh` (cron `@reboot`, 5-minute watchdog, 02:17 backup), `postgres.sh`, `keycloak.sh`, `qualify.sh`;
`deploy/dev/deploy_to_server.sh` (rsync from the Mac, rebuild, restart). `docker-compose.yml` is local development only
(no orchestrator worker, `:latest` tags). No Helm or Kubernetes manifests exist.

## 9. Code-level observations

- **Single-sourced science, duplicated control:** both executors call the same activities, but the round loops
  (`local_runner.py:614-677, 996-1048` and `campaign.py:85-161, 227-289`) are separate and have drifted.
- **Hotspots:** `local_runner.py` (1,411 lines, `LocalExecutor.run` 154 lines, six responsibilities in one file);
  `campaign_activities.py` (1,106); `snapshot/builder.py` (1,302, locked); `report/campaign_mar.py`
  (`assemble_campaign_mar` 183 lines).
- **Repeated helpers:** eleven `file://` → `Path` helpers with different error behaviour.
- **Locked vs critical:** the gate verdict (`campaign/evaluate.py`), fitting, NCA, VBE, report code and the whole
  orchestrator are not locked, while `acceptance.py`, `diagnostics.py`, `map.py` and the R scripts are.
- **Stale in-code docs:** `cpf/build.py:6-7`, `round_build.py:13-15, 55-57` describe gaps that are now built.
