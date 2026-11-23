# Page Inventory (Phase 3, Gate 2)

One entry per page. Routes are relative to `/api/v1` unless shown. Status: **E** existing, kept · **R** existing,
redesigned or moved · **N** new on existing API routes · **N·be** new, needs a backend change · **Q** waits on an owner
question · **F** future. Roles: V viewer · C curator (owner) · Cs curator the project is shared with · Rv reviewer ·
QA · A admin. "Read-only" for Cs / V / QA means no edit controls (from `GET /members` `you_change_it`).

Common to every page: breadcrumbs, compact page header, flash bar, empty / loading / error states. Error state names
what failed in words ("The API did not answer; nothing on this page is current") and never shows sample data.

---

## Portfolio

### P-01 Home · `/` · R
| | |
|---|---|
| Users | Everyone signed in |
| Purpose | Answer three questions on one screen: what waits on me, what is running, where each program stands |
| Shows | Your work summary (top 5 links + count); counters: projects, running campaigns, waiting on a person, open questions (each a filter link to P-03); recent projects (table, 8 rows); risk across programs (low / medium / high counts) |
| Actions | Create project (primary); go to Your work; open a project |
| Nav | Top bar logo; side nav "Home" |
| Backend | `GET /projects`, `GET /projects/{id}/steps` per project (N+1 until R-N03), `GET /campaigns` (after R-S01), `GET /escalations` (after R-S01) |
| Today → change | Dashboard hero, KPI tiles and project cards → compact header, dense counters, tables. Cards view moves to P-03 as an option |

### P-02 Your work · `/work` · N (N·be later)
| | |
|---|---|
| Users | Everyone; most useful to reviewers across projects |
| Purpose | One list of links to everything that waits on this person. **Nothing is decided here** (G1-3) |
| Shows | Table: project, step, item ("Sign the MAP", "Decide the S1 escalation", "4 values to confirm"), status word, waiting since, link "Open". Filters: project, kind (sign / decide / confirm / fill in), status word |
| Actions | Open (goes to the page where it is decided) |
| Nav | Top bar "Your work (n)"; side nav |
| Backend | Today: `GET /projects` + `/steps` per project + `GET /escalations`. Later: step state in `GET /projects` (R-N03) |
| Empty state | "Nothing waits on you." |

### P-03 Projects · `/projects` · R
| | |
|---|---|
| Users | Everyone (their projects); A sees all through the console |
| Purpose | Find and open a project; archive and restore |
| Shows | Table: name, drug, step (1–4 with status icon), next action, risk, open questions, owner, updated; toggle Show archived; optional Cards view |
| Actions | Create project (primary); Archive / Restore with a reason (owner) |
| Backend | `GET /projects`, `/steps`, `POST /projects/{id}:archive`, `:restore`, `GET /members` (owner name) |

### P-04 Create project · `/projects/start` · R
| | |
|---|---|
| Users | C, Rv |
| Purpose | Start a project from the client's proposal and files in one upload |
| Shows | Form: drug, project name; drop zone with per-file tag; tag proposals. No reference-model start (owner, Q2: this is where real client work starts) |
| Actions | Create project (primary), Cancel |
| Backend | `POST /projects:initiate`, `POST /documents/{sha}:tag` |

### P-05 Campaigns (all projects) · `/campaigns` · N
| | |
|---|---|
| Users | Everyone, own projects only |
| Purpose | See every running and finished campaign without opening each project |
| Shows | Table: campaign, project, compound, status, current stage, verdict, started, budget used |
| Backend | `GET /campaigns` (filters by membership since R-S01 was fixed, 2026-11-23) |

### P-30 Help · `/help` · N
| | |
|---|---|
| Purpose | How to use the product, MS-01 stages, status words, signatures, blinding, in plain words |
| Backend | none (content from `docs/USING_THE_TOOL.md`, reviewed for plain words) |

---

## Project

### P-10 Project overview · `/projects/{id}` · N (replaces the Run page as home)
| | |
|---|---|
| Users | Members |
| Purpose | Where this project stands and what to do next |
| Shows | Header: project name, drug, risk badge, owner, archived badge. Steps panel: the four steps with status and next action. Question of interest table (question, application, model risk, stage, failing criteria). Latest campaign (status, stage). Open items by status word. Recent activity (last 10 audit events). Read-only notice for non-owners |
| Actions | The next step's action (primary, e.g. "Continue on Inputs"); Add data |
| Backend | `GET /projects/{id}`, `/steps`, `GET /campaigns?project=`, `GET /audit` (last events), `GET /members` |

### P-11 Start · `/projects/{id}/start` · R
| | |
|---|---|
| Users | Members; C edits |
| Purpose | Confirm what the agent read from the proposal; say what is modelled |
| Shows | Sections as a form with field rows: the drug and the files (PubChem CID, SMILES), the question of interest, model risk drafts (ICH M15, UNVERIFIED rule), scope gates; each draft marked "waits on you" |
| Actions | Read the proposal again; Set a field; Continue to Data (primary when done) |
| New | "What this changes" impact preview before saving a field that makes a confirmed or signed artifact stale (`POST /impact`) |
| Backend | `GET/PUT /brief`, `brief:extract`, `brief/items:remove`, `brief/questions/{q}`, `/steps`, `POST /impact` |

### P-12 Data room · `/projects/{id}/dataroom` · R
| | |
|---|---|
| Users | Members; C acts |
| Purpose | What the client sent and whether it is right (G1-1) |
| Shows | Header actions: Upload a delivery, Run again. Run status line (files read, OCR pages, steps waiting for a model, finished at; "Show the steps"). In-page nav (left, inside content) of the 13 sections with status dots: Overview · Files · Drug substance · ADME and disposition · Formulation · Solubility · Dissolution · Clinical studies · Observed PK · Decisions · Data requests · Simulation plan · PK-Sim inputs. Conflicts first. Source chips open the **split panel** with the page or sheet line |
| Actions | Upload; Run; decide; enter a value; edit / print / copy a data request; Send to the model (signed with step-up) |
| Status words | The Inputs four words replace the section dots' colours-only meaning (G1-1: Inputs' rules apply to both) |
| Removed | Footer link "The earlier Inputs page" (G1-1) |
| Backend | `dataroom/*` (15 routes) |

### P-12b Evidence report · `/projects/{id}/dataroom/report` · E
Print layout of the Data room; light only. Backend `GET /dataroom`.

### P-13 Inputs · `/projects/{id}/inputs` · R
| | |
|---|---|
| Users | Members; C acts and signs the confirmation |
| Purpose | What goes into the model (G1-1) |
| Shows | Status line ("In the model: n studies · n formulations · n compound values"), the single "Next" action, tabs: To do · Compound (incl. **Model system**, moved from Run) · Products and dissolution · Clinical studies · Populations and individuals · Simulation settings · Client files. Cards per study or product; one row per file |
| Actions | Fill in, confirm, link, decide, spot check, sign the confirmation (step-up), ask the client (.xlsx) |
| Removed | "Open in the Data room" framed as an alternative path; the Data room is reached from the side nav |
| New | Impact preview before re-confirming a signed card (`POST /impact`) |
| Backend | `inputs*`, `client-data*`, `client-review*`, `delivery*`, `evidence*`, `datasets*`, `value-reuse`, `reading-queue`, `GET/PUT /system` |

### P-13b Data plan · `/projects/{id}/data-plan` · N (owner, Q1: yes, read-mostly)
| | |
|---|---|
| Purpose | Which data each application (VBE, DDI, food effect, FIH, special populations) requires, who provides each item, and what is covered |
| Shows | Requirements table: item, application, provider, purpose, status, linked study or product |
| Actions | Open the card where an item is settled. **No edits here**: they stay on the cards (one place per decision) |
| Backend | `GET /requirements` (the matrix is re-derived on every brief save) |
| Note | The 23 Oct removal from Start was about 27 rows of "—" linked to nothing; this page shows real status with links (owner, 2026-11-23) |

### P-14 Review & sign · `/projects/{id}/plan` · R
| | |
|---|---|
| Users | Members; C edits; C or Rv signs; V/QA read through `plan:view` |
| Purpose | The model analysis plan (MAP) and its signature |
| Shows | Tabs (kept): Studies and roles (canvas) · The inputs · The estimation plan · The validation plan · Applications · Credibility · Validator and changes. Validator status pinned in the header ("No open MS-01 rule violation") |
| Actions | Move a study (with reason); **Back to the MS-01 default** (`:unlock`, new); fit or fix; group; acknowledge; Approve and sign (primary, step-up) |
| Fix | Viewers get 403 today because `GET /plan` needs a writer; read-only uses `plan:view` (R-S03) |
| Backend | `plan*` (18 routes), `GET /plan/review`, `GET/PUT /blinding`, `POST /impact` |

### P-15 Campaigns (project) · `/projects/{id}/campaigns` · R (today's Run page)
| | |
|---|---|
| Purpose | Run a modelling campaign and see this project's campaigns |
| Shows | Readiness checklist when a campaign cannot start (what is missing, with links); campaigns table: id, status, current stage, compound, started |
| Actions | Run campaign (primary, when ready) |
| Backend | `campaign:prepare`, `POST /campaigns`, `GET /campaigns?project=`, `/steps` |

### P-16 Campaign · `/campaigns/{cid}` · R
| | |
|---|---|
| Purpose | Follow and decide on one campaign |
| Shows | Header: compound, status, risk, acceptance tier; fixture banner when not on PK-Sim (kept, mandatory). Tabs: **Stages** (S0–S7 table with verdict, limits, budget) · **Fit** (goodness-of-fit, log toggle) · **Rounds** (round history table) · **Feedback** (external-validation cycles) · **Package** (reproduction verdict, hashes, files, PK-Sim projects, report issues, downloads; new from `GET /package`) · **Runs** (F: raw results when the distributed path exists) |
| Actions | Decide the escalation (dialog, step-up) when open and permitted; download package files |
| Backend | `GET /campaigns/{cid}`, `GET /campaigns/{cid}/package`, `/package/{artifact}`, `escalation:resolve` |

### P-17 Compounds · `/projects/{id}/compounds` · N
List of the project's compounds with completeness and role in the model system. Backend `GET /projects/{id}`,
`GET /system`.

### P-17b Compound · `/projects/{id}/compounds/{c}` · R
CPF table (parameter, value, unit, provenance, reference, fittable stages) with filters by status and provenance.
Backend `GET /cpf`. Writes stay on Inputs (one home per decision).

### P-18 Documents · `/projects/{id}/library` · R
| | |
|---|---|
| Shows | Table: document, tags, what cites it, added by / when, withdrawn; split panel preview (pages, figures) |
| Actions | Add documents (primary); tag; withdraw / restore with a reason; open the figure in the digitizer |
| Backend | `GET /library`, `documents*`, `documents:read-for-data` |

### P-19 Agent activity · `/projects/{id}/agent-activity` · N·be
| | |
|---|---|
| Purpose | What each AI agent did on this project: for the modeler's trust and the report's "how it was made" |
| Shows | Table: agent (A1–A10 in words), model, started by, started, duration, status, tokens, refusals |
| Backend | **New:** `GET /projects/{id}/agent-runs` (list). Detail exists |

### P-19b Agent run · `/projects/{id}/agent-activity/{run}` · N
Steps of one run (each turn, tool call, refusal, model switch), the model that wrote each answer. Backend
`GET /agent-runs/{run_id}`.

### P-21 History · `/projects/{id}/history` · R
Tabs: **Audit trail** (filterable table, `GET /audit`) · **Signatures** (filtered from the audit until a dedicated
read exists; F: signature register) · **Versions** (`GET /artifacts`, `/history`) · **Out of date** (`GET /stale`).

### P-22 Members · `/projects/{id}/members` · R
Table of members with role and owner flag; Add, Remove with a reason (owner). Backend `GET/POST /members`,
`members:remove`.

### P-23 Settings · `/projects/{id}/settings` · N
Owner; archive / restore with a reason; blinding state (read-only, links to Review & sign). Backend `GET /members`,
`:archive`, `:restore`, `GET /blinding`.

---

## Admin console (`modeler-admin`)

| Id | Page | Route | Status | Shows / actions | Backend |
|---|---|---|---|---|---|
| P-20 | Overview | `/admin` | R | Limit warnings; platform block (deployment, agents' models); counters; links | `GET /admin/overview` |
| P-24 | Companies | `/admin/companies` | R | Table: company, people, projects (active / archived), runs, failed, tokens, cost; Add company; Disable / Enable | `GET /admin/overview`, `POST /admin/companies*` |
| P-24b | Company | `/admin/companies/{t}` | E | People with their projects and use; projects with members; Give a person projects | `GET /admin/companies/{t}`, `:give-projects` |
| P-25 | People | `/admin/people` | E | Table of people; Add person; change roles; move; disable / enable; reset authenticator | `/admin/people*` |
| P-26 | Usage and cost | `/admin/usage` | E | Tabs: by agent · person · project · company · day; runs; CSV | `GET /admin/usage` |
| P-27 | Agents and models | `/admin/models` | E | Per agent: provider, model, effort; set every agent; failover chain | `/admin/agents*`, `agent-chain` |
| P-28 | Keys | `/admin/keys` | E | Table: provider, last 4, added by / when, age (flag > 90 days), state; Add, Test, Activate, Retire | `/admin/keys*` |
| P-29 | Limits | `/admin/limits` | E | Limits per company / project / person with use this month; Set, Remove | `/admin/limits` |
| P-31 | Intake pipeline | `/admin/pipeline` | E | Pipeline health | `GET /admin/pipeline` |
| P-32 | System status | `/admin/system` | N | API health, deployment, execution backend, agents and their keys' state, intake pipeline; engine reachability later | `GET /health`, `/admin/overview`, `/admin/pipeline`; engine check **N·be** |
| P-33 | Platform audit log | `/admin/audit` | F | The owner's chain (`admin.view`, `admin.*` changes) | **N·be** |

---

## System pages and dialogs
| Item | Status | Notes |
|---|---|---|
| Sign-in / sign-out | E | Keycloak hosted; route handlers `/auth/*` |
| Step-up dialog (signatures) | E | Restyled only; says the password is never typed into Modeler One |
| Not found (404), error, loading | R | Compact header; the side nav stays so the way back is there |
| Read-only notice | N | Flash bar from `GET /members` |
| Escalation decision dialog | R | Opened from the project's flash bar or Your work; never shown to someone who may not sign (R-S02) |

## Count
**34 pages**: portfolio 6, project 17, admin 11; plus 5 system pages and dialogs.

| Status | Pages | Ids |
|---|---|---|
| E kept | 8 | P-12b, P-24b, P-25, P-26, P-27, P-28, P-29, P-31 |
| R redesigned or moved | 15 | P-01, P-03, P-04, P-11, P-12, P-13, P-14, P-15, P-16, P-17b, P-18, P-20, P-21, P-22, P-24 |
| N new on existing routes | 9 | P-02 (step state later N·be), P-05, P-10, P-13b, P-17, P-19b, P-23, P-30, P-32 |
| N·be new, backend change | 1 | P-19 (list route) |
| F future | 1 | P-33 |
