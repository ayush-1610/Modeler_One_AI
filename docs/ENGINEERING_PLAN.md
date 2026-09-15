# Modeler One — Product Engineering Plan

**v1.0 · 2026-09-15 · supersedes the architecture pack (v0.2) where they differ.**
Companion documents: [PBPK_MODELING_WORKFLOW.md](PBPK_MODELING_WORKFLOW.md) (the scientific loop, MS-01),
[WORKFLOW_AND_AUTOMATION.md](WORKFLOW_AND_AUTOMATION.md) (plain-English walkthrough),
[CONTINUATION_PACKAGE.md](CONTINUATION_PACKAGE.md) (ordered handoff tasks T-xx referenced below),
[ARCHITECTURE_PACK.md](ARCHITECTURE_PACK.md) (domain map, feature catalog, agents, roadmap detail).

Tier labels: **FINALIZED** = decided in this session; do not reopen without a recorded reason.
**HANDOFF: SONNET/OPUS → T-xx** = implementation task described in the Continuation Package.
**[SME]** = a scientific default that is versioned data and needs PBPK/QA sign-off; it never blocks engineering.

---

## 0. Gap analysis of the current state (what changes and why)

| # | Gap found | Consequence if left | Decision in this plan |
|---|---|---|---|
| G1 | Auth is a placeholder header; no RBAC, no step-up for signatures | Part 11 §11.10(d)/(g), §11.200 unmet; unusable beyond a laptop | §6: Keycloak OIDC, realm roles + project membership, step-up (`acr=loa2`, fresh `auth_time`) for signatures |
| G2 | No persistence layer (SQL DDL exists, no ORM/repositories, no run/result ingestion) | Nothing survives a process restart; audit chain never written | §5 data model finalized; T-05..T-08 build repositories, results ingestion (CSV → Parquet + PK rows), audit on every write |
| G3 | Engine worker uses `file://` object store; engine has no credentials story | Cannot run on 3 servers; secrets sprawl | §7: MinIO with per-job presigned URLs (write-only, 2 h expiry) issued by the orchestrator; engine pods have no long-lived credentials |
| G4 | Fitting workflow cancels activities at the deadline but the worker never observes cancellation | R keeps computing past the deadline; cores stay busy | §8.4: runner polls `activity.is_cancelled()` in the heartbeat loop and kills the process group; activities are cancellable by design |
| G5 | Snapshot builder covers first-order metabolism and GFR only; no CPF layer; stages would write simulation overrides | "All models on one parameter framework" not enforceable; DDI/population models impossible | §4.2 CPF is the system of record; builder regenerates all simulations from it; T-10..T-12 extend process/formulation/population coverage from the engine catalog harvest |
| G6 | No modeling campaign orchestration (stages, rounds, diagnostics, escalations) | The core promise (loop-based automation) not implemented | §4.3 `ModelingCampaignWorkflow` state machine; T-13..T-17 |
| G7 | Acceptance and DDI rulesets are UNVERIFIED | GxP use blocked | Kept as data with `status`; campaigns on UNVERIFIED rulesets are allowed only in projects flagged `exploratory`; T-30 SME sign-off |
| G8 | Observed-data conversion supports plasma/mass units only; LLOQ encoding in PK-Sim unverified | Urine/feces mass balance and molar data unusable | T-11 verifies with the engine (golden test) and extends matrices/units; until then the converter rejects, never guesses |
| G9 | Agents have no persisted `agent_runs/agent_steps`, no evals, no token budgets enforced | Not auditable; quality unmeasured | §5.6 tables; §11.6 eval sets; T-20..T-22 |
| G10 | No CI, no image signing, no SBOM, no validation evidence capture | Not validatable (GAMP 5); supply-chain risk | §9.5 CI pipeline with cosign + Syft; pytest markers `req("F-xxx")` → trace matrix; T-25 |
| G11 | Root disk on servers at 93 % | Any run can fill the disk and corrupt Postgres/MinIO | §9.1: all state on `/data` (separate disk per node); disk alerts at 80/90 %; runs refuse to start below 10 GB free |
| G12 | Temporal workflow code passes `list[EngineJob]` through `asyncio.gather` and untyped activity args | Non-deterministic replay risk if payload converters change | §8.3: pydantic data converter, typed dataclasses only, workflow versioning via `workflow.patched()` |
| G13 | Web app is a starter with example rows | No user path | §3.4 screens finalized; T-26..T-28 |
| G14 | Single R process per job; PI start loads models itself | Acceptable (OSP PI keeps models warm inside a start); population and sensitivity tasks not implemented | T-09 adds `population`, `sensitivity`, `pk_analysis` tasks with `SimulationBatch` |
| G15 | No reproducibility gate, no submission bundle, no report renderer | Priority #1 (FDA-reviewable package) unmet | §4.6, T-23, T-24 |
| G16 | Literature agent depends on public MCP servers being reachable; no fallback | Research step fails silently on outages | §10: each source has a fallback (direct REST client with the same record schema) and a degraded mode (source marked unavailable in the coverage report) |

---

## 1. Architecture overview (FINALIZED)

```
                       ┌──────────────────────────── control plane ────────────────────────────┐
  Browser ──TLS──► Traefik ──► Keycloak (OIDC)                                                   │
                    │                                                                            │
                    └──► API (FastAPI) ──► PostgreSQL 16 (CloudNativePG, 1 primary + 2 replicas)  │
                          │  │  │        MinIO (Object Lock, versioned)                         │
                          │  │  └──────► Temporal (self-hosted, own DB in the same PG cluster)  │
                          │  └── SSE ───► Browser                                                │
                          └── presigned URLs ──► MinIO                                           │
                                                                                                 │
  Orchestrator workers (Python, Temporal task queue `orchestrator`)                              │
     ModelingCampaignWorkflow → StageLoopWorkflow → FitRoundWorkflow / SimulationRunWorkflow      │
     activities: plan, ingest results, evaluate, diagnose, notify, render                        │
                                                                                                 │
  Agent workers (task queue `agents`) ──► Claude (Anthropic API now; Bedrock/Vertex/self-hosted) │
     ──► MCP servers (BioMCP, ChEMBL, PubChem) inside the cluster; allowlisted tools              │
  ─────────────────────────────────────── engine plane (no egress) ───────────────────────────── │
  Engine workers (task queues engine-s/m/l), image modeler-engine:<digest>                       │
     R + ospsuite 12.4.4 + PK-Sim 12.3.173 + .NET 8; run_job.R, run_pi.R; presigned MinIO I/O    │
```

**Runtime:** k3s on the three Ubuntu 24.04 servers (§9). **Language split:** Python 3.12 for everything but the engine
scripts (R) and the web app (TypeScript). **System of record:** PostgreSQL rows + MinIO objects, both hashed; Temporal
holds workflow state only (rebuildable from rows).

---

## 2. Component breakdown (FINALIZED)

| Component | Package / service | Responsibility | Owns data |
|---|---|---|---|
| Domain library | `packages/pbpk-domain` | CPF, snapshot models/builder/validation/transfer, metrics, acceptance, fitting planner and assessment, diagnostics rules, split algorithm, M15 rules, VBE/DDI statistics. Pure, deterministic, versioned | none |
| Intake library | `packages/data-intake` | Raw vault, grids, recipes, apply/validate, PK-Sim observed-data conversion | none |
| Contracts | `packages/run-contracts` | Dataclasses crossing process boundaries | none |
| API | `services/api` | REST v1, auth, tenancy, repositories, audit, signatures, SSE, presigned URLs, exports | PostgreSQL, MinIO |
| Orchestrator | `services/orchestrator` | Temporal workflows and platform activities (campaign, stages, rounds, runs, evaluation, reporting) | Temporal namespace `modeler` |
| Engine worker | `services/engine-worker` | Engine image, `run_job.R` tasks, integrity checks, heartbeats, cancellation | scratch only |
| Agents | `services/agents` | Data mapping, literature research, curation, strategist, evaluation interpreter, report drafter, QC; MCP client layer | `agent_runs/steps`, `retrieved_records` (via API) |
| Web | `apps/web` | Next.js app: workspace, campaign monitor, review inbox, M15/MAP/MAR editors, audit viewer | none (API only) |
| MCP servers | Helm subcharts | BioMCP, ChEMBL, PubChem, pinned versions, no egress except their upstreams | cache only |
| Platform services | Helm | Keycloak, CloudNativePG, MinIO, Temporal, kube-prometheus-stack, Loki, Tempo, Argo CD, KEDA | – |

---

## 3. User flows and screens (FINALIZED)

1. **Project setup:** create project → compound (name, structure) → question(s) of interest → M15 planning rows → upload documents/data.
2. **Data intake:** upload file → grid preview → agent mapping proposal → reviewer confirms → records + validation report → observed data ready.
3. **Parameterization:** literature research run → proposals inbox → curator accepts/rejects → CPF populated with provenance → completeness report.
4. **Campaign:** MAP generated from MS-01 (split table, stage plan, criteria) → MIDD lead signs → campaign runs → live stage/round monitor with metrics and plots → escalations appear in the review inbox with the decision options from MS-01 → final CPF accepted → S4/S5 signed.
5. **Applications:** template runs (DDI, pediatrics, …) → results → M15 submission rows.
6. **Reporting:** MAR draft → edits → signatures (author, reviewer, QA) → reproducibility gate → bundle download.
7. **Audit:** audit viewer with filters; export for inspection.

Screens (web): Projects · Compound & CPF (table with provenance chips, completeness) · Documents & proposals inbox ·
Data intake (grid + mapping side by side) · Studies (class, score, split) · Campaign monitor (stage timeline, round
table, GOF/VPC plots, escalation cards) · Review inbox (signatures, escalations, deviations) · Applications ·
M15 table editor · MAP/MAR editor · Audit viewer · Admin (users, engine images, rulesets).

---

## 4. Core mechanisms (FINALIZED)

### 4.1 Identity and hashing
- Every stored artifact has a SHA-256; snapshots use canonical JSON (sorted keys, compact) for the hash and PK-Sim
  key order for the engine file.
- Runs are memoized on `(snapshot_sha256, engine_digest, task, options_hash, seed)`.
- IDs: ULIDs (`01J…`) for all rows except append-only sequences.

### 4.2 Compound Parameter Framework (CPF)
JSON document per compound version (`cpf_versions.document`), schema in MS-01 §2. The snapshot builder consumes a CPF
plus a scenario list and emits one snapshot; simulation-level overrides are written only by the parameter-transfer step
and only with `ParameterIdentification` provenance. Engine binding table is generated per engine image by the catalog
harvest (T-12) and stored with the image; a CPF parameter with no binding for the pinned engine is a build error.

### 4.3 Modeling campaign state machine
```
CREATED → MAP_SIGNED → S1 → S2 → S3 → S4 → S5 → S6 → S7 → COMPLETED
 any stage: RUNNING ⇄ ESCALATED (human decision) → RUNNING | ABANDONED
 S5 fail → DEVIATION_PENDING → (path 6.6) → S1..S3 partial rerun → S4 → S5
```
`ModelingCampaignWorkflow` (Temporal) holds the state; each stage is a child `StageLoopWorkflow` producing
`campaign_rounds` rows via activities; each fitting round is a child `FitRoundWorkflow` (exists). Human decisions arrive
as Temporal signals carrying the signature or decision record ID (never free text).

### 4.4 Deterministic core / advisory edge
Only code computes numbers, verdicts and permitted actions. Agents return structured proposals validated against the
permitted set; a proposal outside it is rejected and logged, and the loop falls back to the first permitted action.

### 4.5 Time budget
Campaign budget → stage budgets (MS-01 §7) → `plan_multistart` per round using `engine_benchmarks.seconds_per_simulation`
for the pinned image on the cluster's node class. A round is started only if its estimate fits; at the stage deadline
running starts are cancelled (§8.4).

### 4.6 Reproducibility gate and bundle
Bundle = manifest.json (every file with SHA-256, engine digest, seeds, software versions) + snapshots + pkml + results
Parquet/CSV + observed data + raw client files + CPF versions + fit specs/results + evaluation tables/figures + MAP +
MAR + M15 table + signatures + `rerun_all.R`. Gate: a fresh engine pod re-runs `rerun_all.R` on the bundle, PK tables
must match within 1e-6 relative (solver determinism) and result file hashes must match; otherwise export is refused
with the diff.

---

## 5. Data model (FINALIZED)

PostgreSQL 16. All tenant-owned tables carry `tenant_id` with RLS as in `services/api/migrations/0001_core.sql`.
Append-only tables: `audit_events`, `signatures`, `agent_steps`, `campaign_rounds`, `fit_starts`, `deviations`.
Migrations: Alembic with hand-written SQL (never autogenerate for compliance tables).

### 5.1 Core
```sql
tenants(id, slug, tenancy_mode, created_at)
users(id, tenant_id, oidc_subject, printed_name, email, active, created_at)
projects(id, tenant_id, name, sponsor, regulator[] , exploratory bool, retention_until, created_at)
project_members(project_id, user_id, role)            -- role ∈ {owner, modeler, reviewer, curator, qa, viewer}
compounds(id, tenant_id, project_id, name, inchikey, smiles, created_at)
questions_of_interest(id, project_id, compound_id, text, application_template_id, template_version, status)
```
### 5.2 Parameters and models
```sql
cpf_versions(id, compound_id, version int, document jsonb, sha256, parent_id, created_by, created_at, reason)
parameter_provenance(…as existing…, cpf_version_id, parameter_id text)     -- one row per CPF parameter value
engine_images(id, digest, engine_id, snapshot_versions int[], status, qualified_contexts text[], catalog jsonb,
              benchmark jsonb, qualification_report_id, created_at)
model_versions(…as existing…, cpf_version_id, scenario_set jsonb)          -- generated snapshot per campaign round
```
### 5.3 Data
```sql
documents(id, tenant_id, project_id, sha256, original_name, media_type, size_bytes, kind, uploaded_by, uploaded_at)
   -- kind ∈ {client_data, literature, regulatory, retrieved_record}
document_pages(document_id, page int, text, PRIMARY KEY(document_id, page))
mapping_recipes(id, project_id, recipe_id, version, document jsonb, fingerprints jsonb, confirmed_by, confirmed_at)
studies(id, project_id, compound_id, study_id, reference_document_id, class, population jsonb, design jsonb,
        route, dose, dose_unit, formulation, food_state, statistic, n, lloq, matrices text[], flags text[],
        information_score numeric, split text CHECK (split IN ('INTERNAL','EXTERNAL','SUPPORTIVE','UNASSIGNED')))
observations(id bigserial, study_id, series, matrix, time, time_unit, value, unit, below_lloq, lloq, sd, n,
             source jsonb)  PARTITION BY HASH(study_id)
dissolution_profiles(id, project_id, batch, medium, ph, apparatus, rpm, vessel, time, time_unit, percent, source jsonb)
```
### 5.4 Campaigns and runs
```sql
campaigns(id, question_id, cpf_version_start, engine_image_id, map_id, budget_seconds, seed, status, current_stage,
          started_at, finished_at, final_cpf_version_id)
campaign_stages(id, campaign_id, stage text, status, budget_seconds, max_rounds, started_at, finished_at, summary jsonb)
campaign_rounds(id, stage_id, round int, cpf_before, cpf_after, action jsonb, diagnostics jsonb, metrics jsonb,
                verdict text, model_version_id, started_at, finished_at)              -- append-only
fit_starts(id, round_id, start_index, spec_sha256, result jsonb, status, manifest_key)  -- append-only
runs(…as existing…, round_id nullable, purpose text)                                    -- purpose ∈ {fit, evaluate, validate, application, gate}
run_results(run_id, output_path, parquet_key, n_rows, sha256)
pk_parameter_values(…as existing…)
evaluations(id, campaign_id, stage, role text, ruleset text, tier text, verdicts jsonb, groups jsonb, passes bool, signed_by)
escalations(id, campaign_id, stage_id, round_id, reason_code, evidence jsonb, options jsonb, decision jsonb,
            decided_by, decided_at)
deviations(id, campaign_id, map_id, kind, rationale, decided_by, signature_id)          -- append-only
```
### 5.5 Regulatory documents
```sql
maps(id, question_id, version, document jsonb, sha256, status)     -- generated from MS-01 + edits
mars(id, question_id, version, sections jsonb, sha256, status)
m15_tables(…as existing…)
signatures(…as existing…)
audit_events(…as existing…)
bundles(id, question_id, manifest jsonb, object_key, reproducibility jsonb, exported_by, exported_at)
```
### 5.6 Agents
```sql
agent_runs(id, tenant_id, project_id, agent, model, prompt_version, tool_schema_version, provider, status,
           input jsonb, output jsonb, token_input, token_output, cost_usd, started_at, finished_at)
agent_steps(id bigserial, run_id, seq, kind, content jsonb, created_at)            -- append-only
proposals(id, run_id, kind, payload jsonb, state, decided_by, decided_at, reason)  -- parameter, mapping, study, text
access_requests(id, project_id, title, authors, doi, journal, year, needed_for, status, fulfilled_document_id)
```
Retention: rows are never deleted; `projects.retention_until` drives an archival export, then a legal-hold check, then
tenant-level purge by a separate signed procedure (not part of v1).

---

## 6. Security and auth model (FINALIZED)

- **Identity provider:** Keycloak 26, realm `modeler`, OIDC Authorization Code + PKCE for the web app, client
  credentials for services. Realm roles: `platform_admin`, `qa`, `midd_lead`, `modeler`, `reviewer`, `curator`,
  `viewer`. Project membership (`project_members.role`) gates data access; realm roles gate global actions.
- **Token validation:** API validates RS256 JWT against cached JWKS (refresh 10 min, hard fail on unknown `kid`).
  `tenant_id` comes from a realm attribute mapped into the token, never from headers.
- **Step-up for signatures (11.200, 11.50, 11.70):** Keycloak flow `signing` requires password + TOTP and returns
  `acr = "loa2"`. `POST /signatures` requires a token with `acr == loa2` and `auth_time` within 300 s, and the signature
  row stores `printed_name`, UTC time, meaning, record hash. A token without those is a 403 `STEP_UP_REQUIRED`.
- **Authorization matrix (excerpt):**

| Action | Roles |
|---|---|
| Upload data, confirm mapping | modeler, curator |
| Accept parameter proposals | curator, modeler |
| Sign MAP (Authored) / (Approved) | modeler / midd_lead |
| Decide escalations, deviations | modeler (proposes), reviewer (approves) |
| Sign evaluation (Reviewed) | reviewer |
| QA release | qa |
| Manage engine images, rulesets | platform_admin (+ qa signature for QUALIFIED) |

- **Service-to-service:** in-cluster mTLS via Linkerd is *not* adopted in v1 (complexity); NetworkPolicies isolate
  namespaces; Temporal runs with TLS between workers and frontend using cluster-issued certs (cert-manager).
- **Engine plane:** NetworkPolicy denies all egress except MinIO and Temporal; pods run as UID 10001, read-only root
  FS, `emptyDir` scratch with size limit, seccomp `RuntimeDefault`. Engine pods receive **presigned MinIO URLs** for
  their inputs (GET) and outputs (PUT) valid 2 h; no static credentials.
- **Secrets:** SOPS (age) encrypted manifests in git, decrypted by Argo CD's KSOPS plugin; rotation quarterly; LLM
  API keys per tenant in a `Secret` mounted only into agent workers.
- **Data protection:** TLS 1.2+ everywhere; MinIO SSE-S3 with per-tenant KMS keys (MinIO KES) from Phase 2; Postgres
  at-rest encryption via LUKS on `/data`.
- **Prompt injection:** document and tool text is data; agents' tools are read-only except proposal tools; proposals
  are validated; agents cannot call platform write endpoints.
- **Audit:** every write path goes through `append_audit_event` in the same transaction (`services/api/src/modeler_api/compliance/audit.py`).

---

## 7. API design (FINALIZED contracts; implementation HANDOFF)

Base `/api/v1`, JSON, envelope `{data, meta{request_id, timestamp, api_version}, errors[{code, message, location?}]}`.
Errors: 400 malformed, 401 unauthenticated, 403 `FORBIDDEN|STEP_UP_REQUIRED`, 404, 409 conflict/idempotency replay
mismatch, 422 domain validation (issue list), 423 `RECORD_LOCKED`, 429 rate limit, 503 `DEPENDENCY_UNAVAILABLE`
(Temporal/MinIO/engine pool). All POSTs that create runs, campaigns, signatures or exports require
`Idempotency-Key` (UUID); replays return the original response for 24 h. Pagination: cursor (`?after=&limit=`).
Long operations return 202 with `{id, status_url, events_url}`; events via SSE `text/event-stream` with
`event: status|round|escalation|log`, `id:` monotonic, resumable with `Last-Event-ID`.

| Method & path | Purpose | Notes |
|---|---|---|
| `POST /projects`, `GET /projects/{id}` | project lifecycle | |
| `POST /projects/{id}/compounds` | create compound (name, SMILES) | RDKit derives MW/InChIKey; stored as CPF `phys.mw` PREDICTED-from-structure |
| `GET/PUT /compounds/{id}/cpf` | read/update CPF (creates a new `cpf_versions` row) | PUT body = full CPF; server validates schema, units, bindings for the project's engine; returns completeness report |
| `POST /documents` (multipart) | vault upload | returns `sha256`; duplicate returns existing |
| `POST /documents/{sha}/grid` | parse spreadsheet grid | returns sheet previews |
| `POST /documents/{sha}/mapping-proposals` | run Data Mapping agent | 202; result = review (recipe, records, issues, questions) |
| `POST /mapping-recipes/{id}/confirm` | confirm recipe | requires reviewer answers to open questions |
| `POST /documents/{sha}/apply-recipe/{recipe_id}` | produce studies/observations | 422 with issues if validation fails |
| `GET /projects/{id}/studies` · `PATCH /studies/{id}` | catalog, manual metadata fixes | split field is read-only; set by campaign planning |
| `POST /questions/{id}/map:generate` | build MAP from MS-01 | returns MAP document with split table, stage plan, criteria |
| `POST /questions/{id}/campaigns` | create campaign from a signed MAP | 409 if MAP unsigned; body `{map_id, engine_image_id, budget_seconds}` |
| `POST /campaigns/{id}:start` · `GET /campaigns/{id}` · `GET /campaigns/{id}/events` (SSE) | run and monitor | |
| `GET /campaigns/{id}/rounds` · `GET /rounds/{id}` | round records with metrics, diagnostics, action | |
| `GET /escalations?status=open` · `POST /escalations/{id}:decide` | human decisions | body `{option_id, rationale, signature_id?}`; options are those MS-01 lists |
| `POST /campaigns/{id}/deviations` | MAP deviation | body `{kind, rationale}`; requires reviewer signature |
| `POST /runs` · `GET /runs/{id}` · `GET /runs/{id}/results?output=&format=arrow\|csv` | ad-hoc runs | memoized |
| `GET /evaluations/{id}` | acceptance table, plots (Plotly JSON + SVG keys) | |
| `POST /questions/{id}/applications` | run an application template | 202 |
| `GET/PUT /questions/{id}/m15-table` | M15 table | validation via `pbpk_domain.m15` |
| `GET/PUT /questions/{id}/mar` | MAR sections | numbers are references to evaluation/run IDs, rendered server-side |
| `POST /signatures` | e-signature | `{record_type, record_id, meaning}`; token must be loa2 + fresh |
| `POST /questions/{id}/bundles` · `GET /bundles/{id}` | build/export package | 202; reproducibility gate result in `reproducibility` |
| `GET /audit-events?resource_type=&resource_id=&after=` | audit review | export as CSV/JSON |
| `POST /agent-runs` · `GET /agent-runs/{id}` · `GET /proposals?state=PROPOSED` · `POST /proposals/{id}:decide` | agents | |
| `GET /engine-images` · `POST /engine-images/{id}:qualify` | admin | qualify requires qa signature |

Example, campaign creation response:
```json
{"data": {"id": "01J9…", "status": "CREATED", "map_id": "01J8…", "engine_image": {"digest": "sha256:…", "engine_id": "ospsuite-12.4.4"},
          "budget_seconds": 3600, "planned_stages": ["S1","S2","S3","S4","S5","S6","S7"],
          "runtime_estimate_seconds": 2280, "status_url": "/api/v1/campaigns/01J9…", "events_url": "/api/v1/campaigns/01J9…/events"},
 "meta": {"request_id": "…", "timestamp": "…", "api_version": "1"}, "errors": []}
```

---

## 8. Orchestration and engine (FINALIZED)

### 8.1 Temporal
Self-hosted Temporal 1.x (Helm), namespace `modeler`, persistence in the CNPG cluster (databases `temporal`,
`temporal_visibility`). Task queues: `orchestrator`, `agents`, `engine-s` (1 vCPU/2 GiB), `engine-m` (4 vCPU/8 GiB),
`engine-l` (16 vCPU/32 GiB). Data converter: pydantic JSON converter; all payloads are dataclasses/pydantic models
from `modeler_contracts`. Workflow code changes use `workflow.patched("<id>")`; retired patches are removed after
all open workflows of the old version finish (tracked by a weekly report).

### 8.2 Workflows
- `ModelingCampaignWorkflow(campaign_id)`: loads campaign, iterates stages per MS-01, waits on signals
  `map_signed`, `escalation_decided(id)`, `deviation_recorded(id)`, `accept_final_cpf(signature_id)`.
  Continue-as-new after each stage (history size control).
- `StageLoopWorkflow(campaign_id, stage)`: rounds loop; activities `build_round_snapshot`, `run_round` (fan-out of
  `SimulationRunWorkflow` per study or `FitRoundWorkflow`), `evaluate_round`, `diagnose_round`, `choose_action`
  (agent, timeout 120 s, fallback to first permitted action), `record_round`.
- `FitRoundWorkflow` (exists), `SimulationRunWorkflow` (exists), `PopulationRunWorkflow` (exists),
  `ApplicationWorkflow(template)`, `ReportWorkflow`, `BundleWorkflow` (includes the reproducibility gate),
  `EngineQualificationWorkflow`.

### 8.3 Activity contracts
Every activity is idempotent on its inputs; every result is persisted before the activity returns; activities that
write rows do so with the run/round ID as idempotency key. Retries: platform activities 3× exponential; engine
activities: infrastructure errors retried once on a different node (`ApplicationError` non-retryable for
`InputIntegrityError`, `EngineError`, `EngineTimeout`).

### 8.4 Engine worker behaviour
- Inputs are fetched via presigned GET, hashed and compared; mismatch → `InputIntegrityError` (non-retryable).
- Process group runs with `setsid`; the heartbeat loop (every 15 s) calls `activity.is_cancelled()`; on cancellation
  the process group receives SIGTERM, then SIGKILL after 20 s; partial outputs are uploaded under `cancelled/` and the
  manifest status is `CANCELLED`.
- Wall-clock timeout per task (`EngineJob.timeout_s`) enforced by the runner; Temporal `start_to_close` is
  timeout + 5 min.
- Outputs are hashed and uploaded via presigned PUT; `engine_manifest.json` is always written, even on failure.
- Resource limits: cgroup CPU/memory via pod spec; `OMP_NUM_THREADS=1` inside R except for `SimulationBatch`
  parallelism, which is set to the pod's CPU request.
- Disk guard: refuse to start when the scratch volume has < 2 GiB free.

### 8.5 Engine image lifecycle
Build (CI) → golden tests inside the image (`golden_roundtrip.R`, `pi_smoke.R`, benchmark) → SBOM + cosign sign →
push by digest → `engine_images` row `BUILT` → qualification workflow (OSP qualification sets + cross-version
comparison) → QA signature → `QUALIFIED` with contexts. Projects pin a digest; changing it is a deviation.

---

## 9. Infrastructure and deployment (FINALIZED)

### 9.1 Target: three on-prem Ubuntu 24.04 servers
- **Prerequisite:** each node gets a data disk mounted at `/data` (≥ 1 TB recommended); k3s data dir, container
  images, PV storage (Longhorn or local-path on `/data`), MinIO and Postgres volumes all live there. Nothing writes to
  the root disk. Alert at 80 %, page at 90 %; campaigns refuse to start below 10 % free.
- **Kubernetes:** k3s (3 servers, embedded etcd HA, Traefik ingress, local-path storage on `/data`; Longhorn from
  Phase 2 for replicated PVs). Node labels: `modeler.io/role=control+engine` on all three (control plane is light).
- **Decision tree:** team without Kubernetes experience → Phase 0 on Docker Compose on server 1 (existing
  `docker-compose.yml`), migrate to k3s in Phase 1 with the same images and Helm values. Team with experience →
  k3s from day one.
- **Data services:** CloudNativePG (3 instances, synchronous replica, WAL archiving to MinIO, PITR 30 days);
  MinIO: Phase 0 single node on `/data` with versioning + Object Lock (compliance mode, retention per tenant policy),
  Phase 2 distributed 3 nodes (needs ≥ 2 drives per node); nightly `mc mirror` to an off-node backup target.
- **Scaling:** engine Deployments per resource class; KEDA Temporal scaler on task-queue backlog; max replicas per
  node class computed from physical cores (24 per server): `engine-s` up to 36, `engine-m` up to 5, `engine-l` 1.
- **GitOps:** Argo CD applies the `deploy/` Helm umbrella per environment (`values-onprem.yaml`, `values-dev.yaml`);
  images referenced by digest; SOPS for secrets.
- **Environments:** `dev` (compose), `staging` (namespace on the cluster), `prod` (namespace); staging is a validated
  copy used for qualification runs and validation evidence.

### 9.2 Backups and DR
Postgres PITR (RPO 15 min, RTO 4 h); MinIO versioned buckets mirrored nightly and on export; quarterly restore drill
recorded as validation evidence; Temporal state is rebuildable (campaigns can be resumed from rows: `resume_campaign`
activity reconstructs stage/round from the DB).

### 9.3 Image and dependency pinning
Base images by digest; R packages from a dated r-universe snapshot (`OSP_LINUX_BINARIES` + `renv.lock` recorded in the
image); Python via `uv.lock`; Node via `package-lock.json`; MCP servers pinned by version and image digest.

### 9.4 Environments variables (engine)
`LC_ALL=en_US.UTF-8`, `DOTNET_ROOT`, `LD_LIBRARY_PATH=<site-library>/ospsuite/lib`, `MODELER_ENGINE_ID`,
`MODELER_IMAGE_DIGEST`, `MODELER_RESOURCE_CLASS`, `MODELER_TEMPORAL_ADDRESS` (+ TLS certs), no object-store keys.

### 9.5 CI/CD (GitHub Actions)
`test` (uv sync, ruff, pytest with `--junitxml`, coverage ≥ 85 % on `pbpk-domain` and `data-intake`) → `web`
(typecheck, build, Playwright smoke) → `engine-image` (build amd64, run golden tests inside, benchmark, Syft SBOM,
cosign sign, push GHCR by digest, write `engine_images` candidate via API) → `services-images` → `argocd` sync on
tag. Validation evidence: JUnit + coverage + golden reports uploaded as build artifacts and attached to the release.

---

## 10. Third-party dependencies and fallbacks (FINALIZED)

| Dependency | Used for | Failure mode | Fallback / degraded behaviour |
|---|---|---|---|
| OSP ospsuite 12.4.4 / PK-Sim 12.3.173 | engine | crash, solver failure, API change | Pinned image; solver failures are run failures with logs; version change only via qualification |
| .NET 8 runtime | rSharp | missing/incompatible | Baked into image; golden test at build |
| r-universe / P3M | image build | outage | Build cache; vendored tarballs in `deploy/vendor/` refreshed monthly |
| Temporal | orchestration | unavailable | API returns 503 for run/campaign creation; running engine jobs finish and upload; workflows resume |
| PostgreSQL | records | primary down | CNPG failover (< 1 min); API read-only mode until promotion |
| MinIO | objects | unavailable | Engine jobs fail before start (no inputs) and are retried by Temporal; exports refused |
| Keycloak | auth | down | Existing tokens valid until expiry (15 min); no new logins; alert |
| Claude API (Anthropic/Bedrock/Vertex/self-hosted) | agents | outage, refusal, quota | Agent steps fail with `LLM_UNAVAILABLE`; campaign loop uses the first permitted action; intake/literature tasks queue with retry (max 6 h) |
| BioMCP / ChEMBL / PubChem MCP servers | literature | upstream API errors, rate limits | Per-source circuit breaker; direct REST fallback clients (Europe PMC, ChEMBL, PubChem PUG) with the same `retrieved_records` schema; coverage report marks sources unavailable |
| npm/GHCR/apt during build | images | outage | Mirror to internal registry (Harbor) in Phase 2; builds are not run-time dependencies |
| Plotly/AG Grid (web) | UI | CDN | Bundled, no CDN at runtime |

---

## 11. Observability and alerting (FINALIZED)

- **Tracing:** OpenTelemetry SDK in API, orchestrator, agents; Temporal interceptors propagate trace context; engine
  runs are spans with `run_id`, `campaign_id`, `stage`, `round`; exported to Tempo.
- **Metrics (Prometheus):** `engine_run_duration_seconds{task,resource_class}`, `engine_run_failures_total{class}`,
  `temporal_task_queue_backlog`, `campaign_stage_duration_seconds{stage}`, `campaign_escalations_total{reason}`,
  `fit_starts_total{status}`, `acceptance_verdicts_total{tier,role,passes}`, `agent_tokens_total{agent,provider}`,
  `agent_cost_usd_total`, `disk_free_bytes{node,mount}`, `audit_chain_verify_ok{tenant}` (nightly job).
- **Logs:** JSON to stdout → Loki; engine stderr attached to run records; PII-free (no observed data in logs).
- **Dashboards:** cluster health; campaign throughput and budget adherence (planned vs actual minutes per stage);
  engine pool utilisation; agent spend; audit integrity.
- **Alerts (Alertmanager → email/Slack):**

| Alert | Condition | Severity |
|---|---|---|
| DiskLow | `/data` free < 20 % (warn) / < 10 % (page) | warn/page |
| EngineFailureRate | > 10 % failed runs over 15 min | page |
| CampaignOverBudget | stage wall time > 1.2 × budget | warn |
| EscalationStale | escalation open > 24 h | warn |
| AuditChainBroken | nightly verify fails | page (QA + admin) |
| TemporalBacklog | backlog > 200 tasks for 10 min without scale-up | warn |
| KeycloakDown / PostgresPrimaryDown / MinioDown | probe fails 3× | page |
| AgentCostSpike | hourly cost > 3 × 7-day median | warn |
| CertExpiry | < 14 days | warn |

---

## 12. Edge cases, failure scenarios and responses (FINALIZED)

### 12.1 Intake
| Scenario | Response |
|---|---|
| `.xls`, password-protected, macros | 422 `UNSUPPORTED_FILE` with instruction to convert; macros are never executed |
| Same file uploaded twice | Vault returns the existing record; no duplicate studies (recipe application is idempotent on `(sha256, recipe_id, version)`) |
| Header fingerprint matches but data columns shifted | Validation catches non-numeric time/values → 422; reviewer re-confirms recipe (new version) |
| Values below LLOQ without stated LLOQ | `LLOQ_MISSING` blocks confirmation; question for reviewer |
| Mixed units in one column | `UNKNOWN_UNIT`/`MIXED_UNITS`; never converted silently |
| Individual and mean data both present | Recipe maps individuals only; means ignored; noted in review |
| Duplicated time points | `DUPLICATE_TIME` → reviewer must choose; no averaging |
| Figure-only data | Digitizer flow (T-19) with axis calibration and overlay check; else access/extraction request |
| Decimal comma ambiguity (`1,5` vs `1,500`) | Reject unless the recipe declares `decimal_comma`; no heuristics |
| File > 50 MB or > 200 k cells | 413 with guidance to split; grid parsing is bounded |

### 12.2 CPF and snapshot build
| Scenario | Response |
|---|---|
| Missing P0 parameter | S0 gate fails with the list; campaign not started |
| Parameter without engine binding for the pinned image | Build error `NO_ENGINE_BINDING`; admin must harvest the catalog for that image |
| Unit not the PK-Sim storage unit | 422; units are converted only by the validated unit service (OSP dimension tables) at CPF write time with both values recorded |
| Enzyme named in CPF without expression profile in PK-Sim DB | S0 fails; options: choose another profile source or mark pathway as total hepatic clearance |
| Snapshot fails the engine dry run | Round fails with engine stderr; escalation `ENGINE_LOAD_FAILED` (usually catalog drift) |
| Two subjects define the same expression profile differently | Builder error `CONFLICTING_EXPRESSION_PROFILE` |

### 12.3 Campaign loop
| Scenario | Response |
|---|---|
| No IV data | MS-01 §6.1 path; MAP states risk floor |
| Only one study in a class | INTERNAL; external validation "not achievable" limitation recorded |
| Round 1 already passes | Stage passes with no fitting; recorded |
| Fitted parameter at bound | Escalation with parameter, bound and evidence |
| Starts disagree | One DEoptim round, then escalation |
| Budget exhausted mid-round | Running starts cancelled (§8.4); round assessed on finished starts; stage escalates with best-so-far |
| Strategist unavailable or returns disallowed action | First permitted action used; logged `STRATEGIST_FALLBACK` |
| Engine pool down | Rounds wait (Temporal retries); campaign clock pauses (budget counts engine time, not queue time); alert |
| External validation fails | `DEVIATION_PENDING`; options per MS-01 §6.6; nothing automatic |
| Human decision never arrives | Escalation stale alert at 24 h; campaign remains paused indefinitely; can be abandoned by owner |
| MAP changed after signing | New MAP version invalidates the campaign; a new campaign must be created (old one kept for audit) |
| Engine image retired mid-campaign | Campaign continues on the pinned digest (images are immutable); new campaigns cannot pin it |
| Same campaign started twice | Idempotency key + unique constraint `(question_id, map_id, status in running)` → 409 |

### 12.4 Engine
| Scenario | Response |
|---|---|
| Input hash mismatch | `InputIntegrityError`, non-retryable; alert (possible tampering or storage fault) |
| Solver error / NaN outputs | Run `ENGINE_ERROR`; results not promoted; round diagnostics get `ENGINE_FAILURE` evidence → escalation if repeated twice |
| OOM | Retried once on `engine-l`; then failure |
| Timeout | `EngineTimeout`; partial outputs kept under `cancelled/`; never used for verdicts |
| Node loss mid-run | Temporal reschedules the activity (heartbeat timeout 2 min) on another node; outputs are per-attempt keys |
| Locale/µ garbling | Image sets `LC_ALL`; golden test asserts `µg/l` round trip |
| Engine warnings | Captured; a run with warnings needs reviewer acknowledgement before it can back a signed evaluation |

### 12.5 Compliance and records
| Scenario | Response |
|---|---|
| Signature on a record that changed since the signing view was loaded | 409 `RECORD_HASH_MISMATCH`; client reloads |
| Audit chain verification fails | Page; writes continue (chain continues from the last good head); QA investigation record |
| User deactivated with open reviews | Reviews reassigned by owner; audit records keep the original actor |
| Clock skew on a node | Chrony required; API rejects timestamps > 60 s from DB clock; audit uses DB `now()` |
| Retention expiry | Export + legal hold check before any purge; purge is a signed admin procedure, out of v1 |

### 12.6 Agents
| Scenario | Response |
|---|---|
| Provider refusal | Step recorded with `stop_reason=refusal`; task marked `REFUSED`; human notified |
| Token/cost budget exceeded | Run stops `INCOMPLETE` with partial proposals |
| Citation not found verbatim | Proposal rejected automatically (existing) |
| Hidden instructions in a document | Ignored by design (tools are read-only; proposals validated); flagged if the QC agent detects instruction-like text |
| Duplicate tool names across MCP servers | First wins; others skipped and logged |
| MCP server down | Circuit breaker → REST fallback → source marked unavailable in coverage report |

---

## 13. Testing strategy (FINALIZED)

| Level | What | Tooling | Gate |
|---|---|---|---|
| Unit | domain, intake, contracts, compliance, agents' deterministic parts | pytest, hypothesis (snapshot round-trip and unit properties) | CI, ≥ 85 % coverage on domain/intake |
| Engine golden | image runs `golden_roundtrip.R` (snapshot→project→snapshot, run from snapshot, PK), `pi_smoke.R`, `benchmark.R`; reference PK values for Aciclovir and the platform example within 1e-6 | in-image CI job | image cannot be pushed without pass |
| Contract | OpenAPI schema fuzzing; idempotency; RLS isolation (two tenants) | schemathesis, pytest | CI |
| Workflow | Temporal test server with time skipping: campaign state machine, budget deadline, escalation signals, continue-as-new | temporalio testing | CI |
| Integration | compose stack: upload → mapping → campaign S1 on the example snapshot → evaluation → signature → bundle | pytest + compose | nightly + pre-release |
| E2E | browser flows for the seven user flows | Playwright | pre-release |
| Performance | seconds/simulation and PI evaluation time per image on the cluster node class; regression > 20 % fails | benchmark job | image qualification |
| Agent evals | golden sets: 30 mapping cases (messy sheets), 50 parameter extractions with known citations, 20 diagnostics-to-action cases; precision ≥ 0.95 on citations, recall reported | pytest + recorded LLM outputs; live run weekly | prompt/model changes |
| Validation evidence | pytest markers `@pytest.mark.req("F-xxx.Ry")` → trace matrix; JUnit and golden reports archived per release | CI artifacts | release |
| Security | dependency scan (Trivy), SBOM, secret scan, ZAP baseline against staging | CI + weekly | release |

---

## 14. Phased delivery (FINALIZED milestones; tasks in the Continuation Package)

| Phase | Scope | Milestone / success criteria |
|---|---|---|
| **P0 Engine on Linux** (week 1) — *image part done 2026-09-15: golden round trip and fitting smoke pass inside `modeler-engine:ospsuite-12.4.4-dev`* | Ubuntu check on one server; benchmark numbers recorded; engine image registered | `engine_images` row `BUILT` with benchmark JSON from the servers; run-from-snapshot and project round trip pass on Linux (done in the image) |
| **P1 Vertical slice** (weeks 2–7) | Auth (Keycloak), persistence, MinIO presigned I/O, results ingestion, CPF v1 + builder extensions from catalog harvest, campaign S0–S2 (IV + oral loop) on the example compound, campaign monitor UI, signatures + audit live | One campaign runs S0→S2 unattended on the example within budget; every round, run and decision is in rows with audit events; a modeler signs the MAP via step-up |
| **P2 Full loop** (weeks 8–13) | S3 (formulation/fed), S4, S5 with deviation paths, diagnostics ruleset v1, strategist agent, population runs, sensitivity, reproducibility gate, bundle v1 | A library-like compound (built from public data) completes S0→S5 unattended; bundle re-runs identically in a clean pod |
| **P3 Applications & reporting** (weeks 14–20) | DDI, pediatrics, special populations, VBE templates; MAR generation; M15 flows; literature/intake agents in production; k3s on 3 nodes; observability; CI validation evidence | One DDI question of interest reaches a signed MAR + M15 table; OSP DDI qualification set reproduced within its reported GMFE |
| **P4 Hardening** (weeks 21–26) | Multi-tenant profiles, KMS, Longhorn/MinIO distributed, validation pack generator, self-hosted LLM endpoint support, pen-test, DR drill | Validation pack accepted by QA; DR restore drill passed; first external-user pilot |

Go-live engine decision (**FINALIZED, conditional**): ospsuite 12.4.4 / PK-Sim 12.3.173 on Linux is the production
engine if the P0 golden tests pass on the servers. If `runSimulationsFromSnapshot` fails on Linux, the fallback is the
same image executing `.pkml` exported by PK-Sim CLI on a Windows worker (Track B) for the affected steps only, and a bug
report goes to OSP. ospsuite 13 is adopted only after formal release, qualification and re-evaluation of affected models.

---

## 15. Open items requiring input (not blockers for P0/P1)

| Item | From | Needed by |
|---|---|---|
| Run `ubuntu_engine_check.sh` on one server; attach the results folder | server admin | P0 |
| Provision `/data` disk on each server; confirm the three servers are identical and on one network | server admin | P1 start |
| Kubernetes experience in the team (decides Compose-first vs k3s-first) | project lead | P1 start |
| SME sign-off of `pbpk_acceptance_criteria.yaml`, `ddi_static_screening.yaml`, MS-01 [SME] defaults | PBPK lead | before first GxP campaign |
| Who supplies paywalled PDFs from access requests, and the turnaround | project lead | P2 |
| Keycloak: existing corporate IdP to federate (SAML/OIDC) or standalone users | IT | P1 |
| Legal review of GPLv2 posture for on-prem delivery | legal | before external delivery |
