# Wireframes (Phase 4, Gate 3)

**Prototype:** [`prototype/index.html`](prototype/index.html). One self-contained file: open it in any browser, no build,
no dependencies, no network. It calls no API and is independent of `apps/web`. Every number in it is invented and
labelled **MOCK**; compounds have invented names (Exampleamide, Planamide, Renalide, Pedamide).

## 1. How to review it
1. Open `design-review/prototype/index.html` (double-click, or drag into a browser).
2. The yellow strip at the top is prototype furniture, not product. It holds **All pages** (an index of every page with
   a link) and **Prototype controls**:
   - **Signed in as**: owner (curator), curator a project is shared with, reviewer, viewer, QA (proposed), platform
     admin. The page changes with the role: edit buttons, sign buttons, read-only notice, admin console, Your work.
   - **Page state**: Normal, Empty, Loading, Error (API down). Shows each page's empty, loading and error state.
3. Each page carries its id (P-xx) at the top right, matching [`PAGE_INVENTORY.md`](PAGE_INVENTORY.md).
4. Working interactions: navigation, breadcrumbs, tabs and in-page sections (each with its own address), sortable
   columns, text filters, the project switcher, the user menu, the help panel ("Info"), the side panel (select a row or
   a source chip), and every dialog (reason required where the product requires one; signing shows the step-up). Any
   "save" ends with "Prototype only: nothing was saved or sent".

## 2. Fidelity and conventions
| Convention | Meaning |
|---|---|
| Hatched box with dashed border | Something the wireframe does not draw: the MS-01 canvas, charts, page and sheet previews. **No curve is drawn anywhere** (owner rule, 6–7 Nov) |
| `MOCK` outline badge | Invented numbers |
| Accent `#001B94` | Only primary buttons, the active navigation item and tab, focus rings, the Your work count, progress fills (decision D-P1, 60-30-10). Tab counts are neutral |
| Status words | Missing · To confirm · To decide · Done (plus "To sign" in Your work); run states Running · Escalated · Stopped · Passed · Failed |
| System font | Hi-fi (Gate 4) uses IBM Plex Sans and Mono |
| Light only | Every colour is a token, so dark mode can be added later (decision G1-2) |

## 3. The shell (every page)
| Zone | Wireframe |
|---|---|
| Top bar (48 px, white) | Logo placeholder + "Modeler One" → Home · **Go to project…** (type-ahead list) · Your work (count) · Help · API dot (select to re-check) · user menu (name, company, role, Help, Sign out) |
| Side navigation (240 px, fixed, never hover-opened) | Three contexts: **portfolio** (Home, Your work, Projects, Campaigns, Help; Platform → Admin console for admins), **project** (back link, project name, drug, application, risk; Overview; Workflow 1–4 with step icons ✓ ● ◐ ○ and Data's three pages; Records; Project), **admin** (back link; nine pages; Future: platform audit log). Below 1024 px it becomes a menu (☰) |
| Breadcrumbs | Every page below Home |
| Page header (~88 px) | Title, status badge, **Info** (opens the help panel), one-line description; actions on the right, one primary |
| Flash bar | Under the header: archived notice, read-only notice for non-owners, "A decision is waiting" on the project's pages for people who may sign, action results, API errors |
| Help panel | Right side; the page's explanation in plain words (replaces long paragraphs in cards) |
| Side panel | Right side; a selected row's detail or a value's source; Escape closes it |

**Responsive:** at 1024 px the side navigation becomes a menu and two-column layouts stack; at 640 px the top bar
drops the project switcher (Projects in the menu reaches every project) and Help (it stays in the user menu), and wide
tables scroll inside their panel. The
crawl found no page that scrolls sideways at 390 px.

## 4. Role differences (as wired)
| Role | Sees | Does not see |
|---|---|---|
| Owner (curator) | Every edit and sign control; Your work 7 items | Admin console |
| Curator, shared | Read-only notice naming the owner; Create project | Edit and sign controls; Your work is empty |
| Reviewer, shared | Read-only notice "as a reviewer you may sign"; **Approve and sign**, **Decide the escalation**, the decision flash on the project | Other edit controls |
| Viewer | Read-only notice; Review & sign readable | Every edit and sign control, Create project |
| QA (proposed default) | Projects described as "every project of your company"; read-only | Edits, signatures |
| Platform admin | Everything an owner sees, plus Platform → Admin console and a key-rotation item in Your work | — |
| Anyone not admin at `/admin…` | "There is no page here", as the app answers today | — |

## 5. Page by page
Ids and routes as in `PAGE_INVENTORY.md`; routes are the prototype's hash routes (`#/…`), the same paths as the
sitemap's.

### Portfolio
| Id | Page | Layout (top to bottom) | States and notes |
|---|---|---|---|
| P-01 | Home `#/` | Two columns. Left: Your work (5 rows, "View all"); Projects (steps bar, next action, risk, updated). Right: Portfolio counters (links), Risk across programs table, Recent campaigns list | No KPI cards or charts; counters are links. Empty: "No projects" with Create project |
| P-02 | Your work `#/work` | One table: item, project, step, status word, waiting since, **Open**. Toolbar: text filter, kind, project | Links only (G1-3). Empty: "All clear" |
| P-03 | Projects `#/projects` | Toolbar: filter, Show archived, Table/Cards toggle. Table: project, drug, steps, next action, risk, open questions, owner, updated, Archive/Restore | Archive needs a reason. Cards view: noted, not drawn |
| P-04 | Create project `#/projects/start` | Two columns: Project (drug, name) and Files (drop zone, file table with tag per file, a tag proposal decided in one click); "What happens next" | No reference-model option (Q2). Viewer: told the role cannot create |
| P-05 | Campaigns `#/campaigns` | Table: campaign, project, compound, status, current stage, started, budget used; status filter | Membership-filtered (R-S01) |
| P-30 | Help `#/help` | In-page topics (Getting started, Status words, Signatures, Blinding, MS-01 stages, AI agents) + topic text | Content from `docs/USING_THE_TOOL.md` in Gate 4 |

### Project
| Id | Page | Layout | States and notes |
|---|---|---|---|
| P-10 | Overview `#/projects/exa` | Header with risk, owner; actions Add data ▾, **Next: …**. Left: Steps table (state, next), Questions of interest, Recent activity. Right: Open items by status word, Latest campaign, Members | New project home. Add data asks "a client delivery → Data room, or documents → Documents" (G1-1 open item) |
| P-11 | Start `#/projects/exa/start` | Four numbered panels as field tables (field, value, status, Set): the drug and the files, question of interest, model risk (UNVERIFIED rule), scope | **Set** → value + source → **What this changes** (impact preview) → save |
| P-12 | Data room `#/projects/exa/dataroom` | Run line (Show the steps). In-page nav of 13 sections, each with a status word; content right | Wired in detail: Overview, Files, Dissolution, Decisions, Data requests (print/copy), PK-Sim inputs (**Send to the model** → step-up). Others show the generic findings table. Source chips → side panel |
| P-12b | Evidence report `#/projects/exa/dataroom/report` | Print page: question, conflicts, data requests, how it was made | Print hides the shell |
| P-13 | Inputs `#/projects/exa/inputs` | Status line ("In the model: …"); **Next** primary; tabs with neutral counts: To do · Compound · Products and dissolution · Clinical studies · Populations and individuals · Simulation settings · Client files | To do groups by status word; a study row opens its card in the side panel (To do on this study, Facts, Observed data, Files and tables, Checks, **Confirm and sign**). Model system now under Compound. Blinded study EX-03 shows the blinding reason |
| P-13b | Data plan `#/projects/exa/data-plan` | Table: requirement, application, who provides it, status, settled on (link to the card); filters | Read-mostly (Q1): no edits here |
| P-14 | Review & sign `#/projects/pla/plan` | Validator badge in the header; **Approve and sign** (owner, reviewer); tabs: Studies and roles · The inputs · The estimation plan · The validation plan · Applications · Credibility · Validator and changes | Canvas is a placeholder over a studies table with Move… and **Back to the MS-01 default** (`:unlock`). Viewer: read-only notice, no sign |
| P-15 | Run `#/projects/ren/campaigns` | Readiness checklist when a campaign cannot start; campaigns table; **Run campaign** | Readiness links to the step that is missing |
| P-16 | Campaign `#/campaigns/camp-7f3a` | Header: id, status, risk; fixture warning (mandatory); decision flash; tabs: Stages · Fit · Rounds · Feedback · Package · Runs | **Decide the escalation** → decision dialog → step-up. Fit is a placeholder (no curve). Package uses `GET /package`. Runs: "after the multi-server deployment" |
| P-17 | Compounds `#/projects/exa/compounds` | Table: compound, role, complete, version | New |
| P-17b | Compound `#/projects/exa/compounds/Exampleamide` | CPF table with provenance badges; filters | Values change on Inputs (one place per decision) |
| P-18 | Documents `#/projects/exa/library` | Toolbar: find, tag; table; row → side panel preview with Withdraw (reason) | |
| P-19 | Agent activity `#/projects/exa/agent-activity` | Table: agent in words, model (incl. fallback), started by, started, took, status, tokens, refusals | Needs the new list route (R-N05) |
| P-19b | Agent run `#/projects/exa/agent-activity/run-a8-0412` | Turns table: read, model switch, tool call, refusal by code, answer, and the model of each | |
| P-21 | History `#/projects/exa/history` | Tabs: Audit trail · Signatures · Versions · Out of date | Append-only |
| P-22 | Members `#/projects/exa/members` | Table: person, role, access (Owner / Reads / Reads · signs), since, Remove (reason) | Add a member: people who signed in once |
| P-23 | Settings `#/projects/exa/settings` | Owner; Blinding (read-only, set on Review & sign); Archive (danger, reason) | |

### Admin console (role "Platform admin")
| Id | Page | Layout | Notes |
|---|---|---|---|
| P-20 | Overview `#/admin` | Limit warning flash; Companies table; The platform; This month | |
| P-24 | Companies `#/admin/companies` | Table with Disable / Enable (reason); Add company | Never deleted |
| P-24b | Company `#/admin/companies/northwind` | People table; Projects table; **Give a person projects** | |
| P-25 | People `#/admin/people` | Table; Add a person; Change (roles, company, reset authenticator, disable) | Dialog says the identity provider sets passwords, never Modeler One |
| P-26 | Usage and cost `#/admin/usage` | Filters (since, company, priced as); tabs By agent · person · project · company · day; CSV | |
| P-27 | Agents and models `#/admin/models` | Agents table (provider, model, effort, Change); Failover list | Put every agent on one model |
| P-28 | Keys `#/admin/keys` | Table: provider, last 4, added, age (Rotate flag > 90 days), state; Test, Retire; Add a key (write-only) | |
| P-29 | Limits `#/admin/limits` | Table with usage bars; Set a limit (reason) | Warn only, never stop |
| P-31 | Intake pipeline `#/admin/pipeline` | Stage table: waiting, running, failed today, median time | |
| P-32 | System status `#/admin/system` | Parts table: API, campaign execution, engine (needs a new check route), agents, keys, intake pipeline | New |
| P-33 | Platform audit log `#/admin/audit` | "Not available yet" empty state | Future (R-N07) |

### System
| Id | Page | Notes |
|---|---|---|
| SYS-404 | Not found (any unknown address) | Keeps the shell, so the way back is there |
| SYS-ERR | Error `#/error` | Support reference |
| SYS-OUT | Signed out `#/signed-out` | Sign in again |
| Dialogs | Step-up, escalation decision, reason, impact, archive, upload, decide, add member, add person, add key, set limit, give projects, agents | Step-up text: password and authenticator are entered at the identity provider, never in Modeler One |

## 6. Verification (2026-11-23)
A headless-browser run over the prototype:
- **Crawl:** every in-prototype link followed from Home and the index, for each of the six roles, at 1440 px and
  390 px. 295 distinct addresses; no script error, no dead link, no "undefined" text, no sideways page scroll.
- **Interactions:** 90 dialogs opened from every page; each reason-required dialog refused an empty reason in words;
  Escape closed each; 9 side panels; empty, loading and error states on every page; the escalation → step-up sign
  flow; the viewer has no sign button on Review & sign; a non-admin finds no page at `/admin`.

## 7. Not drawn or simplified (by design at low fidelity)
- The MS-01 canvas, charts, page and sheet previews, project cards view: placeholders.
- Select filters are shown but only the text filters filter.
- Dialog choices are not carried into the page (nothing is saved).
- Phone tables scroll inside their panel; Gate 4 proposes a stacked-row pattern for the busiest ones.

## 8. Questions for Gate 3 (defaults used in the wireframe)
1. **Data room sections:** left in-page navigation (as wired, like the current page) or tabs? Default: left navigation,
   13 sections do not fit a tab row.
2. **Inputs study card:** in the side panel (as wired) or as its own page? Default: side panel, so the list stays in
   view; a full page if the card grows.
3. **Your work count** appears in the top bar and in the portfolio navigation. Default: both (the top bar is the one
   seen inside a project).
