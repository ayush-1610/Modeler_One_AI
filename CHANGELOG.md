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

### Changed — reference checks run on the server; the PK-Sim workflow is manual
- `.github/workflows/reference-models.yml` no longer runs on push (only "Run workflow" by hand): the reference set runs
  on the server's PK-Sim (`bash deploy/reference/run_all.sh`), and the repository goes private. Last full run on
  Actions (run 35, da2b2c8): every round-trip pair identical, within 1e-3 of the peak, or labelled by design;
  Ketoconazole's parent-only curves 90–100 % of the published (2 % before its compound settings).

### Fixed — compound settings beyond MW and halogens; the water of administrations given together (run 33)
- A compound's other parameters in the published snapshot are imported by their PK-Sim name and unit (`cmpd.<name>`,
  bound to the Compound building block) and written back. OSP Ketoconazole sets "Enable supersaturation" 1, "Treat
  precipitated drug as" 0, its aqueous diffusion coefficient and drug density; without them every Ketoconazole curve
  was ~2 % of the published one (run 33, parent-only and system round trips).
- A dose given as several administrations at 0 h (OSP Verapamil Ratiopharm 1989: two tablets, 3.5 ml/kg each) is
  given with their combined water (7 ml/kg); run 33 had the right dose but 3.5 ml/kg (Cmax +14 %).
- Run 33 also: Verapamil system 69 of 75 identical (60 in run 26).

### Changed — round-trip summaries separate solver-level residuals from real differences
- The headline now also counts pairs off by more than 1e-6 but at most 1e-3 of the peak with AUC and Cmax within
  1e-3 ("solver level"), and the pairs labelled by design. Acceptance (T-10) is unchanged: identical means 1e-6.
  Run 33 (PK-Sim, all fixes to 9768b96): Voriconazole 2/2, Clarithromycin 17/17, Digoxin 44/44 identical; the
  Itraconazole system's day-1 studies from 40–50 % off to ≤ 4e-5; the Verapamil system as-is campaign passed S2, S4
  and S5 on the published clinical data and waits at the S6 signature. Residuals of 1e-6 to 4e-4 remain unexplained.

### Fixed — administrations at the same moment are one dose (found by run 26)
- A published protocol that gives a dose as several administrations at one moment (OSP Verapamil Ratiopharm 1989:
  two 40 mg tablets, one schema each, both at 0 h) was read as its first administration: the study's product got half
  the dose (AUC ratio 0.45 in run 26). The dose is now the total given at each moment, when every moment gives the
  same.

### Fixed — water per dose; every meal of the simulated regimen (found by run 26)
- The published simulations set the water per application: OSP Itraconazole Barone 1993 gives 2.82 ml/kg with the
  first dose and 3.5 after. The water is read per dose (for a product given as several bins, from each dose's first
  application); one volume for all doses stays `water_ml_per_kg`, a different first dose becomes a regimen phase
  (`DosePhase.water_ml_per_kg`, written on that phase's schema item).
- A day-1 profile of a multiple-dose study is simulated with the whole regimen but kept only the meals of its
  sampled window: OSP Itraconazole Hardin 1988 day 1 had one breakfast of 14. Every meal within the simulated regimen
  is now given. Run 26: the day-1 studies were 40–50 % off over the simulated span, their day-15 twins identical.

### Fixed — the water given with an oral dose is the published one (found by run 26)
- Every oral protocol was built with PK-Sim's default "Volume of water/body weight" (3.5 ml/kg). The OSP models set
  others: Verapamil 2 ml/kg, Itraconazole 1.37 and 2.82, Dabigatran 2, Ketoconazole 0. The importer reads the
  published simulation's value (else its protocol's) into `StudyRecord.water_ml_per_kg`, and the build writes it on
  every dosed compound's protocol. Run 26: Verapamil Maeda 2011 and Blume 1989 were ~10 % off with every compared
  parameter identical (the protocol is not part of that comparison).

### Added — the Ketoconazole model system
- A metabolite the published simulations form (their `MetaboliteName`) is a member and a formation link even when the
  building block names none (OSP Ketoconazole: n-deacetyl-ketoconazole → n-deacetyl-n-hydroxy-ketoconazole by FMO3);
  the metabolite most selecting simulations form is taken. A cellular permeability of 0 (a published input for that
  metabolite) is accepted.
- CI round trip and example project for the Ketoconazole system. The parent-only Ketoconazole round trip is ~35×
  off by design (its metabolites inhibit its CYP3A4 / P-gp clearance); its template says so.

### Fixed — older snapshots' expression, simulation calculation methods and solver settings (found by run 26)
- A snapshot written before PK-Sim 10 (OSP Voriconazole) keeps each individual's enzymes under "Molecules" and has no
  ExpressionProfiles documents; the importer read none and the builder used the library's CYP2C19 profile (gut
  relative expression 0.013 instead of 0.324). Each such enzyme is now converted to a profile document: the harvested
  library profile of the same protein (paths, localization) with the individual's relative expressions, reference
  concentration, half-lives and ontogeny. Other proteins or localizations are left unconverted.
- A compound's calculation methods are taken from what most of its published simulations use. OSP Voriconazole's
  simulations all use "Poulin and Theil", its compound building block says "PK-Sim Standard" (fat partition
  coefficient 1.6 vs 20.6 in run 26). Recorded in the import notes.
- A published simulation's own solver settings (OSP Dabigatran Härtter 2012: RelTol 1e-09) are carried by its study
  (`StudyRecord.solver`) and written to its simulation.
- Run 26 also confirmed on PK-Sim: Clarithromycin 17 of 17 identical (the suspension fix), Alfentanil 13 of 15
  (Kharasch 2012 fixed), Digoxin 44 of 44.

### Added — model your own compound from the wizard; a user guide
- New starting point "Your own compound": the parameters the S0 gate requires (molecular weight, logP, pKa or
  neutral, fraction unbound, solubility, and total hepatic clearance bound as PK-Sim's LiverClearance "Plasma
  clearance", harvested from OSP Digoxin), each marked missing. The CPF table takes each value and its source
  directly; saving it opens the project's CSV data intake. Before, every project had to start from a published model.
- Fixed in the S0 gate: a `phys.pka.neutral` record marked missing (no value, no source) satisfied the pKa
  requirement. MS-01 §2.2 asks for a documented statement, so it now needs a value and a source like the others.
- `docs/USING_THE_TOOL.md`: deploying, loading the examples, what a campaign does, the package, your own compound.

### Added — the S7 package carries the PK-Sim project file of every bundled simulation
- S7 converts every bundled snapshot to its PK-Sim project (`pksim/<stem>.pksim5`) on the engine's
  `convert_to_project` task (PK-Sim loads the snapshot and saves the project; proven in every CI run's golden step)
  and puts it in `package.zip` beside the snapshot, results, CPF, MAP, fits and MAR: the file a reviewer opens in
  PK-Sim. A conversion that fails is named on the package (`project_notes`); the release still depends only on the
  reproduction check (D13). The package view lists the projects.
- `deploy/server/seed_examples.sh`: loads every worked example into the running tool on the server and runs its
  campaigns on PK-Sim in the background (refuses to start below 5 GB free).
- CI: the Trivy scan ran from `aquasecurity/trivy-action@0.28.0`, a tag withdrawn upstream, so the job could not
  start; it now runs Aqua's official image with the same settings (report-only, as before).

### Fixed — each project keeps its own CPF; system projects list every compound; readable study ids
- The file store kept one CPF per compound for the whole tenant (`cpf/<compound>.json`): two projects on the same
  drug (an as-published and a refit Dapagliflozin; the Itraconazole model and its system) overwrote each other's
  parameters. CPFs are now kept per project (`cpf/<project>/<compound>.json`); a project without its own still reads
  one stored the old way, so existing deployments keep working.
- `PUT /projects/{id}/system` adds every compound of the system to the project (the project page listed only the
  parent: Esomeprazole without R-omeprazole).
- A dataset whose "Study Id" is a bare number or a word (OSP Omeprazole: 2, "Median"; Ketoconazole: 9) is named after
  its data sheet or its own name: `regardh1990-2`, `boyce-2012-9-female-ketoconazole` instead of `2-0`, `9-0`.
- Added `deploy/showcase/seed_examples.py`: loads every example (the published OSP models with their clinical data,
  refit twins for Dapagliflozin and Rifampicin, the four model systems, the illustrative Aciclovir check) into the
  running tool through the API, and runs their campaigns a few at a time on the engine.

### Fixed — a tablet's "Use as suspension" setting is imported (found by run 24)
- Weibull formulations were always built with "Use as suspension" = 1, the value in the Dapagliflozin, Midazolam and
  Itraconazole tablets. OSP Clarithromycin's tablet, Voriconazole's and Dabigatran's capsule set 0. The value is now
  imported (`form.{name}.weibull.suspension`) and built; it is never a fit target.
- Run 24: every oral Clarithromycin curve was 1.2–1.6 % of the peak off (16 of 17 pairs), with every compared
  parameter identical.

### Fixed — DDI arms and paediatric studies are no longer fitted (found by run 24)
- A dataset named "with Perpetrator (X)" or "after Perpetrator (X)" (not placebo) is a DDI arm: `co_medication = X`
  (OSP Midazolam Greenblatt 2003 grapefruit juice, Reitman 2011 rifampicin; Digoxin Reitman 2011, Gurley 2008b
  echinacea). A dataset of the perpetrator itself (OSP Itraconazole's own plasma) is not. Run 24 fitted the
  grapefruit-juice arm in Midazolam S3.
- A study whose individual is under 18 is `special_population = pediatric` (OSP Itraconazole Abdel-Rahman 2007,
  four age groups). Run 24 fitted the 12–16 y group in S1 of the Itraconazole system.
- MS-01's classification is unchanged: these are data labels the importer now reads. The round trip still builds the
  paediatric studies in the published child individual; the campaign classes them SPECIAL.

### Changed — reference logs end with a recap
- `deploy/reference/run_reference.py` prints the headline and every round-trip pair outside 1e-6 again at the end of
  the log: the parameter lists run long, and log tails missed the result.

### Fixed — a model value the published simulation leaves at its default stays default
- The model's simulation-level values (`sim.*`, `sim[route].*`) were applied to every simulation of the route. A
  published simulation that does not set one keeps PK-Sim's default. The study now names those paths
  (`StudyRecord.default_simulation_values`), and the build leaves them out of that simulation only
  (`SimulationSpec.default_parameters`).
- Found by run 24: OSP Alfentanil's Kharasch 2012 oral simulation keeps the default gut-wall permeabilities (22 paths),
  and our curve was off (AUC ratio 0.32). Also affects Metformin Caille 1993 fed (3 paths).
- Impact: round-trip fidelity only; a campaign fit of these values is unchanged for the other studies.

### Fixed — a process the published simulation switches off stays off (poor metabolisers)
- A study whose published simulation leaves out processes the model's other simulations use now carries them as
  `inactive_processes` (per compound; the importer compares each simulation's process selection with the one most of
  them share). The builder leaves them out of that simulation only. OSP Omeprazole's poor-metaboliser studies (Uno
  2007, FDA esomeprazole) lose CYP2C19 on both enantiomers; OSP Metformin's Morrissey 2016 keeps only glomerular
  filtration. Before, both were built with every process: the PM curves ran on EM clearance.
- Such a study is marked with a genotype ("<compound> without <processes>"), so the campaign classes it PGX and keeps
  it out of S1–S3 (MS-01 §3.3 rule 4, unchanged). The round trip plans it as an ordinary scenario, because it checks
  the build against the published simulation. Omeprazole's system round trip goes from 9 to 14 pairs.
- Carried through `StudyRecord`, `MapScenario`, the study upload API and `SimulationSpec.inactive_processes`.
  Impact: needs a PK-Sim round trip to confirm (Actions is blocked; `deploy/reference/run_all.sh omeprazole`).

### Added — try it: 12 published models in the wizard; reference checks on the server; the plan to the goal
- The create-project wizard offers every single-compound OSP library model that imports S0-ready (Rifampicin,
  Midazolam, Alfentanil, Alprazolam, Clarithromycin, Digoxin, Metformin, Raltegravir, Ketoconazole, Voriconazole,
  Itraconazole) beside Dapagliflozin, each with its real clinical studies; descriptions name only the processes the
  model imports. A project takes the compound name the published model uses (`ketoconazole`, `Voriconazole1`).
- `deploy/reference/run_all.sh`: the CI reference matrix (read from the workflow) on this machine's PK-Sim, N tasks
  at a time, with a summary — for the server while GitHub Actions cannot start jobs.
- Plan: `docs/plans/2026-09-24-remaining-to-goal.md` — what remains, in order, with estimates and the decisions
  needed.

### Added — every meal as given: timing, template and values
- A fed study got one meal, the MAP's template, at its dose. The published simulations give meals before or after the
  dose and one per dosing day: Midazolam Bornemann 1986 dosed 1 h before a high-fat breakfast (a fasted study with a
  meal 1 h later; 0.015 of the peak off on run 14 and unlabelled) and 1 h after one; Itraconazole a breakfast with
  each daily dose plus standard meals (up to 32 meals; day-15 fed pairs were 0.98 off); Metformin meals 7.5-15 min
  before the dose and a 300 / 500 kcal standard meal (changed template values).
- `StudyRecord.meals` / `Meal` (time after the first dose, negative before it; PK-Sim template; name; changed values)
  carried by the API upload and the MAP scenario. Round build: one meal event per distinct meal with its values
  (`MealEventSpec.parameters`), each at its time (`SimulationSpec.event_times`); a meal before the dose starts the
  simulation and the dose follows (protocol start time), as the published simulations do. Empty: a fed study's meal is
  the MAP template at the dose, as before.
- Importer: the meals of the linked published simulation, relative to its first dose, within the study's sampled
  window; the data keep the meal's clock when the meal comes first. A fasted study whose first meal is at or before
  the dose contradicts its report and gets none. Also fixed: the time shift of a dataset recorded in minutes was
  subtracted in hours.

### Added — solubility and intestinal permeability per product and food state (owner-approved 2026-09-24)
- A published model can give a study's simulation another alternative of a compound property depending on the product
  given and the food state: OSP Itraconazole's solubility "Capsule fasted", "Capsule fed", "Solution fed" (default
  "Solution fasted"); OSP Ketoconazole's intestinal permeability "Fit fed" (default "Fit fasted"). One CPF value per
  property made every Itraconazole capsule and fed round trip differ (9 of 41 identical as a system).
- CPF: each non-default alternative's values are `<id>@<alternative>` records (`phys.solubility.ref@Capsule fed`,
  `phys.solubility.ref_ph@...`, `perm.intestinal@Fit fed`, same units as the default's) and `alt.select` (JSON) holds
  the rules {group, formulation, food, alternative}. `cpf.build.alternatives_for` picks, for an oral study, the rule
  for its CPF formulation (none when dissolved) and food state, else the rule for any formulation in that food state,
  else the default. IV studies use the default.
- Importer: per (formulation, food state) of the oral studies, the alternative most of their published simulations use
  becomes a rule; one alternative for every product of a food state becomes a single any-product rule. A study whose
  published simulation uses another alternative than the model selects is labelled (Ketoconazole Boyce 2010 (9) and
  Wire 2007 (94): named fasted, simulated with "Fit fed" in the published model). A pH-solubility-table alternative is
  named, not placed per product.
- Builder: `CompoundSpec.solubility_alternatives` / `intestinal_permeability_alternatives` are written after the
  default (IsDefault false, as published) and `SimulationSpec.alternatives` selects one per simulation; an unknown
  alternative is refused.
- Fitting: a fit of the default's value (`phys.solubility.ref`, `.ref_ph`, `perm.intestinal`) leaves out the studies
  whose simulation selects another alternative of that group; setting the value there would overwrite their
  alternative. The alternatives' own values are not fitted: MS-01 and diag-rules name only the default (a change
  there is SME-governed).
- Food state from the published simulation's name: when a dataset reports none, the importer used "fasted" unless the
  published simulation has a meal. OSP Ketoconazole's fed studies have no meal event (the model represents the fed
  state by "Fit fed") and all its datasets report no food state, so 16 fed studies were classed fasted. A simulation
  named with "fed" or "fasted" (as a word, not both) now gives the study that food state, with the reason in its
  reference (also Metformin's 8 fed studies, unchanged in outcome).
- Result (offline, on the regenerated snapshots): every Itraconazole study selects the solubility its published
  simulation uses (single compound and system); Ketoconazole 51 of 53 (the two above labelled). All 15 vendored models
  stay S0-ready. To be confirmed on PK-Sim when CI runners are available again.

### Fixed — the published model's own expression profiles, simulation values and formulations (run-14 round trips)
- **Expression profiles are imported verbatim.** The builder gave every protein the library's copy of its profile,
  harvested from another OSP model, plus only the numeric values that differed. The copies also differ in what is not
  a number, and in values the published profile leaves at the PK-Sim default: Clarithromycin's P-gp has no ontogeny
  where the library's copy has one (ontogeny factor 1e-14 in our model, oral curves 1-2 % off); Metformin leaves MATE1
  and OCT1 unexpressed in brain, muscle and colon where the library's copy expresses them (0 of 40 pairs identical);
  ABCB1 differs in transport type and localization in five models. Each profile of the published individual is now a
  CPF record `expr.profile.<molecule>` (the document as JSON, binding `ExpressionProfileDocument`), and a study's own
  published individual carries its profiles (`PublishedIndividual.profiles`); the builder uses them instead of the
  library's, and the `expr.*` values on top. The library stays the default for a CPF without them. Every
  regenerated profile checked (Clarithromycin, Metformin x28 individuals, Ketoconazole, Verapamil, Midazolam) equals
  the published one. The build report names the proteins given their own profile.
- **The majority simulation value is imported.** A compound value the simulations set with any disagreement was
  dropped: Metformin's brain cell permeability, 0.02 cm/min in 38 of 39 simulations, 0.023 in one. Now the value a
  strict majority of a route's setting simulations use (and at least half of the route's simulations) is imported;
  a tie is still named and not imported.
- **A simulation's own values are labelled.** A published simulation that sets compound values the model does not
  carry (a minority value) is labelled on its study as differing by design, naming the first path.
- **Dose counts of named DosingIntervals.** The label comparing doses now counts a published DI_12_12 / DI_24
  protocol (PK-Sim repeats while time < End time): Raltegravir's MD pairs "19 dose(s) as the study gave them; the
  published simulation gives 20", Kassahun 2007 (single dose) likewise; the study's own schedule is unchanged.
- **A liquid given a release model by the published model is simulated with it.** Raltegravir's granules in
  suspension (Rhee 2014) use "Weibull (granules)" in the published simulation; we dissolved them (AUC 2.3x). The study
  keeps its MS-01 class (suspension).
- **A later session of a named-interval simulation gets its schedule.** OSP Alfentanil "Kharasch 2011b IV 1 mg" is
  DI_24 to 48 h (two sessions); its "simultaneous" datasets start at 24.08 h and were simulated as one dose at 0 h (AUC
  0.51x on run 17). A dataset that starts after a named-interval protocol's second dose now takes its schedule; one
  sampled from 0 h stays single-dose (Raltegravir Kassahun 2007). A published profile entry whose value the CPF
  repeats keeps its value origin.
- Run 17 (8bf41e6), before the profile fix: Alfentanil 11/15 identical (all IV boluses 2e-8, oral with the oral-only
  gut-wall values 2e-7); the rest are the two sessions above and Kharasch 2012 oral in its own individual.
  Itraconazole as a system, as-is: S0 passes; S1 escalates on Abdel-Rahman 2007 12-16 y (published model vs
  clinical data, AUC 2.19x) in its own paediatric individual.
- Run 14 otherwise: Digoxin 38/39 identical (the other was the Kirch loading dose, now placed as phases);
  Raltegravir 14/19 (the rest labelled or fixed above); Itraconazole as a system 9/41 identical with the metabolites
  simulated, every solution-fasted pair within 2e-4, the capsule and fed pairs off because the published simulations
  select other solubility alternatives per formulation and food state (one alternative is imported; open question).

### Added — loading-dose and phased regimens (OSP Voriconazole: 0 -> 12 importable studies)
- A regimen whose doses differ or are unevenly spaced is now simulated as the published protocol writes it: one
  schema per phase (Start time, NumberOfRepetitions, TimeBetweenRepetitions) with one item at the phase's dose and,
  for an infusion, its own infusion time. New `StudyRecord.dose_phases` / `DosePhase` (start, dose, number of doses,
  interval, infusion time; `dose_mg` is the first dose), carried by the API upload and the MAP scenario; builder
  `DosePhaseSpec` on every protocol spec. Harvested shapes: Voriconazole "Purkin et al. 2003 B" (6 mg/kg IV bolus
  twice 12 h apart, then 3 mg/kg every 12 h from 24 h), "Purkin et al. 2003 A" (one dose, then every 12 h from 48 h),
  "Saari et al. vrz_oral" (400 mg twice, then 200 mg twice).
- Importer: a published schema protocol whose phases differ in dose or infusion time, or whose doses are not evenly
  spaced, becomes the study's phases. A dose the dataset reports must be the regimen's first dose or its total;
  otherwise the study is skipped with the reason. The published regimen must start at 0 h.
- Studies recovered: Voriconazole 0 -> 12 (S0-ready; its 10 Saari 2006 subjects are dosed with midazolam and stay DDI
  arms, not simulated), Metformin 41 -> 48 (779.9 mg then 584.9 mg), Digoxin +3 (twice daily for 2 days, then daily),
  Alprazolam +2 (Kroboth 1988: 1 mg over 2 min, then 0.576 mg over 8 h; Fleishaker 1994), Rifampicin +1 (Chattopadhyay
  2018). For every one checked (Purkin A/B, Kroboth, Ding, Johne) each administration (time, dose, unit, route,
  infusion time) is identical to the published protocol. They were skipped before, or (Kroboth) simulated as repeated
  identical doses in the version before 8bf41e6.
- A model system splits every phase by the product's dose fractions.
- Diagnostics leave a phased study out of the dose-normalised AUC trend (its first dose is not its exposure dose).
- A binned product given in phases is refused (no published protocol does it).
- Voriconazole snapshot vendored (commit f482aa1); round-trip CI job.

### Fixed — round-trip defects found on PK-Sim (CI run 14): Dabigatran oral 2-fold, Alfentanil/Alprazolam/Midazolam
- **A process can run on another molecule of the individual than it names.** The OSP Dabigatran simulations select
  DabiEtex's `ABCB1-FIT` transport on the individual's `P-gp`, which has its own modified profile ("new ref. conc.").
  We selected it on `ABCB1` with the library's ABCB1 profile, so every oral curve was ~2-fold off although all 10 640
  parameters compared equal (the paths differ by molecule name, so the diff could not see it). The importer now records
  a selection the compound's own simulations run elsewhere, by majority, as a categorical CPF record
  `molecule.<selection>` (binding `ProcessSelection`); the builder selects the process and interactions on that
  molecule and expresses it instead. A simulation that maps it differently is labelled (Ketoconazole's DDI arms).
- **IV bolus.** Published `IntravenousBolus` protocols (Start time and InputDose, no infusion time; harvested from
  Alfentanil, Midazolam, Digoxin, Metformin, Verapamil) were rejected as "IV with no infusion time": every Alfentanil
  IV study was skipped. New `IntravenousBolusProtocolSpec`; an `iv_bolus` study without an infusion time is built as
  a bolus (an infusion study without one still raises). Alfentanil 7 -> 18 studies, Midazolam +16 IV studies,
  Metformin +1.
- **Simulation values are decided per route.** Alfentanil sets its gut-wall permeabilities in 3 of 4 oral simulations
  and none of 8 IV ones, so the all-simulation majority dropped them (22 parameters off in every oral round trip).
  Alprazolam sets its PI permeability in all IV simulations and no oral one, and the majority applied it to the oral
  ones too (0.046 instead of the compound's 0.76 cm/min). Now: a value common to every route stays `sim.<path>`;
  otherwise a route gets `sim[oral].<path>` / `sim[iv].<path>` (`EngineBinding.route`), applied only to its
  simulations. CPF JSON schema regenerated.
- **An unset plasma protein binding partner stays unset.** Alprazolam and all Verapamil compounds leave it unset
  (PK-Sim stores 2); we wrote "Albumin" (stored 1). The CPF records `bind.partner = unspecified` and the builder omits
  the field, as the published snapshot does; no enum value is guessed.
- **Schedules of mixed or loading-dose protocols.** A schedule taken from a published protocol now counts only the
  study's own route: Midazolam's IV Mikus 2017 study was simulated as two IV doses (the protocol gives oral 4 mg at 0 h
  and IV 2 mg at 6 h); now one IV dose, and both arms labelled "the published simulation also gives an oral /
  intravenous dose". A protocol whose administrations differ in dose or infusion time (Alprazolam Kroboth 1988, 1 mg
  over 2 min then 0.576 mg over 8 h; Digoxin Kirch 1986 loading doses) was simulated as repeated identical doses
  (2-fold off); such studies are now skipped with the reason. A binned product's bins at one moment count as one
  administration.
- A model system's import now labels its studies with the link's feedback (alternatives, selection mappings) as the
  single-compound import does.
- Run 14 results otherwise: every parameter identical for Dapagliflozin, Rifampicin, Midazolam; remaining curve
  differences are labelled by design or solver noise (<= 2e-5 of the peak at 250-500 mg Dapagliflozin).

### Added — particle dissolution and binned products (OSP Ketoconazole: 5 -> 53 importable studies)
- `Formulation_Particles` (Noyes-Whitney, monodisperse), harvested from the Ketoconazole model: the unstirred water
  layer thickness (mm), the size distribution type (only 0, monodisperse, is placed; another is named), the mean
  particle radius (converted to µm; published in mm or µm). CPF `form.{name}.type = Particles`,
  `form.{name}.particles.{thickness,radius,distribution}`; builder `ParticleFormulationSpec`.
- Binned products: a tablet given as several particle-size bins at once ("PD_tablet_3Bins_B1..B3": 99.0 / 0.90 /
  0.10 % of the dose). CPF `form.{product}.type = ParticleBins` with `form.{product}.bins` (each bin and its mass
  fraction, from the published protocol, 12 digits: the published splits differ in the 7th and each is kept). The
  protocol is written as published: one schema item per bin keyed by its formulation, the water with the first only,
  one repetition 0 h apart for a single dose; the simulation selects every bin (Key = Name). A multiple-dose regimen
  becomes schema repetitions. A study linked to a binned protocol never falls back to its first bin alone.
- A "solution" the published model gives as a particle formulation (Ketoconazole's 8 nm PD_solution, dissolution
  still limited by solubility) is simulated with it; other solutions stay dissolved.
- Importer: a binned protocol's dose is the sum of its bins at the same moment; an unreported formulation is
  classified from the published formulation's name; a dataset whose molecule matches the compound on letters only is
  the parent's ("voriconazole" for Voriconazole1). A dose that is not reported, where the published protocol gives a
  loading dose, is named as such (Voriconazole's own studies); loading-dose regimens are not placed yet.
- Ketoconazole snapshot vendored; round-trip CI job. Library: 21 of 24 importable models S0-ready as single
  compounds (plus Dabigatran as a system); Warfarin (no compartment, racemic data) and Voriconazole (loading doses)
  remain named gaps.

### Added — campaigns on a model system (phase 1 wiring)
- API: `PUT /projects/{id}/system` stores the system's links (`SystemLinks`: roles, formation, products, observers,
  analytes) next to each compound's CPF, refusing it until every compound's CPF is there. `campaign:prepare` on a
  project with a system requires a parent as the fitted compound, converts each study's observed data with its
  analyte's molecular weight, stages `system.json` (URI and hash in the response, `model_system_sha256` in the MAP),
  and names the studies it cannot evaluate yet (`not_evaluated`: a mass-concentration sum such as Dabigatran's `SUM`,
  or a molar sum of compounds with different molecular weights).
- MAP scenarios carry the analyte's output path and `gated`: only the fitted parent's plasma enters the acceptance
  gate, the fit and the VPC; metabolite and sum studies are evaluated on their own curve and reported beside the gate
  (owner decision 3). A fit or validation stage whose studies are all reported analytes is SKIPPED with that reason
  (Verapamil's IV data are racemic sums), not escalated.
- Orchestrator: `system_uri` travels campaign -> stage -> round; the round build uses the system with the parent's
  current (fitted) CPF; S0 checks every compound; evaluation reads each study on its analyte's output from the
  engine bundle (unit-checked; a missing output is a finding); the S7 bundle includes `cpf/system.json`.
- `run_reference.py campaign <Drug> --system`; CI jobs for the Verapamil and Itraconazole systems as published.
- Fixed: `@activity.defn(name="diagnose_round")` had been left on the `_off` helper by an earlier edit in this
  session, so the Temporal worker registered the helper under that name; a test now guards the registration.

### Added — model systems, phase 1 step 4 (engine): every selected output in the result bundle
- `run_job.R` keeps each peripheral-venous output a simulation selects (every compound's plasma, the sum observers)
  under `profiles[<sim>].outputs[<path>]` with its own unit (a mass-sum observer reports mass concentration); the
  first compound's plasma stays the top-level curve, so existing readers are unchanged. Columns are matched exactly
  (`<path> [<unit>]`); a selected output without a column is a warning in the engine log. The engine image must be
  rebuilt (CI builds it per job).
- Still to do for campaigns on a system: store the `ModelSystem` with the project (API), carry the analyte's output
  path in the MAP scenario, and evaluate each study on its analyte's curve (report only for non-parent analytes, owner
  decision 3).

### Added — model systems, phase 1 step 3: building and round-tripping systems
- Builder: a simulation holds several compounds (`SimulationSpec.co_compounds`, each dosed by its own protocol or only
  formed); a process forming a metabolite carries `Metabolite` and is selected with `MetaboliteName`; published
  `ObserverSets` are emitted verbatim and selected; outputs are every compound's plasma plus the analytes' paths.
- `build_from_system`: every compound from its own CPF, formation set on the forming process, all compounds'
  proteins expressed, the individual from the CPF carrying it, each compound's `sim.*` values where it takes part.
- Round build: a study's product becomes one protocol per dosed compound at dose x fraction (Verapamil 80 mg TID ->
  2 x 37.03 mg), the metabolites they form are simulated with them, and the sum observers whose compounds are present
  are computed.
- `system_roundtrip_inputs` / `run_reference.py roundtrip <Drug> --system`: each pair compared on its study's analyte at
  the same output path on both sides (`reference_compare.R` reads the pair's `output`). CI jobs for Verapamil,
  Omeprazole, Dabigatran and Itraconazole.
- Fixed: a study's own individual now gets its own expression-profile categories for every protein (Omeprazole's
  Japanese individual reused "Healthy", which carries the main individual's CPF values, and the build refused it).

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

### Added — P5 model plan: the canvas (D1, D2, D3), live validator, A5, MAP from plan, signature (T-50)
- **ModelPlan** (`modeler_project.plan`, MODEL_PLAN/main): starts as the MS-01 default computed exactly as today
  (`split_studies`, the MAP's own training-stage rule, the stage plan's fit candidates resolved on CPF v1, budgets);
  each study's role (S1 / S2 / S3 train, S5 external, S6 application, supportive), fit choices, structure (objective,
  context of use, model risk, food effect, planned applications, from the brief), A5 rationales and proposals,
  acknowledged warnings and the canvas layout. A person's change carries a reason and is **userLocked**: rebasing on
  new inputs or a structure change moves only unlocked placements; A5 cannot touch a locked one.
- **Live validator** (MS-01 §3.3 rules 1, 3, 4, 5; class ↔ training stage; profile needed to train; core vs applied
  studies; fit stages and bounds; reasons; real data). Errors block; warnings block until acknowledged with a reason
  and then become MAP limitations. A drop is validated (dry run) before the person confirms it.
- **MAP from plan** (`map_from_plan`): the plan's placements as the split, its fits as the campaign CPF's fit policies,
  its changes and acknowledged warnings in the MAP's rationale and limitations, through `generate_map` unchanged (one
  public helper added to `campaign/map.py`: `training_stages`). With no change it equals `generate_map` (content hash).
- **Agent A5** (`modeler_agents.planning_agent`): explains every assignment and proposes departures with reasons;
  code refuses a proposal on a person's choice or one that breaks a rule; the person accepts or rejects each in the diff.
- **Sign** (`POST /plan:sign`, role modeler-reviewer = MIDD lead, D-07): refused while anything is open; the MAP is
  generated, signed from the token's step-up (meaning Approved, bound to its content hash), the campaign inputs are
  staged like `campaign:prepare` (campaign CPF, signed MAP, observed PK with origins), plan and MAP are approved (P5
  gate). Later changes are refused (a MAP deviation, D-14).
- Web `/projects/{id}/plan`: "Overall Data" side panel; D3 development and validation DAG with native HTML5 drag and
  drop onto nodes, the arrows into a stage and the training layer, node re-layout; D1 disposition and D2 absorption /
  formulation (read-mostly, D-13) with fit forms; the validator; the diff (MS-01 default → plan, A5 proposals); Approve
  and Sign; Run the campaign (P6). Integration plan and departures from plan §11.4 (no React Flow; new data placed by
  the default and marked; edge drops) in `docs/P5_PLAN_CANVAS.md`.
- Fixed: the P4 readiness read the brief's food-effect application by code (`APP-12`) against stored labels
  (`APP-12 food effect`), so food effect in question was never seen there; both P4 and P5 now read the code.
- **Known gap:** A5 has run only against a scripted model; MAP deviations after signature (D-14) and project-wide
  blinding of external values (D-15) are not built yet.

### Added — P4 model inputs: CPF v1 from accepted evidence, the study catalog, readiness (T-49)
- **CPF v1 is assembled, never typed** (`modeler_project.inputs`): one record per accepted evidence item, its value in
  the PK-Sim unit (logP in the builder's "Log Units"; pKa as `phys.pka.{acid|base}.i` from the stated conditions), its
  provenance carried into PK-Sim's `ValueOrigin`: Source and **Method** from the harvested enums only (Method values
  harvested from the OSP fixtures: InVitro, InVivo, Assumption, ParameterIdentification, Other, Unknown), the citation,
  locator, evidence source type and grade in the description, and the evidence id@version on the record
  (`Provenance.method`, `Provenance.evidence`, new optional fields; the builder writes Method only when set). Two
  accepted values for one parameter are named, never averaged or chosen between.
- **Process parameters are bound from the harvested table** (`pbpk_domain.cpf.process_bindings`, the OSP import's
  process table, now public as `PROCESS_PARAMETERS` / `PROCESS_FAMILY`): GFR fraction, total hepatic / renal clearance
  bind directly; a quantity carried by several process types (`CLspec/[Enzyme]` on `MetabolizationSpecific_FirstOrder`
  and `rCYP450_FirstOrder`) waits for a person's choice with a reason (`InputChoices`, also the formulation a solid
  study used and studies left out); a value in another unit than the builder places is named.
- **Study catalog** from the accepted datasets (origin kept; the mean / median series is the judged profile; PK-parameter
  and individual-only datasets are listed as not judged by the current campaign, with why).
- **Readiness** (READINESS/main): the S0 rules (completeness, placeable pathways, expression profiles, from
  `pbpk_domain`), formulations of solid studies, observed data to judge on, the real-data rule, the default MS-01 split,
  and a **software build of every planned simulation** (`build_stage_snapshot` on a default MAP). Loading the snapshots
  into PK-Sim (the engine dry run) needs the engine and is stated as not run here. P4 closes with a named acceptance
  when ready; `inputs:publish` hands CPF v1 and the judged studies (with their origin) to the campaign path.
- API `/projects/{id}/inputs` (`:assemble`, `/choices`, `:accept`, `:publish`); web `/projects/{id}/inputs` with tabs
  mirroring PK-Sim's building blocks (Compound, Formulations, Individuals, Simulation settings), Studies and Readiness;
  P3 and P4 pages refresh the phase rail after each action. Playwright covers the flow.
- **Known gap:** the engine dry run (PK-Sim loads every snapshot) runs on the server; `ValueOrigin.Method` in built
  snapshots is untested on PK-Sim until that run (the values are those of the OSP snapshots PK-Sim loads).

### Added — dissolution: canonical profiles, checks, f2 and the Weibull fit in PK-Sim's parameterization (T-48)
- **Profiles** (`pbpk_domain.dissolution`, `modeler_project.dissolution_register`): every client file's dissolution rows
  (template, or a confirmed mapping recipe) become canonical profiles, one per product × role × strength × batch ×
  apparatus × rpm × medium × pH × volume, with times in minutes, per-vessel values, mean, SD, CV, n and the source cells
  (DISSOLUTION artifacts, rebuilt idempotently; a profile repeated in a later file is replaced by it, and the replacement
  is noted).
- **Checks** say which release model the data support: Weibull; Dissolved (≥ 85 % within 15 min, MS-01 §4 S2); or
  Table, for release that plateaus well below complete (refused as a Weibull release model; table formulations are not
  placed by the builder yet). Means above 110 %, dissolution at t = 0 and falling means are flagged.
- **f2** for each TEST profile against the RLD / REFERENCE profile under the same conditions, computed only when its
  conditions hold (12 units, ≥ 3 points, one point after 85 %, CV ≤ 20 % early / ≤ 10 % later); otherwise the reasons;
  both ≥ 85 % within 15 min is similar without f2. Conditions are ruleset data: **new ruleset
  `rulesets/dissolution_similarity.yaml` (2026.1-draft, UNVERIFIED)**, owner-approved with the plan, awaiting SME sign-off.
- **Weibull fit**: deterministic least squares of t50 and shape (lag 0, as the OSP tablets have it), with standard
  errors and RMSE, in PK-Sim's parameterization (`Dissolution time (50% dissolved)` min, `Dissolution shape`, `Lag time`
  min, harvested from the OSP formulation catalog): fraction dissolved = 1 − exp(−ln 2 · ((t − lag)/t50)^shape). A person
  proposes a profile as a formulation's release model (D-12: the choice is a planning decision); its values become
  evidence (`form.<name>.type`, `form.<name>.weibull.t50/shape/lag`, extraction COMPUTED, grade C) to accept like any
  other. Evidence assessment now keeps flags that start with `unconfirmed`.
- Web: a Dissolution card on the L2b page (mean points with the fitted curve, t50 / shape ± SE, f2 verdicts with the
  ruleset version, propose-as-release-model). Playwright covers it.
- **Known gap:** the equation has not yet been compared with PK-Sim's own release curve on the engine (plan harvest
  rule; acceptance "within 1 %"): `ENGINE_CONFIRMED` is False and every proposed Weibull value carries the
  `unconfirmed` flag until that run is recorded on the server (e.g. the OSP Dapagliflozin IC tablet, t50 30 min, shape
  0.6, dissolved fraction over time against the equation).

### Added — P3 client data: the client-data template, sheet triage, agent A4 and reconciliation (T-47)
- **Client-data template** (`modeler_intake.client_template`, `GET /client-data/template.xlsx`, plan §10.2, D-11):
  README plus Studies, PK_Individual, PK_Summary, PK_Parameters, Dissolution, Product, Physchem_InVitro, Urine_Feces;
  one column list builds the download and reads the upload, so they cannot drift. Read with no AI: typed per column,
  enumerations checked, BLQ / `<LLOQ` kept as below-LLOQ, every value with its cell; a value that does not parse (a
  decimal comma, a unit in the cell), a value outside the allowed list, a missing required value, a renamed column are
  reported with their cell, never guessed.
- **Into the project** (`modeler_project.client_data`): each study arm becomes an observed dataset (origin CLIENT,
  extraction CELL; individual series per subject, summary series per statistic, NCA rows as reported PK; locator and
  the quoted row line point at the cells); each Physchem_InVitro row an evidence item quoted from its row and matched to
  its data-plan item (graded like any other evidence: a row that does not state a required condition is grade B).
  Dissolution, product and urine/feces rows are kept with their cells for T-48 / T-49. Doses and products that the
  brief does not mention are listed as questions (plan §10.1 step 7). The same bytes uploaded again change nothing.
- **Any other workbook** (`modeler_intake.triage`): each sheet is classified by the words of its first rows, quoting
  the deciding cell; undecided sheets go to **agent A4** (`modeler_agents.sheet_triage`), whose classification is
  recorded only when code finds its quoted header in that cell; a person can change any. Data are read from such a
  sheet only with a mapping recipe a person confirms (preview shows records, problems and open questions; confirming
  needs none). PDF, Word, CSV and Markdown files are stored as citable documents (owner, §3 #15).
- **Reconciliation** (plan §10.1 step 6): per client item of the data plan, delivered / partial (e.g. "2 of 3 promised
  media", from the proposal's own words) / missing / not available, and what arrived that the plan did not promise.
  The P3 gate (CLIENT_SUBMISSION/register, named approval) refuses while a required client item is missing; the person
  skips it as not available or switches on the literature cross-check (owner, R-07).
- Web: the L2b page `/projects/{id}/client-data` (template download, upload, per-file sheet triage with changes and
  reasons, problems with their cells, recipe mapping with preview, reconciliation with skip / cross-check, approval).
  Playwright: template downloaded, a filled template and a raw workbook uploaded, the decimal comma named at its cell,
  a sheet reclassified with a reason, the client dataset shown with origin client.
- **Known gap:** A4 has not run against a live provider yet (scripted model in tests); the data-mapping agent that
  drafts recipes still uses the older Anthropic client and is not wired to the L2b page (a person writes the recipe).

### Added — the real-data rule: only real observed data can sign off a model (T-46, plan §9.4, D-19)
- **Why:** a campaign could reach "passed" on the illustrative Aciclovir profile or on simulated data, and nothing on
  the monitor or in the MAR said so ("without any data we completed results").
- **Origin everywhere** (`pbpk_domain.data_origin`, shared with `modeler_project.datasets`): a study upload takes
  `origin` (CLIENT, LITERATURE, FIGURE_DIGITIZED, OSP_LIBRARY, SYNTHETIC, ILLUSTRATIVE; anything else is refused);
  `campaign:prepare` writes it into the observed PK and returns each study's origin and the studies with no observed
  data (not evaluable). The OSP templates and the showcase systems label their studies OSP_LIBRARY; the illustrative
  Aciclovir profile is relabelled ILLUSTRATIVE; the dev case studies (analytical stand-in data) SYNTHETIC. The CSV
  intake asks where the data come from (its example data is ILLUSTRATIVE).
- **Verdicts say what they rest on:** every round records how many judged studies were real and from which origin.
  A pass judged on data that is not real is shown as **"TEST ONLY: no real observed data"** (or "origin not recorded
  for n of m"), on the monitor (red banner, per-round "n of m real") and in the MAR round tables. A study without
  observed data is not evaluable and never counts.
- **The S4/S5 signature is refused** (API 409, before a signature is taken; the runner refuses too) when any stage
  S1–S5 judged a study that is synthetic, illustrative or of unrecorded origin, unless the project is
  **exploratory** (`POST /projects` `exploratory`; the wizard sets it for the illustrative example, the dev case
  studies and the showcase's illustrative check). Stopping the campaign stays possible.
- Impact: the local-runner tests now label their golden PK-Sim data SYNTHETIC in exploratory projects and expect
  TEST ONLY verdicts. A project created through the API without origins can no longer sign S4/S5 until each study's
  origin is recorded.
- **Known gap:** the Temporal backend (`escalation:decide`) does not apply the signature refusal yet; the local
  backend is what runs today. Accepted P2 datasets do not yet flow into the campaign's studies (T-49).

### Added — P2 observed data: datasets with their origin, agent A3 and the figure digitizer (T-45)
- **Observed datasets** (`modeler_project.datasets`, `dataset_register`): every clinical PK dataset is a DATASET
  artifact (proposed → accepted / rejected with a reason) carrying the study design, analyte and matrix, one or more
  series (statistic, error kind, n, values below LLOQ kept as such), reported PK parameters, the source page and
  locator, and its **origin** (CLIENT, LITERATURE, FIGURE_DIGITIZED, OSP_LIBRARY, SYNTHETIC, ILLUSTRATIVE). Code flags
  what a person must look at: too few time points, a profile that never declines, a reported AUC or Cmax that the
  profile's own NCA does not reproduce (> 20 %), a design that contradicts the data plan. Coverage now includes the
  data plan's observed-data needs.
- **Agent A3** (`modeler_agents.observed_data_agent`): extracts tables only when every row carries a verbatim quote
  from the stored page that contains that row's time and value (checked by code; one bad row refuses the whole
  table); figures become digitization requests for a person, never values the agent reads off a picture.
- **Digitizer** (`pbpk_domain.digitize`, web `Digitizer`): a person calibrates two references per axis (linear or
  log) on the PDF page or uploaded image and clicks the points; code maps pixels to values and records the click
  resolution. A digitized dataset can be accepted only after its overlay is approved by a named person. Uploads now
  take PNG / JPEG figures (stored as documents without text).
- API `/projects/{id}/datasets` (manual entry, `:digitize`, `:overlay`, `:decide`) and `evidence:research?agent=A3`;
  the L2a page gains an Observed data tab. Playwright: a drawn figure with markers at known values is digitized to
  within 1 % of the truth (1 h → 0.999 h / 100.3, 2 h → 1.996 h / 75.4, 4 h → 3.99 h / 50.5), approved and accepted.

### Added — P2 literature evidence: the evidence register and agent A2 (T-44)
- **Evidence register** (`modeler_project.evidence`, `evidence_register`): every value that may enter a model is an
  EVIDENCE artifact (proposed → accepted / rejected, each decision a new version with its reason) carrying the
  source (document page, locator, title, authors, year, DOI / PMID / URL), the verbatim quote, the conditions, the
  extraction method, the purpose and the provider. **Code** converts the stated value to the PK-Sim storage unit
  (`pbpk_domain.parameter_units`: plain unit changes only; CLint → CLspec is IVIVE and waits for a person) and grades
  it A–D (plan §8.4) with flags (value not in the quote, missing conditions, species mismatch, physically impossible
  value). Conflicts (> 2-fold between items of one parameter) are computed when read, shown side by side, never
  averaged. Coverage per data-plan item; the P2 gate closes only when every required literature item has accepted
  evidence or is recorded as not available (which changes the data plan, re-approved).
- **Agent A2** (`modeler_agents.evidence_agent`) on the provider-agnostic loop: searches Europe PMC, reads abstracts
  and open-access full texts (`modeler_agents.sources`: JATS → text with tables as rows) and the uploaded documents;
  every text is stored as a document before it can be cited, and every proposal is checked by code against exactly
  that text. Papers that are not open access become access requests that a person fulfils by uploading the PDF.
  Europe PMC is unreachable from the build container (tested with a mocked API); the server must reach it (D-17).
- API `/projects/{id}/evidence` (view, `:research`, manual proposal with a checked quote or a DOI / PMID / URL,
  `:decide`, `:approve`) and access-request fulfilment; data-plan items can be marked not available. Web: the L2a page
  (`/projects/{id}/evidence`) with proposals side by side per item, grades, flags, quotes and the source page; the
  Playwright flow covers the manual path.

### Added — the P1 data plan and the feasibility check (T-42 / T-43)
- **Requirement templates** (`pbpk_domain/requirements/*.yaml`, **UNVERIFIED**, version 2026.1-draft; owner-approved
  with the plan, awaiting SME sign-off): the core small-molecule template (MS-01 §2.2 parameters with their PK-Sim
  locations as MS-01 records them, the MS-01 §3.3 observed-data needs) and application templates for VBE, food
  effect, DDI, special populations and FIH. Items not in the harvested catalog are marked *to harvest*, never named.
- **The data plan** (`modeler_project.requirements`): derived deterministically from the brief. A condition is
  true, false or *undetermined* when the brief does not say (shown, never assumed); formulation items repeat per
  solid product. Each item's provider comes from a person's override (kept across re-derivations), else the
  proposal's own data-plan statement (its words shown), else the template default; a client item can be flagged for
  a literature cross-check (D-02). P2 searches exactly the literature items and the flagged client items.
- **The feasibility check** (`modeler_project.feasibility`, plan §7.5): each feature the brief needs (modality,
  routes, release types, expression profiles of the named proteins, clearance processes, populations,
  applications) as supported, limited, needs harvest, not supported or undetermined, with the route to support.
- API `/projects/{id}/requirements` (derive, view, override with a reason, approve); approving the brief derives the
  data plan at once, and the P1 gate closes when both are approved. Web: *Data plan* and *Feasibility* tabs on
  the P1 page; the Playwright flow covers them.

### Added — P0 initiate and the P1 Project Brief (T-41), with agent A1
- **Start a project from its technical proposal** (`/projects/start`, `POST /api/v1/projects:initiate`): the drug
  name, any context, and any number of PDF, Word, Markdown, text, CSV or Excel files. Each file is kept unchanged in
  the write-once blob store and read into quotable pages (`modeler_intake.documents`: pypdf, python-docx, openpyxl);
  a PDF without a text layer is reported as needing OCR, never guessed. The typed context is stored as a document
  too, so it can be cited like the proposal. The earlier wizard stays as the quick start.
- **The Project Brief** (`modeler_project.brief`, plan §6): one fixed schema for every project, sections A–J; every
  field is a record with status (entered, extracted, retrieved, computed, edited, confirmed, missing, not
  applicable), citations (document hash, page, verbatim quote, locator) and a confidence grade. Lists (products with
  TEST / RLD roles, scenarios, populations, the data plan of who provides what) are groups. Approval (D-07: a named
  "Reviewed" approval) is refused while a required field is missing or a question is open.
- **Agent A1** (`modeler_agents.proposal_intake`): proposes one field at a time; code accepts it only if the field
  and option exist, the number fits, and the quote is found verbatim on the cited page; rejections go back to the
  model with the reason. A field a person entered, edited, confirmed or marked not applicable is never overwritten
  (merged after the run, so edits made during it survive), and the M15 ratings and risk tier are never proposed.
  Live on Gemini (`gemini-3.1-flash-lite`) with a synthetic proposal: 36 fields accepted with verified quotes,
  2 rejected by the citation check. Agent runs and every step are kept per tenant (`FileRunStore`).
- **Drug identity**: PubChem lookup stored as a retrieved-record document (values quoted from exactly what PubChem
  returned) and an RDKit cross-check (formula, MW, InChIKey, halogen counts; a stated MW that disagrees with the
  structure raises a question). PubChem is blocked from the build container; it must be reachable from the server.
- **The L1 review page** (`/projects/{id}/brief`): the brief by section beside the source document, citation chips
  that open the page with the quote marked, inline edits that require a reason and can preview their impact, open
  questions, and what blocks approval. Playwright flow `e2e/start-project.spec.ts` (upload → brief → edit → history)
  passes against the real API.

### Added — agents on Gemini or Groq (decision D-16)
- **`modeler_agents.llm`**: one OpenAI-compatible client for the owner's two providers (Gemini, Groq) and a
  provider-agnostic tool loop: the model calls tools, deterministic handlers check and record what it proposes and
  answer it (rejections included), and every model turn and tool result goes to the agent run's step log. Retries
  with backoff on overload / rate limits (429, 5xx), no retry on a refusal. Selected by `MODELER_LLM_PROVIDER`
  (`gemini` | `groq` | unset = agents off, manual paths only); keys only from `GEMINI_API_KEY` / `GROQ_API_KEY`.
- **Gemini needs its thought signature echoed back**: a follow-up turn whose function call lost
  `extra_content.google.thought_signature` is refused (HTTP 400, seen live on 2026-10-05). The loop returns each
  call exactly as the provider sent it. Verified live on the owner's key: tool calls work on `gemini-flash-latest`,
  `gemini-3.5-flash`, `gemini-3.1-flash-lite`; the pro models are over the key's free quota and the free tier
  throttles quickly (429). Groq is unreachable from this build container (network policy) and untested live.
- **Server**: `deploy/server/_env.sh` sources `~/.modeler-secrets.env` (owner-only, outside the repository;
  template `deploy/server/modeler-secrets.env.example`). The keys pasted into the plan should be rotated.

### Added — project start-up pipeline, T-40: versioned artifacts, staleness, impact preview, audit chain
- **New workspace package `packages/project-model` (`modeler_project`)**, the spine every phase P0–P6 stores into
  (plan §13). An artifact version is immutable (written once), hashed, and names the exact upstream versions it was
  derived from. An edit creates the next version and needs a reason; everything made from the old version is
  reported **stale** with that reason (computed, never stored, so it cannot drift), never deleted or silently
  redone. Approvals bind a version's hash and are refused for stale or superseded versions.
- **Impact preview** (`POST /api/v1/projects/{id}/impact`): the field changes an edit would make and every
  artifact it would make stale, with the effect (re-derive, re-review, signature needed: a signed MAP is superseded
  and its campaigns invalidated) before anything is saved.
- **Single-node audit trail**: every commit and approval is appended to a per-tenant hash chain
  (`<root>/<tenant>/audit.jsonl`) with the same event shape and row hash as the Postgres `audit_events` table (a
  test pins identical hashes), so it migrates unchanged. Before this the single-node store kept no audit trail.
- API: `/projects/{id}/phases`, `/artifacts`, `/artifacts/{kind}/{id}` (+`?version=`), `/history`, `/audit`. Web:
  a **phase rail** (P0–P6 with status) on project pages and a **History** page (stale items with reasons, every
  version with its field changes and approvals, the audit trail and whether its chain verifies).

### Docs
- **The start-up pipeline plan is approved (owner, v0.2, 2026-10-05) and its build has started.** The owner answered
  D-03 (fold tiers + symmetric PE limits + the proposal's own criteria, all metrics gating; ruleset change
  owner-approved, stays UNVERIFIED) and D-16 (Gemini or Groq), and approved the rest as recommended; the plan's new
  §21 records how the build applies each answer, and the owner's P5 canvas specification is kept in §5.2. **Two API
  keys the owner pasted into the plan were removed before commit**: keys come only from host environment variables.
  The branch now also carries the parallel session's work (`main-1czavz`, merged so this build sits on the current
  importer, wizard and runner).
- **Draft plan: the project start-up pipeline (P0–P6) and a non-linear model backend**
  (`docs/plans/2026-09-25-project-startup-pipeline.md`, DRAFT, awaiting the owner's answers and approval; nothing
  built). Why: campaigns so far were judged against illustrative or self-simulated profiles, and every input (CPF,
  studies) is typed in as raw JSON with no document intake, literature work, client Excel handling, reviewable plan
  or way to edit an early decision later. The plan puts phase-gated, multi-agent intake in front of S0 (technical
  proposal → Project Brief, literature and client data with provenance, PK-Sim input pages, a three-diagram planning
  canvas), a rule that only real observed data can pass, and a non-linear backend (no-regression gate, a joint
  refinement stage SJ over all internal studies, external-validation feedback cycles, influence map). SJ and any
  criterion change are MS-01 / ruleset proposals that need explicit approval. Impact: none until approved; it does
  not replace the 2026-09-24 plan, whose Phase 4 continues.
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
| 2026-09-25 | per commit trailer (new session) | Plan for the project start-up pipeline (P0–P6) and the non-linear backend (draft, awaiting approval) |
