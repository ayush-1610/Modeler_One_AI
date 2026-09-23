# Modeler One — Session Handoff

## Project Snapshot
- Modeler One: enterprise PBPK modeling/sim platform on OSP Suite (PK-Sim), submission-grade (ICH M15, 21 CFR Part 11, GAMP 5).
- Priorities: **#1 FDA-reviewable model package**, **#2 sims+PI <1h on 3 servers** (PE <10%).
- Phase: MS-01 auto-loop done+engine-verified; priority-#1/#2 lanes complete; web app built + now on **live read-APIs**.

## Current Objective
- Web UI runs on live data. Just wired GET read-APIs (projects/compounds/CPF); verified end-to-end. Awaiting user: extend read-APIs to campaigns/escalations/proposals (so campaign monitor + review inbox go live) OR stop.

## Architecture & Conventions
- Repo `/Users/ayush/Projects/Modeler_One_AI`, git `main`. uv monorepo (Python 3.12): packages/{pbpk-domain,data-intake,run-contracts}, services/{api,orchestrator,engine-worker,agents}; apps/web (Next 15/React 19, App Router).
- Commands: `uv run pytest -q`; `uv run ruff check .` (line 130, py312); `uv sync --all-packages`; web `npm --prefix apps/web run {dev,build,typecheck}`.
- Tests: **393 pass, 13 Docker-skipped**. Trace matrix: `--trace-matrix reports/trace-matrix.md` (reports/ gitignored). Tag tests `@pytest.mark.req("T-xx")`.
- Conventions: NEVER invent engine names/paths — harvest from real engine/snapshots. pydantic frozen models. RLS on `app.tenant_id`. Migration list hardcoded in test_persistence.py. Commit trailer: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- Server: `ssh adt-server` (192.168.1.10, user adt-ayush); repo `~/Modeler_One_AI` (rsync target, NOT git); engine env recipe in [[osp-engine-facts-2026-09]]. NO docker on server or Mac.

## Decisions Log
- Web reads via `ReadStore` protocol + `FileReadStore` (file://) = seam for future Postgres §5 read tables.
- `DevVerifier` (env `MODELER_DEV_AUTH`, DEV-ONLY) accepts any bearer→fixed dev principal; lets UI skip Keycloak. Rejected: full OIDC in dev (no Keycloak running).
- UI fetches live w/ graceful fixture fallback + "sample data" banner. Rejected: hard dependency on API.
- `envelope` moved to responses.py to break main↔read_api import cycle.

## Failed Attempts / Lessons
- main↔read_api circular import (read_api imported main.envelope) → extract to responses.py.
- Engine: JSON whole-numbers → R int → .NET `Nullable<Double>` reject → coerce as.numeric/as.integer. ValueOrigin.Source must be enum (else sim silently dropped). Sensitivity needs a COMPOUND param (e.g. `{compound}|Lipophilicity`) or 0 rows.
- Plotly in grid collapsed → `minmax(0,1fr)` columns + post-render `Plotly.Plots.resize`.

## Modified Files (this session, all committed)
- Backend: read_api.py, responses.py, auth.py(DevVerifier), config.py(read_root/dev_auth), main.py, migration 0003_agents.sql, registration.py, run.py(agents); report/{mar,render,validation_pack}.py; reproducibility.py(+generate_rerun_script); run_job.R(pop/sens/batch), golden_tasks.R, ubuntu_engine_check.sh; .github/workflows/{ci,engine-image}.yml; conftest.py; docs/validation/requirements.yaml; deploy/dev/read-root/.
- Web: app/{page,projects/*,campaigns/*,review,intake} , components/{Nav,ui,EscalationDecision,ConcentrationTimePlot}, lib/{api,reads,fixtures}, globals.css, .claude/launch.json.

## Open Tasks (priority order)
1. Read-APIs for campaigns/rounds/escalations/proposals → wire campaign monitor + review inbox live.
2. Playwright flows (T-26 formal acceptance).
3. Agent: Postgres-backed RunStore + wire AgentRun into strategist/parameter_curation.
4. T-10 tail (particle/Table formulations, Populations, total/biliary/tubular CL — need reference model).
5. T-31 application templates (needs OSP DDI/pediatric ref models); T-32 IQ/PQ (needs T-29).
6. Infra: T-29 Helm/k3s/observability; T-22 MCP deploy. T-21 eval sets; T-19 digitizer.
7. object-store I/O beyond file://; T-17 escalation→token step-up.

## Immediate Next Steps
- If continuing UI-live: add GET campaigns/{id}, escalations, proposals to read_api.py (same ReadStore pattern), seed deploy/dev/read-root, point campaign+review pages at them.
- Two bg dev servers currently running: API :8000, web :3000.

## Blockers / Open Questions
- No live Keycloak (dev auth only); no Postgres/Docker locally (persistence tests skip). Real §5 read tables (projects/compounds/cpf_versions) not built — FileReadStore is the stand-in.

## Context References
- Entry: docs/CONTINUATION_PACKAGE.md (tasks T-01..T-32, deps). docs/ENGINEERING_PLAN.md §5/§7/§9. docs/PBPK_MODELING_WORKFLOW.md (MS-01 S0–S7).
- Memory: MEMORY.md index → project-docs-and-tasks (task tracker, session log), osp-engine-facts-2026-09 (engine facts+SSH+gotchas), project-priorities-fda-and-runtime, project-deployment-decisions.
- Session commits: bc5835a T-25, bca33e8 T-09, 01ff5fa T-24, c26c923 T-12, 5003e6f T-20, fe2cc69 T-23, 467335f T-32, 817c14d web, fdeaf91 web read-APIs.
- Run live stack: `MODELER_DEV_AUTH=1 MODELER_READ_ROOT=deploy/dev/read-root uv run uvicorn modeler_api.main:app --port 8000` + `MODELER_API_BASE=http://127.0.0.1:8000 MODELER_WEB_TOKEN=dev npm --prefix apps/web run dev`.

## New Session Kickoff Prompt
Resume Modeler One (PBPK/PK-Sim submission-grade platform). The MS-01 loop and priority-#1/#2 lanes are done and engine-verified; the Next.js web app is built and I just wired live GET read-APIs (projects/compounds/CPF via a ReadStore/FileReadStore seam + a DEV-only DevVerifier), verified end-to-end. Read memory (project-docs-and-tasks, osp-engine-facts-2026-09) and docs/CONTINUATION_PACKAGE.md first. Next: extend the read-APIs to campaigns/escalations/proposals so the campaign monitor and review inbox render live data, then Playwright flows — follow existing patterns (ReadStore protocol, deploy/dev/read-root seeds, fixture fallback) and keep the suite green + lint clean, committing with the standard Co-Authored-By trailer.
