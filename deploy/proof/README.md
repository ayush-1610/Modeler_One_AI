# T-56 · End-to-end proof: Dapagliflozin from a mock proposal, P0 → P6 on real PK-Sim

Plan: `docs/plans/2026-09-25-project-startup-pipeline.md` §19 T-56 and Appendix A. Acceptance: **a reviewer can trace
every number in the MAR to its source.** The kit is `run_t56.py`; it drives the same API the web app uses.

## What goes in, and what it is

| Input | What it is | Origin recorded |
|---|---|---|
| `dapagliflozin/proposal.md` | a **mock** technical proposal (food effect of a 10 mg IR tablet); states no values | the project's proposal document |
| 42 parameter values | every parameter of the published OSP Dapagliflozin model (PK-Sim snapshot in `services/engine-worker/golden/fixtures/`), each citing the model and its ValueOrigin text | evidence, `OSP_LIBRARY` |
| 39 clinical datasets | the observed data the published model carries, each with its publication (PubMed link) and figure; the statistic (arithmetic / geometric mean) as the snapshot records it | datasets, `OSP_LIBRARY` |
| 1 "client" study | Kasichayanula 2011a, fed arm, delivered in the client-data template — **published data in a mock client delivery**, said so in the workbook README | dataset, `CLIENT` |

Not used, and why: no measured dissolution profile of the tablet is public, so none is invented; the data plan's release
item is answered from the literature (the published model's tablet Weibull) with that reason. Parameter values are the
published model's, entered by the manual path; an A2 literature search runs only with a provider key.

## Run it on the server (PK-Sim)

The API must run with the PK-Sim engine (`deploy/server/run_modeler.sh`; `MODELER_ENGINE_COMMAND` names `run_job.R`).
`--token` is **your own** access token (on the single-node dev deployment the DEV-ONLY verifier accepts `dev`). No
password is ever typed into or stored by the kit.

```bash
cd ~/Modeler_One_AI
uv run python deploy/proof/run_t56.py prepare --api http://localhost:8000 --token dev --out ~/modeler-data/t56
#   P0–P3: project from the mock proposal, brief filled from it, data plan, values / datasets / client file proposed.
#   Review them on /projects/<id> (Evidence, Client data). Nothing is accepted yet.

uv run python deploy/proof/run_t56.py accept --api http://localhost:8000 --token dev --out ~/modeler-data/t56 \
    --project <id> --as "Your Name"
#   Your decisions, recorded under your name: every proposed item accepted with its reason, P1–P4 approved, the P5
#   plan drafted from the MS-01 default. It stops before the MAP signature.

#   In the web app: /projects/<id>/plan — review the placements and fits (any move or freed parameter is yours, with
#   its reason), then "Approve and Sign" (MIDD lead, step-up).

uv run python deploy/proof/run_t56.py start --api http://localhost:8000 --token dev --project <id>
uv run python deploy/proof/run_t56.py watch --api http://localhost:8000 --token dev --campaign <cid>
#   Escalations, the S4/S5 signature and any S5 feedback decision are yours, in the review inbox.

uv run python deploy/proof/run_t56.py trace --api http://localhost:8000 --token dev --out ~/modeler-data/t56 \
    --project <id> --campaign <cid>
#   Writes trace.md: every CPF parameter → evidence → source; every judged study → dataset → publication; the
#   campaign's parameter changes (ledger); the MAR's evidence index. Exit code 0 only when nothing is broken.
```

## What it shows, and what it does not

- With no fit chosen on the canvas, the campaign judges the published model's values through S1 → S7 on the real
  clinical data (as `deploy/reference/run_reference.py campaign --mode as-is` does, but entered through P0–P5 with
  every value cited). Freeing parameters on D1/D2 turns it into a development run; that choice is the reviewer's.
- A run on `deploy/dev/stub_engine.py` checks the software path only; the trace says "Not a PBPK result" for it.
  `services/api/tests/test_t56_kit.py` runs the kit that way.
