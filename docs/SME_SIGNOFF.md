# SME sign-off list (T-30)

Every piece of scientific content that decides a model, a verdict or an application result, and still waits for a
PBPK SME (and QA where named). Each item is data in a versioned, locked file (`docs/architecture/locked-files.json`);
none is code. Until it is signed it stays `UNVERIFIED` / `DRAFT`, and every report built on it says so.

**How to sign one off:**
1. The SME reviews the file and the questions below.
2. The owner approves the change in its own PR: set `status: SME_APPROVED` (templates: `APPROVED`), bump the version,
   and add a CHANGELOG entry naming the reviewer and the date.
3. Refresh the locked hashes: `UPDATE_LOCKED=1 uv run pytest tests/architecture/test_locked_files.py`.

Last brought up to date: 2026-10-09.

## 1. The modelling standard and its rulesets

| Item | File | Version | What the SME decides |
|---|---|---|---|
| MS-01 modelling standard | `docs/PBPK_MODELING_WORKFLOW.md`, `MS01_VERSION` in `campaign/map.py` | 1.3 | The [SME] defaults from v1.0. Stage SJ and the §7 budget split (v1.1). Feedback cycles (v1.2). Stage SM, per-analyte split rule 7, and metabolite gating (v1.3, D-25). **Open:** §9 (what the MAP contains) does not list the MAP's applications yet (B6 PR 2) |
| Acceptance criteria | `rulesets/pbpk_acceptance_criteria.yaml` | 2026.2-draft | Tier limits. Metabolites judged by the parent's tier limits (2026.2). **Open (found on PK-Sim, 2026-10-09):** should S1 judge the Cmax of a short IV infusion, or only AUC and t½? The published Itraconazole (Heykants 1989 IV, Cmax 2.14×), Verapamil (McAllister 1982 IV, 3.10×) and Dapagliflozin (IV Cmax 0.52×) models escalate at S1 on IV Cmax with AUC in band, and their IV simulations round-trip identically to the published ones |
| Diagnostic rules | `rulesets/diag_rules.yaml` | 0.6 | Every rule's evidence, thresholds and actions. The metabolite clearance and formation rules, and SM in the shared rules (0.6) |
| Dissolution similarity | `rulesets/dissolution_similarity.yaml` | 2026.1-draft | f2 conditions and the release-model evidence |
| DDI static screening | `rulesets/ddi_static_screening.yaml` | 2026.1-draft | Static DDI thresholds |
| Parameter registry | `parameters/registry.yaml` | 1.2 | Placement and units of every CPF id. `ehc_fraction` placed at `Organism|Liver|EHC continuous fraction` (B3) |

## 2. Data requirements (P1 data plan)

| Item | File | Version | What the SME decides |
|---|---|---|---|
| Core small molecule | `requirements/core_small_molecule.yaml` | 2026.1-draft | The items, their criticality and default providers |
| Food effect, DDI, FIH, special populations | `requirements/app_food_effect.yaml`, `app_ddi.yaml`, `app_fih.yaml`, `app_special_populations.yaml` | 2026.1-draft | The same |
| Virtual bioequivalence | `requirements/app_vbe.yaml` | 2026.2-draft | The intra-subject variability (`REQ-vbe.variability`) has no default provider; the data plan names who gives it (D-26) |

## 3. Analysis templates (T-31)

| Item | File | Version | What the SME and QA decide |
|---|---|---|---|
| VBE crossover | `analysis_templates/vbe-crossover.yaml` | 0.2.0-draft | The NTI limits 0.90–1.1111, marked [VERIFY] (the standard 0.80–1.25 at a 90 % CI is verified). Which parameters carry intra-subject variability (ARCHITECTURE Q7). The F-304 criterion: simulated vs observed between-subject CV within 1.5-fold, `verified: false`. The observed GMR within the simulated 5–95 %. The design (n, K, seed and PoS threshold are the person's inputs, never defaulted). The engine occasion's median-1 log-normal factor (`run_job.R`, B6 PR 3) |
| DDI CYP3A4 victim | `analysis_templates/ddi-cyp3a4-victim.yaml` | 1.0.0-draft | The whole template. No S6 runner exists for it yet |

## 4. Methods confirmed on PK-Sim but not yet signed as acceptance methods

| Item | Where | Evidence on PK-Sim | What the SME decides |
|---|---|---|---|
| Weibull release equation | `pbpk_domain/dissolution.py` (`ENGINE_CONFIRMED = True`) | Engine-image run 37919482630: max deviation 4.2e-05 of the dose | Its use as release-model evidence from in-vitro dissolution |
| Equal weight per study in PI | `fit_spec.build_fit_spec` weights, `run_pi.R` (D-04) | The weighted PI golden case: "objective x 4 (expected 4)" | The weighting rule w = √(N / (k·nₛ)) |
| EHC fraction | registry 1.2, `indiv.*` route | Placed at the harvested path; round trip unchanged | Its placement and use |
| Population occasions | `run_job.R` `variability` + `occasion_seed` | Engine-image run 37958733969: same individuals, seeds differ, a seed reproduces, an unknown path stops | As in §3 |

## 5. Reference-data decisions already taken by the owner (for the record)

| Item | File | Decision |
|---|---|---|
| OSP Rifampicin Stone 2004 | `reference/exclusions.yaml` | Excluded. It is labelled mg/l, but its values are about 1000× below the other 600 mg studies (owner, D5, 2026-10-09). The published data are not altered |

## 6. What the PK-Sim reference runs found that the SME should see

- **The published models as imported, judged by our gates.**
  - Dapagliflozin and Rifampicin as-is are unchanged before and after the architecture refactor (run 37922984864 vs
    36079717728).
  - Dapagliflozin S1 IV Cmax is 0.52×; Rifampicin Cmax is 1.59×.
  - The Itraconazole and Verapamil systems escalate at S1 on IV Cmax (section 1).
- **Refits from shifted starts.**
  - Rifampicin refit: VPC 3/6.
  - Dapagliflozin refit: UGT1A9 at its bound.
  - Verapamil system refit (run 37951203929): escalates at S1 after 3.3 h. The R-Verapamil formation kcats end at
    their lower bounds and the racemic-sum AUC is still 0.46×. The co-parent's shifted parameters (S-Verapamil) are
    not S1 candidates for the sum analyte, so the refit cannot recover the published values. **Question:** should
    S1 fit a co-parent's parameters against a racemic sum, or should a system refit shift one compound at a time?
- **Illustrative VBE** (run 37965688096; an invented TEST tablet with t50 × 1.5 and an illustrative 30 % CV on
  gastric emptying).
  - Results: AUC GMR 0.979, Cmax GMR 0.880, PoS 100 %, NOT_VALIDATED.
  - The narrow trial-to-trial spread says gastric emptying variability barely moves Dapagliflozin exposure. Which
    parameters should carry the intra-subject variability is a question for section 3.
