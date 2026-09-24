# Using Modeler One — get it running, open the examples, build a PBPK model

Every simulation the tool runs on the server is **real PK-Sim** (ospsuite 12.4.4 / PK-Sim 12.3.173 through
`services/engine-worker/r/run_job.R`). The stand-in engines in `deploy/dev/` are test fixtures only; a campaign run
on one is labelled "Not a PBPK result" on every page, so it can never be mistaken for evidence.

## 1. Start the tool on the server (from the Mac)

```bash
cd ~/Modeler_One_AI            # the git checkout on the Mac
git pull origin main-1czavz
bash deploy/dev/deploy_to_server.sh      # rsync, install, build the web app, restart API + web, print the URL
```

Open `http://<server>:3000` (the LAN address the script prints, or the tailnet address after
`bash ~/Modeler_One_AI/deploy/server/setup_tailscale.sh` on the server, which gives a stable address from anywhere).

## 2. Load every worked example (on the server)

```bash
ssh adt-server 'bash ~/Modeler_One_AI/deploy/server/seed_examples.sh'     # 3 campaigns at a time
ssh adt-server 'tail -f ~/modeler-logs/seed.log'                           # progress
```

It creates one project per example through the API, exactly as you would in the browser (project, CPF, studies,
analysis plan generated and signed, campaign started), and runs the campaigns on PK-Sim a few at a time. Run it again
at any time: examples already in the tool are skipped. It refuses to start with less than 5 GB free.

| Project | What it shows |
|---|---|
| Dapagliflozin (as published) / (refit S1-S3) | The plan-exit drug: 40 real studies (IV microdose, solution, tablets, fed, multiple dose, renal impairment). As published: the peer-reviewed parameters judged stage by stage. Refit: the parameters MS-01 lets S1–S3 fit, freed and fitted on PK-Sim. |
| Rifampicin (as published) / (refit S1-S3) | The second plan-exit drug: saturable AADAC metabolism, OATP1B1 / P-gp transport, auto-induction, 53 studies. |
| Midazolam, Alfentanil, Alprazolam, Clarithromycin, Digoxin, Metformin, Raltegravir, Ketoconazole, Voriconazole, Itraconazole | The other published OSP library models with their clinical data (CYP3A4 / UGT metabolism, transporters, particle dissolution, loading-dose regimens, pH-dependent solubility, fed-state alternatives). |
| Verapamil, Omeprazole, Dabigatran, Itraconazole systems | Parent with enantiomers and metabolites simulated together (sum observers, CYP2C19 poor metabolisers, prodrug). The parent is fitted and gated; metabolite data are reported (phase 2 needs the MS-01 amendment). |
| Aciclovir (illustrative) | A hand-made quick check of the software path; labelled as such, not evidence. |

## 3. What each campaign does

S0 readiness → S1 IV → S2 oral fasted → S3 formulation / fed → S4 internal validation → S5 external validation → S6
prediction (sensitivity, prediction intervals; **stops for your signature**) → S7 report and package.

- **Escalations** land in the **Review inbox**. A stage escalates when the model misses the acceptance criteria
  (1.5-fold at medium risk) on a study it must fit, and no permitted action fixes it. You decide there (accept with a
  justification, exclude data, change what is fitted, stop); every decision is signed and recorded. Published models
  do escalate on some studies: the pipeline judges them by the same rules as a new model.
- **S7 package** (`package.zip`, only when the re-run of every bundled simulation reproduces the results at 1e-6):
  the final CPF, the signed analysis plan, the observed data, the S4/S5 simulations as PK-Sim snapshots **and as
  PK-Sim projects (`pksim/*.pksim5`, open them in PK-Sim)**, their results, every fit's specification and result, S6,
  the report (MAR) as PDF/A, Word and Markdown, a manifest with hashes, and `rerun_all.R`.

## 4. Your own compound

**New project** → pick a starting point (a published model with its real data, or start empty) → enter or check the
compound's parameters (CPF: physchem, binding, permeability, clearance processes; every value with its source) →
**Add data** (CSV of plasma concentrations per study: dose, route, formulation, food state, population) → **Run
campaign**. The tool generates the analysis plan from your studies (the MS-01 data split), you sign it, and the
campaign runs S0 → S7 on PK-Sim.

## 5. Checks against the published models

`bash deploy/reference/run_all.sh roundtrip -j 8` on the server (or the GitHub Actions workflow "Reference models
(PK-Sim)", which runs on every push) rebuilds every published simulation from the imported CPF and compares both on
PK-Sim: identical inputs must give identical curves (1e-6 of the peak). Results: `reports/reference/<stamp>/summary.md`.
