# 08 · Data architecture and information flow (post-MAP scope)

Diagram source: `data_flow.mmd`. `<rr>` = `MODELER_READ_ROOT/<tenant>`; `<os>` = `MODELER_OBJECT_STORE_URI/tenants/<tenant>`
(both `file://` on the server).

## 1. Where data comes from and where it goes

| Stage of life | Data | Origin | Validation | Store |
|---|---|---|---|---|
| Enters the campaign | CPF, signed MAP, observed PK, model system | staged at `plan:sign` (`prep/plan-v{n}`) or `campaign:prepare` (`prep/{question_id}`) | pydantic models on read; run guard (pilot/production): MAP signed, CPF = MAP table | `<rr>/prep/...` |
| Per round | PK-Sim snapshot, PI spec | `build_round_snapshot` | builder refuses non-storage units; ValueOrigin coerced to the harvested enum; scenario build errors fail a fit stage | next to the CPF: `<prep>/snapshots/` |
| Engine I/O | `job.json`, outputs, `engine_manifest.json` | `EngineRunner` | sha256 per input (Python and R); output hashes recorded | `<os>/campaigns/<cid>/<stage>/r<n>[-phase]/`, fits under `<os>/fits/<round>/start-NNN/` |
| Fitted model | new CPF version (FITTED, provenance ParameterIdentification, SD/CV/CI95) | `run_round` → `apply_fit_estimates` | bounds ⊆ plausibility enforced on the policy; `model_copy` does not re-validate the record | `<prep>/cpf/<cid>-<stage>-r<n>[-c<k>].json` (+ `.system.json` beside it for a model system) |
| Verdicts and progress | `CampaignRecord` | `CampaignArtifactWriter.flush` | `CampaignRecord.model_validate` before each write | `<rr>/campaigns.json` (one file, every campaign of the tenant) |
| Escalations | `EscalationRecord` | writer | `EscalationRecord.model_validate` | `<rr>/escalations.json` |
| Stage evidence | status, findings, rounds, notes, judged metrics, snapshot, outputs | `_persist` after a non-stopped stage | none (JSON dump, `OSError` swallowed) | `<os>/campaigns/<cid>/evidence/<stage>.json` |
| Signatures | `signature.create` events | escalation, plan and generic signature routes | step-up; hash length 64 | `<rr>/audit.jsonl` (+ Postgres in production) |
| S6 | sensitivity ranking, prediction intervals | `evaluate_s6` | - | `<os>/campaigns/<cid>/s6/s6.json` (VBE only in `evidence/S6.json`) |
| S7 | bundle, re-run outputs, `.pksim5`, MAR, zip | `finish_package` | 1e-6 table comparison; MAR lint | `<os>/campaigns/<cid>/package/` |
| Memo | key → manifest + outputs | `MemoEngine` | outputs re-hashed before reuse | `<rr>/memo/<k[:2]>/<key>.json` |
| Leaves the system | `package.zip`, `mar.md/.docx/.pdf` | download routes | path must resolve under the object-store root; no integrity re-check | browser |

## 2. Data dictionary (core records)

### 2.1 `CampaignRequest` (`packages/run-contracts/src/modeler_contracts/runs.py:200-221`)
| Field | Type | Meaning |
|---|---|---|
| campaign_id, tenant_id, compound, map_id | str | identity |
| cpf_uri, cpf_sha256 | str | starting CPF (hash supplied by the client, not re-checked) |
| map_uri, map_sha256 | str | signed MAP (`map_sha256` never set by the start route) |
| observed_uri, observed_sha256 | str | observed PK (`observed_sha256` never set) |
| system_uri, system_sha256 | str | model system, "" for one compound |
| stages | list[str] | default S0, S1, S2, S3, SM, SJ, S4, S5, S6, S7 |
| stage_budgets_seconds | dict | development only |
| max_rounds_per_stage | int | 4 |
| seed | int | 1 |
| signature_timeout_days | int | 14 (Temporal) |
| cycle | int | feedback cycle, 1 first |

### 2.2 `CampaignRecord` (monitor read model, `packages/storage/src/modeler_storage/records.py:128-165`)
`id, project, compound, question, modelRisk, internalTargetPe?, budgetSeconds, elapsedSeconds, currentStage, status`
(QUEUED, RUNNING, ESCALATED, AWAITING_SIGNATURE, ABORTED, COMPLETED), `stages[]` (`stage, label, status, rounds[],
notes[]`), `gof[]`, `gofByStage{}`, `prediction`, `package`, `engine {kind, command}`, `deployment`,
`observedOrigins{}`, `realData{}`, `ledger {entries, verdicts, current}`, `influence`, `cycle`, `feedback[]`,
`feedbackPending`, `resume {request, cpf_uri, cpf_sha256, completed_stages, escalated_stage, feedback?}`.

Round row (`RoundRecord`): `round, action, aucGmfe, cmaxGmfe, verdict, studies[], groups[], vpc{}, findings[],
realData, modelSet {id, stage, cpf_sha256, engine, scenario_set_sha256, builder_version}, cycle`.

### 2.3 `EscalationRecord` (`records.py:166-`)
`id` (`<campaign>-<stage>`), `campaignId, stage, reasonCode` (e.g. S0_NOT_READY, BUDGET_EXHAUSTED, ROUNDS_EXHAUSTED,
VPC_COVERAGE_BELOW_80, REGRESSION, STAGE_FAILED, INTERNAL_VALIDATION_FAILED, EXTERNAL_VALIDATION_FAILED,
SIGNATURE_REQUIRED, PACKAGE_NOT_REPRODUCIBLE), `evidence`, `options[] {id, label, requiresSignature, disabled?}`,
`feedback?`.

### 2.4 `EngineJob` / `EngineManifest` (`runs.py:20-60`)
Job: `job_id, tenant_id, task, inputs[{name, uri, sha256}], outputs_uri, options, timeout_s (600)`.
Manifest: `job_id, status (SUCCEEDED | CANCELLED), outputs[{name, uri, sha256, size}], warnings[], engine_info{},
stderr_tail`. Failures raise instead of returning a status.

### 2.5 CPF parameter record (`packages/pbpk-domain/src/pbpk_domain/cpf/models.py:145-261`)
`id` (registry id, e.g. `phys.mw`, `elim.hepatic.<enzyme>.clspec`, `form.<name>.weibull_t50`), `value, unit` (storage
unit), `status` (FIXED, PREDICTED, FITTED, DERIVED…), `fitted_at_stage`, `fit_policy {stages, lower, upper, scale}`,
`plausibility {lower, upper}`, `provenance {source_type, reference, run, supersedes…}`, `engine_binding`,
`uncertainty {sd, cv_percent, ci95_lower, ci95_upper}`. CPF: `compound, version, parameters[], groups[], note,
created_at`.

### 2.6 MAP (`packages/pbpk-domain/src/pbpk_domain/campaign/map.py:335-414`)
`version, status (DRAFT | SIGNED), signature {printed_name, meaning, signed_at, signature_id, content_sha256},
supersedes_sha256, model_risk, cpf_parameters[] (value, unit, grade, bounds, plausibility), studies[] (assignment
INTERNAL/EXTERNAL/SUPPORTIVE, class), split_rationale[], split_limitations[], stage_plan[] (stage, fit_candidates,
branches, max_rounds, budget_seconds), scenarios[] (study_id, stage, route, dose, formulation, food_state, population,
sex, analyte, gated…), acceptance (ruleset snapshot, internal_target_pe), applications[], risk_assessment, seeds,
engine_image_digest, software_versions`.

### 2.7 Bundle manifest (`packages/pbpk-domain/src/pbpk_domain/reproducibility.py:35-47`)
`bundle_id, campaign, files[{path, sha256, size_bytes, numeric}], engine_image_digest, software_versions, created_at`;
`content_sha256` = SHA-256 over sorted `path:sha:size:numeric` lines.

### 2.8 Audit event (`modeler_project/audit.py`, `modeler_storage/audit.py`)
`tenant_id, seq, occurred_at, actor, action, resource_type, resource_id, before, after, reason, request_id, prev_hash,
row_hash`; `row_hash = SHA-256(prev_hash | canonical JSON)`, genesis 64 zeros.

## 3. PostgreSQL schema (`services/api/migrations/*.sql`)

| Table | Purpose | Integrity | Used today |
|---|---|---|---|
| tenants, users | identity | RLS on `app.tenant_id` | production |
| engine_images | qualified image registry (BUILT / QUALIFIED / RETIRED) | digest unique | no rows written (CI uploads an artifact instead) |
| model_versions, parameter_provenance, runs | model and run registry; memo index on runs | immutable trigger on model_versions | no (file stores used) |
| signatures | Part 11 signature rows (meaning ∈ Authored/Reviewed/Approved/QA Released) | append-only trigger; UPDATE/DELETE/TRUNCATE revoked | production copy |
| audit_events | Part 11 audit copy (seq, prev_hash, row_hash) | append-only trigger incl. TRUNCATE | production copy |
| campaigns, campaign_stages, campaign_rounds, escalations, deviations | Temporal `CampaignStore` | RLS forced; rounds and deviations append-only | no (Temporal not deployed) |
| agent_runs, agent_steps, proposals | agents | steps append-only | pre-MAP |

Mismatch: `campaigns.status` allows RUNNING/COMPLETED/ESCALATED/REJECTED and `campaign_stages.status` lacks SKIPPED,
while the application uses QUEUED, AWAITING_SIGNATURE, ABORTED and SKIPPED (`0002_campaigns.sql`; `runs.py:197`).

## 4. Transformations along the way

1. **CPF → snapshot:** per scenario an individual (population, sex, age, weight/height or the published individual),
   a protocol (IV bolus/infusion, oral, multiple dose, phases), a formulation (Dissolved, Weibull, Particles, bins), meal
   events, process selections `{Molecule}-{DataSource}`, expression profiles (CPF's own or the harvested library of 40
   molecules), outputs (plasma per compound) (`cpf/build.py`, `snapshot/builder.py`).
2. **Engine CSV → `profiles.json`:** first individual only; plasma column by path prefix; every selected peripheral
   venous output kept with its unit (`run_job.R:67-138`).
3. **Profiles + observed → PK:** prediction read at the observed sampling times, NCA (lin-up/log-down from the first
   sample, adjusted-R² terminal phase), comparisons pred/obs (`campaign/evaluate.py`, `nca.py`).
4. **Units:** observed profiles stored in minutes and µmol/l; PI bounds and estimates converted to PK-Sim base units in
   R and back (`units.py`; `run_pi.R:301-387`).
5. **Fit → CPF:** best start's estimates and Hessian CI into a new CPF version; other compounds' estimates into their
   own CPF in the system document (`campaign_activities.py:619-671`).
6. **Evidence → MAR:** prose numbers are `{{value:id}}` tokens resolved from evidence values at render time; table
   cells taken from stage metrics, the CPF, S6 and the ledger (`report/mar.py`, `campaign_mar.py`).

## 5. Retention, backup and size

- `~/modeler-data` (every campaign record, CPF version, snapshot, engine output, evidence and package) is **not backed
  up**; the nightly job dumps only PostgreSQL to the same disk, kept 14 days (`deploy/server/postgres.sh:148-161`).
- No retention policy or disk guard for campaign outputs (ENGINEERING_PLAN §8.4 asks for one); the server's root disk
  was reported 95 % full.
- `campaigns.json` holds every campaign of a tenant with its GOF series, VPC bands and ledger, and is rewritten whole
  on each of 18 flush points (`filestore.py:142-175`; `local_runner.py`). Reads load the whole file per request.

## 6. Data-integrity observations

| Strength | Weakness |
|---|---|
| sha256 on every engine input, checked in Python and again in R | the client-supplied `cpf_sha256` is never recomputed; MAP and observed hashes are not set |
| CPF versions are immutable files with provenance and the fit's CI | a fit is applied without checking that it improved the model |
| Model set id ties each verdict to CPF hash, engine key, scenarios and builder version | builder version is the package version, so builder changes within one version are indistinguishable |
| Memo reuse re-hashes recorded outputs | memo key ignores the engine scripts' content |
| Audit chain detects edited lines | tail truncation of `audit.jsonl` goes undetected; campaign events are not audited |
| S7 compares every result table at 1e-6 | `abs_tol=1e-6` lets percent-level differences pass at low µmol/l concentrations; S6 numbers are not re-run |
