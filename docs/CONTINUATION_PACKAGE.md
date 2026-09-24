# Continuation Package

**Purpose:** the entry point for anyone — engineer or AI model — resuming work on Modeler One. Read in this order:
`CLAUDE.md` (working rules) → this file (where things stand) → `CHANGELOG.md` (what changed, why, when) → the active
plan in `docs/plans/`. **Last brought up to date: 2026-09-24 (HEAD 62bceff + Phase 4 importer).** If HEAD is far ahead of
that commit and §4 was not updated with it, §4 is stale — fix it before trusting it.

## 30-second system state

Modeler One automates PBPK model development on the open-source OSP engine (ospsuite R 12.4.x, PK-Sim 12.3, .NET 8,
run as an isolated subprocess through `services/engine-worker/r/run_job.R`) and is meant to produce
regulator-reproducible packages under ICH M15 and 21 CFR Part 11. The scientific procedure is MS-01
(`docs/PBPK_MODELING_WORKFLOW.md`): stages **S0 readiness → S1 IV → S2 oral fasted → S3 formulation/fed → S4 internal
validation → S5 external validation → S6 prediction → S7 report & package**.

**What it is today:** a git repository (`main`), uv workspace, **429 Python tests pass (13 skip without Docker), ruff
clean**. It runs as a *single-node* tool: the web app (Next.js, :3000) proxies `/api/*` to the FastAPI service (:8000);
campaigns execute in-process (`LocalExecutor`, `MODELER_EXECUTION_BACKEND=local`) with file-backed stores; simulations
run on **real PK-Sim on the Linux server**. The distributed path (Temporal, Postgres with RLS, Keycloak, MinIO) is
built and tested in code but not deployed.

**A user can:** create a project (wizard) → enter the compound's parameters (CPF) → load studies (CSV intake) →
generate and sign the analysis plan (MAP) → run a campaign → watch it live → decide escalations in the review inbox
(signed).

**The honest limit:** every stage S0 → S7 now runs on real PK-Sim, but only on known-truth (synthetic) data so
far — see the coverage table in §4.1. Real clinical data is the open item: the Phase 4 reference importer turns the
published OSP Dapagliflozin model into a CPF and 40 real clinical studies (`pbpk_domain.reference`), and every stage
builds from it; running that campaign on the server's PK-Sim is next. Active plan:
`docs/plans/2026-09-24-s0-s7-real-pbpk.md`.

**Engine:** runs only on Linux — on macOS snapshot execution is unsupported and `loadProjectFromSnapshot` segfaults.
Server `ssh adt-server` (LAN 192.168.1.10, user `adt-ayush`, no sudo, repo rsynced to `~/Modeler_One_AI`, engine in
`~/modeler-engine`, data in `~/modeler-data`). It drops off the LAN, has no Tailscale yet, and its root disk is 95%
full. Docker Desktop is installed on the Mac (daemon off by default) and is the planned fallback engine host.

## 1. Decisions finalized in this session

| ID | Decision |
|---|---|
| D1 | Engine: ospsuite 12.4.4 / PK-Sim 12.3.173 / .NET 8 on Linux x86-64 is the go-live engine, conditional on the Linux golden tests (T-01). ospsuite 13 only after formal release + qualification. Windows CLI path is fallback only |
| D2 | Engine image: `rocker/r-ver:4.6.1` + OSP r-universe Linux binaries (`bin/linux/noble-x86_64/4.6`) + .NET 8; pinned by digest; golden tests inside the image gate every push |
| D3 | The Compound Parameter Framework (CPF, MS-01 §2) is the system of record for all models; the builder regenerates every simulation from it; overrides only via parameter transfer with PI provenance |
| D4 | The modeling loop is MS-01: S0 readiness → S1 IV → S2 oral fasted → S3 formulation/fed → S4 internal validation → S5 external validation (fasted and fed separately) → S6 prediction/application → S7 report. Data split by the deterministic algorithm in MS-01 §3, frozen in the MAP |
| D5 | Human touchpoints are exactly: MAP signature, data exclusions, escalations, MAP deviations, final CPF acceptance, evaluation/MAR/M15 signatures. Everything else runs unattended |
| D6 | Acceptance criteria are tiered by M15 model risk (high 1.25-fold all; medium 1.5-fold/Guest ≥ 80 %; low 2-fold ≥ 80 %), internal and external judged separately; stored as versioned ruleset awaiting SME sign-off; UNVERIFIED rulesets usable only in `exploratory` projects |
| D7 | Diagnostics are a deterministic ruleset (MS-01 §5); the strategist agent may only choose among permitted actions |
| D8 | Time budget: campaign budget → stage budgets → `plan_multistart` with measured seconds/simulation; deadline guaranteed; starts cancelled at the deadline; escalation with best-so-far |
| D9 | Runtime: k3s on the 3 servers (Compose-first allowed for P0/P1 if the team lacks Kubernetes experience); all state on a `/data` disk per node; CloudNativePG, MinIO (single node → distributed in P2), Temporal self-hosted, Keycloak, kube-prometheus-stack, Loki, Tempo, Argo CD, KEDA |
| D10 | Auth: Keycloak OIDC; realm roles + project membership; signatures require step-up (`acr=loa2`, `auth_time` ≤ 300 s); tenant from token claim |
| D11 | Engine plane has no credentials: presigned MinIO URLs per job; no egress; cancellation honoured via heartbeat polling |
| D12 | Agents: Claude Opus via Anthropic API now (Bedrock/Vertex/self-hosted endpoint supported by config); MCP servers self-hosted, allowlisted, every result stored as a citable record; REST fallbacks per source |
| D13 | FDA-reviewable package: bundle with manifest, all inputs/outputs/specs, `rerun_all.R`; export blocked unless the reproducibility gate passes |
| D14 | Data model as in ENGINEERING_PLAN §5; append-only compliance tables; Alembic with hand-written SQL |
| D15 | API contracts as in ENGINEERING_PLAN §7 (envelope, idempotency keys, SSE, error codes) |
| D16 | Testing gates as in ENGINEERING_PLAN §13; validation evidence from CI artifacts |

## 2. Remaining tasks (ordered; dependencies in §3)

Model routing: **SONNET** for well-specified mechanical work; **OPUS** for design-heavy or engine-discovery work.
Each task lists what to build, inputs/outputs, constraints, acceptance criteria, and where it fits.

### T-01 — Verify the engine on Linux · SONNET · P0
- **Build:** run `services/engine-worker/scripts/ubuntu_engine_check.sh /data/modeler-engine` on one server (needs the results back), and run the golden scripts inside the Docker image `modeler-engine:ospsuite-12.4.4-dev` (`Rscript /engine/golden/golden_roundtrip.R /engine/golden/example_snapshot.json /tmp/g`, `pi_smoke.R`, `benchmark.R`).
- **Outputs:** `benchmark.json`, `golden_report.json`, `pi_result.json`; record seconds/simulation and PI seconds/evaluation in `docs/WORKFLOW_AND_AUTOMATION.md §6` and in an `engine_images` row (once T-05 exists; until then in `deploy/engine-images.yaml`).
- **Acceptance:** `run_from_snapshot`, `snapshot_to_project`, `project_to_snapshot`, `roundtrip_content` and PK steps all OK on Linux; PI smoke converged. If `run_from_snapshot` fails on Linux: file the OSP issue with the log and switch D1 to Track B for that step.

### T-02 — Engine catalog harvest · OPUS · P0
- **Build:** `services/engine-worker/r/harvest_catalog.R` that, inside the image, exports to JSON: available compound process types and their parameter names/units (metabolizing enzyme first-order and Michaelis-Menten, transporters, specific binding, total hepatic clearance, GFR, tubular secretion, biliary), formulation types with parameters, calculation-method names (partition, permeability), species and populations, meal/event templates, PK parameter names from `allPKParameterNames()`, dimensions/units, and the exact simulation-level naming of process selections (from a set of reference snapshots converted via `loadProjectFromSnapshot` and re-exported). Use OSP library snapshots (Dapagliflozin, Midazolam, Itraconazole, Rifampicin) as fixtures to discover naming.
- **Outputs:** `catalog.json` per image (stored with the image, `engine_images.catalog`), plus golden fixtures under `services/engine-worker/golden/fixtures/`.
- **Constraints:** never hand-invent names; every entry must come from an engine export. Unknown → omitted and listed under `unresolved`.
- **Acceptance:** builder catalogs (T-03/T-10) load from this JSON; a snapshot built for each process type loads in the engine (dry run) without error.

### T-03 — CPF schema, engine binding, builder regeneration · OPUS · P1
- **Build:** `pbpk_domain/cpf/` with pydantic models for MS-01 §2.1/2.2 (parameter records, status, fit policy, plausibility, provenance), JSON Schema export, completeness check (S0 gate), `bind(cpf, catalog) -> BuildPlan`, and `SnapshotBuilder.from_cpf(cpf, system, scenarios)` that generates compound alternatives/processes, individuals/populations, protocols, formulations, events and simulations from the CPF and a scenario list. Parameter transfer updates the CPF (new version) and regenerates, instead of writing simulation overrides, except for the PK-Sim-native override written by `apply_identified_values` for traceability.
- **Inputs:** CPF document, catalog (T-02), scenario list (from studies). **Outputs:** snapshot + `BuildReport` (bindings used, unresolved parameters).
- **Constraints:** deterministic; units must be storage units; `NO_ENGINE_BINDING` error when a parameter has no binding for the image.
- **Acceptance:** the example compound and a CPF reconstructed from the Dapagliflozin snapshot both regenerate snapshots that load in the engine; property test: build → parse → build is stable.

### T-04 — Study classification and split · SONNET · P1
- **Build:** `pbpk_domain/campaign/split.py`: classify studies (MS-01 §3.2), information score, split algorithm (§3.3) returning assignments plus the generated rationale sentences; fed-data decision from the question of interest.
- **Acceptance:** unit tests for every rule in §3.3 incl. single-study classes, forced external categories, fed decision; output is stable for equal inputs.

### T-05 — Persistence layer · SONNET · P1
- **Build:** SQLAlchemy 2.0 async models and repositories for every table in ENGINEERING_PLAN §5; Alembic migrations (hand-written SQL, starting from `0001_core.sql`); `bind_tenant` on every session; audit event in the same transaction for every write; unique constraints and partitions as specified.
- **Acceptance:** RLS isolation test with two tenants; append-only triggers tested; migrations up/down clean on Postgres 16.

### T-06 — Authentication and authorization · SONNET · P1
- **Build:** Keycloak realm export (`deploy/keycloak/realm-modeler.json`) with roles, `signing` step-up flow (password + TOTP → `acr=loa2`); FastAPI dependency validating JWT (JWKS cache), tenant claim, realm roles, project membership; `POST /signatures` enforcing `acr` and `auth_time`; web app login (Authorization Code + PKCE).
- **Acceptance:** contract tests: no token 401; wrong project 403; signature without loa2 → 403 `STEP_UP_REQUIRED`; signature with stale `auth_time` → 403.

### T-07 — Object store and presigned I/O · SONNET · P1
- **Build:** `S3ObjectStore` (MinIO, boto3) implementing the `ObjectStore` protocol; orchestrator activity `prepare_engine_job` issues presigned GET/PUT URLs (2 h) per input/output prefix; engine runner downloads/uploads via HTTP with hash checks; bucket policies with Object Lock compliance mode and per-tenant prefixes.
- **Acceptance:** engine worker test against a MinIO container: tampered object → `InputIntegrityError`; expired URL → retry path; no credentials in the engine pod env.

### T-08 — Results ingestion · SONNET · P1
- **Build:** activity `ingest_results`: read engine CSV outputs, write Parquet (columns: time, path, value, unit, individual_id) under `runs/{run_id}/results/`, write `run_results` and `pk_parameter_values` rows (from `pk_analyses.csv`), attach manifest and warnings to the `runs` row, audit event; DuckDB query helper for `GET /runs/{id}/results`.
- **Acceptance:** ingestion of the golden run reproduces the PK table; idempotent on re-run.

### T-09 — Engine tasks: population, sensitivity, pk_analysis; cancellation · OPUS · P1
- **Build:** in `run_job.R`: `population` (createPopulation from demographic spec or load CSV, run, export results + PK), `sensitivity` (`runSensitivityAnalysis` on listed paths with variation range), `pk_analysis` (existing, plus user-defined PK parameters), `batch` (SimulationBatch over parameter sets for the evaluation of many scenarios); in `runner.py`: `activity.is_cancelled()` polling, process-group kill, `CANCELLED` manifest, partial outputs under `cancelled/`.
- **Acceptance:** golden tests per task; cancellation test kills a sleeping fake engine within 25 s and uploads a `CANCELLED` manifest.

### T-10 — Builder coverage from the catalog · OPUS · P1
- **Build:** extend `pbpk_domain/snapshot/builder.py` with Michaelis-Menten metabolism, transporters, total hepatic/biliary/tubular-secretion clearances, inhibition/inactivation/induction processes, solubility tables, particle dissolution and table formulations, advanced protocols (multiple dose schemas), meal events, populations, expression profiles for transporters; all names from T-02 fixtures.
- **Acceptance:** each new structure round-trips through the engine (dry run + run) in the golden suite; the Dapagliflozin snapshot can be rebuilt from its CPF with identical simulation outputs within 1e-6.

### T-11 — Observed data coverage · SONNET · P1
- **Build:** extend `modeler_intake/pksim.py` for urine/feces fractions (`Fraction` dimension), molar units (needs MW), geometric statistics, individual series, and the LLOQ encoding verified by an engine golden test (`DataSet$LLOQ` round trip through a snapshot).
- **Acceptance:** golden test loads the converted observed data in PK-Sim and PI uses it with LLOQ handling.

### T-12 — Engine image CI and registration · SONNET · P0/P1
- **Build:** GitHub Actions job: build amd64 image, run golden scripts and benchmark inside, Syft SBOM, cosign sign, push to GHCR by digest, register `engine_images` (status `BUILT`) with catalog and benchmark; `deploy/vendor/` monthly refresh of R binaries.
- **Acceptance:** a PR that breaks a golden test cannot publish an image; digest and benchmark appear in the registry row.

### T-13 — Campaign workflows · OPUS · P1/P2
- **Build:** `ModelingCampaignWorkflow`, `StageLoopWorkflow`, activities (`plan_campaign` from MAP, `build_round_snapshot`, `run_round`, `evaluate_round`, `diagnose_round`, `choose_action`, `record_round`, `resume_campaign`), signals (`map_signed`, `escalation_decided`, `deviation_recorded`, `accept_final_cpf`), continue-as-new per stage, stage budgets and deadlines, MS-01 stage rules S0–S5 (S6/S7 in T-31/T-24).
- **Acceptance:** Temporal test-server tests for the state machine, deadline cancellation, escalation pause/resume, resume from rows after worker restart; integration run of S0→S2 on the example compound within its budget.

### T-14 — Diagnostics ruleset and evaluator · OPUS · P2
- **Build:** `rulesets/diag_rules.yaml` (MS-01 §5 with thresholds, status UNVERIFIED) and `pbpk_domain/diagnostics.py` computing evidence (t½ ratio, early-phase error, tmax/Cmax pattern, dose-normalized AUC trend, secondary peaks, accumulation ratio, bound proximity, correlations, start agreement) and returning permitted actions per stage.
- **Acceptance:** 20 golden cases (synthetic profiles with known causes) map to the expected first action.

### T-15 — Strategist agent · SONNET · P2
- **Build:** `modeler_agents/strategist.py`: structured-output call with `output_format` = `{action_id ∈ permitted, rationale, parameters_to_fit[], bounds_override?}`; validation against the permitted set; fallback to the first permitted action; persisted in `agent_runs/steps`.
- **Acceptance:** disallowed choices are rejected; eval set of 20 diagnostics cases agrees with the ruleset's first action ≥ 80 %.

### T-16 — MAP generator · SONNET · P1
- **Build:** `pbpk_domain/campaign/map.py` producing the MAP document (MS-01 §9) from CPF, studies, split, question, tier, engine image and budget; `POST /questions/{id}/map:generate`; docx/PDF rendering via the report renderer (T-24) later, JSON first.
- **Acceptance:** generated MAP contains every field in MS-01 §9; changes after signing create a new version and invalidate campaigns.

### T-17 — Escalations, deviations, decisions API · SONNET · P2
- **Build:** endpoints from ENGINEERING_PLAN §7 for escalations/deviations; decision options served from MS-01; signals to workflows; review-inbox feed.
- **Acceptance:** an escalated campaign resumes only through a decision with the required signature role.

### T-18 — Evaluation activity and plots · OPUS · P1/P2
- **Build:** `evaluate_round`/`evaluate_stage`: PK parameters from runs vs observed NCA (deterministic NCA on observed data: linear-up/log-down AUC, Cmax, tmax, t½ by terminal regression with ≥ 3 points), `acceptance.evaluate`, GMFE, GOF datasets, VPC bands from population runs, Plotly JSON + static SVG/PNG.
- **Acceptance:** NCA validated against known datasets (e.g. OSP Aciclovir profiles) within 1 %; plots render in the web app.

### T-19 — Figure digitizer · OPUS · P3
- **Build:** tool that takes a PDF page image, user-set axis calibration (two points per axis, linear/log), and extracts marker coordinates → observations draft with overlay image for verification.
- **Acceptance:** synthetic figure round trip within 2 % of axis range.

### T-20 — Agent persistence, budgets, provider fallback · SONNET · P2
- **Build:** `agent_runs/agent_steps/proposals` writes through the API; token/cost budgets per agent; provider selection per tenant; `LLM_UNAVAILABLE` handling; retry queue.
- **Acceptance:** every agent step visible in the audit viewer; budget stop produces `INCOMPLETE`.

### T-21 — Agent evaluation sets · OPUS · P2/P3
- **Build:** golden sets (30 messy sheets, 50 parameter extractions, 20 diagnostics cases) and a runner comparing outputs; weekly live run.
- **Acceptance:** citation precision ≥ 0.95; report published per prompt/model version.

### T-22 — MCP servers deployment and REST fallbacks · SONNET · P2
- **Build:** Helm subcharts for BioMCP (`serve-http`), ChEMBL and PubChem servers (pinned images), NetworkPolicies allowing only their upstreams; `modeler_agents/sources/` REST fallback clients (Europe PMC, ChEMBL, PubChem PUG) producing `retrieved_records`; circuit breaker per source.
- **Acceptance:** with BioMCP down, a research run completes using fallbacks and the coverage report marks the source unavailable.

### T-23 — Reproducibility gate and bundle · OPUS · P2
- **Build:** `BundleWorkflow`: assemble the package (ENGINEERING_PLAN §4.6), generate `rerun_all.R`, run it in a fresh engine pod, compare hashes and PK tables (1e-6), write `bundles` row and manifest; export as ZIP with PDF/A reports.
- **Acceptance:** a bundle of the example campaign re-runs identically; a tampered file fails the gate with a diff.

### T-24 — MAR generation and report rendering · SONNET · P3
- **Build:** MAR skeleton (M15 Appendix 2) filled from campaign artifacts; numbers as references resolved at render time; Pandoc → DOCX and PDF/A-2b with signature manifestation blocks; M15 table rendering.
- **Acceptance:** rendered MAR contains every table/figure referenced; no number in the text that is not in evidence.

### T-25 — CI pipeline and validation evidence · SONNET · P1
- **Build:** GitHub Actions per ENGINEERING_PLAN §9.5; pytest `req` marker plugin producing the trace matrix; Trivy, secret scan; release artifacts.
- **Acceptance:** green pipeline on the main branch; trace matrix lists every feature ID with test IDs.

### T-26 / T-27 / T-28 — Web app · SONNET · P1–P3
- **Build:** T-26 auth, projects, compound/CPF screen with provenance chips and completeness; T-27 intake (grid + mapping side by side, questions, confirm) and review inbox (proposals, escalations, signatures with step-up); T-28 campaign monitor (stage timeline, round table, GOF/VPC plots via Plotly, budget bar), evaluation and M15/MAP/MAR editors, audit viewer.
- **Acceptance:** Playwright flows for the seven user flows in ENGINEERING_PLAN §3.

### T-29 — Helm umbrella, k3s runbook, observability · SONNET · P3
- **Build:** `deploy/` Helm umbrella (api, orchestrator, agents, engine pools with KEDA, web, MCP servers) + values per environment; runbook for the 3-node k3s install with `/data`; kube-prometheus-stack, Loki, Tempo, alert rules from ENGINEERING_PLAN §11; Argo CD app-of-apps; SOPS.
- **Acceptance:** staging namespace deploys from a tag; all alerts fire in a fault-injection test (disk fill, engine failure, Keycloak down).

### T-30 — SME sign-off packets · HUMAN (PBPK lead, clinical pharmacology, QA)
- Review `pbpk_acceptance_criteria.yaml`, `ddi_static_screening.yaml`, MS-01 [SME] defaults, `diag_rules.yaml`; sign; set `status: SME_APPROVED` with version bump and signature record.

### T-31 — Application templates · OPUS · P3
- **Build:** DDI (victim/perpetrator with OSP library models pinned by tag), pediatrics (age bins, ontogeny), special populations, VBE (uses `bioequivalence.py`), FIH translation; each as YAML template + workflow steps + gate + M15 row generator.
- **Acceptance:** OSP DDI qualification subset reproduced within reported GMFE; pediatric template reproduces a published OSP pediatric evaluation.

### T-32 — Validation pack generator · SONNET · P4
- **Build:** URS/FS from feature specs, trace matrix, OQ evidence from CI, IQ from Helm/k3s state, PQ from staging campaign runs; DOCX/PDF output.

## 3. Dependency order

```
T-01 ─┬─► T-02 ─► T-03 ─┬─► T-10 ─► T-13 ─► T-14 ─► T-15 ─► T-17
      │                 ├─► T-04 ─► T-16 ─┘        │
      │                 └─► T-11                   └─► T-23 ─► T-24 ─► T-31
      └─► T-12
T-05 ─┬─► T-06 ─► T-26 ─► T-27 ─► T-28
      ├─► T-07 ─► T-08 ─► T-18 ─► (T-13)
      ├─► T-09 ─► (T-13)
      └─► T-20 ─► T-21, T-22
T-25 (parallel from week 2) · T-29 (P3) · T-30 (human, parallel) · T-19 (P3) · T-32 (P4)
```
Critical path to the first unattended S0→S2 campaign (P1 milestone): T-01 → T-02 → T-03 → T-04/T-10 → T-13, with
T-05 → T-07 → T-08 → T-18 and T-09 in parallel.

## 4. Where things stand (2026-09-24)

### 4.1 Pipeline coverage — update this table in the same commit as any stage change

| Stage | MS-01 job | Status | What exists and works | What is missing | Plan item |
|---|---|---|---|---|---|
| S0 readiness | CPF completeness, data split, MAP signed | **Done** | completeness gate, split algorithm (§3), MAP generator, step-up signature | — | — |
| S1 IV | fit clearance and distribution to IV data | **Done — PK-Sim** | round loop build → simulate → evaluate → diagnose → fit, fit judged in its own round; renal clearance rule; enzyme/transporter expression harvested from OSP models; PI in base units with SD/CV/CI kept in the CPF; VPC gate (≥ 80 % in 5–95 %, n = 100); fit starts in parallel | clinical-data proof (Phase 4) | 4 |
| S2 oral fasted | absorption from solution (or the tablet, §6.3) | **Done — PK-Sim** | solution / rapid IR / §6.3 tablet reference; multiple dose (DI_24, DI_12_12); VPC gate; known-truth recovery of intestinal permeability exact | clinical-data proof | 4 |
| S3 formulation / fed | Weibull tablet release, fed effect | **Partial — PK-Sim** | CPF Weibull formulations; slow-release IR solids train S3; Weibull t50/shape fitted per simulation at harvested paths; known-truth recovery of t50 exact | fed sub-loop (`food.fed_solubility_factor` has no engine binding yet); dissolution-data intake (in-vitro Weibull fit) | 4 / next |
| S4 internal validation | final CPF vs internal studies, no fitting | **Done — PK-Sim** | every trained study re-simulated once, judged, never fitted; VPC per study reported; failure escalates with §6.6 choices | — | — |
| S5 external validation | fasted and fed judged separately | **Done — PK-Sim** | external core-class studies (IV, oral, tablet, MD) judged from the final CPF, fasted / fed as separate groups; unbuildable ones named; "not achievable" with no external study | clinical-data proof; fed studies await the fed sub-loop | 4 |
| S6 prediction | sensitivity + uncertainty on the question | **Partial — PK-Sim** | runs after the signed S4/S5 gate; local sensitivity over FITTED/PREDICTED parameters; uncertainty of fitted parameters (n = 200) → AUC/Cmax intervals; verified on the server (known-truth) | application templates (T-31); correlated sampling; Temporal wiring | next phase |
| S7 report & package | MAR, M15 table, bundle, re-run | **Partial — PK-Sim** | evidence persisted per stage; data bundle; fresh-engine re-run compared at 1e-6; MAR (MD, DOCX, PDF/A-2b) with evidence index; zip released only if reproduction passed; 7/7 tables reproduced on the server | MAR signature; M15 influence/consequence capture; Temporal wiring (download API and monitor card done) | Phase 3 |

Roadblocks R1–R13 are defined in the active plan. **Evidence rule:** a stage is "Done" only when a campaign has passed
it on real PK-Sim, not on a stub or the analytical stand-in.

### 4.2 Platform

| Component | State |
|---|---|
| Execution | Single-node `LocalExecutor` (in-process, same activities) — **used**. Temporal workflows — built, tested, not deployed |
| Persistence | File-backed `ReadStore` / `WriteStore` under `MODELER_READ_ROOT` — **used**. Postgres schema with RLS and append-only audit (T-05) — built, not used |
| Auth | `DevVerifier` (**DEV ONLY**, `MODELER_DEV_AUTH=1`) in the single-node deploy. Keycloak OIDC + step-up (T-06) — built, not deployed |
| Object store | `file://` — used. MinIO presigned I/O — not built |
| Engine | Real PK-Sim on the server, and on the Mac through Docker (`deploy/dev/docker_engine.sh`, image from `services/engine-worker/Dockerfile`; set `MODELER_ENGINE_COMMAND="bash <repo>/deploy/dev/docker_engine.sh"`). `deploy/dev/stub_engine.py` (synthetic) and `analytical_engine.py` (one-compartment) are **software fixtures only — never PBPK evidence** |
| Deployment | `deploy/server/` scripts: run / stop / status / autostart (cron `@reboot` + watchdog, installed 2026-09-24) / Tailscale (installed userspace, awaiting the owner's login). Redeploy from the Mac: `bash deploy/dev/deploy_to_server.sh` |
| Web | Dark design system, project wizard (starting points from `GET /templates`: the published Dapagliflozin model with real data, or the labelled illustrative quick check), data intake, campaign monitor with fold-error gauge and engine label (red banner for a software-fixture run), review inbox. No sample-data fallback: pages state the real problem. Playwright flows in `apps/web/e2e` (4, pass on the stub engine; the PK-Sim run of the same flow is pending) |

### 4.3 Task status (specs in §2)

| Task | Status |
|---|---|
| T-01 → T-09, T-11, T-12, T-18, T-25 | Done |
| T-03 | Done — server acceptance (a CPF reconstructed from Dapagliflozin regenerates it) folds into the Phase 4 importer |
| T-10 | Partial — Weibull/Dissolved formulations, individual overrides (`indiv.*`), per-study published individual, study weight/height, expression overrides (`expr.*`), pH-solubility tables, IV bolus protocols (`IntravenousBolus`), simulation values scoped to a route (`sim[oral|iv].*`), a process selected on another molecule of the individual (`molecule.*`, Dabigatran ABCB1 on P-gp), an unset plasma protein binding partner kept unset, regimens of phases (loading dose then maintenance, unevenly spaced doses, a phase's own infusion time: `StudyRecord.dose_phases`), published expression profiles verbatim (`expr.profile.*`), solubility / intestinal-permeability alternatives per product and food state (`<id>@<alternative>`, `alt.select`), every meal with its time, template and values (`StudyRecord.meals`); processes: specific FO/MM, liver-microsome MM, recombinant-CYP MM/FO, intrinsic FO, total hepatic and renal clearance, GFR, transporter MM / Hill / vesicular assay, competitive / noncompetitive / mixed / irreversible inhibition, induction, specific binding (names harvested from the OSP library). Model systems (plan `2026-09-24-multi-compound.md`, approved): `ModelSystem`, system import, multi-compound build (formation, per-compound protocols, observers), round trip per analyte, engine outputs per path, campaigns (API `PUT /system`, per-analyte evaluation, only the fitted parent gated — phase 2 needs the MS-01 amendment). Particle dissolution (monodisperse) and binned products placed (Ketoconazole). Missing: Table / Lint80 formulations, polydisperse particles, loading-dose regimens, Populations block, biliary clearance |
| Phase 4 reference runs | OSP library (25 public JSON snapshots): **22 import S0-ready as single compounds (Voriconazole added with loading-dose regimens), Dabigatran as a system** (2026-09-24; 3 before), gaps named per drug by `deploy/reference/portfolio.py` — Warfarin (racemic data vs enantiomer compounds, no compartment in its data) remains; Ketoconazole (particle formulation) and Voriconazole (loading doses) are placed. Round trips on PK-Sim (`.github/workflows/reference-models.yml`): Dapagliflozin 28/34 within 6.3e-5 of the peak; Rifampicin 20/21; Midazolam oral gap traced to per-simulation gut-wall permeabilities (fixed, re-run pending). Round trips on PK-Sim, run 14 (2026-09-24): every parameter identical for Dapagliflozin (25/34 curves within 1e-6, the rest by design or 2e-6–2e-5 solver noise at high doses), Rifampicin (20/21), Midazolam (all but Bornemann "1 h before a meal", 0.015, and Mikus 2017, now labelled mixed-route); Dabigatran system: IV exact, oral 2-fold off, fixed afterwards (ABCB1 selected on P-gp); Alprazolam and Alfentanil gaps (route-scoped values, IV bolus, binding partner) fixed afterwards, to be confirmed by the next run |
| T-13 | Done (Temporal) + single-node `LocalExecutor` |
| T-14 | Done — ruleset **UNVERIFIED** pending SME sign-off (T-30) |
| T-15, T-17, T-20 | Done — agent `RunStore` still file-backed |
| T-16 | Done — but the MAP never schedules S4/S5 work (R1) |
| T-23, T-24, T-32 | Done as libraries — not wired into campaigns (R9) |
| T-26 / T-27 / T-28 | Built — Playwright create-project flow + failure-mode flows written and passing (stub engine); intake / review-inbox decision flows not yet; wizard offers 12 published OSP models with real data |
| Remaining to the goal | `docs/plans/2026-09-24-remaining-to-goal.md`: plan exit ≈ 7–11 sessions, regulator-reviewable product ≈ 22–34 sessions + SME time. Verification blocked on GitHub Actions minutes; `deploy/reference/run_all.sh` runs the same checks on the server |
| T-19, T-21, T-22, T-29 | Not started |
| T-30 | Human (SME / QA sign-off) — pending |
| T-31 | Not started — next phase after S0 → S7 |

### 4.4 How to run

```bash
make sync && make test && make lint          # Python: uv workspace, pytest, ruff
npm --prefix apps/web run typecheck           # web
npm --prefix apps/web run build
npm --prefix apps/web run e2e                 # Playwright: starts its own API + web; stub engine unless
                                              # E2E_ENGINE_COMMAND="Rscript $PWD/services/engine-worker/r/run_job.R"
```

On the server (one URL, `http://<server>:3000`): `deploy/server/run_modeler.sh`, `stop_modeler.sh`,
`status_modeler.sh`; `install_autostart.sh` once. Configuration lives in `deploy/server/_env.sh`.
Engine checks on the server: `Rscript services/engine-worker/golden/golden_roundtrip.R …` and
`services/engine-worker/scripts/verify_run_round.sh`.

### 4.5 Earlier session notes (2026-09-15 → 16) — kept for the engine facts

**T-01 done (2026-09-15).** Engine verified on the project server (Intel Xeon Silver 4510, 48 logical cores, Ubuntu
24.04). The server has no sudo and no `/data`; the engine was installed under `~/modeler-engine` via Miniforge R 4.6.1
(`ubuntu_engine_check.sh` was made sudo-optional and conda-R aware). Golden round trip + fitting smoke test pass;
benchmark: single run 0.506 s, 1-core batch 0.4214 s/run, **47-core batch 0.00555 s/run (75.9× speedup)**, PI 0.36
s/eval. The 1-hour campaign budget is met comfortably (full IV→oral→fed with 32 multistart each ≈ 20 min). D1 confirmed.
Engine image also passes the same golden tests; `initPKSim()` needs a writable cwd (image sets `WORKDIR /home/engine`).

**T-02 done (2026-09-15).** `services/engine-worker/r/harvest_catalog.R` + `scripts/fetch_reference_snapshots.sh` +
`scripts/harvest_catalog.sh`; Python loader `pbpk_domain.catalog` (17 tests). Validated end-to-end (R→JSON→Python)
against the OSP Dapagliflozin/Midazolam/Itraconazole/Rifampicin models. Key harvested facts (see the
`osp-engine-facts` memory): compound processes have no Name (identified by InternalName+Molecule+DataSource); the
simulation selection Name is `{Molecule}-{DataSource}` / `Glomerular Filtration-{DataSource}` (SystemicProcessType=GFR)
— confirmed across all 4 models, validating `validation.process_selection_for`. The authoritative
`golden/catalog.json` was harvested on the Linux server (2026-09-15): all four OSP models + the example snapshot load
in the engine (`roundtrip_ok=true`), and its content matches the macOS harvest exactly (cross-platform check). Committed
with `golden/fixtures/*.json`; `tests/test_engine_catalog.py` pins its invariants in CI. Re-run
`scripts/harvest_catalog.sh ~/modeler-engine` whenever the engine image changes.

**T-03 done (2026-09-15).** `pbpk_domain.cpf`: versioned parameter document + record (§2.1), S0 completeness gate
(§2.2), catalog binding (`bind` → `BuildPlan`, `BindingError`/NO_ENGINE_BINDING), `build_from_cpf` /
`SnapshotBuilder.from_cpf` snapshot regeneration (deterministic; unsupported processes reported in `unresolved` for
T-10), JSON Schema at `packages/pbpk-domain/schemas/cpf.schema.json` (20 tests). **Remaining acceptance (server):** a
CPF reconstructed from the Dapagliflozin snapshot regenerates a snapshot that loads in the engine.

**T-04 done (2026-09-15).** `pbpk_domain.campaign.split`: classification (§3.2), information score, split algorithm
(§3.3) with rationale sentences and documented limitations (23 tests).

**T-10 mostly done (2026-09-16).** `pbpk_domain.snapshot.builder` extended with Michaelis-Menten metabolism
(`MetabolizationSpecific_MM`), active transport (`ActiveTransportSpecific_MM`), competitive inhibition, induction,
specific binding — exact catalog names/units; transporter/other-protein expression profiles; multiple-dose protocols
(DosingInterval + End time) and meal events. CPF→snapshot mapper groups records by (process, molecule). Engine
round-trip of MM+transporter+MD+meal **passed on the server** (`golden/process_coverage_snapshot.json`). **Remaining
T-10** (not in the 4 OSP fixtures, need a reference model or engine-API harvest): particle-dissolution/Table/Lint80
formulations, Populations block, total-hepatic/biliary/tubular-secretion clearances.

**T-13 done (2026-09-16).** `modeler_orchestrator.campaign`: `ModelingCampaignWorkflow` (S0 readiness → MAP signature
gate → per-stage `StageLoopWorkflow` children → final CPF acceptance; resume + escalation) and `StageLoopWorkflow`
(round loop build→fit-child/run→evaluate→diagnose→choose→record, stage budget/deadline, escalation retry/accept/abort).
Campaign contracts in run-contracts; `campaign_activities` (plan_campaign completeness + choose_action fallback
implemented; build/run/evaluate/diagnose/record/resume are boundaries pending T-05/07/08/09/14/15). Temporal
time-skipping tests cover the state machine, deadline, escalation, signature gates and resume.

**Repository is under git** (first commit 2026-09-16). 164 Python tests pass, lint clean. Critical path next: the
services lane **T-05** (persistence) → **T-07** (object store) → **T-08** (results) → **T-09** (engine population/
sensitivity/cancellation), which turn the T-13 activity boundaries into real behaviour, then **T-14/T-15** (diagnostics
ruleset + strategist) and **T-16** (MAP generator). Finish the T-10 tail (populations) alongside T-09.
