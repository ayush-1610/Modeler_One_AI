# Phase 5: services out of routers, `modeler_api.deps`, deterministic helpers out of the agents package

Status: **5a done** (this plan's first PR). 5b–5d next, each one PR to `main`, behaviour identical.
Sources: `docs/ARCHITECTURE_BOUNDARIES.md` (rules B3/B4, couplings C3, C4, C9, §6 phase 5); exceptions in
`tests/architecture/boundaries.toml`, which only shrinks.

## Why
The API's routers did three things a router should not:
- they imported each other for shared dependencies (C3);
- they ran business logic: agent jobs, data-plan derivation, CPF views (C4);
- they reached into the agents package for deterministic helpers that are not agents at all (C9).

A change to one router broke another's tests, and the agents package could not be replaced without touching the HTTP
layer.

## Steps
- **5a — done.** `modeler_api.deps` holds what the routers share:
  - roles (`Reader`, `Writer`, `MiddLead`);
  - the project store (`get_project_store`, `StoreDep`);
  - `workspace_for`, `parse_kind`, `version_view`, `impact_view`;
  - the blinding views (`blinded_studies`, `redact`, `hidden_paths`, `blinding_view`, `project_record`, `model_risk`).

  `agents_status` moved to the agents seam `modeler_api.agent_jobs`. `project_api` re-exports `get_project_store`, so
  the tests' dependency overrides still find it. Router exceptions went from 14 to 4, and 35 → 25 overall. The OpenAPI
  snapshot is unchanged.
- **5b — agent jobs into `modeler_api.agent_jobs`.** The jobs are A1 `run_extraction`, A3 triage, A2 research and A4
  observed data, and A5 planning, plus the agent run records (`run_store`). Each router calls a job function in the
  seam. This removes the 16 seam exceptions apart from the deterministic ones handled in 5c.
- **5c — deterministic helpers out of the agents package:**
  - `citations` (quote check) moves to `modeler_project`;
  - `data_mapping` (recipe review) moves to `modeler_intake`;
  - the recipe constant keys get one owner (C9: `recipe.py`, `apply.py`, `data_mapping.ConstantKey`, `sheet_form.py`).

  The agents package keeps only what calls a model. This removes the `declared` agents → `pbpk_domain` exception if
  nothing else needs it.
- **5d — services out of routers:**
  - data-plan derivation (`requirements_api`) moves to a `modeler_project` service;
  - `_observed_from_studies` (`write_api`) moves to a service;
  - the project CPF view (`read_api`) moves to a service;
  - the `StudyUpload` request model gets its own module. Phase 6 types the responses.

  This removes the last 4 router exceptions.

## Verification (every PR)
- The boundary ratchet runs with the removed exceptions gone, and no stale entry remains.
- The OpenAPI snapshot is unchanged.
- `make test` shows only the known environment failures, and `make lint` passes. CI on the PR.
- `deploy/proof/run_t56.py` and the e2e specs pass unchanged through phase 5.
