# 07 · API and integration catalog (post-MAP scope)

Machine-readable copy: `API_INVENTORY.csv`. Prefix `/api/v1` unless shown. "Envelope" = `{data, meta, errors}`.
Role shorthand: **Reader** = viewer, curator, reviewer or qa; **Writer** = curator or reviewer; **owner_guard** = a write
to a `{project_id}` path passes only for the project's owner (or a reviewer on the two signing routes). Every route
below was read in code; none was called against a server. The OpenAPI snapshot (`docs/api/openapi.json`) documents only
200/201/202 and 422 responses; the 401, 403 (`STEP_UP_REQUIRED`, `STEP_UP_STALE`, `NOT_OWNER`), 404, 409 and 503 answers
below come from the code.

## 1. HTTP endpoints

| Method | Path | Purpose | Auth / roles | Request | Response | Source |
|---|---|---|---|---|---|---|
| POST | `/projects/{project_id}/plan:sign` | Generate the MAP from the plan, sign it with the step-up, stage the campaign body (later calls sign deviations) | reviewer + member + owner_guard (signing route) + step-up | `{note}` | Envelope[PlanSigned] | `services/api/src/modeler_api/plan_api.py:518-601` |
| GET | `/projects/{project_id}/plan` / `plan:view` | Plan page incl. `map.campaign` (start body with server `file://` URIs) | Writer / Reader + member | - | Envelope[PlanPage] | `plan_api.py:192-205` |
| POST | `/projects/{project_id}/questions/{question_id}/campaign:prepare` | Stage CPF, MAP, observed (and system) under `prep/{question_id}` | Writer + member + owner_guard | PrepareRequest | Envelope[CampaignInputs] | `write_api.py:182-293` |
| POST | `/projects/{project_id}/signatures` | Generic Part 11 signature (used as `map_approval`) | any role + member + owner_guard + step-up | `{meaning, record_type, record_id, record_sha256}` | SignatureCreated | `signatures_api.py:26-49` |
| GET | `/projects/{project_id}/signatures` | Signature register with chain verdict | Reader + member | - | Envelope[SignatureRegister] | `signatures_api.py:56-85` |
| POST | `/projects/{project_id}/campaigns` | **Start a campaign** (202) | Writer + member + owner_guard; run guard outside development (409 unsigned MAP / CPF ≠ MAP; 422 budget override; 503 no read root or Temporal address) | CampaignStartRequest | CampaignStarted `{campaign_id, status: QUEUED, status_url}` | `campaign_api.py:29-81` |
| GET | `/campaigns[?project=]` | Tenant's campaigns filtered by membership; unreadable records named | Reader | - | Envelope[Campaigns] | `read_api.py:128-138` |
| GET | `/campaigns/{campaign_id}` | Monitor record (stages, rounds, gof, realData, engine, package, feedback, resume) | Reader; membership if the campaign has a project; 404; 409 unreadable shape | - | Envelope[CampaignRecord] | `read_api.py:141-155` |
| GET | `/escalations` | Open escalations with `can_decide` | Reader | - | Envelope[Escalations] | `read_api.py:286-300` |
| GET | `/escalations/decision-options` | Static options (lists 3 of the 6 actions) | none | - | DecisionOptions | `escalations.py:134-136` |
| POST | `/campaigns/{campaign_id}/stages/{stage}/escalation:resolve` | **Decide** retry, accept_best, abort, approve (S6 gate), learn, new_evidence (local backend) | any role + member + `ensure_owner(signing)` + step-up; 409 Temporal backend / not open / real-data refusal (approve) / feedback guardrail; 404; 422 | ResolveRequest `{action, note, studies, beyond_cap, evidence}` | EscalationResolved `{campaign_id, stage, action, status, remaining_stages?, note, signature}` | `escalations.py:199-284` |
| POST | `/campaigns/{campaign_id}/stages/{stage}/escalation:decide` | Temporal decision signal | **no bearer**; `X-Tenant-Id` header; password + second factor in body; **always 503** | SignedDecisionRequest | EscalationDecided | `escalations.py:83-84, 100-109, 139-158` |
| POST | `/campaigns/{campaign_id}/deviations` | Temporal deviation | as above, **always 503** | DeviationRequest | DeviationRecorded (201) | `escalations.py:111-118, 161-179` |
| GET | `/campaigns/{campaign_id}/package` | S7 summary: exportable, reproduction, hashes, artifacts, PK-Sim projects, issues, notes | Reader; membership if project; 404 before S7 | - | Envelope[CampaignPackage] | `read_api.py:195-212` |
| GET | `/campaigns/{campaign_id}/package/{artifact}` | Download `package.zip`, `mar.md`, `mar.docx`, `mar.pdf` | Reader; membership if project; 409 zip not exportable; path must be under the `file://` object store | - | FileResponse | `read_api.py:160-165, 215-234` |
| GET | `/runs/{run_id}/results` | Parquet results (output paths or a series) | any authenticated tenant user (no role, no project) | `path, individual_id, limit` | RunOutputs / RunSeries | `results_api.py:34-58` |
| POST | `/runs` | Submit one simulation to Temporal | Writer; 503 without Temporal | RunSubmission | Envelope[RunAccepted] (its `status_url` has no route) | `system_api.py:105-142` |
| POST | `/m15/validate` | M15 table completeness and allowed risk | Writer | `{stage, table}` | `{complete, allowed_model_risk, issues}` | `system_api.py:89-103` |
| GET | `/projects/{project_id}/steps` | The four steps; Run from campaign statuses | Reader + member | - | Envelope[Steps] | `project_api.py:60-66` |
| GET | `/projects/{project_id}/audit` | Project audit trail and chain verdict (prefix filter; campaign decisions not included) | Reader + member | `limit` | Envelope[AuditTrail] | `project_api.py:120-145` |
| GET | `/projects/{project_id}/system` | Model system panel | Reader + member | - | Envelope[ProjectSystem] | `read_api.py:272-283` |
| GET | `/admin/system` | Deployment, execution backend, engine check (starts the engine command, ≤ 20 s, cached 60 s) | admin | - | Envelope[SystemStatus] | `admin_api.py:229-237`; `engine_check.py:52-109` |
| GET | `/me` | User id, name, tenant, roles | authenticated | - | Envelope[MeView] | `admin_api.py:105-108` |
| GET | `/health` (no prefix) | Status, deployment kind, verifier kind | none | - | Health | `system_api.py:34-36` |

Not present: stop/cancel/resume of a running campaign, SSE/WebSocket events, `Idempotency-Key` handling, final CPF
acceptance, MAR or package signature, QA release.

## 2. Request body: `CampaignStartRequest` (`campaign_api.py:29-41`)

```json
{
  "compound": "string (min 1)",
  "map_id": "string (min 1)",
  "cpf_uri": "file:///… (server path)",
  "cpf_sha256": "64 hex",
  "map_uri": "file:///…",
  "observed_uri": "file:///…",
  "system_uri": "", "system_sha256": "",
  "question": "",
  "model_risk": "low | medium | high (required)",
  "stages": null,
  "stage_budgets_seconds": {}
}
```

## 3. Non-HTTP integrations

| Integration | Purpose | Interface | Data | Auth | Source |
|---|---|---|---|---|---|
| PK-Sim engine (subprocess) | every simulation, PI, population, sensitivity, batch, project conversion | `Popen([*MODELER_ENGINE_COMMAND, job.json])`, own process group, env allow-list | `job.json` → output files + `engine_manifest.json`; stdout `PROGRESS`/`WARNING` | none (local process) | `services/engine-worker/src/modeler_engine/runner.py`; `r/run_job.R` |
| Engine port | lets the orchestrator load the runner without importing it | entry point group `modeler.engines`, name `subprocess` | factory `(command, engine_id, image_digest)` | - | `packages/run-contracts/src/modeler_contracts/ports.py:46-54` |
| Docker engine shim | run the engine image on the Mac | `bash deploy/dev/docker_engine.sh job.json` (same-path bind mount) | as above | Docker | `deploy/dev/docker_engine.sh` |
| Keycloak | sign-in (PKCE), step-up loa2, JWKS | OIDC | JWT (`acr`, `auth_time`, `tenant_id`, `projects`) | - | `services/api/src/modeler_api/auth.py`; `apps/web/lib/oidc.ts`; `deploy/keycloak/realm-modeler.json` |
| PostgreSQL | Part 11 copy (audit events, signatures) in production; Keycloak DB | asyncpg | rows | DB login without UPDATE/DELETE on Part 11 tables | `packages/storage/src/modeler_storage/part11.py`; `deploy/server/postgres.sh` |
| File stores | records, monitor, escalations, audit chain, object store | filesystem, atomic writes, `flock` | JSON / JSONL / CSV / binaries | OS permissions | `packages/storage/src/modeler_storage/filestore.py`; `modeler_project/audit.py` |
| pandoc, typst | MAR DOCX and PDF/A-2b | Python packages `pypandoc-binary`, `typst` | Markdown → DOCX/PDF | - | `pbpk_domain/report/render.py` |
| Temporal (not deployed) | durable workflows | gRPC client, task queues `orchestrator`, `engine-s/m/l` | dataclass payloads | - | `services/orchestrator/src/modeler_orchestrator/{campaign,workflows,fitting,worker}.py` |
| MinIO / S3 (not wired into S7) | object store with presigned URLs | boto3, HTTP PUT/GET | files | access keys / presigned | `modeler_storage/objects.py`; `modeler_engine/objectstore.py` |
| GHCR + cosign + Syft (CI) | publish and sign the engine image | GitHub Actions | image by digest, SPDX SBOM artifact | OIDC keyless | `.github/workflows/engine-image.yml` |
| LLM providers | not used post-MAP (strategist deterministic) | - | - | - | `services/agents/src/modeler_agents/strategist.py` |

## 4. Engine job contract (per task)

| Task | Inputs | Key options | Outputs | Caller |
|---|---|---|---|---|
| `simulate` | `snapshot.json` | `export_pkml` | `*-Results.csv`, `profiles.json`, `*.pkml` | round, S6, S7 re-run, VBE |
| `convert_to_project` | `snapshot.json` | - | `*.pksim5` | S7 |
| `dry_run` | `snapshot.json` | - | `*.pksim5` | none |
| `pk_analysis` | `simulation.pkml` | - | `results.csv`, `pk_analyses.csv` | none |
| `population` | `simulation.pkml` [+ `population.csv`] | `population`, `seed`, `variability`, `occasion_seed`, `vpc` | `population.csv`, `results.csv`, `pk_analyses.csv`, `occasion.json`, `vpc.json` | VPC, VBE |
| `sensitivity` | `simulation.pkml` | `parameter_paths`, `number_of_steps`, `variation_range`, cores | `sensitivity.csv` | S6, S5 feedback |
| `batch` | `simulation.pkml` | parameter paths, units, run values | `batch-NNN-results.csv`, `batch_index.json` | S6 uncertainty |
| `parameter_identification` | `pi_spec_base.json` + pkml files | `start_values`, `start_index`, `seed` | `pi_spec.json`, `pi_result.json` | fit rounds, SJ |

Integrity: each input's sha256 is checked by the runner and again by `run_job.R`; output hashes are recorded in the
manifest. Status is `SUCCEEDED` or `CANCELLED`; failures raise `EngineFailedError` / `EngineTimeoutError` /
`InputIntegrityError`.
