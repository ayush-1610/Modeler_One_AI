# Phase 5: services out of routers, `modeler_api.deps`, deterministic helpers out of the agents package

Status: **done** (5a–5d, one PR each, behaviour identical). Boundary exceptions 35 → 4; none of the router or seam kind left.
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
- **5b — done.** Every router reaches the agents through `modeler_api.agent_jobs`:
  - the configured model: `chat_model`, `require_chat_model` (the 409 an agent endpoint returns when agents are off or
    misconfigured, with the router's own "do it by hand" message), `agents_status`;
  - the run records: `AgentRun` (started, each step logged, finished once), `project_runs`, `run_record`, `run_steps`;
  - one entry point per agent: A1 `proposal_intake`, A2/A3 `literature_research`, A4 `sheet_triage`, A5 `planning`.

  The jobs stay in their routers (`run_extraction`, `run_triage_job`, `run_research_job`, `run_planning_job`): their
  bodies read and write the project through router helpers that 5d moves out. Run ids, actors, step sequence, summaries
  and error messages are unchanged; the run detail still checks the run is the viewer's before reading its steps. Seam
  exceptions went from 16 to 2 (`citations`, `data_mapping`, which are 5c), and 25 → 11 overall.
- **5c — done.** Deterministic helpers left the agents package:
  - `citations` (the quote check) is now `modeler_intake.citations`. **Deviation from this plan, which said
    `modeler_project`:** the recipe review (L2, `modeler_intake`) needs `normalize_for_match`, and L2 cannot import L3.
    The quote check reads text only, so it sits with the readers that produce that text.
  - The deterministic half of `data_mapping` is now `modeler_intake.recipe_review`: the proposal models, `to_recipe`,
    `check_evidence` and `review_proposal`. `modeler_agents.data_mapping` keeps the prompt and `propose_mapping`, the
    part that calls a model. The proposal's JSON schema, which the model is given, is unchanged.
  - The recipe constant keys have one owner (C9): `recipe.ConstantKey`, `CONSTANT_KEYS` and `NUMERIC_CONSTANTS`. The
    review, `apply._const` and the recipe's schema text read them, and a test keeps the sheet form's keys inside them.
  - `planning_agent` and `data_mapping` still use `pbpk_domain` (`CPF`, `Issue`), so the agents package now declares
    it. That is a workspace package already installed through `modeler_intake`; no new third-party dependency, and
    `uv.lock` gains two lines. This removes the `declared` agents → `pbpk_domain` exception.

  Seam exceptions went from 2 to 0, and 11 → 8 overall. The tests moved with the code: `test_citations.py` and
  `test_recipe_review.py` in `data-intake`. The agents' `test_data_mapping.py` checks only what the agent does: it
  sends the sheets, asks for the proposal's schema, and passes the proposal to the review unchanged.
- **5d — done.** Services left the routers:
  - Data-plan derivation is now `modeler_project.data_plan.derive_data_plan`. With no brief it raises `NoBriefError`,
    which `requirements_api` turns into the same 404. `brief_api` calls the service on approval.
  - The study upload models (`ObservedProfile`, `StudyUpload`, `StudiesUpload`) and the observed PK per profile
    (`observed_from_studies`, formerly the private `write_api._observed_from_studies`) are now in `modeler_api.studies`.
    They are read by `write_api`, `inputs_api` (`inputs:publish`) and `plan_api` (`plan:sign`).
    `deploy/reference/run_reference.py` imports it from there; `run_t56.py` is unchanged.
  - The project CPF view is now `modeler_api.cpf_view.project_cpf_view`. `read_api` still re-exports it.

  Phase 6 types the responses. This removed the last 4 router exceptions; the OpenAPI snapshot is unchanged.

## Verification (every PR)
- The boundary ratchet runs with the removed exceptions gone, and no stale entry remains.
- The OpenAPI snapshot is unchanged.
- `make test` shows only the known environment failures, and `make lint` passes. CI on the PR.
- `deploy/proof/run_t56.py` and the e2e specs pass unchanged through phase 5.
