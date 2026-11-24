# What data a regulatory PBPK submission needs, by context of use (literature review, 2026-11-24)
Research report by a literature agent; not SME-reviewed. Statements marked (memory, verify) or [REG – recalled, verify] are unverified.

## 0. Scope, method, counts

- **Search tools:** Consensus (7 searches, 260 records) and PubMed (about 35 targeted searches, about 50 records, overlapping with Consensus). **About 290 records were screened** on title and abstract. **9 were read in full text**: Paul 2025, Chenel 2026, Shebley 2018, Riedmaier 2020, Kuemmel 2020, Johnson 2021, Heimbach 2024, plus Pepin 2024 and Li 2025 in part. **About 50 are cited below.**
- **Guidances.** I did not re-read the guidance texts in this session (no web fetch). Guidance content is stated only where a cited paper quotes or paraphrases it. Anything from my own memory is marked *(memory, verify)*. I give no clause numbers.
- **No other repository file was edited** (this report is the one file it wrote). I read the acceptance ruleset, `m15.py` and the 2026-11-21 data-intake plan only to make the product ideas fit. Two things in the locked ruleset look wrong (§9).

**Status codes in the tables**
- **R**: required for this CoU.
- **U**: usually needed. Becomes R when model influence is high, i.e. the model replaces a study or drives the label.
- **C**: conditional. Required when the trigger in the "Why" column applies to the compound.
- **O**: optional or supportive.
- **N**: not relevant to this CoU.

**Key design finding:** whether an item counts as "missing" depends on three things: (a) the CoU, (b) the compound's properties (weak base, fm, renal fraction excreted, transporter substrate, BCS class), and (c) model influence and risk. The CoU alone is not enough. Two examples:
- Fed-state data is **not automatically irrelevant** for pediatric extrapolation. Johnson 2021 lists "consider differences in pediatric food effect due to meal size, composition, and frequency". Statelova 2020 found that adult-to-infant extrapolation of paracetamol suspension depended strongly on the adult dosing conditions (fasted and infant-formula data worked; the reference-meal data did not).
- So "fed PK = N" for pediatrics is right only when the drug has no food effect and children are dosed fasted. It is C for infants fed milk or formula, for food vehicles such as apple sauce, and for drugs with a food effect in adults.

## 1. Main findings

1. **Regulators reject most models for missing or unsuitable data, not for software problems.** EMA reviewed full marketing authorisation applications (MAAs) approved in 2022–23 (Paul 2025):
   - 25 of 95 contained PBPK, with 65 proposed uses. Models were qualified for **28%** of uses and accepted as "supportive" for another 9%.
   - Reasons for non-qualification: lack of relevant data to assess predictive performance (15), concerns about model structure (14), unjustified key assumptions or inputs (12), poor prediction of clinical data (11), too few compounds in the qualification dataset (7), unclear (7).
2. **DDI dominates the use of PBPK and is the best-supported CoU.** It is 69% of EMA uses (Paul 2025) and 81.9% of FDA uses 2020–24 (Li 2025, secondary analysis).
   - FDA OCP analyses used a pre-specified **1.25-fold** limit on the predicted/observed ratio of DDI ratios. For CYP inhibitors 81% (AUC ratio) and 77% (Cmax ratio) of cases fell within it and all were within 2-fold (Wagner 2015). For CYP3A inducers the figures were 77% and 83% (Wagner 2016).
   - Transporter DDI, induction, gut CYP3A and non-CYP3A pathways are still treated as less established. At EMA, 1 of 13 transporter-perpetrator uses was qualified.
3. **Required evidence scales with model risk = model influence × consequence of a wrong decision.** This is the ASME V&V40 approach applied to PBPK (Kuemmel 2020), the EMA high/moderate/low impact scheme (EMA 2018 guideline via Paul 2025), and ICH M15's assessment table (Chenel 2026).
   - The data tables should therefore carry R/U/O/N **per risk tier**, not one fixed list per CoU.

## 2. Core drug-model items (default for every CoU; the CoU tables override)

| Item | Default | Why | Source |
|---|---|---|---|
| MW, logP/logD, pKa(s), compound class | R | Ionisation, distribution (Kp) and pH-dependent absorption | Chenel 2026; Shebley 2018 (Table 1) |
| fu,p (plasma unbound fraction) | R | Unbound clearance and IVIVE; tissue distribution | Chenel 2026 |
| B/P (blood-to-plasma ratio) | R | Blood clearance; relating blood and plasma assays | Chenel 2026 |
| In vitro CLint (hepatocytes, HLM, rCYP); Km/Vmax | R if metabolised | IVIVE of clearance | Chenel 2026 |
| Mass balance (radiolabelled), metabolite profile, fraction excreted unchanged in urine | U (R for DDI victim, organ impairment, pediatrics) | Splits clearance across routes; non-radiolabel methods risk missing metabolites | Chenel 2026; Johnson 2021 |
| IV PK (or IV microtracer) | U | "Gold standard" for disposition; without it Fg/Fh are not identifiable for poorly soluble drugs. Alternatives: oral solution, SAD/MAD, mass balance, DDI studies, PopPK | Heimbach 2024; Shebley 2018 (Table 5) |
| Fasted oral PK (SAD/MAD), full concentration–time profiles | R | Training and verification of the base model; dose linearity | Chenel 2026; Shebley 2018 |
| Study metadata: population, dose and regimen, formulation, fed/fasted and meal, matrix, analyte (total/free, parent/metabolite), LLOQ | R | Observed data cannot be simulated faithfully without it | Chenel 2026 §2.2.4 |
| Independent (external) verification dataset | U (R at high influence) | Internal-only validation "carries evidentiary limitations" | Chenel 2026; Shebley 2018 (high-impact criterion 5) |
| Sensitivity and uncertainty analysis of uncertain inputs | R | EMA objections in 5 cases were withdrawn once sensitivity analyses were supplied | Shebley 2018; Kuemmel 2020 |
| Platform/version and its qualification for the intended use | R at high impact | EMA expects platform qualification. For PK-Sim, see the OSP qualification framework (CYP3A4 DDI: GMFE 1.4 over 135 observations) | EMA guideline via Paul 2025; Frechen 2021 |

## 3. Data items per context of use

### 3.1 DDI: drug as victim (CYP/UGT)

| Item | Status | Why | Source |
|---|---|---|---|
| fm per enzyme from reaction phenotyping (rCYP; HLM with selective inhibitors) | R | Drives the victim DDI magnitude. EMA did not qualify models whose fm derivation was unjustified | Shebley 2018 (criterion 2); Paul 2025; Chenel 2026 |
| Clinical DDI with a strong index inhibitor and/or inducer | U; R when extrapolating to untested moderate/weak perpetrators for the label | Refines fm in vivo; standard validation comparator | Kuemmel 2020 (CoU 1); Chenel 2026 (Box 1); Umehara 2019; Li 2025* |
| Mass balance | R | fm versus renal/biliary fraction | Chenel 2026; Shebley 2018 |
| IV PK | U | Separates Fg from Fh | Shebley 2018 (Table 5) |
| Gut-wall metabolism parameters | C (CYP3A substrates) | EMA cited missing intestinal enzyme activity as a structural flaw | Paul 2025 |
| Auto-inhibition / auto-induction (kinact/KI, EC50/Emax on own pathway) | C (drug modulates own clearance) | Cited structural flaw | Paul 2025 |
| Verified perpetrator (index) models | R | The default rifampicin model under-predicted induction; verifying the inducer model was "crucial" | Wagner 2016; Frechen 2021 |
| Pathway qualification set (number of substrates/perpetrators) | R at high impact | EMA guideline: "for example, eight to ten compounds" (written for CYP3A4; EMA now acknowledges this is hard for other enzymes) | Paul 2025 |
| Genotype groups (PM/IM/EM) | C (CYP2D6/2C9/2C19 substrates) | Drug–gene and drug–drug interaction scenarios (eliglustat label case) | Shebley 2018 |
| Active or inhibitory metabolites | C | Omitting a metabolite's contribution was a cited limitation | Li 2025*; Templeton 2016 (Consensus) |
| Fed PK, dissolution, PSD | N (C if the label scenario is fed dosing) | "Food effect on DDI" is a separate CoU at EMA | Paul 2025 |
| Ontogeny | N (unless pediatric DDI) | — | Johnson 2021 |

### 3.2 DDI: drug as perpetrator (inhibition, TDI, induction)

| Item | Status | Why | Source |
|---|---|---|---|
| Reversible Ki (unbound, fu,inc-corrected) and mechanism of inhibition | R if inhibitor | Interaction strength | Chenel 2026; Shebley 2018 |
| kinact/KI with pre-incubation conditions documented | R if TDI | Assay conditions change the derived constants | Chenel 2026 |
| Induction EC50/Emax and the calibration approach | R if inducer | An FDA review reportedly rejected an in vitro rifampicin-calibration approach | Hariparsad 2022; Li 2025* |
| Exposure at the interaction site: fu, B/P, hepatic uptake, gut concentration (dose, solubility) | R | EMA rejected an intestinal CYP3A prediction (lenvatinib) | Shebley 2018 |
| Clinical PK at the therapeutic regimen (steady state) | R | Perpetrator exposure drives the effect | Chenel 2026 |
| Clinical DDI with a sensitive index substrate (e.g. midazolam) | U; R for induction or mixed perpetrators and for label extrapolation | Verifying with a non-sensitive substrate was judged "circular" (inavolisib/palbociclib) | Li 2025*; Shebley 2018 (crizotinib) |
| Verified victim (index substrate) models | R | Needed for qualification | Frechen 2021 |
| Sensitivity analysis over Ki/KI/EC50/Emax ranges | R | Choosing the range is "key" (Shebley). In one FDA review a 10-fold Ki change took the predicted DDI from >2-fold to >5-fold, so a clinical study was required | Shebley 2018 (Table 5); Taskar 2025 (Consensus); Li 2025* |
| Inhibitory metabolites; net inhibition + induction | C | Cited omissions | Li 2025*; Hariparsad 2022 |
| fm of the perpetrator's own clearance | N (U if the same model is also used as a victim) | — | — |
| Fed PK, dissolution | N | — | — |

### 3.3 Transporter-mediated DDI

| Item | Status | Why | Source |
|---|---|---|---|
| Km/Vmax or CLint,active; Ki/IC50 with test system and substrate stated | R | IVIVE of transporter kinetics | Chenel 2026; Taskar 2020 |
| Transporter abundance and empirical scaling factors | R | In vitro data tend to under-predict; scaling factors are used | Taskar 2021; Vijaywargi 2023 |
| Transporter vs enzyme contribution (extended clearance) | R | Hard to determine; a recognised gap | Shebley 2018 (Table 5); Storelli 2023 |
| Clinical DDI with a probe inhibitor | R at high impact | EMA qualified 1/13 perpetrator uses. An FDA review found under-prediction (probenecid: observed AUC GMR 2.0, predicted 1.04) | Paul 2025; Li 2025* |
| Endogenous biomarker data | O/U | Proposed to raise confidence; the specific biomarker choice is my suggestion *(verify)* | Vijaywargi 2023; Rodrigues 2025 |
| Renal clearance, fraction excreted unchanged, GFR·fu vs CLr (evidence of secretion) | C (renal transporters) | Separates filtration from secretion | Johnson 2021; Hsueh 2018 |
| Intestinal efflux (P-gp/BCRP) in absorption | C | Absorption-phase mechanisms missing were cited as a deficiency | Li 2025* |
| Transporter genotype (e.g. SLCO1B1) | C | Drug–gene interactions | Prieto Garcia 2022 |

### 3.4 Food effect

| Item | Status | Why | Source |
|---|---|---|---|
| Fasted clinical PK, same or similar formulation | R | Verification step in the IQ decision tree | Riedmaier 2020 |
| Fed clinical PK (high-fat "anchor" study) | U. R for the middle-out route and for extending to new formulations or doses. May be waived for high-confidence bottom-up mechanisms | IQ: high-confidence bottom-up models "may not require" an anchor study; middle-out ones need one | Riedmaier 2020; Tistaert 2019 (Consensus) |
| Aqueous solubility versus pH (pH 2, 4, 7, plus ±1 unit around each pKa) | R | The IQ protocol | Riedmaier 2020 |
| Biorelevant solubility (FaSSGF, FaSSIF-V2, FeSSIF-V2); bile-micelle partition | R | Bile salt solubilisation is the key positive-food-effect mechanism | Riedmaier 2020; Al-Amiry Santos 2025 (Consensus) |
| Permeability (Caco-2/MDCK → Peff) | R | Absorption model | Riedmaier 2020 |
| Biorelevant dissolution (FaSSIF/FeSSIF); PSD | U | "Helpful" when the model must predict food effect | Pepin 2024 (Table 2) |
| Precipitation / supersaturation (two-stage transfer); full solubility profile including common-ion effect | C (weak bases, salts) | Main source of low-confidence predictions | Wagner 2021; Chenel 2026 |
| Meal composition and timing of the clinical studies | R | Needed to choose the fed physiology | Chenel 2026 |
| IV PK | O | IQ used IV only to simplify; models "can be applied even in the absence of IV data" when the mechanism is absorption | Riedmaier 2020 |
| High hepatic extraction; absorption limited by transporters | C (lowers confidence) | Excluded from the IQ set | Riedmaier 2020 |
| fm, DDI data, ontogeny | N | — | — |

### 3.5 Pediatric extrapolation

| Item | Status | Why | Source |
|---|---|---|---|
| Adult model verified across single dose, multiple dose and DDI | R | First best-practice criterion | Johnson 2021 |
| Elimination pathway fractions (mass balance, in vitro, adult DDI) | R | Ontogeny applies per pathway | Johnson 2021 |
| Ontogeny of the relevant enzymes/transporters, verified with other drugs of the same pathway in the same age range | R | Example validation plan for a pediatric CoU | Johnson 2021; Kuemmel 2020 (CoU 2); Chenel 2026 |
| GFR·fu vs CLr; renal transporter ontogeny | C (renal elimination) | — | Johnson 2021; Zhou 2016 |
| Pediatric PK, even sparse | U; R when the model replaces a study | "Validation against available pediatric PK data whenever possible" | Chenel 2026 |
| Pediatric formulation (adult BE, salts, co-solvents) | U | — | Johnson 2021 |
| Food and dosing conditions (milk/formula, food vehicles, meal size and frequency); co-administered fluid volume | C (infants; drugs with an adult food effect; poorly soluble drugs) | — | Johnson 2021; Statelova 2020; Parrott 2024 (Consensus) |
| Biorelevant solubility, permeability (mechanistic absorption) | C (BCS 2, 3, 4) | — | Johnson 2021 |
| Allometric cross-check; PD or receptor-occupancy target | O | "Safety net" | Johnson 2021 |
| Disease effects on system parameters | C | — | Johnson 2021 |
| QC dissolution; IV PK | N / O | — | — |

### 3.6 Organ impairment (RI = renal impairment, HI = hepatic impairment)

| Item | RI | HI | Why | Source |
|---|---|---|---|---|
| Fraction excreted unchanged in urine / CLr | R | U | The renal share drives the RI AUC change | Heimbach 2021; Chenel 2026 |
| Filtration vs secretion; renal transporters | C | N | OAT substrates in CKD were predicted within 50% of observed AUC changes | Hsueh 2018 |
| fm per hepatic enzyme; hepatic extraction class | U | R | Enzyme-specific changes in HI | Chenel 2026; El-Khateeb 2021 |
| Hepatic uptake (OATP) | U | C | Extended-clearance behaviour differs in HI | Storelli 2023 |
| fu and binding protein (albumin, AAG) | U | U | fu changes with disease | Hu 2025 (Consensus); Chenel 2026 |
| Uraemic effects on hepatic enzymes/transporters | U | N | — | Chenel 2026 |
| Clinical impairment-arm PK | U (R at high influence) | U (R at high influence, especially moderate and severe) | IQ: over-prediction in moderate/severe HI. EMA qualified elacestrant for mild and moderate HI only | Heimbach 2021; Paul 2025 |
| Absorption changes in HI (bile salts, shunting) | N | O | Hypothesis-level evidence | El-Khateeb 2021; Al-Amiry Santos 2026 (Consensus) |
| Food, dissolution, ontogeny | N | N | — | — |

### 3.7 Formulation change, bridging and virtual BE (PBBM)

| Item | Status | Why | Source |
|---|---|---|---|
| Disposition model: IV (preferred) or one justified alternative (oral solution, SAD/MAD, mass balance, PopPK) | R (one of them) | "No stringent regulatory requirement to routinely generate iv data" | Heimbach 2024 |
| Solubility vs pH; surface solubility; salt disproportionation | R | — | Pepin 2024 |
| pKa; permeability (fitting Peff without justification was criticised) | R | — | Pepin 2024 |
| Dissolution profiles, with method parameters (volume, pH, apparatus, rpm, surfactant, micelle properties) | R. Suggested: ≥3 independent methods on the same batch | Workshop checklist, not guidance | Pepin 2024 (Table 2); Kollipara 2023 |
| API PSD (D10/D50/D90) | C (when PSD is a critical material attribute) | Case study | Heimbach 2024 (case 4) |
| Clinical PK for several formulations/batches, ideally including a non-BE batch (failure edge) | U | "Should be guided by meaningful changes and be feasible to produce" | Heimbach 2024 |
| Individual-level PK; between- and within-subject variability (IOV) | R for virtual BE | — | Chenel 2026; Bego 2022 |
| Precipitation; excipient, polymer and ASD effects | C | — | Pepin 2024; Chenel 2026 |
| Fed-state data | C (only if BE must be shown fed) | — | Chenel 2026 |
| fm, DDI data, ontogeny | N | — | — |

### 3.8 pH-dependent absorption and acid-reducing agents (ARA)

| Item | Status | Why | Source |
|---|---|---|---|
| pKa; solubility over the gastric pH range under ARA | R (weak bases) | Mechanism of the interaction | Dong 2020; Wu D 2025 |
| Dissolution at acidic and neutral pH, or in media simulating elevated gastric pH under PPIs | R | — | Pepin 2024; Segregur 2021 |
| Precipitation / supersaturation; salt form and surface pH | U / C | Acalabrutinib maleate case | Heimbach 2024 |
| Clinical PK with and without an ARA (at least one study) | U (R at high influence) | FDA case set: erlotinib only qualitatively predicted. EMA did not qualify the mitapivat ARA DDI model | Dong 2020; Paul 2025 |
| Fed vs fasted PK | U | Used to verify the models | Dong 2020 |
| FDA ARA guidance: in vitro plus clinical approach | — | "Guidance on the evaluation of pH-mediated DDI" (title/date from memory: draft, 2020) | Wu D 2025 |
| fm, ontogeny | N | — | — |
| Precedent in PK-Sim | — | Dasatinib model covering both ARA and CYP3A4 DDI | Kovar 2024 |

### 3.9 First-in-human (FIH) and dose prediction (low regulatory impact; Shebley 2018)

| Item | Status | Why | Source |
|---|---|---|---|
| In vitro CLint, fu (human and species), B/P, logP, pKa, solubility, permeability | R | Bottom-up inputs | Miller 2019; Shebley 2018 |
| Preclinical IV PK in several species (to verify IVIVE) | U | All 5 compounds were within 2-fold only with preclinical verification. Clearance IVIVE was the most common failure | Jackson 2026; Chenel 2026 |
| Uncertainty and sensitivity analysis (CLint, Kp, absorption rate) | R | — | Chenel 2026 |
| Clinical data | N (not yet available) | — | — |
| Food, ontogeny, organ impairment | N/O | — | — |

### 3.10 Special populations

| Population | Item | Status | Source |
|---|---|---|---|
| Pregnancy | Verified non-pregnant model with pathway fractions (CYP, UGT, transporter) | R | Coppola 2023 |
| Pregnancy | Gestation-dependent physiology (OSP workflow) | R | Dallmann 2018 |
| Pregnancy | Pregnancy PK of drugs sharing the pathway | U. Data scarcity "hampered" the MHRA evaluation | Coppola 2021, 2023 |
| Pregnancy | Placental transfer | C (fetal exposure question) | Coppola 2021 |
| Pregnancy | UGT and transporter changes | Recognised gap: flag the model as weaker | Coppola 2023 |
| Geriatrics | Age-informed physiology | R (platform) | Schlender 2016 (PK-Sim) |
| Geriatrics | Verification with drugs in the elderly | U | Schlender 2016 |
| Geriatrics | Renal function distribution | C (renal drugs) | Chenel 2026 |
| Ethnicity | Population-specific enzyme abundance and genotype frequency | U | Feng 2015 |
| Ethnicity | Probe-drug verification in that population | U | Feng 2015 (omeprazole/CYP2C19: Japanese oral clearance under-predicted) |

## 4. Verification and acceptance criteria by CoU

| CoU | Criteria reported | Source |
|---|---|---|
| General | No single agency number. EMA: "acceptance criteria … depends on the regulatory impact". Pre-specify AFE/AAFE/GMFE/RMSE and fold limits in the analysis plan. 0.8–1.25 typical for virtual BE; 2-fold "may be justified" early in development | Paul 2025 (quoting the EMA guideline); Chenel 2026 |
| General | Fixed 2-fold can be unreasonable when observed data come from small studies; link the limit to observed variability | Abduljalil 2014 |
| DDI | 1.25-fold on predicted/observed ratio of AUC and Cmax ratios (FDA OCP; percentages in §1). Fixed 2-fold is biased toward "success" when the AUC ratio is below 2, hence variable limits (Guest) | Wagner 2015, 2016; Guest 2011 |
| DDI | High-risk worked example: DDI ratios within 25%, base Cmax within 2-fold | Kuemmel 2020 |
| DDI | PK-Sim CYP3A4 qualification: GMFE 1.4 | Frechen 2021 |
| Food effect | IQ confidence classes: high = 0.8–1.25 (or bottom-up within 2-fold with good overlay); moderate = 0.5–2; low = >2. Result: 15/8/7 of 30 compounds. Literature: about 50% within 1.25-fold, 75% within 2-fold | Riedmaier 2020; Li M 2018 |
| Pediatric | Clearance within 2-fold for 33/34 renally cleared drugs (≥1 month); 10/11 within 1.5-fold at 1 month–2 years. Low-risk CoU: visual comparison sufficient | Zhou 2016; Kuemmel 2020 |
| Organ impairment | AUC ratio within 2-fold: RI 47/50 arms, HI 43/56 arms (worse in moderate/severe HI). CKD OAT substrates within 50% | Heimbach 2021; Hsueh 2018 |
| PBBM / virtual BE | "No pre-established acceptance criteria." Pre-specify %PE, FE, AFE, AAFE, AAPE. Virtual BE uses the GMR with 90% CI and needs BSV/WSV. Elagolix accepted at 0.80–1.25. ±10% is the usual dissolution-specification window | Heimbach 2024; Bego 2022 |
| ARA | No numeric criterion found; evidence base small | Dong 2020 |
| FIH | 2-fold is the working standard | Jackson 2026 |
| Pregnancy | No numeric criterion; trends captured, magnitude often not | Coppola 2023 |

## 5. Model credibility and model risk

- **ASME V&V40 applied to PBPK (Kuemmel 2020).** Steps: question of interest → CoU → model risk (influence × decision consequence, each low/medium/high, mapped to a 5-level matrix) → credibility goals and activities across 13 factors (code, calculation, model form, inputs, comparators, output comparison, applicability) → assessment.
  - If credibility falls short, the options are to **downgrade influence**, add data, or revise the CoU.
- **EMA.** The impact levels (from Paul 2025): high = the model is the key source for the SmPC; moderate = combined with clinical data; low = descriptive. "The higher the impact, the greater the requirements on qualification." The Musuamba 2021 credibility matrix is proposed for assessment reports.
- **ICH M15.** QoI, CoU, model influence, consequence of a wrong decision, model risk and an "assessment table", with technical criteria pre-defined in the analysis plan (Chenel 2026). The repository's ruleset states M15 reached Step 4 on 29 Jan 2026; I did not verify that date.
- **Shebley 2018, high-impact criteria.** Qualified platform; mechanism-specific drug model; training set; independent verification set; sensitivity analysis; patient-risk evaluation including uncertainty.

**How evidence scales with risk**

| Risk | Typical evidence | Source |
|---|---|---|
| Low (FIH, trial design, pediatric starting dose later confirmed in a trial) | Documented assumptions; base PK reproduced; visual checks | Kuemmel 2020; Shebley 2018 |
| Medium (supportive evidence alongside clinical data; transporter DDI; pediatrics) | Internal and external validation on relevant data; sensitivity analysis | Shebley 2018 |
| High (waives a study or sets the label) | Platform qualified for the pathway (EMA: about 8–10 compounds for CYP3A4); mechanism verified with independent clinical data; stringent pre-set criteria on the decision metric; global sensitivity analysis plus uncertainty propagation; benefit–risk context (exposure–response) | Paul 2025; Kuemmel 2020; Chenel 2026 |

## 6. What reviewers flag most often

- **EMA (Paul 2025):**
  - No relevant verification data: healthy-volunteer data only, sparse or non-PK sampling, small n, irrelevant DDI, compound file not submitted.
  - Structure: autoinhibition or autoinduction missing; intestinal enzyme or transporter missing; probe-substrate handling.
  - Unjustified inputs: literature values instead of in-house data; fm methodology.
  - Poor reproduction of Tmax, Cmax or DDI magnitude.
  - Too few qualification compounds.
- **EMA and FDA (Shebley 2018):** missing sensitivity analyses (5 objections, withdrawn once supplied); intestinal CYP3A DDI not accepted; disagreement on induction and UGT-inducer evidence.
- **FDA reviews of 2024 approvals (Li 2025\*):** a single unverified Ki; empirical fm adjustments; induction calibrated without clinical DDI data; verification with a non-sensitive substrate; incomplete transporter mechanisms. Underlying theme: the chain from in vitro data to clinical prediction is broken. FDA also found default perpetrator models under-predicting (Wagner 2016).
- **PBBM (Pepin 2024; Heimbach 2024; Arora 2025):**
  - Lesinurad (EMA): fitted Peff and gastric emptying, GI fluid volumes, formulation switch, manual dose adjustment during verification, virtual-population variability lower than clinical.
  - Acalabrutinib (FDA): an 8-subject dataset and fitted product particle size (P-PSD).
  - Across submissions: "frequent requests for additional information".
- **Pregnancy (Coppola 2023):** lack of pathway-specific clinical data; UGT and transporter changes missing from platforms.
- **Pediatrics (Johnson 2021):** verification data must match the target age range; ontogeny uncertainty needs sensitivity analysis.

\*Li 2025 is a secondary analysis by a consultancy. Some details look doubtful, for example a reported boxed-warning text for pediatric dosing. Check against the primary FDA review documents before relying on specifics.

## 7. Product ideas that follow from the evidence

1. **CoU requirement matrix (SME-governed ruleset).** Each data item gets R/U/C/O/N per CoU. **C items carry machine-checkable triggers** from compound attributes in the CPF: weak base with pH-dependent solubility, fm above a threshold, renal fraction excreted, transporter substrate, BCS class, TDI or inducer flag, infant dosing condition. Thresholds are for SMEs to set; I propose none.
   - "Missing" is shown only for R items, and for U items when influence is high. N items are hidden; C items appear only when their trigger fires.
2. **Risk-tier escalation from the M15 assessment table.** The existing `m15.py` influence/consequence ratings would switch U→R automatically for high-influence uses (independent clinical verification, qualification-set size, global sensitivity analysis), matching Kuemmel 2020 and Shebley 2018.
3. **"Not relevant" is an auditable decision, not a blank.** The platform proposes N with the literature rationale (e.g. "fed PK: N because pediatric dosing is fasted and adult food effect is absent"). Overriding needs a reason under Part 11 audit. This fits the data-intake plan's status words.
4. **Auto-worded data requests per missing item**, including why it matters and the accepted alternatives. Example: "IV PK unavailable; acceptable alternatives: oral solution, SAD/MAD, mass balance, PopPK" (Heimbach 2024). Another: "a clinical DDI with a strong index inhibitor will be needed to extrapolate to moderate inhibitors" (Kuemmel 2020).
5. **Pre-flight check against the EMA non-qualification categories** (Paul 2025):
   - Autoinhibition modelled when the drug inhibits its own pathway?
   - Gut metabolism included for CYP3A substrates?
   - Verification population and design relevant to the target?
   - Compound/project files included?
   - fm derivation justified?
   - Number of qualification compounds per pathway?
6. **Pathway qualification tracker for PK-Sim.** Pull the relevant OSP qualification report (Frechen 2021) into the package. Count qualified perpetrators and substrates per pathway against the EMA 8–10 expectation, and warn on thin non-CYP3A pathways.
7. **"Decision-flip" sensitivity panel.** Show whether the label conclusion changes within plausible ranges of Ki, fm, EC50/Emax or precipitation time (Shebley 2018; Taskar 2025; the Li 2025 Ki example).
8. **Evidence-chain view.** A schematic mapping in vitro → base PK → pathway verification → application, with the data used at each step (Chenel 2026, Fig. 2; Li 2025).
9. **Acceptance-criteria picker locked into the analysis plan per CoU.** Options: DDI ratios (1.25-fold, or Guest limits); food effect (the IQ confidence classes); virtual BE (GMR with 90% CI and BSV/WSV). Criteria are fixed before any run.
10. **Mechanism-based confidence labels for food effect.** High when the mechanism is GI fluids or bile; low for salts, weak bases with precipitation, or viscosity effects (Riedmaier 2020; Wagner 2021).
11. **Report skeletons mapped to the expected structures:** FDA 2018 format, the EMA 2018 guideline, the PBBM template (Arora 2025), and the M15 assessment table.

## 8. Caveats and items to verify

- **Guidance texts were not re-read in this session.** Titles and dates I give from memory and have not verified:
  - FDA PBPK Format and Content (final, Aug 2018).
  - FDA draft PBPK for biopharmaceutics applications (Oct 2020).
  - FDA ARA draft (2020).
  - FDA food-effect guidance (2022).
  - ICH M12 and M13A (2024), M13B, E11A.
  - FDA renal/hepatic impairment guidance versions.
- **I found no numeric acceptance criterion in the FDA PBBM draft or in ICH M15.** Do not state one.

## 9. Two problems in the locked acceptance ruleset

These are in `packages/pbpk-domain/src/pbpk_domain/rulesets/pbpk_acceptance_criteria.yaml` (not edited; any change needs owner/SME approval):

1. **Wrong title for `guest_2011`.** The ruleset calls it "Assessment of algorithms for predicting drug-drug interactions via inhibition mechanisms". PubMed lists Drug Metab Dispos 2011;39:170–3 as **"Critique of the two-fold measure of prediction success for ratios: application for the assessment of drug-drug interactions"** (PMID 21036951).
2. **Medium-tier 1.5-fold limit attributed to the EMA guideline.** No source I read supports this: Paul 2025 quotes EMA as impact-dependent only. Also, the high tier applies 1.25-fold to **base** AUC and Cmax, whereas the literature applies the tight limit to the **decision metric** (DDI ratio) and allows looser base PK, e.g. 2-fold base Cmax with ratios within 25% (Kuemmel 2020). Both points are for SME review.

## 10. References

According to PubMed: DOIs as listed; \* = Consensus record, PMID not retrieved.

- Paul P et al. 2025, Clin Pharmacol Ther. PMID 39748538, https://doi.org/10.1002/cpt.3525
- Chenel M et al. 2026, CPT PSP. PMID 42400597, https://doi.org/10.1002/psp4.70295
- Shebley M et al. 2018, Clin Pharmacol Ther. PMID 29315504, https://doi.org/10.1002/cpt.1013
- Kuemmel C et al. 2020, CPT PSP. PMID 31652029, https://doi.org/10.1002/psp4.12479
- Musuamba FT et al. 2021, CPT PSP. PMID 34102034, https://doi.org/10.1002/psp4.12669
- Zhang X et al. 2020, J Clin Pharmacol. PMID 33205429, https://doi.org/10.1002/jcph.1767
- Grimstein M et al. 2019, J Pharm Sci. PMID 30385284, https://doi.org/10.1016/j.xphs.2018.10.033
- Luzon E et al. 2017, Clin Pharmacol Ther. PMID 27770430, https://doi.org/10.1002/cpt.539
- Zhao P et al. 2011, Clin Pharmacol Ther. PMID 21191381, https://doi.org/10.1038/clpt.2010.298
- Li Y et al. 2025, Pharmaceutics. PMID 41304751, https://doi.org/10.3390/pharmaceutics17111413
- Wagner C et al. 2015, Clin Pharmacokinet. PMID 25260695, https://doi.org/10.1007/s40262-014-0188-4
- Wagner C et al. 2016, Clin Pharmacokinet. PMID 26369776, https://doi.org/10.1007/s40262-015-0330-y
- Guest EJ et al. 2011, Drug Metab Dispos. PMID 21036951, https://doi.org/10.1124/dmd.110.036103
- Abduljalil K et al. 2014, Drug Metab Dispos. PMID 24989891, https://doi.org/10.1124/dmd.114.058099
- Frechen S et al. 2021, CPT PSP. PMID 33946131, https://doi.org/10.1002/psp4.12636
- Taskar KS et al. 2020, Clin Pharmacol Ther. PMID 31628859, https://doi.org/10.1002/cpt.1693
- Taskar KS et al. 2021, Curr Drug Metab. PMID 33397250, https://doi.org/10.2174/1389200221999210101233340
- Vijaywargi G et al. 2023, Biopharm Drug Dispos. PMID 36413625, https://doi.org/10.1002/bdd.2339
- Hariparsad N et al. 2022, Clin Pharmacol Ther. PMID 34862964, https://doi.org/10.1002/cpt.2503
- Rodrigues D et al. 2025, Clin Transl Sci. PMID 40671325, https://doi.org/10.1111/cts.70299
- Umehara K et al. 2019, Drug Metab Pers Ther. PMID 31145690, https://doi.org/10.1515/dmpt-2018-0042
- Prieto Garcia L et al. 2022, CPT PSP. PMID 35722750, https://doi.org/10.1002/psp4.12837
- Riedmaier AE et al. 2020, AAPS J. PMID 32981010, https://doi.org/10.1208/s12248-020-00508-2
- Wagner C et al. 2021, AAPS J. PMID 34142242, https://doi.org/10.1208/s12248-021-00601-0
- Li M et al. 2018, CPT PSP. PMID 29168611, https://doi.org/10.1002/psp4.12260
- Johnson TN et al. 2021, CPT PSP. PMID 34288581, https://doi.org/10.1002/psp4.12678
- Statelova M et al. 2020, AAPS J. PMID 33000297, https://doi.org/10.1208/s12248-020-00504-6
- Zhou W et al. 2016, CPT PSP. PMID 27566992, https://doi.org/10.1002/psp4.12101
- Heimbach T et al. 2021, Clin Pharmacol Ther. PMID 33270249, https://doi.org/10.1002/cpt.2125
- Hsueh CH et al. 2018, Clin Pharmacol Ther. PMID 28738449, https://doi.org/10.1002/cpt.750
- El-Khateeb E et al. 2021, Aliment Pharmacol Ther. PMID 34218453, https://doi.org/10.1111/apt.16489
- Pepin X et al. 2024, Mol Pharm. PMID 38946085, https://doi.org/10.1021/acs.molpharmaceut.4c00526
- Heimbach T et al. 2024, Mol Pharm. PMID 39348508, https://doi.org/10.1021/acs.molpharmaceut.4c00758
- Arora S et al. 2025, Mol Pharm. PMID 40300064, https://doi.org/10.1021/acs.molpharmaceut.5c00225
- Wu F et al. 2021, AAPS J. PMID 33619657, https://doi.org/10.1208/s12248-021-00564-2
- Bego M et al. 2022, AAPS J. PMID 34988679, https://doi.org/10.1208/s12248-021-00672-z
- Dong Z et al. 2020, CPT PSP. PMID 32633893, https://doi.org/10.1002/psp4.12541
- Wu D et al. 2025, Drug Metab Rev. PMID 38700278, https://doi.org/10.1080/03602532.2024.2345632
- Segregur D et al. 2021, Eur J Pharm Sci. PMID 33253885, https://doi.org/10.1016/j.ejps.2020.105656
- Kovar C et al. 2024, CPT PSP. PMID 38693610, https://doi.org/10.1002/psp4.13146
- Miller NA et al. 2019, Clin Pharmacokinet. PMID 30729397, https://doi.org/10.1007/s40262-019-00741-9
- Jackson C et al. 2026, Clin Pharmacokinet. PMID 42171970, https://doi.org/10.1007/s40262-026-01655-z
- Jones HM et al. 2015, Clin Pharmacol Ther. PMID 25670209, https://doi.org/10.1002/cpt.37
- Coppola P et al. 2021, Front Pediatr. PMID 34249817, https://doi.org/10.3389/fped.2021.687978
- Coppola P et al. 2023, J Clin Pharmacol. PMID 37317504, https://doi.org/10.1002/jcph.2266
- Dallmann A et al. 2018, CPT PSP. PMID 29569837, https://doi.org/10.1002/psp4.12300
- Schlender JF et al. 2016, Clin Pharmacokinet. PMID 27351180, https://doi.org/10.1007/s40262-016-0422-3
- Feng S et al. 2015, Eur J Clin Pharmacol. PMID 25801493, https://doi.org/10.1007/s00228-015-1834-y
- \*Tistaert C et al. 2019, J Pharm Sci: https://consensus.app/papers/details/w:e8661642-9bea-452c-a732-76d4951892fb/?utm_source=claude_desktop
- \*Taskar KS et al. 2025, Clin Pharmacol Ther: https://consensus.app/papers/details/w:3f153bf7-999f-4eef-80e0-1617b8fb218d/?utm_source=claude_desktop
- \*Templeton IE et al. 2026, CPT PSP: https://consensus.app/papers/details/w:0ed941e6-6dc8-497f-adb3-999a6756e3e2/?utm_source=claude_desktop
- \*Parrott N 2024, J Clin Pharmacol: https://consensus.app/papers/details/w:6c5f719b-c29a-4679-9778-3c179755ed31/?utm_source=claude_desktop
- \*Hu Y et al. 2025, AAPS J: https://consensus.app/papers/details/w:00aaaf33-61de-4cd6-ad03-81984a1ea749/?utm_source=claude_desktop
- \*Storelli F et al. 2023, CPT PSP: https://consensus.app/papers/details/w:26fa8f48-1541-47b1-88bd-5f761229975a/?utm_source=claude_desktop
- \*Al-Amiry Santos LG et al. 2025, AAPS J: https://consensus.app/papers/details/w:4844956e-84b6-40cf-b6b4-b963d67ce941/?utm_source=claude_desktop
- \*Al-Amiry Santos LG et al. 2026, AAPS J: https://consensus.app/papers/details/w:8e2051f5-20d7-4663-8e68-82ff5484d8ec/?utm_source=claude_desktop
- \*Templeton IE et al. 2016, CPT PSP (inhibitory metabolites): seen in Consensus screening only; link not captured.
- \*Kollipara S et al. 2023, AAPS PharmSciTech (dissolution data in PBBM): seen in Consensus screening only; link not captured.

**Guidances, cited by name:**
- FDA, PBPK Analyses — Format and Content (2018).
- FDA, The Use of PBPK Analyses — Biopharmaceutics Applications for Oral Drug Product Development, Manufacturing Changes, and Controls (draft, 2020).
- EMA, Guideline on the reporting of PBPK modelling and simulation, EMA/CHMP/458101/2016 (effective 1 July 2019).
- ICH M15, M12, M13A, E11A.
- ASME V&V 40-2018 (via Kuemmel 2020).

