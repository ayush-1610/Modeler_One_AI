# Modeler One

An enterprise web platform that automates PBPK modeling and simulation on the open-source
[Open Systems Pharmacology Suite](https://www.open-systems-pharmacology.org/) (PK-Sim, MoBi), from
question of interest to a signed ICH M15 assessment table and a reviewer-reproducible submission package.

- [docs/CONTINUATION_PACKAGE.md](docs/CONTINUATION_PACKAGE.md) — 30-second state, finalized decisions, ordered
  implementation tasks with dependencies (start here when implementing)
- [docs/ENGINEERING_PLAN.md](docs/ENGINEERING_PLAN.md) — architecture, components, data model, API contracts, security,
  infrastructure, observability, edge cases, dependencies and fallbacks, testing, phased delivery
- [docs/PBPK_MODELING_WORKFLOW.md](docs/PBPK_MODELING_WORKFLOW.md) — MS-01, the automated model-development loop:
  parameter framework, data split, stages S0–S7, diagnostics, decision trees
- [docs/WORKFLOW_AND_AUTOMATION.md](docs/WORKFLOW_AND_AUTOMATION.md) — plain-English walkthrough, verified engine
  results, server sizing
- [docs/ARCHITECTURE_PACK.md](docs/ARCHITECTURE_PACK.md) — domain map, feature catalog, agents, validation strategy,
  open questions (v0.2)

## Repository layout

| Path | What it is |
|---|---|
| `packages/pbpk-domain` | Deterministic domain logic: PK-Sim snapshot models, builder, reference validation and parameter transfer; evaluation metrics; acceptance criteria by M15 risk; fitting planner and fit assessment; static DDI screening; virtual BE statistics; M15 table rules |
| `packages/data-intake` | Client data intake: write-once raw vault, spreadsheet grids with cell references, mapping recipes, validation, conversion to PK-Sim observed data |
| `packages/run-contracts` | Payloads exchanged between API, workflows and engine workers |
| `services/api` | FastAPI service, hash-chained audit trail, Part 11 signatures, Postgres schema with row-level security |
| `services/orchestrator` | Temporal workflows: simulation runs, population fan-out, fitting rounds with a deadline, review gates |
| `services/engine-worker` | Engine container and scripts: `r/run_job.R`, `r/run_pi.R` (one fitting start), `r/benchmark.R`, `golden/` engine checks, `scripts/ubuntu_engine_check.sh` |
| `services/agents` | Claude agents: data mapping, parameter curation, literature research over MCP servers, with deterministic citation checks |
| `templates/analysis` | Versioned analysis templates per PBPK application |
| `apps/web` | Next.js front end starters |

## Quick start

```bash
make sync     # uv workspace install (Python 3.12)
make test     # all Python tests
make api      # http://localhost:8000/docs
```

Engine on a compute server (Ubuntu 24.04; installs into the given directory and runs benchmark, golden round trip and
fitting smoke test):

```bash
bash services/engine-worker/scripts/ubuntu_engine_check.sh /data/modeler-engine
```

## Status (2026-09-15)

Verified by running: the engine on the **project server** (Intel Xeon Silver 4510, 48 logical cores) — golden round
trip, fitting smoke test and benchmark all pass (single run 0.506 s, 47-core batch 0.00555 s/run, PI 0.36 s/eval; the
1-hour campaign budget is met with room to spare); the Linux engine image passes the same golden round trip and fitting
smoke test; OSP parameter identification through the platform's fitting job script; lossless parsing of real OSP
snapshots; messy-Excel intake to PK-Sim observed data.

Done in code with tests (122 Python tests, lint clean):
- **T-01** engine verified on the server (see `docs/WORKFLOW_AND_AUTOMATION.md`).
- **T-02** engine catalog harvest — `services/engine-worker/r/harvest_catalog.R` (+ fetch/run scripts), Python loader
  `pbpk_domain.catalog`. The authoritative catalog `services/engine-worker/golden/catalog.json` was harvested on the
  Linux engine: all four OSP reference models (Dapagliflozin/Midazolam/Itraconazole/Rifampicin) plus the platform's own
  example load in the engine (`roundtrip_ok=true`), and the `{molecule}-{data_source}` process-selection convention is
  confirmed. Committed with `golden/fixtures/*.json`; CI pins its invariants (`tests/test_engine_catalog.py`).
- **T-03** CPF layer — `pbpk_domain.cpf` (versioned parameter document, S0 completeness gate, catalog binding with
  `NO_ENGINE_BINDING`, `SnapshotBuilder.from_cpf` snapshot regeneration); JSON Schema at
  `packages/pbpk-domain/schemas/cpf.schema.json`.
- **T-04** study classification and internal/external split — `pbpk_domain.campaign.split` (MS-01 §3).

Regenerate the engine catalog on a server (after `ubuntu_engine_check.sh` has installed the engine there) when the
engine image changes:

```bash
bash services/engine-worker/scripts/harvest_catalog.sh ~/modeler-engine
```

Not yet verified: `from_cpf` snapshots loading in the engine on Linux (run the harvest/golden on the server), Temporal
workflows against a live server, persistence, authentication, live MCP servers and Claude calls, the web app build.
Items marked **[VERIFY]** in the architecture pack and **[SME]** in MS-01 need SME, QA or legal sign-off.

PK-Sim®, MoBi® and the OSP Suite are open-source software under GPLv2 and are not part of this repository's license;
see architecture pack §5.13.
