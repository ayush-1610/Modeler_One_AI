# Decision Log

Every owner decision on the redesign, verbatim where possible, with what it changes. Newest first.

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
