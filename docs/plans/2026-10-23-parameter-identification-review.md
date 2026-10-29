# Parameter identification: are we fitting, and is it sound PBPK? (review and plan)

Status: **in progress** (2026-10-29). The owner decided: PI-1 pin 2.2.0 (merged, #100); PI-2 (merged, #101, its golden
case qualified on PK-Sim in run 40080162775; correlations recorded and flagged). On 2026-10-25: **PI-3 stays linear**
with the log-sampled multi-start, and a parameter transform is proposed upstream (options (c) + (b); the draft request is
`docs/upstream/2026-10-25-osp-pi-log-scale-request.md`, not sent until the owner has reviewed it). **PI-2b is built**
(merged, #103). On 2026-10-29: **grade vs status goes into the SME grading rubric** (option (c)), and **PI-4 is next**.
Science items are UNVERIFIED and go to the SME (T-30) before they bind anything.

The owner asked (2026-10-23): "are we doing or running Parameter Identification, are many of the simulation is just
running and not fitting actually? Follow all principles of PBPK modeling." This document answers from the code and
the PK-Sim records, lists where the method departs from PBPK practice, and proposes a plan.

## 1. The short answer
- **Parameter identification exists and works on PK-Sim.** `services/engine-worker/r/run_pi.R` drives
  `ospsuite.parameteridentification` 2.2.0: BOBYQA, Latin-hypercube multi-start (4–32 starts, sized to the stage
  budget), log-scale residuals, equal weight per study (B2). It has run on real PK-Sim in the reference refits:
  Dapagliflozin S1 clearance fit, GMFE 2.478 → 1.412 (Actions run 39286267822), and the Rifampicin kcat refit.
- **In the T-56 path, no fit has run yet.** You are right that those campaigns only simulated:
  - 2026-10-22 run: before D-37, no candidate had fit bounds, so the diagnosis had nothing it could fit.
  - 2026-10-23 run: S1 ran the baseline, then a partition-method branch, then escalated. Most likely the plan was
    signed before D-37 was deployed, so logP had no bounds (not yet confirmed on the server).
  - PR #97 makes every future record say which fits ran, which could not and why.
- **Even where a fit runs, part of the method falls short of PBPK practice** (§3). The most important gap: the
  platform fits parameters the data cannot separate, and its identifiability checks are wired but never fed.

## 2. How a stage fits today
1. Simulate the stage's training studies (MS-01 split: S1 IV, S2 oral fasted, S3 fed/formulation, SM metabolites).
2. Judge them against the signed MAP's criteria (D-35).
3. If they fail, the diagnosis (`diag_rules.yaml` 0.6) names the cause and its permitted actions in order, for
   example *clearance off* → fit `elim.hepatic.{enzyme}.clspec`, then kcat, GFR fraction, tubular secretion, logP;
   *distribution off* → branch the partition method, then fit logP.
4. One action per round: a fit runs the multi-start on the training studies, applies the best estimate to a new
   CPF version, and the next round re-judges. At most 4 rounds (S3: 2), within the stage's MAP budget.
5. The no-regression gate (T-52) re-judges earlier stages; SJ (T-53) may refit jointly.

## 3. Findings against PBPK practice
Each finding names its evidence. **Severity:** high = can give a wrong or unjustified model; medium = weakens the
evidence; low = clarity.

| # | Finding | Evidence | Severity |
|---|---|---|---|
| F1 | **Parallel pathways fitted together from data that cannot separate them.** `{enzyme}` expands to every hepatic enzyme: Dapagliflozin's S1 fits Hepatic-CYP, UGT1A9 and UGT2B7 clspec at once from one IV microdose study. Plasma data identify total hepatic clearance only; the split (fm) needs in vitro phenotyping, metabolite or mass-balance data. | `fit_spec.resolve_fit_ids`; the reference refit ended with UGT1A9 at its lower bound and UGT2B7 at its upper bound. | high |
| F2 | **Identifiability checks are wired but never fed.** `fitting.assess_fit` can flag highly correlated pairs and wide confidence intervals, and `diag_rules` has `non_identifiable_pair → fix_and_refit`. But `fitting_activities` calls `assess_fit` without correlations or intervals, and `run_pi.R` does not export the correlation matrix. A non-identifiable fit therefore passes, or shows only "at bound". | `fitting_activities.py` (`assess_fit(results, …)`); `run_pi.R` output | high |
| F3 | **The optimiser works on the linear value over six decades.** The start values are log-sampled, but BOBYQA steps linearly, so a clearance range of [0.0001, 100] converges slowly or stops at a bound. Already approved by the owner, after T-56: fit log-scaled parameters on their logarithm. | `run_pi.R` (locked) | high |
| F4 | **One cause per round, in sequence.** IV data inform clearance (AUC) and volume (shape, t½) together. Today they are corrected in separate rounds, and a branch takes a whole round, so a stage can run out of rounds before it fits what matters. | `diag_rules.yaml` action order; `max_rounds` 4 | medium |
| F5 | **Parameters are chosen by rule, not by sensitivity.** Sensitivity runs only at S6 and in the feedback cycles. Practice: fit only parameters the training outputs are sensitive to and that are uncertain. Insensitive parameters wander to their bounds. | `local_runner._run_prediction`; `prepare_feedback_sensitivity` | medium |
| F6 | **Uncertainty of the estimates is read but not judged or carried.** `run_pi.R` returns SD, CV and 95 % CI (Hessian); they are stored, but no rule uses them, the MAR does not show them per fit, and S6 draws parameters independently (correlations not propagated). | `FitStartOutcome.uncertainty`; `prediction.py` | medium |
| F7 | **The S1 trigger is the IV Cmax of a short-infusion microdose** (0.54× in T-56). The early peak depends on infusion length, sampling time and site. Practice judges AUC, CL, Vss and t½ at S1, and Cmax only where end-of-infusion is sampled. This is the open SME question, `docs/SME_SIGNOFF.md` §1. | T-56 S1 record; reference as-is runs | medium (SME) |
| F8 | **Thin training data per stage.** On Dapagliflozin, S1 trains on one IV microdose (0.08 mg, n 7); S2 on two oral studies (a 2.5 mg solution and a 500 mg capsule, which may be solubility-limited); 33 of 40 studies are S5 external. The split is MS-01's (locked, SME), but the information content per fitted parameter is not checked. | Review & sign, studies and roles | medium (SME) |
| F9 | **Error model and BLQ handling to verify on the engine.** Residuals are log-scaled with equal study weights. Mean data carry their SD when it is given (`yErrorType`), but whether the PI package weights by it, and how it treats points below LLOQ (dropped, or a likelihood term such as M3), is not yet verified. | `run_pi.R` `build_dataset` | medium |
| F10 | **Fits run only with the real engine.** The stub engine exports no `.pkml`, so local and CI runs never fit. That is correct (only PK-Sim counts), but no automated test proves a fit inside a campaign; the evidence is the reference refits in Actions. | `collect_pkml_inputs`; PR #97 notes | low |

**What is already right:**
- measured fu is held fixed (D-37);
- the bounds come from MS-01 §2.2 and are signed in the MAP (D-36, D-37);
- multi-start with a check that the starts agree, and a flag when an estimate sits on a bound;
- equal weight per study;
- training and validation data are separated, and S5 is blinded until the MAP signature;
- the no-regression gate and SJ;
- every estimate is a new CPF version with its provenance.

## 4. Proposed plan
Each step is its own PR to `main`. A step marked *science* changes how models are built or judged: owner approval,
UNVERIFIED, version bump, CHANGELOG science entry, and PK-Sim evidence before it counts.

| Step | What | Files | Kind |
|---|---|---|---|
| **PI-0** | **Confirm what T-56 did.** Re-run T-56 with a plan signed after D-37. PR #97's notes then show the fit candidates, each fit and why any did not run. | the owner, on the server | evidence |
| **PI-1** | **Unblock the engine image.** r-universe now serves PI 2.3.0, so every engine build fails. Install the qualified 2.2.0 from its release source with a pinned sha256, as ospsuite already is. | `services/engine-worker/Dockerfile` (locked) | infra |
| **PI-2** | **Identifiability in every fit, without changing any decision:** `run_pi.R` exports the correlation matrix of the best start; `assess_fit` receives the correlations and the CIs, so "highly correlated" and "poorly determined" fire, and the existing `non_identifiable_pair` rule can act; each fit's estimate, CI, CV, correlations, start agreement and bounds go into the stage notes and a MAR table. | `run_pi.R` (locked), `fitting_activities.py`, `campaign_mar.py` | engine + report |
| **PI-2b** | **Act on a non-identifiable pair** (\|r\| > 0.95): carry out MS-01's `fix_and_refit` ("fix the one with the more reliable source; refit"), then hand the correlated pairs to the diagnosis. **The owner's rule (2026-10-25):** fix the parameter with the more reliable source at its source value from the signed MAP, and refit the rest. More reliable = the higher evidence grade (A–D); measured beats predicted; where the two disagree, the grade decides (2026-10-27). A tie (equal grade and status) is not guessed: the round escalates to the owner. **Built:** #103 (merged 2026-10-29), locked `map.py` approved 2026-10-27. **Grade vs status (owner, 2026-10-29, option (c)):** the rule stays "grade decides", and the SME grading rubric makes the grade carry what the status said. A predicted value is capped below a measured one, and the test system (human in vivo, human in vitro, animal, in silico) is part of the grade, so the two no longer disagree. SME-governed and locked: the rubric's diff goes to the owner first. | `campaign_activities.py`, `fitting_activities.py`, `map.py` (locked: the MAP records each parameter's grade) | science |
| **PI-3 (decided 2026-10-25: (c) + (b))** | **Log-scale optimisation: not possible through the package's public API.** `ospsuite.parameteridentification` 2.2.0 puts the optimiser's raw values into `SimulationBatch$addRunValues`; there is no transform hook. **The owner's decision:** (c) stay linear for now, keeping the log-sampled multi-start; and (b) propose a parameter transform upstream (draft: `docs/upstream/2026-10-25-osp-pi-log-scale-request.md`, shown to the owner before it is sent), adopted once released, pinned and re-qualified. Option (a), our own log-space optimisation driving the package's internal objective function, is revisited only if `POORLY_DETERMINED` or `NO_CI` findings show up often in real fits. | `run_pi.R` (locked), unchanged | engine |
| **PI-3 (original)** | **Log-scale optimisation** (approved by the owner on 2026-10-23, after T-56): parameters with a log fit policy are optimised on log10. Includes a golden PI case and a PK-Sim qualification run. Can share the engine PR with PI-2. | `run_pi.R` (locked), `golden/pi_smoke.R` | engine |
| **PI-4 (next, owner 2026-10-29)** | **Parallel pathways: fit what the data identify** (science, SME). The dapagliflozin refit on PK-Sim (run 40739239767) shows the case: one IV study, three parallel clearances, every 95 % CI wider than its estimate. When several pathways of one kind would be fitted from plasma data alone, fit one common factor on them and keep their fm split, unless the stage has data that separate them (metabolites, urine). The MAP records which. | `diag_rules.yaml` 0.7, `fit_spec.py`, MS-01 (locked, SME) | science |
| **PI-5** | **Choose by sensitivity** (science). Before a fit, run a local sensitivity of the training outputs to the action's candidates (the engine's `sensitivity` task). Leave out those below a threshold, and record why. | `campaign_activities.py`, `diag_rules.yaml` | science |
| **PI-6** | **Fit clearance and distribution together at S1** when both are off (science), and treat the partition-method branch as a comparison inside the round, not a round of its own. | `diag_rules.yaml`, `local_runner.py` | science |
| **PI-7** | **Verify the error model on the engine:** SD weighting and BLQ handling in `ospsuite.parameteridentification` 2.2.0, from its documentation and a golden case. Record the result; change only if it is wrong. | `golden/` (locked) | verification |
| **PI-8** | **Carry the uncertainty:** S6 draws from the estimates' covariance, not independently. | `prediction.py` | science |

**Recommended order:**
1. PI-0 and PI-1 now. PI-1 is blocking CI on any PR that touches the engine paths, #97 included.
2. Then PI-2 and PI-3 together, in one engine PR with one re-qualification.
3. Then PI-4 to PI-6 with the SME.
4. PI-7 and PI-8 after that.

**Evidence for each science step:** `dapagliflozin-refit` and the T-56 kit on PK-Sim, before and after. Compare:
- GMFE on the training and validation studies;
- the number of estimates at a bound;
- CI widths;
- start agreement.

A step counts only if those runs show it.

## 5. Decisions for the owner
1. **PI-1:** approve the locked Dockerfile change that keeps PI 2.2.0 (recommended), or re-qualify 2.3.0 instead?
2. **PI-2 and PI-3:** approve one locked engine PR for `run_pi.R` (correlations plus log scale)?
3. **PI-4 to PI-6:** take these to the SME as written? The SME list also gets F7 (S1 IV Cmax) and F8 (information per
   fitted parameter).
4. **PI-0:** re-run T-56 on the server with a freshly signed plan.

## 6. Not in scope
- The acceptance criteria and MS-01's split rules: SME content, unchanged here.
- Population fitting (NLME): PK-Sim's PI fits a mean individual. A population approach would be a separate,
  larger decision.
