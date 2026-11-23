# design-review/

Isolated workspace for the AWS-console-inspired redesign charter (2026-11-22). Nothing here is production code:
no file in this folder is imported, built or deployed, and no production file was changed to make it.

## Gate status
| Gate | Phases | State |
|---|---|---|
| 1 Product discovery | 0–2 | **Approved** 2026-11-23 (decisions in [`DECISIONS.md`](DECISIONS.md)) |
| 2 Information architecture | 3 | **Ready for review** |
| 3 Wireframes | 4 | Not started (waits for Gate 2 approval) |
| 4 Final design and technical | 5–7 | Not started |
| Implementation | 9–10 | Needs separate explicit authorisation |

## Gate 2 documents
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
