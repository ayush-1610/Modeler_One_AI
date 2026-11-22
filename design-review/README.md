# design-review/

Isolated workspace for the AWS-console-inspired redesign charter (2026-11-22). Nothing here is production code:
no file in this folder is imported, built or deployed, and no production file was changed to make it.

## Gate status
| Gate | Phases | State |
|---|---|---|
| 1 Product discovery | 0–2 | **Ready for review** |
| 2 Information architecture | 3 | Not started (waits for Gate 1 approval) |
| 3 Wireframes | 4 | Not started |
| 4 Final design and technical | 5–7 | Not started |
| Implementation | 9–10 | Needs separate explicit authorisation |

## Gate 1 documents
- [`PROJECT_AUDIT.md`](PROJECT_AUDIT.md): purpose, users and roles, architecture, routes, API surface, data model,
  current design language, constraints, git state, coverage checklist.
- [`FEATURE_INVENTORY.md`](FEATURE_INVENTORY.md): every capability, classified (functional, incomplete, backend-only,
  frontend-only).
- [`BLOATWARE_REPORT.md`](BLOATWARE_REPORT.md): candidates with evidence; nothing removed.
- [`PROPOSED_FEATURES.md`](PROPOSED_FEATURES.md): proposals tied to user problems and existing backend support.
- [`UNKNOWN.md`](UNKNOWN.md): what could not be found or checked.
- [`current-state/`](current-state/): screenshots of today's UI, captured from the existing Playwright suite on the
  stub engine with synthetic data (software evidence only; no number in them is a PBPK result).

## Revision history
| Date | Feedback | Affected | Change | Reason |
|---|---|---|---|---|
| 2026-11-22 | — | — | Gate 1 package created | Charter Phase 0–2 |
