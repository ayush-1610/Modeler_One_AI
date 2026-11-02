# PI-4 B: fitting parallel pathways through one factor (design)

Status: **approved by the owner, 2026-11-02 (answers below); B1, B1b, B2a and B2b built.** The owner chose PI-4 **A + B + D** on 2026-11-02
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

## The owner's answers (2026-11-02)
1. **Log scale: yes, in B1**, applied only when the signed fit policy says `scale: log`. A spec without a scale runs
   exactly as today. The golden cases cover log and linear, with and without groups.
2. **Order: agreed.** B2 first: a person chooses and signs the group, with a reason that cites where the split comes
   from. B3, the automatic rule, waits for the SME and stays UNVERIFIED. Escalation (D) stays until then.
3. **Golden model: Aciclovir**, provided its model really has filtration and a separate tubular secretion process.
   Check it against the engine files first; otherwise use another OSP example with two parallel elimination
   processes. Never add a pathway to the model. After the golden case passes, run the dapagliflozin refit with the
   three liver clearances as one group.

**Checked (2026-11-02):** `Aciclovir.pkml` as shipped by ospsuite 12.4.4 (`inst/extdata`, release commit `4f37d444`,
the engine image's pin) holds two separate processes in `Neighborhoods|Kidney_pls_Kidney_ur|Aciclovir`:
- `Glomerular Filtration-GFR-Aciclovir`, with "GFR fraction" = 1;
- `Renal Clearances-TS-Aciclovir` (`TubularSecretion_FirstOrder`), with `TSspec` in 1/min, computed from "Tubular
  secretion" = 0.412 l/min.

Its only other elimination, `Aciclovir-Total Hepatic Clearance-Test`, has a plasma clearance of 0. So Aciclovir is
the golden model, unchanged.

## Status
- **B1, the engine (#120):** built. The spec's `groups`, the per-parameter and per-group `scale`, the result's
  per-group rows, and `golden/pi_relative_group.R` in the qualification gate. No platform fit changes in B1.
  - **The golden case passed on PK-Sim** (engine-image run 41467498164, ospsuite 12.4.4, PK-Sim 12.3.173), with a
    known factor of 0.5:
    - the group, linear: 0.5008 (95 % CI 0.4952–0.5064);
    - the group, log: 0.5008 (0.4952–0.5065);
    - secretion alone, log: TSspec 0.47176 1/min (0.46397–0.47967) against a truth of 0.47062;
    - with no scale and with "linear": identical, on the package's own class;
    - lipophilicity beside the group: factor 0.5032, r(Lipophilicity, renal) = 0.958.
- **B1b, the signed scale reaches the engine:** built.
  - `fit_spec` passes each parameter's signed `scale`, and the multi-start draws on the scale the spec gives.
  - The platform checks the result echoes it: an older engine ignores it, and its start is not used
    (`ENGINE_SCALE_IGNORED`).
  - The MAP's log-scale limitation is retired: "[lo, hi] log" now means what it says.
- **B2, a person chooses the group:** as planned, with a reason that cites where the split comes from (the owner's
  answer 2). It is built in two PRs.
  - **B2a, the record and the run:** built.
    - `CPF.fit_groups` (name, members, the factor's bounds and scale, reason, split source), signed in the MAP.
    - `fit_spec` passes the groups, and the multi-start draws the factor.
    - The round is assessed on the factor, and the members' estimates go to the CPF.
    - **Deviation from this plan:** the group is a CPF-level record (`CPF.fit_groups`), not a field of each member's
      fit policy. One record holds the factor's bounds, scale, reason and split source, and it is validated in one
      place.
  - **The dapagliflozin refit, grouped:** the reference workflow's task `dapagliflozin-refit-grouped`
    (`run_reference.py --group`). Its three hepatic clearances are fitted as one factor; the refit's ×2 shift keeps
    their published split, so the factor's truth is 0.5.
  - **The result on PK-Sim** (reference run 41495102951, 2026-11-02, B2a's code with B1b's log scale, 32 starts).
    Both runs fit the three hepatic clearances at S1 from the same shifted start:

    | | grouped (one factor) | each on its own (three values) |
    |---|---|---|
    | the starts agree | **100 %** | 72 % |
    | estimate (95 % CI) | factor **0.4565 (0.31–0.672)**; truth 0.5 | CYP 0.963 (0.351–2.64); UGT1A9 0.0399 (0.000216–7.4); UGT2B7 0.0660 (0.000207–21) |
    | at a bound | none | UGT1A9 at its lower, UGT2B7 at its upper |
    | each clearance / published | 0.913 for all three (the split kept) | CYP 6.7×, UGT1A9 0.1×, UGT2B7 10× |
    | AUC / Cmax GMFE after the fit | 1.423 / 2.395 | 1.412 / 2.291 |
    | what the diagnosis did next | fitted logP (2.35, 2.01–2.69; published 2.67): 1.341 / 1.916 | escalated: a parameter at its bound |
    | campaign | escalated at S1: the IV study's Cmax 0.52-fold (distribution) | escalated at S1 |

    - **The grouped fit is identifiable:** one factor, with a CI narrower than the estimate.
    - **The ungrouped fit is not:** the same profile fits about as well with the clearances 67-fold apart, two at
      their bounds and their CIs spanning four to five decades. This is the non-identifiability B was built for.
    - **Both escalate at S1 for a reason the grouping does not touch:** the IV study's Cmax is too low (distribution).
      Also, the refit shifts the GFR fraction ×2 and the diagnosis did not fit it. That likely explains why the
      factor lands at 0.46 rather than 0.5: the liver compensates for the extra renal clearance.
  - **B2b, the person's choice on Review & sign:** built. It adds the estimation plan's "Fitted as one" form
    (members, the factor's bounds and scale, the split's source and the reason, both required), the plan's validator
    and the API. Its groups reach the campaign CPF, so the MAP signs them.
- **B3:** waits for the SME.
