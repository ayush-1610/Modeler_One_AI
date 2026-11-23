# Backend Change Requirements (Phase 7, Gate 4)

What the approved design needs from the API beyond what exists. Every proposal is **additive** unless marked, names
the page that needs it, and is verified against today's code and contract (`docs/api/openapi.json`). Nothing here is
built. Each change, when authorised, lands with a failing test first, an OpenAPI snapshot update, regenerated web types
and a `CHANGELOG.md` entry (CLAUDE.md). No proposal touches a locked file unless it says so.

Already done at the owner's go-ahead (2026-11-23): R-S01 (list membership), R-S03 (viewer reads the plan), R-S04
(sign-in on two system routes). See `REMEDIATION_PLAN.md` §1.

## 1. Needed by the design (implementation scope)

### R-N03 · Step state and owner in the project list
| | |
|---|---|
| Needed by | P-01 Home, P-02 Your work, P-03 Projects (today one `GET /projects/{id}/steps` and one `GET /members` per project) |
| Today | `GET /projects` → `ProjectRecord {id, name, compounds, openQuestions, risk, questions, pipeline, blinding, exploratory}` + `archived`. Steps come from `GET /projects/{id}/steps` → `StepRow {step, label, state, reasons, formulation}` (`project_api.get_steps`, computed by `project_steps(ws, campaign statuses)`) |
| Proposal | Add optional `steps: StepRow[]` and `owner_name: str \| null` to each item of `GET /projects` (same computation as `/steps`, same membership filter). Optional query `?with=steps,owner` so other callers keep today's cost |
| Files | `read_api.list_projects` (not locked), `views/` model, OpenAPI, `lib/api-types.ts` |
| Risk | Cost of computing steps for every project: measure with 50 projects; cache per project version if needed |
| Tests | list returns the same steps as `/steps` for each project; a non-member's project absent; `with` omitted → unchanged payload |
| Effort | M |

### R-N05 · List a project's agent runs
| | |
|---|---|
| Needed by | P-19 Agent activity |
| Today | `GET /projects/{id}/agent-runs/{run_id}` → `{run, steps}` (`brief_api.get_agent_run`, reads `agent_jobs.run_record`); no list. Runs are kept under the read root with `project_id`, `tenant_id`, `started_by` (admin plan §4) |
| Proposal | `GET /projects/{id}/agent-runs?limit=&before=` → `{runs: [{run_id, agent, model, started_by, started_at, finished_at, status, input_tokens, output_tokens, refusals, fallback_from}]}`, newest first, membership-checked (Reader). No cost field (cost stays in the admin console) |
| Files | `brief_api.py` or a small `agent_runs_api.py` router; `agent_jobs.py` (a lister beside `run_record`) |
| Tests | only the project's runs; another tenant's run never listed; paging stable |
| Effort | S–M |

### R-N09 · Signature register per project
| | |
|---|---|
| Needed by | P-21 History → Signatures (today filtered in the browser from `GET /audit`) |
| Why it is a requirement | `part11.record_signature` writes each signature as a `signature.create` event on the **company's** audit chain (and a Part 11 row in production), with `resource_id` = the signed record's id. `GET /projects/{id}/audit` keeps only events whose `resource_id` starts with the project id (`project_api.get_audit`), so a signature on a record named otherwise, such as an escalation decision (`{campaign_id}-{stage}`), is **not** in the project's History today (INFERRED from the code; to confirm with a test) |
| Proposal | `GET /projects/{id}/signatures` → `{signatures: [{signature_id, signer_id, printed_name, meaning, record_type, record_id, record_sha256, signed_at, manifestation}]}`: the `signature.create` events of the company chain whose record belongs to the project (its own records, and its campaigns' escalations through the campaign's project), Reader. Today only `POST` exists on that path |
| Files | `signatures_api.py` (not locked); reads only. `compliance/signatures.py` is **locked**: read-only use, no change |
| Effort | S |

### R-S02 (remainder) · Only people who may decide see a waiting decision
| | |
|---|---|
| Needed by | Shell escalation flash, P-02 Your work |
| Today | Since R-S01 only members see an escalation; a member who may not sign (viewer, a curator it is shared with) still sees it and is refused when deciding |
| Proposal | Add `can_decide: bool` to each item of `GET /escalations`, computed with the rule `escalation:resolve` applies (`ensure_owner(..., signing=True)`: the owner, a reviewer it is shared with, or the legacy no-owner rule). The response model gains a view type wrapping `EscalationRecord` (the stored record does not change) |
| Files | `read_api.list_escalations`, `ownership.py` (a boolean form of `ensure_owner`), a view model |
| Effort | S |

### R-S05 · The QA role reads every project of its company (owner's default, not objected)
| | |
|---|---|
| Today | `modeler-qa` is offered by Admin → People (`keycloak_admin.ROLES`) and grants nothing |
| Proposal | Add `modeler-qa` to the read roles (`deps.READ_ROLES`, `read_api._READ_ROLES`, `templates_api._READ_ROLES`); let a QA principal pass project membership for reads in its own tenant (a `"*"`-like read grant computed in `memberships.admit`, never for writes or signatures) |
| Files | `deps.py`, `read_api.py`, `memberships.py` (not locked). **If** the grant must live in `auth.require_project`, `auth.py` is **locked**: own PR, owner's approval |
| Tests | QA reads any project of its tenant, none of another; every write and signature refused |
| Effort | M |

## 2. Wanted soon (not blocking the redesign)

### R-N06 · Live status without polling
| | |
|---|---|
| Needed by | Run status (Data room), campaign monitor, escalation flash, Your work count |
| Today | Polling: the escalation pop-up every 5 s and the sidebar every 30 s on every page; pages re-read on timers. D15 planned SSE |
| Proposal | `GET /events` (SSE, per signed-in person): `{type: run.progress \| campaign.stage \| escalation.opened \| escalation.decided \| dataroom.run, project_id, id, at}`; membership-filtered; the page then re-reads the one resource named. Single node first (in-process queue), Temporal later |
| Effort | L |

### R-N08 · Engine reachability for System status
| | |
|---|---|
| Needed by | P-32 System status |
| Proposal | `GET /admin/system` (Admin) → `{api, execution_backend, engine: {reachable, image_digest, checked_at, detail}, agents: [...], keys_due: n, intake: {...}}`. The engine check is new (the doctor has no engine probe): run the configured engine command's lightest call with a short timeout, cached for a minute; never a simulation |
| Files | `admin_api.py` (not locked); the engine scripts are **locked** and are only called, not changed |
| Effort | S–M |

### R-N07 · Read the platform audit chain
| | |
|---|---|
| Needed by | P-33 Platform audit log (future) |
| Proposal | `GET /admin/audit?since=&kind=&limit=` (Admin) over the owner's chain the console already writes (`admin.view`, `admin.*`), with its chain verification like `GET /projects/{id}/audit` |
| Files | `admin_api.py`; the audit store is **locked** (`modeler_project/audit.py`, `modeler_storage/audit.py`): read-only use, no change |
| Effort | M |

## 3. Retirements (each its own commit, after Gate 4, with the owner's OK)
| Operation | Before removing | Contract |
|---|---|---|
| `GET /proposals` + `FileReadStore.upsert_proposal/list_proposals` + `modeler_agents.literature`, `modeler_agents.parameter_curation` | Confirm no script reads `proposals.json`; delete their tests with them | OpenAPI −1 op, CHANGELOG |
| `POST /campaigns/{id}/feedback:decide` | Move `test_escalation_resolve.py` feedback cases onto `escalation:resolve` with the S5 payload | OpenAPI −1 op |
| `POST /questions/{q}/map:generate` | Confirm the plan canvas's MAP covers every field the tests assert | OpenAPI −1 op |
| `POST /client-review:edit` | Show that every fact the sheet-form card asks for is set through `client-review:finish` | OpenAPI −1 op |
| `GET /templates`, `GET /templates/{id}` | Move `e2e/campaign-monitor.spec.ts` (3 tests) and `deploy/showcase/seed_examples.py` to `POST /projects` + the published-model import; keep `reference_models` (Inputs' published-model source and the T-56 kit use it) | OpenAPI −2 ops |
| `pbpk_domain.snapshot.parameter_transfer` | Science owner confirms fitted values reach PK-Sim through the CPF and `ValueOrigin` | none (no route) |

## 4. Before any multi-server (Temporal) deployment
| Id | Change |
|---|---|
| R-S06 | `escalation:decide` and `/deviations` take `password` and `second_factor` in the body, `signer_id` from the body and the tenant from a header. Rewrite both on the token's step-up as `escalation:resolve` does (signer from the token, tenant from the token, `require_project`, `ensure_owner(signing=True)`), or remove them. `compliance/signatures.py` (**locked**) keeps `sign_record(password=…)` until then; removing it is its own PR |
| — | `GET /escalations/decision-options` lists 3 of the 6 actions; serve all 6 with the rewrite, or retire it |

## 5. Not needed (checked)
- **Recent activity** on the Overview: `GET /projects/{id}/audit` already takes `limit`.
- **Read-only state**: `GET /projects/{id}/members` already returns `owner_name` and `you_change_it`.
- **Roles in the page**: `GET /me` already returns `roles` and `admin`.
- **Open-item counts** on the Overview: computed in the browser from the reads Inputs already makes (`lib/inputsWork.ts`); a
  server summary is optional.
- **Database migrations**: none of the above needs one (the single-node store is files; the Part 11 mirror is unchanged).
