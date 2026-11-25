# 00 · Executive summary

**Subject:** Modeler One, post-MAP scope: everything from a signed Model Analysis Plan (MAP) to a downloadable
submission package, i.e. the modelling campaign on PK-Sim (MS-01 stages S1→S7), its decisions, and the S7 package.
**Repository:** `ayush-1610/Modeler_One_AI`, commit `1dbda7f` (2026-11-25, branch `claude/focused-clarke-7dq61v`, one
merge ahead of `origin/main` `70f6010`).
**Mode:** Mode A (source code investigation). No running instance, no server access (`adt-server` is LAN-only), no
PK-Sim in this container (no `Rscript`). Every claim below comes from reading code, plus a Python test run.
**Date:** 2026-11-25.

## 1. What it is

Modeler One automates physiologically based pharmacokinetic (PBPK) model development on the open-source Open Systems
Pharmacology engine (ospsuite R 12.4.4 / PK-Sim 12.3 / .NET 8). After a person signs the MAP, a campaign regenerates
PK-Sim simulations from the Compound Parameter Framework (CPF), fits parameters against clinical data stage by stage,
judges each stage with pre-specified, risk-tiered acceptance criteria, stops for signed human decisions when it cannot
proceed, validates the final model on blinded studies, characterises it (sensitivity, uncertainty, virtual
bioequivalence) and assembles an ICH M15 Model Analysis Report (MAR) with a reproducibility-gated package.

## 2. How the post-MAP part works (one paragraph)

`POST /api/v1/projects/{id}/campaigns` checks the run guard (signed MAP, signed stage limits, CPF = MAP) and starts a
daemon thread in the API process (`LocalExecutor`, `services/orchestrator/src/modeler_orchestrator/local_runner.py`).
For each stage the executor plans from the signed MAP, builds a PK-Sim snapshot from the CPF
(`pbpk_domain.campaign.round_build` → `cpf.build` → `snapshot.builder`), runs `Rscript run_job.R` as a subprocess
(`modeler_engine.runner.EngineRunner`), reduces the profiles by NCA, judges them (`acceptance`, `campaign.evaluate`,
VPC), diagnoses failures with a deterministic ruleset (`diagnostics.py` + `diag_rules.yaml`), picks the first untried
permitted action, and fits with `ospsuite.parameteridentification` (`run_pi.R`, 4–32 multistarts). Fitted values become
a new CPF version. S4/S5 judge the final CPF without fitting; S5 failures enter a signed feedback cycle (limitation,
learn, new evidence, stop). S6 waits for a signed S4/S5 evaluation, then runs sensitivity, uncertainty and optional VBE.
S7 bundles the evidence, re-runs every bundled simulation on a fresh engine process, compares at 1e-6, renders the MAR
(Markdown, DOCX, PDF/A-2b) and releases `package.zip` only if the re-run matched and the MAR lint is clean.

## 3. Status at a glance

| Area | Status | Evidence |
|---|---|---|
| S0→S7 loop on real PK-Sim | Works on **synthetic known-truth** data (S0→S7 in 264–266 s on the server, 2026-09-24) | CHANGELOG (see `08`/`F_docs_deploy` notes) |
| Real clinical data | **No published-model campaign passes S1 without a human decision**: Dapagliflozin, Rifampicin, Itraconazole and Verapamil systems escalate at S1 (mostly a short IV infusion's Cmax with AUC in band; open SME question) | `docs/SME_SIGNOFF.md:20`; CHANGELOG 2026-10-09 → 11-02 |
| T-56 end-to-end proof | One server campaign reached S7 on published data (2026-10-22, 9 min), but **no fit ran, it ran in pilot with the DEV token**, so its PQ is incomplete | CHANGELOG:7440-7518 |
| Execution backend in use | Single-node `LocalExecutor` with file stores; Temporal/MinIO/k3s built or planned but not deployed | `config.py:21`; `deploy/server/_env.sh` |
| Governance | Every post-MAP ruleset, template and MS-01 v1.1–1.3 is UNVERIFIED/DRAFT pending SME sign-off | `docs/SME_SIGNOFF.md` |
| Tests (in scope, this container) | **1,168 passed, 14 failed, 23 skipped** (1,205). The 14 failures are the Temporal suite, which cannot download its test server here | `evidence/E_quality.md` §3 |
| Real-engine CI | Golden scripts only on engine-worker/contract changes; full PK-Sim campaigns are manual dispatch | `.github/workflows/engine-image.yml`, `reference-models.yml` |

## 4. Most important findings

Severity and full evidence are in `11_TECHNICAL_ASSESSMENT.md`. Items marked **(L)** were re-verified line by line by
the lead investigator.

**Compliance and scientific integrity**
1. **(L) The S4/S5 evaluation signature can be bypassed.** `escalation:resolve` accepts any of six actions without
   checking the escalation's offered options; `accept_best` at the S6 signature gate marks S6 ACCEPTED, skips the D-19
   real-data refusal and S6 itself, and runs S7 (`escalations.py:202,248`; `local_runner.py:1277-1306`).
2. **(L) The run guard trusts a MAP's self-declared signature.** `map_signed` returns true for any JSON at the
   client-supplied `file://` path with `"status":"SIGNED"` and a truthy `signature`; the content hash is never
   recomputed, and the client's `cpf_sha256` is never checked (`run_guard.py:46-65`; `campaign_api.py:57-62`).
3. **No post-MAP sign-off of the deliverable.** Nothing signs the MAR, the package, the final CPF or a QA release in
   the deployed path; the only post-MAP signature (S6 gate) hashes the label `campaign:stage:action`, not the evaluation
   (`campaign_mar.py:414-420`; `escalations.py:266-267`).
4. **No separation of duties.** A curator who owns the project can start a campaign and sign its escalations and its
   evaluation; the one-click Run button signs a MAP that was never displayed (`ownership.py:62-65`;
   `RunCampaignButton.tsx:28-64`).
5. **(L) An accepted escalated stage disappears from the package.** Stages that escalate and are then accepted by a
   signed decision never write their evidence; the MAR reports them "not run" and an accepted S4/S5 is neither bundled
   nor reproduced (`local_runner.py:554-556, 1277-1286`).
6. **Fixture or pilot output can look like evidence.** The MAR and zip record neither engine kind nor deployment; a
   stub-engine campaign releases an "exportable" package; DEV-verifier signatures are stored as `oidc:loa2`.

**Model-building correctness**
7. **(L) "Accept the best round" accepts the latest round**, and fit estimates are applied without comparing against
   the pre-fit result (`local_runner.py:649-650`; `campaign_activities.py:619-671`).
8. **(L) Three diagnostic action types are no-ops.** Only `fit` and `fix_and_refit` change the model; `branch`
   (partition/permeability method), `switch` (Michaelis-Menten) and `switch_algorithm` (DEoptim) consume a round on an
   unchanged CPF (`campaign_activities.py:221, 438`).
9. **Five diagnostic evidences are never computed** (secondary peak, MD accumulation, permeability shape, two fed
   signals), the distribution rule cannot fire for an IV bolus **(L)**, and the S3 fed sub-loop cannot run
   (`food.fed_solubility_factor` has no engine binding).
10. **The PI objective's SD weighting and BLQ handling are package defaults** (`run_pi.R` sets none), while
    `docs/WORKFLOW_AND_AUTOMATION.md` claims SD weighting.

**Operations and engineering**
11. **(L) Campaigns are not durable.** They run on daemon threads in the API; any restart (every deploy, the watchdog)
    leaves them RUNNING forever. There is no cancel/stop route and no startup recovery (`main.py:44-56`).
12. **(L) One failed PI start fails the whole stage** in the local path; there is no fit deadline cancellation
    (`runner.py:136-137`; `local_runner.py:1058-1069`).
13. **Engine identity is asserted, not measured.** The server "digest" is a hash of the committed `catalog.json`; the
    engine id is hard-coded; the memo key ignores the engine scripts' content, so a fixed `run_pi.R` can keep serving
    old memoised results.
14. **The catalog gate is unwired** (`cpf.binding.bind` has no production caller) and the committed catalog is stale
    against 8 process types used by vendored fixtures.
15. **`rerun_all.R`, shipped to reviewers, is never executed**; the zip is not byte-reproducible and its manifest omits
    itself and `rerun_all.R`.

## 5. Bottom line

The post-MAP pipeline is architecturally complete in the single-node path and has run end to end on real PK-Sim with
synthetic data. It is **not yet a regulator-reviewable product**: no clinical-data campaign has passed S1 unaided, the
governing rulesets are unsigned, the deliverable carries no signatures, and several controls that Part 11 reviewers
would test (signature binding, gate enforcement, separation of duties, audit of campaign events, durable execution)
have confirmed gaps. Most fixes are local and well-scoped (see `12_GAPS_AND_OPPORTUNITIES.md`).

## 6. How to read this package

Start with `INDEX.md`. The detailed per-slice evidence notes (with file:line citations) are under `evidence/`.
