# Requirement lists per context of use: drafts for the owner's review (2026-11-24)

**Status:** DRAFT, UNVERIFIED. Nothing live reads these lists. They answer decision **D5** of
`docs/plans/2026-11-24-data-story-next-phase.md` (§6 and §11): "draft the requirement lists from the literature as
UNVERIFIED drafts. They become templates only after my review. Do not change the locked templates."

**Where they are:** `packages/pbpk-domain/src/pbpk_domain/requirement_drafts/context_of_use/`, one YAML file per
context of use, plus `core.yaml` and `context_only.yaml`. The locked templates in `pbpk_domain/requirements/` are
unchanged.

**What they come from:** the three literature reviews of 2026-11-24 in `docs/research/`:
- the **regulatory review**, `2026-11-24-regulatory-data-by-context-of-use.md` (the main source: its per-CoU tables
  with R/U/C/O/N statuses);
- the **PBBM review**, `2026-11-24-pbbm-absorption-inputs.md` (formulation and in vitro inputs, the context-only
  material, the gap requests);
- the **clinical-data review**, `2026-11-24-clinical-pk-data-curation.md` (observed-data items and study metadata).

Every item names its sources (PMID, DOI or guidance name, as the reviews cite them). A test checks that every PMID and
DOI appears in one of the three reviews, so none is invented. Where a review row cites no primary source, the item
cites the review section and says so.

**How to review.** Each table below has an empty **Note** column. Write "OK", a different status, a change to the
trigger, or "drop". Section 4 lists the questions the SME must answer before any of this becomes a template.

---

## 1. Numbers at a glance

147 items in 12 files. R = required, U = usually needed, C = conditional, O = optional, N = not needed.

| File | Items | R | U | C | O | N | Items the Data room cannot fully place yet (section 6) |
|---|---|---|---|---|---|---|---|
| `core.yaml` | 19 | 9 | 5 | 4 | 1 | 0 | 1 |
| `ddi_victim.yaml` | 12 | 3 | 3 | 5 | 0 | 1 | 1 |
| `ddi_perpetrator.yaml` | 11 | 4 | 1 | 4 | 0 | 2 | 0 |
| `transporter_ddi.yaml` | 8 | 3 | 1 | 3 | 1 | 0 | 2 |
| `food_effect.yaml` | 12 | 5 | 3 | 2 | 1 | 1 | 2 |
| `pediatric.yaml` | 14 | 4 | 2 | 4 | 3 | 1 | 1 |
| `organ_impairment.yaml` (renal 10, hepatic 10) | 20 | 4 | 8 | 2 | 1 | 5 | 0 |
| `pbbm_bridging_vbe.yaml` | 22 | 9 | 6 | 6 | 0 | 1 | 5 |
| `acid_reducing_agents.yaml` | 7 | 2 | 3 | 1 | 0 | 1 | 1 |
| `fih_dose_prediction.yaml` | 8 | 5 | 1 | 0 | 0 | 2 | 1 |
| `special_populations.yaml` (pregnancy 5, geriatrics 3, ethnicity 2) | 10 | 3 | 4 | 2 | 1 | 0 | 1 |
| `context_only.yaml` | 4 | — | — | — | — | 4 (kept as context) | 0 |

## 2. How the drafts work

- **One status per item, per context of use** (plan §6.3):
  - **Required**: shown as missing when absent.
  - **Usually needed**: becomes required when the item's condition holds. By default that is **model influence
    high**: the model replaces a study or drives the label. The M15 influence rating the project already records can
    decide this.
  - **Conditional**: required only when its **trigger** fires on the compound, the product or the question. Otherwise
    it is not shown.
  - **Optional**: never shown as missing.
  - **Not needed**: listed once, folded, under "Not needed for this question, and why". A modeller who wants one turns
    it on, with a reason.
- **Triggers in two forms.** Words (`trigger_text`) and a small structure code can evaluate (`trigger`), e.g.
  `{property: salt_form, equals: true}`, combined with `any` and `all`. A trigger names only properties from the
  vocabulary in `core.yaml` (section 5). Each property says how the Data room determines it: computed from the facts and
  tables, read from the brief, or asked.
- **No invented numbers.** A trigger compares with a number only where a cited source states one; `threshold_source`
  says where. There is one such number, used in two triggers: pKa above 5, from the PBBM review ("about 5").
  Everywhere else the trigger says `threshold: SME`, and the SME sets the number (section 4.1).
- **An unknown trigger is "to ask", never "missing".** If a property is not determined yet, or the SME has not set its
  number, the item shows as a question. It never shows as missing and never as not needed.
- **Core and overrides.** Every CoU starts from `core.yaml`. A CoU file replaces a core item by naming it under
  `overrides`. Example: DDI victim makes the mass balance required, where core has it as usually needed.
- **Several CoUs combine.** For example virtual BE plus food effect. When the same item has different statuses in two
  files, the stricter status should win. That rule is for the Phase 2 wiring and is not coded here.
- **Context only** (`context_only.yaml`). The manufacturing process, tablet hardness, the full excipient list and f2
  are **stored with their provenance, never a model input, never reported missing, and never asked for**. Each one
  names the data request it triggers instead. Example: a process change between batches asks for those batches'
  dissolution and disintegration. This removes today's "manufacturing process" request from every project (plan §6.1).
- **Data room vocabulary.** Each item names what satisfies it in the room's vocabulary
  (`modeler_intake.room_specs`): `field:` names, `table:` kinds and `topic:` names. Items marked **(no room field)**
  or **(room field in part)** need a field the room does not have yet (section 6).
- **Activities and system items.** Some items are not delivery data:
  - **activities**, such as a sensitivity analysis, stated in the analysis plan;
  - **system data**, such as ontogeny or the qualification set, taken from the OSP library.

  These are never asked of the client.
- **What is not in them:** no PK-Sim name, path or unit; no default value; no acceptance threshold. A test enforces
  all three.
- **Inert:**
  - `applies_to: []` in every file;
  - the live loader (`modeler_project.requirements.load_templates`) does not list this folder;
  - no data plan, gate or live template reads the drafts. The test checks this with every application picked.
- **Where "my" comes from.** A note that says "my reading" or "my choice" marks a decision the drafter (Claude) made
  where the review was silent or ambiguous. Section 4.2 lists them all.

## 3. The items, per context of use

### 3.1 Core (every context of use starts here) (`core.yaml`, 19 items)

*Context of use:* The items every context of use starts from: the drug model's basic inputs and the observed data that train and verify it.

| Item | Status | When | Why | Note |
|---|---|---|---|---|
| `core.molecular_weight` Molecular weight | Required | — | Every amount and concentration in the model is converted with it. | |
| `core.lipophilicity` Lipophilicity (logP or logD with its pH) | Required | — | It drives tissue distribution and, when no permeability is measured, the predicted permeability. | |
| `core.pka` pKa values and their type (acid or base), or a statement that the drug is neutral | Required | — | Ionisation sets distribution and every pH-dependent step of absorption. | |
| `core.fu_plasma` Fraction unbound in plasma | Required | — | Clearance and tissue distribution act on the unbound drug. | |
| `core.blood_plasma_ratio` Blood-to-plasma concentration ratio | Required | — | It converts plasma clearance to blood clearance and relates blood and plasma assays. | |
| `core.in_vitro_clint` In vitro intrinsic clearance (hepatocytes, liver microsomes or recombinant enzymes), with Km and Vmax where saturable | Conditional | The drug is cleared at least partly by metabolism. | Clearance is scaled from these data to the whole body (IVIVE). | |
| `core.mass_balance` Mass balance (radiolabelled), metabolite profile and fraction excreted unchanged in urine | Usually | Required when model influence high (the model replaces a study or drives the label); the DDI-victim, organ-impairment and paediatric lists make it REQUIRED | It splits clearance between metabolism, urine and bile; methods without a radiolabel can miss metabolites. | |
| `core.iv_pk` Intravenous PK (or an IV microtracer) | Usually | Required when model influence high (the model replaces a study or drives the label) | It is the reference for disposition; without it gut and liver extraction cannot be told apart for a poorly soluble drug. | |
| `core.fasted_oral_pk` Fasted oral PK (single and multiple ascending dose), full concentration-time profiles | Required | — | These profiles train and verify the base model and show whether exposure is proportional to dose. | |
| `core.study_metadata` Study metadata: population, dose and regimen, formulation, fed or fasted and the meal, matrix, analyte (total or unbound, parent or metabolite), lower limit of quantification | Required | — | Observed data cannot be simulated faithfully without the conditions they were measured under. | |
| `core.observed_statistic` The statistic of each observed value (arithmetic or geometric mean, or median), its spread (SD, CV or SEM) and n per time point | Required | — | A simulated summary must be of the same statistic as the observed one, or the comparison is silently wrong. | |
| `core.blq_handling` Samples below the limit of quantification kept as such, with the limit per assay and how they were treated in any means | Usually | Required when model influence high (the model replaces a study or drives the label), or individual data with more than a small share of BLQ samples are fitted (the review's decision rules; the share is the SME's) | Dropping or replacing values below the limit biases the terminal phase and the distribution parameters. | |
| `core.actual_sampling_times` Actual sampling and dosing times beside the nominal ones | Conditional | The delivery has subject-level concentrations (individual data are fitted or the sponsor's NCA is re-computed). | Individual data are fitted and NCA is computed on actual times; nominal times bias the estimates where the profile curves sharply. | |
| `core.exclusions_flagged` Subjects and samples the sponsor excluded, each with its reason (kept as flags, never deleted) | Conditional | The delivery has subject-level concentrations. | The modeller uses the sponsor's analysis population and must know which profiles were left out and why. | |
| `core.sponsor_nca` The sponsor's NCA results and the settings behind them (integration rule, terminal-slope window, BLQ rule, time basis) | Optional | — | They let the room reproduce the sponsor's numbers and explain any difference by a setting rather than by the data. | |
| `core.external_verification` An independent (external) clinical dataset kept out of model building | Usually | Required when model influence high (the model replaces a study or drives the label) | Verification on the data the model was built on alone carries evidentiary limits. | |
| `core.permeability_calibration` The laboratory's permeability reference compounds and its calibration, with every in vitro permeability value *(room field in part)* | Conditional | An in vitro permeability value (Caco-2, MDCK or PAMPA) is supplied. | In vitro and human permeability are on different scales linked only by each laboratory's own calibration, so a raw value cannot enter the model. | |
| `core.sensitivity_analysis` Sensitivity and uncertainty analysis of the uncertain inputs | Required | — | Regulators' objections were withdrawn once sensitivity analyses were supplied. | |
| `core.platform_qualification` The platform version and its qualification for the intended use | Usually | Required when model influence high (the model replaces a study or drives the label) | EMA expects the platform to be qualified for the use the model is put to. | |

### 3.2 DDI: the drug as victim (`ddi_victim.yaml`, 12 items)

*Context of use:* Predict how much the drug's exposure changes when it is given with an inhibitor or inducer of an enzyme that clears it.

| Item | Status | When | Why | Note |
|---|---|---|---|---|
| `ddiv.fm_phenotyping` Fraction metabolised per enzyme from reaction phenotyping (recombinant enzymes; liver microsomes with selective inhibitors) | Required | — | The fraction metabolised by the affected enzyme sets the size of the interaction, and EMA did not qualify models whose fm was not justified. | |
| `ddiv.clinical_ddi_index` Clinical DDI study with a strong index inhibitor and/or inducer | Usually | Required when the model extrapolates to untested moderate or weak perpetrators for the label, or model influence is high (the model replaces a study or drives the label) | It refines the fraction metabolised in vivo and is the standard comparator for the model. | |
| `ddiv.mass_balance` Mass balance (radiolabelled), metabolite profile and fraction excreted unchanged in urine | Required | (replaces `core.mass_balance`) | It weighs the fraction metabolised against renal and biliary elimination. | |
| `ddiv.iv_pk` Intravenous PK | Usually | Required when model influence high (the model replaces a study or drives the label) (replaces `core.iv_pk`) | It separates gut-wall extraction from hepatic extraction, which an inhibitor of a gut enzyme changes differently. | |
| `ddiv.gut_wall_metabolism` Evidence for gut-wall metabolism (the intestinal enzyme's contribution) | Conditional | The drug is a CYP3A substrate. | EMA cited a missing intestinal enzyme activity as a structural flaw of DDI models for CYP3A substrates. | |
| `ddiv.auto_modulation` Auto-inhibition or auto-induction of the drug's own pathway (kinact and KI, or EC50 and Emax) | Conditional | The drug inhibits or induces an enzyme that clears it. | A missing auto-inhibition or auto-induction was a structural flaw EMA cited. | |
| `ddiv.verified_perpetrator_models` Verified models of the index perpetrators | Required | — | The default inducer model under-predicted induction, and verifying the perpetrator model was found crucial. | |
| `ddiv.pathway_qualification_set` Qualification set for the pathway (the substrates and perpetrators the platform was qualified on) | Usually | Required when model influence high (the model replaces a study or drives the label) | EMA expects the platform to be qualified on several compounds for the pathway concerned, and too few compounds was a reason for non-qualification. | |
| `ddiv.genotype_groups` PK by genotype group (poor, intermediate and extensive metabolisers) *(room field in part)* | Conditional | The drug is a CYP2D6, CYP2C9 or CYP2C19 substrate. | Drug-gene and drug-drug interactions combine for substrates of polymorphic enzymes, as in the eliglustat label. | |
| `ddiv.active_metabolites` Active or inhibitory metabolites and their PK | Conditional | The drug has an active or inhibitory metabolite. | Leaving out a metabolite's contribution was a cited limitation of submitted models. | |
| `ddiv.fed_dosing_data` Fed PK, dissolution and particle size | Conditional | The label scenario is fed dosing. | Food effect on a DDI is a separate context of use at EMA, needed only when the interaction is to be predicted under fed dosing. | |
| `ddiv.ontogeny` Enzyme and transporter ontogeny | Not needed | — | An adult DDI question does not involve maturation; a paediatric DDI question adds the paediatric list. | |

### 3.3 DDI: the drug as perpetrator (`ddi_perpetrator.yaml`, 11 items)

*Context of use:* Predict how much the drug, given at its therapeutic regimen, changes the exposure of other drugs cleared by an enzyme it inhibits or induces.

| Item | Status | When | Why | Note |
|---|---|---|---|---|
| `ddip.reversible_ki` Reversible inhibition constant (unbound, corrected for binding in the incubation) and the mechanism of inhibition | Conditional | The drug is a reversible inhibitor. | It sets the strength of the interaction. | |
| `ddip.tdi_kinact_ki` Time-dependent inhibition (kinact and KI), with the pre-incubation conditions | Conditional | The drug is a time-dependent inhibitor. | The assay conditions change the derived constants, so they must be documented with them. | |
| `ddip.induction_ec50_emax` Induction EC50 and Emax, with the calibration approach | Conditional | The drug is an inducer. | Induction is extrapolated from these data, and an FDA review reportedly rejected an in vitro calibration approach. | |
| `ddip.interaction_site_exposure` Exposure at the interaction site (unbound fraction, blood-to-plasma ratio, hepatic uptake, gut concentration from dose and solubility) | Required | — | The perpetrator acts through its concentration at the enzyme, and EMA rejected an intestinal CYP3A prediction built without it. | |
| `ddip.steady_state_pk` Clinical PK at the therapeutic regimen (steady state), with the full dosing history | Required | — | The perpetrator's own exposure over the dosing interval drives the size of the interaction. | |
| `ddip.clinical_ddi_sensitive_substrate` Clinical DDI study with a sensitive index substrate | Usually | Required when the drug is an inducer or a mixed inhibitor and inducer, the model extrapolates to other substrates for the label, or model influence is high (the model replaces a study or drives the label) | Verifying the model with a substrate that is not sensitive was judged circular. | |
| `ddip.verified_victim_models` Verified models of the index substrates | Required | — | The perpetrator model is qualified against verified substrate models. | |
| `ddip.sensitivity_on_constants` Sensitivity analysis over the ranges of the inhibition and induction constants | Required | (replaces `core.sensitivity_analysis`) | The predicted interaction can change class within a plausible range of the constant, which decides whether a clinical study is needed. | |
| `ddip.metabolites_and_net_effect` Inhibitory metabolites, and the net effect when the drug both inhibits and induces | Conditional | The drug has an active or inhibitory metabolite, or it both inhibits and induces. | Leaving out an inhibitory metabolite or the opposing mechanism was a cited omission. | |
| `ddip.own_fm` Fraction metabolised of the perpetrator's own clearance | Not needed | — | The perpetrator's own pathways do not set the effect on the victim; when the same model is also used as a victim, the DDI-victim list applies. | |
| `ddip.fed_pk_dissolution` Fed PK and dissolution | Not needed | — | The interaction is predicted for the perpetrator's systemic and gut exposure at its regimen, not for its formulation's behaviour with food. | |

### 3.4 Transporter-mediated DDI (`transporter_ddi.yaml`, 8 items)

*Context of use:* Predict a drug-drug interaction mediated by an uptake or efflux transporter, with the drug as substrate or as inhibitor.

| Item | Status | When | Why | Note |
|---|---|---|---|---|
| `tddi.transporter_kinetics` Transporter kinetics (Km and Vmax, or active intrinsic clearance) and inhibition constants (Ki or IC50), with the test system and substrate | Required | — | Transporter kinetics are scaled from these in vitro data to the body. | |
| `tddi.abundance_scaling` Transporter abundance and the empirical scaling factors used *(no room field)* | Required | — | In vitro transporter data tend to under-predict in vivo activity, so scaling factors are applied and must be justified. | |
| `tddi.extended_clearance` Contribution of transporters versus enzymes to clearance (extended clearance) | Required | — | Which step limits clearance decides whether a transporter inhibitor changes exposure; it is hard to determine and a recognised gap. | |
| `tddi.clinical_ddi_probe_inhibitor` Clinical DDI study with a probe transporter inhibitor | Usually | Required when model influence high (the model replaces a study or drives the label) | Transporter DDI predictions have under-predicted observed interactions, and EMA qualified few transporter-perpetrator uses. | |
| `tddi.endogenous_biomarker` Endogenous transporter biomarker data | Optional | — | Proposed to raise confidence in the transporter model. | |
| `tddi.renal_secretion_evidence` Renal clearance and fraction excreted unchanged, against filtration (unbound fraction times GFR), as evidence of secretion | Conditional | Renal elimination is substantial (fraction excreted unchanged above a cut-off the SME sets), or the drug is actively secreted. | It separates filtration from transporter-mediated secretion, which a renal transporter inhibitor changes. | |
| `tddi.intestinal_efflux` Intestinal efflux (P-gp or BCRP) during absorption | Conditional | The drug is a P-gp or BCRP substrate. | Missing absorption-phase mechanisms were cited as a deficiency. | |
| `tddi.transporter_genotype` PK by transporter genotype (for example SLCO1B1) *(room field in part)* | Conditional | The drug is a substrate of a polymorphic transporter (the review's example is SLCO1B1, the OATP1B1 gene). | Drug-gene interactions add to drug-drug interactions for substrates of polymorphic transporters. | |

### 3.5 Food effect (`food_effect.yaml`, 12 items)

*Context of use:* Predict how a meal changes the drug's exposure, to support or replace a clinical food-effect study or a label statement.

| Item | Status | When | Why | Note |
|---|---|---|---|---|
| `fe.fasted_clinical_pk` Fasted clinical PK with the same or a similar formulation | Required | (replaces `core.fasted_oral_pk`) | The fasted model is verified first; the fed prediction builds on it. | |
| `fe.fed_clinical_pk` Fed clinical PK (a high-fat 'anchor' study) | Usually | Required when the model is built middle-out, it extends the food effect to new formulations or doses, or model influence is high (the model replaces a study or drives the label); it may be waived for a high-confidence bottom-up mechanism | The IQ group found that middle-out models need an anchor fed study, while high-confidence bottom-up models may not. | |
| `fe.solubility_vs_ph` Aqueous solubility versus pH, with the start and final pH | Required | — | The IQ protocol builds the absorption model on it, and an unreported final pH or common-ion effect gives a wrong solubility. | |
| `fe.biorelevant_solubility` Biorelevant solubility (fasted and fed simulated gastric and intestinal fluids) and bile-micelle partitioning | Required | — | Solubilisation by bile salts is the key mechanism of a positive food effect. | |
| `fe.permeability` Permeability (Caco-2 or MDCK, converted to human permeability through the laboratory's calibration) | Required | — | The absorption model needs it, and a raw in vitro value cannot be used directly. | |
| `fe.biorelevant_dissolution_psd` Biorelevant dissolution (fasted and fed intestinal media) and particle size distribution | Usually | Required when model influence high (the model replaces a study or drives the label) | These data help when the model must predict the food effect of the product rather than of the drug substance. | |
| `fe.precipitation` Precipitation and supersaturation (two-stage or transfer test), and the full solubility profile with any common-ion effect *(room field in part)* | Conditional | A weak base with a pKa above about 5 whose solubility falls from gastric to intestinal pH (how large a fall is the SME's), or a salt. | Precipitation of weak bases and salts is the main source of low-confidence food-effect predictions. | |
| `fe.meal_and_timing` Meal composition and timing in each clinical study | Required | — | The fed physiology the model simulates is chosen from the meal and its timing. | |
| `fe.iv_pk` Intravenous PK | Optional | (replaces `core.iv_pk`) | When the food effect acts on absorption the model can be applied without IV data; the IQ group used IV only to simplify. | |
| `fe.confidence_limits` Evidence on hepatic extraction and on transporter-limited absorption | Conditional | The drug has a high hepatic extraction, or its absorption is limited by transporters. | Such drugs were left out of the IQ evaluation set, so a prediction for one carries lower confidence and must say why. | |
| `fe.disintegration` Disintegration time of the product (or capsule opening), in fasted and fed media where tested *(no room field)* | Usually | Required when disintegration is slow or changes with food (how slow is the SME's), or model influence is high (the model replaces a study or drives the label) | A slow or food-dependent disintegration delays release and must be separated from dissolution before a particle model is fitted. | |
| `fe.fm_ddi_ontogeny` Fraction metabolised, DDI data and ontogeny | Not needed | — | A food effect in adults acts on absorption, not on the enzymes or their maturation. | |

### 3.6 Paediatric extrapolation (`pediatric.yaml`, 14 items)

*Context of use:* Predict exposure in children of a target age range from a verified adult model, to select doses or support a paediatric plan or label.

| Item | Status | When | Why | Note |
|---|---|---|---|---|
| `ped.adult_model_verified` Adult data across single dose, multiple dose and DDI, against which the adult model is verified | Required | — | A paediatric extrapolation is only as good as the adult model it starts from; this is the first best-practice criterion. | |
| `ped.pathway_fractions` Elimination pathway fractions (from mass balance, in vitro data and adult DDI studies) | Required | (replaces `core.mass_balance`) | Maturation is applied pathway by pathway, so each pathway's share of clearance must be known. | |
| `ped.ontogeny` Ontogeny of the enzymes and transporters that clear the drug | Required | — | Clearance in children is scaled through the maturation of each relevant enzyme and transporter. | |
| `ped.pathway_verification_drugs` Paediatric PK of other drugs cleared by the same pathways, in the same age range | Required | — | The ontogeny of a pathway is verified with other drugs of that pathway in the target age range. | |
| `ped.renal` Renal clearance against filtration (unbound fraction times GFR), and renal transporter maturation | Conditional | Renal elimination is substantial (fraction excreted unchanged above a cut-off the SME sets). | Kidney function and renal transporters mature at their own pace, so a renally cleared drug needs its renal route split out. | |
| `ped.pediatric_pk` Paediatric PK, even sparse | Usually | Required when the model replaces a paediatric study (model influence high) | The model is validated against paediatric data whenever any exist, and the data must match the target age range. | |
| `ped.pediatric_formulation` The paediatric formulation (its bioequivalence to the adult product, salts, co-solvents) | Usually | Required when model influence high (the model replaces a study or drives the label) | A different formulation for children can change absorption independently of age. | |
| `ped.food_and_dosing_conditions` Food and dosing conditions (milk or formula, food vehicles, meal size and frequency) and the fluid volume given with the dose | Conditional | Infants are in the target population, the dose is given with milk, formula or food, the drug has a food effect in adults, or the drug is poorly soluble (read as BCS class II or IV). | Fed data are not automatically irrelevant for children; extrapolation to infants depended strongly on the adult dosing conditions. | |
| `ped.mechanistic_absorption_inputs` Biorelevant solubility and permeability (for a mechanistic absorption model) | Conditional | The drug is BCS class II, III or IV. | For a drug that is not both highly soluble and highly permeable, absorption in children depends on the child's gut and must be modelled mechanistically. | |
| `ped.allometric_crosscheck` Allometric cross-check of the predicted clearance | Optional | — | A simple allometric estimate is a safety net against a gross error of the mechanistic model. | |
| `ped.pd_target` A pharmacodynamic or receptor-occupancy target exposure *(no room field)* | Optional | — | It anchors the dose selection to the exposure that matters, as a second safety net. | |
| `ped.disease_effects` Effects of the disease on system parameters | Conditional | The target children are patients with a disease that changes physiology. | A disease can change the physiology the model scales, on top of age. | |
| `ped.qc_dissolution` Quality-control dissolution | Not needed | — | A QC method is not biopredictive and does not inform exposure in children. | |
| `ped.iv_pk` Intravenous PK | Optional | (replaces `core.iv_pk`) | The adult model's disposition is already verified; IV data add support but are not needed for the extrapolation. | |

### 3.7 Organ impairment (`organ_impairment.yaml`, 20 items)

*Context of use:* Predict how renal or hepatic impairment changes the drug's exposure, to support or replace an impairment study or set doses for the label.

**Renal impairment**

| Item | Status | When | Why | Note |
|---|---|---|---|---|
| `ri.fraction_excreted` Fraction excreted unchanged in urine and renal clearance | Required | — | The renal share of clearance drives the change in exposure with renal impairment. | |
| `ri.mass_balance` Mass balance (radiolabelled), metabolite profile and fraction excreted unchanged in urine | Required | (replaces `core.mass_balance`) | Every route of elimination must be known to say which one the impairment changes. | |
| `ri.filtration_vs_secretion` Filtration versus secretion, and the renal transporters involved | Conditional | The drug is actively secreted by the kidney. | Filtration and transporter-mediated secretion change differently in kidney disease; for OAT substrates the change was predicted well. | |
| `ri.fm_hepatic_extraction` Fraction metabolised per hepatic enzyme, and the hepatic extraction class | Usually | Required when model influence high (the model replaces a study or drives the label) | Kidney disease can change hepatic enzymes as well, so the non-renal routes matter too. | |
| `ri.hepatic_uptake` Hepatic uptake (OATP) | Usually | Required when model influence high (the model replaces a study or drives the label) | Hepatic uptake is part of the non-renal clearance that kidney disease can change. | |
| `ri.binding_protein` Unbound fraction and the binding protein (albumin or alpha-1-acid glycoprotein) | Usually | Required when model influence high (the model replaces a study or drives the label) | The unbound fraction changes with disease as the binding protein's level changes. | |
| `ri.uraemic_effects` Uraemic effects on hepatic enzymes and transporters | Usually | Required when model influence high (the model replaces a study or drives the label) | Uraemia can change the activity of hepatic enzymes and transporters, and with it non-renal clearance. | |
| `ri.impairment_pk` Clinical PK in renally impaired subjects | Usually | Required when model influence high (the model replaces a study or drives the label) | Impairment-arm data verify the predicted change in exposure. | |
| `ri.absorption_changes` Changes in absorption with impairment (bile salts, shunting) | Not needed | — | These changes are described for hepatic impairment, not renal. | |
| `ri.food_dissolution_ontogeny` Food, dissolution and ontogeny data | Not needed | — | An adult impairment question acts on elimination, not on the product or on maturation. | |

**Hepatic impairment**

| Item | Status | When | Why | Note |
|---|---|---|---|---|
| `hi.fraction_excreted` Fraction excreted unchanged in urine and renal clearance | Usually | Required when model influence high (the model replaces a study or drives the label) | The renal share is the part of clearance hepatic impairment leaves unchanged. | |
| `hi.mass_balance` Mass balance (radiolabelled), metabolite profile and fraction excreted unchanged in urine | Required | (replaces `core.mass_balance`) | Every route of elimination must be known to say which one the impairment changes. | |
| `hi.filtration_vs_secretion` Filtration versus secretion, and the renal transporters involved | Not needed | — | How the kidney clears the drug does not change the hepatic impairment prediction. | |
| `hi.fm_hepatic_extraction` Fraction metabolised per hepatic enzyme, and the hepatic extraction class | Required | — | Hepatic impairment changes each enzyme by its own amount, and the extraction class decides how much a change matters. | |
| `hi.hepatic_uptake` Hepatic uptake (OATP) | Conditional | The drug is an OATP substrate. | Extended-clearance behaviour differs in hepatic impairment for drugs taken up into the liver. | |
| `hi.binding_protein` Unbound fraction and the binding protein (albumin or alpha-1-acid glycoprotein) | Usually | Required when model influence high (the model replaces a study or drives the label) | The unbound fraction changes with disease as the binding protein's level changes. | |
| `hi.uraemic_effects` Uraemic effects on hepatic enzymes and transporters | Not needed | — | Uraemia belongs to kidney disease, not to hepatic impairment. | |
| `hi.impairment_pk` Clinical PK in hepatically impaired subjects, by severity | Usually | Required when model influence high (the model replaces a study or drives the label), especially for moderate and severe impairment | Predictions over-estimated the change in moderate and severe impairment, and EMA qualified a model for mild and moderate impairment only. | |
| `hi.absorption_changes` Changes in absorption with hepatic impairment (bile salts, shunting) | Optional | — | Changes in bile salts and portal shunting may alter absorption, but the evidence is at the level of hypothesis. | |
| `hi.food_dissolution_ontogeny` Food, dissolution and ontogeny data | Not needed | — | An adult impairment question acts on elimination, not on the product or on maturation. | |

### 3.8 Formulation bridging and virtual BE (PBBM) (`pbbm_bridging_vbe.yaml`, 22 items)

*Context of use:* Predict whether a changed or new oral product gives the same exposure as the reference (virtual bioequivalence, bridging, dissolution safe space), to support or replace a clinical study.

| Item | Status | When | Why | Note |
|---|---|---|---|---|
| `vbe.disposition_data` Disposition data, intravenous PK preferred, or one justified alternative | Required | (replaces `core.iv_pk`) | The product's absorption can only be isolated once disposition is known; there is no strict requirement for IV data if an alternative is justified. | |
| `vbe.solubility_vs_ph` Solubility versus pH across the physiological range, with start and final pH, buffer and any common ions | Required | — | Dissolution in each part of the gut follows the solubility at its pH, and an unreported final pH gives a wrong value. | |
| `vbe.surface_solubility` Surface solubility (surface pH) of the dissolving drug *(room field in part)* | Required | — | Using the bulk instead of the surface solubility over-predicted dissolution when dissolution limits absorption. | |
| `vbe.salt_disproportionation` Salt disproportionation (pHmax) of the salt form *(room field in part)* | Conditional | The drug substance is a salt. | A salt can convert back to the less soluble free form in the gut or the dosage form. | |
| `vbe.solid_form` Solid form of the drug substance (salt, cocrystal, polymorph or amorphous) in each batch | Usually | Required when the solid form differs between the batches or products compared, or model influence is high (the model replaces a study or drives the label) | The form sets the solubility, and a change of form can change exposure. | |
| `vbe.biorelevant_solubility` Biorelevant solubility (fasted and fed simulated gastric and intestinal fluids) | Usually | Required when the drug is lipophilic or neutral and poorly soluble, the question includes fed dosing, or model influence is high (the model replaces a study or drives the label) | Bile micelles raise the solubility of lipophilic poorly soluble drugs, which matters little when the drug is ionised in the gut. | |
| `vbe.permeability` Permeability, converted through the laboratory's calibration (never a raw in vitro value; a fitted value only with its justification) | Required | — | Fitting permeability without justification was criticised by regulators. | |
| `vbe.api_psd` Particle size distribution of the drug substance (the full distribution, the method, per clinical batch) | Conditional | Particle size is a critical material attribute or under study, or the drug is BCS class II or IV. | Particle size sets the dissolution rate of poorly soluble drugs, though the size measured before processing is a poor guide to the product's. | |
| `vbe.dose_strength` Dose and strength of each product | Required | — | The ratio of dose to solubility decides when absorption becomes limited by solubility. | |
| `vbe.functional_excipients` Amounts per dose of the functional excipients (sugar alcohols and other osmotic agents, surfactants, pH modifiers, permeation modifiers, polymers and precipitation inhibitors) | Usually | Required when the drug is BCS class III, the test and reference differ in a functional excipient, or model influence is high (the model replaces a study or drives the label) | Functional excipients change solubility, dissolution, transit or permeability, and so exposure; the rest of the excipient list is context. | |
| `vbe.polymer_effects` Amorphous solubility measured with the polymer present, and the effect of precipitation inhibitors *(room field in part)* | Conditional | The product is an amorphous solid dispersion or another supersaturating (enabling) formulation. | The polymer changes amorphous solubility, colloid formation and precipitation, so these must be measured with it present. | |
| `vbe.precipitation` Precipitation and supersaturation (two-stage or transfer test, form and size of the precipitate) *(room field in part)* | Conditional | A weak base with a pKa above about 5 whose solubility falls from gastric to intestinal pH (how large a fall is the SME's), or a supersaturating product. | Precipitation in the intestine lowers exposure; in vitro tests are mainly used to rule it out, and its rate is usually fitted to PK. | |
| `vbe.disintegration` Disintegration time (or capsule opening) *(no room field)* | Usually | Required when disintegration is slow or changes with food (how slow is the SME's), or model influence is high (the model replaces a study or drives the label) | A disintegration lag must be removed before a particle model is fitted to dissolution, or the fit is wrong. | |
| `vbe.dissolution_profiles` Dissolution profiles per batch and per medium, for the clinical batches, the reference product and any non-bioequivalent or variant batch | Required | — | The product's release in vivo is derived from these profiles, and quality-control media alone are not biopredictive. | |
| `vbe.dissolution_method` Dissolution method details (apparatus, speed, volume, medium composition and buffer capacity, pH, surfactant and its concentration, sinkers) | Required | — | A mechanistic dissolution fit needs the conditions each profile was measured under; speed and viscosity change the rate. | |
| `vbe.unit_level_dissolution` Dissolution of each unit and the number of units, not only the means | Usually | Required when the question uses f2 or the virtual trial needs between-unit variability, or model influence is high (the model replaces a study or drives the label) | Unit-level data show whether f2 may be applied and give the between-unit variability. | |
| `vbe.reference_product` Reference product dissolution and PK | Conditional | The question compares a product with a reference product. | The reference product is the reference arm of the virtual bioequivalence trial. | |
| `vbe.clinical_pk_batches` Clinical PK for several formulations or batches, ideally including a non-bioequivalent batch | Usually | Required when model influence high (the model replaces a study or drives the label) | The model must be shown to tell a bioequivalent batch from one that is not; a missing non-bioequivalent batch was a common rejection reason. | |
| `vbe.individual_pk` Individual-level PK from the bioequivalence or bridging studies | Required | — | A virtual bioequivalence trial is built and checked at the level of the subject, not the mean. | |
| `vbe.variability` Between- and within-subject variability of exposure (inter-occasion) | Required | — | Virtual populations with too little variability gave conclusions regulators questioned. | |
| `vbe.fed_state_data` Fed-state PK and dissolution | Conditional | Bioequivalence must be shown under fed dosing. | A fed bioequivalence conclusion needs a model verified under fed conditions. | |
| `vbe.fm_ddi_ontogeny` Fraction metabolised, DDI data and ontogeny | Not needed | — | A formulation comparison in the same population does not depend on which enzymes clear the drug. | |

### 3.9 pH-dependent absorption and acid-reducing agents (`acid_reducing_agents.yaml`, 7 items)

*Context of use:* Predict how raising gastric pH with an acid-reducing agent changes the exposure of a drug whose solubility depends on pH.

| Item | Status | When | Why | Note |
|---|---|---|---|---|
| `ara.gastric_solubility` Solubility over the gastric pH range reached with and without the acid-reducing agent, with the pKa | Required | — | The interaction works through the drug's lower solubility at the raised gastric pH. | |
| `ara.dissolution_ph` Dissolution at acidic and neutral pH, or in media that simulate the raised gastric pH under a proton-pump inhibitor | Required | — | A mechanistic dissolution model is needed to predict release at a gastric pH no clinical study may have tested. | |
| `ara.precipitation` Precipitation and supersaturation after gastric emptying *(room field in part)* | Usually | Required when model influence high (the model replaces a study or drives the label) | Whether the dissolved drug precipitates in the intestine changes how much an acid-reducing agent matters. | |
| `ara.salt_form_surface_ph` Salt form and the surface pH it creates as it dissolves | Conditional | The drug substance is a salt. | A salt can lessen the effect of a raised gastric pH, as in the acalabrutinib maleate case. | |
| `ara.clinical_pk_with_ara` Clinical PK with and without an acid-reducing agent (at least one study), with the agent, its dose and the timing | Usually | Required when model influence high (the model replaces a study or drives the label) | Models were only qualitatively right in the FDA case set, and EMA did not qualify one ARA interaction model. | |
| `ara.fed_fasted_pk` Fed and fasted PK | Usually | Required when model influence high (the model replaces a study or drives the label) | Fed and fasted data were used to verify the published ARA models. | |
| `ara.fm_ontogeny` Fraction metabolised and ontogeny | Not needed | — | The interaction acts on dissolution in the stomach, not on the enzymes that clear the drug. | |

### 3.10 First in human and dose prediction (`fih_dose_prediction.yaml`, 8 items)

*Context of use:* Predict human PK before the first human dose, from in vitro and preclinical data, to choose the starting dose and the escalation.

| Item | Status | When | Why | Note |
|---|---|---|---|---|
| `fih.in_vitro_clint` In vitro intrinsic clearance in human and in each preclinical species | Required | (replaces `core.in_vitro_clint`) | Human clearance is predicted bottom-up from in vitro data, and the same scaling is checked in each species first. | |
| `fih.fu_species` Fraction unbound in plasma, in human and in each preclinical species | Required | (replaces `core.fu_plasma`) | Clearance and distribution are scaled on the unbound drug in each species. | |
| `fih.solubility` Solubility (with its pH and medium) | Required | — | Oral absorption is predicted bottom-up from solubility and permeability. | |
| `fih.permeability` Permeability, converted through the laboratory's calibration | Required | — | Oral absorption is predicted bottom-up from solubility and permeability. | |
| `fih.preclinical_iv_pk` Preclinical intravenous PK in several species *(room field in part)* | Usually | Required when model influence high (the model sets the starting dose without other support) | Clearance scaling was the most common failure, and predictions came close only when it had been checked in preclinical species first. | |
| `fih.uncertainty_sensitivity` Uncertainty and sensitivity analysis of intrinsic clearance, tissue partitioning and absorption rate | Required | (replaces `core.sensitivity_analysis`) | With no human data yet, the range of plausible human exposure is part of the answer. | |
| `fih.clinical_data` Clinical data (human PK, mass balance, an external clinical dataset) | Not needed | (replaces `core.fasted_oral_pk`, `core.iv_pk`, `core.mass_balance`, `core.external_verification`, `core.sponsor_nca`) | Before the first human dose no clinical data exist yet. | |
| `fih.food_ontogeny_impairment` Food, ontogeny and organ-impairment data | Not needed | — | Food, age and impairment questions come after the first human studies. | |

### 3.11 Special populations (`special_populations.yaml`, 10 items)

*Context of use:* Predict exposure in pregnancy, in the elderly or in a specific ethnic population from a verified model of the general adult population.

**Pregnancy**

| Item | Status | When | Why | Note |
|---|---|---|---|---|
| `preg.nonpregnant_model_pathways` A verified non-pregnant model with its pathway fractions (enzymes, UGT, transporters) | Required | (replaces `core.mass_balance`) | Pregnancy changes each pathway differently, so the share of each must be known before it is scaled. | |
| `preg.gestational_physiology` Gestation-dependent physiology | Required | — | The physiology changes through gestation, and the model must follow it. | |
| `preg.same_pathway_pk` Pregnancy PK of other drugs that share the drug's pathways | Usually | Required when model influence high (the model replaces a study or drives the label) | Scarce data of this kind hampered a regulator's evaluation of a pregnancy model. | |
| `preg.placental_transfer` Placental transfer (for example cord-blood or in vitro transfer data) *(room field in part)* | Conditional | The question asks about exposure of the fetus. | Fetal exposure cannot be predicted without data on how the drug crosses the placenta. | |
| `preg.ugt_transporter_changes` Pregnancy-related changes in UGT and transporter activity | Optional | — | These changes are a recognised gap of the platforms, so a model of a drug cleared by UGT or transporters is flagged as weaker. | |

**Geriatrics**

| Item | Status | When | Why | Note |
|---|---|---|---|---|
| `ger.age_physiology` Age-informed physiology of the elderly | Required | — | The physiology changes with age, and the model must follow it. | |
| `ger.elderly_verification` PK of other drugs in the elderly, to verify the aged physiology | Usually | Required when model influence high (the model replaces a study or drives the label) | The aged physiology is verified with drugs studied in the elderly. | |
| `ger.renal_function_distribution` Distribution of renal function in the elderly population | Conditional | Renal elimination is substantial (fraction excreted unchanged above a cut-off the SME sets). | For a renally cleared drug, the spread of kidney function among the elderly shapes their exposure. | |

**Ethnicity**

| Item | Status | When | Why | Note |
|---|---|---|---|---|
| `eth.enzyme_abundance_genotype` Population-specific enzyme abundance and genotype frequencies | Usually | Required when model influence high (the model replaces a study or drives the label) | Enzyme abundance and genotype frequencies differ between populations and change clearance. | |
| `eth.probe_drug_verification` PK of a probe drug in that population, to verify the population model | Usually | Required when model influence high (the model replaces a study or drives the label) | A probe drug showed a population model under-predicting oral clearance in Japanese subjects. | |

### 3.12 Context only (stored, never an input, never missing) (`context_only.yaml`, 4 items)

*Context of use:* Material a delivery may hold that is stored as context for every context of use, never used as a model input and never reported missing.

| Item | Why it is context only | Triggers a request for | Note |
|---|---|---|---|
| `ctx.manufacturing_process` The manufacturing process and its changes (narrative, equipment, granulation route, milling, compression, coating) | The process acts on exposure only through disintegration and dissolution, which must be measured; a product particle size fitted to dissolution captures its effect. | A process change between the batches or products compared, or a process named as under study, triggers a request for the dissolution and disintegration of the affected batches and, where they exist, their clinical PK. (`vbe.dissolution_profiles`, `vbe.disintegration`, `vbe.clinical_pk_batches`) | |
| `ctx.tablet_hardness` Tablet hardness, friability, porosity and compression force | They act only through disintegration and dissolution, and serve to choose clinically relevant variant batches. | A difference between the batches or products compared triggers a request for the disintegration and dissolution of those batches. (`vbe.disintegration`, `vbe.dissolution_profiles`) | |
| `ctx.full_excipient_list` The full excipient list beyond the functional classes (kept for the qualitative and quantitative comparison of test and reference) | Only functional excipients change exposure; the full list is kept to compare test and reference qualitatively and quantitatively. | A test-versus-reference difference in a functional class (sugar alcohols, surfactants, pH modifiers, permeation modifiers, polymers), especially for a BCS class III drug, triggers a request for the amounts per dose of those excipients. (`vbe.functional_excipients`) | |
| `ctx.f2` f2 similarity factors between dissolution profiles | f2 is a regulatory comparator, not a model input: models have shown bioequivalence where f2 failed, and for BCS class III the reverse risk exists. | An f2 value without the profiles behind it triggers a request for the full profiles, unit by unit, with the method; it also flags the question of interest (which batches are compared, in which media). (`vbe.dissolution_profiles`, `vbe.unit_level_dissolution`, `vbe.dissolution_method`) | |

## 4. Open questions for the SME

### 4.1 Numbers the literature does not give (written `threshold: SME`)

Each trigger below stays "to ask" until the SME sets its number. None is written in the drafts.

| # | Question | Where it is used | What the reviews say |
|---|---|---|---|
| T1 | How large a fall in solubility, from pH 1–2 to pH 6.5, makes a weak base a precipitation risk? | `fe.precipitation`, `vbe.precipitation` | The pH points come from the PBBM review (§5 idea 7). It gives no size of fall. |
| T2 | Is a basic pKa **above 5** the right cut-off? | the same | The PBBM review says "about 5". The draft writes 5 with that source. It is the only number in any trigger. |
| T3 | Which fraction excreted unchanged makes a drug "renally eliminated"? | `tddi.renal_secretion_evidence`, `ped.renal`, `ger.renal_function_distribution` | No number in the reviews. |
| T4 | What rule infers active renal secretion from renal clearance compared with filtration (unbound fraction × GFR)? | property `renal_secretion` | The reviews name the comparison but give no margin. |
| T5 | What rule classes hepatic extraction as low, intermediate or high from blood clearance? | `fe.confidence_limits` | No number in the reviews. |
| T6 | Which age band counts as "infants"? | `ped.food_and_dosing_conditions` | The reviews speak of infants without an age. |
| T7 | What size of change counts as an adult food effect? | `ped.food_and_dosing_conditions` | No number for this purpose. |
| T8 | What disintegration time counts as "slow"? | escalation of `fe.disintegration` and `vbe.disintegration` | The PBBM review cites one example for weak-base tablets (Nakamura 2022). It is not used. |
| T9 | Above what share of BLQ samples must their handling be stated (BLQ handling escalated to required)? | escalation of `core.blq_handling` | The clinical-data review reports 5 % from Irby 2021, as a method-choice rule. It is not used as a trigger. |
| T10 | Amount-per-dose thresholds for functional excipients (sugar alcohols in particular)? | escalation of `vbe.functional_excipients`; `ctx.full_excipient_list` | The PBBM review cites a provisional no-effect level from one PBBM, marked UNVERIFIED. It is not used. |
| T11 | Should a **minor** pathway fire the substrate triggers? This would mean an fm cut-off. | `ddiv.gut_wall_metabolism` (CYP3A), `ddiv.genotype_groups` (CYP2D6/2C9/2C19) | The review's condition is "substrate", with no fm. |
| T12 | Which transporters count as polymorphic? | `tddi.transporter_genotype` (only OATP today) | The review gives SLCO1B1 as its one example. |

### 4.2 Statuses I was unsure of, or chose where the review was silent or ambiguous

| # | Item(s) | What the draft says | Why it needs a look |
|---|---|---|---|
| S1 | `core.blood_plasma_ratio` | Required | The regulatory review says R. The live core template has it OPTIONAL. |
| S2 | `core.observed_statistic` | Required | This is my reading of the clinical-data review's "must keep their statistic type". It is not a regulatory status. |
| S3 | `core.blq_handling` | Usually needed | This is my reading. PBPK papers rarely state BLQ handling, so "required" would flag almost every literature dataset. |
| S4 | `core.fasted_oral_pk` | Required | The review's core list assumes an oral drug. An IV-only drug would need an override. |
| S5 | `core.sponsor_nca` | Optional | This is my choice. It serves the NCA re-computation check, not the model. |
| S6 | `tddi.endogenous_biomarker` | Optional | The review gives "O/U". |
| S7 | `ped.qc_dissolution`, `ped.iv_pk` | Not needed; optional | The review gives "N / O" for one row covering both. The split is mine. |
| S8 | `ped.food_and_dosing_conditions` | trigger includes BCS II or IV | The review says "poorly soluble drugs". Reading that as BCS II/IV is mine. |
| S9 | `ped.disease_effects`, `ri.filtration_vs_secretion`, `hi.hepatic_uptake` | Conditional | The review marks them C without a trigger. The triggers are my readings: a patient population, active secretion, an OATP substrate. |
| S10 | `vbe.salt_disproportionation` | Conditional (salt) | The review lists it R inside the solubility row. Making it depend on a salt form is mine. |
| S11 | `vbe.solid_form`, `vbe.biorelevant_solubility`, `vbe.unit_level_dissolution`, `vbe.disintegration`, `fe.disintegration` | Usually needed | They come from the PBBM review, which gives impact levels, not statuses. I mapped HIGH or MEDIUM impact with "always extract" to U. |
| S12 | `vbe.dose_strength` | Required | Mapped from HIGH impact plus "always extract". |
| S13 | `vbe.functional_excipients` | Usually needed | The PBBM review says "always extract" the functional classes. The regulatory review gives "excipient, polymer and ASD effects" as C. U is my reconciliation. |
| S14 | `vbe.reference_product` | Conditional (a reference product in the question) | The PBBM review says HIGH for generics. A sponsor's own bridge uses its earlier formulation as the reference. |
| S15 | `ara.*` | the whole file | The review's first row is "R (weak bases)". The file assumes a drug with pH-dependent solubility. Should the CoU itself need a trigger? The review's "U / C" row is split: precipitation U, salt form C. |
| S16 | `fih.clinical_data`, `fih.food_ontogeny_impairment` | Not needed | The list of core items FIH overrides is mine. The review gives "N/O" for food, ontogeny and impairment. |
| S17 | `preg.ugt_transporter_changes` | Optional | The review gives no status, only "flag the model as weaker". What the flag looks like is open. |
| S18 | `ddip.own_fm` | Not needed | The review says "N (U if the same model is also used as a victim)". The draft relies on the victim list applying in that case. |
| S19 | Default providers | as in the live templates for overlapping core items | logP, pKa, fu and B/P default to LITERATURE (as live). Most other data default to CLIENT. The data plan overrides either. |
| S20 | Several CoUs at once | not coded | Proposed rule: the stricter status wins (R > C fired > U > O > N). Not in the reviews. |

### 4.3 Sources to treat with care

- **Li Y 2025** (PMID 41304751) is a secondary analysis by a consultancy. The regulatory review warns that some of its
  details look doubtful. Eight items cite it:
  - `ddiv.clinical_ddi_index` and `ddiv.active_metabolites`;
  - `ddip.induction_ec50_emax`, `ddip.clinical_ddi_sensitive_substrate`, `ddip.sensitivity_on_constants` and
    `ddip.metabolites_and_net_effect`;
  - `tddi.clinical_ddi_probe_inhibitor` and `tddi.intestinal_efflux`.

  Each also cites another source, except `tddi.intestinal_efflux`, which rests on Li Y 2025 alone. Check it against
  the primary FDA reviews.
- **Consensus-only records** have no PMID in the reviews: Storelli 2023, Hu 2025, Tistaert 2019, Taskar 2025, Parrott
  2024, Al-Amiry Santos 2025 and 2026, Templeton 2016, Hegde 2026. Their links are in the reviews' reference lists.
- **Guidance wording** was not re-read in the reviews (fda.gov and ema.europa.eu could not be reached). The drafts
  therefore cite guidances only through the papers that quote them.

## 5. The property vocabulary (defined once in `core.yaml`)

How each is determined:
- **"code computes it"**: computed from the room's facts and tables.
- **"read from the brief"**: taken from the confirmed brief.
- **"stated in the delivery, else asked"**: a person answers, and the reason is kept.

| Property | About | How | How it is determined | Used by |
|---|---|---|---|---|
| `weak_base` | compound | code computes it | Yes when a pKa fact is of type base; no when every pKa given is acidic or the delivery states the drug is neutral; unknown when no pKa is given. | `fe.precipitation`, `vbe.precipitation` |
| `highest_basic_pka` | compound | code computes it | The highest pKa of type base among the pKa facts, as reported; unknown when there is none. | `fe.precipitation`, `vbe.precipitation` |
| `solubility_ratio_gastric_to_intestinal` | compound | code computes it | The solubility at pH 1 to 2 divided by the solubility near pH 6.5 (the pH points of the PBBM review §5 idea 7), from solubility facts or a solubility table, as reported; unknown when either is missing. How large a fall counts is the SME's (threshold SME). | `fe.precipitation`, `vbe.precipitation` |
| `salt_form` | compound | code computes it | Yes when the salt-form fact or the brief's drug.salt_form names a salt; no when the delivery states the free acid or base; unknown otherwise. | `fe.precipitation`, `vbe.salt_disproportionation`, `ara.salt_form_surface_ph` |
| `bcs_class` | compound | read from the brief | As stated: the brief's drug.bcs_class or a BCS fact in the delivery. The room never computes a BCS class; unknown when neither states one. | `ped.food_and_dosing_conditions`, `ped.mechanistic_absorption_inputs`, `vbe.api_psd` |
| `metabolised` | compound | code computes it | Yes when the brief's scope.pathways holds hepatic_metabolism or gut_wall_metabolism, or a metabolism fact names an enzyme; no when the delivery states the drug is excreted unchanged; unknown otherwise. | `core.in_vitro_clint` |
| `metabolising_enzymes` | compound | code computes it | The enzymes the metabolism facts name, as written, with those in the brief's scope.pathways_stated; empty when the drug is stated not to be metabolised; unknown when nothing is said. | `ddiv.gut_wall_metabolism`, `ddiv.genotype_groups` |
| `modulates_own_clearance` | compound | stated in the delivery, else asked | Yes when the brief's scope.nonlinearity names auto-induction or auto-inhibition, or the delivery shows the drug inhibiting or inducing an enzyme that clears it (an interaction fact naming an enzyme of its own metabolism); asked otherwise. | `ddiv.auto_modulation` |
| `active_metabolite` | compound | stated in the delivery, else asked | Yes when the brief's scope.parent_metabolite is parent_and_metabolites, or the delivery names an active or inhibitory metabolite (a metabolism fact, or a metabolite measured as an analyte); asked otherwise. | `ddiv.active_metabolites`, `ddip.metabolites_and_net_effect` |
| `perpetrator_mechanisms` | compound | stated in the delivery, else asked | The mechanisms the interaction facts and the brief's scope.ddi state; asked when the drug is a perpetrator and no mechanism is stated. | `ddip.reversible_ki`, `ddip.tdi_kinact_ki`, `ddip.induction_ec50_emax`, `ddip.metabolites_and_net_effect` |
| `fraction_excreted_unchanged` | compound | code computes it | The fraction of the dose excreted unchanged in urine, from the excretion facts as reported; unknown when not given. Which fraction makes a drug "renally eliminated" for a trigger is the SME's (threshold SME). | `tddi.renal_secretion_evidence`, `ped.renal`, `ger.renal_function_distribution` |
| `renal_secretion` | compound | stated in the delivery, else asked | Yes when the brief's scope.pathways holds renal_secretion, or the delivery states active renal secretion or a renal transporter; asked otherwise. Inferring it by comparing renal clearance with filtration needs a rule the SME sets (threshold SME). | `tddi.renal_secretion_evidence`, `ri.filtration_vs_secretion` |
| `transporter_families` | compound | code computes it | The transporters the transporter facts name, as written (P-gp, BCRP, OATP1B1 and so on), with those in the brief's scope.pathways_stated; a family name in a trigger matches its members (OATP matches OATP1B1). | `tddi.intestinal_efflux`, `tddi.transporter_genotype`, `hi.hepatic_uptake` |
| `transporter_limited_absorption` | compound | stated in the delivery, else asked | Stated in the delivery (transporter facts with absorption data) or asked; never computed. | `fe.confidence_limits` |
| `hepatic_extraction` | compound | stated in the delivery, else asked | As the delivery states it, or computed from blood clearance by a rule the SME sets (threshold SME); unknown otherwise. | `fe.confidence_limits` |
| `in_vitro_permeability_supplied` | compound | code computes it | Yes when a permeability fact comes from an in vitro system (Caco-2, MDCK, PAMPA). | `core.permeability_calibration` |
| `individual_data_available` | question | code computes it | Yes when a concentrations table of the delivery has a subject column. | `core.actual_sampling_times`, `core.exclusions_flagged` |
| `fed_dosing_in_scope` | question | code computes it | Yes when a brief scenario's food_state is fed, a fed study is part of the question, or the question names fed dosing for the label (or that bioequivalence must be shown fed); no when every scenario is fasted; asked otherwise. | `ddiv.fed_dosing_data`, `vbe.fed_state_data` |
| `reference_product_in_question` | question | code computes it | Yes when the confirmed question card lists a product of role reference, or the brief one of role RLD or REFERENCE. | `vbe.reference_product` |
| `psd_critical_material_attribute` | product | stated in the delivery, else asked | Yes when the client's specification or the question names the drug substance's particle size as a critical material attribute or a specification under study; asked otherwise. | `vbe.api_psd` |
| `enabling_formulation` | product | stated in the delivery, else asked | Yes when the brief's scope.formulation_types holds amorphous_solid_dispersion, or the delivery describes a supersaturating product; asked when the composition shows a polymer or precipitation inhibitor. | `vbe.polymer_effects`, `vbe.precipitation` |
| `infants_in_target_population` | population | stated in the delivery, else asked | The brief's paediatric population and its age range, read against age bands the SME sets (threshold SME); asked otherwise. | `ped.food_and_dosing_conditions` |
| `food_vehicle_dosing` | question | stated in the delivery, else asked | Stated in the question or protocol, or asked: children are dosed with milk or formula, or with the dose mixed into food (apple sauce, for example). | `ped.food_and_dosing_conditions` |
| `adult_food_effect` | compound | code computes it | From a food-effect fact or an adult fed study with its fed/fasted result; what size of change counts as a food effect is the SME's (threshold SME); unknown when no fed data exist. | `ped.food_and_dosing_conditions` |
| `target_population_disease` | population | stated in the delivery, else asked | Yes when the brief's populations or the study population name patients with a disease that changes physiology; asked otherwise. | `ped.disease_effects` |
| `fetal_exposure_question` | question | stated in the delivery, else asked | Yes when the question asks about exposure of the fetus. | `preg.placental_transfer` |

## 6. What the Data room cannot place yet

These items are delivery data, but the room's vocabulary (`modeler_intake.room_specs`) has no field for them, or covers them only in part. Phase 2 would add the fields, or a table kind such as a transfer test or disintegration. System and activity items are not listed: they never come from a delivery.

| Item | Label | Room fields it has |
|---|---|---|
| `core.permeability_calibration` | The laboratory's permeability reference compounds and its calibration, with every in vitro permeability value | `field:substance.permeability` |
| `ddiv.genotype_groups` | PK by genotype group (poor, intermediate and extensive metabolisers) | `table:concentrations`, `field:adme.metabolism` |
| `tddi.abundance_scaling` | Transporter abundance and the empirical scaling factors used | none |
| `tddi.transporter_genotype` | PK by transporter genotype (for example SLCO1B1) | `table:concentrations` |
| `fe.precipitation` | Precipitation and supersaturation (two-stage or transfer test), and the full solubility profile with any common-ion effect | `table:solubility`, `field:substance.solubility`, `field:substance.salt` |
| `fe.disintegration` | Disintegration time of the product (or capsule opening), in fasted and fed media where tested | none |
| `ped.pd_target` | A pharmacodynamic or receptor-occupancy target exposure | none |
| `vbe.surface_solubility` | Surface solubility (surface pH) of the dissolving drug | `field:substance.solubility` |
| `vbe.salt_disproportionation` | Salt disproportionation (pHmax) of the salt form | `field:substance.salt`, `field:substance.solubility` |
| `vbe.polymer_effects` | Amorphous solubility measured with the polymer present, and the effect of precipitation inhibitors | `field:substance.solubility`, `table:composition` |
| `vbe.precipitation` | Precipitation and supersaturation (two-stage or transfer test, form and size of the precipitate) | `table:solubility`, `field:substance.solubility` |
| `vbe.disintegration` | Disintegration time (or capsule opening) | none |
| `ara.precipitation` | Precipitation and supersaturation after gastric emptying | `table:solubility`, `field:substance.solubility` |
| `fih.preclinical_iv_pk` | Preclinical intravenous PK in several species | `table:concentrations`, `field:study.route` |
| `preg.placental_transfer` | Placental transfer (for example cord-blood or in vitro transfer data) | `table:concentrations`, `field:study.matrix` |

## 7. What happens next

1. **The owner** reviews this document. Annotate the Note columns and answer what you can of section 4.
2. **The SME** answers the open questions. Each answer goes into the YAML, keeps the **UNVERIFIED** mark until signed,
   and bumps the draft version (`0.1-draft` → `0.2-draft`).
3. **Phase 2 wiring** (plan §6.3 and §10): the Data room shows the drafts **labelled as drafts**. It does the
   following:
   - computes the properties;
   - folds the not-needed items with their reasons;
   - keeps context-only material as context;
   - adds the missing room fields (section 6).

   **Wired on 2026-11-24** (the owner's "go ahead with all phases"; `modeler_project.dataroom.drafts` and
   `.checklist`, CHANGELOG): the room reads the applications from the confirmed question card (a decision a person
   confirms), computes the properties code can, shows the checklist with its coverage ledger (found, missing with the
   files searched, not needed and why, context only, for a person to check) and asks for each missing required or
   usually-needed item in its **own** data requests, each marked "(draft requirement, UNVERIFIED)". No data plan, gate
   or live template reads the drafts; the missing room fields of section 6 are still to add.
4. **Promotion to templates** is a locked-file change to `pbpk_domain/requirements/*.yaml`, in its own PR, with the
   owner's approval, a CHANGELOG entry and a version bump. The PK-Sim locations are harvested from the engine at that
   point, never written by hand.
