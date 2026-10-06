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
| Verapamil, Omeprazole, Dabigatran, Itraconazole, Ketoconazole systems | Parent with enantiomers and metabolites simulated together (sum observers, CYP2C19 poor metabolisers, prodrug). The parent is fitted and gated; metabolite data are reported (phase 2 needs the MS-01 amendment). |
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

## 6. Client data (P3): reading the client's spreadsheets

The Client data page shows five steps at the top: data plan, files, sheets read, plan items, approval. The approve
button opens when every **required** plan item is delivered or decided.

1. **Upload** every file (drop zone). Workbooks are split into sheets; PDF, Word and Markdown are kept as citable
   documents. The client-data template (download button) is read automatically, cell by cell.
2. **Read each data sheet** ("Read this sheet"). The sheet appears next to a form filled in from what the sheet
   states: header row, data rows (Mean / SD rows under the subjects are left out), times down a column or across the
   top, subject / period / value columns, units, LLOQ and dose quoted from their cells. "Found in the sheet" says what
   was taken from the file name instead (study id, food state) and what is missing.
   - Fill what the sheet does not say: number of subjects, formulation, the study's purpose (BE, fed and
     other-formulation studies: **external validation**), the infusion time for IV data.
   - Give each BE arm its own study id (e.g. `230-23-TEST`, `230-23-REF`).
   - Dissolution: name the product exactly as the brief does and its role (TEST / RLD); the release-model item and the
     f2 comparison count only such profiles.
   - "Check what will be read" shows the subjects, times, the first values with their cells, and every problem in
     words (e.g. a cell that says `NS`: add it under "cells that mean no sample"). "Save these data" keeps it.
   - "Same settings as the last sheet" copies the layout to the next file of the same kind.
3. **Settle what the client cannot send** ("What stops approval"): with a reason, either **Not from the client** (the
   gap is recorded) or **Get it from the literature instead** (P2 takes it over). The literature cross-check counts only
   once a literature value is accepted. These decisions change the data plan: approve its new version on the Brief
   page.
4. **Approve the client data.** Then accept the new datasets and release-model values on the Literature page.

## 7. Model inputs (P4): from evidence to a ready CPF

Press **Assemble from the accepted evidence**. Under it, **What stops readiness** lists each open item with what
settles it; every decision asks for a reason and the inputs are assembled again after it:

- **Several accepted values: keep one.** Pick the value (source, grade and quote are shown) and give the reason; the
  others are rejected with it. Code never averages or chooses.
- **Filed under the wrong parameter.** `elim` (the data plan's "an elimination pathway"), a template such as
  `elim.hepatic.{enzyme}.km/vmax`, or a name the model does not use (e.g. "plasma protein binding") never reaches PK-Sim.
  Choose the real parameter (and the enzyme) and **Correct**, or **Reject**. A value filed under another parameter is
  proposed again with its converted value: check the number still means the same (30 % *bound* is fu 0.70, not 0.30).
- **pKa: acidic or basic?** Choose and save.
- **Missing for S0.** Accept a proposal shown there, propose the molecular weight from the brief's PubChem record
  (check it is the free base), or **Ask the literature agent for what is missing**.
- **Observed data.** Accept the datasets read on the Client data page. Studies with individual subjects only are kept
  for the population evaluation; the campaign judges mean profiles (e.g. published mean data).

## 8. When something looks wrong: the project doctor

On the server, in `~/Modeler_One_AI`:

    source deploy/server/_env.sh
    uv run python -m modeler_api.doctor --list            # tenant, project id, drug, phases
    uv run python -m modeler_api.doctor <project_id>      # also saved as ~/modeler-logs/doctor-<project_id>.md

The report gives each phase's state and blockers, the evidence per parameter (conflicts, unknown names), datasets
(metadata only, never concentrations), readiness and its to-do list, the last audit events and recent API errors.
Paste it into a Claude session to get the project diagnosed. To let Claude look at the server directly, run a Claude
Code session on the server itself (`claude remote-control` in `~/Modeler_One_AI`); that folder is a deploy copy, so code
changes are still made in the git checkout and deployed.
