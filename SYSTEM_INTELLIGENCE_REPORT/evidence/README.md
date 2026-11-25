# Evidence notes

Working notes from the investigation, one per slice, each with `file:line` citations and VERIFIED / INFERRED labels.
The numbered reports (`../00_…` to `../13_…`) consolidate them; when a report and a note differ, the report wins
(the lead investigator re-checked the high-impact claims in code and corrected where needed).

| File | Slice | Written by |
|---|---|---|
| `G_orchestration.md` | Campaign spine: LocalExecutor, Temporal workflows, activities, memo, ledger, feedback, SJ, Postgres schema | lead investigator |
| `A_engine.md` | Engine plane: `run_job.R`, `run_pi.R`, runner, catalog, golden/CI, image, fixtures | sub-investigator |
| `B_science.md` | Domain logic: acceptance, NCA, VPC, diagnostics, fit spec, multistart, identifiability, round build, S6, VBE, model systems, builder, rulesets | sub-investigator |
| `C_package.md` | S7 and compliance: bundle, reproducibility gate, MAR, M15 table, signatures, audit chain, validation pack | sub-investigator |
| `D_api_web.md` | API endpoints, web pages, roles × actions, step-up sequence | sub-investigator |
| `E_quality.md` | Tests (run in this container), CI, guardrails, locked files, LocalExecutor vs Temporal parity, quality | sub-investigator |
| `F_docs_deploy.md` | Deployment (intended vs actual), configuration names, timeline of real PK-Sim evidence, stale docs | sub-investigator |

Line numbers refer to commit `1dbda7f`. Nothing in these notes was produced by running PK-Sim; the only execution was
the Python test suite and ruff (see `E_quality.md` §3).
