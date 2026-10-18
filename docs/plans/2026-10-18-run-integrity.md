# R0 · Run integrity (P0–P5 redesign, first PR, 2026-10-18)

Status: **built** (2026-10-18, branch `run-integrity`). The owner chose this order on 2026-10-18: "fix them first", as
one small PR before the redesign document, with the campaign time budget "set at signing".

## Context: the P0–P5 redesign
On 2026-10-15 the owner tried the tool on real data and found P0–P5 "near to impossible" to get through: data is
entered at many phases, every item asks for Accept / Reject with a reason, the agents are weak, P3 Client data is the
worst, and the UI is dull. The agreed way forward:

1. **The field map** (an interactive checklist page): the owner marked all 104 rows on 2026-10-17. 51 keep, 16 drop,
   14 move, 12 merge, 6 add, 5 agree. Their notes:
   - Quick start (published model): **drop**; without P0–P4 there is no modelling. The published OSP model becomes a
     source of inputs instead.
   - The digitizer must also read figures from images inside a PDF.
   - Values that agree across papers get more weight, with every paper recorded as a source; disagreeing values are
     still the person's choice, never averaged.
   - Escalations must open on screen in the project, not only in the review inbox.
2. **The owner's answers (2026-10-18):**
   - out-of-scope products (biologics, a local site of action, formulations beyond IR/MR) are asked at Start and
     refused clearly ("not supported yet") before any data work;
   - demographics: entered per study, or "healthy adult default" chosen explicitly and recorded as a MAP limitation;
   - SME thresholds (identifiability, data quality, acceptance per pathway): advisory and provisional until the SME
     signs;
   - no per-item review: one full review at the MAP signature (decision D-27, recorded with R1).
3. **The order** (each a PR the owner merges):
   - **R0, run integrity** (this document);
   - **R1**, the redesign document and wireframes, approved by the owner before any rebuild;
   - **R2**, the design foundation, then Start (P0 + P1);
   - **R3**, Inputs (P2 + P3 + P4);
   - **R4**, Review and sign (P5);
   - **R5**, removing the old pages (Quick start included), then the T-56 kit and the e2e flows.

## What R0 fixes (the guide's 4A.1–4A.3, 1.4, 3.7, 3.8)
| # | Defect found | Fix |
|---|---|---|
| 1 | The runner ignored the signed MAP: 30 min and 4 rounds for every stage | `LocalExecutor._limits`: the budget set at the start, else the MAP's stage budget, else 30 min; the MAP's `max_rounds`, else the request's. Each stage notes its limits and their source. S3 now runs 2 rounds (MS-01) |
| 2 | The MAP's stage budgets came from a fixed 1 h | The campaign budget is a plan structure choice (`campaign_budget_seconds`, default 8 h), split by MS-01's fractions. A warning at signing when a fit stage's share is under a fit's 15-min reserve |
| 3 | A campaign could start on an unsigned MAP | `run_guard.require_signed_map`: 409 in pilot and production unless the MAP is SIGNED or a `map_approval` signature is recorded on its bytes; development allowed |
| 4 | The model risk silently defaulted to medium (plan seeding, project creation, prepare, the run button) | Required everywhere; the plan blocks the signature until it is set (with a reason) |
| 5 | A generic signature left no audit event in file mode | `part11.record_signature` appends `signature.create` |
| 6 | The P6 rail never moved | Derived from the project's campaigns in the runner's store |
| 7 | Escalations only in the review inbox | `EscalationPopup` on the project and campaign pages |

## Not changed (locked or out of scope)
- `map.py` (locked): read only. MS-01's fractions and round limits are SME content and are not touched.
- The Temporal path keeps its fixed limits until Temporal is deployed (CHANGELOG known gap).
- The 1-hour goal vs MS-01's S3 fraction plus the fit reserve: listed for the SME and the owner, not decided here.

## Verification
- `make test` (only the 15 known container-only failures), `make lint`, `tests/architecture`, the web typecheck and
  build, dev e2e 18/18.
- **PK-Sim (Actions runs 39131983498 and 39132704379):** the Dapagliflozin round trip, as-is and refit give the
  same results as before R0 (CHANGELOG). None reaches S3, so its 2-round limit is unit-tested only.
