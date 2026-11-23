# Unknowns (Phase 0)

What was searched for and not found, or could not be checked from this cloud session.

| ID | Unknown | Searched | Where | Status / how to resolve |
|---|---|---|---|---|
| U-01 | Git history before 2026-11-11 | `git log`, `git rev-parse --is-shallow-repository` (true) | this clone | Shallow clone (149 commits). `CHANGELOG.md` covers 2026-09-16 onward. `git fetch --unshallow` would recover it; not needed for Gate 1 |
| U-02 | Other Claude Code conversations (parallel sessions) | Not accessible to this session | — | Reconstructed only from `CHANGELOG.md` session table, plans and branch commits. Two commits on this branch not on `main` (`445fb51`, `cf3f6ec`) come from such a session |
| U-03 | What runs on the server now (deployed commit, Keycloak live or DEV sign-in, real users, data volume) | `deploy/server/*`, CONTINUATION §4 | repo | Server `adt-server` is on the owner's LAN; not reachable from here. CONTINUATION says the Inputs redesign was "not yet deployed" (2026-11-19) |
| U-04 | Deployment and execution logs | `deploy/`, repo for `*.log` | repo | None in the repository (logs live on the server: `MODELER_LOGS`). Not accessible |
| U-05 | Real user count, roles in use, companies | admin overview needs a live `modeler-admin` session | server | Owner to share, or read `/admin` on the server |
| U-06 | Actual time PK-Sim runs and fits take on the server | CONTINUATION, `docs/WORKFLOW_AND_AUTOMATION.md` §6 | repo | Benchmarks recorded in docs; not re-measured (no PK-Sim in this container) |
| U-07 | Python dependency bloat | `pyproject.toml`, `uv.lock` | repo | Not audited this phase (needs an import scan per package against declared deps) |
| U-08 | Unused TypeScript exports | no ts-prune/knip installed | `apps/web/lib` | Not installed by rule (no new dependencies). File-level orphans checked: none |
| U-09 | Full `make test` and `make lint` results today | — | — | Not run (long); last recorded 3,188 passed / 15 baseline failures (CONTINUATION §4.0c). e2e subset run: 35/35 |
| U-10 | Persona research (who uses which page, how often) | docs, plans | repo | No analytics or interview records found. Personas in the audit are inferred from plans and roles |
| U-11 | Brand assets beyond the logo (brand guide, approved palette file) | `app/icon.svg`, `Nav.tsx` `Logo`, plan 2026-11-21 §10 | repo | The palette is described in `globals.css` comments and plan §10; the "kick-off deck" it cites is not in the repo |
| U-12 | The Claude Design "Modeler One App" mockup source | plan 2026-11-06 §1 | repo | Not in the repo (claude.ai canvas). Its review is in the plan |
| U-13 | Whether `escalation:decide`, `feedback:decide`, `client-review:edit`, `map:generate` have non-web clients (scripts, the owner's tooling) | `apps/web`, `deploy/`, `services/` | repo | None found in the repo; outside clients unknown |
| U-14 | Design skills for AWS-console patterns | session skill list | environment | No AWS-specific design skill is installed. Available and relevant: `design:design-system`, `design:accessibility-review`, `design:design-critique`, `design:ux-copy`, `artifact-design`. Nothing installed |
| U-15 | Figma or other design files | Figma connector | environment | The Figma connector failed to connect (proxy refusal); not needed for Gate 1 |
