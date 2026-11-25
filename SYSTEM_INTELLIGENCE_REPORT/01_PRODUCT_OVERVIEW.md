# 01 · Product overview (post-MAP scope)

## 1. In plain language

A drug company wants to know how much of a drug reaches the blood, and how fast it leaves, under conditions it has not
tested (another dose, a new tablet, a meal, a population). A PBPK model answers that by simulating the body as organs
connected by blood flow. Building such a model by hand takes an expert weeks: choose parameters, compare simulations
with clinical data, adjust, repeat, then write it all up so a regulator can check it.

Modeler One does the repetitive part automatically and keeps every step on the record. Once a scientist has gathered the
inputs and **signed the plan** (the MAP), the platform:

1. builds the model in PK-Sim from the compound's parameter record (the CPF);
2. compares it with intravenous data, then oral data, then tablet and food data, adjusting parameters only where the
   signed plan allows;
3. stops and asks a person whenever it cannot meet the plan's criteria, and records that person's signed decision;
4. tests the final model on studies it never saw during fitting;
5. measures which parameters matter most and how uncertain the predictions are;
6. writes the report and a package a reviewer can re-run, and releases the package only if a fresh re-run reproduces
   every number.

## 2. In technical language

A FastAPI + Next.js application whose post-MAP core is a stage machine (MS-01: S0, S1, S2, S3, SM, SJ, S4, S5, S6, S7)
executed in-process by `LocalExecutor` against an engine port. The engine is `Rscript run_job.R` (ospsuite 12.4.4,
PK-Sim 12.3, .NET 8, Linux only) run as an isolated subprocess per job. Snapshots are regenerated deterministically from
a versioned CPF; parameter identification uses `ospsuite.parameteridentification` 2.2.0 (BOBYQA, Hessian CI) with a
Latin-hypercube multistart sized to the stage's time budget. Verdicts use tiered fold-error criteria (ICH M15 model
risk) frozen into the signed MAP; failures are mapped to permitted actions by a deterministic YAML ruleset. Human
touchpoints are Part 11 signatures with OIDC step-up (Keycloak, loa2). S7 produces a hash-manifested bundle, a MAR in
Markdown/DOCX/PDF-A-2b and a zip gated by a 1e-6 re-run.

## 3. Why it exists

- **Regulatory goal:** a regulator-reviewable model package under ICH M15 and 21 CFR Part 11 (CLAUDE.md).
- **Time goal:** simulations and parameter identification within one hour on the project's servers (CLAUDE.md). The
  benchmark (0.506 s per simulation, 47-core batch 0.00555 s per run) supports it for simple compounds; the signed
  default budget is 8 h and one model-system refit took 3.3 h (see `11`).
- **Reproducibility goal:** every simulation regenerated from the CPF, every number in the report traceable, the
  package re-runnable.

## 4. Users and roles

| User | What they do after the MAP | Realm role |
|---|---|---|
| Modeller / project owner | starts the campaign, watches it, decides escalations, downloads the package | `modeler-curator` (or reviewer) + project owner |
| MIDD lead / reviewer | signs the MAP and MAP deviations, decides escalations, signs the S4/S5 evaluation | `modeler-reviewer` |
| QA | reads every project of the company; the planned "QA release" of the bundle is not built | `modeler-qa` |
| Viewer | reads campaigns and downloads | `modeler-viewer` |
| Administrator | engine status, members, settings | `modeler-admin` |
| SME (outside the tool) | signs rulesets, acceptance criteria and MS-01 amendments | - (`docs/SME_SIGNOFF.md`) |

## 5. Primary use cases (post-MAP)

1. **Develop and qualify a single-compound PBPK model** from IV, oral solution, tablet, multiple-dose and fed studies.
2. **Develop a model system** (parent, metabolites, enantiomers) where each analyte has its own gate (SM stage,
   UNVERIFIED).
3. **Validate on blinded external studies** with fasted and fed judged separately, and handle failures through signed
   feedback cycles.
4. **Characterise the validated model:** local sensitivity and parameter-uncertainty prediction intervals.
5. **Virtual bioequivalence** of a TEST vs reference formulation (template `vbe-crossover`, DRAFT).
6. **Produce the submission package:** MAR, M15 credibility table, data bundle, PK-Sim projects, `rerun_all.R`.

## 6. Secondary use cases

- Reference checks: import a published OSP library model and run it as is or refit (`deploy/reference/`).
- End-to-end proof for qualification (T-56 kit, `deploy/proof/`), IQ/PQ evidence (`deploy/server/qualify.sh`).

## 7. Capabilities (what exists today)

| Capability | State |
|---|---|
| S0 readiness (completeness, unplaceable pathways, expression profiles) | implemented |
| S1–S3 round loop with diagnosis and fitting | implemented; only `fit` / `fix_and_refit` actions execute |
| VPC gate at S1/S2 (100 individuals, ≥ 80 % in 5–95 %) | implemented |
| No-regression gate and SJ joint refinement | implemented (SJ UNVERIFIED) |
| S4 internal / S5 external validation, fasted vs fed | implemented |
| S5 feedback cycles (limitation, learn, new evidence, stop) | implemented (UNVERIFIED) |
| S6 sensitivity (±10 %), uncertainty (200 independent draws), VBE | implemented; EMA worst-case ranges and correlated sampling missing |
| S7 bundle, 1e-6 re-run, `.pksim5`, MAR (MD/DOCX/PDF-A), zip gate | implemented in the local path |
| Signed decisions with OIDC step-up, hash-chained audit, Postgres Part 11 copy | implemented |
| Live monitor (polling), change ledger, influence map | implemented |
| Temporal / MinIO distributed execution | built, partial (no SJ/S6/S7), not deployed |

## 8. What makes it distinctive

- **The CPF is the system of record:** fitted values are written back into a new CPF version with provenance and CI;
  simulations are never edited in place (`fit_spec.apply_fit_estimates`).
- **The signed plan binds the run:** acceptance criteria, internal target, fit bounds, stage budgets and round limits
  are read from the signed MAP at run time, not from today's ruleset files (D-35, D-36).
- **AI never decides science:** diagnostics are a deterministic ruleset; the strategist may only pick among permitted
  actions (and today picks the first). Agents are used before the MAP (intake, literature), not in the campaign.
- **Fixture labelling:** the stub and analytical engines are labelled "Not a PBPK result" on the campaign page.

## 9. Limitations (post-MAP)

- No clinical-data campaign has yet passed S1 without a person's decision (S1 IV-Cmax criterion awaiting the SME).
- All governing rulesets are UNVERIFIED; reports built today rest on owner-approved, not SME-approved, criteria.
- No signature on the MAR, package or final CPF; no QA release; no audit events for campaign start, verdicts or
  downloads.
- Single node only; campaigns lost on API restart; no cancel; polling, no live stream.
- S3 fed sub-loop, DDI, paediatric, special-population and FIH applications are not runnable.
- macOS cannot run PK-Sim snapshots; the engine host must be Linux (server, or Docker on the Mac).

## 10. Tasks it does not support

- Editing a running campaign, stopping it, or resuming it after a crash.
- Fitting with any optimiser other than BOBYQA; method branches (partition coefficients), switching elimination to
  Michaelis-Menten, or switching algorithm on multiple optima.
- Population simulations beyond the VPC and VBE tasks; PD or MoBi models.
- Running on an S3/MinIO object store (S7 and downloads need `file://`).
- Producing a signed, QA-released submission package.
