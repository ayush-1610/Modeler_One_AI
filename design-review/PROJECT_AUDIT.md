# Project Audit — Modeler One (Phase 0, Gate 1)

**Date:** 2026-11-22 · **Scope:** read-only discovery for the AWS-console-inspired redesign charter ·
**Base:** branch `claude/inspiring-einstein-191gn3` at `cf3f6ec` (= `origin/main` `61ffb53` + 2 commits, see §9).

Evidence labels used throughout:
- **VERIFIED**: read in code, run, or seen in a screenshot this session (path or command given).
- **INFERRED**: a reasonable reading of evidence, not proven.
- **UNKNOWN**: searched for and not found; logged in [`UNKNOWN.md`](UNKNOWN.md).

Companion documents: [`FEATURE_INVENTORY.md`](FEATURE_INVENTORY.md) (every capability, classified),
[`BLOATWARE_REPORT.md`](BLOATWARE_REPORT.md), [`PROPOSED_FEATURES.md`](PROPOSED_FEATURES.md),
[`UNKNOWN.md`](UNKNOWN.md), screenshots of today's UI in [`current-state/`](current-state/).

---

## 1. What the product is

| | Finding | Evidence |
|---|---|---|
| Purpose | Automates PBPK (physiologically based pharmacokinetic) model development on the open-source OSP engine (PK-Sim 12.3, ospsuite R 12.4.x), from a client's proposal and data delivery to a signed ICH M15 assessment table and a reviewer-reproducible submission package (21 CFR Part 11). | VERIFIED `README.md`, `docs/CONTINUATION_PACKAGE.md` §"30-second system state" |
| Value proposition | Replace weeks of manual PK-Sim work (reading client files, entering parameters, fitting, documenting) with an audited pipeline where **AI describes, code computes, the modeler decides** and every number traces to its source cell or page. | VERIFIED `CONTINUATION_PACKAGE.md` §4.0d "Principle"; §4.0b "the LLM proposes the mapping, code reads the values" |
| Business model | A PBPK service provider (CRO-style) running models for client sponsors; "companies" are tenants. | INFERRED from `config.py` `tenancy_mode: saas-pooled / cro-silo / onprem-single`, admin plan "client will see and decide later" |
| Scientific procedure | MS-01: S0 readiness → S1 IV → S2 oral fasted → S3 formulation/fed → SJ joint refinement → S4 internal validation → S5 external validation (feedback cycles) → S6 prediction → S7 report & package. SJ, feedback cycles and SM (metabolites) are UNVERIFIED pending SME sign-off. | VERIFIED `docs/PBPK_MODELING_WORKFLOW.md` (locked), `CONTINUATION_PACKAGE.md` |
| Honest limit | Every stage runs on real PK-Sim only on known-truth synthetic data so far; real clinical data is the open item. | VERIFIED `CONTINUATION_PACKAGE.md` line 28 |

### 1.1 Users and roles (as implemented)

| Role | Source | What the code lets it do |
|---|---|---|
| `modeler-viewer` | Keycloak realm role | Read any project it is a member of (`deps.READ_ROLES`) |
| `modeler-curator` | Keycloak realm role | Read + write (`deps.WRITE_ROLES`), but only on projects it **owns** (`ownership.owner_guard`) |
| `modeler-reviewer` | Keycloak realm role | As curator, plus signs MAP / records / escalation decisions on projects shared with it (`ownership.SIGNING_ROUTES`), `MiddLead` routes (`plan_api`, `project_api`) |
| `modeler-qa` | Keycloak realm role | **Assignable in Admin → People, but no API route checks it.** VERIFIED `keycloak_admin.py:32`; no other reference in `services/api` |
| `modeler-admin` | Keycloak realm role, owner only | The whole `/admin` console (23 routes, `admin_api.Admin`); every change needs a fresh step-up |
| Project owner | `members.json` (creator) | The only person who changes a project; others it is shared with read it (owner decision 2026-11-10) |
| Dev principal | `MODELER_DEV_AUTH=1` | DEV ONLY: viewer+curator+reviewer, every project (`"*"`), a fresh step-up; no admin. Refused in production (`check_auth`) |

Signatures: 21 CFR Part 11 e-signatures come from the token's step-up (`acr=loa2`, `auth_time` ≤ 300 s,
`auth.ensure_step_up`); the platform never takes a password. VERIFIED `services/api/src/modeler_api/auth.py:163`.

Personas (INFERRED from plans and copy): **PBPK modeler** (owner of a project, does the work), **reviewer / middle
lead** (signs MAP and escalations; second-person approval), **QA** (role exists, no screens), **platform owner**
(admin console), and the **client** (sends data, receives data requests; has no login).

---

## 2. Architecture as built

```
Browser ── Next.js 16.4 app router (apps/web, :3000) ── /api/* proxy (proxy.ts, server.mjs) ──┐
                                                                                             ▼
                          FastAPI "Modeler One API" 0.1.0 (services/api, :8000, 19 routers, 183 ops)
                             │ file-backed project store (MODELER_READ_ROOT, per tenant), hash-chained audit JSONL
                             │ optional Part 11 mirror in PostgreSQL (RLS)            │ agents (services/agents)
                             ▼                                                        ▼  Bedrock / GroqCloud / NVIDIA /
              LocalExecutor (in-process campaigns)  or  Temporal (built, not deployed)    in-house Ollama via LiteLLM
                             ▼
              engine worker: Rscript run_job.R / run_pi.R → PK-Sim 12.3 on Linux (server), Docker image
```

Layers L0–L7 with imports pointing down only, enforced by `tests/architecture/` (VERIFIED
`docs/ARCHITECTURE_BOUNDARIES.md`, `tests/architecture/boundaries.toml`):

| Layer | Package | Role | Size (tracked files) |
|---|---|---|---|
| L0 | `packages/pbpk-domain` (`pbpk_domain`) | CPF schema, snapshot builder, acceptance, MAP, split, diagnostics, M15, DDI static, VBE stats, rulesets (locked, SME) | 127 |
| L1 | `packages/run-contracts`, `packages/storage` | payloads, ports, object store, Part 11 audit | 7 + 16 |
| L2 | `packages/data-intake` (`modeler_intake`) | raw vault, workbook/PDF/DOCX/OCR readers, mapping, PK-Sim observed data | 80 |
| L3 | `packages/project-model` (`modeler_project`) | project store, brief, evidence, inputs, delivery ledger, Data room engine, members, blinding | 151 |
| L4 | `services/agents` (`modeler_agents`) | A1–A10 agents, providers, failover chain, evals | 56 |
| L5 | `services/orchestrator` | campaigns, fitting, feedback, Temporal workflows | 40 |
| L6 | `services/api` (`modeler_api`) | FastAPI routers, auth, ownership, signatures, admin | 117 |
| L7 | `apps/web` | Next.js UI | 291 |

Runtime today (VERIFIED `CONTINUATION_PACKAGE.md` line 18–22): **single node**: web → API, campaigns in-process
(`MODELER_EXECUTION_BACKEND=local`), file-backed stores, PK-Sim on one Linux server. Temporal, PostgreSQL with RLS,
Keycloak, MinIO are built and tested in code but **not deployed** (Keycloak go-live branch exists per the admin plan;
deployment state UNKNOWN).

### 2.1 Frontend stack (VERIFIED `apps/web/package.json`)
Next.js ^16.4.6, React ^19.1, TanStack Query ^5.59 (via one `useResource` hook in 40 files), plotly.js-dist-min ^3
(two charts), pdfjs-dist ^4.10 (source viewer, digitizer), openapi-typescript 7.13 (typed client checked in CI),
Playwright 1.56.1 (54 specs). No component library, no CSS framework: 20 hand-written CSS files (2,898 lines) loaded
in a fixed cascade order in `app/layout.tsx`. IBM Plex Sans/Mono self-hosted. Light theme only (owner, 2026-11-07).

### 2.2 Backend stack (VERIFIED)
FastAPI, pydantic (frozen domain models), uv workspace, Python 3.12, ruff. Persistence: files under
`MODELER_READ_ROOT` per tenant plus an append-only hash-chained audit; Alembic SQL migrations (locked) for the
PostgreSQL mirror. Agents call providers through Anthropic's SDK (Bedrock) or OpenAI-compatible clients.

---

## 3. Frontend: routes and what each does (VERIFIED by reading `apps/web/app/**/page.tsx`)

| Route | Page (as titled) | Who | What it holds | Sub-views |
|---|---|---|---|---|
| `/` | Dashboard | all | Hero, 4 KPI tiles (projects, running, needs you, open questions), search, filter chips, Cards/List toggle, project cards with 4-step progress, "Needs your attention", "Risk across programs"; List = table with archive/restore | Cards · List |
| `/projects/start` | Start from proposal | writer | Drug, name, files with document tags; tag proposals decided in one click | — |
| `/projects/[id]/start` | Start (Step 1 of 4) | member | The brief the A1 agent read from the proposal: drug identity (PubChem CID, SMILES), question of interest, model risk drafts, files | numbered sections |
| `/projects/[id]/inputs` | Inputs (Step 2 of 4) | member | Task-first workspace: status line, "Next" action, 7 areas | To do · Compound · Products and dissolution · Clinical studies · Populations and individuals · Simulation settings · Client files |
| `/projects/[id]/dataroom` | Data room (Inputs, new path) | member | Drop zone + Run, stage progress, rail of 13 sections with status dots, source drawer, decisions, data requests, PK-Sim inputs, signed "Send to the model" | Overview · Files · Drug substance · ADME and disposition · Formulation · Solubility · Dissolution · Clinical studies · Observed PK · Decisions · Data requests · Simulation plan · PK-Sim inputs |
| `/projects/[id]/dataroom/report` | Evidence report | member | Printable report of the Data room | — |
| `/projects/[id]/plan` | Review & sign (Step 3 of 4) | member; sign: owner/reviewer | MAP plan canvas: drag-and-drop study placement with reasons, live MS-01 validator, approve and sign | Studies and roles · The inputs · The estimation plan · The validation plan · Applications · Credibility · Validator and changes |
| `/projects/[id]` | Run (Step 4 of 4) | member | Run a campaign, compounds, observed studies (first 10), model system panel, campaigns table, questions of interest, members | — |
| `/campaigns/[id]` | Campaign monitor | member | Fixture banner when not on PK-Sim, stage progress S0–S7, time budget, goodness-of-fit plot (log toggle), round history, external-validation feedback, package downloads | — |
| `/projects/[id]/compounds/[c]` | Compound Parameter Framework | member | CPF table: parameter, value, unit, provenance, reference, fittable stages | — |
| `/projects/[id]/library` | Project Document Library | member | Every document with what cites it; find, filter, open, withdraw/restore, tags | — |
| `/projects/[id]/history` | History | member | Audit trail, stale artifacts, artifact versions | — |
| `/review` | (redirect) | — | Redirects to `/` since the review inbox was removed 2026-11-11 | — |
| `/admin` | Admin console | `modeler-admin` | All companies, the platform | — |
| `/admin/companies/[t]` | Company | admin | People with projects and use; projects with members | — |
| `/admin/usage` | Usage and cost | admin | By agent, person, project, company, day | — |
| `/admin/models` | Agents / models | admin | Per-agent provider and model, set every agent, failover chain | — |
| `/admin/keys` | Keys | admin | Add, test, activate, retire provider keys | — |
| `/admin/limits` | Limits | admin | Monthly spend/token limits with warnings | — |
| `/admin/people` | People | admin | Keycloak people and companies: add, change roles, move, disable, reset | — |
| `/admin/pipeline` | Intake pipeline | admin | Pipeline health | — |
| `/auth/login`, `/callback`, `/logout` | route handlers | — | OIDC Authorization Code + PKCE | — |

Global shell (VERIFIED `components/Nav.tsx`, `app/layout.tsx`): a 64 px icon rail that opens on hover/focus and can
be pinned; groups **Work** (Projects, Start from proposal), **Platform** (Admin console, admin only), **This project**
(Add data, Data room, Project Document Library, History); person and an API "live" dot at the foot; skip link; a
global escalation pop-up on any page (`EscalationPopup`). **The four project steps (Start, Inputs, Review & sign,
Run) are not in the sidebar**; they live in a step bar under each page's hero.

---

## 4. Backend surface (VERIFIED: `docs/api/openapi.json` 165 paths / 183 operations; AST pass over routers)

| Group (OpenAPI tag) | Ops | Router | Highlights |
|---|---|---|---|
| client-data (incl. delivery) | 41 | `client_api.py`, `delivery_routes.py` (2,085 lines) | uploads, sheet reading, mapping review, values assign, regions exclude, spot check, signed confirm, reading queue, client request `.xlsx` |
| admin | 24 | `admin_api.py` | `/me`, overview, companies, usage, agents and chain, keys, limits, people, pipeline |
| plan | 18 | `plan_api.py` | MAP draft, structure, placements, fits, groups, layout, proposals, violations, rebase, sign |
| evidence | 16 | `evidence_api.py` | evidence, literature research, published model, datasets, digitize, value reuse |
| brief | 16 | `brief_api.py` | initiate project, documents and library, pages, figures, raw, brief extract/edit, agent run |
| dataroom | 15 | `dataroom_api.py` | uploads, run, room, files/pages/parts, question, decisions, entered, requests, publication, publish |
| read | 11 | `read_api.py` | projects, project, CPF, campaigns, package, studies, system, escalations, proposals |
| project-pipeline | 10 | `project_api.py` | steps, stale, artifacts, history, impact, audit, blinding, reveal |
| escalations | 5 | `escalations.py` | decision options, decide, resolve, deviations, feedback |
| others | 27 | write, inputs, members, requirements, templates, campaigns, archive, signatures, results, system | CPF write, system, studies, campaign prepare/start, members, archive/restore, signatures, run results, health |

Cross-check of the UI against the contract (script in session scratchpad): **161 of 183 operations are called by
the web app; 22 are not** (Gate 2 correction: `deviations` was miscounted as used) (listed in `FEATURE_INVENTORY.md` §3). No web call targets a path missing from the
contract. VERIFIED.

Asynchronous work is **polled**, not streamed: the sidebar polls `/escalations` every 30 s; reading queues, Data room
runs and campaigns are re-read by the page. No SSE or WebSocket route exists (VERIFIED: none in the contract),
although decision D15 planned SSE (`CONTINUATION_PACKAGE.md` §1).

---

## 5. Data model (summary; INFERRED from module docstrings, VERIFIED where cited)

Per tenant, per project, in the file store: **project** → brief (question of interest, risk, applications) →
**documents** (content-addressed library, tags, withdrawn state) → **client data** (files, sheets, mappings, ledger
of anchored values, subjects: studies, products, batches, analytes) → **evidence** (literature and client values with
source and grade) → **inputs** (CPF per compound, choices) → **plan / MAP** (signed, hashed) → **campaigns** (stages,
rounds, escalations, feedback cycles) → **package**. Every artifact is versioned with provenance and approvals
(`modeler_project.artifacts`, `deps.version_view`); stale artifacts are tracked when inputs change. Platform level:
`_platform/` limits, keys (AES-GCM under `MODELER_MASTER_KEY`), agent settings, the owner's audit chain.

---

## 6. Current design language (VERIFIED: screenshots in `current-state/`, `app/globals.css`)

- Apple-like consumer look adopted 2026-11-07 from a Claude Design mockup (`docs/plans/2026-11-06-app-design-merge.md`
  §5): bench `#F5F5F7`, ink `#1D1D1F`, indigo brand `#3B1F7A`/`#4B2A99`, 24 px card radius, long soft shadows, pill
  buttons, a large centred gradient hero with a decorative curve on every page, a floating pill step bar,
  spring/magnetic/parallax motion, light only.
- Accessibility work is real and must be kept: skip link, focus management (`kit/focus.ts`), live regions, WCAG 2.2
  target sizes (`targets.css`), text-grade colour twins ≥ 4.5:1, verdicts written in words.
- Plain-language vocabulary is a product rule: `lib/words.ts` (1,266 lines) maps engine/PK-Sim terms to words; status
  words fixed to **Missing · To confirm · To decide · Done**; no engine ids on screen (owner rules, plan 2026-11-14 §2).

**Observed problems for an operational console** (VERIFIED in screenshots):
1. The hero consumes 300–420 px of every page before content (`01-dashboard.png`, `02-start.png`).
2. Long single-column scroll pages: Review & sign renders at 6,796 px tall at 1600 px wide (`05-review-and-sign.png`);
   Inputs at 2,965 px (`03-inputs-todo.png`).
3. No persistent location: the step bar is the only project navigation; project pages are absent from the sidebar.
4. Two intake paths shown side by side: Inputs ("Open in the Data room") and the Data room ("The earlier Inputs page").
5. Dense text sentences replace structure in places (e.g. the Run page's "Run a modeling campaign" paragraph).
6. Low information density in tables; few resource tables with sort/filter (10 `SortableTable` users vs 46 files with
   raw `<table>`).
7. In the Data room full-page capture, the sticky sidebar is drawn mid-page over the content (`04-dataroom.png`).
   INFERRED: a full-page screenshot artefact of `position: sticky`, possibly not visible in a live browser.

---

## 7. Quality gates and tests (VERIFIED)

| Gate | Where | State this session |
|---|---|---|
| `make test` (pytest) | CI `test` | Not run here (long). Last recorded: 3,188 passed, 15 baseline environment failures (`CONTINUATION_PACKAGE.md` §4.0c) |
| `make lint` (ruff) | CI `lint` | Not run here |
| web typecheck (incl. OpenAPI drift check) and build | CI `web` | Build ran as part of e2e: **passed** |
| Playwright e2e | CI `web` | **35 of 35 passed** (16 specs: dashboard, shell, start, inputs, Data room, plan, review-sign, campaign monitor, library, admin, members, VBE, feedback), stub engine, throwaway data dir |
| Architecture: boundaries, locked files, OpenAPI contract, config reads, web client | `tests/architecture/` | Not run; a `design-review/` folder of .md/.html/.png is outside every pattern (checked `test_*`) |
| Secret scan (gitleaks), Trivy, API image, release evidence | CI | Not run; prototype mock data must not resemble keys |

Every engine number in e2e comes from `deploy/dev/stub_engine.py`: software evidence only, never PBPK evidence.

---

## 8. Constraints any redesign must respect (VERIFIED, from CLAUDE.md and owner decisions)

1. **No invented science words, PK-Sim names or units** on screen; harvested names only; plain words via `lib/words.ts`.
2. **No sample data presented as results.** A page shows why it could not read the API; never demo numbers, never a
   decorative concentration-time curve (owner rejected both in the 2026-11-06 mockup review, §2.2).
3. **Part 11:** signatures only via step-up; nobody acts as another person; nothing erased (archive, disable, withdraw).
4. **Blinding:** external-validation studies are withheld until the MAP is signed; every view must honour it.
5. **SME-governed content stays UNVERIFIED** and is shown as such.
6. **Locked files** (`docs/architecture/locked-files.json`): auth, signatures, audit, migrations, rulesets, CPF, builder,
   CI. A redesign touching auth (e.g. a new role) needs its own PR with owner approval.
7. **Owner's UX rules** (plan 2026-11-14 §2): one list of work; one home per decision; one card per study/product;
   one row per file; four status words; nothing a person can do today becomes impossible.
8. **Escalations are asked where the person is** (inbox removed 2026-11-11). A redesign that restores a central queue
   reverses an owner decision and needs the owner's call.

---

## 9. Git, branches and parallel work (VERIFIED)

- The clone is **shallow** (`git rev-parse --is-shallow-repository` = true): 149 commits, earliest 2026-11-11. Work
  from 2026-09-16 onward is known only through `CHANGELOG.md` (10,079 lines, 363 headings) and its session table.
- Branches: `main` (= `origin/main` `61ffb53`), `claude/inspiring-einstein-191gn3` (this session) at `cf3f6ec`, which
  carries **2 commits not on `main`** made earlier today by another session ("Agents: when a model cannot answer…",
  "Records: free models measured…"). They are left untouched.
- One worktree (this checkout). No uncommitted work at start (`git status` clean).
- Session table (end of `CHANGELOG.md`): several Claude models across ~15 cloud/desktop sessions
  since 2026-09-16, often with parallel worktrees and multi-agent review rounds; one merge PR has
  [ayush-1610/Modeler_One_AI#173](https://github.com/ayush-1610/Modeler_One_AI/pull/173) (locked-file draft).
- Other Claude Code conversations were **not** accessible; parallel activity above is reconstructed from records only.

---

## 10. Shared project memory: proposed mapping (no new root files yet)

The charter asks for seven project records. The repository already keeps most of them; duplicating them would
create a second, drifting source of truth (the drift CLAUDE.md warns about). Proposal:

| Charter record | Existing home | Action proposed |
|---|---|---|
| PROJECT_STATUS.md | `docs/CONTINUATION_PACKAGE.md` §4 | reuse |
| PROJECT_ARCHITECTURE.md | `docs/ARCHITECTURE_PACK.md`, `docs/ARCHITECTURE_BOUNDARIES.md`, `docs/ENGINEERING_PLAN.md` | reuse |
| PROJECT_HISTORY.md | `CHANGELOG.md` (+ its session table) | reuse |
| FEATURE_REGISTRY.md | none | `design-review/FEATURE_INVENTORY.md` now; promote after Gate 4 |
| API_UI_MAPPING.md | none | `design-review/API_PAGE_MAPPING.md` (Phase 7) |
| CODE_CLEANUP_LOG.md | none | `design-review/BLOATWARE_REPORT.md` now; a log once removals are authorised |
| PRODUCT_ROADMAP.md | `docs/plans/` + CONTINUATION §2 | `design-review/PROPOSED_FEATURES.md` feeds it |

---

## 11. Audit coverage checklist

| Area | Coverage | Method |
|---|---|---|
| Repository layout, git state, branches, worktrees | Full | git commands |
| Docs: README, CLAUDE.md, CONTINUATION §1–§4, CHANGELOG session table, plans 2026-11-06, 11-10, 11-14 §2 | Read | direct |
| Other 28 plans in `docs/plans/` | Titles and status only via CONTINUATION | not read line by line |
| Web routes (22 pages), shell, nav, layout, tokens | Full | read |
| Web components (120 files) | Imports, sizes, orphan check, duplicates; not every file read | scripts + spot reads |
| API routers (19) and auth/ownership/roles | Full for routes and authz; handlers spot-read | AST + read |
| Domain packages L0–L5 | Module purpose, size and consumers (digest); handlers not read | scripted digest + spot checks |
| Engine worker R scripts, golden files | Not read (locked, engine-only) | — |
| Deploy scripts, Keycloak realm, docker-compose | Listed only | — |
| CI workflows | Job list read | read |
| Runtime: tests | e2e subset run (35/35); pytest and lint not run | run |
| Production server state, deployed version, real users | Not accessible | see UNKNOWN |
