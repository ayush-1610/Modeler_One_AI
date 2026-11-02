# What "log scale" means in a fit today (review)

Status: **review for the owner** (2026-11-02, the owner's item 2: "'our fitting script fits log-scaled parameters on
their linear value' not sounding correct, need detail and proper review"). Package line numbers are for
`ospsuite.parameteridentification` tag `v2.2.0`, commit `cb9e9e5`, the version the engine image pins.

## The short answer
The sentence in `docs/CONTINUATION_PACKAGE.md` §4.1 (row P5) was too compressed to be right. It is replaced by:

> A fitted parameter whose signed fit policy says **scale "log"** is optimised on its **linear** value. Only the
> multi-start's start values are drawn on a log scale. The optimiser's steps and the Hessian confidence interval are on
> the linear value, and `run_pi.R` never receives the scale.

The residuals are a separate matter, and they are right: each output is compared on a log scale (log simulated minus log
observed). That is the output mapping's `scaling`, not the parameter's.

## Where "log" comes from
- **The estimation plan proposes it** (`modeler_project.estimation`, lines 136–147):
  - a relative MS-01 §2.2 default (`[lo×, hi×]` the start value, and the 0.1–10× fallback) gets `scale: log`;
  - a positive absolute range gets `log`;
  - an additive default (logP ± 1.5) gets `linear`.

  So most fitted clearances, permeabilities, Km and Vmax are `log`.
- **The person can change it** on Review & sign. The validator asks a log scale for a positive lower bound
  (`plan.py:518`, `cpf/models.py:46`).
- **The MAP signs it:** `MapBounds.scale` (`campaign/map.py:142`). It is shown to the signer as `[lo, hi] log`
  (`map.py:400`), with no word on what "log" does.

## What the platform does with `scale: log`
1. **Start values:** the multi-start draws them by Latin hypercube **in log space** between the bounds
   (`pbpk_domain.fitting.FitParameter.from_unit`; `campaign_activities._is_log_scale` sets `log_scale` on each
   `FitParameterBounds`).
2. **S6 prediction uncertainty:** a log-scaled parameter is drawn **log-normally**, with σ = √ln(1 + CV²) and
   CV = SD / estimate (`campaign/prediction.py:72–82`). The SD it uses is the linear one from step 4.
3. **The fit spec:** `fit_spec.build_fit_spec` writes each parameter's `name`, `min`, `max`, `start`, `unit` and paths
   (`fit_spec.py:206`), but **not** its scale. `run_pi.R` reads no scale.
4. **The engine** (`run_pi.R`, locked):
   - It builds one `PIParameters` per parameter, with bounds and start in the base unit.
   - The package's `.runAlgorithm` (`R/ParameterIdentification.R:697`) passes `startValue`, `minValue` and `maxValue`
     to `Optimizer$run` unchanged.
   - `.evaluate` (`:508`) writes the optimiser's `currVals[[idx]]` straight into the simulations
     (`SimulationBatch$addRunValues`, `:549`).
   - So BOBYQA, HJKB or DEoptim move the **linear value** inside `[min, max]`.
5. **The confidence interval:** `estimateCI` (`:906` → `Optimizer.R:125–200`) takes the numerical Hessian at the
   estimate, on the linear value, with Cov = σ² (H/2)⁻¹ and σ² = SSR / (n − p). The interval is estimate ± z·SD:
   - it is **symmetric**;
   - its lower end can be **negative** for a parameter that can only be positive;
   - the CV is SD / |estimate|.

## What this means
- **The signed MAP says more than the engine does.** A signer reading `[0.1, 10] log` will take it to mean the
  optimiser works on log(value), as in Monolix, NONMEM or the OSP desktop. It does not. This is a disclosure gap in a
  signed record, not a numerical error. It should be stated in the MAP until the engine does what the label says (see
  "What changes", item 2).
- **Optimisation over wide ranges:** two decades (the 0.1–10× default) are handled well enough by BOBYQA on the linear
  value, with log-sampled starts. Absolute ranges over four to six decades (e.g. a specific clearance from 1e-4 to
  100 1/min) are badly scaled:
  - the low end is explored only from the starts that land there;
  - a fit can stop at a bound;
  - this is finding F3 of the PI review (`docs/plans/2026-10-23-parameter-identification-review.md`).
- **Two uncertainty models for one parameter:**
  - The fit reports a symmetric, linear interval.
  - S6 turns its SD into a log-normal.
  - At a CV of 0.1 the two are close: the 95 % range is 0.80–1.20× the estimate as a normal, 0.82–1.21× as the
    log-normal.
  - At a CV of 0.3 they already differ: 0.41–1.59× against 0.54–1.70×.
  - Above a CV of 0.51 the linear interval reaches below zero.
  - The dapagliflozin refit had 95 % CIs wider than the estimates themselves, so a CV above 0.25.
  - The prediction then rests on a distribution the fit never estimated.
- **Not affected:** the residual scale (log), equal study weights, the bounds the MAP signed, and the estimate itself
  when both optimisers reach the same minimum. What differs is how reliably the linear one gets there, and the interval
  around it.

## What the OSP desktop does (for request A)
The OSP documentation on parameter identification, read through a search index (the page,
`docs.open-systems-pharmacology.org/shared-tools-and-example-workflows/parameter-identification`, cannot be opened from
the build session's network; please confirm on the page) describes two options per identification parameter:
- **Scaling:** Linear or Log ("if the magnitude of the parameter is not known, Log scale should be selected", which
  needs a minimum value above 0).
- **Use as Factor:** several simulation parameters are attached to one identification parameter. "Both specific
  clearances are then varied in parallel by multiplying each simulation value by the same factor."

Both are exactly what the two draft requests ask of the R package. The requests become **parity requests**: the
desktop has these options, and `ospsuite.parameteridentification` 2.2.0 does not. The draft is updated to say so.

## What changes
1. **Wording (this PR):** §4.1 P5 row and the PI review's F3 now say what happens, as above.
2. **The MAP states it (proposed for the locked `map.py` PR, the owner's item 5):** until the engine optimises on
   log(value), the MAP shows a log-scaled bound as "log: start values sampled on a log scale; optimised and its CI
   computed on the linear value", and lists it once under the limitations.
3. **Making "log" real, a question for the owner:**
   - Option B of PI-4 (approved 2026-11-02) drives the package's objective function with our own optimiser, so that one
     factor can scale a group.
   - The same driver can optimise log(value) and take the Hessian on the log scale, giving an asymmetric interval,
     log-normal by construction, that matches S6.
   - That is PI-3's option (a), set aside on 2026-10-25 in favour of waiting for OSP. Building it inside B costs one
     engine PR and one qualification instead of two.
   - **Recommended:** include it in B, behind the signed `scale`. Until B is released, item 2 discloses today's
     behaviour.
4. **The OSP requests (option A):** updated with the desktop parity. Still not sent: the owner reviews the text, then it
   is posted.
