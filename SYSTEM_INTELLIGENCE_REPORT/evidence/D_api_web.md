# D · API (L6) and web (L7) for the post-MAP campaign lifecycle, roles and permissions

Investigator slice D. Read-only audit of `/workspace/Modeler_One_AI` on 2026-11-25. All paths are relative to the repo
root unless absolute. **VERIFIED** = I read the code at the cited line. **INFERRED** = reasoned from code I read, not
executed. Nothing was run against a server; no repo file was changed. (One throw-away pydantic check ran in the
scratchpad to confirm how pydantic formats an error message; it did not touch the repo.)

---

## 1. Summary

- **Two ways to start a campaign in the web app.**
  - (a) The plan canvas. **Approve and Sign** calls `plan:sign`, which needs realm role `modeler-reviewer`. Its handler
    generates the MAP, signs it from the token's step-up, and stages the CPF, MAP and observed files. **Run the campaign
    (P6)** then posts the staged body to `POST /projects/{id}/campaigns` (`services/api/src/modeler_api/plan_api.py:522-601`,
    `apps/web/components/plan/PlanCanvas.tsx:361-380`).
  - (b) An older one-click **Run campaign** button on `/projects/{id}/campaigns`. It calls `campaign:prepare`, then a
    generic `POST /signatures` with `record_type=map_approval`, then the start
    (`apps/web/components/RunCampaignButton.tsx:28-64`). The owner signs a MAP that was never shown to them, in the same
    click, and needs no reviewer role.
- **Campaign start** (`campaign_api.py:44-81`). It checks the realm role (curator or reviewer), project membership and
  ownership (`owner_guard`).
  - Outside development it also runs three run-guard checks (`run_guard.py`): the MAP is signed (409), no stage-budget
    override (422), and the CPF matches the MAP's parameter table, D-36 (409).
  - It then dispatches to Temporal (`ModelingCampaignWorkflow`) or to the in-process `LocalCampaignRunner`, which starts a
    **daemon thread** (`local_runner.py:1153-1169`). The choice follows `MODELER_EXECUTION_BACKEND`, default `local`
    (`config.py:21`).
- **There is no stop, cancel or resume endpoint for a running campaign.** The only way to end one is the `abort`
  decision on an open escalation (`escalations.py:219-284`). There is no SSE or WebSocket. Live progress is polling:
  `router.refresh()` every 2.5 s while the campaign is QUEUED or RUNNING (`apps/web/components/AutoRefresh.tsx:8-15`), and
  `/api/v1/escalations` every 5 s on every page (`EscalationPopup.tsx:34`).
- **Escalation decisions.**
  - Only `escalation:resolve` (local backend) works. It takes the signature from the token's step-up (loa2, auth_time
    within 300 s), writes it to the audit chain, then applies the decision.
  - The Temporal endpoints `escalation:decide` and `POST /campaigns/{id}/deviations` **always answer 503**: their
    verifier dependency raises unconditionally (`escalations.py:83-84`). They also take no bearer principal and carry a
    **password field** in the request body (`escalations.py:100-118`), against the rule in `CLAUDE.md`.
- **Most important defects** (detail in §8):
  1. The server never checks a decision's action against the escalation's offered options. `accept_best` on the S6
     signature gate marks S6 ACCEPTED and runs S7 without the S4/S5 evaluation signature, and so skips the D-19 real-data
     refusal (`escalations.py:248`, `local_runner.py:1277-1306`).
  2. `map_signed` trusts a MAP file's own `"status": "SIGNED"` field (`run_guard.py:56-57`). The `cpf_uri` and `map_uri`
     a client sends are read as arbitrary `file://` paths, and the D-36 error message echoes pydantic's
     `input_value` (`run_guard.py:93-100`).
  3. Curator owners can sign MAPs (through `map_approval`), escalation decisions and the S4/S5 evaluation, although the
     realm says only reviewers sign. There is no separation-of-duties check.
  4. The UI offers actions the API refuses: "Approve and Sign" to curators, "Run the campaign" to reviewers who are not the
     owner, and decisions on orphan escalations.
  5. A campaign interrupted by an API restart stays RUNNING forever: no recovery at startup, no cancel route.
  6. There is no audit event for a campaign start, a package download or a stage verdict; only signatures are chained.
- **Roles.** Keycloak realm roles: `modeler-viewer`, `modeler-curator`, `modeler-reviewer`, `modeler-qa`, `modeler-admin`
  (`deploy/keycloak/realm-modeler.json`). Platform memberships add a project **owner** and project **members**
  (`ownership.py`, `memberships.py`). QA reads every project of its company and changes or signs nothing; the realm's
  "QA release of the submission bundle" has no implementation.

---

## 2. Module inventory

| Module | Path | Responsibility | Called by | Calls | Lines |
|---|---|---|---|---|---|
| main | services/api/src/modeler_api/main.py | App, CORS, lifespan checks (production engine settings, DEV verifier refused in production, Part 11 store); router registration; `owner_guard` on most routers | uvicorn | every router, `runtime_env().check_production`, `dataroom_runs.pick_up` | 107 |
| campaign_api | …/campaign_api.py | `POST /projects/{id}/campaigns`: run guard, then Temporal or local dispatch | web `startCampaign` | run_guard, execution.RunnerDep, temporalio | 81 |
| run_guard | …/run_guard.py | Start checks: signed MAP, signed stage budgets, CPF = MAP (D-36), all skipped in development | campaign_api | runtime_env, FileProjectStore audit, `cpf_differences` | 105 |
| execution | …/execution.py | The one seam to the orchestrator (`get_campaign_runner` → `LocalCampaignRunner`) | campaign_api, escalations | modeler_orchestrator.campaign_runner | 30 |
| escalations | …/escalations.py | Decision options; Temporal `escalation:decide` and `deviations` (inert); local `escalation:resolve` | web `resolveEscalation` | compliance.signatures, part11.record_signature, runner | 284 |
| read_api | …/read_api.py | Projects, CPF, campaigns list/detail, S7 package and downloads, studies, system, escalations (`can_decide`), proposals | web server components, EscalationPopup | FileReadStore, ownership.may_change, memberships | 307 |
| write_api | …/write_api.py | Project create, CPF put, system put, study upload, `campaign:prepare` (stages CPF, MAP, observed) | RunCampaignButton, e2e | FileWriteStore, generate_map | 293 |
| plan_api (part) | …/plan_api.py | `plan:sign` (reviewer, step-up), MAP generation and staging of the campaign body; deviations (D-14) | PlanCanvas | sign_after_step_up, record_signature, record_signed_map | 601 |
| signatures_api | …/signatures_api.py | Generic `POST /projects/{id}/signatures`; signature register | RunCampaignButton (`signMap`), History page | sign_after_step_up, audit chain | 85 |
| results_api | …/results_api.py | `GET /runs/{id}/results` (Parquet via DuckDB) | **no web caller** (grep: none) | results.query | 58 |
| system_api | …/system_api.py | `/health`, snapshot preview, M15 validate, `POST /api/v1/runs` (Temporal) | web (health not used by pages) | SnapshotBuilder, temporalio | 142 |
| system_view | …/system_view.py | Model-system panel projection (no routes) | read_api.get_system | pbpk_domain.system | 43 |
| deps | …/deps.py | Role tuples (Reader, Writer, MiddLead), project store, workspace, `project_campaigns`, blinding helpers | most routers | FileProjectStore | 204 |
| auth | …/auth.py | Principal, JWKS verifier, DevVerifier, `require_role`, `require_project`, `ensure_step_up` | every route | memberships.admit | 169 |
| memberships | …/memberships.py | Platform memberships added to the token's projects; QA sees all company projects (`reads_only`) | auth.current_principal | modeler_project.members | 66 |
| ownership | …/ownership.py | `owner_guard` (writes: owner only; reviewer on the two signing routes); `may_change` | main.py routers, escalations, read_api | memberships | 65 |
| jobs | …/jobs.py | Background-job leases for agent, intake and Data room jobs; **campaigns are not a job kind** | plan_api, others | FileJobRegistry | 50 |
| doctor | …/doctor.py | CLI report of one project's state; **not an endpoint** | operator CLI | Workspace, project_steps | 207 |
| engine_check | …/engine_check.py | Starts the engine command with no job; answer kept 60 s | admin_api `/admin/system` | subprocess, runtime_env | 109 |
| platform_settings | …/platform_settings.py | Agent models, keys, limits, paid caps; **no campaign or engine settings** | admin_api | AES-GCM | 621 |
| config | …/config.py | `MODELER_*` settings (execution_backend, temporal_*, read_root, object_store_uri, results_root, oidc_*, dev_auth, part11_store, image_digest) | everything | pydantic-settings | 120 |
| responses | …/responses.py | Envelope; `answers` and `answers_without_envelope` | routers | — | 61 |
| views/campaigns, escalations, system | …/views/*.py | Response models: CampaignStarted, CampaignPackage, Escalations (+`can_decide`), SignatureCreated/Register, EscalationResolved/Decided, Health | routers | modeler_storage.records | 99 / 45 / 59 |
| compliance/signatures | …/compliance/signatures.py | SignatureMeaning (Authored, Reviewed, Approved, QA Released); `sign_record` (password) and `sign_after_step_up` | escalations, plan_api, signatures_api | — | 119 |
| part11 | …/part11.py | `record_signature` → audit chain (+ Postgres row in production) | signing routes | Part11Store | 82 |
| runtime (L1) | packages/run-contracts/src/modeler_contracts/runtime.py | Deployment kind (development, pilot, production), engine command, `engine_kind` (pksim / software-fixture / unknown) | run_guard, engine_check, local_runner | env | 182 |
| campaign_runner (L5) | services/orchestrator/src/modeler_orchestrator/campaign_runner.py | Port adapter → local_runner | execution | local_runner, feedback | 33 |
| Campaign page | apps/web/app/campaigns/[campaignId]/page.tsx | Monitor with tabs, fixture and test-only banners, package tab | browser | reads.getCampaign/getCampaignPackage, AutoRefresh, PackageDownloads | 347 |
| Campaigns list | apps/web/app/campaigns/page.tsx + components/portfolio/Campaigns.tsx | All campaigns of the person's projects | browser | getCampaigns, getProjects | 17 + 42 |
| Project Run page | apps/web/app/projects/[projectId]/campaigns/page.tsx | Run step: what is missing, RunCampaignButton, studies, campaigns | browser | getProject, getStudies, getCampaigns | 145 |
| RunCampaignButton | apps/web/components/RunCampaignButton.tsx | prepare → sign `map_approval` → start | Run page | lib/writes | 77 |
| PlanCanvas (part) | apps/web/components/plan/PlanCanvas.tsx | Approve and Sign; Run the campaign (P6) | /projects/{id}/plan | planApi.sign, startCampaign | 553 |
| EscalationPopup | apps/web/components/campaign/EscalationPopup.tsx | Flash bar and decision dialog on project and campaign pages | app/layout.tsx:88 | GET /escalations (5 s poll), GET /campaigns | 89 |
| EscalationDecision | apps/web/components/EscalationDecision.tsx | Decision form, confirm dialog, `resolveEscalation` | EscalationPopup | lib/writes, useMutation | 171 |
| StepUpDialog + lib/step-up | apps/web/components/StepUpDialog.tsx, lib/step-up.ts | On 403 STEP_UP_*, opens Keycloak loa2 in a pop-up and retries once | lib/api.ts withSession | /auth/login?step_up=1 | 56 + 24 |
| PackageDownloads | apps/web/components/PackageDownloads.tsx | Fetches artifacts with the bearer and saves them as blobs | Campaign page | apiFile | 53 |
| Work | app/work/page.tsx, components/portfolio/Work.tsx, lib/portfolio.ts | "Your work" list of links (replaces the review inbox) | browser | getPortfolio, getEscalations, getCampaigns, getMe | 21 + 51 + 80 |
| lib/api, hooks, reads, writes | apps/web/lib/*.ts | Typed client (serverGet, post, send, apiFile), react-query mutations, server reads, write helpers | pages and components | Next proxy → API | 297 / 290 / 101 / 36 |
| proxy | apps/web/proxy.ts | Token refresh; puts the person's access token on /api/*; no-role → /no-access | every request | Keycloak token endpoint | 66 |
| auth routes | apps/web/app/auth/{login,callback}/route.ts | PKCE login; `step_up=1` → `acr_values=loa2`; the pop-up answers with postMessage | StepUpDialog | Keycloak | 27 + 49 |

---

## 3. API table: the post-MAP lifecycle (VERIFIED unless noted)

"Envelope" = `{data, meta, errors}`. "Reader" = role in (viewer, curator, reviewer, qa). "Writer" = curator or reviewer.
"owner_guard" = router dependency `OWNER_ONLY_WRITES` (`main.py:87-106`): a write to a `{project_id}` path passes only for
the project's owner, or for a reviewer on the two signing routes (`ownership.py:19-20,24-35`).

| Method | Path | Purpose | Auth / roles | Request | Response | Source |
|---|---|---|---|---|---|---|
| POST | /api/v1/projects/{project_id}/plan:sign | Generate the MAP from the plan, sign it (step-up), stage the campaign body; a later call signs deviations (D-14) | `modeler-reviewer` realm role (MiddLead) + project member + owner_guard (reviewer passes as a signing route) + `ensure_step_up` | SignRequest{note} | Envelope[PlanSigned] (plan view + signature) | plan_api.py:518-601 |
| GET | /api/v1/projects/{project_id}/plan | Plan page including `map.campaign` (the start body, with server `file://` URIs) | Writer + member | — | Envelope[PlanPage] | plan_api.py:192-194, 158-184 |
| GET | /api/v1/projects/{project_id}/plan:view | Read-only plan for viewers (also returns `map.campaign`) | Reader + member | — | Envelope[PlanPage] | plan_api.py:197-205 |
| POST | /api/v1/projects/{project_id}/questions/{question_id}/campaign:prepare | Stage CPF, MAP and observed files under `prep/{question_id}` for the one-click path | Writer + member + owner_guard | PrepareRequest | Envelope[CampaignInputs] (cpf/map/observed URIs, sha256s, tier, stages) | write_api.py:182-293 |
| POST | /api/v1/projects/{project_id}/signatures | Generic Part 11 signature on any record_type, record_id, sha256 and meaning (used as `map_approval`) | CurrentPrincipal (**no realm-role check**) + member + owner_guard (owner or reviewer) + step-up | SignatureRequest{meaning, record_type, record_id, record_sha256} | SignatureCreated (no envelope) | signatures_api.py:26-49 |
| GET | /api/v1/projects/{project_id}/signatures | Signature register, escalation decisions on the project's campaigns included | Reader + member | — | Envelope[SignatureRegister] | signatures_api.py:56-85 |
| POST | /api/v1/projects/{project_id}/campaigns | **Start campaign** (202) | Writer + member + owner_guard (owner only) + run guard outside development | CampaignStartRequest{compound, map_id, cpf_uri, cpf_sha256, map_uri, observed_uri, system_uri, system_sha256, question, model_risk (required), stages?, stage_budgets_seconds} | CampaignStarted{campaign_id, status QUEUED, status_url} | campaign_api.py:29-81 |
| — | (stop / cancel / resume a running campaign) | **Does not exist.** grep for cancel, stop, resume and SSE found nothing for campaigns | — | — | — | grep over services/api (§8 D-05) |
| GET | /api/v1/campaigns[?project=] | Tenant's campaigns, filtered by membership; unreadable records named | Reader | — | Envelope[Campaigns] | read_api.py:128-138 |
| GET | /api/v1/campaigns/{campaign_id} | Monitor record (stages, rounds, gof, realData, engine, package, feedback, **resume incl. server URIs**) | Reader; membership checked only if the campaign has a project | — | Envelope[CampaignRecord] | read_api.py:141-155 |
| GET | /api/v1/escalations | Open escalations of the person's projects, each with `can_decide` | Reader; an escalation whose campaign is unknown or has no project stays listed with `can_decide=true` | — | Envelope[Escalations] | read_api.py:286-300 |
| GET | /api/v1/escalations/decision-options | Static MS-01 §4 options (only retry, accept_best, abort; **stale**: lacks approve, learn, new_evidence) | **none** (no principal) | — | DecisionOptions | escalations.py:134-136 |
| POST | /api/v1/campaigns/{campaign_id}/stages/{stage}/escalation:resolve | **Decide an escalation or a gate, local backend**: retry, accept_best, abort, approve (S6 gate), learn, new_evidence | CurrentPrincipal (no realm role) + member + `ensure_owner(signing=True)` (owner or reviewer; QA refused) if the campaign has a project + step-up; 409 if the backend is Temporal, not open, a real-data refusal (approve only) or a feedback guardrail; 404 campaign; 422 runner ValueError | ResolveRequest{action, note, studies, beyond_cap, evidence} | EscalationResolved{campaign_id, stage, action, status, remaining_stages?, note, signature} | escalations.py:199-284 |
| POST | /api/v1/campaigns/{campaign_id}/stages/{stage}/escalation:decide | Temporal decision signal | **No principal**; `X-Tenant-Id` header; password + second_factor in the body; **always 503** (`get_verifier` raises) | SignedDecisionRequest | EscalationDecided | escalations.py:83-84, 100-109, 139-158 |
| POST | /api/v1/campaigns/{campaign_id}/deviations | Signed deviation sent to the Temporal stage workflow | As above: **no principal, password in the body, always 503** | DeviationRequest | DeviationRecorded (201) | escalations.py:111-118, 161-179 |
| GET | /api/v1/campaigns/{campaign_id}/package | S7 summary: exportable, reproduction, hashes, artifacts, PK-Sim projects, issues | Reader; membership if the campaign has a project; 404 before S7 | — | Envelope[CampaignPackage] | read_api.py:195-212 |
| GET | /api/v1/campaigns/{campaign_id}/package/{artifact} | Download package.zip, mar.md, mar.docx or mar.pdf; zip 409 unless exportable (D13); path must resolve under the file:// object-store root | Reader + membership if project; **no audit event** | — | FileResponse | read_api.py:160-165, 215-234 |
| GET | /api/v1/runs/{run_id}/results | Ingested run results (output paths, or one series) | CurrentPrincipal only (**no role, no project check**; tenant from the token) | query: path, individual_id, limit | RunOutputs \| RunSeries | results_api.py:34-58 |
| POST | /api/v1/runs | Submit a single simulation to Temporal | Writer; 503 without a Temporal address | RunSubmission | Envelope[RunAccepted]; `status_url /api/v1/runs/{id}` **does not exist** | system_api.py:105-142 |
| GET | /api/v1/projects/{project_id}/steps | Four steps; the Run step comes from campaign statuses | Reader + member | — | Envelope[Steps] | project_api.py:60-66; steps.py:214-227 |
| GET | /api/v1/projects/{project_id}/audit | Project audit trail (by prefix: campaign decisions are not in it, see signatures) | Reader + member | limit | Envelope[AuditTrail] | project_api.py:120-145 |
| GET | /api/v1/projects/{project_id}/system | Model system for the system panel | Reader + member | — | Envelope[ProjectSystem] | read_api.py:272-283 |
| GET | /health | Status, deployment kind, verifier kind | **none** | — | Health | system_api.py:34-36 |
| GET | /api/v1/me | User id, name, tenant, roles, admin flag | CurrentPrincipal | — | Envelope[MeView] | admin_api.py:105-108 |
| GET | /api/v1/admin/system | Deployment, execution backend, engine check (starts the engine command, up to 20 s, kept 60 s) | `modeler-admin` | — | Envelope[SystemStatus] | admin_api.py:229-237; engine_check.py:52-109 |

OpenAPI (`docs/api/openapi.json`, extracted with python3/json) lists every path above with **only 200/201/202 and 422
responses**. No 401, 403 (STEP_UP_REQUIRED, NOT_OWNER), 404, 409 or 503 is documented. `GET /runs/{id}/results` and
`/package/{artifact}` have no response schema. The response models match the code.

---

## 4. Feature table

| Feature | Purpose | Inputs | Outputs | Source | Status | Evidence note |
|---|---|---|---|---|---|---|
| MAP signing (plan canvas) | MIDD lead signs the MAP; campaign inputs staged | plan, step-up token | signed MapArtifact with `campaign` body | plan_api.py:522-601 | implemented | Reviewer only; 409 if stale or already signed; deviations make a new MAP version |
| MAP approval via generic signature | Older path: sign the prepared MAP's sha256 | map_id, map_sha256 | `signature.create` event, `map_approval` | RunCampaignButton.tsx:39; signatures_api.py:26-49; run_guard.py:62-65 | implemented (bypasses the reviewer rule) | Any owner (curator) with a step-up |
| Campaign start | Run S0–S7 | CampaignStartRequest | campaign_id, QUEUED | campaign_api.py:44-81 | implemented | Run guard only outside development |
| Run guard: signed MAP | Refuse an unsigned MAP (pilot/production) | map_uri | 409 | run_guard.py:46-74 | partial | Trusts the file's own `status/signature` fields |
| Run guard: stage budgets | Budgets come from the signed MAP | stage_budgets_seconds | 422 | run_guard.py:77-82 | implemented | — |
| Run guard: CPF = MAP (D-36) | Run uses the signed parameters | cpf_uri, map_uri | 409 with up to 5 differences | run_guard.py:85-105 | implemented, with risks | Arbitrary `file://` read; error echoes the input |
| Real-data rule (D-19) | No S4/S5 signature on non-real data outside exploratory projects | campaign.realData, project.exploratory | 409 at approve | escalations.py:246-250; local_runner.py:1178-1184 | partial | Applies only to `approve`; `accept_best` on S6 skips it |
| Execution: local | In-process daemon thread | CampaignRequest | campaigns.json records | local_runner.py:1153-1169 | implemented | Lost on restart; no recovery |
| Execution: Temporal | Workflow start | CampaignRequest | workflow id = campaign id | campaign_api.py:64-73 | partial | Decisions are impossible (decide → 503; resolve → 409); monitor feed INFERRED unwired |
| Stop / cancel / resume | Halt a running campaign | — | — | — | **absent** | Only `abort` on an open escalation |
| Live updates | Monitor fills in | — | polling | AutoRefresh.tsx:8-15; EscalationPopup.tsx:34 | implemented (polling) | No SSE; refresh stops at ESCALATED or AWAITING_SIGNATURE |
| Escalation decision (local) | retry, accept_best, abort, approve, learn, new_evidence with a signature | ResolveRequest, step-up | signature; campaign continues on a thread | escalations.py:219-284 | implemented, with gaps | Action not checked against the offered options |
| Escalation decision (Temporal) | Signal workflow | password body | — | escalations.py:139-158 | **placeholder** (503) | Verifier never wired |
| Campaign deviation (Temporal) | Signed deviation | password body | — | escalations.py:161-179 | **placeholder** (503) | — |
| MAP deviation (D-14) | Post-sign plan change becomes a new MAP version | canvas change + plan:sign | MAP v+1 | plan_api.py:267-297, 532-567 | implemented | Reviewer signs |
| Feedback cycles (S5) | learn / new_evidence | studies, beyond_cap, evidence | cycle c+1 | escalations.py:190-216, 252-257; local_runner.py:1198-1218 | implemented (software) | Guardrails checked before the signature |
| VBE display | S6 VBE card | campaign.prediction.vbe | card with validation banner | components/campaign/Vbe.tsx | implemented (UI) | Shown only when a prediction exists |
| S7 package summary | Reproduction, hashes, artifacts | — | CampaignPackage | read_api.py:195-212 | implemented | Server paths not returned here, but `resume` in the campaign record has them |
| Package / MAR download | Get the files | artifact name | file | read_api.py:215-234; PackageDownloads.tsx | implemented | zip only if exportable; no audit; a fixture run's package is not refused |
| Signature register | List a project's signatures | — | rows + chain_verifies | signatures_api.py:56-85 | implemented | — |
| Engine health | Is the engine PK-Sim and does it answer | — | EngineStatus | admin_api.py:229-237 | implemented | Admin only |
| Fixture red banner | Stub runs are never presented as PBPK | campaign.engine.kind | banner | campaigns/[campaignId]/page.tsx:106-114 | implemented, with a hole | No banner when `engine` is null; the list page has no flag |
| Test-only banner | Non-real data | realData | banner | page.tsx:115-121 | implemented | — |
| Deployment banner (dev/pilot) | Say a run is not production Part 11 | campaign.deployment | — | — | **absent** | Field stored (records.py:145), never shown |
| Raw runs tab | Results per run | — | — | page.tsx:22-23 | **absent by design** | Waits for multi-server (R-N08) |
| Review inbox | — | — | redirect to /work | app/review/page.tsx | retired | Owner decision 2026-11-11 |
| QA release | QA signs the bundle | — | — | SignatureMeaning.QA_RELEASED (signatures.py:22) | **absent** | QA may not sign (ownership.py:60) |
| Run results API | Parquet series | run_id | series | results_api.py | implemented (API), unwired in UI | No web caller |

---

## 5. Web sitemap and page-by-page description

```
/                         Home (portfolio; running-campaign count)          components/portfolio/Home.tsx
/work                     Your work: links (escalations "To decide", steps)  app/work/page.tsx
/review                   → redirect /work (inbox retired)                  app/review/page.tsx
/campaigns                Campaigns list (all of the person's projects)      app/campaigns/page.tsx
/campaigns/{cid}?tab=     Campaign monitor
   ├─ stages (default)    stage table, stage notes, time-budget meter
   ├─ fit                 goodness-of-fit chart
   ├─ rounds              round history (sortable), ledger, influence map
   ├─ feedback            S5 diagnosis, cycle timeline, "Open the decision"
   ├─ prediction          (only when S6 gave one) sensitivity, intervals, VBE card
   └─ package             S7 reproduction, hashes, PK-Sim projects, issues, downloads
/projects/{id}            Overview: latest campaign, project work items      app/projects/[projectId]/page.tsx
/projects/{id}/plan       Step 3 Review & sign: Approve and Sign, Run the campaign (P6)
/projects/{id}/campaigns  Step 4 Run: what is missing, Run campaign (one-click), studies, campaigns
/projects/{id}/history?tab=signatures   Signature register (escalation decisions included)
/admin/system             Engine status (kind, reachable, digest), execution backend (admin only)
(shell overlay)           EscalationPopup flash bar + decision dialog; StepUpDialog
```

Campaigns link in the side nav: `components/shell/SideNav.tsx:62`. The Run step's route is
`/projects/{p}/campaigns` (`lib/pipeline.ts:29`).

**/campaigns** (`app/campaigns/page.tsx:6-16`, `components/portfolio/Campaigns.tsx:16-41`). A server read of
`GET /campaigns` and `GET /projects`. The table shows id, project, compound, status, current stage and the share of the
budget used, with a status filter. **No fixture or test-only flag in the list**; the comment says the campaign's own page
says so (Campaigns.tsx:4-5). Empty state: "No campaign has run yet…".

**/campaigns/{cid}** (`app/campaigns/[campaignId]/page.tsx`). A server component.
- Reads `GET /campaigns/{cid}` (`lib/reads.ts:78-80`), and `GET /campaigns/{cid}/package` only on the package tab
  (page.tsx:88).
- Not found: a "not recorded yet" banner and polling (page.tsx:53-68). Any other error: an ApiProblem (no sample data).
- Header: compound, question, status, risk badge. Facts: id, an acceptance line built from a **hard-coded** fold limit
  (high 1.25, low 2, otherwise 1.5; page.tsx:73), the internal target if any, the current stage, and the engine line only
  when it is PK-Sim (page.tsx:104).
- **Red banner** when `c.engine && c.engine.kind !== "pksim"`: "Not a PBPK result: this campaign ran on a software test
  fixture…" for a fixture, otherwise "not identified as PK-Sim… Treat its numbers as unverified" (page.tsx:106-114).
  If `engine` is null there is no banner and no engine line.
- **TEST ONLY banner** when any stage's realData is judged and not passable (page.tsx:76, 115-121).
- AutoRefresh is active only while RUNNING or QUEUED (page.tsx:122).
- Tabs are links with `?tab=` (page.tsx:124-131). The prediction tab is hidden without a prediction (page.tsx:82).
- **Package tab** (page.tsx:294-344):
  - "No package yet" when `c.package` is null; an ApiProblem when the package read fails.
  - Otherwise: reproduced or not, released yes or no, the package and data-bundle sha256 (first 16 characters), the file
    count, the PK-Sim projects, project notes, the report issues table and the report notes.
  - `PackageDownloads` offers one button per artifact the API lists. Each fetch carries the bearer, becomes a blob and is
    saved with an `<a download>`; the object URL is revoked at once (PackageDownloads.tsx:23-38).

**/projects/{id}/campaigns (Run)** (`app/projects/[projectId]/campaigns/page.tsx:20-144`).
- Reads the project, its studies and its campaigns.
- `runnable` = a question, a compound and at least one *uploaded* study (Inputs studies do not count: campaigns/page.tsx:40-47).
  Otherwise StepBlocked lists what is missing.
- `RunCampaignButton`: shows the progress ("Generating the MAP…", "Signing the MAP…", "Starting…") and goes to
  `/campaigns/{id}` on success (RunCampaignButton.tsx:28-64). It is disabled while busy.
- The button shows for any viewer of the page. Role and ownership are not checked here; the API refuses instead
  (INFERRED from the code: there is no role check in the page).

**/projects/{id}/plan (Review & sign)** (`components/plan/PlanCanvas.tsx`).
- **Approve and Sign** is enabled when the validator has nothing open, the plan is not stale, and the plan is unsigned or
  has pending deviations (PlanCanvas.tsx:312). It is shown to any curator or reviewer (`WRITE_ROLES`, PlanCanvas.tsx:224,
  236). **The API requires `modeler-reviewer`** (plan_api.py:68, 523), so a curator gets a 403.
- **Run the campaign (P6)** appears once the MAP is signed with no pending deviations. It posts `view.map.campaign` with
  **no busy or disabled state** (PlanCanvas.tsx:373-380).

**/work** (`app/work/page.tsx`, `lib/portfolio.ts:48-79`). Lists escalations with `can_decide` as "To decide", linked to
the campaign page. Step items are listed for the owner, and the review step also for any reviewer. Nothing is decided on
this page.

**Escalation pop-up** (`components/campaign/EscalationPopup.tsx`).
- Mounted once in the shell (app/layout.tsx:88). It polls `GET /escalations` every 5 s on **every** page and filters to
  `can_decide`.
- It shows a flash bar only on `/campaigns/{cid}` for that campaign, or on `/projects/{p}/*` for that project's campaigns.
  On a project page it also reads `GET /campaigns` to map campaigns to projects.
- "Decide" opens a dialog holding `EscalationDecision`. "Decide later" closes it. `OpenDecisionButton` on the feedback tab
  reopens it with a CustomEvent.

**Decision form** (`components/EscalationDecision.tsx`).
- Facts: stage, reason code in words, evidence. The S5 diagnosis table when feedback exists.
- A select of the stored `options` (disabled options are explained). Learn shows checkboxes, plus a beyond-cap reason
  when a deviation is needed. New evidence takes parameter, value, unit and source. The rationale is **optional**.
- "Sign & submit" opens the confirm dialog ("recorded as an *Approved* signature… your password is never entered").
  Confirm calls `resolveEscalation` with `useMutation`. Afterwards `/escalations` and `/campaigns` are read again and the
  server parts redrawn (EscalationDecision.tsx:16, 45-64).
- **Step-up**: `post()` → `withSession` (lib/api.ts:126-138). On 403 with detail.code STEP_UP_REQUIRED or STEP_UP_STALE it
  calls `requestStepUp()`, which shows StepUpDialog. "Confirm identity" opens
  `window.open('/auth/login?step_up=1&popup=1')` (StepUpDialog.tsx:29-32). The login route adds `acr_values=loa2`
  (auth/login/route.ts:22). The callback stores the tokens and posts `modeler:stepped-up` to the opener
  (auth/callback/route.ts:40-46). The call is then sent **once more**. If the pop-up is blocked, a same-tab fallback loses
  what was typed (StepUpDialog.tsx:42-48).

**History, Signatures tab** (`app/projects/[projectId]/history/page.tsx:62,107`) reads `GET /projects/{id}/signatures`.

**/admin/system** (`app/admin/system/page.tsx:20-80`) shows the engine state, its kind (a fixture in bold as "not PK-Sim:
its numbers are never PBPK results"), the command, the engine id, the digest, and "Runs on this server" or on Temporal.

**e2e coverage** (`apps/web/e2e`).
- `campaign-monitor.spec.ts`: a real run from the Run page, on the stub engine unless `E2E_ENGINE_COMMAND` is set, and a
  check of the engine-warning banner (lines 41-63). Also not-recorded and test-only cases.
- `campaign-tabs.spec.ts`: a seeded campaign and its tabs.
- `escalation-popup.spec.ts`: the flash bar, the dialog focus, and the orphan escalation "can still be decided", which only
  checks that the form opens (lines 94-110). Step-up is mocked with `page.route` returning 403 (lines 112-133).
- `feedback.spec.ts`: a seeded S5 failure.
- `oidc-signing.spec.ts`: real Keycloak, only when `E2E_OIDC_ISSUER` is set.
- Default e2e uses `MODELER_DEV_AUTH=1` and the stub engine (playwright.config.ts:20, 48-58).

---

## 6. Role × action matrix

Realm roles: `deploy/keycloak/realm-modeler.json` (viewer "Read-only…", curator "Propose parameter values; edit CPFs
before signing", reviewer "Review and sign MAPs, escalation decisions and CPF acceptance", qa "QA release of the submission
bundle", admin "Tenant administration"). `tenant_id` and `projects` are user attributes that only an admin may edit
(user-profile config). `username`, `firstName` and `lastName` can be edited by the user, and they feed the printed name on
signatures (auth.py:52).

Step-up flow (realm): browser flow "modeler browser" → conditional "loa1 password" (username+password) or "loa2 signing"
(password + OTP), `loa-max-age` 0 for loa2. `acr.loa.map` = {loa1:1, loa2:2}. Access token lifespan 300 s; SSO idle
1800 s; brute-force protection on. API: acr must equal `loa2` and auth_time must be within 300 s (auth.py:23-24, 163-169).
One step-up can therefore cover several signatures within 5 minutes, although the dialog says "every time"
(StepUpDialog.tsx:39).

Legend: ✓ allowed · ✗ refused (code) · — no such action. "Member" = project membership (token claim or platform);
"Owner" = `memberships.owner(project)`.

| Action (route) | viewer member | curator owner | curator member (not owner) | reviewer owner | reviewer member (not owner) | QA only | admin only | DEV principal (`*`) | Evidence |
|---|---|---|---|---|---|---|---|---|---|
| View campaigns, monitor, escalations, package summary | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ (all company projects) | ✗ 403 role | ✓ | read_api.py:42,50; memberships.py:45-57 |
| Download package / MAR | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ | read_api.py:215-234 |
| Sign MAP via plan:sign | ✗ role | ✗ role (**UI offers it**) | ✗ | ✓ | ✓ (signing route) | ✗ | ✗ | ✓ | plan_api.py:68,523; ownership.py:19-20 |
| Sign MAP via `map_approval` signature (one-click path) | ✓ if owner (edge: no role check) | ✓ | ✗ NOT_OWNER | ✓ | ✓ | ✗ | ✗ | ✓ | signatures_api.py:34-36; ownership.py:54-65 |
| Start campaign | ✗ role | ✓ | ✗ NOT_OWNER | ✓ | ✗ NOT_OWNER (**UI offers it**) | ✗ role | ✗ | ✓ | campaign_api.py:26,49; main.py:91 |
| Cancel / stop campaign | — | — | — | — | — | — | — | — | no route |
| Abort (only when an escalation is open) | ✓ if owner (edge) | ✓ | ✗ | ✓ | ✓ | ✗ | ✗ | ✓ | escalations.py:236-239 |
| Decide escalation (retry, accept_best, learn, new_evidence) | ✓ if owner (edge) | ✓ | ✗ | ✓ | ✓ | ✗ | ✗ | ✓ | same |
| Sign the S4/S5 evaluation (`approve` the S6 gate) | ✓ if owner (edge) | ✓ (self-approval) | ✗ | ✓ | ✓ | ✗ | ✗ | ✓ | same, + gate_refusal escalations.py:248 |
| Sign a MAP deviation (plan:sign with pending deviations) | ✗ | ✗ role | ✗ | ✓ | ✓ | ✗ | ✗ | ✓ | plan_api.py:532-567 |
| Campaign deviation (Temporal `/deviations`) | 503 for everyone (no principal checked) | | | | | | | | escalations.py:83-84,161 |
| Decide on a campaign **with no project** | ✓ any authenticated tenant user, QA and no-role users included | | | | | | | | escalations.py:236-239 |
| Read run results `/runs/{id}/results` | ✓ any authenticated tenant user, no role or project check | | | | | | | | results_api.py:34-36 |
| Engine status `/admin/system` | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ unless it holds admin | admin_api.py:229 |

Edge "viewer owner": `ensure_owner` checks ownership, not roles (ownership.py:54-65). `escalation:resolve` and
`POST /signatures` use `CurrentPrincipal` with no role. An admin can make anyone owner (`admin_api.py:188-215`), so a
viewer-only owner can decide and sign (INFERRED). The DEV principal has viewer, curator and reviewer and `*`, with a fresh
loa2 on every token (auth.py:90-103). It is accepted in **pilot** as well as development (config.py:65-71).

---

## 7. Sequence: signing an escalation decision with step-up (local backend, Keycloak on)

```mermaid
sequenceDiagram
    autonumber
    actor U as Reviewer / owner
    participant B as Browser (EscalationPopup + EscalationDecision)
    participant N as Next proxy (proxy.ts)
    participant KC as Keycloak (realm modeler)
    participant A as API escalation:resolve (escalations.py)
    participant S as File store (campaigns.json, escalations.json, audit.jsonl)
    participant R as LocalCampaignRunner / local_runner
    B->>N: GET /api/v1/escalations (every 5 s)
    N->>A: + Bearer (person's access token)
    A-->>B: escalations[] with can_decide (may_change signing=True)
    U->>B: Decide → choose action, rationale → Sign & submit → Confirm
    B->>N: POST /campaigns/{cid}/stages/{st}/escalation:resolve {action, note, ...}
    N->>A: + Bearer
    A->>A: current_principal (JWKS RS256, admit memberships)
    A->>S: get_campaign; require_project; ensure_owner(signing)
    A->>S: escalation {cid}-{st} still open? (else 409)
    A->>R: gate_refusal (approve only) / check_feedback (409 on refusal)
    A->>A: ensure_step_up: acr==loa2 and auth_time ≤ 300 s?
    A-->>B: 403 {code: STEP_UP_REQUIRED | STEP_UP_STALE}
    B->>B: withSession → requestStepUp → StepUpDialog
    U->>B: Confirm identity
    B->>KC: pop-up /auth/login?step_up=1 → authorize acr_values=loa2 (PKCE)
    U->>KC: password + TOTP
    KC-->>B: /auth/callback → code exchange → cookies → postMessage(stepped-up)
    B->>N: POST escalation:resolve (sent once more)
    N->>A: + Bearer (new token, acr=loa2)
    A->>A: checks again → sign_after_step_up (meaning Approved, record {cid}-{st}, sha = digest)
    A->>S: record_signature → audit append signature.create (+Postgres row in production)
    A->>R: runner.resolve(...)
    R->>S: remove_escalation (claim under file lock; already decided → ValueError → 422)
    R->>S: writer.flush (status RUNNING / ACCEPTED / ABORTED / COMPLETED)
    R-)R: daemon thread: LocalExecutor.run(remaining stages)
    A-->>B: EscalationResolved {status, remaining_stages, signature.manifestation}
    B->>B: useMutation After: read /escalations and /campaigns again, router.refresh()
    B->>N: AutoRefresh every 2.5 s while RUNNING / QUEUED
```

Sources: EscalationPopup.tsx:34-46; EscalationDecision.tsx:45-64; lib/api.ts:126-138, 262-277; StepUpDialog.tsx:12-56;
auth/login/route.ts:8-26; auth/callback/route.ts:17-48; proxy.ts:21-61; escalations.py:219-284; part11.py:39-59;
local_runner.py:1220-1318; filestore.py:183-194.

---

## 8. Defects and risks

Severity is my judgement. CONFIRMED = the code path is unambiguous from the cited lines (not executed). POTENTIAL = it
depends on deployment, data or behaviour I did not verify.

**D-01 CONFIRMED (high, compliance): the server does not check the decision action against the escalation's offered
options. `accept_best` on the S6 gate skips the S4/S5 signature and the real-data rule.**
- The S6 gate's escalation offers only `approve` and `abort` (local_runner.py:105-109, 395-403).
- `escalation:resolve` accepts any of six actions (escalations.py:202) and checks the real-data rule only when
  `action == "approve"` (escalations.py:248).
- In the runner, `accept_best` marks the escalated stage ACCEPTED, appends it to the completed stages and continues with
  the rest (local_runner.py:1277-1306). On the S6 gate that runs S7 without S6 and without an evaluation approval.
- Similarly, `retry` is possible on S4 or S5 although MS-01 §6.6 offers no retry (local_runner.py:100-104), and `approve` on
  an ordinary stage behaves as a retry.
- The UI offers only the stored options (EscalationDecision.tsx:80-82), so this needs a direct API call.

**D-02 CONFIRMED (high): the run guard trusts a MAP's self-declared status and reads any `file://` path the client names.**
- `map_signed` returns True when the JSON at `map_uri` has `status == "SIGNED"` and a non-empty `signature`
  (run_guard.py:56-57). It does not check that the signature exists in the audit chain.
- `map_uri` and `cpf_uri` are client-supplied (campaign_api.py:31-35) and read with `Path(...).read_bytes()` with no root
  restriction (run_guard.py:38-43).
- The D-36 refusal puts the exception text in the response: `detail=f"… does not read: {exc}"` (run_guard.py:99-100). For
  invalid input, pydantic 2.13 includes a truncated `input_value` in that text (checked in the scratchpad with a
  throw-away model). An owner with any signed MAP could therefore read fragments of arbitrary server files in
  pilot/production.
- A forged "SIGNED" MAP needs a JSON file the attacker can place on the server at a known path (POTENTIAL, depends on
  upload paths).

**D-03 CONFIRMED (high, compliance): no separation of duties; curators sign what the realm reserves for reviewers.**
- The realm says the reviewer signs "MAPs, escalation decisions and CPF acceptance".
- But `ensure_owner(signing=True)` passes the **owner** whatever their role (ownership.py:62-65), so a curator owner can
  decide escalations and sign the S4/S5 evaluation for a campaign they ran themselves.
- The one-click path signs the MAP through `POST /signatures` (no role check, signatures_api.py:34-36) as `map_approval`,
  which run_guard accepts (run_guard.py:62-65). That bypasses `plan:sign`'s reviewer-only rule (plan_api.py:68).
- No check stops the person who started the campaign from signing its evaluation.

**D-04 CONFIRMED (medium): the one-click Run campaign button signs a MAP the person never saw.**
RunCampaignButton.tsx:32-55 runs prepare, sign and start in one click. The Part 11 manifestation binds the MAP's sha256,
but no page shows the MAP content before signing.

**D-05 CONFIRMED (high, operations): no cancel, stop or resume, and an interrupted local campaign is stranded.**
- The local runner uses daemon threads (local_runner.py:1166-1168, 1312-1314).
- Startup recovers only Data room runs (main.py:44-69). The campaign record stays `RUNNING`.
- No route can stop it, and no escalation exists to abort it. The Run step stays "running" (steps.py:223-224) and the
  monitor polls forever.
- The `try` only wraps stage execution (local_runner.py:513-531). An exception in S0, `_persist` or `_influence` would end
  the thread silently (INFERRED).

**D-06 CONFIRMED (medium): the Temporal decision and deviation endpoints are inert and violate the password rule.**
- `get_verifier` always raises 503 (escalations.py:83-84). `get_store` returns None.
- `SignedDecisionRequest` and `DeviationRequest` require `password` and `second_factor` (escalations.py:100-118), and they
  appear in openapi.json. `CLAUDE.md` says "signatures come from the token's step-up, never a password in a request".
- These routes take no bearer principal, only an `X-Tenant-Id` header, and have no project check
  (escalations.py:139-179). If a verifier is ever wired, they would be unauthenticated apart from the password.
- With `MODELER_EXECUTION_BACKEND=temporal`, `escalation:resolve` answers 409 (escalations.py:227-229). **No escalation
  can be decided on Temporal.**

**D-07 CONFIRMED (medium): the UI offers actions the API refuses.**
- "Approve and Sign" is enabled for curators; the API needs a reviewer (PlanCanvas.tsx:224, 312, 361 vs plan_api.py:523).
- "Run the campaign (P6)" shows for any writer; the API needs the owner (PlanCanvas.tsx:373; main.py:91).
- Your work lists "Sign the MAP" for a curator owner (portfolio.ts:70).
- An orphan escalation (campaign not recorded) gets `can_decide=true` for every reader, QA and viewers included
  (read_api.py:298-299). Its resolve then answers 404 "campaign not found" (escalations.py:233-235). The e2e test only
  checks that the form opens (escalation-popup.spec.ts:94-110).

**D-08 CONFIRMED (medium): duplicate campaign starts.**
"Run the campaign (P6)" has no busy state (PlanCanvas.tsx:374-379), and the API has no idempotency or job lease for
campaigns (`jobs.Kind` has no campaign kind, jobs.py:22). A double click starts two campaigns on the same inputs.

**D-09 CONFIRMED (medium): the stage list and hashes of a start are not tied to the signed MAP.**
- `CampaignStartRequest.stages` is honoured as given (campaign_api.py:40, 61). The runner drops only SM when it is not
  planned (local_runner.py:1364-1371).
- A pilot/production start can omit S1–S5. The S6 gate's real-data check then sees no judged stage and passes
  (data_origin.py:75-88 returns None for empty summaries).
- `map_sha256` and `observed_sha256` are never set on the CampaignRequest (campaign_api.py:57-62). No API code checks
  that `cpf_sha256` matches the CPF bytes (searched; INFERRED that none exists downstream either).

**D-10 CONFIRMED (medium): `campaign:prepare` reuses its staging path.**
Repeated prepares for the same question overwrite `prep/{question_id}/{cpf,map,observed}.json` (write_api.py:260-266),
while a running campaign keeps reading `map_uri` and `observed_uri` (local_runner.py:593-600, 1120-1133). The signed bytes
can change under a running or queued campaign. The plan path uses `prep/plan-v{n}` and is safe.

**D-11 CONFIRMED (medium, Part 11 audit): signatures are the only campaign events on the hash-chained trail.**
- A campaign start (campaign_api.py), a stage verdict and status change (`writer.flush` rewrites campaigns.json), and a
  package download (read_api.py:215-234) write no audit event.
- A signature is recorded before the decision is applied (escalations.py:270-281). If the claim then loses a race
  (filestore.py:188-194) or `resolve` raises, a signature exists for a decision that was never applied (the 422 path).

**D-12 CONFIRMED (low/medium): authorization gaps on reads and project-less campaigns.**
- `GET /runs/{id}/results` checks only the tenant, with no role and no project (results_api.py:34-36).
- Campaign detail, package and resolve skip the membership and owner checks when `campaign.project` is empty
  (read_api.py:148-150, 182-183; escalations.py:236-239). On such a campaign any authenticated tenant user (QA and no-role
  users included) can sign a decision.
- `GET /escalations/decision-options` and `GET /health` need no authentication; the latter reveals the deployment and
  verifier kinds (system_api.py:34-36).

**D-13 CONFIRMED (low/medium): server paths reach the client although the package route promises otherwise.**
- `GET /campaigns/{id}` returns `resume.request.cpf_uri`, `map_uri` and `observed_uri`, plus `resume.cpf_uri`
  (local_runner.py:479-480, 563-566; records.py:153).
- `plan` and `plan:view` return `map.campaign` with `file://` URIs to every reader (plan_api.py:176, 583-586).
- The design has the browser send server paths back to the start route.

**D-14 CONFIRMED (medium): a non-production run is not shown as non-production on the campaign page.**
`deployment` is stored (records.py:145: "only production signs Part 11") but never rendered (grep in apps/web: only the
admin pages). A pilot running the DEV verifier makes "signed" MAPs and decisions by "Dev User" with no authentication
(auth.py:90-103; config.py:65-71), and the campaign page shows no warning. The fixture banner also does not fire when
`engine` is null (page.tsx:106).

**D-15 CONFIRMED (low): a fixture-engine run is labelled but not blocked.**
Pilot/production require `MODELER_ENGINE_COMMAND` but accept `stub_engine.py` (runtime.py:126-138, 146-151). No code
refuses a start or an export on a software fixture (grep "software-fixture": only labels). The package tab shows
"released" for a fixture run's package; only the top banner says otherwise.

**D-16 CONFIRMED (low): the signature meaning is always "Approved", also for abort and stop.**
DECISION_MEANING = APPROVED (escalations.py:47, 264). An `abort` is recorded as an approval. The rationale is optional
(ResolveRequest.note default "", escalations.py:203).

**D-17 CONFIRMED (low): the fold limits are hard-coded in the UI.**
page.tsx:73 copies the SME-governed acceptance tiers (pbpk_acceptance_criteria.yaml:29-55, "2026.2-draft", UNVERIFIED)
instead of reading the MAP's acceptance. They drift if the ruleset changes.

**D-18 CONFIRMED (low): contract and documentation gaps.**
- OpenAPI documents no 401, 403, 404, 409 or 503.
- `POST /api/v1/runs` returns a `status_url` that does not exist (system_api.py:142).
- `decision-options` lists 3 of the 6 actions (escalations.py:41-45).

**D-19 POTENTIAL (medium): a signed plan of a model system may start as a single compound.**
The `plan:sign` campaign body has no `system_uri` or `system_sha256` (plan_api.py:584-589), and observed PK uses the parent
MW for every row (plan_api.py:576-577). `campaign:prepare` does stage the system (write_api.py:267-272). Needs confirmation
against how plan-path projects carry systems.

**D-20 POTENTIAL (low): monitor and project-step side effects.**
- AutoRefresh stops at ESCALATED or AWAITING_SIGNATURE, so after a decision taken elsewhere the page is stale until
  reloaded.
- The project Run step reports "needs_you" while **any** old campaign is ESCALATED or AWAITING_SIGNATURE, even after a
  later campaign completes (steps.py:221-227).
- The global 5-second poll of `/escalations` calls `list_campaigns` plus `may_change` per escalation for every open tab
  (read_api.py:292-300).

**D-21 POTENTIAL (low): the signer's printed name can be edited by the user.**
It comes from `name` or `preferred_username` (auth.py:52), and the user profile lets the user edit username, first name
and last name. Part 11 manifestations could then carry a name the user chose. Whether a refreshed Keycloak token keeps
`acr=loa2` within the 300-second window is not verified here.

**D-22 POTENTIAL (low): the download may be cancelled.**
`URL.revokeObjectURL` runs right after `a.click()` (PackageDownloads.tsx:32-37), which some browsers cancel.

---

## 9. Open questions

1. Is the one-click `RunCampaignButton` path (prepare → `map_approval` → start) meant to survive in pilot/production? It
   contradicts D-07 (reviewer signs MAPs) and the "MAP from plan" design.
2. Should `escalation:resolve` enforce the escalation's stored `options` (and `disabled`) server-side? Should the S6 gate
   accept anything but approve or abort?
3. How is a Temporal campaign meant to be decided, and how does its monitor reach `campaigns.json`? The decision endpoint
   cannot work today. Is the Temporal backend in scope for the pilot at all?
4. Is a cancel or stop action required (for example a stuck RUNNING campaign after a deploy)? Who may use it, and is it a
   signed action?
5. Should `run_guard.map_signed` verify the signature in the audit chain or the MapArtifact, rather than trusting
   `status` in the file? Should `cpf_uri` and `map_uri` be limited to `<read_root>/<tenant>/prep/`, or replaced by a
   server-side reference to the signed MapArtifact?
6. Separation of duties: must the evaluation signer differ from the campaign starter, and must they hold
   `modeler-reviewer`? What should QA's "QA release" become (meaning `QA Released` exists but no route can use it)?
7. Should a pilot deployment be allowed to start campaigns and sign with the DEV verifier, given its records show "Dev
   User" signatures as if authenticated? Should the campaign page show `deployment`?
8. Should package downloads, campaign starts and stage verdicts be audit events (Part 11 §11.10(e))?
9. Is `GET /runs/{id}/results` meant for the UI? It has no caller and no project-level authorization.
10. Do Keycloak tokens refreshed by `proxy.ts` keep `acr=loa2`? If not, a step-up done in the pop-up might be lost when the
    proxy refreshes before the retry. This needs a live test against the realm.
