# Proposed Features (Phase 2)

Proposals only: nothing here is built or approved. Each row names the user problem and the backend that exists today
(VERIFIED against `docs/api/openapi.json` and the routers). "Existing backend support": **Full** = the API already
answers it; **Partial** = some routes exist, a change is needed; **None** = new backend work.

Priority: **P1** do with the redesign (it fixes a problem the redesign is meant to fix) · **P2** next · **P3** later ·
**FUTURE** speculative. Effort: **S** < 3 days, **M** 1–2 weeks, **L** > 2 weeks (one engineer, INFERRED).

Rules every proposal keeps: no sample numbers shown as results; signatures only via step-up; nothing erased; blinding
honoured; SME-governed content shown as UNVERIFIED.

## P1: enable the redesign

| Feature | User problem it solves | Existing backend support | Effort | Priority | Why now |
|---|---|---|---|---|---|
| Project navigation in the sidebar (steps Start → Inputs → Review & sign → Run, plus Campaigns, Library, History, Members, Settings) | Inside a project there is no persistent "where am I"; the step bar scrolls away under a 300–400 px hero, and project records hide in a hover rail | Full: `GET /projects/{id}/steps`, existing routes | S | P1 | The core of an AWS-style service navigation |
| Compact page header with breadcrumbs, title, status and actions | Every page spends a screen on a decorative hero; the actions sit far from the content | Full (frontend only) | S | P1 | Recovers 30–40 % of the first screen |
| Resource tables with sort, filter, column choice, counts and paging (projects, studies, documents, campaigns, people, keys) | 46 hand-built tables, 10 sortable; finding a study or document means scrolling | Full for data; paging is client-side (INFERRED fine at today's sizes) | M | P1 | One table component replaces many (Bloatware B-06) |
| Read-only state for people a project is shared with | They see edit buttons the API refuses (`NOT_OWNER`) | Full: `GET /members` returns `owner_name` and `you_change_it` (verified at Gate 2) | S | P1 | Ownership rule (2026-11-10) is enforced but not shown |
| "Your work" across projects: decisions, signatures, escalations and to-confirm items, each opening the page where it is decided | The dashboard lists attention items, but a reviewer with many projects has no queue; the old inbox was removed | Partial: `/steps` per project (N+1), `/escalations`; needs step state in `GET /projects` | M | P1 | Keeps the owner's rule (decide where the work is) while giving a reviewer a list. **Needs owner call (Q3)** |
| Agent activity per project: each run's agent, model, turns, tokens, refusals, who started it | A modeler cannot see what an AI read or why a value was proposed; a regulator will ask how inputs were made | Partial: `GET /agent-runs/{run_id}` exists and is unused; a list route is missing | M | P1 | Answers the governance item "report's how it was made section" (CONTINUATION §4.0d) |

## P2: expose what the backend already has

| Feature | User problem it solves | Existing backend support | Effort | Priority | Why now |
|---|---|---|---|---|---|
| Data plan (requirements) matrix per application **[owner question Q1: the owner dropped the data checklist from Start on 2026-10-23]** | The modeler cannot see which data an application (VBE, DDI, food effect, FIH, special populations) requires and which are covered | Full: `GET/PUT /requirements`, `requirements:derive` (SME templates) | M | P2 | Three routes with no screen |
| Impact preview before changing a confirmed or signed input | A change silently makes signed artifacts stale; the person learns afterwards on History | Full: `POST /projects/{id}/impact` | S | P2 | Unused route; prevents surprise re-signing |
| Campaign run results and package browser | Raw run series and the package contents are only reachable as named downloads | Full: `GET /runs/{id}/results`, `GET /campaigns/{id}/package` | M | P2 | Reviewer verification of what was submitted |
| Start from a published reference model (Dapagliflozin; Aciclovir illustrative) **[Gate 2: corrected, owner question Q2]** | Which applications the platform supports is invisible | Full: `GET /templates`, `/templates/{id}` | S | P2 | Unused routes |
| Signature register per project (who signed what, when, meaning, record hash) | Part 11 review needs one list of signatures; today they are spread over pages and the audit trail | Partial: signatures recorded (`record_signature`), visible inside `/audit`; a filtered read is missing | M | P2 | Regulator-facing package |
| System status page (API, engine and PK-Sim version, agents and their models, intake pipeline) | When something stalls, nobody can tell which part is down; the only signal is a green dot | Partial: `/health`, `/admin/overview` ("the platform"), `/admin/pipeline`, `doctor.py` | M | P2 | Ops clarity for a single-node server that "drops off the LAN" |
| Unlock a placed study on the plan canvas | A locked placement cannot be undone from the UI | Full: `plan/placements/{s}:unlock` | S | P2 | Unused route |
| Live status (runs, Data room, campaigns, escalations) without polling | Pages re-read on timers; 30 s polling from every page | None (D15 planned SSE) | L | P2 | Removes B-15 |
| Notifications centre (escalation opened, run finished, Data room ready, limit reached) | Events are only noticed by visiting the page | Partial: escalations, limit warnings; needs an event feed | M | P2 | Pairs with live status |
| Cross-project activity feed | "What changed since yesterday" needs opening each project's History | None (app-design-merge gap 2) | M | P2 | Dashboard and admin both need it |
| QA role with read-all, audit and signature review | The role exists in Keycloak and the console but grants nothing | Partial: `deps.READ_ROLES` (not locked) would admit it; QA screens are new | S–M | P2 | Part 11 independent review |
| Model version comparison (CPF and verdict diff between campaign rounds or plan versions) | "What moved this verdict?" requires reading history by hand | Partial: artifact history, change ledger and influence map (`modeler_orchestrator.history`) | M | P2 | Uses T-54 output that has no view |

## P3 and FUTURE

| Feature | User problem it solves | Existing backend support | Effort | Priority | Why now |
|---|---|---|---|---|---|
| Global search (projects, compounds, studies, documents) with a command palette | Navigation by memory across many projects | None (per-project lists exist) | M | P3 | Matters once the portfolio grows |
| Expert tools: snapshot preview, M15 table validation, ad-hoc engine run | Engine-level checks need the API docs | Full: `model-versions/preview`, `m15/validate`, `POST /runs` | S | P3 | Low demand INFERRED; keep API-only until asked |
| Admin routines (key age, spend, failed runs, engine, backups) with "run now" | Planned module G | None | M | P3 | Already in the admin plan |
| Support "view as" (read-only) | Planned module H | None | M | P3 | Already in the admin plan |
| Client data request tracking (sent, answered, overdue) | Data requests A–D are printed or copied; their follow-up is manual | Partial: `PATCH dataroom/requests/{id}` | M | P3 | After the intake path decision (Q1) |
| Static DDI screening | Triage mechanisms before dynamic PBPK | Domain only (`pbpk_domain.ddi_static`, UNVERIFIED ruleset); no API | M | FUTURE | Needs SME sign-off first |
| Client portal (the client uploads and answers data requests) | Data arrives by email and is re-uploaded | None; new auth surface | L | FUTURE | Commercial decision |
| Project assistant answering questions over the project record, with citations to audit and sources | Finding why something is as it is | Partial: agents and citation checks exist | L | FUTURE | Only with code-verified citations and no writes; Part 11 risk |
| Groups and teams within a company | Sharing per person only | None; owner deferred | M | FUTURE | Owner: "more access management later" |

## Deliberately not proposed
- Demo or "live" decorative charts, sparklines from hashes, offline demo mode: rejected by the owner (2026-11-06/07).
- Accept/Reject of agent proposals without a decide route: would show a control that does nothing.
- A password field on signing, impersonation, hard delete: Part 11 rules.
