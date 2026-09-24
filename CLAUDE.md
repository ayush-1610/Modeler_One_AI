# Modeler One — working rules

PBPK modelling platform on the OSP engine (PK-Sim). Goal: a regulator-reviewable model package (ICH M15, 21 CFR
Part 11), with simulations and parameter identification finishing within an hour on our servers.

## Start here, every session
1. `docs/CONTINUATION_PACKAGE.md` — where things stand. §4.1 is the S0–S7 pipeline-coverage table.
2. `CHANGELOG.md` — what changed, why, and in which commit.
3. The active plan in `docs/plans/` (newest date). Follow it; if you deviate, say so and record why.

## Record every change — not optional
- **Every commit that changes behaviour adds a `CHANGELOG.md` entry in the same commit**: what changed, why, and its
  impact. Science changes (model building, fitting, evaluation, acceptance, rulesets) always get an entry, however
  small. Entries go under `[Unreleased]`; the hash is added when that section is dated.
- **A stage changes status → update the coverage table in `docs/CONTINUATION_PACKAGE.md` §4.1 in the same commit.**
- **A new session or AI model takes over → add a row to the table at the end of `CHANGELOG.md`.**
- Before the context runs out, bring §4 of the continuation doc up to date.

## Scientific ground rules
- **Never invent PK-Sim names, paths or units.** Harvest them from the engine or the OSP reference snapshots
  (`services/engine-worker/golden/`). The builder has silently produced wrong models before: a raw `ValueOrigin`
  label made PK-Sim drop the simulation; an unbound process parameter left the model with no clearance.
- **A result counts only if it ran on real PK-Sim.** `deploy/dev/stub_engine.py` and `deploy/dev/analytical_engine.py`
  are software fixtures for tests — never present their numbers as simulation results or PBPK evidence.
- **SME-governed content** — `packages/pbpk-domain/src/pbpk_domain/rulesets/*.yaml`, acceptance criteria, MS-01 —
  changes only with the user's explicit approval, stays marked `UNVERIFIED`, and bumps the ruleset version.
- The CPF (Compound Parameter Framework) is the system of record; every simulation is regenerated from it.
- PK-Sim snapshots run only on **Linux** (macOS: unsupported / segfaults). Engine hosts: the server, or the Mac's
  Docker Desktop with the image from `services/engine-worker/Dockerfile`.

## Engineering conventions
- `make test` (pytest), `make lint` (ruff, line 130, Python 3.12), `npm --prefix apps/web run typecheck` and `build`.
  Keep all of them green before committing.
- Tag tests with `@pytest.mark.req("T-xx")` for the trace matrix.
- Domain models are frozen pydantic. Match the surrounding code's style and comment density.
- Server: `ssh adt-server` (user `adt-ayush`, no sudo). `~/Modeler_One_AI` there is an **rsync target, not a git
  checkout**. Scripts in `deploy/server/`.
- Security: `DevVerifier` / `MODELER_DEV_AUTH` is DEV ONLY. Never type, store or transmit the user's passwords;
  signatures come from the token's step-up, never a password in a request.
