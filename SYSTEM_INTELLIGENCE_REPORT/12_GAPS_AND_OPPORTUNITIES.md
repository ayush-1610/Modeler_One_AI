# 12 · Gaps, hidden capabilities and opportunities (post-MAP scope)

Defect IDs (C-, S-, O-, E-, P-, A-, U-, Q-) refer to `11_TECHNICAL_ASSESSMENT.md`.

## 1. What exists vs what is missing

| Capability | Exists today | Partial | Configuration only | Needs development |
|---|---|---|---|---|
| S0→S7 campaign on PK-Sim (single node) | ✓ | | | |
| Clinical-data campaign passing S1 unaided | | | | SME decision on the S1 IV-Cmax criterion, then evidence |
| Diagnostic action types `branch`, `switch`, `switch_algorithm` | | offered, not executed | | handlers in `build_round_snapshot` / fit spec (S-02) |
| Evidences: secondary peak, MD accumulation, permeability shape, fed signals | | rules exist | | evidence computation (S-03) |
| S3 fed sub-loop | | | | harvested engine binding for `food.fed_solubility_factor`, MS-01 amendment (S-04) |
| SM metabolites, SJ, feedback cycles | ✓ (UNVERIFIED) | | | PK-Sim proof, SME sign-off |
| S6 sensitivity and uncertainty | | ±10 %, independent draws | | EMA worst-case ranges, covariance sampling (S-08) |
| VBE | ✓ (DRAFT) | | | a real observed BE study for F-304 |
| DDI, paediatric, special populations, FIH | | DDI template DRAFT, no runner | | runners, templates |
| MAR (MD/DOCX/PDF-A) | ✓ | no figures, no signatures, M15 table partial | | signature flow, figures, full M15 rendering (C-06, P-06) |
| Reproducibility gate | ✓ (same host, 1e-6) | `rerun_all.R` untested | | execute `rerun_all.R` in the gate on a clean engine (P-01) |
| Final CPF acceptance, MAR signature, QA release | | Temporal signal only | | routes and UI (C-06) |
| Cancel / stop / resume a campaign | | | | routes, lease, startup reconciliation (O-01) |
| Live status stream | | polling | | SSE (ENGINEERING_PLAN §7) |
| Distributed execution (Temporal, MinIO) | | built, partial | `MODELER_EXECUTION_BACKEND=temporal` | SJ/S6/S7, monitor, signals, decision route (A-01) |
| Postgres as the campaign store | | schema exists | | file-store migration, enum fixes (A-04) |
| Engine identity from the engine itself | | | | read `engine_manifest.json`; key memo by script hashes (E-01, E-02) |

## 2. Hidden, underused or unwired capabilities (evidence-backed)

| Capability | Where | Reachable how | State |
|---|---|---|---|
| Headless campaign CLI | `python -m modeler_orchestrator.local_runner <spec.json>` | operator shell | works (single node, writes the same monitor records) |
| T-56 end-to-end kit | `deploy/proof/run_t56.py` | operator | P0 → P6 scripted, writes `trace.md` and `pq.json` |
| Reference runner | `deploy/reference/run_all.sh`, `run_reference.py` | operator / manual CI | as-is and refit campaigns of OSP models; stops at the S6 gate |
| Part 11 verification CLI | `python -m modeler_api.part11 verify` | operator, nightly cron | works; misses truncation (C-14) |
| Validation pack renderer | `python -m pbpk_domain.report.validation_pack` | CI (OQ only) and operator | IQ/PQ inputs from `qualify.sh` and the T-56 kit |
| Project doctor | `modeler_api.doctor` | operator CLI | report of one project's state |
| M15 completeness check | `POST /api/v1/m15/validate` | API only (no UI caller) | not run at S7 |
| Run results (Parquet) | `GET /api/v1/runs/{run_id}/results` | API only | cannot find data (path mismatch), no project check (A-03) |
| Single simulation on Temporal | `POST /api/v1/runs` | API only | stages only `snapshot.json`; `status_url` route missing |
| Engine tasks `pk_analysis`, `dry_run` | `run_job.R:159-171` | engine job | no orchestrator caller |
| LLM strategist | `modeler_agents.strategist.llm_decider` | code only | unwired (A-05) |
| Catalog binding gate | `pbpk_domain.cpf.binding.bind` | tests only | unwired (E-03) |
| Static DDI screen | `pbpk_domain.ddi_static.screen` | none | unwired; refuses UNVERIFIED rulesets |
| Parameter transfer to snapshot | `pbpk_domain.snapshot.parameter_transfer` | none | unused (and contrary to the CPF-only principle) |
| Bundle tamper check | `pbpk_domain.reproducibility.verify_bundle_integrity` | tests only | unwired (P-03) |
| MAR figures and signatures | `report.mar.assemble_mar` (`FigureRef`, signatures) | generic MAR only | the campaign MAR does not use them |
| Presigned object store | `modeler_engine.objectstore.HttpObjectStore`, `modeler_storage.objects.S3ObjectStore` | not wired into S7 or downloads | output URIs break presigned query strings (`runner.py:149`) |
| Memo switch and fit parallelism | `MODELER_MEMO`, `MODELER_FIT_WORKERS`, `MODELER_ENGINE_CORES` | environment | works |
| Exploratory projects | project flag `exploratory` | project settings | lifts the D-19 real-data refusal for development work |

## 3. Opportunities, ordered

### 3.1 P0: compliance blockers (small, local changes)

1. **Enforce the offered options server-side** in `escalation:resolve`: refuse an action not in the stored `options`
   (or marked `disabled`), so the S6 gate accepts only approve/abort (C-01).
2. **Bind the start to the signed record:** accept a `map_id` and resolve the MAP, CPF and observed files server-side
   from the signed MapArtifact; recompute `content_sha256()` against `signature.content_sha256`, require a matching
   signature in the audit chain, recompute the CPF hash, record `map_sha256` and `observed_sha256`, and refuse a stage
   list that drops planned stages (C-02, C-03, C-04, C-05). Give each `campaign:prepare` its own directory.
3. **Persist evidence for accepted stages** (status ACCEPTED, last judged round) and carry signed limitations into the
   MAR (C-10).
4. **Separation of duties:** require `modeler-reviewer` for decisions and the evaluation, and a signer different from
   the starter; retire or gate the one-click path (C-08, C-09).
5. **Label or refuse non-evidence:** write engine kind and deployment into the MAR front matter and the manifest; refuse
   an exportable package on a fixture engine or outside production; record DEV signatures with their own
   `auth_method`; show the deployment on the campaign page (C-11).
6. **Audit campaign events:** start, stage verdicts, S6 gate, S7 release and downloads (C-12); record the signature
   after the claim (C-13).

### 3.2 P1: reliability and model-building correctness

1. **Durable execution on one node:** a campaign lease in `modeler_storage.jobs`, startup reconciliation (mark
   orphaned RUNNING campaigns INTERRUPTED with a resumable escalation built from the persisted `resume` state), and a
   signed cancel route (O-01, O-03).
2. **Tolerate failed PI starts** and add a local fit deadline (O-02).
3. **Keep the best round:** track the best CPF by the gate's metric, and accept a fit only when it improves the
   objective or the verdict (S-01).
4. **Execute or retire** `branch`, `switch` and `switch_algorithm` actions; compute the missing evidences; fix the
   bolus guard; bind the fed solubility factor (S-02 to S-05).
5. **Sign the deliverable:** MAR author/reviewer signatures and a QA release over the package manifest; bind the
   evaluation signature to the evaluation content (C-06, C-07).
6. **Make the package verifiable:** deterministic zip timestamps, manifest coverage of `rerun_all.R` (and a
   signed hash of `manifest.json`), a stored zip hash, and run `rerun_all.R` in the gate on a clean engine (P-01, P-02).

### 3.3 P2: engine, data and operations

1. **Measure engine identity:** read ospsuite/PI/PK-Sim versions from `engine_manifest.json` into the run, the MAP and
   the MAR; include script hashes in the memo key; run the server from the qualified image or verify its versions at
   startup (E-01, E-02, E-05).
2. **Wire the catalog gate at S0** and refresh the catalog from the vendored fixtures (E-03).
3. **Extend the CI golden gate** to `run_job.R simulate` and `parameter_identification`, and trigger it on builder,
   evaluation and orchestrator changes (E-04, Q-01).
4. **Back up `~/modeler-data`**, add a disk guard and retention (O-05); move campaign records to per-campaign files or
   Postgres (O-06, A-04).
5. **Observability:** logging configuration on the API process, per-job engine logs, metrics for stage time and fit
   wall time against the plan (Q-04).

### 3.4 P3: platform evolution

1. Decide the Temporal path's future: complete parity (SJ, S6, S7, no-regression, feedback, monitor, token-based
   decision route) or retire it and revise ENGINEERING_PLAN (A-01, A-02, C-15).
2. SSE for the monitor; idempotency keys on starts (U-02, O-04).
3. S6 regulatory completeness (worst-case ranges, covariance), DDI and paediatric runners, the S3 fed gate.
4. MAR figures (GOF, VPC), full M15 table, executive summary.

### 3.5 Human and SME items that gate everything above

- Sign or amend the acceptance ruleset (S1 IV-Cmax question, 1.5-fold source, Guest citation), diag-rules 0.6, MS-01
  v1.1–1.3, the 10 % default internal target, D-37 default bounds, the fit-group rule (PI-4 B3).
- Decide the 1-hour goal against the MS-01 budget split and the 8 h default.
- Confirm PI's error model (SD weighting, BLQ).
- Run PI-0 (T-56 again with a plan signed after D-37) and a production PQ.
