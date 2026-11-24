# PBBM and oral absorption inputs: what to extract from a client delivery (literature review, 2026-11-24)

Research report by a literature agent; not SME-reviewed. Items marked not verified / UNVERIFIED stay so until checked.

**Scope and method.** I searched PubMed (search_articles, get_article_metadata, get_full_text_article) and Consensus (6 searches, page sizes 30–35). I screened about **360 unique records** by title and abstract: 236 PubMed metadata records plus 190 Consensus records, de-duplicated by title. About 25 PubMed hits were off-topic (dermal, inhalation and long-acting injectable products, nutraceuticals) and were excluded. I read **4 key papers in full**: the 2023 M-CERSI workshop summary (Mackie 2024), the Day-1 parameterisation report (Pepin 2024), the Day-3 applications report (Tannergren 2025) and the industry PBBM report template (Arora 2025). The reference list below has **126 papers**; all are cited in the text. 119 were checked against PubMed metadata, 3 have a PMID from the citation matcher only (no metadata check), and 4 come from Consensus only (link given).

I checked PK-Sim names, read-only, against the OSP snapshots in `services/engine-worker/golden/fixtures/*.json` and `packages/pbpk-domain/src/pbpk_domain/cpf/formulations.py`. A PK-Sim name is given only where it appears there; anything else is marked *not verified*. I edited no other repository file (this report is the one file I wrote).

Consensus hit its free monthly limit partway through, so the rest of the search used PubMed only.

---

## 0. Bottom line for the extraction decision

What matters depends on **which step limits absorption**: gastric emptying, dissolution, solubility, permeability, or precipitation. If absorption is limited by permeability, faster dissolution does not change exposure and a minimum dissolution criterion is enough. If it is limited by dissolution, any change in release changes exposure [2, 29, 30].

The platform should therefore extract enough to classify the limiting step first, then insist on the inputs that drive that step.

**Always extract (these change predictions):**
- **Dissolution profiles**, per batch and per medium:
  - unit-level data, not only means;
  - complete method metadata (apparatus, speed, volume, medium, surfactant);
  - for the clinical batches, the reference product and any non-bioequivalent (non-BE) or variant batches.
- **Solubility versus pH**, with the start and final pH, plus **biorelevant solubility** (FaSSGF, FaSSIF, FeSSIF).
- **pKa** and the **solid form**: salt, polymorph or amorphous.
- **Particle size distribution** of the drug substance: the full distribution with the method used, per clinical batch.
- **Dose and strength.**
- **Permeability together with that lab's reference-compound calibration set.**
- **Precipitation or transfer data**, for weak bases and supersaturating formulations.
- **Quantities of *functional* excipients:** sugar alcohols and other osmotic agents, surfactants, pH modifiers, permeation-modifying excipients, and amorphous solid dispersion (ASD) polymers or precipitation inhibitors.
- **Disintegration time.**
- **Clinical pharmacokinetics (PK) per batch**, including IV or oral-solution PK and any food or acid-reducing agent (ARA) studies.

**Context only.** Store these and use them as triggers to request data, but do not turn them into model parameters:
- the full excipient list beyond the functional classes (keep it for Q1/Q2 qualitative and quantitative comparison);
- the manufacturing process narrative and equipment;
- tablet hardness and friability;
- f2 values, which are a regulatory comparator, not a model input.

The manufacturing process and hardness act *through* disintegration and dissolution, which have to be measured. A DS particle size measured before processing is rarely a good guide to the drug surface area available in the finished product (Pepin 2024, breakout session C) [2].

---

## 1. Input-impact table

Impact levels: HIGH means the input often changes the predicted Cmax or AUC enough to change a bioequivalence or specification decision. MEDIUM means it matters in some cases or for some questions. LOW means it rarely matters. CONTEXT ONLY means it is not a model input.

| # | Input | Impact | For which question | How it enters the model (PK-Sim only where verified) | Sources |
|---|---|---|---|---|---|
| 1 | **Dissolution profiles per medium** (QC method, pH 1.2/4.5/6.8, biorelevant), per batch | **HIGH** for BCS II/IV immediate release, modified release and enabling formulations. **LOW–MEDIUM** when absorption is permeability-limited (ribociclib; a BCS III product where >85% in 60 min had no BE impact) | Dissolution specification and safe space, virtual BE (VBE), batch or formulation bridging, SUPAC. Several media are needed when food, ARA or other populations are in scope | (a) **Empirical:** a Weibull fit, which depends on time only and ignores physiology. PK-Sim `Formulation_Tablet_Weibull` has "Dissolution time (50% dissolved)" [min], "Dissolution shape", "Lag time" [min] and "Use as suspension" (verified in the snapshots). (b) **Mechanistic:** a fitted z-factor or product particle size distribution (P-PSD) feeding a particle dissolution model. PK-Sim `Formulation_Particles` has "Particle radius (mean)" [µm], "Thickness (unstirred water layer)" [mm] and "Type of particle size distribution" (verified). The repository's `ParticleBins` gives a multi-bin P-PSD. A mechanistic model is required to extrapolate to the fed state, ARA co-administration or other populations, because Weibull and direct input cannot respond to physiology [2] | [2, 15, 22, 27–33, 110] |
| 2 | **Dissolution method metadata**: apparatus, rpm, volume, medium composition, buffer capacity, pH, surfactant type and concentration, sinkers, dose | **HIGH** (prerequisite) | Any mechanistic dissolution fit | Needed to derive a P-PSD or z-factor. The workshop checklist asks for ≥3 independent methods on the same batch, plus the surfactant's blank solubility, micelle concentration, drug–surfactant affinity, CMC and micelle size [2, Table 2]. Paddle speed and viscosity change dissolution rate [47] | [2, 47, 50, 51] |
| 3 | **Individual-unit dissolution data and number of units** | **MEDIUM** | f2 validity checks; between-unit variability in VBE | Not a model parameter. Used for uncertainty and variability ranges, and to check whether f2 may be applied. Guidance as commonly summarised requires 12 units per profile (FDA 1997 IR dissolution guidance, EMA 2010 BE guideline, ICH M13A); *these figures are from my knowledge of the guidances, not retrieved here: verify* | [55, 56, 41, 5] |
| 4 | **f2** | **CONTEXT ONLY** | Flags the question of interest | Not an input. PBBM has repeatedly shown BE despite f2 < 50 [28–30, 38]. The f2 ≥ 50 region lies entirely inside the BE region, so f2 is conservative [54]. For BCS III the reverse risk exists: BCS biowaiver dissolution tests missed a non-BE pravastatin product [103] | [28–30, 38, 54, 57, 103] |
| 5 | **Disintegration time / capsule opening** | **MEDIUM**; **HIGH** if slow (e.g. ≥45 min in FaSSGF for weak-base tablets [58]) or food-dependent [59, 60] | Immediate-release performance, food effect | Disintegration time must be removed before fitting particle models, or disintegration modelled separately [2, 48]. Disintegration in vivo is slower than in the USP test [2]. Weibull "Lag time" exists in PK-Sim; using it to represent disintegration is a modelling assumption | [2, 48, 58–60] |
| 6 | **Tablet hardness, porosity, compression force** | **CONTEXT ONLY** as an input | Choosing clinically relevant variants for a safe space | Acts only through disintegration and dissolution. The template lists porosity, compression force and disintegrant amount among the material and process attributes (CMAs/CPPs) to vary in fit-for-purpose clinical batches [5, Table 8] | [2, 5] |
| 7 | **Manufacturing process** (granulation route, milling, compression, coating) | **CONTEXT ONLY** as an input; **HIGH** as context | Safe space, SUPAC, setting specifications | Compression fragments particles, the drug substance aggregates, and shape and wettability vary. Scaling the drug-substance PSD with one diffusion-layer factor therefore "cannot be sustained theoretically" [2]; a P-PSD fitted to dissolution captures the process effect. ANVISA cited "incomplete understanding of product CMA, CPP, CQA relationships" as a deficiency [1] | [1, 2, 5] |
| 8a | **Sugar alcohols and other osmotic excipients** (sorbitol, mannitol), as mg per dose | **HIGH** for low-permeability (BCS III) drugs and solutions | BCS III biowaivers, generic bridging | Act through GI water and transit, so they enter via a change to physiology. *A PK-Sim excipient input is not verified; I know of none.* With 5 g sorbitol versus sucrose, ranitidine Cmax fell about 50% and AUC about 45% [95]. Sorbitol at 7–60 mg affected risperidone oral solution [97]. A PBBM estimated a provisional no-effect level of <400 mg [96] (**UNVERIFIED**; SME decision) | [95–101] |
| 8b | **Surfactants** (SLS, polysorbates) | **MEDIUM–HIGH** | Dissolution, solubility, permeability | Enter via the solubility and dissolution measured with the surfactant present, plus micelle parameters [2]. 3.64 mg SLS altered risperidone bioavailability [97]. Micelle-bound drug is not absorbed like free drug [70]. SLS can form poorly soluble lauryl sulfate salts in vitro [2] | [2, 70, 97] |
| 8c | **pH modifiers, buffering or alkalinising salts** (calcium phosphates, organic acids) | **HIGH** for ionisable low-solubility drugs | BE risk, Cmax | Change the surface pH and so the dissolution rate. Tribasic calcium phosphate raised ibuprofen Cmax [51]. Calcium monohydrogen phosphate made a dexketoprofen product non-BE [104] | [2, 51, 104] |
| 8d | **Permeation-modifying excipients** (some disintegrants, others) | **MEDIUM** (BCS III) | BCS III biowaiver, VBE | Enter by scaling permeability. Silodosin: crospovidone and related excipients changed permeability [102]. Pravastatin: the non-BE product had higher permeability [103]. Acyclovir: products stayed BE up to a +30% increase in Papp [106]. Caco-2 tends to over-predict excipient effects [2] | [102, 103, 105–107] |
| 8e | **ASD polymers and precipitation inhibitors** | **HIGH** | Enabling formulations | Change amorphous solubility, colloid formation and precipitation; amorphous solubility should be measured *with* the polymer present [2] | [2] |
| 9 | **Dose and strength** | **HIGH** | Non-linearity, strength biowaivers | Dose in the protocol. The dose-to-solubility ratio sets the onset of solubility-limited absorption [108, 71] | [30, 38, 71, 108] |
| 10 | **Solubility vs pH** (pH ~1–8; above pKa+2 for intrinsic solubility; start and final pH; buffer; common ions; pHmax for salts) | **HIGH** for ionisable compounds | Food effect, ARA, precipitation, dissolution | PK-Sim compound "Solubility at reference pH" with "Reference pH" (names present in the repository), or a "Solubility table" against pH (verified in the ketoconazole snapshot). A common-ion (chloride) effect forced a model refinement in the Health Canada case [2] | [2, 72–75] |
| 11 | **Surface pH / surface solubility** | **HIGH** when dissolution limits absorption | Dissolution model fidelity | Using bulk instead of surface solubility over-predicted dissolution by 48% [32]. Buffer capacity matters (ibuprofen [50, 51]). *Whether standard PK-Sim particle dissolution handles surface pH is not verified*; a MoBi extension may be needed [116] | [2, 32, 49–51] |
| 12 | **Biorelevant solubility** (FaSSGF, FaSSIF v1/v2, FeSSIF, FeSSGF; ideally aspirated human intestinal fluid) | **HIGH** for lipophilic or neutral poorly soluble drugs and for food effect; **LOW** when the drug is ionised in the gut | Food effect, fed BE | Bile-micelle solubilisation. The OSP workflow estimates bile-salt partitioning with the OSP solubility toolbox and a MoBi dissolution model [116, 117]. *No standard PK-Sim field for this is verified.* Solubility in aspirated fluid matched FaSSIF/FeSSIF for 17 drugs [61] | [2, 61–64, 68, 116, 117] |
| 13 | **pKa** values and their types | **HIGH** for ionisable compounds | Everything pH-related | PK-Sim `PkaTypes` (Type Acid/Base, pKa) (verified) | [2] |
| 14 | **logP / logD / membrane affinity** | **MEDIUM** for absorption, **HIGH** for distribution | Permeability when none is measured | PK-Sim "Lipophilicity" [Log Units] (verified). PK-Sim's *default* intestinal permeability is calculated from lipophilicity and molecular weight [108, 109]. OSP models often *fit* lipophilicity (the ketoconazole snapshot has the value "fit"), which couples absorption to distribution — flag this | [108, 109] |
| 15 | **Salt, cocrystal, polymorph, amorphous form** | **HIGH** when the form changes solubility | ARA, specifications, setting impurity limits | Form-specific solubility, and precipitation back to the free form. Salts mitigated the ARA effect [74, 75]. PMDA accepted a polymorphic-impurity limit via VBE [1]. Selumetinib salt versus free base behaved differently for precipitation [35] | [1, 35, 74, 75] |
| 16 | **Particle size** (d10/d50/d90; full distribution; method; per batch; aggregation or BET surface area) | **HIGH** for BCS II/IV, especially when a PSD specification is the question; **LOW** for BCS I/III | Drug-substance PSD specification, safe space | PK-Sim "Particle radius (mean)" (a radius, not a diameter) and "Type of particle size distribution" (verified); multi-bin via `ParticleBins`. Laser-diffraction PSD under-predicted dissolution by 31%; a P-PSD fitted to dissolution worked better [32]. Apixaban: particles <120 µm kept the product BE [36]. PSD similarity alone does not predict f2 [57] | [2, 31, 32, 36, 57, 112] |
| 17 | **Drug density and aqueous diffusion coefficient** | **MEDIUM** (only for the particle model) | Mechanistic dissolution | PK-Sim "Density (drug)" [g/cm³] and "Aqueous diffusion coefficient" [dm²/min] (both verified). Micelle-bound drug diffuses more slowly [2] | [2] |
| 18 | **Permeability** (Caco-2, MDCK or PAMPA Papp with the lab's reference set; human Peff; efflux ratio) | **HIGH** for BCS III/IV or permeability-limited drugs; **MEDIUM** for high-permeability drugs (affects rate and Tmax) | Fraction absorbed, Cmax, BCS III biowaiver | PK-Sim "Specific intestinal permeability (transcellular)" [cm/min] (verified). It must be **calibrated or fitted, never a raw Papp** (Section 2) | [2, 81–94] |
| 19 | **Transporter kinetics** (efflux or uptake; Km and Vmax) | **MEDIUM**, only when the data show an effect | Non-linear absorption, DDI | PK-Sim transporter processes (the ketoconazole snapshot has `ActiveTransportSpecific_MM` with ABCB1). An efflux ratio >2 does not by itself prove an in vivo effect [2] | [2] |
| 20 | **Precipitation data** (two-stage or transfer test, critical supersaturation, form and size of precipitate, redissolution) | **HIGH** for weak bases with high gastric and low intestinal solubility, and for supersaturating products | Dose escalation, food effect, ARA | PK-Sim "Enable supersaturation" and "Treat precipitated drug as" (verified). Precipitation kinetics are usually fitted to PK; in vitro tests are mainly used to *rule out* precipitation [1, 2]. Precipitation time was a commonly optimised parameter in FDA-reviewed food-effect models [67] | [1, 2, 35, 67, 76–80] |
| 21 | **Chemical or physical instability in GI media** | **MEDIUM** if present | Mass balance | A bell-shaped curve or a plateau below assay suggests degradation or a form change; measure degradation separately [2] | [2] |
| 22 | **IV or oral-solution PK** | **HIGH** | Separating absorption from disposition | Disposition model. Lack of IV data was an ANVISA deficiency [1]; a decision tree for using IV data is discussed in [3] | [1, 3] |
| 23 | **Clinical PK per batch, including non-BE or variant batches** (individual data) | **HIGH** for validation | Any regulatory use of the model | Validation set. A missing non-BE batch accounted for 14% of rejections [1] | [1, 5] |
| 24 | **Reference product (RLD) dissolution and PK** | **HIGH** for generics | VBE, biowaivers | Reference arm of the VBE | [17, 18, 43] |
| 25 | **Food and meal composition, timing, water volume** | **HIGH** for food-effect and fed-BE questions | Food effect; ICH M13A fed BE | Fed-state physiology: gastric emptying, pH, bile, volume, viscosity. *PK-Sim meal inputs not verified here* | [20, 23, 62–66] |
| 26 | **ARA co-medication** (PPI, H2 blocker, antacid; timing) | **HIGH** for weak bases | pH-dependent DDI | Raised gastric pH plus a mechanistic dissolution model | [33, 72–74] |
| 27 | **Gastric emptying** (fasted MMC phase; fed state) | **HIGH** for Cmax/Tmax of rapidly dissolving drugs and for enteric-coated or modified release | Cmax, double peaks, VBE variability | System physiology with variability; the client supplies only the dosing conditions. In PK-Sim paediatric models, gastric emptying time and specific intestinal permeability were the most sensitive parameters and solubility was minor [115]. Gastric emptying dominated diclofenac EC and furosemide PK [110] | [110, 115, 123, 124] |
| 28 | **Small-intestine and colon transit times** | **MEDIUM–HIGH** for BCS III, modified release and colonic absorption | Extent of absorption | System parameters. A PK-Sim metformin–glyburide model was most sensitive to GI pH and transit times [118]. Transit was the most sensitive parameter in monkeys [114] | [114, 118, 125] |
| 29 | **GI fluid volumes, pH, bile** | **MEDIUM–HIGH** for poorly soluble drugs | Dissolution in vivo | System parameters. Small-intestine water by MRI: 105 ± 72 mL fasted vs 54 ± 41 mL fed, held in separate pockets [122]. EMA questioned undocumented changes to the default fluid fraction [2] | [2, 122] |
| 30 | **Population** (paediatric, achlorhydria, bariatric) | **HIGH** when the question involves that population | Bridging to special populations | Physiology changes; requires a mechanistic dissolution model [2] | [2, 44] |

---

## 2. Converting Caco-2 / PAMPA permeability for PBPK use

**Why direct use is wrong:**

1. **Different scales.** Caco-2 Papp of completely absorbed drugs is above about 1×10⁻⁶ cm/s [84]. Human jejunal Peff of metoprolol (fraction absorbed about 90%) is 1.34×10⁻⁴ cm/s [2]. The two scales differ by about two orders of magnitude and are linked only through an empirical, usually log-linear, calibration [81–85].
2. **Lab-to-lab variability.** Between labs, log-Papp RMSE reached 0.581 for 10 compounds with known Peff. Fraction absorbed was predicted best (RMSE 0.128) only when the calibration used the *same* lab's Papp values [86]. Any calibration therefore belongs to one laboratory.
3. **Unstirred water layer.** In unstirred PAMPA it is about 2000 µm, about 40 times thicker than in vivo, so it must be corrected for or high-permeability compounds look UWL-limited [87]. PAMPA measures passive transcellular transport only.
4. **Biology.** Caco-2 cells are colonic in origin, with different tight junctions and transporter expression. An efflux ratio >2 does not mean efflux limits absorption in vivo [2].
5. **Biorelevant donor media.** Micelle entrapment biases Papp: for danazol, Papp falls as bile-salt concentration rises. Use free concentrations [2].
6. **Large or lipophilic compounds** (beyond Rule of 5): low recovery and non-specific binding make standard assays unreliable [93].
7. **Excipient effects.** Caco-2 over-predicts them; rat perfusion was considered more reliable [1, 2].
8. **Regional differences.** Jejunal Peff does not equal ileal or colonic permeability. A surface-area correction is one option [89]; colonic permeability is lower for low-permeability drugs [2].

**Recommended practice** (workshop consensus [2]; supported by [86, 88, 90]):
- Use an **in-house calibration curve** built from reference compounds with low, moderate and high permeability, and include a calibrator in every run. Metoprolol or minoxidil are used as the high/low dividers [2]. Examples: Beran 2025 used 16 references in MDCK knockout cells with R² > 0.8 [90]; Lee 2017 used 10 references [86].
- **Estimate bottom-up first, then confirm** against informative clinical PK (an oral solution). If the Caco-2-based value fails, optimising within a justified range is acceptable but must be flagged. EMA preferred a bottom-up Peff for lesinurad [2].
- **Gut metabolism confounds fitting Peff from PK**; predict it mechanistically [2].
- **Confidence is high for high-permeability compounds and low for low and moderate ones** [2].

**PK-Sim specifics.**
- The target parameter is "Specific intestinal permeability (transcellular)" in cm/min (verified).
- Its default value comes from a semi-empirical equation using lipophilicity and molecular weight, trained on 111 drugs with known fraction absorbed [108, 109].
- OSP models often fit it to clinical data. The ketoconazole snapshot has separate fitted values for fasted and fed ("Fit fasted", "Fit fed").
- *Not verified:* the exact relationship between PK-Sim's specific permeability and Lennernäs human jejunal Peff, given PK-Sim's own surface-area assumptions. **Do not paste a human Peff in as if it were the PK-Sim parameter** until the OSP documentation confirms the definition. Calibrate instead, for example by fitting the PK-Sim parameter for reference drugs and regressing those values against their Papp.

---

## 3. Common pitfalls in PBBM data

| Pitfall | Consequence | Detect / remedy | Sources |
|---|---|---|---|
| **Using QC media only** (pH 6.8 + SLS, sink conditions) | The method is not biopredictive; this was a top-5 rejection reason in 2023 | Require biorelevant or multi-pH data matched to the question | [1, 2, 5] |
| **Sink vs non-sink** | Sink conditions hide solubility limits; supersaturating products need non-sink tests | Compute a sink index; derive the P-PSD under non-sink conditions | [32, 53] |
| **Coning / sedimentation in USP2** | Biased dissolution rate and extent | Use hydrodynamics/coning models (166 experiments, 18 drugs) [47]; z-factor pitfalls [48] | [2, 47, 48] |
| **Disintegration lag not removed** | The particle-model fit is wrong | Subtract the lag or model disintegration | [2, 48, 58] |
| **Drug-substance PSD used as the product's surface area** | 31% under-prediction | Fit a P-PSD to dissolution and validate it in ≥3 media | [2, 32, 34] |
| **Bulk instead of surface solubility** | 48% over-prediction | Measure the final pH and compute surface pH | [32, 50, 51] |
| **Final pH and common ions not reported** | Wrong solubility | Record start and final pH and the medium composition | [2] |
| **Batches tested under different conditions** (paddle speed) or **PSD missing for some batches** | Fluconazole case judged of limited value | Enforce the same method across batches | [2] |
| **No reference-product or non-BE/variant data** | 14% of rejections | Request variants at the extremes of CMAs/CPPs; alternatives are fed/fasted or PPI PK [5] | [1, 5] |
| **Over-fitting or non-identifiability** | e.g. the lesinurad *dose* was cut to 352 mg to fit the data, which EMA rejected | Keep a parameter history and justify every change from the default | [2] |
| **VBE variability too narrow** (no within-subject variability; 8-subject populations) | Regulators questioned the conclusions | Include within- and between-subject variability and compare with observed variability | [1, 2, 41] |
| **Weibull used to extrapolate** to food, ARA or paediatrics | Not mechanistic | Use a P-PSD or z-factor particle model | [2] |
| **Z-factor fitted in surfactant media** | Wrong diffusivity | Use a P-PSD with micelle terms | [2] |
| **Precipitation rate taken directly from harsh in vitro tests** | Over-predicts precipitation; interlab variability is real | Use in vitro tests to rule out precipitation; fit the rate to PK | [2, 35, 78, 79] |
| **Ignoring excipient effects on permeability or transit for BCS III** | Unexplained BE failures | Q1/Q2 comparison and flags for functional excipients | [95, 97, 102, 103] |
| **Degradation or form change in the dissolution vessel** | Bell-shaped curves | Run a stability check | [2] |
| **Model multiplicity** (several models for one drug) | Regulator concern | Version the model and use one model across uses | [2] |

---

## 4. What regulators and the 2019–2025 workshops say about data for PBBM

**United States (FDA).**
- Draft guidance: *The Use of Physiologically Based Pharmacokinetic Analyses — Biopharmaceutics Applications for Oral Drug Product Development, Manufacturing Changes, and Controls* (2020; date from my knowledge).
- FDA reported about **50 NDA/ANDA/IND submissions with PBBM, 48% acceptable**. SUPAC uses rose from 5% to 36% after the guidance [1].
- Validation is risk-based and fit for purpose, should use **PK from batches with unacceptable bioavailability**, and needs **acceptance criteria set in advance** [1].
- On the draft guidance's 10% average absolute prediction error (AAPE) criterion: 24% of survey respondents found it adequate, 63% wanted it larger, and most voted for ≤20% [1].
- Between 2008 and 2018, 24 NDAs used absorption modelling to set dissolution and API PSD specifications [13].

**EMA.**
- The **2018 PBPK reporting guideline** sets no PBBM acceptance criteria; the sponsor must pre-define them [4].
- As of 2023, fewer than 5 PBBM cases had been reviewed. EMA fills in a credibility matrix (model influence, decision consequence) [2].
- Early scientific advice is recommended, and EMA described where PBBM content belongs in the eCTD [4].

**MHRA** [4]:
- clearly stated objectives;
- high-quality solubility and permeability data;
- predicted parameters only with sensitivity analysis;
- justification of the dissolution input method (Z-factor or P-PSD);
- a non-BE batch for validation;
- pre-specified acceptance criteria;
- an account of variability in VBE.

**Health Canada.** A 2021 pharmacometrics policy statement; a 2-fold increase in IVIVC/PBBM submissions; recurring deficiencies were unclear objectives and unjustified dissolution inputs [1, 4].

**ANVISA.** Six cases in 2020–22: 2 approved, 2 denied, 1 withdrawn, 1 treated as informative. Problems: CMA/CPP/CQA understanding, missing IV data, and variability [1].

**PMDA.** Set up a modelling and simulation project team and accepted a polymorphic-impurity limit via VBE [1, 4].

**ICH guidelines.**
- **ICH M13A:** a validated PBPK absorption model or PBBM may justify a fasted or fed BE design and assess pH-dependency risk with VBE [4, 20].
- **ICH M15 (MIDD general principles):** a draft when the template was written [5]; *check its current status*.
- **ICH M9 (BCS III):** the test product must match the reference excipients, with cumulative differences ≤10% [105].

**Workshop consensus and survey findings.**
- About **two-thirds of PBBM submissions were rejected** in both 2019 and 2023 [1, 5]. The 2023 top-5 reasons were: inadequate parameterisation; inadequate validation; no agreement on validation criteria; no non-BE or fit-for-purpose clinical data; and a non-biopredictive dissolution method [5].
- **Data to submit:** at least 3 dissolution methods on one batch, with full conditions and micelle characterisation; surface solubility; pH–solubility from pH 1–8 with start and final pH; amorphous solubility measured with the polymer present; permeability with the calibration set; and precipitation evidence [2].
- **VBE practice:** the number of subjects should match the clinical BE study. About 10 trials is the common choice, although regulators have asked for 100–200. Subjects are sampled from a virtual population of 1000–5000. Within-subject variability is needed [1, 4, 5].
- **Report template:** 8 sections and a table of CMA/CPP variants per dosage form [5].

---

## 5. Product ideas for client-delivery ingestion

1. **Structured intake dossier** with these sections:
   - **Drug substance:** form, pKa, logP/logD, solubility–pH with final pH, biorelevant solubility, PSD with method and per-batch distribution, density, permeability with the calibration set.
   - **Drug product:** composition with a functional class and mg/unit for each excipient; strength; process; disintegration.
   - **Dissolution:** unit-level data, method metadata, batch IDs, and the reference product tested side by side.
   - **Clinical:** PK per batch, IV or solution PK, food and ARA studies, non-BE batches.
   - **Question of interest and context of use.**

   Every value should carry its provenance: document, page, method and unit.
2. **Absorption-regime triage.** Calculate dose number, sink index and a critical mass-to-solubility check [108] before building the model, to tell the user which inputs are critical for this compound.
3. **Excipient classifier.** Group excipients into sugar alcohols, surfactants, pH modifiers, disintegrants, polymers and lipids, and flag:
   - test-versus-reference Q1/Q2 differences, especially for BCS III;
   - mg-per-dose totals against SME-set thresholds. Literature values such as <400 mg for sugar alcohols [96] stay **UNVERIFIED** until SMEs approve them; per CLAUDE.md, any threshold put in a ruleset needs that approval and a version bump.
4. **Dissolution QC engine.** Check:
   - number of units and the f2 preconditions (*verify against the guidance text*);
   - plateau below assay, bell-shaped curves, likely coning;
   - an apparent disintegration lag;
   - whether all batches were tested under the same conditions;
   - whether a reference product was tested.
5. **Dissolution-method decision tree.** Weibull only when the question stays within the tested physiology. Otherwise require a P-PSD fit (repository `ParticleBins`), fitting from the minimum number of bins upward and validating in ≥3 media, with AFE/AAFE reported [2]. Lint80 and table release are not supported by the repository builder (comment in `formulations.py`); *their PK-Sim names are not verified*.
6. **Permeability module.** Refuse to map a raw Papp directly to the PK-Sim parameter. Require the lab's reference set, store the calibration, and label any fitted value "fitted" in its ValueOrigin.
7. **Automatic gap requests.** Ask the client for:
   - reference product data;
   - variant or non-BE batches;
   - IV or solution PK;
   - biorelevant solubility;
   - per-batch PSD;
   - final pH;
   - unit-level dissolution;
   - transfer tests for weak bases (pKa above about 5 with a solubility drop between pH 1–2 and pH 6.5);
   - pHmax for salts;
   - amorphous solubility for ASDs.
8. **Context-only store with triggers.** A process change, hardness or full excipient list triggers a request for dissolution of the affected batches rather than a parameter.
9. **Credibility and report scaffolding.** Pre-fill the credibility matrix (question of interest, context of use, model influence, decision consequence) and the 8-section PBBM template [5]. Keep a parameter-change history [2].
10. **VBE presets.** Number of subjects equal to the clinical study, ≥10 trials (option for 100–200), explicit within- and between-subject variability; evaluate OSP's open-source VBEToolbox [42].

---

## References

According to PubMed (DOIs as links) unless marked as Consensus-only.

1. Mackie 2024 Mol Pharm, PMID 38600804, [doi](https://doi.org/10.1021/acs.molpharmaceut.4c00202) — full text read
2. Pepin 2024 Mol Pharm, PMID 38946085, [doi](https://doi.org/10.1021/acs.molpharmaceut.4c00526) — full text read
3. Heimbach 2024 Mol Pharm, PMID 39348508, [doi](https://doi.org/10.1021/acs.molpharmaceut.4c00758)
4. Tannergren 2025 Mol Pharm, PMID 39680866, [doi](https://doi.org/10.1021/acs.molpharmaceut.4c01148) — full text read
5. Arora 2025 Mol Pharm, PMID 40300064, [doi](https://doi.org/10.1021/acs.molpharmaceut.5c00225) — full text read
6. McAllister 2026 Pharmaceutics, PMID 42198260, [doi](https://doi.org/10.3390/pharmaceutics18050566)
7. Pepin 2021 J Pharm Sci, PMID 32380182, [doi](https://doi.org/10.1016/j.xphs.2020.04.021)
8. Pepin 2021 J Pharm Sci, PMID 32956678, [doi](https://doi.org/10.1016/j.xphs.2020.09.021)
9. Parrott 2021 J Pharm Sci, PMID 33058891, [doi](https://doi.org/10.1016/j.xphs.2020.09.058)
10. Mitra 2021 J Pharm Sci, PMID 33152375, [doi](https://doi.org/10.1016/j.xphs.2020.10.059)
11. Heimbach 2019 AAPS J, PMID 30746576, [doi](https://doi.org/10.1208/s12248-019-0298-x)
12. Anand 2022 Pharm Res, PMID 35585448, [doi](https://doi.org/10.1007/s11095-022-03280-4)
13. Wu 2021 AAPS J, PMID 33619657, [doi](https://doi.org/10.1208/s12248-021-00564-2)
14. Wu 2023 Pharm Res, PMID 36076007, [doi](https://doi.org/10.1007/s11095-022-03373-0)
15. Wu 2023 Pharm Res, PMID 35840856, [doi](https://doi.org/10.1007/s11095-022-03319-6)
16. Zhang 2017 CPT PSP, PMID 28571121, [doi](https://doi.org/10.1002/psp4.12204)
17. Wu 2023 CPT PSP, PMID 36530026, [doi](https://doi.org/10.1002/psp4.12907)
18. Wu 2024 AAPS J, PMID 38267737, [doi](https://doi.org/10.1208/s12248-024-00886-x)
19. Cheng 2025 Pharm Res, PMID 40155500, [doi](https://doi.org/10.1007/s11095-025-03849-9)
20. Pal 2025 Pharm Res, PMID 40467912, [doi](https://doi.org/10.1007/s11095-025-03866-8)
21. Tsakalozou 2023 AAPS J, PMID 37783902, [doi](https://doi.org/10.1208/s12248-023-00862-x)
22. Kollipara 2023 AAPS PharmSciTech, PMID 36759492, [doi](https://doi.org/10.1208/s12249-023-02521-y)
23. Kollipara 2024 J Pharm Sci, PMID 38043684, [doi](https://doi.org/10.1016/j.xphs.2023.11.030)
24. Ahmed 2023 AAPS J, PMID 37498474, [doi](https://doi.org/10.1208/s12248-023-00837-y)
25. Kostewicz 2014 Eur J Pharm Sci, PMID 24060672, [doi](https://doi.org/10.1016/j.ejps.2013.09.008)
26. Raines 2023 AAPS J, PMID 37936002, [doi](https://doi.org/10.1208/s12248-023-00865-8)
27. Heimbach 2021 J Pharm Sci, PMID 34551349, [doi](https://doi.org/10.1016/j.xphs.2021.09.017)
28. Kourentas 2023 AAPS J, PMID 36788163, [doi](https://doi.org/10.1208/s12248-023-00787-5)
29. Laisney 2022 J Pharm Sci, PMID 34678270, [doi](https://doi.org/10.1016/j.xphs.2021.10.017)
30. Bhattiprolu 2022 J Pharm Sci, PMID 36096285, [doi](https://doi.org/10.1016/j.xphs.2022.09.003)
31. Pepin 2016 Mol Pharm, PMID 27438964, [doi](https://doi.org/10.1021/acs.molpharmaceut.6b00497)
32. Pepin 2019 Eur J Pharm Biopharm (Part I), PMID 31306753, [doi](https://doi.org/10.1016/j.ejpb.2019.07.014)
33. Pepin 2019 Eur J Pharm Biopharm (Part II), PMID 31306750, [doi](https://doi.org/10.1016/j.ejpb.2019.07.011)
34. Zhou 2023 Pharm Res, PMID 35478298, [doi](https://doi.org/10.1007/s11095-022-03268-0)
35. Pepin 2023 Pharm Res, PMID 36002614, [doi](https://doi.org/10.1007/s11095-022-03339-2)
36. Paixão 2025 Pharmaceutics, PMID 40143045, [doi](https://doi.org/10.3390/pharmaceutics17030382)
37. Wang 2024 AAPS J, PMID 38862807, [doi](https://doi.org/10.1208/s12248-024-00938-2)
38. Saadeddin 2024 AAPS J, PMID 38267790, [doi](https://doi.org/10.1208/s12248-024-00888-9)
39. Kambayashi 2022 J Pharm Sci, PMID 34390740, [doi](https://doi.org/10.1016/j.xphs.2021.08.008)
40. Loisios-Konstantinidis 2020 Eur J Pharm Sci, PMID 31783158, [doi](https://doi.org/10.1016/j.ejps.2019.105170)
41. Bego 2022 AAPS J, PMID 34988679, [doi](https://doi.org/10.1208/s12248-021-00672-z)
42. Hamadeh 2025 CPT PSP, PMID 40990143, [doi](https://doi.org/10.1002/psp4.70115)
43. Kollipara 2024 Pharmaceuticals, PMID 39065727, [doi](https://doi.org/10.3390/ph17070876)
44. Doki 2017 Eur J Pharm Sci, PMID 28774813, [doi](https://doi.org/10.1016/j.ejps.2017.07.035)
45. de la Cruz Cruz 2026 AAPS J, PMID 42864569, [doi](https://doi.org/10.1208/s12248-026-01319-7)
46. Bi 2024 AAPS PharmSciTech, PMID 39690309, [doi](https://doi.org/10.1208/s12249-024-03006-2)
47. Pepin 2022 J Pharm Sci, PMID 34666045, [doi](https://doi.org/10.1016/j.xphs.2021.10.006)
48. Hofsäss 2020 J Pharm Sci, PMID 32497594, [doi](https://doi.org/10.1016/j.xphs.2020.05.019)
49. Cristofoletti 2019 J Pharm Sci, PMID 31539541, [doi](https://doi.org/10.1016/j.xphs.2019.09.012)
50. Hens 2022 AAPS J, PMID 34982285, [doi](https://doi.org/10.1208/s12248-021-00663-0)
51. Cámara-Martinez 2022 Int J Pharm, PMID 34973409, [doi](https://doi.org/10.1016/j.ijpharm.2021.121415)
52. Salehi 2020 Mol Pharm, PMID 32886520, [doi](https://doi.org/10.1021/acs.molpharmaceut.0c00614)
53. Sun 2016 J Pharm Sci, PMID 27174227, [doi](https://doi.org/10.1016/j.xphs.2016.03.024)
54. Xie 2015 Eur J Pharm Sci, PMID 25315411, [doi](https://doi.org/10.1016/j.ejps.2014.10.002)
55. Muselík 2021 Pharmaceutics, PMID 34683995, [doi](https://doi.org/10.3390/pharmaceutics13101703)
56. Stevens 2015 AAPS J, PMID 25669756, [doi](https://doi.org/10.1208/s12248-015-9723-y)
57. Oktay 2026 Eur J Pharm Sci — Consensus only: [link](https://consensus.app/papers/details/w:0a6b8d72-195d-4998-8829-b74841eb5c84/?utm_source=claude_desktop)
58. Nakamura 2022 Eur J Pharm Biopharm, PMID 36154905, [doi](https://doi.org/10.1016/j.ejpb.2022.09.017)
59. Radwan 2012 Biopharm Drug Dispos, PMID 22782559, [doi](https://doi.org/10.1002/bdd.1798)
60. Brouwers 2011 Eur J Pharm Biopharm, PMID 21055466, [doi](https://doi.org/10.1016/j.ejpb.2010.10.009)
61. Dahlgren 2021 Eur J Pharm Biopharm, PMID 33872761, [doi](https://doi.org/10.1016/j.ejpb.2021.04.005)
62. Jones 2006 Clin Pharmacokinet, PMID 17112297, [doi](https://doi.org/10.2165/00003088-200645120-00006)
63. Parrott 2009 AAPS J, PMID 19184451, [doi](https://doi.org/10.1208/s12248-008-9079-7)
64. Riedmaier 2020 AAPS J, PMID 32981010, [doi](https://doi.org/10.1208/s12248-020-00508-2) — 30 compounds: 15 high, 8 moderate, 7 low prediction confidence
65. Wagner 2021 AAPS J, PMID 34142242, [doi](https://doi.org/10.1208/s12248-021-00601-0)
66. Pepin 2021 AAPS J, PMID 33398593, [doi](https://doi.org/10.1208/s12248-020-00548-8)
67. Li 2018 CPT PSP, PMID 29168611, [doi](https://doi.org/10.1002/psp4.12260) — about 50% within 1.25-fold, 75% within 2-fold
68. Stamatopoulos 2023 Pharmaceutics, PMID 36839843, [doi](https://doi.org/10.3390/pharmaceutics15020521)
69. Rudolph 2025 Eur J Pharm Sci, PMID 39983931, [doi](https://doi.org/10.1016/j.ejps.2025.107047)
70. Holzem 2024 J Pharm Sci, PMID 39059554, [doi](https://doi.org/10.1016/j.xphs.2024.07.017)
71. Fink 2020 Eur J Pharm Sci, PMID 32562690, [doi](https://doi.org/10.1016/j.ejps.2020.105431)
72. Mitra 2020 J Pharm Sci, PMID 31778721, [doi](https://doi.org/10.1016/j.xphs.2019.11.017)
73. Dong 2020 CPT PSP, PMID 32633893, [doi](https://doi.org/10.1002/psp4.12541)
74. Kesisoglou 2018 AAPS PharmSciTech, PMID 29872977, [doi](https://doi.org/10.1208/s12249-018-1059-3)
75. Chirumamilla 2021 Pharmaceutics, PMID 34452130, [doi](https://doi.org/10.3390/pharmaceutics13081169)
76. Kostewicz 2004 J Pharm Pharmacol, PMID 14980000, [doi](https://doi.org/10.1211/0022357022511)
77. Kambayashi 2016 Eur J Pharm Biopharm, PMID 27012902, [doi](https://doi.org/10.1016/j.ejpb.2016.03.020)
78. Berben 2019 Eur J Pharm Biopharm, PMID 31051249, [doi](https://doi.org/10.1016/j.ejpb.2019.04.017)
79. O'Dwyer 2019 J Pharm Pharmacol, PMID 29956338, [doi](https://doi.org/10.1111/jphp.12951)
80. Patel 2018 J Pharm Sci — Consensus only: [link](https://consensus.app/papers/details/w:326d18b8-c6e1-4e9e-95be-b21c4d374008/?utm_source=claude_desktop)
81. Lennernäs 1997 J Pharm Pharmacol, PMID 9255703, [doi](https://doi.org/10.1111/j.2042-7158.1997.tb06084.x)
82. Lennernäs 1998 J Pharm Sci, PMID 9548891, [doi](https://doi.org/10.1021/js970332a)
83. Dahlgren 2015 J Pharm Sci, PMID 25410736, [doi](https://doi.org/10.1002/jps.24258)
84. Artursson 1991 Biochem Biophys Res Commun, PMID 1673839 (citation matcher only)
85. Yee 1997 Pharm Res, PMID 9210194 (citation matcher only)
86. Lee 2017 Eur J Pharm Biopharm, PMID 28088633, [doi](https://doi.org/10.1016/j.ejpb.2016.12.027)
87. Ruell 2003 Eur J Pharm Sci, PMID 14659483, [doi](https://doi.org/10.1016/j.ejps.2003.08.006)
88. Tsuchitani 2022 Int J Clin Pharmacol Ther, PMID 35343429, [doi](https://doi.org/10.5414/CP204172)
89. Olivares-Morales 2015 AAPS J, PMID 25986421, [doi](https://doi.org/10.1208/s12248-015-9758-0)
90. Beran 2025 Mol Pharm, PMID 40914889, [doi](https://doi.org/10.1021/acs.molpharmaceut.5c00755)
91. Koziolek 2023 Pharmaceutics, PMID 37896157, [doi](https://doi.org/10.3390/pharmaceutics15102397)
92. O'Shea 2022 Eur J Pharm Sci, PMID 34954051, [doi](https://doi.org/10.1016/j.ejps.2021.106098)
93. Muschong 2024 Pharmaceutics — Consensus only: [link](https://consensus.app/papers/details/w:1989c7ee-e228-4602-a05f-3aed1e9f4ebd/?utm_source=claude_desktop); see also Huth 2021 J Pharm Sci — Consensus only: [link](https://consensus.app/papers/details/w:bef4c024-3094-427d-afb4-2d9626340f14/?utm_source=claude_desktop)
94. Dahlgren 2019 Pharmaceutics, PMID 31412551 (citation matcher only)
95. Chen 2007 Pharm Res, PMID 17048115, [doi](https://doi.org/10.1007/s11095-006-9120-4)
96. Yamane 2021 J Pharm Sci, PMID 32470348, [doi](https://doi.org/10.1016/j.xphs.2020.05.013)
97. García-Arieta 2014 Eur J Pharm Sci, PMID 25236823, [doi](https://doi.org/10.1016/j.ejps.2014.09.004)
98. Metry 2022 AAPS J, PMID 34988701, [doi](https://doi.org/10.1208/s12248-021-00670-1)
99. Flanagan 2019 Eur J Pharm Biopharm, PMID 31128247, [doi](https://doi.org/10.1016/j.ejpb.2019.05.020)
100. Martinez 2022 AAPS J, PMID 35501528, [doi](https://doi.org/10.1208/s12248-022-00713-1)
101. Matsui 2025 Mol Pharm, PMID 40062405, [doi](https://doi.org/10.1021/acs.molpharmaceut.4c01309)
102. González-Álvarez 2022 Pharmaceutics, PMID 36559059, [doi](https://doi.org/10.3390/pharmaceutics14122565)
103. Ruiz-Picazo 2019 Pharmaceutics, PMID 31835294, [doi](https://doi.org/10.3390/pharmaceutics11120663)
104. Bermejo 2019 Pharmaceutics, PMID 30884755, [doi](https://doi.org/10.3390/pharmaceutics11030122)
105. Fang 2025 J Pharm Sci, PMID 41115505, [doi](https://doi.org/10.1016/j.xphs.2025.104030)
106. Al Shoyaib 2026 AAPS J, PMID 43073617, [doi](https://doi.org/10.1208/s12248-026-01339-3)
107. Gonzalez-Alvarez 2024 Pharmaceutics, PMID 38543284, [doi](https://doi.org/10.3390/pharmaceutics16030390)
108. Willmann 2004 J Med Chem, PMID 15267240, [doi](https://doi.org/10.1021/jm030999b)
109. Thelen 2011 J Pharm Sci, PMID 21993815, [doi](https://doi.org/10.1002/jps.22726)
110. Thelen 2012 J Pharm Sci, PMID 22125236, [doi](https://doi.org/10.1002/jps.22825)
111. Willmann 2009 J Pharm Pharmacol, PMID 19589231, [doi](https://doi.org/10.1211/jpp/61.07.0008) — variability in effective surface area was the largest contributor to absorption variability
112. Willmann 2010 Eur J Pharm Biopharm, PMID 20554023, [doi](https://doi.org/10.1016/j.ejpb.2010.06.003)
113. Willmann 2012 J Pharm Pharmacol, PMID 22686345, [doi](https://doi.org/10.1111/j.2042-7158.2012.01534.x) — PK-Sim dissolution integration
114. Willmann 2007 Pharm Res, PMID 17373575, [doi](https://doi.org/10.1007/s11095-007-9247-y)
115. Liu 2021 J Clin Pharmacol, PMID 34185902, [doi](https://doi.org/10.1002/jcph.1845)
116. Vrenken 2025 Eur J Pharm Sci (Part 1), PMID 40505839, [doi](https://doi.org/10.1016/j.ejps.2025.107164)
117. Vrenken 2025 Eur J Pharm Sci (Part 2), PMID 40615096, [doi](https://doi.org/10.1016/j.ejps.2025.107189)
118. Zhao 2025 Pharmaceutics, PMID 41155987, [doi](https://doi.org/10.3390/pharmaceutics17101352)
119. Denninger 2023 Pharmaceutics, PMID 37514164, [doi](https://doi.org/10.3390/pharmaceutics15071978) — biphasic dissolution data used in PK-Sim
120. Winter 2025 Eur J Pharm Biopharm, PMID 40706964, [doi](https://doi.org/10.1016/j.ejpb.2025.114815) — PK-Sim absorption model extended for bile and excipient solubilisation
121. Lippert 2019 CPT PSP, PMID 31671256, [doi](https://doi.org/10.1002/psp4.12473)
122. Schiller 2005 Aliment Pharmacol Ther, PMID 16268972, [doi](https://doi.org/10.1111/j.1365-2036.2005.02683.x)
123. Higaki 2008 Eur J Pharm Biopharm, PMID 18434110, [doi](https://doi.org/10.1016/j.ejpb.2008.02.022)
124. Langguth 1994 Biopharm Drug Dispos, PMID 7888602, [doi](https://doi.org/10.1002/bdd.2510150902)
125. Ni 2017 AAPS J, PMID 28357656, [doi](https://doi.org/10.1208/s12248-017-0075-7)
126. Kesisoglou 2016 J Pharm Sci, PMID 26886317, [doi](https://doi.org/10.1016/j.xphs.2015.11.034) — industry absorption-modelling case studies

**Not taken from the literature search, so verify against the source documents before relying on them:**
- the f2 rules (12 units, CV limits);
- the FDA 2020 and EMA 2018 guidance titles and reference numbers;
- the current status of ICH M15;
- whether PK-Sim has a meal module or a Lint80 formulation, and their parameter names;
- whether PK-Sim's specific intestinal permeability can be mapped directly to human Peff.
