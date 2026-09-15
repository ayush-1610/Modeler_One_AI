# How Modeler One Works: Workflow, Automation and Compute

**Version 0.2 · 2026-09-15** · Plain-English companion to [ARCHITECTURE_PACK.md](ARCHITECTURE_PACK.md).
This document explains how a PBPK project runs from question to FDA-ready package, what users provide, where humans
decide, and how the one-hour runtime target is met on the project's servers. Statements marked **verified** were
checked by running the real OSP engine or the test suite; **estimate** means not measured yet.

---

## 1. What has been verified so far

| Claim | Evidence |
|---|---|
| The OSP engine runs headless from R: ospsuite 12.4.4, parameter identification 2.2.0, PK-Sim 12.3.173 inside, .NET 8 runtime | Installed and run on macOS (arm64) on 2026-09-15 |
| A simulation of the OSP Aciclovir example takes ~0.2 s; batch runs take 0.17 s per run on 1 core and 0.0076 s per run on 9 cores | `services/engine-worker/r/benchmark.R` |
| OSP parameter identification works end to end: BOBYQA, 2 parameters, 2 simulations: 41 evaluations in 6.9 s with SD, CV and 95% CI | `benchmark.R` |
| The platform's fitting job script works: spec file -> OSP PI package -> result file with estimate, CI, convergence | `golden/pi_smoke.R` + `r/run_pi.R`: 20 evaluations, 2.4 s, converged |
| The snapshot builder reproduces real PK-Sim structure; a real OSP snapshot (Dapagliflozin) parses and re-exports without losing anything | Python tests |
| Messy Excel files are read with cell-level provenance, validated, and converted to PK-Sim observed data | Python tests with a deliberately messy workbook |
| Acceptance criteria, fitting planner, fit assessment, audit trail, signatures, agents' citation checks | 62 passing tests |
| **Linux engine image works end to end**: platform snapshot → PK-Sim project → snapshot (all compounds, individuals, protocols, formulations, simulations and observed data preserved, Version 80) → run from snapshot → PK analysis for the IV and PO simulations; fitting job converged (BOBYQA, 20 evaluations) | Docker image `modeler-engine:ospsuite-12.4.4-dev` (`rocker/r-ver:4.6.1` + OSP Linux binaries + .NET 8), `golden_roundtrip.R` and `pi_smoke.R` run inside it on 2026-09-15. Run on an emulated x86-64 container on the development Mac; numbers from the real servers still come from `scripts/ubuntu_engine_check.sh` |
| PK-Sim writes into the working directory on initialization | Verified: `initPKSim()` fails with "Permission denied" when the working directory is not writable. The worker runs every job in its own scratch directory; the image's default working directory is the engine user's home |
| On macOS, `runSimulationsFromSnapshot` is unsupported and `loadProjectFromSnapshot` crashes R | Development on macOS uses the Docker image for anything snapshot-related |

---

## 2. The journey of a project

```
 ① Question & plan ──► ② Client data ──► ③ Literature & databases ──► ④ Build model
      human signs          human confirms       human accepts values         human approves
      the MAP              each new file layout  and access requests          structure
                                                                                    │
 ⑦ Apply & report ◄── ⑥ Verify · validate · qualify ◄── ⑤ Simulate + fit (automatic loop) ◄┘
      author, reviewer,     human signs evaluation          human approves parameters/bounds,
      QA sign               against acceptance criteria     decides only if the loop gets stuck
```

### ① Question and plan
The user types the question ("Can Example-A be given with itraconazole, and at what dose?"), the regulator, and the
deadline. The planner agent drafts the Model Analysis Plan: context of use, which studies are for fitting and which are
held back for validation, acceptance criteria (section 6), data needed, and a runtime estimate. The M15 risk ratings
are left empty. A modeller edits and the MIDD lead rates and signs. Nothing runs before the plan is signed.

### ② Client data, including unstructured Excel
Code: `packages/data-intake`.

1. **Raw vault.** The file is stored exactly as uploaded, named by its SHA-256 fingerprint, write-once.
2. **Grid.** Every sheet is read into cells that keep their `Sheet!A1` reference; merged header cells apply to every
   column they span.
3. **Mapping recipe.** The Data Mapping agent looks at the sheets and proposes a recipe: which rows are data, which
   column is time, which columns are subjects or vessels, units, LLOQ, dose, study id. Every unit, LLOQ or identifier it
   reports must quote the cell it came from; a quote that is not in that cell blocks the proposal. What the file does
   not say becomes a question for the reviewer, never a guess.
4. **Deterministic application.** Code applies the recipe: numbers are parsed, `BLQ` or `<0.5` become "below LLOQ",
   decimal commas are only accepted when the recipe says so, and the data block ends at the first empty row.
5. **Validation.** Unknown units, negative values, times out of order, duplicate times, missing LLOQ for BLQ values,
   mean values without N, dissolution outside 0-110%: all reported, none silently fixed.
6. **Canonical records** go to the database with the source cells of each value. They are converted to PK-Sim observed
   data (dimension `Concentration (mass)`, unit `µg/l`, SD as a linked `ArithmeticStdDev` column), the format read from
   real PK-Sim snapshots.
7. **Next time** the same client sends the same layout, its header fingerprint matches the confirmed recipe and the file
   is read without AI.

### ③ Literature and databases
Code: `services/agents/src/modeler_agents/literature.py`, `mcp_servers.py`.

The research agent uses open sources through MCP servers that run inside the platform network, plus documents the
client uploaded:

| MCP server | License | What it gives | Pinned version |
|---|---|---|---|
| [BioMCP](https://github.com/genomoncology/biomcp) | MIT | PubMed/PubTator3, Europe PMC, ClinicalTrials.gov, OpenFDA, Drugs@FDA, ChEMBL, MyChem | latest `biomcp-cli`; pin at deployment |
| [cyanheads/chembl-mcp-server](https://github.com/cyanheads/chembl-mcp-server) | Apache-2.0 | Compounds, targets, bioactivities (IC50/Ki/EC50), assays incl. ADMET type, drug mechanism | 0.2.4 |
| [cyanheads/pubchem-mcp-server](https://github.com/cyanheads/pubchem-mcp-server) | Apache-2.0 | Compound identity, computed properties, cross-references, bioactivity, summaries | 0.6.2 |

How results stay trustworthy:
- Every MCP tool result is saved as a **retrieved record** with a fingerprint. A value proposed from it must quote that
  record word for word, or it is rejected automatically.
- Database values that are **computed** (e.g. computed logP) are labelled as predictions and used only when no measured
  value exists.
- Conflicting values are proposed separately; the scientist chooses.
- **Paywalled papers:** the agent never works around access. It files an access request with title, authors, journal,
  year and DOI. The team supplies the PDF, it is uploaded to the vault, and the agent can then cite it.
- Studies that report concentration-time data are listed as candidates for extraction (section ② flow), each with a
  citation.

### ④ Model building
Code: `packages/pbpk-domain/src/pbpk_domain/snapshot/`.
Accepted values become a PK-Sim snapshot through fixed code. Units must already be the units PK-Sim stores; anything
else is rejected instead of converted. Every value carries its source into PK-Sim's own `ValueOrigin` field. The same
inputs always give the same snapshot fingerprint. A modeller can open the model in PK-Sim desktop at any time.

### ⑤ Simulate and fit: the automatic loop
Code: `services/engine-worker/r/run_pi.R`, `services/orchestrator/src/modeler_orchestrator/fitting*.py`,
`packages/pbpk-domain/src/pbpk_domain/fitting.py`.

1. **Baseline run** of all fitting studies; prediction error per study for AUC and Cmax.
2. **Sensitivity analysis** picks parameters that are both influential and uncertain.
3. **Staged fitting:** IV data for distribution and elimination first, then oral data for absorption, then special
   processes. Fewer parameters per stage means faster and more trustworthy fits.
4. **Multi-start plan inside the time budget.** The planner computes how many starts fit in the budget on the available
   cores and spreads start values over the parameter ranges (Latin hypercube).
5. **Each start** runs OSP's own parameter identification package (BOBYQA or HJKB locally, DEoptim globally), with log
   residuals, SD weighting and LLOQ handling. Each start's exact spec is saved with its result, so a reviewer can re-run
   it.
6. **Deadline:** starts still running when the budget ends are stopped; the round is judged on finished starts and
   marked "deadline reached".
7. **Automatic assessment** of the round:
   - no start converged
   - starts disagree (possible multiple optima, parameters not identifiable)
   - a parameter stuck at its bound
   - two parameters correlated above 0.95
   - confidence interval wide relative to the estimate
8. **If the fit passes:** a person accepts it; values are written back into the snapshot exactly as PK-Sim's "Transfer to
   Simulation" does, with the run named in the value's origin.
9. **If not:** fixed diagnostic rules and the PI strategist agent propose the next round (add or fix a parameter, change
   weights, flag a suspicious study). The loop may not widen bounds beyond literature ranges and may never exclude data
   by itself; excluding data needs a person and a written reason.

### ⑥ Verification, validation, qualification
- **Verification** ("built right"): unit and reference checks, reproducible re-runs, qualified engine version.
- **Validation** ("right model"): predict the held-back studies and judge them against the acceptance criteria.
- **Qualification** ("platform trusted for this use"): OSP qualification sets re-run per engine version.

### ⑦ Apply and report
Application simulations (DDI, pediatrics, special populations, VBE, FIH, PK/PD) with virtual populations of more than
100 individuals; M15 table rows; the report text is drafted by AI but every number, table and figure comes from engine
runs; author, reviewer and QA sign; the submission package is exported.

---

## 3. Where people decide

| Step | The platform does | People do | Signature |
|---|---|---|---|
| Plan | Drafts plan, criteria, data list, runtime estimate | Edit, rate M15 risk | Yes |
| Client data | Reads, proposes mapping, validates, converts | Confirm each new file layout, answer open questions | Recorded confirmation |
| Literature | Searches, extracts with citations, files access requests | Accept or reject values, supply paywalled PDFs | Recorded acceptance |
| Model build | Builds snapshot, proposes structure | Approve structure | Recorded approval |
| Fitting | Runs, fits, checks, diagnoses, re-runs within the budget | Approve fitted parameters and bounds; exclude data (with reason); decide when stuck; accept the fit | Recorded acceptance |
| Evaluation | All metrics and plots | Judge and sign | Yes |
| Report | Tables, figures, draft text, package | Edit interpretation | Yes: author, reviewer, QA |

---

## 4. Acceptance criteria: what regulators ask for

No regulator sets one number. EMA says acceptance "depends on the regulatory impact and needs to be considered
separately for each application" (EMA/CHMP/458101/2016, Appendix 2). ICH M15 says technical criteria are pre-defined in
the plan and match the model risk. FDA reviews repeatedly accepted predictions within 0.8-1.25-fold of observed AUC and
Cmax for DDI submissions (Li, Sun, Zhang, *Pharmaceutics* 2025;17:1413).

The platform therefore starts every plan from risk-based defaults (`rulesets/pbpk_acceptance_criteria.yaml`, status
**awaiting SME sign-off**):

| M15 model risk | AUC, Cmax | DDI ratios | Share of studies that must pass |
|---|---|---|---|
| High (PBPK replaces a clinical study or drives the label) | 0.80-1.25-fold | 0.80-1.25-fold | all |
| Medium | 0.67-1.5-fold | Guest limits (delta 2) | at least 80% |
| Low | 0.5-2-fold | 0.5-2-fold | at least 80% |

Fitting studies and held-back validation studies are reported separately; both must pass. A plan may tighten any limit.
Loosening needs a written justification.

Evidence the report must always contain (EMA guideline): visual predictive checks with 5th/95th percentiles and 95%
intervals on linear and log scales; more than 100 virtual individuals; Cmax, tmax, t1/2 and AUC; pre-specified
sensitivity ranges (e.g. 10-fold for CYP enzymes, 30-fold for transporters); estimation method and identifiability;
for a victim drug, prediction of a DDI study with a strong inhibitor; executable model files; platform version.

---

## 5. The FDA-ready package

The FDA does not review anything automatically; the regulatory team submits. The platform produces, in one step, a
package a reviewer can open, re-run and trace:

- PK-Sim project file, human-readable snapshot, simulation files
- observed data as CSV plus the original client files
- parameter table with the source of every value
- every fitting start: its spec, its result, the round assessment
- verification, validation and qualification reports
- signed plan, signed report, M15 table
- `rerun_all.R` and a manifest with fingerprints of every file, engine version and seeds

Before export the platform re-runs the package in a clean environment and compares the results; export is blocked if
anything differs. Any number in the report traces to a run, a model version, a parameter source, and finally a
literature quote or an Excel cell.

---

## 6. Runtime on the project servers

**Server (per machine):** Intel Xeon Silver 4510, 2 sockets × 12 cores with hyper-threading = 24 physical / 48 logical
cores, 251 GB RAM, Ubuntu 24.04.4. Root disk 1.8 TB with 126 GB free (93% used).

### How the time is spent
Inside one local fit, evaluations run one after another; only the simulations of one evaluation (one per study) run in
parallel. More cores therefore give more starts at the same time, not a faster single start. DEoptim evaluates a whole
generation at once and does speed up with cores.

### Budget examples (estimates until the server benchmark runs)
Assumptions: 12 fitting studies, 300 evaluations per local start, 45 of the 60 minutes for fitting (15 reserved for
validation runs and reporting). Seconds per simulation on the Xeon is not measured yet; the Aciclovir example took 0.2 s
on the development Mac and 0.47 s in the emulated Linux container (batch: 0.36 s per run on one core, 0.016 s per run
on nine cores, 22.8× speed-up; a two-parameter fit: 41 evaluations in 16.8 s). Realistic oral models with more outputs
will be slower; only the server benchmark counts for sizing.

| Seconds per simulation | One server (48 threads) | Three servers (144 threads) |
|---|---|---|
| 0.5 s | 4 starts in parallel, 2.5 min each: 32 starts in ~20 min | 12 in parallel: 32 starts in ~7.5 min |
| 1 s | 32 starts in ~40 min | 32 starts in ~15 min |
| 3 s | 12 starts in 45 min | 32 starts in ~45 min |
| 10 s | budget too small: the planner refuses and asks for fewer parameters, fewer evaluations or shorter simulations | 12 starts in ~50 min: over budget with reserve |

The planner (`plan_multistart`) makes this calculation before every round from the measured simulation time, and the
round stops at the deadline.

### Sizing recommendations
- **Engine workers:** start with 36 per server (leave threads for the database, workflow engine and OS) and compare
  24 vs 44 workers in the benchmark; hyper-threads usually add less than physical cores for this kind of computation.
- **Memory:** about 1 GB per worker (estimate) is well within 251 GB.
- **Disk:** the root disk is the constraint. Put the engine directory, Docker data and simulation results on another
  disk, keep results as compressed Parquet, and alert at 85% usage.

### First step on the servers
```bash
bash services/engine-worker/scripts/ubuntu_engine_check.sh /data/modeler-engine
```
It installs the engine into that directory and runs the benchmark, the golden round trip (including the Linux-only
snapshot checks) and the fitting smoke test. The resulting `benchmark.json` replaces the estimates above.

---

## 7. Multi-agent, RAG and MCP in this design

- **Multi-agent: yes, controlled.** Specialist agents (planning, data mapping, literature, fit strategy, evaluation
  interpretation, report drafting, QC) are steps in a fixed workflow run by the workflow engine. They propose; code
  checks; people decide. They never set a model value or report number directly.
- **RAG: yes.** Uploaded documents and retrieved records form the citable library; every citation is checked word for
  word against it.
- **MCP: yes, as the access layer to data sources.** The agents reach PubMed, ChEMBL, PubChem, ClinicalTrials.gov and
  FDA data through self-hosted MCP servers with an allowlist of tools, and every call is logged. Simulations, fitting
  and signed records never go through MCP or AI.
- **AI provider:** Claude through Anthropic's API now; the provider setting also supports AWS, Google Cloud, and a
  self-hosted endpoint for the planned local model, which must pass the agents' test sets before use.

---

## 8. Open items

| Item | Needed from |
|---|---|
| Run `ubuntu_engine_check.sh` on one server and share the results folder | Server admin |
| Confirm whether the three servers are identical and networked | Server admin |
| Free disk space or add a data disk for engine and results | Server admin |
| SME sign-off of acceptance criteria and static DDI ruleset | PBPK and clinical pharmacology leads |
| Confirm the literature access process for paywalled papers (who supplies PDFs) | Project lead |
| Legal review of GPLv2 use for on-prem delivery | Legal |
