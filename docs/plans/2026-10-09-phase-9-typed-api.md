# Phase 9: a typed answer for every API route, from the API through the web

Status: **9a and 9b done.** 9c–9e next. Each step is one PR to `main`, and nothing changes behaviour unless a step says so.
Sources:
- `docs/ARCHITECTURE_BOUNDARIES.md`: rules B2 and B6, coupling C5, §6 phase 9.
- The lists under `[response]` in the locked `tests/architecture/boundaries.toml`, which only shrink.

## Why
Phases 6 and 7 typed the P0–P4 and escalation answers. They also moved the review pages onto the generated types, the
one API client and the hooks.

The rest of the API still answers untyped JSON:
- the P5 plan;
- campaigns and escalations, which the orchestrator writes into the read model;
- projects, the CPF, studies and templates;
- signatures, runs and results;
- the system routes.

On the web side, `lib/types.ts`, `lib/plan.ts`, `lib/reads.ts` and `lib/writes.ts` mirror those shapes by hand. They
call them with the untyped helpers, and the P5 canvas still hand-writes its loading. As a result, a renamed key passes
every check and breaks in the browser.

The guard had two holes:
- `test_response_models.py` saw only the P0–P4 routers.
- It took any route without a response model for a file download. So routes whose handler had no return annotation
  (all of `read_api`, `templates_api`, and the routes on the app in `main.py`) were never counted.

## Decisions (the owner, 2026-10-08)
- **Guardrail:** the ratchet covers every router. The change goes in its own PR, because `boundaries.toml` is locked.
- **Run records:** the campaign monitor and escalation records get a shared model in `modeler_storage`, which owns the
  read model. The orchestrator writes through it and the API answers with it, so the writer and the reader cannot
  drift (B2, a typed contract at a process edge).
- **Stored content:** the contract reuses the owner modules' content models: `ModelPlan`, `EvidenceItem` and
  `ObservedDataset`. A probe confirmed their JSON round-trips unchanged.
- **Shapes:** as in phase 6, today's shapes are kept and typed. Records with camelCase keys stay camelCase.

## Steps
Each step after 9a types one area **in the API and the web together**. `test_web_client.py` fails as soon as a route
answers a typed envelope while the web still calls it untyped. Every step:
- adds tests for any route no test reaches, so the conftest identity guard checks every typed answer;
- updates the OpenAPI snapshot and regenerates `lib/api-types.ts`;
- adds a CHANGELOG entry.

- **9a — done. Guardrails (locked file, owner approval):**
  - `test_response_models.py` now counts a route as untyped whenever it has no pydantic response model. Only a handler
    annotated to return a `Response` is exempt, which leaves the 3 file downloads. The two download handlers that had
    no annotation now return `-> FileResponse`.
  - A second list, `[response] open`, holds the routes typed only as `Envelope[dict[str, Any]]`.
  - The 4 routes that lived on the app in `main.py` move unchanged to a new router, `modeler_api.system_api`:
    `/health`, `model-versions/preview`, `m15/validate` and `runs`.
  - `[response] routers` gains `plan_api`, `campaign_api`, `read_api`, `results_api`, `signatures_api`,
    `templates_api`, `write_api` and `system_api`. The lists record what is left: 37 untyped routes and 5 open
    answers.
  - The locked hash is refreshed. The OpenAPI snapshot is unchanged.
- **9b — done. The P5 model plan** (13 routes of `plan_api`; untyped 37 → 24):
  - **API:** a `views/plan.py` holds `PlanPage`:
    - `plan` is `ModelPlan`; alongside it are the artifact, violations, diff, overall data, D1/D2, MAP, deviations,
      agents and running;
    - the dry run answers `PlacementPreview`, signing answers `PlanSigned` (with `signature`), and the draft answers
      `DraftStart`;
    - new tests cover the routes no test reaches: `plan:view`, fits, structure, rebase, draft, and the dry run.
  - **Web:** the `lib/plan.ts` types become `Schema` aliases, and `planApi` calls the routes by name. `PlanCanvas` uses
    `useResource` and `useMutation`.
  - **As built:**
    - The plan's content models mark their defaulted fields as always present in the answer schema
      (`json_schema_serialization_defaults_required`), because the plan is always dumped whole.
    - The snapshot gains 13 response schemas and 29 schemas, and changes none.
    - The e2e specs for the canvas, blinding and new project pass.
- **9c — API-owned records** (part of `read_api`, plus `write_api` and `templates_api`):
  - **API:** `modeler_storage.records` gets `ProjectRecord`, `QuestionRecord` and `StudyRecord`, built by every API
    writer. There are also views for the CPF, templates, prepare, system and studies-stored answers. The partial test
    fakes are completed to the real shapes.
  - **Web:** `lib/reads.ts` moves to `serverGet` and `lib/writes.ts` to `send`.
- **9d — orchestrator-written records and the answers without an envelope** (`read_api`, `campaign_api`,
  `signatures_api`, `results_api`, `system_api`):
  - **API:** `CampaignRecord` and `EscalationRecord` go in `modeler_storage.records`, written by `local_runner`.
  - **Web:** a typed `post` for routes without the envelope replaces `rawPost`. The campaign types become `Schema`
    aliases, and the escalation decision, campaign start and new-project pages move to `useMutation`.
- **9e — the open answers:**
  - `POST /evidence` answers `EvidenceItem`. The dataset routes (`datasets`, `datasets:digitize`, `:overlay`,
    `:reveal`) answer `ObservedDataset`.
  - Both lists end empty. The web's untyped helpers are removed, leaving `apiFile` for downloads.

## Verification (every PR)
- `make test` (only the known environment failures are allowed), `make lint`, and `uv run pytest tests/architecture`.
- `npm --prefix apps/web run typecheck` (including the drift check) and `build`.
- The Playwright e2e specs, run locally on the stub engine. They prove the software path only.
- The T-56 kit stays green. It reads the real runner's full campaign record.
- CI on the PR.
