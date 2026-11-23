# Feature Inventory (Phase 2)

Every capability found, classified with the charter's seven classes. "Functional" means the software path works and
is covered by a passing browser or API test; it never means a scientific result is validated (see the S0–S7
coverage table in `docs/CONTINUATION_PACKAGE.md` §4.1, and the rule that only real PK-Sim runs count).

Classes: **1** Existing & functional · **2** Existing but incomplete · **3** Backend-supported, not exposed in the UI ·
**4** Frontend without complete backend · **5** New feature recommended · **6** Future possibility · **7** Obsolete or
unnecessary. Classes 5–6 are in [`PROPOSED_FEATURES.md`](PROPOSED_FEATURES.md); class 7 in
[`BLOATWARE_REPORT.md`](BLOATWARE_REPORT.md).

Roles: V viewer · C curator (owner of the project) · R reviewer · A platform admin.

---

## 1. Existing and functional (class 1)

### 1.1 Portfolio
| Capability | Roles | UI | API | Evidence |
|---|---|---|---|---|
| Portfolio dashboard: KPIs, needs-attention list, risk across programs, search, filters, Cards/List | V C R | `/` | `GET /projects`, `GET /projects/{id}/steps` (one call per project) | `dashboard.spec.ts` passed |
| Archive / restore a project with a reason (never deleted) | C | `/` List | `POST /projects/{id}:archive`, `:restore` | `projects-archive.spec.ts` |
| Start a project from a proposal and client files in one upload, with document tags and tag proposals | C | `/projects/start` | `POST /projects:initiate`, `documents/{sha}:tag` | `start-project.spec.ts` passed |

### 1.2 Project step 1: Start (the brief)
| Capability | Roles | UI | API | Evidence |
|---|---|---|---|---|
| A1 reads the proposal; brief fields with drafts that wait on the person; drug identity (PubChem CID, SMILES), question of interest, model risk (ICH M15, UNVERIFIED rule) | C | `/projects/{id}/start` | `GET/PUT /brief`, `brief:extract`, `brief/items:remove`, `brief/questions/{q}` | `start-step.spec.ts` passed |
| Start cannot be left while a box waits on the person | C | step bar | `GET /steps` | same |
| Compound values from free structured sources, quoted (no AI) | C | Start / Inputs | `modeler_agents.compound_sources` | `compound-sources.spec.ts` |

### 1.3 Project step 2: Inputs (task-first workspace)
| Capability | Roles | UI | API | Evidence |
|---|---|---|---|---|
| One list of work with four status words; status line with a single "Next" | C | Inputs To do | `GET /inputs`, `/delivery`, `/client-review` | `inputs-task-first.spec.ts` |
| Seven areas: To do, Compound, Products and dissolution, Clinical studies, Populations and individuals, Simulation settings, Client files | C | Inputs | `GET /inputs`, `PUT /inputs/choices`, `inputs:assemble` | `inputs-workspace.spec.ts` passed |
| Client data delivery: upload, sheet reading, table-layout (mapping) review, link values to study/product, numbers not read, exclude/restore regions | C | Inputs To do, Client files | `client-data/*`, `delivery/*` (41 ops) | `delivery.spec.ts`, `inputs-todo.spec.ts` |
| Spot check (17 always + 100 random values) and signed confirmation of a study/product | C (sign) | study/product card | `delivery/subjects/.../spot-check`, `:confirm` | `inputs-owner-job.spec.ts` passed |
| Fill what is missing: compound values with source sentence, arms, batches, analytes, individuals | C | Inputs | `:enter`, `POST /evidence` | `inputs-fill.spec.ts` |
| "Ask the client" request workbook | C | To do | `GET /client-data/request.xlsx` | `inputs-owner-job.spec.ts` |
| AI reading queue and tray; read again; read library documents for data | C | Inputs | `reading-queue`, `documents:read-for-data` | `library.spec.ts` passed |
| Figure digitizer (PDF/image; calibrated axes) | C | Inputs | `POST /datasets:digitize` | `digitize*.spec.ts` |
| Value reuse from earlier projects | C | Inputs | `GET/POST /value-reuse` | `value-reuse.spec.ts` |
| Literature research and published-model import (evidence with grade) | C | Inputs | `evidence:research`, `evidence:published-model`, `literature-run` | `published-model.spec.ts` |
| Blinding of external-validation studies until the MAP is signed | C R | everywhere | `GET/PUT /blinding`, `:reveal` | `blinding.spec.ts`, `inputs-blinded*.spec.ts` |

### 1.4 Data room (the newer intake path, 2026-11-21)
| Capability | Roles | UI | API | Evidence |
|---|---|---|---|---|
| Drop a whole delivery (zips, scans, OCR), background run per project, stage progress | C | `/dataroom` | `dataroom/uploads`, `/run`, `import-existing` | `dataroom.spec.ts` passed |
| 13 sections with status dots; conflicts first; source chip opens the page or sheet line | C R | `/dataroom` | `GET /dataroom`, `files/.../pages/{p}.png`, `parts/{part}` | same |
| Decisions, entered values, data requests (print/copy), simulation plan, PK-Sim input sheet | C | `/dataroom` | `decisions/{id}`, `entered`, `PATCH requests/{id}` | same |
| "Send to the model" (signed with step-up) publishes confirmed inputs to evidence and datasets | C | `/dataroom` | `GET publication`, `POST publish` | same |
| Printable evidence report | C R | `/dataroom/report` | `GET /dataroom` | — |

### 1.5 Project step 3: Review & sign (MAP)
| Capability | Roles | UI | API | Evidence |
|---|---|---|---|---|
| Plan canvas: drag-and-drop study placement with reasons; live MS-01 validator; acknowledgements | C | `/plan` | `PUT placements`, `structure`, `layout`, `violations/{id}:acknowledge` | `model-plan.spec.ts` passed |
| Estimation plan (fit or fix, bounds, fit groups "fitted as one") | C | `/plan` | `PUT/POST plan/fits/*`, `plan/groups/*` | `review-sign.spec.ts` passed |
| Validation plan, applications, credibility (M15 risk, acceptance criteria by tier, time budget per stage) | C | `/plan` | `GET /plan/review` | same |
| Approve and sign the MAP (owner or a reviewer it is shared with) | C R | `/plan` | `plan:sign` | same |
| Agent proposals in the plan decided | C | `/plan` | `plan/proposals/{id}:decide` | — |
| Rebase a plan after its inputs changed | C | `/plan` | `plan:rebase` | — |

### 1.6 Project step 4: Run and campaigns
| Capability | Roles | UI | API | Evidence |
|---|---|---|---|---|
| Prepare and start a campaign (MS-01 S0→S7) | C | `/projects/{id}` | `campaign:prepare`, `POST /campaigns` | `campaign-monitor.spec.ts` passed |
| Campaign monitor: stage progress, time budget, goodness of fit (log toggle), round history, fixture banner | V C R | `/campaigns/{id}` | `GET /campaigns/{id}` | same |
| Escalation: global pop-up, signed decision (step-up) | C R | any page | `escalation:resolve`, `GET /escalations` | `escalation-popup.spec.ts` |
| External-validation feedback cycle with signed limitation | C R | campaign | `feedback` path | `feedback.spec.ts` passed |
| Model system (parent, metabolites, enantiomers) | C | Run page | `GET/PUT /system` | `model-system.spec.ts` |
| Package downloads | C R | campaign | `GET /campaigns/{id}/package/{artifact}` | `PackageDownloads.tsx` |
| VBE (virtual bioequivalence) application with "not validated" warning | C | campaign | `vbe-crossover` template | `vbe.spec.ts` passed |

### 1.7 Project records
| Capability | Roles | UI | API | Evidence |
|---|---|---|---|---|
| Document library: list, cites, find, filter, open, withdraw/restore, tag proposals, figure suggestions | V C | `/library` | `GET /library`, `documents/*` | `library.spec.ts` passed |
| History: audit trail, stale artifacts, artifact versions | V C R | `/history` | `GET /audit`, `/stale`, `/artifacts` | — |
| CPF view per compound | V C R | `/compounds/{c}` | `GET /cpf` | — |
| Members: list, add, remove (with reason) | C | Run page | `members`, `members:remove` | `members.spec.ts` passed |

### 1.8 Platform administration (owner only)
| Capability | UI | API | Evidence |
|---|---|---|---|
| Overview of every company: people, projects, agent runs, tokens, cost; banner for limits | `/admin` | `GET /admin/overview` | `admin-console.spec.ts` (non-admin refused) passed |
| Company page; give a person projects | `/admin/companies/{t}` | `GET company`, `:give-projects` | — |
| Usage and cost by agent, person, project, company, day | `/admin/usage` | `GET /admin/usage` | — |
| Agents' models: per agent, all at once, failover chain | `/admin/models` | `PUT /admin/agents*`, `agent-chain` | — |
| Provider keys: add, test, activate, retire (write-only, AES-GCM) | `/admin/keys` | `/admin/keys*` | — |
| Monthly limits with 80 % / 100 % warnings (never stop an agent) | `/admin/limits` | `/admin/limits` | — |
| People and companies through Keycloak: add, change roles, move, disable, reset authenticator | `/admin/people` | `/admin/people*`, `/admin/companies*` | — |
| Intake pipeline health | `/admin/pipeline` | `GET /admin/pipeline` | — |

### 1.9 Platform
| Capability | Evidence |
|---|---|
| OIDC sign-in (Keycloak, PKCE), sign-out, step-up dialog for signatures | `app/auth/*`, `StepUpDialog.tsx`, `oidc-signing.spec.ts` (runs only with a Keycloak) |
| Hash-chained append-only audit per tenant; platform audit chain for admin views/changes | `modeler_project.audit`, `admin.view` events |
| API live indicator in the sidebar | `Nav.tsx` `useApiLive` |

---

## 2. Existing but incomplete (class 2)

| Capability | What is missing | Evidence |
|---|---|---|
| Two intake paths (Inputs task-first and Data room) | Both live; each links to the other ("The earlier Inputs page"). Which one is the product's path is undecided | `04-dataroom.png` footer; CONTINUATION §4.0d |
| Read-only for shared members | API refuses non-owner writes (`NOT_OWNER`), but pages still show edit buttons that answer with the refusal | admin plan §4 "Not yet: the pages marked read-only" |
| QA role | Assignable in Admin → People, no permission or screen | `keycloak_admin.py:32` |
| Routines (G) and support "view as" (H) in the admin plan | Not built | admin plan §2 table vs §4 builds |
| Groups / teams within a company | Deferred by the owner | admin plan §4 F |
| Limit warnings by email or push | Console banner only | admin plan §4 E |
| Agent run transparency | Each run records turns, tokens, model, started_by; UI shows only summaries | `GET /agent-runs/{id}` unused |
| Real-time status | Polling only; D15 planned SSE | §4 of the audit |
| Dashboard scaling | One `/steps` call per project | app-design-merge plan §4 gap 3 |
| Science coverage | All stages on PK-Sim with synthetic data only; real clinical data open; Data room rules 0.1 UNVERIFIED | CONTINUATION §4.0d, §4.1 |
| Data room agents scoring | A6–A10 scored on one model; others open (NVIDIA 502s, GroqCloud free tier) | CONTINUATION §4.0d "Open" 1 |
| Word figures in the digitizer | PDF and images only | CONTINUATION §4.0a known gap |
| Open owner questions on Inputs | 16 listed (gate per delivery or study, spot-check size, unblinding by purpose change…) | CONTINUATION §4.0c |

---

### 2.1 Defects found at Gate 2 (details in `REMEDIATION_PLAN.md` §1)
| Id | Defect |
|---|---|
| R-S01 | `GET /campaigns` and `GET /escalations` list every project's items in the company, members or not |
| R-S02 | The escalation pop-up (every 5 s, every page) shows decisions to people who cannot sign them |
| R-S03 | A viewer gets 403 on Review & sign (`GET /plan` needs a writer; `plan:view` unused) |
| R-S04 | `POST /model-versions/preview` and `POST /m15/validate` take no authentication |
| R-S05 | `modeler-qa` grants nothing |
| R-S06 | Temporal-path signing routes take a password in the body (inert today) |

## 3. Backend-supported, not exposed in the UI (class 3)

22 of 183 operations have no caller in `apps/web` (VERIFIED by contract cross-check plus a text search per path; Gate 1 said 21 and missed `POST /campaigns/{id}/deviations`). *(Corrected at Gate 2: see [`REMEDIATION_PLAN.md`](REMEDIATION_PLAN.md).)*


| Operation | What it offers | Likely reason / UX opportunity |
|---|---|---|
| `GET /api/v1/proposals` | Agent parameter proposals across projects | Always empty: nothing in production writes it (dead chain, R-B13) |
| `GET /escalations/decision-options` | MS-01 decision options | UI hard-codes or reads them elsewhere (INFERRED) |
| `POST /campaigns/{id}/stages/{s}/escalation:decide` | Signed decision (older route) | UI uses `:resolve`; candidate duplicate (Bloatware B-03) |
| `POST /campaigns/{id}/feedback:decide` | Feedback decision | INFERRED replaced by `:resolve` with payload |
| `GET /campaigns/{id}/package` | List a campaign's package | UI fetches named artifacts directly; a package browser is missing |
| `GET /runs/{run_id}/results` | Raw run outputs / series | A run-level results explorer is missing |
| `POST /runs`, `POST /model-versions/preview`, `POST /m15/validate` | Ad-hoc engine run, snapshot preview, M15 table validation (F-101/102/401) | Expert tools with no screen |
| `GET /health` | Liveness | Used by `deploy/server/qualify.py`; no system-status page |
| `GET /projects/{id}/agent-runs/{run_id}` | One agent run's turns, model, tokens | Agent activity viewer is missing |
| `POST /questions/{q}/map:generate` | MAP JSON generation (T-16) | Superseded by the plan canvas path (INFERRED) |
| `POST /client-review:edit` | Edit a study fact (sheet-form path) | INFERRED superseded by delivery `:enter` |
| `POST /plan/placements/{s}:unlock` | Unlock a placed study | No control on the canvas |
| `GET /plan:view` | Read-only plan | Could back a reviewer's read-only view |
| `POST /projects/{id}/impact` | Preview what a change makes stale | Impact preview before an edit is missing |
| `GET /requirements`, `PUT /requirements/{r}`, `POST /requirements:derive` | Data plan requirements per application (SME templates) | The requirements matrix has no screen of its own |
| `GET /templates`, `GET /templates/{id}` | Project starting points of the removed create-project wizard: the published Dapagliflozin model and an illustrative Aciclovir set (**not** the VBE/DDI analysis templates, as Gate 1 said) | Owner question Q2 |
| `POST /campaigns/{id}/deviations` | Signed MAP deviation on the Temporal path (password in the body) | Inert today; R-S06 |

Domain capabilities with no API route (VERIFIED: no production importer):
- `pbpk_domain.ddi_static` (static DDI screening, ruleset `ddi_static_screening.yaml`).
- `modeler_agents.literature` and `modeler_agents.parameter_curation` (agents F-501): only tests import them;
  INFERRED superseded by the evidence research path.

---

## 4. Frontend without complete backend support (class 4)

| Item | Evidence |
|---|---|
| None found among API calls: every web call matches a contract path. | contract cross-check |
| Edit buttons shown to non-owners that the API refuses | class 2 above |
| `lib/writes.ts:39` comment refers to a wizard reading `GET /templates`; no such caller remains | stale comment |

Gaps the previous design review named and that remain open (app-design-merge plan §4): a decision route for agent
proposals; a cross-project activity feed; step state inside `GET /projects`.
