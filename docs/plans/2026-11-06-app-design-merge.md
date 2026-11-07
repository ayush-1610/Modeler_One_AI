# The "Modeler One App" design, reviewed and merged with the web app (2026-11-06)

Source: the Claude Design canvas "Start Page UI Mockups", page **Modeler One App** (migrated to claude.ai on
2026-11-06). The owner's direction (2026-11-06): review the design first, then implement it in `apps/web`, merging it
"wisely" with the app: keep the design's look and structure where it is better, drop what in the app is not
important, and keep (or add) what the backend already supports that the design leaves out.

This plan is the record of that review and of what each phase builds. It does not change any SME-governed content
(rulesets, acceptance criteria, MS-01) or any API contract.

---

## 1. What the design is

One page that simulates the whole product in a single component, with a demo data set and an optional live mode
(`modeler-kit.js` calls the API when `apiBase` answers). Its screens:

| Screen | In the design | In `apps/web` today |
|---|---|---|
| Shell | A rail sidebar (64 px, opens to 240 px on hover, can be pinned), groups **Work** (Projects, Start from proposal, Review inbox with a count) and **Workspace** (Parameter library, History, Settings), the person and a connection dot at the foot | A fixed 236 px sidebar with three links, a "This project" group (Add data, Project Document Library), the theme toggle, the person |
| Dashboard | A coloured hero (eyebrow, title, lede, "+ New project"); four KPI tiles; search, filter chips, cards / list; project cards with a step ring and a sparkline; side column with "Simulation, live", "Needs your attention", "Risk across programs", "Recent activity" | "Projects": a heading and one table (compounds, open questions, risk, history link, archive / restore with a reason) |
| New project | Drug, name, context, one drop zone for every file; a "Ready to start 0 / 3" side card | `/projects/start`: the same fields, plus document tags |
| Start, Inputs, Review & sign, Run | A sticky step bar, the hero per step, tabs, and simplified versions of each step's content | Each step's full page (Start, Inputs workspace, Plan canvas and review tabs, the run page with campaigns, system, members) |
| Review inbox | Parameter proposals with Accept / Reject; escalations with a decision, a rationale and "Sign & submit"; a "Reviewer patience" chart | `/review`: proposals (read only) and escalations with the signed decision |
| Library, Settings | A global parameter library; three switches | Neither exists (the library is per project) |

## 2. Review

### 2.1 What the design gets right (adopted)
1. **A dashboard, not a table.** The first screen answers "what waits on me, what is running, where does each
   program stand" before listing projects. Every number it needs exists in the API (projects, their four steps,
   campaigns, escalations, proposals).
2. **Where each project stands, at a glance.** The four steps shown on each project as progress, with its state
   (needs you, running, done) and the next action written out ("Review the brief", "Sign the MAP").
3. **The page head.** Eyebrow, title, a one-sentence lede and the page's actions: the same structure as the kit's
   `PageShell`, with more presence. Used on the dashboard first.
4. **Grouped navigation with a count on the inbox.** The inbox is where signed decisions wait; a count on it is the
   one badge that earns its place.
5. **Copy.** The design's sentences ("Nothing is approved here: the one review is at the MAP signature", "Values are
   never averaged", "Escalations resume only through a signed decision") are precise and match the product's rules.
6. **The signature dialog text.** It says the password is never entered into Modeler One and the signature comes
   from the session's step-up. That is the rule (`CLAUDE.md`) and how `StepUpDialog` already works.

### 2.2 What the design gets wrong or cannot do (not adopted, with why)
1. **Demo numbers presented as live.** "Simulation, live" draws a predicted curve over observed dots on a loop, and
   the cards draw sparklines from a hash of the compound name. Neither is a simulation. In a product whose rule is
   "a result counts only if it ran on real PK-Sim", a decorative concentration–time curve on the first screen reads as
   evidence. **Dropped.** A card shows the project's real step progress instead.
2. **"Ask for a password on every signature" (Settings).** Contradicts the design's own signature dialog and the
   Part 11 rule here: signatures come from the token's step-up, never a password typed into the app. **Dropped.**
3. **Accept / Reject on agent parameter proposals in the inbox.** There is no decision route for
   `GET /api/v1/proposals` (the design's live mode says so in its toast). Accepting is done where the value is used
   (Inputs, evidence decisions). **Not built**; the inbox keeps proposals read only. Listed as an API gap (§4).
4. **A global "Parameter library" and "Settings".** No backend for either (the library is per project:
   `GET /projects/{id}/library`). Showing them would be navigation to nothing. **Dropped from the sidebar** until the
   backend has them.
5. **"Recent activity" across programs.** The audit trail is per project (`GET /projects/{id}/audit`); there is no
   cross-project feed, and reading every project's chain on each dashboard load does not scale. **Deferred** (§4).
6. **Archive is missing.** The design's project list has no archive / restore. A project is a Part 11 record, never
   erased (owner's decision 5, 2026-10-29). **Kept**: the list view is the current table with archive / restore and
   the History link.
7. **Hover-to-open rail sidebar.** Opening on hover covers the page, flickers under a passing pointer and is not
   reachable the same way by keyboard. **Changed**: a button collapses the sidebar to a rail and back; the choice is
   remembered in the browser.
8. **Colour.** The design uses Apple blue (`#0071E3`) as the primary and for chrome, and "the interface is light
   only". The app's palette reserves saturated colour for meaning (teal predicted, amber observed, verdict colours with
   text twins that pass AA) and supports dark mode. **Kept the app's tokens**; the design's layout, radii, spacing and
   hero gradient are drawn with them, in light and dark.
9. **Demo data in the step screens.** The design's Start, Inputs, Review and Run screens are simplified, hard-coded
   copies of pages the app already builds from the API (with citations, sources, grades, the plan canvas, the MAP
   signature). Rebuilding them from the mockup would lose function. **Kept the app's pages**; the design's head and
   step bar are applied to them in phase B.
10. **The "Reviewer patience" chart, the magnet / count-up effects.** Decoration with no data behind it. **Dropped.**

### 2.3 What the app has that the design leaves out (kept)
Document tags on Start from proposal, the project document library and "Add data" at any step, the stale-artifact
notices, the members panel, the system panel, the campaign monitor and package downloads, the escalation popup on a
running project, the theme toggle, the skip link and the 404 page. None is removed.

### 2.4 What in the app is removed or demoted
- The dashboard's bare "Projects" heading and its paragraph: replaced by the hero and KPI row.
- The project table as the only view: it becomes the **List** view beside **Cards**.
- "+ Start from proposal" as a nav label: "Start from proposal" (the action, without the symbol).

## 3. Phases

**A — shell and dashboard (this change).**
- Sidebar: groups *Work* (Projects, Start from proposal, Review inbox with the count of open escalations and
  proposals) and *This project* (Add data, Project Document Library, History); collapse to a rail and back; the
  person and the theme toggle at the foot. Every existing link name, test id and the skip link are kept.
- Dashboard (`/`): hero; KPI tiles (projects and compounds, running, needs you, open questions), each a filter;
  "Needs your attention" (each project step that waits on a person, with its reason, and the inbox); "Risk across
  programs" (program risk, counted); search, filters, Cards / List. Cards show the four steps from
  `GET /projects/{id}/steps`, the state, the open questions, the risk and the next action, and open the step that
  waits. List is the current table (archive, restore, history).
- No API change, no new endpoint.

**B — the step pages.** The hero (as `PageShell`'s head) and a sticky step bar on Start, Inputs, Review & sign and
Run; the Run page's sections in the design's order (campaigns, compounds and studies, questions, members).

**C — the inbox.** The design's escalation card layout (decision, rationale, sign) over the existing
`EscalationDecision`; the open count in the head.

## 4. API gaps found (not built here; each needs its own change and an OpenAPI update)
1. A decision route for agent parameter proposals (`/api/v1/proposals/{id}:decide`).
2. A cross-project activity feed (recent audit events across the tenant's projects, paged).
3. Step state in `GET /api/v1/projects` (today the dashboard reads `/steps` per project: one call each).

---

## 5. Revision, 2026-11-07: match the design's look

The owner (2026-11-07), after phase A: the design has a completely different look, and the app should match it ("Implement
this design in this codebase … match how it looks, using this codebase's own components and conventions", with a
screenshot of the design's Inputs step). This supersedes §2.2 items 7 and 8 and the "keep the app's tokens" choice:

- **Palette and type** (`app/globals.css`): the design's neutrals (`#F5F5F7` bench, `#1D1D1F` ink, `#6E6E73` secondary),
  its blue `#0071E3` as the primary and as the predicted series, its amber `#B25000` as the observed series and "needs
  you", its green `#1E7B45` for done; the system UI font (SF Pro on Apple devices); radii 9 / 14 / 24 px. Dark mode was
  kept at first, then removed (§5.1).
- **The shared pieces** (`app/styles/design.css`, loaded last): the rail sidebar that opens over the page on hover or
  focus and can be pinned (§2.2 item 7 reversed at the owner's request; it also opens by keyboard focus); the centred
  head (`Hero` in `components/kit`) with the area's colour wash and the product's curve as decoration; the step bar as a
  floating pill under the head that stays in view; tabs as a segmented control; white panels with a 24 px radius and a
  long soft shadow; pill buttons; Start's numbered sections; Inputs' values as one panel with a hairline between rows.
- Every page now opens with the head: Dashboard, Start a project, Start, Inputs, Review & sign, Run, History, Review
  inbox, the document library, a compound's CPF and a campaign. The step bar follows the head (passed to `PageShell`,
  `StartScreen`, `InputsWorkspace` and `PlanCanvas` as `steps`).
- Still not adopted (unchanged from §2.2): the decorative "Simulation, live" panel and the cards' sparklines, a password
  on signing, Accept / Reject without an API route, the global library / Settings / activity feed.

### 5.1 Light only, the design on every page (2026-11-07)
The owner: remove the dark theme and apply the design to all pages. The design is light only, so the app is now too: the
dark tokens, the theme toggle and its boot script are gone. The 404, error and loading screens use the design's head,
dialogs use its neutral backdrop, and wide tables scroll inside their panel.

## 6. The theme spec, applied as a re-skin (2026-11-07)

The owner shared the design's full theme spec (tokens, motion, components, states). Applied as its option D: the
existing app is re-skinned; no logic is rewritten. Added: the spring engine, magnetic tiles, scroll reveal, the head's
parallax, the progress bar, the compacting step bar, rolling counters, the page transition, toast, celebration burst,
modal entry, skeleton loading, the sidebar's light and connection dot, and the spec's exact token values.

Not adopted, and why (the repo's rules win where they conflict with the spec):
1. **Offline demo mode with sample data.** `CLAUDE.md` and the read layer: a page shows why it could not read the API,
   never sample data. The connection dot says Live or not; nothing on screen is invented.
2. **Sparklines on project cards and the "live" curve card.** Decorative concentration–time shapes read as simulation
   results; only real PK-Sim runs count. Cards show the real four steps instead.
3. **Recent activity across projects.** Still no cross-project feed in the API (§4, gap 2).
4. **Content rising as it scrolls in, and the step bar changing height when it compacts.** Both moved interactive
   content under the pointer (a figure being digitized, the plan canvas), so a point or a drop could land off target.
   Content and a new page fade in place instead, and the bar compacts by scale and fade.
