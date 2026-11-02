# PI-4 B: fitting parallel pathways through one factor (design)

Status: **design for the owner** (2026-11-02). The owner chose PI-4 **A + B + D** on 2026-11-02
(`docs/plans/2026-10-29-pi-4-parallel-pathways.md`):
- **A:** ask OSP for a relative group (`docs/upstream/2026-10-25-osp-pi-log-scale-request.md`).
- **B:** build it ourselves now. This plan covers B.
- **D:** keep escalating such fits until B is released (today's behaviour).

Package line numbers are for `ospsuite.parameteridentification` v2.2.0 (`cb9e9e5`), the version the engine image pins.

## What B does
A **relative group** fits several parameters through one factor *f*: each parameter *i* is simulated at
*f* × start*ᵢ*, so their split (from in vitro data, e.g. the fractions metabolised) is kept, and the data estimate only
the total they can identify. The OSP desktop calls this "Use as Factor".

**The case on PK-Sim:** the dapagliflozin refit (run 40739239767) fits three hepatic clearances (CYP, UGT1A9, UGT2B7)
from one IV study, and every 95 % CI is wider than its estimate. A group fits one factor instead of three values.

## How (the engine, `run_pi.R`, locked)
- **A subclass of `ParameterIdentification`** (R6 `inherit`) overrides one private method, `.runAlgorithm`. The package
  calls it only from `run()` (`R/ParameterIdentification.R:855`). The override:
  - builds the optimised vector θ: one entry per group (its factor) and one per parameter outside any group;
  - expands θ to the per-parameter vector the package expects;
  - hands `private$.objectiveFunction(expand(θ))` to the package's own `Optimizer$run`, so the residuals, weights,
    LLOQ handling and algorithms are exactly today's;
  - returns the optimiser's result with `par` expanded, so `.applyFinalValues` and `PIResult` report every parameter
    as usual.
- **The CI:** an override of `estimateCI` calls the package's own `Optimizer$estimateCI` on θ: the same Hessian, with
  σ² = SSR / (n − p), where p is now the number of factors, correctly fewer than the parameters.
  - Each parameter's interval is the factor's, times its start.
  - The fit then reports one CI per group, plus the factor itself.
- **The spec:** `parameters[].group` names a group, and `groups: [{name, min, max}]` gives the bounds on *f*. A spec
  without groups runs exactly as today.
- **Optional, if the owner says yes in #115:** each θ optimised on log(θ), with the CI on the log scale (asymmetric,
  log-normal, matching S6). It is the same code path, behind the signed `scale`.
- **The risk:** the subclass uses the package's internals: a private method, and `Optimizer`, which is not exported
  (`:::`).
  - The image pins 2.2.0, and every version change already re-qualifies it.
  - A golden test fails loudly if the internals change.
  - A, once OSP releases it, would retire the subclass.

## How it is proven
- **A golden case** (`services/engine-worker/golden/pi_relative_group.R`, locked) uses known truth on PK-Sim:
  - simulate OSP's Aciclovir example with its two parallel renal pathways (GFR and tubular secretion), both scaled by a
    known factor (e.g. 1.5);
  - fit the group from that simulated profile;
  - require the factor back within tolerance, the split unchanged, and a CI.
  - A spec without groups must give today's result.
- **Where it runs:** in the engine image's qualification job, on real PK-Sim, on every PR (`engine-image.yml`). A
  result counts only from there.
- **Then on the dapagliflozin refit:** the three hepatic clearances as one group. Expected: one factor with a CI
  narrower than its estimate, where today every CI is wider than its estimate.

## How the platform uses it (three PRs, each to `main`)
1. **B1, the engine (locked: `run_pi.R`, the golden case):** the subclass, the spec's groups, the golden case and its
   qualification run.
2. **B2, a person chooses a group (locked: `cpf/models.py` and `map.py`):**
   - The CPF's fit policy gains an optional `group`.
   - On Review & sign, the estimation plan lets a person fit several parameters as one factor, with a reason. The
     signed MAP records it.
   - `fit_spec` passes the groups to the engine, and the results come back per parameter and per group.
   - No rule decides it yet: the person does, and signs it.
3. **B3, the diagnosis proposes it (SME, locked: `diag_rules.yaml` 0.7, MS-01, the MAP):**
   - The rule: when a stage would fit two or more pathways of one kind, and its training data hold nothing that
     separates them (no metabolite, urine or selective DDI data), fit them as one group.
   - Marked UNVERIFIED until the SME signs, and changed only with the owner's explicit approval.
   - Until B3, D stands: such a fit still escalates, and the person can choose B2's grouping.

## For the owner
1. **Log scale in B1** (the question in #115): yes or no?
2. **The order:** B2 lets a person choose the group before any rule does, and B3 (the rule) waits for the SME. Agreed?
3. **The golden case's model:** proposed is OSP's Aciclovir example, already in `golden/pi_smoke.R`. Its renal
   clearance has two parallel pathways, GFR and tubular secretion. Or another model you prefer?
