# The console redesign: implementation plan (2026-11-23)

**Status: plan only. No production code changes until the owner gives a separate, explicit implementation
authorisation** (charter Phase 9 → 10). Gates 1–4 are approved; their record is `design-review/` (start at its
`README.md`; decisions in `design-review/DECISIONS.md`).

## 1. What is being built
The approved design, as specified by:
| Document | Role in implementation |
|---|---|
| `design-review/PRODUCT_SITEMAP.md`, `PAGE_INVENTORY.md` | the 34 pages, routes and navigation |
| `design-review/DESIGN_SYSTEM.md` + `prototype-hifi/index.html` | the visual and interaction spec; the prototype is the reference implementation |
| `design-review/API_PAGE_MAPPING.md` | every page action's endpoint, models and permissions |
| `design-review/BACKEND_CHANGE_REQUIREMENTS.md` | the API changes, retirements and their prerequisites |
| `design-review/REMEDIATION_PLAN.md` | defects and bloatware, with verdicts |
| `design-review/ARCHIVE.md` | the baseline (`pre-aws-redesign-20261123-1601`) and how to restore it |

**Out of scope:** any science change (MS-01, rulesets, acceptance, CPF, builder, engine), SME-governed content, locked
files (except where a step below names one and asks), the Temporal path (R-S06 waits for it), dark mode (tokens ready,
light ships), the official "send to the model" choice (G1-1, owner's later decision: both sends stay).

## 2. Frontend architecture
| Concern | Decision | Why |
|---|---|---|
| Framework | Stay on Next.js 16 app router, React 19, TanStack Query through `lib/hooks.ts` (`useResource`, `useMutation`) | Works; 165 browser tests depend on it |
| API access | The one typed client `lib/api.ts` (enforced by `tests/architecture/test_web_client.py`); new routes get types from `docs/api/openapi.json` | No raw `fetch`, as today |
| Rendering | Server components read first (as `lib/reads.ts` does) for a fast first paint; client components for interaction | As today |
| Styling | `app/styles/tokens.css` (DESIGN_SYSTEM §2–3, one `:root` block, dark-ready) + one CSS Module per component (`*.module.css`, built into Next, no dependency). Old global sheets move into `app/styles/legacy/` and are deleted page by page | Ends the 20-sheet cascade (B-07) without a big bang |
| Shell | `app/layout.tsx` renders `AppShell`: `TopBar`, `SideNav` (context from the route: portfolio, project, admin), `main`, `HelpPanel` slot, `SidePanel` portal, `FlashBar` context | Sitemap §1 |
| Icons | `components/kit/icons.tsx`: the prototype's 24-unit line set, inline SVG | No icon dependency |
| Charts | Keep Plotly behind one `<Chart>` wrapper that adds the legend, direct labels, the Chart/Table switch, Log/Linear, the crosshair (`hovermode: "x unified"`) and the token palette | Lowest risk; replacing Plotly with a small SVG chart is a later bloat item (the prototype shows it is feasible) |
| Fonts | IBM Plex, already self-hosted (`app/fonts`) | — |
| New runtime dependencies | **None** | Charter rule |
| Test ids | **A contract.** New components accept and keep every existing `data-testid` (1,142 in source; e2e uses 2,117 `getByTestId` calls). A moved element keeps its id | Most specs survive the restyle |

### 2.1 Component map (today → new)
| Today | New | Notes |
|---|---|---|
| `components/Nav.tsx` (hover rail), `kit/Stepper` (step bar) | `kit/TopBar`, `kit/SideNav` (steps with status icons) | Step state from `/steps` (then R-N03) |
| `kit/index.tsx` `Hero`, `PageShell` | `kit/PageHeader` (+ `Breadcrumbs`); `PageShell` kept as an adapter so pages change little in slice 1 | |
| `components/ui.tsx` `Card`, `RiskChip`, `StatusChip`, `ProvenanceChip`, `ApiProblem` | `kit/Panel`, `kit/StatusIndicator`, `kit/Badge`, `kit/FlashBar` | B-05 |
| `kit/DataTable`, `kit/SortableTable`, 46 raw `<table>` | `kit/Table` (filter, sort, preferences, pager, row → side panel, stacked rows on phones) | B-06, migrated page by page |
| `kit/Dialog`, `StepUpDialog`, `delivery/ConfirmDialog` | `kit/Dialog`; `StepUpDialog` restyled, wording per DESIGN_SYSTEM §5.6 | Signing logic unchanged |
| `campaign/EscalationPopup` (every page, 5 s) | `FlashBar` item on the project's pages + Your work row; the decision dialog opens from there | R-S02 |
| `kit/Motion` (spring, magnetic, parallax, burst) | removed | B-09 |
| `kit/Tabs`, Data room rail | `kit/Tabs` (≤ 7), `kit/SectionNav` (Data room, Help) | Owner Gate 3 answer 1 |
| `kit/SourcePeek`, `dataroom/SourceDrawer`, document dialog | `kit/SidePanel` + `SourceViewer` (page / sheet) | |
| `ConcentrationTimePlot`, `dataroom/kit` charts | `kit/Chart` (§2) | |
| `targets.css`, `kit/LiveRegion`, `kit/focus.ts`, `lib/words.ts`, `lib/inputsWork.ts` | kept (requirements, the owner's rules) | split by area later (B-11) |

### 2.2 Routes
Kept: every URL that exists today. New: `/work`, `/projects` (list; today part of `/`), `/projects/[id]/campaigns`
(today's Run page; `/projects/[id]` becomes the Overview), `/projects/[id]/data-plan`, `/compounds`,
`/agent-activity`, `/agent-activity/[run]`, `/members`, `/settings`, `/help`, `/admin/companies`, `/admin/system`.
`/review` redirects to `/work`. Old bookmarks to `/projects/[id]` land on the Overview, one click from Run.

## 3. Backend changes, in the order the slices need them
| Id | Change | Slice | Locked file? |
|---|---|---|---|
| R-S02 | `can_decide` on `GET /escalations` | 1 | no |
| R-N03 | step state and owner name in `GET /projects` (`?with=steps,owner`) | 2 | no |
| R-N09 | `GET /projects/{id}/signatures`. **First a failing test** that confirms an escalation signature is missing from `GET /projects/{id}/audit` | 7 | no (reads the locked audit store, does not change it) |
| R-N05 | `GET /projects/{id}/agent-runs` | 7 | no |
| R-N08 | `GET /admin/system` with an engine check | 8 | no (calls the locked engine scripts, does not change them) |
| R-S05 | QA reads every project of its company | 8 | `auth.py` **only if** the grant cannot live in `memberships.admit`; then its own PR with the owner's approval |
| Retirements | `feedback:decide`, `map:generate`, `client-review:edit`, `/proposals` + dead chain, `/templates` (after moving its 2 consumers), `parameter_transfer` | 9 | no |
| Later | R-N06 (live status, SSE), R-N07 (platform audit log) | after acceptance | no |

**Database:** no migration. The single-node stores are files; the Part 11 mirror is unchanged. Every API change is
additive until the retirements in slice 9, so the archived frontend keeps working against the new API.

## 4. Permissions and security (unchanged guarantees)
- Owner-only writes (`ownership.owner_guard`), reviewer signing, step-up for every signature, blinding (D-15) and the
  admin role stay exactly as enforced today. The UI only reflects them: read-only state from `GET /members`
  (`you_change_it`), roles from `GET /me`.
- New reads (R-N03, R-N05, R-N09) are membership-checked like their neighbours; each gets a two-member test (a
  non-member sees nothing) and, for R-N09, a blinded-study test.
- The step-up dialog's wording and flow do not change; no password field anywhere.
- R-S06 (password-in-body Temporal routes) stays recorded for the multi-server deployment.

## 5. Testing strategy
| Layer | What | Gate |
|---|---|---|
| API (pytest) | Failing test first for every backend change; contract snapshot updated; role and membership tests | `make test`, `tests/architecture` |
| Contract | `UPDATE_SNAPSHOTS=1 … test_openapi_contract.py` + `npm run api-types` for each API change | CI `web` typecheck |
| Browser (Playwright) | The 165 existing tests run after every slice; specs that assert moved structure are updated in the same slice (shell, dashboard, Run page, members, review inbox redirect). New specs per new page: Your work, Overview, Data plan, Agent activity, History signatures, Admin system | CI `web` e2e |
| Roles | Role views tested by answering `/api/v1/me` with the role (as `plan-viewer.spec.ts` does) and by API tests for the enforcement | per slice |
| Accessibility | A new spec ports the prototype's checks to the real app: every visible control named, one `h1`, focus order through the shell, target size ≥ 24 px, dialogs trap focus; at 1440 and 390 px | slice 1 onward |
| Responsive | Smoke at 390 px for every route: no sideways page scroll | slice 1 onward |
| Visual review | Screenshots of each slice's pages for the owner, beside the prototype's | each slice |
| Science | None of these slices touch it; engine numbers in tests stay stub-engine software evidence | — |

CI (`.github/workflows/ci.yml`, locked) is not changed.

## 6. Sequence (each slice: its own branch from the current integration head, its tests, CHANGELOG, owner review)
| Slice | Scope | Exit criteria | Effort |
|---|---|---|---|
| 0 Prep | Archive (done, verified); push the tag and archive branch (owner's go-ahead); bring `main` and the session branch together (owner's choice, §8) | baseline reachable from the remote | S |
| 1 Foundations and shell | Tokens, icons, Button, StatusIndicator, Badge, FlashBar, PageHeader, Breadcrumbs, TopBar, SideNav (3 contexts), HelpPanel, SidePanel, Dialog; every existing page inside the new shell through the `PageShell` adapter; hover rail, Hero and motion removed; escalation pop-up → flash + R-S02 | all 165 e2e green (shell/dashboard specs updated); a11y and 390 px specs pass | L |
| 2 Collections and portfolio | `Table`; Home, Your work, Projects (cards option kept), Campaigns; R-N03 | Your work = links only; N+1 gone | M |
| 3 Project frame | Overview (new home), Run → `/campaigns`, Members, Settings, Compounds list, CPF page | old URLs land correctly; members/archive specs updated | M |
| 4 Data | Data room restyle (section list, the four status words), Inputs restyle (tabs, study and product cards in the side panel), Data plan (read-only), impact preview, "earlier page" links removed | Inputs owner-job specs green; Data room specs green | L |
| 5 Review & sign | Tabs, canvas restyle, "Back to the MS-01 default" (`:unlock`), impact preview, read-only polish | model-plan, review-sign, plan-viewer green | M |
| 6 Campaign | Tabs (Stages, Fit, Rounds, Feedback, Package, Runs), `<Chart>`, Package tab (`GET /package`), decision dialog from the flash | campaign-monitor, feedback, escalation specs green; fixture banner unchanged | M |
| 7 Records | Documents, History (4 tabs) + R-N09, Agent activity + R-N05 | signature test passes; agent runs listed | M |
| 8 Admin | Console restyle, Companies list, System status + R-N08; R-S05 if approved | admin specs green | M |
| 9 Cleanup | Delete legacy CSS, `ui.tsx`, old kit pieces, motion; retirements (each its own commit after its prerequisite); README and `docs/USING_THE_TOOL.md` updated | no orphan, lint and typecheck clean | M |
| 10 Acceptance | Full regression, accessibility and responsive pass, the owner uses it on real work, deploy plan | the owner's acceptance | M |

Effort: S < 3 days · M 1–2 weeks · L 2–3 weeks of one engineer (INFERRED; AI-assisted sessions are usually faster but
the owner's reviews set the pace).

## 7. Rollback
- **Per slice:** each slice lands as one merge commit; `git revert -m 1 <merge>` undoes it. Backend changes are
  additive and separate commits, revertible alone.
- **Whole redesign:** restore `apps/web` from `pre-aws-redesign-20261123-1601` (`design-review/ARCHIVE.md`); the API
  stays compatible because retirements come last (slice 9) and only after acceptance.
- **Server:** redeploy the previous `main` head or the tag with `bash deploy/dev/deploy_to_server.sh`. No data
  migration, so no data rollback.

## 8. Bloatware removal plan
| When | What | Gate |
|---|---|---|
| Slice 1 | `kit/Motion`, `Hero`, hover rail, decorative curve | replaced in the same slice |
| Slices 1–8 | 20 global stylesheets → tokens + modules; 39 inline styles; `ui.tsx` and duplicate tables and dialogs | page by page, deleted when unused |
| Slice 9 | `feedback:decide`, `map:generate`, `client-review:edit` | verification in REMEDIATION §2 |
| Slice 9 | `/proposals` + `upsert_proposal`/`list_proposals` + `modeler_agents.literature`, `parameter_curation` | owner's OK |
| Slice 9 | `/templates` | campaign-monitor e2e and `seed_examples.py` moved first; importer kept |
| Slice 9 | `pbpk_domain.snapshot.parameter_transfer` | science owner confirms |
| Kept | evaluation tooling, Temporal and S3 entry points, `requirement_drafts`, `ddi_static` | REMEDIATION §3 |
| Later | splitting `delivery_routes.py`, `DeliveryReview.tsx`, `InputsWorkspace.tsx`, `lib/words.ts`, `lib/inputsWork.ts`; Plotly replacement | own PRs, no behaviour change |

## 9. Risks
| Risk | Mitigation |
|---|---|
| Specs break on moved structure | test ids are a contract; specs updated in the slice that moves the element; full e2e per slice |
| Inputs and Data room are large and recently reviewed in seven rounds | restyle, do not rewrite: same components and hooks inside the new layout; behaviour diffs are bugs |
| The shell change touches every page at once (slice 1) | the `PageShell` adapter keeps page bodies untouched; screenshots of every route reviewed |
| R-N03 makes `GET /projects` slow | `?with=` opt-in; measured with 50 projects |
| Two sends to the model confuse | both pages say what they send and where; the owner's later decision picks one |
| `main` and the session branch diverge further | slice 0 brings them together before code moves |

## 10. Decisions needed before implementation starts
1. **Authorisation** to start implementation (slice 0 and 1 first; each later slice reviewed before the next).
2. **Landing:** a PR per slice into `main` (recommended; CLAUDE.md: `main` is the integration branch), or one
   redesign branch merged at the end.
3. **Push the archive refs:** the tag `pre-aws-redesign-20261123-1601` and the branch
   `archive/stylish-frontend-20261123-1601` exist only in this session until pushed.
4. **`main`:** merge this session branch (the Gate work, the security fixes and another session's two commits
   `445fb51`, `cf3f6ec`) into `main` before slice 1.
5. **QA (R-S05):** if the grant needs `auth.py` (locked), approve its own PR, or keep QA for later.

**Answers (2026-11-23, the owner):** 1 authorised, slices 0 and 1, review after each; 2 one PR per slice into `main`;
3 push the tag and the archive branch; 4 merge this branch into `main` before slice 1 (done: `main` fast-forwarded to
`000a59d`, which holds `445fb51` and `cf3f6ec`); 5 QA without `auth.py` if possible, else its own PR, otherwise later.
QA needs no `auth.py` change (a membership admit and the read roles), so it waits for slice 8.

## 11. Deviations recorded during implementation
| Slice | Plan said | Done instead | Why |
|---|---|---|---|
| 0 | push the tag and the archive branch | branch pushed; the tag push was refused (HTTP 403, this session's git access) | not worked around; the owner pushes the tag (`design-review/ARCHIVE.md`) |
| 1 | each slice on its own branch from the integration head | slice 1 on the session branch `claude/inspiring-einstein-191gn3`, which is `main` plus slice 1 | this session may push only that branch; the PR into `main` is the same review |
| 1 | escalation pop-up → flash bar | pop-up kept, filtered to `can_decide` (R-S02 fixed); the flash bar comes in slice 2 | an escalation whose campaign is not recorded yet has no project page; its only other home is Your work, built in slice 2 |
| 1 | HelpPanel, SidePanel, Dialog, FlashBar, Button, Badge, StatusIndicator as components | styles in `console.css` on the existing kit pieces; the components arrive with the first page that uses them (side panel slice 4, help and flash slice 2, decision dialog slice 6) | a component no page uses yet would be untested code; slice 9 removes the old ones |
| 1 | slice 1 styled to `DESIGN_SYSTEM.md` (light top bar) | restyled to option 5, "Brand Navy bar" | the owner's review of slice 1 (2026-11-24): too close to the old look; ten options drawn, option 5 chosen (DECISIONS D-I1) |
| 1 | side navigation lists every page of the sitemap | only pages that exist: Your work, Campaigns, Help, project Overview, Members, Settings, Compounds and Agent activity join with their slices; a campaign page shows the portfolio navigation until slice 6 | no link to a page that is not built |
| 2 | Home's projects table "recent 8" | the 8 newest active projects (the API lists projects in creation order) | the API records no "updated" time per project; "recently changed" needs one (later, with R-N06) |
| 2 | Your work and Projects show "waiting since" / "updated" | not shown | no timestamp on a step or project in the API; recorded for later |
| 2 | the flash bar sits under the page header | at the top of the content, above the breadcrumbs | the shell mounts one flash for every page; moving it under each page's header comes with the PageHeader component |
| 2 | the decision dialog restyled with the flash | the existing dialog, opened from the flash | its restyle is slice 6 (campaign page) |
| 2 | Help (P-30) in slice 2 | the user guide page another session added on `main` (renders `docs/USING_THE_TOOL.md`) | two Help pages arrived the same day; the one that renders the guide is what the page inventory asks for |
| 3 | Observed studies removed from Run (a duplicate of Inputs) | kept on Run as the studies a campaign fits | three owner-job specs read it as the proof that Inputs' studies reach the campaign (OWN-13); it goes with slice 4, when Inputs' studies are restyled |
| 3 | Model system moves to Inputs → Compound | stays on Run | it moves with Inputs in slice 4 |
| 3 | Settings and Members separate | Settings (built the same day by the sign-in work, with the members panel) shows who it is shared with as a summary; Members manages them | one home per decision |
| 3 | read-only notice as a flash bar on every project page | a notice on Overview, Members and Settings | the other pages' own edit controls are reworked in their slices (4 to 7) |
| 4 | one PR | 4a (Data plan, Data room words, links, model system) and 4b (Inputs' cards in a side panel, impact preview) | the owner, 2026-11-24 (D-I2) |
| 4 | observed studies removed from Run | kept | Review & sign's Overall Data does not list the studies Inputs holds; the Run list is the downstream check of OWN-13. A later change could give Review & sign that list, then Run's goes |
| 4b | impact preview before confirming a changed signed card again (`POST /impact`) | built in 4c with a new route, `GET …/delivery/subjects/{type}/{subject}/impact` | `POST /impact` previews one artifact's next content; a card's confirmation lands several records through the intake landing, so the preview is a dry run of the landing (`intake_landing.preview_landing`). The owner chose a 4c PR (2026-11-24) |
| 4b | the up-to-three-open rule (2026-11-05) | one card at a time in the side panel | D-I2 |
| 5 | impact preview on Review & sign (`POST /impact`) | each change's own dry run says what it changes: a move (`PUT …/placements?dry_run`) and the put-back (`POST …:unlock?dry_run`, new) | `POST /impact` needs the plan's next content, which only the server computes; the dry run is the plan's impact preview, and says when a change is a MAP deviation |
| 5 | Approve and sign in the page header (prototype) | in the signature panel above the tabs, with its note | the note and the signature stay together; the header carries the validator's badge |
| 5 | "Back to the MS-01 default" with a reason dialog (prototype) | a confirmation that says what it changes, no reason asked | `:unlock` takes none; after the signature it is recorded as a deviation "back to the MS-01 default", signed with the others |
| 6 | a Runs tab (raw run results) | not shown | the raw results exist only on the multi-server deployment (R-N08); a tab that can only say "not available" is left out until then |
| 6 | the S6 prediction and the VBE (not in the six tabs) | a Prediction (S6) tab, shown only once S6 gave one | they had a place on the old page and none among the planned tabs |
| 6 | tabs as buttons, as on Inputs and Review & sign | tabs as links (`?tab=`), the page drawn on the server | the campaign page is a server page that refreshes itself while a campaign runs; links keep it so, and each tab reads only what it shows (the package only on its tab) |
