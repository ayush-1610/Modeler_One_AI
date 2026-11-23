# Remediation Plan: screenless operations, bloatware and defects (Gate 2)

The owner asked (2026-11-23) for the screenless API operations and the bloatware to be fixed too, investigated
diligently, with questions where anything is unclear. This plan gives every item a verdict, the evidence (read in code
this session), where it lands in the new sitemap, and what change it needs.

**Scope note.** The charter forbids production changes before Gate 4 and a separate implementation authorisation.
Items marked **S** (security or correctness) are defects in today's product and do not depend on the redesign; Q3
asks whether they may be fixed now in a small separate PR. Everything else is scheduled into the implementation plan.

Effort: S < 1 day · M 1–3 days · L > 3 days. Locked = needs its own PR with the owner's approval
(`docs/architecture/locked-files.json`).

## 1. Security and correctness defects found while verifying (new since Gate 1)

| Id | Defect | Evidence | Fix | Files (locked?) | Effort |
|---|---|---|---|---|---|
| **R-S01** ✅ fixed 2026-11-23 | `GET /campaigns` (no `?project=`) and `GET /escalations` return **every campaign and open escalation in the company**, including projects the person is not a member of. `GET /projects` filters by membership; the two lists do not. Detail routes do check (`require_project`) | `read_api.py:94-100`, `:244-247` vs `:51-57` | Filter both lists by `principal.projects` exactly as `list_projects` does; test with two members of one tenant | `read_api.py` (no) + API test; contract unchanged | S |
| **R-S02** ◐ partly fixed by R-S01 (non-members no longer see it) | The escalation pop-up (`EscalationPopup`, polls `/escalations` every **5 s** on every page) shows decisions to people who cannot sign them (the decide route then refuses). With R-S01 it also leaks names across projects | `EscalationPopup.tsx:32`; `escalations.py` `ensure_owner(signing=True)` | After R-S01, show the decision only where the person may sign; in the redesign move it to the project's flash bar and Your work (sitemap §1) | web only | S (now) / part of redesign |
| **R-S03** ✅ fixed 2026-11-23 | A **viewer gets 403 on Review & sign**: the page reads `GET /plan`, which requires a writer; `GET /plan:view` (reader) exists for this and is never used | `plan_api.py:190-203`; `lib/plan.ts:30` | Read `plan:view` when the person cannot write (from `GET /members` `you_change_it` or the role) | web only | S |
| **R-S04** ✅ fixed 2026-11-23 | `POST /model-versions/preview` and `POST /m15/validate` have **no authentication**: anyone who reaches the API can make it build and validate snapshots (CPU) | `system_api.py:48`, `:85` (no principal dependency) | Add `require_role("modeler-curator", "modeler-reviewer")`; OpenAPI gains 401/403 responses; CHANGELOG | `system_api.py` (no), `docs/api/openapi.json` | S |
| **R-S05** | The `modeler-qa` role can be given in Admin → People but grants nothing; a QA person cannot read anything | `keycloak_admin.py:32`; `deps.READ_ROLES` lacks it | **Proposed default:** QA reads every project of its company, no writes, no signing. Add to read roles and admit company-wide reads for QA | `deps.py`, `read_api.py` (no); `auth.py` **locked** only if `require_project` must change | M |
| **R-S06** ⏸ waits for the multi-server setup (owner) | `escalation:decide` and `/deviations` (the Temporal path) take **`password` and `second_factor` in the request body**, the signer's id from the body and the tenant from a header, with no bearer token. CLAUDE.md: "signatures come from the token's step-up, never a password in a request". Inert today: their verifier always answers 503 | `escalations.py:84-118`, `:121-130`, `get_verifier` | Before any Temporal deployment: rewrite both on the token step-up as `escalation:resolve` does, or remove them with `decision-options`. Until then, mark deprecated in OpenAPI | `escalations.py` (no); `compliance/signatures.py` **locked** if `sign_record(password=…)` is removed | M |
| R-S07 | Not a defect, a design note: each agent run record starts with `cost_usd: 0.0`; cost is priced at read time in `/admin/usage` | `run_store.py:45`; admin plan §1, §4 | Agent activity (P-19) shows tokens; cost only in the admin console | — | — |

## 2. The 25 screenless API operations

**Corrected at Gate 4:** 25, as the owner said at Gate 1. Gate 1 counted 21 and Gate 2 22: a path-only match took
`POST /projects`, `PUT /projects/{id}/compounds/{compound}/cpf` and `POST /projects/{id}/studies` as used because a GET
shares their path (#23–#25), and `/deviations` was miscounted as used (the plan canvas only reads a `deviation` flag).

| # | Operation | What it does (verified) | Verdict | Home in the sitemap | Change needed |
|---|---|---|---|---|---|
| 1 | `GET /projects/{id}/plan:view` | Read-only MAP for readers | **Expose** | P-14 | web (R-S03) |
| 2 | `POST /plan/placements/{s}:unlock` | A moved study back to the MS-01 default, recorded as a deviation after signing | **Expose** | P-14 "Back to the MS-01 default" | web |
| 3 | `POST /projects/{id}/impact` | What saving a new version would change and make stale; saves nothing | **Expose** | P-11, P-13, P-14 "What this changes" | web |
| 4 | `GET /projects/{id}/agent-runs/{run}` | One agent run's record and steps, tenant- and project-scoped | **Expose** | P-19b | web + **new list route** `GET /projects/{id}/agent-runs` (R-N05) |
| 5 | `GET /campaigns/{id}/package` | Reproduction verdict, hashes, files, PK-Sim projects, report notes and issues | **Expose** | P-16 Package tab | web |
| 6 | `GET /health` | Liveness (used by `deploy/server/qualify.py`) | **Expose** | P-32, top bar dot | web |
| 7 | `GET /requirements` | The data checklist: derived from the brief, never approved; also feeds delivery cards internally | **Expose** (owner, Q1) | P-13b Data plan, read-mostly | web |
| 8–9 | `PUT /requirements/{r}`, `POST requirements:derive` | Provider and purpose overrides; re-derivation (already runs on every brief save) | **Keep API-only**: edits stay on the cards, and no card edits a requirement today | — | — |
| 10–11 | `GET /templates`, `GET /templates/{id}` | Project starting points of the removed create-project wizard: the published Dapagliflozin model (real clinical data) and an illustrative Aciclovir set. **Not** the VBE/DDI analysis templates (Gate 1 said so; corrected) | **Retire** (owner, Q2), **after** moving its two consumers: `e2e/campaign-monitor.spec.ts` (3 tests build their projects from it) and `deploy/showcase/seed_examples.py`. The importer stays: it serves Inputs' "published model" source and the T-56 kit | — | OpenAPI + CHANGELOG + the two consumers |
| 12 | `POST /model-versions/preview` | Build and validate a snapshot without saving | **Keep API-only** | — | auth (R-S04) |
| 13 | `POST /m15/validate` | Validate an M15 table | **Keep API-only** | — | auth (R-S04) |
| 14 | `POST /runs` | Submit an engine run; 503 unless Temporal is configured | **Keep for Temporal** | P-16 Runs tab later | — |
| 15 | `GET /runs/{id}/results` | Ingested Parquet results (T-08), distributed path | **Keep for Temporal** | P-16 Runs tab later | — |
| 16 | `POST /campaigns/{id}/stages/{s}/escalation:decide` | Temporal signal with a password-based signature | **Rewrite or remove** | — | R-S06 |
| 17 | `POST /campaigns/{id}/deviations` | Same, for a MAP deviation | **Rewrite or remove** | — | R-S06 |
| 18 | `GET /escalations/decision-options` | Lists 3 actions (retry, accept_best, abort); `escalation:resolve` accepts 6 (adds approve, learn, new_evidence) | **Retire, or extend to all 6 with R-S06** | — | R-S06 |
| 19 | `POST /campaigns/{id}/feedback:decide` | A thin alias calling `escalation:resolve` at stage S5 | **Retire** (duplicate) | — | OpenAPI + tests + CHANGELOG |
| 20 | `POST /questions/{q}/map:generate` | Stateless MAP JSON from a client-supplied CPF; persists nothing | **Retire** (the plan canvas persists and signs the MAP) | — | OpenAPI + tests + CHANGELOG |
| 21 | `POST /client-review:edit` | Edit one study fact on the sheet-form path before confirming | **Verify, then retire**: the sheet-form card takes facts through `client-review:finish`; confirm no fact can only be corrected through `:edit` | — | OpenAPI + tests |
| 22 | `GET /proposals` | Tenant-wide agent parameter proposals | **Retire with its dead chain**: `FileReadStore.upsert_proposal` has no production caller, so the list is always empty; its only writers are the unwired `literature` and `parameter_curation` agents. Plan proposals (A5) are separate and in use | — | see R-B13 |
| 23 | `POST /projects` | Create a project from a CPF (the scripted campaign path) | **Keep API-only**: `deploy/reference/run_reference.py`, case studies, showcase, e2e and API tests build projects with it | — | — |
| 24 | `PUT /projects/{id}/compounds/{compound}/cpf` | Write a CPF directly | **Keep API-only** (same scripts and tests); the product writes values through Inputs | — | — |
| 25 | `POST /projects/{id}/studies` | Upload observed studies (scripted path) | **Keep API-only** (same scripts and tests); the product's data arrive through the Data room and Inputs | — | — |

## 3. Bloatware: verdicts after verification

| Id | Candidate | Verdict | Action | When |
|---|---|---|---|---|
| R-B01 | Two intake UIs | **Resolved by G1-1** | One "Data" section, two pages with separate jobs; drop "the earlier page" links; Inputs' four status words in the Data room. Open: the official send (later) | Redesign |
| R-B03 | `escalation:decide` beside `:resolve` | See #16, R-S06 | — | Before Temporal |
| R-B04 | `/review` redirect | Keep, retarget to `/work` | web | Redesign |
| R-B05 | `components/ui.tsx` beside `components/kit` | Merge into one design-system kit | web | Redesign |
| R-B06 | 46 raw tables vs 10 sortable | One table component (sort, filter, columns, counts, empty state) | web | Redesign |
| R-B07 | 20 CSS files in cascade order | Replace with token-based styles; keep `targets.css` rules as requirements | web | Redesign |
| R-B08 | 39 inline styles | Tokens / utilities | web | Redesign |
| R-B09 | Motion system (spring, magnetic, parallax, burst, counters) | Remove (G1-2); keep `prefers-reduced-motion` respect and short state transitions | web | Redesign |
| R-B10 | Decorative hero on every page | Compact header (G1-2) | web | Redesign |
| R-B11 | `lib/words.ts` 1,266 lines, `lib/inputsWork.ts` 1,598 | **Keep** (owner rules); split by area, no behaviour change | web | Redesign |
| R-B12 | `delivery_routes.py` 2,085 lines; `DeliveryReview.tsx` 1,062; `InputsWorkspace.tsx` 922 | Split by concern, no behaviour change | API, web | Implementation, own PRs |
| R-B13 | Dead chain: `GET /proposals`, `FileReadStore.upsert_proposal`/`list_proposals`, `modeler_agents.literature` (244 lines), `modeler_agents.parameter_curation` (237) | **Remove** after the owner's OK (High: no production caller; `documents.py` only mirrors a shape in a comment) | API, storage, agents + tests + OpenAPI + CHANGELOG | After Gate 4 |
| R-B13b | `pbpk_domain.snapshot.parameter_transfer` (50 lines) | **Remove** after the science owner confirms: fitted values reach PK-Sim through a new CPF version and the builder's `ValueOrigin` (`cpf/build.py:367`), so the override path is unused (D3) | domain + tests | After Gate 4 |
| R-B13c | `pbpk_domain.requirement_drafts` | **Keep**: inert by the owner's decision (biologics, dermal, ocular drafts await a named scientist) | none | — |
| R-B13d | Evaluation tooling (`value_score`, `value_key`, `key_compare`, `arrival_eval`, `format_inventory`, `intake_fixtures`, `modeler_agents.evals`, `llm_check`) | **Keep**; optional move under an `evals` package later | none | — |
| R-B13e | Temporal and S3 entry points (`*.worker`, `workflows`, `objectstore`) | **Keep** (distributed path, built, not deployed) | none | — |
| R-B13f | `pbpk_domain.ddi_static` | **Keep**, FUTURE feature (needs SME sign-off of its ruleset) | none | — |
| R-B14 | Dashboard `/steps` N+1 | Add step state to `GET /projects` (R-N03) | API + OpenAPI | Implementation |
| R-B15 | Polling: sidebar every 30 s and pop-up every 5 s on every page | One shared status read; later SSE (R-N06) | web, later API | Redesign |
| R-B16 | `modeler-qa` grants nothing | R-S05 | — | — |
| R-B17 | Stale docs: README calls the web app "starters"; `lib/writes.ts:39` cites a wizard that is gone; `read_api.py` docstrings say "review inbox" | Update | docs, comments | With the next change to each file |

## 4. New backend changes the sitemap needs

| Id | Change | For | Effort |
|---|---|---|---|
| R-N03 | Step state (and owner name) in `GET /projects` | P-01, P-02, P-03 without N+1 | M |
| R-N05 | `GET /projects/{id}/agent-runs` (list: agent, model, started_by, times, status, tokens) | P-19 | S–M |
| R-N06 | One status stream (SSE) for runs, Data room, campaigns, escalations | Live status, removes polling | L |
| R-N07 | Read route for the platform audit chain | P-33 (future) | M |
| R-N08 | Engine reachability check for non-admin status | P-32 | S |

## 5. Order proposed
1. **Done 2026-11-23 (owner, Q3):** R-S01, R-S03, R-S04, each with a failing test first; OpenAPI and web types
   regenerated; CHANGELOG. R-S02's remainder (a member who may not sign still sees the pop-up; the decision is then
   refused in words) moves into the redesign's flash bar and Your work.
2. **Gate 3–4:** the redesign absorbs R-B01, R-B04–R-B10, R-B15, the five "Expose" items and P-19's list route.
3. **Implementation:** R-N03, R-N05, R-B12 splits, R-S05 (after the owner confirms QA's scope).
4. **After Gate 4, with the owner's OK:** retire #19–#22, the two `/templates` routes (after their consumers move) and
   the dead chain (R-B13, R-B13b), each removal its own commit with OpenAPI and CHANGELOG.
5. **Before any Temporal deployment:** R-S06.
