# Phase 7: frontend seams, with the web types generated from the API contract

Status: **done (7a–7d).** Each step was one PR to `main`, with no behaviour change unless stated. 7d landed as two PRs,
hooks then CSS, so that each stayed reviewable (a deviation from one PR per step).
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
- **7b — done.** The answers the contract types now come from `Schema<…>`:
  - `lib/pipeline.ts`: phases, artifacts, history, audit;
  - the client-data, evidence and inputs pages, and the start page;
  - the escalation resolve call, with `ResolveRequest` / `EscalationResolved`.

  What was added for it:
  - **`Narrow<Schema<…>, {…}>`** types an answer's open-object fields (stored content) by hand. It only accepts keys
    the answer has, so a field the API drops or renames fails the typecheck.
  - **Generation flag:** `--default-non-nullable false`, so a field with a default is optional. A request body may
    leave it out, and an answer sent with unset keys left out may not have it.
  - **Tightened API models** where the values are a closed set, so the generated types keep the unions the pages use:
    - phase ids (`PhaseId`);
    - `PhaseStatus` and `ArtifactStatus`;
    - change kinds;
    - dissolution `problems` as strings;
    - `RunSummary`, whose keys `run_store.start_run` has always written.

    The view model `PhaseStatus` (a row) is renamed `PhaseRow`. The answers are unchanged, as the conftest guard
    checks. 7a's null guard on the brief page went back out once `RunSummary` said what the records hold.
  - **Still hand-typed:** `lib/types.ts` (campaign, results, read API) and `lib/plan.ts` (P5). Their routes were not
    typed in phase 6, so they wait until those routers get response models.

  The original scope was: **every page answer from `Schema<…>`:** `lib/types.ts`, `lib/pipeline.ts`, `lib/plan.ts` and the page-local types
  that describe an API answer become aliases of the generated models, one module at a time. Each mismatch tsc reports
  is either a web bug (fixed in the page) or a too-loose model (tightened in the API, with the snapshot and the
  CHANGELOG). Stored content, such as the brief, the plan, a CPF record and a dataset, stays hand-typed until its owner
  module gives it a model in the contract.
- **7c — done. One API client,** `lib/api.ts`, typed by route from the generated `paths`:
  - A call names its route as the contract does: `get("/api/v1/projects/{project_id}/brief", { project_id })`. The
    path parameters, the body and the answer type follow from the route; `send`, `upload` and `serverGet` work the
    same way. A page cannot call a route that does not exist, send a body the request model rejects, or read the
    wrong shape.
  - `lib/writes.ts` lost its own transport and keeps its domain calls; `lib/reads.ts` and `lib/pipeline.ts` read
    through `serverRead` / `serverGet`. `apiFile` serves the downloads. The unused `apiPost`, `apiPostAuth`,
    `createSignature` and `decideEscalation` are gone.
  - Routes the contract does not type yet (P5 plan, campaigns, CPF, projects, templates, the read API) keep
    `apiGet` / `apiSend` / `serverRead` with a hand-written answer type.
  - **Guard:** `tests/architecture/test_web_client.py` fails on a `fetch` outside `lib/api.ts`, and on an untyped
    helper called on a route whose answer the contract types.
- **7d — B6 hooks and CSS:**
  - **Hooks — done.** `lib/hooks.ts` on react-query, which was already a dependency, with `components/Providers.tsx`
    as the cache:
    - `useResource(route, params, { select, poll })` reads a typed route;
    - `useMutation().run(call)` refreshes the page's resources and the server-rendered phase rail after a change
      succeeds.

    The P1–P4 review pages, the sheet reader, the digitizer and the blinding panel use them. The P5 canvas, the
    campaign pages and the escalation decision keep their own loading until their routes are typed.
    `test_web_client.py` checks that only the hooks import the typed read `get`.
  - The phase list is already read from the API (`PhaseRail` uses `/phases`).
  - **CSS — done.** `app/globals.css` keeps the base and the classes several pages share. Each feature's rules are in
    `app/styles/<feature>.css` (campaign, pipeline, brief, evidence, client-data, plan, inputs). The root layout
    imports them in the order the rules had in the single sheet, so the cascade is unchanged. All 277 rules were kept,
    which a split script checked, along with every pair of rules whose order moved.

## Verification (every PR)
- `npm --prefix apps/web run typecheck` (including the drift check) and `build`.
- `make test` and `make lint`.
- The e2e specs, unchanged except where a page's markup changes on purpose.
- CI on the PR.
