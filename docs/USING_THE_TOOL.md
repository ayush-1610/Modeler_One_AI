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

**From a proposal (Step 1 · Start):** **+ Start from proposal** → name the drug and drop the proposal, its annexes and
the client's data files in one upload (each file says what it is; the client's go straight to Inputs) → the Start screen
fills the drug's identity from PubChem and, with an agent configured, the short brief from the documents, each value with
the words it came from. Set what they do not say and correct what is wrong; no "why" is asked. Rate model influence and
decision consequence, then set the model risk ICH M15 admits for them. Say what is modelled (modality, PBPK model, site
of action, formulation types, the scenarios' routes): what the builder cannot model yet is refused there. The data
checklist below follows the brief as it changes; change who provides an item in place. Nothing on Start is approved: you
review everything once, when you sign the plan.

## 5. Checks against the published models

`bash deploy/reference/run_all.sh roundtrip -j 8` on the server (or the GitHub Actions workflow "Reference models
(PK-Sim)", which runs on every push) rebuilds every published simulation from the imported CPF and compares both on
PK-Sim: identical inputs must give identical curves (1e-6 of the peak). Results: `reports/reference/<stamp>/summary.md`.

## 6. Client data (P3): reading the client's spreadsheets

The Client data page shows five steps at the top: data checklist, files, sheets read, plan items, approval. The approve
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
   - "Same layout as the last sheet" copies columns, units, LLOQ and cell texts to the next file; the rows and the
     study (id, dose, route, formulation, food, subjects, purpose) stay this sheet's own.
   - Read a sheet again to correct it: the new reading replaces the earlier one (its datasets are rejected).
3. **Settle what the client cannot send** ("What stops approval"): with a reason, either **Not from the client** (the
   gap is recorded) or **Get it from the literature instead** (P2 takes it over). The literature cross-check counts only
   once a literature value is accepted. These decisions change the data checklist, which follows them at once (Start
   shows it); it is never approved.
4. **Approve the client data.** Then accept the new datasets and release-model values on the Literature page.

## 7. Inputs (step 2): from every source to a ready CPF

The Inputs page (`/projects/{id}/inputs`) is one workspace in PK-Sim's building blocks: **Compound**, **Formulations**,
**Individuals**, **Simulation settings** and **Studies**. Values flow in from the client's files, the literature agent,
PubChem and the published OSP model with no per-item acceptance (D-27). The inputs are put together again after
every change. The side list **Still missing to run** names each open item; clicking one opens it on its tab. Nothing
is approved here: the one review is at the MAP signature.

- **One value per input (source selection 0.1, provisional until the SME signs).** Sources within 10 % of each other
  are one value with all of them listed ("+N agree"). Within 2-fold, the best source is kept (the client, then the
  literature by grade, then databases, then the published model) and the others are listed under the row for the
  review. Beyond 2-fold, **keep one** with a reason. Values are never averaged.
- **Exclude a source** from a row's sources, with a reason; the next best source takes over.
- **Add a value** in any row: the value, its unit, the source (DOI or URL) and the sentence that states it.
- **Held until you check it:** a value filed where a mistake is likely (a % bound as fu, fe as the GFR fraction), one
  with no conversion to the PK-Sim unit, or one moved to another parameter by a correction. Accept or reject it.
- **Filed under the wrong parameter.** `elim` (the data plan's "an elimination pathway"), a template such as
  `elim.hepatic.{enzyme}.km/vmax`, or a name the model does not use never reaches PK-Sim. Choose the real parameter
  (and the enzyme) and **Correct**, or **Reject**. The fraction excreted unchanged in urine goes under
  `elim.fe_urine`; PK-Sim's GFR fraction is a multiplier on filtration, not fe.
- **pKa: acidic or basic?** Choose and save. Two acidic (or two basic) values from different sources wait on you.
- **Individuals.** Each study's individual: the PK-Sim population database, sex and age (with the age range, weight and
  height when reported), or **Use the healthy adult default**, which the MAP lists as a limitation. It is never
  applied silently.
- **Studies.** Each study's facts, the role the MS-01 split proposes (changed only on Review & sign), whether it is
  blinded, a multiple-dose study's number of doses and interval, and **Leave out** with a reason. Add data by reading
  the client's sheets, filling the client-data template, digitizing a published figure, or typing a table in.
  - **Digitizing a figure in a PDF:** open the digitizer on the Literature page. A PDF's figures (images placed on
    its pages) are listed: pick one and the page is cropped to it. A figure drawn as lines is cropped by hand
    (**Crop to a region**, then two corners). **Zoom** enlarges the view. Calibrate the axes and pick the points in
    that view; changing the crop, the page or the zoom starts the calibration again. The dataset keeps the crop.
- **Formulations and Simulation settings.** The formulation of each solid study, the dissolution profiles with their
  Weibull fit ("Propose as release model") and f2, the calculation methods, the values set on the simulation, and each
  study's solver settings.

When the list is empty, **Go to Review & sign**.

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
