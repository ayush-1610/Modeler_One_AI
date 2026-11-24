# Design System (Phase 5, Gate 4)

The visual and interaction language of the redesigned Modeler One. The high-fidelity prototype
([`prototype-hifi/index.html`](prototype-hifi/index.html)) is its reference implementation: every rule here is visible
there. Inputs: the owner's decisions G1-1 … G1-4, D-P1 and the Gate 2–3 answers ([`DECISIONS.md`](DECISIONS.md)).

**Reference, not copy.** Interaction patterns follow the AWS Management Console as published in AWS's open-source
Cloudscape Design System (app layout with navigation, help and split panels; flashbar; breadcrumbs; collection tables
with filter, preferences and pagination; status indicators; key-value pairs). No AWS logo, colour, typeface, icon or
product label is used: Modeler One keeps its own mark, palette and type.

> **Revision 2026-11-24 (decision D-I1):** the visual style is design option 5, "Brand Navy bar"
> (`design-review/console-options/O5-NavyBar.dc.html`). Where this document and D-I1 differ (top bar colour, radii,
> button and tab style, alert style, status colours), D-I1 and `apps/web/app/styles/tokens.css` win.

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
Tokens only; no component names a hex value. 60 % neutral · 30 % structure · 10 % accent.

| Token | Value | Use | Contrast (computed) |
|---|---|---|---|
| `--canvas` | `#F8FAFC` | page background | — |
| `--surface` | `#FFFFFF` | panels, tables, top bar, side navigation | — |
| `--surface-2` | `#F1F5F9` | table headers, toolbars, hover | — |
| `--surface-3` | `#E2E8F0` | skeletons, empty bars | — |
| `--border` / `--border-2` | `#E2E8F0` / `#CBD5E1` | hairlines / stronger dividers | non-text |
| `--control-edge` | `#7C8798` | edges of inputs, buttons, checkboxes | 3.64:1 on white (≥ 3:1) |
| `--ink` | `#0F172A` | headings, primary text | 17.85:1 |
| `--ink-2` | `#334155` | table text, labels | 10.35:1 |
| `--ink-3` | `#475569` | secondary text on any surface | 7.58:1 white, 6.78:1 on tint |
| `--ink-muted` | `#64748B` | placeholder, meta on white/canvas only | 4.76:1; **not on tints** (4.26:1) |
| `--accent` | `#001B94` | primary button, active nav and tab, focus ring, key counts, progress | white on it 13.25:1 |
| `--accent-hover` | `#00136B` | hover/pressed primary | 16.09:1 |
| `--accent-tint` | `#EEF2FF` | selected row, active nav background | accent text 11.85:1 |
| Status ink / background | pass `#17663A`/`#E7F4EC` · warn `#9A4500`/`#FDF1E4` · fail `#B3261E`/`#FBEAE8` · info `#001B94`/`#EEF2FF` | status indicators, flash bars | ink ≥ 6.5:1 |

**Accent budget (10 %).** Allowed: the one primary button per region, the active navigation item and tab, focus
rings, the Your work count, progress fills, selection, chart series 1. Not allowed: headings, tab counts (neutral),
decorative fills, large backgrounds. **Top bar stays light**: the accent on a dark bar is 1.35:1.

### 2.1 Chart palette (validated with the data-viz skill's validator, light surface)
| Slot | Token | Value | Job |
|---|---|---|---|
| 1 | `--chart-1` | `#2E4BC6` | the model / predicted; reference product. The accent's chart step: `#001B94` itself is too dark for marks (OKLCH L 0.33 < 0.43) |
| 2 | `--chart-2` | `#B25000` | observed; test product |
| 3 | `--chart-3` | `#1BAF7A` | reformulated product |

Result: lightness band, chroma floor, colour-blind separation (worst ΔE 13.6 deutan) and normal-vision floor (26.9) all
pass. Slot 3 is 2.82:1 against white, so **every chart has direct labels and a table view** (required, not optional).
Fixed order, never cycled; a 4th series folds into small multiples. Colour follows the entity, never its rank. Grid
`#E2E8F0`, axis `#94A3B8`, text in ink tokens, never in series colour.

## 3. Type, space, shape
| | |
|---|---|
| Typefaces | **IBM Plex Sans** (400–600, variable) for everything; **IBM Plex Mono** (400, 500) for ids, codes, hashes, sheet cells. Self-hosted (SIL OFL), no third-party request |
| Scale | 12 · 13 · 14 (body) · 16 (section) · 20 · 24 (page title) px; line height 1.5 body, 1.25 titles; weights 400 / 500 / 600 |
| Numbers | tabular figures in tables and counts; right-aligned numeric columns; units in the column header or after the value, never omitted |
| Dates | `2026-11-22 16:04` (24 h); relative time only as a tooltip |
| Spacing | 4 px grid: 4 · 8 · 12 · 16 · 20 · 24 · 32. Panel padding 16; between panels 16; page gutter 24 (16 on phones) |
| Radii | 4 (chips, badges inner) · 6 (controls, buttons) · 8 (panels, dialogs). No pill containers |
| Elevation | panels: 1 px border + `0 1px 2px rgba(15,23,42,.06)`; overlays (dialog, popover, side panel): `0 8px 24px rgba(15,23,42,.12)`. Nothing else casts a shadow |
| Icons | 24-unit line icons, 1.75 stroke, 16 px in navigation and text, 13–14 px in badges; always beside a word, or with an accessible name |
| Motion | none decorative. State changes only (focus, hover 120 ms, side navigation slide on small screens); `prefers-reduced-motion` turns spinners and skeleton shimmer off |

## 4. Layout
| Region | Spec |
|---|---|
| Top bar | 52 px, white, bottom border. Logo (the "Dose to curve" mark, unchanged, Q4) + name → Home · "Go to project…" (220 px, type-ahead) · right: Your work (count), Help, API status, avatar menu |
| Side navigation | 256 px, fixed, always open ≥ 1024 px, scrolls on its own; context: portfolio, project, admin (`PRODUCT_SITEMAP.md` §1). Group headings 11 px caps; items 34 px; active = 3 px accent bar + tint + accent text; step items carry a status icon |
| Content | fluid; tables use the full width; reading text max 80 ch |
| Help panel | 340 px right column (overlay below 1100 px); opened by "Info" |
| Side (split) panel | 520 px right overlay for a selected row's detail or a source; Escape closes |
| Breakpoints | ≥ 1100 full · < 1100 help panel overlays · < 1024 navigation becomes a menu, columns stack, in-page navigation becomes a scroll row · < 640 top bar drops the switcher and Help, tables stack into labelled rows |

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
accent ring) and managed (dialogs trap and return focus; side panel focuses its Close). Targets ≥ 24 × 24 px (2.5.8).
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
