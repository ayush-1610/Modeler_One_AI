# Architecture boundaries — layers, rules, locked files and the guardrails that enforce them

**Status: phases 1–3 in force (2026-10-07).** Changes to agents, the pipeline pages and the API repeatedly broke code that
was not part of the change: the T-56 kit broke twice from P4 evidence checks, a study "purpose" broke the MS-01 study
record, a merged API response showed a count as `[object Object]`, an id outside the builder's vocabulary passed S0
while the model had no clearance, and a campaign file was read mid-write. The cause is structural: nothing enforced
which package may use which, the parameter-id vocabulary is copied into many modules, and responses are untyped. This
document draws the boundaries; `tests/architecture/` enforces them in `make test` and CI.

## 1. Layers

Imports point down only. Two packages on one layer do not import each other.

| Layer | Package (import name) | Holds | Must not |
|---|---|---|---|
| L0 | `pbpk_domain` | Science: CPF, builder, MS-01 stages, units, rulesets, acceptance; later the parameter registry | import anything first-party |
| L1 | `modeler_contracts` | Typed DTOs and ports shared across processes (runs, campaigns; later settings schema, `CampaignRunner`) | hold logic |
| L2 | `modeler_intake` | Deterministic file reading, recipes and their vocabulary | call an LLM |
| L2 | `modeler_storage` | The Postgres audit trail (3a), the file-backed campaign read model and the database repositories (3b) | import the API or the orchestrator |
| L3 | `modeler_project` | Pipeline artifacts P0–P4 (`FileProjectStore`, audit), one service per artifact kind | know about HTTP |
| L4 | `modeler_agents` | The LLM edge only: agents propose, code and people decide | hold deterministic rules others need |
| L5 | `modeler_orchestrator`, `modeler_engine` | Campaign runner; engine worker | import `modeler_api` |
| L6 | `modeler_api` | HTTP only: auth dependencies, request → service, response | hold business logic; routers import routers |
| L7 | `apps/web` | Pages, a generated API client and typed hooks *(phase 7)* | hand-write API types |

## 2. Rules

| Rule | Statement | Enforced by |
|---|---|---|
| B1 | One parameter vocabulary: every CPF id with placement, value kind, storage unit, bounds, S0 role, PK-Sim name | phase 1: `test_parameter_vocabulary.py` keeps today's copies consistent; phase 4: the registry `pbpk_domain/parameters/registry.yaml` (4b: it derives every table, `test_parameter_registry.py` in `pbpk-domain/tests` and `tests/architecture`) |
| B2 | Typed contracts at every process edge: response models per endpoint, generated web types, artifact content models | phase 1: `test_openapi_contract.py` (any contract change is visible); phase 6: `test_response_models.py` (P0–P4 and escalation routes); phase 7: `apps/web/lib/api-types.ts` generated from the snapshot, checked by `npm run typecheck` |
| B3 | One writer per artifact kind; nobody else reads `version.content["…"]` | phase 6: `test_artifact_owners.py` (`[owners]` in `boundaries.toml`; no exceptions since 6f) |
| B4 | No upward or sideways imports; the API reaches the orchestrator and the agents through one seam module each; routers do not import routers | phase 1: `test_import_boundaries.py` |
| B5 | Configuration read in one place, injected (never patched in tests) | phase 2: `test_config_reads.py` (§3a) |
| B6 | Frontend seams: one API client, `useResource` / `useMutation` with rail refresh, CSS per feature, phase list from the API | phase 7c: `test_web_client.py` (only `apps/web/lib/api.ts` fetches; a route the contract types is called by name through `get` / `send` / `upload` / `serverGet`); phase 7d: the same test (only `lib/hooks.ts` imports the typed read `get`; pages use `useResource` / `useMutation`); CSS per feature: `apps/web/app/styles/` (phase 7d) |
| B7 | Tests use public surfaces: contract tests per boundary, e2e by `data-testid` / role, not wording | phase 1 (package tests obey the layer rule); phases 5–7 |

## 3. Guardrails (phase 1) — what fails, and what to do

All are plain-Python tests under `tests/architecture/`, tagged `T-25`, run by `make test` and CI. No new dependencies.

| Test | Fails when | Then |
|---|---|---|
| `test_import_boundaries.py` | a module imports upward or sideways (lazy imports count); imports a workspace package its `pyproject.toml` does not declare; an API module other than the seam imports the orchestrator / agents; a router imports a router; a package's tests import a higher layer; an exception in `boundaries.toml` no longer occurs | move the code down a layer or behind a port. An exception needs the owner's approval (`boundaries.toml` is locked). Remove an exception the moment it is fixed |
| `test_openapi_contract.py` | the API's OpenAPI document differs from `docs/api/openapi.json`; the message lists the added / removed / changed operations and schemas | if intended: `UPDATE_SNAPSHOTS=1 uv run pytest tests/architecture/test_openapi_contract.py` and a CHANGELOG entry saying what changed for clients |
| `test_parameter_vocabulary.py` | an id has a storage unit but no placement; an id S0, the to-do list or the bounds table advertise is not placeable; PK-Sim compound parameters are not model inputs; the reference-elimination sets disagree | add the id to every list, or (phase 4) to the registry. Known drift is `xfail(strict=True)`: fixing it turns the test red until the mark goes |
| `test_parameter_characterization.py` | a table of the vocabulary, or what a vocabulary function answers for one of ~100 ids (placement, storage unit, conversion, binding, compound path, bounds, ValueOrigin method, S0), differs from `docs/architecture/parameter-vocabulary.json` | phase 4 refactors keep it unchanged; a science change (owner's approval, CHANGELOG) rewrites it with `UPDATE_SNAPSHOTS=1` and the diff is the review |
| `test_locked_files.py` | a locked file's bytes change, a new file appears under a locked pattern, or one disappears | only with the owner's approval, in its own PR, with a CHANGELOG entry; then `UPDATE_LOCKED=1 uv run pytest tests/architecture/test_locked_files.py` |
| `test_config_reads.py` | a module outside `[config]` in `boundaries.toml` reads `os.environ` / `os.getenv` or defines a `BaseSettings`; a test patches `get_settings` | read through `modeler_api.config.Settings` (`SettingsDep`) or `modeler_contracts.runtime.runtime_env()`; in API tests use the `api_settings` fixture. A new reader needs the owner's approval |
| `test_response_models.py` (phases 6, 9) | a route of a router listed under `[response] routers` in `boundaries.toml` (since phase 9, every router) answers with no pydantic model and is not listed under `[response] untyped`, or answers an open `Envelope[dict[str, Any]]` and is not listed under `[response] open`; a listed route is typed or gone. Only a handler annotated to return a `Response` (a file download) is exempt | declare `response_model=Envelope[...]` with a model in `modeler_api.views` (stored content: the owner's content model), update the OpenAPI snapshot; remove the route from the list. A new entry needs the owner's approval |
| `test_artifact_owners.py` (phase 6) | a module writes an artifact kind it does not own (`[owners]`); a module that owns no kind reads stored content raw (`.content[…]`, `.content.get(…)`, `**….content`) more or less often than `[owner_exceptions.reads]` records; an exception no longer occurs | call the owner module's function; when reads go, lower the recorded count (drop it at zero). A new exception needs the owner's approval |
| `test_web_client.py` (phases 7c, 9e) | a module of `apps/web` other than `lib/api.ts` calls `fetch`; a removed untyped helper (`apiGet` / `apiSend` / `apiUpload` / `serverRead` / `rawPost`) appears again, or `lib/api.ts` exports a function other than `apiFile` that takes a bare URL; a module other than `lib/hooks.ts` imports the typed read `get` | read with `useResource` and change with `useMutation` (`lib/hooks.ts`); call the route by name with `get` / `send` / `upload` / `serverGet` / `post` (a download: `apiFile`) |
| `npm run typecheck` in `apps/web` (phase 7) | `apps/web/lib/api-types.ts` differs from what `docs/api/openapi.json` generates (`openapi-typescript --check`), or a page uses an answer as a shape the contract does not give | `npm --prefix apps/web run api-types` after the snapshot changes; fix the page, or the response model if it is too loose |

CI also builds the web app (`web`: `npm ci`, typecheck, production build) and the API image (`api-image`: build,
imports, `/health`), and the secret scan reads `.gitleaks.toml` (default rules; a dotted CPF id is not a secret).

### Exceptions recorded on 2026-10-07 (`tests/architecture/boundaries.toml`: 48, 35 after phase 3, 25 after phase 5a, 11 after 5b, 8 after 5c, 4 after 5d, **none after 8c**)

| Rule | Count | What | Removed in |
|---|---|---|---|
| layer | 0 | none. `local_runner` reaches the engine through the port `modeler_contracts.ports.engine_factory`: the engine worker registers `modeler_engine.runner:subprocess_engine` under the `modeler.engines` entry point (the 3 orchestrator → API imports went in phase 3) | done (8c) |
| declared | 0 | none (api → intake and api → orchestrator are declared since phase 3; agents → pbpk_domain since phase 5c; the orchestrator no longer imports the engine since 8c) | done (8c) |
| seam | 0 | none: the API reaches the agents only through `modeler_api.agent_jobs` (phase 5b, 14 removed) and the orchestrator only through `modeler_api.execution` (phase 3). The deterministic quote check and recipe review left the agents package in phase 5c (`modeler_intake.citations`, `modeler_intake.recipe_review`; 2 removed) | done |
| router | 0 | none. Phase 5a moved the shared dependencies to `modeler_api.deps` (10 removed); phase 5d moved the data-plan derivation to `modeler_project.data_plan`, the study upload models and the observed PK to `modeler_api.studies`, and the project CPF view to `modeler_api.cpf_view` (4 removed) | done |
| tests | 0 | none. The `_fittable_candidates` case moved to `orchestrator/tests/test_fittable_candidates.py`, and the S3 object store moved to `modeler_storage.objects`, which the engine's object-store test reads (the 5 orchestrator tests → API went in phase 3) | done (8c) |

### Known vocabulary drift (strict xfail)
- Fixed in phase 4e (registry 1.1, the owner's decision 2026-10-08): `elim.hepatic.total_cl` is an alias of
  `elim.hepatic.total.plasma_clearance`, which PK-Sim's `LiverClearance` is bound to and which converts to ml/min/kg.
- Still open: `elim.ehc_fraction` converts (dimensionless) but is refused, with its reason: MS-01's Individual path
  (`Organism|Liver|EHC continuous fraction`) is not harvested yet. Harvesting it lets it be placed.

### 3a. Configuration (phase 2)

| Process | Reads the environment | Code gets it by |
|---|---|---|
| API | `modeler_api.config.Settings` (pydantic-settings, `MODELER_*`, once per process) | `settings: SettingsDep` in routers and dependency providers; `get_settings()` in the few helpers below a view (blinding's project record, `plan_api._exploratory`) until phase 5 makes blinding a service; `main.py` reads it once at import for CORS |
| Orchestrator, engine worker | `modeler_contracts.runtime.runtime_env()` (stdlib, read on each call) | `runtime_env().get("image_digest", "local")`: each call site keeps its own default |
| Agents | `modeler_agents.llm`, `web_search` (callers may pass their own mapping) | unchanged |
| Engine subprocess | `modeler_engine.runner` passes chosen variables through | unchanged |

Tests: `services/api/tests/conftest.py` gives `api_settings(read_root=..., ...)` (through `config.use_settings`, seen by
injected and direct reads alike) and re-reads `MODELER_*` before each test (`config.reload_settings`).

**One default per variable** (the owner's decision, 2026-10-08; `modeler_contracts.runtime`): development defaults,
and a production deployment (`MODELER_DEPLOYMENT=production`, set by `deploy/server/_env.sh`) that refuses to start
unless it sets them (`RuntimeSettings.check_production`, called by the API's lifespan and each runner's entry point).
- `MODELER_OBJECT_STORE_URI`: `LOCAL_OBJECT_STORE` for the API and the orchestrator alike; production sets it.
- `MODELER_ENGINE_COMMAND`: none in production. In development the local runner runs the stub engine, which every page
  labels a software fixture; the engine worker runs the image's `Rscript /engine/run_job.R`.
- `MODELER_ENGINE_ID`: the engine names itself. It is `ospsuite-12.4.4` for PK-Sim (the qualified catalog; a test
  keeps them equal) and `software-fixture:<name>` for a fixture.
- `MODELER_IMAGE_DIGEST`: production refuses the all-zero placeholder, which is for tests and development only. A
  container records its image digest (`sha256:<hex>`). The server, which runs PK-Sim from its own installation, records
  its harvested catalog's digest (`catalog:sha256:<hex>`).

## 4. Locked files (approved by the owner 2026-10-07)

Listed with their SHA-256 in `docs/architecture/locked-files.json`. **SME**: changes only with the owner's explicit
approval, stays UNVERIFIED, bumps its version. **core**: changes only in its own PR with the owner's approval and a
CHANGELOG entry.

| Layer | Owner | Files | Why |
|---|---|---|---|
| L0 | SME | `pbpk_domain/rulesets/*.yaml` (4) | acceptance criteria, diagnostics, dissolution similarity, DDI screening |
| L0 | SME | `pbpk_domain/requirements/*.yaml` (6) | data-plan templates: what an application must have |
| L0 | SME | `pbpk_domain/parameters/registry.yaml` (added 2026-10-08, phase 4b) | the CPF parameter registry: placement, storage units, PK-Sim compound names, review bounds, S0 |
| repo | SME | `docs/PBPK_MODELING_WORKFLOW.md` | MS-01 |
| L0 | core | `cpf/models.py`, `cpf/build.py`, `snapshot/builder.py`, `reference/osp_import.py`, `pksim_paths.py`, `parameter_units.py` | CPF schema, builder, harvested PK-Sim names, units |
| L0 | core | `acceptance.py`, `campaign/map.py`, `campaign/split.py`, `diagnostics.py`, `m15.py`, `reproducibility.py` | acceptance, MAP and MS01_VERSION, data split, diagnostics, ICH M15, reproducibility gate |
| L3 | core | `modeler_project/audit.py`, `modeler_project/store.py` | audit hash chain, artifact versions and approvals (Part 11) |
| L5 | core | `engine-worker/r/*.R`, `engine-worker/golden/**`, `engine-worker/Dockerfile`, `.github/workflows/engine-image.yml` | the qualified engine and its golden gate |
| L2 | core | `modeler_storage/audit.py` (moved unchanged from `modeler_api/compliance/` in phase 3a, same sha256) | Postgres audit chain |
| L6 | core | `compliance/signatures.py`, `auth.py`, `services/api/migrations/*.sql` | e-signatures, step-up / DevVerifier, audit-table rules |
| repo | core | `CLAUDE.md`, `docs/validation/requirements.yaml`, `conftest.py`, `.github/workflows/ci.yml`, `tests/architecture/boundaries.toml` | working rules, validation evidence, CI gates, boundary exceptions |

Apart from the moved audit trail, nothing in L1, L2, L4 or L7 is locked: those are what phases 2–7 refactor. Phases 3 (moved `compliance/audit.py` in 3a),
4 (`build.py`, `parameter_units.py`, `pksim_paths.py`) and 5 (shrinks `boundaries.toml`) each need the owner's approval.

## 5. Coupling map — where changes ripple today (2026-10-07 survey)

| # | Coupling | Where | Phase |
|---|---|---|---|
| C1 | Parameter ids in 12+ places | `cpf/build.py`, `cpf/completeness.py`, `parameter_units.py`, `pksim_paths.py`, `cpf/process_bindings.py`, `modeler_project/inputs.py`, `modeler_project/evidence.py`, `plan_api.py`, `templates_api.py`, requirement YAMLs, the A2 prompt, `deploy/proof/run_t56.py` | 4 |
| C2 | Settings and environment read in ~20 modules; tests patch `get_settings` per router | `main.py` reads settings at import; `MODELER_OBJECT_STORE_URI` defaults differ between orchestrator and API | 2 |
| C3 | `project_api` is a hub; routers import routers | see the router exceptions above | 5 |
| C4 | Business logic in routers | agent jobs (`run_extraction`, `run_triage_job`, `run_research_job`, `run_planning_job`), MAP signing, data-plan derivation, CPF publishing | 5 |
| C5 | Untyped, merged responses | `envelope({**preview, **_view(ws)})` in `client_api`; `escalations` without an envelope | 6 (**done**: every P0–P4 and escalation answer has a response model, shapes kept); 9 (**done**: every route of the API, stored content as its owner's model) |
| C6 | Artifact content without an owner | CPF kind: 3 ids, 3 schemas, 2 writers; MAP written by a router, its signature read by `blinding` | 6 (**done**: 6e one writer per kind, `map_artifact` owns the MAP; 6f only the owner modules read stored content) |
| C7 | Two persistence models on `MODELER_READ_ROOT`; orchestrator imports the API's store | `FileProjectStore` + `modeler_api.filestore`; e2e writes `campaigns.json` | 3 |
| C8 | Process-local job state | `_RUNNING` sets in four routers; `_LOCK` in `store.py`, `audit.py`, `run_store.py` | 8 (**done**: 8a the artifact store writes atomically and locks approvals across processes; 8b job leases in `modeler_storage.jobs`, read-model and run-record writes under `file_lock`, a decision claimed by removing its escalation; `test_process_state.py` keeps it so) |
| C9 | Recipe constant keys ×4 | `recipe.py`, `apply.py`, `data_mapping.ConstantKey`, `sheet_form.py`. **Done in phase 5c:** `recipe.ConstantKey` / `CONSTANT_KEYS` / `NUMERIC_CONSTANTS` are the one list; `apply`, the review and the recipe's schema read it, and a test keeps the sheet form's keys inside it | 5 |
| C10 | Tests on internals and wording | `test_cpf.py` → orchestrator internals; `match=` on other packages' messages; the T-56 kit on ~20 endpoints | 5–7 |

## 6. Phases (each one PR to `main`, behaviour identical, everything green)

| Phase | What | Removes |
|---|---|---|
| 1 | Guardrail tests, web and API-image CI jobs, API Dockerfile installs the locked workspace, this document | stops new violations |
| 2 | **Done.** One reader per process (§3a), injected; tests use `api_settings` | C2 |
| 3 | **Done.** 3a: `modeler_storage` with the Postgres audit trail (locked, moved unchanged, its own PR). 3b: the read model, repositories and tenancy move in; the orchestrator no longer imports the API; the API starts and steers campaigns through `CampaignRunner` (`modeler_contracts.ports`) obtained in `modeler_api.execution` | C7, the api ⇄ orchestrator cycle |
| 4 | Parameter registry in `pbpk_domain` (SME-governed); characterization tests first; `total_cl` fixed in its own science PR with an alias. Plan: `docs/plans/2026-10-08-parameter-registry.md`; **4a done** (characterization snapshot), **4b done** (the registry, locked, derives every table), **4c done** (`inputs`, `evidence`, `completeness`, `process_bindings` read it), **4d done** (the locked `parameter_units`, `pksim_paths`, `cpf.build` read it; no hand-kept copy left), **4e done** (registry 1.1: `total_cl` alias, `ehc_fraction` refused with its reason, total clearance InVivo). **Phase 4 done** | C1 |
| 5 | Services out of routers; `deps.py`; deterministic helpers out of the agents package. Plan: `docs/plans/2026-10-08-phase-5-services.md`; **5a done** (`modeler_api.deps`, the `agent_jobs` seam; router exceptions 14 → 4); **5b done** (every agent job and run record through `modeler_api.agent_jobs`; seam exceptions 16 → 2); **5c done** (the quote check and recipe review in `modeler_intake`, one list of recipe constant keys; seam 2 → 0, agents declare `pbpk_domain`); **5d done** (data-plan derivation, study models and observed PK, project CPF view out of the routers; router 4 → 0). **Phase 5 done**: 4 exceptions left (the engine port, 2 package tests) | C3, C4, C9 |
| 6 | Typed responses for P0–P4; one owner per artifact kind. Plan: `docs/plans/2026-10-08-phase-6-contracts.md`; **6a done** (the two ratchets: 55 untyped routes, 3 non-owner writers, 48 raw reads in 12 modules); **6b done** (`Envelope[T]`, `modeler_api.views`; P0/P1 typed, 55 → 40 untyped); **6c done** (P2/P3 typed, 40 → 20); **6d done** (P4, project and escalation routes typed, 20 → 0: C5 closed); **6e done** (one writer per kind: `brief_ops`, `inputs`, the new `map_artifact`; raw reads 48 → 40); **6f done** (raw reads 40 → 0: C6 closed). **Phase 6 done** | C5, C6 |
| 7 | Frontend seams (`openapi-typescript`, approved by the owner 2026-10-08). Plan: `docs/plans/2026-10-08-phase-7-frontend.md`; **7a done** (generated web types, the drift check in `typecheck`, `Schema<…>`, the brief page on it); **7b done** (every typed answer the pages read from `Schema<…>` / `Narrow<…>`; closed value sets tightened in the API); **7c done** (one API client in `lib/api.ts`, typed by route; `test_web_client.py`); **7d done** (`useResource` / `useMutation` on react-query, a change refreshes the phase rail; one stylesheet per feature in `app/styles/`). **Phase 7 done** | B2, B6 |
| 8 | Job state out of the process (owner: do it now, 2026-10-09). **8a done** (the locked artifact store: versions and blobs linked into place whole, approvals under `flock`); **8b done** (job leases shared by every process on the root, `modeler_api.jobs` for a project's agent jobs, read-model and agent-run writes under `file_lock`, a decision claimed once; guardrail `test_process_state.py`); **8c done** (the engine port `modeler_contracts.ports.engine_factory` through the `modeler.engines` entry point, the S3 store in `modeler_storage.objects`: `boundaries.toml` has no exception left). **Phase 8 done** | C8 |
| 9 | Every remaining route typed, API and web together (owner decisions 2026-10-08). Plan: `docs/plans/2026-10-09-phase-9-typed-api.md`; **9a done** (the response ratchet covers every router, a route without a model counts unless it returns a `Response`; `[response] open` for envelopes of stored content; the `main.py` routes moved to `modeler_api.system_api`; 37 untyped routes and 5 open answers left); **9b done** (the P5 plan: `views/plan.py` with the owner's `ModelPlan`, the canvas on the hooks; 24 untyped left); **9c done** (`modeler_storage.records`: `ProjectRecord`, `ProposalRecord`, written through by every writer; projects, CPF, studies, templates and the guided flow typed; 12 untyped left); **9d done** (`CampaignRecord` / `EscalationRecord`, checked by the runner as it writes them; the monitor, inbox, package, campaign start, signature, results and system routes typed; `[response] untyped` empty; the web's typed `post`); **9e done** (the evidence and dataset routes answer the owner's `EvidenceItem` / `ObservedDataset`; `[response] open` empty; the web's untyped helpers removed, only `apiFile` takes a URL). **Phase 9 done** | C5 (rest of the API), B2, B6 |

Never in these phases: a big-bang rewrite; renaming artifact kinds, ids or stored JSON keys without a versioned
migration (the audit chain hashes content); a change to SME-governed content or MS-01 semantics without approval;
reordering audit or approval writes. `deploy/proof/run_t56.py` and the e2e specs keep passing unchanged through phase 5.
