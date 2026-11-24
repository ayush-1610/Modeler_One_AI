# Clinical PK data curation for PBPK model building and verification (literature review, 2026-11-24)
Research report by a literature agent; not SME-reviewed. Items marked [REG – recalled, verify] or [L] are unverified or the agent's own reasoning.

**For:** Modeler One (PBPK on OSP / PK-Sim). **Type:** research report only; no repository files were changed.
**Sources:** PubMed (search, metadata, PMC full text) and Consensus. Date: 2026-11-24.

## 0. Method, counts and limits

- **Records screened:** about **215 unique titles and abstracts**, from 19 Consensus searches (about 330 records, with duplicates) and about 25 PubMed searches and metadata pulls.
- **Full texts read (PMC):** 5. Irby 2021, Fernandes 2024, Hanke 2018, Dunvald 2022 and Kuepfer 2016.
- **Papers cited below:** **72 peer-reviewed or indexed items**, plus 9 regulatory or standards documents.
- **Limits:**
  1. The Consensus free quota ran out partway through. Some later queries (food-effect designs, mean versus individual data) were done with PubMed only, which gave narrower coverage.
  2. Consensus free-tier records have no DOI. Items without a PMID are cited by journal and year, and marked "(Consensus)".
  3. **fda.gov and ema.europa.eu are blocked in this session's network.** I could not check the exact wording of the FDA, EMA and ICH documents. Statements taken from those documents are marked **[REG – recalled, verify]**. To check them, allow those hosts or read the ICH M13A Step 4 PDF.
- **Certainty labels used:**
  - **[H]** consistent evidence across several papers.
  - **[M]** one good paper, or a simulation study only.
  - **[L]** my own reasoning or field practice, with no direct citation.

---

## Executive summary

1. **BLQ values (below the lower limit of quantification).** Beal's M3 method (a censored likelihood) is the reference method for fitting models. If 5% or fewer of the observations are BLQ, the methods give similar results. Above 5% BLQ, replacing every BLQ with LLOQ/2 (M5) should not be used. Peripheral-compartment parameters and nonlinear clearance are biased from about 5% BLQ unless M3 is used (Irby 2021). For non-compartmental analysis (NCA), standard practice is simple imputation set in the statistical analysis plan (SAP). In the PBPK papers I screened, BLQ handling of observed data is almost never stated. This is a documentation gap Modeler One can close.
2. **Nominal versus actual sampling times.** Use actual times for NCA and for fitting individual data. Use nominal times for mean profiles and summary tables. How much bias nominal times cause depends mainly on the **curvature** of the profile around the sample (Choi 2013). For drugs with a short half-life, errors of 5 minutes already bias the estimates (Alihodzic 2020).
3. **Why a re-computed NCA differs from the sponsor's.** Five settings explain most differences:
   - the AUC integration rule; the linear trapezoid error reaches 15.5% when an interval spans 2 half-lives (Chiou 1978);
   - the terminal-slope (λz) window; the adjusted-R² rule biases λz upward (Noe 2019);
   - the BLQ rules;
   - actual versus nominal times;
   - AUCτ versus AUC to infinity, and the steady-state conventions.
   When settings are identical, validated NCA programs agree to better than 0.0001% (CPhaMAS 2024, PreKinetix 2025). **I found no published tolerance for re-computing a sponsor's NCA.** Section 3 proposes tiers; they are my proposal.
4. **Analysis populations.** The bioequivalence (BE) exclusions are regulatory conventions [REG – recalled, verify]:
   - pre-dose concentration greater than 5% of the subject's Cmax;
   - vomiting at or before 2 × median Tmax for immediate-release products.
   Regulators otherwise refuse post-hoc exclusion of outliers (Fernandes 2024). A PBPK modeller should use the sponsor's PK population with the exclusions recorded as flags, not deleted.
5. **Summary statistics.** Observed data must keep their **statistic type**: arithmetic mean, geometric mean or median, the spread measure, and n per time point. The simulated statistic must be of the same type. OSP practice compares arithmetic mean ± SD with a 68% population interval (Hanke 2018).
6. **Digitised data.** Digitising software is accurate to about 1% (Wojtyniak 2020). The larger risk is errors already in the publication: 85% of 181 published Cmax values differed by more than 5% from the digitised curves.
7. **Verification criteria depend on the context of use.** Common choices:
   - 2-fold for AUC and Cmax;
   - Guest limits for drug–drug interaction (DDI) ratios;
   - 0.8–1.25 for "high confidence" food-effect predictions;
   - a confidence interval of the predicted/observed geometric mean ratio within set bounds (van Borselen 2024);
   - average fold error (AFE) and absolute average fold error (AAFE), or GMFE;
   - visual predictive checks (VPC or prediction-corrected VPC), with BLQ shown;
   - the continuous ranked probability score (CRPS) for distributions.
   EMA judged most PBPK models in the marketing applications it reviewed for 2022–2023 to be **not qualified** (Paul 2025), so the data and verification trail matters.
8. **CDISC standards make automatic import possible.** The relevant standards are SDTM PC and PP, and ADaM ADPC, ADPP, ADNCA and ADPPK. Pharmacometrics teams already build tools on them (PmWebSpec 2024; ADPPK case studies 2026).

---

## 1. BLQ values and missing samples

### 1.1 Beal's M1–M7 methods

| Method | What it does | Evidence (sim = simulation study) | Certainty |
|---|---|---|---|
| M1 | Discard BLQ values | Bias in V2, Q and between-subject variability, sometimes even at low BLQ %. Bergstrand 2009 found substantial bias "even for seemingly small amounts". With ≤5% BLQ in the elimination phase of a 1-compartment model the effect was small (Xu 2011) | H |
| M2 | Discard, then condition the likelihood on values above the LOQ | Better than M1 (Ahn 2008). Reduces false selection of 2-compartment models when BLQ >10% (Irby 2021) | M |
| **M3** | Treat BLQ as censored: likelihood P(y < LLOQ) | Least biased in most simulations (Ahn 2008; Bergstrand 2009; Irby 2021). Runs converge less often (Keizer 2015: successful minimisation under 50%). The objective function is unstable across retries (Wijk 2025: ±14.7) | H |
| M4 | M3, also conditioned on y > 0 | Similar to M3; better when data are truncated-normal (Ahn 2008) | M |
| M5 | Replace every BLQ with LLOQ/2 | Biased from 10% BLQ; **do not use above 5%** (Irby 2021) | H |
| M6 | First BLQ in a run → LLOQ/2, discard the rest | Bias above 20% BLQ (1-compartment); biased for 2-compartment models (Irby 2021; Duval 2002) | H |
| M7 | Replace with 0 (first BLQ) | Biased. Unstable objective function (±130). M7+ (with inflated additive error) comes close to M3 (Wijk 2025) | M |
| Use the measured BLQ values | Lab reports the numbers below the LLOQ | Lowest error in simulation (Keizer 2015). Argued for by Jusko 2012, Senn 2012 and Hecht 2018. Bioanalytical labs rarely release them | M |

**Irby 2021 decision rules** (a review plus new simulations; still simulation-based) [M]:
- 5% BLQ or less: all methods are about equal.
- 1-compartment IV model, rich sampling, BLQ ≤30%: M1 is about as good as M3.
- 2-compartment model, or nonlinear PK: use M3 from 5% BLQ.
- Oral dosing with more than 5% BLQ in the absorption phase: use M3.

**Effect on model choice.** At about 50% BLQ, the M1 method favoured a 2-compartment model in 96% of simulations where the true model had one compartment (Irby 2021, citing earlier work). For PBPK this matters: discarding BLQ values distorts the apparent terminal phase and the distribution parameters.

**BLQ in NCA:**
- Common SAP convention [L, verify in each SAP]:
  - BLQ before the first quantifiable value → 0;
  - BLQ between two quantifiable values → missing;
  - trailing BLQ → excluded.
- SDTM PC stores BLQ as a character result. A 2018 industry paper shows how BLOQ is recorded in SDTM.PC and proposes simple handling rules (Consensus).
- Other methods: kernel-density imputation performed best for AUC in simulation (Barnett 2020). Tobit regression for λz is equivalent to M3 (Denney 2024, conference abstract).

**PBPK practice.** Across the PBPK papers screened, none stated how BLQ observations were treated in observed data or in parameter identification.
- Hanke 2018 does not discuss it.
- Kuepfer 2016, the OSP tutorial (full text checked), gives no guidance on observed data.
- **Risk.** Literature means are often computed from quantifiable values only, which inflates late concentrations. This is my inference [L], consistent with the omission bias in Bergstrand 2009.
- The OSP parameter-identification module has LLOQ handling options. I did not check their names or behaviour, so harvest them from the engine (CLAUDE.md: never invent PK-Sim names).

### 1.2 Missing or erroneous samples, times and doses

Irby 2021 [H] recommends the following.
- Read the bioanalytical report before analysis.
- Check agreement between assays and sites with dose-normalised plots, and use an assay covariate or scaling factor if needed.
- Replace erroneous values with corrected ones, or remove them.
- Check that units are consistent. A switch between kg and lb in only 5% of records gave about 40% error in the covariate effect.
- Dose-time errors cause bias in parameter estimates. Errors in sampling times mainly inflate the residual error (Jaber & Brundage 2023 [M]; Karlsson 1995).

Missing late samples in BE studies, for example the 72-hour sample, are not handled the same way by all regulators. Imputing them conflicts with a model-independent NCA (Fernandes 2024).

---

## 2. Nominal versus actual sampling times

| Use | Time basis | Basis |
|---|---|---|
| Individual NCA (regulatory BE/BA) | **Actual** | [REG – recalled, verify] EMA 2010 BE guideline and ICH M13A. Dunvald 2022 notes that observed times "do not always agree with the planned timepoints" |
| Mean profiles, summary statistics by time point, figures | **Nominal** (planned) | Dunvald 2022 plots means at planned times |
| Tmax | Observed sample time. In practice it is discrete and equal to a nominal time | Willavize 2008. Report the median and range (Dunvald 2022) |
| Fitting individual data (popPK, PBPK parameter identification) | **Actual** | Choi 2013 [M]: bias grows with curvature and the size of the error; dense sampling reduces it. Alihodzic 2020 [M]: ±5 min errors already bias V1 and the residual error for meropenem (half-life about 1 h) |
| Fitting **mean** data (common in PBPK) | Nominal, because means are taken by nominal time point | [L] Check whether actual times are spread widely around Tmax |
| Comparison with the sponsor's NCA | **Whatever the sponsor used.** Read the SAP, or detect it (Section 3) | [L] |

**Sampling windows.** Takahashi 2026 measured how window length changes NCA parameters, using BE criteria as the yardstick. Use their windows as a QC threshold for flagging late or early samples [M].

---

## 3. NCA conventions that cause apparent discrepancies

| Source | Size and direction | Evidence |
|---|---|---|
| Linear trapezoid in the declining phase | Overestimates. Error per interval is about 1% at Δt = 0.5·t½, **15.5% at 2·t½, 57.1% at 4·t½**. It underestimates in the absorption phase | Chiou 1978 [H]. Chiou recommends linear before the peak and log after. Dunvald 2022 calls linear-up/log-down reasonable for first-order drugs |
| Other integration choices (Lagrange, splines) | Up to about 11% difference in etoposide AUC between methods | McCauley 1995 (Consensus); Yu 1995 (Consensus) [M] |
| How the curve shape is assumed during an infusion | The largest source of NCA-versus-model AUC difference in a busulfan study | Hughes 2024 (Consensus) [M] |
| λz window selection | The adjusted-R² rule fails when the terminal phase has more than 3 points, and λz is **positively biased**. Visual inspection did better than both R² rules | Noe 2019 (DOI 10.1002/pst.1979) [M]. The "two times tmax" rule is an alternative for oral drugs (Scheerans 2008) |
| Reporting rules for t½ and AUC to infinity | t½ is reliable when the terminal span is ≥1.5 half-lives with low assay noise, or ≥2.5 with high noise. Adjusted-R² and span rules did not identify reliable estimates | Noe 2019 (DOI 10.1002/pst.1978) [M] |
| How long sampling lasts | Needs ≥2 half-lives for AUC to infinity and ≥4 for t½. Exclude a subject's t½ if it exceeds half the sampling interval | Colucci 2011 [M] |
| Extrapolated % of AUC | AUC to infinity is unreliable if more than 20% is extrapolated | Dunvald 2022. EMA requires AUC(0–t) ≥80% of AUC to infinity [REG – recalled, verify] |
| AUC measure used | AUC to a common time is better for dose proportionality when t½ is uncertain | Brocks 2024 (Consensus) [M] |
| Steady state | AUCτ and Cmax,ss over the dosing interval (multiple-dose BE) | Fernandes 2024 [H] |
| Tmax | Discrete and set by the design. Observation-based Cmax and Tmax are biased compared with the true peak | Willavize 2008; Han 2018 (Consensus) [M] |
| Software differences, same settings | Below 0.0001% (CPhaMAS vs WinNonlin; PreKinetix vs Phoenix). The NonCompart, ncar and PKNCA R packages are checked against WinNonlin | Kuang 2024 (Consensus); PreKinetix 2025 (Consensus); Kim 2018; Dunvald 2022 [H] |

**Tolerance when re-computing a sponsor's NCA: none published.** The only related benchmarks are below 0.0001% between programs with identical settings, and Heatherington 1998's criterion of under 1% difference as "agreement" between modelling programs. **Proposed tiers [L]; they need SME approval before use:**

| Tier | Relative difference | Meaning |
|---|---|---|
| Pass | ≤1% (allows for concentrations rounded to 3 significant figures) | Same settings reproduced |
| Investigate | 1–5% | A setting differs (integration rule, time basis, BLQ rule, λz window) |
| Fail | >5% and not explained by any variant tried | A data difference (exclusions, sample re-assays, units). Escalate |

---

## 4. Analysis populations and exclusions

| Rule | Source | Use in PBPK |
|---|---|---|
| Pre-dose concentration >5% of Cmax → exclude the subject. Lower values may be kept without adjustment | [REG – recalled, verify] EMA 2010; FDA BE draft guidance; ICH M13A. A sample trial protocol (NCT03437447) applies the 5% rule. Re-assay is allowed only for pre-dose samples suspected of carry-over (Fernandes 2024) | Flag the profile. For crossover periods, carry-over contaminates the observed period |
| Vomiting at or before 2 × median Tmax (immediate-release) → exclude | [REG – recalled, verify] EMA 2010; FDA. **Not confirmed in this session.** The same sample protocol used a different rule (after 6 h), so **sponsor protocols differ: read the SAP** | Exclude from absorption fitting, because PBPK assumes the full dose was absorbed |
| Excluding outliers on statistical or PK grounds | Not accepted by most regulators. Canada allows a statistical test (studentised residual >3) with conditions. A sensitivity analysis is encouraged | Fernandes 2024 [H]. The ICH M13A forum discussed how to handle aberrant profiles (Blume 2024) |
| Protocol deviations (dose, fasting state, concomitant medication) | Defined in each SAP | Flag. Exclude if the deviation changes the simulated scenario |
| Flag-based exclusion in ADaM | ADPPK uses the variables FLGREAS and EXCLF | Hegde 2026 (Consensus). Keeps records and gives an audit trail |

**Which population a PBPK modeller should use [L]:**
- Use the sponsor's **PK analysis set**: all subjects with an evaluable profile.
- Carry every exclusion as a flag with its reason (EXCLF/FLGREAS-style), never as a deletion. This fits Part 11 and the audit chain.
- Apply exclusions that make the simulated scenario wrong, such as vomiting, a wrong dose or wrong fed state.
- Do **not** drop subjects only because they are outliers; let the population variability cover them.
- When comparing with the sponsor's NCA tables, use exactly the sponsor's population.

---

## 5. Mean versus individual data, arithmetic versus geometric means, digitised data

| Topic | Finding | Source |
|---|---|---|
| How OSP compares with observed data | Observed values are "most often reported in terms of arithmetic means and SDs". They are compared with the simulated arithmetic mean and the 68% interval (±1 SD). Virtual population of 100 subjects. Separate training and test studies. GMFE per study | Hanke 2018 [H] |
| Geometric vs arithmetic mean | AUC and CL are skewed; the geometric mean is the better central value | Midha 1989; Dunvald 2022 (geometric mean ratio, median for Tmax, no SEM) [H] |
| Matching statistics [L] | A simulated arithmetic mean must be compared with an observed arithmetic mean, and geometric with geometric. A geometric mean approximates the median of the virtual population. Cmax read from a mean curve is lower than the mean of individual Cmax values | Standard PK principle; no specific citation found |
| Individual vs aggregate data | A confidence interval of the predicted/observed geometric mean ratio can be built from either individual or aggregate data. Individual data need fewer subjects | van Borselen 2024 [M] |
| Variability between studies | One clinical study is a noisy "truth". A 2-fold criterion can be unreasonable for small studies. Tie the criterion to n and variance | Abduljalil 2014 [H] |
| Digitising accuracy | Scaled median symmetric accuracy about **0.99%**, with no relevant confounders. **85% of 181 published Cmax values differed by more than 5%** from the digitised curves (errors in the publications) | Wojtyniak 2020 [H] |
| Reliability of WebPlotDigitizer | Intraclass correlation >0.95. Difference from true values 0.23–30.35% for a continuous outcome. Software extraction was faster and agreed better than manual reading | Burda 2017; Drevon 2016 (Consensus); Jelicic Kadic 2016 (Consensus) [H] |
| AUC computed from digitised means | Standard trapezoid underestimates AUC; a Monte Carlo method was almost unbiased | Titensor 2025 (Consensus) [M] |
| AI or LLM digitising | About 70% faster than WebPlotDigitizer, with 92% accuracy auto-filling study context (Delineate, conference abstract). The best of 16 models reached 87.5% at ±5% tolerance on real figures (PlotGround, arXiv). PlotPick withdrew an earlier performance claim. **Human verification is still needed** | Consensus [L–M] |
| Curated PK databases | PK-DB records experimental error, normalises units, annotates to ontologies, computes PK parameters from time courses, uses validation rules, and has a REST API | Grzegorzewski 2021 [H] |

---

## 6. Verification criteria by context of use

| Context of use | Typical criterion | Source |
|---|---|---|
| Fitting and checking single-drug profiles | Predicted/observed AUC and Cmax within 2-fold. Report GMFE/AAFE (AAFE = 10^mean\|log10(pred/obs)\|) and AFE (signed bias) | Hanke 2018 (93% of AUC ratios and 94% of Cmax ratios within 2-fold); Sheiner & Beal 1981 (use bias and precision, not correlation) [H] |
| DDI ratios | Guest limits narrow as the observed ratio approaches 1. Use a variability term δ. Applying them cut prediction "success" by 21% compared with 2-fold | Guest 2011 [H]. Used in OSP work (Hanke 2018) |
| Platform qualification | Simcyp (EMA qualification): AFE about 1, AAFE 1.23–1.25, 98.8% of 246 predictions within 2-fold. PK-Sim CYP3A4: GMFE 1.4 over 135 observations | Rowland Yeo 2026; Frechen 2021 [H] |
| Food effect | High confidence = within 0.8–1.25. Moderate = 0.5–2. Out of 30 compounds: 15 high, 8 moderate, 7 low | Riedmaier 2020 [H]; PBBM for fed-BE waivers (Kollipara 2024; Mackie 2024) |
| BE or virtual BE, model-informed dosing | 90% CI of the geometric mean ratio within 0.80–1.25, or a confidence interval of the predicted/observed ratio within set bounds | van Borselen 2024 [M] |
| Population distribution | VPC or prediction-corrected VPC; VPCs that show the BLQ fraction; CRPS with a skill score | Bergstrand 2011; Bergstrand 2009; Sluijterman 2026 [M] |
| Regulatory credibility | Risk-informed credibility framework, ICH M15. EMA found most PBPK models in 2022–2023 applications not qualified | Kuemmel 2020; Shebley 2018; Paul 2025 [H] |

*Note.* CLAUDE.md treats acceptance criteria as SME-governed. The thresholds above are literature defaults for SME review, not approved rules.

---

## 7. Multiple-dose, food-effect, crossover and parallel designs: what to extract

| Design | Extract | Why it matters for PBPK |
|---|---|---|
| Multiple dose / steady state | The full dosing history with actual dose times; AUCτ, Cmax,ss, Ctrough series; accumulation ratio; evidence of steady state (for example a trough-ratio CI) | Identifies auto-induction or auto-inhibition. Hanke 2018 fitted auto-induction using multiple-dose perpetrator studies only. Effective t½ from the accumulation ratio checks time dependence (Momper 2025; Chen 2017). A model can simulate steady state from single-dose data (GBHI, Schug 2025) |
| Food effect | Meal composition and calories, how long after the meal the dose was given, fasting duration, water volume, formulation; fed/fasted geometric mean ratio with 90% CI; Tmax shift | A high-fat, high-calorie meal is the default (Fernandes 2024). FDA product-specific guidances ask for fasting **and** fed BE in 86.5% of cases; EMA in 15.9% (Kotsybar 2023). [REG – recalled, verify]: FDA 2022 food-effect guidance on meal timing and calories |
| Crossover | Periods, sequences, washout, pre-dose values per period; **within-subject** ratios | The ratios PBPK predicts for DDI and food effect. Check for carry-over (Section 4) |
| Parallel | Each arm separately, with n and statistic type | Variability between subjects is mixed into the ratio, so CIs are wider. Used for long t½ and antibodies (Chioato 2013) |
| Pooling across studies | Study and assay identifiers, LLOQ per assay | Assay and study effects (van Wijk 2023 individual patient data meta-analysis; Irby 2021) |

---

## 8. Data standards for automatic import

Sources: Wood 2012 (Consensus); Magielse 2014 (Consensus); Dombrowsky 2026 (Consensus); Hegde 2026 (Consensus); Chen 2024 (PmWebSpec); Kim 2018 (NonCompart and ncar, CDISC-compatible).

| Standard | Content | Import use |
|---|---|---|
| **SDTM PC** (one record per subject per sample) | Analyte, matrix, original and standardised result, units, status and reason not done, **LLOQ**, collection datetime, planned time point and planned elapsed time, time-point reference | Gives actual and nominal time together, BLQ status and LLOQ. Exact variable names (PCTESTCD, PCORRES, PCSTRESN, PCLLOQ, PCDTC, PCTPT, PCELTM, PCTPTREF, PCSTAT): **verify against the current SDTMIG**; I recalled them |
| **SDTM PP** (one record per subject per parameter) | Sponsor NCA parameters under CDISC controlled terminology (for example CMAX, TMAX, AUCLST, AUCIFO, AUCTAU, LAMZ, LAMZHL, R2ADJ; **verify the CT version**) | The comparison target for re-computation |
| **SDTM EX/EC, DM, AE, VS/LB** | Doses with times, demographics, vomiting events, covariates | Exposure, covariates, emesis flags |
| **ADaM ADPC/ADPP and ADNCA** | Analysis-ready concentrations with actual and nominal relative times, plus analysis flags | Directly matches NCA re-computation |
| **ADaM ADPPK** (popPK implementation guide) | PARAM/PARAMCD, AVAL/AVALC, AFRLT, FLGREAS, EXCLF | Pooled modelling dataset with exclusions kept as flags (Hegde 2026). Dose-record checks (ADDL/II): Sukumar 2024 (Consensus) |

---

## 9. Product ideas for automatic ingestion and checking

Ranked by value against effort. All are **proposals [L]**, each tied to the evidence above.

| # | Feature | What it does | Evidence |
|---|---|---|---|
| 1 | **CDISC importer** (SDTM PC/PP/EX/DM/AE and ADaM ADPC/ADNCA/ADPPK; XPT plus Define-XML) | Maps into the CPF observed-data records. Keeps raw values, LLOQ, BLQ status, nominal **and** actual relative times, analyte, matrix and units. Hashes files into the audit chain | §8; Chen 2024 |
| 2 | **NCA re-computation with method detection** | Runs NCA with each combination of {linear, linear-up/log-down, linear-log} × {actual, nominal times} × {BLQ rule sets} × {λz windows ≥3 points}. Picks the combination that reproduces the sponsor's PP values, then reports the settings found and the size of any remaining difference against the Section 3 tiers | Chiou 1978; Noe 2019; Kuang 2024 |
| 3 | **Exclusion detector** that flags, never deletes | Pre-dose >5% Cmax; emesis at or before 2 × median Tmax (from AE data, with the threshold read from the SAP); samples outside the protocol window; dose or fasting deviations; t½ longer than half the sampling span; extrapolated AUC >20%. Writes EXCLF/FLGREAS-style flags with reasons | §4; Colucci 2011; Takahashi 2026 |
| 4 | **BLQ profiler and rule suggestion** | Computes BLQ % overall, before Cmax, in the terminal phase and embedded. Suggests M1/M3/M6 using Irby's decision tree. Warns when literature means were computed from quantifiable values only. BLQ-aware VPC | Irby 2021; Bergstrand 2009 |
| 5 | **Time QC** | Statistics of actual-minus-nominal time; curvature-weighted warning near Tmax and fast phases; detects 24-hour wrap, time-zone and date errors; dose-time sanity checks | Choi 2013; Alihodzic 2020; Irby 2021 |
| 6 | **Observed data that know their statistic** | Required fields: statistic type (arithmetic/geometric mean, median), spread type (SD, geometric SD, CV, SEM with n → SD), n per time point, time basis. Simulation output is summarised the same way | Hanke 2018; Midha 1989; Dunvald 2022 |
| 7 | **Unit, analyte and matrix normaliser** | Mass↔molar conversion using the molecular weight from the CPF; parent vs metabolite; plasma, blood or serum with B:P ratio; detects kg/lb and ng/µg mix-ups | PK-DB; Irby 2021 |
| 8 | **Digitising with dual extraction and cross-checks** | Two independent extractions; computes NCA on the digitised mean and compares it with the reported Cmax/AUC. A difference >5% is a known common error. Monte Carlo AUC from digitised means | Wojtyniak 2020; Titensor 2025 |
| 9 | **Protocol and SAP extractor** (LLM-assisted, human-confirmed) | Design (crossover or parallel, periods, washout), meal, fasting, dose regimen, BLQ and exclusion rules → simulation protocol in the CPF plus NCA settings | Delineate (Consensus); PKPDAI NER, F1 90.4% (Gonzalez Hernandez 2024) |
| 10 | **Verification dashboard by context of use** | Fold error, Guest limits, AFE/AAFE/GMFE, confidence interval of the geometric mean ratio, pcVPC, CRPS, with variability between studies shown. Criteria come from the SME-governed ruleset and are marked UNVERIFIED | §6; Abduljalil 2014 |
| 11 | **Steady-state checker** | Trough plateau test, accumulation ratio vs single-dose prediction, effective t½. Flags time-dependent PK before model building | Momper 2025; Hanke 2018 |
| 12 | **Delivery diff** | When a sponsor sends a revised delivery, shows changed or re-assayed samples and changed flags, with a Part 11 reason-for-change prompt | Fernandes 2024 (re-assay rules) |

**Scientific guardrail [L].** NCA re-computation runs independently of PK-Sim and checks the *data*. Under CLAUDE.md, a result counts as a PBPK result only when it was simulated on real PK-Sim.

---

## 10. Gaps and uncertainties

- No published tolerance exists for re-computing a sponsor's NCA. The tiers in Section 3 are a proposal.
- PBPK papers almost never state how BLQ values in observed data were handled. I found no study on the effect of BLQ-truncated literature means.
- The regulatory provisions marked [REG – recalled, verify] could not be fetched. Check them in the ICH M13A Step 4 PDF, the EMA 2010 BE guideline, the FDA BE draft guidance and the FDA 2022 food-effect guidance.
- The exact SDTM and ADaM variable names and CDISC controlled-terminology codes were recalled, not retrieved. Check them against the current implementation guides.
- I could not disambiguate some PMIDs: Noe 2019, Jelicic Kadic 2016 and CPhaMAS. They are cited by DOI or journal only.

---

## References

**Peer-reviewed and indexed (PMID; DOI where retrieved)**

1. Beal SL 2001, J Pharmacokinet Pharmacodyn. PMID 11768292; doi:10.1023/A:1012299115260
2. Ahn JE et al. 2008, J Pharmacokinet Pharmacodyn. PMID 18686017; doi:10.1007/s10928-008-9094-4
3. Bergstrand M, Karlsson MO 2009, AAPS J. PMID 19452283
4. Keizer RJ et al. 2015, Pharmacol Res Perspect. PMID 26038706
5. Xu XS et al. 2011, J Pharmacokinet Pharmacodyn. PMID 21626437; doi:10.1007/s10928-011-9201-9
6. Irby DJ et al. 2021, CPT PSP. PMID 33715307; doi:10.1002/psp4.12611 (full text read)
7. Wijk M et al. 2025, CPT PSP. PMID 40067154; doi:10.1002/psp4.70015
8. Senn S et al. 2012, Stat Med. PMID 22825800
9. Hecht M et al. 2018, Bioanalysis. PMID 30033744
10. Jusko WJ 2012, Pharm Res. PMID 22729370
11. Duval V, Karlsson MO 2002, Pharm Res. PMID 12523662
12. Cheng Y, Li Y 2025, J Pharm Sci. PMID 40706799; doi:10.1016/j.xphs.2025.103916
13. Barnett H et al. 2020, Stat Biopharm Res (Consensus; no PMID)
14. Denney WS 2024, Tobit half-life (conference abstract; Consensus)
15. "Methods for Handling Concentration Values Below the LOQ in PK Studies" 2018 (industry paper; Consensus)
16. Choi L et al. 2013, Eur J Clin Pharmacol. PMID 23975237; doi:10.1007/s00228-013-1576-7
17. Karlsson MO, Beal SL, Sheiner LB 1995, J Pharmacokinet Biopharm. PMID 8733951; doi:10.1007/BF02353466
18. Jaber MM, Brundage RC 2023, J Pharmacokinet Pharmacodyn. PMID 36617366; doi:10.1007/s10928-022-09837-5
19. Alihodzic D et al. 2020, Front Pharmacol. PMID 32194411
20. Takahashi K et al. 2026, Clin Pharmacol Drug Dev. PMID 41545906
21. Dunvald AD et al. 2022, Clin Transl Sci. PMID 35570335; doi:10.1111/cts.13305 (full text read)
22. Willavize SA, Morgenthien EA 2008, Pharm Stat. PMID 17256803
23. Chiou WL 1978, J Pharmacokinet Biopharm. PMID 731416
24. Noe DA 2019, Pharm Stat, adjusted-R² algorithm. doi:10.1002/pst.1979
25. Noe DA 2019, Pharm Stat, reporting criteria for t½ and AUC to infinity. doi:10.1002/pst.1978
26. Noe DA 2020, Clin Pharmacol Drug Dev, NCA estimation and reporting. PMID 32706165
27. Colucci P et al. 2011, J Pharm Pharm Sci. PMID 21733410
28. Scheerans C et al. 2008, Biopharm Drug Dispos. PMID 18098336
29. Kim H et al. 2018, Transl Clin Pharmacol, NonCompart/ncar. PMIDs 32055542 / 32055564 (article and erratum, not disambiguated)
30. Acharya C et al. 2016, Comput Methods Programs Biomed, ncappc. PMID 27000291
31. Kuang Y et al. 2024, Comput Methods Programs Biomed, CPhaMAS (Consensus)
32. PreKinetix 2025, Pharmacy & Pharmacology (Consensus)
33. Heatherington AC et al. 1998, J Pharm Sci (Consensus)
34. Hughes JH et al. 2024, J Pharmacokinet Pharmacodyn, MAP vs NCA (Consensus)
35. Brocks DR et al. 2024, J Pharm Pharmacol (Consensus)
36. Han YR et al. 2018, Drug Metab Dispos (Consensus)
37. McCauley DL et al. 1995, Cancer Chemother Pharmacol (Consensus)
38. Yu Z et al. 1995, Biopharm Drug Dispos (Consensus)
39. Fernandes EAF et al. 2024, J Pharm Pharm Sci. PMID 38577255; doi:10.3389/jpps.2024.12398 (full text read)
40. Kotsybar J et al. 2023, Clin Transl Sci. PMID 37904315; doi:10.1111/cts.13670
41. Blume H et al. 2024, Eur J Pharm Sci. PMID 38452875; doi:10.1016/j.ejps.2024.106741
42. Verbeeck RK, Musuamba FT 2012, J Pharm Pharm Sci. PMID 23148877
43. Schug BS et al. 2025, Eur J Pharm Sci, GBHI 6th conference (Consensus)
44. Wojtyniak JG et al. 2020, CPT PSP. PMID 32543786
45. Burda BU et al. 2017, Res Synth Methods. PMID 28268241
46. Drevon DD et al. 2016, Behav Modif (Consensus)
47. Jeličić Kadić A et al. 2016, J Clin Epidemiol (Consensus)
48. Titensor S et al. 2025, BMC Med Res Methodol (Consensus)
49. Nieves E et al. 2024, Delineate (conference abstract; Consensus)
50. Zhang Y et al. 2026 PlotGround, and Carstensen T 2026 PlotPick (arXiv preprints; Consensus)
51. Hanke N et al. 2018, CPT PSP. PMID 30091221; doi:10.1002/psp4.12343 (full text read)
52. Frechen S et al. 2021, CPT PSP. PMID 33946131
53. Rowland Yeo K et al. 2026, Clin Pharmacol Ther. PMID 42934176
54. Guest EJ et al. 2011, Drug Metab Dispos. PMID 21036951; doi:10.1124/dmd.110.036103
55. Abduljalil K et al. 2014, Drug Metab Dispos. PMID 24989891; doi:10.1124/dmd.114.058099
56. Sheiner LB, Beal SL 1981, J Pharmacokinet Biopharm. PMID 7310648; doi:10.1007/BF01060893
57. Shebley M et al. 2018, Clin Pharmacol Ther. PMID 29315504; doi:10.1002/cpt.1013
58. Kuemmel C et al. 2020, CPT PSP. PMID 31652029; doi:10.1002/psp4.12479
59. van Borselen MD et al. 2024, Clin Pharmacokinet. PMID 38361163
60. Sluijterman L et al. 2026, CPT PSP. PMID 41550071
61. Paul P et al. 2025, Clin Pharmacol Ther. PMID 39748538
62. Bergstrand M et al. 2011, AAPS J, pcVPC. PMID 21302010; doi:10.1208/s12248-011-9255-z
63. Riedmaier AE et al. 2020, AAPS J. PMID 32981010; doi:10.1208/s12248-020-00508-2
64. Kollipara S et al. 2024, J Pharm Sci. PMID 38043684; doi:10.1016/j.xphs.2023.11.030
65. Mackie C et al. 2024, Mol Pharm. PMID 38600804; doi:10.1021/acs.molpharmaceut.4c00202
66. Midha KK et al. 1989, J Clin Psychopharmacol. PMID 2723140; doi:10.1097/00004714-198904000-00005
67. Momper JD et al. 2025, Ther Drug Monit. PMID 39446891; doi:10.1097/FTD.0000000000001270
68. Chen R et al. 2017, Int J Clin Pharmacol Ther. PMID 27936523
69. Chioato A et al. 2013, Clin Drug Investig. PMID 24030571
70. Grzegorzewski J et al. 2021, Nucleic Acids Res, PK-DB. PMID 33151297; doi:10.1093/nar/gkaa990
71. Gonzalez Hernandez F et al. 2024, Sci Rep, PK NER. PMID 39379460; doi:10.1038/s41598-024-73338-3. Also the 2021 Wellcome Open Res paper: PMID 34381873; doi:10.12688/wellcomeopenres.16718.1
72. Chen L et al. 2024, AAPS J, PmWebSpec. PMID 38570385
73. van Wijk RC et al. 2023, CPT PSP, IPDMA tutorial. PMID 37303132
74. Kuepfer L et al. 2016, CPT PSP. PMID 27653238; doi:10.1002/psp4.12134 (full text checked: no guidance on observed data)
75. Consensus-only, CDISC and pharmacometrics practice: Hegde 2026 (ADPPK case study); Dombrowsky 2026; Wood 2012 (SDTM PK submission); Magielse 2014 (ADaM in PK); Sukumar 2024 (ADDL/II macro); ter Heine 2026 (NCA Assistant: λz override, audit trails)

**Regulatory and standards documents (not peer-reviewed; wording not checked in-session)**

- ICH M13A, BE for IR solid oral dosage forms (Step 4, July 2024; replaces parts of the EMA BE guideline from 25 Jan 2025)
- EMA Guideline on the Investigation of Bioequivalence, CPMP/EWP/QWP/1401/98 Rev.1/Corr** (2010)
- FDA, Bioequivalence Studies with PK Endpoints for ANDAs (draft)
- FDA, Assessing the Effects of Food on Drugs (2022)
- FDA, PBPK Analyses — Format and Content (2018)
- EMA, Guideline on reporting of PBPK modelling and simulation (2018)
- ICH M15, MIDD general principles
- CDISC SDTMIG (PC/PP), ADaM ADNCA, ADaM popPK implementation guide (ADPPK)

**Web sources from the one web search** (the documents themselves could not be fetched):
- [PMDA M13A PDF 1](https://www.pmda.go.jp/files/000269966.pdf)
- [PMDA M13A PDF 2](https://www.pmda.go.jp/files/000251087.pdf)
- [FDA M13A](https://fda.gov/media/165049/download)
- [ICH M13A Step 4 copy (JFDA)](https://jfda.jo/ebv4.0/root_storage/ar/eb_list_page/ich_m13a_step4_final_guideline_2024_0723-0-0.pdf)
- [EMA M13A page](https://www.ema.europa.eu/en/ich-guideline-m13a-bioequivalence-immediate-release-solid-oral-dosage-forms-scientific-guideline)
- [Sample BE protocol NCT03437447](https://cdn.clinicaltrials.gov/large-docs/47/NCT03437447/Prot_000.pdf)
- [Sample BE SAP NCT03437447](https://cdn.clinicaltrials.gov/large-docs/47/NCT03437447/SAP_001.pdf)

**Access note:** to check the regulatory wording directly, fda.gov and www.ema.europa.eu must be allowed in this session's network settings.
