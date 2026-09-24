// Typed example data for the screens whose GET endpoints are not built yet (the backend exposes the POST
// actions — map:generate, campaigns, escalations, signatures — but no read APIs for projects/CPF yet).
// These shapes mirror the backend domain models so swapping to real fetches is a drop-in change.

import type { Rating } from "@/lib/api";

export type Project = { id: string; name: string; compounds: string[]; openQuestions: number; risk: Rating };
export type ProjectDetail = Project & { questions?: Question[] };

export type CpfParameter = {
  id: string;
  value: string | null;
  unit: string | null;
  status: string; // CPF status: fixed | fitted | predicted | derived
  source: string; // provenance source_type (drives the provenance chip)
  reference: string;
  fittableStages: string[];
};

// provenance sources that count as measured / literature evidence (vs fitted or predicted)
export const MEASURED_SOURCES = ["measured", "Publication", "Database", "Other"];

export type Compound = {
  name: string;
  project: string;
  version: number;
  completeness: number; // 0..1 (S0 readiness)
  parameters: CpfParameter[];
};

export type Question = {
  id: string;
  question: string;
  application: string;
  modelRisk: Rating | null;
  stage: "planning" | "evaluation" | "reporting" | "signed";
  failingCriteria: number;
};

export type Round = {
  round: number;
  action: string;
  aucGmfe: number | null;
  cmaxGmfe: number | null;
  verdict: string;
};

export type Stage = {
  stage: string;
  label: string;
  status: "RUNNING" | "PASSED" | "ACCEPTED" | "SKIPPED" | "ESCALATED" | "ABORTED" | "FAILED" | "PENDING";
  rounds: Round[];
  notes?: string[]; // why a stage was skipped, studies it could not simulate, what the build deferred
};

export type Campaign = {
  id: string;
  project?: string;
  status?: string; // QUEUED | RUNNING | COMPLETED | ESCALATED (from the runner)
  compound: string;
  question: string;
  modelRisk: Rating;
  budgetSeconds: number;
  elapsedSeconds: number;
  currentStage: string;
  stages: Stage[];
};

export type GofSeries = { name: string; time_h: number[]; concentration: number[]; unit: string; kind: "simulated" | "observed" };

// The campaign monitor's full read view: the campaign plus its goodness-of-fit series.
// S6: sensitivity ranking and prediction intervals per study; S7: the package record (no server paths are shown).
export type Band = { p5: number; p50: number; p95: number; n: number };
export type Prediction = {
  sensitivity?: Record<string, { parameter: string; pk_parameter: string; value: number }[]>;
  intervals?: Record<string, { AUC?: Band; Cmax?: Band }>;
  notes?: string[];
};
export type PackageRecord = {
  exportable: boolean;
  reproduction?: { passes: boolean; compared: number; failures: { path: string; status: string; detail?: string }[] };
  report?: Record<string, string>;
  data_bundle_sha256?: string;
  package_sha256?: string;
  files?: number;
  report_notes?: string[];
};
export type CampaignDetail = Campaign & { gof?: GofSeries[]; prediction?: Prediction | null; package?: PackageRecord | null };

export type Escalation = {
  id: string;
  campaignId: string;
  stage: string;
  reasonCode: string;
  evidence: string;
  options: { id: string; label: string; requiresSignature: boolean }[];
};

export type Proposal = {
  id: string;
  parameterId: string;
  value: string;
  unit: string | null;
  quote: string;
  reference: string;
  agent: string;
};

export const PROJECTS: Project[] = [
  { id: "example-a", name: "Example-A program", compounds: ["Example-A"], openQuestions: 2, risk: "high" },
  { id: "renal-drug", name: "RenalDrug FIH", compounds: ["RenalDrug"], openQuestions: 1, risk: "medium" },
];

export const QUESTIONS: Question[] = [
  { id: "qoi-1", question: "AUC ratio of Example-A with itraconazole 200 mg QD; label dose adjustment?",
    application: "DDI (CYP3A4)", modelRisk: "high", stage: "evaluation", failingCriteria: 1 },
  { id: "qoi-2", question: "Dose for children 2 to <6 years matching adult AUC",
    application: "Pediatric extrapolation", modelRisk: "medium", stage: "planning", failingCriteria: 0 },
];

export const COMPOUND: Compound = {
  name: "Example-A",
  project: "example-a",
  version: 4,
  completeness: 0.86,
  parameters: [
    { id: "phys.mw", value: "300.0", unit: "g/mol", status: "measured", source: "Publication", reference: "Smith 2019", fittableStages: [] },
    { id: "phys.logp", value: "2.5", unit: "Log Units", status: "fitted", source: "ParameterIdentification", reference: "S1 round 3", fittableStages: ["S1"] },
    { id: "bind.fu", value: "0.12", unit: "", status: "measured", source: "Publication", reference: "Smith 2019", fittableStages: ["S1"] },
    { id: "phys.solubility.ref", value: "1.4", unit: "mg/ml", status: "measured", source: "Database", reference: "OSP DB", fittableStages: ["S2"] },
    { id: "perm.intestinal", value: "3.1e-6", unit: "cm/min", status: "fitted", source: "ParameterIdentification", reference: "S2 round 2", fittableStages: ["S2"] },
    { id: "elim.hepatic.CYP3A4.clspec", value: "0.8", unit: "l/µmol/min", status: "fitted", source: "ParameterIdentification", reference: "S1 round 4", fittableStages: ["S1", "S2"] },
    { id: "elim.renal.gfr_fraction", value: "1.0", unit: "", status: "predicted", source: "assumed", reference: "GFR assumption", fittableStages: ["S1"] },
  ],
};

const t = [0, 0.25, 0.5, 1, 1.5, 2, 3, 4, 6, 8, 12, 24];
export const GOF: GofSeries[] = [
  { name: "Predicted (S2)", unit: "µmol/l", kind: "simulated", time_h: t,
    concentration: [0, 8, 22, 38, 41, 36, 27, 20, 11, 6.2, 2.1, 0.35] },
  { name: "Observed", unit: "µmol/l", kind: "observed", time_h: [0.5, 1, 2, 4, 8, 24],
    concentration: [24, 40, 34, 19, 6.6, 0.4] },
];

export const CAMPAIGN: Campaign = {
  id: "camp-101",
  compound: "Example-A",
  question: "AUC ratio of Example-A with itraconazole 200 mg QD; label dose adjustment?",
  modelRisk: "high",
  budgetSeconds: 3600,
  elapsedSeconds: 2340,
  currentStage: "S3",
  stages: [
    { stage: "S0", label: "Readiness", status: "PASSED", rounds: [] },
    { stage: "S1", label: "IV disposition", status: "PASSED", rounds: [
      { round: 1, action: "fit elim.hepatic.CYP3A4.clspec", aucGmfe: 1.42, cmaxGmfe: 1.31, verdict: "improved" },
      { round: 2, action: "fit phys.logp", aucGmfe: 1.08, cmaxGmfe: 1.12, verdict: "passed" },
    ] },
    { stage: "S2", label: "Oral fasted", status: "PASSED", rounds: [
      { round: 1, action: "fit perm.intestinal", aucGmfe: 1.21, cmaxGmfe: 1.5, verdict: "improved" },
      { round: 2, action: "fit phys.solubility.ref", aucGmfe: 1.05, cmaxGmfe: 1.09, verdict: "passed" },
    ] },
    { stage: "S3", label: "Formulation / fed", status: "RUNNING", rounds: [
      { round: 1, action: "fit food.fed_solubility_factor", aucGmfe: 1.33, cmaxGmfe: 1.28, verdict: "improved" },
    ] },
    { stage: "S4", label: "Internal validation", status: "PENDING", rounds: [] },
    { stage: "S5", label: "External validation", status: "PENDING", rounds: [] },
  ],
};

export const ESCALATIONS: Escalation[] = [
  { id: "esc-1", campaignId: "camp-101", stage: "S3", reasonCode: "MAX_ROUNDS_NO_PASS",
    evidence: "Stage S3 reached its max rounds without passing the fed AUC criterion (GMFE 1.33).",
    options: [
      { id: "retry", label: "Retry with a wider bound", requiresSignature: false },
      { id: "accept_best", label: "Accept the best round", requiresSignature: true },
      { id: "abort", label: "Abort the stage", requiresSignature: true },
    ] },
];

export const PROPOSALS: Proposal[] = [
  { id: "prop-1", parameterId: "phys.logp", value: "2.5", unit: "Log Units",
    quote: "measured log P of 2.5", reference: "doi:10.1000/example (Table 2)", agent: "parameter_curation" },
  { id: "prop-2", parameterId: "bind.fu", value: "0.12", unit: "",
    quote: "fraction unbound in plasma was 12%", reference: "doi:10.1000/example (p. 4)", agent: "parameter_curation" },
];
