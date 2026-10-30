# PI-4: fitting parallel pathways that plasma data cannot separate (plan)

Status: **DRAFT for the owner's decision** (2026-10-29). Nothing is built. The owner decided on 2026-10-29 that PI-4
comes next (decision 9). Parent plan: `docs/plans/2026-10-23-parameter-identification-review.md`, row PI-4.

## 1. The problem, on PK-Sim
- **The case:** the dapagliflozin refit (Actions run 40739239767, engine 12.4.4, PI 2.2.0) fits three parallel
  clearances from one IV study. Every 95 % CI is wider than its estimate, and reaches below zero:

  | Pathway | Estimate | 95 % CI |
  |---|---|---|
  | UGT1A9 specific clearance | 0.040 | −0.031 to 0.111 |
  | UGT2B7 specific clearance | 0.066 | −0.39 to 0.52 |
  | Hepatic CYP specific clearance | 0.963 | −0.66 to 2.59 |

  Only 59 % of the starts reach the best solution.
- **Why:** plasma data identify the total clearance, not the split between pathways of one kind. PI-2b's
  non-identifiable pair rule (|r| > 0.95) does not catch it: no pair is that strongly correlated, while the three
  together trade off.
- **What PI-4 proposed:** fit one common factor on such pathways and keep their split (the fractions metabolised
  their sources give), unless the stage has data that separate them (metabolite profiles, urine). The MAP records
  which.

## 2. What the engine allows
`ospsuite.parameteridentification` 2.2.0 (commit `cb9e9e5`, pinned in the engine image):
- **A group shares a value, not a factor.** `PIParameters$initialize` (`R/PIParameters.R:116`) documents that "all
  parameters are optimized using this unified value", and `setValue` (`:136`) writes that one value into each
  parameter.
  - Parallel pathways start at different values, so a shared value would destroy their split.
  - A group therefore cannot be a common factor.
- **The objective function is private.** `.objectiveFunction` (`R/ParameterIdentification.R:265`) is in the R6
  class's private part. Driving it ourselves means reaching into the package's internals, which may change in any
  release.
- This is the same kind of limit PI-3 found for the log scale. The optimiser's values go straight to
  `SimulationBatch$addRunValues`.

## 3. Options
| | What | Gains | Costs |
|---|---|---|---|
| **A** | **Ask OSP for a relative group** (each parameter = factor × its start). Added as a second issue to the unsent request, `docs/upstream/2026-10-25-osp-pi-log-scale-request.md`. Adopted once released, pinned and re-qualified. | The package's own optimiser, CI and results, maintained upstream. | Waits on OSP. Until then, nothing changes in the fits. |
| **B** | **Our own one-factor fit:** a new engine script optimises `f` (1-D, bounded, on log f). Each evaluation sets every pathway to `f × start` and calls the package's private `.objectiveFunction`, so the error model and weights stay the package's. | PI-4 now. One parameter is well determined, and its CI is cheap to profile. | Our code at the engine's heart. It uses a private function of a pinned version, so it needs a golden case, a PK-Sim qualification and the SME. It touches the engine scripts (locked category) and the fit path. |
| **C** | **Interim, no engine change:** where pathways cannot be separated, the stage fits only the pathway with the weakest source and holds the others at their source values. The MAP lists the changed split as a limitation. | Small. Uses PI-2b's grading. | The split moves onto one pathway, which is scientifically weaker. A fitted fm that no data support can mislead a DDI application. |
| **D** | **Keep today's behaviour:** the stage escalates (a parameter at its bound, or wide CIs); the modeller decides. | Nothing to build. | The case recurs on every drug with parallel pathways and plasma data only. |

**Recommendation: A now, then B if you want PI-4 before OSP answers.**
- A costs nothing beyond your review of the request text.
- B is the in-house path. It is worth it only with a golden case and a qualification run, because it relies on a
  private function.
- C is not recommended. It hides the identifiability problem in a fitted split.

## 4. What PI-4 needs whichever option is taken
These parts are ours in any case, and SME-governed:
- **When pathways count as "parallel of one kind":** for example, two or more hepatic metabolic pathways
  (`elim.hepatic.*`), fitted at one stage from plasma data only.
- **What separates them:** metabolite profiles of a pathway's metabolite, urine for renal against hepatic, a DDI
  study with a selective inhibitor. The stage fits them separately when it has such data.
- **What the MAP records:** for each stage, which pathways are fitted together and why. This is a locked `map.py`
  change.
- **The rule's home:** a new `diag_rules.yaml` rule (0.7, SME-governed, locked), and the matching MS-01 text (locked).

## 5. Decisions for the owner
1. Options A, B, C or D, or a combination (recommended: A, then B).
2. If A: review the second request's text in the draft (it is unsent, like the first).
3. If B: approve touching the engine scripts and the fit path, in its own PR, with a golden case and a PK-Sim
   qualification run before it binds any fit.
