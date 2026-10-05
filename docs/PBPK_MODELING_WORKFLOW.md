# PBPK Modeling Standard MS-01: the automated model-development loop

**Status: FINALIZED for engineering (v1.0, 2026-09-15). Scientific defaults marked [SME] need PBPK lead sign-off before the first GxP project; they are data in versioned rulesets, not code.**

This document is the operating procedure the platform executes for every compound. It is embedded verbatim, with its
ruleset versions, in the Model Analysis Plan (MAP) of each project, so that what regulators read is what the machine ran.

Vocabulary used throughout:

| Term | Meaning here |
|---|---|
| CPF | Compound Parameter Framework: the single parameter set that every model of a compound is built from (§2) |
| Internal validation | Performance of the final parameter set on the studies that were used for fitting (also called training or development set) |
| External validation | Performance on held-out studies that were never used for fitting (test set), separately for fasted and fed state |
| Prediction | Simulation of a scenario for which no observed data were used at all (e.g. a DDI, a pediatric dose, a fed-state study when no fed parameter was fitted) |
| Stage | One step of the pipeline (§4). Each stage is a loop: build, run, evaluate, decide, adjust, repeat |
| Round | One pass through a stage loop |
| Gate | A pass/fail check against the acceptance ruleset that ends a loop |
| Escalation | The loop stops and a person is asked; the campaign is paused, never silently continued |

---

## 1. What is automatic and what is not

**Runs without intervention:** data classification and split (§3), every stage loop (§4), all fitting, all evaluation,
all diagnostics and the choice of the next adjustment within the permitted action set (§5), sensitivity and uncertainty
analysis, all application simulations, all tables and figures, report drafting, package export.

**Requires a person, and cannot be automated under ICH M15 / EMA PBPK guidance:**

| Point | Why |
|---|---|
| MAP signature before the first run | M15 §4.1: the plan is pre-defined |
| Exclusion of any observed data point or study | M15 §3: rationale for exclusion must be documented; the machine may flag, never exclude |
| Escalations (§4, per stage) | A stage exhausted its rounds or budget, or the permitted actions are exhausted |
| Acceptance of the final fitted parameter set | Human accountability for the model |
| Deviation from the MAP (e.g. changing the data split after a failed external validation) | M15 §4.2 |
| Signatures on evaluation, MAR and M15 table | 21 CFR Part 11 |

Everything else is a log entry, not a question.

---

## 2. Compound Parameter Framework (CPF)

Every model version of a compound is the CPF plus a system (individual or population) plus a scenario (protocol,
formulation, events, outputs). Stages never edit simulation-level overrides by hand; they update the CPF, and the
snapshot builder regenerates every simulation from it. This is what "all models on the same parameter framework" means
in code: one document, versioned, with provenance per parameter, from which IV, oral, fed, validation and application
models are all generated.

### 2.1 Parameter record

```json
{
  "id": "elim.hepatic.CYP3A4.clspec",
  "value": 0.5, "unit": "l/µmol/min",
  "status": "FITTED",                       // FIXED | FITTED | DERIVED | PREDICTED | MISSING
  "fitted_at_stage": "S1",
  "fit_policy": {"stage": ["S1", "S2"], "lower": 1e-4, "upper": 1e2, "scale": "log"},
  "plausibility": {"lower": 1e-4, "upper": 1e2, "source": "OSP library range [SME]"},
  "provenance": {"source_type": "ParameterIdentification", "run": "fit-S1-r2", "supersedes": "…"},
  "engine_binding": {"building_block": "Compound", "process": "MetabolizationSpecific_FirstOrder:CYP3A4", "parameter": "CLspec/[Enzyme]"}
}
```

### 2.2 Canonical parameters

Units are the units PK-Sim stores. "Fit stage" lists where a parameter may be fitted; anything not listed is never
fitted by the machine. Bounds are defaults [SME]; the MAP may narrow them, never widen them beyond plausibility.

| ID | PK-Sim location | Unit | Default source | Fit stage | Default bounds | Notes |
|---|---|---|---|---|---|---|
| `id.name`, `id.inchikey`, `id.smiles` | Compound name | – | client | never | – | Identity cross-checked with RDKit (MW from structure vs stated) |
| `phys.mw` | Compound `Molecular weight` | g/mol | structure | never | – | |
| `phys.halogens.{F,Cl,Br,I}` | Compound parameters `F`,`Cl`,`Br`,`I` | count | structure | never | – | Needed by PK-Sim's effective MW |
| `phys.logp` | Lipophilicity alternative `Lipophilicity` | Log Units | measured logP/logD7.4 or predicted | S1 (S2 if no IV) | measured ±1.5; predicted [−2, 7] | Drives partition coefficients |
| `phys.pka[i].value/type` | `PkaTypes` | – | measured | never | – | Predicted pKa flagged PREDICTED; escalate if it changes ionization at pH 6.5–7.4 |
| `phys.solubility.ref` + `phys.solubility.ref_ph` | Solubility alternative `Solubility at reference pH`, `Reference pH` | mg/ml | measured aqueous | S2 | [1×, 100×] measured (biorelevant ≥ aqueous) | Only for BCS II/IV or when absorption is dissolution-limited |
| `phys.solubility.table` | Solubility table alternative | mg/ml vs pH | measured | never | – | Preferred over single value when available |
| `bind.fu` | FractionUnbound `Fraction unbound (plasma, reference value)` | – | measured | never if measured; S1 if predicted | measured: fixed; predicted [0.5×, 2×] | |
| `bind.partner` | `PlasmaProteinBindingPartner` | Albumin/Glycoprotein/Unknown | measured | never | – | Affects special populations |
| `dist.bp_ratio` | `Blood/Plasma concentration ratio` | – | measured | never | – | Fixed when measured; else derived by PK-Sim |
| `dist.partition_method` | CalculationMethods (Rodgers & Rowland, Schmitt, PK-Sim Standard, Poulin & Theil, Berezhkovskiy) | enum | default Rodgers & Rowland | S1 (discrete branch) | – | Compared as separate branches, not fitted |
| `dist.permeability_method` | CalculationMethods (PK-Sim Standard, Charge dependent Schmitt, …) | enum | PK-Sim Standard | S1 (discrete branch) | – | |
| `perm.cellular` | Permeability alternative `Permeability` | cm/min | calculated | S1 only on permeability-limited diagnosis | [1e-7, 1e-1] | Rarely fitted |
| `perm.intestinal` | IntestinalPermeability `Specific intestinal permeability (transcellular)` | cm/min | calculated / Caco-2 IVIVC | S2 | [1e-7, 1e-2] | |
| `elim.hepatic.{enzyme}.clspec` | Process `MetabolizationSpecific_FirstOrder` `CLspec/[Enzyme]` | l/µmol/min | IVIVE from CLint (HLM/hepatocytes, fu,inc-corrected) | S1 (S2 if no IV) | [1e-4, 1e2] | One per enzyme with an expression profile |
| `elim.hepatic.{enzyme}.km/vmax` | Michaelis-Menten process | µmol/l, µmol/l/min | in vitro | S2 on nonlinearity | Km [0.1×, 10×] in vitro | Replaces clspec when saturation is detected |
| `elim.hepatic.total_cl` | `Total Hepatic Clearance` plasma clearance | ml/min/kg | clinical | S1 when no enzyme data | [0.01, 30] | Used when fm unknown; replaced by enzyme processes when data allow |
| `elim.fm.{enzyme}` | derived from processes | fraction | clinical DDI/PGx | never (constraint) | – | When known clinically, fitting keeps the ratio between enzyme clearances fixed |
| `elim.renal.gfr_fraction` | Process `GlomerularFiltration` `GFR fraction` | – | 1 (unbound filtration) | S1 with urine or fe data | [0, 3] | Fixed 1 when fe unknown |
| `elim.renal.ts_clspec` | `Kidney` tubular secretion `TSspec` | 1/min | – | S1 with urine data | [0, 10] | |
| `elim.biliary.cl` | `Biliary clearance` plasma clearance | ml/min/kg | mass balance | S1 with feces data | [0, 20] | |
| `elim.ehc_fraction` | Individual `Organism|Liver|EHC continuous fraction` | – | 1 (= no recycling delay) | S2 on secondary peaks | [0, 1] | |
| `transp.{transporter}.{km,vmax\|clspec}` | Transport process per organ | – | in vitro | S1/S2 only with clinical evidence | in vitro [0.1×, 10×] | |
| `form.{name}.type` | Formulation type (Dissolved, Weibull, Lint80, Particle dissolution, Table) | enum | dissolution data | S3 | – | |
| `form.{name}.weibull.t50/shape/lag` | Weibull parameters | min, –, min | fit to in vitro dissolution | S3 | in vivo [0.5×, 2×] of in vitro fit | |
| `form.{name}.particle.{d50,…}` | Particle dissolution parameters | µm | measured PSD | S3 (d50 only) | measured [0.5×, 2×] | |
| `food.fed_solubility_factor` | Fed-state solubility (or solubility table in FeSSIF) | – | measured FeSSIF/FaSSIF ratio | S3 fed | [1, 50] | Only fed-specific parameter the machine may fit |
| `ddi.perp.{enzyme}.ki_u`, `.kinact`, `.k_i`, `.ec50_u`, `.emax` | Inhibition / inactivation / induction processes | µmol/l, 1/min, – | in vitro, fu,inc-corrected | never by the machine | – | Fitting to clinical DDI data is a documented deviation with SME approval |
| `pd.*` | MoBi module parameters | – | clinical | S6 (PD sub-loop) | per module | Out of scope for MS-01 v1.0; see decision tree §6.9 |

**Completeness rule (S0 gate):** `phys.mw`, `phys.logp`, `phys.pka` (or documented "neutral"), `bind.fu`,
`phys.solubility.ref` and at least one elimination pathway (`elim.*` or `elim.hepatic.total_cl`) must be present with
provenance, otherwise the campaign does not start and the missing items go to the literature agent and the client.

### 2.3 System and scenario, aligned with the CPF

- **Individual**: age, weight, height (or BMI), sex, population, from the study's reported demographics (mean values for
  aggregated data; per subject for individual data). Ontogeny and expression profiles come from PK-Sim's database for
  every enzyme/transporter named in the CPF; missing profiles are an S0 failure.
- **Population** (validation VPCs, applications): PK-Sim population from the study's demographic ranges, n = 100 unless
  the MAP sets more; seed recorded.
- **Scenario**: protocol (dose, route, schedule), formulation reference into the CPF, events (meal template for fed),
  output schema (resolution 20 pts/h for 0–2 h, 4 pts/h after [SME]), outputs (plasma; urine/feces fractions when data
  exist).

---

## 3. Data catalog, classification and split

### 3.1 Study record (from the intake pipeline)

`study_id, reference/doc, population (healthy/patient, ethnicity, age range), n, design (SD/MD, crossover), route
(IV bolus/infusion, oral, other), dose, formulation (solution, IR tablet, capsule, MR, batch), food state (fasted/fed,
meal type), statistic (individual/mean±SD/geometric), time points, LLOQ, matrices (plasma, urine, feces), co-medication,
genotype, special population flag`.

### 3.2 Classification (deterministic)

| Class | Rule |
|---|---|
| IV-SD | route IV, single dose, healthy adults, no co-medication |
| PO-SOL-FASTED | oral solution/suspension, fasted, SD, healthy adults |
| PO-IR-FASTED | oral IR solid, fasted, SD |
| PO-FED | any oral, fed (meal documented) |
| PO-MD | multiple dose (any formulation) |
| PO-MR / PO-OTHER | modified-release or other |
| DDI, PGX, SPECIAL (pediatric, HI, RI, pregnancy, elderly), PRECLINICAL | as flagged |

Information score per study: `n × (number of time points) × w_stat` with `w_stat` = 1 for individual data, 0.6 for
mean±SD, 0.4 for mean only, +0.3 bonus for urine/feces data, +0.3 for dose-range coverage (multiple dose levels).

### 3.3 Split algorithm (runs before any fitting; the result is frozen in the MAP)

1. Fitting needs by stage: S1 needs ≥1 IV-SD; S2 needs ≥1 PO-SOL-FASTED or PO-IR-FASTED covering the lowest and highest
   fasted SD dose; S3 needs the dissolution data per formulation and, only if a fed parameter will be fitted, ≥1 PO-FED.
2. For each need, assign the highest-scoring eligible study to **INTERNAL**. If a class has exactly one study, it is
   INTERNAL, and external validation for that class is recorded as *not achievable, documented limitation*.
3. Everything else is **EXTERNAL**, and the external set must contain, whenever the class exists: ≥1 fasted study, ≥1
   fed study, ≥1 multiple-dose study, ≥1 other dose level, ≥1 other formulation. If an external category would be empty
   while INTERNAL holds ≥2 studies of that class, the lowest-scoring internal study of that class is moved to EXTERNAL.
4. DDI, PGX, SPECIAL and PRECLINICAL studies are never fitted in S1–S3; they are external validation for the
   corresponding application (S6) or, when no such application is planned, supportive.
5. **Fed data decision:** if the question of interest includes food effect, no fed parameter is fitted and *all* fed
   studies are EXTERNAL (fed exposure is predicted mechanistically from the meal model and measured fed solubility). If a
   fed parameter must be fitted (measured fed solubility unavailable and food effect is not itself the question), one
   fed study is INTERNAL and at least one other fed study must remain EXTERNAL, else the limitation is recorded.
6. The MAP records: the table of studies with class, score and assignment, and the sentences generated by rules 2–5.

---

## 4. Stage pipeline

Every stage loop has the same skeleton:

```
round = 0
while round < max_rounds and time_left(stage) > 0:
    round += 1
    build snapshot from CPF (+ round adjustments) → run internal studies → evaluate against gate
    if gate passes: record; exit loop (stage PASSED)
    diagnostics = diag-rules@v(evidence)              # deterministic, §5
    actions = permitted actions for this stage minus actions already tried
    next = strategist(diagnostics, actions)           # advisory agent; may only pick from `actions`
    if next is None: escalate("no permitted action left")
    apply next to CPF for the next round (fit spec, branch, or parameter policy change)
escalate("rounds/budget exhausted") with best round so far
```

Round records store: CPF before/after, fit specs (every start), results, metrics, diagnostics, chosen action and
rationale, engine manifest hashes, wall time. Defaults: `max_rounds = 4` per stage; time budgets from the campaign
budget (§7).

### S0 Readiness (no engine runs)

Inputs: CPF, study catalog. Checks: CPF completeness (§2.2), expression profiles present for every enzyme/transporter,
units validated, data split done, engine image qualified for the intended contexts, budget feasible (planner estimate
from the benchmark). Output: MAP sections *Data*, *Methods*, *Split*, *Technical criteria* filled; MAP signature
requested. **Gate: signature.**

### S1 IV modeling (distribution and elimination)

- Build: one simulation per INTERNAL IV study; individual from study demographics.
- Round 1: no fitting; evaluate. If the gate passes, IV stage is done with all parameters FIXED/PREDICTED.
- Fit candidates (ordered, max 3 per round): `elim.hepatic.*.clspec` (as one scaling factor when clinical fm is known,
  otherwise individually), `phys.logp`, `elim.renal.gfr_fraction` (only with urine/fe data), `perm.cellular` (only after
  a permeability-limited diagnosis), `bind.fu` (only if PREDICTED).
- Branches (discrete): partition method R&R → Schmitt → PK-Sim Standard → Poulin & Theil; permeability method.
  A branch is a separate round; the winner is the lowest objective that passes the gate, ties broken by fewer fitted
  parameters, then by the default method.
- Gate (internal, all INTERNAL IV studies): AUC and Cmax within tier limits (§8); t½ within 1.5-fold flagged, not
  blocking; VPC coverage ≥ 80 % of observed points inside the simulated 5–95 % band of a 100-individual population with
  the study demographics.
- Escalation reasons: rounds exhausted; fitted parameter at bound; correlation > 0.95 after fixing; CV > 50 % on a
  parameter the question of interest depends on.
- Output: CPF v(S1) with fitted values FITTED@S1; S1 report section (parameter table, GOF, residuals).

**No IV data (decision tree §6.1):** S1 becomes *prior distribution and clearance*: distribution from physchem with the
default method (no fit), clearance from IVIVE if in vitro CLint exists, else from oral data in S2 with `phys.logp` fixed
and clearance fitted jointly with absorption under the constraint that F ≤ 1 and the dose-normalized AUC across doses is
matched. The MAP states the identifiability risk and the M15 model risk may not be rated *low* for CL-dependent
questions.

### S2 Oral modeling, fasted (absorption)

- Build: S1 CPF fixed; one simulation per INTERNAL fasted oral study (solution/IR); formulation `Dissolved` for
  solutions; for IR solids in S2 use `Dissolved` if dissolution is > 85 % in 15 min (rapid), else the formulation is
  handled in S3 and S2 uses the solution studies only.
- Round 1: no fitting (predicted absorption from logP/MW-based permeability and measured solubility).
- Fit candidates (ordered, max 3): `perm.intestinal`, `phys.solubility.ref` (only if solubility-limited diagnosis or
  BCS II/IV), `elim.ehc_fraction` (only on secondary-peak diagnosis), `elim.hepatic.{enzyme}.km/vmax` (only on
  nonlinearity diagnosis, replacing clspec, Km bounded by in vitro), `elim.hepatic.*.clspec` (only when no IV data).
- Dose-range check: dose-normalized AUC across INTERNAL fasted doses; deviation > 25 % [SME] triggers the nonlinearity
  branch: decreasing with dose → solubility/dissolution-limited (fit solubility); increasing with dose → saturable
  first-pass (Michaelis-Menten).
- Multiple-dose check (if any INTERNAL PO-MD exists): simulate MD; accumulation ratio within tier limits; mismatch with
  SD fitting fine → flag *time-dependent clearance* → escalate (auto-induction is not fitted automatically).
- Gate: as S1, on INTERNAL fasted oral studies; additionally tmax within 2-fold or ±1 h (flag only).
- Output: CPF v(S2).

### S3 Formulation and fed state

- Formulation sub-loop, per formulation with dissolution data: fit Weibull (t50, shape, lag) or particle dissolution
  to the in vitro dissolution profiles (deterministic least squares, no engine); then simulate the fasted study of that
  formulation; allowed in vivo adjustment of t50/shape within [0.5×, 2×] of the in vitro fit (one round). Gate: fasted
  study of that formulation within tier limits.
- Fed sub-loop: meal event = PK-Sim template matching the study's meal (high-fat breakfast / standard meal [VERIFY
  template list from catalog harvest]); fed solubility = measured FeSSIF value if present (FIXED); otherwise, and only if
  the split assigned an INTERNAL fed study, fit `food.fed_solubility_factor` (max 1 parameter, 2 rounds). If no fed
  parameter may be fitted, S3-fed is a *prediction* and is reported under S5.
- Gate: fed INTERNAL study within tier limits; fed/fasted AUC and Cmax ratios within Guest-style limits (delta 2 [SME]).
- Output: CPF v(S3), formulation set, meal mapping.

### S4 Internal validation

Re-simulate every INTERNAL study from the final CPF (nothing fitted here). Produce the acceptance table (AUC, Cmax,
tmax, t½: predicted, observed, ratio, PE %, tier limit, verdict), GMFE per parameter, fraction within limits, GOF plots
(predicted vs observed, residuals vs time and vs prediction, linear and semi-log overlays), VPC per study, parameter
table with provenance and CI, correlation matrix of fitted parameters. **Gate:** all INTERNAL groups pass the tier
(`acceptance.evaluate`, role = fitting). Failure here means a stage passed on stale values (a bug) or an interaction
between stages; the campaign escalates rather than refits.

### S5 External validation (fasted, fed, other)

Simulate every EXTERNAL study from the final CPF; no fitting. Report per class: fasted, fed, MD, other dose, other
formulation, plus DDI/PGX/SPECIAL studies designated as validation for planned applications. **Gate:** tier limits with
role = validation, fasted and fed reported as separate groups. On failure the machine stops and presents the decision
tree §6.6 to the modeler; the chosen path is a MAP deviation record.

### S6 Prediction and application

Runs only after S4 and S5 are signed. Local sensitivity on every FITTED and PREDICTED parameter plus the parameters
named in the EMA worst-case list (10-fold for CYP abundance, 30-fold for transporters); uncertainty propagation from
fitted-parameter CIs to prediction intervals (parameter sampling, n = 200 [SME]); then the application template(s) from
the question of interest (DDI network with qualified perpetrators, pediatric age bins, HI/RI physiology sets, VBE
trials, FIH translation, PK/PD module). Each application has its own gate defined in its template (architecture pack
§2.2) and produces the M15 *Evaluation of models and outcomes* row.

### S7 Reporting and package

MAR sections (M15 Appendix 2) assembled from S0–S6 artifacts; M15 table submission rows; reproducibility gate
(re-run the package in a clean engine container, compare hashes and PK tables within solver tolerance); signatures;
export.

---

## 5. Diagnostics ruleset (`diag-rules`, versioned, deterministic)

Evidence is computed from the round's metrics; each rule maps evidence to a cause and an ordered list of permitted
actions. The strategist agent chooses among the permitted actions for the stage and writes the rationale; it cannot add
actions. Thresholds are ruleset data [SME].

| Evidence (on internal studies of the stage) | Likely cause | Permitted actions, in order |
|---|---|---|
| Terminal t½ ratio pred/obs > 1.25 or < 0.8, AUC off in the same direction | Clearance | fit `elim.hepatic.*.clspec` (scaling factor if fm known); if at bound → fit `phys.logp` (Vss) |
| AUC within limits, early concentrations (< 2 × tmax,IV) off, Vss off | Distribution | branch partition method; then fit `phys.logp` |
| Early distribution phase shape off (first 30 min IV) with Vss fine | Permeability-limited tissue | branch permeability method; then fit `perm.cellular` |
| Oral: Cmax high and tmax early | Absorption too fast | fit `perm.intestinal` (down); for solids: S3 dissolution |
| Oral: Cmax low and tmax late, AUC fine | Absorption too slow | fit `perm.intestinal` (up); check `phys.solubility.ref` |
| Oral: AUC low with IV clearance verified, F predicted > observed | First-pass or solubility | if dose-normalized AUC decreases with dose → fit `phys.solubility.ref`; else check intestinal enzyme expression (flag, no fit) → fit `perm.intestinal` |
| Dose-normalized AUC increases with dose | Saturable elimination/first-pass | switch dominant enzyme to Michaelis-Menten; fit Km (bounded), Vmax |
| Secondary peak(s) in observed profile after absorption | Enterohepatic recycling | fit `elim.ehc_fraction` |
| MD accumulation ratio off with SD fine | Time-dependent clearance | escalate: auto-induction / TDI requires SME decision |
| Fed/fasted AUC ratio off, Cmax ratio consistent | Fed solubility | fit `food.fed_solubility_factor` (if permitted) else escalate |
| Fed tmax off | Gastric emptying | escalate (meal template choice) |
| Any fitted parameter at bound | Bound or misspecification | escalate with the parameter and the bound |
| Correlation > 0.95 between two fitted parameters | Non-identifiable pair | fix the one with the more reliable source; refit |
| Starts disagree (agreement < 50 %) | Multiple optima | switch algorithm to DEoptim for one round; if unchanged → escalate |
| Fallback (diag-rules 0.5, UNVERIFIED): AUC off > 1.5-fold and no other rule matches | Exposure off, cause unresolved | fit `elim.hepatic.*.clspec`, `elim.hepatic.*.kcat`, `transp.*.kcat`; then `phys.logp` |

---

## 6. Decision trees for scenarios

### 6.1 No IV data
S1 → prior mode (see S1). In S2 fit clearance and absorption jointly with at most 3 parameters; require ≥ 2 dose
levels or an MD study internally, else clearance and bioavailability are confounded: escalate with the recommendation
to obtain IVIVE-based clearance or an IV/microdose study. M15 model risk floor: medium for any CL-dependent question.

### 6.2 IV data only
S2/S3 skipped; oral applications are predictions with absorption parameters PREDICTED; the MAP states that oral
exposure predictions are unverified.

### 6.3 Oral data, several formulations, no solution
Choose the fastest-dissolving IR formulation as the S2 reference (treated as `Dissolved` if > 85 % in 15 min, else
Weibull from its dissolution data fitted in S3 first, then S2 with those formulation parameters fixed).

### 6.4 Nonlinear PK
Detected in S2 dose-range check; Michaelis-Menten branch; if in vitro Km unavailable → bounds [0.01, 100] µmol/l and the
MAP records that Km is fitted without in vitro anchor (model risk floor medium).

### 6.5 Metabolite data
Version 1.0 fits the parent only; metabolite profiles are supportive plots. Parent-metabolite modeling is a later MS
revision (requires metabolite CPF and MoBi/PK-Sim metabolite processes).

### 6.6 External validation fails
1. If the failing study differs in a documented way from the training set (formulation, population, co-medication) →
   record a limitation, restrict the context of use, continue.
2. Else, if another external study of the same class exists → move the failing study to INTERNAL (deviation), refit the
   affected stage only, re-run S4 and S5. Allowed once per class.
3. Else → external validation for that class is *not achievable*; the model may still be used with the M15 model risk
   rated accordingly, or the project waits for more data.

### 6.7 No fed data
Fed exposure is a prediction from the meal model and measured/estimated fed solubility; reported as prediction with the
sensitivity of fed solubility ±10-fold [SME].

### 6.8 Preclinical species (FIH)
Species CPF variants share `phys.*`; `bind.fu` and clearances are species-specific with their own provenance; the
species loop runs S1/S2 per species and the human model is the same CPF with human values. Human clearance prior:
IVIVE first, allometry second, both reported.

### 6.9 PK/PD
Out of MS-01 v1.0. The application template couples the final PK model to a MoBi PD module; PD parameters are fitted in
a separate PD loop with its own MAP section.

### 6.10 DDI victim / perpetrator
Victim: fm per pathway must be supported by clinical evidence (strong-inhibitor DDI study or PGx) for high-risk
questions; the DDI study used for that is EXTERNAL validation of S6, never S1 training. Perpetrator: interaction
parameters FIXED from in vitro; qualification via OSP library victims.

---

## 7. Time budget and compute

Campaign budget default 60 min (MAP may set another). Allocation: S0 1 %, S1 25 %, S2 25 %, S3 12 %, S4 5 %, S5 5 %,
S6 20 %, S7 7 %. Each stage's fitting rounds use `plan_multistart` with the measured seconds-per-simulation from the
engine benchmark on the target servers; a round that cannot fit in the remaining budget is not started, the stage ends
with the best round so far and escalates. Seeds: campaign seed → stage → round → start, all recorded. Engine: one pinned
image per campaign.

---

## 8. Acceptance tiers

From `pbpk_acceptance_criteria.yaml` (architecture pack §2.5; status awaiting SME sign-off): high risk 0.8–1.25-fold
AUC and Cmax, all studies; medium 1.5-fold, ≥ 80 % of studies; low 2-fold, ≥ 80 %. DDI ratios: 1.25-fold (high) or
Guest limits (medium). Internal and external groups are judged separately and both must pass. Stricter MAP criteria
(e.g. |PE| ≤ 10 %) are allowed for internal groups; they must never be looser than the tier.

---

## 9. What the MAP contains, generated from this standard

Objective and question of interest; context of use; CPF table with source per parameter and fit policy; study catalog
with class, score and INTERNAL/EXTERNAL assignment and the split rationale sentences; stage plan with permitted
fit candidates, branches, max rounds, budgets; diagnostics ruleset version; acceptance tier and criteria; engine image
digest; software versions; seeds; what triggers escalation; signatures.

---

## 10. Mapping to code

| Concept | Code |
|---|---|
| CPF schema, engine binding, snapshot generation | `pbpk_domain.cpf` (to build), `pbpk_domain.snapshot.builder` (extend) |
| Study classification and split | `pbpk_domain.campaign.split` (to build) |
| Stage loops | Temporal `ModelingCampaignWorkflow` → `StageLoopWorkflow` → `FitRoundWorkflow` (exists) → engine jobs |
| Fit planning, start sampling, assessment | `pbpk_domain.fitting` (exists) |
| Acceptance gates | `pbpk_domain.acceptance` (exists) |
| Diagnostics | `pbpk_domain.diagnostics` + `rulesets/diag_rules.yaml` (to build) |
| Strategist | `modeler_agents.strategist` (to build; advisory, structured output restricted to permitted actions) |
| Parameter transfer | `pbpk_domain.snapshot.parameter_transfer` (exists) |
| Engine | `run_job.R`, `run_pi.R` (exist); population and sensitivity tasks (to build) |
