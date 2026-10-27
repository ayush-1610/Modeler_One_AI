# Upstream request: optimise parameters on a log scale in `ospsuite.parameteridentification`

**Status: DRAFT, not sent.** The owner decided on 2026-10-25: stay linear for now and propose a parameter transform
upstream (PI-3, options (c) + (b), `docs/plans/2026-10-23-parameter-identification-review.md`). The owner reviews this
text before anything is posted. It would go to the package's GitHub issues
(`Open-Systems-Pharmacology/OSPSuite.ParameterIdentification`) as a feature request. Every line reference below is
for tag `v2.2.0`, commit `cb9e9e5859dc31732a31130f8f46307118420a65`, the version our engine image pins.

---

## Title
Feature request: optimise a `PIParameters` on a log scale (a parameter transform)

## Body

**What we would like**

An option on `PIParameters` to optimise the parameter on a log scale, for example `scale = "log"` (default
`"linear"`, unchanged behaviour). The optimiser would then see `log(value)`, and the simulations would keep
receiving the value in the parameter's own unit.

**Why**

Many PBPK parameters we identify span several orders of magnitude and are only meaningful when positive. Examples
are specific clearances, Km and Vmax, permeabilities and transporter activities. On a linear scale:
- the bounds are badly scaled, for example a range of 0.001 to 10 1/min;
- BOBYQA's trust region and the Hessian behave poorly near the lower bound;
- the Hessian CI is symmetric in the value, while the uncertainty of such parameters is multiplicative.

Estimating such parameters on a log scale is common practice: log-normal parameters in Monolix, exponential
parameterisation in NONMEM, and the logarithmic scaling the OSP desktop parameter identification offers per
parameter.

**What happens today (v2.2.0)**

The value the optimiser proposes goes straight into the simulations, and there is no hook to transform it:
- `.runAlgorithm` (`R/ParameterIdentification.R:697`) passes each `PIParameters`' `startValue`, `minValue` and
  `maxValue` to `Optimizer$run` as they are.
- `.evaluate` (`:508`) and `.getPKValues` (`:435`) write the optimiser's `currVals[[idx]]` into
  `private$.variableParameters` and pass them to `SimulationBatch$addRunValues` (`:549`, `:448`).
- `PIParameters$setValue` (`R/PIParameters.R:136`) is called only by `.applyFinalValues` (`:680`), after the
  optimisation. A subclass that overrides it therefore cannot change the scale the optimiser works on.
- `estimateCI` (`:906`) estimates the Hessian at `currValue` on the same linear scale.

We tried a `PIParameters` subclass that applies `10^x` in `setValue`. The optimiser's log values reached the
simulations unchanged: a tubular secretion specific clearance was simulated at −0.30 1/min, and the simulation
failed with negative amounts.

**A possible design**

- **The field:** `PIParameters` gains `scale` (`"linear"` or `"log"`; the base can be fixed, e.g. natural log). With
  `"log"`, `minValue` must be positive.
- **The optimisation:** `.runAlgorithm` transforms the start value and the bounds before `Optimizer$run`.
- **The simulations:** `.evaluate`, `.getPKValues` and the grid and profile-likelihood helpers back-transform each
  value before writing it to `.variableParameters`.
- **The final value:** `.applyFinalValues` back-transforms before `setValue`.
- **The CI:** `estimateCI` estimates the Hessian on the transformed scale. It reports the estimate, and the CI
  back-transformed to the parameter's unit, which gives an asymmetric interval. The SD and CV are documented as
  being on the transformed scale, or reported on both scales.
- **The results:** `PIResult` / `toDataFrame()` keep reporting values in the parameter's unit, plus the scale used.

The default stays linear, so existing scripts and results are unchanged.

**What we can offer**

We can test a development branch against our qualification cases (single and multi-parameter fits on the OSP
Aciclovir example model, in our engine image on PK-Sim 12.3). If the maintainers prefer, we can also propose a pull
request with tests.

---

## Notes for the owner (not part of the request)
- **What it tells OSP:** only what the request itself states, namely the package's public behaviour and our
  failed-subclass finding. It contains no project data, compound data or internal names.
- **Check before posting:** the request says the OSP desktop parameter identification (PK-Sim / MoBi) offers
  logarithmic scaling per parameter. Please confirm that in the desktop version you use, or drop that clause.
- **Once posted:** we adopt the transform only after it is released, pinned and re-qualified in the engine image (a
  locked Dockerfile change, its own PR). Until then the fits stay linear, with the log-sampled multi-start.
- **Revisit option (a)** (our own log-space optimisation in `run_pi.R`) only if `POORLY_DETERMINED` or `NO_CI`
  findings show up often in real fits.
