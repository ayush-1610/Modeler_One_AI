# Changelog

Every notable change to Modeler One, newest first. **Any commit that changes behaviour adds an entry here in the
same commit** — see `CLAUDE.md`. Each entry says what changed, why, and the commit, so the history survives a change
of person, session or AI model.

Status words: **Added** new capability · **Changed** behaviour altered · **Fixed** a defect, with its impact ·
**Known gap** a limitation we know about and have not yet fixed · **Docs** / **Infra** as named.

Where things stand right now, stage by stage, is in `docs/CONTINUATION_PACKAGE.md` §4 (pipeline coverage).

---

## [Unreleased] — make the pipeline do real PBPK, S0 → S7
Plan: `docs/plans/2026-09-24-s0-s7-real-pbpk.md`. Scope agreed 2026-09-24: complete every MS-01 stage, prove it on
published OSP models against their real clinical data on real PK-Sim. DDI / paediatric application templates follow.

### Added — model systems, phase 1 steps 1–2: data model and import (plan `2026-09-24-multi-compound.md`, approved)
- `pbpk_domain.system.ModelSystem`: one CPF per compound (unchanged), roles (parent = dosed, metabolite = only
  formed), formation links, **products** (what a study administers: each dosed compound's fraction of the reported
  dose, carrying the salt and enantiomer split — required, never defaulted), published sum observers copied
  verbatim, and analytes with the output path the published simulations read. `ModelSystem.single(cpf)` is today's
  single-compound case.
- `import_osp_system`: the system around the main parent — its enantiomer family, compounds a published sum
  observer adds, and everything they form; DDI co-drugs stay out. Each study names its analyte (compound or sum, from
  its molecule, the observer name, or the published output mapping) and its product (from the published protocols).
  Verapamil: 74 studies on 6 analytes (racemic sums, enantiomers, norverapamil), products including
  `R-Verapamil 0.462875 + S-Verapamil 0.462875` (120 mg HCl -> 2 x 55.545 mg). Omeprazole: esomeprazole vs racemic
  products. Dabigatran: prodrug -> CES1/CES2 -> dabigatran -> UGT2B15 -> glucuronide, and the mass-weighted `SUM`.
  Itraconazole: 63 studies incl. 22 hydroxy-itraconazole. Warfarin's datasets name no compartment for a single
  enantiomer and stay skipped (named).
- `StudyRecord` / `StudyUpload` gain `analyte` and `product`. Verapamil, Omeprazole and Dabigatran snapshots vendored.
- Not yet: building and simulating systems (step 3), engine outputs and round trip per analyte (step 4).

### Fixed — what the PK-Sim runs of 9e617f6 showed (run 36009097300)
- **Round trips now match to ~5e-5 of the peak where they were off.** Midazolam oral was 1.4–3.7× the published curve;
  with the per-simulation gut-wall permeabilities it is within 5e-5 (AUC ratio 1.00003) for every oral study, the six
  per-kg IV studies are now found and match, and Yu 2004 in its own Korean individual is within 2e-5.
- **The remaining systematic ~5e-5 was the individual's Seed.** The parameter diff showed every organ-volume
  percentile slightly different (`Organism|Stomach|Volume|Percentile` 0.50086 published vs 0.50032 ours): PK-Sim
  draws them from `Individuals[].Seed`, and the builder used the campaign's seed. The published seed is now a CPF
  record (`indiv.seed`, the `Seed` key harvested from the snapshot) applied to every subject built from the CPF; a
  per-study published individual carries its own. Seeds are signed 32-bit, as published (Alprazolam -2063117500).
- **Diagnostics never saw the fit's optimiser evidence.** `assess_fit` found parameters at a bound, correlated pairs and
  disagreeing starts, but the findings stopped at the fit round: the refit of the published Dapagliflozin model left
  UGT1A9 clspec at its 0.1x bound and the next round reported "no diagnostic rule matched". `FitRoundOutcome` now
  carries them structured, the post-fit pass passes them in `RoundContext.fit_signals`, and the existing escalate /
  fix-and-refit / switch-algorithm rules (MS-01 §5, diag-rules unchanged) act on them.
- **The IV distribution rule could never fire.** Its evidence (early concentrations < 2 x tmax off, Vss off) was
  hard-wired off. It is now computed from the prediction read at the observed sampling times: the geometric-mean
  ratio over the early samples, and the Vss ratio (MRT/AUC with the infusion correction; dose cancels), judged
  against the ruleset's own 0.8–1.25 band. The refit's IV Cmax 0.44 with AUC in limits is that rule's case.
- `run_reference.py`: `--out` is resolved to an absolute path (the evaluate jobs failed on a relative file URI).

### Added — the OSP model library through the importer: 20 of 25 published models S0-ready (3 before)
Every published JSON snapshot of github.com/Open-Systems-Pharmacology (25; Gemfibrozil, Theophylline, Repaglinide and
Trimethoprim ship only a binary `.pksim5` project) was imported; each gap found was fixed from the snapshots' own
names and units, or is named. Six small models are vendored as fixtures with their commits
(`services/engine-worker/golden/fixtures/SOURCES.md`) and each process type / edge case has a regression test
(`test_reference_library.py`).
- **Process types** (builder `HarvestedProcess`, a table of harvested parameter names and units per type; an
  unlisted name is refused): intrinsic first-order (Alfentanil), recombinant-CYP MM and first-order (Efavirenz,
  Itraconazole), total hepatic clearance (Digoxin, Cimetidine), renal clearance (Clarithromycin), Hill transport
  (Metformin PMAT), vesicular-assay transport (Rosuvastatin), irreversible / mixed / noncompetitive inhibition
  (Clarithromycin, Atazanavir, Fluconazole). Systemic selections harvested: `Total Hepatic Clearance-<source>`
  (Hepatic), `Renal Clearances-<source>` (Renal).
- **Two pathways on one enzyme** (Alprazolam CYP3A4 alpha-OH / 4-OH) were one process: processes are now keyed by
  data source, and colliding CPF ids name it (`elim.hepatic.CYP3A4@alpha-OH pathway.kcat`).
- **Multi-compound snapshots** (11 models) were refused. The parent (the compound most simulations dose, or the one
  named) is imported; a study whose published simulation doses another drug is a DDI arm (`co_medication`); one whose
  metabolites act on the parent's clearing protein (Itraconazole's hydroxy-, keto-, N-desalkyl-itraconazole on
  CYP3A4) is labelled "differs by design" in the round trip. Interactions come from the compound's own simulations
  only, not DDI arms. Processes no own simulation selects are named, not built.
- **Units**: nmol↔pmol per mg microsomal protein / per pmol enzyme or transporter, µM, 1/h, ml/h/kg, l/h/kg, l/h,
  pmol/ml/min, mg/dl. **Vmax 0** is a published input when kcat carries the rate (Cimetidine, S-Warfarin,
  Clarithromycin microsomes); a microsomal process without kcat leaves it to PK-Sim's formula.
- **pH-solubility tables** (Raltegravir, Voriconazole): `phys.solubility.table` (pH, mg/l points), written as PK-Sim's
  `Solubility table` TableFormula; S0 completeness accepts it as the reference solubility.
- **Several solubility alternatives** (Carbamazepine, Erythromycin, Itraconazole): the one most own simulations use is
  imported; studies simulated with another are labelled. Exact per-study alternatives are a named follow-up.
- **Metadata edge cases** (every value in the library): routes "po", "iv", "capsule", "IV_30min_infusion",
  "30-min infusion" (infusion time read), genotype filed as route ("EM"/"PM") or none → the published protocol's
  application type; a dose without unit is mg only when the dataset name repeats it, else the published protocol's
  dose; no administration times → the published protocol's schedule; food states "Breakfast", "Light breakfast",
  "Semifed" → fed, "Semifasted"/"Unknown"/mixed → the published simulation's meal state; a dataset with no study id
  → its own name (Clarithromycin's 17 datasets collided on ""); a garbled molecule name ("Fluvoxaminekjujhöjö") is
  accepted only where the published model maps the dataset onto the parent's plasma output. All noted per study.
- **Expression library 16 → 40 proteins** (CYP1A2/2A6/2B6/2C8/2C9/2C19/2D6/3A5, OCT1/2, MATE1, OAT3, BCRP, OATP1B3,
  OATP2B1, PMAT, MRP2, CES1/2, FMO3, UGT2B15, …) from library clones (`harvest_expression_library.py --library`, commit
  recorded per entry). Existing entries are unchanged, so existing models build identically.
- **Fixed — fit paths for transport, inhibition and induction were never harvested and were wrong.** `pksim_paths`
  assumed they share the metabolism container (`<C>-<M>-<source>|p`); the published PIs' `LinkedParameters` show
  `<C>|<M>-<source>|p`. A transporter kcat fit (diag-rules 0.4) would have addressed a path that does not exist.
  Shapes are now harvested per type (intrinsic FO, recombinant CYP, total hepatic clearance added); a type with no
  harvested path raises and is not offered for fitting.
- Portfolio: fetches the vendored fixture, then the raw file, then a shallow `git clone`; a split failure is a row.

### Fixed — a study the published model simulates in its own individual was regenerated in the main one
- **Per-study published individual.** `StudyRecord.published_individual` (reference import) carries the individual a
  published model uses for one study when it differs from the main one: its complete physiology overrides (replacing
  the CPF's `indiv.*` for that study, so a value the main individual sets and this one does not stays at the PK-Sim
  default, never invented) and its expression values that differ from the library, built under the subject's own
  profile category. Cases: Rifampicin `acocella-1972a-day-7` in the "EHC off" individual (round-trip AUC 1.043 before);
  Midazolam `yu-2004-control-cyp3a5-3-3` in the Korean individual (CYP3A4 3.63 vs 4.32 µmol/l, round-trip AUC 0.91).
- **Study weight and height are now written into the individual.** `OriginData.Weight` (kg) / `Height` (cm) were held
  back until harvested; the OSP Midazolam model's Korean individual sets both, so the builder emits a study's recorded
  mean weight/height and PK-Sim scales the physiology to it. Impact: any study with a recorded weight is now simulated
  at that weight instead of the population default for its age and sex. The reference importer takes both from the
  published individual's OriginData; the write API keeps `published_individual` on upload.

### Changed — diag-rules 0.5 (UNVERIFIED): exposure fallback rule (approved by the project owner, 2026-09-24)
- New rule `exposure_fallback`: when a fitting study's AUC is off by more than 1.5-fold (either direction) and no other
  rule's evidence is present, fit clearance first (`elim.hepatic.{enzyme}.clspec`, `elim.hepatic.{enzyme}.kcat`,
  `transp.{name}.kcat`), then `phys.logp`. Evidence `exposure_off`; threshold `exposure_fallback_fold: 1.5`. A rule
  marked `fallback: true` fires only when no specific rule matched, so the clearance, absorption and first-pass rules
  keep their own order.
- Why: refitting the published Dapagliflozin and Rifampicin models from shifted starts escalated at round 1 with
  "no diagnostic rule matched" while AUC was 2-fold off. The clearance rule needs t1/2 to move with AUC; with several
  parameters wrong at once they point opposite ways.
- Impact: those refits now proceed to a clearance fit. Ruleset version bumped to 0.5; stays UNVERIFIED pending SME
  sign-off. `docs/PBPK_MODELING_WORKFLOW.md` §5 table gains the row.

### Fixed — Midazolam round trip on real PK-Sim: oral curves 1.4–3.7× the published ones (run 36003028399)
- **Gut-wall permeabilities set per simulation were dropped.** The published Midazolam model sets the PI-identified
  `Neighborhoods|<segment>_int_<segment>_cell|Midazolam|P (interstitial<->intracellular)` (11 gut segments, 22 values)
  in its simulations. The importer only took `<Compound>|…` paths, so our oral simulations had PK-Sim's default gut-wall
  permeability and far less intestinal first-pass (IV matched to 0.3 %; oral AUC 1.2–2.7× and Cmax 2.2–3.7× high,
  worst at microdoses where gut CYP3A4 is not saturated). Any compound path the simulations set is now a `sim.*`
  record when every simulation setting it agrees and at least half set it; a simulation that leaves it at the default
  is named in the notes (Midazolam: the 30-min IV infusion).
- **The published expression profile now wins over the library copy.** The builder used the harvested library profile
  (CYP3A4 from the Dapagliflozin model, `t1/2 (liver)` 37 h); the Midazolam and Rifampicin models use 36 h, which sets
  the enzyme turnover that induction acts on. Each value of the published individual's profiles that differs from the
  library becomes an `expr.<path>` record (ExpressionProfile building block) applied over the library profile at build.
- **Published simulations named with "/" (`iv 0.075 mg/kg (1 min)`) were reported "not exported".** PK-Sim writes the
  "/" as a subdirectory; `reference_compare.R` now lists the export recursively and falls back to an alphanumeric
  name match. Its parameter diff skips wildcard paths (`Organism|R*T`), which `getQuantityValuesByPath` rejects.
- Impact: 6 Midazolam IV studies join the round trip; oral Midazolam and Rifampicin induction are regenerated from the
  published values. Re-run pending on real PK-Sim.

### Changed — reference workflow
- `run_reference.py evaluate <drug>`: the published model judged on every study it can simulate by the pipeline's own
  evaluation (GMFE, within 1.25/1.5/2-fold of AUC and Cmax), one engine run; matrix jobs for the three drugs.
  `roundtrip.study_snapshot` builds that snapshot. The workflow no longer cancels a running set on push.

### Fixed — the model regenerated from a published CPF was not the published model (found preparing the round trip)
- **Simulation-level compound values were dropped.** Every published Dapagliflozin simulation sets
  `Dapagliflozin|logP (veg.oil/water)` = 2.083 (drives Rodgers & Rowland tissue partitioning) and the measured
  blood/plasma ratio 0.88. The CPF now carries them as `sim.<path>` records (Simulation building block), and the
  builder writes them into every simulation's `Parameters`.
- **Inhibition and induction never acted.** The builder selected `CompetitiveInhibition` / `Induction` among the
  compound's `Processes`. PK-Sim selects them as the simulation's `Interactions`
  (`{"Name": "<Molecule>-<DataSource>", "MoleculeName", "CompoundName"}`, harvested from the OSP Rifampicin snapshot),
  so rifampicin's auto-induction of its own metabolism (AADAC) and transport (P-gp, OATP1B1) would have been
  silently off. Now written as interactions. The old test that asserted the wrong selection is corrected.
- **Rifampicin imports** (51 plasma studies from its 13 sources; 38 datasets named and not used): values the paper
  identified are recognised by `ValueOrigin.Method` too, so they are `FITTED`. Studies are linked through the
  paper's own parameter identifications (`ParameterIdentifications[].OutputMappings`) as well as the simulations.
  Every OSP regimen notation is read (`(S0-T24-R14)`, `(S-0,T-24,R-7)`, `0-24-48-…`, mixed). A linked
  multiple-dose protocol applies only when the dataset was sampled after the second dose; irregular schedules are
  named, not simulated. IV infusion times come from the published simulation's override, else from the dataset's
  description. Free-text formulations are classified by their words. An antacid arm is a DDI study and a
  liver-disease arm a hepatic-impairment study, and neither is fitted. Interactions the published simulations
  never select (DDI with victim drugs: CYP2C8, CYP2C9, BCRP, OATP1B3, OATP2B1, CYP1A2, CYP2E1) are named and left
  for the DDI phase. The study upload now keeps `co_medication`.
- **`docker_engine.sh` on Linux** runs the engine as the calling user (the job directory is 0700; the image's uid
  10001 could not write there).

### Verified on PK-Sim — first reference results (GitHub runner, qualified engine 12.4.4 / rSharp 1.2.2)
- **Dapagliflozin round trip:** 28 of 34 published simulations regenerated from the imported CPF agree within 6.3e-5
  of the peak (AUC and Cmax within 0.005 %), the same small offset in every pair. Not yet the 1e-6 bar; a
  parameter-by-parameter model diff is added to locate it. The IV pair's 100 % "difference" was a harness bug (see
  below). The Chang 2015 fed tablet (Cmax 0.71×) and the five Komoroski MAD day-1 datasets (AUC 13.7×) differ by
  design: we simulate the reported meal and the real 14-dose regimen, while the published model approximates them
  as fasted / single dose. They are now labelled so.
- **Rifampicin round trip:** first pair within 4e-5 of the peak (run interrupted; rerun queued).
- **Dapagliflozin as-is campaign escalated at S1** on the IV microdose Cmax (0.48×), while the published model and
  ours agree. The cause was our evaluation, fixed below. **Refit:** the clearance fit cut the S1 AUC error from 2.6×
  to 1.46×, then the stage failed on `BudgetTooSmallError` (a 1800 s stage on a 4-core runner).

### Fixed — evaluation and NCA defects the PK-Sim runs exposed (science; flagged for SME review)
- **The prediction is read at the observed sampling times** before NCA. Predicted and observed AUC, Cmax, tmax and t½
  now come from identical sampling. Before, the simulated grid (every 6 min) was reduced over the observed window,
  so the IV microdose sampled from 5 min was scored on a 6-min value (Cmax 0.48×). `ObservedPK.sample_times`.
- **Simulations are sampled every minute for the first 2 h**, then as before (two output intervals, as the OSP
  reference simulations use). Early IV and distribution-phase samples are resolved.
- **NCA terminal phase:** only points after Cmax; trailing points that do not decline are left out of λz (they stay
  in AUClast); adjusted-R² ties within 1e-4 take more points (the standard best-fit rule). The Boulton 2013 IV data
  (last two points identical, assay limit) gave t½ = 275 h; now 9.5 h from 8 points.
- **A stage that cannot fit its remaining budget escalates with the best CPF so far** (`budget_exhausted`, D8),
  instead of failing and losing its rounds. Reference runs set the stage budget for their host
  (`REFERENCE_STAGE_BUDGET_S`; 1.5 h per stage on a 4-core runner, where the server has 48 cores).
- **Round-trip harness:** samples are paired by time (PK-Sim always outputs t = 0, so a published dose at 60 min
  shifted the indices and showed a false 100 % difference), and deliberate differences are labelled.
- Test fixture fixed: its observed Cmax was not the Cmax of its observed profile.

### Added — Midazolam, and the edge cases it brings (third reference model)
- **Microsomal Michaelis-Menten metabolism** (`MetabolizationLiverMicrosomes_MM`: in-vitro Vmax per mg microsomal
  protein, microsomal enzyme content, Km, kcat; names and units from the OSP Midazolam model) is placed by the builder;
  **specific binding** (GABRG2) is imported. Midazolam imports S0-ready: 79 real studies, 72 paired with a published
  simulation.
- **Per-kg doses** (`0.05 mg/kg`) are simulated as PK-Sim `mg/kg` InputDose (scaled by the individual's weight, as
  the published protocols do); µg doses are converted. A study carries `dose_per_kg`; the S2 dose-level choice and
  the dose-normalised diagnostic compare like units only.
- **Any regular regimen** (e.g. every 6 h) is built as a repeated protocol schema (`NumberOfRepetitions` /
  `TimeBetweenRepetitions`, the structure of the OSP multiple-dose protocols); named DosingIntervals (DI_24, DI_12_12)
  stay as they were. Before, such a study was not simulated.
- **Study demographics** reach the MAP: the upload keeps `demographics`, and the importer sets them from the
  individual the published simulation uses (e.g. an Asian_Tanaka_1996 study is simulated in that population).
- **A formulation named only by its product** ("Dormicum") is recorded as `other`: judged, never used to train
  absorption or release; syrups and injections given orally are solutions.

### Changed — diag-rules 0.4 (owner-approved 2026-09-24, still UNVERIFIED pending SME sign-off)
- **The clearance rule may fit Michaelis-Menten catalytic rates** (`elim.hepatic.{enzyme}.kcat`,
  `transp.{name}.kcat`), after first-order `clspec` and before renal clearance and logP; the S1/S2 stage plan permits
  them. Before, a compound cleared by saturable metabolism or transport (rifampicin: AADAC, OATP1B1, P-gp) could
  never have its clearance fitted, only escalated or hidden in logP. The Rifampicin refit is no longer held.

### Added — the OSP library portfolio
- `deploy/reference/portfolio.py` fetches every OSP library model (`Open-Systems-Pharmacology/<Drug>-Model`), imports
  it, checks S0 and the split, and, on the engine, round-trips each published simulation. The table of what the tool
  can and cannot take, drug by drug, is the work list for the next fixes. Runs in the reference workflow.

### Fixed — the engine image was not the qualified engine
- **The Dockerfile pinned nothing but R and .NET.** Built today it pulled rSharp 2.0.0 (needs .NET 10) with the
  .NET 8 runtime, and PK-Sim could not start (`No .NET 10 runtime was found`; first reference run). The qualified
  engine (golden/catalog.json) is ospsuite 12.4.4 / PI 2.2.0 / rSharp 1.2.2. rSharp is now installed from its
  tagged 1.2.2 release, and the build fails unless all three versions match.

### Added — reference runs on real PK-Sim (GitHub Actions)
- `deploy/reference/run_reference.py` (round trip / as-is / refit) and `.github/workflows/reference-models.yml`. The
  workflow builds the pinned engine image on a GitHub runner, where CRAN and the OSP r-universe are reachable (they
  are not from the development container). `reference_compare.R` compares each published simulation with our
  regenerated one on identical time points (tolerance 1e-6 of the peak). The refit (`pbpk_domain.reference.refit`)
  frees what the published model identified within the user-approved bounds (0.1×–10×; logP ±1.5), from shifted
  starts. Campaigns stop at the S6 signature gate; CI never signs.
- **Known gap (needs approval, SME-governed):** the diagnostics clearance rule offers only first-order `clspec`,
  GFR fraction, tubular secretion and logP as fit targets. A Michaelis-Menten `kcat` (rifampicin's AADAC metabolism,
  P-gp / OATP1B1 transport) can never be fitted, so the Rifampicin refit is held.

### Added — the reference importer: a published OSP model becomes a CPF and its real clinical studies (Phase 4)
- **`pbpk_domain.reference.import_osp_snapshot`** turns a published single-compound OSP model snapshot into a CPF
  plus its plasma studies in the API's upload shape. The data are real: they are the OSP model's own clinical
  datasets. Values, units and provenance are copied from the snapshot (a value the published model identified stays
  `FITTED`, a literature value `FIXED`); no fit policy is invented. A study's route, dose, formulation, food state
  and regimen come from the dataset's metadata. Where a dataset leaves one open, the published simulation that runs
  it fills the gap, and the study's reference says so. Display units of the same dimension (e.g. fu in %, solubility
  in mg/l, a transporter concentration in µmol/l) are converted to the unit the builder requires. Any other unit
  pair raises an error.
- **Dapagliflozin imports complete and S0-ready**: 28 CPF records (3 UGT/CYP clearances, GFR, physchem, both
  permeabilities, the Weibull tablet, 7 individual physiology values) and 40 plasma studies from 13 publications
  (IV microdose, solution, capsules, tablet, fed, multiple dose, renal impairment). The MS-01 split assigns the IV
  microdose to S1, solution / Dissolved-capsule studies to S2, the fed tablet to S3, and 32 external studies to S5.
  The four T2DM / renal-impairment arms are SPECIAL and never fitted. Every stage's snapshot builds, and it carries
  the published process values and individual physiology exactly (asserted in the tests). The 15 datasets not
  imported (urine/feces fractions → T-11, metabolites) are each named with the reason. **Not yet proven on PK-Sim**:
  the 1e-6 round trip against OSP's own outputs and the full campaign need the engine host.
- **Gaps the other reference models expose (named, not fixed):** Rifampicin's DDI targets (CYP2C8, CYP2C9, BCRP,
  OATP1B3, OATP2B1, CYP1A2, CYP2E1) have no harvested expression profile, so S0 refuses it; its capsules are
  described in free text; 33 of its IV datasets link to no simulation that gives an infusion time. Midazolam needs
  `MetabolizationLiverMicrosomes_MM` and `SpecificBinding` placement and per-kg doses. The Itraconazole snapshot holds
  4 compounds.
- **The CPF can carry an individual's changed physiology** (`indiv.<PK-Sim path>` records bound to the Individual
  building block). Every subject the CPF is simulated in gets them as path-addressed `Individuals[].Parameters`,
  the structure the OSP reference snapshots use. The published Dapagliflozin model sets the gallbladder's EHC
  continuous fraction to 1 and fits the colon's effective surface-area factors. Without these the regenerated
  model would not be the published one.

### Fixed — "create a new project" failed where the user could not see why, and showed made-up data
Found by driving the wizard end to end in a browser (new Playwright flows, below).
- **The wizard's own starting CPF could not start a campaign.** The pre-filled Aciclovir set had
  `elim.renal.gfr_fraction` with no engine binding. Since S0 began refusing unplaceable clearance parameters, it
  was refused at S0. Fixed: the template carries the GFR binding (tested).
- **Errors vanished.** The web client parsed every answer as a success envelope. A FastAPI refusal (`{"detail": …}`,
  e.g. 422) had neither `data` nor `errors`, so the wizard did nothing and said nothing. A proxy failure was reported
  as "Could not reach the API" with no status. Every write now reports the API's own reason (validation errors
  field by field), or the HTTP status with a hint when the web server cannot reach the API. MAP-signature and
  campaign-start refusals carry their reason too. The Run button checked `if (!signed)` on what is now a result
  object; corrected.
- **"Showing sample data — the API is not reachable" was wrong and hid the real state.** Any failed read (including
  a 404 for a campaign whose monitor record had not been written yet, right after Start) made the page show a
  hard-coded sample campaign/project with that banner. Pages now show the actual problem (unreachable with its
  cause, the API's error, or "not recorded yet — this page checks again"), never sample data. The sample data are
  deleted (`lib/fixtures.ts` → `lib/types.ts`, types only).
- **No pre-made demo project.** The sidebar's hard-coded "Example project: Aciclovir FIH" links and the server's
  first-run seeding of that project (`deploy/server/run_modeler.sh`, `deploy/dev/read-root/`) are removed. Every
  project is created in the wizard.

### Added — project templates from the API, and a monitor that says what produced the numbers
- **`GET /api/v1/templates`, `GET /api/v1/templates/{id}`** serve the wizard's starting points. The first is the
  published **Dapagliflozin OSP model with its real clinical data** (imported live from the reference snapshot;
  `MODELER_REFERENCE_MODELS_DIR` overrides the location). The second is the Aciclovir illustrative quick check,
  labelled "not clinical data". The wizard gains a step 0 "Start from", shows the CPF and the studies as tables (JSON
  still editable), lists the source datasets not used and why, and lets the modeler set the M15 model risk.
- **Every campaign records its engine** (`engine`: PK-Sim / software fixture / injected, from
  `MODELER_ENGINE_COMMAND`). A campaign run on `stub_engine.py` or `analytical_engine.py` carries a red "Not a PBPK
  result" banner on the monitor, so a software-fixture run cannot be mistaken for model evidence (CLAUDE.md rule).
- **Playwright acceptance flows** (`apps/web/e2e`, `npm --prefix apps/web run e2e`). The config starts its own API
  and web server on a fresh data directory. On the stub engine by default the flows prove the software path only:
  wizard from the published model → CPF → 40 studies → MAP (S0 → S7) → signature → campaign → monitor. The same
  flow runs on PK-Sim with `E2E_ENGINE_COMMAND`. Three more flows: the API not answering, the API refusing a step,
  and an unknown campaign. On the stub engine the Dapagliflozin campaign passes S0 and escalates at S1 (the
  synthetic curve is 13 000-fold off), which is the gate working. No fit is tried because the imported published
  CPF has no fit policies.

### Fixed — the study upload dropped who was studied
- **`POST /projects/{id}/studies` silently discarded `population_type` and `special_population`**, although the MAP's
  split reads them. A renal-impairment or patient study was therefore classified as healthy and could train the
  healthy-volunteer model (MS-01 §3.2 forbids it). The upload now keeps both, so such a study is classified SPECIAL.

### Docs
- **Added `CHANGELOG.md` (this file) and `CLAUDE.md`.** There was no change log and the continuation doc was 50
  commits out of date; project context lived only in commit messages and a private assistant memory, so it was lost
  whenever the session or AI model changed. `CLAUDE.md` is loaded into every Claude Code session, which is what makes
  the "record every change" rule stick.
- **Rewrote `docs/CONTINUATION_PACKAGE.md` §4 to the truth**, with a pipeline-coverage table (S0–S7).

### Fixed — the pipeline now runs S0 → S5 (plan item 1.1, plus defects found running it on PK-Sim)
Proven on real PK-Sim (the engine image under Docker on the Mac): an Aciclovir campaign started from a wrong renal
clearance (GFR fraction 0.4) runs S0 → S5 and completes — S1 baseline fails (AUC 2.06-fold), the fit recovers
GFR fraction 1.272, the fitted model passes in the same round (AUC 1.008-fold); S2/S3 are skipped (no oral or
fed study, MS-01 §6.2/§6.7), S4 re-validates the fitted model and passes, S5 is recorded as not achievable (no
external study). The data are the example's illustrative IV profile, not clinical data — real-data proof is Phase 4.
- **R0 — the UI only ever asked for S0 → S1.** The Run button and the new-project wizard hard-coded
  `stages: ["S0", "S1"]`, and `campaign:prepare` defaulted to S0 → S2. Both now run every stage; a stage with no
  data is skipped with its reason instead of being left out.
- **R1 — S4 and S5 now simulate.** The MAP gives every internal study an S4 scenario and every external study of a
  core class (IV, oral fasted, fed, multiple dose, MR, other) an S5 scenario. DDI / PGX / special-population studies
  are named in S5's notes as validating their S6 application (MS-01 §3.3 rule 4).
- **R2 — validation mode.** S4/S5 simulate the final CPF once and judge it; they never diagnose or fit. A failure
  escalates with the MS-01 §6.6 choices (record a limitation and continue, or stop) — no blind retry.
- **A stage with nothing to simulate is SKIPPED with its documented reason** (new stage status), instead of running
  an empty round and escalating. New `plan_stage` activity, used by both the single-node runner and Temporal.
- **S5 judges fasted and fed as separate groups** (MS-01 §8): acceptance comparisons carry a group.
- **R13 (raised to critical) — a fit is judged in the round it happens.** The round simulated the CPF *before* the
  fit and evaluated that, so a successful fit was scored on stale values, its action counted as tried, and the stage
  could run out of actions and escalate although the fit worked. The round now re-simulates the fitted CPF
  (`phase="postfit"`) and judges that. Same change in the Temporal workflow.
- **The campaign's fit could never start** (found on PK-Sim). The fit spec named its models after the round's
  snapshot file, but the engine names exported models after its input (`snapshot-<simulation>.pkml`). Now one
  constant, `ROUND_SNAPSHOT_INPUT`, drives both.
- **Fitting a dimensionless parameter crashed the engine** (found on PK-Sim, GFR fraction). A null unit came back
  from `run_job.R`'s re-serialisation as `{}`; the spec now omits it and `run_pi.R` only accepts a real string.
- **Observed data are converted to the engine's units before any comparison** (new `pbpk_domain.units`). The
  gate compared predicted AUC/Cmax (µmol/l, minutes) with observed values in whatever the study reported — an
  upload in hours or ng/ml was judged 60-fold or MW-fold off. `campaign:prepare` now converts every profile to
  minutes and µmol/l (unknown units → 422), and the fit declares the molar dimension (it declared µmol/l data as
  a mass concentration).
- **The prediction is reduced over the observed window at both ends** (`ObservedPK.t_first`): an IV study sampled
  from 5 min, or a steady-state study sampled over its last interval, was scored against area never measured.
- **Each simulation covers its study's sampling window** (was a fixed 24 h, truncating longer studies).
- **Multiple-dose studies can be simulated**: `dosing_interval_h` / `n_doses` on the study, mapped to the PK-Sim
  schedules found in the OSP reference snapshots only (`DI_24`, `DI_12_12`). Verified on PK-Sim: q12h × 4 gives
  exactly 4 doses, q24h × 3 gives 3 (PK-Sim doses while t < End time).
- **A validation stage simulates every study it can and names the rest** ("NOT SIMULATED: …"); one study the
  builder cannot place yet (e.g. a tablet) no longer stops the others from being judged.
- Monitor rounds no longer say "improved" for a round that merely tried an action; they say passed / no pass, and
  carry per-study and per-group results. Stage notes (skip reasons, studies not simulated) are shown under the stage
  rail. Each stage keeps its own goodness-of-fit plot (`gofByStage`).

### Fixed — enzymes and transporters now act on PK-Sim (plan item 1.2, R4)
- **Every enzyme-cleared drug had been simulated with zero metabolic clearance.** The CPF build never gave the
  individual an expression profile for the enzymes its processes name, so the processes had no protein to act on.
  Proven on PK-Sim: a UGT1A9-cleared compound (CLspec 0.4 l/µmol/min) built the old way gives AUC(0–48 h) 1242.7
  µmol·min/l — identical to no clearance at all. The run looked valid; nothing warned.
- **Expression library harvested from the OSP reference models** (`pbpk_domain/data/expression_library.json`,
  `scripts/harvest_expression_library.py`): 16 proteins (CYP3A4, CYP1A1, UGT1A1/1A4/1A9/2B7, AADAC, P-gp, ABCB1,
  ABCG2, OATP1B1, …) copied verbatim with their per-organ relative expression, half-lives, transport directions and
  ontogeny, each with its source model recorded. A profile needs those tables — with only a reference concentration
  every organ's relative expression is zero and the process still does nothing.
- The CPF build gives every subject the harvested profile of every process protein. Same compound, now: AUC 112.8
  µmol·min/l, t½ 8.5 h — the enzyme clears the drug.
- **S0 refuses a CPF whose process names a protein with no harvested profile** (MS-01 §S0), instead of running a
  model that silently eliminates nothing. Build notes name each profile's source.
- **Transporter direction was being dropped.** The builder wrote `TransporterType`; the snapshot key (per the
  engine-harvested catalog) is `TransportType`, so PK-Sim ignored it and defaulted the direction — an influx
  transporter such as OATP1B1 would have been modelled wrongly. The test fixture that "confirmed" the old key was
  hand-written; corrected.

### Fixed — tablets and the S3 formulation stage (plan item 1.3, R5), and a unit defect in every fit
- **Tablets and capsules can be simulated.** CPF formulations (`form.{name}.type` Weibull | Dissolved,
  `form.{name}.weibull.{t50,shape,lag}`, MS-01 §2.2) become PK-Sim `Formulation_Tablet_Weibull` /
  `Formulation_Dissolved`; lag defaults to 0 min and "use as suspension" to 1, as in every published OSP tablet
  (Dapagliflozin, Midazolam, Itraconazole). A study names its formulation (`formulation_name`); an unnamed one in a
  CPF with exactly one formulation uses it, and the build note says so. Anything else is a named build error.
- **S2 / S3 routing follows MS-01**: an immediate-release solid trains S2 when it dissolves rapidly (its formulation
  is Dissolved) or when no solution study exists (§6.3, the tablet is the S2 reference with its in-vitro Weibull
  fixed); otherwise it trains S3 and S2 uses the solution studies only (§4 S2).
- **S3 can fit the formulation**: Weibull t50 / shape are fitted per simulation at the paths harvested from PK-Sim
  (`Events|<protocol>|<formulation>|Dissolution time (50% dissolved)`, `…|Dissolution shape`, `…|Lag time`), only in
  the simulations that use that formulation, within the CPF fit policy ([0.5×, 2×] of the in-vitro fit).
- **diag-rules 0.2 → 0.3 (UNVERIFIED)**: S3 release-rate rules (too slow / too fast → fit t50, then shape) — the
  MS-01 §4 S3 sub-loop; before this a formulation stage could only escalate. Their evidence is new: `release_slow`
  / `release_fast` = Cmax off with AUC in limits, tmax not contradicting. The absorption evidence's "tmax > 1.25-fold"
  cannot fire at ordinary sampling density (seen on PK-Sim: Cmax 0.80-fold, sampled tmax 90 vs 102 min), so reusing
  it left the rule dead. Flagged for SME review with the rest of the ruleset.
- **Every fit of a parameter whose CPF unit differs from PK-Sim's base unit was stored wrongly** (found on PK-Sim,
  known-truth campaign). `ospsuite.parameteridentification` 2.2.0 drives the optimiser in the parameter's *base*
  unit whatever `PIParameters$unit` says, and setting the unit does not convert the bounds. An intestinal
  permeability "fitted in cm/min" was really fitted in dm/min: the engine found 2.79e-6 dm/min (≈ the truth), we
  stored 2.79e-6 cm/min — 10× too low — and the "fitted" model got worse. `run_pi.R` now converts bounds and start
  to the base unit and estimates, SDs and CIs back to the CPF's unit. logP, GFR fraction, CLspec and t50 share
  their units with PK-Sim, which is why earlier fits looked right; permeabilities and solubility did not.
- **Fit starts run in parallel on the single-node runner**, as many at once as the multistart plan assumed (cores ÷
  simulations per start), capped by the machine's CPUs; `MODELER_FIT_WORKERS` overrides it (e.g. on a laptop's
  Docker engine). They ran one after another, multiplying a planned fit's time by up to 32.

### Added — S6 prediction and S7 report & reproducible package (plan Phase 2, R8/R9)
- **S6 and S7 are campaign stages** (`CAMPAIGN_STAGES` S0–S7; MAP budget split per MS-01 §7: S6 20 %, S7 7 %).
- **Signature gate before S6** (MS-01 §4 S6 "runs only after S4 and S5 are signed", decision D5): after S5 the
  campaign pauses as `AWAITING_SIGNATURE` with a review-inbox item; a signed **approve** (new decision, API and web)
  resumes it into S6/S7.
- **S6** re-simulates the internal studies from the final CPF, then per study runs a local sensitivity analysis over
  every FITTED/PREDICTED parameter (engine `sensitivity`) and propagates the fitted parameters' SD — 200 draws,
  log-normal for log-scaled parameters, truncated to the fit bounds — through an engine `batch` to 5/50/95 %
  intervals of AUC and Cmax (`pbpk_domain.campaign.prediction`). Parameter correlations are not propagated yet.
  Application templates (DDI, paediatric, organ impairment, VBE) remain the next phase (T-31).
- **The engine's batch task converts run values to base units** (`options.parameter_units`), the same trap as the fit.
- **S7** assembles the data bundle from evidence each stage persists as it finishes (`evidence/<stage>.json`: rounds,
  final metrics, notes, the judged snapshot and outputs — so the package survives the pause for signature): final
  CPF, MAP, observed data, S4/S5 snapshots and result tables, every fit's specs and results, S6. Every bundled
  snapshot is **re-run on a fresh engine process** and compared at 1e-6; the MAR (`report/campaign_mar.py`, ICH M15
  Appendix 2 structure, every number an evidence reference) records the verdict and the data-bundle hash; the
  package zip (manifest + `rerun_all.R`) is written **only if reproduction passed** (D13), else S7 escalates.
- **DOCX and PDF/A-2b without TeX**: pandoc 3.9 (`pypandoc-binary`) and Typst 0.15 (`typst`, PDF/A-2b with embedded
  fonts) are pinned in `uv.lock`, so the report renderer is reproducible; the LaTeX route remains as a fallback.
- **S0 refuses a CPF with an elimination/transport parameter the builder cannot place** (no engine binding).
  Found when a finished report listed "NOT PLACED IN THE MODEL: elim.renal.gfr_fraction" yet concluded the model
  met its tier — the simulation had no renal clearance at all. Test fixtures that carried the unbound parameter fixed.
- Verified on the server's PK-Sim with the known-truth campaign (before the S0 and renderer changes): S0 → S5, the
  signature, S6 and S7 completed in 264 s; S6 ranked GFR fraction first for AUC (−0.84) and the tablet t50 for its
  Cmax (−0.35); S7 reproduced 7 of 7 result tables and released a 147-file package. The prediction intervals were
  degenerate because noise-free synthetic data identify the parameters almost exactly (SD 4e-12) — the draws were
  applied; real clinical data (Phase 4) will give real intervals.

- **Package API and monitor** — `GET /campaigns/{id}/package` (verdict, hashes, available artifacts; no server
  paths) and `GET /campaigns/{id}/package/{package.zip|mar.pdf|mar.docx|mar.md}`. The zip is refused with 409 while
  reproduction has not passed (D13); only files inside the object store are served; project membership applies. The
  campaign monitor shows the S6 sensitivity/intervals and a Report & package card with the downloads. Verified in
  the live tool on the server: a known-truth S0 → S7 campaign (266 s) whose PDF/A-2b report, DOCX and 152-entry zip
  download through the tool.

### Known gap — Phase 2 still open
- The Temporal workflow does not run S6/S7 (it marks them SKIPPED with that reason); the single-node runner does.
- The M15 table's model influence and decision consequence are not captured by the MAP yet; the report says so.

### Verified — the whole S0 → S5 loop on real PK-Sim, by known-truth recovery (2026-09-24, server engine)
A "true" Aciclovir model (IV, oral solution, a Weibull tablet) was simulated on PK-Sim to produce the observed
profiles; the campaign started from a wrong model — intestinal permeability 10× too low, tablet release (t50) 55
instead of 30 min — at **high** model risk (1.25-fold, every study within). It completed in 201 s: S2 fitted
permeability back to 4e-05 cm/min (the truth, exactly), S3 fitted t50 back to 30 min (exactly), S4 re-validated
every trained study (VPC 100 % each), S5 judged two external tablets, a solution and a multiple-dose study as the
fasted group, all within 1.25-fold. Synthetic data: this proves the machinery, not clinical validity (Phase 4).

### Added — visual predictive check, the MS-01 population gate (plan item 1.5, R7)
- After a stage's PK gate passes at S1, S2 and S4, each study's exported model is run across a 100-individual
  virtual population built from the study's demographics (population, sex, age range; seed recorded); the engine
  returns the 5/50/95 % band (`vpc.json`, new `options.vpc` on the `population` task). The gate needs ≥ 80 % of the
  observed points inside the 5–95 % band (MS-01 S1). A failure escalates as `vpc_coverage_below_80` — no fit action
  addresses variability. Coverage and band are stored per study with each round, for the monitor's plot.
- A study's VPC age range is its reported one (`Demographics.age_min/age_max`), else the mean ± 10 years (adults
  from 18) — a MAP default the modeler signs, flagged for SME review like every MS-01 [SME] value.
- The VPC **gates S1 and S2** (MS-01 §4: S1 gate, S2 "as S1"); at **S4 it is reported, not gated** — MS-01 lists
  "VPC per study" in the S4 report while its gate is the PK acceptance table. (First implemented as gating S4 too;
  corrected when a known-truth run escalated at S4 on a VPC of 70 %.)
- Same step in the Temporal workflow (`prepare_vpc_jobs` / `evaluate_vpc` activities).

### Added — fitted parameters keep their precision
- The CPF record of a fitted parameter now carries its **SD, CV and 95 % CI** (`ParameterRecord.uncertainty`, from
  the engine's Hessian CI estimate, in the CPF's unit). They were dropped after the fit; MS-01 S4 needs them in the
  parameter table and S6 needs them to propagate uncertainty. CPF JSON Schema regenerated.

### Changed — diagnostics ruleset `diag-rules` 0.1 → 0.2 (UNVERIFIED; change approved by the project owner)
- **R6 — the clearance rule offers renal clearance before logP**: `fit elim.renal.gfr_fraction`, then
  `fit elim.renal.ts_clspec`, then `fit phys.logp`. Under 0.1 a renally cleared compound with wrong renal clearance
  could only be "fixed" by bending logP — seen on PK-Sim, where it moved AUC from 2.06- to 1.89-fold by distorting
  distribution. MS-01 §2.2's condition (renal fits only with urine/fe data) is enforced per compound by the CPF fit
  policy. Awaiting SME sign-off (T-30).

### Infra
- **Mac Docker engine fallback** (`deploy/dev/docker_engine.sh`): runs a job in the linux/amd64 engine image with
  the job directory mounted at the same path, so `EngineRunner` works unchanged. Golden round trip passes in the
  container (~21 s). A development fallback — not the qualified, digest-pinned production image.
- **`deploy/dev/deploy_to_server.sh`**: rsync + dependencies + web build + restart, as one command.
- **Server redeployed** to the current build (it was running a 2026-09-20 build), autostart installed, engine gate
  (`golden_roundtrip.R`, `verify_run_round.sh`) passes there. Tailscale installed in userspace mode, awaiting login.

### Known gap — found while fixing the above
- `modeler_intake` keeps its own unit tables; they should use `pbpk_domain.units` so there is one source.

### Known gap — diagnosed 2026-09-24 (the reason every campaign stopped at S1)
Tracked as R1–R13 in the plan. The critical ones:
- **R1 — S4 and S5 never simulated anything.** `campaign/map.py::_scenarios` only created scenarios for INTERNAL
  studies in three classes (IV → S1, oral fasted → S2, fed → S3). Nothing was ever tagged S4, and EXTERNAL studies
  were skipped outright, so internal and external validation had no work and escalated.
- **R2 — the runner had no validation mode**; every stage was treated as a fit loop.
- **R4 — enzyme-cleared drugs were never metabolised on real PK-Sim.** The CPF build never attached expression
  profiles to the individual, so CYP/UGT processes had no enzyme to act on.
- **R5 — only oral solutions/suspensions could be built**; tablets and capsules raised, and S3 did not exist.
- **R8/R9 — S6 and S7 were not part of the pipeline** even though sensitivity, population, parameter CIs, the MAR
  generator and the reproducibility bundle all exist and are engine-verified.
- **R11 — the 2026-09-24 case studies were not PBPK.** With the engine host down they ran on a one-compartment
  analytical stand-in. Their four defect findings stand; their numbers are not simulation results.

---

## 2026-09-24

### Added
- **Twelve end-to-end case studies** driven through the real API (`deploy/dev/case_studies/`), evidence in
  `reports/case-studies/` (gitignored). *Ran on the analytical stand-in, not PK-Sim — see Known gap R11.* (84533d3)
- **Analytical stand-in engine** `deploy/dev/analytical_engine.py`: one-compartment model driven by the CPF's real
  values, with a parameter-identification task. A software fixture only; never a simulation result. (84533d3)
- **Review-inbox decisions act on the campaign**: `escalation:resolve` endpoint + `resolve_escalation()` apply
  retry / accept best / abort to a stopped single-node campaign, signing from the token's step-up (no password on the
  wire) *before* applying anything. (310c1a2)
- **Server lifecycle scripts in the repo** (`deploy/server/`): run / stop / status, shared `_env.sh`, and
  `install_autostart.sh` (no-root `@reboot` + 5-minute watchdog that respects a deliberate stop). They previously
  existed only on the server. (122ba94)
- **Sudo-optional Tailscale setup** `deploy/server/setup_tailscale.sh` (userspace mode when there is no root).
  (afcb76d, ee1b407)
- **Interface redesign** as a dark instrument (IBM Plex; teal = predicted, amber = observed) and a **fold-error
  gauge** showing predicted/observed on a log scale against the ICH M15 tier band. (0854342)

### Fixed
- **AUC compared over mismatched time windows** — prediction reduced over the simulation window, observation over
  its sampling window. A perfect model of a slowly eliminated drug was reported at +101% error and escalated.
  Predictions are now reduced over the observed window (`ObservedPK.t_last`). *Would have produced false failures on
  real submissions.* (84533d3)
- **Fit candidates not checked against the compound** — a renal drug spent a round fitting a hepatic enzyme it does
  not have. Candidates are now filtered to real, bounded, stage-permitted parameters with an engine path. (84533d3)
- **An engine crash hung the campaign at RUNNING** with the error hidden; stage failures are now recorded with the
  actual message. (84533d3)
- **Missing input file raised** where every caller expects graceful degradation. (84533d3)
- **The model silently had no clearance** — a process parameter without an `engine_binding` was dropped by the
  builder with no warning. Now reported as "NOT PLACED IN THE MODEL". (3aca992)
- **Snapshot integrity check always failed through `EngineRunner`** — the build hashed the canonical snapshot but the
  runner hashed the file bytes. Masked because server tests called `run_job.R` directly. (ba0a9ab)
- Tailscale version lookup parsed a key that does not exist; now uses the `latest` redirect. (ee1b407)

### Changed
- **Real runnable example** replaces the static Example-A mock screens; one-click "Run campaign"; real data intake
  (CSV upload, column mapping); studies merge by id instead of being replaced. (9c1be08)
- Example CPF calibrated: bound GFR clearance, MS-01 fit policies, real pKa records. (3aca992)
- All three escalation decisions now require a signature, matching `decision_options()`. (310c1a2)

### Docs
- Moved `SESSION_HANDOFF.md` into `docs/`. (999c8ca)

## 2026-09-20 → 2026-09-23

### Added
- **Guided "New project" wizard**: project → CPF → studies → MAP & sign → run, opening the live monitor. (ba0a9ab)
- **Single entry point** — the web app proxies `/api/*` to the backend: one URL, no CORS. (d4017db)
- **Deployed on the server as one tool**: Node via nvm, web + API + engine behind `http://<server>:3000`.

## 2026-09-19

### Added
- **Single-node execution mode (no Docker / no Temporal needed)**: `LocalExecutor` runs the MS-01 loop in-process
  using the same activities as the Temporal path; `FileReadStore`/`FileWriteStore` persistence seam;
  `MODELER_EXECUTION_BACKEND=local|temporal`. (3e48fa4)
- **Create-project write API** and `campaign:prepare` (MAP + NCA-derived observed PK). (b4a3526)
- **Web app** (T-26/27/28) with live read APIs for projects, CPF, campaigns, escalations, proposals.
  (817c14d, fdeaf91, acfffa7)
- **T-09** population, sensitivity and batch engine tasks, verified on the engine. (bca33e8)
- **T-24** MAR generation and rendering (DOCX / PDF-A via pandoc, Markdown fallback). (01ff5fa)
- **T-12** engine image CI, qualification gate, registration record. (c26c923)
- **T-20** agent run persistence, token/cost budgets, provider-failure handling. (5003e6f)
- **T-23** `rerun_all.R` generation; byte-exact reproduction verified on the engine. (fe2cc69)
- **T-32** validation pack generator (URS/FS, RTM, OQ evidence). (467335f)

## 2026-09-18

### Added
- **Fit loop, end to end** — CPF → PK-Sim parameter paths harvested from the engine; PI spec built; estimates
  applied to a new CPF version; strategist bounds threaded through. Verified on the engine: PI recovered GFR fraction
  1.0 from a 0.4 start. (cf4a843, 712b8ac, 83a1571, a13e746, d2ac368)
- **T-11** observed-data coverage: molar units, urine/feces fractions, geometric statistics, LLOQ. (c444720)
- **T-17** escalations, deviations and signed decisions API. (47322d0)
- **T-23 core** reproducibility gate and submission bundle. (7f36c8e)
- **T-06** Keycloak OIDC authentication and step-up signatures. (101e605)
- Auth-guarded campaign / run APIs; `GET /runs/{id}/results`. (8281c65, 9e438b8)
- **T-25** CI pipeline and requirement trace matrix. (bc5835a)

## 2026-09-17

### Added
- **T-18** deterministic NCA. (6997975)
- **Round loop wired**: build → simulate on the engine → evaluate against the tier gate → diagnose → choose action.
  (27516d6, d1386ff, 0588bd0, 2abd0a9, 902158f)
- **T-14** diagnostics ruleset; **T-15** strategist agent. (0588bd0, 2abd0a9)

### Fixed
- **`ValueOrigin.Source` enum** — a raw CPF label made PK-Sim *silently drop the simulation*. Every CPF-built
  campaign would have produced nothing. Caught by the first on-engine smoke. (6de102d)
- `run_job.R` matched the wrong result-CSV names for multi-simulation snapshots. (8e8ef8b)

## 2026-09-16

### Added
- Repository under git. Platform scaffold, engine verified on Linux (T-01), catalog harvest (T-02), CPF (T-03),
  study split (T-04). (ab20736)
- **T-10** builder coverage: Michaelis-Menten metabolism, transporters, inhibition, induction, specific binding,
  multiple-dose protocols, meal events. (0afed52, a201367)
- **T-13** campaign workflows; **T-05** campaign persistence with RLS and append-only audit; **T-07** object store;
  **T-08** results ingestion; **T-09** cancellation; **T-16** MAP generator.
  (fdb5f0d, e103d6f, c32831b, 17a98b1, dec21ab, 7b4ce26, 147f6d5)

### Docs
- Continuation package recorded T-10/T-13 progress — its last update until 2026-09-24. (cdc8a7a)

---

## Sessions and AI models
Work on this repository has been done across several sessions and Claude models. When the model or session changes,
record it here so a reader knows which context produced which work.

| Date | Model (from commit trailers) | What it did |
|---|---|---|
| 2026-09-16 → 20 | Claude Opus 4.8 | Planning (MS-01, engineering plan), T-01 → T-32 core, web app, single-node execution, create-project flow |
| 2026-09-23 → 24 | Claude Opus 5 | Real example, calibration, review decisions, server scripts, autostart, case studies, redesign |
| 2026-09-24 → | Claude Opus 5.5 | Diagnosis of the S1 stop; S0 → S7 plan and execution; this change log |
| 2026-09-24 (cloud session) | Claude Opus 5.5 | Phase 4 reference importer (Dapagliflozin real data), wizard templates, e2e flow. No PK-Sim in this container (CRAN / r-universe blocked): engine proof stays on the server |
