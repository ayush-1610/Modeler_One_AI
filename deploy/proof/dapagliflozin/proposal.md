# MOCK technical proposal — PBPK model of dapagliflozin (T-56 software proof)

> **This is a mock document written for the T-56 end-to-end proof of Modeler One.** It is not a client proposal and
> states no values: every number in the project comes from a cited source (the published OSP Dapagliflozin model and
> the clinical studies it cites) during the run.

## 1. Objective

Develop and qualify a physiologically based pharmacokinetic (PBPK) model of dapagliflozin in PK-Sim (Open Systems
Pharmacology Suite) to support a food-effect statement for a 10 mg immediate-release (IR) tablet in healthy adults.

## 2. Question of interest and context of use

Question: what is the effect of a meal on dapagliflozin exposure (AUC, Cmax) after a single 10 mg IR tablet?
Context of use: the model predicts fed versus fasted exposure of the 10 mg IR tablet in healthy adults to support the
food-effect section of the label discussion. It does not replace a clinical food-effect study.

## 3. Product

Test product: dapagliflozin 10 mg IR tablet (TEST).

## 4. Scenarios

- Healthy adults, single oral dose of 10 mg, fasted.
- Healthy adults, single oral dose of 10 mg, fed.

## 5. Data

- The client provides the dissolution profiles of the 10 mg tablet and one fed pharmacokinetic study.
- Everything else (physicochemical properties, binding, elimination pathways, intravenous and oral clinical
  pharmacokinetics) comes from the published literature.

## 6. Elimination

Dapagliflozin is cleared mainly by UGT1A9 glucuronidation, with a renal contribution (glomerular filtration).

## 7. Deliverables

The PBPK model, the Modeling Analysis Report (MAR) and the model package.
