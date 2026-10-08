# Phase 6: typed responses for P0–P4, one owner per artifact kind

Status: **6a–6e done** (every P0–P4 and escalation answer is typed; every artifact kind has one writer). 6f next.
Sources:
- `docs/ARCHITECTURE_BOUNDARIES.md`: rules B2 and B3, couplings C5 and C6, §6 phase 6.
- The exceptions in `tests/architecture/boundaries.toml` (`[response]`, `[owners]`, `[owner_exceptions]`), which only
  shrink.

## Why
- **C5, untyped and merged responses.** No route declared a response model, and every P0–P4 view was a
  `dict[str, Any]`. A renamed or dropped key passed every contract check and failed in the browser. The OpenAPI
  snapshot recorded the routes and the request models, but no answers.
- **C6, artifact content without an owner:**
  - Routers wrote artifacts: `brief_api` wrote the brief, `inputs_api` the CPF hand-off record, and `plan_api` the
    signed MAP.
  - The CPF kind has three ids (`main`, `choices`, `published`) with three untyped schemas.
  - `blinding` read the MAP's signature from raw JSON. A change to one stored key broke a page nobody had touched.

## Decisions (the owner, 2026-10-08)
- **Guardrails:** both ratchets are approved and recorded in the locked `boundaries.toml`. They may only shrink.
- **Response shapes:** keep today's shapes and type them as they are.
  - The client-data map answers with the preview merged into the page view (`{**preview, "datasets", **view}`).
  - The escalation routes answer without the envelope.

  Fixing the shapes is an API change that waits for phase 7's generated web types.

## Steps
- **6a — done.** Two guardrails, with no code change:
  - `tests/architecture/test_response_models.py` covers the routes of `project_api`, `brief_api`, `requirements_api`,
    `evidence_api`, `client_api`, `inputs_api` and `escalations`. A route must have a pydantic response model, or be
    listed under `[response] untyped`. That list holds 55 routes; the 2 file downloads are not counted.
  - `tests/architecture/test_artifact_owners.py`. `[owners]` names one module per artifact kind. Only that module
    commits the kind, and only owner modules read stored content raw (`.content[…]`, `.content.get(…)`,
    `**….content`). Today's exceptions:
    - 3 writers: `brief_api` → brief, `inputs_api` → cpf, `plan_api` → map;
    - 48 raw reads in 12 modules, recorded as exact counts.
- **6b — done** (P0/P1: the 11 JSON routes of `brief_api` and the 4 of `requirements_api`). As planned, plus:
  - `answers(Model)` in `modeler_api.responses` gives a route `response_model=Envelope[Model]` and
    `response_model_exclude_unset=True`, so a key the handler leaves out (an optional one) stays out.
  - A guard in `services/api/tests/conftest.py` compares every typed answer in the API tests with the handler's own
    return value, serialized without a model. A dropped, added or coerced value fails the test that made the request.
    A new test calls the 4 brief routes no test had reached (document upload, `brief:extract`, `items:remove`,
    `questions/{id}`).
  - The OpenAPI snapshot: 15 operations gain their 2xx response schema, and 33 schemas are added. No schema, request
    or parameter changed.

  The original scope was:
  - `modeler_api.responses` gains `Envelope[T]`, `Meta` and `ErrorItem`; `envelope()` is unchanged.
  - View models go in `modeler_api/views/{brief,requirements}.py`. The routes of `brief_api` and `requirements_api`
    declare `response_model=Envelope[...]`.
  - Models use `extra="forbid"`, so an undeclared key fails loudly instead of being dropped. Numbers are typed
    `int | float`, so no value is coerced.
  - Nested artifact content stays `dict[str, Any]` until 6e gives it a model.
  - The OpenAPI snapshot gains response schemas only (an API contract change, recorded in the CHANGELOG).
- **6c — done** (P2: the 12 routes of `evidence_api`; P3: the 8 JSON routes of `client_api`):
  - `views/evidence.py` and `views/client_data.py`.
  - The merged answers are one model each, built by inheritance:
    - `EvidenceChoice` and `EvidenceCorrection` (the page plus `rejected` / `corrected`);
    - `ClientUpload` and `ReleaseProposal`;
    - `MapReading` (preview, datasets and page). Where the preview and the page both name `dissolution`, the page's
      wins, as today.
  - An answer that is a stored artifact's content (an evidence item, a dataset) is `Envelope[StoredContent]` (a
    `dict[str, Any]`) until 6e gives the kind a model.
  - New tests reach the 4 routes no test had reached: `evidence:research`, `access-requests/{id}:fulfil`,
    `evidence:approve` (its success path) and `client-data/{id}:triage`.
  - The OpenAPI snapshot: 20 operations gain their 2xx schema, and 34 schemas are added. Nothing else changed.

  The original scope was: **P2 `evidence_api` and P3 `client_api`.** The merged map response is one model, built by inheritance from the
  preview, `datasets` and the page view.
- **6d — done:**
  - P4: the 6 routes of `inputs_api`;
  - the 9 routes of `project_api`;
  - the 5 escalation routes, which have no envelope (`answers_without_envelope`).

  The models are in `views/inputs.py`, `views/project.py` and `views/escalations.py`. `[response] untyped` is empty;
  it stays, so a new route cannot answer untyped. Along the way:
  - The typing found a test fake of the runner's `resolve` that answered only `{"status": …}`. The real runner always
    sends `campaign_id`, `stage` and `action`, so the fake now answers as the runner does.
  - A new test reaches `inputs:propose-identity`.
  - The OpenAPI snapshot: 20 operations gain their 2xx schema, and 27 schemas are added. Nothing else changed.

  The original scope was: **P4 `inputs_api`, `project_api` and the escalation routes.** The escalation routes are typed as they are, with
  no envelope. `[response] untyped` ends empty.
- **6e — done.** Every kind is written by its owner only:
  - **brief:** `brief_ops.save_brief` takes over `brief_api`'s five commits. Each keeps the current provenance unless
    the documents are named anew, as before.
  - **cpf/published:** `inputs.record_publication`, with a `Publication` content model. `inputs.publication` serves
    the page.
  - **map:** the new `modeler_project.map_artifact` holds `MapArtifact`, `MapSignature`, `latest_map`, `signed_map`
    and `record_signed_map`. `plan_api` (sign, `_signed_map`, the page's MAP block) and `blinding.map_signed` read
    through it.
  - Round-trip tests: the MAP versions written by `plan:sign` and the hand-off record keep the keys the routers wrote
    before, and read back unchanged. An unsigned MAP gains no null keys.
  - The writer exceptions are gone (3 → 0). Raw reads: `plan_api` 10 → 3, `blinding` 4 → 3; 48 → 40 overall.

  The CPF `main` content model is left to 6f: `inputs` already owns it, and the readers outside go through accessors
  there. The original scope was:
  - **brief:** `modeler_project.brief_ops.save_brief(...)` takes over `brief_api`'s commits.
  - **cpf:** `modeler_project.inputs` owns all three ids, with content models for `main` (`{cpf, assembly}`), `choices`
    (`InputChoices`) and `published`. The hand-off record moves out of `inputs_api.publish`.
  - **map:** a new `modeler_project.map_artifact` holds a `MapArtifact` content model (the MAP, `map_sha256`, the
    campaign and the signature). Its accessors `latest_map` and `map_signature` serve `plan_api`, `blinding` and
    `doctor`, and it takes over `plan_api`'s commit. MAP generation (`pbpk_domain.campaign.map`, locked) is untouched.
  - **Stored JSON stays byte-identical,** because the audit chain hashes content. Each content model is tested
    `to_content(from_content(c)) == c` on content produced by today's code.
- **6f — raw reads go through the owners,** module by module, largest first:
  - `plan_api` 10;
  - `evidence_agent` and `proposal_intake` 7 each, through the document library's metadata;
  - `brief_api` 5, and `client_api` and `blinding` 4 each;
  - then the rest.

  Each PR lowers the recorded counts, and the section goes at zero.

**Not in phase 6:**
- renaming kinds, ids or stored keys (that needs a versioned migration);
- SME-governed content;
- the web client (phase 7);
- the engine port.

## Verification (every PR)
- `make test` shows only the known environment failures. `make lint`, and the web typecheck and build, pass.
- The ratchets pass with no stale entry, and the locked hash of `boundaries.toml` is refreshed.
- **6b–6d:** every P0–P4 response recorded from `services/api/tests` before and after the change is equal, except
  `meta`. The OpenAPI snapshot diff adds response schemas only.
- **6e:** the content round-trip tests pass, and the audit-chain verification passes on a store written before the
  change.
- `deploy/proof/run_t56.py` and the e2e specs pass unchanged.
