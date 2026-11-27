# Decision Log

Every owner decision on the redesign, verbatim where possible, with what it changes. Newest first.

## D-I4 (2026-11-27): the look is "Graphite"; it replaces the navy look of D-I1
The owner found the redesigned console still short of what they wanted and asked for catalogues to choose from (palettes,
icon styles, fonts, inspiration from B2B SaaS, pharma and AI products, "our own way", comfortable for people from 18 to
60). A Design Studio (a private artifact of the owner's, with live previews) offered each choice; the owner's saved picks:
**direction** Clinical calm · **colours** Graphite mono · **fonts** Plus Jakarta Sans · **icons** fine line (1.5 stroke) ·
**corners** round (14) · **surfaces** soft shadows · **layout** left sidebar · **text size** standard (15 px; compact
shortlisted) · **theme** light. Note: Linear, Notion and the other inspirations "are great to get inspired or have
elements of them in our tool". A prototype of three pages in that look followed; **the owner approved it and the six
choices below ("approved", 2026-11-27):**
1. Corners: 14 px panels, 10 px buttons and fields.
2. Colour: near-black `#18181B` for buttons and the current choice; **one blue `#2563EB`** for charts, source links and
   the focus outline; the status colours (green, amber, red) unchanged.
3. The navy top bar goes: search (⌘K), "Start from proposal", Your work with its count and the account move into the
   left sidebar; notifications and Help sit top right of the page.
4. Icons: the app's own set at a 1.5 stroke, the missing ones drawn (a bell among them); no new icon dependency.
5. Identifiers (parameter ids, campaign ids, paths) in JetBrains Mono, as in the prototype.
6. A per-person "Compact view" switch, later.

The build, each step its own PR with the owner's review (`docs/plans/2026-11-27-console-graphite-restyle.md`): **R1**
colours, font, corners and shadows on every page; **R2** the sidebar layout replaces the top bar (phone menu included);
**R3** icons, buttons, tables, side panel and dialogs polished; **R4** accessibility pass over every page, a screenshot
gallery for sign-off, the deploy plan updated.

Consequences found while building R1 (for the owner's review in the R1 PR):
- The tokens keep their names (`app/styles/tokens.css`); only the values change, so no component changed its classes.
  `--c-ink-muted` (`#6B6B74`) stays for white and the canvas only (4.47:1 on the selected tint), as before.
- "Running" is the one blue's tint (`#1D4ED8` on `#E8F0FE`, 5.85:1), as in the prototype; it was navy on navy's tint.
- The bar that asks for a person (a decision waiting) is amber tint with its edge, not solid yellow: the prototype's
  decision banner.
- The charts' three colours are validated again (the data-viz validator, all pairs, on white and the canvas): predicted
  blue `#2563EB`, observed orange `#EA580C`, reformulated teal `#0D9488`. The Data room's products use the same three in
  place of the earlier brand indigo, teal and magenta, so every chart in the product speaks one palette.
- The sign-in pages (the app's and Keycloak's theme, `deploy/keycloak/themes/modeler-one`) take the same look; the
  Keycloak theme needs copying in at deploy (`deploy/server/keycloak.sh theme`, then a Keycloak restart).
- The product's mark is unchanged (G1-3). Until R2, the top bar is the ink, white on it.

## D-G4 · Gate 4 approved (2026-11-23)
The design system, the high-fidelity prototype and the backend mapping are approved. Next: the implementation plan
(`docs/plans/2026-11-23-console-redesign-implementation.md`) and the archive (`ARCHIVE.md`). Implementation needs the
owner's separate authorisation.

## D-G3 · Gate 3 approved, with its three answers (2026-11-23)
| # | Owner's answer | Effect |
|---|---|---|
| 1 | Data room sections: the left-hand list | As wired; DESIGN_SYSTEM §4.1 "Workspace with sections" |
| 2 | Inputs study card: the side panel | As wired; DESIGN_SYSTEM §5.7 |
| 3 | "Your work" count in the top bar and the portfolio menu | As wired |

## D-P2 · Chart palette (2026-11-23, derived; follows D-P1)
`#001B94` is too dark for chart marks (OKLCH lightness 0.33, below the 0.43 band floor), so charts use its lighter step
`#2E4BC6` as series 1 with `#B25000` and `#1BAF7A`. Validated with the data-viz skill's validator on white: all checks
pass; slot 3 is 2.82:1, so every chart carries direct labels and a table view. Magenta/teal pairs failed colour-blind
separation (ΔE 3–6) and were rejected. Details: DESIGN_SYSTEM.md §2.1.

## D-G2 · Answers to the Gate 2 questions (2026-11-23; Gate 2 itself not yet approved)

| # | Owner's answer | What it changes |
|---|---|---|
| Q1 | **Data plan page: yes, under Data, read-mostly.** The 23 Oct removal was about noise on Start (27 rows of "—" linked to nothing); a page under Data showing real status is different. It answers "what does a VBE or DDI application require, and do we have it?". The table shows each item, who provides it, its status and a link to the card where it is settled; **edits stay on the cards** (one place per decision). | P-13b confirmed. `GET /requirements` gets a screen. `PUT /requirements/{r}` (provider, purpose overrides) and `POST requirements:derive` (runs on every brief save already) stay API-only: no card edits them today, so the override has no screen, as since 23 Oct |
| Q2 | **No "start from a reference model" on Create project.** Create project is where real client work starts. The two `/templates` routes join the retire list (API contract update and CHANGELOG entry). **Keep the importer.** Verify, before deleting anything, whether tests or the engine-proof kit use the Dapagliflozin import. | P-04 has no reference option. Verified the same day (below): the routes cannot be deleted until two consumers move |
| Q2b | "Correct the record **if** you consider that data incorrect." | Not applied: no evidence says the published OSP Dapagliflozin data is incorrect (it is imported from the peer-reviewed snapshot with its 13 publications). The status doc is left as it is. Keeping it off Create project rests on the owner's own reason, not on the data's quality |
| Q3 | **Security fixes now: yes** (R-S01, R-S03, R-S04). R-S06 waits for the multi-server setup. | Fixed on 2026-11-23, see `REMEDIATION_PLAN.md` §1 |
| Q4 | **Keep the logo mark.** `#001B94` is for actions, active states, focus and key data; a logo redraw is a separate brand decision; revisit at Gate 4 if the gradient clashes. | Logo unchanged |
| Default | QA reads every project of its company; no edits, no signing. Not objected to. | R-S05 scheduled for implementation |

**Verification for Q2 (read in code, 2026-11-23).** The `/templates` routes still have two consumers that would break:
`apps/web/e2e/campaign-monitor.spec.ts` builds its three campaign projects from `GET /api/v1/templates/{id}` (its header:
"the template API stays for scripts and the reference runs"), and `deploy/showcase/seed_examples.py` lists and reads
them to seed the showcase. The importer behind them (`modeler_api.reference_models.TEMPLATES`, `pbpk_domain.reference`)
also serves a live Inputs feature, "take a published model's values" (`POST evidence:published-model`;
`published-model.spec.ts`, `table-sort.spec.ts`, `test_published_model.py`), and the T-56 proof kit reads the published
model through that feature's rules (`deploy/proof/run_t56.py`). So: the importer stays; the two routes retire only after
the campaign-monitor spec and the showcase script build their projects another way (for example `POST /projects` and
`evidence:published-model`), so no coverage drops silently.

## D-G1 · Gate 1 approved (2026-11-23)

| # | Owner's decision | What it changes |
|---|---|---|
| G1-1 | **Merge the two intake paths, with a clear split of jobs.** **Data room** = what the client sent and whether it is right (whole-delivery upload, the 13 sections, conflicts, data requests, evidence report). **Inputs** = what goes into the model (compound, products, studies, populations, settings, the fill-in forms, the signed confirmation). Inputs' rules (four status words, one list of work, one place per decision) apply to both. In navigation: one **Data** section with two pages; neither page calls the other "the earlier page". **Still open:** which "send to the model" step is the official one; the backend is unchanged for now. | Sitemap §3 "Data"; page inventory P-06, P-07; remediation R-B01 |
| G1-2 | **The AWS direction replaces the 7 Nov look.** Drop the large decorative headers, the hover-open sidebar and decorative animation. Add a fixed sidebar with the project's steps, breadcrumbs, compact page headers, denser tables. Keep the brand accent (see D-P1), IBM Plex, all accessibility work and the plain-words rules. **Dark mode: not now**; tokens built so it can come later; ship light only. | Sitemap §1 shell; design system (Phase 5) |
| G1-3 | **"Your work" list: yes, links only.** No decision is taken in the list; the 11 Nov rule "decide where the work is" holds. One backend change later (each project's step state in the project list); start with today's data. | Page P-02; remediation R-N03 |
| G1-4 | **Project records: reuse what exists.** Status → `docs/CONTINUATION_PACKAGE.md`; history → `CHANGELOG.md`. Only the feature registry and the API-to-page mapping stay in `design-review/`, moving to `docs/` after Gate 4. | No new root files |
| G1-5 | **Fix the screenless operations and the bloatware too**, "diligently", asking where anything is unclear. | [`REMEDIATION_PLAN.md`](REMEDIATION_PLAN.md): every item has a verdict and a home in the sitemap. Production changes still follow the charter's gates (see "Scope note" there) |

## D-P1 · Brand accent: deep royal blue `#001B94` (2026-11-23)

The owner's palette brief, applied to the design system in Phase 5. Recorded now because it shapes the shell.

**60-30-10.** 60 % neutral canvas (off-white, white, soft slate); 30 % structural UI (muted greys, hairline borders,
slate text, navigation, containers); 10 % accent `#001B94`, only for primary actions, active navigation and selection,
focus rings, key badges, progress fills and primary data series.

| Token (proposed name) | Value | Use | Contrast (WCAG 2.x, computed) |
|---|---|---|---|
| `--accent` | `#001B94` | primary buttons, active nav item, active tab, checked controls, focus ring, progress fill, the predicted series | white on it 13.25:1 (AAA); it on white 13.25:1, on `#F8FAFC` 12.67:1 |
| `--accent-hover` | `#00136B` | hover / pressed primary | white on it 16.09:1 |
| `--accent-tint` | `#EEF2FF` (≈ `rgba(0,27,148,0.08)` = `#EBEDF6` on white) | selected row, active nav background, icon wells | accent text on it 11.85:1 |
| `--ink` | `#0F172A` | headings, primary text | 17.85:1 on white |
| `--ink-2` | `#334155` | body text in dense tables | 10.35:1 |
| `--ink-3` | `#475569` | secondary text on **any** surface, including tints | 7.58:1 white, 6.78:1 on `--accent-tint` |
| `--ink-muted` | `#64748B` | secondary text on white and `#F8FAFC` only | 4.76:1 white, 4.55:1 `#F8FAFC`; **fails AA on `#F1F5F9` (4.34) and `#EEF2FF` (4.26)** |
| `--canvas` | `#F8FAFC` | page background | — |
| `--surface` | `#FFFFFF` | panels, tables, cards | — |
| `--surface-2` | `#F1F5F9` | table headers, toolbars | — |
| `--border` | `#E2E8F0` | hairlines | non-text |
| `--control-edge` | `#7C8798` | edges of inputs, checkboxes, selects (WCAG 1.4.11 needs ≥ 3:1) | 3.64:1 on white, 3.47:1 on `#F8FAFC`; the usual `#94A3B8` is 2.56:1 and fails |

Consequences found while checking contrast:
1. `#64748B` is not used for text on tinted or grey surfaces; `--ink-3` (`#475569`) is.
2. **The top bar stays light.** `#001B94` on a dark slate bar (`#0F172A`) is 1.35:1, so an AWS-style dark header would
   need a second, lighter accent for its active states. A white header with a bottom border keeps one accent
   everywhere and keeps the 60 % neutral share.
3. Semantic colours stay separate from the accent and keep their text-grade twins (pass `#17663A` 7.0:1, warn
   `#9A4500` 6.5:1, fail `#B3261E` 6.5:1); the observed series stays amber (`#B25000`, 5.2:1).
4. Dark mode later: every colour above is a token; no component names a hex value.

**Open (Q4 in the Gate 2 summary):** the logo mark today is an indigo-to-magenta gradient (`Nav.tsx` `Logo`,
`app/icon.svg`). Keep it as the brand mark, or redraw it in `#001B94`.

## D-I1 (2026-11-24): the visual style is option 5, "Brand Navy bar"
The owner judged slice 1's first styling too close to the look being replaced and asked for ten AWS-console design
options before going further. Ten were drawn on one canvas, the same campaign page in each
(`design-review/console-options/`, files `*.dc.html`; the canvas artifact is private to the owner). **Chosen: option 5,
as drawn** (the owner declined a mix with option 1, "Console Refresh").
- Top bar in the brand navy `#001B94`, white text (13.9:1), a white "Go to project" field, the API state as a light pill,
  the person's initials on a white disc. The logo mark is drawn in white there (same shape; the indigo line would
  vanish on navy).
- Side navigation white, items rounded and inset, the current one on `#EEF2FF`; each step's state a small tinted disc;
  "Add data" an outlined button.
- Breadcrumbs with "/" separators; page title 28 px; status as a tinted pill beside it.
- Panels white with a `#DADDE6` border, 10 px radius and a soft shadow; key-value cells divided by hairlines.
- Buttons 8 px radius: secondary outlined in navy, the page's one primary filled navy.
- Tabs as a segmented control on a `#E7EAF2` track, the current one white and raised.
- Alerts bordered and tinted (ink text); the flash bar that asks for a person solid `#FBD332`.
- Status labels: tinted pills with the word (pass `#166534` on `#DCFCE7`, warn `#92400E` on `#FEF3C7`, fail `#991B1B`
  on `#FEE2E2`, each ≥ 6:1).
- Supersedes "The top bar stays light" (consequence 2 above): the bar itself is the accent, so no second accent is
  needed for active states on it; focus rings on the bar are white.

## D-I2 (2026-11-24): slice 4, study cards and its landing
- **Inputs' study and product cards open one at a time in a side panel** (the Gate 3 answer), and that wins over the
  rule of 2026-11-05 that kept up to three study cards open inline with the first to confirm opened by itself. The
  first card to confirm opens in the panel; Next and Previous move between them.
- **Slice 4 lands as two PRs:** 4a (Data room status words, the Data plan page, the "earlier page" links removed, the
  model system moved from Run to Inputs) and 4b (Inputs' cards in the side panel, the impact preview).
- Data room section words, chosen in 4a for the owner's review: in order → **Done**, needs a look → **To confirm**,
  missing → **Missing**; a section with nothing delivered keeps **Nothing yet** (no task yet).

## D-I3 (2026-11-24): slice 9, which API operations retire now
- **The verified retirements now, each its own commit:** `POST /campaigns/{id}/feedback:decide`,
  `POST …/questions/{q}/map:generate` and `POST /projects/{id}/client-review:edit` (REMEDIATION §2, #19–21), and
  `/templates` once its two consumers (the campaign-monitor e2e, `seed_examples.py`) no longer use it.
- **Not now:** `GET /proposals` and its chain (R-B13) and `pbpk_domain.snapshot.parameter_transfer` (R-B13b) stay until
  their owners say so.
- Found while doing it: `/templates` is named in `tests/architecture/boundaries.toml`, a locked file, so the routes
  themselves are removed in a separate PR with the owner's approval; their consumers already read
  `reference_models.starting_point`.
- 2026-11-25: the owner approved that PR ("Slice 10 approved, merge it and open the /templates PR"): the routes, their
  answers and the boundary entry are removed, the locked hash refreshed.

## Earlier owner decisions that still bind the redesign
| Date | Decision | Source |
|---|---|---|
| 2026-11-14 | Six Inputs rules: one list of work; one home per decision; one card per study or product; one row per file; four status words (Missing · To confirm · To decide · Done); nothing a person can do today becomes impossible | `docs/plans/2026-11-14-inputs-task-first.md` §2 |
| 2026-11-11 | Review inbox removed: a decision is asked where the person is | `Nav.tsx`, `shell.spec.ts` |
| 2026-11-10 | Owner-only edits; shared members read; a reviewer it is shared with signs | admin plan §3 answers 4, 6 |
| 2026-11-10 | Admin console for `modeler-admin` only; no impersonation, no password through the platform, nothing erased | admin plan §2 |
| 2026-11-06/07 | No sample numbers as results, no decorative curves or sparklines, no offline demo | app-design-merge plan §2.2, §6 |
| 2026-10-29 | Projects archived with a reason, never deleted | page review 1 |
| 2026-10-23 | Start: the data checklist, "How the model is used", "What a wrong decision means" dropped from the page (kept in the brief) | `docs/plans/2026-10-23-page-by-page-review.md` §4.1 |
