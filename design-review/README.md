# design-review/

Isolated workspace for the AWS-console-inspired redesign charter (2026-11-22). Nothing here is production code:
no file in this folder is imported, built or deployed, and no production file was changed to make it.

## Gate status
| Gate | Phases | State |
|---|---|---|
| 1 Product discovery | 0–2 | **Approved** 2026-11-23 (decisions in [`DECISIONS.md`](DECISIONS.md)) |
| 2 Information architecture | 3 | **Approved** 2026-11-23 |
| 3 Wireframes | 4 | **Approved** 2026-11-23 |
| 4 Final design and technical | 5–7 | **Approved** 2026-11-23 |
| Implementation readiness | 9 | **Ready for review**: [`ARCHIVE.md`](ARCHIVE.md) (archive verified), plan [`docs/plans/2026-11-23-console-redesign-implementation.md`](../docs/plans/2026-11-23-console-redesign-implementation.md) |
| Implementation | 10 | Needs separate explicit authorisation |

## Phase 9 documents
- [`ARCHIVE.md`](ARCHIVE.md): the baseline tag, archive branch and file copy of `apps/web`, verified identical to the
  tag and rebuilt from scratch; how to restore.
- [`../docs/plans/2026-11-23-console-redesign-implementation.md`](../docs/plans/2026-11-23-console-redesign-implementation.md):
  architecture, component map, backend order, permissions, testing, ten slices, rollback, bloatware removal, risks and
  the decisions needed to start.

## Gate 4 documents (approved)
- [`prototype-hifi/index.html`](prototype-hifi/index.html): the high-fidelity prototype. Same pages, routes, controls and
  behaviour as the approved wireframe, with the design system applied: IBM Plex, the token palette, icons, status
  indicators, collection tables (preferences, pagination, stacked rows on phones), charts with a table view and a
  crosshair, the MS-01 canvas, the document and sheet source viewers. Opens offline; mock data only.
- [`DESIGN_SYSTEM.md`](DESIGN_SYSTEM.md): principles, colour (with the validated chart palette), type, space, layout,
  page templates, components, content rules, accessibility, dark-mode readiness, and the map from today's code.
- [`API_PAGE_MAPPING.md`](API_PAGE_MAPPING.md): 100 page actions mapped to the 183 operations, with handlers, models and
  permissions read from the code; appendix of every operation's permissions.
- [`BACKEND_CHANGE_REQUIREMENTS.md`](BACKEND_CHANGE_REQUIREMENTS.md): what the design needs from the API, proposed
  contracts, retirements and their prerequisites.

## Gate 3 documents (approved)
- [`prototype/index.html`](prototype/index.html): the navigable low-fidelity prototype of all 34 pages, with prototype
  controls for role and page state. Opens directly in a browser; mock data only.
- [`WIREFRAMES.md`](WIREFRAMES.md): how to review it, the shell, role differences, every page's layout and states,
  verification, and three questions.

## Gate 2 documents (approved)
- [`PRODUCT_SITEMAP.md`](PRODUCT_SITEMAP.md): the shell, navigation per context (portfolio, project, admin), who sees
  what, old to new URLs, and where each screenless API operation lands.
- [`PAGE_INVENTORY.md`](PAGE_INVENTORY.md): all 34 pages (and 5 system items) with users, purpose, content, actions,
  backend routes and status.
- [`USER_FLOWS.md`](USER_FLOWS.md): ten flows across the new pages, with every signature and write marked.
- [`REMEDIATION_PLAN.md`](REMEDIATION_PLAN.md): verdicts for the 22 screenless operations and every bloatware
  candidate, six defects found while verifying, and an order.
- [`DECISIONS.md`](DECISIONS.md): the owner's Gate 1 decisions and the `#001B94` palette with measured contrast.

## Gate 1 documents (approved)
[`PROJECT_AUDIT.md`](PROJECT_AUDIT.md) · [`FEATURE_INVENTORY.md`](FEATURE_INVENTORY.md) ·
[`BLOATWARE_REPORT.md`](BLOATWARE_REPORT.md) · [`PROPOSED_FEATURES.md`](PROPOSED_FEATURES.md) ·
[`UNKNOWN.md`](UNKNOWN.md) · [`current-state/`](current-state/) (screenshots from the existing Playwright suite on the
stub engine with synthetic data; no number in them is a PBPK result). Gate 2 corrections are marked in each.

## Revision history
| Date | Feedback | Affected | Change | Reason |
|---|---|---|---|---|
| 2026-11-22 | — | — | Gate 1 package created | Charter Phases 0–2 |
| 2026-11-23 | Gate 1 approved; merge intake as one Data section (Data room + Inputs); AWS look replaces the 7 Nov look, light only, dark-ready; Your work as links only; reuse existing records | Sitemap, all project pages | Gate 2 package | Owner's decisions G1-1 … G1-4 |
| 2026-11-23 | Accent `#001B94` with 60-30-10 | Shell, design system | Palette recorded with contrast checks; light top bar; `#475569` for secondary text on tints | Owner's palette brief (D-P1) |
| 2026-11-23 | Fix the screenless operations and the bloatware, diligently | All | Every item verified in code; 22 operations (not 21); six defects found (R-S01 … R-S06) | Owner's request G1-5 |
| 2026-11-23 | Q1 Data plan yes (read-mostly); Q2 no reference start, retire `/templates` after verifying; Q3 fix security now; Q4 keep logo | P-04, P-13b, remediation | Applied; `/templates` consumers verified (2 must move first); R-S01, R-S03, R-S04 fixed in code with tests | Owner's answers (DECISIONS D-G2) |
| 2026-11-23 | Gate 2 approved | All pages | Gate 3 prototype and wireframe documentation | Charter Phase 4 |
| 2026-11-23 | Gate 3 approved (left-hand Data room sections, side-panel study card, count in both places) | Design system, all pages | Gate 4 package; screenless count corrected to 25; a signature-visibility gap found (R-N09) | Charter Phases 5–7 |
| 2026-11-23 | Gate 4 approved; prepare the implementation plan | apps/web baseline, plan | Archive made and verified; implementation plan written | Charter Phase 9 |
| 2026-11-23 | Authorised slices 0 and 1; PR per slice; push archive refs; merge into `main` first; QA without `auth.py` | Shell, all pages | Slice 0 done (tag push refused, owner pushes it); slice 1 built: the console shell; R-S02 fixed | Owner's implementation go-ahead |
| 2026-11-24 | Slice 1 looked too much like the old design; propose ten AWS designs; chose option 5 as drawn | Visual style, all pages | `console-options/` (ten designs); D-I1; slice 1 restyled | Owner's review of slice 1 |
| 2026-11-24 | Slice 1 approved; proceed to slice 2 | Portfolio pages, decisions | Slice 1 merged (#174); slice 2 built: Home, Your work, Projects, Campaigns, Help, R-N03, decision flash bar | Owner's review |
| 2026-11-24 | Slice 2 approved; proceed to slice 3 | Project frame | Slice 2 merged (#175); slice 3 built: Overview, Run at /campaigns, Compounds, Members, Settings |  Owner's review |
| 2026-11-24 | Slice 3 approved; slice 4: study cards in a side panel one at a time; two PRs | Data, Inputs | Slice 3 merged (#176); D-I2; slice 4a built |  Owner's review and answers |
