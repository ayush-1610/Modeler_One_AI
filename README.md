# Modeler One

An enterprise web platform that automates PBPK modeling and simulation on the open-source
[Open Systems Pharmacology Suite](https://www.open-systems-pharmacology.org/) (PK-Sim, MoBi), from
question of interest to a signed ICH M15 assessment table and a reviewer-reproducible submission package.

- [docs/CONTINUATION_PACKAGE.md](docs/CONTINUATION_PACKAGE.md) — 30-second state, S0–S7 pipeline coverage, finalized
  decisions, ordered implementation tasks (start here)
- [CHANGELOG.md](CHANGELOG.md) — every change, why it was made, and its commit
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

## Status

Where things stand — stage by stage — is in [docs/CONTINUATION_PACKAGE.md](docs/CONTINUATION_PACKAGE.md) §4, and every
change with its reason is in [CHANGELOG.md](CHANGELOG.md). Working rules for contributors (and AI sessions) are in
[CLAUDE.md](CLAUDE.md).

PK-Sim®, MoBi® and the OSP Suite are open-source software under GPLv2 and are not part of this repository's license;
see architecture pack §5.13.
