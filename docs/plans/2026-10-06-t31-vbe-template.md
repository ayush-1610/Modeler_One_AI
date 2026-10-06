# T-31 slice: the virtual bioequivalence (VBE) application template — design, not yet built

Status: **design only (2026-10-06)**, scoped in worktree branch `claude/vbe-template`; no VBE code is written yet.
Spec sources: `docs/ARCHITECTURE_PACK.md` F-304 and APP-11/APP-14; `requirements/app_vbe.yaml` (REQ-vbe.*);
`templates/analysis/ddi-cyp3a4-victim.yaml` (the template format to follow).

## What already exists
- `pbpk_domain.bioequivalence`: paired crossover 90 % CI (`paired_crossover_ci`), `probability_of_success`.
- `pbpk_domain.dissolution`: canonical profiles, f2, Weibull fit in PK-Sim's parameterization — **`ENGINE_CONFIRMED =
  False`**: the release equation has not been checked against PK-Sim's own release curve.
- Brief: application `APP-14 virtual bioequivalence`, products with roles TEST / RLD; dissolution register pairs them.
- Engine `population` task (create from demographics with a seed, or load `population.csv`; exports `pk_analyses.csv`).
- Catalog PK names harvested: `AUC_tEnd`, `AUC_inf`, `C_max`.
- Gap: campaigns have no "application" — S6 always runs sensitivity + uncertainty only.

## Build order
1. **Confirm the Weibull release equation on PK-Sim** (a tablet's dissolved fraction vs `weibull_fraction`), then set
   `ENGINE_CONFIRMED`. VBE rests on it.
2. **Template** `templates/analysis/vbe-crossover.yaml` (DRAFT, UNVERIFIED): requires a validated oral model, TEST and
   RLD CPF formulations (`form.{name}.*`), intra-subject variability (parameter, CV, source — REQ-vbe.variability,
   never defaulted to invented numbers), design (n subjects, K trials, limits 0.80–1.25, 90 % CI, seed).
3. **Signed MAP carries the application** (`MapDocument.applications`, excluded from the content hash when empty so
   existing signatures stay valid); `campaign:prepare` accepts it. Wiring from the P5 plan (T-50) is a follow-up in
   that module.
4. **Engine**: `population` task option `variability: [{path, cv}]` + `occasion_seed` — per individual, multiply the
   parameter (population value, else the simulation's base value, in base units) by a seeded log-normal factor, so
   each arm is a separate occasion. Harvest the gastric-emptying / transit-time paths from a real oral pkml first.
5. **S6 VBE step** (local runner): build TEST and RLD simulations of the design scenario from the final CPF → export
   pkml → TEST arm creates the population (K·n, seed) and exports `population.csv`; RLD arm loads that CSV (same
   individuals), its own occasion seed → per-individual AUC/Cmax from `pk_analyses.csv` → K trials of n →
   per-trial GMR + 90 % CI (AUC, Cmax) → probability of BE success (per metric and joint).
6. **Validation gate (F-304)**: the model must reproduce the observed variability of a clinical BE/PK study
   (REQ-vbe.be_study): simulated between-subject CV vs observed, and the observed GMR within the simulated trials'
   5–95 %. No observed BE data → the VBE result is reported "not validated", never a pass (real-data rule, D-19).
7. **Report**: MAR section (design, PoS, GMR distribution, gate) + M15 row; monitor card.
8. **Proof on PK-Sim**: an illustrative TEST vs RLD tablet pair on a published model (labelled not clinical).

## Decisions for the owner / SME
- BE limits and NTI limits, trials × subjects defaults, which parameters carry intra-subject variability (ARCHITECTURE
  Q7), the PoS threshold, and the variability-gate criterion — all UNVERIFIED until signed.
