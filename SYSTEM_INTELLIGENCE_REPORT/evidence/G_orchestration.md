# G — Orchestration spine (read by the lead investigator)

All paths relative to /workspace/Modeler_One_AI. Verified by reading code unless marked INFERRED.

## Entry: campaign start
- `POST /api/v1/projects/{project_id}/campaigns` — services/api/src/modeler_api/campaign_api.py:44-81. Role: `modeler-curator` or `modeler-reviewer` (:26) + `require_project`.
- Body `CampaignStartRequest` (:29-41): compound, map_id, cpf_uri, cpf_sha256 (hex pattern), map_uri, observed_uri, system_uri/sha, question, model_risk (required low/medium/high), stages, stage_budgets_seconds (dev only). No `map_sha256`, `observed_sha256`, `seed`, `max_rounds` field: CampaignRequest defaults apply (max_rounds_per_stage=4, seed=1, signature_timeout_days=14 — packages/run-contracts/src/modeler_contracts/runs.py:200-221).
- Run guard (services/api/src/modeler_api/run_guard.py): skipped entirely in `development` deployment.
  - `require_signed_map` (:68-74) → `map_signed` (:46-65): reads the client-supplied `file://` map_uri; returns True if JSON has `status == "SIGNED"` and a truthy `signature`, OR an audit `signature.create` of `map_approval` with record_sha256 == sha256(bytes). It does NOT recompute `MapDocument.content_sha256()` against `signature.content_sha256`, does not look the signature up in the signature register, and does not confine the URI to the tenant/project store. grep for `content_sha256()` comparisons: none outside map.py sign/revise and plan_api (CONFIRMED).
  - `require_signed_limits` (:77-82): 422 if stage_budgets_seconds set outside development.
  - `require_cpf_matches_map` (:85-105): D-36, `cpf_differences(map, cpf)`; 409 on any departure or unreadable.
  - `cpf_sha256` from the client is never checked against the CPF bytes at start (no hash compare in campaign_api/run_guard) — POTENTIAL integrity gap (it is a label carried through the request).
- Backend: `settings.execution_backend == "temporal"` → `Client.start_workflow("ModelingCampaignWorkflow", ...)` (:61-73); else local `runner.start(...)` (`LocalCampaignRunner`, services/orchestrator/src/modeler_orchestrator/campaign_runner.py) → `local_runner.start_campaign` (local_runner.py:1153-1169): writes QUEUED record, then a **daemon thread** runs `_run_with` → `LocalExecutor.run`.
- No startup reconciliation of campaigns orphaned by an API restart: main.py lifespan (:44-56) resumes Data-room runs only; grep finds no campaign recovery. A campaign whose thread dies with the process stays RUNNING in campaigns.json (POTENTIAL, high operational impact). Exceptions inside a stage are caught (local_runner.py:524-530) → FAILED, so in-process errors do surface.

## LocalExecutor.run (services/orchestrator/src/modeler_orchestrator/local_runner.py:438-591)
1. S0: `plan_campaign` (campaign_activities.py:113-131): CPF completeness (`check_completeness`), D-36 departures as notes (dev), model system → every compound checked, `unplaceable_parameters`, `missing_expression_profiles` (:145-162). Not ready → ESCALATED `S0_not_ready`.
2. For each stage in request.stages (default CAMPAIGN_STAGES = S0,S1,S2,S3,SM,SJ,S4,S5,S6,S7, runs.py:194):
   - S6 gate: if not in `approved_gates` → writer.resume saved, escalation `SIGNATURE_REQUIRED` (options approve/abort), status `AWAITING_SIGNATURE` (:476-487).
   - `plan_stage` (campaign_activities.py:165-194): kind from MAP `stage_coverage`: absent (SM without metabolite plan), skip_reason (nothing to simulate → SKIPPED), joint, validate, predict, report, fit.
   - dispatch: joint → `_run_joint`; validate → `_run_validation`; predict → `_run_prediction`; report → `_run_package`; else `_run_stage`.
   - training stage PASSED with a changed CPF → `_no_regression` (:834-858) re-judges every earlier passed training stage on the new CPF; regression → `_run_joint(after_regression=True)` over stages up to this one; joint fails → ESCALATED `regression` (:531-548).
   - `_influence` after every stage (:977-981); `_persist` writes stage evidence via `package_activities.persist_stage_evidence`, swallowing OSError (:715-730).
   - Stop statuses ESCALATED/ABORTED/FAILED → resume state persisted; S5 `external_validation_failed` → `_diagnose_s5` + `record_feedback` (EXTERNAL_VALIDATION_FAILED with feedback options); else `record_escalation` (:560-582).
3. All done → COMPLETED (:584-591). Final CPF acceptance is described as a later review-inbox action (docstring :16-18); in the local path there is no final-CPF gate in code (the Temporal workflow has one, campaign.py:396-404).

## Limits (`_limits`, :593-612)
- Budget: request.stage_budgets_seconds[stage] ("set at the start") > signed MAP stage_plan budget_seconds > 1800 s default (`_DEFAULT_STAGE_BUDGET_S`, :88). Rounds: MAP stage_plan max_rounds > request.max_rounds_per_stage (4). The source is written as a stage note.
- Budget is checked only at the start of each round (:625-629). Fit planning raises `BudgetTooSmallError` → ESCALATED `budget_exhausted` (:641-646). In the local path `assess_fit_round(..., deadline_reached=False)` is always passed (:1058): running engine jobs are not cancelled at the stage deadline by the executor; only each EngineJob's own timeout_s bounds them (prepare_round_job timeout = max(60, remaining), campaign_activities.py:518).

## Round (`_run_round`, :996-1048)
build_round_snapshot → engine simulate → (fit round) collect_pkml_inputs → `_run_fit` (plan_jobs multistart, ThreadPoolExecutor of engine subprocesses, `fit_workers` = cores ÷ sims-per-start, ≤ cpu_count, override MODELER_FIT_WORKERS; :145-153, :1050-1069) → run_round applies estimates → if CPF changed: re-simulate the fitted CPF (phase "postfit") and judge that (:1014-1024) → evaluate_round → if gate passed and VPC stage: prepare_vpc_jobs (population, 100 individuals) + evaluate_vpc; VPC fail → escalate `vpc_coverage_below_80` → else diagnose_round → choose_action.

## Fit application — POTENTIAL defect
- `_apply_round_fit` (campaign_activities.py:619-671) writes the best start's estimates into a new CPF unconditionally (no comparison against the pre-fit objective or the pre-fit verdict). The next round carries the fitted CPF.
- `_run_stage` sets `best_uri, best_sha = cpf_uri, cpf_sha` after every round (local_runner.py:649-650); the Temporal StageLoop does the same (campaign.py:123-124). So the "best" CPF returned on escalation is the **latest** round's CPF. The escalation option is labelled "Accept the best round" (local_runner.py:94) and `accept_best` continues with `resume.cpf_uri` = that latest CPF (:1263-1286). A fit that worsened agreement is what gets accepted. Label vs behaviour mismatch (CONFIRMED in code; impact depends on whether worse fits occur).

## Strategist
- `choose_action` (campaign_activities.py:1054-1073) calls `modeler_agents.strategist.decide` with no `decider` → deterministic fallback = first not-yet-tried permitted action (strategist.py:106-125). `llm_decider` (strategist.py:171) is not called anywhere outside tests (grep). The LLM strategist is built but unwired.

## Diagnose (campaign_activities.py:939-1051)
Per-study residual ratios (AUC, Cmax, tmax, t½, early-phase, Vss) from evaluation metrics; candidates from `STAGE_PLAN[stage].fit_candidates` filtered by `_fittable_candidates` (value present, fit policy allows the stage, bounds exist, harvested PK-Sim path) (:804-837); multi-compound subjects (`subjects`, `_qualify_action`, `_merge_diagnoses`); fit signals on post-fit pass (at_bound, correlated pairs, starts agreement); fix_and_refit pairs decided by `identifiability.choose_fixed` from signed sources, else escalate (:907-931). Docstring admits early-phase residual / secondary peak evidence is partly not wired (:944-948).

## Evaluate (campaign_activities.py:700-797)
Reads MAP (role INTERNAL→fitting else validation; S5 groups by food state), engine `profiles.json`, observed PK (auc, cmax, tmax, thalf, window, sample points, infusion time); `assess_round(..., ruleset=map_doc.acceptance.as_ruleset(), internal_target_pe=...)` — judged by the criteria signed into the MAP (D-35), not today's ruleset file. Missing MAP/results → gate cannot pass (never a false pass).

## Validation S4/S5 (`_run_validation`, :679-708)
One round judge_only from the final CPF, `skip_unbuildable=True` for validation stages (unbuildable studies named "NOT SIMULATED"). Failure → ESCALATED internal_/external_validation_failed; options accept_best ("Record a limitation and continue") / abort (:100-103).

## S5 feedback cycles (feedback.py, local_runner.py:944-975, 1185-1361)
- `_diagnose_s5`: failing studies, sensitivity of failing studies (`prepare_feedback_sensitivity`), influence map, `feedback.diagnose` → per study: failed metrics, direction, class, learn_stage (IV→S1, fed→S3, other formulation→S3/S2), documented differences, influences; per class learn possible / cap (LEARN_CAP_PER_CLASS = 1, D-05) / not achievable; MS-01 §6.6 path 1/2/3 and a recommendation.
- Decisions: accept_best (limitation, context of use restricted), learn (MAP deviation: studies move external→internal, MAP revised and signed by the decision's signature id, `map-cycle{n}.json`; re-run [S(k), SJ, S4, S5]), new_evidence (one numeric parameter replaced by a measured value in the CPF's own unit, inside plausibility, with reference; status FIXED; re-run from S1; flagged "prompted by S5"), abort.
- Guardrails in code: `check_learn`, `check_evidence` (feedback.py:189-252). `decision_digest` binds decision + payload (:280-284).

## Escalation resolution (`resolve_escalation`, :1220-1318)
Actions: retry, accept_best, abort, approve, learn, new_evidence. approve checks `gate_refusal` (real-data rule, plan §9.4/D-19: data not real refuses the S4/S5 signature outside exploratory projects; :1178-1182). Claim = `remove_escalation` (double-decision refused). Continues on a daemon thread. `retry` re-runs the stage from the escalated CPF with no new action (pending cleared).

## SJ joint refinement (`_run_joint`, :878-942; joint.py)
Parameters FITTED at the stages involved with a fit policy; S1-fitted ones bounded to their S1 95 % CI (compensation guard); a derived MAP `map-SJ-<tag>.json` with the training scenarios relabelled SJ; baseline round + joint fit round (equal study weights, D-04: sqrt(N/(k n))); kept only if fitted, every study passes and mean(AUC GMFE, Cmax GMFE) not worse.

## S6 (`_run_prediction`, :732-765) and VBE (vbe_activities.py)
Re-simulate S4's scenarios from the final CPF with pkml export; `prepare_s6_jobs` / `evaluate_s6` (package_activities) for sensitivity + uncertainty; VBE when the MAP pins `vbe-crossover`: TEST/reference arms from the CPF formulations on a design scenario, K·n individuals created on the TEST arm and reused on the reference arm with occasion seeds 2s+1 / 2s+2, `pk_analyses.csv` → trials, GMR 90 % CI, PoS, F-304 validation gate (NOT_VALIDATED without an observed BE study).

## S7 (`_run_package`, :783-832)
load_stage_evidence → collect_bundle → prepare_reproduction_jobs (job ids `-S7-rerun-`, never memoized: memo.py NEVER_REUSE_MARKERS) → verify_package_reproduction → prepare_project_jobs/collect_projects (.pksim5; failure is a note, not a block) → finish_package; exportable → PASSED, else ESCALATED `package_not_reproducible`.

## Memoisation (memo.py)
`MemoEngine` keyed by sha256(task, sorted input hashes, options, engine key = kind:command@image digest). Reuse only when every recorded output still exists with the same hash; outputs copied; manifest warning "memoized: outputs of <job> reused". On by default for the configured engine (local_runner.py:1078-1086). Model set id = sha(cpf sha | engine key | stage scenarios sha | pbpk-domain version) (memo.py:107-119).

## Ledger / influence (history.py)
Ledger entries per working-parameter-set change with parameter diffs and the verdicts they moved; influence map parameters × studies, structural (from MAP scenarios) + quantitative (S6 normalized sensitivities AUC_tEnd/AUC_inf, C_max).

## Read model persistence
- `CampaignArtifactWriter.flush` (local_runner.py:357-384) validates against `CampaignRecord` and upserts into `<read_root>/<tenant>/campaigns.json` — one JSON file per tenant holding every campaign (with GOF series, VPC bands, ledger). `FileWriteStore._upsert` rewrites the whole file under `file_lock` atomically (packages/storage/src/modeler_storage/filestore.py:142-175). 18 flush call sites in local_runner. Read API reads the whole list per GET (services/api/src/modeler_api/read_api.py:128-160). POTENTIAL scalability hotspot as campaigns accumulate.

## Temporal path (campaign.py, workflows.py, fitting.py, worker.py) — built, not deployed
- ModelingCampaignWorkflow (campaign.py:306-421): resume_campaign → S0 + waits `map_signed` signal (even though the API only starts after signing) → StageLoopWorkflow children → `final_cpf` signature gate. SJ, S6, S7 → SKIPPED "not wired in the Temporal workflow yet" (:356-364). No no-regression gate, no feedback cycles, no VPC? (VPC is there: `_vpc` :184-205). No real-data gate before S6. Stage budgets: request.stage_budgets_seconds or 1800 (does not read the signed MAP's stage_plan, unlike local `_limits`) (:64-66); max_rounds from request only. `cycle` not passed to RoundContext.
- Resume POTENTIAL defect: `CampaignStore.resume` returns `cpf_uri=request.cpf_uri` with `cpf_sha256=campaign.final_cpf_sha256` (campaign_store.py:52-55) — URI of the starting CPF paired with the hash of the final one.
- FitRoundWorkflow (fitting.py) runs starts on queue `engine-l`, cancels pending at the deadline (`deadline_reached` true) — the deadline guarantee (D8) exists only on the Temporal path.
- `ingest_results` (activities.py) is a placeholder: "Until then only the manifest is acknowledged".
- Worker task queue "orchestrator"; engine queues engine-s / engine-m / engine-l.

## Postgres schema (services/api/migrations/*.sql) — used today only for Part 11 copies (per continuation doc §4.2); campaign tables back the Temporal CampaignStore
- 0001_core.sql: tenants, users, engine_images (digest UNIQUE, status BUILT/QUALIFIED/RETIRED), model_versions (immutable trigger, status DRAFT/EVALUATED/LOCKED/SUPERSEDED/QUARANTINED), parameter_provenance (source_type enum incl. ParameterIdentification; Assumption needs ≥50-char justification), runs (memo unique index on tenant, model_version, task, image digest, options_hash, seed), signatures (meaning ∈ Authored/Reviewed/Approved/QA Released; record_sha256; auth_method), audit_events (seq, prev_hash, row_hash; PK tenant+seq). reject_mutation() triggers: audit_events (UPDATE/DELETE/TRUNCATE), signatures, model_versions. RLS `tenant_isolation` on app.tenant_id; REVOKE UPDATE/DELETE/TRUNCATE on audit_events, signatures.
- 0002_campaigns.sql: campaigns (status CHECK RUNNING/COMPLETED/ESCALATED/REJECTED — no ABORTED/QUEUED/AWAITING_SIGNATURE/FAILED), campaign_stages (status CHECK RUNNING/PASSED/ACCEPTED/ESCALATED/ABORTED/FAILED — no SKIPPED although STAGE_STATUS has it, runs.py:197), campaign_rounds (append-only), escalations, deviations (append-only). RLS forced on all five. FKs to questions_of_interest/cpf_versions/maps deferred (comment :3-4).
- 0003_agents.sql: agent_runs, agent_steps (append-only), proposals. 0004: signatures.record_id → text; users.email nullable.
- POTENTIAL: DB status enums narrower than the application's (QUEUED, AWAITING_SIGNATURE, ABORTED campaign; SKIPPED stage) — would reject rows if the file read model moved to Postgres as is.
