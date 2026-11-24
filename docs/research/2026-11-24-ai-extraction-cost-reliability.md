# AI and LLM automation in PBPK, and running LLM extraction cheaply and reliably (literature review, 2026-11-24)
Research report by a literature agent; not SME-reviewed. Cost figures are estimates at list prices fetched 2026-11-24.

**For:** the Modeler One data room (agents A6–A10; about 10 files, 200 model calls and 0.5–1 M input tokens per delivery). **Date:** 2026-11-24. **No other repository file was edited** (this report is the one file it wrote). I read some code for context: `services/agents/src/modeler_agents/claude.py`, `llm.py`, `dataroom/stages.py`, and `docs/plans/2026-11-21-intelligent-client-data-intake.md` §9 and §15.

---

## 0. Summary

1. **The literature supports the platform's design: the AI reads and describes, code extracts and checks, the modeler decides.** A 2026 systematic review of 27 studies on LLM data extraction found:
   - numbers are extracted less reliably (47–88%) than categories (74–96%);
   - most errors are **omissions** (60–74% of errors), not invented values (hallucinations 0.08–6%) (PMID 42501879).
   - In the largest error study (664 trials, 23,069 cells), the top error was **misallocation**: the right number put in the wrong field. It was 57% of errors; omission was 23% (Fan 2026).
   - Verbatim-quote and code checks deal with invented values. They do not catch omission or misallocation, which need **coverage checks** and **structural cross-checks**.
2. **No credible evidence that a general LLM can predict fu, Kp, CL or permeability.** Purpose-built ML models (QSAR, graph networks, SMILES transformers) reach about 2-fold accuracy for CL and Vss, and about 65% of AUC predictions fall within 2-fold. These are labelled priors, never data.
3. **Agentic modelling (MIDD) is early.** PKGPT, PMxAgent, ToxMCP and MAPLE all produce runnable output, but each needs a human in the loop. **MAPLE** (provenance schemas plus validators for LLM-assisted QSP calibration) is the closest analogue to Modeler One. **ToxMCP** already wraps the OSP Suite as typed, audited tools.
4. **Regulators:**
   - FDA's January 2025 draft guidance sets a 7-step, risk-based credibility framework: model influence × decision consequence.
   - The EU GMP Annex 22 draft keeps LLMs out of critical GMP uses and requires a human in the loop elsewhere.
   - Best positioning: the LLM is a low-influence proposal generator. Deterministic code checks it and a human confirms it. **Reproducibility means re-deriving inputs from stored outputs, not re-running the model.**
5. **Cost is small; reliability matters more.** My estimate at list prices is roughly $3–15 per delivery, with output and thinking tokens likely the largest share on Opus 5.5. The best cost levers are:
   - make the cached prompt prefix shareable across files (today the extractor's system prompt and tools vary per file);
   - sweep effort per agent, and re-run only the files that fail verification at higher effort;
   - a content-hash response cache with versioned keys;
   - a cheap triage model only after an evaluation shows it does not miss files.

   Batch APIs fit evaluation runs, not interactive runs. Anthropic's Message Batches API is not available on Bedrock.
6. **Reliability:** keep resume at the (file × stage) step. On model failover, **restart the step** rather than continue the conversation on another model. Thinking blocks and caches are tied to a model, and provenance needs one author per output.

---

## 1. Method and counts

- **PubMed:** 13 queries, 241 records with title and abstract.
- **Consensus:** 4 semantic queries, 150 records. The free quota then ran out (notice at the end).
- **Web:** FDA draft guidance, Annex 22, provider pricing pages, Self-Route. Anthropic's pricing, prompt-caching and cost-optimization pages were fetched on 2026-11-24.
- **Totals:** about **370 unique records screened** by title, about **110 abstracts read**, **about 95 sources cited**: 59 from PubMed, 38 from Consensus, and web or provider documents.
- **Limits:**
  - Abstracts only; no full texts.
  - Computer-science venues were reached only through Consensus and web search.
  - The searches on long context versus retrieval and on agent memory relied on web search and a few well-known papers marked "not re-verified".
  - **No peer-reviewed study on LLM decimal-separator or locale errors was found.** Those recommendations are engineering judgement.
  - Whether the FDA guidance has been finalized was not checked.

---

## 2. Part A — literature findings

### A1. ML and AI prediction of PBPK inputs (fu, Kp, CL, permeability)

- **Typical accuracy is about 2-fold:**
  - Roche, 9,685 compounds (rodent): CLp and Vss average absolute fold error 1.96–2.84; oral bioavailability is harder (PMID 36595708, DOI 10.1021/acs.jcim.2c01134).
  - Human CLtot: geometric mean fold error 1.92, 66.5% within 2-fold. Vdss: 1.64 and 71.1% (PMID 35993595, DOI 10.1021/acs.jcim.2c00318).
- **ML inputs fed to PBPK:**
  - ML-predicted fu, Caco-2 permeability and clearance gave AUC within 2-fold for 65.0% of 40 compounds, against 47.5% using in-vitro inputs (PMID 38918309, DOI 10.1007/s11095-024-03725-y).
  - An AI-PBPK platform, validated against PK-DB on 71 IV and 606 oral administrations, put most AUCs within 2–3-fold (PMID 40418625, DOI 10.1002/cpt.3732).
- **fu and Kp:**
  - SMILES-BERT model for fu (PMID 37656906, DOI 10.1021/acs.molpharmaceut.3c00129).
  - Kp QSAR models built on small, sparse sets of 119 compounds × 9 tissues (PMIDs 37266860, 38639496).
  - Rat CLint,u from 2,639 proprietary compounds (PMID 37713584).
  - High-throughput PBPK fed with ML-predicted inputs (PMID 41617209).
- **Drift is real.** A 20-month prospective industrial validation (120 datasets, including human and rat plasma protein binding) found that regular retraining raised accuracy (PMID 37216672, DOI 10.1021/acs.jcim.3c00160).
- **Reviews:** PMIDs 36156156 (DOI 10.1093/toxsci/kfac101), 41093240 (10.1016/j.addr.2025.115716), 38727016 (10.1080/17460441.2024.2348157).
- **The LLM's role here is curator, not predictor.** PharmaBench used a multi-agent LLM system to mine experimental conditions from 14,401 bioassays (PMID 39256394, DOI 10.1038/s41597-024-03793-0).
- **Implication:** ML predictions enter the CPF only as labelled *in-silico priors*, with a model version and an applicability-domain flag. Never as client data.

### A2. Automated model building and agentic workflows

- **PKGPT** (Gemini 3 Flash, recursive agent for NONMEM; PMID 42076151, DOI 10.3390/pharmaceutics18040501):
  - always produced runnable, converging models;
  - but gave a physiologically implausible peripheral volume (V2 = 149 L against the expert's 13.2 L);
  - missed established covariates, and repeat runs varied;
  - the authors conclude a human in the loop is required.
- **NONMEM coding with LLMs:** basic structures are fine; complex models need human review (PMIDs 41187068, 38656706, 40464844, 37952004).
- **Tools beat free-form generation:**
  - **PMxAgent** (MCP over R tools): NCA accuracy of 98.3% across 182 drugs, matching or beating frontier agents [Bloomingdale 2026].
  - **ToxMCP** wraps the OSP Suite PBPK engine, among others, as typed MCP tools with provenance bundles, applicability-domain checks and confirmation of critical actions [Djidrovski 2026].
  - Related: Talk2Biomodels (PMID 41254502); MCP model prototyping [Ruscone 2026]; GRASP, a typed knowledge graph that keeps units consistent, F1 = 0.95 [Bazgir 2025]; Mozi, governed autonomy with human checkpoints [Cao 2026].
- **MAPLE (PMID 42535762, DOI 10.1002/psp4.70306)** is the closest design to Modeler One:
  - structured schemas separate extraction from modelling decisions;
  - validators match each value to a source snippet, resolve DOIs and execute code;
  - **50 automatic retries were triggered before any human review**;
  - every value carries a direct quote and a verified citation;
  - modelers still revised forward-model choices in 65% of targets and priors in 46%.
- **Silent numeric failures:** of 200 LLM-written scripts for a 3-compartment PK model, 2.5% were wrong or structurally defective even though they ran [Omote 2026, medRxiv]. Runtime code must be human-written and tested, not generated.
- **Non-LLM automation is mature:** Pharmpy automatic model development [Chen 2024]; Simcyp Designer automated assembly (PMID 40430895). Reviews: Tosca 2025 (PMID 41155911, DOI 10.3390/pharmaceutics17101274); Shahin 2025 [Agents for Change]; PMID 37621112; PMID 40214191.
- **Memory for long agent runs:** a 3-layer memory capped injected state at a median of 301 tokens and improved PKPD parameter recovery [Tewari 2026, arXiv].

### A3. How accurate is LLM extraction?

| Study | Setting | Result | Main errors |
|---|---|---|---|
| Shankar 2026, SR of 27 studies (PMID 42501879) | evidence synthesis | 47–99.9% overall; numeric 47–88%, categorical 74–96% | omissions 60–74%, hallucinations 0.08–6%. Few-shot prompts plus structured output help. Model version and inference settings often unreported |
| JCE 2026 SR (PMID 41831731) | systematic-review tasks | extraction median accuracy 0.95 (IQR 0.91–0.97, n=11) | wide range, 0.36–1.00 |
| Gartlehner 2025, Ann Intern Med, prospective study within 6 reviews [link] | Claude extracts, human verifies, vs human-only; 9,341 elements | 91.0% vs 89.0%; major errors 2.5% vs 2.7%; 41 min saved per study | missed items most frequent in both arms |
| Fan 2026, BMJ EBM [link] | Claude 3.5 Sonnet, 664 RCTs, 23,069 cells | 6.6% error rate | **misallocation 57.1%**, omission 23.2%. Better-reported trials (CONSORT) gave fewer errors |
| Yisha 2026 (PMID 41535766) | 105 RCTs | group size 91–94%; event counts 57–71%; **mean/SD 24–56%** | numeric outcomes |
| Oami 2026 (PMID 42137114) | 3 LLMs, 3 prompt strategies | outcomes 27.8–80.7%; **session-to-session consistency 44.8–65.6%** | self-reflection prompting gave modest gains and doubled time |
| Konet 2024 (PMID 38895747) | Claude 2 vs GPT-4 + PDF plug-in | 96.3% vs 68.8%; **with clean text supplied: 98.7% and 100%** | PDF parsing was the bottleneck |
| Khan 2025, JAMIA (PMID 39836495) | two LLMs cross-checking | concordant answers 0.94 accurate; discordant 0.41/0.50; cross-critique → 0.76 | disagreement is a strong review signal |
| Dual LLM 2026 (PMID 42015569) | GPT-5.2 + Gemini 3 Pro | both correct 82%; at least one correct 95.1% | — |
| Sleep-medicine RCTs (PMID 41192088) | 648 RCTs | ≤71.5%; multi-sentence prompts beat single-sentence by up to 11% | — |
| HIV papers (PMID 38918736) | GPT-4, 3,600 questions | 86.9% | more **false positives when each question is asked alone**; instruction sheet did not help |
| Public-health RAG pipeline (PMID 41195132) | Llama-3-70B | 68% acceptable; repeat-run agreement 0.71 | non-determinism |
| Domain pipelines | CYP450 extraction (PMID 40858183) P 0.987 / R 0.963; SEETrials (PMID 39493413) F1 0.974; PK table classifier F1 > 96% with GPT-4 only on uncertain cases (PMID 40128567); PK named-entity recognition, BioBERT F1 90.4% (PMID 39379460) | — | — |

Further context:
- Generic evaluations rarely use real data: only 5% of 519 health-care LLM evaluations used real patient-care data (PMID 39405325).
- **ExtractBench** [Ferguson 2026]: frontier models degrade sharply as the output schema widens, down to **0% valid output on a 369-field schema**. It scores each field by type (exact match for IDs, tolerance for quantities) and separates omission from hallucination.
- **Tan 2026**: errors are structural (role reversals, binding drift, numbers attached to the wrong analysis), and long multi-document inputs make them worse.
- **Implication for Modeler One:** published accuracy comes mostly from well-reported trials. Expect worse on raw CRO tables, since reporting quality predicts error (Fan 2026).

### A4. Table error types and mitigations that worked

| Error type | Evidence | Mitigations that worked |
|---|---|---|
| Column shift, wrong row or wrong field ("misallocation", data-referencing error) | 57% of errors (Fan 2026); occurs in every model tested [Yang 2026]; numbers attached to the wrong analysis [Tan 2026] | a critic step on data references, +12% accuracy [Yang 2026]; table splitting and explicit representation, F1 96.8% [MaTableGPT]; schema-driven extraction, F1 74–96 [Bai 2024]; **code reads the cells from an LLM-written layout description** (Modeler One's current design) |
| Omission | the dominant error type (PMID 42501879; Gartlehner 2025) | coverage ledger per checklist item; second model; making "not reported" an explicit, acceptable answer (both LLMs recognized missing items in Konet 2024) |
| Units, quantities, modifiers (<, ±, ~) | taxonomy of measurement hallucinations: quantities, units, modifiers, relations [MeasHalu 2026] | deterministic unit parsing; store the original text **and** the parsed number with its parse rule [KnowMat 2026]; strict schema plus rule checks plus a recovery module [Serdiukov 2026] |
| PDF parsing and OCR cascade | the plug-in caused most of GPT-4's errors (Konet); OCR noise cascades into retrieval [OHRBench, Zhang 2025]; table extraction is still hard on heterogeneous PDFs [Soric 2026] | layout-aware local parsing (as now); evaluate parsers semantically [Horn 2026]; uncertainty scores per table cell [Ajayi 2025] |
| Merged cells, multi-level headers | — | split and re-represent tables before prompting [MaTableGPT]; one line-based representation for every file type (the platform's own §15 #1 finding agrees) |
| Spreadsheet auto-conversion | Excel turned gene names into dates in one-fifth of papers (PMID 27552985, DOI 10.1186/s13059-016-1044-7), rising to 30.9% by 2021 (PMID 34329294) | read raw cell values and number formats, never displayed strings; flag date-like serial numbers |
| Decimal separators and locale | **no peer-reviewed LLM study found** | deterministic per-file locale detection by code; never let the LLM normalize a number |
| Invented values | rare (0.08–6%) but not zero | verbatim quote plus value-in-quote check (MAPLE; already in Modeler One); follow-up questions, about 90% precision and recall [ChatExtract]; cross-document outlier check, 98% outlier precision [P-COD 2026]; semantic entropy [Farquhar 2024, Nature] |
| Non-determinism | repeat-run consistency 44.8–91.3% (PMID 42137114); agreement 0.71 (PMID 41195132) | store each output once with model and prompt version; never re-run to "reproduce" |

### A5. Regulated settings: credibility, validation, human in the loop

- **FDA draft guidance, 6 January 2025** ("Considerations for the Use of AI to Support Regulatory Decision-Making for Drug and Biological Products"):
  - seven steps: question of interest → context of use → model risk (model influence × decision consequence) → credibility plan → execute → document deviations → judge adequacy;
  - out of scope: discovery, and operational uses that do not affect patient safety, quality or **reliability of results**.
  - Data extraction that feeds a regulatory PBPK model plausibly affects reliability of results, so plan as if it is in scope ([FDA draft PDF](https://www.hhs.gov/guidance/sites/default/files/hhs-guidance-documents/FDA/59502407dft.pdf), [DLA Piper summary](https://www.dlapiper.com/en-gl/insights/publications/2025/01/fda-releases-draft-guidance-on-use-of-ai)).
  - Critiques: Niazi 2026; a GxP comparison including Annex 22 by Patel 2026.
- **EU GMP Annex 22 draft** (consultation 7 July – 7 October 2025):
  - only static, deterministic models in critical GMP uses; **LLMs and generative AI excluded there**;
  - non-critical uses allowed with a human in the loop;
  - test data kept separate from training data; the AI must perform at least as well as the process it replaces;
  - the manufacturer stays accountable for vendor AI.
  - This is a manufacturing rule, not directly binding on MIDD, but it shows regulators' direction ([EC consultation](https://health.ec.europa.eu/consultations/stakeholders-consultation-eudralex-volume-4-good-manufacturing-practice-guidelines-chapter-4-annex_en), [ECA summary](https://www.gmp-compliance.org/guidelines/gmp-guideline/eu-gmp-annex-22-draft-2025-artificial-intelligence), [RAPS](https://www.raps.org/resource/european-commission-proposes-on-updated-gmp-guidel.html)).
- **MIDD credibility frameworks** based on ASME V&V40:
  - Kuemmel 2020, applied to PBPK (PMID 31652029, DOI 10.1002/psp4.12479);
  - Musuamba 2021, credibility matrix; Rusten 2021, empirical pharmacometric models; Viceconti 2020, in-silico trials;
  - Aldieri 2025, 12 statements on the credibility of ML predictors; PROBAST+AI (Moons 2025); TRIPOD-LLM reporting gaps (PMID 42501879).
  - ICH M15 uses the same risk-informed logic (not re-verified in this session).
- **Human in the loop:**
  - The best evidence is the prospective, blinded Gartlehner 2025 study: LLM first pass plus human verification was at least as accurate as human-only, and faster.
  - Other designs: an HTA review system with a human adjusting the PICO criteria live (PMID 40036547); human-in-the-loop computer system validation with rationale cards, confidence bands and risk tiering [Amin 2026].
- **21 CFR Part 11:** no paper addressing LLMs under Part 11 was found (a gap). The engineering reading:
  - the LLM's output is a *proposal*;
  - the GxP record is the human-confirmed value, with its audit trail and step-up signature;
  - model ID and version, prompt version, input hashes and the raw output are metadata of that record.

### A6. Knowledge graphs

- **Literature-mined triples are noisy:** chemical–gene relations scored a precision-recall AUC of 0.50 against curated data (PMID 37682956, DOI 10.1371/journal.pone.0291142).
- **NP-KG** (745k nodes, 7.2M edges; PMID 36933632) needed error analysis to find wrong predications.
- **Typed graphs that keep units consistent work for building models** [GRASP].
- **PK-DB** shows what to keep: normalized units, explicit experimental errors, ontology annotation (PMID 33151297, DOI 10.1093/nar/gkaa990).
- **Implication:** an internal fact graph (compound → parameter → anchored source → who confirmed) is useful. A literature-mined graph is not a source of model inputs.

### A7. Gaps in the literature

- Nothing on LLM extraction from **raw CRO and sponsor deliveries** (as opposed to published papers).
- Nothing on decimal-separator or locale errors.
- No study of LLM extraction under Part 11.
- No PBPK-specific (PK-Sim or OSP) LLM extraction benchmark. A searchable PBPK + LLM query returned 14 hits, none an evaluation.

---

## 3. Part B — engineering

### B1. Where the money goes (estimate, not measured)

**Assumptions:**
- 200 calls, 0.75 M input tokens, about 1,500 output tokens per call (visible plus thinking) = 0.30 M output.
- First-party list prices fetched 2026-11-24 ([pricing](https://platform.claude.com/docs/en/about-claude/pricing)): Opus 5.5 $4 in / $20 out per million tokens; Sonnet 5.5 $2 / $10; Haiku 5.5 $0.10 / $0.50 for prompts up to 100k tokens ($0.50 / $2.50 above).
- Cache reads cost 0.05× input on Opus and Sonnet 5.5 and 0.1× on Haiku 5.5; 5-minute cache writes 1.25×; 1-hour writes 2×.
- **Bedrock prices are set by AWS; verify them.**

| Scenario | Input | Output | Total per delivery |
|---|---|---|---|
| Opus 5.5, no cache | $3.00 | $6.00 | ~$9.00 |
| Opus 5.5, 80% of input read from cache | ~$0.87 | $6.00 | ~$6.90 (−24% total, −71% input) |
| …plus output halved (effort, terser output) | ~$0.87 | $3.00 | ~$3.90 |
| Sonnet 5.5, 80% cached | ~$0.44 | $3.00 | ~$3.40 |

**Takeaway:** output and thinking tokens probably dominate. Caching is necessary but is not the whole answer. At these sums, a modeler-hour costs more than many deliveries, so the target metric is **cost per correctly extracted input** and protection against runaway tail runs.

Two code facts that matter:
- The extractor's system prompt is built per file (`extract_system(topics)`), and its tools appear to be built per file (`_doc_tools({path: …})`, `_search_one(path, doc)`). If their names, descriptions or schemas embed the file, each file's cache starts from byte zero.
- The delivery-wide block (question, products, checklist) comes after those file-specific parts, so files cannot share it.

### B2. Cost techniques

"Measured" means measured by the cited source on its own workload. "Estimate" means my estimate for Modeler One.

| Technique | Expected saving | Basis | Risks | Fit for Modeler One |
|---|---|---|---|---|
| **Provider prompt caching with a cross-file prefix:** tools and common system (breakpoint) → topic vocabulary (breakpoint) → delivery block (breakpoint) → file block → turns (automatic caching) | Measured: 83–86% off a small triage agent; 4.8–7.2× on a research agent; healthy loops read a median 84% of input from cache. Estimate here: −60–75% of input spend, −20–25% of total | Anthropic [cost-optimization page](https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence), [prompt-caching page](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) | silent invalidators (timestamps, unsorted JSON, per-file tool text, changed effort, tool_choice or images); minimum cacheable 512 tokens on the 5.5 models; **parallel requests miss until the first response starts**; caches are per model, per workspace on the Claude API and per organization on Bedrock; max 4 breakpoints | Caching is on already. Restructure the prefix, warm one request before fanning out, keep a trimmed variant for small-context providers (Groq at 8k) |
| **Exact response cache keyed by content hash:** file sha256 + parser version + prompt version + tool-schema version + model + effort + input bytes | 100% of repeated calls; on re-runs or a delivery with one new file, most calls (estimate) | engineering; the per-file × stage store already does part of this | stale hits if a version is missing from the key. **Never use semantic or fuzzy caching for numbers** | extend the existing sha256 store's key |
| **Code-selected pages with escalation to the whole document** (Self-Route pattern) | Measured: −39% to −65% cost at long-context accuracy ([Li et al., EMNLP 2024 Industry](https://aclanthology.org/2024.emnlp-industry.66)) | long context also loses mid-document facts ("Lost in the Middle", Liu et al., TACL 2024, DOI 10.1162/tacl_a_00638, not re-verified); clean text raised accuracy to 98.7–100% (Konet) | retrieval misses become omissions, the dominant error | already done (`_focus`). Add an explicit escalation step and measure page-selection recall |
| **Effort sweep per agent** | Measured: research work at `low` gave up 1–3 points for 33–50% off; another benchmark lost 13 points at `low` | Anthropic cost page | accuracy loss on hard tables; needs the evaluation | Opus 5.5 defaults to `medium`; sweep A7–A9 on the answer keys |
| **Re-run failures at higher effort or a stronger model** | Measured: about 40% less than running everything at `high`, same pass rate | Anthropic (SWE-bench Pro) | needs a failure signal. Code verification gives one for numbers, **not for omissions** | strong fit: verification failures trigger escalation |
| **Cheap-model routing for triage** (a 40× price gap, Opus 5.5 vs Haiku 5.5) | Measured on benchmarks: FrugalGPT up to 98%; RouteLLM over 2×; Hybrid LLM 40% fewer large-model calls; early abstention −13% cost and −5% error | Dekoninck 2025 (the quality estimator is the crux); Bouchard 2026 (two models are enough) | triage misses are silent; caches not shared across models; Haiku 5.5 costs 5× more above 100k-token prompts | triage only, after an evaluation shows no missed files |
| **Batch API** (50%, stacks with caching on Anthropic) | 50% of batchable traffic | Anthropic pricing; Bedrock batch inference also 50% for selected models ([AWS](https://aws.amazon.com/bedrock/pricing/), [announcement](https://aws.amazon.com/about-aws/whats-new/2025/08/amazon-bedrock-batch-inference-anthropic-claude-sonnet-4-openai-gpt-oss-models)); OpenAI also 50%, but whether its batch and caching discounts stack is unclear ([docs](https://developers.openai.com/api/docs/guides/prompt-caching.md)) | 24 h window; no tool loop; **Anthropic Message Batches not on Bedrock**; Claude 5.5 on Bedrock batch unverified | evaluation and regression runs only |
| **Token and cost budgets per stage, early exit** | caps the tail: in one measured run 2 of 20 tasks carried 43% of spend | Anthropic | a hit cap means omissions. **Treat a cap-hit as a failure**, never as an answer | `max_turns` exists. Add a $ and token cap per run with an alert |
| **Output hygiene** (strict schemas, terse answers) | Measured: about 13% (39% fewer output tokens) | Anthropic | — | yes |
| **Input hygiene** (narrow tools, no tool recaps, local OCR rather than images) | Measured: 21–26% off a triage agent | Anthropic; vision is billed by pixel area | — | mostly done (local RapidOCR) |
| Context editing or compaction | Measured: context editing **added 73%** on a short run; compaction −32% only on long runs | Anthropic | breaks the cache | **skip**: loops are at most 14 turns |

### B3. Reliability techniques

| Technique | Notes and evidence | Risks | Status in Modeler One |
|---|---|---|---|
| Retry with backoff and jitter on 408/409/429/5xx and connection errors; honour `retry-after` | SDK default; wall-clock can reach timeout × (retries + 1) | duplicate side effects if a tool is not idempotent | done (`_RETRY_STATUS`, `_retry_after`, `max_retries=4`) |
| Rate budgeting per provider | Groq free tier: 8k tokens per minute | — | partly done (waits) |
| **Model failover at the step level** | Opus 5.5 thinking blocks are model-bound (Sonnet 5.5 cannot read them; they are dropped); caches are per model | mixed-author outputs | `FallbackChat` exists; make failover **restart the step** and record the author |
| Step journal and checkpoint | unit = (delivery, file sha256, stage, prompt version, model); append-only; write then rename | partial or corrupt writes | per-file × stage store plus `run.json`: add versions to the key and write-then-rename |
| Turn-level resume of a tool loop | possible only if append-only, same model, same tool schemas, and every `tool_use` has a `tool_result` | the history-editing check on Opus 5.5 rejects edited history; orphaned tool calls | **not needed now** (≤14 turns); restart the step instead |
| Idempotent tools | read tools are safe to re-run; `submit_*` must be idempotent per key | — | read tools yes; check the submit tools |
| Circuit breaker and cost guard | stop a run when error rate or spend crosses a threshold | — | add |
| Plan for non-determinism | `temperature`/`top_p` are rejected on the 2026-10-21 API version; repeat-run agreement 0.45–0.91 in the literature | — | store outputs; reproduce by deterministic re-derivation |

### B4. Resuming a multi-turn tool conversation after an error

1. **Transient error (429, 5xx, timeout):** resend the identical request bytes. The prefix is cached, so it is cheap. The SDK already does this.
2. **Process died mid-loop:**
   - Default: **restart that file × stage unit from its start**. It is cheap: one unit is about 1/10 of a stage.
   - Resume from the stored transcript only if all of these hold: same model, same tool schemas, the transcript is byte-identical and append-only, thinking blocks are sent back unchanged, and every unanswered `tool_use` gets a `tool_result` (re-run the read-only tool).
3. **Always restart rather than resume** when:
   - the model changed (failover or refusal fallback);
   - the prompt or tool-schema version changed;
   - a partial answer was already persisted;
   - the transcript cannot be shown to be the one that was sent.
4. **One author per output:** each stored answer has exactly one model and prompt version. Never splice answers from two models. The checker stays a different model, which is already the plan.

### B5. Agent memory across a project

- **Worth keeping** (project-scoped, versioned, each item hash-anchored with who confirmed it):
  - confirmed values (already in the CPF and evidence stores, the system of record);
  - validated table layouts, keyed by file hash and locator plus a fingerprint of the header text, offered as **hints** for a recurring CRO template;
  - client conventions: BLQ and missing markers, decimal convention, time units, code maps, date formats;
  - decisions and overrides with reasons; data requests and replies;
  - negative findings ("file X, hash …, has no dissolution data");
  - evaluation scores per agent, model, prompt version and effort.
- **Not worth keeping as memory:**
  - raw transcripts (keep them as audit records, not as context);
  - unverified LLM summaries and chain of thought;
  - any number held outside the CPF;
  - anything shared across clients (confidentiality);
  - anything without a source hash.
- **Bound the injected memory.** Tewari 2026: median 301 tokens. Code re-verifies anything memory suggests.
- **Risks:** stale memory, and memory poisoned by text a client document injects. Treat document text as data; the tools are read-only.

---

## 4. Recommendations, ranked by value for Modeler One

1. **Measure before optimizing** (low effort, high value). Finish the evaluation in plan §9:
   - add **omission** and **misallocation** categories (the literature's dominant errors) next to found, missed, wrong and invented;
   - add cost per correct input, cache-read share (target ≥ 80%), and the output/thinking share;
   - aggregate the usage already logged per call into a per-run ledger.
2. **Target omission and misallocation in code** (high value; the residual risk after the quote checks):
   - a coverage ledger per checklist item: found, missing with the pages searched, or not applicable;
   - structural cross-checks on table descriptions: header-to-unit consistency, monotonic times, per-column type and range, rows = subjects × periods, and recomputing the client's mean and RSD rows (the NCA reproduction already does part of this);
   - read raw Excel values and number formats; detect the decimal convention by code;
   - store the original string, the parsed number and the parse rule.
3. **Restructure the cache prefix** (medium effort; estimated −60–75% of input spend):
   - file-agnostic tools, with the file passed as an argument;
   - static common system text, then topic vocabulary, then the delivery block (question, products, checklist), each with a breakpoint, then the file block;
   - warm one request before fanning out;
   - check that `cache_read_input_tokens` dominate.
   - Keep the trimmed per-topic variant for small-context providers. Narrow output schemas stay narrow, as ExtractBench advises.
4. **Use verification failures as the escalation signal:**
   - first pass at lower effort or on Sonnet 5.5; re-run only the files that fail checks at higher effort or on Opus;
   - get two models to agree only on mappings code cannot check (codes, arms, batches): concordant answers go to normal human confirmation; discordant ones are highlighted (Khan 2025).
5. **Step-level checkpoints and a versioned content-hash cache.** Restart-the-step on failover; record the author; write then rename.
6. **Sweep effort per agent on the answer keys** (the cinacalcet case and the CI fixture). Only then consider a cheap triage model, with at most a two-model cascade.
7. **Guardrails:** $ and token caps per run and per stage; a cap-hit counts as a failure; a circuit breaker on error rate.
8. **Batch only evaluation and regression runs:** first-party Message Batches, or Bedrock batch inference if the 5.5 models are listed (verify). Not interactive runs: they would break the 20-minute target.
9. **Write the extraction tool's credibility file** along the FDA 7 steps:
   - context of use and model risk (low influence, because code verifies and a human confirms; consequence medium to high, because the inputs feed a regulatory model);
   - credibility plan = the evaluation, with confidence intervals;
   - change control = re-run the evaluation on any model or prompt change;
   - record model, prompt and input hashes in the Part 11 audit trail. Signatures stay from the token's step-up.
10. **Memory of conventions and validated layouts** as hints (later), always re-verified by code.

**Do not:**
- cache extraction outputs by semantic similarity;
- add context editing or compaction (short loops);
- switch models within a conversation;
- generate numeric code at runtime;
- accept LLM-predicted fu, Kp or CL as values.

---

## 5. References

**PubMed** (PMID, DOI):
- 42501879 (10.1016/j.jbi.2026.105086)
- 41831731 (10.1016/j.jclinepi.2026.112221)
- 38432227 (10.1002/jrsm.1710)
- 38895747 (10.1002/jrsm.1732)
- 39836495 (10.1093/jamia/ocae325)
- 41535766 (10.1186/s12874-025-02729-5)
- 42137114 (10.3389/fdgth.2026.1799623)
- 41192088 (10.1016/j.smrv.2025.102192)
- 38918736 (10.1186/s12874-024-02253-y)
- 41265689 (10.1016/j.jdent.2025.106245)
- 41195132 (10.1002/cesm.70061)
- 41019842 (10.1002/cesm.70033)
- 42015569 (10.1002/ksa.70412)
- 40199559 (10.1136/bmjebm-2024-113066)
- 39903558 (10.1097/JS9.0000000000002215)
- 42525208 (10.1007/s40273-026-01648-7)
- 40113776 (10.1038/s41537-025-00601-5)
- 39493413 (10.1016/j.imu.2024.101589)
- 40858183 (10.1016/j.ijpharm.2025.126111)
- 40128567 (10.1038/s41598-025-94778-5)
- 39379460 (10.1038/s41598-024-73338-3)
- 38994403 (10.1039/d4sc00924j)
- 39405325 (10.1001/jama.2024.21700)
- 40036547 (10.1093/jamia/ocaf030)
- 42535762 (10.1002/psp4.70306)
- 42076151 (10.3390/pharmaceutics18040501)
- 41187068 (10.1002/psp4.70125)
- 38656706 (10.1007/s10928-024-09921-y)
- 40464844 (10.1007/s10928-025-09982-7)
- 37952004 (10.1007/s10928-023-09892-6)
- 41155911 (10.3390/pharmaceutics17101274)
- 37621112 (10.1111/bcp.15895)
- 41254502 (10.1186/s12859-025-06310-1)
- 40430895 (10.3390/pharmaceutics17050604)
- 40214191 (10.1111/cts.70203)
- 41709726 (10.1002/psp4.70201)
- 41121745 (10.1002/cpt.70096)
- 36156156 (10.1093/toxsci/kfac101)
- 41093240 (10.1016/j.addr.2025.115716)
- 38727016 (10.1080/17460441.2024.2348157)
- 38918309 (10.1007/s11095-024-03725-y)
- 36595708 (10.1021/acs.jcim.2c01134)
- 35993595 (10.1021/acs.jcim.2c00318)
- 37216672 (10.1021/acs.jcim.3c00160)
- 37656906 (10.1021/acs.molpharmaceut.3c00129)
- 37266860 (10.1007/s13318-023-00832-w)
- 38639496 (10.1021/acs.jcim.4c00046)
- 37713584 (10.1021/acs.molpharmaceut.3c00374)
- 41617209 (10.1021/acs.molpharmaceut.5c01317)
- 34732590 (10.1248/bpb.b21-00769)
- 40418625 (10.1002/cpt.3732)
- 39256394 (10.1038/s41597-024-03793-0)
- 33151297 (10.1093/nar/gkaa990)
- 27552985 (10.1186/s13059-016-1044-7)
- 34329294 (10.1371/journal.pcbi.1008984)
- 36933632 (10.1016/j.jbi.2023.104341)
- 37682956 (10.1371/journal.pone.0291142)
- 31652029 (10.1002/psp4.12479)
- 42874751 (10.1016/j.ejps.2026.107688)

**Consensus** (link format `https://consensus.app/papers/details/<id>/?utm_source=claude_desktop`):
- Gartlehner 2025, Ann Intern Med ([link](https://consensus.app/papers/details/w:54a3e43b-fe62-4880-a57e-d3c2b6c01ba5/?utm_source=claude_desktop))
- Fan 2026, BMJ EBM ([link](https://consensus.app/papers/details/w:55be9c47-9bd2-461b-827a-1ab8245bdf21/?utm_source=claude_desktop))
- ExtractBench, Ferguson 2026 (w:efdc5e99-bdaf-4c1d-8a46-9a5510df4990)
- Tan 2026 (w:9b66db30-4a1f-4e76-b5f6-0efa8677b2ae)
- Yang 2026 (w:4a9254a4-e043-4cba-869b-245c48ebccd1)
- MeasHalu 2026 (w:0bea86a0-d488-4ee7-ae0e-d0ab8fd191fc)
- MaTableGPT 2025 (w:f0af2a4e-28a5-47db-a30a-235c24f17378)
- Bai 2024 (w:36fc1ae0-7d6a-4e6c-af0a-ac337f50f9ed)
- ChatExtract, Polak 2024 (w:1ae60651-19e9-4465-8e84-4c368bb49b0e)
- Soric 2026 (w:6e4878e5-519a-4f55-9ac7-6ef241fe33d7)
- OHRBench 2025 (w:1fd652fb-9d19-4c47-b30e-f8f3c606731c)
- Ajayi 2025 (w:56ce14f5-fbd5-4132-9c5b-3ce4d27366e6)
- P-COD 2026 (w:1f7c1149-8d3f-4bf2-ada4-5d4191212e82)
- Farquhar 2024, Nature (w:f506380c-0dd2-4e77-8d0e-f9ae3cb0e544)
- Serdiukov 2026 (w:da39a7eb-ea8f-4f33-bf3a-7ce03790d2bf)
- KnowMat 2026 (w:e8a10f23-73d0-47bf-aec1-c5616041f80f)
- Horn 2026 (w:c6ca1afe-0351-403e-966a-09ec697234d4)
- FrugalGPT 2024 (w:56d9d9b7-f85a-4596-ac3b-a9a21f3f827b)
- RouteLLM 2025 (w:142375ea-56e2-4a71-aa23-aa07c248a8a1)
- Hybrid LLM 2024 (w:11f221c2-0f50-4099-a0cf-19dc5048a795)
- Dekoninck 2025 (w:30fe4d5f-07b8-4c43-91ef-6cc3874b422a)
- Bouchard 2026 (w:aa4794e8-451b-4d1b-8d8b-e1a9d1c9f2be)
- Zellinger 2025 (w:664cb9d6-bbee-43e0-bab2-3a0eb2e87582)
- PMxAgent 2026 (w:4b305968-2302-48d0-984d-ab9a8b3310f6)
- Tewari 2026 (w:a7d99f3e-fc1e-436d-ad90-ad8f6df85c21)
- Shahin 2025 (w:04210c70-34b6-409a-a586-659729ab67a6)
- ToxMCP 2026 (w:4436ff35-06d0-4460-be36-8bca4bc24c5e)
- Pharmpy automatic model development, Chen 2024 (w:91717e85-4f7d-4474-aa8e-7cd5f64915fd)
- GRASP 2025 (w:efc84361-96d4-4b7a-9591-e1105c70538c)
- Omote 2026 (w:42cbbdfa-7dc2-4aeb-ad3a-9690fa3573e0)
- Mozi 2026 (w:93fe0f5c-0d2f-4b3d-8e9d-67d455c9f5fb)
- Ruscone 2026 (w:f6899f57-e432-4f6f-aa08-7c1ba099e8e2)
- Musuamba 2021 (w:a746902b-0590-4240-8061-a649bf2694eb)
- Rusten 2021 (w:88a9b1a2-6b3d-425e-9d7d-ecabfa5c8d1f)
- Viceconti 2020 (w:b6b64390-f07b-4bd8-8572-0dee94d0d9f1)
- Niazi 2026 (w:d94648d2-3784-4c6b-b1d5-4f1ab1df785c)
- Aldieri 2025 (w:be01945b-45b1-4af8-a445-f56fca7296df)
- Patel 2026 (w:9f6d5f28-40bf-44c6-b239-cc85ead9fb63)
- Amin 2026 (w:fdda56c6-5ca7-4158-a58a-dafd0f60b0e9)
- PROBAST+AI, Moons 2025 (w:bd1f783d-7ce6-4f15-8809-401054aecc43)

**Web and provider documents:**
- [FDA draft guidance (PDF)](https://www.hhs.gov/guidance/sites/default/files/hhs-guidance-documents/FDA/59502407dft.pdf); [DLA Piper summary](https://www.dlapiper.com/en-gl/insights/publications/2025/01/fda-releases-draft-guidance-on-use-of-ai)
- [EC Annex 22 consultation](https://health.ec.europa.eu/consultations/stakeholders-consultation-eudralex-volume-4-good-manufacturing-practice-guidelines-chapter-4-annex_en); [ECA](https://www.gmp-compliance.org/guidelines/gmp-guideline/eu-gmp-annex-22-draft-2025-artificial-intelligence); [RAPS](https://www.raps.org/resource/european-commission-proposes-on-updated-gmp-guidel.html)
- Anthropic [pricing](https://platform.claude.com/docs/en/about-claude/pricing), [prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching), [cost optimization](https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence) (all fetched 2026-11-24)
- [Self-Route, EMNLP 2024 Industry](https://aclanthology.org/2024.emnlp-industry.66)
- [AWS Bedrock pricing](https://aws.amazon.com/bedrock/pricing/); [Bedrock batch announcement](https://aws.amazon.com/about-aws/whats-new/2025/08/amazon-bedrock-batch-inference-anthropic-claude-sonnet-4-openai-gpt-oss-models)
- [OpenAI prompt caching docs](https://developers.openai.com/api/docs/guides/prompt-caching.md)
- Not re-verified in this session: Liu et al., "Lost in the Middle", TACL 2024 (DOI 10.1162/tacl_a_00638).
