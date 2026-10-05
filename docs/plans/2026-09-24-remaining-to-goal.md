# What remains to the goal, and how long it takes (2026-09-24)

Status: **proposal** — the order and estimates are mine; items marked *owner* or *SME* need a decision or sign-off.
Builds on `2026-09-24-s0-s7-real-pbpk.md` (its Definition of done) and `2026-09-24-multi-compound.md`.

## The goal, in two steps

1. **Plan exit (the S0–S7 plan's Definition of done).** A user creates a project, loads a compound and gets, on real
   PK-Sim, a fitted model with internal and external validation (fasted and fed separate), VPC, sensitivity,
   prediction intervals, a signed MAR (DOCX, PDF/A) and a package that re-runs identically — shown on Dapagliflozin
   and Rifampicin against their published clinical data.
2. **Regulator-reviewable product (CLAUDE.md goal).** The same on a Part 11 platform (real identity, signatures,
   audit, database), with SME-signed rulesets, application templates (DDI, paediatric) and a validation pack.

## Where it stands

- Engine, builder and importer: 15 OSP library models vendored and S0-ready (22 of 24 importable in the library);
  model systems (parent, enantiomers, metabolites, sums) for Verapamil, Omeprazole, Dabigatran, Itraconazole.
  Round trips on PK-Sim before today's fixes: Dapagliflozin, Rifampicin, Midazolam, Digoxin all parameters identical;
  most curves within 1e-6 of the peak, the rest labelled or since fixed.
- Pipeline: S0, S1, S2, S4, S5 done on PK-Sim; S3, S6, S7 partial (`CONTINUATION_PACKAGE.md` §4.1).
- **Not yet confirmed on PK-Sim:** everything since commit 8bf41e6 (IV bolus, per-route values, expression profiles,
  phased regimens, alternatives, meals). GitHub Actions stopped starting jobs at 16:15 UTC (account limit).

## Remaining work, in order

Estimates are in working sessions like today's (one session ≈ one working day of focused work plus the engine
runs it waits on). Ranges reflect what the engine runs may uncover.

| # | Work | Why | Estimate | Needs |
|---|---|---|---|---|
| 0 | Unblock verification: restore Actions minutes, **or** run `deploy/reference/run_all.sh` on the server | nothing since 8bf41e6 is proven on PK-Sim | 0 (owner) + 1 h server run | *owner*: billing, or server access |
| 1 | Confirm round trips of all 15 models and the 4 systems; fix what they show; harvest the observer column naming for system campaigns | the reference proof (T-10 acceptance: 1e-6) | 1–2 | — |
| 2 | Clinical-data proof for Dapagliflozin and Rifampicin: as-is and refit campaigns S0→S7, GMFE vs the published model | plan exit criterion | 2–3 | may need rule decisions (*owner*, rulesets are SME-governed) |
| 3 | S3 fed sub-loop: fit the fed alternative (solubility / permeability) against fed studies; dissolution data | S3 is partial; the alternatives now exist to hold a fed value | 1–2 | *owner/SME*: MS-01 amendment (which fed parameters S3 may fit) |
| 4 | S7 completion: MAR signature (step-up), M15 influence / consequence table, package wiring checked end to end | plan exit criterion | 1–2 | — |
| 5 | UI for what the importer now carries: phases, meals, alternatives shown in intake and the MAP view; intake and review-inbox e2e flows | a user can see and check what is simulated | 2 | UI review (*owner*) |
| — | **Plan exit reached** | | **≈ 7–11 sessions** | |
| 6 | Multi-compound phase 2: fit metabolite / enantiomer parameters, gates for their analytes | Itraconazole, Verapamil, Dabigatran as full campaigns | 2–3 | *SME*: MS-01 amendment |
| 7 | Multi-compound phase 3: projects with several compounds in the UI and API (dose fractions, analyte per study) | systems usable by a user | 2 | UI review |
| 8 | Warfarin (racemic data, no compartment in the data) | last importable library gap | 0.5–1 | — |
| 9 | S6 application templates T-31: DDI (e.g. midazolam with itraconazole / rifampicin), paediatric; correlated sampling | the model's use, not only its fit | 3–4 | — |
| 10 | Part 11 platform: Temporal, Postgres (RLS, append-only audit), Keycloak (step-up signatures), object store deployed; DevVerifier removed; server disk (95 % full) | regulator-reviewable | 3–5 | *owner*: server resources |
| 11 | T-19 digitizer, T-21 agent evaluation sets, T-22 MCP servers, T-29 Helm / k3s | completeness of the product | 4–6 | — |
| 12 | SME sign-off of rulesets and acceptance criteria (T-30), validation pack, QA review | regulatory standing | owner / SME time | *SME / QA* |
| — | **Regulator-reviewable product** | | **≈ 22–34 sessions + SME time** | |

## What can be tried now

- The wizard offers 12 published OSP models with their real clinical data as starting points (plus the illustrative
  check). Deploy from the Mac (`git pull` on `main-1czavz`, `bash deploy/dev/deploy_to_server.sh`), then on the server
  `bash deploy/server/run_modeler.sh`; open `http://<server>:3000`. Locally on the Mac: Docker Desktop with the engine
  image, `MODELER_ENGINE_COMMAND="bash $PWD/deploy/dev/docker_engine.sh"`.
- Expect: S0 → S5 run on PK-Sim; S6 stops at the signature gate; S7 package after reproduction. Fed studies of
  models with fed alternatives, and metabolite / sum studies, are reported but not fitted (items 3 and 6).
- Reference checks on the server: `bash deploy/reference/run_all.sh roundtrip -j 8` (results under
  `reports/reference/<stamp>/summary.md`).

## Risks

- Engine runs keep uncovering import defects (every run so far has); item 1 may take the upper estimate.
- The Dapagliflozin / Rifampicin refits stalled before on non-identifiable clearance parameters (now escalated
  correctly); a pass may need an approved change of what S1 frees.
- SME availability decides items 3, 6 and 12.
