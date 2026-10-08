# Phase 7: frontend seams, with the web types generated from the API contract

Status: **7a done** (this plan's first PR). 7b–7d next, each one PR to `main`, with no behaviour change unless stated.
Sources:
- `docs/ARCHITECTURE_BOUNDARIES.md`: rules B2 and B6, the L7 row, §6 phase 7.
- The OpenAPI snapshot `docs/api/openapi.json`. Phase 6 typed every P0–P4 and escalation answer in it.

## Why
The web app hand-wrote the shape of every answer, in `lib/types.ts`, `lib/brief.ts`, `lib/pipeline.ts`, `lib/plan.ts`
and in the pages. Nothing compared those types with what the API sends, so a renamed or dropped key passed the API's
tests and the web typecheck alike, and broke in the browser. Since phase 6 the API's answers are typed, so the web
types can be generated from the same contract.

## Decision (the owner, 2026-10-08)
- Adopt `openapi-typescript` as a dev dependency of `apps/web`, pinned to exactly `7.13.0`. It is a code generator:
  it adds nothing to the app's runtime bundle.

## Steps
- **7a — done:**
  - `npm run api-types` generates `apps/web/lib/api-types.ts` from `docs/api/openapi.json`. The file is committed.
  - `npm run typecheck`, which CI's web job runs, first checks the file against the snapshot
    (`openapi-typescript --check`). It fails while the file is older than the snapshot. The OpenAPI contract test's
    message now says to regenerate both.
  - `Schema<"Name">` in `lib/api.ts` names a generated response model.
  - **Pilot, the brief:** `BriefView`, `DocumentView` and `Impact` in `lib/brief.ts` are now generated types. The
    stored brief content and the field kinds of its catalog stay hand-typed, because the API sends them as open
    objects.
  - The generated types surfaced one gap. The contract allows an agent run's `status` and `summary` to be null, and
    the brief page read them unguarded. The page is now null-safe.
- **7b — every page answer from `Schema<…>`:** `lib/types.ts`, `lib/pipeline.ts`, `lib/plan.ts` and the page-local types
  that describe an API answer become aliases of the generated models, one module at a time. Each mismatch tsc reports
  is either a web bug (fixed in the page) or a too-loose model (tightened in the API, with the snapshot and the
  CHANGELOG). Stored content, such as the brief, the plan, a CPF record and a dataset, stays hand-typed until its owner
  module gives it a model in the contract.
- **7c — one API client:** `serverRead`, `apiPost` and `apiPostAuth` become one client, typed by route from the
  generated `paths`. A call names its route, and the answer type follows from the route, so a page cannot read the
  wrong shape. `lib/reads.ts` and `lib/writes.ts` go through it.
- **7d — B6 hooks and CSS:**
  - Client pages fetch with `useResource` and change state with `useMutation`, both on react-query, which is already a
    dependency. A mutation refreshes the phase rail and the page's own resource. This replaces hand-written
    fetch-then-refresh code.
  - The phase list is already read from the API (`PhaseRail` uses `/phases`).
  - CSS is split per feature, where a page's styles live in the global sheet.

## Verification (every PR)
- `npm --prefix apps/web run typecheck` (including the drift check) and `build`.
- `make test` and `make lint`.
- The e2e specs, unchanged except where a page's markup changes on purpose.
- CI on the PR.
