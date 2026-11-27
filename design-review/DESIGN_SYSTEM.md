# Design System (Phase 5, Gate 4)

The visual and interaction language of the redesigned Modeler One. The high-fidelity prototype
([`prototype-hifi/index.html`](prototype-hifi/index.html)) is its reference implementation: every rule here is visible
there. Inputs: the owner's decisions G1-1 … G1-4, D-P1 and the Gate 2–3 answers ([`DECISIONS.md`](DECISIONS.md)).

**Reference, not copy.** Interaction patterns follow the AWS Management Console as published in AWS's open-source
Cloudscape Design System (app layout with navigation, help and split panels; flashbar; breadcrumbs; collection tables
with filter, preferences and pagination; status indicators; key-value pairs). No AWS logo, colour, typeface, icon or
product label is used: Modeler One keeps its own mark, palette and type.

> **Revision 2026-11-27 (decision D-I4):** the look is "Graphite" (`docs/plans/2026-11-27-console-graphite-restyle.md`),
> which replaced design option 5, "Brand Navy bar" (D-I1, 2026-11-24). §2 and §3 below carry its values. Where another
> part of this document and D-I4 differ (tab and button style, until R3), D-I4 and
> `apps/web/app/styles/tokens.css` win.

## 1. Principles
1. **Evidence before decoration.** No curve, sparkline or number is drawn unless it comes from the record; a chart says
   where its data came from. A page that cannot read the API says so and shows nothing stale.
2. **One place per decision.** A decision has one home; lists link to it (owner's rule, 14 Nov; "Your work" is links only).
3. **Dense, not crowded.** Tables over cards; 34 px controls; a compact page header; whitespace separates groups, it
   does not pad them.
4. **Plain words.** Four status words; no engine ids, paths or field names on screen (`lib/words.ts` is the dictionary).
5. **The signature is never casual.** Signing is always a dialog, says what is signed and its meaning, and hands off to
   the identity provider (never a password in Modeler One).
6. **Accessible by construction.** WCAG 2.2 AA, keyboard first, colour never alone.

## 2. Colour
Tokens only; no component names a hex value (`apps/web/app/styles/tokens.css`). Graphite: a neutral, slightly warm grey
scale; near-black ink for actions and the current choice; one blue for data, source links and focus; the status colours.
Ratios computed (WCAG 2.x relative luminance).

| Token | Value | Use | Contrast (computed) |
|---|---|---|---|
| `--c-canvas` | `#F4F4F5` | page background | — |
| `--c-surface` | `#FFFFFF` | panels, tables, side navigation | — |
| `--c-surface-2` | `#F4F4F5` | table headers, toolbars, hover | — |
| `--c-surface-3` | `#E9E9EC` | the segmented control's track, a progress rail | — |
| `--c-border` / `--c-border-soft` / `--c-border-2` | `#E4E4E7` / `#EFEFF1` / `#D4D4D8` | hairlines / panel edges and rows / a secondary button's edge | non-text (a button's word names it) |
| `--c-control-edge` | `#8A8A93` | edges of inputs, selects, checkboxes | 3.42:1 white, 3.11:1 canvas (≥ 3:1) |
| `--c-ink` | `#18181B` | headings, primary text, links (underlined) | 17.72:1 white, 16.12:1 canvas |
| `--c-ink-2` | `#3F3F46` | table text, labels | 10.44:1 |
| `--c-ink-3` | `#52525B` | secondary text on any surface | 7.73:1 white, 6.55:1 on the tint, 6.38:1 on the track |
| `--c-ink-muted` | `#6B6B74` | placeholder, meta on white or the canvas only | 5.28:1 white, 4.80:1 canvas; **not on the tint** (4.47:1) |
| `--c-accent` | `#18181B` | the primary button, the current navigation item and tab, key counts, progress | white on it 17.72:1 |
| `--c-accent-hover` | `#2E2E33` | hover/pressed primary | white on it 13.51:1 |
| `--c-accent-tint` | `#ECECEE` | selected row, current navigation item | ink on it 15.02:1 |
| `--c-focus` | `#2563EB` | the focus outline (2 px) | 5.17:1 white, 4.70:1 canvas, 4.38:1 tint, 3.43:1 on the ink |
| `--c-run` / `--c-run-bg` | `#1D4ED8` / `#E8F0FE` | something running (a step, a campaign, an agent run) | 5.85:1 |
| `--c-flash` / `--c-flash-line` | `#FEF3C7` / `#E8C16A` | the bar that asks for a person (a decision waiting) | ink on it 15.91:1 |
| `--c-info-bg` / `--c-info-line` | `#EFF5FF` / `#A9C3F7` | information banners | ink 16.18:1, ink-3 7.06:1 |
| Status ink / background | pass `#166534`/`#DCFCE7` · warn `#92400E`/`#FEF3C7` · fail `#991B1B`/`#FEE2E2` (unchanged, D-I4) | status labels, banners | 6.49 · 6.37 · 6.80:1 |

**The one blue.** `#2563EB` is for the charts' first series, source links, the focus outline and (as its darker step)
what is running. Not for headings, buttons or large fills. The ink does the work the navy accent did.

### 2.1 Chart palette (validated with the data-viz skill's validator, all pairs, on white and on the canvas)
| Slot | Token | Value | Job |
|---|---|---|---|
| 1 | `--c-chart-1` | `#2563EB` | the model / predicted; the reference product |
| 2 | `--c-chart-2` | `#EA580C` | observed; the test product |
| 3 | `--c-chart-3` | `#0D9488` | the reformulated product |

Result (2026-11-27): lightness band, chroma floor, contrast (all ≥ 3:1 on white), normal-vision floor (worst ΔE 22.6,
blue↔teal) and CVD separation (worst 13.8 protan) pass; blue↔teal under tritan is 6.4, inside the 6–8 band that is legal
only with secondary encoding, which every chart has: **direct labels or a legend, and a table view (required)**. Fixed
order, never cycled; a 4th series folds into small multiples. Colour follows the entity, never its rank. Grid `#E4E4E7`,
axis `#A1A1AA`, text in ink tokens, never in series colour. The Data room's products use the same three (D-I4).

## 3. Type, space, shape
| | |
|---|---|
| Typefaces | **Plus Jakarta Sans** (variable, 200–800; used at 400–700) for everything; **JetBrains Mono** (400, 500) for ids, codes, hashes, sheet cells. Self-hosted (SIL OFL 1.1), no third-party request (D-I4) |
| Scale | 12 · 13 · 15 (body) · 16 · 17 (section) · 20 · 28 (page title) px; line height 1.5 body, 1.25 titles; weights 400 / 500 / 600, 700 for headings with −0.01 to −0.02 em tracking |
| Numbers | tabular figures in tables and counts; right-aligned numeric columns; units in the column header or after the value, never omitted |
| Dates | `2026-11-22 16:04` (24 h); relative time only as a tooltip |
| Spacing | 4 px grid: 4 · 8 · 12 · 16 · 20 · 24 · 32. Panel padding 16; between panels 16; page gutter 24 (16 on phones) |
| Radii | 6 (code, small wells) · 10 (buttons, fields, navigation items, banners) · 14 (panels, tables, dialogs) · pill for status labels (D-I4) |
| Elevation | panels: a hairline + `0 1px 2px rgba(24,24,27,.05), 0 6px 18px -8px rgba(24,24,27,.14)`; overlays (dialog, popover, side panel): `0 2px 6px rgba(24,24,27,.06), 0 24px 48px -16px rgba(24,24,27,.28)`; the primary button and a secondary button's faint lift. Nothing else casts a shadow |
| Icons | 24-unit line icons, 1.75 stroke (1.5 from R3, D-I4), 16 px in navigation and text, 13–14 px in badges; always beside a word, or with an accessible name |
| Motion | none decorative. State changes only (focus, hover 120 ms, side navigation slide on small screens); `prefers-reduced-motion` turns spinners and skeleton shimmer off |

## 4. Layout
The Graphite layout (D-I4 choice 3, built in R2): no top bar. A sidebar on the grey canvas; the page as one white rounded
panel beside it, its own bar on top.

| Region | Spec |
|---|---|
| Sidebar | 256 px on the canvas, fixed, always open ≥ 1024 px. **Top (always, never scrolls):** the mark on an ink tile and "Modeler One" → Home; **Start from proposal** (the product's one primary action, filled ink); **Search** "Go to project…" with its shortcut (⌘K, Ctrl K off a Mac); Home, Your work (with the count of what waits on the person), Projects, Campaigns. **Middle (scrolls):** the context from the address: a project (its name, Add data, Overview, the four steps with their state, Records, Project), the platform administration, or the portfolio's Admin console link for its owner; then Help. **Foot:** the person (initials, name to the account page, Sign out; "Development sign-in" under the development sign-in). Items 34 px, 10 px radius; hover the tint; the current item a white raised row with its word in ink |
| Page panel | white, 14 px radius, a hairline and the soft shadow, 10 px from the window's edge |
| Page bar | 52 px at the top of the panel, sticky to the window: the menu button (below 1024 px), the breadcrumbs on one line (the page's own name in ink; below 760 px the last two only), then **notifications** (a bell; a dot when something waits on the person; its list: the first six of Your work, each a link), **Help**, and **the API's state** (a pill with a green dot when its reads answer; a click asks again) |
| Content | fluid; tables use the full width; reading text max 80 ch; page gutter 24 px (16 on phones) |
| Help panel | 340 px right column (overlay below 1100 px); opened by "Info" |
| Side (split) panel | 600 px on the right from 1600 px; docked at the bottom below that; a sheet on a phone. Escape closes |
| Breakpoints | ≥ 1100 full · < 1100 help panel overlays · < 1024 the sidebar becomes a menu under the page bar (Escape or a new page closes it), the panel fills the window · < 760 the breadcrumbs keep two parts, the API pill its dot · < 640 tables stack into labelled rows |

### 4.1 Page templates
| Template | Used by | Shape |
|---|---|---|
| Summary | Home, Overview, Admin overview | header · 2 columns (2:1): main tables left, key-value panels right |
| Collection | Projects, Your work, Campaigns, Documents, People, Keys… | header with one primary action · one panel: toolbar (filter, selects) → table → footer (count, pager, preferences) |
| Workspace with tabs | Inputs (7), Review & sign (7), Campaign (6), History (4), Usage (5) | header · status line or flash · tabs (≤ 7) · tab content |
| Workspace with sections | Data room (13 sections, owner Gate 3 answer 1), Help | header · run line · left section list with status words · section content |
| Form | Create project, Start | numbered panels of field rows (field · value · status · action) |
| Detail | Campaign, Compound, Agent run, Company | header with status badges · tabs or panels · key-value |
| Document | Evidence report | centred page 840 px, print stylesheet, no shell when printed |

## 5. Components
### 5.1 Page header
Title (24/600) · status badge(s) · "Info" link · one-line description (ink-3, ≤ 80 ch) · actions right: **one primary**,
then secondary, then link buttons. Breadcrumbs above on every page below Home.

### 5.2 Buttons
| Variant | When |
|---|---|
| Primary (accent fill) | the page's or dialog's main action: Create project, Approve and sign, Upload a delivery. One per region |
| Normal (outline) | other actions |
| Link | inline secondary: "Back to the MS-01 default", "Its columns" |
| Danger (red outline) | archive, disable, retire; always behind a reason dialog |
| Small (28 px) | inside tables and side panels |
Labels are verbs naming the object ("Confirm and sign", not "OK"). Disabled buttons say why (title + a line nearby).

### 5.3 Status indicator
Icon + word, in a soft pill; never colour alone. Product words: **Missing** (✕ red) · **To confirm** (… amber) ·
**To decide** (⚠ amber) · **Done** (✓ green); "To sign" in Your work. Runs: Running (spinner, accent) · Escalated ·
Stopped · Passed · Failed · Proposed. Risk: Low/Medium/High risk with a gauge icon. Counts: accent pill only for "Your
work"; elsewhere neutral.

### 5.4 Tables (collections)
Toolbar: filter with a search icon (filters on every column's text), selects for the main facets, toggles. Header:
sortable columns show a chevron; `aria-sort` set. Rows: 9 px vertical padding; hover tint; a clickable row opens the
side panel (Enter works); the selected row keeps an accent edge. Footer: "n rows", pager, preferences (rows per page,
wrap lines, columns). Empty: one sentence of what will appear and, when the person can act, the action. **Phones:**
each row becomes a labelled block (cell label from the column header), controls keep their natural width.

### 5.5 Flash bar
Under the header; types info / success / warning / error with a 4 px left edge and an icon. Uses: read-only notice,
archived notice, "A decision is waiting", API unreachable ("Nothing on this page is current"), action results.
Action results say what happened in words; dismissible. Page-level problems are not dismissible.

### 5.6 Forms and dialogs
Label above the control (600), hint under it, error in red under it with the field focused. Required reasons use a
textarea and say "kept in the audit trail". Choices are bordered rows (radio or checkbox + text). Dialogs: 580 px,
title says the action and object, footer with Cancel + one primary, focus trapped, Escape cancels.
**Step-up dialog** (every signature): what is signed, its meaning (Part 11), and "your identity provider asks you to
confirm; the password and code are entered there, never in Modeler One".

### 5.7 Side panel, help panel
Side panel for a row's detail (study or product card, document preview, a value's source, a table layout); actions in
its header; never a second form for a decision that has a home elsewhere. Help panel for the page's explanation.

### 5.8 Key-value pairs
`dt` ink-3, `dd` ink 500; two columns; three columns for summaries on wide screens.

### 5.9 Charts
Form first: line for model against time; dots for observed; lines for dissolution profiles; a table when exact values
matter. One y axis, never two. 2 px lines, 9 px markers with a 2 px surface ring, recessive grid, direct labels (≤ 4
series) plus a legend (≥ 2 series). **Crosshair tooltip** per time point naming every series' value (hover targets
never overlap). **Chart / Table** switch on every chart; **Log / Linear** on concentration charts. The source and
round are in the panel title. In the product a chart only draws recorded results; the prototype marks its mock charts
"Illustrative · mock data · not a result".

### 5.10 MS-01 canvas
Six stage lanes (S1 → S6), study chips with a grip, "moved" badge with an accent edge for a change from the MS-01
default, hatched lane for blinded studies. Dragging is a pointer shortcut: every move is also possible with "Move…" in
the studies table below (keyboard), and every move asks for a reason.

### 5.11 Source viewers
**Document:** page image with the value's box outlined in accent, page controls, zoom; the quote under it.
**Sheet:** cell grid in mono, the table's range shaded, the header row marked, column mapping stated in words.

### 5.12 States
Loading: skeleton lines (no spinner over content). Empty: icon, a title, one sentence, the action if any. Error: error
flash ("The API did not answer. Nothing on this page is current.") + Try again; never cached or sample data. Read-only:
info flash naming the owner; edit controls absent (not disabled), sign controls present for a reviewer.

## 6. Content rules
- Status words exactly as in §5.3; one name per concept (`lib/words.ts`).
- Sentences, not labels with colons, for explanations; explanations live in the help panel, not in cards.
- Name the person and the time for every decision and signature.
- UNVERIFIED and PROVISIONAL (SME) are shown wherever a rule or criterion is not signed off.
- Never "click here"; links name their destination.

## 7. Accessibility
WCAG 2.2 AA. Skip link; one `h1` per page; landmarks (banner, navigation, main, complementary). Focus visible (2 px
blue outline, `--c-focus`) and managed (dialogs trap and return focus; side panel focuses its Close). Targets ≥ 24 × 24 px (2.5.8).
Status by icon and word; charts with a table view. Live regions for action results. Reduced motion respected. The
prototype passes an automated check that every visible control has an accessible name and every page one `h1`.

## 8. Dark mode (later)
Every colour is a token in one `:root` block; dark mode redefines that block (and a validated dark chart palette)
under `prefers-color-scheme` and an explicit switch. Light only ships now (owner, G1-2); print stays light.

## 9. From today's code to this system
| Today (`apps/web`) | Becomes |
|---|---|
| `components/ui.tsx` (Card, chips, ApiProblem) + `components/kit` (Hero, PageShell, DataTable, SortableTable, Dialog, Tabs, Stepper, Banner) | one kit: AppShell, SideNav, PageHeader, FlashBar, Table (collection), StatusIndicator, Button, Dialog, StepUpDialog, SidePanel, HelpPanel, KeyValue, Tabs, SectionNav, Chart, EmptyState |
| `Hero` (300–420 px) | PageHeader (~88 px) |
| Hover rail `Nav.tsx` + `Stepper` | fixed SideNav with steps and status icons |
| 20 CSS files in cascade order | one token sheet + component styles |
| Motion system (`kit/Motion`) | removed; state transitions only |
| `targets.css` rules, `LiveRegion`, `kit/focus.ts`, `lib/words.ts` | kept as requirements |
| Plotly charts | the chart spec in §5.9 (library choice at implementation; Plotly can meet it) |
