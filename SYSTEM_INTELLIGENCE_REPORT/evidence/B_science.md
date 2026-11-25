# B — Scientific domain logic (L0 `pbpk_domain`) used by the post-MAP campaign

Read-only audit, 2026-11-25. Path abbreviations: `pd/` = `packages/pbpk-domain/src/pbpk_domain/`; `orch/` =
`services/orchestrator/src/modeler_orchestrator/`; `agents/` = `services/agents/src/modeler_agents/`; `proj/` =
`packages/project-model/src/modeler_project/`. "VERIFIED" = I read the code at the cited lines. "INFERRED" = reasoned
from code or docs but not executed. Nothing in the repo was run (no repo imports); worked numbers were recomputed with
stand-alone arithmetic that re-implements the cited formulas.

---

## 1. Summary

The L0 package is a mostly pure, deterministic library. It implements the MS-01 v1.3 procedure
(`docs/PBPK_MODELING_WORKFLOW.md`) as data plus code. The rulesets, registry and templates are versioned YAML, all
`UNVERIFIED`/`DRAFT`. The code covers: the study split (§3), MAP generation and hashing (§9), the round snapshot build
from the CPF (§2), NCA and acceptance gates (§8), the diagnostics ruleset (§5), fit specification and parameter
transfer back into the CPF, multistart planning and fit assessment, the identifiability rule, VPC coverage, S6
sensitivity and uncertainty helpers, VBE statistics, and model systems (metabolites).

What works, verified in code:
- tiered fold-error acceptance with per-(role, analyte, group, quantity) grouping;
- the signed MAP's criteria and internal target used at run time (D-35);
- NCA by linear-up/log-down with adjusted-R² terminal selection;
- prediction read at the observed sampling times, so AUC and Cmax are compared like for like;
- PK-ratio diagnostics (clearance, absorption, release, dose trend, exposure fallback, optimiser signals);
- LHS multistart with budget planning;
- equal per-study weights for SJ;
- grade/status-based fix_and_refit;
- the CPF→snapshot builder for 18 process types and Dissolved/Weibull/Particle/binned formulations, with IV
  bolus/infusion, oral, multiple-dose and phased regimens and meal events;
- VBE paired-crossover CIs, PoS and the F-304 gate.

Most important gaps, CONFIRMED by tracing:
1. Only `fit` and `fix_and_refit` actions are executed (`orch/campaign_activities.py:221`). Three ruleset actions are
   offered, consumed as "tried", and change nothing:
   - `branch dist.partition_method`;
   - `switch elim.hepatic.{enzyme}.mm` (Michaelis-Menten);
   - `switch_algorithm DEoptim` (the algorithm is always BOBYQA, `pd/fit_spec.py:220`).
2. Five diagnostic evidences are never computed in production: secondary peak, MD accumulation, permeability shape,
   and the two fed signals. The rules for enterohepatic recycling (EHC), time-dependent clearance, permeability-limited
   distribution, fed solubility and gastric emptying therefore cannot fire.
3. The S3 fed sub-loop cannot run. `food.fed_solubility_factor` has no placement or engine path.
4. The IV "distribution" evidence can never fire for an IV bolus, because the Vss/early-phase computation requires an
   infusion time.
5. The S6 EMA worst-case sensitivity (10× CYP, 30× transporter) is not implemented; only ±10 % local sensitivity.
6. The DDI path is entirely unwired: no producer of AUCR/CmaxR comparisons, `ddi_static.screen` has no callers, and the
   template names a non-existent step.
7. Catalog binding verification (`cpf.binding.bind`) has no callers outside tests.

Surprising:
- `elim.ehc_fraction` placed on the Individual (registry 1.2) appears to be flagged as an unplaced elimination
  parameter. That would block S0 (static trace, untested).
- Every fed study gets the same default meal, "Meal: High-fat breakfast (Human)", unless it carries explicit meals;
  `meal_type` is ignored.
- The project default internal target of |PE| ≤ 10 % (UNVERIFIED, owner default) applies to every internal AUC and
  Cmax, IV Cmax included. That is far stricter than any tier.

---

## 2. Module inventory

"Called by" = non-test importers in `services/` and the other packages (grep of `pbpk_domain.<module>`).

| Module | Path | Responsibility | Called by (non-test) | Calls | Lines |
|---|---|---|---|---|---|
| acceptance | pd/acceptance.py | Tiered fold/Guest verdicts, groups, internal target | orch (via campaign/evaluate), api/brief_api, proj/plan, review, steps | metrics, m15 | 156 |
| metrics | pd/metrics.py | GMFE, fraction within fold, Guest limits | acceptance, campaign/evaluate (no direct service importer) | numpy | 76 |
| nca | pd/nca.py | AUC (lin-up/log-down or linear), λz, t½, AUCinf | api/studies (observed PK), campaign/evaluate, prediction, proj dataroom | — | 156 |
| campaign.evaluate | pd/campaign/evaluate.py | Reduce sim profiles at observed times, compare, gate, metrics | orch/campaign_activities (`evaluate_round`) | nca, acceptance, metrics | 282 |
| campaign.vpc | pd/campaign/vpc.py | VPC constants, age range, band coverage | orch/campaign_activities (`prepare_vpc_jobs`, `evaluate_vpc`) | — | 73 |
| diagnostics | pd/diagnostics.py | Evidence labels → rules → permitted actions | orch/campaign_activities (`diagnose_round`), agents/strategist | rulesets/diag_rules.yaml | 286 |
| campaign.map | pd/campaign/map.py | MAP model, stage plan, budgets, scenarios, hashing, signing, CPF diff | orch (many), api/plan_api, run_guard, write_api, proj/plan, review, roles, inputs | split, acceptance, system, formulations, vpc | 696 |
| campaign.split | pd/campaign/split.py | Study classes, information score, INTERNAL/EXTERNAL/SUPPORTIVE split | api/inputs_api, write_api, proj/plan, roles, inputs, datasets, intake | — | 540 |
| campaign.round_build | pd/campaign/round_build.py | MAP scenarios → builder specs → stage snapshot | orch/campaign_activities, package_activities, vbe_activities, proj/inputs | cpf.build, snapshot.builder, formulations, system | 410 |
| campaign.prediction | pd/campaign/prediction.py | S6 sensitivity candidates, uncertainty sampling, PIs, CSV parsing | orch/package_activities | nca, cpf.models | 138 |
| fit_spec | pd/fit_spec.py | PI spec from CPF, weights, groups, estimates back into CPF | orch/campaign_activities, joint, proj/plan | pksim_paths, formulations, spread | 306 |
| fitting | pd/fitting.py | LHS starts, runtime estimate, multistart plan, fit assessment | orch/fitting_activities, local_runner | numpy | 242 |
| identifiability | pd/identifiability.py | fix_and_refit: choose the pair member to fix, fix it at its signed value | orch/campaign_activities (`_decide_pairs`, `_round_base`) | campaign.map, cpf | 92 |
| system | pd/system.py | Model system: roles, formation, products, analytes, gating | orch (round_system, campaign/package/vbe activities), api, storage, contracts | cpf.models | 264 |
| vbe | pd/vbe.py | K×n virtual crossover trials, PoS, F-304 gate | orch/vbe_activities, proj/room_basis | bioequivalence | 144 |
| bioequivalence | pd/bioequivalence.py | Paired log-difference 90 % CI | vbe, proj/room_basis | scipy | 69 |
| ddi_static | pd/ddi_static.py | Static R1/R2/R3 screens (ICH M12 basic models) | **none** | rulesets/ddi_static_screening.yaml | 120 |
| data_origin | pd/data_origin.py | Real-data rule (D-19), TEST ONLY labels, signature refusal | orch/local_runner, api/studies, proj, storage | — | 88 |
| units | pd/units.py | Observed profile → min, µmol/l | api/studies, orch, proj intake | spread | 93 |
| parameter_units | pd/parameter_units.py | Stated value → CPF storage unit (no IVIVE) | proj/evidence | parameters | 95 |
| spread | pd/spread.py | SD from SE/CV; PK-Sim error types | orch, proj intake | — | 33 |
| expression | pd/expression.py | Harvested expression library (40 molecules) | proj/inputs; cpf.build | data/expression_library.json | 42 |
| pksim_paths | pd/pksim_paths.py | CPF record → PK-Sim simulation path for PI | orch/campaign_activities, package_activities; fit_spec | parameters | 92 |
| parameters | pd/parameters/{__init__.py,registry.yaml} | CPF id registry: placement, storage unit, PK-Sim name, S0 gate | intake/fields, proj/estimation, evidence, inputs; cpf.* | — | 278 + 125 |
| cpf.models | pd/cpf/models.py | CPF, ParameterRecord, FitPolicy, Plausibility, FitGroup, Uncertainty | everywhere | — | 261 |
| cpf.build | pd/cpf/build.py | CPF (+system) → CompoundSpec/processes/expression → Snapshot + BuildReport | orch/campaign_activities, proj/inputs, round_build | snapshot.builder, parameters, expression | 750 |
| cpf.binding | pd/cpf/binding.py | Validate engine bindings against harvested catalog | **none (tests only)** | catalog | 107 |
| cpf.completeness | pd/cpf/completeness.py | S0 completeness gate | orch/campaign_activities, api/cpf_view, reference_models | parameters | 40 |
| cpf.formulations | pd/cpf/formulations.py | form.* → Dissolved/Weibull/Particles/Bins specs, Weibull paths | orch, api/plan_api, proj | snapshot.builder | 160 |
| cpf.process_bindings | pd/cpf/process_bindings.py | Candidate process types for a process id | api/inputs_api, proj/evidence, inputs | reference.osp_import tables | 60 |
| snapshot.builder | pd/snapshot/builder.py | Typed specs → PK-Sim v80/v81 snapshot JSON, reference validation | cpf.build, api/system_api, proj, golden scripts | snapshot.models, validation | 1302 |
| snapshot.models | pd/snapshot/models.py | Typed snapshot view, ValueOrigin coercion | builder, golden scripts | — | 299 |
| snapshot.validation | pd/snapshot/validation.py | Process/interaction selection names, reference integrity | builder | — | 124 |
| snapshot.parameter_transfer | pd/snapshot/parameter_transfer.py | "Transfer to Simulation" overrides | **none** | snapshot.models | 50 |
| analysis_templates | pd/analysis_templates/{__init__.py,*.yaml} | Template schema, input checks, limits | orch/vbe_activities, proj/review; campaign.map | — | 166 |
| dissolution | pd/dissolution.py | f2, Weibull in-vitro fit (pre-MAP use) | proj dataroom/intake, agents/document_reader | rulesets/dissolution_similarity.yaml | 291 |
| m15 | pd/m15.py | M15 Rating enum, admissible risk | many | — | 109 |
| reference.osp_import | pd/reference/osp_import.py | OSP snapshot → CPF + studies (+ harvested process tables) | process_bindings (tables), api | — | 2084 |

`reference/osp_import.py` (skipped except role): it imports a published OSP library snapshot (Dapagliflozin,
Rifampicin, …) as a CPF plus its clinical studies. Values, units and provenance are copied verbatim; formulations become
`form.*`, individual changes `indiv.*`, and each parent plasma dataset a study. Anything unusable is listed as
skipped/unplaced (`osp_import.py:1-13`). It also holds the harvested `PROCESS_PARAMETERS`/`PROCESS_FAMILY` tables
(`osp_import.py:58-112`) that `cpf.process_bindings` and the builder's placement depend on.

---

## 3. Feature table

| Feature | Purpose | Inputs | Outputs | Source (file:line) | Status | Evidence note |
|---|---|---|---|---|---|---|
| Tiered fold acceptance | MS-01 §8 gate | Comparisons, tier, signed ruleset | Verdicts, GroupResults | pd/acceptance.py:104-156 | implemented | VERIFIED; status of ruleset not checked |
| Guest limits for DDI ratios | Medium-tier AUCR/CmaxR | R_pred, R_obs, δ | pass/fail | pd/metrics.py:58-76; acceptance.py:108-111 | implemented, unwired | no producer of AUCR/CmaxR in services (grep) |
| Internal target | MAP-stricter |PE| for internal AUC/Cmax | target %, role | verdict | acceptance.py:38-44,132-136,143 | implemented | default 10 % set upstream (proj/brief.py:512, plan.py:391-400) |
| Per-group judging | fasted/fed (S5), analytes | role, analyte, group, quantity | per-group fraction | acceptance.py:146-151; orch/campaign_activities.py:726-729 | implemented | VERIFIED |
| NCA | reduce profiles to PK | t, C | Cmax, tmax, AUClast, λz, t½, AUCinf | pd/nca.py:46-156 | implemented | linear-up/log-down, adj-R² |
| Sampling-matched prediction | like-for-like PK | sim curve, obs times | PK at obs times | pd/campaign/evaluate.py:72-89,149-164 | implemented | |
| IV profile-shape evidence | distribution rule | obs samples, infusion time | early ratio, Vss ratio | evaluate.py:218-241 | partial | needs infusion time → never for bolus |
| GMFE / 2-fold metrics | reporting, SJ agreement | pred/obs | value | metrics.py:41-55; evaluate.py:263-271 | implemented | pools all studies |
| VPC coverage gate | S1/S2 gate, S4 report | 5–95 % band, obs points | coverage, pass | pd/campaign/vpc.py:17-73; orch 529-601 | implemented | n=100, ≥ 80 %, single sex |
| Diagnostics ruleset engine | §5 evidence → actions | residuals, fit signals | permitted actions / escalate | pd/diagnostics.py:118-286 | implemented | |
| PK-ratio evidences | clearance, absorption, release, dose trend, exposure | ratios | labels | diagnostics.py:136-187 | implemented | |
| Profile evidences (EHC, MD, permeability, fed) | §5 rows | — | labels | diagnostics.py:42-63, 189-198 | placeholder | never set in orch (grep) |
| Action application: fit / fix_and_refit | next round | action | PI spec | orch/campaign_activities.py:221 | implemented | |
| Action application: branch / switch / switch_algorithm | method branches, MM, DEoptim | action | — | none | placeholder | consumed as tried, no effect |
| Strategist choice | pick next action | permitted list | first untried | agents/strategist.py:106-144; orch 1055 | implemented (deterministic) | LLM decider not wired |
| Stage plan & budgets | MAP §9 | — | candidates, rounds, seconds | pd/campaign/map.py:41-81, 625-674 | implemented | |
| Split | §3.3 | studies, question | INTERNAL/EXTERNAL/SUPPORTIVE + rationale | pd/campaign/split.py:267-540 | implemented / partial | rule 3 partial |
| MAP hash/sign/revise | Part 11 binding | MAP | sha256, signed copy | map.py:370-414 | implemented | |
| CPF vs MAP diff | D-36 guard | MAP, CPF | differences | map.py:446-469 | implemented | |
| Fit spec | PI input | CPF, fit ids, sims | pi_spec_base | pd/fit_spec.py:214-277 | implemented | BOBYQA fixed |
| Bounds precedence | override > policy > plausibility | record | (lo, hi) | fit_spec.py:163-174 | implemented | override unconstrained |
| Equal study weights (SJ) | D-04 | sims | weights | fit_spec.py:199-211 | implemented | |
| Fit groups (factor) | PI-4 B2 | CPF groups | group factor spec | fit_spec.py:130-155 | implemented | |
| Estimates → CPF | CPF system of record | estimates, CI | new CPF version | fit_spec.py:280-306 | implemented | model_copy skips validation |
| Multistart planning | 1-h goal | budget, sims, cores | n_starts | pd/fitting.py:116-140 | implemented | |
| Fit assessment | optimiser evidence | starts, corr, CI | findings, pairs | fitting.py:193-242 | implemented | CV > 50 % trigger not escalated |
| fix_and_refit choice | PI-2b | pair, signed MAP | FixChoice / reason | pd/identifiability.py:56-91 | implemented | |
| S6 sensitivity | which params matter | CPF FITTED/PREDICTED | engine job rows | pd/campaign/prediction.py:30-34,48-52,121-138 | partial | ±10 % only |
| S6 uncertainty | PIs | FITTED with SD | 200 draws, P5/50/95 | prediction.py:54-100 | partial | independent, truncation by resampling |
| VBE trials + PoS | APP-11/14 | arm PK, design | per-metric & joint PoS | pd/vbe.py:108-144; bioequivalence.py:33-62 | implemented | |
| F-304 gate | VBE validation | observed BE summary | PASSED/FAILED/NOT_VALIDATED | vbe.py:72-100 | implemented | 1.5-fold CV criterion unverified |
| Static DDI screen | ICH M12 R1/R2/R3 | in-vitro params | flags | pd/ddi_static.py:91-120 | implemented, unwired | refuses UNVERIFIED ruleset |
| Model system gating | §6.5 | system, analyte, stage | gated, subjects | pd/system.py:207-264 | implemented | |
| CPF → snapshot | §2 regeneration | CPF, subjects, scenarios | Snapshot + BuildReport | pd/cpf/build.py:616-750 | implemented | |
| Process placement | 18 process types | CPF process records | CompoundProcess | build.py:411-491; snapshot/builder.py:386-405 | implemented | biliary/TS/fed absent |
| Formulations | oral release | form.* | specs | pd/cpf/formulations.py:33,101-159 | implemented | Lint80/Table absent |
| Catalog binding check | T-03 | CPF, catalog | BuildPlan / BindingError | pd/cpf/binding.py:55-107 | implemented, unwired | no callers |
| Parameter transfer to snapshot | PK-Sim-style overrides | PI values | Snapshot | pd/snapshot/parameter_transfer.py:26-50 | implemented, unused | contradicts CPF-only principle anyway |
| S0 completeness | §2.2 gate | CPF | ready/missing | pd/cpf/completeness.py:27-40; registry.yaml:112-125 | implemented | ehc counts as pathway |
| Real-data rule | D-19 | origins, metrics | labels, refusal | pd/data_origin.py:48-88 | implemented | |

---

## 4. Detailed findings per question

### Q1. Acceptance

**Criteria (VERIFIED).** `rulesets/pbpk_acceptance_criteria.yaml`, `id: pbpk-acceptance-criteria`,
`version: "2026.2-draft"`, `status: UNVERIFIED` (lines 15-17).

| Tier | AUC/Cmax limit | Source cited | DDI AUCR/CmaxR | Min fraction within |
|---|---|---|---|---|
| high | max_fold 1.25 | fda_review_practice | 1.25-fold | 1.0 |
| medium | max_fold 1.5 | ema_pbpk_reporting | Guest, δ = 2 | 0.8 |
| low | max_fold 2.0 | ema_pbpk_reporting | 2.0-fold | 0.8 |

Tier lines are 30-38, 39-47 and 48-56. The tier key is the ICH M15 `Rating` (`low`/`medium`/`high`, `pd/m15.py:17-20`),
assigned by a person (`m15.py:1-4`, `allowed_model_risk` 30-39).

**Verdict per comparison** (`acceptance.py:104-120`):
- ratio = pred/obs.
- A fold rule passes when 1/f ≤ ratio ≤ f, with relative slack 1e-12 (line 114).
- A Guest rule calls `within_guest_limits` (line 110).
- PE % = (pred − obs)/obs × 100 (47-50).
- When an internal target t applies, the comparison must also have |PE| ≤ t (117-119).
- Non-positive values raise (105-106).

**Internal target** (`acceptance.py:38-44, 132-136, 143`):
- It applies only to role `fitting` and only to AUC/Cmax (the `pk_parameters` section). It never applies to
  validation comparisons or DDI ratios.
- It must satisfy 0 < t ≤ (1 − 1/f_min) × 100. That limit is 20 % for high, 33.3 % for medium and 50 % for low
  (recomputed).
- The MAP records it (`map.py:254-267, 472-481`). The campaign judges with `map_doc.acceptance.as_ruleset()` and
  `internal_target_pe` (`orch/campaign_activities.py:787-789`), so a run uses the signed criteria, not the file (D-35).
- Upstream, Start applies a **default of 10 %** when nobody sets one (`proj/brief.py:512`; `proj/plan.py:391-400`,
  "UNVERIFIED, not reviewed by an SME").
- |PE| ≤ t is asymmetric in log space. At the high tier with t = 20 %, ratio 1.25 (PE +25 %) fails the target while
  0.80 (PE −20 %) passes. The effective internal band becomes [0.80, 1.20].

**Grouping** (`acceptance.py:138-151`):
- Verdicts are grouped by `(role, analyte, group, quantity)`. Each group passes when
  fraction_within ≥ `min_fraction_within`, and the report passes when every group passes (96-98).
- AUC and Cmax are thus separate groups, and so are internal and external.
- At S5 the group is the scenario's `food_state` (`orch/campaign_activities.py:728-729`: `group_of = food_of if
  ctx.stage == "S5" else {}`), giving fasted/fed separately.
- Each model-system analyte is its own group. Metabolites, co-parents and racemic sums are held to the parent's limits
  (yaml lines 18-21).
- Role comes from the MAP assignment: INTERNAL → fitting, everything else → validation (orch 726).

**GMFE** (`metrics.py:41-45`) = 10^mean|log10(pred/obs)|, with non-positive pairs excluded and counted. It is reported
per quantity over all studies of the round (`evaluate.py:263-271`), not per group. SJ uses it as the "agreement" score
(`orch/joint.py`, `agreement`, the mean of the AUC and Cmax GMFE).

**Guest limits** (`metrics.py:58-71`): r = R_obs (or 1/R_obs when < 1); limit = (δ(r − 1) + 1)/r; the accepted range is
[R_obs/limit, R_obs·limit].

**Worked examples** (recomputed):
- Medium tier, AUC ratio 1.45: passes 1.5-fold. Ratio 0.66 fails, since 1/1.5 = 0.6667.
- Medium tier, 5 studies with 4 passing: 0.8 ≥ 0.8, passes. With 4 studies and 3 passing: 0.75, fails. For n ≤ 4 the
  medium and low tiers therefore demand every study (arithmetic of `min_fraction_within` 0.8).
- Internal target 10 % (the default): a ratio of 1.12 passes the 1.5-fold tier but fails internally ("1.5-fold and
  |PE| ≤ 10 %").
- Guest, δ = 2:

  | R_obs | Accepted R_pred range |
  |---|---|
  | 2.0 | [1.333, 3.0] |
  | 1.2 | [1.029, 1.40] |
  | 0.5 | [0.333, 0.75] |
  | 5.0 | [2.778, 9.0] |

  As R_obs → 1 the range collapses to [1, 1].
- GMFE of ratios {1.2, 0.8, 1.5} = 1.31.

**How verdicts are produced in a round** (`campaign/evaluate.py:123-206`):
1. Each simulated profile is read at the observed sampling times when ≥ 2 fall in the simulated window (149-151), else
   cut to [t_first, t_last] (152-164).
2. It is reduced by `nca` (165).
3. AUC (auc_last by default, `auc_kind="last"`) and Cmax comparisons are built (181-186).
4. Studies in `reported` (non-gated analytes) are reduced but excluded (179-180).
5. With no comparisons the gate is `False`, never a false pass (188-193).

Observed PK is NCA of the uploaded, unit-normalised profile, `auc = result.auc_last`
(`services/api/src/modeler_api/studies.py:74-92`).

**Open SME items** (`docs/SME_SIGNOFF.md:20`; `docs/research/2026-11-24-note-for-the-sme-acceptance-ruleset.md`):
- the `guest_2011` title is wrong; the real paper is the "Critique of the two-fold measure…", DMD 2011;39:170-173;
- the medium 1.5-fold is attributed to EMA without a supporting source;
- whether S1 should judge IV Cmax. The published Itraconazole, Verapamil and Dapagliflozin models escalate at S1 on IV
  Cmax with AUC in band.

### Q2. NCA, metrics, VPC gate

**AUC rule** (`nca.py:46-59`): linear trapezoid on rising or flat segments or when an end point is zero; log trapezoid
dt·(c0 − c1)/ln(c0/c1) on falling positive segments. It runs from the **first sampled time**, not from 0. A linear-only
option exists for reproducing a client's NCA (62-65, 138-139).

**Terminal phase** (`nca.py:73-135`):
- Only points after Cmax are used (95). Trailing points that do not decline are trimmed (96-97; the Boulton 2013
  artefact in the docstring).
- Log-linear regressions over the last n points, n ≥ 3, are compared by adjusted R². Ties within `ADJ_R2_TOLERANCE`
  1e-4 go to more points (70, 104-113). λz must be > 0.
- t½ = ln2/λz; AUCinf = AUClast + C_last/λz using the last **observed** value (151).
- A fixed-window option, `terminal_points`, exists.

**Worked NCA** (re-implemented):
- Input: t = [0.25, 0.5, 1, 2, 4, 8, 12, 24] h, C = [2.0, 3.5, 4.0, 3.2, 2.1, 0.9, 0.4, 0.05].
- AUClast = 21.52 (from 0.25 h).
- Terminal candidates: n = 3, adj-R² 0.99784; n = 4, 0.99638; n = 5, 0.99647. n = 3 is chosen, since the others are not
  within 1e-4.
- λz = 0.1789 h⁻¹, t½ = 3.87 h, AUCinf = 21.80.

**Other evaluation metrics** (`evaluate.py:244-282`):
- Per study: the predicted and observed AUC, Cmax, tmax and t½, `early_ratio`, `vss_ratio`, `gated`, `auc_in_limits`
  and `cmax_in_limits`.
- Per quantity: n, GMFE and fraction within 2-fold.
- Plus tier, ruleset, internal target and groups.
- Vss ratio = (MRT_p/AUC_p)/(MRT_o/AUC_o) with MRT = AUMC/AUC − T_inf/2 over the identical samples. It is truncated and
  not extrapolated, so it is an approximation (218-241).

**VPC** (`campaign/vpc.py`; wiring in `orch/campaign_activities.py:529-601`, `orch/campaign.py:184-188, 269`):
- Constants: `VPC_STAGES = (S1, S2, S4)`, gate stages `(S1, S2)`, n = 100, min coverage 0.80, percentiles 5/50/95
  (17-21).
- The age range is the study's own, else mean ± 10 y (adults ≥ 18) (24, 43-48).
- Coverage counts observed points within the simulated window and ≥ LLOQ that fall between the interpolated P5 and P95
  (61-73). It passes when n_points > 0 and fraction ≥ 0.8 (38-40).
- Population job: `proportion_of_females` is 100 or 0 from the scenario's single sex (orch 557); the seed is the
  campaign seed.
- The VPC runs **only after the PK gate passed** (campaign.py:187).
- At gating stages a missing band or observed profile fails the gate (orch 588-590, 599). At S4 a low coverage is only a
  finding.
- Not run at S3, SM or S5. MS-01 §4 SM says "Gate: as S1", so SM lacks the VPC part (INFERRED deviation).
- Scientific caveat (INFERRED): for mean data, the observed means of a healthy study usually fall inside a 90 %
  individual band, so ≥ 80 % coverage is a weak test for aggregated data.

### Q3. Diagnostics

**Ruleset** `diag-rules` version 0.6, UNVERIFIED (`diag_rules.yaml:11-13`).

Thresholds (53-58):

| Threshold | Value |
|---|---|
| ratio_high | 1.25 |
| ratio_low | 0.8 |
| dose_norm_auc_rel | 0.25 |
| starts_agreement_min | 0.5 |
| exposure_fallback_fold | 1.5 |

**Evidence computed** (`diagnostics.py:118-210`, on fitting-role studies, or all if none, 96-98):
- `clearance_off`: t½ ratio and AUC ratio both > 1.25 or both < 0.8 (137-140).
- `formation_off` (SM only): t½ within the band and AUC out of it (144-146).
- `exposure_off`: AUC ratio beyond 1.5-fold (149-152).
- `distribution_off`: IV, AUC in limits, early phase off and Vss off (155-156).
- `permeability_limited` (158-159).
- `absorption_fast`: oral, Cmax > 1.25 and tmax < 0.8 (162-163).
- `absorption_slow`: Cmax < 0.8, tmax > 1.25 and AUC in limits (164-165).
- `release_slow` / `release_fast`: Cmax off with AUC in limits and tmax not contradicting (170-175).
- Dose trend: observed dose-normalised AUC, lowest vs highest dose, ±25 % (101-115, 178-187). It gives
  `dose_norm_auc_increasing`, `auc_low_dose_dependent` and `auc_low_dose_independent`.
- `secondary_peak`, `accumulation_off`, `fed_solubility`, `fed_tmax_off` (189-198).
- Optimiser signals: `param_at_bound`, `correlated_pair` (the strongest pair), `starts_disagree` (201-208).

**What is actually fed in production** (orch/campaign_activities.py:940-1050): ratios for AUC, Cmax, tmax and t½,
observed AUC, dose, `auc_in_limits`, and `early_phase_off`/`vss_off` derived from `early_ratio`/`vss_ratio` against
0.8–1.25 (999-1000, `_off` 934-936). Post-fit, the fit signals (at_bound, correlated pairs, starts agreement) are added
(1007-1012). `secondary_peak`, `accumulation_off`, `permeability_shape_off` and `FedSignals` are **never set** (grep:
the only non-test hit is lines 999-1000).

**Rules and actions** (yaml 61-257):

| Rule | Stages | Evidence | Actions, in order | Wired? |
|---|---|---|---|---|
| clearance | S1, S2 | clearance_off | fit clspec → kcat → transp kcat → gfr_fraction → ts_clspec → logP | yes (ts_clspec unplaceable) |
| metabolite_clearance | SM | clearance_off | clspec, kcat, transp kcat, gfr, logP | yes |
| metabolite_formation | SM | formation_off | fit formation | yes |
| distribution | S1 | distribution_off | branch partition method → fit logP | evidence: infusion only; branch not executed |
| permeability_limited | S1 | permeability_limited | branch permeability method → fit perm.cellular | no evidence |
| absorption_too_fast / too_slow | S2 | absorption_* | perm.intestinal (+ solubility for slow) | yes |
| release_too_slow / too_fast | S3 | release_* | Weibull t50 → shape | yes |
| bioavailability_solubility / firstpass | S2 | auc_low_* | solubility / perm.intestinal | yes |
| saturable_elimination | S2 | dose_norm_auc_increasing | switch elim.hepatic.{enzyme}.mm | evidence yes; action not executed |
| enterohepatic_recycling | S2, S3 | secondary_peak | fit elim.ehc_fraction | no evidence |
| fed_solubility | S3 | fed_solubility | fit food.fed_solubility_factor | no evidence, no engine path |
| non_identifiable_pair | S1–S3, SM | correlated_pair | fix_and_refit | yes (post-fit) |
| multiple_optima | S1–S3, SM | starts_disagree | switch_algorithm DEoptim | evidence yes; action not executed |
| exposure_fallback (fallback: true) | S1, S2, SM | exposure_off | clspec, kcat, transp kcat, formation, logP | yes |
| time_dependent_clearance (escalate) | S2, S3 | accumulation_off | — | no evidence |
| gastric_emptying (escalate) | S3 | fed_tmax_off | — | no evidence |
| parameter_at_bound (escalate) | S1–S3, SM | param_at_bound | — | yes |

**Selection logic** (`diagnose`, 233-286):
1. Match rules by stage and evidence; a `fallback` rule counts only when no non-fallback rule matched (249-252).
2. Any matched escalate rule escalates first (255-263).
3. Otherwise the actions are concatenated in rule order. An action is kept only when it is valid for the stage: `fit`
   needs its target among the stage candidates, `branch` among the branches, and `switch` needs Km or Vmax among the
   candidates (221-230). It must also be untried.
4. If none remain, escalate with "all permitted actions … already tried" or "no diagnostic rule matched" (279-286).

The YAML `routes` field is not read; routes are hard-coded in `compute_evidence`.

**Permitted actions per stage:**
- The candidate set is `STAGE_PLAN` (`map.py:41-73`), filtered by the orchestrator to candidates the CPF can fit
  (`_fittable_candidates`, orch 804-837). A candidate is dropped when it resolves to no parameter, its policy excludes
  the stage, it has no bounds, or it has no engine path.
- Stage candidate tokens:
  - S1: clspec, kcat, transp kcat, logP, gfr, ts_clspec, perm.cellular, bind.fu, plus the branches partition and
    permeability method.
  - S2: perm.intestinal, solubility, ehc_fraction, km, vmax, clspec, kcat, transp kcat. No logP (see defect D27).
  - S3: Weibull t50, Weibull shape, fed solubility factor.
  - SM: per-metabolite clearances, formation, logP.
- `bind.fu` (S1) is a candidate but no rule offers it. `perm.cellular` is offered only by the unwired
  permeability_limited rule.

**First action choice:**
- With no LLM decider wired, `strategist.decide` returns `available[0]`, the first untried permitted action in ruleset
  order (`agents/strategist.py:106-125`; orch `choose_action` 1055-1074).
- A clearance diagnosis at S1 therefore fits `elim.hepatic.<enzyme>.clspec` first (all enzymes matching the template,
  resolved by `fit_spec.resolve_fit_ids`, `fit_spec.py:108-127`).
- In a model system each analyte's studies are diagnosed apart and merged, parent first (orch 1013-1040, 887-904). A
  `fix_and_refit` is decided by the signed MAP's grades, else escalated (`_decide_pairs` 907-931).

**Execution of actions:** only `FIT_OPS = ("fit", "fix_and_refit")` produce a fit (orch 221, 438). There is no handler
anywhere for `branch`, `switch` or `switch_algorithm` (grep), and the algorithm stays "BOBYQA" (`fit_spec.py:220`; call
at orch 387-388). These actions are appended to `actions_tried` (`orch/campaign.py:153-154`), and the next round
re-simulates the unchanged CPF.

### Q4. Fit specification, bounds, policies, multistart, identifiability

**Candidates per stage:** `STAGE_PLAN` (map.py:41-73) is copied into the MAP stage plan (668-674).
- `max_rounds`: S1, S2 and SM = 4; S3 = 2; SJ = 1.
- SJ's candidates are "fitted in S1–S3": the parameters with status FITTED and `fitted_at_stage` in the training stages,
  with a fit policy (`orch/joint.py`, `joint_parameters`).

**Bounds and their sources:**
- Precedence in `fit_spec._bounds` (163-174): strategist override, then the CPF fit policy, then the plausibility range,
  else `FitSpecError`.
- The start value is the current value clamped into the bounds (247). A log-scaled policy writes `scale: log` and needs
  lower > 0 (256-261). `run_pi.R` optimises log(value) (`services/engine-worker/r/run_pi.R:13-14, 100-116`).
- The fit policy is signed in the MAP parameter table as `MapBounds` plus plausibility (`map.py:136-160, 417-432`).
  `cpf_differences` refuses runs whose CPF departs from the signed table (446-469; D-36).
- Where the policy comes from:
  - a person's estimation plan;
  - otherwise, under **D-37**, MS-01 §2.2's default bounds for every candidate a person neither frees nor holds fixed
    (`proj/plan.py:911-942`, `default_fits`; `campaign_cpf` 944-). The defaults are copied verbatim into
    `proj/fit_bounds.yaml` (version 0.1, UNVERIFIED; e.g. clspec [1e-4, 1e2], logP measured ±1.5 or predicted [−2, 7],
    perm.intestinal [1e-7, 1e-2], Weibull t50/shape [0.5×, 2×], fed factor [1, 50], fallback 0.1–10×).
- `:hold` / `:release` (plan.py:772-790) keep a candidate fixed or return it to the default.
- There is no default row for `kcat` or `vmax`, so those take the 0.1–10× fallback (INFERRED from fit_bounds.yaml:22 and
  its row list).
- The CPF validator enforces fit policy ⊆ plausibility (`cpf/models.py:166-171`).
- The strategist override is only checked for finiteness and lo < hi (`agents/strategist.py:88-98`), not against the MAP
  or plausibility. That is inactive today because no LLM decider is wired.

**Fit groups:** each member is simulated at f × start. The factor's bounds are intersected with each member's own bounds
(`fit_spec.py:130-155`). An error is raised if they leave no room.

**Weights:** stage fits weight every point equally. SJ uses w = √(N/(k·n)) per study (`fit_spec.py:199-211`;
orch 387-388). Example: two studies of 10 and 40 points give w = 1.581 and 0.791; each contributes w²·n = 25 to the
weighted sum of squares.

**Multistart** (`fitting.py`):
- Starts are a Latin hypercube in the bound-normalised (log for log-scaled) space, seeded (48-54).
- `plan_multistart` (116-140): the largest n_starts ≤ 32 fitting the budget minus the reserve, raising if fewer than 4.
  Example: budget 720 s, reserve 120 s, 200 evaluations per start, 2 simulations per evaluation, 1.5 s per simulation,
  16 cores. Then 2 cores per start, 8 parallel starts and 300 s per wave, so floor(600/300) = 2 waves and n = 16.
- `assess_fit` (193-242):
  - converged starts are clustered within 0.05 of the leader in unit space;
  - agreement = |best cluster| / converged (< 0.5 gives MULTIPLE_OPTIMA);
  - AT_BOUND within 1 % of the range;
  - HIGHLY_CORRELATED when |r| > 0.95, strongest pair first;
  - POORLY_DETERMINED when the CI width exceeds 100 % of the estimate.
- POORLY_DETERMINED is not mapped into `FitSignals` (`diagnostics.py:50-55`). The MAP escalation trigger "CV > 50% on a
  parameter the question depends on" (`map.py:124`) is therefore not enforced.

**Estimates back into the CPF** (`fit_spec.py:280-306`): new version, status FITTED, `fitted_at_stage`, provenance
`ParameterIdentification` with `supersedes`, and SD/CV %/CI95. A qualified `<compound>::<id>` goes to that compound's
CPF via `by_compound` (orch 634-656). `model_copy` does not re-validate, so the plausibility check is bypassed for
fitted values. This is INFERRED harmless, since bounds lie within plausibility.

**Identifiability, fix_and_refit by evidence grade** (`identifiability.py:26-91`):
- Grades run A > B > C > D (26); status FIXED beats PREDICTED, and FITTED and DERIVED are unranked (27).
- The grade decides when both have one and they differ, otherwise the status (66).
- An undecidable pair returns a reason string. The orchestrator then escalates, because "which one to fix is the
  modeller's decision" (orch 925-929).
- `fix_at_source` restores the signed MAP value and status, clears the CI and keeps the fit policy (79-91).
- The grades come from the signed MAP (`MapParameter.grade`, map.py:159; `evidence_grading.yaml` 0.1, UNVERIFIED,
  SME_SIGNOFF:34, 38).

### Q5. Round building

**Which studies each stage simulates** (`map.py:484-561`, `stage_coverage` 574-603):

| Stage | Studies |
|---|---|
| S1 | Internal IV-SD |
| S2 | Internal PO-SOL-FASTED. Internal PO-IR-FASTED when its CPF formulation is Dissolved, or when no internal solution study exists (§6.3) (`_training_stage` 484-499) |
| S3 | Internal PO-FED, and internal IR solids that are not Dissolved when a solution exists. An unresolvable formulation also goes to S3, which then reports why it cannot build (497-498) |
| SM | Metabolite-analyte copies of parent-stage scenarios (606-622) |
| SJ | Union of the training scenarios, relabelled SJ, in a derived MAP written next to the signed one (`orch/joint.py`, `joint_map`) |
| S4 | Every internal study that trained a stage (502-508) |
| S5 | External studies of core classes: IV-SD, PO-SOL, PO-IR, PO-FED, PO-MD, PO-MR, PO-OTHER (101-104, 509-510) |
| S6 | Simulates from the S4 scenarios (582) |

Flagged classes (DDI, PGX, SPECIAL, PRECLINICAL) are EXTERNAL for a planned application or SUPPORTIVE
(`split.py:370-386`). S5 notes list them (`map.py:585-594`).

Split details (`split.py`):
- S1 takes the single highest-scoring IV-SD (389-401).
- S2 takes the best study at the lowest and at the highest fasted SD dose, per-kg doses only when no absolute dose
  exists (404-437).
- Fed (rule 5): food effect in question, or measured fed solubility, makes every fed study EXTERNAL; otherwise one fed
  study is INTERNAL (440-469).
- Everything else becomes EXTERNAL (472-474).
- Rule 3 rebalancing covers only the "fasted oral", "fed" and "multiple-dose" categories (482-486). MS-01's "other dose
  level" and "other formulation" are not enforced.
- Model systems split each analyte on its own (521-540).
- Information score = n × timepoints × (w_stat + 0.3 for excreta + 0.3 for multiple dose levels) (297-305). Example: n 12,
  15 points, mean ± SD with urine gives 12 × 15 × 0.9 = 162.
- Classification quirk: an IV multiple-dose study falls through to PO-OTHER (280-294).

**Simulation construction** (`round_build.py`):
- **Individual** per scenario (90-111): population, sex and age; weight and height as OriginData when given
  (`snapshot/builder.py:730-748`); or the published model's own individual.
- **IV** (252-270):
  - bolus when no infusion time and route `iv_bolus`;
  - infusion requires `infusion_time_min`, else `ScenarioBuildError`;
  - other routes raise (272).
- **Oral**: solution/suspension without a named formulation → Dissolved (203-204); otherwise the CPF formulation
  (Weibull, Dissolved, Particles or ParticleBins) from `cpf_formulation` (`cpf/formulations.py:101-136`). The study's
  formulation name must match, or be the CPF's only one (139-151).
- **MD** (114-135):
  - DI_24 / DI_12_12 named intervals with End time n × τ;
  - any other interval as schema repetitions;
  - `dose_phases` for loading/maintenance;
  - the simulation end is extended to cover the regimen and the last sampling time (138-145; default 24 h, 54).
- **Fed** (224-238):
  - explicit `meals` give one event per meal at their times; a pre-dose meal shifts the dose start (210-218);
  - otherwise one event with the MAP's single `meal_template` at t = 0;
  - the default is "Meal: High-fat breakfast (Human)" (`map.py:640`), applied to every fed study (`map.py:546`);
  - no caller passes `meal_template` (grep), and `StudyRecord.meal_type` is unused.
  - Food-state-specific property alternatives come from `alt.select` (`cpf/build.py:97-118`; round_build 148-154, 241).
- **Model system** (281-319): each dosed compound gets the protocol at dose × product fraction. Metabolites in the
  formation closure are co-compounds, and published observers are included when all their members are present.
- **Unbuildable scenarios:** they raise in fit stages and are skipped with "NOT SIMULATED" in validation stages
  (`skip_unbuildable`, 365-398).
- **Build notes:** "NOT PLACED IN THE MODEL" (unresolved CPF ids) and "NOT ACTIVE IN THE MODEL" (missing expression)
  (322-346).

### Q6. Prediction S6 and VBE

**Sensitivity** (`prediction.py`):
- Candidates are numeric FITTED or PREDICTED records (48-52), varied by the engine's local `sensitivity` task at ±10 %
  (31; `orch/package_activities.py:110-117`, `variation_range`; `run_job.R:243-258`).
- Results are parsed for AUC_inf, AUC_tEnd and C_max on the first "Plasma (Peripheral Venous Blood)" quantity (34,
  121-138).
- **Not implemented:**
  - the EMA worst-case list (10-fold CYP abundance, 30-fold transporters), required by MS-01 §4 S6 and by
    `evidence_requirements.sensitivity_ranges` (acceptance yaml 70-74) (grep: no hit);
  - DDI, paediatric, organ-impairment and FIH applications. The docstring says "next phase (T-31)" (13-14).

**Uncertainty** (54-100):
- FITTED records with SD > 0. n = 200 [SME] (30). Draws are independent; the correlation matrix is not propagated (70).
- Log-scaled policies draw mean·exp(N(−σ²/2, σ)) with σ = √ln(1 + CV²). That keeps the arithmetic mean at the estimate,
  so the median falls below it.
- Others draw normally. Both are truncated to the policy (or plausibility) bounds by rejection (81-88).
- P5/P50/P95 of AUC (to t_last) and Cmax from the batch CSV (93-118).
- Example: CV 30 % gives σ = 0.2936.

**VBE** (`vbe.py`, `bioequivalence.py`, template `vbe-crossover` 0.2.0-draft DRAFT):
- PK is read per individual from `pk_analyses.csv` for AUC_inf and C_max (23-52).
- The trials (108-144): individuals with a positive finite value of every metric in both arms are kept, and the others
  named. Trials are formed in id order, `min(K, N_kept // n)` of them.
- Each trial is the paired log-difference CI with t-quantile df = n − 1 (`bioequivalence.py:33-62`). It passes iff
  lower ≥ L and upper ≤ U (29-30). No rounding to 2 decimals.
- PoS per metric = passing / run; joint PoS = every metric passing in the same trial.
- Outputs: GMR median, P5, P95, and the reference-arm between-subject CV √(e^{s²} − 1).
- `meets_threshold` = joint PoS ≥ `pos_threshold`.
- Worked example: n = 24, mean log-difference −0.02, SD 0.15. Then SE = 0.0306, t₀.₉₅,₂₃ = 1.714 and the 90 % CI is
  [0.930, 1.033], which passes 0.80–1.25.

**F-304 gate** (`vbe.py:72-100`):
- No observed BE summary gives `NOT_VALIDATED` (D-19).
- Otherwise, per metric: simulated/observed between-subject CV within `cv_fold`, and the observed GMR within the
  simulated P5–P95.
- `cv_fold` is the template's `fold: 1.5`, marked `verified: false` (template line 85; orch/vbe_activities.py:154).

Template limits:
- standard 0.80–1.25 at a 90 % CI, `verified: true`;
- NTI 0.90–1.1111, `verified: false`, "[VERIFY]" (50-62).

The design inputs (variability, n, K, seed, PoS) are `never_default` (21-34). `MapDocument.sign` refuses a MAP whose
application inputs are incomplete (`map.py:389-396`, `MapApplication.problems` 297-317).

The SME list records an illustrative run: AUC GMR 0.979, Cmax 0.880, PoS 100 %, NOT_VALIDATED (`docs/SME_SIGNOFF.md:80-83`).

### Q7. Model systems and metabolites (`pd/system.py`)

**What a ModelSystem holds** (61-101):
- several CPFs;
- roles (parent or metabolite; at least one parent);
- formation links (compound, process, molecule, data source → metabolite);
- products with dose fractions (required, never defaulted; every parent must be dosed);
- verbatim published observers;
- analytes (compound or observer, each with an output path).

`single(cpf)` makes the trivial system (103-107). `closure` gives the dosed compounds plus every metabolite formed
transitively (119-130). The content hash excludes CPF timestamps (132-137).

**Subjects** (207-226): which compounds a study informs.
- A compound analyte informs itself.
- A molar sum of compounds sharing one MW (a racemate) informs all members.
- A mass sum, a sum of different MWs, or an unknown analyte informs none, with the reason
  (`analyte_molecular_weight`, 177-198).

**Gating** (229-246): parent analytes are gated at every stage. Metabolite analytes are reported at S1–S3 and gated at
SM, SJ, S4 and S5 (`METABOLITE_STAGES`, 204). Mixed-role sums are never gated.

**Formation targets** (249-264): the `.kcat` / `.clspec` record of the forming process on the forming compound.

**Consumers:**
- `map._system_scenarios` adds output paths and gated flags, and duplicates metabolite studies at SM (map.py:606-622).
- `round_build._system_scenario` builds the multi-compound simulations.
- `build_from_system` sets `metabolite` on the forming process (cpf/build.py:686-692).
- Fit ids for other compounds are qualified `<compound>::<id>` (`fit_spec.py:39-67`).

**PK-Sim evidence:** the Verapamil system refit escalated at S1, with formation kcats at their bounds and the racemic
sum AUC at 0.46×. The co-parent's shifted parameters are not S1 candidates for the sum analyte (SME_SIGNOFF:75-78). This
is an open scientific design question.

### Q8. CPF → snapshot builder

**Compound** (`cpf/build.py:494-613`):
- Required: MW, logP and fu (505-518); missing ones raise "run S0 completeness first".
- Optional: solubility at reference pH, or a pH-solubility table; intestinal and cellular permeability; alternatives per
  formulation and food (`@<alt>` ids); binding partner; calculation methods; pKa (acid/base); halogens; `cmpd.<name>`
  passthrough; process-selection molecule maps.

**ValueOrigin:**
- The source is coerced to the harvested enum {ParameterIdentification, Unknown, Publication, Database, Other} via
  aliases. The raw label is kept in the description (`cpf/build.py:367-378`; `snapshot/models.py:21-49, 64-78`).
- The method is kept only if it is in the harvested set.
- This is the guard against the "raw ValueOrigin label dropped the simulation" incident (models.py:21-24).

**Processes** (`_build_process` 411-460; builder `HARVESTED_PROCESSES` 386-405), grouped per (type, molecule, data
source) (463-491):
- Specific first-order (CLspec/[Enzyme]).
- Specific Michaelis-Menten. Needs Vmax **and** Km; kcat and enzyme concentration are optional.
- Liver-microsome MM.
- Active transport MM (needs Vmax and Km).
- Competitive inhibition and induction.
- Specific binding.
- GFR.
- Harvested tables: intrinsic first-order, rCYP450 MM and first-order, LiverClearance, KidneyClearance, transport Hill,
  vesicular MM, and irreversible, mixed and non-competitive inhibition.

A process missing a required parameter, or of an unknown type, sends its ids to `unresolved`. Process-family ids
(`elim.`, `transp.`) that nothing placed are added as `unbound` (596-606).

**Selections** (`snapshot/validation.py:16-45`):
- molecule processes are selected as `{Molecule}-{DataSource}`, plus `MetaboliteName` when they form a metabolite;
- GFR, Hepatic and Renal are systemic selections;
- inhibition and induction are selected as simulation `Interactions` on the same compound (auto-interaction);
- references are integrity-checked (54-124).

**Individuals:**
- `indiv.*` physiology overrides and the seed (279-356).
- Expression profiles of every process protein: the CPF's own published document, else the harvested library of 40
  molecules (`expression.py`), with `expr.*` overrides (169-276). A missing profile is reported (`missing_expression`).
- `sim.*` / `sim[route].*` simulation-level parameters per route (306-341).

**Protocols:** oral, IV infusion, IV bolus, multiple dose (DosingInterval or schema repetitions), phases and binned
products (builder 762-986). **Formulations:** Dissolved, Weibull (t50, shape, lag, "Use as suspension"), Particles
(monodisperse) and ParticleBins (`cpf/formulations.py:33, 101-136`; builder 988-1061). **Events:** meal templates with
changed parameters (1063-1072).

**Simulation:**
- model "4Comp";
- plasma outputs for every compound plus additional outputs;
- output schema 0–2 h at max(res, 60) pts/h, then the default 10 pts/h (1085-1137);
- always an Individual, never a Population (1272-1302). The VPC population is generated by the engine task.

**Builder determinism and units:** quantities must already be in PK-Sim storage units or the builder rejects them
(builder.py:1-9).

**Known gaps:**

| Gap | Evidence | Status |
|---|---|---|
| Lint80 and table release formulations; particle d50 fit | formulations.py:24-25 comment; no S3 candidate | not implemented |
| Fed solubility factor | registry has only `origin` for `food.` (registry.yaml:102); no `pksim_compound`; `pksim_parameter_path` raises (pksim_paths.py:65-71); not a process family, so silently not placed and not reported | CONFIRMED gap; also continuation §4.1 S3 row |
| Tubular secretion `elim.renal.ts_clspec`, biliary `elim.biliary.cl` | fixed prefix `elim.renal` → GFR table only (process_bindings.py:19-20); no "elim" family in `PROCESS_FAMILY` (osp_import.py:96-112) | not placeable; shown as unresolved if present; dropped by `_fittable_candidates` |
| DDI victim–perpetrator merge | `snapshot_builder.merge_victim_perpetrator` named in ddi-cyp3a4-victim.yaml:24 does not exist (grep) | placeholder |
| PD / MoBi modules | MS-01 §6.9 | out of scope |
| Catalog binding verification | `cpf.binding.bind` unused | unwired |
| EHC fraction | placed on the Individual (registry.yaml:76-77; build.py:279-292) but very likely also listed in `unresolved` (see D5) | inconsistency |

Stale docs:
- `cpf/build.py:6-7` says MM, transporters, total clearance and DDI are unresolved. They are now built.
- `round_build.py:13-15` says weight and height are deferred. They are written (split.py:93-95, builder 739-741).
- `round_build.py:55-57` says other dosing intervals raise. They become repetitions (131-133).
- The continuation doc's P5 row says the log scale never reaches `run_pi.R`. The code passes it
  (`fit_spec.py:256-261`, run_pi.R:13-14).

### Q9. SME-governed / UNVERIFIED content and implications

Status per file is in §5 below; the SME list is `docs/SME_SIGNOFF.md` §1-§4. Every ruleset, the parameter registry, both
analysis templates, `fit_bounds.yaml`, `evidence_grading.yaml`, the 10 % default internal target, and MS-01 v1.1–v1.3
(SJ, feedback cycles, SM) are UNVERIFIED, DRAFT or owner-approved-only.

Implications (INFERRED from code behaviour):
- The acceptance and diagnostics code never checks `status`. Every gate verdict is produced by UNVERIFIED criteria, and
  regulatory use depends on the reports labelling them. The only exception is `ddi_static.screen`, which refuses a
  non-`SME_APPROVED` ruleset without `allow_unapproved` (ddi_static.py:92-96).
- The MAP records ruleset id@version; `diag_ruleset_version()` appends `-UNVERIFIED` (diagnostics.py:91-93), but the
  acceptance id string does not carry the status (`map.py:480`).
- The MAR adds an explicit "DRAFT and UNVERIFIED" limitation for templates (`report/campaign_mar.py:196`).
- Under ICH M15 the technical criteria must be pre-specified and commensurate with risk. They are pre-specified via the
  signed MAP (D-35), but their scientific basis (e.g. the medium 1.5-fold "EMA" attribution, the Guest citation) is
  disputed in the repo's own SME note. A regulator-facing package built today would rest on owner-approved, not
  SME-approved, criteria.

---

## 5. Ruleset table

| File | Version | Status | What it governs | Key thresholds |
|---|---|---|---|---|
| pd/rulesets/pbpk_acceptance_criteria.yaml | 2026.2-draft | UNVERIFIED | Tier limits for AUC/Cmax and DDI ratios; min fraction within; evidence requirements | high 1.25×, all studies; medium 1.5×, ≥ 80 %, DDI Guest δ = 2; low 2×, ≥ 80 %; VPC > 100 individuals; worst-case 10× CYP / 30× transporter |
| pd/rulesets/diag_rules.yaml | 0.6 | UNVERIFIED | §5 evidence → cause → actions per stage | ratio band 0.8–1.25; dose trend 25 %; starts agreement 0.5; exposure fallback 1.5× |
| pd/rulesets/dissolution_similarity.yaml | 2026.1-draft | UNVERIFIED | f2 conditions, profile checks, rapid-dissolution rule | f2 ≥ 50; 12 units; ≥ 3 points; ≤ 1 point > 85 %; CV ≤ 20 % to 10 min, ≤ 10 % later; very rapid 85 % in 15 min; plateau 2 pts ≤ 2 pp below 85 % |
| pd/rulesets/ddi_static_screening.yaml | 2026.1-draft | UNVERIFIED | ICH M12 basic static screens | R1 ≥ 1.02; R1,gut ≥ 11 (0.25 l); R2 ≥ 1.25 (5×Imax,u); R3 ≤ 0.8 (10×Imax,u, d = 1) |
| pd/parameters/registry.yaml | 1.2 | UNVERIFIED | CPF id placement, storage units, PK-Sim names, review bounds, S0 gate | e.g. fu [0, 1]; logP [−10, 15]; perm.intestinal [0, 1] cm/min; ehc_fraction on the Individual; S0: MW, logP, fu, solubility or table, pKa or neutral, any `elim.*` except fe/fm |
| pd/analysis_templates/vbe-crossover.yaml | 0.2.0-draft | DRAFT | VBE design, limits, F-304 | standard 0.80–1.25 at a 90 % CI (verified); NTI 0.90–1.1111 ([VERIFY]); CV within 1.5× (verified: false); observed GMR in simulated P5–P95 |
| pd/analysis_templates/ddi-cyp3a4-victim.yaml | 1.0.0-draft | DRAFT | CYP3A4 victim DDI | Guest δ = 2, ≥ 0.8 within; GMFE(AUCR) ≤ 1.25; n = 1000 population; no runner |
| proj/fit_bounds.yaml (out of L0, used by D-37) | 0.1 | UNVERIFIED | Default fit bounds from MS-01 §2.2 | clspec [1e-4, 1e2]; logP ±1.5 / [−2, 7]; Weibull [0.5×, 2×]; fed [1, 50]; fallback 0.1–10× |
| MS-01 (`MS01_VERSION`, map.py:81) | 1.3 | FINALIZED v1.0; v1.1–1.3 UNVERIFIED | The procedure; budget split | S0 1 / S1 20 / S2 20 / S3 7 / SJ 15 / S4 5 / S5 5 / S6 20 / S7 7 %; SM 10 % with the others × 0.9 (map.py:76-80) |

Budget worked example (map.py:666-672) for 3600 s: S1 720, S2 720, S3 252, SJ 540, S4 180, S5 180, S6 720, S7 252,
S0 36. With SM: SM 360 and every other stage × 0.9 (S1 648, …).

---

## 6. Glossary (grounded in the repo)

**Plans, stages and gates**
- **MS-01**: the PBPK modelling standard the platform executes, embedded in each MAP (`docs/PBPK_MODELING_WORKFLOW.md:1-19`).
- **CPF (Compound Parameter Framework)**: an immutable, versioned per-compound parameter document. Each record holds a
  value, unit, status, fit policy, plausibility, provenance, engine binding and uncertainty (`cpf/models.py:145-261`).
- **MAP (Model Analysis Plan)**: the signed, hashed plan with parameter table, studies, split rationale, stage plan,
  scenarios, acceptance, seeds, applications and risk assessment (`campaign/map.py:335-414`).
- **Stage / round / gate / escalation**: MS-01 §0 vocabulary. A stage loop runs rounds until the gate passes or it
  escalates to a person.
- **Study class**: IV-SD, PO-SOL-FASTED, PO-IR-FASTED, PO-FED, PO-MD, PO-MR, PO-OTHER, DDI, PGX, SPECIAL, PRECLINICAL
  (`split.py:23-34`).
- **INTERNAL / EXTERNAL / SUPPORTIVE**: fit (training), validate (test), context only (`split.py:42-45`).
- **Information score**: n × time points × statistic weight (+ bonuses), the split ranking (`split.py:297-305`).
- **SJ**: joint refinement of S1–S3 (+ SM) parameters over all internal studies with equal study weights (`orch/joint.py`).
- **S1-CI guard**: in SJ, an S1-fitted parameter is held within its S1 95 % CI (`orch/joint.py`, `joint_parameters`).
- **SM**: the metabolite fitting stage for model systems (map.py:58-65).
- **D-35 / D-36**: a run is judged by the signed criteria; a run's CPF must match the signed parameter table
  (`map.py:263-267, 446-449`).

**Acceptance and PK metrics**
- **Fold error / ratio**: predicted/observed (`acceptance.py:107`).
- **PE %**: (pred − obs)/obs × 100 (`acceptance.py:47-50`).
- **Internal target**: the MAP's stricter |PE| ≤ t % on internal AUC/Cmax, never looser than (1 − 1/f) × 100
  (`acceptance.py:38-44`).
- **Tier / model risk**: the ICH M15 rating low/medium/high selecting the limits (`m15.py:17-39`).
- **GMFE**: geometric mean fold error, 10^mean|log10 ratio| (`metrics.py:41-45`).
- **Guest limits**: the variable acceptance range for DDI ratios, limit = (δ(R − 1) + 1)/R (`metrics.py:58-71`).
- **VPC**: visual predictive check; share of observed points inside the 5–95 % band of a 100-individual population
  (`campaign/vpc.py`).
- **NCA**: deterministic non-compartmental analysis (`nca.py`).
- **AUClast / AUC_tEnd**: AUC to the last time; the gate's AUC kind (`evaluate.py:10-13`).
- **λz / adjusted R²**: terminal slope selected by best adjusted R² (`nca.py:73-135`).
- **Early ratio / Vss ratio**: IV profile-shape evidence (`evaluate.py:105-106, 218-241`).

**Diagnostics and fitting**
- **diag-rules / evidence label / permitted action**: the ruleset mapping labels to ordered `"{op} {target}"` actions
  (`diagnostics.py:1-16`).
- **Strategist**: an advisory chooser restricted to permitted actions. Today it is deterministic, first untried
  (`agents/strategist.py:106-144`).
- **fix_and_refit**: fix the more reliable member of a correlated pair at its signed value and refit the rest
  (`identifiability.py`).
- **Evidence grade A–D**: source reliability from `evidence_grading.yaml`, recorded per parameter in the MAP (`map.py:157-159`).
- **Fit policy**: the stages at which a parameter may be fitted, with bounds and scale (`cpf/models.py:33-47`).
- **Plausibility**: the range a fit may never exceed (`cpf/models.py:50-61`).
- **Fit group**: parameters fitted as one factor f ("Use as Factor") (`cpf/models.py:64-88`).
- **D-37 hold/release**: unfreed MS-01 candidates get MS-01 default bounds as their fit policy unless held fixed
  (`proj/plan.py:911-942`).
- **No-regression gate**: earlier passed stages re-judged after a later CPF change (MS-01 §4 SJ; orchestrator).

**Model systems**
- **Model system / analyte / product / observer**: several compounds simulated together; what a study measures; dose
  fractions per administered product; a published sum (`system.py`).
- **Gated / reported**: whether a study enters the gate and fit at a stage, or is only shown (`system.gated`, `evaluate.py:179`).
- **Formation target**: the forming process's kcat/clspec on the forming compound (`system.py:249-264`).

**Engine and snapshot**
- **ValueOrigin**: the PK-Sim provenance block (Source, Method, Description). Source is restricted to the harvested enum
  (`snapshot/models.py:21-78`).
- **Engine binding**: where a CPF value lives in PK-Sim (building block, parameter, process:molecule, data source,
  route) (`cpf/models.py:114-142`).
- **Alternative / alt.select**: per-formulation/food property alternatives chosen per simulation (`cpf/build.py:81-118`).
- **Expression profile**: the per-protein ontogeny and expression, harvested from the OSP models (`expression.py`).
- **Published individual**: a reference model's own individual for one study (`split.py:147-162`).

**Applications, VBE and data**
- **Analysis template / never_default**: a versioned application recipe; inputs a person must give
  (`analysis_templates/__init__.py:1-38`).
- **PoS**: probability of success, the share of virtual trials passing BE (`vbe.py:130-136`).
- **F-304 / NOT_VALIDATED**: the VBE validation gate against an observed BE study (`vbe.py:72-100`).
- **Real-data rule (D-19) / TEST ONLY**: only real-origin data can sign a non-exploratory verdict (`data_origin.py`).
- **UNVERIFIED / SME_APPROVED / DRAFT**: governance status of a ruleset or template (`docs/SME_SIGNOFF.md:7-11`).

---

## 7. Defects and risks

Labels: CONFIRMED = traced in code; POTENTIAL = plausible from code, not demonstrated.

**Action execution, evidence wiring and missing checks**
- **D1 CONFIRMED** — **branch / switch / switch_algorithm actions are no-ops.**
  - `FIT_OPS = ("fit", "fix_and_refit")` (orch/campaign_activities.py:221). There is no handler for the other operations
    (grep), and the algorithm is fixed at BOBYQA (fit_spec.py:220; orch 387-388).
  - Partition-method branching (MS-01 S1), the Michaelis-Menten switch (§6.4) and DEoptim (multiple optima) each burn a
    round on an unchanged CPF, then escalate.
- **D2 CONFIRMED** — **Five evidences never computed:**
  - `secondary_peak`, `accumulation_off`, `permeability_shape_off` and `FedSignals` are only defaults (diagnostics.py:42-63).
  - Only `early_phase_off` and `vss_off` are set (orch 999-1000).
  - The EHC, time-dependent clearance, permeability-limited, fed-solubility and gastric-emptying rules cannot fire.
  - An MD auto-induction mismatch therefore produces no escalation from diagnostics.
- **D3 CONFIRMED** — **The distribution rule cannot fire for an IV bolus.** `_profile_shape` returns None when
  `infusion_time is None` (evaluate.py:222). evaluate_round passes `infusion_time_min`, which is None for a bolus
  (orch ~781). A bolus has T = 0, so the guard is wrong for bolus studies.
- **D4 CONFIRMED** — **The fed sub-loop is impossible.**
  - `food.fed_solubility_factor` has no placement or path (registry.yaml:102; pksim_paths.py:65-71). It is dropped by
    `_fittable_candidates`.
  - A value under that id in the CPF is not placed in the snapshot and **not reported as unresolved**: `food.` is not a
    builder process family (build.py:596-606).
  - The S3 fed gate (Guest-style fed/fasted ratios, MS-01 S3) has no code at all.

**CPF and S0 placement**
- **D5 CONFIRMED (static trace, not executed)** — **`elim.ehc_fraction` is likely reported as unplaced.**
  - `_compound_from_cpf` marks as `unbound` every `elim.*` / `transp.*` id not consumed by the compound (build.py:596-606).
  - The Individual-bound `elim.ehc_fraction` (registry 1.2, `proj/inputs.py:348-352`) is consumed only later by
    `_with_individual_parameters`.
  - So `unplaceable_parameters` would list it, the S0 gate fails (orch 153, 162), and the round notes say
    "NOT PLACED IN THE MODEL" while it is in fact placed.
  - No test covers this path (grep).
- **D6 CONFIRMED** — **The S0 "elimination pathway" check is satisfied by any `elim.*` id** except fe/fm
  (registry.yaml:122-125). That includes `elim.ehc_fraction`, which is not a clearance. It is mitigated by the
  separate unplaceable check, but the completeness message is misleading.
- **D7 CONFIRMED** — **One meal template for all fed studies.** It is the default "Meal: High-fat breakfast (Human)"
  (map.py:640, 546). No caller sets it, and `meal_type` is unused. This contradicts MS-01 S3, "template matching the
  study's meal".
- **D8 CONFIRMED** — **An internal PO-MD/MR/OTHER study gets no scenario** (map.py:93-98, 506-508). The split never
  assigns one INTERNAL (split.py:472-474). A person's P5 placement could, and the study would then be silently neither
  trained nor validated in S4 (POTENTIAL consequence). MS-01 S2's "multiple-dose check" is not implemented.
- **D9 CONFIRMED** — **MS-01 checks missing.**
  - S1 t½ within 1.5-fold (flag); S2 tmax within 2-fold or ±1 h (flag).
  - The MD accumulation ratio, and the dose-range check as an explicit branch (only a diagnostic trend exists).
  - The "CV > 50 %" escalation, although it is listed in `ESCALATION_TRIGGERS` (map.py:124; FitSignals lacks it,
    diagnostics.py:50-55).
- **D10 CONFIRMED** — **S6 is incomplete.** Sensitivity is only ±10 % (prediction.py:31), with no EMA worst-case
  ranges. Uncertainty ignores correlations (70). There are no application templates other than VBE.
- **D11 CONFIRMED** — **Split rule 3 is partial.** The "other dose level" and "other formulation" external categories
  are not enforced (split.py:482-486).

**Guardrails, unwired code and docs**
- **D12 POTENTIAL** — **Unconstrained bounds override.** The strategist override is only checked lo < hi
  (agents/strategist.py:88-98) and is used verbatim (fit_spec.py:164-166). Once an LLM decider is wired it could widen
  beyond the signed MAP or plausibility, against MS-01 §2.2's "never widen". It is inactive today.
- **D13 CONFIRMED (cross-slice)** — **"Best round so far" is the last round.** `best_cpf_uri` is overwritten every round
  (orch/campaign.py:124), so an escalation hands over the last round, not the best.
- **D14 POTENTIAL** — **Uncertainty sampling issues.**
  - `sample_parameters` rejection sampling has no iteration cap (prediction.py:81-88). It hangs if the bounds hold
    negligible probability mass.
  - The log-normal is centred on the arithmetic mean (84), not the log-scale estimate the engine's log-scale CI is
    centred on.
- **D15 POTENTIAL** — **Model-system CSV parsing.** `results_csv_pk` / `parse_sensitivity` take the first plasma
  column/quantity (prediction.py:109, 128). In a model system they may read the wrong compound.
- **D16 CONFIRMED** — **Unwired or dead code.**
  - `cpf.binding.bind` (T-03 catalog check, no callers);
  - `snapshot.parameter_transfer` (no callers);
  - `ddi_static.screen` (no callers);
  - the AUCR/CmaxR acceptance path (no producer);
  - `fitting.estimate_population_algorithm` (no callers);
  - the DDI template step `snapshot_builder.merge_victim_perpetrator` (ddi yaml:24), which does not exist.
- **D17 CONFIRMED** — **Stale documentation inside code and docs**: see Q8 (build.py:6-7, round_build.py:13-15 and
  55-57, the continuation P5 log-scale remark).
- **D18 CONFIRMED** — **The output schema deviates from MS-01 §2.3** (20 / 4 pts/h [SME]). The code uses 60 / 10
  (builder.py:1122-1137, 1093). The dense window covers only the first 2 h after the first dose, so later MD peaks are
  sampled at 6-min resolution (INFERRED effect on Cmax small).

**VPC, ruleset and metric details**
- **D19 CONFIRMED** — **VPC limitations.** The population is single-sex (orch 557), and SM has no VPC (vpc.py:17-18 vs
  MS-01 SM "as S1"). INFERRED scientific risk: coverage on mean data is weak evidence.
- **D20 CONFIRMED (minor)** — **Unused `routes` field.** The rule `routes` field in diag_rules.yaml is ignored by
  `diagnose` (diagnostics.py:249).
- **D21 CONFIRMED** — **The default internal target is 10 %** (UNVERIFIED; proj/brief.py:512). Combined with IV Cmax
  being gated, most published models would fail S1 (INFERRED from SME_SIGNOFF:20, 70-71).
- **D22 CONFIRMED** — **Candidate tokens that can never be fitted by diagnosis:**
  - `bind.fu` (no rule) and `perm.cellular` (unwired rule) at S1;
  - `elim.renal.ts_clspec` and `elim.biliary.cl` (no binding);
  - `phys.logp` is absent from S2 although MS-01 §2.2 allows "S1 (S2 if no IV)" (map.py:49-55), so the §6.1 no-IV path
    cannot fit logP.
- **D23 CONFIRMED** — **An IV multiple-dose study is classed PO-OTHER** (split.py:280-294).
- **D24 POTENTIAL** — **The round GMFE pools everything.** It mixes all studies regardless of role, analyte or gating
  (evaluate.py:263-271). SJ's "agreement" criterion uses it (joint.py `agreement`).
- **D25 CONFIRMED** — **Gates run on unapproved rulesets.** The acceptance and diagnostic rulesets are used regardless of
  status; only `ddi_static` refuses an unapproved ruleset (ddi_static.py:92-96).
- **D26 CONFIRMED (minor)** — **Weak upload guard.** `_fittable_candidates` lets a parameter whose policy has an empty
  stage tuple, or which has only plausibility, be fitted at any stage (orch 826-830). This contradicts MS-01 "anything
  not listed is never fitted". D-37 always sets stages, so the risk is limited to hand-written CPFs.
- **D27 CONFIRMED (minor)** — **Metric details.**
  - The BE pass test has no rounding to 80.00/125.00 (bioequivalence.py:29-30).
  - Guest limits collapse at R_obs = 1 (metrics.py:69-71).

---

## 8. Open questions

1. **IV Cmax at S1:** should S1 judge a short-infusion IV Cmax, or only AUC and t½? This is open for the SME
   (SME_SIGNOFF:20), and with D21's 10 % internal target it decides whether any published model passes S1.
2. **Branch and switch actions:** are the partition/permeability-method branches, the MM switch and DEoptim meant to be
   wired? If so, how will a "branch" round be compared (MS-01: "lowest objective that passes the gate, ties by fewer
   parameters")? There is no code for this comparison.
3. **Fed sub-loop:** when will `food.fed_solubility_factor` get a harvested engine binding? What computes `FedSignals`
   (fed/fasted ratios) and the S3 Guest-style fed gate?
4. **D5:** does a real campaign with an `elim.ehc_fraction` record fail S0? This needs an executed test of
   `unplaceable_parameters` on such a CPF.
5. **Meals:** should the meal template come from `meal_type` per study? The template list is marked
   "[VERIFY template list from catalog harvest]" in MS-01 S3.
6. **Rule 3 split:** are the missing "other dose level" and "other formulation" rules an intended simplification?
   Should the split refuse internal PO-MD placement, or should S2 simulate it?
7. **S6 for regulatory use:** are the EMA worst-case sensitivities and correlated parameter sampling planned? Is the
   arithmetic-mean-preserving log-normal intended?
8. **VPC design:** should the VPC use a mixed-sex population matching the study? Is VPC coverage on mean data acceptable
   evidence, or should the gate use observed SD/percentiles (acceptance `evidence_requirements.vpc_percentiles`)?
9. **Ruleset sources:** what replaces "ema_pbpk_reporting" as the source of the medium 1.5-fold? Should the Guest title
   be corrected? Should the high-tier 1.25-fold apply to base PK or only to the decision metric (SME note, Finding 2)?
10. **Governance enforcement:** will production runs (GxP) refuse UNVERIFIED acceptance and diagnostic rulesets, as
    `ddi_static` does? Or is the labelling in the MAR the only control?
11. **Co-parents and racemic sums:** should S1 fit a co-parent's parameters against a racemic sum (SME_SIGNOFF:75-78)?
    Today only the subject compounds' own candidate tokens are offered.
12. **Strategist bounds:** when an LLM strategist is enabled, will its bounds override be clipped to the signed fit
    policy and plausibility (D12)?
