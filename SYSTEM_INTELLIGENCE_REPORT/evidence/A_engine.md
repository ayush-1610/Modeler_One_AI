# A — Engine plane: how Modeler One talks to PK-Sim (post-MAP campaign)

Read-only audit of `/workspace/Modeler_One_AI` at `1dbda7f` (2026-11-25, shallow clone). Nothing was executed against
PK-Sim: this container has no `Rscript` (`which Rscript` → not found). All claims are labelled **VERIFIED** (I read the
code) or **INFERRED** (reasoned from code, docs or package behaviour I could not run). Line numbers are 1-based.

---

## 1. Summary

The platform never links to PK-Sim. Every engine call is a **fresh subprocess** started as `<command> <job.json>`:
`EngineRunner` (`services/engine-worker/src/modeler_engine/runner.py:91-229`) downloads the inputs into a private temp
dir, checks each input's sha256, writes `job.json`, starts the command in its own process group, parses
`PROGRESS`/`WARNING` lines from stdout, enforces a wall-clock timeout and optional cancellation, then hashes and
"uploads" every file the engine wrote and returns an `EngineManifest`. The real engine is `Rscript run_job.R`
(`services/engine-worker/r/run_job.R`). It supports eight tasks (`simulate`, `dry_run`, `convert_to_project`,
`pk_analysis`, `population`, `sensitivity`, `batch`, `parameter_identification`). The last one sources `run_pi.R`, which
wraps `ospsuite.parameteridentification` 2.2.0. It adds one-value-per-dataset weights, base-unit conversion, and log
scales and relative groups through an R6 subclass. That subclass overrides private, unexported package internals.

**Who invokes it (VERIFIED).** The only live path is the API's `LocalCampaignRunner` (`services/api/src/modeler_api/execution.py:16-19`).
It reaches `local_runner.default_engine()`, which loads `subprocess_engine` through the `modeler.engines` entry point
(`packages/run-contracts/src/modeler_contracts/ports.py:46-54`, `services/engine-worker/pyproject.toml:15-16`). That
engine is wrapped by the orchestrator's `MemoEngine` (`services/orchestrator/src/modeler_orchestrator/memo.py:53-105`).
The Temporal worker (`modeler_engine/worker.py`), the presigned-URL `HttpObjectStore` and the Temporal workflows exist,
but the API never starts a campaign through them. `POST /api/v1/runs` is the only Temporal entry, and it is
structurally broken for most tasks.

**The most important findings:**
- **The catalog harvest does not gate the campaign at run time.** `cpf.binding.bind(cpf, catalog)` has no non-test
  caller. The committed `golden/catalog.json` (harvested 2026-09-15 from 4 OSP models plus the example) is also stale
  against the 15 fixtures now vendored. 8 process `InternalName`s and 1 formulation type used by committed fixtures are
  missing from it.
- **Engine identity is asserted, not measured.** On the server the "digest" is a hash of the committed catalog file
  (`deploy/server/_env.sh:60-61`). The engine id is hard-coded to `ospsuite-12.4.4` for any command whose basename is
  `run_job.R` (`runtime.py:59,62,85`). The actual versions that `run_job.R` writes to `engine_manifest.json` are never
  read by the orchestrator. The memo key does not cover the engine scripts' content.
- **The engine reports problems that nobody reads.** `manifest.warnings` and `engine_info` have no consumer. If a
  simulation's CSV goes missing, `run_job.R` emits a `WARNING` and drops the study, and `evaluate_round` then judges only
  the studies that remain. A dropped study is not reported.
- **The CI qualification gate never exercises the two tasks the campaign depends on.** `simulate` (with
  `write_profiles`) and `parameter_identification` are not run through `run_job.R` by any CI golden script. The
  published, signed, digest-pinned GHCR image is consumed by nothing: the server runs its own R install, and the Mac and
  the reference CI build local tags.
- **Local mode has no cancellation and no global fit deadline.** One failed or timed-out PI start raises through
  `ThreadPoolExecutor.map` and fails the whole stage.

---

## 2. Module inventory

| Module | Path | Responsibility | Called by | Calls | Lines |
|---|---|---|---|---|---|
| Engine image | `services/engine-worker/Dockerfile` | R 4.6.1 + ospsuite 12.4.4 + PI 2.2.0 + rSharp 1.2.2 + .NET 8; Python worker; non-root uid 10001 | CI `engine-image.yml`, `reference-models.yml`, `docker_engine.sh` users | rocker base, r-universe, GitHub archives, dot.net | 93 |
| Job entrypoint | `services/engine-worker/r/run_job.R` | parse `job.json`, verify input sha256, dispatch 8 tasks, write outputs + `engine_manifest.json` | `EngineRunner` via `MODELER_ENGINE_COMMAND`; `golden_tasks.R`; `verify_run_round.sh` | ospsuite R API; `run_pi.R` | 341 |
| PI runner | `services/engine-worker/r/run_pi.R` | one PI start: datasets, weights, base units, groups/log scale, Hessian CI, `pi_result.json` | `run_job.R:301-327`; `pi_smoke.R`, `pi_relative_group.R` (sourced directly) | ospsuite.parameteridentification public + private internals | 432 |
| Catalog harvest | `services/engine-worker/r/harvest_catalog.R` | dimensions/units, PK params, species/populations; names from reference snapshots; Linux load check | `scripts/harvest_catalog.sh` (manual) | ospsuite, jsonlite, digest | 257 |
| Benchmark | `services/engine-worker/r/benchmark.R` | load/single/batch (1 vs N cores)/PI timings on Aciclovir | `engine-image.yml:60`, `ubuntu_engine_check.sh:116` | ospsuite, PI | 135 |
| Runner | `services/engine-worker/src/modeler_engine/runner.py` | subprocess lifecycle, integrity, timeout, cancel, manifest | `subprocess_engine` (entry point) → orchestrator; `worker.py` | `ObjectStore`, `subprocess` | 235 |
| Temporal worker | `services/engine-worker/src/modeler_engine/worker.py` | `run_engine_job` activity on queue `engine-<class>` | Temporal workflows (no live deployment found) | `EngineRunner`, `runtime_env` | 69 |
| Presigned I/O | `services/engine-worker/src/modeler_engine/objectstore.py` | credential-free GET/PUT over presigned URLs | tests only (`tests/test_objectstore.py`) | urllib | 63 |
| Registration | `services/engine-worker/src/modeler_engine/registration.py` | `engine_images` record + golden gate | `engine-image.yml:137-156`; `tests/architecture/test_engine_identity.py` | hashlib | 82 |
| Contracts: runs | `packages/run-contracts/src/modeler_contracts/runs.py` | `EngineJob`, `EngineManifest`, `FitRoundRequest`, `FitStartOutcome`, `RUN_TASKS` | everything above L5 | — | 387 |
| Contracts: ports | `packages/run-contracts/src/modeler_contracts/ports.py` | `EngineFactory` port, `engine_factory()` entry-point loader | `local_runner.default_engine` | importlib.metadata | 54 |
| Contracts: runtime | `packages/run-contracts/src/modeler_contracts/runtime.py` | `MODELER_*` env, engine kind/id/digest resolution, production checks | worker, local_runner, engine_check | — | 182 |
| Orchestrator dispatch | `services/orchestrator/src/modeler_orchestrator/local_runner.py` | `default_engine`, `development_engine` (stub), `engine_identity`, `fit_workers`, `_run_jobs` | `LocalCampaignRunner` | engine port, MemoEngine | 1411 |
| Memo | `services/orchestrator/src/modeler_orchestrator/memo.py` | content-keyed reuse of successful engine outputs | `_executor_engine` (`local_runner.py:1078-1086`) | engine | 119 |
| Fit jobs | `services/orchestrator/src/modeler_orchestrator/fitting_activities.py` | multistart → PI `EngineJob`s; read `pi_result.json`; assess | local_runner `_run_fit`; `FitRoundWorkflow` | `pbpk_domain.fitting` | 170 |
| Engine health | `services/api/src/modeler_api/engine_check.py` | start the command with no job, read its usage line | `admin_api.py:232-233` (System status) | subprocess | 109 |
| Catalog loader | `packages/pbpk-domain/src/pbpk_domain/catalog.py` | pydantic model of `catalog.json`, lookups, `NoEngineBindingError` | `cpf/binding.py` (only tests call `bind`) | pydantic | 230 |
| Fit paths | `packages/pbpk-domain/src/pbpk_domain/pksim_paths.py` | CPF parameter → PK-Sim path by harvested shape | `fit_spec`, S6 `_parameter_paths` | parameters registry | 92 |
| Docker shim | `deploy/dev/docker_engine.sh` | run one job in the image with same-path bind mount | `MODELER_ENGINE_COMMAND` on Mac / reference CI | docker | 45 |
| Stub fixture | `deploy/dev/stub_engine.py` | canned mono-exponential `profiles.json` (simulate only) | `development_engine()` default; Playwright; tests | — | 52 |
| Analytical fixture | `deploy/dev/analytical_engine.py` | 1-compartment model + coordinate-search "PI" | manual `MODELER_ENGINE_COMMAND`; `case_studies/cases.py` | — | 301 |
| Golden scripts | `services/engine-worker/golden/*.R, *.py` | qualification (roundtrip, tasks, PI smoke, relative group, Weibull), reference compare | CI, `ubuntu_engine_check.sh`, `run_reference.py` | run_job.R / run_pi.R / ospsuite | ~996 |
| Server IQ | `deploy/server/qualify.py` | IQ-04 R package versions vs catalog; IQ-05 digest = catalog hash | `deploy/server/qualify.sh iq` (on demand) | Rscript | — |

---

## 3. Feature table

| Feature | Purpose | Inputs | Outputs | Source (file:line) | Status | Evidence note |
|---|---|---|---|---|---|---|
| Subprocess job protocol | isolate GPL engine; stdout progress/warnings | `job.json` {job_id, task, inputs[{name,path,sha256}], options, outputs_dir} | outputs dir files; stdout lines | runner.py:120-127, 185-195; run_job.R:4, 30-33 | implemented | VERIFIED; unit-tested with a fake engine (tests/test_runner.py:52-105) |
| Input integrity (Python) | refuse tampered/renamed inputs | `EngineInput.sha256` | `InputIntegrityError` | runner.py:110-118 | implemented | VERIFIED |
| Input integrity (R, again) | defence in depth | `job.inputs[].sha256` | `stop("sha256 mismatch")` | run_job.R:35-44 | implemented | VERIFIED |
| Output hashing | manifest of every output | outputs dir | `OutputFile{name,uri,sha256,size}` | runner.py:145-152 | implemented | VERIFIED; hash taken from local file, not re-read from destination |
| Timeout | bound runtime | `EngineJob.timeout_s` (default 600) | SIGTERM→SIGKILL group; `EngineTimeoutError` | runner.py:51-63, 206-221; runs.py:34 | implemented | VERIFIED; partial outputs discarded |
| Cancellation | stop on Temporal cancel | `is_cancelled` callable | `CANCELLED` manifest, partial outputs under `cancelled/` | runner.py:129-133, 214-217; worker.py:40 | partial | VERIFIED: only wired in Temporal worker; `subprocess_engine` passes none (runner.py:235) |
| Heartbeat | Temporal liveness | progress fraction | `activity.heartbeat` every 15 s | runner.py:99, 222-228; worker.py:33 | partial | Temporal path only |
| simulate | run snapshot, canonical profiles | `snapshot.json`; `export_pkml` | `<stem>-<Sim>-Results.csv`, `profiles.json`, optional `.pkml` | run_job.R:147-158, 67-138 | implemented | VERIFIED code; file-naming NOTE at :65-66 still open; not in CI golden gate |
| dry_run / convert_to_project | load snapshot into PK-Sim without solving | `snapshot.json` | `.pksim5` | run_job.R:159-163 | implemented (convert used by S7); dry_run unused | `package_activities.py:310-323`; no caller dispatches `dry_run` |
| pk_analysis | single sim + PK | `simulation.pkml` | `results.csv`, `pk_analyses.csv` | run_job.R:164-171 | implemented, unwired | no orchestrator caller |
| population | virtual population run, occasions, VPC band | `simulation.pkml` [+ `population.csv`]; `options.population`, `seed`, `variability`, `occasion_seed`, `vpc` | `population.csv`, `results.csv`, `pk_analyses.csv`, `occasion.json`, `vpc.json` | run_job.R:172-242 | implemented | golden_tasks.R:61-104 covers creation and occasions (not VPC) |
| sensitivity | local sensitivity | `simulation.pkml`; `parameter_paths`, steps, range, cores | `sensitivity.csv` | run_job.R:243-260 | implemented | golden_tasks.R:106-111; used by S6 (`package_activities.py:105-118`) |
| batch | many parameter sets in one SimulationBatch | `simulation.pkml`; paths, units, runs | `batch-NNN-results.csv`, `batch_index.json` | run_job.R:261-300 | implemented | golden_tasks.R:113-129 (no units case); S6 uncertainty (`package_activities.py:204-212`) |
| parameter_identification | one PI start | `pi_spec_base.json` + pkml inputs; `start_values`, `start_index`, `seed` | `pi_spec.json`, `pi_result.json` | run_job.R:301-327; run_pi.R:292-426 | implemented | run_pi.R exercised by pi_smoke / pi_relative_group (sourced directly, not via run_job.R) |
| Base-unit conversion (PI) | avoid "cm/min fitted as dm/min" | spec `unit`, min/max/start | estimates back in CPF unit | run_pi.R:301-324, 381-387 | implemented | VERIFIED |
| Dataset weights | SJ equal-study weighting | `observed.weight` | weighted residuals | run_pi.R:329-337; fit_spec.py:199-211 | implemented | pi_smoke.R:188-198 checks objective × 4 for w = 2 |
| Log scale + relative groups | optimise log(value) / one factor for a group | `scale`, `group`, `groups[]` | per-parameter + per-group estimates, CI, `sd_log` | run_pi.R:100-290, 388-419 | implemented (fragile) | pi_relative_group.R known-truth cases A–F; relies on non-exported internals (run_pi.R:235-239) |
| Hessian CI + correlations | uncertainty, identifiability | package CI | `sd`, `cv`, `lowerCI`, `upperCI`, `correlations[]`, `ci_error` | run_pi.R:89-98, 206-233, 398-422 | implemented | CI computed inside `run()` (INFERRED from golden asserts) |
| Multistart | several starts per round | bounds, budget, cores | N jobs `…-sNNN` | fitting_activities.py:27-52; fitting.py (pbpk_domain) :48-54, 116-140 | implemented | LHS (log space for log params); 4–32 starts |
| Memoisation | skip identical successful jobs | job task, input hashes, options, engine key | copied outputs + reused manifest | memo.py:46-105 | implemented (orchestrator layer) | key excludes engine-script content |
| Engine identity | label fixture vs PK-Sim | command words; env id/digest | `kind`, `engine_id`, `image_digest` | runtime.py:61-85, 146-161; local_runner.py:134-142 | implemented | id/digest asserted, not measured |
| Engine health probe | System status | configured command | reachable/detail (kept 60 s) | engine_check.py:52-109 | implemented | fixture always "reachable"; Docker shim stops before Docker is asked |
| Catalog harvest | never invent PK-Sim names | engine + reference snapshots | `catalog.json` | harvest_catalog.R | implemented, manual | committed catalog is stale vs 15 fixtures |
| Catalog binding gate | refuse unbound CPF params | CPF + Catalog | `BuildPlan` / `BindingError` | cpf/binding.py:55 | placeholder (unwired) | only tests call `bind` |
| Presigned object store | credential-free engine pods | presigned URLs | GET/PUT | objectstore.py:23-63 | placeholder (unwired) | worker hard-codes LocalObjectStore (worker.py:30) |
| Image publish (digest, SBOM, cosign) | supply-chain evidence | built image | GHCR digest, SPDX SBOM artifact, keyless signature, registration JSON | engine-image.yml:101-156 | implemented in CI; not consumed | no runtime pulls by digest; no `cosign verify` anywhere |
| Population chunking (Temporal) | split big populations | `PopulationRunRequest` | child runs | workflows.py:56-77 | broken | passes `snapshot.json` + `population_size`; run_job.R needs `simulation.pkml` + `options.population` |

---

## 4. Detailed findings

### 4.1 Job contract (Q1)

**Python → engine (VERIFIED).**
- `EngineJob{job_id, tenant_id, task, inputs[EngineInput{name, uri, sha256}], outputs_uri, options, timeout_s=600}`
  (`runs.py:20-34`).
- The runner rejects any input name that is not a bare file name (`runner.py:111-112`). It downloads each input into
  `<tmp>/inputs/<name>`, checks its sha256 (`:114-117`), then writes `job.json` with `job_id`, `task`, the staged inputs
  `{name, path, sha256}`, `options` and `outputs_dir` (`:120-127`).
- `tenant_id` and `timeout_s` do not reach the engine.
- R re-hashes every input when a task asks for it (`run_job.R:35-44`).

**Engine → Python (VERIFIED).**
- stdout lines `PROGRESS <0..1>` and `WARNING <text>` are parsed. Every other stdout line is **discarded**
  (`runner.py:185-195`), although the docstring calls it "log output" (`:4-5`).
- stderr is accumulated in memory and its last 4,000 chars are kept (`:197-199, 229`).
- R warnings are turned into `WARNING` lines by `withCallingHandlers` (`run_job.R:332-338`).
- On success, every file under `outputs/` is uploaded to `<outputs_uri>/<relative path>` and hashed (`runner.py:145-152`).
- `engine_manifest.json` (ospsuite version, R version, platform, `sessionInfo()`, the task's `extra` list;
  `run_job.R:46-57`) is parsed into `EngineManifest.engine_info`. If the file is missing this is `{}` with no error
  (`runner.py:139-140`).

**Outputs per task (VERIFIED from run_job.R).**

| Task | Outputs |
|---|---|
| simulate | PK-Sim's CSVs + `profiles.json` `{profiles:{<SimName>:{times_min, concentrations, path, unit, outputs:{<path>:{concentrations, unit}}}}}` (`:62-66, 127-136`) + `.pkml` if `export_pkml` |
| dry_run / convert_to_project | `.pksim5` |
| pk_analysis | `results.csv`, `pk_analyses.csv` |
| population | `population.csv`, `results.csv`, `pk_analyses.csv`, optional `occasion.json`, `vpc.json` |
| sensitivity | `sensitivity.csv` |
| batch | `batch-NNN-results.csv` per run, `batch_index.json` |
| parameter_identification | `pi_spec.json` (the exact spec of this start), `pi_result.json` |

**Status values (VERIFIED).**
- `EngineManifest.status` is only `"SUCCEEDED"` or `"CANCELLED"` (`runner.py:133, 143`).
- Failure and timeout raise `EngineFailedError` / `EngineTimeoutError`, with the stderr tail in the message
  (`:134-137`). The Temporal worker maps them to non-retryable `ApplicationError` types `InputIntegrityError`,
  `EngineTimeout` and `EngineError` (`worker.py:43-48`), and `ENGINE_RETRY` excludes them (`workflows.py:23-26`).
- Fit starts are summarised as `SUCCEEDED | FAILED | CANCELLED_AT_DEADLINE` (`runs.py:137`; `fitting_activities.py:95-107`).
- Stage-level statuses are in `runs.py:197`.

**Integrity limits (VERIFIED).**
- Output hashes are computed from the local file after `store.upload` (`runner.py:150-151`). The destination is not
  re-read.
- Readers downstream do not re-verify. `run_round` takes the URI of `profiles.json` (`campaign_activities.py:687-693`),
  and `_read_result` opens `pi_result.json` by path (`fitting_activities.py:55-63`).
- Only `MemoEngine._reuse` re-hashes recorded outputs before it reuses them (`memo.py:71-75`).
- The manifest itself is neither signed nor chained at this layer.

### 4.2 Task types in run_job.R (Q2) — all VERIFIED from code

`initPKSim()` runs only for `simulate`, `dry_run`, `convert_to_project` and `population` (`run_job.R:142-144`). The
others are ospsuite "Core" operations on a `.pkml`.

- **simulate** (`:147-158`): `runSimulationsFromSnapshot(snapshot, output=out_dir, exportCSV=TRUE, exportPKML=isTRUE(options$export_pkml))`, then `write_profiles`.
  - CSVs are matched to simulations by file name: `-<Sim>-Results.csv`, then `<Sim>.csv`, then `-<Sim>`, then the single
    file (`:71-86`).
  - Only the first `IndividualId` is kept (`:100`).
  - The plasma column `Organism|PeripheralVenousBlood|<compound>|Plasma (Peripheral Venous Blood)` is located by prefix,
    with a fallback to "the only non-Time/Id column" (`:102-107`).
  - Every selected `Organism|PeripheralVenousBlood|…` output is kept with its own unit (`:116-126`).
  - A missing CSV or column gives a `WARNING` and the study is skipped (`:87-90, 108-111, 120-122`).
  - The source itself says the file-name mapping is unconfirmed: "confirm PK-Sim's naming on the Linux engine (F-405
    golden run)" (`:65-66`).
- **dry_run / convert_to_project** (`:159-163`): `loadProjectFromSnapshot(..., runSimulations = FALSE)` and list the
  `.pksim5` files. Only `convert_to_project` is dispatched, by S7 (`package_activities.py:310-323`). `dry_run` has no
  caller; P4's "engine dry run" is reported as "not run here" (`modeler_project/inputs.py:578`).
- **pk_analysis** (`:164-171`): `loadSimulation` → `runSimulations` → `exportResultsToCSV` +
  `exportPKAnalysesToCSV(calculatePKAnalyses(...))`. No orchestrator caller (grep).
- **population** (`:172-242`):
  - The population is `loadPopulation(population.csv)` or `createPopulationCharacteristics(...)` +
    `createPopulation(...)` with integers cast to double (`:180-192`). The seed comes from `options$seed`.
  - `exportPopulationToCSV` always runs (`:197`).
  - **Occasions** (VBE, T-31; `:198-220`): each listed path is checked with `getParameter(..., stopIfNotFound = TRUE)`.
    Values are multiplied by `exp(σ·N(0,1))` with `σ = sqrt(log(1+CV²))`, RNG Mersenne-Twister/Inversion seeded by
    `occasion_seed`. The factors go to `occasion.json`.
  - `runSimulations(sim, population)`, then results and PK CSVs (`:221-224`).
  - **VPC band**: `getOutputValues` at each time, `stats::quantile` at the requested percentiles (default 5/50/95),
    written to `vpc.json` (`:225-240`).
- **sensitivity** (`:243-260`): `SensitivityAnalysis$new` + `addParameterPaths`, optional `numberOfSteps`,
  `variationRange`, `numberOfCores`, then `runSensitivityAnalysis` and `exportSensitivityAnalysisResultsToCSV`. The S6
  caller passes `number_of_steps=2` and no cores (`package_activities.py:113-117`).
- **batch** (`:261-300`):
  - `createSimulationBatch(sim, parameter_paths, molecule_paths)` + `addRunValues` per run, then
    `runSimulationBatches(list(batch))[[batch$id]]`.
  - Run values are converted to the base unit through `toBaseUnit` when `parameter_units` is given (`:274-280`). Molecule
    initial values are not converted.
- **parameter_identification** (`:301-327`):
  - `source(run_pi.R)`; read `pi_spec_base.json`; resolve each `simulations[].pkml` through `input_path`, which
    re-checks its hash.
  - Inject `start_values` per parameter. A start for a group member is refused (`:311-315`). Group starts are injected
    by group name (`:318-321`).
  - Set `start_index` and `seed`; write `pi_spec.json`; run.
- Any other task: `stop("task '%s' is not implemented by this engine image")` (`:329`).

### 4.3 run_pi.R in depth (Q3) — VERIFIED unless marked

- **Spec** (`:9-27`): `simulations[{id,pkml}]`; `parameters[{name, unit, min, max, start, scale?, group?, paths[{simulation, path}]}]`
  (several paths = one shared value); `groups[{name,min,max,start?,scale?}]`; `output_mappings[{simulation, output_path, scaling lin|log, observed{…}}]`;
  `algorithm`; `max_evaluations | generations, population_size`; `seed`.
- **Optimiser** (`:67-87`): `BOBYQA` (`maxeval`), `HJKB` (`maxfeval`) or `DEoptim` (`itermax`, `NP`), starting from the
  package's `AlgorithmOptions_*`. The platform's spec builder defaults to **BOBYQA, `max_evaluations = 200`, output
  scaling "log"** (`packages/pbpk-domain/src/pbpk_domain/fit_spec.py:220-223`). The campaign does not override these
  (`campaign_activities.py:387-388`).
- **Objective / residual weighting / LLOQ handling**: run_pi.R never sets the package's objective-function options (grep
  finds no `objectiveFunction`, `residualWeighting` or `autoEstimateCI` anywhere). The cost type, whether SDs weight the
  residuals, and how values below the LLOQ are treated are **the PI 2.2.0 defaults**. INFERRED: least squares on the
  mapping's scale. **Not verified here.** The SDs are attached to the dataset (`yErrorValues`, error type arithmetic or
  geometric; `:44-61`) and the LLOQ is set (`:62`), but whether they change the cost depends on those defaults.
- **Weights per study** (`:329-337`): a single scalar per dataset, passed as `addObservedDataSets(dataset, weights = list(<name> = w))`.
  SJ sets `w = sqrt(N/(k·n))` (`fit_spec.py:199-211`).
- **Units** (`:301-324`): bounds, start and estimates are converted to the base unit (`toBaseUnit`) before the optimiser
  sees them. They are converted back by a linear factor `toUnit(obj, 1, unit)` for estimate, sd, lowerCI, upperCI and
  initialValue (`:381-387`). `cv` and `sd_log` are left unscaled, which is correct for dimensionless values. Bounds are
  widened first, then the start is set, then the bounds are narrowed, to satisfy the setters (`:317-322`).
- **Log scale and relative groups** (`:100-290`):
  - `free_vector` builds one optimised entry per group (factor f) and per ungrouped parameter. Each entry is on its own
    scale (`log` → optimise `log(value)`).
  - `expand(x) = from_free(x)[entry_of] * multiplier`, where a member's multiplier is its start (`:120-204`).
  - Validation: duplicate group, a group/parameter name clash, an undefined or empty group, the start outside
    [min, max], a group with min ≤ 0, a log scale with min ≤ 0, and the f-bounds × start of a member outside the
    member's own bounds (`:121-185`).
  - `TransformedParameterIdentification` subclasses `ParameterIdentification`. It overrides the private `.runAlgorithm`
    and the public `estimateCI`, and uses unexported `Optimizer`, `PIResult`, `.storeSimulationState`,
    `.restoreSimulationState` and private fields such as `.objectiveFunction`, `.batchInitialization`,
    `.lastOptimResult`, `.bestCostSummary` and `.lastCostSummary` (`:239-290`). The comment says it is "pinned to …
    2.2.0, and golden/pi_relative_group.R fails if they change" (`:235-238`).
  - With neither groups nor log scales, the package's own class is used unchanged (`:347-355`).
- **Hessian CI** (`:206-233, 266-288`):
  - Only the Hessian CI is allowed with the free vector (`:268-270`). σ² = SSR/(n−p) is as the package computes it
    (comment `:206`; INFERRED, not checked against the package source here).
  - A log entry's interval is `exp()` of the log-scale CI, so it is asymmetric. Its CV is `sqrt(exp(sd_log²)−1)` and its
    SD is CV × estimate.
  - INFERRED: the package's `run()` calls `estimateCI()` itself. `pi_smoke.R:210` and `pi_relative_group.R:123` assert
    that a CI or a `ci_error` is present after `run()`.
- **Correlations** (`:89-98, 398-401`): the upper triangle of `ciDetails$corMat` as `{a, b, r}`, keyed by CPF id or by
  group name when the free vector is used. When the covariance is not positive definite there is no CI and the result
  carries `ci_error` (`:420-422`).
- **Multi-start**: there is none inside R, which runs one start per job. Starts come from the orchestrator:
  - `plan_multistart` picks 4–32 starts to fit `budget − reserved` (`pbpk_domain/fitting.py:116-140`).
  - `sample_start_values` draws a Latin hypercube in log space for log parameters (`fitting.py:48-54`).
  - One `EngineJob` per start, `job_id = <round>-sNNN`, `seed = request.seed + index`, `timeout_s = budget − reserved`
    (`fitting_activities.py:27-52`).
  - The seed matters only for DEoptim. BOBYQA from a fixed start is deterministic (INFERRED).
- **Outputs** (`:370-423`): `pi_result.json` has:
  - `start_index`, `algorithm`, `convergence`, `objective_value`, `function_evaluations`, `wall_seconds`;
  - `estimates[]` {name→CPF id, `pksim_name`, path, unit, `base_unit`, estimate, sd, cv, lowerCI, upperCI, initialValue,
    plus `scale`/`group`/`sd_log` on the free path};
  - `correlations[]`, `groups[]` (factor, CI, members), `ospsuite`, `parameteridentification`, `ci_error`.
- **Assessment** (`fitting_activities.py:87-158`):
  - A start whose result lacks `scale:"log"` for a signed log parameter is rejected (`:101-108`).
  - The best converged start supplies the CI and correlations. `assess_fit` flags AT_BOUND, correlated pairs and
    agreement.

### 4.4 Engine command, subprocesses, timeouts, cancellation, parallelism, memo (Q4)

**Command selection (VERIFIED).** `MODELER_ENGINE_COMMAND` is read by `runtime_env()` (`runtime.py:30-50`), and
`resolved_engine_command(default)` picks the value (`:146-152`).

| Context | Default when unset |
|---|---|
| orchestrator / API, development | **the stub fixture** `python <repo>/deploy/dev/stub_engine.py` (`local_runner.py:127-131`) |
| Temporal worker | `Rscript /engine/run_job.R` (`worker.py:27`); the image also sets `ENV MODELER_ENGINE_COMMAND` (`Dockerfile:92`) |
| `pilot` / `production` | no default: `ConfigurationError` (`runtime.py:150-151`); `check_production` also requires the object store and a non-placeholder digest (`:126-144`) |
| server | `Rscript $REPO/services/engine-worker/r/run_job.R` (`deploy/server/_env.sh:56`) |
| Mac / reference CI | `bash …/deploy/dev/docker_engine.sh` (`reference-models.yml:111`) |

The command is split with `shlex` (`local_runner.py:123`; `worker.py:29`).

**Subprocess management (VERIFIED).**
- `Popen([*command, job.json], cwd=workdir, env=<allow-list>, start_new_session=True)` (`runner.py:172-180`).
- The env allow-list is `PATH HOME LANG LC_ALL LD_LIBRARY_PATH DOTNET_ROOT R_LIBS R_LIBS_USER TMPDIR` (`:28`). Anything
  else the engine command reads from the environment never reaches it. `MODELER_ENGINE_IMAGE`, which `docker_engine.sh:19`
  reads, is one example; `DOCKER_HOST` is another.
- Two daemon threads drain stdout and stderr (`:185-203`).
- Termination sends `killpg` SIGTERM, waits 5 s, then sends SIGKILL (`:51-63`).

**Timeouts (VERIFIED).**

| Job | timeout_s |
|---|---|
| default | 600 |
| round `simulate` | max(60, deadline) else 600 (`campaign_activities.py:518`) |
| VPC population | max(120, deadline) else 900 (`:564`) |
| PI start | budget − reserved, 2,700 s by default (`fitting_activities.py:49`; `runs.py:181-182`) |
| S6 sensitivity | 1,800 (`package_activities.py:117`) |
| S6 batch | 3,600 (`:211`) |
| S7 rerun / project | 1,800 (`:305, 322`) |
| VBE | ≥ 3,600 (`vbe_activities.py:105`) |

Temporal adds `start_to_close` (run +300 s; fit = deadline) and `heartbeat_timeout` of 2 min (`workflows.py:39-47`;
`fitting.py:40-49`). The engine-check probe has 20 s, and its answer is kept for 60 s (`engine_check.py:25-26`).

**Cancellation (VERIFIED).**
- Only the Temporal activity sets `is_cancelled` (`worker.py:40`). The runner polls it when each heartbeat wait expires
  (`runner.py:213-217`).
- `FitRoundWorkflow` cancels the pending starts at the deadline (`fitting.py:51-55`).
- The local path builds `EngineRunner` with no `is_cancelled` and no heartbeat (`runner.py:235`). The orchestrator and
  API have no cancel route (grep "cancel": only fitting messages). A local campaign runs on a daemon thread
  (`local_runner.py:1153-1170`) and cannot be stopped short of killing the process.

**Parallelism (VERIFIED, with INFERRED parts).**
- One OS process per job. Local fit starts run through `ThreadPoolExecutor(max_workers=fit_workers)`:
  - `fit_workers` is `cores // simulations_per_evaluation`, capped by `os.cpu_count()` and the number of jobs;
    `MODELER_FIT_WORKERS` overrides it (`local_runner.py:145-153, 1050-1069`).
  - Other job lists (VPC, S6) use `min(len, cpu_count, MODELER_FIT_WORKERS or 64)` (`:1062-1063`).
- `cores` comes from `MODELER_ENGINE_CORES`, default **48**, the server's core count (`campaign_activities.py:407`).
- Inside R, only the `sensitivity` task takes a core count. `batch`, `population`, `simulate` and PI use the ospsuite
  default. INFERRED: `SimulationRunOptions` defaults to all logical cores but one, which oversubscribes when several jobs
  run at once. `benchmark.R:70-79` is the only place `numberOfCores` is set explicitly.
- The Temporal worker runs `MODELER_ENGINE_CONCURRENCY` activities (default 1) on queue `engine-<MODELER_RESOURCE_CLASS>`,
  default `s` (`worker.py:55-63`).
- Workflows target `engine-s` (rounds, `campaign.py:58`), `engine-m` (population chunks, `workflows.py:73`) and
  `engine-l` (fits, `fitting.py:44`). The only worker defined anywhere is `docker-compose.yml` with class `s`
  (`docker-compose.yml:46-53`), so nothing serves the fit queue.

**Memoisation (VERIFIED). There is none inside the engine plane. It lives in the orchestrator.**
- `MemoEngine` keys a job by its task, the sorted input sha256s, the canonical options (seeds included) and `engine_key`
  (`memo.py:46-50`).
- `engine_key = "<kind>:<command basenames>@<resolved digest>"` (`local_runner.py:1072-1075`).
- On a hit, the recorded outputs are re-hashed, copied into the new `outputs_uri`, and the old manifest is returned with
  the new `job_id` plus a `"memoized: …"` warning (`memo.py:68-85`).
- Jobs whose id contains `-S7-rerun-` are never reused (`:35, 88-89`). Only `SUCCEEDED` runs are recorded (`:101-104`).
- Memo is on for the configured engine and off for an injected one unless asked (`local_runner.py:1078-1086`).

### 4.5 Catalog harvest (Q5)

**What is harvested (VERIFIED, `harvest_catalog.R`).**
- From the engine API:
  - `allAvailableDimensions` and `getUnitsForDimension` (`:55-64`). `baseUnitName` comes back empty in 12.4.4, so all 95
    `base_unit` values are null (checked in catalog.json).
  - `allPKParameterNames` (`:66-68`), `Species` and `HumanPopulation` (`:70-78`).
- From reference snapshots (JSON only, never invented), names read from compound `Processes[].InternalName`:
  - process types with the parameters present in the fixture;
  - formulation types;
  - compound and individual calculation methods;
  - expression-profile types and fields;
  - event templates;
  - simulation-level selection names checked against `{Molecule}-{DataSource}` (`:121-199`).
- Each fixture is loaded on Linux with `loadProjectFromSnapshot(runSimulations = FALSE)` to set `roundtrip_ok`. On macOS
  this step is skipped (`:201-216`).
- Failures land in `unresolved` instead of aborting (`:28-39`).
- The reference snapshots come from `fetch_reference_snapshots.sh`, which downloads **from `master`, unpinned**
  (`scripts/fetch_reference_snapshots.sh:61-73`). `harvest_catalog.sh` then `cp -f`s them over the committed golden
  fixtures (`scripts/harvest_catalog.sh:40-41`).
- Cosmetic bug: the progress line prints `comp$Processes` from the last loop iteration (`:219`).

**Committed catalog (VERIFIED by reading the JSON).**
- Engine block: ospsuite 12.4.4, PI 2.2.0, rSharp 1.2.2, `x86_64-conda-linux-gnu`, harvested 2026-09-15, snapshot
  version 80.
- Fixtures: Dapagliflozin, Itraconazole, Midazolam, Rifampicin and the example, all with `roundtrip_ok = true`.
- 9 process types, all with `kind = null`, and 2 formulation types.
- **Stale against the 15 committed fixtures.** I compared fixture `Compounds[].Processes[].InternalName` and
  `Formulations[].FormulationType` with the catalog. Missing from the catalog:

  | Missing name | Used by |
  |---|---|
  | `ActiveTransportSpecific_Hill` | Metformin |
  | `ActiveTransport_InVitro_VesicularAssay_MM` | Verapamil |
  | `IrreversibleInhibition` | Clarithromycin, Omeprazole, Verapamil, Voriconazole |
  | `KidneyClearance` | Clarithromycin, Omeprazole |
  | `LiverClearance` | Digoxin |
  | `MetabolizationIntrinsic_FirstOrder` | Alfentanil, Omeprazole, Voriconazole |
  | `NoncompetitiveInhibition` | Verapamil |
  | `rCYP450_FirstOrder` | Ketoconazole |
  | `Formulation_Particles` | Ketoconazole |

  Yet `pksim_paths.py:36-44` binds `LiverClearance` and `MetabolizationIntrinsic_FirstOrder`, which the catalog does not
  contain. They were harvested from `LinkedParameters` of published PIs (`pksim_paths.py:15-24`), a second, unreconciled
  harvest source.

**How Python loads it (VERIFIED).**
- `Catalog.load` is a frozen pydantic model with `extra="ignore"` (`catalog.py:37-38, 129-131`).
- Lookups NFKC-fold µ and μ (`:23-30`). `require_process_type` and `require_formulation_type` raise
  `NoEngineBindingError` (`:172-191`).
- `cpf/binding.py:55` `bind()` checks process name, parameter name and unit.
- **No production code calls `bind()` or `Catalog.load`.** Grep finds them only in `pbpk_domain` tests and comments in
  `modeler_project`. The builder instead hard-codes harvested constants, e.g. `snapshot/builder.py:46-56` ("The engine
  catalog supersedes these"), and the `pksim_paths` shapes.
- So the "prevents invented names" property rests on:
  1. hand-copied constants;
  2. CI tests pinning catalog invariants (`packages/pbpk-domain/tests/test_engine_catalog.py:28-80`);
  3. PK-Sim itself failing at run time (`getParameter(..., stopIfNotFound=TRUE)` in `run_job.R:208`; `getParameter` in
     `run_pi.R:311`).

  There is no run-time gate against the catalog.

### 4.6 Golden / qualification, pinning, CI publishing, benchmark (Q6)

**Golden gate in `engine-image.yml` (VERIFIED).** On PR, main and tags touching `services/engine-worker/**` or
`run-contracts`, the job builds `linux/amd64` and runs, inside the image (`:50-74`):

| Script | What it checks | What it does not check |
|---|---|---|
| `golden_roundtrip.R` | init → snapshot→project→snapshot by building-block **names** → `runSimulationsFromSnapshot` → PK per exported pkml → DataSet API probe | no numeric reference; if no `.pksim5` appears, the back-conversion is silently skipped (`golden_roundtrip.R:57-60`) |
| `pi_smoke.R` | one-parameter BOBYQA on OSP Aciclovir: estimate finite, weight × 2 → objective × 4, two-parameter correlation or `ci_error` | asserts no estimate value |
| `pi_relative_group.R` | known truth f = 0.5 within 3 % for group linear/log, log CI symmetry, "as before" identity | — |
| `golden_tasks.R` | population (6 individuals), occasions reproducible, unknown path refused, sensitivity rows, batch distinct peaks | — |
| `benchmark.R` (400 runs) | timings | — |
| `weibull_check.R` + `compare_weibull.py` | PK-Sim's Weibull fraction vs the platform's equation within 0.01 (`compare_weibull.py:254-267`) | — |

- `golden.json` is a **literal** `{"roundtrip": true, …}` written after `set -e` (`:74`). The registration gate
  (`registration.py:19, 43-48`) can therefore never see a `false` from CI; it is effectively the shell's `set -e`.
- `weibull` is added to `golden.json` but is not in `REQUIRED_GOLDEN`. A Weibull failure still fails the job, because
  `compare_weibull.py` exits 1.
- **Not covered:** `run_job.R simulate` / `write_profiles` and `run_job.R parameter_identification`. `pi_*` source
  `run_pi.R` directly (`pi_smoke.R:181-184`), so the start-value injection and group refusal in `run_job.R:301-327` and
  the CSV → profiles mapping are not qualified. Also not covered: `pk_analysis`, `dry_run`, `convert_to_project`, the VPC
  band, and batch unit conversion.
- `verify_run_round.sh` exercises `simulate` but is manual (`scripts/verify_run_round.sh:1-8`).

**Image pinning (VERIFIED).**

| Component | How it is pinned |
|---|---|
| ospsuite | commit `4f37d44…` + archive sha256 (`Dockerfile:48-50, 59-64`) |
| PI 2.2.0 | commit + **source-tree hash** (`:51-53, 65-70`) |
| rSharp 1.2.2 | GitHub tag tarball, **no hash** (`:71-73`) |
| final check | versions are asserted, the build fails otherwise (`:74-77`) |
| base `rocker/r-ver:4.6.1` | **tag only** (`:12-13`); the comment says production pins it by digest (`:10`), not done |
| .NET | `--channel 8.0`, latest patch (`:15, 33`) |
| other CRAN/OSP packages | unpinned latest binaries (`:55-58`) |

**Publishing (VERIFIED).**
- Non-PR events push `<image>:<sha12>` and read the RepoDigest (`:101-112`).
- Syft SPDX SBOM is a workflow artifact only, not attached or attested to the image (`:114-120, 158-169`).
- `cosign sign --yes <ref@digest>`, keyless (`:122-127`).
- The registration JSON is built from the **committed** `golden/catalog.json`, not a harvest of the just-built image
  (`:146`). `sbom_ref` is set to the image ref, not the SBOM (`:152`). No `engine_images` row is written anywhere; the
  record is an uploaded artifact.
- No consumer: grep shows no `ghcr.io/…/modeler-engine` pull, no `@sha256:` engine reference, no `cosign verify`.
  `reference-models.yml` builds its own `modeler-engine:ospsuite-12.4.4` tag (`:29, 81-91`). `docker_engine.sh` runs a
  tag (`:19`). The server runs its own conda-R install (`deploy/server/_env.sh:14-19, 56`).

**Benchmarks recorded (VERIFIED in docs only).** No benchmark JSON is committed; the CI one is an artifact.
- `docs/CONTINUATION_PACKAGE.md:778-780`: single run 0.506 s, 1-core batch 0.4214 s/run, 47-core batch 0.00555 s/run
  (75.9×), PI 0.36 s/eval, on a 48-core Xeon Silver 4510.
- `campaign_activities.py:66-68` hard-codes `FIT_SECONDS_PER_SIM = 0.506` and `FIT_EVALUATIONS_PER_START = 40`.
- **The planner's 40 evaluations per start do not match the spec's `max_evaluations = 200`** (`fit_spec.py:221`), so
  planned fit wall time can be up to about 5× too low.

### 4.7 Linux-only constraints, failure modes, logging (Q7)

**Linux.**
- `runSimulationsFromSnapshot` is unsupported on macOS and `loadProjectFromSnapshot` segfaults there
  (`golden_roundtrip.R:46-49, 80-82`; `harvest_catalog.R:202-205`; `run_job.R:6`).
- `run_job.R` has no platform check: on macOS, `simulate` would crash or stop and surface as `EngineFailedError`
  (INFERRED).
- Required environment: .NET 8, `LC_ALL=en_US.UTF-8` (`run_job.R:5`; `Dockerfile:18-24`) and a writable cwd for
  `initPKSim` (`Dockerfile:89-91`).
- The Mac path forces `--platform linux/amd64` and runs as the caller on Linux hosts (`docker_engine.sh:34-45`).
- The server's installer pulls the **newest** ospsuite and PI from r-universe, not 12.4.4 / 2.2.0
  (`scripts/ubuntu_engine_check.sh:92-107`). Version agreement with the catalog is checked only on demand by IQ-04
  (`deploy/server/qualify.py:100-113`), which skips rSharp.

**Failure modes.**

| Failure | Effect | Where |
|---|---|---|
| R `stop()` | non-zero exit → `EngineFailedError` with stderr tail | runner.py:136-137 |
| Temporal path | non-retryable `ApplicationError` | worker.py:43-48 |
| Local path, one PI start fails or times out | `pool.map` re-raises → the stage's `except Exception` → **stage FAILED** (`findings=["EngineFailedError: …"]`); the other starts are lost | local_runner.py:1057-1069, 524-530 |
| Failure or timeout | the temp dir is deleted **without uploading partial outputs**; only cancellation uploads them | runner.py:129-137 |
| `pi_result.json` missing | `ValueError`; a non-`file://` URI raises `NotImplementedError` | fitting_activities.py:55-63 |
| `convergence` null or `{}` | `str(None).lower()` = `"none"` is not in the false-list → treated as **converged** | fitting_activities.py:110 |
| `objective_value` NA | `float(None)` raises | fitting_activities.py:112 |
| simulate drops a study (missing CSV or column) | only a `WARNING` | run_job.R:87-90, 108-111 |

**Logging.**
- Engine stdout outside the protocol is dropped. stderr is kept only as a 4,000-char tail in the manifest or exception.
- No per-job log file is persisted.
- The orchestrator logs through `activity.logger`. The local path has no Temporal context (INFERRED: the logs go to the
  default logger).
- `manifest.warnings` / `engine_info`: grep shows no consumer in `services/orchestrator`, `pbpk_domain` or `services/api`
  apart from the placeholder `ingest_results`, which counts them (`activities.py:25-30`), and memo, which appends one.

### 4.8 Stub and analytical engines (Q8)

**Selection (VERIFIED).**
- The stub is the development default whenever `MODELER_ENGINE_COMMAND` is unset and the deployment is `development`
  (`local_runner.py:127-131`; `runtime.py:146-152`). Pilot and production refuse it.
- The analytical engine is chosen only by setting the command explicitly. Its model functions are also imported by
  `deploy/dev/case_studies/cases.py:87-91` to **synthesise "observed" data**.
- Playwright uses the stub (`apps/web/playwright.config.ts:21`).

**Behaviour (VERIFIED).**
- `stub_engine.py`:
  - handles only `simulate`, writing a fixed C0 = 60 µmol/l, t½ = 174 min curve per simulation (`:18-20, 39-45`);
  - writes `engine_manifest.json {"engine":"stub"}` (`:46`);
  - for any other task writes nothing, so a fit yields "FIT NOT RUN" or a `ValueError`;
  - run with no argument, raises `IndexError`.
- `analytical_engine.py`:
  - a one-compartment model from snapshot values (`:15-23, 117-146`);
  - a deterministic coordinate search for "PI" that echoes the scale/group contract (`:191-212, 246-293`);
  - for `export_pkml`, writes **JSON into files named `*.pkml`** (`:240-244`), so a reader that trusts the extension
    could take a fixture artefact for a PK-Sim model.

**Labelling (VERIFIED).**
- `engine_kind` matches the command's word basenames against `FIXTURE_ENGINES = (stub_engine.py, analytical_engine.py)`
  and then `PKSIM_ENGINES = (run_job.R, docker_engine.sh)` (`runtime.py:61-76`).
- `default_engine_id` gives `software-fixture:<name>`, `ospsuite-12.4.4` or `unknown` (`:79-85`). An explicit
  `MODELER_ENGINE_ID` overrides it (`:154-155`); `docker-compose.yml:52` sets `ospsuite-dev`.
- The campaign records `engine=engine_identity(engine)` once at start (`local_runner.py:1129`).
- The web shows a red "Not a PBPK result" banner for `software-fixture` and an "unverified" banner for `unknown`
  (`apps/web/app/campaigns/[campaignId]/page.tsx:104-113`). System status shows the kind
  (`apps/web/app/admin/system/page.tsx:58`).
- The validation pack check PQ-01 requires `engine_kind == "pksim"` (`pbpk_domain/report/validation_pack.py:106-107`).
- The engine-check probe reports a fixture as reachable without looking at its output (`engine_check.py:101-103`).
- `kind` is derived from the command, so it cannot be forged by `MODELER_ENGINE_ID`. The per-manifest `engine_id` can be.

---

## 5. Sequence diagrams

### 5.1 One round `simulate` job (local / server path)

```mermaid
sequenceDiagram
    autonumber
    participant LR as LocalExecutor (local_runner.py)
    participant CA as campaign_activities
    participant ME as MemoEngine (memo.py)
    participant ER as EngineRunner.run (runner.py)
    participant FS as LocalObjectStore (file://)
    participant R as Rscript run_job.R
    participant PK as ospsuite / PK-Sim (.NET)
    LR->>CA: build_round_snapshot(ctx) → RoundBuild{snapshot_uri, sha256}
    LR->>CA: prepare_round_job(ctx, build) → EngineJob(task=simulate, inputs=[snapshot.json], export_pkml?)
    LR->>ME: engine(job)
    ME->>ME: job_key(task, input sha256s, options, engine_key)
    alt record exists and outputs re-hash OK
        ME-->>LR: reused manifest (+ "memoized" warning)
    else miss
        ME->>ER: run(job)
        ER->>FS: download(uri → tmp/inputs/snapshot.json)
        ER->>ER: sha256 == job.sha256 ? else InputIntegrityError
        ER->>ER: write tmp/job.json {job_id, task, inputs[path,sha256], options, outputs_dir}
        ER->>R: Popen([Rscript, run_job.R, job.json], new session, env allow-list)
        R->>R: input_path(): re-hash snapshot.json
        R->>PK: initPKSim(); runSimulationsFromSnapshot(exportCSV, exportPKML)
        PK-->>R: <stem>-<Sim>-Results.csv (+ <stem>-<Sim>.pkml)
        R->>R: write_profiles() → profiles.json (WARNING on a missing CSV/column)
        R-->>ER: stdout PROGRESS/WARNING; exit 0; engine_manifest.json
        Note over ER: timeout → killpg TERM/KILL → EngineTimeoutError (partial outputs dropped)
        ER->>FS: upload each output, sha256 each
        ER-->>ME: EngineManifest(SUCCEEDED, outputs[], warnings[], engine_info, stderr_tail)
        ME->>ME: store record (SUCCEEDED only)
        ME-->>LR: manifest
    end
    LR->>CA: run_round() → results_uri = profiles.json URI (warnings ignored)
    LR->>CA: evaluate_round() → judges only studies present in profiles.json
```

### 5.2 One parameter-identification round (local path)

```mermaid
sequenceDiagram
    autonumber
    participant LR as LocalExecutor._run_fit
    participant FA as fitting_activities.plan_jobs
    participant PD as pbpk_domain.fitting
    participant TP as ThreadPoolExecutor(fit_workers)
    participant ER as EngineRunner (one per start)
    participant RJ as run_job.R (task=parameter_identification)
    participant RP as run_pi.R
    participant PI as ospsuite.parameteridentification 2.2.0
    LR->>FA: plan_jobs(FitRoundRequest{base_spec, bounds, cores=MODELER_ENGINE_CORES|48, evals=40})
    FA->>PD: plan_multistart(budget−reserved) → n_starts ∈ [4, 32]
    FA->>PD: sample_start_values (LHS; log space for log params)
    FA-->>LR: N EngineJobs {pi_spec_base.json + snapshot-<study>.pkml…; options{start_index, start_values, seed+i}; timeout=budget−reserved}
    LR->>TP: map(engine, jobs)
    par each start
        TP->>ER: run(job)
        ER->>RJ: Rscript run_job.R job.json
        RJ->>RJ: source(run_pi.R); read base spec; pkml via input_path (sha256)
        RJ->>RJ: inject start_values (group member start → stop); write pi_spec.json
        RJ->>RP: run_parameter_identification(pi_spec.json, out)
        RP->>PI: loadSimulation ×k; PIParameters (base-unit bounds/start); PIOutputMapping + DataSet (SD, LLOQ, weight, scaling)
        alt groups or log scale
            RP->>PI: TransformedParameterIdentification$run() (private .runAlgorithm on the free vector)
        else
            RP->>PI: ParameterIdentification$run()
        end
        PI-->>RP: PIResult (estimates, Hessian CI, corMat or ciError)
        RP-->>ER: pi_result.json (CPF ids, CPF units, CI, correlations, groups)
        ER-->>TP: manifest (or raises → the whole map raises → stage FAILED)
    end
    TP-->>LR: manifests
    LR->>FA: assess_round(request, jobs, manifests, deadline_reached=False)
    FA-->>LR: FitRoundOutcome(best start, AT_BOUND, correlated pairs, agreement, ci_error)
```

---

## 6. Defects and risks

**CONFIRMED (traced in code)**

1. **The catalog binding gate is unwired.**
   - `bind()` / `Catalog.load` have no production caller (grep). The T-02/T-03 rule ("refuses to emit anything that is
     not present here", `harvest_catalog.R:6-7`; `catalog.py:10-11`) is not enforced at run time.
   - The committed catalog also lacks 8 process types and 1 formulation type that committed fixtures use (§4.5).
     `pksim_paths.py` binds two of them from a separate harvest.
2. **Engine identity is asserted, not measured.**
   - The server digest = sha256 of the committed `catalog.json` (`_env.sh:60-61`). It does not change when the server's
     R packages or `run_job.R` / `run_pi.R` change.
   - `engine_id` = `ospsuite-12.4.4` for any `run_job.R` / `docker_engine.sh` command (`runtime.py:59-62, 85`).
   - The MAP records `software_versions={"ospsuite": "12.4.4"}` as a literal (`write_api.py:253`). The MAR prints the MAP's
     digest and versions, not those of the runs (`campaign_mar.py:418`).
   - Nothing compares `engine_info.ospsuite_version` with the qualified version.
3. **The memo key ignores the engine scripts' content.** `engine_key` = kind + command basenames + digest
   (`local_runner.py:1072-1075`). A fix to `write_profiles` or `run_pi.R` deployed by rsync keeps serving the old
   memoized outputs on the server.
4. **Engine warnings and info are dropped.**
   - `manifest.warnings` / `engine_info` have no consumer (grep).
   - A study whose CSV or plasma column is missing is skipped with a `WARNING` (`run_job.R:87-90, 108-111`).
     `evaluate_round` and `assess_round` iterate only the studies present (`campaign_activities.py:738-755`;
     `evaluate.py:143`). A stage can therefore be judged on fewer studies than it built, and the record says nothing.
5. **The CI golden gate never exercises `run_job.R simulate` or `parameter_identification`.** These are the two tasks
   every campaign round uses (§4.6). The `write_profiles` CSV-mapping TODO is still in the code (`run_job.R:65-66`).
6. **The golden gate's JSON is hard-coded `true`** (`engine-image.yml:74`). The registration gate is only `set -e`.
   Registration hashes the committed catalog, not a harvest of the image just built (`:146`).
7. **The published, signed image has no consumer, and its supply chain is partly unpinned.**
   - Nothing pulls it by digest and nothing verifies its signature.
   - The base image is pinned by tag only (`Dockerfile:13`), rSharp has no hash (`:71-73`), .NET is a channel, and the
     other R packages are unpinned.
   - The SBOM is not attached to the image.
8. **Local mode has no cancellation, no global fit deadline, and fails a stage on one bad start.**
   - `subprocess_engine` sets no `is_cancelled` (`runner.py:235`).
   - `_run_fit` passes `deadline_reached=False` (`local_runner.py:1058`).
   - `pool.map` re-raises the first engine exception (`:1069`), which becomes stage FAILED (`:524-530`). The Temporal
     design instead tolerates failed starts (`fitting.py:57-62`).
9. **Planner assumptions do not match the engine.**
   - `FIT_EVALUATIONS_PER_START = 40` against the spec's `max_evaluations = 200` (`campaign_activities.py:68` vs
     `fit_spec.py:221`).
   - `MODELER_ENGINE_CORES` defaults to 48 (`campaign_activities.py:407`), while `fit_workers` caps at `os.cpu_count()`
     (`local_runner.py:153`). On a laptop the planner plans 32 starts as if 48 cores were present, and each start's
     timeout restarts per wave.
10. **Convergence parsing is permissive.** A null or `{}` `convergence` counts as converged
    (`fitting_activities.py:110`).
11. **Failure loses evidence.** On a timeout or error the outputs and the full stderr are discarded (`runner.py:134-137`).
    Only a 4,000-char tail survives in the exception, and non-protocol stdout is always dropped (`:185-195`).
12. **The Temporal path is broken or unwired.**
    - `PopulationRunWorkflow` sends `snapshot.json` and `population_size`, but `run_job.R` needs `simulation.pkml` and
      `options.population` (`workflows.py:66-74`; `activities.py:18`; `run_job.R:175-179`).
    - `POST /api/v1/runs` accepts every `RUN_TASKS` entry but always stages only `snapshot.json`
      (`system_api.py:119-139`; `activities.py:11-22`). Its `status_url` `/api/v1/runs/{id}` has no route.
    - The fit queue `engine-l` has no worker.
    - `ingest_results` is a placeholder (`activities.py:27-30`).
    - The worker hard-codes `LocalObjectStore` (`worker.py:30`).
13. **`HttpObjectStore` cannot upload outputs as designed.** The runner builds each output URI as
    `f"{outputs_uri}/{relative}"` (`runner.py:149`), which breaks a presigned URL's query string. The presigned test
    engine writes no outputs (`tests/test_objectstore.py:31-38`).
14. **The env allow-list drops variables the Docker shim needs.** `MODELER_ENGINE_IMAGE` and `DOCKER_*` are not passed
    (`runner.py:28`), so `docker_engine.sh` always runs the default tag (`:19`). The override set in
    `reference-models.yml:107` is ignored when the shim runs under `EngineRunner`.
15. **Reference-fixture provenance is weak.**
    - `fetch_reference_snapshots.sh` pulls from `master` and `harvest_catalog.sh` overwrites the committed fixtures
      (`:61-73`; `:40-41`).
    - `SOURCES.md` lists no file hashes and no commits for 4 of the 15 fixtures (`fixtures/SOURCES.md:6-19`).
16. **Weak golden assertions.** The roundtrip compares names only and silently skips back-conversion when no `.pksim5`
    is produced (`golden_roundtrip.R:57-78`). `pi_smoke` asserts no estimate value.
17. **The governance lock skips the Python half of the engine plane.** `runner.py`, `worker.py`, `runtime.py`
    (`FIXTURE_ENGINES`, `QUALIFIED_ENGINE_ID`), `memo.py`, `docker_engine.sh` and `scripts/*.sh` are not in
    `docs/architecture/locked-files.json`, although they decide integrity, identity and reuse. The R scripts, golden
    files, Dockerfile and `engine-image.yml` are locked.
18. **The analytical fixture writes JSON into `*.pkml` files** (`analytical_engine.py:240-244`), and the case studies'
    "observed" data are generated by that fixture (`case_studies/cases.py:80-99`).

**POTENTIAL**

- **Core oversubscription.** Parallel PI, batch and population jobs each use ospsuite's default `numberOfCores`; only
  sensitivity takes a core count (INFERRED). On a 48-core server up to 32 concurrent R/.NET processes could also strain
  memory.
- **Fragile PI subclass.** `TransformedParameterIdentification` depends on PI 2.2.0 private internals (`run_pi.R:235-290`).
  The image pins 2.2.0, but the server installer takes the newest PI (`ubuntu_engine_check.sh:103-105`). A reinstall
  could break groups and log scales, or change behaviour silently if the internals keep their names.
- **PI objective, weighting and LLOQ are package defaults**, never set by the platform. Whether the observed SDs weight
  the fit, and how BLQ points are handled, is undocumented at this layer.
- **Ambiguous CSV matching.** `endsWith("-<Sim>-Results.csv")` can match another simulation whose name ends with
  `-<Sim>`, e.g. `A-IV` and `IV` (`run_job.R:83`). The fallback to "the only non-Time column" can mislabel `path`
  (`:104-107, 130`).
- **Unhandled engine fields.** A PI estimate whose path is not in `id_by_path` keeps its PK-Sim name
  (`run_pi.R:379-381`). Downstream code keys estimates by name (`fitting_activities.py:109`), so such a value would
  silently not apply.
- **Orphan containers.** When SIGKILL reaches the `docker run` CLI (`docker_engine.sh:42`), the container may keep
  running.
- **Arbitrary local file read.** `POST /api/v1/runs` takes an arbitrary `file://` `snapshot_uri` (curator or reviewer
  role). Through `LocalObjectStore` this copies any readable local file into the job dir, given its hash
  (`runner.py:72-83`).
- **Undocumented test fixtures.** `results_sample/*.csv` are real-looking ospsuite outputs used across tests, with no
  documented provenance.
- **Unconverted time in S6.** `evaluate_s6` passes raw observed `times` as `t_last_min` without the defensive
  unit conversion `evaluate_round` applies (`package_activities.py:228-233` vs `campaign_activities.py:762-765`). Low
  risk if profiles are always stored in minutes (`units.py:72-92`).
- **VPC demographics.** VPC populations are 0 % or 100 % female, from the study's representative sex
  (`campaign_activities.py:557`). Weight and height ranges are not passed.

---

## 7. Open questions and what could not be verified

- **Nothing here ran PK-Sim**, because there is no `Rscript` in this container. Unverified:
  - that `run_job.R` / `run_pi.R` behave as read;
  - that PK-Sim names CSVs `<stem>-<Sim>-Results.csv` (the code's own open NOTE);
  - that PI 2.2.0's `run()` computes the CI itself;
  - the default objective, weighting and LLOQ handling;
  - the package's `cv` units (fraction or %);
  - `convergence` value types;
  - ospsuite's default `numberOfCores`;
  - pkml byte-determinism, which affects memo hits for PI.
- **CI pass history is not visible here.** I cannot confirm that `engine-image.yml` passes today. The continuation doc
  says the reference matrix moved to the server and the repo is private (`docs/CONTINUATION_PACKAGE.md`, "Session
  2026-09-24").
- **The server's installed versions are unknown.** IQ-04 exists, but no IQ record is committed.
- **Who wrote `results_sample/*.csv`**, and when, is not recorded.
- **No Helm chart or Kubernetes manifests are in the repo,** despite "production runs on Kubernetes via Helm"
  (`docker-compose.yml:1`). The Temporal and presigned-URL design cannot be checked end to end.
- **The continuation doc contradicts the code on log scales.** Its P5 row says "`run_pi.R` never receives the scale" and
  that log parameters are optimised linearly. `run_pi.R` (PI-4 B1) and `fitting_activities.py:101-108` show scales are
  honoured and checked. The doc row looks stale; the reference runs would confirm it.
- **S7's "fresh-engine re-run at 1e-6"** reruns on the same host and engine build (`package_activities.py:294-307`). It
  shows run-to-run determinism, not reproducibility on an independent qualified image.
- **Unexplored here:** how the platform-set simulation names (study ids) are constrained. If one can contain `/`, PK-Sim
  writes a subdirectory (`reference_compare.R:37`), and `collect_pkml_inputs`' `Path(name).name` would then break the
  PI input names.
