# 09 · Business logic and domain intelligence (post-MAP scope)

Abbreviations: `pd/` = `packages/pbpk-domain/src/pbpk_domain/`; `orch/` = `services/orchestrator/src/modeler_orchestrator/`.
Worked numbers were recomputed by hand from the cited formulas (details in `evidence/B_science.md`). Every ruleset
named here is **UNVERIFIED or DRAFT** (SME sign-off pending, `docs/SME_SIGNOFF.md`).

## 1. The procedure (MS-01 v1.3) as code

| Stage | Purpose | Studies it uses | Fits? | Gate | Source |
|---|---|---|---|---|---|
| S0 | readiness | - | no | CPF completeness (MW, logP, fu, solubility or table, pKa or neutral, an `elim.*` pathway), every pathway placeable, every enzyme/transporter has an expression profile; model system: every compound | `orch/campaign_activities.py:113-162`; `pd/cpf/completeness.py` |
| S1 IV | clearance and distribution | internal IV-SD | yes | acceptance + VPC ≥ 80 % | `pd/campaign/map.py:484-561`; `pd/campaign/vpc.py` |
| S2 oral fasted | absorption | internal PO-SOL-FASTED; PO-IR-FASTED when its formulation is Dissolved or no solution exists | yes | acceptance + VPC | same |
| S3 formulation / fed | release, fed effect | internal PO-FED and non-dissolved IR solids when a solution exists | yes (max 2 rounds) | acceptance | same |
| SM metabolites | metabolite clearance and formation (model systems with metabolite data) | metabolite-analyte copies of parent-stage scenarios | yes | acceptance (no VPC, though MS-01 says "as S1") | `map.py:606-622` |
| SJ | joint refinement | union of training scenarios | one joint fit | every internal study passes and GMFE not worse | `orch/joint.py`; `orch/local_runner.py:878-942` |
| S4 internal validation | re-judge the final CPF on every trained study | internal | no | acceptance (VPC reported, not gated) | `map.py:502-508` |
| S5 external validation | judge on blinded studies; fasted and fed separately | external core classes (IV-SD, PO-SOL, PO-IR, PO-FED, PO-MD, PO-MR, PO-OTHER) | no | acceptance per food-state group | `map.py:101-104, 509-510`; `campaign_activities.py:726-729` |
| S6 prediction | sensitivity, uncertainty, applications | S4's scenarios; VBE design scenario | no | runs only after a signed S4/S5 evaluation | `orch/local_runner.py:476-487, 732-781` |
| S7 report & package | bundle, reproduction, MAR | S4/S5 snapshots | no | reproduction at 1e-6 and a clean MAR lint | `orch/package_activities.py:411-419` |

**Budget split** (`map.py:76-80`), fraction of the campaign budget: S0 1 %, S1 20 %, S2 20 %, S3 7 %, SJ 15 %, S4 5 %,
S5 5 %, S6 20 %, S7 7 %; with SM, SM takes 10 % and the others × 0.9. Example for 3,600 s: S1 720 s, S2 720 s, S3 252 s,
SJ 540 s, S4 180 s, S5 180 s, S6 720 s, S7 252 s, S0 36 s. The plan's default campaign budget is 8 h
(`modeler_project/plan.py:81`); `generate_map` defaults to 3,600 s (`map.py:638`).

## 2. Study split (MS-01 §3.3, `pd/campaign/split.py`)

- Classes by route, formulation, food, dosing and flags (DDI, PGX, special populations, preclinical).
- **Information score** = n × time points × (statistic weight + 0.3 for excreta + 0.3 for multiple dose levels).
  Example: n = 12, 15 points, mean ± SD with urine → 12 × 15 × 0.9 = 162.
- S1 takes the single best IV-SD; S2 the best study at the lowest and highest fasted doses; fed (rule 5): a food-effect
  question or measured fed solubility makes every fed study EXTERNAL, otherwise one fed study is INTERNAL; the rest are
  EXTERNAL; flagged classes are EXTERNAL for a planned application, else SUPPORTIVE.
- Gaps: rule 3 rebalancing covers only fasted oral, fed and multiple-dose categories; an IV multiple-dose study is
  classed PO-OTHER; an internal PO-MD/MR/OTHER gets no training scenario.

## 3. Acceptance (`pd/acceptance.py`, `pd/metrics.py`, ruleset `pbpk_acceptance_criteria.yaml` 2026.2-draft)

| Tier (ICH M15 model risk) | AUC/Cmax limit | Minimum fraction within | DDI ratios |
|---|---|---|---|
| high | 1.25-fold | 1.0 (every study) | 1.25-fold |
| medium | 1.5-fold | 0.8 | Guest limits, δ = 2 |
| low | 2-fold | 0.8 | 2-fold |

- A comparison passes when 1/f ≤ pred/obs ≤ f (slack 1e-12). PE % = (pred − obs)/obs × 100.
- **Internal target** (MAP, default 10 % set upstream, UNVERIFIED): internal AUC/Cmax must also have |PE| ≤ t; t must be
  ≤ (1 − 1/f) × 100 (20 % high, 33.3 % medium, 50 % low). It is asymmetric in log space: at t = 20 % a ratio of 1.25
  fails, 0.80 passes.
- Verdicts are grouped by (role, analyte, group, quantity); every group must reach its minimum fraction. AUC and Cmax,
  internal and external, fasted and fed (S5) and each analyte are separate groups.
- **The run uses the criteria signed in the MAP** (`map_doc.acceptance.as_ruleset()`), not the file of the day (D-35).
- GMFE = 10^mean|log10(ratio)| over all studies of the round (reported, and SJ's agreement score).
- Guest: r = R_obs (or 1/R_obs if < 1), limit = (δ(r − 1) + 1)/r, accepted range [R_obs/limit, R_obs·limit].

**Worked examples**
- Medium tier, AUC ratio 1.45 → pass; 0.66 → fail (1/1.5 = 0.667).
- Medium tier, 5 studies, 4 pass → 0.8 ≥ 0.8 pass; 4 studies, 3 pass → 0.75 fail. For n ≤ 4, medium and low tiers
  effectively require every study.
- Internal target 10 %: ratio 1.12 passes the 1.5-fold tier but fails internally.
- Guest δ = 2: R_obs 2.0 → [1.333, 3.0]; R_obs 1.2 → [1.029, 1.40]; R_obs 0.5 → [0.333, 0.75].
- GMFE of {1.2, 0.8, 1.5} = 1.31.

## 4. NCA (`pd/nca.py`)

- AUC: linear trapezoid on rising/flat segments or when a value is zero, log trapezoid on falling positive segments,
  **from the first sampled time** (not t = 0). A linear-only option reproduces a client's NCA.
- Terminal phase: points after Cmax, trailing non-declining points trimmed, log-linear regressions over the last n ≥ 3
  points compared by adjusted R² (ties within 1e-4 go to more points); λz > 0; t½ = ln 2/λz; AUCinf = AUClast + C_last/λz.
- Worked: t = [0.25, 0.5, 1, 2, 4, 8, 12, 24] h, C = [2.0, 3.5, 4.0, 3.2, 2.1, 0.9, 0.4, 0.05] → AUClast 21.52, n = 3
  chosen (adj-R² 0.99784), λz 0.1789 h⁻¹, t½ 3.87 h, AUCinf 21.80.
- The prediction is read at the observed sampling times when ≥ 2 fall inside the simulated window, so AUC and Cmax are
  compared like for like (`pd/campaign/evaluate.py:72-89, 149-164`).

## 5. VPC (`pd/campaign/vpc.py`; `orch/campaign_activities.py:528-602`)

100 virtual individuals from the study's demographics (age range from the study, else mean ± 10 y; single sex 0 % or
100 % female), seed = campaign seed; coverage = observed points ≥ LLOQ inside the interpolated P5–P95; gate ≥ 80 % at S1
and S2, reported at S4; runs only after the PK gate passed; a missing band fails the gate. Caveat: coverage of mean
data by an individual band is a weak test.

## 6. Diagnostics (`pd/diagnostics.py`, `diag_rules.yaml` 0.6)

Thresholds: ratio band 0.8–1.25; dose-normalised AUC trend 25 %; starts agreement 0.5; exposure fallback 1.5-fold.

| Rule | Stages | Evidence | Actions (in order) | Executable today? |
|---|---|---|---|---|
| clearance | S1, S2 | t½ and AUC ratios both high or both low | fit clspec → kcat → transporter kcat → gfr_fraction → ts_clspec → logP | yes (ts_clspec unplaceable) |
| metabolite_clearance / formation | SM | as above / t½ in band, AUC off | metabolite clearances / fit formation | yes |
| distribution | S1 | IV, AUC in limits, early phase and Vss off | branch partition method → fit logP | evidence needs an infusion time (never for a bolus); branch not executed |
| permeability_limited | S1 | permeability shape | branch permeability method → perm.cellular | evidence never computed |
| absorption too fast / too slow | S2 | Cmax and tmax ratios | perm.intestinal (+ solubility) | yes |
| release too slow / too fast | S3 | Cmax off, AUC in limits | Weibull t50 → shape | yes |
| bioavailability (solubility / first pass) | S2 | low AUC, dose dependent or not | solubility / perm.intestinal | yes |
| saturable_elimination | S2 | dose-normalised AUC increasing | switch to Michaelis-Menten | evidence yes, action not executed |
| enterohepatic_recycling | S2, S3 | secondary peak | fit ehc_fraction | evidence never computed |
| fed_solubility | S3 | fed signals | fit food.fed_solubility_factor | no evidence, no engine path |
| non_identifiable_pair | S1–S3, SM | |r| > 0.95 after a fit | fix_and_refit | yes |
| multiple_optima | S1–S3, SM | starts agreement < 0.5 | switch_algorithm DEoptim | evidence yes, action not executed |
| exposure_fallback (only if nothing else matched) | S1, S2, SM | AUC beyond 1.5-fold | clspec, kcat, transporter kcat, formation, logP | yes |
| time_dependent_clearance, gastric_emptying | S2/S3 | MD accumulation, fed tmax | escalate | evidence never computed |
| parameter_at_bound | S1–S3, SM | estimate within 1 % of a bound | escalate | yes |

**Selection:** match by stage and evidence; an escalate rule wins; otherwise concatenate actions in rule order, keep
those valid for the stage (a fit target must be a stage candidate the CPF can fit: value, policy allowing the stage,
bounds, harvested PK-Sim path) and untried; none left → escalate. The strategist then takes the first
(`services/agents/src/modeler_agents/strategist.py:106-125`). In a model system each analyte's studies are diagnosed
for the compounds they inform and merged parent first.

**Execution:** only `fit` and `fix_and_refit` change anything (`orch/campaign_activities.py:221, 438`).

## 7. Fitting

- **Bounds** precedence: strategist override (inactive) > CPF fit policy (signed in the MAP; D-37 fills MS-01 §2.2
  defaults for unfreed candidates, `fit_bounds.yaml` 0.1) > plausibility. Start value = current value clamped.
  Log-scaled policies optimise log(value) (`pd/fit_spec.py:163-261`; `run_pi.R:100-116`).
- **Spec:** BOBYQA, `max_evaluations` 200, output scaling log; SJ uses equal study weights w = √(N/(k·n)) (example:
  studies of 10 and 40 points → w = 1.581 and 0.791, each contributing 25 to the weighted SSR).
- **Multistart** (`pd/fitting.py:116-140`): the largest n ≤ 32 that fits budget − reserve, at least 4, Latin hypercube
  in normalised (log for log-scaled) space. Example: budget 720 s, reserve 120 s, 200 evaluations × 2 simulations ×
  1.5 s, 16 cores → 8 parallel starts, 300 s per wave, 2 waves, n = 16. The orchestrator plans with 40 evaluations per
  start at 0.506 s per simulation and 48 cores by default, so real wall time can exceed the plan up to ~5×.
- **Assessment:** converged starts clustered within 0.05 of the leader; agreement = cluster ÷ converged; AT_BOUND
  within 1 % of the range; HIGHLY_CORRELATED |r| > 0.95; POORLY_DETERMINED CI width > 100 % of the estimate (not wired
  into diagnostics, so the MAP's "CV > 50 %" escalation trigger is not enforced). A null `convergence` counts as converged.
- **Identifiability** (`pd/identifiability.py`): for a correlated pair, fix the one with the better evidence grade
  (A > B > C > D), else the better status (FIXED > PREDICTED), at its signed source value, and refit the other; if the
  signed sources cannot decide, escalate.
- **Apply:** the best start's estimates go into a new CPF version unconditionally; the round then re-simulates the
  fitted CPF and judges that.

## 8. Feedback cycles after an S5 failure (`orch/feedback.py`)

- Per failing study: failed metrics and direction, class, the stage it would train (IV → S1, fed → S3, another
  formulation → S3 when a solution trains S2 and the product is not Dissolved, else S2), documented differences from
  the training set (fed without fed training, untrained formulation, dose outside the trained range, multiple dose).
- MS-01 §6.6 path per study: 1 documented difference → limitation; 2 another external study of its class remains →
  learn (one cycle per class, D-05; more need a signed deviation reason); 3 otherwise → not achievable.
- **Learn:** studies move external → internal; MAP revised and signed by the decision's signature id; re-run
  [S(k), SJ, S4, S5]; external claims rest only on the studies left.
- **New evidence:** one numeric parameter replaced by a measured value in the CPF's own unit, inside plausibility, with
  a reference; status FIXED; re-run from S1; S5 verdict flagged "prompted by S5".

## 9. S6 and VBE

- Sensitivity: FITTED/PREDICTED numeric parameters, local ±10 %, AUC and Cmax; top 12 per study kept. Missing: EMA
  worst-case ranges (10-fold CYP abundance, 30-fold transporter) required by MS-01 §4 S6.
- Uncertainty: FITTED records with SD > 0, n = 200, **independent** draws (correlations not propagated);
  log-scaled: mean·exp(N(−σ²/2, σ)), σ = √ln(1 + CV²) (CV 30 % → σ 0.2936); truncation by rejection without an
  iteration cap.
- VBE (`pd/vbe.py`, template `vbe-crossover` 0.2.0-draft): individuals with valid AUC_inf and C_max in both arms; trials
  formed in id order; each trial's paired log-difference 90 % CI with t(n−1); pass iff within limits (standard
  0.80–1.25; NTI 0.90–1.1111 unverified); PoS per metric and joint. Worked: n 24, mean −0.02, SD 0.15 → CI
  [0.930, 1.033], pass. F-304: simulated/observed between-subject CV within 1.5-fold (unverified) and observed GMR within
  the simulated P5–P95; NOT_VALIDATED without an observed BE study. Every design input is `never_default`.

## 10. Governance rules enforced in code

| Rule | Enforcement | Source |
|---|---|---|
| D-19 real-data rule | S4/S5 signature (`approve`) refused when any stage before S6 was judged on non-real data, unless the project is exploratory; non-real passes shown as TEST ONLY | `pd/data_origin.py`; `orch/local_runner.py:1178-1182` |
| D-35 signed criteria | evaluation uses the MAP's acceptance | `campaign_activities.py:786-789` |
| D-36 CPF = MAP | pilot/production start refused on any difference | `services/api/src/modeler_api/run_guard.py:85-105` |
| Signed stage limits | pilot/production start refused with budget overrides | `run_guard.py:77-82` |
| Model risk never assumed | required on start | `campaign_api.py:39` |
| VBE inputs never defaulted | MAP cannot be signed with missing inputs | `map.py:389-396` |
| Package only if reproduced | zip written only when the re-run matches and the MAR lint is clean | `package_activities.py:411` |
| Ruleset status | **not enforced**: acceptance and diagnostics run on UNVERIFIED rulesets; only `ddi_static.screen` (unwired) refuses one | `pd/ddi_static.py:92-96` |

## 11. Ruleset inventory

| File | Version | Status | Governs |
|---|---|---|---|
| `pd/rulesets/pbpk_acceptance_criteria.yaml` | 2026.2-draft | UNVERIFIED | tiers, fractions, DDI limits, evidence requirements |
| `pd/rulesets/diag_rules.yaml` | 0.6 | UNVERIFIED | evidence → causes → actions |
| `pd/rulesets/dissolution_similarity.yaml` | 2026.1-draft | UNVERIFIED | f2 (pre-MAP) |
| `pd/rulesets/ddi_static_screening.yaml` | 2026.1-draft | UNVERIFIED | ICH M12 static screens (unwired) |
| `pd/parameters/registry.yaml` | 1.2 | UNVERIFIED | CPF ids, units, PK-Sim names, S0 gate |
| `pd/analysis_templates/vbe-crossover.yaml` | 0.2.0-draft | DRAFT | VBE design, limits, F-304 |
| `pd/analysis_templates/ddi-cyp3a4-victim.yaml` | 1.0.0-draft | DRAFT | DDI (no runner; names a non-existent builder step) |
| `modeler_project/fit_bounds.yaml` | 0.1 | UNVERIFIED | D-37 default bounds |
| MS-01 (`docs/PBPK_MODELING_WORKFLOW.md`) | 1.3 | v1.0 final; v1.1–1.3 UNVERIFIED | the procedure |

Open SME items that change outcomes: whether S1 judges a short IV infusion's Cmax (every published model escalates
there today); the 10 % default internal target; the medium tier's 1.5-fold source; the Guest citation; SD weighting and
BLQ handling in PI; the 1-hour goal versus the S3 share of the budget.
